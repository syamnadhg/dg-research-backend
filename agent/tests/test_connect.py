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


def test_runtime_profiles_back_compat_views_stay_consistent():
    # RUNTIMES / RUNTIME_META are now DERIVED from PROFILES — they must stay
    # byte-identical views so every existing call site keeps working. Pin it.
    assert set(connect.PROFILES) == set(connect.RUNTIMES) == set(connect.RUNTIME_META)
    for name, p in connect.PROFILES.items():
        assert connect.RUNTIMES[name] == p.skill_subpath
        assert connect.RUNTIME_META[name] == p.meta
        assert connect.RUNTIME_META[name] == {"label": p.label, "icon": p.icon, "rgb": p.rgb}
        assert p.skill_subpath.name == "sr"            # dir-leaf invariant, per runtime
    # Listing order is load-bearing (picker/detect_* order) — openclaw, then hermes.
    assert list(connect.PROFILES) == ["openclaw", "hermes"]


def test_chat_armable_scheduler_flag_matches_legacy_hermes_gate():
    # The scheduler install/uninstall gates used to be `runtime == "hermes"`; the
    # refactor routes them through this flag. It MUST stay True for hermes and
    # False for openclaw or the watchdog wiring changes silently.
    assert connect.PROFILES["hermes"].has_chat_armable_scheduler is True
    assert connect.PROFILES["openclaw"].has_chat_armable_scheduler is False


def test_profile_accessor_unknown_runtime_raises():
    assert connect.profile("hermes") is connect.PROFILES["hermes"]
    with pytest.raises(KeyError):
        connect.profile("nope")


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


def test_sweep_orphan_stream_crons_drops_only_shimless_jobs(tmp_path):
    # Self-heal: a per-chat `sr-stream-<slug>` cron whose generated shim is GONE is an
    # orphan (fires "Script not found" every tick) → swept. A cron whose shim is still
    # on disk (a live run's watchdog), the shared `sr-stream` / `sr-update-notice`
    # jobs, and unrelated user jobs are ALL preserved.
    import json
    scripts = tmp_path / ".hermes" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "sr_poll_telegram_live00.py").write_text("# live shim\n", encoding="utf-8")  # present
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(json.dumps({
        "jobs": [
            {"name": "memory-dreaming", "enabled": False},
            {"name": "sr-stream", "script": "sr_attention_poll.py"},         # shared → keep
            {"name": "sr-update-notice", "script": "sr_update_notice.py"},   # daily → keep
            {"name": "sr-stream-telegram_live00", "script": "sr_poll_telegram_live00.py"},  # shim present → keep
            {"name": "sr-stream-telegram_gone11", "script": "sr_poll_telegram_gone11.py"},  # shim gone → ORPHAN
        ],
        "updated_at": 5,
    }), encoding="utf-8")
    assert connect._sweep_orphan_stream_crons(tmp_path) == 1
    data = json.loads((cron / "jobs.json").read_text(encoding="utf-8"))
    names = [j["name"] for j in data["jobs"]]
    assert "sr-stream-telegram_gone11" not in names           # orphan swept
    assert "sr-stream-telegram_live00" in names               # live run's job kept
    assert {"sr-stream", "sr-update-notice", "memory-dreaming"} <= set(names)  # bundle + user jobs kept
    assert data["updated_at"] == 5                            # sibling top-level keys untouched
    assert connect._sweep_orphan_stream_crons(tmp_path) == 0  # idempotent — nothing left to sweep


def test_sweep_orphan_stream_crons_safe_when_missing_or_malformed(tmp_path):
    assert connect._sweep_orphan_stream_crons(tmp_path) == 0  # no jobs.json → no-op
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text("not json", encoding="utf-8")
    assert connect._sweep_orphan_stream_crons(tmp_path) == 0  # unreadable → no-op, no raise
    assert (cron / "jobs.json").read_text(encoding="utf-8") == "not json"  # left as-is


def test_install_sweeps_orphan_stream_cron(tmp_path):
    # End-to-end: a standard-path (re)connect / self-update self-heals a stranded
    # per-chat watchdog cron whose shim is gone — the exact live orphan-spam bug
    # (sr-stream-telegram-e639c4e3bb → sr_poll_telegram_e639c4e3bb.py "Script not found").
    import json
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(json.dumps({
        "jobs": [
            {"name": "memory-dreaming"},
            {"name": "sr-stream-telegram_e639c4e3bb", "script": "sr_poll_telegram_e639c4e3bb.py"},
        ],
    }), encoding="utf-8")
    connect.install("hermes", home=tmp_path)  # connect never wrote that shim → orphan
    names = [j["name"] for j in json.loads((cron / "jobs.json").read_text(encoding="utf-8"))["jobs"]]
    assert "sr-stream-telegram_e639c4e3bb" not in names  # orphan swept on connect
    assert "memory-dreaming" in names                    # user job preserved


def test_install_preserves_live_shims(tmp_path):
    # A reconnect / self-update must NOT wipe a live run's watchdog shim + de-dup
    # state (an update shouldn't kill the watchdog mid-run). connect only re-copies
    # the shared bundle scripts into HERMES_HOME/scripts — never the generated shims,
    # and the orphan-sweep only touches CRON entries whose shim is absent.
    connect.install("hermes", home=tmp_path)
    scripts = tmp_path / ".hermes" / "scripts"
    shim = scripts / "sr_poll_telegram_live99.py"
    shim.write_text("# live shim\n", encoding="utf-8")
    state = scripts / ".sr_poll_telegram_live99.state.json"
    state.write_text("{}", encoding="utf-8")
    connect.install("hermes", home=tmp_path)  # re-connect (the self-update path)
    assert shim.is_file() and state.is_file()  # live watchdog survives the redeploy


# ── runtime display name: label the agent with its own name, not "Super Agent" ──

def _write_hermes_config(home, body: str) -> None:
    hd = home / ".hermes"
    hd.mkdir(parents=True, exist_ok=True)
    (hd / "config.yaml").write_text(body, encoding="utf-8")


def test_runtime_display_name_reads_hermes_personality(tmp_path):
    # The active persona key under display: is the runtime's own name.
    _write_hermes_config(tmp_path, (
        "model:\n  timeout: 30\n"
        "display:\n  compact: true\n  personality: rocky\n  resume_display: full\n"
        "personalities:\n  rocky: \"You are Rocky.\"\n"
    ))
    assert connect.runtime_display_name("hermes", home=tmp_path) == "Rocky"


def test_runtime_display_name_normalizes_and_rejects_generic(tmp_path):
    _write_hermes_config(tmp_path, "display:\n  personality: my_helper_bot\n")
    assert connect.runtime_display_name("hermes", home=tmp_path) == "My Helper Bot"
    _write_hermes_config(tmp_path, 'display:\n  personality: "aria"  # active\n')
    assert connect.runtime_display_name("hermes", home=tmp_path) == "Aria"  # quotes + inline comment stripped
    for generic in ("default", "assistant", "Hermes", "agent"):
        _write_hermes_config(tmp_path, f"display:\n  personality: {generic}\n")
        assert connect.runtime_display_name("hermes", home=tmp_path) is None  # placeholder → keep default


def test_runtime_display_name_survives_non_utf8_config(tmp_path):
    # A persona prompt saved in a legacy codepage (cp1252 em-dash 0x97, smart quotes)
    # must NOT crash `agent connect` (UnicodeDecodeError is a ValueError, not OSError).
    # The ASCII display.personality key still resolves.
    hd = tmp_path / ".hermes"
    hd.mkdir(parents=True)
    raw = (b"display:\n  personality: rocky\n"
           b"personalities:\n  rocky: \"Loyal \x97 sharp \x93brilliant\x94.\"\n")  # cp1252 bytes
    (hd / "config.yaml").write_bytes(raw)
    assert connect.runtime_display_name("hermes", home=tmp_path) == "Rocky"  # no raise, name intact


def test_runtime_display_name_preserves_deliberate_capitalization(tmp_path):
    for key, expect in [("rocky", "Rocky"), ("JARVIS", "JARVIS"), ("McKay", "McKay"), ("aria", "Aria")]:
        _write_hermes_config(tmp_path, f"display:\n  personality: {key}\n")
        assert connect.runtime_display_name("hermes", home=tmp_path) == expect


def test_runtime_display_name_none_when_absent_or_not_hermes(tmp_path):
    assert connect.runtime_display_name("hermes", home=tmp_path) is None  # no config.yaml
    _write_hermes_config(tmp_path, "display:\n  compact: true\n")           # no personality key
    assert connect.runtime_display_name("hermes", home=tmp_path) is None
    _write_hermes_config(tmp_path, "display:\n  personality: rocky\n")
    assert connect.runtime_display_name("openclaw", home=tmp_path) is None  # openclaw → keep default


def test_yaml_scalar_under_scopes_to_the_section():
    text = ("top: 1\n"
            "other:\n  personality: wrong\n"          # same key, different section → ignored
            "display:\n  compact: true\n  personality: rocky  # comment\n"
            "next:\n  personality: also_wrong\n")
    assert connect._yaml_scalar_under(text, "display", "personality") == "rocky"
    assert connect._yaml_scalar_under(text, "display", "missing") is None
    assert connect._yaml_scalar_under(text, "absent", "personality") is None


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


def test_wsl_running_distros_honors_env_override(monkeypatch):
    # The pin treats pinned distros as running so tests stay subprocess-free.
    monkeypatch.setenv(connect.WSL_DISTRO_ENV, "Ubuntu-24.04")
    assert connect.wsl_running_distros() == ["Ubuntu-24.04"]


def test_wsl_running_distros_parses_running_list(monkeypatch):
    monkeypatch.delenv(connect.WSL_DISTRO_ENV, raising=False)
    monkeypatch.setattr(connect.sys, "platform", "win32")
    captured = {}

    class _R:
        # UTF-16LE with a BOM + a NUL pad, like real `wsl -l -q --running`.
        stdout = "﻿Ubuntu-24.04\r\n\x00".encode("utf-16-le")

    def _run(cmd, **k):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setattr(connect.subprocess, "run", _run)
    assert connect.wsl_running_distros() == ["Ubuntu-24.04"]
    assert "--running" in captured["cmd"]


# ── WSL delegation (Model A: connect runs inside the distro) ─────────────────

class _Rc:
    def __init__(self, code):
        self.returncode = code


def test_wsl_pipx_available_true_via_login_shell(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return _Rc(0)

    monkeypatch.setattr(connect.subprocess, "run", fake_run)
    assert connect.wsl_pipx_available("Ubuntu-24.04") is True
    a = seen["args"]
    assert a[:4] == ["wsl.exe", "-d", "Ubuntu-24.04", "--"]
    # probe via a login shell, module form so it's true the moment pipx is installed
    assert "bash" in a and "-lc" in a and "python3 -m pipx --version" in a


def test_wsl_pipx_available_false_on_nonzero(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    monkeypatch.setattr(connect.subprocess, "run", lambda *a, **k: _Rc(1))
    assert connect.wsl_pipx_available("U") is False


def test_wsl_pipx_available_off_windows(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    assert connect.wsl_pipx_available("U") is False


def test_wsl_pipx_available_swallows_errors(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")

    def boom(*a, **k):
        raise OSError("no wsl")

    monkeypatch.setattr(connect.subprocess, "run", boom)
    assert connect.wsl_pipx_available("U") is False


def test_ensure_wsl_pipx_noop_when_already_present(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    monkeypatch.setattr(connect, "wsl_pipx_available", lambda d: True)
    ran = []
    monkeypatch.setattr(connect.subprocess, "run", lambda *a, **k: ran.append(a) or _Rc(0))
    assert connect.ensure_wsl_pipx("U") is True
    assert ran == []  # already present → no install attempt


def test_ensure_wsl_pipx_installs_then_succeeds(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    probes = {"n": 0}

    def fake_probe(d):
        probes["n"] += 1
        return probes["n"] > 1  # missing first, present after the install

    monkeypatch.setattr(connect, "wsl_pipx_available", fake_probe)
    seen = {}
    monkeypatch.setattr(connect.subprocess, "run",
                        lambda args, **kw: seen.update(args=args) or _Rc(0))
    assert connect.ensure_wsl_pipx("Ubuntu-24.04") is True
    inner = seen["args"][-1]  # the bash -lc command string
    assert "pip install --user" in inner and "pipx" in inner
    assert "--break-system-packages" in inner  # PEP-668 (Ubuntu 24.04) fallback


def test_ensure_wsl_pipx_false_when_still_missing(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    monkeypatch.setattr(connect, "wsl_pipx_available", lambda d: False)  # never resolves
    monkeypatch.setattr(connect.subprocess, "run", lambda *a, **k: _Rc(0))
    assert connect.ensure_wsl_pipx("U") is False


def test_ensure_wsl_pipx_off_windows(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    assert connect.ensure_wsl_pipx("U") is False


def test_run_agent_in_wsl_builds_login_shell_command(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return _Rc(0)

    monkeypatch.setattr(connect.subprocess, "run", fake_run)
    rc = connect.run_agent_in_wsl("Ubuntu-24.04", "connect", ["--yes", "--no-login"])
    assert rc == 0
    a = seen["args"]
    assert a[:5] == ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash"]
    assert a[5] == "-lc"
    # the in-distro command is the package's own <subcommand> with forwarded flags,
    # prefixed by the continuation marker as an env var (version-safe). connect forces
    # --no-cache so a re-connect pulls the LATEST published build, not a stale pipx-run
    # cache (otherwise a publish wouldn't reach the runtime within pipx's cache window).
    assert a[6] == "SUPER_AGENT_CONNECT_CONTINUED=1 python3 -m pipx run --no-cache superresearch-agent connect --yes --no-login"


def test_run_agent_in_wsl_uses_the_given_subcommand(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    seen = {}
    monkeypatch.setattr(connect.subprocess, "run",
                        lambda args, **kw: seen.update(args=args) or _Rc(0))
    connect.run_agent_in_wsl("Ubuntu-24.04", "disconnect")
    # disconnect is frequent/idempotent — keeps the pipx-run cache for speed (no --no-cache)
    assert seen["args"][6] == "SUPER_AGENT_CONNECT_CONTINUED=1 python3 -m pipx run superresearch-agent disconnect"


def test_run_agent_in_wsl_forces_fresh_resolve_for_run_commands(monkeypatch):
    """serve/resurrect (re)start the bridge, so they must run current code too —
    --no-cache, like connect. status/doctor stay cached (frequent, version-agnostic)."""
    monkeypatch.setattr(connect.sys, "platform", "win32")
    seen = {}
    monkeypatch.setattr(connect.subprocess, "run",
                        lambda args, **kw: seen.update(args=args) or _Rc(0))
    for sub in ("serve", "resurrect"):
        connect.run_agent_in_wsl("U", sub)
        assert "pipx run --no-cache superresearch-agent " + sub in seen["args"][6]
    for sub in ("status", "doctor", "retire"):
        connect.run_agent_in_wsl("U", sub)
        assert "--no-cache" not in seen["args"][6]
        assert "pipx run superresearch-agent " + sub in seen["args"][6]


def test_run_agent_in_wsl_passes_through_returncode(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")
    monkeypatch.setattr(connect.subprocess, "run", lambda *a, **k: _Rc(7))
    assert connect.run_agent_in_wsl("U", "retire") == 7


def test_run_agent_in_wsl_off_windows(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    assert connect.run_agent_in_wsl("U", "connect") == 1


def test_run_agent_in_wsl_swallows_launch_error(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "win32")

    def boom(*a, **k):
        raise FileNotFoundError("wsl.exe missing")

    monkeypatch.setattr(connect.subprocess, "run", boom)
    assert connect.run_agent_in_wsl("U", "connect") == 1
