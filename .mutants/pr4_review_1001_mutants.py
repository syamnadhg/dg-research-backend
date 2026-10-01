"""Mutation harness — the eight items of the approving review of org PR #4
(2026-09-23), fixed 2026-10-01.

⛔⛔ WHAT THIS CODE DECIDES.
  A* — agent/facade/selfupdate.py: the chat assistant's reconnect waiter starts
       with uv's and pipx's homes first on PATH — through Popen's env for a plain
       detached child, and as `--setenv=PATH=…` before systemd-run's `--` when
       it is escaped. (Item 1.)
  N* — research.py: no narrator caller caps Gemini below the default ceiling,
       and an empty MAX_TOKENS answer counts toward the breaker (and only that
       kind of empty answer). (Item 2.)
  W* — research.py main(): a serve owns `pending-w<N>.jsonl` from before its
       first event; a command drops a worker id it inherited. (Item 3.)
  U* — research.py `_nlm_dom_add_files`: a file the chooser took, or that the
       handler already emptied from the queue, is not set on the input too.
       (Item 4.)
  R* — research.py `_update_intent_verdict`: with no target version, a build
       that moved off the starting one is the target. (Item 5.)
  P* — research.py `_post_fe_phase_notice`: the token is fetched on the
       dispatch thread. (Item 6.)
  T* — telemetry.py: a POST still out at the flush deadline keeps its events
       claimed — not adopted, and not renamed over, by our own next flush —
       until its own thread settles them on the real outcome; a POST thread
       that will not start is a failed delivery, and an adopted file's events
       past the batch cap go to the live spool. (Item 7.)
  S* — telemetry.py `_trim_spool`: a trim takes the spool by rename before it
       rewrites it, so a flush's claim in between never leaves the same events
       in two files. (Item 3, its second case.)
  Item 8 is a decision with no code change.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER: a run that dies leaves `<this file>.inflight` naming the
file that still holds a mutant, and the next run refuses to start until it is
restored. Run this in a throwaway worktree, never in the tree a computer runs from.
⛔⛔ SCORED AGAINST THIS CHANGE'S OWN TESTS ONLY.

  python .mutants/pr4_review_1001_mutants.py
  python .mutants/pr4_review_1001_mutants.py A1 N4 T3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

SU = "agent/facade/selfupdate.py"
RESEARCH = "research.py"
TELEMETRY = "telemetry.py"

SUITES = {
    SU: (AGENT, "tests/test_selfupdate_waiter_path_1001.py"),
    RESEARCH: (ROOT, "tests/test_pr4_review_1001.py"),
    TELEMETRY: (ROOT, "tests/test_pr4_review_1001.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")
_RUN_TIMEOUT_S = 900

_PATH_LOOP = ('    for d in [*_waiter_path_dirs(), '
              '*(env.get("PATH") or os.defpath).split(os.pathsep)]:\n')
_SPLICE = '        escape = escape[:-1] + [f"--setenv=PATH={env[\'PATH\']}"] + escape[-1:]\n'
_MAXTOK = '                    if str(cand.get("finishReason") or "").strip() == "MAX_TOKENS":\n'
_SR_SET = '    if args.serve or args.worker_id is not None:\n'
_LATE_GATE = '            if not _chooser_opened and getattr(browser, "_upload_queue", None):\n'
_MOVED = '    _moved = bool(installed) and not installed.startswith("(") and installed != was\n'

MUTANTS = [
    # ═══ A — the chat assistant's reconnect waiter (item 1) ════════════════════
    ("A1", SU, "⛔⛔ the plain detached waiter (macOS, Windows, unsupervised, the "
     "fallback) inherits the supervisor's narrow PATH — pipx cannot find uv",
     [('    return _spawn_detached(waiter, "self-update.log", env=env)\n',
       '    return _spawn_detached(waiter, "self-update.log")\n')]),
    ("A2", SU, "⛔⛔ the systemd transient unit gets the user manager's PATH — no "
     "uv on a supervised Linux host",
     [(_SPLICE, '        escape = list(escape)\n')]),
    ("A3", SU, "⛔ the PATH option lands after `--`, so systemd-run tries to run it "
     "as the command",
     [(_SPLICE, '        escape = escape + [f"--setenv=PATH={env[\'PATH\']}"]\n')]),
    ("A4", SU, "⛔⛔ the waiter's PATH is not widened at all",
     [(_PATH_LOOP,
       '    for d in [*(env.get("PATH") or os.defpath).split(os.pathsep)]:\n')]),
    ("A5", SU, "⛔ the tool homes go LAST — a system pipx or uv wins over the user's",
     [(_PATH_LOOP,
       '    for d in [*(env.get("PATH") or os.defpath).split(os.pathsep), '
       '*_waiter_path_dirs()]:\n')]),
    ("A6", SU, "⛔⛔ the env built for the waiter never reaches Popen",
     [('                                env=env, **kwargs)\n',
       '                                **kwargs)\n')]),
    ("A7", SU, "⛔ a directory already on PATH is listed twice",
     [('    for d in [*_waiter_path_dirs(), *(env.get("PATH") or os.defpath)'
       '.split(os.pathsep)]:\n        if not d or d in seen:\n',
       '    for d in [*_waiter_path_dirs(), *(env.get("PATH") or os.defpath)'
       '.split(os.pathsep)]:\n        if not d:\n')]),
    ("A8", SU, "⛔⛔ the waiter loses the rest of our environment",
     [('    env = dict(os.environ)\n    parts: "list[str]" = []\n',
       '    env = {}\n    parts: "list[str]" = []\n')]),

    # ═══ N — the narrator's ceiling and breaker (item 2) ═══════════════════════
    ("N1", RESEARCH, "⛔⛔ the alert-copy rewrite caps Gemini at 220 again — an empty "
     "MAX_TOKENS answer, and no rewrite on a host without an Anthropic key",
     [('            system, user, gemini_key=gemini_key, use_gemini=use_gemini,\n'
       '            err_holder=None)\n',
       '            system, user, gemini_key=gemini_key, use_gemini=use_gemini,\n'
       '            err_holder=None, max_tokens=220)\n')]),
    ("N2", RESEARCH, "⛔⛔ Tier-3 narration caps Gemini at 200 again",
     [('            err_holder=_narrator_err_holder,\n        )\n'
       '        if fb_status >= 400 or not fb_text:\n',
       '            err_holder=_narrator_err_holder, max_tokens=200,\n        )\n'
       '        if fb_status >= 400 or not fb_text:\n')]),
    ("N3", RESEARCH, "⛔⛔ per-agent narration caps Gemini at 200 again",
     [('                        err_holder=_narrator_err_holder,\n'
       '                    )\n                    if a_status == 429:\n',
       '                        err_holder=_narrator_err_holder, max_tokens=200,\n'
       '                    )\n                    if a_status == 429:\n')]),
    ("N4", RESEARCH, "⛔⛔ an empty MAX_TOKENS answer is not counted — every tick waits "
     "out Gemini's thinking again for the whole phase",
     [(_MAXTOK, '                    if False:\n')]),
    ("N5", RESEARCH, "⛔ every empty answer counts — an empty STOP writes Gemini off",
     [(_MAXTOK, '                    if True:\n')]),
    ("N6", RESEARCH, "⛔ a MAX_TOKENS trip is silent — the log never says Gemini was "
     "written off",
     [('                            exc_name="empty answer (finishReason=MAX_TOKENS)")\n'
       '                        if _tripped:\n                            _note_trip(_detail)\n',
       '                            exc_name="empty answer (finishReason=MAX_TOKENS)")\n')]),
    ("N7", RESEARCH, "⛔⛔ the default ceiling itself drops below what thinking needs",
     [('    max_tokens: int = 800,\n', '    max_tokens: int = 200,\n')]),

    # ═══ W — which telemetry spool a process owns (item 3) ═════════════════════
    ("W1", RESEARCH, "⛔⛔ nothing sets SR_WORKER_ID — every serve shares the command spool",
     [('        os.environ["SR_WORKER_ID"] = str(max(1, int(args.worker_id or 1)))\n',
       '        pass\n')]),
    ("W2", RESEARCH, "⛔ a standalone serve (no --worker-id) still shares the command spool",
     [(_SR_SET + '        os.environ["SR_WORKER_ID"]',
       '    if args.worker_id is not None:\n        os.environ["SR_WORKER_ID"]')]),
    ("W3", RESEARCH, "⛔ a command keeps a worker id it inherited and appends to that "
     "worker's spool",
     [('        os.environ.pop("SR_WORKER_ID", None)\n', '        pass\n')]),
    ("W4", RESEARCH, "⛔ the id is set after the serve's first event — SERVE_STARTED "
     "still lands in the command spool",
     [(_SR_SET + '        os.environ["SR_WORKER_ID"] = str(max(1, int(args.worker_id or 1)))\n'
       '    else:\n        os.environ.pop("SR_WORKER_ID", None)\n', ''),
      ('        tm.tm_emit(tm.Ev.SERVE_STARTED, worker=WORKER_ID,\n'
       '                   supervised=_detect_supervised())\n',
       '        tm.tm_emit(tm.Ev.SERVE_STARTED, worker=WORKER_ID,\n'
       '                   supervised=_detect_supervised())\n'
       '        os.environ["SR_WORKER_ID"] = str(WORKER_ID)\n')]),

    # ═══ U — NotebookLM: one file, one source (item 4) ═════════════════════════
    ("U1", RESEARCH, "⛔⛔ a chooser that opened is ignored — the input in the dialog "
     "takes the same file a second time",
     [(_LATE_GATE, '            if getattr(browser, "_upload_queue", None):\n')]),
    ("U2", RESEARCH, "⛔ a queue the handler already emptied is ignored — the file is "
     "added twice",
     [(_LATE_GATE, '            if not _chooser_opened:\n')]),
    ("U3", RESEARCH, "⛔⛔ the revealed input is never used — with no chooser, nothing "
     "is uploaded",
     [(_LATE_GATE, '            if False:\n')]),

    # ═══ R — an update with no target version (item 5) ═════════════════════════
    ("R1", RESEARCH, "⛔⛔ no target still means 'failed', with no Restart, though the new "
     "build is on disk",
     [('    target = want or (installed if _moved else "")\n', '    target = want\n')]),
    ("R2", RESEARCH, "⛔ a build that never moved reads as installed",
     [(_MOVED, '    _moved = bool(installed) and not installed.startswith("(")\n')]),
    ("R3", RESEARCH, "⛔ '(source checkout)' is reported as the installed version",
     [(_MOVED, '    _moved = bool(installed) and installed != was\n')]),
    ("R4", RESEARCH, "⛔ the restart check compares against the empty target — a "
     "finished update asks for a restart",
     [('        needs = bool(served and served != target)\n',
       '        needs = bool(served and served != want)\n')]),
    ("R5", RESEARCH, "⛔ the verdict reports no version as 'latest'",
     [('        return {"state": "installed", "current": served or installed, '
       '"latest": target,\n',
       '        return {"state": "installed", "current": served or installed, '
       '"latest": want,\n')]),

    # ═══ P — the phase notice's token (item 6) ═════════════════════════════════
    ("P1", RESEARCH, "⛔⛔ the token is refreshed on the caller's thread again — every "
     "phase boundary can hold the worker's loop for an HTTP timeout",
     [('        id_token = _fresh_user_mode_id_token()\n        if not id_token:\n'
       '            # Not an error worth a WARN: an unpaired or revoked machine still\n'
       '            # runs, it just cannot ask.',
       '        id_token = _early_token\n        if not id_token:\n'
       '            # Not an error worth a WARN: an unpaired or revoked machine still\n'
       '            # runs, it just cannot ask.'),
      ('    def _ask():\n        # ⭐ Counted as an in-flight handoff',
       '    _early_token = _fresh_user_mode_id_token()\n\n'
       '    def _ask():\n        # ⭐ Counted as an in-flight handoff')]),

    # ═══ T — telemetry: settle a late POST on its outcome (item 7) ═════════════
    ("T1", TELEMETRY, "⛔⛔ the old behaviour: events go back to the spool at the "
     "deadline and are sent again in a different batch",
     [('        if ok is None:\n            continue', '        if ok is None:\n'
       '            ok = False')]),
    ("T2", TELEMETRY, "⛔⛔ a late answer settles nothing — the claimed file is never "
     "deleted or merged back",
     [('            try:\n                _settle(ok, claimed, path, owed)\n',
       '            try:\n                pass\n')]),
    ("T3", TELEMETRY, "⛔⛔ our own next flush adopts a file whose POST is still out",
     [('    with _in_flight_lock:\n        if str(path) in _IN_FLIGHT:\n'
       '            return False\n', '')]),
    ("T4", TELEMETRY, "⛔ the late callback is never called",
     [('        if late and on_late is not None:\n', '        if False:\n')]),
    ("T5", TELEMETRY, "⛔ every POST counts as late, even one that answered in time",
     [('        if "ok" in state:\n            return state["ok"]\n', '')]),
    ("T6", TELEMETRY, "⛔ the claimed file is never marked in flight",
     [('        with _in_flight_lock:\n            _IN_FLIGHT.add(key)\n', '')]),
    ("T7", TELEMETRY, "⛔⛔ a POST that failed late leaves its events out of the live spool",
     [('    _merge_back(claimed, _unclaimed_name(path))\n    return False\n',
       '    return False\n')]),
    # Added after T3 and T6 survived the first run. Both were masked by a real
    # defect: a flush while a late POST was out renamed the live spool over that
    # POST's claimed file (the name is per process), so its events were gone
    # before anything could post them twice — or merge them back.
    ("T8", TELEMETRY, "⛔⛔ a flush renames the live spool over a claim whose POST is "
     "still out — that POST's events are lost if it then fails",
     [('    with _in_flight_lock:\n        if str(claimed) in _IN_FLIGHT:\n'
       '            return None\n', '')]),
    # Added with the review of this change (2026-10-01).
    ("T9", TELEMETRY, "⛔⛔ a POST thread that will not start raises out of flush — the "
     "file stays marked in flight and this process never sends it again",
     [('        return False\n    thread.join(max(0.1, float(deadline_sec)))\n',
       '        raise\n    thread.join(max(0.1, float(deadline_sec)))\n')]),
    ("T10", TELEMETRY, "⛔⛔ an adopted file's events past the batch cap are written back "
     "into the adopted file itself, which is then deleted",
     [('            _write_back(owed, _unclaimed_name(path))\n',
       '            _write_back(owed, path)\n')]),

    # ═══ S — telemetry: a trim never re-creates a claimed spool (item 3) ═══════
    ("S1", TELEMETRY, "⛔⛔ the old trim: read, then rewrite in place — a claim between "
     "the two re-creates the file and those events are sent twice",
     [('    try:\n        os.replace(str(path), str(taken))\n'
       '        lines = taken.read_text(encoding="utf-8").splitlines()\n'
       '    except OSError:\n'
       '        return            # a flush claimed it first: every one of them is being sent\n',
       ''),
      ('            with open(path, "a", encoding="utf-8") as fh:\n'
       '                fh.write("\\n".join(keep) + "\\n")\n',
       '            with open(path, "w", encoding="utf-8") as fh:\n'
       '                fh.write("\\n".join(keep) + "\\n")\n')]),
    ("S2", TELEMETRY, "⛔⛔ a trim that lost the rename to a claim writes its kept half "
     "back anyway — sent twice",
     [('        return            # a flush claimed it first: every one of them is being sent\n',
       '        pass\n')]),
    ("S3", TELEMETRY, "⛔ the small, newer file the rename took is trimmed as if it were "
     "the old one — fresh events dropped, a drop reported",
     [('    if len(lines) > SPOOL_MAX_LINES:\n        keep = _oldest_half_dropped(lines)\n',
       '    if True:\n        keep = _oldest_half_dropped(lines)\n')]),
    ("S4", TELEMETRY, "⛔⛔ the kept half overwrites an event recorded while the trim "
     "held the file",
     [('            with open(path, "a", encoding="utf-8") as fh:\n'
       '                fh.write("\\n".join(keep) + "\\n")\n',
       '            with open(path, "w", encoding="utf-8") as fh:\n'
       '                fh.write("\\n".join(keep) + "\\n")\n')]),
]


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
