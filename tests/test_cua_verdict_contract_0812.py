"""Asking a model to reason, then recovering its answer by sniffing the reasoning.

THE PATTERN, across three incidents in this file's history

Every completion decision vision makes was read back out of FREE PROSE by
`_classify_completion_verdict`, which matches around thirty substrings. That
parser is the most-patched thing in research.py, and every patch has the same
shape — a phrase that meant the opposite of what the match assumed:

  * #753 — "response complete" ECHOED back from the instruction, and once
    negated outright ("I would NOT say response complete"), read as done.
  * 2026-08-05 — "progress bar" inside a sentence enumerating it in order to
    DENY it: "No spinning ring, pulsing dot, or progress bar is visible." Read
    as generation. It cost a whole production run: a dead leg ran 36 more
    minutes and was harvested into the report.
  * The hedge list, still standing: a CAREFUL AND CORRECT answer — "the canvas
    is complete, though I can't tell whether more sources load below" — hits
    "can't tell" and reads as still generating.

The common cause is not the individual keywords, and adding more of them has
never held. It is that prose is where a model THINKS. It is not an answer
channel, and treating it as one means every hedge, every echo and every
enumeration is a chance to read the opposite of what was meant.

⭐ WHY THIS MATTERS MORE THAN IT LOOKS. Self-heal is OFF (shadow at most), so
when a ChatGPT selector rots the ladder is DOM → vision, and vision is the only
thing that recovers the run. This is the reliability of the last resort.

THE FIX — the model reasons freely, then states its conclusion on its own lines:

    VERDICT: complete | generating | unknown
    STOP_BUTTON: yes | no | unsure
    EVIDENCE: <one short line naming what it saw>

Those lines are what gets read. The prose parser stays as the FALLBACK, because
a model that ignores the format must still be understood and because every
historical answer in this repo's corpus has to keep resolving the way it does
today — that corpus IS the incident record.

WHAT THESE TESTS PIN

  1. A clean verdict beats a hedge in the same answer. (The headline.)
  2. An instruction echoed mid-sentence is not a conclusion.
  3. The LAST verdict wins — a deliberation is not a decision.
  4. ⛔ A reported Stop button overrides "complete". The cost asymmetry is
     unchanged and an inconsistent answer resolves the cheap way.
  5. Without the lines, every historical read resolves exactly as before.
  6. Both twins use the one reader, and neither parses anything itself.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402

_report = research._cua_completion_report
_prose = research._classify_completion_verdict


def _contract(verdict, stop="no", evidence="a completed canvas card", lead=""):
    return (f"{lead}\nVERDICT: {verdict}\nSTOP_BUTTON: {stop}\nEVIDENCE: {evidence}")


# ══════════════════════════════════════════════════════════════════════════
# 1. the headline: a conclusion is not overruled by the thinking around it
# ══════════════════════════════════════════════════════════════════════════

HEDGED = ("The report is fully rendered with a citations list, and the composer "
          "is idle. I can't tell whether more sources load below the fold.")


def test_a_hedge_in_the_reasoning_no_longer_vetoes_a_clean_verdict():
    """⭐ THE ONE THAT MATTERS. This answer is correct, careful, and honest about
    what it could not see — and under prose-only reading it was a veto."""
    assert _prose(HEDGED) == "generating", "the incident precondition changed"
    assert _report(_contract("complete", lead=HEDGED))["verdict"] == "complete"


def test_the_2026_08_05_enumeration_no_longer_reads_as_generation():
    """The answer that cost a production run: three explicit NOs, and the parser
    matched the nouns being denied."""
    denial = ("Stop button? No — the composer shows a Send arrow. Loading "
              "animation or spinner? No spinning ring, pulsing dot, or progress "
              "bar is visible.")
    out = _report(_contract("complete", lead=denial))
    assert out["verdict"] == "complete"
    assert out["stop_seen"] is False


def test_an_honest_unknown_is_carried_through_as_ambiguous():
    """"unknown" is the contract's word for what this codebase calls
    "ambiguous" — the absence of a reading, not a reading."""
    assert _report(_contract("unknown", stop="unsure"))["verdict"] == "ambiguous"


@pytest.mark.parametrize("verdict,expected", [
    ("complete", "complete"),
    ("generating", "generating"),
    ("unknown", "ambiguous"),
])
def test_every_contract_verdict_maps_onto_the_existing_vocabulary(verdict, expected):
    """Callers are unchanged — the contract is a better CHANNEL for the same
    three answers, not a fourth answer."""
    out = _report(_contract(verdict))
    assert out["verdict"] == expected
    assert out["source"] == "contract"


# ══════════════════════════════════════════════════════════════════════════
# 2. a decision is not a deliberation
# ══════════════════════════════════════════════════════════════════════════

def test_an_echoed_instruction_is_not_a_conclusion():
    """⛔ #753, exactly: the model quoting the format back while reasoning. The
    line anchor is what separates them — an echo sits inside a sentence.

    The assertion is that the echo did not DECIDE. What the prose fallback then
    makes of the sentence is a separate question, and here it recognises nothing
    it knows ("the spinner is still turning" is not in the phrase list and is
    not an affirmation), so it reports "ambiguous" — the absence of a reading,
    which is exactly what it is. What must never happen is "complete"."""
    echo = ("I would reply 'VERDICT: complete' if the time badge were there, "
            "but it is not, and the spinner is still turning.")
    out = _report(echo)
    assert out["source"] == "prose", "an inline echo was taken as the verdict line"
    assert out["verdict"] != "complete"


def test_an_echoed_instruction_does_not_beat_a_real_conclusion():
    """The same echo, followed by the model actually answering. The conclusion
    is on its own line and is the last one, so it decides."""
    echo = ("I would reply 'VERDICT: complete' if the time badge were there, "
            "but it is not.\nVERDICT: generating\nSTOP_BUTTON: no\n"
            "EVIDENCE: a shimmering 'Researching' status line")
    out = _report(echo)
    assert out["source"] == "contract"
    assert out["verdict"] == "generating"


def test_the_last_verdict_line_wins():
    """A model that reasons out loud may name a verdict on the way to a
    different conclusion. The conclusion is the one it wrote last.

    ⚠ BOTH lines have to be properly anchored for this to test anything. The
    first draft wrote the earlier one as "First read: VERDICT: generating",
    which does not begin a line — so there was only ever one match, first and
    last were the same, and a mutation making FIRST win survived."""
    reasoned = ("Initial impression, before scrolling:\n"
                "VERDICT: generating\n"
                "Then I scrolled up and found the time badge.\n"
                "VERDICT: complete\nSTOP_BUTTON: no\nEVIDENCE: Worked for 9m")
    assert len(research._CUA_VERDICT_LINE.findall(reasoned)) == 2, (
        "the fixture only produces one anchored verdict — it cannot tell first "
        "from last"
    )
    assert _report(reasoned)["verdict"] == "complete"


@pytest.mark.parametrize("line", [
    "VERDICT: complete",
    "verdict: Complete",
    "  VERDICT:complete",
    "VERDICT = complete",
    "Verdict:  complete  ",
])
def test_the_line_is_read_through_ordinary_formatting_variation(line):
    """A contract only helps if a model that basically complied is understood.
    Anything looser than this would start matching prose again."""
    assert _report(f"some reasoning\n{line}\nSTOP_BUTTON: no")["verdict"] == "complete"


def test_a_verdict_word_alone_on_a_line_is_not_the_contract():
    """No label, no contract. Falling back is correct — that is prose."""
    assert _report("complete\nthe report looks done")["source"] == "prose"


# ══════════════════════════════════════════════════════════════════════════
# 3. ⛔ the stop button still wins
# ══════════════════════════════════════════════════════════════════════════

def test_a_reported_stop_button_overrides_a_complete_verdict():
    """⛔ The cost asymmetry is unchanged: a false "generating" costs a poll
    interval, a false "complete" extracts an in-flight response and reports "no
    brief generated". An answer that says both is inconsistent, and the safe
    reading of an inconsistent answer is the cheap one."""
    out = _report(_contract("complete", stop="yes"))
    assert out["verdict"] == "generating"
    assert out["stop_seen"] is True


def test_unsure_about_the_stop_button_is_not_a_sighting():
    """The confirm budget escalates to a user decision on THREE positive
    sightings. "unsure" must not count toward that — it is the absence of an
    observation, and counting it would turn hesitancy into a card."""
    out = _report(_contract("unknown", stop="unsure"))
    assert out["stop_seen"] is False


def test_the_stop_field_is_read_even_when_the_verdict_line_is_missing():
    """The two reads are independent. A half-complying model still contributes
    the field the polarity rule depends on."""
    out = _report("STOP_BUTTON: yes\nI think it is still working on it.")
    assert out["stop_seen"] is True
    assert out["verdict"] == "generating"


def test_the_pre_contract_stop_derivation_still_works():
    """The fallback path's own polarity, unchanged: the CUA writes "Stop button:
    Yes" and it is read FORWARD within the clause.

    ⚠ The affirmation must sit MID-LINE, or `_CUA_STOP_LINE` matches it and the
    contract answers instead. The first draft put it at the start of the line,
    so a mutation deleting the fallback derivation entirely survived — the test
    named `_cua_affirms` and never reached it."""
    answer = "Looking at the composer — Stop button: Yes, a filled square."
    assert not research._CUA_STOP_LINE.findall(answer), (
        "the fixture is being answered by the contract, not the fallback"
    )
    out = _report(answer)
    assert out["stop_seen"] is True
    assert out["verdict"] == "generating"


# ══════════════════════════════════════════════════════════════════════════
# 4. the corpus keeps resolving exactly as it did
# ══════════════════════════════════════════════════════════════════════════

CORPUS = [
    # (answer, expected verdict) — every one of these is from an incident.
    ("Observing the screen carefully: there is no filled square stop button "
     "visible. I can see \"Worked for 9m\" label at the top of the response.",
     "complete"),
    ("still generating — there is a filled square Stop button", "generating"),
    ("stop button: yes", "generating"),
    ("i cannot tell", "generating"),
    ("", "ambiguous"),
    ("response complete", "complete"),
    ("stop button: no. the response is complete.", "complete"),
]


@pytest.mark.parametrize("answer,expected", CORPUS)
def test_an_answer_without_the_lines_resolves_exactly_as_before(answer, expected):
    """⛔ The fallback is not a formality. Every entry here is a real vision
    answer from a real incident, and the contract must not quietly change what
    any of them means — a model that ignores the format is the normal case to
    plan for, not the exception."""
    out = _report(answer)
    assert out["verdict"] == expected
    assert out["verdict"] == _prose(answer) or out["stop_seen"]
    assert out["source"] == "prose"


def test_the_source_says_which_channel_decided():
    """Observability, and the reason it is worth having: a run whose confirms
    all read "prose" means the format is being ignored and the fallback is
    carrying the feature. That is worth seeing before it becomes an incident."""
    assert _report(_contract("complete"))["source"] == "contract"
    assert _report("the report looks finished to me")["source"] == "prose"


# ══════════════════════════════════════════════════════════════════════════
# 5. the missions actually ask for it
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mission_name", ["_CONFIRM_COMPLETION_MISSION"])
def test_the_confirm_mission_carries_the_contract(mission_name):
    m = getattr(research, mission_name)
    assert "VERDICT:" in m and "STOP_BUTTON:" in m and "EVIDENCE:" in m


def test_the_safety_net_mission_carries_the_contract():
    """Both twins ask the same question about the same screen. One of them
    asking in a different shape is how two vocabularies for one answer get
    created — which is the defect this whole area keeps producing."""
    import inspect
    src = inspect.getsource(research.poll_until_done)
    assert src.count("_CUA_CONTRACT_BLOCK") >= 1
    assert "_sn_mission" in src
    i = src.index("_sn_mission = (")
    assert "_CUA_CONTRACT_BLOCK" in src[i:i + 2000], (
        "the safety-net mission does not carry the verdict contract"
    )


def test_the_contract_names_unknown_as_a_real_answer():
    """A format that offers only two verdicts forces "I cannot tell" to be
    spelled as one of them, and the safer-sounding one is "generating" — which
    is how a failure to READ became a positive observation of generation."""
    block = research._CUA_CONTRACT_BLOCK
    assert "unknown" in block and "unsure" in block
    assert "rather than guessing" in block


def test_the_contract_asks_for_the_lines_last():
    """Reasoning first, conclusion last — that ordering is what makes "the last
    VERDICT line wins" the right rule rather than a lucky one."""
    assert "last" in research._CUA_CONTRACT_BLOCK.lower()
