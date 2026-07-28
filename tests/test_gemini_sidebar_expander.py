"""The Recent expander must expand RECENT — not the Notebooks section above it.

Root cause of the dropped-send recovery failing twice (2026-07-20 + 2026-07-27):
`data-test-id="expandable-section-toggle"` is not unique. Gemini's rail renders
Notebooks above Recent and BOTH carry that test-id, and `querySelector` with a
selector LIST returns the first match in DOCUMENT ORDER — it does not prefer the
earlier selector. So the old single-`q()` grabbed the Notebooks toggle every time,
read its aria-expanded, clicked it, and left Recent collapsed with its conversation
anchors out of the DOM. The sidebar read empty through the whole refresh budget and
recovery re-submitted the brief into a blank home instead of adopting the chat the
dropped send had already created.

Source-text assertions cannot catch a selector-semantics bug, so these tests RUN the
real `_EXPAND_SIDEBAR_JS` against the rail markup recorded in the failing rail-diag.
This is the test that would have caught it.
"""

from __future__ import annotations

import importlib

import pytest

from _domshim import NODE, el, js_constant, run_js

research = importlib.import_module("research")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not available to run the page JS")

TOGGLE = "expandable-section-toggle"


def _expand_js() -> str:
    return js_constant(research._gemini_adopt_lost_conversation,
                       "_EXPAND_SIDEBAR_JS").strip()


def _rail(*, recent_expanded="false", recent_label="Toggle Recent",
          notebooks_expanded="false", with_convos=False, include_recent=True):
    """The rail exactly as the failing rail-diag recorded it: sidebar already OPEN
    (so the opener branch is a no-op), Notebooks BEFORE Recent, same test-id on both.

    `recent_label=None` models label drift — an unlabelled toggle findable only
    through its enclosing section's own text.
    """
    kids = [
        el("button", {"aria-label": "Close sidebar"}),
        el("expandable-section", {"data-test-id": "notebooks-expandable-section"}, "", [
            el("button", {"data-test-id": TOGGLE, "aria-label": "Toggle Notebooks",
                          "aria-expanded": notebooks_expanded}, "Notebooks"),
            el("div", {"data-test-id": "expandable-section-content"}, "New notebook"),
        ]),
    ]
    if include_recent:
        recent_kids = [
            el("button", {"data-test-id": TOGGLE, "aria-label": recent_label,
                          "aria-expanded": recent_expanded}, "Recent"),
        ]
        if with_convos:
            recent_kids.append(el("conversations-list", {}, "", [
                el("a", {"href": "/app/abc", "aria-label": "# Deep Research Brief"}, "x")]))
        kids.append(el("expandable-section",
                       {"data-test-id": "recent-expandable-section"}, "", recent_kids))
    return el("body", {}, "", kids)


def _run(spec) -> dict:
    got = run_js(spec, _expand_js())
    return {"acted": got["ret"], "clicks": got["clicks"]}


def test_expands_recent_and_never_touches_notebooks():
    """The regression itself. Pre-fix this clicked 'Toggle Notebooks'."""
    got = _run(_rail())
    assert "Toggle Recent" in got["clicks"], \
        f"Recent was never expanded — clicked {got['clicks']!r}"
    assert "Toggle Notebooks" not in got["clicks"], \
        "clicked the Notebooks toggle — the exact 2026-07-20/27 failure"


def test_leaves_an_already_expanded_recent_alone():
    # Clicking an open section would COLLAPSE it and hide the anchors we need.
    got = _run(_rail(recent_expanded="true"))
    assert "Toggle Recent" not in got["clicks"], "collapsed an already-open Recent"


def test_does_not_expand_when_conversations_are_already_present():
    # aria-expanded absent + anchors already in the DOM → nothing to do. This gate is
    # scoped to `conversations-list a[href*="/app/"]` on purpose.
    got = _run(_rail(recent_expanded=None, with_convos=True))
    assert "Toggle Recent" not in got["clicks"]


def test_expands_when_aria_expanded_is_absent_and_there_are_no_anchors():
    got = _run(_rail(recent_expanded=None))
    assert "Toggle Recent" in got["clicks"]


def test_falls_back_to_the_recent_section_when_the_toggle_is_unlabelled():
    """Label drift: found via the enclosing section's text, still never Notebooks."""
    got = _run(_rail(recent_label=None))
    assert got["acted"] is True, "no toggle found at all"
    assert "Toggle Notebooks" not in got["clicks"]


def test_a_notebooks_only_rail_clicks_nothing():
    """No Recent section at all → must not fall back onto Notebooks."""
    got = _run(_rail(include_recent=False))
    assert "Toggle Notebooks" not in got["clicks"], got["clicks"]


def test_the_old_single_queryselector_would_have_failed_this():
    """Guards the *reason* the fix works, not just the outcome: prove the rail really
    does put a Notebooks toggle first in document order, so a plain querySelector on
    the shared test-id resolves to Notebooks. Without this, a future refactor could
    reintroduce the bare lookup and these tests would be the only warning."""
    bare = ('() => { const el = document.querySelector(\'[data-test-id="' + TOGGLE
            + '"], button[aria-label="Toggle Recent" i]\');'
            " return el && el.getAttribute('aria-label'); }")
    assert run_js(_rail(), bare)["ret"] == "Toggle Notebooks"


# ── Against the LIVE captured rail (2026-07-28, gemini.google.com @728px) ──────
# The capture settled the root cause: two toggles, "Toggle Notebooks" at index 0 and
# "Toggle Recent" at index 1, so a bare querySelector on the shared test-id really
# does resolve to Notebooks. Sections are `notebooks-expandable-section` and
# `chats-expandable-section`, and the Recent section's textContent is the header PLUS
# the chat titles ("RecentOne UI Bug Research Research (Eren)").

def _captured_rail(*, chat_title="One UI Bug Research Research (Eren)",
                   recent_expanded="false", unlabelled=False):
    return el("body", {}, "", [
        el("button", {"aria-label": "Close sidebar"}),
        el("expandable-section", {"data-test-id": "notebooks-expandable-section"}, "", [
            el("button", {"data-test-id": TOGGLE, "aria-label": None if unlabelled else "Toggle Notebooks",
                          "aria-expanded": "true"}, "Notebooks"),
            el("div", {}, "New notebook"),
        ]),
        el("expandable-section", {"data-test-id": "chats-expandable-section"}, "", [
            el("button", {"data-test-id": TOGGLE, "aria-label": None if unlabelled else "Toggle Recent",
                          "aria-expanded": recent_expanded}, "Recent"),
            el("conversations-list", {}, "", [
                el("a", {"href": "/app/a9145b6679baece3", "aria-label": chat_title}, chat_title)]),
        ]),
    ])


def test_captured_rail_expands_recent():
    got = _run(_captured_rail())
    assert "Toggle Recent" in got["clicks"]
    assert "Toggle Notebooks" not in got["clicks"]


def test_captured_rail_leaves_an_open_recent_alone():
    got = _run(_captured_rail(recent_expanded="true"))
    assert got["clicks"] == []


def test_a_chat_titled_notebook_does_not_break_the_section_fallback():
    """The Recent section's textContent includes chat TITLES, so an earlier fallback
    that rejected any section whose text matched /notebook/ would have refused the real
    Recent section whenever a conversation happened to be titled "Notebook…" — and
    then given up entirely. Keyed on data-test-id now."""
    got = _run(_captured_rail(chat_title="Notebook research on One UI", unlabelled=True))
    assert got["acted"] is True, "the section fallback found nothing"
    assert "Toggle Notebooks" not in got["clicks"]
    assert "Recent" in " ".join(got["clicks"]), got["clicks"]


def test_captured_rail_confirms_notebooks_is_first_in_document_order():
    """The root cause itself, against the real markup."""
    bare = ('() => { const el = document.querySelector(\'[data-test-id="' + TOGGLE
            + '"]\'); return el && el.getAttribute("aria-label"); }')
    assert run_js(_captured_rail(), bare)["ret"] == "Toggle Notebooks"
