"""One flaky visual click must not cost a phase its entire narration.

⛔ THE REPORT (owner, mid-e2e, 2026-08-17): "ChatGPT P1 did not click the sources
line and open the source panel for rich narration and streaming data into the raw
activity panel."

⭐⭐ WHAT THE LOG SAID, and it is not what either of us assumed. Two consecutive
live P1 runs eleven hours apart met the SAME ChatGPT UI — a past-tense step
summary sitting below the last user message ("Built the research brief", then
"Clarified the research scope"), with no ellipsis, no count, and no verb the
matcher knows. The DOM rung missed it in BOTH runs, identically, at
`walked_hits=0`. So nothing regressed between the runs at all: the DOM tier has
never once matched this state, and the whole feature had quietly come to rest on a
single CUA click.

The two runs differed only in whether that one click landed:

  * run A — CUA opened it; the panel then streamed 3 URLs / 17 searches for the
    rest of the phase.
  * run B — CUA reported "the click may not have registered", and that was the
    end of it: 21 further DOM misses across ELEVEN MINUTES, no second attempt, an
    empty activity drilldown in the app, and no sources.

A visual click failing is ordinary. Betting a phase's whole narration on one of
them, while ten minutes of polling sit idle, is the defect — and the cap that
caused it was explicit in the source, on all three panel openers: "capped at
1/agent/phase".

⚠ NOT FIXED HERE, deliberately: the DOM rung still cannot match this wording. That
needs the real neighbourhood of the strip, and the diagnostic that was supposed to
provide it was spending its whole row budget on eighteen nested copies of the same
line. That is fixed too (see the snapshot tests at the bottom) so the next miss
can answer it — guessing a matcher from two text samples is how the last DOM wave
went wrong.
"""
import research


READY = dict(dom_misses=2, attempts=0, panel_open=False)


# ── the first attempt behaves exactly as it always did ──────────────────────

def test_the_first_escalation_still_lands_on_the_second_miss():
    """The retry change must not move the first attempt. Everything about the
    existing behaviour up to that point was correct."""
    assert research.panel_cua_should_escalate(**READY) is True


def test_one_miss_is_not_enough():
    assert research.panel_cua_should_escalate(**{**READY, "dom_misses": 1}) is False


def test_an_open_panel_never_escalates():
    assert research.panel_cua_should_escalate(**{**READY, "panel_open": True}) is False


def test_a_blocked_caller_never_escalates():
    """⭐ P2's completed-chip anchor and Claude's zero-artifact count mean there
    is legitimately nothing to click. A retry schedule must not be able to turn a
    phase that should stay quiet into one that keeps clicking."""
    assert research.panel_cua_should_escalate(**READY, blocked=True) is False


# ── ...and now it tries again ───────────────────────────────────────────────

def test_a_failed_first_attempt_gets_a_second_chance():
    """⭐⭐ THE FIX, in one assertion. Under the old cap this was False forever,
    which is why eleven minutes of polling produced nothing."""
    assert research.panel_cua_should_escalate(
        dom_misses=6, attempts=1, panel_open=False) is True


def test_and_a_third():
    assert research.panel_cua_should_escalate(
        dom_misses=14, attempts=2, panel_open=False) is True


def test_but_not_a_fourth():
    """Unbounded retries on a 30s poll would be a visual click every half minute
    for the length of the phase — cost, and a mis-click risk, with no new
    information between tries."""
    assert research.panel_cua_should_escalate(
        dom_misses=99, attempts=3, panel_open=False) is False


def test_the_retries_are_SPACED_not_immediate():
    """⛔ The retry that fires on the next poll after a failure is worth almost
    nothing: the same visual click against the same pixels a moment later. Each
    attempt has to wait for real elapsed polling, which is what the miss count
    measures."""
    # A second attempt is refused at the miss count that earned the FIRST one.
    assert research.panel_cua_should_escalate(
        dom_misses=2, attempts=1, panel_open=False) is False
    assert research.panel_cua_should_escalate(
        dom_misses=5, attempts=1, panel_open=False) is False
    # A third is refused until well past the second's threshold.
    assert research.panel_cua_should_escalate(
        dom_misses=6, attempts=2, panel_open=False) is False
    assert research.panel_cua_should_escalate(
        dom_misses=13, attempts=2, panel_open=False) is False


def test_the_thresholds_are_strictly_increasing_and_start_at_two():
    """The schedule is the whole design: three well-separated chances across a
    long phase. A flat or decreasing schedule would collapse into a burst."""
    sched = research._PANEL_CUA_RETRY_AT_MISSES
    assert sched[0] == 2, "the first attempt must not move"
    assert list(sched) == sorted(sched) and len(set(sched)) == len(sched)


def test_the_attempt_ceiling_is_DERIVED_from_the_schedule():
    """⛔ It started as `= 3` beside a 3-entry table, which made the ceiling check
    and the table-bounds check numerically identical — two guards that were each
    other's only protection, so mutation testing could kill NEITHER. Asserting
    equality here would not have caught that (they were equal); the property that
    matters is that one cannot exist without the other."""
    with open("research.py", encoding="utf-8") as fh:
        src = fh.read()
    assert "_PANEL_CUA_MAX_ATTEMPTS = len(_PANEL_CUA_RETRY_AT_MISSES)" in src, (
        "the ceiling must be derived, or the two can drift apart and one of them "
        "becomes untestable dead weight"
    )
    assert research._PANEL_CUA_MAX_ATTEMPTS == len(research._PANEL_CUA_RETRY_AT_MISSES)


def test_the_schedule_fits_inside_a_real_phase():
    """At a 30s poll the last attempt has to happen while the phase is still
    running — a third chance that arrives after the response completes is not a
    chance. The observed P1 runs were 11-12 minutes."""
    assert research._PANEL_CUA_RETRY_AT_MISSES[-1] * 30 <= 9 * 60


def test_a_run_of_misses_yields_exactly_the_capped_number_of_attempts():
    """End to end over a simulated phase: 25 polls, every one a DOM miss."""
    attempts = 0
    fired_at = []
    for miss in range(1, 26):
        if research.panel_cua_should_escalate(
                dom_misses=miss, attempts=attempts, panel_open=False):
            attempts += 1
            fired_at.append(miss)
    assert attempts == research._PANEL_CUA_MAX_ATTEMPTS
    assert fired_at == list(research._PANEL_CUA_RETRY_AT_MISSES)


def test_a_panel_that_opens_midway_stops_the_schedule():
    """The common good case: attempt 1 works. Nothing further may fire."""
    attempts = 0
    opened = False
    for miss in range(1, 26):
        if research.panel_cua_should_escalate(
                dom_misses=miss, attempts=attempts, panel_open=opened):
            attempts += 1
            opened = True                      # this attempt succeeded
    assert attempts == 1


# ── all three openers are actually wired to it ─────────────────────────────

def _src():
    with open("research.py", encoding="utf-8") as fh:
        return fh.read()


def test_every_panel_opener_uses_the_shared_schedule():
    """⭐ Three call sites carried the same one-shot bug with three different
    variable names. Pinning the helper proves nothing about any of them."""
    src = _src()
    assert src.count("panel_cua_should_escalate(") == 4, (
        "one definition plus exactly three call sites: P1 ChatGPT, P2 ChatGPT, "
        "P2 Claude"
    )


def test_no_opener_still_carries_a_one_shot_cap():
    """⛔ The exact expression that caused this. Any of the three reverting to it
    silently restores 'one flaky click loses the phase'."""
    src = _src()
    for name in ("_panel_cua_attempts",
                 "chatgpt_panel_cua_attempts",
                 "claude_artifact_cua_attempts"):
        assert f"{name} == 0" not in src, f"{name} is capped at one attempt again"
        assert f'{name}", 0) == 0' not in src, f"{name} is capped at one attempt again"


def test_every_opener_increments_rather_than_assigns():
    """`= 1` cannot count past one, so the schedule would hand out attempt 1
    forever and the retry would be infinite instead of bounded."""
    src = _src()
    assert "_panel_cua_attempts += 1" in src
    assert 'p["chatgpt_panel_cua_attempts"] = p.get("chatgpt_panel_cua_attempts", 0) + 1' in src
    assert 'p["claude_artifact_cua_attempts"] = p.get("claude_artifact_cua_attempts", 0) + 1' in src


def test_the_claude_artifact_count_stays_behind_the_cheap_check():
    """It is an await on every poll cycle. Ordering it first would pay for a DOM
    query on every quiet cycle of every P2 run."""
    src = _src()
    at = src.index("op=\"open_artifact_1\"")
    region = src[at - 1200:at]
    sched = region.index("panel_cua_should_escalate(")
    count = region.index("_count_claude_artifacts(")
    assert sched < count, "the pure schedule check must short-circuit the await"


# ── the diagnostic that has to answer the DOM question next time ────────────

def test_the_snapshot_dedupes_by_text():
    """⛔ Both captured misses returned eighteen rows of the SAME text, because a
    strip line is a stack of nested wrappers all reporting identical innerText.
    The budget described one line eighteen times and never once showed what sits
    NEXT to it — which is precisely what a wording-free matcher must be built
    from."""
    src = _src()
    at = src.index("async def _log_chatgpt_thread_snapshot")
    body = src[at:at + 5000]
    assert "seen" in body and "dupes" in body
    assert "seen.has(key)" in body


def test_the_snapshot_looks_for_a_shimmer_on_DESCENDANTS_too():
    """⭐ The vision tier described the line as shimmering while the snapshot
    reported anim:false — because the animated gradient lives on an inner span
    and the check only ever asked the element itself. If `animKid` turns out to
    be the reliable signal, "the shimmering line below the last user message"
    becomes the structural anchor that wording never was."""
    src = _src()
    at = src.index("async def _log_chatgpt_thread_snapshot")
    body = src[at:at + 5000]
    assert "animKid" in body
    assert "el.querySelectorAll('*')" in body


def test_the_snapshot_reports_a_class_hook():
    src = _src()
    at = src.index("async def _log_chatgpt_thread_snapshot")
    body = src[at:at + 5000]
    assert "cl:" in body


def test_the_snapshot_line_is_not_truncated_before_the_neighbours():
    """The dedupe moves the interesting rows to the TAIL of the line, which the
    old 1800-char cut discarded."""
    src = _src()
    at = src.index("async def _log_chatgpt_thread_snapshot")
    body = src[at:at + 6000]
    assert "line[:3500]" in body
