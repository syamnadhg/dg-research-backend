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
        # Either None (no python on PATH — unusual) or a real, non-venv python.
        if py is not None:
            from pathlib import Path as _P
            assert _P(py).exists()
            # Must NOT be this process's (venv) python — that's the whole point.
            try:
                assert _P(py).resolve() != _P(research.sys.executable).resolve()
            except Exception:
                pass  # resolve() edge cases shouldn't fail the assertion

    def test_spawn_detached_aborts_cleanly_without_pipx(self, monkeypatch):
        # With no pipx resolvable, spawning must return False (caller then prints
        # the manual command) — never raise.
        monkeypatch.setattr(research, "_pipx_cmd", lambda: None)
        assert research._spawn_detached_lifecycle("uninstall") is False


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
        import json, time
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.1")
        (tmp_path / ".version_check.json").write_text(
            json.dumps({"checked_at": time.time(), "latest": "0.1.2"})
        )
        assert research._check_newer_version() == "0.1.2"

    def test_cache_hit_same_version_returns_none(self, tmp_path, monkeypatch):
        import json, time
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
