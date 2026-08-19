"""Mutation harness for wave 2 step 2 — the support bundle.

⛔ WHAT THIS IS FOR. A user with a broken machine has to be able to hand us
everything relevant and nothing else. Two signed-off bounds (last 30 runs AND
last 30 days), a 128 MB ceiling, and a collector that may only read from
`~/.super-research/logs/`.

⭐⭐ THE SHARPEST MUTANTS HERE:
  S3  — "whichever bound is smaller" implemented as a BRANCH. It has to pick,
        and the two bounds answer different questions: a count has no time
        bound, an age bound has no size bound. The branch skips the age bound
        whenever few runs exist, which is exactly the machine you are debugging.
  B1  — the newest run stops being exempt from the size cap, so the bundle can
        drop the run the user is complaining about.
  B2  — the cap goes back to deciding per FILE, so a folder's small meta.json
        fits where its log does not: the archive lists a run with no log, and
        the index insists it is there.
  B8  — the system-log pattern widens. That directory also holds DOM dumps and
        page snapshots this repo writes while debugging, which carry the CONTENT
        of a research session and are named nowhere in the consent screen.
  B9/B10 — the collector allowlist, and its `resolve()`. The consent promise
        about passwords, cookies and profile data is gated on both.
  N1  — the scan skips folders with no meta. The folder whose meta write failed
        is the CRASHED one, so the run that matters is the run that vanishes.
  B13 — `collected.json` disappears, and silent truncation reads as complete
        coverage.

⭐ Over-corrections:
  B6  — sessions become count-bound, which starves the case the bundle exists
        for: the machine that never got a run to start.
  B15 — the content type drifts from the one named constant, so an honest
        upload takes a 403 the retry ladder mislabels as transient.
  S7  — the age bound is applied to the raw device tails too, so a grandfathered
        machine with months-old logs and no runs sends an empty bundle.

    python .mutants/log_bundle_0818_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_BUNDLE = "tests/test_log_bundle_0818.py"
T_CAP = "tests/test_run_log_capture_0818.py"
ALL = [T_BUNDLE, T_CAP]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the selection ═══════════════════════════════════════════════════
    ("S1", "under", "⛔ the age bound is gone, so months-old runs ship under a "
     "30-day promise",
     [('    fresh = [r for r in rows if float(r.get("startedEpoch") or 0) >= cutoff]',
       '    fresh = list(rows)')],
     [T_BUNDLE]),
    ("S2", "under", "the count bound is gone, so a busy fortnight ships hundreds "
     "of runs",
     [('    return fresh[:max(0, int(max_runs))]', '    return fresh')],
     [T_BUNDLE]),
    ("S3", "over", "⛔⛔ 'whichever bound is smaller' as a BRANCH — it skips the "
     "age bound whenever few runs exist, which is the machine being debugged",
     [('    fresh = [r for r in rows if float(r.get("startedEpoch") or 0) >= cutoff]',
       '    fresh = list(rows) if len(rows) <= int(max_runs) else [r for r in rows if float(r.get("startedEpoch") or 0) >= cutoff]')],
     [T_BUNDLE]),
    ("S4", "under", "oldest-first, so the newest thirty become the OLDEST thirty "
     "and the cap drops the run being complained about",
     [('    fresh.sort(key=lambda r: float(r.get("startedEpoch") or 0), reverse=True)\n    return fresh[',
       '    fresh.sort(key=lambda r: float(r.get("startedEpoch") or 0))\n    return fresh[')],
     [T_BUNDLE]),
    ("S5", "under", "a zero bound is ignored rather than honoured",
     [('    return fresh[:max(0, int(max_runs))]',
       '    return fresh[:int(max_runs)] if max_runs else fresh')],
     [T_BUNDLE]),
    ("S6", "under", "the session stream loses its age bound, so a year-old "
     "pairing attempt ships",
     [('        if max(_safe_mtime(p) for p in members) >= cutoff:',
       '        if True:')],
     [T_BUNDLE]),
    ("S7", "over", "sessions become count-bound too, starving the case the "
     "bundle exists for — the machine that never got a run to start",
     [('    out.sort(key=lambda members: max(_safe_mtime(p) for p in members), reverse=True)\n    return out',
       '    out.sort(key=lambda members: max(_safe_mtime(p) for p in members), reverse=True)\n    return out[:5]')],
     [T_BUNDLE]),

    # ══ the metas ARE the index ═════════════════════════════════════════
    ("N1", "under", "⛔⛔ folders with no readable meta are skipped — and the "
     "folder whose meta write failed is the CRASHED one",
     [('        except Exception:\n            meta = {}\n        started = _epoch_from_iso(meta.get("startedUtc")) or _safe_mtime(folder)',
       '        except Exception:\n            continue\n        started = _epoch_from_iso(meta.get("startedUtc")) or _safe_mtime(folder)')],
     [T_BUNDLE]),
    ("N2", "under", "the stored word is repeated instead of derived, so a "
     "process-died run reads as running in the index a human opens",
     [('            "status": _derive_run_status(meta) if meta else "unknown",',
       '            "status": meta.get("status") or "unknown",')],
     [T_BUNDLE]),
    ("N3", "under", "the scan is unordered, so 'newest first' is whatever the "
     "filesystem felt like",
     [('    rows.sort(key=lambda r: r["startedEpoch"], reverse=True)\n    return rows',
       '    return rows')],
     [T_BUNDLE]),
    ("N4", "under", "a folder's size is never measured, so the cap has nothing "
     "to weigh runs against",
     [('            "sizeBytes": _dir_size(folder),', '            "sizeBytes": 0,')],
     [T_BUNDLE]),

    # ══ the archive ═════════════════════════════════════════════════════
    ("B1", "under", "⛔⛔ the newest run stops being exempt, so the bundle can "
     "drop the very run the user is complaining about",
     [('            newest = position == 0', '            newest = False')],
     [T_BUNDLE]),
    ("B2", "under", "⛔ the cap decides per FILE again — a folder's meta.json "
     "fits where its log does not, so a run is listed with no log in it",
     [('            if not newest and written + folder_bytes > int(max_bytes):\n                dropped_runs.append(row["name"])\n                continue',
       '            if False:\n                dropped_runs.append(row["name"])\n                continue')],
     [T_BUNDLE]),
    # ⛔ B3 REMOVED 2026-08-18. It mutated a per-FILE size check that every
    # caller bypassed once the cap moved to whole runs and session groups — the
    # surviving mutant proved the code unreachable, so the code was deleted
    # rather than the mutant weakened. The cap is measured by B1/B2 and by the
    # system-tail check below.
    ("B3", "under", "the system-tail cap never engages, so a grandfathered "
     "machine's four raw logs blow straight past the ceiling",
     [('            if written + len(data) > int(max_bytes):\n                dropped_sessions.append(f"system/{path.name}")\n                continue',
       '            if False:\n                dropped_sessions.append(f"system/{path.name}")\n                continue')],
     [T_BUNDLE]),
    ("B5", "under", "⛔ sessions are not collected, so the founding case — a "
     "machine that never got a run to start — sends nothing at all",
     [('        for members in sessions:\n            group_bytes = 0',
       '        for members in []:\n            group_bytes = 0')],
     [T_BUNDLE]),
    ("B6", "under", "the raw device tails are dropped, so a machine that has "
     "been running since before per-run capture existed sends no history",
     [('        for path in _system_log_tails():', '        for path in []:')],
     [T_BUNDLE]),
    ("B8", "under", "⛔⛔ the collected-file pattern widens to every .log, so the "
     "e2e transcripts and debugging dumps in that directory ship too",
     [('            if re.match(r"^backend(-\\d+)?\\.(err\\.)?log(\\.1)?$", name) or \\',
       '            if name.endswith(".log") or \\')],
     [T_BUNDLE]),
    ("B9", "under", "⛔⛔ the collector allowlist is gone, so anything on disk is "
     "collectable and the consent promise about passwords is void",
     [('    try:\n        Path(path).resolve().relative_to(_logs_root().resolve())\n        return True\n    except Exception:\n        return False',
       '    return True')],
     [T_BUNDLE]),
    ("B10", "under", "the allowlist stops resolving, so a symlink walks straight "
     "out of the log root",
     [('        Path(path).resolve().relative_to(_logs_root().resolve())',
       '        Path(path).relative_to(_logs_root())')],
     [T_BUNDLE]),
    ("B11", "under", "⛔ the raw log is read from the HEAD, so the tail — where "
     "the failure is — is exactly what gets left out",
     [('            if size > limit:\n                fh.seek(size - limit)',
       '            if size > limit:\n                fh.seek(0)')],
     [T_BUNDLE]),
    ("B12", "under", "the tail starts mid-line, so the first record a reader "
     "sees is a fragment",
     [('                nl = chunk.find(b"\\n")\n                return chunk[nl + 1:] if 0 <= nl < len(chunk) - 1 else chunk',
       '                return chunk')],
     [T_BUNDLE]),
    ("B13", "under", "⛔ collected.json disappears, so silent truncation reads as "
     "complete coverage",
     [('        }, indent=1).encode("utf-8"), "collected.json")',
       '        }, indent=1).encode("utf-8"), "unused.json")')],
     [T_BUNDLE]),
    ("B14", "under", "the manifest loses the install id, so a bundle sent while "
     "pairing was broken can never be linked to the account",
     [('            "installUuid": _install_uuid_best_effort(),', '')],
     [T_BUNDLE]),
    ("B15", "over", "the content type drifts from the one named constant, so an "
     "honest upload takes a 403 the retry ladder mislabels as transient",
     [('BUNDLE_CONTENT_TYPE = "application/zip"', 'BUNDLE_CONTENT_TYPE = "application/gzip"')],
     [T_BUNDLE]),
    ("B16", "under", "the index carries the run folder's absolute path, which "
     "names the operating-system account in the part a ticket quotes",
     [('        index = [{k: v for k, v in row.items() if k != "dir"} for row in selected]',
       '        index = [dict(row) for row in selected]')],
     [T_BUNDLE]),
    ("B17", "under", "the manifest stops naming the bounds it applied, so a "
     "reader cannot tell a small bundle from a truncated one",
     [('            "bounds": {"maxRuns": int(max_runs), "maxAgeDays": int(max_age_days),',
       '            "unused": {"maxRuns": int(max_runs), "maxAgeDays": int(max_age_days),')],
     [T_BUNDLE]),
    ("B18", "under", "a refused source is swallowed instead of recorded, so a "
     "collector pointed somewhere it should not be leaves no trace",
     [('        if not _bundle_source_is_allowed(src):\n            refused.append(str(src))\n            return False',
       '        if not _bundle_source_is_allowed(src):\n            return False')],
     [T_BUNDLE]),
    ("B19", "under", "the archive is stored uncompressed, turning a 700 KB "
     "bundle into 18 MB on a connection that is already the problem",
     [('    with _zipfile.ZipFile(dest, "w", compression=_zipfile.ZIP_DEFLATED) as zf:',
       '    with _zipfile.ZipFile(dest, "w") as zf:')],
     [T_BUNDLE]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        rc = subprocess.run([PY, "-m", "pytest", "-q", *tests], cwd=ROOT,
                            capture_output=True, timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
