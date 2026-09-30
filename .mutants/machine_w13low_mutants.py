"""Mutation harness — Wave 13's small machine items, finished before the publish.

⛔⛔ WHAT THIS CODE DECIDES.
  R* — a refused "Move to queue" tells the app why: the worker writes
       `requeueRefusal: {runId, workerId, reason, at}` to its own device
       document, in an update of its own, with one of six fixed reasons; a move
       that works clears it; a second press while the worker is leaving is not
       a refusal. Driven through the real device-command listener.
  T* — the chat assistant's runs (`agent-` + 16 hex) keep their research id in
       telemetry, and nothing near that shape is admitted. Driven through the
       real run-log capture and the per-event tap into a real spool.
  H* — a Send Logs receipt refused only because the cached token lacks its
       deviceId claim gets ONE re-mint and one retry; a token carrying the claim
       gets none; the research writes' cooldown, count and latch are untouched.
       Driven through `_open_log_bundle_row` against the rules-shaped fake.
  G* — gRPC's fork support is off before gRPC loads, so no forked child runs
       gRPC code before its exec (the owner's ConsumeWakeup aborts). Driven by
       a real gRPC server + stream and 200 real forks in a child Python.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant must die on behaviour.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⭐ EACH MUTANT NAMES ITS OWN TEST FILE (last column), so a run costs minutes.

  .venv/bin/python .mutants/machine_w13low_mutants.py
  .venv/bin/python .mutants/machine_w13low_mutants.py R1 H3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
TELEMETRY = "telemetry.py"

REQUEUE_T = ["tests/test_requeue_w13.py"]
TELEM_T = ["tests/test_incognito_run_id_and_logs_109.py"]
RECEIPT_T = ["tests/test_send_logs_receipts_w13.py"]
FORK_T = ["tests/test_grpc_fork_support_w13.py"]
TESTS = REQUEUE_T + TELEM_T + RECEIPT_T + FORK_T
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ R — a refused move says why ═══════════════════════════════════════
    ("R1", RESEARCH, "⛔ a refused move tells the app nothing — the worker stays off "
     "with no reason on screen",
     [("    if reason:\n        _note_requeue_refusal(",
       "    if False:\n        _note_requeue_refusal(")], REQUEUE_T),
    ("R2", RESEARCH, "an incognito run's refusal goes out under the handler's own word, "
     "not the code the app knows",
     [("    \"keeps-nothing\": \"private-run\",",
       "    \"keeps-nothing\": \"keeps-nothing\",")], REQUEUE_T),
    ("R3", RESEARCH, "a move that works leaves an earlier refusal on screen",
     [("    _note_requeue_refusal(rid, None)   # a refusal shown earlier no longer holds\n",
       "")], REQUEUE_T),
    ("R4", RESEARCH, "the refusal names the wrong worker",
     [("\"runId\": rid, \"workerId\": int(WORKER_ID), \"reason\": reason,",
       "\"runId\": rid, \"workerId\": 1, \"reason\": reason,")], REQUEUE_T),
    ("R5", RESEARCH, "a second press while the worker is leaving is shown as a refusal",
     [("    \"not-owner\": \"not-owner\",\n",
       "    \"not-owner\": \"not-owner\",\n    \"exiting\": \"not-running-here\",\n")],
     REQUEUE_T),
    ("R6", RESEARCH, "`at` in seconds, not the milliseconds the contract says",
     [("            \"at\": int(time.time() * 1000)})",
       "            \"at\": int(time.time())})")], REQUEUE_T),

    # ═══ T — the chat assistant's runs in telemetry ════════════════════════
    ("T1", TELEMETRY, "⛔ the assistant's run ids are refused again — every event warns "
     "and names no run",
     [("RESEARCH_ID_RE = re.compile(r\"^(?:chat_[0-9]{13}_[0-9]{1,6}|agent-[0-9a-f]{16})$\")",
       "RESEARCH_ID_RE = re.compile(r\"^chat_[0-9]{13}_[0-9]{1,6}$\")")], TELEM_T),
    ("T2", TELEMETRY, "⛔ the guard admits more than the minted shape — any 16-17 "
     "letters after agent- reach the wire",
     [("|agent-[0-9a-f]{16})$\")",
       "|agent-[0-9a-z]{16,17})$\")")], TELEM_T),

    # ═══ H — one re-mint for a receipt on a stale token ════════════════════
    ("H1", RESEARCH, "⛔ a receipt refused only for a stale token is dropped for good",
     [("            if creds is None or _grpc_token_claims().get(\"deviceId\"):\n",
       "            if True:\n")], RECEIPT_T),
    ("H2", RESEARCH, "⛔⛔ every refused receipt re-mints — the storm spends securetoken "
     "again",
     [("            if creds is None or _grpc_token_claims().get(\"deviceId\"):\n",
       "            if creds is None:\n")], RECEIPT_T),
    ("H3", RESEARCH, "⛔ the receipt's re-mint stamps the research writes' cooldown — "
     "a research write ten seconds later gets none",
     [("                creds.refresh(None)\n                reminted = True\n",
       "                creds.refresh(None)\n                reminted = True\n"
       "                _grpc_heal_last_ts = time.time()\n")], RECEIPT_T),
    ("H4", RESEARCH, "the receipt is re-minted but never retried",
     [("f\"once and retrying\", \"INFO\")\n            return op()\n",
       "f\"once and retrying\", \"INFO\")\n            raise\n")], RECEIPT_T),

    # ═══ G — gRPC's fork support is off ════════════════════════════════════
    ("G1", RESEARCH, "⛔ fork support left on — forked children run gRPC's poller "
     "before their exec and can abort",
     [("os.environ.setdefault(\"GRPC_ENABLE_FORK_SUPPORT\", \"0\")",
       "os.environ.setdefault(\"GRPC_ENABLE_FORK_SUPPORT_UNUSED\", \"0\")")], FORK_T),
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
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    selected = [m for m in MUTANTS if not only or m[0] in only]
    base_tests = sorted({t for m in selected for t in m[4]})
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, base_tests)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — a skipped test measures nothing here.\n"
              + out[-1500:])
        sys.exit(2)
    print("green\n")

    survivors = []
    for mid, fname, why, edits, tests in selected:
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
            ok, _out = green(ROOT, tests)
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
