"""Wave 4, 2026-09-13 — images inside extracted documents are kept, fetched once,
handed to the web, and referenced.

⛔⛔ WHAT WAS WRONG. `html_to_markdown` passed `strip=['img', …]`, so every HTML
capture route deleted every image and its alt text, and nothing anywhere fetched a
byte. The routes that keep a platform's own markdown kept its URLs, which a reader
could not load.

⭐⭐ WHAT THIS FILE PROVES, and how:
  · the converter, the rewrite of every markdown form, the byte checks, the address
    checks, the redirect walk, the byte cap, the upload and the funnel are all
    EXECUTED — real markdownify, real requests/urllib3 plumbing, no network: a fake
    resolver, a fake socket peer, a fake session, a fake web.
  · the per-agent save (`extract_and_record_agent`) is EXECUTED end to end: its
    local .md, its Firestore content and the text it hands back all carry refs.
  · the brief saves, the finalize re-save, the two regen re-saves and the
    consolidated build live inside `run_pipeline` (~4,000 lines, a browser, a
    queue) and cannot be executed here, so they are SOURCE-PINNED on `code_only`
    text: the statement feeding each write is the rehost, and the count of saves is
    pinned so a new, unfunneled one fails. `_rehost_result_texts`, which those loops
    call, is executed below.
  · the panel TRACKER's opt-out is source-pinned too: executing
    `_read_claude_artifact_panel` needs a live frame tree.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import hashlib
import re
import struct
import time
import types
from email.message import Message

import pytest
import requests
import urllib3.connection

import research as R
from conftest import code_only  # type: ignore

RID = "rid_0913-A"
UID = "uid-owner-1"
REF_RE = re.compile(r"/document-images/([A-Za-z0-9_-]{1,128})/([a-f0-9]{64})\.(png|jpg|gif|webp)")


# ── image bytes built by hand, so the checks are measured against known headers ──

def png(w=100, h=60, ihdr=b"IHDR"):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr
            + struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0) + b"\x00\x00\x00\x00")


def gif(w=100, h=60, version=b"89a"):
    return b"GIF" + version + struct.pack("<HH", w, h) + b"\x00\x00\x00"


def jpeg(w=100, h=60, sof=True):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    out = b"\xff\xd8" + app0
    if sof:
        out += b"\xff\xc0" + struct.pack(">HBHH", 17, 8, h, w) + b"\x03" + b"\x00" * 9
    else:
        out += b"\xff\xda" + struct.pack(">H", 4) + b"\x00\x00" + b"\x00" * 12
    return out


def webp_vp8x(w=100, h=60):
    return (b"RIFF" + struct.pack("<I", 30) + b"WEBP" + b"VP8X" + struct.pack("<I", 10)
            + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


def webp_vp8l(w=100, h=60):
    bits = (w - 1) | ((h - 1) << 14)
    return (b"RIFF" + struct.pack("<I", 30) + b"WEBP" + b"VP8L" + struct.pack("<I", 10)
            + b"\x2f" + bits.to_bytes(4, "little") + b"\x00" * 5)


def webp_vp8(w=100, h=60):
    return (b"RIFF" + struct.pack("<I", 30) + b"WEBP" + b"VP8 " + struct.pack("<I", 10)
            + b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", w, h) + b"\x00" * 4)


def _independent_ext(data: bytes) -> str:
    """The fake web's own sniff — deliberately NOT the code under test."""
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF8"):
        return "gif"
    return "webp"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ref_for(data: bytes, rid: str = RID) -> str:
    return f"/document-images/{rid}/{sha(data)}.{_independent_ext(data)}"


class FakeWebResponse:
    def __init__(self, status=200, body=None, raise_json=False):
        self.status_code = status
        self._body = body
        self._raise = raise_json

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._body


# ── the world: a research, a token, a fake fetch, a fake web, a captured log ────

@pytest.fixture
def world(monkeypatch):
    w = types.SimpleNamespace(images={}, fetches=[], posts=[], logs=[], token_calls=0,
                              web=None, fetch_delay=0.0)
    monkeypatch.setattr(R, "_fb_uid", UID)
    monkeypatch.setattr(R, "_fb_research_id", RID)
    monkeypatch.setattr(R, "_doc_img_cache", collections.OrderedDict())
    monkeypatch.setattr(R, "_doc_img_decorative_pending", 0)
    monkeypatch.setattr(R, "_doc_img_resolve_host", lambda host, port: ["93.184.216.34"])

    def token():
        w.token_calls += 1
        return "tok-1"
    monkeypatch.setattr(R, "_fresh_user_mode_id_token", token)

    def fetch(url, deadline):
        w.fetches.append(url)
        if w.fetch_delay:
            time.sleep(w.fetch_delay)
        if url in w.images:
            got = w.images[url]
            if isinstance(got, BaseException):
                raise got
            return got
        R._doc_img_check_url(url)  # the real URL rules refuse non-https forms
        raise R._DocImageRefused("failed")
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)

    def post(url, headers=None, json=None, timeout=None, allow_redirects=True, **kw):
        w.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout,
                        "allow_redirects": allow_redirects})
        if w.web is not None:
            return w.web(json)
        data = base64.b64decode(json["data_base64"])
        return FakeWebResponse(200, {"ref": ref_for(data, json["research_id"])})
    monkeypatch.setattr(requests, "post", post)

    monkeypatch.setattr(R, "log", lambda msg, level="INFO": w.logs.append((level, msg)))
    return w


def rehost(text, label="ChatGPT"):
    return asyncio.run(R._rehost_document_images(text, label))


# ═══ 1. the reference form mirrors the web's contract ═══════════════════════════

@pytest.mark.parametrize("ref", [
    "/document-images/abc/" + "a" * 64 + ".png",
    "/document-images/A_b-9/" + "0123456789abcdef" * 4 + ".jpg",
    "/document-images/" + "x" * 128 + "/" + "f" * 64 + ".gif",
    "/document-images/r/" + "e" * 64 + ".webp",
])
def test_the_ref_regex_accepts_the_contract_form(ref):
    assert R._DOC_IMG_REF_RE.match(ref)


@pytest.mark.parametrize("ref", [
    "/document-images/abc/" + "A" * 64 + ".png",
    "/document-images/abc/" + "a" * 63 + ".png",
    "/document-images/abc/" + "a" * 64 + ".svg",
    "/document-images/abc/" + "a" * 64 + ".jpeg",
    "/document-images/a.c/" + "a" * 64 + ".png",
    "/document-images/" + "x" * 129 + "/" + "a" * 64 + ".png",
    "x/document-images/abc/" + "a" * 64 + ".png",
    "/document-images/abc/" + "a" * 64 + ".png?x=1",
    "/document-images/abc/" + "a" * 64 + ".png\n",
    "https://superresearch.io/document-images/abc/" + "a" * 64 + ".png",
])
def test_the_ref_regex_refuses_anything_else(ref):
    """⛔ The trailing-newline case is the Python `$` trap: `^…$` matches before a
    final newline, the web's anchored JS regex does not."""
    assert not R._DOC_IMG_REF_RE.match(ref)


# ═══ 2. the converter keeps images ═════════════════════════════════════════════

def test_the_converter_keeps_an_image_and_its_alt():
    out = R.html_to_markdown('<p>Revenue <img src="https://cdn.example.com/chart.png" '
                             'alt="Revenue by year"></p>')
    assert "![Revenue by year](<https://cdn.example.com/chart.png>)" in out


def test_images_inside_links_headings_and_table_cells_survive():
    """markdownify's own convert_img returns the bare alt inside a heading or a
    cell unless the DIRECT parent is listed — a linked image in a cell was lost."""
    out = R.html_to_markdown(
        '<h2><img src="https://c.example.com/h.png" alt="Heading pic"> Title</h2>'
        '<table><tr><th>h</th></tr><tr><td><a href="https://x.example.com">'
        '<img src="https://c.example.com/cell.png" alt="Cell pic"></a></td></tr></table>')
    assert "![Heading pic](<https://c.example.com/h.png>)" in out
    assert "[![Cell pic](<https://c.example.com/cell.png>)](https://x.example.com)" in out


@pytest.mark.parametrize("tag", [
    '<img src="https://c.example.com/i.png" alt="d" width="16">',
    '<img src="https://c.example.com/i.png" alt="d" height="32">',
    '<img src="https://c.example.com/i.png" alt="d" width="24px">',
    '<img src="https://c.example.com/i.png" alt="d" style="height: 20px">',
    '<img src="https://c.example.com/i.png" alt="d" aria-hidden="true">',
    '<img src="https://c.example.com/i.png" alt="d" role="presentation">',
    '<img src="https://www.google.com/s2/favicons?domain=x.com&sz=64" alt="d">',
    '<img src="https://t0.gstatic.com/faviconV2?client=SOCIAL&url=x" alt="d">',
    '<img src="https://icons.duckduckgo.com/ip3/x.com.ico" alt="d">',
    '<img src="https://x.example.com/favicon.ico" alt="d">',
])
def test_decorative_images_are_dropped_before_conversion(tag, monkeypatch):
    monkeypatch.setattr(R, "_doc_img_decorative_pending", 0)
    out = R.html_to_markdown(f"<p>Body text {tag}</p>")
    assert "![" not in out and "example.com" not in out and "gstatic" not in out
    assert R._doc_img_decorative_pending == 1


@pytest.mark.parametrize("attrs", [
    'width="33"', 'height="100%"', 'style="max-width: 10px"', 'role="img"', 'aria-hidden="false"',
])
def test_content_images_at_the_decorative_boundary_are_kept(attrs, monkeypatch):
    monkeypatch.setattr(R, "_doc_img_decorative_pending", 0)
    out = R.html_to_markdown(f'<p>x <img src="https://c.example.com/k.png" alt="k" {attrs}></p>')
    assert "![k](<https://c.example.com/k.png>)" in out
    assert R._doc_img_decorative_pending == 0


def test_a_src_with_spaces_or_parens_stays_one_destination(world):
    """Unbracketed, `a (1) b.png` ends the destination at the space and half a
    platform URL is left in the text where no parser sees an image."""
    url = "https://c.example.com/a (1) b.png"
    md = R.html_to_markdown(f'<p><img src="{url}" alt="Spaced"></p>')
    assert md == f"![Spaced](<{url}>)"
    world.images[url] = png()
    out = rehost(md)
    assert world.fetches == [url]
    assert out == f"![Spaced]({ref_for(png())})"


def test_alt_brackets_and_pipes_are_escaped_so_the_image_stays_parseable():
    out = R.html_to_markdown('<table><tr><th>h</th></tr><tr><td>'
                             '<img src="https://c.example.com/a.png" alt="Q[1] | Q2"></td></tr></table>')
    assert "![Q\\[1\\] \\| Q2](<https://c.example.com/a.png>)" in out


@pytest.mark.parametrize("tag,expected", [
    ('<img src="https://c.example.com/a&gt;b.png" alt="Odd">', "![Odd]()"),
    ('<img alt="No source">', "![No source]()"),
    ('<img src="">', ""),
])
def test_an_unrepresentable_or_missing_src_becomes_a_caption(tag, expected):
    assert R.html_to_markdown(f"<p>{tag}</p>") == expected


def test_the_opt_out_is_the_old_output():
    html = '<p>A <img src="https://c.example.com/x.png" alt="Gone"> B</p><h2>T</h2>'
    old = R.html_to_markdown(html, keep_images=False)
    assert "![" not in old and "Gone" not in old and "x.png" not in old
    assert old.startswith("A") and "## T" in old


def test_the_panel_tracker_opts_out_and_the_capture_routes_do_not():
    """SOURCE PIN (executing the panel reader needs a live frame tree). The tracker's
    markdown is never saved: its length is `partial_text_len` (the length-sanity
    rejection's input) and its https harvest is the source list."""
    tracker = code_only(R._read_claude_artifact_panel)
    assert tracker.count("html_to_markdown(html_blob, keep_images=False)") == 2
    assert "html_to_markdown(html_blob)" not in tracker
    for fn in (R._extract_html_to_md, R._extract_html_to_md_anyframe, R._copy_via_hijack):
        src = code_only(fn)
        assert "html_to_markdown(html)" in src, fn.__name__
        assert "keep_images" not in src, fn.__name__


# ═══ 3. every markdown form is rewritten ═══════════════════════════════════════

def test_an_inline_image_with_a_title_gets_the_ref_the_web_returned(world):
    url = "https://img.example.com/chart.png"
    world.images[url] = png()
    out = rehost(f'Intro ![Chart one]({url} "The title") outro')
    assert out == f"Intro ![Chart one]({ref_for(png())}) outro"


def test_an_angle_bracket_destination_is_rewritten(world):
    url = "https://img.example.com/a b.png"
    world.images[url] = gif()
    out = rehost(f"![G](<{url}>)")
    assert out == f"![G]({ref_for(gif())})"


def test_reference_style_images_become_inline_refs_and_their_definitions_go(world):
    world.images["https://img.example.com/1.png"] = png(200, 100)
    world.images["https://img.example.com/2.png"] = jpeg()
    world.images["https://img.example.com/3.png"] = webp_vp8x()
    text = ('Full ![First][fig one] collapsed ![Second][] shortcut ![Third]\n\n'
            '[Fig  One]: https://img.example.com/1.png "T"\n'
            '[second]: <https://img.example.com/2.png>\n'
            '[third]: https://img.example.com/3.png\n'
            'after\n')
    out = rehost(text)
    assert out == (f"Full ![First]({ref_for(png(200, 100))}) collapsed ![Second]({ref_for(jpeg())}) "
                   f"shortcut ![Third]({ref_for(webp_vp8x())})\n\nafter\n")


def test_a_definition_only_a_link_uses_stays(world):
    text = "See [the site][s].\n\n[s]: https://example.com/page\n"
    assert rehost(text) == text
    assert world.fetches == []


def test_a_shortcut_with_no_definition_is_text_not_an_image(world):
    text = "Note ![not an image] here."
    assert rehost(text) == text
    assert world.fetches == []


def test_an_escaped_bang_is_not_an_image(world):
    text = r"literal \![x](https://img.example.com/e.png)"
    assert rehost(text) == text
    assert world.fetches == []


def test_a_data_uri_is_decoded_locally_and_never_left(world):
    data = png(64, 64)
    uri = "data:image/png;base64," + base64.b64encode(data).decode()
    out = rehost(f"![Inline]({uri})")
    assert out == f"![Inline]({ref_for(data)})"
    assert world.fetches == []
    assert base64.b64decode(world.posts[0]["json"]["data_base64"]) == data


@pytest.mark.parametrize("uri", [
    "data:image/svg+xml;base64," + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>").decode(),
    "data:image/png," + "%89PNG",
    "data:image/png;base64,!!!notbase64!!!",
])
def test_a_data_uri_that_is_not_a_stored_raster_is_captioned(world, uri):
    out = rehost(f"![Vector]({uri})")
    assert out == "![Vector]()"
    assert "data:" not in out and world.posts == []


def test_an_unused_data_uri_definition_is_removed(world):
    text = "Body.\n\n[blob1]: data:image/png;base64,AAAA\n"
    out = rehost(text + "![x](https://img.example.com/missing.png)")
    assert "data:" not in out


def test_a_raw_html_img_in_markdown_is_rehosted(world):
    url = "https://img.example.com/raw.png?a=1&b=2"
    world.images[url] = png()
    out = rehost("Before <IMG alt='Raw &amp; ready' src=\"https://img.example.com/raw.png?a=1&amp;b=2\"> after "
                 '<img src="https://www.google.com/s2/favicons?domain=x" alt="fav">')
    assert out == f"Before ![Raw & ready]({ref_for(png())}) after "
    assert world.fetches == [url]


def test_not_kept_with_alt_is_an_empty_destination_and_without_alt_is_removed(world):
    out = rehost("a ![Kept caption](https://img.example.com/nope.png) b ![](https://img.example.com/nope2.png) c")
    assert out == "a ![Kept caption]() b  c"


@pytest.mark.parametrize("dest", [
    "blob:https://chatgpt.com/1234", "sandbox:/mnt/data/chart.png", "http://img.example.com/a.png",
    "/relative/a.png", "file:///etc/passwd", "attachment://x.png",
    "https://user:pw@img.example.com/a.png", "https://img.example.com:8443/a.png",
])
def test_no_platform_or_unsafe_url_survives(world, dest):
    out = rehost(f"x ![Figure]({dest}) y")
    assert out == "x ![Figure]() y"
    assert world.posts == []


# ═══ 4. idempotent, fetched once, cached per research ══════════════════════════

def test_a_reference_to_this_research_is_left_alone_without_a_fetch(world):
    ref = f"/document-images/{RID}/{'b' * 64}.png"
    text = f"![Done]({ref})"
    assert rehost(text) == text
    assert world.fetches == [] and world.posts == [] and world.token_calls == 0


def test_a_reference_to_another_research_is_not_trusted(world):
    out = rehost(f"![Other](/document-images/someone_else/{'b' * 64}.png)")
    assert out == "![Other]()"


def test_the_same_image_twice_in_one_document_is_fetched_once(world):
    url = "https://img.example.com/twice.png"
    world.images[url] = png()
    out = rehost(f"![a]({url}) and ![b]({url})")
    assert world.fetches == [url] and len(world.posts) == 1
    assert out.count(ref_for(png())) == 2


def test_a_second_document_of_the_research_reuses_without_fetching(world):
    url = "https://img.example.com/shared.png"
    world.images[url] = png()
    rehost(f"![a]({url})", "ChatGPT")
    out = rehost(f"other doc ![b]({url})", "Gemini")
    assert world.fetches == [url] and len(world.posts) == 1
    assert out == f"other doc ![b]({ref_for(png())})"


def test_another_research_fetches_its_own_copy(world, monkeypatch):
    url = "https://img.example.com/shared.png"
    world.images[url] = png()
    rehost(f"![a]({url})")
    monkeypatch.setattr(R, "_fb_research_id", "rid_other")
    out = rehost(f"![a]({url})")
    assert world.fetches == [url, url]
    assert out == f"![a]({ref_for(png(), 'rid_other')})"


def test_a_failed_image_is_not_refetched_by_the_next_document(world):
    url = "https://img.example.com/broken.png"
    world.images[url] = R._DocImageRefused("failed")
    assert rehost(f"![x]({url})") == "![x]()"
    assert rehost(f"again ![x]({url})") == "again ![x]()"
    assert world.fetches == [url]


def test_the_consolidated_report_reuses_refs_without_refetching(world):
    """The pipeline glues the agents' texts into the consolidated report AFTER the
    finalize funnel. Built here exactly the way the pipeline builds it."""
    for i in range(3):
        world.images[f"https://img.example.com/{i}.png"] = png(100 + i, 60)
    world.images["https://img.example.com/common.png"] = gif()
    results = {n: {"text": f"{n} ![own](https://img.example.com/{i}.png) "
                           f"![common](https://img.example.com/common.png)"}
               for i, n in enumerate(["ChatGPT", "Gemini", "Claude"])}
    asyncio.run(R._rehost_result_texts(results))
    assert len(world.fetches) == 4 and len(world.posts) == 4
    parts = ["# Consolidated Research Report: topic\n"]
    for name in ["ChatGPT", "Gemini", "Claude"]:
        parts.append(f"\n## {name} Research\n\n{results[name]['text']}")
    consolidated = rehost("\n".join(parts), "Consolidated")
    assert len(world.fetches) == 4 and len(world.posts) == 4
    assert "img.example.com" not in consolidated
    assert consolidated.count(ref_for(gif())) == 3


def test_the_cache_is_bounded_per_research_and_across_researches(world, monkeypatch):
    monkeypatch.setattr(R, "_DOC_IMG_CACHE_PER_RUN", 2)
    monkeypatch.setattr(R, "_DOC_IMG_CACHE_RUNS", 2)
    for i in range(3):
        world.images[f"https://img.example.com/c{i}.png"] = png(100 + i)
    rehost(" ".join(f"![x](https://img.example.com/c{i}.png)" for i in range(3)))
    assert len(R._doc_img_cache[f"{UID}\x00{RID}"]) == 2
    for rid in ("r2", "r3"):
        monkeypatch.setattr(R, "_fb_research_id", rid)
        rehost("![x](https://img.example.com/c0.png)")
    assert list(R._doc_img_cache) == [f"{UID}\x00r2", f"{UID}\x00r3"]


# ═══ 5. limits ═════════════════════════════════════════════════════════════════

def test_at_most_40_fetches_per_document(world):
    urls = [f"https://img.example.com/n{i}.png" for i in range(45)]
    for i, u in enumerate(urls):
        world.images[u] = png(100 + i)
    out = rehost(" ".join(f"![i{i}]({u})" for i, u in enumerate(urls)))
    assert len(world.fetches) == 40
    assert out.count("/document-images/") == 40 and out.count("]()") == 5


def test_a_spent_deadline_fetches_nothing(world, monkeypatch):
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.0)
    world.images["https://img.example.com/a.png"] = png()
    assert rehost("![a](https://img.example.com/a.png)") == "![a]()"
    assert world.fetches == []


def test_no_token_means_no_fetch_and_a_caption(world, monkeypatch):
    monkeypatch.setattr(R, "_fresh_user_mode_id_token", lambda: None)
    world.images["https://img.example.com/a.png"] = png()
    assert rehost("![a](https://img.example.com/a.png)") == "![a]()"
    assert world.fetches == [] and world.posts == []


def test_the_token_is_asked_once_per_document(world):
    for i in range(3):
        world.images[f"https://img.example.com/t{i}.png"] = png(100 + i)
    rehost(" ".join(f"![t](https://img.example.com/t{i}.png)" for i in range(3)))
    assert world.token_calls == 1
    assert all(p["headers"] == {"Authorization": "Bearer tok-1"} for p in world.posts)


@pytest.mark.parametrize("uid,rid", [(None, RID), (UID, None), ("", "")])
def test_legacy_mode_without_a_research_fetches_nothing(world, monkeypatch, uid, rid):
    monkeypatch.setattr(R, "_fb_uid", uid)
    monkeypatch.setattr(R, "_fb_research_id", rid)
    world.images["https://img.example.com/a.png"] = png()
    assert rehost("![a](https://img.example.com/a.png)") == "![a]()"
    assert world.fetches == [] and world.token_calls == 0


# ═══ 6. the upload ═════════════════════════════════════════════════════════════

def test_the_upload_posts_the_contract_body_to_the_web(world):
    from auth.v2_flow import FE_BASE_URL
    data = jpeg(300, 200)
    world.images["https://img.example.com/j.jpg"] = data
    rehost("![j](https://img.example.com/j.jpg)")
    (p,) = world.posts
    assert p["url"] == f"{FE_BASE_URL}/api/document-images"
    assert p["headers"] == {"Authorization": "Bearer tok-1"}
    assert set(p["json"]) == {"ownerUid", "research_id", "data_base64"}
    assert p["json"]["ownerUid"] == UID and p["json"]["research_id"] == RID
    assert base64.b64decode(p["json"]["data_base64"]) == data
    assert p["allow_redirects"] is False and p["timeout"]


def test_the_owner_and_research_are_read_at_call_time(world, monkeypatch):
    world.images["https://img.example.com/a.png"] = png()
    world.images["https://img.example.com/b.png"] = gif()
    rehost("![a](https://img.example.com/a.png)")
    monkeypatch.setattr(R, "_fb_uid", "uid-two")
    monkeypatch.setattr(R, "_fb_research_id", "rid_two")
    rehost("![b](https://img.example.com/b.png)")
    assert [(p["json"]["ownerUid"], p["json"]["research_id"]) for p in world.posts] == [
        (UID, RID), ("uid-two", "rid_two")]


@pytest.mark.parametrize("status", [404, 401, 413, 500, 302, 201])
def test_a_web_answer_other_than_200_is_a_caption(world, status):
    """404 `not_available` is the web's answer until THE DEPLOY — expected, and it
    must degrade to captions."""
    world.images["https://img.example.com/a.png"] = png()
    world.web = lambda body: FakeWebResponse(status, {"error": "not_available",
                                                      "ref": ref_for(png())})
    assert rehost("![a](https://img.example.com/a.png)") == "![a]()"


@pytest.mark.parametrize("make", [
    lambda d: FakeWebResponse(200, {"ref": "https://storage.example.com/x.png"}),
    lambda d: FakeWebResponse(200, {"ref": ref_for(d, "rid_someone_else")}),
    lambda d: FakeWebResponse(200, {"ref": f"/document-images/{RID}/{'0' * 64}.png"}),
    lambda d: FakeWebResponse(200, {"ref": ref_for(d).replace(".png", ".gif")}),
    lambda d: FakeWebResponse(200, {"ref": ref_for(d) + "\n"}),
    lambda d: FakeWebResponse(200, {"nope": 1}),
    lambda d: FakeWebResponse(200, [ref_for(d)]),
    lambda d: FakeWebResponse(200, None, raise_json=True),
])
def test_a_malformed_or_mismatched_ref_is_a_caption(world, make):
    data = png()
    world.images["https://img.example.com/a.png"] = data
    world.web = lambda body: make(data)
    assert rehost("![a](https://img.example.com/a.png)") == "![a]()"


# ═══ 7. the bytes ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("data,ext", [
    (png(), "png"), (jpeg(), "jpg"), (gif(version=b"87a"), "gif"), (gif(version=b"89a"), "gif"),
    (webp_vp8x(), "webp"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", None),
    (b"<!doctype html><html>", None),
    (gif(version=b"88a"), None),
    (b"GIF89b" + b"\x00" * 10, None),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", None),
    (png()[:7], None),
    (b"\xff\xd8", None),
])
def test_the_sniff_mirrors_the_contract(data, ext):
    assert R._doc_img_sniff_ext(data) == ext


@pytest.mark.parametrize("data,ext,dims", [
    (png(640, 480), "png", (640, 480)),
    (gif(321, 123), "gif", (321, 123)),
    (jpeg(1024, 768), "jpg", (1024, 768)),
    (webp_vp8x(5000, 49), "webp", (5000, 49)),
    (webp_vp8l(777, 66), "webp", (777, 66)),
    (webp_vp8(900, 300), "webp", (900, 300)),
])
def test_dimensions_are_read_from_each_header(data, ext, dims):
    assert R._doc_img_dimensions(data, ext) == dims


@pytest.mark.parametrize("data,ext", [
    (png(ihdr=b"IDAT"), "png"), (jpeg(sof=False), "jpg"), (png()[:20], "png"),
    (webp_vp8l()[:20] + b"\x00" + webp_vp8l()[21:], "webp"),
    (webp_vp8()[:23] + b"\x00\x00\x00" + webp_vp8()[26:], "webp"),
    (b"RIFF\x00\x00\x00\x00WEBPALPH" + b"\x00" * 20, "webp"),
])
def test_unreadable_dimensions_are_none(data, ext):
    assert R._doc_img_dimensions(data, ext) is None


@pytest.mark.parametrize("data,kind", [
    (png(47, 200), "dropped"), (png(200, 47), "dropped"), (gif(47, 47), "dropped"),
    (png(ihdr=b"IDAT"), "failed"), (b"<svg/>" * 20, "failed"), (b"", "failed"),
])
def test_tiny_unreadable_and_non_raster_bytes_are_refused(data, kind):
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_check_bytes(data)
    assert got.value.kind == kind


def test_48_px_is_kept():
    assert R._doc_img_check_bytes(png(48, 48)) == "png"


def test_more_than_5mb_is_refused_and_5mb_is_not(monkeypatch):
    at_cap = png(100, 100) + b"\x00" * (R._DOC_IMG_MAX_BYTES - len(png(100, 100)))
    assert R._doc_img_check_bytes(at_cap) == "png"
    with pytest.raises(R._DocImageRefused):
        R._doc_img_check_bytes(at_cap + b"\x00")


def test_an_oversize_data_uri_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(R.base64, "b64decode", lambda *a, **k: pytest.fail("decoded"))
    uri = "data:image/png;base64," + "A" * (4 * -(-R._DOC_IMG_MAX_BYTES // 3) + 4)
    with pytest.raises(R._DocImageRefused):
        R._doc_img_decode_data_uri(uri)


# ═══ 8. where the machine may connect ══════════════════════════════════════════

@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "255.255.255.255", "240.0.0.1", "224.0.0.1", "239.255.255.250",
    "::1", "::", "fe80::1", "fc00::1", "ff02::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
    "2002:7f00:1::", "2001::1", "64:ff9b::a00:1", "64:ff9b::7f00:1", "", "not-an-ip", None,
])
def test_non_public_addresses_are_refused(addr):
    """Multicast and the NAT64 prefix are the two `is_global` calls global; the rest
    pin the library's own behaviour on this interpreter, so a Python that differs
    fails here rather than in the owner's LAN."""
    assert R._doc_img_address_is_public(addr) is False


@pytest.mark.parametrize("addr", ["93.184.216.34", "8.8.8.8", "2606:4700::1111",
                                  "::ffff:8.8.8.8", "64:ff9b::808:808"])
def test_public_addresses_pass(addr):
    assert R._doc_img_address_is_public(addr) is True


@pytest.mark.parametrize("url", [
    "http://img.example.com/a.png", "ftp://img.example.com/a.png", "blob:https://x/1",
    "sandbox:/mnt/data/a.png", "HTTPS:img.example.com", "https:///a.png",
    "https://user:pw@img.example.com/a.png", "https://user@img.example.com/a.png",
    "https://img.example.com:8443/a.png", "https://img.example.com:0/a.png",
    "https://img.example.com:99999/a.png",
    "https://img.example.com\\@127.0.0.1/a.png", "https://img.example.com/a b.png",
    "https://img.example.com/a\x00.png", "https://img.example.com/" + "a" * 4100,
])
def test_url_rules_refuse(url, monkeypatch):
    monkeypatch.setattr(R, "_doc_img_resolve_host", lambda h, p: ["93.184.216.34"])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_check_url(url)
    assert got.value.kind == "refused"


@pytest.mark.parametrize("addrs", [["93.184.216.34", "10.0.0.8"], ["127.0.0.1"], []])
def test_every_resolved_address_must_be_public(addrs, monkeypatch):
    monkeypatch.setattr(R, "_doc_img_resolve_host", lambda h, p: addrs)
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_check_url("https://img.example.com/a.png")
    assert got.value.kind == "refused"


def test_a_name_that_does_not_resolve_fails(monkeypatch):
    def boom(h, p):
        raise OSError("nxdomain")
    monkeypatch.setattr(R, "_doc_img_resolve_host", boom)
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_check_url("https://img.example.com/a.png")
    assert got.value.kind == "failed"


def test_https_on_443_with_public_addresses_passes(monkeypatch):
    seen = []
    monkeypatch.setattr(R, "_doc_img_resolve_host", lambda h, p: seen.append((h, p)) or ["8.8.8.8"])
    R._doc_img_check_url("https://IMG.example.com:443/a.png?x=1")
    R._doc_img_check_url("https://img.example.com/b.png")
    assert seen == [("img.example.com", 443), ("img.example.com", 443)]


class FakeSock:
    def __init__(self, peer):
        self.peer = peer
        self.closed = False
        self.sent = b""

    def getpeername(self):
        if isinstance(self.peer, BaseException):
            raise self.peer
        return (self.peer, 443)

    def close(self):
        self.closed = True

    def sendall(self, data, *a):
        self.sent += data

    def send(self, data, *a):
        self.sent += data
        return len(data)

    def settimeout(self, t):
        pass

    def gettimeout(self):
        return None

    def setsockopt(self, *a):
        pass

    def fileno(self):
        return -1


@pytest.mark.parametrize("peer", ["10.0.0.7", "127.0.0.1", "169.254.169.254", OSError("gone")])
def test_a_non_public_peer_is_refused_and_the_socket_closed(peer):
    sock = FakeSock(peer)
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_check_peer(sock)
    assert got.value.kind == "refused" and sock.closed


def test_a_public_peer_passes():
    sock = FakeSock("93.184.216.34")
    R._doc_img_check_peer(sock)
    assert not sock.closed


def test_the_peer_check_runs_inside_real_requests_before_a_byte_is_written(monkeypatch):
    """DNS rebinding: the name resolved public for the check, then the connect went
    somewhere private. Driven through the REAL requests → urllib3 chain, with only
    the TCP connect faked."""
    socks = []

    def fake_new_conn(self):
        s = FakeSock("10.0.0.7")
        socks.append(s)
        return s
    monkeypatch.setattr(urllib3.connection.HTTPConnection, "_new_conn", fake_new_conn)
    session = R._doc_img_session()
    with pytest.raises(R._DocImageRefused):
        session.get("https://img.example.com/a.png", stream=True, allow_redirects=False,
                    timeout=(1, 1))
    assert len(socks) == 1 and socks[0].closed and socks[0].sent == b""


def test_a_public_peer_is_not_refused_by_the_real_chain(monkeypatch):
    monkeypatch.setattr(urllib3.connection.HTTPConnection, "_new_conn",
                        lambda self: FakeSock("93.184.216.34"))
    session = R._doc_img_session()
    with pytest.raises(Exception) as got:
        session.get("https://img.example.com/a.png", stream=True, allow_redirects=False,
                    timeout=(1, 1))
    assert not isinstance(got.value, R._DocImageRefused)


def test_the_session_keeps_no_cookies_sends_no_auth_and_ignores_the_environment():
    from requests.cookies import MockRequest, MockResponse
    session = R._doc_img_session()
    assert session.trust_env is False and session.auth is None
    assert "Cookie" not in session.headers and "Authorization" not in session.headers
    assert session.headers["Accept-Encoding"] == "identity"
    msg = Message()
    msg["Set-Cookie"] = "sid=1; Path=/"
    req = requests.Request("GET", "https://img.example.com/a.png").prepare()
    session.cookies.extract_cookies(MockResponse(msg), MockRequest(req))
    assert len(session.cookies) == 0
    control = requests.Session()
    control.cookies.extract_cookies(MockResponse(msg), MockRequest(req))
    assert len(control.cookies) == 1  # the fake would store a cookie if allowed


# ═══ 9. the fetch: redirects by hand, a hard byte cap ══════════════════════════

class FakeRaw:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.total = 0
        self.asks = []

    def read(self, amt=None, decode_content=True):
        self.asks.append((amt, decode_content))
        if not self.chunks:
            return b""
        chunk = self.chunks[0]
        if callable(chunk):
            chunk = chunk()
        elif len(chunk) > amt:
            self.chunks[0] = chunk[amt:]
        else:
            self.chunks.pop(0)
        out = chunk[:amt]
        self.total += len(out)
        return out


class FakeHTTPResponse:
    def __init__(self, status=200, headers=None, chunks=(), raw=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw = raw or FakeRaw(chunks)
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def net(monkeypatch):
    n = types.SimpleNamespace(dns={}, resolved=[], session=None)

    def resolve(host, port):
        n.resolved.append(host)
        return n.dns.get(host, ["93.184.216.34"])
    monkeypatch.setattr(R, "_doc_img_resolve_host", resolve)
    monkeypatch.setattr(R, "_doc_img_session", lambda: n.session)
    return n


def far():
    return time.monotonic() + 60


def test_redirects_are_followed_by_hand_and_every_hop_is_checked(net):
    first = FakeHTTPResponse(302, {"Location": "/moved/a.png"})
    second = FakeHTTPResponse(301, {"Location": "https://cdn2.example.com/final.png"})
    final = FakeHTTPResponse(200, {}, [png()])
    net.session = FakeSession([first, second, final])
    assert R._doc_img_fetch("https://img.example.com/a.png", far()) == png()
    assert [c[0] for c in net.session.calls] == [
        "https://img.example.com/a.png", "https://img.example.com/moved/a.png",
        "https://cdn2.example.com/final.png"]
    assert net.resolved == ["img.example.com", "img.example.com", "cdn2.example.com"]
    for _url, kw in net.session.calls:
        assert kw["allow_redirects"] is False and kw["stream"] is True
        assert kw["timeout"] == R._DOC_IMG_TIMEOUT
    assert first.closed and second.closed and final.closed and net.session.closed


def test_a_redirect_to_a_private_host_is_refused(net):
    net.dns["internal.example.com"] = ["10.1.2.3"]
    net.session = FakeSession([FakeHTTPResponse(302, {"Location": "https://internal.example.com/x"}),
                               FakeHTTPResponse(200, {}, [png()])])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert got.value.kind == "refused" and len(net.session.calls) == 1


def test_a_redirect_to_http_is_refused(net):
    net.session = FakeSession([FakeHTTPResponse(307, {"Location": "http://img.example.com/a.png"}),
                               FakeHTTPResponse(200, {}, [png()])])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert got.value.kind == "refused" and len(net.session.calls) == 1


def test_three_redirects_are_followed_and_a_fourth_fails(net):
    hop = lambda i: FakeHTTPResponse(302, {"Location": f"https://img.example.com/{i}.png"})  # noqa: E731
    net.session = FakeSession([hop(1), hop(2), hop(3), FakeHTTPResponse(200, {}, [png()])])
    assert R._doc_img_fetch("https://img.example.com/0.png", far()) == png()
    net.session = FakeSession([hop(1), hop(2), hop(3), hop(4), FakeHTTPResponse(200, {}, [png()])])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/0.png", far())
    assert got.value.kind == "failed" and len(net.session.calls) == 4


@pytest.mark.parametrize("resp", [
    FakeHTTPResponse(404, {}, [png()]), FakeHTTPResponse(206, {}, [png()]),
    FakeHTTPResponse(302, {}, []),
])
def test_a_non_200_or_a_redirect_without_location_fails(net, resp):
    net.session = FakeSession([resp])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert got.value.kind == "failed" and resp.closed and net.session.closed


def test_the_url_is_checked_before_any_request(net):
    net.session = FakeSession([FakeHTTPResponse(200, {}, [png()])])
    with pytest.raises(R._DocImageRefused):
        R._doc_img_fetch("http://img.example.com/a.png", far())
    assert net.session.calls == []


def test_the_body_is_capped_at_5mb_plus_one_byte(net):
    raw = FakeRaw([lambda: b"\x00" * 1_000_000])  # an endless body
    net.session = FakeSession([FakeHTTPResponse(200, {}, raw=raw)])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert got.value.kind == "failed"
    assert raw.total == R._DOC_IMG_MAX_BYTES + 1
    assert all(dc is False for _amt, dc in raw.asks)


def test_exactly_5mb_is_read_whole(net):
    body = png() + b"\x00" * (R._DOC_IMG_MAX_BYTES - len(png()))
    net.session = FakeSession([FakeHTTPResponse(200, {}, [body[:3_000_000], body[3_000_000:]])])
    assert R._doc_img_fetch("https://img.example.com/a.png", far()) == body


def test_a_declared_oversize_is_refused_before_reading(net):
    resp = FakeHTTPResponse(200, {"Content-Length": str(R._DOC_IMG_MAX_BYTES + 1)}, [png()])
    net.session = FakeSession([resp])
    with pytest.raises(R._DocImageRefused):
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert resp.raw.asks == []


def test_a_passed_deadline_stops_the_fetch_and_the_read(net):
    net.session = FakeSession([FakeHTTPResponse(200, {}, [png()])])
    with pytest.raises(R._DocImageRefused):
        R._doc_img_fetch("https://img.example.com/a.png", time.monotonic() - 1)
    assert net.session.calls == []
    resp = FakeHTTPResponse(200, {}, [png()])
    with pytest.raises(R._DocImageRefused):
        R._doc_img_read_capped(resp, time.monotonic() - 1)
    assert resp.raw.asks == []


def test_a_refused_address_inside_the_document_is_counted_and_captioned(world, monkeypatch):
    monkeypatch.setattr(R, "_doc_img_resolve_host", lambda h, p: ["192.168.0.10"])
    out = rehost("![Router admin](https://router.example.com/cam.png)")
    assert out == "![Router admin]()"
    assert world.logs[-1][1].endswith("refused=1 failed=0 captioned=1 removed=0")


# ═══ 10. the funnel ════════════════════════════════════════════════════════════

def test_the_event_loop_keeps_running_while_images_are_fetched(world):
    world.fetch_delay = 0.3
    world.images["https://img.example.com/slow.png"] = png()

    async def main():
        ticks = 0
        done = False

        async def ticker():
            nonlocal ticks
            while not done:
                await asyncio.sleep(0.01)
                ticks += 1
        t = asyncio.create_task(ticker())
        out = await R._rehost_document_images("![s](https://img.example.com/slow.png)", "Gemini")
        done = True
        await t
        return out, ticks

    out, ticks = asyncio.run(main())
    assert out == f"![s]({ref_for(png())})"
    assert ticks >= 10, f"the loop was blocked: {ticks} ticks in 300 ms"


def test_a_stuck_document_is_cut_off_and_written_with_captions(world, monkeypatch):
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.2)
    monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", 0.1)
    world.fetch_delay = 1.5
    world.images["https://img.example.com/stuck.png"] = png()

    async def main():
        # ⚠ Timed INSIDE the loop: `asyncio.run` itself waits for the abandoned
        # worker thread at shutdown, which a long-lived pipeline loop never does.
        t0 = time.monotonic()
        got = await R._rehost_document_images("![Stuck](https://img.example.com/stuck.png)", "ChatGPT")
        return got, time.monotonic() - t0

    out, elapsed = asyncio.run(main())
    assert elapsed < 1.2
    assert out == "![Stuck]()"
    assert any(level == "WARN" and "TimeoutError" in msg for level, msg in world.logs)
    assert "img.example.com" not in " ".join(m for _l, m in world.logs)


def test_text_without_images_is_returned_untouched_with_no_thread(world, monkeypatch):
    monkeypatch.setattr(R.asyncio, "to_thread", lambda *a, **k: pytest.fail("thread started"))
    text = "# Report\n\nNo pictures [a link](https://example.com) here."
    assert rehost(text) is text
    assert world.logs == []


def test_the_stats_line_holds_counts_only(world):
    world.images["https://img.example.com/secret-topic-chart.png"] = png()
    rehost("Tesla margins ![Secret alt words](https://img.example.com/secret-topic-chart.png) "
           "![](https://img.example.com/none.png) ![Cap](sandbox:/x.png)", "Claude")
    (level, line), = world.logs
    assert line == ("[Claude] document images: found=3 stored=1 reused=0 dropped=0 refused=1 "
                    "failed=1 captioned=1 removed=1")
    for leak in ("img.example.com", "Secret", "Tesla", "sandbox", "Cap"):
        assert leak not in line


def test_decorative_drops_reach_the_next_documents_stats_line_and_reset(world):
    R.html_to_markdown('<p>x<img src="https://c.example.com/i.png" width="16"><img aria-hidden="true" '
                       'src="https://c.example.com/j.png"></p>')
    rehost("no images at all", "Gemini")
    assert world.logs[-1][1] == ("[Gemini] document images: found=0 stored=0 reused=0 dropped=2 "
                                 "refused=0 failed=0 captioned=0 removed=0")
    rehost("still none", "Gemini")
    assert len(world.logs) == 1


def test_rehost_result_texts_rewrites_in_place_and_skips_what_has_no_text(world):
    world.images["https://img.example.com/r.png"] = png()
    results = {"ChatGPT": {"text": "![r](https://img.example.com/r.png)", "status": "done"},
               "Gemini": {"text": "", "status": "failed"}, "Claude": "not-a-dict"}
    asyncio.run(R._rehost_result_texts(results))
    assert results["ChatGPT"] == {"text": f"![r]({ref_for(png())})", "status": "done"}
    assert results["Gemini"] == {"text": "", "status": "failed"} and results["Claude"] == "not-a-dict"


# ═══ 11. the consumers — every save receives rewritten text ════════════════════

class _Page:
    url = "https://chatgpt.com/c/abc"


class _Browser:
    async def switch_to_page(self, page):
        return None


def _drive_extract(monkeypatch, tmp_path, world, guard=lambda text, *a, **k: text):
    saved = []

    async def extract(page, **kw):
        return "Findings ![Market chart](https://img.example.com/m.png) end"

    async def save(doc_type, content, name=None, **kw):
        saved.append((doc_type, content))
        return True

    async def no_sleep(*a, **k):
        return None
    world.images["https://img.example.com/m.png"] = png()
    monkeypatch.setattr(R, "extract_chatgpt_response", extract)
    monkeypatch.setattr(R, "reject_off_topic_text", guard)
    monkeypatch.setattr(R, "save_document_to_firestore_with_retry", save)
    monkeypatch.setattr(R, "_firebase_db", object())
    monkeypatch.setattr(R, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(R, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(R.asyncio, "sleep", no_sleep)
    result = asyncio.run(R.extract_and_record_agent("ChatGPT", _Page(), _Browser(), None, tmp_path))
    return result, saved


def test_the_per_agent_save_writes_and_returns_rewritten_text(monkeypatch, tmp_path, world):
    """EXECUTED. The local .md, the Firestore content and the text handed back in
    `results` — which the finalize re-save and the consolidated report read."""
    result, saved = _drive_extract(monkeypatch, tmp_path, world)
    ref = ref_for(png())
    local = (tmp_path / "documents" / "chatgpt.md").read_text(encoding="utf-8")
    assert local == f"# ChatGPT Deep Research\n\nFindings ![Market chart]({ref}) end"
    assert saved == [("chatgpt", local)]
    assert result["text"] == f"Findings ![Market chart]({ref}) end"
    assert result["status"] == "done"


def test_an_off_topic_document_s_images_are_never_fetched(monkeypatch, tmp_path, world):
    _drive_extract(monkeypatch, tmp_path, world, guard=lambda text, *a, **k: "")
    assert world.fetches == [] and world.posts == []


def _pipeline():
    return code_only(R.run_pipeline)


def test_every_brief_save_is_built_from_rehosted_text():
    """SOURCE PIN — `run_pipeline` cannot be executed here. For each brief build,
    the LAST assignment to `brief_text` before it is the rehost, and its save
    follows the build."""
    src = _pipeline()
    builds = list(re.finditer(r'(_brief_md\w*) = f"# Research Brief\\n\\n\{brief_text\}"', src))
    assert len(builds) == 3
    for b in builds:
        last = list(re.finditer(r"\bbrief_text = ", src[:b.start()]))[-1]
        stmt = src[last.start():src.index("\n", last.start())]
        assert stmt == 'brief_text = await _rehost_document_images(brief_text, label="Brief")', stmt
        nxt = src.find('_brief_md', b.end())
        tail = src[b.end():b.end() + 1200]
        assert f'save_document_to_firestore("brief", {b.group(1)}, ' in tail, (b.group(1), nxt)


def test_every_results_loop_that_writes_a_document_is_fed_by_the_rehost():
    """SOURCE PIN — the finalize re-save and both regen re-saves."""
    src = _pipeline()
    writers = [m.start() for m in re.finditer(r'\(queue_dir / "documents" / fname\)\.write_text\(', src)]
    assert len(writers) == 3
    for w in writers:
        loop = src.rindex("for name, r in results.items():", 0, w)
        before = src[:loop].rstrip().splitlines()[-1].strip()
        assert before == "await _rehost_result_texts(results)", before
        assert "results = " not in src[loop:w]


def test_the_consolidated_build_reads_the_rehosted_results():
    src = _pipeline()
    build = src.index("consolidated_parts = ")
    funnel = src.rindex("await _rehost_result_texts(results)", 0, build)
    between = src[funnel:build]
    assert "results = " not in between and "results[" not in between
    assert src.index('"consolidated.md").write_text(_consolidated_md') > build


def test_the_pipeline_has_exactly_the_measured_document_saves():
    """Three brief saves, the finalize re-save, the consolidated report, two regen
    re-saves. A new save site fails here until it is funneled and counted."""
    src = _pipeline()
    assert src.count("save_document_to_firestore(") == 7
    assert src.count("await _rehost_document_images(") == 3
    assert src.count("await _rehost_result_texts(results)") == 3


def test_the_per_agent_funnel_sits_between_the_guard_and_the_first_write():
    src = code_only(R.extract_and_record_agent)
    guard = src.index("text = reject_off_topic_text(")
    funnel = src.index("text = await _rehost_document_images(text, label=name)")
    write = src.index("(documents_dir / fname).write_text")
    assert guard < funnel < write
