"""Wave 2 step 9 — where the content-free tier is actually wired in.

⛔⛔ THE THREE CANNOT-FIRE TRAPS THIS FILE EXISTS TO HOLD SHUT:

  1. THE OUTAGE EDGE. `_mark_firestore_down` is called on EVERY down tick — 4,921
     times in the measured incident. An emit on the call rather than the
     transition floods the rate limit and evicts the pairing events that explain
     the outage. Exactly one started, exactly one ended, per outage.
  2. THE TAP'S PLACEMENT. Behind `if not _tracks_dir: return`, the mirror drops
     every event from a run whose Firestore setup is the thing that failed — and
     absence reads as health.
  3. THE EVENT NAME. `emit_event("fail_phase")` occurs ZERO times in this file;
     phase failures ride `emit_decision`, whose default event name is
     `pipeline_error`. Mapping the obvious name captures no failures at all.

⭐ And the literal-tuple pin: the tap forwards the event, the phase number, an
agent mapped onto an enum, and the id. `**data` is structurally never passed,
because "temporarily" adding one field is how free text re-enters a content-free
path.
"""
import inspect
import re

import pytest

from conftest import code_only_deep

import research
import telemetry as tm


_REAL_TM_EMIT = tm.tm_emit


@pytest.fixture(autouse=True)
def _capture(monkeypatch, tmp_path):
    """Record every emit instead of spooling it.

    `_REAL_TM_EMIT` is kept above so the one end-to-end test can put the real
    serializer back — asserting against a recorder proves the mapping and nothing
    about whether an event can actually be written."""
    seen = []
    monkeypatch.setattr(tm, "tm_emit",
                        lambda event, **fields: seen.append((event, fields)) or True)
    monkeypatch.setattr(research.tm, "flush_in_background", lambda *a, **k: None)
    research._RUN_LOG_SINKS.clear()
    yield seen
    research._RUN_LOG_SINKS.clear()


def _events(seen):
    return [e for e, _f in seen]


# ══ 1. the outage edge ═════════════════════════════════════════════════
def test_mark_mark_clear_clear_produces_exactly_one_pair(_capture, monkeypatch):
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    research._mark_firestore_down(now=1000.0)
    research._mark_firestore_down(now=1005.0)
    research._clear_firestore_down()
    research._clear_firestore_down()
    events = _events(_capture)
    assert events.count(tm.Ev.FIRESTORE_OUTAGE_STARTED) == 1, events
    assert events.count(tm.Ev.FIRESTORE_OUTAGE_ENDED) == 1, events


def test_a_second_outage_gets_its_own_pair(_capture, monkeypatch):
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    for _ in range(2):
        research._mark_firestore_down(now=1000.0)
        research._clear_firestore_down()
    events = _events(_capture)
    assert events.count(tm.Ev.FIRESTORE_OUTAGE_STARTED) == 2
    assert events.count(tm.Ev.FIRESTORE_OUTAGE_ENDED) == 2


def test_clearing_a_healthy_client_says_nothing(_capture, monkeypatch):
    """⛔ `_clear_firestore_down` runs at the one place a client is built, which
    is every reconnect attempt AND every boot. An unconditional emit there would
    report an outage that never happened."""
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    research._clear_firestore_down()
    assert _events(_capture) == []


def test_the_outage_reports_how_long_it_lasted(_capture, monkeypatch):
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    import time as _t
    research._mark_firestore_down(now=_t.time() - 42.0)
    research._clear_firestore_down()
    ended = [f for e, f in _capture if e is tm.Ev.FIRESTORE_OUTAGE_ENDED][0]
    assert 41_000 <= ended["duration_ms"] <= 44_000, ended


def test_the_outage_emit_claims_no_cause_it_cannot_know(_capture, monkeypatch):
    """⛔⛔ FOUND BY THIS FILE. The first draft read a global that does not exist,
    which would have raised a NameError on the ONE code path that runs only while
    the product is already broken. At mark time nothing knows WHY the client went
    away — the doctor's network verdict is what names DNS."""
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    monkeypatch.setattr(research, "_firebase_down_reason", None, raising=False)
    research._mark_firestore_down(now=1000.0)
    started = [f for e, f in _capture if e is tm.Ev.FIRESTORE_OUTAGE_STARTED][0]
    assert started["error_class"] is None, started


def test_a_revoked_token_IS_named_because_that_one_is_known(_capture, monkeypatch):
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    monkeypatch.setattr(research, "_firebase_down_reason", "revoked", raising=False)
    research._mark_firestore_down(now=1000.0)
    started = [f for e, f in _capture if e is tm.Ev.FIRESTORE_OUTAGE_STARTED][0]
    assert started["error_class"] is tm.ErrorClass.AUTH_REVOKED


def test_the_outage_path_survives_a_missing_global(monkeypatch):
    """The NameError above was only reachable because the name was read directly.
    `globals().get` is what makes a missing one a None rather than a crash."""
    monkeypatch.setattr(research, "_firestore_down_since_ts", None, raising=False)
    monkeypatch.delattr(research, "_firebase_down_reason", raising=False)
    research._mark_firestore_down(now=1000.0)  # must not raise
    research._clear_firestore_down()


def test_the_emit_is_inside_the_edge_branch():
    """A source pin as well as a behavioural one: the behaviour is only correct
    because the call sits inside the `is None` branch."""
    src = code_only_deep(research._mark_firestore_down)
    i = src.index("if _firestore_down_since_ts is None:")
    assert "FIRESTORE_OUTAGE_STARTED" in src[i:], (
        "the emit escaped the edge branch — 4,921 events per incident")


# ══ 2. the tap, above the guard ════════════════════════════════════════
def test_the_tap_fires_with_no_firestore_run(_capture, monkeypatch):
    monkeypatch.setattr(research, "_tracks_dir", None)
    research.emit_event("phase_start", phase=2, agent="claude")
    assert tm.Ev.PHASE_START in _events(_capture)


def test_the_tap_forwards_a_literal_tuple(_capture, monkeypatch):
    """⛔⛔ THE SET IS PINNED. "Temporarily" forwarding one more field is how free
    text re-enters a content-free path."""
    monkeypatch.setattr(research, "_tracks_dir", None)
    research.emit_event("phase_complete", phase=3, agent="chatgpt",
                        durationSec=12, detail="KALKI-2898-AD-SENTINEL")
    fields = [f for e, f in _capture if e is tm.Ev.PHASE_COMPLETE][0]
    assert set(fields) == {"phase", "platform"}, fields
    assert fields["phase"] == 3
    assert fields["platform"] is tm.Platform.CHATGPT


def test_a_topic_through_data_is_byte_absent_from_the_tap(_capture, monkeypatch):
    monkeypatch.setattr(research, "_tracks_dir", None)
    sentinel = "KALKI-2898-AD-SENTINEL"
    research.emit_event("phase_start", phase=1, topic=sentinel, detail=sentinel)
    assert sentinel not in repr(_capture)


def test_the_run_id_is_taken_from_the_armed_sink_not_from_data(_capture, monkeypatch):
    monkeypatch.setattr(research, "_tracks_dir", None)
    with research._RunLogCapture(research_id="chat_1755500000000_7"):
        _capture.clear()
        research.emit_event("phase_start", phase=1)
    fields = [f for e, f in _capture if e is tm.Ev.PHASE_START][0]
    assert fields["research_id"] == "chat_1755500000000_7"


def test_pipeline_error_is_the_mapped_name_and_fail_phase_does_not_exist():
    """⛔⛔ MEASURED. `emit_event("fail_phase")` occurs ZERO times in this file —
    phase failures ride `emit_decision`, whose default event name is
    `pipeline_error`. Mapping the obvious name would have captured no failures at
    all, and absence reads as health."""
    assert "pipeline_error" in research._TM_EVENT_MAP
    assert "fail_phase" not in research._TM_EVENT_MAP
    src = code_only_deep(research)
    assert 'emit_event("fail_phase"' not in src
    assert "fail_phase" not in research._TM_EVENT_MAP


def test_driving_a_phase_failure_end_to_end_serializes_a_tier1_error(monkeypatch):
    """The real path: `emit_decision` defaults to `pipeline_error`, and that has
    to come out the other end as a serialized event, not merely as a mapping."""
    monkeypatch.setattr(research, "_tracks_dir", None)
    landed = []
    monkeypatch.setattr(tm, "_spool", lambda body, worker=None: landed.append(body) or True)
    monkeypatch.setattr(tm, "tm_emit", _REAL_TM_EMIT)
    research.emit_event("pipeline_error", phase=2, agent="claude")
    assert landed, "no tier-1 event reached the spool"
    assert landed[0]["ev"] == int(tm.Ev.PIPELINE_ERROR)
    assert landed[0]["d"]["phase"] == 2
    assert landed[0]["d"]["platform"] == int(tm.Platform.CLAUDE)


def test_an_unmapped_event_is_silent_rather_than_guessed(_capture, monkeypatch):
    monkeypatch.setattr(research, "_tracks_dir", None)
    research.emit_event("phase_narration", phase=2)
    assert _events(_capture) == []


def test_an_unknown_agent_becomes_OTHER_rather_than_reaching_the_wire(_capture,
                                                                     monkeypatch):
    """⛔ `normalize_agent_key` passes through anything it does not recognise."""
    monkeypatch.setattr(research, "_tracks_dir", None)
    research.emit_event("phase_start", phase=1, agent="some-new-platform-2027")
    fields = [f for e, f in _capture if e is tm.Ev.PHASE_START][0]
    assert fields["platform"] is tm.Platform.OTHER


# ══ 3. the run lifecycle ═══════════════════════════════════════════════
def test_a_run_reports_started_and_finished(_capture):
    with research._RunLogCapture(research_id="chat_1755500000000_1"):
        pass
    events = _events(_capture)
    assert events.count(tm.Ev.RUN_STARTED) == 1
    assert events.count(tm.Ev.RUN_FINISHED) == 1


def test_the_outcome_is_named_rather_than_left_unknown(_capture):
    cap = research._RunLogCapture(research_id="chat_1755500000000_2")
    with pytest.raises(ValueError):
        with cap:
            raise ValueError("nope")
    finished = [f for e, f in _capture if e is tm.Ev.RUN_FINISHED][0]
    assert finished["outcome"] is tm.RunOutcome.ERRORED
    assert finished["research_id"] == "chat_1755500000000_2"
    assert finished["duration_ms"] >= 0


def test_a_completed_run_says_complete(_capture):
    with research._RunLogCapture(research_id="chat_1755500000000_3"):
        pass
    finished = [f for e, f in _capture if e is tm.Ev.RUN_FINISHED][0]
    assert finished["outcome"] is tm.RunOutcome.COMPLETE


def test_a_cancelled_run_is_stopped_not_errored(_capture):
    import asyncio
    cap = research._RunLogCapture(research_id="chat_1755500000000_4")
    cap.__enter__()
    cap.__exit__(asyncio.CancelledError, asyncio.CancelledError(), None)
    finished = [f for e, f in _capture if e is tm.Ev.RUN_FINISHED][0]
    assert finished["outcome"] is tm.RunOutcome.STOPPED


def test_run_finished_does_NOT_come_from_the_teardown(_capture):
    """⛔ The plan's first anchor was `teardown_firestore_run`, measured to be a
    context-free cleanup with nothing in scope — an event that says nothing. The
    capture's exit is the one place that sees every run's terminal state AND has
    the id and the duration."""
    src = code_only_deep(research)
    i = src.index("def teardown_firestore_run")
    assert "RUN_FINISHED" not in src[i:i + 3000]


# ══ 4. the commands a person runs ══════════════════════════════════════
def test_every_entry_point_is_instrumented():
    src = code_only_deep(research)
    for marker in ("Ev.PAIR_STARTED", "Ev.PAIR_FAILED", "Ev.PAIR_CANCELLED",
                   "Ev.PAIR_TOKEN_EXCHANGED", "Ev.LOGIN_STARTED",
                   "Ev.DOCTOR_RUN", "Ev.SERVE_STARTED", "Ev.SEND_LOGS_RESULT"):
        assert marker in src, f"{marker} has no call site"


def test_pairing_reports_how_far_it_GOT_not_only_that_it_failed(_capture):
    """⭐⭐ THE DENOMINATOR. Without a completion event, `PAIR_FAILED` has nothing
    to be a fraction of — and "no completions recorded" reads exactly like "nobody
    ever finishes pairing"."""
    src = code_only_deep(research)
    assert "Ev.PAIR_COMPLETED" in src
    assert "Ev.PAIR_STAGE_REACHED" in src
    assert "Ev.PAIR_CODE_SHOWN" in src


def test_each_pair_stage_reports_at_its_OWN_call_site():
    """⛔ Not inside `_setup_step`. That helper is shared with --retire,
    --resurrect and --unpair, so an emit there would label their steps as pairing
    progress — a number that means two different things."""
    helper = code_only_deep(research._setup_step)
    assert "tm.tm_emit" not in helper, (
        "_setup_step is shared; an emit here reports --retire's steps as pairing")
    src = code_only_deep(research)
    for stage in (2, 3, 4):
        assert f"tm.tm_emit(tm.Ev.PAIR_STAGE_REACHED, stage={stage})" in src, stage


def test_the_completion_names_the_capacity_the_incident_turned_on():
    """⭐ The owner wanted two concurrent run slots and got one, and [5/5] Ready
    reported success without ever naming the capacity."""
    src = code_only_deep(research)
    i = src.index("Ev.PAIR_COMPLETED")
    window = src[i:i + 300]
    # ⛔ Found by mutation: `profiles=` alone matches `profiles=None`, which is the
    # exact defect — the field present and the number gone. The counter itself has
    # to be in the expression.
    assert "next_profile_n" in window, window
    assert "profiles=None" not in window


def test_a_failed_token_refresh_reports_its_CLASS_and_never_its_message():
    """⭐ The line that diagnosed the founding incident and that nobody ever saw:
    `refresh: network error … Failed to resolve 'securetoken.googleapis.com'`. It
    reached bare stderr and no file. The message carries a hostname, a path and a
    Firebase Web API key — the class carries none of that."""
    src = code_only_deep(research._fresh_user_mode_id_token)
    assert "Ev.TOKEN_REFRESH_FAILED" in src
    assert "tm.classify_exception(e)" in src
    i = src.index("Ev.TOKEN_REFRESH_FAILED")
    assert "str(e)" not in src[i:i + 200]
    # And the revoked path reports too — a different cause, a different class.
    assert "tm.ErrorClass.AUTH_REVOKED" in src


def test_login_reports_finishing_as_well_as_starting(_capture):
    src = code_only_deep(research.run_login)
    assert "Ev.LOGIN_STARTED" in src
    assert "Ev.LOGIN_FINISHED" in src
    assert src.index("Ev.LOGIN_STARTED") < src.index("Ev.LOGIN_FINISHED")


def test_every_pairing_abort_path_reports_before_it_returns():
    """⛔ A build-time WALK of the abort paths, because the one that matters is
    whichever one a broken machine takes — and a path that returns silently is
    indistinguishable from a pairing that never started."""
    src = code_only_deep(research.cmd_pair_v2)
    for marker in ("no answer within the pairing window",
                   "could not reach the pairing service",
                   "pairing stopped on an error we have no specific advice for"):
        i = src.index(marker)
        # ⛔ Found by mutation: a fixed 400-character window reaches back into the
        # PREVIOUS except-branch and finds ITS emit, so removing this branch's
        # emit changed nothing. The window starts at the enclosing `except`.
        # ⛔ And not `rfind("except")` either: `classify_exception` contains the
        # word, so for two of the three markers that found a position AFTER the
        # emit. A real clause only.
        clauses = [m.start() for m in re.finditer(r"\n\s+except\b", src)
                   if m.start() < i]
        assert clauses, marker
        window = src[clauses[-1]:i]
        assert "tm.tm_emit(" in window, (
            f"{marker!r} returns without reporting — the abort a broken machine "
            "actually takes")


def test_the_pairing_failure_carries_a_classified_cause():
    src = code_only_deep(research.cmd_pair_v2)
    assert "tm.classify_exception(e)" in src
    assert "str(e)" not in src.split("tm.classify_exception(e)")[0][-200:]


# ══ 5. the flush ═══════════════════════════════════════════════════════
def test_every_command_flushes_at_the_top_of_main():
    """⛔⛔ THE TWO CASES THAT OTHERWISE NEVER FIRE: a machine whose pairing
    SUCCEEDED but whose POST failed never pairs again, and a machine whose
    pairing FAILED runs `--doctor` next. "Retry on the next attempt of the same
    thing" has no trigger at all."""
    src = code_only_deep(research.main)
    assert "tm.flush_in_background()" in src
    assert src.index("tm.flush_in_background()") < src.index("args = parser.parse_args()")


def test_the_flush_runs_on_every_worker_not_only_worker_one():
    """⛔ The worker-1 heartbeat loop is gated `WORKER_ID == 1`, so a worker-2
    spool anchored there would never go out at all."""
    src = code_only_deep(research._firebase_reconnect_loop)
    assert "tm.flush_in_background()" in src
    assert "WORKER_ID == 1" not in src


def test_a_finished_run_flushes_what_it_just_recorded():
    src = code_only_deep(research._RunLogCapture.__exit__)
    assert "tm.flush_in_background()" in src


def test_the_flush_is_never_synchronous_in_a_command_path():
    """A telemetry flush must never be why a command feels broken."""
    src = code_only_deep(research)
    assert "tm.flush()" not in src, (
        "a blocking flush on a machine with dead DNS holds the command inside a "
        "name lookup")


# ══ 6. telemetry can never break the thing it measures ═════════════════
def test_tm_emit_never_raises_whatever_it_is_handed():
    for bad in (None, "nonsense", 999_999, object()):
        assert tm.tm_emit(bad) in (True, False)
    assert tm.tm_emit(tm.Ev.PHASE_START, phase=object()) in (True, False)
    assert tm.tm_emit(tm.Ev.PHASE_START, research_id=b"bytes") in (True, False)


def test_the_module_is_imported_once_at_the_top_not_inside_call_sites():
    """A local import inside a hot call site is a per-call filesystem stat.

    Read from the FILE rather than through `code_only_deep`: the import sits in
    the module header where that helper's dedent/re-pad is at its least
    predictable, and no comment in this file contains the literal."""
    from pathlib import Path
    src = Path("research.py").read_text(encoding="utf-8")
    assert "\nimport telemetry as tm\n" in src
    assert src.count("import telemetry") == 1


def test_a_keystore_failure_never_takes_the_pairing_down(monkeypatch):
    """⛔ Found by mutation. A correlation id is a convenience; a pairing is not.
    The guard only matters on the machine where the keystore is the broken thing —
    which is exactly the machine this whole wave is about."""
    import auth.v2_flow as flow
    import auth.keystore as ks
    monkeypatch.setattr(ks, "install_uuid",
                        lambda: (_ for _ in ()).throw(OSError("keychain locked")))
    assert flow._install_uuid_best_effort() is None


def test_the_install_id_reaches_the_device_doc_at_pair_time():
    """⭐ The only thing that can join a bundle or a batch sent while pairing was
    broken to the account that ends up owning the machine."""
    from pathlib import Path
    flow = Path("auth/v2_flow.py").read_text(encoding="utf-8")
    assert '"installUuid": _install_uuid_best_effort()' in flow
    route = Path(__file__).resolve().parents[2] / "dg-research" / "src" / "app" / "api" / "devices" / "initiate-pair" / "route.ts"
    if not route.exists():
        pytest.skip("sibling app repo not checked out")
    text = route.read_text(encoding="utf-8")
    assert "installUuid" in text
    assert "INSTALL_UUID_RE" in text, (
        "an unauthenticated route stores this value; it has to be shape-bounded")
