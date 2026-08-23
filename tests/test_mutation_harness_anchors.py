"""Every mutation harness anchor must still match exactly once.

⛔⛔ An anchor that no longer matches once measures NOTHING — and prints a kill.
That is the worst failure mode a test-quality tool has, because there is nothing
above a harness to notice when it goes quiet.

This repo has now been bitten three times:
  * `serve_stop_deliverable` D3 — matched twice after a later function landed,
    so the sharpest over-correction in that wave was measuring nothing.
  * `share_ordering` C5 — matched **twenty-three** times, and that harness used
    `.replace(frm, to, 1)`, so for months it silently mutated the first
    `Escape` keypress in the file instead of the NotebookLM canvas close.
  * the seventeen this file pins below, found the first time the sweep ran.

⭐ The ratchet: `KNOWN_STALE` is a closed, dated list that may only SHRINK. A
new stale anchor fails immediately. Fixing an old one also fails — with a
message telling you to take it off the list. Neither can pass unnoticed, which
is the whole property the harnesses lost.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(os.path.dirname(HERE), ".mutants", "_anchor_sweep.py")


def _sweep():
    spec = importlib.util.spec_from_file_location("_anchor_sweep", SWEEP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.sweep()


# ⛔ PRE-EXISTING DEBT, recorded 2026-08-17 by the sweep's first run. Four waves
# from 2026-08-11 → 08-14 whose anchors drifted as the source moved under them.
# Each entry is (harness, mutant id). Re-anchoring them needs the intent of the
# wave that wrote them, so it is a named follow-up rather than a silent fix —
# but nothing new may join them.
# ⭐⭐ TWO CAME OFF THIS LIST ON 2026-08-18, and they were never stale. The sweep
# scanned only columns 1-2 for a target file, so `review_should_fix`'s
# per-mutant file in column 4 was missed and its anchors were counted against
# `research.py` — the wrong file, where they match zero times. Fixing the sweep's
# detection resolved them. ⛔ Which is the lesson for this list: an entry here
# says "this mutant measures nothing", and two of the original seventeen were
# saying it about the TOOL rather than about the mutant.
# ✅ EMPTIED 2026-08-23. All fifteen re-anchored, and three of them were more
# than drift: the Claude upsell filter now exists in FOUR byte-identical copies
# (the picker, the probe, the dropdown click, and the Gemini ranker wave 6
# ported it to), so five one-line anchors matched 2-3x. Those mutants are now
# spread deliberately ACROSS the copies — the suite only ever exercised one, and
# a copy nothing measures will show up as a SURVIVOR instead of as silence.
#
# ⛔ The list stays here, empty. Deleting it would delete the ratchet: the two
# assertions below are what make a NEW stale anchor fail immediately and a FIXED
# one fail until it is taken off the list. Neither may pass unnoticed.
KNOWN_STALE: "set[tuple[str, str]]" = set()


def test_the_sweep_can_actually_see_the_harnesses():
    """A sweep that silently found nothing to check would pass every assertion
    below — the same shape of lie it exists to catch."""
    checked, _ = _sweep()
    assert checked > 400, f"only {checked} anchors reachable; the sweep is broken"


def test_no_new_stale_anchors():
    _, bad = _sweep()
    found = {(name, mid) for name, mid, _why in bad}
    new = found - KNOWN_STALE
    details = {(n, m): w for n, m, w in bad}
    assert not new, (
        "these anchors no longer match exactly once, so the mutants using them "
        "measure nothing and report kills:\n"
        + "\n".join(f"  {n} {m}: {details[(n, m)]}" for n, m in sorted(new))
    )


def test_the_known_stale_list_only_shrinks():
    _, bad = _sweep()
    found = {(name, mid) for name, mid, _why in bad}
    fixed = KNOWN_STALE - found
    assert not fixed, (
        "good news — these are no longer stale. Remove them from KNOWN_STALE so "
        f"the ratchet keeps its grip: {sorted(fixed)}"
    )


def test_every_harness_is_swept():
    """A harness that fails to import is invisible to the sweep, which would
    make an empty result look like a clean one."""
    _, bad = _sweep()
    unreadable = [(n, w) for n, m, w in bad
                  if m == "-" or "would not import" in w]
    assert not unreadable, f"harnesses the sweep could not read: {unreadable}"
