"""Stretch 7.5 step 4 — a subject check the opening brief never had, and a
second opinion that can actually disagree.

⛔⛔ THE PREMISE THIS STEP WAS PLANNED ON WAS FALSE, AND IT CAME FROM A COMMENT.
The plan said briefs run 2,000-5,000 characters, so the existing guard's
20,000-character floor meant "the obvious fix can never fire". The number came
from `research.py`'s own brief-short comment. Twenty-seven real briefs in this
machine's logs (`~/.super-research/logs`, `Brief extracted: N chars`) measure:

    min 46,183 · median 62,893 · max 73,494 — not one under 46 KB.

So the obvious fix would have fired on every one of them. What makes it the
wrong fix is not that it cannot fire, it is what it DOES: `reject_off_topic_text`
answers a bad document with `""`, and phase 2 cannot run without a brief. Pointed
at the brief it would end runs, reporting the brief as MISSING rather than wrong,
with no card and no way back.

What is confirmed, and is the actual hole: the brief passes no subject check on
any path, and it is the one document all three researchers work from — one string
pasted into three composers, one file attached to all three. A wrong report costs
one leg; a wrong brief costs the run.

THE OTHER HALF. The "cross-verify" on the reports is the same pure function, on
the same string, resolving the same topic from the same folder, THREE times: once
in the finalize path and twice at the sweeps. It cannot reject anything the first
pass accepted. Meanwhile the extractors accept a report at 100 characters and the
guard will not look below 20,000, so everything between is written, mirrored,
merged and handed to NotebookLM having never been compared to what the user asked
for. The file already knows: the phase-2→3 handoff carries a belt described as
covering "the case the sweep cannot judge — a topic under the anchor floor, or
text under the size floor", and that belt dates a conversation id out of a URL.

A second opinion is not the first one run again. It is the same question asked of
DIFFERENT EVIDENCE — here, the text the agent's own activity panel produced while
it worked: a different source, a different mechanism, a different moment.

Run:  pytest tests/test_brief_and_second_opinion_0902.py -v
"""
import ast
import asyncio
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

# The 2026-08-05 incident's topic, reused so the two files talk about the same
# run. Its distinctive words are nemoclaw / nemohermes / nemotron / openshell.
TOPIC = ("NemoClaw vs NemoHermes vs Nemotron and also about OpenShell and how "
         "all of these can be used for security")

# A brief at the MEASURED size of a real one, on topic and off.
ON_TOPIC_BRIEF = ("## Scope\n\nCompare NemoClaw and Nemotron guardrail coverage, "
                  "then assess OpenShell exposure.\n\n") * 900        # ~99k
OFF_TOPIC_BRIEF = ("## Scope\n\nEvidence-based global breed, health, welfare and "
                   "ownership reporting for the retriever.\n\n") * 900  # ~99k

# A topic with no distinctive vocabulary at all — perfectly good, unguardable.
BLAND_TOPIC = "best practices for team retrospectives"


# ─────────────────────────────────────────────────────────────────────────────
# ONE RULE, NOT ONE COPY PER ARTEFACT
#
# "Does this text name the subject?" existed twice with two different length
# policies, because a title is thirty characters and could never clear a
# 20,000-character floor. The length policy now belongs to the callers.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_presence_rule_has_no_length_floor_of_its_own():
    """The whole point of splitting it out. Thirty characters is a real answer."""
    assert research.topic_presence("A Nemotron security note", TOPIC) is True
    assert research.topic_presence("A golden retriever note", TOPIC) is False


def test_an_unguardable_topic_is_a_THIRD_answer_not_a_pass():
    """`None` is not `False`. "I cannot judge this" and "this is fine" lead to
    different places, and collapsing them is how a guard goes silently inert."""
    assert research.topic_presence("anything at all", BLAND_TOPIC) is None
    assert research.topic_presence("", BLAND_TOPIC) is None


@pytest.mark.parametrize("text", ["", None])
def test_empty_text_against_a_guardable_topic_names_nothing(text):
    """Distinct from the unguardable case: the topic IS judgeable, the text just
    says nothing. Callers apply their own floor to decide whether that matters."""
    assert research.topic_presence(text, TOPIC) is False


def test_matching_is_substring_so_inflections_and_versions_still_count():
    assert research.topic_presence("we deployed Nemotron-4 last week", TOPIC) is True
    assert research.topic_presence("NemoClaw's guardrails", TOPIC) is True


def test_one_anchor_anywhere_is_enough():
    assert research.topic_presence(
        ("filler " * 5000) + "openshell" + (" filler" * 5000), TOPIC) is True


# ─────────────────────────────────────────────────────────────────────────────
# THE REFACTOR MOVED NOTHING
#
# ⭐⭐ The strongest thing this file asserts. A behaviour-preserving refactor is
# only preserving if you check, and "the tests still pass" checks the cases
# someone already thought of. These two re-implement the ORIGINAL bodies and
# compare verdict-for-verdict across a matrix that includes both sides of every
# threshold.
# ─────────────────────────────────────────────────────────────────────────────

def _text_is_off_topic_ORIGINAL(text, topic):
    """`text_is_off_topic` exactly as it stood before 2026-09-02."""
    anchors = research.topic_anchors(topic)
    if len(anchors) < research._TOPIC_GUARD_MIN_ANCHORS:
        return False
    if len(text or "") < research._TOPIC_GUARD_MIN_CHARS:
        return False
    low = text.lower()
    return not any(a in low for a in anchors)


def _title_refusal_verdict_ORIGINAL(title, topic, corpus):
    """`title_refusal_verdict` exactly as it stood before 2026-09-02."""
    _t = (title or "").strip()
    if not _t:
        return "accept"
    anchors = research.topic_anchors(topic)
    if len(anchors) < research._TOPIC_GUARD_MIN_ANCHORS:
        return "accept"
    low = _t.lower()
    if any(a in low for a in anchors):
        return "accept"
    return ("refuse_loud" if _text_is_off_topic_ORIGINAL(corpus or "", topic)
            else "refuse_silent")


_FLOOR = research._TOPIC_GUARD_MIN_CHARS
_MATRIX_TEXTS = [
    "", None,
    "nemotron",                                  # anchor, far below the floor
    "golden retriever",                          # no anchor, far below the floor
    "x" * (_FLOOR - 1),                          # one character below the floor
    "x" * _FLOOR,                                # exactly at the floor
    "x" * (_FLOOR - 1) + "nemotron",             # anchor, straddling the floor
    ("golden retriever " * 2000),                # no anchor, well above
    ("nemoclaw " * 4000),                        # anchor, well above
]
_MATRIX_TOPICS = [TOPIC, BLAND_TOPIC, "", None, "NemoClaw"]


@pytest.mark.parametrize("text", _MATRIX_TEXTS)
@pytest.mark.parametrize("topic", _MATRIX_TOPICS)
def test_the_report_predicate_is_byte_for_byte_the_old_one(text, topic):
    assert research.text_is_off_topic(text, topic) is _text_is_off_topic_ORIGINAL(
        text, topic), (text[:40] if text else text, topic)


@pytest.mark.parametrize("title", ["", "   ", "Nemotron Security Review",
                                   "Golden Retriever Ownership Evidence"])
@pytest.mark.parametrize("corpus", ["", "golden retrievers",
                                    ("golden retriever " * 2000),
                                    ("nemoclaw " * 4000)])
@pytest.mark.parametrize("topic", [TOPIC, BLAND_TOPIC])
def test_the_title_verdict_is_byte_for_byte_the_old_one(title, corpus, topic):
    assert research.title_refusal_verdict(title, topic, corpus) == \
        _title_refusal_verdict_ORIGINAL(title, topic, corpus)


def test_the_title_check_still_judges_a_thirty_character_title():
    """The refactor's whole risk: the title check had NO floor by hand, and the
    shared rule it now calls must not have acquired one."""
    assert research.title_refusal_verdict(
        "Golden Retriever Health Evidence", TOPIC,
        ("golden retriever " * 2000)) == "refuse_loud"


def test_the_predicate_is_still_consulted_in_exactly_two_places():
    """⛔ The invariant `test_reject_off_topic_text_is_the_only_place_the_decision
    _is_made` protects, restated here because this step was the obvious place to
    break it: the temptation was to add a third caller with a lower floor. The
    floor moved to the callers instead, so the count is untouched."""
    src = code_only(open(research.__file__, encoding="utf-8").read())
    assert src.count("text_is_off_topic(") == 3


# ─────────────────────────────────────────────────────────────────────────────
# THE BRIEF'S VERDICT
# ─────────────────────────────────────────────────────────────────────────────

def test_a_full_length_brief_that_never_names_the_subject_is_off_topic():
    assert len(OFF_TOPIC_BRIEF) > 46_000, "fixture must match a real brief's size"
    assert research.brief_topic_verdict(OFF_TOPIC_BRIEF, TOPIC) == "off_topic"


def test_a_brief_about_the_topic_is_accepted():
    assert research.brief_topic_verdict(ON_TOPIC_BRIEF, TOPIC) == "accept"


def test_the_measured_size_of_a_real_brief_clears_the_bar_with_room_to_spare():
    """⛔ The plan said briefs are 2-5k and the guard's floor is 20,000, so the
    fix "can never fire". Both halves are wrong: the smallest measured brief is
    46,183 characters. This pins the bar low enough that the SMALLEST real brief
    is judged, which is the property the plan believed was unobtainable."""
    assert research._BRIEF_TOPIC_MIN_CHARS <= 46_183


def test_the_bar_is_the_same_number_the_pipeline_already_uses_for_brief_or_stub():
    """Three answers to "is this a brief?" would rot apart. This is deliberately
    the figure the salvage offer and the extract accept gate already share.

    ⚠ The extract accept gate's copy is a LOCAL inside `poll_until_done`, not a
    module constant, so it is read from source. That asymmetry is pre-existing —
    the comment tying the two together names it as a constant and it is not."""
    assert research._BRIEF_TOPIC_MIN_CHARS == research._MIN_SALVAGEABLE_BRIEF_LEN
    poll_src = inspect.getsource(research.poll_until_done)
    assert f"_SAFETY_NET_MIN_BRIEF_LEN = {research._BRIEF_TOPIC_MIN_CHARS}" in poll_src


def test_a_stub_shorter_than_a_brief_is_never_judged():
    """A document this short has too few chances to name its subject for a zero
    to mean anything, and the length guards upstream already have opinions.

    ⚠ Its fixture is derived from the constant, so it pins that the bar is
    RESPECTED, not where the bar is — see the absolute statement below."""
    stub = OFF_TOPIC_BRIEF[:research._BRIEF_TOPIC_MIN_CHARS - 1]
    assert research.brief_topic_verdict(stub, TOPIC) == "abstain"


def test_A_FEW_HUNDRED_CHARACTERS_IS_NEVER_A_BRIEF():
    """⛔ Stated absolutely, because the test above cannot see the bar move: its
    input is computed from the number it is checking, so dropping the bar to 1
    empties the fixture and it abstains for the wrong reason.

    500 characters is where the pipeline's own short-brief card already says the
    extraction went wrong. Nothing that short is a research brief, and judging
    one would be judging a fragment."""
    assert research.brief_topic_verdict(
        OFF_TOPIC_BRIEF[:500], TOPIC) == "abstain"


def test_one_character_more_and_it_IS_judged():
    """Both sides of the bar, so a mutant that moves it has somewhere to fail."""
    judged = OFF_TOPIC_BRIEF[:research._BRIEF_TOPIC_MIN_CHARS]
    assert research.brief_topic_verdict(judged, TOPIC) == "off_topic"


def test_an_unguardable_topic_abstains_however_wrong_the_brief_looks():
    assert research.brief_topic_verdict(OFF_TOPIC_BRIEF, BLAND_TOPIC) == "abstain"


@pytest.mark.parametrize("brief", ["", None, "   "])
def test_no_brief_is_not_an_off_topic_brief(brief):
    assert research.brief_topic_verdict(brief, TOPIC) == "abstain"


def test_leading_and_trailing_whitespace_does_not_buy_length():
    """A stub padded with newlines must not clear the bar by being padded."""
    padded = " " * 10_000 + OFF_TOPIC_BRIEF[:500] + " " * 10_000
    assert research.brief_topic_verdict(padded, TOPIC) == "abstain"


def test_the_brief_verdict_is_pure():
    """No page, no run directory, no thread — the same property that makes
    `title_refusal_verdict` testable in both polarities."""
    assert not inspect.iscoroutinefunction(research.brief_topic_verdict)
    params = list(inspect.signature(research.brief_topic_verdict).parameters)
    assert params == ["brief", "topic"], params


# ─────────────────────────────────────────────────────────────────────────────
# THE GATE — the decision AND what it does about it, EXECUTED
#
# ⛔⛔ The plan's own warning for this step: "a test asserting the call exists
# would pass". Every test below drives the real coroutine and reads the real
# consequences — the card, the events, the returned move. None of them greps.
# ─────────────────────────────────────────────────────────────────────────────

class _Bus:
    """A phase-decision bus that answers once with a scripted verdict.

    ⛔ IT RECORDS WHETHER IT WAS ASKED. Half the properties here are about the
    gate NOT waiting — a card with no Retry button that still awaits a decision
    hangs the phase forever, and a test that only checks the return value cannot
    tell the difference."""

    def __init__(self, answer="skip"):
        self.answer = answer
        self.asked = []

    async def await_phase_decision(self, phase, timeout=86400.0):
        self.asked.append(phase)
        return self.answer


@pytest.fixture
def gate(monkeypatch):
    """Drive `brief_topic_gate` with a scripted bus, capturing cards and events."""
    cards, events, logs = [], [], []

    bus = _Bus()
    monkeypatch.setattr(research._controls, "await_phase_decision",
                        bus.await_phase_decision)
    monkeypatch.setattr(research, "fail_phase",
                        lambda *a, **k: cards.append((a, k)))
    monkeypatch.setattr(research, "emit_event",
                        lambda name, **k: events.append((name, k)))
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: logs.append((level, msg)))

    def _run(brief, topic, *, answer="skip", retry_count=0, max_retries=2):
        bus.answer = answer
        return asyncio.run(research.brief_topic_gate(
            brief, topic, retry_count=retry_count, max_retries=max_retries))

    _run.cards, _run.events, _run.logs, _run.bus = cards, events, logs, bus
    return _run


def test_an_off_topic_brief_raises_a_card_the_user_can_answer(gate):
    gate(OFF_TOPIC_BRIEF, TOPIC)
    assert len(gate.cards) == 1, gate.cards
    args, kwargs = gate.cards[0]
    assert args[0] == 1, "the card belongs to phase 1"
    assert kwargs["can_retry"] is True
    assert kwargs["agent"] == "chatgpt"


def test_the_card_names_the_words_it_looked_for(gate):
    """A card that says only "this looks wrong" cannot be judged by the person
    reading it. It has to say what it searched the brief for and did not find."""
    gate(OFF_TOPIC_BRIEF, TOPIC)
    _, kwargs = gate.cards[0]
    body = gate.cards[0][0][2]
    assert "nemoclaw" in body.lower(), body
    assert "nemotron" in body.lower(), body


def test_the_card_says_why_a_wrong_brief_is_worse_than_a_wrong_report(gate):
    """The one fact that makes this worth interrupting for: all three agents work
    from this document, so the blast radius is the whole run."""
    gate(OFF_TOPIC_BRIEF, TOPIC)
    body = gate.cards[0][0][2].lower()
    assert "three" in body and "researcher" in body, body


def test_an_on_topic_brief_raises_nothing_and_asks_nobody(gate):
    assert gate(ON_TOPIC_BRIEF, TOPIC) == "keep"
    assert gate.cards == []
    assert gate.bus.asked == [], "a healthy brief must never block on a human"


def test_an_abstain_raises_nothing_and_asks_nobody(gate):
    assert gate(OFF_TOPIC_BRIEF, BLAND_TOPIC) == "keep"
    assert gate.cards == []
    assert gate.bus.asked == []


def test_an_abstain_SAYS_it_abstained(gate):
    """⛔ A silent abstain reads exactly like a pass. The phase-2 sweep already
    logs an INERT line for this reason; phase 1 needs the same, because it
    abstains on the two shapes most likely to be wrong."""
    gate(OFF_TOPIC_BRIEF, BLAND_TOPIC)
    assert any("ABSTAIN" in m for _, m in gate.logs), gate.logs
    # And the healthy case must NOT print it, or the line means nothing.
    gate.logs.clear()
    gate(ON_TOPIC_BRIEF, TOPIC)
    assert not any("ABSTAIN" in m for _, m in gate.logs), gate.logs


def test_retry_is_what_the_user_asked_for(gate):
    assert gate(OFF_TOPIC_BRIEF, TOPIC, answer="retry") == "retry"
    assert gate.bus.asked == [1]


def test_stop_ends_the_run(gate):
    assert gate(OFF_TOPIC_BRIEF, TOPIC, answer="stop") == "stop"


@pytest.mark.parametrize("answer", ["skip", "timeout"])
def test_the_user_may_keep_a_brief_the_guard_dislikes(answer, gate):
    """⛔ THE ASYMMETRY THAT MATTERS. The guard's opinion never outranks the
    person's. A false positive costs one question, not a run."""
    assert gate(OFF_TOPIC_BRIEF, TOPIC, answer=answer) == "keep"


def test_it_never_returns_a_modified_brief(gate):
    """The reason this is a verdict and not `reject_off_topic_text` pointed at
    the brief: that function answers with `""`, and phase 2 cannot run without a
    brief — it would report the brief MISSING rather than wrong."""
    for answer in ("skip", "retry", "stop", "timeout"):
        assert gate(OFF_TOPIC_BRIEF, TOPIC, answer=answer) in (
            "keep", "retry", "stop")


def test_the_retry_budget_is_shared_with_the_short_brief_guard(gate):
    """Two guards on one phase, one attempt cap. Spent means spent."""
    assert gate(OFF_TOPIC_BRIEF, TOPIC, answer="retry",
                retry_count=2, max_retries=2) == "keep"


def test_with_no_retries_left_the_card_offers_none(gate):
    gate(OFF_TOPIC_BRIEF, TOPIC, retry_count=2, max_retries=2)
    assert gate.cards[0][1]["can_retry"] is False


def test_with_no_retries_left_it_does_not_WAIT_for_an_answer(gate):
    """⛔ THE HANG. The card has no Retry button, so there is no answer coming.
    Awaiting the bus anyway parks phase 1 for twenty-four hours. The returned
    value alone cannot catch this — only asking whether the bus was consulted."""
    gate(OFF_TOPIC_BRIEF, TOPIC, retry_count=2, max_retries=2)
    assert gate.bus.asked == [], "it waited on a decision nobody can give"


def test_a_missing_brief_is_not_this_guards_problem(gate):
    """Empty briefs have their own path. This one must not add a second card."""
    for brief in ("", None):
        assert gate(brief, TOPIC) == "keep"
    assert gate.cards == []


def test_the_retry_is_recorded_as_a_phase_restart(gate):
    """The analytics page counts restarts by reason; a new restart cause that
    emits nothing is invisible to it."""
    gate(OFF_TOPIC_BRIEF, TOPIC, answer="retry")
    restarts = [k for n, k in gate.events if n == "phase_restart"]
    assert len(restarts) == 1, gate.events
    assert restarts[0]["reason"] == "user_retry_brief_off_topic"
    assert restarts[0]["attempt"] == 2


def test_the_rejection_is_recorded_where_the_other_ones_are(gate):
    """`wrong_artifact_rejected` is how every other wrong-document verdict in
    this pipeline is counted. A phase-1 verdict that used a name of its own
    would not show up beside them."""
    gate(OFF_TOPIC_BRIEF, TOPIC)
    rejects = [k for n, k in gate.events if n == "wrong_artifact_rejected"]
    assert len(rejects) == 1, gate.events
    assert rejects[0]["phase"] == 1
    assert rejects[0]["tier"] == "topic_guard"


def test_nothing_is_emitted_for_a_healthy_brief(gate):
    gate(ON_TOPIC_BRIEF, TOPIC)
    assert gate.events == []


def test_the_card_is_raised_BEFORE_the_wait(gate):
    """Order is the whole mechanism: a decision bus with no card on screen is a
    phase waiting on a button the user was never shown."""
    order = []
    gate.bus.asked = order_probe = []

    class _OrderBus(_Bus):
        async def await_phase_decision(self, phase, timeout=86400.0):
            order.append("waited")
            order_probe.append(phase)
            return "skip"

    bus = _OrderBus()
    import unittest.mock as _m
    with _m.patch.object(research._controls, "await_phase_decision",
                         bus.await_phase_decision), \
         _m.patch.object(research, "fail_phase",
                         lambda *a, **k: order.append("carded")):
        asyncio.run(research.brief_topic_gate(
            OFF_TOPIC_BRIEF, TOPIC, retry_count=0, max_retries=2))
    assert order == ["carded", "waited"], order


# ─────────────────────────────────────────────────────────────────────────────
# THE SECOND WITNESS
# ─────────────────────────────────────────────────────────────────────────────

import json
import tempfile
from pathlib import Path


def _report(n, on_topic):
    """A report at a length the extractors accept but the incumbent will not judge."""
    unit = ("Nemotron and OpenShell both expose a libkrun boundary. " if on_topic
            else "Golden retrievers are a friendly breed with a cancer rate. ")
    return (unit * (n // len(unit) + 1))[:n]


def _panel(on_topic, n=1200):
    """What an activity panel's step titles and section headings look like."""
    unit = ("Searching build.nvidia.com for Nemotron guardrails\n" if on_topic
            else "Searching akc.org for retriever hip dysplasia rates\n")
    return (unit * (n // len(unit) + 1))[:n]


@pytest.fixture(autouse=True)
def _clean_snapshots():
    before = dict(getattr(research._runtime, "agent_progress_snapshots", {}))
    research._runtime.agent_progress_snapshots = {}
    yield
    research._runtime.agent_progress_snapshots = before


def test_the_witness_is_what_the_agents_own_panel_said(_clean_snapshots=None):
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": ["Searching for Nemotron benchmarks"],
        "sections": ["Guardrail coverage"],
        "current_focus": "Reading build.nvidia.com",
    }
    w = research.mid_run_witness_text("chatgpt")
    assert "Nemotron benchmarks" in w
    assert "Guardrail coverage" in w
    assert "build.nvidia.com" in w


def test_the_witness_carries_no_urls():
    """⛔ Source URLs are in the snapshot and are deliberately NOT in the witness.
    A hostname can contain an anchor by luck — `nemotron.example.com` in a
    tracking parameter is not the agent saying anything about Nemotron."""
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": [], "sections": [],
        "source_urls": ["https://nemotron.example.com/a"],
    }
    assert research.mid_run_witness_text("chatgpt") == ""


def test_an_agent_that_never_entered_the_poll_set_has_no_witness():
    assert research.mid_run_witness_text("claude") == ""


def test_a_non_string_in_the_snapshot_does_not_raise():
    """The snapshot is built from scraped page data. It must not be able to
    crash the sweep it feeds."""
    research._runtime.agent_progress_snapshots["gemini"] = {
        "steps": [None, 3, "a real step"], "sections": {}, "current_focus": 7,
    }
    assert research.mid_run_witness_text("gemini") == "a real step"


# ── the four verdicts, pure ──────────────────────────────────────────────────

def test_a_report_that_names_the_subject_needs_no_second_opinion():
    assert research.report_second_opinion(
        _report(5_000, True), TOPIC, _panel(False)) == "agree"


def test_when_the_report_says_nothing_but_the_panel_did_the_EXTRACTION_is_suspect():
    """⭐⭐ THE VERDICT THE INCUMBENT CANNOT REACH. The leg researched the right
    subject — its own interface said so while it worked — so what came back is
    not what it wrote. That is a different problem from drift, and until now the
    two were indistinguishable from the report alone."""
    assert research.report_second_opinion(
        _report(5_000, False), TOPIC, _panel(True)) == "extraction_suspect"


def test_when_NEITHER_names_the_subject_two_independent_sources_agree():
    assert research.report_second_opinion(
        _report(5_000, False), TOPIC, _panel(False)) == "drift_corroborated"


def test_a_thin_witness_cannot_corroborate_anything():
    """⛔ The direction that matters. One witness saying nothing is not evidence
    — it is why the incumbent abstains below 20,000 characters in the first
    place. A second witness that barely spoke must not upgrade it."""
    thin = _panel(False, research._WITNESS_MIN_CHARS - 1).strip()
    assert len(thin) == research._WITNESS_MIN_CHARS - 1
    assert research.report_second_opinion(_report(5_000, False), TOPIC,
                                          thin) == "abstain"


def test_A_SINGLE_SCRAPED_LINE_IS_NEVER_A_SECOND_WITNESS():
    """⛔⛔ THE TEST ABOVE CANNOT SEE THE BAR MOVE, AND MUTATION PROVED IT. Its
    fixture is `_WITNESS_MIN_CHARS - 1` characters long — derived from the very
    number it is meant to pin — so dropping the bar to 1 makes the fixture empty
    and it abstains for a different reason, passing. A test whose input is
    computed from the value under test cannot detect a change to that value.

    This one states the property in absolute terms instead: a panel holding one
    step title is not a witness. 220 characters is the scraper's own per-step
    cap (`out.steps.push(t.slice(0, 220))`), so this is the largest single line
    the panel can produce, and one line is not the agent having told us what it
    spent an hour on."""
    one_line = "Searching akc dot org for retriever hip dysplasia rates" * 4
    assert len(one_line) <= 220, "a single scraped step title, at the scraper's cap"
    assert research.report_second_opinion(
        _report(5_000, False), TOPIC, one_line) == "abstain"


def test_the_witness_bar_sits_between_one_line_and_a_working_leg():
    """The constant itself, bounded from both sides, so neither direction of
    drift is silent. Below 220 a single step title would convict a leg; above
    ~3,500 nothing realistic clears it, because the caps are 15 steps and 20
    headings and a real panel repeats itself."""
    assert research._WITNESS_MIN_CHARS > 220
    assert research._WITNESS_MIN_CHARS < 3_500


def test_one_character_more_of_witness_and_it_DOES_corroborate():
    """Both sides of the bar, so a mutant that moves it has somewhere to fail."""
    enough = _panel(False, research._WITNESS_MIN_CHARS + 40).strip()[
        :research._WITNESS_MIN_CHARS - 1] + "x"
    assert len(enough) == research._WITNESS_MIN_CHARS
    assert enough == enough.strip(), "the fixture must not lose length to strip()"
    assert research.report_second_opinion(_report(5_000, False), TOPIC,
                                          enough) == "drift_corroborated"


def test_whitespace_does_not_buy_a_witness_its_length():
    """A panel that scraped nothing but blank lines has not spoken."""
    assert research.report_second_opinion(
        _report(5_000, False), TOPIC, " " * 50_000) == "abstain"


@pytest.mark.parametrize("witness", ["", None, "   "])
def test_no_witness_is_an_abstain_not_a_verdict(witness):
    assert research.report_second_opinion(
        _report(5_000, False), TOPIC, witness) == "abstain"


def test_an_unguardable_topic_abstains_before_anything_else_is_read():
    assert research.report_second_opinion(
        _report(5_000, False), BLAND_TOPIC, _panel(False)) == "abstain"


def test_it_judges_the_reports_the_incumbent_will_not_look_at():
    """The gap this closes, stated as a size: the extractors accept a report at
    100 characters and the incumbent will not judge below 20,000."""
    short = _report(5_000, False)
    assert research.text_is_off_topic(short, TOPIC) is False, "incumbent abstains"
    assert research.report_second_opinion(
        short, TOPIC, _panel(False)) == "drift_corroborated"


def test_the_second_opinion_is_pure():
    assert not inspect.iscoroutinefunction(research.report_second_opinion)
    assert list(inspect.signature(research.report_second_opinion).parameters) == \
        ["text", "topic", "witness"]


# ─────────────────────────────────────────────────────────────────────────────
# THE SWEEP CONSULTS IT — driven end to end, not read
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def run_dir():
    d = Path(tempfile.mkdtemp())
    (d / "documents").mkdir()
    (d / "meta.json").write_text(json.dumps({"topic": TOPIC}), encoding="utf-8")
    return d


@pytest.fixture()
def spy(monkeypatch):
    """Capture what the sweep says, without changing what it decides."""
    events, logs = [], []
    monkeypatch.setattr(research, "emit_event",
                        lambda name, **k: events.append((name, k)))
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: logs.append((level, msg)))
    return {"events": events, "logs": logs}


def _drifted_leg():
    return {"ChatGPT": {"status": "done", "text": _report(5_000, False),
                        "url": "https://chatgpt.com/c/abc", "verified": True}}


def test_the_sweep_reaches_a_verdict_on_a_report_it_cannot_reject(run_dir, spy):
    """⭐⭐ THE HEADLINE. The incumbent abstains on this report and leaves it in
    place — correctly, it has no grounds. The second witness gives it grounds."""
    results = _drifted_leg()
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": [_panel(False, 800)], "sections": [], "current_focus": "",
    }
    assert research.apply_off_topic_sweep(results, run_dir) == [], \
        "precondition: the incumbent has nothing to say about a 5,000-char report"
    assert results["ChatGPT"]["topic_second_opinion"] == "drift_corroborated"


def test_a_corroborated_drift_tells_the_user(run_dir, spy):
    results = _drifted_leg()
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": [_panel(False, 800)], "sections": [], "current_focus": "",
    }
    research.apply_off_topic_sweep(results, run_dir)
    warns = [k for n, k in spy["events"] if n == "pipeline_warning"]
    assert len(warns) == 1, spy["events"]
    assert warns[0]["alert_id"] == "phase2_chatgpt_second_opinion"
    assert warns[0]["actions"] == [], "phase 2 is over — there is nothing to skip"
    assert "message" in warns[0], "the web app's warning branch reads message"


def test_a_suspect_extraction_is_logged_and_NOT_carded(run_dir, spy):
    """⭐ The witnesses DISAGREE, so the leg did the right work and only the pull
    is doubtful. There is nothing for a person to do, and an anchor test on a
    short report is exactly where a false zero lives."""
    results = _drifted_leg()
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": [_panel(True, 800)], "sections": [], "current_focus": "",
    }
    research.apply_off_topic_sweep(results, run_dir)
    assert results["ChatGPT"]["topic_second_opinion"] == "extraction_suspect"
    assert [k for n, k in spy["events"] if n == "pipeline_warning"] == []
    assert any("SECOND OPINION" in m for _, m in spy["logs"]), spy["logs"]


def test_a_healthy_leg_is_left_entirely_alone(run_dir, spy):
    results = {"Gemini": {"status": "done", "text": _report(5_000, True),
                          "url": "https://gemini.google.com/app/x", "verified": True}}
    research._runtime.agent_progress_snapshots["gemini"] = {
        "steps": [_panel(False, 800)], "sections": [], "current_focus": "",
    }
    assert research.apply_off_topic_sweep(results, run_dir) == []
    assert results["Gemini"]["topic_second_opinion"] == "agree"
    assert [k for n, k in spy["events"] if n == "pipeline_warning"] == []


def test_the_second_opinion_never_destroys_anything(run_dir, spy):
    """⛔ THE ASYMMETRY. Two witnesses raise the confidence enough to TELL
    somebody; they do not raise it enough to fail a leg the user waited an hour
    for. Nothing here may blank text, flip a status, or set the rejection
    marker the handoff reads."""
    results = _drifted_leg()
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": [_panel(False, 800)], "sections": [], "current_focus": "",
    }
    research.apply_off_topic_sweep(results, run_dir)
    r = results["ChatGPT"]
    assert r["text"] == _report(5_000, False)
    assert r["status"] == "done"
    assert r["verified"] is True
    assert "off_topic_rejected" not in r


def test_the_sweep_runs_TWICE_and_the_user_is_told_ONCE(run_dir, spy):
    """⛔⛔ `apply_off_topic_sweep` is called at `run_phase2`'s return AND again
    as a belt in the finalize block. Anything that speaks must speak once, or
    every corroborated drift raises two identical cards."""
    results = _drifted_leg()
    research._runtime.agent_progress_snapshots["chatgpt"] = {
        "steps": [_panel(False, 800)], "sections": [], "current_focus": "",
    }
    research.apply_off_topic_sweep(results, run_dir)
    research.apply_off_topic_sweep(results, run_dir)
    warns = [k for n, k in spy["events"] if n == "pipeline_warning"]
    assert len(warns) == 1, f"spoke {len(warns)} times"


def test_a_rejected_leg_is_never_asked_for_a_second_opinion(run_dir, spy):
    """The incumbent already had grounds and acted. There is nothing to add, and
    the entry's text is blank by then anyway."""
    results = {"ChatGPT": {"status": "done", "text": _report(25_000, False),
                           "url": "https://chatgpt.com/c/abc", "verified": True}}
    assert research.apply_off_topic_sweep(results, run_dir) == ["ChatGPT"]
    assert "topic_second_opinion" not in results["ChatGPT"]


# ─────────────────────────────────────────────────────────────────────────────
# THE SWEEP'S OWN SENTENCE STOPS BEING HALF FALSE
# ─────────────────────────────────────────────────────────────────────────────

def test_a_rejected_legs_REPORT_FILE_is_not_handed_to_notebooklm(run_dir):
    """⛔⛔ The sweep logs that a rejected leg's text "will not be … handed to
    NotebookLM". True of the link, which it drops. False of the FILE, which the
    handoff appended on disk existence alone.

    Today the writers are all gated on the text the sweep blanks, so a rejected
    leg usually leaves no file — but a plain pause/resume does not clear
    `documents/` (only a feedback-targeted resume does), so a previous attempt's
    file outlives the rejection. That is this test."""
    (run_dir / "documents" / "chatgpt.md").write_text("x" * 500, encoding="utf-8")
    results = {"ChatGPT": {"status": "failed", "text": "",
                           "url": "https://chatgpt.com/c/abc",
                           "off_topic_rejected": True}}
    research._runtime.p2_md_files_for_p3 = []
    research._build_phase2_to_phase3_handoff(results, run_dir)
    assert research._runtime.p2_md_files_for_p3 == []


def test_an_accepted_legs_report_file_still_goes(run_dir):
    """The half that must not regress — dropping every file would leave
    NotebookLM with nothing to read."""
    (run_dir / "documents" / "gemini.md").write_text("x" * 500, encoding="utf-8")
    results = {"Gemini": {"status": "done", "text": _report(5_000, True),
                          "url": "https://gemini.google.com/app/x"}}
    research._runtime.p2_md_files_for_p3 = []
    research._build_phase2_to_phase3_handoff(results, run_dir)
    assert [p.name for p in research._runtime.p2_md_files_for_p3] == ["gemini.md"]


# ─────────────────────────────────────────────────────────────────────────────
# THE CALL SITE — read structurally, because nothing executes `run_phase1`
#
# ⚠ HONEST LIMIT. Everything that DECIDES is in `brief_topic_gate` and is driven
# above. What is left in `run_phase1` is a three-outcome dispatch, and this repo
# has no way to execute that function. These read the parse tree rather than the
# text, so a mutant that keeps the words and changes the meaning still fails.
# ─────────────────────────────────────────────────────────────────────────────

def _phase1_tree():
    return ast.parse(inspect.getsource(research.run_phase1).lstrip())


def _gate_call(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "brief_topic_gate"):
            return node
    return None


def test_the_gate_is_actually_called_and_awaited():
    call = _gate_call(_phase1_tree())
    assert call is not None, "the gate is never reached"
    awaits = [n for n in ast.walk(_phase1_tree())
              if isinstance(n, ast.Await) and n.value is not None
              and isinstance(n.value, ast.Call)
              and isinstance(n.value.func, ast.Name)
              and n.value.func.id == "brief_topic_gate"]
    assert awaits, "a coroutine that is never awaited decides nothing"


def test_the_gate_is_handed_the_brief_and_the_topic_not_a_copy_of_one():
    """⛔ The circularity trap, structurally. Passing the brief as BOTH arguments
    — or the run directory's name as the topic — would produce a check that
    always passes, which is the exact defect this step exists to remove."""
    call = _gate_call(_phase1_tree())
    assert [a.id for a in call.args if isinstance(a, ast.Name)] == \
        ["brief_text", "topic"]


def test_the_gate_shares_phase_ones_retry_budget():
    call = _gate_call(_phase1_tree())
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw["retry_count"], ast.Name)
    assert kw["retry_count"].id == "_retry_count"
    assert isinstance(kw["max_retries"], ast.Name)
    assert kw["max_retries"].id == "P1_MAX_USER_RETRIES"


def test_a_retry_verdict_actually_retries_and_COUNTS_the_attempt():
    """⛔ THE INFINITE LOOP. A recursion that forwards the retry count unchanged
    re-enters with a full budget every time. The operand is read, not grepped."""
    src = inspect.getsource(research.run_phase1)
    tree = ast.parse(src.lstrip())
    recursions = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "run_phase1"
        and any(k.arg == "_retry_count" for k in n.keywords)
    ]
    assert recursions, "nothing recurses, so retry cannot mean retry"
    for call in recursions:
        inc = [k.value for k in call.keywords if k.arg == "_retry_count"][0]
        assert isinstance(inc, ast.BinOp) and isinstance(inc.op, ast.Add), \
            ast.dump(inc)
        assert isinstance(inc.right, ast.Constant) and inc.right.value == 1


def test_a_stop_verdict_ends_the_phase_rather_than_carrying_on():
    tree = _phase1_tree()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                and t.left.id == "_bt_action"
                and isinstance(t.comparators[0], ast.Constant)
                and t.comparators[0].value == "stop"):
            assert len(node.body) == 1
            assert isinstance(node.body[0], ast.Return)
            assert isinstance(node.body[0].value, ast.Constant)
            assert node.body[0].value.value is None
            return
    pytest.fail("no branch turns a stop verdict into an ended phase")


def test_the_gate_runs_BEFORE_the_brief_is_returned_to_the_caller():
    """The caller writes the brief to disk, mirrors it to Firestore and pastes it
    into three composers. A check after the return could only apologise."""
    src = code_only(research.run_phase1)
    assert src.index("brief_topic_gate(") < src.index('return {"text": brief_text')


def test_flow_B_still_finds_the_users_own_source_files(run_dir):
    """⛔ THE HALF THE DROP MUST NOT BREAK. When no agent ran at all, the fallback
    scan is the ONLY way NotebookLM gets anything — it is what Flow B (brief and
    every agent off, sources uploaded by the user) depends on entirely. Refusing
    a file this run rejected must not turn into refusing files it never judged."""
    (run_dir / "documents" / "user-notes.md").write_text("x" * 500, encoding="utf-8")
    research._runtime.p2_md_files_for_p3 = []
    research._build_phase2_to_phase3_handoff({}, run_dir)
    assert [p.name for p in research._runtime.p2_md_files_for_p3] == ["user-notes.md"]


def test_the_fallback_scan_still_refuses_derived_documents(run_dir):
    """The scan's original exclusions are untouched: the brief and the merged
    report are byproducts, not sources, and uploading them duplicates content."""
    for stem in ("brief", "consolidated", "keep-me"):
        (run_dir / "documents" / f"{stem}.md").write_text("x" * 500, encoding="utf-8")
    research._runtime.p2_md_files_for_p3 = []
    research._build_phase2_to_phase3_handoff({}, run_dir)
    assert [p.name for p in research._runtime.p2_md_files_for_p3] == ["keep-me.md"]
