"""Mutation harness — wave 8: the agent log travels alone, the rename survives, a
machine that cannot run is not offered, and four filed items (2026-09-16).

⛔⛔ WHAT THIS CODE DECIDES. Whether the one person who cannot reach a research
computer can send the file that describes exactly that; whether they get a support
code for it, which is the only thing that makes it forwardable to a developer;
whether what a person is told before it leaves is what actually leaves; whether a
public computer stays public the day anything writes the new field name; whether
the agent offers a machine the browser would refuse; and whether `agent disconnect`
deletes a cron row that was never ours.

⛔⛔ EVERY DEFECT IN THIS WAVE IS SILENT, WHICH IS WHY THE HARNESS MATTERS MORE
THAN USUAL. The rename turns computers private with no error on any surface. The
pairing filter announces "Started" on a machine the app refuses. The online check
never decays on a fast clock. The poller's truncated state file reads as a clean
first tick. Not one of them raises, logs, or shows a person anything.

⭐⭐ THE SHARPEST MUTANTS HERE (ids checked against the list below — an earlier
version of this header named four that carried different mutations, so a reader
navigating by id landed somewhere else):
  S1/S2   — the standalone send loses its explicitness and infers the mode from a
            missing code. Every ordinary test still passes; a client that drops
            its support code silently opens a new bundle nobody was told about.
  S6      — the chat client stops asking for the standalone route at all, so
            `--agent-log --none` falls through to the run list, which refuses
            anybody who has no computer — the exact person it exists for.
  T1      — the rotated copies are collected OLDEST-FIRST, so the cap fills with
            the oldest rotation and the material being reported is what gets
            dropped. Every "did the backups go" assertion still passes.
  D2      — the NEW field name wins over the old one, which disagrees with every
            writer and every query there is: the agent then reports a discovery
            state the product does not implement, and the toggle answers "already
            public" to an owner closing the door.
  D4      — the toggle goes back to the pre-wave state, a raw row AND a raw
            literal. ⛔ It takes BOTH edits: each half alone is an equivalent
            mutant, which is how the first version of it reported a survivor and
            measured nothing.
  P1      — the chosen machine is accepted even when it cannot take a run, so a
            computer part-way through a Reset is enqueued to and the person is
            told "Started" while the browser refuses the identical machine.
  C2      — the future bound becomes the offline threshold, which is the exact
            mistake the web app made in wave 3: a machine 45 s fast reads offline
            everywhere and every run is refused.
  A1      — the state file goes back to a truncating write. Nothing fails; the
            next tick baselines silently and every phase that completed is lost.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS WAVE'S OWN GUARDS. Pass --unfiltered to ask the other
question — whether the TREE catches it — which is deliberately separate. A
borrowed kill is not evidence that the guard you just wrote works.

    .venv/bin/python .mutants/wave8_agent_0916_mutants.py
    .venv/bin/python .mutants/wave8_agent_0916_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

CLI = "agent/facade/cli.py"
BRIDGE = "agent/facade/bridge.py"
SR = "agent/facade/skill/scripts/sr.py"
REST = "agent/facade/firestore_rest.py"
CONNECT = "agent/facade/connect.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
SKILL = "agent/facade/skill/SKILL.md"
OURS = (CLI, BRIDGE, SR, REST, CONNECT, POLL, SKILL)

# ⭐ THE GUARDS THIS WAVE ADDED, and the only tests a score here is about.
MINE = ("tests/test_agent_log_alone_0916.py "
        "tests/test_wave8_survival_0916.py "
        "tests/test_chat_public_792.py "
        "tests/test_agent_log_consent_791.py "
        "tests/test_send_logs_picker_791.py "
        "tests/test_send_logs_crossverify_791.py "
        "tests/test_chat_picker_791.py "
        "tests/test_log_locality_791.py "
        "tests/test_connect.py")
MIN_SELECTED = 300

ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ S — the log travels alone ══════════════════════════════════
    ("S1", BRIDGE, "under",
     "⛔⛔ THE STANDALONE ROUTE DISAPPEARS and the person with no research "
     "computer is back to the refusal — the state the whole lane exists to end",
     [('            if standalone:\n'
       '                self._agent_log_alone(sess)\n'
       '                return\n', '')]),
    ("S2", BRIDGE, "over",
     "⛔⛔ THE MODE IS INFERRED FROM A MISSING CODE instead of asked for. A client "
     "that loses its support code silently opens a NEW bundle under a code nobody "
     "was told, which reads as success on every surface",
     [('            standalone = body.get("standalone") is True',
       '            standalone = body.get("standalone") is True or not code')]),
    ("S3", BRIDGE, "under",
     "the contradiction is resolved instead of refused, so a caller asking for "
     "two different things gets whichever the code happened to read first",
     [('            if standalone and code:\n', '            if False:\n')]),
    ("S4", BRIDGE, "under",
     "⛔ THE MODE HEADER GOES, so the app reads an attach with no code and answers "
     "400 — the send fails for a reason the person cannot act on",
     [('                {"x-agent-log-mode": "standalone"},', '                {},')]),
    ("S5", BRIDGE, "over",
     "⛔⛔ A 200 THAT STORED NOTHING IS REPORTED AS A SEND, so somebody is handed "
     "an empty support code — or a sentence claiming their log went with no code "
     "under it",
     [('            if not reply.get("stored") or not code:',
       '            if False:')]),
    ("S6", SR, "under",
     "⛔ THE CHAT CLIENT STOPS ASKING FOR IT, so `--agent-log --none` falls through "
     "to the run list, which refuses anybody who has no computer",
     [('    if _agent_log_only_request(args):\n'
       '        owned_hint, hint_name = _agent_log_machine_hint(args)\n'
       '        return _send_agent_log_alone(args, offer_machine=owned_hint, name=hint_name)\n',
       '')]),
    ("S7", SR, "over",
     "⛔⛔ BARE `--agent-log` BECOMES THE LOG ALONE, so somebody who asked for every "
     "run AND the agent's log gets only the log — silently, and the runs they "
     "asked for are never sent",
     [('    return bool(getattr(args, "none", False)) or bool(spec)',
       '    return True')]),
    ("S8", SR, "over",
     "a spec naming runs as well as 0 is treated as the log alone, so the runs the "
     "person picked are dropped without a word",
     [('    if [t for t in spec if t != _AGENT_LOG_TOKEN]:\n        return False\n', '')]),
    ("S9", SR, "under",
     "⛔ THE CONFIRM STOPS SENDING, so a person who said yes is told nothing and "
     "nothing goes",
     [('    code, sent = _post("/logs/agent-log", {"standalone": True})',
       '    code, sent = 200, {}')]),
    ("S10", CLI, "under",
     "the terminal's plan stops being a consent screen — the send happens without "
     "the prompt, which is what makes the claim true",
     [('    if not _decide(None, bool(getattr(args, "yes", False)),\n'
       '                   "Send the agent\'s own log?", default=False):\n'
       '        print("Nothing was sent.")\n'
       '        return 1\n', '')]),

    ("S14", SR, "under",
     "⛔⛔ THE MACHINE OFFER LOSES THE COMMAND THAT DELIVERS IT. The plan still "
     "tells an owner their computer's own logs can go in the same breath, and the "
     "only command on the screen sends the agent's log ALONE — an offer an "
     "assistant cannot carry out, which is the circle an earlier wave closed",
     [('            directives.append(\n                "If they want that computer’s own logs too, run instead: sr.py "\n                "send-logs --confirm --machine --none --agent-log")\n', "")]),

    # ═══════════ T — the rotated copies ═════════════════════════════════════
    ("T1", BRIDGE, "over",
     "⛔⛔ THE BUDGET IS SPENT OLDEST-FIRST, so the cap fills with the oldest "
     "rotation and the material being reported is what gets dropped — every "
     "\"did the backups go\" assertion still passes",
     [("    for path in reversed(present):", "    for path in present:")]),
    ("T2", BRIDGE, "under",
     "⛔ ONLY THE ACTIVE FILE GOES AGAIN, so a problem that scrolled past a "
     "rotation is unsendable and nothing says so",
     [("    present = [p for p in _agent_log_paths() if _file_size(p) > 0]",
       "    present = [p for p in _agent_log_paths()[-1:] if _file_size(p) > 0]")]),
    ("T3", BRIDGE, "over",
     "the single-file read charges a banner nobody will see against its cap, so a "
     "tight cap loses the last whole line — the shape that made this a two-pass "
     "function rather than one loop",
     [('    if len(present) == 1:\n        return _read_file_tail(present[0], cap)\n', '')]),
    ("T4", BRIDGE, "over",
     "the oldest rotation is looked for one past the handler's backup count, so "
     "the file it does keep is the one that never arrives",
     [("_AGENT_LOG_BACKUPS = 3", "_AGENT_LOG_BACKUPS = 2")]),
    ("T5", BRIDGE, "over",
     "⛔ THE ASSEMBLED BUNDLE IS WRITTEN NEWEST-FIRST — a log read backwards is not "
     "a log, and nothing in the file says which way round it is",
     [("    parts.reverse()\n    return b\"\".join(parts)",
       "    return b\"\".join(parts)")]),

    # ═══════════ D — the rename ═════════════════════════════════════════════
    ("D1", BRIDGE, "under",
     "⛔⛔ THE NEW NAME STOPS BEING READ. The day the migration removes the old "
     "key, every public computer reads private in chat and in the terminal, with "
     "no error anywhere",
     [('_DISCOVERY_KEYS = ("visibility", "joinPolicy")',
       '_DISCOVERY_KEYS = ("visibility",)')]),
    ("D2", BRIDGE, "over",
     "⛔⛔ THE NEW NAME WINS OVER THE OLD ONE — which disagrees with every writer "
     "and every query there is, so the agent reports a discovery state the product "
     "does not implement, and the toggle answers \"already public\" to an owner "
     "closing the door. Both keys are still read, so no test supplying one alone "
     "can see it",
     [('_DISCOVERY_KEYS = ("visibility", "joinPolicy")',
       '_DISCOVERY_KEYS = ("joinPolicy", "visibility")')]),
    ("D3", BRIDGE, "over",
     "⛔ ABSENT READS AS PUBLIC. Every machine paired before 2026-09-04 carries "
     "neither key, and the safe direction for a discovery setting is the one that "
     "hides",
     [('    # ⛔ ABSENT IS PRIVATE. A machine paired before 2026-09-04 carries neither key,\n'
       '    # and the safe direction for a discovery setting is the one that hides.\n'
       '    return "private"\n',
       '    return "public"\n')]),
    # ⛔⛔ D4 IS A TWO-EDIT MUTANT, AND ITS FIRST SHAPE MEASURED NOTHING. On its own
    # the raw-literal comparison changes nothing — `_owned_device` hands back a
    # DECORATED row and the projection has already resolved the field — and on its
    # own the undecorated row changes nothing either, because `_discovery_of` reads
    # both names anyway. Each half was an equivalent mutant reporting as a survivor.
    #
    # ⭐ TOGETHER THEY ARE EXACTLY THE PRE-WAVE STATE, which is the thing worth
    # asking about: a machine public under the new name, an owner asking for
    # private, and an answer of "it is already private" with no write — on the one
    # surface whose entire job is closing that door.
    ("D4", BRIDGE, "under",
     "⛔⛔ THE TOGGLE IS BACK TO THE PRE-WAVE STATE: a raw row AND a raw literal, "
     "so a machine public under the new name reads private and an owner closing "
     "the door is told it is already shut",
     [('            self._decorate_devices([row], sess.uid,\n                                   prefs.get_selected_device(sess.uid))\n',
       '            row["owned"] = row.get("ownerUid") == sess.uid\n'),
      ('            current = _discovery_of(row)',
       '            current = "public" if row.get("visibility") == "public" else "private"')]),

    ("D5", BRIDGE, "under",
     "⛔ THE PROJECTION STOPS RESOLVING IT, so both clients read the raw field and "
     "the one line that carries all three surfaces through the rename is gone",
     [('                d["visibility"] = _discovery_of(d)\n', '')]),

    # ═══════════ P — a machine that cannot run ══════════════════════════════
    # ⛔⛔ P1 MOVED FROM THE LIST FILTER TO THE RUN GATE, and the move IS the
    # finding. The first build put `pair_state_usable` inside `is_pair_confirmed`,
    # which drops a machine mid-Reset out of `list_devices` entirely — so the
    # person's saved selection stops being a member, reads STALE, is cleared, and
    # the run goes to a DIFFERENT computer without a word. Worse than the defect:
    # the old bug announced "Started" on a machine that would not run; that one ran
    # the research somewhere nobody chose. The browser keeps the machine listed and
    # refuses at the submit, and this is now that.
    ("P1", BRIDGE, "under",
     "⛔⛔ THE CHOSEN MACHINE IS ACCEPTED AGAIN even when it cannot take a run, "
     "so a computer part-way through a Reset is enqueued to and the person is told "
     "\"Started\" while the browser refuses the identical machine",
     [('        if not pair_state_usable(by_id[selected]):\n            return None, "selection_not_ready", False\n', "")]),
    ("P1b", BRIDGE, "under",
     "the auto-pick stops skipping a machine that cannot run, so one is chosen FOR "
     "somebody and then refuses — the same broken promise arrived at without them "
     "even naming it",
     [('    runnable = [d for d in devs if pair_state_usable(d)]\n',
       "    runnable = list(devs)\n")]),

    ("P2", REST, "over",
     "⛔ A LEGACY RECORD IS REFUSED. It carries no pairState at all, and the web "
     "app admits those deliberately — so this refuses machines the app runs on",
     [('    return state is None or state == "active"', '    return state == "active"')]),
    ("P3", REST, "over",
     "any non-empty pairState is admitted, so the two states a Reset produces are "
     "back in the list under a test that only ever supplies \"active\"",
     [('    return state is None or state == "active"', "    return True")]),

    # ═══════════ C — the clock ══════════════════════════════════════════════
    ("C1", BRIDGE, "under",
     "⛔⛔ THE ONLINE CHECK NEVER DECAYS AGAIN. A machine switched off with a fast "
     "clock reads online for as long as the skew lasts, because every negative age "
     "is below the threshold",
     [("    return age < _DEVICE_ONLINE_MS and age > -_HEARTBEAT_FUTURE_TOLERANCE_MS",
       "    return age < _DEVICE_ONLINE_MS")]),
    ("C2", BRIDGE, "over",
     "⛔⛔ THE FUTURE BOUND BECOMES THE OFFLINE THRESHOLD — the exact mistake the "
     "web app made in wave 3, where a working machine 45 s fast read offline "
     "everywhere and every run was refused",
     [("_HEARTBEAT_FUTURE_TOLERANCE_MS = 5 * 60_000",
       "_HEARTBEAT_FUTURE_TOLERANCE_MS = 30_000")]),

    # ═══════════ I — asking by id ═══════════════════════════════════════════
    ("I1", SR, "under",
     "⛔⛔ THE ONLY SHAPE THE APP MINTS IS REFUSED AGAIN, so pasting a real id out "
     "of a browse listing is looked up as a NAME — against a list that drops the "
     "caller's own machines, the ones they share and the private ones",
     [('    if re.fullmatch(r"[0-9a-fA-F]{32}", w):\n        return True\n', '')]),
    ("I2", SR, "over",
     "⛔ THE SEPARATOR RULE GOES, so any eight-letter word is an id again and "
     "\"ask for feedback\" reaches a consent question about disclosing a name",
     [('    if " " in w:\n        return False\n'
       '    if re.fullmatch(r"[0-9a-fA-F]{32}", w):\n        return True\n'
       '    if len(w) < 8:\n        return False\n',
       '    if " " in w or len(w) < 8:\n        return False\n'
       '    return True\n')]),

    # ═══════════ Q — the queue relay ════════════════════════════════════════
    ("Q1", BRIDGE, "under",
     "⛔⛔ THE QUEUE RELAY TRUSTS ITS SOURCE AGAIN — the shape cross-verification "
     "measured on the browse relay, where a whole device row came through with a "
     "plaintext pair code in it",
     [('                "incoming": [{k: d[k] for k in _INCOMING_REQUEST_KEYS if k in d}\n'
       '                             for d in incoming if isinstance(d, dict)]})',
       '                "incoming": incoming})')]),
    ("Q2", BRIDGE, "over",
     "the outgoing half carries the owner's key list, so a uid nobody needs is "
     "published to the person who filed the request",
     [('                "requests": [{k: d[k] for k in _OUTGOING_REQUEST_KEYS if k in d}',
       '                "requests": [{k: d[k] for k in _INCOMING_REQUEST_KEYS if k in d}')]),

    # ═══════════ A — the four filed items ═══════════════════════════════════
    ("A1", POLL, "under",
     "⛔⛔ THE STATE FILE GOES BACK TO A TRUNCATING WRITE. Nothing fails; an "
     "interrupted save leaves a file that parses as nothing, the next tick "
     "baselines SILENTLY, and every phase that completed is never announced",
     [("    tmp = target.with_suffix(\".json.sr-tmp.%d\" % os.getpid())\n"
       "    try:\n"
       "        tmp.write_text(json.dumps(state), \"utf-8\")\n"
       "        os.replace(tmp, target)\n",
       "    try:\n"
       "        target.write_text(json.dumps(state), \"utf-8\")\n")]),
    ("A2", POLL, "over",
     "the temp file is shared across processes, so two ticks interleave and "
     "publish half a state — the trap the jobs writer beside it documents",
     [('    tmp = target.with_suffix(".json.sr-tmp.%d" % os.getpid())',
       '    tmp = target.with_suffix(".json.sr-tmp")')]),
    ("A3", CONNECT, "over",
     "⛔ THE SHIM MATCH GOES BACK TO A PREFIX, so `agent disconnect` deletes a cron "
     "row pointing at a file that is not one of our generated shims and cannot be",
     [("            or bool(_POLL_SHIM_RE.fullmatch(script)))",
       '            or script.startswith("sr_poll_"))')]),
    ("A4", CLI, "under",
     "⛔⛔ THE CONSENT FACTS STOP RIDING THE FLAG on the check route, so an "
     "assistant arriving straight at the second step uploads this file having "
     "shown the person nothing about what is in it",
     [("                for _fact in _agent_log_fact_lines():\n"
       "                    print(_fact)\n", "")]),
    ("A5", SR, "under",
     "⛔ THE ONE DOOR ON THE NO-COMPUTER SCREEN GOES. Every other sentence there is "
     "about picking a computer, so somebody whose problem IS that they have none "
     "is left with nothing to do",
     [('            if body.get("reason") == "no_devices":\n', '            if False:\n')]),

    # ═══════════ H — the hint is an extra, never a gate ═════════════════════
    ("H1", SR, "over",
     "⛔⛔ THE BEST-EFFORT LOOKUP BECOMES A GATE. `/logs/runs` refuses somebody "
     "with no computer, and that person is exactly who this branch exists for — so "
     "the send they came for is refused by a call that was only ever decoration",
     [("    code, body = _get(\"/logs/runs\")\n"
       "    if code != 200 or not body.get(\"owned\"):\n"
       "        return False, \"\"\n",
       "    code, body = _get(\"/logs/runs\")\n"
       "    if code != 200:\n"
       "        raise SystemExit(1)\n"
       "    if not body.get(\"owned\"):\n"
       "        return False, \"\"\n")]),
    ("H2", SR, "over",
     "the machine offer is made to a SHARER, who is refused `--machine` a few "
     "lines away — the circle an earlier wave closed on this branch",
     [("    if code != 200 or not body.get(\"owned\"):\n        return False, \"\"\n",
       "    if code != 200:\n        return False, \"\"\n")]),
]


def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave, so
    a git check would report dirty on every run and a real leftover mutant would
    be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and a
    runner that only asks `returncode == 0` reads that as red — so one typo in the
    selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(filtered: bool) -> bool:
    purge_pycache(AGENT)
    py = str(AGENT / ".venv" / "bin" / "python")
    suites = MINE.split() if filtered else [ALL_SUITES]
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  AGENT, ENV)
    if out == "nothing-collected":
        raise AssertionError("the agent leg collected NO tests — check the selection")
    return out == "green"


def _selected_count() -> int:
    py = str(AGENT / ".venv" / "bin" / "python")
    out = sh([py, "-B", "-m", "pytest", *MINE.split(), "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=AGENT, env=ENV).stdout
    # ⛔ THE SUMMARY LINE IS "N tests collected in 0.09s" — it does not END with
    # "collected", and a parser that assumed it did returned 0 and refused the run.
    # That refusal is the guard working; this is the parser it was guarding.
    import re as _re
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")
    print("scope: THE WHOLE AGENT SUITE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\nRestore that file, then delete\n    {_INFLIGHT}")
        return 2

    if not unfiltered:
        n = _selected_count()
        print(f"the wave's own files collect {n} test(s)")
        if n < MIN_SELECTED:
            print(f"⛔⛔ TOO FEW (need >= {MIN_SELECTED}) — a selection that matches "
                  "nothing exits 5 and scores every mutant killed. Refusing to run.")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(filtered=not unfiltered):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green\n")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then goes
            # red on an import error and the mutant banks a kill it never earned.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            _mark(mid, fname)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests(filtered=not unfiltered)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered)
                if again != killed:
                    flapped = True
                    killed = False
            mark = "✓ killed  " if killed and not flapped else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed or flapped:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    leftover = [f for f in before if before[f] != after[f]]
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    scope = " [whole agent suite]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
