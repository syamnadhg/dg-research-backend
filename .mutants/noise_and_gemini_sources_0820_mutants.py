"""Mutation harness for the 08-20 false-alarm batch + Gemini's dead source arm.

⛔ THE REPORT (owner, 2026-08-20): I named three "problems" off the 08-19 run that
were not problems, and they pushed back — *"Maybe the logging is raising false
alarms. Please go through that."* All three were mine to own: ChatGPT's
conversation URL is that agent's intended ending, Claude's artifact panel worked,
and the queued→ongoing 403 is a compensated no-op. I had reported log SEVERITY as
system health.

⭐⭐ AND THE EXERCISE FOUND A REAL DEFECT the log had been silent about. Gemini's
source selector ends in `a[href*="http"]:not(…)` — which matches ANCHORS — and the
next line asked each match for a CHILD anchor. `querySelector` searches
descendants, so an `<a>` always answered null and every match was dropped. The
broadest arm contributed nothing.

⛔⛔ AND TWO SHIM GAPS MEANT NO TEST COULD HAVE CAUGHT IT. `:not()` was
unmatchable (the qualifier pattern never accepted a `:`), and a dot inside an
attribute VALUE was read as a class selector — so `[href*="accounts.google"]` also
required `class="google"` and matched nothing. Dead in production AND unmatchable
in the harness, and the two are indistinguishable from outside.

⭐ THE OVER-CORRECTIONS ARE THE RISK, because "make the log quieter" is one step
from "make the log lie the other way":
  F3 — the genuinely unresolved path (transaction refused AND the fallback read
       failed) also goes quiet. Nobody then knows the status, and that is the one
       case a person CAN act on.
  F5 — the suppressor keys on nothing, so a NEW failure class is swallowed by the
       first one's marker. The root cause here is still unnamed.
  G4 — the exclusion list is dropped while widening the arm, so Google's own
       sign-in URLs and Gemini's own conversation URL count as citations.

    .venv/bin/python .mutants/noise_and_gemini_sources_0820_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "research.py"
SHIM = "tests/_domshim.py"
MUTATED_FILES = [SRC, SHIM]

T_NEW = "tests/test_noise_and_gemini_sources_0820.py"
# ⛔ The sibling suites that own parts of this same source. Reporting "real suite
# gaps" that are only this harness's scope has happened repeatedly here.
T_P1 = "tests/test_p1_structural_anchor_0820.py"
T_GEM = "tests/test_gemini_stop_split_0819.py"
T_CHIPS = "tests/test_p1_inline_chips_0819.py"
ALL = [T_NEW, T_P1, T_GEM, T_CHIPS]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

_ANCHOR_FIX = """                const a = (s.tagName === 'A') ? s
                        : (s.querySelector ? s.querySelector('a') : s);"""
_EXCLUDES = """                'a[href*="http"]:not([href*="google.com/gemini"])'
                + ':not([href*="accounts.google"]):not([href*="gemini.google"])'"""
_NOT_STRIP = """  p = p.replace(/:not\\(([^()]*)\\)/g, (_m, inner) => { nots.push(inner); return ''; });"""
_BARE = """  const bare = m[2].replace(/\\[[^\\]]*\\]/g, '');"""

MUTANTS: list[tuple[str, str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ Gemini's dead arm ══════════════════════════════════════════════════
    ("G1", SRC, "under", "⭐⭐ THE ORIGINAL BUG — every matched anchor is asked "
     "for a CHILD anchor again, so the broadest arm of the selector contributes "
     "nothing and an 82,817-character report reports zero sources",
     [(_ANCHOR_FIX, "                const a = s.querySelector ? s.querySelector('a') : s;")],
     [T_NEW]),
    # ⛔ G2 ("take the element unconditionally") WAS REMOVED as an EQUIVALENT
    # mutant: once the anchor arm works, every container's inner link is matched
    # by that arm independently, so dropping the conditional loses nothing on any
    # realistic page. It survived by construction, which is a harness bug.
    # Removing it is what surfaced G2b below — the container arm's real defect.
    ("G2b", SRC, "over", "⛔⛔ the host guard moves off the RESOLVED url, so a "
     "container arm (.source-card wrapping accounts.google) smuggles an excluded "
     "host in as a citation — the exclusion list guards only the anchor arm",
     [("                        && !SELF.test(href)) srcSet.add(href);",
       "                        ) srcSet.add(href);")],
     [T_NEW]),
    ("G2c", SRC, "under", "the host guard rejects everything, so a report with "
     "real citations reports none",
     [("                const SELF = /accounts\\\\.google|google\\\\.com\\\\/gemini"
       "|gemini\\\\.google/i;",
       "                const SELF = /./i;")],
     [T_NEW]),
    ("G3", SRC, "under", "the whole document-wide arm is removed, leaving only "
     "the container classes — which is where this started",
     [(_EXCLUDES, "                'a[href*=\"nothing-matches-this\"]'")],
     [T_NEW]),
    # ⛔ G4 and G5 WERE RETIRED as EQUIVALENT mutants, and the reason is the
    # fix itself. Both broke the `:not(...)` list on the SELECTOR — and the host
    # exclusion no longer lives there. It moved onto the RESOLVED url (`SELF`),
    # because the selector's list guarded only the anchor arm and a container arm
    # smuggled `accounts.google` straight past it. So mutating the selector list
    # now changes nothing observable: the resolved-url guard catches the same
    # hosts either way. They survived by construction, which is a harness bug and
    # not a suite gap. G2b/G2c below test the guard where it actually is, and
    # G3 still covers losing the arm entirely.
    ("G6", SRC, "under", "the provenance collapses to one number, so the next "
     "zero cannot be told apart from a blind selector or a panel that never opened",
     [("            r.src_panel = _panelSrcCount;\n"
       "            r.src_page = srcSet.size - _panelSrcCount;",
       "            r.src_panel = 0;\n            r.src_page = 0;")],
     [T_NEW]),
    ("G7", SRC, "under", "the Gemini source line stops being logged at all — "
     "which is the state that made this undiagnosable from a run",
     [('                if _gsrc != p.get("gemini_src_last"):',
       "                if False:")],
     [T_NEW]),
    ("G8", SRC, "over", "the source line prints every cycle instead of on change "
     "— wave 2's flood lesson, re-learned on the fix for wave 1's blindness",
     [('                if _gsrc != p.get("gemini_src_last"):', "                if True:")],
     [T_NEW]),

    # ══ the false alarms ═══════════════════════════════════════════════════
    ("F1", SRC, "under", "the flip 403 goes back to WARN, so a compensated no-op "
     "shouts at the operator once per run again",
     [('                    + logquiet.suppressed_note(_flip_dropped),\n'
       '                    "DEBUG",',
       '                    + logquiet.suppressed_note(_flip_dropped),\n'
       '                    "WARN",')],
     [T_NEW]),
    ("F2", SRC, "under", "the line goes back to calling it a failure, which is "
     "the wording that made me report it as one",
     [('                    f"[flip] could not open the queued→ongoing transaction for "',
       '                    f"Failed to flip queued→ongoing for "')],
     [T_NEW]),
    ("F3", SRC, "over", "⛔⛔ the path where the fallback read ALSO failed is "
     "quietened too. Nobody then knows the status — the one case in this whole "
     "batch that a person can actually act on",
     [('                        log("[flip] the transaction was refused and the doc could "\n'
       '                            "not be read either — proceeding, as before", "WARN")',
       '                        log("[flip] the transaction was refused and the doc could "\n'
       '                            "not be read either — proceeding, as before", "DEBUG")')],
     [T_NEW]),
    ("F4", SRC, "under", "the suppressor is removed, so the full transaction "
     "diagnostic prints on every attempt again",
     [("            if _emit_flip:", "            if True:")],
     [T_NEW]),
    ("F5", SRC, "over", "⛔ the suppressor keys on nothing, so a DIFFERENT failure "
     "class is swallowed by the first one's marker — and the root cause here is "
     "still unnamed, so that is exactly the signal we would lose",
     [('            _emit_flip, _flip_dropped = _FLIP_403_QUIET.consider(\n'
       '                "flip-txn-refused", f"{type(_root).__name__ if _root else type(e).__name__}")',
       '            _emit_flip, _flip_dropped = _FLIP_403_QUIET.consider(\n'
       '                "flip-txn-refused", "same")')],
     [T_NEW]),
    ("F6", SRC, "over", "the suppressor widens instead of speaking once, so the "
     "line comes back every fifth and fifteenth attempt",
     [("_FLIP_403_QUIET = logquiet.Suppressor(logquiet.ONCE)",
       "_FLIP_403_QUIET = logquiet.Suppressor()")],
     [T_NEW]),
    ("F7", SRC, "under", "Claude's panel line goes back to WARN, four seconds "
     "before the report is read out of that very panel",
     [('                        f"and normally succeed; a probe gap, not a closed panel",\n'
       '                        "DEBUG")',
       '                        f"and normally succeed; a probe gap, not a closed panel",\n'
       '                        "WARN")')],
     [T_NEW]),
    ("F8", SRC, "under", "the wording goes back to asserting the panel is shut, "
     "which is the claim the extraction contradicts nine seconds later",
     [('                    log(f"[{label}] the probe still cannot confirm the artifact "',
       '                    log(f"[{label}] CUA panel-open recovery ran but panel still not "')],
     [T_NEW]),

    # ══ the shim gaps that hid all of it ═══════════════════════════════════
    ("S1", SHIM, "under", "⛔⛔ `:not()` becomes unmatchable again, so every "
     "production selector carrying one matches NOTHING — silently, which is how "
     "an exclusion list that cannot exclude passed for one that works",
     [(_NOT_STRIP, "  p = p;")],
     [T_NEW]),
    ("S2", SHIM, "over", "`:not()` is stripped but never enforced, so an "
     "exclusion selector admits exactly what it exists to reject",
     [("""  for (const n of nots) {
    if (n.split(',').map(s => s.trim()).filter(Boolean)
         .some(x => matchSimple(el, x))) return false;
  }""", "  for (const n of nots) { void n; }")],
     [T_NEW]),
    ("S3", SHIM, "under", "⛔⛔ the class scan goes back over the bracket "
     "contents, so a dot in an attribute VALUE is read as a class selector and "
     "`[href*=\"accounts.google\"]` silently requires `class=\"google\"`",
     [(_BARE, "  const bare = m[2];")],
     [T_NEW]),
    ("S4", SHIM, "over", "class selectors stop being enforced at all — the "
     "opposite failure, and `.source-card` would then match every element",
     [("""  for (const cls of (bare.match(/\\.[A-Za-z0-9_-]+/g) || [])) {
    if (!el.classList.contains(cls.slice(1))) return false;
  }""", "  void bare;")],
     [T_NEW]),
]


def green(tests):
    try:
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def skipped(tests) -> int:
    """Every executed-JS test here needs node; without it a clean sweep would
    have measured nothing."""
    try:
        out = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                              *tests], cwd=ROOT, capture_output=True, text=True,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                             timeout=_TEST_TIMEOUT_S).stdout
    except subprocess.TimeoutExpired:
        return 0
    for line in out.splitlines():
        if "skipped" in line:
            for part in line.replace("=", " ").split(","):
                if "skipped" in part:
                    for tok in part.split():
                        if tok.isdigit():
                            return int(tok)
    return 0


def snapshot():
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before):
    return [f for f, t in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != t]


def main() -> int:
    before = snapshot()
    print("baseline… ", end="", flush=True)
    ok, t_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if t_out else 'RED'}. Nothing below would mean anything.")
        return 2
    n_skip = skipped([T_NEW])
    print(f"green ({n_skip} skipped)", flush=True)
    if n_skip:
        print(f"⚠ {n_skip} test(s) SKIPPED — without node every executed-JS mutant "
              "below measures NOTHING.")

    survivors, stale = [], []
    for mid, path, direction, why, edits, tests in MUTANTS:
        target = ROOT / path
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs 1): {frm[:60]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, t_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed)" if t_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif t_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
