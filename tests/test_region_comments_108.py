"""The comments in the run-lifecycle region, held to what the code does.

⛔⛔ WHY A TEST AND NOT JUST AN EDIT. `research.py` is 85,000 lines in six
disjoint blocks, and the comments are the only index anyone has. Wave 10.8's
start cross-check lost a lens to exactly this: a `KNOWN LIMITATION` comment
written 2026-07-16 described a defect that was fixed the next morning, sat
seventeen lines above the mechanism that fixed it, and a measuring pass read it
and reported the item as OPEN. Rewriting it is worth a commit. Pinning the
shapes that let it happen is worth more.

⭐ WHAT IS PINNED HERE IS NARROW ON PURPOSE. Nobody can test that prose is
true. What a test CAN do is hold the few claims that are mechanically
checkable — a named branch exists, a dodge is still in place, a count does not
grow — and those are the three shapes that actually went wrong.
"""
import ast
from pathlib import Path

import research

SRC = Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")


# ══ 1. the pointers ════════════════════════════════════════════════════
# ⭐ The ratchet that stood here (ceiling 47, measured 2026-09-21) is replaced
# by `tests/test_no_line_pointers.py`: wave 10.10 swept every line-number
# pointer in the repository to the name it meant, and that guard holds the
# count at ZERO over every form — this one saw only `research.py:N`, which was
# 42 of the file's 141.


def test_the_two_notes_that_deliberately_refuse_a_line_number_are_still_there():
    """⭐ ACCEPT POLARITY for the pointer guard. A guard that only ever counts
    down is satisfied by deleting the comments, and this is the one that
    teaches the habit — in its own words, the previous note there cited a
    number that had drifted by seventy lines."""
    assert "No line number on purpose" in SRC


# ══ 2. comments that named a branch which does not exist ═══════════════
def test_nothing_claims_an_is_retry_attempt_branch_any_more():
    """⛔⛔ THE SHAPE THAT COST THE MOST. `_runtime.is_retry_attempt` is
    declared, assigned once and READ NOWHERE — and two comments sent readers to
    "the `_runtime.is_retry_attempt` branch at each browser-crash site", which
    has never existed. One of the two went further and described a safety
    property the code does not have: that auto-retry cannot fire on a resumed
    run. Since #725 it can, and that is why a person's Retry buys three more
    silent relaunches."""
    reads = [
        n for n in ast.walk(ast.parse(SRC))
        if isinstance(n, ast.Attribute) and n.attr == "is_retry_attempt"
        and isinstance(n.ctx, ast.Load)
    ]
    assert reads == [], (
        "something reads `is_retry_attempt` now — the comments calling it dead "
        "have to be corrected in the same change, or they become the next "
        "wrong pointer")
    assert "branch at each browser-crash site" not in SRC, (
        "the comment naming a branch that does not exist is back")


def test_the_planner_still_lets_a_crash_retry_a_resumed_run():
    """⛔ THE FACT THE CORRECTED COMMENT NOW ASSERTS. If this ever changes, the
    comment beside the assignment becomes wrong in the other direction — and a
    comment that is wrong in a SAFE direction is the one nobody re-checks.

    ⛔⛔ AND THIS IS PARSED, NOT GREPPED, FOR A REASON I WALKED INTO. The first
    version was `assert "if not ((not resume_dir) or ..." in SRC` — and the
    corrected comment QUOTES that line, so the needle was satisfied by the
    prose explaining it. Delete the gate entirely and the test stays green off
    its own documentation. That is the trap the frontend's `srcCode` helper
    exists for and this suite has no equivalent of; parsing sidesteps it.
    """
    planner = next(
        n for n in ast.walk(ast.parse(SRC))
        if isinstance(n, ast.FunctionDef) and n.name == "_plan_pipeline_auto_retry")
    gates = [
        n for n in ast.walk(planner)
        if isinstance(n, ast.If)
        and {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)}
        >= {"resume_dir", "is_crash", "crash_budget_ok"}
    ]
    assert gates, (
        "the planner's retry gate no longer reads resume_dir, is_crash and the "
        "crash budget together — a crash on a resumed run may no longer retry, "
        "which is the opposite of what the comment beside the dead flag says")


# ══ 3. the dodge that is the whole safety margin ═══════════════════════
def test_both_manual_brief_emitters_still_pass_an_explicit_empty_action_list():
    """⛔⛔ ONE WORD IS THE WHOLE MARGIN. `ALERT_INTENTS["manual_brief"]`
    declares the token `brief_input`, and `_alert_actions_for` has no branch
    for it — the fall-through is a `raise NotImplementedError`, not a logged
    warning. Both live callers dodge it by passing `actions=[]`, and that works
    ONLY because the guard reads `if actions is None` rather than a truthiness
    test: `[]` is falsy, so the common idiom `actions or _alert_actions_for(…)`
    would make the crash live today, in phase 1, on a person waiting to type
    their brief.

    Nothing tested either half. `tests/test_alert_intents.py` asserts the
    expander RAISES for this intent — it pins the trap open rather than
    guarding against it, and it passes whether or not the callers still dodge.
    """
    calls = [
        n for n in ast.walk(ast.parse(SRC))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "emit_decision"
        and any(k.arg == "intent" and isinstance(k.value, ast.Constant)
                and k.value.value == "manual_brief" for k in n.keywords)
    ]
    assert len(calls) == 2, f"expected 2 manual_brief emitters, found {len(calls)}"
    for c in calls:
        actions = next((k.value for k in c.keywords if k.arg == "actions"), None)
        assert isinstance(actions, ast.List) and actions.elts == [], (
            f"the manual_brief emitter at line {c.lineno} no longer passes an "
            f"explicit empty action list — the catalogue names a button the "
            f"builder cannot make, and the fall-through raises")


def test_the_guard_that_makes_that_dodge_work_is_an_identity_check():
    """⛔ `if actions is None` and NOT `if not actions`. Tidying it to the
    truthier idiom turns the dodge above into a crash, and every other test in
    this suite would stay green."""
    assert "    if actions is None:" in SRC
    assert "    if not actions:" not in SRC


# ══ 4. the comment the cross-check actually tripped over ═══════════════
def test_the_dead_worker_note_no_longer_contradicts_the_code_below_it():
    """⛔⛔ THE ONE THAT COST A LENS. It described the backstop as prototyped
    and REVERTED, seventeen lines above the rehydration and a few hundred above
    the reconciler that implements it. A measuring pass read it and reported
    the item open."""
    assert "prototyped and\n                        # REVERTED" not in SRC
    assert "tracked for a follow-up" not in SRC, (
        "the note still describes the backstop as future work")
    # and it names the mechanism by SYMBOL, which cannot drift the way a line
    # number does
    assert "_dead_worker_reconcile_loop" in SRC
    assert "#64 SHIPPED THE NEXT MORNING" in SRC


def test_the_drive_wait_rationale_no_longer_cites_the_removed_abort_handler():
    """⛔ The comment justified a 3600-second hold with a web behaviour that
    was removed on 2026-09-19 and is in production: a closed socket used to
    SIGTERM the encode and write `status: "stopped"`, and does not any more.
    The number stays — the route still runs P4/P5 inline — but for a different
    reason, and the comment now says which."""
    assert "THE REASON WRITTEN HERE EXPIRED ON 2026-09-19" in SRC
    # ⛔ THE NEEDLE STOPS AT THE LINE WRAP. `"A CLOSED SOCKET IS NOT A STOP"`
    # reads as one phrase and is not one string — prose comments wrap, and the
    # quotation breaks after the `A`. A needle that spans a wrap fails against
    # text that is present, which is a false alarm, and a reader chasing it
    # concludes the comment is missing when it is merely reflowed.
    assert "CLOSED SOCKET IS NOT A STOP" in SRC
    # ⛔ AND THE TWO COPIES OF THE OLD REASON ARE GONE (wave 10.10). The
    # respawn gate's docstring and its call site's comment still said the route
    # "aborts the request, SIGTERMs ffmpeg and terminalises the research" a
    # wave after the tombstone above retired that sentence. The tombstone
    # quotes it in its own words ("SIGTERMs the in-flight ffmpeg child"), so
    # this needle cannot be satisfied by the tombstone, only by a copy.
    assert "SIGTERMs ffmpeg" not in SRC, (
        "a note again says a dropped connection SIGTERMs ffmpeg — untrue since "
        "2026-09-19; say the route runs P4/P5 inside the request instead")
    assert "SIGTERMs the in-flight ffmpeg child" in SRC, (
        "the tombstone that keeps the history is gone — this guard's needle "
        "was chosen to miss it, so its absence means the text moved")
    assert research._FE_DRIVE_WAIT_SEC == 3600
    # ⛔ AND THE CONSTANT BESIDE IT SURVIVES. Rewriting this block deleted
    # `_FE_HANDOFF_WAIT_SEC` once — `ast.parse` was happy, because its two
    # readers are inside a function and the absence is only a NameError at
    # call time. Importing the module is what catches that, so the assertion
    # is on the VALUE, not on the text.
    assert research._FE_HANDOFF_WAIT_SEC == 90
    assert research._fe_respawn_wait_budget() == 90
