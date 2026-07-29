"""DGOPS-9507: the self-update's version floor, and the three calls that must NOT
carry it.

The decision recorded on that ticket is a monotonicity floor — a self-update may
never move the host onto a build older than the one it is running — applied by
version only, never by index URL, so an internal mirror keeps working.

Which calls take the floor is not uniform, and the asymmetry is the whole point of
this file. Measured against pipx 1.16.3:

  * `pipx upgrade` must NOT take it. pipx silently DISCARDS a constraint passed to
    `upgrade`: `pipx upgrade 'pkg>=0.1.31'` exits 0 reporting "already at latest
    version 0.1.30". A floor there reads as protection and provides none. It needs
    none either — `pip install --upgrade` against an index whose newest release is
    older than the installed one reports "Requirement already satisfied" and leaves
    the newer build in place.
  * `pipx install --force` and `pipx run` MUST take it. Both are fresh resolves
    (--force recreates the venv, run builds an ephemeral one), and a fresh install
    from that same older-only index gets the OLDER version — there is no prior
    version for it to be protected by.
  * `pipx install <backend>` must not take it: a first install of a different
    package onto a host that has none has no prior version to walk backwards from.

The floor also has to be applied CONSISTENTLY across the pre-flight and the waiter.
`agent_resolvable()` runs while the current bridge is still alive; the waiter runs
after it has been shut down. If the pre-flight resolved unfloored it would pass,
/agent-install would shut the bridge down, and every floored attempt in the waiter
would then fail — converting a clean refusal into a host with no bridge at all.
`test_the_preflight_and_the_waiter_resolve_the_same_spec` is that invariant.

The waiter tests EXECUTE `_RECONNECT_WAITER` against a fake pipx and read back the
argv it actually built. Asserting on the source text instead would pass just as
happily against a spec that never reaches a subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from facade import selfupdate

FLOOR_VERSION = "9.9.9"
EXPECTED_SPEC = f"superresearch-agent>={FLOOR_VERSION}"


@pytest.fixture
def floored(monkeypatch):
    """Pin the running version. `__version__` is read from installed package
    metadata, so on a dev checkout it reflects whatever distribution happens to be
    importable rather than pyproject's number — a literal here would assert about
    the machine instead of the code."""
    monkeypatch.setattr(selfupdate, "__version__", FLOOR_VERSION)
    return EXPECTED_SPEC


# ── the floor itself ──────────────────────────────────────────────────────────

def test_the_floor_is_the_running_version(floored):
    assert selfupdate._agent_floor_spec() == EXPECTED_SPEC


def test_the_floor_is_ge_not_eq(floored):
    """`==` would refuse to reinstall the version already present, and repairing a
    half-broken venv by re-running the update is a supported flow."""
    spec = selfupdate._agent_floor_spec()
    assert ">=" in spec
    assert "==" not in spec


def test_the_floor_never_pins_an_index(floored):
    """The index pin was DECLINED on DGOPS-9507 — it breaks mirror hosts, which are
    a supported configuration. The floor is what replaced it, so it must not smuggle
    one back in."""
    assert "--index-url" not in selfupdate._agent_floor_spec()
    assert "index" not in selfupdate._agent_floor_spec()


# ── the pre-flight ────────────────────────────────────────────────────────────

def _capture_preflight(monkeypatch, floored_spec: str) -> list:
    seen: list = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    assert selfupdate.agent_resolvable() is True
    assert len(seen) == 1
    return seen[0]


def test_the_preflight_resolves_against_the_floor(floored, monkeypatch):
    argv = _capture_preflight(monkeypatch, floored)
    assert "--spec" in argv, f"pre-flight resolves unfloored: {argv!r}"
    assert argv[argv.index("--spec") + 1] == EXPECTED_SPEC
    assert "--no-cache" in argv, (
        "the pre-flight lost --no-cache, so a cached run-venv can false-pass on the "
        f"stale build the reconnect will not actually get: {argv!r}"
    )


def test_the_preflight_positional_is_the_app_not_the_spec(floored, monkeypatch):
    """`pipx run`'s positional is the APP name — that is how it picks which console
    script to execute. Passing the requirement string there relies on pipx parsing
    the package name back out of it, which is undocumented and version-dependent."""
    argv = _capture_preflight(monkeypatch, floored)
    app = argv[argv.index("--spec") + 2]
    assert app == selfupdate.AGENT_PKG, f"positional is not the bare app name: {argv!r}"
    assert ">=" not in app


def test_the_preflight_still_fails_closed_on_a_nonzero_resolve(floored, monkeypatch):
    """An unsatisfiable floor must make /agent-install DECLINE, which is the whole
    reason fail-closed is safe: the refusal lands while the old bridge is alive."""
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no match"))
    assert selfupdate.agent_resolvable() is False


# ── pre-flight / waiter agreement ─────────────────────────────────────────────

def test_the_preflight_and_the_waiter_resolve_the_same_spec(floored, tmp_path, monkeypatch):
    """The strand-the-host invariant. These two resolve at different moments in the
    update — one before the shutdown, one after — so a disagreement is only
    observable once the bridge is already gone."""
    preflight_argv = _capture_preflight(monkeypatch, floored)
    preflight_spec = preflight_argv[preflight_argv.index("--spec") + 1]

    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix", lambda: [])
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: False)
    spawned: list = []

    def fake_popen(cmd, **kw):
        spawned.append(list(cmd))
        return type("P", (), {"poll": lambda self: None})()

    monkeypatch.setattr(selfupdate.subprocess, "Popen", fake_popen)
    assert selfupdate.spawn_detached_reconnect() is True

    cfg = json.loads(spawned[0][-1])
    assert cfg["spec"] == preflight_spec == EXPECTED_SPEC
    assert cfg["pkg"] == selfupdate.AGENT_PKG, (
        "the waiter still needs the BARE package name as the venv/app identity; "
        "the spec is carried separately"
    )


# ── the waiter, executed for real ─────────────────────────────────────────────

_FAKE_PIPX = r'''
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_PIPX_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv) + "\n")
if argv[:1] == ["environment"]:
    sys.stdout.write(os.environ.get("FAKE_PIPX_VENVS", ""))
    sys.exit(0)
sub = argv[0] if argv else ""
sys.exit(int(os.environ.get("FAKE_RC_" + sub.upper(), "0")))
'''


def _dead_pid() -> int:
    """A pid guaranteed to be reaped, so the waiter's alive() loop exits at once
    instead of burning its full ~60s ceiling."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _run_waiter(tmp_path, *, rcs: dict, make_entry: bool) -> list:
    """Execute `_RECONNECT_WAITER` against a fake pipx; return the argv it built.

    `make_entry` controls whether the persistent console script exists, which is
    what decides between the entry path and the ephemeral `pipx run` fallback.
    """
    fake = tmp_path / "fakepipx.py"
    fake.write_text(_FAKE_PIPX, encoding="utf-8")
    log = tmp_path / "pipx-argv.jsonl"
    venvs = tmp_path / "venvs"

    pkg = selfupdate.AGENT_PKG
    rel = ("Scripts", pkg + ".exe") if sys.platform == "win32" else ("bin", pkg)
    entry = venvs.joinpath(pkg, *rel)
    if make_entry:
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("", encoding="utf-8")
        entry.chmod(0o755)

    cfg = json.dumps({
        "pipx": [sys.executable, str(fake)],
        "pkg": pkg,
        "spec": EXPECTED_SPEC,
        "connect_args": ["connect", "--yes", "--no-login"],
        "restart_args": [],
        "log": str(tmp_path / "self-update.log"),
    })
    env = {**os.environ, "FAKE_PIPX_LOG": str(log), "FAKE_PIPX_VENVS": str(venvs)}
    for sub, rc in rcs.items():
        env["FAKE_RC_" + sub.upper()] = str(rc)

    # The real `entry` is an empty file, so executing it fails on some platforms —
    # the waiter wraps nothing around that call, so tolerate a non-zero waiter exit
    # and assert on the pipx argv, which is what this file is about.
    subprocess.run([sys.executable, "-c", selfupdate._RECONNECT_WAITER,
                    str(_dead_pid()), cfg], env=env, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()] \
        if log.exists() else []


def test_the_waiter_never_floors_upgrade(tmp_path):
    """Passing the floor here would be silently discarded by pipx — protection that
    looks real in a diff and does nothing on the host."""
    calls = _run_waiter(tmp_path, rcs={"upgrade": 0}, make_entry=True)
    upgrades = [c for c in calls if c[:1] == ["upgrade"]]
    assert upgrades, f"the waiter never tried `pipx upgrade`: {calls!r}"
    for argv in upgrades:
        assert argv == ["upgrade", selfupdate.AGENT_PKG], (
            f"`pipx upgrade` carries a version constraint pipx will drop: {argv!r}"
        )


def test_the_waiter_floors_the_force_install(tmp_path):
    """--force RECREATES the venv, so it is a fresh resolve with no prior version to
    protect. This is the call the floor exists for."""
    calls = _run_waiter(tmp_path, rcs={"upgrade": 1, "install": 0}, make_entry=True)
    installs = [c for c in calls if c[:1] == ["install"]]
    assert installs, (
        f"`pipx upgrade` failed but the --force fallback never ran: {calls!r}"
    )
    assert installs[0] == ["install", "--force", EXPECTED_SPEC], (
        f"the --force install resolves unfloored: {installs[0]!r}"
    )


def test_the_waiter_ephemeral_fallback_carries_the_floor_in_spec(tmp_path):
    """The last-resort path fetches AND executes in one step, so there is no
    after-fetch gap to verify in — the floor at resolve time is the only guard
    available here."""
    calls = _run_waiter(tmp_path, rcs={"upgrade": 1, "install": 1}, make_entry=False)
    runs = [c for c in calls if c[:1] == ["run"]]
    assert runs, f"both upgrades failed but the ephemeral fallback never ran: {calls!r}"
    argv = runs[0]
    assert "--spec" in argv, f"the ephemeral fallback resolves unfloored: {argv!r}"
    assert argv[argv.index("--spec") + 1] == EXPECTED_SPEC
    assert argv[argv.index("--spec") + 2] == selfupdate.AGENT_PKG, (
        f"the positional must stay the APP name, not the requirement: {argv!r}"
    )
    assert "--no-cache" in argv, (
        f"--no-cache is load-bearing here — a ~14-day cached venv re-runs the STALE "
        f"build the floor was meant to rule out: {argv!r}"
    )
    assert "connect" in argv


def test_the_waiter_skips_the_fallback_once_the_persistent_entry_resolves(tmp_path):
    """Guard against the guard: if `make_entry=True` did not actually change the
    waiter's branch, the fallback test above would be asserting on the only path
    the waiter ever takes and would pass for the wrong reason."""
    calls = _run_waiter(tmp_path, rcs={"upgrade": 0}, make_entry=True)
    assert not [c for c in calls if c[:1] == ["run"]], (
        f"the persistent entry resolved yet the ephemeral fallback still ran: {calls!r}"
    )


# ── the backend install stays unfloored ───────────────────────────────────────

def test_the_backend_install_is_deliberately_unfloored(floored, monkeypatch):
    """A first install onto a host with no backend has no prior version to be walked
    backwards from, so the only floor available would be a literal minimum hardcoded
    in selfupdate.py that goes stale every backend release. Asserted so that adding
    one later is a deliberate decision rather than a tidy-up."""
    seen: list = []
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_spawn_detached",
                        lambda cmd, log_name, **kw: seen.append(list(cmd)) or True)
    assert selfupdate.spawn_detached_backend_install() is True
    assert seen[0] == ["pipx", "install", selfupdate.BACKEND_PKG], (
        f"the backend install grew a constraint: {seen[0]!r}"
    )


def test_the_backend_package_is_not_the_agent_package():
    """The two floors would be unrelated numbers even if we wanted one — the agent's
    __version__ says nothing about which backend build is current."""
    assert selfupdate.BACKEND_PKG != selfupdate.AGENT_PKG


# ── the waiter is still syntactically valid after the edits ───────────────────

def test_the_waiter_still_compiles():
    """`_RECONNECT_WAITER` ships as a `-c` string, so a typo introduced while adding
    the floor would only surface on a real host mid-update."""
    compile(selfupdate._RECONNECT_WAITER, "<reconnect-waiter>", "exec")


def test_the_waiter_tolerates_a_cfg_with_no_spec():
    """Forward-compat: the waiter source and the cfg writer ship together, but the
    fallback is cheap and makes the intent explicit rather than incidental."""
    assert 'cfg.get("spec") or pkg' in selfupdate._RECONNECT_WAITER


def test_the_floor_is_resolved_before_the_upgrade_not_after(floored, tmp_path, monkeypatch):
    """The floor has to be captured from the version currently RUNNING. Reading it
    inside the waiter after the upgrade would compare the new build against itself,
    which is not a floor at all — so it is resolved by the spawning process and
    passed through the cfg."""
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix", lambda: [])
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: False)
    spawned: list = []
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: (spawned.append(list(cmd)),
                                           type("P", (), {"poll": lambda self: None})())[1])
    assert selfupdate.spawn_detached_reconnect() is True
    assert json.loads(spawned[0][-1])["spec"] == EXPECTED_SPEC
    assert "__version__" not in selfupdate._RECONNECT_WAITER, (
        "the waiter must not derive the floor itself — it is stdlib-only and cannot "
        "import from the package it is replacing"
    )
