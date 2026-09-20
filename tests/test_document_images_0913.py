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
import contextlib
import datetime
import hashlib
import ipaddress
import json
import re
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import types
from email.message import Message
from pathlib import Path

import pytest
import requests

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
                              web=None, fetch_delay=0.0, budgets=[], threads=[], scopes=[],
                              masks=[])
    monkeypatch.setattr(R, "_fb_uid", UID)
    monkeypatch.setattr(R, "_fb_research_id", RID)
    monkeypatch.setattr(R, "_doc_img_cache", collections.OrderedDict())
    monkeypatch.setattr(R, "_doc_img_decorative_pending", 0)
    monkeypatch.setattr(R, "_doc_img_resolve_host", lambda host, port: ["93.184.216.34"])
    # A fresh Stop/Pause state: the funnel reads it, and another test's Stop must
    # not turn every rehost here into the offline pass.
    monkeypatch.setattr(R, "_controls", R.PipelineControls())
    # ⛔ And no exit scheduled: the offline pass is taken on `_exit_scheduled`, which
    # a test elsewhere in the suite may leave set.
    monkeypatch.setattr(R, "_exit_scheduled", False)

    def token():
        w.token_calls += 1
        return "tok-1"
    monkeypatch.setattr(R, "_fresh_user_mode_id_token", token)

    def fetch(url, deadline):
        w.fetches.append(url)
        w.budgets.append(deadline - time.monotonic())
        w.threads.append(threading.current_thread().name)
        w.scopes.append(R._LOG_SCOPE.get())
        if hasattr(signal, "pthread_sigmask"):
            w.masks.append(signal.pthread_sigmask(signal.SIG_BLOCK, []))
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

    # The upload's own session (its every connection watched by its guard): the same
    # fake web behind it. `w.upload_guards` holds each upload's REAL guard.
    w.upload_guards, w.upload_sessions_closed = [], 0

    class UploadSession:
        def post(self, url, **kw):
            return post(url, **kw)

        def close(self):
            w.upload_sessions_closed += 1

    def upload_session(guard):
        w.upload_guards.append(guard)
        return UploadSession()
    monkeypatch.setattr(R, "_doc_img_upload_session", upload_session)

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

    def dup(self):
        return FakeSock(self.peer)

    def shutdown(self, how):
        pass

    def gettimeout(self):
        return None

    def setsockopt(self, *a):
        pass

    def fileno(self):
        return -1


def _no_lookup(*a, **k):
    raise AssertionError("a real name lookup — this test must not reach the network")


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
    the TCP connect faked (`_doc_img_connect`, the connection's own connect)."""
    socks = []

    def fake_connect(host, port, deadline, socket_options=None):
        s = FakeSock("10.0.0.7")
        socks.append(s)
        return s
    monkeypatch.setattr(R, "_doc_img_connect", fake_connect)
    monkeypatch.setattr(socket, "getaddrinfo", _no_lookup)
    session = R._doc_img_session(R._DocImgDeadline(far()))
    with pytest.raises(R._DocImageRefused):
        session.get("https://img.example.com/a.png", stream=True, allow_redirects=False,
                    timeout=(1, 1))
    assert len(socks) == 1 and socks[0].closed and socks[0].sent == b""


def test_a_public_peer_is_not_refused_by_the_real_chain(monkeypatch):
    monkeypatch.setattr(R, "_doc_img_connect", lambda *a, **k: FakeSock("93.184.216.34"))
    monkeypatch.setattr(socket, "getaddrinfo", _no_lookup)
    session = R._doc_img_session(R._DocImgDeadline(far()))
    with pytest.raises(Exception) as got:
        session.get("https://img.example.com/a.png", stream=True, allow_redirects=False,
                    timeout=(1, 1))
    assert not isinstance(got.value, R._DocImageRefused)


def test_the_session_keeps_no_cookies_sends_no_auth_and_ignores_the_environment():
    from requests.cookies import MockRequest, MockResponse
    session = R._doc_img_session(R._DocImgDeadline(far()))
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
    monkeypatch.setattr(R, "_doc_img_session", lambda guard: n.session)
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
    assert world.logs[-1][1].endswith("refused=1 login=0 failed=0 linked=0 captioned=1 removed=0")


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
    monkeypatch.setattr(R, "_doc_img_executor", lambda: pytest.fail("thread started"))
    text = "# Report\n\nNo pictures [a link](https://example.com) here."
    assert rehost(text) is text
    assert world.logs == []


def test_the_stats_line_holds_counts_only(world):
    world.images["https://img.example.com/secret-topic-chart.png"] = png()
    rehost("Tesla margins ![Secret alt words](https://img.example.com/secret-topic-chart.png) "
           "![](https://img.example.com/none.png) ![Cap](sandbox:/x.png)", "Claude")
    (level, line), = world.logs
    assert line == ("[Claude] document images: found=3 stored=1 reused=0 dropped=0 refused=1 "
                    "login=0 failed=1 linked=0 captioned=1 removed=1")
    for leak in ("img.example.com", "Secret", "Tesla", "sandbox", "Cap"):
        assert leak not in line


def test_decorative_drops_reach_the_next_documents_stats_line_and_reset(world):
    R.html_to_markdown('<p>x<img src="https://c.example.com/i.png" width="16"><img aria-hidden="true" '
                       'src="https://c.example.com/j.png"></p>')
    rehost("no images at all", "Gemini")
    assert world.logs[-1][1] == ("[Gemini] document images: found=0 stored=0 reused=0 dropped=2 "
                                 "refused=0 login=0 failed=0 linked=0 captioned=0 removed=0")
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
    follows the build.

    ⛔⛔ Wave 10 REPAIR, 2026-09-18 — RE-POINTED BACK. The wave first numbered the
    brief on its way to disk, so this pattern read
    `_document_with_sources(f"# Research Brief…")`. `brief.md` is the file
    ChatGPT and Claude RECEIVE, so numbering it handed them the numbering pass's
    own idempotency sentinel and one echoed marker cost a whole agent report its
    numbers and its bibliography, silently
    (`tests/test_numbered_sources_placement_0918.py`). The brief is written
    unnumbered again; the rehost-ordering claim below is untouched throughout,
    and the funnel count that used to include these three sites now pins them
    OUT."""
    src = _pipeline()
    builds = list(re.finditer(
        r'(_brief_md\w*) = f"# Research Brief\\n\\n\{brief_text\}"',
        src))
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
    # ⭐ Wave 10, 2026-09-18 — this used to point at the disk write, which is
    # retired (`tests/test_stacked_document_retired_0918.py`). The ordering claim
    # is unchanged and now rides the write that survived, the Firestore mirror;
    # the disk write is additionally pinned ABSENT, so re-pointing asserts more
    # than it did rather than less.
    assert '"consolidated.md").write_text' not in src
    assert src.index('save_document_to_firestore("consolidated", _consolidated_md') > build


def test_the_pipeline_has_exactly_the_measured_document_saves():
    """Three brief saves, the finalize re-save, the consolidated report, two regen
    re-saves. A new save site fails here until it is funneled and counted."""
    src = _pipeline()
    assert src.count("save_document_to_firestore(") == 7
    assert src.count("await _rehost_document_images(") == 3
    assert src.count("await _rehost_result_texts(results)") == 3
    # Round 4: the phase-1 skip branch's brief (no save, a local file and the paste).
    assert src.count("await _rehost_skipped_brief(") == 1


def test_the_per_agent_funnel_sits_between_the_guard_and_the_first_write():
    src = code_only(R.extract_and_record_agent)
    guard = src.index("text = reject_off_topic_text(")
    funnel = src.index("text = await _rehost_document_images(text, label=name)")
    write = src.index("(documents_dir / fname).write_text")
    assert guard < funnel < write


# ═══ 12. repair round 1 — one image's fetch ends at its deadline ════════════════
#
# ⛔⛔ The read timeout bounds ONE receive; a buffered read of 65536 bytes keeps
# receiving, so a server that trickles a byte at a time held a worker thread for
# days. These run the REAL fetch — requests, urllib3, TLS — against a REAL local
# server, with only the public-address rules switched off (it is 127.0.0.1).

# ⛔ 127.0.0.1, NOT "localhost". Every fake server in this file binds
# ("127.0.0.1", 0), but "localhost" resolves ::1 FIRST on Windows and nothing is
# listening there — and a refused connect to a closed loopback port costs ~2.04s
# here (Windows retransmits the SYN before reporting WSAECONNREFUSED), not the
# instant RST POSIX gives. Tests whose whole budget is 1.0-1.4s therefore spent it
# all on the dead address family: the deadline expired, `guard.watch()` refused the
# socket, and the listener was never reached — reported as `head_sent == []` or
# "the upload never reached the local web", i.e. as the product failing. The certs
# below already carry `IP:127.0.0.1` in their SANs, so TLS verification stays real.
_LOOPBACK = "127.0.0.1"

def _self_signed(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        made = subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
             "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
             "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], capture_output=True)
        if made.returncode != 0:
            pytest.skip("⛔⛔ NO CERTIFICATE TOOL (neither `cryptography` nor openssl) — the "
                        "trickling-server deadline tests measured NOTHING on this machine")
        return cert, key
    pkey = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ski = x509.SubjectKeyIdentifier.from_public_key(pkey.public_key())
    built = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
             .public_key(pkey.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now - datetime.timedelta(minutes=5))
             .not_valid_after(now + datetime.timedelta(days=1))
             .add_extension(x509.SubjectAlternativeName(
                 [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                 critical=False)
             .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
             .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                          key_encipherment=False, data_encipherment=False,
                                          key_agreement=False, key_cert_sign=True, crl_sign=False,
                                          encipher_only=False, decipher_only=False), critical=True)
             .add_extension(ski, critical=False)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski),
                            critical=False)
             .sign(pkey, hashes.SHA256()))
    cert.write_bytes(built.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(pkey.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return cert, key


@contextlib.contextmanager
def tls_server(tmp_path, head: bytes, drip: bytes = b"", every: float = 0.2, for_sec: float = 0.0):
    """Serves `head` at once, then `drip` every `every` seconds for `for_sec`, then closes."""
    cert, key = _self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    lsock = socket.socket()
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(4)
    lsock.settimeout(0.1)
    stop = threading.Event()
    served = []

    def serve():
        while not stop.is_set():
            try:
                raw, _ = lsock.accept()
            except OSError:
                continue
            conn = None
            try:
                raw.settimeout(3)
                conn = ctx.wrap_socket(raw, server_side=True)
                conn.recv(65536)
                conn.sendall(head)
                served.append("head")
                until = time.monotonic() + for_sec
                while drip and not stop.is_set() and time.monotonic() < until:
                    conn.sendall(drip)
                    stop.wait(every)
            except (OSError, ssl.SSLError):
                pass
            finally:
                (conn or raw).close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    try:
        yield cert, lsock.getsockname()[1], served
    finally:
        stop.set()
        th.join(5)
        lsock.close()


class _Made(list):
    pass


def _spy_deadlines(monkeypatch):
    """Every `_DocImgDeadline` the fetch makes, in order."""
    made = _Made()
    real_guard = R._DocImgDeadline

    class SpyDeadline(real_guard):
        def __init__(self, deadline):
            super().__init__(deadline)
            made.append(self)
    monkeypatch.setattr(R, "_DocImgDeadline", SpyDeadline)
    return made


def _trust_local_server(monkeypatch, cert):
    """The real session, trusting the local certificate, with the public-address
    rules off (the server is 127.0.0.1)."""
    real_session = R._doc_img_session
    monkeypatch.setattr(R, "_doc_img_check_url", lambda url: None)
    monkeypatch.setattr(R, "_doc_img_check_peer", lambda sock: None)
    # The connect's own address rule too (round 4: checked before a socket is made).
    monkeypatch.setattr(R, "_doc_img_address_is_public", lambda addr: True)

    def session(guard):
        s = real_session(guard)
        s.verify = str(cert)
        return s
    monkeypatch.setattr(R, "_doc_img_session", session)


def _fetch_in_thread(url, budget, wait):
    box = {}

    def go():
        t0 = time.monotonic()
        try:
            box["value"] = R._doc_img_fetch(url, time.monotonic() + budget)
        except BaseException as exc:  # noqa: BLE001 — the kind is asserted by the caller
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=go, daemon=True)
    th.start()
    th.join(wait)
    return th, box


def _png_response(body: bytes) -> bytes:
    return (b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: "
            + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)


def test_the_real_tls_chain_fetches_a_whole_image(tmp_path, monkeypatch):
    """The control: without it the trickle tests below could pass on a certificate
    error that fails at once."""
    made = _spy_deadlines(monkeypatch)
    with tls_server(tmp_path, _png_response(png(300, 200))) as (cert, port, served):
        _trust_local_server(monkeypatch, cert)
        th, box = _fetch_in_thread(f"https://{_LOOPBACK}:{port}/a.png", 5.0, 6.0)
    assert not th.is_alive()
    assert box.get("value") == png(300, 200), box.get("error")
    (guard,) = made
    guard._timer.join(2)
    assert not guard._timer.is_alive() and guard._socks == [] and guard.expired


def _trickle(tmp_path, monkeypatch, head, drip):
    made = _spy_deadlines(monkeypatch)
    with tls_server(tmp_path, head, drip, every=0.2, for_sec=6.0) as (cert, port, served):
        _trust_local_server(monkeypatch, cert)
        th, box = _fetch_in_thread(f"https://{_LOOPBACK}:{port}/slow.png", 1.0, 3.0)
        alive = th.is_alive()
        head_sent = list(served)
    return alive, box, head_sent, made


def test_a_body_sent_a_byte_at_a_time_ends_at_the_deadline(tmp_path, monkeypatch):
    head = (b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: 4000000\r\n\r\n"
            + png(300, 200))
    alive, box, head_sent, made = _trickle(tmp_path, monkeypatch, head, b"\x00")
    assert not alive, "the fetch was still reading 3 s after a 1 s deadline"
    assert head_sent == ["head"] and "error" in box and "value" not in box
    assert 0.8 <= box["elapsed"] < 2.5, box
    assert made[0]._socks == [] and made[0].expired


def test_headers_sent_a_byte_at_a_time_end_at_the_deadline(tmp_path, monkeypatch):
    alive, box, head_sent, made = _trickle(tmp_path, monkeypatch, b"HTTP/1.1 200 OK\r\nX-Slow: ", b"a")
    assert not alive, "the status line and headers held the fetch past its deadline"
    assert head_sent == ["head"] and "error" in box and "value" not in box
    assert 0.8 <= box["elapsed"] < 2.5, box


def test_the_deadline_shuts_the_connection_through_a_dup():
    guard = R._DocImgDeadline(far())
    a, b = socket.socketpair()
    try:
        a.settimeout(3)
        guard.watch(a)
        t0 = time.monotonic()
        guard.expire()
        # ⛔ THE PROPERTY IS "the blocked read ENDED", not the shape of the
        # ending. POSIX gets a clean FIN, so `recv` returns b"". Windows gets an
        # RST, because `shutdown` there returns success and leaves the read
        # sitting out its full timeout — so `expire()` uses an abortive close and
        # the read wakes as ConnectionAbortedError. Both are the cut landing; the
        # thing this test must still catch is the read NOT ending, which on either
        # platform shows up as the 3s timeout blowing the 1.0s budget below.
        try:
            ended = a.recv(1) == b""
        except ConnectionResetError:
            ended = True
        except ConnectionAbortedError:
            ended = True
        assert ended and time.monotonic() - t0 < 1.0
    finally:
        guard.close()
        a.close()
        b.close()
    assert guard._socks == []


def test_no_connection_may_start_after_the_deadline():
    guard = R._DocImgDeadline(far())
    guard.expire()
    a, b = socket.socketpair()
    try:
        with pytest.raises(R._DocImageRefused) as got:
            guard.watch(a)
        assert got.value.kind == "failed" and a.fileno() == -1
    finally:
        a.close()
        b.close()


def test_a_deadline_that_lands_between_reads_is_a_refusal_not_a_short_image(net, monkeypatch):
    """The timer fires after the loop's deadline check; the next read sees EOF and
    a truncated image with a readable header would pass every later check."""
    made = _spy_deadlines(monkeypatch)
    raw = FakeRaw([png(300, 200), lambda: (made[0].expire(), b"")[1]])
    net.session = FakeSession([FakeHTTPResponse(200, {"Content-Type": "image/png"}, raw=raw)])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert got.value.kind == "failed"


def test_every_fetch_cancels_its_timer_and_closes_its_dups(net, monkeypatch):
    made = _spy_deadlines(monkeypatch)
    net.session = FakeSession([FakeHTTPResponse(200, {}, [png()])])
    assert R._doc_img_fetch("https://img.example.com/a.png", far()) == png()
    net.session = FakeSession([FakeHTTPResponse(500, {}, [])])
    with pytest.raises(R._DocImageRefused):
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert len(made) == 2
    for guard in made:
        guard._timer.join(2)
        assert not guard._timer.is_alive() and guard.expired


def test_one_image_gets_at_most_its_own_budget_and_never_more_than_the_document(world, monkeypatch):
    world.images["https://img.example.com/a.png"] = png()
    rehost("![a](https://img.example.com/a.png)")
    assert R._DOC_IMG_PER_IMAGE_SEC - 2 <= world.budgets[0] <= R._DOC_IMG_PER_IMAGE_SEC
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 5.0)
    world.images["https://img.example.com/b.png"] = gif()
    rehost("![b](https://img.example.com/b.png)")
    assert 3.0 <= world.budgets[1] <= 5.0


def test_the_rehost_runs_on_its_own_threads_and_keeps_the_log_scope(world):
    world.images["https://img.example.com/a.png"] = png()

    async def main():
        with R._machine_log_scope():
            return await R._rehost_document_images("![a](https://img.example.com/a.png)", "Gemini")
    assert asyncio.run(main()) == f"![a]({ref_for(png())})"
    assert world.threads[0].startswith("doc-images")
    assert world.scopes == [R._LOG_SCOPE_MACHINE]
    assert R._doc_img_executor()._max_workers == R._DOC_IMG_WORKERS == 1


def _doc_image_threads():
    return [t for t in threading.enumerate() if t.name.startswith("doc-images")]


@pytest.mark.skipif(not hasattr(signal, "pthread_sigmask"), reason="no signal mask on this platform")
def test_a_rehost_thread_takes_no_signal_and_ends_with_its_document(world):
    """⛔⛔ A process-wide signal goes to ANY thread that has not blocked it. Idle
    rehost threads that lived forever took the serve-stop test's SIGUSR1 — it
    failed, and once the default action killed the whole suite with no summary."""
    world.images["https://img.example.com/a.png"] = png()
    assert rehost("![a](https://img.example.com/a.png)") == f"![a]({ref_for(png())})"
    (mask,) = world.masks
    assert {signal.SIGUSR1, signal.SIGINT, signal.SIGTERM} <= mask
    # ⛔⛔ A blocked fault signal is undefined by POSIX: a crash in this thread would
    # kill the serve process with no traceback.
    faults = {signal.SIGSEGV, signal.SIGBUS, signal.SIGFPE, signal.SIGILL, signal.SIGABRT}
    assert not (faults & mask), sorted(faults & mask)
    for t in _doc_image_threads():
        t.join(3)
    assert _doc_image_threads() == []
    got = []
    old_handler = signal.getsignal(signal.SIGUSR1)
    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    try:
        signal.signal(signal.SIGUSR1, lambda *_a: got.append(1))
        signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGUSR1])
        import os
        os.kill(os.getpid(), signal.SIGUSR1)
        assert signal.SIGUSR1 in signal.sigpending(), "held by the main thread"
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGUSR1])
        assert got == [1]
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        signal.signal(signal.SIGUSR1, old_handler)


def test_the_pool_is_shut_down_by_the_funnel_and_not_by_the_collector(world, monkeypatch):
    """⛔⛔ `pool.shutdown` in the funnel's `finally` — never a dropped reference.

    The executor's OWN weakref hides a missing shutdown: while nothing else holds
    the pool, CPython frees it the moment the funnel returns and the callback ends
    the worker anyway, so the test above passes either way. Anything that keeps the
    frame alive keeps the pool alive with it — a profiler, a debugger, a traceback
    held for a log line, any non-refcounted runtime — and then the idle thread lives
    on with the process's signals to take. So the pool is HELD here, the way such a
    reader holds it, and the shutdown is read where it is public and needs no
    collector: a shut-down executor refuses new work, and its worker still ends."""
    world.images["https://img.example.com/a.png"] = png()
    pools = []
    real = R._doc_img_executor
    monkeypatch.setattr(R, "_doc_img_executor", lambda: pools.append(real()) or pools[-1])
    assert rehost("![a](https://img.example.com/a.png)") == f"![a]({ref_for(png())})"
    assert len(pools) == 1
    try:
        with pytest.raises(RuntimeError):
            pools[0].submit(lambda: None)
        for t in _doc_image_threads():
            t.join(3)
        assert _doc_image_threads() == []
    finally:
        pools[0].shutdown(wait=False)


# ═══ 13. repair round 1 — login-only images, the user agent ═════════════════════

@pytest.mark.parametrize("status", [401, 403])
def test_a_login_only_image_is_its_own_count(net, status):
    resp = FakeHTTPResponse(status, {}, [png()])
    net.session = FakeSession([resp])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://img.example.com/a.png", far())
    assert got.value.kind == "login" and resp.raw.asks == []


def test_the_stats_line_counts_login_only_images(world):
    world.images["https://img.example.com/private.png"] = R._DocImageRefused("login")
    assert rehost("![Private](https://img.example.com/private.png)", "ChatGPT") == "![Private]()"
    assert world.logs[-1][1] == ("[ChatGPT] document images: found=1 stored=0 reused=0 dropped=0 "
                                 "refused=0 login=1 failed=0 linked=0 captioned=1 removed=0")


def test_the_user_agent_does_not_name_the_product():
    ua = R._doc_img_session(R._DocImgDeadline(far())).headers["User-Agent"]
    assert ua.startswith("Mozilla/5.0") and "superresearch" not in ua.lower()


# ═══ 14. repair round 1 — a citation after "!" stays a link ═════════════════════

def test_a_page_after_an_exclamation_mark_is_written_back_as_a_link(world):
    url = "https://news.example.com/article"
    world.images[url] = R._DocImageRefused("linked")
    text = f"This changes everything![source]({url}) and more."
    out = rehost(text)
    assert out == f"This changes everything\\![source]({url}) and more."
    assert world.logs[-1][1].endswith("linked=1 captioned=0 removed=0")
    assert rehost(out) == out and world.fetches == [url]
    again = rehost(f"Another doc![source]({url}) too.", "Gemini")
    assert again == f"Another doc\\![source]({url}) too." and world.fetches == [url]
    assert world.logs[-1][1] == ("[Gemini] document images: found=1 stored=0 reused=0 dropped=0 "
                                 "refused=0 login=0 failed=0 linked=1 captioned=0 removed=0")


def test_a_linked_reference_keeps_its_definition(world):
    url = "https://news.example.com/a"
    world.images[url] = R._DocImageRefused("linked")
    text = f"See everything![source][1] now.\n\n[1]: {url}\n"
    assert rehost(text) == f"See everything\\![source][1] now.\n\n[1]: {url}\n"


def test_only_a_web_page_is_a_link(net):
    net.session = FakeSession([FakeHTTPResponse(200, {"Content-Type": "text/html; charset=utf-8"},
                                                [b"<!doctype html><title>x</title>"])])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://news.example.com/a", far())
    assert got.value.kind == "linked"
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    net.session = FakeSession([FakeHTTPResponse(200, {"Content-Type": "image/svg+xml"}, [svg])])
    assert R._doc_img_fetch("https://img.example.com/a.svg", far()) == svg
    net.session = FakeSession([FakeHTTPResponse(200, {"Content-Type": "text/html"}, [png()])])
    assert R._doc_img_fetch("https://img.example.com/mislabelled", far()) == png()


def test_the_citation_after_an_exclamation_mark_is_a_finding_again(world):
    url = "https://news.example.com/article"
    world.images[url] = R._DocImageRefused("linked")
    out = rehost(f"## Impact\n\nThis changes everything![source]({url}) and more for the market.\n")
    (finding,) = R._extract_findings(out, [])
    assert finding["url"] == url
    assert "This changes everything!source and more for the market" in finding["snippet"]


# ═══ 15. repair round 1 — code is quoted text ═══════════════════════════════════

@pytest.mark.parametrize("text", [
    "Use the <img> element for pictures.",
    "Always give <IMG /> an alt.",
    "Always give <img alt> a value.",
    "Inline `<img src=\"https://cdn.example.com/x.png\" alt=\"logo\">` sample.",
    "Inline ``a ` ![x](https://img.example.com/x.png) b`` span.",
    "```html\n<img src=\"https://cdn.example.com/logo.png\" alt=\"logo\">\n![m](https://img.example.com/m.png)\n```\n",
    "~~~\n![t](https://img.example.com/t.png)\n~~~\n",
    "````md\n```\n![q](https://img.example.com/q.png)\n````\n",
])
def test_code_and_a_bare_img_mention_are_kept_byte_for_byte(world, text):
    world.images.update({u: png() for u in ("https://cdn.example.com/logo.png",
                                              "https://cdn.example.com/x.png",
                                              "https://img.example.com/x.png",
                                              "https://img.example.com/m.png",
                                              "https://img.example.com/t.png",
                                              "https://img.example.com/q.png")})
    assert rehost(text) == text
    assert world.fetches == [] and world.posts == []
    _assert_the_pass_ran_clean(world)


def _assert_the_pass_ran_clean(world):
    """⛔ The funnel hands back the INPUT when the rewrite raises, so "unchanged" alone
    cannot tell kept code from a crash. The stats line proves the pass finished."""
    assert not any(level == "WARN" for level, _msg in world.logs), world.logs
    assert world.logs and " document images: found=" in world.logs[-1][1]


def test_an_image_after_a_closed_fence_is_still_rehosted(world):
    url = "https://img.example.com/after.png"
    world.images[url] = png()
    out = rehost(f"```\ncode `x`\n```\n\n![after]({url})")
    assert out == f"```\ncode `x`\n```\n\n![after]({ref_for(png())})"


def test_an_image_after_a_closed_fence_in_a_crlf_document_is_still_rehosted(world):
    """⛔ Every CRLF line ends in "\\r": the closer refused it, the fence ran to the
    end of the document, and every later image kept its platform URL."""
    url = "https://img.example.com/crlf.png"
    world.images[url] = png()
    world.images["https://img.example.com/m.png"] = png()
    text = f"```\r\n![m](https://img.example.com/m.png)\r\n```\r\n\r\n![after]({url})\r\n"
    out = rehost(text)
    assert out == f"```\r\n![m](https://img.example.com/m.png)\r\n```\r\n\r\n![after]({ref_for(png())})\r\n"
    assert world.fetches == [url]


def test_a_stray_backtick_does_not_hide_the_next_paragraph(world):
    url = "https://img.example.com/p2.png"
    world.images[url] = png()
    out = rehost(f"one ` stray\n\n![p]({url}) and ` later")
    assert out == f"one ` stray\n\n![p]({ref_for(png())}) and ` later"


def test_an_escaped_backtick_opens_no_code_span(world):
    url = "https://img.example.com/e.png"
    world.images[url] = png()
    assert rehost(f"a \\` ![e]({url}) `b") == f"a \\` ![e]({ref_for(png())}) `b"


def test_an_img_with_a_source_is_still_not_left_in_prose(world):
    """⛔ The mention guard is for a tag with NO source: one whose source cannot be
    written as markdown still goes, URL and all."""
    out = rehost('Before <img src="https://img.example.com/a&gt;b.png"> after')
    assert out == "Before  after" and "img.example.com" not in out


@pytest.mark.parametrize("tag", [
    '<img srcset="https://cdn.example.com/a.png 2x">',
    '<img data-src="https://cdn.example.com/a.png">',
    '<img style="background:url(https://cdn.example.com/a.png)">',
])
def test_an_img_with_any_url_bearing_attribute_is_not_left_in_prose(world, tag):
    """⛔⛔ The mention guard looked at `src` alone: a lazy-load tag with its URL in
    `srcset` or `data-src` was kept byte for byte, and a raw-HTML renderer loads it."""
    out = rehost(f"Before {tag} after")
    assert out == "Before  after" and "cdn.example.com" not in out
    assert world.fetches == []
    _assert_the_pass_ran_clean(world)


def test_nul_bytes_in_the_document_never_collide_with_the_code_placeholders(world):
    text = "odd \x000\x00 and `code` and \x00\x001\x00\x00 <img>"
    assert rehost(text) == text
    _assert_the_pass_ran_clean(world)


# ═══ 16. repair round 1 — definitions, odd destinations, snippets ═══════════════

def test_a_definition_an_image_shares_with_a_link_stays(world):
    url = "https://cdn.example.com/fig.png"
    world.images[url] = png()
    text = f"Chart ![fig][1] and cited [see][1].\n\n[1]: {url}\n"
    assert rehost(text) == f"Chart ![fig]({ref_for(png())}) and cited [see][1].\n\n[1]: {url}\n"


@pytest.mark.parametrize("link", ["[1][]", "[1]"])
def test_collapsed_and_shortcut_link_references_keep_the_definition(world, link):
    url = "https://cdn.example.com/fig.png"
    world.images[url] = png()
    out = rehost(f"![fig][1] then {link} here.\n\n[1]: {url}\n")
    assert out.endswith(f"[1]: {url}\n")


def test_an_inline_link_with_the_same_text_does_not_keep_the_definition(world):
    url = "https://cdn.example.com/fig.png"
    world.images[url] = png()
    out = rehost(f"![fig][1] and [1](https://example.com/x).\n\n[1]: {url}\n")
    assert out == f"![fig]({ref_for(png())}) and [1](https://example.com/x).\n\n"


@pytest.mark.parametrize("dest", [
    "https://upload.example.org/File_(a_(b)).png", "https://img.example.com/a b.png",
    "https://img.example.com/a\\) b.png",
])
def test_an_image_the_pattern_cannot_parse_loses_its_url(world, dest):
    out = rehost(f"x ![c]({dest}) y")
    assert out == "x ![c]() y"
    assert world.logs[-1][1].endswith("refused=1 login=0 failed=0 linked=0 captioned=1 removed=0")


def test_an_escaped_bang_before_an_unparseable_destination_is_left_as_text(world):
    text = "literal \\![x](https://img.example.com/a b.png) text"
    assert rehost(text) == text
    _assert_the_pass_ran_clean(world)


def test_an_unparseable_image_named_like_a_definition_loses_its_url_too(world):
    world.images["https://cdn.example.com/c.png"] = png()
    out = rehost("x ![c](https://img.example.com/a b.png) y\n\n[c]: https://cdn.example.com/c.png\n")
    assert out.startswith("x ![c]() y") and "a b.png" not in out and world.fetches == []


@pytest.mark.parametrize("image, tail, label", [
    ("![fig][l]", "(2024)", "l"),
    ("![fig][]", "(x)", "fig"),
    ("![fig]", "(see below", "fig"),
])
def test_a_reference_image_followed_by_a_parenthesis_resolves_through_its_definition(
        world, image, tail, label):
    """⛔ The unparseable-destination guard caught every reference form: a full
    `![fig][l](2024)`, a collapsed `![fig][](x)` and a shortcut whose `(` never closes
    on its line all render the DEFINITION's image — and all kept its platform URL."""
    url = "https://cdn.example.com/fig.png"
    world.images[url] = png()
    out = rehost(f"see {image}{tail} here\n\n[{label}]: {url}\n")
    assert out == f"see ![fig]({ref_for(png())}){tail} here\n\n"
    assert world.fetches == [url]


@pytest.mark.parametrize("gap", ["\xa0", "\r", "\x0b", "\x0c"], ids=["nbsp", "cr", "vt", "ff"])
def test_a_stored_reference_reaches_the_leftover_pass_and_survives_it(world, gap):
    """⛔ A FINISHED IMAGE THAT REACHES THE LEFTOVER PASS IS LEFT ALONE — end to end.

    The pass captions whatever sits between the parentheses the main pattern could
    not parse, and a stored `/document-images/…` reference DOES arrive there: one
    whitespace character the main pattern will not accept between the reference and
    its `)` — a non-breaking space out of an HTML capture, a stray CR — drops the
    image out of the main pass, and `.strip()` then hands THIS pass the bare
    reference. Blanked, the image is a caption in the saved document and the stored
    object is orphaned while the research's 300 still counts it."""
    ref = ref_for(png())
    text = f"Kept ![Chart]({ref}{gap}) end"
    assert rehost(text) == text
    assert world.fetches == [] and world.posts == []


def test_the_leftover_pass_leaves_a_finished_document_alone():
    """⛔ THE SAME CHECK AT THE PASS ITSELF — a stored reference, and a caption the
    last save wrote, handed to it directly.

    ⭐ Both ends are pinned because the funnel reaches this only through the odd
    whitespace above: the main pattern hides everything IT writes in slots until
    after this pass, so a plain `![c](/document-images/…)` cannot arrive here today.
    That is what the check buys — it is the ONE thing standing between every stored
    image and a caption the day the passes are reordered (the link pass leaves
    leftovers of its own), and nothing else would go red first."""
    run = R._DocImageRun(UID, RID, "ChatGPT", 120.0)
    ref = ref_for(png())
    text = (f"Stored ![Chart]({ref}) then ![Gone]() and a plain [link](https://x/y) "
            f"with [![Logo]({ref})](https://example.org/src) end")
    assert R._doc_img_blank_leftovers(text, run) == text
    assert run.stats["found"] == 0 and run.stats["captioned"] == 0
    assert run.stats["refused"] == 0 and run.stats["removed"] == 0


def test_a_shortcut_image_inside_a_parenthetical_still_resolves(world):
    url = "https://cdn.example.com/fig.png"
    world.images[url] = png()
    out = rehost(f"(chart: ![fig] below) now\n\n[fig]: {url}\n")
    assert out == f"(chart: ![fig]({ref_for(png())}) below) now\n\n"


def test_a_definition_title_on_the_next_line_goes_with_it(world):
    url = "https://cdn.example.com/x.png"
    world.images[url] = png()
    out = rehost(f'![f][fig]\n\n[fig]: {url}\n  "Figure title"\nafter\n')
    assert out == f"![f]({ref_for(png())})\n\nafter\n"
    out = rehost(f'![f][fig]\n\n[fig]: {url}\n"Quoted" said he.\n')
    assert out == f'![f]({ref_for(png())})\n\n"Quoted" said he.\n'


def test_findings_snippets_carry_no_image_markup():
    ref = f"/document-images/{RID}/{'c' * 64}.png"
    md = (f"## Market\n\nRevenue grew 40% last year ![Chart]({ref}) according to "
          "[Reuters](https://www.reuters.com/markets/a) today.\n\n"
          f"Margins fell [![Logo]({ref})](https://www.example.org/src) as costs rose "
          "sharply in the quarter.\n")
    got = {f["url"]: f["snippet"] for f in R._extract_findings(md, [])}
    reuters = got["https://www.reuters.com/markets/a"]
    assert "Revenue grew 40% last year according to Reuters today" in reuters
    src = got["https://www.example.org/src"]
    assert "Margins fell as costs rose sharply" in src
    for snip in (reuters, src):
        assert "![" not in snip and "!Chart" not in snip and "[](" not in snip
        assert "document-images" not in snip and "Logo" not in snip


# ═══ 17. repair round 1 — the machine and the web read ONE upload contract ══════
#
# ⛔ Two copied literals: rename a body key or the reference form on one side and
# both suites stay green, and at THE DEPLOY every upload is refused. Read from the
# web repo's COMMITTED tree (its working tree may be mid-mutation).
# ⭐ Its `main`, not a fixed commit: a pinned commit kept comparing the machine with
# a web the repairs had already moved past. Still read-only (`git show`).

WEB_CONTRACT_REV = "main"


def _web_repo():
    here = Path(R.__file__).resolve().parent
    candidates = [here.parent / "dg-research"]
    try:
        common = subprocess.run(["git", "-C", str(here), "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, encoding="utf-8", timeout=10)
        if common.returncode == 0 and common.stdout.strip():
            candidates.append(Path(common.stdout.strip()).parent.parent / "dg-research")
    except (OSError, subprocess.SubprocessError):
        pass
    return next((c for c in candidates if (c / ".git").exists()), None)


def _web_file(path):
    repo = _web_repo()
    if repo is None:
        pytest.skip("⛔⛔ THE WEB REPO (dg-research) IS NOT ON THIS DISK — the machine/web upload "
                    "contract was NOT compared")
    got = subprocess.run(["git", "-C", str(repo), "show", f"{WEB_CONTRACT_REV}:{path}"],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert got.returncode == 0, f"{repo} has no {WEB_CONTRACT_REV}:{path}: {got.stderr.strip()}"
    return got.stdout


def test_the_reference_regex_is_the_webs():
    src = _web_file("src/lib/document-images.ts")
    folder = re.search(r'export const DOCUMENT_IMAGE_FOLDER = "([^"]+)";', src).group(1)
    id_pattern = re.search(r'const ID_PATTERN = "([^"]+)";', src).group(1)
    template = re.search(r"DOCUMENT_IMAGE_REF_RE = new RegExp\(\s*`([^`]+)`", src).group(1)
    js = (template.replace("${DOCUMENT_IMAGE_FOLDER}", folder)
          .replace("${ID_PATTERN}", id_pattern).replace("\\\\", "\\"))
    assert js.startswith("^") and js.endswith("$") and "${" not in js, js
    assert R._DOC_IMG_REF_RE.pattern == r"\A" + js[1:-1] + r"\Z"


def test_the_upload_body_and_answer_are_the_routes(world):
    route = _web_file("src/app/api/document-images/route.ts")
    read_keys = set(re.findall(r"body\?\.(\w+)", route))
    answers = set(re.findall(r"NextResponse\.json\(\{ (\w+): parsed\.path \}\)", route))
    assert read_keys and answers == {"ref"}
    world.images["https://img.example.com/c.png"] = png()
    assert rehost("![c](https://img.example.com/c.png)") == f"![c]({ref_for(png())})"
    (post,) = world.posts
    assert set(post["json"]) == read_keys
    assert post["url"].endswith("/api/document-images")
    assert 'body.get("ref")' in code_only(R._doc_img_upload)


# ═══ 18. repair round 2 — a link around an image to that image goes ═════════════
#
# ⛔ A capture wraps a chart in a click-to-enlarge anchor. The converter writes
# `[![Chart](<S>)](S)` and the rewrite changed only the inner image, so the saved
# document and every share kept S — a signed platform URL — as the link. Every
# case below starts from the REAL converter's output.

SIGNED = "https://lh3.googleusercontent.com/SIGNED-chart=w800"


def test_the_converter_wraps_a_linked_image_the_way_these_tests_assume():
    """The control: without it the cases below could pass on a shape no capture writes."""
    assert (R.html_to_markdown(f'<p><a href="{SIGNED}"><img src="{SIGNED}" alt="Chart"></a></p>')
            == f"[![Chart](<{SIGNED}>)]({SIGNED})")


def test_a_self_link_around_a_stored_image_goes_and_the_image_stays(world):
    md = R.html_to_markdown(f'<p>Chart: <a href="{SIGNED}"><img src="{SIGNED}" alt="Chart"></a> end</p>')
    world.images[SIGNED] = png()
    out = rehost(md)
    assert out == f"Chart: ![Chart]({ref_for(png())}) end"
    assert rehost(out) == out and world.fetches == [SIGNED]


def test_a_self_link_with_a_title_around_a_captioned_image_goes(world):
    md = R.html_to_markdown(f'<p><a href="{SIGNED}" title="Open full size">'
                            f'<img src="{SIGNED}" alt="Chart"></a></p>')
    assert md.endswith(f'({SIGNED} "Open full size")')
    world.images[SIGNED] = R._DocImageRefused("login")
    assert rehost(md) == "![Chart]()"


def test_a_self_link_around_an_image_with_no_alt_goes_with_it(world):
    md = R.html_to_markdown(f'<p>a <a href="{SIGNED}"><img src="{SIGNED}"></a> b</p>')
    world.images[SIGNED] = R._DocImageRefused("failed")
    out = rehost(md)
    assert "googleusercontent" not in out and "](" not in out
    assert out == "a  b"


def test_a_self_link_around_a_removed_image_with_words_goes_and_the_words_stay(world):
    """⛔ A removed image leaves no text, so reading the link's text for it kept S
    whenever the anchor said more than the image."""
    md = R.html_to_markdown(f'<p><a href="{SIGNED}"><img src="{SIGNED}"> View full size</a></p>')
    assert md == f"[![](<{SIGNED}>) View full size]({SIGNED})"
    world.images[SIGNED] = R._DocImageRefused("failed")
    out = rehost(md)
    assert out == " View full size" and "googleusercontent" not in out


def test_a_link_to_a_different_page_around_a_removed_image_with_words_stays(world):
    page = "https://news.example.com/a"
    md = R.html_to_markdown(f'<p>see <a href="{page}"><img src="{SIGNED}"> Caption</a> end</p>')
    assert md == f"see [![](<{SIGNED}>) Caption]({page}) end"
    world.images[SIGNED] = R._DocImageRefused("failed")
    assert rehost(md) == f"see [ Caption]({page}) end"


def test_document_text_cannot_pose_as_an_image_slot(world):
    """The slot that marks where an image was written carries a per-pass nonce."""
    src = "https://cdn.example.com/chart.png"
    lookalike = ":0 000000000000:0"
    world.images[src] = png()
    assert rehost(f"{lookalike} ![Chart]({src})") == f"{lookalike} ![Chart]({ref_for(png())})"


def test_a_self_link_whose_text_holds_more_than_the_image_goes(world):
    src = "https://cdn.example.com/chart.png"
    md = R.html_to_markdown(f'<p><a href="{src}"><img src="{src}" alt="Q3"> Revenue by quarter</a></p>')
    world.images[src] = png()
    assert rehost(md) == f"![Q3]({ref_for(png())}) Revenue by quarter"


@pytest.mark.parametrize("href", ["blob:https://chatgpt.com/1234", "sandbox:/mnt/data/chart.png",
                                  "data:image/png;base64,AAAA", "BLOB:https://chatgpt.com/9"])
def test_a_link_to_an_address_nobody_can_open_around_an_image_goes(world, href):
    src = "https://cdn.example.com/chart.png"
    md = R.html_to_markdown(f'<p><a href="{href}"><img src="{src}" alt="Chart"></a></p>')
    assert md == f"[![Chart](<{src}>)]({href})"
    world.images[src] = png()
    assert rehost(md) == f"![Chart]({ref_for(png())})"


def test_a_link_around_an_image_to_a_different_page_stays(world):
    """⭐ The article the chart came from is a source, not a platform URL."""
    src = "https://cdn.example.com/chart.png"
    page = "https://news.example.com/story_(2024)"
    md = R.html_to_markdown(f'<p><a href="{page}"><img src="{src}" alt="Chart"> Caption words</a></p>')
    world.images[src] = png()
    assert rehost(md) == f"[![Chart]({ref_for(png())}) Caption words]({page})"
    world.images[SIGNED] = R._DocImageRefused("failed")
    md = R.html_to_markdown(f'<p><a href="{page}"><img src="{SIGNED}" alt="Fig"></a></p>')
    assert rehost(md) == f"[![Fig]()]({page})"


def test_a_citation_to_the_page_a_captioned_image_pointed_at_keeps_its_link(world):
    """⛔ Only a link AROUND that image goes. The same address cited elsewhere is a
    source the report names."""
    url = "https://news.example.com/article"
    world.images[url] = R._DocImageRefused("failed")
    out = rehost(f"Chart ![Reuters]({url}) and per [Reuters]({url}) today.")
    assert out == f"Chart ![Reuters]() and per [Reuters]({url}) today."


# ═══ 19. repair round 2 — a citation after "!" whatever the page answered ═══════
#
# ⛔⛔ Round 1 kept the citation only when its host answered 200 with a web page; a
# 403 to a plain client, a 404, a 5xx, an http address or a spent budget deleted
# it. ⛔⛔ But "any HTML answer is a link" is not the fix either: Google's image host
# answers an id it will not serve with `400 text/html` (measured 2026-09-14), so a
# Gemini chart would have gone back into the share as a live platform URL. A link
# needs the page answer (or no answer at all) AND markup that can be a citation.

_REAL_FETCH = R._doc_img_fetch
CITE = "https://www.reuters.com/markets/a"


def _real_fetch_answering(monkeypatch, status, ctype, body=b"<!doctype html><title>x</title>"):
    """The REAL fetch runs inside the rehost; every URL is answered the same way."""
    monkeypatch.setattr(R, "_doc_img_fetch", _REAL_FETCH)
    calls = []

    def session(guard):
        s = FakeSession([])

        def get(url, **kw):
            calls.append(url)
            return FakeHTTPResponse(status, {"Content-Type": ctype}, [body])
        s.get = get
        return s
    monkeypatch.setattr(R, "_doc_img_session", session)
    return calls


@pytest.mark.parametrize("status,fallback", [(401, "login"), (403, "login"), (404, "failed"),
                                             (429, "failed"), (500, "failed"), (503, "failed")])
def test_a_page_answer_is_a_page_whatever_its_status(net, status, fallback):
    resp = FakeHTTPResponse(status, {"Content-Type": "text/html; charset=utf-8"}, [b"<html>no</html>"])
    net.session = FakeSession([resp])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch(CITE, far())
    assert got.value.kind == "linked" and got.value.fallback == fallback
    assert resp.raw.asks == [] and resp.closed


@pytest.mark.parametrize("status,ctype,kind", [(403, "application/xml", "login"),
                                               (404, "application/json", "failed")])
def test_an_error_that_is_not_a_page_lands_where_it_always_did(net, status, ctype, kind):
    net.session = FakeSession([FakeHTTPResponse(status, {"Content-Type": ctype}, [b"<Error/>"])])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_fetch("https://files.example.net/blob?sig=x", far())
    assert got.value.kind == kind and got.value.fallback == kind


@pytest.mark.parametrize("status", [200, 403, 404, 503])
def test_a_citation_after_an_exclamation_mark_stays_a_link_whatever_the_page_answered(
        world, monkeypatch, status):
    calls = _real_fetch_answering(monkeypatch, status, "text/html; charset=utf-8")
    out = rehost(f"Revenue rose 40%![Reuters]({CITE}) in May.")
    assert out == f"Revenue rose 40%\\![Reuters]({CITE}) in May."
    assert calls == [CITE] and world.posts == []
    assert world.logs[-1][1].endswith("login=0 failed=0 linked=1 captioned=0 removed=0")


@pytest.mark.parametrize("md,expected", [
    ("Chart:\n\n![Chart](https://img.example.com/render?id=1)", "Chart:\n\n![Chart]()"),
    ("Chart: ![Chart](https://img.example.com/render?id=1)", "Chart: ![Chart]()"),
    ("Chart:![Chart](<https://img.example.com/render?id=1>)", "Chart:![Chart]()"),
    ("Chart:![Chart](https://lh3.googleusercontent.com/gg/abc)", "Chart:![Chart]()"),
    ("Chart:![Chart](https://img.example.com/charts/q3.png)", "Chart:![Chart]()"),
])
@pytest.mark.parametrize("status", [200, 400, 404])
def test_an_image_whose_host_answers_a_page_is_a_caption_not_a_link(world, monkeypatch, md, expected, status):
    """⛔⛔ The over direction of the fix above: an image on its own line or after a
    space, one the converter wrote (angle brackets), one on a platform's image
    host, one with an image path — each answered by an HTML error page."""
    _real_fetch_answering(monkeypatch, status, "text/html; charset=UTF-8")
    assert rehost(md) == expected


@pytest.mark.parametrize("status,counts", [(403, "login=1 failed=0"), (404, "login=0 failed=1"),
                                           (200, "login=0 failed=1")])
def test_a_page_answer_that_is_not_a_citation_counts_where_it_always_did(world, monkeypatch, status, counts):
    _real_fetch_answering(monkeypatch, status, "text/html")
    assert rehost("![Private](https://img.example.com/private)") == "![Private]()"
    assert world.logs[-1][1].endswith(f"refused=0 {counts} linked=0 captioned=1 removed=0")


@pytest.mark.parametrize("exit_", ["http", "no-token", "cap", "budget", "no-research"])
def test_a_citation_that_is_never_fetched_stays_a_link(world, monkeypatch, exit_):
    url = CITE
    if exit_ == "http":
        url = "http://www.reuters.com/markets/a"
    elif exit_ == "no-token":
        monkeypatch.setattr(R, "_fresh_user_mode_id_token", lambda: None)
    elif exit_ == "cap":
        monkeypatch.setattr(R, "_DOC_IMG_MAX_PER_DOC", 0)
    elif exit_ == "budget":
        monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.0)
    else:
        monkeypatch.setattr(R, "_fb_research_id", None)
    out = rehost(f"Revenue rose 40%![Reuters]({url}) in May.")
    assert out == f"Revenue rose 40%\\![Reuters]({url}) in May."
    assert world.fetches == [] and world.posts == []
    assert world.logs[-1][1].endswith("linked=1 captioned=0 removed=0")


@pytest.mark.parametrize("md,expected", [
    ("Chart ![Chart](https://img.example.com/render?id=1) end", "Chart ![Chart]() end"),
    ("![Chart](https://img.example.com/render?id=1)", "![Chart]()"),
    ("x\n![Chart](https://img.example.com/render?id=1)", "x\n![Chart]()"),
    ("[![Chart](https://img.example.com/render?id=1)](https://news.example.com/a)",
     "[![Chart]()](https://news.example.com/a)"),
    ("(![Chart](https://img.example.com/render?id=1))", "(![Chart]())"),
    ("|![Chart](https://img.example.com/render?id=1)|", "|![Chart]()|"),
    ("```\ncode\n```\n![Chart](https://img.example.com/render?id=1)", "```\ncode\n```\n![Chart]()"),
    ("Chart:![Chart](<https://img.example.com/render?id=1>)", "Chart:![Chart]()"),
    ("Chart:![Chart](https://lh3.googleusercontent.com/gg/abc)", "Chart:![Chart]()"),
    ("Chart:![Chart](https://files.oaiusercontent.com/file-1?sig=x)", "Chart:![Chart]()"),
    ("Chart:![Chart](https://img.example.com/q3.PNG)", "Chart:![Chart]()"),
    ("Chart:![Chart](http://img.example.com/q3.jpg)", "Chart:![Chart]()"),
    ("Chart:![Chart](sandbox:/mnt/data/chart)", "Chart:![Chart]()"),
    ("Chart:![Chart](blob:https://chatgpt.com/1234)", "Chart:![Chart]()"),
    ("Chart:![Chart](ftp://files.example.com/chart)", "Chart:![Chart]()"),
    ("Chart:![Chart](http://user:pw@img.example.com/chart)", "Chart:![Chart]()"),
])
def test_an_image_that_is_never_fetched_is_a_caption_not_a_link(world, monkeypatch, md, expected):
    """⛔⛔ With no answer to go on, only the markup decides — and every doubt is a
    caption: a lost citation is a low defect, a platform URL in a share is not."""
    monkeypatch.setattr(R, "_fresh_user_mode_id_token", lambda: None)
    assert rehost(md) == expected
    assert world.fetches == [] and world.posts == []


def test_a_page_verdict_is_cached_but_the_link_is_decided_per_occurrence(world):
    url = "https://news.example.com/article"
    world.images[url] = R._DocImageRefused("linked", "failed")
    out = rehost(f"Wow![source]({url}) and\n\n![source]({url})\n")
    assert out == f"Wow\\![source]({url}) and\n\n![source]()\n"
    other = "https://news.example.com/other"
    world.images[other] = R._DocImageRefused("linked", "failed")
    out = rehost(f"![x]({other})\n\nSo true![y]({other})", "Gemini")
    assert out == f"![x]()\n\nSo true\\![y]({other})"
    assert world.fetches == [url, other]


# ═══ 20. repair round 2 — an abandoned rehost stores nothing, remembers nothing ═
#
# ⛔ The hard stop only stops WAITING: the worker kept going, uploaded an object the
# captioned document never references (it counts toward the research's 300) and
# wrote the shared cache under the next document.

def _worker_done(monkeypatch):
    """Set when the WORKER's rewrite returns — not the fallback pass on the loop."""
    done = threading.Event()
    real = R._doc_images_rewrite_sync

    def rewrite(text, run):
        try:
            return real(text, run)
        finally:
            if threading.current_thread().name.startswith("doc-images"):
                done.set()
    monkeypatch.setattr(R, "_doc_images_rewrite_sync", rewrite)
    return done


def _saving_web(monkeypatch, save_sec):
    """A web that takes `save_sec` to save and SAVES WHATEVER THE CLIENT DOES: a client
    whose read timeout is shorter gives up (ReadTimeout) and the object is stored
    anyway — the stranded image a client-side give-up leaves behind."""
    web = types.SimpleNamespace(stored=[], timeouts=[], closed=0, guards=[])

    class Session:
        def post(self, url, json=None, timeout=None, **kw):
            web.timeouts.append(timeout)
            data = base64.b64decode(json["data_base64"])
            if timeout[1] < save_sec:
                time.sleep(max(0.0, timeout[1]))
                web.stored.append(data)
                raise requests.ReadTimeout("the web is still saving")
            time.sleep(save_sec)
            web.stored.append(data)
            return FakeWebResponse(200, {"ref": ref_for(data)})

        def close(self):
            web.closed += 1

    def session(guard):
        web.guards.append(guard)
        return Session()
    monkeypatch.setattr(R, "_doc_img_upload_session", session)
    return web


@pytest.mark.parametrize("arrives", [-0.1, 0.1])
def test_an_image_fetched_at_the_document_deadline_is_uploaded_and_kept(world, monkeypatch, arrives):
    """⛔⛔ The upload's timeouts are NOT the time left. Capped at it, a web saving for
    longer than 0.1 s stored the image while the client gave up: a caption in the
    document AND an object nothing references. The grace is the upload's."""
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.5)
    monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", 8.0)
    web = _saving_web(monkeypatch, save_sec=1.0)

    def fetch(url, deadline):
        time.sleep(max(0.0, deadline - time.monotonic() + arrives))
        return png()
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)
    assert rehost("![Big](https://img.example.com/big.png)") == f"![Big]({ref_for(png())})"
    assert web.stored == [png()] and web.timeouts == [(5.0, 30.0)]
    assert not any(level == "WARN" for level, _m in world.logs), world.logs
    (guard,) = web.guards
    guard._timer.join(1)
    assert web.closed == 1 and guard.expired and not guard._timer.is_alive()


@pytest.mark.parametrize("grace,started", [(3.0, False), (6.0, False), (7.5, True)])
def test_an_upload_with_no_time_to_finish_before_the_hard_stop_is_not_started(
        world, monkeypatch, grace, started):
    """It must end 2 s before the hard stop and needs 5 s of that: with a 0.2 s budget
    a 3 s or 6 s grace leaves 1.2 s or 4.2 s — nothing reaches the web, which would
    have stored it whatever the client did. 7.5 s leaves 5.7 s: the control."""
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.2)
    monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", grace)
    web = _saving_web(monkeypatch, save_sec=0.05)
    world.images["https://img.example.com/late.png"] = png()
    out = rehost("![Late](https://img.example.com/late.png)")
    assert world.fetches == ["https://img.example.com/late.png"]
    if started:
        assert out == f"![Late]({ref_for(png())})" and web.stored == [png()]
    else:
        assert out == "![Late]()" and web.stored == [] and web.timeouts == [] and web.guards == []
        assert world.logs[-1][1].endswith("stored=0 reused=0 dropped=0 refused=0 login=0 failed=1 "
                                          "linked=0 captioned=1 removed=0")
        # ⛔ Too little time is the RUN's condition, not the image's: nothing is
        # remembered, and the next document of the research (a fresh budget) stores it.
        monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", 30.0)
        assert rehost("![Late](https://img.example.com/late.png)") == f"![Late]({ref_for(png())})"
        assert world.fetches == ["https://img.example.com/late.png"] * 2 and web.stored == [png()]


_REAL_UPLOAD_SESSION = R._doc_img_upload_session


@contextlib.contextmanager
def web_server(tmp_path, head, drip, tls, every=0.2, for_sec=6.0):
    """A local web that RECEIVES the whole upload — stored, as the real web would,
    whatever the client does next — then answers `head` and drips `drip`."""
    ctx = cert = None
    if tls:
        cert, key = _self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert), str(key))
    lsock = socket.socket()
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(4)
    lsock.settimeout(0.1)
    stop = threading.Event()
    stored = []

    def serve():
        while not stop.is_set():
            try:
                raw, _ = lsock.accept()
            except OSError:
                continue
            conn = None
            try:
                raw.settimeout(3)
                conn = ctx.wrap_socket(raw, server_side=True) if ctx else raw
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        raise OSError("closed before the headers")
                    buf += chunk
                headers, _, body = buf.partition(b"\r\n\r\n")
                length = int(re.search(rb"(?im)^content-length:\s*(\d+)", headers).group(1))
                while len(body) < length:
                    chunk = conn.recv(65536)
                    if not chunk:
                        raise OSError("closed before the body")
                    body += chunk
                stored.append(body)
                conn.sendall(head)
                until = time.monotonic() + for_sec
                while not stop.is_set() and time.monotonic() < until:
                    conn.sendall(drip)
                    stop.wait(every)
            except (OSError, ssl.SSLError):
                pass
            finally:
                (conn or raw).close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    try:
        yield cert, lsock.getsockname()[1], stored
    finally:
        stop.set()
        th.join(5)
        lsock.close()


@pytest.mark.parametrize("tls", [True, False])
def test_an_upload_answered_a_byte_at_a_time_ends_before_the_hard_stop(world, tmp_path, monkeypatch, tls):
    """⛔⛔ A socket timeout bounds ONE receive: a web answering a byte every 0.2 s held
    the upload past the hard stop, and it stored an image the captioned document
    never references. The REAL upload session and guard, against a real local web
    (https as in production, http as in development)."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.2)
    monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", 2.0)
    monkeypatch.setattr(R, "_DOC_IMG_UPLOAD_MARGIN_SEC", 0.8)
    monkeypatch.setattr(R, "_DOC_IMG_UPLOAD_MIN_SEC", 0.5)
    made = _spy_deadlines(monkeypatch)
    url = "https://img.example.com/big.png"
    world.images[url] = png()
    with web_server(tmp_path, b"HTTP/1.1 200 OK\r\nX-Slow: ", b"a", tls) as (cert, port, stored):
        def session(guard):
            s = _REAL_UPLOAD_SESSION(guard)
            if cert:
                s.verify = str(cert)
            return s
        monkeypatch.setattr(R, "_doc_img_upload_session", session)
        monkeypatch.setattr("auth.v2_flow.FE_BASE_URL", f"{'https' if tls else 'http'}://{_LOOPBACK}:{port}")
        t0 = time.monotonic()
        out = rehost(f"![Big]({url})")
        elapsed = time.monotonic() - t0
    assert len(stored) == 1, "the upload never reached the local web — the test measured nothing"
    assert out == "![Big]()"
    # It ends at 0.2 + 2.0 - 0.8 = 1.4 s, while the funnel still waits (hard stop 2.2 s).
    assert 1.2 <= elapsed < 2.0, elapsed
    assert not any(level == "WARN" for level, _m in world.logs), world.logs
    (guard,) = made
    assert guard.expired and guard._socks == []


@pytest.mark.parametrize("comes_back", ["an image", "a refusal"])
def test_after_the_hard_stop_the_abandoned_worker_uploads_nothing_and_remembers_nothing(
        world, monkeypatch, comes_back):
    """⛔ The fetch comes back WHILE the fallback pass runs — the pass that reads the
    same cache — so a stop marked only after that pass is caught too."""
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.2)
    monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", 0.1)
    # The upload's time rule off, so only the stop mark can refuse the upload.
    monkeypatch.setattr(R, "_DOC_IMG_UPLOAD_MARGIN_SEC", -30.0)
    monkeypatch.setattr(R, "_DOC_IMG_UPLOAD_MIN_SEC", 0.0)
    done, release = threading.Event(), threading.Event()
    real = R._doc_images_rewrite_sync

    def rewrite(text, run):
        worker = threading.current_thread().name.startswith("doc-images")
        if not worker:
            release.set()
            assert done.wait(5), "the abandoned worker never finished"
        try:
            return real(text, run)
        finally:
            if worker:
                done.set()
    monkeypatch.setattr(R, "_doc_images_rewrite_sync", rewrite)

    def fetch(url, deadline):
        release.wait(5)
        if comes_back == "a refusal":
            # No upload to refuse: only the stop check before the cache write stands.
            raise R._DocImageRefused("failed")
        return png()
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)
    url = "https://img.example.com/stuck.png"
    try:
        assert rehost(f"![Stuck]({url})") == "![Stuck]()"
    finally:
        release.set()
    assert done.wait(5)
    assert any(level == "WARN" and "TimeoutError" in msg for level, msg in world.logs)
    assert world.posts == []
    assert url not in R._doc_img_cache.get(f"{UID}\x00{RID}", {})


def test_a_cancelled_rehost_stops_its_worker_before_the_upload_and_the_next_fetch(world, monkeypatch):
    """⛔ A cancelled task ends the wait long before any deadline: only the stop mark
    keeps its worker from uploading, fetching on and writing the cache."""
    done = _worker_done(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    fetched = []

    def fetch(url, deadline):
        fetched.append(url)
        entered.set()
        release.wait(5)
        return png(100 + len(fetched))
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)
    a, b = "https://img.example.com/a.png", "https://img.example.com/b.png"

    async def main():
        task = asyncio.create_task(R._rehost_document_images(f"![A]({a}) ![B]({b})", "ChatGPT"))
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return "cancelled"
        return "finished"
    try:
        assert asyncio.run(main()) == "cancelled"
    finally:
        release.set()
    assert done.wait(5)
    assert fetched == [a] and world.posts == []
    assert R._doc_img_cache.get(f"{UID}\x00{RID}", {}) == {}


def test_an_abandoned_workers_own_failure_is_never_remembered(world, monkeypatch):
    """⛔ The cut-off rule covers a fetch that ran out THIS document's budget — it
    reads the deadline. A cancel (a Stop, a gate-wait, the pipeline torn down) ends
    the wait with the whole budget still on the clock, and the fetch the cancel then
    breaks fails for the MOMENT. Remembered, that chart is a caption in every later
    document of the research, each with a budget of its own. The stop mark before
    the cache write is the only thing that stops it: the upload's own refusal never
    gets that far (it returns before the write), and neither does the deadline's.

    ⭐ The next document is run for real here — the cache is not the point, being
    fetched again is."""
    done = _worker_done(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    fake_web_fetch = R._doc_img_fetch
    url = "https://img.example.com/a.png"

    def fetch(u, deadline):
        entered.set()
        release.wait(5)
        # What a torn-down connection raises — the "failed" bucket, mid-read.
        raise R._DocImageRefused("failed")
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)

    async def main():
        task = asyncio.create_task(R._rehost_document_images(f"![A]({url})", "ChatGPT"))
        for _ in range(3000):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        # ⛔ Loudly on the SETUP, never as a puzzle later: a cancel before the pool
        # picked the job up drops the future, no worker ever runs, and the waits
        # below would fail for a reason that has nothing to do with the rule.
        assert entered.is_set(), "the worker never entered the fetch"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(main())
    finally:
        release.set()
    assert done.wait(5), "the abandoned worker never finished"
    assert R._doc_img_cache.get(f"{UID}\x00{RID}", {}) == {}
    # The document after it — its own budget — fetches the image and stores it.
    monkeypatch.setattr(R, "_doc_img_fetch", fake_web_fetch)
    world.images[url] = png()
    assert rehost(f"![A]({url})") == f"![A]({ref_for(png())})"
    assert world.fetches == [url]


# ═══ 21. repair round 3 (2026-09-14) — a Stop writes the document at once ══════
#
# ⛔⛔ A Stop in --serve exits the process 3 s later. A skipped or salvaged partial
# waited on its image fetches (up to the hard stop) before the finalize loop wrote
# it, under a status already saying "What it had written is in your documents."

@pytest.fixture
def controls(monkeypatch):
    c = R.PipelineControls()
    monkeypatch.setattr(R, "_controls", c)
    return c


def _schedule_exit_without_exiting(monkeypatch, source="firestore-command"):
    """⭐ Round 4: the offline pass is taken on a SCHEDULED EXIT, not on the Stop flag.
    This runs the REAL `_schedule_server_exit` — the helper every exit path calls —
    with only its exit thread kept from starting and its Firestore write stubbed."""
    held = []
    real_thread = threading.Thread

    class HeldExit(real_thread):
        def start(self):
            if getattr(getattr(self, "_target", None), "__name__", "") == "_runner":
                held.append(self)
                return None
            return super().start()
    monkeypatch.setattr(R, "_clear_current_run_id_best_effort", lambda *a, **k: None)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(threading, "Thread", HeldExit)
        R._schedule_server_exit(source)
    assert len(held) == 1 and R._exit_scheduled is True


def test_a_stop_before_the_results_funnel_writes_at_once_with_captions(world, controls, monkeypatch):
    """EXECUTED through `_rehost_result_texts` — the finalize re-save's, both regen
    loops' funnel. The Stop button's path: Stop, then the exit scheduled. No worker,
    no fetch, no token, no upload; a reference and a cache hit stay stored, the rest
    are captions."""
    kept = "https://img.example.com/kept.png"
    world.images[kept] = png()
    rehost(f"![Kept]({kept})")
    assert world.fetches == [kept] and len(world.posts) == 1 and world.token_calls == 1
    monkeypatch.setattr(R, "_doc_img_executor", lambda: pytest.fail("a worker started after the Stop"))
    controls.request_stop()
    _schedule_exit_without_exiting(monkeypatch)
    new ="https://img.example.com/new.png"
    world.images[new] = png(200, 100)
    stored = ref_for(gif())
    results = {"Gemini": {"text": f"Partial ![Kept]({kept}) ![New]({new}) ![Old]({stored})",
                          "status": "skipped"}}
    t0 = time.monotonic()
    asyncio.run(R._rehost_result_texts(results))
    assert time.monotonic() - t0 < 0.5
    assert results["Gemini"]["text"] == f"Partial ![Kept]({ref_for(png())}) ![New]() ![Old]({stored})"
    assert world.fetches == [kept] and len(world.posts) == 1 and world.token_calls == 1
    assert new not in R._doc_img_cache[f"{UID}\x00{RID}"]
    assert any(level == "WARN" and "_DocImgStopRequested" in msg for level, msg in world.logs)


def test_a_stop_before_the_per_agent_save_writes_it_at_once_with_captions(monkeypatch, tmp_path, world, controls):
    """EXECUTED — the save the round-robin makes when an agent finishes."""
    monkeypatch.setattr(R, "_doc_img_executor", lambda: pytest.fail("a worker started after the Stop"))
    controls.request_stop()
    _schedule_exit_without_exiting(monkeypatch, "http-endpoint")
    result, saved = _drive_extract(monkeypatch, tmp_path, world)
    local = (tmp_path / "documents" / "chatgpt.md").read_text(encoding="utf-8")
    assert local == "# ChatGPT Deep Research\n\nFindings ![Market chart]() end"
    assert saved == [("chatgpt", local)] and result["text"] == "Findings ![Market chart]() end"
    assert world.fetches == [] and world.posts == []


def test_a_stop_while_images_are_fetched_writes_at_once_and_the_worker_stores_nothing(
        world, controls, monkeypatch):
    """⛔ The Stop lands while the worker is inside a fetch: the document is written
    with captions within a poll, and the abandoned worker uploads and remembers
    nothing."""
    done = _worker_done(monkeypatch)
    entered, release = threading.Event(), threading.Event()

    def fetch(url, deadline):
        entered.set()
        release.wait(3)
        return png()
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)
    url = "https://img.example.com/slow.png"

    async def main():
        task = asyncio.create_task(R._rehost_document_images(f"![Slow]({url})", "Gemini"))
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        t0 = time.monotonic()
        controls.request_stop()
        _schedule_exit_without_exiting(monkeypatch, "agent-decision-stop")
        out = await task
        return out, time.monotonic() - t0
    try:
        out, elapsed = asyncio.run(main())
    finally:
        release.set()
    assert out == "![Slow]()" and elapsed < 1.0, elapsed
    assert done.wait(5)
    assert world.posts == [] and R._doc_img_cache.get(f"{UID}\x00{RID}", {}) == {}
    assert any(level == "WARN" and "_DocImgStopRequested" in msg for level, msg in world.logs)


def test_a_pause_still_rehosts(world, controls):
    """⭐ Stop, NOT pause: a pause exits nothing, and a caption can never become an
    image again — the source address is gone from the text. Paused before the call
    and throughout a fetch longer than a poll."""
    controls.request_pause()
    world.fetch_delay = 0.6
    url = "https://img.example.com/paused.png"
    world.images[url] = png()
    assert rehost(f"![P]({url})") == f"![P]({ref_for(png())})"
    assert world.fetches == [url] and len(world.posts) == 1


# ═══ 22. repair round 3 — what is remembered for the rest of the research ══════

def _fetch_that_ends_at_its_deadline(monkeypatch, outcomes):
    """Each call waits for its own deadline to pass, then takes the next outcome:
    an exception is raised, bytes are returned."""
    calls = []

    def fetch(url, deadline):
        calls.append(url)
        got = outcomes[min(len(calls), len(outcomes)) - 1]
        time.sleep(max(0.0, deadline - time.monotonic()) + 0.02)
        if isinstance(got, BaseException):
            raise got
        return got
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)
    return calls


@pytest.mark.parametrize("cut", [R._DocImageRefused("failed"),
                                 requests.ConnectionError("shut at the deadline")],
                         ids=["the timer's refusal", "the shut connection's error"])
def test_an_image_cut_off_by_the_document_deadline_is_fetched_again_by_the_next_document(
        world, monkeypatch, cut):
    """⛔ It started with little of the document's budget left. The next document of
    the research has a fresh budget — and used to read a cached failure instead."""
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.3)
    url = "https://img.example.com/late-chart.png"
    calls = _fetch_that_ends_at_its_deadline(monkeypatch, [cut])
    assert rehost(f"![Chart]({url})", "ChatGPT") == "![Chart]()"
    assert world.logs[-1][1].endswith("failed=1 linked=0 captioned=1 removed=0")
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 5.0)
    monkeypatch.setattr(R, "_doc_img_fetch", lambda u, d: (calls.append(u), png())[1])
    assert rehost(f"again ![Chart]({url})", "Gemini") == f"again ![Chart]({ref_for(png())})"
    assert calls == [url, url]


@pytest.mark.parametrize("case", ["the per-image limit", "a login-only answer at the deadline",
                                  "bytes read by the deadline that are not an image"])
def test_what_the_document_deadline_did_not_cut_off_is_still_remembered(world, monkeypatch, case):
    url = "https://img.example.com/c.png"
    if case == "the per-image limit":
        monkeypatch.setattr(R, "_DOC_IMG_PER_IMAGE_SEC", 0.2)
        monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 5.0)
        outcome = R._DocImageRefused("failed")
    else:
        monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.3)
        outcome = (R._DocImageRefused("login") if case.startswith("a login")
                   else b"<svg>not a raster</svg>")
    calls = _fetch_that_ends_at_its_deadline(monkeypatch, [outcome])
    assert rehost(f"![C]({url})") == "![C]()"
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 5.0)
    assert rehost(f"again ![C]({url})") == "again ![C]()"
    assert calls == [url]


@pytest.mark.parametrize("passing", [
    lambda body: FakeWebResponse(503, {"error": "storage"}),
    lambda body: FakeWebResponse(500, None, raise_json=True),
    requests.ConnectionError("reset by peer"),
    requests.ReadTimeout("no answer"),
    R._DocImageRefused("failed"),
    requests.exceptions.ProxyError("proxy unreachable"),
    requests.ConnectTimeout("no connect"),
    requests.exceptions.ChunkedEncodingError("body cut off"),
    ConnectionResetError("a bare reset"),
    TimeoutError("a bare socket timeout"),
], ids=["503", "500 not json", "connection reset", "read timeout", "the guard's refusal",
        "proxy unreachable", "connect timeout", "body cut off", "bare reset", "bare timeout"])
def test_a_passing_upload_failure_is_not_remembered_and_the_next_document_stores_it(world, passing):
    """⛔ A one-off web failure used to caption that chart in every later document."""
    url = "https://img.example.com/chart.png"
    world.images[url] = png()
    answers = []

    def web(body):
        answers.append(1)
        if len(answers) == 1:
            if isinstance(passing, BaseException):
                raise passing
            return passing(body)
        return FakeWebResponse(200, {"ref": ref_for(png())})
    world.web = web
    assert rehost(f"![Chart]({url})", "ChatGPT") == "![Chart]()"
    assert rehost(f"![Chart]({url})", "Claude") == f"![Chart]({ref_for(png())})"
    assert world.fetches == [url, url] and len(answers) == 2


@pytest.mark.parametrize("answer", [
    400, 401, 403, 404, 413, 499,
    requests.exceptions.InvalidURL("Invalid URL 'https://': No host supplied"),
    requests.exceptions.MissingSchema("Invalid URL 'localhost:3000/api': No scheme supplied"),
    requests.exceptions.InvalidSchema("No connection adapters were found"),
    requests.exceptions.InvalidHeader("Invalid leading whitespace in header value"),
    requests.exceptions.SSLError("certificate verify failed: self-signed certificate"),
    requests.exceptions.ContentDecodingError("the answer cannot be decoded"),
    OSError("Could not find a suitable TLS CA certificate bundle"),
], ids=["400", "401", "403", "404", "413", "499", "invalid url", "missing schema",
        "invalid schema", "invalid header", "certificate", "undecodable body", "no ca bundle"])
def test_a_definite_upload_refusal_is_remembered(world, answer):
    """⛔ A misconfigured FE base URL or a certificate that fails verification fails
    every upload the same way: not remembered, every later document fetched the
    image again only to fail the upload again."""
    url = "https://img.example.com/chart.png"
    world.images[url] = png()
    answers = []

    def web(body):
        answers.append(1)
        if len(answers) > 1:
            return FakeWebResponse(200, {"ref": ref_for(png())})
        if isinstance(answer, BaseException):
            raise answer
        return FakeWebResponse(answer, {"error": "no"})
    world.web = web
    assert rehost(f"![Chart]({url})") == "![Chart]()"
    assert rehost(f"again ![Chart]({url})") == "again ![Chart]()"
    assert world.fetches == [url] and len(answers) == 1


def test_an_untrusted_certificate_on_the_real_upload_is_remembered(world, tmp_path, monkeypatch):
    """The REAL upload session against a local https web whose certificate it does
    not trust: requests raises SSLError, and it fails the same way every time."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                 "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    url = "https://img.example.com/chart.png"
    world.images[url] = png()
    raised = _record_real_upload_errors(monkeypatch)
    with web_server(tmp_path, b"HTTP/1.1 200 OK\r\n\r\n", b"", tls=True, for_sec=0.0) as (_c, port, stored):
        monkeypatch.setattr("auth.v2_flow.FE_BASE_URL", f"https://{_LOOPBACK}:{port}")
        assert rehost(f"![Chart]({url})") == "![Chart]()"
        assert rehost(f"again ![Chart]({url})") == "again ![Chart]()"
    assert stored == [] and [type(e) for e in raised] == [requests.exceptions.SSLError], raised
    assert "CERTIFICATE_VERIFY_FAILED" in str(raised[0])
    assert world.fetches == [url]


def _record_real_upload_errors(monkeypatch):
    """The REAL upload session; every error its post raises, in order."""
    raised = []

    def session(guard):
        s = _REAL_UPLOAD_SESSION(guard)
        real_post = s.post

        def post(*a, **kw):
            try:
                return real_post(*a, **kw)
            except BaseException as e:
                raised.append(e)
                raise
        s.post = post
        return s
    monkeypatch.setattr(R, "_doc_img_upload_session", session)
    return raised


@contextlib.contextmanager
def _silent_tls_web():
    """A local web that accepts the TCP connection and never starts TLS."""
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(4)
    held = []

    def serve():
        while True:
            try:
                conn, _ = lsock.accept()
            except OSError:
                return
            held.append(conn)
    th = threading.Thread(target=serve, daemon=True)
    th.start()
    try:
        yield lsock.getsockname()[1], held
    finally:
        lsock.close()
        for conn in held:
            conn.close()
        th.join(2)


def test_a_tls_handshake_the_upload_guard_cut_is_not_remembered(world, monkeypatch):
    """⛔⛔ The guard shutting a TLS handshake at its end raises requests' SSLError —
    the class a certificate failure raises. It is the run's clock, not the image:
    the next document of the research stores the chart."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.2)
    monkeypatch.setattr(R, "_DOC_IMG_HARD_STOP_GRACE_SEC", 2.0)
    monkeypatch.setattr(R, "_DOC_IMG_UPLOAD_MARGIN_SEC", 0.8)
    monkeypatch.setattr(R, "_DOC_IMG_UPLOAD_MIN_SEC", 0.5)
    url = "https://img.example.com/chart.png"
    world.images[url] = png()
    fake_session = R._doc_img_upload_session
    raised = _record_real_upload_errors(monkeypatch)
    with _silent_tls_web() as (port, held):
        monkeypatch.setattr("auth.v2_flow.FE_BASE_URL", f"https://{_LOOPBACK}:{port}")
        t0 = time.monotonic()
        assert rehost(f"![Chart]({url})", "ChatGPT") == "![Chart]()"
        elapsed = time.monotonic() - t0
    assert held, "the upload never connected — the test measured nothing"
    assert 1.2 <= elapsed < 2.0, elapsed
    # The class a certificate failure raises — only the guard's state tells them
    # apart. ⛔ ON WINDOWS IT IS `ConnectionError`, and for the same reason: the
    # guard cannot cut a handshake with `shutdown` there (it returns success and
    # does nothing), so it closes abortively and the RST surfaces as
    # ProtocolError/ConnectionAbortedError rather than an SSL error. The point of
    # the assertion survives either way — the class is one a REAL network or
    # certificate failure also raises, so it cannot be used to decide whether to
    # remember the refusal. What proves that is two lines below: the chart is
    # fetched again and stored by the next document.
    _cut_classes = ([requests.exceptions.SSLError, requests.exceptions.ConnectionError]
                    if sys.platform == "win32" else [requests.exceptions.SSLError])
    assert [type(e) for e in raised] != [], "nothing was raised - the test measured nothing"
    assert all(type(e) in _cut_classes for e in raised), raised
    monkeypatch.setattr(R, "_doc_img_upload_session", fake_session)
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 5.0)
    assert rehost(f"![Chart]({url})", "Claude") == f"![Chart]({ref_for(png())})"
    assert world.fetches == [url, url]


# ═══ 23. repair round 3 — a link around an image to a platform's host ══════════

LH3_FULL = "https://lh3.googleusercontent.com/SIGNED-chart=s0"


@pytest.mark.parametrize("kept", [True, False], ids=["stored", "captioned"])
def test_a_click_to_enlarge_link_to_another_size_on_the_platform_host_goes(world, kept):
    """⛔ `<a href="…=s0"><img src="…=w800">`: the href is not the image's own source,
    and the signed platform URL stayed in the document and every share."""
    md = R.html_to_markdown(f'<p>See <a href="{LH3_FULL}"><img src="{SIGNED}" alt="Chart"></a> end</p>')
    assert md == f"See [![Chart](<{SIGNED}>)]({LH3_FULL}) end"
    world.images[SIGNED] = png() if kept else R._DocImageRefused("failed")
    out = rehost(md)
    assert out == (f"See ![Chart]({ref_for(png())}) end" if kept else "See ![Chart]() end")
    assert "googleusercontent" not in out


def test_a_link_around_an_image_to_a_platform_product_host_goes(world):
    src = "https://cdn.example.com/chart.png"
    href = "https://files.oaiusercontent.com/file-abc?se=2026&sig=x"
    md = R.html_to_markdown(f'<p><a href="{href}"><img src="{src}" alt="Chart"> Open</a></p>')
    world.images[src] = png()
    assert rehost(md) == f"![Chart]({ref_for(png())}) Open"


# ═══ 24. repair round 3 — one image connection is bounded by the image's clock ═
#
# ⛔ urllib3's create_connection tried EVERY resolved address with the full 5 s
# connect timeout before a socket existed for the deadline to watch: thirty silent
# addresses held the worker ~150 s. Driven through the REAL fetch → requests →
# urllib3 chain; only the resolver and the sockets are fakes.

def _unreachable_host(monkeypatch, n, refuse):
    stop = threading.Event()
    made, lookups = [], []

    class Addrs(list):
        # urllib3's own loop walks this — it stops once the test is over, so a
        # surviving mutant's thread does not go on trying the rest.
        def __iter__(self):
            for item in list.__iter__(self):
                if stop.is_set():
                    return
                yield item

    def getaddrinfo(host, port, *a, **k):
        lookups.append(host)
        # Public addresses (the sockets are fakes): a private one is skipped before
        # any socket is made, and would measure nothing here.
        return Addrs([(socket.AF_INET, socket.SOCK_STREAM, 6, "", (f"93.184.216.{i + 1}", port))
                      for i in range(n)])

    class Sock:
        def __init__(self, *a, **k):
            self.timeout = None
            made.append(self)

        def setsockopt(self, *a):
            pass

        def settimeout(self, t):
            if t is not None and t < 0:
                raise ValueError("Timeout value out of range")
            self.timeout = t

        def connect(self, addr):
            if refuse:
                raise ConnectionRefusedError(61, "Connection refused")
            end = time.monotonic() + (60.0 if self.timeout is None else self.timeout)
            while not stop.is_set() and time.monotonic() < end:
                stop.wait(max(0.0, end - time.monotonic()))
            raise socket.timeout("timed out")

        def close(self):
            pass
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "socket", Sock)
    monkeypatch.setattr(R, "_doc_img_check_url", lambda url: None)
    return stop, made, lookups


def test_an_image_host_with_many_silent_addresses_ends_at_the_image_deadline(monkeypatch):
    stop, made, lookups = _unreachable_host(monkeypatch, 30, refuse=False)
    try:
        th, box = _fetch_in_thread("https://img.example.com/a.png", 0.6, 2.5)
        alive = th.is_alive()
    finally:
        stop.set()
    th.join(5)
    assert not alive, "the connect outlived the image's deadline"
    assert isinstance(box.get("error"), R._DocImageRefused) and box["error"].kind == "failed", box
    assert box["elapsed"] < 1.3, box
    assert lookups == ["img.example.com"] and len(made) == 1 and made[0].timeout <= 0.6


def test_one_image_connection_tries_only_a_few_of_the_addresses(monkeypatch):
    stop, made, lookups = _unreachable_host(monkeypatch, 30, refuse=True)
    try:
        th, box = _fetch_in_thread("https://img.example.com/a.png", 5.0, 4.0)
    finally:
        stop.set()
    assert not th.is_alive()
    assert isinstance(box.get("error"), R._DocImageRefused), box
    assert len(made) == R._DOC_IMG_CONNECT_ADDRS == 4 and lookups == ["img.example.com"]


def test_no_lookup_and_no_connect_once_the_image_deadline_has_passed(monkeypatch):
    stop, made, lookups = _unreachable_host(monkeypatch, 3, refuse=True)
    session = R._doc_img_session(R._DocImgDeadline(time.monotonic() - 0.01))
    try:
        with pytest.raises(R._DocImageRefused):
            session.get("https://img.example.com/a.png", stream=True, allow_redirects=False,
                        timeout=(1, 1))
    finally:
        stop.set()
    assert lookups == [] and made == []


# ═══ 25. repair round 3 — image URLs do not count toward an extraction's length ═
#
# ⛔ The floors and Claude's length-sanity check run before the rehost shrinks the
# URLs: three signed chart URLs lifted a wrong artifact past the 30% check.

LONG_IMG = "https://lh3.googleusercontent.com/" + "x" * 700


def test_image_destinations_do_not_count_toward_a_documents_length():
    text = f"Short prose. ![Chart](<{LONG_IMG}>) ![Q3]({LONG_IMG} \"t\") ![Ref][1] end"
    assert R._doc_img_prose_len(text) == len("Short prose. ![Chart]() ![Q3]() ![Ref][1] end")
    assert R._doc_img_prose_len("no images at all") == len("no images at all")
    assert R._doc_img_prose_len("") == 0 and R._doc_img_prose_len(None) == 0


class _EvalPage:
    def __init__(self, html):
        self.html = html

    async def evaluate(self, js, *a):
        return self.html


def test_the_html_capture_floor_does_not_count_image_urls(monkeypatch):
    """EXECUTED — `_extract_html_to_md`, the HTML route every platform's capture uses."""
    monkeypatch.setattr(R, "log", lambda *a, **k: None)
    sparse = f'<div><p>Tiny ack.</p><img src="{LONG_IMG}" alt="Chart"></div>'
    assert asyncio.run(R._extract_html_to_md(_EvalPage(sparse), [".markdown"], "Gemini")) == ""
    rich = f'<div><p>{"Real report prose. " * 8}</p><img src="{LONG_IMG}" alt="Chart"></div>'
    assert asyncio.run(R._extract_html_to_md(_EvalPage(rich), [".markdown"], "Gemini")).startswith(
        "Real report prose.")


def test_the_frame_density_floor_does_not_count_image_urls(monkeypatch):
    """EXECUTED — the ChatGPT Deep Research frame's density fallback."""
    monkeypatch.setattr(R, "log", lambda *a, **k: None)

    async def no_selector_hit(target, selectors, label):
        return ""
    monkeypatch.setattr(R, "_extract_html_to_md", no_selector_hit)
    frame = _EvalPage(f'<div><p>{"Words here. " * 20}</p><img src="{LONG_IMG}" alt="Chart"></div>')
    monkeypatch.setattr(R, "_chatgpt_dr_frame_targets", lambda page: [_EvalPage(""), frame])
    assert asyncio.run(R._extract_html_to_md_anyframe(object(), [".markdown"], "ChatGPT")) == ""
    frame.html = f'<div><p>{"Words here. " * 50}</p><img src="{LONG_IMG}" alt="Chart"></div>'
    assert asyncio.run(R._extract_html_to_md_anyframe(object(), [".markdown"], "ChatGPT")).startswith(
        "Words here.")


@pytest.mark.parametrize("fn,floor", [
    ("_copy_via_hijack", "if md and _doc_img_prose_len(md) >= min_chars:"),
    ("extract_chatgpt_response", "if md and _doc_img_prose_len(md) > 2000:"),
    ("extract_gemini_response", "if md and _doc_img_prose_len(md) > 2000:"),
    ("extract_claude_response", "if md_chat and _doc_img_prose_len(md_chat) > 100:"),
    # Round 4: Claude's artifact-panel DOM scrape (T2), the last one left raw.
    ("extract_claude_response", "if md_dom and _doc_img_prose_len(md_dom) > 2000:"),
])
def test_every_other_floor_on_converter_output_measures_without_image_urls(fn, floor):
    """SOURCE PIN — these tiers need a live page, a CUA or a clipboard. Each floor on
    the converter's output measures prose. ⚠ The text/plain and clipboard floors are
    not changed: their platform markdown carried image URLs before wave 4 too."""
    assert code_only(getattr(R, fn)).count(floor) == 1


def _drive_claude_extract(monkeypatch, tmp_path, world, text, expected):
    events = []

    async def extract(page, **kw):
        return text

    async def save(doc_type, content, name=None, **kw):
        return True

    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(R, "extract_claude_response", extract)
    monkeypatch.setattr(R, "reject_off_topic_text", lambda t, *a, **k: t)
    monkeypatch.setattr(R, "save_document_to_firestore_with_retry", save)
    monkeypatch.setattr(R, "_firebase_db", object())
    monkeypatch.setattr(R, "emit_event", lambda name, **k: events.append((name, k)))
    monkeypatch.setattr(R, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(R.asyncio, "sleep", no_sleep)
    asyncio.run(R.extract_and_record_agent("Claude", _Page(), _Browser(), None, tmp_path,
                                           expected_text_len=expected))
    return [k for name, k in events if name == "wrong_artifact_rejected"]


def test_the_length_sanity_check_does_not_count_image_urls(monkeypatch, tmp_path, world):
    """EXECUTED — `extract_and_record_agent`. The tracker streamed 20,000 characters;
    the extraction is 4,000 of prose and three signed chart URLs, 6,000+ in all."""
    imgs = "".join(f" ![Chart {i}]({LONG_IMG}{i})" for i in range(3))
    wrong = "Wrong artifact. " * 250 + imgs
    assert len(wrong) >= 6000 > R._doc_img_prose_len(wrong)
    rejected = _drive_claude_extract(monkeypatch, tmp_path, world, wrong, 20000)
    assert [r["length"] for r in rejected] == [R._doc_img_prose_len(wrong)]
    assert not (tmp_path / "documents" / "claude.md").exists() and world.fetches == []
    right = "Right artifact. " * 410 + imgs
    assert _drive_claude_extract(monkeypatch, tmp_path, world, right, 20000) == []
    assert (tmp_path / "documents" / "claude.md").exists()


# ═══ 26. repair round 4 (2026-09-14) — a Stop with no exit coming still stores ══
#
# ⛔⛔ Round 3 took every Stop as "the process exits in 3 s". The 24-hour pause
# limit, a cancel in the gate wait and a foreground hard reset set the Stop and exit
# nothing: the run finalizes, and its unsaved documents' images became captions for
# good. The offline pass is now taken on a SCHEDULED EXIT only.

def test_a_stop_with_no_exit_coming_still_rehosts(world, controls):
    controls.request_stop()
    url = "https://img.example.com/stopped.png"
    world.images[url] = png()
    assert rehost(f"![S]({url})") == f"![S]({ref_for(png())})"
    assert world.fetches == [url] and len(world.posts) == 1


def test_a_stop_with_no_exit_coming_during_a_fetch_still_rehosts(world, controls):
    """The Stop lands while the worker is inside a fetch longer than a poll."""
    world.fetch_delay = 0.6
    url = "https://img.example.com/slow-stop.png"
    world.images[url] = png()

    async def main():
        task = asyncio.create_task(R._rehost_document_images(f"![S]({url})", "Gemini"))
        for _ in range(500):
            if world.fetches:
                break
            await asyncio.sleep(0.01)
        controls.request_stop()
        return await task
    assert asyncio.run(main()) == f"![S]({ref_for(png())})"
    assert world.fetches == [url] and len(world.posts) == 1


def test_the_pause_limit_stops_the_run_and_its_partials_still_store_their_images(
        world, controls, monkeypatch):
    """EXECUTED — `wait_if_paused` giving up (its bound shrunk), then the finalize
    funnel. The finding's scenario: nobody answered a parked agent for 24 hours."""
    monkeypatch.setattr(R, "PAUSE_HEARTBEAT_S", 0.01)
    monkeypatch.setattr(R, "PAUSE_MAX_WAIT_S", 0.02)
    url = "https://img.example.com/parked.png"
    world.images[url] = png()
    results = {"Claude": {"text": f"Partial ![Chart]({url})", "status": "skipped"}}

    async def main():
        controls.request_pause("a parked agent's retry or skip")
        await controls.wait_if_paused()
        assert controls.is_stop() and controls._pause_gave_up and R._exit_scheduled is False
        await R._rehost_result_texts(results)
    asyncio.run(main())
    assert results["Claude"]["text"] == f"Partial ![Chart]({ref_for(png())})"
    assert world.fetches == [url] and len(world.posts) == 1


def test_an_exit_scheduled_with_no_stop_pressed_writes_at_once(world, controls, monkeypatch):
    """The process goes whatever scheduled it: an exit alone takes the offline pass."""
    monkeypatch.setattr(R, "_doc_img_executor",
                        lambda: pytest.fail("a worker started with the exit scheduled"))
    _schedule_exit_without_exiting(monkeypatch, "device-update")
    assert not controls.is_stop()
    url = "https://img.example.com/exit.png"
    world.images[url] = png()
    assert rehost(f"![E]({url})") == "![E]()"
    assert world.fetches == [] and world.posts == []


# ═══ 27. repair round 4 — no TCP handshake with an address that is not public ══
#
# ⛔ The connect resolved the name a second time and completed a handshake with
# whatever came back; the peer check closed a LAN socket only after it.

def _connect_world(monkeypatch, addrs, refuse=False):
    made, connected = [], []

    class Sock:
        def __init__(self, *a, **k):
            made.append(self)

        def setsockopt(self, *a):
            pass

        def settimeout(self, t):
            pass

        def connect(self, addr):
            connected.append(addr[0])
            if refuse:
                raise ConnectionRefusedError(61, "Connection refused")

        def close(self):
            pass

    def getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (ip, port)) for ip in addrs]
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "socket", Sock)
    return made, connected


def test_the_connect_makes_no_socket_for_an_address_that_is_not_public(monkeypatch):
    """⛔⛔ DNS rebinding: the URL check saw a public answer, the connect's own lookup
    answers LAN hosts. No socket is made, so no handshake reaches them."""
    made, connected = _connect_world(
        monkeypatch, ["10.0.0.7", "127.0.0.1", "fe80::1%en0", "169.254.169.254"])
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_connect("img.example.com", 443, far())
    assert made == [] and connected == []
    assert got.value.kind == "refused"


def test_the_real_chain_refuses_a_rebound_name_before_any_socket(monkeypatch):
    """The consumer: requests → urllib3 → `_new_conn` → `_doc_img_connect`."""
    made, connected = _connect_world(monkeypatch, ["10.0.0.7"])
    session = R._doc_img_session(R._DocImgDeadline(far()))
    with pytest.raises(R._DocImageRefused) as got:
        session.get("https://img.example.com/a.png", stream=True, allow_redirects=False,
                    timeout=(1, 1))
    assert got.value.kind == "refused" and made == [] and connected == []


def test_the_connect_skips_the_private_answer_and_connects_to_the_public_one(monkeypatch):
    made, connected = _connect_world(monkeypatch, ["10.0.0.7", "93.184.216.34"])
    sock = R._doc_img_connect("img.example.com", 443, far())
    assert connected == ["93.184.216.34"] and made == [sock]


def test_a_public_address_that_fails_after_a_skipped_one_is_a_failure(monkeypatch):
    """Only 'nothing public to try' is a refusal; a public host that did not answer
    is the ordinary failure it always was."""
    made, connected = _connect_world(monkeypatch, ["10.0.0.7", "93.184.216.34"], refuse=True)
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_connect("img.example.com", 443, far())
    assert connected == ["93.184.216.34"] and got.value.kind == "failed"


# ═══ 28. repair round 4 — a heading's image is not its title ════════════════════

HEADING_REF = f"/document-images/{RID}/{'d' * 64}.png"


def test_heading_titles_carry_no_image_markup():
    assert R._find_heading_title(f"![Logo]({HEADING_REF}) Market overview") == "Market overview"
    assert R._find_heading_title(f"Q3 ![Chart]({HEADING_REF}) results") == "Q3 results"
    assert R._find_heading_title(f"[![Logo]({HEADING_REF})](https://example.org) Home") == "Home"
    assert R._find_heading_title(f"![Only]({HEADING_REF})") == ""
    assert R._find_heading_title("Plain  heading  ") == "Plain  heading  "


def test_save_meta_sections_carry_no_image_markup(tmp_path, monkeypatch):
    """EXECUTED — `save_meta`: agents.<platform>.sections, and the findings fallback
    built from them when there are no cited findings."""
    (tmp_path / "documents").mkdir()
    body = (f"# Claude Deep Research\n\n## ![Logo]({HEADING_REF}) Market overview\n\nText.\n\n"
            f"## Q3 ![Chart]({HEADING_REF}) results\n\n## ![Only]({HEADING_REF})\n\n"
            "## Plain  heading  \n\n" + "filler line to clear the size gate. " * 8)
    (tmp_path / "documents" / "claude.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(R, "_runtime", types.SimpleNamespace(agent_progress_snapshots={}),
                        raising=False)
    R.save_meta(tmp_path, "a topic", 2)
    got = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["agents"]["claude"]
    assert got["sections"] == ["Market overview", "Q3 results", "Plain  heading  "]
    assert got["findings"] == ["Market overview", "Q3 results", "Plain  heading  "]


def _claude_sections(tmp_path, monkeypatch, body):
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "claude.md").write_text(
        "# Claude Deep Research\n\n" + body + "filler line to clear the size gate. " * 8,
        encoding="utf-8")
    monkeypatch.setattr(R, "_runtime", types.SimpleNamespace(agent_progress_snapshots={}),
                        raising=False)
    R.save_meta(tmp_path, "a topic", 2)
    return json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["agents"]["claude"]


def test_save_meta_dedupes_sections_on_their_titles_not_their_image_markup(tmp_path, monkeypatch):
    """EXECUTED — fixup: the dedupe ran on the raw strings, so a heading with a logo
    and the bold line under it were two sections both called "Overview"."""
    got = _claude_sections(tmp_path, monkeypatch,
                           f"## ![Logo]({HEADING_REF}) Overview\n\nText.\n\n**Overview**\n\n")
    assert got["sections"] == ["Overview"]


def test_image_only_headings_do_not_count_toward_skipping_the_bold_fallback(tmp_path, monkeypatch):
    """EXECUTED — fixup: two image-only headings counted as sections, the bold
    fallback was skipped, and then both were dropped — one section left."""
    got = _claude_sections(tmp_path, monkeypatch,
                           f"## ![A]({HEADING_REF})\n\n## ![B]({HEADING_REF})\n\n"
                           "## Real heading\n\n**Bold Section Title**\n\n")
    assert got["sections"] == ["Real heading", "Bold Section Title"]


def test_a_bold_section_line_is_titled_without_its_image_caption(tmp_path, monkeypatch):
    """EXECUTED — an image that could not be kept is `![Chart]()`, short enough for
    the bold fallback's 80 characters."""
    got = _claude_sections(tmp_path, monkeypatch,
                           "## Only heading\n\n**![Chart]() Quarterly revenue**\n\n")
    assert got["sections"] == ["Only heading", "Quarterly revenue"]


def test_a_finding_under_a_heading_with_an_image_is_titled_by_that_heading():
    """EXECUTED — `_extract_findings`. The rehosted reference pushed the heading past
    80 characters, and the finding took the heading above as its source title. An
    image-only heading still ends the section above it."""
    # ⚠ 2026-09-19 — THE URLS ARE BARE NOW, AND THAT IS THE POINT OF THE EDIT.
    # They used to be `[Reuters](…)` and `[Source](…)`. Once `_extract_findings`
    # learned to read a link's own label as the page title, those labels won and
    # this test passed without ever consulting a heading — it would have gone on
    # reporting green while the image-in-heading handling it is named for rotted
    # away underneath it. Bare mentions keep the heading rung as the rung under
    # test.
    md = ("## Background\n\nOld context sits here for the reader.\n\n"
          f"## ![Company logo]({HEADING_REF}) Market overview\n\n"
          "Revenue grew 40% last year according to https://www.reuters.com/markets/a today.\n\n"
          f"## ![Only]({HEADING_REF})\n\n"
          "Margins fell sharply in the quarter per https://www.example.org/src data.\n")
    assert len(f"![Company logo]({HEADING_REF}) Market overview") > 80
    got = {f["url"]: f["sourceTitle"] for f in R._extract_findings(md, [])}
    assert got == {"https://www.reuters.com/markets/a": "Market overview",
                   "https://www.example.org/src": "example.org"}


# ═══ 29. repair round 4 — a brief supplied with phase 1 skipped is rehosted ═════
#
# ⛔ The skip branch read the brief back with no rehost: a data: URI or a platform
# URL stayed in brief.md and in what every phase-2 agent was pasted.

def _brief_images(world):
    url = "https://img.example.com/brief.png"
    world.images[url] = png()
    data = "data:image/gif;base64," + base64.b64encode(gif()).decode()
    text = f"Plan ![Chart]({url}) and ![Pasted]({data}) end"
    return text, f"Plan ![Chart]({ref_for(png())}) and ![Pasted]({ref_for(gif())}) end"


def test_a_skipped_phase_1_brief_is_rehosted_and_the_runs_brief_md_rewritten(world, tmp_path):
    """EXECUTED — `_rehost_skipped_brief` on the inline brief's path: read back from
    the run's own documents/brief.md."""
    text, want = _brief_images(world)
    local = tmp_path / "documents" / "brief.md"
    local.parent.mkdir()
    local.write_text(f"# Research Brief\n\n{text}", encoding="utf-8")
    out = asyncio.run(R._rehost_skipped_brief(tmp_path, text, local))
    assert out == want
    assert local.read_text(encoding="utf-8") == f"# Research Brief\n\n{want}"


def test_the_owners_own_brief_file_is_never_rewritten_and_no_brief_md_is_made(
        world, tmp_path, monkeypatch):
    """⛔ The run's brief.md is refused BY NAME — it is never even opened. Pinned on
    the open, not on what a missing file happens to raise or log: a run that has one
    (a resume) is the test below, and here nothing but the name stands."""
    text, want = _brief_images(world)
    own = tmp_path / "my-brief.md"
    own.write_text(text, encoding="utf-8")
    run = tmp_path / "run"
    (run / "documents").mkdir(parents=True)
    local = run / "documents" / "brief.md"
    opened: list = []
    real_read_text = Path.read_text
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: (opened.append(Path(self)), real_read_text(self, *a, **kw))[1])
    assert asyncio.run(R._rehost_skipped_brief(run, text, own)) == want
    assert local not in opened
    assert not local.exists()
    assert own.read_text(encoding="utf-8") == text


def test_a_resumes_brief_md_is_left_alone_when_the_owner_named_another_file(world, tmp_path):
    """⛔ A resume ALREADY HAS a documents/brief.md — the one phase 3 ingests and the
    phase-2 attachment reads. An owner who then passes their own --brief-file holding
    that same brief must not have the run's copy rewritten under them: only the file
    the brief was actually read from is rewritten, and `.resolve()` is what decides."""
    text, want = _brief_images(world)
    own = tmp_path / "my-brief.md"
    own.write_text(text, encoding="utf-8")
    run = tmp_path / "run"
    (run / "documents").mkdir(parents=True)
    local = run / "documents" / "brief.md"
    raw = f"# Research Brief\n\n{text}".encode()
    local.write_bytes(raw)
    assert asyncio.run(R._rehost_skipped_brief(run, text, own)) == want
    assert local.read_bytes() == raw
    assert own.read_text(encoding="utf-8") == text


def test_a_brief_from_the_verify_gate_is_rehosted_with_no_file_written(world, tmp_path):
    text, want = _brief_images(world)
    (tmp_path / "documents").mkdir()
    assert asyncio.run(R._rehost_skipped_brief(tmp_path, text, None)) == want
    assert list((tmp_path / "documents").iterdir()) == []


def test_a_skipped_brief_with_an_exit_scheduled_is_written_at_once_with_captions(
        world, tmp_path, monkeypatch):
    text, _want = _brief_images(world)
    local = tmp_path / "documents" / "brief.md"
    local.parent.mkdir()
    local.write_text(f"# Research Brief\n\n{text}", encoding="utf-8")
    _schedule_exit_without_exiting(monkeypatch)
    out = asyncio.run(R._rehost_skipped_brief(tmp_path, text, local))
    assert out == "Plan ![Chart]() and ![Pasted]() end"
    assert local.read_text(encoding="utf-8") == f"# Research Brief\n\n{out}"
    assert world.fetches == [] and world.posts == []


def _read_like_the_skip_branch(path):
    """What the phase-1 skip branch hands the rehost: the file read back, with only
    the exact `# Research Brief\\n\\n` header stripped."""
    text = path.read_text(encoding="utf-8")
    return text[len("# Research Brief\n\n"):] if text.startswith("# Research Brief\n\n") else text


def test_a_skipped_brief_with_no_image_leaves_brief_md_byte_identical(world, tmp_path):
    """EXECUTED — fixup: the inline brief is saved as-is when it already opens with
    `# Research Brief…`; the skip branch strips only the exact header, and a fixed
    header written back doubled it for a brief with no image at all."""
    local = tmp_path / "documents" / "brief.md"
    local.parent.mkdir()
    raw = b"# Research Brief: EV batteries\r\n\r\nCell chemistry plan, no pictures.\r\n"
    local.write_bytes(raw)
    text = _read_like_the_skip_branch(local)
    assert asyncio.run(R._rehost_skipped_brief(tmp_path, text, local)) == text
    assert local.read_bytes() == raw
    assert world.fetches == []


def test_a_skipped_brief_with_its_own_header_keeps_that_header_once(world, tmp_path):
    text, want = _brief_images(world)
    local = tmp_path / "documents" / "brief.md"
    local.parent.mkdir()
    local.write_text(f"# Research Brief: EV batteries\n\n{text}", encoding="utf-8")
    got = _read_like_the_skip_branch(local)
    assert asyncio.run(R._rehost_skipped_brief(tmp_path, got, local)).endswith(want)
    assert local.read_text(encoding="utf-8") == f"# Research Brief: EV batteries\n\n{want}"


def test_a_brief_md_that_no_longer_ends_with_the_brief_is_left_alone(world, tmp_path):
    text, want = _brief_images(world)
    local = tmp_path / "documents" / "brief.md"
    local.parent.mkdir()
    other = "# Research Brief\n\nSomething else was written here meanwhile."
    local.write_text(other, encoding="utf-8")
    assert asyncio.run(R._rehost_skipped_brief(tmp_path, text, local)) == want
    assert local.read_text(encoding="utf-8") == other


def test_the_phase_1_skip_branch_rehosts_the_brief_before_the_paste_reads_it():
    """SOURCE PIN — `run_pipeline` cannot be executed here. The rehost is the last
    word on brief_text before brief_artifact is built, and it is handed the file the
    brief was read from."""
    src = _pipeline()
    assert src.count("_rehost_skipped_brief(") == 1
    call = src.index("brief_text = await _rehost_skipped_brief(queue_dir, brief_text, _loaded_path)")
    build = src.index('brief_artifact = BriefArtifact(text=brief_text, url="")', call)
    assert src[src.index("\n", call):build].strip() == ""
    strip = src.rindex('brief_text = brief_text[len("# Research Brief\\n\\n"):]', 0, call)
    branch = src.rindex("if 1 in skip_phases or _user_skip_p1 or _gate_skipped_p1:", 0, strip)
    body = src[branch:call]
    assert "_loaded_path = Path(brief_file)" in body and "_loaded_path = _bp" in body


# ═══ 33. wave 9 (2026-09-16) — the clock is not a refusal ══════════════════════
#
# ⛔⛔ `skipped and not tried` is ALSO true when one answer was private and the
# image's deadline broke the loop before any public address was tried. That verdict
# was "refused", and a refusal is remembered for the whole research — so a chart the
# CLOCK ran out on was a caption in every later document of that run, though the
# next document has a fresh budget and `_doc_img_resolve_src` already lets a
# deadline "failed" out of the cache.


def _skip_that_spends_the_budget(monkeypatch, seen, spend=0.6):
    """The REAL public/private rule, with a skipped answer taking `spend` seconds of
    the image's budget — what a second lookup and a slow skip do on a live run."""
    real = R._doc_img_address_is_public

    def slow(ip):
        seen.append(ip)
        if real(ip):
            return True
        time.sleep(spend)
        return False
    monkeypatch.setattr(R, "_doc_img_address_is_public", slow)


def test_a_connect_the_clock_broke_is_a_failure_not_a_refusal(monkeypatch):
    """⛔⛔ EXECUTED — `_doc_img_connect`. One private answer skipped, then the image's
    deadline broke the loop before the public address could be tried. `seen` holds
    both addresses, so the loop DID run (the pre-loop guard would leave it empty) and
    `connected` is empty, so the break — not a connect failure — ended it."""
    made, connected = _connect_world(monkeypatch, ["10.0.0.7", "93.184.216.34"])
    seen = []
    _skip_that_spends_the_budget(monkeypatch, seen)
    with pytest.raises(R._DocImageRefused) as got:
        R._doc_img_connect("img.example.com", 443, time.monotonic() + 0.3)
    assert seen == ["10.0.0.7", "93.184.216.34"]
    assert made == [] and connected == []
    assert got.value.kind == "failed"


def _connect_world_for_the_funnel(monkeypatch, addrs):
    """`_connect_world`, with asyncio's own AF_UNIX self-pipe left alone: the funnel
    runs inside `asyncio.run`, which cannot start an event loop on a fake socket.
    An image address still gets a dead socket, so nothing can reach the network."""
    made, connected = [], []
    real = socket.socket

    class _Dead:
        def setsockopt(self, *a):
            pass

        def settimeout(self, t):
            pass

        def connect(self, addr):
            connected.append(addr[0])

        def close(self):
            pass

    def spy(family=-1, type=-1, proto=-1, fileno=None):
        if family in (socket.AF_INET, socket.AF_INET6):
            made.append(family)
            return _Dead()
        return real(family, type, proto, fileno)

    def getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (ip, port)) for ip in addrs]
    # ⛔ `socketpair` MUST KEEP THE REAL CLASS. On POSIX it is a native AF_UNIX
    # call that never touches `socket.socket`, so the spy above is invisible to
    # it. On Windows there is no AF_UNIX socketpair and CPython falls back to a
    # pure-Python one that binds and connects a real AF_INET pair — through
    # `socket.socket`, which is now `spy`, which hands it a `_Dead` with no
    # `bind`. The AttributeError surfaces far from here, inside whatever the
    # product used a self-pipe for, and reads as the funnel under test breaking.
    _real_pair = getattr(socket, "socketpair", None)
    if _real_pair is not None:
        def _socketpair(*a, **k):
            saved, socket.socket = socket.socket, real
            try:
                return _real_pair(*a, **k)
            finally:
                socket.socket = saved
        monkeypatch.setattr(socket, "socketpair", _socketpair)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "socket", spy)
    return made, connected


def test_an_image_the_connects_clock_broke_is_fetched_again_by_the_next_document(
        world, monkeypatch):
    """⛔⛔ EXECUTED — THE CONSUMER of that verdict is the cache. The rehost runs the
    REAL `_doc_img_connect` inside the fetch; the document's budget is spent by the
    time it breaks, so nothing is remembered and the next document of the research
    (a fresh budget) fetches the chart and stores it."""
    made, connected = _connect_world_for_the_funnel(monkeypatch, ["10.0.0.7", "93.184.216.34"])
    seen = []
    _skip_that_spends_the_budget(monkeypatch, seen)
    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 0.3)
    url = "https://img.example.com/late-chart.png"
    calls = []

    def fetch(u, deadline):
        calls.append(u)
        return R._doc_img_connect("img.example.com", 443, deadline)
    monkeypatch.setattr(R, "_doc_img_fetch", fetch)
    assert rehost(f"![Chart]({url})", "ChatGPT") == "![Chart]()"
    assert seen == ["10.0.0.7", "93.184.216.34"] and made == [] and connected == []
    assert world.logs[-1][1].endswith("failed=1 linked=0 captioned=1 removed=0")

    monkeypatch.setattr(R, "_DOC_IMG_DOC_BUDGET_SEC", 5.0)
    monkeypatch.setattr(R, "_doc_img_fetch", lambda u, d: (calls.append(u), png())[1])
    assert rehost(f"again ![Chart]({url})", "Gemini") == f"again ![Chart]({ref_for(png())})"
    assert calls == [url, url]


# ═══ 34. wave 9 — a bold pseudo-heading whose image was STORED ═════════════════
#
# ⛔⛔ The 5-80 bound measured the RAW captured line, image markup and all, so a
# stored reference (96 characters) pushed a bold section line out of the match
# entirely — while the SAME line written `## …` kept its section, because that path
# captures the whole line, has no bound at all, and strips first.

BOLD_STORED = f"**![Chart]({HEADING_REF}) Quarterly revenue**"
LONG_BOLD_TITLE = ("Revenue grew steadily across every region we sell into this year " * 5).strip()


def test_a_bold_section_line_whose_image_was_stored_is_still_a_section(tmp_path, monkeypatch):
    """⛔⛔ EXECUTED — `save_meta`. The stored line must come back as a section now,
    and the two the bound still has to drop are in the SAME document: an image-ONLY
    bold line (which must not return as an empty section) and a bold sentence whose
    TITLE runs past 80, which the widened capture can now reach."""
    assert len(BOLD_STORED) - 4 > 80 and 80 < len(LONG_BOLD_TITLE) < 400
    got = _claude_sections(tmp_path, monkeypatch,
                           f"## Only heading\n\n{BOLD_STORED}\n\n"
                           f"**![Only]({HEADING_REF})**\n\n"
                           f"**{LONG_BOLD_TITLE}**\n\n")
    assert got["sections"] == ["Only heading", "Quarterly revenue"]


def test_a_stored_image_makes_no_difference_between_a_bold_line_and_a_hash_heading(
        tmp_path, monkeypatch):
    """The asymmetry itself: the same content, once as `**…**` and once as `## …`.
    The '##' path always kept it; the bold path dropped it on the image's length."""
    got = _claude_sections(tmp_path, monkeypatch,
                           f"## ![Chart]({HEADING_REF}) Quarterly revenue\n\nText.\n\n")
    assert got["sections"] == ["Quarterly revenue"]
    (tmp_path / "b").mkdir()
    bold = _claude_sections(tmp_path / "b", monkeypatch, f"{BOLD_STORED}\n\n")
    assert bold["sections"] == ["Quarterly revenue"]


def test_a_numbered_bold_line_whose_image_was_stored_is_still_a_section(tmp_path, monkeypatch):
    """⛔ The numbered-bold variant carried the same raw bound. The trailing prose
    keeps the plain-bold pattern (which needs the line to END in `**`) off this line,
    so only the numbered capture can put this section in meta.json."""
    line = f"**1. ![Chart]({HEADING_REF}) Margin outlook** — see the appendix"
    got = _claude_sections(tmp_path, monkeypatch, f"## Only heading\n\n{line}\n\n")
    assert got["sections"] == ["Only heading", "Margin outlook"]


# ═══ 35. wave 9 — the rejection line reports the number the gate weighed ═══════
#
# ⛔ The HTML→MD floors measure PROSE (image destinations left out); the messages
# printed len(). A panel carrying four signed chart URLs logged ~3,000 characters
# beside "below 2000-char threshold" and the rejection read as a machine fault.
#
# ⭐ These two tiers turn out to be EXECUTABLE with no browser: T1/T2 of the CUA
# ladders are gated on `browser and cua_client`, so a page whose every evaluate
# answers empty falls straight through them.


class _TierPage:
    """Every evaluate answers empty, so the CUA/clipboard tiers below find nothing."""

    async def evaluate(self, js, *a):
        return ""


def _tier_logs(monkeypatch, md):
    logs = []
    monkeypatch.setattr(R, "log", lambda msg, level="INFO", *a, **k: logs.append(msg))

    async def no_sleep(*a, **k):
        return None

    async def scrape(page, selectors, label):
        return md
    monkeypatch.setattr(R.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(R, "_extract_html_to_md", scrape)
    return logs


def _ack_with_charts(prose):
    """A chat-side ack whose RAW length clears the 2000 floor on image URLs alone."""
    return prose + "".join(f"![C{i}]({LONG_IMG}{i})" for i in range(4))


@pytest.mark.parametrize("prose", ["Tiny chat-side ack. ",
                                   "A rather longer chat-side acknowledgement sits here. "])
def test_geminis_T1_rejection_reports_the_prose_length_the_gate_weighed(monkeypatch, prose):
    """⛔ EXECUTED — `extract_gemini_response` T1. Two different acks, so a hard-coded
    number could not satisfy both."""
    md = _ack_with_charts(prose)
    assert len(md) > 2000 > R._doc_img_prose_len(md)
    logs = _tier_logs(monkeypatch, md)
    monkeypatch.setattr(R, "_strip_gemini_panel_noise", lambda t: t)
    assert asyncio.run(R.extract_gemini_response(_TierPage())) == ""
    line = [m for m in logs if "T1 HTML→MD returned" in m]
    assert len(line) == 1
    assert f"returned {R._doc_img_prose_len(md)} chars" in line[0]
    assert f"returned {len(md)} chars" not in line[0]
    assert "below 2000-char threshold" in line[0]


@pytest.mark.parametrize("prose", ["Tiny partial render. ",
                                   "A rather longer partial render sits in the panel. "])
def test_claudes_T2_panel_rejection_reports_the_prose_length_the_gate_weighed(monkeypatch, prose):
    """⛔ EXECUTED — `extract_claude_response` T2, the artifact-panel DOM scrape."""
    md = _ack_with_charts(prose)
    assert len(md) > 2000 > R._doc_img_prose_len(md)
    logs = _tier_logs(monkeypatch, md)

    async def one(page):
        return 1

    async def click(page, index=0):
        return True
    monkeypatch.setattr(R, "_count_claude_artifacts", one)
    monkeypatch.setattr(R, "_click_claude_artifact", click)
    assert asyncio.run(R.extract_claude_response(_TierPage())) == ""
    line = [m for m in logs if "T2 HTML→MD returned" in m]
    assert len(line) == 1
    assert f"returned {R._doc_img_prose_len(md)} chars" in line[0]
    assert f"returned {len(md)} chars" not in line[0]
    assert "below 2000-char floor" in line[0]
