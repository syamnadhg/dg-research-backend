"""Unit tests for Track D `auth/keystore.py`.

Hits the file-fallback path exclusively — the OS keystore (DPAPI on
Windows, libsecret on Linux, Keychain on macOS) is environment-specific
and not deterministically testable from CI. We force `_try_keyring` to
return None so all read/write/promote/recover operations go through the
chmod-0600 file at `~/.super-research/auth.json`.

The atomicity contract — kill at any of the four points in
`promote_pending`, end up with a usable token via `try_recover` — is the
load-bearing property; most of the test surface exercises that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auth import keystore


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect ~/.super-research/ to a tmp dir + force file fallback."""
    monkeypatch.setattr(keystore, "_FALLBACK_DIR", tmp_path)
    monkeypatch.setattr(keystore, "_FALLBACK_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(keystore, "_INSTALL_UUID_PATH", tmp_path / "install_uuid")
    # Keep the wipe-audit + refresh-lock files inside the tmp dir too, so tests
    # don't write to the real ~/.super-research/ (they're module constants).
    monkeypatch.setattr(keystore, "_WIPE_LOG", tmp_path / "keystore-audit.log")
    monkeypatch.setattr(keystore, "_REFRESH_LOCK_PATH", tmp_path / ".refresh.lock")
    # Force the keyring backend to "unavailable" so all ops hit the file.
    monkeypatch.setattr(keystore, "_try_keyring", lambda: None)
    return tmp_path


class TestInstallUuid:
    def test_creates_on_first_call(self, isolated_home):
        uuid = keystore.install_uuid()
        assert isinstance(uuid, str) and len(uuid) > 0
        assert (isolated_home / "install_uuid").exists()

    def test_stable_across_calls(self, isolated_home):
        u1 = keystore.install_uuid()
        u2 = keystore.install_uuid()
        u3 = keystore.install_uuid()
        assert u1 == u2 == u3

    def test_reads_existing(self, isolated_home):
        (isolated_home / "install_uuid").write_text("pre-existing-uuid")
        assert keystore.install_uuid() == "pre-existing-uuid"

    def test_handles_empty_file(self, isolated_home):
        # An empty file shouldn't be treated as a valid UUID — recreate.
        (isolated_home / "install_uuid").write_text("")
        uuid = keystore.install_uuid()
        assert uuid != ""


class TestSetGetDelete:
    def test_set_then_get(self, isolated_home):
        keystore.set("current", "install-A", "token-1")
        assert keystore.get("current", "install-A") == "token-1"

    def test_get_missing_returns_none(self, isolated_home):
        assert keystore.get("current", "install-A") is None

    def test_delete_removes(self, isolated_home):
        keystore.set("current", "install-A", "token-1")
        keystore.delete("current", "install-A")
        assert keystore.get("current", "install-A") is None

    def test_delete_missing_is_no_op(self, isolated_home):
        # Idempotent: deleting a slot that was never written shouldn't raise.
        keystore.delete("current", "install-A")
        assert keystore.get("current", "install-A") is None

    def test_slots_are_independent(self, isolated_home):
        keystore.set("current", "install-A", "cur")
        keystore.set("previous", "install-A", "prev")
        keystore.set("pending", "install-A", "pend")
        assert keystore.get("current", "install-A") == "cur"
        assert keystore.get("previous", "install-A") == "prev"
        assert keystore.get("pending", "install-A") == "pend"

    def test_install_uuids_are_independent(self, isolated_home):
        keystore.set("current", "install-A", "tok-A")
        keystore.set("current", "install-B", "tok-B")
        assert keystore.get("current", "install-A") == "tok-A"
        assert keystore.get("current", "install-B") == "tok-B"


class TestPromotePending:
    def test_no_op_when_pending_empty(self, isolated_home):
        keystore.set("current", "i", "old")
        keystore.promote_pending("i")
        # Untouched: no pending → no promotion.
        assert keystore.get("current", "i") == "old"
        assert keystore.get("previous", "i") is None

    def test_promotes_when_pending_present(self, isolated_home):
        keystore.set("current", "i", "old")
        keystore.set("pending", "i", "new")
        keystore.promote_pending("i")
        assert keystore.get("current", "i") == "new"
        assert keystore.get("previous", "i") == "old"
        assert keystore.get("pending", "i") is None

    def test_first_promotion_skips_previous(self, isolated_home):
        # No prior current → previous stays empty (nothing to demote).
        keystore.set("pending", "i", "new")
        keystore.promote_pending("i")
        assert keystore.get("current", "i") == "new"
        assert keystore.get("previous", "i") is None
        assert keystore.get("pending", "i") is None

    def test_kill_after_pending_write_recovers_pending(self, isolated_home):
        # Simulate kill BEFORE promote — current is still old, pending has new.
        keystore.set("current", "i", "old")
        keystore.set("pending", "i", "new")
        # Note: promote_pending NOT called.

        recovered = keystore.try_recover("i")
        assert recovered is not None
        # Recovery order: pending → current → previous. pending wins.
        slot, token = recovered
        assert slot == "pending"
        assert token == "new"

    def test_kill_mid_promote_after_previous_written(self, isolated_home):
        # Simulate kill AFTER `previous <- current` but BEFORE
        # `current <- pending`. State: previous=old, current=old, pending=new.
        # (Caller would have read old from current; we model that by leaving
        #  current unchanged.)
        keystore.set("current", "i", "old")
        keystore.set("previous", "i", "old")
        keystore.set("pending", "i", "new")
        # Recovery still picks pending — fresher.
        slot, token = keystore.try_recover("i")  # type: ignore[misc]
        assert slot == "pending"
        assert token == "new"

    def test_kill_mid_promote_after_current_swap(self, isolated_home):
        # Kill AFTER `current <- pending` but BEFORE
        # `delete pending`. State: previous=old, current=new, pending=new.
        keystore.set("current", "i", "new")
        keystore.set("previous", "i", "old")
        keystore.set("pending", "i", "new")
        # Try-recover still picks pending (it's there, value matches).
        slot, token = keystore.try_recover("i")  # type: ignore[misc]
        assert slot == "pending"
        assert token == "new"


class TestTryRecover:
    def test_returns_none_when_all_slots_empty(self, isolated_home):
        assert keystore.try_recover("i") is None

    def test_pending_takes_precedence_over_current(self, isolated_home):
        keystore.set("current", "i", "from-current")
        keystore.set("pending", "i", "from-pending")
        slot, token = keystore.try_recover("i")  # type: ignore[misc]
        assert slot == "pending"
        assert token == "from-pending"

    def test_current_takes_precedence_over_previous(self, isolated_home):
        keystore.set("current", "i", "from-current")
        keystore.set("previous", "i", "from-previous")
        slot, token = keystore.try_recover("i")  # type: ignore[misc]
        assert slot == "current"
        assert token == "from-current"

    def test_falls_back_to_previous(self, isolated_home):
        keystore.set("previous", "i", "from-previous")
        slot, token = keystore.try_recover("i")  # type: ignore[misc]
        assert slot == "previous"
        assert token == "from-previous"


class TestClearAll:
    def test_wipes_every_slot(self, isolated_home):
        for slot in keystore.SLOTS:
            keystore.set(slot, "i", f"val-{slot}")
        keystore.clear_all("i", reason="test")
        for slot in keystore.SLOTS:
            assert keystore.get(slot, "i") is None

    def test_other_installs_unaffected(self, isolated_home):
        keystore.set("current", "install-A", "a")
        keystore.set("current", "install-B", "b")
        keystore.clear_all("install-A", reason="test")
        assert keystore.get("current", "install-A") is None
        assert keystore.get("current", "install-B") == "b"


class TestFileFallbackAtomicity:
    def test_corrupted_json_treated_as_empty(self, isolated_home):
        # If the file got truncated mid-write (no transaction, hard kill),
        # subsequent reads should not crash — they should treat the file
        # as empty and let the caller decide what to do (likely re-pair).
        (isolated_home / "auth.json").write_text("{not valid json")
        assert keystore.get("current", "i") is None
        # Subsequent write should succeed and atomically replace the bad file.
        keystore.set("current", "i", "fresh")
        # Reading back works.
        assert keystore.get("current", "i") == "fresh"

    def test_tmp_files_cleaned_up_after_write(self, isolated_home):
        # `_file_save` writes to a temp file then `os.replace`s. After a
        # successful write, no stray `.auth.*.tmp` files should linger.
        keystore.set("current", "i", "tok")
        leftovers = list(isolated_home.glob(".auth.*.tmp"))
        assert leftovers == []

    def test_file_contents_are_valid_json(self, isolated_home):
        keystore.set("current", "i", "tok-c")
        keystore.set("pending", "i", "tok-p")
        raw = (isolated_home / "auth.json").read_text()
        blob = json.loads(raw)  # must round-trip
        assert "current:i" in blob
        assert blob["current:i"] == "tok-c"
        assert "pending:i" in blob
        assert blob["pending:i"] == "tok-p"


class TestWipeAudit:
    """clear_all must require a reason and leave a durable audit breadcrumb so a
    future wipe is never again unattributable (RC-6 / RC-4)."""

    def test_reason_is_required(self, isolated_home):
        import pytest as _pytest
        with _pytest.raises(TypeError):
            keystore.clear_all("i")  # missing the keyword-only `reason`

    def test_writes_audit_record_before_deletion(self, isolated_home):
        keystore.set("current", "i", "tok")
        keystore.clear_all("i", reason="crash-loop")
        audit = isolated_home / "keystore-audit.log"
        assert audit.exists()
        rec = json.loads(audit.read_text().strip().splitlines()[-1])
        assert rec["event"] == "clear_all"
        assert rec["reason"] == "crash-loop"
        assert rec["install"] == "i"[:8]
        assert "pid" in rec and "stack" in rec

    def test_audit_appends_one_line_per_wipe(self, isolated_home):
        keystore.clear_all("i", reason="unpair")
        keystore.clear_all("i", reason="retire")
        lines = (isolated_home / "keystore-audit.log").read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["reason"] == "unpair"
        assert json.loads(lines[1])["reason"] == "retire"


class TestCrossProcessRefreshLock:
    """The cross-process refresh lock must acquire/release cleanly and — the
    correctness-critical property — must NOT mask exceptions raised inside the
    `with` body (a single yield, no double-yield)."""

    def test_acquire_and_release(self, isolated_home):
        with keystore.cross_process_refresh_lock() as locked:
            assert locked is True
        # Released → re-acquirable.
        with keystore.cross_process_refresh_lock() as locked2:
            assert locked2 is True

    def test_body_exception_propagates_not_masked(self, isolated_home):
        import pytest as _pytest

        class Boom(RuntimeError):
            pass

        with _pytest.raises(Boom):
            with keystore.cross_process_refresh_lock():
                raise Boom("body error must surface, not a generator RuntimeError")
        # Lock is released after the exception → next acquire still works.
        with keystore.cross_process_refresh_lock() as locked:
            assert locked is True


class TestTryKeyringSentinel:
    """_try_keyring must reject the fail.Keyring sentinel so headless hosts use
    the file fallback cleanly instead of throwing on every op (RC-23)."""

    def test_fail_keyring_returns_none(self, tmp_path, monkeypatch):
        # NOTE: do NOT use isolated_home here — it stubs _try_keyring. Exercise
        # the real function against a fake keyring whose backend is fail.Keyring.
        import sys as _sys
        import types as _types

        fail_mod = _types.ModuleType("keyring.backends.fail")

        class _FailKeyring:
            pass

        fail_mod.Keyring = _FailKeyring
        kr_mod = _types.ModuleType("keyring")
        kr_mod.get_keyring = lambda: _FailKeyring()
        backends_mod = _types.ModuleType("keyring.backends")
        monkeypatch.setitem(_sys.modules, "keyring", kr_mod)
        monkeypatch.setitem(_sys.modules, "keyring.backends", backends_mod)
        monkeypatch.setitem(_sys.modules, "keyring.backends.fail", fail_mod)
        assert keystore._try_keyring() is None

    def test_real_backend_returned(self, tmp_path, monkeypatch):
        import sys as _sys
        import types as _types

        fail_mod = _types.ModuleType("keyring.backends.fail")

        class _FailKeyring:
            pass

        fail_mod.Keyring = _FailKeyring

        class _RealBackend:
            pass  # not a _FailKeyring, no empty `backends` attr

        kr_mod = _types.ModuleType("keyring")
        kr_mod.get_keyring = lambda: _RealBackend()
        backends_mod = _types.ModuleType("keyring.backends")
        monkeypatch.setitem(_sys.modules, "keyring", kr_mod)
        monkeypatch.setitem(_sys.modules, "keyring.backends", backends_mod)
        monkeypatch.setitem(_sys.modules, "keyring.backends.fail", fail_mod)
        assert keystore._try_keyring() is kr_mod


class TestSetPurgesFileShadow:
    """When keyring is the live store, set() must purge any stale file-fallback
    shadow so a later transient keyring miss can't return an outdated token
    (RC-24)."""

    def test_keyring_success_removes_file_shadow(self, tmp_path, monkeypatch):
        monkeypatch.setattr(keystore, "_FALLBACK_DIR", tmp_path)
        monkeypatch.setattr(keystore, "_FALLBACK_PATH", tmp_path / "auth.json")
        # Seed a stale file shadow for current:i
        (tmp_path / "auth.json").write_text(json.dumps({"current:i": "STALE"}))

        store: dict[str, str] = {}

        class _KR:
            def set_password(self, _svc, acct, val):
                store[acct] = val

        monkeypatch.setattr(keystore, "_try_keyring", lambda: _KR())
        keystore.set("current", "i", "FRESH")
        # Keyring got the value…
        assert store["current:i"] == "FRESH"
        # …and the stale file shadow is gone (no split-brain).
        blob = json.loads((tmp_path / "auth.json").read_text())
        assert "current:i" not in blob
