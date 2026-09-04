"""#279 — Claude's live scraper was reading the column, not the panel.

⛔⛔ MEASURED ON THE 2026-09-03 RUN. Claude's report was WHOLE — 60,058
characters extracted — and this scraper saw 4,559 and one URL. ChatGPT saw
87,949 of 89,816 and Gemini 103,773 of 106,497 on the same run. Only Claude
reads a container it identifies BY NAME, and Claude is the one that writes into
an artifact panel while the scraper reads the chat column. The one link it
reported was an Anthropic support page because that was the only link in the
column it was reading — a reading fault, not a research fault.

⭐ THE FILE ALREADY KNEW. `_claude_artifact_panel_state` went geometry-first in
2026-07 with the reason recorded: the claude.ai panel no longer reliably carries
artifact-panel-style class names. The progress scraper kept asking for them.

⭐ THE SHARPEST ONES HERE:
  G1 — the geometry find goes and the named selectors decide again. Green on
       every fixture that has no panel, and it is the whole defect.
  G3 — the flush-right gate goes, so the CHAT COLUMN qualifies as the panel and
       the scraper measures the conversation it was already wrongly measuring,
       now with a number that looks authoritative.
  G4 — the chat-marker test goes, so with the sidebar expanded the main content
       wrapper passes every pure-geometry gate and the walker harvests
       chat-column junk while reporting the panel open.
  L1 — the `claude.` filters come back. They name no host: `anthropic.com` does
       not contain "claude.", so every Anthropic page passes while a source
       whose path reads `claude.html` is deleted.
  M1 — the panel REPLACES the named containers rather than joining them by max,
       so a run where the panel is closed measures less than it did before.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/claude_panel_geometry_0903_mutants.py
  .venv/bin/python .mutants/claude_panel_geometry_0903_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_claude_panel_geometry_0903.py "
          "tests/test_claude_sources_toggle_0822.py")

MINE = ("panels_report_is_measured or only_raise_the_number or "
        "left_navigation_is_not or wide_content_wrapper or "
        "wide_centred_card or holding_the_conversation or "
        "wider_than_three_quarters or short_right_docked or "
        "left_gate_is_live or "
        "cited_only_in_the_panel or anthropic_support_page or "
        "path_says_claude or platform_tagged_is_kept or "
        "tests_a_platform_name_against_a_whole_url")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_claude_panel_geometry_0903.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
WIDTH = "                        if (rect.width < 380 || rect.width > vw * 0.75) continue;"
LEFT = "                        if (rect.left < vw * 0.22) continue;"
RIGHT = "                        if (rect.right < vw - 40) continue;"
TALL = "                        if (rect.height < vh * 0.5) continue;"
CHATM = "                        if (el.querySelector(CHAT)) continue;"
FLOOR = "                        if (txt.length < 40) continue;"
#: ⛔ THE TEXT FLOOR ALONE IS NOT UNIQUE — a byte-identical line lives in the
#: artifact snapshot logger a few hundred lines below, and an anchor that matches
#: twice measures nothing at all. The line AFTER it makes the pair unique.
FLOOR_PAIR = (FLOOR + "\n"
              "                        const head = txt.slice(0, 500);")

MAXTEXT = "            if (__panel) textLen = Math.max(textLen, (__panel.innerText || '').length);"
KEEP = "            const __keep = (a) => a.href && a.href.startsWith('http') && !"
PANELLINKS = ("""            if (__panel) {
                __panel.querySelectorAll('a[href*="http"]').forEach(a => {
                    if (__keep(a)) srcSet.add(a.href);
                });
            }""")
FINDER_HEAD = "            const __panel = (() => {"

MUTANTS = [
    ("G1", "under",
     "⛔⛔ the geometry find goes and the named selectors decide again. It is green "
     "on every fixture without a panel, and it is the entire defect: 4,559 seen of "
     "60,058 written, on a page where the report was whole",
     [(FINDER_HEAD, "            const __panel = (() => { return null; })(); const __unused = (() => {")]),
    ("G3", "under",
     "⛔⛔ the flush-right gate goes, so the CHAT COLUMN qualifies as the panel. The "
     "scraper then measures the conversation it was already wrongly measuring and "
     "reports it as the panel — the same wrong number with a confident label",
     [(RIGHT, "                        if (false) continue;")]),
    ("G4", "under",
     "⛔⛔ the chat-marker test goes. With the sidebar expanded the main content "
     "wrapper is flush right, tall and starts past 22% of the viewport, so it "
     "passes every pure-geometry gate — the walker harvests chat-column junk and "
     "reports the panel open",
     [(CHATM, "                        if (false) continue;")]),
    ("G5", "over",
     "⛔ the width cap goes, so that same wrapper qualifies on width too. The real "
     "panel is about half the viewport; without the cap the gate stops describing "
     "a panel at all",
     [(WIDTH, "                        if (rect.width < 380) continue;")]),
    # ⛔⛔ G6 (removing the LEFT gate) WAS REMOVED AS AN EQUIVALENT MUTANT AT THIS
    # VIEWPORT, not because the gate is redundant. Flush-right means
    # `left = right - width >= (vw - 40) - width`, so `left < 0.22·vw` requires a
    # width the `0.75·vw` cap already forbids whenever vw >= 1333. The shim runs at
    # 1440, where no fixture can make the gate decide anything; the automation
    # viewport is 1280, where it can. `test_the_left_gate_is_live_at_the_automation
    # _viewport_and_not_at_this_one` carries the arithmetic so the fact is not lost
    # with the mutant.
    ("G7", "under",
     "the height gate goes, so a short right-docked toast or a dialog outscores the "
     "panel whenever it holds more text than the panel has rendered yet",
     [(TALL, "                        if (false) continue;")]),
    ("G8", "over",
     "the text floor rises to 4000, so a panel mid-render is not seen at all and "
     "the scraper reports the column until the report is finished — which is the "
     "whole window the live progress view exists to cover",
     [(FLOOR_PAIR, "                        if (txt.length < 4000) continue;\n"
                   "                        const head = txt.slice(0, 500);")]),
    ("M1", "over",
     "⛔⛔ the panel REPLACES the named containers instead of joining them by max, "
     "so a run whose panel is closed or iframe-mounted now measures LESS than it "
     "did before the fix — a repair that regresses the case it was not about",
     [(MAXTEXT, "            textLen = __panel ? (__panel.innerText || '').length : 0;")]),
    ("L1", "under",
     "⛔⛔ the `claude.` filters come back. They name no host — `anthropic.com` does "
     "not contain the string 'claude.' — so every Anthropic page passes three "
     "sweeps while a genuine source whose path reads `claude.html` is deleted",
     [(KEEP, "            const __keep = (a) => a.href && a.href.startsWith('http') "
             "&& !a.href.includes('claude.') && false && !")]),
    ("L2", "under",
     "⛔ the panel's own links stop being swept. The report lives there, so this is "
     "every link the report cites — and the text measurement still rises, which "
     "makes the run look repaired while the sources stay empty",
     [(PANELLINKS, "            // links: panel not swept")]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> str | None:
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


def _pytest(kfilter: str | None) -> str:
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


def run_tests(kfilter: str | None) -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: str | None) -> set:
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
          else "scope: THIS STEP'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this step's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS STEP'S OWN GUARDS, so "
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
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. On disagreement,
            # run a third time and take the majority — reported separately,
            # because "the guards cannot see this" and "that run was noisy" are
            # different claims and collapsing them sends the next reader hunting
            # a defect that is not there.
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
