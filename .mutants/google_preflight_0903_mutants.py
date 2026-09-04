"""#282 (backend half) — nothing asked whether the credential worked until minute 40.

⛔⛔ ON 2026-09-03 PHASE 5's OAUTH GRANT HAD BEEN REVOKED. The run did all its
research, wrote three reports, encoded and uploaded a podcast, and only then
found it could not create the document. The comment that explains why no check
existed is still one block above the new probe: "P5 (Doc + email) dropped
2026-04-30 — FE-owned … neither needs login verification in the BE preflight."
True of a browser login WALK, read for four months as needing no check at all —
and the identical sentence had already been written about the Anthropic key, so
this file held both the mistake and its own correction side by side.

⭐ THE SHARPEST ONES HERE:
  O1 — the probe moves BELOW the skipInitVerify blanking. Ordering is the whole
       guarantee: everything past that line stops running for most users, and
       nothing about the code reads differently.
  F1 — a probe that could not reach the app starts blocking runs. A preflight
       that fails closed on its own network blip strands healthy runs, which is
       how a check earns its own removal.
  P1 — a degraded upload POOL starts blocking. One live slot still uploads.
  C1 — the intent leaves the catalog, so the card has no recoverability class,
       the notifier's blocker gate cannot see it, and the run waits overnight
       without telling anybody.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/google_preflight_0903_mutants.py
  .venv/bin/python .mutants/google_preflight_0903_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_google_preflight_0903.py "
          "tests/test_doc_matches_code_0903.py")

MINE = ("secrets_are_not_readable or none_rather_than_raising or "
        "unchecked_not_unhealthy or above_the_skip_verification or "
        "consults_the_skip_preference or "
        "only_runs_when_a_google_phase or blocks_only_on_the_document or "
        "names_the_dead_pool or logs_the_healthy_case or "
        "registered_in_the_catalog or is_retry_only or "
        "carries_googles_own_sentence or before_the_work or "
        "every_reason_that_is_emitted")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_google_preflight_0903.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
GATE = "        if _need_p5 or _need_p4:"
BLOCK = '                if _need_p5 and _gcred.get("driveBlocked"):'
POOLLOG = "                if _need_p4 and _pool_t and _pool_n < _pool_t:"
HEALTHLOG = ('                log(f"Phase 0: Google credentials — doc identity "\n'
             '                    f"{\'ok\' if _drv.get(\'ok\') else (_drv.get(\'error\') or \'unset\')}, "\n'
             '                    f"upload pool {_pool_n}/{_pool_t} healthy")')
WHY = '                    _why = _drv.get("detail") or _drv.get("error") or "rejected"'
INTENT = '    "oauth_expired":         {"class": "blocker",     "actions": ["retry_phase"]},'
HTTP = "        if _r.status_code != 200:"
HEADER = "        # ── #282: Google credential preflight (infra, NOT login) ──"

MUTANTS = [
    ("O1", "under",
     "⛔⛔ the probe starts honouring skipInitVerify, which defaults ON — so for "
     "almost every user this check silently stops running while staying exactly "
     "where it is. ⛔ A first version of this mutant tried to MOVE the block "
     "instead and was caught by the ordering test; reading the preference in "
     "place is the easier edit and was the one nothing could see",
     [(GATE, "        _skip_early = bool(pipeline_config.get(\"skipInitVerify\", True)) \\\n"
             "            if isinstance(pipeline_config, dict) else True\n"
             "        if (_need_p5 or _need_p4) and not _skip_early:")]),
    ("F1", "over",
     "⛔⛔ a probe that could not REACH the app starts blocking the run. A "
     "preflight that fails closed on its own network blip strands healthy runs, "
     "which is exactly how a check earns its own removal",
     [(HTTP, "        if _r.status_code != 200:\n"
             "            fail_phase(0, 'Google Docs access has expired', 'probe failed',\n"
             "                       agent='system', intent='oauth_expired',\n"
             "                       alert_id='phase0_google_credential')")]),
    ("P1", "over",
     "⛔⛔ a degraded upload POOL starts blocking. One live slot still uploads, so "
     "this trades a real research result for a warning — and the pool is degraded "
     "far more often than the pinned identity is dead",
     [(BLOCK, '                if (_need_p5 and _gcred.get("driveBlocked")) or (_pool_t and _pool_n < _pool_t):')]),
    ("B1", "under",
     "⛔⛔ a refused DOCUMENT identity stops blocking, so the run starts, does "
     "forty minutes of work and fails at the last step — the 2026-09-03 outage, "
     "restored exactly",
     [(BLOCK, '                if False and _gcred.get("driveBlocked"):')]),
    ("G1", "under",
     "the phase gate goes, so a links-only run with 4 and 5 skipped is stopped by "
     "a card about a credential it was never going to use",
     [(GATE, "        if True:")]),
    ("L1", "under",
     "⚠ the healthy line goes behind the failure branch, so a pool at 3/3 and a "
     "check that never ran leave an identical record — which is how a dead slot "
     "survived eight weeks",
     [(HEALTHLOG, "                pass")]),
    ("L2", "under",
     "⛔ the degraded-pool warning stops naming WHICH account and WHY, so the one "
     "line that could have caught the July failure becomes a number nobody acts on",
     [(POOLLOG, "                if False:")]),
    ("W1", "under",
     "⛔ Google's own sentence is dropped from the card and only the code is "
     "shown. `invalid_grant` covers a revoked grant AND a token minted against the "
     "wrong client, and those are different repairs",
     [(WHY, '                    _why = _drv.get("error") or "rejected"')]),
    ("C1", "under",
     "⛔⛔ the intent leaves the catalog. The card then has no recoverability "
     "class, so the notifier's `recoverability == \\'blocker\\'` gate cannot see it "
     "and the run waits overnight without telling anybody — the exact failure that "
     "gate was built for",
     [(INTENT, "")]),
    ("C2", "over",
     "⛔ the card gains a skip token. The action is scoped to the card's OWN "
     "phase, and this card is phase 0 — so it offers to skip the preflight, not "
     "the document. A control that looks like the thing you want and does "
     "something else is worse than no control",
     [(INTENT, '    "oauth_expired":         {"class": "blocker",     "actions": ["retry_phase", "skip_phase"]},')]),
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
