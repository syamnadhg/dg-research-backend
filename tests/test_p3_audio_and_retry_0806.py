"""Phase 3, second run of 2026-08-06: the audio downloaded and we said it hadn't.

    [21:43:44] Claude: ... The download of the Brief audio overview has begun.
    [21:44:14] [WARN] Download event not received — checking common download dirs...
    [21:44:25] [WARN] Phase 3: audio file missing — auto-retry 1/3 in 5 min
    [21:45:13] [INFO] Command received: RETRY_PHASE phase=3
    [21:48:54] [INFO] Command received: STOP — server will exit after cleanup

Chrome's own history records the download completing at 21:43:40. It went into
Playwright's artifacts directory, under a GUID, with NO EXTENSION — while the
fallback globbed `*.mp3 *.wav *.m4a *.webm` under ~/Downloads. Two independent
reasons it could never match.

Then the user pressed Retry, the backend logged the command, and the wait carried
on sleeping for another three and a half minutes because it watched only
stop / skip / pause. The app showed "restarting" with nothing to acknowledge it,
the paused chrome latched, and the user gave up and pressed Stop.

⭐ Both are the same shape: the system had the answer and no path to hear it.
"""

import asyncio
import inspect
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402

# Real leading bytes, not invented ones.
M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 4096
# Containers that share the same magic and are NOT ours.
MP4_VIDEO = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 4096
HEIC = b"\x00\x00\x00\x20ftypheic" + b"\x00" * 4096
WEBP = b"RIFF\x24\x08\x00\x00WEBP" + b"\x00" * 4096
AVI = b"RIFF\x24\x08\x00\x00AVI " + b"\x00" * 4096
MP3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 4096
WAV = b"RIFF\x24\x08\x00\x00WAVE" + b"\x00" * 4096
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 4096
NOT_AUDIO = b"%PDF-1.7\n" + b"\x00" * 4096


def _write(d: Path, name: str, data: bytes):
    p = d / name
    p.write_bytes(data)
    return p


class TestTheContentSniff:

    @pytest.mark.parametrize("data,ext", [
        (M4A, ".m4a"), (MP3, ".mp3"), (WAV, ".wav"), (WEBM, ".webm"),
    ])
    def test_each_format_is_recognised_without_an_extension(self, tmp_path, data, ext):
        # GUID name, no suffix — exactly what Playwright wrote.
        f = _write(tmp_path, "665ac91e-dbf6-4a34-890e-21c4bfe7a6fa", data)
        assert research._audio_kind(f) == ext

    def test_a_non_audio_file_is_refused(self, tmp_path):
        assert research._audio_kind(_write(tmp_path, "x", NOT_AUDIO)) == ""

    def test_an_empty_file_is_refused(self, tmp_path):
        assert research._audio_kind(_write(tmp_path, "x", b"")) == ""

    def test_a_missing_file_is_refused(self, tmp_path):
        assert research._audio_kind(tmp_path / "nope") == ""


class TestFindingTheDownloadNobodyCouldSee:

    def test_the_extensionless_guid_is_found(self, tmp_path):
        f = _write(tmp_path, "665ac91e-dbf6-4a34-890e-21c4bfe7a6fa", M4A)
        found, ext, _mv = research._find_recent_audio([(tmp_path, True, 300, True)])
        assert found == f and ext == ".m4a"

    def test_the_old_glob_would_have_missed_it(self, tmp_path):
        # Proves the fixture reproduces the defect rather than passing anyway.
        _write(tmp_path, "665ac91e-dbf6-4a34-890e-21c4bfe7a6fa", M4A)
        assert list(tmp_path.glob("*.m4a")) == []
        assert list(tmp_path.glob("*.mp3")) == []

    def test_the_newest_wins(self, tmp_path):
        old = _write(tmp_path, "old", M4A)
        import os
        os.utime(old, (time.time() - 60, time.time() - 60))
        new = _write(tmp_path, "new", MP3)
        found, ext, _mv = research._find_recent_audio([(tmp_path, True, 300, True)])
        assert found == new and ext == ".mp3"

    def test_a_stale_file_is_ignored(self, tmp_path):
        import os
        f = _write(tmp_path, "ancient", M4A)
        os.utime(f, (time.time() - 9999, time.time() - 9999))
        assert research._find_recent_audio([(tmp_path, True, 300, True)]) == (None, "", False)

    @pytest.mark.parametrize("data,what", [
        (MP4_VIDEO, "an mp4 video"), (HEIC, "an iPhone photo"),
        (WEBP, "a webp image"), (AVI, "an avi video"),
    ])
    def test_a_container_that_is_not_audio_is_refused(self, tmp_path, data, what,
                                                      monkeypatch):
        # ⛔ Review finding. The first version keyed on `ftyp` at offset 4 and a
        # bare `RIFF`, which match mp4, mov, heic, avi and webp — and the next
        # step MOVED the file. Someone's holiday video could have been published
        # as the podcast.
        #
        # The probe is pinned, because otherwise this test asserts something that
        # is only true on machines that HAVE ffprobe. `_audio_kind` deliberately
        # falls back to directory trust when no probe exists, so on a bare runner
        # a video stub in the artifacts directory IS accepted — by design, and
        # covered by its own test below. Pinning the probe here keeps this test
        # about the refusal, on every machine, instead of about the toolchain.
        class _R:
            returncode = 1
            stdout = ""
        monkeypatch.setattr(research, "_ffprobe_bin", lambda: "/nonexistent/ffprobe")
        monkeypatch.setattr(research.subprocess, "run", lambda *a, **k: _R())

        _write(tmp_path, "recent-download", data)
        assert research._audio_kind(tmp_path / "recent-download") == "", what
        assert research._find_recent_audio(
            [(tmp_path, True, 300, True)]) == (None, "", False), what

    def test_without_a_probe_the_trusted_directory_is_believed(self, tmp_path,
                                                               monkeypatch):
        """The documented other half, stated out loud rather than left to whichever
        machine happens to run the suite.

        With no ffprobe, an unrecognised container out of Playwright's OWN
        artifacts directory is accepted — that directory holds only what this run
        downloaded, and refusing there is what caused the 08-09 outage. The user's
        Downloads folder gets no such benefit, which is the guard that actually
        protects somebody's holiday video."""
        monkeypatch.setattr(research, "_ffprobe_bin", lambda: None)
        _write(tmp_path, "recent-download", MP4_VIDEO)
        found, ext, _mv = research._find_recent_audio([(tmp_path, True, 300, True)])
        assert found is not None and ext == ".m4a"
        assert research._find_recent_audio(
            [(tmp_path, False, 300, False)]) == (None, "", False)

    def test_a_part_file_is_never_taken(self, tmp_path):
        _write(tmp_path, "podcast.m4a.crdownload", M4A)
        assert research._find_recent_audio(
            [(tmp_path, True, 300, True)]) == (None, "", False)

    def test_a_growing_file_is_not_settled(self, tmp_path):
        f = _write(tmp_path, "growing", M4A)
        assert research._is_settled(f, pause_s=0.05) is True
        # And a file that changes between the two stats is refused.
        import threading
        def _grow():
            time.sleep(0.02)
            with open(f, "ab") as fh:
                fh.write(b"\x00" * 5000)
        t = threading.Thread(target=_grow)
        t.start()
        settled = research._is_settled(f, pause_s=0.2)
        t.join()
        assert settled is False

    def test_a_tiny_file_is_ignored(self, tmp_path):
        # A truncated or placeholder file is not the podcast.
        _write(tmp_path, "stub", b"\x00\x00\x00\x20ftypM4A ")
        assert research._find_recent_audio([(tmp_path, True, 300, True)]) == (None, "", False)

    def test_a_nested_artifacts_layout_is_searched(self, tmp_path):
        # Playwright nests the file one directory down.
        sub = tmp_path / "playwright-artifacts-S5S7O0"
        sub.mkdir()
        f = _write(sub, "665ac91e-dbf6", M4A)
        found, _ext, _mv = research._find_recent_audio([(tmp_path, True, 300, True)])
        assert found == f

    def test_a_missing_directory_is_survivable(self, tmp_path):
        assert research._find_recent_audio([(tmp_path / "nope", True, 300, True), (None, True, 300, True)]) == (None, "", False)

    def test_a_non_audio_file_never_wins(self, tmp_path):
        _write(tmp_path, "report.pdf", NOT_AUDIO)
        assert research._find_recent_audio([(tmp_path, True, 300, True)]) == (None, "", False)


class TestTheUsersDownloadsAreNotOursToTake:
    """⛔ Review finding. A recursive sweep of ~/Downloads plus shutil.move is not
    a fix, it is a hazard. Policy is now per-directory."""

    def _plan(self, tmp_path=None, monkeypatch=None):
        if tmp_path is not None:
            import tempfile as _tf
            monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
            (tmp_path / "playwright-artifacts-S5S7O0").mkdir(exist_ok=True)
        return research._audio_search_plan(object())

    def test_playwright_dirs_may_be_moved_from(self, tmp_path, monkeypatch):
        """OUR OWN context directory is movable and recursed — that is what makes
        the recovery work. Driven through a browser double that reports a context
        directory, because `object()` cannot produce the production condition."""
        own = tmp_path / "ctx-downloads"
        own.mkdir()
        plan = research._audio_search_plan(_browser_with_ctx(own))
        pw = [e for e in plan if e[3] is True]
        assert pw, "nothing is movable — the recovery cannot work"
        assert all(e[1] is True for e in pw), "our own dir should be recursed"
        assert own in [e[0] for e in pw]

    def test_a_SIBLING_runs_artifact_dir_is_scanned_but_never_moved_from(
            self, tmp_path, monkeypatch):
        """⛔ The concurrent-run hazard the old fixture could not see. Another
        worker's `playwright-artifacts-*` may hold a newer audio file that is
        mid-download; `shutil.move` would take it. Scanned, so a file that exists
        is still found — never moved, so it is never stolen."""
        import tempfile as _tf
        monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
        own = tmp_path / "ctx-downloads"
        own.mkdir()
        foreign = tmp_path / "playwright-artifacts-OTHERRUN"
        foreign.mkdir()
        plan = research._audio_search_plan(_browser_with_ctx(own))
        entry = next(e for e in plan if e[0] == foreign)
        assert entry[3] is False, "a sibling run's directory is not ours to move from"
        assert entry[1] is True, "still recurse it — the file may genuinely be there"
        assert next(e for e in plan if e[0] == own)[3] is True

    def test_the_human_downloads_folder_is_copy_only(self):
        home = [e for e in self._plan()
                if str(e[0]).endswith("Downloads") and "playwright" not in str(e[0])]
        assert home, home
        for _p, recursive, age, may_move in home:
            assert may_move is False, "never move a file out of someone's Downloads"
            assert recursive is False, "never recurse someone's Downloads"
            assert age <= 120, "keep the human folder's window tight"

    def test_the_call_site_copies_when_it_may_not_move(self):
        """Anchored on the RECOVERY call site, not on the first `_find_recent_audio(`
        in the function.

        This used to take the first occurrence and slice a fixed 1400-char window.
        A second, earlier call was later added — the DOM rung waits for a file to
        appear before deciding whether the visual agent is still needed — and the
        window then landed on that detection loop, which has no copy/move at all.
        The property below was still true; only the locator had rotted. So find the
        site by what makes it the recovery site: it is the one that assigns
        `audio_path`.
        """
        src = inspect.getsource(research.run_phase3_audio)
        i = src.index("_found, _ext, _may_move = _find_recent_audio(")
        block = src[i:src.index("audio_path = dest", i) + 200]
        assert "if _may_move:" in block, block[:400]
        assert "shutil.copy2" in block, block[:400]
        assert "shutil.move" in block, "the artifacts dir is still ours to move from"

    def test_the_call_site_refuses_an_unsettled_file(self):
        src = inspect.getsource(research.run_phase3_audio)
        assert "_is_settled(_found)" in src


def _browser_with_ctx(dirpath):
    """A browser double whose context reports its own download directory.

    ⭐ 2026-08-11. The two tests below used `object()`, so the context lookup
    yielded nothing and the temp-wide glob was the ONLY source of playwright
    directories. That made them assert a production property through a fixture
    that cannot produce the production condition — and it hid the concurrent-run
    hazard entirely: every temp `playwright-artifacts-*` on the host was being
    treated as this run's own, trusted and MOVABLE, so a sibling worker's podcast
    could be moved out from under it mid-download.
    """
    class _Impl:
        _download_dir = str(dirpath)
        _artifacts_dir = None

    class _Ctx:
        _impl_obj = _Impl()

    class _Page:
        context = _Ctx()

    class _Browser:
        page = _Page()

    return _Browser()


class TestTheFallbackLooksWherePlaywrightPuts_It:

    def test_the_temp_artifacts_dirs_are_included(self, tmp_path, monkeypatch):
        # ⭐ Mutation escape. This asserted "playwright-artifacts-" appeared in
        # the source — and it does, in the DOCSTRING, so deleting the line that
        # actually collects those directories survived. Execute it instead.
        # `gettempdir()` caches its answer process-wide, so TMPDIR alone is
        # too late — patch the resolved value.
        import tempfile as _tf
        monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
        art = tmp_path / "playwright-artifacts-S5S7O0"
        art.mkdir()
        # Still collected — not finding a file that exists is what caused the
        # 08-09 outage. It moved seam: `_playwright_download_dirs` now returns
        # only what the CONTEXT reported (movable, trusted), and a temp directory
        # that is not ours arrives through the foreign helper as scan-only. The
        # search plan is where both meet, so assert there.
        plan_paths = [e[0] for e in research._audio_search_plan(object())]
        assert art in plan_paths, plan_paths
        assert art in research._playwright_foreign_artifact_dirs(object())

    def test_a_browser_without_a_context_is_survivable(self):
        # It is called on the failure path, where the page may already be gone.
        assert isinstance(research._playwright_download_dirs(None), list)

    def test_the_audio_path_consults_it(self):
        src = inspect.getsource(research.run_phase3_audio)
        assert "_audio_search_plan(browser)" in src
        assert "_find_recent_audio(" in src


    def test_no_extension_glob_survives_on_that_path(self):
        src = inspect.getsource(research.run_phase3_audio)
        i = src.index("Download event not received")
        block = src[i:i + 1500]
        for pat in ('"*.mp3"', '"*.wav"', '"*.m4a"', '"*.webm"'):
            assert pat not in block, (
                f"{pat} is back — the file we are looking for has no extension"
            )

    def test_the_destination_gains_the_sniffed_extension(self):
        """Anchored on the RECOVERY call site — the one that assigns `audio_path` —
        rather than on the first `_find_recent_audio(` plus a 700-char window.

        A second, earlier call was later added (the DOM rung waits for a file to
        appear before deciding whether the visual agent is still needed), and the
        window then landed on that detection loop, which names no destination. The
        property is unchanged: a GUID-named, extensionless artifact has to arrive
        carrying the extension its BYTES earned, or ffmpeg cannot read it.
        """
        src = inspect.getsource(research.run_phase3_audio)
        i = src.index("_found, _ext, _may_move = _find_recent_audio(")
        block = src[i:src.index("audio_path = dest", i) + 200]
        assert "_found.suffix" in block, block[:400]
        assert "_found.name + _ext" in block, block[:400]


class TestTheWaitCanHearARetry:

    def _controls(self):
        c = research.PipelineControls()
        c.stop_event.clear()
        c.pause_event.clear()
        return c

    def test_a_retry_breaks_the_wait(self):
        c = self._controls()
        c.request_retry_phase(3)
        out = asyncio.run(c.interruptible_sleep(0.05, check_interval=0.01,
                                                retry_phase=3))
        assert out == "retry"

    def test_the_request_is_consumed(self):
        # A flag left set can be cashed later by a soft-warn and restart a phase
        # nobody asked to restart.
        c = self._controls()
        c.request_retry_phase(3)
        asyncio.run(c.interruptible_sleep(0.05, check_interval=0.01, retry_phase=3))
        assert c.consume_retry_phase(3) is False

    def test_another_phases_retry_is_left_alone(self):
        c = self._controls()
        c.request_retry_phase(4)
        out = asyncio.run(c.interruptible_sleep(0.05, check_interval=0.01,
                                                retry_phase=3))
        assert out is None
        assert c.consume_retry_phase(4) is True

    def test_callers_that_do_not_ask_are_unaffected(self):
        # Every pre-existing caller passes no retry_phase and must not start
        # consuming requests meant for someone else.
        c = self._controls()
        c.request_retry_phase(3)
        out = asyncio.run(c.interruptible_sleep(0.05, check_interval=0.01))
        assert out is None
        assert c.consume_retry_phase(3) is True

    def test_stop_still_wins(self):
        c = self._controls()
        c.request_retry_phase(3)
        c.stop_event.set()
        out = asyncio.run(c.interruptible_sleep(0.05, check_interval=0.01,
                                                retry_phase=3))
        assert out == "stop"

    def test_the_audio_wait_asks_for_it(self):
        # The wait lives in run_pipeline, not run_phase3_audio — the retry loop
        # is the ORCHESTRATOR's, which is part of why the command had no consumer.
        src = inspect.getsource(research.run_pipeline)
        i = src.index("_AUDIO_RETRY_INTERVAL_SEC, check_interval=10")
        block = src[i:i + 1200]
        assert "retry_phase=3" in block

    def test_the_audio_wait_restarts_on_it(self):
        """⛔⛔ THIS TEST USED TO ASSERT `"continue" in block` — AND PASSED BECAUSE
        OF THE BUG. `continue` restarts the while loop, jumping straight past the
        retry attempt at the bottom of the body: the press announced a restart,
        spent an auto-retry slot, and ran nothing. Three presses would exhaust
        the budget having never called run_phase3_audio once.

        A presence assertion cannot tell "the branch does the thing" from "the
        branch skips the thing". Walk the AST and assert the branch CANNOT leave
        the loop early."""
        import ast as _ast
        import textwrap as _tw
        tree = _ast.parse(_tw.dedent(inspect.getsource(research.run_pipeline)))
        branch = None
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.If):
                continue
            t = node.test
            if (isinstance(t, _ast.Compare) and isinstance(t.left, _ast.Name)
                    and t.left.id == "_interrupt"
                    and isinstance(t.comparators[0], _ast.Constant)
                    and t.comparators[0].value == "retry"):
                branch = node
                break
        assert branch is not None, "the retry branch is gone"
        leaves = [n for n in _ast.walk(branch)
                  if isinstance(n, (_ast.Continue, _ast.Break, _ast.Return))]
        assert leaves == [], (
            "the retry branch leaves the loop body, so the retry it announced "
            "never runs — fall through to the attempt instead"
        )
        emits = [n for n in _ast.walk(branch)
                 if isinstance(n, _ast.Call) and getattr(n.func, "id", "") == "emit_event"]
        assert emits, "the restart is not announced at all"

    def test_a_user_retry_does_not_spend_an_unattended_attempt(self):
        src = inspect.getsource(research.run_pipeline)
        i = src.index('if _interrupt == "retry":')
        block = src[i:i + 1400]
        assert "_audio_auto_retries = max(0, _audio_auto_retries - 1)" in block, (
            "a person asking for a retry must not consume one of the three "
            "automatic attempts"
        )

    def test_the_auto_restart_is_not_emitted_twice_on_the_retry_path(self):
        src = inspect.getsource(research.run_pipeline)
        i = src.index('reason="auto_retry_audio_missing"')
        assert 'if _interrupt != "retry":' in src[max(0, i - 300):i]
