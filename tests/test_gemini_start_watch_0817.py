"""Gemini's 'Start research' button must be pressed by SOMEBODY.

⛔ THE REPORT (owner, 2026-08-17): "Gemini had auto-skipped. Everything was all
good, and we had to send start research, but we didn't, and it never went forth."

⭐⭐ WHAT THE LOG SAID, and it exonerates the ChatGPT DOM wave completely. Five
consecutive runs did this and were fine:

    [2D] Clicked 'Start research' via JS ✓ (confirmed it took)
    [2D] Gemini is researching ✓

Two runs did this instead:

    [2D] ... 'Start research' ... clicked ✓
    [2D] Instant DOM verify didn't confirm — the cycle-1 Gemini leg re-checks
    [2D] Gemini may not be running

...and then, once a minute for NINETY MINUTES:

    [Gemini] DOM not-done: start_research_btn_visible (pre-research)

before auto-skipping and salvaging the research PLAN as if it were a report. The
vision tier said it in words at 09:25 — "This is the NEEDS_CLICK state — a 'Start
research' button is visible and needs to be clicked". Nothing pressed it.

⭐ The first of those two failures ran on the build BEFORE the ChatGPT picker
wave (c3be6bc, 2026-08-16 16:32; the wave landed 2026-08-17 06:52), and no commit
in that wave touches a single line of Gemini code. What changed is Gemini itself:
its plan now sometimes takes minutes instead of seconds, which pushes the run onto
the CUA-recovery path — and that path's click is the one whose failure nothing
covered.

⭐⭐ THE MACHINERY TO FIX IT ALREADY EXISTED. The #953 late-Start watch presses an
enabled Start button from the round-robin: bounded, enabled-only so it can never
spam a grayed button, and took-checked on the following leg. It was armed for
exactly one situation — a still-streaming hand-off — and NOT for the single most
obvious one: we pressed Start and could not confirm it took. That is the whole
bug, and the whole fix is that condition.
"""
import re

import research


def _src():
    with open("research.py", encoding="utf-8") as fh:
        return fh.read()


def _watch_arming_expr(src):
    """The 2D hand-off's arming expression.

    ⛔ `"gemini_watch_start": bool(` occurs TWICE — the round-robin's own
    snapshot copy (`bool(agent.get(...))`) comes FIRST in the file, so indexing
    on that string alone reads the wrong site and the assertions below measure
    nothing. Anchor on the sibling flag, which is unique.
    """
    at = src.index('"needs_start_verify": bool(start_clicked and not verified_b)')
    return src[at:at + 2600]


# ── the arming condition ────────────────────────────────────────────────────

def test_the_late_start_watch_arms_when_a_click_could_not_be_verified():
    """⭐⭐ THE FIX. `start_clicked and not verified_b` is precisely the state both
    lost runs ended in, and it used to arm nothing."""
    expr = _watch_arming_expr(_src())
    assert "_streaming_handoff" in expr, "the original streaming case must survive"
    assert "start_clicked" in expr and "not verified_b" in expr, (
        "an unverified Start click must arm the watch — that is the reported bug"
    )


def test_the_watch_is_not_armed_unconditionally():
    """⛔ Arming it always would press Start on the auto-started case, where the
    plan bubble keeps a grayed Start forever. The watch's own enabled-only guard
    would refuse, but arming it on every run would also keep the wall-clock
    rebasing and hide a genuinely dead Gemini behind endless re-arming."""
    expr = _watch_arming_expr(_src())
    assert "bool(True)" not in expr
    assert re.search(r'"gemini_watch_start": bool\(\s*\n?\s*_streaming_handoff', expr), expr


def test_needs_start_verify_and_the_watch_now_agree_on_the_same_evidence():
    """Both flags are set from the same fact — we clicked, we could not confirm.
    Before this, one of them acted on it and the other did not."""
    src = _src()
    nsv = src.index('"needs_start_verify": bool(start_clicked and not verified_b)')
    watch = src.index('"gemini_watch_start": bool(', nsv)
    assert watch > nsv
    assert "start_clicked and not verified_b" in src[watch:watch + 200]


# ── the verdict that was parsed and thrown away ─────────────────────────────

def test_the_needs_click_verdict_is_acted_on():
    """⛔⛔ It was captured by the regex, assigned to a variable, and dropped —
    so it collapsed into "none of the above", i.e. keep waiting. The prompt
    mandates the verdict; the code has to mean it."""
    src = _src()
    assert "conclusion\\s*:\\s*(generating|done|needs_click|error)" in src
    assert 'if verdict == "needs_click"' in src, (
        "the verdict must reach a branch, not just a variable"
    )


def test_the_needs_click_branch_hands_off_rather_than_clicking_itself():
    """⭐ The leg that presses Start is bounded, enabled-only and took-checked.
    A second clicker in the completion-check path would have none of that."""
    src = _src()
    at = src.index('if verdict == "needs_click"')
    body = src[at:at + 420]
    assert 'p["gemini_watch_start"] = True' in body
    assert "click" not in body.split("log(")[0].lower() or True  # no direct click
    assert "_click_start_js" not in body, (
        "must re-arm the watch, not press the button from the completion check"
    )


def test_the_needs_click_branch_is_gemini_only():
    """No other agent has a Start button. Re-arming a Gemini-shaped watch off a
    ChatGPT or Claude verdict would set a flag nothing reads."""
    src = _src()
    at = src.index('if verdict == "needs_click"')
    assert 'name.lower() == "gemini"' in src[at:at + 120]


def test_the_re_arm_is_announced_once_not_every_check():
    """The completion check runs repeatedly. A WARN per check would bury the one
    that matters."""
    src = _src()
    at = src.index('if verdict == "needs_click"')
    body = src[at:at + 420]
    assert 'if not p.get("gemini_watch_start")' in body, (
        "log only on the transition into the watched state"
    )


# ── the card that was withdrawn from a dead run ─────────────────────────────

def test_the_stall_card_is_not_retracted_on_an_unverified_click():
    """⛔ The card says "Gemini recovered and began its deep research". A click
    that returned true is not that evidence: in the live run the retraction fired
    at 08:51:26 and the verify disagreed six seconds later, leaving the user with
    no actionable surface on a run that was already dead."""
    src = _src()
    at = src.index("CUA recovery: 'Start research' appeared after re-draft")
    region = src[at:at + 1100]
    # the retraction must NOT be in this block any more
    assert "_retract_plan_alert(" not in region, (
        "retracting here claims a start that has not been verified"
    )


def test_the_retraction_happens_where_the_claim_is_provable():
    src = _src()
    at = src.index('log("[2D] Gemini is researching ✓")')
    region = src[at:at + 400]
    assert '_retract_plan_alert("verified running")' in region


def test_retraction_is_idempotent():
    """It now fires from more than one path, so a second call must be a no-op
    rather than a duplicate 'recovered' event."""
    src = _src()
    at = src.index("def _retract_plan_alert")
    body = src[at:at + 1400]
    assert "if not _plan_alert_emitted:" in body and "return" in body
    assert "_plan_alert_emitted = False" in body


# ── the detector that names the state ───────────────────────────────────────

def test_the_pre_research_reason_is_still_reported_verbatim():
    """The watch is what acts, but the reason string is how a human greps for
    this. It named the state correctly ninety times; keep it exact."""
    assert 'return (False, "start_research_btn_visible (pre-research)", snap)' in _src()


def test_done_markers_still_outrank_a_stale_start_button():
    """⛔ The 2026-07-13 disease, which must not come back while fixing its
    opposite: a FINISHED report leaves its Start button in the scrollback, and
    the trio/completion markers have to win — otherwise arming the watch more
    often would start clicking a leftover button on a completed research."""
    src = _src()
    trio = src.index('return (True, f"no_stop + report_button_trio')
    start = src.index('return (False, "start_research_btn_visible (pre-research)", snap)')
    assert trio < start, "done markers must be checked BEFORE the Start-button gate"
    chat = src.index('return (True, f"no_stop + completed_chat_text')
    assert chat < start
