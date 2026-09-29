"""Mutation harness — the stale-restore lane's repair (2026-09-29 verify).

⛔⛔ WHAT THIS CODE DECIDES.
  C* — a job queued for an OLD run carries its own clock: the start listener's
       Resume and the supervised auto-resume at boot stamp `queued_at_ms` when
       they queue it, and the boot restore's age check takes it as one of the
       job's clocks. Without it a Resume pressed minutes ago on a run parked ten
       days back was dropped at the next boot as "waited 10 days".
  M* — on EVERY pickup, a 403 on the job's record is the answer when the device
       document positively does not list the job's account: a removed sharer's
       leftover start doc, or Resume, is not run at serve start, and the dequeue
       does not run a job whose account was removed while it waited. A member's
       403 (the fresh-document race) and a membership nobody could read are
       still taken.
  P* — a token with no deviceId claim is this computer's own pairing at fault,
       like a deviceId mismatch: the heal's structural line says re-pair,
       whoever's research the refused write was for.

The lane's first harness, `stale_restore_0928_mutants.py`, holds the rest of
the restore (the boot restore's refusal, the owner check, the age gate, the
heal's line for another account's research).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/stale_restore_repair_0928_mutants.py
  .venv/bin/python .mutants/stale_restore_repair_0928_mutants.py C1 M4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

# ⛔ THE OLDER PICKUP AND RESTORE PINS RUN TOO. This repair widened what every
# pickup does with a refused read, so a mutant that breaks an old guarantee — a
# blip is taken, a deleted research stands down, the dequeue re-asks a refused
# flip — must die here as well as on the new pins.
SUITES = {
    RESEARCH: (ROOT, "tests/test_stale_or_foreign_restore_0928.py "
                     "tests/test_deleted_research_never_runs_1010.py "
                     "tests/test_failed_read_keeps_the_run_1010.py "
                     "tests/test_restart_recovery_retries_1010.py "
                     "tests/test_flip_stage_0806.py "
                     "tests/test_supervised_auto_resume_enqueue.py "
                     "tests/test_grpc_synth_403_heal.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: a job queued for an old run carries its own clock ─────────────
AGE_CLOCK = "        seen.append(clock / 1000)"
RESUME_CLOCK = ("                            # ⛔ ITS OWN CLOCK: the run id and the folder are\n"
                "                            # as old as the run — see `_job_age_s`.\n"
                '                            "queued_at_ms": int(time.time() * 1000),\n')
AUTO_RESUME_CLOCK = ("                                    # ⛔ ITS OWN CLOCK: the run id and the folder\n"
                     "                                    # are as old as the run — see `_job_age_s`.\n"
                     '                                    "queued_at_ms": int(time.time() * 1000),\n')

# ── anchors: a refusal for an account that left, on every pickup ───────────
RULE = "        if _is_denied_read(err) and (denied_is_answer or _known_not_a_member(uid)):"
NOT_A_MEMBER = '    return members is not None and str(uid or "").strip() not in members'
DEQUEUE_ASKS = ('                    if _is_denied_read(_fe) and '
                '_known_not_a_member(job.get("uid")):')
DEQUEUE_ANSWER = ("                        should_run = False\n"
                  '                        _log_pickup_not_run("dequeue", job.get("research_id"),\n'
                  "                                            _RESTORE_NOT_OPENABLE)\n")

# ── anchors: a token with no claim is this computer's own pairing ──────────
OWN_PAIRING = "        own_pairing = not tok_did or bool(cfg_did and tok_did != cfg_did)"

MUTANTS = [
    # ═══ C — a job queued for an old run carries its own clock ═════════════
    ("C1", RESEARCH, "⛔⛔ THE 09-29 DEFECT: the age check ignores the job's own "
     "clock — a Resume pressed today on a ten-day-old run is dropped at boot",
     [(AGE_CLOCK, "        pass")]),
    ("C2", RESEARCH, "⛔ the clock is read as seconds, not milliseconds — every job "
     "that carries one is 'in the future' and never stale, however old",
     [(AGE_CLOCK, "        seen.append(clock)")]),
    ("C3", RESEARCH, "⛔⛔ the start listener's Resume stops stamping its clock — "
     "judged by its old run id and folder, it is dropped at the next boot",
     [(RESUME_CLOCK, "")]),
    ("C4", RESEARCH, "⛔ the supervised auto-resume stops stamping its clock — "
     "the run it queued is dropped as stale at the boot after",
     [(AUTO_RESUME_CLOCK, "")]),

    # ═══ M — a refusal for an account that left, on every pickup ═══════════
    ("M1", RESEARCH, "⛔⛔ THE 09-29 DEFECT: only the boot restore hears a refusal "
     "— a removed sharer's leftover start doc runs at serve start",
     [(RULE, "        if _is_denied_read(err) and denied_is_answer:")]),
    ("M2", RESEARCH, "⛔⛔ OVER-REACH: every 403 on a pickup is an answer — a "
     "current sharer's fresh research, or the owner's, is thrown away",
     [(RULE, "        if _is_denied_read(err):")]),
    ("M3", RESEARCH, "⛔ OVER-REACH: 'can't tell who shares this computer' reads as "
     "'not a member' — a device read that blips drops a sharer's job",
     [(NOT_A_MEMBER, '    return members is None or str(uid or "").strip() not in members')]),
    ("M4", RESEARCH, "⛔⛔ the dequeue runs a job whose account left while it "
     "waited, 'proceeding, as before'",
     [(DEQUEUE_ASKS, "                    if False:")]),
    ("M5", RESEARCH, "⛔ OVER-REACH: the dequeue refuses on every 403 — a member's "
     "run is not started when the flip and the read are both refused",
     [(DEQUEUE_ASKS, "                    if _is_denied_read(_fe):")]),
    ("M6", RESEARCH, "⛔ the dequeue says the job is not run, and runs it",
     [(DEQUEUE_ANSWER, '                        _log_pickup_not_run("dequeue", job.get("research_id"),\n'
                       "                                            _RESTORE_NOT_OPENABLE)\n")]),
    ("M7", RESEARCH, "the dequeue drops the job and never says why",
     [(DEQUEUE_ANSWER, "                        should_run = False\n")]),

    # ═══ P — a token with no claim is this computer's own pairing ══════════
    ("P1", RESEARCH, "⛔ a token with no deviceId claim blames the sharer's account "
     "instead of saying re-pair",
     [(OWN_PAIRING, "        own_pairing = bool(tok_did and cfg_did and tok_did != cfg_did)")]),
    ("P2", RESEARCH, "OVER-REACH: every refused write to another account's research "
     "says re-pair — the 09-28 line comes back",
     [(OWN_PAIRING, "        own_pairing = True")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-x",
             "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
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
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
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
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
