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
    assert h == tmp_path / ".hermes" / "skills" / "research" / "sr"
    assert o == tmp_path / ".openclaw" / "workspace" / "skills" / "sr"


def test_dir_leaf_matches_frontmatter_name():
    # THE INVARIANT (2026-06-11 E2E failure): the gateway advertises a skill by
    # its frontmatter `name:` but LOADS it by directory name — a mismatch makes
    # the skill unloadable ("Skill 'sr' not found") and the model then tries to
    # do the research itself in-chat. Every runtime's install leaf must equal
    # the bundled frontmatter name, forever.
    fm = connect._frontmatter_name(connect.skill_src_dir() / "SKILL.md")
    assert fm == "sr"
    for rt, rel in connect.RUNTIMES.items():
        assert rel.name == fm, f"{rt} installs to {rel} but the skill is named {fm!r}"


def test_install_rejects_leaf_name_drift(tmp_path, monkeypatch):
    # If someone renames the frontmatter (or the RUNTIMES leaf) without the
    # other, the install must fail loudly — not produce an unloadable skill.
    monkeypatch.setitem(connect.RUNTIMES, "hermes",
                        connect.RUNTIMES["hermes"].parent / "wrong-leaf")
    with pytest.raises(RuntimeError, match="frontmatter name"):
        connect.install("hermes", home=tmp_path)


def test_install_prunes_legacy_super_research_dir(tmp_path):
    # Upgrade path: a pre-rename install at .../research/super-research must be
    # removed on re-connect, or the gateway sees two skills advertising "sr".
    legacy = tmp_path / ".hermes" / "skills" / "research" / "super-research"
    (legacy / "scripts").mkdir(parents=True)
    (legacy / "SKILL.md").write_text("---\nname: sr\n---\n", encoding="utf-8")
    (legacy / "scripts" / "sr.py").write_text("# old", encoding="utf-8")
    connect.install("hermes", home=tmp_path)
    assert not legacy.exists()  # stale copy pruned
    assert connect.verify(tmp_path / ".hermes" / "skills" / "research" / "sr")


def test_uninstall_sweeps_legacy_leaf_too(tmp_path):
    # disconnect on NEW code must clean an OLD install (user upgraded without
    # ever re-connecting) — both leaves go.
    legacy = tmp_path / ".hermes" / "skills" / "research" / "super-research"
    (legacy / "scripts").mkdir(parents=True)
    (legacy / "SKILL.md").write_text("x", encoding="utf-8")
    assert connect.uninstall("hermes", home=tmp_path) is True
    assert not legacy.exists()


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


def test_uninstall_refuses_non_skill_custom_dest(tmp_path):
    # A mistyped --dest pointing at an unrelated (e.g. runtime config) dir must NOT
    # be rmtree'd — it isn't named super-research and doesn't verify as our skill.
    victim = tmp_path / "runtime-config"
    victim.mkdir()
    (victim / "important.json").write_text("{}", encoding="utf-8")
    assert connect.uninstall("hermes", dest=victim) is False
    assert victim.exists() and (victim / "important.json").exists()


def test_uninstall_removes_verified_custom_dest(tmp_path):
    # A custom-named dest that IS our skill (verifies) is still removable.
    dest = tmp_path / "weird-name"
    connect.install("hermes", dest=dest)
    assert connect.verify(dest)
    assert connect.uninstall("hermes", dest=dest) is True
    assert not dest.exists()


def test_uninstall_removes_own_leaf_even_if_partial(tmp_path):
    # The standard skill leaf (current or legacy name) is cleaned even when
    # half-installed.
    for leaf in ("sr", "super-research"):
        dest = tmp_path / leaf
        dest.mkdir()
        (dest / "SKILL.md").write_text("x", encoding="utf-8")  # no scripts/sr.py → verify False
        assert connect.verify(dest) is False
        assert connect.uninstall("hermes", dest=dest) is True
        assert not dest.exists()


def test_looks_containerized_false_off_linux(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    assert connect.looks_containerized() is False
    monkeypatch.setattr(connect.sys, "platform", "darwin")
    assert connect.looks_containerized() is False


def test_looks_containerized_false_without_markers(monkeypatch):
    # Mocked-linux on a host with no /.dockerenv or /proc/1/cgroup → False (best-effort).
    monkeypatch.setattr(connect.sys, "platform", "linux")
    assert connect.looks_containerized() is False


def test_install_then_uninstall_roundtrip_at_runtime_path(tmp_path):
    # End-to-end at the real runtime-relative path (under a fake home).
    connect.install("hermes", home=tmp_path)
    target = connect.runtime_dest("hermes", home=tmp_path)
    assert connect.verify(target)
    assert connect.uninstall("hermes", home=tmp_path) is True
    assert not target.exists()


# ── streaming watchdog: connect drops it in HERMES_HOME/scripts (hermes only) ──

def test_install_drops_stream_script_in_hermes_scripts(tmp_path):
    # A standard-path hermes install also places the cron watchdog under
    # HERMES_HOME/scripts so the /sr skill can arm a `no_agent` cron job by name.
    connect.install("hermes", home=tmp_path)
    poll = tmp_path / ".hermes" / "scripts" / "sr_attention_poll.py"
    assert poll.is_file()
    # a stale de-dup state from a prior session must be swept on disconnect so a
    # re-connect + re-arm starts from a clean silent baseline (no phase replay)
    state = tmp_path / ".hermes" / "scripts" / ".sr_stream_state.json"
    state.write_text("{}", encoding="utf-8")
    assert connect.uninstall("hermes", home=tmp_path) is True
    assert not poll.exists() and not state.exists()  # disconnect tears both down


def test_uninstall_removes_sr_stream_cron_job(tmp_path):
    # disconnect must also remove the gateway `sr-stream` cron job — else it
    # orphan-fires every tick erroring on the now-removed script (the spam bug).
    import json
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(json.dumps({
        "jobs": [
            {"name": "memory-dreaming", "enabled": False},
            {"name": "sr-stream", "script": "sr_attention_poll.py", "enabled": True},
        ],
        "updated_at": 1,
    }), encoding="utf-8")
    connect.uninstall("hermes", home=tmp_path)
    data = json.loads((cron / "jobs.json").read_text(encoding="utf-8"))
    names = [j["name"] for j in data["jobs"]]
    assert "sr-stream" not in names      # ours removed
    assert "memory-dreaming" in names    # the user's other jobs preserved
    assert data["updated_at"] == 1       # sibling top-level keys untouched


def test_remove_stream_cron_return_contract(tmp_path):
    # Returns True only when jobs.json is CONFIRMED free of watchdog jobs (safe to
    # delete the script); False when it can't confirm (so the caller keeps it).
    assert connect._remove_stream_cron(tmp_path) is True  # no cron dir → nothing references the script
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text("not json", encoding="utf-8")
    assert connect._remove_stream_cron(tmp_path) is False  # corrupt → can't confirm → keep the script
    assert (cron / "jobs.json").read_text(encoding="utf-8") == "not json"  # left as-is, no raise
    import json
    (cron / "jobs.json").write_text(json.dumps({"jobs": [{"name": "memory-dreaming"}]}), encoding="utf-8")
    assert connect._remove_stream_cron(tmp_path) is True  # no watchdog job present → already clean


def test_uninstall_sweeps_per_chat_shims_and_state(tmp_path):
    # #819: arm-stream generates per-chat shims (sr_poll_<slug>.py) + state files
    # (.sr_poll_<slug>.state.json). Disconnect must sweep ALL of them, not just
    # the shared watchdog — else an orphaned shim keeps firing after disconnect.
    connect.install("hermes", home=tmp_path)
    scripts = tmp_path / ".hermes" / "scripts"
    (scripts / "sr_poll_telegram_abc123.py").write_text("# shim\n", encoding="utf-8")
    (scripts / ".sr_poll_telegram_abc123.state.json").write_text("{}", encoding="utf-8")
    (scripts / "sr_poll_whatsapp_def456.py").write_text("# shim\n", encoding="utf-8")
    # an unrelated user script in the same dir must survive
    (scripts / "my_other_job.py").write_text("# keep me\n", encoding="utf-8")
    assert connect.uninstall("hermes", home=tmp_path) is True
    assert not list(scripts.glob("sr_poll_*.py"))
    assert not list(scripts.glob(".sr_poll_*.state.json"))
    assert (scripts / "my_other_job.py").is_file()  # untouched


def test_remove_stream_cron_drops_per_chat_jobs(tmp_path):
    # Both the shared `sr-stream` job and per-chat `sr-stream-<slug>` jobs (and a
    # job pointing at a generated sr_poll_<slug>.py shim) must be removed.
    import json
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(json.dumps({
        "jobs": [
            {"name": "memory-dreaming", "enabled": False},
            {"name": "sr-stream", "script": "sr_attention_poll.py"},
            {"name": "sr-stream-telegram_abc123", "script": "sr_poll_telegram_abc123.py"},
            {"name": "custom-name", "script": "sr_poll_whatsapp_def456.py"},  # matched by script
        ],
        "updated_at": 7,
    }), encoding="utf-8")
    assert connect._remove_stream_cron(tmp_path) is True  # confirmed jobless after removal
    names = [j["name"] for j in json.loads((cron / "jobs.json").read_text(encoding="utf-8"))["jobs"]]
    assert names == ["memory-dreaming"]  # every watchdog job swept, user job kept


def test_uninstall_keeps_script_when_cron_removal_unconfirmed(tmp_path):
    # The spam guard: if the watchdog cron job removal can't be CONFIRMED (jobs.json
    # corrupt/unreadable), disconnect KEEPS the watchdog script so a surviving job
    # runs it and it exits silently (bridge down) — instead of the scheduler
    # spamming "Script not found" every tick. (Job swept next disconnect / logout.)
    connect.install("hermes", home=tmp_path)
    script = tmp_path / ".hermes" / "scripts" / "sr_attention_poll.py"
    assert script.is_file()
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text("{ corrupt", encoding="utf-8")  # removal can't be confirmed
    connect.uninstall("hermes", home=tmp_path)
    assert script.is_file()  # KEPT — no job-without-script spam window
    # the skill itself is still torn down (disconnect proceeds)
    assert not (tmp_path / connect.RUNTIMES["hermes"]).exists()


def test_uninstall_removes_job_then_script_when_confirmed(tmp_path):
    # Normal path: a clean jobs.json → the watchdog job is removed AND confirmed
    # gone → the script is deleted; unrelated jobs survive.
    import json
    connect.install("hermes", home=tmp_path)
    script = tmp_path / ".hermes" / "scripts" / "sr_attention_poll.py"
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(json.dumps({"jobs": [
        {"name": "sr-stream", "script": "sr_attention_poll.py"},
        {"name": "keep-me", "enabled": True},
    ]}), encoding="utf-8")
    connect.uninstall("hermes", home=tmp_path)
    names = [j["name"] for j in json.loads((cron / "jobs.json").read_text(encoding="utf-8"))["jobs"]]
    assert names == ["keep-me"]      # watchdog job removed, user job kept
    assert not script.exists()       # confirmed jobless → script removed


def test_is_stream_job_classifies():
    assert connect._is_stream_job({"name": "sr-stream"})
    assert connect._is_stream_job({"name": "sr-stream-telegram_abc"})
    assert connect._is_stream_job({"script": "sr_attention_poll.py"})
    assert connect._is_stream_job({"script": "sr_poll_x.py"})
    assert not connect._is_stream_job({"name": "memory-dreaming"})
    assert not connect._is_stream_job({"name": "stream-of-thought"})  # not our prefix
    assert not connect._is_stream_job("nope")


def test_install_dest_override_skips_stream_script(tmp_path):
    # A custom `dest` must NOT write to HERMES_HOME (else a dest test would hit the
    # real ~/.hermes). The cron script belongs only with the standard layout.
    connect.install("hermes", dest=tmp_path / "sr", home=tmp_path)
    assert not (tmp_path / ".hermes" / "scripts" / "sr_attention_poll.py").exists()


def test_openclaw_install_has_no_stream_script(tmp_path):
    # The cron watchdog is hermes-only (OpenClaw has no equivalent scheduler).
    connect.install("openclaw", home=tmp_path)
    assert not (tmp_path / ".hermes" / "scripts" / "sr_attention_poll.py").exists()
    assert not (tmp_path / ".openclaw" / "scripts" / "sr_attention_poll.py").exists()


# ── Target + detect_targets (local + WSL) ────────────────────────────────────

def test_host_os_label(monkeypatch):
    for plat, label in (("win32", "Windows"), ("darwin", "macOS"), ("linux", "Linux")):
        monkeypatch.setattr(connect.sys, "platform", plat)
        assert connect.host_os_label() == label


def test_target_dest_and_where(monkeypatch):
    from pathlib import Path

    # A "local" install renders as the actual host OS (not hardcoded Windows).
    monkeypatch.setattr(connect.sys, "platform", "linux")
    loc = connect.Target("hermes", "local", Path("/home/x"))
    assert loc.dest == Path("/home/x") / connect.RUNTIMES["hermes"]
    assert loc.where == "Linux"
    monkeypatch.setattr(connect.sys, "platform", "win32")
    assert connect.Target("hermes", "local", Path("C:/Users/x")).where == "Windows"
    wsl = connect.Target("openclaw", "wsl", Path("/h/u"), distro="Ubuntu-24.04")
    assert wsl.where == "WSL · Ubuntu-24.04"  # distro shown regardless of host


def test_detect_targets_local(tmp_path):
    assert connect.detect_targets(home=tmp_path, include_wsl=False) == []
    (tmp_path / ".hermes").mkdir()
    targets = connect.detect_targets(home=tmp_path, include_wsl=False)
    assert len(targets) == 1
    assert targets[0].runtime == "hermes" and targets[0].location == "local"
    assert targets[0].home == tmp_path


def test_detect_targets_default_includes_wsl_branch(tmp_path, monkeypatch):
    # Default include_wsl=True path must call the WSL branch and return cleanly
    # (local targets only) when no WSL distro is present — no crash/hang.
    monkeypatch.setattr(connect, "wsl_distros", lambda: [])
    (tmp_path / ".openclaw").mkdir()
    targets = connect.detect_targets(home=tmp_path)  # default include_wsl=True
    assert [t.runtime for t in targets] == ["openclaw"]
    assert all(t.location == "local" for t in targets)


def test_detect_wsl_targets_off_windows_guard(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    assert connect.detect_wsl_targets() == []  # distros=None off-Windows → []


# ── WSL detection (injected distro list + fake UNC root) ─────────────────────

def test_wsl_user_homes_lists_home_dirs_and_root(tmp_path):
    (tmp_path / "home" / "alice").mkdir(parents=True)
    (tmp_path / "home" / "bob").mkdir(parents=True)
    (tmp_path / "root").mkdir()
    homes = connect.wsl_user_homes("Ubuntu", root=tmp_path)
    names = {p.name for p in homes}
    assert names == {"alice", "bob", "root"}


def test_detect_wsl_targets_finds_runtime(tmp_path):
    # Fake WSL tree: /home/alice/.openclaw exists.
    (tmp_path / "home" / "alice" / ".openclaw").mkdir(parents=True)
    targets = connect.detect_wsl_targets(distros=["Ubuntu-24.04"], root_for=lambda d: tmp_path)
    assert len(targets) == 1
    t = targets[0]
    assert t.runtime == "openclaw" and t.location == "wsl" and t.distro == "Ubuntu-24.04"
    assert t.home == tmp_path / "home" / "alice"
    # dest is the standard relative skill path under the WSL home
    assert t.dest == t.home / connect.RUNTIMES["openclaw"]


def test_detect_wsl_targets_empty_when_no_runtime(tmp_path):
    (tmp_path / "home" / "alice").mkdir(parents=True)  # home exists, no runtime
    assert connect.detect_wsl_targets(distros=["U"], root_for=lambda d: tmp_path) == []


def test_install_into_wsl_target_home(tmp_path):
    # A WSL target's home behaves like any other home for install/uninstall.
    (tmp_path / "home" / "alice" / ".openclaw").mkdir(parents=True)
    t = connect.detect_wsl_targets(distros=["U"], root_for=lambda d: tmp_path)[0]
    connect.install(t.runtime, home=t.home)
    assert connect.verify(t.dest)


def test_wsl_distros_honors_env_override(monkeypatch):
    monkeypatch.setenv(connect.WSL_DISTRO_ENV, "Ubuntu-24.04, Debian ,")
    assert connect.wsl_distros() == ["Ubuntu-24.04", "Debian"]


# ── .wslconfig mirrored-networking parser ────────────────────────────────────

def test_networking_mode_parses_mirrored():
    text = "[wsl2]\nmemory=13GB\nnetworkingMode=mirrored\n"
    assert connect.networking_mode(text) == "mirrored"


def test_networking_mode_ignores_other_sections_and_comments():
    text = "[experimental]\nnetworkingMode=nat\n[wsl2]\n# networkingMode=nat\nswap=4GB\n"
    assert connect.networking_mode(text) is None  # only commented under [wsl2]


def test_networking_mode_case_insensitive():
    assert connect.networking_mode("[WSL2]\nNetworkingMode = Mirrored\n") == "mirrored"


def test_mirrored_networking_enabled(tmp_path):
    assert connect.mirrored_networking_enabled(home=tmp_path) is None  # no .wslconfig
    (tmp_path / ".wslconfig").write_text("[wsl2]\nnetworkingMode=mirrored\n", encoding="utf-8")
    assert connect.mirrored_networking_enabled(home=tmp_path) is True
    (tmp_path / ".wslconfig").write_text("[wsl2]\nnetworkingMode=nat\n", encoding="utf-8")
    assert connect.mirrored_networking_enabled(home=tmp_path) is False


# ── enable_mirrored_networking (the writer) ──────────────────────────────────

def test_enable_creates_file_when_absent(tmp_path):
    changed, p = connect.enable_mirrored_networking(home=tmp_path)
    assert changed is True
    assert p == tmp_path / ".wslconfig"
    assert connect.mirrored_networking_enabled(home=tmp_path) is True
    assert "[wsl2]" in p.read_text(encoding="utf-8")


def test_enable_preserves_existing_keys(tmp_path):
    (tmp_path / ".wslconfig").write_text(
        "[wsl2]\nmemory=13GB\nswap=4GB\n", encoding="utf-8")
    changed, p = connect.enable_mirrored_networking(home=tmp_path)
    assert changed is True
    body = p.read_text(encoding="utf-8")
    # other keys survive AND the new key landed inside [wsl2]
    assert "memory=13GB" in body and "swap=4GB" in body
    assert connect.networking_mode(body) == "mirrored"


def test_enable_is_idempotent(tmp_path):
    (tmp_path / ".wslconfig").write_text(
        "[wsl2]\nnetworkingMode=mirrored\n", encoding="utf-8")
    changed, _ = connect.enable_mirrored_networking(home=tmp_path)
    assert changed is False  # already mirrored → no rewrite, no false "restart WSL"


def test_enable_rewrites_nat_value(tmp_path):
    (tmp_path / ".wslconfig").write_text(
        "[wsl2]\nnetworkingMode=nat\nmemory=8GB\n", encoding="utf-8")
    changed, p = connect.enable_mirrored_networking(home=tmp_path)
    assert changed is True
    body = p.read_text(encoding="utf-8")
    assert connect.networking_mode(body) == "mirrored"
    assert "networkingMode=nat" not in body  # the nat line was replaced, not duplicated
    assert body.count("networkingMode") == 1
    assert "memory=8GB" in body


def test_enable_appends_section_when_no_wsl2(tmp_path):
    (tmp_path / ".wslconfig").write_text(
        "[experimental]\nsparseVhd=true\n", encoding="utf-8")
    changed, p = connect.enable_mirrored_networking(home=tmp_path)
    assert changed is True
    body = p.read_text(encoding="utf-8")
    assert "[experimental]" in body and "sparseVhd=true" in body  # untouched
    assert connect.networking_mode(body) == "mirrored"  # new [wsl2] section added


def test_enable_tolerates_bom(tmp_path):
    # Notepad-style UTF-8 BOM must not break the section match / produce a dup.
    (tmp_path / ".wslconfig").write_bytes(
        b"\xef\xbb\xbf[wsl2]\nmemory=4GB\n")
    changed, p = connect.enable_mirrored_networking(home=tmp_path)
    assert changed is True
    body = p.read_text(encoding="utf-8")
    assert connect.networking_mode(body) == "mirrored"
    assert body.count("[wsl2]") == 1  # didn't append a second section


def test_wsl_shutdown_off_windows_guard(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    ok, msg = connect.wsl_shutdown()
    assert ok is False and "Windows-only" in msg


# ── mirrored-networking port-collision guard (the #225 fortification) ─────────

def test_parse_listening_ports_picks_wanted_tcp_listeners():
    text = (
        "\nActive Connections\n\n"
        "  Proto  Local Address          Foreign Address        State           PID\n"
        "  TCP    127.0.0.1:3000         0.0.0.0:0              LISTENING       37292\n"
        "  TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4\n"
        "  TCP    [::]:8080              [::]:0                 LISTENING       9001\n"
        "  TCP    127.0.0.1:51000        127.0.0.1:3000        ESTABLISHED     1234\n"
        "  UDP    0.0.0.0:5353           *:*                                   2222\n"
    )
    got = connect._parse_listening_ports(text, {3000, 8080, 9999})
    # 3000 + 8080 (incl. the [::] form) picked; 445 not wanted; ESTABLISHED/UDP ignored.
    assert got == {3000: "37292", 8080: "9001"}


def test_parse_listening_ports_first_holder_wins():
    text = (
        "  TCP    127.0.0.1:3000   0.0.0.0:0   LISTENING   111\n"
        "  TCP    [::]:3000        [::]:0      LISTENING   222\n"
    )
    assert connect._parse_listening_ports(text, {3000}) == {3000: "111"}


def test_windows_port_owners_off_windows_is_empty(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    assert connect.windows_port_owners() == {}
