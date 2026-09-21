"""A Resume the machine cannot honour has to leave a record.

⛔⛔ WHAT THIS EXISTS FOR, MEASURED 2026-09-21. The resume handler has exactly
ONE Firestore write and it sits on the success path. NINE other exits delete the
queue entry and write nothing at all, so the research document keeps whatever
status put the Resume banner on screen — which the web reads as a run that is
paused but NOT over. On the web side `resumePipelineFromCheckpoint` is a bare
`addDoc` with no listener and no timeout, and the chat cleared its card the
moment that write resolved. Four seconds after the press there was no banner, no
error and no button, on a request this process had already thrown away.

⛔⛔ AND NOT ONE TEST IN THIS SUITE COULD SEE ANY OF IT. `grep -rn "Resume:"
tests/` returned nothing; so did the log strings of every drop branch. The five
resume-named test files all exercise different functions.

⭐ THE PIN HAS TO BE ABOUT THE DROP BRANCHES SPECIFICALLY. A test that only
proves "a resume writes something" is satisfied by the success path and measures
nothing — the standing rule here, and the trap four of this project's pins fell
into. So the behavioural cases below drive the REAL listener callback with a
resume document that cannot be honoured, and assert the write happens and
happens BEFORE the delete.

⭐ AND THE ORDER IS ASSERTED STRUCTURALLY TOO, over the parse tree rather than
the text. A `toContain` on source cannot tell "writes then deletes" from
"deletes then writes", and the deletion is what makes the write unrepeatable.
"""
import ast
import inspect
import time
from pathlib import Path

import pytest

import research


# ══ helpers ════════════════════════════════════════════════════════════
class _ChangeType:
    def __init__(self, name):
        self.name = name


class _Ref:
    def __init__(self, journal):
        self._journal = journal

    def delete(self):
        self._journal.append(("delete", None))


class _Doc:
    def __init__(self, data, journal):
        self._data = data
        self.reference = _Ref(journal)
        self.id = "queue-doc-1"

    def to_dict(self):
        return dict(self._data)

    @property
    def exists(self):
        return True


class _Change:
    def __init__(self, data, journal):
        self.type = _ChangeType("ADDED")
        self.document = _Doc(data, journal)


class _FakeNode:
    """One node that answers both chains the handler walks.

    ⛔ THE FIRST VERSION HAD TWO CLASSES AND A DEAD END. The queue chain is
    `devices/{id}/queue`; the research chain is
    `users/{uid}/researches/{rid}` — and a collection that could not hand back
    a document made the second chain raise, so the handler took its
    read-failed exit and the test reported "wrote nothing back" about a branch
    it never reached. One node that answers `collection`, `document` and `get`
    keeps the fake from deciding which branch runs.
    """

    def __init__(self, box, research):
        self._box = box
        self._research = research

    def collection(self, _name):
        return self

    def document(self, _id):
        return self

    def on_snapshot(self, cb):
        self._box["cb"] = cb
        return object()

    # the listener does a FIFO pre-query on attach; an empty stream is honest
    def where(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def stream(self):
        return iter(())

    def get(self):
        if isinstance(self._research, Exception):
            raise self._research
        return _Snap(self._research)


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _FakeDb(_FakeNode):
    def __init__(self, box, research=None):
        super().__init__(box, research if research is not None
                         else {"status": "paused_backend_restart"})


def _drive(monkeypatch, data, journal, research_doc=None):
    """Register the real listener against a fake db and hand it one document."""
    box = {}
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(box, research_doc))
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: False)

    def _record_update(uid, rid, updates):
        journal.append(("write", {"uid": uid, "rid": rid, **dict(updates)}))
        return True

    monkeypatch.setattr(research, "_update_research_doc", _record_update)

    class _Loop:
        def call_soon_threadsafe(self, fn, *a):
            fn(*a)

    research.start_firestore_start_listener(object(), _Loop())
    cb = box.get("cb")
    assert cb is not None, "the listener did not register a snapshot callback"
    cb(object(), [_Change(data, journal)], None)
    return journal


def _resume_doc(**over):
    base = {
        "action": "resume",
        "uid": "uid-alice",
        "submittedBy": "uid-alice",
        "researchId": "chat_1755500000000_3",
        "timestamp": int(time.time() * 1000),
    }
    base.update(over)
    return base


def _writes(journal):
    return [row for kind, row in journal if kind == "write"]


def _order(journal):
    return [kind for kind, _ in journal]


# ══ 1. the three drops a person cannot recover from ════════════════════
def test_a_resume_with_no_saved_run_says_so_before_it_drops_the_request(monkeypatch):
    """⛔⛔ THE HEADLINE. No backendRunId means there is nothing on disk to pick
    up from. The old code logged a local WARN and deleted the queue entry; the
    person's banner sat unchanged, still offering a Resume that would take the
    same path again."""
    journal = _drive(monkeypatch, _resume_doc(), [])
    writes = _writes(journal)
    assert writes, "the drop wrote nothing back — the person is never told"
    assert writes[0]["rid"] == "chat_1755500000000_3"
    assert writes[0]["status"] == "paused_backend_restart_failed"
    assert "nothing to pick up from" in writes[0]["lastError"]
    # ⛔ BEFORE THE DELETE. Afterwards is not a smaller bug: the queue entry is
    # the only thing that would bring us back here.
    assert _order(journal).index("write") < _order(journal).index("delete")


def test_a_resume_whose_files_were_swept_says_that_and_not_something_vaguer(monkeypatch, tmp_path):
    """⛔ The 7-day startup sweep keeps a folder only when delivery.json reads
    completed/paused/paused_backend_restart — and boot rehydration writes the
    paused status to FIRESTORE ONLY, never to that file. So the sweep removes
    the folder of the very run whose banner is still asking to be resumed."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    journal = _drive(monkeypatch, _resume_doc(backendRunId="Topic_20260101_000000"), [])
    writes = _writes(journal)
    assert writes, "a swept run folder dropped the resume silently"
    assert "cleared from the computer" in writes[0]["lastError"]
    assert writes[0]["status"] == "paused_backend_restart_failed"
    assert _order(journal).index("write") < _order(journal).index("delete")


def test_a_resume_for_a_terminally_stopped_run_says_it_is_over(monkeypatch, tmp_path):
    """⛔ A `.stop` sentinel is a deliberate end. Saying so is the difference
    between a person retrying forever and a person starting a new run."""
    qdir = tmp_path / "queues" / "Topic_20260101_000000"
    qdir.mkdir(parents=True)
    (qdir / ".stop").write_text("", encoding="utf-8")
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    journal = _drive(monkeypatch, _resume_doc(backendRunId="Topic_20260101_000000"), [])
    writes = _writes(journal)
    assert writes, "a terminally stopped run dropped the resume silently"
    assert "stopped for good" in writes[0]["lastError"]
    assert _order(journal).index("write") < _order(journal).index("delete")


# ══ 2. the over-correction: the drops that must stay quiet ═════════════
def test_a_resume_missing_its_identity_writes_nothing_because_there_is_nowhere_to_write(monkeypatch):
    """⭐ ACCEPT POLARITY, and it is not pedantry: `_update_research_doc` needs
    a uid AND a research id. A write-back attempted without them would either
    throw inside a listener callback or, worse, land somewhere arbitrary."""
    journal = _drive(monkeypatch, _resume_doc(uid="", researchId=""), [])
    assert _writes(journal) == []
    assert "delete" in _order(journal)


def test_the_helper_refuses_a_half_identity(monkeypatch):
    """The same rule at the unit below, because the branches are not the only
    future callers."""
    calls = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, up: calls.append((u, r, up)) or True)
    assert research._resume_drop_writeback("", "rid", "why") is False
    assert research._resume_drop_writeback("uid", "", "why") is False
    assert calls == []


def test_the_helper_can_leave_the_status_alone(monkeypatch):
    monkeypatch.setattr(research, "_research_is_terminal", lambda u, r: False)
    """⛔⛔ THE 12-HOUR CASE NEEDS THIS AND THE OTHER THREE MUST NOT USE IT.
    `paused_backend_restart_failed` is absent from `_safe_enqueue`'s whitelist,
    so writing it permanently closes auto-resume for that run. On the three
    unrecoverable branches that costs nothing — every re-enqueue path is already
    blocked. On a request that merely went stale the artifacts are still on
    disk, so the run IS resumable and moving the status would take that away."""
    calls = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, up: calls.append(up) or True)
    research._resume_drop_writeback("uid", "rid", "why", status=None)
    assert calls == [{"lastError": "why"}]
    calls.clear()
    research._resume_drop_writeback("uid", "rid", "why")
    assert calls[0]["status"] == "paused_backend_restart_failed"


def test_a_run_that_is_already_OVER_gets_the_sentence_and_keeps_its_status(monkeypatch):
    """⛔⛔ THE NASTIEST SHAPE IN THE WAVE, CAUGHT BY CROSS-VERIFY BEFORE THE
    PUSH. The recovery card offers Resume for all four statuses INCLUDING the
    two terminal ones, so pressing it on a watchdog-stopped or discarded run
    reaches these branches. A blind write of `paused_backend_restart_failed`
    demotes a finished run to a non-terminal one — and that status is
    deliberately absent from the web's TERMINAL_RUN_STATUSES, so the listing
    page recomputes `isActivePipeline` as true and puts Stop and Pause back on
    a run that ended hours ago. That is the wave-10.7 defect reopened, and
    pressing Stop there overwrites the record permanently."""
    writes = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, up: writes.append(up) or True)
    for terminal in research.TERMINAL_RESEARCH_STATUSES:
        writes.clear()
        monkeypatch.setattr(research, "_firebase_db", _FakeDb({}, {"status": terminal}))
        research._resume_drop_writeback("uid", "rid", "because")
        assert writes and "status" not in writes[0], (
            f"a {terminal} run was demoted to paused_backend_restart_failed")
        assert writes[0]["lastError"] == "because", "and it still says why"
    # ⭐ ACCEPT POLARITY — a run that is genuinely still going IS moved.
    writes.clear()
    monkeypatch.setattr(research, "_firebase_db", _FakeDb({}, {"status": "ongoing"}))
    research._resume_drop_writeback("uid", "rid", "because")
    assert writes[0]["status"] == "paused_backend_restart_failed"


def test_an_unreadable_document_leaves_the_status_alone(monkeypatch):
    """⚠ FAILS CLOSED, and that is the cheap direction. The worst case is a
    sentence with no status change — the person still learns why. The other
    direction demotes a finished run."""
    writes = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, up: writes.append(up) or True)
    monkeypatch.setattr(research, "_firebase_db", _FakeDb({}, RuntimeError("503")))
    research._resume_drop_writeback("uid", "rid", "because")
    assert "status" not in writes[0]
    monkeypatch.setattr(research, "_firebase_db", None)
    writes.clear()
    research._resume_drop_writeback("uid", "rid", "because")
    assert "status" not in writes[0]


def test_the_failed_status_is_still_outside_the_enqueue_whitelist(monkeypatch):
    """⛔ THE REASON THE ABOVE MATTERS, pinned rather than remembered. If this
    ever changes, the choice made on each branch has to be revisited — and
    nothing else in the suite would notice."""
    default = inspect.signature(research._safe_enqueue).parameters["allowed_statuses"].default
    assert "paused_backend_restart_failed" not in default
    assert "paused_backend_restart" in default


# ══ 3. the 12-hour carve-out that used to lose the overnight case ══════
def test_a_resume_that_waited_overnight_is_told_why_and_keeps_its_status(monkeypatch):
    """⛔⛔ THE CARVE-OUT. The abandoned sweep exempted `start` docs from its
    health-read rescue and left a note reading "(resume docs keep their prior
    behavior — out of scope.)" — and the prior behaviour is a silent delete.
    The banner's own copy is "Start Super Research on your PC, then tap Resume",
    so tapping before booting is the order the product asks for."""
    old = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    journal = _drive(monkeypatch, _resume_doc(timestamp=old), [])
    writes = _writes(journal)
    assert writes, "a resume dropped by the 12h sweep still said nothing"
    assert "more than 12 hours" in writes[0]["lastError"]
    # ⛔ THE STATUS MUST NOT MOVE. The files are still there; the 7-day sweep is
    # what removes them. Stamping the failed status would close auto-resume on a
    # run that can still be picked up.
    assert "status" not in writes[0]
    assert _order(journal).index("write") < _order(journal).index("delete")


def test_a_read_that_merely_FAILED_says_nothing_because_the_request_replays(monkeypatch):
    """⛔⛔ THE OVER-CORRECTION, AND A MUTANT FOUND IT MISSING. Only three of the
    nine exits are unrecoverable. This one is not: a denied or failed read of
    the research document is transient, the queue entry is deleted but the
    banner stays, and the next restart replays it. Telling the person their run
    failed here is the same lie this file exists to end, pointed the other way —
    and it is the change a reviewer is most likely to wave through as "more
    coverage"."""
    denied = PermissionError("403 Missing or insufficient permissions")
    journal = _drive(monkeypatch, _resume_doc(), [], research_doc=denied)
    assert _writes(journal) == [], (
        "a transient read failure was reported to the person as a failed run")
    assert "delete" in _order(journal)


def test_a_stale_START_doc_is_untouched_by_the_resume_write_back(monkeypatch):
    """⭐ THE OVER-CORRECTION GUARD. The sweep handles both kinds. A start doc
    that ages out is a different story with its own rescue, and writing a
    resume sentence onto it would be a lie about which request was dropped."""
    old = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    journal = _drive(monkeypatch, _resume_doc(action="start", timestamp=old), [])
    for w in _writes(journal):
        assert "12 hours" not in str(w.get("lastError", ""))


# ══ 4. the order, over the parse tree ══════════════════════════════════
def _resume_branch_nodes():
    """Every `if` inside the start listener whose body drops a resume."""
    src = Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "start_firestore_start_listener":
            return node
    raise AssertionError("start_firestore_start_listener not found")


def _calls_not_under_a_nested_if(stmts):
    """Write/delete calls directly in these statements, NOT inside a nested if.

    ⛔ `ast.walk` PLUS A `continue` DOES NOT PRUNE — walk yields every
    descendant regardless, so the first attempt let an outer branch inherit the
    deletes of every sibling branch beneath it and failed on correct code. A
    false alarm is the same disease as a silent pass: both make the harness
    something you stop believing.
    """
    found = []

    def _descend(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                continue
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Name) and f.id == "_resume_drop_writeback":
                    found.append(("write", child.lineno))
                if isinstance(f, ast.Attribute) and f.attr == "delete":
                    found.append(("delete", child.lineno))
            _descend(child)

    for stmt in stmts:
        if isinstance(stmt, ast.If):
            continue
        _descend(stmt)
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            pass
    return found


def test_every_write_back_precedes_its_delete_in_the_parse_tree():
    """⛔⛔ A `toContain` CANNOT TELL WRITE-THEN-DELETE FROM DELETE-THEN-WRITE,
    and the delete is what makes the write unrepeatable — a failure here is
    silent on every text-shaped pin. Walking the tree is what makes the ORDER
    the thing measured."""
    fn = _resume_branch_nodes()
    seen = 0
    paired = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        # ⛔ THE IMMEDIATE BODY ONLY. Walking the whole subtree made an OUTER
        # `if` inherit the deletes of every branch nested under it, so the test
        # failed on code that was correct — a false alarm is the same disease
        # as a silent pass. The write and the delete that concern each other
        # are siblings, so siblings is what this reads.
        # ⛔ BOTH ARMS. Checking only `body` meant an `else:` that also writes
        # was invisible — and the repair that split the no-backendRunId branch
        # put a write in exactly that arm. A checker blind to half a branch
        # under-counts, which is how `seen` came out one short and told me so.
        body_calls = (_calls_not_under_a_nested_if(node.body)
                      + _calls_not_under_a_nested_if(node.orelse))
        kinds = [k for k, _ in body_calls]
        if "write" not in kinds:
            continue
        seen += 1
        first_write = min(ln for k, ln in body_calls if k == "write")
        deletes_after = [ln for k, ln in body_calls if k == "delete" and ln > first_write]
        deletes_before = [ln for k, ln in body_calls if k == "delete" and ln < first_write]
        # ⛔ THE RULE IS ONE-SIDED, AND THE FIRST DRAFT GOT IT WRONG BOTH WAYS.
        # "every write branch must also delete" is false: the 12-hour sweep
        # guards its write with a nested `if action == "resume"` and deletes
        # unconditionally AFTER it, which is correct and which that assertion
        # failed. What actually matters is the ORDER — a delete before the
        # write-back would remove the only thing that brings us back here.
        assert not deletes_before, (
            f"a queue entry is deleted (line {deletes_before}) before the "
            f"write-back at {first_write} that explains it — the delete is "
            f"what stops us coming back here")
        if deletes_after:
            paired += 1
    # ⛔ AND THE COUNTS, or this whole test passes vacuously on a file where
    # nothing calls the helper at all. Three branches write AND delete in the
    # same breath; the fourth is the 12-hour guard described above.
    # ⛔ THE COUNTS MOVED WITH A REPAIR, AND THE REASON IS RECORDED RATHER
    # THAN THE NUMBER QUIETLY LOWERED. Cross-verify found the no-backendRunId
    # branch closing auto-recovery on runs whose files are still on disk, so
    # that branch now forks: an on-disk run gets the sentence with no status
    # change, an absent one gets the full refusal. Both sub-branches write and
    # the delete is their shared sibling — the same shape the 12-hour guard
    # already had. So more branches WRITE, and the same two write-then-delete.
    # FOUR, measured, not guessed: the queue_dir-gone branch, the `.stop`
    # branch, the 12-hour guard, and the no-backendRunId fork — whose two arms
    # are two writes inside ONE `if`, so it counts once.
    assert seen >= 4, f"expected at least 4 write-back branches, walked {seen}"
    assert paired >= 2, f"expected 2 write-then-delete branches, found {paired}"


def test_the_no_run_id_branch_asks_the_disk_before_closing_recovery():
    """⛔⛔ CROSS-VERIFY SEPARATED TWO THINGS I HAD CONFLATED. "There is no run
    directory to point at" was my justification for closing auto-recovery on
    this branch — and it is true of the DOCUMENT, not the disk. The start
    listener writes `backendRunId` back with an update and falls back to a
    merged set precisely because that write can fail; when both fail the run
    proceeds with a real `queues/<run_id>` directory while the document carries
    nothing. `paused_backend_restart_failed` is outside BOTH enqueue whitelists,
    so writing it there ends that run's automatic recovery for ever."""
    fn = _resume_branch_nodes()
    # The call is in the assignment above the fork, so find the name it binds
    # and then the `if` that branches on it — matching the call inside the test
    # would pin a spelling rather than the structure.
    bound = {
        t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "_run_dir_owning_research"
    }
    assert bound, "the no-backendRunId branch no longer consults the disk"
    forks = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and any(isinstance(c, ast.Name) and c.id in bound for c in ast.walk(n.test))
    ]
    assert forks, "the disk answer is fetched and then never branched on"
    fork = forks[0]
    on_disk = _calls_not_under_a_nested_if(fork.body)
    absent = _calls_not_under_a_nested_if(fork.orelse)
    assert on_disk and absent, "one arm of the fork writes nothing"
    src = ast.dump(ast.Module(body=fork.body, type_ignores=[]))
    assert "status" in src and "None" in src, (
        "the on-disk arm must pass status=None — its run can still be resumed")


def test_a_run_whose_folder_is_on_disk_is_found_by_its_owner_file(tmp_path, monkeypatch):
    """⭐ The disk is the second opinion, and it is matched on `owner.json`'s
    researchId rather than the folder name — the name is sanitised and two
    researches can share a prefix."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    d = tmp_path / "queues" / "Topic_20260101_000000"
    d.mkdir(parents=True)
    (d / "owner.json").write_text('{"uid": "u", "researchId": "chat_A"}', encoding="utf-8")
    other = tmp_path / "queues" / "Topic_20260101_010000"
    other.mkdir(parents=True)
    (other / "owner.json").write_text('{"uid": "u", "researchId": "chat_B"}', encoding="utf-8")
    assert research._run_dir_owning_research("chat_A") == d
    assert research._run_dir_owning_research("chat_missing") is None
    assert research._run_dir_owning_research("") is None


def test_the_three_sentences_are_distinct_and_none_is_empty():
    """⭐ Three branches, three reasons. A shared sentence would make the card
    say the same thing about a swept folder and a deliberate stop, which is the
    class of flattening this project keeps having to undo."""
    lines = [research.RESUME_DROP_NO_RUN_ID,
             research.RESUME_DROP_NO_RUN_ID_ON_DISK,
             research.RESUME_DROP_ARTIFACTS_GONE,
             research.RESUME_DROP_TERMINALLY_STOPPED,
             research.RESUME_DROP_WENT_STALE]
    assert all(len(s.strip()) > 40 for s in lines)
    assert len(set(lines)) == 5
    # Each one tells the person what to do next, which is the whole point of
    # writing it rather than logging it.
    for s in lines:
        assert "Resume" in s or "Start it again" in s or "start the app" in s
