"""Wave 10.9 (#536, the machine half) — can the guards see a research computer
going back to keeping an incognito run?

The promise is "nothing stays in Super Research once the run ends". The app can
stop writing what it used to write and the rules can refuse what a browser or a
wheel sends, but the PIPELINE runs on this machine: it names the queue folder,
writes the logs, uploads the podcast, posts the notices, stamps the expiry and
recreates a record that was purged. Every mutant below is a way one of those
could go back to what it was while the code still looks like it learned.

The ones that matter most are the quiet ones:

  I2  — the id predicate loses its end anchor, so `incog_…-copy` becomes
        ephemeral: somebody's ordinary research hidden from them for good.
  I3  — the predicate answers False for everything. Nothing breaks, no test
        about an ordinary run fails, and the whole feature is decoration.
  I8  — the incognito run id drops the research id, so every incognito run of
        one second shares a queue directory and writes over the other's
        documents.
  I13 — the telemetry id is dropped for EVERYBODY, which loses the join for
        every ordinary run while looking like a privacy fix.
  N4  — the document scrub is skipped along with the upload, which writes the
        agents' signed file links into the text the email carries.
  C2  — the claim fallback recreates a purged incognito record, the exact
        resurrection the rules and this code both exist to refuse.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED. The tests run as
`sys.executable -m pytest` from the repo root, so `-m` puts this checkout first
on sys.path — which is what makes a worktree measure itself rather than the
editable install the venv points at.

⛔ SR_WEB_REPO IS REQUIRED. The capability suite's parity pins read the web
repo's `incognito.ts` and rules, and a SKIP here would read as "the suite was
fine with this mutant".

  SR_WEB_REPO=<web checkout> <venv>/bin/python -u \\
      .mutants/wave109_incognito_machine_mutants.py
  SR_WEB_REPO=<web checkout> <venv>/bin/python -u \\
      .mutants/wave109_incognito_machine_mutants.py I3 I8
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_incognito_capability_109.py "
          "tests/test_incognito_run_id_and_logs_109.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the predicate and the mint ─────────────────────────────────────
ID_RE = '_INCOGNITO_ID_RE = re.compile(r"^incog_[0-9]{13}_[0-9]{1,6}$")'
PREDICATE = ('    return isinstance(research_id, str) and '
             'bool(_INCOGNITO_ID_RE.match(research_id))')
MINT_INCOG = ('    if _is_incognito_research(research_id):\n'
              '        return f"incognito_{research_id.removeprefix(\'incog_\')}_{stamp}"')
MINT_PLAIN = '    return f"{safe_name(topic)}_{stamp}"'
LOG_TOPIC = ('    if _is_incognito_research(research_id):\n'
             '        return _BUNDLE_TOPIC_MARK\n'
             '    return str(topic or "")[:limit]')

# ── anchors: the device capability ──────────────────────────────────────────
CAP_CONST = "_INCOGNITO_RUNS_CAPABILITY = 1"
CAP_SOURCE = ('        return {"version": None, "updateAvailable": None, "sourceCheckout": True,\n'
              '                "servingVersion": None,\n'
              '                "incognitoRuns": _INCOGNITO_RUNS_CAPABILITY}')
CAP_INSTALLED = ('    return {"version": version, "updateAvailable": update_available,\n'
                 '            "sourceCheckout": False, "servingVersion": serving,\n'
                 '            "incognitoRuns": _INCOGNITO_RUNS_CAPABILITY}')

# ── anchors: the consumers ──────────────────────────────────────────────────
# ⛔ THE COMMENT IS PART OF THE ANCHOR. The idle-rescan mints with the same
# call at the same indentation, so the bare line matches twice and the mutant
# would measure nothing while reporting a kill.
LISTENER_MINT = ("            # Generate run_id\n"
                 "            run_id = _mint_run_id(topic, research_id)")
LISTENER_DEFER = ('                        f"topic={_loggable_topic(topic, research_id)!r} '
                  "submittedBy={(data.get('submittedBy') or '?')[:8]} \"\n"
                  '                        f"reason={_defer_reason}",')
LISTENER_CLAIMED = ('                    log(f"[start-listener] worker {WORKER_ID}: claimed '
                    '{research_id[:8]}… topic={_loggable_topic(topic, research_id)!r} '
                    "submittedBy={(data.get('submittedBy') or '?')[:8]}\", \"INFO\")")
LISTENER_MISSING = ('                log(f"Firestore start request missing fields: uid={uid}, '
                    'rid={research_id}, topic={_loggable_topic(topic, research_id, 30)}", "WARN")')

# ── anchors: telemetry ──────────────────────────────────────────────────────
TM_ID = "    return None if _is_incognito_research(research_id) else research_id"
TM_TAP = "    rid = _tm_research_id(rid)"
TM_STARTED = ("            tm.tm_emit(tm.Ev.RUN_STARTED,\n"
              "                       research_id=_tm_research_id(self.research_id),\n"
              "                       worker=WORKER_ID)")
TM_FINISHED = "                       research_id=_tm_research_id(sink.research_id),"

MUTANTS = [
    # ══ the one predicate ══════════════════════════════════════════════════
    ("I1", "over", "a bare prefix match — `incog_notes` becomes a run that "
     "keeps nothing, and its owner never sees it again",
     [(ID_RE, '_INCOGNITO_ID_RE = re.compile(r"^incog_")')]),
    ("I2", "over", "⛔⛔ the end anchor goes — `incog_…-copy` is ephemeral, and "
     "a TTL rule is handed an id it will expire",
     [(ID_RE, '_INCOGNITO_ID_RE = re.compile(r"^incog_[0-9]{13}_[0-9]{1,6}")')]),
    ("I3", "under", "⛔⛔ the predicate answers False for everything — nothing "
     "about an ordinary run breaks and the whole feature is decoration",
     [(PREDICATE, "    return False")]),
    ("I4", "over", "the predicate answers True for everything, so every "
     "ordinary run loses its name, its logs and its telemetry",
     [(PREDICATE, "    return True")]),
    ("I5", "under", "a non-string id raises instead of answering, which stops "
     "a sweep mid-scan",
     [(PREDICATE, "    return bool(_INCOGNITO_ID_RE.match(research_id))")]),

    # ══ the run id ═════════════════════════════════════════════════════════
    ("I6", "under", "⛔⛔ the mint forgets incognito — the topic is back in the "
     "queue folder, the backendRunId and the device document",
     [(MINT_INCOG, "    if False:\n        pass")]),
    ("I7", "under", "the ordinary mint returns the incognito shape, so every "
     "run on the machine loses its name",
     [(MINT_PLAIN, '    return f"incognito_{stamp}"')]),
    ("I8", "under", "⛔⛔ the research id leaves the incognito run id — two "
     "members claiming in the same second share one queue directory",
     [(MINT_INCOG, '    if _is_incognito_research(research_id):\n'
                   '        return f"incognito_{stamp}"')]),
    ("I9", "under", "the stamp leaves the incognito name, so `_RUN_ID_STAMP_RE` "
     "and the bundle's queue-name cut both stop finding it",
     [(MINT_INCOG, '    if _is_incognito_research(research_id):\n'
                   '        return f"incognito_{research_id.removeprefix(\'incog_\')}"')]),

    # ══ the log lines ══════════════════════════════════════════════════════
    ("I10", "under", "⛔ the topic is logged for an incognito run after all",
     [(LOG_TOPIC, '    return str(topic or "")[:limit]')]),
    ("I11", "over", "every run's topic is marked out, so `backend.log` stops "
     "saying what any run was about",
     [(LOG_TOPIC, "    return _BUNDLE_TOPIC_MARK")]),
    ("I12", "under", "the mark is a word of its own instead of the redactor's, "
     "so a bundle and a live log disagree about the same line",
     [(LOG_TOPIC, '    if _is_incognito_research(research_id):\n'
                  '        return "(hidden)"\n'
                  '    return str(topic or "")[:limit]')]),

    # ══ the consumers ══════════════════════════════════════════════════════
    ("I13", "under", "⛔⛔ the listener mints without the research id — the "
     "helper is perfect and the branch that calls it is not",
     [(LISTENER_MINT, "            # Generate run_id\n"
                      "            run_id = _mint_run_id(topic)")]),
    ("I13b", "under", "the defer line of a shared computer goes back to "
     "printing the topic — the run nobody is watching yet",
     [(LISTENER_DEFER, LISTENER_DEFER.replace(
         "{_loggable_topic(topic, research_id)!r}", "{topic[:40]!r}"))]),
    ("I14", "under", "the claim line goes back to printing the topic",
     [(LISTENER_CLAIMED, LISTENER_CLAIMED.replace(
         "{_loggable_topic(topic, research_id)!r}", "{topic[:40]!r}"))]),
    ("I15", "under", "the malformed-document line goes back to printing the "
     "topic — the case where nobody is watching",
     [(LISTENER_MISSING, LISTENER_MISSING.replace(
         "{_loggable_topic(topic, research_id, 30)}", "{topic[:30]}"))]),

    # ══ the device capability ══════════════════════════════════════════════
    ("I16", "under", "⛔⛔ the capability is never published — every app is "
     "left unable to tell an old wheel from a new one",
     [(CAP_CONST, "_INCOGNITO_RUNS_CAPABILITY = None")]),
    ("I17", "under", "the source-checkout branch drops it, which is the "
     "owner's own machine and the first one to run this",
     [(CAP_SOURCE, '        return {"version": None, "updateAvailable": None, '
                   '"sourceCheckout": True,\n                "servingVersion": None}')]),
    ("I18", "under", "the installed branch drops it, so the fleet says nothing",
     [(CAP_INSTALLED, '    return {"version": version, "updateAvailable": update_available,\n'
                      '            "sourceCheckout": False, "servingVersion": serving}')]),
    ("I19", "under", "the capability is published as a string, which the rules "
     "type-check — and `hasOnly` then refuses the WHOLE version patch",
     [(CAP_CONST, '_INCOGNITO_RUNS_CAPABILITY = "1"')]),
    ("I20", "over", "the capability is published as a bool, which is not an int "
     "to the rules either",
     [(CAP_CONST, "_INCOGNITO_RUNS_CAPABILITY = True")]),

    # ══ telemetry ══════════════════════════════════════════════════════════
    ("I21", "under", "⛔ the id reaches telemetry for an incognito run — a "
     "warning per event and an invalid counter for the whole run",
     [(TM_ID, "    return research_id")]),
    ("I22", "under", "⛔⛔ the id is dropped for EVERYBODY, which loses the join "
     "on every ordinary run while looking like a privacy fix",
     [(TM_ID, "    return None")]),
    ("I23", "under", "the per-event tap asks nobody and forwards the raw id",
     [(TM_TAP, "    rid = rid")]),
    ("I24", "under", "the run-started event forwards the raw id",
     [(TM_STARTED, "            tm.tm_emit(tm.Ev.RUN_STARTED,\n"
                   "                       research_id=self.research_id,\n"
                   "                       worker=WORKER_ID)")]),
    ("I25", "under", "the run-finished event forwards the raw id",
     [(TM_FINISHED, "                       research_id=sink.research_id,")]),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
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
    if re.search(r"SKIPPED \[\d+\] tests/test_incognito_capability_109", out):
        raise SystemExit("⛔ the web-parity pins SKIPPED — set SR_WEB_REPO")
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({RESEARCH})
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
    for mid, direction, why, edits in selected:
        path = _path(RESEARCH)
        original = ORIGINALS[RESEARCH]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {RESEARCH} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, RESEARCH, "exec")
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
