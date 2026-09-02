"""⛔⛔⛔ STRETCH 5E — WHAT THE MACHINE TELLS YOU, AND WHAT IT NEVER TELLS YOU.

Measured 2026-09-01, before a line was changed.

⛔⛔⛔ THE RESEARCH COMPUTER HAD EXACTLY ONE SERVER-SIDE NOTIFY ASK, and it was
gated to two event types, both of them good news. A run waiting on a sign-in at
02:00, a quota exhaustion, a stop at the five-hour ceiling, a backend restart
mid-run — every one written to Firestore and to nothing else, while the settings
screen promised "a research finished, hit an error, went offline mid-run, or
needs you". Only "finished" had a sender.

⭐ A run started VIA THE AGENT was already covered — a watcher polls every five
minutes and messages the person, and the tracker did not know that. The gap was
runs started in the web app, which had nothing at all.

⛔⛔ THE PAUSE THE WATCHDOG CANNOT SEE. `wait_if_paused` had no timeout — the
only wait in the pipeline with no bound — and the worker watchdog EXCLUDES paused
time from its active-time ceiling on purpose. So a run parked there accrued
nothing, tripped nothing, and sat forever having spoken once.

⛔⛔ THE OUTAGE NOTICE THAT COULD NOT BE SENT DURING AN OUTAGE. The telemetry
flush sat inside `if _firebase_db is not None:`, so FIRESTORE_OUTAGE_STARTED —
the one event whose entire purpose is to report that Firestore is unreachable —
was unsendable for exactly as long as the thing it describes was true. Telemetry
does not use Firestore; it POSTs to the web app over HTTPS.

⛔⛔ AND THE SWEEP THAT RE-DATED THE DEAD. Owner-reported the same day: the agent
announced that a research "stopped early" for a run from weeks earlier. The
stuck-run sweep stamps `updatedAt = now` with no age bound, and `updatedAt` is
the only timestamp the run reaches the watcher on — so Reset Backend made a
month-old corpse look freshly finished.
"""
import inspect
import re

import research


def _src(fn) -> str:
    """Source with comments stripped — a guard must read the CODE.

    ⛔ `inspect.getsource` includes comments, so a naive `in` check passes on a
    comment that merely QUOTES the thing it is checking for. That mistake has
    been made in this repo before.
    """
    out = []
    for line in inspect.getsource(fn).split("\n"):
        stripped = re.sub(r"(?<!:)#.*$", "", line)
        out.append(stripped)
    return "\n".join(out)


# ── The sender the machine never had ────────────────────────────────────────

def test_the_gate_is_the_cards_class_not_its_event_name():
    """⛔⛔⛔ THE MISS CROSS-VERIFY FOUND, and it defeated the whole point.

    My first gate keyed on `event_type in ("pipeline_error", "pipeline_stopped")`.
    But `emit_decision` takes an `event_name` override, and EVERY blocker that
    strands a run overnight uses one — `login_required`,
    `human_verification_required`, `manual_brief_required`. So the 02:00 sign-in
    the comment names as the thing being fixed matched nothing and was not sent.

    `recoverability == "blocker"` is the field the catalog already maintains for
    exactly this question, and it cannot be defeated by an event_name override.
    """
    src = _src(research.emit_event)
    assert 'data.get("recoverability") == "blocker"' in src
    assert '"pipeline_error", "pipeline_stopped"' not in src


def test_the_seven_blocking_intents_are_the_ones_that_wait_on_a_person():
    """The catalog's own answer to "who must the person unblock?"."""
    blockers = {k for k, v in research.ALERT_INTENTS.items() if v["class"] == "blocker"}
    assert {"login_required", "manual_brief", "cua_unavailable",
            "env_missing_key", "hv_solvable", "pro_required"} <= blockers
    # ⛔ …and the self-healing ones are NOT in it. Paging somebody for a card
    # that retries itself is how they mute the category and lose the real ones.
    for recoverable in ("agent_link_failed", "phase_error", "agent_stuck", "chat_mode"):
        assert research.ALERT_INTENTS[recoverable]["class"] != "blocker"


def test_quiet_no_longer_silences_a_blocker():
    """⛔⛔ `quiet` means "do not paint the tile red for a phase that was never
    reached" — its own comment says the Retry banner still fires. Excluding it
    silenced precisely the preflight blockers that strand a run before it
    starts."""
    src = _src(research.emit_event)
    gate = src[src.index("_notify_ok = bool(_emitted_seq) and ("):src.index("if _notify_ok:")]
    assert 'quiet' not in gate
    assert 'actions' not in gate


def test_a_stop_the_person_pressed_is_not_announced():
    """⛔⛔ Every `pipeline_stopped` emit site is a stop the PERSON asked for
    (`user_stop_*`). Notifying on it means pushing "Your research stopped" to
    somebody who has just pressed Stop — which the completion notice already
    refuses to do, in writing, for the same reason."""
    src = _src(research.emit_event)
    gate = src[src.index("_notify_ok = bool(_emitted_seq) and ("):src.index("if _notify_ok:")]
    assert "pipeline_stopped" not in gate


def test_a_blocker_is_not_held_to_the_phase_range():
    """⛔ One raised in preflight is exactly the kind that strands a run
    overnight, so the 1..5 clause must stay on the TERMINAL branch only."""
    src = _src(research.emit_event)
    cond = src[src.index("_notify_ok = bool(_emitted_seq) and ("):src.index("if _notify_ok:")]
    split = cond.index('or data.get("recoverability")')
    assert "1 <= phase <= 5" in cond[:split]
    assert "1 <= phase <= 5" not in cond[split:]


def test_the_terminal_gate_is_unchanged():
    """⛔ The fix must not cost the notices that already worked."""
    src = _src(research.emit_event)
    assert '"phase_complete", "phase_skipped"' in src
    assert "_post_fe_phase_notice(" in src


def test_a_failed_write_is_still_never_announced():
    src = _src(research.emit_event)
    assert "_notify_ok = bool(_emitted_seq) and (" in src


def test_the_stale_claim_about_phase_four_is_gone():
    """The comment said "Phases 4 and 5 are not here"; the gate is 1..5 and the
    resume path really does emit phase_complete on phase 4.

    ⛔⛔ MY FIRST VERSION OF THIS TEST FAILED ON MY OWN CORRECTION, because the
    correction QUOTES the sentence it is retracting — the same trap that bit
    this repo in 5D. A flat "the phrase is absent" check cannot tell a claim
    from a retraction of it, so this requires every occurrence to sit inside one.
    """
    raw = inspect.getsource(research.emit_event)
    claim = "Phases 4 and 5 are not here"
    lines = raw.split("\n")
    hits = [i for i, ln in enumerate(lines) if claim in ln]
    assert hits, "the retraction itself has gone missing"
    for i in hits:
        window = " ".join(lines[i:i + 4])
        assert "ALREADY WRONG" in window, (
            f"line {i} states the claim without retracting it: {lines[i]!r}")


# ── The pause with no bound ─────────────────────────────────────────────────

def test_the_pause_is_bounded():
    """⛔⛔ It had NO timeout, and the watchdog is blind to this state."""
    assert research.PAUSE_MAX_WAIT_S == 86400.0
    src = _src(research.PipelineControls.wait_if_paused)
    assert "timeout=PAUSE_HEARTBEAT_S" in src
    assert "PAUSE_MAX_WAIT_S" in src


def test_the_pause_says_so_while_it_waits():
    """It spoke exactly once and then went silent for as long as the pause
    lasted, which for an unanswered blocker was forever."""
    src = _src(research.PipelineControls.wait_if_paused)
    assert "still waiting on" in src
    assert research.PAUSE_HEARTBEAT_S <= 900.0


def test_the_bound_ends_the_wait_the_only_way_callers_handle():
    """All sixteen callers ignore the return value, so the bound has to end it
    through the stop path, which every one of them already handles."""
    src = _src(research.PipelineControls.wait_if_paused)
    assert "self.request_stop()" in src


def test_the_heartbeat_is_far_below_the_bound():
    """A heartbeat at or above the bound speaks once and then gives up, which
    is the silence being fixed."""
    assert research.PAUSE_HEARTBEAT_S * 10 <= research.PAUSE_MAX_WAIT_S


# ── The outage notice that could not be sent during an outage ───────────────

def test_the_telemetry_flush_is_not_behind_the_thing_it_reports_on():
    """⛔⛔ One branch of indentation. FIRESTORE_OUTAGE_STARTED could not be
    flushed for exactly as long as the outage it describes was happening."""
    src = _src(research._firebase_reconnect_loop)
    flush = src.index("tm.flush_in_background()")
    branch = src.index("if _firebase_db is not None:")
    assert flush < branch, "the flush must run BEFORE the Firestore branch"


def test_the_flush_still_runs_on_every_worker():
    """The worker-1 heartbeat loop is gated; a worker-2 spool anchored there
    would never go out at all."""
    src = _src(research._firebase_reconnect_loop)
    head = src[:src.index("tm.flush_in_background()")]
    assert "WORKER_ID == 1" not in head


# ── The sweep that re-dated the dead ────────────────────────────────────────

class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = self
        self.applied = None

    def to_dict(self):
        return dict(self._data)

    def update(self, patch):
        self.applied = patch


class _Q:
    def __init__(self, snaps):
        self._snaps = snaps

    def where(self, *a, **k):
        return self

    def stream(self):
        return iter(self._snaps)


class _Col:
    def __init__(self, snaps):
        self._snaps = snaps

    def document(self, _uid):
        return self

    def collection(self, _name):
        return _Q(self._snaps)

    def where(self, *a, **k):
        return _Q(self._snaps)


class _DB:
    def __init__(self, snaps):
        self._col = _Col(snaps)

    def collection(self, _name):
        return self._col

    def document(self, _uid):
        return self._col


def _sweep(snaps, **kw):
    return research._sweep_stuck_research_docs(
        _DB(snaps), "owner", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend", **kw)


NOW_MS = None


def _now_ms():
    import time
    return int(time.time() * 1000)


def test_an_ancient_run_is_swept_but_NOT_re_dated():
    """⛔⛔ THE OWNER'S REPORT, and the shape of the repair cross-verify forced.

    My first version SKIPPED old docs entirely — which made Reset Backend and
    Unpair permanent no-ops for exactly the runs a person is trying to clear,
    while both callers went on reporting "no stale runs found".

    The defect was never the sweeping. It was the RE-DATING: `updatedAt` is the
    only timestamp the run reaches the agent watcher on, so bumping it made a
    month-old corpse look freshly finished and it was announced as having
    "stopped early". So clean the run AND leave that one field alone.
    """
    was = _now_ms() - 30 * 24 * 60 * 60 * 1000
    old = _Snap("rid-old", {"status": "ongoing", "deviceId": "dev-1", "updatedAt": was})
    n, fail = _sweep([old], max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert (n, fail) == (1, 0), "the run must still be cleaned"
    assert old.applied["status"] == "stopped"
    assert old.applied["updatedAt"] == was, "re-dating it is the whole defect"


def test_reset_backend_is_never_a_no_op():
    """⛔ The over-correction: a bound that leaves a person unable to clear the
    very runs they pressed the button for."""
    docs = [
        _Snap("recent", {"status": "ongoing", "deviceId": "dev-1",
                         "updatedAt": _now_ms() - 60_000}),
        _Snap("ancient", {"status": "queued", "deviceId": "dev-1",
                          "updatedAt": _now_ms() - 400 * 24 * 60 * 60 * 1000}),
    ]
    n, fail = _sweep(docs, max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert (n, fail) == (2, 0)
    assert all(d.applied["status"] == "stopped" for d in docs)


def test_a_recent_stuck_run_is_still_swept():
    """⛔ The over-correction: a bound that stops the sweep doing its job."""
    fresh = _Snap("rid-new", {
        "status": "paused_backend_restart", "deviceId": "dev-1",
        "updatedAt": _now_ms() - 60_000,
    })
    n, fail = _sweep([fresh], max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert (n, fail) == (1, 0)
    assert fresh.applied["status"] == "stopped"


def test_a_doc_with_no_timestamp_still_sweeps_and_still_gets_one():
    """⛔ Unknown age is not old age — and every one of the sweep's own existing
    fixtures is timestamp-free, so the opposite reading breaks all of them.

    ⛔⛔ AND IT MUST STILL GET A REAL TIMESTAMP. Treating "no timestamp" as
    ancient freezes `updatedAt` to the value that was not there — writing None
    over the field every listing orders by. Mutation found this; asserting only
    the sweep COUNT could not see it.
    """
    bare = _Snap("rid-bare", {"status": "ongoing", "deviceId": "dev-1"})
    n, fail = _sweep([bare], max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert (n, fail) == (1, 0)
    assert isinstance(bare.applied["updatedAt"], int)
    assert bare.applied["updatedAt"] > 0


def test_the_pause_bound_unblinds_the_watchdog(monkeypatch):
    """⛔⛔ The worker watchdog EXCLUDES paused time from its active-time ceiling
    by design. Giving up on a pause without clearing the flag would leave the
    watchdog blind for the rest of the process — the run stopping while the one
    backstop that could catch anything after it still saw "paused"."""
    src = _src(research.PipelineControls.wait_if_paused)
    give_up = src[src.index("if _paused_for >= PAUSE_MAX_WAIT_S:"):]
    clear = give_up.index("self.pause_event.clear()")
    stop = give_up.index("self.request_stop()")
    assert clear < stop, "the flag must be cleared before the stop is requested"


def test_stopped_at_is_when_the_run_died_not_when_we_noticed():
    """⛔⛔ `stoppedAt` was `now` for a run that died a week ago. It is the field
    anything asking "when did it end?" should be reading."""
    died = _now_ms() - 3 * 24 * 60 * 60 * 1000
    snap = _Snap("rid", {"status": "ongoing", "deviceId": "dev-1", "updatedAt": died})
    n, _ = _sweep([snap], max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert n == 1
    assert snap.applied["stoppedAt"] == died
    assert snap.applied["updatedAt"] > died


def test_the_default_is_unbounded_so_direct_callers_are_unchanged():
    """The bound is opt-in at the wrapper; the raw function keeps its contract."""
    old = _Snap("rid-old", {
        "status": "ongoing", "deviceId": "dev-1",
        "updatedAt": _now_ms() - 365 * 24 * 60 * 60 * 1000,
    })
    n, _ = _sweep([old])
    assert n == 1


def test_the_wrapper_passes_the_bound():
    """⛔⛔ PINNED AT THE CALLER. The bound is a parameter with a permissive
    default, so a rule that is never passed is a rule that does nothing — and
    every unit test of the sweep itself would still pass."""
    src = _src(research._sweep_stuck_research_docs_for_device)
    assert "max_age_ms=SWEEP_MAX_AGE_MS" in src


def test_the_bound_is_well_past_any_real_run():
    """The active-time ceiling is five hours; the bound must not be able to
    strand a run that is merely slow."""
    assert research.SWEEP_MAX_AGE_MS >= 24 * 60 * 60 * 1000
    assert research.SWEEP_MAX_AGE_MS <= 30 * 24 * 60 * 60 * 1000


def test_the_skip_is_said_out_loud(monkeypatch):
    """A silent skip is how a bound becomes the next mystery.

    ⛔⛔ BEHAVIOURAL, and mutation is what forced that. The source version of
    this test asserted the variable and the message were PRESENT — and making
    the branch unreachable (`if False:`) leaves both present, so the mutant
    survived. A guard satisfied by dead code is the exact defect this repo keeps
    re-finding; the only honest question is whether the line actually comes out.
    """
    said = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: said.append(str(msg)))
    old = _Snap("rid-old", {
        "status": "ongoing", "deviceId": "dev-1",
        "updatedAt": _now_ms() - 30 * 24 * 60 * 60 * 1000,
    })
    _sweep([old], max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert any("WITHOUT bumping updatedAt" in m for m in said), said


def test_nothing_is_said_when_nothing_was_skipped(monkeypatch):
    """⛔ The other half — a line on every ordinary sweep is noise, and noise is
    how the one that matters gets skipped over."""
    said = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: said.append(str(msg)))
    fresh = _Snap("rid", {"status": "ongoing", "deviceId": "dev-1",
                          "updatedAt": _now_ms() - 60_000})
    _sweep([fresh], max_age_ms=research.SWEEP_MAX_AGE_MS)
    assert not any("WITHOUT bumping updatedAt" in m for m in said), said
