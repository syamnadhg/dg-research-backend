"""#757-B capture — read-only NotebookLM Studio-panel DOM dump.

The duplicate-audio DETECTOR counters (_count_nlm_audio_cards /
_check_audio_complete_dom) use guessed selectors that never match live NLM —
every count returns 0, so the post-generate / mid-poll / post-cleanup dup-guards
are dead no-ops. They can't be repaired blind (a wrong selector that matches too
broadly would OVER-count -> a false fail_phase). The fix needs the REAL DOM, so
_dump_nlm_audio_dom(page, ctx) captures the Studio panel — READ-ONLY, never
clicks — at the points where a card MUST exist but the counter read 0:
  (A) post-generate            (in-flight card)
  (B) CUA-complete-dom-missed  (complete card the DOM check missed)
  (C) post-cleanup             (the lone complete + cleaned card)
It must NOT fire on the pre-flight baseline, where 0 is the normal empty-notebook
state. Grep the next E2E for '[#757-B dom-dump' to pin the selectors (task #767).

Source-inspection guards (the helper is a standalone async def; the call sites
live inline in the large run_phase3_audio coroutine), matching the suite
convention. Run:  pytest tests/test_nlm_dom_dump_757b.py -v
"""
import inspect

import research


def _dump_src():
    return inspect.getsource(research._dump_nlm_audio_dom)


def _p3_src():
    return inspect.getsource(research.run_phase3_audio)


# ── The helper ────────────────────────────────────────────────────────────────

def test_helper_exists_and_is_async():
    assert inspect.iscoroutinefunction(research._dump_nlm_audio_dom), (
        "_dump_nlm_audio_dom must be an async read-only DOM-capture helper"
    )


def test_helper_is_read_only_never_acts():
    # The whole point is a SAFE diagnostic — it may only read via page.evaluate,
    # never click / type / press / run a CUA loop (which is how the original
    # duplicate was created in the first place).
    src = _dump_src()
    assert "page.evaluate(" in src, "the dump no longer reads via page.evaluate"
    for forbidden in (".click(", "left_click", "agent_loop", ".press(",
                      ".fill(", ".tap(", ".type(", ".hover("):
        assert forbidden not in src, (
            f"_dump_nlm_audio_dom calls {forbidden!r} — it MUST be read-only "
            f"(an action could re-create the duplicate audio it's meant to detect)"
        )


def test_helper_is_exception_safe():
    # A diagnostic must never break the run — both the evaluate and the log path
    # are guarded.
    src = _dump_src()
    assert "except Exception" in src, "the dump's page.evaluate is no longer guarded"


def test_helper_output_is_bounded_and_warn_logged():
    src = _dump_src()
    assert ">= 6" in src, "the anchor list is no longer capped (output could be unbounded)"
    assert "< 7" in src, "the ancestor chain walk is no longer depth-bounded"
    assert '"WARN"' in src, "the dump must log at WARN so it surfaces in the log"
    assert "[#757-B dom-dump" in src, "the grep-able dump tag is gone"


def test_helper_reports_why_the_current_count_is_zero():
    # The dump records what the CURRENT (broken) selectors match — so the log
    # proves the count==0 cause and gives the markup to fix it.
    src = _dump_src()
    assert "curSelectorMatches" in src, (
        "the dump no longer records the current selectors' match count"
    )
    assert "chain" in src and "anchors" in src, (
        "the dump no longer records the audio card(s) + their ancestor chain — "
        "that chain is what reveals the real container selectors to pin"
    )
    # A keyword anchor is usually a leaf TITLE node, so its OWN subtree holds
    # neither <audio> nor the progress bar — the dump must climb to the nearest
    # ancestor that DOES (cardEl) so a complete card isn't misread as having no
    # audio. cardEl + its state are the load-bearing fields for pinning.
    assert "cardEl" in src and "cardHasAudioEl" in src, (
        "the dump no longer climbs to the card container (cardEl) — the leaf "
        "anchor's hasAudioEl reads false even on a complete card, which misleads "
        "the selector-pinning"
    )


# ── The call sites (inside run_phase3_audio) ───────────────────────────────────

def test_wired_at_all_three_anomalous_zero_sites():
    src = _p3_src()
    assert src.count("_dump_nlm_audio_dom(") >= 3, (
        "expected the dump wired at all three count==0 sites (post-generate, "
        "cua-complete-dom-missed, post-cleanup)"
    )
    for ctx in ('"post-generate"', '"cua-complete-dom-missed"', '"post-cleanup"'):
        assert ctx in src, f"the {ctx} dump call site is missing"


def test_dumps_are_gated_on_the_anomalous_zero_path():
    # Each dump must sit BEHIND its anomalous-count guard, never unconditional.
    src = _p3_src()
    pairs = [
        ("if post_gen_cards == 0:", '_dump_nlm_audio_dom(browser.page, "post-generate")'),
        ("if not dom_complete:", '_dump_nlm_audio_dom(browser.page, "cua-complete-dom-missed")'),
        ("if total_count == 0:", '_dump_nlm_audio_dom(browser.page, "post-cleanup")'),
    ]
    for gate, call in pairs:
        i_gate, i_call = src.find(gate), src.find(call)
        assert -1 < i_gate < i_call, (
            f"the {call} dump is no longer gated by {gate!r} immediately before it"
        )


def test_preflight_baseline_never_dumps():
    # Pre-flight runs on an empty notebook where 0 is CORRECT — dumping there
    # would fire on every healthy run. The pre-flight COUNT/decision block (from
    # the inventory log up to the generate dispatch `if _reuse_existing:`) must
    # never dump. (#778 added a deliberate read-only `customize-open` canary in
    # the GENERATE branch, after the dispatch + behind a once-per-process gate —
    # that is NOT the pre-flight baseline, so the boundary ends at the dispatch.)
    src = _p3_src()
    preflight = src.split("Pre-flight inventory", 1)[1].split("if _reuse_existing:", 1)[0]
    assert "_dump_nlm_audio_dom(" not in preflight, (
        "a DOM dump was added to the pre-flight baseline — it would spam every "
        "healthy run (0 cards is the normal empty-notebook state there)"
    )
