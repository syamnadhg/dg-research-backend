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
SUFFIXES = (".py", ".ts", ".tsx", ".mjs", ".js", ".json", ".rules", ".md")


def _read(rel, cache):
    if rel in cache:
        return cache[rel]
    for base in (REPO, FE):
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
    """Return (anchors_checked, [(harness, mutant_id, why), …])."""
    cache = {}
    bad = []
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

        default_files = list(getattr(mod, "MUTATED_FILES", None)
                             or [getattr(mod, "SRC", "research.py")])

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
                checked += 1
                if frm == to:
                    bad.append((name, mid, "replacement equals anchor — "
                                           "mutates nothing"))
                    continue
                texts = [_read(f, cache) for f in files]
                if all(t is None for t in texts):
                    bad.append((name, mid, f"target file(s) not found: {files}"))
                    continue
                hits = sum((t or "").count(frm) for t in texts)
                if hits != 1:
                    bad.append((name, mid,
                                f"matches {hits}x in {files}: {frm[:60]!r}"))
    return checked, bad


def main() -> int:
    checked, bad = sweep()
    print(f"swept {checked} anchors across {len(harnesses())} harnesses")
    if bad:
        print("\n⛔ STALE / BROKEN ANCHORS — each of these measures NOTHING:")
        for name, mid, why in bad:
            print(f"  {name}  {mid}  {why}")
        return 1
    print("✓ every anchor still matches exactly once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
