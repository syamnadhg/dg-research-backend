"""Mutation harness — everyone already waiting gets in when the owner turns Allow all
on (2026-09-29).

⛔⛔ WHAT THIS CODE DECIDES.
  B* — bridge `/device/visibility`: the web app's `admit-waiting` route is asked
       EXACTLY once, after a CONFIRMED Allow-all ON write or when the yes finds
       Allow all already on (the retry) — never on OFF, private, a plain public,
       or a write that was refused, unconfirmed or revoked; only a 200 with real
       counts is a confirmation, anything else is `{"unconfirmed": True}` and
       Allow all is still reported on; the route gets its own longer wait.
  S* — sr.py: the lines under the switch (who joined, who is still waiting and
       why, could-not-confirm with the retry), "Nothing to change" only when
       nothing else is said, the 75s wait, and the switch-on question saying
       anyone already waiting joins too — counted in `do`, for that computer only,
       never in the router.
  T* — cli.py: the terminal's copy of the same lines, and its 75s wait.
  K* — SKILL.md: the one line beside the Allow-all confirm rule.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler: a run that dies leaves `<this file>.inflight` naming the file that
still holds a mutant, and the next run refuses to start until it is restored. Run
this in a throwaway worktree, never in the tree the agent is installed from.
⛔⛔ SCORED AGAINST THIS CHANGE'S OWN TESTS ONLY — a borrowed kill from an older
file is not evidence that the guard just written works.

  python .mutants/admit_waiting_0929_mutants.py
  python .mutants/admit_waiting_0929_mutants.py B1 S9 T3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
SR = "agent/facade/skill/scripts/sr.py"
CLI = "agent/facade/cli.py"
SKILL = "agent/facade/skill/SKILL.md"

_OWN = "tests/test_allow_all_admit_waiting_0929.py"
SUITES = {
    BRIDGE: (AGENT, _OWN),
    SR: (AGENT, _OWN),
    CLI: (AGENT, _OWN),
    SKILL: (AGENT, _OWN),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ═══ B — the bridge ════════════════════════════════════════════════════════
    ("B1", BRIDGE, "⛔⛔ 'allow all yes' on a computer already on never runs the sweep — "
     "the retry the owner chose does nothing, and a computer ticked before this "
     "shipped keeps its waiting people waiting",
     [('                if allow is True:\n'
       '                    same["waiting"] = _admit_waiting(sess, device_id)\n', '')]),
    ("B2", BRIDGE, "⛔⛔ any no-op on an Allow-all computer — a plain 'make it public', "
     "an OFF that already holds — lets everyone waiting in",
     [('                if allow is True:\n                    same["waiting"]',
       '                if True:\n                    same["waiting"]')]),
    ("B3", BRIDGE, "⛔⛔ THE FEATURE IS GONE: switching Allow all on never lets anyone "
     "already waiting in",
     [('            if allow is True:\n'
       '                done["waiting"] = _admit_waiting(sess, device_id)\n', '')]),
    ("B4", BRIDGE, "⛔⛔ going private, switching Allow all OFF or a plain publish lets "
     "everyone waiting in",
     [('            if allow is True:\n                done["waiting"]',
       '            if True:\n                done["waiting"]')]),
    ("B5", BRIDGE, "⛔ a non-200 carrying count-shaped fields is reported as people let in",
     [('    if status != 200 or not counts:\n', '    if not counts:\n')]),
    ("B6", BRIDGE, "⛔ a 200 with no counts is relayed as counts — the clients read "
     "missing as 'nobody was waiting'",
     [('    if status != 200 or not counts:\n', '    if status != 200:\n')]),
    ("B7", BRIDGE, "⛔ a bool is a count — 'True people joined'",
     [('isinstance(n, int) and not isinstance(n, bool) and n >= 0',
       'isinstance(n, int) and n >= 0')]),
    ("B8", BRIDGE, "⛔ a negative count is relayed",
     [('isinstance(n, int) and not isinstance(n, bool) and n >= 0',
       'isinstance(n, int) and not isinstance(n, bool)')]),
    ("B9", BRIDGE, "⛔ `full` is read loosely — a string says the computer is full",
     [('    full = body.get("full") is True\n', '    full = bool(body.get("full"))\n')]),
    ("B10", BRIDGE, "⛔ the route gets the shared fifteen seconds — a sweep that committed "
     "comes back 'could not confirm'",
     [('{"deviceId": device_id},\n                                timeout=_FE_ADMIT_TIMEOUT)',
       '{"deviceId": device_id})')]),
    ("B11", BRIDGE, "⛔ the contract's path is wrong — every sweep is a 404",
     [('_ADMIT_WAITING_PATH = "/api/devices/access-request/admit-waiting"\n',
       '_ADMIT_WAITING_PATH = "/api/devices/access-request/decide"\n')]),
    ("B12", BRIDGE, "⛔⛔ a refused or unconfirmed write still lets everyone waiting in",
     [('                log.warning("device visibility write failed: %s", e)\n',
       '                log.warning("device visibility write failed: %s", e)\n'
       '                if allow is True:\n'
       '                    _admit_waiting(sess, device_id)\n')]),
    ("B13", BRIDGE, "⛔⛔ a revoked sign-in's switch still asks the route",
     [('                # A revoked sign-in sends nothing, so after a landed clear the\n',
       '                _admit_waiting(sess, device_id)\n'
       '                # A revoked sign-in sends nothing, so after a landed clear the\n')]),
    ("B14", BRIDGE, "⛔⛔ the sweep runs BEFORE the write lands — on a switch that may "
     "never go on, and twice on one that does",
     [('            clear_first = want_all is True and current != "public" and stored\n',
       '            if allow is True:\n'
       '                _admit_waiting(sess, device_id)\n'
       '            clear_first = want_all is True and current != "public" and stored\n')]),

    # ═══ S — the chat (sr.py) ══════════════════════════════════════════════════
    ("S1", SR, "⛔⛔ the owner is never told who joined",
     [('                 *waiting,\n', '')]),
    ("S2", SR, "⛔ 'Nothing to change' over people a retry just let in",
     [('                      + ("" if waiting else " Nothing to change."),\n',
       '                      + " Nothing to change.",\n')]),
    ("S3", SR, "⛔⛔ an unconfirmed sweep says nothing — the owner never learns to retry",
     [('    if waiting.get("unconfirmed"):\n        return [_WAITING_UNCONFIRMED]\n', '')]),
    ("S4", SR, "⛔ an older bridge with no `waiting` crashes the reply",
     [('    if not isinstance(waiting, dict):\n        return []\n'
       '    if waiting.get("unconfirmed"):\n        return [_WAITING_UNCONFIRMED]\n',
       '    if waiting.get("unconfirmed"):\n        return [_WAITING_UNCONFIRMED]\n')]),
    ("S5", SR, "⛔ people left waiting on a computer with room are told it is full",
     [('f"your requests." if waiting.get("full") is True',
       'f"your requests." if True')]),
    ("S6", SR, "⛔ '1 people who were already waiting'",
     [('"1 person who was already waiting joined too." if joined == 1',
       '"1 person who was already waiting joined too." if False')]),
    ("S7", SR, "⛔⛔ the chat gives up at forty — a slow sweep reads as a lost switch",
     [('**payload}, timeout=75)', '**payload}, timeout=40)')]),
    ("S8", SR, "⛔⛔ the switch-on question never says the people waiting join too — "
     "consent to less than the yes does",
     [('(_ALLOW_ALL_MEANS + " " + _AA_WAITING_JOIN + " If it isn’t "',
       '(_ALLOW_ALL_MEANS + " If it isn’t "')]),
    ("S9", SR, "⛔ every question `do` prints costs a look at the owner's requests",
     [('    if not any(_AA_WAITING_JOIN in line for line in lines):\n'
       '        return lines\n', '')]),
    ("S10", SR, "⛔⛔ the count takes people waiting on the owner's OTHER computers",
     [('row.get("deviceId") == dev.get("id")', 'row.get("deviceId")')]),
    ("S11", SR, "⛔ `do` never counts — the question never carries a number",
     [('_with_waiting_count(text, lines or [])', 'lines or []')]),
    ("S12", SR, "⛔ the computer the owner named is ignored — the count is for a guess",
     [('    dev, _ = _resolve_device_arg(named) if named else _pick_owned_device()\n',
       '    dev, _ = _pick_owned_device()\n')]),
    ("S13", SR, "⛔ several computers and none named crashes the question",
     [('    if dev is None:\n        return lines\n', '')]),
    ("S14", SR, "⛔ '0 people are already waiting' — no count is said as a count",
     [('    if not count:\n        return lines\n', '')]),
    ("S15", SR, "⛔ '1 people are still waiting'",
     [('        who = "1 person is" if left == 1 else',
       '        who = "1 person is" if False else')]),
    ("S16", SR, "⛔ '0 people who were already waiting joined too' when nobody was",
     [('    joined = waiting.get("admitted") or 0\n    if joined:\n',
       '    joined = waiting.get("admitted") or 0\n    if True:\n')]),
    ("S17", SR, "⛔ '0 people are still waiting' when nobody is",
     [('    left = waiting.get("stillWaiting") or 0\n    if left:\n',
       '    left = waiting.get("stillWaiting") or 0\n    if True:\n')]),

    # ═══ T — the terminal (cli.py) ═════════════════════════════════════════════
    ("T1", CLI, "⛔⛔ the terminal never says who joined",
     [('        for line in waiting:\n            print(line)\n', '')]),
    ("T2", CLI, "⛔ 'Nothing to change' over people a retry just let in",
     [("{'' if changed or waiting else ' Nothing to change.'}",
       "{'' if changed else ' Nothing to change.'}")]),
    ("T3", CLI, "⛔⛔ an unconfirmed sweep says nothing — no retry is named",
     [('    if waiting.get("unconfirmed"):\n        return ["     Allow all is on',
       '    if False:\n        return ["     Allow all is on')]),
    ("T4", CLI, "⛔ people left waiting on a computer with room are told it is full",
     [('f"in your requests." if waiting.get("full") is True',
       'f"in your requests." if True')]),
    ("T5", CLI, "⛔⛔ the terminal gives up at forty — a slow sweep reads as a lost switch",
     [('**payload}, timeout=75.0)', '**payload}, timeout=40.0)')]),
    ("T6", CLI, "⛔ an older bridge with no `waiting` crashes the reply",
     [('    if not isinstance(waiting, dict):\n        return []\n'
       '    if waiting.get("unconfirmed"):\n        return ["     Allow',
       '    if waiting.get("unconfirmed"):\n        return ["     Allow')]),
    ("T7", CLI, "⛔ '0 people who were already waiting joined too' when nobody was",
     [('    joined = waiting.get("admitted") or 0\n    if joined:\n',
       '    joined = waiting.get("admitted") or 0\n    if True:\n')]),
    ("T8", CLI, "⛔ '0 people are still waiting' when nobody is",
     [('    left = waiting.get("stillWaiting") or 0\n    if left:\n',
       '    left = waiting.get("stillWaiting") or 0\n    if True:\n')]),
    ("T9", CLI, "⛔ '1 people who were already waiting'",
     [('"     1 person who was already waiting joined too." if joined == 1',
       '"     1 person who was already waiting joined too." if False')]),
    ("T10", CLI, "⛔ '1 people are still waiting'",
     [('        who = "1 person is" if left == 1 else',
       '        who = "1 person is" if False else')]),
    ("T11", CLI, "⛔ the retry command names no computer — it cannot be run as printed",
     [('f"     run `agent device allow-all {device_id} yes` again to retry."',
       '"     run `agent device allow-all <id> yes` again to retry."')]),

    # ═══ K — SKILL.md ══════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ the assistant's confirm rule never says the yes lets the waiting "
     "people in, nor what the retry is",
     [('Its yes also lets in everyone already waiting on that computer (oldest first, '
       'up to 25 people in all) — the question says so, the reply says who joined, and '
       'when the reply could not confirm them the retry is the same `device-allow-all '
       'yes`, confirmed again.\n', '')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
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
