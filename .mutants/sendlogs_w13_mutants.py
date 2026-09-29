"""Mutation harness — wave 13, Send Logs receipts stop retrying forever.

⛔⛔ WHAT THIS CODE DECIDES.
  H* — a receipt write never spends the research writes' safety net: it gets
       the free same-token retry, never the re-mint, its cooldown or the latch.
  C* — a receipt write says how it went: landed, refused, could not reach the
       account, nothing to write with. A network failure on a retry is not a
       refusal. The live writer still says so when a receipt fails; the
       terminal, which has no client, parks without a warning.
  F* — the refusal writer parks only a receipt that could not reach the
       account, and its patch carries the row's scope.
  R* — the replay opens in the patch's scope, and a refused open goes on to the
       patch, so a row whose open had landed finishes.
  D* — the drain drops a refused receipt with one line, drops one older than
       the bundle's 30 days, keeps one that could not reach the account and
       backs off 30 s doubling to 30 min, and is machine-logged.
  W* — the watcher runs the drain off its loop, on worker 1 only.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant here dies on behaviour: the
real drain, refusal writer, command handler, `_grpc_write_with_heal`,
`_update_research_doc`, `cmd_send_logs` and reconnect watcher, against a fake
Firestore that ports the logBundles rules clause by clause.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/sendlogs_w13_mutants.py
  .venv/bin/python .mutants/sendlogs_w13_mutants.py D2 W1
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_send_logs_receipts_w13.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ H — the research writes' safety net ════════════════════════════════
    ("H1", RESEARCH, "⛔⛔ a refused receipt goes on to the re-mint — spends the "
     "cooldown, counts toward the latch, prints re-pair required",
     [("        if not heal:\n"
       "            raise  # the original denial — the free retry is all this write gets\n",
       "")]),
    ("H2", RESEARCH, "⛔⛔ the receipt writer asks for the full heal",
     [("                what=\"log_bundle_status\", heal=False)",
       "                what=\"log_bundle_status\")")]),
    ("H3", RESEARCH, "⛔ every other write loses the heal by default — a stale "
     "research write is never re-minted",
     [("                          heal: bool = True):",
       "                          heal: bool = False):")]),

    # ═══ C — how a receipt write went ═══════════════════════════════════════
    ("C1", RESEARCH, "⛔⛔ a network failure on the retry reads as a refusal — a "
     "receipt that could still land is dropped",
     [("        return (\"denied\" if _is_synth_permission_denied(exc, ignore=exc.__context__)",
       "        return (\"denied\" if _is_synth_permission_denied(exc)")]),
    ("C2", RESEARCH, "every failure reads as a refusal",
     [("        return (\"denied\" if _is_synth_permission_denied(exc, ignore=exc.__context__)\n"
       "                else \"failed\")",
       "        return \"denied\"")]),
    ("C3", RESEARCH, "no client reads as a failure — the terminal warns about a "
     "receipt it parked on purpose",
     [("    if not _firebase_db or not owner_uid or not code:\n        return \"offline\"",
       "    if not _firebase_db or not owner_uid or not code:\n        return \"failed\"")]),
    ("C4", RESEARCH, "the live writer is silent when the account cannot be reached",
     [("    if outcome in (\"denied\", \"failed\"):\n        why = (",
       "    if outcome == \"denied\":\n        why = (")]),
    ("C5", RESEARCH, "the live writer calls a write that never reached the account a success",
     [("    return outcome == \"ok\"\n\n\ndef _log_bundle_row_write(",
       "    return outcome != \"denied\"\n\n\ndef _log_bundle_row_write(")]),
    ("C6", RESEARCH, "a write that landed reports a failure",
     [("            _write(bare)\n        return \"ok\"\n",
       "            _write(bare)\n        return \"failed\"\n")]),

    # ═══ F — the refusal writer ═════════════════════════════════════════════
    ("F1", RESEARCH, "⛔⛔ the parked refusal forgets its scope — a sharer's replays "
     "as a whole-machine row and is refused forever",
     [("    patch = {\"status\": \"failed\", \"errorClass\": error_class,\n"
       "             \"machineIncluded\": bool(machine_included)}\n",
       "    patch = {\"status\": \"failed\", \"errorClass\": error_class}\n")]),
    ("F2", RESEARCH, "⛔⛔ a refused refusal row is parked — the removed sharer's "
     "press restarts the storm",
     [("    if outcome == \"denied\":\n        log(f\"[send-logs] the account refused the "
       "{error_class} receipt",
       "    if False:\n        log(f\"[send-logs] the account refused the {error_class} receipt")]),
    ("F3", RESEARCH, "⛔ a refusal that could not reach the account is dropped",
     [("        f\"sent once the account can be reached\", \"WARN\")\n"
       "    _queue_log_bundle_row(owner_uid, code, patch, device_id=device_id)\n",
       "        f\"sent once the account can be reached\", \"WARN\")\n")]),
    ("F4", RESEARCH, "the refusal's patch is never written after its open landed",
     [("    if outcome == \"ok\":\n        outcome = _log_bundle_row_write(owner_uid, code, patch)\n",
       "")]),

    # ═══ R — the replay of one row ══════════════════════════════════════════
    ("R1", RESEARCH, "⛔⛔ a refused open ends the replay — a row whose open had "
     "landed is refused forever and its patch never goes",
     [("    if opened not in (\"ok\", \"denied\"):", "    if opened != \"ok\":")]),
    ("R2", RESEARCH, "⛔ every replay opens as a whole-machine row — a sharer's is refused",
     [("                                patch.get(\"machineIncluded\") is not False),",
       "                                True),")]),
    ("R3", RESEARCH, "every replay opens as a sharer's row — the terminal's "
     "whole-machine bundle says it is not",
     [("                                patch.get(\"machineIncluded\") is not False),",
       "                                False),")]),
    ("R4", RESEARCH, "a replay that could not reach the account reports it landed",
     [("    if opened not in (\"ok\", \"denied\"):\n        return opened\n",
       "    if opened not in (\"ok\", \"denied\"):\n        return \"ok\"\n")]),

    # ═══ D — the drain ══════════════════════════════════════════════════════
    ("D1", RESEARCH, "⛔ the replay's lines land in whatever run is armed",
     [("@_machine_logged\ndef _drain_queued_log_bundle_rows() -> int:",
       "def _drain_queued_log_bundle_rows() -> int:")]),
    ("D2", RESEARCH, "a receipt exactly thirty days old still lands",
     [("        if now - _epoch_from_iso(row.get(\"at\")) >= BUNDLE_MAX_AGE_DAYS * 86400:",
       "        if now - _epoch_from_iso(row.get(\"at\")) > BUNDLE_MAX_AGE_DAYS * 86400:")]),
    ("D3", RESEARCH, "⛔⛔ no age bound — a month-old receipt lands as sent, naming "
     "a deleted bundle",
     [("        if now - _epoch_from_iso(row.get(\"at\")) >= BUNDLE_MAX_AGE_DAYS * 86400:",
       "        if False:")]),
    ("D4", RESEARCH, "⛔⛔ no backoff — a row that cannot reach the account is "
     "tried every five seconds",
     [("        if now < float(row.get(\"retryAt\") or 0):", "        if False:")]),
    ("D5", RESEARCH, "the wait ends one tick late",
     [("        if now < float(row.get(\"retryAt\") or 0):",
       "        if now <= float(row.get(\"retryAt\") or 0):")]),
    ("D6", RESEARCH, "⛔⛔ THE STORM: a refused row is kept and tried again",
     [("        elif outcome == \"denied\":\n            log(f\"[send-logs] the account refused a saved",
       "        elif False:\n            log(f\"[send-logs] the account refused a saved")]),
    ("D7", RESEARCH, "the wait never grows",
     [("            row[\"tries\"] = int(row.get(\"tries\") or 0) + 1",
       "            row[\"tries\"] = 1")]),
    ("D8", RESEARCH, "the first wait is a minute, not thirty seconds",
     [("_PARKED_ROW_RETRY_S * 2 ** (row[\"tries\"] - 1),",
       "_PARKED_ROW_RETRY_S * 2 ** row[\"tries\"],")]),
    ("D9", RESEARCH, "the first wait is one tick",
     [("_PARKED_ROW_RETRY_S = 30\n", "_PARKED_ROW_RETRY_S = 5\n")]),
    ("D10", RESEARCH, "a long outage waits two hours between tries",
     [("_PARKED_ROW_RETRY_CAP_S = 1800\n", "_PARKED_ROW_RETRY_CAP_S = 7200\n")]),
    ("D11", RESEARCH, "the wait is never written down, so it never holds",
     [("            still_owed.append(json.dumps(row))", "            still_owed.append(line)")]),
    ("D12", RESEARCH, "a line that is JSON but not a row stops the whole drain",
     [("            row = dict(json.loads(line))", "            row = json.loads(line)")]),
    ("D13", RESEARCH, "⛔ the line names the whole support code — the read "
     "capability for its bundle",
     [("        which = f\"{str(row.get('code') or '')[:4]}…\"",
       "        which = f\"{str(row.get('code') or '')}…\"")]),
    ("D14", RESEARCH, "the drain's clock stands still at zero",
     [("    now = time.time()\n    still_owed, landed = [], 0\n",
       "    now = 0.0\n    still_owed, landed = [], 0\n")]),

    # ═══ W — the watcher ════════════════════════════════════════════════════
    ("W1", RESEARCH, "every worker drains the same file again",
     [("                if WORKER_ID == 1:\n"
       "                    await asyncio.to_thread(_drain_queued_log_bundle_rows)",
       "                if True:\n"
       "                    await asyncio.to_thread(_drain_queued_log_bundle_rows)")]),
    ("W2", RESEARCH, "⛔⛔ the replay runs on the job worker's loop and freezes it",
     [("                    await asyncio.to_thread(_drain_queued_log_bundle_rows)",
       "                    _drain_queued_log_bundle_rows()")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider", "-rs"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    ok = (re.search(r"\b\d+ (failed|errors?)\b", out) is None
          and re.search(r"\b\d+ passed\b", out) is not None)
    return ok, out


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    # ⛔ UTF-8 OUT (Windows review, 2026-09-29): a redirected run on Windows has a
    # cp1252 stdout, and the first "✓ killed" raised UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # ⛔⛔ AN IN-FLIGHT MARKER (Windows review, 2026-09-29). Windows ends a process
    # with TerminateProcess — no SIGTERM handler, no `finally:` — so a killed run
    # left a mutant in research.py silently. Now it leaves this file naming the
    # file that holds one, and the next run refuses to start until it is restored.
    # Run harnesses in a throwaway worktree, never in the live checkout.
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, TESTS)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — a skipped test measures nothing, so "
              "no kill below would mean anything.\n" + out[-1500:])
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            ok, _out = green(ROOT, TESTS)
            if ok:
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)
            if _digest(path.read_bytes()) == DIGESTS[fname]:
                try:
                    _INFLIGHT.unlink()
                except FileNotFoundError:
                    pass

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
