"""#947 — new podcasts shipped with durationSec: 0, freezing the FE player.

E2E 2026-07-12: every podcast generated on the macOS worker played fine but
its progress bar + clock were stuck at 0:00. Root cause: run_phase3_audio
probes duration with `subprocess.run(["ffprobe", ...])`; the BE runs under a
launchd LaunchAgent whose PATH lacks /opt/homebrew/bin (the only ffprobe on
the machine), so the call raised FileNotFoundError, the bare except swallowed
it, and save_audio_to_firestore wrote durationSec: 0. The FE audio store's
seek() clamps currentTime to duration, so 0 pinned every timeupdate to 0.

Fix (BE half), two layers:
- PERMANENT (user-directed, for pipx wheel installs on clean machines):
  `_audio_duration_sec()` probes with tinytag — pure Python, declared in
  pyproject + requirements so `pipx install superresearch` always has it,
  no ffmpeg / no PATH involved. Verified exact-match vs ffprobe on real
  NotebookLM m4a files. ffprobe (via `_ffprobe_bin()`, which tolerates the
  bare launchd PATH) is a guarded FALLBACK only.
- The P3 site logs a WARN when both probes fail instead of swallowing.
(FE half: AudioMiniPlayer self-heals duration from the media's
loadedmetadata and writes the corrected durationSec back to the audio doc.)

Run: pytest tests/test_podcast_duration_probe_947.py -v
"""
from __future__ import annotations

import inspect
import os
import sys
import wave

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


def test_p3_audio_probe_uses_shared_helper_and_warns():
    src = inspect.getsource(research.run_phase3_audio)
    assert "_audio_duration_sec" in src, (
        "run_phase3_audio must probe via _audio_duration_sec (tinytag "
        "primary / ffprobe fallback) — the bare ffprobe argv silently "
        "failed under launchd (durationSec: 0)"
    )
    assert '["ffprobe"' not in src, "no bare ffprobe argv may remain"
    assert "duration probe failed" in src, (
        "a failed duration probe must WARN — the silent except is what let "
        "durationSec: 0 ship unnoticed"
    )


def test_all_probe_sites_use_shared_helper():
    mod_src = inspect.getsource(research)
    # No bare-argv ffprobe invocation may remain anywhere (the docstring of
    # _ffprobe_bin mentions the old form; match the executable argv shape).
    assert '["ffprobe", "-v"' not in mod_src, (
        "every duration probe must go through _audio_duration_sec()"
    )
    # Both sites: run_phase3_audio (async — passed to to_thread, so no
    # paren) + the podcasts scan (direct call).
    assert "asyncio.to_thread(_audio_duration_sec" in mod_src, (
        "run_phase3_audio must probe via _audio_duration_sec on a thread "
        "(the probe must not block the heartbeat loop — B2)"
    )
    assert "= _audio_duration_sec(f)" in mod_src, (
        "the podcasts scan must probe via _audio_duration_sec"
    )


# ── Permanent fix: pure-Python probe, pip-declared ───────────────────────────

def test_audio_duration_sec_reads_wav_without_ffprobe(tmp_path, monkeypatch):
    # A clean machine: NO ffprobe anywhere. tinytag (a wheel dependency)
    # must still read the duration. WAV via stdlib keeps the test portable.
    monkeypatch.setattr(research, "_ffprobe_bin", lambda: None)
    p = tmp_path / "probe.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * 3)  # 3 seconds
    assert research._audio_duration_sec(p) == 3, (
        "tinytag must probe duration with no ffprobe on the machine — this "
        "is the pipx clean-install guarantee"
    )


def test_audio_duration_sec_returns_zero_when_all_probes_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_ffprobe_bin", lambda: None)
    p = tmp_path / "not-audio.m4a"
    p.write_bytes(b"this is not an audio file")
    assert research._audio_duration_sec(p) == 0


def test_tinytag_is_a_declared_dependency():
    # The permanent guarantee lives in packaging: pipx must install tinytag.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as fh:
        assert '"tinytag>=' in fh.read(), (
            "tinytag must be a [project] dependency — without it a clean "
            "pipx install regresses to the ffprobe-or-nothing probe"
        )
    with open(os.path.join(root, "requirements.txt"), encoding="utf-8") as fh:
        assert "tinytag>=" in fh.read(), (
            "tinytag must be in requirements.txt (source-checkout installs; "
            "kept in sync with pyproject.toml)"
        )
