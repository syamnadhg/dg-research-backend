"""No mutation harness does anything with side effects when it is merely IMPORTED.

⛔⛔ WHY (2026-09-26). The static anchor sweep and the apply sweep
(tests/test_mutation_harness_anchors.py) import every file in .mutants/. Two
harnesses registered `atexit.register(restore)` and SIGINT/SIGTERM handlers at
module level, so the sweep's own process was armed to rewrite research.py from a
copy captured at import: its exit silently reverted any edit made while it ran,
and a wrapper timeout's SIGTERM rewrote the file mid-run while the sweep was
reading it — 3,169 anchors reported stale on a clean tree (Linux, WSL, a 900 s
`timeout`). Whatever a harness does to files belongs under `if __name__ ==
"__main__":` or inside a function it calls from there.
"""
import ast
from pathlib import Path

MUTANTS = Path(__file__).resolve().parents[1] / ".mutants"
_ARMING = {("atexit", "register"), ("signal", "signal")}


def _module_level_calls(tree: ast.Module):
    """Calls that run at import: module-level statements, not function bodies
    and not the `if __name__ == "__main__":` block."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                yield sub


def test_no_harness_arms_a_restore_or_a_signal_handler_at_import():
    offenders = []
    harnesses = sorted(MUTANTS.glob("*.py"))
    assert len(harnesses) > 50, "the sweep must actually see the harnesses"
    for path in harnesses:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _module_level_calls(tree):
            f = call.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    and (f.value.id, f.attr) in _ARMING):
                offenders.append(f"{path.name}:{call.lineno} {f.value.id}.{f.attr}")
    assert offenders == [], offenders


def test_the_detector_sees_a_module_level_registration(tmp_path):
    """⛔ Positive control: an absent-check that cannot fire proves nothing."""
    src = "import atexit\ndef restore():\n    pass\natexit.register(restore)\n"
    calls = list(_module_level_calls(ast.parse(src)))
    assert any(isinstance(c.func, ast.Attribute) and c.func.attr == "register" for c in calls)
    inside = "import atexit\ndef main():\n    atexit.register(print)\n"
    assert not list(_module_level_calls(ast.parse(inside)))
