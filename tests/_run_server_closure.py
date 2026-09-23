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
import types
from pathlib import Path

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
