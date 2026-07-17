"""#63 — alert copy + notification hygiene (BE half).

Two centralizations + one alert-id split, all source-pinned (the emitters live
deep inside the huge async P2 setup functions, so — like
test_alert_id_collisions_62.py — we assert the helper contract + the branch
structure rather than driving a live pipeline):

  1. GEMINI "couldn't start Deep Research" copy → `_GEMINI_CANT_START`. Five
     emit sites carried a byte-identical (title, details); a future edit to one
     could silently drift the other four. Now one constant, referenced 5×.

  2. BRIEF "Couldn't send the brief to {platform}" copy → `_brief_send_fail_copy`.
     Four emit sites, two detail bodies (default hand-off failure + the
     paste/chip "kept rejecting" variant). Now one helper, called 4×.

  3. ANTHROPIC key cards get distinct alert_ids on the fail_phase path. The four
     blockers (rate-limit / overload / cap / rejected) shared the generic
     phase{n}_error, so the FE dismiss-resurface ledger (keyed on alert_id) let
     a dismissed earlier card silence a later, different one within its 5-min
     window. Distinct ids can't cross-silence; the P2 per-agent fail_agent path
     is deliberately left on phase{n}_agent_{key}_error (one card per agent).

Run: pytest tests/test_alert_copy_hygiene_63.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def _module_src() -> str:
    return inspect.getsource(research)


# ── 1. Gemini couldn't-start copy centralized ────────────────────────────────

def test_gemini_cant_start_constant_is_byte_exact():
    title, details = research._GEMINI_CANT_START
    assert title == "Gemini couldn't start Deep Research"
    # byte-exact vs the pre-#63 two-literal string (space after "glitch.").
    assert details == (
        "Gemini didn't begin its research — likely a platform-side glitch. "
        "Retry to try again, or Skip to continue without it."
    )


def test_gemini_copy_has_no_duplicated_inline_literals():
    src = _module_src()
    # The title/details must appear ONCE — only inside the constant. A second
    # occurrence means an emit site kept an inline copy that can drift.
    assert src.count("Gemini couldn't start Deep Research") == 1, (
        "the Gemini couldn't-start title must live only in _GEMINI_CANT_START."
    )
    assert src.count("Gemini didn't begin its research — likely a platform-side glitch.") == 1


def test_all_five_gemini_sites_use_the_constant():
    src = _module_src()
    # 5 emit sites all spread the constant (the definition line does NOT match
    # this pattern, so the count is exactly the call sites).
    assert src.count('fail_agent("gemini", *_GEMINI_CANT_START)') == 5, (
        "all five Gemini couldn't-start emit sites must call "
        "fail_agent('gemini', *_GEMINI_CANT_START)."
    )


# ── 2. brief-delivery copy centralized ───────────────────────────────────────

def test_brief_send_fail_copy_default_variant_is_byte_exact():
    title, details = research._brief_send_fail_copy("Gemini")
    assert title == "Couldn't send the brief to Gemini"
    assert details == (
        "We couldn't hand the research brief to Gemini. "
        "Retry to try again, or Skip it."
    )


def test_brief_send_fail_copy_rejected_variant_is_byte_exact():
    title, details = research._brief_send_fail_copy("ChatGPT", rejected=True)
    assert title == "Couldn't send the brief to ChatGPT"
    assert details == (
        "ChatGPT kept rejecting the brief upload. "
        "Retry to try again, or Skip it."
    )


def test_brief_variants_are_distinct_bodies_same_title():
    d_title, d_body = research._brief_send_fail_copy("Claude")
    r_title, r_body = research._brief_send_fail_copy("Claude", rejected=True)
    assert d_title == r_title == "Couldn't send the brief to Claude"
    assert d_body != r_body


def test_brief_copy_has_no_duplicated_inline_literals():
    src = _module_src()
    # Each body appears once — only inside _brief_send_fail_copy.
    assert src.count("We couldn't hand the research brief to") == 1
    assert src.count("kept rejecting the brief upload") == 1


def test_all_four_brief_sites_use_the_helper():
    src = _module_src()
    # 2 default + 2 rejected calls (definition line uses `def`, not a call).
    assert src.count("fail_agent(platform_l, *_brief_send_fail_copy(platform))") == 2
    assert src.count(
        "fail_agent(platform_l, *_brief_send_fail_copy(platform, rejected=True))"
    ) == 2


# ── 3. Anthropic key cards → distinct alert_ids (fail_phase path) ─────────────

def test_anthropic_key_cards_have_distinct_alert_ids():
    src = _module_src()
    for _id in (
        'alert_id=f"phase{_phase}_ai_rate_limit"',
        'alert_id=f"phase{_phase}_ai_unavailable"',
        'alert_id=f"phase{_phase}_ai_cap"',
        'alert_id=f"phase{_phase}_ai_key_rejected"',
    ):
        assert _id in src, (
            f"the Anthropic key card must carry its own {_id} so a dismissed "
            "sibling card can't silence it via the FE dismiss ledger."
        )


def test_anthropic_ids_are_mutually_distinct():
    ids = {"phase{_phase}_ai_rate_limit", "phase{_phase}_ai_unavailable",
           "phase{_phase}_ai_cap", "phase{_phase}_ai_key_rejected"}
    assert len(ids) == 4  # no two kinds collapse onto one id


def test_p2_agent_key_path_keeps_shared_per_agent_id():
    # The fail_agent (P2, one-card-per-agent) branch must NOT get a distinct
    # per-kind id — that would double-card an agent. It stays on the default
    # phase{n}_agent_{key}_error via fail_agent (no alert_id override there).
    src = _module_src()
    # The four fail_agent key-card calls carry recoverability but NO alert_id=.
    for _title in ('"API key rate limit persists"', '"AI service unavailable"',
                   '"API key is over its limit"', '"API key was rejected"'):
        i = src.index(f"fail_agent(_agent, {_title}")
        window = src[i:i + 160]
        assert "recoverability=\"blocker\"" in window
        assert "alert_id=" not in window, (
            f"the P2 per-agent card {_title} must stay on the shared "
            "phase{n}_agent_{key}_error slot (one card per agent)."
        )


def test_fail_phase_honors_the_new_ai_alert_id(monkeypatch):
    # The mechanism the distinct ids rely on: alert_id via **extra overrides
    # fail_phase's hardcoded phase{n}_error default (payload.update).
    events = []
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(research, "_persist_pending_decision", lambda p: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research._runtime, "phase", 1, raising=False)
    research.fail_phase(1, "API key was rejected", "d",
                        recoverability="blocker",
                        alert_id="phase1_ai_key_rejected")
    ev = next(k for (a, k) in events if a and a[0] == "pipeline_error")
    assert ev["alert_id"] == "phase1_ai_key_rejected"
