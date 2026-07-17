"""#945 — two E2E failures from the 2026-07-11 FIFA run (backend.log wk1).

A) NotebookLM upload was fail-open end to end: an Anthropic API 500 killed
   the gemini.md CUA task at iteration 4 (15:28:50) BEFORE the file dialog
   opened; agent_loop returned an error dict that both P3 call sites
   discarded; clear_upload_file wiped the still-armed file; and the
   red-state-only source verify passed the 2/3 notebook as "all sources OK"
   (a never-uploaded source has no row, hence no red icon). Fix: DOM-first
   upload (create notebook + hidden input[type=file] + source-row census),
   per-file deterministic verification with a row-watcher abort_event on the
   CUA fallback, manifest-aware census in _verify_and_repair_nlm_sources
   (missing == failed), transient-5xx retries in agent_loop, DOM-first
   rename (NLM's title input ignores Ctrl+A — FIFA title shipped mangled),
   and a hard raise → Retry/Skip card when sources are still missing.

B) Claude completion detection was blind for ~24 min (report done 15:01:43,
   confirmed 15:26:07): detect_completion_claude's liveActive ticker check
   ("N sources and counting" — kept alive by OUR OWN kept-open tracking
   panel) unconditionally vetoed before any done-marker was consulted, and
   the snapshot selectors were the pre-#914 class vocabulary (all zeros on
   the 2026-07 layout → the #921 empty-snapshot guard refused done anyway).
   Fix: geometry panel root back-ported into the detector, marker-over-
   ticker ordering, artifact-header Copy+Publish affordance marker
   (ticker-gated), _claude_modern_marker hoisted to a shared helper consulted
   at done_count==1, the stuck arbiter no longer stamps last_cua_check, and
   the pre-CUA scroll covers the virtualized panel.

Run: pytest tests/test_p3_upload_and_claude_done_945.py -v
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


# ── A1: DOM-first NotebookLM upload machinery exists and is wired ────────────

def test_nlm_dom_helpers_exist():
    for helper in ("_nlm_dom_upload_sources", "_nlm_dom_add_files",
                   "_nlm_visible_source_names", "_nlm_close_dialogs",
                   "_nlm_dom_rename", "_nlm_click_first"):
        assert hasattr(research, helper), (
            f"{helper} missing — the DOM-first NotebookLM path (2026-07-11 "
            "FIFA incident) is gone"
        )


def test_p3_runs_dom_first_before_cua():
    src = inspect.getsource(research.run_phase3_upload)
    dom = src.index("_nlm_dom_upload_sources")
    cua = src.index("nlm-create-upload")
    assert dom < cua, (
        "run_phase3_upload must attempt the DOM-first upload BEFORE any CUA "
        "vision task — CUA is the fallback tier, not the primary"
    )
    # Only files the DOM census could NOT confirm go to the CUA fallback.
    assert "_remaining" in src and "_dom_uploaded" in src


def test_p3_captures_cua_result_and_verifies_per_file():
    src = inspect.getsource(research.run_phase3_upload)
    # The FIFA bug: bare `await _shadow_observed_cua(...)` discarded the
    # error dict. The result must now be captured...
    assert "_cua_res = await _shadow_observed_cua(" in src, (
        "P3 upload call sites must capture the CUA result — a returned "
        "{'status':'error'} dict is otherwise indistinguishable from success"
    )
    # ...and each file must be deterministically DOM-verified afterwards.
    assert "NOT visible after CUA task" in src, (
        "each CUA-fallback upload must be followed by a per-file DOM census "
        "— the API-500-killed gemini.md task left no other trace"
    )


def test_p3_cua_fallback_gets_row_watcher_abort():
    src = inspect.getsource(research.run_phase3_upload)
    assert "abort_event=_row_evt" in src, (
        "the CUA upload missions must carry the row-watcher abort_event — "
        "without it the loop burns every remaining iteration re-clicking "
        "'Upload files' against an empty queue (6 warnings / ~4 wasted "
        "minutes in the FIFA run)"
    )


def test_p3_raises_on_missing_sources_after_repair():
    src = inspect.getsource(research.run_phase3_upload)
    assert "_still_missing" in src and "raise RuntimeError(" in src, (
        "P3 must raise (→ the existing fail_phase Retry/Skip card) when "
        "sources are still missing after upload + repair — the FIFA run "
        "silently shipped a 2/3 notebook"
    )
    # The raise must NOT contain login-classifier keywords, or the card
    # would mislabel a missing-source failure as a sign-in problem.
    m = re.search(r'raise RuntimeError\(\s*f?"([^"]+)"', src)
    assert m, "missing-source raise not found"
    low = m.group(1).lower()
    for kw in ("login", "signin", "auth", "unauthor"):
        assert kw not in low, (
            f"missing-source raise contains '{kw}' — the except at the retry "
            "loop would misclassify it as a login error"
        )


# ── A2: manifest-aware verify (missing == failed) ────────────────────────────

def test_verify_census_runs_before_red_state_probe():
    src = inspect.getsource(research._verify_and_repair_nlm_sources)
    census = src.index("_nlm_census_settled")
    red = src.index("PROMPT_NOTEBOOKLM_VERIFY_SOURCES")
    assert census < red, (
        "the DOM census against the expected manifest must run BEFORE the "
        "red-state CUA probe — a never-uploaded source has no row and no red "
        "icon, so the vision probe alone passes a partial notebook"
    )
    # The census must also close leftover modals (the FIFA verify ran behind
    # an open Add-sources dialog).
    assert "_nlm_close_dialogs" in src
    # And the function must report what is still missing to the caller.
    assert "return set()" in src, "healthy paths must return an empty set"


def test_verify_runs_census_even_without_cua_client():
    src = inspect.getsource(research._verify_and_repair_nlm_sources)
    # The old guard `if not cua_client or not md_files: return` skipped
    # EVERYTHING without a CUA client; the census is pure DOM and must run.
    assert "if not md_files:" in src
    assert "if not cua_client or not md_files" not in src, (
        "verify must not skip the DOM census when no CUA client is available"
    )


def test_verify_mission_carries_expected_manifest():
    src = inspect.getsource(research._verify_and_repair_nlm_sources)
    assert "expected to contain exactly these" in src, (
        "the red-state CUA mission must enumerate the expected manifest so "
        "vision can flag ABSENT sources too"
    )


# ── A3: agent_loop retries transient 5xx ─────────────────────────────────────

def test_agent_loop_retries_transient_5xx():
    src = inspect.getsource(research.agent_loop)
    assert "transient_api_retries" in src, (
        "agent_loop must retry transient server-side 5xx errors — a single "
        "mid-mission 500 used to silently terminate the whole CUA task "
        "(FIFA 15:28:50: gemini.md never reached the file dialog)"
    )
    assert "error code:\\s*5\\d\\d" in src
    assert "transient_api_retries < 3" in src, "5xx retries must be bounded"
    # (review r2) the retry must live in an INNER loop around the create
    # call so it doesn't burn mission iterations (a 500 on the final
    # iteration used to exit as max_iterations without retrying), and it
    # must not swallow the 429/529 classes handled by the outer branches.
    create_idx = src.index("client.beta.messages.create")
    inner_loop = src.rindex("while True:", 0, create_idx)
    assert src.index("transient_api_retries < 3") > inner_loop, (
        "the 5xx retry must be inside the inner while-True around the "
        "create call, not the outer iteration loop"
    )
    assert "not (_is_rate_limit or _is_overload)" in src, (
        "the inner 5xx retry must exclude 429/529/rate-limit (#61 gives those "
        "their own in-place bounded retry + paused-blocker escalation)"
    )


# ── A4: DOM-first rename ─────────────────────────────────────────────────────

def test_rename_tries_dom_before_cua():
    src = inspect.getsource(research.run_phase3_upload)
    assert "if not await _nlm_dom_rename(page, title):" in src, (
        "rename must be DOM-first — NLM's title input ignores Ctrl+A, so CUA "
        "typing APPENDS (FIFA shipped 'FIFA World Cup Evolution And "
        "EconomicsThe FIFA W')"
    )


def test_dom_rename_uses_native_value_setter():
    src = inspect.getsource(research._nlm_dom_rename)
    assert "HTMLInputElement.prototype" in src and "dispatchEvent" in src, (
        "_nlm_dom_rename must set the input value natively + fire Angular-"
        "visible events — keyboard select-all is what failed in the FIFA run"
    )
    # (review r2) success needs a delayed READ-BACK from a fresh DOM query —
    # `inp.value === title` right after the setter is near-tautological and
    # would skip the CUA fallback exactly when Angular reverts the value.
    assert "read-back" in src.lower()
    assert src.index("asyncio.sleep") < src.index("committed"), (
        "the rename read-back must happen after a settle delay"
    )


# ── A5 (review r2): census settling + click-priority hardening ───────────────

def test_census_settled_helper_polls():
    src = inspect.getsource(research._nlm_census_settled)
    assert "_nlm_visible_source_names" in src and "asyncio.sleep" in src, (
        "_nlm_census_settled must poll — single-shot censuses raced async "
        "ingestion (duplicate re-adds + a spurious final failure card)"
    )
    # The verify path and the per-file post-CUA check must both use it.
    vsrc = inspect.getsource(research._verify_and_repair_nlm_sources)
    assert vsrc.count("_nlm_census_settled") >= 2, (
        "verify rounds AND the final honest census must settle-poll"
    )
    psrc = inspect.getsource(research.run_phase3_upload)
    assert "_nlm_census_settled" in psrc, (
        "the per-file post-CUA check must settle-poll before re-adding"
    )


def test_click_js_pattern_order_is_authoritative():
    js = research._NLM_CLICK_JS
    assert js.index("for (const p of patterns)") < js.index("for (const scope of scopes)"), (
        "the pattern loop must be outermost — DOM order beat pattern "
        "specificity pre-fix, letting a stray mat-icon 'add' button shadow "
        "the real Add-source control"
    )
    assert "norm" in js, "textContent must be icon-ligature-normalized"


def test_add_files_has_no_bare_add_pattern():
    src = inspect.getsource(research._nlm_dom_add_files)
    assert 'r"^add\\b"' not in src, (
        "bare '^add' matches every mat-icon '+' button (ligature text) — "
        "dropped in review r2"
    )


def test_row_watch_requires_notebook_url_and_structured_rows():
    src = inspect.getsource(research.run_phase3_upload)
    anchor = src.index("_row_watch")
    block = src[anchor:anchor + 1200]
    assert '"/notebook/" not in' in block, (
        "the row watcher must ignore censuses taken off the notebook page "
        "(home-page cards can contain the filename stem)"
    )
    assert "_rows != -1" in block, (
        "the row watcher must require structured source rows — the body-"
        "text fallback can match a transient '<name> failed' toast"
    )


# ── B1: Claude detector — marker-over-ticker + geometry snapshot ─────────────

def test_claude_detector_has_geometry_snapshot():
    src = inspect.getsource(research.detect_completion_claude)
    assert "getBoundingClientRect" in src and "geoPanel" in src, (
        "detect_completion_claude must carry the #914 geometry panel scan — "
        "the 2026-07 layout matches no artifact class names, so the legacy "
        "selectors read snap 0/0/0 and the #921 guard structurally refused "
        "done (FIFA: detector blind 24 min while the geo walker read 15 steps)"
    )
    # Same gates as _bestGeoPanel: right-docked, capped width, no chat markers.
    assert "vw * 0.75" in src and "vw * 0.22" in src
    assert 'data-message-author-role="user"' in src


def test_claude_detector_marker_overrides_stale_ticker():
    src = inspect.getsource(research.detect_completion_claude)
    # ONLY the anchored markers may override the ticker (review r2: the
    # loose 'research complete' regex matches launch prose like "once the
    # research completes", proven executable to a mid-run false done).
    assert "if live_active and not anchored:" in src, (
        "the live-ticker veto must yield ONLY to anchored done-markers — "
        "the kept-open tracking panel freezes 'N sources and counting' in "
        "body text after completion (FIFA: ticker + 'Research complete · N "
        "sources' coexisted for 20+ min)"
    )
    assert "anchoredDone" in src, (
        "the detector JS must compute the anchored marker form "
        "('research complete · N sources' / Boom!) separately from the "
        "loose prose-matchable regex"
    )
    assert "stale live-ticker overridden" in src, (
        "a done verdict that overrode the ticker must say so in its reason "
        "string (log-greppable postmortems)"
    )
    # The loose regex must carry a word boundary so 'the research completes'
    # (Claude's own launch prose) cannot match.
    assert "research\\\\s+complete(?:d)?\\\\b" in src, (
        "the loose researchDone regex needs a trailing \\b — without it "
        "'complete' matches inside 'completes' (review-confirmed false done)"
    )


def test_claude_detector_tracker_fed_snapshot_guard():
    src = inspect.getsource(research.detect_completion_claude)
    assert "tracker_fed_snapshot_weak_marker" in src, (
        "when the ONLY content evidence is the tracking-shaped geo panel "
        "(legacy selectors all zero) and the marker is not anchored, the "
        "detector must refuse done — geo numbers from the tracker otherwise "
        "structurally disarm the #921 empty-snapshot guard (review r2)"
    )
    assert "legacyEmpty" in src and "geoIsTracker" in src


def test_claude_detector_affordances_are_ticker_gated():
    src = inspect.getsource(research.detect_completion_claude)
    assert "artifactAffordances" in src
    assert 'affordances = bool(data.get("artifactAffordances")) and not live_active' in src, (
        "the Copy+Publish header affordance marker must NOT override a live "
        "ticker on its own — a mid-research tracking panel could plausibly "
        "carry header buttons; only the anchored research-complete markers "
        "outrank the ticker"
    )
    # Both Copy AND Publish/Share must be required, scoped to the geo panel's
    # HEADER STRIP with aria-label-or-short-text matching (review r2: a
    # code-block Copy button deep in content or a citation chip titled
    # '…market share…' must not satisfy it).
    assert "hasCopy && hasPublish" in src
    assert "pr.top + 96" in src, "affordance scan must be header-strip scoped"
    assert "bt.length < 30" in src, (
        "textContent matching must be limited to short button labels"
    )


def test_claude_detector_keeps_921_empty_snapshot_guard():
    src = inspect.getsource(research.detect_completion_claude)
    assert "done_marker_but_empty_snapshot" in src, (
        "the #921 empty-snapshot guard must survive the rewrite — a done-"
        "marker on a 0/0/0 snap is the platform-bug false-done (NemoClaw)"
    )


# ── B2: poll-site — shared marker helper + cadence fixes ─────────────────────

def test_modern_marker_hoisted_to_shared_helper():
    assert hasattr(research, "_claude_modern_marker"), (
        "_claude_modern_marker helper missing — the only marker probe that "
        "survived the 2026-07 layout was buried in the CUA-says-done branch"
    )
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert src.count("_claude_modern_marker") >= 2, (
        "the poll loop must consult _claude_modern_marker BOTH at "
        "done_count==1 (corroboration) and in the artifact-count gate"
    )


def test_done_one_of_two_accepts_dom_marker_corroboration():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    anchor = "accepting without a second CUA pass"
    assert anchor in src, (
        "done_count==1 + modern marker in DOM must confirm immediately — "
        "waiting for a second vision pass costs a rotation (~3-10 min) and "
        "one misread resets the counter (FIFA: ~14 min lost to the 15:12 "
        "misread)"
    )
    # The corroboration must set done_count to 2 (fall through to confirmed)
    # and use the STRICT marker form (anchored only — review r2: the card
    # fallback's layout-scoping assumption is too weak to replace a second
    # vision confirmation).
    tail = src[src.index(anchor):src.index(anchor) + 400]
    assert 'p["done_count"] = 2' in tail
    head = src[max(0, src.index(anchor) - 800):src.index(anchor)]
    assert "strict=True" in head, (
        "done_count==1 corroboration must call _claude_modern_marker with "
        "strict=True (anchored forms only)"
    )


def test_stuck_arbiter_no_longer_stamps_last_cua_check():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    m = re.search(r"_confirmed_stuck = bool\(.*?\n(.*?)except", src, re.DOTALL)
    assert m, "stuck-arbiter parse block not found"
    block = m.group(1)
    assert 'p["last_cua_check"] = time.time()' not in block, (
        "the arbiter must NOT stamp last_cua_check — a WORKING verdict used "
        "to defer the completion check a full CUA_CHECK_INTERVAL (FIFA: the "
        "15:17 arbiter pushed the next check to 15:22 on a complete report)"
    )
    assert "deliberately NOT stamping last_cua_check" in block, (
        "the omission must be documented in place so a future refactor "
        "doesn't 'helpfully' restore the stamp"
    )


def test_pre_cua_scroll_covers_artifact_panel():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    anchor = "CUA checking completion"
    scroll_block = src[src.index(anchor) - 2000:src.index(anchor)]
    assert "aside" in scroll_block and "overflow-y" in scroll_block, (
        "the pre-CUA scroll must include aside/artifact/overflow containers "
        "(parity with the DOM detector's scroll) — the virtualized panel "
        "hides the completion marker from the screenshot otherwise"
    )


def test_claude_platform_hint_teaches_stale_ticker():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "stale 'N sources and counting'" in src, (
        "the Claude CUA platform hint must warn that the kept-open tracking "
        "panel's ticker is NOT evidence of generation — the 15:12 misread "
        "(no stop button, verdict still-generating) reset the confirmation "
        "counter"
    )
