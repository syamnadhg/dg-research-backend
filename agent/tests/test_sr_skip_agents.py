"""#899 (agent) — "skip Claude in P2" from chat works like the app's per-agent
Research toggles.

Live 2026-07-02: "Skip Claude in P2 and Skip youtube and email phases" → the
agent could only do P4/P5 off and answered "Claude isn't exposed as a
separately skippable phase". The app's tile toggles each P2 agent individually
(pipelineConfig.agents[k]=false + a mid-run {action:"config"} command), so the
chat path must reach the same writes: `sr.py skip claude` → POST /skip
{agents:["claude"]} → bridge patches pipelineConfig.agents (+ skippedPhases 2
when all three go off — FE parity) and, on an ongoing run, mirrors the FE
tile's config command (+ skip_agent for a run already inside P2).
"""
import importlib.util
import sys
from pathlib import Path

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_skip_under_test", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_skip_under_test"] = sr
_spec.loader.exec_module(sr)


def _argv(text):
    argv, lines = sr._nl_resolve(text)
    assert argv is not None, f"expected a command for {text!r}, got note: {lines}"
    return argv


# ── NL routing: agent names reach `skip` ──────────────────────────────────────

def test_skip_claude_in_p2_routes_to_skip_claude():
    # The live ask, verbatim shape.
    assert _argv("Skip Claude in P2") == ["skip", "claude"]


def test_skip_agent_and_phase_mix():
    argv = _argv("skip the video and drop claude")
    assert argv[0] == "skip"
    assert "video" in argv and "claude" in argv


def test_drop_chatgpt_from_the_research():
    argv = _argv("drop ChatGPT from the research")
    assert argv[0] == "skip"
    assert "chatgpt" in argv


def test_research_without_claude_gets_honest_two_step():
    # No fire-time agent flag exists — the resolver must NOT leak "without
    # claude" into the topic; it offers start-now-trim-after instead.
    argv, lines = sr._nl_resolve("research quantum sensors without claude")
    assert argv is None
    note = " ".join(lines)
    assert "Claude" in note and "quantum sensors" in note


# ── review catches: the skip route must never fire from mere agent mentions ──

def _not_skip(text):
    argv, lines = sr._nl_resolve(text)
    assert not (argv and argv[0] == "skip"), f"{text!r} wrongly routed to {argv}"


def test_questions_about_agents_are_not_skip_orders():
    _not_skip("why is there no claude output?")
    _not_skip("did claude skip anything?")
    _not_skip("is gemini done? no rush")


def test_device_phrasings_with_agent_names_stay_device_verbs():
    # "remove claude's laptop" must reach the device-remove CONFIRM, and a
    # device named with an agent word must never silently drop the P2 agent.
    argv, lines = sr._nl_resolve("remove claude's laptop")
    assert argv is None and "device" in " ".join(lines).lower()
    _not_skip("remove the claude-pc device")


def test_agent_noun_needs_adjacent_verb():
    _not_skip("no word from claude yet")


def test_compound_phase_noun_wins_over_agent():
    # "the gemini video" is the video, not the Gemini agent.
    assert _argv("skip the gemini video") == ["skip", "video"]


def test_research_ask_with_agent_exclusion_prefix_is_not_a_skip():
    # "no gpt needed, research X" — never eat the research ask AND drop
    # ChatGPT; falling through to a safe ask is the acceptable outcome.
    _not_skip("no gpt needed, research the future of solar panels")


def test_skip_multiple_agents():
    argv = _argv("skip claude and gemini")
    assert argv[0] == "skip" and "claude" in argv and "gemini" in argv


# ── skip-arg parsing: names → agents payload ─────────────────────────────────

def test_skip_agent_name_map():
    assert sr._SKIP_AGENTS["claude"] == "claude"
    assert sr._SKIP_AGENTS["gpt"] == "chatgpt"
    assert sr._SKIP_AGENTS["openai"] == "chatgpt"
    assert sr._SKIP_AGENTS["gemini"] == "gemini"


def test_skip_posts_agents_payload(monkeypatch):
    calls = {}

    def fake_post(path, payload=None, **kw):
        calls["path"] = path
        calls["payload"] = payload
        return 200, {"ok": True, "runId": "r1", "skipped": [], "agentsOff": ["claude"],
                     "commandSent": True}

    monkeypatch.setattr(sr, "_post", fake_post)
    monkeypatch.setattr(sr, "_fetch_runs", lambda **kw: (200, {}, [
        {"runId": "r1", "title": "German Shepard", "status": "ongoing", "phase": 1},
    ]))
    printed = []
    monkeypatch.setattr(sr, "_emit", lambda body, as_json, lines, code=0: printed.extend(lines) or code)

    args = type("A", (), {"phases": ["claude"], "run": "", "json": False})()
    rc = sr.cmd_skip(args)
    assert rc == 0
    assert calls["path"].endswith("/skip")
    assert calls["payload"] == {"agents": ["claude"]}
    out = " ".join(printed)
    assert "Claude" in out and "Research (P2)" in out
    assert "applied to the running pipeline" in out


def test_skip_unknown_word_names_agents_in_the_error(monkeypatch):
    printed = []
    monkeypatch.setattr(sr, "_fetch_runs", lambda **kw: (200, {}, [
        {"runId": "r1", "title": "T", "status": "ongoing"},
    ]))
    monkeypatch.setattr(sr, "_emit", lambda body, as_json, lines, code=0: printed.extend(lines) or code)
    args = type("A", (), {"phases": ["nonsense"], "run": "", "json": False})()
    assert sr.cmd_skip(args) == 1
    assert "chatgpt/gemini/claude" in " ".join(printed)


# ── watchdog self-heal: stale/missing state + live agent run → re-arm lines ──

def test_stream_health_rearm_when_state_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)  # no state file here
    monkeypatch.setattr(sr, "_prepare_stream_arm",
                        lambda: (["ARM ME", "  cronjob: create …"], {}, 0))
    runs = [{"runId": "r1", "status": "ongoing", "viaAgent": True}]
    # The re-arm directive is wrapped under the do-not-relay marker (assistant
    # acts on it silently; it never reaches the user).
    assert sr._stream_health_lines(runs) == sr._agent_directive_block(
        ["ARM ME", "  cronjob: create …"])
    assert sr._AGENT_ONLY_MARKER in sr._stream_health_lines(runs)


def test_stream_health_quiet_when_ticking(monkeypatch, tmp_path):
    state = tmp_path / ".sr_stream_state.json"
    state.write_text("{}", encoding="utf-8")  # fresh mtime = ticking watchdog
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    runs = [{"runId": "r1", "status": "ongoing", "viaAgent": True}]
    assert sr._stream_health_lines(runs) == []


def test_stream_health_quiet_without_agent_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    # Live but NOT via-agent (web-app run) → the watchdog wouldn't stream it;
    # no nag. Finished agent run → same.
    runs = [{"runId": "r1", "status": "ongoing", "viaAgent": False},
            {"runId": "r2", "status": "complete", "viaAgent": True}]
    assert sr._stream_health_lines(runs) == []


def test_stream_health_rearm_on_needs_attention(monkeypatch, tmp_path):
    # The live failure shape: a blocked run needing the user, watchdog dead.
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: (["ARM"], {}, 0))
    runs = [{"runId": "r1", "status": "errored", "viaAgent": True,
             "needsAttention": True, "attention": "ChatGPT stopped responding"}]
    assert sr._stream_health_lines(runs) == sr._agent_directive_block(["ARM"])


def test_stream_health_scoped_chat_ignores_other_chats_runs(monkeypatch, tmp_path):
    # Review catch: a status ask from a DIFFERENT chat must not arm a scoped
    # watchdog that can never see the run (it would poll forever, posting
    # nothing, and never tear down).
    monkeypatch.setattr(sr, "_origin_from_env",
                        lambda: {"platform": "whatsapp", "chat_id": "B", "thread_id": ""})
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    runs = [{"runId": "r1", "status": "ongoing", "viaAgent": True,
             "chatOrigin": {"platform": "whatsapp", "chat_id": "A"}}]
    assert sr._stream_health_lines(runs) == []


def test_stream_health_scoped_chat_rearms_for_its_own_run(monkeypatch, tmp_path):
    monkeypatch.setattr(sr, "_origin_from_env",
                        lambda: {"platform": "whatsapp", "chat_id": "A", "thread_id": ""})
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: (["ARM"], {}, 0))
    runs = [{"runId": "r1", "status": "ongoing", "viaAgent": True,
             "chatOrigin": {"platform": "WhatsApp", "chat_id": "A"}}]
    assert sr._stream_health_lines(runs) == sr._agent_directive_block(["ARM"])


# ── stale chat-side copy tell ────────────────────────────────────────────────

def test_skill_build_matches_package_version():
    # _SKILL_BUILD is the "which copy am I" stamp for cmd_version's stale-copy
    # warning — it must move in lockstep with the package version.
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r'^version = "([^"]+)"$', pyproject, _re.M)
    assert m, "pyproject.toml version not found"
    assert sr._SKILL_BUILD == m.group(1), (
        f"sr.py _SKILL_BUILD ({sr._SKILL_BUILD}) != pyproject version ({m.group(1)}) — "
        "bump them together"
    )
