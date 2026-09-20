"""A failed keyring write must not leave a store nobody reads.

⛔⛔ THE DEFECT, found on 2026-09-20 in a log line the owner asked about because
it looked like noise:

    [WARN] [auth.keystore] keyring write of slot=previous failed, using file:
           Can't store password on keychain: (-25244, 'Unknown Error')

-25244 is `errSecInvalidOwnerEdit`. macOS answers it when the keychain item
EXISTS but was created by a different binary — `set_password` MODIFIES in place
and the item's ACL does not trust the interpreter now asking. A new venv, a new
wheel, a reinstalled Python is enough.

The warning was not the problem. `set()` already purged the file shadow after a
GOOD keyring write, with a comment saying exactly why — "auth.json can never
hold a STALE token that a later get() would return". The FAILURE path built that
very shadow, and `get()` asks the keyring FIRST. It was live on the machine that
produced the line: `previous:<install>` in the keychain from 18:39:51Z AND in
auth.json fifty minutes later. The fresher copy was unreachable.

⭐ WHAT THESE MUTANTS DEFEND, in one line each:
  M1 — the delete-then-recreate retry goes, so a foreign item is routed around
       forever instead of being cured once. Every rotation pays the warning.
  M2 — ⛔⛔ THE ONE THAT MATTERS. The fallback stops silencing the keyring, so
       the file is written and the stale keychain value still answers every
       read. This IS the original defect, restored, and it looks tidier.
  M3 — the hot path grows the repair. A good write should be one call; this
       makes every rotation delete first, which is a real risk on a store whose
       delete can succeed while the re-write fails.
  M4 — the OSStatus hint stops firing, so the log says `-25244, 'Unknown Error'`
       again. That is the form that read as noise for as long as it did.
  M5 — the wrong code is mapped. The hint is present, plausible and silent on
       the one error it exists for.
  M6 — the unsilenceable divergence drops back to a WARNING. Two stores
       disagreeing about a credential is not a warning.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/keyring_write_shadow_0920_mutants.py
  .venv/bin/python .mutants/keyring_write_shadow_0920_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_keyring_write_shadow_0920.py "
          "tests/test_track_d_keystore.py")

MINE = ("foreign_item or reader_gets or silenced_first or "
        "deletion_cannot_fix or disagreeing_in_silence or "
        "CLEAN_fallback_is_not_reported or osstatus_is_named or "
        "never_invents or purges_the_file_shadow or still_one_call or "
        "straight_to_the_file or empty_entry_is_silence")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_keyring_write_shadow_0920.py",)

TARGET = "auth/keystore.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The ONE delete. It cures the ownership problem AND silences a stale value.
DEL = ('            with contextlib.suppress(Exception):\n'
       '                kr.delete_password(SERVICE, acct)  # type: ignore[attr-defined]')
#: The rewrite that takes ownership.
REWRITE = '                kr.set_password(SERVICE, acct, value)  # type: ignore[attr-defined]\n                log.info('
#: The hot path — one call, no repair.
HOT = ('            kr.set_password(SERVICE, acct, value)  # type: ignore[attr-defined]\n'
       '            # Keyring is the live store')
#: The honest question: can a reader still get something out of the keyring?
ASK = '            if _keyring_can_still_answer(kr, acct):'
#: The probe itself — asked of `get`, not inferred from a delete.
PROBE = '        return bool(kr.get_password(SERVICE, acct))'
#: The OSStatus translator's search.
HINT = ('    for code, name in _OSSTATUS_NAMES.items():\n'
        '        if str(code) in text:\n'
        '            return f"{text} — {name}"')
#: The code this whole file exists because of.
CODE = '    -25244: "errSecInvalidOwnerEdit: the item exists but belongs to a different binary",'
#: The level the unsilenceable case is reported at.
LOUD = '                log.error('

MUTANTS = [
    ("M1", "under",
     "⛔⛔⛔ THE ORIGINAL DEFECT, RESTORED, AND IT LOOKS TIDIER THAN THE FIX. "
     "The delete goes, so `set_password` — which MODIFIES in place — can never "
     "take ownership of a foreign item, and the stale value is left where "
     "`get()` looks FIRST. The fresh token goes to the file, which nobody "
     "reads. On the `current` slot that is every refresh presenting a dead "
     "token until the machine has to be paired again",
     [(DEL, "            pass")]),

    ("M2", "under",
     "⛔⛔ the rewrite after the delete goes, so the keyring is emptied and "
     "never refilled. Every rotation from here on lands in the file and the "
     "keyring is permanently unused — correct by luck, because the delete "
     "happens to silence it, and one line away from losing the token entirely",
     [(REWRITE, '                raise RuntimeError("no rewrite")\n                log.info(')]),

    ("M3", "over",
     "⛔ the repair moves onto the HOT path: every good write now deletes "
     "first. On a store where the delete can succeed and the re-write then "
     "fail, that turns a working rotation into a lost credential — and it "
     "doubles the keychain traffic of every refresh to buy nothing",
     [(HOT, '            kr.delete_password(SERVICE, acct)  # type: ignore[attr-defined]\n'
            '            kr.set_password(SERVICE, acct, value)  # type: ignore[attr-defined]\n'
            '            # Keyring is the live store')]),

    ("M4", "under",
     "⛔⛔ the divergence check is inverted: a clean fallback shouts ERROR and "
     "a genuine two-store disagreement goes out as a WARNING. Both halves are "
     "harmful — the false alarm trains everybody to ignore the real one",
     [(ASK, '            if not _keyring_can_still_answer(kr, acct):')]),

    ("M5", "under",
     "⛔⛔ the probe answers from the store's EXISTENCE rather than from what "
     "`get` returns. An entry holding an empty string reads as a live stale "
     "token, and the one thing this function exists to mirror is `get`",
     [(PROBE, '        return kr.get_password(SERVICE, acct) is not None')]),

    ("M6", "under",
     "⛔ the OSStatus hint stops firing and the log goes back to "
     "`(-25244, 'Unknown Error')` — a number with no meaning attached, which "
     "is the exact form that read as noise until somebody happened to ask",
     [(HINT, '    for code, name in _OSSTATUS_NAMES.items():\n'
             '        if False:\n'
             '            return f"{text} — {name}"')]),

    ("M7", "under",
     "⛔⛔ the ONE code this file exists for is mapped one off. The translator "
     "is present, plausible and tested-looking, and is silent on the only "
     "error anybody has actually met",
     [(CODE, '    -25245: "errSecTrustNotAvailable: no trust results are available",')]),

    ("M8", "under",
     "⛔⛔ the unsilenceable case drops back to a WARNING. Two stores holding "
     "different values for the same credential, with no way to clear either, "
     "is not a warning — and a warning is precisely what hid this for as long "
     "as it hid",
     [(LOUD, '                log.warning(')]),
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
