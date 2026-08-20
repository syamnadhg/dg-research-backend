"""Half the evidence in a support bundle was two sentences repeated.

⛔⛔ MEASURED 2026-08-19 ON THE OWNER'S OWN FILES, which is the only reason any
number in this file is allowed to be here.

The session log a `--send-logs` bundle carries — 1,367 lines, 130,113 bytes:

    412 lines  33.9% of BYTES  telemetry: no id-token accessor (ImportError) …
    231 lines   9.8%           [aegis] worker 1: ◆ standing watch
    ─────────  ─────
               43.7%           two sentences

The last 5 MiB of the four raw machine logs the bundle also carries:

    backend.log        74,836 / 82,032 = 91.3%   "GET /api/health … 200 OK"
    backend-2.log      80,303 / 84,202 = 95.4%   the same line
    backend.err.log     5,047 / 10,581 = 47.7%   ONE repeated refresh error
    backend-2.err.log  13,479 / 14,083 = 95.7%   the same sentence

⭐⭐ AND THEY ARE ONE DEFECT, NOT FOUR. Every one is a true statement whose
information content is a single bit, emitted on a hot path with no cadence. So
the fix is one shared primitive (`logquiet`) with three consumers, plus a
read-time rule for the files that are already frozen and cannot be helped by
silencing anything.

⛔ THE FIX IS NOT SILENCE, and most of the tests below are about that
distinction. The accessor line is the ONLY account of a wiring fault that made
every telemetry batch anonymous. The refresh line is the single line that
diagnosed a new owner's entire outage. A failing health probe is the endpoint the
worker watchdog uses to decide a worker is wedged. Each of those must still
speak; what must stop is the 412th copy.
"""
from __future__ import annotations

import ast
import inspect
import os
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

# ⛔ `code_only_deep` ONLY, never plain `code_only`. Mutation caught this file
# asserting on `fh.tell()` while the mutant had removed it — the DOCSTRING of
# the function under test names the call, and `code_only` strips `#` comments
# but not docstrings. A function's prose stood in for its code.
from conftest import code_only_deep

import logquiet
import research
import telemetry as tm
from auth import credentials as creds


# ⛔ MEMOISED, AND MEASURED. `code_only_deep` on research.py ast-walks 71k lines to
# blank every docstring — 3.6 s a call, and nine tests in this file want the whole
# module, which made the file 38 s on its own. Per PROCESS, which is exactly the
# right lifetime: a mutation harness rewrites the source between pytest processes,
# never inside one, so a cache cannot serve a stale file to a mutant.
_RESEARCH_SRC: "str | None" = None


def _research_src() -> str:
    global _RESEARCH_SRC
    if _RESEARCH_SRC is None:
        _RESEARCH_SRC = code_only_deep(inspect.getsource(research))
    return _RESEARCH_SRC



# ══════════════════════════════════════════════════════════════════════════
#  1. logquiet — the shared primitive
# ══════════════════════════════════════════════════════════════════════════

def test_the_first_occurrence_of_a_state_always_speaks():
    """⛔ THE POLARITY TEST, first in the file on purpose. A cadence that
    suppressed index 0 would delete the one copy of every line that was worth
    having — and every "it is quieter now" assertion below would still pass."""
    assert logquiet.emits(0) is True
    assert logquiet.emits(0, logquiet.ONCE) is True
    assert logquiet.emits(0, ()) is True


def test_a_negative_index_is_treated_as_the_first():
    """Fail toward speaking. A caller that manages to pass -1 gets a line."""
    assert logquiet.emits(-1) is True


def test_the_default_cadence_widens_and_never_stops():
    fired = [n for n in range(400) if logquiet.emits(n)]
    # minutely at first…
    assert fired[:6] == [0, 1, 2, 3, 4, 5]
    # …then every 5th, every 15th, and hourly, forever.
    assert 10 in fired and 25 in fired
    assert 30 in fired and 105 in fired
    assert 120 in fired and 180 in fired and 360 in fired
    # ⛔ The property that matters more than any boundary: it thins out, but it
    # never goes quiet. A cadence that ran out would delete a liveness pulse
    # permanently on exactly the long-running processes it exists for.
    assert [n for n in range(100_000, 100_200) if logquiet.emits(n)], \
        "the cadence stopped emitting entirely"


def test_the_measured_floods_become_readable():
    """⭐ The claim in `_aegis_pulse_line`'s docstring, computed rather than
    asserted in prose — so raising a band cannot leave a stale number behind."""
    assert sum(1 for n in range(2274) if logquiet.emits(n)) == 52
    assert sum(1 for n in range(2754) if logquiet.emits(n)) == 60


def test_once_says_it_once():
    assert [n for n in range(500) if logquiet.emits(n, logquiet.ONCE)] == [0]


def test_an_empty_cadence_fails_toward_noise():
    """⛔ THE DIRECTION OF THE FAILURE IS THE DESIGN. A malformed cadence must
    produce a noisy log, never a silent one — this module's whole risk is
    deleting evidence, so there is no way to fall off the end into silence."""
    assert all(logquiet.emits(n, ()) for n in range(50))


def test_the_last_band_applies_however_its_boundary_reads():
    """A closed final band would otherwise be a permanent silence hole."""
    closed = ((2, 1), (4, 2))
    assert logquiet.emits(0, closed) is True
    assert logquiet.emits(1, closed) is True
    assert logquiet.emits(100, closed) is True     # 100 % 2 == 0
    assert logquiet.emits(101, closed) is False


@pytest.mark.parametrize("bad", [
    (),                              # nothing at all
    ((None, 1), (5, 1)),             # an open band that is not last
    ((5, 1), (30, 5)),               # a closed final band
    # ⛔ FOUND BY MUTATION. The two cases below used to read `((5, 1), (5, 2))`
    # and `((5, 1), (3, 2))` — both of which the last-band-must-be-open rule now
    # rejects FIRST, so the increasing-boundary check had no case of its own and
    # deleting it survived. An open final band is what makes these reach it.
    ((5, 1), (5, 2), (None, 3)),     # boundaries that do not increase
    ((5, 1), (3, 2), (None, 3)),     # boundaries that go backwards
    # ⛔ FOUND ON A FINAL READ, NOT BY MUTATION. Every case above is caught by the
    # last-band-must-be-open rule FIRST, so the "only the LAST band may be
    # open-ended" branch had no case that reached it. Two open bands is the shape
    # that does: without the check it validates cleanly and the second band is
    # silently dead, because `emits` returns on the first `until is None`.
    ((None, 1), (None, 60)),
    ((0, 1), (None, 2)),             # a zero-width first band
])
def test_a_malformed_cadence_is_refused_at_construction(bad):
    """Loud at construction beats fail-open at every call: an empty cadence
    would silently restore the flood and the only symptom would be a big log."""
    with pytest.raises(ValueError):
        logquiet.Suppressor(bad)


def test_a_repeat_is_counted_not_discarded():
    s = logquiet.Suppressor()
    seen = [s.consider("t", "up") for _ in range(31)]
    emitted = [(i, d) for i, (e, d) in enumerate(seen) if e]
    assert [i for i, _ in emitted] == [0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30]
    # ⭐ The count is what makes the sparseness lossless. Between index 5 and
    # index 10 four repeats were dropped, and the line at 10 says so.
    assert dict(emitted)[10] == 4
    assert dict(emitted)[15] == 4
    # And the first line of a state never claims a suppressed count.
    assert dict(emitted)[0] == 0


def test_a_changed_state_speaks_immediately_however_quiet_it_had_become():
    """⛔ The alarm this must not delay. The aegis pulse can be an hour into its
    widest band when Firestore drops; the transition is news and cannot wait."""
    s = logquiet.Suppressor()
    for _ in range(500):
        s.consider("pulse", "up")
    emit, dropped = s.consider("pulse", "down")
    assert emit is True
    assert dropped == 0, "a state change is not a suppressed repeat"


def test_reset_makes_the_next_occurrence_speak():
    """⛔⛔ THE HALF THAT IS EASY TO FORGET. Without it a fault that clears and
    RETURNS is reported at the wide cadence the first outage had reached, so the
    second incident — a new event — arrives up to an hour late."""
    s = logquiet.Suppressor()
    for _ in range(500):
        s.consider("net", "ConnectionError")
    assert s.consider("net", "ConnectionError")[0] is False
    s.reset("net")
    assert s.consider("net", "ConnectionError") == (True, 0)


def test_reset_of_an_unknown_topic_is_harmless():
    logquiet.Suppressor().reset("never-seen")


def test_seen_counts_repeats_of_the_current_state():
    s = logquiet.Suppressor()
    assert s.seen("t") == 0
    for _ in range(7):
        s.consider("t", "up")
    assert s.seen("t") == 6
    s.consider("t", "down")
    assert s.seen("t") == 0, "a state change restarts the count"


def test_topics_do_not_interfere():
    s = logquiet.Suppressor()
    for _ in range(50):
        s.consider("a", "x")
    assert s.consider("b", "x") == (True, 0), "one topic muted another"


def test_the_suppressed_note_is_empty_when_nothing_was_dropped():
    """A bare `(+0 …)` on the first line of an outage reads as a bug."""
    assert logquiet.suppressed_note(0) == ""
    assert logquiet.suppressed_note(-3) == ""
    assert "+247" in logquiet.suppressed_note(247)


def test_the_note_has_exactly_one_definition():
    """⛔ Three call sites render this fact. A second phrasing means a reader
    greps for one wording and misses two of the three floods."""
    src = code_only_deep(logquiet)
    assert src.count("since the last of these") == 1
    for name, text in (("research", _research_src()),
                       ("telemetry", code_only_deep(inspect.getsource(tm))),
                       ("credentials", code_only_deep(inspect.getsource(creds)))):
        assert "since the last of these" not in text, (
            f"{name} spells the suppressed note out itself instead of "
            f"calling logquiet.suppressed_note")


def test_logquiet_imports_nothing_first_party():
    """⛔ LOAD-BEARING, NOT TIDY. Its consumers are telemetry.py — which
    documents that it imports nothing from the backend so a telemetry failure
    can never sit in the path of the thing it measures — and
    auth/credentials.py, which runs during `--pair` before any pipeline module
    exists. One first-party import here breaks both."""
    tree = ast.parse(Path(logquiet.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "threading"}, (
        f"logquiet grew an import: {sorted(imported)}")


def test_the_suppressor_is_locked():
    """Consumers are a telemetry flush thread, an asyncio task, and a credential
    refresh reached from the gRPC metadata thread."""
    src = code_only_deep(inspect.getsource(logquiet.Suppressor))
    assert "threading.Lock()" in src
    assert src.count("with self._lock:") >= 3


# ══════════════════════════════════════════════════════════════════════════
#  2. Fix A — the 412-line accessor flood (33.9% of the session log's bytes)
# ══════════════════════════════════════════════════════════════════════════

def test_a_missing_accessor_still_says_so_once(caplog):
    """⛔ The line is not deleted. It is the ONLY account of the wiring fault
    that made every telemetry batch this product ever sent anonymous.

    ⭐ NO PER-TEST SUPPRESSOR IS INSTALLED HERE, deliberately. The real module
    global is used, so this test also proves the suite-wide reset in conftest
    works — a `ONCE` topic is per-PROCESS, and a pytest run is one process, which
    is how this exact assertion went red in a file nobody had touched."""
    with caplog.at_level(logging.DEBUG, logger="telemetry"):
        assert tm._id_token() is None
    hits = [r for r in caplog.records if "id-token accessor" in r.getMessage()]
    assert len(hits) == 1
    assert "ImportError" in hits[0].getMessage()


def test_the_accessor_line_does_not_repeat(caplog):
    """⛔⛔ THE MEASURED DEFECT: 412 copies in one session log. `_id_token` is
    called once per flush and a flush happens per event batch."""
    with caplog.at_level(logging.DEBUG, logger="telemetry"):
        for _ in range(412):
            tm._id_token()
    hits = [r for r in caplog.records if "id-token accessor" in r.getMessage()]
    assert len(hits) == 1, f"{len(hits)} copies of a one-bit fault"


def test_a_different_failure_class_speaks_again(caplog):
    """⭐ WHY IT IS KEYED ON THE EXCEPTION CLASS RATHER THAN ONE-SHOT. A missing
    module cannot start existing mid-process, so the second ImportError carries
    nothing — but a different failure is a different fault and must be heard."""
    quiet = tm._ID_TOKEN_QUIET
    with caplog.at_level(logging.DEBUG, logger="telemetry"):
        for _ in range(50):
            tm._id_token()
    assert quiet.consider("no-id-token-accessor", "ImportError")[0] is False
    assert quiet.consider("no-id-token-accessor", "AttributeError")[0] is True, (
        "a different failure class is a different fault and must be heard")
    assert quiet.consider("no-id-token-accessor", "AttributeError")[0] is False


def test_the_accessor_never_forces_a_refresh_or_touches_the_keystore():
    """Pre-existing invariant, re-pinned because this wave edited the function:
    `_fresh_user_mode_id_token` does a network round-trip AND a keystore wipe on
    revoke, so wiring it in here would make telemetry cause an auth side effect.

    ⛔ `code_only_deep`, not `code_only`: this function's own DOCSTRING explains
    at length why it must not call `_fresh_user_mode_id_token`, so a presence
    assertion on comment-stripped-only source matches the prose and can never
    fail."""
    src = code_only_deep(inspect.getsource(tm._id_token))
    assert "_fresh_user_mode_id_token" not in src
    assert "keystore" not in src


# ══════════════════════════════════════════════════════════════════════════
#  3. Fix B — the aegis pulse
# ══════════════════════════════════════════════════════════════════════════

def test_the_pulse_carries_how_long_the_watch_has_held():
    """⭐ WHAT MAKES THE SPARSENESS LOSSLESS. The old argument for a repeating
    text was that `log()` stamps a fresh timestamp every minute; an hour apart,
    that no longer answers "has it been up the whole time, or did it restart?"."""
    line = research._aegis_pulse_line(1, 0, up_for=15132.0)
    assert "standing watch" in line
    assert "4h12m" in line


def test_a_pulse_with_no_clock_does_not_invent_a_duration():
    """⛔ `up_for=None` must not render as "0s" — a fabricated fact is worse than
    an absent one, and the pre-cadence shape has to stay available."""
    line = research._aegis_pulse_line(1, 0)
    assert "standing watch" in line
    assert "0s" not in line


def test_both_pulse_shapes_report_what_was_suppressed():
    up = research._aegis_pulse_line(1, 0, up_for=60.0, suppressed=59)
    down = research._aegis_pulse_line(1, 0, down_for=60.0, suppressed=3)
    assert "+59" in up
    assert "+3" in down, "a broken watch loses its count while a healthy one keeps it"


def test_a_broken_watch_still_says_everything_it_used_to():
    """The 2026-08-17 fix stays intact under the 08-19 one."""
    line = research._aegis_pulse_line(2, 3, down_for=600.0)
    assert "standing watch" not in line
    assert "watch broken" in line and "✗" in line
    assert "10m00s" in line
    assert "offline" in line and "will not arrive" in line
    assert "worker 2" in line


def _pulse_loop_src() -> str:
    """The loop body, sliced to the NEXT construct rather than a byte window — a
    fixed slice slid past the lines under test once already this month."""
    src = _research_src()
    start = src.index("async def _aegis_pulse_loop():")
    end = src.index("asyncio.create_task(_aegis_pulse_loop())", start)
    return src[start:end]


def test_the_loop_applies_the_shared_cadence():
    body = _pulse_loop_src()
    assert "logquiet.Suppressor()" in body
    assert ".consider(" in body
    assert "if not _emit:" in body


def test_the_tick_stays_at_sixty_seconds():
    """⛔⛔ TWO DECISIONS, AND COLLAPSING THEM WOULD BE A BUG. The state check is
    what notices a broken watch, so slowing the TICK would delay the alarm this
    loop exists to raise. Only the EMISSION widens."""
    body = _pulse_loop_src()
    assert "await asyncio.sleep(60)" in body


def test_a_pipeline_run_does_not_reset_the_cadence():
    """A two-hour run must not read as a state change and put the pulse back to
    one line a minute afterwards — so the running branch skips the suppressor
    entirely rather than consulting it."""
    body = _pulse_loop_src()
    running = body[body.index('_QUEUE_STATE.get("running")'):]
    running = running[:running.index("_cut_off")]
    assert "continue" in running
    assert "consider(" not in running


def test_the_loop_still_passes_the_real_state_and_level():
    """Everything the 08-17 outage wave pinned here, re-pinned: this wave
    rewrote the loop, and a `down_for` that stopped being computed would put the
    pulse straight back to claiming a watch it is not keeping.

    ⛔⛔ THE KEYWORD IS PINNED WITH ITS EXPRESSION, and mutation is why. `assert
    "up_for=" in body` passed against `up_for=None` and against
    `suppressed=0` — the keyword survives every mutation of the value behind it,
    so a presence check on the name proves only that the argument is still
    SPELLED, never that anything is passed. Two survivors said so on the first
    round of this wave, and `_clear_local_logs`' default said it a third time."""
    body = _pulse_loop_src()
    assert "_firebase_db is None" in body
    assert "down_for=((time.time() - _since) if _since else 0.0)" in body
    assert "up_for=None if _cut_off else (time.time() - _state_since)" in body
    assert "suppressed=_dropped" in body
    assert '"WARN" if _cut_off else "INFO"' in body


def test_the_uptime_clock_and_the_cadence_restart_together():
    """Both are driven off ONE comparison. Two independent notions of "the state
    changed" is how a line ends up reporting an uptime from before the restart
    it is meant to reveal."""
    body = _pulse_loop_src()
    branch = body[body.index("if _state != _last_state:"):]
    branch = branch[:branch.index("_quiet.consider")]
    assert "_last_state = _state" in branch
    assert "_state_since = time.time()" in branch


# ══════════════════════════════════════════════════════════════════════════
#  4. Fix C — the refresh flood (95.7% of one .err tail)
# ══════════════════════════════════════════════════════════════════════════

class _Boom(creds.requests.RequestException):
    pass


def _exchange(monkeypatch, *, fail: bool, status: int = 200):
    """Drive `_do_refresh_exchange` past the keystore with no keyring in sight."""
    monkeypatch.setattr(creds.keystore, "get", lambda *a, **k: "rt-token")
    monkeypatch.setattr(creds.keystore, "set", lambda *a, **k: None)
    monkeypatch.setattr(creds.keystore, "promote_pending", lambda *a, **k: None)

    class _Resp:
        status_code = status
        content = b"{}"
        ok = 200 <= status < 300

        def json(self):
            return {"refresh_token": "r", "id_token": "i", "expires_in": 3600,
                    "user_id": "u"}

        @property
        def text(self):
            return "{}"

    def _post(*a, **k):
        if fail:
            raise _Boom("Failed to resolve 'securetoken.googleapis.com'")
        return _Resp()

    monkeypatch.setattr(creds.requests, "post", _post)
    return creds.RefreshTokenCredentials("iu", "key")


def test_the_refresh_error_still_names_the_failure_once(monkeypatch, caplog):
    """⛔ NOT DELETED. This is the single line that diagnosed a new owner's whole
    outage — `Failed to resolve 'securetoken.googleapis.com'`."""
    monkeypatch.setattr(creds, "_REFRESH_NET_QUIET", logquiet.Suppressor())
    c = _exchange(monkeypatch, fail=True)
    with caplog.at_level(logging.WARNING, logger=creds.log.name):
        with pytest.raises(_Boom):
            c._do_refresh_exchange()
    hits = [r for r in caplog.records if "refresh: network error" in r.getMessage()]
    assert len(hits) == 1
    assert "securetoken.googleapis.com" in hits[0].getMessage()
    assert "attempt 1" in hits[0].getMessage()


def test_a_dead_network_does_not_write_thirteen_thousand_lines(monkeypatch, caplog):
    """⛔⛔ THE MEASURED DEFECT: 13,479 of 14,083 lines in one .err tail, and
    since 2026-08-17 this logger is BRIDGED into `log()` — so the flood now
    lands in the file users send and in every per-run folder too."""
    monkeypatch.setattr(creds, "_REFRESH_NET_QUIET", logquiet.Suppressor())
    c = _exchange(monkeypatch, fail=True)
    with caplog.at_level(logging.WARNING, logger=creds.log.name):
        for _ in range(600):
            with pytest.raises(_Boom):
                c._do_refresh_exchange()
    hits = [r for r in caplog.records if "refresh: network error" in r.getMessage()]
    assert 5 <= len(hits) <= 30, f"{len(hits)} lines for 600 retries"
    # ⭐ And the scale is still reported, so "it kept failing" survives.
    assert any("+" in r.getMessage() for r in hits)
    assert any("attempt 6" in r.getMessage() for r in hits)


def test_recovery_resets_the_cadence(monkeypatch, caplog):
    """⛔⛔ A SECOND OUTAGE IS A NEW EVENT. Without the reset it would be
    reported at whatever hourly cadence the first outage had widened to."""
    monkeypatch.setattr(creds, "_REFRESH_NET_QUIET", logquiet.Suppressor())
    down = _exchange(monkeypatch, fail=True)
    for _ in range(400):
        with pytest.raises(_Boom):
            down._do_refresh_exchange()
    assert creds._REFRESH_NET_QUIET.seen(creds._REFRESH_NET_TOPIC) > 0
    _exchange(monkeypatch, fail=False)._do_refresh_exchange()
    assert creds._REFRESH_NET_QUIET.seen(creds._REFRESH_NET_TOPIC) == 0
    with caplog.at_level(logging.WARNING, logger=creds.log.name):
        with pytest.raises(_Boom):
            _exchange(monkeypatch, fail=True)._do_refresh_exchange()
    assert any("refresh: network error" in r.getMessage() for r in caplog.records), \
        "the second outage was swallowed by the first one's cadence"


def test_the_reset_boundary_is_the_post_returning_not_a_2xx(monkeypatch):
    """⭐ The topic is "could we reach securetoken at all", so a 400
    TOKEN_EXPIRED proves the network is back exactly as well as a 200 does."""
    monkeypatch.setattr(creds, "_REFRESH_NET_QUIET", logquiet.Suppressor())
    down = _exchange(monkeypatch, fail=True)
    for _ in range(10):
        with pytest.raises(_Boom):
            down._do_refresh_exchange()
    assert creds._REFRESH_NET_QUIET.seen(creds._REFRESH_NET_TOPIC) > 0
    with pytest.raises(Exception):
        _exchange(monkeypatch, fail=False, status=400)._do_refresh_exchange()
    assert creds._REFRESH_NET_QUIET.seen(creds._REFRESH_NET_TOPIC) == 0


def test_the_state_is_the_exception_class_never_its_message():
    """⛔ The message embeds the resolver's own text. Anything that varies
    between otherwise-identical failures restarts the cadence every time and
    suppresses nothing — indistinguishable from not wiring this in at all."""
    src = code_only_deep(inspect.getsource(
        creds.RefreshTokenCredentials._do_refresh_exchange))
    assert "type(e).__name__" in src
    assert "str(e)" not in src


def test_the_reset_is_reached_before_any_status_branch():
    """A reset placed after the 400 handling would never run for a revoked
    token, so a revoke during an outage would leave the cadence wide open."""
    src = code_only_deep(inspect.getsource(
        creds.RefreshTokenCredentials._do_refresh_exchange))
    assert src.index("_REFRESH_NET_QUIET.reset(") < src.index("resp.status_code == 400")


# ══════════════════════════════════════════════════════════════════════════
#  5. Fix D1 — the live health-probe filter
# ══════════════════════════════════════════════════════════════════════════

def _access_record(path: str, status: int, method: str = "GET"):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                             '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:1", method, path, "1.1", status), None)


@pytest.mark.parametrize("status,kept", [(200, False), (204, False),
                                         (500, True), (404, True), (301, True)])
def test_only_a_SUCCESSFUL_probe_is_dropped(status, kept):
    """⛔⛔ THE FILTER USED TO DELETE THE SIGNAL WITH THE NOISE. Its test was
    `"/api/health" not in message`, so a 500 from the endpoint the worker
    watchdog uses to decide a worker is wedged was silenced by the same rule as
    the 74,836 boring ones."""
    rec = _access_record("/api/health", status)
    assert research._DropHealthProbeAccessLines().filter(rec) is kept


def test_every_other_route_still_logs():
    assert research._DropHealthProbeAccessLines().filter(
        _access_record("/api/runs", 200)) is True


def test_a_line_that_merely_mentions_the_path_survives():
    """⛔ The lines a bundle exists for name this path: the watchdog's
    "/api/health unreachable for 180s", `_probe_local_api`'s failure detail. A
    path match would delete exactly the diagnostics, and a bytes-level rule that
    got this wrong would do it silently inside a support archive."""
    for text in (b'[WARN] /api/health unreachable for 180s while IDLE',
                 b'[INFO] probing http://localhost:8000/api/health',
                 b'127.0.0.1:1 - "GET /api/health HTTP/1.1" 503'):
        assert research._drop_from_tail(text) is False, text


def test_an_unformattable_record_is_never_swallowed():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                            "%s %s", ("only-one-arg",), None)
    assert research._DropHealthProbeAccessLines().filter(rec) is True


def test_the_probe_pattern_has_exactly_one_definition():
    """⛔ TWO READERS, ONE PATTERN. A successful probe is dropped as it is logged
    and again as a frozen log is read into a bundle; the bytes version is
    COMPILED FROM the string so there is no sibling for a mutant to hide in."""
    src = _research_src()
    assert src.count("_HEALTH_PROBE_ACCESS_PATTERN = (") == 1
    assert src.count('_HEALTH_PROBE_ACCESS_PATTERN.encode("ascii")') == 1
    # ⛔ And the class must not carry a private copy of the path any more.
    assert "_PROBE_PATH" not in src
    assert research._HEALTH_PROBE_ACCESS_RE_BYTES.pattern == \
        research._HEALTH_PROBE_ACCESS_RE.pattern.encode("ascii")


def test_the_pattern_requires_a_status_not_just_a_path():
    """The `2\\d\\d` is what makes this a filter on "nothing happened" rather
    than on a topic."""
    assert re.search(r"2..d..d", research._HEALTH_PROBE_ACCESS_PATTERN) or \
        "2\\d\\d" in research._HEALTH_PROBE_ACCESS_PATTERN


def test_the_filter_is_still_scoped_to_the_access_logger_alone():
    cfg = research._uvicorn_log_config()
    assert cfg["handlers"]["dg_access"]["filters"] == ["no_health_probe"]
    assert "filters" not in cfg["handlers"]["dg_default"]


# ══════════════════════════════════════════════════════════════════════════
#  6. Fix D2 — the read-time rule for files that are already frozen
# ══════════════════════════════════════════════════════════════════════════

def test_a_successful_probe_costs_a_bundle_nothing():
    stats: dict = {}
    lines = [b'127.0.0.1:1 - "GET /api/health HTTP/1.1" 200 OK'] * 500 + [b"real"]
    kept = research._filter_tail_lines(reversed(lines), 10_000, stats)
    assert kept == [b"real"]
    assert stats["dropped"] == 500


def test_a_run_of_identical_lines_collapses_to_one_plus_a_count():
    """⭐ LOSSLESS, and GENERAL — it catches the refresh flood, our own pulse,
    and whatever the next one turns out to be with nobody adding a pattern."""
    stats: dict = {}
    lines = [b"before"] + [b"boom"] * 9 + [b"after"]
    kept = research._filter_tail_lines(reversed(lines), 10_000, stats)
    assert list(reversed(kept)) == [
        b"before", b"boom", b"[bundle] ^ the line above then repeated 8 more times",
        b"after"]
    assert stats["collapsed"] == 8


def test_a_collapsed_run_keeps_the_oldest_copy_and_the_note_follows_it():
    """Chronological order survives the backward walk: the line, THEN the note
    that it went on repeating. Reversed, that is what a reader sees."""
    kept = research._filter_tail_lines(reversed([b"x", b"x", b"x"]), 10_000, {})
    chrono = list(reversed(kept))
    assert chrono[0] == b"x"
    assert b"repeated 2 more times" in chrono[1]


def test_only_CONSECUTIVE_duplicates_collapse():
    """⛔ Collapsing non-adjacent duplicates would destroy a timeline: "A B A"
    is a different story from "A A B"."""
    stats: dict = {}
    kept = research._filter_tail_lines(reversed([b"a", b"b", b"a"]), 10_000, stats)
    assert list(reversed(kept)) == [b"a", b"b", b"a"]
    assert stats["collapsed"] == 0


def test_dropped_noise_between_duplicates_does_not_block_a_collapse():
    """A pulse separated only by health probes is still a run of one sentence."""
    noise = b'127.0.0.1:1 - "GET /api/health HTTP/1.1" 200 OK'
    stats: dict = {}
    kept = research._filter_tail_lines(
        reversed([b"pulse", noise, b"pulse", noise, b"pulse"]), 10_000, stats)
    assert stats["dropped"] == 2
    assert stats["collapsed"] == 2
    assert list(reversed(kept))[0] == b"pulse"


def test_a_collapsed_run_that_outlasts_the_budget_still_reports_its_count():
    """⛔ The break is placed AFTER the flush precisely so a run in progress
    cannot be dropped along with its count when the budget runs out."""
    stats: dict = {}
    lines = [b"z" * 200] * 50 + [b"tail"] * 5000
    kept = research._filter_tail_lines(reversed(lines), 300, stats)
    assert stats["collapsed"] >= 4999
    assert any(b"repeated" in line for line in kept)


def test_the_budget_bounds_what_is_kept():
    stats: dict = {}
    lines = [f"line {i:06d} padded out to some width".encode() for i in range(5000)]
    kept = research._filter_tail_lines(reversed(lines), 1000, stats)
    assert sum(len(x) + 1 for x in kept) <= 1000 + 64
    assert kept[0] == lines[-1], "the newest line must be the one kept"


def test_a_tail_starts_at_a_whole_line_and_stays_bounded(tmp_path):
    """The pre-existing contract, re-pinned: this wave rewrote the reader."""
    p = tmp_path / "big.log"
    # ⚠ write_BYTES, not write_text: on Windows write_text translates
    # \n to \r\n, so the fixture would not hold the bytes this test
    # asserts on. The reader under test is byte-oriented by design.
    p.write_bytes("".join(f"line {i:05d} padded out\n"
                          for i in range(2000)).encode())
    tail = research._tail_bytes(p, limit=500).decode()
    assert tail.startswith("line ")
    assert tail.endswith("line 01999 padded out\n")
    assert len(tail) <= 500, f"the tail is {len(tail)} bytes for a 500-byte limit"
    assert "line 00000" not in tail


def test_a_trim_never_orphans_a_collapse_marker(tmp_path):
    """⛔⛔ FOUND BY MY OWN REVIEW, AFTER 41/41 MUTANTS. The budget trim removes the
    OLDEST lines — and if the oldest line is a collapsed run's retained copy, its
    "^ the line above then repeated N more times" marker survives pointing at
    whatever line is now above it. A fabricated repeat count, inside a support
    archive, in the wave whose whole subject is markers that lie."""
    p = tmp_path / "orphan.log"
    # An old collapsed run, then enough newer content to push the budget past it.
    # ⭐ SMALL ON PURPOSE. The sweep below is exhaustive, so the fixture's size
    # is the sweep's cost: forty unique lines made this one test 27 seconds.
    # Three still spans the whole orphan window, and `seen_marker` proves it.
    p.write_bytes(b"dup\n" * 6 + b"".join(
        f"unique line {i:04d} padding padding\n".encode() for i in range(3)))
    # ⛔⛔ EXHAUSTIVE, AND THE FIRST VERSION WAS NOT. It swept
    # `range(40, 900, 17)` and the mutant that deletes the orphan sweep SURVIVED,
    # because the window where an orphan can appear is narrow — the walk has to
    # reach the collapsed run AND then overshoot the budget by less than one
    # line, which for this fixture is a ~50-byte band above 1320. A sampled
    # sweep that steps over the only interesting band is a guard that cannot
    # fire, in the very test written to catch one. Every limit, no steps.
    size = p.stat().st_size
    seen_marker = False
    for limit in range(1, size + 120):
        out = research._tail_bytes(p, limit=limit)
        for i, line in enumerate(out.splitlines()):
            if line.startswith(research._TAIL_REPEAT_NOTE_PREFIX):
                seen_marker = True
                assert i > 0, (
                    f"limit={limit}: a collapse marker is the FIRST line, so it "
                    f"describes a line that is no longer in the tail")
    assert seen_marker, (
        "no limit in the sweep produced a collapse marker at all, so this test "
        "proved nothing about orphaning")


def test_the_marker_prefix_is_derived_from_the_template():
    """⛔ Two spellings of the same marker and the orphan check silently stops
    matching, which puts the fabricated count straight back."""
    assert research._TAIL_REPEAT_NOTE.startswith(
        research._TAIL_REPEAT_NOTE_PREFIX)
    assert research._TAIL_REPEAT_NOTE_PREFIX
    src = _research_src()
    assert src.count("_TAIL_REPEAT_NOTE_PREFIX = ") == 1
    assert '_TAIL_REPEAT_NOTE.split(b"%")[0]' in src


def test_the_newest_line_survives_even_when_it_alone_exceeds_the_budget(tmp_path):
    """A tail of nothing is worse than a tail slightly over budget."""
    p = tmp_path / "wide.log"
    p.write_bytes(b"old\n" + b"y" * 400 + b"\n")
    out = research._tail_bytes(p, limit=50)
    assert out == b"y" * 400 + b"\n"


def test_a_tiny_chunk_size_still_reads_the_whole_file(tmp_path, monkeypatch):
    """One byte at a time is the smallest positive chunk, and it must still
    assemble whole lines across every boundary."""
    monkeypatch.setattr(research, "_TAIL_CHUNK_BYTES", 1)
    p = tmp_path / "tiny.log"
    p.write_bytes(b"a\nbb\nccc\n")
    assert research._tail_bytes(p, limit=1000) == b"a\nbb\nccc\n"


def test_the_step_cannot_be_zero(tmp_path):
    """⛔⛔ PINNED ON THE SOURCE, AND THAT IS THE ONLY BOUNDED WAY TO PIN IT.

    The clamp replaced an `if step <= 0: return` guard that could NEVER fire —
    the while condition already made `pos` and `scan_limit - scanned` at least 1
    — so the protection moved to `max(1, …)` where it can act.

    The first version of this test set `_TAIL_CHUNK_BYTES = 0` and called
    `_tail_bytes`. With the clamp present that passes; with the clamp REMOVED the
    walk subtracts zero forever, so the test HANGS rather than fails. A hang is
    not a failure: it cost the mutation harness a ten-minute timeout and got
    reported as a stale anchor instead of a kill. There is no in-process way to
    observe "this loop would never end", so the expression itself is the
    assertion — and a behavioural test at chunk size 1 covers the arithmetic."""
    src = code_only_deep(inspect.getsource(research._tail_lines_newest_first))
    assert "max(1, _TAIL_CHUNK_BYTES)" in src, (
        "the chunk-size clamp is gone; a chunk of 0 would spin the backward walk "
        "forever inside a user's support-bundle build")
    assert "if step <= 0" not in src, (
        "the dead guard is back — the while condition already excludes it")


def test_a_file_smaller_than_the_budget_comes_back_whole(tmp_path):
    p = tmp_path / "small.log"
    # ⚠ write_BYTES, not write_text: on Windows write_text translates
    # \n to \r\n, so the fixture would not hold the bytes this test
    # asserts on. The reader under test is byte-oriented by design.
    p.write_bytes(b"a\nb\nc\n")
    assert research._tail_bytes(p, limit=1_000) == b"a\nb\nc\n"


def test_a_file_with_no_trailing_newline_keeps_its_last_line(tmp_path):
    """⛔ The boundary the backward chunker is most likely to lose."""
    p = tmp_path / "nonl.log"
    p.write_bytes(b"first\nsecond\nlast-with-no-newline")
    out = research._tail_bytes(p, limit=1_000)
    assert b"last-with-no-newline" in out
    assert out.count(b"\n") == 3


def test_a_line_longer_than_one_chunk_survives(tmp_path, monkeypatch):
    """`partial` accumulates across chunks; a line longer than the chunk is the
    case that proves it does."""
    monkeypatch.setattr(research, "_TAIL_CHUNK_BYTES", 64)
    p = tmp_path / "long.log"
    huge = b"x" * 500
    p.write_bytes(b"head\n" + huge + b"\ntail\n")
    out = research._tail_bytes(p, limit=100_000)
    assert huge in out
    assert out.startswith(b"head\n") and out.endswith(b"tail\n")


def test_a_missing_file_is_empty_not_an_exception(tmp_path):
    assert research._tail_bytes(tmp_path / "nope.log") == b""


def test_the_scan_is_bounded_so_one_huge_file_cannot_hang_a_bundle(tmp_path):
    p = tmp_path / "wide.log"
    p.write_text("".join(f"row {i}\n" for i in range(50_000)), encoding="utf-8")
    stats: dict = {}
    research._tail_bytes(p, limit=100, stats=stats, scan_limit=4096)
    assert stats["scannedBytes"] <= 4096
    assert stats["reachedStart"] is False, (
        "a truncated scan must SAY it never reached the start, or a reader "
        "concludes the file begins where the tail begins")


def test_the_scan_cap_is_tied_to_the_rotation_threshold():
    """⭐ `_rotate_if_oversize` keeps a raw log under RAW_LOG_ROTATE_BYTES, so a
    scan cap equal to it can always reach the start of a file that has not
    rotated. Raising one without the other would silently leave part of a legal
    file unreachable."""
    assert research.TAIL_SCAN_MAX_BYTES == research.RAW_LOG_ROTATE_BYTES


def test_a_filtered_tail_admits_it_in_the_file_itself(tmp_path, monkeypatch):
    """⛔⛔ A FILTERED ARTIFACT THAT DOES NOT ADMIT IT IS A FALSE STATEMENT ABOUT
    THE MACHINE. A reader who opens `system/backend.log` and finds no health
    probes in five megabytes would conclude the probes stopped — a diagnosis,
    and a wrong one."""
    root = tmp_path / "logs"
    (root / "runs").mkdir(parents=True)
    (root / "sessions").mkdir()
    noise = '127.0.0.1:1 - "GET /api/health HTTP/1.1" 200 OK\n'
    (root / "backend.log").write_text(noise * 40 + "something real\n",
                                      encoding="utf-8")
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    dest = tmp_path / "b.zip"
    research._build_log_bundle(dest)
    with zipfile.ZipFile(dest) as zf:
        body = zf.read("system/backend.log").decode()
        collected = json.loads(zf.read("collected.json"))
    assert body.startswith("[bundle] backend.log:")
    assert "40 successful /api/health access lines removed" in body
    assert "something real" in body
    stats = collected["systemTailFilter"]["backend.log"]
    assert stats["dropped"] == 40
    assert stats["reachedStart"] is True


def test_an_unfiltered_tail_gets_no_header(tmp_path, monkeypatch):
    """⛔ A header on every tail would be a claim of filtering where none
    happened — and it would put our own text at the top of a clean log."""
    root = tmp_path / "logs"
    (root / "runs").mkdir(parents=True)
    (root / "sessions").mkdir()
    # ⚠ write_BYTES, not write_text: on Windows write_text translates
    # \n to \r\n, so the fixture would not hold the bytes this test
    # asserts on. The reader under test is byte-oriented by design.
    (root / "backend.log").write_bytes(b"clean\nlines\nonly\n")
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    dest = tmp_path / "b.zip"
    research._build_log_bundle(dest)
    with zipfile.ZipFile(dest) as zf:
        assert zf.read("system/backend.log") == b"clean\nlines\nonly\n"


# ══════════════════════════════════════════════════════════════════════════
#  7. Fix E1 — the mirror was unbounded (2,568,739 bytes, measured)
# ══════════════════════════════════════════════════════════════════════════

def test_the_mirror_is_bounded(monkeypatch, tmp_path):
    """⛔⛔ `_trim_spool` bounded the pending spool; NOTHING bounded this. A
    transparency file that grows forever is a disk-filler with a good motive."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setattr(tm, "MIRROR_MAX_BYTES", 4096)
    for i in range(600):
        tm._mirror({"seq": i, "pad": "x" * 40})
    size = tm.sent_log_path().stat().st_size
    assert size <= 4096 * 2, f"the mirror reached {size} bytes against a 4096 cap"


def test_the_mirror_drops_the_OLDEST_half(monkeypatch, tmp_path):
    """⭐ Matching `_trim_spool`, and for the same reason: the newest events
    describe whatever is going wrong right now."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setattr(tm, "MIRROR_MAX_BYTES", 2048)
    for i in range(400):
        tm._mirror({"seq": i, "pad": "y" * 40})
    body = tm.sent_log_path().read_text(encoding="utf-8")
    assert '"seq":399' in body, "the newest event was dropped"
    assert '"seq":0' not in body, "this is the head, not the tail"


def test_every_line_of_the_mirror_is_still_a_parseable_record(monkeypatch, tmp_path):
    """⛔ A trim that cut mid-line would leave an unparseable record in the one
    file whose whole job is to be readable."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setattr(tm, "MIRROR_MAX_BYTES", 1024)
    for i in range(300):
        tm._mirror({"seq": i, "pad": "z" * 30})
    for line in tm.sent_log_path().read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_the_mirror_never_gains_a_line_that_did_not_leave(monkeypatch, tmp_path):
    """⛔ THE DIFFERENCE FROM THE SPOOL. `_trim_spool` appends a
    TELEMETRY_DROPPED envelope; doing that here would put a record in "what left
    this machine" that never left. The drop is visible anyway — `seq` rises
    monotonically, so a gap at the head IS the record of it."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setattr(tm, "MIRROR_MAX_BYTES", 1024)
    for i in range(300):
        tm._mirror({"seq": i, "ev": 40})
    body = tm.sent_log_path().read_text(encoding="utf-8")
    assert "TELEMETRY_DROPPED" not in body
    assert str(int(tm.Ev.TELEMETRY_DROPPED)) not in [
        str(json.loads(x).get("ev")) for x in body.splitlines()]
    assert code_only_deep(inspect.getsource(tm._trim_mirror)).count(
        "keep.append") == 0


def test_the_common_path_does_not_read_the_whole_mirror():
    """`_trim_spool` reads and splits the entire file on EVERY event just to count
    its lines. Copying that here would put a megabyte-sized read in the path of
    every event a run emits — the append's own file position is the new size for
    free.

    ⛔⛔ FOUND BY MUTATION, AND IT WAS THIS TEST THAT WAS BROKEN. The first version
    used `code_only`, which strips `#` comments but NOT docstrings — and
    `_mirror`'s own docstring names the call it is asserting on, so replacing that
    call with a constant left the assertion passing. The function's prose was
    standing in for its code. `code_only_deep` is mandatory whenever a presence
    check could be satisfied by writing about the thing instead of doing it."""
    src = code_only_deep(inspect.getsource(tm._mirror))
    assert "fh.tell()" in src
    assert "read_text" not in src
    assert "splitlines" not in src


def test_the_mirror_holds_a_useful_number_of_events(monkeypatch, tmp_path):
    """⭐ THE CAP MEASURED AGAINST REAL ENVELOPES, so the constant is justified by
    a number nothing has to remember. A comment claiming "~6,000 events" would go
    stale the first time the envelope gained a field, and nothing would notice."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    for i in range(50):
        tm._mirror(tm._envelope({"ev": int(tm.Ev.PHASE_START),
                                 "d": {"phase": 1, "worker": 1}}))
    per_event = tm.sent_log_path().stat().st_size / 50
    assert tm.MIRROR_MAX_BYTES / per_event >= 2000, (
        f"the cap holds only {tm.MIRROR_MAX_BYTES / per_event:.0f} events at "
        f"{per_event:.0f} bytes each — too short a window to answer 'what left'")


def test_the_mirror_is_never_observed_half_written(monkeypatch, tmp_path):
    """⛔⛔ THIS FILE IS SHARED BY EVERY PROCESS, unlike the spool. A
    truncate-then-rewrite leaves a window where the mirror is a FRAGMENT — and a
    fragment of JSONL is unreadable rather than short. The rewrite must land
    atomically, and it must not leave its temp file behind."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setattr(tm, "MIRROR_MAX_BYTES", 2048)
    for i in range(400):
        tm._mirror({"seq": i, "pad": "w" * 40})
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["sent.log"], f"a temp file survived the trim: {names}"
    src = code_only_deep(inspect.getsource(tm._trim_mirror))
    assert "os.replace(" in src, "the rewrite is not atomic"
    assert "path.write_text" not in src, (
        "the mirror is written in place, so a reader can catch it mid-rewrite")
    # ⛔ FOUND BY MUTATION, and pinned on the SOURCE because it cannot be shown
    # from inside one process: without the pid, two workers trimming at the same
    # moment write the same temp name and one lands a file the other is still
    # writing — which is the half-written mirror `os.replace` was added to prevent,
    # arriving by a different route.
    assert "os.getpid()" in src, "the trim temp name is not per-process"


def test_a_failed_trim_does_not_leave_a_temp_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    p = tm.sent_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f'{{"seq":{i}}}\n' for i in range(20)), encoding="utf-8")

    def _boom(*a, **k):
        raise OSError("no")

    monkeypatch.setattr(tm.os, "replace", _boom)
    tm._trim_mirror(p)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["sent.log"]
    assert p.read_text(encoding="utf-8").count("\n") == 20, (
        "a failed trim damaged the mirror it could not replace")


def test_a_single_enormous_line_is_left_alone(monkeypatch, tmp_path):
    """Splitting the "oldest half" of one line would truncate a JSON record."""
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    p = tm.sent_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"one":"' + "q" * 5000 + '"}\n', encoding="utf-8")
    tm._trim_mirror(p)
    json.loads(p.read_text(encoding="utf-8").strip())


# ══════════════════════════════════════════════════════════════════════════
#  8. Fix E2 — Clear logs could not reach the telemetry directory
# ══════════════════════════════════════════════════════════════════════════

def _clear_fixture(tmp_path):
    root = tmp_path / "logs"
    (root / "runs" / "old").mkdir(parents=True)
    (root / "runs" / "old" / "run.log").write_text("x", encoding="utf-8")
    (root / "sessions").mkdir()
    (root / "sessions" / "doctor.log").write_text("x", encoding="utf-8")
    (root / "backend.log").write_text("x", encoding="utf-8")
    telemetry = tmp_path / "telemetry"
    telemetry.mkdir()
    (telemetry / "sent.log").write_text('{"seq":1}\n', encoding="utf-8")
    (telemetry / "pending-cli.jsonl").write_text('{"seq":2}\n', encoding="utf-8")
    (telemetry / "pending-w1.jsonl").write_text('{"seq":3}\n', encoding="utf-8")
    (telemetry / "pending-cli.sending.999.jsonl").write_text("{}\n", encoding="utf-8")
    return root, telemetry


def test_clear_logs_erases_the_local_record_of_what_was_sent(tmp_path, monkeypatch):
    """⛔⛔ MEASURED 2,568,739 BYTES SURVIVING A BUTTON WHOSE WHOLE JOB IS TO
    LEAVE NOTHING BEHIND. `telemetry.py` keeps its spool and its sent-mirror
    OUTSIDE `_logs_root()`, so the collector cannot reach them — and the
    collector-defined clear structurally could not see them either."""
    root, telemetry = _clear_fixture(tmp_path)
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    out = research._clear_local_logs(root=root, telemetry_root=telemetry)
    assert out["telemetry"] == 4
    assert out["failed"] == 0
    assert sorted(p.name for p in telemetry.iterdir()) == []


def test_the_clear_reports_the_telemetry_count_separately(tmp_path, monkeypatch):
    """A partial clear reported as a whole one is the same lie as a privacy
    button that says "cleared 4" while four files survive."""
    root, telemetry = _clear_fixture(tmp_path)
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    out = research._clear_local_logs(root=root, telemetry_root=telemetry)
    assert set(out) >= {"runs", "sessions", "tails", "bundles", "telemetry",
                        "kept", "failed"}
    src = _research_src()
    assert "telemetry={cleared['telemetry']}" in src, (
        "the count exists but the operator's log line never says it")


def test_the_clear_never_removes_a_directory_it_does_not_recognise(tmp_path, monkeypatch):
    """⛔ A sweep that rmtree's whatever it finds is
    `_bundle_source_is_allowed`'s nightmare one level over — a collector that
    can be pointed anywhere. Files by name, never the directory."""
    root, telemetry = _clear_fixture(tmp_path)
    keep = telemetry / "some-folder"
    keep.mkdir()
    (keep / "held.txt").write_text("mine", encoding="utf-8")
    (telemetry / "notes.txt").write_text("mine", encoding="utf-8")
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    research._clear_local_logs(root=root, telemetry_root=telemetry)
    assert (keep / "held.txt").read_text(encoding="utf-8") == "mine"
    assert (telemetry / "notes.txt").exists()
    # And structurally: the telemetry sweep selects files by NAME. A glob or an
    # rglob here is how "clear the logs" becomes "clear the directory".
    src = code_only_deep(inspect.getsource(research._clear_local_logs))
    sweep = src[src.index("tm_targets = []"):src.index("live = {")]
    assert "p.is_file()" in sweep
    assert "rmtree" not in sweep and "rglob" not in sweep


def test_a_missing_telemetry_directory_is_not_a_failure(tmp_path, monkeypatch):
    root, _ = _clear_fixture(tmp_path)
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    out = research._clear_local_logs(root=root,
                                    telemetry_root=tmp_path / "never-made")
    assert out["telemetry"] == 0
    assert out["failed"] == 0


def test_the_default_telemetry_root_is_the_one_telemetry_actually_uses(
        tmp_path, monkeypatch):
    """⛔⛔ FOUND BY MUTATION, AND THE FIRST VERSION OF THIS TEST COULD NOT SEE IT.
    It asserted `"tm.sent_log_path()" in src` — and swapping the default to
    `Path(base) / "telemetry"` leaves that string in the file anyway, because the
    filename comparison still uses it. A source-text presence check cannot see a
    changed EXPRESSION, only a deleted name.

    So this exercises the DEFAULT: no `telemetry_root`, and the file has to go.
    Two notions of where the spool lives is how a clear reports success against
    an empty directory nobody writes to."""
    root = tmp_path / "logs"
    (root / "runs").mkdir(parents=True)
    (root / "sessions").mkdir()
    real = tmp_path / "elsewhere" / "telemetry"
    real.mkdir(parents=True)
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(real))
    (real / "sent.log").write_text('{"seq":1}\n', encoding="utf-8")
    (real / "pending-cli.jsonl").write_text('{"seq":2}\n', encoding="utf-8")
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    out = research._clear_local_logs(root=root)
    assert out["telemetry"] == 2, (
        "the clear looked somewhere other than where telemetry.py writes")
    assert list(real.iterdir()) == []


def test_clear_still_leaves_the_collector_with_nothing_to_send(tmp_path, monkeypatch):
    """⭐ THE ORIGINAL INVARIANT, UNCHANGED. Proved by BUILDING a bundle
    afterwards rather than by re-reading a list — the new rule is
    `clear ⊇ what the collector reads`, so widening it must not narrow this."""
    root, telemetry = _clear_fixture(tmp_path)
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    research._clear_local_logs(root=root, telemetry_root=telemetry)
    dest = tmp_path / "after.zip"
    research._build_log_bundle(dest)
    with zipfile.ZipFile(dest) as zf:
        left = [n for n in zf.namelist()
                if n.startswith(("runs/", "sessions/", "system/"))]
    assert left == [], f"the collector still found {left}"


# ══════════════════════════════════════════════════════════════════════════
#  9. The bundle contract's silent fallback
# ══════════════════════════════════════════════════════════════════════════

def test_the_bundle_contract_fallback_matches_the_file_it_falls_back_from():
    """⛔ `bundle-contract.json` does NOT ship in the wheel — pyproject packs
    `scripts` as package-data and nothing else — so `_bundle_contract`'s
    "literal fallback" is what EVERY installed build actually reads. The values
    happen to agree today; nothing was checking. Editing the file without
    editing the fallback would change the slider's meaning on a source checkout
    and leave every wheel on the old numbers, silently, which is the exact
    two-repos-disagree failure the file was created to prevent."""
    src = inspect.getsource(research._bundle_contract)
    literal = src[src.index("return {", src.index("except Exception:")):]
    fallback = ast.literal_eval(literal[len("return "):literal.rindex("}") + 1])
    on_disk = json.loads(
        (Path(research.__file__).resolve().parent / "bundle-contract.json")
        .read_text(encoding="utf-8"))
    for key in fallback:
        assert fallback[key] == on_disk[key], (
            f"{key}: the wheel would read {fallback[key]!r} while a source "
            f"checkout reads {on_disk[key]!r}")


# ══════════════════════════════════════════════════════════════════════════
# 10. The wave did not quietly widen anything
# ══════════════════════════════════════════════════════════════════════════

def test_the_collector_allowlist_is_untouched():
    """⛔ Clearing more than the collector reads is safe — it only deletes the
    user's own data at their request. COLLECTING more is what the consent
    screen's promise is gated on, and this wave must not have touched it."""
    assert research._bundle_source_is_allowed(
        research._logs_root() / "runs" / "x" / "run.log") is True
    for outside in ("/etc/passwd", str(research._STATE_DIR / "keystore-audit.log"),
                    str(Path(research.tm.sent_log_path()))):
        assert research._bundle_source_is_allowed(outside) is False, outside


def test_the_telemetry_mirror_is_still_not_collected():
    """The mirror is now CLEARABLE but must stay UNCOLLECTED: it carries the
    install uuid and every research id this machine ever ran."""
    assert research._bundle_source_is_allowed(tm.sent_log_path()) is False

# ══════════════════════════════════════════════════════════════════════════
# 11. Dating a line in a multi-week log (owner ask, 2026-08-19)
# ══════════════════════════════════════════════════════════════════════════

def _fresh_date_stamp(monkeypatch, value=""):
    """Undo the suite-wide fixture that spends the marker, for tests that want it.

    ⛔ `tests/conftest.py` sets `_LOG_DATE_STAMPED` to today for EVERY test, because
    a module global set by the first `log()` call in a process would otherwise put
    one extra line into exactly one test's captured stdout — and which one depends
    on collection order, across the 26 files that capture output."""
    monkeypatch.setattr(research, "_LOG_DATE_STAMPED", value)


def test_the_first_line_of_a_process_is_dated(monkeypatch, capsys):
    """⛔⛔ THE MEASURED GAP: `log()` stamps TIME ONLY, so not one line in the
    44 MB `backend.log` on this machine could be dated from its own text — and
    that file spans 2026-07-19 → 08-05."""
    _fresh_date_stamp(monkeypatch)
    research.log("something happened")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert research.LOG_DATE_PREFIX in lines[0]
    assert re.search(r"\d{4}-\d{2}-\d{2}", lines[0]), lines[0]
    assert "something happened" in lines[1]


def test_the_marker_wears_the_same_format_as_every_other_line(monkeypatch, capsys):
    r"""⛔ This repo already fixed "four log formats in one stream" once. A marker
    that did not start with `[HH:MM:SS] [LEVEL] ` would bring it back through the
    fix for dating — and `grep '^\['` would stop seeing the whole file."""
    _fresh_date_stamp(monkeypatch)
    research.log("x")
    marker = capsys.readouterr().out.splitlines()[0]
    assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] \[INFO\] ", marker), marker


def test_the_marker_is_emitted_once_a_day_not_once_a_line(monkeypatch, capsys):
    """⭐ The whole reason it is a marker and not a wider timestamp: six more
    characters on every line is 15% of a 44 MB file."""
    _fresh_date_stamp(monkeypatch)
    for i in range(50):
        research.log(f"line {i}")
    out = capsys.readouterr().out
    assert out.count(research.LOG_DATE_PREFIX) == 1
    assert len(out.splitlines()) == 51


def test_a_midnight_rollover_gets_a_new_marker(monkeypatch, capsys):
    """The case the feature exists for: a serve process that runs for days."""
    _fresh_date_stamp(monkeypatch, "2026-08-18")
    research.log("after midnight")
    out = capsys.readouterr().out
    assert out.count(research.LOG_DATE_PREFIX) == 1
    assert "2026-08-18" not in out, "the marker announced the day that just ended"


def test_the_marker_reaches_the_per_run_folder_too(monkeypatch):
    """A run that starts before midnight and ends after it must be datable from
    its OWN log, not only from the machine tail."""
    src = code_only_deep(inspect.getsource(research.log))
    assert src.count("_log_write_through(") == 2, (
        "the marker is printed but not written through, so an armed run folder "
        "gets the undated half only")


def test_the_printed_line_format_is_unchanged():
    """⛔ The one thing this fix may not do. `_uvicorn_log_config`, the session
    capture and the run capture all share `[%H:%M:%S] [LEVEL] msg`."""
    src = code_only_deep(inspect.getsource(research.log))
    assert 'line = f"[{ts}] [{level}] {msg}"' in src
    # …and only ONE clock read, so the date costs no second strftime on a path
    # called thousands of times a run.
    assert src.count("datetime.now()") == 1


def test_the_marker_carries_no_lock_and_says_why():
    """⭐ A deliberate race: two threads crossing midnight can print the marker
    twice. That costs one duplicate line; a lock would cost every log call."""
    src = code_only_deep(inspect.getsource(research._log_date_marker))
    assert "Lock" not in src and "with " not in src


def test_a_tail_says_which_dates_its_markers_cover(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    (root / "runs").mkdir(parents=True)
    (root / "sessions").mkdir()
    noise = '127.0.0.1:1 - "GET /api/health HTTP/1.1" 200 OK\n'
    (root / "backend.log").write_text(
        f"[00:00:01] [INFO] {research.LOG_DATE_PREFIX} 2026-08-01\n"
        + noise * 5
        + "[10:00:00] [INFO] real work\n"
        + f"[00:00:01] [INFO] {research.LOG_DATE_PREFIX} 2026-08-02\n"
        + "[11:00:00] [INFO] more real work\n", encoding="utf-8")
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    dest = tmp_path / "b.zip"
    research._build_log_bundle(dest)
    with zipfile.ZipFile(dest) as zf:
        body = zf.read("system/backend.log").decode()
        collected = json.loads(zf.read("collected.json"))
    assert "2026-08-01 … 2026-08-02" in body, body.splitlines()[0]
    stats = collected["systemTailFilter"]["backend.log"]
    assert stats["dateOldest"] == "2026-08-01"
    assert stats["dateNewest"] == "2026-08-02"


def test_a_tail_with_no_markers_falls_back_to_the_files_own_timestamp(tmp_path):
    """⛔⛔ THE ARCHIVE LOSES THIS AND NOTHING ELSE CARRIES IT. Tails go in via
    `writestr`, which stamps when the BUNDLE was built — so `system/backend.log`
    from a machine frozen weeks ago wears today's date. Every one of the owner's
    four raw logs is in exactly this state: written before markers existed."""
    p = tmp_path / "old.log"
    p.write_text("[10:00:00] [INFO] undatable\n", encoding="utf-8")
    os.utime(p, (1_754_400_000, 1_754_400_000))
    stats: dict = {}
    research._tail_bytes(p, stats=stats)
    assert stats["lastWrittenUtc"].startswith("2025-08-05"), stats["lastWrittenUtc"]
    text = research._tail_dating_text(stats)
    assert "no [date] lines" in text
    assert stats["lastWrittenUtc"] in text
    assert "undated" in text


def test_the_dating_text_never_claims_a_date_it_does_not_have():
    """⛔ The polarity. A sentence that reads confidently on an undatable file is
    worse than one that says it cannot tell."""
    text = research._tail_dating_text({})
    assert "unknown" in text
    assert "…" not in text


def test_the_header_never_names_a_date_the_body_does_not_contain(tmp_path):
    """⛔⛔ FOUND ON A FINAL READ. The header says "the [date] lines BELOW cover
    X … Y" — so if the range were collected during the walk, the budget trim could
    remove the oldest marker and leave the header naming a date the reader cannot
    find. Reading the range off the FINAL list makes the claim true by
    construction, and this sweeps every limit to prove it."""
    pre = research.LOG_DATE_PREFIX
    p = tmp_path / "dated.log"
    p.write_bytes(b"".join(
        f"[00:00:01] [INFO] {pre} 2026-08-0{d}\n"
        f"[1{d}:00:00] [INFO] day {d} work here\n".encode() for d in (1, 2, 3)))
    size = p.stat().st_size
    seen = False
    for limit in range(1, size + 60):
        stats: dict = {}
        out = research._tail_bytes(p, limit=limit, stats=stats)
        for key in ("dateOldest", "dateNewest"):
            if stats.get(key):
                seen = True
                assert stats[key].encode("ascii") in out, (
                    f"limit={limit}: the header names {stats[key]} but that date "
                    f"is not in the tail it describes")
    assert seen, "no limit produced a date range at all, so this proved nothing"


def test_the_marker_pattern_is_derived_from_the_prefix_the_writer_uses():
    """⛔ Two spellings and the reader silently stops finding what the writer is
    still emitting."""
    src = _research_src()
    assert src.count("_LOG_DATE_MARKER_RE = re.compile(") == 1
    assert "re.escape(LOG_DATE_PREFIX.encode" in src
    assert research._LOG_DATE_MARKER_RE.search(
        b"[00:00:01] [INFO] " + research.LOG_DATE_PREFIX.encode() + b" 2026-08-19")


# ══════════════════════════════════════════════════════════════════════════
# 12. The hand-over line stops naming the worst file on the disk
# ══════════════════════════════════════════════════════════════════════════

def test_the_hand_over_line_names_the_command_and_no_path():
    """⛔⛔ OWNER DECISION 2026-08-19. `backend.log` is 44 MB, is the one log with
    no dates in it, and contains none of the per-run folders or session logs —
    while `--send-logs`, one clause earlier, writes ~600 KB with all three."""
    line = research._doctor_share_logs_line()
    assert "--send-logs" in line
    assert "backend.log" not in line
    assert str(research._STATE_DIR) not in line
    assert "Report Bug" in line, "the no-terminal route is what made dropping it safe"


def test_dropping_the_route_left_the_file_still_offered():
    """⭐ By the command, not by a guessed path: it writes the bundle FIRST and
    prints where it put it whether or not the upload lands."""
    src = code_only_deep(inspect.getsource(research.cmd_send_logs))
    assert "Bundle written" in src
    assert "can be attached to an email" in src

# ── the suite-wide fixture, proved by a PAIR ─────────────────────────────
# ⛔⛔ THE ORDER OF THESE TWO IS LOAD-BEARING, and mutation is why. Deleting the
# conftest fixture SURVIVED at first: every date test above sets the stamp itself,
# so by the time anything else ran the marker was already spent and nothing
# noticed the fixture was gone. A guard whose protection is supplied incidentally
# by its neighbours is not a guard.
#
# So the first test below pollutes the global DELIBERATELY, and without
# monkeypatch — a self-undoing patch could never show that something else repairs
# it. The second asserts the repair happened. Reorder them and the second fails
# loudly rather than passing hollowly.

def test_the_date_stamp_is_polluted_on_purpose_for_the_next_test():
    """Sets a stamp no clock will ever produce. Asserts nothing: its whole job is
    to leave the process dirty for the test immediately below."""
    research._LOG_DATE_STAMPED = "1999-01-01"


def test_the_suite_fixture_repairs_a_polluted_date_stamp():
    """⛔ Without `_the_date_marker_is_already_spent` in conftest, this sees
    1999-01-01 — i.e. the next `log()` call anywhere would print a marker into
    whichever test happened to be capturing stdout at the time."""
    today = datetime.now().strftime("%Y-%m-%d")
    assert research._LOG_DATE_STAMPED == today, (
        "the suite-wide date-marker fixture did not run, so `log()` will emit a "
        "[date] line into whichever test captures stdout first — an order-"
        "dependent failure across the 26 files that capture output. (If this "
        "passes only because the test above was reordered away, that is the same "
        "bug in the test.)")
    # Leave the process as the fixture found it, so nothing downstream inherits
    # the sentinel once monkeypatch unwinds this fixture at teardown.
    research._LOG_DATE_STAMPED = today

