"""The podcast WAS downloaded. The sniffer threw it away (e2e 2026-08-09).

THE EVIDENCE, from Chrome's own history in the pipeline's browser profile:

    08-10 06:03:01 UTC   state=1 (COMPLETE)   3,487,728 / 3,487,728 bytes
    target=/var/folders/.../T/playwright-artifacts-u0H95z/08f967c3-6609-...

06:03 UTC is 23:03 local — the exact minute the run reported "audio file missing".
The download completed. It landed in Playwright's artifacts directory, which
`_audio_search_plan` already scans. The scan ran 34 seconds later, walked that
directory, found the file, and discarded it.

WHY

`_audio_kind` required the ISO-BMFF major brand to be literally `M4A ` or `M4B `.
NotebookLM serves a generic brand. So the file was audio, was ours, was complete —
and did not match a four-byte literal.

That literal arrived in the 2026-08-06 hardening, which was right about the hazard
it was fixing (a recursive scan of the user's Downloads folder plus a `shutil.move`
could have published somebody's holiday video as the podcast) and wrong about the
test for it. The brand does not answer "is this a video?". ffprobe does.

WHY THE 08-06 SUITE DID NOT CATCH IT

Every fixture there is a STUB — `b"\\x00\\x00\\x00\\x20ftypM4A " + b"\\x00" * 4096`.
The audio case was hand-written as `M4A `, so the suite proved that a file with the
brand we assumed would be accepted. It never held a real NotebookLM artifact, and
no assertion said what a real one looks like.

So these tests use REAL media, built with ffmpeg at run time: a genuine AAC audio
file whose brand is `mp42` (not `M4A `), and a genuine video that carries an audio
track. Those two are the whole problem — the first must be accepted and the second
must not, and the brand cannot tell them apart.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research as R  # noqa: E402

_FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
_HAVE_FFMPEG = Path(_FFMPEG).exists()
requires_ffmpeg = pytest.mark.skipif(
    not _HAVE_FFMPEG, reason="ffmpeg needed to build REAL media; stubs cannot prove this"
)


def _run(args):
    subprocess.run([_FFMPEG, *args], capture_output=True, timeout=120, check=True)


@pytest.fixture(scope="module")
def real_audio_generic_brand(tmp_path_factory):
    """A real AAC file whose major brand is NOT `M4A ` — what NotebookLM serves."""
    p = tmp_path_factory.mktemp("m") / "overview.m4a"
    _run(["-f", "lavfi", "-i", "sine=frequency=440:duration=2",
          "-c:a", "aac", "-brand", "mp42", "-y", str(p)])
    return p


@pytest.fixture(scope="module")
def real_video_with_audio(tmp_path_factory):
    """A real video that also has an audio track — the 08-06 hazard, exactly."""
    p = tmp_path_factory.mktemp("v") / "holiday.mp4"
    _run(["-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
          "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
          "-c:v", "libx264", "-c:a", "aac", "-y", str(p)])
    return p



def _probe_says(monkeypatch, *, returncode=0, stdout=""):
    """Pin BOTH halves of the probe: that a probe exists, and what it answered.

    Patching only `subprocess.run` is not enough — `_is_audio_only` returns early
    when `_ffprobe_bin()` finds nothing, so on a machine without ffmpeg the fake
    is never reached and the test silently exercises the no-tool path instead of
    the one it names. That is exactly how two of these passed locally and failed
    on a runner with no ffmpeg installed.
    """
    class _R:
        pass
    _R.returncode = returncode
    _R.stdout = stdout
    monkeypatch.setattr(R, "_ffprobe_bin", lambda: "/nonexistent/ffprobe")
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: _R())

# ── the file the pipeline actually threw away ───────────────────────────────

@requires_ffmpeg
def test_the_brand_really_is_not_M4A(real_audio_generic_brand):
    """Pin the premise, so this test cannot quietly stop testing anything. If
    ffmpeg ever starts writing `M4A ` here, the file below would be accepted by the
    OLD rule too and the regression test would be proving nothing."""
    head = real_audio_generic_brand.read_bytes()[:12]
    assert head[4:8] == b"ftyp"
    assert head[8:12] not in (b"M4A ", b"M4B "), (
        f"fixture no longer reproduces the failing shape: brand={head[8:12]!r}"
    )


@requires_ffmpeg
def test_real_audio_with_a_generic_brand_is_ACCEPTED(real_audio_generic_brand):
    """THE regression. This exact shape was downloaded, complete, in our own
    directory, and discarded — and the run then reported the audio missing."""
    assert R._audio_kind(real_audio_generic_brand, trusted=True) == ".m4a"


@requires_ffmpeg
def test_and_it_is_accepted_even_from_an_untrusted_directory(real_audio_generic_brand):
    """Trust is the fallback for a box with no ffprobe, not the basis of the
    decision. When ffprobe can answer, the answer stands wherever the file is."""
    assert R._audio_kind(real_audio_generic_brand, trusted=False) == ".m4a"


# ── and the hazard the 08-06 hardening existed to stop ──────────────────────

@requires_ffmpeg
def test_a_real_video_is_still_REFUSED(real_video_with_audio):
    """The whole point of the brand check, kept. A video with an audio track is
    still a video, and `shutil.move` on somebody's Downloads folder is not ours to
    do. Note it would pass a naive "has an audio stream" test — which is why the
    check is audio AND NOT video."""
    assert R._audio_kind(real_video_with_audio, trusted=True) == ""
    assert R._audio_kind(real_video_with_audio, trusted=False) == ""


@requires_ffmpeg
def test_the_video_really_does_carry_an_audio_track(real_video_with_audio):
    """Pins the fixture's teeth. A silent video would be refused by a much weaker
    check and this test would stop meaning anything."""
    out = subprocess.run(
        [shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe", "-v", "error",
         "-show_entries", "stream=codec_type", "-of",
         "default=noprint_wrappers=1:nokey=1", str(real_video_with_audio)],
        capture_output=True, text=True, timeout=60)
    kinds = {l.strip() for l in out.stdout.splitlines() if l.strip()}
    assert "audio" in kinds and "video" in kinds, kinds


# ── bytes that are not media at all ─────────────────────────────────────────

def test_a_zero_filled_mp4_stub_is_refused_even_when_trusted(tmp_path, monkeypatch):
    """An earlier draft of the fix accepted this. ffprobe could not read it, that
    was treated as "cannot say", and directory trust let it through — which is the
    holiday-video hazard wearing a different hat. ffprobe RAN and said no; that is
    an answer, not an absence of one. The 08-06 suite caught this draft.

    The probe is simulated rather than assumed present: a real ffprobe exits
    non-zero on these bytes, and this test is about what we DO with that answer.
    The real-ffprobe version of the same claim is above, under the marker."""
    _probe_says(monkeypatch, returncode=1)
    p = tmp_path / "stub"
    p.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 8192)
    assert R._audio_kind(p, trusted=True) == ""


def test_an_explicit_M4A_brand_still_needs_no_probe(tmp_path):
    """`M4A `/`M4B ` say audio outright. Keeping that path probe-free means the
    common case costs nothing and works on a box without ffprobe."""
    p = tmp_path / "explicit.m4a"
    p.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 8192)
    assert R._audio_kind(p, trusted=False) == ".m4a"


# ── the probe's tri-state ───────────────────────────────────────────────────

@requires_ffmpeg
def test_is_audio_only_separates_cannot_read_from_cannot_ask(
        tmp_path, real_audio_generic_brand, real_video_with_audio, monkeypatch):
    """Three distinct answers, and the difference between the last two is what the
    first draft got wrong:

      True  — audio, no video
      False — ffprobe ran and the answer was no (a video, or unreadable bytes)
      None  — ffprobe is not installed; nobody was asked
    """
    assert R._is_audio_only(real_audio_generic_brand) is True
    assert R._is_audio_only(real_video_with_audio) is False

    junk = tmp_path / "junk"
    junk.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 8192)
    assert R._is_audio_only(junk) is False, "unreadable bytes are a NO, not a maybe"

    monkeypatch.setattr(R, "_ffprobe_bin", lambda: None)
    assert R._is_audio_only(junk) is None, "no tool is a different answer from no"


def test_ffprobe_absent_falls_back_to_directory_trust(tmp_path, monkeypatch):
    """A box with no ffprobe must not repeat the 08-09 outage. The file is ours by
    construction there — the artifacts directory holds only what this run
    downloaded — so it is accepted, and untrusted paths stay strict."""
    monkeypatch.setattr(R, "_ffprobe_bin", lambda: None)
    p = tmp_path / "unknown"
    p.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 8192)
    assert R._audio_kind(p, trusted=True) == ".m4a"
    assert R._audio_kind(p, trusted=False) == ""


# ── the scan passes trust through ───────────────────────────────────────────

@requires_ffmpeg
def test_the_scan_finds_a_generic_brand_file_in_the_trusted_dir(
        tmp_path, real_audio_generic_brand):
    """End to end through `_find_recent_audio`, the function that ran on 08-09 and
    came back empty. The file is GUID-named and extensionless, exactly as Playwright
    saves it."""
    art = tmp_path / "playwright-artifacts-XXXX"
    art.mkdir()
    guid = art / "08f967c3-6609-4f70-a631-870df507ef16"
    guid.write_bytes(real_audio_generic_brand.read_bytes())

    found, ext, may_move = R._find_recent_audio([(art, True, 300, True)])
    assert found == guid, "the scan must find the downloaded podcast"
    assert ext == ".m4a"
    assert may_move is True, "Playwright's own artifacts may be moved, not copied"


@requires_ffmpeg
def test_the_scan_still_refuses_a_video_in_the_users_downloads(
        tmp_path, real_video_with_audio):
    """The other half, at the same seam."""
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "holiday.mp4").write_bytes(real_video_with_audio.read_bytes())
    found, _, _ = R._find_recent_audio([(dl, False, 300, False)])
    assert found is None


def test_a_probe_that_reports_NO_STREAMS_is_a_no(monkeypatch, tmp_path):
    """ffprobe exiting 0 with nothing to say is still an answer: this file has no
    audio. Treating it as "cannot say" hands it to the directory-trust fallback,
    which is how an empty container gets published as the podcast.

    Driven by faking the probe result rather than trying to author a valid MP4 with
    zero streams — the branch under test is the tri-state logic, not ffprobe.
    """
    _probe_says(monkeypatch, returncode=0, stdout="")
    p = tmp_path / "nostreams"
    p.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 8192)
    assert R._is_audio_only(p) is False, "no streams means no, not maybe"
    assert R._audio_kind(p, trusted=True) == "", (
        "a probe that found no streams must not be overridden by directory trust"
    )


def test_the_scan_passes_TRUST_through_not_a_constant(monkeypatch, tmp_path):
    """`_find_recent_audio` must hand each directory's own trust to the sniffer.

    Exercised where trust actually decides: ffprobe unavailable, generic brand. With
    a real audio file the probe answers on its own and the trust argument is never
    consulted — which is why a mutant that hardcoded `trusted=False` survived the
    first version of these tests.
    """
    monkeypatch.setattr(R, "_ffprobe_bin", lambda: None)
    blob = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 8192

    art = tmp_path / "playwright-artifacts-YYYY"
    art.mkdir()
    (art / "guid-named-no-extension").write_bytes(blob)
    found, ext, may_move = R._find_recent_audio([(art, True, 300, True)])
    assert found is not None and ext == ".m4a", (
        "our own artifacts directory must stay usable when ffprobe is absent"
    )

    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "something.mp4").write_bytes(blob)
    assert R._find_recent_audio([(dl, False, 300, False)])[0] is None, (
        "the user's Downloads folder must NOT get the same benefit of the doubt"
    )
