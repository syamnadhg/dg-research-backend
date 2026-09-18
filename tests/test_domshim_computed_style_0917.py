"""The shim's computed style — 2026-09-17, wave 10 lane 1.

⛔⛔ WHAT WAS WRONG, AND WHY IT LOOKED FINE. `tests/_domshim.py` honours a
fixture's `hidden` attribute in two places — `getClientRects()` returns no rects
and `offsetParent` returns null, both propagating down the subtree. So "the shim
cannot express a hidden control" was never true, and the wave plan said it was.

The real gap is narrower and worse: `getComputedStyle` returned CONSTANT
`display:block`, `visibility:visible`, `opacity:1`, and the 2026-09-10 Gemini
re-draft path reads `getBoundingClientRect` + `getComputedStyle` and NOTHING
else. `hidden` therefore never reached the code this shim exists to execute —
only the SIZE half of that gate could be driven negative by a fixture, so the
09-10 wave's own visibility check had never run once. A gate that cannot be
driven negative is not a tested gate; it is a comment.

⛔ THE FIX ADDS KEYS, IT DOES NOT REPURPOSE OLD ONES. `disp`, `vis` and `op`
are new; `hidden`, `anim` and `clip` behave exactly as they did. Fixtures across
this suite already use `hidden` for the rects/offsetParent idiom and two live
mutants read `animationName`/`backgroundClip`, so a change that gave any of
those a second meaning would silently alter what every existing fixture tells
production JS. Those three properties are pinned below on purpose.

⛔ NO `skipif(NODE is None)` IN THIS FILE. Hundreds of test functions in this
suite skip silently when node is absent, so a machine without node reports green
having executed none of the page JS. Every measurement here runs under node, and
if node is missing these tests FAIL rather than disappear —
`test_node_is_required_not_skipped_0917.py` is where that requirement is stated
once, for the whole suite; this file simply declines to opt out of it.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _domshim import el, run_js, spec_from_html  # noqa: E402


# Every node carries an id so the probe can report on it by name, and default
# geometry (100x24 at 10,10) so the SIZE gate is satisfied throughout — the
# whole point is to drive the style gate with the size gate held open.
FIXTURE = """
<div id="plain">plain</div>
<div id="gone" disp="none">display none</div>
<div id="invis" vis="hidden">visibility hidden</div>
<div id="faded" op="0.05">below the opacity floor</div>
<div id="shimmer" anim="pulse" clip="text">an animated, clipped line</div>
<div id="hid" hidden>
  <div id="hidkid">inside a hidden subtree</div>
</div>
<div id="vishost" vis="hidden">
  <div id="visinherit">inherits hidden</div>
  <div id="visoverride" vis="visible">overrides back to visible</div>
</div>
<div id="disphost" disp="none">
  <div id="dispkid">display does not inherit</div>
</div>
<div id="fadedhost" op="0">
  <div id="fadedkid">opacity does not inherit</div>
</div>
"""

# Reads BOTH views of every element in one pass: the computed style, and the two
# idioms `hidden` drives. Reading them together is what makes "the new keys did
# not disturb the old ones" a fact rather than two separate hopes.
_STYLE_PROBE = """
() => {
  const out = {};
  for (const e of document.body.querySelectorAll('[id]')) {
    const cs = getComputedStyle(e);
    out[e.getAttribute('id')] = {
      display: cs.display,
      visibility: cs.visibility,
      opacity: cs.opacity,
      animationName: cs.animationName,
      backgroundClip: cs.backgroundClip,
      rects: e.getClientRects().length,
      hasOffsetParent: !!e.offsetParent,
    };
  }
  return out;
}
"""


def _styles() -> dict:
    return run_js(spec_from_html("<body>" + FIXTURE + "</body>"), _STYLE_PROBE)["ret"]


def _triple(s: dict) -> tuple:
    return (s["display"], s["visibility"], s["opacity"])


def test_the_three_properties_still_default_to_what_every_existing_fixture_expects():
    """⛔ THE HAZARD GUARD. Hundreds of fixtures in this suite say nothing about
    style and rely on these exact three values. Attribute-driving them is only
    safe while the un-attributed default is unchanged."""
    assert _triple(_styles()["plain"]) == ("block", "visible", "1")


def test_disp_drives_display_and_touches_nothing_else():
    assert _triple(_styles()["gone"]) == ("none", "visible", "1")


def test_vis_drives_visibility_and_touches_nothing_else():
    assert _triple(_styles()["invis"]) == ("block", "hidden", "1")


def test_op_drives_opacity_and_touches_nothing_else():
    assert _triple(_styles()["faded"]) == ("block", "visible", "0.05")


def test_hidden_still_means_what_it_meant_and_does_not_leak_into_computed_style():
    """⛔⛔ THE DESTRUCTIVE VERSION OF THIS CHANGE, PINNED SO IT CANNOT LAND.
    Making `hidden` also report `display:none` is the obvious shortcut and it
    would rewrite the meaning of every existing fixture that hides a subtree —
    the menu rows, the model rankers, the panel walkers — all of which use
    `hidden` for the rects/offsetParent idiom alone. A fixture must ask for a
    computed-style hide by name."""
    st = _styles()
    assert _triple(st["hid"]) == ("block", "visible", "1")
    assert _triple(st["hidkid"]) == ("block", "visible", "1")
    # ...while the two idioms it DOES drive are untouched, subtree included.
    assert (st["hid"]["rects"], st["hid"]["hasOffsetParent"]) == (0, False)
    assert (st["hidkid"]["rects"], st["hidkid"]["hasOffsetParent"]) == (0, False)
    # And a node with no `hidden` ancestor still reports both positively, so the
    # two assertions above cannot be satisfied by a shim that hides everything.
    assert (st["plain"]["rects"], st["plain"]["hasOffsetParent"]) == (1, True)


def test_the_animation_and_clip_keys_are_exactly_as_they_were():
    """⛔ Two live mutants read `animationName` and `backgroundClip` through this
    object (`gemini_stop_split_0819` H1-H3, `p1_inline_chips_0819`). If adding
    three keys moved either of those, those harnesses would start reporting
    kills for a reason that has nothing to do with what they mutate."""
    st = _styles()
    assert (st["shimmer"]["animationName"], st["shimmer"]["backgroundClip"]) == ("pulse", "text")
    assert (st["plain"]["animationName"], st["plain"]["backgroundClip"]) == ("none", "")


def test_visibility_inherits_the_way_a_browser_inherits_it():
    """A row inside a `visibility:hidden` container is hidden in a browser, and a
    descendant can set itself visible again. Both halves matter: without the
    first a fixture cannot hide a menu the way Gemini hides one, and without the
    second `vis` would be a one-way trapdoor no real page has."""
    st = _styles()
    assert st["vishost"]["visibility"] == "hidden"
    assert st["visinherit"]["visibility"] == "hidden"
    assert st["visoverride"]["visibility"] == "visible"


def test_display_and_opacity_do_not_inherit_the_way_a_browser_does_not():
    """⛔ THE OPPOSITE ERROR, AND IT IS THE ONE THAT WOULD FLATTER A TEST.
    `getComputedStyle` on a child of a `display:none` parent reports the CHILD's
    own display in a browser, and opacity composites rather than inheriting. A
    shim that propagated either would let a fixture prove a gate the live page
    never reaches — the same class of false pass the constants above created."""
    st = _styles()
    assert st["dispkid"]["display"] == "block"
    assert st["fadedkid"]["opacity"] == "1"
    # The hosts themselves still carry their own values, so the two assertions
    # above cannot pass because the attributes were ignored entirely.
    assert st["disphost"]["display"] == "none"
    assert st["fadedhost"]["opacity"] == "0"


def test_the_shim_calls_the_function_under_test_exactly_once_per_process():
    """⛔ CHECKED, NOT ASSUMED — the wave notes rest on it. `__run` builds the
    document, calls `fn` once and returns; nothing loops. So a property about
    REPEATED calls ("clicks once and stops", "gives up at the deadline") cannot
    be measured through `run_js` at all and needs a fake page object instead.
    Pinned here so the limit is a fact in the suite, not a memory.

    ⛔⛔ THE COUNT IS READ OUT OF BAND, NOT OFF THE RETURN VALUE. The first cut
    incremented a global and asserted the RETURN was 1 — which cannot tell
    "called once" from "called three times, first result returned", the very
    shape it is quoted for elsewhere in the wave. `CLICKS` is a shim-side array
    that every `.click()` appends to and `__run` reads AFTER `fn` has returned,
    so its length is the number of calls however the return value is chosen."""
    out = run_js(el("div", kids=[el("button", {"aria-label": "probe"})]),
                 "() => { document.querySelector('button').click(); "
                 "globalThis.__n = (globalThis.__n || 0) + 1; return globalThis.__n; }")
    assert out["clicks"] == ["probe"], (
        f"the shim called the function under test {len(out['clicks'])} times, "
        "so nothing here may claim a per-call property")
    assert out["ret"] == 1
