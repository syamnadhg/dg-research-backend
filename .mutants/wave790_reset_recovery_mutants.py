"""7.9-0 — reset recovery on a machine with no supervisor.

⛔⛔ THE INCIDENT THIS WAVE CAME FROM, measured on the owner's own machine
2026-09-06. They reset their pair code — the supported way to boot a sharer off
a research computer. That revokes the machine's device token by design. Their
machine was not running at the time, and deliberately has no supervisor, so
nothing recovered: it silently dropped off the public list for hours. Every
command they then ran told them to run `--pair`, and `--pair` does not repair a
machine — the server mints a fresh random deviceId and a new device carries no
`visibility` field, which reads as private. The advice would have cost them the
computer's identity and the public listing they were trying to check, in one
command. When they finally ran serve, recovery worked in one second and the
process then exited 0 on the assumption that a supervisor would restart it.

⭐ THE MUTANTS WORTH READING:
  W1  — the classifier asks about the token before the device id, so a machine
        that has never paired is told to start a serve that has nothing to do.
        The ORDER of those two questions is the whole safety property: the id is
        what decides whether pairing is a repair or a demolition.
  W4  — the remedy names `--pair` again. This is the defect verbatim, and it is
        the one mutant in this file that shipped in production.
  W8  — the doctor goes back to appending its own hardcoded advice, which is how
        the sentence survived every previous pass over this file: the classifier
        can be perfect and the consumer can still ignore it.
  W12 — the relink exit stops asking whether anything will restart it. Killed
        only by a source guard, because driving a watcher that ends its own
        process is not something a test can survive.
  W13 — the re-exec loses its once-only marker. An invisible restart loop is
        worse than the defect it replaces, which is why the marker is an env var
        and not a module global: it has to survive into the new process.
  W15 — the banner hardcodes "connected", restoring a green (active) device on a
        machine whose connection had already failed.
  W19 — the sync helper reports success for a machine with no device id, which
        could not possibly have told the app anything.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/wave790_reset_recovery_mutants.py
  .venv/bin/python .mutants/wave790_reset_recovery_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_credential_state_790.py "
          "tests/test_relink_exit_790.py "
          "tests/test_serve_banner_truth_790.py "
          "tests/test_supervised_claim_790.py "
          "tests/test_visibility_0904.py "
          "tests/test_doctor_network_truth_0817.py")

MINE = ("never_paired or orphaned or no_token or rejected or healthy or "
        "unknown_state or remedy or pairing or timer or advice_sites or "
        "rest_only_command or keystore_that_cannot or retired_sentence or "
        "restart or supervisor or exits or last_word or confirms_what or "
        "banner or device_chip or heartbeat_row or footer or terminal_open or "
        "footers_cannot or "
        "revoked_session or failed_SET or failed_SHOW or unprovable_failure or "
        "sync_helper or device_id_is_a_failure or refused_patch or "
        "written_patch or synced_tick or dead_generator or "
        "genuine_revoke or "
        # ⛔ ADDED after the coverage check flagged them: W14's ONLY killer is
        # `test_the_seam_sets_the_marker_before_it_execs`, so without this word
        # that mutant would have been reported as a survivor — and a survivor
        # and a deselected guard read identically on the way past.
        "seam or gated_on_the_credential_state or next_action_never_offers or "
        "in_serve or outside_a_serve or bound_everywhere or "
        "footers or keep_the_terminal or failed_exec or giveup")

# ⛔⛔ ONLY FILES THIS WAVE OWNS ENTIRELY. Cross-verify proposed adding the two
# MODIFIED files here as well, and I tried it — the run immediately failed with
# thirty-odd "the filter cannot see this guard" lines. The check's rule is that
# EVERY test in an owned file must be selectable by the filter, and those two
# files are mostly guards belonging to 7.7B and to the 08-17 doctor work. Owning
# them would mean either dragging unrelated suites into every mutant run or
# blunting the filter until it stops being a scope.
# ⭐ THE CONCERN UNDER THE PROPOSAL WAS REAL AND IS HANDLED IN `MINE` INSTEAD:
# the guards this wave ADDED to those two files are named there by keyword, so a
# mutant only they can kill is still selected. What is given up is the automatic
# proof of that — hence this note, so the next person adding a guard to a
# pre-existing file knows to add its keyword too.
OWNED_FILES = (
    "tests/test_credential_state_790.py",
    "tests/test_relink_exit_790.py",
    "tests/test_serve_banner_truth_790.py",
    "tests/test_supervised_claim_790.py",
)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The order of the classifier's questions, which is its safety property.
ORDER = ('    if not device_id:\n'
         '        return CRED_NEVER_PAIRED\n'
         '    if not paired_uid:\n'
         '        return CRED_ORPHANED')
#: The rejection test, which must outrank a token we still hold.
REJECTED = ('    if token_rejected:\n'
            '        return CRED_TOKEN_REJECTED')
# ⛔ `RECOVER` (the recovered-states `if`) WAS REMOVED — it was an anchor no
# mutant used, which the sweep cannot flag because it only checks that anchors
# MATCH, not that they are reached. An unused anchor reads like coverage and is
# not any. Cross-verify caught it.
#: The ACTION those states name. ⛔ This, not the tuple above, is where the
#: production defect lived: the branch was always reachable, the sentence inside
#: it was wrong.
RECOVER_ACTION = ('             f"Then start this computer with:  {_PROG} --serve"),')
#: The keystore probe that must fail toward the safe answer.
PROBE_FAIL = ('    except Exception:\n'
              '        has_token = False')
#: The doctor's Firestore-init action, now delegated.
#: ⛔ THE `_fail` LINE IS CARRIED ONLY TO MAKE THIS UNIQUE. 7.9-0 routed TWO of
#: the doctor's branches through the same call — this one and the pair-state
#: check — so the call alone matches twice, and an anchor that matches twice
#: measures nothing. The sweep caught it before this harness ever ran.
#: ⛔ ANCHORED WITH THE `print()` THAT FOLLOWS IT, not with the `_fail` above:
#: comment lines sit between them and would have to be carried verbatim, which
#: ties the anchor to prose that is free to be reworded. The trailing `print()`
#: is code, and it is what makes this branch's call distinguishable from the
#: pair-state branch's identical one.
DOCTOR = ('        _cred_actions = credential_remedy(credential_state_now())')
#: The visibility empty-read branch's state question.
VIS_STATE = ('        state = credential_state_now()\n'
             '        remedy = credential_remedy(state)')
#: The verdict a person who asked for a change is owed.
VIS_VERDICT = ('        if value != _VISIBILITY_SHOW:')
#: The relink exit's supervisor question.
RELINK_SUP = ('                if _supervisor_is_my_parent():')
#: The once-only marker on the re-exec.
RELINK_ONCE = ('                if _os.environ.get(RELINK_REEXEC_ENV) != "1":')
#: The banner's connection question.
BANNER_CONN = ('    _connected = _firebase_db is not None')
#: The footer that must not announce a listener that was skipped.
BANNER_FOOTER = ('    if _connected:\n'
                 '        print(f"  {_c(_BOLD + _ACCENT, \'  Listening for pipeline jobs.\')}  {_c(_DIM, \'Keep this terminal open.\')}")')
#: The heartbeat row.
BANNER_HB = ('        ("Heartbeat",\n'
             '         _c(_BOLD, f"{HEARTBEAT_INTERVAL_SEC}s cadence") if _connected\n'
             '         else _c(_WARN, "not beating — no connection")),')
#: The sync helper's two honest answers.
SYNC_NO_ID = ('        log("Device not paired — skipping Firestore flag update.", "WARN")\n'
              '        return False')
SYNC_FAIL = ('    log("Could not update supervised flag (REST patch failed)", "WARN")\n'
             '    return False')

#: The order inside the restart seam: the marker must be written BEFORE the
#: exec, because after it there is no "after".
SEAM_ORDER = ('        os.environ[RELINK_REEXEC_ENV] = "1"\n'
              '        os.execv(argv[0], argv)')

#: The banner's gate on WHICH machine gets the remedy.
BANNER_GATE = ('    if _cred_now != CRED_HEALTHY:')
#: The pairing offer in the banner's next actions, and what limits it.
BANNER_PAIR_GATE = ('        if _cred_now in (CRED_NEVER_PAIRED, CRED_ORPHANED):')
#: The give-up branch's refusal to lead with pairing.
GIVEUP = ('                log(\n'
          '                    "[relink] open the app and look under Devices: if this "')
#: The marker clear on a healthy boot.
MARKER_CLEAR = ('    os.environ.pop(RELINK_REEXEC_ENV, None)')
#: The real command line the restart re-execs.
SEAM_ARGV = ('    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])')
#: The tick that must depend on whether the app heard, at the pair-flow site
#: whose call was left uncaptured and crashed the default pair.
PAIR_SYNC = ('                _synced = _write_supervised_flag(True)')

MUTANTS = [
    ("W1", "under",
     "⛔⛔ the classifier asks about the TOKEN before the DEVICE ID, so a machine "
     "that has never paired is classified as one that lost its session — and is "
     "told to start a serve that has nothing to recover, instead of to pair. The "
     "order of these two questions is the whole safety property",
     [(ORDER,
       '    if not has_token:\n'
       '        return CRED_NO_TOKEN\n'
       '    if not paired_uid:\n'
       '        return CRED_ORPHANED')]),
    ("W2", "under",
     "⛔ a machine with an id but no owner link reports as never paired, so the "
     "sentence tells somebody their computer was never set up while its name and "
     "its public setting are still attached to it",
     [(ORDER,
       '    if not device_id:\n'
       '        return CRED_NEVER_PAIRED\n'
       '    if not paired_uid:\n'
       '        return CRED_NEVER_PAIRED')]),
    ("W3", "under",
     "⛔ a token the server has already refused reports as healthy, so the one "
     "command that could explain the machine says nothing at all",
     [(REJECTED, '    if False:\n        return CRED_TOKEN_REJECTED')]),
    # ⛔⛔ W4 WAS AN EQUIVALENT MUTANT AND SURVIVED ITS FIRST RUN. It added
    # CRED_NEVER_PAIRED to the recovered-states tuple — which is unreachable,
    # because that state returns four lines earlier. It changed nothing, so
    # nothing could kill it, and it reported as a survivor on the single most
    # important behaviour in this wave. An equivalent mutant is a HARNESS BUG,
    # not a test gap, and the fix is a mutant that actually restores the defect:
    # the recovered states' ACTION becomes pairing, which is the sentence that
    # was printed to the owner in production.
    ("W4", "over",
     "⛔⛔ THE PRODUCTION DEFECT, VERBATIM. The machine whose session was revoked "
     "is told to pair instead of to serve — which mints a NEW deviceId and drops "
     "the public setting, on the exact machine whose owner was trying to check it",
     [(RECOVER_ACTION,
       '             f"Then pair it again with:  {_PROG} --pair"),')]),
    ("W5", "under",
     "⛔ the keystore probe fails toward 'we have a token', so a machine that "
     "cannot even read its own keystore reports healthy and is told nothing",
     [(PROBE_FAIL, '    except Exception:\n        has_token = True')]),
    ("W6", "over",
     "⛔⛔ the banner's remedy is gated on the DISK fields again, which excludes "
     "the very machine this wave came from — device id and owner link both "
     "present, only the token revoked — so it falls through and is offered "
     "--resurrect on a boot that cannot work",
     [(BANNER_GATE, '    if not (_device_id_now and _paired_uid_now):')]),
    ("W7", "over",
     "⛔⛔ the banner offers pairing to every unhealthy machine again, including "
     "one that would lose its identity and its public listing by running it — a "
     "tenth advice site, on the busiest surface in the program",
     [(BANNER_PAIR_GATE, '        if True:')]),
    ("W20", "over",
     "⛔⛔ the hour-long give-up leads with pairing again, on a machine whose "
     "record may well still exist — the sentence that survived the wave's first "
     "pass and was caught only at cross-verify",
     [(GIVEUP,
       '                log(\n'
       '                    f"[relink] run `{_PROG} --pair` to recover. if this "')]),
    ("W21", "under",
     "⛔⛔ the restart marker is never cleared, so the guard means once per "
     "process LINEAGE — a machine that recovered from one reset refuses to "
     "restart itself after the NEXT one, reproducing the incident months later",
     [(MARKER_CLEAR, '    pass  # marker deliberately left set')]),
    ("W22", "under",
     "⛔ the restart re-execs a reconstructed command line instead of the real "
     "one, which is not this program on a pipx or console-script install and "
     "cannot run at all on Windows — the installs most likely to be unsupervised",
     [(SEAM_ARGV, '    argv = [sys.executable, *sys.argv]')]),
    ("W23", "under",
     "⛔⛔ the pair flow's supervised branch discards the sync result again, so "
     "`_synced` is read on a path that never binds it — an UnboundLocalError on "
     "the DEFAULT pair, whose cleanup handler then deletes the device that was "
     "just created",
     [(PAIR_SYNC, '                _write_supervised_flag(True)')]),
    ("W8", "over",
     "⛔⛔ the doctor goes back to appending its own hardcoded advice. The "
     "classifier can be perfect and this consumer can still print the sentence "
     "that nearly cost the owner their machine — which is how it survived every "
     "previous pass over this file",
     [(DOCTOR,
       '        _cred_actions = ["Run `python research.py --pair`"]')]),
    ("W9", "under",
     "⛔ the visibility command stops asking why the read failed and goes back to "
     "blaming the network, on the one failure it can actually name from disk",
     [(VIS_STATE,
       '        state = CRED_HEALTHY\n'
       '        remedy = []')]),
    ("W10", "under",
     "⛔⛔ a person who asked to SET a value is never told it was not changed, so "
     "the only honest reading of the output is that it might have worked",
     [(VIS_VERDICT, '        if False:')]),
    ("W11", "over",
     "⛔ every failed read claims nothing was changed, including for somebody who "
     "only asked to look — noise that buries the message that matters",
     [(VIS_VERDICT, '        if True:')]),
    ("W12", "under",
     "⛔⛔ the relink exit stops asking whether anything will restart it, so a "
     "successful recovery ends the owner's only process with exit code 0 and "
     "their machine stays off the public list until they happen to run it again",
     [(RELINK_SUP, '                if True:')]),
    ("W13", "under",
     "⛔⛔ the re-exec loses its once-only marker, so a recovery that keeps "
     "failing restarts the process forever — an invisible loop, which is worse "
     "than the defect it replaces",
     [(RELINK_ONCE, '                if True:')]),
    ("W14", "under",
     "⛔⛔ the restart marker is written AFTER the exec instead of before, which "
     "means never — the new process inherits an environment without it, so a "
     "recovery that keeps failing restarts forever and the owner sees a machine "
     "that never finishes starting",
     [(SEAM_ORDER,
       '        os.execv(argv[0], argv)\n'
       '        os.environ[RELINK_REEXEC_ENV] = "1"')]),
    ("W15", "over",
     "⛔⛔ the banner hardcodes connected, restoring the green (active) device, "
     "the heartbeat cadence and 'Keep this terminal open' on a machine whose "
     "connection had already failed and which is about to quit",
     [(BANNER_CONN, '    _connected = True')]),
    ("W16", "over",
     "⛔ the footer announces a job listener that was skipped, so a disconnected "
     "boot says it is listening for work that cannot arrive",
     [(BANNER_FOOTER,
       '    if True:\n'
       '        print(f"  {_c(_BOLD + _ACCENT, \'  Listening for pipeline jobs.\')}  {_c(_DIM, \'Keep this terminal open.\')}")')]),
    ("W17", "over",
     "⛔ the heartbeat row is a constant again, advertising a rhythm nothing is "
     "keeping",
     [(BANNER_HB,
       '        ("Heartbeat", _c(_BOLD, f"{HEARTBEAT_INTERVAL_SEC}s cadence")),')]),
    ("W18", "over",
     "⛔ a refused patch reports success, so --resurrect and --retire tell the "
     "person the app was updated when the rules turned the write down",
     [(SYNC_FAIL,
       '    log("Could not update supervised flag (REST patch failed)", "WARN")\n'
       '    return True')]),
    ("W19", "over",
     "⛔⛔ a machine with no device id reports that it synced, when it could not "
     "possibly have told the app anything at all",
     [(SYNC_NO_ID,
       '        log("Device not paired — skipping Firestore flag update.", "WARN")\n'
       '        return True')]),
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
