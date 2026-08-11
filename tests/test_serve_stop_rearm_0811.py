"""Ctrl+C must KEEP working, not just work at startup.

WHAT HAPPENED (2026-08-11)

The 08-10 change armed the stop handlers once, after uvicorn began serving, and
logged on arrival so the next failure would leave evidence. It did. A serve that
had been up four hours and had finished a run was probed in both directions:

  * SIGTERM  → logged, drained, exited in ~3s. The whole stop path, intact.
  * SIGINT   → nothing. No line, no shutdown, no backstop thread (so the handler
               had not run at all), and the process was still answering HTTP on
               its port two milliseconds later.

Same handler object, installed by the same call, in the same loop, moments
apart. So the handler was never wrong — SIGINT's DISPOSITION was reset out from
under it during the run and stayed reset for the rest of the process's life.
That also rules out the terminal (the probe used kill(2) and never touched it),
delivery (unblocked, nothing pending), and uvicorn's own handler, which never
saw a stop either — the listening socket stayed open the whole time.

Nothing in this repo or in any of its Python dependencies sets SIGINT to
SIG_IGN, so the caller is native and cannot be reached from here. The fix is
therefore not to find it but to stop depending on the disposition staying put:
re-assert the handlers for the life of the server, and say what was found the
first time one has drifted — which is the line that will finally name it.

⭐ Two things in here are the whole point, and both are easy to "simplify" back
into the bug:

  1. The re-install is UNCONDITIONAL. `getsignal` reports Python's own record,
     which stays correct when the disposition is changed below it, so a
     check-then-install sees "already ours" and repairs nothing.
  2. The handler object is built ONCE and re-installed as the same object. A
     re-assert that rebuilds it hands every pass a fresh press counter, and the
     second Ctrl+C — the one that exists to escape a stalled graceful shutdown —
     never fires.
"""
import asyncio
import signal

import pytest

import research


# ── harness ─────────────────────────────────────────────────────────────────

class _FakeSig:
    """Stand-in for the `signal` module.

    `force_exit` on the fake server (below) is pre-set so the handler's backstop
    thread stands down on its first check — a test must never leave a daemon
    thread that reaches the real `_schedule_server_exit` after the test's
    monkeypatches have been undone. That call ends in `os._exit`.
    """

    SIG_IGN = signal.SIG_IGN
    SIG_DFL = signal.SIG_DFL
    default_int_handler = signal.default_int_handler
    Signals = signal.Signals

    def __init__(self, current=None, raises_for=()):
        self._current = current            # what getsignal() reports
        self._raises_for = set(raises_for)
        self.installed = []                # [(signum, handler)]

    def getsignal(self, signum):
        return self._current

    def signal(self, signum, handler):
        if signum in self._raises_for:
            raise ValueError("signal only works in main thread of the main interpreter")
        self.installed.append((signum, handler))
        return self._current


class _FakeServer:
    def __init__(self):
        self.started = True
        self.should_exit = False
        # Pre-armed so any backstop thread returns on its first check.
        self.force_exit = True


BOTH = (signal.SIGINT, signal.SIGTERM)


@pytest.fixture
def logged(monkeypatch):
    """Capture (level, message) instead of printing."""
    out = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": out.append((level, msg)))
    return out


def _warns(logged):
    return [m for lvl, m in logged if lvl == "WARN"]


# ── the install is unconditional ────────────────────────────────────────────

def test_the_handler_is_installed_even_when_python_says_it_already_is(logged):
    """⭐ THE fix. `getsignal` returns Python's RECORD of the handler, and the
    failure being fixed changes the disposition below that record — so the
    record still reads as ours while Ctrl+C is dead. A check-then-install is
    exactly correct-looking and exactly useless here."""
    def handler(signum, frame): ...
    sig = _FakeSig(current=handler)          # "already ours"

    research._assert_stop_handlers(sig, BOTH, handler, set())

    assert [s for s, _ in sig.installed] == list(BOTH), (
        "must re-install regardless of what getsignal reports"
    )
    assert _warns(logged) == [], "nothing drifted, so nothing to announce"


def test_it_reinstalls_when_the_disposition_was_reset_below_python(logged):
    """`getsignal` returns None when the disposition was set from outside
    Python — i.e. by native code — which is the exact shape of the live
    failure."""
    def handler(signum, frame): ...
    sig = _FakeSig(current=None)

    research._assert_stop_handlers(sig, BOTH, handler, set())

    assert [h for _, h in sig.installed] == [handler, handler]
    assert len(_warns(logged)) == 2


# ── the drift line has to name the culprit ──────────────────────────────────

def test_the_drift_line_says_the_signal_was_being_discarded(logged):
    """The measured live state. If the line cannot distinguish "ignored" from
    "back to default", it does not narrow the suspects and the next person
    repeats this investigation."""
    def handler(signum, frame): ...
    research._assert_stop_handlers(_FakeSig(current=signal.SIG_IGN), (signal.SIGINT,),
                                   handler, set())
    line = _warns(logged)[0]
    assert "SIG_IGN" in line and "discarded" in line, line


def test_the_drift_line_fingers_native_code_when_python_did_not_set_it(logged):
    def handler(signum, frame): ...
    research._assert_stop_handlers(_FakeSig(current=None), (signal.SIGINT,),
                                   handler, set())
    assert "native" in _warns(logged)[0]


def test_the_drift_line_names_which_signal_drifted(logged):
    """SIGINT drifted and SIGTERM did not — that asymmetry IS the finding. A
    line that omits which one erases it."""
    def handler(signum, frame): ...
    research._assert_stop_handlers(_FakeSig(current=signal.SIG_IGN), (signal.SIGINT,),
                                   handler, set())
    assert "SIGINT" in _warns(logged)[0]


def test_the_description_distinguishes_every_case():
    sig = _FakeSig()
    seen = {
        research._stop_handler_description(sig, signal.SIG_IGN),
        research._stop_handler_description(sig, signal.SIG_DFL),
        research._stop_handler_description(sig, signal.default_int_handler),
        research._stop_handler_description(sig, None),
    }
    assert len(seen) == 4, seen


# ── it must not become a log flood ──────────────────────────────────────────

def test_a_permanent_drift_is_announced_once_not_every_pass(logged):
    """This runs every few seconds forever. A drift that is never repaired by
    the culprit would otherwise print until the terminal is unusable — and an
    operator who scrolls past it learns nothing they did not already know."""
    def handler(signum, frame): ...
    sig, reported = _FakeSig(current=signal.SIG_IGN), set()
    for _ in range(5):
        research._assert_stop_handlers(sig, (signal.SIGINT,), handler, reported)

    assert len(_warns(logged)) == 1
    assert len(sig.installed) == 5, "quiet after the first line, but still repairing"


def test_the_first_install_is_not_announced_as_drift(logged):
    """At first install the handler in place is uvicorn's, by design. Calling
    that drift would print a scary WARN on every single healthy startup."""
    def handler(signum, frame): ...
    def uvicorns(signum, frame): ...

    research._assert_stop_handlers(_FakeSig(current=uvicorns), BOTH, handler,
                                   set(), announce=False)

    assert _warns(logged) == []


# ── failing to arm is loud, and survivable ──────────────────────────────────

def test_a_failure_to_arm_is_a_WARN_not_a_debug_whisper(logged):
    """⭐ The failure being a DEBUG line is why this survived three attempts —
    there was never a line to find. The level is the fix."""
    def handler(signum, frame): ...
    # `current=handler` so nothing reads as drift — this isolates the arming
    # failure, which is the only line under test here.
    research._assert_stop_handlers(_FakeSig(current=handler, raises_for=BOTH),
                                   BOTH, handler, set())

    assert len(_warns(logged)) == 2
    assert all("could not arm" in m for m in _warns(logged)), _warns(logged)
    assert not [m for lvl, m in logged if lvl == "DEBUG"]


def test_arming_failure_does_not_propagate(logged):
    """A serve that refuses to start because it could not arm a convenience is
    worse than one you stop with kill."""
    def handler(signum, frame): ...
    assert research._assert_stop_handlers(_FakeSig(raises_for=BOTH), BOTH,
                                          handler, set()) == []


def test_one_signal_failing_does_not_cost_us_the_other(logged):
    """Ctrl+C and a supervisor's SIGTERM arrive by different routes. Losing both
    because one could not be installed turns a partial failure into a total
    one."""
    def handler(signum, frame): ...
    sig = _FakeSig(raises_for=(signal.SIGINT,))

    installed = research._assert_stop_handlers(sig, BOTH, handler, set())

    assert installed == ["SIGTERM"]
    assert [s for s, _ in sig.installed] == [signal.SIGTERM]


def test_a_repeated_arming_failure_is_also_reported_once(logged):
    def handler(signum, frame): ...
    sig, reported = _FakeSig(current=handler, raises_for=BOTH), set()
    for _ in range(4):
        research._assert_stop_handlers(sig, BOTH, handler, reported)
    assert len(_warns(logged)) == 2, _warns(logged)


# ── the handlers are HELD, not installed once ───────────────────────────────

class _Enough(Exception):
    """Ends the (deliberately endless) re-assert loop from inside the spy."""


def _run_arming(monkeypatch, *, passes, on_pass=None):
    """Drive `_arm_stop_signals` for `passes` calls, then stop it.

    The period is pinned to 0 and the spy raises, so this is deterministic —
    no sleeping and no wall-clock assertions.
    """
    calls = []

    def _spy(sig_mod, signums, handler, reported, announce=True):
        calls.append({"handler": handler, "announce": announce,
                      "signums": tuple(signums)})
        if on_pass:
            on_pass(handler, len(calls))
        if len(calls) >= passes:
            raise _Enough
        return ["SIGINT", "SIGTERM"]

    monkeypatch.setattr(research, "_assert_stop_handlers", _spy)
    monkeypatch.setattr(research, "_STOP_REARM_S", 0)
    srv = _FakeServer()
    with pytest.raises(_Enough):
        asyncio.run(research._arm_stop_signals(srv, 8000))
    return calls, srv


def test_the_handlers_are_reasserted_for_the_life_of_the_server(monkeypatch, logged):
    """One install was measured to be insufficient — that is the entire bug."""
    calls, _ = _run_arming(monkeypatch, passes=4)
    assert len(calls) == 4


def test_every_reassert_reinstalls_the_SAME_handler_object(monkeypatch, logged):
    """⭐ The over-correction that would look like a tidy refactor. Rebuilding
    the handler per pass gives each one a fresh press counter, which silently
    disables the second Ctrl+C."""
    calls, _ = _run_arming(monkeypatch, passes=5)
    handlers = {id(c["handler"]) for c in calls}
    assert len(handlers) == 1, "the handler must be built once and re-installed"


def test_rearming_between_presses_does_not_reset_the_press_counter(monkeypatch, logged):
    """The behavioural consequence of the above, asserted end to end: press,
    let a re-assert land, press again — the second press must still take the
    immediate-exit branch rather than re-entering the graceful path it exists
    to escape."""
    exits = []
    monkeypatch.setattr(research, "_schedule_server_exit",
                        lambda source, delay_sec=3.0, **kw: exits.append((source, delay_sec)))
    monkeypatch.setitem(research._server_stop_signal, "n", None)

    def press_on_first_two(handler, n):
        if n in (1, 2):
            handler(signal.SIGINT, None)

    _run_arming(monkeypatch, passes=3, on_pass=press_on_first_two)

    assert exits, "a second press must schedule an exit"
    assert exits[-1][1] == 0, f"second press must not wait: {exits}"


def test_the_first_pass_is_silent_about_drift_and_later_passes_are_not(monkeypatch, logged):
    """Announcing on the first pass cries wolf on every startup; never
    announcing means the drift is invisible, which is the state this whole
    investigation started in."""
    calls, _ = _run_arming(monkeypatch, passes=3)
    assert calls[0]["announce"] is False
    assert all(c["announce"] is True for c in calls[1:])


def test_both_stop_signals_are_held(monkeypatch, logged):
    calls, _ = _run_arming(monkeypatch, passes=2)
    assert calls[0]["signums"] == (signal.SIGINT, signal.SIGTERM)


def test_the_first_press_still_asks_for_a_graceful_stop(monkeypatch, logged):
    """The refactor must not have cost the ordinary path: press one announces,
    then sets the same flag uvicorn's own handler sets."""
    monkeypatch.setitem(research._server_stop_signal, "n", None)
    seen = {}

    def press(handler, n):
        if n == 1:
            handler(signal.SIGINT, None)
            seen["logged"] = [m for _, m in logged]

    _, srv = _run_arming(monkeypatch, passes=2, on_pass=press)

    assert srv.should_exit is True
    assert any("stop requested" in m for m in seen["logged"]), seen["logged"]


def test_the_press_still_records_which_signal_arrived(monkeypatch, logged):
    """130 and 143 are different answers to anything watching the exit code."""
    monkeypatch.setitem(research._server_stop_signal, "n", None)
    _run_arming(monkeypatch, passes=2,
                on_pass=lambda h, n: h(signal.SIGTERM, None) if n == 1 else None)
    assert research._server_stop_signal["n"] == signal.SIGTERM


# ── the period ──────────────────────────────────────────────────────────────

def test_the_rearm_period_is_a_sane_length():
    """It bounds how long Ctrl+C can be dead after a drift, so it has to be
    short — and it costs two syscalls a pass, so it need not be shorter."""
    assert 1.0 <= research._STOP_REARM_S <= 30.0, research._STOP_REARM_S
    assert research._STOP_REARM_S < research._STOP_GRACE_S, (
        "a re-assert must land well inside the grace window"
    )
