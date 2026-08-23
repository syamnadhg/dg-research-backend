"""Wave 5: the search path a supervised run uses is finally written down.

⛔⛔ THE FINDING, from the org review of wave 2. `_supervisor_path_value` bakes
the tool homes FIRST and says out loud what that trades away: anything dropped
in a user-writable directory shadows the OS copy for every supervised child. The
ordering is deliberate and it stands — the alternative reintroduces the bug it
was written for. What was missing is any way to SEE it afterwards:

  * nothing logged the baked value, on any platform, ever;
  * nothing logged the path a running worker actually has;
  * `--doctor` looked at DISPLAY and at nothing else.

So a shadowed audio binary presented as a phase-3 failure that happened only
under the supervisor, and a support bundle from that machine contained not one
byte that could explain it.

⭐⭐ AND ASKING FROM THE DOCTOR IS THE WRONG QUESTION IF YOU ASK IT PLAINLY.
`--doctor` runs in a login shell whose path is not the one a supervised child
gets. The two answers have to be compared: a tool that resolves differently in
each IS the "works in my terminal, fails as a service" report, already localized.

Run: pytest tests/test_search_path_visibility_0822.py -v
"""
from __future__ import annotations

import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


def _mk(dirpath, name, executable=True):
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / (name + (".exe" if sys.platform == "win32" else ""))
    p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if executable:
        p.chmod(0o755)
    else:
        p.chmod(0o644)
    return p


# ══════════════════════════════════════════════════════════════════════════
#  1. every match, not just the winner
# ══════════════════════════════════════════════════════════════════════════

class TestWhichAll:

    def test_it_finds_the_one_that_wins(self, tmp_path):
        a = _mk(tmp_path / "a", "ffmpeg")
        got = research._which_all("ffmpeg", str(tmp_path / "a"))
        assert got == [str(a)]

    def test_it_also_names_the_ones_that_lose(self, tmp_path):
        """⭐⭐ THE WHOLE REASON THIS EXISTS. `shutil.which` answers only the
        first, and the second copy further along is the difference between "not
        installed" and "the wrong one wins" — which is the diagnosis."""
        a = _mk(tmp_path / "a", "ffmpeg")
        b = _mk(tmp_path / "b", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
        assert research._which_all("ffmpeg", path) == [str(a), str(b)]

    def test_order_is_resolution_order_not_alphabetical(self, tmp_path):
        a = _mk(tmp_path / "zzz", "ffmpeg")
        b = _mk(tmp_path / "aaa", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "zzz"), str(tmp_path / "aaa")])
        assert research._which_all("ffmpeg", path) == [str(a), str(b)]

    def test_a_file_that_is_not_executable_is_not_a_match(self, tmp_path):
        """⛔ A non-executable file of the right name is not what runs, and
        reporting it as a shadow would send someone after the wrong thing."""
        _mk(tmp_path / "a", "ffmpeg", executable=False)
        b = _mk(tmp_path / "b", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
        assert research._which_all("ffmpeg", path) == [str(b)]

    def test_a_directory_of_that_name_is_not_a_match(self, tmp_path):
        (tmp_path / "a" / "ffmpeg").mkdir(parents=True)
        assert research._which_all("ffmpeg", str(tmp_path / "a")) == []

    def test_the_same_directory_twice_is_reported_once(self, tmp_path):
        a = _mk(tmp_path / "a", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "a")])
        assert research._which_all("ffmpeg", path) == [str(a)]

    @pytest.mark.parametrize("path", ["", None, os.pathsep, os.pathsep * 4])
    def test_an_empty_path_is_an_empty_answer_not_a_crash(self, path):
        assert research._which_all("ffmpeg", path) == []

    def test_a_hostile_entry_does_not_stop_the_walk(self, tmp_path):
        """This runs inside a diagnostic; a bad entry part way along the path
        must not cost the entries after it.

        ⛔ AND IT NEEDS NO try/except TO BE TRUE. `os.path.isfile` and
        `os.access` both absorb OSError and ValueError internally — including an
        embedded null — and answer False. A guard around them could not fire,
        which mutation proved by surviving one written to test it. The guard was
        removed rather than tested around."""
        good = _mk(tmp_path / "good", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "nope"), "\x00bad",
                                str(tmp_path / "good")])
        assert research._which_all("ffmpeg", path) == [str(good)]

    def test_an_empty_entry_is_not_the_current_directory(self, tmp_path, monkeypatch):
        """⛔ FOUND BY MUTATION. An empty PATH entry means the CURRENT DIRECTORY
        to a shell. This report must not say a tool was found because the person
        happened to be standing next to a file with that name — and the earlier
        empty-path tests could not see it, because the directory they ran in did
        not contain one."""
        _mk(tmp_path, "ffmpeg")
        monkeypatch.chdir(tmp_path)
        assert research._which_all("ffmpeg", os.pathsep) == []
        assert research._which_all("ffmpeg", f"{os.pathsep}{tmp_path}") == [
            str(tmp_path / "ffmpeg")]


# ══════════════════════════════════════════════════════════════════════════
#  2. what the installed supervisor really exports
# ══════════════════════════════════════════════════════════════════════════

class TestReadingTheInstalledEntry:

    @pytest.mark.skipif(sys.platform != "darwin", reason="launchd plist")
    def test_it_reads_the_path_out_of_the_plist(self, tmp_path, monkeypatch):
        """⛔⛔ NOT `_supervisor_path_value()`, and that is the point. The entry
        on disk may have been written by an older build — the value was a
        literal `/usr/local/bin:/usr/bin:/bin` until 2026-08, with no
        `/opt/homebrew/bin` in it — and every supervised child keeps using the
        old one until someone re-runs --resurrect."""
        plist = tmp_path / "agent.plist"
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '  <key>EnvironmentVariables</key>\n'
            '  <dict><key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string></dict>\n'
            '</dict></plist>\n', encoding="utf-8")
        monkeypatch.setattr(research, "_SUPERVISOR_PLIST_PATH", plist)
        assert research._installed_supervisor_path() == "/usr/local/bin:/usr/bin:/bin"

    @pytest.mark.skipif(sys.platform != "darwin", reason="launchd plist")
    def test_a_plist_that_is_not_installed_is_an_empty_answer(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(research, "_SUPERVISOR_PLIST_PATH", tmp_path / "gone.plist")
        assert research._installed_supervisor_path() == ""

    @pytest.mark.skipif(sys.platform != "darwin", reason="launchd plist")
    def test_a_corrupt_plist_is_an_empty_answer_not_an_exception(
            self, tmp_path, monkeypatch):
        """A diagnostic that raises on a broken file is useless on exactly the
        machine that has one."""
        plist = tmp_path / "agent.plist"
        plist.write_bytes(b"<plist>this is not xml")
        monkeypatch.setattr(research, "_SUPERVISOR_PLIST_PATH", plist)
        assert research._installed_supervisor_path() == ""

    @pytest.mark.skipif(sys.platform != "darwin", reason="launchd plist")
    def test_a_plist_with_no_environment_block_is_an_empty_answer(
            self, tmp_path, monkeypatch):
        plist = tmp_path / "agent.plist"
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict><key>Label</key><string>x</string></dict></plist>\n',
            encoding="utf-8")
        monkeypatch.setattr(research, "_SUPERVISOR_PLIST_PATH", plist)
        assert research._installed_supervisor_path() == ""

    def test_the_reader_and_the_writer_agree_on_the_plist_shape(self):
        """⛔ Two opinions about where the value lives and the doctor reports on
        a key nothing writes. Pinned against the writer's own source."""
        writer = code_only_deep(research._arm_supervisor_macos)
        assert "<key>EnvironmentVariables</key>" in writer
        assert "<key>PATH</key>" in writer
        reader = code_only_deep(research._installed_supervisor_path)
        assert '"EnvironmentVariables"' in reader and '"PATH"' in reader

    def test_the_reader_and_the_writer_agree_on_the_unit_shape(self):
        writer = code_only_deep(research._arm_supervisor_linux)
        assert 'Environment="PATH=' in writer
        reader = code_only_deep(research._installed_supervisor_path)
        assert 'Environment="PATH=' in reader

    def test_a_unit_file_is_parsed_the_way_it_is_written(self):
        """⭐ Runs the reader's own regex against a unit built by the writer's
        own f-string, so the two cannot drift apart in a way only Linux sees."""
        reader = code_only_deep(research._installed_supervisor_path)
        pattern = re.search(r'r\'(\^Environment="PATH=[^\']*)\'', reader)
        assert pattern, "the unit-file pattern has been reshaped"
        line = 'Environment="PATH=/opt/homebrew/bin:/usr/bin"'
        m = re.search(pattern.group(1), f"[Service]\n{line}\nRestart=always\n",
                      re.MULTILINE)
        assert m and m.group(1) == "/opt/homebrew/bin:/usr/bin"


# ══════════════════════════════════════════════════════════════════════════
#  3. the report
# ══════════════════════════════════════════════════════════════════════════

class TestTheReport:

    def test_it_names_the_path_in_use(self, tmp_path):
        lines = research._search_path_report(env_path=str(tmp_path), would_bake="")
        assert any(str(tmp_path) in x for x in lines)

    def test_an_empty_path_says_so_rather_than_printing_nothing(self):
        lines = research._search_path_report(env_path="", would_bake="")
        assert "PATH is empty" in lines[0]

    def test_it_names_every_tool_this_product_resolves_by_name(self, tmp_path):
        text = " ".join(research._search_path_report(env_path=str(tmp_path),
                                                     would_bake=""))
        for tool in research._PATH_SENSITIVE_TOOLS:
            assert tool in text

    def test_the_tool_list_is_the_one_the_code_actually_uses(self):
        """⛔⛔ THE LIST THAT ROTS. A binary resolved by name and missing from
        here is a binary whose shadowing nobody can see. Read off the call sites
        rather than trusted."""
        src = inspect.getsource(research)
        by_name = set(re.findall(r'shutil\.which\("([a-z0-9_.-]+)"', src))
        # `superresearch`, `patchright` and `systemd-run` are resolved by name
        # too, but a shadow of those is a broken install rather than a wrong
        # tool — they are not what the audio pipeline shells out to.
        assert set(research._PATH_SENSITIVE_TOOLS) <= by_name, (
            f"{sorted(set(research._PATH_SENSITIVE_TOOLS) - by_name)} is "
            f"reported but never resolved by name")
        for audio in ("ffmpeg", "ffprobe"):
            assert audio in research._PATH_SENSITIVE_TOOLS, (
                "the audio binaries are the ones the review's finding was about")

    def test_a_shadow_names_both_copies(self, tmp_path):
        """⭐⭐ THE LINE THAT DIAGNOSES THE FAILURE. Naming the loser is what
        turns "the audio step behaves differently under the supervisor" into one
        readable fact."""
        a = _mk(tmp_path / "a", "ffmpeg")
        b = _mk(tmp_path / "b", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
        line = next(x for x in research._search_path_report(
            env_path=path, would_bake="") if x.startswith("[path] ffmpeg:"))
        assert str(a) in line and str(b) in line
        assert "shadows" in line

    def test_a_single_copy_is_not_called_a_shadow(self, tmp_path):
        _mk(tmp_path / "a", "ffmpeg")
        line = next(x for x in research._search_path_report(
            env_path=str(tmp_path / "a"), would_bake="")
            if x.startswith("[path] ffmpeg:"))
        assert "shadows" not in line

    def test_a_missing_tool_says_so(self, tmp_path):
        lines = research._search_path_report(env_path=str(tmp_path), would_bake="")
        assert any("ffmpeg: not on this path" in x for x in lines)

    def test_it_says_when_the_path_in_use_is_not_what_we_would_install(
            self, tmp_path):
        """⛔ The gap between them is a machine still running an older build's
        entry, and that gap is the diagnosis nobody could see."""
        lines = research._search_path_report(env_path="/a", would_bake="/b")
        assert any("would use: /b" in x for x in lines)

    def test_it_stays_quiet_when_they_agree(self):
        lines = research._search_path_report(env_path="/a", would_bake="/a")
        assert not any("would use" in x for x in lines)

    def test_every_line_is_its_own_line_and_tagged(self):
        lines = research._search_path_report(env_path="/a", would_bake="/b")
        assert lines and all("\n" not in x for x in lines)
        assert all(x.startswith("[path] ") for x in lines)

    def test_it_reads_the_live_environment_by_default(self, monkeypatch):
        monkeypatch.setenv("PATH", "/sentinel/dir")
        assert "/sentinel/dir" in research._search_path_report(would_bake="")[0]


# ══════════════════════════════════════════════════════════════════════════
#  4. it is written down where a support bundle can find it
# ══════════════════════════════════════════════════════════════════════════

def test_a_worker_writes_its_search_path_at_boot():
    """⛔⛔ IT NEVER DID. Every subprocess a worker starts inherits this path,
    and a support bundle from a machine where the wrong ffmpeg won contained
    nothing that could show it."""
    src = code_only_deep(research.run_server)
    assert "_search_path_report()" in src


def test_it_sits_next_to_the_build_line():
    """They answer the same question — what is this worker actually running —
    and a reader who found one should not have to hunt for the other."""
    src = code_only_deep(research.run_server)
    assert src.index('log(f"[build] {_build}")') < src.index("_search_path_report()")


@pytest.mark.parametrize("fn", ["_arm_supervisor_macos", "_arm_supervisor_linux"])
def test_arming_a_supervisor_says_what_it_baked_in(fn):
    """⛔ The only record of which value a machine actually got used to be the
    plist or the unit file, and a support bundle collects neither."""
    src = code_only_deep(getattr(research, fn))
    assert "_supervisor_path_value()" in src
    assert "baking search path" in src


def test_the_baked_value_is_still_derived_not_written_out():
    """⛔ OVER-CORRECTION GUARD. The ordering is a stated trade and this wave
    does not touch it — only the visibility. A literal here is the exact bug
    `_supervisor_path_value` was written to end."""
    src = code_only_deep(research._supervisor_path_value)
    assert "_lifecycle_path_dirs()" in src
    assert '"/usr/local/bin:/usr/bin:/bin"' not in src


# ══════════════════════════════════════════════════════════════════════════
#  5. the doctor asks the right machine's question
# ══════════════════════════════════════════════════════════════════════════
#
# ⭐⭐ EVERY TEST BELOW CALLS THE DECISION. `run_doctor` cannot be executed — it
# opens a Firestore client, imports patchright and spawns a 60-second Chromium
# probe — so the section used to be pinned by reading its source. Mutation
# showed what that was worth: FIVE mutants gutted the branches one at a time and
# every one of those pins still passed, because the strings they searched for
# survived the gutting. The decisions moved into `_search_path_findings`, and
# `run_doctor` only renders it.


def _find(shell="", sup="", bake="", platform="Darwin", tools=("ffmpeg",)):
    return research._search_path_findings(
        shell_path=shell, supervisor_path=sup, would_bake=bake,
        platform=platform, tools=tools)


def _rows(res, level=None):
    return [r for r in res["rows"] if level is None or r[0] == level]


class TestWhatTheDoctorDecides:

    def test_it_answers_for_the_supervisor_not_for_this_shell(self, tmp_path):
        """⭐⭐ THE ONE THAT MATTERS. The doctor runs in a login shell whose path
        is not the one a supervised child gets. Answering from the shell renders
        the same section and reports on the wrong machine."""
        shell_only = _mk(tmp_path / "shell", "ffmpeg")
        sup_only = _mk(tmp_path / "sup", "ffmpeg")
        res = _find(shell=str(tmp_path / "shell"), sup=str(tmp_path / "sup"),
                    bake=str(tmp_path / "sup"))
        detail = " ".join(x[2] for x in res["rows"]) + " ".join(
            x[1] for x in res["rows"])
        assert str(sup_only) in detail, "it reported on the doctor's own shell"
        assert str(shell_only) in detail, (
            "the shell's answer is what makes the difference legible")

    def test_a_tool_that_differs_between_the_two_is_a_warning(self, tmp_path):
        """This IS the "works in my terminal, fails as a service" report."""
        _mk(tmp_path / "shell", "ffmpeg")
        _mk(tmp_path / "sup", "ffmpeg")
        res = _find(shell=str(tmp_path / "shell"), sup=str(tmp_path / "sup"),
                    bake=str(tmp_path / "sup"))
        warns = _rows(res, "warn")
        assert any("differs under the supervisor" in w[1] for w in warns), warns

    def test_the_same_tool_in_both_is_not_a_warning(self, tmp_path):
        """⛔ OVER-CORRECTION GUARD. Most machines resolve identically, and a
        warning on every one of them is a warning nobody reads."""
        _mk(tmp_path / "both", "ffmpeg")
        res = _find(shell=str(tmp_path / "both"), sup=str(tmp_path / "both"),
                    bake=str(tmp_path / "both"))
        assert _rows(res, "warn") == []
        assert any(r[0] == "ok" and r[1] == "ffmpeg" for r in res["rows"])

    def test_a_shadow_is_a_warning_that_names_the_loser(self, tmp_path):
        a = _mk(tmp_path / "a", "ffmpeg")
        b = _mk(tmp_path / "b", "ffmpeg")
        path = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
        res = _find(shell=path, sup=path, bake=path)
        warn = next(w for w in _rows(res, "warn") if "shadowed" in w[1])
        assert str(a) in warn[2] and str(b) in warn[2]

    def test_an_out_of_date_supervisor_entry_is_a_warning_with_its_remedy(self):
        """⛔ An entry written by an older build keeps every supervised child on
        the old path, and one command rewrites it."""
        res = _find(shell="/x", sup="/old:/bin", bake="/new:/bin")
        assert any("out of date" in w[1] for w in _rows(res, "warn"))
        assert research._remedy_resurrect() in res["actions"]

    def test_a_current_supervisor_entry_is_not_a_warning(self):
        res = _find(shell="/x", sup="/same", bake="/same")
        assert not any("out of date" in w[1] for w in _rows(res, "warn"))
        assert res["actions"] == []
        assert any(r[0] == "ok" and "Supervisor search path" in r[1]
                   for r in res["rows"])

    def test_a_missing_optional_tool_is_a_note_not_a_fault(self, tmp_path):
        """⚠ ffmpeg and ffprobe are both optional — tinytag is the primary
        duration probe and the transcode falls back to the original file.
        Counting their absence would put an issue on the summary line of a
        machine with nothing wrong with it."""
        res = _find(shell=str(tmp_path), sup="", bake="")
        assert _rows(res, "warn") == []
        assert any("not on this path" in r[1] for r in _rows(res, "note"))

    def test_with_no_supervisor_it_says_so_and_reports_this_shell(self, tmp_path):
        _mk(tmp_path / "a", "ffmpeg")
        res = _find(shell=str(tmp_path / "a"), sup="", bake="/whatever")
        assert any("No supervisor installed" in r[1] for r in _rows(res, "note"))
        assert any(r[0] == "ok" and r[1] == "ffmpeg" for r in res["rows"])

    def test_windows_says_the_task_bakes_nothing(self, tmp_path):
        res = _find(shell=str(tmp_path), sup="", bake="", platform="Windows")
        assert any("Scheduled Task bakes no search path" in r[1]
                   for r in _rows(res, "note"))

    def test_every_tool_gets_exactly_one_row(self, tmp_path):
        _mk(tmp_path / "a", "ffmpeg")
        res = _find(shell=str(tmp_path / "a"), sup="", bake="",
                    tools=("ffmpeg", "ffprobe", "uv"))
        named = [r for r in res["rows"] if any(
            r[1].startswith(t) for t in ("ffmpeg", "ffprobe", "uv"))]
        assert len(named) == 3

    def test_every_level_it_emits_is_one_the_renderer_handles(self, tmp_path):
        """⛔ A fourth level would print through the `else`, i.e. silently as a
        dim note — including if it were meant to be a failure."""
        res = _find(shell=str(tmp_path), sup="/a", bake="/b",
                    tools=research._PATH_SENSITIVE_TOOLS)
        assert {r[0] for r in res["rows"]} <= {"ok", "warn", "note"}

    def test_a_shadow_beats_a_difference_when_both_are_true(self, tmp_path):
        """Two copies under the supervisor AND a different one in the shell:
        the shadow is the actionable half, and reporting both would be two
        warnings about one binary."""
        _mk(tmp_path / "a", "ffmpeg")
        _mk(tmp_path / "b", "ffmpeg")
        _mk(tmp_path / "shell", "ffmpeg")
        sup = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
        res = _find(shell=str(tmp_path / "shell"), sup=sup, bake=sup)
        warns = _rows(res, "warn")
        assert len(warns) == 1 and "shadowed" in warns[0][1]


def test_the_doctor_renders_that_decision_and_makes_no_other():
    """⛔ PIN THE CONSUMER. The tests above are worth nothing if `run_doctor`
    still decides for itself."""
    src = code_only_deep(research.run_doctor)
    section = src[src.index("Search path"):src.index("Process tree")]
    assert "_search_path_findings(" in section
    assert "_which_all(" not in section, "the doctor is resolving tools itself"
    assert "shutil.which" not in section


def test_the_doctor_passes_the_supervisors_path_and_the_shells():
    src = code_only_deep(research.run_doctor)
    section = src[src.index("Search path"):src.index("Process tree")]
    assert "_installed_supervisor_path()" in section
    assert 'os.environ.get("PATH", "")' in section
    assert "_supervisor_path_value()" in section


def test_the_renderer_handles_every_level_the_decision_can_emit():
    """⛔ A level with no arm of its own falls through to the `else` and prints
    as a dim note — so a shadowed binary would render, look calm, and never
    reach the issue count or the list of steps. The levels are read off a call
    that produces all three rather than written out here."""
    res = research._search_path_findings(
        shell_path="/nowhere", supervisor_path="/a", would_bake="/b",
        platform="Darwin", tools=research._PATH_SENSITIVE_TOOLS)
    src = code_only_deep(research.run_doctor)
    section = src[src.index("Search path"):src.index("Process tree")]
    emitted = {r[0] for r in res["rows"]}
    assert {"warn", "note"} <= emitted, "the fixture stopped covering both"
    for level in emitted - {"note"}:      # `note` is deliberately the else
        assert f'_lvl == "{level}"' in section, (
            f"the renderer has no arm for {level!r}; it would print as a note")
    assert "else:" in section, "the note arm is the else"


def test_the_doctors_actions_reach_the_summary():
    """An action a finding produces and nobody prints is the empty action list
    this command was criticised for."""
    src = code_only_deep(research.run_doctor)
    section = src[src.index("Search path"):src.index("Process tree")]
    assert 'manual_actions.extend(_spf["actions"])' in section


def test_the_section_runs_on_every_platform():
    """⚠ The Linux DISPLAY section next door is platform-gated, and this one
    must not be: the shadowing trade applies wherever a supervisor is armed, and
    Windows is the commonest new-owner platform."""
    src = code_only_deep(research.run_doctor)
    before = src[:src.index("Search path")]
    tail = before[before.rindex("print()"):]
    assert 'plat ==' not in tail, (
        "the search-path section sits inside a platform branch")
