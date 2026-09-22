"""Wave 10.9 — a refused keychain write keeps the saved key, and says what is true.

⛔⛔ WHAT THE WAVE CLOSED (auth/keystore.py, items M13 / M15 / M16). The
2026-09-20 repair cured the common case — an item another binary owns is deleted
and rewritten — and on the paths where that cure does not work it still:

  M13 — asked a probe that answered "nothing there" when the keychain could not
        even be READ (a locked keychain, -25308), so the log called the keyring
        silent and the file authoritative while the old entry sat in it;
  M15 — ran the only destructive op on an error path (the pre-rewrite delete)
        with no audit record, no log line, and BEFORE the new token was
        persisted anywhere;
  M16 — let `get()` ask the keyring first, so the fresh token in the file was
        unreachable whenever the old keychain entry survived.

⭐ AND WHAT THE CROSS-VERIFY THEN FOUND IN M15 (2026-09-21). A LOCKED keychain
refuses the delete as surely as the write, so the record written before it
described nothing that happened — three per refresh, one worker, 71 records and
79 KB in a day, in a log nothing rotates, burying the `clear_all` wipes it
exists to attribute. The delete is no longer attempted there, and what is not
attempted is not recorded; K31-K37 are the ways that could rot.

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The quiet ones:

  K3  — the probe keeps its three answers and the CONSUMER ignores the third.
        The helper's own tests stay green; only a test of `set()` can see it.
  K7  — the stamp check becomes `if False and refused:`. Every name stays.
  K8  — the stamp stops mattering and ANY file copy outranks the keyring: the
        over-correction that re-routes every legacy file copy to the front.
  K12 — the file write moves back BELOW the delete. Still present, still
        greppable; the credential is in neither store while the rewrite runs.
  K13 — a failing file write is swallowed so the delete runs anyway: the one
        shape that destroys the last copy of anything.
  K15 — the audit moves below the delete, which is what "written BEFORE the
        deletion" exists to forbid: a process killed mid-delete leaves no line.
  K26 — the stamp check reads through `_file_load`, which retries an unreadable
        file for ~1.4s — on every `get` of a machine whose keyring works.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutant is compiled before it is written, so an unparseable one is a fault too —
never a kill banked on an import error.

  .venv/bin/python .mutants/wave109_keystore_mutants.py
  .venv/bin/python .mutants/wave109_keystore_mutants.py K3 K12
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_keystore_write_truth_109.py "
          "tests/test_keyring_write_shadow_0920.py "
          "tests/test_track_d_keystore.py")
TARGET = "auth/keystore.py"
FILES = (TARGET,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: M13, the probe and the sentence it chooses ─────────────────────
#: The probe's third answer.
P_UNKNOWN = '    except Exception:\n        return "unknown"'
#: The consumer's third branch.
C_UNKNOWN = '            elif answer == "unknown":'
#: The level of that branch, anchored on its own comment (two `log.error(`).
L_UNKNOWN = ('                # old entry. Say only what is known.\n'
             '                log.error(')
#: The first branch, which must not swallow the unknown case.
C_VALUE = '            if answer == "value":'
#: The clean fallback's sentence.
S_EMPTY = ('                    "keyring write of slot=%s failed (%s); it holds nothing "\n'
           '                    "readable for that slot, so the new token is kept in the "\n'
           '                    "file store and read from there", slot, _oserror_hint(e))')

# ── anchors: M16, the stamp and the read order ──────────────────────────────
#: `get` consulting the stamp before the keyring.
G_CHECK = ('    refused = _refused_write_copy(_file_peek(), acct)\n'
           '    if refused:\n'
           '        return refused\n')
G_IF = '    if refused:\n        return refused'
G_PEEK = '    refused = _refused_write_copy(_file_peek(), acct)'
#: The decision: a copy outranks the keyring only when stamped.
D_RULE = '    return blob.get(acct) if blob.get(acct + _FALLBACK_STAMP) else None'
#: The stamp written beside a refused write's copy.
W_STAMP = '            blob[acct + _FALLBACK_STAMP] = datetime.now(timezone.utc).isoformat()\n'
#: The whole durable-first block.
W_BLOCK = ('            blob = _file_load()\n'
           '            blob[acct] = value\n'
           '            blob[acct + _FALLBACK_STAMP] = datetime.now(timezone.utc).isoformat()\n'
           '            _file_save(blob)\n')
W_SAVE = '            _file_save(blob)\n            # Audited, and skipped when'
#: The quiet reader's catch.
Q_CATCH = '    except (OSError, ValueError):\n        return None'
#: The purge dropping the stamp, and noticing a lone one.
U_POP = '            blob.pop(stamp, None)\n'
U_COND = '        if acct in blob or stamp in blob:'
U_WARN = ('        log.warning(\n'
          '            "keyring write of slot=%s succeeded but its file copy could not be "\n'
          '            "removed (%s); reads may return that OLDER copy until a later write "\n'
          '            "clears it", acct.partition(":")[0], e)')
#: `delete()` taking the stamp with the copy.
X_POP = '    blob.pop(_keyring_account(slot, install_id) + _FALLBACK_STAMP, None)\n'

# ── anchors: M15, the audited delete ────────────────────────────────────────
#: ⭐ 2026-09-21: the audit and the delete moved into `_delete_before_rewrite`
#: (the repair below), so these anchors sit at ITS indentation, not `set`'s.
#: Same lines, same defects, one scope in.
A_CALL = ('    _write_wipe_audit(install_id, _oserror_hint(refusal),\n'
          '                      event="keyring-delete-before-rewrite", slot=slot)\n')
A_EVENT = '                      event="keyring-delete-before-rewrite", slot=slot)'
A_REC_EVENT = '            "event": event,  # clear_all | keyring-delete-before-rewrite'
A_REC_SLOT = '            "slot": slot,  # None = every slot'
#: The end of the delete's try/except — where a moved line would land.
DEL_END = ('        log.warning("keyring slot=%s: could not delete the old entry "\n'
           '                    "before rewriting (%s)", slot, _oserror_hint(de))\n'
           '        return "failed"\n')
DEL_LOG = ('        log.warning("keyring slot=%s: could not delete the old entry "\n'
           '                    "before rewriting (%s)", slot, _oserror_hint(de))')
#: `set`'s one call to it — where the file write would land if it moved back.
FATE_CALL = '            fate = _delete_before_rewrite(kr, acct, slot, install_id, e)\n'
#: The hot path.
HOT = ('            kr.set_password(SERVICE, acct, value)  # type: ignore[attr-defined]\n'
       '            # Keyring is the live store')

# ── anchors: the locked keychain that is not audited (2026-09-21) ───────────
#: The decision, and the early return it guards.
LOCK_TEST = '    return str(_INTERACTION_NOT_ALLOWED) in str(e)'
LOCK_SKIP = ('    if _refusal_forbids_deleting(refusal):\n'
             '        return "skipped"\n')
#: What the closing ERROR says became of an entry it did not remove.
BECAME = ('                became = {"failed": "that could not be removed",\n'
          '                          "skipped": "that the locked keychain would not let "\n'
          '                                     "us remove",\n'
          '                          "deleted": "that is there again after being removed",\n'
          '                          }[fate]\n')
#: The INFO line that must not claim a cure that never ran.
CURED = '                if fate == "deleted":'

MUTANTS = [
    # ── M13: the probe, and what the log says about a keychain it cannot read ─
    ("K1", "under", TARGET,
     "⛔⛔ THE DEFECT ITSELF — a read that raises is 'nothing there' again, so a "
     "locked keychain holding the old token is called silent, and the file "
     "store 'authoritative', in a WARNING nobody reads twice",
     [(P_UNKNOWN, '    except Exception:\n        return "empty"')]),

    ("K2", "over", TARGET,
     "⛔ the other collapse — a read that raises is taken as a live stale entry, "
     "so the log asserts an old token IS readable when nobody could look. A "
     "claim nobody can check is the same lie pointed the other way",
     [(P_UNKNOWN, '    except Exception:\n        return "value"')]),

    ("K3", "under", TARGET,
     "⛔⛔ THE PROBE KEEPS ITS THREE ANSWERS AND THE CONSUMER DROPS ONE. The "
     "helper's unit tests stay green; the unknown case falls into the else and "
     "says the keychain holds nothing — M13 restored one line away from its fix",
     [(C_UNKNOWN, '            elif False:')]),

    ("K4", "under", TARGET,
     "⛔ the unreadable-keychain case drops to a WARNING. It may be the one "
     "genuinely bad state, and a warning is what hid that state last time",
     [(L_UNKNOWN, '                # old entry. Say only what is known.\n'
                  '                log.warning(')]),

    ("K5", "over", TARGET,
     "⛔ unknown shares the value branch's sentence, so an unreadable keychain "
     "is reported as one that verifiably still holds the old entry",
     [(C_VALUE, '            if answer in ("value", "unknown"):')]),

    ("K29", "under", TARGET,
     "⛔ the clean fallback's old sentence comes back — 'the file store is "
     "authoritative' — the words M16 was filed against",
     [(S_EMPTY, '                    "keyring write of slot=%s failed (%s); the keyring is now "\n'
                '                    "silent for it, so the file store is authoritative",\n'
                '                    slot, _oserror_hint(e))')]),

    # ── M16: the copy the keyring refused is the one a reader gets ──────────
    ("K6", "under", TARGET,
     "⛔⛔⛔ THE 2026-09-20 DEFECT, RESTORED ON THE PATHS ITS FIRST FIX MISSED — "
     "`get` asks the keyring first again, and the keychain answers with the "
     "token the rotation replaced. On `current` that is every refresh "
     "presenting a dead token until the machine is paired again",
     [(G_CHECK, "")]),

    ("K7", "under", TARGET,
     "⛔⛔ the stamp check becomes one term of a compound condition — every "
     "name, line and call stays, and the stale keychain value wins every read",
     [(G_IF, '    if False and refused:\n        return refused')]),

    ("K8", "over", TARGET,
     "⛔⛔ THE OVER-CORRECTION — the stamp stops mattering and ANY file copy "
     "outranks the keyring. Every legacy file shadow (the RC-24 kind, older than "
     "the stamp and saying nothing about which store is newer) is re-routed to "
     "the front of every read",
     [(D_RULE, '    return blob.get(acct)')]),

    ("K9", "over", TARGET,
     "⛔ any slot's stamp promotes every slot's copy, so a refused `pending` "
     "write re-routes reads of `current` to whatever old copy the file holds",
     [(D_RULE, '    return blob.get(acct) if any(str(k).endswith(_FALLBACK_STAMP) '
               'for k in blob) else None')]),

    ("K10", "under", TARGET,
     "⛔ an empty stamped copy wins the read — `get` returns '' instead of the "
     "token the keyring holds. `get` has always meant `if val:`",
     [(G_IF, '    if refused is not None:\n        return refused')]),

    ("K11", "under", TARGET,
     "⛔⛔ the refused write is no longer stamped, so the file copy is "
     "indistinguishable from a legacy shadow and the keyring wins again — the "
     "read-side fix left with nothing to read",
     [(W_STAMP, "")]),

    ("K26", "under", TARGET,
     "⛔ the stamp check reads through `_file_load`, which retries an unreadable "
     "auth.json for ~1.4s and warns — on EVERY `get` of a machine whose keyring "
     "works, the moment auth.json belongs to someone else",
     [(G_PEEK, '    refused = _refused_write_copy(_file_load(), acct)')]),

    ("K30", "under", TARGET,
     "⛔ the quiet reader stops catching bad JSON, so a corrupt auth.json makes "
     "`get` raise before the keyring is even asked",
     [(Q_CATCH, '    except OSError:\n        return None')]),

    ("K22", "under", TARGET,
     "⛔ a good write drops the copy and leaves the stamp — harmless until the "
     "next refused write lands beside it, and a file nobody can reason about",
     [(U_POP, "")]),

    ("K23", "under", TARGET,
     "a good write ignores a stamp left on its own (an older binary's purge "
     "pops only the key it knew), so the orphan lives for ever",
     [(U_COND, '        if acct in blob:')]),

    ("K24", "under", TARGET,
     "⛔⛔ a failed purge is silent again. A stamped copy OUTRANKS the keyring, "
     "so this is the one failure that makes a newer keychain value lose — and "
     "it would leave no trace at all",
     [(U_WARN, '        pass')]),

    ("K25", "under", TARGET,
     "⛔ `delete()` leaves the stamp behind, so a deleted slot keeps half of a "
     "claim to outrank the keyring",
     [(X_POP, "")]),

    # ── M15: the audited delete, and the order that keeps the saved key ─────
    ("K12", "under", TARGET,
     "⛔⛔⛔ THE FILE WRITE MOVES BACK BELOW THE DELETE. Still present, still "
     "stamped, still greppable — and while the rewrite runs the credential is "
     "in neither store; if the file then refuses too, it is nowhere",
     [(W_BLOCK, ""),
      (FATE_CALL, FATE_CALL + W_BLOCK)]),

    ("K13", "under", TARGET,
     "⛔⛔ THE SHAPE THAT DESTROYS THE LAST COPY — a failing file write is "
     "swallowed, so the keychain entry is deleted although the new token "
     "reached no store at all",
     [(W_SAVE, '            with contextlib.suppress(Exception):\n'
               '                _file_save(blob)\n'
               '            # Audited, and skipped when')]),

    ("K14", "under", TARGET,
     "⛔⛔ the delete is unaudited again — the only destructive op on an error "
     "path, the one a forensic needs, and the header says every one is recorded",
     [(A_CALL, "")]),

    ("K15", "under", TARGET,
     "⛔⛔ the audit moves BELOW the delete. Still written, still greppable, and "
     "a process killed mid-delete leaves no line — the exact case 'written "
     "BEFORE the deletion' exists for",
     [(A_CALL, ""),
      (DEL_END, DEL_END + A_CALL)]),

    ("K16", "under", TARGET,
     "⛔ the call forgets its event, so the record says `clear_all` — a wipe of "
     "every slot — for a one-slot delete on a refused write",
     [(A_EVENT, '                              slot=slot)')]),

    ("K17", "under", TARGET,
     "⛔ the writer hardcodes `clear_all` again and ignores the event it is "
     "handed — K16's harm from the other end",
     [(A_REC_EVENT, '            "event": "clear_all",')]),

    ("K18", "under", TARGET,
     "the writer drops the slot, so the record cannot say WHICH credential went",
     [(A_REC_SLOT, '            "slot": None,')]),

    ("K19", "under", TARGET,
     "the call stops passing its slot — K18's harm from the caller's end",
     [(A_EVENT, '                              event="keyring-delete-before-rewrite")')]),

    ("K20", "over", TARGET,
     "⛔ the audit spreads onto the HOT path, one line per good rotation in a "
     "log nothing rotates — burying the two records that matter under noise",
     [(HOT, '            _write_wipe_audit(install_id, "hot", '
            'event="keyring-delete-before-rewrite", slot=slot)\n' + HOT)]),

    ("K21", "under", TARGET,
     "⛔ the delete's outcome is swallowed again — `contextlib.suppress` in all "
     "but name",
     [(DEL_LOG, '        pass')]),

    # ── the locked keychain that is not audited (cross-verify, 2026-09-21) ───
    ("K31", "over", TARGET,
     "⛔⛔ THE DEFECT ITSELF — a LOCKED keychain is asked to delete anyway and "
     "the record is written first. Every refresh is three writes, so three "
     "stack traces per refresh (measured: 24 refreshes, 71 records, 79 KB) in "
     "a log nothing rotates, for deletes that destroyed nothing",
     [(LOCK_SKIP, "")]),

    ("K32", "under", TARGET,
     "⛔⛔ the skip swallows the FOREIGN-ITEM case as well, so the one delete "
     "that cures anything never runs and the one destructive op on an error "
     "path is never recorded",
     [(LOCK_TEST, '    return True')]),

    ("K33", "under", TARGET,
     "⛔ the test names the wrong OSStatus — -25244 deletes cleanly and needs "
     "to, a locked keychain does not and is recorded anyway. Both halves "
     "wrong, and the constant still reads like a deliberate choice",
     [('_INTERACTION_NOT_ALLOWED: Final[int] = -25308',
       '_INTERACTION_NOT_ALLOWED: Final[int] = -25244')]),

    ("K34", "over", TARGET,
     "⛔ the record is skipped but the delete is still attempted — the audit "
     "stops describing what the code does, which is the whole point of it",
     [(LOCK_SKIP, ""),
      (A_CALL, '    if not _refusal_forbids_deleting(refusal):\n    ' + A_CALL)]),

    ("K35", "under", TARGET,
     "the skipped delete is reported as one that was refused, so the ERROR "
     "tells the owner the keychain would not let go of an entry nobody asked "
     "it about",
     [('            fate = _delete_before_rewrite(kr, acct, slot, install_id, e)',
       '            fate = _delete_before_rewrite(kr, acct, slot, install_id, e)\n'
       '            fate = "failed" if fate == "skipped" else fate')]),

    ("K37", "under", TARGET,
     "the ERROR goes back to one fixed sentence, so an entry no delete was "
     "ever attempted on is reported as one that 'could not be removed'",
     [(BECAME, '                became = "that could not be removed"\n')]),

    ("K36", "under", TARGET,
     "a write that succeeded on the second attempt claims the old item was "
     "deleted and re-created under this binary — naming a cure that never ran "
     "as the reason it worked",
     [(CURED, '                if True:')]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    # ⭐ sys.executable, not `.venv/bin/python`: a worktree has no .venv of its
    # own, and a relative interpreter there fails to start — which reads as red,
    # i.e. as a KILL, for every mutant.
    r = _run(f'"{sys.executable}" -B -m pytest {SUITES} -q -p no:cacheprovider')
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. An errored test is red.
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY — the static anchor sweep loads
# every harness in this directory with `exec_module`, which EXECUTES it.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}


    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")


    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, fname, why, edits in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg})") from None
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed")
    if faults:
        print("harness faults (measured nothing, counted out): " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
