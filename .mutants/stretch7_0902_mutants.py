"""Mutation harness — stretch 7 (2026-09-02).

⛔⛔ WHAT THIS CODE DECIDES. Whether a button a person just pressed is executed or
silently discarded; whether the doctor's port row tells the truth or dies into a
bare `except`; and whether a refused update says a reason or a wait.

⭐⭐ THE SHARPEST MUTANTS HERE:
  S1      — the live-command guard goes and the gate dates every command again.
            That IS the defect this stretch found: `timestamp` is written by the
            BROWSER, so a machine clock ~30s ahead silently discarded every
            Settings button — Update, check-update, Restart, hard_reset, Clear
            logs and all three send-logs actions — forever, with no log line,
            because the `received action=` line sat AFTER the skip.
  S5      — the device listener stops calling the shared gate and re-inlines its
            own. This is the ORIGINAL SHAPE: the gate was written twice, #704
            fixed one copy, and the copy every Settings button used was never
            touched. The old guard read one of the two and passed.
  P1/P2   — the two real historical bugs, restored in the one place they now
            live: `ss` handed to macOS, `lsof` handed to Windows.
  P4      — the refusal re-inlines the lsof literal while the helper stays
            perfect. Helper pinned, consumer not — the failure this project has
            hit nine times.
  P8      — the doctor's failed-lookup branch goes silent again. That silence is
            the whole original defect: a dead check that reads as a clean run.
  U1      — the device-read refusal returns bare again, so the app sits on
            "started" until its own timeout and reports a WAIT, not a REASON.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS STRETCH'S OWN GUARDS by default (`-k`), because a kill
borrowed from a pre-existing test is not evidence that the guard just written
works. `--unfiltered` asks the other question — whether the TREE catches it — and
is a deliberate second run, not the default. Learned the hard way one wave ago,
where a "no filter needed" claim was measurably false.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
One typo would score every mutant killed against zero tests. `_pytest` separates
that case out and raises it as a fault; the filtered selection is counted before
the run and the baseline runs filtered AND whole.

    .venv/bin/python .mutants/stretch7_0902_mutants.py
    .venv/bin/python .mutants/stretch7_0902_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_command_stale_gate.py "
          "tests/test_stretch7_0902.py "
          "tests/test_serve_port_reclaim_0810.py "
          "tests/test_device_update_command.py")

# The guards this stretch added or rewrote. `test_the_refusal_tells_them_how_to_look`
# is included by name because it is a REWRITE — it used to pin the defect.
MINE = ("stale or port_hint or port_verdict or squatter or stuck_port or doctor or kill_hint or "
        "process_manager_label or supervisor_artifact_label or "
        "device_read_failure or that_refusal_still_reports or "
        "refusal_tells_them_how_to_look or boolean_is_not_a_timestamp or "
        "boundary_is_not_inclusive or usable_timestamp or "
        "listeners or first_snapshot or live_command")

# ⛔⛔ THE FILTER IS A SECOND PLACE THE TRUTH CAN DRIFT, AND A COUNT DOES NOT
# CATCH IT. The first version of MINE silently deselected the three behavioural
# verdict tests — the exact tests written to kill P6/P7/P10 — while
# MIN_SELECTED's "at least 15" passed on 32. All three mutants survived against
# a selection that could not see them, which reads identically to a real
# survivor. So the check is now EXACT: every test in the two files this stretch
# owns outright must be selected. "Too few" was the wrong property.
OWNED_FILES = ("tests/test_command_stale_gate.py", "tests/test_stretch7_0902.py")

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

GATE_LIVE = "    if not is_first_snapshot:\n        return False\n"
GATE_TYPES = ("    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:\n"
              "        return False\n")
GATE_CMP = "    return (now - int(ts)) > max_age_ms"

DEV_CALL = ("            if _is_stale_replay(data, is_first_snapshot):\n"
            "                try:\n"
            "                    doc.reference.update({\"processed\": True, \"staleSkipped\": True})\n"
            "                except Exception:\n"
            "                    pass\n"
            "                log(f\"[device-cmds] stale first-attach command skipped \"\n"
            "                    f\"doc={doc.id} action={(data.get('action') or '')!r}\")\n"
            "                continue\n")

REFUSAL = ('        _write_update_status(device_id, {\n'
           '            "state": "failed", "current": cur,\n'
           '            "reason": "couldn\'t read this computer\'s record — try again"},\n'
           '            merge=True)\n'
           '        return')

# (id, direction, why, [(from, to), ...])
MUTANTS = [
    # ═════════ S — the command staleness gate ═══════════════════════════════
    ("S1", "over",
     "⛔⛔⛔ THE DEFECT ITSELF. The live-command guard goes, so the gate dates every "
     "command again — and `timestamp` is the BROWSER's clock. A machine even 30s "
     "ahead silently discards every Settings button, forever, with no log line",
     [(GATE_LIVE, "")]),
    ("S2", "over",
     "the window becomes inclusive, so a command exactly at the boundary is "
     "dropped — the coarse cases both still pass",
     [(GATE_CMP, "    return (now - int(ts)) >= max_age_ms")]),
    ("S3", "over",
     "⛔ the bool guard goes. `isinstance(True, int)` is True in Python, so "
     "`{\"timestamp\": True}` is subtracted from the clock and a live command "
     "looks 1.7e12 ms old",
     [(GATE_TYPES,
       "    if not isinstance(ts, (int, float)) or ts <= 0:\n        return False\n")]),
    ("S4", "over",
     "the non-positive guard goes, so a zero or negative timestamp dates a "
     "command from the epoch and every one of them is stale",
     [(GATE_TYPES,
       "    if isinstance(ts, bool) or not isinstance(ts, (int, float)):\n"
       "        return False\n")]),
    ("S5", "over",
     "⛔⛔ THE ORIGINAL SHAPE RESTORED. The device listener stops calling the "
     "shared gate and re-inlines its own — which is exactly how #704 came to be "
     "fixed in one copy and left standing in the other",
     [(DEV_CALL,
       "            _STALE_MS = 30_000\n"
       "            _ts = data.get(\"timestamp\")\n"
       "            if isinstance(_ts, (int, float)) and _ts > 0 and \\\n"
       "                    (int(time.time() * 1000) - int(_ts)) > _STALE_MS:\n"
       "                try:\n"
       "                    doc.reference.update({\"processed\": True, \"staleSkipped\": True})\n"
       "                except Exception:\n"
       "                    pass\n"
       "                continue\n")]),
    ("S6", "under",
     "the device listener drops a stale command silently again — the reported "
     "symptom was a button that did nothing and logs showing nothing arrived",
     [("                log(f\"[device-cmds] stale first-attach command skipped \"\n"
       "                    f\"doc={doc.id} action={(data.get('action') or '')!r}\")\n", "")]),
    ("S7", "over",
     "the device listener's first-snapshot flag never flips, so the gate applies "
     "to every callback forever and live commands are dated again",
     [('        _dev_cmd_first_snapshot["v"] = False\n', "")]),
    ("S8", "under",
     "the flag starts False, so the gate never applies and a previous session's "
     "unprocessed stop replays the moment a fresh serve attaches",
     [('    _dev_cmd_first_snapshot = {"v": True}', '    _dev_cmd_first_snapshot = {"v": False}')]),

    # ═════════ P — the platform-locked hints and the dead doctor row ═════════
    ("P1", "over",
     "⛔⛔ THE MIRROR BUG RESTORED: macOS is handed `ss`, which it does not have. "
     "This is the one that printed NOTHING at all — neither pass nor fail",
     [('    if sys.platform == "darwin":\n        return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"',
       '    if sys.platform == "darwin":\n        return f"ss -ltnp | grep :{port}"')]),
    ("P2", "over",
     "⛔⛔ THE ORIGINAL BUG RESTORED: Windows is handed `lsof`, at the moment "
     "`--serve` has already exited 3",
     [('    if sys.platform == "win32":\n        return f\'netstat -ano -p TCP | findstr ":{port}"\'',
       '    if sys.platform == "win32":\n        return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"')]),
    ("P3", "under",
     "the hint drops the port, so somebody looks at every socket on the machine "
     "instead of the one that refused",
     [('        return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"',
       '        return "lsof -nP -iTCP -sTCP:LISTEN"')]),
    ("P4", "over",
     "⛔⛔ HELPER PINNED, CONSUMER NOT. The refusal re-inlines the lsof literal "
     "while `_port_holder_hint` stays perfect and every helper test still passes",
     [('              f"{_port_holder_hint(port)}\\n")',
       '              f"lsof -nP -iTCP:{port} -sTCP:LISTEN\\n")')]),
    ("P5", "under",
     "the doctor's port row is platform-gated again, so Windows loses it entirely "
     "— the quieter half of the original defect",
     [("        _holders_8000 = _port_holders(8000)",
       "        _holders_8000 = (_port_holders(8000)\n"
       "                         if plat in (\"Linux\", \"Darwin\") else None)")]),
    # ⛔⛔ P6 AND P7 BOTH SURVIVED THEIR FIRST FORM, and that is why the doctor's
    # verdict is now a function. They mutated the CONDITIONS while the assertions
    # pinned strings: `h.get("ours")` was still present in the branch BODY, and
    # "not bound" was still present in a branch made unreachable. Mutating the
    # decision itself is the only version a behavioural test can answer.
    ("P6", "over",
     "our own --serve stops being recognised, so a healthy port is reported as "
     "held by a stranger and the doctor tells somebody to kill their own backend",
     [('    for h in holders:\n        if h.get("ours"):\n            return ("ours", h)\n'
       '    return ("squatter", holders[0])',
       '    return ("squatter", holders[0])')]),
    ("P7", "over",
     "\"nothing bound\" collapses into the squatter verdict, so an unreachable API "
     "is reported as somebody else's process and the remedy is to kill nothing",
     [('    if not holders:\n        return ("unbound", None)',
       '    if not holders:\n        return ("squatter", None)')]),
    ("P10", "over",
     "the verdict looks at the first holder only, so a squatter listed ahead of "
     "our own --serve masks it — and the remedy for one is the opposite of the "
     "other",
     [('    for h in holders:\n        if h.get("ours"):', '    for h in holders[:1]:\n        if h.get("ours"):')]),
    ("P11", "over",
     "⛔ the doctor decides the row inline again, so the verdict function is "
     "perfect and nothing calls it — helper pinned, consumer not",
     [('        _verdict, _who = _port_row_verdict(_holders_8000)',
       '        _verdict, _who = (("ours", _holders_8000[0]) if _holders_8000\n'
       '                          else ("unbound", None))')]),
    ("P8", "under",
     "⛔⛔ THE ORIGINAL DEFECT, EXACTLY: a failed lookup goes silent again, so the "
     "row prints neither pass nor fail and a dead check reads as a clean run",
     [('    except Exception as _ph_err:\n'
       '        _holders_8000 = None\n'
       '        _warn("Port 8000 unknown", f"could not look: {type(_ph_err).__name__}")\n'
       '        manual_actions.append(f"Check by hand with `{_port_holder_hint(8000)}`")',
       '    except Exception:\n        _holders_8000 = None')]),
    ("P9", "over",
     "`_kill_pid_hint` hands POSIX `kill -9` to Windows — one of the three "
     "helpers this block joins, none of which had a single test before today",
     [('    if sys.platform == "win32":\n        return f"taskkill /F /PID {pid}"',
       '    if False:\n        return f"taskkill /F /PID {pid}"')]),

    # ═════════ U — the refusal that said nothing ════════════════════════════
    ("U1", "under",
     "⛔⛔ THE DEVICE-READ REFUSAL RETURNS BARE AGAIN. The app sits on \"started\" "
     "until its own timeout and then reports a WAIT rather than a REASON",
     [(REFUSAL, "        return")]),
    ("U2", "over",
     "the refusal writes without merge, so reporting on a request can lower "
     "`needsRestart` or wipe `latest` — the clobber already found once on the "
     "restart branch",
     [(REFUSAL, REFUSAL.replace("            merge=True)\n", "            )\n"))]),
    ("U3", "under",
     "the refusal writes a failed state with no reason — which is the "
     "wait-not-a-reason bug with an extra step",
     [('            "reason": "couldn\'t read this computer\'s record — try again"},',
       '            },')]),
    ("U4", "under",
     "the refusal drops `current`, so the app has a reason and no version to "
     "attach it to",
     [('            "state": "failed", "current": cur,\n'
       '            "reason": "couldn\'t read this computer\'s record — try again"},',
       '            "state": "failed",\n'
       '            "reason": "couldn\'t read this computer\'s record — try again"},')]),
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
    """Test ids pytest would run for `files` under `kfilter`."""
    args = [sys.executable, "-B", "-m", "pytest", *files,
            "--collect-only", "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    out = sh(args, cwd=ROOT, env=ENV).stdout
    return {ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(" ")}


def _filter_misses(kfilter: str) -> set:
    """Tests in this stretch's own files that the filter would NOT run.

    Non-empty means the score is being measured against a selection blind to
    some of the guards it is supposed to be scoring.
    """
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
          else "scope: THIS STRETCH'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this stretch's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS STRETCH'S OWN GUARDS, so "
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
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. The first version
            # took `killed and again`, so one unstable run in a long sequence
            # reported a mutant as SURVIVED — and six did, at the wide scope,
            # every one of which killed deterministically when re-run alone.
            # "Survived" means the guards cannot see the defect; that is a
            # completely different claim from "this run was noisy", and
            # collapsing them sends the next reader hunting a defect that is not
            # there. On disagreement, run a third time and take the majority.
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
