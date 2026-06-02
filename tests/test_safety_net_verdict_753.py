"""#753 — the REAL root cause behind the recurring P1 "no brief generated"
false-alarm (worker-1 05:05/06:31/09:10 + worker-2 05:07/06:34/09:08).

The brief was NEVER an extraction problem — ChatGPT wedged on "Finalizing
answer" (a ~185-char summary, live Stop button) and the safety-net WRONGLY ruled
the response "complete ✓", so the pipeline extracted an in-flight brief → 0
chars → false failure. The safety-net CUA prompt says "if a Stop button is
visible anywhere, say 'still generating'", and the CUA obeyed ("Stop button:
Yes"), but the inline parse checked `if "response complete" in text` FIRST and
matched the phrase the model echoed from the instruction / used in a negated
clause. (Its Stop-button fallback was also inverted — it looked for 'yes'
BEFORE 'stop', never catching "Stop button: Yes".)

Fix: _classify_completion_verdict — generating signals (affirmed Stop button,
'finalizing', 'still generating', loading) WIN over a bare "response complete"
substring; ambiguous defaults to "generating" (cost asymmetry: false-complete
wrecks the run, false-generating just keeps polling, bounded by the stall
surface). This is a pure function, so these are real functional tests.

Run:  pytest tests/test_safety_net_verdict_753.py -v
"""
import research


def _v(text):
    return research._classify_completion_verdict(text)


# ── The exact bug: Stop button affirmed + "response complete" echoed/negated ──
def test_stop_button_yes_with_echoed_complete_is_generating():
    # Reproduces backend.log 09:10:50 — CUA saw a Stop button (still generating)
    # but the verdict text also contained "response complete" from the prompt.
    txt = ("1. **Stop button**: Yes — there is a solid square icon in the "
           "bottom-right of the composer. Per the rule I should only say "
           "response complete if there is NO stop button.")
    assert _v(txt) == "generating"


def test_finalizing_answer_is_generating():
    # The wedge state the CUA reported at 09:11-09:12.
    assert _v("The page still shows 'Finalizing answer' and the final "
              "artifact has not appeared yet.") == "generating"


def test_negated_complete_is_generating():
    assert _v("I would NOT say the response is complete — it's still working.") == "generating"


def test_stop_button_yes_short_form():
    assert _v("Stop button: Yes. Loading animation: Yes.") == "generating"


# ── Genuine completion must still read complete (don't over-correct) ──────────
def test_genuine_complete_no_stop_button():
    assert _v("Stop button: No. The final paragraph of the response is "
              "visible. Response complete.") == "complete"


def test_stale_dom_stop_but_visually_complete_is_complete():
    # The safety-net's ORIGINAL purpose: DOM says generating but the screen is
    # visually done (no stop button) — must still resolve complete.
    assert _v("There is no stop button visible. The response is fully "
              "rendered, completed: yes.") == "complete"


def test_response_visible_phrase_is_complete():
    # "response visible" is an explicit complete signal the CUA can emit.
    assert _v("No stop button anywhere. Response visible, final paragraph shown.") == "complete"


def test_paraphrased_done_without_keyphrase_stays_generating():
    # Conservative by design: the CUA prompt instructs the literal phrase
    # "response complete"; if the model only paraphrases ("looks done") with no
    # clear complete signal, we keep waiting rather than risk extracting an
    # in-flight brief. A real complete in the wild carries the instructed phrase
    # (see the two tests above). False-generating is the safe error here.
    assert _v("Looks done to me, the text seems all there.") == "generating"


# ── Ambiguous / empty → keep waiting (never early-exit on a fuzzy read) ───────
def test_ambiguous_defaults_to_generating():
    assert _v("I'm not sure what state this is in.") == "generating"


def test_empty_defaults_to_generating():
    assert _v("") == "generating"
    assert _v(None) == "generating"


# ── Hardening edge cases (review r1/r2) ───────────────────────────────────────
def test_adjacent_clause_yes_does_not_affirm_stop():
    # "Stop button: No. Is complete: yes." — the 'yes' answers a LATER clause;
    # clause-scoped _affirmed must NOT read it as an affirmed stop button.
    assert _v("Stop button: No. Is complete: yes.") == "complete"


def test_stop_not_visible_then_complete():
    assert _v("Stop button: not visible. Yes, response complete.") == "complete"


def test_hedged_stop_with_echoed_complete_is_generating():
    # A hedge ("might be... cannot tell") must bias to generating even if the
    # verdict also contains "response complete" (cost asymmetry).
    assert _v("There might be a stop button but I cannot tell. "
              "Response complete.") == "generating"


def test_not_yet_completed_is_generating():
    assert _v("No stop button visible but the answer is not yet completed.") == "generating"


def test_completed_declarative_is_complete():
    assert _v("No stop button. The response has completed rendering.") == "complete"


# ── Guard: the 20-min stall surface stays reachable (timer decouple) ──────────
def test_generating_does_not_reset_stall_window():
    # #753 review (major): a confirmed-"generating" safety-net verdict must NOT
    # reset stall_window_start (the stall surface reads it) — else the 20-min
    # _BriefStreamStalled card is unreachable on a persistent wedge. It must
    # re-arm on its own cadence var instead.
    import inspect
    src = inspect.getsource(research.poll_until_done)
    # Scope precisely to the generating branch (ends at the Stall-surface block).
    gen_branch = src.split("Safety-net CUA confirms still generating", 1)[1].split("Stall surface", 1)[0]
    assert "stall_window_start = time.time()" not in gen_branch, (
        "the generating branch resets stall_window_start again — that makes the "
        "20-min stall card unreachable on a wedge (#753 regression)"
    )
    assert "_safety_net_next_check" in gen_branch, (
        "safety-net re-arm no longer uses its decoupled cadence timer"
    )


# ── Guard: the safety-net wires the helper in (no stray inline parse) ─────────
def test_safety_net_uses_the_classifier():
    import inspect
    src = inspect.getsource(research.poll_until_done)
    assert "_classify_completion_verdict(_sn_text)" in src, (
        "the safety-net no longer routes its verdict through the hardened "
        "classifier — the greedy 'response complete' parse may have crept back"
    )
    # And the old inverted Stop-button check must be gone from the safety-net.
    assert '_sn_text.split("stop")' not in src, (
        "the inverted ('yes' before 'stop') Stop-button check is back in the "
        "safety net"
    )
