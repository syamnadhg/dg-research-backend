"""The post-publish step, rehearsed end to end on throwaway copies of BOTH repos.

⛔⛔ WHY THIS EXISTS (2026-09-23). `tools/bump_version.py --post-publish` is the
one command run after the agent reaches PyPI, and it had no test at all. Its first
rehearsal - the real tool, a copy of the web repo, PyPI faked to list 0.1.33 - left
the web unit suite at "3 failed | 7258 passed" on the day of the publish:

  * the hosted-skill test guarded "the served copy has none of 0.1.33's code" with
    `if (AGENT_WHEEL_PUBLISHED === "0.1.32")`, and the tool rewrote the version
    without inverting the assertion inside it;
  * two mutation-harness mutants anchored `AGENT_LOG_STEP_PUBLISHED = false;`,
    which matches nothing once the flag moves, so the anchor ratchet went red;
  * the commit line it printed named `tests/unit`, and nothing that it had
    actually broken.

Every piece of that was invisible until the step ran, and the step runs once per
release. So this runs it: both repos copied, PyPI served from a local page, the
tool's own `main()` loaded FROM THE COPY, then the web tests that read the release
state and the whole anchor ratchet run inside the copied web repo. Nothing touches
either real checkout, and nothing reaches the network.

⭐ BOTH DIRECTIONS. With the version missing from the fake index the step must
refuse and change nothing; with it present, it must leave every selected web test
green, and every file it changed must be named in the commit it prints.

⛔ THE WEB CHECKOUT is `SR_WEB_REPO` when set - and then a missing checkout, node or
`node_modules` is a FAILURE, never a skip, because somebody asked for this - else a
sibling `dg-research` beside this repo or beside the checkout this worktree belongs
to. Only with none of those on disk does it skip, naming what it tried.
"""
from __future__ import annotations

import hashlib
import http.server
import importlib.util
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
GATES = "src/lib/agent-release-gates.ts"

#: What marks a web unit test as reading the release state. A test that does is
#: exactly the kind that hard-codes one side of the publish, so the selection is
#: made by CONTENT and a new one joins without anyone listing it here.
RELEASE_STATE_NEEDLES = ("agent-release-gates", "AGENT_LOG_STEP_PUBLISHED",
                         "AGENT_WHEEL_PUBLISHED", ".well-known", "agent-skill-sync")
#: The anchor ratchet: every harness anchor still matches once, every mutant still
#: applies and parses. It is what saw the two anchors the flip broke.
RATCHET = "tests/unit/mutationHarnessAnchorRatchet.test.ts"


# ── where the web checkout is ─────────────────────────────────────────────────

def _web_candidates() -> list[Path]:
    env = os.environ.get("SR_WEB_REPO")
    if env:
        return [Path(env)]
    out = [HERE.parent / "dg-research"]
    try:
        common = subprocess.run(
            ["git", "-C", str(HERE), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        if common.returncode == 0 and common.stdout.strip():
            out.append(Path(common.stdout.strip()).parent.parent / "dg-research")
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def _web() -> Path:
    asked = bool(os.environ.get("SR_WEB_REPO"))
    tried = _web_candidates()
    for base in tried:
        if (base / GATES).is_file():
            web = base
            break
    else:
        assert not asked, (f"SR_WEB_REPO={tried[0]} holds no {GATES}, so the "
                           "post-publish rehearsal was aimed at nothing")
        pytest.skip("no web checkout in " + ", ".join(map(str, tried))
                    + " - the post-publish step was NOT rehearsed; set SR_WEB_REPO")
    node = shutil.which("node")
    vitest = web / "node_modules" / "vitest" / "vitest.mjs"
    missing = [what for what, ok in (("node on PATH", node),
                                     (str(vitest), vitest.is_file())) if not ok]
    if missing:
        assert not asked, f"SR_WEB_REPO is set but there is no {' and no '.join(missing)}"
        pytest.skip(f"no {' and no '.join(missing)} - the post-publish step was NOT rehearsed")
    return web


# ── the throwaway copies ──────────────────────────────────────────────────────

def _files(repo: Path, *paths: str) -> list[str]:
    """Tracked and untracked-but-not-ignored files: the working tree as it is, so
    an uncommitted change is rehearsed too."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard", "-z", "--", *paths],
        capture_output=True, check=True, timeout=60).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _copy(repo: Path, dst: Path, *paths: str) -> Path:
    for rel in _files(repo, *paths):
        src = repo / rel
        if not src.is_file():          # deleted in the working tree
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / rel)
    return dst


def _link(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # A junction needs no privilege on Windows, where a symlink can.
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)


@pytest.fixture
def copies(tmp_path, monkeypatch):
    """(backend copy, web copy) side by side, the layout the tool probes for.
    ⛔ `SR_WEB_ROOT` is cleared: set, it would aim the tool at a real checkout."""
    monkeypatch.delenv("SR_WEB_ROOT", raising=False)
    web_src = _web()
    be = _copy(HERE, tmp_path / "dg-research-backend", "tools", "agent")
    web = _copy(web_src, tmp_path / "dg-research")
    link = web / "node_modules"
    _link((web_src / "node_modules").resolve(), link)
    try:
        yield be, web
    finally:
        # The link goes first, so no cleanup can ever walk into the real modules.
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()


def _snapshot(web: Path) -> dict[str, str]:
    out = {}
    for p in web.rglob("*"):
        rel = p.relative_to(web).as_posix()
        if rel == "node_modules" or rel.startswith("node_modules/") or not p.is_file():
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}


# ── PyPI, faked ───────────────────────────────────────────────────────────────

class _Index:
    """A local stand-in for https://pypi.org/simple/superresearch-agent/ listing
    one wheel per version given - the page the tool actually parses."""

    def __init__(self, *versions: str):
        body = "".join(f'<a href="#">superresearch_agent-{v}-py3-none-any.whl</a><br>\n'
                       for v in versions).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/simple/superresearch-agent/"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def _tool(be: Path):
    """The tool loaded FROM THE COPY, so its `_REPO_ROOT` - and therefore every
    path it writes - is the copy's."""
    spec = importlib.util.spec_from_file_location("bump_version_rehearsal", be / "tools" / "bump_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._REPO_ROOT == be.resolve()
    return mod


def _release_version(tool, be: Path) -> str:
    """The version to rehearse publishing: what the backend builds - or, between a
    real publish and the next bump, when there is no transition left to rehearse,
    the next patch, bumped in the COPY so the rehearsal is always of a real one."""
    (building,) = {v for vs in tool.read_versions(be).values() for v in vs}
    if tool._published_version(be) != building:
        return building
    head, _, last = building.rpartition(".")
    nxt = f"{head}.{int(last) + 1}"
    tool.bump(nxt, be)
    return nxt


def _post_publish(tool, index: _Index, version: str, monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.setattr(tool, "_PYPI_SIMPLE", index.url)
    rc = tool.main(["--post-publish", version])
    return rc, capsys.readouterr().out


def _vitest(web: Path, files: list[str]) -> tuple[str, subprocess.CompletedProcess]:
    proc = subprocess.run(
        [shutil.which("node"), str(web / "node_modules" / "vitest" / "vitest.mjs"),
         "run", *files],
        cwd=str(web), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900, env={**os.environ, "FORCE_COLOR": "0"})
    out = re.sub(r"\x1b\[[0-9;]*m", "", (proc.stdout or "") + (proc.stderr or ""))
    return out, proc


# ── the rehearsal ─────────────────────────────────────────────────────────────

def test_before_the_wheel_is_on_PyPI_the_step_refuses_and_changes_nothing(copies, monkeypatch, capsys):
    """⛔ The refusing direction. Everything downstream keys off the published
    version, so a step that moved it on a typed-in belief would ship a hosted skill
    nobody can install."""
    be, web = copies
    tool = _tool(be)
    version = _release_version(tool, be)
    before = _snapshot(web)
    with _Index("0.1.31", "0.1.32") as index:
        rc, out = _post_publish(tool, index, version, monkeypatch, capsys)
    assert rc == 2, out
    assert f"{version} is NOT on PyPI" in out
    assert "Nothing was changed" in out
    assert _changed(before, _snapshot(web)) == set()


def test_after_the_publish_the_step_leaves_the_web_suite_green(copies, monkeypatch, capsys):
    """⛔⛔ THE WHOLE STEP, then what it could break. Would this pass before the
    fix? No: against the web tree of 2026-09-23 the tool finished happily and the
    selected tests read 3 failed."""
    be, web = copies
    tool = _tool(be)
    version = _release_version(tool, be)
    before = _snapshot(web)
    with _Index("0.1.32", version) as index:
        rc, out = _post_publish(tool, index, version, monkeypatch, capsys)
    assert rc == 0, out

    # ── what it wrote ────────────────────────────────────────────────────────
    gates = (web / GATES).read_text(encoding="utf-8")
    assert f'export const AGENT_WHEEL_PUBLISHED = "{version}";' in gates
    assert "export const AGENT_LOG_STEP_PUBLISHED = true;" in gates
    ok, lockstep = tool.check_lockstep(be)
    assert ok, "\n".join(lockstep)
    assert re.search(rf"^\s*hosted twin\s+{re.escape(version)}$", "\n".join(lockstep), re.M), lockstep

    # ── and that the commit it prints carries all of it ─────────────────────
    changed = _changed(before, _snapshot(web))
    assert GATES in changed and "scripts/agent-skill-sync.json" in changed, changed
    add = [ln for ln in out.splitlines() if re.search(r"git -C .* add ", ln)]
    assert len(add) == 1, out
    assert f'git -C "{web}" add ' in add[0], "the command names the checkout it changed"
    specs = add[0].split(" add ", 1)[1].split()
    assert specs == list(tool.POST_PUBLISH_WEB_PATHS)
    unnamed = sorted(p for p in changed
                     if not any(p == s or p.startswith(s.rstrip("/") + "/") for s in specs))
    assert unnamed == [], f"changed by the step and missing from its commit: {unnamed}"

    # ── what it could break ──────────────────────────────────────────────────
    selected = sorted(
        p.relative_to(web).as_posix() for p in (web / "tests" / "unit").glob("*.test.ts")
        if any(n in p.read_text(encoding="utf-8") for n in RELEASE_STATE_NEEDLES))
    # ⛔ a selection that collapsed would pass on nothing
    assert len(selected) >= 8, selected
    for must in ("tests/unit/hostedSkillTwin.test.ts",
                 "tests/unit/documentImagesContract.test.ts",
                 "tests/unit/sendLogsAgentLogLine.test.ts"):
        assert must in selected, (must, selected)
    files = [*selected, RATCHET]
    report, proc = _vitest(web, files)
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE.
    tests_line = re.search(r"^\s*Tests\s+(.*)$", report, re.M)
    files_line = re.search(r"^\s*Test Files\s+(.*)$", report, re.M)
    assert tests_line and files_line, report[-4000:]
    assert "failed" not in tests_line.group(1) and "failed" not in files_line.group(1), (
        "the post-publish step leaves these red:\n"
        + "\n".join(ln for ln in report.splitlines() if re.match(r"\s*(FAIL|×)", ln))[:4000])
    passed = re.fullmatch(r"(\d+) passed \((\d+)\)", tests_line.group(1).strip())
    assert passed and passed.group(1) == passed.group(2), tests_line.group(0)
    assert int(passed.group(1)) >= 200, tests_line.group(0)
    assert files_line.group(1).strip() == f"{len(files)} passed ({len(files)})", files_line.group(0)
    assert proc.returncode == 0, report[-4000:]
