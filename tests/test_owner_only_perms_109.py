"""#538 / N4 / queues root — the research computer's keys and records are
readable by its owner's OS account only.

⛔⛔ WHAT WAS OPEN, MEASURED 2026-09-21 ON THE OWNER'S MAC. `.dg-supervisor.env`
(the API keys) was -rw-r--r--: the seed chmodded it 0600, and then every key
save threw that away, because `tmp.write_text(); tmp.replace(target)` hands the
target the TEMP file's inode at the umask's 0644. ~/.super-research, logs/,
runs/, sessions/, outgoing/ and queues/ were drwxr-xr-x; the support zips and
keystore-audit.log -rw-r--r--. The home is drwxr-x--- with group `staff`, and
every macOS account is in staff — so any other account could read the keys,
other members' uids and every research topic. A wheel is worse: the key file
and queues/ sit in site-packages under a 0755 ~/.local.

⭐ EVERY PIN HERE RUNS UNDER AN EXPLICIT UMASK 022, and the fixture PROVES it:
it writes a probe the way the old code did and asserts the probe came out 0644.
A test that ran under a developer's 077 umask would pass against the broken
code and measure nothing.

⭐ ACCEPT POLARITY, because "chmod everything 000" or "delete the file" would
also leave nothing readable by others. Every narrowing assertion is paired with
"the owner still reads and writes it" and "every byte is still there".
"""
import os
import stat
import sys
from pathlib import Path

import pytest

import research

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode bits; the hook skips Windows by design (pinned below by simulating it)")


def _mode(p) -> int:
    return stat.S_IMODE(os.lstat(p).st_mode)


def _restore_owner_access(d) -> None:
    try:
        os.chmod(d, 0o700)
        entries = list(os.scandir(d))
    except OSError:
        return
    for e in entries:
        if e.is_dir(follow_symlinks=False):
            _restore_owner_access(e.path)


@pytest.fixture(autouse=True)
def _tmp_stays_deletable(tmp_path):
    """⛔ A mutant that forces 0600 onto directories (harness P3) locks the OWNER
    out of tmp_path, and pytest's cleanup then leaves it on the disk for good —
    52 such directories after the first harness run. Hand the x bit back,
    top-down, after every test."""
    yield
    _restore_owner_access(tmp_path)


@pytest.fixture
def umask_022(tmp_path_factory):
    old = os.umask(0o022)
    try:
        probe = tmp_path_factory.mktemp("umask-probe") / "probe"
        probe.write_text("x", encoding="utf-8")
        # The control: a plain write — exactly what the old writers did — comes
        # out readable by everyone here, so a narrowed mode below is the code's.
        assert _mode(probe) == 0o644, "the umask did not take; nothing below would measure"
        yield
    finally:
        os.umask(old)


@pytest.fixture
def install(tmp_path):
    d = tmp_path / "install"
    d.mkdir()
    return d


def _open_file(path: Path, body: str, mode: int = 0o644) -> Path:
    path.write_text(body, encoding="utf-8")
    os.chmod(path, mode)
    return path


def _owner_only_and_usable_file(p) -> None:
    m = _mode(p)
    assert m & 0o077 == 0, f"{p} is {oct(m)} — another OS account can still read it"
    assert m & 0o600 == 0o600, f"{p} is {oct(m)} — the owner lost read/write"
    assert os.access(p, os.R_OK | os.W_OK)


def _owner_only_and_usable_dir(p) -> None:
    m = _mode(p)
    assert m & 0o077 == 0, f"{p} is {oct(m)} — another OS account can still list it"
    assert m & 0o700 == 0o700, f"{p} is {oct(m)} — the owner can no longer use it"


# ── #538: the writers ────────────────────────────────────────────────────────

def test_saving_a_key_takes_other_accounts_off_an_already_open_file(install, umask_022):
    p = _open_file(install / ".dg-supervisor.env",
                   "# header\nANTHROPIC_API_KEY='sk-ant-old'\n")
    assert research._save_api_key_to_env_file("GEMINI_API_KEY", "AIza-new", path=p) is True
    _owner_only_and_usable_file(p)
    body = p.read_text(encoding="utf-8")
    assert "# header" in body
    assert "ANTHROPIC_API_KEY='sk-ant-old'" in body
    assert "GEMINI_API_KEY='AIza-new'" in body


def test_the_first_save_creates_the_file_owner_only(install, umask_022):
    p = install / ".dg-supervisor.env"
    assert research._save_api_key_to_env_file("ANTHROPIC_API_KEY", "sk-ant-1", path=p) is True
    _owner_only_and_usable_file(p)
    assert p.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY='sk-ant-1'\n"


def test_clearing_one_key_rewrites_the_other_owner_only(install, umask_022):
    """The clear rewrites the file with every OTHER key still in it — the same
    rename, the same 0644, on a file that still holds a live key."""
    p = _open_file(install / ".dg-supervisor.env",
                   "ANTHROPIC_API_KEY='sk-ant-keep'\nGEMINI_API_KEY='AIza-drop'\n")
    assert research._clear_api_key_from_env_file("GEMINI_API_KEY", path=p) is True
    _owner_only_and_usable_file(p)
    body = p.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY='sk-ant-keep'" in body
    assert "GEMINI_API_KEY" not in body


def test_the_key_is_never_in_a_file_others_can_read_even_mid_write(install, umask_022, monkeypatch):
    """The old `.tmp` held the key at 0644 for the whole write. Look at the temp
    at the one moment it is guaranteed to exist — as it is renamed."""
    seen = []
    real_replace = os.replace

    def spy(src, dst, *a, **kw):
        seen.append((_mode(src), Path(src).read_text(encoding="utf-8")))
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", spy)
    p = install / ".dg-supervisor.env"
    assert research._save_api_key_to_env_file("GEMINI_API_KEY", "AIza-inflight", path=p) is True
    assert seen, "the writer never renamed anything — nothing was measured"
    mode, body = seen[-1]
    assert "AIza-inflight" in body
    assert mode & 0o077 == 0, f"the key sat in a {oct(mode)} temp while it was written"


def test_a_save_that_fails_leaves_no_key_bearing_temp_behind(install, umask_022, monkeypatch):
    p = _open_file(install / ".dg-supervisor.env", "ANTHROPIC_API_KEY='sk-ant-old'\n", mode=0o600)

    def refuse(src, dst, *a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    assert research._save_api_key_to_env_file("GEMINI_API_KEY", "AIza-lost", path=p) is False
    assert sorted(x.name for x in install.iterdir()) == [".dg-supervisor.env"]
    assert p.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY='sk-ant-old'\n"


def test_the_seed_is_owner_only_from_its_first_byte(install, umask_022, monkeypatch):
    """⚠ A GUARD, NOT A MEASUREMENT: the old seed already chmodded 0600 after
    its write. It is here because the seed now goes through the shared writer,
    and a revert to a plain write must fail somewhere."""
    target = install / ".dg-supervisor.env"
    monkeypatch.setattr(research, "_SUPERVISOR_ENV_FILE_DEFAULT_PATH", target)
    assert research._seed_env_file_if_missing() is True
    _owner_only_and_usable_file(target)
    example = Path(research.__file__).parent / "scripts" / "dg-supervisor.env.example"
    assert target.read_text(encoding="utf-8") == example.read_text(encoding="utf-8-sig")


def test_the_pair_and_unpair_consumers_write_the_default_file_owner_only(install, umask_022,
                                                                        monkeypatch):
    """A tested helper is not a tested consumer: `--pair` Stage 4 and the legacy
    migration call `_save_api_key_local`, `--unpair --deep` calls
    `_clear_api_key_local`, and both resolve the DEFAULT path themselves."""
    p = _open_file(install / ".dg-supervisor.env", "OTHER_KEY='other'\n")
    monkeypatch.setattr(research, "_SUPERVISOR_ENV_FILE_DEFAULT_PATH", p)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert research._save_api_key_local("ANTHROPIC_API_KEY", "sk-ant-pair") is True
    _owner_only_and_usable_file(p)
    os.chmod(p, 0o644)
    assert research._clear_api_key_local("OTHER_KEY") is True
    _owner_only_and_usable_file(p)
    assert p.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY='sk-ant-pair'\n"


# ── the one-path narrower ────────────────────────────────────────────────────

def test_narrowing_takes_only_group_and_other_bits(tmp_path, umask_022):
    d = tmp_path / "d"
    d.mkdir()
    os.chmod(d, 0o755)
    f = _open_file(tmp_path / "f", "body", 0o644)
    x = _open_file(tmp_path / "x", "#!/bin/sh\n", 0o755)
    for p in (d, f, x):
        research._owner_only(p)
    # A directory keeps its x bit, or the owner could not enter it.
    assert _mode(d) == 0o700
    assert _mode(f) == 0o600
    # The owner's own bits are theirs: an executable stays executable.
    assert _mode(x) == 0o700
    assert f.read_text(encoding="utf-8") == "body"


# ── the boot hook ────────────────────────────────────────────────────────────

@pytest.fixture
def machine(tmp_path, monkeypatch, umask_022):
    """A computer the way earlier builds left it: every path open to others."""
    install = tmp_path / "install"
    install.mkdir()
    state = tmp_path / "home" / ".super-research"
    logs = state / "logs"
    queues = install / "queues"
    files = {
        install / ".dg-supervisor.env": "DG_PERMS_109_KEY='sk-live'\n",
        install / ".dg-supervisor.env.tmp": "DG_PERMS_109_KEY='sk-stale'\n",
        state / "keystore-audit.log": "wipe at 2026-09-06\n",
        state / "selfheal-audit.log": "heal at 2026-09-06\n",
        logs / "backend.log": "supervisor up\n",
        logs / "runs" / "chat_1_1" / "run.log": "Firestore bridge active: users/uid-bob/researches/r1\n",
        logs / "runs" / "chat_1_1" / "meta.json": '{"submitterUid": "uid-bob"}\n',
        logs / "outgoing" / "support-ABCD1234.zip": "PK zip bytes\n",
        logs / "sessions" / "pair_20260921T0000.log": "pair session\n",
        queues / "kalki_20260920_000847" / "brief.md": "a topic brief\n",
    }
    for p, body in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        _open_file(p, body)
    dirs = [state, logs, logs / "runs", logs / "runs" / "chat_1_1", logs / "outgoing",
            logs / "sessions", queues, queues / "kalki_20260920_000847"]
    for d in dirs:
        os.chmod(d, 0o755)
    monkeypatch.setattr(research, "_SUPERVISOR_ENV_FILE_DEFAULT_PATH", install / ".dg-supervisor.env")
    monkeypatch.setattr(research, "_STATE_DIR", state)
    monkeypatch.setattr(research, "_queues_root", lambda: queues)
    return {"install": install, "state": state, "logs": logs, "queues": queues,
            "files": files, "tmp": tmp_path}


def _narrowed(m) -> None:
    """Every path the hook owns is owner-only, still usable, and untouched."""
    f = m["files"]
    expected_files = [p for p in f if m["queues"] not in p.parents]
    for p in expected_files:
        _owner_only_and_usable_file(p)
    for d in (m["state"], m["logs"], m["logs"] / "runs", m["logs"] / "runs" / "chat_1_1",
              m["logs"] / "outgoing", m["logs"] / "sessions", m["queues"]):
        _owner_only_and_usable_dir(d)
    for p, body in f.items():
        assert p.read_text(encoding="utf-8") == body, f"{p} was changed or emptied"


def test_boot_hook_takes_other_accounts_off_everything_already_there(machine):
    assert research._harden_owner_only_paths() is None
    _narrowed(machine)


def test_boot_hook_creates_a_missing_queues_root_owner_only(machine):
    """A worker makes queues/ on its first claim, AFTER boot — so narrowing only
    what exists would leave a fresh install's run folders open for the life of
    its first serve."""
    q = machine["queues"]
    for p in sorted(q.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    q.rmdir()
    research._harden_owner_only_paths()
    assert q.is_dir()
    _owner_only_and_usable_dir(q)
    # And a worker's later mkdir(exist_ok=True) keeps what the hook made.
    q.mkdir(parents=True, exist_ok=True)
    _owner_only_and_usable_dir(q)


# ── the sudo'd first command ────────────────────────────────────────────────

def _remove_queues(q) -> None:
    """The wheel ships no queues/ — pyproject excludes it — so this is what a
    fresh install looks like before its first claim."""
    for p in sorted(q.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    q.rmdir()


def _the_hook_ran_past_queues(m) -> None:
    """⛔ The whole hook is wrapped in `except Exception: pass`, so "queues/ was
    not created" is also what a hook that DIED before the mkdir looks like. The
    logs walk is the step AFTER the queues block: if the support zip came out
    narrowed, the queues decision was reached and taken."""
    _owner_only_and_usable_file(m["logs"] / "outgoing" / "support-ABCD1234.zip")


def test_a_command_run_under_sudo_creates_no_queues_root_the_owner_cannot_use(
        machine, monkeypatch):
    """⛔⛔ THE PIN. The installers warn against `sudo` and people still use it.
    One sudo'd command before the first real run used to leave
    <site-packages>/queues root-owned at 0700 — and then every run as the actual
    user fails to make a run folder in it, for good. Leave it to the worker."""
    q = machine["queues"]
    _remove_queues(q)
    # ⛔ Only this one patch comes off below — `monkeypatch.undo()` would take
    # the fixture's `_queues_root` with it and point the hook at the real repo.
    real_geteuid = os.geteuid
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    research._harden_owner_only_paths()

    assert not q.exists(), (
        "a root-owned queues/ was created in an install this account owns")
    _the_hook_ran_past_queues(machine)
    # And the run that comes after, as the real user, still gets it.
    monkeypatch.setattr(os, "geteuid", real_geteuid)
    research._harden_owner_only_paths()
    _owner_only_and_usable_dir(q)


def test_a_sudo_run_still_narrows_a_queues_root_that_is_already_there(
        machine, monkeypatch):
    """⭐ ACCEPT POLARITY. Only the CREATE is conditional: a chmod makes nothing,
    and the owner's existing 0755 folder of topic-named runs is exactly what the
    hook is for. Skipping the whole block under sudo would lose that."""
    q = machine["queues"]
    os.chmod(q, 0o755)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    research._harden_owner_only_paths()

    _owner_only_and_usable_dir(q)
    _the_hook_ran_past_queues(machine)


def test_the_account_that_owns_the_install_creates_its_own_queues_root(
        machine, monkeypatch):
    """⭐ ACCEPT POLARITY, and the reason the test is the install directory's
    OWNER and not "is this root". An install that really is root's, run as root,
    is the same account owning the same tree: it must still get its queues/."""
    q = machine["queues"]
    _remove_queues(q)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(q.parent).st_uid)

    research._harden_owner_only_paths()

    assert q.is_dir()
    _owner_only_and_usable_dir(q)


def test_an_install_that_belongs_to_another_account_is_not_populated(
        machine, monkeypatch):
    """Nothing is created in a tree this account does not own, whoever we are —
    the mkdir would have failed there anyway, and the run folders belong to
    whichever account the workers actually run as."""
    q = machine["queues"]
    _remove_queues(q)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(q.parent).st_uid + 1)

    research._harden_owner_only_paths()

    assert not q.exists()
    _the_hook_ran_past_queues(machine)


def test_boot_hook_never_re_permissions_what_a_link_points_at(machine):
    outside = machine["tmp"] / "elsewhere"
    outside.mkdir()
    os.chmod(outside, 0o755)
    shared = _open_file(outside / "shared.txt", "someone else's\n")
    inner = outside / "inner"
    inner.mkdir()
    os.chmod(inner, 0o755)
    deep = _open_file(inner / "deep.txt", "deep\n")
    logs = machine["logs"]
    os.symlink(shared, logs / "linked.log")
    os.symlink(inner, logs / "linked-dir")
    research._harden_owner_only_paths()
    assert _mode(shared) == 0o644
    assert _mode(outside) == 0o755
    assert _mode(inner) == 0o755
    assert _mode(deep) == 0o644
    assert (logs / "linked.log").is_symlink() and (logs / "linked-dir").is_symlink()
    _narrowed(machine)


def test_one_path_that_refuses_does_not_stop_the_rest(machine, monkeypatch):
    env_file = machine["install"] / ".dg-supervisor.env"
    real_chmod = os.chmod

    def picky(path, mode, *a, **kw):
        if Path(path) == env_file:
            raise PermissionError("not yours")
        return real_chmod(path, mode, *a, **kw)

    monkeypatch.setattr(os, "chmod", picky)
    research._harden_owner_only_paths()
    assert _mode(env_file) == 0o644
    for p in machine["files"]:
        if p != env_file and machine["queues"] not in p.parents:
            _owner_only_and_usable_file(p)
    _owner_only_and_usable_dir(machine["logs"] / "outgoing")
    _owner_only_and_usable_dir(machine["queues"])


def test_boot_hook_never_raises_into_the_command(machine, monkeypatch):
    def broken_walk(*a, **kw):
        raise RuntimeError("filesystem went away")

    monkeypatch.setattr(os, "walk", broken_walk)
    assert research._harden_owner_only_paths() is None
    # What came before the failure was still done.
    _owner_only_and_usable_file(machine["install"] / ".dg-supervisor.env")
    _owner_only_and_usable_dir(machine["queues"])


def test_windows_is_skipped(machine, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    q = machine["queues"]
    os.chmod(q, 0o755)
    research._harden_owner_only_paths()
    assert _mode(machine["install"] / ".dg-supervisor.env") == 0o644
    assert _mode(machine["logs"] / "outgoing" / "support-ABCD1234.zip") == 0o644
    assert _mode(q) == 0o755


def test_queues_root_is_the_folder_the_workers_write(monkeypatch):
    assert research._queues_root() == Path(research.__file__).parent / "queues"
    assert research._queues_root() == research._worker_lock_path(1).parent


# ── the consumer: main() ─────────────────────────────────────────────────────

def _run_main(monkeypatch, argv):
    for name in ("_install_stdlib_log_bridge", "_install_crash_log_hook",
                 "_migrate_state_to_home", "_warn_if_restart_pending",
                 "_migrate_legacy_api_keys"):
        monkeypatch.setattr(research, name, lambda *a, **kw: None)
    monkeypatch.setattr(research.tm, "flush_in_background", lambda *a, **kw: None)
    reached = []
    monkeypatch.setattr(research, "run_commands_help", lambda: reached.append(True))
    # The default env file is LOADED by main; pre-set its key so the loader
    # leaves os.environ alone and monkeypatch restores it afterwards.
    monkeypatch.setenv("DG_PERMS_109_KEY", "preset")
    monkeypatch.setattr(sys, "argv", ["research.py", *argv])
    research.main()
    assert reached == [True], "main() never reached dispatch — the test measured nothing"


def test_every_command_passes_through_the_hook_before_dispatch(machine, monkeypatch):
    """`--help` is the cheapest command there is, and it still hardens: the call
    sits above every dispatch branch, so every command inherits it."""
    _run_main(monkeypatch, ["--help"])
    _narrowed(machine)


def test_a_custom_env_file_is_left_to_its_owner(machine, monkeypatch):
    custom = _open_file(machine["tmp"] / "team.env", "# a file the user pointed us at\n")
    _run_main(monkeypatch, ["--env-file", str(custom), "--help"])
    assert _mode(custom) == 0o644
    assert custom.read_text(encoding="utf-8") == "# a file the user pointed us at\n"
    # The default file is still ours, whatever else was named.
    _owner_only_and_usable_file(machine["install"] / ".dg-supervisor.env")
