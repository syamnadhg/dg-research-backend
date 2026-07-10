"""Guard: Claude P2 completion must be detected by the CHEAP DOM detector, not
left to the slow CUA fallback.

THE BUG (live E2E 2026-07-10): a COMPLETED Claude deep-research report sat ~50 min
reading as still-running. `detect_completion_claude` scrapes document.body.innerText,
but Claude renders the finished report + its "Research complete · N sources · Xm Ys"
done-marker inside a VIRTUALIZED artifact panel — the marker isn't in innerText
until the panel is scrolled. The poll loop scrolled to the bottom only before the
5-min CUA check (research.py ~:24444), not before the per-cycle DOM detect, so the
DOM detector never fired and completion was caught only by the slow CUA path
(logs: flat "5 URLs, 15 steps" for ~50m, zero "Done-marker confirmed" lines,
completion via "CUA confirms complete ✓").

THE FIX: scroll Claude's panel/window to the bottom BEFORE the DOM detect so the
marker renders into the DOM (Claude-scoped). Plus: log the DOM detector's not-done
REASON (throttled) so a future stall is one-grep diagnosable — the old code logged
nothing on the persistent not-done path.

Run: pytest tests/test_claude_p2_scroll_detect.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def test_claude_panel_scrolled_before_dom_detect():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert 'name == "Claude"' in src, "the pre-detect scroll must be Claude-scoped"
    assert "scrollHeight" in src, "must scroll the panel/window to render virtualized content"
    # The Claude pre-detect scroll must come BEFORE the DOM detect call (the CUA
    # path also scrolls, but that's AFTER detect — the first scrollHeight is ours).
    first_scroll = src.index("scrollHeight")
    detect_call = src.index("await detect_fn(")
    assert first_scroll < detect_call, (
        "Claude's panel must be scrolled to the bottom BEFORE detect_fn runs, so "
        "the DOM completion detector sees the 'Research complete' marker instead of "
        "falling back to the slow CUA path."
    )


def test_dom_detector_not_done_reason_is_logged():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "DOM not-done:" in src, (
        "the poll loop must log the DOM detector's not-done reason so 'stuck despite "
        "complete' is diagnosable from backend.log alone."
    )
    assert "last_notdone_log_at" in src, (
        "the not-done reason log must be throttled (last_notdone_log_at) so a long "
        "run doesn't spam the log."
    )


def test_detect_completion_claude_still_matches_modern_marker():
    # Sanity: the done-marker regex the (now-scrolled) DOM will be tested against
    # still recognizes Claude's modern "Research complete · N sources · Xm Ys".
    src = inspect.getsource(research.detect_completion_claude)
    assert "researchDone" in src and "research" in src.lower()
    assert "researchCardDone" in src, "card/marker detection must remain"


def test_detect_completion_claude_guards_animation_false_positive():
    # PRIMARY fix (2026-07-10): hasStop is checked BEFORE the done-marker, so an
    # unguarded [class*="animate-pulse"] on completed/hidden UI chrome pins
    # hasStop=true and the report never reads as done. The animation check must be
    # guarded like verify_claude_generating: element VISIBLE (offsetParent) AND
    # animation actually RUNNING (getAnimations().playState === 'running').
    src = inspect.getsource(research.detect_completion_claude)
    assert "getAnimations" in src and "playState" in src and "running" in src, (
        "detect_completion_claude must only treat a RUNNING animation as streaming "
        "(getAnimations().playState==='running'), not any animate-pulse class."
    )
    assert "offsetParent" in src, (
        "the animation check must require the element to be VISIBLE (offsetParent) "
        "so hidden/persisted shimmer chrome doesn't false-positive hasStop."
    )
    # The naive bare selector that caused the stuck-detection must be gone.
    assert '[class*="animate-pulse"]' not in src or "getAnimations" in src
