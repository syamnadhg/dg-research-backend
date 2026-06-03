"""#767 — repair of the NotebookLM duplicate-audio DETECTOR counters.

The dup-guard counters (_count_nlm_audio_cards / _check_audio_complete_dom /
_count_nlm_deep_dive_cards) used guessed CSS selectors
([role=article]/[class*=audio-card]/[data-testid*=audio] + an <audio> element +
[role=progressbar]) that matched NOTHING in the live NLM Studio panel — every
count read 0, so the pre-flight / post-generate / mid-poll fail_phase dup-guards
were dead no-ops. The #757-B dom-dump (2026-06-03) pinned the real markup: a
generated audio is an <artifact-library-item> carrying the "audio_magic_eraser"
icon ligature; the in-flight state is a "Generating Audio Overview…" placeholder
in .artifact-library-container with no item yet. This locks the repair to that
markup AND the hard no-delete safety (the auto-delete cleanup must stay
uncalled).

Source-inspection guards (the JS lives inline in async page.evaluate bodies),
matching the suite convention. Run:
  pytest tests/test_nlm_detector_repair_767.py -v
"""
import inspect

import research


def _src(fn):
    return inspect.getsource(fn)


# ── The repaired detectors anchor on the REAL markup ────────────────────────

def test_count_audio_cards_uses_artifact_library_item():
    src = _src(research._count_nlm_audio_cards)
    assert "artifact-library-item" in src, (
        "_count_nlm_audio_cards no longer scopes to <artifact-library-item> — "
        "the real NLM audio card element"
    )
    assert "audio_magic_eraser" in src, (
        "the audio-only filter (audio_magic_eraser icon ligature) is gone — it "
        "distinguishes audio from study-guide/mind-map artifact items"
    )


def test_dead_selectors_removed_from_audio_count():
    src = _src(research._count_nlm_audio_cards)
    for dead in ('[class*="audio-card"]', '[data-testid*="audio"]',
                 '[data-testid*="overview-item"]'):
        assert dead not in src, (
            f"the dead selector {dead!r} (matched nothing live) is still in "
            f"_count_nlm_audio_cards"
        )


def test_complete_dom_drops_nonexistent_audio_and_progressbar_gates():
    src = _src(research._check_audio_complete_dom)
    # The panel has NO <audio> element and NO [role=progressbar] — gating on
    # them made DOM-complete unreachable. The repair keys off the artifact item
    # + absence of the "Generating Audio Overview" placeholder instead.
    assert "querySelector('audio')" not in src and 'querySelector("audio")' not in src, (
        "_check_audio_complete_dom still gates on a nonexistent <audio> element"
    )
    assert "role=\"progressbar\"" not in src and "role='progressbar'" not in src, (
        "_check_audio_complete_dom still gates on a nonexistent [role=progressbar]"
    )
    assert "artifact-library-item" in src and "audio_magic_eraser" in src, (
        "_check_audio_complete_dom no longer detects the real audio card"
    )
    assert "generating audio overview" in src.lower(), (
        "_check_audio_complete_dom must treat the 'Generating Audio Overview' "
        "placeholder as still-in-flight"
    )


def test_deep_dive_count_in_lockstep_with_new_markup():
    src = _src(research._count_nlm_deep_dive_cards)
    assert "artifact-library-item" in src and "audio_magic_eraser" in src, (
        "_count_nlm_deep_dive_cards drifted off the repaired markup"
    )
    assert "deep dive" in src.lower(), "the deep-dive text filter is gone"


def test_post_cleanup_invariant_is_total_count_only():
    # dd_count is unreliable in the new markup (the title no longer says "Deep
    # Dive"), so the invariant must NOT gate on it — only total_count == 1.
    p3 = _src(research.run_phase3_audio)
    assert "_ok = (total_count == 1)" in p3, (
        "the post-cleanup invariant should be total-count-only (#767) — gating "
        "on dd_count would WARN on every healthy long run"
    )
    assert "dd_count == 1 and total_count == 1" not in p3, (
        "the old dd_count-based invariant is still present"
    )


# ── No-delete safety: the active deleter must stay uncalled ─────────────────

def test_active_deleter_is_not_called_in_phase3():
    p3 = _src(research.run_phase3_audio)
    assert "await _cleanup_nlm_keep_requested_audio(" not in p3, (
        "the auto-delete cleanup is CALLED again — it clicks Delete on cards, "
        "violating the hard NotebookLM no-delete constraint. Duplicate handling "
        "must be detect-and-fail_phase only."
    )


def test_dup_guards_fail_phase_never_delete():
    # The three dup-count guards must surface via fail_phase, not delete.
    p3 = _src(research.run_phase3_audio)
    assert "existing_cards >= 2" in p3 and "post_gen_cards > 1" in p3 and "_live_cards > 1" in p3, (
        "a dup-count fail_phase guard (pre-flight / post-generate / mid-poll) is missing"
    )
