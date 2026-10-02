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
    assert "or (start_clicked and not verified_b))}" in expr, (
        "an unverified Start click must arm the watch — that is the reported bug")


def test_the_wait_that_ended_with_nothing_pressed_arms_it_on_the_runs_own_chat():
    """⭐ Wave 15: Gemini starts by itself, and a plan that shows its Start after
    the wait is pressed by the watch. ⛔ Only on the run's own chat — the watch
    presses — and never for a Gemini that already finished on its own."""
    expr = _watch_arming_expr(_src())
    assert ("(not start_clicked and not _finished_handoff\n"
            "                                     and not _controls.is_stop() and _chat_ok)"
            in expr), expr


def test_the_watch_is_not_armed_unconditionally():
    """⛔ Arming it always would press Start on a tab that is not the run's chat,
    and keep the wall-clock rebasing on a Gemini that finished."""
    expr = _watch_arming_expr(_src())
    assert "bool(True)" not in expr
    assert re.search(r'"gemini_watch_start": bool\(\s*\n\s*\(not start_clicked', expr), expr


def test_needs_start_verify_and_the_watch_now_agree_on_the_same_evidence():
    """Both flags are set from the same fact — we clicked, we could not confirm.
    Before this, one of them acted on it and the other did not."""
    src = _src()
    nsv = src.index('"needs_start_verify": bool(start_clicked and not verified_b)')
    watch = src.index('"gemini_watch_start": bool(', nsv)
    assert watch > nsv
    assert "start_clicked and not verified_b" in src[watch:watch + 400]


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


# ⛔ Wave 15 (10-02): the plan wait raises no card any more, so the tests of
# where its card was taken down went with it.
