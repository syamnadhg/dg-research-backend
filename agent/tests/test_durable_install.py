"""The login pin must never point into pipx's evictable run cache.

`pipx run superresearch-agent connect` is the documented from-chat install, and it
executes out of a venv pipx throws away after ~14 days. Everything the pin bakes in
— the interpreter to exec AND the directory put on sys.path — came from whatever
copy happened to be running, so a pin written at that moment reports success, works
for a fortnight, and then resurrects an old bridge or (after the eviction) nothing
at all. The user sees "the agent starts on an old version" on a reboot weeks later,
with nothing on screen connecting it back to the install.

Three things have to hold, and each is a separate failure if it doesn't:
  1. the paths are RESOLVED to the durable install, not to wherever we run from;
  2. that includes the INTERPRETER — an evicted cache takes python with it, and a
     unit exec'ing a missing binary produces no bridge and no error anyone reads;
  3. when no durable install exists, pinning REFUSES rather than writing a launcher
     it already knows will rot, and the caller makes one.

The pipx probes are subprocess calls, so every test here drives them through a fake
`pipx environment` and asserts on real filesystem layouts. `_pipx_values` memoises
per process, so it is cleared between tests — otherwise the first test to run would
decide the answer for all of them.
"""
from __future__ import annotations

import sys

import pytest

from facade import autostart


@pytest.fixture(autouse=True)
def _clear_pipx_cache():
    autostart._pipx_values.clear()
    autostart._uv_cache.clear()
    yield
    autostart._pipx_values.clear()
    autostart._uv_cache.clear()


def _fake_pipx_env(monkeypatch, values: dict, *, uv_cache=None):
    """Answer `pipx environment --value NAME` from `values`; anything absent is a
    pipx that cannot answer (exit 1), which is the degraded path.

    `uv_cache` answers `uv cache dir` the same way. It is a separate parameter
    rather than another key in `values` because it is a separate TOOL: a
    uv-backed pipx runs out of uv's store and pipx's own probe cannot see it, and
    conflating the two here would let a test pass while the code asked only pipx.
    Absent (the default) means uv is not installed."""
    import subprocess

    def fake_run(argv, **kw):
        if argv[1:3] == ["cache", "dir"]:
            return subprocess.CompletedProcess(argv, 0, str(uv_cache), "") \
                if uv_cache is not None else subprocess.CompletedProcess(argv, 1, "", "")
        name = argv[-1]
        if name in values:
            return subprocess.CompletedProcess(argv, 0, str(values[name]), "")
        return subprocess.CompletedProcess(argv, 1, "", "unknown")

    monkeypatch.setattr(autostart, "_pipx_argv", lambda: ["pipx"])
    monkeypatch.setattr(autostart.shutil, "which",
                        lambda name: "/usr/bin/uv" if name == "uv" and uv_cache is not None
                        else None)
    monkeypatch.setattr(autostart.subprocess, "run", fake_run)


def _make_venv(root, pkg="superresearch-agent", *, with_facade=True, python=True,
               version=None):
    """A pipx-local-venvs tree containing one venv laid out the way pipx does.

    `version` writes the dist-info directory pipx's install leaves behind, which
    is where the installed version is read from — the same place, and in the same
    shape, as on a real host."""
    venv = root / pkg
    # site-packages exists either way — "half-built" means the DIRECTORY is there
    # and the package is not. Omitting the directory too would make the negative
    # test pass for the wrong reason: there would be nothing to look inside, so a
    # check that never looked would satisfy it.
    sp = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    if with_facade:
        (sp / "facade").mkdir()
    if version:
        (sp / f"{pkg.replace('-', '_')}-{version}.dist-info").mkdir()
    if python:
        (venv / "bin").mkdir(parents=True, exist_ok=True)
        for n in ("python3", "python"):
            (venv / "bin" / n).write_text("", encoding="utf-8")
        (venv / "Scripts").mkdir(parents=True, exist_ok=True)
        for n in ("python.exe", "pythonw.exe"):
            (venv / "Scripts" / n).write_text("", encoding="utf-8")
    return venv


# ── is_ephemeral ─────────────────────────────────────────────────────────────

def test_the_run_cache_is_ephemeral(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": cache})
    assert autostart.is_ephemeral(cache / "abcd1234" / "lib" / "site-packages") is True


def test_the_durable_venv_is_not_ephemeral(tmp_path, monkeypatch):
    """The distinction the whole fix rests on: pipx keeps the persistent installs
    and the throwaway run venvs in two different trees."""
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": tmp_path / "cache"})
    assert autostart.is_ephemeral(tmp_path / "venvs" / "superresearch-agent") is False


def test_a_source_checkout_is_never_treated_as_ephemeral(tmp_path, monkeypatch):
    """Pinning a dev checkout is legitimate, and a false positive here breaks the
    install flow outright — so the fallback heuristic must not fire on it."""
    _fake_pipx_env(monkeypatch, {})  # pipx cannot answer → heuristic path
    assert autostart.is_ephemeral(tmp_path / "src" / "agent") is False


def test_the_heuristic_needs_both_a_cache_and_a_tool_component(tmp_path, monkeypatch):
    """Without either tool to ask, "somewhere under a cache dir" alone is far too
    broad — it would swallow anything that vendors itself under ~/.cache."""
    _fake_pipx_env(monkeypatch, {})
    assert autostart.is_ephemeral(tmp_path / ".cache" / "black" / "envs" / "x") is False
    assert autostart.is_ephemeral(tmp_path / ".cache" / "pipx" / "abcd" / "x") is True
    assert autostart.is_ephemeral(tmp_path / ".cache" / "uv" / "archive-v0" / "x") is True


def test_uv_is_matched_as_a_whole_component_not_a_substring(tmp_path, monkeypatch):
    """The narrowness is the point. "pipx" is distinctive enough to match
    anywhere in a path segment; two letters are not, and treating them as a
    substring would call ~/.cache/uvicorn evictable and refuse to pin a host that
    happens to keep its checkout there."""
    _fake_pipx_env(monkeypatch, {})
    assert autostart.is_ephemeral(tmp_path / ".cache" / "uvicorn" / "x") is False


def test_uvs_own_cache_is_ephemeral(tmp_path, monkeypatch):
    """The configuration most machines are in, and the one the shipped check
    missed entirely. When uv is installed pipx uses it as the install backend by
    DEFAULT, and a uv-backed `pipx run` never touches PIPX_VENV_CACHEDIR — it
    executes out of ~/.cache/uv/archive-v0/<hash>/. Asking only pipx therefore
    answers "durable" and pins a path uv prunes."""
    uv_cache = tmp_path / "uvcache"
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": tmp_path / "pipxcache"},
                   uv_cache=uv_cache)
    running = uv_cache / "archive-v0" / "L1t8k3zb" / "lib" / "python3.13" / "site-packages"
    assert autostart.is_ephemeral(running) is True


def test_a_durable_pipx_tree_under_a_cache_dir_is_still_durable(tmp_path, monkeypatch):
    """A host with PIPX_HOME under ~/.cache keeps its PERSISTENT venvs at
    ~/.cache/pipx/venvs/<pkg>, which carries both a cache-ish and a pipx-ish
    component. Letting the name heuristic answer there would refuse to pin a
    perfectly good install and leave that user with no login pin at all."""
    home = tmp_path / ".cache" / "pipx"
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": home / "venvs",
                                 "PIPX_VENV_CACHEDIR": home / ".cache"})
    assert autostart.is_ephemeral(home / "venvs" / "superresearch-agent") is False
    assert autostart.is_ephemeral(home / ".cache" / "abcd1234") is True


def test_the_same_tree_is_durable_even_when_pipx_cannot_be_ASKED(tmp_path, monkeypatch):
    """The case above, minus the thing that rescued it.

    Asking pipx where its persistent tree lives fails on exactly the hosts where
    the name heuristic is in charge — so the escape it provides evaporates when it
    is most needed, and a real install answers "evictable". Reproduced on this
    machine before the fix: with pipx unreachable, a durable venv under a
    cache-rooted PIPX_HOME came back True, which makes `install()` refuse and
    leaves the user with no login pin at all. pipx's layout answers it offline —
    the persistent tree is always `<PIPX_HOME>/venvs/<pkg>` and the run cache is
    always `<PIPX_HOME>/.cache/<hash>`, which cannot overlap."""
    _fake_pipx_env(monkeypatch, {})  # neither probe can answer
    home = tmp_path / ".cache" / "pipx"
    assert autostart.is_ephemeral(home / "venvs" / "superresearch-agent") is False
    assert autostart.is_ephemeral(home / ".cache" / "abcd1234") is True


def test_the_offline_escape_wants_a_whole_component(tmp_path, monkeypatch):
    """A leftover cache tree that merely CONTAINS the word is not an install.
    Matching it as a substring would hand the pin to something evictable, which
    is the failure the whole module exists to prevent."""
    _fake_pipx_env(monkeypatch, {})
    home = tmp_path / ".cache" / "pipx"
    assert autostart.is_ephemeral(home / "venvs-old" / "abcd1234") is True
    assert autostart.is_ephemeral(home / "old-venvs" / "abcd1234") is True


# ── the durable install has to be CURRENT, not merely durable ────────────────
# Durability alone was the wrong bar. `pipx run superresearch-agent connect`
# fetches the newest agent and then asks where to pin it; if some older
# `pipx install` is still on the machine, redirecting to it downgrades the user
# with the very command documented as the way to get up to date — permanently,
# because login starts that copy from then on.

def _running(monkeypatch, version):
    import facade
    monkeypatch.setattr(facade, "__version__", version)


def test_an_older_durable_install_is_not_a_pin_target(tmp_path, monkeypatch):
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, version="0.1.28")
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    _running(monkeypatch, "0.1.31")
    assert autostart.durable_is_current() is False
    assert autostart.durable_agent_dir() is None, (
        "pinning here silently downgrades the user to 0.1.28"
    )
    assert autostart.durable_python() is None, (
        "the interpreter has to move with the package — one build's python with "
        "another build's site-packages injected ahead of it is untested ground"
    )


def test_a_current_durable_install_is_the_pin_target(tmp_path, monkeypatch):
    """Guard against the guard: refusing every durable install would make the
    bootstrap reinstall on every connect and never resolve."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, version="0.1.31")
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    _running(monkeypatch, "0.1.31")
    assert autostart.durable_is_current() is True
    assert autostart.durable_agent_dir() is not None
    assert autostart.durable_python() is not None


def test_a_newer_durable_install_is_still_a_pin_target(tmp_path, monkeypatch):
    """Deliberately running an older build (`pipx run …==0.1.20 connect`) must not
    drag the machine's login pin backwards to match."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, version="0.2.0")
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    _running(monkeypatch, "0.1.31")
    assert autostart.durable_is_current() is True


def test_the_version_compare_is_numeric_not_lexicographic(tmp_path, monkeypatch):
    """"0.1.9" > "0.1.31" as strings, and that ordering flips on the release the
    minor version reaches double digits — a bug that would arrive on its own."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, version="0.1.9")
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    _running(monkeypatch, "0.1.31")
    assert autostart.durable_is_current() is False


def test_the_same_release_written_two_ways_is_not_stale(tmp_path, monkeypatch):
    """`(0, 2)` sorts BELOW `(0, 2, 0)` as a tuple, so "0.2" and "0.2.0" — one
    release — would read as one being behind the other, and every connect would
    tear down a working install to "fix" it. Both sides get zero-padded first."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, version="0.2")
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    _running(monkeypatch, "0.2.0")
    assert autostart.durable_is_current() is True


def test_an_unreadable_version_is_treated_as_current(tmp_path, monkeypatch):
    """The safe direction. A wrong "stale" verdict tears down a working install on
    every single connect; a wrong "current" verdict is only today's behaviour."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs)  # facade present, no dist-info to read a version from
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    _running(monkeypatch, "0.1.31")
    assert autostart.durable_is_current() is True


def test_the_stale_install_makes_the_pin_target_undurable(tmp_path, monkeypatch):
    """The end-to-end consequence, and the reason the check lives in
    `durable_agent_dir` rather than in the bootstrap: with the redirect declined,
    `agent_dir()` falls back to the ephemeral copy we are running from, so
    `pin_target_is_durable()` goes false and the caller bootstraps a real install
    instead of pinning the old one. Gating inside `ensure_durable_install` could
    not have worked — it is only ever called once that test has already failed."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, version="0.1.28")
    cache = tmp_path / "cache"
    running = cache / "abcd1234" / "lib" / "python3.13" / "site-packages" / "facade" / "x.py"
    running.parent.mkdir(parents=True)
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs, "PIPX_VENV_CACHEDIR": cache})
    _running(monkeypatch, "0.1.31")
    monkeypatch.setattr(autostart, "__file__", str(running))
    assert autostart.pin_target_is_durable() is False


# ── resolving the durable install ────────────────────────────────────────────

def test_durable_agent_dir_finds_the_site_packages(tmp_path, monkeypatch):
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    got = autostart.durable_agent_dir()
    assert got is not None and (got / "facade").is_dir()


def test_a_half_built_venv_is_not_a_durable_home(tmp_path, monkeypatch):
    """Verified by the presence of `facade`, not by path shape. A venv that exists
    but has no package in it would otherwise be pinned and then fail to import at
    every login — an even quieter failure than the cache one."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs, with_facade=False)
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    assert autostart.durable_agent_dir() is None


def test_no_durable_install_resolves_to_nothing(tmp_path, monkeypatch):
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _fake_pipx_env(monkeypatch, {"PIPX_LOCAL_VENVS": venvs})
    assert autostart.durable_venv() is None
    assert autostart.durable_agent_dir() is None


# ── agent_dir redirection ────────────────────────────────────────────────────

def test_agent_dir_redirects_from_the_cache_to_the_durable_install(tmp_path, monkeypatch):
    cache, venvs = tmp_path / "cache", tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": cache, "PIPX_LOCAL_VENVS": venvs})
    running = cache / "abcd" / "lib" / "site-packages" / "facade" / "autostart.py"
    monkeypatch.setattr(autostart, "__file__", str(running))
    got = autostart.agent_dir()
    assert not autostart.is_ephemeral(got), f"agent_dir still resolves into the cache: {got}"
    assert (got / "facade").is_dir()


def test_agent_dir_leaves_a_non_cache_location_alone(tmp_path, monkeypatch):
    """The redirect is scoped to the cache case. Silently rewriting a source
    checkout's path to some unrelated installed copy would pin the WRONG code —
    the same class of bug, pointing the other way."""
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": tmp_path / "cache",
                                 "PIPX_LOCAL_VENVS": venvs})
    src = tmp_path / "src" / "agent" / "facade" / "autostart.py"
    src.parent.mkdir(parents=True)
    monkeypatch.setattr(autostart, "__file__", str(src))
    assert autostart.agent_dir() == src.parent.parent


def test_agent_dir_keeps_the_cache_path_when_there_is_nothing_better(tmp_path, monkeypatch):
    """Degrade, don't crash: returning None here would break every caller. The
    REFUSAL to pin is what protects the user, not a missing path."""
    cache = tmp_path / "cache"
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": cache, "PIPX_LOCAL_VENVS": venvs})
    running = cache / "abcd" / "lib" / "site-packages" / "facade" / "autostart.py"
    monkeypatch.setattr(autostart, "__file__", str(running))
    assert autostart.agent_dir() == running.parent.parent
    assert autostart.pin_target_is_durable() is False


# ── the interpreter ──────────────────────────────────────────────────────────

def test_the_service_interpreter_comes_from_the_durable_venv(tmp_path, monkeypatch):
    """An evicted cache takes python with it. A unit exec'ing a path that no longer
    exists produces no bridge and no message anyone will ever read, so resolving
    sys.path alone would fix half the bug and leave the louder half."""
    cache, venvs = tmp_path / "cache", tmp_path / "venvs"
    venvs.mkdir()
    venv = _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": cache, "PIPX_LOCAL_VENVS": venvs})
    monkeypatch.setattr(autostart.sys, "executable", str(cache / "abcd" / "bin" / "python"))
    monkeypatch.setattr(autostart, "is_windows", lambda: False)
    assert autostart.service_python() == str(venv / "bin" / "python3")


def test_the_windowless_interpreter_comes_from_the_durable_venv(tmp_path, monkeypatch):
    cache, venvs = tmp_path / "cache", tmp_path / "venvs"
    venvs.mkdir()
    venv = _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": cache, "PIPX_LOCAL_VENVS": venvs})
    monkeypatch.setattr(autostart.sys, "executable",
                        str(cache / "abcd" / "Scripts" / "python.exe"))
    monkeypatch.setattr(autostart, "is_windows", lambda: True)
    assert autostart.pythonw_exe() == str(venv / "Scripts" / "pythonw.exe")


def test_a_non_cache_interpreter_is_untouched(tmp_path, monkeypatch):
    venvs = tmp_path / "venvs"
    venvs.mkdir()
    _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": tmp_path / "cache",
                                 "PIPX_LOCAL_VENVS": venvs})
    monkeypatch.setattr(autostart.sys, "executable", str(tmp_path / "usr" / "bin" / "python3"))
    monkeypatch.setattr(autostart, "is_windows", lambda: False)
    assert autostart.service_python() == str(tmp_path / "usr" / "bin" / "python3")


def test_the_unit_and_the_plist_both_carry_the_resolved_interpreter(tmp_path, monkeypatch):
    """Two generators, one rule. The macOS plist was the reported case; the systemd
    unit reads sys.executable through the identical path and would rot the same way."""
    cache, venvs = tmp_path / "cache", tmp_path / "venvs"
    venvs.mkdir()
    venv = _make_venv(venvs)
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": cache, "PIPX_LOCAL_VENVS": venvs})
    monkeypatch.setattr(autostart.sys, "executable", str(cache / "abcd" / "bin" / "python"))
    monkeypatch.setattr(autostart, "is_windows", lambda: False)
    durable = str(venv / "bin" / "python3")
    for text in (autostart.launchd_plist_source(), autostart.systemd_unit_source()):
        assert durable in text, f"a generated unit still execs the cache interpreter:\n{text}"
        assert str(cache) not in text


# ── the refusal ──────────────────────────────────────────────────────────────

def test_install_refuses_to_pin_the_cache(tmp_path, monkeypatch):
    """The alternative is an install that reports success and fails weeks later on
    a reboot, which is precisely what was reported."""
    called: list = []
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(autostart, "_exec", lambda argv: called.append(argv) or (True, ""))
    monkeypatch.setattr(autostart, "write_launcher", lambda *a, **k: called.append("launcher"))
    ok, msg = autostart.install()
    assert ok is False
    assert not called, f"it pinned anyway: {called!r}"
    assert "pipx install" in msg, f"the refusal must name the fix, got: {msg!r}"


def test_install_proceeds_once_the_target_is_durable(monkeypatch):
    """Guard against the guard: if the refusal fired unconditionally, the test
    above would pass against code that can never pin at all."""
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: True)
    monkeypatch.setattr(autostart, "is_windows", lambda: False)
    monkeypatch.setattr(autostart, "is_linux", lambda: False)
    monkeypatch.setattr(autostart, "is_macos", lambda: True)
    monkeypatch.setattr(autostart, "_darwin_install", lambda: (True, "installed"))
    assert autostart.install() == (True, "installed")


# ── making the refusal actionable ────────────────────────────────────────────

def _pipx_recorder(monkeypatch, mod, *, rc=0, out="", err=""):
    """Record every pipx argv `mod` runs, and script the exit code."""
    import subprocess
    seen: list = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        code = rc(len(seen)) if callable(rc) else rc
        return subprocess.CompletedProcess(argv, code, out, err)

    monkeypatch.setattr(mod, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # Stubbed so it doesn't add a pipx call of its own to `seen`; its own behaviour
    # is pinned by test_a_successful_bootstrap_drops_the_run_cache below.
    if hasattr(mod, "spawn_detached_cache_clear"):
        monkeypatch.setattr(mod, "spawn_detached_cache_clear", lambda: True)
    return seen


def test_ensure_durable_install_is_a_no_op_when_already_durable(monkeypatch):
    """A normal `pipx install` host and a source checkout must not be reinstalled
    every time they pin — that would turn `resurrect` into a minutes-long command
    and, on a checkout, replace the code the developer is editing."""
    from facade import selfupdate
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: True)
    seen = _pipx_recorder(monkeypatch, selfupdate)
    assert selfupdate.ensure_durable_install() == (True, "")
    assert not seen, f"it reinstalled a host that was already durable: {seen!r}"


def test_ensure_durable_install_installs_floored(monkeypatch):
    from facade import selfupdate
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: None)
    seen = _pipx_recorder(monkeypatch, selfupdate)
    ok, _ = selfupdate.ensure_durable_install()
    assert ok is True
    assert seen == [["pipx", "install", "--force", selfupdate._agent_floor_spec()]], (
        f"the bootstrap install is not the floored forced install: {seen!r}"
    )


def test_the_bootstrap_install_is_forced(monkeypatch):
    """Measured against real pipx 1.16.5: `pipx install <spec>` over a venv that
    still exists prints "already seems to be installed" and EXITS 0. So if the
    uninstall above it was the leg that failed — a Windows file lock on a
    supervisor-relaunched bridge is the realistic cause — a plain install would
    report success having changed nothing, and we would pin the stale copy while
    telling the user it had been replaced."""
    from facade import selfupdate
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: None)
    seen = _pipx_recorder(monkeypatch, selfupdate)
    selfupdate.ensure_durable_install()
    installs = [c for c in seen if c[1] == "install"]
    assert installs and "--force" in installs[0], (
        f"a plain install here is a no-op that reports success: {installs!r}"
    )


def test_ensure_durable_install_replaces_a_stale_durable_copy(tmp_path, monkeypatch):
    """An older durable install is worse than none: pinning to it is how the bridge
    "starts on an old version" even after the cache problem is solved. Remove it,
    then install — the same clean-install rule the updater follows."""
    from facade import selfupdate
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: tmp_path)
    seen = _pipx_recorder(monkeypatch, selfupdate)
    assert selfupdate.ensure_durable_install()[0] is True
    subs = [c[1] for c in seen]
    assert subs == ["uninstall", "install"], f"not a clean replacement: {seen!r}"


def test_ensure_durable_install_reports_a_failed_install(monkeypatch):
    from facade import selfupdate
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: None)
    _pipx_recorder(monkeypatch, selfupdate, rc=1, err="No matching distribution")
    ok, note = selfupdate.ensure_durable_install()
    assert ok is False
    assert "No matching distribution" in note, f"the reason was swallowed: {note!r}"


def test_ensure_durable_install_refuses_a_zero_exit_it_cannot_verify(monkeypatch):
    """pipx exiting 0 is not proof: if the package dir still can't be resolved, the
    caller would pin the cache path anyway and we would be back at the reported
    bug with a green tick in front of it."""
    from facade import selfupdate
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: None)
    _pipx_recorder(monkeypatch, selfupdate, rc=0)
    ok, note = selfupdate.ensure_durable_install()
    assert ok is False and "couldn't be resolved" in note


def test_pin_startup_installs_before_pinning(monkeypatch):
    """Order is the property: pinning first and installing after would write the
    cache paths and then leave them there."""
    from facade import cli, selfupdate
    trace: list = []
    monkeypatch.setattr(cli.autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(selfupdate, "ensure_durable_install",
                        lambda: (trace.append("ensure") or (True, "ok")))
    monkeypatch.setattr(cli.autostart, "install",
                        lambda *a, **k: (trace.append("pin") or (True, "")))
    assert cli._pin_startup() == (True, "")
    assert trace == ["ensure", "pin"], f"wrong order: {trace!r}"


def test_pin_startup_does_not_pin_when_the_install_failed(monkeypatch):
    """Falling through to `autostart.install()` would just hit its own refusal, but
    the user would see the generic message instead of the reason the install
    failed — which is the only actionable thing here."""
    from facade import cli, selfupdate
    trace: list = []
    monkeypatch.setattr(cli.autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(selfupdate, "ensure_durable_install", lambda: (False, "offline"))
    monkeypatch.setattr(cli.autostart, "install",
                        lambda *a, **k: (trace.append("pin") or (True, "")))
    ok, msg = cli._pin_startup()
    assert ok is False and "offline" in msg
    assert trace == [], "it pinned despite having nothing durable to pin to"


def test_pin_startup_skips_the_install_on_a_durable_host(monkeypatch):
    from facade import cli, selfupdate
    trace: list = []
    monkeypatch.setattr(cli.autostart, "pin_target_is_durable", lambda: True)
    monkeypatch.setattr(selfupdate, "ensure_durable_install",
                        lambda: (trace.append("ensure") or (True, "")))
    monkeypatch.setattr(cli.autostart, "install",
                        lambda *a, **k: (trace.append("pin") or (True, "")))
    assert cli._pin_startup() == (True, "")
    assert trace == ["pin"], f"reinstalled a durable host: {trace!r}"


def test_a_successful_bootstrap_drops_the_run_cache(monkeypatch):
    """"No cache needed" has to be true, not just intended. `pipx run` reuses its
    venv for ~14 days, so leaving it behind means a later bootstrap can replay a
    build OLDER than the install we just made — the same stale-version symptom
    arriving by a different route."""
    from facade import selfupdate
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: None)
    _pipx_recorder(monkeypatch, selfupdate)
    cleared: list = []
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear",
                        lambda: cleared.append(True) or True)
    assert selfupdate.ensure_durable_install()[0] is True
    assert cleared == [True], "the stale run-cache venv was left behind"


def _run_cache_cleaner(cache_dir):
    """Execute the real `_CACHE_CLEAR_WAITER` payload against `cache_dir`.

    It ships as a `-c` STRING run by a foreign interpreter, so nothing in the
    import path exercises it — and the test above can only ever prove it was
    CALLED. That is how the previous cleaner passed while deleting nothing at all:
    it matched cache entries by name, and pipx names a run-venv after a truncated
    sha256 of the spec (`aa2125a9e139d3c`) with no package name anywhere in it."""
    import subprocess
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    from facade import selfupdate
    subprocess.run([sys.executable, "-c", selfupdate._CACHE_CLEAR_WAITER,
                    str(dead.pid), str(cache_dir)], timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _cache_entry(root, name, *, ours, windows=False):
    """A pipx run-venv, named the way pipx names them: a bare hash."""
    sp = (root / name / "Lib" / "site-packages") if windows else \
        (root / name / "lib" / "python3.13" / "site-packages")
    sp.mkdir(parents=True)
    (sp / ("facade" if ours else "black")).mkdir()
    return root / name


def test_the_run_cache_cleaner_removes_our_venv(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    mine = _cache_entry(cache, "aa2125a9e139d3c", ours=True)
    _run_cache_cleaner(cache)
    assert not mine.exists(), (
        "the cleaner matched nothing — pipx run-venv names are bare hashes, so a "
        "filter looking for 'superresearch' in the directory name deletes nothing "
        "while reporting that it cleaned up"
    )


def test_the_run_cache_cleaner_removes_the_windows_layout_too(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    mine = _cache_entry(cache, "6b504b0006266e7", ours=True, windows=True)
    _run_cache_cleaner(cache)
    assert not mine.exists()


def test_the_run_cache_cleaner_leaves_other_tools_alone(tmp_path):
    """Surgical, and it has to be: this is an rmtree loop over a directory shared
    with every other pipx-run tool on the machine."""
    cache = tmp_path / "cache"
    cache.mkdir()
    theirs = _cache_entry(cache, "b1c2d3e4f506070", ours=False)
    loose = cache / "CACHEDIR.TAG"
    loose.write_text("Signature: 8a477f597d28d172", encoding="utf-8")
    _run_cache_cleaner(cache)
    assert theirs.exists(), "it deleted another tool's cached venv"
    assert loose.exists(), "it deleted a file it does not own"


def test_a_failed_bootstrap_leaves_the_cache_alone(monkeypatch):
    """The cache copy is the only working agent on the box at that moment —
    deleting it after a failed install would take chat down with it."""
    from facade import selfupdate
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(selfupdate.autostart, "durable_venv", lambda: None)
    _pipx_recorder(monkeypatch, selfupdate, rc=1, err="boom")
    cleared: list = []
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear",
                        lambda: cleared.append(True) or True)
    assert selfupdate.ensure_durable_install()[0] is False
    assert cleared == [], "it deleted the only agent left on the machine"


# ── degrading without lying ──────────────────────────────────────────────────

def test_a_transient_pipx_failure_is_not_remembered(tmp_path, monkeypatch):
    """One slow or failed `pipx environment` must not make a healthy host look
    pipx-less for the rest of the process.

    Memoising it does exactly that: `durable_venv()` returns None, pinning
    refuses, the bootstrap reinstalls over a perfectly good venv, and even after
    THAT succeeds the re-check reads the same poisoned answer and reports the
    install unresolvable. A repeated subprocess on a genuinely broken host is the
    cheaper mistake."""
    import subprocess
    calls = {"n": 0}
    venvs = tmp_path / "venvs"
    venvs.mkdir()

    def flaky(argv, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return subprocess.CompletedProcess(argv, 1, "", "timed out")
        return subprocess.CompletedProcess(argv, 0, str(venvs), "")

    monkeypatch.setattr(autostart, "_pipx_argv", lambda: ["pipx"])
    monkeypatch.setattr(autostart.subprocess, "run", flaky)
    assert autostart._pipx_value("PIPX_LOCAL_VENVS") is None
    assert autostart._pipx_value("PIPX_LOCAL_VENVS") == str(venvs), (
        "a one-off failure was cached and the host stays 'broken' for good"
    )


def test_a_success_is_remembered(tmp_path, monkeypatch):
    """Guard against the guard: never caching would put a subprocess on every
    path resolution, and `agent_dir()` is called on every launcher write."""
    import subprocess
    calls = {"n": 0}

    def counted(argv, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(argv, 0, str(tmp_path), "")

    monkeypatch.setattr(autostart, "_pipx_argv", lambda: ["pipx"])
    monkeypatch.setattr(autostart.subprocess, "run", counted)
    autostart._pipx_value("PIPX_LOCAL_VENVS")
    autostart._pipx_value("PIPX_LOCAL_VENVS")
    assert calls["n"] == 1


def test_a_foreign_pipxs_answer_does_not_clear_the_path(tmp_path, monkeypatch):
    """Hosts routinely have two pipxes — a brew one on PATH and a `python -m pipx`,
    or a PIPX_HOME exported in the shell that ran `pipx run` but not in ours. The
    one we can reach then reports a DIFFERENT cache root than the one we are
    running out of, and taking its "not in my cache" as final pins the evictable
    path all over again. A no from containment is not a yes to durability."""
    _fake_pipx_env(monkeypatch, {"PIPX_VENV_CACHEDIR": tmp_path / "other-pipx" / "cache"})
    running = tmp_path / "home" / ".cache" / "pipx" / "abcd" / "lib" / "site-packages"
    assert autostart.is_ephemeral(running) is True


def _store(tmp_path, monkeypatch):
    """Point the generated launcher at a temp store dir and seed a GOOD pin."""
    monkeypatch.setattr(autostart.config, "store_dir", lambda: tmp_path)
    p = autostart.launcher_path()
    p.write_text("sys.path.insert(0, '/durable/site-packages')\n", encoding="utf-8")
    return p


def test_the_windows_restart_will_not_downgrade_a_good_pin(tmp_path, monkeypatch):
    """`restart` refreshes the launcher because the agent dir moves on an upgrade.
    Invoked as `pipx run superresearch-agent restart` with nothing durable to
    resolve, that refresh would overwrite a working pin with cache paths — turning
    a login launcher that works into one that rots. Leaving it alone is strictly
    better; the restart itself still happens.

    Drives the REAL writer. Stubbing `write_launcher` is how the bypass survived
    review: the guard lived at this call site, `_win_restart` then fell through to
    `_win_start`, whose first act is an unconditional `write_launcher()` — and a
    stub records that as "called" without ever showing which path got written."""
    p = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(autostart, "_healthz", lambda timeout=2.0: None)
    monkeypatch.setattr(autostart, "_exec", lambda argv: (True, ""))
    monkeypatch.setattr(autostart, "_wait_healthz", lambda t: {"version": "1"})
    autostart._win_restart("T")
    assert "/durable/site-packages" in p.read_text(encoding="utf-8"), (
        "it rewrote the pin with paths it knows will be evicted"
    )


def test_the_windows_start_fallback_also_leaves_a_good_pin_alone(tmp_path, monkeypatch):
    """The bypass itself. When the scheduled task declines to start (an /IT task
    with no interactive session), `_win_restart` falls back to `_win_start` — and
    that fallback used to regenerate the launcher with cache paths, undoing the
    refusal the branch above had just made."""
    p = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(autostart, "_healthz", lambda timeout=2.0: None)
    monkeypatch.setattr(autostart, "_exec", lambda argv: (True, ""))
    monkeypatch.setattr(autostart, "pythonw_exe", lambda: sys.executable)
    monkeypatch.setattr(autostart.subprocess, "Popen", lambda *a, **k: None)
    healthz = iter([None, {"version": "1"}])
    monkeypatch.setattr(autostart, "_wait_healthz", lambda t: next(healthz))
    autostart._win_restart("T")
    assert "/durable/site-packages" in p.read_text(encoding="utf-8"), (
        "the start fallback wrote the cache path the guard had just refused"
    )


def test_every_launcher_writer_inherits_the_guard(tmp_path, monkeypatch):
    """One check on the writer, not four at the call sites. `_win_start`,
    `_write_systemd_unit` and `_darwin_install` all called `write_launcher()`
    unconditionally; only `_win_restart` guarded, so the property held on exactly
    one of the four paths that can write this file."""
    p = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: False)
    autostart.write_launcher()
    assert "/durable/site-packages" in p.read_text(encoding="utf-8")


def test_the_guard_never_blocks_the_first_launcher(tmp_path, monkeypatch):
    """Something that works until eviction beats nothing at all — and `install()`
    separately refuses to pin it, so this cannot quietly become the login
    configuration."""
    monkeypatch.setattr(autostart.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: False)
    monkeypatch.setattr(autostart, "agent_dir", lambda: tmp_path / "cachey")
    p = autostart.write_launcher()
    assert "cachey" in p.read_text(encoding="utf-8")


def test_an_explicit_agent_dir_still_wins(tmp_path, monkeypatch):
    """A caller that passes a directory has already decided what it is pinning —
    the guard is for the callers that pass nothing and inherit `agent_dir()`."""
    p = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: False)
    autostart.write_launcher(tmp_path / "chosen")
    assert "chosen" in p.read_text(encoding="utf-8")


def test_the_windows_restart_still_refreshes_a_durable_pin(tmp_path, monkeypatch):
    """Guard against the guard: skipping the refresh always would leave the
    launcher pointing at the pre-upgrade venv, which is the bug it exists for."""
    p = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(autostart, "pin_target_is_durable", lambda: True)
    monkeypatch.setattr(autostart, "agent_dir", lambda: tmp_path / "fresh")
    monkeypatch.setattr(autostart, "_healthz", lambda timeout=2.0: None)
    monkeypatch.setattr(autostart, "_exec", lambda argv: (True, ""))
    monkeypatch.setattr(autostart, "_wait_healthz", lambda t: {"version": "1"})
    autostart._win_restart("T")
    assert "fresh" in p.read_text(encoding="utf-8")
