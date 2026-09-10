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


def _sweep_module():
    spec = importlib.util.spec_from_file_location("_anchor_sweep", SWEEP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sweep():
    """(checked, stale) — the two the ratchet below is about."""
    checked, bad, _unreachable = _sweep_module().sweep()
    return checked, bad


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
    below — the same shape of lie it exists to catch.

    ⭐ `checked` counts anchors actually COMPARED, so this floor is what stops
    the unreachable bucket below from turning the whole guard vacuous on a
    one-checkout runner: excusing an anchor removes it from this count too."""
    checked, _ = _sweep()
    assert checked > 400, f"only {checked} anchors compared; the sweep is broken"


def test_nothing_is_excused_when_every_target_repo_is_present():
    """⛔⛔ THE HALF OF THE RATCHET THAT KEEPS ITS GRIP AFTER 2026-09-10.

    The sweep reads three checkouts — this repo, the app repo and the fork — and
    CI has only the first, so 84 anchors there resolve to no file through no
    fault of their own. Those are reported as UNREACHABLE rather than stale, and
    that concession is the kind of thing that quietly eats a guard: the same
    excuse covers a fork file somebody actually renamed.

    ⭐ So it is bounded by the disk. On any checkout holding all three repos —
    which is every machine a harness is written or run on — nothing may be
    excused at all. A renamed fork file fails here, immediately, on the only
    machines that could ever have noticed."""
    mod = _sweep_module()
    missing = mod.absent_roots()
    if missing:
        pytest.skip(f"target checkout(s) not on this disk: {missing} — the "
                    f"reachability ratchet is asserted where they exist")
    _checked, _bad, unreachable = mod.sweep()
    assert not unreachable, (
        "every target repo is present, so these anchors have genuinely moved "
        "and are measuring nothing:\n"
        + "\n".join(f"  {n} {m}: {w}" for n, m, w in unreachable)
    )


def test_an_absent_repo_is_the_only_thing_that_excuses_an_anchor():
    """⛔ The concession must be keyed on the ROOT being gone, not on the file
    being gone — otherwise it is just "missing files are fine", which is the
    failure mode this whole file exists to prevent. Proven by taking the two
    sibling roots away and checking that the anchors move buckets rather than
    disappearing, and that the backend's own anchors are still compared."""
    mod = _sweep_module()
    if mod.absent_roots():
        pytest.skip("this proof needs all three checkouts present")
    before_checked, before_bad, before_unreachable = mod.sweep()
    assert not before_unreachable

    mod.FE = "/nonexistent-app-checkout"
    mod.FORK = "/nonexistent-fork-checkout"
    mod.ROOTS = (("backend", mod.REPO), ("app", mod.FE), ("fork", mod.FORK))
    after_checked, after_bad, after_unreachable = mod.sweep()

    assert after_unreachable, "hiding two repos excused nothing — the split is dead"
    assert len(after_bad) == len(before_bad), (
        "hiding a repo turned anchors STALE instead of unreachable, which is "
        "the red CI carried for fifteen days"
    )
    assert after_checked == before_checked - len(after_unreachable), (
        "an excused anchor must leave the compared count too, or the floor "
        f"above stops meaning anything: {after_checked} vs {before_checked}"
    )
    assert after_checked > 400, (
        f"only {after_checked} anchors survive a one-checkout run; the guard "
        f"would be vacuous on CI"
    )


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


def test_a_missing_file_is_still_stale_when_its_repo_IS_here():
    """⛔⛔ THE PROPERTY THE CONCESSION COULD HAVE EATEN, and the one the two
    tests above cannot see: nothing is actually missing on a full checkout, so
    "excuse every missing file" and "excuse only what an absent repo explains"
    look identical here. One of those is the fifteen-day CI red fixed the wrong
    way round.

    ⭐ So a file is made invisible with every root present, and the anchors that
    used it must come back STALE. Hiding `research.py` is deliberate: it is the
    file most mutants target, so if the concession is keyed on the file rather
    than the root this goes from "hundreds stale" to "hundreds excused"."""
    mod = _sweep_module()
    if mod.absent_roots():
        pytest.skip("this proof needs all three checkouts present")
    real_read = mod._read

    def _blind(rel, cache):
        if rel == "research.py":
            return None
        return real_read(rel, cache)

    mod._read = _blind
    checked, bad, unreachable = mod.sweep()
    assert bad, "hiding research.py upset nothing — the sweep is not reading it"
    assert not unreachable, (
        "a file that is simply GONE was excused while every repo it could live "
        "in is right here; the ratchet is keyed on the wrong thing:\n"
        + "\n".join(f"  {n} {m}: {w}" for n, m, w in unreachable[:5])
    )
    assert all("not found" in w for _n, _m, w in bad
               if "research.py" in w), "the reason no longer names the file"


def test_one_missing_file_does_not_get_summed_around(tmp_path):
    """⛔ A mutant naming TWO files used to need BOTH gone before it was reported
    as missing. With one present it fell through and summed its hits across
    whatever was there — so an anchor that matches exactly once in the file this
    checkout lacks was reported as `matches 0x`, i.e. as drift in a file that is
    perfectly fine. 48 mutants declare more than one target file today; none of
    them spans two repos yet, which is the only reason this never fired.

    ⭐ Proven on a synthetic harness because no real one is that shape. A test
    that waited for one to appear would be a comment, not a guard."""
    mod = _sweep_module()
    harness = tmp_path / "synthetic_mutants.py"
    harness.write_text(
        'MUTANTS = [\n'
        '    ("M1", "here.py", "gone.py", [("KEEP", "BREAK")], "two files, one absent"),\n'
        ']\n',
        encoding="utf-8")
    present = tmp_path / "repo"
    present.mkdir()
    (present / "here.py").write_text("KEEP\n", encoding="utf-8")

    mod.HERE = str(tmp_path)
    mod.ROOTS = (("backend", str(present)), ("fork", str(tmp_path / "nope")))
    checked, bad, unreachable = mod.sweep()

    assert not bad, f"a partial file set was reported as drift: {bad}"
    assert len(unreachable) == 1, unreachable
    _n, mid, why = unreachable[0]
    assert mid == "M1"
    assert "gone.py" in why and "here.py" not in why, (
        f"the report must name the file that is actually missing: {why}"
    )
    assert checked == 0, (
        f"an anchor nobody could compare was counted as compared: {checked}"
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
