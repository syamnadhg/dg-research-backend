"""Wave 10 — the DOM shim's computed style: the gate that could not be driven.

⛔⛔ WHAT WAS WRONG, AND WHY IT LOOKED FINE. `tests/_domshim.py` is the node DOM
this suite executes production page JS against. Its `getComputedStyle` returned
CONSTANT `display:block`, `visibility:visible`, `opacity:1` — and the 2026-09-10
Gemini re-draft path reads `getBoundingClientRect` + `getComputedStyle` and
NOTHING else. So only the SIZE half of that visibility gate could ever be driven
negative by a fixture, and the style half had never run once. A gate that cannot
be driven negative is not a tested gate; it is a comment.

⭐ THE FIX ADDS THREE KEYS — `disp`, `vis`, `op` — and repurposes none. `hidden`,
`anim` and `clip` behave exactly as they did, because fixtures across this suite
already use `hidden` for the rects/offsetParent idiom and two live mutants read
`animationName`/`backgroundClip`. A change that gave any of those a second
meaning would silently alter what every existing fixture tells production JS.

⛔⛔ AND THIS IS THE ONE HARNESS IN THE FLEET WHOSE TARGET IS A TEST FILE. That is
deliberate and it is the point: the shim is not a test, it is the INSTRUMENT the
lane-2 evidence is taken with, and an instrument nobody has tried to break is
exactly the shape wave 10's cross-verify found six lanes of. If the shim can
report a hidden control as visible, every executed page-JS test in the wave is
measuring the shim rather than the page.

⭐ THE ONES WORTH READING:
  S1/S2/S3 — each key reverts to the constant it replaced, one at a time. These
        are the defect itself, three times over, and each is killed both by its
        own unit pin AND by the lane-2 clicker tests that now drive a control
        hidden by style alone — which is what says the fix reached production JS.
  S4/S5 — the browser semantics get subtly wrong: visibility stops inheriting,
        or display starts. Getting inheritance backwards is the FLATTERING error
        (fixtures still look like they work), and both directions are pinned.
  S6  — the destructive shortcut: `hidden` also reports `display:none`. It reads
        like a simplification and it changes what every pre-existing fixture in
        the suite says to production JS, which is the one thing this lane
        promised not to do.
  S7  — `__run` calls the function under test TWICE and returns the FIRST
        result. The wave quotes "the shim calls `fn` exactly once per process"
        as the reason a property about REPEATED calls cannot be measured through
        `run_js`; this is that claim's only evidence.

⛔ DELIBERATELY ABSENT — recorded so the next reader does not re-add them:
  * "the default triple changes" (`'block'/'visible'/'1'` → anything else).
    Every fixture in the suite that does not set an attribute depends on it, so
    the mutant would red the whole tree and score a kill for the suite's
    existence rather than for this lane. The DEFAULTS are pinned by
    `test_the_three_properties_still_default_to_what_every_existing_fixture_expects`;
    S1-S3 mutate the ATTRIBUTE READ, which is the thing wave 10 added.
  * "`hidden` stops driving getClientRects/offsetParent". That is the shim's
    pre-existing behaviour, not this wave's; mutating it measures the 08-06 shim.
    S6 is the wave's own hazard — `hidden` LEAKING INTO computed style — and it
    is here.
  * "`getAnimations()` stops reporting". Same reason: it is the 08-19 addition,
    covered by its own tests, and unchanged by this wave. S8 mutates the
    `animationName` READ instead, which is what this wave promised not to touch.

⭐ OWN PINS ADDED WITH THIS HARNESS (tests/test_domshim_computed_style_0917.py):
  test_the_shim_calls_the_function_under_test_exactly_once_per_process → kills S7
  (it was REPAIRED with this harness: it asserted the RETURN value, which cannot
  tell "called once" from "called three times, first result returned". It now
  counts the calls out of band, through the shim's own CLICKS array, which is
  read after `fn` returns.)

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/wave10_domshim_style_0917_mutants.py
  .venv/bin/python .mutants/wave10_domshim_style_0917_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The shim's own file, plus the lane-2 file that EXECUTES production JS through
# it — because "the shim can express a hidden control" only matters where the
# page code reads it, and those two suites are where it does.
SUITES = ("tests/test_domshim_computed_style_0917.py "
          "tests/test_gemini_page_js_executed_0917.py")

MINE = (
    # tests/test_domshim_computed_style_0917.py
    "still_default_to_what_every_existing_fixture or "
    "disp_drives_display or vis_drives_visibility or op_drives_opacity or "
    "hidden_still_means_what_it_meant or animation_and_clip_keys or "
    "visibility_inherits_the_way_a_browser or "
    "display_and_opacity_do_not_inherit or exactly_once_per_process or "
    # tests/test_gemini_page_js_executed_0917.py
    "captured_control_reads_visible_and_enabled or "
    "hidden_only_by_computed_style or went_invisible_by_style_mid_flight or "
    "both_rendered_shapes_of_start_research or "
    "neither_reported_nor_clicked or skeleton_is_skipped or "
    "clicked_exactly_once_even_when_the_page_offers_two or "
    "reads_research_mode_off_a_page or reads_plain_chat_mode or "
    "marks_the_pill_pressed or unpressed_pill or "
    "pill_that_is_not_rendered or whole_name_not_a_word_inside_it or "
    "composer_fallback_picks_the_lowest or composer_fallback_ignores or "
    "neither_composer_nor_pill"
)

OWNED_FILES = ("tests/test_domshim_computed_style_0917.py",
               "tests/test_gemini_page_js_executed_0917.py")

# ⛔⛔ THE TARGET IS A TEST-SUPPORT FILE, NOT PRODUCTION SOURCE — see the header.
TARGET = "tests/_domshim.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors (inside the shim's JS, held in a Python string) ─────────────
DISPLAY = "  return { display: get('disp') || 'block',"
VISIBILITY = "           visibility: inherited('vis') || 'visible',"
OPACITY = "           opacity: get('op') || '1',"
ANIMATION = "           animationName: get('anim') || 'none',"
CLIP = "  const clip = get('clip');"
RUN = ("  const ret = arg === undefined ? fn() : fn(arg);\n"
       "  return { ret, clicks: CLICKS };")

MUTANTS = [
    ("S1", "under",
     "⛔⛔ `display` GOES BACK TO THE CONSTANT — the defect itself. A fixture "
     "can no longer say `display:none`, so the visibility clause of every "
     "production gate this suite executes is un-drivable again and the 09-10 "
     "re-draft path's check has never run. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_disp_drives_display_and_touches_nothing_else, and independently by "
     "tests/test_gemini_page_js_executed_0917.py::"
     "test_the_clicker_refuses_a_control_that_went_invisible_by_style_mid_flight "
     "— which is what says the key reached production JS and not just the shim",
     [(DISPLAY, "  return { display: 'block',")]),
    ("S2", "under",
     "⛔⛔ `visibility` GOES BACK TO THE CONSTANT. Same defect, and this is the "
     "property Gemini actually uses to hide a control mid-flight. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_vis_drives_visibility_and_touches_nothing_else",
     [(VISIBILITY, "           visibility: 'visible',")]),
    ("S3", "under",
     "⛔⛔ `opacity` GOES BACK TO THE CONSTANT, so the opacity FLOOR in every "
     "production visibility helper is dead code under test. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_op_drives_opacity_and_touches_nothing_else",
     [(OPACITY, "           opacity: '1',")]),
    ("S4", "under",
     "⛔ VISIBILITY STOPS INHERITING. A browser inherits `visibility` through "
     "the tree — that is how a hidden PANEL hides the buttons inside it — so a "
     "shim that reads only the element's own attribute tells production JS that "
     "a control inside a hidden container is visible. The flattering error. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_visibility_inherits_the_way_a_browser_inherits_it",
     [(VISIBILITY, "           visibility: get('vis') || 'visible',")]),
    ("S5", "over",
     "⛔ DISPLAY STARTS INHERITING — the same error the other way round, and it "
     "is the over-correction a reader reaches for after S4. `display:none` on an "
     "ancestor removes the subtree from layout, but the CHILD's computed display "
     "is its own; a shim that inherits it reports `none` for elements a browser "
     "reports `block` for, and fixtures start refusing controls that are really "
     "there. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_display_and_opacity_do_not_inherit_the_way_a_browser_does_not",
     [(DISPLAY, "  return { display: inherited('disp') || 'block',")]),
    ("S6", "over",
     "⛔⛔ THE DESTRUCTIVE SHORTCUT: `hidden` ALSO REPORTS `display:none`. It "
     "reads like a tidy simplification — one attribute, both meanings — and it "
     "silently changes what every pre-existing fixture in this suite says to "
     "production JS, because `hidden` is the rects/offsetParent idiom hundreds "
     "of fixtures already use. This wave's stated rule is that the three new "
     "keys add meaning and repurpose none. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_hidden_still_means_what_it_meant_and_does_not_leak_into_computed_style",
     [(CLIP,
       CLIP + "\n"
       "  if (el && el.getAttribute && el.getAttribute('hidden') !== null) {\n"
       "    return { display: 'none', visibility: 'visible', opacity: '1',\n"
       "             animationName: 'none', backgroundClip: clip,\n"
       "             webkitBackgroundClip: clip };\n"
       "  }")]),
    ("S7", "under",
     "⛔⛔ `__run` CALLS THE FUNCTION UNDER TEST TWICE AND RETURNS THE FIRST "
     "RESULT. The whole wave rests on \"the shim calls `fn` exactly once per "
     "process\" — it is the stated reason a property about REPEATED calls "
     "(\"clicks once and stops\", \"gives up at the deadline\") must be measured "
     "with a fake page object instead. A shim that quietly re-ran the function "
     "would make every click-count assertion in the executed lane wrong. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_the_shim_calls_the_function_under_test_exactly_once_per_process, "
     "REPAIRED WITH THIS HARNESS to count the calls through the shim's CLICKS "
     "array (read after `fn` returns) rather than through the return value, "
     "which this mutant leaves reading 1",
     [(RUN,
       "  const ret = arg === undefined ? fn() : fn(arg);\n"
       "  if (arg === undefined) { fn(); }\n"
       "  return { ret, clicks: CLICKS };")]),
    ("S8", "under",
     "⛔ `animationName` IS REWIRED ONTO ANOTHER ATTRIBUTE. The three new keys "
     "were supposed to leave `anim` and `clip` byte-identical, and two live "
     "mutants elsewhere in this fleet read them: a fixture that says \"this "
     "spinner is animating\" would start meaning something else, and the two "
     "harnesses that depend on it would score kills for a reason nobody stated. "
     "KILLED BY tests/test_domshim_computed_style_0917.py::"
     "test_the_animation_and_clip_keys_are_exactly_as_they_were",
     [(ANIMATION, "           animationName: get('disp') || 'none',")]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _digest() -> dict:
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}


def _pytest(kfilter: "str | None") -> str:
    """'green' | 'red' | 'nothing-collected'."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    code = sh(args, cwd=ROOT, env=ENV).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(kfilter: "str | None") -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: "str | None") -> set:
    args = [sys.executable, "-B", "-m", "pytest", *files,
            "--collect-only", "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    out = sh(args, cwd=ROOT, env=ENV).stdout
    return {ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(" ")}


def _filter_misses(kfilter: str) -> set:
    return _collected(OWNED_FILES, None) - _collected(OWNED_FILES, kfilter)


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    kfilter = None if unfiltered else MINE

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — spot check, not a score.")
    print("scope: THE WHOLE SELECTION (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this wave's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS WAVE'S OWN GUARDS, so "
                  "any mutant only they could kill would report as a SURVIVOR:")
            for tid in sorted(missed):
                print(f"    {tid}")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(kfilter) or not run_tests(None):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green (filtered and whole)\n")

    path = ROOT / TARGET
    survivors, faults, flaky = [], [], []
    for mid, direction, why, edits in selected:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            try:
                compile(mutated, TARGET, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            _mark(mid)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            verdicts = [not run_tests(kfilter) for _ in range(SURVIVOR_CONFIRMATIONS)]
            flapped = len(set(verdicts)) > 1
            if flapped:
                verdicts.append(not run_tests(kfilter))
            killed = sum(verdicts) * 2 > len(verdicts)
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = (f"  ⚠ FLAPPED {sum(verdicts)}/{len(verdicts)} — tie broken by "
                    "majority" if flapped else "")
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
            elif flapped:
                flaky.append((mid, sum(verdicts), len(verdicts)))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in selected if m[1] == "over")
    scope = " [whole selection]" if unfiltered else " [own guards]"
    label = " (SPOT CHECK)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority — killed, "
              f"but this selection is not perfectly stable:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
