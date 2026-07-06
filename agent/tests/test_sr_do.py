"""#891 — `sr.py do` deterministic NL fallback.

The 2026-07-01 live chat failures, replayed as fixtures: "Status of the Super
Research?" ran the ACCOUNT status; "Status of Research?" fell through to the
runtime's own tools (git repos!); "Status?" wasn't routed; "add device <code>"
was refused. `do` moves the text→command mapping into code so those phrasings
resolve the same way every time. Resolver-level tests (no bridge needed) +
one dispatch test.
"""
import importlib.util
import sys
from pathlib import Path

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_do_under_test", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_do_under_test"] = sr
_spec.loader.exec_module(sr)


def _argv(text):
    argv, lines = sr._nl_resolve(text)
    assert argv is not None, f"expected a command for {text!r}, got note: {lines}"
    return argv


def _note(text):
    argv, lines = sr._nl_resolve(text)
    assert argv is None, f"expected a note for {text!r}, got command: {argv}"
    return " ".join(lines)


# ── the four live failures (2026-07-01 transcript) ───────────────────────────

def test_live_failure_status_of_the_super_research():
    # Live: ran status-account (sign-in status + update nudge). Must be RUN status.
    assert _argv("Status of the Super Research?") == ["status"]


def test_live_failure_status_of_research():
    # Live: Hermes checked git repos. Must resolve to run status.
    assert _argv("Status of Research?") == ["status"]


def test_live_failure_bare_status():
    # Live: "Up and ready" (runtime's own status). Must be run status.
    assert _argv("Status?") == ["status"]


def test_live_failure_add_device_with_code():
    assert _argv("add device K7XQ-9B2M") == ["device-add", "K7XQ-9B2M"]
    assert _argv("K7XQ-9B2M") == ["device-add", "K7XQ-9B2M"]
    assert _argv("pair my PC, code is MFG8-33UD") == ["device-add", "MFG8-33UD"]
    assert _argv("add device YGXU7WH2") == ["device-add", "YGXU7WH2"]


# ── double-auth guard: sign-in questions = FRESH account check ───────────────

def test_signin_questions_hit_account_status():
    assert _argv("am I signed in?") == ["status-account"]
    assert _argv("are we connected?") == ["status-account"]
    assert _argv("which account is this?") == ["status-account"]


def test_run_status_never_confused_with_account():
    assert _argv("how's it going?") == ["status"]
    assert _argv("progress?") == ["status"]
    assert _argv("results of the EV research") == ["status", "EV"]


# ── the rest of the command surface ──────────────────────────────────────────

def test_research_phrasings():
    assert _argv("research the EV battery market") == ["research", "the EV battery market"]
    assert _argv("Do a Super Research on solid-state batteries") == \
        ["research", "solid-state batteries"]
    assert _argv("deep dive into quantum error correction") == \
        ["research", "quantum error correction"]
    assert _argv("look into Tesla's 2026 margins") == ["research", "Tesla's 2026 margins"]


def test_research_without_topic_asks():
    assert "topic" in _note("do a super research").lower()


def test_stop_is_confirm_first_not_executed():
    note = _note("stop the EV run")
    assert "Stop" in note and "“EV”" in note and "yes" in note.lower()
    assert "stop" in _note("that's enough").lower()


def test_pause_resume_retry_run_directly():
    assert _argv("pause it") == ["pause"]
    assert _argv("resume the Mars run") == ["resume", "Mars"]
    assert _argv("retry") == ["retry"]


def test_skip_phase_words_not_device_remove():
    assert _argv("skip the video and the report") == ["skip", "video", "report"]
    assert _argv("remove the video please") == ["skip", "video"]


def test_devices_verbs():
    assert _argv("which devices do I have?") == ["devices"]
    assert _argv("switch to the office PC") == ["device-use", "office PC"]
    note = _note("remove the old laptop device")
    assert "Unlink" in note and "yes" in note.lower()


def test_podcast_and_lists():
    assert _argv("send me the podcast") == ["podcast"]
    assert _argv('the audio for the "Mars" run') == ["podcast", "Mars"]
    assert _argv("what researches do I have?") == ["list"]
    assert _argv("what's running right now?") == ["updates"]


def test_session_and_maintenance():
    assert _argv("log me in") == ["login"]
    assert "sign out" in _note("log out of super research").lower()
    assert _argv("what version?") == ["version"]
    assert "agent" in _note("update the agent").lower()
    # "update super research" (no agent) → the runtime doesn't update the backend
    # anymore; it redirects to `superresearch --update` on the Research computer.
    n = _note("update super research").lower()
    assert "superresearch --update" in n and "research computer" in n


def test_unmatched_is_a_safe_ask_never_a_guess():
    note = _note("what's the weather like tomorrow")
    assert "research" in note.lower() and "?" in note


# ── round-2 review fixtures: rule-order + false-positive hardening ───────────

def test_research_topics_containing_control_verbs_stay_research():
    # Pre-fix these hit the stop/pause/status/podcast rules and hijacked the
    # request (a "yes" would even have stopped an unrelated in-flight run).
    assert _argv("research how to stop smoking") == ["research", "how to stop smoking"]
    assert _argv("research why airlines cancel flights") == \
        ["research", "why airlines cancel flights"]
    assert _argv("deep dive on the end of moores law") == \
        ["research", "the end of moores law"]
    assert _argv("research the pause feature") == ["research", "the pause feature"]
    assert _argv("research the history of the podcast industry") == \
        ["research", "the history of the podcast industry"]
    assert _argv("research the status of the EV market") == \
        ["research", "the status of the EV market"]
    assert _argv("look into progress in fusion energy") == \
        ["research", "progress in fusion energy"]


def test_bare_research_status_tail_is_still_a_progress_ask():
    assert _argv("research status") == ["status"]


def test_research_with_exclusions_maps_to_run_flags():
    assert _argv("research the EV market without the video") == \
        ["research", "the EV market", "--no-video"]
    assert _argv("research quantum computing, no email") == \
        ["research", "quantum computing", "--no-email"]
    # No research-time flag for the podcast phase → honest two-step ask.
    note = _note("deep dive on solar panels without the podcast")
    assert "solar panels" in note and "yes" in note.lower()


def test_plain_skip_still_works():
    assert _argv("skip the video and the report") == ["skip", "video", "report"]


def test_progress_flavored_update_is_status_not_maintenance():
    # Pre-fix ALL of these returned an update confirm — a reflexive "yes" acted on
    # a progress question. They must resolve to a run STATUS ask.
    assert _argv("update me") == ["status"]
    assert _argv("give me an update") == ["status"]
    assert _argv("any updates?") == ["status"]
    assert _argv("any update on the Tesla research?") == ["status", "Tesla"]
    assert _argv("update me on the Tesla run") == ["status", "Tesla"]


def test_update_routing_agent_vs_backend():
    # "update" / "update the agent" / "upgrade" → confirm the AGENT self-update
    # (the only thing the runtime updates now — no misroute to a backend that
    # isn't on this host).
    for phrase in ("update", "upgrade", "update the agent", "update yourself",
                   "update the super research agent"):
        assert "agent" in _note(phrase).lower(), phrase
    # Backend-named asks (no 'agent') → redirect to `superresearch --update` on the
    # Research computer; the runtime never updates the backend itself now.
    for phrase in ("update the backend", "update super research",
                   "update the research computer"):
        n = _note(phrase).lower()
        assert "superresearch --update" in n and "research computer" in n, phrase


def test_update_with_english_word_be_routes_to_agent():
    # Regression: the backend-ask regex must NOT match the ordinary English word
    # "be" (the |be alternative was dropped). These are AGENT-update asks, not
    # backend redirects.
    for phrase in ("update it, should be quick", "go ahead and update, that'd be great"):
        n = _note(phrase).lower()
        assert "research computer" not in n, phrase  # NOT the backend redirect
        assert "agent" in n, phrase                  # the agent-update confirm


def test_code_regex_rejects_hyphenated_words_and_embedded_tokens():
    # Dashed alternative now requires a digit — ordinary hyphenated words
    # must not fire device-add.
    assert _argv("research real-time analytics") == ["research", "real-time analytics"]
    note = _note("add my high-tech pc as a device")
    assert "access code" in note.lower()
    note2 = _note("pair my new device john-dell")
    assert "access code" in note2.lower()
    # A code-shaped token inside a sentence isn't a pairing request.
    assert _argv("research iphone17 pricing") == ["research", "iphone17 pricing"]
    assert _argv("research iphone17") == ["research", "iphone17"]
    assert _argv("status of iphone17") == ["status", "iphone17"]
    # Real codes still pair: bare, or with a device keyword.
    assert _argv("MFG8-33UD") == ["device-add", "MFG8-33UD"]
    assert _argv("add device K7XQ-9B2M") == ["device-add", "K7XQ-9B2M"]


def test_log_me_out_variants_reach_the_logout_confirm():
    assert "sign out" in _note("log me out").lower()
    assert "sign out" in _note("sign me out").lower()


def test_apostrophes_are_not_quote_delimiters():
    # "what's … Tesla's …" used to extract the garbage between the two
    # apostrophes as the run title.
    assert _argv("what's the status of Tesla's run") == ["status", "Tesla's"]


def test_bare_yes_gets_the_safe_ask():
    # A confirm reply must be handled by the AI (SKILL.md handoff) — `do`
    # itself answers a bare "yes" with the capabilities ask, never a command.
    _note("yes")
    _note("go ahead")


def test_cmd_do_dash_leading_text_never_dumps_usage(monkeypatch, capsys):
    seen = {}

    def fake_research(ns):
        seen["topic"] = ns.topic
        return 0

    monkeypatch.setattr(sr, "cmd_research", fake_research)
    rc = sr.main(["do", "research", "--help"])
    out = capsys.readouterr().out
    assert rc == 0 and seen["topic"] == "--help"
    assert "usage:" not in out.lower()


def test_cmd_do_dispatches_through_real_parser(monkeypatch):
    # `do` executes a resolved non-destructive command via the real argparse
    # wiring (defaults + flags stay in sync with direct invocation).
    seen = {}

    def fake_status(ns):
        seen["runId"] = ns.runId
        return 0

    monkeypatch.setattr(sr, "cmd_status", fake_status)
    rc = sr.main(["do", "Status", "of", "the", "Super", "Research?"])
    assert rc == 0 and seen == {"runId": None}


def test_cmd_do_confirm_paths_never_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(sr, "cmd_stop", lambda ns: (_ for _ in ()).throw(AssertionError("must not run")))
    rc = sr.main(["do", "stop", "the", "EV", "run"])
    out = capsys.readouterr().out
    assert rc == 0 and "yes" in out.lower()
