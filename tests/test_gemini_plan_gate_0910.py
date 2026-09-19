"""The [2D] plan gate — state, not text — and "the alert comes last" (2026-09-10).

Two things this wave changed about the plan wait, both measured first:

  * ⛔⛔ THE GATE WAS `not start_clicked` PLUS A PAGE-WIDE TEXT PROBE. That
    condition is true for the whole drafting window, so the branch leaned
    entirely on the shared retry helper's fail-text check to stay off a healthy
    plan — and that helper reads `document.body.innerText`, which holds the
    pasted brief and the rail's chat titles. It is asked for the plan's STATE
    now, from four measured inputs.
  * ⛔⛔ THE CARD'S EVIDENCE ARM HAD NEVER FIRED. `regen_capped` is fed by a
    counter that only advances when a re-draft is clicked, and nothing could
    click Gemini's control ("Redo" against a `retry|regenerate|try again|rerun|
    restart` word list). Eight green tests, one unreachable branch, and every
    card this predicate ever raised came from the clock.

The behaviour of the reader and the clicker is pinned by EXECUTION against the
owner's captured DOM in `test_gemini_redraft_0910.py`. What is left here is the
wiring and the ordering, which live inline in `run_phase2` — so those are
source-scoped guards, matching the suite convention, and they say so.
"""

from __future__ import annotations

import ast
import inspect


import research


def _phase2_src():
    return inspect.getsource(research.run_phase2)


def _2d_loop():
    """The [2D] plan-wait loop, from its init to the CUA recovery."""
    src = _phase2_src()
    return src.split("start_clicked = False", 1)[1].split(
        '# CUA recovery for "Start research"', 1)[0]


# ── The hold ────────────────────────────────────────────────────────────────
#
# ⛔⛔ THERE IS NO LONGER A HELPER HERE, AND THAT IS THE FIX. The first version
# computed the hold from `acted and not redrafted and count < cap` — which
# conflated two different facts and put the cap in two places at once. Both were
# wrong, and cross-verify found both:
#
#   · `acted` is true on paths where nothing is generating — an overlay whose
#     rows we cannot name and then dismiss, an `evaluate` that raised. Holding
#     the owner's alert for those waits on something that cannot arrive, which
#     the helper's own docstring said it would never do.
#   · with the cap in the hold AND in the predicate's `regen_capped` arm, the
#     two were mutually exclusive by construction — so the arm ORDER the
#     docstring emphasises could never be exercised, and a mutation of it was
#     free.
#
# The hold is now the third boolean `_gemini_redraft_plan` returns, `in_flight`,
# which is pinned at the orchestrator in test_gemini_redraft_0910.py.

# ── The card predicate's new arm ─────────────────────────────────────────────

def _due(**kw):
    args = {"elapsed": 400, "wait_max_sec": 300, "alert_sec": 240,
            "regen_capped": False, "streaming_recent": False,
            "start_clicked": False, "redraft_pending": False}
    args.update(kw)
    return research._gemini_plan_card_due(**args)


def test_the_timer_arm_still_fires_when_no_redraft_is_pending():
    assert _due() is True


def test_a_pending_redraft_holds_the_card_past_the_timer():
    """The owner's instruction: the alert comes after the clicks, not beside
    them."""
    assert _due(redraft_pending=True) is False


def test_exhausted_attempts_outrank_a_pending_redraft():
    """⛔ ORDER IS THE CONTENT, AND THIS PAIR IS WHY THE ARM SITS WHERE IT DOES.
    Three spent re-drafts is evidence of failure, not a timer, and #921 exists
    so that evidence reaches the owner early. If the hold could outrank it, a
    stale True would keep the card down for the rest of the run."""
    assert _due(regen_capped=True, redraft_pending=True) is True
    assert _due(regen_capped=True, redraft_pending=True, elapsed=5) is True


def test_a_started_run_still_outranks_everything():
    assert _due(start_clicked=True, redraft_pending=False) is False
    assert _due(start_clicked=True, regen_capped=True) is False


def test_streaming_still_outranks_the_regen_arm():
    assert _due(streaming_recent=True, regen_capped=True) is False


def test_the_new_arm_defaults_to_todays_behaviour():
    """⭐ The parameter is keyword-only with a False default so every existing
    caller and every existing test keeps its exact meaning — the arm is added,
    nothing is redefined."""
    assert research._gemini_plan_card_due(
        elapsed=400, wait_max_sec=300, alert_sec=240, regen_capped=False,
        streaming_recent=False, start_clicked=False) is True


# ── The wiring, inline in run_phase2 ────────────────────────────────────────

def test_the_loop_asks_for_the_plan_state_and_only_redrafts_a_failure():
    loop = _2d_loop()
    assert "_gemini_plan_verdict(" in loop
    i_verdict = loop.index("_gemini_plan_verdict(")
    i_redraft = loop.index("_gemini_redraft_plan(")
    assert i_verdict < i_redraft, (
        "the re-draft must be decided by the verdict, not before it")
    assert '_verdict == "failed"' in loop, (
        "the re-draft is no longer gated on the FAILED verdict — every other "
        "state (ready, drafting, researching, silent) must be left alone")


def _acted_branch_statements():
    """The statements the `if _acted:` branch actually contains, by AST.

    ⛔ SOURCE ORDER CANNOT EXPRESS "UNDER THIS BRANCH", and the first version of
    this test proved it: it compared character offsets with a `+ 200` slack, so
    the cooldown assignment could move up to two hundred characters ABOVE the
    branch and still pass — and once the same assignment appeared at the loop's
    initialisation too, the offset it found was the wrong one entirely. Nothing
    else in this file checks indentation; the parser does it exactly.
    """
    tree = ast.parse(inspect.getsource(research).lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "_acted" and not node.orelse):
            return {ast.unparse(s).split("\n")[0] for s in ast.walk(node)
                    if isinstance(s, (ast.Assign, ast.AugAssign, ast.Expr))}
    raise AssertionError("the `if _acted:` branch is gone from research.py")


def test_the_attempt_is_spent_on_the_click_not_on_the_outcome():
    """⛔ A control that clicks and never re-drafts would otherwise be clicked
    every ten seconds for the whole plan window — the Start-button spam #953
    removed on the directive "send Start Research and wait, only retry if it
    doesn't fire"."""
    body = _acted_branch_statements()
    assert "_regen_count += 1" in body, (
        "the attempt counter is not inside the `acted` branch")
    assert any(s.startswith("_last_regen_at = time.time()") for s in body), (
        "the cooldown is not armed inside the `acted` branch")
    loop = _2d_loop()
    assert "if _redrafted:" not in loop, (
        "the attempt must not be gated on the OUTCOME — that is how a click "
        "that never re-drafts becomes a click every tick")


def test_the_cooldown_clock_starts_with_the_loop_not_at_zero():
    """⛔ AT 0.0 THE COOLDOWN IS ALREADY SATISFIED ON THE FIRST TICK, so a
    re-draft could fire about two seconds after the brief was submitted — at a
    turn still painting. Harmless while nothing could click Gemini's control; a
    live hazard the moment one can."""
    loop = _2d_loop()
    assert "_last_regen_at = 0.0" not in loop
    i_init = loop.index("_last_regen_at = time.time()")
    assert i_init < loop.index("while True:"), (
        "the cooldown clock must be set before the poll loop starts")


def test_the_last_attempt_gets_the_same_patience_as_the_first_two():
    """⛔⛔ THIS ARM WAS UNREACHABLE IN PRODUCTION UNTIL THIS WAVE — nothing could
    click Gemini's control, so the counter never moved — and making it reachable
    exposed a missing grace. Attempts one and two each get the full cooldown to
    produce a plan; the third was judged about ten seconds after its click, the
    settle window and nothing more. Same page, same failure, and a card on the
    third that the first would not have raised: either retracted moments later
    (the 2026-08-17 "cried wolf" pattern) or answered with Skip on a working
    agent (the 2026-07-09 one)."""
    loop = _2d_loop()
    latch = loop[loop.index("_regen_count >= _GEMINI_MAX_PLAN_REGEN"):]
    latch = latch[:latch.index("_regen_cap_emitted = True")]
    assert "_GEMINI_REGEN_COOLDOWN_SEC" in latch, (
        "the exhausted-attempts latch fires the instant the third click lands, "
        "before that click has had the window the other two got")


def test_our_own_redraft_is_not_evidence_that_research_auto_started():
    """⛔⛔ THE HAND-OFF READS PERSISTENT STREAMING AS "the research has almost
    certainly auto-started" — and a Redo we clicked ourselves restarts the plan,
    legitimately, which the heartbeat then reports as `generating`. Before this
    wave nothing could click, so the premise held by accident. Unfixed, a
    planless Gemini is handed to the round-robin as though its research were
    already running: no CUA ladder, no card, and a log line that is false."""
    loop = _2d_loop()
    handoff = loop[loop.index("if (_elapsed >= _stream_handoff_sec"):]
    handoff = handoff[:handoff.index("_streaming_handoff = True")]
    assert "_last_regen_at" in handoff, (
        "the hand-off counts our own re-draft's streaming as proof that Gemini "
        "auto-started its research")


def test_the_running_research_probe_is_bought_only_when_a_click_is_imminent():
    """⭐ THE COST GATE, AND IT IS ALSO THE SAFETY ONE. Re-drafting a RUNNING
    research is the single destructive move on this screen, and the 2026-07-13
    auto-start layout renders Start permanently disabled — so "no Start
    control" cannot tell a dead plan from a live run. The probe answers that,
    and it is paid for on the tick where a click is about to happen rather than
    on every healthy tick."""
    loop = _2d_loop()
    assert "_gemini_reads_as_failed(_latest)" in loop
    i_gate = loop.index("_gemini_reads_as_failed(_latest)")
    i_probe = loop.index("_gemini_research_started(gemini_page)")
    assert i_gate < i_probe, (
        "the running-research probe must sit under the fail-text gate, not "
        "above it")
    assert "_already_running = True" in loop, (
        "a running-research probe that RAISED must read as 'assume it is "
        "running' — at this call site False is what authorises the click, and "
        "the click is the destructive move")
    assert "research_started=_already_running" in loop, (
        "the verdict must be handed the MEASURED value — a hardcoded False "
        "here would make its first arm dead at its only call site")


def test_the_verdict_is_fed_four_measured_inputs_and_no_literals():
    loop = _2d_loop()
    call = loop[loop.index("_gemini_plan_verdict("):]
    call = call[:call.index(")")]
    for bad in ("=False", "=True", '=""'):
        assert bad not in call, (
            f"the verdict is being handed a literal ({bad}) — an arm its only "
            f"caller can never exercise is a guard that cannot fire")


def test_the_start_presence_answer_comes_from_the_finder_that_just_ran():
    """#905's lesson: two finders reading the same DOM differently is how the
    disabled skeleton Start got clicked. The presence answer is derived from
    the click that just happened, not from a second probe."""
    loop = _2d_loop()
    assert "_start_present_now = False" in loop, (
        "the per-tick presence answer must be reset each tick, or a stale True "
        "keeps the loop off a genuinely failed plan forever")
    assert "_start_present_now = True" in loop
    assert "start_present=_start_present_now" in loop
    i_reset = loop.index("_start_present_now = False")
    i_set = loop.index("_start_present_now = True")
    i_use = loop.index("start_present=_start_present_now")
    assert i_reset < i_set < i_use


def test_the_hold_flag_survives_the_cooldown_between_attempts():
    """⛔ IT MUST BE DECLARED OUTSIDE THE WHILE LOOP. 1b only runs once the 45s
    cooldown has elapsed, so a per-tick variable would read False for the whole
    window the card is supposed to be held through — and the card would fire in
    the gap between two clicks."""
    loop = _2d_loop()
    i_decl = loop.index("_redraft_pending = False")
    i_while = loop.index("while True:")
    assert i_decl < i_while, (
        "_redraft_pending is initialised inside the poll loop — it would reset "
        "on every tick that the cooldown skips 1b")


def test_the_break_site_never_holds_the_card_and_the_loop_body_always_can():
    """⛔⛔ THE DEFECT THIS REPLACES WAS A BLOCKER, AND TWO REVIEWERS FOUND IT
    INDEPENDENTLY. Both card sites were handed the hold flag — including the one
    inside `if _elapsed >= _start_wait_max_sec`, where the very next statement
    is an unconditional `break`. So the alert was deferred to a retry that the
    following line cancelled: no card at the moment the loop gives up, and the
    owner's first actionable surface arrived from the CUA ladder's terminal card
    about twelve minutes later. That is the seventeen-minute ladder #921 exists
    to remove, deleted by a boolean rather than by an edit — which is precisely
    what the comment above that block warns about.

    ⭐ The rule runs both ways: an alert that fires while its caller intends to
    keep waiting is wrong, and an alert held while its caller is giving up is
    wrong too."""
    loop = _2d_loop()
    assert loop.count("_gemini_plan_card_due(") == 2
    assert loop.count("redraft_pending=_redraft_pending") == 1, (
        "only the in-loop card site may be held; the break site is the loop "
        "deciding to stop waiting")
    assert loop.count("redraft_pending=False") == 1

    # And it is the BREAK site that passes False — pin which, not just how many.
    i_break = loop.index("_raise_plan_alert(\"our own plan-wait budget is spent\")")
    i_body = loop.index("_raise_plan_alert(\"plan clearly failed\")")
    before_break = loop[:i_break]
    before_body = loop[:i_body]
    assert before_break.rindex("redraft_pending=False") > before_break.rfind(
        "redraft_pending=_redraft_pending"), (
        "the break-site call is being handed the hold flag again")
    assert before_body.rindex("redraft_pending=_redraft_pending") > (
        before_body.rfind("redraft_pending=False")), (
        "the in-loop call has stopped being handed the hold flag, so the alert "
        "is beside the clicks again rather than after them")


def test_the_loop_no_longer_blind_dumps_twelve_buttons():
    """The one-time diagnostic existed so "a future E2E can pin the icon-only
    Regenerate selector". That future arrived: the control is captured and
    targeted structurally, so the dump is now scoped to the two states where
    there is genuinely nothing to click."""
    loop = _2d_loop()
    assert "out.length >= 12" not in loop
    assert "_logged_stall_diag" in loop, (
        "the stall diagnostic is still needed for the plain-chat case — no "
        "plan, no error, nothing to click")
    # ⛔ AND THE FAILED-READ BRANCH MUST ACTUALLY BE GATED ON `found`. Counting
    # the diagnostics does not check that: the mutant that drops the gate leaves
    # all three in place and simply makes one unreachable.
    assert 'not _reading.get("found")' in loop, (
        "the failed-read diagnostic no longer distinguishes a page it could not "
        "read from a plan that is genuinely silent")
    i_gate = loop.index('not _reading.get("found")')
    i_msg = loop.index("Gemini plan reading FAILED")
    assert i_gate < i_msg, "the failed-read message is not under the found gate"
    assert loop.count("_logged_stall_diag = True") == 3, (
        "one diagnostic for 'failed but unreachable', one for a READ THAT "
        "FAILED, and one for 'silent' — the middle one exists because the "
        "first version reported an unreadable page as a silent plan, naming "
        "the wrong cause for the exact failure the diagnostic is for")


def test_the_diagnostic_stays_read_only():
    """⛔ "We do NOT blind-click — clicking an unidentified control risks a
    destructive misclick." The diagnostic paths must not click."""
    loop = _2d_loop()
    diag = loop[loop.index('if _verdict == "failed":'):]
    assert "b.click()" not in diag


VERDICTS = {"researching", "ready", "failed", "drafting", "silent"}


def test_the_verdict_vocabulary_is_exactly_the_five_the_consumer_knows():
    """⛔ THE CONSUMER'S GATE IS A SINGLE EQUALITY (`== "failed"`), so a sixth
    verdict would be handled by nothing at all and read as "leave it alone" —
    silently, on whichever state someone added it for. Run over the whole
    input matrix: the vocabulary must not grow without this failing, and all
    five must be reachable, because an unreachable verdict is a branch the
    consumer is carrying for nothing."""
    seen = set()
    for started in (False, True):
        for present in (False, True):
            for streaming in (False, True):
                for text in ("Sorry, something went wrong.",
                             "Here is your research plan.",
                             ""):
                    seen.add(research._gemini_plan_verdict(
                        research_started=started, start_present=present,
                        streaming=streaming, latest_text=text))
    assert seen == VERDICTS, f"vocabulary drifted: {seen ^ VERDICTS}"


def test_only_a_failed_draft_can_reach_the_redraft_click():
    """Containment by ordering rather than by indentation: the click must sit
    between the `failed` gate and any other verdict test, so no other state can
    fall into it."""
    loop = _2d_loop()
    i_failed = loop.index('if _verdict == "failed":')
    i_redraft = loop.index("_gemini_redraft_plan(")
    assert i_failed < i_redraft, "the click is not under the failed gate"
    for v in VERDICTS - {"failed"}:
        needle = f'_verdict == "{v}"'
        if needle in loop:
            assert i_redraft < loop.index(needle), (
                f"the {v!r} test precedes the re-draft click — that state can "
                "reach a click meant only for a failed draft")


def test_the_loop_names_only_the_two_verdicts_it_has_a_job_for():
    """⛔ THE VOCABULARY GUARD. The click is gated on `failed` and the one-time
    diagnostic on `silent`; `ready`, `drafting` and `researching` are handled by
    being left alone. A new gate on one of those three must fail here and be
    looked at, because "leave it alone" is a decision, not an omission."""
    loop = _2d_loop()
    named = {v for v in VERDICTS if f'_verdict == "{v}"' in loop}
    assert named == {"failed", "silent"}, f"verdict gates drifted: {named}"


def test_the_silent_case_is_diagnosed_and_never_clicked():
    """The plain-chat stall: no plan, no error, nothing moving. It gets a
    read-only log line and the card, because there is nothing to click."""
    loop = _2d_loop()
    i_silent = loop.index('_verdict == "silent"')
    tail = loop[i_silent:]
    assert "_logged_stall_diag = True" in tail
    assert "_gemini_redraft_plan(" not in tail
