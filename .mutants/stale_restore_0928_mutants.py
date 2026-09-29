"""Mutation harness — serve must not re-run a stale or foreign job on start
(2026-09-28, lane "stale restore").

⛔⛔ WHAT THIS CODE DECIDES.
  D* — a 403 on the job's research record is an ANSWER at boot: the pickup rule
       says "denied" (only for the boot restore), the funnel refuses a 403 when
       handed a `denied` list, the boot restore sheds such an entry, and the
       held entry's re-offer lets it go. A read that FAILED (timeout, UNAVAILABLE,
       5xx) is still taken.
  F* — a job whose owner (the entry's uid, or its run folder's owner.json) is
       neither this computer's account nor one of its sharers is dropped BEFORE
       any read; "cannot tell who shares it" is never "nobody".
  A* — a job older than `_STALE_RUN_S` (the startup sweep's 7 days) is not
       restored; its age is the NEWER of its run-id stamp and its folder's time.
  H* — the heal's structural line names another account instead of "re-pair
       required" when the refused write is to another account's research (a
       device-id mismatch still says re-pair), and every pinned research writer
       hands the heal its owner's uid.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/stale_restore_0928_mutants.py
  .venv/bin/python .mutants/stale_restore_0928_mutants.py D1 H4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

# ⛔ THE OLDER RESTORE PINS RUN TOO. This lane changed what the boot restore does
# with a failed read, so a mutant that breaks the old guarantees — a blip is
# taken, a held entry is re-offered, a deleted research is shed — must die here
# as well as on the new pins.
SUITES = {
    RESEARCH: (ROOT, "tests/test_stale_or_foreign_restore_0928.py "
                     "tests/test_deleted_research_never_runs_1010.py "
                     "tests/test_failed_read_keeps_the_run_1010.py "
                     "tests/test_restart_recovery_retries_1010.py "
                     "tests/test_pending_queue_keeps_nothing_109.py "
                     "tests/test_grpc_synth_403_heal.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: a 403 is an answer at boot ─────────────────────────────────────
RULE_DENIED = "        if denied_is_answer and _is_denied_read(err):"
RULE_DENIED_LINE = ("            _log_pickup_not_run(where, rid, _RESTORE_NOT_OPENABLE)\n"
                    '            return "denied", None')
DENIED_TEST = ('    return (type(err).__name__ == "PermissionDenied" or "403" in s\n'
               '            or "PERMISSION_DENIED" in s\n'
               '            or "Missing or insufficient permissions" in s)')
FUNNEL_DENIED = "                if denied is not None:"
RESTORE_ASKS = '                             "disk-restore", denied_is_answer=True)[0]:'
RESTORE_LIST = "                         hold_unreadable=_UNREAD_RESTORES, denied=denied):"
RESTORE_SHEDS = ("        elif denied:\n"
                 "            # The pickup rule's read answered and this one was refused: the\n"
                 "            # same answer, arrived a moment later. Shed, never kept.\n"
                 "            skipped += 1\n"
                 "            withdrew = True")
RETRY_LIST = "                         denied=[])"

# ── anchors: not one of this computer's accounts ────────────────────────────
OWNER_CHECK = "        if foreign:"
MEMBERS_SHARED = "    members.update(s for s in shared if isinstance(s, str) and s)"
OWNER_FILE = "                    owners.add(o)"
OWNER_FILE_ABOUT = ('                    and str(meta.get("researchId") or "") in\n'
                    '                    ("", str((job or {}).get("research_id") or ""))):')
NO_DEVICE_DOC = ('        snap = _firebase_db.collection("devices").document(device_id).get()\n'
                 "        if not snap.exists:\n"
                 "            return None")
DEVICE_BLIP = ('            f"({type(err).__name__}) — the record read decides instead", "DEBUG")\n'
               "        return None")

# ── anchors: too old ────────────────────────────────────────────────────────
AGE_GATE = "        if age is not None and age > _STALE_RUN_S:"
AGE_FOLDER = "            seen.append(d.stat().st_mtime)"
AGE_NEWEST = "    return (now - max(seen)) if seen else None"

# ── anchors: the heal's structural line ─────────────────────────────────────
ADVICE_GATE = "    if uid and owner and uid != owner and not mismatch:"
MISMATCH = "        mismatch = bool(tok_did and cfg_did and tok_did != cfg_did)"
LATCH_ADVICE = '                        f"{_structural_heal_advice(uid, before, mismatch=mismatch)} "'
SITE_EMIT = '            what="emit_event", uid=_fb_uid,'
SITE_UPDATE = '            what=f"update research {research_id[:8]}…", uid=uid,'
SITE_SET = '            what=f"set research {research_id[:8]}…", uid=uid,'
SITE_LINK = '            what=f"link {kind}", uid=_fb_uid,'
SITE_DOCUMENT = '            what=f"document {doc_type}", uid=_fb_uid)'
SITE_PHASE = ('        _grpc_write_with_heal(_op, what=f"phase-status phase={phase_num}", '
              'uid=_fb_uid)')
SITE_KICK = ('        _grpc_write_with_heal(_op, what=f"cloud-kick refusal rid={research_id[:8]}…",\n'
             "                              uid=uid)")

MUTANTS = [
    # ═══ D — a 403 is an answer at boot ════════════════════════════════════
    ("D1", RESEARCH, "⛔⛔ THE 09-28 DEFECT: the pickup rule takes a refused record "
     "again ('a read that fails is not a deletion') and says so in the log",
     [(RULE_DENIED, "        if False:")]),
    ("D2", RESEARCH, "⛔⛔ OVER-REACH: every failed read counts as a refusal — a "
     "boot that came up before the network drops the owner's real jobs",
     [(RULE_DENIED, "        if denied_is_answer:")]),
    ("D3", RESEARCH, "the refusal is dropped but never said — no line tells the "
     "owner why a queued job did not run",
     [(RULE_DENIED_LINE, '            return "denied", None')]),
    ("D4", RESEARCH, "⛔ the refusal test no longer recognises a 403 — the pickup "
     "takes it and the funnel holds it for a retry",
     [(DENIED_TEST, "    return False")]),
    ("D5", RESEARCH, "⛔ the funnel ignores the list it was handed and trusts the "
     "403 — the refusal on its own read is taken",
     [(FUNNEL_DENIED, "                if False:")]),
    ("D6", RESEARCH, "the boot restore stops asking the pickup rule for a refusal "
     "— the record read logs 'taking the job' before the funnel drops it",
     [(RESTORE_ASKS, '                             "disk-restore")[0]:')]),
    ("D7", RESEARCH, "⛔ the boot restore hands the funnel no list — a refusal on "
     "the funnel's read is trusted and run",
     [(RESTORE_LIST, "                         hold_unreadable=_UNREAD_RESTORES):")]),
    ("D8", RESEARCH, "⛔ a refusal on the funnel's read is KEPT in the snapshot — "
     "re-offered, and refused, at every boot for ever",
     [(RESTORE_SHEDS, "        elif False:\n"
                      "            skipped += 1\n"
                      "            withdrew = True")]),
    ("D9", RESEARCH, "⛔⛔ the held entry's re-offer trusts a 403 — a job held on a "
     "blip at boot runs later although the rules refuse it",
     [(RETRY_LIST, "                         )")]),

    # ═══ F — not one of this computer's accounts ═══════════════════════════
    ("F1", RESEARCH, "⛔⛔ the owner check is gone — a stranger's job whose record "
     "happens to read runs on this computer",
     [(OWNER_CHECK, "        if False:")]),
    ("F2", RESEARCH, "⛔⛔ OVER-REACH: sharers are not members — every job a sharer "
     "sent is dropped at the next boot",
     [(MEMBERS_SHARED, "    pass")]),
    ("F3", RESEARCH, "the run folder's owner.json is never read — an entry with no "
     "uid of its own stays in the snapshot for ever",
     [(OWNER_FILE, "                    pass")]),
    ("F6", RESEARCH, "⛔ OVER-REACH: an owner.json about ANOTHER research in a shared "
     "folder name drops a sharer's job it says nothing about",
     [(OWNER_FILE_ABOUT, "                    ):")]),
    ("F4", RESEARCH, "⛔ OVER-REACH: no device document reads as 'shared with "
     "nobody' — every sharer's job is dropped",
     [(NO_DEVICE_DOC, '        snap = _firebase_db.collection("devices").document(device_id).get()\n'
                      "        if not snap.exists:\n"
                      "            return set()")]),
    ("F5", RESEARCH, "⛔ OVER-REACH: a device read that blipped reads as 'shared "
     "with nobody' — every sharer's job is dropped on a network hiccup",
     [(DEVICE_BLIP, '            f"({type(err).__name__}) — the record read decides instead", "DEBUG")\n'
                    "        return set()")]),

    # ═══ A — too old ═══════════════════════════════════════════════════════
    ("A1", RESEARCH, "⛔⛔ the age gate is gone — an eight-day-old job runs",
     [(AGE_GATE, "        if False:")]),
    ("A2", RESEARCH, "the horizon is its own number, not the startup sweep's — the "
     "two can disagree about whether a run is still somebody's",
     [(AGE_GATE, "        if age is not None and age > 7 * 86400:")]),
    ("A3", RESEARCH, "⛔ the folder's time is ignored — a run resumed today from an "
     "old folder is dropped as stale",
     [(AGE_FOLDER, "            pass")]),
    ("A4", RESEARCH, "⛔ the OLDER clock wins — a run resumed today from an old "
     "folder is dropped as stale",
     [(AGE_NEWEST, "    return (now - min(seen)) if seen else None")]),

    # ═══ H — the heal's structural line ════════════════════════════════════
    ("H1", RESEARCH, "⛔⛔ the structural line says 're-pair required' for another "
     "account's research again",
     [(ADVICE_GATE, "    if False:")]),
    ("H2", RESEARCH, "⛔ a device-id mismatch on another account's write stops "
     "saying re-pair — the one case where re-pairing IS the fix",
     [(ADVICE_GATE, "    if uid and owner and uid != owner:")]),
    ("H3", RESEARCH, "the mismatch is never seen by the advice",
     [(MISMATCH, "        mismatch = False")]),
    ("H4", RESEARCH, "⛔ the latch line hard-codes 're-pair required' again",
     [(LATCH_ADVICE, '                        f"A force-refresh cannot fix this — re-pair required. "')]),
    ("H5", RESEARCH, "⛔⛔ the run's event writer — the one the 09-28 log latched on "
     "— stops handing the heal its owner",
     [(SITE_EMIT, '            what="emit_event",')]),
    ("H6", RESEARCH, "the research record update stops handing the heal its owner",
     [(SITE_UPDATE, '            what=f"update research {research_id[:8]}…",')]),
    ("H7", RESEARCH, "the research record set stops handing the heal its owner",
     [(SITE_SET, '            what=f"set research {research_id[:8]}…",')]),
    ("H8", RESEARCH, "the link writer stops handing the heal its owner",
     [(SITE_LINK, '            what=f"link {kind}",')]),
    ("H9", RESEARCH, "the document writer stops handing the heal its owner",
     [(SITE_DOCUMENT, '            what=f"document {doc_type}")')]),
    ("H10", RESEARCH, "the phase-status writer stops handing the heal its owner",
     [(SITE_PHASE, '        _grpc_write_with_heal(_op, what=f"phase-status phase={phase_num}")')]),
    ("H11", RESEARCH, "the cloud-kick refusal writer stops handing the heal its owner",
     [(SITE_KICK, '        _grpc_write_with_heal(_op, what=f"cloud-kick refusal rid={research_id[:8]}…")')]),
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
