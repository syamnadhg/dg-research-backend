"""A published wheel says which code is inside it (wave 10.9, OPS-5).

WHAT WAS WRONG

Nobody could prove which code a published wheel held. The wheels of one release
are built on different machines — the Mac here, the Windows box and its WSL for
the others — and a compiled module cannot be read back to its source.
tools/build_compiled.py had no git step, no hash step and wrote no record of any
kind, and nothing at publish time compared the wheels with each other.

A commit stamp alone would not have fixed it: a build tree that arrived by
rsync or zip has no `.git`, so the stamp says "unknown" on exactly the builds it
exists to police. So the build now fingerprints the SOURCE itself, before the
compile replaces it, with CRLF read as LF so a Windows checkout with autocrlf
fingerprints the same code the same way, and tools/check_release.py refuses a
release whose wheels disagree or carry no stamp.

WHAT THESE TESTS PIN

Every test runs the real functions on throwaway trees and throwaway zip
"wheels"; nothing here builds, compiles or publishes anything, and nothing reads
the real repository's sources. The build's own `main` is driven end to end with
pip, wheel and Nuitka replaced by stand-ins that lay files out the way those
tools do, because a stamp function nothing calls — or calls after the compile —
would pass every other test in this file.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load("build_compiled_under_test", "build_compiled.py")
release = _load("check_release_under_test", "check_release.py")

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

VERSION = "0.2.7"


def _tree(root: Path) -> Path:
    """An unpacked source wheel, laid out the way `pip wheel . --no-deps` and
    `wheel unpack` leave it."""
    tree = root / f"superresearch-{VERSION}"
    files = {
        "research.py": "def main():\n    return 0\n",
        **{f"{m}.py": f"NAME = {m!r}\n" for m in build.TOP_MODULES},
        "auth/__init__.py": "",
        "auth/keystore.py": "SLOT = 'a'\n",
        "scripts/__init__.py": "",
        "scripts/selfheal_report.py": "print('report')\n",
        "scripts/dg-supervisor.env.example": "DG_X=1\n",
        f"superresearch-{VERSION}.dist-info/METADATA":
            f"Name: superresearch\nVersion: {VERSION}\n",
        f"superresearch-{VERSION}.dist-info/RECORD": "",
    }
    for rel, text in files.items():
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return tree


def _fingerprint(tree: Path) -> str:
    # The parent of an unpacked tree is a bare temp directory: no git there.
    return build.stamp_tree(tree, tree.parent)["source_sha256"]


# ── stamp_tree: what the fingerprint covers ─────────────────────────────────

def test_the_stamp_is_written_into_the_tree_and_says_what_it_returns(tmp_path):
    tree = _tree(tmp_path)
    stamp = build.stamp_tree(tree, tmp_path)
    on_disk = json.loads((tree / "_sr_build.json").read_text(encoding="utf-8"))
    assert on_disk == stamp
    assert set(stamp) == {"source_sha256", "commit", "dirty"}
    assert re.fullmatch(r"[0-9a-f]{64}", stamp["source_sha256"])


@pytest.mark.parametrize("rel", [
    "research.py",
    f"{build.TOP_MODULES[0]}.py",
    f"{build.TOP_MODULES[-1]}.py",
    "auth/keystore.py",
    "auth/__init__.py",
    "scripts/selfheal_report.py",
])
def test_one_byte_of_first_party_source_changes_the_fingerprint(tmp_path, rel):
    """Each part of what ships: the pipeline, a compiled sibling at either end
    of TOP_MODULES, both packages, and an empty `__init__.py`."""
    tree = _tree(tmp_path)
    before = _fingerprint(tree)
    p = tree / rel
    data = p.read_bytes()
    p.write_bytes(data[:-1] + b"!" if data else b"#")
    assert _fingerprint(tree) != before, f"a change to {rel} left the fingerprint alone"


def test_a_CRLF_checkout_fingerprints_the_same_as_an_LF_one(tmp_path):
    """⛔⛔ The Windows box's tree may be a checkout with autocrlf: the same code
    in different bytes. Without the normalisation every Windows wheel would
    read as different code from the Mac one, forever, and the check would be
    trained to be ignored."""
    lf = _fingerprint(_tree(tmp_path / "lf"))
    crlf_tree = _tree(tmp_path / "crlf")
    for p in crlf_tree.rglob("*.py"):
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert b"\r\n" in (crlf_tree / "research.py").read_bytes()
    assert _fingerprint(crlf_tree) == lf


def test_a_lone_CR_is_still_a_difference(tmp_path):
    """Only CRLF is normalised — the one rewrite autocrlf makes. A lone CR is a
    line break to Python, so `A = 1<CR>B = 2` and `A = 1B = 2` are different
    programs (the second does not even parse); dropping every CR would give
    them one fingerprint."""
    tree = _tree(tmp_path)
    (tree / "research.py").write_bytes(b"A = 1\rB = 2\n")
    split = _fingerprint(tree)
    (tree / "research.py").write_bytes(b"A = 1B = 2\n")
    assert _fingerprint(tree) != split


def test_what_is_not_code_does_not_count(tmp_path):
    """The version in METADATA, the RECORD, the env template and anything else
    that is not a .py file: none of it is source, and a version bump alone must
    not read as different code."""
    tree = _tree(tmp_path)
    before = _fingerprint(tree)
    (tree / f"superresearch-{VERSION}.dist-info/METADATA").write_text(
        "Name: superresearch\nVersion: 9.9.9\n", encoding="utf-8")
    (tree / f"superresearch-{VERSION}.dist-info/RECORD").write_text("x,,\n", encoding="utf-8")
    (tree / "scripts/dg-supervisor.env.example").write_text("DG_X=2\n", encoding="utf-8")
    (tree / "README.txt").write_text("notes\n", encoding="utf-8")
    assert _fingerprint(tree) == before


def test_a_rename_is_a_change(tmp_path):
    """The same bytes under another name ship as another module."""
    tree = _tree(tmp_path)
    before = _fingerprint(tree)
    (tree / "scripts/selfheal_report.py").rename(tree / "scripts/selfheal_report2.py")
    assert _fingerprint(tree) != before


def test_the_order_the_filesystem_lists_files_in_does_not_count(tmp_path, monkeypatch):
    """NTFS, APFS and ext4 list a directory in different orders. The same tree
    must fingerprint the same whichever order it is walked in."""
    tree = _tree(tmp_path)
    before = _fingerprint(tree)
    real = Path.rglob
    monkeypatch.setattr(Path, "rglob", lambda self, pat: reversed(list(real(self, pat))))
    assert _fingerprint(tree) == before


def test_a_tree_without_the_pipeline_is_refused(tmp_path):
    """A stamp over a tree with no research.py describes nothing that ships —
    the wrong directory, most likely — and must not be written."""
    tree = _tree(tmp_path)
    (tree / "research.py").unlink()
    with pytest.raises(SystemExit):
        build.stamp_tree(tree, tmp_path)
    assert not (tree / "_sr_build.json").exists()


# ── stamp_tree: the commit and dirty hints ──────────────────────────────────

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", str(path))
    (path / "research.py").write_text("x = 1\n", encoding="utf-8")
    _git("-C", str(path), "add", "-A")
    _git("-C", str(path), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "init")
    return _git("-C", str(path), "rev-parse", "HEAD").strip()


def test_a_tree_git_cannot_answer_for_says_unknown_not_a_guess(tmp_path):
    """The rsync or zip copy: no `.git`, so commit and dirty are null. The
    fingerprint still stands on its own."""
    stamp = build.stamp_tree(_tree(tmp_path / "t"), tmp_path)
    assert (stamp["commit"], stamp["dirty"]) == (None, None)


@needs_git
def test_a_clean_checkout_names_its_commit(tmp_path):
    repo = tmp_path / "repo"
    head = _git_repo(repo)
    stamp = build.stamp_tree(_tree(tmp_path / "t"), repo)
    assert stamp["commit"] == head
    assert stamp["dirty"] is False


@needs_git
def test_an_edited_checkout_says_it_is_dirty(tmp_path):
    """The commit alone would claim code the tree no longer holds."""
    repo = tmp_path / "repo"
    head = _git_repo(repo)
    (repo / "research.py").write_text("x = 2\n", encoding="utf-8")
    stamp = build.stamp_tree(_tree(tmp_path / "t"), repo)
    assert stamp["commit"] == head
    assert stamp["dirty"] is True


@needs_git
def test_a_repository_with_no_commit_yet_names_none(tmp_path):
    """`git rev-parse --show-toplevel HEAD` there prints the top level AND the
    literal word HEAD, then exits 128. Reading stdout without the exit code
    would stamp the commit as "HEAD"."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", str(repo))
    stamp = build.stamp_tree(_tree(tmp_path / "t"), repo)
    assert (stamp["commit"], stamp["dirty"]) == (None, None)


@needs_git
def test_a_copy_inside_another_repository_does_not_borrow_its_commit(tmp_path):
    """⛔ git walks up to the nearest repository. A zip unpacked inside one (a
    home directory kept in git) would otherwise be stamped with a commit that
    describes none of its code."""
    outer = tmp_path / "outer"
    _git_repo(outer)
    copy = outer / "dg-research-backend"
    copy.mkdir()
    stamp = build.stamp_tree(_tree(tmp_path / "t"), copy)
    assert (stamp["commit"], stamp["dirty"]) == (None, None)


def test_a_machine_without_git_still_gets_a_stamp(tmp_path, monkeypatch):
    def _no_git(*a, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(build.subprocess, "run", _no_git)
    tree = _tree(tmp_path)
    stamp = build.stamp_tree(tree, tmp_path)
    assert (stamp["commit"], stamp["dirty"]) == (None, None)
    assert (tree / "_sr_build.json").exists()


def test_a_status_git_refuses_is_unknown_not_clean(tmp_path, monkeypatch):
    """HEAD readable but `git status` refused (a lock, a permissions fault):
    dirty is unknown, and must not come out as a confident False."""
    def _git_half(repo, *args):
        if args[0] == "rev-parse":
            return f"{repo}\n{'a' * 40}\n"
        return None

    monkeypatch.setattr(build, "_git", _git_half)
    stamp = build.stamp_tree(_tree(tmp_path), tmp_path)
    assert (stamp["commit"], stamp["dirty"]) == ("a" * 40, None)


# ── the build calls it, at the right step ───────────────────────────────────

def _zip_tree(tree: Path, dest: Path) -> None:
    with zipfile.ZipFile(dest, "w") as z:
        for p in sorted(tree.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(tree).as_posix())


@needs_git
def test_the_build_stamps_the_uncompiled_source_into_every_wheel(tmp_path, monkeypatch):
    """⛔⛔ THE CONSUMER. `main` with pip, wheel and Nuitka replaced by stand-ins
    that leave files where those tools leave them. Both wheels it emits (the
    compiled one and the source fallback) must carry the fingerprint of the
    source AS IT SHIPS, uncompiled: stamped after the drop (the unpacked tree
    here holds a DROP_FROM_WHEEL file, as a working tree does), before the
    fallback is packed, and before the compile swaps research.py for the shim.
    Stamped at any other step, or not at all, this fails. The commit is the
    REPOSITORY's, not the temporary tree's, which has no git at all."""
    repo = tmp_path / "repo"
    head = _git_repo(repo)
    outdir = tmp_path / "dist"
    source = _tree(tmp_path / "source")
    dropped = sorted(build.DROP_FROM_WHEEL)[0]
    (source / dropped).write_text("import research\n", encoding="utf-8")
    expected = _fingerprint(_tree(tmp_path / "expected"))

    def _run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        if cmd[1:4] == ["-m", "pip", "wheel"]:
            dest = Path(cmd[cmd.index("-w") + 1])
            (dest / f"superresearch-{VERSION}-py3-none-any.whl").write_bytes(b"")
        elif cmd[1:4] == ["-m", "wheel", "unpack"]:
            shutil.copytree(source, Path(cmd[cmd.index("-d") + 1]) / source.name)
        elif cmd[1:4] == ["-m", "wheel", "pack"]:
            _zip_tree(Path(cmd[4]), Path(cmd[cmd.index("-d") + 1])
                      / f"superresearch-{VERSION}-py3-none-any.whl")
        elif cmd[1:4] == ["-m", "wheel", "tags"]:
            raw = Path(cmd[-1])
            tag = "-".join(cmd[cmd.index(f) + 1]
                           for f in ("--python-tag", "--abi-tag", "--platform-tag"))
            raw.rename(raw.with_name(f"superresearch-{VERSION}-{tag}.whl"))
        else:
            raise AssertionError(f"unexpected build command: {cmd}")

    def _nuitka(src_py, out_dir):
        (Path(out_dir) / f"{Path(src_py).stem}.cpython-3x.so").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build, "REPO", repo)
    monkeypatch.setattr(build, "run", _run)
    monkeypatch.setattr(build, "nuitka_module", _nuitka)
    argv = ["build_compiled.py", "--outdir", str(outdir), "--also-source"]
    if sys.platform == "darwin":
        target = sysconfig.get_platform().split("-")[1]
        monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", target)
        argv += ["--macos-target", target]
    monkeypatch.setattr(sys, "argv", argv)

    build.main()

    wheels = sorted(outdir.glob("*.whl"))
    assert len(wheels) == 2, f"expected the compiled wheel and the fallback: {wheels}"
    for whl in wheels:
        stamp = release.read_stamp(whl)
        assert stamp is not None, f"{whl.name} carries no stamp"
        assert stamp["source_sha256"] == expected, (
            f"{whl.name} is stamped with something other than the uncompiled "
            "source it was built from")
        assert (stamp["commit"], stamp["dirty"]) == (head, False)
    compiled = next(w for w in wheels if "py3-none-any" not in w.name)
    with zipfile.ZipFile(compiled) as z:
        assert "def main():\n    return 0" not in z.read("research.py").decode("utf-8"), (
            "the stand-ins did not reach the compile step — this test measured nothing")
    assert release.main([str(outdir)]) == 0


# ── check_release: one release, one source ──────────────────────────────────

def _wheel(path: Path, stamp) -> Path:
    """A zip shaped like a wheel, with `stamp` as its `_sr_build.json` (a dict
    is written as JSON, bytes verbatim, None leaves it out)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("research.py", "def main():\n    return 0\n")
        if isinstance(stamp, dict):
            z.writestr("_sr_build.json", json.dumps(stamp))
        elif stamp is not None:
            z.writestr("_sr_build.json", stamp)
    return path


def _stamp(src="a" * 64, commit="c" * 40, dirty=False):
    return {"source_sha256": src, "commit": commit, "dirty": dirty}


_PLATFORMS = ("cp313-cp313-macosx_11_0_arm64", "cp313-cp313-win_amd64",
              "cp313-cp313-manylinux_2_28_x86_64")


def _release(tmp_path, *stamps):
    return [_wheel(tmp_path / f"superresearch-{VERSION}-{plat}.whl", s)
            for plat, s in zip(_PLATFORMS, stamps)]


def test_three_wheels_of_one_source_pass(tmp_path, capsys):
    wheels = _release(tmp_path, _stamp(), _stamp(), _stamp())
    assert release.main([str(w) for w in wheels]) == 0
    out = capsys.readouterr().out
    for w in wheels:
        assert w.name in out, "every wheel is listed, so a person can read them side by side"
    assert "a" * 64 in out


def test_one_source_built_from_different_commits_still_passes(tmp_path):
    """Accept polarity: the fingerprint is the authority, the commit a hint. The
    Mac and the Windows box can build the same code from two commits that
    differ only in tests, and that is one release."""
    wheels = _release(tmp_path, _stamp(commit="1" * 40), _stamp(commit=None, dirty=None),
                      _stamp(commit="2" * 40, dirty=True))
    assert release.main([str(w) for w in wheels]) == 0


def test_one_wheel_of_different_source_fails(tmp_path, capsys):
    wheels = _release(tmp_path, _stamp(), _stamp(src="b" * 64), _stamp())
    assert release.main([str(w) for w in wheels]) == 1
    assert "REFUSED" in capsys.readouterr().out


@pytest.mark.parametrize("bad", [
    None,                                   # no stamp at all: built before stamps
    {"commit": "c" * 40, "dirty": False},   # a stamp with no fingerprint
    {"source_sha256": "", "commit": None, "dirty": None},
    b"{not json",
    b"[1, 2]",
], ids=["missing", "no-fingerprint", "empty-fingerprint", "not-json", "not-an-object"])
def test_one_wheel_without_a_usable_stamp_fails(tmp_path, bad):
    """A wheel that cannot say what it holds cannot join the release, however
    the other two agree."""
    wheels = _release(tmp_path, _stamp(), bad, _stamp())
    assert release.main([str(w) for w in wheels]) == 1


def test_a_file_that_is_not_a_wheel_fails(tmp_path):
    wheels = _release(tmp_path, _stamp(), _stamp())
    junk = tmp_path / f"superresearch-{VERSION}-cp313-cp313-win_amd64.whl.part"
    junk.write_bytes(b"not a zip")
    assert release.main([str(w) for w in wheels] + [str(junk)]) == 1


def test_no_wheels_is_not_a_pass(tmp_path):
    """An empty glob or an empty staging directory checked nothing."""
    assert release.main([]) == 1
    empty = tmp_path / "staging"
    empty.mkdir()
    assert release.main([str(empty)]) == 1


def test_a_staging_directory_stands_for_every_wheel_in_it(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    _release(staging, _stamp(), _stamp(), _stamp())
    assert release.main([str(staging)]) == 0
    _wheel(staging / f"superresearch-{VERSION}-py3-none-any.whl", _stamp(src="b" * 64))
    assert release.main([str(staging)]) == 1, "a directory must not stop at its first wheel"


def test_the_build_writes_the_name_the_check_reads(tmp_path):
    """The two scripts spell the stamp's name separately. Stamp a tree with the
    build's function, pack it, read it back with the check's."""
    tree = _tree(tmp_path)
    stamp = build.stamp_tree(tree, tmp_path)
    whl = tmp_path / f"superresearch-{VERSION}-py3-none-any.whl"
    _zip_tree(tree, whl)
    assert release.read_stamp(whl) == stamp
