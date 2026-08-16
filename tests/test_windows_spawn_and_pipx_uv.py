"""Two Windows-only defects found in the 0.1.12 pre-publish audit.

Both are invisible on macOS and Linux, which is why they survived: one shows up
only as pixels on a Windows desktop, the other only on a Windows host whose pipx
carries its own uv. Neither has a symptom the mac side could ever observe.

  1. narrate.py's PowerShell probe span a VISIBLE console. Every other
     powershell/schtasks/wmic spawn in the product passes CREATE_NO_WINDOW because
     the serve worker is itself console-less, so Windows hands any console child a
     brand-new window. This one was missed, on a path that runs every narrate tick.

  2. `_pipx_bundles_uv()` could never return True on Windows. It resolves pipx's
     interpreter from a `#!` shebang, but `_pipx_cmd()` returns `pipx.EXE` there — a
     PE binary. `py` stayed None, so the function always returned False, and the
     upgrade preflight that depends on it flipped from fail-open to fail-closed:
     `--update` and the app's Update button refused an upgrade pipx would have
     completed.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import research

REPO = Path(__file__).resolve().parent.parent
NARRATE = REPO / "narrate.py"


# ── 1. no console flash ───────────────────────────────────────────────────────

def _spawn_calls(path: Path):
    """Every subprocess.run/Popen call in a module, as AST nodes."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in {"run", "Popen", "check_output", "call"}:
            if isinstance(f.value, ast.Name) and f.value.id == "subprocess":
                yield node


def _spawns_a_console_program(call: ast.Call) -> bool:
    """True if argv[0] is a Windows console program that would open a window."""
    if not call.args:
        return False
    first = call.args[0]
    names = []
    if isinstance(first, ast.List):
        for el in first.elts:
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                names.append(el.value)
                break
    elif isinstance(first, ast.Constant) and isinstance(first.value, str):
        names.append(first.value)
    return any(
        Path(n).name.lower() in {"powershell.exe", "schtasks.exe", "wmic.exe", "cmd.exe"}
        for n in names
    )


def test_narrate_never_spawns_a_visible_console() -> None:
    """The regression itself. A missing creationflags here is one black window on
    the user's desktop per narrate tick, for the length of a run, in a product
    whose supervisor runs under pythonw specifically to stay invisible."""
    offenders = [
        call.lineno
        for call in _spawn_calls(NARRATE)
        if _spawns_a_console_program(call)
        and not any(kw.arg == "creationflags" for kw in call.keywords)
    ]
    assert not offenders, (
        f"narrate.py spawns a Windows console program without creationflags at "
        f"line(s) {offenders}. Pass CREATE_NO_WINDOW — otherwise the console-less "
        f"serve worker gets a brand-new visible window every time this runs."
    )


def test_the_console_scan_can_actually_fire() -> None:
    """Guard against the guard: prove the AST scan flags an unflagged spawn, so a
    green result means 'none found' rather than 'scan matched nothing'."""
    bad = ast.parse(
        "import subprocess\n"
        "subprocess.run(['powershell.exe', '-NoProfile', '-Command', 'x'],\n"
        "               capture_output=True)\n"
    )
    calls = [n for n in ast.walk(bad) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "run"]
    assert calls and _spawns_a_console_program(calls[0])
    assert not any(kw.arg == "creationflags" for kw in calls[0].keywords)


RESEARCH = REPO / "research.py"

# The two copies of the Windows User-scope env probe. They are twins by
# intention, not by accident, and they have already drifted once — the
# CREATE_NO_WINDOW flag went missing from the narrate side inside the very
# commit that aligned them.
_TWINS = (
    (RESEARCH, "_read_user_scope_env"),
    (NARRATE, "_read_user_scope_env_safe"),
)


def _powershell_probe(path: Path, func_name: str) -> "tuple[ast.Module, ast.AST, ast.Call]":
    """The one `subprocess.run` inside a named function, with the module and
    function nodes around it. Raises if either the function or the call is gone,
    so a rename cannot quietly empty this guard."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == func_name), None)
    assert fn is not None, f"{path.name} no longer defines {func_name}()"
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute) and c.func.attr == "run"]
    assert len(calls) == 1, (
        f"{path.name}:{func_name}() has {len(calls)} subprocess.run calls, not 1 — "
        f"this comparison no longer knows which one is the probe"
    )
    return tree, fn, calls[0]


def _shape(call: ast.Call) -> tuple:
    """The comparable shape of a spawn: its argv with interpolations collapsed
    to a placeholder, plus every keyword except the flags value.

    Collapsing the f-string is what makes the two sides comparable at all —
    one interpolates `name` into the PowerShell command, and the literal text
    around it is the part that must not drift. The creationflags VALUE is
    excluded here because the two sides reach it by different NAMES; it is
    compared separately, after each name is resolved.
    """
    argv: list = []
    first = call.args[0] if call.args else None
    assert isinstance(first, ast.List), "the probe no longer passes a literal argv"
    for el in first.elts:
        if isinstance(el, ast.Constant):
            argv.append(el.value)
        elif isinstance(el, ast.JoinedStr):
            argv.append("".join(
                p.value if isinstance(p, ast.Constant) else "{}" for p in el.values))
        else:
            argv.append("<expr>")
    kwargs = {}
    for kw in call.keywords:
        if kw.arg == "creationflags":
            continue
        kwargs[kw.arg] = (kw.value.value if isinstance(kw.value, ast.Constant)
                          else "<expr>")
    return tuple(argv), tuple(sorted(kwargs.items()))


def test_narrate_probe_matches_the_research_twin() -> None:
    """The two implementations are copies of each other; they must not drift again.

    ⚠ This used to assert `"CREATE_NO_WINDOW" in src` — a substring that a
    COMMENT satisfies, that says nothing about whether the flag reaches the
    spawn, and that cannot see any other kind of divergence at all: a changed
    PowerShell command, a different timeout, a dropped `capture_output`. It was
    named for drift detection while being unable to detect drift. The reviewer
    was right to call it out; this compares the two calls.
    """
    shapes = {}
    for path, fn_name in _TWINS:
        probe = _powershell_probe(path, fn_name)
        shapes[path.name] = (_shape(probe[2]), _flags_source(*probe))
    (a_name, a), (b_name, b) = shapes.items()
    assert a == b, (
        f"the User-scope env probes in {a_name} and {b_name} have drifted:\n"
        f"  {a_name}: {a}\n  {b_name}: {b}"
    )


def _flags_source(tree: ast.Module, fn: ast.AST, call: ast.Call) -> "str | None":
    """The `creationflags` expression, resolved one hop through whichever name
    the call uses — a local inside the probe, or a module-level constant.

    Necessary because the two twins spell the same value differently: research
    hoists it into the module constant `_PS_NO_WINDOW` (it has many PowerShell
    spawns), narrate binds a local `no_window` (it has one). Comparing the
    spellings would fail on a difference that is not drift; resolving them
    compares what each actually passes.

    ⚠ Cannot be a runtime read: both evaluate to 0 off Windows, so every host in
    CI would see "no flag" and "the right flag" as identical.
    """
    flags = next((kw for kw in call.keywords if kw.arg == "creationflags"), None)
    if flags is None:
        return None
    if isinstance(flags.value, ast.Name):
        want = flags.value.id
        for scope in (fn, tree):
            for node in ast.walk(scope):
                if isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == want
                        for t in node.targets):
                    return ast.unparse(node.value)
    return ast.unparse(flags.value)


def test_both_twins_pass_a_no_window_flag() -> None:
    """The specific drift that shipped. `_shape` excludes the flags VALUE so the
    two sides may name it differently; that each one passes it is not optional,
    because the serve worker is console-less and Windows hands any console child
    a brand-new visible window without it."""
    for path, fn_name in _TWINS:
        src = _flags_source(*_powershell_probe(path, fn_name))
        assert src is not None, (
            f"{path.name}:{fn_name}() spawns PowerShell with no creationflags — one "
            f"black window on the user's desktop per call"
        )
        assert "CREATE_NO_WINDOW" in src, (
            f"{path.name}:{fn_name}() passes creationflags, but not the no-window "
            f"flag: {src}"
        )


def test_the_twin_comparison_can_actually_fire() -> None:
    """Guard against the guard, and the reason this rewrite exists: prove the
    comparison FAILS on a divergence. The assertion it replaced passed against
    a probe with the flag missing entirely."""
    drifted = ast.parse(
        "import subprocess\n"
        "def probe(name):\n"
        "    return subprocess.run(\n"
        "        ['powershell.exe', '-NoProfile', '-Command',\n"
        "         f\"[System.Environment]::GetEnvironmentVariable('{name}','Machine')\"],\n"
        "        capture_output=True, text=True, timeout=9)\n"
    )
    call = next(c for c in ast.walk(drifted) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute) and c.func.attr == "run")
    real = _shape(_powershell_probe(*_TWINS[0])[2])
    assert _shape(call) != real, "the shape comparison cannot see a real divergence"
    assert not any(kw.arg == "creationflags" for kw in call.keywords)


# ── 2. pipx's bundled uv is reachable on Windows ──────────────────────────────

class _Result:
    def __init__(self, rc: int, out: str = "") -> None:
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def test_pipx_bundles_uv_resolves_an_interpreter_from_an_exe_shim(monkeypatch, tmp_path) -> None:
    """The defect, reproduced through the exact Windows shape: pipx is a .exe, so
    there is no shebang to read. Before the fix this returned False no matter what
    pipx reported, because `py` could never be assigned."""
    shim = tmp_path / "pipx.exe"
    shim.write_bytes(b"MZ\x90\x00" + b"\x00" * 64)          # a real PE preamble

    venvs = tmp_path / "venvs"
    for rel in (("Scripts", "python.exe"), ("bin", "python3")):
        p = venvs.joinpath("pipx", *rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")

    monkeypatch.setattr(research, "_pipx_cmd", lambda: [str(shim)])

    seen: list = []

    def fake_run(argv, **kw):
        seen.append(argv)
        if "environment" in argv:
            return _Result(0, str(venvs))
        if len(argv) >= 2 and argv[1] == "-c":
            return _Result(0)                                # `import uv` succeeds
        return _Result(1)

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    assert research._pipx_bundles_uv() is True, (
        "a Windows .exe shim still cannot resolve pipx's interpreter — the preflight "
        "will refuse upgrades that pipx would complete"
    )
    assert any("environment" in a for a in seen), "it never asked pipx where its venvs live"


def test_it_still_returns_false_when_uv_is_genuinely_absent(monkeypatch, tmp_path) -> None:
    """Guard against the guard: the fix must not vouch unconditionally. If pipx's
    own interpreter cannot import uv, the answer is still no."""
    shim = tmp_path / "pipx.exe"
    shim.write_bytes(b"MZ\x90\x00")
    venvs = tmp_path / "venvs"
    p = venvs / "pipx" / "Scripts" / "python.exe"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")

    monkeypatch.setattr(research, "_pipx_cmd", lambda: [str(shim)])

    def fake_run(argv, **kw):
        if "environment" in argv:
            return _Result(0, str(venvs))
        return _Result(1)                                    # `import uv` fails

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    assert research._pipx_bundles_uv() is False


def test_a_broken_pipx_environment_is_not_fatal(monkeypatch, tmp_path) -> None:
    """The branch must stay strictly additive: anything unexpected leaves the old
    answer (False) rather than raising into the caller's preflight."""
    shim = tmp_path / "pipx.exe"
    shim.write_bytes(b"MZ\x90\x00")
    monkeypatch.setattr(research, "_pipx_cmd", lambda: [str(shim)])

    for behaviour in (
        lambda argv, **kw: _Result(1),                        # pipx environment fails
        lambda argv, **kw: _Result(0, ""),                    # empty answer
        lambda argv, **kw: _Result(0, str(tmp_path / "nope")),  # dir does not exist
    ):
        monkeypatch.setattr(research.subprocess, "run", behaviour)
        assert research._pipx_bundles_uv() is False

    def boom(argv, **kw):
        raise OSError("pipx exploded")

    monkeypatch.setattr(research.subprocess, "run", boom)
    assert research._pipx_bundles_uv() is False


def test_the_dash_m_form_still_wins_without_asking_pipx(monkeypatch) -> None:
    """`[python, '-m', 'pipx']` already names its interpreter — the new fallback
    must not add a subprocess round-trip to a path that was already correct."""
    monkeypatch.setattr(research, "_pipx_cmd", lambda: [sys.executable, "-m", "pipx"])
    calls: list = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return _Result(0)

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    assert research._pipx_bundles_uv() is True
    assert not any("environment" in a for a in calls), (
        "it asked pipx for its venv dir even though the -m form already named the "
        "interpreter"
    )
