"""2026-07-19 e2e incident — two Gemini lost-send recovery gaps.

Timeline (backend.log, worker 1): send dropped platform-side (URL stayed bare
/app). Adopt-first RAN and found the exact lost conversation (sole owned
candidate, our brief title) — but its sidebar click silently never routed to
/app/<id>, the code gave up after that SINGLE click attempt, and recovery fell
through to the re-paste ladder. The ladder then re-submitted WITHOUT re-arming
Deep Research (the dropped send reverts the tool selection, and adopt's
empty-home reloads reset the composer to chat mode) — so the retried send
landed as a PLAIN CHAT message: Gemini answered the brief inline, no 'Start
research' ever appeared, 2D burned its 300s plan-wait + 3 CUA passes, and the
user had to skip the agent (0-char extraction).

Fix 1 — adopt click retries: each owned candidate gets a bounded number of
click attempts (DG_GEMINI_ADOPT_CLICK_TRIES, default 3); between failed
attempts the EMPTY HOME is reloaded (the only place reload is safe — same
policy as the Recent-list refresh) to unwedge the SPA, the rail re-expanded,
and the entry re-clicked. The pre-click URL is re-captured per attempt.

Fix 2 — the re-paste ladder re-arms DR: before every re-submit it calls
ensure_deep_mode_active (the same pre-send helper the normal path uses, which
re-runs setup_gemini_dr when the pill is off), fail-open on measurement misses.

Run:  pytest tests/test_gemini_adopt_retry_dr_rearm.py -v
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research

ADOPT_SRC = inspect.getsource(research._gemini_adopt_lost_conversation)
GEM_SRC = inspect.getsource(research.start_agent_no_gemini_wait)


# ── Fix 1: bounded click retries in the adopt candidate loop ───────────────

def test_adopt_click_is_bounded_retry_not_single_shot():
    assert "DG_GEMINI_ADOPT_CLICK_TRIES" in ADOPT_SRC
    assert "for _at in range(_click_tries):" in ADOPT_SRC
    # The candidate is only abandoned after ALL attempts fail.
    assert "never routed to a new /app/<id> after" in ADOPT_SRC


def test_adopt_click_retry_recaptures_before_url_each_attempt():
    # _before_u must be captured INSIDE the attempt loop — a reload between
    # attempts can normalize the URL, and a stale _before_u would break the
    # routed-by-CHANGE detection.
    i_loop = ADOPT_SRC.index("for _at in range(_click_tries):")
    i_before = ADOPT_SRC.index('_before_u = (page.url or "").split("?", 1)[0].rstrip("/")')
    assert i_loop < i_before, "_before_u capture must live inside the attempt loop"


def test_adopt_unwedge_reload_is_empty_home_gated():
    # The between-attempts reload must carry the same empty-home-only guard as
    # the Recent-refresh loop (never reload inside a conversation). Scope the
    # check to the attempt loop's region.
    i_loop = ADOPT_SRC.index("for _at in range(_click_tries):")
    region = ADOPT_SRC[i_loop:]
    i_guard = region.index('_cur.endswith("gemini.google.com/app")')
    i_reload = region.index("await page.reload(")
    assert i_guard < i_reload, "empty-home guard must precede the unwedge reload"


def test_adopt_reexpands_rail_after_unwedge_reload():
    # A reload collapses the rail; the entry must be re-surfaced before the
    # re-click or the click JS reports it vanished.
    i_loop = ADOPT_SRC.index("for _at in range(_click_tries):")
    region = ADOPT_SRC[i_loop:]
    assert region.index("await page.reload(") < region.index("_EXPAND_SIDEBAR_JS")


def test_adopt_vanished_entry_moves_to_next_candidate_without_retries():
    # A genuinely-gone entry (click JS returns False) is not worth re-clicking —
    # break out to the next candidate instead of burning the retry budget.
    assert "_entry_gone = True" in ADOPT_SRC
    assert "if _entry_gone:" in ADOPT_SRC


# ── Fix 2: the re-paste ladder re-arms Deep Research ───────────────────────

def _ladder_region():
    i0 = GEM_SRC.index("no lost conversation to adopt")
    i1 = GEM_SRC.index("Gemini submission confirmed ✓ (re-submit landed)")
    return GEM_SRC[i0:i1]


def test_repaste_ladder_rearms_deep_research_before_resubmit():
    ladder = _ladder_region()
    assert "ensure_deep_mode_active(page, platform, label)" in ladder, (
        "every ladder re-submit must re-arm Deep Research first — a dropped "
        "send reverts the tool and the retry lands as plain chat"
    )
    # Re-arm runs BEFORE the re-submit click (its distinctive log line — the
    # ladder header also contains the word "re-submitting", so pin the full
    # re-submit line, not the bare word).
    assert ladder.index("ensure_deep_mode_active(") \
        < ladder.index("Gemini URL still bare, no error yet — re-submitting"), (
        "DR re-arm must precede the re-submit"
    )


def test_repaste_ladder_rearm_escalates_then_parks_never_sends_silently():
    """2026-07-27: this path used to be FAIL-OPEN, justified as "2D verifies the
    plan". It does not — the 2D block has no DR predicate of any kind, it only waits
    for and clicks 'Start research'. So a measured-OFF re-submit went to chat mode
    with nothing downstream to catch it (agent-18df1b0011fc4625: DR off at 14:47:08,
    submitted 14:47:11, no plan, CUA exhausted 3 attempts, run finished 2/3).

    ⛔ 2026-08-05 — THIS TEST WAS WRONG, and its own docstring is why the defect
    survived it. It used to end: "Still never blocks the send; it just stops the run
    silently pretending to be a Deep Research." Those two clauses contradict each
    other. Sending with Deep Research MEASURED OFF *is* the run silently pretending
    to be a Deep Research: the send returns a plain chat answer and `_gemini_landed`
    accepts the resulting conversation URL as success.

    So the test asserted the escalate/re-measure/park machinery was present and then
    explicitly permitted the send anyway — encoding the bug as the contract. The
    machinery only ever changed the outcome on the FINAL attempt; attempts 1 and 2
    logged "will re-arm again" and fell through to the send.

    The contract now: re-arm → CUA setup tier → RE-MEASURE → and if it is still off,
    DO NOT SEND on this attempt. Park the non-blocking keep/skip gate once the
    attempts are spent. A measurement that RAISED is not a measurement, so it still
    permits the send — only a reading of "off" blocks it."""
    ladder = _ladder_region()
    tail = ladder[ladder.index("ensure_deep_mode_active("):]
    # The false justification must be gone.
    assert "2D verifies the plan" not in tail, (
        "the '2D verifies the plan' claim is not implemented anywhere — 2D has no DR "
        "predicate; it must not be used to justify sending with DR off"
    )
    # Escalate to the CUA setup tier…
    assert 'hotspot_id="setup-dr"' in tail, "no CUA setup escalation on the retry path"
    # …then RE-MEASURE (the CUA tier's own result is not proof — that is exactly the
    # "proceeding anyway" hole on the first-pass path).
    assert tail.count("ensure_deep_mode_active(") >= 2, (
        "DR must be re-measured after the CUA setup tier, not assumed fixed"
    )
    # …and park the SAME gate the pre-send path uses, rather than inventing one.
    assert "_park_chat_mode_decision(" in tail
    # Measurement failures still must not block the send.
    assert "DR re-arm raised (non-fatal)" in tail

    # ⭐ And the send is GATED on the measurement. This is the assertion the old
    # version of this test refused to make, which is why the fall-through lived.
    assert "_dr_ok_for_submit = False" in tail, (
        "nothing carries the 'still off' measurement out to the send gate"
    )
    assert "if not _dr_ok_for_submit:" in tail, (
        "the re-submit is not gated on the measurement — attempts before the last "
        "one will send a plain chat answer that reads as recovered research"
    )
    # The gate must sit BEFORE the re-submit, not after it.
    assert tail.index("if not _dr_ok_for_submit:") \
        < tail.index("Gemini URL still bare, no error yet — re-submitting"), (
        "the gate runs after the send, which gates nothing"
    )


def test_a_still_off_measurement_skips_the_attempt_rather_than_sending():
    """Both non-recovered branches must set the gate — the park branch on the final
    attempt AND the 'will re-arm again' branch on the earlier ones. The earlier ones
    are the whole defect: parking already existed, the fall-through did not."""
    tail = _ladder_region()
    tail = tail[tail.index("ensure_deep_mode_active("):]
    park = tail.index("_park_chat_mode_decision(")
    rearm = tail.index("will re-arm again on")
    gate = tail.index("if not _dr_ok_for_submit:")
    # One assignment after the park, one after the re-arm log, both before the gate.
    assert tail.count("_dr_ok_for_submit = False") == 2, (
        "exactly two branches measured DR as off; both must block the send"
    )
    assert park < gate and rearm < gate


def test_a_raised_measurement_still_permits_the_send():
    """⚠ Deliberate asymmetry, and it must not be 'tidied' into symmetry: a raise
    tells us nothing about Deep Research, so refusing there would park runs that are
    perfectly healthy. Only a reading of 'off' blocks."""
    tail = _ladder_region()
    exc = tail[tail.index("DR re-arm raised (non-fatal)"):]
    gate = exc[:exc.index("if not _dr_ok_for_submit:")]
    assert "_dr_ok_for_submit = False" not in gate, (
        "the except branch now blocks the send; a measurement failure is not a "
        "measurement of 'off'"
    )
    assert "_dr_ok_for_submit = True" in _ladder_region(), (
        "the gate must default to permitting the send"
    )


def test_repaste_ladder_rearm_runs_after_paste_like_normal_path():
    # Mirror the normal flow's paste → ensure → send ordering: the re-arm sits
    # after the composer re-paste block, inside the same not-in-conversation
    # branch, so all three composer branches (empty / holds / unreadable) get it.
    ladder = _ladder_region()
    assert ladder.index("re-pasting brief before re-submit") \
        < ladder.index("ensure_deep_mode_active(")


def test_adopt_gate_counts_late_route_as_routed():
    # Sub-second race (adversarial-review catch): the SPA can route AFTER the
    # inner wait's last URL read. The pre-reload gate must re-read the URL and
    # count a NEW /app/<id> as routed (the body-verify decides adoption) —
    # never abandon an already-open conversation to the re-paste ladder.
    i_loop = ADOPT_SRC.index("for _at in range(_click_tries):")
    region = ADOPT_SRC[i_loop:]
    i_late = region.index('if "/app/" in _cur and _cur != _before_u.lower():')
    i_reload = region.index("await page.reload(")
    assert i_late < i_reload, "the late-route re-check must precede the unwedge reload"
    # It marks the attempt routed instead of breaking to the next candidate.
    late_window = region[i_late:i_late + 200]
    assert "_routed = True" in late_window


def test_normal_presend_ensure_still_present():
    # The ladder re-arm supplements — must not have displaced — the two
    # pre-existing ensure calls (the normal pre-send check + the Phoenix
    # measure-only read). Pre-fix count was exactly 2, so >=3 pins that the
    # ladder call is genuinely NEW (an >=2 assertion would pass on a revert —
    # adversarial-review catch).
    assert GEM_SRC.count("ensure_deep_mode_active(") >= 3, (
        "normal pre-send + Phoenix measure-only + the ladder re-arm must all "
        "call the ensure helper"
    )
