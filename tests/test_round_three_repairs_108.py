"""Round three of cross-verify, and the five fixes it named.

⛔⛔ WHY A THIRD ROUND EXISTS. Round one over wave 10.8 found six highs; round
two over the REPAIRS found a blocker and four more, because three of my own
fixes had cancelled each other. Round three found a blocker, four highs and four
smaller items — a flat trend, and two of the five top items were damage round
two's repairs had themselves created. What stopped the loop was not a clean
result: it was that every survivor had become a named one- or two-line change at
a single site, with no interaction between them.

⭐⭐ AND TWO OF THEM REQUIRED FLIPPING AN ASSERTION I HAD JUST WRITTEN, which is
the tell that a fix was pinned to the DECISION rather than to the BEHAVIOUR.
`_dispatch_never_left(ConnectionError, 3600) is True` canonised the defect in
exactly the way a test can: by agreeing with the code.
"""
import ast
import json
from pathlib import Path

import pytest

import research

OWNER = "uid-owner"
SHARER = "uid-sharer"
OTHER = "uid-third"


def _src() -> str:
    return Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")


def _fn(name: str):
    for node in ast.walk(ast.parse(_src())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


class _FakeRef:
    def __init__(self):
        self.deleted = 0

    def delete(self):
        self.deleted += 1


class _FakeDoc:
    def __init__(self):
        self.reference = _FakeRef()


# ══ 1. the refusal is a refusal, not a verdict somebody may ignore ═════════
#
# ⛔⛔ THE WIRING TESTS COULD NOT SEE THE FOUNDING DEFECT COME BACK. Round three
# built two mutants of the old shape and ran the previous suite's own AST logic
# against each: `if False and _owner_control_refused(...)` stayed green, and so
# did keeping the call while replacing its body with a log — which is this
# wave's founding defect verbatim, every assertion passing. Name-presence in a
# parse tree is not a measurement of what a branch DOES.

@pytest.fixture(autouse=True)
def _owner(monkeypatch):
    monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)


def _doc(**over):
    base = {"action": "cancel", "uid": SHARER, "submittedBy": SHARER,
            "researchId": "chat_1"}
    base.update(over)
    return base


def test_a_refused_doc_is_actually_deleted():
    """⛔⛔ THE WHOLE REFUSAL, EXECUTED. A queue document we decline and leave
    in place is not declined — the next snapshot re-reads it, and the idle
    rescan sweeps up exactly the documents the listener passed over."""
    doc = _FakeDoc()
    assert research._refuse_owner_control(
        doc, _doc(uid=OWNER, submittedBy=SHARER), "t") is True
    assert doc.reference.deleted == 1, (
        "the doc was refused and left in the collection to be re-read")


def test_an_allowed_doc_is_left_completely_alone():
    """⭐ ACCEPT POLARITY. A guard that deletes the document it is about to
    allow has stopped the work just as effectively as one that refuses it."""
    doc = _FakeDoc()
    assert research._refuse_owner_control(doc, _doc(), "t") is False
    assert doc.reference.deleted == 0
    # and the owner's deliberate divergence — the Shared-with popup
    doc2 = _FakeDoc()
    assert research._refuse_owner_control(
        doc2, _doc(uid=SHARER, submittedBy=OWNER), "t") is False
    assert doc2.reference.deleted == 0


def test_a_delete_that_raises_still_counts_as_refused():
    """⛔ The verdict must not depend on the cleanup succeeding. A sibling
    worker deleting the doc first is the ordinary case, not an error."""
    class _Boom(_FakeDoc):
        def __init__(self):
            super().__init__()
            self.reference = type("R", (), {"delete": lambda _s: (_ for _ in ()).throw(RuntimeError("gone"))})()
    assert research._refuse_owner_control(
        _Boom(), _doc(uid=OWNER, submittedBy=SHARER), "t") is True


def test_both_dispatch_branches_call_the_refusal_helper():
    """⛔⛔ HELPER-PINNED, CONSUMER-NOT is this project's commonest miss. This
    still reads the tree — but what it looks for now PERFORMS the refusal, so
    the mutant that keeps the call and drops its effect no longer exists."""
    fn = _fn("start_firestore_start_listener")
    found = {}
    for node in ast.walk(fn):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)):
            continue
        left, ops, comps = node.test.left, node.test.ops, node.test.comparators
        if not (isinstance(left, ast.Name) and left.id == "action"):
            continue
        if not (len(ops) == 1 and isinstance(ops[0], ast.Eq)):
            continue
        if comps and isinstance(comps[0], ast.Constant) and comps[0].value in ("cancel", "resume"):
            found[comps[0].value] = ast.dump(ast.Module(body=node.body, type_ignores=[]))
    assert set(found) == {"cancel", "resume"}, sorted(found)
    for verb, body in found.items():
        assert "_refuse_owner_control" in body, (
            f"the {verb} branch acts on another person's uid with no guard")


def test_the_guard_is_the_whole_condition_not_one_term_of_it():
    """⛔⛔ `if False and _owner_control_refused(...)` — the mutant that defeated
    the previous shape. A guard whose test is a BoolOp can be neutered by a term
    the name-search still passes."""
    fn = _fn("start_firestore_start_listener")
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(n, ast.Name) and n.id == "_refuse_owner_control"
                   for n in ast.walk(node.test)):
            continue
        assert isinstance(node.test, ast.Call), (
            "the refusal is one term of a compound condition — something else "
            "can decide the branch")


# ══ 2. the half the identity guard cannot see ══════════════════════════════
#
# ⛔⛔ BOTH LAYERS ASKED THE SAME QUESTION. The rule and the machine guard each
# check whether `uid` disagrees with `submittedBy`; neither asks whether the
# `researchId` belongs to `uid`. So a member signs honestly as themselves and
# names somebody else's run: no divergence, both layers pass, and the cancel
# handler matches its target on `research_id` alone.

def test_a_job_that_names_another_person_is_recognised():
    assert research._job_is_another_persons({"uid": SHARER}, OWNER) is True
    assert research._job_is_another_persons({"uid": OWNER}, SHARER) is True


def test_a_persons_own_job_is_not():
    """⭐ THE HALF THAT MATTERS MOST. A guard that refused every cancel would be
    secure and would have taken the product away from everyone."""
    assert research._job_is_another_persons({"uid": SHARER}, SHARER) is False
    assert research._job_is_another_persons({"uid": OWNER}, OWNER) is False


def test_absent_is_not_disagreeing():
    """⛔ The same rule both identity guards state. A job dict predating the
    uid requirement must still be cancellable by its owner."""
    assert research._job_is_another_persons({}, SHARER) is False
    assert research._job_is_another_persons({"uid": ""}, SHARER) is False
    assert research._job_is_another_persons({"uid": SHARER}, "") is False
    assert research._job_is_another_persons(None, SHARER) is False


def test_the_sweep_finds_the_victims_job_wherever_it_is_parked():
    """⛔⛔ FIVE MATCH SITES, ONE GATE. The handler matches its target in the
    gate-pending job, the running job, both of their race re-checks and the
    deque scan — a check added to some of them is not a check."""
    victim = {"research_id": "chat_v", "uid": OTHER}
    mine = {"research_id": "chat_m", "uid": SHARER}
    assert research._another_persons_run_locally(
        [mine, victim], "chat_v", SHARER) is True
    assert research._another_persons_run_locally(
        [mine, victim], "chat_m", SHARER) is False
    # ⛔⛔ A research this process holds no job for is not something the LOCAL
    # sweep can judge — which is all this asserts, and all it ever could. The
    # comment here used to read "is not somebody else's", and that was the
    # unguarded case (wave 10.9): a deferred run is held by nobody, so this is
    # False for it and the deferred scan deleted the victim's start doc. That
    # path now asks the START doc's own uid (`_deferred_start_doc_id`, executed
    # in test_member_run_ownership_109.py). Not flipped: refusing every cancel
    # for a research nobody holds would refuse a person's own queued run.
    assert research._another_persons_run_locally([mine], "chat_x", SHARER) is False
    assert research._another_persons_run_locally([], "chat_v", SHARER) is False
    # ⛔ and an empty research id must not match the empty slots the caller
    # passes in for an idle worker — `current_job` is `{}` most of the time.
    assert research._another_persons_run_locally([{}, {}], "", SHARER) is False


def _cancel_branch():
    fn = _fn("start_firestore_start_listener")
    for node in ast.walk(fn):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "action"
                and node.test.comparators
                and isinstance(node.test.comparators[0], ast.Constant)
                and node.test.comparators[0].value == "cancel"):
            return node
    raise AssertionError("the cancel dispatch branch is gone")


def test_a_cancel_aimed_at_another_persons_run_is_refused_and_dropped():
    """⛔⛔⛔ A MUTANT SURVIVED THE FIRST VERSION OF THIS PAIR, and it is this
    project's commonest miss wearing its third disguise in one wave. The branch
    read `if _another_persons_run_locally(...)` and the test asked whether that
    NAME appeared and whether its line came before `request_stop`. Wrapping the
    call as `if False and _another_persons_run_locally(...)` keeps the name,
    the line number AND the ordering — so the test passed while the victim's
    run was stopped anyway, a permanent `.stop` left behind it.

    ⭐ EXECUTED NOW. The refusal is performed by a function, so a fake document
    can be asked whether the delete actually fired."""
    doc = _FakeDoc()
    victim = {"research_id": "chat_v", "uid": OTHER}
    assert research._refuse_foreign_run(
        doc, [victim], "chat_v", SHARER, "t") is True
    assert doc.reference.deleted == 1, (
        "the cancel was refused and its queue document left to be re-read")


def test_a_cancel_of_your_own_run_is_left_completely_alone():
    """⭐ ACCEPT POLARITY. A guard that also dropped the honest cancel would
    take the product away from every member of a shared computer."""
    doc = _FakeDoc()
    mine = {"research_id": "chat_m", "uid": SHARER}
    assert research._refuse_foreign_run(
        doc, [mine], "chat_m", SHARER, "t") is False
    assert doc.reference.deleted == 0
    # and a research this process holds no job for is not somebody else's
    doc2 = _FakeDoc()
    assert research._refuse_foreign_run(
        doc2, [mine], "chat_unknown", SHARER, "t") is False
    assert doc2.reference.deleted == 0


def test_the_cancel_branch_consults_the_sweep_before_it_stops_anything():
    """⛔ ORDER. A refusal after `request_stop` is not a refusal — and `.stop`
    is permanent, so this wave's own resume path would then answer every later
    Resume with "This run was stopped for good"."""
    branch = _cancel_branch()
    gates = [n.lineno for n in ast.walk(branch) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "_refuse_foreign_run"]
    # ⛔ AN ATTRIBUTE, NOT A NAME — `_controls.request_stop`. My first version
    # looked for a bare Name, found none, and would have passed the ordering
    # assertion vacuously if the `assert stops` line below were not here.
    stops = [n.lineno for n in ast.walk(branch) if isinstance(n, ast.Attribute)
             and n.attr == "request_stop"]
    assert gates, "the cancel branch never asks whose run this is"
    assert stops, "the cancel branch no longer stops anything — check this test"
    assert min(gates) < min(stops), (
        "the run is stopped before anyone checks whether the person asking "
        "owns it")


def test_the_ownership_gate_is_the_WHOLE_condition():
    """⛔⛔⛔ THE MUTANT THAT SURVIVED: `if False and _refuse_foreign_run(...)`.
    Every name stays, every line number stays, the ordering stays. The only
    thing that changes is the SHAPE of the test, so that is what to assert —
    a bare Call, and a body that does nothing but leave."""
    branch = _cancel_branch()
    guards = [n for n in ast.walk(branch) if isinstance(n, ast.If)
              and any(isinstance(x, ast.Name) and x.id == "_refuse_foreign_run"
                      for x in ast.walk(n.test))]
    assert len(guards) == 1, f"expected one ownership gate, found {len(guards)}"
    gate = guards[0]
    assert isinstance(gate.test, ast.Call), (
        "the ownership gate is one term of a compound condition — something "
        "else can decide whether the victim's run gets stopped")
    assert isinstance(gate.test.func, ast.Name), "the gate is called indirectly"
    assert [type(n) for n in gate.body] == [ast.Continue], (
        "the refusal branch does something other than leave, so the code below "
        "it may still run")
    assert not gate.orelse


def test_the_race_rechecks_ask_it_too():
    """⛔ THE WHOLE REASON THIS BRANCH EXISTS is that a job can arrive after the
    listener-thread gate ran, so it is exactly where the gate cannot be assumed
    to have covered the job it matches.

    ⛔ THERE WERE TWO OF THEM until wave 10.9. The second re-checked
    `gate_pending_now` — the job a worker held while it waited on the previous
    run's cloud tail — and that wait, and its slot, are gone (N8): a dequeued
    job is `current_job` from the moment it leaves the queue. The count is
    asserted, not merely iterated, so a re-check that quietly stops asking the
    ownership question still fails this."""
    fn = _fn("start_firestore_start_listener")
    do_cancel = next(n for n in ast.walk(fn)
                     if isinstance(n, ast.FunctionDef) and n.name == "_do_cancel")
    checked = 0
    for node in ast.walk(do_cancel):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "current_now" not in names:
            continue
        assert "_job_is_another_persons" in names, (
            "a race re-check matches on research_id alone — the window the "
            "listener-thread gate cannot cover is the window left open")
        checked += 1
    assert checked == 1, f"expected the race re-check, saw {checked}"


def test_the_deque_scan_drops_only_this_persons_job():
    """⛔ Matching on research_id alone made "the job I named" and "the job I
    own" the same sentence, which is the confusion this repair is about."""
    fn = _fn("start_firestore_start_listener")
    do_cancel = next(n for n in ast.walk(fn)
                     if isinstance(n, ast.FunctionDef) and n.name == "_do_cancel")
    cancels = next((n for n in ast.walk(do_cancel)
                    if isinstance(n, ast.FunctionDef) and n.name == "_cancels"), None)
    assert cancels is not None, "the deque scan no longer has an ownership predicate"
    assert any(isinstance(n, ast.Name) and n.id == "_job_is_another_persons"
               for n in ast.walk(cancels))
    # and the predicate is what the scan actually uses
    dumped = ast.dump(do_cancel)
    assert "'kept'" in dumped or "kept" in dumped
    assert dumped.count("_cancels") >= 3, (
        "the predicate is defined and the scan still filters some other way")


# ══ 3. a client-supplied run id is a claim, not a fact ═════════════════════

@pytest.fixture
def _queues(tmp_path, monkeypatch):
    """Point research.py's `queues/` at a scratch tree."""
    fake = tmp_path / "research.py"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(research, "__file__", str(fake))
    q = tmp_path / "queues"
    # ⭐ BOTH HALVES OF THE RECORD, as `setup_firestore_run` writes it. The
    # fixture used to carry the research alone, which is how the person half
    # of the question went unasked (wave 10.9).
    for run, rid, uid in (("run_victim", "chat_victim", OTHER),
                          ("run_mine", "chat_mine", SHARER)):
        (q / run).mkdir(parents=True)
        (q / run / "owner.json").write_text(
            json.dumps({"uid": uid, "researchId": rid}), encoding="utf-8")
    (q / "run_legacy").mkdir(parents=True)          # no owner.json at all
    return q


def test_a_resume_payload_cannot_point_at_another_runs_directory(_queues):
    """⛔⛔⛔ EXECUTED, AND A MUTANT IS WHY. `backendRunId` is read straight off
    the queue document deliberately — that is how a synth user who cannot read
    the research doc still resumes — so nothing upstream checks that the run it
    names is the research it names. Unchecked it resumes somebody else's
    directory under this person's research, clearing their `.no_auto_retry` and
    their `.pause` on the way.

    The first version of this pin read the listener's parse tree for the string
    "owner.json" and for an assignment of `""`. Both survive
    `if False and backend_run_id:`, and the harness proved it."""
    # the claim names a run that belongs to somebody else → refused
    assert research._corroborated_run_id("run_victim", "chat_mine", SHARER) == ""
    # ⛔⛔ AND NAMING THE VICTIM'S RESEARCH TOO NO LONGER HELPS (wave 10.9).
    # Research ids are published to every member, so this is the real attack.
    assert research._corroborated_run_id("run_victim", "chat_victim", SHARER) == ""
    # the claim is honest → kept
    assert research._corroborated_run_id("run_mine", "chat_mine", SHARER) == "run_mine"
    assert research._corroborated_run_id("run_victim", "chat_victim", OTHER) == "run_victim"


def test_silence_from_the_disk_is_not_a_refusal(_queues):
    """⭐ ACCEPT POLARITY, and it is the half that keeps the product working. A
    directory with no readable `owner.json` is the ordinary pre-owner.json
    shape; only a directory that positively names a DIFFERENT research loses
    its claim. Refusing on absence would break resume for every run that
    predates that file."""
    assert research._corroborated_run_id("run_legacy", "chat_mine", SHARER) == "run_legacy"
    assert research._corroborated_run_id("run_missing", "chat_mine", SHARER) == "run_missing"
    # and the degenerate inputs pass through rather than being invented
    assert research._corroborated_run_id("", "chat_mine", SHARER) == ""
    assert research._corroborated_run_id("run_mine", "", SHARER) == "run_mine"


def test_the_predicate_in_the_other_direction_still_works(_queues):
    """`_run_dir_owning_research` is the same question asked from the disk —
    and, as of wave 10.9, asked about the person as well as the research."""
    assert research._run_dir_owning_research("chat_victim", OTHER) == _queues / "run_victim"
    assert research._run_dir_owning_research("chat_mine", SHARER) == _queues / "run_mine"
    assert research._run_dir_owning_research("chat_absent", SHARER) is None
    assert research._run_dir_owning_research("chat_victim", SHARER) is None, (
        "the disk handed one member another member's run directory")


def test_the_resume_branch_assigns_through_the_corroboration_unconditionally():
    """⛔⛔ THE CONSUMER, PINNED ON SHAPE. The mutant that survived wrapped the
    whole check in `if False and backend_run_id:` — every name the old test
    looked for stayed exactly where it was. There is no branch to neuter now:
    `backend_run_id` is ASSIGNED from the call, so a mutant must change the
    assignment's value node, which is what this asserts."""
    fn = _fn("start_firestore_start_listener")
    branch = next(n for n in ast.walk(fn)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                  and isinstance(n.test.left, ast.Name) and n.test.left.id == "action"
                  and n.test.comparators
                  and isinstance(n.test.comparators[0], ast.Constant)
                  and n.test.comparators[0].value == "resume")
    # ⛔⛔ RE-AIMED IN WAVE 10.9, deliberately. The branch used to assign
    # `backend_run_id = _corroborated_run_id(backend_run_id, target_rid)` and
    # then took the research document's `backendRunId` UNCHECKED — the same
    # claim, from the sender's own tree. Both claims now go through one
    # resolution, `_resume_run_id`, assigned as a tuple; its behaviour (and
    # this branch's) is EXECUTED in test_member_run_ownership_109.py. What is
    # left for the parse tree is the shape the surviving mutant exploited.
    def _binds_run_id(t):
        if isinstance(t, ast.Name):
            return t.id == "backend_run_id"
        return isinstance(t, ast.Tuple) and any(
            isinstance(e, ast.Name) and e.id == "backend_run_id" for e in t.elts)
    assigns = [n for n in ast.walk(branch) if isinstance(n, ast.Assign)
               and any(_binds_run_id(t) for t in n.targets)]
    through = [n for n in assigns if isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "_resume_run_id"]
    assert through, (
        "the payload's run id is used without being corroborated against the "
        "directory it names")
    # ⛔ AND IT MUST NOT SIT UNDER A CONDITION *INSIDE* THE BRANCH. An `if`
    # above it is precisely what the surviving mutant exploited.
    #
    # ⛔ `node is not branch` IS LOAD-BEARING. Without it this fired on the
    # dispatch branch itself — `if action == "resume":` is an `ast.If` and the
    # assignment is of course in its body — so a correct fix failed the test.
    # That is the second time in this round that my own checker was the thing
    # that was wrong.
    # ⛔ ANYWHERE UNDER IT, NOT ONLY AS A DIRECT CHILD (wave 10.9). The call now
    # sits in a `try:` — so an `if False:` wrapped round that `try` would have
    # held the assignment as a grandchild, and a direct-children check passes.
    for node in ast.walk(branch):
        if not isinstance(node, ast.If) or node is branch:
            continue
        guarded = [x for part in (node.body, node.orelse) for stmt in part
                   for x in ast.walk(stmt)]
        if any(a is through[0] for a in guarded):
            raise AssertionError(
                "the corroboration is guarded by a condition again — that is "
                "the exact shape the mutant neutered")
    # ⛔ AND NOTHING ELSE IN THE BRANCH SETS THE RUN ID but the disk arm, which
    # adopts a directory `_run_dir_owning_research` found for this person. A raw
    # `backend_run_id = data.get("backendRunId")` or `rd.get(...)` re-added here
    # would bypass the resolution — the hole this wave closed on the document.
    others = [n for n in assigns if n is not through[0]]
    for n in others:
        assert (isinstance(n.value, ast.Attribute) and n.value.attr == "name"), (
            f"line {n.lineno} sets the run id from something other than the "
            f"resolution or the disk arm: {ast.dump(n.value)[:80]}")
    assert "backendRunId" not in "".join(ast.dump(n.value) for n in others)


# ══ 4. the twelve-hour sweep writes into a named person's document ═════════

def test_the_stale_sweep_is_gated_by_the_same_guard():
    """⛔⛔ IT RAN SIXTY LINES ABOVE THE LINE THAT READS `action`, so it reached
    a named person's research document before either owner-control layer was
    consulted — the one path where the machine check and the Firestore rule are
    not two layers but one. In the window the machine guard exists for, a resume
    doc naming somebody else's tree landed `lastError`, `resumeDropReason` and
    its stamp in their document; and this wave taught the card to prefer that
    reason for every recovery status."""
    fn = _fn("start_firestore_start_listener")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_resume_drop_writeback"]
    assert calls, "the write-back is gone entirely"
    stale = [n for n in ast.walk(fn)
             if isinstance(n, ast.If)
             and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                     and c.func.id == "_resume_drop_writeback"
                     for c in ast.walk(n))
             and any(isinstance(x, ast.Name) and x.id == "_owner_control_refused"
                     for x in ast.walk(n.test))]
    assert stale, (
        "the stale-resume write-back reaches a research document with no "
        "ownership check above it")


# ══ 5. a successful resume retires its own refusal ════════════════════════

def test_the_resume_success_write_deletes_the_drop_fields():
    """⛔⛔ ROUND ONE'S DEFECT, ON THE REPLACEMENT FIELD. `resumeDropReason` was
    given one writer to fix the stale-`lastError` problem, and then the card was
    widened to prefer it for all four recovery statuses — while it still had no
    deleter. So a Resume that WORKED left its old refusal standing: the run hits
    the watchdog ceiling hours later and the card reads "Your earlier Resume sat
    waiting for more than 12 hours…" under "Run stopped — it hit the time
    limit", suppressing "Your PC was fine throughout" — the sentence a
    2026-09-01 measurement exists to protect."""
    fn = _fn("start_firestore_start_listener")
    branch = next(n for n in ast.walk(fn)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                  and isinstance(n.test.left, ast.Name) and n.test.left.id == "action"
                  and n.test.comparators
                  and isinstance(n.test.comparators[0], ast.Constant)
                  and n.test.comparators[0].value == "resume")
    writes = [n for n in ast.walk(branch)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_update_research_doc"
              and any(isinstance(k, ast.Constant) and k.value == "assignedWorker"
                      for a in n.args if isinstance(a, ast.Dict) for k in a.keys)]
    assert len(writes) == 1, (
        f"expected exactly one success write to match on, found {len(writes)}")
    payload = next(a for a in writes[0].args if isinstance(a, ast.Dict))
    keys = {k.value for k in payload.keys if isinstance(k, ast.Constant)}
    assert {"resumeDropReason", "resumeDropAt"} <= keys, (
        "a resume that succeeded leaves its refusal on the document, and the "
        "card prefers that refusal for every recovery status")
    # ⛔ RESOLVE THE ALIAS, DO NOT GUESS AT ITS SPELLING. My first version asked
    # whether the value's name contained "DELETE" — which the file's own
    # convention (`as _DF`) does not, so a correct fix failed the test. Follow
    # the import instead: whatever DELETE_FIELD was bound to in this branch.
    deleters = {a.asname or a.name
                for n in ast.walk(branch) if isinstance(n, ast.ImportFrom)
                for a in n.names if a.name == "DELETE_FIELD"}
    assert deleters, "the resume branch imports no DELETE_FIELD to clear with"
    for name in ("resumeDropReason", "resumeDropAt"):
        idx = [i for i, k in enumerate(payload.keys)
               if isinstance(k, ast.Constant) and k.value == name][0]
        val = payload.values[idx]
        assert isinstance(val, ast.Name) and val.id in deleters, (
            f"{name} is overwritten rather than deleted — an empty string is a "
            f"value the card will happily render")


def test_the_writeback_still_stamps_every_refusal():
    """⭐ THE STAMP IS WHAT MAKES A REPEAT REFUSAL VISIBLE AT ALL. Three of the
    nine drop branches are permanent, so the WORDS are identical on every press
    — the web's 45-second fallback can only tell "it answered again" from "it
    said nothing" by this number moving."""
    fn = _fn("_resume_drop_writeback")
    dumped = ast.dump(fn)
    assert "resumeDropAt" in dumped and "resumeDropReason" in dumped
    stamps = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "time"]
    assert stamps, "the refusal is no longer stamped, so repeats are invisible"


# ══ 6. the start guard is a different rule and must stay one ══════════════

def test_the_start_guard_refuses_the_owners_divergence_too():
    """⛔⛔ THE PREVIOUS PIN WAS A SOURCE LITERAL THAT LIVES IN THE SHARED
    HELPER. It asserted `"if uid and claimed and uid != claimed:" in src`, and
    that line occurs exactly once — inside `_start_doc_identity_conflict`, which
    the NEW guard also calls. So adding an owner exemption to
    `_start_doc_identity_refused` — the exact edit its docstring forbids — left
    the assertion green. Executed, it cannot.

    ⭐ AND THE TWO RULES REALLY ARE DIFFERENT. A divergent START doc runs in a
    tree its writer does not own, whoever wrote it; a divergent CANCEL is the
    Shared-with popup doing its job."""
    doc = {"uid": SHARER, "submittedBy": OWNER, "researchId": "chat_1"}
    assert research._start_doc_identity_refused(doc, "t") is True, (
        "the start guard learned about owners — a divergent start doc runs in "
        "somebody else's tree no matter who signed it")
    assert research._owner_control_refused(doc, "t") is False, (
        "the control guard forgot about owners — this is the Shared-with popup")
    # and the ordinary shapes, so the polarity above is not accidental
    assert research._start_doc_identity_refused(
        {"uid": SHARER, "submittedBy": SHARER}, "t") is False
    assert research._start_doc_identity_refused({}, "t") is False
