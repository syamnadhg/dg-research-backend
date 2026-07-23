"""Podcast → mp3 transcode (2026-07-23).

NotebookLM serves the Audio Overview as an .m4a whose `moov` atom sits at the
END of the file, so a CLOUD-hosted agent that STREAMS the URL (rather than
download-then-plays) can't begin playback. run_phase3_audio now transcodes the
downloaded file to a plain CBR mp3 (progressively streamable everywhere) via
`_transcode_audio_to_mp3`, so EVERY agent can stream it regardless of transport.

The switch is deliberately BE-contained: all downstream mime handling is
extension-driven (Storage content-type, the local /audio server, the agent
bridge), so nothing else needed to change and old .m4a runs still resolve.

Guarantees pinned here:
- best-effort + non-raising: missing ffmpeg / non-zero exit / exception all
  fall back to delivering the ORIGINAL file (never lose the podcast);
- on success exactly ONE file remains (source deleted) so save_meta's
  `podcasts/*.*` glob can't double-count the same podcast;
- idempotent for an input already ending .mp3;
- the transcode runs off-thread and BEFORE the Storage upload, so the mp3
  (not the m4a) is what gets uploaded / streamed.

Run: pytest tests/test_podcast_mp3_transcode.py -v
"""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── _ffmpeg_bin: mirror the _ffprobe_bin launchd-PATH resilience ──────────────

def test_ffmpeg_bin_prefers_which(monkeypatch):
    monkeypatch.setattr(research.shutil, "which", lambda _: "/somewhere/ffmpeg")
    assert research._ffmpeg_bin() == "/somewhere/ffmpeg"


def test_ffmpeg_bin_falls_back_to_homebrew_path(monkeypatch):
    # launchd env: which() misses but the homebrew binary is on disk.
    monkeypatch.setattr(research.shutil, "which", lambda _: None)
    monkeypatch.setattr(research.os.path, "exists",
                        lambda p: p == "/opt/homebrew/bin/ffmpeg")
    assert research._ffmpeg_bin() == "/opt/homebrew/bin/ffmpeg"


def test_ffmpeg_bin_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(research.shutil, "which", lambda _: None)
    monkeypatch.setattr(research.os.path, "exists", lambda _: False)
    assert research._ffmpeg_bin() is None


# ── _transcode_audio_to_mp3 behavior ─────────────────────────────────────────

def test_transcode_success_returns_mp3_and_deletes_source(tmp_path, monkeypatch):
    src = tmp_path / "audio_overview.m4a"
    src.write_bytes(b"fake m4a bytes")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")

    def fake_run(argv, **kw):
        # ffmpeg output path is the last argv element — simulate a good encode.
        assert argv[0] == "/usr/bin/ffmpeg"
        assert "libmp3lame" in argv, "must encode with libmp3lame"
        assert "-map_metadata" in argv, "must carry embedded metadata across"
        Path(argv[-1]).write_bytes(b"ID3 fake mp3 bytes")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    out = research._transcode_audio_to_mp3(src)
    assert out == src.with_suffix(".mp3")
    assert out.exists() and out.stat().st_size > 0
    assert not src.exists(), (
        "the source .m4a must be removed after a successful transcode — "
        "save_meta globs podcasts/*.* and a lingering .m4a would create a "
        "second podcast entry with the same stem"
    )


def test_transcode_idempotent_for_mp3_input(tmp_path, monkeypatch):
    src = tmp_path / "already.mp3"
    src.write_bytes(b"mp3 bytes")
    called = {"ffmpeg": False, "run": False}
    monkeypatch.setattr(research, "_ffmpeg_bin",
                        lambda: called.__setitem__("ffmpeg", True) or "/usr/bin/ffmpeg")
    monkeypatch.setattr(research.subprocess, "run",
                        lambda *a, **k: called.__setitem__("run", True) or _FakeCompleted())
    out = research._transcode_audio_to_mp3(src)
    assert out == src
    assert src.exists()
    assert not called["ffmpeg"] and not called["run"], (
        "an .mp3 input must short-circuit before resolving/invoking ffmpeg"
    )


def test_transcode_falls_back_when_ffmpeg_missing(tmp_path, monkeypatch):
    src = tmp_path / "audio_overview.m4a"
    src.write_bytes(b"orig")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: None)
    out = research._transcode_audio_to_mp3(src)
    assert out == src, "no ffmpeg ⇒ deliver the original m4a unchanged"
    assert src.exists()


def test_transcode_nonzero_exit_keeps_source_and_cleans_partial(tmp_path, monkeypatch):
    src = tmp_path / "audio_overview.m4a"
    src.write_bytes(b"orig")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")

    def fake_run(argv, **kw):
        Path(argv[-1]).write_bytes(b"partial-broken")  # a bad partial mp3
        return _FakeCompleted(returncode=1, stderr="ffmpeg boom")

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    out = research._transcode_audio_to_mp3(src)
    assert out == src, "a failed encode must deliver the original"
    assert src.exists(), "the original must survive a failed transcode"
    assert not src.with_suffix(".mp3").exists(), (
        "a partial/broken mp3 must be removed so save_meta doesn't ship it"
    )


def test_transcode_exception_keeps_source_and_cleans_partial(tmp_path, monkeypatch):
    src = tmp_path / "audio_overview.m4a"
    src.write_bytes(b"orig")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")

    def boom(argv, **k):
        # Write a partial dst BEFORE raising so the except-path cleanup is
        # actually exercised (a bare raise would never create dst, making the
        # 'no leftover mp3' assertion trivially true / non-load-bearing).
        Path(argv[-1]).write_bytes(b"partial-before-crash")
        raise research.subprocess.TimeoutExpired(cmd="ffmpeg", timeout=600)

    monkeypatch.setattr(research.subprocess, "run", boom)
    out = research._transcode_audio_to_mp3(src)
    assert out == src
    assert src.exists()
    assert not src.with_suffix(".mp3").exists(), (
        "the partial mp3 written before the crash must be removed"
    )


def test_transcode_zero_byte_output_keeps_source(tmp_path, monkeypatch):
    # ffmpeg can exit rc==0 having produced a 0-byte file. The `dst.stat().
    # st_size > 0` guard must treat this as a failure — otherwise the source
    # m4a would be deleted and an unplayable empty mp3 returned (silent
    # podcast loss). This pins that guard directly.
    src = tmp_path / "audio_overview.m4a"
    src.write_bytes(b"orig")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")

    def fake_run(argv, **kw):
        Path(argv[-1]).write_bytes(b"")  # 0-byte output despite a "success" rc
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(research.subprocess, "run", fake_run)
    out = research._transcode_audio_to_mp3(src)
    assert out == src, "a 0-byte mp3 with rc==0 must NOT count as success"
    assert src.exists(), "the source must survive when the output is empty"
    assert not src.with_suffix(".mp3").exists(), "the empty mp3 must be removed"


# ── Wiring in run_phase3_audio ────────────────────────────────────────────────

def test_run_phase3_audio_transcodes_off_thread():
    src = inspect.getsource(research.run_phase3_audio)
    call = "audio_path = await asyncio.to_thread(_transcode_audio_to_mp3, audio_path)"
    assert call in src, (
        "the podcast must be transcoded to mp3 via asyncio.to_thread so the "
        "encode never blocks the heartbeat loop"
    )


def test_run_phase3_audio_transcode_is_guarded():
    src = inspect.getsource(research.run_phase3_audio)
    call = "audio_path = await asyncio.to_thread(_transcode_audio_to_mp3, audio_path)"
    window = src[max(0, src.index(call) - 160): src.index(call)]
    assert "if audio_path and audio_path.exists():" in window, (
        "the transcode must be guarded on a real file so a no-audio run "
        "(audio_path None / not downloaded) never invokes ffmpeg"
    )


def test_transcode_precedes_storage_upload_and_probe():
    src = inspect.getsource(research.run_phase3_audio)
    t = src.index("_transcode_audio_to_mp3")
    assert t < src.index("upload_audio_to_storage"), (
        "transcode must run before the Storage upload so the mp3 (not the "
        "m4a) is what the FE/agents stream"
    )
    assert t < src.index("_audio_duration_sec"), (
        "transcode must run before the duration probe so durationSec is "
        "measured on the delivered mp3"
    )


# ── Downstream mime handling stays extension-driven (regression guards) ───────

def test_storage_upload_content_type_maps_mp3():
    src = inspect.getsource(research)
    assert 'audio/mpeg" if filename.lower().endswith(".mp3")' in src, (
        "the Storage upload content-type must map .mp3 → audio/mpeg so a "
        "transcoded podcast serves with the right type"
    )


def test_local_audio_server_mime_map_covers_both_formats():
    src = inspect.getsource(research)
    assert '".mp3": "audio/mpeg"' in src, "the /audio server must serve mp3"
    assert '".m4a": "audio/mp4"' in src, (
        "the /audio server must still serve legacy m4a runs"
    )


# ── save_meta double-count safety net (defends invariant #2 race-independently)

def test_save_meta_dedupes_same_stem_m4a_and_mp3(tmp_path, monkeypatch):
    # If the transcode's source-unlink lost a rare race (Windows AV/indexer
    # lock), podcasts/ can hold BOTH audio_overview.m4a AND audio_overview.mp3.
    # save_meta globs podcasts/*.* — without a dedup it would emit two entries
    # with the same id (stem), a duplicate podcast in meta.json. The scan must
    # keep exactly one per stem, preferring the streamable .mp3 (what actually
    # got uploaded to Storage + the Firestore audios doc).
    monkeypatch.setattr(research, "_audio_duration_sec", lambda _f: 42)
    pod = tmp_path / "podcasts"
    pod.mkdir()
    (pod / "audio_overview.m4a").write_bytes(b"legacy m4a")
    (pod / "audio_overview.mp3").write_bytes(b"streamable mp3")

    research.save_meta(tmp_path, "Test Topic", 3)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    audios = meta.get("audios", [])
    stems = [a["id"] for a in audios]
    assert stems.count("audio_overview") == 1, (
        f"a same-stem m4a+mp3 pair must yield ONE podcast entry, got {stems}"
    )
    the_one = next(a for a in audios if a["id"] == "audio_overview")
    assert the_one["name"].endswith(".mp3"), (
        f"the surviving entry must be the streamable mp3, got {the_one['name']}"
    )


def test_save_meta_keeps_lone_m4a_for_legacy_runs(tmp_path, monkeypatch):
    # A run that predates the mp3 switch (only an .m4a on disk) must still
    # surface its podcast — the dedup is format-agnostic for a lone file.
    monkeypatch.setattr(research, "_audio_duration_sec", lambda _f: 30)
    pod = tmp_path / "podcasts"
    pod.mkdir()
    (pod / "legacy_show.m4a").write_bytes(b"legacy m4a")

    research.save_meta(tmp_path, "Legacy Topic", 3)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    names = [a["name"] for a in meta.get("audios", [])]
    assert names == ["legacy_show.m4a"], f"legacy lone m4a must survive, got {names}"
