"""Wave 5B — when the ChatGPT activity-panel opener gives up, it must say why.

Owner finding 9, from the live run: the opener abandons any root with more than
8000 descendants — a deliberate cost ceiling on a long thread — and did it
SILENTLY. A page too large to scan returned `{found: false, candidates: 0}`,
byte-identical to a page that was fully scanned and simply had no strip in it.
So both callers logged the same sentence, "strip not yet rendered or wording
changed", asserting two causes on evidence for neither — and that sentence was
plainly false whenever nothing had been examined at all.

Which matters more the longer a run goes: a Deep Research thread only grows, so
the cause the log never named is the one that becomes MORE likely with time,
while the two it did name become less so.

The JS is EXECUTED here. A source-text assertion cannot tell whether the walk
reached the cap, and the whole finding is that a returned value looked right.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import research
from _domshim import el, js_constant, run_js


_JS = js_constant(research._open_chatgpt_activity_panel, "JS")

# One over the production ceiling. Read from the JS rather than restated, so a
# changed ceiling moves the fixture with it instead of quietly under-filling it.
_CAP = int(_JS.split("const NODE_CAP =")[1].split(";")[0].strip())


def _bulk(n: int):
    """`n` inert nodes — enough to push a root past the ceiling."""
    return el("i", {}, "", repeat=n)


def _strip(text="Searching the web..."):
    """The activity strip: a short interactive row with the live wording."""
    return el("div", {"role": "button"}, text)


def _open(spec, skip_structural=False):
    return run_js(spec, _JS, skip_structural)["ret"]


# ── 1. The bail-out now names itself ─────────────────────────────────────────

def test_a_page_too_large_to_scan_says_so_instead_of_reporting_no_match():
    """THE finding. The strip is right there and the walker never looked."""
    spec = el("body", {}, "", [_bulk(_CAP + 50), _strip()])
    res = _open(spec)
    assert res["found"] is False
    assert res["reason"] == "node_cap"
    assert res["walked"] == 0
    assert res["maxNodes"] > _CAP
    assert res["nodeCap"] == _CAP


def test_a_page_that_was_scanned_and_had_no_strip_says_that_instead():
    """The other cause, which must stay distinguishable — it is the one that
    means "go and look at the wording"."""
    res = _open(el("body", {}, "", [el("div", {}, "Some ordinary prose")]))
    assert res["found"] is False
    assert res["reason"] == "no_match"
    assert res["walked"] > 0
    assert res["cappedRoots"] == 0


def test_a_partly_scanned_page_is_neither_of_those():
    """A dialog small enough to walk plus a host page too big to. Reporting
    this as a plain node_cap would hide that the dialog WAS examined; as a
    no_match, that most of the page was not. Both explanations are still live
    and the caller is told so."""
    spec = el("body", {}, "", [
        el("div", {"role": "dialog", "w": "420", "h": "320"}, "", [
            el("p", {}, "Plan for the research"),
        ]),
        _bulk(_CAP + 50),
    ])
    res = _open(spec)
    assert res["found"] is False
    assert res["reason"] == "node_cap_partial"
    assert res["walked"] > 0
    assert res["cappedRoots"] >= 1


def test_the_structural_pass_reports_its_own_ceiling_hit():
    """PASS 0 anchors below the last user message and has the SAME ceiling. Its
    skip was the most invisible of the three: it silently emptied its node list
    and fell through to passes that were about to be capped as well."""
    spec = el("body", {}, "", [
        el("div", {"data-message-author-role": "user"}, "the prompt"),
        el("main", {}, "", [_bulk(_CAP + 50)]),
    ])
    res = _open(spec)
    assert res["found"] is False
    assert res["structuralCapped"] is True


def test_an_empty_document_says_nothing_matched_not_nothing_looked_at():
    res = _open(el("body", {}, "", []))
    assert res["found"] is False
    assert res["reason"] in ("no_match", "no_roots")
    assert res["cappedRoots"] == 0


# ── 2. The instrumentation must not have cost the opener its job ────────────

def test_a_strip_on_a_normal_page_is_still_found_and_clicked():
    out = run_js(el("body", {}, "", [_strip()]), _JS, False)
    assert out["ret"]["found"] is True
    assert out["ret"]["clicked"] is True
    assert out["clicks"], "the strip was reported found but never dispatched a click"


def test_a_strip_is_still_found_when_the_page_is_merely_large():
    """Just under the ceiling: the walk must still happen."""
    spec = el("body", {}, "", [_bulk(_CAP - 200), _strip()])
    res = _open(spec)
    assert res["found"] is True


def test_a_capped_walk_reports_no_candidates_rather_than_a_stale_count():
    spec = el("body", {}, "", [_bulk(_CAP + 50), _strip()])
    assert _open(spec)["candidates"] == 0


# ── 3. The sentence the caller logs ─────────────────────────────────────────

@pytest.mark.parametrize("res,must_say", [
    ({"reason": "node_cap", "walked": 0, "maxNodes": 12000, "nodeCap": 8000},
     "too large to scan"),
    ({"reason": "node_cap_partial", "walked": 900, "maxNodes": 12000,
      "nodeCap": 8000, "cappedRoots": 2}, "partially scanned"),
    ({"reason": "no_match", "walked": 900, "roots": 3, "contexts": 1},
     "wording changed"),
    ({"reason": "no_roots"}, "no roots"),
])
def test_the_reason_line_names_what_was_seen(res, must_say):
    assert must_say in research._panel_miss_reason(res)


def test_the_capped_line_does_not_claim_the_strip_is_missing():
    """The old sentence asserted the strip was absent or renamed. On a capped
    walk neither was established, and saying so sent three live investigations
    at the wording."""
    line = research._panel_miss_reason(
        {"reason": "node_cap", "walked": 0, "maxNodes": 12000, "nodeCap": 8000})
    assert "wording" not in line
    assert "may well be there" in line


def test_both_miss_log_sites_report_the_reason_rather_than_asserting_one():
    """P1 and P2 each own a copy of this log line, and each carried the same
    invented explanation. Testing the sentence-builder alone would leave the
    two lines free to go back to the constant they used to print."""
    tree = ast.parse(inspect.getsource(research))
    sites = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "log" and node.args):
            continue
        arg = node.args[0]
        if not isinstance(arg, ast.JoinedStr):
            continue
        literal = "".join(v.value for v in arg.values
                          if isinstance(v, ast.Constant) and isinstance(v.value, str))
        if "panel DOM miss" not in literal:
            continue
        sites.append(arg)
        called = {n.func.id for v in arg.values if isinstance(v, ast.FormattedValue)
                  for n in ast.walk(v.value)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_panel_miss_reason" in called, (
            "a panel-miss log line states a cause instead of reporting one")
        assert "wording changed" not in literal, (
            "the invented explanation is back in the format string")
    assert len(sites) == 2, f"expected the P1 and P2 miss lines, found {len(sites)}"


def test_a_walk_that_raised_is_reported_as_a_raise():
    line = research._panel_miss_reason(
        {"reason": "no_result", "error": "TimeoutError: boom", "context": "host"})
    assert "raised" in line and "TimeoutError" in line


def test_an_absent_result_still_produces_a_line():
    """`None` reaches this from the already-open branch; a bare traceback in a
    log line is worse than the sentence it replaced."""
    assert research._panel_miss_reason(None)
    assert research._panel_miss_reason({})


# ── 4. The Python side keeps the evidence instead of flattening it ──────────

class _Frame:
    def __init__(self, res, url="https://chatgpt.com/frame"):
        self._res = res
        self.url = url

    async def evaluate(self, js, arg=None):
        if isinstance(self._res, Exception):
            raise self._res
        return self._res


class _Page:
    def __init__(self, host, frames=()):
        self._host = host
        self.main_frame = object()
        self.frames = [self.main_frame, *frames]

    async def evaluate(self, js, arg=None):
        if isinstance(self._host, Exception):
            raise self._host
        return self._host


def _drive(page):
    import asyncio
    return asyncio.run(research._open_chatgpt_activity_panel(page))


def test_the_host_diagnostic_survives_the_frame_walk():
    """It used to be discarded: the function fell through twenty frames and
    returned a hardcoded constant, so the one context that had something to say
    was the one context guaranteed to be forgotten."""
    host = {"found": False, "candidates": 0, "reason": "node_cap",
            "walked": 0, "maxNodes": 20000, "nodeCap": 8000}
    res = _drive(_Page(host, frames=[_Frame({"found": False, "reason": "no_match",
                                             "walked": 40, "roots": 1})]))
    assert res["reason"] == "node_cap"
    assert res["maxNodes"] == 20000
    assert res["context"] == "host"


def test_a_frame_that_hit_the_ceiling_outranks_a_frame_that_merely_missed():
    """Most frames on a ChatGPT page were never going to hold the strip, so
    their "nothing matched" is the default answer. A ceiling hit names a cause
    and must not be drowned by them."""
    host = {"found": False, "reason": "no_match", "walked": 10, "roots": 1}
    frames = [_Frame({"found": False, "reason": "no_match", "walked": 5, "roots": 1}),
              _Frame({"found": False, "reason": "node_cap", "walked": 0,
                      "maxNodes": 30000, "nodeCap": 8000}),
              _Frame({"found": False, "reason": "no_match", "walked": 5, "roots": 1})]
    res = _drive(_Page(host, frames=frames))
    assert res["reason"] == "node_cap"
    assert res["context"] == "frame"


def test_every_context_tried_is_counted():
    host = {"found": False, "reason": "no_match", "walked": 10, "roots": 1}
    frames = [_Frame({"found": False, "reason": "no_match", "walked": 5, "roots": 1})
              for _ in range(3)]
    assert _drive(_Page(host, frames=frames))["contexts"] == 4


def test_a_found_result_is_still_returned_untouched():
    host = {"found": True, "clicked": True, "label": "Searching...", "candidates": 3}
    assert _drive(_Page(host))["found"] is True


def test_a_frame_hit_wins_over_any_host_diagnostic():
    host = {"found": False, "reason": "node_cap", "walked": 0, "maxNodes": 20000}
    res = _drive(_Page(host, frames=[_Frame({"found": True, "clicked": True})]))
    assert res["found"] is True
    assert res["frameUrl"].startswith("https://chatgpt.com/frame")


def test_a_host_evaluate_that_raises_is_carried_out_as_the_reason():
    res = _drive(_Page(RuntimeError("Execution context was destroyed")))
    assert res["found"] is False
    assert "Execution context was destroyed" in research._panel_miss_reason(res)


def test_frames_that_raise_are_skipped_without_losing_the_host_reason():
    host = {"found": False, "reason": "node_cap", "walked": 0,
            "maxNodes": 20000, "nodeCap": 8000}
    res = _drive(_Page(host, frames=[_Frame(RuntimeError("detached")),
                                     _Frame(RuntimeError("detached"))]))
    assert res["reason"] == "node_cap"
