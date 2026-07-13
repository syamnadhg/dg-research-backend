"""#947 — new podcasts shipped with durationSec: 0, freezing the FE player.

E2E 2026-07-12: every podcast generated on the macOS worker played fine but
its progress bar + clock were stuck at 0:00. Root cause: run_phase3_audio
probes duration with `subprocess.run(["ffprobe", ...])`; the BE runs under a
launchd LaunchAgent whose PATH lacks /opt/homebrew/bin (the only ffprobe on
the machine), so the call raised FileNotFoundError, the bare except swallowed
it, and save_audio_to_firestore wrote durationSec: 0. The FE audio store's
seek() clamps currentTime to duration, so 0 pinned every timeupdate to 0.

Fix (BE half): `_ffprobe_bin()` resolves ffprobe via shutil.which with
/opt/homebrew/bin, /usr/local/bin, /usr/bin fallbacks; both probe sites use
it, and the P3 site logs a WARN instead of swallowing silently. (FE half:
AudioMiniPlayer self-heals duration from the media's loadedmetadata and
writes the corrected durationSec back to the audio doc.)

Run: pytest tests/test_podcast_duration_probe_947.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def test_ffprobe_bin_falls_back_to_homebrew_path(monkeypatch):
    # Simulate the launchd environment: bare PATH (which() misses) but the
    # homebrew binary exists on disk.
    monkeypatch.setattr(research.shutil, "which", lambda _: None)
    real_exists = os.path.exists
    monkeypatch.setattr(research.os.path, "exists",
                        lambda p: p == "/opt/homebrew/bin/ffprobe" or real_exists(p) is False)
    assert research._ffprobe_bin() == "/opt/homebrew/bin/ffprobe", (
        "with ffprobe off PATH, _ffprobe_bin must fall back to the "
        "/opt/homebrew/bin install (the launchd-PATH incident)"
    )


def test_ffprobe_bin_prefers_which(monkeypatch):
    monkeypatch.setattr(research.shutil, "which",
                        lambda _: "/somewhere/ffprobe")
    assert research._ffprobe_bin() == "/somewhere/ffprobe"


def test_ffprobe_bin_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(research.shutil, "which", lambda _: None)
    monkeypatch.setattr(research.os.path, "exists", lambda _: False)
    assert research._ffprobe_bin() is None


def test_p3_audio_probe_uses_resolver_and_warns():
    src = inspect.getsource(research.run_phase3_audio)
    assert "_ffprobe_bin()" in src, (
        "run_phase3_audio must resolve ffprobe via _ffprobe_bin — the bare "
        '["ffprobe", ...] argv silently failed under launchd (durationSec: 0)'
    )
    assert '["ffprobe"' not in src, "no bare ffprobe argv may remain"
    assert "duration probe failed" in src, (
        "a failed duration probe must WARN — the silent except is what let "
        "durationSec: 0 ship unnoticed"
    )


def test_snapshot_scan_probe_uses_resolver():
    mod_src = inspect.getsource(research)
    # No bare-argv ffprobe invocation may remain anywhere (the docstring of
    # _ffprobe_bin mentions the old form; match the executable argv shape).
    assert '["ffprobe", "-v"' not in mod_src, (
        "every ffprobe invocation must go through _ffprobe_bin()"
    )
    # The queue-dir podcasts scan uses the resolver too.
    assert mod_src.count("_ffprobe = _ffprobe_bin()") >= 2, (
        "both probe sites (run_phase3_audio + the podcasts scan) must "
        "resolve via _ffprobe_bin"
    )
