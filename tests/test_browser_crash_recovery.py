"""Tests for #725 — browser-close mid-run recovery.

Covers the three pure functions the fix introduces:

  * `_is_browser_close_error(exc)` — classifies a Chromium/patchright
    "page or browser went away" exception. Strings are taken VERBATIM from
    the two production crashes that motivated #725 (backend.log /
    backend-2.log): a Phase-1 `Page.evaluate` close on the owner run and a
    `Page.bring_to_front` close on the sharer run. Cross-platform: the strings
    come from the CDP driver, not the OS.

  * `_plan_pipeline_auto_retry(...)` — the single source of truth for "will
    run_pipeline silently retry this failure?", consulted by BOTH the except
    handler (to suppress the card) and the post-finally block (to recurse).
    The headline regression: a browser crash at phase 0/1 (brief not yet
    written → detect_resume_phase==0) MUST be retry-eligible — the legacy
    `1 < phase` gate excluded it, which is exactly why the reported runs
    dead-ended.

  * `_sharer_rehydration_enabled()` — env var OR research_config.json (#725
    item 6; the Windows env var didn't propagate to the relaunched daemon).

Run:  pytest tests/test_browser_crash_recovery.py -v
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


# ── _is_browser_close_error ────────────────────────────────────────────
class _TargetClosedError(Exception):
    """Stand-in for patchright's TargetClosedError (type-name match)."""


def test_classifies_owner_run_phase1_evaluate_close():
    # backend.log:88184 — the owner run's actual Fatal.
    e = Exception("Page.evaluate: Target page, context or browser has been closed")
    assert research._is_browser_close_error(e) is True


def test_classifies_sharer_run_bring_to_front_close():
    # backend-2.log:60361 — the sharer run's actual Fatal.
    e = Exception("Page.bring_to_front: Target page, context or browser has been closed")
    assert research._is_browser_close_error(e) is True


def test_classifies_by_exception_type_name():
    # Message wording could change; the type name still classifies.
    assert research._is_browser_close_error(_TargetClosedError("whatever")) is True


def test_classifies_screenshot_and_context_close_variants():
    for msg in (
        "BrowserContext.close: Target page, context or browser has been closed",
        "Page.screenshot: Target page, context or browser has been closed",
        "Mouse.click: Target page, context or browser has been closed",
    ):
        assert research._is_browser_close_error(Exception(msg)) is True, msg


def test_does_not_classify_unrelated_errors():
    for msg in (
        "Page.goto: net::ERR_NAME_NOT_RESOLVED",
        "Gemini API key is invalid",
        "Timeout 30000ms exceeded waiting for selector",
        "No brief to research",
    ):
        assert research._is_browser_close_error(Exception(msg)) is False, msg


# ── _plan_pipeline_auto_retry ──────────────────────────────────────────
def _qdir(tmp_path, name, *, delivery_status=None, brief=False, links=False,
          stop=False, pause=False):
    """Build a queue_dir on disk that detect_resume_phase will read."""
    q = tmp_path / name
    (q / "documents").mkdir(parents=True, exist_ok=True)
    if delivery_status is not None:
        (q / "delivery.json").write_text(json.dumps({"status": delivery_status}), encoding="utf-8")
    if brief:
        (q / "documents" / "brief.md").write_text("# Research Brief\n\n" + "x" * 200, encoding="utf-8")
    if links:
        (q / "links.json").write_text(json.dumps({"notebook": "https://x"}), encoding="utf-8")
    if stop:
        (q / ".stop").write_text("", encoding="utf-8")
    if pause:
        (q / ".pause").write_text("", encoding="utf-8")
    return q


def test_browser_crash_phase0_brief_not_written_IS_eligible(tmp_path):
    # THE #725 regression: empty queue_dir → detect_resume_phase==0. The
    # legacy `1 < phase` gate excluded this; a browser crash here MUST retry.
    q = _qdir(tmp_path, "run-phase0")
    will, phase, is_crash = research._plan_pipeline_auto_retry(
        q, resume_dir=str(q), failure_kind="browser_crash", crash_retries=0)
    assert phase == 0
    assert is_crash is True
    assert will is True


def test_browser_crash_first_attempt_eligible_with_brief(tmp_path):
    # brief present → detect==2. Crash, budget fresh → retry.
    q = _qdir(tmp_path, "run-phase2", brief=True)
    will, phase, _ = research._plan_pipeline_auto_retry(
        q, resume_dir=str(q), failure_kind="browser_crash", crash_retries=0)
    assert phase == 2 and will is True


def test_browser_crash_budget_exhausted_escalates(tmp_path):
    # crash_retries == MAX → no more silent retries → escalate (card shown).
    q = _qdir(tmp_path, "run-exhausted")
    will, _, is_crash = research._plan_pipeline_auto_retry(
        q, resume_dir=str(q), failure_kind="browser_crash",
        crash_retries=research.BROWSER_CRASH_MAX_RETRIES)
    assert is_crash is True
    assert will is False


def test_browser_crash_retries_below_budget_still_eligible(tmp_path):
    q = _qdir(tmp_path, "run-mid-budget")
    will, _, _ = research._plan_pipeline_auto_retry(
        q, resume_dir=str(q), failure_kind="browser_crash",
        crash_retries=research.BROWSER_CRASH_MAX_RETRIES - 1)
    assert will is True


def test_normal_failure_first_run_one_shot_retry(tmp_path):
    # Non-crash failure, first run (resume_dir None), phase 3 → one-shot retry.
    q = _qdir(tmp_path, "run-normal-first", links=True)
    will, phase, is_crash = research._plan_pipeline_auto_retry(
        q, resume_dir=None, failure_kind="", crash_retries=0)
    assert phase == 3 and is_crash is False and will is True


def test_normal_failure_on_resume_escalates(tmp_path):
    # Non-crash failure on a resume attempt (resume_dir set) → no auto-retry,
    # surface the card. This is the existing one-shot policy, unchanged.
    q = _qdir(tmp_path, "run-normal-resume", links=True)
    will, _, _ = research._plan_pipeline_auto_retry(
        q, resume_dir=str(q), failure_kind="", crash_retries=0)
    assert will is False


def test_normal_failure_phase0_not_eligible(tmp_path):
    # A non-crash failure at phase 0/1 is a setup/brief issue — a blind retry
    # rarely helps, so surface to the user (only crashes retry at phase 0/1).
    q = _qdir(tmp_path, "run-normal-p0")
    will, phase, _ = research._plan_pipeline_auto_retry(
        q, resume_dir=None, failure_kind="", crash_retries=0)
    assert phase == 0 and will is False


def test_terminal_delivery_status_never_retries(tmp_path):
    for st in ("completed", "stopped", "paused"):
        q = _qdir(tmp_path, f"run-{st}", delivery_status=st, brief=True)
        will, _, _ = research._plan_pipeline_auto_retry(
            q, resume_dir=str(q), failure_kind="browser_crash", crash_retries=0)
        assert will is False, st


def test_stop_and_pause_sentinels_block_retry(tmp_path):
    q_stop = _qdir(tmp_path, "run-stop", brief=True, stop=True)
    q_pause = _qdir(tmp_path, "run-pause", brief=True, pause=True)
    for q in (q_stop, q_pause):
        will, _, _ = research._plan_pipeline_auto_retry(
            q, resume_dir=str(q), failure_kind="browser_crash", crash_retries=0)
        assert will is False


def test_no_queue_dir_is_noop():
    will, phase, is_crash = research._plan_pipeline_auto_retry(
        None, resume_dir=None, failure_kind="browser_crash", crash_retries=0)
    assert (will, phase, is_crash) == (False, 0, True)


# ── _sharer_rehydration_enabled ────────────────────────────────────────
def test_sharer_rehydration_on_by_default(monkeypatch, tmp_path):
    # #725: flipped default-ON after live validation. No env, config has no
    # flag → enabled.
    cfg = tmp_path / "research_config.json"
    cfg.write_text(json.dumps({"deviceId": "d1"}), encoding="utf-8")
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", cfg)
    monkeypatch.delenv("ENABLE_SHARER_REHYDRATION", raising=False)
    assert research._sharer_rehydration_enabled() is True


def test_sharer_rehydration_on_when_no_config_file(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.delenv("ENABLE_SHARER_REHYDRATION", raising=False)
    assert research._sharer_rehydration_enabled() is True


def test_sharer_rehydration_env_var_arms(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", tmp_path / "research_config.json")
    monkeypatch.setenv("ENABLE_SHARER_REHYDRATION", "1")
    assert research._sharer_rehydration_enabled() is True


def test_sharer_rehydration_env_disables(monkeypatch, tmp_path):
    # Explicit env opt-out wins even over a config that says true.
    cfg = tmp_path / "research_config.json"
    cfg.write_text(json.dumps({"enableSharerRehydration": True}), encoding="utf-8")
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", cfg)
    for val in ("0", "false", "off", "no"):
        monkeypatch.setenv("ENABLE_SHARER_REHYDRATION", val)
        assert research._sharer_rehydration_enabled() is False, val


def test_sharer_rehydration_config_false_opts_out(monkeypatch, tmp_path):
    cfg = tmp_path / "research_config.json"
    cfg.write_text(json.dumps({"enableSharerRehydration": False}), encoding="utf-8")
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", cfg)
    monkeypatch.delenv("ENABLE_SHARER_REHYDRATION", raising=False)
    assert research._sharer_rehydration_enabled() is False
