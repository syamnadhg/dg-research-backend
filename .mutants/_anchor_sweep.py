"""Static stale-anchor sweep across every mutation harness in this directory.

⛔⛔ WHY THIS EXISTS. A harness anchor that no longer matches EXACTLY ONCE
measures nothing — and reports a kill. This repo has now been bitten three
times: `serve_stop_deliverable` D3 (matched twice), `share_ordering` C5
(twenty-three times, silently mutating the first `Escape` in the file for
months), and the seventeen found by this sweep's first run on 2026-08-17.

A harness is the thing that tells you your tests are real. When it goes quiet
there is nothing above it to notice, so the check has to be cheap enough to run
every time — hence STATIC. No test runs, no mutation, seconds not hours.

    python .mutants/_anchor_sweep.py

⛔ The tables are not one shape. Some are (id, direction, why, edits, tests)
with a module-level MUTATED_FILES; others carry the target file as the second
column. A sweep that assumes one shape invents false alarms, which is the same
disease it exists to catch — so the file column is DETECTED, and an entry whose
target cannot be resolved is REPORTED rather than guessed at.
"""
import glob
import io
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FE = os.path.join(os.path.dirname(REPO), "dg-research")
# ⛔⛔ THE FORK IS A THIRD TARGET REPO, ADDED 2026-08-26 — and its absence made
# four live mutants report as "target file(s) not found", i.e. as STALE, when
# they resolve perfectly inside their own harness. This tool already reached
# across into the app repo; a harness that measures the fleet skill's copy of a
# sentence is the same shape of thing, and the alternative was four entries on
# the KNOWN_STALE ratchet saying "this measures nothing" about the TOOL rather
# than about the mutant — the exact mistake two of the original seventeen made.
FORK = os.path.join(os.path.dirname(REPO), "dg-hermes-fleet")
SUFFIXES = (".py", ".ts", ".tsx", ".mjs", ".js", ".json", ".rules", ".md")

# ⛔⛔ THIS TOOL NEEDS THREE CHECKOUTS AND CI HAS ONE, which is why the suite's
# copy of it was RED from 2026-08-26 to 09-10 — every anchor whose target lives
# in the app repo or the fork reported "target file(s) not found", i.e. as STALE,
# on a runner that simply never had those files. 168 of them. ⛔ And nobody saw
# it for fifteen days: the lint step runs first in the same job, so once THAT
# broke on 09-05 the tests step reported `skipped` and the run's red looked like
# one failure instead of two.
# ⭐ So a missing file now has two meanings, and they are told apart by looking
# at the DISK rather than by pattern-matching the path: if every root exists, a
# file that resolves nowhere has genuinely moved and is STALE. If a root is
# absent, the anchor is UNREACHABLE HERE — counted, named, and excluded from the
# staleness verdict, because this checkout cannot hold an opinion about it.
# ⛔ The ratchet is NOT loosened by that: the test asserts unreachable is EMPTY
# whenever all three roots are present, so a fork file that gets renamed still
# fails on every machine that can see the fork — which is every machine a
# harness is ever run on.
ROOTS = (("backend", REPO), ("app", FE), ("fork", FORK))


def absent_roots():
    """The declared target checkouts that are not on this disk."""
    return [name for name, path in ROOTS if not os.path.isdir(path)]


def _read(rel, cache):
    if rel in cache:
        return cache[rel]
    for _name, base in ROOTS:
        path = os.path.join(base, rel)
        if os.path.exists(path):
            cache[rel] = io.open(path, encoding="utf-8").read()
            return cache[rel]
    cache[rel] = None
    return None


def harnesses():
    return sorted(p for p in glob.glob(os.path.join(HERE, "*.py"))
                  if not os.path.basename(p).startswith("_"))


def sweep():
    """Return (checked, [(harness, mutant, why)…], [(harness, mutant, why)…]).

    The third list is the anchors this checkout cannot judge: their target files
    live in a repo that is not here. `checked` counts only anchors that were
    actually compared, so a caller can tell a real sweep from a vacuous one.
    """
    cache = {}
    bad = []
    unreachable = []
    missing = absent_roots()
    checked = 0

    for path in harnesses():
        name = os.path.basename(path)
        mod_name = "_sweep_" + name[:-3].replace("-", "_")
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception as exc:
            bad.append((name, "-", f"harness would not import: "
                                   f"{type(exc).__name__}: {exc}"))
            continue

        mutants = getattr(mod, "MUTANTS", None)
        if not mutants:
            bad.append((name, "-", "no MUTANTS table — cannot sweep"))
            continue

        # ⛔⛔ RESOLVE THE TARGET THE WAY THE HARNESSES ACTUALLY DECLARE IT.
        # This read used to be MUTATED_FILES or SRC, falling back to
        # "research.py" — and it was RIGHT BY ACCIDENT for 55 harnesses,
        # because every one of them targets research.py anyway. The first
        # harness in the fleet to target anything else (wave10_domshim_style,
        # target tests/_domshim.py) had all eight of its anchors reported STALE:
        # they were being counted in research.py, where of course they do not
        # appear. A default that is usually correct is worse than one that is
        # never correct, because nothing reveals it until the day it matters.
        # ⭐ _apply_sweep.py already reads this chain; the two tools disagreeing
        # is what hid the bug, so they now agree by construction.
        default_files = list(getattr(mod, "MUTATED_FILES", None) or [])
        if not default_files:
            for _attr in ("SRC", "TARGET", "RESEARCH", "FILE"):
                _v = getattr(mod, _attr, None)
                if isinstance(_v, str) and _v:
                    default_files = [_v]
                    break
        if not default_files:
            default_files = ["research.py"]

        for entry in mutants:
            mid = entry[0] if entry else "?"
            edits = next((it for it in entry
                          if isinstance(it, list) and it
                          and isinstance(it[0], tuple)), None)
            if edits is None:
                continue
            # ⛔ THE FILE COLUMN IS ANYWHERE. Harnesses put the target file
            # second (older BE waves), or LAST (a per-mutant target, which is
            # what a wave touching two files needs). Scanning only columns 1-2
            # made a last-column harness fall back to MUTATED_FILES and sum
            # matches across EVERY file it declares — so an anchor matching once
            # in its real target was reported as matching twice, and the only way
            # to quieten it would have been to add a false entry to the ratchet.
            # A tool that produces false alarms gets its alarms ignored, which is
            # the same end state as one that misses them. Found 2026-08-18 by the
            # wave-2 telemetry harness.
            targets = [it for it in entry
                       if isinstance(it, str) and it.endswith(SUFFIXES)
                       and " " not in it]
            files = targets or default_files

            for frm, to in edits:
                if frm == to:
                    checked += 1
                    bad.append((name, mid, "replacement equals anchor — "
                                           "mutates nothing"))
                    continue
                texts = [_read(f, cache) for f in files]
                # ⛔ ANY missing file disqualifies the mutant, not just all of
                # them. A mutant declaring one backend file and one fork file
                # used to fall through here and sum its hits across whatever
                # happened to be present — reporting "matches 0x" for an anchor
                # that matches perfectly in the file this checkout lacks. None
                # of the 168 was that shape, but the next one would have been
                # harder to read than a plain "not found".
                gone = [f for f, t in zip(files, texts) if t is None]
                if gone:
                    why = f"target file(s) not found: {gone}"
                    if missing:
                        unreachable.append(
                            (name, mid, why + f" — not this checkout's call, "
                                              f"missing root(s): {missing}"))
                    else:
                        bad.append((name, mid, why))
                    continue
                checked += 1
                hits = sum((t or "").count(frm) for t in texts)
                if hits != 1:
                    bad.append((name, mid,
                                f"matches {hits}x in {files}: {frm[:60]!r}"))
    return checked, bad, unreachable


def main() -> int:
    checked, bad, unreachable = sweep()
    print(f"swept {checked} anchors across {len(harnesses())} harnesses")
    if unreachable:
        print(f"\n… {len(unreachable)} anchor(s) NOT CHECKED — their target "
              f"files live in a repo this checkout does not have "
              f"({', '.join(absent_roots())}):")
        for name, mid, why in unreachable:
            print(f"  {name}  {mid}  {why}")
    if bad:
        print("\n⛔ STALE / BROKEN ANCHORS — each of these measures NOTHING:")
        for name, mid, why in bad:
            print(f"  {name}  {mid}  {why}")
        return 1
    print("✓ every anchor still matches exactly once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
