"""Mutation harness — stretch 7.5 step 2, backend half (2026-09-02).

⛔⛔ WHAT THIS CODE DECIDES. Whether the app is handed a private ChatGPT
conversation address after a run resumes with added input. The app STORES every
link a phase reports, so what this one emit passes outlives the run: it became a
clickable row in the agent drill-down, a line in the follow-up chat's system
instruction (sent to a model), and a candidate for the public video description.

⭐⭐ THE SHARPEST MUTANTS HERE:
  E1 — the whole leak restored, byte for byte: the raw conversation address
       under the label "ChatGPT Brief", unverified and unmarked.
  E2 — the label drifts. Not a leak, a DOUBLE RENDER: the frontend's
       reopen-hydration backfill synthesizes "Read Brief report" for the same
       URL, and the (label, url) dedup cannot collapse a mismatched pair, so a
       phone or cold reopen shows the brief twice (#746).
  E5 — the in-app link loses its `:brief` target and opens the documents index
       instead. A link that goes somewhere is not a link that goes there.
  E6 — the fallback goes, so a CLI run with no Firestore id emits
       `/documents?open=:brief`.
  E8 — the empty-kind guard goes, so a caller with no document kind gets
       `/documents?open=<id>:`, which anchors at nothing.

⛔⛔ 2026-09-02, STRETCH 7.5 STEP 5 — FOUR OF THESE MUTANTS WENT WRONG AT ONCE AND
THE ANCHOR SWEEP COULD ONLY SEE TWO OF THEM. Step 5 lifted the in-app address into
`in_app_document_url` and gave `brief_url` a single meaning (that same address, on
every phase-1 branch). E5 and E6 anchored on the lifted expression and went STALE,
which the sweep catches. E1 and E4 mutated to `brief_url` in order to restore the
conversation address — and `brief_url` is now the in-app address, so both quietly
became EQUIVALENT MUTANTS with descriptions that no longer matched what they did.
An anchor that still matches is not an anchor that still means anything.

⚠ THESE ARE SOURCE GUARDS AND THE HARNESS DOES NOT PRETEND OTHERWISE. The branch
lives inside `run_pipeline`, which no test in this repo can drive. The
behavioural proof that a link of this shape cannot reach a user is on the
frontend — .mutants/private_chat_links_0902_mutants.mjs drives the filters, the
video description and the Admin-side Firestore reader for real.

⚠ ONE MUTANT DELIBERATELY ABSENT. Pointing `BriefArtifact(url=…)` back at the
conversation address is an EQUIVALENT MUTANT: measured, `brief_artifact.url` has
ZERO readers anywhere in the repo — only `.text`, `.chars` and `.sections` are
read — so it changes nothing observable and would report as a survivor for no
reason.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
The filtered selection is proven to cover EVERY test in the file this step owns
before a single mutant is applied.

    .venv/bin/python .mutants/p1_regen_link_0902_mutants.py
    .venv/bin/python .mutants/p1_regen_link_0902_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_p1_regen_link_0902.py "
          "tests/test_resume_at_phase5_handoff.py "
          "tests/test_pause_resume_safety_net_0902.py")

MINE = "regen or phase_1_link or chatgpt_brief or in_app_url or brief_specifically or label_is_the_load_bearing"

OWNED_FILES = ("tests/test_p1_regen_link_0902.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

HELPER_URL = '    return (f"/documents?open={_fb_research_id}:{kind}"'
HELPER_COND = '            if _fb_research_id and kind else "/documents")'
LINKS_ARG = ('                                   links=[{"label": "Read Brief report", "url": _regen_in_app_url,\n'
             '                                           "verified": True, "primary": True}])')

MUTANTS = [
    ("E1", "under",
     "⛔⛔⛔ THE LEAK RESTORED BYTE FOR BYTE — the raw ChatGPT conversation address "
     "under the label \"ChatGPT Brief\", unverified and unmarked, stored by the app "
     "and outliving the run",
     [(LINKS_ARG,
       '                                   links=[{"label": "ChatGPT Brief", "url": p1_new.get("url", "")}])')]),
    ("E2", "under",
     "⛔⛔ the label drifts. Not a leak — a DOUBLE RENDER: the app's reopen backfill "
     "synthesizes \"Read Brief report\" for the same URL and the (label, url) dedup "
     "cannot collapse a mismatched pair, so a cold reopen shows the brief twice",
     [('"label": "Read Brief report", "url": _regen_in_app_url',
       '"label": "Read brief", "url": _regen_in_app_url')]),
    ("E3", "under",
     "the link loses `verified` and `primary`, so the app reads it as a secondary "
     "share row and the phase summary can pick up the \"(no verified links)\" suffix",
     [(LINKS_ARG,
       '                                   links=[{"label": "Read Brief report", "url": _regen_in_app_url}])')]),
    ("E4", "under",
     "⛔⛔ the in-app URL is computed and then IGNORED — the emit goes back to the "
     "conversation address by a different route, while the line above it still "
     "reads as fixed. ⚠ It no longer reaches for `brief_url`: since step 5 that "
     "name IS the in-app address, so the old form of this mutant changed nothing",
     [('"label": "Read Brief report", "url": _regen_in_app_url',
       '"label": "Read Brief report", "url": p1_new.get("url", "")')]),
    ("E5", "under",
     "the link loses its `:{kind}` target and opens the documents index instead. A "
     "link that goes somewhere is not a link that goes there",
     [(HELPER_URL, '    return (f"/documents?open={_fb_research_id}"')]),
    ("E6", "under",
     "the fallback goes, so a CLI run with no Firestore document emits "
     "`/documents?open=:brief`, which resolves to nothing",
     [(HELPER_COND, '            if True else "/documents")')]),
    ("E8", "under",
     "the empty-kind half of the guard goes, so a caller with no document kind "
     "gets `/documents?open=<id>:` — an anchor at nothing, which is the second way "
     "to build an unopenable link and the one the four inline copies never covered",
     [(HELPER_COND, '            if _fb_research_id else "/documents")')]),
    ("E7", "over",
     "the regen reports NO links at all, which trips the app's \"(no verified "
     "links)\" caption on a phase that finished perfectly well",
     [(LINKS_ARG, '                                   links=[])')]),
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
    kfilter = None if unfiltered else MINE
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
    for mid, direction, why, edits in MUTANTS:
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
            faults.append((mid, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    measured = len(MUTANTS) - len(faults)
    scope = " [whole selection]" if unfiltered else " [own guards]"
    print(f"\n{measured - len(survivors)}/{measured} killed ({over} over-corrections){scope}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
