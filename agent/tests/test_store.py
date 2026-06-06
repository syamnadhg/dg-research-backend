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
