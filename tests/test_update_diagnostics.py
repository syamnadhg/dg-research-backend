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
import json

import pytest

import research
from conftest import code_only


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
    allowed = {"os", "sys", "time", "subprocess", "json", "tempfile", "ctypes"}
    assert imported <= allowed, f"non-stdlib import in the waiter: {imported - allowed}"


def test_the_journal_is_written_before_the_step_that_can_hang():
    """The whole point. If the package manager is launched before anything is
    journaled, a hang leaves no record of reaching it."""
    src = code_only(WAITER)
    start = src.index('_note("package_manager_start"')
    run = src.index("subprocess.run(cmd, timeout=")
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
    i = src.index("_payload = {")
    payload = src[i:i + 700]
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
    assert "_UPDATE_JOURNAL_PATH" in src[i:i + 200]


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
    reading them here covers a helper that left none."""
    src = code_only(research._consume_pending_update_result)
    assert 'raw.get("journal")' in src
    assert "_update_diagnostics()" in src


def test_a_timeout_gets_its_own_sentence_not_an_exit_code():
    """"exit 124" reads as though the package manager chose to fail, when in fact
    nothing ever answered."""
    src = code_only(research._consume_pending_update_result)
    i = src.index('raw.get("timed_out")')
    assert "20 minutes" in src[i:i + 300]


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
