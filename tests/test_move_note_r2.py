"""Round 2 (09-30) — the owner's note on "Move to queue", the machine's half.

The owner's confirm gains an optional note (up to 280 characters) and the
`requeue` device command carries it as `note`. The machine writes it on the
moved run's research record as `moveNote`, next to `movedToQueueAt`, only when
a note was written; both go when the run starts again, or ends while it waits.
The run's own person reads it there — in the app's queued banner and in the
chat assistant (the Windows brief uses the same two names).

⭐ EVERY TEST DRIVES THE REAL PATH: the device-command listener's callback for
the move, the idle rescan for the run starting again, the start listener for a
stop or cancel while it waits, and boot rehydration for the record written
again over a run that is still waiting. The machine is `test_requeue_w13`'s.

⛔ Would these pass against df26bdd? No: the move wrote no `moveNote` at all,
and none of the three clears named it.

Run:  pytest tests/test_move_note_r2.py -v
"""
import pytest
from google.cloud.firestore import DELETE_FIELD

import research
import test_requeue_w13 as T
# ⛔ IMPORTED HERE, AT COLLECTION, as the file it borrows from does.
import _run_server_closure  # noqa: F401


def _moved_record(monkeypatch, tmp_path, **command):
    """Move worker 2's running run with the REAL command listener; the record
    write the move made."""
    m, _job, _folder = T._running(monkeypatch, tmp_path)
    fate = T._command(monkeypatch, m, T._requeue(**command))
    assert fate == ["deleted"] and m.exits == ["requeue"], (fate, m.exits, m.lines)
    mine = [p for u, r, p in m.writes if (u, r) == (T.SHARER, T.RID)]
    assert len(mine) == 1 and mine[0]["status"] == "queued", m.writes
    return mine[0]


# ══ 1. the move writes the note ═══════════════════════════════════════════════

def test_the_owners_note_is_written_on_the_moved_runs_record(monkeypatch, tmp_path):
    """⭐ THE PIN. A note on the command lands on the record as `moveNote`, in
    the same write as `movedToQueueAt` — the person reads both together."""
    rec = _moved_record(monkeypatch, tmp_path, note="Need this worker for a demo, back by 3")
    assert rec["moveNote"] == "Need this worker for a demo, back by 3", rec
    assert isinstance(rec["movedToQueueAt"], int) and rec["movedToQueueAt"] > 0, rec


@pytest.mark.parametrize("note", [None, "", "   ", 42, ["x"]],
                         ids=["absent", "empty", "blank", "number", "list"])
def test_a_move_without_a_note_writes_none_and_clears_an_old_one(monkeypatch, tmp_path, note):
    """⛔ No note — or nothing that is one — puts no words on the record. The
    key is CLEARED, not left out: a note an earlier move left there (its clear
    never landed) would otherwise be read as this move's."""
    command = {} if note is None else {"note": note}
    rec = _moved_record(monkeypatch, tmp_path, **command)
    assert rec["moveNote"] is DELETE_FIELD, rec
    assert isinstance(rec["movedToQueueAt"], int), "the move itself was not marked"


def test_the_note_is_one_line_and_at_most_280_characters(monkeypatch, tmp_path):
    """⛔ The app's field allows 280. Anything longer (an older or a changed
    app) is cut there; line breaks and runs of spaces become one space."""
    rec = _moved_record(monkeypatch, tmp_path, note="  Back\n\nsoon  " + "x" * 400)
    assert rec["moveNote"].startswith("Back soon xxx"), rec["moveNote"][:20]
    assert len(rec["moveNote"]) == 280 == research.MOVE_NOTE_MAX


def test_a_refused_move_writes_no_note(monkeypatch, tmp_path):
    """⛔ The control: a move the machine refuses writes nothing on the record,
    the note included."""
    m, _job, _folder = T._running(monkeypatch, tmp_path, supervised=False)
    T._command(monkeypatch, m, T._requeue(note="hello"))
    assert [p for u, r, p in m.writes if (u, r) == (T.SHARER, T.RID)] == [], m.writes


# ══ 2. the run starts again: both go ══════════════════════════════════════════

def test_the_note_goes_with_the_stamp_when_a_worker_takes_the_run(monkeypatch, tmp_path):
    """⭐ The next awake worker takes the run (the REAL idle rescan): the record
    says running again, and neither the stamp nor the note is left on it."""
    m, _folder = T._waiting(monkeypatch, tmp_path, worker=1)
    assert [j["research_id"] for j in T._rescan(monkeypatch, m)] == [T.RID]
    ongoing = [p for u, r, p in m.writes if (u, r) == (T.SHARER, T.RID)]
    assert ongoing and ongoing[0]["status"] == "ongoing", m.writes
    assert ongoing[0]["movedToQueueAt"] is DELETE_FIELD, ongoing[0]
    assert ongoing[0]["moveNote"] is DELETE_FIELD, ongoing[0]


@pytest.mark.parametrize("who", list(T.CANCELS))
def test_the_note_goes_when_the_waiting_run_is_stopped_or_cancelled(monkeypatch, tmp_path, who):
    """⛔ A waiting run ended by its person, or by the owner's Stop or Cancel,
    no longer waits: the note about why it waits goes with the stamp."""
    over, _expect = T.CANCELS[who]
    _r, folder = T._run_folder(tmp_path, T.RID, uid=T.SHARER)
    (folder / "phase2_complete.marker").write_text("x", encoding="utf-8")
    T._moved_marker(folder, T.SHARER, T.RID)
    lis, _published = T._cancel_listener(monkeypatch, tmp_path)

    lis.feed(action="cancel", uid=T.SHARER, researchId=T.RID, **over)

    mine = [p for _u, r, p in lis.writes if r == T.RID]
    assert len(mine) == 1 and mine[0]["status"] == "stopped", mine
    assert mine[0]["movedToQueueAt"] is DELETE_FIELD, mine[0]
    assert mine[0]["moveNote"] is DELETE_FIELD, mine[0]


# ══ 3. written again while it still waits: the note stays ═════════════════════

def test_a_run_still_waiting_keeps_its_note_when_its_record_is_written_again(
        monkeypatch, tmp_path):
    """⛔ The worker a run was moved off can write "ongoing" in its last
    second, and boot writes the waiting record again over it. The run has not
    started: the owner's note is still true, and that write must not clear it."""
    m, _q, _folder, _counts = T._boot_rehydrate(monkeypatch, tmp_path, resting=False,
                                                waiting=True)
    again = [p for u, r, p in m.writes if (u, r) == (T.OWNER, T.RID)]
    assert again and again[0]["status"] == "queued", m.writes
    assert "moveNote" not in again[0], again[0]
