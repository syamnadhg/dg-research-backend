"""Notification reliability and serve stability (2026-08-16).

The owner's second end-to-end run reported three things: phase notifications
that never arrived, a device flickering offline/online several times per app
open, and a foreground `--serve` that exited on its own. This file covers the
backend half of the repair wave.

⭐ THE OBSERVATION THAT ORGANISES ALL OF IT. Everything the owner RECEIVED
arrived with the web app in the foreground; everything MISSING was sent while it
was closed. The backend's part of that is the ask it makes on the owner's behalf
— and until now that ask could report success for a call that delivered nothing,
could be lost to a single network blip, and ran inside a process that would
`os._exit` itself out from under the run.
"""
import ast
import inspect

import pytest

import research


# ── FIX 8: a log line that cannot overstate what happened ───────────────────
#
# The caller printed "delivered ✓" for any HTTP 200, then the first 120
# characters of the body. The body was the list of dedup keys the route had
# BUILT. So a call that decided every channel was off, reached zero devices and
# sent zero mail printed a tick and a list of things that had not happened.
#
# That log line is the ONLY view anyone has of this path — it runs with the app
# closed by definition — and it is what sent the investigation to the wrong
# place when the owner reported the notices missing.


def test_a_reply_with_no_delivery_reports_none():
    out = research._summarize_notify_reply('{"ok": true, "delivered": []}')
    assert "no notices earned" in out


def test_it_reports_the_channels_and_the_counts():
    out = research._summarize_notify_reply(
        '{"ok": true, "delivered": [{"dedupKey": "briefReady-r1", "pushed": 2, '
        '"emailed": false, "channels": {"inApp": true, "push": true, "email": false}}]}'
    )
    assert "briefReady-r1" in out
    assert "pushed=2" in out
    assert "emailed=False" in out or "emailed=false" in out
    assert "inApp,push" in out


def test_a_notice_that_reached_nobody_reads_as_zero():
    """⭐ THE POINT. The old line said 'delivered ✓' here."""
    out = research._summarize_notify_reply(
        '{"ok": true, "delivered": [{"dedupKey": "k", "pushed": 0, "emailed": false, '
        '"channels": {"inApp": false, "push": false, "email": false}}]}'
    )
    assert "pushed=0" in out
    assert "channels=none" in out
    assert "✓" not in out


def test_every_notice_is_reported_separately():
    """Phase 3 earns two and they fail independently — each carries its own
    dedup marker precisely so they can. One shared verdict would hide it."""
    out = research._summarize_notify_reply(
        '{"delivered": ['
        '{"dedupKey": "notebookReady-r1", "pushed": 1, "emailed": false, "channels": {"push": true}},'
        '{"dedupKey": "podcastReady-r1", "pushed": 0, "emailed": false, "channels": {"push": true}}]}'
    )
    assert "notebookReady-r1 pushed=1" in out
    assert "podcastReady-r1 pushed=0" in out


@pytest.mark.parametrize("body", ["", "not json", "null", "[]", '{"ok": true}'])
def test_an_answer_it_cannot_read_is_never_reported_as_success(body):
    """⛔ The over-correction guard. A parser that fell back to a cheerful
    default would put the original defect straight back — a 200 with a body
    this side does not understand is exactly the shape a changed route would
    produce, and that is the moment the log must stop claiming delivery."""
    out = research._summarize_notify_reply(body)
    assert "✓" not in out
    assert "pushed=" not in out
    assert ("unparsed" in out) or ("no delivery detail" in out)


def test_the_caller_prints_the_summary_and_not_a_tick():
    """The consumer side. A correct summariser nobody calls changes nothing,
    and the string it replaced is the one that lied."""
    src = inspect.getsource(research._post_fe_phase_notice)
    assert "_summarize_notify_reply(" in src
    at = src.index("if _resp.status_code == 200:")
    ok_branch = src[at:at + 300]
    assert "delivered ✓" not in ok_branch, (
        "a 200 must not be logged as delivery — that is the defect"
    )


# ── FIX 12: the ask is retried ──────────────────────────────────────────────
#
# ⭐ It is a single fire-and-forget POST with NO replay path behind it. The web
# app's own notifier cannot cover the gap — needing an open tab is the entire
# reason this call exists — and the inbox reconcile only covers a run's
# COMPLETION, not the artifacts a phase produced on the way. One blip on one
# request was that phase's notice gone for good.


def _ask_src():
    return inspect.getsource(research._post_fe_phase_notice)


def test_the_ask_is_retried():
    src = _ask_src()
    assert "for _attempt in range(1, 4)" in src, (
        "one network blip must not cost a phase its notification"
    )


def test_it_backs_off_between_attempts():
    """Three immediate retries against a web app that is restarting is a
    hammer, not a retry."""
    src = _ask_src()
    at = src.index("for _attempt in range(1, 4)")
    body = src[at:]
    assert "time.sleep(" in body
    assert "_delay = 2 * _attempt" in body


def test_a_4xx_is_not_retried():
    """⛔ THE POLARITY. A 4xx means the request was refused on its merits — an
    unauthorised device, a malformed body, an event this side named that the
    web app could not match. Repeating it changes nothing except the load, and
    a device looping on a 403 is exactly what the route's limiter is for."""
    src = _ask_src()
    assert "if _resp.status_code < 500:" in src
    at = src.index("if _resp.status_code < 500:")
    assert "return" in src[at:at + 250]


def test_a_success_stops_immediately():
    """⛔ The over-correction: a loop that retried a 200 would deliver the same
    notice three times. The dedup marker would collapse push and email, but the
    two extra round trips are real and the log would be a lie."""
    src = _ask_src()
    at = src.index("if _resp.status_code == 200:")
    assert "return" in src[at:at + 220]


def test_it_gives_up_rather_than_looping_forever():
    src = _ask_src()
    assert "gave up after 3 attempts" in src


# ── FIX 5b: not exiting on top of a handoff ─────────────────────────────────


def test_the_notice_thread_is_counted_as_in_flight():
    """⭐ For the WHOLE retry sequence, not per attempt: a respawn landing in
    the backoff between two attempts kills the notice just as dead."""
    src = _ask_src()
    assert "_fe_handoff_begin()" in src
    at = src.index("_fe_handoff_begin()")
    after = src[at:at + 260]
    assert "finally:" in after and "_fe_handoff_end()" in after


def test_the_p4p5_drive_is_counted_as_a_DRIVE():
    """⭐⭐ Not a brief handoff. That request is the rest of the run, and the
    route aborts it when the client goes away — SIGTERMing ffmpeg and writing
    status="stopped". A 90-second bound would land mid-encode."""
    src = inspect.getsource(research._post_fe_p4p5_trigger)
    assert "_fe_handoff_begin(drive=True)" in src
    at = src.index("_fe_handoff_begin(drive=True)")
    after = src[at:at + 260]
    assert "finally:" in after and "_fe_handoff_end(drive=True)" in after


def test_the_two_budgets_differ_by_orders_of_magnitude():
    assert research._FE_HANDOFF_WAIT_SEC <= 300
    assert research._FE_DRIVE_WAIT_SEC >= 1800


def test_the_budget_follows_what_is_actually_in_flight():
    assert research._fe_handoff_pending() == 0
    assert research._fe_respawn_wait_budget() == research._FE_HANDOFF_WAIT_SEC
    research._fe_handoff_begin(drive=True)
    try:
        assert research._fe_handoff_pending() == 1
        assert research._fe_respawn_wait_budget() == research._FE_DRIVE_WAIT_SEC
    finally:
        research._fe_handoff_end(drive=True)
    assert research._fe_handoff_pending() == 0
    assert research._fe_respawn_wait_budget() == research._FE_HANDOFF_WAIT_SEC


def test_a_brief_handoff_uses_the_short_budget_even_beside_nothing_else():
    research._fe_handoff_begin()
    try:
        assert research._fe_handoff_pending() == 1
        assert research._fe_respawn_wait_budget() == research._FE_HANDOFF_WAIT_SEC
    finally:
        research._fe_handoff_end()
    assert research._fe_handoff_pending() == 0


def test_the_counter_never_goes_negative():
    """A stray end() — a double finally, a refactor — must not push the count
    below zero and make a genuine handoff invisible."""
    research._fe_handoff_end()
    research._fe_handoff_end(drive=True)
    assert research._fe_handoff_pending() == 0


# ⭐⭐ The gate itself is a PURE FUNCTION, and these tests execute it.
#
# ⛔ The first version of these tests asserted that `_fe_handoff_pending()` and
# "respawning anyway" appeared in the loop's source. Mutation killed that idea:
# replacing the entry condition with `False`, and dropping the deadline from the
# poll condition, both left every identifier exactly where it was and both tests
# green. The loop never returns, so nothing could execute it — which is the same
# shape of gap that let three defects ship in the phase-notice hook.

NOW = 1_755_800_000.0
BUDGET = 90


def _hold(pending=1, wait_until=None, now=NOW, budget=BUDGET, supervised=True):
    return research._decide_respawn_hold(pending, wait_until, now, budget, supervised)


def test_nothing_in_flight_goes_straight_through():
    assert _hold(pending=0) == ("go", None)


def test_something_in_flight_holds_and_sets_a_deadline():
    """⭐ The respawn would land on top of a POST that hands this run to the web
    app, and killing the P4/P5 one aborts the request, SIGTERMs ffmpeg and
    terminalises the research as stopped."""
    action, until = _hold()
    assert action == "hold"
    assert until == NOW + BUDGET


def test_the_hold_persists_while_the_work_does():
    assert _hold(wait_until=NOW + 10) == ("hold", NOW + 10)


def test_the_deadline_does_not_restart_on_each_poll():
    """Otherwise a handoff that keeps looking busy holds for ever, which is the
    unbounded case reached by another road."""
    _, until = _hold(wait_until=NOW + 10)
    assert until == NOW + 10


def test_the_hold_ends_the_moment_the_work_does():
    assert _hold(pending=0, wait_until=NOW + 10) == ("go", None)


def test_the_wait_is_BOUNDED():
    """⛔⛔ One wedged thread must not leave this worker permanently deaf —
    which is the exact condition the respawn exists to clear."""
    assert _hold(wait_until=NOW - 1) == ("go_late", None)
    assert _hold(wait_until=NOW) == ("go_late", None)


def test_only_a_SUPERVISED_recovery_ever_waits():
    """⭐ A foreground serve re-binds in place. That swaps two Firestore watches
    and touches no outbound request, so there is nothing to wait for and
    deferring it would delay the recovery for no reason."""
    assert _hold(supervised=False) == ("go", None)


def test_the_loop_actually_consults_it():
    """A correct gate nobody calls changes nothing."""
    src = inspect.getsource(research._firebase_reconnect_loop)
    assert "_decide_respawn_hold(" in src
    assert 'if _action == "hold":' in src
    assert 'if _action == "go_late":' in src
    assert "respawning anyway" in src


def test_the_supervisor_probe_is_not_re_run_on_every_poll():
    """It shells out to `ps`, and this branch is re-entered every two seconds
    while holding — for up to an hour when a P4/P5 drive is in flight."""
    src = inspect.getsource(research._firebase_reconnect_loop)
    assert "False if _was_waiting else _supervisor_is_my_parent()" in src


# ── FIX 5a: a foreground serve must not exit itself ─────────────────────────


def test_the_supervisor_probe_asks_about_the_PARENT():
    """⛔⛔ THE DEFECT IN THE OLD PROBE. Every existing check enumerates every
    research.py on the machine and asks whether ANY of them is a daemon-loop —
    a machine-wide question. On a laptop running the supervised fleet AND a
    foreground --serve at once, which is the owner's own setup, that is true for
    the foreground session too, and acting on it os._exit()s the very session it
    was meant to protect. Nothing then restarts it."""
    src = inspect.getsource(research._supervisor_is_my_parent)
    assert "os.getppid()" in src
    assert 'role == "daemon-loop"' in src
    assert "pid == ppid" in src


def test_a_reparented_process_is_not_supervised():
    """ppid 1 is init/launchd after the real parent died — the one case where a
    supervisor definitely is NOT coming back for us."""
    src = inspect.getsource(research._supervisor_is_my_parent)
    assert "ppid <= 1" in src


def test_a_failed_probe_assumes_FOREGROUND():
    """⛔ The direction matters. Guessing 'supervised' costs an unrecoverable
    exit; guessing 'foreground' costs a stale listener that logs loudly. Only
    one of those is survivable."""
    src = inspect.getsource(research._supervisor_is_my_parent)
    at = src.index("except Exception as _e:")
    assert "return False" in src[at:] or src.rstrip().endswith("return False")
    assert "assuming foreground" in src


def test_the_probe_answers_for_this_process_without_raising():
    """It runs on every reconnect. A probe that can throw would take the
    recovery down with it."""
    assert research._supervisor_is_my_parent() in (True, False)


def test_supervised_still_respawns():
    """⛔ The over-correction. Under a daemon-loop the exit is still right: it
    is cheap, deterministic, and the supervisor brings us straight back."""
    src = inspect.getsource(research._recover_after_reconnect)
    assert "_schedule_server_exit(" in src
    at = src.index("_schedule_server_exit(")
    assert "_supervisor_is_my_parent()" in src[:at]


def test_foreground_rebinds_in_place_instead():
    src = inspect.getsource(research._recover_after_reconnect)
    assert "_watch_rebinder" in src
    assert "asyncio.to_thread(_watch_rebinder)" in src, (
        "⛔ unsubscribe() joins a background consumer thread — inline it would "
        "stall the event loop, heartbeat included, and the FE would report the "
        "device offline during the very recovery meant to keep it online"
    )


def test_a_failed_rebind_stays_up():
    """⛔⛔ Exiting here would reintroduce the exact defect this function exists
    to remove, on the rarer path where it is hardest to reproduce."""
    src = inspect.getsource(research._recover_after_reconnect)
    at = src.index("except Exception as _e:")
    tail = src[at:]
    assert "staying up" in tail
    assert "_schedule_server_exit" not in tail
    assert "os._exit" not in tail


def test_a_missing_rebinder_is_not_fatal_either():
    src = inspect.getsource(research._recover_after_reconnect)
    at = src.index("if _watch_rebinder is None:")
    branch = src[at:at + 400]
    assert "return" in branch
    assert "os._exit" not in branch


def test_the_rebind_nulls_the_handles_between_drop_and_reattach():
    """A failure part way through must not leave a handle to a stream that is
    already dead — shutdown would unsubscribe it a second time."""
    src = inspect.getsource(research._rebind_firestore_watches)
    drop = src.index("_start_listener = None")
    attach = src.index("start_firestore_start_listener(")
    assert drop < attach


def test_the_rebind_reattaches_BOTH_watches():
    """⛔ Re-binding one and not the other is 'online but deaf' with a
    reassuring log line — the failure this whole path exists to clear.

    ⚠ Mutation found the first version of this test: asserting that both calls
    APPEAR left `if False:` above the second one perfectly green. The guard is
    pinned as well as the call, because the call being present is not the
    claim — the call being reachable is."""
    src = inspect.getsource(research._rebind_firestore_watches)
    assert "start_firestore_start_listener(" in src
    assert "_start_device_command_listener(" in src
    at = src.index("_start_device_command_listener(")
    guard = src[:at].rsplit("\n", 2)[-2].strip()
    assert guard == "if uid and device_id:", (
        f"the device-command watch must be re-attached whenever there is an "
        f"identity to attach it for, not behind {guard!r}"
    )
    assert "if False" not in src


def test_an_unsubscribe_that_raises_does_not_abort_the_rebind():
    """A stream already torn down by the outage raises here, and that is the
    ordinary case rather than an error — the unsubscribe exists to be sure, not
    to be the first to notice."""
    src = inspect.getsource(research._rebind_firestore_watches)
    at = src.index("handle.unsubscribe()")
    after = src[at:at + 300]
    assert "except Exception" in after


def test_the_rebinder_is_registered_at_boot():
    """⭐ The reconnect loop cannot build this itself: the job queue, the event
    loop and the paired identity are all locals of the boot path — which is
    exactly why the old recovery was a whole-process respawn."""
    src = inspect.getsource(research)
    assert "_watch_rebinder = lambda: _rebind_firestore_watches(" in src
