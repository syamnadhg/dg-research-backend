"""Mutation harness for wave 2 step 5 — `--send-logs` from the terminal.

⛔⛔ THE MUTANT TO READ FIRST IS L1. It gates the unauthenticated fallback on the
machine being unpaired — which is the shape the first draft of this design had,
and it would have excluded the founding case exactly: a PAIRED machine whose
Google DNS was dead, so securetoken, firestore and firebasestorage were all
gone. A fallback that skips the case it was built for is the repo's signature
defect wearing a network costume.

⭐ THE OTHER ONES THAT MATTER:
  Y1  — the confirmation defaults to yes, so one stray Enter ships somebody's
        research topics and their result links.
  Y3  — the 30-day deletion sentence prints while no bucket lifecycle rule
        exists anywhere. That is a lie of exactly the kind wave 1 spent itself
        removing, which is why the sentence sits behind a flag.
  F1  — the local file is written AFTER the network attempts, so the floor the
        whole design rests on is gone whenever the process dies mid-upload.
  L3  — a support code is printed for a bundle that is nowhere, which leads a
        support conversation to an empty bucket.
  R1/R4 — the index row. Dropping a failed write loses it forever; hanging the
        replay off the outage-cleared edge never fires for a terminal
        `--send-logs`, which has no Firestore client to have been "down".
  I4  — the install id header goes, and it is the ONLY thing that can link an
        unpaired bundle to an account once pairing finally works.

    python .mutants/send_logs_cli_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_CLI = "tests/test_send_logs_cli_0818.py"
T_TRIAGE = "tests/test_network_triage_0817.py"
T_SEND = "tests/test_send_logs_command_0818.py"
ALL = [T_CLI, T_TRIAGE, T_SEND]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ consent ═════════════════════════════════════════════════════════
    ("Y1", "under", "⛔⛔ the confirmation defaults to YES, so one stray Enter "
     "ships somebody's topics and their result links",
     [('            if not _ask_yes_no_sync("Send this to the team?", default=False):',
       '            if not _ask_yes_no_sync("Send this to the team?", default=True):')],
     [T_CLI]),
    ("Y2", "under", "the consent screen stops naming the result links — the one "
     "item on the list that hands a reader the research itself",
     [('        "links that open your research results — anyone holding one can read them",',
       '')],
     [T_CLI]),
    ("Y2b", "under", "the screen stops naming the hostname and the OS account",
     [('        "this computer\'s hostname and the account name you sign into it with",',
       '')],
     [T_CLI]),
    ("Y3", "over", "⛔⛔ the 30-day deletion promise prints while no bucket "
     "lifecycle rule exists in any repo — the exact class of lie wave 1 removed",
     [('    if BUNDLE_LIFECYCLE_VERIFIED:\n        lines.append("and it is deleted automatically after 30 days")',
       '    lines.append("and it is deleted automatically after 30 days")')],
     [T_CLI]),
    ("Y4", "under", "the gate ignores its own flag, so flipping it after the "
     "bucket rule lands changes nothing — a gate that is decoration",
     [('    if BUNDLE_LIFECYCLE_VERIFIED:\n        lines.append("and it is deleted automatically after 30 days")',
       '    if False:\n        lines.append("and it is deleted automatically after 30 days")')],
     [T_CLI]),
    ("Y5", "under", "the prompt is skipped entirely, so the screen becomes a "
     "notice rather than a decision",
     [('    if not assume_yes:', '    if False:')],
     [T_CLI]),
    ("Y6", "under", "declining sends anyway",
     [('                print(f"  {_c(_DIM, \'Nothing was sent.\')}")\n                return 0',
       '                pass')],
     [T_CLI]),
    ("Y7", "under", "the raw device logs are folded into the 30-day sentence, "
     "making that half a claim about bytes it does not cover",
     [('        "this device\'s own log files — the most recent few megabytes of each, "\n        "whatever their age",',
       '        "this device\'s own log files",')],
     [T_CLI]),

    # ══ the floor ═══════════════════════════════════════════════════════
    ("F1", "under", "⛔⛔ the local file is written AFTER the network attempts, so "
     "the floor is gone whenever the process dies mid-upload",
     [('    print(f"  {_c(_OK, \'✓\')}  Bundle written  {_c(_BOLD, str(dest))}")\n',
       '')],
     [T_CLI]),
    ("F2", "under", "the bundle's path is not printed, so the file exists and "
     "nobody can find it",
     [('    print(f"     {_c(_BOLD, str(dest))}")\n    return 0', '    return 0')],
     [T_CLI]),
    ("F3", "over", "a send that fell back to the local file exits non-zero, so "
     "every script treats the floor as a failure",
     [('    print(f"     {_c(_BOLD, str(dest))}")\n    return 0',
       '    print(f"     {_c(_BOLD, str(dest))}")\n    return 1')],
     [T_CLI]),
    ("F4", "under", "a bundle that could not be built leaves the reader with "
     "nothing — not even where the raw logs are",
     [('        print(f"  {_c(_DIM, \'The raw logs are still here:\')}  "\n              f"{_c(_BOLD, str(_logs_root()))}")\n',
       '')],
     [T_CLI]),
    ("F5", "under", "the truncation notice goes, so a bundle that quietly "
     "dropped the run being asked about reads as complete coverage",
     [('    if _n_dropped:', '    if False:')],
     [T_CLI, T_SEND]),

    # ══ the ladder ══════════════════════════════════════════════════════
    ("L1", "under", "⛔⛔ THE FOUNDING CASE, EXCLUDED. The fallback is gated on "
     "the machine being unpaired — and the machine that started this wave was "
     "paired with Google DNS dead",
     # Re-anchored 2026-08-18 when the server-minted code landed; the ratchet
     # caught the stale anchor in the same suite run.
     [('    if not landed_via:\n        _server_code = _post_bundle_to_ingest(dest, code, email=email)',
       '    if not landed_via and not device_id:\n        _server_code = _post_bundle_to_ingest(dest, code, email=email)')],
     [T_CLI]),
    ("L2", "under", "the authenticated route is never tried, so every bundle "
     "goes through the open door even when the account works",
     [('    if id_token and owner_uid and device_id:', '    if False:')],
     [T_CLI]),
    ("L3", "under", "⛔ a support code is printed for a bundle that is nowhere, "
     "leading a support conversation to an empty bucket",
     [('    if landed_via:\n        print(f"  {_c(_OK, \'✓\')}  Sent via {_c(_BOLD, landed_via)}")',
       '    if True:\n        print(f"  {_c(_OK, \'✓\')}  Sent via {_c(_BOLD, landed_via)}")')],
     [T_CLI]),
    ("L4", "under", "the printed code is minted separately from the one the "
     "object was stored under",
     [('        print(f"  {_c(_BOLD, \'Your support code is\')}  {_c(_BOLD + _ACCENT, code)}")',
       '        print(f"  {_c(_BOLD, \'Your support code is\')}  {_c(_BOLD + _ACCENT, _mint_support_code())}")')],
     [T_CLI]),
    ("L5", "under", "the sign-in failure is silent, so the reader cannot tell "
     "why their account was not used",
     [('        print(f"  {_c(_DIM, \'This machine could not sign in, so the account route is\')} "',
       '        print(f"  {_c(_DIM, \'\')}" if False else "" or f"  {_c(_DIM, \'x\')} "')],
     [T_CLI]),

    # ══ the row that appears late, never never ══════════════════════════
    ("R1", "under", "⛔ a row that could not be written is dropped instead of "
     "parked, so the upload succeeds and the account never learns of it — and "
     "Clear Shared Logs walks ROWS, so the object becomes unreachable",
     [('            if not (_open_log_bundle_row(owner_uid, code, device_id or "", "")\n                    and _write_log_bundle_status(owner_uid, code, patch)):\n                _queue_log_bundle_row(owner_uid, code, patch,\n                                      device_id=device_id or "")',
       '            _open_log_bundle_row(owner_uid, code, device_id or "", "")\n            _write_log_bundle_status(owner_uid, code, patch)')],
     [T_CLI]),
    ("R1b", "under", "⛔⛔ THE DEFECT THE EMULATOR CAUGHT, RESTORED on the terminal "
     "path: the row is CREATED at 'done', which the rule denies — so every "
     "terminal send leaves a readable bundle that Clear Shared Logs cannot see, "
     "on a product where no bucket lifecycle rule exists yet",
     [('            if not (_open_log_bundle_row(owner_uid, code, device_id or "", "")\n                    and _write_log_bundle_status(owner_uid, code, patch)):',
       '            if not _write_log_bundle_status(owner_uid, code, patch, create=True):')],
     [T_CLI]),
    ("R1c", "under", "the parked replay creates from the patch again, reproducing "
     "the denial it exists to work around",
     [('        if (_open_log_bundle_row(owner, code, row.get("deviceId") or "")\n                and _write_log_bundle_status(owner, code, row.get("patch") or {})):',
       '        if _write_log_bundle_status(owner, code, row.get("patch") or {}, create=True):')],
     [T_CLI]),
    ("R2", "under", "nothing ever replays the parked rows",
     [('                _drain_queued_log_bundle_rows()\n', '')],
     [T_CLI]),
    ("R3", "under", "the drain deletes rows it could not write, losing them",
     [('        if still_owed:\n            path.write_text("\\n".join(still_owed) + "\\n", encoding="utf-8")\n        else:\n            path.unlink()',
       '        path.unlink()')],
     [T_CLI]),
    ("R4", "under", "⛔⛔ the replay hangs off the outage-cleared EDGE, which never "
     "fires for a terminal --send-logs: that process has no Firestore client to "
     "have been down in the first place",
     [('                _drain_queued_log_bundle_rows()\n', ''),
      ('def _clear_firestore_down(', 'def _clear_firestore_down_UNUSED(')],
     [T_CLI]),
    ("R5", "under", "the drain reports success for rows it never wrote",
     [('        if (_open_log_bundle_row(owner, code, row.get("deviceId") or "")\n                and _write_log_bundle_status(owner, code, row.get("patch") or {})):\n            landed += 1\n        else:\n            still_owed.append(line)',
       '        _open_log_bundle_row(owner, code, row.get("deviceId") or "")\n        _write_log_bundle_status(owner, code, row.get("patch") or {})\n        landed += 1')],
     [T_CLI]),

    # ══ the open route ══════════════════════════════════════════════════
    ("I1", "under", "the local size pre-check goes, so an over-cap body is sent "
     "and refused by the route instead of never leaving",
     [('    if size > BUNDLE_INGEST_MAX_BYTES:', '    if False:')],
     [T_CLI]),
    ("I2", "under", "the content type goes off the ingest POST",
     [('        "Content-Type": BUNDLE_CONTENT_TYPE,\n        "X-Support-Code": code,',
       '        "X-Support-Code": code,')],
     [T_CLI]),
    ("I3", "under", "a refusal from the route is reported as a send",
     [('    if resp.status_code != 200:\n        log(f"[send-logs] ingest refused: HTTP {resp.status_code} "',
       '    if False:\n        log(f"[send-logs] ingest refused: HTTP {resp.status_code} "')],
     [T_CLI]),
    ("I4", "under", "⛔⛔ the install id goes, and it is the ONLY thing that can "
     "link an unpaired bundle to an account once pairing finally works",
     [('        "X-Install-Id": str(_install_uuid_best_effort() or ""),\n', '')],
     [T_CLI]),
    ("I5", "under", "an unreachable host raises out of the command instead of "
     "falling through to the printed local file",
     [('    except Exception as exc:\n        log(f"[send-logs] {url} unreachable: {type(exc).__name__}: {exc}", "WARN")\n        return None',
       '    except Exception as exc:\n        raise')],
     [T_CLI]),
    ("I6", "under", "an empty email header is sent when the user gave none, "
     "which is a claim about a person that is not true",
     [('    if email:\n        headers["X-Contact-Email"] = email',
       '    headers["X-Contact-Email"] = email or ""')],
     [T_CLI]),

    # ══ the hand-over line and the probe list ══════════════════════════
    ("D1", "under", "the doctor stops probing the host the upload rides, so a "
     "machine that reaches firestore but not storage gets the wrong diagnosis",
     [('    ("firebasestorage.googleapis.com",\n     "where your logs and podcasts are uploaded", "google"),\n', '')],
     [T_CLI]),
    ("D2", "under", "the hand-over line stops naming the command that now exists",
     [('    return (f"Still stuck? Run {_PROG} --send-logs to hand your logs to us, "',
       '    return (f"Still stuck? "')],
     [T_TRIAGE]),
    ("D3", "over", "⛔ the line names ONLY the command, so a reader with no shell "
     "open — and no idea what a shell is — has nothing left",
     [('            f"or send the file yourself — {_STATE_DIR / \'logs\' / \'backend.log\'} "\n            f"— or use Report Bug on the web app\'s Settings page.")',
       '            f"and that is the only way.")')],
     [T_TRIAGE]),
    ("D4", "under", "the command is dispatched after the doctor, so the person "
     "who just read the hand-over line and typed it lands on a doctor run",
     [('    if args.send_logs:\n        raise SystemExit(cmd_send_logs(assume_yes=bool(args.assume_yes),\n                                      email=args.contact_email,\n                                      runs=args.send_logs_runs))\n\n    if args.doctor:\n        run_doctor()\n        return',
       '    if args.doctor:\n        run_doctor()\n        return\n\n    if args.send_logs:\n        raise SystemExit(cmd_send_logs(assume_yes=bool(args.assume_yes),\n                                      email=args.contact_email,\n                                      runs=args.send_logs_runs))')],
     [T_CLI]),
    ("D5", "under", "⛔ the terminal's --runs never reaches the builder, so the "
     "flag is accepted and ignored",
     [('        summary = _build_log_bundle(dest, support_code=code, max_runs=n_runs)',
       '        summary = _build_log_bundle(dest, support_code=code)')],
     [T_CLI]),
    ("D6", "under", "the terminal's consent screen describes a number it will not "
     "use",
     [('    for line in _send_logs_consent_lines(n_runs):', '    for line in _send_logs_consent_lines():')],
     [T_CLI]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing. Three earlier waves had
        # already learned this and set the flag; it was never propagated.
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
