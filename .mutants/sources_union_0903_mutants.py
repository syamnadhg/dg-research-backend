"""#278 — the panel's captures were discarded for being second best to nothing.

⛔⛔ THE RULE HAD ITS REASONING RIGHT AND ITS FAILURE CASE MISSING. `save_meta`
wrote the live panel's captured URLs only for an agent with NO report, on the
argument that "an agent WITH a report already has citation-derived sources from
its own text, and those are the better list". True whenever a report cites
addresses. On 2026-09-03 not one of three reports held a single URL, so the
better list was empty, the fallback was skipped for the report existing, and ten
genuine research hosts per agent were thrown away in favour of nothing.

⭐ THE SHARPEST ONES HERE:
  U1 — the union goes and the report alone decides again. Green everywhere
       except a report that cites by name, which is the only shape that ever
       showed the defect.
  O1 — the panel leads and the report follows. The list is CAPPED, so on a
       well-sourced run that silently drops the agent's own citations in favour
       of pages it opened and chose not to cite.
  K1 — the dedupe goes back to the raw string, so one page seen by both rungs is
       two sources, and every ChatGPT run over-reports by however many of its
       citations the panel also caught.
  P1 — the panel side skips the host rule, which reopens the previous fix through
       the door beside it: `support.anthropic.com` is back in the user's Sources.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/sources_union_0903_mutants.py
  .venv/bin/python .mutants/sources_union_0903_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = "tests/test_sources_union_0903.py"

MINE = ("cites_by_name or citations_come_first or seen_by_both or smuggle or "
        "the_report_wrote or malformed_snapshot or "
        "non_http_panel_entry or union_is_capped or leaves_the_report_alone or "
        "rungs_empty")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_sources_union_0903.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
PANEL = (
    '            _panel_urls = []\n'
    '            try:\n'
    '                _panel_urls = [\n'
    '                    u for u in (getattr(_runtime, "agent_progress_snapshots", {})\n'
    '                                .get(platform, {}) or {}).get("source_urls", []) or []\n'
    '                    if isinstance(u, str) and u.lower().startswith(("http://", "https://"))\n'
    '                    and not _find_is_platform_host(u)\n'
    '                ]\n'
    '            except Exception:\n'
    '                _panel_urls = []'
)
LOOP = (
    '            _seen_keys, unique_urls = set(), []\n'
    '            for _u in urls + _panel_urls:\n'
    '                _k = _find_normalize_url(_u)\n'
    '                if _k in _seen_keys:\n'
    '                    continue\n'
    '                _seen_keys.add(_k)\n'
    '                unique_urls.append(_u)\n'
    '                if len(unique_urls) >= _SOURCE_LIST_CAP:\n'
    '                    break'
)

MUTANTS = [
    ("U1", "under",
     "⛔⛔ the union goes and the report alone decides again. It is green on every "
     "run whose report cites addresses, and reports zero on the one shape that "
     "exposed the defect — a whole report that cites by name",
     [(LOOP, "            unique_urls = list(dict.fromkeys(urls))[:_SOURCE_LIST_CAP]")]),
    ("O1", "over",
     "⛔⛔ the panel LEADS and the report follows. The list is capped, so on a "
     "well-sourced run this silently drops the agent's own citations in favour of "
     "pages it opened and chose not to cite — the two rungs' roles inverted",
     [(LOOP, LOOP.replace("for _u in urls + _panel_urls:",
                          "for _u in _panel_urls + urls:"))]),
    ("K1", "under",
     "⛔⛔ the dedupe goes back to the raw string, so one page seen by BOTH rungs "
     "is two sources. ChatGPT tags its outbound links, so the panel's row and the "
     "report's citation of one page never match as text and every run over-reports",
     [(LOOP, LOOP.replace("_k = _find_normalize_url(_u)", "_k = _u"))]),
    ("K2", "over",
     "⛔ the NORMALISED key is emitted rather than the address the report wrote, so "
     "a page whose query string is load-bearing is handed to the user stripped of "
     "the part that makes it resolve",
     [(LOOP, LOOP.replace("unique_urls.append(_u)", "unique_urls.append(_k)"))]),
    ("C1", "under",
     "the cap goes, so a report with hundreds of citations plus a full panel "
     "writes an unbounded list into a Firestore document",
     [(LOOP, LOOP.replace('                if len(unique_urls) >= _SOURCE_LIST_CAP:\n'
                          '                    break', '                pass'))]),
    ("P1", "under",
     "⛔⛔ the panel side skips the host rule, which reopens the previous fix "
     "through the door beside it — `support.anthropic.com` is back in the user's "
     "Sources, arriving by the rung nobody re-checked",
     [(PANEL, PANEL.replace('\n                    and not _find_is_platform_host(u)', ''))]),
    ("P2", "under",
     "⛔ the scheme check goes, so a `javascript:` entry written by page JS reaches "
     "a list the app renders into hrefs",
     [(PANEL, PANEL.replace('if isinstance(u, str) and u.lower().startswith(("http://", "https://"))\n                    and not',
                            'if isinstance(u, str)\n                    and not'))]),
    ("P3", "under",
     "⛔⛔ the try/except goes, so a snapshot holding a TRUTHY non-iterable where a "
     "list was expected takes the WHOLE meta.json write down with it — the report, "
     "the sections, the timings, the phase's entire persisted record — to lose a "
     "supplementary list. ⛔ Not a null: `or []` already absorbs that, and the "
     "first guard written for this mutant used one and proved nothing. A first "
     "draft of the mutant itself deleted the isinstance check and was absorbed "
     "the same way, which is what pointed at the try/except as the thing worth "
     "mutating",
     [(PANEL, "            _panel_urls = [\n"
              '                u for u in (getattr(_runtime, "agent_progress_snapshots", {})\n'
              '                            .get(platform, {}) or {}).get("source_urls", []) or []\n'
              '                if isinstance(u, str) and u.lower().startswith(("http://", "https://"))\n'
              "                and not _find_is_platform_host(u)\n"
              "            ]")]),
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
