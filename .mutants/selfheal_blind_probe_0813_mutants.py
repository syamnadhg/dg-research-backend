"""Mutation harness for the blind-probe fix.

The fix makes "we saw nothing" distinguishable from "we saw breakage". Both
directions are real failures:

  UNDER — go back to `would_heal = not ok`, or drop the blind counter, or let
  blind samples back into the match rate. Each restores the 2026-08-13 state
  where the drift canary alarmed on two regions nobody had looked at.

  OVER — ⛔ the more dangerous one: silence a REAL failure. If `would_heal`
  stops firing on a probe that actually saw the region and found it broken, or
  a genuinely drifted intent stops reading DRIFT, then the fix has not made the
  signal honest — it has deleted it, and the whole point of shadow mode is to
  catch rot before it costs a run.

Plus the call-site half: observing a dialog-scoped intent after the dialog is
dismissed can only ever record an empty probe, so the ORDER is the fix.

    .venv/bin/python .mutants/selfheal_blind_probe_0813_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_selfheal_blind_probe_0813.py "
          "tests/test_selfheal_wiring.py "
          "tests/test_selfheal_report.py "
          "tests/test_selfheal_foundation.py "
          "tests/test_selfheal_drift.py "
          "tests/test_selfheal_act.py "
          "tests/test_selfheal_resolver.py")

RESEARCH = "research.py"
REPORT = "scripts/selfheal_report.py"

MUTANTS = [
    # ═══════════════════ the observer (research.py) ════════════════════════
    ("U1", RESEARCH, "under", "⭐ would_heal is back to `not ok` — a blank page counts as drift",
     [('            "would_heal": (not ok) and _observed,', '            "would_heal": not ok,')]),
    ("U2", RESEARCH, "under", "probe_empty is never written — the report must infer it again",
     [('            "probe_empty": not _observed,\n', "")]),
    ("U3", RESEARCH, "under", "probe_empty always says 'we saw something'",
     [('            "probe_empty": not _observed,', '            "probe_empty": False,')]),
    ("O1", RESEARCH, "over", "⛔ would_heal never fires — a real observed failure is silenced",
     [('            "would_heal": (not ok) and _observed,', '            "would_heal": False,')]),
    ("O2", RESEARCH, "over", "⛔ `_observed` is inverted — only blind samples count as heals",
     [("        _observed = bool(snap)", "        _observed = not bool(snap)")]),

    # ══════════════════ the call site (research.py) ════════════════════════
    ("C1", RESEARCH, "under", "⭐ the dialog observations move back after the Save click",
     [('        if selfheal and selfheal.is_enabled():\n'
       '            await _selfheal_shadow_observe(page, "notebooklm.set_public_access",\n'
       "                                           outcome_pass=bool(public_verified))\n"
       '            await _selfheal_shadow_observe(page, "notebooklm.copy_share_link",\n'
       "                                           outcome_pass=is_notebooklm_url(url))\n\n"
       "        # Step 3b: Click Save/Done to apply the sharing change.",
       "        # Step 3b: Click Save/Done to apply the sharing change.")]),
    ("C2", RESEARCH, "under", "only ONE of the two moves — the other keeps probing a closed dialog",
     [('            await _selfheal_shadow_observe(page, "notebooklm.copy_share_link",\n'
       "                                           outcome_pass=is_notebooklm_url(url))\n", "")]),
    ("C3", RESEARCH, "over", "the flag gate is dropped — shadow runs in production by default",
     [("        if selfheal and selfheal.is_enabled():\n"
       '            await _selfheal_shadow_observe(page, "notebooklm.set_public_access",',
       "        if selfheal:\n"
       '            await _selfheal_shadow_observe(page, "notebooklm.set_public_access",')]),
    ("C4", RESEARCH, "over", "the predicate becomes a hardcoded pass — the 'noise' defect, again",
     [("                                           outcome_pass=bool(public_verified))",
       "                                           outcome_pass=True)")]),

    # ════════════════════ the report (selfheal_report.py) ══════════════════
    ("R1", REPORT, "under", "⭐ blind samples are back in the match rate — DRIFT on an unseen region",
     [("            if _blind:\n"
       '                s["resolver_blind"] += 1\n'
       "            else:\n"
       '                s["resolver_seen"] += 1\n'
       '                if rec.get("heal_match_found") is True:\n'
       '                    s["resolver_matched"] += 1\n'
       "                hc = rec.get(\"heal_confidence\")\n"
       "                if isinstance(hc, (int, float)):\n"
       '                    s["heal_conf_sum"] += float(hc)\n'
       '                    s["heal_conf_n"] += 1',
       '            s["resolver_seen"] += 1\n'
       '            if rec.get("heal_match_found") is True:\n'
       '                s["resolver_matched"] += 1\n'
       "            hc = rec.get(\"heal_confidence\")\n"
       "            if isinstance(hc, (int, float)):\n"
       '                s["heal_conf_sum"] += float(hc)\n'
       '                s["heal_conf_n"] += 1')]),
    ("R2", REPORT, "under", "a legacy blind would_heal is counted again",
     [('        if rec.get("would_heal") is True and not _blind:',
       '        if rec.get("would_heal") is True:')]),
    ("R3", REPORT, "under", "the blind counter never increments",
     [('        if _blind:\n            s["empty_probe"] += 1', "        if False:\n            pass")]),
    ("R4", REPORT, "under", "⛔ a never-observed intent reads DRIFT again",
     [('            if not seen:\n                verdict = "not observed"\n            elif fr < 1.0:',
       '            if fr < 1.0:')]),
    ("R5", REPORT, "under", "the all-blind row loses its warning",
     [('        flag = "   ⚠ never observed" if n and blind == n else ""', '        flag = ""')]),
    ("R6", REPORT, "under", "the blind column is dropped from the table",
     [("f\"{s['would_heal']:>7}{avg:>8.1f}{blind:>7}{flag}\")",
       "f\"{s['would_heal']:>7}{avg:>8.1f}\")")]),
    ("O3", REPORT, "over", "⛔ every intent reads 'not observed' — real drift is silenced",
     [('            if not seen:\n                verdict = "not observed"',
       '            if True:\n                verdict = "not observed"')]),
    ("O4", REPORT, "over", "⛔ probe_empty is trusted over the count, so 0 probes grade as seen",
     [('        _blind = (rec.get("probe_empty") is True or pc == 0)',
       '        _blind = (rec.get("probe_empty") is True)')]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--",
              "research.py", "tests", "scripts"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=180).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, target, direction, why, edits in MUTANTS:
        path = ROOT / target
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found in {target}: {frm[:60]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, f"ANCHOR MISS: {exc}"))
        finally:
            path.write_text(original, encoding="utf-8")

    still_dirty = tracked_dirty()
    if still_dirty:
        print("\n⛔ the tree did not come back clean:\n" + "\n".join(still_dirty))
        return 2

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    for mid, direction, why in survivors:
        print(f"  SURVIVED {mid} [{direction}] {why}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
