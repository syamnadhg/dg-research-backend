"""Mutation harness — Round 2 (09-30), the owner's note on "Move to queue"
(the research computer's side). One mutant per fix.

  N* — the move writes the command's `note` on the run's research record as
       `moveNote`, next to `movedToQueueAt`: one line, at most 280 characters,
       only a string; a move without one CLEARS an old one.
  G* — the note goes with the stamp: when a worker takes the run again, and
       when the waiting run is stopped or cancelled (its person's stop, the
       owner's Stop or Cancel).
  K* — the rehydrate scan's rewrite of a record STILL waiting keeps the note.

⛔ NO SOURCE PIN IN THE KILLS. Every mutant dies on behaviour: the real
device-command listener, the real idle rescan, the real start listener and
boot rehydration, against `test_requeue_w13`'s fakes of Firestore and a
temporary disk.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/move_note_r2_mutants.py
  .venv/bin/python .mutants/move_note_r2_mutants.py N1 G2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_move_note_r2.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors ──────────────────────────────────────────────────────────────────
WRITES = "    _update_research_doc(uid, rid, _moved_record_patch(data))"
CLEARS_OLD = '    return {**_waiting_record_patch(), "moveNote": note if note else _DF}'
ONLY_STR = '    if not isinstance(raw, str):\n        return ""'
ONE_LINE = '    return " ".join(raw.split())[:MOVE_NOTE_MAX]'
TAKEN = '        "movedToQueueAt": _DF, "moveNote": _DF,\n    })'
OWN_STOP = '        "movedToQueueAt": _DF,\n        "moveNote": _DF,\n    }'
OWNER_CANCEL = "                                    }, movedToQueueAt=_DF, moveNote=_DF))"
WAITING_STAMP = '        "queueEtaComputedAt": _DF,\n        "movedToQueueAt": int(time.time() * 1000),\n    }'

MUTANTS = [
    # ══ N — the move writes the note ══════════════════════════════════════
    ("N1", RESEARCH, "⛔⛔ the move writes no note — the plain waiting record — "
     "killed by THE PIN",
     [(WRITES, "    _update_research_doc(uid, rid, _waiting_record_patch())")]),
    ("N2", RESEARCH, "⛔ a move without a note leaves an old one on the record — "
     "killed by 'writes none and clears an old one'",
     [(CLEARS_OLD, '    return {**_waiting_record_patch(), '
                   '**({"moveNote": note} if note else {})}')]),
    ("N3", RESEARCH, "⛔ anything that is not a string is written as a note — "
     "killed by the number and list cases",
     [(ONLY_STR, "    if not isinstance(raw, str):\n        raw = str(raw)")]),
    ("N4", RESEARCH, "⛔ the note is written as sent — line breaks and all, past 280 — "
     "killed by 'one line and at most 280'",
     [(ONE_LINE, "    return raw.strip()")]),
    # ══ G — the note goes with the stamp ══════════════════════════════════
    ("G1", RESEARCH, "⛔⛔ a worker takes the run and the note stays up — "
     "killed by 'goes with the stamp when a worker takes the run'",
     [(TAKEN, '        "movedToQueueAt": _DF,\n    })')]),
    ("G2", RESEARCH, "⛔ its own person stops the waiting run and the note stays — "
     "killed by 'stopped or cancelled' [own-cancel]",
     [(OWN_STOP, '        "movedToQueueAt": _DF,\n    }')]),
    ("G3", RESEARCH, "⛔ the owner's Stop or Cancel of the waiting run leaves the note — "
     "killed by 'stopped or cancelled' [owner-cancel, owner-stop]",
     [(OWNER_CANCEL, "                                    }, movedToQueueAt=_DF))")]),
    # ══ K — a record still waiting keeps it ═══════════════════════════════
    ("K1", RESEARCH, "⛔ the rehydrate rewrite of a run still waiting clears the owner's "
     "note — killed by 'keeps its note when its record is written again'",
     [(WAITING_STAMP, '        "queueEtaComputedAt": _DF,\n'
                      '        "movedToQueueAt": int(time.time() * 1000),\n'
                      '        "moveNote": _DF,\n    }')]),
]


# ⛔ A SUITE THAT HANGS IS NOT A KILL.
_RUN_TIMEOUT_S = 600


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
    # ⛔⛔ AN IN-FLIGHT MARKER: a killed run (Windows ends a process with no
    # `finally:`) would otherwise leave a mutant in research.py silently.
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
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, TESTS)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — no kill below would mean anything.\n" + out[-1500:])
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
