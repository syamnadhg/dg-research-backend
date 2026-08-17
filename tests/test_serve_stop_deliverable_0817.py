"""Ctrl+C has to be able to ARRIVE, not just be handled once it does.

⛔ THE REPORT (owner, 2026-08-17). A serve that had been up ninety seconds and
had run nothing was sent three Ctrl+C presses. The terminal echoed all three.
The log recorded NOTHING — no `stop requested`, no second-press line, and no
`was no longer ours` drift line either. The same process then went on to claim a
job and run it normally a minute later, so nothing was wedged and nothing had
died: the handler simply never ran. The owner had to stop the server from the web
app instead.

⭐⭐ WHAT THAT RULES OUT, and it is most of the field. The 08-11 wave already
re-asserts both handlers every few seconds, unconditionally, and announces the
first drift it finds. Twelve of those passes had run before the first press. So
either the disposition was fine and the signal never arrived, or it arrived and
could not be delivered. Both are invisible to a loop that only asserts WHO the
handler is.

⭐ THE MECHANISM THIS FILE CLOSES. A blocked signal is not discarded — it is held
PENDING indefinitely. While SIGINT is blocked, `getsignal` still reports our
handler, `signal.signal` still succeeds, and every re-assert pass still reports
success, while the press goes unheard. It is byte-for-byte the same observable as
the disposition reset the last wave chased: no line, no shutdown, a healthy
process afterwards. Re-installing a handler cannot repair it, which is why no
amount of tuning the old loop would ever have helped.

Unblocking a signal that is already pending delivers it immediately, so a press
that was swallowed still stops the server — one re-assert period late rather than
never.

⚠ HONESTY: that this is what happened to the owner is NOT measured. Their process
was gone before it could be probed, and the last time this class was investigated
the pending and blocked masks were both read as empty. What IS established is
that this is the one mechanism the existing loop structurally cannot repair, and
that either way the WARN below now names the truth the next time.
"""
import asyncio
import signal

import pytest

import research


# ── harness ─────────────────────────────────────────────────────────────────

BOTH = (signal.SIGINT, signal.SIGTERM)


class _MaskSig:
    """Stand-in for the `signal` module with a controllable process mask.

    `pthread_sigmask(SIG_BLOCK, [])` is the documented way to READ the mask
    without changing it, so that call must return the current set and record
    nothing.
    """

    SIG_BLOCK = signal.SIG_BLOCK
    SIG_UNBLOCK = signal.SIG_UNBLOCK
    SIG_IGN = signal.SIG_IGN
    SIG_DFL = signal.SIG_DFL
    default_int_handler = signal.default_int_handler
    Signals = signal.Signals

    def __init__(self, blocked=(), pending=(), mask_raises=False,
                 unblock_raises=False, pending_raises=False, current=None):
        self.blocked = set(blocked)
        self.pending = set(pending)
        self._mask_raises = mask_raises
        self._unblock_raises = unblock_raises
        self._pending_raises = pending_raises
        self._current = current
        self.unblocked = []                 # [tuple(signums)] per SIG_UNBLOCK
        self.installed = []                 # [(signum, handler)]

    # -- the parts under test --
    def pthread_sigmask(self, how, sigs):
        if self._mask_raises:
            raise AttributeError("no pthread_sigmask on this platform")
        if how == signal.SIG_BLOCK and not list(sigs):
            return set(self.blocked)        # a read, not a write
        if how == signal.SIG_UNBLOCK:
            if self._unblock_raises:
                raise OSError("mask write refused")
            self.unblocked.append(tuple(sigs))
            self.blocked -= set(sigs)
            return set(self.blocked)
        raise AssertionError(f"unexpected mask write: {how} {sigs}")

    def sigpending(self):
        if self._pending_raises:
            raise OSError("sigpending unavailable")
        return set(self.pending)

    # -- the parts the handler install needs --
    def getsignal(self, signum):
        return self._current

    def signal(self, signum, handler):
        self.installed.append((signum, handler))
        return self._current


class _FakeServer:
    def __init__(self):
        self.started = True
        self.should_exit = False
        self.force_exit = True              # any backstop thread stands down


@pytest.fixture
def logged(monkeypatch):
    out = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": out.append((level, msg)))
    return out


def _warns(logged):
    return [m for lvl, m in logged if lvl == "WARN"]


# ── a blocked stop signal is freed ──────────────────────────────────────────

def test_a_blocked_stop_signal_is_unblocked(logged):
    """⭐⭐ THE FIX. Nothing else in the stop path can do this: the handler was
    always installed and always correct."""
    sig = _MaskSig(blocked=BOTH)

    freed = research._unblock_stop_signals(sig, BOTH, set())

    assert freed == ["SIGINT", "SIGTERM"]
    assert sig.unblocked == [(signal.SIGINT, signal.SIGTERM)]
    assert not sig.blocked


def test_an_unblocked_signal_is_left_completely_alone(logged):
    """The healthy path must not touch the process mask at all — this runs every
    few seconds for the life of the server."""
    sig = _MaskSig(blocked=())

    assert research._unblock_stop_signals(sig, BOTH, set()) == []
    assert sig.unblocked == []
    assert _warns(logged) == []


def test_only_the_stop_signals_are_freed(logged):
    """⛔ Unblocking the whole mask would hand the process every signal somebody
    else deliberately deferred — a stop fix has no business doing that."""
    sig = _MaskSig(blocked=(signal.SIGINT, signal.SIGUSR1, signal.SIGCHLD))

    research._unblock_stop_signals(sig, BOTH, set())

    assert sig.unblocked == [(signal.SIGINT,)]
    assert signal.SIGUSR1 in sig.blocked and signal.SIGCHLD in sig.blocked


def test_one_blocked_signal_does_not_drag_the_other_along(logged):
    sig = _MaskSig(blocked=(signal.SIGTERM,))
    assert research._unblock_stop_signals(sig, BOTH, set()) == ["SIGTERM"]
    assert sig.unblocked == [(signal.SIGTERM,)]


# ── the line that names this class ──────────────────────────────────────────

def test_being_blocked_is_a_WARN_that_names_the_signal(logged):
    """A whisper is why the previous incarnation of this failure survived three
    attempts. There was never a line to find."""
    research._unblock_stop_signals(_MaskSig(blocked=(signal.SIGINT,)), BOTH, set())

    warns = _warns(logged)
    assert len(warns) == 1
    assert "SIGINT" in warns[0] and "BLOCKED" in warns[0]


def test_a_press_that_was_already_swallowed_is_reported_as_such(logged):
    """⭐ Blocked, and blocked WITH something pending, are different facts. The
    second one is proof a human pressed Ctrl+C and was not heard — that sentence
    is what turns this from a theory into a measurement."""
    research._unblock_stop_signals(
        _MaskSig(blocked=(signal.SIGINT,), pending=(signal.SIGINT,)), BOTH, set())

    assert "already pending" in _warns(logged)[0]


def test_a_blocked_signal_with_nothing_pending_does_not_claim_a_press(logged):
    """Saying a stop had been pressed when none had would send the next reader
    hunting for a keypress that never happened."""
    research._unblock_stop_signals(
        _MaskSig(blocked=(signal.SIGINT,), pending=()), BOTH, set())

    assert "already pending" not in _warns(logged)[0]


def test_a_permanent_block_is_announced_once_not_every_pass(logged):
    """This runs every few seconds forever."""
    sig, reported = _MaskSig(blocked=BOTH), set()
    for _ in range(5):
        sig.blocked = set(BOTH)             # the culprit keeps re-blocking it
        research._unblock_stop_signals(sig, BOTH, reported)

    assert len(_warns(logged)) == 2, _warns(logged)
    assert len(sig.unblocked) == 5, "quiet after the first line, but still repairing"


# ── it must never be the thing that stops the server starting ───────────────

def test_a_platform_with_no_signal_mask_is_not_an_error(logged):
    """Windows has no pthread_sigmask. Raising here would take the whole serve
    down on a platform this bug cannot occur on."""
    assert research._unblock_stop_signals(_MaskSig(mask_raises=True), BOTH, set()) == []
    assert _warns(logged) == []


def test_a_refused_mask_write_is_reported_and_survived(logged):
    sig = _MaskSig(blocked=(signal.SIGINT,), unblock_raises=True)

    assert research._unblock_stop_signals(sig, BOTH, set()) == ["SIGINT"]

    assert any("could not unblock" in m for m in _warns(logged)), _warns(logged)


def test_pending_being_unreadable_does_not_stop_the_unblock(logged):
    """The pending set is for the LINE. Losing it must not cost the repair."""
    sig = _MaskSig(blocked=(signal.SIGINT,), pending_raises=True)

    assert research._unblock_stop_signals(sig, BOTH, set()) == ["SIGINT"]
    assert sig.unblocked == [(signal.SIGINT,)]


def test_reading_the_mask_does_not_write_it(logged):
    """`pthread_sigmask(SIG_BLOCK, [])` is a read. Passing the signums there
    instead would BLOCK the very signals this function exists to free — a
    one-word slip that inverts the whole fix."""
    sig = _MaskSig(blocked=())

    research._unblock_stop_signals(sig, BOTH, set())

    assert sig.blocked == set(), "the mask must be unchanged by a healthy pass"


# ── both properties, in the order that matters ──────────────────────────────

def test_one_pass_both_installs_the_handler_and_frees_the_signal(logged):
    def handler(signum, frame): ...
    sig = _MaskSig(blocked=BOTH, current=handler)

    installed, freed = research._hold_stop_signals(sig, BOTH, handler, set())

    assert installed == ["SIGINT", "SIGTERM"]
    assert freed == ["SIGINT", "SIGTERM"]


def test_the_handler_is_installed_BEFORE_the_signal_is_unblocked(logged):
    """⛔⛔ THE ORDER IS LOAD-BEARING. Unblocking first delivers a pending signal
    to whatever the disposition had drifted to — and if that is SIG_DFL, the
    process is killed outright instead of shutting down cleanly. Which is to say:
    getting this backwards turns the fix for a swallowed Ctrl+C into an
    ungraceful kill of a healthy server."""
    order = []

    class _Ordered(_MaskSig):
        def signal(self, signum, handler):
            order.append(("install", signum))
            return super().signal(signum, handler)

        def pthread_sigmask(self, how, sigs):
            if how == signal.SIG_UNBLOCK:
                order.append(("unblock", tuple(sigs)))
            return super().pthread_sigmask(how, sigs)

    def handler(signum, frame): ...
    research._hold_stop_signals(_Ordered(blocked=BOTH, current=handler), BOTH,
                               handler, set())

    kinds = [k for k, _ in order]
    assert kinds.index("install") < kinds.index("unblock"), order


# ── and it is actually reached from the loop that holds the stop path ───────

class _Enough(Exception):
    """Ends the deliberately endless re-assert loop."""


def _drive_arming(monkeypatch, *, sleeps, freed=("SIGINT",)):
    """Run `_arm_stop_signals` for `sleeps` iterations of its hold loop.

    ⛔⛔ THE LOOP IS ENDED FROM `asyncio.sleep`, NOT FROM THE SPY, and that is
    not a style choice. A spy that raises only works while the code still calls
    the spied function: point the loop at something else and the exception never
    comes, `_STOP_REARM_S` is 0, and the test spins forever. A test that HANGS
    instead of failing is not a test — it took a mutation run with a twelve-minute
    stuck pytest to notice, because the mutant that redirects this very call is
    the first one in the harness. Every pass awaits the sleep no matter what the
    body calls, so counting sleeps terminates unconditionally.

    Returns the recorded passes (empty if the loop never called the helper).
    """
    passes = []

    def _spy(sig_mod, signums, handler, reported, announce=True):
        passes.append({"announce": announce, "signums": tuple(signums),
                       "handler": handler})
        return ["SIGINT", "SIGTERM"], list(freed)

    async def _no_sleep(_secs):
        _no_sleep.n += 1
        if _no_sleep.n >= sleeps:
            raise _Enough
    _no_sleep.n = 0

    monkeypatch.setattr(research, "_hold_stop_signals", _spy)
    monkeypatch.setattr(research, "_STOP_REARM_S", 0)
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    with pytest.raises(_Enough):
        asyncio.run(research._arm_stop_signals(_FakeServer(), 8000))
    return passes


def test_the_arming_loop_holds_BOTH_properties_every_pass(monkeypatch, logged):
    """⭐ Pinning the helper proves nothing about the server. Before this, the
    loop re-asserted the handler and never once looked at the mask — so the
    helper above could be perfect and unreachable."""
    passes = _drive_arming(monkeypatch, sleeps=3)

    assert len(passes) == 3, "arm time plus two loop passes"
    assert passes[0]["signums"] == BOTH
    assert passes[0]["announce"] is False, "the first pass is not drift"
    assert all(p["announce"] is True for p in passes[1:])


def test_every_pass_holds_the_SAME_handler_object(monkeypatch, logged):
    """Carried over from the 08-11 wave, because the refactor moved the call:
    rebuilding the handler per pass hands each one a fresh press counter and
    silently disables the second Ctrl+C."""
    passes = _drive_arming(monkeypatch, sleeps=4)
    assert len({id(p["handler"]) for p in passes}) == 1


def test_a_signal_freed_at_arm_time_is_announced_at_startup(monkeypatch, logged):
    """Blocked before the server ever got here is the worst case — it would be
    blocked for the life of the process. Startup must say so out loud."""
    _drive_arming(monkeypatch, sleeps=1, freed=("SIGINT",))

    assert any("had to be unblocked at arm time" in m for m in _warns(logged)), logged


def test_a_clean_startup_says_nothing_about_the_mask(monkeypatch, logged):
    _drive_arming(monkeypatch, sleeps=1, freed=())

    assert _warns(logged) == []


# ── the platform actually behaves the way the fix assumes ───────────────────

def test_the_real_signal_module_delivers_a_pending_signal_on_unblock():
    """⭐ The load-bearing premise, asserted against the real kernel rather than
    a fake: a blocked signal is HELD, not dropped, and unblocking it delivers it
    at once. If that were not true, unblocking would repair the next press and
    silently lose the one already made.

    Uses SIGUSR1 so a failure cannot stop the test runner.
    """
    got = []
    old_handler = signal.getsignal(signal.SIGUSR1)
    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    try:
        signal.signal(signal.SIGUSR1, lambda *_a: got.append(1))
        signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGUSR1])
        import os
        os.kill(os.getpid(), signal.SIGUSR1)
        assert signal.SIGUSR1 in signal.sigpending(), "held, not dropped"
        assert got == [], "and not delivered while blocked"
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGUSR1])
        assert got == [1], "delivered the moment it was unblocked"
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        signal.signal(signal.SIGUSR1, old_handler)
