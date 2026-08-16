"""Mutation harness for the non-pro Claude fallback (2026-08-14).

⭐ THE SHAPE OF THE WRONG FIX HERE IS OVER-CORRECTION, and by a wide margin. The
feature is "notice that this account's plan excludes the model family, and use
the fallback family instead" — so every cheap way to write it is a way to fire
it too often:

  * dropping the `chips` requirement (D1) makes a RENAME look like a plan limit,
    which converts a loud, fixable rollout regression into a permanent silent
    downgrade on every affected account;
  * dropping the `n == 0` requirement (D2) makes ONE upsell chip beside genuine
    rows — normal on a paid account — downgrade a pro user;
  * dropping the mounted-menu requirement (D3) lets a popover that has not
    rendered yet answer the question;
  * recording the family from the DIAGNOSIS rather than from a PICK (S2) tells
    every later reader in the run to assert on a family nothing selected;
  * and losing the cross-run wipe (S3) is the worst of all: one visit from a
    non-pro account would teach the worker process a fallback family that every
    later run inherits, including runs signed into a Pro account.

The under-corrections are the couplings. Each of them leaves the fallback
PRESENT and INERT in a different way — the pick lands and something downstream
undoes it — which is precisely the failure mode a green suite is worst at
catching, because nothing crashes and the model is merely wrong.

⚠ `prompts.py` renders its two Claude constants at IMPORT from the builders, so
a mutant in a builder reaches both the per-call render and the frozen constant.
That is intended: they must not be able to disagree.

⛔ EVERY REPLACEMENT MUST STILL RESOLVE. C7/C8 mutate the CUA call sites to the
argument-less render rather than to the module constants — research.py no longer
imports those, so a constant there would raise NameError and the mutant would be
recorded as killed by an import error rather than by anything the suite asserts.
A mutant that dies for the wrong reason is a mutant that measured nothing.

    .venv/bin/python .mutants/free_family_fallback_0814_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_SUITES = ("tests/test_free_family_fallback_0814.py "
               "tests/test_review_blockers_0813.py "
               "tests/test_review_wave2_0813.py "
               "tests/test_model_policy.py "
               "tests/test_prompts_model_policy.py "
               "tests/test_claude_model_pick.py "
               "tests/test_claude_popover_skip.py "
               "tests/test_claude_mode_detect.py "
               "tests/test_known_good_fallback.py "
               "tests/test_onthefly_learning.py "
               "tests/test_model_selection_precision.py")

MUTATED_FILES = ("research.py", "models.py", "prompts.py")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ the detector — three cases, three answers ══════════════════
    ("D1", "research.py", "over",
     "⛔ the chips requirement is dropped, so a RENAMED family (no rows, no "
     "chips) reads as a plan limit — a loud rollout regression becomes a "
     "permanent silent downgrade",
     [('        if probe.get("menu") and not probe.get("n") and probe.get("chipsAny"):',
       '        if probe.get("menu") and not probe.get("n"):')]),
    ("D2", "research.py", "over",
     "⛔ the no-real-rows requirement is dropped, so ONE upsell chip beside "
     "genuine rows — normal on a paid account — downgrades a pro user",
     [('        if probe.get("menu") and not probe.get("n") and probe.get("chipsAny"):',
       '        if probe.get("menu") and probe.get("chips"):')]),
    ("D3", "research.py", "over",
     "⛔ the mounted-menu requirement is dropped, so a popover that has not "
     "rendered answers the question",
     [('        if probe.get("menu") and not probe.get("n") and probe.get("chipsAny"):',
       '        if not probe.get("n") and probe.get("chips"):')]),
    ("D4", "research.py", "over",
     "⛔ an unreadable probe becomes a plan limit — a page.evaluate failure now "
     "changes the model",
     [('            log(f"[setup_claude_dr] Step 1B† plan probe errored "\n'
       '                f"({type(exc).__name__}) — not treating this as a plan limit", "WARN")\n'
       '            return False',
       '            log(f"[setup_claude_dr] Step 1B† plan probe errored "\n'
       '                f"({type(exc).__name__}) — not treating this as a plan limit", "WARN")\n'
       '            return True')]),
    ("D5", "research.py", "under",
     "the detector always says no — the whole feature is present and inert",
     [('        if probe.get("menu") and not probe.get("n") and probe.get("chipsAny"):\n'
       '            return True',
       '        if False:\n            return True')]),
    ("D6", "research.py", "under",
     "a mounted menu with REAL rows keeps being re-polled instead of settling "
     "the question — a second of latency added to ordinary runs at the one "
     "seam that already failed",
     [('        if probe.get("menu") and probe.get("n"):\n            return False',
       '        if False:\n            return False')]),
    ("D8", "research.py", "over",
     "⛔ the verdict goes back to the ROW-FILTERED count, which is blind to a "
     "chip rendered as a plain div or li — the whole fallback silently does "
     "nothing on that markup, which is the shape it shipped with",
     [('        if probe.get("menu") and not probe.get("n") and probe.get("chipsAny"):',
       '        if probe.get("menu") and not probe.get("n") and probe.get("chips"):')]),
    ("D9", "research.py", "over",
     "⛔ every element counts as a chip regardless of its text, so a perfectly "
     "ordinary menu with no rows yet reads as a plan limit",
     [("                if (isUpsell(raw)) {\n                    chipsAny = true;",
       "                chipsAny = true;\n                if (isUpsell(raw)) {")]),
    ("D7", "research.py", "under",
     "⭐ the retry is gone, so a menu one beat from finishing its render reads "
     "as the rename case and the account never reaches its fallback",
     # ⚠ Anchored on the docstring's last line too — the bare `for` line is a
     # substring of two deeper-indented loops elsewhere in this file.
     [('    """\n    for _attempt in range(3):', '    """\n    for _attempt in range(1):')]),

    # ═══════════ the seam ════════════════════════════════════════════════════
    ("S1", "research.py", "under",
     "⭐ the fallback branch never runs — Step 1B FAIL returns as before, so "
     "effort is never set and the CUA rungs go hunting for the excluded family",
     [("                if not opus_selected and _claude_family == _claude_primary \\\n"
       "                        and _claude_free_family:",
       "                if False:")]),
    ("S2", "research.py", "over",
     "⛔ the family is recorded from the DIAGNOSIS rather than from a PICK, so "
     "a plan limit with no clickable fallback row still tells every later "
     "reader to assert on a family nothing selected",
     [('                        if opus_selected:\n'
       '                            # ⚠ RECORDED BEFORE Step 1C runs',
       '                        if True:\n'
       '                            # ⚠ RECORDED BEFORE Step 1C runs')]),
    ("S3", "research.py", "over",
     "⛔⛔ the cross-run wipe is gone — ONE non-pro run teaches this worker a "
     "fallback family that every later PRO run inherits, silently, with model "
     "selection reporting success",
     [("    _P2_ACTIVE_FAMILY.clear()\n", "")]),
    ("S4", "research.py", "over",
     "⛔ the fallback pick inherits the FAILED family's version bounds, so a "
     "step-back that reaches it filters the new family's rows against a number "
     "measured on the other one",
     [('                        _pick_args = {**_pick_args, "fam": _claude_family,\n'
       '                                      "pin": None, "below": None}',
       '                        _pick_args = {**_pick_args, "fam": _claude_family}')]),
    ("S5", "research.py", "under",
     "the run's family is never recorded, so the pick lands and the very next "
     "pass reads it as a regression",
     [('                            _P2_ACTIVE_FAMILY["claude"] = _claude_family\n', "")]),

    # ═══════════ the run-scoped reader ══════════════════════════════════════
    ("R1", "research.py", "under",
     "⭐ the reader always answers with the POLICY family, so the fallback is "
     "recorded and never read — present, inert, and invisible",
     [("    if fam and fam in (p2_family(p), p2_free_family(p)):\n        return fam",
       "    if False:\n        return fam")]),
    ("R2", "research.py", "over",
     "⛔ the reader stops validating, so a stale word from a policy edit is "
     "interpolated straight into four `new RegExp` sites",
     [("    if fam and fam in (p2_family(p), p2_free_family(p)):\n        return fam",
       "    if fam:\n        return fam")]),

    # ═══════════ the couplings — each leaves the fix present and undone ══════
    ("C1", "research.py", "under",
     "⛔ the pre-send check asserts on the POLICY family again, so a correct "
     "fallback composer reads as 'mode regressed' and the ENTIRE Claude setup "
     "re-runs before every single send",
     [('            _cl_family = _p2_active_family("claude") or "opus"',
       '            _cl_family = p2_family("claude") or "opus"')]),
    ("C2", "research.py", "under",
     "the family is not re-read after the re-activation, so the pass that "
     "DISCOVERS the plan limit reports the fix it just made as still broken",
     [('                _cl_family = _p2_active_family("claude") or _cl_family\n', "")]),
    ("C3", "research.py", "under",
     "the ladder's outcome probe asks about the policy family, so it answers "
     "'unknown' every pass and the CUA validator it exists to skip runs anyway",
     [('                _CLAUDE_MODE_STATE_JS, _p2_active_family("claude") or "opus") or {}',
       '                _CLAUDE_MODE_STATE_JS, p2_family("claude") or "opus") or {}')]),
    ("C4", "research.py", "under",
     "⛔ the step-back pin is read from the primary family's slot again — a "
     "version learned on one family, hunted for on the other",
     [("                _kg = p2_known_good(platform_l, _step_fam)",
       "                _kg = p2_known_good(platform_l)")]),
    ("C5", "research.py", "under",
     "the learned version is written into the other family's slot, planting it "
     "for a later run that cannot use it",
     [("            record_known_good(platform_l, _P2_PICKED_VERSION.get(platform_l),\n"
       "                              _p2_active_family(platform_l))",
       "            record_known_good(platform_l, _P2_PICKED_VERSION.get(platform_l))")]),
    ("C6", "research.py", "under",
     "⛔⛔ the validate CUA mission freezes to the policy family again — its "
     "'only touch the model if it is not <fam>' clause then fires on the "
     "CORRECT model and sends the agent back into the chip menu",
     [('        "claude": p2_claude_validate_directive(_p2_active_family("claude")),',
       '        "claude": p2_claude_validate_directive(),')]),
    ("C7", "research.py", "under",
     "the validate SYSTEM prompt freezes while its user message does not — one "
     "CUA call holding two instructions that disagree about the model",
     [('        "claude": claude_validate_setup_prompt(_p2_active_family("claude")),',
       '        "claude": claude_validate_setup_prompt(),')]),
    ("C8", "research.py", "under",
     "the retry's CUA setup mission freezes, so the pass that follows a proved "
     "plan limit is sent hunting for the excluded family again",
     [('            claude_deep_research_prompt(_p2_active_family("claude")),\n'
       '            p2_claude_setup_directive(_p2_active_family("claude")),',
       '            claude_deep_research_prompt(),\n'
       '            p2_claude_setup_directive(),')]),

    # ═══════════ the policy ═════════════════════════════════════════════════
    ("P1", "models.py", "under",
     "the policy loses its fallback family, so every non-pro account is back to "
     "a failed setup",
     [('        "free_family": "sonnet",\n', "")]),
    ("P2", "models.py", "over",
     "⛔ a fallback EQUAL to the primary family is honoured — the retry re-runs "
     "the same picker over the same refused rows and logs a switch that did "
     "not happen",
     [('    return "" if not free or free == p2_family(platform) else free',
       '    return free')]),
    ("P3", "models.py", "over",
     "⛔ the fallback word skips sanitation, so an overlay metacharacter throws "
     "inside the browser and takes model selection down on exactly the accounts "
     "that need this path",
     [('    free = _family_word(platform, "free_family")',
       '    free = str(p2_labels(platform).get("free_family") or "").lower().strip()')]),
    ("P4", "models.py", "over",
     "⛔ the known-good slot ignores the family again — a version learned on one "
     "family is read back as the other's",
     [('    if not fam or fam == p2_family(platform):\n        return "known_good"',
       '    if True:\n        return "known_good"')]),
    ("P5", "models.py", "over",
     "⛔ even the PRIMARY family gets a suffixed slot, stranding every value "
     "already on disk",
     [('    if not fam or fam == p2_family(platform):\n        return "known_good"',
       '    if not fam:\n        return "known_good"')]),

    # ═══════════ the missions ═══════════════════════════════════════════════
    ("M1", "models.py", "under",
     "the setup directive ignores the family it is handed",
     [('    fam = (str(family) or primary).capitalize()                # "Opus" / "Sonnet"',
       '    fam = primary.capitalize()')]),
    ("M2", "models.py", "under",
     "⛔ the validate directive ignores the family it is handed — the mission "
     "that runs after a SUCCESSFUL setup is the one that undoes it",
     [('    fam = (str(family) or primary).capitalize()\n'
       '    effort = str(pol.get("effort", "max")).capitalize()\n'
       '    tool = str(pol.get("tool", "research")).capitalize()\n'
       '    swapped = "" if fam.lower() == primary.lower() else \\\n'
       '        f"{free_family_note(primary.capitalize(), fam)} "\n'
       '    return (\n'
       '        f"{swapped}Verify Claude is on {fam}',
       '    fam = primary.capitalize()\n'
       '    effort = str(pol.get("effort", "max")).capitalize()\n'
       '    tool = str(pol.get("tool", "research")).capitalize()\n'
       '    swapped = ""\n'
       '    return (\n'
       '        f"{swapped}Verify Claude is on {fam}')]),
    ("M3", "models.py", "over",
     "⛔ the switched-family sentence is added on the PRO render too, telling a "
     "paid account its plan excludes the model it is running",
     [('    swapped = "" if fam.lower() == primary.lower() else \\\n'
       '        f"{free_family_note(primary.capitalize(), fam)} "\n'
       '    return (\n'
       '        f"{swapped}Ensure the model is {fam}',
       '    swapped = f"{free_family_note(primary.capitalize(), fam)} "\n'
       '    return (\n'
       '        f"{swapped}Ensure the model is {fam}')]),
    ("M4", "models.py", "over",
     "⛔ the switched-family sentence becomes the generic chip warning, which "
     "ends 'leave the model exactly as it is and move on' — the exact opposite "
     "of what a mission sent to select a different family must do",
     [('        f"Do not click one and do not read one as {excluded} being available — "\n'
       '        f"{use_instead} is the correct model on this account."',
       '        f"leave the model exactly as it is and move on."')]),
    ("M5", "prompts.py", "under",
     "the CUA system prompt ignores the family, so it and the user directive "
     "disagree about which model is correct",
     [('    fam = (str(family) or _OPUS).capitalize()', '    fam = _OPUS.capitalize()')]),
    ("M6", "prompts.py", "over",
     "⛔ the validate prompt's wrong-model examples come back — 'if the button "
     "shows Sonnet/Haiku with no Sonnet at all' is satisfied by the CORRECT "
     "model on a fallback run",
     [('ONLY touch the model if the button does not name "{fam}" anywhere at all:',
       'ONLY touch the model if the button shows Sonnet/Haiku with no {fam} at all:')]),

    # ═══════════ the Vision hints ═══════════════════════════════════════════
    ("V1", "research.py", "under",
     "the shadow hint keeps the raw token, so Vision is told to look for a "
     "model called '{claude_family}'",
     # ⚠ Anchored with the preceding newline+indent: the 4-space form is a
     # SUBSTRING of the 8-space observe-path line, so the bare text is ambiguous.
     [("\n    _hint = _sub_claude_family(_HOTSPOT_VISION_HINTS.get(hotspot_id, {}))",
       "\n    _hint = _HOTSPOT_VISION_HINTS.get(hotspot_id, {})")]),
    ("V2", "research.py", "over",
     "⛔ the substitution mutates the module catalog, so the first run to fall "
     "back bakes its family into every later run in this process",
     [("    out = dict(hint)", "    out = hint")]),
    ("V3", "research.py", "under",
     "the success-path hint is left un-substituted while the miss-path one is "
     "not — the two calls the shadow tier COMPARES now aim at different models",
     [("        _hint = _sub_claude_family(_HOTSPOT_VISION_HINTS.get(hotspot_id, {}))",
       "        _hint = _HOTSPOT_VISION_HINTS.get(hotspot_id, {})")]),
]

ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

# ⚠ Not optional — see wave 1. The dev venv holds an editable install of a
# DIFFERENT checkout of these same module names, so a test process can resolve
# the unmutated copy and record a phantom survivor.
SURVIVOR_CONFIRMATIONS = 3


def sh(cmd: list[str], *, cwd=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                          env=env or ENV)


def purge_pycache() -> None:
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES, "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    purge_pycache()
    return sh([sys.executable, "-B", "-m", "pytest", *ROOT_SUITES.split(),
               "-q", "-p", "no:cacheprovider"]).returncode == 0


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
    for mid, fname, direction, why, edits in MUTANTS:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                # ⛔⛔ UNIQUENESS, NOT MERE PRESENCE. `str.replace(…, 1)` takes the
                # FIRST match in the file, and an anchor that is a substring of a
                # more-indented line elsewhere matches THAT instead — silently,
                # with no error, mutating a function the mutant was never about.
                # Measured here on 2026-08-14: `    for _attempt in range(3):`
                # also occurs inside two deeper-indented loops, so the retry
                # mutant landed 2,300 lines away and was recorded as a SURVIVOR
                # while the code it claimed to test was never touched. A mutant
                # that measures the wrong line is worse than no mutant — it
                # reports a suite gap that does not exist and hides the one that
                # does. Fix by lengthening the anchor until it is unique.
                # ⛔ AND THE REPLACEMENT MUST DIFFER. An identity edit applies
                # cleanly, restores cleanly, and survives every possible test —
                # it reports a suite gap where there is not even a mutation.
                # Measured here on 2026-08-14: a bulk rename across this file
                # rewrote a mutant's REPLACEMENT along with its anchor, and the
                # resulting no-op was reported as a real survivor twice.
                if frm == to:
                    raise AssertionError(
                        f"replacement is identical to the anchor — this mutates "
                        f"nothing: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                killed = not run_tests()
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            # ⚠ A HARNESS FAULT, NOT A SUITE GAP. A stale anchor measured
            # nothing at all, and listing it beside real survivors is how it
            # gets read as one — which is exactly what happened on the first
            # run of this file. Tagged so the summary can separate them.
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, "anchor", why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    broken = [s for s in survivors if s[1] == "anchor"]
    real = [s for s in survivors if s[1] != "anchor"]
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if broken:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING, fix and re-run):\n"
              + "\n".join(f"  {m} {w}" for m, _, w in broken))
    if real:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in real))
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
