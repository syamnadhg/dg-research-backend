"""Wave 5B — P3 must not report zero audio cards while one is visibly generating.

The owner has watched this for months: NotebookLM shows "Generating Audio
Overview…" and the log says `Post-generate inventory: 0 audio card(s)`.

It is not a selector that drifted. `_count_nlm_audio_cards` counts
<artifact-library-item> elements carrying the `audio_magic_eraser` ligature, and
that item is what NotebookLM renders when generation FINISHES — while in flight
there is a placeholder in .artifact-library-container and no item at all. The
counter's own docstring nevertheless promised "in-flight + completed", so the
number was read as authoritative by three call sites and by the reader of the
log, and a healthy post-generate state fired the anomalous-zero WARN dump every
single run.

The JS here is EXECUTED against fixtures, not string-matched. The in-flight
count is the interesting case: every ancestor of a placeholder also contains the
phrase, so the naive implementation reports one generation as four.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import research
from _domshim import el, evaluate_js, run_js


GEN = "Generating Audio Overview…"
_READY_JS = evaluate_js(research._count_nlm_audio_cards)
_GEN_JS = evaluate_js(research._count_nlm_audio_generating)


def _panel(*kids, tag="artifact-library"):
    """The Studio artifact container the counters scope into."""
    return el("body", {}, "", [el(tag, {}, "", list(kids))])


def _placeholder(depth: int = 1):
    """A generating entry, wrapped in `depth` ancestors that inherit its text.

    The wrapping is the point: in the real panel the placeholder sits inside a
    card, inside a list, inside the container, and textContent propagates all
    the way up.
    """
    node = el("span", {}, GEN)
    for _ in range(depth - 1):
        node = el("div", {}, "", [node])
    return node


def _ready_card(title="The Genetic Tragedy of Golden Retrievers"):
    return el("artifact-library-item", {}, "", [
        el("mat-icon", {}, "audio_magic_eraser"),
        el("span", {}, title),
    ])


def _count_gen(spec):
    return run_js(spec, _GEN_JS)["ret"]


def _count_ready(spec):
    return run_js(spec, _READY_JS)["ret"]


# ── 1. The in-flight count ───────────────────────────────────────────────────

def test_a_generating_placeholder_is_counted():
    """The headline: one generation on screen reads as one, not zero."""
    assert _count_gen(_panel(_placeholder())) == 1


def test_an_ancestor_chain_does_not_multiply_one_generation():
    """Four nested nodes all contain the phrase. Counting every match would
    report four audio overviews in flight when there is one — a number worse
    than the zero it replaced, because the dup guard acts on it."""
    assert _count_gen(_panel(_placeholder(depth=4))) == 1


def test_two_generations_in_flight_count_as_two():
    """The duplicate #778 exists to catch, seen while it is still a placeholder
    instead of minutes later when both become items."""
    assert _count_gen(_panel(_placeholder(depth=3), _placeholder(depth=3))) == 2


def test_a_phrase_split_across_sibling_nodes_still_counts_once():
    """Angular splits label text across spans routinely. No child owns the whole
    phrase, so the parent is the deepest owner — one placeholder, not zero."""
    split = el("div", {}, "", [
        el("span", {}, "Generating Audio "),
        el("span", {}, "Overview…"),
    ])
    assert _count_gen(_panel(split)) == 1


def test_a_panel_with_nothing_generating_counts_zero():
    assert _count_gen(_panel(_ready_card())) == 0


def test_an_empty_panel_counts_zero():
    assert _count_gen(_panel()) == 0


def test_the_phrase_is_matched_case_insensitively():
    assert _count_gen(_panel(el("div", {}, "GENERATING AUDIO OVERVIEW"))) == 1


def test_the_container_naming_a_generation_no_element_owns_still_reports_one():
    """The documented floor. If the phrase is in the container but the element
    that owns it cannot be resolved, "at least one is generating" is still
    proven — and answering 0 there would put back the exact contradiction this
    helper exists to remove."""
    spec = el("body", {}, "", [el("artifact-library", {}, GEN, [])])
    assert _count_gen(spec) == 1


def test_the_count_is_scoped_to_the_artifact_container():
    """A chat message or a notification elsewhere on the page that happens to
    say "generating audio overview" is not an entry in the Studio panel."""
    spec = el("body", {}, "", [
        el("artifact-library", {}, "", [_ready_card()]),
        el("div", {"class": "chat-log"}, "", [el("span", {}, GEN)]),
    ])
    assert _count_gen(spec) == 0


def test_the_container_class_is_honoured_as_well_as_the_tag():
    spec = el("body", {}, "", [
        el("div", {"class": "artifact-library-container"}, "", [_placeholder(2)]),
    ])
    assert _count_gen(spec) == 1


def test_a_hidden_subtree_does_not_contribute_a_second_generation():
    """A hidden template copy must not double the count of a real one."""
    spec = _panel(_placeholder(depth=2),
                  el("div", {"hidden": ""}, "", [_placeholder(depth=2)]))
    assert _count_gen(spec) == 1


# ── 2. The two counters are complements, and must stay that way ─────────────

def test_the_ready_counter_still_cannot_see_a_generating_entry():
    """Pins WHY a second counter exists: today's placeholder is not an
    artifact-library-item at all, so the ready counter structurally cannot
    see it."""
    assert _count_ready(_panel(_placeholder(depth=3))) == 0


def test_a_skeleton_row_is_counted_once_by_the_pair_not_twice_by_both():
    """The fixture the previous test CANNOT reach, and the one that matters.

    Callers add the two counts. If NotebookLM ever renders a generating entry
    as an artifact-library-item bearing the audio icon — the obvious next
    redesign, a skeleton row in the list — both counters would match it and one
    audio overview would be reported as two: a false duplicate WARN produced by
    the very fix that exists to stop the count contradicting the screen. The
    counters are disjoint by construction so that cannot happen.
    """
    skeleton = el("artifact-library-item", {}, "", [
        el("mat-icon", {}, "audio_magic_eraser"),
        el("span", {}, GEN),
    ])
    spec = _panel(skeleton)
    assert _count_ready(spec) == 0
    assert _count_gen(spec) == 1
    assert _count_ready(spec) + _count_gen(spec) == 1


def test_a_finished_card_beside_a_skeleton_row_totals_two():
    """And the exclusion must not swallow the real card next to it."""
    spec = _panel(_ready_card(), el("artifact-library-item", {}, "", [
        el("mat-icon", {}, "audio_magic_eraser"),
        el("span", {}, GEN),
    ]))
    assert (_count_ready(spec), _count_gen(spec)) == (1, 1)


def test_the_ready_counter_counts_a_finished_entry():
    assert _count_ready(_panel(_ready_card())) == 1


def test_a_panel_mid_transition_is_one_of_each():
    """The real duplicate case: the first audio finished while the second is
    still generating. Ready-only reads 1 and stays quiet."""
    spec = _panel(_ready_card(), _placeholder(depth=3))
    assert (_count_ready(spec), _count_gen(spec)) == (1, 1)


# ── 3. The call sites read both numbers ─────────────────────────────────────

def _phase3_tree():
    return ast.parse(inspect.getsource(research.run_phase3_audio))


def _log_call_containing(tree, needle):
    """The single `log(f"…{needle}…")` call, as an ast node.

    Partitioned to ONE call on purpose: asserting that a name appears somewhere
    in a 900-line function is satisfied by any unrelated use of it.
    """
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "log" and node.args):
            continue
        arg = node.args[0]
        if not isinstance(arg, ast.JoinedStr):
            continue
        literal = "".join(v.value for v in arg.values
                          if isinstance(v, ast.Constant) and isinstance(v.value, str))
        if needle in literal:
            hits.append(arg)
    assert len(hits) == 1, f"{len(hits)} log calls mention {needle!r}"
    return hits[0]


def _interpolated_names(joined: ast.JoinedStr):
    return {n.id for v in joined.values if isinstance(v, ast.FormattedValue)
            for n in ast.walk(v.value) if isinstance(n, ast.Name)}


@pytest.mark.parametrize("headline,ready,generating", [
    ("Pre-flight inventory", "existing_cards", "existing_generating"),
    ("Post-generate inventory", "post_gen_cards", "post_gen_generating"),
    ("Mid-poll", "_live_ready", "_live_generating"),
])
def test_the_inventory_log_reports_both_populations(headline, ready, generating):
    """A log line naming one population and calling it "audio card(s)" is what
    made the report disagree with the screen."""
    names = _interpolated_names(_log_call_containing(_phase3_tree(), headline))
    assert ready in names, f"{headline} does not report the ready count"
    assert generating in names, f"{headline} does not report the in-flight count"


def _dump_gate(tree, ctx: str) -> ast.If:
    """The `if …:` whose OWN body dumps the DOM for `ctx`.

    "Own body", not `ast.walk`: the post-cleanup dump sits inside
    `if audio_done and audio_path:` as well, and a walk-based search reports
    that outer condition — an assertion about the wrong gate that passes or
    fails for reasons unrelated to the counter.
    """
    def is_dump(stmt):
        val = stmt.value if isinstance(stmt, ast.Expr) else None
        val = val.value if isinstance(val, ast.Await) else val
        return (isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
                and val.func.id == "_dump_nlm_audio_dom"
                and any(isinstance(a, ast.Constant) and a.value == ctx
                        for a in val.args))

    gates = [n for n in ast.walk(tree)
             if isinstance(n, ast.If) and any(is_dump(s) for s in n.body)]
    assert len(gates) == 1, f"{len(gates)} gates dump {ctx!r}"
    return gates[0]


def test_the_post_generate_anomaly_dump_requires_both_counts_to_be_zero():
    """Five seconds after Generate the healthy state is 0 ready + 1 generating.
    Gating the WARN dump on the ready count alone fired it on EVERY run, which
    is how a canary stops being read."""
    gate = _dump_gate(_phase3_tree(), "post-generate")
    names = {n.id for n in ast.walk(gate.test) if isinstance(n, ast.Name)}
    assert names == {"post_gen_cards", "post_gen_generating"}, sorted(names)
    assert isinstance(gate.test, ast.BoolOp) and isinstance(gate.test.op, ast.And)


def test_the_mid_poll_duplicate_check_sums_both_populations():
    """A duplicate spawned by a misclick is a placeholder first. Comparing only
    ready cards means the second one is invisible for as long as it takes to
    render — which on an audio overview is most of the window."""
    tree = _phase3_tree()
    sums = [n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_live_cards" for t in n.targets)]
    assert len(sums) == 1
    value = sums[0].value
    assert isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)
    assert {value.left.id, value.right.id} == {"_live_ready", "_live_generating"}


def test_the_post_cleanup_zero_is_still_treated_as_an_anomaly():
    """Deliberately NOT changed. By post-cleanup the audio is downloaded, so a
    READY card must exist — zero there is a genuine counter miss and the dump is
    the canary that re-pins the selectors."""
    gate = _dump_gate(_phase3_tree(), "post-cleanup")
    names = {n.id for n in ast.walk(gate.test) if isinstance(n, ast.Name)}
    assert names == {"total_count"}, sorted(names)
