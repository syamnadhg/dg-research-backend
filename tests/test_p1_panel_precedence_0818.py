"""The P1 sources panel: which pass answers, and what "live" is decided by.

⛔⛔ MEASURED ON THE OWNER'S OWN CORPUS, 2026-08-18. The panel has opened via DOM
thirteen times and every one was `anchor=global clickedTag=P` on labels like
"Planning a research-based report..." — never once from a structural pick.

⭐⭐ AND THOSE THIRTEEN RODE ON ONE SIGNAL: THE TRAILING ELLIPSIS. "Planning" and
"Gathering" are in no verb list, the labels carry no count and no status word, so
of the five wording matchers only ELLIPSIS could have fired. The label text is
topic-flavoured and changes every run — what does not change is that ChatGPT
appends "…" while a step is live and drops it when the step ends. The wording
anchor has been detecting the shimmer by its punctuation the whole time.

⛔⛔ AND THE ACTUAL SHIMMER CHECK COULD NOT TELL LIVE FROM DEAD. Two of its three
arms were `background-clip: text` — a static PAINT property equally true of a
gradient that has stopped — and the third accepted a paused animation because a
paused animation still has a name. The vision tier called the chosen row "gray,
not shimmering" in the same minute the detector called it a shimmer.

These tests pin the three properties that follow: the pass with a success record
answers first, "live" means an animation is RUNNING, and the static gradient may
narrow the field but may never decide alone.
"""
import re

from conftest import code_only_deep

import research


def _panel_js() -> str:
    """The page script that picks and clicks the activity strip.

    ⛔ Anchored on CODE. `code_only_deep` blanks the `//` comments inside these
    JS strings — which is the point of it — so a landmark like "PASS 0" is
    whitespace by the time a test sees it."""
    src = code_only_deep(research)
    i = src.index("const structural = [];")
    return src[i:i + 20000]


# ── the pass that works answers first ────────────────────────────────────────

def test_the_structural_pass_defers_instead_of_clicking():
    """⛔ It used to `return clickAndReturn(...)` the moment anything qualified,
    so the global walk was unreachable whenever it found something — which,
    after the qualifying gate became reachable, was every run."""
    js = _panel_js()
    head = js[:js.index("const dialogs = document.querySelectorAll(")]
    assert "deferredStructural = ranked[0]" in head
    assert "return clickAndReturn" not in head, (
        "the structural pass clicks and returns again, so the pass with 13 "
        "recorded successes never runs")


def test_the_global_walk_is_consulted_before_the_structural_pick():
    js = _panel_js()
    assert js.index("walk(document)") < js.index("'+lastresort'")


def test_the_structural_pick_survives_as_a_last_resort():
    """Not deleted — pressing something beats pressing nothing once every pass
    with a success record has declined."""
    js = _panel_js()
    window = js[js.index("walk(document)"):js.index("'+lastresort'")]
    assert "!hits.length && deferredStructural" in window
    assert "clickAndReturn(deferredStructural.el" in window


def test_a_last_resort_press_says_it_was_one():
    assert "'+lastresort'" in _panel_js()


# ── what "live" is decided by ────────────────────────────────────────────────

def _shimmer_bodies() -> list[str]:
    """⛔ Both copies. Asserting against the whole file let a mutant strip the
    check out of the PICKER and still pass, because the snapshot's copy kept the
    string alive — the survivor that found this."""
    src = code_only_deep(research)
    bodies = re.findall(r"const shimmers = \(n\) => \{.*?\n *\};", src, re.S)
    assert len(bodies) == 2, f"expected the picker and the snapshot, got {len(bodies)}"
    return bodies


def test_a_running_animation_is_what_shimmering_means():
    for body in _shimmer_bodies():
        assert "animationPlayState !== 'paused'" in body, (
            "a paused animation still has a name, so this copy accepts a "
            "stopped row as live")


def test_the_static_gradient_clip_is_not_evidence_of_life():
    """⛔ The whole defect: `background-clip: text` sat inside `shimmers()`,
    so a completed step that kept its gradient class read as shimmering."""
    for body in _shimmer_bodies():
        assert "backgroundClip" not in body and "webkitBackgroundClip" not in body, (
            "the static paint property is back inside the liveness check")
    assert code_only_deep(research).count("const clipped = (n) =>") == 2, (
        "the picker and the miss snapshot must split it the same way, or they "
        "disagree about the same row")


def test_the_clip_tier_cannot_outrank_a_running_shimmer():
    js = _panel_js()
    assert "(anim ? 3 : 0)" in js
    assert "(clip ? 1 : 0)" in js


def test_the_clip_tier_only_runs_when_nothing_strict_qualifies():
    """It exists to preserve reach, not to compete: before the split this arm
    lived inside `anim`, so dropping it outright would have narrowed the pass."""
    js = _panel_js()
    i = js.index("qualifiesWeak")
    window = js[i:i + 400]
    assert "if (!ranked.length)" in window
    assert "structural.filter(qualifiesWeak)" in window


def test_a_press_carried_by_a_dead_gradient_is_labelled():
    js = _panel_js()
    assert "'+staticonly'" in js and "'+clip'" in js


def test_the_qualifying_predicate_is_still_a_predicate():
    """⛔ The scoring bug stays fixed — the threshold equalled one signal while
    the distance penalty was always subtracted, so a one-signal candidate could
    never qualify. Reverting to a sum restores THAT bug."""
    js = _panel_js()
    assert "const qualifies = (h) => h.named" in js
    assert "h.anim && h.inTurn" in js
    assert re.search(r"score\s*>=\s*3", js) is None


def test_the_prefilter_still_admits_everything_it_used_to():
    """`clip` was folded into `anim` before the split. If the prefilter forgot
    it, rows that used to reach the ranking would vanish silently."""
    assert "if (!inter && !anim && !clip && !named) continue;" in _panel_js()


# ── the miss snapshot can explain a miss ─────────────────────────────────────

def test_the_miss_snapshot_records_what_the_picker_decides_on():
    """⛔⛔ It captured anim, animKid, testid, aria, class and y — but not
    containment, interactivity, naming, or the gradient. Given a row the picker
    had chosen, the log could not say which signal carried it."""
    src = code_only_deep(research)
    i = src.index("const row = { t: key, tag: el.tagName,")
    row = src[i:i + 1400]
    for field in ("clip", "inter", "inTurn", "named"):
        assert re.search(rf"\b{field}\b", row), (
            f"the miss snapshot still does not carry {field!r}, so the next miss "
            f"cannot be diagnosed either")


def test_the_snapshot_dedupe_does_not_drop_a_gradient_the_inner_copy_saw():
    src = code_only_deep(research)
    assert "prev.clip = prev.clip || clip;" in src
