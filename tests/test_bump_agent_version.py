"""tools/bump_agent_version.py — the agent version-bump helper.

The agent version must move in lockstep across pyproject / _SKILL_BUILD /
__init__ fallback (see the tool's docstring for WHY _SKILL_BUILD can't just read
the package metadata). Hand-editing the three is how they drift — and how the same
bump got authored twice from two machines. These tests pin the helper's behavior on
THROWAWAY trees; they never touch the real repo files.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "bump_agent_version.py"


def _load():
    spec = importlib.util.spec_from_file_location("bump_agent_version_under_test", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bump_mod = _load()


def _make_tree(tmp_path: Path, version: str = "0.1.28", *, crlf: bool = False) -> Path:
    """A minimal stand-in for the three files the tool rewrites."""
    nl = "\r\n" if crlf else "\n"
    pyproject = nl.join([
        "[project]",
        'name = "superresearch-agent"',
        f'version = "{version}"',
        'requires-python = ">=3.11"',
        "",
    ])
    sr = nl.join([
        "# a comment mentioning a version 9.9.9 that must NOT be touched",
        f'_SKILL_BUILD = "{version}"',
        "_TIMEOUT = 30",
        "",
    ])
    init = nl.join([
        "try:",
        "    from importlib.metadata import PackageNotFoundError, version as _pkg_version",
        "",
        "    try:",
        '        __version__ = _pkg_version("superresearch-agent")',
        "    except PackageNotFoundError:",
        f'        __version__ = "{version}"',
        "except Exception:",
        f'    __version__ = "{version}"',
        "",
    ])
    for rel, text in (
        ("agent/pyproject.toml", pyproject),
        ("agent/facade/skill/scripts/sr.py", sr),
        ("agent/facade/__init__.py", init),
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return tmp_path


# ── version validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("v", ["0.1.29", "1.0", "0.1.29rc1", "10.20.30", "0.1.29.post1"])
def test_valid_versions(v):
    assert bump_mod.valid_version(v)


@pytest.mark.parametrize("v", ["", "v0.1.9", "0,1,9", " 0.1.9", "0.1.9 ", "abc"])
def test_invalid_versions(v):
    # The typos that actually happen must be refused, not silently written in.
    assert not bump_mod.valid_version(v)


# ── bump ─────────────────────────────────────────────────────────────────────

def test_bump_rewrites_all_three(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    bump_mod.bump("0.1.29", root=root)
    found = bump_mod.read_versions(root)
    assert found["pyproject"] == ["0.1.29"]
    assert found["_SKILL_BUILD"] == ["0.1.29"]
    assert found["__init__ fallback"] == ["0.1.29", "0.1.29"]  # BOTH fallbacks


def test_bump_leaves_the_metadata_assignment_alone(tmp_path):
    # `__version__ = _pkg_version("superresearch-agent")` is the real source of truth
    # at runtime; only the quoted FALLBACKS may be rewritten.
    root = _make_tree(tmp_path, "0.1.28")
    bump_mod.bump("0.1.29", root=root)
    init = (root / "agent/facade/__init__.py").read_text(encoding="utf-8")
    assert '__version__ = _pkg_version("superresearch-agent")' in init


def test_bump_does_not_touch_unrelated_version_like_text(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    bump_mod.bump("0.1.29", root=root)
    sr = (root / "agent/facade/skill/scripts/sr.py").read_text(encoding="utf-8")
    assert "9.9.9" in sr          # the comment survives
    assert "_TIMEOUT = 30" in sr  # unrelated assignment survives


def test_bump_is_idempotent(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    bump_mod.bump("0.1.29", root=root)
    first = {p: (root / p).read_bytes() for p in
             ("agent/pyproject.toml", "agent/facade/skill/scripts/sr.py",
              "agent/facade/__init__.py")}
    notes = bump_mod.bump("0.1.29", root=root)   # again
    assert all((root / p).read_bytes() == b for p, b in first.items())
    assert all("unchanged" in n for n in notes)


def test_bump_preserves_crlf_line_endings(tmp_path):
    # The repo is checked out CRLF on Windows; rewriting must not flip endings
    # (that would show up as a whole-file diff and churn the hosted twin).
    root = _make_tree(tmp_path, "0.1.28", crlf=True)
    bump_mod.bump("0.1.29", root=root)
    raw = (root / "agent/pyproject.toml").read_bytes()
    assert b"\r\n" in raw                          # CRLF survived the rewrite
    assert b"\n" not in raw.replace(b"\r\n", b"")  # and no BARE LF was introduced
    assert b'version = "0.1.29"' in raw


def test_bump_rejects_a_bad_version(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    with pytest.raises(ValueError):
        bump_mod.bump("v0.1.29", root=root)
    assert bump_mod.read_versions(root)["pyproject"] == ["0.1.28"]  # untouched


def test_bump_errors_on_a_missing_file(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    (root / "agent/facade/__init__.py").unlink()
    with pytest.raises(FileNotFoundError):
        bump_mod.bump("0.1.29", root=root)


# ── --check lockstep ─────────────────────────────────────────────────────────

def test_check_passes_when_in_lockstep(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    ok, msgs = bump_mod.check_lockstep(root)
    assert ok and any("0.1.28" in m for m in msgs)


def test_check_detects_drift(tmp_path):
    root = _make_tree(tmp_path, "0.1.28")
    p = root / "agent/facade/skill/scripts/sr.py"
    p.write_text(p.read_text(encoding="utf-8").replace("0.1.28", "0.1.27"),
                 encoding="utf-8")
    ok, msgs = bump_mod.check_lockstep(root)
    assert not ok and any("DRIFT" in m for m in msgs)


def test_check_detects_a_half_bumped_init(tmp_path):
    # Only ONE of the two __init__ fallbacks edited — the classic hand-edit slip.
    root = _make_tree(tmp_path, "0.1.28")
    p = root / "agent/facade/__init__.py"
    p.write_text(p.read_text(encoding="utf-8").replace("0.1.28", "0.1.29", 1),
                 encoding="utf-8")
    ok, _ = bump_mod.check_lockstep(root)
    assert not ok


# ── Windows-console safety (a real crash hit while building this) ────────────

def test_main_hardens_stdout_for_non_ascii():
    """A release tool must not die on its own status line. Windows consoles are
    cp1252 and cannot encode the check/warn glyphs or the em-dashes this tool's
    messages carry — printing them raised UnicodeEncodeError mid-run while this
    was being built. main() must reconfigure stdout/stderr to UTF-8."""
    import inspect
    assert "reconfigure" in inspect.getsource(bump_mod.main)


def test_status_markers_are_plain_ascii():
    """The marker prefixes themselves stay ASCII, so even an un-hardened stream
    (a caller importing bump()/check_lockstep() directly) can print them."""
    for _ok, msgs in (bump_mod.check_lockstep(),):
        "\n".join(msgs).encode("ascii")   # raises if a marker regressed to unicode


def test_check_output_survives_a_cp1252_console(capsys):
    """--check output must encode on a legacy Windows console."""
    assert bump_mod.main(["--check"]) == 0
    out = capsys.readouterr().out
    out.encode("cp1252")          # raises UnicodeEncodeError if we regress


# ── the REAL repo stays in lockstep (mirrors the agent-suite guard) ──────────

def test_real_repo_is_in_lockstep():
    ok, msgs = bump_mod.check_lockstep()
    assert ok, "\n".join(msgs)
