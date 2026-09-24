"""A run that keeps nothing writes its topic into no name, no log and no event.

⛔⛔ THE RUN ID CARRIED THE TOPIC, AND IT TRAVELS FURTHER THAN THE DISK. It was
`safe_name(topic)_YYYYMMDD_HHMMSS`, built at four sites, and it becomes the
queue directory on the research computer, the record's `backendRunId`, the
device document's `workers.{n}.runId` — which the machine's OWNER reads — and
part of every log line that names the job. For somebody running on a computer
they do not own, that is their research subject spread across another person's
machine and another person's app, while the owner is deliberately told only
that a run happened.

Beside it, seven start-listener lines printed `topic=…` into `backend.log`,
whose tail rides the owner's support bundle; and the content-free telemetry
tier carried the research id, which an incognito run does not leave behind.

⭐ EVERY PIN BELOW RUNS THE REAL THING — the real listener callback for the
consumer, the real `telemetry` module for the spool — and each refusal is
paired with the ordinary `chat_` run, whose bytes must not move at all.
"""
import json
import time
import types

import pytest

import research
import telemetry as tm
from _queue_listener import Listener

OWNER = "uid-owner"
SHARER = "uid-sharer"
INCOG = "incog_1758400000000_7"
CHAT = "chat_1758400000000_7"
SECRET = "my divorce settlement options"
WHEN = research.datetime(2026, 9, 22, 10, 15, 0)


# ══ 1. the mint ═══════════════════════════════════════════════════════════

def test_an_ordinary_run_id_is_byte_for_byte_what_it_always_was():
    """⭐ ACCEPT POLARITY, AND IT IS THE WHOLE COMPATIBILITY CLAIM. Existing
    queue directories, resume payloads and `backendRunId` values on live
    records all have this shape, and nothing about them may move."""
    assert research._mint_run_id(SECRET, CHAT, now=WHEN) == \
        "my_divorce_settlement_options_20260922_101500"
    # No research id at all — the serve API's local run.
    assert research._mint_run_id(SECRET, now=WHEN) == \
        "my_divorce_settlement_options_20260922_101500"


def test_an_incognito_run_id_carries_nothing_of_the_topic():
    """⛔⛔ THE PIN THE SPEC NAMED."""
    minted = research._mint_run_id(SECRET, INCOG, now=WHEN)
    for word in SECRET.split():
        assert word not in minted, f"{word!r} survived into the run id"
    assert minted == "incognito_1758400000000_7_20260922_101500"


def test_two_incognito_runs_in_the_same_second_are_two_directories():
    """⛔⛔ DROPPING THE TOPIC COLLAPSES THE NAMES. Every incognito run of one
    second would otherwise mint the same id — and two members of a shared
    computer claiming in the same second would share one queue directory, each
    writing their documents over the other's. The research id's own
    `<ms>_<counter>` tail is what keeps them apart, which also keeps this mint a
    pure function with no clock to seed."""
    a = research._mint_run_id("one", "incog_1758400000000_1", now=WHEN)
    b = research._mint_run_id("two", "incog_1758400000000_2", now=WHEN)
    c = research._mint_run_id("three", "incog_1758400000001_1", now=WHEN)
    assert len({a, b, c}) == 3


def test_an_incognito_run_id_keeps_the_shape_everything_else_parses():
    """The stamp must still END the name: `_RUN_ID_STAMP_RE` is what
    `_log_job_ref` prints instead of a run id, and `_BUNDLE_QUEUE_NAME_RE` is
    the cut the support-bundle redactor makes on a queue directory name."""
    minted = research._mint_run_id(SECRET, INCOG, now=WHEN)
    assert research._RUN_ID_STAMP_RE.search(minted).group(1) == "20260922_101500"
    assert research._BUNDLE_QUEUE_NAME_RE.fullmatch(minted).group(1) == "20260922_101500"


def test_a_run_folder_key_still_refuses_an_incognito_run_id():
    """⛔ THE RUN-ID DENY STAYS ARMED. `_run_log_folder_name` refuses any key
    ending in a run-id stamp so a topic can never reach a log folder name; the
    new shape must stay inside that refusal rather than sneak past it."""
    minted = research._mint_run_id(SECRET, INCOG, now=WHEN)
    assert research._RUN_ID_SUFFIX_RE.search(minted)
    assert research._run_log_folder_name(minted, "2026-09-22T10:15:00Z").startswith("local_")


# ══ 2. the log lines ══════════════════════════════════════════════════════

def test_a_log_line_says_the_topic_for_an_ordinary_run():
    """⭐ ACCEPT POLARITY. `backend.log` is the machine owner's file and an
    ordinary run's subject is allowed in it — they can see it in the queue
    folder name and in the app already. Byte-identical to the slice this
    replaced, or seven live log lines changed for everybody."""
    assert research._loggable_topic(SECRET, CHAT) == SECRET[:40]
    assert research._loggable_topic(SECRET, CHAT, 30) == SECRET[:30]
    assert research._loggable_topic(SECRET, None) == SECRET[:40]


def test_a_log_line_says_nothing_of_an_incognito_topic():
    assert research._loggable_topic(SECRET, INCOG) == "<topic removed>"


def test_the_mark_is_the_bundle_redactors_own_word():
    """⭐ ONE VOCABULARY. `<topic removed>` is already what this product writes
    over a research subject that is not there, and re-marking an already-marked
    value is a no-op — so a redacted bundle and a live log read the same, and
    the next reader does not have to learn a second word."""
    assert research._loggable_topic(SECRET, INCOG) == research._BUNDLE_TOPIC_MARK


# ══ 3. the consumer: the real start listener, fed an incognito start ══════

def _start(rid, topic=SECRET):
    return {"action": "start", "researchId": rid, "uid": SHARER,
            "submittedBy": SHARER, "topic": topic,
            "timestamp": int(time.time() * 1000) - 1000}


def _listener(monkeypatch, tmp_path, rid):
    """A listener whose fake database already holds the record being started —
    without it the branch bails before the mint as "the user deleted the chat"."""
    return Listener(monkeypatch, tmp_path, owner=OWNER,
                    research_docs={(SHARER, rid): {"status": "queued"}})


@pytest.fixture()
def logged(monkeypatch):
    lines: list = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: lines.append(str(msg)))
    return lines


def test_the_listener_gives_an_incognito_run_a_topicless_run_id(
        tmp_path, monkeypatch, logged):
    """⛔⛔ THE CONSUMER, NOT THE HELPER. The mint sits inside the start branch
    of a Firestore snapshot callback; a helper nobody called would pass every
    test above."""
    lis = _listener(monkeypatch, tmp_path, INCOG).feed(**_start(INCOG))
    [(uid, rid, patch)] = lis.writes
    assert (uid, rid) == (SHARER, INCOG)
    run_id = patch["backendRunId"]
    assert run_id.startswith("incognito_1758400000000_7_")
    for word in SECRET.split():
        assert word not in run_id
    # The job handed to the worker names the same directory.
    assert lis.enqueued[0]["run_id"] == run_id


def test_the_listener_still_names_an_ordinary_run_after_its_topic(
        tmp_path, monkeypatch, logged):
    """⭐ ACCEPT POLARITY on the same consumer."""
    lis = _listener(monkeypatch, tmp_path, CHAT).feed(**_start(CHAT))
    [(_uid, _rid, patch)] = lis.writes
    assert patch["backendRunId"].startswith("my_divorce_settlement_options_")


def test_no_line_the_listener_logs_for_an_incognito_start_says_the_topic(
        tmp_path, monkeypatch, logged):
    """⛔ `backend.log` IS THE MACHINE'S. Its tail ships in the owner's support
    bundle, and on a shared computer every member's runs land in it."""
    _listener(monkeypatch, tmp_path, INCOG).feed(**_start(INCOG))
    assert logged, "the start branch logged nothing at all — re-anchor this pin"
    blob = "\n".join(logged)
    for word in SECRET.split():
        assert word not in blob, f"{word!r} reached backend.log: {blob}"
    assert "<topic removed>" in blob


def test_the_same_lines_still_say_an_ordinary_topic(tmp_path, monkeypatch, logged):
    """⭐ ACCEPT POLARITY — and it is what proves the assertion above is not
    passing because the listener stopped logging."""
    _listener(monkeypatch, tmp_path, CHAT).feed(**_start(CHAT))
    assert SECRET[:40] in "\n".join(logged)


def _multi_worker_listener(monkeypatch, tmp_path, rid):
    """⛔ THE CLAIM BRANCH IS MULTI-WORKER ONLY, and it holds three of the seven
    topic-bearing lines — the claim, the claim error and the lost-to-a-sibling
    skip. A single-worker install skips the whole block (no contender to race),
    so a suite that only ever fed one worker measured none of them."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(SHARER, rid): {"status": "queued"}})
    monkeypatch.setattr(research, "load_worker_count", lambda: 2)
    # ⛔ THE IN-FLIGHT COUNTER IS A MODULE GLOBAL another test can leave set,
    # and a non-zero read sends this doc down the defer branch instead of the
    # claim — the pin would then measure a line it never reached.
    monkeypatch.setattr(research, "_pending_enq_read", lambda: 0)
    return lis


def test_the_claim_line_of_a_shared_computer_says_nothing_of_the_topic(
        tmp_path, monkeypatch, logged):
    """A shared research computer is exactly where this matters: every member's
    claim lands in one `backend.log`, whose tail rides the owner's bundle."""
    _multi_worker_listener(monkeypatch, tmp_path, INCOG).feed(**_start(INCOG))
    blob = "\n".join(logged)
    assert "claimed" in blob, "the claim branch was not reached — re-anchor this pin"
    for word in SECRET.split():
        assert word not in blob, f"{word!r} reached backend.log: {blob}"


def test_the_claim_line_still_says_an_ordinary_topic(tmp_path, monkeypatch, logged):
    """⭐ ACCEPT POLARITY — the cross-account triage this line was promoted to
    INFO for still works for everybody else."""
    _multi_worker_listener(monkeypatch, tmp_path, CHAT).feed(**_start(CHAT))
    blob = "\n".join(logged)
    assert "claimed" in blob and SECRET[:40] in blob


def test_the_defer_line_of_a_busy_computer_says_nothing_of_the_topic(
        tmp_path, monkeypatch, logged):
    """⛔ THE RUN NOBODY IS WATCHING YET. A start that arrives while the
    machine is busy is logged and then sits in the queue — this line was added
    precisely because the silent defer was untraceable, and it carries the
    topic of whichever member submitted it."""
    lis = _multi_worker_listener(monkeypatch, tmp_path, INCOG)
    monkeypatch.setitem(research._QUEUE_STATE, "running", True)
    lis.feed(**_start(INCOG))
    blob = "\n".join(logged)
    assert "defer" in blob, "the defer branch was not reached — re-anchor this pin"
    for word in SECRET.split():
        assert word not in blob, f"{word!r} reached backend.log: {blob}"


def test_the_defer_line_still_says_an_ordinary_topic(tmp_path, monkeypatch, logged):
    """⭐ ACCEPT POLARITY — the multi-account FIFO triage this line exists for."""
    lis = _multi_worker_listener(monkeypatch, tmp_path, CHAT)
    monkeypatch.setitem(research._QUEUE_STATE, "running", True)
    lis.feed(**_start(CHAT))
    blob = "\n".join(logged)
    assert "defer" in blob and SECRET[:40] in blob


def test_a_start_doc_missing_a_field_still_says_nothing_of_an_incognito_topic(
        tmp_path, monkeypatch, logged):
    """The refusal line prints the topic too, and a malformed document is
    exactly the case where nobody is watching."""
    _listener(monkeypatch, tmp_path, INCOG).feed(**{**_start(INCOG), "uid": ""})
    blob = "\n".join(logged)
    assert "divorce" not in blob, blob


# ══ 4. telemetry ══════════════════════════════════════════════════════════

@pytest.fixture()
def spool(tmp_path, monkeypatch):
    """A real telemetry spool in a scratch home — the module, not a double."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("SR_WORKER_ID", raising=False)
    monkeypatch.setenv("SR_TELEMETRY", "1")
    monkeypatch.setattr(tm, "_install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(tm, "_build", lambda: "0.1.13")
    # ⛔ THE FLUSH IS NOT THE SUBJECT, AND IT RACES THE READ. Leaving a capture
    # starts `tm.flush_in_background()`, whose thread renames this very spool to
    # `.sending.` while it posts — so on a loaded machine the read below found
    # no file and both lifecycle pins failed with nothing wrong (measured in the
    # whole-suite gate, 2026-09-23; each passed alone). What these pins read is
    # what was SPOOLED, so the delivery is stood down.
    monkeypatch.setattr(tm, "flush_in_background", lambda *a, **k: None)

    def _read():
        path = tm.spool_path()
        if not path.exists():
            return []
        return [json.loads(ln) for ln in
                path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return _read


def _arm(monkeypatch, rid):
    monkeypatch.setattr(research, "_active_run_sink",
                        lambda: types.SimpleNamespace(research_id=rid))


def test_an_ordinary_runs_event_still_names_its_research(monkeypatch, spool):
    """⭐ ACCEPT POLARITY FIRST — the id is how a phase event is joined to a
    run, and dropping it for everybody would be a silent loss."""
    _arm(monkeypatch, CHAT)
    research._tm_note_event("phase_start", phase=2, agent="chatgpt")
    [event] = spool()
    assert event["ev"] == int(tm.Ev.PHASE_START)
    assert event["d"]["research_id"] == CHAT
    assert event["d"]["phase"] == 2


def test_an_incognito_runs_event_rides_without_naming_the_run(monkeypatch, spool):
    """⛔⛔ AND IT SPOOLS NO TELEMETRY_INVALID. `coerce_field` admits one string
    shape — `chat_<13 digits>_<counter>` — so an `incog_…` id RAISES, and
    `tm_emit` answers a raise with a WARNING and an invalid-event counter, for
    every event of a ninety-minute run: a warning flood on the person's own
    machine and a counter that says the product is broken while it behaves."""
    _arm(monkeypatch, INCOG)
    research._tm_note_event("phase_start", phase=2, agent="chatgpt")
    [event] = spool()
    assert event["ev"] == int(tm.Ev.PHASE_START), (
        "the phase event itself must still ride — phase and platform are "
        "content-free and are the whole point of this tier")
    assert "research_id" not in event["d"]
    assert event["d"]["phase"] == 2
    assert not any(e["ev"] == int(tm.Ev.TELEMETRY_INVALID) for e in spool())


def test_the_id_is_dropped_before_the_wire_not_widened_into_it():
    """⛔ THE REPAIR THAT WOULD HAVE BEEN WRONG. Widening `RESEARCH_ID_RE` to
    admit `incog_…` would have silenced the warnings and kept the one field
    that joins a whole run's timeline together — which is the thing an
    incognito run must not leave behind."""
    assert tm.coerce_field("research_id", CHAT) == CHAT
    with pytest.raises(tm.TelemetryFieldError):
        tm.coerce_field("research_id", INCOG)


def test_the_run_start_and_finish_events_ask_the_same_question():
    """⭐ ONE ANSWER FOR ALL THREE EMITTERS. `tm_emit` drops a `None` field
    silently, so an emitter that forgot would look exactly like one that
    remembered until somebody read the spool."""
    assert research._tm_research_id(CHAT) == CHAT
    assert research._tm_research_id(INCOG) is None
    assert research._tm_research_id(None) is None


def test_an_ordinary_runs_lifecycle_events_name_it(spool):
    """⭐ ACCEPT POLARITY for the other two emitters, run for real: arming a
    capture emits RUN_STARTED and leaving it emits RUN_FINISHED."""
    with research._RunLogCapture(research_id=CHAT):
        pass
    ids = {e["ev"]: e["d"] for e in spool()}
    assert ids[int(tm.Ev.RUN_STARTED)]["research_id"] == CHAT
    assert ids[int(tm.Ev.RUN_FINISHED)]["research_id"] == CHAT


def test_an_incognito_runs_lifecycle_events_do_not_name_it(spool):
    """⛔ THE TWO EMITTERS THE PER-EVENT TAP DOES NOT COVER. Each holds the id
    directly, and each would otherwise spool a TELEMETRY_INVALID instead."""
    with research._RunLogCapture(research_id=INCOG):
        pass
    events = spool()
    by_ev = {e["ev"]: e["d"] for e in events}
    assert int(tm.Ev.RUN_STARTED) in by_ev and int(tm.Ev.RUN_FINISHED) in by_ev, (
        "the lifecycle events must still ride — the outcome and the duration "
        "are content-free")
    assert "research_id" not in by_ev[int(tm.Ev.RUN_STARTED)]
    assert "research_id" not in by_ev[int(tm.Ev.RUN_FINISHED)]
    assert not any(e["ev"] == int(tm.Ev.TELEMETRY_INVALID) for e in events)
