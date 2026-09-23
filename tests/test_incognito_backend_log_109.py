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
import json
import os
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


# ══ 1. the console decides, through the real `log()` ══════════════════════

def test_an_ordinary_run_still_prints_every_line_it_writes(capsys):
    """⭐ ACCEPT POLARITY FIRST. A console rule that swallowed everything would
    pass every refusal below and leave the owner a log with nothing in it."""
    sink = _arm(CHAT)
    research.log(f"Phase 2: off-topic sweep is INERT this run: topic {SECRET!r}")

    assert SECRET in capsys.readouterr().out
    assert SECRET in "\n".join(sink.lines)


def test_a_line_a_run_that_keeps_nothing_writes_stays_out_of_backend_log(capsys):
    """⛔⛔ THE DEFECT. Every line the run writes was printed to the worker's
    stdout — which IS `backend.log` — as well as into the run's own folder, and
    only the folder is removed when the run ends."""
    sink = _arm(INCOG)
    research.log(f"Phase 2: off-topic sweep is INERT this run: topic {SECRET!r}")

    _says_nothing_of_it(capsys.readouterr().out)
    # ⭐ AND THE RUN STILL HAS ITS OWN ACCOUNT, in the folder that leaves with it.
    assert SECRET in "\n".join(sink.lines), (
        "the line was dropped instead of kept in the run's own folder")


def test_a_machine_line_written_while_it_runs_still_reaches_backend_log(capsys):
    """⭐ THE MACHINE'S OWN LINES ARE NOT THE RUN'S. The heartbeat, the sweeps
    and the start listener write inside the machine scope, and the owner's log
    must keep them — a private run on a shared computer cannot blind its owner
    to what the computer is doing."""
    _arm(INCOG)
    with research._machine_log_scope():
        research.log("[heartbeat] device doc refreshed")

    assert "[heartbeat] device doc refreshed" in capsys.readouterr().out


def test_a_run_whose_folder_could_not_be_armed_is_still_recognised(capsys, monkeypatch):
    """⛔ THE CAPTURE NEVER RAISES INTO THE RUN, so a disk that refused the run
    folder leaves no sink at all — and every line of that run would have gone
    to `backend.log`. The pipeline's own research id is the second witness."""
    monkeypatch.setattr(research, "_fb_research_id", INCOG)
    research.log(f"Phase 1: Injecting user feedback: {SECRET}")

    _says_nothing_of_it(capsys.readouterr().out)


def test_the_second_witness_still_prints_an_ordinary_run(capsys, monkeypatch):
    """⭐ ACCEPT POLARITY for the witness above."""
    monkeypatch.setattr(research, "_fb_research_id", CHAT)
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
# ⛔ THE FOLDER'S ATTRIBUTION ENDS WHEN THE RUN DOES. A raw thread the pipeline
# spawned and that is still writing after the run has returned reaches
# `backend.log` as a machine line — and for a run that keeps nothing, phases 3
# and 4 are off, so the run ends seconds after the title refresh is dispatched.

class _LateThread:
    """Runs the worker when started — AFTER the run has ended, which is when a
    slow title model answers for a run that keeps nothing."""

    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        research._fb_research_id = None
        self._target()


@pytest.mark.parametrize("verdict", ["refuse_loud", "refuse_silent"])
@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_a_late_title_refusal_names_no_incognito_topic_words(
        monkeypatch, logged, rid, verdict):
    """The refusal lines print the topic's distinctive WORDS — the anchors — so
    an operator can see why a title was thrown away. For a run that keeps
    nothing those words are its subject."""
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(research, "_try_llm_title", lambda *a, **k: "Golden Retriever Care")
    monkeypatch.setattr(research, "title_refusal_verdict", lambda *a, **k: verdict)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_threading",
                        types.SimpleNamespace(Thread=_LateThread))
    monkeypatch.setattr(research, "_fb_research_id", rid)

    research._refresh_research_title_async(SECRET, "", "findings")
    blob = "\n".join(logged)

    assert "[title-refresh]" in blob, "the refusal branch was not reached"
    if rid == INCOG:
        _says_nothing_of_it(blob)
    else:
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
