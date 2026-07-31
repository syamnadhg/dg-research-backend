"""P3 NotebookLM — the notebook-URL predicate, and why it is a shape test.

2026-07-30 outage. Google began serving notebooks from `notebook.google.com`
(the same host minus the "lm"). Every gate on the Phase-3 path tested the
literal string `notebooklm.google.com`, so within one afternoon:

  * the share-dialog DOM read (`input[value*="notebooklm"]`) stopped matching —
    the hostname was baked into the SELECTOR, so it could not even find the
    field,
  * the clipboard containment guard stopped matching — the correct link WAS on
    the clipboard and was discarded,
  * the vision fallback's success signal became unsatisfiable, so the CUA could
    not self-report success either, and
  * the URL validator rejected every notebook the pipeline built.

Audio, P4 and P5 are all hard-gated behind that last check: 7 consecutive
Phase-3 failures, 6 orphaned notebooks, ~71 minutes of wasted wall clock, zero
podcasts.

These tests pin the SHAPE contract, not a list of hostnames. The point of the
fix is that the next rename needs no code change; a test that enumerated the two
known hosts would pass while the design regressed back to a literal.
"""
from __future__ import annotations

import pytest

import research
from conftest import code_only


# ── The shape contract ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    # The original host.
    "https://notebooklm.google.com/notebook/0d028786-66ef-4933-a322-ed66c7b56ce8",
    # The host Google moved to on 2026-07-30 — the one that broke everything.
    "https://notebook.google.com/notebook/0d028786-66ef-4933-a322-ed66c7b56ce8",
    # Trailing path/query/fragment are all fine — a share link may carry them.
    "https://notebook.google.com/notebook/2300054c-fab9-4080-8e11-5ec4fff597d8?authuser=0",
    "https://notebooklm.google.com/notebook/abc123#audio",
    "https://notebooklm.google.com/notebook/abc123/audio",
    # Surrounding whitespace: a clipboard read routinely carries it.
    "  https://notebook.google.com/notebook/abc123  ",
    # http is accepted; we never emit it, but rejecting it would be a silent
    # data loss if a platform ever served one.
    "http://notebook.google.com/notebook/abc123",
])
def test_accepts_a_notebook_url_on_any_google_host(url):
    assert research.is_notebooklm_url(url) is True


@pytest.mark.parametrize("url", [
    # No /notebook/<id> — these are the surfaces the OLD literal check also had
    # to reject, and the shape test must not have loosened them.
    "https://notebooklm.google.com/",
    "https://notebook.google.com",
    "https://notebooklm.google.com/home",
    # /notebook with NO id: the home/listing surface, not a notebook.
    "https://notebook.google.com/notebook",
    "https://notebook.google.com/notebook/",
    # A sign-in redirect — the single most likely thing to be sitting in the tab
    # when extraction fails, and the thing that must never ship as a link.
    "https://accounts.google.com/signin/v2/identifier?continue=https://notebook.google.com/notebook/x",
    # Other Google products, including one that nests the path deeper.
    "https://docs.google.com/document/d/abc/edit",
    "https://drive.google.com/drive/my-drive",
    "https://google.com/search?q=notebook",
    # A lookalike host that is NOT Google. `endswith('.google.com')` is what
    # makes this fail; a naive `'google.com' in host` would accept it.
    "https://notebook.google.com.evil.example/notebook/abc123",
    "https://notgoogle.com/notebook/abc123",
    # Not a URL at all.
    "",
    "notebook.google.com/notebook/abc123",     # scheme-less
    "javascript:alert(1)//notebook/abc",
    "the link has been copied to your clipboard",
])
def test_rejects_everything_that_is_not_a_notebook_url(url):
    assert research.is_notebooklm_url(url) is False


@pytest.mark.parametrize("bad", [None, 123, [], {}, object()])
def test_non_string_input_is_false_not_an_exception(bad):
    """Called on clipboard reads and `page.url`, both of which can be None."""
    assert research.is_notebooklm_url(bad) is False


def test_a_subdomain_of_google_is_accepted_so_the_next_rename_needs_no_release():
    """The load-bearing property. Any future NotebookLM host under google.com
    validates without a code change — that is the whole reason this is a shape
    test. If someone re-pins it to an enumerated host list, this fails."""
    assert research.is_notebooklm_url(
        "https://notebooks.google.com/notebook/future-uuid") is True
    assert research.is_notebooklm_url(
        "https://nlm.google.com/notebook/future-uuid") is True


# ── The predicate is actually WIRED at every gate ────────────────────────────

def test_the_link_validator_uses_the_predicate():
    """`validate_link("notebooklm", …)` is the gate that rejected 7 runs' worth
    of notebooks and took audio/P4/P5 down with them."""
    assert research._LINK_VALIDATORS["notebooklm"] is research.is_notebooklm_url
    assert research.validate_link(
        "notebooklm", "https://notebook.google.com/notebook/abc123") is True
    assert research.validate_link(
        "notebooklm", "https://notebooklm.google.com/notebook/abc123") is True
    assert research.validate_link("notebooklm", "https://notebooklm.google.com/") is False


def test_bad_url_patterns_still_win_over_the_shape_test():
    """`_BAD_URL_PATTERNS` is checked BEFORE the platform validator. An auth page
    that somehow carried a /notebook/ path must still be refused."""
    assert research.validate_link(
        "notebooklm",
        "https://accounts.google.com/notebook/abc123") is False


def test_no_phase3_gate_still_compares_the_hostname_by_hand():
    """The four independent literal comparisons are what made one rename fatal:
    each had to be found and fixed separately, and each was a place the next
    rename could hide. Consolidating them is the fix — so nothing on the P3 path
    may go back to substring-matching the host.

    Scoped to the functions that read or gate a notebook URL. Navigation targets
    (`browser.new_tab("https://notebooklm.google.com")`) are deliberately NOT in
    scope: a canonical entry point is correct and any redirect handles it.
    """
    for fn in (research.extract_notebooklm_url,
               research._set_nlm_public_and_get_link,
               research.extract_with_retry):
        src = code_only(fn)
        assert "notebooklm.google.com" not in src, (
            f"{fn.__name__} compares the NotebookLM hostname by hand again — "
            "use is_notebooklm_url / _JS_IS_NLM_URL so one rename cannot take "
            "the back half of the pipeline down"
        )


def test_the_js_predicate_matches_the_python_one_and_has_no_backslashes():
    """The in-page reads need the same rule as the Python side, and it must be
    regex-free: a lone backslash in a non-raw Python string once became a literal
    backspace and silently disabled a JS gate for months (#913)."""
    js = research._JS_IS_NLM_URL
    assert "\\" not in js, (
        "no backslashes in embedded JS — #913 turned one into a backspace"
    )
    # Same three components as the Python predicate.
    assert "google.com" in js
    assert "endsWith('.google.com')" in js
    assert "'/notebook/'" in js
    # And it is an expression (passed as an argument to page.evaluate), not a
    # statement — so it must be parenthesised.
    assert js.strip().startswith("(") and js.strip().endswith(")")


def test_the_share_dialog_dom_read_no_longer_filters_by_hostname():
    """The old selector was `input[value*="notebooklm"]`, i.e. the hostname was
    part of the SELECTOR. After the rename it could not locate the field at all,
    so widening only the value guard would have left this channel dead."""
    src = code_only(research._set_nlm_public_and_get_link)
    assert 'input[value*="notebooklm"]' not in src
    assert "_JS_IS_NLM_URL" in src, (
        "the DOM link read must go through the shared JS predicate"
    )
