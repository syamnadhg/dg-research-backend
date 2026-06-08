"""Non-secret prefs store (selected device)."""

from facade import config, prefs


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "store_dir", lambda: tmp_path)


def test_empty_when_absent(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert prefs.load() == {}
    assert prefs.get_selected_device("u1") is None


def test_set_get_clear_roundtrip(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    prefs.set_selected_device("dev-1", "u1")
    assert prefs.get_selected_device("u1") == "dev-1"
    prefs.set_selected_device("dev-2", "u1")  # overwrite
    assert prefs.get_selected_device("u1") == "dev-2"
    prefs.clear_selected_device()
    assert prefs.get_selected_device("u1") is None
    # clearing again is a no-op, not an error
    prefs.clear_selected_device()


def test_selection_is_uid_bound(monkeypatch, tmp_path):
    # The core isolation property: account B never inherits account A's selection,
    # even with no intervening logout (the file just persists across the swap).
    _isolate(monkeypatch, tmp_path)
    prefs.set_selected_device("dev-A", "uidA")
    assert prefs.get_selected_device("uidA") == "dev-A"
    assert prefs.get_selected_device("uidB") is None  # different account → invisible


def test_legacy_selection_without_uid_ignored(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    prefs.save({"selectedDeviceId": "dev-old"})  # pre-uid-binding shape
    assert prefs.get_selected_device("u1") is None


def test_runtime_roundtrip(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert prefs.get_runtime() is None
    prefs.set_runtime("hermes")
    assert prefs.get_runtime() == "hermes"
    # runtime is independent of the (uid-bound) device selection
    prefs.set_selected_device("dev-1", "u1")
    assert prefs.get_runtime() == "hermes" and prefs.get_selected_device("u1") == "dev-1"


def test_runtime_records_wsl_install_location(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert prefs.get_runtime_home() is None
    prefs.set_runtime("openclaw", home=r"\\wsl.localhost\Ubuntu-24.04\home\me",
                      location="wsl", distro="Ubuntu-24.04")
    assert prefs.get_runtime() == "openclaw"
    assert prefs.get_runtime_home() == r"\\wsl.localhost\Ubuntu-24.04\home\me"
    assert prefs.get_runtime_location() == "wsl"
    assert prefs.get_runtime_distro() == "Ubuntu-24.04"


def test_runtime_windows_clears_stale_distro(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    prefs.set_runtime("openclaw", home=r"\\wsl.localhost\U\home\me", location="wsl", distro="U")
    # Re-connecting to a Windows-local runtime must not inherit the WSL distro.
    prefs.set_runtime("hermes", home="C:\\Users\\me", location="windows")
    assert prefs.get_runtime_location() == "windows"
    assert prefs.get_runtime_distro() is None


def test_corrupt_file_treated_as_empty(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    (tmp_path / "prefs.json").write_text("{not json", encoding="utf-8")
    assert prefs.load() == {}


def test_preserves_other_keys(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    prefs.save({"someOtherKey": 7})
    prefs.set_selected_device("dev-9", "u1")
    data = prefs.load()
    assert data["someOtherKey"] == 7 and data["selectedDeviceId"] == "dev-9"


def test_install_id_is_stable(monkeypatch, tmp_path):
    # The #790 agentSessions doc id: minted once, then stable across calls — so
    # re-login overwrites the SAME agent row rather than accreting new ones.
    _isolate(monkeypatch, tmp_path)
    iid = prefs.get_or_create_install_id()
    assert iid and prefs.get_or_create_install_id() == iid
    # ...and it survives a "logout" (prefs persist; only the keyring blob is wiped)
    assert prefs.load()["installId"] == iid


def test_label_default_and_rename(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert prefs.get_label() == "Super Agent"  # default
    prefs.set_label("Sammy's Agent")
    assert prefs.get_label() == "Sammy's Agent"
    # an empty/blank label falls back to the default — never an empty row label
    prefs.save({**prefs.load(), "agentLabel": ""})
    assert prefs.get_label() == "Super Agent"
