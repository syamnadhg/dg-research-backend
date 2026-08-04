"""DGOPS-9507: the self-update's version floor, and the three calls that must NOT
carry it.

The decision recorded on that ticket is a monotonicity floor — a self-update may
never move the host onto a build older than the one it is running — applied by
version only, never by index URL, so an internal mirror keeps working.

Which calls take the floor is not uniform, and the asymmetry is the whole point of
this file. Measured against pipx 1.16.3:

  * The agent's replacement `pipx install` and the ephemeral `pipx run` MUST take
    it. Both are fresh resolves — the update now REMOVES the old venv before
    installing, and run builds a throwaway one — so neither has a prior version to
    be protected by, and each would happily install whatever an older-only index
    calls latest. (`pipx upgrade` used to be the first attempt and deliberately
    carried no floor, because pipx silently DISCARDS a constraint passed to it. It
    is gone: an in-place upgrade layers over the old venv.)
  * The ROLLBACK install takes `==<prev>`, not the floor. It is a return to a known
    build, and `>=prev` would re-resolve straight back to the release that just
    failed.
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
    # The rollback target. Resolved HERE for the same reason the spec is — the
    # waiter is stdlib-only and cannot import __version__ from the package it is
    # about to delete, and reading it afterwards would compare the new build
    # against itself. Without it a failed clean install has nothing to restore,
    # which is the whole safety argument for removing the old venv first.
    assert cfg["prev"] == FLOOR_VERSION, (
        f"the waiter cannot roll back — no previous version was carried: {cfg!r}"
    )


# ── the waiter, executed for real ─────────────────────────────────────────────

# The fake MODELS pipx; it does not merely log it. That matters because the defect
# this file now has to catch is one only a modelled pipx can express: a plain
# `pipx install` over a venv that still exists prints "already seems to be
# installed" and EXITS 0. A double that returns a scripted code and touches no
# state cannot tell that apart from a real install — which is how the old "a failed
# uninstall is followed by a forced install" test passed while asserting a recovery
# real pipx could never reach.
#
# Behaviour taken from pipx 1.16.5, measured (scratchpad review notes):
#   environment --value X   -> the venvs root
#   install <req>           -> venv exists: rc 0 and NOTHING changes; else install
#   install --force <req>   -> (re)install in place, restoring a missing script
#   uninstall <pkg>         -> remove the venv tree
#   list --json             -> the version actually on disk
#   run …                   -> exit code only
# `FAKE_PIPX_LIES` names subcommands that exit 0 and change nothing — the shape of
# every "pipx said it worked" defect in this file, expressed once.
#
# `FAKE_RC_<SUB>` still forces a failure, and a forced failure leaves the disk
# alone — which is also what real pipx does, since it refuses to remove a venv it
# did not create in the same session. It may be a COMMA-SEPARATED sequence consumed
# one entry per call of that subcommand (the last entry repeats), because a run can
# issue several `install` calls with opposite intent — the replacement, the retry
# after a removal, and the rollback — and a single rc for all three cannot tell
# "the replacement worked" from "the rollback rescued us".
_FAKE_PIPX = r'''
import json, os, shutil, sys
from pathlib import Path
argv = sys.argv[1:]
log = os.environ["FAKE_PIPX_LOG"]
venvs = Path(os.environ["FAKE_PIPX_VENVS"])
pkg = os.environ["FAKE_PIPX_PKG"]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv) + "\n")

venv = venvs / pkg
rel = ("Scripts", pkg + ".exe") if sys.platform == "win32" else ("bin", pkg)
entry = venv.joinpath(*rel)
marker = venv / "INSTALLED_VERSION"

def satisfies(latest, req):
    """Whether this fake index's `latest` satisfies a `>=` requirement."""
    if ">=" not in req:
        return True
    floor = req.split(">=", 1)[1].strip()
    def t(v):
        out = []
        for chunk in (v or "").split("."):
            d = ""
            for ch in chunk:
                if not ch.isdigit():
                    break
                d += ch
            out.append(int(d or 0))
        return tuple(out)
    n = max(len(t(latest)), len(t(floor)))
    return t(latest) + (0,) * (n - len(t(latest))) >= t(floor) + (0,) * (n - len(t(floor)))
def wanted(req):
    """What the index would resolve `req` to. `==X` is exact; anything else takes
    whatever this fake index calls latest."""
    if "==" in req:
        return req.split("==", 1)[1].strip()
    return os.environ.get("FAKE_PIPX_LATEST", "")

def place(req):
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("", encoding="utf-8")
    entry.chmod(0o755)
    marker.write_text(wanted(req), encoding="utf-8")

if argv[:1] == ["environment"]:
    sys.stdout.write(str(venvs))
    sys.exit(0)
sub = (argv[0] if argv else "").upper()
seen = 0
with open(log, encoding="utf-8") as fh:
    for line in fh:
        prior = json.loads(line)
        if prior[:1] and prior[0].upper() == sub:
            seen += 1
seen -= 1  # our own line is already in the log
codes = [c for c in os.environ.get("FAKE_RC_" + sub, "0").split(",") if c != ""]
rc = int(codes[min(seen, len(codes) - 1)]) if codes else 0
# A resolver REFUSES a requirement it cannot satisfy. Without this the double
# would install a build below the floor and exit 0 — a resolve real pipx cannot
# perform, so any test built on it would be testing the double. Skipped when the
# index is deliberately modelled as broken.
if rc == 0 and sub in ("INSTALL", "RUN") and not os.environ.get("FAKE_PIPX_DOWNGRADES"):
    if not satisfies(wanted(argv[-1]), argv[-1]):
        sys.stderr.write("ERROR: No matching distribution found\n")
        sys.exit(1)
lies = os.environ.get("FAKE_PIPX_LIES", "").upper().split(",")
if rc == 0 and sub not in lies:
    if sub == "INSTALL":
        if "--force" in argv or not venv.is_dir():
            place(argv[-1])
        # else: the real no-op — "already seems to be installed", exit 0.
    elif sub == "UNINSTALL":
        shutil.rmtree(venv, ignore_errors=True)
if sub == "LIST":
    ver = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    body = {"venvs": {pkg: {"metadata": {"main_package": {"package_version": ver}}}}} \
        if ver else {"venvs": {}}
    sys.stdout.write(json.dumps(body))
sys.exit(rc)
'''


def _dead_pid() -> int:
    """A pid guaranteed to be reaped, so the waiter's alive() loop exits at once
    instead of burning its full ~60s ceiling."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _venv_paths(tmp_path):
    venvs = tmp_path / "venvs"
    pkg = selfupdate.AGENT_PKG
    rel = ("Scripts", pkg + ".exe") if sys.platform == "win32" else ("bin", pkg)
    return venvs, venvs.joinpath(pkg, *rel), venvs / pkg / "INSTALLED_VERSION"


def _run_waiter(tmp_path, *, rcs: dict, make_entry: bool = False, prev: str = "1.2.3",
                latest: str = FLOOR_VERSION, installed: str | None = None,
                venv_only: bool = False, lies: str = "",
                downgrades: bool = False) -> list:
    """Execute `_RECONNECT_WAITER` against the modelled pipx; return its argv log.

    `make_entry` seeds a durable install that already exists — the console script
    plus the version marker `pipx list` reads back. `installed` overrides which
    version that pre-existing install is (default: `prev`, i.e. the build we are
    running). `venv_only` seeds the venv DIRECTORY without the console script,
    which is the half-broken state a part-way uninstall leaves behind.

    `latest` is what this fake index resolves the floored spec to. Setting it
    BELOW the floor models an index that answers with a stale build — the case an
    exit code cannot see and the post-condition can.

    `rcs` maps a pipx subcommand to the exit code the fake should return, so a
    test can fail exactly one leg.
    """
    fake = tmp_path / "fakepipx.py"
    fake.write_text(_FAKE_PIPX, encoding="utf-8")
    log = tmp_path / "pipx-argv.jsonl"
    venvs, entry, marker = _venv_paths(tmp_path)
    pkg = selfupdate.AGENT_PKG

    if make_entry or venv_only:
        entry.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(installed or prev, encoding="utf-8")
    if make_entry:
        entry.write_text("", encoding="utf-8")
        entry.chmod(0o755)

    cfg = json.dumps({
        "pipx": [sys.executable, str(fake)],
        "pkg": pkg,
        "spec": EXPECTED_SPEC,
        "prev": prev,
        "connect_args": ["connect", "--yes", "--no-login"],
        "restart_args": [],
        "log": str(tmp_path / "self-update.log"),
    })
    env = {**os.environ, "FAKE_PIPX_LOG": str(log), "FAKE_PIPX_VENVS": str(venvs),
           "FAKE_PIPX_PKG": pkg, "FAKE_PIPX_LATEST": latest, "FAKE_PIPX_LIES": lies,
           "FAKE_PIPX_DOWNGRADES": "1" if downgrades else ""}
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


def _connect_runs(calls: list) -> list:
    """The ephemeral CONNECT fallback only. The fetchability probe issues a `run`
    too (`… --version`), so a bare "was there a run?" no longer distinguishes
    them — and conflating the two would make the fallback assertions pass on the
    probe."""
    return [c for c in calls if c[:1] == ["run"] and "connect" in c]


def test_the_waiter_replaces_the_install_rather_than_layering(tmp_path):
    """"Update" has to mean the same thing as "install".

    An in-place `pipx upgrade` LAYERS the new distribution over the old venv, so a
    module the release deleted stays importable and a half-written venv stays
    half-written. `install --force` does not: it reinstalls the distribution and
    its dependencies, restoring even a missing console script."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True)
    subs = [c[0] for c in calls if c[:1] != ["environment"]]
    assert "upgrade" not in subs, f"an in-place upgrade layers over the old venv: {calls!r}"
    _, _, marker = _venv_paths(tmp_path)
    assert marker.read_text(encoding="utf-8").strip() == FLOOR_VERSION, (
        f"the version on disk never moved: {calls!r}"
    )


def test_the_healthy_path_never_deletes_the_install(tmp_path):
    """Uninstall-first is the destructive order and the ONLY one that can leave a
    host with no agent, so it must not be on the path every update takes.
    Measured: `install --force` reinstalls in place, and pipx refuses to remove a
    venv it did not create in the same session — so a failure there leaves the
    previous agent installed and working."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True)
    assert not [c for c in calls if c[:1] == ["uninstall"]], (
        f"a healthy update tore the install down first: {calls!r}"
    )


def test_the_waiter_floors_the_replacement_install(tmp_path):
    """A forced install is a FRESH resolve with no prior version to be protected
    by, so it is exactly the call the floor exists for (DGOPS-9507)."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True)
    installs = [c for c in calls if c[:1] == ["install"]]
    assert installs, f"the replacement install never ran: {calls!r}"
    assert installs[0] == ["install", "--force", EXPECTED_SPEC], (
        f"the replacement install is not the floored forced install: {installs[0]!r}"
    )


def test_an_install_that_exits_0_and_leaves_nothing_is_not_a_success(tmp_path):
    """The defect at the centre of this rewrite.

    pipx exits 0 for things that changed nothing — measured: a plain install over
    an existing venv prints "already seems to be installed" and returns 0, and it
    does so even when that venv has no console script left in it. So an exit code
    was never evidence that anything happened. Here the install claims success and
    leaves the half-broken venv exactly as it found it; the waiter must read the
    disk back, refuse to call it a success, and both attempt the recovery and put
    chat back up. Before the post-condition it logged "upgrade ok" and reconnected
    from an install that does not exist."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, venv_only=True,
                        prev="1.2.3", lies="install")
    assert [c for c in calls if c[:1] == ["uninstall"]], (
        f"it accepted an install that changed nothing: {calls!r}"
    )
    assert _connect_runs(calls), (
        f"nothing usable was installed, yet chat was never brought back: {calls!r}"
    )


def test_an_index_that_answers_below_the_floor_is_not_a_success(tmp_path):
    """The other half of the post-condition, and it is DEFENCE, not a live bug.

    A resolver honouring `>=<the version we are running>` cannot hand back
    anything older, so this needs an index modelled as broken — a mirror that
    ignores the constraint. That is the whole reason the check reads the disk
    instead of the exit code: a tool reporting success for something it did not do
    is not hypothetical here, it is measured behaviour of the adjacent form of the
    same command. `downgrades=True` says out loud that the scenario needs a pipx
    misbehaving, rather than hiding it in a double that quietly ignores its
    arguments."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True,
                        prev="1.2.3", latest="1.0.0", downgrades=True)
    assert [c for c in calls if c[:1] == ["list"]], (
        f"nothing ever read back which version landed: {calls!r}"
    )
    assert [c for c in calls if c[:1] == ["uninstall"]], (
        f"it accepted an install that moved the host backwards: {calls!r}"
    )


def test_reinstalling_the_same_version_is_still_a_success(tmp_path):
    """Guard against the guard: the floor is `>=`, deliberately — repairing a
    half-broken venv means installing the version already recorded, and demanding
    a strictly higher number would make every repair report as a failure.

    Both numbers are the FLOOR here, which is what production looks like: the
    spec is `pkg>=<the version we are running>` and `prev` is that same version.
    The harness defaults them apart only so a rollback is identifiable in the
    argv log."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True,
                        prev=FLOOR_VERSION, latest=FLOOR_VERSION)
    assert not [c for c in calls if c[:1] == ["uninstall"]], (
        f"a legitimate same-version repair was treated as a failure: {calls!r}"
    )


def test_the_post_condition_does_not_claim_to_detect_a_stalled_upgrade(tmp_path):
    """State the LIMIT, so nobody builds on a guarantee that isn't there.

    The waiter is told `>=<the version we are running>` and never the target
    number — nobody knows it until the index is asked — so "the same version is
    still installed" and "a repair reinstalled the same version" are the same
    observation, and it must accept both. Detecting a stalled upgrade needs the
    version the app compared against, which is the backend's job (it holds the
    before/after pair) and is covered on that side."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True,
                        prev="1.2.3", lies="install")
    assert not [c for c in calls if c[:1] == ["uninstall"]], (
        f"the waiter invented a verdict it has no way to reach: {calls!r}"
    )


def test_a_half_broken_venv_is_repaired(tmp_path):
    """A venv whose console script is gone — an earlier uninstall that hit a
    locked file part-way — is still in pipx's way: a plain install no-ops on it
    and rc 0 comes back anyway. Deciding "is one installed" from the SCRIPT meant
    this host got no uninstall, no forced install and no rollback, and stayed
    wedged forever. The forced install repairs it outright."""
    _, entry, _ = _venv_paths(tmp_path)
    calls = _run_waiter(tmp_path, rcs={"install": 0}, venv_only=True)
    assert entry.exists(), f"the script-less venv was never repaired: {calls!r}"
    assert not _connect_runs(calls), (
        f"it fell back to an ephemeral run with a repaired install present: {calls!r}"
    )


def test_the_plain_install_is_only_issued_once_the_venv_is_gone(tmp_path):
    """A plain `pipx install` over a venv that still exists is a no-op that
    reports success, so it is only ever meaningful after a REMOVAL succeeded.
    Here the uninstall fails, and the plain form must not be reached — reaching it
    would produce exactly the false "upgrade ok" this file exists to prevent."""
    calls = _run_waiter(tmp_path, rcs={"install": 1, "uninstall": 1}, make_entry=True)
    assert not [c for c in calls if c[:1] == ["install"] and "--force" not in c], (
        f"issued a plain install over a venv that is still there: {calls!r}"
    )


def test_the_destructive_order_is_gated_on_the_replacement_being_fetchable(tmp_path):
    """Deleting the working install and then discovering the index is unreachable
    is the one failure with no way back — the rollback needs the same network the
    install just failed on. So the removal is not attempted until a real fetch of
    the replacement has succeeded."""
    calls = _run_waiter(tmp_path, rcs={"install": 1, "run": 1}, make_entry=True)
    assert not [c for c in calls if c[:1] == ["uninstall"]], (
        f"tore down the install with no way to replace it: {calls!r}"
    )
    _, entry, _ = _venv_paths(tmp_path)
    assert entry.exists(), "the previous agent was destroyed by a failed update"


def test_a_first_install_removes_nothing(tmp_path):
    """With no durable venv there is nothing to remove, and issuing `uninstall`
    anyway would make every fresh install log a spurious failure."""
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=False)
    assert not [c for c in calls if c[:1] == ["uninstall"]], (
        f"uninstalled a package that was never installed: {calls!r}"
    )


def test_a_failed_replacement_restores_the_version_we_were_running(tmp_path):
    """The reason the destructive branch is survivable. Without this the host is
    left with NO agent once a removal succeeds and the install after it does not.

    Pinned with `==`: this is a rollback to a known build, not an update, and
    `>=prev` would re-resolve to the very release that just failed to install."""
    calls = _run_waiter(tmp_path, rcs={"install": "1,1,0"}, make_entry=True, prev="1.2.3")
    installs = [c for c in calls if c[:1] == ["install"]]
    assert installs[-1] == ["install", "--force", f"{selfupdate.AGENT_PKG}==1.2.3"], (
        f"the restore is not pinned to the version we were running: {installs!r}"
    )
    _, entry, marker = _venv_paths(tmp_path)
    assert entry.exists() and marker.read_text(encoding="utf-8").strip() == "1.2.3", (
        f"the rollback did not actually put the old build back: {calls!r}"
    )


def test_a_rollback_only_ever_targets_the_version_we_were_running(tmp_path):
    """`prev` is the build this host is executing right now, so restoring it can
    never introduce something it has not run. With no `prev` in the cfg — which is
    what an older build writes — there is nothing honest to fall back to, and
    guessing would install a version nobody asked for."""
    calls = _run_waiter(tmp_path, rcs={"install": 1}, make_entry=False, prev="")
    installs = [c for c in calls if c[:1] == ["install"]]
    assert len(installs) == 1, f"restored a version it was never told about: {calls!r}"


def test_the_waiter_ephemeral_fallback_carries_the_floor_in_spec(tmp_path):
    """The last-resort path fetches AND executes in one step, so there is no
    after-fetch gap to verify in — the floor at resolve time is the only guard
    available here."""
    calls = _run_waiter(tmp_path, rcs={"install": 1}, make_entry=False)
    runs = _connect_runs(calls)
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
    calls = _run_waiter(tmp_path, rcs={"install": 0}, make_entry=True)
    assert not _connect_runs(calls), (
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


def test_a_restored_install_is_what_the_waiter_reconnects_from(tmp_path):
    """A rollback that worked leaves a perfectly good durable install on disk.

    Resolving the entry point only on SUCCESS threw that away and sent the waiter
    to the ephemeral fallback — which resolves the floored spec straight back to
    the release that just refused to install. If that release is the problem (a
    broken wheel, a yanked version), the fallback fails too and the host has no
    bridge, with a working install sitting right there. Reconnecting from the
    restored build is the entire point of restoring it.

    Only a pipx double that MODELS the venv can prove this: with one that merely
    logs argv, the seeded console script survives every scripted failure, so the
    entry resolves whether the rollback worked or not and the test cannot fail."""
    calls = _run_waiter(tmp_path, rcs={"install": "1,1,0"}, make_entry=True, prev="1.2.3")
    installs = [c for c in calls if c[:1] == ["install"]]
    assert len(installs) >= 2, f"the rollback never ran: {calls!r}"
    assert not _connect_runs(calls), (
        f"it fell back to an ephemeral run with a durable install available: {calls!r}"
    )


def test_a_rollback_that_failed_does_send_it_to_the_fallback(tmp_path):
    """Guard against the guard for the test above: if the modelled uninstall did
    not really delete the entry, that test would be asserting on a durable install
    nothing had touched."""
    calls = _run_waiter(tmp_path, rcs={"install": 1}, make_entry=True, prev="1.2.3")
    assert _connect_runs(calls), (
        f"nothing durable survived, yet chat was never brought back up: {calls!r}"
    )
