"""Only the device owner may act on somebody else's run.

⛔⛔ THE HOLE, FOUND BY THE 2026-09-21 GROUP-SECURITY AUDIT AND CONFIRMED BY THE
OWNER AS "definitely fix it". The Firestore rule pinned `submittedBy` — the
field this listener does NOT act on — and left `uid` free, which is the one it
reads to decide whose tree to write into and whose run to stop. The identity
guard that would have caught the divergence is scoped to `action == "start"`,
below the line that skips every other action.

So one client write let any member of a shared computer cancel, purge or
force-resume another member's run. Everything needed — their uid, their
researchId — sits on the device document every member reads whole. The victim's
chat then said "Stopped by the device owner": false, and naming nobody. A cancel
carrying `ownerControl` additionally sets `cancelled: True`, which drives the
web's delete-on-close cascade, so the research went with it.

⭐ THE DIVERGENCE IS A REAL FEATURE AND STAYS. It is exactly how the owner's
"Shared with" popup stops a sharer's run: the web writes `uid=<sharer>,
submittedBy=<owner>` deliberately, and its own docstring says the gate is at the
CALL SITE. A call site is a UI affordance, not a gate.

⭐⭐ AND THE CHECK IS HERE AS WELL AS IN THE RULES, DELIBERATELY. Rules deploy in
one command; the machine upgrades when its owner chooses. The two are never in
step, and this listener is the thing that acts.
"""
import ast
from pathlib import Path

import pytest

import research

OWNER = "uid-owner"
SHARER = "uid-sharer"


def _fn(name):
    src = Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


@pytest.fixture(autouse=True)
def _owner(monkeypatch):
    monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)


def _dispatch_branches(fn):
    """Every `if action == "<verb>"` branch that acts on a queue doc's uid."""
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        left, ops, comps = node.test.left, node.test.ops, node.test.comparators
        if not (isinstance(left, ast.Name) and left.id == "action"):
            continue
        if not (len(ops) == 1 and isinstance(ops[0], ast.Eq)):
            continue
        if not (comps and isinstance(comps[0], ast.Constant)):
            continue
        if comps[0].value in ("cancel", "resume"):
            out.append((comps[0].value, node))
    return out


def _doc(**over):
    base = {"action": "cancel", "uid": SHARER, "submittedBy": SHARER,
            "researchId": "chat_1"}
    base.update(over)
    return base


# ══ 1. the refusal ═════════════════════════════════════════════════════
def test_a_sharer_cannot_act_on_another_persons_run():
    """⛔⛔ THE DEFECT. The writer signs honestly as themselves and names
    somebody else's run — which is precisely the shape the rule permitted,
    because it only ever checked the signature."""
    assert research._owner_control_refused(
        _doc(uid=OWNER, submittedBy=SHARER), "t") is True
    assert research._owner_control_refused(
        _doc(action="resume", uid=OWNER, submittedBy=SHARER), "t") is True
    assert research._owner_control_refused(
        _doc(uid="uid-third", submittedBy=SHARER), "t") is True


def test_the_owner_still_can_because_that_is_the_feature():
    """⭐ The Shared-with popup. Taking this away would remove the control the
    owner actually has, which is worse than the bug."""
    assert research._owner_control_refused(
        _doc(uid=SHARER, submittedBy=OWNER), "t") is False
    assert research._owner_control_refused(
        _doc(action="resume", uid=SHARER, submittedBy=OWNER), "t") is False


def test_everyone_still_governs_their_own_run():
    """⭐ ACCEPT POLARITY, and the half that matters most. A guard that refused
    every divergence would be right; one that refuses a person cancelling their
    OWN work has taken the product away from them."""
    assert research._owner_control_refused(
        _doc(uid=SHARER, submittedBy=SHARER), "t") is False
    assert research._owner_control_refused(
        _doc(uid=OWNER, submittedBy=OWNER), "t") is False


def test_a_doc_that_names_no_writer_is_left_alone():
    """⛔ ABSENT IS NOT DISAGREEING — the same rule the start-doc guard states.
    A legacy doc naming no writer must still work; it simply ends up
    attributable to nobody."""
    assert research._owner_control_refused(_doc(submittedBy=""), "t") is False
    assert research._owner_control_refused(_doc(uid=""), "t") is False
    assert research._owner_control_refused({}, "t") is False


def test_an_unknown_owner_refuses_rather_than_waving_it_through():
    """⛔ FAIL CLOSED. If this machine cannot say who it is paired with, it
    cannot tell an owner's action from an impostor's — and the cheap direction
    is to refuse a cross-person action, which the person can retry, rather than
    to destroy somebody's research."""
    def _boom():
        raise RuntimeError("keystore unreadable")
    import unittest.mock as _m
    with _m.patch.object(research, "load_paired_uid", _boom):
        assert research._owner_control_refused(
            _doc(uid=OWNER, submittedBy=SHARER), "t") is True
    with _m.patch.object(research, "load_paired_uid", lambda: ""):
        assert research._owner_control_refused(
            _doc(uid=OWNER, submittedBy=SHARER), "t") is True


# ══ 2. the wiring, because a helper is not a consumer ══════════════════
def test_both_branches_that_act_on_uid_consult_it():
    """⛔⛔ HELPER-PINNED, CONSUMER-NOT is this project's commonest miss — and
    the original defect was precisely a guard that existed and was scoped to a
    branch that did not need it."""
    # ⛔ THE DISPATCH BRANCHES ONLY — `if action == "<verb>"`. My first version
    # matched any `if` whose test merely MENTIONED the word, which swept in the
    # abandoned-sweep condition (`action != "cancel"`) and failed on code that
    # is correct. A false alarm is the same disease as a silent pass.
    fn = _fn("start_firestore_start_listener")
    guarded = _dispatch_branches(fn)
    assert {v for v, _ in guarded} == {"cancel", "resume"}, (
        f"expected the cancel and resume dispatch branches, found "
        f"{sorted(v for v, _ in guarded)}")
    for verb, node in guarded:
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        assert "_owner_control_refused" in body, (
            f"the {verb} branch acts on another person's uid with no guard")


def test_the_guard_runs_BEFORE_the_branch_reads_the_uid():
    """⛔ ORDER. A refusal after the write is not a refusal."""
    fn = _fn("start_firestore_start_listener")
    for _verb, node in _dispatch_branches(fn):
        guards = [n.lineno for n in ast.walk(node)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_owner_control_refused"]
        writes = [n.lineno for n in ast.walk(node)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ("_update_research_doc", "_owner_control_patch")]
        if guards and writes:
            assert min(guards) < min(writes), (
                "the branch writes to another person's tree before it checks "
                "whether it is allowed to")


def test_the_start_guard_is_still_scoped_to_start():
    """⭐ THE TWO GUARDS ARE DIFFERENT RULES AND MUST STAY SEPARATE. The start
    guard refuses ANY divergence, because a divergent start doc would run in
    somebody else's tree. This one permits the owner's, because that is the
    feature. Collapsing them would break the Shared-with popup."""
    src = Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")
    assert "_start_doc_identity_refused" in src
    assert "if uid and claimed and uid != claimed:" in src, (
        "the start guard learned about owners — it must not; a divergent START "
        "doc runs in a tree its writer does not own, whoever wrote it")
