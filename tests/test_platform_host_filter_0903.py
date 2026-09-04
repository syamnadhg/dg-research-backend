"""#277 — one host filter, and the nine copies that each got it wrong.

⛔⛔ THE FILTER MEANT TO SKIP THE PLATFORM'S OWN PAGES WAS DISCARDING THE
SOURCES. Every scrape site asked `h.includes('chatgpt.com')` of the WHOLE URL,
and ChatGPT appends `?utm_source=chatgpt.com` to every outbound link it renders
— so the test matched on the tracking tag of genuine sources. Measured on the
6 August capture: 22 of 40 anchors dropped, 16 sources reported where 36
distinct ones existed. That was diagnosed then and repaired at ONE of the ten
sites, the activity-panel reader; the other nine kept the substring test.

⛔⛔ AND IT WAS WRONG IN THE OTHER DIRECTION TOO, WHICH IS THE LINK THE OWNER
ASKED ABOUT. The Python readers tested `host in _HOST_DENYLIST`, which is an
equality test, so `support.anthropic.com` is not `anthropic.com` and an Anthropic
support page was presented as a research source. The suffix rule existed — it had
been written for the findings extractor and never reached its three neighbours.

⛔ SO THE SAME RUN GAVE TWO ANSWERS ABOUT THE SAME URL: `save_meta` wrote it into
`sourceUrls` with no host test at all, while `_extract_findings` dropped it. One
list said the page was a source and the other said it was not.

⭐ There is now one list (`_HOST_DENYLIST`) and one rule over it, in two
languages: `_is_platform_host` for Python and `_js_platform_guard` for the page
scrapes. The scrape sites carry the generator's output as literal text rather
than splicing it, because the test shim resolves those JS constants statically to
feed them to node and cannot fold a concatenation — a spliced constant made three
test files fail to collect. `test_every_scrape_site_is_the_one_rule` is what makes
the literal a copy rather than a fork.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "research.py").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(
    subprocess.run(["which", "node"], capture_output=True).returncode != 0,
    reason="node required to execute page JS",
)


# ── the rule itself ──────────────────────────────────────────────────────────

class TestTheHostRule:
    @pytest.mark.parametrize("host", [
        "chatgpt.com", "claude.ai", "anthropic.com", "openai.com",
        "gemini.google.com", "accounts.google.com",
    ])
    def test_a_listed_host_is_platform(self, host):
        assert research._is_platform_host(host) is True

    @pytest.mark.parametrize("host", [
        "support.anthropic.com",     # ⛔ the owner's link
        "cdn.openai.com",
        "files.oaiusercontent.com",
        "www.chatgpt.com",
        "help.claude.ai",
    ])
    def test_a_subdomain_is_platform_too(self, host):
        """An equality test answers False for every one of these, which is how a
        support page reached a user's Sources list."""
        assert research._is_platform_host(host) is True

    @pytest.mark.parametrize("host", [
        "notchatgpt.com",            # a bare suffix test swallows this
        "myclaude.ai",
        "docs.nvidia.com",
        "nature.com",
        "openai.com.evil.example",   # the list must be at the END of the host
        "",
    ])
    def test_everything_else_survives(self, host):
        assert research._is_platform_host(host) is False

    def test_the_google_hosts_that_are_ordinary_sources_survive(self):
        """⛔⛔ A MUTATION THAT COLLAPSED THE THREE GOOGLE AGENT HOSTS INTO
        `google.com` SURVIVED THE FIRST HARNESS RUN, on both sides of the app. It
        reads like tidying — one entry instead of three — and it deletes every
        Google-hosted citation a report makes. The boundary is per-host, and this
        pair of lists is what says where it falls."""
        for host in ("scholar.google.com", "books.google.com",
                     "patents.google.com", "cloud.google.com",
                     "developers.google.com"):
            assert research._is_platform_host(host) is False, host
        for host in ("gemini.google.com", "bard.google.com",
                     "notebooklm.google.com", "accounts.google.com"):
            assert research._is_platform_host(host) is True, host

    def test_the_url_face_agrees_with_the_host_face(self):
        assert research._find_is_platform_host("https://support.anthropic.com/a") is True
        assert research._find_is_platform_host("https://docs.nvidia.com/a") is False

    def test_a_source_carrying_the_platforms_tracking_tag_is_not_platform(self):
        """⛔⛔ THE 2026-08-06 DEFECT. ChatGPT tags every outbound link with
        `?utm_source=chatgpt.com`; a whole-URL test calls all of them platform
        chrome and throws the run's sources away."""
        assert research._find_is_platform_host(
            "https://docs.nvidia.com/guide?utm_source=chatgpt.com") is False
        assert research._find_is_platform_host(
            "https://example.com/about-claude.ai-tips") is False


# ── the page scrapes, actually executed ──────────────────────────────────────

def _turn_sources(hrefs):
    """Run the real ChatGPT inline-activity extractor over a turn holding these
    anchors, and return the source URLs it kept."""
    anchors = [el("a", {"href": h, "w": "200", "h": "20", "x": "300",
                        "y": str(300 + 22 * i)}, "src")
               for i, h in enumerate(hrefs)]
    spec = el("body", {"w": "1440", "h": "900"}, "", [
        el("main", {"w": "1440", "h": "900"}, "", [
            el("div", {"data-message-author-role": "user", "w": "600",
                       "h": "60", "x": "300", "y": "142"}, "the brief"),
            el("section", {"data-testid": "conversation-turn-2", "w": "800",
                           "h": "400", "x": "300", "y": "230"}, "", anchors)])])
    out = run_js(spec, research._CHATGPT_INLINE_ACTIVITY_JS)["ret"]
    assert out is not None, "the walker bailed out — the fixture, not the filter"
    return out.get("source_urls") or []


@needs_node
def test_the_turn_sweep_keeps_a_source_the_platform_tagged():
    """⛔⛔ THE WHOLE POINT. Before this, the tag was enough to delete it."""
    got = _turn_sources(["https://docs.nvidia.com/guide?utm_source=chatgpt.com"])
    assert got == ["https://docs.nvidia.com/guide?utm_source=chatgpt.com"], got


@needs_node
def test_the_turn_sweep_still_drops_the_platforms_own_pages():
    got = _turn_sources(["https://chatgpt.com/auth/login",
                         "https://cdn.openai.com/asset.png",
                         "https://nature.com/articles/x"])
    assert got == ["https://nature.com/articles/x"], got


@needs_node
def test_the_turn_sweep_does_not_swallow_a_lookalike_host():
    assert _turn_sources(["https://notchatgpt.com/article"]) == \
        ["https://notchatgpt.com/article"]


# ── the two lists that disagreed about the same URL ──────────────────────────

def test_the_sources_list_and_the_findings_list_now_agree():
    """⛔⛔ THE OWNER'S LINK, END TO END. A report citing an Anthropic support
    page used to put it in Sources and leave it out of Findings — one run, two
    answers. Both sides read the same rule now."""
    md = ("# Report\n\n"
          "Background is at https://support.anthropic.com/en/articles/1 and the "
          "measurement is in https://www.nature.com/articles/x which reports a "
          "clear effect across the whole cohort studied.\n")
    swept = research._sweep_source_urls(md)
    assert "https://support.anthropic.com/en/articles/1" in swept, \
        "the sweep is deliberately host-blind — the filter is the caller's job"
    kept = [u for u in swept if not research._find_is_platform_host(u)]
    assert kept == ["https://www.nature.com/articles/x"]
    findings = research._extract_findings(md, [])
    assert [f["url"] for f in findings] == ["https://www.nature.com/articles/x"]


def test_the_writer_applies_the_filter():
    """A behaviour test cannot see `save_meta`'s comprehension without a whole
    run, so the call site is pinned. It is the ONE host judgement made on the
    write side, and the sweep must stay host-blind beneath it."""
    assert ("urls = [u for u in _sweep_source_urls(content) "
            "if not _find_is_platform_host(u)]") in SRC


# ── one definition, mechanically ─────────────────────────────────────────────

def _live_code(text: str) -> str:
    """`research.py` with every comment and docstring blanked, code untouched.

    ⛔⛔ A CORRECTION THAT NAMES WHAT IT CORRECTS DEFEATS ANY ABSENCE GUARD, and
    the three guards below failed on their own explanations before this existed.
    Naming the retired spelling is right — a reader given only the new rule cannot
    tell whether the old one was ever believed — so the guard changes, not the
    prose.

    ⛔ AST, NOT A REGEX, AND THE DIFFERENCE IS LOAD-BEARING. A regex over `\"\"\"`
    cannot tell a docstring from the page JS, and the page JS is exactly what
    these guards must still be able to see: nine of the ten sites live inside
    triple-quoted assignments. A docstring is an `Expr` statement whose value is a
    string; a JS constant is an `Assign`. Only the first is blanked.

    Blanked rather than deleted so byte offsets, and therefore line numbers in a
    failure message, still line up with the real file.
    """
    import ast as _ast
    import io as _io
    import tokenize as _tok

    out = list(text)

    def blank(lo, hi):
        for i in range(lo, min(hi, len(out))):
            if out[i] != "\n":
                out[i] = " "

    lines = text.splitlines(keepends=True)
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln))

    def off(row, col):
        return starts[row - 1] + col

    for node in _ast.walk(_ast.parse(text)):
        if isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Constant) \
                and isinstance(node.value.value, str):
            blank(off(node.lineno, node.col_offset),
                  off(node.end_lineno, node.end_col_offset))

    for t in _tok.generate_tokens(_io.StringIO(text).readline):
        if t.type == _tok.COMMENT:
            blank(off(t.start[0], t.start[1]), off(t.end[0], t.end[1]))

    # ⛔ AND THE JS COMMENTS INSIDE THE RETAINED STRINGS. The scrape constants are
    # kept on purpose, so their `//` prose is kept with them — and the sentence
    # recording what the substring filter used to be lives in one of them, which
    # failed this guard on its own tombstone.
    #
    # ⛔⛔ WHOLE LINES ONLY, AND THE FIRST DRAFT WAS NOT. It matched `//` anywhere
    # not preceded by `:` — the frontend's rule, where the only hazard is a URL —
    # and here that also matches INSIDE a regex literal: `/^https?:\\/\\//i`
    # ends in two slashes. It blanked the guard sites themselves, and only the
    # test below noticed, because every absence check downstream passes hardest
    # when it can see nothing at all. A comment line starts with `//`; a regex
    # never starts one.
    import re as _re
    return _re.sub(r"(?m)^(\s*)//.*$",
                   lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))),
                   "".join(out))


def _escaped(js: str) -> str:
    """The generator's output as it appears in research.py, where these JS
    strings are ordinary (non-raw) Python literals."""
    return js.replace("\\", "\\\\")


LIVE = _live_code(SRC)


def test_the_live_code_reader_can_still_see_the_page_js():
    """⛔ THE GUARD ON THE GUARD. If blanking ever swallowed the scrape constants,
    every absence check below would pass by seeing nothing at all — the failure
    mode where a test is loudest and emptiest."""
    assert "_CHATGPT_INLINE_ACTIVITY_JS" in LIVE
    assert LIVE.count(_escaped(research._js_platform_guard("h"))) == 7
    assert "⛔⛔ THE MEMBERSHIP TESTS THIS REPLACES WERE EXACT" not in LIVE


def test_every_scrape_site_is_the_one_rule():
    """⛔ Nine sites, byte-identical to the generator. This is what makes the
    inlining a copy rather than a fork: change `_HOST_DENYLIST` or the guard and
    every site that did not follow fails here."""
    n_h = SRC.count(_escaped(research._js_platform_guard("h")))
    n_href = SRC.count(_escaped(research._js_platform_guard("href")))
    assert (n_h, n_href) == (7, 2), (n_h, n_href)


def test_the_panel_regex_is_built_from_the_same_list():
    """The one site that was already correct in August covered two hosts of the
    eleven. It reads the whole list now."""
    alt = "|".join(sorted(d.replace(".", "\\.") for d in research._HOST_DENYLIST))
    assert _escaped("/(^|\\.)(" + alt + ")$/i") in SRC


def test_no_scrape_still_tests_a_platform_name_against_a_whole_url():
    """⛔⛔ THE ABSENCE GUARD, AND IT IS THE ONE THAT MATTERS. Every one of these
    reads as a filter that skips the platform's own pages and behaves as a filter
    that deletes the run's sources.

    Comment text is exempt: the corrections above name what they retired, and a
    guard that forbids the name forbids explaining it. Code is not exempt."""
    offenders = [
        m for m in re.findall(
            # ⛔⛔ `claude`, NOT `claude\.ai`, AND THAT NARROWNESS COST THREE SITES.
            # The first draft of this guard searched for the full host and ran
            # green over `!a.href.includes('claude.')` — a filter naming no host
            # at all, in Claude's own progress scraper, which let every
            # `anthropic.com` page through while deleting sources whose path read
            # `claude.html`. A guard against spelling a platform name into a
            # whole-URL test has to match the SPELLINGS, not one of them.
            # ⛔ AND IT MUST BE A URL BEING TESTED. Widening to the bare platform
            # names caught two innocents on the first run — a composer placeholder
            # (`placeholder.includes('ask gemini')`) and a model-name check
            # (`t.includes('claude')`). Neither is a link filter, and failing on
            # them would have trained the next reader to loosen the guard rather
            # than the code. The receiver is the discriminator: these tests are
            # wrong only when what they test is an address.
            r"(?:href|url|link|src|\bh|\bu)\??\.includes\("
            r"'[^']*(?:chatgpt|openai|claude|anthropic|gemini|oaiusercontent|notebooklm)[^']*'\)",
            LIVE)
    ]
    # The redirector unwrap legitimately asks whether a URL IS a chatgpt.com
    # redirect before rewriting it — that is a shape question, not a host filter.
    offenders = [o for o in offenders if "chatgpt.com/" not in o]
    assert offenders == [], offenders


def test_no_reader_still_tests_membership_in_the_denylist():
    """`host in _HOST_DENYLIST` is an equality test and every subdomain slips it.
    The list is a list of DOMAINS; only `_is_platform_host` may read it as one."""
    assert " in _HOST_DENYLIST" not in LIVE.replace("for d in _HOST_DENYLIST", "")


def test_the_list_is_read_in_exactly_two_places():
    """`_is_platform_host` for Python and `_js_platform_guard` for the scrapes.

    ⛔ The panel regex is NOT a third reader — it carries the generator's output
    as literal text, like the nine guard sites, and is held to it by
    `test_the_panel_regex_is_built_from_the_same_list`. A third reader of the raw
    frozenset would be a third chance to spell the rule differently."""
    assert LIVE.count("_HOST_DENYLIST") == 3  # the definition, plus two readers
