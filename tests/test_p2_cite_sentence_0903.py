"""#280 — the word that was missing from the phase-2 instruction was `links`.

⛔⛔ MEASURED ON THE 2026-09-03 RUN: THREE REPORTS, 258 KB, ZERO URLS. Not few —
none, in any of them, from any agent. They cited by name: "Hart et al. 2020
(Frontiers in Veterinary Science)", "Torres de la Riva et al. 2013 PLOS ONE".
Real, checkable, and unlinkable.

⛔⛔ AND THE INSTRUCTION WAS SATISFIED. It asked for "a comprehensive research
report with citations", and those ARE citations. Everything downstream then
reported honestly on a report with nothing in it to report — `sources=0` for all
three agents, the findings extractor empty, the Sources list empty. The defect
was never in the readers, which is why this is the fix that had to come first.

⛔ FOUR COPIES OF ONE SENTENCE IS FOUR CHANCES TO DRIFT. The instruction is
written in the deterministic type, in the CUA fallback's user directive, in that
call's context hint, and in the hotspot hint the shadow observer scores an
attempt against. A fallback that asks for something different from the path it
is a fallback for produces a run whose sources depend on which rung fired.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


def _typed_prompt() -> str:
    """The message actually typed into the composer, rebuilt exactly."""
    return ("Please perform deep research on the topic described in the attached brief. "
            "Use the brief as the complete context — objectives, scope, sections, "
            "sources to target. Produce a comprehensive research report. "
            + research._P2_CITE_SENTENCE)


class TestTheSentence:
    def test_it_asks_for_addresses_not_only_credit(self):
        """⛔⛔ `citations` WAS ALREADY THERE AND WAS ALREADY OBEYED. The word that
        turns a named paper into something the pipeline can carry is `links`."""
        s = research._P2_CITE_SENTENCE.lower()
        assert "links" in s
        assert "inline" in s

    def test_it_asks_for_a_list_at_the_end_as_well(self):
        """Two placements, because they fail differently: an agent that writes
        prose without inline links may still append a bibliography, and one that
        links inline may never gather them."""
        assert "at the end" in research._P2_CITE_SENTENCE.lower()

    def test_it_is_one_sentence(self):
        """⚠ The whole message must stay short enough that no platform converts it
        to an attachment. A typed prompt that becomes a second attachment leaves
        the composer empty and the run with no instruction at all — which is what
        the brief file is already for."""
        assert research._P2_CITE_SENTENCE.count(".") == 1
        assert research._P2_CITE_SENTENCE.endswith(".")


class TestTheTypedMessage:
    def test_the_prompt_the_function_builds_carries_the_sentence(self):
        assert research._P2_CITE_SENTENCE in _typed_prompt()

    def test_it_no_longer_asks_only_for_citations(self):
        """⛔⛔ THE EXACT PHRASE THE 2026-09-03 REPORTS SATISFIED. Three agents
        produced 258 KB of correctly-cited prose containing no address at all, so
        an instruction whose only demand is this phrase is one the pipeline
        cannot act on."""
        assert "report with citations" not in _typed_prompt()

    def test_it_stays_short_enough_not_to_become_an_attachment(self):
        """A bound, not a measurement of the platforms' real threshold — which is
        thousands of characters. The point is that this message is a short
        instruction and the brief is the payload; if it ever grows into prose,
        that split has stopped being true."""
        assert len(_typed_prompt()) < 600

    def test_it_holds_no_newline(self):
        """⛔⛔ IT IS TYPED WITH `page.keyboard.type`, SO A NEWLINE IS AN ENTER
        PRESS. One `\\n` anywhere in this string submits the message mid-sentence,
        on a composer whose Send is meant to be a separate deterministic step —
        and the agent would start researching a truncated instruction."""
        assert "\n" not in _typed_prompt()
        assert "\r" not in _typed_prompt()


class TestEveryRungAsksForTheSameThing:
    """⛔ THE FALLBACK MUST NOT ASK FOR SOMETHING ELSE. These fire when the
    deterministic type misses its selector, which happens on a warm or canvas
    tab — so the run that most needs a correct instruction is the one served by
    the copy nobody reads."""

    def test_the_cua_fallback_user_directive(self):
        # ⛔ THE SOURCE, NOT THE CODE CONSTANTS. The directive is built by
        # concatenating the constant onto two literals, so `co_consts` holds the
        # pieces and never the joined sentence — a first draft asserted on the
        # pieces and failed against a site that was correct.
        import inspect
        src = inspect.getsource(research.type_inline_prompt_with_cua)
        assert "+ _P2_CITE_SENTENCE" in src

    def test_the_cua_fallback_context_hint(self):
        src = " ".join(_strings(research.type_inline_prompt_with_cua.__code__.co_consts))
        assert "sources cited inline with links" in src
        # ⛔ AND THE OLD SUMMARY IS GONE. "deep research + citations" is the
        # shorthand that described the instruction the reports satisfied.
        assert "deep research + citations" not in src

    def test_the_hotspot_hint_the_observer_scores_against(self):
        hint = research._HOTSPOT_VISION_HINTS["inline-type"]["context_hint"]
        assert research._P2_CITE_SENTENCE in hint
        assert "comprehensive report with citations" not in hint


def _strings(consts) -> list:
    """Every string constant in a code object, nested code objects included."""
    out = []
    for c in consts:
        if isinstance(c, str):
            out.append(c)
        elif hasattr(c, "co_consts"):
            out.extend(_strings(c.co_consts))
    return out


def test_the_sentence_is_defined_once():
    """⛔ A fifth copy is a fifth chance for the rungs to disagree. Every site
    references the constant; none spells it out."""
    src = (Path(__file__).resolve().parents[1] / "research.py").read_text(encoding="utf-8")
    assert src.count('"Cite primary and authoritative sources inline with links, "') == 1
    # The definition plus three sites. The fourth — the CUA call's own context
    # hint — carries the demand as prose ("sources cited inline with links")
    # rather than the sentence, because it summarises the task for an observer
    # instead of being text anyone types. Its wording is pinned separately.
    assert src.count("_P2_CITE_SENTENCE") == 4


@pytest.mark.parametrize("rung", ["deterministic", "cua-user", "cua-hint", "hotspot"])
def test_no_rung_still_promises_only_citations(rung):
    """The phrase that produced 258 KB of linkless reports, gone from all four."""
    texts = {
        "deterministic": _typed_prompt(),
        "cua-user": " ".join(_strings(research.type_inline_prompt_with_cua.__code__.co_consts)),
        "cua-hint": " ".join(_strings(research.type_inline_prompt_with_cua.__code__.co_consts)),
        "hotspot": research._HOTSPOT_VISION_HINTS["inline-type"]["context_hint"],
    }
    t = texts[rung].lower()
    assert "report with citations" not in t
    assert "links" in t
