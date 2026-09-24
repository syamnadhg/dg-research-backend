"""A run that keeps nothing leaves none of its words in the machine's own log.

Wave 10.9 repair. `backend.log` is the MACHINE's file, not one person's: every
worker's stdout is appended to it, its tail rides the owner's support bundle,
and on a shared computer every member's runs land in it. The wave kept the
start listener's lines about an incognito run free of its topic — and missed
everything else:

  · the queue sweep's ZOMBIE / ABANDONED / ABANDONED-BY-RESEARCH lines and the
    idle rescan's two claim lines printed `topic=…` raw — measured on the real
    listener: a start doc whose record had been deleted by Cancel put
    "my divorce settlement options" into the owner's log on the next boot;
  · and every line the RUN ITSELF writes is printed there too, not only into
    its own folder. The folder is removed when the run ends; `backend.log` is
    never cleaned. Its topic checks print the topic's words, its brief gate
    prints the person's feedback, its CUA and arbiter lines quote the pages.

⭐ SO THE RUN'S OWN LINES ARE DECIDED ONCE, AT THE CONSOLE, with the same
attribution the run folder already uses — and the lines the machine writes
about somebody ELSE's run are fixed where they are written. Every pin below runs
the real thing and is paired with the ordinary run, whose lines must not move.

Run:  pytest tests/test_incognito_backend_log_109.py -v
"""
import asyncio
import contextlib
import json
import os
import threading
import time
import types

import pytest

import research
from _queue_listener import Listener

OWNER = "uid-owner"
SHARER = "uid-sharer"
INCOG = "incog_1758400000000_7"
CHAT = "chat_1758400000000_7"
SECRET = "my divorce settlement options"
WORDS = SECRET.split()[1:]            # "my" is not evidence of anything


def _says_nothing_of_it(text):
    for word in WORDS:
        assert word not in text, f"{word!r} reached backend.log:\n{text}"


class _Sink:
    """The armed run folder, as `log()` sees it: an id and somewhere to write."""

    def __init__(self, research_id):
        self.research_id = research_id
        self.lines: "list[str]" = []

    def note_line(self, line, level):
        self.lines.append(line)


@pytest.fixture(autouse=True)
def _nothing_armed(monkeypatch):
    """No run armed and no pipeline running, unless the test says so."""
    assert research._LOG_RUN.get() is None, "a test before this one leaked a run origin"
    saved = list(research._RUN_LOG_SINKS)
    research._RUN_LOG_SINKS.clear()
    monkeypatch.setattr(research, "_fb_research_id", None)
    yield
    research._RUN_LOG_SINKS.clear()
    research._RUN_LOG_SINKS.extend(saved)


def _arm(research_id):
    sink = _Sink(research_id)
    research._RUN_LOG_SINKS.append(sink)
    return sink


@contextlib.contextmanager
def _running(research_id, *, arm=True):
    """A run's own work, framed the way `run_pipeline_captured` frames it: its
    folder armed, and its ORIGIN set — which is what the console decides by."""
    sink = _arm(research_id) if arm else None
    token = research._LOG_RUN.set(research_id)
    try:
        yield sink
    finally:
        research._LOG_RUN.reset(token)


# ══ 1. the console decides, through the real `log()` ══════════════════════

def test_an_ordinary_run_still_prints_every_line_it_writes(capsys):
    """⭐ ACCEPT POLARITY FIRST. A console rule that swallowed everything would
    pass every refusal below and leave the owner a log with nothing in it."""
    with _running(CHAT) as sink:
        research.log(f"Phase 2: off-topic sweep is INERT this run: topic {SECRET!r}")

    assert SECRET in capsys.readouterr().out
    assert SECRET in "\n".join(sink.lines)


def test_a_line_a_run_that_keeps_nothing_writes_stays_out_of_backend_log(capsys):
    """⛔⛔ THE DEFECT. Every line the run writes was printed to the worker's
    stdout — which IS `backend.log` — as well as into the run's own folder, and
    only the folder is removed when the run ends."""
    with _running(INCOG) as sink:
        research.log(f"Phase 2: off-topic sweep is INERT this run: topic {SECRET!r}")

    _says_nothing_of_it(capsys.readouterr().out)
    # ⭐ AND THE RUN STILL HAS ITS OWN ACCOUNT, in the folder that leaves with it.
    assert SECRET in "\n".join(sink.lines), (
        "the line was dropped instead of kept in the run's own folder")


def test_a_machine_line_written_while_it_runs_still_reaches_backend_log(capsys):
    """⭐ THE MACHINE'S OWN LINES ARE NOT THE RUN'S. The heartbeat, the sweeps
    and the start listener write inside the machine scope, and the owner's log
    must keep them — a private run on a shared computer cannot blind its owner
    to what the computer is doing. The scope wins even inside the run's own
    call stack."""
    with _running(INCOG):
        with research._machine_log_scope():
            research.log("[heartbeat] device doc refreshed")

    assert "[heartbeat] device doc refreshed" in capsys.readouterr().out


def test_a_run_with_no_folder_is_still_recognised_by_its_origin(capsys):
    """⛔ THE CAPTURE NEVER RAISES INTO THE RUN, so a disk that refused the run
    folder leaves no sink at all. The origin does not depend on the folder."""
    with _running(INCOG, arm=False):
        research.log(f"Phase 1: Injecting user feedback: {SECRET}")

    _says_nothing_of_it(capsys.readouterr().out)


def test_an_ordinary_origin_with_no_folder_still_prints(capsys):
    """⭐ ACCEPT POLARITY for the case above."""
    with _running(CHAT, arm=False):
        research.log(f"Phase 1: Injecting user feedback: {SECRET}")

    assert SECRET in capsys.readouterr().out


def test_nothing_running_prints_everything(capsys):
    research.log(f"[serve] idle — last topic {SECRET}")
    assert SECRET in capsys.readouterr().out


# ══ 2. the consumer: the wrapper every queued run goes through ════════════
#
# ⛔ A TESTED RULE IS NOT A TESTED RUN. These drive the real
# `run_pipeline_captured` — real `_RunLogCapture`, real folder on disk — with
# only the pipeline body replaced by one that writes the lines a run writes.

def _drive_the_wrapper(monkeypatch, tmp_path, research_id):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))

    async def _body(*args, **kwargs):
        research.log(f"Phase 1: Injecting user feedback: {SECRET}")
        research.log(f"[title-refresh] keeping the topic-derived name ({SECRET})", "WARN")

    monkeypatch.setattr(research, "run_pipeline", _body)
    asyncio.run(research.run_pipeline_captured(
        topic=SECRET, research_id=research_id, uid=SHARER,
        run_id="incognito_1758400000000_7_20260922_101500"))
    [run_log] = list(research._runs_log_root().glob("*/run.log"))
    return run_log.read_text(encoding="utf-8")


def test_a_queued_run_that_keeps_nothing_writes_none_of_its_words_to_backend_log(
        tmp_path, monkeypatch, capsys):
    """⛔⛔ THE CONSUMER. The rule above is only worth something if the wrapper
    every claimed job runs through arms the run it describes."""
    kept = _drive_the_wrapper(monkeypatch, tmp_path, INCOG)
    out = capsys.readouterr().out

    _says_nothing_of_it(out)
    assert SECRET in kept, "the run's own folder lost its account of the run"
    # ⭐ AND THE GAP IS EXPLAINED. An hour of silence in the owner's log reads as
    # a hung machine unless the log says why it is quiet.
    assert f"{INCOG[:8]}… keeps nothing" in out, (
        "backend.log went quiet for a whole run without saying why")


def test_a_queued_ordinary_run_still_prints_its_lines(tmp_path, monkeypatch, capsys):
    """⭐ ACCEPT POLARITY on the same wrapper — and nothing is announced."""
    _drive_the_wrapper(monkeypatch, tmp_path, CHAT)
    out = capsys.readouterr().out

    assert SECRET in out
    assert "keeps nothing" not in out


# ══ 3. the lines the machine writes about somebody else's run ═════════════
#
# These run in the machine scope, outside any run's folder, so the console rule
# rightly leaves them alone — each one has to be safe where it is written.

@pytest.fixture()
def logged(monkeypatch):
    lines: list = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: lines.append(str(msg)))
    return lines


_HOUR_MS = 60 * 60 * 1000


def _stale_start(rid, **extra):
    return {"action": "start", "researchId": rid, "uid": SHARER,
            "submittedBy": SHARER, "topic": SECRET, **extra}


@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_the_zombie_sweep_names_the_run_and_not_an_incognito_topic(
        tmp_path, monkeypatch, logged, rid):
    """⛔ A CLAIM WHOSE WORKER DIED. On the next boot the replayed start doc is
    deleted with a line that printed its topic."""
    now = int(time.time() * 1000)
    Listener(monkeypatch, tmp_path, owner=OWNER).feed(
        **_stale_start(rid, assignedWorker=1, claimedAt=now - 60_000))
    blob = "\n".join(logged)

    assert "stale-skip ZOMBIE" in blob, "the zombie branch was not reached"
    if rid == INCOG:
        _says_nothing_of_it(blob)
    else:
        assert SECRET[:40] in blob, "an ordinary run lost its triage line"


@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_the_abandoned_sweep_names_the_run_and_not_an_incognito_topic(
        tmp_path, monkeypatch, logged, rid):
    """⛔⛔ THE MEASURED PATH. The person pressed Cancel (or left the chat) while
    the computer was switched off; the record is gone and the start doc waits
    out its fuse. The owner boots twelve hours later and the sweep reads the
    subject into the owner's own log as it deletes the doc."""
    Listener(monkeypatch, tmp_path, owner=OWNER).feed(
        **_stale_start(rid, timestamp=int(time.time() * 1000) - 13 * _HOUR_MS))
    blob = "\n".join(logged)

    assert "stale-skip ABANDONED" in blob, "the abandoned branch was not reached"
    if rid == INCOG:
        _says_nothing_of_it(blob)
    else:
        assert SECRET[:40] in blob


@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_the_legacy_staleness_sweep_names_the_run_and_not_an_incognito_topic(
        tmp_path, monkeypatch, logged, rid):
    """The third sweep line — a start doc with no timestamp, judged by its
    record's age. The web always stamps one today, so this is the cheap end of
    the set; it prints the same expression and is fixed the same way."""
    old = int(time.time() * 1000) - 13 * _HOUR_MS
    Listener(monkeypatch, tmp_path, owner=OWNER,
             research_docs={(SHARER, rid): {"updatedAt": old, "createdAt": old}}
             ).feed(**_stale_start(rid, timestamp=None))
    blob = "\n".join(logged)

    assert "ABANDONED-BY-RESEARCH" in blob, "the legacy branch was not reached"
    if rid == INCOG:
        _says_nothing_of_it(blob)
    else:
        assert SECRET[:40] in blob


# ── the idle rescan, a closure inside `run_server` ─────────────────────────

class _RescanSnap:
    def __init__(self, data):
        self.id = "q-orphan"
        self._data = data
        self.reference = object()

    def to_dict(self):
        return dict(self._data)


class _RescanDb:
    """`devices/{id}/queue` holding one unclaimed start doc."""

    def __init__(self, data):
        self._snap = _RescanSnap(data)

    def collection(self, _name):
        return self

    def document(self, _name):
        return self

    def limit(self, _n):
        return self

    def stream(self):
        return iter([self._snap])


class _IdleQueue:
    _queue = ()

    def qsize(self):
        return 0


def _rescan_once(monkeypatch, rid, claim_outcome):
    """Run the REAL `_rescan_queue_for_unclaimed` once, reconstructed from
    `run_server`'s code object — the only value supplied is the queue it
    closes over."""
    code = next((c for c in research.run_server.__code__.co_consts
                 if isinstance(c, types.CodeType)
                 and c.co_name == "_rescan_queue_for_unclaimed"), None)
    assert code is not None, "the rescan is no longer a closure of run_server"
    assert code.co_freevars == ("_job_queue",), (
        f"the rescan closes over {code.co_freevars} now — supply them here")
    fn = types.FunctionType(code, research.__dict__, code.co_name, None,
                            (types.CellType(_IdleQueue()),))
    monkeypatch.setattr(research, "_firebase_db", _RescanDb(_stale_start(
        rid, timestamp=int(time.time() * 1000) - 1000)))
    monkeypatch.setattr(research, "load_worker_count", lambda: 2)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: False)
    monkeypatch.setattr(research, "_exit_scheduled", False)
    monkeypatch.setitem(research._REST_DEFER_SEEN, "v", False)
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setattr(research, "_try_claim_queue_doc",
                        lambda *a, **k: claim_outcome)
    asyncio.run(fn())


@pytest.mark.parametrize("outcome,line", [(None, "claim error"),
                                          (False, "lost to sibling")])
@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_the_idle_rescan_names_the_run_and_not_an_incognito_topic(
        monkeypatch, logged, rid, outcome, line):
    """⛔ TWO IDLE WORKERS RACE FOR ONE ORPHAN and one of them loses — on any
    machine with two workers that is ordinary, and the loser printed the topic."""
    _rescan_once(monkeypatch, rid, outcome)
    blob = "\n".join(logged)

    assert line in blob, f"the {line!r} branch was not reached:\n{blob}"
    if rid == INCOG:
        _says_nothing_of_it(blob)
    else:
        assert SECRET[:40] in blob


# ══ 4. what `--login` prints on the owner's own terminal ══════════════════

def _in_flight(tmp_path, monkeypatch, rid):
    """One live worker lock and the run folder it names."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    queues = tmp_path / "queues"
    run_id = "incognito_1758400000000_7_20260922_101500"
    run = queues / run_id
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"title": SECRET, "topic": SECRET}),
                                   encoding="utf-8")
    (run / "owner.json").write_text(json.dumps({"uid": SHARER, "researchId": rid}),
                                    encoding="utf-8")
    (queues / ".worker.1.lock").write_text(json.dumps({
        "worker_id": 1, "pid": os.getpid(), "run_id": run_id,
        "started_at": int(time.time() * 1000)}), encoding="utf-8")
    return run_id


def test_login_does_not_read_out_a_private_runs_topic_to_the_owner(
        tmp_path, monkeypatch):
    """⛔⛔ THE OWNER, AT THEIR OWN KEYBOARD. `--login` closes every run in
    flight and names each one — "Closing Run 1 — <title>" — on the terminal of
    the person who owns the computer, and into the session log that rides their
    support bundle. For a member's private run that title is the topic."""
    run_id = _in_flight(tmp_path, monkeypatch, INCOG)
    [run] = research._enumerate_ongoing_runs()

    assert run["run_id"] == run_id
    _says_nothing_of_it(run["title"])


def test_login_still_names_an_ordinary_run_by_its_title(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY — the whole reason the listing reads `meta.json`."""
    _in_flight(tmp_path, monkeypatch, CHAT)
    [run] = research._enumerate_ongoing_runs()

    assert run["title"] == SECRET


# ══ 5. a thread the run leaves behind ═════════════════════════════════════
#
# ⛔ A RAW THREAD CARRIES NO RUN'S ORIGIN, so its lines are the machine's and
# reach `backend.log` — and for a run that keeps nothing, phases 3 and 4 are
# off, so the run ends seconds after the title refresh is dispatched. Such a run
# dispatches no refresh at all (its record is purged, and the model call on its
# topic would outlive it); where its words could go is pinned in
# `test_late_writers_name_their_run_109.py`.

class _LateThread:
    """Runs the worker when started — AFTER the run has ended, which is when a
    slow title model answers."""

    started: "list" = []

    def __init__(self, target=None, args=(), kwargs=None, **_kw):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        _LateThread.started.append(self._target)
        research._fb_research_id = None
        self._target(*self._args, **self._kwargs)


@pytest.mark.parametrize("verdict", ["refuse_loud", "refuse_silent"])
@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_a_late_title_refusal_names_no_incognito_topic_words(
        monkeypatch, logged, rid, verdict):
    """The refusal lines print the topic's distinctive WORDS — the anchors — so
    an operator can see why a title was thrown away. For a run that keeps
    nothing those words are its subject, and it starts no refresh to print them."""
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(research, "_try_llm_title", lambda *a, **k: "Golden Retriever Care")
    monkeypatch.setattr(research, "title_refusal_verdict", lambda *a, **k: verdict)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(_LateThread, "started", [])
    monkeypatch.setattr(research, "_threading",
                        types.SimpleNamespace(Thread=_LateThread))
    monkeypatch.setattr(research, "_fb_research_id", rid)

    research._refresh_research_title_async(SECRET, "", "findings")
    blob = "\n".join(logged)

    if rid == INCOG:
        assert _LateThread.started == [], "a run that keeps nothing started a refresh"
        _says_nothing_of_it(blob)
    else:
        assert "[title-refresh]" in blob, "the refusal branch was not reached"
        assert "divorce, settlement" in blob, "an ordinary refusal lost its anchors"


# ══ 6. the traceback of a run that dies ═══════════════════════════════════
#
# ⛔ STDERR IS THE MACHINE'S OTHER LOG (`backend.err.log`), and `print_exc`
# never goes through `log()` — so the console rule above cannot see it. The
# exception it prints is whatever the failing call was holding.

def _die_at_the_first_phase(tmp_path, monkeypatch, research_id):
    """Drive the REAL `run_pipeline` into its fatal handler: a resume whose
    first phase event raises, with everything around it stubbed and recorded."""
    queue_dir = tmp_path / "incognito_1758400000000_7_20260922_101500"
    (queue_dir / "documents").mkdir(parents=True)
    lines: list = []
    monkeypatch.setattr(research, "resolve_api_key", lambda _k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: lines.append(str(msg)))
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)

    async def _no_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _no_dispatcher)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _qd: (1, "resume at 1"))
    monkeypatch.setattr(research, "load_checkpoint", lambda _qd: {"topic": SECRET})

    def _emit(name, **_kw):
        if name == "phase_start":
            raise RuntimeError(f"could not open sources/{SECRET}.pdf")
    monkeypatch.setattr(research, "emit_event", _emit)
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)
    monkeypatch.setattr(research, "fail_phase", lambda *a, **k: None)
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry",
                        lambda *a, **k: (False, 0, False))
    asyncio.run(research.run_pipeline(
        topic=SECRET, resume_dir=str(queue_dir), uid=None, email=None,
        api_key="test-key", research_id=research_id))
    return "\n".join(lines)


def test_a_run_that_keeps_nothing_dies_without_writing_to_backend_err_log(
        tmp_path, monkeypatch, capsys):
    """⛔⛔ THE CONSUMER, run to its fatal handler: the traceback — with the
    exception's own text — goes into the run's lines, never to stderr."""
    logged_lines = _die_at_the_first_phase(tmp_path, monkeypatch, INCOG)
    err = capsys.readouterr().err

    _says_nothing_of_it(err)
    assert "Traceback" not in err, "the traceback still went to stderr"
    assert "Traceback" in logged_lines and "RuntimeError" in logged_lines, (
        "the run lost its own account of how it died")


def test_an_ordinary_run_still_prints_its_traceback_to_stderr(
        tmp_path, monkeypatch, capsys):
    """⭐ ACCEPT POLARITY — where an operator has always looked."""
    _die_at_the_first_phase(tmp_path, monkeypatch, CHAT)
    err = capsys.readouterr().err

    assert "Traceback" in err and SECRET in err


# ══ 7. a line belongs to the run it was written FOR (last repair) ══════════
#
# ⛔⛔ THE FIRST RULE ASKED WHICH RUN WAS ARMED NOW. Every line written while a
# private run was running was treated as that run's — an ordinary run's late
# hand-off, the owner's alarms, Reset Backend's record of stopping other
# people's jobs — and a teardown that raised kept a finished run's id alive to
# silence the machine for hours. The rule now asks where the line CAME FROM.
# Each case below drives the real `run_pipeline_captured`, with a body that
# sets the run up with the real `setup_firestore_run`/`teardown_firestore_run`
# exactly as `run_pipeline` does, and fails against the previous commit.

RUN_ID = "incognito_1758400000000_7_20260922_101500"


def _a_run_with(monkeypatch, tmp_path, rid, during):
    """The REAL `run_pipeline_captured` for `rid`, whose body sets the run up,
    awaits `during()` while it runs, and tears it down."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", None)

    async def _body(*_a, **_k):
        research.setup_firestore_run(SHARER, rid)
        try:
            await during()
        finally:
            research.teardown_firestore_run()

    monkeypatch.setattr(research, "run_pipeline", _body)
    return research.run_pipeline_captured(
        topic=SECRET, research_id=rid, uid=SHARER, run_id=RUN_ID)


def test_an_ordinary_runs_late_hand_off_still_reaches_backend_log_while_a_private_run_runs(
        tmp_path, monkeypatch, capsys):
    """⛔⛔ THE REVIEWER'S CASE. Member A's ordinary run ends and its P4/P5
    drive — a raw thread — keeps the POST open for minutes. The worker dequeues
    member B's private run at once. Every line the drive then wrote was judged
    by B's run: kept off `backend.log` and written into B's folder, which is
    deleted when B ends — so a drive that failed for an ORDINARY run left no
    record anywhere. It is the real drive, started before B, writing while B
    runs."""
    private_is_running = threading.Event()
    drive_is_done = threading.Event()

    def _ordinary_drive():
        private_is_running.wait(10)
        try:
            research._drive_cloud_phases(
                SHARER, CHAT, post=lambda *_a: (503, "busy"),
                mint_token=lambda: "tok", sleep=lambda _s: None,
                note=lambda _l: None, record_failure=lambda _r: None)
        finally:
            drive_is_done.set()

    threading.Thread(target=_ordinary_drive, daemon=True).start()

    async def _during():
        private_is_running.set()
        await asyncio.to_thread(drive_is_done.wait, 10)

    asyncio.run(_a_run_with(monkeypatch, tmp_path, INCOG, _during))
    out = capsys.readouterr().out

    assert drive_is_done.is_set(), "the ordinary run's drive never finished"
    assert "P4/P5 gave up" in out and f"rid={CHAT[:8]}" in out, (
        f"the ordinary run's hand-off went missing from backend.log:\n{out}")


def test_the_owners_alarm_from_a_standing_loop_reaches_backend_log_while_a_private_run_runs(
        tmp_path, monkeypatch, capsys):
    """⛔⛔ THE RELINK NOTICE BEFORE THE PROCESS EXITS. `run_server` starts the
    revoked-credential loop, the reconnect loop and the device-command listener
    — none of them is a run's work, and while a private run was armed their
    lines went only into its folder. The owner's last line before `os._exit`
    was written nowhere they could read."""
    relink = ("[relink] giving up — this serve is stopping now; nothing on this "
              "computer will restart it")

    async def _server():
        started, said = asyncio.Event(), asyncio.Event()

        async def _standing_loop():      # started by the server, not by a run
            await started.wait()
            research.log(relink, "ERROR")
            said.set()

        task = asyncio.create_task(_standing_loop())

        async def _during():
            started.set()
            await said.wait()

        await _a_run_with(monkeypatch, tmp_path, INCOG, _during)
        await task

    asyncio.run(_server())

    assert relink in capsys.readouterr().out


def test_a_teardown_that_raises_still_lets_go_of_the_run(monkeypatch, capsys):
    """⛔ `run_pipeline`'s finally survives an unsubscribe that raises, on
    purpose — and the run's ids stayed behind it, naming a finished private run
    to everything that asks, until the next run's setup hours later."""
    class _Stuck:
        def unsubscribe(self):
            raise RuntimeError("the listen stream was already closed")

    monkeypatch.setattr(research, "_fb_uid", SHARER)
    monkeypatch.setattr(research, "_fb_research_id", INCOG)
    monkeypatch.setattr(research, "_fb_listener", _Stuck())

    with pytest.raises(RuntimeError):
        research.teardown_firestore_run()

    assert (research._fb_uid, research._fb_research_id) == (None, None), (
        "a teardown that raised left the finished run's ids behind")
    research.log("[reconnect] Firestore unreachable — retrying in 30s", "WARN")
    assert "[reconnect] Firestore unreachable" in capsys.readouterr().out


@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_every_hop_of_the_runs_own_work_carries_its_origin(
        tmp_path, monkeypatch, capsys, rid):
    """⭐ THE ORIGIN GOES WHERE THE WORK GOES — a task the pipeline creates and a
    `to_thread` hop it makes are still the run's, in both directions."""
    async def _a_task():
        research.log(f"task: {SECRET}")

    async def _during():
        research.log(f"direct: {SECRET}")
        await asyncio.to_thread(research.log, f"to_thread: {SECRET}")
        await asyncio.create_task(_a_task())

    asyncio.run(_a_run_with(monkeypatch, tmp_path, rid, _during))
    out = capsys.readouterr().out
    [run_log] = list(research._runs_log_root().glob("*/run.log"))
    kept = run_log.read_text(encoding="utf-8")

    for hop in ("direct", "to_thread", "task"):
        assert f"{hop}: {SECRET}" in kept, f"the run's folder lost its {hop} line"
        if rid == INCOG:
            assert f"{hop}: " not in out, f"the private run's {hop} line reached backend.log"
        else:
            assert f"{hop}: {SECRET}" in out, f"an ordinary run's {hop} line went missing"


def test_a_private_run_whose_folder_was_refused_keeps_its_lines_out_anyway(
        tmp_path, monkeypatch, capsys):
    """⛔ THE CAPTURE NEVER RAISES INTO A RUN, so a disk that refused the folder
    arms nothing — and the pipeline's first lines come before its Firestore
    setup. Neither is what says whose line it is. ⭐ And the machine's own line
    about its disk is still the owner's."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))

    def _refused():
        raise OSError("No space left on device")

    monkeypatch.setattr(research, "_runs_log_root", _refused)

    async def _body(*_a, **_k):
        research.log(f"Topic: {SECRET}")

    monkeypatch.setattr(research, "run_pipeline", _body)
    asyncio.run(research.run_pipeline_captured(
        topic=SECRET, research_id=INCOG, uid=SHARER, run_id=RUN_ID))
    out = capsys.readouterr().out

    _says_nothing_of_it(out)
    assert "capture unavailable for this run" in out


def test_the_owner_is_told_a_private_run_ended(tmp_path, monkeypatch, capsys):
    """⭐ "TOLD A RUN HAPPENED, NEVER ITS TOPIC" — the other half. The run's
    origin ends with the run's work, so the line saying its folders were taken
    off this computer is the machine's and reaches the owner."""
    async def _during():
        queue_dir = tmp_path / "queues" / RUN_ID
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "delivery.json").write_text(
            json.dumps({"status": "completed"}), encoding="utf-8")

    asyncio.run(_a_run_with(monkeypatch, tmp_path, INCOG, _during))
    out = capsys.readouterr().out

    assert f"[incognito] {INCOG[:8]}… ended — its run folder" in out, out
    _says_nothing_of_it(out)
