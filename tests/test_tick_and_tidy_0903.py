"""Stretch 7.5 step 6 — the branch that could not succeed, the mirror nobody
read, and the card that named the wrong failure.

⛔⛔ WHAT THIS STEP FOUND THAT THE PLAN DID NOT. The plan listed a dead branch, a
dead mirror and some stale comments. Measuring them turned up one thing a person
actually reads: when Claude finishes without its report, the failure card told
them we could not fetch a link. There is no report link to fetch — since
2026-08-28 the report's link is a page in our own app, minted from text already
in hand — so the sentence sent a person looking for a network fault on a run
whose report was simply missing. The same emit already carried the true sentence
in `lastError`, three lines away.

⭐ WHERE THESE TESTS EXECUTE AND WHERE THEY PIN. `validate_link` is executed, and
it is the whole reason the removed branch was dead. The Flow C hydration loop and
the Claude hard-fail live inside `run_pipeline` and the round-robin poller, which
no test in this repository drives, so those are source pins and say so.

Run:  pytest tests/test_tick_and_tidy_0903.py -v
"""
import inspect
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "research.py").read_text(encoding="utf-8")
CODE = code_only(SRC)


def live_source(text: str = SRC) -> str:
    """The file minus its tombstones.

    ⛔⛔ SIX TIMES IN ONE SESSION A CORRECTION I WROTE QUOTED THE CLAIM IT WAS
    RETIRING, AND EACH TIME THE GUARD FOR THAT CLAIM FAILED ON THE FIX ITSELF.
    The instinct to write "this used to say X, and X was false" is right — a
    reader given only the new sentence cannot tell whether the old one was ever
    believed, which is the difference between a correction and a quiet edit. So
    the guard is what has to change, not the wording.

    A CONTIGUOUS COMMENT BLOCK CONTAINING ⛔ IS A TOMBSTONE and may name the
    dead. Absence checks run against everything else — the file's live claims.

    ⚠ WHY THE BLOCK AND NOT THE LINE. A line-scoped version of this rule was
    tried first and it failed on its own corrections: these tombstones run to a
    dozen lines and the marker sits on the first, so the quoted claim was never
    on an exempt line. The block is still tied to an explicit marker somebody
    had to type, and it ends at the first non-comment line — it cannot be
    stretched over live code.
    """
    out, block = [], []

    def flush():
        if block and not any("⛔" in b for b in block):
            out.extend(block)
        elif block:
            out.extend("" for _ in block)   # keep line count honest
        block.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            block.append(line)
            continue
        flush()
        out.append("" if "⛔" in line else line)
    flush()
    return "\n".join(out)


class TestThePastedBriefBranch:
    """A call that logged two warnings per paste and could never work."""

    def test_the_validator_has_no_answer_for_a_brief(self):
        """⛔ EXECUTED. This is the fact, not the story: every pasted brief took
        the unknown-platform arm."""
        assert "brief" not in research._LINK_VALIDATORS
        for url in ("https://chatgpt.com/share/abc", "https://example.com/brief", ""):
            assert research.validate_link("brief", url) is False

    def test_a_user_pasting_their_own_conversation_would_be_refused_anyway(self):
        """⛔⛔ WHY THE FIX IS NOT A `brief` VALIDATOR. Adding one would put
        somebody else's address back in the slot step 5 made mean 'our own
        page' — and it would STILL refuse the most likely paste, because a
        private conversation address is on the deny list by shape. The obvious
        repair buys nothing and costs the root-cause fix."""
        for convo in ("https://chatgpt.com/c/abc123",
                      "https://claude.ai/chat/abc123",
                      "https://gemini.google.com/app/abc123"):
            assert any(bad in convo for bad in research._BAD_URL_PATTERNS)

    def test_the_dead_call_is_gone_and_no_other_survives(self):
        # pin: the branch lives inside run_pipeline, which no test drives.
        assert 'emit_validated_link(2, "brief"' not in CODE
        # ⭐ ABSOLUTE: no call anywhere may pass a platform the validator lacks.
        for m in re.finditer(r'emit_validated_link\(\s*\d+,\s*"([a-z_]+)"', CODE):
            assert m.group(1) in research._LINK_VALIDATORS, m.group(1)

    def test_the_pasted_link_still_reaches_the_user_through_the_path_that_works(self):
        """⛔ THE LINK WAS NEVER LOST, and that is why removing the call is safe.
        The unconditional append above it is what put the pasted brief in the
        delivered document all along."""
        src = inspect.getsource(research.run_pipeline)
        hydration = src.split("Flow C hydration")[0]
        assert "append_user_source_in_firestore(_kind, _url, _label, phase=3)" in hydration
        # And the user's own link still becomes this run's brief.
        assert 'if _kind == "brief" and not brief_url:' in hydration
        assert "brief_url = _url" in hydration

    def test_the_comment_no_longer_promises_the_three_things_that_do_not_happen(self):
        src = inspect.getsource(research.run_pipeline)
        seg = src.split('if _kind == "brief" and not brief_url:')[1][:2600]
        # ⭐ Corrections PRESENT, not old words ABSENT — the correction quotes
        # what it corrects on purpose, and a fix that defeats its own guard is a
        # trap this session hit five times.
        assert "A CALL THAT COULD" in seg and "NEVER SUCCEED" in seg
        assert "append_user_source_in_firestore" in seg
        assert "NOT A `brief` VALIDATOR" in seg


class TestTheDeliveryMirror:
    """Written once, read never, and served by a local API with no auth."""

    def test_the_brief_is_no_longer_mirrored_into_the_served_file(self):
        assert "update_delivery(brief_url=" not in CODE

    def test_the_checkpoint_write_beside_it_survives(self):
        """⛔ THE TWO LOOKED IDENTICAL AND ONLY ONE WAS DEAD. A resume at phase 5
        reads `brief_url` back off the checkpoint and renders a Research Brief
        row from it; removing that would cost a real link on a real screen."""
        # ⛔⛔ A COUNT, NOT A PRESENCE CHECK, AND MUTATION IS WHAT FOUND THAT.
        # There are TWO of these writes — phase 1 has a file branch and a live
        # branch — so `... in CODE` stayed true after one of them was deleted,
        # and the mutant that deleted the live one survived a green suite. The
        # same shape as the delivery mirror it sits beside is exactly why: two
        # near-identical lines, one safe to remove and one not.
        assert CODE.count("save_checkpoint(queue_dir, 1, topic=topic, brief_url=_in_app_brief_url)") == 2
        assert 'bf_url = cp.get("brief_url", "")' in CODE
        assert '{"label": "Research Brief", "url": bf_url, "verified": True}' in CODE

    def test_the_delivery_file_still_declares_the_slot(self):
        """⚠ DECLARING A SHAPE THIS MODULE NO LONGER FILLS IS HONEST — `doc_url`
        and `email_sent` have been that way since P5 moved to the app. What was
        wrong was filling it with a copy nobody read."""
        assert '"brief_url": "", "research_links": {}' in CODE


class TestTheCardThatNamedTheWrongFailure:
    def test_the_live_card_says_the_report_is_missing(self):
        # pin: the emit sits in the round-robin poller, which no test drives.
        assert '"title": "Claude didn\'t finish its report"' in CODE
        assert "never produced the final report" in CODE

    def test_no_surface_still_blames_a_link(self):
        """⭐ ABSOLUTE AND WHOLE-FILE. Two emits carried this sentence — the live
        one and the orphaned gate's — and correcting only the live one would
        leave the other to re-seed it."""
        for phrase in ("Couldn't get Claude's report link",
                       "couldn't grab its result link",
                       "'s report link"):
            assert phrase not in SRC, phrase

    def test_the_diagnosis_agrees_with_the_detail_the_same_emit_carries(self):
        """The `lastError` on that event was right the whole time."""
        assert "Claude produced its sources but not the full report" in CODE


class TestTheCommentsThatPlantedTheLandmine:
    def test_two_identifiers_the_ladder_named_exist_nowhere_else(self):
        """⛔⛔ THEY WERE ONLY EVER IN THE COMMENT. A header describing a
        five-step ladder named `completed_set` and `extraction_in_progress` as
        the caller's bookkeeping; both had been gone long enough that the file
        contained them nowhere but in that sentence."""
        live = live_source()
        assert "completed_set" not in live
        assert "extraction_in_progress" not in live

    def test_the_emission_ladder_describes_the_steps_that_run(self):
        seg = SRC.split("# ── Per-Agent Extract + Record")[1][:2200]
        assert "emit link_extracted for the report's page IN OUR APP" in seg
        assert "Steps 3 and 4 share one gate" in seg
        # ⭐ The `fallback` key the app's dead branch was waiting for: no emit in
        # this module has ever passed one, so the contract was fiction.
        assert 'fallback="chat_url"' not in SRC
        assert "fallback?" not in live_source(seg)

    def test_the_tick_comment_says_which_half_was_false(self):
        src = inspect.getsource(research.extract_and_record_agent)
        seg = src.split("Step 3 — Markdown-as-primary emit")[1][:1600]
        assert "HALF (a) IS FALSE" in seg
        assert "reads the agent's own document BY TYPE" in seg

    def test_the_orphaned_gate_says_it_is_orphaned(self):
        doc = inspect.getdoc(research.wait_for_agent_decision) or ""
        assert "NOTHING IN PRODUCTION CALLS THIS" in doc
        assert "poll_agent_decision" in doc

    @pytest.mark.parametrize("gone", [
        "parallel share-link worker",
        "best-effort secondary",
        "still propagates to Phase 5",
        "frontend reads this for live links",
        "extract_and_record_agent Step 4b",
    ])
    def test_a_claim_the_code_had_outgrown_is_no_longer_stated(self, gone):
        # ⭐ Against the LIVE lines: each of these is named by the ⛔ comment
        # that retired it, which is the point of writing one.
        assert gone not in live_source(), gone
