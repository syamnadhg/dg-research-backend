"""A run's folder holds only its own lines — never a line another run wrote late.

⛔⛔ WHAT WAS WRONG (wave 10.10). Wave 10.9's last repair taught `log()` to
decide what `backend.log` holds back by a line's ORIGIN — `_LOG_RUN`, set around
exactly one run's own work and carried by every task and `to_thread` hop it
makes. The folder copy was left asking only which folder was armed at write
time. A private run's work that outlives the run — a copied-context thread still
inside a fetch, a `to_thread` worker whose awaiter was cancelled — then wrote
into the NEXT person's run folder, while (correctly) staying out of the owner's
log. That folder ships in that person's support bundle.

⭐ THE FOUR CASES, EACH EXECUTED THROUGH THE REAL `log()` INTO A REAL FOLDER:
  · same origin as the folder's research   → written
  · a different origin                      → not written
  · no origin (machine / server / SDK line) → written, as it always was: the
    per-run command listener's STOP lines have no origin and are the only
    account some runs keep of how they ended (`test_machine_log_scope_0824`)
  · an origin, and a folder whose research is unknown → not written

Then the consumer: two real `run_pipeline_captured` runs back to back, the first
leaving a copied-context thread behind that writes while the second runs.

Run:  pytest tests/test_log_folder_origin_1010.py -v
"""
import asyncio
import contextlib
import contextvars
import json
import threading

import pytest

import research

INCOG = "incog_1758400000000_4"
CHAT = "chat_1758400000000_4"
OTHER = "chat_1758400000000_9"
SECRET = "my custody hearing notes"


@pytest.fixture(autouse=True)
def _nothing_armed(monkeypatch):
    assert research._LOG_RUN.get() is None, "a test before this one leaked a run origin"
    saved = list(research._RUN_LOG_SINKS)
    research._RUN_LOG_SINKS.clear()
    monkeypatch.setattr(research, "_fb_research_id", None)
    yield
    for sink in research._RUN_LOG_SINKS:
        with contextlib.suppress(Exception):
            sink.writer.close()
    research._RUN_LOG_SINKS.clear()
    research._RUN_LOG_SINKS.extend(saved)


def _folder(tmp_path, research_id, name="armed"):
    """A REAL run folder — the `_RunLogSink` the capture arms — pushed on the
    stack the way `_RunLogCapture.__enter__` pushes it."""
    sink = research._RunLogSink(tmp_path / name, research_id=research_id)
    research._RUN_LOG_SINKS.append(sink)
    return sink


def _kept(sink):
    return (sink.dir / "run.log").read_text(encoding="utf-8")


@contextlib.contextmanager
def _origin(research_id):
    token = research._LOG_RUN.set(research_id)
    try:
        yield
    finally:
        research._LOG_RUN.reset(token)


# ══ 1. each combination, through the real `log()` and the real folder ══════

@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_a_runs_own_line_is_written_into_its_folder(tmp_path, rid):
    """⭐ ACCEPT POLARITY FIRST. A rule that wrote nothing would pass every
    refusal below and leave every run with an empty folder."""
    sink = _folder(tmp_path, rid)
    with _origin(rid):
        research.log(f"Phase 1: Injecting user feedback: {SECRET}")

    assert SECRET in _kept(sink)


def test_a_private_runs_late_line_stays_out_of_an_ordinary_runs_folder(tmp_path, capsys):
    """⛔⛔ THE VERIFIER'S CASE. The line carries the private run's origin; the
    ordinary run's folder is armed. It stayed out of `backend.log` and went
    into the ordinary run's folder — which rides that person's bundle."""
    sink = _folder(tmp_path, CHAT)
    with _origin(INCOG):
        research.log(f"[doc-images] fetch finished for {SECRET}")

    assert SECRET not in _kept(sink), "a private run's line landed in another person's folder"
    assert SECRET not in capsys.readouterr().out, "…and the console rule broke too"


def test_an_ordinary_runs_late_line_stays_out_of_the_next_runs_folder(tmp_path, capsys):
    """⛔ THE SAME RULE, THE OTHER WAY ROUND. An ordinary run's late line is
    not the next person's business either — and it still reaches the owner's
    log, which is where the machine keeps it."""
    sink = _folder(tmp_path, OTHER)
    with _origin(CHAT):
        research.log(f"[title-refresh] kept the name ({SECRET})")

    assert SECRET not in _kept(sink)
    assert SECRET in capsys.readouterr().out, "an ordinary run's line vanished from backend.log"


def test_a_line_with_no_origin_still_reaches_the_armed_folder(tmp_path, capsys):
    """⭐ NO ORIGIN IS THE MACHINE'S OR THE SERVER'S, AND IT STAYS AS IT WAS.
    The per-run command listener runs on an SDK thread no context reaches; its
    `Command received: STOP` is the only record some runs keep of how they
    ended. A rule that treated "no origin" as "another run" would take it out."""
    sink = _folder(tmp_path, CHAT)
    research.log("[cmd] Command received: STOP")

    assert "Command received: STOP" in _kept(sink)
    assert "Command received: STOP" in capsys.readouterr().out


def test_a_line_with_no_origin_reaches_a_folder_whose_research_is_unknown(tmp_path):
    """⭐ A CLI run mints its own id and arms a folder with no research id; it
    sets no origin, so every one of its own lines must still land."""
    sink = _folder(tmp_path, None)
    research.log(f"Topic: {SECRET}")

    assert SECRET in _kept(sink)


def test_a_line_with_an_origin_stays_out_of_a_folder_whose_research_is_unknown(tmp_path):
    """⛔ THE LINE IS KNOWN TO BE ONE RUN'S, and a folder that cannot say it is
    that run's does not get it."""
    sink = _folder(tmp_path, None)
    with _origin(INCOG):
        research.log(f"[doc-images] fetch finished for {SECRET}")

    assert SECRET not in _kept(sink)


def test_the_retry_folder_of_the_same_run_keeps_its_lines(tmp_path):
    """⭐ A CRASH RETRY ARMS A SECOND FOLDER FOR THE SAME RESEARCH, on top of
    the first. Both are the run's; the line goes to the top one, as before."""
    outer = _folder(tmp_path, INCOG, "first")
    inner = _folder(tmp_path, INCOG, "retry")
    with _origin(INCOG):
        research.log(f"retry: {SECRET}")

    assert SECRET in _kept(inner)
    assert SECRET not in _kept(outer)


# ══ 2. the consumer: two real runs, one late thread ════════════════════════
#
# ⛔ A TESTED RULE IS NOT A TESTED RUN. The real `run_pipeline_captured` arms
# the real folder and sets the real origin; only the pipeline body is replaced.

def _run(monkeypatch, rid, body):
    async def _pipeline(*_a, **_k):
        await body()

    monkeypatch.setattr(research, "run_pipeline", _pipeline)
    return research.run_pipeline_captured(
        topic=SECRET, research_id=rid, uid="uid-member",
        run_id=f"run_{rid}_20260923_101500")


def _folder_of(rid):
    for meta in research._runs_log_root().glob("*/meta.json"):
        if json.loads(meta.read_text(encoding="utf-8")).get("researchId") == rid:
            return (meta.parent / "run.log").read_text(encoding="utf-8")
    raise AssertionError(f"no folder for {rid}")


@pytest.mark.parametrize("first,second", [(INCOG, CHAT), (CHAT, OTHER)])
def test_a_thread_the_first_run_left_behind_writes_nothing_into_the_second_runs_folder(
        tmp_path, monkeypatch, capsys, first, second):
    """⛔⛔ THE CONSUMER. The first run starts a copied-context worker — the
    shape the document-image rehost and the alert-copy draft both use — and
    ends while it is still busy. The worker writes while the NEXT run is armed."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    second_is_running = threading.Event()
    late_line_written = threading.Event()

    def _late_work():
        second_is_running.wait(10)
        research.log(f"[doc-images] late fetch finished: {SECRET}")
        late_line_written.set()

    async def _first_body():
        research.log("first run: own line")
        ctx = contextvars.copy_context()
        threading.Thread(target=ctx.run, args=(_late_work,), daemon=True).start()

    async def _second_body():
        research.log("second run: own line")
        second_is_running.set()
        await asyncio.to_thread(late_line_written.wait, 10)

    asyncio.run(_run(monkeypatch, first, _first_body))
    asyncio.run(_run(monkeypatch, second, _second_body))
    out = capsys.readouterr().out

    assert late_line_written.is_set(), "the late worker never wrote"
    second_folder = _folder_of(second)
    assert "second run: own line" in second_folder, "the second run lost its own line"
    assert SECRET not in second_folder, (
        f"the first run's late line landed in the second run's folder:\n{second_folder}")
    if first == INCOG:
        assert SECRET not in out, "a private run's late line reached backend.log"
    else:
        assert SECRET in out, "an ordinary run's late line vanished from backend.log"


# ══ 3. the run's own late threads — title refresh, summary, phase-3 save ═══
#
# ⛔⛔ THE KNOWN THREE (wave 10.10 repair). Each is a RAW thread the run starts
# and does not wait for: a model call for the title and the summary, an ffprobe
# per podcast for the phase-3 save. A raw thread starts with an empty context,
# so its lines had NO origin and went into whatever folder was armed when they
# were written — the next run's. Each is dispatched through its REAL function
# from inside the first run; only the slow call it waits on is replaced, and
# that replacement writes the line once the second run is running.

def _late_dispatch(monkeypatch, which, write_late):
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(research, "_update_research_doc", lambda *a, **k: True)
    if which == "title":
        monkeypatch.setattr(research, "_try_llm_title", lambda *a, **k: write_late() or "")
        return lambda: research._refresh_research_title_async(SECRET, "brief", "findings")
    if which == "summary":
        monkeypatch.setattr(research, "_try_llm_summary", lambda *a, **k: write_late() or "")
        return lambda: research._generate_research_summary_async(SECRET, "brief", "findings")
    monkeypatch.setattr(research, "save_meta", lambda *a, **k: write_late())
    return lambda: research._save_meta_in_background("unused", SECRET, 3)


@pytest.mark.parametrize("which", ["title", "summary", "phase3-save"])
def test_a_late_thread_of_the_run_writes_nothing_into_the_next_runs_folder(
        tmp_path, monkeypatch, capsys, which):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    second_is_running = threading.Event()
    late_line_written = threading.Event()

    def _write_late():
        second_is_running.wait(10)
        research.log(f"[{which}] late answer for {SECRET}", "WARN")
        late_line_written.set()

    dispatch = _late_dispatch(monkeypatch, which, _write_late)

    async def _first_body():
        research.log("first run: own line")
        dispatch()

    async def _second_body():
        research.log("second run: own line")
        second_is_running.set()
        await asyncio.to_thread(late_line_written.wait, 10)

    asyncio.run(_run(monkeypatch, CHAT, _first_body))
    asyncio.run(_run(monkeypatch, OTHER, _second_body))
    out = capsys.readouterr().out

    assert late_line_written.is_set(), "the late thread never wrote — this measured nothing"
    second_folder = _folder_of(OTHER)
    assert "second run: own line" in second_folder
    assert SECRET not in second_folder, (
        f"the {which} thread's late line landed in the next run's folder:\n{second_folder}")
    assert SECRET in out, "an ordinary run's late line vanished from backend.log"
