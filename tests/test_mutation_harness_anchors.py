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
MUTANTS = os.path.join(os.path.dirname(HERE), ".mutants")
SWEEP = os.path.join(MUTANTS, "_anchor_sweep.py")
APPLY = os.path.join(MUTANTS, "_apply_sweep.py")


def _sweep_module():
    spec = importlib.util.spec_from_file_location("_anchor_sweep", SWEEP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sweep():
    """(checked, stale) — the two the ratchet below is about."""
    checked, bad, _unreachable = _sweep_module().sweep()
    return checked, bad


def _apply_module():
    spec = importlib.util.spec_from_file_location("_apply_sweep", APPLY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_APPLY_RESULT = []


def _apply_sweep():
    """(stats, broken, unreachable, notes, per_harness), computed ONCE.

    ⛔ It applies 3.4k mutants and parses each result, so it costs ~35 seconds.
    Running it per test would put four minutes into a unit file and somebody
    would take it out again — which is how the twenty breaks below survived."""
    if not _APPLY_RESULT:
        _APPLY_RESULT.append(_apply_module().sweep())
    return _APPLY_RESULT[0]


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


# ══════════════════════════════════════════════════════════════════════════════
# THE OTHER HALF: a mutant that APPLIES but measures nothing anyway.
# ══════════════════════════════════════════════════════════════════════════════
#
# ⛔⛔ EVERYTHING ABOVE COUNTS ANCHORS AGAINST THE FILE AS IT SITS, and on
# 2026-09-17 that turned out to be half a guard. Applying every mutant in order
# found TWENTY-SEVEN mutants measuring nothing where the resting sweep saw a
# clean bill, in two shapes it structurally cannot see:
#
#   1. THE MUTANT DOES NOT PARSE. A re-anchor moved the ANCHOR onto re-wrapped
#      source and left the REPLACEMENT in the old shape. Where the harness
#      compiles the mutant first this is subtracted from its own denominator as a
#      "fault" and the score line still reads clean. Where it does NOT — eleven of
#      the sixteen harnesses holding a break — the unparseable file is WRITTEN,
#      the suite reds on an import error, and `killed = not green` BANKS A KILL
#      IT NEVER EARNED. Those scores are not narrower than they claim. They are
#      INFLATED, and eighteen of the twenty-seven were that.
#   2. THE ANCHOR IS UNIQUE UNTIL THE MUTANT'S OWN EARLIER EDIT RUNS. Edit 1's
#      replacement contains edit 2's anchor as a substring, so edit 2 matches
#      twice — unique at rest, ambiguous mid-mutant. A resting sweep can NEVER
#      see this one, however carefully it is written.
#
# ⭐ Seven were repaired the day the tool was written, because they belonged to
# the harnesses wave 9 actually ran: device_visibility V2 (shape 2 — and the
# only mutation evidence for the joinPolicy read), wave793 N15 and W14, wave794
# R2/X3/X10, wave792 N11. The twenty below belong to their own waves and are
# recorded here rather than fixed, for the same reason the list above was:
# re-anchoring one needs the intent of the wave that wrote it.
#
# ⛔ THE DATES ARE THE POINT. Only ONE of the twenty-seven arrived with wave 9.
# Eighteen have been broken since the day they were written — the oldest since
# 2026-08-11 — so those mutants have never once measured anything, and
# `telemetry_0818` F2 writes keyword params after `**kwargs`, which has never
# been legal on any day of Python.
KNOWN_UNAPPLIABLE: "set[tuple[str, str]]" = {
    ('broken_install_0822_mutants.py', 'N6'),
    ('clear_local_logs_0818_mutants.py', 'C16'),
    ('new_owner_setup_0817_mutants.py', 'F1'),
    ('new_owner_setup_0817_mutants.py', 'F15'),
    ('noise_and_durations_0811_mutants.py', 'D4'),
    ('queue_gate_vision_0811_mutants.py', 'X3'),
    ('queue_gate_vision_0811_mutants.py', 'X4'),
    ('queue_gate_vision_0811_mutants.py', 'X6'),
    ('queue_gate_vision_0811_mutants.py', 'X7'),
    ('review_wave2_0813_mutants.py', 'K4'),
    ('telemetry_0818_mutants.py', 'F2'),
    ('watch_liveness_0822_mutants.py', 'D2'),
    ('watch_liveness_0822_mutants.py', 'P5'),
    ('watch_liveness_0822_mutants.py', 'R2'),
    ('watch_liveness_0822_mutants.py', 'R6'),
    ('wave11_router_gates_0911_mutants.py', 'Q6'),
    ('wave11_router_gates_0911_mutants.py', 'Q8'),
    ('wave1_merge_gates_0821_mutants.py', 'U3'),
    ('wave8_attribution_0824_mutants.py', 'O1c'),
    ('wave8_machine_scope_0824_mutants.py', 'H1'),
}


def test_no_new_mutant_stops_applying():
    """⛔⛔ THE RATCHET. Anything not on the dated list above fails at once.

    A hard failure on the whole set would red the gate over twenty breaks that
    are five weeks old and belong to other waves, and a gate that is red for a
    reason nobody can act on today gets switched off — which is the same end
    state as no gate. So the debt is CLOSED and DATED, and the list may only
    shrink."""
    _stats, broken, _unreachable, _notes, _per = _apply_sweep()
    found = {(f["harness"], f["mutant"]) for f in broken}
    new = found - KNOWN_UNAPPLIABLE
    why = {(f["harness"], f["mutant"]): f"[{f['kind']}] {f['detail']}"
           for f in broken}
    assert not new, (
        "these mutants no longer apply cleanly, so they measure NOTHING — and "
        "in a harness with no pre-write compile guard they report a KILL:\n"
        + "\n".join(f"  {h} {m}: {why[(h, m)]}" for h, m in sorted(new))
    )


def test_the_known_unappliable_list_only_shrinks():
    mod = _apply_module()
    if mod.absent_roots():
        pytest.skip(f"target checkout(s) not on this disk: {mod.absent_roots()}")
    _stats, broken, _unreachable, _notes, _per = _apply_sweep()
    found = {(f["harness"], f["mutant"]) for f in broken}
    fixed = KNOWN_UNAPPLIABLE - found
    assert not fixed, (
        "good news — these apply and parse again. Take them off "
        f"KNOWN_UNAPPLIABLE so the ratchet keeps its grip: {sorted(fixed)}"
    )


def test_the_apply_sweep_cannot_report_clean_by_doing_nothing():
    """⛔⛔ AN AUDITOR THAT PASSES BY LOOKING AT NOTHING IS THE DEFECT BEING FIXED.

    The two assertions above are satisfied perfectly by a sweep that loaded no
    harness, found no mutant and applied no edit — which is precisely the shape
    of silence that let twenty-seven mutants report kills. So the floors are
    asserted, and a harness that yields zero mutants or applies zero edits is a
    HOLE in the audit rather than a clean harness."""
    stats, _broken, _unreachable, _notes, per_harness = _apply_sweep()
    assert not _apply_module().vacuity(stats, per_harness)
    assert stats["harnesses"] > 100, stats
    assert stats["mutants"] > 3000, stats
    assert stats["edits"] > 3000, stats
    assert stats["py_parsed"] > 3000, (
        "the edits were applied but almost nothing was PARSED, so the half of "
        f"this that finds an unparseable mutant is not running: {stats}"
    )


def test_every_harness_still_imports_for_the_apply_sweep():
    """A harness that will not import yields no mutants, and a sweep that skips
    it quietly is back to reporting clean by looking at nothing."""
    stats, broken, _unreachable, notes, _per = _apply_sweep()
    assert stats["harnesses"] == stats["imported"], (
        f"{stats['harnesses'] - stats['imported']} harness(es) would not "
        f"import: {[n for n in notes if 'would not import' in n]}"
    )
    assert not [f for f in broken if f["mutant"] == "-"], (
        f"harnesses yielding no mutant table: {[f for f in broken if f['mutant'] == '-']}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# The two properties the ratchet above rests on, pinned where nothing else can
# satisfy them. Both are proven on a SYNTHETIC harness: pinning them on a real
# one would mean keeping a mutant broken on purpose, and the moment somebody
# repaired it the proof would evaporate without anyone noticing.
# ──────────────────────────────────────────────────────────────────────────────

def _synthetic(tmp_path, name, target, edits):
    """A one-mutant harness in a repo-shaped temp tree; returns both sweeps."""
    repo = tmp_path / name
    (repo / ".mutants").mkdir(parents=True)
    (repo / "t.py").write_text(target, encoding="utf-8")
    body = [
        "from pathlib import Path",
        "",
        "ROOT = Path(__file__).resolve().parent.parent",
        'SRC = "t.py"',
        "MUTANTS = [",
        f'    ("M1", "the synthetic mutant", {edits!r}),',
        "]",
        "",
        "for mid, why, edits in MUTANTS:",
        "    path = ROOT / SRC",
        "",
    ]
    (repo / ".mutants" / "synthetic_mutants.py").write_text(
        "\n".join(body), encoding="utf-8")

    rest = _sweep_module()
    rest.HERE = str(repo / ".mutants")
    rest.ROOTS = (("backend", str(repo)),)
    resting = rest.sweep()

    app = _apply_module()
    app.HERE = repo / ".mutants"
    app.REPO = repo
    app.ROOT_SPEC = (("backend", repo),)
    applied = app.sweep()
    return resting, applied


def test_an_anchor_that_only_doubles_MID_MUTANT_is_caught(tmp_path):
    """⛔⛔ THE ONE THE RESTING SWEEP CAN NEVER SEE, and the reason applying the
    edits IN ORDER is the whole point rather than an implementation detail.

    `device_visibility` V2 is exactly this shape and it is wave 9's own bug: its
    edit 2 anchors on the four-space `return "private"` fallback, which is unique
    in the file — until edit 1's own replacement, a twelve-space
    `return "private" if …`, puts a second copy of that substring in the file.
    The harness then saw two matches, called V2 a fault, subtracted it from its
    own denominator and printed a clean score. V2 is the only mutation evidence
    for the joinPolicy read, the sharpest lane in that wave.

    ⭐ The assertion below is in two halves ON PURPOSE. Checking only that the
    apply sweep complains would be satisfied by a tool that checks anchors
    against the resting file and happens to be strict — so the resting sweep is
    asserted CLEAN on the very same harness. Nothing but applying edit 1 before
    counting edit 2 can pass both."""
    target = ('def pick(v):\n'
              '    for k in ("a",):\n'
              '        if v:\n'
              '            return "public" if v == "public" else "private"\n'
              '    return "private"\n')
    edits = [('            return "public" if v == "public" else "private"',
              '            return "private" if v == "private" else "public"'),
             ('    return "private"', '    return "public"')]
    (r_checked, r_bad, r_unreach), (stats, broken, _un, _n, per) = _synthetic(
        tmp_path, "midmutant", target, edits)

    assert r_checked == 2 and not r_bad and not r_unreach, (
        "the resting sweep found this at rest, so it proves nothing about "
        f"applying the edits in order: {r_bad}")
    assert len(broken) == 1, broken
    assert broken[0]["mutant"] == "M1"
    assert broken[0]["kind"] == "anchor-2x+", broken[0]
    assert "edit 2" in broken[0]["detail"], broken[0]["detail"]
    assert "2x" in broken[0]["detail"], broken[0]["detail"]
    assert stats["mutants"] == 1 and stats["harnesses"] == 1, stats
    assert per["synthetic_mutants.py"]["mutants"] == 1


def test_a_mutant_that_does_not_PARSE_is_caught(tmp_path):
    """⛔⛔ THE EIGHTEEN THAT BANKED A KILL THEY NEVER EARNED.

    A replacement left behind by a half-done re-anchor still MATCHES once, so
    the resting sweep is happy; the file it produces is a SyntaxError. In a
    harness with no pre-write compile guard — eleven of the sixteen holding a
    break — that file is written, the suite reds on an import error, and
    `killed = not green` reads the red as a kill. The score is not narrower than
    it claims. It is inflated.

    ⭐ Same two-halved assertion: the resting sweep must be CLEAN here, so the
    only thing that can pass this test is actually parsing the mutated text."""
    target = ('def pick(v):\n'
              '    return "private"\n')
    edits = [('    return "private"', '    return ("private"')]
    (r_checked, r_bad, r_unreach), (stats, broken, _un, _n, _per) = _synthetic(
        tmp_path, "unparseable", target, edits)

    assert r_checked == 1 and not r_bad and not r_unreach, (
        f"the resting sweep already refused this, so it pins nothing: {r_bad}")
    assert len(broken) == 1, broken
    assert broken[0]["mutant"] == "M1"
    assert broken[0]["kind"] == "parse-error", broken[0]
    assert "t.py" in broken[0]["detail"], broken[0]["detail"]
    assert stats["edits"] == 1, stats


def test_a_harness_with_no_mutants_is_a_HOLE_not_a_clean_bill(tmp_path):
    """⛔ The failure mode this whole file is about, one level up: a sweep that
    reports clean because it looked at nothing. An empty harness passes every
    ratchet above, so emptiness itself has to be the thing that fails."""
    app = _apply_module()
    repo = tmp_path / "empty"
    (repo / ".mutants").mkdir(parents=True)
    (repo / ".mutants" / "hollow_mutants.py").write_text(
        "MUTANTS = []\n", encoding="utf-8")
    app.HERE = repo / ".mutants"
    app.REPO = repo
    app.ROOT_SPEC = (("backend", repo),)
    stats, broken, _un, _notes, per = app.sweep()

    reasons = app.vacuity(stats, per)
    assert reasons, "a harness yielding zero mutants was reported as clean"
    assert any("ZERO mutants" in r for r in reasons), reasons
    assert [f["kind"] for f in broken] == ["no-mutants"], broken

    # …and the same verdict when there is no harness at all.
    bare = tmp_path / "bare"
    (bare / ".mutants").mkdir(parents=True)
    app.HERE = bare / ".mutants"
    app.REPO = bare
    app.ROOT_SPEC = (("backend", bare),)
    stats2, _b2, _u2, _n2, per2 = app.sweep()
    assert app.vacuity(stats2, per2), (
        "a sweep that loaded no harness at all called itself clean")


# ── the two sweeps must agree about WHICH FILE a harness mutates ────────────
# ⛔⛔ ADDED 2026-09-18, AFTER THE BUG THIS PINS SHIPPED AND HID FOR A DAY.
# `_anchor_sweep` resolved a harness's target as MUTATED_FILES or SRC, falling
# back to "research.py". That default was RIGHT BY ACCIDENT for all 55 harnesses
# that declare neither, because every one of them targets research.py anyway.
# The first harness in the fleet to target something else — wave10_domshim_style,
# whose target is tests/_domshim.py — had all EIGHT of its anchors reported STALE,
# because they were being counted in a file they do not appear in.
#
# ⭐ WHAT MADE IT INVISIBLE IS THE THING THIS TEST FIXES: `_apply_sweep` already
# read TARGET and resolved it correctly, so the two tools disagreed and neither
# said so. One reported 8 stale anchors, the other reported a clean apply, and a
# reader could believe whichever matched their expectation. A default that is
# usually correct is worse than one that is never correct — nothing reveals it
# until the day it matters, and on that day it accuses the newest work.
def test_a_module_level_TARGET_is_swept_against_that_file(tmp_path):
    """⛔⛔ THE 09-18 BUG, DRIVEN THROUGH THE REAL SWEEP.

    `_anchor_sweep` resolved a harness's target as MUTATED_FILES or SRC, falling
    back to "research.py". That default was RIGHT BY ACCIDENT for all 55 harnesses
    that declare neither, because every one of them targets research.py anyway.
    The first harness in the fleet to target something else — wave10_domshim_style,
    whose target is tests/_domshim.py — had all EIGHT of its anchors reported
    STALE, because they were being counted in a file they do not appear in.

    ⭐ WHAT MADE IT INVISIBLE: `_apply_sweep` already read TARGET and resolved it
    correctly, so the two tools disagreed and neither said so. One reported eight
    stale anchors, the other reported a clean apply, and a reader could believe
    whichever matched their expectation.

    ⛔ THIS TEST DRIVES THE REAL SWEEP rather than re-deriving its chain. The
    first two attempts at this pin did re-derive it — once comparing the fallback
    against the other tool's per-mutant resolution (which falsely accused five
    healthy harnesses), and once comparing the chain to itself (which could not
    fail at all). A synthetic harness that declares TARGET and nothing else is the
    only shape that measures the tool instead of a copy of it.
    """
    repo = tmp_path / "declared_target"
    (repo / ".mutants").mkdir(parents=True)
    (repo / "elsewhere.py").write_text("VALUE = 1\n", encoding="utf-8")
    # research.py exists and does NOT contain the anchor — so a sweep that
    # defaults to it reports the anchor stale, which is precisely the bug.
    (repo / "research.py").write_text("# nothing to see here\n", encoding="utf-8")

    (repo / ".mutants" / "declared_mutants.py").write_text("\n".join([
        "from pathlib import Path",
        "",
        "ROOT = Path(__file__).resolve().parent.parent",
        'TARGET = "elsewhere.py"',
        "FILES = (TARGET,)",
        "MUTANTS = [",
        '    ("M1", "the declared-target mutant", [("VALUE = 1", "VALUE = 2")]),',
        "]",
        "",
        "for mid, why, edits in MUTANTS:",
        "    path = ROOT / TARGET",
        "",
    ]), encoding="utf-8")

    rest = _sweep_module()
    rest.HERE = str(repo / ".mutants")
    rest.ROOTS = (("backend", str(repo)),)
    checked, bad, unreachable = rest.sweep()

    assert not bad, (
        "the sweep resolved a harness's declared TARGET somewhere else and called "
        "its anchor stale — the 09-18 bug: " + repr(bad)
    )
    assert checked >= 1, "the sweep checked nothing, so its clean verdict means nothing"
