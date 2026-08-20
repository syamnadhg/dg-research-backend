"""2026-08-05 — the guards that would each, alone, have stopped the bad run.

Prod run `NemoClaw_vs_NemoHermes_vs_Nemotron_..._20260805_064715`, v0.1.12.
`documents/chatgpt.md` came back 121KB about golden retrievers: 46 hits for
"golden retriever", 0 for any of the topic's four distinctive words. It logged
`status=done`, became source 3-of-3 in NotebookLM, and Phase 3 started
generating a Deep Dive podcast from it.

Four things could have caught it. None did.

  1. The ChatGPT poll leg's scrape read `text_len: 0, sources: 0` for 31
     minutes — the DOM correctly reporting that this conversation produced
     nothing for us. ChatGPT turned out to be the ONLY agent whose CUA
     completion verdict was not sanity-checked against its own scrape: Gemini
     has a source/length rule and Claude an artifact rule, and control fell
     straight past both to the extraction. Two vision "done" readings were
     therefore sufficient to authorise a 120KB save.
  2. The stuck arbiter reset the growth clock on that same never-grew leg, with
     no counter and no cap — each WORKING verdict bought another full window,
     indefinitely.
  3. Nothing compared the extracted text to the topic. A grep for
     off_topic/relevance/topic_guard across all ~58,800 lines returned nothing.
  4. The notebook's title. ⭐ The incident report called this "NotebookLM's
     auto-title derived from the sources". It is not: Phase 3 TYPES a title, and
     that title comes from OUR OWN model summarising the consolidated corpus. So
     our titler had the answer in its hands before Phase 3 spent 30-45 minutes
     on audio, and wrote it out as the run's name.

Every threshold here is chosen so the guard ABSTAINS rather than misfires — a
gate that fails a healthy run is worse than the hole it closes — and the tests
below pin the abstentions as hard as the catches.

Run:  pytest tests/test_topic_guard_and_never_grew.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

# The incident, verbatim.
TOPIC = ("NemoClaw vs NemoHermes vs Nemotron and also about OpenShell and how "
         "all of these can be used for security")
GOLDEN = ("Golden Retriever: Evidence-Based Global Breed, Health, Welfare, and "
          "Ownership Report. Primary geographic scope: Canada, United States, "
          "United Kingdom. ") * 900
NOTEBOOK_TITLE = "Golden Retriever Health, Breeding, and Ownership Evidence"


# ── The anchors ───────────────────────────────────────────────────────────

def test_the_incident_topic_yields_exactly_its_four_distinctive_words():
    assert research.topic_anchors(TOPIC) == [
        "nemoclaw", "nemohermes", "nemotron", "openshell"]


def test_generic_research_vocabulary_is_not_an_anchor():
    """"security" is in this topic and anchors nothing — a golden-retriever
    welfare report could plausibly use it. Anchors have to be words the subject
    cannot avoid."""
    a = research.topic_anchors(TOPIC)
    for generic in ("security", "research", "about", "these", "used"):
        assert generic not in a


@pytest.mark.parametrize("topic", [
    "best practices for team retrospectives",
    "the current state of the market",
    "a comparison of different approaches",
    "recent trends in technology",
    "",
])
def test_a_topic_with_no_distinctive_vocabulary_is_not_guardable(topic):
    assert len(research.topic_anchors(topic)) < research._TOPIC_GUARD_MIN_ANCHORS


def test_anchors_are_deduplicated_and_ordered():
    a = research.topic_anchors("Nemotron and Nemotron and NEMOTRON plus OpenShell")
    assert a == ["nemotron", "openshell"]


@pytest.mark.parametrize("connector", [
    "plus", "versus", "alongside", "together", "whether", "rather", "instead",
])
def test_a_connector_never_becomes_an_anchor(connector):
    """⚠ An over-inclusive anchor set does not make the guard stricter — it makes
    it UNFIREABLE. The gate trips only when ZERO anchors appear, so one word that
    shows up in arbitrary prose is enough for any document to pass. This is the
    direction the guard fails silently in, so it gets its own test."""
    # Three real anchors, so the topic is guardable and the connector is the
    # only thing under test (two anchors would abstain, hiding the point).
    topic = f"Nemotron {connector} OpenShell {connector} NemoClaw"
    a = research.topic_anchors(topic)
    assert connector not in a
    assert a == ["nemotron", "openshell", "nemoclaw"]
    # …and the guard still catches the incident document with that phrasing.
    assert research.text_is_off_topic(GOLDEN, topic) is True


# ── The gate: catches the incident, abstains on everything else ───────────

def test_the_incident_document_is_off_topic():
    assert len(GOLDEN) > research._TOPIC_GUARD_MIN_CHARS
    assert research.text_is_off_topic(GOLDEN, TOPIC) is True


def test_a_document_that_mentions_the_subject_is_not_off_topic():
    ok = "NemoClaw and Nemotron compared for security hardening. " * 900
    assert research.text_is_off_topic(ok, TOPIC) is False


def test_one_anchor_anywhere_in_the_document_is_enough():
    """Deliberately generous. A report that discusses the subject cannot score
    zero, and anything short of zero has an innocent explanation."""
    doc = GOLDEN + "\n\nAppendix: see also OpenShell."
    assert research.text_is_off_topic(doc, TOPIC) is False


def test_matching_is_substring_so_inflections_and_versions_count():
    for variant in ("Nemotron-4", "NemoClaw's", "OpenShelling", "NEMOHERMES"):
        doc = f"A report discussing {variant} at length. " * 900
        assert research.text_is_off_topic(doc, TOPIC) is False, variant


def test_a_short_partial_is_never_judged():
    """A truncated extraction is the shape most likely to be innocent, and it
    is exactly what a mid-generation harvest produces."""
    assert len(GOLDEN[:5000]) < research._TOPIC_GUARD_MIN_CHARS
    assert research.text_is_off_topic(GOLDEN[:5000], TOPIC) is False


def test_a_vocabulary_free_topic_abstains_even_on_wildly_wrong_text():
    assert research.text_is_off_topic(GOLDEN, "best practices for retrospectives") is False


# ids= is NOT cosmetic here. Without it pytest derives the case id from the
# VALUE, and GOLDEN is a full document -- the id ran past 32,767 characters,
# which is the hard ceiling Windows puts on a single environment variable. pytest
# exports the current id as PYTEST_CURRENT_TEST, so every one of these cases
# died in setup AND teardown with a ValueError that named the env var and never
# mentioned the id. Naming the cases keeps the inputs identical and makes the
# failure output readable on every platform.
@pytest.mark.parametrize("text,topic", [
    ("", TOPIC),
    (None, TOPIC),
    (GOLDEN, ""),
    (GOLDEN, None),
], ids=["empty-text", "text-is-None", "empty-topic", "topic-is-None"])
def test_missing_inputs_abstain(text, topic):
    assert research.text_is_off_topic(text, topic) is False


def test_the_length_floor_is_high_enough_to_exclude_a_partial_but_below_the_incident():
    assert research._TOPIC_GUARD_MIN_CHARS < 121_081, (
        "the floor must sit below the size of the document that shipped"
    )
    assert research._TOPIC_GUARD_MIN_CHARS >= 10_000, (
        "too low a floor starts judging partial extractions"
    )


# ── Reading the topic off disk ────────────────────────────────────────────

def test_the_topic_is_read_from_meta_first(tmp_path):
    d = tmp_path / "Some_Dir_20260805_064715"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"topic": TOPIC}), encoding="utf-8")
    (d / "checkpoint.json").write_text(json.dumps({"topic": "wrong"}), encoding="utf-8")
    assert research._run_topic_for_guard(d) == TOPIC


def test_the_topic_falls_back_to_the_checkpoint(tmp_path):
    d = tmp_path / "Some_Dir_20260805_064715"
    d.mkdir()
    (d / "checkpoint.json").write_text(json.dumps({"topic": TOPIC}), encoding="utf-8")
    assert research._run_topic_for_guard(d) == TOPIC


def test_the_topic_falls_back_to_the_directory_name(tmp_path):
    d = tmp_path / "NemoClaw_vs_Nemotron_and_OpenShell_20260805_064715"
    d.mkdir()
    got = research._run_topic_for_guard(d)
    assert "NemoClaw" in got and "OpenShell" in got
    # …and that fallback is still enough to build a usable anchor set.
    assert len(research.topic_anchors(got)) >= research._TOPIC_GUARD_MIN_ANCHORS


def test_corrupt_metadata_does_not_raise(tmp_path):
    d = tmp_path / "Topic_Here_20260805_064715"
    d.mkdir()
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert research._run_topic_for_guard(d) == "Topic Here"


def test_a_bad_queue_dir_abstains():
    assert research._run_topic_for_guard(None) == ""


# ── Wired in at the save site, BEFORE the write ───────────────────────────

EXTRACT_SRC = code_only(research.extract_and_record_agent)


# ⭐ 2026-08-05 — the decision MOVED into `reject_off_topic_text`, because the
# inline version below covered exactly one of the three paths that reach
# documents/<agent>.md and the run shipped 121KB about golden retrievers through
# the other two. These tests follow it: the call site is checked for ORDER and for
# taking the return value, and the decision itself is checked where it now lives.
GUARD_SRC = code_only(research.reject_off_topic_text)


def test_the_guard_runs_before_the_markdown_is_written():
    """Bolting it on where the conversation URL is read further down would be
    too late — the markdown save and the Firestore mirror both happen above it."""
    assert EXTRACT_SRC.index("reject_off_topic_text(") < EXTRACT_SRC.index(
        '(documents_dir / fname).write_text')


def test_the_call_site_takes_the_guard_s_RETURN_VALUE():
    """⭐ The mutation that now silently disables the guard is dropping the
    assignment: `reject_off_topic_text(text, …)` still logs, still emits, and still
    leaves `text` untouched. A presence check passes against it."""
    i = EXTRACT_SRC.index("reject_off_topic_text(")
    line_start = EXTRACT_SRC.rindex("\n", 0, i) + 1
    stmt = EXTRACT_SRC[line_start:i]
    assert stmt.strip() == "text =", (
        f"the guard's result must be assigned back to `text`, got {stmt.strip()!r}")


def test_the_guard_itself_is_REACHABLE():
    """⚠ Ordering assertions find strings, not execution. A mutant that changed the
    entry condition to `if False:` (or inverted the early return) left every string
    in place — and every ordering test passed against a guard that could never run.
    """
    # The abstain gate must still depend on there BEING text and a run directory.
    entry = GUARD_SRC[:GUARD_SRC.index("topic = _run_topic_for_guard(queue_dir)")]
    assert "if not text or not queue_dir:" in entry, entry
    assert "False" not in entry and "True" not in entry, entry
    # And the decision must be a call to the predicate, not a constant.
    decision = GUARD_SRC[GUARD_SRC.index("topic = _run_topic_for_guard(queue_dir)"):
                         GUARD_SRC.index("anchors = topic_anchors(")]
    assert "text_is_off_topic(text, topic)" in decision, decision
    assert "False" not in decision and "True" not in decision, decision


def test_the_guard_runs_before_n_chars_is_taken():
    """`n_chars` is what decides status=done, so clearing `text` after it would
    fail the leg and still report the size of what it rejected."""
    assert EXTRACT_SRC.index("reject_off_topic_text(") < EXTRACT_SRC.index(
        "n_chars = len(text)")


def test_a_rejection_clears_the_text_rather_than_logging_a_warning():
    """Behavioural now, not a source scan: the helper must RETURN the empty string."""
    import json as _json
    import tempfile as _tempfile
    from pathlib import Path as _Path
    d = _Path(_tempfile.mkdtemp())
    (d / "meta.json").write_text(
        _json.dumps({"topic": "NemoClaw NemoHermes Nemotron OpenShell"}),
        encoding="utf-8")
    off = ("Golden retrievers shed a great deal in spring. "
           * (research._TOPIC_GUARD_MIN_CHARS // 46 + 2))
    assert research.reject_off_topic_text(off, d, "ChatGPT", "chatgpt", op="t") == ""


def test_the_rejection_names_the_terms_it_looked_for():
    branch = GUARD_SRC[GUARD_SRC.index("anchors = topic_anchors("):]
    assert "anchors[:6]" in branch, (
        "the operator needs to see which words were missing, or the rejection "
        "is unreviewable"
    )
    assert "topic_anchors(" in branch


# ── The never-grew veto on ChatGPT's completion verdict ───────────────────

RR_SRC = code_only(research.poll_all_agents_round_robin)


def _completion_region() -> str:
    i = RR_SRC.index("CUA confirms complete")
    return RR_SRC[i:RR_SRC.index('if name == "Gemini" and elapsed <')]


def test_chatgpt_completion_is_now_sanity_checked_like_its_siblings():
    region = _completion_region()
    assert 'name == "ChatGPT"' in region, (
        "ChatGPT was the only agent reaching the extraction with no check on "
        "its own scrape"
    )
    assert 'last_growth_len' in region and 'last_growth_sources' in region


def test_the_veto_requires_literally_never_anything_not_merely_little():
    """⚠ Narrower than Gemini's `< 3 sources / < 2000 chars` ON PURPOSE. ChatGPT
    Deep Research genuinely renders inside surfaces the host-side scrapers can
    miss (the 2026-04-28 cross-origin class), so a LOW count must stay
    acceptable. Only never-anything has no innocent explanation."""
    region = _completion_region()
    assert 'p.get("last_growth_len", 0) == 0' in region
    assert 'p.get("last_growth_sources", 0) == 0' in region
    for loose in ("< 3", "< 2000", "< 100", "<= 0"):
        assert loose not in region, (
            f"a threshold ({loose}) re-opens the cross-origin false-positive class"
        )


def test_the_veto_does_not_extract_on_either_pass():
    region = _completion_region()
    assert region.count("continue") >= 2, (
        "both the first refusal and the escalation must skip the extraction"
    )
    assert "extract_and_record_agent" not in region


def test_the_second_veto_raises_a_card_rather_than_looping_forever():
    """⚠ A counter that is never READ is not a bound. A mutant turning the
    `<= 1` test into `if True:` left the counter, the fail_agent and the park all
    present — and this test passed against a refusal that loops forever. Pin the
    comparison itself."""
    region = _completion_region()
    assert "never_grew_vetoes" in region, "no counter — the refusal could loop"
    assert 'p["never_grew_vetoes"] <= 1:' in region, (
        "the counter is incremented but never compared — the escalation branch "
        "is unreachable and no card is ever raised"
    )
    # The escalation must live on the ELSE side of that bound.
    tail = region[region.index('p["never_grew_vetoes"] <= 1:'):]
    assert 'fail_agent(' in tail and '"kind": "agent_error"' in tail


def test_the_veto_card_honours_the_auto_skip_setting():
    """Every sibling park does. A card showing a countdown to a fire the user's
    setting says cannot happen is the 2026-08-02 defect."""
    region = _completion_region()
    assert "unacted_window_sec(_runtime.auto_skip_stuck)" in region


def test_the_veto_voids_the_stale_completion_signals_before_parking():
    """A leftover done_count makes the loop-top Retry consumer log "the agent
    already completed", retract the card, and restart nothing."""
    region = _completion_region()
    assert "void_completion_signals(p)" in region


# ── The arbiter's bounds ──────────────────────────────────────────────────

def _arbiter_working_branch() -> str:
    i = RR_SRC.index("CUA arbiter: WORKING")
    return RR_SRC[i - 900:i + 1600]


def test_a_never_grew_leg_does_not_get_its_growth_clock_rewound():
    branch = _arbiter_working_branch()
    assert "_never_grew" in branch, (
        '"stopped growing" and "never grew once" are different failures'
    )
    assert 'p["last_growth_time"] = time.time()' in branch
    # …and the rewind is now conditional rather than unconditional.
    assert "if _reset_ok:" in branch


def test_the_number_of_arbiter_granted_extensions_is_bounded():
    """⚠ The constant's NAME also appears in this branch's log line, so a
    presence assertion passed against a mutant that raised the bound to 10,000.
    Pin the comparison expression."""
    branch = _arbiter_working_branch()
    assert "p[\"arbiter_working_resets\"] <= _ARBITER_MAX_WORKING_RESETS" in branch, (
        "each WORKING verdict buys another full window; unbounded, a model that "
        "keeps saying working holds a dead leg open indefinitely"
    )
    assert 'p["arbiter_working_resets"] = p.get("arbiter_working_resets", 0) + 1' in branch, (
        "nothing increments the counter, so the bound can never be reached"
    )


def test_the_cap_is_small_enough_to_matter_and_big_enough_to_be_safe():
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("_ARBITER_MAX_WORKING_RESETS = ")
    assert '"2"' in src[i:i + 120], (
        "two extensions covers the cross-origin false-positive class the branch "
        "exists for without letting a dead leg run to the wall clock"
    )


def test_the_arbiters_own_reasoning_is_logged():
    """It named the wrong topic out loud twice and the only bit extracted was
    the word "working" — the text existed solely in the narrator stream, which
    is part of why the run took a forensic pass to read back.

    ⚠ Assert the log is REACHED, not merely written. A mutant changing its
    `if _sp_text:` to `if False:` left the log statement in place and passed the
    first version of this test."""
    branch = _arbiter_working_branch()
    assert "if _sp_text:" in branch, (
        "the arbiter's reasoning is logged behind a condition that can never be "
        "true — the text is discarded again"
    )
    tail = branch[branch.index("if _sp_text:"):]
    assert "log(" in tail[:200] and "_sp_text[:" in tail[:200]


def test_a_leg_that_grew_then_stalled_still_gets_its_reset():
    """The 2026-04-28 cross-origin class must stay protected — this fix must not
    turn a legitimate scraper blind spot into a failed run."""
    branch = _arbiter_working_branch()
    assert "not _never_grew" in branch, (
        "the veto must key on never-grew, not on flatness in general"
    )


# ── The title tripwire ────────────────────────────────────────────────────

TITLE_SRC = code_only(research._refresh_research_title_async)


def test_the_generated_title_is_checked_against_the_topic():
    assert "title_refusal_verdict(" in TITLE_SRC, (
        "our own findings-based titler had the answer and wrote it out as the "
        "run's name"
    )


def test_the_check_runs_before_the_firestore_write():
    assert TITLE_SRC.index("title_refusal_verdict(") < TITLE_SRC.index(
        '_update_firestore_research({"title"')


def test_a_drifted_title_is_refused_not_merely_logged():
    tail = TITLE_SRC[TITLE_SRC.index("title_refusal_verdict("):]
    branch = tail[:tail.index('_update_firestore_research({"title"')]
    assert 'text = ""' in branch, (
        "refusing the write keeps the title derived from the user's own input"
    )


def test_the_operator_is_told_before_phase_three_spends_the_audio_time():
    """2026-08-06: REWRITTEN. This used to assert only that the emit was PRESENT
    somewhere in the refusal branch, and that is precisely what pinned the bug —
    the emit was unconditional, so a title-only mismatch on a perfectly on-topic
    corpus raised a card, on a phase already marked Complete, carrying a Skip
    that had nothing to skip. The operator must still be told when the CORPUS is
    off-topic; the assertion is now about which branch the emit sits in."""
    assert research.title_refusal_verdict(
        NOTEBOOK_TITLE, TOPIC, "golden retriever " * 3000) == "refuse_loud"
    tail = TITLE_SRC[TITLE_SRC.index('"refuse_loud"'):]
    branch = tail[:tail.index("else:")]
    assert "emit_event(" in branch and "pipeline_warning" in branch, (
        "the loud path is the corpus-also-failed path — that is the shape with "
        "no innocent explanation, and it is what this guard was built for"
    )


def test_a_title_only_mismatch_raises_nothing(monkeypatch):
    """The owner's finding, as a behaviour. The corpus is plainly on topic; the
    title is a vendor-level summary of it. Nothing for a human to do."""
    assert research.title_refusal_verdict(
        "NVIDIA Agent Stack Architecture And Security Boundaries",
        TOPIC,
        ("Nemotron and NemoClaw deployment notes. " * 800)) == "refuse_silent"


def test_the_title_check_honours_the_same_abstain_rule():
    """A title is far too short for the length floor, so the anchor test is
    applied directly — but the minimum-anchors rule still has to hold, or an
    unguardable topic starts refusing perfectly good titles.

    2026-08-06: asserted by EXECUTION now that the decision is a function. The
    old source-shape check would have passed against a constant that was merely
    mentioned."""
    assert research.title_refusal_verdict(
        "Some Entirely Unrelated Title",
        "best practices for team retrospectives",
        "x" * 30_000) == "accept"


def test_the_incident_title_would_have_been_refused():
    anchors = research.topic_anchors(TOPIC)
    assert not any(a in NOTEBOOK_TITLE.lower() for a in anchors)


def test_a_good_title_is_still_accepted():
    anchors = research.topic_anchors(TOPIC)
    assert any(a in "NemoClaw vs Nemotron Security Comparison".lower() for a in anchors)
