"""The post-select confirm was reading an EMPTY trigger (live log, 2026-08-16).

    [p1:extended_pro_confirm] trig='' extended=False pro=False instant=False

`_chatgpt_extended_pro_confirm` locates the mode trigger by looking for a control
whose `data-testid` or `aria-label` contains "model". The redesigned composer
labels nothing that way — the effort pill carries neither — so the lookup found
nothing and every branch below decided from an empty string. That leaves the
function with only its marker scan, which is the weaker of its two evidence
sources and the one it is deliberately careful to treat as a hint.

⛔⛔ AND THE MARKER SCAN HAS A NEW HAZARD. The capture shows that while the picker
is OPEN the composer mounts a hidden measuring strip carrying every label it might
ever display — including the literal "Pro Extended". Those spans are twelve
characters, sit outside every overlay, and return real client rects, so they
satisfy the scan's "a thinking word AND a tier word in one short element" rule
exactly. The verdict would then be 'extended' whatever the live mode is. That is
not a missed detection, it is an INVERTED one, and masking a real downgrade is
the single thing this function exists to prevent.

ⓘ Not a live fault today — the confirm runs after the picker is dismissed, and
the strip is absent from the closed-composer capture. Pinned anyway: the cost of
the guard is one attribute read, and the failure it prevents is silent.

These tests EXECUTE the production page JS through the node DOM shim.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from models import p1_words  # noqa: E402
from _domshim import el, evaluate_js, run_js  # noqa: E402

CONFIRM_JS = evaluate_js(research._chatgpt_extended_pro_confirm, contains="trigText")

PARAMS = {k: p1_words("chatgpt", k) for k in
          ("tier_words", "thinking_words", "downgrade_words", "upgrade_verbs")}
PARAMS["avoid"] = "deep research"

# The measuring strip, verbatim in shape from the capture: one span per label the
# pill might display, mounted while the menu is open.
STRIP_LABELS = ["Instant", "Medium", "High", "Extra High", "Pro",
                "Instant", "Medium", "High", "Extra High", "Pro", "Pro Extended"]


def _run(spec):
    return run_js(spec, CONFIRM_JS, PARAMS)["ret"]


def _composer(pill_text, *, expanded="false", strip=False, extra=()):
    """The composer, with the effort pill as the redesign renders it: no
    `model` testid, no `model` aria-label, just a short chip owning a menu."""
    kids = [
        el("div", {"id": "prompt-textarea", "contenteditable": "true"}),
        el("button", {"class": "__composer-pill", "aria-haspopup": "menu",
                      "aria-expanded": expanded}, pill_text),
    ]
    kids.extend(extra)
    if strip:
        kids.extend(el("span", {}, t) for t in STRIP_LABELS)
    return el("body", {}, kids=[el("form", {}, kids=kids)])


class TestTheTriggerIsFoundAtAll:
    def test_the_redesigned_pill_is_read(self):
        # ⛔ THE REGRESSION. Before the fallback this returned '' for this markup.
        out = _run(_composer("Pro"))
        assert out["trigText"] == "Pro"
        assert out["hasPro"] is True
        assert out["hasInstant"] is False

    def test_a_low_tier_pill_reads_as_a_downgrade_candidate(self):
        out = _run(_composer("Instant"))
        assert out["trigText"] == "Instant"
        assert out["hasPro"] is False
        assert out["hasInstant"] is True

    def test_the_named_lookup_still_wins_where_it_applies(self):
        # An older layout — or a rollback — labels the control, and that is exact
        # where it exists. The fallback must not displace it.
        old = el("button", {"data-testid": "model-switcher"}, "Pro")
        spec = _composer("Instant", extra=[old])
        assert _run(spec)["trigText"] == "Pro"

    def test_the_deep_research_pill_is_not_mistaken_for_the_trigger(self):
        # ⛔ Both are short composer chips owning menus. This one must be skipped
        # by the policy tool word, never by position.
        dr = el("button", {"class": "__composer-pill", "aria-haspopup": "menu"},
                "Deep research")
        spec = _composer("Pro")
        form = spec["kids"][0]
        form["kids"].insert(0, dr)          # FIRST in document order
        assert _run(spec)["trigText"] == "Pro"

    def test_a_wrapper_that_swallows_the_composer_is_not_a_trigger(self):
        # The length cap. A container whose textContent concatenates the whole
        # composer must not pose as a chip.
        wrap = el("div", {"role": "button", "aria-haspopup": "menu"},
                  "Instant" + " lorem ipsum dolor sit amet" * 4)
        spec = _composer("Pro", extra=[wrap])
        assert _run(spec)["trigText"] == "Pro"


class TestTheMeasuringStripCannotForgeAVerdict:
    def test_with_the_picker_OPEN_the_marker_scan_stands_down(self):
        # ⭐⭐ "Pro Extended" is present and satisfies the two-word rule. The
        # guard is what stops it becoming a permanent 'extended'.
        out = _run(_composer("Instant", expanded="true", strip=True))
        assert out["hasExtended"] is False, out
        assert out["extText"] == ""

    def test_the_pills_own_text_is_still_read_while_the_picker_is_open(self):
        # The guard suppresses the MARKER scan only. Standing down entirely would
        # trade a false positive for a blind spot.
        out = _run(_composer("Instant", expanded="true", strip=True))
        assert out["trigText"] == "Instant"
        assert out["hasInstant"] is True

    def test_with_the_picker_CLOSED_a_real_marker_is_still_honoured(self):
        # The strip does not exist in this state, and a genuine "Extended Pro"
        # chip must still count — otherwise the guard has deleted the feature.
        chip = el("span", {}, "Extended Pro")
        out = _run(_composer("Pro", extra=[chip]))
        assert out["hasExtended"] is True
        assert out["extText"] == "Extended Pro"


class TestVerdicts:
    """The function's contract, end to end, through the real Python wrapper."""

    @pytest.mark.parametrize("pill,expected", [
        ("Pro", "pro"),
        ("Instant", "downgrade"),
        ("Extra High", "unsure"),
    ])
    def test_the_verdict_follows_the_pill(self, pill, expected, monkeypatch):
        import asyncio

        class _Page:
            async def evaluate(self, js, arg=None):
                return run_js(_composer(pill), js, arg)["ret"]

        assert asyncio.run(
            research._chatgpt_extended_pro_confirm(_Page())) == expected
