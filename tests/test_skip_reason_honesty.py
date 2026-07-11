"""Guard: an agent the PIPELINE dropped must never be reported "skipped by user".

THE BUG (live E2E 2026-07-11 ~02:50, worker 2, run chat_1783761548282_2):
Gemini's brief never registered (URL pinned at bare /app through 3 re-submits).
[2C] correctly raised a Retry/Skip pipeline_error and marked Gemini failed —
then parked it in `_controls.skipped_agents` (an internal marker whose only
job is keeping the dead agent out of the poll/scrape). The round-robin's skip
consumer treats every member of that set as a USER tap: it stamped
status="skipped_by_user", emitted agent_skipped(reason=user_skip_after_leaving_poll)
— which the FE renders literally as "Skipped by user" (pipeline-errors.ts:153)
— and the emit auto-retracted the honest Retry/Skip card via the emit_event
pending-decision clear seam (card raised 02:50:13, phantom-cleared 02:50:17,
zero user interaction). ChatGPT (2A) and Claude (2B) setup-fail paths had the
identical leak, and the login-gate timeout's honest agent_skipped could be
overwritten by a second user_skip* emit the same way.

THE FIX: `skipped_agents` entries are now classified. `request_skip_agent`
(the only user-tap producer) records the key in `user_skip_taps`; internal
adders tag `auto_skip_reasons`. The poll consumer routes non-tap markers away
from the user-skip rails: drop from `pending` (status "failed_setup") with NO
agent_skipped emit — the source already reported the truth (fail_agent card +
errored tile, or the login gate's own honest reason) and the card must stay up.

Plus two Gemini submit-robustness guards from the same incident:
  - the retry loop re-pastes the brief when the composer is EMPTY (the
    documented Gemini drop reverts the composer, so bare re-clicks of Send
    were guaranteed no-ops — all 3 incident retries did nothing), and
  - before fail_agent, `_gemini_adopt_lost_conversation` checks sibling tabs
    + the sidebar's most-recent chat (ownership-verified via
    `_gemini_owns_candidate`) and logs a tab census for postmortems.

Run: pytest tests/test_skip_reason_honesty.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


# ── 1. Classification plumbing ──────────────────────────────────────────────

def test_controls_have_tap_and_auto_channels():
    c = research.PipelineControls()
    assert c.user_skip_taps == set()
    assert c.auto_skip_reasons == {}


def test_request_skip_agent_records_user_tap():
    c = research.PipelineControls()
    c.request_skip_agent("Gemini")
    assert "gemini" in c.skipped_agents
    assert "gemini" in c.user_skip_taps, (
        "a real user tap must be recorded in user_skip_taps — it's the only "
        "thing that entitles the consumer to say 'skipped by user'"
    )


def test_internal_setup_fail_markers_are_tagged_auto():
    src = inspect.getsource(research.run_phase2)
    for agent in ("chatgpt", "claude", "gemini"):
        add = f'_controls.skipped_agents.add("{agent}")'
        tag = f'_controls.auto_skip_reasons["{agent}"] = "setup_failed"'
        assert add in src, f"{agent} setup-fail marker missing"
        assert tag in src, (
            f"{agent} setup-fail add must be tagged auto — untagged, the poll "
            "consumer reports it as a user skip (2026-07-11 incident)"
        )
        # The tag must live in the same block as the add (right after it).
        assert 0 < src.index(tag) - src.index(add) < 400, (
            f"{agent}: auto tag must accompany its skipped_agents.add"
        )


def test_login_timeout_marker_is_tagged_auto():
    src = inspect.getsource(research._work_tab_login_pause)
    assert "login_required_timeout" in src
    assert 'auto_skip_reasons[agent_key] = "login_required_timeout"' in src, (
        "the login-gate timeout emits its own honest agent_skipped — without "
        "the auto tag the consumer re-emits it as user_skip* and the honest "
        "copy is overwritten"
    )


# ── 2. The consumer must not stamp user_skip on internal markers ────────────

def test_consumer_guards_user_skip_behind_tap_record():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    guard = "not in _controls.user_skip_taps"
    assert guard in src, (
        "the mid-run skip consumer must branch on user_skip_taps membership — "
        "set membership alone is NOT evidence of a user tap"
    )
    # The internal-marker branch must come BEFORE both user-skip emits so a
    # non-tap entry can never reach them.
    g = src.index(guard)
    assert g < src.index('reason="user_skip"'), (
        "internal-marker routing must precede the in-pending user_skip emit"
    )
    assert g < src.index('reason="user_skip_after_leaving_poll"'), (
        "internal-marker routing must precede the left-poll user_skip emit "
        "(the exact emit that mislabeled the 2026-07-11 Gemini failure)"
    )


def test_consumer_internal_branch_drops_without_agent_skipped_emit():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    start = src.index("not in _controls.user_skip_taps")
    # The branch's own in-pending check is indented deeper; the consumer's next
    # top-level check (12-space indent, newline-anchored) ends the branch.
    end = src.index("\n            if _agent_name and _agent_name in pending:", start)
    branch = src[start:end]
    assert '"failed_setup"' in branch, (
        "an internal marker for an in-pending agent must drop it with an "
        "explicit failed_setup status, not skipped_by_user"
    )
    assert "emit_event" not in branch, (
        "the internal branch must NOT emit agent_skipped — the emit would grey "
        "the errored tile AND auto-retract the live Retry/Skip card via the "
        "emit_event pending-decision clear seam"
    )
    assert "skipped_by_user" not in branch


def test_consumer_discards_tap_record_with_marker():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "_controls.consume_skip_marker(_ag_key)" in src, (
        "consumed markers must retire via consume_skip_marker so the tap "
        "record + auto reason go with them — a stranded tap misreads a later "
        "internal marker for the same agent as a user tap"
    )


# ── 3. Gemini submit robustness (same incident) ─────────────────────────────

def test_gemini_retry_repastes_when_composer_empty():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert "composer is EMPTY on retry" in src, (
        "the Gemini re-submit loop must detect the reverted (empty) composer — "
        "re-clicking Send against it is a guaranteed no-op (all 3 incident "
        "retries were no-ops)"
    )
    block = src[src.index("Gemini URL still bare, no error yet") - 2500:
                src.index("Gemini URL still bare, no error yet")]
    assert "verified_paste_brief" in block, (
        "on an empty composer the loop must re-paste the brief BEFORE re-sending"
    )


def test_gemini_adoption_runs_before_fail_agent():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    adopt = src.index("_gemini_adopt_lost_conversation")
    fail_log = src.index("never started a research plan after")
    assert adopt < fail_log, (
        "lost-conversation adoption (sibling tab + sidebar, ownership-verified) "
        "must be attempted before surfacing the Retry/Skip blocker"
    )


def test_adopt_helper_logs_tab_census():
    src = inspect.getsource(research._gemini_adopt_lost_conversation)
    assert "tab census" in src, (
        "the adoption helper must log the Gemini tab census so backend.log "
        "alone can adjudicate tab-orphan vs dropped-send next time"
    )
    assert "_gemini_owns_candidate" in src, "both probes must be ownership-gated"


# ── 4. Ownership matcher (pure) ─────────────────────────────────────────────

BRIEF_HEAD = (
    "# Research Brief: NemoClaw — NVIDIA's agentic robotics framework\n"
    "Investigate the architecture, training pipeline and deployment story of "
    "NemoClaw, including its integration with Isaac Sim and Jetson Thor."
)


def test_owns_candidate_matches_gemini_autotitle():
    # Gemini auto-titles a new chat from the prompt's opening words.
    assert research._gemini_owns_candidate(
        "NemoClaw NVIDIA agentic robotics framework", BRIEF_HEAD)


def test_owns_candidate_rejects_unrelated_past_run():
    assert not research._gemini_owns_candidate(
        "Golden retriever breed history and care guide", BRIEF_HEAD)


def test_owns_candidate_fails_closed_on_empty_or_short():
    assert not research._gemini_owns_candidate("", BRIEF_HEAD)
    assert not research._gemini_owns_candidate("Hi", BRIEF_HEAD)
    assert not research._gemini_owns_candidate("NemoClaw stuff", "")


def test_owns_candidate_requires_majority_token_overlap():
    # 1 of 6 significant tokens present (below the 60% bar) → no match.
    assert not research._gemini_owns_candidate(
        "NemoClaw quarterly earnings report shareholders meeting", BRIEF_HEAD)


def test_owns_candidate_rejects_generic_short_titles():
    # Adversarial-review finding: a 1-2 generic-token title must fail-closed
    # (min 3 significant tokens) even if every token appears in the brief.
    assert not research._gemini_owns_candidate("Market research", BRIEF_HEAD + " market research")
    assert not research._gemini_owns_candidate("robotics framework", BRIEF_HEAD)


def test_owns_candidate_uses_word_boundaries():
    # 'search' as a substring of 'Research' must NOT count as a hit.
    assert not research._gemini_owns_candidate(
        "search deep dive analysis", "# Research Brief: something unrelated entirely")


# ── 5. Marker lifecycle (adversarial-review HIGH) ───────────────────────────

def test_consume_skip_marker_retires_all_three_channels():
    c = research.PipelineControls()
    c.request_skip_agent("gemini")
    c.auto_skip_reasons["gemini"] = "setup_failed"
    c.consume_skip_marker("Gemini")
    assert "gemini" not in c.skipped_agents
    assert "gemini" not in c.user_skip_taps, (
        "a stranded tap would misclassify a LATER internal marker for the "
        "same agent as a user skip — the incident all over again"
    )
    assert "gemini" not in c.auto_skip_reasons


def test_reset_clears_classification_fields():
    # The worker loop reuses ONE PipelineControls across runs with reset() as
    # the only boundary — run N's tap must not bleed into run N+1.
    c = research.PipelineControls()
    c.user_skip_taps.add("chatgpt")
    c.auto_skip_reasons["claude"] = "setup_failed"
    c.reset()
    assert c.user_skip_taps == set()
    assert c.auto_skip_reasons == {}


def test_no_bare_skipped_agents_discard_outside_controls():
    # Every discard must go through consume_skip_marker (atomic retirement).
    # The only allowed bare discards are inside PipelineControls itself.
    import re as _re
    src_file = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research.py")
    with open(src_file, encoding="utf-8") as fh:
        src = fh.read()
    bare = _re.findall(r"_controls\.skipped_agents\.discard\(", src)
    assert not bare, (
        "found bare _controls.skipped_agents.discard(...) call(s) — use "
        "_controls.consume_skip_marker(...) so the tap record and auto reason "
        "retire atomically with the marker"
    )


def test_clear_seam_scopes_agent_skipped():
    src = inspect.getsource(research.emit_event)
    assert '_clear_pending_decision(agent if event_type == "agent_skipped" else None)' in src, (
        "the emit_event clear seam must agent-scope agent_skipped clears so "
        "skipping agent A can't retract agent B's still-live Retry/Skip mirror"
    )
