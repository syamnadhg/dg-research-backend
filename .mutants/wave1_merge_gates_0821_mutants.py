"""Mutation harness for wave 1 (2026-08-21) — the merge-gating batch, backend.

⛔⛔ THE ITEM THAT TURNED OUT NOT TO BE THE ITEM. This wave was planned around
"a sharer is told their software is out of date". It is not reachable: the queue
rules keep send-logs out of the sharer allowlist, and the app hides the whole
control from anyone who does not own the machine. Three gates, not one.

⭐⭐ AND THE REACHABLE CASE WAS RIGHT NEXT TO IT. Worker 1 deletes the command
document before dispatch, so ANY silent refusal is the pair the app reads as
"took the request but its software is older than this setting".

⚠ AND I NAMED THE WRONG ONE TWICE. Not single-flight: `_work` stamps the cooldown
milliseconds into the build and the cooldown check runs first, so a human
pressing again is refused as CooldownActive, which always wrote a row. The
genuinely reachable silent refusal is the DEVICE-READ FAILURE — a Firestore
hiccup on the machine, with no row and, until now, no recoverable owner tree.
Single-flight is a two-tab race, plus a permanent path on any machine that cannot
write the stamp file (that write swallows its own failure).

⛔ THE OVER-CORRECTIONS ARE THE REAL RISK HERE, because "always write a row" is
one step from "write a row somewhere it does not belong":
  S6 — the refusal row goes into the SUBMITTER's tree. The rules pin it to the
       device owner's, so this is a write that is DENIED in production while the
       fake database in the tests accepts it happily. A green suite would be
       measuring nothing.
  S7 — the refused second press clears the FIRST press's in-flight claim.
  S8 — the row write moves back inside `_SEND_LOGS_LOCK`, serialising the fast
       path behind a network round-trip.
  A6 — the local run's missing submitter is filled in from the paired uid,
       asserting the machine's owner typed a command nobody can attribute.

⭐ AND THE COMMENT MUTANTS ARE NOT DECORATION. Three of this wave's four items
are comments that told a reader the opposite of what the code does — one of them
was quoted back to us in a review reply. A mutant that restores the false wording
must fail the suite, or "we fixed the comment" is unfalsifiable.

    .venv/bin/python .mutants/wave1_merge_gates_0821_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "research.py"
MOD = "models.py"
MUTATED_FILES = [SRC, MOD]

T_NEW = "tests/test_wave1_merge_gates_0821.py"
# ⛔ The sibling suites that own the same source. Reporting "a real suite gap"
# that is only this harness's scope has happened repeatedly here.
T_SEND = "tests/test_send_logs_command_0818.py"
T_CAP = "tests/test_run_log_capture_0818.py"
T_SILENT = "tests/test_update_never_silent.py"
T_TCC = "tests/test_macos_launchd_tcc_logs.py"
T_BLOCK = "tests/test_review_blockers_0813.py"
ALL = [T_NEW, T_SEND, T_CAP, T_SILENT, T_TCC, T_BLOCK]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

# ── anchors, each verified to occur exactly once ──────────────────────────
_UNIT_NOTE = """# The PATH below is this service's AND every child it spawns. Tool homes come
# first, so a binary in a user-writable dir such as ~/.local/bin resolves ahead
# of the OS copy for all of them. That is deliberate: system-first resolved
# tools the user never installed and broke app-driven updates. ExecStart above
# is an absolute interpreter path and cannot be shadowed either way."""

_HELPER_GUARD = """        log(f"[send-logs] refusing ({error_class}) with NO row — no owner tree "
            f"is known, so the app cannot be told why", "WARN")
        return"""

_HELPER_PARK = """    patch = {"status": "failed", "errorClass": error_class}
    if not (_open_log_bundle_row(owner_uid, code, device_id, request_id,
                                machine_included=machine_included)
            and _write_log_bundle_status(owner_uid, code, patch)):
        _queue_log_bundle_row(owner_uid, code, patch, device_id=device_id)"""

_READ_FAIL = """        _refuse_log_bundle_with_row(load_paired_uid() or "", code, device_id,
                                    request_id, "DeviceReadFailed")"""

_NO_SUB = """        _refuse_log_bundle_with_row(owner_uid, code, device_id, request_id,
                                    "SubmitterMissing")"""

_NOT_OWNER = """        _refuse_log_bundle_with_row(owner_uid, code, device_id, request_id,
                                    "NotDeviceOwner")"""

_BUILDING = """    if _already_building:"""

# ⛔ RE-ANCHORED 2026-08-24 (Wave 8 command path: the row tree is the SUBMITTER's
# on the scoped action, and every refusal now states whether it carries
# machine-level material). Meaning unchanged.
_BUILDING_CALL = """        _refuse_log_bundle_with_row(row_uid, code, device_id, request_id,
                                    "AlreadyBuilding",
                                    machine_included=machine_wanted)
        return"""

_LOCK = """    _already_building = False
    with _SEND_LOGS_LOCK:
        if _send_logs_inflight:
            _already_building = True
        else:
            _send_logs_inflight = True"""

_META_KEYS = """            "submitterUid": self.submitter_uid,
            "submitterSource": self.submitter_source,"""

_SINK_SET = """        self.submitted_by = (str(submitted_by).strip() or None) if submitted_by else None"""

_CAP_PASS = """                started_utc=started, submitted_by=self.submitted_by,
                claimed_by=self.claimed_by)"""

_CAP_STORE = """        self.submitted_by = submitted_by"""

_BIND = """                bound.arguments.get("uid") or None)"""

_WRAP = """    with _RunLogCapture(research_id=_rid, attempt=_attempt,
                        submitted_by=_submitter, claimed_by=_claimed):"""

_DOC_NOCALLER = """    ⚠ NO PRODUCTION CALLER — selection happens in the browser. This is the"""

_JS_NOTE = """                // ⛔ NO "FAMILY NAMED FIRST" EXEMPTION, and this comment used to"""

_QUEUE_NOTE = """            # ⛔ WHAT THE RULE PINS IS NOT WHAT WE JUST READ. The queue rule"""

MUTANTS: list[tuple[str, str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the send-logs refusals the app reads as "out of date" ═══════════
    ("S1", SRC, "under", "⭐⭐ THE ONE AN OWNER REACHES — the second press is "
     "refused with no row again, so the app tells someone their current machine "
     "is out of date while it builds their bundle",
     [(_BUILDING_CALL, "        return")],
     [T_NEW, T_SEND]),
    ("S2", SRC, "under", "the device-read failure goes silent again, which is "
     "the other reachable route to the same false accusation",
     [(_READ_FAIL, "        pass")],
     [T_NEW, T_SEND]),
    ("S3", SRC, "under", "the locally-stored paired uid is not consulted, so a "
     "device-read failure has no tree to answer in and stays silent",
     [('_refuse_log_bundle_with_row(load_paired_uid() or "", code, device_id',
       '_refuse_log_bundle_with_row("", code, device_id')],
     [T_NEW, T_SEND]),
    ("S4", SRC, "under", "the missing-submitter refusal stops writing a row",
     [(_NO_SUB, "        pass")],
     [T_NEW, T_SEND]),
    ("S5", SRC, "under", "the non-owner refusal stops writing a row, so a "
     "rules-lag write leaves no record on the machine's owner's account",
     [(_NOT_OWNER, "        pass")],
     [T_NEW, T_SEND]),
    ("S6", SRC, "over", "⛔⛔ THE REFUSAL ROW IS AIMED AT THE SUBMITTER'S TREE. "
     "The create rule pins it to the device owner's, so in production this write "
     "is DENIED and the refusal vanishes — while the fake db in the tests "
     "accepts it and everything looks green",
     [(_NOT_OWNER,
       """        _refuse_log_bundle_with_row(submitted_by, code, device_id, request_id,
                                    "NotDeviceOwner")""")],
     [T_NEW, T_SEND]),
    ("S7", SRC, "over", "the refused second press releases the FIRST press's "
     "in-flight claim, so a third press starts a concurrent build",
     [(_BUILDING, "    _send_logs_inflight = False\n    if _already_building:")],
     [T_NEW, T_SEND]),
    ("S8", SRC, "over", "the row write moves back under _SEND_LOGS_LOCK, holding "
     "the lock across a Firestore round-trip — a stall, not an error",
     [(_LOCK,
       """    _already_building = False
    with _SEND_LOGS_LOCK:
        if _send_logs_inflight:
            _already_building = True
            _refuse_log_bundle_with_row(owner_uid, code, device_id, request_id,
                                        "AlreadyBuilding")
        else:
            _send_logs_inflight = True""")],
     [T_NEW, T_SEND]),
    ("S9", SRC, "under", "⛔ the helper patches a row it never created. An update "
     "against a missing document is a silent no-op, so every refusal is "
     "invisible exactly as before — and nothing raises",
     [(_HELPER_PARK,
       """    patch = {"status": "failed", "errorClass": error_class}
    if not _write_log_bundle_status(owner_uid, code, patch):
        _queue_log_bundle_row(owner_uid, code, patch, device_id=device_id)""")],
     [T_NEW, T_SEND]),
    ("S11", SRC, "under", "⛔⛔ THE DEFECT THE ADVERSARIAL REVIEW FOUND, RESTORED. "
     "The refusal is DROPPED when the write fails — and on the DeviceReadFailed "
     "path the write goes through the very client whose read just raised, so it "
     "fails for the same reason. The fix's own headline case then delivers "
     "nothing and the app is back to guessing the software is out of date",
     [(_HELPER_PARK,
       """    patch = {"status": "failed", "errorClass": error_class}
    _open_log_bundle_row(owner_uid, code, device_id, request_id)
    _write_log_bundle_status(owner_uid, code, patch)""")],
     [T_NEW, T_SEND]),
    ("S12", SRC, "over", "every refusal is parked as well as written, so the "
     "reconnect drain replays create-then-patch against a row that is already "
     "failed — refused by the rule, and warning on every tick forever",
     [(_HELPER_PARK,
       """    patch = {"status": "failed", "errorClass": error_class}
    _open_log_bundle_row(owner_uid, code, device_id, request_id)
    _write_log_bundle_status(owner_uid, code, patch)
    _queue_log_bundle_row(owner_uid, code, patch, device_id=device_id)""")],
     [T_NEW, T_SEND]),
    # ⛔⛔ S10's FIRST FORM WAS AN EQUIVALENT MUTANT, and it survived by
    # construction rather than by finding a gap. Dropping the helper's
    # `if not owner_uid` changed NOTHING observable, because
    # `_write_log_bundle_status` rejects a falsy uid too — so the guard was
    # unobservable from outside, and a harness cannot tell a redundant guard
    # from a working one. The fix was in the SOURCE, not here: the guard now
    # names the one case where the machine refuses with nothing the app can
    # read, which is the only place that reason survives. This mutant removes
    # that line.
    ("S10", SRC, "under", "the one refusal the app can never see stops saying so "
     "even locally, so a support bundle shows a refusal that left no trace "
     "anywhere and the app's own guess is the only account of it",
     [(_HELPER_GUARD, "        return")],
     [T_NEW, T_SEND]),

    # ══ run attribution ════════════════════════════════════════════════
    ("A1", SRC, "under", "⛔⛔ THE SIGNATURE DEFECT OF THIS CODEBASE, restored: "
     "the parameter exists and nobody passes it, so every run records no "
     "submitter and the later per-run filter has nothing to filter on",
     [(_CAP_PASS, "                started_utc=started)")],
     [T_NEW, T_CAP]),
    ("A2", SRC, "under", "the capture drops the value on the way in, so the "
     "sink is handed None however the caller was invoked",
     [(_CAP_STORE, "        self.submitted_by = None")],
     [T_NEW, T_CAP]),
    ("A3", SRC, "under", "the wrapper stops binding `uid`, so a queued run is "
     "recorded as local",
     [(_BIND, "                None)")],
     [T_NEW, T_CAP]),
    ("A4", SRC, "under", "the wrapper never forwards the submitter it just bound",
     [(_WRAP, "    with _RunLogCapture(research_id=_rid, attempt=_attempt):")],
     [T_NEW, T_CAP]),
    ("A5", SRC, "over", "`submitterSource` is hardcoded, so a local run claims "
     "to have come from the queue and a null reads as a lost value rather than "
     "an absent one",
     [(_META_KEYS, '            "submitterUid": self.submitter_uid,\n'
                   '            "submitterSource": "queue",')],
     [T_NEW, T_CAP]),
    ("A6", SRC, "over", "⛔ a local run's missing submitter is filled in from the "
     "paired uid — asserting the machine's owner typed a command that nobody can "
     "actually attribute to anyone",
     [(_SINK_SET,
       "        self.submitted_by = ((str(submitted_by).strip() or None) "
       "if submitted_by else (load_paired_uid() or None))")],
     [T_NEW, T_CAP]),
    ("A7", SRC, "under", "⛔ THE TEMPTING WRONG IMPLEMENTATION: read the "
     "process-wide global instead of the argument. It is bound inside "
     "run_pipeline, AFTER this meta is written, so it holds the PREVIOUS run's "
     "submitter and a crash freezes that wrong value on disk",
     [(_CAP_STORE, '        self.submitted_by = _RUN_SUBMITTER.get("uid")')],
     [T_NEW, T_CAP]),
    # ⛔⛔ A8 RE-POINTED 2026-08-24 BECAUSE ITS MUTANT BECAME THE SHIPPED DESIGN.
    # It added `submitterUid` to the scan ROW, which was the defect when the row
    # fed index.json directly. Wave 8 needs it on the row — that is where the
    # server-side selection filter reads it — and moved the exclusion to the
    # index itself. The old edit is now a duplicate key in a dict literal:
    # behaviour unchanged, an equivalent mutant, a tripwire measuring nothing.
    #
    # ⭐ The PROPERTY it was written for is unchanged and still worth a mutant:
    # a uid must not travel inside a support archive. So it now attacks the
    # exclusion list rather than the row, and it is measured against a different
    # pair of suites than the Wave 8 harness's version of the same idea.
    ("A8", SRC, "over", "⛔⛔ the submitter uid leaks into the bundle's run index, "
     "so every support archive carries an account identifier for every run in "
     "it — disclosed under a consent screen that names no such thing",
     [('_INDEX_PRIVATE_KEYS = ("dir", "submitterUid", "submitterSource")',
       '_INDEX_PRIVATE_KEYS = ("dir",)')],
     [T_NEW, T_CAP]),

    # ══ the three comments that told a reader the opposite ══════════════
    ("C1", MOD, "under", "the docstring's caller claim comes back, and with it "
     "the answer we gave a reviewer from it",
     [(_DOC_NOCALLER,
       "    ⚠ Mirror of every JS ranker that calls it — the Claude one passes it.")],
     [T_NEW]),
    ("C2", SRC, "under", "the orphaned exemption comment returns above code that "
     "implements the opposite, with a worked example the code classifies the "
     "other way",
     [(_JS_NOTE,
       "                // the first mention of the family is describing a row, not")],
     [T_NEW]),
    ("C3", SRC, "under", "⛔⛔ the false rule claim returns: the comment says the "
     "queue rule validates the field the line above it reads, and it validates a "
     "different one",
     [(_QUEUE_NOTE,
       "            # uid validation is enforced server-side by the Firestore queue")],
     [T_NEW]),
    ("C4", SRC, "under", "the correction keeps the false half and drops the TRUE "
     "half — membership really is enforced, and saying otherwise is the same "
     "error pointing the other way",
     [("            # enforced (`deviceWritingTo` checks the device doc's ownerUid /",
       "            # NOT enforced at all (nothing checks the device doc's ownerUid /")],
     [T_NEW]),

    # ══ the systemd unit note ══════════════════════════════════════════
    ("U1", SRC, "under", "the generated unit loses its only comment, so the "
     "administrator reading it sees a user-writable directory ahead of /usr/bin "
     "with nothing saying why",
     [(_UNIT_NOTE, "# DG Super Research")],
     [T_NEW, T_SILENT, T_TCC]),
    ("U2", SRC, "under", "the note drops the consequence and keeps only the "
     "restatement, which is the shape of a comment that answers nothing",
     [(_UNIT_NOTE, "# The PATH below is derived rather than hardcoded.")],
     [T_NEW]),
    ("U3", SRC, "over", "⛔ a brace enters the unit f-string. It is evaluated "
     "BEFORE the try that would catch it, on the --resurrect path, so this is a "
     "hard crash rather than a bad unit file",
     [("# first, so a binary in a user-writable dir such as ~/.local/bin resolves ahead",
       "# first, so a binary in a user-writable dir {such as ~/.local/bin} resolves ahead")],
     [T_NEW]),
    ("U4", SRC, "over", "⛔ the word the macOS relocation pin greps this "
     "function's raw source for is reintroduced by a comment",
     [("# is an absolute interpreter path and cannot be shadowed either way.",
       "# is an absolute interpreter path (never under Library) and cannot be shadowed.")],
     [T_NEW, T_TCC]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    """(passed, timed_out). `-B` because stale bytecode has faked whole rounds
    of measurement in this repo before."""
    try:
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=_TEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, True
    return rc.returncode == 0, False


def snapshot():
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before):
    return [f for f, t in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != t]


def main() -> int:
    before = snapshot()
    print("baseline… ", end="", flush=True)
    ok, t_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if t_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors, stale = [], []
    for mid, path, direction, why, edits, tests in MUTANTS:
        target = ROOT / path
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs 1): {frm[:60]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, t_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed)" if t_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif t_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
