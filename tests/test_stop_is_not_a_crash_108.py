"""Pressing Stop is not a crash, and a crash we gave up on stops relaunching.

⛔⛔ TWO DEFECTS IN ONE `except` BLOCK, AND THE FIRST ONE IS MINE, FROM 09-20.
The Stop handler closes the research browser deliberately — that is how it ends
a run mid-phase — and the five unwind sites added that day tag every browser
death with the literal "(browser crash)" so the classifier can re-derive the
kind from the exception alone. Both changes are right. Together they mean a
person who presses Stop during phase 2 or 3 raises a crash error, lands in
`run_pipeline`'s catch-all, and is shown **"The run kept hitting errors"** about
a run they ended themselves. The auto-retry was already refused for the right
reason, so only the sentence was wrong — and this exit wrote no terminal status
at all, so the document sat `ongoing` afterwards.

⛔⛔ AND THE CRASH BUDGET DIED WITH ITS CALL. `_crash_retries` is a PARAMETER of
`run_pipeline`. A supervised device's boot rehydration finds artifacts on disk
and no `.stop`, enqueues the run again, and it starts over at attempt zero:
three more Chrome launches on a run that just exhausted its budget, silently,
with the person's terminal card still on screen.

⭐ THE MARKER IS NOT `.stop`, AND THAT IS THE WHOLE DESIGN. `.stop` means "ended
for good" and the resume path checks it too — it would refuse the very Retry the
card is offering and, since this wave's drop write-back, would tell the person
their run "was stopped for good", which is the wrong story for a crash. The new
marker refuses only the AUTOMATIC paths; a human pressing Retry clears it and
gets a fresh budget, because they chose to spend it. Clearing it on the one
human-driven path is also why `_safe_enqueue`'s gate needs no list of callers
and cannot drift out of step with one.
"""
import ast
import json
import time
from pathlib import Path

import pytest

import research


# ══ helpers ════════════════════════════════════════════════════════════
class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _Node:
    def __init__(self, data):
        self._data = data

    def collection(self, _n):
        return self

    def document(self, _i):
        return self

    def get(self):
        return _Snap(self._data)


def _fn(name):
    src = Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    d = tmp_path / "queues" / "Topic_20260101_000000"
    d.mkdir(parents=True)
    return d


def _job(run_dir):
    return {"research_id": "chat_1", "uid": "uid-alice",
            "run_id": run_dir.name, "resume_dir": str(run_dir)}


class _Q:
    def __init__(self):
        self.items = []

    def put_nowait(self, job):
        self.items.append(job)


# ══ 1. the marker stops the AUTOMATIC paths, and only those ════════════
def test_a_run_that_used_up_its_attempts_is_not_enqueued_again(run_dir, monkeypatch):
    """⛔⛔ THE DEFECT. Without the marker a supervised boot re-enqueues a run
    whose terminal card is on screen, and `run_pipeline` starts over at attempt
    zero — the budget lives in a function parameter and died with the call."""
    monkeypatch.setattr(research, "_firebase_db", _Node({"status": "ongoing"}))
    q = _Q()
    # ⭐ THE A/B IS THE POINT. Without the marker this run enqueues — so the
    # refusal below is the marker's doing and not some other gate's.
    assert research._safe_enqueue(q, _job(run_dir), "test-auto") is True
    assert len(q.items) == 1

    (run_dir / research.NO_AUTO_RETRY_MARKER).write_text("{}", encoding="utf-8")
    assert research._safe_enqueue(q, _job(run_dir), "test-auto") is False
    assert len(q.items) == 1, "a run that gave up was enqueued again"


def test_the_marker_is_not_the_stop_sentinel(run_dir):
    """⛔⛔ THE DESIGN, PINNED. Reusing `.stop` would have been one line — and it
    would refuse the person's own Retry and tell them the run "was stopped for
    good", which is the wrong story for a crash."""
    assert research.NO_AUTO_RETRY_MARKER != ".stop"
    (run_dir / research.NO_AUTO_RETRY_MARKER).write_text("{}", encoding="utf-8")
    assert not (run_dir / ".stop").exists(), (
        "giving up on automatic retries must not mark the run terminally stopped")


def test_a_person_pressing_retry_gets_a_clean_budget(run_dir, monkeypatch):
    """⭐ AND THE CLEAR IS WHAT MAKES THE GATE SAFE. Retry is a decision to
    spend a fresh budget; a machine rebooting is not."""
    (run_dir / research.NO_AUTO_RETRY_MARKER).write_text("{}", encoding="utf-8")
    research._clear_no_auto_retry(run_dir)
    assert not research._no_auto_retry_marked(run_dir)
    monkeypatch.setattr(research, "_firebase_db", _Node({"status": "ongoing"}))
    q = _Q()
    assert research._safe_enqueue(q, _job(run_dir), "test-human") is True


def test_clearing_a_marker_that_is_not_there_is_not_an_error(run_dir):
    """⭐ The resume path clears unconditionally — it cannot know whether the
    run ever gave up, and a raise inside a Firestore listener callback costs
    the whole snapshot."""
    research._clear_no_auto_retry(run_dir)
    research._clear_no_auto_retry(run_dir / "nope")
    assert research._no_auto_retry_marked(run_dir) is False
    assert research._no_auto_retry_marked(run_dir / "nope") is False


def test_the_resume_listener_clears_it_before_it_enqueues():
    """⛔ ORDER, over the parse tree. Clearing AFTER the enqueue would be a
    no-op against the gate the enqueue just failed."""
    fn = _fn("start_firestore_start_listener")
    clears = [c.lineno for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
              and c.func.id == "_clear_no_auto_retry"]
    enqueues = [c.lineno for c in ast.walk(fn)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "_safe_enqueue"]
    assert clears, "the human Retry path never clears the marker"
    assert enqueues, "the resume path no longer enqueues at all"
    assert min(clears) < max(enqueues), (
        "the marker is cleared after the enqueue that it blocks")


# ══ 2. a Stop is told apart from a crash ═══════════════════════════════
def _except_handler():
    """`run_pipeline`'s catch-all — the block both defects live in."""
    fn = _fn("run_pipeline")
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            if (isinstance(h.type, ast.Name) and h.type.id == "Exception"
                    and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id == "_plan_pipeline_auto_retry"
                            for n in ast.walk(h))):
                return h
    raise AssertionError("run_pipeline's catch-all handler not found")


def test_a_stop_is_checked_BEFORE_anything_calls_it_a_crash():
    """⛔⛔ THE ORDER IS THE FIX. The crash branches are reached by falling
    past this one; putting the stop test after them would leave the card
    exactly as wrong as it was."""
    h = _except_handler()
    stop_lines = [n.lineno for n in ast.walk(h)
                  if isinstance(n, ast.Name) and n.id == "_stop_requested"]
    retry_lines = [n.lineno for n in ast.walk(h)
                   if isinstance(n, ast.Name) and n.id == "_will_silent_retry"]
    assert stop_lines, "the catch-all does not ask whether a stop was requested"
    assert retry_lines
    assert min(stop_lines) < max(retry_lines), (
        "the stop test does not precede the crash branches")


def test_a_stopped_run_is_not_handed_the_crash_card():
    """⛔ The card's own words. A run the person ended must not be described as
    one that "kept hitting errors" — and the two must be in different branches,
    not merely both present in the block."""
    h = _except_handler()
    branch = None
    for node in ast.walk(h):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "_stop_requested"):
            branch = node
            break
    assert branch is not None, "no branch is guarded on a stop having been requested"
    body_src = ast.dump(ast.Module(body=branch.body, type_ignores=[]))
    assert "kept hitting errors" not in body_src, (
        "the stop branch shows the crash card")
    # and the crash card is in what it falls past
    else_src = ast.dump(ast.Module(body=branch.orelse, type_ignores=[]))
    assert "kept hitting errors" in else_src, (
        "the crash card is no longer reached by falling past the stop test")


def test_a_stopped_run_gets_a_terminal_status_and_an_event():
    """⛔⛔ THE HALF NOBODY FILED. This exit wrote NO run-level status, so the
    document sat `ongoing` after a Stop that arrived mid-phase. The branch now
    takes the same exit every phase-boundary stop in this function takes."""
    h = _except_handler()
    branch = next(n for n in ast.walk(h)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                  and n.test.id == "_stop_requested")
    src = ast.dump(ast.Module(body=branch.body, type_ignores=[]))
    assert "pipeline_stopped" in src, "the stop branch emits no terminal event"
    assert "_update_firestore_research" in src, "the stop branch writes no status"
    assert "'stopped'" in src or '"stopped"' in src


def test_the_stop_exit_does_not_overwrite_a_terminal_status():
    """⛔⛔ CROSS-VERIFY CAUGHT THIS IN THE FIX ITSELF. A watchdog kill writes
    `stopped_by_watchdog` AND queues a stop command, whose handler closes the
    browser — so that death lands in this very branch, sees `.stop`, and a
    blind write of plain "stopped" erased the attribution seconds later. Plain
    `stopped` is not a recovery status, so the chat's listener then CLEARED the
    card: the person lost the only sentence explaining a ceiling stop and both
    of its buttons. Before this wave the block wrote no status at all, which is
    exactly why the defect could not exist until I added the write."""
    h = _except_handler()
    branch = next(n for n in ast.walk(h)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                  and n.test.id == "_stop_requested")
    guarded = [
        n for n in ast.walk(branch)
        if isinstance(n, ast.If)
        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "_research_is_terminal" for c in ast.walk(n.test))
    ]
    assert guarded, (
        "the stop exit writes a status without asking whether the run already "
        "carries a terminal one — a watchdog kill lands here and loses its "
        "attribution and its card")
    src = ast.dump(ast.Module(body=guarded[0].body, type_ignores=[]))
    assert "_update_research_doc" in src or "_update_firestore_research" in src, (
        "the guard is present but the write is outside it")


def test_the_terminal_set_the_guard_reads_matches_the_pre_claim_gate():
    """⭐ ONE LIST, AND IT ALREADY EXISTED IN THIS FILE AS A LITERAL. The
    pre-claim gate a few hundred lines below names the same five; if the two
    drift, a run terminal to one is resumable to the other."""
    assert set(research.TERMINAL_RESEARCH_STATUSES) == {
        "stopped", "completed", "archived",
        "terminated_by_user_discard", "stopped_by_watchdog",
    }


def test_the_terminal_crash_card_records_that_it_gave_up():
    """⛔ Without this write the marker is a constant nothing ever sets, and
    every test above passes against a product that still relaunches."""
    h = _except_handler()
    marks = [n for n in ast.walk(h)
             if isinstance(n, ast.Name) and n.id == "NO_AUTO_RETRY_MARKER"]
    assert marks, (
        "the terminal crash card writes no marker — a supervised boot will "
        "start this run again at attempt zero")


def test_the_marker_says_when_and_why(run_dir, monkeypatch):
    """⭐ Diagnostics, and the lesson from the dead-worker marker one commit
    ago: a marker that records one cause for several outcomes is how a gap
    stays invisible."""
    payload = json.dumps({"at": int(time.time() * 1000), "phase": 2,
                          "kind": "browser_crash"})
    (run_dir / research.NO_AUTO_RETRY_MARKER).write_text(payload, encoding="utf-8")
    rec = json.loads((run_dir / research.NO_AUTO_RETRY_MARKER).read_text(encoding="utf-8"))
    assert rec["kind"] == "browser_crash" and rec["phase"] == 2
    assert research._no_auto_retry_marked(run_dir)
