"""Wave 10.9 (W9, machine half) — can the guards see the person who sent their
logs being told nothing about what was left out, again?

⛔⛔ WHAT THE WAVE CLOSED. The builder counted what it cut — older items for
size, ticked runs it would not attribute to the asker, other members' runs kept
out of an owner's bundle — and all three reached its own log line and the
terminal. The `done` row carried none of them, so the web could say nothing.

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The ones that matter most are the quiet ones:

  L2  — the NAMES ride the row instead of the count. Still present, still a
        truthy value; it hands a research id to a person whose bundle left out
        somebody else's run.
  L6  — the counts ride the 'uploading' write too: a claim about a sent bundle
        made before anything was sent, on the row a failed send leaves standing.
  L8  — the older-rules retry goes. Nothing looks different while the rules are
        deployed; the day they are behind, every `done` write is refused whole
        and the row sits at 'uploading' naming nothing — the pathless row the
        web's Clear logs has to hold back.
  L9  — the retry fires on ANY failure, so a network outage doubles every
        status write's time on a thread the next press is waiting behind.
  L11 — the retry keeps the counts and drops everything else, objectPath
        included — the exact loss it exists to prevent, spelled backwards.
  W1  — the web rules forget a key the machine writes; only the parity pin can
        see it from this repo.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated Python file is COMPILED before it is written.

⛔ SR_WEB_REPO IS REQUIRED — or a sibling `dg-research` checkout. The parity pin
skips without one, and a skip here would read as "the suite was fine with this
mutant". The harness refuses to run rather than guess.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED. The tests run as
`sys.executable -m pytest` from the repo root, so `-m` puts this checkout first
on sys.path — which is what makes a worktree measure itself rather than the
editable install the venv points at.

  SR_WEB_REPO=<web checkout> <venv>/bin/python -u .mutants/wave109_logs_mutants.py
  SR_WEB_REPO=<web checkout> <venv>/bin/python -u .mutants/wave109_logs_mutants.py L8 L9
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_bundle_left_out_row_109.py "
          "tests/test_bundle_other_members_109.py "
          "tests/test_send_logs_command_0818.py "
          "tests/test_send_logs_cli_0818.py")
RESEARCH = "research.py"
WEB_RULES_FILE = "firestore.rules"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _web_rules_path() -> "Path | None":
    env = os.environ.get("SR_WEB_REPO")
    base = Path(env) if env else ROOT.parent / "dg-research"
    path = base / WEB_RULES_FILE
    return path if path.exists() else None


WEB_RULES = _web_rules_path()

# ── anchors: research.py ────────────────────────────────────────────────────
DROPPED = '        "droppedForSize": len(summary.get("droppedForSize") or []),'
UNATTRIB = '        "runsNotAttributed": int(summary.get("runsNotAttributed") or 0),'
OTHERS = '        "runsOtherMembers": int(summary.get("runsOtherMembers") or 0),'
DONE_SPREAD = ('                    # On `done` only: what the person is shown beside "Sent".\n'
               "                    **_log_bundle_left_out(summary),\n")
UPLOADING_TAIL = ('                "runsApplied": int(summary["maxRunsApplied"]),\n'
                  "            })\n"
                  "            object_path")
CLI_SPREAD = ('                     "sizeBytes": int(summary["sizeBytes"]),\n'
              "                     **_log_bundle_left_out(summary)}")
RETRY_IF = "            if len(bare) == len(body) or not _is_synth_permission_denied(denied):"
STRIP = "            bare = {k: v for k, v in body.items() if k not in _LOG_BUNDLE_LEFT_OUT_KEYS}"
KEYS = '_LOG_BUNDLE_LEFT_OUT_KEYS = ("droppedForSize", "runsNotAttributed", "runsOtherMembers")'
GIVE_UP = ('        log(f"[send-logs] status write failed ({type(exc).__name__}) — the upload "\n'
           '            f"continues; the row will look stale", "WARN")\n'
           "        return False")
DONE_APPLIED = ('                    "runsApplied": int(summary["maxRunsApplied"]),\n'
                "                    # On")

# ── anchors: the web repo's firestore.rules ─────────────────────────────────
RULES_KEYS = "                   'droppedForSize', 'runsNotAttributed', 'runsOtherMembers'])"
RULES_INT = "                  || request.resource.data.droppedForSize is int)"

MUTANTS = [
    # ══ the counts ════════════════════════════════════════════════════════
    ("L1", "under", RESEARCH,
     "the size count is always zero, so a cut bundle reads as complete",
     [(DROPPED, '        "droppedForSize": 0,')]),
    ("L2", "under", RESEARCH,
     "⛔⛔ the NAMES ride the row — a research id handed to whoever reads it",
     [(DROPPED, '        "droppedForSize": summary.get("droppedForSize") or [],')]),
    ("L3", "under", RESEARCH,
     "the unattributed count is always zero",
     [(UNATTRIB, '        "runsNotAttributed": 0,')]),
    ("L4", "under", RESEARCH,
     "the other-members count is always zero",
     [(OTHERS, '        "runsOtherMembers": 0,')]),

    # ══ the consumers ═════════════════════════════════════════════════════
    ("L5", "under", RESEARCH,
     "⛔⛔ the app's `done` write drops the counts — the whole of W9",
     [(DONE_SPREAD, "")]),
    ("L6", "over", RESEARCH,
     "⛔ the counts ride the 'uploading' write — before anything was sent",
     [(UPLOADING_TAIL, '                "runsApplied": int(summary["maxRunsApplied"]),\n'
                       "                **_log_bundle_left_out(summary),\n"
                       "            })\n"
                       "            object_path")]),
    ("L7", "under", RESEARCH,
     "the terminal's `done` row drops the counts, so a terminal send says less "
     "on the web than it printed",
     [(CLI_SPREAD, '                     "sizeBytes": int(summary["sizeBytes"])}')]),

    # ══ older rules ═══════════════════════════════════════════════════════
    ("L8", "under", RESEARCH,
     "⛔⛔ no retry: against older rules the whole `done` write is refused and "
     "the row names nothing",
     [(RETRY_IF, "            if True:")]),
    ("L9", "over", RESEARCH,
     "⛔ the retry fires on ANY failure, doubling a network outage",
     [(RETRY_IF, "            if len(bare) == len(body):")]),
    ("L10", "over", RESEARCH,
     "the retry fires on a denial with nothing to drop — the same refused write "
     "sent twice",
     [(RETRY_IF, "            if not _is_synth_permission_denied(denied):")]),
    ("L11", "under", RESEARCH,
     "⛔⛔ the retry keeps the counts and drops everything else, objectPath too",
     [(STRIP, "            bare = {k: v for k, v in body.items() if k in _LOG_BUNDLE_LEFT_OUT_KEYS}")]),
    ("L12", "under", RESEARCH,
     "the retry forgets one key, so the retried write is refused as well",
     [(KEYS, '_LOG_BUNDLE_LEFT_OUT_KEYS = ("droppedForSize", "runsNotAttributed")')]),

    # ══ neighbours the change moved (replicas of send_logs_0818 R5 / N7) ═══
    ("L13", "over", RESEARCH,
     "a status-write failure aborts an upload that was working",
     [(GIVE_UP, "        raise")]),
    ("L14", "under", RESEARCH,
     "the `done` row reports the caller's bound, not the builder's",
     [(DONE_APPLIED, '                    "runsApplied": int(runs),\n'
                     "                    # On")]),

    # ══ the web rules (cross-repo; the parity pin is the only reader here) ══
    # ⚠ The file column is the app repo's RELATIVE path, which is what
    # `_anchor_sweep.py` resolves against its three roots; `_path` below maps it
    # to SR_WEB_REPO for the run itself.
    ("W1", "under", WEB_RULES_FILE,
     "⛔ the web rules forget a key the machine writes",
     [(RULES_KEYS, "                   'droppedForSize', 'runsNotAttributed'])")]),
    ("W2", "under", WEB_RULES_FILE,
     "a count is typed as something other than an int",
     [(RULES_INT, "                  || request.resource.data.droppedForSize is number)")]),
]


def _path(fname: str) -> Path:
    return WEB_RULES if fname == WEB_RULES_FILE else ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL. The first draft of the retry
#: recursed, and its guard's mutant recursed forever — `except Exception` catches
#: RecursionError and walks back into the retry — so the harness waited on it for
#: ten minutes. A bounded run turns that into a named fault instead of silence.
_RUN_TIMEOUT_S = 300


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q",
             "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    # ⛔ A SKIP IS NOT A PASS: the parity pin skips without a web checkout, and a
    # skipped pin would read as "the suite was fine with this mutant".
    if re.search(r"SKIPPED \[\d+\] tests/test_bundle_left_out_row_109", out):
        raise SystemExit("⛔ this harness's own parity pin SKIPPED — set SR_WEB_REPO")
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    if WEB_RULES is None:
        print("⛔ no web firestore.rules found — set SR_WEB_REPO to the web checkout.")
        sys.exit(2)
    files = sorted({m[2] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

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
        path = _path(fname)
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
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as e:
                    raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}", flush=True)
            else:
                print(f"  {mid}  ✓ killed", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if _path(f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
