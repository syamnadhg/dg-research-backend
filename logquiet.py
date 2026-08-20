"""Repeat suppression for log lines whose information content is one bit.

⛔⛔ MEASURED 2026-08-19 ON THIS MACHINE'S OWN LOGS, not reasoned about. Three
sites, one defect — a true statement restated until it destroyed the file it
was written into:

  * ``telemetry: no id-token accessor (ImportError) — batches will be anonymous``
    412 lines in a 1,367-line session log. **33.9% of its bytes.**
  * ``[aegis] worker N: ◆ standing watch``
    231 lines in the same file (9.8% of its bytes), and 2,274 / 2,754 lines in
    the last 5 MiB of the two raw machine logs.
  * ``refresh: network error … Failed to resolve 'securetoken.googleapis.com'``
    5,047 lines — 47.7% — of one ``.err`` tail, and 13,479 of 14,083 (95.7%) of
    the other.

The first two together are **43.7% of the bytes** in the session log a user
sends with ``--send-logs``. Two sentences, half the evidence.

⭐ THE FIX IS NOT SILENCE, and the distinction is the whole design. Every one of
those lines is worth having ONCE — the accessor line is the only account of a
wiring fault that made every telemetry batch anonymous, and the refresh line is
the single line that diagnosed a new owner's entire outage. What is worthless is
the 412th copy. So a suppressed repeat is not discarded: it is COUNTED, and the
count rides the next line that does get emitted. A reader learns strictly more
from ``… (+247 since the last of these)`` than from 247 identical lines, because
the number is legible at a glance and the 247 lines are not.

⛔ NOTHING FIRST-PARTY IS IMPORTED HERE, and that is load-bearing rather than
tidy. The consumers are ``telemetry.py`` — which documents that it imports
nothing from the backend so that a telemetry failure can never sit in the path
of the thing it measures — and ``auth/credentials.py``, which runs during
``--pair`` before any pipeline module exists. A stdlib-only leaf module is the
only shape both of them can take. Do not add an import to this file.
"""
from __future__ import annotations

import threading

# ── Cadences ────────────────────────────────────────────────────────────
# A cadence is a tuple of ``(until, every)`` bands, read in order: while the
# repeat index `n` is below `until`, emit every `every`-th repeat. `every <= 0`
# means the band emits nothing at all.
#
# ⛔ THE LAST BAND ALWAYS APPLIES, whatever its `until` says, and that is a
# deliberate structural choice rather than a convenience. A band list that
# simply ran out would return "do not emit" for every `n` past its end — i.e.
# the line would vanish permanently, silently, and only on long-running
# processes. This module's failure mode must be "too many lines", never "the
# evidence is gone", so there is no way to fall off the end of a cadence.

#: Widening: every repeat, then every 5th, then every 15th, then every 60th. On
#: a once-a-minute tick that reads as minutely for the first few minutes, then
#: every five for the first half hour, every quarter-hour to two hours, hourly
#: after that. ⭐ COMPUTED, not estimated: applied to the aegis pulse it takes the
#: measured 2,274-line and 2,754-line tails to 52 and 60 lines.
DEFAULT_CADENCE: tuple[tuple[int | None, int], ...] = (
    (5, 1), (30, 5), (120, 15), (None, 60),
)

#: Say it once and never again. For a condition that CANNOT change without a
#: code change — a failed import of a module that either exists or does not.
ONCE: tuple[tuple[int | None, int], ...] = ((1, 1), (None, 0))


def emits(n: int, cadence: "tuple[tuple[int | None, int], ...]" = DEFAULT_CADENCE) -> bool:
    """Whether the `n`-th consecutive repeat of a state is emitted (0-based).

    ``n == 0`` is the FIRST occurrence of a state and always speaks. That is not
    an optimisation: a cadence is about how often to restate something, and
    there is nothing to restate yet.
    """
    if n <= 0:
        return True
    last = len(cadence) - 1
    for i, (until, every) in enumerate(cadence):
        if i == last or until is None or n < until:
            return every > 0 and n % every == 0
    # Reachable only for an EMPTY cadence, and it fails OPEN for the reason in
    # the band comment above: a caller who passes nothing gets a noisy log, not
    # a silent one.
    return True


def _validated(cadence) -> "tuple[tuple[int | None, int], ...]":
    """Reject a cadence whose bands are unusable, at construction time.

    ⛔ An empty cadence is the one that matters: `emits` fails open on it, so
    every consumer would silently go back to the flood this module exists to
    stop, and the only symptom would be a large log.

    ⭐ THE LAST BAND MUST BE WRITTEN OPEN — `(None, every)` — even though `emits`
    would apply it regardless. Requiring it syntactically is what stops a cadence
    from LOOKING closed while behaving open: `((5, 1), (30, 5))` reads as "stop
    after thirty" to everyone who has not read `emits`, and a declaration that
    contradicts the behaviour is a trap whether or not it changes the output.
    That leaves `emits`' own last-band clause as a fail-open backstop rather than
    the primary mechanism, which is the right way round.
    """
    bands = tuple((None if u is None else int(u), int(e)) for u, e in cadence)
    if not bands:
        raise ValueError("cadence has no bands — every repeat would be emitted")
    if bands[-1][0] is not None:
        raise ValueError(
            f"the last band must be open-ended (None, every), got {bands[-1]!r} "
            f"— a closed final band reads as a permanent silence it is not")
    seen = 0
    for until, _every in bands[:-1]:
        if until is None:
            raise ValueError("only the LAST band may be open-ended")
        if until <= seen:
            raise ValueError(f"band boundaries must increase: {until} after {seen}")
        seen = until
    return bands


class Suppressor:
    """Per-topic repeat state.

    A `topic` is a stable literal naming one recurring statement. A `state` is
    what the statement is ABOUT — an exception class, "up"/"down". When the
    state changes the cadence restarts and the new state speaks immediately,
    because a changed condition is news.

    ⛔ `state` MUST NOT be a full message. Anything that varies between
    otherwise-identical occurrences — a retry counter, a port, an elapsed time —
    makes every call a state change and defeats suppression entirely, which is
    indistinguishable from this module not being wired in at all. Pass the
    exception CLASS, not `str(exc)`; render the detail into the line instead.

    ⛔ A topic dictionary keyed by caller data would grow without bound. Topics
    are literals at the three call sites; only one state is retained per topic,
    so the memory here is the number of literals in the source.

    Thread-safe: the consumers are a telemetry flush thread, an asyncio task,
    and a credential refresh that already runs under two other locks.
    """

    __slots__ = ("_cadence", "_lock", "_state", "_n", "_emitted")

    def __init__(self, cadence=DEFAULT_CADENCE) -> None:
        self._cadence = _validated(cadence)
        self._lock = threading.Lock()
        self._state: dict[str, str] = {}
        self._n: dict[str, int] = {}
        self._emitted: dict[str, int] = {}

    def consider(self, topic: str, state: str = "") -> "tuple[bool, int]":
        """``(emit, suppressed_since_the_last_emitted_line)``.

        The count is what makes sparseness lossless — a caller that throws it
        away turns "this happened 13,479 times" into "this happened", which is
        the weaker of the two statements the flood was at least making.
        """
        with self._lock:
            if self._state.get(topic) != state:
                self._state[topic] = state
                self._n[topic] = 0
                self._emitted[topic] = 0
                return True, 0
            n = self._n[topic] + 1
            self._n[topic] = n
            if emits(n, self._cadence):
                suppressed = n - self._emitted[topic] - 1
                self._emitted[topic] = n
                return True, suppressed
            return False, 0

    def reset(self, topic: str) -> None:
        """Forget a topic, so its next occurrence speaks at once.

        ⛔⛔ THIS IS THE HALF THAT IS EASY TO FORGET AND WRONG TO OMIT. Without
        it, a fault that clears and then RETURNS is reported at whatever wide
        cadence the first outage had already widened to — so the second
        incident, which is a new event, arrives up to an hour late or not at
        all. A recovery path that does not reset is a suppressor that hides
        exactly the transition a reader is looking for.
        """
        with self._lock:
            self._state.pop(topic, None)
            self._n.pop(topic, None)
            self._emitted.pop(topic, None)

    def clear(self) -> None:
        """Forget every topic.

        ⛔⛔ THIS EXISTS FOR SUITE ISOLATION AND NOTHING IN THE PRODUCT CALLS IT,
        which is worth saying out loud rather than leaving a reader to wonder.
        A `ONCE` suppressor held in a module global is per-PROCESS by design — and
        a test process is one process, so the first test to trip a topic makes the
        line invisible to every test that runs after it. That is not hypothetical:
        it turned `test_a_missing_accessor_is_not_the_same_as_a_signed_out_machine`
        red in the full suite while it passed alone, on 2026-08-19, and a
        per-test-remembered reset is exactly the kind of isolation a suite ends up
        not having. `tests/conftest.py` resets every module-level Suppressor it can
        find, so nothing has to remember.
        """
        with self._lock:
            self._state.clear()
            self._n.clear()
            self._emitted.clear()

    def seen(self, topic: str) -> int:
        """Repeats of the current state, for a caller that wants the total in
        its own line. 0 when the topic is unknown or was just reset."""
        with self._lock:
            return int(self._n.get(topic, 0))


def suppressed_note(n: int) -> str:
    """The one rendering of a suppressed count, so three call sites cannot each
    invent their own phrasing for the same fact. Empty when nothing was dropped
    — a bare ``(+0 …)`` on the first line of an outage reads as a bug."""
    return f" (+{int(n)} since the last of these)" if int(n) > 0 else ""
