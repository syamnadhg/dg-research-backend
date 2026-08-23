"""Mutation harness for wave 5 fix 2 — the triage, against real sockets.

⛔ WHAT THIS IS FOR. Every verdict in the doctor's network triage was pinned
with a hand-written probe dict, and the only live run `_probe_host` has ever had
was on a WORKING network. So the harness runs ONLY the live file: a mutant that
dies here died to a real socket, which is the whole claim the new file makes.

⭐⭐ THE SHARPEST MUTANTS HERE:
  L1  — the two facts swap fields. A name that will not resolve is DNS and a
        name that resolves but will not connect is a firewall; the entire triage
        is that distinction, and swapping them still produces a confident answer.
  L4  — the probe stops absorbing failures, so the one command a stuck person
        was told to run ends on the first dead host.
  V2  — a refused connection is reported as `ok`. The person is told their
        network is fine while nothing can reach it.
  V6  — the refusing address is dropped, and that address is the only thing a
        corporate firewall request has to name.

⭐ Over-corrections:
  V7  — a partly-broken path is called a total block, which sends someone to
        their IT team over one host.

    python .mutants/network_triage_live_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

# ⛔ THE LIVE FILE ONLY, deliberately. The 2026-08-17 file pins the same verdicts
# from hand-written dicts and would kill most of these on its own — which would
# tell us nothing about whether a real socket reaches them.
T_LIVE = "tests/test_network_triage_live_0822.py"
ALL = [T_LIVE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the probe ═══════════════════════════════════════════════════════
    ("L1", "under", "⛔⛔ the two facts swap fields — a lookup failure is filed "
     "as a refused connection, and the whole triage is that distinction",
     [('        out["resolve_error"] = f"{type(exc).__name__}: {exc}"\n        return out',
       '        out["connect_error"] = f"{type(exc).__name__}: {exc}"\n        return out')],
     [T_LIVE]),
    ("L2", "under", "resolution is assumed before it is attempted, so a name "
     "that resolves nowhere reads as resolved",
     [('        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)\n'
       '        out["resolved"] = True',
       '        out["resolved"] = True\n'
       '        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)')],
     [T_LIVE]),
    ("L3", "under", "the connection is never attempted, so every host on a "
     "perfectly good network reads as blocked",
     [('        with socket.create_connection((host, port), timeout=timeout):\n'
       '            out["connected"] = True',
       '        with socket.create_connection((host, port), timeout=timeout):\n'
       '            pass')],
     [T_LIVE]),
    ("L4", "under", "⛔⛔ the probe stops absorbing failures, so the one command "
     "a stuck person was told to run ends on the first dead host",
     [('    except Exception as exc:\n'
       '        out["resolve_error"] = f"{type(exc).__name__}: {exc}"',
       '    except ZeroDivisionError as exc:\n'
       '        out["resolve_error"] = f"{type(exc).__name__}: {exc}"')],
     [T_LIVE]),
    ("L5", "under", "the resolved address is not recorded, so an IT ticket has "
     "no address to name",
     [('            out["addr"] = str(infos[0][4][0])', '            out["addr"] = ""')],
     [T_LIVE]),
    ("L6", "under", "the failure is recorded without its type, so two different "
     "faults read the same in a support bundle",
     [('        out["resolve_error"] = f"{type(exc).__name__}: {exc}"',
       '        out["resolve_error"] = f"{exc}"')],
     [T_LIVE]),
    ("L7", "under", "a refusal is not recorded at all, so `blocked_after_dns` "
     "arrives with nothing behind it",
     [('        out["connect_error"] = f"{type(exc).__name__}: {exc}"',
       '        out["connect_error"] = ""')],
     [T_LIVE]),

    # ══ the verdict ═════════════════════════════════════════════════════
    ("V1", "under", "nothing resolving is no longer `no_dns`",
     [('    if not g_res and not c_res:', '    if False:')],
     [T_LIVE]),
    ("V2", "under", "⛔⛔ a refused connection reads as `ok` — the person is told "
     "their network is fine while nothing can reach us",
     [('    if not unresolved and not unconnected:', '    if not unresolved:')],
     [T_LIVE]),
    ("V3", "under", "the google/control test is inverted, so the corporate-"
     "resolver case is called the opposite of what it is",
     [('    if c_res and not g_res:', '    if g_res and not c_res:')],
     [T_LIVE]),
    ("V4", "under", "⛔ `blocked_after_dns` also claims the cases where a name "
     "did not resolve, so DNS faults are reported as firewalls",
     [('    if unconnected and not unresolved:', '    if unconnected:')],
     [T_LIVE]),
    ("V5", "under", "a healthy path is handed actions to take, so a person is "
     "sent to their IT team over nothing",
     [('        return {"kind": "ok",\n'
       '                "headline": "The network path is fine — every host this machine "\n'
       '                            "needs resolves and accepts a connection.",\n'
       '                "actions": [], "blocked_addrs": []}',
       '        return {"kind": "ok",\n'
       '                "headline": "The network path is fine — every host this machine "\n'
       '                            "needs resolves and accepts a connection.",\n'
       '                "actions": ["Disconnect any VPN and run this again."],\n'
       '                "blocked_addrs": []}')],
     [T_LIVE]),
    ("V6", "under", "⛔⛔ the refusing address is dropped, and it is the one "
     "thing a corporate firewall request has to name",
     [('    blocked = [p.get("addr", "") for p in unconnected if p.get("addr")]',
       '    blocked = []')],
     [T_LIVE]),
    ("V7", "over", "a partly-broken path is called a total block, which sends "
     "someone to their IT team over one host",
     [('    return {\n        "kind": "partial",', '    return {\n        "kind": "no_dns",')],
     [T_LIVE]),
    ("V8", "under", "the last verdict hands over nothing to do, which is the "
     "founding complaint about this command",
     [('        "actions": [\n'
       '            "Disconnect any VPN and run this again — a split-tunnel VPN produces "\n'
       '            "exactly this pattern.",\n'
       '            "If it persists, the per-host detail above is what to send us.",\n'
       '        ],',
       '        "actions": [],')],
     [T_LIVE]),

    # ══ the target list itself ══════════════════════════════════════════
    ("T1", "under", "a shipped hostname is misspelled, so the doctor reports a "
     "blocked network on every machine on earth",
     [('    (FIRESTORE_HOST, "the channel your machine and the web app talk over", "google"),',
       '    ("firestore.googelapis.com", "the channel your machine and the web app talk over", "google"),')],
     [T_LIVE]),
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
