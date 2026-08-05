"""Unit tests for Track D D5c — user-mode token mint.

Originally covered three areas:
  - `_fresh_user_mode_id_token` (still active — used by other Track D
    request flows: device-patch, oauth-callback, etc.)
  - `_save_api_key_via_fe_bridge` (REMOVED — pair-time API keys now
    persist BE-local, not Firestore)
  - `_save_api_key_to_firestore` mode-branch (REMOVED — function deleted
    alongside the bridge)

The bridge tests were dropped when --pair Stage 3 moved to BE-local
persistence (Win User-scope env / .dg-supervisor.env). See
test_pair_prompt.py for the new `TestSaveApiKeyLocal` coverage.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


# Import via importlib so we can reload between tests if needed
research = importlib.import_module("research")


# ─── _fresh_user_mode_id_token ────────────────────────────────────────


class TestFreshUserModeIdToken:
    def test_returns_none_when_keystore_empty(self, monkeypatch):
        # Stub the keystore.try_recover() to return None (no creds saved).
        from auth import keystore as ks
        monkeypatch.setattr(ks, "install_uuid", lambda: "fake-uuid")
        monkeypatch.setattr(ks, "try_recover", lambda _: None)
        assert research._fresh_user_mode_id_token() is None

    def test_returns_token_on_successful_refresh(self, monkeypatch):
        from auth import keystore as ks, credentials as creds_mod
        monkeypatch.setattr(ks, "install_uuid", lambda: "fake-uuid")
        monkeypatch.setattr(ks, "try_recover", lambda _: "stored-refresh-token")

        class FakeCreds:
            token = "fake-id-token"
            def __init__(self, *_args, **_kwargs):
                pass
            def refresh(self, _request):
                self.token = "fake-id-token"

        monkeypatch.setattr(creds_mod, "RefreshTokenCredentials", FakeCreds)
        assert research._fresh_user_mode_id_token() == "fake-id-token"

    def test_returns_none_on_revoked(self, monkeypatch):
        from auth import keystore as ks, credentials as creds_mod
        monkeypatch.setattr(ks, "install_uuid", lambda: "fake-uuid")
        monkeypatch.setattr(ks, "try_recover", lambda _: "stored-refresh-token")
        cleared = {"called": False, "reason": None}
        def fake_clear(_iuid, *, reason=None):
            cleared["called"] = True
            cleared["reason"] = reason
        monkeypatch.setattr(ks, "clear_all", fake_clear)

        class FakeCreds:
            def __init__(self, *_args, **_kwargs):
                pass
            def refresh(self, _request):
                # Raises on BOTH the initial refresh AND the re-read-before-wipe
                # retry → the re-read confirms a genuine revoke, so the wipe fires.
                raise creds_mod.RevokedError("INVALID_REFRESH_TOKEN")

        monkeypatch.setattr(creds_mod, "RefreshTokenCredentials", FakeCreds)
        assert research._fresh_user_mode_id_token() is None
        # Defense-in-depth: keystore should be wiped on a CONFIRMED revoked token.
        assert cleared["called"]
        assert cleared["reason"] == "revoke"


# ─── Detached lifecycle waiter (--update / --uninstall self-lock fix) ──
class TestLifecycleWaiter:
    def test_waiter_script_is_valid_python(self):
        # The waiter is an embedded `-c` string normal import/compile won't
        # exercise — a typo would only surface at runtime when a user runs
        # --uninstall. Compile it here so the syntax is regression-guarded.
        compile(research._LIFECYCLE_WAITER, "<lifecycle-waiter>", "exec")

    def test_path_python_is_non_venv_when_possible(self):
        py = research._path_python()
        # Either None (nothing safe exists — the caller prints the manual
        # command) or a real interpreter outside the venv pipx will rebuild.
        if py is not None:
            from pathlib import Path as _P
            assert _P(py).exists()
            # ⚠ LOCATION, not realpath identity. The previous form compared
            # `_P(py).resolve()` against `sys.executable.resolve()` — and on
            # POSIX a venv's python is a SYMLINK to its base, so both sides
            # resolve to the same real binary and the assertion fired on
            # perfectly safe answers. Measured 2026-08-05: it failed on this Mac
            # AND in the CI condition (no venv, actions/setup-python, where PATH's
            # python IS the running one), and passed only on Windows, whose venvs
            # COPY python.exe rather than symlinking it. A guard that is green on
            # exactly one platform is not a guard.
            #
            # What actually matters is where the returned interpreter LIVES: it
            # must not be inside the directory pipx is about to delete.
            if research.sys.prefix == research.sys.base_prefix:
                return          # not a venv — nothing is going to be deleted
            try:
                venv = _P(research.sys.prefix).resolve()
                cand = _P(py)
                inside = venv == cand or venv in cand.parents \
                    or venv == cand.resolve() or venv in cand.resolve().parents
            except OSError:
                pytest.skip("resolve() failed on this filesystem")
            assert not inside, (
                f"_path_python() returned an interpreter inside the venv ({py}). "
                f"The self-update waiter would die with the venv it is rebuilding."
            )

    def test_spawn_detached_aborts_cleanly_without_pipx(self, monkeypatch):
        # With no pipx resolvable, spawning must return None (falsy — caller then
        # prints the manual command) — never raise.
        monkeypatch.setattr(research, "_pipx_cmd", lambda: None)
        assert research._spawn_detached_lifecycle("uninstall") is None


# ─── Daemon-loop orphan-sweep — the offline-after-pair ROOT-CAUSE invariant ──
class TestSweepKillTargets:
    """Regression guard: the pre-flight orphan sweep must NEVER kill a peer
    `--daemon-loop` process. Killing one cascaded and terminated the surviving
    supervisor itself (it logged 'supervisor up' then died before spawning any
    worker → API never bound → device permanently offline). Single-instance is
    guarded by the cross-process lock, not by reaping peers."""

    def _procs(self):
        return [
            (100, r"py research.py --daemon-loop", "daemon-loop"),  # self
            (200, r"py research.py --daemon-loop", "daemon-loop"),  # PEER — must survive
            (300, r"py research.py --serve --port 8000", "serve"),  # in-range + healthy → skip
            (301, r"py research.py --serve --port 8001", "serve"),  # in-range, UNhealthy → kill
            (302, r"py research.py --serve --port 9999", "serve"),  # out-of-range → kill
            (400, r"py research.py 'some topic'", "other"),         # old one-off → kill
            (401, r"py research.py 'fresh topic'", "other"),        # fresh one-off → skip
        ]

    def test_peer_daemon_loop_never_killed(self):
        kill, skipped = research._sweep_kill_targets(
            self._procs(), self_pid=100, fleet_lo=8000, fleet_hi=8002, max_age_h=4,
            health_fn=lambda p: p == 8000,                 # only 8000 is healthy
            age_fn=lambda pid: 99999 if pid == 400 else 1,  # 400 is old, 401 fresh
        )
        assert 200 not in kill, "PEER daemon-loop must NEVER be reaped (the cascade bug)"
        assert 100 not in kill, "self must be excluded"
        assert 300 not in kill and 300 in skipped, "healthy in-range serve is skipped"
        assert 301 in kill, "unhealthy in-range serve is reaped"
        assert 302 in kill, "out-of-range serve is reaped"
        assert 400 in kill, "old one-off proc is reaped"
        assert 401 not in kill, "fresh one-off proc is left alone"

    def test_no_daemon_loops_in_killlist_at_all(self):
        kill, _ = research._sweep_kill_targets(
            self._procs(), self_pid=999, fleet_lo=8000, fleet_hi=8002, max_age_h=4,
            health_fn=lambda p: False, age_fn=lambda pid: 0,
        )
        # Even with self_pid not in the list, NO daemon-loop pid is ever killed.
        assert 100 not in kill and 200 not in kill


# ─── pip-style version-upgrade notice ──────────────────────────────────
class TestVersionNotice:
    def test_version_gt(self):
        assert research._version_gt("1.0.10", "1.0.9") is True
        assert research._version_gt("0.1.2", "0.1.1") is True
        assert research._version_gt("0.1.1", "0.1.1") is False
        assert research._version_gt("0.1.0", "0.1.1") is False
        assert research._version_gt("garbage", "0.1.1") is False  # never raises

    def test_cache_hit_newer_returns_latest(self, tmp_path, monkeypatch):
        import json
        import time
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.1")
        (tmp_path / ".version_check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest": "0.1.2"})
        )
        assert research._check_newer_version() == "0.1.2"

    def test_cache_hit_same_version_returns_none(self, tmp_path, monkeypatch):
        import json
        import time
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.2")
        (tmp_path / ".version_check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest": "0.1.2"})
        )
        assert research._check_newer_version() is None

    def test_source_checkout_skips(self, monkeypatch):
        monkeypatch.setattr(research, "_is_source_checkout", lambda: True)
        assert research._check_newer_version() is None

    def test_check_newer_version_force_passthrough(self, monkeypatch):
        # `force=True` (the app's "Check for updates") must reach _latest_on_pypi.
        seen = {}
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.5")

        def _latest(*, force=False):
            seen["force"] = force
            return "0.1.6"

        monkeypatch.setattr(research, "_latest_on_pypi", _latest)
        assert research._check_newer_version(force=True) == "0.1.6"
        assert seen["force"] is True

    def test_version_gt_zero_pads(self):
        # 1.0 and 1.0.0 are the SAME version — neither is 'newer' (regression:
        # unpadded compare treated 1.0.0 > 1.0, which would false-trigger --update).
        assert research._version_gt("1.0", "1.0.0") is False
        assert research._version_gt("1.0.0", "1.0") is False
        assert research._version_gt("1.0.1", "1.0") is True
        assert research._version_gt("0.1.5", "0.1.5") is False

    def test_latest_on_pypi_cache_hit_returns_raw(self, tmp_path, monkeypatch):
        # Returns the RAW latest regardless of the installed version (vs
        # _check_newer_version which only returns it when strictly newer).
        import json
        import time
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        (tmp_path / ".version_check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest": "0.1.2"})
        )
        assert research._latest_on_pypi() == "0.1.2"

    def test_latest_on_pypi_force_bypasses_cache(self, tmp_path, monkeypatch):
        # A forced lookup ignores a fresh 24h cache and re-hits the network.
        import json
        import time
        import urllib.request as _u
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        (tmp_path / ".version_check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest": "0.1.2"})  # stale
        )

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"info": {"version": "0.1.9"}}).encode()

        monkeypatch.setattr(_u, "urlopen", lambda *a, **k: _Resp())
        assert research._latest_on_pypi(force=True) == "0.1.9"
        # cache was refreshed → a subsequent non-forced read sees the new value
        assert research._latest_on_pypi() == "0.1.9"

    def test_latest_on_pypi_force_failure_preserves_cache(self, tmp_path, monkeypatch):
        # A forced fetch that FAILS (offline) must NOT clobber a prior good value
        # with "" — else the CLI + FE "update available" nudge goes silent for 24h.
        import json
        import time
        import urllib.request as _u
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        (tmp_path / ".version_check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest": "0.1.9"})
        )

        def _boom(*a, **k):
            raise OSError("offline")

        monkeypatch.setattr(_u, "urlopen", _boom)
        # this call couldn't determine a fresh value…
        assert research._latest_on_pypi(force=True) is None
        # …but the prior good value survives for the non-forced readers (nudge stays)
        data = json.loads((tmp_path / ".version_check.json").read_text())
        assert data["latest"] == "0.1.9"
        assert research._latest_on_pypi() == "0.1.9"

    def test_device_version_fields_installed_with_update(self, monkeypatch):
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.4")
        monkeypatch.setattr(research, "_check_newer_version", lambda *, force=False: "0.1.5")
        assert research._device_version_fields() == {
            "version": "0.1.4", "updateAvailable": "0.1.5", "sourceCheckout": False}

    def test_device_version_fields_current(self, monkeypatch):
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.5")
        monkeypatch.setattr(research, "_check_newer_version", lambda *, force=False: None)
        assert research._device_version_fields() == {
            "version": "0.1.5", "updateAvailable": None, "sourceCheckout": False}

    def test_device_version_fields_source_checkout_no_prompt(self, monkeypatch):
        # A SOURCE CHECKOUT reports sourceCheckout=True + version None — even when
        # it's an editable / `pip install -e .` install whose discoverable metadata
        # makes _sr_version() report a REAL version (the VivobookPro leak: the old
        # `startswith("(")` test let "0.1.4" through). Gate is the path check, so a
        # real version string must STILL yield None + the sourceCheckout flag (the
        # app then shows "Source checkout · update with git pull", no Check/Update).
        monkeypatch.setattr(research, "_is_source_checkout", lambda: True)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.4")  # metadata present
        # _check_newer_version is short-circuited by the same gate; assert it too.
        assert research._check_newer_version() is None
        assert research._device_version_fields() == {
            "version": None, "updateAvailable": None, "sourceCheckout": True}


class TestSelfUpdateIdempotent:
    """`superresearch --update` must reinstall ONLY when actually outdated — else
    say 'already up to date' and NOT bounce running workers (the idempotency gate
    that already existed on the bridge `/update` path, ported to the CLI)."""

    def _wire(self, monkeypatch, *, cur, latest, spawned):
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_sr_version", lambda: cur)
        monkeypatch.setattr(research, "_latest_on_pypi", lambda *, force=False: latest)

        def _spawn(action, **kw):
            spawned.append(action)
            return True

        monkeypatch.setattr(research, "_spawn_detached_lifecycle", _spawn)

    def test_already_current_does_not_reinstall(self, monkeypatch, capsys):
        spawned = []
        self._wire(monkeypatch, cur="0.1.5", latest="0.1.5", spawned=spawned)
        assert research._self_update() == 0
        assert spawned == [], "must NOT spawn an upgrade when already current"
        assert "up to date" in capsys.readouterr().out.lower()

    def test_current_ahead_of_pypi_does_not_reinstall(self, monkeypatch):
        # Local pre-release ahead of PyPI — treat as current, no reinstall.
        spawned = []
        self._wire(monkeypatch, cur="0.1.6", latest="0.1.5", spawned=spawned)
        assert research._self_update() == 0
        assert spawned == []

    def test_outdated_reinstalls(self, monkeypatch):
        spawned = []
        self._wire(monkeypatch, cur="0.1.4", latest="0.1.5", spawned=spawned)
        assert research._self_update() == 0
        assert spawned == ["upgrade"], "must spawn the upgrade when outdated"

    def test_offline_proceeds(self, monkeypatch):
        # PyPI unreachable (latest None) — don't strand an intentional update.
        spawned = []
        self._wire(monkeypatch, cur="0.1.5", latest=None, spawned=spawned)
        assert research._self_update() == 0
        assert spawned == ["upgrade"]

    def test_freshness_check_is_forced(self, monkeypatch):
        # The gate MUST use a forced lookup (not the stale 24h cache).
        seen = {}
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.5")
        monkeypatch.setattr(research, "_spawn_detached_lifecycle", lambda a, **kw: True)

        def _latest(*, force=False):
            seen["force"] = force
            return "0.1.5"

        monkeypatch.setattr(research, "_latest_on_pypi", _latest)
        research._self_update()
        assert seen.get("force") is True


# ─── _path_python() drives the waiter's interpreter choice ────────────────────
#
# Reproduced 2026-08-05. The old selection compared RESOLVED interpreters:
#
#     me = Path(sys.executable).resolve()
#     for exe in cands:
#         if Path(exe).resolve() != me: return exe
#     return cands[0] if cands else None
#
# On POSIX a venv's python is a SYMLINK to its base, so `me` IS the base and
# every PATH candidate from that same base got rejected. The unguarded fallback
# then supplied the answer. With the venv's own bin on PATH — what `activate`
# does — that fallback returned the venv python itself:
#
#     PATH = <venv>/bin  ->  _path_python() -> <venv>/bin/python      # doomed
#
# which is what the docstring already forbade. The waiter would die with the venv
# pipx was rebuilding: backend down, not upgraded.
#
# These build a synthetic venv rather than leaning on the one the suite happens
# to run in, so they assert the same thing on macOS, Linux and Windows — and in
# CI, where there is no venv at all. That matters here: the guard they replace
# passed on exactly one platform.

class TestPathPythonPicksASurvivor:
    _BIN = "Scripts" if sys.platform == "win32" else "bin"
    _EXE = "python.exe" if sys.platform == "win32" else "python3"

    def _interpreter(self, root, link_to=None):
        """A findable, executable python at the platform's venv layout.

        ⚠ `link_to` matters. A real POSIX venv SYMLINKS its python to the base
        interpreter, so `resolve()` on it lands OUTSIDE the venv — which is
        exactly why the literal-path check exists and why a fixture built from
        plain files cannot see it. Verified by mutation: with plain files,
        deleting the literal check survived. Windows venvs copy the exe, so the
        plain file is the faithful shape there.
        """
        d = root / self._BIN
        d.mkdir(parents=True, exist_ok=True)
        exe = d / self._EXE
        if link_to is not None and sys.platform != "win32":
            exe.symlink_to(link_to)
        else:
            exe.write_text("")
            exe.chmod(0o755)
        return exe

    def _layout(self, tmp_path, monkeypatch, *, path_dirs, base_has_python=True):
        venv = tmp_path / "venv"
        base = tmp_path / "base"
        if base_has_python:
            self._interpreter(base)
            self._interpreter(venv, link_to=base / self._BIN / self._EXE)
        else:
            # Nothing to point at — a dangling symlink is not a findable python,
            # and this case is about there being no survivor at all.
            self._interpreter(venv)
        monkeypatch.setattr(research.sys, "prefix", str(venv))
        monkeypatch.setattr(research.sys, "base_prefix", str(base))
        monkeypatch.setenv("PATH", os.pathsep.join(str(p) for p in path_dirs(venv, base)))
        return venv, base

    def test_an_activated_venv_never_yields_the_doomed_interpreter(self, tmp_path, monkeypatch):
        """⭐ The reproduction. Every PATH name points back inside the venv."""
        venv, _ = self._layout(tmp_path, monkeypatch,
                               path_dirs=lambda v, b: [v / self._BIN])
        got = research._path_python()
        assert got is not None, "a safe interpreter exists (the base) and was not found"
        p = Path(got)
        assert venv not in p.parents and p != venv, (
            f"returned {got}, which is inside the venv pipx is about to delete")

    def test_it_falls_back_to_the_interpreter_the_venv_was_built_from(self, tmp_path, monkeypatch):
        """The base interpreter is outside the venv by definition, so it survives
        the rebuild — and it is the only safe answer once PATH is exhausted."""
        _, base = self._layout(tmp_path, monkeypatch,
                               path_dirs=lambda v, b: [v / self._BIN])
        assert Path(research._path_python()).parent.parent == base

    def test_a_safe_path_candidate_wins_over_the_base_fallback(self, tmp_path, monkeypatch):
        """PATH first, base last: a system python already on PATH is the cheaper
        and more predictable answer, and the fallback is a last resort."""
        safe = tmp_path / "usr"
        self._interpreter(safe)
        venv, base = self._layout(
            tmp_path, monkeypatch,
            path_dirs=lambda v, b: [safe / self._BIN, v / self._BIN])
        assert Path(research._path_python()).parent == safe / self._BIN

    def test_none_when_every_candidate_is_doomed(self, tmp_path, monkeypatch):
        """⛔ None is the honest answer, and the caller already handles it by
        printing the manual command. Returning a doomed interpreter instead —
        which is what the old fallback did — takes the backend down mid-upgrade
        and does not upgrade it."""
        self._layout(tmp_path, monkeypatch,
                     path_dirs=lambda v, b: [v / self._BIN], base_has_python=False)
        assert research._path_python() is None

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink semantics")
    def test_a_symlink_pointing_into_the_venv_is_rejected(self, tmp_path, monkeypatch):
        """A wrapper on PATH that RESOLVES into the venv.

        Built as a `--copies` venv on purpose: its interpreter is a real file
        inside the venv, which is what `python -m venv --copies`, uv, and Windows
        all produce. In that shape the literal path of the wrapper is innocent and
        only resolving it shows where it lands — the mirror of the default POSIX
        venv, where the literal path is the guilty one and resolve() points
        harmlessly out. Both checks are load-bearing, each for one of these two.
        """
        venv, base = tmp_path / "venv", tmp_path / "base"
        real_inside = self._interpreter(venv)          # --copies: a real binary
        self._interpreter(base)
        hop = tmp_path / "hop" / self._BIN
        hop.mkdir(parents=True, exist_ok=True)
        (hop / self._EXE).symlink_to(real_inside)
        monkeypatch.setattr(research.sys, "prefix", str(venv))
        monkeypatch.setattr(research.sys, "base_prefix", str(base))
        monkeypatch.setenv("PATH", os.pathsep.join([str(hop), str(base / self._BIN)]))
        got = research._path_python()
        assert Path(got).resolve().parent.parent == base, (
            f"followed a symlink into the doomed venv: {got}")

    def test_a_process_outside_any_venv_takes_the_first_candidate(self, tmp_path, monkeypatch):
        """⚠ The CI condition — actions/setup-python, no venv, and PATH's python
        IS the running interpreter. Nothing is being deleted, so that is a fine
        answer; the OLD guard called it a failure and would have gone red on
        every CI run."""
        here = tmp_path / "sys"
        self._interpreter(here)
        monkeypatch.setattr(research.sys, "prefix", str(tmp_path / "same"))
        monkeypatch.setattr(research.sys, "base_prefix", str(tmp_path / "same"))
        monkeypatch.setenv("PATH", str(here / self._BIN))
        assert Path(research._path_python()).parent == here / self._BIN
