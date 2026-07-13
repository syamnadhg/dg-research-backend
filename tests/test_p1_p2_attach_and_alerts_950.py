"""#950 — the 2026-07-13 03:26 retest (worker 1, build 26ae89f).

WHAT THE LOG SHOWED:
  [03:40:24] [2A] Brief attached via hidden file input
  [03:40:50] attachment NOT verified (found=False, processing=False, error='')
  …3 attempts, then paste fallback…
  [03:41:51] Paste verify (clipboard): 17/73309 chars (0%)
  [03:42:02] Paste verify (cua-assisted): 17/73309 chars (0%)
  [03:42:02] CRITICAL: Both attach and paste (DOM+CUA) failed
  [03:42:03] [pending-decision] persisted … alert_id=agent_chatgpt_error  ×2

LIVE-PROBED ROOT CAUSES (chip_probe.py against the real profile):
  A) attach: on a CLEAN chatgpt.com page the same set_input_files lands its
     chip in 2.5s with the filename visible in innerText AND in the remove
     button's aria-label ("Remove file 1: probe_brief.md"). The run's tab was
     P1's WARM post-canvas tab (client-side New chat) — the first
     input[type=file] in document order there isn't necessarily wired to the
     live composer, and feeding a stale input is a total silent no-op (no
     chip, no spinner, no toast — exactly the log's three all-False probes).
     attach_brief_file must rank composer-form inputs first and accept a
     candidate only when the page actually reacts.
  B) paste: ChatGPT AUTO-CONVERTS a brief-sized paste into a "Pasted text"
     attachment chip. After pasting 74k chars the composer reads EXACTLY
     "\\ufeff\\nDeep research\\n " = 17 chars — the run's mysterious
     17/73309. The paste had fully landed both times; the char-count verify
     failed a delivered brief and killed the agent.
  C) alert: the CRITICAL site fired fail_agent ("Couldn't send the brief to
     ChatGPT") and the outer 2A handler fired a SECOND generic fail_agent
     ("ChatGPT didn't start") 1s later — same alert_id, so the generic copy
     overwrote the specific one. (The P1-dropdown leak of that card is the
     FE's flat agentAlerts["chatgpt"] map — fixed FE-side by stamping+
     matching alert.phase; the BE already emits phase=2, pinned here.)

Run: pytest tests/test_p1_p2_attach_and_alerts_950.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

ATTACH_SRC = inspect.getsource(research.attach_brief_file)
STATE_SRC = inspect.getsource(research._brief_attachment_state)
ENSURE_SRC = inspect.getsource(research._ensure_brief_attached)
VERIFY_SRC = inspect.getsource(research._verify_paste_landed)
FAIL_SRC = inspect.getsource(research.fail_agent)
MOD_SRC = inspect.getsource(research)


# ── A: attach feeds the RIGHT input and verifies the page reacted ────────────

def test_attach_ranks_composer_form_inputs_first():
    assert "closest('form')" in ATTACH_SRC, (
        "candidates must be ranked composer-form-first — the warm post-canvas "
        "tab is where the first document-order input was a stale no-op"
    )
    assert "query_selector_all" in ATTACH_SRC, (
        "ALL file inputs must be enumerated (query_selector picked only the "
        "first, which was the broken one on 2026-07-13)"
    )


def test_attach_accepts_only_on_page_reaction():
    i_set = ATTACH_SRC.index("set_input_files(all_paths)")
    i_census = ATTACH_SRC.index("Poll for a page reaction")
    i_ret = ATTACH_SRC.index("return True")
    assert i_set < i_census < i_ret, (
        "the reaction poll must sit between set_input_files and the True "
        "return — set_input_files succeeding is NOT evidence the composer "
        "saw the file (three silent no-ops on 2026-07-13)"
    )
    assert "stale input, trying next" in ATTACH_SRC, (
        "an unreactive input must be skipped with a log line, and the next "
        "candidate tried"
    )


def test_attach_reaction_signals_are_not_page_global_stale():
    # #950 review: `found` (the filename chip) is input-specific; the
    # page-global processing/error signals only count when NEW vs a baseline
    # AND on the composer-form input — a spinner/toast lingering from a prior
    # attempt must not credit a stale non-composer input.
    assert "base = await _brief_attachment_state(page, fname)" in ATTACH_SRC, (
        "a baseline probe must be taken BEFORE set_input_files so only NEW "
        "signals count as a reaction"
    )
    assert "not base.get(\"processing\")" in ATTACH_SRC
    assert "grp == 0 and (" in ATTACH_SRC, (
        "processing/error may only credit a composer-form input"
    )


def test_attach_failure_toast_counts_as_wired():
    # A failure toast means the upload pipeline SAW the file — that input is
    # the right one; _ensure_brief_attached owns the retry pacing from there.
    assert "_real_err(st)" in ATTACH_SRC
    # …but a crashed probe must NOT count as a reaction.
    assert 'startswith("probe_error")' in ATTACH_SRC


def test_attach_success_log_is_honest_about_dropped_extras():
    # #950 review: when the multi-file attach fails and retries brief-only,
    # the success log must NOT claim the extras were attached.
    assert "extras_delivered = False" in ATTACH_SRC
    assert "extras dropped — will reach NLM via P3" in ATTACH_SRC


def test_chooser_fallback_censuses_too():
    # #950 review: the OS-chooser fallback must not blind-return True — it
    # re-introduces the exact pattern the input loop removed (ChatGPT's "+"
    # opens a menu, not a chooser, so the click can no-op).
    i_btnclick = ATTACH_SRC.index("Brief attached via button click")
    tail_head = ATTACH_SRC[i_btnclick - 400:i_btnclick]
    assert "_brief_attachment_state(page, fname)" in tail_head, (
        "the chooser fallback must census the result before returning True"
    )


# ── B: attachment-state probe — multi-signal found, no silent crashes ────────

def test_state_probe_accepts_remove_button_aria():
    assert "aria-label" in STATE_SRC and "remove|delete" in STATE_SRC, (
        "found must also accept a visible remove-attachment button naming "
        "the file — live ChatGPT chip: aria-label='Remove file 1: brief.md'"
    )
    assert "fname.slice(0, 12)" in STATE_SRC, (
        "the chip TITLE truncates long filenames, so the aria check accepts "
        "a 12-char prefix"
    )


def test_state_probe_crash_is_logged_not_silent():
    assert "probe_error" in STATE_SRC, (
        "an evaluate() crash must be distinguishable from 'chip absent' — "
        "the 03:40 run's found=False/error='' was unexplainable from the log"
    )
    assert "attachment-state probe crashed" in STATE_SRC


def test_ensure_treats_probe_crash_as_retry_not_platform_failure():
    i_crash = ENSURE_SRC.index("state probe crashed")
    i_fail = ENSURE_SRC.index("platform reported upload")
    assert i_crash < i_fail, (
        "probe_error must be handled BEFORE the platform-failure branch — "
        "a crashed probe is our bug, not an upload rejection"
    )
    crash_block = ENSURE_SRC[i_crash:i_crash + 260]
    assert "continue" in crash_block, (
        "a crashed probe retries the probe; it must not burn an attach attempt"
    )


# ── C: paste verify — ChatGPT auto-convert is SUCCESS ────────────────────────

def test_chatgpt_pasted_chip_census_exists():
    js = research._CHATGPT_PASTED_CHIP_JS
    assert "remove file" in js and "pasted text" in js.lower(), (
        "census keys on the live chip shape: aria 'Remove file N: <paste "
        "head>' + the 'Pasted text' caption"
    )


def test_paste_verify_accepts_chatgpt_auto_convert():
    assert '"chatgpt" and ratio < 0.90' in VERIFY_SRC, (
        "the ChatGPT branch mirrors Claude's tile rule — a converted paste "
        "IS a delivered brief (the 03:41 run failed a landed 74k paste at "
        "'17/73309 chars')"
    )
    assert "auto-converted to a" in VERIFY_SRC
    assert "duplicate" in VERIFY_SRC, (
        "chips > 1 (double paste) must warn — but still count as delivered, "
        "otherwise every retry adds another chip and it never converges"
    )


def test_converted_paste_gets_operative_inline_prompt():
    i_topup = MOD_SRC.index("Pasted brief auto-converted to an attachment chip")
    i_mode = MOD_SRC.index("mode_state = await ensure_deep_mode_active", i_topup)
    assert i_topup < i_mode, (
        "the inline-prompt top-up must run at the paste/attach convergence "
        "point, before the pre-send mode gates — a converted paste leaves "
        "the composer EMPTY (17 chars of pill scaffolding)"
    )
    topup = MOD_SRC[i_topup - 700:i_topup + 900]
    assert "not _brief_via_attach and not is_gemini" in topup, (
        "top-up is gated to the paste path on converting platforms — the "
        "attach path already types its prompt, Gemini's paste stays text"
    )
    # #950 review (confirmed finding): the top-up must ESCALATE to CUA on a
    # type miss, the same guard the attach path has — a silently-failed type
    # would send a bare chip with NO operative instruction.
    assert "type_inline_prompt_with_cua(page, browser, cua_client" in topup


def test_inline_type_helper_shared_by_both_paths_and_escalates():
    # One helper types + escalates to CUA; both the attach path and the
    # paste→chip top-up must route through it (no bare type_short_inline_prompt
    # whose False return gets discarded).
    helper = inspect.getsource(research.type_inline_prompt_with_cua)
    assert "type_short_inline_prompt(page, platform, label)" in helper
    assert "_shadow_observed_cua(" in helper, (
        "a type miss must fall to the CUA act tier, not silently proceed"
    )
    # both call sites use the shared helper
    assert MOD_SRC.count("type_inline_prompt_with_cua(page, browser, cua_client") >= 2


def test_pre_send_recheck_covers_the_converted_paste_chip():
    i_flag = MOD_SRC.index("_paste_chip_head = None")
    i_recheck = MOD_SRC.index("elif _paste_chip_head is not None:")
    i_send = MOD_SRC.index("_send_sels = [")
    assert i_flag < i_recheck < i_send, (
        "the pasted-text chip is an upload too — a late processing failure "
        "kills it after verify, and the composer then only holds the short "
        "inline prompt (the exact stale-run #949 closed for the attach path)"
    )
    tail = MOD_SRC[i_recheck:i_recheck + 1800]
    assert "NOT sending a brief-less run" in tail
    assert "fail_agent(" in tail


# ── D: one failure, one card ─────────────────────────────────────────────────

def test_fail_agent_stamps_card_timestamp():
    assert "_AGENT_ERROR_CARD_TS[agent_key] = time.monotonic()" in FAIL_SRC, (
        "fail_agent must stamp its emit so the outer generic card can tell "
        "a specific card is already up (same alert_id → the generic copy "
        "OVERWROTE 'Couldn't send the brief' on 2026-07-13 03:42)"
    )


def test_generic_didnt_start_cards_defer_to_specific_ones():
    assert MOD_SRC.count("specific failure card already up") >= 2, (
        "both the 2A and 2B outer handlers must skip their generic "
        "'didn't start' card when the launch flow already carded the cause"
    )
    # The suppression window must be tight — minutes-later retry failures
    # must still card (a stale stamp eating the ONLY card of a new failure
    # would strand the run with no UI).
    src = inspect.getsource(research._agent_error_recently_carded)
    assert "45" in src
    # #950 review: monotonic clock — an NTP step must not stretch/collapse
    # the window; wall-clock time.time() would.
    assert "time.monotonic()" in src
    assert "time.monotonic()" in FAIL_SRC


def test_recently_carded_snapshot_taken_before_page_probes():
    # #950 review: the specific-card check is snapshotted at the TOP of each
    # failure branch, BEFORE _hv_setup_fail_card / _page_shows_login_wall —
    # those probes can run seconds on a stalled page and expire the window.
    for tag, snap in (("2A", "_cg_specific_already"), ("2B", "_cl_specific_already")):
        i_snap = MOD_SRC.index(f"{snap} = _agent_error_recently_carded")
        i_hv = MOD_SRC.index("_hv_setup_fail_card(", i_snap)
        i_use = MOD_SRC.index(f"elif {snap}:")
        assert i_snap < i_hv < i_use, (
            f"{tag}: the snapshot must precede the page probes and be consumed "
            f"after them"
        )


def test_fail_agent_event_carries_phase_2():
    # The FE's phase-scoped alert routing (AgentAlert.phase) keys off this —
    # P1's brief tile shares the "chatgpt" agentAlerts key with the P2 agent.
    assert 'emit_event("pipeline_error", phase=2, agent=agent_key' in FAIL_SRC
