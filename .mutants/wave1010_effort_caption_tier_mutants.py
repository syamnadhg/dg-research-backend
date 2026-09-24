"""Wave 10.10, leftover 4 — does Claude's effort caption name the tier the run
is ON once the computer-use pass has run, or the tier setup read before it?

The gap the verifier found: setup read Low, the computer-use pass moved the tier
to a THIRD one (High), and the tile said "researching at Low effort — Max could
not be set" about a run at High. The fix reads the tier off the model button in
the pre-send check (the button carries it: the 09-20 run's read "Opus 5 Low"),
names that tier in both the telemetry clause and the caption, and keeps setup's
read only for a button that shows no tier.

Every mutant below undoes one decision of that fix, or over-corrects it:

  S1-S3 — the detector: the button's tier is never read, is read PAGE-WIDE (the
          plan chip says "Max", so the caption goes silent about a Low run), or
          is read and dropped from what the detector hands back.
  S4-S8 — each word the Effort submenu labels a rung with drops out of the tier
          list, so a button showing that tier reads as showing none.
  S9    — any word on the label counts as a tier ("Model effort").
  P1-P3 — the consumer: the button's tier is ignored, setup's read is no longer
          the fallback (a button with no tier silences the caption), or setup's
          read wins over the button's.
  P4/P5 — the telemetry clause and the caption stop naming the SAME tier: one
          keeps setup's while the other names the button's.
  P6    — the pre-send check drops the button's tier on the way out.
  P7    — the helper is handed the tier ALONE instead of setup's record with the
          tier swapped in: setup's confirmation is lost, and the everyday run
          (setup confirmed Max, the button reads Max) logs a false note that the
          computer-use pass set it. Its verifier found it surviving every suite.

The effort caption's older mutants (E9, E10, T1-T7) live in
`wave1010_models_mutants.py`; every anchor they use is unchanged by this fix.

⛔ A KILL IS A FAILED OR ERRORED TEST, NEVER A SKIP. Fewer passes with more
skips is counted as a survivor: a pin that stops running looks exactly like one
that caught something.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout being measured:

  <venv>/bin/python -u .mutants/wave1010_effort_caption_tier_mutants.py
  <venv>/bin/python -u .mutants/wave1010_effort_caption_tier_mutants.py S2 P2
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
RESEARCH = "research.py"

#: The detector run through the shim, and the pre-send check + telemetry block
#: run end to end on what that detector hands back.
TESTS = ["tests/test_claude_mode_detect.py", "tests/test_claude_real_popover_0923.py"]

# ── anchors: the detector (`_CLAUDE_MODE_STATE_JS`) ─────────────────────────
SHOWN = "        effortShown = toks.find(t => TIERS.indexOf(t) !== -1);"
TIERS = "        const TIERS = ['low', 'medium', 'high', 'extra', 'max'];"
RETURN = "    return { hasExtended, researchOn, effortOk, effortShown };"

# ── anchors: the pre-send check and the telemetry block ─────────────────────
HANDED_BACK = '                    "effortShown": state.get("effortShown"),\n'
NOW = ('                _eff_now = ((mode_state or {}).get("effortShown")\n'
       '                            or _tstate.get("effort_got"))')
CLAUSE = '                    _pol.get("effort"), {**_tstate, "effort_got": _eff_now},'
CAPTION = '                    _pol.get("effort"), _eff_now)["notice"]'


def _tiers_without(word):
    kept = [w for w in ("low", "medium", "high", "extra", "max") if w != word]
    return "        const TIERS = [" + ", ".join(f"'{w}'" for w in kept) + "];"


MUTANTS = [
    # ══ 1. the detector reads the tier off the BUTTON ══════════════════════
    ("S1", "under", "⛔⛔ the button's tier is never read — the caption names setup's "
     "Low while the button says High, which is the gap itself",
     [(SHOWN, "        effortShown = undefined;")], RESEARCH, TESTS),
    ("S2", "over", "⛔⛔ the tier is read PAGE-WIDE — the plan chip says 'Max', the "
     "wanted tier, so the caption goes silent about a run at Low or High",
     [(SHOWN, "        effortShown = (document.body.innerText || '').toLowerCase()"
              ".split(/[^a-z0-9.]+/).find(t => TIERS.indexOf(t) !== -1);")],
     RESEARCH, TESTS),
    ("S3", "under", "the detector reads the tier and never hands it back",
     [(RETURN, "    return { hasExtended, researchOn, effortOk };")], RESEARCH, TESTS),

    # ══ 2. which words are a tier ═════════════════════════════════════════
    ("S4", "under", "a button showing Low (the 09-20 run's) reads as showing none",
     [(TIERS, _tiers_without("low"))], RESEARCH, TESTS),
    ("S5", "under", "a button showing Medium reads as showing none",
     [(TIERS, _tiers_without("medium"))], RESEARCH, TESTS),
    ("S6", "under", "a button showing High reads as showing none — the verifier's "
     "third tier is captioned with setup's Low again",
     [(TIERS, _tiers_without("high"))], RESEARCH, TESTS),
    ("S7", "under", "a button showing Extra reads as showing none",
     [(TIERS, _tiers_without("extra"))], RESEARCH, TESTS),
    ("S8", "under", "a button showing Max reads as showing none, for a policy that "
     "asks for less than Max",
     [(TIERS, _tiers_without("max"))], RESEARCH, TESTS),
    ("S9", "over", "any word on the label is a tier — 'Claude is researching at "
     "Model effort'",
     [(SHOWN, "        effortShown = toks.find(t => t);")], RESEARCH, TESTS),

    # ══ 3. the consumer names what the button shows ═══════════════════════
    ("P1", "under", "⛔⛔ the consumer ignores the button's tier — setup's read is "
     "named after the computer-use pass moved it",
     [(NOW, '                _eff_now = _tstate.get("effort_got")')], RESEARCH, TESTS),
    ("P2", "over", "⛔ setup's read is no longer the fallback — a button that shows "
     "no tier silences the caption about a run setup read at Low",
     [(NOW, '                _eff_now = (mode_state or {}).get("effortShown")')],
     RESEARCH, TESTS),
    ("P3", "under", "setup's read wins over the button's whenever setup read one",
     [(NOW, '                _eff_now = (_tstate.get("effort_got")\n'
            '                            or (mode_state or {}).get("effortShown"))')],
     RESEARCH, TESTS),
    ("P4", "under", "⛔ the telemetry clause keeps setup's tier while the tile names "
     "the button's — the log and the tile name two different tiers",
     [(CLAUSE, '                    _pol.get("effort"), _tstate,')], RESEARCH, TESTS),
    ("P5", "under", "⛔ the caption keeps setup's tier while the telemetry clause "
     "names the button's — the defect, on the tile only",
     [(CAPTION, '                    _pol.get("effort"), _tstate.get("effort_got"))["notice"]')],
     RESEARCH, TESTS),
    ("P6", "under", "the pre-send check drops the button's tier on the way out",
     [(HANDED_BACK, "")], RESEARCH, TESTS),
    ("P7", "under", "⛔⛔ the helper gets the tier alone, not setup's record with it "
     "swapped in — setup's confirmation is lost, and every everyday run (setup "
     "confirmed Max, the button reads Max) logs that the computer-use pass set it",
     [(CLAUSE, '                    _pol.get("effort"), {"effort_got": _eff_now},')],
     RESEARCH, TESTS),
]


# ── the runner ──────────────────────────────────────────────────────────────

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)")


def summary(tests):
    """pytest's own tally for `tests`, from its SUMMARY LINE — or a fault."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the tests ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines()
             if re.search(r" in [\d.]+s", ln) and _COUNT.search(ln)]
    if not lines:
        raise AssertionError("pytest printed no summary line — the run did not happen:\n"
                             + out[-1500:])
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for n, kind in _COUNT.findall(lines[-1]):
        if kind.startswith("error"):
            counts["error"] = int(n)
        elif kind in counts:
            counts[kind] = int(n)
    return counts


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`.
if __name__ == "__main__":
    only = set(sys.argv[1:])
    selected = [m for m in MUTANTS if not only or m[0] in only]
    files = sorted({m[4] for m in selected})
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in files}

    baselines = {}
    print("baseline… ", end="", flush=True)
    for tests in sorted({tuple(m[5]) for m in selected}):
        try:
            got = summary(list(tests))
        except AssertionError as e:
            print(f"⛔ BASELINE FAULT for {' '.join(tests)}: {e}")
            sys.exit(2)
        if got["failed"] or got["error"] or got["skipped"] or not got["passed"]:
            print(f"⛔ BASELINE NOT CLEAN for {' '.join(tests)}: {got} — a skip in "
                  f"the baseline is a pin that measures nothing")
            sys.exit(2)
        baselines[tests] = got
    print("green\n", flush=True)

    survivors, faults = [], []
    for mid, direction, why, edits, fname, tests in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            got = summary(tests)
            if got["failed"] or got["error"]:
                print(f"  {mid}  ✓ killed  {got}", flush=True)
            else:
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}  {got}", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    over = sum(1 for m in selected if m[1] == "over")
    print(f"\n{measured - len(survivors)}/{measured} killed ({over} over-corrections)")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
