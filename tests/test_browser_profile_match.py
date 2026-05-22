"""Unit tests for `_profile_matches_cmdline` — the boundary-match helper
that replaced a bare-substring check in Browser.start()'s orphan-Chrome
sweep and Browser.close()'s fallback kill.

Bug background: prior code did `if our_profile in cmdline` (substring).
Worker 1's profile dir is `…/browser-profile/` (no suffix) and worker
2's is `…/browser-profile-2/`. The substring "browser-profile" IS in
"browser-profile-2/…", so worker 1's sweep wrongly identified worker
2's live Chrome as its own orphan and killed it. The boundary helper
prevents this by requiring the path segment to be followed by '/',
whitespace, or end-of-string.

Run via:
    pytest tests/test_browser_profile_match.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import _profile_matches_cmdline  # noqa: E402


# ── Sanity: same-profile-self matches ──────────────────────────────────

def test_worker1_profile_matches_worker1_cmdline():
    profile = "c:/users/syamn/.super-research/browser-profile"
    cmdline = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline) is True


def test_worker2_profile_matches_worker2_cmdline():
    profile = "c:/users/syamn/.super-research/browser-profile-2"
    cmdline = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile-2/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline) is True


# ── THE BUG: worker 1's profile must NOT match worker 2's cmdline ──────

def test_worker1_profile_does_NOT_match_worker2_cmdline():
    """The 2026-05-22 cross-worker browser-kill bug. browser-profile
    substring would match browser-profile-2 path under the OLD bare-
    substring `in` check; the new helper must reject it."""
    profile = "c:/users/syamn/.super-research/browser-profile"
    cmdline_worker_2 = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile-2/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline_worker_2) is False


def test_worker2_profile_does_NOT_match_worker1_cmdline():
    """Symmetric: worker 2's `browser-profile-2` must not match
    worker 1's `browser-profile/default` cmdline either."""
    profile = "c:/users/syamn/.super-research/browser-profile-2"
    cmdline_worker_1 = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline_worker_1) is False


# ── Higher worker numbers ──────────────────────────────────────────────

def test_worker3_profile_does_NOT_match_worker2_cmdline():
    profile = "c:/users/syamn/.super-research/browser-profile-3"
    cmdline_worker_2 = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile-2/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline_worker_2) is False


def test_worker1_profile_does_NOT_match_worker10_cmdline():
    """Edge: worker 1's `browser-profile` is a prefix of `browser-profile-10`
    too. The boundary check (next char must be '/', ' ', or EOL) catches it."""
    profile = "c:/users/syamn/.super-research/browser-profile"
    cmdline_worker_10 = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile-10/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline_worker_10) is False


# ── Boundary token variants ────────────────────────────────────────────

def test_profile_at_end_of_cmdline_matches():
    """If cmdline ends exactly at the profile path (no trailing slash or
    subdir), still match. Rare but valid for some Patchright invocations."""
    profile = "c:/users/syamn/.super-research/browser-profile"
    cmdline = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile"
    )
    assert _profile_matches_cmdline(profile, cmdline) is True


def test_profile_followed_by_whitespace_matches():
    """Profile arg with whitespace boundary (e.g., positional CLI form)."""
    profile = "c:/users/syamn/.super-research/browser-profile"
    cmdline = (
        "chrome.exe --user-data-dir c:/users/syamn/.super-research/"
        "browser-profile --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline) is True


# ── No-match cases ─────────────────────────────────────────────────────

def test_unrelated_chrome_does_not_match():
    """User's personal Chrome (no super-research path) must not match."""
    profile = "c:/users/syamn/.super-research/browser-profile"
    cmdline = (
        "chrome.exe --user-data-dir=c:/users/syamn/appdata/local/google/"
        "chrome/user data/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline) is False


def test_empty_cmdline_does_not_match():
    profile = "c:/users/syamn/.super-research/browser-profile"
    assert _profile_matches_cmdline(profile, "") is False


# ── Profile with trailing slash (caller normalization variants) ────────

def test_profile_with_trailing_slash_still_matches():
    """If caller passes profile WITH trailing slash, the helper should
    still work (it does .rstrip('/') internally)."""
    profile = "c:/users/syamn/.super-research/browser-profile/"
    cmdline = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline) is True


def test_profile_with_trailing_slash_does_NOT_match_worker2():
    profile = "c:/users/syamn/.super-research/browser-profile/"
    cmdline_worker_2 = (
        "chrome.exe --user-data-dir=c:/users/syamn/.super-research/"
        "browser-profile-2/default --no-sandbox"
    )
    assert _profile_matches_cmdline(profile, cmdline_worker_2) is False
