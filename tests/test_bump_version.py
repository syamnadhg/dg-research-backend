"""tools/bump_version.py — the agent + BE version-bump helper.

The agent version must move in lockstep across pyproject / _SKILL_BUILD /
__init__ fallback (see the tool's docstring for WHY _SKILL_BUILD can't just read
the package metadata); the BE version is a single pyproject line whose bump must
re-seed the release-dep guard snapshot. Hand-editing these is how they drift — and
how the same bump got authored twice from two machines. These tests pin the helper's
behavior on THROWAWAY trees; they never touch the real repo files.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "bump_version.py"


def _load():
    spec = importlib.util.spec_from_file_location("bump_version_under_test", _TOOL)
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


# ── BE (superresearch) bump + release-dep guard re-seed ──────────────────────

def _make_be_tree(tmp_path: Path, version: str = "0.1.8",
                  deps=("anthropic>=0.85", "requests>=2.32")) -> Path:
    """A throwaway tree with a root pyproject + a REAL copy of the release-dep
    guard, so bump_be can load + re-seed the guard against THIS tree (not the repo)."""
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    dep_lines = "\n".join(f'    "{d}",' for d in deps)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "superresearch"\n'
        f'version = "{version}"\n'
        "dependencies = [\n" + dep_lines + "\n]\n",
        encoding="utf-8")
    real_guard = Path(__file__).resolve().parents[1] / "tests" / "test_release_dep_version_guard.py"
    shutil.copy(real_guard, tmp_path / "tests" / "test_release_dep_version_guard.py")
    return tmp_path


def test_bump_be_rewrites_version_and_reseeds(tmp_path):
    root = _make_be_tree(tmp_path, "0.1.8")
    notes = bump_mod.bump_be("0.1.9", root=root)
    assert bump_mod.read_be_version(root) == ["0.1.9"]
    snap = json.loads((root / "tests" / "released_deps.json").read_text(encoding="utf-8"))
    assert snap["version"] == "0.1.9"          # snapshot moved with the version
    ok, msgs = bump_mod.check_be(root)
    assert ok, "\n".join(msgs)                 # the canonical guard now passes
    assert any("re-seeded" in n for n in notes)


def test_bump_be_is_idempotent(tmp_path):
    root = _make_be_tree(tmp_path, "0.1.8")
    bump_mod.bump_be("0.1.9", root=root)
    notes = bump_mod.bump_be("0.1.9", root=root)   # again
    assert any("unchanged" in n for n in notes)
    assert bump_mod.read_be_version(root) == ["0.1.9"]


def test_bump_be_rejects_a_bad_version(tmp_path):
    root = _make_be_tree(tmp_path, "0.1.8")
    with pytest.raises(ValueError):
        bump_mod.bump_be("v0.1.9", root=root)
    assert bump_mod.read_be_version(root) == ["0.1.8"]  # untouched


def test_bump_be_refuses_ambiguous_version_lines(tmp_path):
    # A stray column-0 `version = ` in another table must make the bump refuse,
    # not rewrite both — the anchor can't tell them apart.
    root = _make_be_tree(tmp_path, "0.1.8")
    p = root / "pyproject.toml"
    p.write_text(p.read_text(encoding="utf-8") + '\n[tool.other]\nversion = "9.9.9"\n',
                 encoding="utf-8")
    with pytest.raises(ValueError):
        bump_mod.bump_be("0.1.9", root=root)


def test_check_be_detects_a_stale_snapshot(tmp_path):
    # Deps unchanged but the version moved without a re-seed → the guard must fail.
    root = _make_be_tree(tmp_path, "0.1.8")
    bump_mod.reseed_released_deps(root)            # snapshot pinned at 0.1.8
    p = root / "pyproject.toml"
    p.write_text(p.read_text(encoding="utf-8").replace('version = "0.1.8"', 'version = "0.1.9"'),
                 encoding="utf-8")
    ok, msgs = bump_mod.check_be(root)
    assert not ok and any("guard" in m.lower() for m in msgs)


def test_main_requires_an_action():
    with pytest.raises(SystemExit):
        bump_mod.main([])   # no --agent/--be/--check


def test_main_check_covers_agent_and_be(capsys):
    # Against the REAL repo (in lockstep + guard-clean after this release bump).
    assert bump_mod.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "agent version lockstep OK" in out
    assert "BE release-dep guard OK" in out


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


# ── the hosted-skill twin sync, 2026-09-01 ───────────────────────────────────
#
# ⛔⛔ THIS SYNC HAS BEEN A NO-OP AT EVERY RELEASE, AND IT REPORTED SUCCESS-ISH.
# `sync_fe_twin` shells out to the frontend's own sync script, which takes the
# skill bundle's path as its first positional argument. This tool passed none, so
# the FE script fell back to a hardcoded sibling layout that does not exist in
# this checkout, printed its own "not found", and exited 1 — which `bump()`
# renders as a WARNING and carries on from. The twin was only ever current
# because somebody re-ran the script by hand after the bump.
#
# ⭐ Pinned on the ARGV, not on the message. A test asserting the warning text
# would have passed throughout the entire period the sync did nothing.

def _fake_web(tmp_path):
    """A throwaway web checkout holding a stub sync script."""
    web = tmp_path / "web"
    (web / "scripts").mkdir(parents=True)
    (web / "scripts" / "sync-agent-skill.mjs").write_text("// stub\n")
    return web


def test_sync_passes_the_skill_bundle_path_as_argv(tmp_path, monkeypatch):
    """⛔ THE FIX. The bundle lives in THIS repo beside this tool, so the other
    repo must never have to guess our directory layout."""
    root = tmp_path / "be"
    (root / "agent" / "facade" / "skill").mkdir(parents=True)
    web = _fake_web(tmp_path)
    monkeypatch.setenv("SR_WEB_ROOT", str(web))
    monkeypatch.setattr(bump_mod.shutil, "which", lambda _n: "/usr/bin/node")

    seen = {}

    class _Done:
        returncode = 0
        stdout = "synced 2 files"
        stderr = ""

    def _fake_run(argv, **kw):
        seen["argv"] = argv
        return _Done()

    monkeypatch.setattr(bump_mod.subprocess, "run", _fake_run)
    ok, msg = bump_mod.sync_fe_twin(root)
    assert ok, msg
    # node, the script, AND the source path — three arguments, not two.
    assert len(seen["argv"]) == 3, seen["argv"]
    assert seen["argv"][2] == str(root / "agent" / "facade" / "skill")


def test_sync_refuses_rather_than_letting_the_fe_guess(tmp_path, monkeypatch):
    """⛔ A missing bundle STOPS here with a path in the message. Letting it run
    argument-less is exactly the silent no-op this pair of tests exists for: the
    FE would guess, fail, and the bump would shrug."""
    root = tmp_path / "be"          # no agent/facade/skill inside
    root.mkdir()
    web = _fake_web(tmp_path)
    monkeypatch.setenv("SR_WEB_ROOT", str(web))
    monkeypatch.setattr(bump_mod.shutil, "which", lambda _n: "/usr/bin/node")

    def _must_not_run(*_a, **_kw):
        raise AssertionError("the sync ran without a bundle to sync from")

    monkeypatch.setattr(bump_mod.subprocess, "run", _must_not_run)
    ok, msg = bump_mod.sync_fe_twin(root)
    assert ok is False
    assert "no skill bundle" in msg


def test_the_real_checkout_is_found_with_NO_env_override(tmp_path, monkeypatch):
    """⛔⛔ THE GUARD THAT WAS MISSING, AND ITS ABSENCE IS WHY THE FIRST FIX WAS
    HALF A FIX. Every other test here sets `SR_WEB_ROOT`, so not one of them ever
    exercised the DEFAULT — and the default pointed at `research-app/web`, a
    layout that does not exist. `sync_fe_twin` therefore failed its
    `script.exists()` check before reaching the argument fix at all.

    ⭐ Asserted against the REAL checkout on disk, with the override explicitly
    cleared. A fixture would have proved only that the probe loop runs."""
    monkeypatch.delenv("SR_WEB_ROOT", raising=False)
    root = Path(bump_mod.__file__).resolve().parents[1]
    web = bump_mod._web_root(root)
    assert (web / "scripts" / "sync-agent-skill.mjs").is_file(), (
        f"the default web root does not hold the sync script: {web}. The release "
        f"sync short-circuits here, before the bundle path is ever passed."
    )


def test_an_env_override_still_wins_over_the_probe(tmp_path, monkeypatch):
    """The override is how a non-standard checkout works, and probing must not
    quietly outrank an explicit instruction."""
    monkeypatch.setenv("SR_WEB_ROOT", str(tmp_path / "elsewhere"))
    assert bump_mod._web_root(Path("/nope")) == tmp_path / "elsewhere"


def test_the_real_repo_has_the_bundle_where_the_tool_looks(tmp_path):
    """⭐ The path is not a guess in a test fixture either — it is where the
    bundle actually is. A rename that moved it would make the two tests above
    pass against a directory nobody ships."""
    root = Path(bump_mod.__file__).resolve().parents[1]
    assert (root / "agent" / "facade" / "skill" / "SKILL.md").is_file()
