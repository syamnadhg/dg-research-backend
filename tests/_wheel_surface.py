"""The first-party source surface the WHEEL ships — ONE derivation, two readers.

Two different guards need the same fact, and until 2026-09-17 they each had
their own answer to it:

  * tests/test_review_wave2_0813.py asks "does anything that ships alongside the
    launcher shim reach the pipeline by the name `research`?" — and derived the
    full surface (every py-module + every packaged file minus the ones the build
    drops).
  * tests/test_compiled_wheel_covers_every_module.py asks "is every module these
    files import at module scope actually packed into the wheel?" — and read
    research.py plus auth/*.py ONLY. The other seven py-modules and the whole
    shipped `scripts` package were unscanned, so a module-scope first-party
    import added to models.py / prompts.py / vision.py / narrate.py /
    selfheal.py / telemetry.py / logquiet.py of something absent from py-modules
    was invisible: the wheel would raise ModuleNotFoundError on startup, which
    is exactly the 2026-08-19 `telemetry` hole one level out.

Two lists that must agree is the defect, not the cure — the narrow one is the
one that goes stale, and it did. So the derivation lives here and both files
read it. It is guarded from BOTH sides: test_the_shipped_surface_scan_is_not_empty
(wave 2) pins that it still sees the compiled siblings, the scripts package and
nothing the build drops; test_the_scan_covers_every_module_the_wheel_packs and
its two siblings (the compiled-wheel file) pin that the import scan's own list
still reaches every one of them.

⚠ `research.py` is NOT in this list. In the wheel it is a launcher shim
exporting only `main` — that asymmetry is the entire subject of the wave 2
guard, so it excludes it deliberately. A caller that needs the shim's SOURCE
scanned (the import guard does — it is where `telemetry` was caught) adds it
back explicitly rather than having it appear here by accident.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
BUILD_SCRIPT = REPO / "tools" / "build_compiled.py"


def dropped_from_wheel() -> "set[str]":
    """`DROP_FROM_WHEEL` from tools/build_compiled.py — repo-relative paths the
    build deletes out of the packed tree (source-tree diagnostics that reach the
    pipeline by the name `research`, which in a wheel is the shim).

    Read with `ast`, and asserted non-empty by every caller's use of it: a
    derivation that silently resolved to nothing would report files as SHIPPED
    that the wheel does not contain."""
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"))
    dropped: "set[str]" = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "DROP_FROM_WHEEL" for t in node.targets)):
            dropped = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return dropped


def wheel_shipped_sources() -> "list[Path]":
    """Every first-party .py the WHEEL contains, read from the two declarations
    that decide it rather than from a hand-kept list here.

    ⚠ A hardcoded list is what made the first version of the wave 2 guard
    useless: it named the five compiled sibling modules, so it could not see the
    same defect sitting in the `scripts/` package — which pyproject ships
    wholesale, minus whatever the build script drops. Deriving the set means a
    new shipped file is covered the day it is added, by the person who added
    it."""
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool = (pyproject.get("tool") or {}).get("setuptools") or {}

    dropped = dropped_from_wheel()
    assert dropped, "DROP_FROM_WHEEL could not be read — this scan would over-report"

    out = [REPO / f"{m}.py" for m in tool.get("py-modules", []) if m != "research"]
    for pkg in tool.get("packages", []):
        for path in sorted((REPO / pkg).rglob("*.py")):
            if path.relative_to(REPO).as_posix() in dropped:
                continue
            out.append(path)
    return [p for p in out if p.exists()]
