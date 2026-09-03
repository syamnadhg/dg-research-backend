"""The architecture doc, checked against the code it describes.

⛔⛔ THE DOCUMENT DID NOT LAG THE CODE, IT CONTRADICTED IT — stretch 7.5 step 6,
2026-09-03. Its "Agent Link Gate" section stated that a Phase 2 agent is done
only once a shareable link passes `validate_link`. That is not the gate; and the
validator table has no entry for `chatgpt`, `gemini` or `claude`, so it answers
False for all three, always. **Anyone restoring the documented behaviour would
ship a pipeline in which no research agent ever completes.** Ten more rows, a
changelog entry and every line-number citation were wrong too.

⭐⭐ SO THIS FILE DOES NOT PIN PROSE. Asserting the doc's sentences would only
prove nobody had retyped them. Each test below asserts the CODE FACT the
corrected row now states, so the doc and the code fail together when either
moves — and adds a doc-side check only where a false claim would otherwise be
free to come back.

⚠ Two rules this file enforces that are cheap and hold forever:
  · no line-number citation may appear in the doc (all sixteen had rotted), and
  · a retired symbol may be named only on a line that marks it retired,
    so a correction can quote what it corrects without re-asserting it.

Run:  pytest tests/test_doc_matches_code_0903.py -v
"""
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect

import research
from conftest import code_only

ROOT = Path(__file__).resolve().parent.parent
ARCH = ROOT / "ARCHITECTURE.md"
SRC = (ROOT / "research.py").read_text(encoding="utf-8")
DOC = ARCH.read_text(encoding="utf-8")
CODE = code_only(SRC)


def live_claims(text: str = DOC) -> str:
    """The doc minus its tombstones.

    ⛔⛔ FIVE TIMES IN ONE SESSION A CORRECTION I WROTE QUOTED THE SENTENCE IT
    WAS RETIRING, AND EACH TIME THE GUARD FOR THAT SENTENCE FAILED ON THE FIX
    ITSELF. Naming the retired claim is the right thing to do — a reader who
    knows only the new sentence cannot tell whether the old one was ever true —
    so the guard has to be the thing that changes, not the wording.

    A line carrying ⛔ is a tombstone: it exists to say something is dead, and it
    is allowed to name the dead. Every absence check runs against the remaining
    lines, which are the doc's live claims.
    """
    return "\n".join(l for l in text.splitlines() if "⛔" not in l)

#: Symbols the doc presented as live that are not. A retired symbol may appear
#: in the doc ONLY on a line that also carries the ⛔ marker — that lets a
#: correction name what it corrects without the next reader mistaking the
#: mention for a live claim.
RETIRED_IN_DOC = (
    "wait_for_agent_decision",
    "await_stuck_decision",
    "await_retry_or_continue",
)


class TestTheGateTheDocGotBackwards:
    """The single most expensive false sentence in either repository."""

    def test_the_completion_gate_reads_no_link(self):
        src = inspect.getsource(research.extract_and_record_agent)
        body = code_only(src)
        assert "if n_chars > 0 and has_anchor and md_saved:" in body
        # ⛔ ABSOLUTE, not relative: the gate must consult no validator and no
        # verification flag, not merely "fewer link terms than before".
        for term in ("validate_link", "_LINK_VALIDATORS", "conversation_url)"):
            assert term not in body.split("if n_chars > 0")[1], term

    def test_the_documented_gate_could_not_have_worked(self):
        """⛔⛔ EXECUTED, NOT READ. This is the fact that makes the doc a trap
        rather than a lag: restoring what it described would complete nothing."""
        for agent in ("chatgpt", "gemini", "claude"):
            assert research.validate_link(agent, "https://chatgpt.com/share/abc") is False
            assert research.validate_link(agent, "https://example.com/x") is False
        # And the reason, so a validator added later fails this loudly rather
        # than silently reviving the documented gate.
        assert set(research._LINK_VALIDATORS) == {"notebooklm", "youtube", "gdocs"}

    def test_the_doc_no_longer_states_the_gate_it_had(self):
        live = live_claims()
        assert "Agent Link Gate (B1)" not in live
        assert "at least 100 chars of research text" not in live
        # The corrected section must say what the real gate is.
        assert "Its markdown is non-empty" in DOC
        assert "The Firestore document write succeeded" in DOC


class TestSymbolsTheDocNamed:
    """A row that names a function is a promise the function is there."""

    def test_the_pause_helper_the_doc_named_has_no_production_caller(self):
        assert hasattr(research, "wait_for_agent_decision")
        calls = len(re.findall(r"(?<!def )wait_for_agent_decision\(", CODE))
        assert calls == 0, f"{calls} production call(s) — the doc's claim would become true"

    def test_the_live_decision_path_exists(self):
        assert hasattr(research.PipelineControls, "poll_agent_decision")
        assert "_resolve_parked_agent_decision" in CODE

    def test_a_coroutine_the_doc_named_never_existed(self):
        assert "await_stuck_decision" not in SRC

    def test_the_retry_helper_belongs_to_phase_3(self):
        callers = re.findall(r"(?<!def )(?<!async def )extract_with_retry\(", CODE)
        assert len(callers) == 1, "one caller — the NotebookLM notebook link"
        # It is the source of all three link_extract* events, so their phase
        # column in the doc follows from this one fact.
        assert "await extract_with_retry(" in CODE

    @pytest.mark.parametrize("symbol", RETIRED_IN_DOC)
    def test_a_retired_symbol_is_named_only_on_a_line_that_retires_it(self, symbol):
        for line in DOC.splitlines():
            if symbol in line:
                assert "⛔" in line, f"{symbol} named as live: {line[:120]}"


class TestTheEventTable:
    def test_a_pause_reason_the_table_listed_is_emitted_nowhere(self):
        assert '"user_pause"' not in SRC
        assert "user_pause" not in live_claims()

    def test_the_table_lists_every_reason_that_is_emitted_and_no_others(self):
        """⛔⛔ THE CORRECTION I WAS HANDED WAS ITSELF WRONG ON TWO ENTRIES, and
        this is the test that caught it: `phase_timeout` is a pipeline_stopped
        reason and `login_interrupt` is a failure kind. Neither pauses anything.
        So the check is a SET, not a membership sweep — a list that is merely
        non-empty is how two invented reasons got as far as a doc row."""
        emitted = set(re.findall(r'request_pause\("([a-z_]+)"\)', CODE))
        assert emitted == {"login_required", "pro_required",
                           "human_verification_required", "cua_unavailable",
                           "agent_link_failed"}
        # A bare `request_pause()` is the ordinary user pause and carries no
        # reason at all — the case the old row invented a name for.
        assert re.search(r"request_pause\(\)", CODE)
        for reason in emitted - {"agent_link_failed"}:
            assert reason in DOC, reason

    def test_the_link_event_carries_our_own_address(self):
        src = inspect.getsource(research.extract_and_record_agent)
        assert "url=_in_app_url" in src
        assert "verified=True, primary=True" in src


class TestThePauseSplitIsWrittenDown:
    """⛔⛔ The omission that could have re-opened the leak."""

    def test_the_two_snapshots_are_different_and_the_doc_says_so(self):
        assert research.PipelineRuntime._SNAPSHOT_LOCAL_ONLY == ("agent_chat_urls",)
        assert hasattr(research.PipelineRuntime, "snapshot_for_app")
        for claim in ("snapshot_for_app", "_SNAPSHOT_LOCAL_ONLY", "reattachment"):
            assert claim in DOC, claim

    def test_the_doc_names_the_helper_that_replaced_the_addresses(self):
        assert "in_app_document_url" in DOC
        assert "redacted_chat_url" in DOC
        assert callable(research.in_app_document_url)
        assert callable(research.redacted_chat_url)


class TestCitationsCannotRotAgain:
    def test_no_line_number_citation_survives(self):
        """All sixteen were wrong. A pointer that rots in silence is worse than
        naming the symbol, so the shape is banned rather than re-anchored."""
        bad = re.findall(r"research\.py:\d+|\.tsx?:\d+|~\d{4,}", DOC)
        assert bad == [], f"line-number citations are banned: {bad[:5]}"

    def test_the_ban_is_stated_where_someone_would_readd_one(self):
        assert "no line numbers in this file" in DOC.lower()


class TestTheChangelogRetractsItsOwnRule:
    def test_the_removed_extractors_are_gone_and_the_entry_says_so(self):
        for symbol in ("extract_share_link_chatgpt", "extract_share_link_gemini",
                       "extract_share_link_claude", "gemini_extractor", "p2_share_extract"):
            assert symbol not in SRC, symbol
        assert "SUPERSEDED ON 2026-08-28 AND THE ENTRY WAS NEVER RETRACTED" in DOC
