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


def test_narrate_probe_matches_the_research_twin() -> None:
    """The two implementations are copies of each other; they must not drift again."""
    src = NARRATE.read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in src, (
        "narrate.py no longer references CREATE_NO_WINDOW — the User-scope env probe "
        "is a twin of research.py's _read_user_scope_env and needs the same flag"
    )


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
