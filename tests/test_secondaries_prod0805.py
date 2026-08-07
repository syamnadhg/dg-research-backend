"""2026-08-05 — the four secondary defects from the same prod run.

(a) THE BIG ONE. Gemini's brief paste verified at `1/61867 chars (0%)` on BOTH
    clipboard strategies, identically. `Control+V` is not the paste accelerator
    on macOS — Blink's Mac editing-behaviour map binds Ctrl+V to MovePageDown and
    Ctrl+A to MoveToBeginningOfLine. So `clipboard.writeText` succeeded (no
    exception, hence no "Strategy A raised" line anywhere in the corpus), the
    keypress did nothing, and the composer was never touched. Two identical
    numbers rather than two different low ones is the signature of the same dead
    key pressed twice.

    ⚠ COLLATERAL, worse than the reported symptom: Strategies A.5 and B were
    BOTH gated to Gemini, so on macOS ChatGPT and Claude had NO working paste
    path at all — and the CUA escalation pressed the same dead key. Gemini only
    ever finished because Strategy B uses CDP Input.insertText, which has no key
    mapping to get wrong.

    And "1 char" was never one character: an empty Quill/ProseMirror
    contenteditable is `<p><br></p>`, whose innerText is exactly "\\n".

(b) NotebookLM's DOM upload was 0/3, "chooser never opened" three times.
    ⭐ The incident report blamed the synthetic-click pattern. That was MEASURED
    WRONG: page.evaluate carries a user gesture, `navigator.userActivation.isActive`
    is true inside it, and a JS `el.click()` opens a file chooser in all four
    handler shapes. The real defects are that the candidate gate was an 8x8 rect
    with no centre-in-viewport or disabled test — in a file that added `onScreen`
    precisely because NotebookLM parks a full-size button at x=-36 — and that the
    fallback waited 10s for a chooser instead of re-checking for the hidden input
    its own click had just revealed.

(c) ⭐ NOT A BUG. `notebook.google.com` is now the canonical host and
    `is_notebooklm_url` is already a pure shape test. The report called it "the
    same host mismatch as the standing P3 finding"; the standing finding is fixed
    and this is the fix working. Pinned below so it is not "repaired" later.

(d) The ChatGPT share extractor read the clipboard four times with no
    `_arm_clipboard()` — the only extractor in the file that did not — and its CUA
    mission was not pinned to a page.

Run:  pytest tests/test_secondaries_prod0805.py -v
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from _domshim import NODE, el, run_js
from conftest import code_only, code_only_deep, js_code_only

needs_node = pytest.mark.skipif(NODE is None, reason="node required to run page JS")


def _click(spec, patterns):
    """Run `_NLM_CLICK_JS` and report what it returned AND what it marked.

    2026-08-06: the helper stopped calling `el.click()` in the page — a synthetic
    click carries no user activation and so could never open the native file
    chooser these uploads need. It now MARKS the element and Playwright presses
    it. `marks` is counted from the document afterwards, independently of the
    return value, so "it picked something" and "it marked exactly that one" stay
    separate observations.
    """
    composed = (
        "(patterns) => { const r = (" + research._NLM_CLICK_JS + ")(patterns); "
        "return { r: r, marks: document.querySelectorAll('["
        + research._SR_CLICK_MARK + "]').length }; }"
    )
    out = run_js(spec, composed, list(patterns))
    raw = out["ret"] or {}
    return {"ret": raw.get("r"), "marks": raw.get("marks", 0),
            "clicks": out.get("clicks", [])}


# ── (a) the accelerator ───────────────────────────────────────────────────

def test_no_bare_control_accelerator_survives_anywhere():
    """A bare `Control+` accelerator is never correct cross-platform. This is a
    whole-module sweep because the defect was four call sites in two functions
    plus a fifth in the Gemini Tier-3 extractor, and only one of them was
    reported."""
    src = code_only_deep(inspect.getsource(research))
    offenders = [ln for ln in src.splitlines()
                 if 'keyboard.press("Control+' in ln]
    assert not offenders, (
        f"bare Control accelerator(s) still present: {offenders}"
    )


@pytest.mark.parametrize("fn", [
    research.verified_paste_brief,
    research.cua_paste_fallback,
])
def test_every_paste_path_uses_the_portable_accelerator(fn):
    src = code_only_deep(fn)
    if "keyboard.press" not in src:
        pytest.skip(f"{fn.__name__} presses no keys")
    assert "ControlOrMeta" in src, (
        f"{fn.__name__} presses a key that does nothing on macOS"
    )


def test_the_gemini_tier3_extractor_was_swept_too():
    """Its header comment ASSERTED that the approach "works on Wayland, X11,
    Windows, and macOS uniformly" — an assertion of coverage that was never
    measured, and the thing that stopped anyone checking."""
    src = code_only_deep(inspect.getsource(research))
    i = src.index('keyboard.press("ControlOrMeta+c")')
    window = src[i - 400:i]
    assert 'keyboard.press("ControlOrMeta+a")' in window, (
        "the select-all before the copy is still a dead key"
    )


def test_the_keyboard_strategy_is_no_longer_gemini_only():
    """On macOS this was the ONLY OS-independent path, and ChatGPT and Claude
    could not reach it."""
    src = code_only(research.verified_paste_brief)
    assert 'if platform_key == "gemini":' not in src.split("Strategy B")[-1], (
        "ChatGPT and Claude are locked out of the one paste path that cannot "
        "fail on a key mapping"
    )
    assert "_keyboard_strategy_platforms" in src
    for p in ("chatgpt", "claude", "gemini"):
        assert p in src


def test_insert_text_stays_the_first_rung_of_that_strategy():
    """⚠ `keyboard.type()` fires Enter per newline and all three platforms bind
    Enter to submit — that is the "brief in pieces, endlessly" submit-storm.
    Ungating the strategy must not promote the dangerous call."""
    src = code_only(research.verified_paste_brief)
    tail = src[src.index("_keyboard_strategy_platforms"):]
    assert tail.index("keyboard.insert_text(") < tail.index("keyboard.type("), (
        "insert_text must be tried before the newline-firing type()"
    )
    assert 'brief_text.replace("\\n", " ")' in tail, (
        "the last-resort type() must strip newlines so it cannot fire submit"
    )


# ── (a) "1 char" was zero ─────────────────────────────────────────────────

@needs_node
@pytest.mark.parametrize("html,expected_zero", [
    ("<p><br></p>", True),          # the empty ProseMirror/Quill composer
    ("<p>​</p>", True),        # a zero-width space
    ("<p>﻿</p>", True),       # a BOM
    ("<p>   </p>", True),           # whitespace only
])
def test_an_empty_composer_measures_zero_not_one(html, expected_zero):
    """The arithmetic identity behind "1/61867 chars (0%)"."""
    inner = html.replace("<p>", "").replace("</p>", "").replace("<br>", "\n")
    spec = el("body", {}, "", [
        el("div", {"contenteditable": "true", "data-placeholder": "Ask", "w": "600",
                   "h": "80"}, inner),
    ])
    got = run_js(spec, js_code_only(research._VERIFY_PASTE_JS))["ret"]
    assert (got == 0) is expected_zero, f"{html!r} measured {got}"


@needs_node
def test_real_text_still_measures_its_length():
    spec = el("body", {}, "", [
        el("div", {"contenteditable": "true", "data-placeholder": "Ask", "w": "600",
                   "h": "80"}, "abcdefghij"),
    ])
    assert run_js(spec, js_code_only(research._VERIFY_PASTE_JS))["ret"] == 10


@needs_node
def test_the_measure_ignores_whitespace_inside_real_text():
    """Normalising strips ALL whitespace, so the ratio is computed on a
    like-for-like basis — the expected length is a raw char count, so this is
    deliberately conservative (it can only under-report, never over-report a
    paste as landed)."""
    spec = el("body", {}, "", [
        el("div", {"contenteditable": "true", "w": "600", "h": "80"}, "ab cd\nef"),
    ])
    assert run_js(spec, js_code_only(research._VERIFY_PASTE_JS))["ret"] == 6


def test_an_empty_composer_is_reported_as_empty_not_as_a_percentage():
    """EMPTY and TRUNCATED need opposite fixes — a dead key mapping versus a
    chunk size — and "0%" described both."""
    src = code_only(research._verify_paste_landed)
    assert "content_len == 0" in src
    assert "EMPTY" in src


# ── (b) the NotebookLM chooser ────────────────────────────────────────────

@needs_node
def test_an_off_canvas_control_cannot_win_the_upload_match():
    """The file added `onScreen` because NotebookLM parks a full-size button at
    x=-36 with a live offsetParent. The upload matcher never used it."""
    spec = el("body", {}, "", [
        # Off-canvas but full-size — the documented NotebookLM shape.
        el("button", {"aria-label": "Upload file", "x": "-400", "w": "120", "h": "40"}, ""),
        el("button", {"aria-label": "Upload file", "x": "40", "w": "120", "h": "40"}, ""),
    ])
    out = _click(spec, ["upload file"])
    assert out["ret"] and out["ret"]["label"] == "Upload file"
    # Exactly one click, and on the on-screen one.
    assert out["marks"] == 1, "exactly one element must be marked"


@needs_node
@pytest.mark.parametrize("attr", ["aria-disabled", "disabled"])
def test_a_disabled_control_cannot_win_the_upload_match(attr):
    """⚠ The two candidates must be DISTINGUISHABLE. The first version of this
    test gave both the same aria-label, so a mutant that removed the disabled
    check matched the disabled one first and still returned "Upload file" with
    exactly one click — identical observable output. Same label, no signal."""
    spec = el("body", {}, "", [
        el("button", {"aria-label": "Upload file (disabled)", attr: "true",
                      "w": "120", "h": "40"}, ""),
        el("button", {"aria-label": "Upload file (live)", "w": "120", "h": "40"}, ""),
    ])
    out = _click(spec, ["upload file"])
    assert out["ret"] and out["ret"]["label"] == "Upload file (live)", (
        f"the {attr} control won the match and was pressed with no effect"
    )
    assert out["marks"] == 1, "exactly one element must be marked"


@needs_node
def test_a_label_for_a_hidden_input_is_now_a_candidate():
    """`<label for=…>` is how a styled upload control is usually built, and the
    old query could not match one at all."""
    spec = el("body", {}, "", [
        el("label", {"for": "f", "w": "120", "h": "40"}, "Upload file"),
    ])
    out = _click(spec, ["upload file"])
    assert out["ret"] and out["ret"]["label"] == "Upload file"
    assert out["ret"]["tag"] == "LABEL"
    assert out["marks"] == 1


@needs_node
def test_pattern_order_is_still_authoritative():
    """⚠ The r2 review invariant: a specific pattern must be exhausted page-wide
    before a generic one. Widening the candidate query must not disturb it."""
    spec = el("body", {}, "", [
        el("button", {"aria-label": "Upload something else", "w": "120", "h": "40"}, ""),
        el("button", {"aria-label": "Add source", "w": "120", "h": "40"}, ""),
    ])
    out = _click(spec, ["^add source", r"\bupload\b"])
    assert out["ret"] and out["ret"]["label"] == "Add source"


@needs_node
def test_a_dialog_scoped_candidate_still_wins_within_a_pattern():
    spec = el("body", {}, "", [
        el("button", {"aria-label": "Upload file", "w": "120", "h": "40"}, ""),
        el("div", {"role": "dialog", "w": "400", "h": "300"}, "", [
            el("button", {"aria-label": "Upload file", "w": "120", "h": "40"}, ""),
        ]),
    ])
    out = _click(spec, ["upload file"])
    assert out["ret"] and out["ret"]["label"] == "Upload file"
    assert out["marks"] == 1, "exactly one element must be marked"


def test_the_chooser_fallback_rechecks_for_the_hidden_input():
    """The click we just made is the most likely thing to have opened the
    Add-sources dialog that CONTAINS the input. Waiting 10s for a chooser
    instead is how this went 0/3."""
    src = code_only(research._nlm_dom_add_files)
    # Anchor on CODE, not on the "Chooser fallback" comment — code_only strips
    # comments, which is the whole point of using it.
    tail = src[src.index("fired_any = False"):]
    # ⚠ Assert on the QUERY, not the variable name. A mutant setting
    # `_late_inp = None` left the name in place and passed the first version of
    # this test — the binding is not the lookup.
    assert '_late_inp = await page.query_selector(\'input[type="file"]\')' in tail, (
        "nothing actually looks for the hidden input the Upload click revealed"
    )
    assert tail.index("_late_inp") < tail.index("_upload_queue"), (
        "the input re-query must precede the chooser wait, or it never runs on "
        "the path that needed it"
    )
    assert "set_input_files([p])" in tail


def test_the_chooser_failure_names_the_control_it_pressed():
    """The filename is the one thing we already knew. Three identical warnings
    could not distinguish "we pressed the right control and Chrome refused" from
    "we pressed a heading" — and this branch does not break, so the same control
    was pressed three times."""
    src = code_only(research._nlm_dom_add_files)
    line = src[src.index("chooser never opened"):][:220]
    assert "{clicked" in line


# ── (c) NOT a bug: the notebook host ──────────────────────────────────────

@pytest.mark.parametrize("url,ok", [
    ("https://notebook.google.com/notebook/7aef7b7b-326f", True),
    ("https://notebooklm.google.com/notebook/7aef7b7b-326f", True),
    ("https://notebook.google.com/", False),
    ("https://notebooklm.google.com/", False),
    ("https://notebook.google.com/notebook/", False),
    ("https://example.com/notebook/abc", False),
])
def test_the_notebook_check_is_a_shape_test_not_a_hostname(url, ok):
    """⭐ The host is IRRELEVANT and the path shape is what is strict. The
    incident report flagged `delivery.json.notebook_url` on notebook.google.com
    as "the same host mismatch as the standing P3 finding" — the standing finding
    is FIXED, that host is now canonical, and this is the fix working. Pinned so
    nobody "repairs" it back into a literal."""
    assert research.is_notebooklm_url(url) is ok


def test_no_hostname_literal_gates_a_live_notebook_url():
    """The four gates that carried one were replaced by the shape test after the
    2026-07-31 outage. Remaining literals are navigation SEEDS, never compared
    against a live URL."""
    src = code_only_deep(inspect.getsource(research.is_notebooklm_url))
    assert '"notebooklm.google.com" in' not in src
    assert '"notebook.google.com" in' not in src


# ── (d) the ChatGPT share extractor ───────────────────────────────────────

SHARE_SRC = code_only(research.extract_share_link_chatgpt)


def test_the_clipboard_is_armed_before_the_copy_click():
    """Every other extractor arms. This one read the clipboard four times and
    accepted any string containing the share host — it could not tell a fresh
    copy from yesterday's. It returned nothing this run, but the leg was already
    sitting on the previous evening's conversation."""
    assert "_arm_clipboard()" in SHARE_SRC
    assert SHARE_SRC.index("_arm_clipboard()") < SHARE_SRC.index("link_btn.click("), (
        "arming after the copy proves nothing"
    )


def test_the_arming_helper_really_clears_the_channel():
    """A guard that calls a no-op helper is decorative. Exercise the real one."""
    research._arm_clipboard()
    assert callable(research._arm_clipboard)
    src = code_only(research._arm_clipboard)
    assert src.strip() and "pass" != src.split(":", 1)[-1].strip()


def test_the_cua_share_mission_is_pinned_to_the_page():
    """Without a target, a 31.5s hunt is not guaranteed to be on the tab whose
    url seeded the result — which is why the prod narration about a
    "shared/read-only view" cannot be used as evidence about that tab."""
    assert "switch_to_page(page)" in SHARE_SRC
    i_switch = SHARE_SRC.index("switch_to_page(page)")
    i_cua = SHARE_SRC.index("async def _chatgpt_share_cua")
    assert i_switch < i_cua


def test_the_cua_pass_arms_the_clipboard_too():
    """Its whole stated purpose is "public-share URL on clipboard"."""
    region = SHARE_SRC[SHARE_SRC.index("CUA fallback for share link"):]
    region = region[:region.index("async def _chatgpt_share_cua")]
    assert "_arm_clipboard()" in region
