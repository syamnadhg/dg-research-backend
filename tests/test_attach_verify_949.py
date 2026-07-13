"""#949 — three fixes from the 2026-07-13 02:46 E2E (worker 2) + screenshot.

A) P2 ChatGPT fired WITHOUT the brief: the platform showed "There was a
   problem processing the upload", the chip never landed, and the run was
   sent anyway — Deep Research ran on the 218-char inline prompt alone.
   attach_brief_file's True only means set_input_files didn't throw. Fix:
   `_brief_attachment_state` (chip visible via innerText + composer-region
   processing spinner + failure-toast scan) and `_ensure_brief_attached`
   (2 stable probes required, bounded re-attach) gate the send for ChatGPT
   + Claude; failure falls back to the inline-paste path (same content as
   text — Gemini's whole path). A pre-send re-check catches a LATE toast
   killing the chip after the mode gates; if re-attach fails there, an
   honest Retry/Skip card fires instead of a brief-less run.

B) P1 raw-activity panel empty until the run finishes: the sources/Activity
   side panel was OPENED at ~30s but nothing ever READ it during P1 — the
   walk (P2's Block 1c mirror) now merges live steps/source urls/titles
   into every P1 progress emit.

C) --no-sandbox banner (user screenshot): patchright injects the flag
   unless chromiumSandbox=true; Chrome paints a permanent "unsupported
   command-line flag" infobar — a bot tell + a geometry shift under every
   vision screenshot. Sandbox now ON for macOS/Windows; Linux unchanged.

Run: pytest tests/test_attach_verify_949.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


# ── A: attachment verification ───────────────────────────────────────────────

def test_attachment_state_helper_covers_the_live_toast():
    src = inspect.getsource(research._brief_attachment_state)
    assert "problem processing the upload" in src, (
        "the failure-toast scan must cover the exact 2026-07-13 ChatGPT toast"
    )
    for phrase in ("failed to upload", "upload failed", "unable to upload"):
        assert phrase in src
    # Chip presence = VISIBLE text (innerText, not textContent — a hidden
    # remnant must not count as a landed chip).
    assert "document.body?.innerText" in src
    # Processing spinner scoped to the composer region, visibility-gated.
    assert "vh * 0.55" in src and "offsetParent === null" in src


def test_ensure_brief_attached_requires_stable_probes_and_bounded_retries():
    src = inspect.getsource(research._ensure_brief_attached)
    assert "stable_hits >= 2" in src, (
        "verification needs 2 consecutive settled probes — a chip that's "
        "still processing can flip to the failure toast a second later"
    )
    assert "max_attempts" in src and "attach_brief_file(" in src, (
        "an unverified attach must be re-attached (bounded), not accepted"
    )
    assert "refusing to fire without the brief" in src


def test_p2_flow_verifies_after_attach_before_typing():
    mod_src = inspect.getsource(research)
    i_attach = mod_src.index("attached = await attach_brief_file(")
    i_verify = mod_src.index("attached = await _ensure_brief_attached(")
    # #950: the attach path now types via the shared type_inline_prompt_with_cua
    # helper (escalates to CUA on a selector miss) instead of a bare
    # type_short_inline_prompt whose False return was discarded.
    i_type = mod_src.index("await type_inline_prompt_with_cua(page, browser, cua_client")
    assert i_attach < i_verify < i_type, (
        "the launch flow must verify the chip landed BEFORE typing/sending — "
        "attach_brief_file's True is not evidence the upload processed"
    )
    # Verification failure must reach the existing inline-paste fallback.
    assert "falling back to inline paste" in mod_src


def test_pre_send_recheck_blocks_briefless_run():
    mod_src = inspect.getsource(research)
    i_recheck = mod_src.index("pre-send re-check: brief chip gone")
    i_send = mod_src.index("_send_sels = [")
    assert i_recheck < i_send, (
        "the pre-send re-check must run before the Send click loop — a late "
        "failure toast can kill the chip after the mode gates"
    )
    tail = mod_src[i_recheck:i_recheck + 1500]
    assert "NOT sending a brief-less run" in tail
    assert "fail_agent(" in tail, (
        "if the chip can't be restored at send time, an honest Retry/Skip "
        "card must fire — never a stale run"
    )


def test_gemini_keeps_paste_path():
    # Gemini never attaches (file-attach silently drops on Gemini) — the
    # verification only rides the use_file_attach branch.
    mod_src = inspect.getsource(research)
    assert 'use_file_attach = brief_path and Path(brief_path).exists() and not is_gemini' in mod_src


# ── B: P1 live activity walk ─────────────────────────────────────────────────

def test_p1_poll_walks_the_open_panel():
    src = inspect.getsource(research.poll_until_done)
    assert "scrape_chatgpt_activity_panel_tracking" in src, (
        "P1 must WALK the opened sources/Activity panel — pre-fix it was "
        "opened at ~30s and never read, so the FE raw-activity drilldown "
        "stayed empty until the run finished"
    )
    walk = src[src.index("P1 activity-panel WALK"):]
    # Live data merged into the emitted progress dict.
    for key in ('"source_urls"', '"steps"', '"source_items"'):
        assert key in walk[:3000]
    # Throttled + gated on the panel actually being open.
    assert "_panel_open_done" in walk[:1400] and "_last_panel_walk" in walk[:1400]


def test_p1_walk_precedes_the_progress_emit():
    src = inspect.getsource(research.poll_until_done)
    i_walk = src.index("P1 activity-panel WALK")
    i_emit = src.index('emit_event("agent_progress"', i_walk)
    assert i_walk < i_emit, (
        "the walk must merge into `progress` BEFORE the agent_progress emit "
        "so the FE gets the live steps/links in the same tick"
    )


# ── C: chromium sandbox ──────────────────────────────────────────────────────

def test_chromium_sandbox_enabled_on_mac_and_windows():
    src = inspect.getsource(research.Browser.start)
    assert '"chromium_sandbox"' in src and '("darwin", "win32")' in src, (
        "patchright injects --no-sandbox unless chromiumSandbox=true — the "
        "permanent 'unsupported command-line flag' infobar is a bot tell and "
        "shifts page geometry under every vision screenshot (user screenshot "
        "2026-07-13)"
    )
