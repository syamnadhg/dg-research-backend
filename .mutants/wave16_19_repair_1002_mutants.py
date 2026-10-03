"""Mutation harness — the review repair of waves 16 and 19 on the computer
(10-02). Run ONCE, on the new lines and on the old lines the review found
untested.

⛔⛔ WHAT THIS CODE DECIDES.
  R*  the research's name: the end of Phase 2 names a record still without one
      (the podcast-off case the old rename covered); only the chat assistant's
      record (`viaAgent`) counts its topic as no name; the pick-up names only
      that record, and rewrites its chat's opening line to the name — never for
      a run that keeps nothing, never without a name.
  X*  wave 16 lines the review found untested: the newest of two folders is
      continued; a carried event list over the cap keeps its newest and counts
      the rest; a joined attempt starts its own clock; an ended attempt stays
      ended.
  G*  tests/conftest.py: no test reaches this computer's real sign-in — the two
      helpers are stood in for, the reach recorded and failed at teardown with
      where it came from; a test of a helper itself names it.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/wave16_19_repair_1002_mutants.py
  .venv/bin/python .mutants/wave16_19_repair_1002_mutants.py R1 G2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
CONFTEST = "tests/conftest.py"

#: The tests the mutants are measured by (names joined into one string, never a
#: `*.py` value in a row: the anchor sweep reads those as target files).
_TESTS = " ".join("tests/" + n + ".py" for n in (
    "test_one_short_name_w19", "test_one_log_folder_per_research_w16",
    "test_track_d_d5c"))
SUITES = {RESEARCH: (ROOT, _TESTS), CONFTEST: (ROOT, _TESTS)}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
       "PYTHONPATH": str(ROOT)}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── R: the research's name ──────────────────────────────────────────────
    ('R1', RESEARCH, '⛔⛔ the measured defect: nothing after Phase 2 names a "New Research" '
                     'record — with the podcast off it keeps it for good',
     [('            await asyncio.to_thread(_name_a_research_left_unnamed, _fb_uid,\n'
       '                                    _fb_research_id, topic)\n',
       '            pass\n')]),
    ('R2', RESEARCH, 'a naming failure fails Phase 2',
     [('        except Exception as _nm_e:\n'
       '            log(f"[name] naming after Phase 2 failed ({type(_nm_e).__name__})",\n',
       '        except ZeroDivisionError as _nm_e:\n'
       '            log(f"[name] naming after Phase 2 failed ({type(_nm_e).__name__})",\n')]),
    ('R3', RESEARCH, '⛔ a record that could not be read is named on a guess at Phase 2\'s end',
     [('    if not found or not _research_name_missing(record.get("title"), topic,\n',
       '    if not _research_name_missing(record.get("title"), topic,\n')]),
    ('R4', RESEARCH, 'the assistant\'s record its pick-up missed is never named at Phase 2\'s end',
     [('    if not found or not _research_name_missing(record.get("title"), topic,\n'
       '                                               record.get("viaAgent")):\n',
       '    if not found or not _research_name_missing(record.get("title"), topic,\n'
       '                                               False):\n')]),
    ('R5', RESEARCH, '⛔⛔ the measured defect: a web research named like its topic is asked '
                     'for again by every process',
     [('            or (bool(via_agent) and _is_the_topic(t, topic)))\n',
       '            or _is_the_topic(t, topic))\n')]),
    ('R6', RESEARCH, '⛔ every record is read as the assistant\'s',
     [('                  or not _research_name_missing(title, topic,\n'
       '                                                record.get("viaAgent"))):\n',
       '                  or not _research_name_missing(title, topic,\n'
       '                                                True)):\n')]),
    ('R7', RESEARCH, '⛔ no record is read as the assistant\'s — its whole topic is its name',
     [('                  or not _research_name_missing(title, topic,\n'
       '                                                record.get("viaAgent"))):\n',
       '                  or not _research_name_missing(title, topic,\n'
       '                                                False)):\n')]),
    ('R8', RESEARCH, '⛔⛔ the measured defect: the pick-up names a web research named like its '
                     'topic and writes over the chat\'s name',
     [('    if (not found or not bool(record.get("viaAgent"))\n'
       '            or bool(record.get("titleLocked"))\n',
       '    if (not found\n'
       '            or bool(record.get("titleLocked"))\n')]),
    ('R9', RESEARCH, '⛔ the person\'s own rename goes into the opening line as the whole topic',
     [('    if (not found or not bool(record.get("viaAgent"))\n'
       '            or bool(record.get("titleLocked"))\n',
       '    if (not found or not bool(record.get("viaAgent"))\n')]),
    ('R10', RESEARCH, '⛔ the opening line keeps the topic',
     [('    if name:\n        _rename_agent_intro(uid, research_id, name)\n', '')]),
    ('R11', RESEARCH, 'the opening line says Researching **""**',
     [('    if name:\n        _rename_agent_intro(uid, research_id, name)\n',
       '    if True:\n        _rename_agent_intro(uid, research_id, name)\n')]),
    ('R12', RESEARCH, '⛔ a run that keeps nothing gets an opening line written',
     [('    if _is_incognito_research(rid):\n        return\n    try:\n'
       '        _grpc_write_with_heal(\n',
       '    try:\n        _grpc_write_with_heal(\n')]),
    ('R13', RESEARCH, 'the opening line says it in other words than the web',
     [('                .update(_be_payload({"content": f\'Researching **"{name}"**\'})),\n',
       '                .update(_be_payload({"content": f\'Researching "{name}"\'})),\n')]),
    ('R14', RESEARCH, '⛔ another bubble than the opening line is written',
     [('                .collection("messages").document(f"intro-{rid}")\n',
       '                .collection("messages").document(f"topic-{rid}")\n')]),
    ('R15', RESEARCH, '⛔ the write carries no device id — the rules refuse it',
     [('                .update(_be_payload({"content": f\'Researching **"{name}"**\'})),\n',
       '                .update({"content": f\'Researching **"{name}"**\'}),\n')]),
    ('R16', RESEARCH, '⛔ the name reaches the log when the opening line cannot be written',
     [('        log(f"[name] the chat\'s opening line kept the topic ({type(e).__name__})",\n',
       '        log(f"[name] the chat\'s opening line kept the topic ({name})",\n')]),

    # ── X: wave 16 lines the review found untested ──────────────────────────
    ('X1', RESEARCH, '⛔ after a split the OLDEST folder is continued',
     [('        if best is None or key > best[0]:\n',
       '        if best is None or key < best[0]:\n')]),
    ('X2', RESEARCH, 'a carried event list over the cap keeps its oldest',
     [('                kept = kept[-RUN_LOG_EVENT_CAP:]\n',
       '                kept = kept[:RUN_LOG_EVENT_CAP]\n')]),
    ('X3', RESEARCH, 'the events a carried list drops are not counted',
     [('                self.counters["eventsDropped"] += len(kept) - RUN_LOG_EVENT_CAP\n',
       '')]),
    ('X4', RESEARCH, '⛔ a joined attempt keeps the first one\'s clock — its time is the total',
     [('        self.started_utc = _utc_iso()\n        self.started_mono = time.monotonic()\n',
       '        self.started_utc = _utc_iso()\n')]),
    ('X5', RESEARCH, '⛔ an ended attempt is closed again — "moved" overwritten as "failed"',
     [('        if current is None or current.get("status") != "running":\n',
       '        if current is None:\n')]),

    # ── G: no test reaches this computer's real sign-in ─────────────────────
    ('G1', CONFTEST, '⛔⛔ the guard stands in for nothing — a test reaches the real sign-in',
     [('        monkeypatch.setattr(research, name, _refused, raising=True)\n', '')]),
    ('G2', CONFTEST, '⛔⛔ a test that reached the sign-in still passes',
     [('    if reached:\n        name, where = reached[0]\n',
       '    if False:\n        name, where = reached[0]\n')]),
    ('G3', CONFTEST, 'a test of a helper itself gets the stand-in',
     [('    left_real = set(marker.args) if marker else set()\n',
       '    left_real = set()\n')]),
    ('G4', CONFTEST, '⛔ the token\'s stand-in hands out a token — the real namer posts',
     [('        cannot = "" if name == "_ask_web_namer" else None\n',
       '        cannot = "" if name == "_ask_web_namer" else "tok"\n')]),
    ('G5', CONFTEST, 'the namer\'s stand-in makes up a name',
     [('        cannot = "" if name == "_ask_web_namer" else None\n',
       '        cannot = "x" if name == "_ask_web_namer" else None\n')]),
    ('G6', CONFTEST, '⛔ the reach is not recorded',
     [('            reached.append((_name, "".join(traceback.format_stack(limit=12)[:-1])))\n',
       '            pass\n')]),
    ('G7', CONFTEST, 'the failure does not say where it was reached from',
     [('                    f"Reached from:\\n{where}", pytrace=False)\n',
       '                    f"Reached from: (not said)", pytrace=False)\n')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too, and a
    # skipped test is not a measurement.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


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
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}", flush=True)
            else:
                print(f"  {mid:4} ✓ killed", flush=True)
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}", flush=True)
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
