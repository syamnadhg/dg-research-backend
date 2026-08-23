"""Mutation harness for wave 5 fix 3 — a missing dependency is not a network.

⛔ WHAT THIS IS FOR. `init_firebase` filed a failed `from auth import …` as
"transient", so a retry ladder that cannot possibly succeed ran for as long as
the machine stayed on, saying "could not reach Google" about a network that was
fine — and `--doctor`, reading the same field, told the person a host was
unreachable and then that their network was healthy, with nothing to do.

⭐⭐ THE SHARPEST MUTANTS HERE:
  C1  — the classification goes back to "transient". Every downstream consumer
        starts lying again from one word.
  L1  — the stand-down branch moves BELOW the transient ladder, so it can never
        be reached. The branch still exists, the tests about its contents still
        pass, and nothing changes on a real machine.
  L4  — the re-check floor goes, and the stand-down is a retry ladder again with
        a nicer message on top.
  D1  — the doctor's new branch moves after the network one, which is the exact
        ordering the fix is about.
  N2  — the notice stops saying the network and the pairing are fine, which is
        the sentence that stops someone spending an afternoon on their VPN.

⭐ Over-corrections:
  L5  — the re-check is removed entirely, so a person who runs the repair
        command is told nothing and has to restart the backend to find out.
  L7  — a repair mid-run respawns the process, which is what the reconnect path
        learned not to do.

    python .mutants/broken_install_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_BROKEN = "tests/test_broken_install_terminal_0822.py"
# ⛔ The doctor's own file owns the branch order these mutants also reach.
T_TRIAGE = "tests/test_network_triage_0817.py"
ALL = [T_BROKEN, T_TRIAGE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the classification ══════════════════════════════════════════════
    ("C1", "under", "⛔⛔ a missing package is filed as transient again, and "
     "every consumer downstream starts blaming the network from one word",
     [('        _firebase_down_reason = "broken_install"\n        return False',
       '        _firebase_down_reason = "transient"\n        return False')],
     [T_BROKEN]),
    ("C2", "under", "it is filed as a revoke, so the person is sent to re-pair "
     "a pairing that was never the problem",
     [('        _firebase_down_reason = "broken_install"\n        return False',
       '        _firebase_down_reason = "revoked"\n        return False')],
     [T_BROKEN]),
    ("C3", "under", "the exception type is dropped, so a missing package and a "
     "broken one read identically in a support bundle",
     [('            f"({type(e).__name__}: {e}) — the install on this computer is "',
       '            f"— the install on this computer is "')],
     [T_BROKEN]),
    # ⛔ C4 RE-ANCHORED 2026-08-22. `except ImportError as e:` appears four
    # times in this file, so the first version measured nothing at all. Anchored
    # on the handler's own first line instead, which is unique.
    ("C4", "over", "every init failure is called a broken install, so a real "
     "network outage is answered with a reinstall",
     [('    except ImportError as e:\n'
       '        # ⛔⛔ THIS IS NOT A HICCUP.',
       '    except Exception as e:\n'
       '        # ⛔⛔ THIS IS NOT A HICCUP.')],
     [T_BROKEN]),

    # ══ the notice ══════════════════════════════════════════════════════
    ("N1", "under", "the repair command is not named, so the reader is told "
     "what is wrong and not what to do",
     [('        f"[install] Repair it with:  {remedy}",', '')],
     [T_BROKEN]),
    ("N2", "under", "⛔⛔ it stops saying the network and the pairing are fine — "
     "the sentence that stops an afternoon spent on a VPN",
     [('        "reach the web app at all. Your network is fine and your pairing is "\n'
       '        "fine — the install on this computer is incomplete.",',
       '        "reach the web app at all.",')],
     [T_BROKEN]),
    ("N3", "under", "the re-check interval is written out as a literal, so it "
     "drifts silently the moment the constant moves",
     [('    minutes = max(1, int(float(recheck_s) // 60))', '    minutes = 10')],
     [T_BROKEN]),
    ("N4", "under", "the remedy is written out here instead of read from the "
     "one place that knows which install this is",
     [('    remedy = remedy or _remedy_reinstall()', '    remedy = remedy or "pip install -r requirements.txt"')],
     [T_BROKEN]),
    ("N5", "under", "the hand-over is dropped, so someone the remedy does not "
     "help is left holding it",
     [('        f"[install] {_doctor_share_logs_line()}",', '')],
     [T_BROKEN]),
    ("N6", "under", "the notice becomes one multi-line string, so every line "
     "after the first loses its timestamp and its level",
     [('    return [\n        "[install] This backend cannot import part of itself, so it cannot "',
       '    return ["\\n".join([\n        "[install] This backend cannot import part of itself, so it cannot "')],
     [T_BROKEN]),

    # ══ the loop ════════════════════════════════════════════════════════
    ("L1", "under", "⛔⛔ the stand-down is unreachable — the transient ladder "
     "claims the case first, and every test about the branch still passes",
     [('            if _firebase_down_reason == "broken_install":\n'
       '                # ⛔⛔ STAND DOWN, AND SAY WHY ONCE.',
       '            if False:\n'
       '                # ⛔⛔ STAND DOWN, AND SAY WHY ONCE.')],
     [T_BROKEN]),
    ("L2", "under", "the remedy is said on every pass of a five-second loop, "
     "which is wallpaper rather than a message",
     [('                if broken_spoken_at is None:\n'
       '                    for _line in _broken_install_notice():',
       '                if True:\n'
       '                    for _line in _broken_install_notice():')],
     [T_BROKEN]),
    ("L3", "under", "it is never said at all, so a stood-down backend is "
     "silent about why it stopped",
     [('                if broken_spoken_at is None:\n'
       '                    for _line in _broken_install_notice():\n'
       '                        log(_line, "ERROR")\n'
       '                    broken_spoken_at = time.time()',
       '                broken_spoken_at = broken_spoken_at or time.time()')],
     [T_BROKEN]),
    ("L4", "under", "⛔⛔ the re-check floor goes, so the stand-down is the same "
     "retry ladder with a nicer message on top of it",
     [('                if time.time() - broken_last_try < FIRESTORE_BROKEN_INSTALL_RECHECK_S:',
       '                if False:')],
     [T_BROKEN]),
    ("L5", "over", "the re-check is removed entirely, so someone who runs the "
     "repair command has to restart the backend to find out it worked",
     [('                broken_last_try = time.time()\n'
       '                if await asyncio.to_thread(init_firebase):',
       '                broken_last_try = time.time()\n'
       '                if False:')],
     [T_BROKEN]),
    ("L6", "under", "a repair is picked up in silence, so the alarm above is "
     "the last word the log ever has on the subject",
     [('                    log("[install] The missing package is back — this computer is "\n'
       '                        "online in the web app again. Nothing to do.", "INFO")',
       '                    pass')],
     [T_BROKEN]),
    ("L7", "over", "a repair mid-run respawns the process, aborting the handoff "
     "the reconnect path learned to wait for",
     [('                    if _QUEUE_STATE.get("running"):\n'
       '                        pending_respawn = True\n'
       '                    else:\n'
       '                        await _recover_after_reconnect("the install was repaired")',
       '                    await _recover_after_reconnect("the install was repaired")')],
     [T_BROKEN]),
    ("L8", "under", "the loop stops ticking its liveness pulse on this branch, "
     "so the watchdog force-respawns a worker that is behaving correctly",
     [('            _last_loop_tick_ms = int(time.time() * 1000)',
       '            _last_loop_tick_ms = _last_loop_tick_ms')],
     [T_BROKEN]),

    # ══ the doctor ══════════════════════════════════════════════════════
    ("D1", "under", "⛔⛔ the doctor's branch moves below the network one, which "
     "is the exact ordering this fix is about",
     [('    elif _firebase_down_reason == "broken_install":\n'
       '        # ⛔⛔ THIS BRANCH DID NOT EXIST, and its absence made the doctor lie the',
       '    elif False:\n'
       '        # ⛔⛔ THIS BRANCH DID NOT EXIST, and its absence made the doctor lie the')],
     [T_BROKEN, T_TRIAGE]),
    ("D2", "under", "the branch reports no action, which is the founding "
     "complaint about this command",
     [('        manual_actions.append(_remedy_reinstall())\n'
       '    elif _firebase_down_reason == "transient":',
       '    elif _firebase_down_reason == "transient":')],
     [T_BROKEN]),
    ("D3", "under", "a broken install is a warning rather than a failure, so a "
     "machine that cannot work at all reports as nearly fine",
     [('        _fail("This install is incomplete",', '        _warn("This install is incomplete",')],
     [T_BROKEN]),
    ("D4", "under", "the branch probes the network anyway, so the reader is "
     "told a host is unreachable and then that the network is fine",
     [('        _fail("This install is incomplete",\n'
       '              "part of the backend is missing — the network and the pairing "\n'
       '              "are both fine")',
       '        _fail("This install is incomplete",\n'
       '              f"{_network_verdict([_probe_host(t[0]) for t in _DOCTOR_NET_TARGETS])}")')],
     [T_BROKEN]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
