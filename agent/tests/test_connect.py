"""`agent connect` skill installer."""

import pytest

from facade import connect


def test_install_copies_bundle_to_dest(tmp_path):
    dest = tmp_path / "skills" / "super-research"
    target = connect.install("hermes", dest=dest)
    assert target == dest
    assert (dest / "SKILL.md").is_file()
    assert (dest / "scripts" / "sr.py").is_file()
    assert connect.verify(dest)


def test_install_is_idempotent(tmp_path):
    dest = tmp_path / "sr"
    connect.install("hermes", dest=dest)
    connect.install("hermes", dest=dest)  # re-connect must not error
    assert connect.verify(dest)


def test_install_prunes_stale_scripts(tmp_path):
    dest = tmp_path / "sr"
    connect.install("hermes", dest=dest)
    stale = dest / "scripts" / "old_helper.py"
    stale.write_text("# left over from a previous bundle", encoding="utf-8")
    connect.install("hermes", dest=dest)  # re-connect mirrors the bundle
    assert not stale.exists()  # pruned
    assert (dest / "scripts" / "sr.py").is_file()  # current bundle intact


def test_install_unknown_runtime_raises(tmp_path):
    with pytest.raises(ValueError):
        connect.install("nope", dest=tmp_path / "x")


def test_runtime_dest_paths(tmp_path):
    h = connect.runtime_dest("hermes", home=tmp_path)
    o = connect.runtime_dest("openclaw", home=tmp_path)
    assert h == tmp_path / ".hermes" / "skills" / "research" / "super-research"
    assert o == tmp_path / ".openclaw" / "workspace" / "skills" / "super-research"


def test_detect_runtimes(tmp_path):
    assert connect.detect_runtimes(home=tmp_path) == []
    (tmp_path / ".hermes").mkdir()
    assert connect.detect_runtimes(home=tmp_path) == ["hermes"]
    (tmp_path / ".openclaw").mkdir()
    assert set(connect.detect_runtimes(home=tmp_path)) == {"hermes", "openclaw"}


def test_bundle_ships_in_package():
    # The source bundle the installer copies must exist in the package.
    src = connect.skill_src_dir()
    assert (src / "SKILL.md").is_file()
    assert (src / "scripts" / "sr.py").is_file()


def test_uninstall_removes_the_bundle(tmp_path):
    dest = tmp_path / "sr"
    connect.install("hermes", dest=dest)
    assert connect.verify(dest)
    assert connect.uninstall("hermes", dest=dest) is True  # removed
    assert not dest.exists()


def test_uninstall_is_idempotent(tmp_path):
    dest = tmp_path / "sr"
    assert connect.uninstall("hermes", dest=dest) is False  # nothing there → no-op
    connect.install("hermes", dest=dest)
    assert connect.uninstall("hermes", dest=dest) is True
    assert connect.uninstall("hermes", dest=dest) is False  # second time → no-op


def test_uninstall_unknown_runtime_raises(tmp_path):
    with pytest.raises(ValueError):
        connect.uninstall("nope", dest=tmp_path / "x")


def test_install_then_uninstall_roundtrip_at_runtime_path(tmp_path):
    # End-to-end at the real runtime-relative path (under a fake home).
    connect.install("hermes", home=tmp_path)
    target = connect.runtime_dest("hermes", home=tmp_path)
    assert connect.verify(target)
    assert connect.uninstall("hermes", home=tmp_path) is True
    assert not target.exists()
