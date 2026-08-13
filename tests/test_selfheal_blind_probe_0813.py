"""Three observations of a blank page, reported as findings.

WHAT HAPPENED (2026-08-13, first real shadow run)

Self-heal shadow was switched on for one e2e. Eleven observations landed. Six
real platform intents probed live DOM — 3 to 40 elements each, real DOM
fingerprints — and all passed. Then:

    notebooklm.set_public_access   probe_count=0  ui_fingerprint=da39a3ee5e6b
    notebooklm.copy_share_link     probe_count=0  ui_fingerprint=da39a3ee5e6b

`da39a3ee5e6b` is the SHA-1 prefix of the EMPTY STRING. Those records
fingerprinted a blank document and probed nothing at all.

TWO DEFECTS, and the second is why the first mattered.

  1. THE OBSERVATION WAS PLACED WHERE ITS REGION CANNOT EXIST. Both intents
     declare `region: "dialog"`, and both were observed AFTER the Save/Done
     click that dismisses the share dialog. So `probe_region` had nothing to
     walk — not on this run, but on EVERY run, forever. Two intents in the
     watch list could never accumulate a usable sample, which defeats the
     entire point of a shadow-first rollout.

  2. AN EMPTY PROBE WAS INDISTINGUISHABLE FROM OBSERVED BREAKAGE.
     `would_heal` was `not outcome_pass`, full stop — no reference to whether
     anything had been looked at. And the report folded the resolver's
     (inevitable) no-match into the match RATE, which is what the PX-4 drift
     canary derives its verdict from. Result: the report announced **DRIFT** on
     two NotebookLM intents purely because their dialog had closed. A false
     alarm on the one signal whose entire job is early warning, pointing at
     selector rot that does not exist.

This is the same defect the note at the `chatgpt.select_model` observation site
already records — "every sample from it was noise" — and the same lesson as the
2026-08-06 panel audit: A COUNT IS NOT PROOF.

WHAT THESE TESTS PIN

  1. An empty probe is never a would-heal, and says so in its own field.
  2. A real probe that fails IS a would-heal — the fix must not silence drift.
  3. The report separates blind samples, and never grades anything on them.
  4. ⛔ A never-observed intent reads "not observed", never "DRIFT".
  5. The report is correct against logs the OLD observer wrote — a shadow
     rollout accumulates records for weeks, and fixing only the writer would
     leave every already-collected line misreported.
  6. The two dialog-scoped observations happen while the dialog is still open.
"""
import ast
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import research  # noqa: E402
import selfheal_report  # noqa: E402
from conftest import code_only  # noqa: E402

# The empty-string fingerprint, which is what made the blank reads recognisable.
EMPTY_FP = "da39a3ee5e6b"


# ══════════════════════════════════════════════════════════════════════════
# 1. the observer: an empty probe is not a finding
# ══════════════════════════════════════════════════════════════════════════

def _observe(monkeypatch, *, probes, outcome_pass, match_found=False):
    """Run the real `_selfheal_shadow_observe` and capture what it logged."""
    written = []
    sh = research.selfheal
    monkeypatch.setattr(sh, "is_enabled", lambda: True)
    monkeypatch.setattr(sh, "load_intents",
                        lambda: {"x.y": {"platform": "x", "region": "document"}})

    async def _probe(page, region):
        return list(probes)
    monkeypatch.setattr(sh, "probe_region", _probe)
    monkeypatch.setattr(sh, "shadow_heal_decision", lambda snap, intent: {
        "match_found": match_found, "match_confidence": 0.6 if match_found else None,
        "inferred_selector": "button.x" if match_found else None,
        "match_reason": "anchor" if match_found else None,
        "ui_fingerprint": EMPTY_FP if not snap else "925584ec88ee",
    })
    monkeypatch.setattr(sh, "shadow_log", lambda rec: written.append(rec))
    monkeypatch.setattr(sh, "capture_enabled", lambda: False)

    import asyncio
    asyncio.run(research._selfheal_shadow_observe(
        object(), "x.y", outcome_pass=outcome_pass))
    assert written, "nothing was logged"
    return written[-1]


def test_an_empty_probe_is_never_a_would_heal(monkeypatch):
    """⭐ The core fix. The outcome failed, but nothing was looked at — so there
    is no drift to report and no heal to attempt."""
    rec = _observe(monkeypatch, probes=[], outcome_pass=False)
    assert rec["would_heal"] is False
    assert rec["probe_empty"] is True
    assert rec["probe_count"] == 0


def test_a_real_probe_that_fails_is_still_a_would_heal(monkeypatch):
    """⛔ The negative control, and the one that matters most. If this stops
    firing, the fix has not made the signal honest — it has deleted it."""
    rec = _observe(monkeypatch, probes=[{"tag": "button"}], outcome_pass=False)
    assert rec["would_heal"] is True
    assert rec["probe_empty"] is False


def test_a_real_probe_that_passes_is_not_a_would_heal(monkeypatch):
    rec = _observe(monkeypatch, probes=[{"tag": "button"}], outcome_pass=True)
    assert rec["would_heal"] is False
    assert rec["probe_empty"] is False


def test_an_empty_probe_that_passes_is_still_flagged_blind(monkeypatch):
    """A pass on a blank page is not evidence of health either. `probe_empty`
    is about whether anything was OBSERVED, independent of the verdict."""
    rec = _observe(monkeypatch, probes=[], outcome_pass=True)
    assert rec["probe_empty"] is True
    assert rec["would_heal"] is False


# ══════════════════════════════════════════════════════════════════════════
# 2. the report: nothing is graded on a blind sample
# ══════════════════════════════════════════════════════════════════════════

def _rec(intent, *, probes, outcome_pass, would_heal, match, probe_empty=None):
    r = {"intent": intent, "platform": intent.split(".")[0],
         "outcome_pass": outcome_pass, "would_heal": would_heal,
         "probe_count": probes, "resolved_by": "shadow",
         "heal_match_found": match,
         "heal_confidence": 0.6 if match else None,
         "ui_fingerprint": EMPTY_FP if probes == 0 else "925584ec88ee"}
    if probe_empty is not None:
        r["probe_empty"] = probe_empty
    return r


# The exact shape the 2026-08-13 run produced, verbatim: written by the OLD
# observer, so `would_heal` is True on a zero-probe record.
LEGACY_BLIND = [
    _rec("notebooklm.set_public_access", probes=0, outcome_pass=False,
         would_heal=True, match=False),
    _rec("notebooklm.copy_share_link", probes=0, outcome_pass=False,
         would_heal=True, match=False),
]


def test_the_report_counts_blind_samples_separately():
    s = selfheal_report.summarize(LEGACY_BLIND)["per_intent"]
    assert s["notebooklm.set_public_access"]["empty_probe"] == 1
    assert s["notebooklm.set_public_access"]["total"] == 1


def test_the_report_discounts_a_legacy_blind_would_heal():
    """⭐ Correct against logs the OLD observer wrote. A shadow rollout
    accumulates records for weeks — fixing only the writer would leave every
    already-collected line misreported forever."""
    s = selfheal_report.summarize(LEGACY_BLIND)["per_intent"]
    assert s["notebooklm.set_public_access"]["would_heal"] == 0


def test_a_blind_sample_never_reaches_the_match_rate():
    """The resolver's (inevitable) no-match on a blank page was being folded
    into the rate the PX-4 canary grades. It is now its own counter."""
    s = selfheal_report.summarize(LEGACY_BLIND)["per_intent"]
    row = s["notebooklm.set_public_access"]
    assert row["resolver_seen"] == 0
    assert row["resolver_blind"] == 1
    assert row["resolver_matched"] == 0


def test_a_never_observed_intent_is_not_reported_as_drift():
    """⛔ THE FALSE ALARM. "DRIFT" is an actionable finding about a region; it
    must not be produced for a region nobody looked at."""
    out = selfheal_report.format_report(selfheal_report.summarize(LEGACY_BLIND))
    assert "not observed" in out
    assert "DRIFT" not in out


def test_a_genuinely_drifted_intent_is_still_reported_as_drift():
    """⛔ The negative control for the test above. A real probe whose resolver
    could not match IS drift, and must keep saying so."""
    recs = [_rec("notebooklm.set_public_access", probes=12, outcome_pass=False,
                 would_heal=True, match=False, probe_empty=False)]
    out = selfheal_report.format_report(selfheal_report.summarize(recs))
    assert "DRIFT" in out
    s = selfheal_report.summarize(recs)["per_intent"]["notebooklm.set_public_access"]
    assert s["would_heal"] == 1
    assert s["resolver_seen"] == 1


def test_an_all_blind_intent_is_flagged_in_the_table():
    """n=2 on a row that has never been watched is the thing that read as
    coverage. The row now says so where someone will see it."""
    out = selfheal_report.format_report(selfheal_report.summarize(LEGACY_BLIND))
    assert "never observed" in out


def test_the_blind_count_is_visible_as_a_column():
    out = selfheal_report.format_report(selfheal_report.summarize(LEGACY_BLIND))
    assert "blind" in out


# ══════════════════════════════════════════════════════════════════════════
# 3. the call site: observe the dialog while it is open
# ══════════════════════════════════════════════════════════════════════════

def _share_flow_src():
    for name in dir(research):
        fn = getattr(research, name)
        if not callable(fn):
            continue
        try:
            src = inspect.getsource(fn)
        except (TypeError, OSError):
            continue
        if ('notebooklm.set_public_access"' in src
                and "txt === 'save'" in src):
            return code_only(src)
    raise AssertionError("the NotebookLM share flow was renamed or restructured")


def test_the_dialog_intents_are_observed_before_the_dialog_is_dismissed():
    """⭐ The structural half of the fix, and the reason the blank reads were
    permanent rather than unlucky.

    Both intents declare `region: "dialog"`. Observing them after the Save/Done
    click means probing a dialog that is gone — 0 elements, every run, forever.
    Order is the whole property, so order is what is asserted."""
    src = _share_flow_src()
    observe = src.index('"notebooklm.set_public_access"')
    # Anchored on the Save CLICK, not on the "Step 3b" comment that labels it:
    # `code_only` blanks comments precisely so an assertion about order cannot
    # come to rest on prose that could be moved independently of the code.
    save = src.index("txt === 'save'")
    assert observe < save, (
        "the shadow observation runs after the Save/Done click that closes the "
        "dialog — those two intents can never probe anything there"
    )


def test_both_dialog_intents_moved_together():
    src = _share_flow_src()
    assert src.index('"notebooklm.copy_share_link"') < src.index("txt === 'save'")


def test_the_two_intents_really_are_dialog_scoped():
    """The premise the test above rests on, read from the intent file rather
    than assumed — if either region became "document", the ordering would stop
    mattering and this file should say so out loud."""
    intents = json.loads(
        (Path(research.__file__).parent / "selfheal_intents.json").read_text())
    intents = intents.get("intents", intents)
    for name in ("notebooklm.set_public_access", "notebooklm.copy_share_link"):
        assert intents[name]["region"] == "dialog", name
    # and the control: the opener is document-scoped, which is why it probed 40
    # elements on the same run the other two probed none.
    assert intents["notebooklm.open_share_dialog"]["region"] == "document"


def test_the_observation_is_still_flag_gated():
    """Shadow must stay inert when the switch is off. It moved earlier in the
    flow, which puts it in front of a live Save click — the gate is what keeps
    that free."""
    src = _share_flow_src()
    i = src.index('"notebooklm.set_public_access"')
    window = src[max(0, i - 400):i]
    assert "selfheal.is_enabled()" in window


def test_the_predicates_are_unchanged_by_the_move():
    """The move must not change WHAT is asserted — both values are computed
    before the Save click, so they are the same numbers either way."""
    src = _share_flow_src()
    assert "outcome_pass=bool(public_verified)" in src
    assert "outcome_pass=is_notebooklm_url(url)" in src
