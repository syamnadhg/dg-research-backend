"""Wave 2 step 1 — the run that dies has to leave a folder behind.

⛔⛔ WHAT THIS EXISTS FOR, MEASURED 2026-08-18. A support bundle cannot be cut
out of `backend.log` after the fact: `log()` stamps time with NO date, the run
marker appears eight times in 676,014 lines and fires at the Firestore claim
rather than at dequeue, and 87.1% of the bytes are one uvicorn access line. So
capture happens at write time or not at all.

⭐⭐ AND THE CASE THAT RESHAPED IT: the founding incident produced NO RUN. A run
index written at DISARM is exactly the container that cannot hold the run that
died — so `meta.json` is written at ARM, and a reader derives the corpse.

The assertions below are grouped by the failure each one prevents, and the
sharpest ones are the accept-polarity pins: a guard that rejects every honest
input ships nothing, which is how the first draft of the id regex would have
gone out.
"""
import ast
import asyncio
import inspect
import json
import os
import re
import textwrap
import time
from pathlib import Path

import pytest

import research


# ══ helpers ════════════════════════════════════════════════════════════
def _runs(tmp):
    return research._runs_log_root()


def _read(path):
    return path.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_stack():
    research._RUN_LOG_SINKS.clear()
    research._RUN_LOG_LAST_DIR = None
    yield
    research._RUN_LOG_SINKS.clear()


# ══ 1. the folder key — where a topic could have leaked ════════════════
def test_the_folder_key_function_cannot_be_handed_a_run_id():
    """⛔ THE PIN THAT MATTERS. `run_id` is `safe_name(topic)_YYYYMMDD_HHMMSS`,
    so it CARRIES THE USER'S TOPIC, and at the worker's claim both names sit in
    scope one line apart. The defence is that the parameter does not exist."""
    params = set(inspect.signature(research._run_log_folder_name).parameters)
    assert "run_id" not in params, (
        "a `run_id` parameter reintroduces the topic leak this signature exists "
        f"to make unrepresentable — parameters are {sorted(params)}")
    assert "topic" not in params
    assert params == {"research_id", "started_utc", "attempt"}


def test_a_real_research_id_is_ACCEPTED_as_the_folder_key():
    """⭐ ACCEPT POLARITY. The first draft of this guard was
    `^[A-Za-z0-9]{20}$`, which rejects every real id — a guard that fires on
    every honest input, i.e. a feature that never works. Real ids are minted
    `chat_${Date.now()}_${counter}` by the frontend."""
    name = research._run_log_folder_name("chat_1755500000000_3", "2026-08-18T15:30:44Z")
    assert name.startswith("chat_1755500000000_3_"), name
    assert "local" not in name


def test_a_run_id_shaped_string_never_becomes_the_folder_key():
    """A one-word topic survives `safe_name` as bare alphanumerics, so the
    character allow-list alone would accept `kalki_20260818_153044`."""
    name = research._run_log_folder_name("kalki_20260818_153044", "2026-08-18T15:30:44Z")
    assert name.startswith("local_"), name
    assert "kalki" not in name


def test_a_topic_with_spaces_or_slashes_never_becomes_the_folder_key():
    for hostile in ("Kalki 2898 AD box office", "../../etc/passwd",
                    "topic\nwith\nnewlines", "a" * 200):
        name = research._run_log_folder_name(hostile, "2026-08-18T15:30:44Z")
        assert name.startswith("local_"), (hostile, name)
        assert "/" not in name and "\\" not in name and " " not in name


def test_no_research_id_falls_back_to_a_local_folder():
    assert research._run_log_folder_name(None, "2026-08-18T15:30:44Z") == \
        "local_20260818T153044"


def test_a_retry_gets_its_own_folder_name():
    first = research._run_log_folder_name("chat_1755500000000_3", "2026-08-18T15:30:44Z", 0)
    retry = research._run_log_folder_name("chat_1755500000000_3", "2026-08-18T15:30:44Z", 1)
    assert first != retry
    assert retry.endswith("_retry1")


# ══ 2. meta at arm, and the corpse a reader derives ════════════════════
def test_meta_json_exists_and_says_running_the_moment_the_run_is_armed():
    """⭐⭐ The whole point. A disarm-only index cannot hold the run that died."""
    with research._RunLogCapture(research_id="chat_1755500000000_9") as sink:
        assert sink is not None
        meta = json.loads(_read(sink.meta_path))
        assert meta["status"] == "running"
        assert meta["pid"] == os.getpid()
        assert meta["researchId"] == "chat_1755500000000_9"
        assert meta["startedUtc"].endswith("Z") and meta["startedUtc"].count("-") == 2


def test_a_meta_still_saying_running_with_a_dead_pid_reads_as_process_died():
    meta = {"status": "running", "pid": 999_999_999,
            "startedUtc": research._utc_iso()}
    assert research._derive_run_status(meta) == "process-died"


def test_a_live_pid_on_a_fresh_run_still_reads_as_running():
    """Accept polarity again: the derivation must not call live runs corpses."""
    meta = {"status": "running", "pid": os.getpid(),
            "startedUtc": research._utc_iso()}
    assert research._derive_run_status(meta) == "running"


def test_pid_liveness_ALONE_is_not_enough_because_pids_recycle():
    """⛔ A recycled pid relabels a dead run as running — which is how the run
    that died stays invisible. The age ceiling is the second, independent test."""
    meta = {"status": "running", "pid": os.getpid(),
            "startedUtc": research._utc_iso()}
    stale = time.time() + research.RUN_LOG_DEAD_AFTER_SEC + 60
    assert research._derive_run_status(meta, now_epoch=stale) == "process-died"


def test_a_finished_run_keeps_its_own_verdict():
    for status in ("complete", "errored", "cancelled", "watchdog"):
        assert research._derive_run_status({"status": status, "pid": 1}) == status


def test_the_dead_ceiling_clears_the_worker_watchdogs_own_ceiling():
    """⛔ Relationship pin. If the watchdog ceiling is raised and this constant
    is not, every long-but-healthy run gets relabelled a corpse."""
    src = inspect.getsource(research)
    m = re.search(r"WORKER_OUTER_TIMEOUT_SEC = (\d+) \* (\d+) \* (\d+)", src)
    assert m, "the worker watchdog ceiling moved — re-anchor this pin"
    ceiling = int(m.group(1)) * int(m.group(2)) * int(m.group(3))
    assert research.RUN_LOG_DEAD_AFTER_SEC >= ceiling + 3600, (
        f"watchdog ceiling is {ceiling}s but a run is called dead after "
        f"{research.RUN_LOG_DEAD_AFTER_SEC}s — raise RUN_LOG_DEAD_AFTER_SEC")


# ══ 3. the cap keeps the HEAD and the LAST LINE ════════════════════════
def test_the_cap_is_head_plus_rolling_tail_not_stop_at_cap(tmp_path):
    """⛔ A wedged pairing's diagnostic payload is its LAST line. A writer that
    stops at the cap throws away exactly the half worth having."""
    w = research._CappedLogWriter(tmp_path / "run.log", max_bytes=2000,
                                  segment_bytes=500, keep=2)
    w.write_line("FIRST-LINE-MARKER")
    for i in range(600):
        w.write_line(f"filler line {i:04d} " + "x" * 40)
    w.write_line("LAST-LINE-MARKER")
    w.close()

    head = _read(tmp_path / "run.log")
    assert "FIRST-LINE-MARKER" in head, "the head was thrown away"
    tail = "".join(_read(p) for p in w.paths() if p.exists())
    assert "LAST-LINE-MARKER" in tail, "the last line — the payload — was dropped"
    assert w.dropped_segments > 0, "nothing rolled; this test measured nothing"
    live = [p for p in w.paths()[1:] if p.exists()]
    assert len(live) <= 2, f"more than `keep` segments survive: {live}"


def test_the_head_names_where_the_rest_went(tmp_path):
    w = research._CappedLogWriter(tmp_path / "run.log", max_bytes=300,
                                  segment_bytes=300, keep=2)
    for i in range(50):
        w.write_line("y" * 60)
    w.close()
    assert "overflow1" in _read(tmp_path / "run.log")


def test_a_writer_whose_disk_fails_never_raises_into_the_caller(tmp_path):
    w = research._CappedLogWriter(tmp_path / "run.log")
    w.close()
    w.write_line("after close")  # must not raise
    w._fh = object()             # a handle with no .write at all
    w.write_line("into a broken handle")


# ══ 4. what the user actually SAW ══════════════════════════════════════
def test_ansi_is_stripped_and_carriage_returns_collapse():
    assert research._visible_text("\x1b[32mgreen\x1b[0m") == "green"
    assert research._visible_text("working...\rworking....\rdone") == "done"
    assert research._visible_text("\x1b[2K\r  ✓  Paired") == "  ✓  Paired"


def test_a_spinner_burst_becomes_one_line_not_twelve_hundred(tmp_path):
    """⭐ `\\r` is NOT an escape sequence, so an ANSI-only strip keeps every
    frame — at ~10 frames/sec a two-minute pairing wait rebuilds the exact wall
    of byte-identical lines this wave exists to remove."""
    w = research._CappedLogWriter(tmp_path / "pair.log")
    tee = research._SessionTee(_Sink(), w)
    for i in range(1200):
        tee.write("\r  ◆  Waiting for the browser…")
    tee.write("\n")
    tee.close_mirror()
    w.close()
    body = [ln for ln in _read(tmp_path / "pair.log").splitlines() if "Waiting" in ln]
    assert len(body) == 1, f"{len(body)} spinner lines reached the file"


def test_a_spinner_that_never_prints_a_newline_cannot_grow_the_buffer(tmp_path):
    """⛔ Found by mutation. The collapse-at-newline test above passes with no
    bound at all, because the collapse also happens when the newline finally
    arrives. A pairing spinner that runs for thirty minutes never sends one."""
    w = research._CappedLogWriter(tmp_path / "pair.log")
    tee = research._SessionTee(_Sink(), w)
    for _ in range(20000):
        tee.write("\r  ◆  Waiting for the browser to come back…")
    assert len(tee._buf) < 8192, (
        f"the mirror buffer reached {len(tee._buf)} chars with no newline in "
        "sight — an unbounded copy of a spinner")


class _Sink:
    """A stand-in terminal that records exactly what was written to it."""

    def __init__(self):
        self.chunks = []

    def write(self, s):
        self.chunks.append(s)
        return len(s)

    def flush(self):
        return None

    def isatty(self):
        return True

    @property
    def text(self):
        return "".join(self.chunks)


def test_the_terminal_output_is_byte_for_byte_unchanged(tmp_path):
    w = research._CappedLogWriter(tmp_path / "pair.log")
    sink = _Sink()
    tee = research._SessionTee(sink, w)
    payload = "\x1b[32m  ✓  Paired\x1b[0m\rredrawn\n"
    tee.write(payload)
    assert sink.text == payload, "the tee altered what the user sees"


def test_a_mirror_that_explodes_still_lets_the_terminal_through(tmp_path):
    class _Boom:
        def write_line(self, _t):
            raise RuntimeError("disk gone")

    sink = _Sink()
    tee = research._SessionTee(sink, _Boom())
    tee.write("still visible\n")
    assert sink.text == "still visible\n"


def test_the_tee_delegates_everything_else_to_the_real_stream(tmp_path):
    w = research._CappedLogWriter(tmp_path / "pair.log")
    tee = research._SessionTee(_Sink(), w)
    assert tee.isatty() is True, (
        "isatty stopped delegating — colour/tty decisions downstream would flip")


def test_a_partial_last_line_is_not_lost_when_the_command_exits(tmp_path):
    w = research._CappedLogWriter(tmp_path / "pair.log")
    tee = research._SessionTee(_Sink(), w)
    tee.write("Enter the code: ")   # no newline — the prompt a user died on
    tee.close_mirror()
    w.close()
    assert "Enter the code:" in _read(tmp_path / "pair.log")


# ══ 5. log() write-through ═════════════════════════════════════════════
def test_the_printed_line_is_unchanged_and_a_copy_reaches_the_run_folder(capsys):
    with research._RunLogCapture(research_id="chat_1755500000000_1") as sink:
        research.log("hello from the pipeline", "WARN")
        printed = capsys.readouterr().out
        assert re.fullmatch(r"\[\d\d:\d\d:\d\d\] \[WARN\] hello from the pipeline\n",
                            printed), repr(printed)
        assert "hello from the pipeline" in _read(sink.writer.primary)


def test_the_write_through_is_a_no_op_with_nothing_armed(capsys):
    research.log("no sink armed", "INFO")
    assert "no sink armed" in capsys.readouterr().out


def test_a_failing_sink_cannot_recurse_back_through_log(capsys):
    """A write-through that logs its own failure is an infinite loop."""
    class _Recursive:
        dir = "x"

        def note_line(self, line, level="INFO"):
            research.log("inner", "ERROR")
            raise RuntimeError("boom")

    research._RUN_LOG_SINKS.append(_Recursive())
    try:
        research.log("outer", "INFO")
    finally:
        research._RUN_LOG_SINKS.pop()
    out = capsys.readouterr().out
    assert out.count("inner") == 1, "the write-through recursed"


def test_warn_and_error_lines_are_counted_in_the_meta():
    with research._RunLogCapture(research_id="chat_1755500000000_2") as sink:
        research.log("a", "INFO")
        research.log("b", "WARN")
        research.log("c", "ERROR")
    meta = json.loads(_read(sink.meta_path))
    assert meta["counters"]["warns"] == 1
    assert meta["counters"]["errors"] == 1
    assert meta["counters"]["lines"] >= 3


# ══ 6. the emit_event tap, above the guard ═════════════════════════════
def test_the_tap_fires_even_with_no_firestore_run(monkeypatch):
    """⛔ THE CANNOT-FIRE PIN. Behind `if not _tracks_dir: return` the mirror
    drops every event from a run whose Firestore setup is the thing that failed
    — and absence would read as health."""
    monkeypatch.setattr(research, "_tracks_dir", None)
    with research._RunLogCapture(research_id="chat_1755500000000_4") as sink:
        research.emit_event("phase_start", phase=2, agent="claude")
        assert [e["type"] for e in sink.events] == ["phase_start"]
        assert sink.events[0]["phase"] == 2
        assert sink.events[0]["agent"] == "claude"


def test_the_tap_forwards_no_data_at_all(monkeypatch, tmp_path):
    """A topic through `**data` is how free text re-enters a content-free path."""
    monkeypatch.setattr(research, "_tracks_dir", None)
    sentinel = "KALKI-2898-AD-SENTINEL"
    with research._RunLogCapture(research_id="chat_1755500000000_5") as sink:
        research.emit_event("phase_complete", phase=3, detail=sentinel,
                            topic=sentinel, durationSec=12)
    for path in sink.dir.rglob("*"):
        if path.is_file():
            assert sentinel not in path.read_text(encoding="utf-8", errors="replace"), \
                f"the sentinel reached {path.name}"


def test_the_event_mirror_is_bounded(monkeypatch):
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "RUN_LOG_EVENT_CAP", 10)
    with research._RunLogCapture(research_id="chat_1755500000000_6") as sink:
        for i in range(40):
            research.emit_event("phase_start", phase=i % 5)
        assert len(sink.events) <= 11, len(sink.events)
        assert sink.counters["eventsDropped"] > 0


# ══ 7. nesting, because the pipeline awaits itself ═════════════════════
def test_two_attempts_in_one_process_get_two_folders_and_the_outer_resumes():
    """⛔ #725's crash-retry AWAITS run_pipeline from inside itself. A singleton
    sink would give the retry the parent's folder and lose the outer's tail."""
    with research._RunLogCapture(research_id="chat_1755500000000_7") as outer:
        research.log("outer before", "INFO")
        with research._RunLogCapture(research_id="chat_1755500000000_7",
                                     attempt=1) as inner:
            research.log("inner only", "INFO")
            assert research._active_run_sink() is inner
        assert research._active_run_sink() is outer, "the outer sink never resumed"
        research.log("outer after", "INFO")

    assert outer.dir != inner.dir
    outer_text = _read(outer.writer.primary)
    inner_text = _read(inner.writer.primary)
    assert "outer before" in outer_text and "outer after" in outer_text
    assert "inner only" in inner_text
    assert "inner only" not in outer_text
    assert json.loads(_read(inner.meta_path))["parentResearchId"] == \
        "chat_1755500000000_7"
    assert json.loads(_read(inner.meta_path))["attempt"] == 1


def test_both_metas_are_finalized():
    with research._RunLogCapture(research_id="chat_1755500000000_8") as outer:
        with research._RunLogCapture(research_id="chat_1755500000000_8",
                                     attempt=1) as inner:
            pass
    for sink in (outer, inner):
        meta = json.loads(_read(sink.meta_path))
        assert meta["status"] == "complete", meta
        assert "endedUtc" in meta and "durationSec" in meta


def test_a_run_that_raises_is_finalized_as_errored_with_the_class_named():
    cap = research._RunLogCapture(research_id="chat_1755500000000_a")
    with pytest.raises(ValueError):
        with cap:
            raise ValueError("nope")
    meta = json.loads(_read(cap.sink.meta_path))
    assert meta["status"] == "errored"
    assert meta["errorClass"] == "ValueError"


def test_re_entering_one_capture_cannot_strand_a_sink_on_the_stack():
    """A stranded sink would silently swallow every later line in the process."""
    cap = research._RunLogCapture(research_id="chat_1755500000000_a2")
    with cap as first:
        with cap as second:
            assert second is first
        assert research._active_run_sink() is None
    assert len(research._RUN_LOG_SINKS) == 0


def test_a_cancelled_run_is_not_reported_as_an_error():
    cap = research._RunLogCapture(research_id="chat_1755500000000_b")
    sink = cap.__enter__()
    try:
        cap.__exit__(asyncio.CancelledError, asyncio.CancelledError(), None)
    finally:
        pass
    assert json.loads(_read(sink.meta_path))["status"] == "cancelled"


def test_capture_failing_never_stops_the_run(monkeypatch, capsys):
    monkeypatch.setattr(research, "_runs_log_root",
                        lambda: (_ for _ in ()).throw(OSError("read-only fs")))
    with research._RunLogCapture(research_id="chat_1755500000000_c") as sink:
        assert sink is None
    assert "capture unavailable" in capsys.readouterr().out


# ══ 8. the supervisor's verdict has to reach the folder ════════════════
def test_the_watchdog_can_stamp_a_folder_after_the_capture_already_exited():
    """⭐ The watchdog cancels the task and AWAITS it before raising, so its
    handler runs AFTER the capture finalized. Patching by folder is what makes
    the verdict land at all."""
    with research._RunLogCapture(research_id="chat_1755500000000_d") as sink:
        pass
    assert research._patch_run_log_status("watchdog", watchdogCeilingSec=18000) is True
    meta = json.loads(_read(sink.meta_path))
    assert meta["status"] == "watchdog"
    assert meta["watchdogCeilingSec"] == 18000


def test_the_watchdog_stamps_the_live_folder_when_one_is_still_armed():
    with research._RunLogCapture(research_id="chat_1755500000000_e") as sink:
        assert research._patch_run_log_status("watchdog") is True
        assert json.loads(_read(sink.meta_path))["status"] == "watchdog"


def test_the_patch_is_a_no_op_when_no_run_ever_ran():
    assert research._patch_run_log_status("watchdog") is False


def test_the_watchdog_handler_actually_calls_it():
    src = inspect.getsource(research.run_server)
    assert '_patch_run_log_status("watchdog"' in src, (
        "the worker watchdog no longer stamps the run folder — the bundle would "
        "show a run that merely errored with no cause named")


# ══ 9. nothing may bypass the capture ══════════════════════════════════
def test_no_call_site_bypasses_the_capture():
    """⛔ A new caller wired straight to `run_pipeline` gets no folder, and
    nothing anywhere would say so."""
    tree = ast.parse(inspect.getsource(research))
    offenders = []

    class _Walk(ast.NodeVisitor):
        def __init__(self):
            self.fn = None

        def visit_FunctionDef(self, node):
            prev, self.fn = self.fn, node.name
            self.generic_visit(node)
            self.fn = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "run_pipeline":
                if self.fn != "run_pipeline_captured":
                    offenders.append((self.fn, node.lineno))
            self.generic_visit(node)

    _Walk().visit(tree)
    assert not offenders, (
        "these call `run_pipeline` directly instead of `run_pipeline_captured`, "
        f"so their runs leave no log folder: {offenders}")


def test_the_wrapper_reads_the_research_id_however_it_was_passed():
    kw = research._run_pipeline_capture_key((), {"topic": "t", "research_id": "chat_1_2"})
    assert kw == ("chat_1_2", 0, None)
    # positional: topic, pdf_paths, brief_file, verbose, api_key, email,
    # resume_dir, config, run_id, uid, research_id
    pos = research._run_pipeline_capture_key(
        ("t", None, None, False, None, None, None, None, "run_id_here", None, "chat_3_4"),
        {})
    assert pos == ("chat_3_4", 0, None)


def test_the_wrapper_reads_the_submitter_however_it_was_passed():
    """⭐ BOTH SHAPES, because the two live callers disagree: the dequeue site
    passes `uid=` by keyword and `--resume` passes ten positionals. A lookup
    that only handled one would read None on the other, and an unattributed run
    is indistinguishable from a local one."""
    kw = research._run_pipeline_capture_key(
        (), {"topic": "t", "research_id": "chat_1_2", "uid": "UID_ALICE"})
    assert kw == ("chat_1_2", 0, "UID_ALICE")
    pos = research._run_pipeline_capture_key(
        ("t", None, None, False, None, None, None, None, "run_id_here",
         "UID_ALICE", "chat_3_4"), {})
    assert pos == ("chat_3_4", 0, "UID_ALICE")


def test_a_local_run_reports_no_submitter_rather_than_guessing_the_owner():
    """⛔ The machine knows the uid it is PAIRED to, and that is not proof of who
    typed the command. A local run must say "local", not name the owner."""
    local = research._run_pipeline_capture_key((), {"topic": "t"})
    assert local == (None, 0, None)


def _captured_meta(monkeypatch, *args, **kwargs):
    """Drive the REAL wrapper and hand back the meta.json it armed.

    ⛔ DELIBERATELY DOES NOT MONKEYPATCH `_RUN_PIPELINE_SIG`. The sibling test
    below replaces it with a three-parameter lambda, and a lambda with no `uid`
    makes the bind return None for the submitter while the assertion still
    passes — a green test measuring nothing. The bind has to run against the
    real signature."""
    seen = {}

    async def _fake(*a, **k):
        sink = research._active_run_sink()
        seen["meta"] = json.loads(_read(sink.meta_path)) if sink else None
        return "done"

    monkeypatch.setattr(research, "run_pipeline", _fake)
    asyncio.run(research.run_pipeline_captured(*args, **kwargs))
    return seen["meta"]


def test_a_queued_run_records_who_fired_it(monkeypatch):
    """⭐ THE CONSUMER, fed exactly what the dequeue site feeds it (research.py
    passes `uid=job.get("uid")`, `research_id=` and `_submitted_by=` by keyword).

    ⛔⛔ REWRITTEN 2026-08-24, AND THE OLD VERSION WAS THE WHOLE PROBLEM. It
    passed `uid=` alone and asserted the run was attributed — which is exactly
    what the code did, and exactly what made the stamp untrustworthy: `uid` is
    a claim the Firestore rules never check. The test agreed with the code and
    both were wrong about what the value MEANT. Attribution now needs the
    rules-pinned writer to agree with the tree."""
    meta = _captured_meta(monkeypatch, topic="t",
                          research_id="chat_1755500000000_31", uid="UID_ALICE",
                          _submitted_by="UID_ALICE")
    assert meta["submitterUid"] == "UID_ALICE"
    assert meta["submitterSource"] == "queue"


def test_a_tree_uid_alone_attributes_nobody(monkeypatch):
    """⛔ THE FIELD THE RULES DO NOT GUARD CANNOT GRANT A PERMISSION ON ITS OWN.

    This is the pre-Wave-8 shape and it is EVERY run on disk today: a start doc
    (or a build) that carried `uid` and no pinned writer. It still runs; it is
    simply attributable to nobody, so no app-side selection can name it."""
    meta = _captured_meta(monkeypatch, topic="t",
                          research_id="chat_1755500000000_35", uid="UID_ALICE")
    assert meta["submitterUid"] is None
    assert meta["submitterSource"] == "unclaimed"


def test_two_identities_that_disagree_attribute_nobody(monkeypatch):
    """⛔⛔ FAIL CLOSED. A writer naming somebody else's tree is the one shape the
    rules PERMIT and nothing legitimate produces on a start doc. If this resolved
    to either name, a sharer's two-run pick could collect the owner's machine."""
    meta = _captured_meta(monkeypatch, topic="t",
                          research_id="chat_1755500000000_36", uid="UID_ALICE",
                          _submitted_by="UID_MALLORY")
    assert meta["submitterUid"] is None
    assert meta["submitterSource"] == "disputed"


@pytest.mark.parametrize("tree,claim,expect", [
    (None, None, (None, "local")),
    ("", "", (None, "local")),
    ("U1", "U1", ("U1", "queue")),
    ("  U1  ", "U1", ("U1", "queue")),
    ("U1", None, (None, "unclaimed")),
    ("U1", "", (None, "unclaimed")),
    (None, "U1", (None, "disputed")),
    ("U1", "U2", (None, "disputed")),
])
def test_the_resolver_grants_only_on_agreement(tree, claim, expect):
    """The whole policy as a truth table — pure, so the rule can be read in one
    place instead of inferred from a capture."""
    assert research._resolve_run_submitter(tree, claim) == expect


def test_the_claim_never_reaches_the_pipeline(monkeypatch):
    """⛔ `_submitted_by` is the WRAPPER's argument. Forwarding it into
    `run_pipeline` would be a TypeError on every queued run — the signature has
    no such parameter — so the pop is load-bearing, not tidiness."""
    seen = {}

    async def _fake(*a, **k):
        seen["kwargs"] = dict(k)
        return "done"

    monkeypatch.setattr(research, "run_pipeline", _fake)
    asyncio.run(research.run_pipeline_captured(
        topic="t", uid="UID_ALICE", _submitted_by="UID_ALICE"))
    assert "_submitted_by" not in seen["kwargs"]
    assert seen["kwargs"].get("uid") == "UID_ALICE"


def test_a_local_cli_run_records_no_submitter(monkeypatch):
    """Fed exactly what the `--resume`/topic CLI sites feed it: no uid at all."""
    meta = _captured_meta(monkeypatch, topic="t", pdf_paths=None, brief_file=None,
                          verbose=False, api_key=None, email=None)
    assert meta["submitterUid"] is None
    assert meta["submitterSource"] == "local"


def test_a_local_run_does_not_inherit_a_previous_runs_submitter(monkeypatch):
    """⛔⛔ THE ONE THAT KILLS THE TEMPTING IMPLEMENTATION. `_RUN_SUBMITTER` holds
    exactly the wanted value but is bound INSIDE run_pipeline — after the sink
    has already written meta.json. Reading it from the capture would stamp the
    previous run's submitter and freeze it there on a crash."""
    monkeypatch.setitem(research._RUN_SUBMITTER, "uid", "UID_STALE")
    meta = _captured_meta(monkeypatch, topic="t")
    assert meta["submitterUid"] is None, "it read the stale process-wide global"


def test_a_crash_retry_stays_attributed(monkeypatch):
    """The auto-retry recurses through the wrapper, so attempt 2 of a run must
    not silently become unattributed."""
    meta = _captured_meta(monkeypatch, topic="t",
                          research_id="chat_1755500000000_32", uid="UID_ALICE",
                          _submitted_by="UID_ALICE", _crash_retries=1)
    assert meta["attempt"] == 1
    assert meta["submitterUid"] == "UID_ALICE"


def test_the_retry_reads_the_claim_off_the_armed_sink(monkeypatch):
    """⛔⛔ THE RETRY FIRES FROM INSIDE `run_pipeline`, WHERE THE CLAIM IS GONE —
    the wrapper popped it. `_run_submitted_by()` is the only thing that still
    holds it, and it works because the retry runs inside the outer `with`.

    Drives the REAL helper against a REAL armed sink rather than asserting the
    call site's source text: a source pin would pass against the comment."""
    seen = {}

    async def _fake(*a, **k):
        seen["mid_run"] = research._run_submitted_by()
        return "done"

    monkeypatch.setattr(research, "run_pipeline", _fake)
    asyncio.run(research.run_pipeline_captured(
        topic="t", research_id="chat_1755500000000_37", uid="UID_ALICE",
        _submitted_by="UID_ALICE"))
    assert seen["mid_run"] == "UID_ALICE"
    # …and it is not a global that survives the run.
    assert research._run_submitted_by() is None


def test_the_new_keys_do_not_leak_into_the_bundle_index(monkeypatch, tmp_path):
    """⛔⛔ THE PIN MOVED FROM THE ROW TO THE ARCHIVE, ON PURPOSE.

    It used to assert `_scan_run_folders` carried no submitter at all. Wave 8
    needs it on the row — that is where the intersection reads it — so keeping
    the old assertion would have meant a second meta read per folder for a
    property nobody wanted. What actually mattered was never the row: it was
    that a uid must not travel inside a support bundle. index.json is the thing
    that ships, so index.json is where the pin belongs.

    ⭐ Asserted against the REAL archive, not against `_INDEX_PRIVATE_KEYS`. A
    constant can be correct while the comprehension that reads it is not."""
    import zipfile

    _captured_meta(monkeypatch, topic="t",
                   research_id="chat_1755500000000_33", uid="UID_ALICE",
                   _submitted_by="UID_ALICE")
    rows = research._scan_run_folders()
    assert rows, "no run folder was scanned"
    assert rows[0]["submitterUid"] == "UID_ALICE", "the row must carry it"
    assert rows[0]["submitterSource"] == "queue"

    dest = tmp_path / "b.zip"
    research._build_log_bundle(dest, support_code="ABCD2345")
    with zipfile.ZipFile(dest) as zf:
        index = json.loads(zf.read("index.json").decode("utf-8"))
    assert index, "the archive's index was empty — this proves nothing"
    for entry in index:
        assert "submitterUid" not in entry
        assert "submitterSource" not in entry
    assert "UID_ALICE" not in zf_index_text(dest), "a uid reached the archive index"


def zf_index_text(dest) -> str:
    """index.json as raw text — a key-name check would miss a uid smuggled in
    as a VALUE under some other key."""
    import zipfile
    with zipfile.ZipFile(dest) as zf:
        return zf.read("index.json").decode("utf-8")


def test_a_status_patch_preserves_the_submitter(monkeypatch):
    """`_patch_run_log_status` is read-modify-write, so it must carry the key
    through rather than rewriting meta.json from a fresh dict."""
    _captured_meta(monkeypatch, topic="t",
                   research_id="chat_1755500000000_34", uid="UID_ALICE",
                   _submitted_by="UID_ALICE")
    folder = research._RUN_LOG_LAST_DIR
    assert folder is not None
    # Patches whatever `_RUN_LOG_LAST_DIR` points at — the shape the worker
    # watchdog actually uses, which is after the capture has already exited.
    assert research._patch_run_log_status("process-died") is True
    meta = json.loads(_read(Path(folder) / "meta.json"))
    assert meta["status"] == "process-died"
    assert meta["submitterUid"] == "UID_ALICE"


def test_the_wrapper_carries_the_crash_retry_count_as_the_attempt():
    assert research._run_pipeline_capture_key((), {"topic": "t", "_crash_retries": 2})[1] == 2


# ── Wave 8 · the claim sites ───────────────────────────────────────────
# ⛔ SOURCE PINS, and only because there is no other reach. `_job_worker` and the
# idle rescan are closures inside `run_server`; there is no seam to call. Every
# one below reads COMMENT-STRIPPED source, because the comments beside these
# lines quote the very keyword being asserted.

@pytest.mark.parametrize("data,expect", [
    ({}, None),
    ({"uid": "U1"}, None),
    ({"submittedBy": "U1"}, None),
    ({"uid": "U1", "submittedBy": "U1"}, None),
    ({"uid": "U1", "submittedBy": " U1 "}, None),
    ({"uid": "U1", "submittedBy": "U2"}, ("U1", "U2")),
    ({"uid": " U1 ", "submittedBy": "U2"}, ("U1", "U2")),
    (None, None),
])
def test_only_a_real_disagreement_is_a_conflict(data, expect):
    """⛔ ABSENT IS NOT DISAGREEING. A legacy start doc names no writer, and
    refusing it would refuse every run written by a build older than this one."""
    assert research._start_doc_identity_conflict(data) == expect


def test_a_legacy_meta_scans_as_unknown_not_as_queued(tmp_path, monkeypatch):
    """⛔⛔ FOUND BY MUTATION. Every run folder on every machine today was written
    by a build that had no submitter field at all, so `meta.get("submitterSource")`
    is None for all of them. Defaulting that to "queue" — the one value that
    grants attribution — would hand every historical run to whoever asked.

    The uid is absent too, so the grant would resolve to None either way TODAY.
    The pin is on the SOURCE because that is the field a later reader branches
    on, and a wrong default here is a live grant the moment anything reads it."""
    root = tmp_path / "runs"
    folder = root / "chat_1755500000000_90_20260819T000000"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({
        "schema": 1, "status": "complete", "researchId": "chat_1755500000000_90",
        "startedUtc": "2026-08-19T00:00:00Z", "build": "0.1.13",
    }), encoding="utf-8")
    rows = research._scan_run_folders(root=root)
    assert len(rows) == 1
    assert rows[0]["submitterUid"] is None
    assert rows[0]["submitterSource"] == "unknown", (
        "a meta with no source key must not read as a queued — i.e. attributable — run")


def test_the_refusal_decides_and_says_why(caplog):
    """The decision half, driven for real — including that a refusal is never
    silent, because a queue doc that vanishes with no line is indistinguishable
    from one that was never written."""
    caplog.clear()
    assert research._start_doc_identity_refused(
        {"uid": "U1", "submittedBy": "U2", "researchId": "chat_1_1"},
        "start-listener") is True
    assert research._start_doc_identity_refused({"uid": "U1"}, "start-listener") is False
    assert research._start_doc_identity_refused(
        {"uid": "U1", "submittedBy": "U1"}, "start-listener") is False


def test_the_refusal_names_neither_person_in_full(capsys):
    """⛔ A uid is an account identifier and this line goes to backend.log, which
    ships in every owner bundle. Both are truncated, and the label says which
    claim site refused so two identical sentences cannot be confused."""
    capsys.readouterr()
    research._start_doc_identity_refused(
        {"uid": "UID_ALICE_FULL", "submittedBy": "UID_MALLORY_FULL",
         "researchId": "chat_1755500000000_9"}, "idle-rescan")
    out = capsys.readouterr().out
    assert "[idle-rescan]" in out
    assert "UID_ALICE_FULL" not in out and "UID_MALLORY_FULL" not in out
    assert "UID_ALIC" in out and "UID_MALL" in out


def _refusal_branches(fn) -> list:
    """Every `if _start_doc_identity_refused(...)` in `fn`, as AST If nodes.

    ⛔⛔ AST, NOT A SUBSTRING COUNT, AND MUTATION IS WHY. The first version of
    this test counted calls to the guard. A mutant that left the call in place
    and neutered its branch (`if False:`) SURVIVED — the call was still there,
    the count was still two, and nothing refused anything. A call is not a
    branch, and only the tree can tell them apart."""
    import ast as _ast
    tree = _ast.parse(textwrap.dedent(inspect.getsource(fn)))
    out = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.If):
            continue
        test = node.test
        if (isinstance(test, _ast.Call)
                and isinstance(test.func, _ast.Name)
                and test.func.id == "_start_doc_identity_refused"):
            out.append(node)
    return out


@pytest.mark.parametrize("fn_name", ["start_firestore_start_listener", "run_server"])
def test_both_claim_sites_refuse_the_same_divergence(fn_name):
    """⭐⭐ ONE DEFINITION, TWO CALLERS. A refusal at the listener only is not a
    refusal — the idle rescan sweeps up exactly the documents the listener
    declined, so the run would start a minute later instead.

    Asserts the guard is the CONDITION of a branch that abandons the document:
    a bare call, or a branch that falls through, refuses nothing."""
    import ast as _ast
    branches = _refusal_branches(getattr(research, fn_name))
    assert len(branches) == 1, f"{fn_name} must gate exactly one claim on the guard"
    body = branches[0].body
    assert any(isinstance(n, _ast.Continue) for n in body), (
        f"{fn_name}'s refusal must abandon the document, not fall through")
    assert any(isinstance(n, _ast.Try) for n in body), (
        f"{fn_name}'s refusal must delete the queue doc, or it replays forever")


def test_the_pinned_writer_reaches_the_job_at_every_claim_site():
    """⛔ A CLAIM SITE THAT DROPS IT PRODUCES AN UNATTRIBUTED RUN, which looks
    exactly like a legacy start doc — silent, and wrong in the safe direction,
    which is precisely why nothing would ever report it."""
    from conftest import code_only_deep
    listener = code_only_deep(research.start_firestore_start_listener)
    server = code_only_deep(research.run_server)
    assert '"submitted_by": sb' in listener, "the start listener's enqueue"
    assert '"submitted_by": str(d.get("submittedBy") or "").strip()' in server, \
        "the idle rescan's enqueue"
    assert '_submitted_by=job.get("submitted_by")' in server, "the dequeue site"


def test_the_supervised_auto_resume_carries_it_too():
    """The disk-resume path has no queue document left; the research doc it is
    rehydrating from is the only writer still on record."""
    from conftest import code_only_deep
    src = code_only_deep(research._rehydrate_ongoing_for_tree)
    assert '"submitted_by": str(' in src and 'data.get("submittedBy")' in src


def test_the_crash_retry_forwards_the_claim():
    from conftest import code_only_deep
    src = code_only_deep(research.run_pipeline)
    assert "_submitted_by=_run_submitted_by()" in src


def test_the_wrappers_signature_cannot_drift_from_the_body():
    """The bind is against `run_pipeline` itself, so a new parameter needs no
    change here — this pins that it really is the same object."""
    assert research._RUN_PIPELINE_SIG == inspect.signature(research.run_pipeline)


def test_the_wrapper_arms_a_folder_around_a_real_await(monkeypatch):
    seen = {}

    async def _fake(*a, **k):
        seen["armed"] = research._active_run_sink()
        return "done"

    monkeypatch.setattr(research, "run_pipeline", _fake)
    monkeypatch.setattr(research, "_RUN_PIPELINE_SIG",
                        inspect.signature(lambda topic=None, research_id=None,
                                          _crash_retries=0: None))
    out = asyncio.run(research.run_pipeline_captured(topic="t",
                                                    research_id="chat_9_9"))
    assert out == "done"
    assert seen["armed"] is not None
    assert seen["armed"].research_id == "chat_9_9"
    assert research._active_run_sink() is None, "the sink outlived the run"


# ══ 10. raw-log rotation, at the site the default install uses ═════════
def test_rotation_leaves_a_small_file_alone(tmp_path):
    p = tmp_path / "backend.log"
    p.write_text("small", encoding="utf-8")
    assert research._rotate_if_oversize(p, max_bytes=1000) == 0
    assert p.exists() and not (tmp_path / "backend.log.1").exists()


def test_rotation_rolls_an_oversized_file_to_dot_one(tmp_path):
    p = tmp_path / "backend.log"
    p.write_text("x" * 2000, encoding="utf-8")
    rolled = research._rotate_if_oversize(p, max_bytes=1000)
    assert rolled == 2000
    assert not p.exists()
    assert (tmp_path / "backend.log.1").read_text(encoding="utf-8") == "x" * 2000


def test_rotation_replaces_an_older_dot_one(tmp_path):
    p = tmp_path / "backend.log"
    (tmp_path / "backend.log.1").write_text("ancient", encoding="utf-8")
    p.write_text("y" * 2000, encoding="utf-8")
    research._rotate_if_oversize(p, max_bytes=1000)
    assert (tmp_path / "backend.log.1").read_text(encoding="utf-8") == "y" * 2000


def test_a_rename_windows_refuses_is_audited_not_swallowed(tmp_path, monkeypatch):
    p = tmp_path / "backend.log"
    p.write_text("z" * 2000, encoding="utf-8")

    def _boom(*_a, **_k):
        raise OSError(32, "used by another process")

    monkeypatch.setattr(research.os, "replace", _boom)
    said = []
    assert research._rotate_if_oversize(p, max_bytes=1000, audit=said.append) == 0
    assert said and "rotation skipped" in said[0], said
    assert p.exists(), "the log was lost on a failed rename"


def test_rotation_runs_at_all_three_places_a_backend_log_is_opened():
    """⭐ THE SITE THAT MATTERS IS THE THIRD ONE. `load_worker_count()` defaults
    to 1, so the default install never enters the multi-worker branch —
    rotation anchored only there is a guard that cannot fire for most users."""
    src = inspect.getsource(research.run_daemon_loop)
    supervisor = src.index("_rotate_if_oversize(_serve_log)")
    spawn = src.index("_rotate_if_oversize(log_out_path, audit=_sup_audit)")
    single = src.index("_rotate_if_oversize(_serve_log, audit=_sup_audit)")
    assert supervisor < spawn < single, (supervisor, spawn, single)
    assert src.index("_rotate_if_oversize(_serve_log, audit=_sup_audit)") < \
        src.index('with open(_serve_log, "ab") as _out'), \
        "the single-worker branch opens the log before rotating it"
    assert src.index("_rotate_if_oversize(log_out_path") < \
        src.index('_out_fh = open(log_out_path, "ab")')


def test_the_log_root_is_the_same_directory_the_supervisor_uses():
    """Two log directories is the drift this indirection exists to prevent."""
    assert research._logs_root() == research._STATE_DIR / "logs"
    assert '_log_dir = _STATE_DIR / "logs"' in inspect.getsource(research.run_daemon_loop)


# ══ 11. local retention ════════════════════════════════════════════════
def _fake_run(root, name, age_days=0):
    d = root / name
    d.mkdir(parents=True)
    (d / "run.log").write_text("x", encoding="utf-8")
    when = time.time() - age_days * 86400
    os.utime(d, (when, when))
    return d


def test_pruning_keeps_the_newest_runs_and_drops_the_rest():
    root = research._runs_log_root()
    for i in range(10):
        _fake_run(root, f"chat_1_{i}_20260818T00000{i}", age_days=10 - i)
    removed = research._prune_local_logs(runs_keep=4, sessions_keep=4)
    assert len(removed) == 6, removed
    assert len(list(root.iterdir())) == 4


def test_pruning_drops_anything_past_the_age_bound_even_inside_the_count():
    root = research._runs_log_root()
    _fake_run(root, "chat_1_new_20260818T000001", age_days=1)
    old = _fake_run(root, "chat_1_old_20260718T000001", age_days=45)
    research._prune_local_logs(runs_keep=100, sessions_keep=100, max_age_days=30)
    assert not old.exists()
    assert len(list(root.iterdir())) == 1


def test_pruning_never_deletes_a_run_that_is_still_being_written():
    """⛔ The live folder is the one a support bundle is about to need — and it
    is NOT protected by being newest. ⭐ A directory's mtime stops moving the
    instant run.log exists, because appends never touch the directory, so a run
    six hours into real work looks ancient to every bound here. Simulated
    exactly, because the first version of this test passed without the guard."""
    with research._RunLogCapture(research_id="chat_1755500000000_f") as sink:
        old = time.time() - 90 * 86400
        os.utime(sink.dir, (old, old))
        research._prune_local_logs(runs_keep=0, sessions_keep=0, max_age_days=1)
        assert sink.dir.exists(), "pruning deleted the armed run's own folder"
        research.log("still writing", "INFO")
    assert "still writing" in _read(sink.writer.primary)


def test_a_live_run_whose_meta_never_landed_is_still_spared():
    """⛔ Found by mutation, second pass. `_folder_is_live` reads meta.json — and
    that write is best-effort and swallows its own failures. So on the one disk
    where the meta did NOT land, the cross-process guard says "not live" and the
    age bound reaches the folder we are writing into right now. The in-process
    sink list is the only thing that answers without touching the disk."""
    with research._RunLogCapture(research_id="chat_1755500000000_i") as sink:
        old = time.time() - 90 * 86400
        os.utime(sink.dir, (old, old))
        sink.meta_path.unlink()
        assert research._folder_is_live(sink.dir) is False, (
            "this test measures nothing unless the meta really is unreadable")
        research._prune_local_logs(runs_keep=0, sessions_keep=0, max_age_days=1)
        assert sink.dir.exists(), (
            "the folder being written to right now was deleted because its meta "
            "was missing")
        research.log("still writing after the meta was lost", "INFO")
    assert "still writing after the meta was lost" in _read(sink.writer.primary)


def test_pruning_spares_another_workers_live_run_too():
    """⛔⛔ FOUND BY MUTATION. The in-process sink list cannot see a run armed by
    a sibling worker, and on a fleet host worker 2 prunes the same directory."""
    root = research._runs_log_root()
    theirs = _fake_run(root, "chat_1_theirs_20260818T000001", age_days=90)
    _atomic = research._atomic_write_json
    _atomic(theirs / "meta.json", {"status": "running", "pid": os.getpid(),
                                   "startedUtc": research._utc_iso()})
    dead = _fake_run(root, "chat_1_dead_20260818T000002", age_days=90)
    _atomic(dead / "meta.json", {"status": "running", "pid": 999_999_999,
                                 "startedUtc": research._utc_iso()})
    research._prune_local_logs(runs_keep=0, sessions_keep=0, max_age_days=1)
    assert theirs.exists(), "another worker's live run folder was deleted"
    assert not dead.exists(), (
        "a folder whose process is gone is protected forever — the status is "
        "trusted instead of derived")


def test_pruning_takes_a_sessions_overflow_segment_with_its_parent():
    root = research._sessions_log_root()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("pair_20260101T000000.log", "pair_20260101T000000.log.overflow1"):
        p = root / name
        p.write_text("x", encoding="utf-8")
        os.utime(p, (time.time() - 90 * 86400,) * 2)
    research._prune_local_logs(max_age_days=30)
    assert list(root.iterdir()) == []


def test_a_session_and_its_overflow_are_kept_or_dropped_as_one():
    """⛔ Found by mutation: the age bound alone cannot see the grouping, because
    an overflow segment is always written after its parent. It is the COUNT
    bound that splits them — 40 sessions with two segments each is 120 files,
    and 'newest 40 files' keeps thirteen sessions and orphans the rest."""
    root = research._sessions_log_root()
    root.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        when = time.time() - (3 - i) * 3600
        for suffix in ("", ".overflow1"):
            p = root / f"pair_2026010{i}T000000.log{suffix}"
            p.write_text("x", encoding="utf-8")
            os.utime(p, (when, when))
    research._prune_local_logs(runs_keep=100, sessions_keep=2, max_age_days=3650)
    left = sorted(p.name for p in root.iterdir())
    assert len(left) == 4, f"grouping was ignored — survivors are {left}"
    for name in left:
        if name.endswith(".overflow1"):
            assert name[: -len(".overflow1")] in left, f"{name} was orphaned"
        else:
            assert name + ".overflow1" in left, f"{name} lost its tail"


def test_arming_a_run_prunes_first(monkeypatch):
    calls = []
    monkeypatch.setattr(research, "_prune_local_logs",
                        lambda *a, **k: calls.append(1) or [])
    with research._RunLogCapture(research_id="chat_1755500000000_g"):
        pass
    assert calls, "the capture is a second unbounded copy without this"


# ══ 12. the crash that reached no file ═════════════════════════════════
def test_a_traceback_out_of_any_command_is_routed_through_log(capsys):
    """⛔ MEASURED: this file had NO excepthook. A crash out of `--pair` reached
    a closing terminal; a crash inside `--serve` reached backend.err.log, the
    half of the logs nobody thinks to ask for."""
    try:
        raise RuntimeError("the pairing crash")
    except RuntimeError as exc:
        research._log_excepthook(type(exc), exc, exc.__traceback__)
    out = capsys.readouterr().out
    assert "RuntimeError: the pairing crash" in out
    assert "Traceback" in out
    assert re.search(r"\[\d\d:\d\d:\d\d\] \[ERROR\] Traceback", out), (
        "the traceback lines are unstamped, which is how a multi-line record "
        "becomes unparseable orphan lines")


def test_the_traceback_is_not_printed_twice(capsys):
    """⛔ Found by mutation. The first version left `_PREV_EXCEPTHOOK` at None,
    so the chain guard was never reached and the test measured nothing. A real
    install captures the DEFAULT hook, which is exactly the one that must not
    be chained."""
    import sys as _sys
    research._PREV_EXCEPTHOOK = _sys.__excepthook__
    try:
        raise RuntimeError("once only")
    except RuntimeError as exc:
        research._log_excepthook(type(exc), exc, exc.__traceback__)
    finally:
        research._PREV_EXCEPTHOOK = None
    combined = capsys.readouterr()
    assert (combined.out + combined.err).count("once only") == 2, (
        "expected the message line and the traceback's own line, not a second "
        "full copy from the default hook")


def test_a_crash_inside_a_run_lands_in_that_runs_folder():
    with research._RunLogCapture(research_id="chat_1755500000000_h") as sink:
        try:
            raise RuntimeError("mid-run explosion")
        except RuntimeError as exc:
            research._log_excepthook(type(exc), exc, exc.__traceback__)
    assert "mid-run explosion" in _read(sink.writer.primary)


def test_ctrl_c_keeps_its_calm_exit(capsys):
    seen = []
    research._PREV_EXCEPTHOOK = lambda *a: seen.append(a)
    try:
        research._log_excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        research._PREV_EXCEPTHOOK = None
    assert seen, "KeyboardInterrupt no longer delegates"
    out = capsys.readouterr().out
    # ⛔ Found by mutation: `format_exception(KeyboardInterrupt, …, None)` prints
    # no "Traceback" line at all, so asserting on that word measured nothing.
    # The calm path is that `log()` never fires.
    assert "Unhandled exception" not in out, (
        "Ctrl+C is being reported as a crash again")
    assert "[ERROR]" not in out
    assert "KeyboardInterrupt" not in out


def test_installing_the_crash_hook_twice_attaches_once(monkeypatch):
    monkeypatch.setattr(research, "_CRASH_HOOK_INSTALLED", False)
    monkeypatch.setattr(research, "_PREV_EXCEPTHOOK", None)
    import sys as _sys
    original = _sys.excepthook
    try:
        assert research._install_crash_log_hook() is True
        assert research._install_crash_log_hook() is False
        assert _sys.excepthook is research._log_excepthook
    finally:
        _sys.excepthook = original


def test_main_installs_the_crash_hook_for_every_command():
    src = inspect.getsource(research.main)
    assert "_install_crash_log_hook()" in src
    assert src.index("_install_crash_log_hook()") < src.index("args = parser.parse_args()")


# ══ 13. which commands get a session file ══════════════════════════════
class _Args:
    def __init__(self, **kw):
        self.pair = self.login = self.doctor = self.serve = False
        # ⛔ `worker_id` belongs here now: it is what separates a supervised
        # worker from a person running serve in a terminal. A namespace missing
        # it would silently read as "not supervised", which is right for a real
        # argparse result (default None) but should be explicit in a fixture.
        self.worker_id = None
        self.daemon_loop = False
        for k, v in kw.items():
            setattr(self, k, v)


def test_the_three_interactive_commands_get_a_session_file():
    assert research._session_command_name(_Args(pair=True)) == "pair"
    assert research._session_command_name(_Args(login=True)) == "login"
    assert research._session_command_name(_Args(doctor=True)) == "doctor"


def test_a_SUPERVISED_serve_does_not_get_one_but_a_MANUAL_one_does():
    """⛔⛔ THIS ASSERTION WAS THE OTHER WAY ROUND, and its name carried the
    premise: "because its stdout is already a file". That is true of a worker the
    supervisor spawned — `_spawn_worker` opens backend-N.log and passes it as
    stdout — and false of `python research.py --serve` in a terminal, which has no
    supervisor and therefore no redirection at all.

    Measured 2026-08-19: a manual foreground serve wrote NO serve-level log file
    anywhere, so its startup, its device-command listener and its entire shutdown
    tail lived only in scrollback and no support bundle could carry them. The test
    was enshrining that, so it is inverted rather than relaxed — the supervised
    half is the half that must still be None."""
    assert research._session_command_name(_Args(serve=True, worker_id=1)) is None
    assert research._session_command_name(_Args(serve=True, worker_id=4)) is None
    assert research._session_command_name(_Args(serve=True)) == "serve"
    assert research._session_command_name(_Args(daemon_loop=True)) is None
    assert research._session_command_name(_Args()) is None


def test_main_installs_the_tee_before_it_dispatches_a_command():
    src = inspect.getsource(research.main)
    install = src.index("_install_session_tee(_session_cmd)")
    for dispatch in ("if args.doctor:", "if args.pair:", "if args.login:"):
        assert install < src.index(dispatch), (
            f"{dispatch} runs before the session tee is installed, so its output "
            "reaches no file")


def test_the_session_file_is_written_with_a_dated_header(monkeypatch):
    import sys as _sys
    out, err = _sys.stdout, _sys.stderr
    try:
        writer = research._install_session_tee("doctor")
        assert writer is not None
        print("doctor said something")
        research._close_session_tees()
    finally:
        _sys.stdout, _sys.stderr = out, err
    text = _read(writer.primary)
    assert "=== super research session: doctor ===" in text
    assert "doctor said something" in text
    assert re.search(r"startedUtc=\d{4}-\d\d-\d\dT", text), (
        "no date in the header — the one thing `log()` never stamps")


def test_what_a_command_writes_to_stderr_reaches_the_session_file(monkeypatch):
    """⛔ Found by mutation. stderr is where failures go, and it is the stream
    the stdlib bridge's lastResort was already dumping 22,758 lines into."""
    import sys as _sys
    out, err = _sys.stdout, _sys.stderr
    try:
        writer = research._install_session_tee("pair")
        print("a failure on stderr", file=_sys.stderr)
        research._close_session_tees()
    finally:
        _sys.stdout, _sys.stderr = out, err
    assert "a failure on stderr" in _read(writer.primary)
