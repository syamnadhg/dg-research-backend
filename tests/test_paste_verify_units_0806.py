"""The 2026-08-06 paste verifier: both sides of the ratio must be in the same units.

`_VERIFY_PASTE_JS` strips `[\\u200b\\ufeff\\s]` from the composer before it measures —
added 2026-08-05 so an empty ProseMirror (`<p><br></p>`, innerText "\\n") stops reading
as a one-character paste. `_verify_paste_landed` then divided that stripped reading by
`len(brief_text)`, the RAW brief. A markdown brief is ~16% whitespace, so a COMPLETE
paste could not reach the 0.90 gate:

    [2C] Paste verify (clipboard):          53968/63954 chars (84%)
    [2C] Paste verify (chunked-clipboard):  53968/63954 chars (84%)
    [2C] Paste verify (keyboard):           53968/63954 chars (84%)

The same number on three independent transports is the signature of a measurement
fault. The run then handed off to the CUA, which pasted a SECOND copy on top —
`107936/63954 chars (169%)`, exactly twice 53968 — and `ratio >= 0.90` waved it
through, so Gemini read the brief twice.

⭐ These tests EXECUTE the real page JS through the node DOM shim and compare its
answer to `paste_compare_len`. Restating the character class in Python would pass
against two classes that had silently diverged, which is the bug itself in miniature.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402


# A brief shaped like the real one: headed sections, blank lines between them, a
# table, an indented list. Its whitespace fraction is what made the live ratio 84%.
BRIEF = "\n\n".join(
    [
        "# Research Brief: NemoClaw vs NemoHermes vs Nemotron",
        "## Section {i}\n\nThis paragraph carries the substance of section {i} and "
        "runs on for a while so the section is not dominated by its own markup.\n\n"
        "| Field | Value |\n| --- | --- |\n| Scope | agent security |\n\n"
        "  - a bullet that is indented\n  - and a second one\n",
    ]
    + ["## Section %d\n\nBody text for section %d.\n\n  - point A\n  - point B\n" % (i, i)
       for i in range(1, 40)]
)


def _composer(text, copies=1):
    """A visible Gemini-shaped composer holding `copies` of `text`."""
    return el("body", kids=[
        el("rich-textarea", kids=[
            el("div", {"contenteditable": "true", "w": "600", "h": "120"},
               text * copies),
        ]),
    ])


def _js_reading(text, copies=1):
    """What `_VERIFY_PASTE_JS` actually returns for that composer."""
    return run_js(_composer(text, copies), research._VERIFY_PASTE_JS)["ret"]


class _Page:
    """A page whose `evaluate` answers the verifier's probes from the shim."""

    def __init__(self, reading, attach=0, chips=0):
        self.reading = reading
        self.attach = attach
        self.chips = chips

    async def evaluate(self, js, arg=None):
        if js is research._VERIFY_PASTE_JS:
            return self.reading
        if js is research._CLAUDE_ATTACH_COUNT_JS:
            return self.attach
        if js is research._CHATGPT_PASTED_CHIP_JS:
            return self.chips
        return 0


def _verify(reading, brief=BRIEF, platform="gemini", **kw):
    return asyncio.run(
        research._verify_paste_landed(_Page(reading, **kw), brief, platform, "2C")
    )


class TestTheTwoNormalizationsAgree:
    """The Python side must strip exactly what the JavaScript side strips."""

    def test_a_complete_paste_measures_the_same_on_both_sides(self):
        # The one assertion that would have caught this: run the real JS over a
        # composer holding the real brief, and compare with the real helper.
        assert _js_reading(BRIEF) == research.paste_compare_len(BRIEF)

    def test_every_member_of_the_js_class_is_stripped_by_the_python_one(self):
        # Each character of JavaScript's `\s` plus the two zero-width members the
        # JS names explicitly. Executed through the shim, not asserted from a list
        # copied out of the source.
        members = (
            "\u200b\ufeff\t\n\r\f\v\u0020\u00a0\u1680"
            "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
            "\u2028\u2029\u202f\u205f\u3000"
        )
        for ch in members:
            probe = "a" + ch + "b"
            assert _js_reading(probe) == 2, f"JS kept {ch!r}"
            assert research.paste_compare_len(probe) == 2, f"Python kept {ch!r}"

    def test_python_does_not_strip_what_the_js_keeps(self):
        # Python's own `\s` shorthand also matches \x1c-\x1f and \x85; the JS does
        # not. Using the shorthand would have made the brief SHORTER than the
        # reading — the same class of mismatch, in the other direction.
        for ch in "\x1c\x1d\x1e\x1f\x85":
            probe = "a" + ch + "b"
            assert _js_reading(probe) == 3, f"JS stripped {ch!r}"
            assert research.paste_compare_len(probe) == 3, f"Python stripped {ch!r}"

    def test_none_and_empty_are_zero(self):
        assert research.paste_compare_len("") == 0
        assert research.paste_compare_len(None) == 0


class TestTheFixtureReallyReproducesTheBug:
    """A regression test that passes for the wrong reason is worth nothing."""

    def test_the_brief_is_whitespace_heavy_enough_to_have_failed(self):
        raw = len(BRIEF)
        stripped = research.paste_compare_len(BRIEF)
        # The live run measured 53968/63954 = 84%. Anything at or above the 0.90
        # gate means the fixture cannot exercise the defect.
        assert stripped / raw < 0.90, (
            f"fixture is only {1 - stripped / raw:.1%} whitespace — it would have "
            f"passed the old comparison, so it cannot pin the fix"
        )


class TestACompletePasteIsAccepted:

    def test_the_full_brief_now_verifies(self):
        assert _verify(_js_reading(BRIEF)) is True

    def test_a_genuinely_short_paste_is_still_rejected(self):
        # Half the brief must still fail — the fix must not have simply widened
        # the gate until everything passes.
        half = BRIEF[: len(BRIEF) // 2]
        assert _verify(_js_reading(half)) is False

    def test_an_empty_composer_is_still_rejected(self):
        assert _verify(0) is False

    def test_a_whitespace_only_brief_does_not_divide_by_zero(self):
        # `expected` is now a stripped length, so a brief of pure whitespace makes
        # it 0 where `len()` would have been positive. The guard must survive it.
        assert _verify(0, brief="\n\n   \n") is False


class TestADuplicatePasteIsCalledOut:

    def test_two_copies_warn_that_the_agent_may_read_it_twice(self, monkeypatch):
        lines = []
        monkeypatch.setattr(research, "log",
                            lambda m, lvl="INFO", *a, **k: lines.append((lvl, m)))
        assert _verify(_js_reading(BRIEF, copies=2)) is True
        warned = [m for lvl, m in lines if lvl == "WARN" and "MORE THAN ONE" in m]
        assert warned, f"no duplicate warning in {lines!r}"

    def test_one_copy_is_not_called_a_duplicate(self, monkeypatch):
        lines = []
        monkeypatch.setattr(research, "log",
                            lambda m, lvl="INFO", *a, **k: lines.append((lvl, m)))
        assert _verify(_js_reading(BRIEF)) is True
        assert not [m for lvl, m in lines if "MORE THAN ONE" in m]

    def test_a_composer_carrying_its_own_chrome_is_not_a_duplicate(self, monkeypatch):
        # The threshold has to leave room for the platform's own composer text —
        # a brief plus a DR pill is one paste, not two.
        lines = []
        monkeypatch.setattr(research, "log",
                            lambda m, lvl="INFO", *a, **k: lines.append((lvl, m)))
        reading = int(research.paste_compare_len(BRIEF) * 1.2)
        assert _verify(reading) is True
        assert not [m for lvl, m in lines if "MORE THAN ONE" in m]


class TestTheAutoConvertPathsStillWork:
    """Claude and ChatGPT turn a large paste into an attachment; that is success."""

    def test_claude_single_attachment_tile_still_passes(self):
        assert _verify(0, platform="claude", attach=1) is True

    def test_chatgpt_pasted_text_chip_still_passes(self):
        assert _verify(0, platform="chatgpt", chips=1) is True


@pytest.mark.parametrize("source", ["clipboard", "chunked-clipboard", "keyboard"])
def test_every_transport_the_live_run_tried_now_passes(source):
    """All three logged the identical 84%. All three must now pass on the same input."""
    page = _Page(_js_reading(BRIEF))
    assert asyncio.run(
        research._verify_paste_landed(page, BRIEF, "gemini", "2C", source=source)
    ) is True
