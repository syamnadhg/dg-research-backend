"""The human-verification card carries its OWN verdict.

⛔⛔ WHY A FIELD AND NOT A RE-DERIVATION. A Cloudflare wall cannot be cleared by
resuming — trying only makes Cloudflare ask harder, which the card's own copy
says. Every reader therefore needs to know which kind of check this is. The
frontend, and until now the agent bridge, worked it out by looking for the word
"cloudflare" in the card's `reason`.

`reason` is the wrong source. It is a non-latching nonlocal that later probes
overwrite, while the gate's own decision (`_is_cloudflare`) LATCHES. So a wall
that was identified as Cloudflare on an early probe, and whose last probe landed
in the Turnstile gap, persists with a reason that never mentions Cloudflare — and
any reader keying on the word then offers a Resume the gate will refuse.

`_hv_intent` is decided once, from the same input that chose the card's copy and
its buttons. This file pins that the mirror carries it, and carries the VARIABLE
rather than a literal.

⛔ These are AST assertions, not text searches, precisely because a text search
for `"hvIntent"` would pass on a comment, a docstring, or a hardcoded value —
and one of the two mutants this file exists for replaces the variable with a
literal, which a text search cannot see.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parents[1]
_TREE = ast.parse((ROOT / "research.py").read_text(encoding="utf-8"))


def _persist_dicts():
    """Every dict literal passed to `_persist_pending_decision(...)`."""
    out = []
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name != "_persist_pending_decision" or not node.args:
            continue
        if isinstance(node.args[0], ast.Dict):
            out.append(node.args[0])
    return out


def _entries(d: ast.Dict) -> dict:
    return {k.value: v for k, v in zip(d.keys, d.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _hv_mirrors():
    found = []
    for d in _persist_dicts():
        e = _entries(d)
        kind = e.get("kind")
        if (isinstance(kind, ast.Constant)
                and kind.value == "human_verification_required"):
            found.append(e)
    return found


def test_the_hv_mirror_exists_and_is_found():
    """A guard that located nothing would pass every assertion below vacuously."""
    mirrors = _hv_mirrors()
    assert len(mirrors) == 1, f"expected one HV mirror, found {len(mirrors)}"


def test_the_hv_card_carries_its_own_verdict():
    """⛔ Without this key a reader must re-derive the verdict from `reason`, and
    a latched Cloudflare wall whose reason no longer says so is offered a Resume
    the gate refuses."""
    (mirror,) = _hv_mirrors()
    assert "hvIntent" in mirror, (
        "the human_verification_required mirror does not carry hvIntent — every "
        "reader is back to guessing from the word in `reason`")


def test_the_verdict_is_the_gates_own_variable_not_a_literal():
    """⛔ Hardcoding it either way is worse than omitting it: "hv_wall" for every
    check strips the Resume from a challenge the person could solve in ten
    seconds, and "hv_solvable" offers a Resume Cloudflare will refuse."""
    (mirror,) = _hv_mirrors()
    node = mirror["hvIntent"]
    assert isinstance(node, ast.Name), (
        f"hvIntent is bound to {type(node).__name__}, not a variable — a "
        "hardcoded verdict is wrong for one of the two cases, always")
    assert node.id == "_hv_intent", node.id


def _hv_intent_assignments():
    """Every `_hv_intent = …` assignment, as AST nodes."""
    out = []
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "_hv_intent":
                out.append(node.value)
    return out


def test_the_verdict_is_decided_once_from_the_cloudflare_test():
    """And it is the same variable the card's copy and its buttons already use,
    so the mirror cannot disagree with what the person sees on screen."""
    assignments = _hv_intent_assignments()
    assert len(assignments) == 1, (
        f"_hv_intent is assigned {len(assignments)}x — two decisions can differ")
    value = assignments[0]
    assert isinstance(value, ast.IfExp), type(value).__name__
    src = ast.unparse(value.test)
    assert "cloudflare" in src.lower(), src


def test_the_two_verdicts_are_the_only_ones():
    """The bridge treats anything that is not "hv_wall" as solvable — the safe
    default, since a Resume it refuses merely does nothing while a missing Resume
    strips a solvable check of its one-tap fix. That default is only correct
    because these are the SOLE values; a third would silently take it."""
    (value,) = _hv_intent_assignments()
    verdicts = set()
    for branch in (value.body, value.orelse):
        assert isinstance(branch, ast.Constant), ast.unparse(branch)
        verdicts.add(branch.value)
    assert verdicts == {"hv_wall", "hv_solvable"}, verdicts
