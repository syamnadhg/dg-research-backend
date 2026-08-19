"""Mutation harness for wave 2 step 4 — the send-logs device command.

⛔⛔ THE SHARPEST MUTANTS IN THIS FILE, because each leaves a working-looking
button that has quietly given something away or stopped working:

  W1  — `send-logs` off the worker-1 skip tuple. Both failure modes are written
        in that block's own comments: every non-1 worker races the archive
        build, AND a sibling's tail-delete of the command doc can be coalesced
        away inside a stream-resync window, dropping the command with no replay.
  O3  — the owner check goes, so a sharer can ship the contents of somebody
        else's machine.
  S1  — the sink-side consent check goes. The app's modal still shows, so
        nothing looks different; the next command writer just does not get asked.
  U1  — the Content-Type header goes. `requests` sends none for a raw file body
        and the storage rule pins it, so our own honest upload takes a 403 — and
        the retry ladder treats a 403 as claim-propagation, so a terminal
        refusal is retried to exhaustion and then reported as transient.
  U2  — the local size pre-check goes, which makes that same cap-403 reachable.
  D2  — the cooldown stamp moves to AFTER the work, so "kill it and press again"
        becomes an unlimited loop.
  R1  — the first status write stops creating the row, so every later update
        lands on a document that does not exist and the app's spinner never
        resolves even on a perfect upload.
  L1  — the local bundle is deleted once the upload fails, removing the floor
        the entire design rests on: the file the user can attach by hand when
        nothing on the network works.

⭐ Over-corrections:
  C4  — the alphabet regains I, L, O and U, so a code read aloud comes back as a
        different one.
  D3  — the cooldown fails CLOSED on an unreadable stamp, making one bad write a
        permanent lockout.
  F2  — the in-flight flag is not released, so a single failure wedges the
        button for the life of the process.
  R5  — a status-write failure aborts an upload that was working. The tool must
        be diagnosable, but a diagnostic must not break delivery.

    python .mutants/send_logs_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_SEND = "tests/test_send_logs_command_0818.py"
T_BUNDLE = "tests/test_log_bundle_0818.py"
ALL = [T_SEND, T_BUNDLE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the worker gate ═════════════════════════════════════════════════
    ("W1", "under", "⛔⛔ send-logs off the worker-1 skip tuple — every non-1 "
     "worker races the build, and a sibling's tail-delete can be coalesced away",
     [('                            SEND_LOGS_ACTION,\n', '')],
     [T_SEND]),
    ("W1b", "under", "⛔⛔ the LIMITED action leaves the tuple, so it falls to the "
     "`else` and every non-primary worker DELETES the command before worker 1 "
     "sees it — the feature ships dead with nothing failing anywhere",
     [('                            SEND_LOGS_LIMITED_ACTION) and WORKER_ID != 1:',
       '                            ) and WORKER_ID != 1:')],
     [T_SEND]),
    ("W2", "under", "the dispatch stops gating on worker 1, so every worker in "
     "the fleet builds its own archive of the same machine",
     [('                if WORKER_ID == 1:\n                    _handle_send_logs_command(',
       '                if True:\n                    _handle_send_logs_command(')],
     [T_SEND]),
    ("W2b", "under", "⛔ the limited action is handled as an unlimited one, so the "
     "number the person chose is silently ignored on the ONE path that exists to "
     "honour it",
     [('                        limited=(action == SEND_LOGS_LIMITED_ACTION))',
       '                        limited=False)')],
     [T_SEND]),
    ("W3", "over", "the handler runs inline on the snapshot callback, queueing "
     "restart and hard_reset behind a tens-of-seconds upload and into the 30s "
     "stale reaper",
     [('    _log_threading.Thread(target=_work, name="send-logs", daemon=True).start()',
       '    _work()')],
     [T_SEND]),

    # ══ the support code ════════════════════════════════════════════════
    ("C1", "under", "the handler stops checking the code's shape, and the code "
     "is a storage path segment",
     [('    if not _SUPPORT_CODE_RE.match(code):\n        log("[send-logs] refusing: no valid support code in the command", "WARN")\n        return',
       '    if False:\n        log("[send-logs] refusing: no valid support code in the command", "WARN")\n        return')],
     [T_SEND]),
    ("C2", "under", "the upload stops checking it too, so a traversal reaches "
     "the object name",
     [('    if not _SUPPORT_CODE_RE.match(str(code or "")):\n        log("[send-logs] refusing upload: support code is not the expected shape", "WARN")\n        return None',
       '    if False:\n        log("[send-logs] refusing upload: support code is not the expected shape", "WARN")\n        return None')],
     [T_SEND]),
    ("C3", "under", "⛔ the code comes from `random` instead of the CSPRNG — and "
     "the code IS the read capability for an unpaired bundle",
     [('    import secrets\n    return "".join(secrets.choice(_SUPPORT_CODE_ALPHABET) for _ in range(8))',
       '    import random\n    return "".join(random.choice(_SUPPORT_CODE_ALPHABET) for _ in range(8))')],
     [T_SEND]),
    ("C4", "over", "I, L, O and U rejoin the alphabet, so a code read aloud "
     "comes back as a different code",
     [('_SUPPORT_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"',
       '_SUPPORT_CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"')],
     [T_SEND]),
    ("C5", "under", "the code shrinks to four characters, so it is guessable by "
     "hand",
     [('for _ in range(8))', 'for _ in range(4))')],
     [T_SEND]),

    # ══ owner-only, refusing on doubt ═══════════════════════════════════
    ("O1", "under", "a device read failure proceeds instead of refusing — the "
     "one moment the answer is unknown is the one moment it must not guess",
     [('        log(f"[send-logs] refusing: device read failed ({exc})", "WARN")\n        return',
       '        dev = {"ownerUid": data.get("submittedBy")}')],
     [T_SEND]),
    ("O2", "under", "a command naming no submitter is accepted",
     [('    if not submitted_by:\n        log("[send-logs] refusing: the command names no submitter", "WARN")\n        return',
       '    if False:\n        log("[send-logs] refusing: the command names no submitter", "WARN")\n        return')],
     [T_SEND]),
    ("O3", "under", "⛔⛔ the owner check goes, so a SHARER can ship the contents "
     "of somebody else's machine",
     [('    if submitted_by != owner_uid:\n        log("[send-logs] refusing: submittedBy is not the device owner", "WARN")\n        return',
       '    if False:\n        log("[send-logs] refusing: submittedBy is not the device owner", "WARN")\n        return')],
     [T_SEND]),
    ("O4", "under", "a device with no recorded owner proceeds, and writes into "
     "whatever tree the command named",
     [('    if not owner_uid:\n        log("[send-logs] refusing: this device has no recorded owner", "WARN")\n        return',
       '    if False:\n        log("[send-logs] refusing: this device has no recorded owner", "WARN")\n        return')],
     [T_SEND]),

    # ══ consent at the sink ═════════════════════════════════════════════
    ("S1", "under", "⛔⛔ the sink-side consent check goes. The modal still shows, "
     "so nothing looks different — the next command writer just is not asked",
     [('    if data.get("consent") is not True:', '    if False:')],
     [T_SEND]),
    ("S2", "under", "consent becomes merely truthy, so the string \"true\" from a "
     "hand-written command counts as a human agreeing",
     [('    if data.get("consent") is not True:', '    if not data.get("consent"):')],
     [T_SEND]),

    # ══ the cooldown ════════════════════════════════════════════════════
    ("D1", "under", "the cooldown is not consulted, so the button is an "
     "unbounded upload loop",
     [('    remaining = _send_logs_cooldown_remaining()\n    if remaining:',
       '    remaining = 0\n    if remaining:')],
     [T_SEND]),
    ("D2", "under", "⛔⛔ the attempt is stamped AFTER the work, so killing the "
     "process mid-bundle and pressing again is an unlimited loop",
     [('            _stamp_send_logs_attempt()\n            _open_log_bundle_row(owner_uid, code, device_id, request_id)',
       '            _open_log_bundle_row(owner_uid, code, device_id, request_id)')],
     [T_SEND]),
    ("D3", "over", "an unreadable stamp fails CLOSED, so one bad write locks the "
     "button out permanently",
     [('    except Exception:\n        return 0\n    elapsed =',
       '    except Exception:\n        return int(cooldown)\n    elapsed =')],
     [T_SEND]),
    ("D4", "under", "the cooldown window collapses to nothing",
     [('SEND_LOGS_COOLDOWN_SEC = 10 * 60', 'SEND_LOGS_COOLDOWN_SEC = 0')],
     [T_SEND]),

    # ══ single-flight ═══════════════════════════════════════════════════
    ("F1", "under", "two presses build two archives of the same machine at once",
     [('        if _send_logs_inflight:\n            log("[send-logs] refusing: a bundle is already being built", "WARN")\n            return',
       '        if False:\n            log("[send-logs] refusing: a bundle is already being built", "WARN")\n            return')],
     [T_SEND]),
    ("F2", "over", "the in-flight flag is never released, so ONE failure wedges "
     "the button for the life of the process",
     [('            with _SEND_LOGS_LOCK:\n                _send_logs_inflight = False',
       '            pass')],
     [T_SEND]),

    # ══ the row the app watches ═════════════════════════════════════════
    ("R1", "under", "⛔⛔ the row is never opened, so every later update lands on a "
     "document that does not exist and the spinner never resolves even on a "
     "perfect upload",
     [('            _open_log_bundle_row(owner_uid, code, device_id, request_id)\n            dest =',
       '            dest =')],
     [T_SEND]),
    ("R1b", "under", "⛔⛔ THE DEFECT THE EMULATOR CAUGHT ON 2026-08-18, RESTORED. A "
     "refusal row is CREATED at 'failed', which the rule denies — so the app "
     "never sees the refusal and falls through to its two-minute quiet timeout, "
     "telling the user the machine did not answer while it is online and refused",
     [('        _open_log_bundle_row(owner_uid, code, device_id, request_id)\n        _write_log_bundle_status(owner_uid, code,\n                                {"status": "failed", "errorClass": "ConsentMissing"})',
       '        _write_log_bundle_status(owner_uid, code,\n                                {"status": "failed", "errorClass": "ConsentMissing",\n                                 "deviceId": device_id, "requestId": request_id},\n                                create=True)')],
     [T_SEND]),
    ("R1c", "under", "the cooldown refusal is created at a verdict for the same "
     "reason, and is denied the same way",
     [('        _open_log_bundle_row(owner_uid, code, device_id, request_id)\n        _write_log_bundle_status(owner_uid, code,\n                                {"status": "failed", "errorClass": "CooldownActive"})',
       '        _write_log_bundle_status(owner_uid, code,\n                                {"status": "failed", "errorClass": "CooldownActive",\n                                 "deviceId": device_id, "requestId": request_id},\n                                create=True)')],
     [T_SEND]),
    ("R1d", "over", "the open is allowed to carry any status, so the one clause "
     "that makes a row mean \"the machine started\" stops holding",
     [('        {"status": "collecting", "deviceId": device_id, "requestId": request_id},',
       '        {"status": "done", "deviceId": device_id, "requestId": request_id},')],
     [T_SEND]),
    ("R2", "under", "the uploading step is never reported, so the app jumps from "
     "collecting to done and a slow upload looks like a hang",
     [('            _write_log_bundle_status(owner_uid, code, {\n                "status": "uploading",',
       '            _write_log_bundle_status(owner_uid, code, {\n                "unused": "uploading",')],
     [T_SEND]),
    ("R3", "under", "⛔ a failed upload writes no failure, so the row sits at "
     "uploading forever and absence reads as patience",
     [('                _write_log_bundle_status(owner_uid, code, {\n                    "status": "failed", "errorClass": "UploadFailed"})',
       '                pass')],
     [T_SEND]),
    ("R4", "under", "the row loses its expiry, so it outlives the 30-day promise "
     "the consent screen makes",
     [('        body.setdefault("expireAt",\n                        datetime.now(timezone.utc) + timedelta(days=BUNDLE_MAX_AGE_DAYS))',
       '        pass')],
     [T_SEND]),
    ("R5", "over", "a status-write failure aborts an upload that was working",
     [('    except Exception as exc:\n        log(f"[send-logs] status write failed ({type(exc).__name__}) — the upload "\n            f"continues; the row will look stale", "WARN")\n        return False',
       '    except Exception as exc:\n        raise')],
     [T_SEND]),
    ("R6", "under", "the request nonce is dropped, so the app cannot tell a "
     "stale row from the one it just asked for",
     [('        {"status": "collecting", "deviceId": device_id, "requestId": request_id},',
       '        {"status": "collecting", "deviceId": device_id},')],
     [T_SEND]),
    ("R7", "under", "an exception in the worker writes no failure at all",
     [('            _write_log_bundle_status(owner_uid, code, {\n                "status": "failed", "errorClass": type(exc).__name__})',
       '            pass')],
     [T_SEND]),

    # ══ the upload ══════════════════════════════════════════════════════
    ("U1", "under", "⛔⛔ the Content-Type header goes. requests sends none for a "
     "raw file body and the rule pins it, so our own honest upload 403s and the "
     "ladder retries a terminal error as transient",
     [('                        "Content-Type": BUNDLE_CONTENT_TYPE,\n', '')],
     [T_SEND]),
    ("U2", "under", "⛔ the local size pre-check goes, which is what made a "
     "cap-403 unreachable rather than merely unlikely",
     [('    if size > BUNDLE_UPLOAD_MAX_BYTES:', '    if False:')],
     [T_SEND]),
    ("U3", "under", "a missing token no longer stops the upload, so it goes out "
     "unauthenticated and 403s with a misleading reason",
     [('    if not id_token:\n        log("[send-logs] no usable ID token — the authenticated path is dead", "WARN")\n        return None',
       '    if not id_token:\n        id_token = ""')],
     [T_SEND]),
    ("U4", "under", "a non-200 is reported as success, so the app says done for "
     "a bundle that is not in the bucket",
     [('    if resp.status_code != 200:\n        log(f"[send-logs] upload failed: HTTP {resp.status_code} "',
       '    if False:\n        log(f"[send-logs] upload failed: HTTP {resp.status_code} "')],
     [T_SEND]),
    ("U5", "under", "the object path drifts from the shape the rules pin, so "
     "every upload 403s",
     [('    object_path = f"logs/{owner_uid}/{device_id}/{code}/bundle.zip"',
       '    object_path = f"logs/{owner_uid}/{code}/bundle.zip"')],
     [T_SEND]),
    ("U6", "under", "the upload ceiling drifts off the storage rule's own number, "
     "putting a cap-403 back in reach",
     [('BUNDLE_UPLOAD_MAX_BYTES = 64 * 1024 * 1024', 'BUNDLE_UPLOAD_MAX_BYTES = 512 * 1024 * 1024')],
     [T_SEND]),

    # ══ how many runs ═══════════════════════════════════════════════════
    ("N1", "over", "⛔⛔ an unreadable count on the LIMITED action falls back to the "
     "cap, so every malformed request resolves toward MORE collection than was "
     "agreed to — the one direction this must never fail in",
     [('    if isinstance(raw, bool) or not isinstance(raw, int):\n        return None',
       '    if isinstance(raw, bool) or not isinstance(raw, int):\n        return BUNDLE_MAX_RUNS')],
     [T_SEND]),
    ("N2", "under", "⭐ the bool check goes, and `runs: true` is honoured as \"1 "
     "run\" — a number nobody chose, because True IS an int in Python",
     [('    if isinstance(raw, bool) or not isinstance(raw, int):',
       '    if not isinstance(raw, int):')],
     [T_SEND]),
    ("N3", "under", "the floor goes, so 0 and negative counts reach the builder",
     [('    if raw < BUNDLE_MIN_RUNS:\n        return None', '    if False:\n        return None')],
     [T_SEND]),
    ("N4", "under", "the cap goes, so a hand-written command collects far past "
     "the bound the consent screen describes",
     [('    return min(int(raw), BUNDLE_MAX_RUNS)', '    return int(raw)')],
     [T_SEND]),
    ("N5", "under", "the FULL action stops meaning the cap, so a plain send "
     "collects nothing",
     [('    if not limited:\n        return BUNDLE_MAX_RUNS', '    if not limited:\n        return 1')],
     [T_SEND]),
    ("N6", "under", "⛔⛔ the bound never reaches the builder, so the slider is "
     "decorative and 30 runs leave against a record of 5",
     [('            summary = _build_log_bundle(dest, support_code=code, max_runs=runs)',
       '            summary = _build_log_bundle(dest, support_code=code)')],
     [T_SEND]),
    ("N7", "under", "⭐ the row reports the CALLER's number instead of the "
     "builder's, so a dropped max_runs= leaves the row reading like a bound that "
     "was honoured",
     [('                "runsApplied": int(summary["maxRunsApplied"]),\n            })',
       '                "runsApplied": int(runs),\n            })'),
      ('                    "runsApplied": int(summary["maxRunsApplied"]),\n                })',
       '                    "runsApplied": int(runs),\n                })')],
     [T_SEND]),
    ("N8", "under", "the builder stops reporting the bound it used at all",
     [('        "maxRunsApplied": int(max_runs),\n', '')],
     [T_SEND, "tests/test_log_bundle_0818.py"]),
    ("N9", "under", "an unreadable count builds a bundle anyway",
     [('    if runs is None:\n        log("[send-logs] refusing: the request named an unreadable number of runs",',
       '    if False:\n        log("[send-logs] refusing: the request named an unreadable number of runs",')],
     [T_SEND]),

    # ══ the consent copy's scope ════════════════════════════════════════
    ("Q1", "under", "⛔⛔ the copy stops saying the number governs ONE line, so "
     "moving it down reads as \"less of everything leaves\" — while the raw tails "
     "still ship the same topics, links and account email at full history",
     [('    lines.append(\n        f"⚠ only the first line above is what the {n}-run choice changes — "\n        f"everything else leaves in full whatever number you pick")',
       '    pass')],
     [T_SEND]),
    ("Q2", "under", "the first line drops the age bound, so \"30 runs\" reads as a "
     "promise of 30",
     [('        f"at most {n} run{\'\' if n == 1 else \'s\'} from this machine — and only "\n        f"{\'if it is\' if n == 1 else \'those\'} from the last "\n        f"{BUNDLE_MAX_AGE_DAYS} days",',
       '        f"the last {n} runs from this machine",')],
     [T_SEND]),
    ("Q3", "under", "the singular case reads \"1 runs\"",
     [("f\"at most {n} run{'' if n == 1 else 's'} from this machine — and only \"",
       'f"at most {n} runs from this machine — and only "')],
     [T_SEND]),

    # ══ the floor ═══════════════════════════════════════════════════════
    ("L1", "under", "⛔⛔ the local bundle is deleted, removing the floor the "
     "whole design rests on — the file a user attaches by hand when nothing on "
     "the network works",
     [('            # ⭐ The local copy stays. It is the floor the whole design rests on:',
       '            try:\n                dest.unlink()\n            except Exception:\n                pass\n            # ⭐ The local copy stays. It is the floor the whole design rests on:')],
     [T_SEND]),
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
