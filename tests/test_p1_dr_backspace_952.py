"""#952 (2026-07-13): P1 ChatGPT — remove a sticky Deep Research tool with
BACKSPACE, never by re-clicking the tool item.

E2E RUN (backend-2.log, 2026-07-13 17:01): a prior P2's 'Deep research' tool was
sticky-on for the next run's Phase-1 composer (pill='deep research',
placeholder='get a detailed report'). The old clear helper tried to turn it off
by (Strategy A) opening the '+'/tools menu and CLICKING the already-selected
'Deep research' item, and (Strategy C, CUA) the PROMPT_CHATGPT_DISABLE_DR prompt
literally said "open the + menu and click the already-selected Deep research to
deselect it". But ChatGPT's tools menu no longer TOGGLES — clicking the item
ADDS a SECOND Deep Research. User-observed: "when deep research is on, it's
trying to again click deep research but that's adding 2 deep researches instead
of removing." (In the logged run Strategy A happened to open the sidebar and
miss with item clicked=False, then the ~60s CUA fallback at 17:01:34→17:02:35
did the adding click; the run ended 'could not confirm Deep Research is OFF'.)

THE FIX (user-directed): the composer tool renders as an INLINE TOKEN at the
start of the (still-empty, pre-brief) composer, so the platform's real remove
affordance is BACKSPACE — "we clear it with backspace (just like deleting
text)". Primary strategy is now a bounded Backspace loop (focus composer → caret
to end → Backspace), guarded by a textLen probe so it can never eat typed prose
and never touches a PDF card (separate row). The tools-menu re-click is REMOVED,
and the CUA fallback + PROMPT_CHATGPT_DISABLE_DR are rewritten to press Backspace
and EXPLICITLY forbid clicking the Deep research tool (a click adds a second).

Run: pytest tests/test_p1_dr_backspace_952.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

CLEAR_SRC = inspect.getsource(research._chatgpt_clear_deep_research)
FOCUS_JS = research._CHATGPT_FOCUS_COMPOSER_END_JS


# ── The focus JS: caret to end + textLen guard ───────────────────────────────

def test_focus_js_collapses_caret_to_end_and_reports_textlen():
    # Backspace must land immediately AFTER the inline token → caret collapses to
    # the END of the composer contents.
    assert "collapse(false)" in FOCUS_JS, "caret must collapse to the very end"
    assert "selectNodeContents" in FOCUS_JS or "setSelectionRange" in FOCUS_JS
    # It reports the char count the caller uses to refuse deleting real prose.
    assert "textLen" in FOCUS_JS and "return { ok" in FOCUS_JS


def test_focus_js_handles_contenteditable_and_textarea():
    # ChatGPT's composer is a contenteditable in the current UI, but the helper
    # must degrade to a <textarea> value path too.
    assert "isContentEditable" in FOCUS_JS
    assert "#prompt-textarea" in FOCUS_JS
    assert "textarea" in FOCUS_JS


# ── Strategy A: bounded Backspace, prose-safe ────────────────────────────────

def test_backspace_is_the_primary_strategy():
    assert "_CHATGPT_FOCUS_COMPOSER_END_JS" in CLEAR_SRC
    assert 'press("Backspace")' in CLEAR_SRC
    assert "Strategy A (Backspace delete)" in CLEAR_SRC


def test_backspace_loop_is_bounded_by_env():
    assert "DG_CHATGPT_DR_BACKSPACE_TRIES" in CLEAR_SRC
    assert "_BS_TRIES" in CLEAR_SRC
    # Re-verifies with _still_active between presses (stops as soon as it clears).
    a = CLEAR_SRC.index('press("Backspace")')
    assert "_still_active()" in CLEAR_SRC[:a], (
        "the loop must re-check DR-active around the Backspace so it stops the "
        "moment the token is gone"
    )


def test_backspace_refuses_when_composer_has_text():
    # Never eat the brief: if the composer already holds typed prose the helper
    # must skip Backspace entirely.
    assert "textLen" in CLEAR_SRC
    assert "skipping Backspace" in CLEAR_SRC


def test_prose_guard_tolerates_a_bare_token_label():
    # If the DR pill renders as an INLINE token inside the editable, its own
    # label ('Deep research') inflates innerText — so the guard must be a
    # THRESHOLD (clearly-prose), not '> 0', or the token's own text would block
    # its removal. The detector caps a token label at <= 30 chars; the guard sits
    # above that so a bare-token composer is still cleared.
    import re
    assert "_DR_PROSE_GUARD" in CLEAR_SRC
    assert "> _DR_PROSE_GUARD" in CLEAR_SRC, (
        "the guard must compare against the threshold, not '> 0'"
    )
    # The threshold must exceed the detector's <=30-char token-label cap.
    m = re.search(r"_DR_PROSE_GUARD\s*=\s*(\d+)", CLEAR_SRC)
    assert m and int(m.group(1)) > 30, (
        "the prose guard must be above the 30-char token-label cap so a bare "
        "'Deep research' token never blocks its own Backspace removal"
    )


# ── Regression: the click-toggle that ADDS a second DR is gone ────────────────

def test_no_tools_menu_click_toggle():
    # The removed path OPENED the '+'/tools menu and CLICKED the 'Deep research'
    # item. Pin its open-signatures (the kept diagnostic dump queries
    # menuitemradio in a selector but never clicks it, so we don't ban that
    # substring).
    assert "composer-plus-btn" not in CLEAR_SRC, (
        "opening the '+'/tools menu to click the 'Deep research' item adds a "
        "second DR — that path must be removed"
    )
    assert "Use a tool" not in CLEAR_SRC, "no tools-menu open"
    assert "menu toggle" not in CLEAR_SRC


# ── Strategy order: Backspace → pill ✕ → CUA ─────────────────────────────────

def test_strategy_order_backspace_first():
    i_bs = CLEAR_SRC.index('press("Backspace")')
    i_pill = CLEAR_SRC.index("Strategy B")
    i_cua = CLEAR_SRC.index("1a-disable-dr")
    assert i_bs < i_pill < i_cua, (
        "Backspace (the deterministic remove) must run before the pill ✕ and "
        "before the CUA fallback"
    )


def test_pill_x_only_clicks_a_genuine_remove_control():
    # The pill ✕ leg must only ever click remove/close/clear controls — it must
    # NOT click the DR tool item itself (which would re-add).
    b = CLEAR_SRC.index("Strategy B")
    c = CLEAR_SRC.index("Strategy C")
    leg = CLEAR_SRC[b:c]
    assert "remove" in leg and "close" in leg
    assert "toggle" not in leg


def test_pill_x_cannot_delete_an_attached_pdf():
    # Adversarial-review fold (#952, two lenses): clear_dr runs AFTER PDF attach,
    # and ChatGPT labels an attachment's delete control "Remove file 1: brief.md"
    # (#950). The old unscoped ancestor-walk would match that bare 'remove' and
    # silently delete the user's source PDF. The leg must now (a) reject
    # file/attach controls and (b) stop the walk once the container is no longer
    # ~just the DR label (climbing into the composer chrome that holds the cards).
    b = CLEAR_SRC.index("Strategy B")
    c = CLEAR_SRC.index("Strategy C")
    leg = CLEAR_SRC[b:c]
    assert "a.includes('file')" in leg and "a.includes('attach')" in leg, (
        "the remove-control matcher must reject file/attachment controls so it "
        "can never delete an attached PDF"
    )
    assert "ctext" in leg and "ctext.length > 40" in leg, (
        "the ancestor walk must stop once the container text stops being ~just "
        "the DR label (it has climbed into shared composer chrome / file cards)"
    )
    # The walk must be bounded tightly (was 4 ancestors, now 3).
    assert "i < 3" in leg


# ── Strategy C: CUA fallback is Backspace-oriented, forbids clicking ─────────

def test_cua_fallback_mission_forbids_clicking_the_tool():
    b = CLEAR_SRC.index("Strategy C")
    leg = CLEAR_SRC[b:].lower()
    assert "backspace" in leg, "the CUA mission must tell Vision to press Backspace"
    assert "adds a second" in leg, (
        "the CUA mission must warn that clicking the tool adds a second DR"
    )
    assert "do not click" in leg or "do not click the" in leg


# ── The shared PROMPT_CHATGPT_DISABLE_DR (prompts.py) ────────────────────────

def test_hotspot_hint_uses_backspace_and_forbids_clicking():
    # Adversarial-review fold (#952): the CANONICAL _HOTSPOT_VISION_HINTS entry
    # for 1a-disable-dr LEADS the merged flow_context.context_hint (the call-site
    # run-detail is demoted to a trailing parenthetical), so it must ALSO be
    # backspace-oriented — a stale 'click Deep research to deselect' here steers
    # tier2/act Vision straight into adding a second DR.
    hint = research._HOTSPOT_VISION_HINTS["1a-disable-dr"]["context_hint"].lower()
    assert "backspace" in hint
    assert "adds a second deep research" in hint
    assert "do not click" in hint
    # The removed toggle-click instruction must be gone.
    assert "to deselect" not in hint
    assert "tools menu and click" not in hint


def test_prompt_uses_backspace_and_forbids_clicking():
    p = research.PROMPT_CHATGPT_DISABLE_DR.lower()
    assert "backspace" in p, "the disable-DR prompt must instruct Backspace"
    assert "adds a second deep research" in p, (
        "the prompt must state that clicking the item adds a second DR"
    )
    assert "do not click" in p
    # The old #923 invariants must still hold.
    assert "do not enable any other tool" in p
    assert "do not press send" in p or "do not send" in p


# ── Fail-safe posture is preserved ───────────────────────────────────────────

def test_still_failsafe_and_never_enables_a_tool():
    assert "try:" in CLEAR_SRC and "except Exception" in CLEAR_SRC
    # Never call the P2 ON-setup.
    assert "await setup_chatgpt_dr(" not in CLEAR_SRC
    assert "await setup_gemini_dr(" not in CLEAR_SRC
    # Final diagnostic dump on a total failure stays (pins the real control).
    assert "composer dump" in CLEAR_SRC
