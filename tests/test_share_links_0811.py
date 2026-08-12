"""Three agents published, three links were thrown away, and the run said nothing.

WHAT HAPPENED (2026-08-11 e2e)

Every agent's publish flow SUCCEEDED. The vision agent created and copied a
public link for each one:

    Claude   https://claude.ai/public/artifacts/d3a9b9a2-de86-4ec9-8957-b6ce60fe8906
    Gemini   https://share.gemini.google/G85YKq3hPsyG

and the pipeline discarded all of them, logging

    [Claude] Inline share-link unverified (, 71.0s) — falling back to
             conversation URL silently

at INFO, with an EMPTY reason and no URL. The finished report then linked to
`claude.ai/chat/…` and `gemini.google.com/app/…` — private conversations that
open for nobody but the account that ran them.

TWO DIFFERENT FAILURES, ONE CAUSE — host literals that the vendors moved off.

  * Gemini: the link was never READ. The share dialog is scraped with
    `input[value*="g.co/gemini"]` and `input[value*="gemini.google.com/share"]`;
    the live dialog holds `share.gemini.google/…`, a host neither selector knows.
  * Claude: the link WAS read and then rejected. The gate was
    `"claude.site" in url`, and Publish now yields `claude.ai/public/artifacts/…`.

And the gate existed TWICE — once inside each extractor, once in
`_LINK_VALIDATORS` — so the two copies could disagree about the same URL. That
is the same duplicated-predicate shape that cost a production run on 2026-08-05.

WHAT THESE TESTS PIN

  1. The live URLs from this run are accepted, and the older forms still are.
  2. A private conversation URL is never accepted.
  3. ⭐ The HOST is matched, not a substring. `evil.com/?x=gemini.google.com/share/1`
     must fail — the 2026-08-06 panel bug discarded 56% of sources because a
     filter substring-matched a whole URL and ChatGPT appends
     `?utm_source=chatgpt.com` to outbound links.
  4. There is ONE authority, and the extractors use it.
  5. The failure is no longer silent: it says which of the two happened, prints
     the URL, and warns that the fallback link is not shareable.
"""
import inspect
import io
import re
import tokenize

import pytest

import research


def code_only(src: str) -> str:
    """`src` with comments blanked out, offsets preserved.

    ⭐ Written because the first version of this file asserted that the old log
    line was GONE, and the assertion failed against the COMMENT that quotes it
    while explaining the fix. That trap has now bitten this project on both
    sides of the stack — prose that documents a string is not the string."""
    out = list(src)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                (srow, scol), (erow, ecol) = tok.start, tok.end
                if srow != erow:
                    continue
                line_start = sum(len(l) + 1 for l in src.splitlines()[:srow - 1])
                for i in range(line_start + scol, min(line_start + ecol, len(out))):
                    out[i] = " "
    except (tokenize.TokenError, IndentationError):
        return src
    return "".join(out)


LIVE = [
    ("gemini", "https://share.gemini.google/G85YKq3hPsyG"),
    ("claude", "https://claude.ai/public/artifacts/d3a9b9a2-de86-4ec9-8957-b6ce60fe8906"),
]
LEGACY = [
    ("gemini", "https://gemini.google.com/share/8e52f021efe3"),
    ("gemini", "https://g.co/gemini/share/abc123"),
    ("claude", "https://claude.site/artifacts/abc123"),
    ("chatgpt", "https://chatgpt.com/share/abc123"),
]
PRIVATE = [
    ("gemini", "https://gemini.google.com/app/109a01ab4625c8d2"),
    ("claude", "https://claude.ai/chat/6fde90e7-5e50-4346-a303-c8e315d885cd"),
    ("chatgpt", "https://chatgpt.com/c/6a7bb5f2-fa1c-83ea-a1f0-a1863830fd93"),
]


# ── 1 & 2: the live links, the old links, and the private ones ──────────────

@pytest.mark.parametrize("platform,url", LIVE)
def test_the_links_this_run_actually_published_are_accepted(platform, url):
    assert research._is_public_share_url(platform, url) is True
    assert research.validate_link(platform, url) is True


@pytest.mark.parametrize("platform,url", LEGACY)
def test_the_previous_forms_still_ship_and_still_pass(platform, url):
    """Both generations are live in the wild — replacing one with the other
    would just move the outage."""
    assert research._is_public_share_url(platform, url) is True


@pytest.mark.parametrize("platform,url", PRIVATE)
def test_a_private_conversation_url_is_never_a_share_link(platform, url):
    """The whole point of the gate. These are exactly the URLs the run fell
    back to, and shipping one as 'verified' would be worse than the bug."""
    assert research._is_public_share_url(platform, url) is False
    assert research.validate_link(platform, url) is False


# ── 3: host, not substring ──────────────────────────────────────────────────

@pytest.mark.parametrize("platform,url", [
    ("gemini", "https://evil.example/?next=gemini.google.com/share/1"),
    ("gemini", "https://evil.example/gemini.google.com/share/1"),
    ("claude", "https://evil.example/?u=claude.site/artifacts/1"),
    ("chatgpt", "https://evil.example/#chatgpt.com/share/1"),
    # ⭐ The ones that MATTER: the path also satisfies the prefix, so only the
    # host check can reject them. Without these, degrading the host match to a
    # substring survived every case above — the path guard was doing the work
    # and the test proved nothing about the host rule.
    ("gemini", "https://evil.example/share/abc?ref=gemini.google.com"),
    ("claude", "https://evil.example/public/artifacts/1?ref=claude.ai"),
    ("chatgpt", "https://evil.example/share/abc?ref=chatgpt.com"),
])
def test_a_matching_string_somewhere_in_the_url_is_not_a_matching_host(platform, url):
    """⭐ The 2026-08-06 lesson, applied before it can bite again: ChatGPT tags
    outbound links with `?utm_source=chatgpt.com`, so any rule that greps the
    whole URL will match links it does not own."""
    assert research._is_public_share_url(platform, url) is False


@pytest.mark.parametrize("platform,url", [
    ("gemini", "https://evilgemini.google.com/share/abc"),
    ("claude", "https://notclaude.site/artifacts/abc"),
    ("chatgpt", "https://fakechatgpt.com/share/abc"),
])
def test_a_lookalike_domain_is_not_a_subdomain(platform, url):
    """`host.endswith("gemini.google.com")` is true for `evilgemini.google.com`.
    The dot matters: only `x.gemini.google.com` is a subdomain."""
    assert research._is_public_share_url(platform, url) is False


@pytest.mark.parametrize("platform,url", [
    ("claude", "ftp://claude.site/artifacts/abc"),
    ("claude", "//claude.site/artifacts/abc"),
    ("gemini", "file://share.gemini.google/abc"),
])
def test_only_http_and_https_can_be_a_share_link(platform, url):
    """A real host on a scheme we never publish. The earlier `javascript:` case
    was rejected by the HOST check (it parses to no host at all), so it never
    exercised the scheme guard."""
    assert research._is_public_share_url(platform, url) is False


@pytest.mark.parametrize("platform,url", [
    ("gemini", "https://share.gemini.google/"),
    ("gemini", "https://gemini.google.com/share"),
    ("chatgpt", "https://chatgpt.com/share/"),
])
def test_the_share_surface_itself_is_not_a_link_to_anything(platform, url):
    assert research._is_public_share_url(platform, url) is False


def test_a_non_http_scheme_is_rejected():
    assert research._is_public_share_url("claude", "javascript:alert(1)//claude.site/x") is False
    assert research._is_public_share_url("gemini", "") is False
    assert research._is_public_share_url("gemini", None) is False


def test_an_unknown_platform_is_rejected():
    assert research._is_public_share_url("perplexity", "https://share.gemini.google/x") is False


# ── 4: one authority, used everywhere ───────────────────────────────────────

@pytest.mark.parametrize("extractor", [
    "extract_share_link_gemini", "extract_share_link_claude",
])
def test_each_extractor_uses_the_shared_authority(extractor):
    """The gate lived in two places and they disagreed: Claude's extractor
    accepted a URL its validator then rejected, so the link was captured and
    dropped downstream with no line explaining it."""
    src = inspect.getsource(getattr(research, extractor))
    assert "_is_public_share_url(" in src
    # and the old hand-rolled predicate must be gone
    assert 'verified = "claude.site" in url.lower()' not in src
    assert '("gemini.google.com/share" in _lu)' not in src


def test_the_validators_delegate_rather_than_re_state_the_rule():
    for platform in ("chatgpt", "gemini", "claude"):
        assert research._LINK_VALIDATORS[platform]("https://x.invalid/y") is False
    # the authority and the validator must agree on every live URL
    for platform, url in LIVE + LEGACY:
        assert research._LINK_VALIDATORS[platform](url) is research._is_public_share_url(platform, url)


def test_gemini_reads_the_current_host_off_the_dialog():
    """Gemini's link was never READ, not merely rejected — the DOM query only
    knew the two older hosts."""
    src = inspect.getsource(research.extract_share_link_gemini)
    assert 'input[value*="share.gemini.google"]' in src
    # the older selectors must survive alongside it
    assert 'input[value*="g.co/gemini"]' in src
    assert 'input[value*="gemini.google.com/share"]' in src


# ── 5: the failure is not silent any more ───────────────────────────────────

def test_the_fallback_names_which_failure_happened_and_prints_the_url():
    """`Inline share-link unverified (, 71.0s)` told the reader nothing: not
    whether a URL was found, not what it was, not that the fallback link is
    unshareable."""
    src = code_only(inspect.getsource(research.extract_and_record_agent))
    assert "Inline share-link unverified" not in src, "the empty-reason line is gone"
    at = src.index("no public share link")
    window = src[at:at + 700]
    assert "did not pass the public-share" in window, "must distinguish rejected…"
    assert "returned no URL at all" in window, "…from never-found"
    assert "NOT" in window and "viewable" in window, "must say the fallback is private"
    # ⭐ The URL itself must be INTERPOLATED, not just described. Asserting the
    # sentence survived a mutant that deleted `{_got}` and kept the prose — the
    # reader would be told a URL was rejected and never shown which one, which
    # is the same dead end as the original empty-reason line.
    assert "{_got[:120]}" in window, "the rejected URL must be printed, not described"


def test_the_fallback_is_a_warning_not_an_info_line():
    """It ships a report whose links open for nobody else. That is not INFO."""
    src = inspect.getsource(research.extract_and_record_agent)
    at = src.index("no public share link")
    assert re.search(r'"WARN"\)', src[at:at + 900]), "the fallback must log at WARN"


def test_a_read_but_rejected_link_is_reported_by_the_extractor_too():
    for extractor in ("extract_share_link_gemini", "extract_share_link_claude"):
        src = inspect.getsource(getattr(research, extractor))
        assert "a link was read but is not a public share URL" in src, extractor


# ── the phase that succeeded but was recorded as errored ────────────────────

def test_the_phase_status_is_recorded_before_the_file_that_reads_it():
    """⭐ 2026-08-11: the run shipped a 64 KB brief with
    `phases[1].status = "errored"` and `durationSec: 0` in meta.json.

    `save_meta` rebuilds the phases array from the recorded terminal statuses.
    It used to run BEFORE the "complete" was recorded, so when phase 1 had
    surfaced a stall card earlier, `fail_phase`'s "errored" was still the
    recorded value — it was written to disk and never rewritten, while
    Firestore (written afterwards) said complete."""
    src = code_only(inspect.getsource(research.run_pipeline))
    marker = 'save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())'
    record = '_write_phase_terminal_status(1, "complete")'
    # ⭐ EVERY phase-1 save_meta, not the first one found. The first version of
    # this test checked only `src.index(marker)` and so tested one of the two
    # branches — the other (brief supplied by file) had the identical bug and
    # would have shipped unfixed.
    saves = [m.start() for m in re.finditer(re.escape(marker), src)]
    assert len(saves) >= 2, f"expected both phase-1 save_meta branches, found {len(saves)}"
    for save_at in saves:
        before = src[:save_at]
        assert record in before, (
            "the terminal status must be recorded BEFORE save_meta rebuilds the "
            "phases array, or a phase that recovered stays 'errored' on disk"
        )
        # …and recorded in THIS branch, not merely somewhere earlier in the file
        assert save_at - before.rindex(record) < 900, (
            "the status record must belong to this branch's completion block"
        )
