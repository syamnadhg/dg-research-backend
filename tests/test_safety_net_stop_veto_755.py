"""#755 — the DETERMINISTIC stop-button veto, the actual remaining cause of the
recurring P1 "no brief generated" false-alarm.

LOG-PROVEN root cause (BE restart 12:28, run before it):
  • Every false-fail had `last_seen_len` 185-387 chars + DOM diag
    `stop_composer:Stop answering` (a LIVE "Stop answering" composer button —
    ChatGPT shows it ONLY while streaming and swaps it for Send the instant the
    answer is done) — i.e. ChatGPT wedged on "Finalizing answer".
        worker-1 09:00 (185, generating✓), 09:05 (185, generating✓),
        09:10 (185, COMPLETE❌); worker-2 09:08 (387, COMPLETE❌),
        12:05 (206, COMPLETE❌).
  • Every genuine success had >33K chars via a RESIDUAL css_animation, never a
    stop button: worker-2 06:34 (33024→34631), worker-1 12:13 (68349→75546).

#753 hardened the CUA *text* parse (_classify_completion_verdict), but the
safety-net's final decision still rested ENTIRELY on that fuzzy visual read. When
the CUA's text is clean-but-wrong (no stop/finalizing keyword, just "looks done")
the classifier returns "complete" and the pipeline extracts the in-flight stub →
0 chars → false fail. The CUA was non-deterministic on the IDENTICAL DOM state
(generating at 09:00/09:05, complete at 09:10). The DOM signals
(last_seen_len + the live Stop button) are deterministic and were captured but
never weighed.

The #755 veto: in the safety-net, a CUA "complete" verdict on a response still
below a real brief's floor (`last_seen_len < 2000`) — while the DOM detector is
insisting it's generating (the only reason the safety-net fires) — is the wedge,
never a finished brief. Force "generating", keep polling; the 20-min stall then
surfaces the honest Retry card instead of a 0-char false "no brief". Large
content (the real successes) is untouched.

The veto lives inline in the big async poll_until_done (local _diag_reason /
last_seen_len), so these are source-inspection guards, matching the suite
convention (see test_safety_net_verdict_753.py).

Run:  pytest tests/test_safety_net_stop_veto_755.py -v
"""
import inspect

import research


def _poll_src():
    return inspect.getsource(research.poll_until_done)


def _veto_block():
    # The veto: from its constant to the (pre-existing) complete-return.
    src = _poll_src()
    return src.split("_SAFETY_NET_MIN_BRIEF_LEN = 2000", 1)[1].split(
        "Safety-net CUA confirms response complete", 1)[0]


def test_veto_constant_is_the_accept_gate():
    # The floor is the extract accept gate (2000) — below it + DOM-generating is
    # a streaming wedge, never a done brief.
    assert "_SAFETY_NET_MIN_BRIEF_LEN = 2000" in _poll_src(), (
        "the safety-net brief floor changed from the 2000-char accept gate"
    )


def test_veto_gates_on_tiny_content_while_complete():
    # The veto fires ONLY when the CUA said complete AND content is below the
    # floor — the exact false-fail shape (185-387 chars).
    block = _veto_block()
    assert "if _sn_is_complete and last_seen_len < _SAFETY_NET_MIN_BRIEF_LEN:" in block, (
        "the stop-button veto is no longer gated on (CUA-complete AND sub-floor "
        "content) — the tiny-stub false-complete can return True again"
    )


def test_veto_flips_complete_to_generating():
    # On veto, the verdict becomes 'still generating' so the loop keeps polling
    # (and re-arms / lets the 20-min stall surface), NOT return True.
    block = _veto_block()
    assert "_sn_is_complete = False" in block and "_sn_is_generating = True" in block, (
        "the veto no longer flips the verdict to generating — it must not let a "
        "sub-floor 'complete' fall through to the return-True path"
    )


def test_veto_does_not_touch_large_content():
    # Large responses (the real successes were 33K-68K chars) must still be able
    # to read complete — the guard is a strict `<` floor, so >= floor is exempt.
    block = _veto_block()
    # No clause that would also veto large content (e.g. an unconditional flip).
    assert "last_seen_len <" in block, "the veto isn't bounded by a content floor"
    # The complete-return survives AFTER the veto block (large content reaches it).
    assert "Safety-net CUA confirms response complete" in _poll_src()


def test_veto_logs_the_stop_signal_for_forensics():
    # The veto WARN must record the char count + the DOM reason so a future log
    # read can tell a stop-button wedge from a different sub-floor stall.
    block = _veto_block()
    assert "_hard_stop_signal" in block, "the veto no longer computes the hard stop signal"
    assert 'startswith(("stop_composer", "card_stop", "generic_stop_label"))' in block, (
        "the hard-stop classification no longer keys off the live composer/card/"
        "generic Stop-button diag reasons"
    )
    assert "vetoing the false-complete" in block, "the veto no longer logs a WARN"


def test_diag_reason_initialized_in_scope():
    # _diag_reason must be initialized before the verify-fn branch so the veto
    # never NameErrors when the diag is skipped (non-chatgpt fn) or throws.
    src = _poll_src()
    assert '_diag_reason = ""' in src, (
        "_diag_reason is no longer pre-initialized — the veto can NameError when "
        "the diagnostic is skipped or fails"
    )
    # It's set before the chatgpt diag branch (so the branch can overwrite it).
    head = src.split("if _verify_fn_name == \"verify_chatgpt_generating\":", 1)[0]
    assert '_diag_reason = ""' in head, (
        "_diag_reason init moved below its first use — scope/ordering regression"
    )


def test_veto_preserves_the_753_classifier_and_stall_decouple():
    # The veto is ADDITIVE — it must sit on top of #753 (classifier + the
    # generating branch that does NOT reset stall_window_start), not replace it.
    src = _poll_src()
    assert "_classify_completion_verdict(_sn_text)" in src, (
        "#753 classifier was dropped — the veto must layer on top of it"
    )
    gen_branch = src.split("Safety-net CUA confirms still generating", 1)[1].split(
        "Stall surface", 1)[0]
    assert "stall_window_start = time.time()" not in gen_branch, (
        "#753 timer-decouple regressed — the generating branch resets the stall "
        "window again, making the 20-min stall card unreachable on a wedge"
    )
