"""Run a function that lives inside `run_server` — the REAL one, not a copy.

⛔⛔ WHY THIS EXISTS (wave 10.10). The worker loop that dequeues every job and
the idle rescan that claims every orphaned start document are closures of
`run_server`, which builds a whole web server and cannot be called from a
test. So the decisions inside them were pinned by reading their source — a
window of N characters after a marker, a count of a phrase — and a source pin
cannot tell a branch that runs from one that is spelled correctly. One of those
pins counted "proceeding, as before" twice in the dequeue's fallback read; the
second occurrence was the branch that ran a job whose research had been
deleted, and the pin held it in place.

⭐ So this lifts the nested function's own definition out of `research.py`'s
parse tree and compiles it against the module's OWN globals. What the closure
took from `run_server` (the job queue, the flip, the recompute) is not a global,
so a test supplies those names on the module with `monkeypatch.setattr(...,
raising=False)`, and everything else the body calls is the real module
function unless the test replaces it. The file is read at call time, so a
mutation harness that rewrites `research.py` is measured, not the import.
"""
import ast
import asyncio
import collections
import types
from pathlib import Path

import pytest

import research

#: Read before any test can point `research.__file__` at a temporary directory.
_SOURCE = Path(research.__file__).resolve()

#: (source text, name) → the compiled body. Parsing the module takes seconds,
#: and the text is part of the key, so a rewritten file is never served stale.
_COMPILED: dict = {}


def lift(name: str):
    """`run_server`'s nested function `name`, callable, with research's globals."""
    text = _SOURCE.read_text(encoding="utf-8")
    key = (hash(text), len(text), name)
    if key not in _COMPILED:
        tree = ast.parse(text)
        server = next(n for n in tree.body
                      if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_server")
        found = [n for n in ast.walk(server)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        assert len(found) == 1, f"run_server defines {name} {len(found)} time(s)"
        code = compile(ast.Module(body=found, type_ignores=[]), str(_SOURCE), "exec")
        _COMPILED[key] = next(c for c in code.co_consts
                              if isinstance(c, types.CodeType) and c.co_name == name)
    return types.FunctionType(_COMPILED[key], research.__dict__, name)


# ══ the worker loop, over one job ═════════════════════════════════════════

class _Done(Exception):
    """Raised by the fake queue's second `get()`: the worker loop is endless."""


class _WorkerQueue:
    def __init__(self, job):
        self._jobs = [job]
        self._queue = collections.deque()

    async def get(self):
        if not self._jobs:
            raise _Done()
        return self._jobs.pop(0)

    def task_done(self):
        pass

    def qsize(self):
        return 0


class _Controls:
    _awaiting_user = False

    def reset(self):
        pass

    def is_stop(self):
        return False

    def is_pause(self):
        return False

    def request_stop(self):
        pass


def run_worker_once(monkeypatch, tmp_path, job, *, flip, db, update_research):
    """Run `_job_worker` — the real dequeue — over `job`, with the flip answering
    `flip` and `db` answering any plain read. Returns the pipelines it started.

    ⭐ The pipeline is replaced by a recorder that hands back an already-finished
    future, so the worker's watchdog loop sees it done at once; everything that
    decides whether it is started at all is the worker's own code."""
    started = []

    def _pipeline(**kw):
        started.append(kw)
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        return done

    async def _nothing():
        return None

    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "_job_queue", _WorkerQueue(job), raising=False)
    monkeypatch.setattr(research, "_flip_queued_to_ongoing", lambda u, r: flip, raising=False)
    monkeypatch.setattr(research, "_persist_pending_queue", lambda current_job=None: None,
                        raising=False)
    monkeypatch.setattr(research, "_recompute_queue_positions", lambda: None, raising=False)
    monkeypatch.setattr(research, "_rescan_queue_for_unclaimed", _nothing, raising=False)
    monkeypatch.setattr(research, "WORKER_OUTER_TIMEOUT_SEC", 3600, raising=False)
    monkeypatch.setattr(research, "run_pipeline_captured", _pipeline)
    monkeypatch.setattr(research, "_controls", _Controls())
    monkeypatch.setattr(research, "_write_worker_lock", lambda *a, **k: None)
    monkeypatch.setattr(research, "_delete_worker_lock", lambda *a, **k: None)
    monkeypatch.setattr(research, "_clear_current_run_id_best_effort", lambda *a, **k: None)
    monkeypatch.setattr(research, "_recompute_deferred_queue_positions", lambda: None)
    monkeypatch.setattr(research, "_pending_enq_dec", lambda: None)
    monkeypatch.setattr(research, "load_device_id", lambda: None)
    monkeypatch.setattr(research, "_update_research_doc", update_research)
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", None)
    with pytest.raises(_Done):
        asyncio.run(lift("_job_worker")())
    return started
