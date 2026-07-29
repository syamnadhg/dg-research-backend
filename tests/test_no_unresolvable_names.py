"""Two name-error traps ruff cannot cover on its own — DGOPS-9508.

Ruff's F821 now genuinely covers the shipped modules, so this file deliberately
does NOT reimplement it. It guards only the two gaps:

1. **A star import blinds F821.** `research.py` used to do `from prompts import *`;
   ruff cannot resolve that, so every unresolved global in the file degraded from
   `F821 undefined-name` to the far weaker `F405 may-be-undefined` — 86 findings
   in which a real typo was indistinguishable from a prompt constant. A
   guaranteed `NameError` (`_job_queue` in `_rehydrate_ongoing_for_tree`) sat in
   that pile. The import is explicit now; this keeps a star import from coming
   back and silently switching the coverage off again.

2. **A nested def used above its own `def`** is an `UnboundLocalError`, and no
   ruff rule catches it — the name IS bound, just not yet. This found
   `update_delivery`, called in `run_pipeline`'s `start_phase == 5` branch ~365
   lines above its definition, in a branch that returns before reaching it.

Stdlib-only (`ast`), so it runs even where ruff is absent.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The modules that ship in the wheel (root pyproject.toml `py-modules`).
SHIPPED_MODULES = ("research.py", "models.py", "prompts.py", "vision.py",
                   "narrate.py", "selfheal.py")


def _tree(rel: str) -> ast.Module:
    path = ROOT / rel
    assert path.exists(), f"{rel} is missing from the repo root"
    return ast.parse(path.read_text(encoding="utf-8"))


def _scope_owner(root: ast.AST, target: ast.AST) -> ast.AST:
    """Innermost function/class/lambda scope under `root` containing `target`.

    References inside a DEEPER function run at call time, so definition order does
    not constrain them — only references in the parent's own body are ordered.
    """
    stack = [(root, root)]
    while stack:
        node, scope = stack.pop()
        for child in ast.iter_child_nodes(node):
            if child is target:
                return scope
            deeper = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                        ast.Lambda, ast.ClassDef))
            stack.append((child, child if deeper else scope))
    return root


def called_before_def(tree: ast.Module, label: str) -> list[str]:
    """Nested functions referenced above their own `def`, in the same scope."""
    bad: list[str] = []
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nested: dict[str, int] = {}
        for child in ast.walk(parent):
            if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child is not parent
                    and _scope_owner(parent, child) is parent):
                nested.setdefault(child.name, child.lineno)
        for node in ast.walk(parent):
            if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                    and node.id in nested and node.lineno < nested[node.id]
                    and _scope_owner(parent, node) is parent):
                bad.append(f"{label}::{parent.name} -> {node.id} used at line "
                           f"{node.lineno} but its def is at line {nested[node.id]}")
    return sorted(set(bad))


@pytest.mark.parametrize("rel", SHIPPED_MODULES)
def test_no_shipped_module_uses_a_star_import(rel: str) -> None:
    """A star import silently disables F821 for the whole file."""
    stars = [f"from {n.module} import *" for n in ast.walk(_tree(rel))
             if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)]
    assert not stars, (
        f"{rel} uses {stars!r}. Ruff cannot resolve a star import, so F821 "
        "degrades to F405 across this entire file and a typo'd name stops being "
        "an error. List the names explicitly instead."
    )


@pytest.mark.parametrize("rel", SHIPPED_MODULES)
def test_no_local_function_is_called_before_its_def(rel: str) -> None:
    """A nested def used earlier in the same body is an UnboundLocalError."""
    bad = called_before_def(_tree(rel), rel)
    assert not bad, (
        "a nested function is referenced above its own def in the same scope, so "
        "the name is an unbound local at that point:\n  " + "\n  ".join(bad)
    )


def test_the_ordering_checker_still_works() -> None:
    """Guard the guard: it passes by finding nothing, so prove it can find something.

    Second case pins the false-positive direction — a helper calling a SIBLING
    defined later is legal, and flagging it would make this guard noise.
    """
    bad = ast.parse("def outer(f):\n"
                    "    if f:\n"
                    "        helper()\n"
                    "        return\n"
                    "    def helper():\n"
                    "        return 1\n")
    assert called_before_def(bad, "s"), "no longer detects a call above its def"

    good = ast.parse("def outer():\n"
                     "    def early():\n"
                     "        return late()\n"
                     "    def late():\n"
                     "        return 1\n"
                     "    return early()\n")
    assert not called_before_def(good, "s"), "a deeper-scope forward reference is legal"
