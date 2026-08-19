"""Two things the owner saw in one e2e: half-written narration, and a false alarm.

⛔ REPORT 2 (owner, 2026-08-17): "Gemini raised an alert and autoresolved. It's
good that it wasn't a blocker. But raising false alarms is also a bad UX."

    14:04:59 [WARN] [2D] Plan not started after 248s — surfacing early card
    14:04:59 [INFO] [2D] Still waiting for Gemini research plan... (248s / 300s)
    14:05:42 [INFO] [2D] Clicked 'Start research' ✓ → Retracted the card

⭐⭐ The line directly UNDER the alarm is the whole diagnosis: 248s of a 300s
budget. We told the owner Gemini could not start while we ourselves were still
waiting, with 52 seconds of our own patience left. `GEMINI_PLAN_ALERT_SEC` (240)
and the loop's `_start_wait_max_sec` (300) were configured independently, so the
alarm was free to drift in front of the patience it describes.

⛔ REPORT 3 (owner, same run, with a screenshot of the Phase 1 card): "In it you
could see incomplete/meaningless narration lines. All narration lines must be
meaningful. They look half cutoff and doesn't make sense." Five struck-through
rows, verbatim:

    ChatGPT is selecting its
    ChatGPT is launching its deep
    ChatGPT is initializing its extended thinking mode
    check:  No questions/
    Data thinness check: We

⭐⭐ Two mechanisms, both of which the quality gate should have caught and could
not:
  * `len(words) < 5 AND len(s) < 22` — two guards joined by `and`, so neither can
    veto alone. "ChatGPT is selecting its" is 4 words and 24 characters.
  * `_vn_text = (_vision_narration_p2 or "")[:140]` ran BEFORE the gate, so the
    gate was inspecting damage the pipeline had just done. A character count
    cannot know where a word ends.
"""
import inspect

import pytest

import research


def _src():
    with open("research.py", encoding="utf-8") as fh:
        return fh.read()


# ═══ Item 3 — the plan card may not precede our own patience ════════════════

DUE = dict(elapsed=248, wait_max_sec=300, alert_sec=240, regen_capped=False,
           streaming_recent=False, start_clicked=False)


def test_the_exact_false_alarm_the_owner_saw_does_not_fire():
    """⭐⭐ 248s of a 300s budget, zero regens, nothing streaming. The plan
    arrived 25 seconds later."""
    assert research._gemini_plan_card_due(**DUE) is False


def test_it_fires_once_our_own_patience_is_actually_spent():
    assert research._gemini_plan_card_due(**{**DUE, "elapsed": 300}) is True


def test_the_alarm_cannot_be_configured_in_front_of_the_wait():
    """⛔ The defect, generalised: the two numbers were independent, so ANY pair
    where the alert is the smaller one cries wolf. Tying them removes the whole
    class rather than re-tuning it."""
    for alert in (10, 60, 120, 240, 299):
        assert research._gemini_plan_card_due(
            **{**DUE, "alert_sec": alert, "elapsed": 299}) is False, alert


def test_an_explicitly_later_alert_is_still_honoured():
    """`max`, not "always the wait" — an operator who sets the alert LATER than
    the budget is asking for a quieter card, and gets one."""
    assert research._gemini_plan_card_due(
        **{**DUE, "alert_sec": 600, "elapsed": 400}) is False
    assert research._gemini_plan_card_due(
        **{**DUE, "alert_sec": 600, "elapsed": 600}) is True


def test_exhausted_regenerations_still_card_immediately():
    """⭐ #921's whole point: three failed re-drafts is EVIDENCE, not a timer, and
    it must reach the owner early instead of after a 17-minute ladder."""
    assert research._gemini_plan_card_due(
        **{**DUE, "elapsed": 5, "regen_capped": True}) is True


def test_a_visibly_streaming_plan_is_never_carded():
    """#929, preserved: healthy-slow is not failed."""
    assert research._gemini_plan_card_due(
        **{**DUE, "elapsed": 900, "streaming_recent": True}) is False


def test_streaming_outranks_even_the_regeneration_cap():
    """⛔ A plan that is drafting in front of us has recovered, whatever the
    regen history says."""
    assert research._gemini_plan_card_due(
        **{**DUE, "regen_capped": True, "streaming_recent": True}) is False


def test_nothing_is_carded_once_start_was_clicked():
    for extra in ({"regen_capped": True}, {"elapsed": 9999}):
        assert research._gemini_plan_card_due(
            **{**DUE, **extra, "start_clicked": True}) is False, extra


# ── the consumer ────────────────────────────────────────────────────────────

def _p2_src():
    return inspect.getsource(research.run_phase2)


def test_the_card_site_asks_the_helper_rather_than_comparing_numbers():
    body = _p2_src()
    assert "_gemini_plan_card_due(" in body
    assert "_elapsed > _PLAN_ALERT_SEC" not in body


def test_the_timer_arm_is_still_reachable_at_all():
    """⛔⛔ THE TRAP THIS FIX WALKS INTO IF DONE CARELESSLY. The give-up break
    sits ABOVE the card block, so tying the alarm to the wait budget makes the
    timer arm unreachable from the block alone — the card would silently stop
    firing and #921's protection would be gone with no test to notice. It is
    therefore ALSO raised at the break, and that call must come first in source
    order because that is the branch that runs."""
    body = _p2_src()
    at_break = body.index("our own plan-wait budget is spent")
    at_block = body.index("plan clearly failed")
    assert at_break < at_block, "the break-site raise must precede the loop body's"
    assert body.count("_gemini_plan_card_due(") == 2


def test_the_card_is_raised_in_one_place_and_only_once():
    """Two call sites, ONE emitter. The idempotence guard lives inside it, so a
    third site could never double-card either.

    ⚠ `fail_agent("gemini", *_GEMINI_CANT_START)` legitimately appears twice in
    this function — the second is the TERMINAL failure after the CUA ladder,
    which deliberately reuses the same alert id. The early card is the one that
    has to be single-sourced."""
    body = _p2_src()
    raiser = body[body.index("def _raise_plan_alert("):
                  body.index("def _retract_plan_alert(")]
    assert raiser.count('fail_agent("gemini", *_GEMINI_CANT_START)') == 1
    assert "if _plan_alert_emitted or _controls.is_stop():" in raiser
    assert "_plan_alert_emitted = True" in raiser
    # …and the two decision sites raise it rather than emitting their own.
    after = body[body.index("def _retract_plan_alert("):]
    assert after.count("_raise_plan_alert(") == 2
    assert after.count('fail_agent("gemini", *_GEMINI_CANT_START)') == 1


def test_the_card_is_still_non_blocking_and_still_retracted():
    """⛔ The owner was explicit: the non-blocking behaviour was RIGHT. Only the
    crying-wolf part changes."""
    body = _p2_src()
    assert "Retracted the early plan-stall card" in body
    assert "non-blocking, recovery continues" in body


def test_the_alert_second_is_still_operator_settable():
    assert "GEMINI_PLAN_ALERT_SEC" in _src()


# ═══ Item 4 — a narration line is a whole sentence or it is not shown ═══════

# Verbatim from the owner's screenshot of the Phase 1 card.
OWNER_LINES = [
    "ChatGPT is selecting its",
    "ChatGPT is launching its deep",
    "ChatGPT is initializing its extended thinking mode",
    "check:  No questions/",
    "Data thinness check: We",
]


@pytest.mark.parametrize("line", OWNER_LINES)
def test_every_line_the_owner_photographed_is_refused(line):
    """⭐⭐ The whole report, one assertion per line."""
    assert not research._is_acceptable_narration(line), line


@pytest.mark.parametrize("line", OWNER_LINES)
def test_and_none_of_them_survives_the_trim_either(line):
    """The call sites trim BEFORE they judge, so a line that the trim rescued
    would still reach the card. None of these has a sentence in it to rescue."""
    assert research._narration_last_sentence(line) == "", line


def test_the_line_that_read_correctly_still_ships():
    good = "ChatGPT is reasoning through the brief with its latest thinking model."
    assert research._is_acceptable_narration(good)
    assert research._narration_last_sentence(good) == good


def test_a_short_fragment_that_is_long_in_characters_is_caught():
    """⛔ THE `and` THAT LET IT THROUGH. Four words, 24 characters: under the word
    bar, over the character bar, and the two were ANDed so neither could veto."""
    line = "ChatGPT is selecting its"
    assert len(line.split()) < 5 and len(line) > 22
    assert not research._is_acceptable_narration(line)


def test_a_dangling_clause_costs_the_clause_not_the_narration():
    """A model that adds half a thought after a good sentence should lose the
    half-thought — falling all the way through to a template would throw away
    real narration."""
    assert research._narration_last_sentence(
        "Gemini is browsing fresh sources. It is also") == \
        "Gemini is browsing fresh sources."


def test_a_hostname_is_not_the_end_of_a_sentence():
    """⛔ The narrator is TOLD to cite hosts, so 'docs.nvidia.com' is ordinary
    output. A trim that stopped at the first dot would cut every cited line in
    half — manufacturing the exact defect it is here to prevent."""
    line = "Claude is reading docs.nvidia.com and pulling citations."
    assert research._narration_last_sentence(line) == line
    assert research._narration_last_sentence(
        "Claude is reading docs.nvidia.com and pulling") == ""


def test_the_limit_returns_a_whole_sentence_not_a_slice():
    long_line = ("Gemini is browsing fresh sources. " +
                 "It is now weaving the findings into a structured report with citations.")
    got = research._narration_last_sentence(long_line, limit=60)
    assert got == "Gemini is browsing fresh sources."
    assert len(got) <= 60


def test_an_exclamation_ends_a_sentence_too():
    """Rare in narration, but it is the other terminal mark and the trim is the
    only thing standing between a finished line and the template."""
    assert research._narration_last_sentence(
        "Gemini finished its plan in record time!") == \
        "Gemini finished its plan in record time!"


def test_a_question_mark_is_not_a_terminal_mark_here():
    """⛔ The gate refuses questions outright, so treating '?' as the end of a
    sentence would let the trim hand one straight back — a narration channel is
    not a place to ask the owner anything."""
    assert research._narration_last_sentence(
        "Which sources would you like me to read first?") == ""


def test_the_trim_keeps_every_sentence_it_can_not_just_the_first():
    """⛔ Stopping at the first full stop would throw away narration the model
    actually finished — the opposite mistake, and just as lossy."""
    two = ("Gemini is browsing fresh sources. "
           "It is weaving the findings into a structured report.")
    assert research._narration_last_sentence(two) == two
    assert research._narration_last_sentence(two + " It is also") == two


def test_the_limit_can_refuse_rather_than_cut():
    """⛔ If not one whole sentence fits, the answer is nothing. That is the
    difference between this and a slice."""
    assert research._narration_last_sentence(
        "Gemini is weaving the findings into a structured report.", limit=20) == ""


def test_a_question_is_still_refused():
    assert not research._is_acceptable_narration(
        "Could you tell me which sources you would like me to read first?")


def test_refusal_prose_is_still_refused():
    assert not research._is_acceptable_narration(
        "I don't have enough information about the agent's progress right now.")


def test_the_trailing_stopword_list_is_gone():
    """⛔⛔ REMOVED, not widened — and my own test is what settled it. The rule
    guessed a mid-sentence cut from the last word against seventeen prepositions,
    which is a blocklist of an open class: "ChatGPT is launching its deep" ends on
    an ordinary adjective. Widening it to a closed word class was written, and
    then this file's own floor failed the gate — the deterministic phase template
    reads "…verifying every agent is logged in." and 'in' was on the list, so a
    strict-gate + rejected-floor combination would have silenced the card
    entirely. With the complete-sentence rule the list can only fire on lines
    that rule already refused, so it goes."""
    assert not hasattr(research, "_NARR_STOPWORD_TAILS")
    assert "_NARR_STOPWORD_TAILS" not in _src()


@pytest.mark.parametrize("line", [
    "Super Research is in the warmup phase, verifying every agent is logged in.",
    "ChatGPT is reading the retrieved articles and pulling citations from them.",
    "Gemini is weaving the findings into a report the reviewer can act on.",
])
def test_a_finished_sentence_ending_on_a_small_word_is_still_good(line):
    """The regression the removal prevents: 'in', 'them' and 'on' all end these
    sentences perfectly well, and every one was on the widened list."""
    assert research._is_acceptable_narration(line), line


# ── the sites that truncate ─────────────────────────────────────────────────

def test_the_vision_narration_is_shortened_by_sentence_not_by_slice():
    """⛔⛔ `[:140]` ran BEFORE the quality gate, so the gate could only ever
    inspect a fragment the pipeline had just manufactured."""
    body = inspect.getsource(research.poll_all_agents_round_robin)
    assert '(_vision_narration_p2 or "")[:140]' not in body
    assert "_narration_last_sentence(_vision_narration_p2, limit=140)" in body


def test_both_narrator_emit_sites_trim_before_they_judge():
    """The phase line and the per-agent line. A trim that ran AFTER the gate
    would rescue nothing — the gate would already have replaced the text with a
    template."""
    loop = inspect.getsource(research._narrator_loop)
    assert loop.count("_narration_last_sentence(") == 2, loop.count(
        "_narration_last_sentence(")
    at = 0
    for _ in range(2):
        trim = loop.index("_narration_last_sentence(", at)
        gate = loop.index("_is_acceptable_narration(", trim)
        assert trim < gate
        at = trim + 1


def test_a_line_with_no_sentence_reaches_the_gate_rather_than_vanishing():
    """⛔ `or text` is load-bearing. Without it a fragment becomes the empty
    string, both `if text …` arms are skipped, and NOTHING is emitted — the card
    goes silent instead of falling back to the deterministic template, which is
    strictly worse than the fragment we set out to remove."""
    loop = inspect.getsource(research._narrator_loop)
    assert "_narration_last_sentence(text) or text" in loop
    assert "_narration_last_sentence(a_text) or a_text" in loop


def test_the_fallback_template_is_written_with_its_full_stop():
    """⭐ Pinned at the CALL SITE, not by rebuilding the string here — a test that
    composes the sentence itself cannot see the site drop the period, and the
    whole strict-gate change rests on this line passing its own gate."""
    loop = inspect.getsource(research._narrator_loop)
    assert loop.count('f"Super Research is in {_phase_short_label(phase)}."') == 2
    assert 'f"Super Research is in {_phase_short_label(phase)}"' not in loop


def test_the_gate_itself_requires_a_whole_sentence():
    gate = inspect.getsource(research._is_acceptable_narration)
    assert "if not _narration_last_sentence(s):" in gate
    assert "len(words) < 5 or len(s) < 22" in gate


# ── the floor has to survive its own gate ───────────────────────────────────

def test_every_tier4_template_would_pass_the_gate_it_falls_back_to():
    """⭐⭐ THE CROSS-CHECK THAT MAKES THE WHOLE CHANGE SAFE. Requiring a complete
    sentence is only sound if the deterministic floor IS one — otherwise a strict
    gate would reject Tier-2, then Tier-3, then the template, and the card would
    go silent instead of merely plainer."""
    for (akey, ph), variants in research.AGENT_TIER4_VARIANTS.items():
        for v in variants:
            assert research._is_acceptable_narration(v), (akey, ph, v)


def test_the_generic_tier4_string_also_passes():
    assert research._is_acceptable_narration(research._tier4_template("nobody", 9))


def test_the_phase_template_also_passes():
    for phase in (0, 1, 2, 3, 7):
        line = f"Super Research is in {research._phase_short_label(phase)}."
        assert research._is_acceptable_narration(line), line


def test_the_prompt_now_asks_for_a_complete_sentence():
    """Cheap belt to the braces: the fewer fragments the model emits, the less
    often the card falls back to a template."""
    body = _src()
    assert body.count("Exactly ONE COMPLETE sentence ending in a period.") == 2
    assert "Never stop mid-clause" in body
