"""The run's record has to survive the hand-off, and stay in its own folder.

⛔⛔ THREE FILED ITEMS, ONE MECHANISM — proved on a real disk before a line was
written. `log()` copies each line into `_RUN_LOG_SINKS[-1]`, a module-global
stack read at WRITE time. The P4/P5 drive posts with a 3600-second timeout and
writes its outcome minutes later, by which point this run's sink has been
popped. So:

  · "Nothing on the server records that a run reached the last two phases" —
    the machine's own account of the hand-off lands in no run folder;
  · "One person's run outcome can land in another person's support bundle" —
    if the NEXT run has armed a sink by then, it lands in THAT folder;
  · task #524, "the machine records the runs the web refuses" — on a 401/403
    the web deliberately writes nothing (no verified identity to write under)
    and says in its own words that this half belongs to the machine, which
    "already sees the non-200 and records nothing".

MEASURED, not argued: across the three run folders on this machine the drive's
own outcome strings appear ZERO times, while the synchronous marker line
written one second earlier — same run, same function, worker thread — is there,
and that folder's last line is `Browser closed`, one second after it.

⭐ THE FIX IS A THIRD USE OF A SHAPE THIS FILE ALREADY HAS TWICE:
`_patch_run_log_status` reaches into a finalized `meta.json`, `_pull_cloud_logs`
drops `cloud.log` into a sealed folder. The collector walks `folder.rglob("*")`,
so a new file rides the support bundle with no collector change at all.
"""
import io
import json
import time
from pathlib import Path

import pytest

import research


@pytest.fixture
def runs(tmp_path, monkeypatch):
    root = tmp_path / "logs" / "runs"
    root.mkdir(parents=True)
    monkeypatch.setattr(research, "_runs_log_root", lambda: root)
    return root


def _folder(runs, name, research_id, *, mtime=None):
    d = runs / name
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "schema": 1, "researchId": research_id, "status": "complete",
    }), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(d, (mtime, mtime))
    return d


def _handoff(d):
    p = d / research.CLOUD_HANDOFF_FILENAME
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ══ 1. the line lands in the run it is about ═══════════════════════════
def test_the_handoff_line_goes_into_that_research_s_own_folder(runs):
    mine = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    assert research._note_cloud_handoff("chat_A", "P4/P5 dispatched ✓") is True
    assert "P4/P5 dispatched ✓" in _handoff(mine)


def test_it_does_NOT_go_into_whichever_run_happens_to_be_armed(runs, monkeypatch):
    """⛔⛔ THE CROSS-RUN MIS-ATTRIBUTION, WHICH IS THE WHOLE POINT. The old
    path resolved the destination from a module-global stack at write time, so
    a slow encode finishing after the next run started put run A's line in run
    B's folder — and B's support bundle."""
    a = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    b = _folder(runs, "Topic_B_20260101T010000", "chat_B")

    # The state that used to decide it: B's sink armed, A's long gone.
    class _Sink:
        dir = b
        research_id = "chat_B"

    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [_Sink()])
    research._note_cloud_handoff("chat_A", "P4/P5 refused by the cloud — HTTP 403")

    assert "403" in _handoff(a), "the line did not reach the run it is about"
    assert _handoff(b) == "", (
        "run A's hand-off landed in run B's folder — and would ship in B's bundle")


def test_a_research_with_no_folder_is_a_quiet_false_not_a_raise(runs):
    """⭐ This runs on a detached daemon thread inside a `try` whose failure
    mode is losing the rest of the hand-off. Clear Logs, the 7-day sweep and a
    machine that never captured the run all reach here."""
    assert research._note_cloud_handoff("chat_missing", "anything") is False
    assert research._note_cloud_handoff("", "anything") is False
    assert research._note_cloud_handoff("chat_A", "") is False


def test_a_folder_removed_between_listing_and_writing_is_not_recreated(runs, monkeypatch):
    """⛔ RE-CHECKED IMMEDIATELY BEFORE THE WRITE. Re-creating it would leave a
    directory holding one line and no meta for the next sweep to puzzle over —
    the same care `_pull_cloud_logs` takes for the same reason."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    real = research._run_folders_for_research_any

    def _vanishing(rid, root=None):
        found = real(rid, root)
        import shutil
        shutil.rmtree(d)
        return found

    monkeypatch.setattr(research, "_run_folders_for_research_any", _vanishing)
    assert research._note_cloud_handoff("chat_A", "late line") is False
    assert not d.exists(), "the folder was re-created behind a sweep's back"


def test_lines_accumulate_rather_than_replacing_each_other(runs):
    """A run can dispatch, be refused, and be retried. Each attempt is a fact."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    research._note_cloud_handoff("chat_A", "first")
    research._note_cloud_handoff("chat_A", "second")
    body = _handoff(d)
    assert "first" in body and "second" in body
    assert body.count("\n") == 2


def test_it_writes_its_own_file_and_never_reopens_the_sealed_run_log(runs):
    """⛔ `finalize()` CLOSES the capped writer and `write_line` on a closed
    writer is a silent no-op, so a line appended to `run.log` after the seal is
    lost exactly when it matters most. It also must not disturb `meta.json`,
    which the bundle index and the sweeps both read."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    (d / "run.log").write_text("=== super research run ===\n", encoding="utf-8")
    before_meta = (d / "meta.json").read_text(encoding="utf-8")
    research._note_cloud_handoff("chat_A", "after the seal")
    assert (d / "run.log").read_text(encoding="utf-8") == "=== super research run ===\n"
    assert (d / "meta.json").read_text(encoding="utf-8") == before_meta
    assert "after the seal" in _handoff(d)


# ══ 2. the resolver, and why it is not the sweep's ═════════════════════
def test_the_resolver_matches_on_meta_not_on_the_folder_name(runs):
    """⛔ The folder name is sanitised, so two researches can share a prefix —
    and a research whose id the pattern strips does not appear in its own name
    at all. The sweep learned this the expensive way; so does this."""
    right = _folder(runs, "Shared_Prefix_20260101T000000", "chat_AAAA")
    _folder(runs, "Shared_Prefix_20260101T010000", "chat_BBBB")
    found = research._run_folders_for_research_any("chat_AAAA")
    assert found == [right]


def test_the_resolver_INCLUDES_a_live_folder_unlike_the_sweep_s(runs, monkeypatch):
    """⛔⛔ THE DIFFERENCE THAT MATTERS, AND THE REASON THIS IS NOT A REUSE.
    `_run_log_folders_for_research` skips any folder a sink is armed on —
    correct for a delete path, wrong here. The drive starts while the pipeline
    is still finishing, so its first line can arrive BEFORE the seal; borrowing
    the sweep's resolver would drop that line and leave the harder case looking
    handled."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")

    class _Sink:
        dir = d
        research_id = "chat_A"

    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [_Sink()])
    assert research._run_folders_for_research_any("chat_A") == [d]
    # the sweep's resolver, for contrast, refuses it — that is its job
    assert research._run_log_folders_for_research("chat_A", root=runs) == []


def test_an_unreadable_meta_is_skipped_rather_than_matched(runs):
    """⭐ A folder with no meta reads back as researchId "" — and "" == "" is a
    match. The sweep's own comment records that one malformed file nearly cost
    it a tree of somebody's diagnostics."""
    (runs / "half_written").mkdir()
    (runs / "half_written" / "meta.json").write_text("{not json", encoding="utf-8")
    good = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    assert research._run_folders_for_research_any("chat_A") == [good]
    assert research._run_folders_for_research_any("") == []


# ══ 3. the caller, because a helper is not a consumer ══════════════════
def test_the_drive_records_every_outcome_it_can_have():
    """⛔⛔ HELPER-PINNED, CONSUMER-NOT is this project's commonest miss. The
    three outcomes are dispatched, refused, and never-arrived, and the refusal
    is the one nothing anywhere else records."""
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(research._post_fe_p4p5_trigger))
    drive = next(n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef) and n.name == "_drive_once")
    tries = [n for n in ast.walk(drive) if isinstance(n, ast.Try)]
    assert tries, "_drive_once no longer guards the POST"
    t = tries[0]

    def _notes(stmts):
        return [n for s in stmts for n in ast.walk(s)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_note_cloud_handoff"]

    # ⛔ COUNTING CALL SITES WAS THE WRONG MEASURE, and my first version of this
    # test said 3 and found 2. The 2xx and the refusal SHARE one call after the
    # branch — which is better, not worse: a single writer cannot record one
    # outcome and forget the other. What has to be true is that both branches
    # reach it, and that the exception path has its own.
    status_ifs = [n for n in ast.walk(t) if isinstance(n, ast.If)
                  and any(isinstance(c, ast.Attribute) and c.attr == "status_code"
                          for c in ast.walk(n.test))]
    assert status_ifs, "the drive no longer branches on the response status"
    branch = status_ifs[0]
    assert branch.body and branch.orelse, "the refusal branch is gone"
    # ⛔⛔ THE RECORD MUST BE UNCONDITIONAL, AND A MUTANT PROVED THIS TEST COULD
    # NOT SEE OTHERWISE. Asking only "is there a call after the branch" is
    # satisfied by `if status in (200, 202): _note_cloud_handoff(...)` placed
    # after it — which records the success and drops the refusal, i.e. removes
    # the whole of task #524 while leaving every name this test looks for in
    # place. So the call has to be a DIRECT statement of the try body, reached
    # however the branch above resolved.
    after = [s for s in t.body if getattr(s, "lineno", 0) > (branch.end_lineno or 0)]
    unconditional = [
        s for s in after
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
        and isinstance(s.value.func, ast.Name)
        and s.value.func.id == "_note_cloud_handoff"
    ]
    assert unconditional, (
        "the hand-off record is either missing or guarded by a condition — the "
        "refusal is the outcome the web deliberately does not write, and "
        "recording only the successes is the whole of task #524 undone")
    assert _notes(t.handlers[0].body if t.handlers else []), (
        "a dispatch that never reached the cloud leaves no record")


def test_a_connection_cut_mid_flight_is_not_reported_as_never_arriving():
    """⛔⛔ THE FIRST VERSION OF THIS RECORD LIED ON THE MAJORITY PATH, and the
    wave's own measurement convicted it. Something in front of Cloud Run severs
    this socket at EXACTLY 300 seconds while the route keeps working — one
    measured run finished at 497s — so `requests` raises on every P4/P5 longer
    than five minutes, and the exception branch wrote "never reached the cloud …
    still on phase 3" into the run's permanent record on runs that SUCCEEDED.
    A lying diagnostic is worse than none, and this file rides the support
    bundle."""
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(research._post_fe_p4p5_trigger))
    drive = next(n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef) and n.name == "_drive_once")
    handler = next(n for n in ast.walk(drive) if isinstance(n, ast.Try)).handlers[0]
    # the branch must ASK how long the connection lasted
    names = {n.id for n in ast.walk(handler) if isinstance(n, ast.Name)}
    assert "_DRIVE_SENT_AFTER_SEC" in names, (
        "the exception branch cannot tell a connection that never opened from "
        "one that was cut after the cloud had the request")
    body = ast.dump(handler)
    assert "never reached the cloud" in body, "the genuine never-arrived case lost its sentence"
    assert "may be finishing it" in body, "the cut-mid-flight case has no sentence of its own"


def test_the_threshold_is_far_below_the_measured_severance():
    """⭐ 300 seconds is where the real severance lands. The threshold only has
    to separate "never left" (DNS, refused, no route — instant) from anything
    the cloud actually received, so it sits close to zero and nowhere near 300."""
    assert 1 <= research._DRIVE_SENT_AFTER_SEC <= 60


def test_the_refusal_line_says_what_happens_next():
    """⭐ A record nobody can act on is a log line with extra steps. The run is
    recoverable — `needsFeTrigger` was written synchronously before the POST —
    so the sentence says so rather than implying the run is lost."""
    import inspect
    src = inspect.getsource(research._post_fe_p4p5_trigger)
    assert "still on phase 3 until" in src
    assert "catch-up fires" in src
