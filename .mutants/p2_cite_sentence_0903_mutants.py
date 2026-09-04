"""#280 — the word that was missing from the phase-2 instruction was `links`.

⛔⛔ MEASURED ON THE 2026-09-03 RUN: THREE REPORTS, 258 KB, ZERO URLS. Not few —
none, from any agent. They cited by name — "Hart et al. 2020 (Frontiers in
Veterinary Science)" — which is real, checkable and unlinkable. The instruction
asked for "a comprehensive research report with citations" and got exactly that.
Everything downstream then reported honestly on a report with nothing in it to
report: `sources=0` for all three agents, the findings extractor empty, the
Sources list empty. The defect was never in the readers.

⭐ THE SHARPEST ONES HERE:
  S1 — the sentence goes back to asking for "citations". It is the instruction
       the agents obeyed perfectly while producing nothing the pipeline could
       carry, and it is the one a reader would call harmless.
  N1 — a newline appears in the typed message. It is typed with
       `page.keyboard.type`, so that is an Enter press: the composer submits
       mid-sentence and the agent researches a truncated instruction, on a run
       whose Send is meant to be a separate deterministic step.
  R2 — only the DETERMINISTIC rung is fixed and the CUA fallback keeps the old
       ask. That fallback fires when the selector misses on a warm or canvas tab
       — so the run that most needs the right instruction gets the old one.
  L1 — the sentence grows into a paragraph. Long enough and the platform converts
       the typed message to an ATTACHMENT, which leaves the composer empty and
       the run with no instruction at all.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/p2_cite_sentence_0903_mutants.py
  .venv/bin/python .mutants/p2_cite_sentence_0903_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = "tests/test_p2_cite_sentence_0903.py"

MINE = ("asks_for_addresses or list_at_the_end or is_one_sentence or "
        "carries_the_sentence or only_for_citations or become_an_attachment or "
        "holds_no_newline or fallback_user_directive or fallback_context_hint or "
        "observer_scores_against or defined_once or promises_only_citations")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_p2_cite_sentence_0903.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
SENTENCE = ('_P2_CITE_SENTENCE = ("Cite primary and authoritative sources inline with links, "\n'
            '                     "and list them at the end.")')
TYPED = '        "Produce a comprehensive research report. " + _P2_CITE_SENTENCE'
CUA = ('                             "comprehensive report. " + _P2_CITE_SENTENCE +\n'
       '                             "\' Then STOP — do not click Send.")')
HINT = ('            context_hint="click the composer and TYPE a short prompt referring to the "\n'
        '                         "attached brief (deep research; sources cited inline with "\n'
        '                         "links) — then STOP. Do NOT click Send; the send is a "\n'
        '                         "separate step.",')
HOTSPOT = '            "Deep Research mode, and produce a comprehensive report. " + _P2_CITE_SENTENCE + " "'

MUTANTS = [
    ("S1", "under",
     "⛔⛔ the sentence goes back to asking for \"citations\". That instruction was "
     "obeyed perfectly on 2026-09-03 and produced 258 KB of prose with no address "
     "in it — the failure that reads hardest as harmless, because nothing errored",
     [(SENTENCE, '_P2_CITE_SENTENCE = "Include citations for the sources you use."')]),
    ("S2", "under",
     "⛔ the inline half goes, so an agent may append a bibliography and link "
     "nothing in the body — half the ask, and the half a reader checks last",
     [(SENTENCE, '_P2_CITE_SENTENCE = ("Cite primary and authoritative sources, "\n'
                 '                     "and list them at the end.")')]),
    ("S3", "under",
     "the end-of-report list goes, so an agent that links inline never gathers "
     "them — the two placements fail differently, which is why both are asked for",
     [(SENTENCE, '_P2_CITE_SENTENCE = ("Cite primary and authoritative sources inline "\n'
                 '                     "with links.")')]),
    ("L1", "over",
     "⛔⛔ the sentence grows into a paragraph. Past some length the platform "
     "converts the TYPED message to an attachment, which leaves the composer empty "
     "and the run with no instruction at all — the failure the brief file already "
     "exists to avoid, reintroduced by being more thorough",
     [(SENTENCE, '_P2_CITE_SENTENCE = ("Cite primary and authoritative sources inline with links, "\n'
                 '                     "and list them at the end. Prefer peer-reviewed journals, "\n'
                 '                     "official statistics, regulatory filings and primary "\n'
                 '                     "documents over summaries, blogs and news aggregators. "\n'
                 '                     "For every numeric claim give the exact source and the "\n'
                 '                     "date it was published. Where two sources disagree, cite "\n'
                 '                     "both and say which you weight higher and why. Never cite "\n'
                 '                     "a source you have not opened. Include a full reference "\n'
                 '                     "list with stable URLs at the end of the report." * 4)')]),
    ("N1", "under",
     "⛔⛔ a newline joins the typed message. It is typed with "
     "`page.keyboard.type`, so that is an ENTER press: the composer submits "
     "mid-sentence and the agent starts researching a truncated instruction, on a "
     "path whose Send is deliberately a separate deterministic step",
     [(SENTENCE, '_P2_CITE_SENTENCE = ("Cite primary and authoritative sources inline with links.\\n"\n'
                 '                     "List them at the end.")')]),
    ("R1", "under",
     "⛔ the deterministic rung — the one that actually runs — drops the sentence "
     "and keeps the vague ask, while all three fallbacks stay correct",
     [(TYPED, '        "Produce a comprehensive research report with citations."')]),
    ("R2", "under",
     "⛔⛔ only the deterministic rung is fixed and the CUA FALLBACK keeps the old "
     "ask. That rung fires when the selector misses on a warm or canvas tab, so the "
     "run least able to help itself gets the instruction that produces no links",
     [(CUA, '                             "comprehensive report with citations.\' Then STOP — do not click Send.")')]),
    ("R3", "under",
     "the shadow observer's hotspot hint keeps the old ask, so a CUA attempt that "
     "types the NEW instruction is scored against the old one and marked wrong",
     [(HOTSPOT, '            "Deep Research mode, and produce a comprehensive report with citations. "')]),
    ("R4", "under",
     "the CUA call's own context hint reverts to the shorthand that described the "
     "instruction the reports satisfied",
     [(HINT, '            context_hint="click the composer and TYPE a short prompt referring to the "\n'
             '                         "attached brief (deep research + citations) — then STOP. Do "\n'
             '                         "NOT click Send; the send is a separate step.",')]),
    ("D1", "over",
     "⛔ the sentence is spelled out at a site instead of referenced, which is how "
     "four copies of one instruction drifted apart in the first place",
     [(TYPED, '        "Produce a comprehensive research report. "\n'
              '        "Cite primary and authoritative sources inline with links, "\n'
              '        "and list them at the end."')]),
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
