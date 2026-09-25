"""The approval poll's backoff ladder — and why it is a ladder, not a cap.

⛔ THE COST: once an ask is pending the watchdog issued one web request per tick
for the full seven-day TTL — ~10,080 for a single unanswered request, each
amplifying to roughly four Firestore ops inside a serverless handler. Rate-limit
safe, but about thirty times more than the job needs. Its sibling
`_support_log_note` was given `_BUNDLE_WATCH_SECONDS` in the same commit; this one
was given nothing, and that inconsistency is the tell.

⛔⛔ A HARD CAP WAS REJECTED, and the reason is the whole design. A wall-clock
deadline burns while the host is asleep, so an ask made Friday and approved
Saturday is NEVER announced on a laptop reopened Monday — today it is. That is a
product regression dressed as a cost fix. A ladder only ever DELAYS the notice.

⭐⭐ AND THE LADDER ITSELF WAS REPLACED (owner, 2026-09-25). It delayed an approval
forty minutes in by up to five minutes, two hours in by up to thirty, on top of the
watcher's own ~2-minute tick and Hermes's queue. Now: a STEADY check about once a
minute for the first six hours of the ask (the held topic's own lifetime — how long
a yes can still start the research), then the old half-hour tail to the seven-day
TTL, which keeps the Friday/Monday case announced. The tests below were re-aimed
from the ladder's numbers to these; the no-hard-cap guard is unchanged.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facade import bridge  # noqa: E402


def _due():
    """The bound `_device_ask_due` off a bare handler class."""
    Handler = bridge._make_handler(bridge.BridgeState.__new__(bridge.BridgeState))
    h = Handler.__new__(Handler)
    return lambda dev, asked_at: Handler._device_ask_due(h, dev, asked_at)


def _spend(due, age_seconds, ticks, minute_step=True):
    """How many of `ticks` one-minute polls actually issue a request."""
    bridge._DEVICE_ASK_CURSOR.clear()
    now = time.time()
    real = time.monotonic
    mono = [0.0]
    time.monotonic = lambda: mono[0]
    try:
        spent = 0
        for i in range(ticks):
            mono[0] = i * 60.0 if minute_step else 0.0
            if due("dev1", now - age_seconds - i * 60.0):
                spent += 1
        return spent
    finally:
        time.monotonic = real


def test_a_fresh_ask_still_polls_every_single_minute():
    """⭐⭐ THE PROMISE THE OWNER VALIDATED BY HAND: the owner approves and you are
    told, unprompted, within about a minute. The ladder must not touch the first
    ten minutes, which is when almost every approval actually lands."""
    assert _spend(_due(), age_seconds=0, ticks=10) == 10


def test_an_ask_two_hours_old_is_still_checked_every_minute():
    """⭐⭐ THE OWNER'S DECISION (2026-09-25). Under the ladder this ask was polled
    twice in ten minutes; an owner approving now waited up to half an hour to be
    announced. Inside the steady window it is checked every minute."""
    assert _spend(_due(), age_seconds=7200, ticks=10) == 10


def test_past_the_steady_window_it_settles_at_the_half_hour_tail():
    """⛔ BOUNDED: past six hours the steady check stops and the half-hour tail
    takes over — re-aimed from the ladder's "past the first hour" (2026-09-25)."""
    due = _due()
    assert _spend(due, age_seconds=7 * 3600, ticks=10) <= 2


def test_the_seven_day_worst_case_stays_in_the_hundreds_not_ten_thousand():
    """⛔ THE NUMBER THIS EXISTS FOR. The unthrottled poll spent 10,080; the ladder
    ~354; the steady-then-tail check (owner, 2026-09-25) ~684 — six hours at one a
    minute (360) plus the half-hour tail. Still a 93% cut, and the common case —
    an approval inside the first hours — is now told within a minute."""
    due = _due()
    bridge._DEVICE_ASK_CURSOR.clear()
    now = time.time()
    real = time.monotonic
    mono = [0.0]
    time.monotonic = lambda: mono[0]
    try:
        spent = 0
        for minute in range(7 * 24 * 60):
            mono[0] = minute * 60.0
            if due("dev1", now - minute * 60.0):
                spent += 1
    finally:
        time.monotonic = real
    assert spent < 800, spent
    # ⛔ AND THE STEADY WINDOW IS REALLY SPENT: every minute of the first six hours.
    assert spent >= 360, spent
    # ⛔ AND NOT ONLY THE STEADY WINDOW — a check that stopped after it would be
    # the hard cap this design rejected, and the bound above would not notice.
    assert spent > 360 + 100, spent


def test_the_age_is_the_asks_own_not_this_processs():
    """⛔ A BRIDGE RESTART MUST NOT WALK A WEEK-OLD ASK BACK TO ONE-A-MINUTE
    FOREVER. The interval is chosen from how long the ASK has been waiting, so a
    fresh cursor on an old ask spends one tick and then throttles again."""
    due = _due()
    bridge._DEVICE_ASK_CURSOR.clear()           # as if the bridge just restarted
    old = time.time() - 4 * 24 * 3600
    assert due("dev1", old) is True             # one free poll after a restart
    assert due("dev1", old) is False            # then straight back to the ladder


def test_the_news_peek_and_the_watchers_tick_spend_ONE_cursor(monkeypatch):
    """⛔⛔ (2026-09-25) The news peek checks approvals too, so a host with instant
    delivery must not pay for two checks a minute. Both go through
    `_device_ask_check_due`: a check the peek spent is not spent again by the
    watcher's own tick inside the same minute."""
    mono = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: mono[0])
    bridge._DEVICE_ASK_CURSOR.clear()
    due = _due()
    asked = time.time()
    assert bridge._device_ask_check_due("dev1", asked) is True      # the peek
    mono[0] = 20.0
    assert due("dev1", asked) is False                               # the watcher
    mono[0] = 60.0
    assert due("dev1", asked) is True


def test_a_reset_makes_the_very_next_check_due(monkeypatch):
    """⭐ The peek saw the answer and pushed; the watcher's own read must then be
    allowed to look again AT ONCE and deliver it, not wait out the minute."""
    mono = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: mono[0])
    bridge._DEVICE_ASK_CURSOR.clear()
    asked = time.time()
    assert bridge._device_ask_check_due("dev1", asked) is True
    mono[0] = 1.0
    assert bridge._device_ask_check_due("dev1", asked) is False
    bridge._device_ask_reset("dev1")
    assert bridge._device_ask_check_due("dev1", asked) is True


def test_a_one_minute_tick_that_lands_early_is_not_skipped(monkeypatch):
    """⛔ ~55 s, NOT 60 (owner, 2026-09-25). The watcher's "every minute" is the
    runtime's minute, not this process's: a tick that lands a second early against a
    60 s interval is refused, and the owner's yes waits a whole extra minute. Found
    by mutation (2026-09-25): every other test here steps exactly 60.0 s, so a 60 s
    interval passed them all."""
    mono = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: mono[0])
    bridge._DEVICE_ASK_CURSOR.clear()
    due = _due()
    asked = time.time()
    assert due("dev1", asked) is True
    mono[0] = 59.0                                   # the next tick, a second early
    assert due("dev1", asked) is True
    mono[0] = 59.0 + 30.0                            # but never twice in one minute
    assert due("dev1", asked) is False


def test_the_cursor_is_bounded():
    due = _due()
    bridge._DEVICE_ASK_CURSOR.clear()
    for i in range(120):
        due(f"dev{i}", time.time())
    assert len(bridge._DEVICE_ASK_CURSOR) <= 50


def test_the_gate_sits_below_the_scope_check():
    """⛔⛔ PLACEMENT IS LOAD-BEARING. Above the scope check, a non-matching chat's
    tick would spend the interval and starve the watchdog that actually owns the
    ask — on a host with several armed chats that is an announce delayed
    indefinitely, not by half an hour."""
    import inspect
    src = inspect.getsource(bridge._make_handler)
    note = src[src.index("def _device_access_note"):]
    note = note[:note.index("def _support_log_note")]
    assert note.index("if scope_chat:") < note.index("_device_ask_due"), (
        "the ladder must run only for the chat that owns the ask")


def test_an_ask_with_no_chat_behind_it_is_never_parked():
    """⛔ NO ORIGIN MEANS NO CHAT CAN EVER BE TOLD, so parking buys nothing but a
    week of web requests against a route nobody reads. A terminal
    `agent device ask` lands here and must behave exactly as it always did."""
    import inspect
    src = inspect.getsource(bridge._make_handler)
    ask = src[src.index("def _device_ask"):]
    ask = ask[:ask.index("def _device_pair")]
    assert "if _ask_origin:" in ask, ask[-600:]
    assert ask.index("if _ask_origin:") < ask.index("prefs.set_device_ask(")
