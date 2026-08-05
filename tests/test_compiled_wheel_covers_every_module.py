"""Every first-party top-level module must be compiled, not shipped as source.

The whole point of the Nuitka build is that `pipx install superresearch` does not
hand out our source. That guarantee is only as good as one hand-maintained list:
`TOP_MODULES` in tools/build_compiled.py. Anything named in pyproject's
`py-modules` but missing from it is packed into the wheel as readable .py, and
nothing anywhere fails — the build prints DONE, the wheel installs, the tests pass
and the code ships in the clear.

That is not hypothetical. `selfheal.py` was added to py-modules on 2026-06-22,
four days after build_compiled.py was written, and shipped readable in every wheel
up to and including the 0.1.12 candidates — ~1160 lines of the self-heal registry
and intent machinery, in the open, for six weeks. It was found by reading a wheel,
which is the only way it COULD be found: the build script's own docstring asserted
that the launcher shim was "the only first-party top-level source file in the
wheel" while that had been false the whole time.

So the invariant is pinned here rather than in a comment. This test reads the two
declarations and compares them; it does not build anything, so it is fast and
runs everywhere.

Deliberately NOT asserting an exact list. A test that hardcodes the module names
has to be edited every time a module is added, which is the same failure mode one
level up — it would be updated by the same person who forgot the build script.
The assertion is the RELATIONSHIP: py-modules ⊆ compiled ∪ {the shim}.
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
BUILD_SCRIPT = REPO / "tools" / "build_compiled.py"

# research.py is not compiled under its own name: it becomes _sr_core.<abi> and a
# small readable launcher shim takes its place, because a .pyd cannot be executed
# as a script and the console entry point needs a stable importable name. It is
# the ONE first-party top-level .py allowed to be readable in the wheel.
SHIM_MODULE = "research"


def _declared_py_modules() -> list[str]:
    """`py-modules = [...]` from pyproject.toml — the modules that get packed.

    Parsed with tomllib rather than a regex: a regex over the raw text counts any
    quoted word between the brackets, including one inside a `#` comment."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    mods = data.get("tool", {}).get("setuptools", {}).get("py-modules")
    assert mods, "could not find `py-modules` in pyproject.toml — has packaging moved?"
    return list(mods)


def _compiled_modules() -> list[str]:
    """`TOP_MODULES = [...]` from tools/build_compiled.py — the modules Nuitka eats.

    Parsed with `ast`, NOT a regex, and the reason is specific. A regex that scrapes
    quoted words out of the list body cannot see comments, so this:

        TOP_MODULES = [
            "models", "prompts", "vision", "narrate",
            # "selfheal",   # nuitka OOMed on the linux builder, re-enable
        ]

    reads as though selfheal is compiled while the build skips it — a FALSE PASS in
    the one direction that matters, reproducing the exact leak this file exists to
    prevent. Inflating `compiled` shrinks `packed - compiled`, so the error is
    silent. (The py-modules side is safe either way: a stray name there inflates
    `packed` and fails loudly, which is the harmless direction.)"""
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "TOP_MODULES" for t in node.targets):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, (list, tuple)), "TOP_MODULES is not a list literal"
        return list(value)
    raise AssertionError("could not find a top-level `TOP_MODULES = [...]` in tools/build_compiled.py")


def test_both_declarations_parse() -> None:
    """Guard against the guard: a regex that silently matched nothing would make
    every assertion below vacuously true, which is the exact shape of the bug this
    file exists to catch."""
    assert len(_declared_py_modules()) >= 2
    assert len(_compiled_modules()) >= 1


def test_every_packed_module_is_compiled() -> None:
    packed = set(_declared_py_modules())
    compiled = set(_compiled_modules()) | {SHIM_MODULE}
    readable = sorted(packed - compiled)
    assert not readable, (
        f"these modules ship as READABLE SOURCE in the wheel: {readable}. They are "
        f"in pyproject's py-modules but not in TOP_MODULES in "
        f"tools/build_compiled.py, so the build packs the .py verbatim. Add them to "
        f"TOP_MODULES and rebuild every platform wheel."
    )


def test_selfheal_specifically_is_compiled() -> None:
    """The instance that motivated the rule. Kept as its own case so a regression
    names the module instead of only the relationship."""
    assert "selfheal" in _compiled_modules(), (
        "selfheal is back to shipping as source — this is the exact 2026-06-22 "
        "regression, ~1160 lines of self-heal internals in the clear"
    )


def test_nothing_is_compiled_that_is_not_shipped() -> None:
    """The other direction. Compiling a module that pyproject does not pack means
    the build spends minutes on a file that never reaches the wheel — a silently
    wasted step, and a sign the two lists have drifted the other way."""
    packed = set(_declared_py_modules())
    stray = sorted(set(_compiled_modules()) - packed)
    assert not stray, (
        f"TOP_MODULES compiles {stray}, which pyproject's py-modules does not ship"
    )


# Hardcoded facts that nothing re-checks. Both of these actually went stale:
# "the 5 top-level modules" survived selfheal becoming the sixth, and "2.1MB"
# survived the core growing to 3.3 MB. Matched as PATTERNS, not as the two exact
# historical strings — an assertion listing only the strings that already went
# wrong catches nothing new, and the first version of this test proved it by
# passing vacuously against "2.1MB" while asserting on "2.1 MB".
_PROSE_COUNTS = [
    (r"the\s+\d+\s+top-level\s+modules", "a module count"),
    (r"\d+(?:\.\d+)?\s*[MK]B\s+core", "a core file size"),
]


@pytest.mark.parametrize("pattern,what", _PROSE_COUNTS)
def test_no_hardcoded_counts_in_prose(pattern: str, what: str) -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    hits = [m.group(0) for m in re.finditer(pattern, text, re.I)]
    assert not hits, (
        f"tools/build_compiled.py states {what} in prose: {hits}. Numbers in comments "
        f"go stale silently and nothing re-checks them — TOP_MODULES is the authority "
        f"for what is compiled, and the core's size is measured at build time."
    )


def test_the_prose_guard_can_actually_fire() -> None:
    """Guard against the guard, the specific way the first version failed: it
    asserted on "the 2.1 MB core" while the file said "2.1MB", so it could never
    match. Prove each pattern matches the text it is meant to reject."""
    samples = {
        r"the\s+\d+\s+top-level\s+modules": "SCOPE (v1): the 5 top-level modules are compiled",
        r"\d+(?:\.\d+)?\s*[MK]B\s+core": "compiling research.py -> _sr_core (the 2.1MB core - slow)",
    }
    for pattern, sample in samples.items():
        assert re.search(pattern, sample, re.I), (
            f"pattern {pattern!r} does not match {sample!r} — it would never fire"
        )
