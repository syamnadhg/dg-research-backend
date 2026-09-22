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
#
# ⛔⛔ AND NAME-PRESENCE IN A PARSE TREE WAS NOT ENOUGH, which round three of
# cross-verify proved by building the mutants and running this file's own logic
# against them. Both `if False and _owner_control_refused(...)` and a guard
# whose body was replaced by a log stayed green — the second being this wave's
# founding defect, verbatim. The refusal is now performed by
# `_refuse_owner_control`, which a test can EXECUTE against a fake document and
# ask whether the delete actually fired:
# see tests/test_round_three_repairs_108.py, section 1.
def test_the_guard_runs_BEFORE_the_branch_reads_the_uid():
    """⛔ ORDER. A refusal after the write is not a refusal."""
    fn = _fn("start_firestore_start_listener")
    for _verb, node in _dispatch_branches(fn):
        guards = [n.lineno for n in ast.walk(node)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ("_refuse_owner_control", "_owner_control_refused")]
        writes = [n.lineno for n in ast.walk(node)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ("_update_research_doc", "_owner_control_patch")]
        if guards and writes:
            assert min(guards) < min(writes), (
                "the branch writes to another person's tree before it checks "
                "whether it is allowed to")


# ⛔⛔ THE START-GUARD PIN THAT USED TO LIVE HERE MEASURED NOTHING. It asserted
# `"if uid and claimed and uid != claimed:" in src`, and that literal occurs
# exactly once — inside `_start_doc_identity_conflict`, the helper the NEW guard
# also calls. So adding an owner exemption to `_start_doc_identity_refused`, the
# exact edit its docstring forbids, left the assertion green. Replaced by an
# executed one: test_the_start_guard_refuses_the_owners_divergence_too.
