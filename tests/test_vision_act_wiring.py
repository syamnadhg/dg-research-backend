"""Track-B acting path: source guards for the per-hotspot dispatcher wiring.

Each wrapped CUA site must route through _shadow_observed_cua with its
canonical hotspot id + the SAME mission prompt the CUA call uses, without
disturbing the load-bearing invariants around it (clipboard hijack, #735
publish flag, marker parsing). Source-inspection style follows
tests/test_vision_engine.py."""
from __future__ import annotations

import inspect
import re

import research


def _src(fn):
    return inspect.getsource(fn)


def _all_hotspot_id_literals():
    """Every ``hotspot_id="..."`` string literal in research.py source.

    This is the drift guard's ground truth. It is deliberately a SUPERSET of the
    _shadow_observed_cua dispatch sites (it also catches _observe_dom_success
    ids) — harvesting every literal cannot miss a newly-wired site the way a
    fixed per-call text window can, so a hotspot added without a curated hint
    fails the guard below instead of silently degrading to a bare context_hint
    at runtime."""
    return set(re.findall(r'hotspot_id="([^"]+)"', inspect.getsource(research)))


# Hotspots intentionally wired WITHOUT a curated hint. Empty today — every
# dispatched/observed hotspot carries one. Only add an id here WITH a written
# reason, and prefer writing the hint over allowlisting.
_HINTLESS_ALLOWLIST: set[str] = set()


def _dispatch_blocks(src):
    """The text of each _shadow_observed_cua(...) call in source order.
    (Functions can also contain _observe_dom_success calls with the same
    hotspot ids — anchoring on the dispatcher call keeps the guards honest.)"""
    blocks, start = [], 0
    while True:
        i = src.find("_shadow_observed_cua(", start)
        if i < 0:
            return blocks
        blocks.append(src[i:i + 1200])
        start = i + 1


def _block_for(src, hotspot_id):
    hits = [b for b in _dispatch_blocks(src) if f'hotspot_id="{hotspot_id}"' in b]
    assert hits, f"no _shadow_observed_cua block with hotspot_id={hotspot_id}"
    return hits


# ── extraction ladder (the #777-dropped trio, re-wrapped) ────────────────────

def test_2c_t3_routed_through_dispatcher():
    src = _src(research.extract_chatgpt_response)
    i = src.index('hotspot_id="2c"')
    assert "_shadow_observed_cua(" in src[:i]
    assert "mission_prompt=PROMPT_COPY_ARTIFACT_CHATGPT" in src
    # The hijack still owns the trigger — capture stays the success truth.
    assert "_run_with_clipboard_hijack(" in src
    assert "_cgpt_t3_trigger" in src
    assert "_is_sources_not_document" in src


def test_2d_nav_all_three_sites_wrapped():
    src = _src(research.extract_claude_response)
    assert src.count('hotspot_id="2d-nav"') == 3
    assert src.count("mission_prompt=PROMPT_NAVIGATE_CLAUDE_FINAL_ARTIFACT") == 3


def test_2d_copy_wrapped_inside_hijack_trigger():
    src = _src(research.extract_claude_response)
    assert src.count('hotspot_id="2d-copy"') == 1
    assert "mission_prompt=PROMPT_COPY_ARTIFACT_CLAUDE" in src
    # Trigger ordering: nav site C then the copy, both inside _claude_t3_trigger,
    # and the hijack helper still drives the trigger.
    t3 = src.index("_claude_t3_trigger")
    assert src.index('hotspot_id="2d-nav"', t3) < src.index('hotspot_id="2d-copy"', t3)
    assert "_run_with_clipboard_hijack(" in src
    # The post-copy selection clear (2026-05-24 highlight-bleed fix) survives.
    assert "removeAllRanges" in src


def test_publish_claude_both_sites_wrapped():
    src_a = _src(research.publish_open_claude_artifact)
    assert 'hotspot_id="publish-claude"' in src_a
    assert "mission_prompt=PROMPT_PUBLISH_CLAUDE_ARTIFACT" in src_a
    # #735 flag is still set BEFORE the CUA/act pass.
    assert src_a.index("_claude_publish_cua_used = True") < src_a.index(
        'hotspot_id="publish-claude"')

    src_b = _src(research.extract_share_link_claude)
    assert 'hotspot_id="publish-claude"' in src_b
    assert "mission_prompt=PROMPT_PUBLISH_CLAUDE" in src_b


# ── the original five sites gain mission parity ──────────────────────────────

def test_panel_open_sites_carry_mission_and_marker():
    (blk_p1,) = _block_for(_src(research.poll_until_done), "7c-p1")
    assert "mission_prompt=PROMPT_OPEN_CHATGPT_SOURCE_PANEL" in blk_p1
    assert 'success_text="panel: open"' in blk_p1

    src_rr = _src(research.poll_all_agents_round_robin)
    (blk_7c,) = _block_for(src_rr, "7c")
    assert "mission_prompt=PROMPT_OPEN_CHATGPT_SOURCE_PANEL" in blk_7c
    assert 'success_text="panel: open"' in blk_7c
    (blk_7d,) = _block_for(src_rr, "7d")
    assert "mission_prompt=PROMPT_OPEN_CLAUDE_SOURCE_ARTIFACT" in blk_7d
    assert 'success_text="panel: open"' in blk_7d


def test_p2_share_sites_carry_missions():
    (blk_c,) = _block_for(_src(research.extract_share_link_chatgpt), "p2-share")
    assert "mission_prompt=" in blk_c
    assert "read it from the clipboard" in blk_c

    (blk_e,) = _block_for(_src(research.extract_and_record_agent), "p2-share")
    assert "cua_share_prompt" in blk_e


# ── hints for the new hotspots ───────────────────────────────────────────────

def test_every_hotspot_literal_has_a_curated_hint():
    """Drift guard: EVERY hotspot_id wired into research.py must carry a curated
    _HOTSPOT_VISION_HINTS entry (or be explicitly allowlisted). Iterates the real
    source literals rather than a hand-maintained id list, so a new dispatch that
    forgets its hint fails here — the failure mode the earlier fixed-list test
    (2c/2d-nav/2d-copy/publish-claude only) could not catch."""
    ids = _all_hotspot_id_literals()
    # Vacuous-pass guard: if the harvester silently breaks (regex/source drift),
    # fail loudly instead of green-on-empty. ~33 unique dispatch/observe ids today.
    assert len(ids) >= 30, (
        f"harvester found only {len(ids)} hotspot_id literals (expected ~33) — "
        "the regex or the dispatch wiring drifted; fix the guard before trusting it."
    )
    missing = sorted(
        hs for hs in ids
        if hs not in _HINTLESS_ALLOWLIST
        and not (research._HOTSPOT_VISION_HINTS.get(hs) or {}).get("context_hint")
    )
    assert not missing, (
        f"hotspot_ids wired with NO curated _HOTSPOT_VISION_HINTS entry: {missing}. "
        "Add a desktop-Chrome target hint that AGREES with the canonical CUA "
        "mission for that site (a divergent hint corrupts promotion data), or add "
        "the id to _HINTLESS_ALLOWLIST with a written reason."
    )


def test_all_curated_hints_are_well_formed():
    """Every entry that exists must be complete — a half-filled hint (missing
    expected_outcome or success_signals) is as useless to Vision as no hint."""
    for hs, hint in research._HOTSPOT_VISION_HINTS.items():
        assert hint.get("context_hint"), f"{hs}: empty/missing context_hint"
        assert hint.get("expected_outcome"), f"{hs}: empty/missing expected_outcome"
        assert hint.get("success_signals"), f"{hs}: empty/missing success_signals"


def test_2d_nav_hint_targets_last_artifact_only():
    hint = research._HOTSPOT_VISION_HINTS["2d-nav"]["context_hint"]
    assert "LAST" in hint
    assert "NEVER the first" in hint  # the #777 wrong-artifact lesson


def test_2c_hint_bans_source_panel_and_preamble():
    hint = research._HOTSPOT_VISION_HINTS["2c"]["context_hint"]
    assert "not the chat" in hint.lower() or "report body only" in hint.lower()
    assert "side panel" in hint.lower()


# ── P1 + polling + misc wiring ───────────────────────────────────────────────

def test_scrape_artifact_wrapped():
    (blk,) = _block_for(_src(research.scrape_claude_artifact_tracking), "scrape-artifact")
    assert "mission_prompt=PROMPT_SCRAPE_CLAUDE_ARTIFACT_TRACKING" in blk


def test_poll_diagnose_and_fix_are_read_only_where_required():
    # wait_until_verified: diagnose read_only, fix acting.
    src_wuv = _src(research.wait_until_verified)
    for blk in _block_for(src_wuv, "poll-diagnose"):
        assert "read_only=True" in blk, "diagnose must be read_only"
    for blk in _block_for(src_wuv, "poll-fix"):
        assert "mission_prompt=PROMPT_FIX_ISSUE" in blk
        assert "read_only" not in blk  # fix acts (click-only, not read-only)


def test_poll_until_done_diagnose_read_only():
    src = _src(research.poll_until_done)
    for blk in _block_for(src, "poll-diagnose"):
        assert "read_only=True" in blk


def test_round_robin_diagnose_read_only():
    src = _src(research.poll_all_agents_round_robin)
    for blk in _block_for(src, "poll-diagnose"):
        assert "read_only=True" in blk


def test_gemini_start_wrapped_dual_target():
    (blk,) = _block_for(_src(research.run_phase2), "gemini-start")
    assert "mission_prompt=PROMPT_GEMINI_START_RESEARCH" in blk
    # dual-target intent preserved in the hint (Start OR Regenerate)
    assert "Retry" in blk or "Regenerate" in blk


def test_select_pro_both_sites_wrapped_no_success_text():
    src = _src(research.run_phase1)
    blks = _block_for(src, "1a-select-pro")
    assert len(blks) == 2
    for blk in blks:
        assert "mission_prompt=PROMPT_SELECT_PRO" in blk
        # No positive success marker — success = absence of "no pro".
        assert "success_text=" not in blk


def test_submit_and_attach_wrapped():
    src = _src(research.run_phase1)
    assert len(_block_for(src, "1a-submit")) == 2
    for blk in _block_for(src, "1a-submit"):
        assert "mission_prompt=PROMPT_SUBMIT_FALLBACK" in blk
    (attach,) = _block_for(src, "1a-attach-pdf")
    assert "mission_prompt=PROMPT_ATTACH_PDF" in attach
    # set/clear_upload_file bracket preserved around the attach act.
    assert "clear_upload_file()" in src


def test_click_send_both_sites_wrapped():
    src = _src(research.start_agent_no_gemini_wait)
    assert len(_block_for(src, "click-send")) == 2
    for blk in _block_for(src, "click-send"):
        assert "mission_prompt=PROMPT_CLICK_SEND" in blk


def test_new_p1_polling_hotspots_have_hints():
    for hs in ("1a-select-pro", "1a-attach-pdf", "1a-submit", "scrape-artifact",
               "poll-diagnose", "poll-fix", "gemini-start", "click-send"):
        hint = research._HOTSPOT_VISION_HINTS.get(hs)
        assert hint and hint.get("context_hint"), f"missing hint for {hs}"


def test_read_only_hints_ban_clicks():
    # poll-diagnose is the read-only verdict hotspot — its hint must forbid clicks.
    hint = research._HOTSPOT_VISION_HINTS["poll-diagnose"]["context_hint"].lower()
    assert "read only" in hint or "do not click" in hint or "never click" in hint
    # poll-fix acts but must never type.
    fix = research._HOTSPOT_VISION_HINTS["poll-fix"]["context_hint"].lower()
    assert "never type" in fix or "click only" in fix


# ── P3 NotebookLM wiring ─────────────────────────────────────────────────────

def test_nlm_upload_sites_preserve_upload_bracket():
    src = _src(research.run_phase3_upload)
    (create,) = _block_for(src, "nlm-create-upload")
    (add,) = _block_for(src, "nlm-add-source")
    assert "mission_prompt=PROMPT_NOTEBOOKLM_UPLOAD" in create
    assert "mission_prompt=PROMPT_NOTEBOOKLM_UPLOAD" in add
    # set/clear_upload_file bracket + filechooser auto-handler stay intact.
    assert "set_upload_file(" in src and "clear_upload_file()" in src


def test_nlm_rename_wrapped():
    (blk,) = _block_for(_src(research.run_phase3_upload), "nlm-rename")
    assert "mission_prompt=PROMPT_NOTEBOOKLM_RENAME" in blk


def test_audio_generate_wrapped_778_guard():
    (blk,) = _block_for(_src(research.run_phase3_audio), "audio-generate")
    assert "mission_prompt=" in blk and "make_prompt_audio_generate" not in blk.split("mission_prompt=")[0][-50:]
    # #778: the hint must forbid touching the card body.
    assert "duplicate" in blk.lower() or "card body" in blk.lower()
    assert "read_only" not in blk  # generate ACTS (Format/Length + Generate)


def test_audio_check_is_read_only():
    (blk,) = _block_for(_src(research.run_phase3_audio), "audio-check")
    assert "read_only=True" in blk  # #778: a single click fires the duplicate


def test_audio_download_preserves_listener_scaffolding():
    src = _src(research.run_phase3_audio)
    (blk,) = _block_for(src, "audio-download")
    assert "read_only" not in blk  # download acts
    # the page.on('download') + future + remove_listener scaffolding survives
    assert 'browser.page.on("download"' in src
    assert "download_future" in src
    assert "target_ordinal" in blk or "entry #" in blk  # #778 target-only threading


def test_audio_check_and_generate_use_length_aware_missions():
    src = _src(research.run_phase3_audio)
    # the length-aware factories still drive the mission text
    assert "make_prompt_audio_check(podcast_length)" in src
    assert "make_prompt_audio_download(podcast_length" in src


def test_nlm_share_fallback_wrapped():
    (blk,) = _block_for(_src(research.extract_notebooklm_url), "nlm-share")
    assert "mission_prompt=" in blk


def test_verify_sources_read_only_reupload_acts():
    src = _src(research._verify_and_repair_nlm_sources)
    (verify,) = _block_for(src, "nlm-verify-sources")
    assert "read_only=True" in verify  # health probe must never click
    assert "mission_prompt=PROMPT_NOTEBOOKLM_VERIFY_SOURCES" in verify
    (reup,) = _block_for(src, "nlm-reupload")
    assert "mission_prompt=PROMPT_NOTEBOOKLM_REUPLOAD" in reup
    assert "read_only" not in reup


def test_p3_read_only_sites_never_execute():
    """The audio-check + verify-sources hotspots are the #778 read-only ones;
    a Vision proposal there must escalate, never act (proven at the loop level
    in test_vision_act_loop; here we pin the CALL SITES pass read_only=True)."""
    audio = _block_for(_src(research.run_phase3_audio), "audio-check")
    assert all("read_only=True" in b for b in audio)


# ── P2 DR-setup path (#709 composer-placeholder requirement) ─────────────────

def test_setup_fallback_wrapped_with_placeholder_hint():
    (blk,) = _block_for(_src(research.start_agent_no_gemini_wait), "setup-dr")
    assert "mission_prompt=" in blk
    # #709: DR-active is judged by the composer placeholder, never a pill state.
    assert "placeholder" in blk.lower()


def test_validate_setup_wrapped_no_success_text():
    # Review [markers]: validate-setup must NOT pass success_text — 'verified' is
    # a confirmation marker gating #744/#709, so stamping it onto any Vision
    # declare_success could flip a hedged claim into a false confirmation. A
    # Vision success flows through unstamped: reason containing 'verified'/'fixed'
    # → confirmed; otherwise the safe ambiguous (True, False).
    (blk,) = _block_for(_src(research.validate_setup_with_cua), "validate-setup")
    assert "success_text=" not in blk
    assert "mission_prompt=" in blk


def test_gemini_validate_mission_keeps_709_placeholder_signal():
    # The Gemini validator user_msg (fed verbatim as the act mission) MUST still
    # demand the composer-placeholder signal, not a pill-pressed heuristic.
    src = _src(research.validate_setup_with_cua)
    assert "What do you want to research?" in src
    assert "merely-visible chip is NOT enough" in src


def test_inline_type_wrapped_no_send():
    # #950: the inline-type CUA fallback moved into the shared
    # type_inline_prompt_with_cua helper (used by BOTH the attach path and the
    # paste→chip top-up); the "no send" contract must survive the move.
    (blk,) = _block_for(_src(research.type_inline_prompt_with_cua), "inline-type")
    assert "do not click Send" in blk.lower() or "not sent" in blk.lower() or "no send" in blk.lower()


def test_human_verify_left_cua_only():
    # Cloudflare/CAPTCHA clearance is deliberately NOT act-wired — Vision escalates
    # on captchas by design, and driving bot-detection is out of scope.
    src = _src(research.wait_for_verification_clearance)
    assert "_shadow_observed_cua(" not in src
    assert "agent_loop(" in src  # still CUA-driven
