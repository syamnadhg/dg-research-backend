from pathlib import Path

from facade import store


def _force_file_backend(monkeypatch, tmp_path: Path):
    """Disable keyring so we exercise the 0600-file fallback deterministically."""
    monkeypatch.setattr(store, "_try_keyring", lambda: None)
    monkeypatch.setattr(store, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(store, "_FALLBACK_PATH", tmp_path / "session.json")


def test_save_load_clear_roundtrip(monkeypatch, tmp_path):
    _force_file_backend(monkeypatch, tmp_path)
    assert store.load() is None

    blob = {"uid": "u1", "email": "a@b.c", "refresh_token": "RT-1"}
    store.save(blob)
    assert store.load() == blob

    store.clear()
    assert store.load() is None


def test_save_overwrites(monkeypatch, tmp_path):
    _force_file_backend(monkeypatch, tmp_path)
    store.save({"uid": "u1", "refresh_token": "RT-1"})
    store.save({"uid": "u1", "refresh_token": "RT-2"})
    assert store.load()["refresh_token"] == "RT-2"


def test_corrupt_file_treated_as_absent(monkeypatch, tmp_path):
    _force_file_backend(monkeypatch, tmp_path)
    (tmp_path / "session.json").write_text("{not json")
    assert store.load() is None


def test_no_keyring_backend_is_quiet(monkeypatch, caplog):
    """A genuinely-absent keyring (WSL/bare Linux) selects keyring's fail.Keyring
    sentinel — _try_keyring must detect it and return None WITHOUT logging a
    WARNING, so connect/login output stays clean."""
    import logging

    from keyring.backends import fail

    fake_keyring = type(
        "K", (), {"get_keyring": staticmethod(lambda: fail.Keyring())}
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)

    with caplog.at_level(logging.WARNING, logger=store.log.name):
        assert store._try_keyring() is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_save_no_keyring_does_not_warn(monkeypatch, tmp_path, caplog):
    """The plaintext-at-rest note on a headless host is INFO, not WARNING."""
    import logging

    monkeypatch.setattr(store, "_try_keyring", lambda: None)
    monkeypatch.setattr(store, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(store, "_FALLBACK_PATH", tmp_path / "session.json")
    monkeypatch.setattr(store, "_warned_plaintext", False)

    with caplog.at_level(logging.INFO, logger=store.log.name):
        store.save({"uid": "u1", "refresh_token": "RT-1"})
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("filesystem ACLs only" in r.message for r in caplog.records)
