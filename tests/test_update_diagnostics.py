"""When an app-driven update does not work, it must leave evidence.

The reported failure is "the update hangs forever". Until now that produced NOTHING
to diagnose from: the upgrade helper writes its outcome sentinel only after the
package manager RETURNS, so a package manager that never returns left no outcome, no
timings, and no indication of how far it got. The helper holds no credentials and
runs on a non-venv interpreter by design, so it cannot tell the app directly — it
leaves files, and whichever backend comes up next publishes them.

Three things are pinned here: the helper journals each step BEFORE the step that can
hang, the package manager has a ceiling so a hang becomes a reported failure, and the
no-sentinel verdict — the branch a hang actually lands in — carries the journal.
"""
import ast
import subprocess
import sys
from pathlib import Path
import json

import pytest

import research
from conftest import code_only, serving_version


WAITER = research._LIFECYCLE_WAITER


# ── The helper script itself ─────────────────────────────────────────────────

def test_the_waiter_is_valid_python():
    """It is executed by a bare interpreter with no venv, so a syntax error here is
    a silent total failure of the update path — nothing would ever run."""
    ast.parse(WAITER)


def test_the_waiter_uses_only_the_standard_library():
    """It runs on an interpreter OUTSIDE the venv pipx is about to delete, so it has
    no third-party packages and no credentials. An import of anything else would
    fail at the worst possible moment."""
    tree = ast.parse(WAITER)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # `signal` joined them with the process-tree kill: killing a process GROUP needs
    # the signal numbers, and it is as much stdlib as the rest.
    allowed = {"os", "sys", "time", "subprocess", "json", "tempfile", "ctypes", "signal"}
    assert imported <= allowed, f"non-stdlib import in the waiter: {imported - allowed}"


def test_the_journal_is_written_before_the_step_that_can_hang():
    """The whole point. If the package manager is launched before anything is
    journaled, a hang leaves no record of reaching it."""
    src = code_only(WAITER)
    start = src.index('_note("package_manager_start"')
    run = src.index("subprocess.Popen(cmd,")
    assert start < run, "the start is journaled after the call it describes"


def test_the_package_manager_has_a_ceiling():
    """An unbounded wait is the reported symptom. A ceiling turns it into a
    reportable failure instead of an eternal spinner."""
    src = code_only(WAITER)
    assert "timeout=_TIMEOUT_S" in src
    assert "_TIMEOUT_S = 1200" in src
    assert "subprocess.TimeoutExpired" in src


def test_a_timeout_is_reported_as_a_failure_not_a_success():
    src = code_only(WAITER)
    i = src.index("except subprocess.TimeoutExpired:")
    window = src[i:i + 260]
    assert "rc = 124" in window, "a timeout must not leave rc at 0"
    assert "_timed_out = True" in window


def test_the_journal_is_appended_never_rewritten():
    """A crash mid-journal must leave the earlier steps intact."""
    src = code_only(WAITER)
    i = src.index("def _note(")
    assert '"a"' in src[i:i + 400], "the journal is not opened for append"


def test_the_log_tail_is_carried_even_on_success():
    """The confusing report is a success whose version does not move. Carrying the
    tail only on failure left exactly that case with no evidence."""
    src = code_only(WAITER)
    i = src.index("_tail = \"\"")
    # No `if rc != 0` gate between the initialisation and the read.
    window = src[i:src.index("_payload = {")]
    assert "if rc != 0" not in window, "the tail is still gated on failure"
    assert "DG_LIFECYCLE_LOG" in window


def test_the_outcome_carries_the_journal_and_the_timeout_flag():
    src = code_only(WAITER)
    # Bounded by the write that follows it rather than a character count, so growing
    # the payload cannot silently move a field out of the window being checked.
    payload = src[src.index("_payload = {"):src.index("_fd, _tmp =")]
    assert '"journal": _journal' in payload
    assert '"timed_out": _timed_out' in payload


def test_the_restart_is_still_refused_after_a_failed_upgrade():
    """Never cycle the supervisor onto a half-built venv — including after a
    timeout, which is now a nonzero rc rather than an exception that skips this."""
    src = code_only(WAITER)
    assert "if after and rc == 0:" in src


# ── The environment the spawner must provide ─────────────────────────────────

def test_the_journal_path_is_passed_to_the_waiter():
    src = code_only(research._spawn_detached_lifecycle)
    assert "DG_LIFECYCLE_JOURNAL=str(_UPDATE_JOURNAL_PATH)" in src


def test_the_journal_variable_is_forwarded_on_linux():
    """systemd-run hands the transient unit the user manager's environment, not
    ours. A variable missing from this list is silently absent on Linux ONLY —
    dead on the platform where the extra indirection makes it hardest to notice."""
    src = code_only(research._spawn_detached_lifecycle)
    i = src.index("_fwd = (")
    assert "DG_LIFECYCLE_JOURNAL" in src[i:i + 400]


def test_a_new_attempt_truncates_the_previous_journal():
    """It is append-only while the helper runs, so without this the last attempt's
    steps read as a continuation of this one's."""
    src = code_only(research._spawn_detached_lifecycle)
    i = src.index("for _stale in (")
    assert "_UPDATE_JOURNAL_PATH" in src[i:i + 220]


class TestTheLogBelongsToOneAttempt:
    """⭐ The log is the file every reason for truncating the journal was written
    about, and it was the one left alone. It is opened append-only and its TAIL is
    published as this attempt's evidence, so a retry handed the user the PREVIOUS
    attempt's error as the explanation for this one — in the diagnostics and in the
    single sentence they actually read."""

    @staticmethod
    def _spawn(monkeypatch, tmp_path, *, popen):
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_path_python", lambda: sys.executable)
        monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
        monkeypatch.setattr(subprocess, "Popen", popen)
        try:
            return research._spawn_detached_lifecycle("upgrade", current="0.1.12",
                                                      latest="0.1.13")
        finally:
            research._ALWAYS_PROTECTED_PIDS.discard(4242)

    def test_the_helper_starts_with_an_empty_log(self, tmp_path, monkeypatch):
        log = tmp_path / "upgrade.log"
        log.write_text("ERROR: no matching distribution for superresearch==0.1.11\n",
                       encoding="utf-8")
        seen = {}

        class _Proc:
            pid = 4242

        def _popen(cmd, **kw):
            # Read it at the moment the helper is launched — that is the state the
            # helper will publish the tail of, and the only moment worth asserting on.
            seen["log"] = log.read_text(encoding="utf-8") if log.exists() else None
            return _Proc()

        assert self._spawn(monkeypatch, tmp_path, popen=_popen) == 4242
        assert seen["log"] == "", \
            "the previous attempt's error is still there to be republished as this one's"

    def test_the_stale_log_goes_even_if_it_cannot_be_reopened(self, tmp_path, monkeypatch):
        """Windows refuses to unlink a file another process still holds open, and it
        equally refuses to truncate one — so the clear cannot rest on either step
        alone. With the open refused, the file must still be gone."""
        import builtins
        log = tmp_path / "upgrade.log"
        log.write_text("ERROR: from the attempt before last\n", encoding="utf-8")
        real_open = builtins.open

        def _refuse(file, *a, **kw):
            if str(file).endswith("upgrade.log"):
                raise PermissionError("being used by another process")
            return real_open(file, *a, **kw)

        monkeypatch.setattr(builtins, "open", _refuse)

        class _Proc:
            pid = 4242

        assert self._spawn(monkeypatch, tmp_path,
                           popen=lambda cmd, **kw: _Proc()) == 4242
        assert not log.exists(), "a stale log survived a refused open"

    def test_the_open_truncates_even_if_the_unlink_is_refused(self, tmp_path,
                                                              monkeypatch):
        """The mirror of the test above, and the reason there are two steps rather
        than one: with the unlink refused — a Windows box whose previous helper still
        holds the file — the open itself has to be what empties it."""
        log = tmp_path / "upgrade.log"
        log.write_text("ERROR: from the attempt before last\n", encoding="utf-8")
        real_unlink = Path.unlink

        def _refuse(self, *a, **kw):
            if str(self).endswith("upgrade.log"):
                raise PermissionError("being used by another process")
            return real_unlink(self, *a, **kw)

        monkeypatch.setattr(Path, "unlink", _refuse)
        seen = {}

        class _Proc:
            pid = 4242

        def _popen(cmd, **kw):
            seen["log"] = log.read_text(encoding="utf-8") if log.exists() else None
            return _Proc()

        assert self._spawn(monkeypatch, tmp_path, popen=_popen) == 4242
        assert seen["log"] == "", "the unlink was refused and nothing else cleared it"


# ── Publishing the evidence ──────────────────────────────────────────────────

def test_diagnostics_are_empty_when_there_is_nothing_to_report(tmp_path, monkeypatch):
    """So a caller can splat the result unconditionally without inventing fields on
    a healthy update."""
    monkeypatch.setattr(research, "_UPDATE_JOURNAL_PATH", tmp_path / "absent.jsonl")
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    assert research._update_diagnostics() == {}


def test_diagnostics_carry_the_journal_tail_and_its_true_length(tmp_path, monkeypatch):
    jp = tmp_path / "j.jsonl"
    jp.write_text("".join(f'{{"t":{i},"step":"s{i}"}}\n' for i in range(200)),
                  encoding="utf-8")
    monkeypatch.setattr(research, "_UPDATE_JOURNAL_PATH", jp)
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    got = research._update_diagnostics(journal_lines=10)
    assert got["journalLines"] == 200, "the true length must survive the truncation"
    assert got["journal"].count("\n") <= 10
    assert '"step":"s199"' in got["journal"], "kept the oldest lines, not the newest"


def test_diagnostics_are_bounded_because_they_land_in_a_document_field(tmp_path, monkeypatch):
    """A package-manager log can be megabytes. An unbounded read would fail the
    write and take the outcome with it — losing the answer to the act of
    explaining it."""
    jp = tmp_path / "j.jsonl"
    jp.write_text("x" * 200_000, encoding="utf-8")
    (tmp_path / "upgrade.log").write_text("y" * 200_000, encoding="utf-8")
    monkeypatch.setattr(research, "_UPDATE_JOURNAL_PATH", jp)
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    got = research._update_diagnostics()
    assert len(got["journal"]) <= 6000
    assert len(got["logTail"]) <= 4000


def test_diagnostics_take_the_END_of_the_log(tmp_path, monkeypatch):
    """The last thing that happened is what says where it stopped."""
    monkeypatch.setattr(research, "_UPDATE_JOURNAL_PATH", tmp_path / "none.jsonl")
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    (tmp_path / "upgrade.log").write_text("early\n" + "pad\n" * 5000 + "LAST-LINE",
                                          encoding="utf-8")
    got = research._update_diagnostics()
    assert got["logTail"].endswith("LAST-LINE")
    assert "early" not in got["logTail"]


def test_diagnostics_never_raise_on_an_unreadable_path(tmp_path, monkeypatch):
    """This runs on the heartbeat path; an exception here would cost the status
    update it is trying to enrich."""
    monkeypatch.setattr(research, "_UPDATE_JOURNAL_PATH", tmp_path)  # a DIRECTORY
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    assert isinstance(research._update_diagnostics(), dict)


def test_the_no_sentinel_verdict_carries_the_diagnostics():
    """⭐ This is the branch a HANG lands in — the helper never got far enough to
    write an outcome, so this is the only path that can report one, and therefore
    the only path where attaching the journal matters."""
    src = code_only(research._update_intent_verdict)
    i = src.index('"state": "failed"')
    assert "_update_diagnostics()" in src[i:i + 400]


def test_a_failed_sentinel_prefers_what_the_helper_captured():
    """The helper read those files while they were still its own. Falling back to
    reading them here covers a helper that left none.

    CALLED, not grepped: the preference is now an extracted decision, so the test
    can watch it choose instead of confirming that the words appear."""
    out = research._update_diag_from({"journal": "from-the-helper", "log_tail": "tail"})
    assert out == {"journal": "from-the-helper", "logTail": "tail"}


def test_an_empty_sentinel_falls_back_to_reading_the_files(tmp_path, monkeypatch):
    """The helper that never got far enough to capture anything is the hang case —
    the one that most needs the fallback."""
    monkeypatch.setattr(research, "_UPDATE_JOURNAL_PATH", tmp_path / "j.jsonl")
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    (tmp_path / "j.jsonl").write_text('{"t":1,"step":"waiter_started"}\n', encoding="utf-8")
    out = research._update_diag_from({"journal": "", "log_tail": ""})
    assert "waiter_started" in out["journal"]


def test_a_timeout_gets_its_own_sentence_not_an_exit_code():
    """"exit 124" reads as though the package manager chose to fail, when in fact
    nothing ever answered."""
    timed_out = research._update_failure_reason({"rc": 124, "timed_out": True})
    assert "20 minutes" in timed_out
    assert "124" not in timed_out
    plain = research._update_failure_reason({"rc": 1, "timed_out": False})
    assert plain == "pipx upgrade failed (exit 1)"


def test_a_timeout_says_the_install_may_be_half_finished():
    """pipx upgrades IN PLACE, so a package manager stopped part-way leaves the venv
    neither build. The user cannot choose the repair unless they are told."""
    reason = research._update_failure_reason({"rc": 124, "timed_out": True})
    assert "half-finished" in reason and "superresearch --update" in reason


def test_an_unconfirmed_kill_asks_for_a_reboot_instead():
    """A survivor holds the venv open and makes the repair fail the same way, so this
    is the one case where another attempt is the wrong advice."""
    reason = research._update_failure_reason({"rc": 124, "timed_out": True,
                                              "orphaned": True})
    assert "reboot" in reason
    assert "reboot" not in research._update_failure_reason({"rc": 124, "timed_out": True})


class TestTheSuccessThatDidNotTakeCarriesEvidenceToo:
    """⭐ The waiter was changed to carry its log tail on SUCCESS, for one specific
    outcome: pipx reports success and the version does not move. The only branch that
    attached anything was the failure one, so that change was INERT — the confusing
    case it was made for still arrived with nothing to look at.

    (The commit describing it therefore claimed a behaviour the code did not have,
    which is the more expensive half of the defect.)"""

    @staticmethod
    def _sentinel(tmp_path, monkeypatch, payload):
        p = tmp_path / "update_result.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", p)

    def test_installed_but_still_serving_the_old_build(self, tmp_path, monkeypatch):
        self._sentinel(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.12", "latest": "0.1.13",
            "journal": '{"t":9.4,"step":"restart_issued"}\n',
            "log_tail": "installed package superresearch 0.1.13",
        })
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.13")
        serving_version(monkeypatch, "0.1.12")
        st = research._consume_pending_update_result()
        assert st["needsRestart"] is True
        assert "restart_issued" in st["journal"], \
            "the one outcome the carried tail exists for still has no evidence"
        assert "installed package" in st["logTail"]

    def test_a_healthy_update_stays_clean(self, tmp_path, monkeypatch):
        """No evidence fields on a success that worked — an empty "Show details" is a
        different claim from "nothing was captured", and the row must not offer one."""
        self._sentinel(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.12", "latest": "0.1.13",
            "journal": '{"t":9.4,"step":"restart_issued"}\n', "log_tail": "installed",
        })
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.13")
        serving_version(monkeypatch, "0.1.13")
        st = research._consume_pending_update_result()
        assert st == {"state": "installed", "current": "0.1.13", "latest": "0.1.13",
                      "needsRestart": False, "reason": ""}


def test_the_journal_path_sits_beside_the_other_update_state():
    assert research._UPDATE_JOURNAL_PATH.parent == research._UPDATE_RESULT_PATH.parent
    assert research._UPDATE_JOURNAL_PATH != research._UPDATE_RESULT_PATH


def test_a_journal_record_is_one_json_object_per_line():
    """The frontend parses it line by line and tolerates a truncated final line.
    Anything multi-line here would break that reader."""
    src = code_only(WAITER)
    i = src.index("def _note(")
    window = src[i:i + 500]
    assert '_j.dumps(rec) + "\\n"' in window
