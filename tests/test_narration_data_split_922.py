"""#922 (2026-07-08): narration ⇄ raw-activity data split + honest stepper.

User feedback (4 D:\\downloads screenshots): the phase-dropdown narration and
the raw-activity popup showed the SAME generic prose; the real activity-panel
content was scraped but under-used; Gemini's stepper had an extra "Planning"
node; and agents looked "researching" before they were opened.

Backend half of the fix, verified here:
  - the narrator finally RECEIVES the scraped activity steps (was silently
    dropped from _compact_event_for_narration) and is told to ground on them;
  - the narrator no longer fabricates a line for an agent that hasn't started
    (P2 opens ChatGPT -> Claude -> Gemini sequentially);
  - the ChatGPT activity-panel VERB_GATE admits real gerund-led step titles
    like "Creating a brief on Golden Retrievers..." (was a fixed allowlist that
    rejected "Creating");
  - real source TITLES ({url,title}) are captured + emitted as `sourceItems`;
  - Gemini's first post-submit emit carries an explicit stage="planning".
"""

import inspect
from pathlib import Path

import research

_SRC = Path(research.__file__).read_text(encoding="utf-8")
_NARR = inspect.getsource(research._narrator_loop)


# ── Narrator now sees the real scraped steps (functional) ────────────────────

def test_compact_event_surfaces_steps():
    line = research._compact_event_for_narration({
        "type": "agent_progress", "phase": 2, "agent": "chatgpt",
        "data": {"steps": [
            "Creating a brief on Golden Retrievers",
            "Reading the breed standard sources",
            "Drafting the methodology section",
        ]},
    })
    assert "steps=" in line, "the scraped step titles must reach the narrator prompt"
    # Freshest step is surfaced (grounds the narration in the latest activity).
    assert "Drafting the methodology section" in line


def test_compact_event_steps_takes_only_freshest_few():
    line = research._compact_event_for_narration({
        "type": "agent_progress", "phase": 2, "agent": "gemini",
        "data": {"steps": [f"step number {i}" for i in range(10)]},
    })
    # Only the last few (freshest) ride the prompt — not the whole history.
    assert "step number 9" in line
    assert "step number 0" not in line


def test_steps_is_in_the_compaction_key_tuple():
    src = inspect.getsource(research._compact_event_for_narration)
    assert '"steps"' in src and "steps=" in src


# ── Narrator stays silent for a not-yet-started agent ────────────────────────

def test_narrator_skips_never_started_agent():
    # The queued-agent guard: no fabricated "Claude is..." before the backend
    # has opened Claude (would contradict the FE "Waiting to start" card).
    assert "if akey not in last_known_status_for_agent:" in _NARR


def test_narrator_prompt_grounds_on_real_steps():
    assert "steps=<titles>" in _NARR


# ── ChatGPT activity-panel VERB_GATE admits gerund-led titles ────────────────

def test_verb_gate_is_leading_gerund():
    src = inspect.getsource(research.scrape_chatgpt_activity_panel_tracking)
    assert r"/^[a-z]+ing\\b/i" in src, "gerund gate must admit 'Creating a brief...'"
    # The old fixed allowlist (which rejected 'Creating') must be gone.
    assert "checking|searching|looking|browsing" not in src


# ── Real source titles captured + emitted as sourceItems ─────────────────────

def test_tracker_captures_source_titles():
    src = inspect.getsource(research.scrape_chatgpt_activity_panel_tracking)
    assert "source_items" in src
    assert "out.source_items.push({ url: h, title:" in src


def test_agent_progress_emits_source_items():
    assert 'sourceItems=progress.get("source_items"' in _SRC


def test_panel_merge_unions_source_items_by_url():
    # dicts aren't hashable -> must NOT ride the dict.fromkeys union; a dedicated
    # url-keyed merge keeps the first non-empty title per url.
    assert 'progress["source_items"] = list(_by_url.values())' in _SRC


# ── Gemini first post-submit emit carries an explicit planning stage ─────────

def test_gemini_first_emit_has_planning_stage():
    assert ('status="generating", stage="planning", '
            'progress="Gemini generating research plan') in _SRC


def test_verify_failed_but_alive_handoff_stamps_researching_stage():
    # Review fix (major): a live-but-unverified P2 agent (DR in a cross-origin
    # iframe → zero counters) must still advance the stepper past "Submitted".
    # The verify-failed-but-alive hand-off now stamps stage="researching" for
    # BOTH ChatGPT (/c/<id>) and Claude (/chat/<id>).
    assert _SRC.count(
        'status="generating",\n                           stage="researching",\n'
        '                           progress="ChatGPT DR submitted'
    ) == 1
    assert _SRC.count(
        'status="generating",\n                           stage="researching",\n'
        '                           progress="Claude DR submitted'
    ) == 1


def test_module_imports_and_symbols_exist():
    for nm in ("_narrator_loop", "_compact_event_for_narration",
               "scrape_chatgpt_activity_panel_tracking"):
        assert hasattr(research, nm)
