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
from _wheel_surface import dropped_from_wheel, wheel_shipped_sources

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


def _first_party_top_level_imports(*sources: Path) -> "dict[str, str]":
    """Module-scope imports of top-level first-party modules, name -> where.

    ⛔⛔ 2026-08-19 — THE MISSING THIRD LEG, and it cost a launch-blocking hole.
    `telemetry.py` was added on 2026-08-18 and `research.py` imports it at module
    scope, unguarded — but it was in NEITHER py-modules NOR TOP_MODULES, and every
    assertion in this file compares those two lists TO EACH OTHER. A module absent
    from both satisfies the relationship perfectly. The next wheel would have
    raised `ModuleNotFoundError: telemetry` before printing a single line, and the
    only thing that would have caught it is running the wheel.

    So the two declarations are now also checked against the SOURCE: whatever
    research.py and the auth package actually import has to be shipped. Derived
    with `ast`, never a list here, because a hardcoded list is maintained by the
    same person who forgot the build script.

    Module scope only. A guarded or function-local import is a deliberate optional
    dependency and this must not start demanding those ship.
    """
    first_party = {
        p.stem for p in REPO.glob("*.py")
        if not p.name.startswith("test_") and p.name != "conftest.py"
    }
    found: "dict[str, str]" = {}
    for src in sources:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in tree.body:            # top level ONLY
            names: "list[str]" = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in first_party:
                    found.setdefault(name, src.name)
    return found


def test_the_import_scan_actually_finds_something() -> None:
    """Guard against the guard. A scan that matched nothing — a moved repo root,
    an `ast` field rename — would make the assertion below vacuously true, which
    is the precise shape of the bug it exists to catch."""
    found = _first_party_top_level_imports(REPO / "research.py")
    assert "telemetry" in found, (
        "the scanner cannot see research.py's own module-scope imports")


def _shipped_sources() -> "list[Path]":
    """Every file whose module-scope imports must be satisfied by the wheel.

    ⛔⛔ ONE DEFINITION, and it is here because of a mutation survivor. Narrowing
    the assertion's own inline list to research.py alone changed nothing
    observable — everything `auth/` imports today happens to be shipped — so the
    coverage was resting on a coincidence, and a separate test that called the
    scanner with its OWN list could not see the narrowing at all. Both the
    assertion and the auth-is-covered test now read this, so shrinking it turns
    two tests red instead of none.

    ⛔⛔ 2026-09-17 — AND IT WAS STILL THE WRONG LIST. `research.py + auth/*.py`
    is not the wheel's source surface: the other SEVEN py-modules (models,
    prompts, vision, narrate, selfheal, telemetry, logquiet) and the whole
    shipped `scripts` package were never read, so the 2026-08-19 hole was closed
    for research.py alone. A module-scope `import <something>` added to any of
    them of a module missing from py-modules would ship a wheel that raises
    ModuleNotFoundError on startup — the same launch-blocker, one file over.

    It is now the DERIVED surface (tests/_wheel_surface.py), which the wave 2
    guard already read. Not a second list here: the narrow list is exactly the
    kind that goes stale, and this one did. `research.py` is added back because
    the derivation excludes the launcher shim on purpose and the shim's source
    is where `telemetry` was caught."""
    return [REPO / "research.py", *wheel_shipped_sources()]


def test_the_scan_reaches_the_auth_package_too() -> None:
    """`auth/credentials.py` imports `logquiet` at module scope, and that is what
    proves the package is in scope — not a comment saying it is."""
    auth_sources = [p for p in _shipped_sources() if p.parent.name == "auth"]
    assert auth_sources, (
        "the auth package dropped out of the shipped-source list, so an auth "
        "module could import something the wheel does not carry")
    found = _first_party_top_level_imports(*auth_sources)
    assert found.get("logquiet") == "credentials.py", (
        f"the auth package is scanned but its imports are not seen: {found}")


def test_the_scan_covers_every_module_the_wheel_packs() -> None:
    """The relationship the narrow list broke: a module the wheel PACKS must
    also be a module the wheel scans.

    Anything in py-modules is shipped, so whatever it imports at module scope
    has to be shipped with it — and the import guard below can only say that
    about files it reads. Until 2026-09-17 it read one of the eight: seven
    shipped modules could import an unpacked module and the three assertions in
    this file all stayed green, which is the 08-19 telemetry hole in a different
    file.

    Written as py-modules ⊆ scanned rather than as a list of names, because a
    list here is maintained by the same person who forgot to widen the scan."""
    scanned = {p.relative_to(REPO).as_posix() for p in _shipped_sources()}
    unscanned = sorted(m for m in _declared_py_modules() if f"{m}.py" not in scanned)
    assert not unscanned, (
        f"pyproject packs {unscanned} into the wheel, but the import scan never "
        f"reads them — a module-scope first-party import in any of those ships a "
        f"wheel that dies with ModuleNotFoundError before printing a line, and "
        f"every assertion in this file stays green. Scanned: {sorted(scanned)}"
    )


def test_the_scan_reaches_the_compiled_siblings_too() -> None:
    """The auth test's twin for the seven sibling modules — and the same reason
    it exists: a list that CLAIMS to cover them proves nothing, a module-scope
    import actually seen inside one of them does.

    `telemetry.py -> logquiet` is the pin that matters most. telemetry is the
    module whose absence from py-modules was the 08-19 launch blocker, and it in
    turn imports another first-party module at module scope — so the file that
    started this whole class of defect is now inside the scan instead of only
    being named by it."""
    siblings = [p for p in _shipped_sources()
                if p.parent == REPO and p.name != "research.py"]
    assert siblings, (
        "the compiled sibling modules dropped out of the shipped-source list, so "
        "models/prompts/vision/narrate/selfheal/telemetry/logquiet could each "
        "import something the wheel does not carry")
    found = _first_party_top_level_imports(*siblings)
    assert found.get("logquiet") == "telemetry.py", (
        f"telemetry.py is listed but its module-scope imports are not seen: {found}")
    assert found.get("models") in {"prompts.py", "vision.py", "narrate.py"}, (
        f"the compiled siblings are listed but their imports are not seen: {found}")


def test_the_scan_reaches_the_shipped_scripts_but_not_the_dropped_ones() -> None:
    """pyproject ships `scripts` WHOLESALE (packages = ["auth", "scripts"]) minus
    whatever tools/build_compiled.py deletes out of the packed tree, so the
    package is shipped source the scan owes the same guarantee to — and the
    build's DROP_FROM_WHEEL list is the only thing that says which of its files
    are source-tree diagnostics rather than product.

    Both halves in one test on purpose: scanning the package but not honouring
    the drop would report a file as shipped that the wheel does not contain.

    The dropped half is DERIVED, not a filename written here, and the file it
    names must exist on disk — otherwise "it is not in the scan" is true of a
    file nobody ships anyway and the assertion is passing vacuously."""
    rels = {p.relative_to(REPO).as_posix() for p in _shipped_sources()}
    assert any(r.startswith("scripts/") for r in rels), (
        f"the shipped scripts package is not scanned at all: {sorted(rels)}")

    on_disk = sorted(r for r in dropped_from_wheel() if (REPO / r).exists())
    assert on_disk, (
        "no file in tools/build_compiled.py's DROP_FROM_WHEEL exists in this "
        "tree, so the half below asserts nothing")
    scanned_anyway = sorted(r for r in on_disk if r in rels)
    assert not scanned_anyway, (
        f"{scanned_anyway} are DROPPED from the wheel by tools/build_compiled.py "
        f"but the scan reads them as if they shipped — their imports are not the "
        f"wheel's problem, and demanding them would push a source-tree diagnostic "
        f"into py-modules")


def test_a_guarded_or_function_local_import_is_not_demanded(tmp_path) -> None:
    """⛔ FOUND BY MUTATION, THE OTHER DIRECTION. Widening the walk from
    `tree.body` to `ast.walk` also survived, because nothing first-party is
    currently imported optionally — so the "module scope only" rule was untested.
    A guarded import is a deliberate optional dependency and must not start
    demanding to ship."""
    src = tmp_path / "probe.py"
    src.write_text(
        "def f():\n"
        "    import selfheal\n"
        "    return selfheal\n"
        "try:\n"
        "    import narrate\n"
        "except Exception:\n"
        "    narrate = None\n",
        encoding="utf-8")
    found = _first_party_top_level_imports(src)
    assert "selfheal" not in found, "a function-local import was demanded"
    assert "narrate" not in found, "a guarded import was demanded"
    # …and the positive half, so this cannot pass by scanning nothing at all.
    src.write_text("import selfheal\n", encoding="utf-8")
    assert "selfheal" in _first_party_top_level_imports(src)


def test_every_module_the_source_imports_is_shipped() -> None:
    found = _first_party_top_level_imports(*_shipped_sources())
    packed = set(_declared_py_modules())
    missing = sorted(f"{name} (imported by {where})"
                     for name, where in found.items() if name not in packed)
    assert not missing, (
        f"these modules are imported at MODULE SCOPE but pyproject's py-modules "
        f"does not ship them: {missing}. An installed wheel raises "
        f"ModuleNotFoundError on startup — before it can print anything."
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
