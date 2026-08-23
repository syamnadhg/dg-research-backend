"""Wave 7: ONE verdict contract for every verifier.

⛔⛔ THE FINDING. Vision answers are read back out of free prose, and this file
has paid for that four times — an echoed "response complete", a "progress bar"
inside a sentence DENYING it, a hedge that read as still-generating. The fix in
August was a stated-conclusion contract: the model reasons freely, then writes
its answer on its own line, and we read THAT line — anchored to the start of a
line, horizontal whitespace only, last match wins.

It was applied to ONE verifier. The diagnose mission states its answer under
`CONCLUSION:` and was read with an unanchored `re.search` that took the FIRST
match — while its own prompt says "the LAST line of your response must be
exactly one of" and then prints all four legal values, each on its own
`CONCLUSION:` line. A reply that quotes its instructions, or reasons aloud
before deciding, was read as the first item on that menu.

⭐ COST, STATED HONESTLY. `generating` heads both the menu and the no-match
default, so the likeliest misread turns a DONE into one more poll. The one that
is not cheap is `needs_click`, which re-arms the late-Start watch — the verdict
the 90-minute Gemini loss turned on.

⭐ AND THE OTHER TWO VERIFIERS ARE SAFE BY CONSTRUCTION, NOT BY CONTRACT. The
login and plan checks run at `max_tokens=8`: there is no room to reason, so
there is no prose to sniff. That is a second, cheaper way of reaching the same
property — and it is invisible, so this file pins it. Someone "improving" those
calls by allowing the model to think would silently reintroduce the whole class.
"""
import re

import pytest

import research


CONCLUSIONS = ("generating", "done", "needs_click", "error")


# ── the shared reader ────────────────────────────────────────────────────────

class TestTheSharedReader:
    def test_it_reads_a_stated_value(self):
        assert research._last_verdict(
            "VERDICT: complete", research._CUA_VERDICT_LINE) == "complete"

    def test_it_is_case_insensitive(self):
        # A contract that states its values in capitals and a reader that
        # matches lower case agree only by accident.
        assert research._last_verdict(
            "CONCLUSION: DONE", research._CUA_CONCLUSION_LINE) == "done"

    def test_it_ignores_a_value_that_does_not_begin_a_line(self):
        # ⛔ #753, in one assertion. The echo is the defect.
        text = "I would not say VERDICT: complete here.\nVERDICT: generating"
        assert research._last_verdict(text, research._CUA_VERDICT_LINE) == "generating"

    def test_an_echo_alone_yields_nothing(self):
        assert research._last_verdict(
            "the answer would be VERDICT: complete", research._CUA_VERDICT_LINE) == ""

    def test_it_takes_the_last_statement_not_the_first(self):
        # ⭐ The prompts PRINT the whole menu above the answer, so the first
        # match in a reply that quotes its instructions is the first menu item.
        text = "CONCLUSION: generating\nCONCLUSION: done\nCONCLUSION: needs_click"
        assert research._last_verdict(
            text, research._CUA_CONCLUSION_LINE) == "needs_click"

    def test_leading_horizontal_space_is_allowed(self):
        assert research._last_verdict(
            "   \tCONCLUSION: error", research._CUA_CONCLUSION_LINE) == "error"

    def test_a_newline_between_the_field_and_its_value_is_not(self):
        # `\s` would span it and undo the anchoring written beside it.
        assert research._last_verdict(
            "CONCLUSION:\ndone", research._CUA_CONCLUSION_LINE) == ""

    def test_it_accepts_an_equals_sign_as_well_as_a_colon(self):
        assert research._last_verdict(
            "VERDICT = complete", research._CUA_VERDICT_LINE) == "complete"

    def test_it_refuses_a_value_outside_the_vocabulary(self):
        assert research._last_verdict(
            "CONCLUSION: finished", research._CUA_CONCLUSION_LINE) == ""

    def test_it_refuses_a_value_that_merely_starts_with_a_legal_one(self):
        # The `\b` is what stops "doneish" reading as "done".
        assert research._last_verdict(
            "CONCLUSION: doneish", research._CUA_CONCLUSION_LINE) == ""

    def test_empty_and_none_are_answers_it_survives(self):
        assert research._last_verdict("", research._CUA_VERDICT_LINE) == ""
        assert research._last_verdict(None, research._CUA_VERDICT_LINE) == ""

    def test_the_field_may_be_a_regex_fragment(self):
        # `stop_button`, `stop button` and `stop-button` are all written by
        # models, so the field is a fragment rather than a literal.
        for spelling in ("STOP_BUTTON", "stop button", "Stop-Button"):
            assert research._last_verdict(
                f"{spelling}: yes", research._CUA_STOP_LINE) == "yes", spelling


# ── every verifier uses it ───────────────────────────────────────────────────

class TestEveryVerifierSharesOneReader:
    @pytest.mark.parametrize("pattern", [
        "_CUA_VERDICT_LINE", "_CUA_STOP_LINE", "_CUA_CONCLUSION_LINE",
    ])
    def test_each_contract_field_is_built_by_the_shared_factory(self, pattern):
        # ⭐ THE POINT OF THE WAVE. Three fields, one set of properties. A
        # fourth reader hand-rolled beside these is how the diagnose one drifted.
        pat = getattr(research, pattern)
        assert pat.flags & re.M, f"{pattern} is not line-anchored"
        assert pat.flags & re.I, f"{pattern} is case-sensitive"
        assert pat.pattern.startswith("^[^\\S\\n]*"), (
            f"{pattern} does not anchor with horizontal whitespace only")

    def test_the_conclusion_reader_covers_the_prompt_s_whole_vocabulary(self):
        # A value the prompt mandates and the reader cannot see collapses into
        # "none of the above", which the caller reads as keep-waiting. That is
        # exactly how `needs_click` was lost once already.
        import prompts
        for value in CONCLUSIONS:
            assert f"CONCLUSION: {value.upper()}" in prompts.PROMPT_DIAGNOSE, value
            assert research._last_verdict(
                f"conclusion: {value}", research._CUA_CONCLUSION_LINE) == value

    def test_the_diagnose_call_site_reads_the_anchored_line_first(self):
        import inspect
        src = inspect.getsource(research.poll_all_agents_round_robin)
        assert "_last_verdict(diag_text, _CUA_CONCLUSION_LINE)" in src, (
            "the diagnose verdict is not read through the shared reader")

    def test_the_unanchored_search_survives_only_as_a_fallback(self):
        # ⛔ Kept deliberately: no answer that resolves today may resolve
        # differently, including a `CONCLUSION:` split across two lines. But it
        # must run AFTER the anchored read, never instead of it.
        import inspect
        src = inspect.getsource(research.poll_all_agents_round_robin)
        # ⛔ SCOPED TO THIS SEARCH. The first draft looked for any `re.search(`
        # and found an unrelated one 90k characters earlier in the same
        # function — a test that failed for a reason it was not about.
        anchored = src.index("_last_verdict(diag_text, _CUA_CONCLUSION_LINE)")
        loose = src.index(r"conclusion\s*:\s*(generating|done|needs_click|error)")
        assert anchored < loose, "the loose search still runs first"
        assert "if not verdict:" in src[anchored:loose]


# ── the two verifiers that need no contract ──────────────────────────────────

class TestTheOneWordVerifiersAreSafeByConstruction:
    """⭐ Not an omission — a different solution to the same problem.

    `_cua_login_call` and the plan detector cap the model at 8 tokens. A model
    that cannot write prose cannot hide its answer in prose, so a prefix read is
    sound there in a way it would never be on a reasoning reply. That property
    is invisible in the code and would be the first thing an "improvement"
    removed, so it is pinned here.
    """

    @pytest.mark.parametrize("fn", ["_cua_login_call"])
    def test_the_login_check_leaves_no_room_to_reason(self, fn):
        import inspect
        src = inspect.getsource(getattr(research, fn))
        assert "max_tokens=8" in src, (
            f"{fn} no longer caps the reply at one word — a prefix read is only "
            f"sound because the model cannot write prose. Give it a stated "
            f"conclusion line instead.")
        assert "ONLY one word" in src

    def test_the_plan_detector_leaves_no_room_either(self):
        import inspect
        src = inspect.getsource(research._cua_pro_tier_call)
        assert "max_tokens=8" in src, (
            "the plan detector no longer caps the reply at one word")
        assert 'verdict.startswith("pro")' in src
