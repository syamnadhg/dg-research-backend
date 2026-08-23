"""Wave 5: a background install's failure had nowhere to be seen.

⛔⛔ "Enable On Startup?" DEFAULTS TO YES, so the common install has no terminal
window at all. Everything this product writes about a failure goes to a file
nobody has been told to open — and when the failure is the supervised process
dying at spawn (a missing dependency, a TCC refusal, an unparseable plist) it
dies BEFORE our own logging exists, so `backend.log` has nothing either.
Whatever launchd or systemd captured on the way down is the entire record.

⛔⛔ AND THAT RECORD REACHED NOBODY, BY THREE SEPARATE ROUTES. Measured
2026-08-22 on this machine:

  * macOS wrote it to `~/Library/Logs/SuperResearch/` — 188 KB of
    `supervisor.out.log` sitting there — and `--send-logs` collects
    `supervisor*.log` from `_logs_root()`, which held none. A support bundle
    from a machine that never came online carried ZERO bytes of it.
  * Linux wrote it to `<install>/logs/`, which for a pipx install is inside
    site-packages: every `--update` deleted the evidence. macOS had already
    moved off that path for exactly that reason; Linux had not.
  * `--doctor` read neither, and answered "daemon-loop not running — see
    Supervisor section above" — a section that reports the plist present and
    launchctl bootstrapped, both TRUE on a machine respawning every ten
    seconds. The pointer led to a section that says nothing is wrong.

⛔ AND THE FIX MAY NOT WIDEN THE COLLECTOR'S ALLOWLIST. That allowlist is what
the consent screen's promise about passwords, cookies and profile data is gated
on. So the supervisor writes where the collector already looks instead, and the
old locations are READ by the doctor and collected by nothing.

Run: pytest tests/test_background_failure_reach_0822.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
#  1. it is written where the bundle already looks
# ══════════════════════════════════════════════════════════════════════════

class TestWhereTheSupervisorWrites:

    def test_it_is_the_one_log_root(self):
        """⛔⛔ THE WHOLE DEFECT IN ONE ASSERTION. The bundle takes
        `supervisor*.log` from `_logs_root()`; anywhere else is a file no
        support call has ever seen."""
        assert research._supervisor_log_dir() == research._logs_root()

    def test_a_supervisor_log_written_there_is_collected(self, tmp_path):
        """⭐ Against the collector itself, not against a claim about it."""
        (tmp_path / "supervisor.err.log").write_text("boom", encoding="utf-8")
        (tmp_path / "supervisor.out.log").write_text("hi", encoding="utf-8")
        names = [p.name for p in research._system_log_tails(root=tmp_path)]
        assert "supervisor.err.log" in names
        assert "supervisor.out.log" in names

    def test_it_is_not_inside_the_install(self):
        """⛔ `<install>/logs` is site-packages for a pipx install, and every
        `--update` reinstall deletes it — which is the evidence for the failure
        an update was meant to fix."""
        install = os.path.realpath(os.path.dirname(research.__file__))
        got = os.path.realpath(str(research._supervisor_log_dir()))
        assert not got.startswith(install + os.sep) and got != install

    def test_it_is_not_in_a_folder_macos_can_refuse(self):
        """⛔⛔ launchd opens StandardOutPath ITSELF, before exec, and that open
        is attributed to launchd — so no TCC grant the user can give will let it
        into a protected folder. A checkout under ~/Downloads made the agent die
        at spawn-init: exit 78, EMPTY logs, respawn every 10s, device never
        online (2026-07-19)."""
        parts = research._supervisor_log_dir().parts
        for protected in ("Downloads", "Desktop", "Documents", "Library"):
            assert protected not in parts, (
                f"{protected} is TCC-gated for a launchd-attributed open")

    @pytest.mark.parametrize("fn", ["_arm_supervisor_macos", "_arm_supervisor_linux"])
    def test_both_platforms_use_the_one_helper(self, fn):
        """⛔ Two opinions about where the supervisor logs is how they came to
        differ in the first place — macOS moved off `<install>/logs` and Linux
        stayed there."""
        src = code_only_deep(getattr(research, fn))
        assert "_supervisor_log_dir()" in src
        assert 'script_dir / "logs"' not in src
        assert '"Library"' not in src

    @pytest.mark.parametrize("fn", ["_arm_supervisor_macos", "_arm_supervisor_linux"])
    def test_the_directory_is_created_before_the_supervisor_opens_it(self, fn):
        """launchd's open happens before exec; a missing directory is exit 78
        with empty logs and a ten-second respawn, which is precisely the failure
        with no evidence."""
        src = code_only_deep(getattr(research, fn))
        assert "log_dir.mkdir(parents=True, exist_ok=True)" in src

    def test_the_names_are_the_ones_the_collector_matches(self):
        """⛔ A rename on either side and the bundle is empty again, silently."""
        for fn in ("_arm_supervisor_macos", "_arm_supervisor_linux"):
            src = code_only_deep(getattr(research, fn))
            assert "supervisor.out.log" in src and "supervisor.err.log" in src
        collector = code_only_deep(research._system_log_tails)
        assert r"^supervisor.*\.log(\.1)?$" in collector


class TestTheOldLocationsAreReadNotCollected:

    def test_the_legacy_list_names_both_of_them(self):
        parts = [p.parts for p in research._legacy_supervisor_log_dirs()]
        assert any("Library" in p for p in parts), "macOS's old location"
        assert any(p[-1] == "logs" and "Library" not in p for p in parts), (
            "the in-install location Linux used")

    def test_nothing_collects_from_them(self):
        """⛔⛔ THE CONSTRAINT. Widening the collector's allowlist is what the
        consent screen's promise about passwords, cookies and profile data is
        gated on — so the old locations are read by a diagnostic and collected
        by nothing."""
        for name in ("_build_log_bundle", "_system_log_tails",
                     "_bundle_source_is_allowed"):
            src = code_only_deep(getattr(research, name))
            assert "_legacy_supervisor_log_dirs" not in src, (
                f"{name} reaches into a directory outside the log root")

    def test_the_allowlist_still_admits_only_the_log_root(self, tmp_path):
        src = code_only_deep(research._bundle_source_is_allowed)
        assert "_logs_root()" in src
        assert "Library" not in src


# ══════════════════════════════════════════════════════════════════════════
#  2. reading the last thing it said
# ══════════════════════════════════════════════════════════════════════════

def _ev(tmp_path, **kw):
    kw.setdefault("log_dir", tmp_path / "new")
    kw.setdefault("legacy_dirs", [tmp_path / "old"])
    return research._supervisor_evidence(**kw)


def _write(d, text):
    d.mkdir(parents=True, exist_ok=True)
    (d / "supervisor.err.log").write_text(text, encoding="utf-8")


class TestReadingTheSupervisorsOwnWords:

    def test_nothing_anywhere_is_an_empty_answer(self, tmp_path):
        got = _ev(tmp_path)
        assert got == {"path": "", "legacy": False, "lines": []}

    def test_it_reads_the_current_location(self, tmp_path):
        _write(tmp_path / "new", "ModuleNotFoundError: No module named 'auth'\n")
        got = _ev(tmp_path)
        assert got["legacy"] is False
        assert "ModuleNotFoundError" in got["lines"][-1]
        assert got["path"].endswith("supervisor.err.log")

    def test_it_falls_back_to_the_old_one_and_says_so(self, tmp_path):
        """⭐ A machine that has not re-run --resurrect still writes to the old
        place. A diagnostic that could not see it would be useless on exactly
        the installs that predate this fix."""
        _write(tmp_path / "old", "Traceback\nRuntimeError: nope\n")
        got = _ev(tmp_path)
        assert got["legacy"] is True
        assert "RuntimeError: nope" in got["lines"][-1]

    def test_the_current_location_wins_when_both_exist(self, tmp_path):
        _write(tmp_path / "new", "the new one\n")
        _write(tmp_path / "old", "the old one\n")
        got = _ev(tmp_path)
        assert got["legacy"] is False
        assert got["lines"] == ["the new one"]

    def test_an_empty_file_is_not_evidence(self, tmp_path):
        """⛔ launchd creates the file at load whether or not anything is
        written to it, so an existing empty log is the ordinary state of a
        healthy machine — and reporting it as the last words would print a
        finding on every machine that has ever been supervised."""
        _write(tmp_path / "new", "")
        _write(tmp_path / "old", "the real answer\n")
        got = _ev(tmp_path)
        assert got["legacy"] is True
        assert got["lines"] == ["the real answer"]

    def test_a_file_of_only_blank_lines_is_not_evidence(self, tmp_path):
        _write(tmp_path / "new", "\n\n   \n\n")
        assert _ev(tmp_path)["lines"] == []

    def test_it_takes_the_END_of_the_file(self, tmp_path):
        """The last exit is the one being diagnosed; the first is from whenever
        this machine was set up."""
        _write(tmp_path / "new", "\n".join(f"line {i}" for i in range(200)) + "\n")
        got = _ev(tmp_path, max_lines=3)
        assert got["lines"] == ["line 197", "line 198", "line 199"]

    def test_it_is_bounded_in_lines(self, tmp_path):
        _write(tmp_path / "new", "\n".join(str(i) for i in range(500)) + "\n")
        assert len(_ev(tmp_path, max_lines=6)["lines"]) == 6

    def test_it_is_bounded_in_bytes(self, tmp_path):
        """⛔ `supervisor.out.log` on this machine is 188 KB and the .err file on
        a crash-looping one grows without limit. A diagnostic that reads the
        whole thing stalls on the machine it exists for.

        ⭐ FOUND BY MUTATION: an earlier version of this had ONE long line
        before the last, so reading from byte zero produced the same answer and
        the bound was never measured. The line cap is deliberately generous
        here, so only the BYTE bound can hold the answer down."""
        _write(tmp_path / "new", "".join(f"L{i:03d}\n" for i in range(400)))
        got = _ev(tmp_path, max_bytes=40, max_lines=200)
        assert len(got["lines"]) <= 10, (
            f"{len(got['lines'])} lines from a 40-byte read — it read the "
            f"whole file")
        assert got["lines"][-1] == "L399"

    def test_a_record_cut_in_half_is_dropped(self, tmp_path):
        """⛔ A truncated first line reads as a different error than the one
        that happened, which is worse than one line fewer."""
        _write(tmp_path / "new",
               "AAAA" * 1000 + "SomeOtherError: not what happened\nreal last\n")
        got = _ev(tmp_path, max_bytes=200, max_lines=6)
        assert all("SomeOtherError" not in x for x in got["lines"]), got["lines"]
        assert got["lines"] == ["real last"]

    def test_a_short_file_keeps_its_first_line(self, tmp_path):
        """⛔ OVER-CORRECTION GUARD. The drop only applies when the read really
        started mid-file — otherwise a two-line crash report loses half of
        itself."""
        _write(tmp_path / "new", "Traceback (most recent call last):\nboom\n")
        assert _ev(tmp_path, max_bytes=8000)["lines"] == [
            "Traceback (most recent call last):", "boom"]

    def test_undecodable_bytes_do_not_stop_it(self, tmp_path):
        d = tmp_path / "new"
        d.mkdir(parents=True)
        (d / "supervisor.err.log").write_bytes(b"\xff\xfe bad bytes\nreadable\n")
        assert "readable" in _ev(tmp_path)["lines"][-1]

    def test_a_directory_of_that_name_is_not_a_log(self, tmp_path):
        d = tmp_path / "new"
        d.mkdir(parents=True)
        (d / "supervisor.err.log").mkdir()
        assert _ev(tmp_path)["lines"] == []

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
    def test_a_file_it_may_not_read_is_an_empty_answer_not_an_exception(
            self, tmp_path):
        """⭐ FOUND BY MUTATION. The earlier version of this used a DIRECTORY of
        that name, which `is_file()` rejects before the open is ever attempted —
        so the handler around the open was never reached. A file with no read
        permission is what actually exercises it, and this runs inside the one
        command a stuck person was told to run."""
        d = tmp_path / "new"
        d.mkdir(parents=True)
        p = d / "supervisor.err.log"
        p.write_text("secret\n", encoding="utf-8")
        p.chmod(0o000)
        try:
            assert _ev(tmp_path)["lines"] == []
        finally:
            p.chmod(0o644)

    def test_it_defaults_to_the_real_locations(self):
        src = code_only_deep(research._supervisor_evidence)
        assert "_supervisor_log_dir()" in src
        assert "_legacy_supervisor_log_dirs()" in src


# ══════════════════════════════════════════════════════════════════════════
#  3. the doctor stops pointing at a section that says nothing is wrong
# ══════════════════════════════════════════════════════════════════════════

def _process_section() -> str:
    src = code_only_deep(research.run_doctor)
    return src[src.index("Process tree"):src.index("Port 8000")]


def test_the_doctor_reads_the_supervisors_own_log():
    """⛔⛔ IT NEVER DID, on either platform, in any location."""
    assert "_supervisor_evidence()" in _process_section()


def test_it_no_longer_points_at_a_section_that_says_nothing_is_wrong():
    """⛔ On a machine respawning every ten seconds the Supervisor section
    reports the plist present and launchctl bootstrapped — both true — so
    "see Supervisor section above" was a pointer to a clean bill of health."""
    section = _process_section()
    assert "see Supervisor section above" not in section


def test_evidence_makes_it_a_failure_rather_than_a_warning():
    """A supervised backend that starts and exits is not a degraded machine, it
    is a machine that does nothing at all."""
    section = _process_section()
    have = section[section.index('if _ev["lines"]:'):]
    have = have[:have.index("else:")]
    assert "_fail(" in have


def test_the_last_words_are_actually_printed():
    """⛔ Reading the evidence and not showing it is the same dead end in a
    more expensive form."""
    section = _process_section()
    assert 'for _evl in _ev["lines"]:' in section
    assert "print(" in section


def test_an_old_location_is_named_with_the_command_that_moves_it():
    """The person can still be helped now, and their next bundle carries it.

    ⛔ FOUND BY MUTATION: asserting `_remedy_resurrect()` anywhere in this
    section was satisfied by an unrelated finding a few lines below — the
    `--serve not running` one prescribes the same command. Scoped to the branch
    that earns it."""
    section = _process_section()
    branch = section[section.index('if _ev["legacy"]:'):]
    branch = branch[:branch.index("else:")]
    assert "--send-logs cannot include it" in branch
    assert "manual_actions.append(_remedy_resurrect())" in branch


def test_with_no_evidence_it_names_the_file_it_looked_in():
    """⭐ "Nothing there either" is a real answer — it rules the whole class
    out — but only if the reader is told which file was checked."""
    section = _process_section()
    tail = section[section.index("else:"):]
    assert "_supervisor_log_dir()" in tail
    assert "supervisor.err.log" in tail


def test_the_printed_lines_are_truncated():
    """A single 40 KB line out of a crash log would redraw the terminal."""
    assert "[:160]" in _process_section()
