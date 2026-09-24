"""Wave 10.10 (the chat assistant, follow-up) — can the guards see a bare run
verb landing on a run the person did not mean?

Hiding incognito research from the assistant made a bare stop, pause, resume,
retry or skip act on the newest run it could SEE: with an incognito run and an
ordinary run both going, "stop" stopped the ordinary one. The repair has three
parts, and every mutant below breaks one of them:

  the read    — `list_researches` leaves each hidden research's husk (its status
                and whether a card is on it, nothing else) on `unshown`;
  the bridge  — `/updates` says `hiddenLiveRun` when one of those could still be
                meant, and marks each row it CAN show `live` by the same test;
  the client  — a bare verb refuses on `hiddenLiveRun` and offers the `live` rows;
                a named verb is untouched.

The ones that matter most:

  V-*  — ONE VERB'S CONSUMER IGNORES THE RULE, measured against that verb's own
         test alone. A kill against the whole file would prove only that one
         verb's test measures.
  N-*  — the verb refuses even when a run is NAMED, measured against that
         verb's named test alone.
  B3   — the bridge drops the husks on the floor, so the flag is always false.
  H2/H3 — the husk carries the card's words, or the whole record: the hidden
         run's content, held where no one looked.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written. ⛔ ANY SKIP IN THE MEASURED FILE
IS A FAULT: this file has no legitimate skip.

⚠ The tests run as `sys.executable -m pytest` from `agent/`, so `-m` puts this
checkout's `facade` first on sys.path — a worktree measures itself.

    <venv>/bin/python -u .mutants/wave1010_bare_verb_mutants.py
    <venv>/bin/python -u .mutants/wave1010_bare_verb_mutants.py V-stop B3
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

REST = "agent/facade/firestore_rest.py"
BRIDGE = "agent/facade/bridge.py"
SR = "agent/facade/skill/scripts/sr.py"
# What the tests are called from inside `agent/`, where they run.
SUITE = "tests/test_bare_verb_hidden_run_1010.py"
ALL = (SUITE,)


def only(*names: str) -> tuple:
    return tuple(f"{SUITE}::{n}" for n in names)


def refuses(form: str) -> tuple:
    return only(f"test_a_bare_verb_beside_a_hidden_run_refuses_to_guess[{form}]")


def named(form: str) -> tuple:
    return only(f"test_a_named_verb_acts_exactly_as_it_does_with_nothing_hidden[{form}]")


# ── anchors: the client ─────────────────────────────────────────────────────
def GUARD(verb: str, arg: str = "args.runId") -> str:
    return f'    unsure = None if {arg} else _refuse_to_guess(body, "{verb}")'


def NO_GUARD(verb: str) -> str:
    return f'    unsure = _refuse_to_guess(body, "{verb}")'


FLAG_GATE = '    if not (isinstance(body, dict) and body.get("hiddenLiveRun") is True):'
MINE = ('    mine = [r for r in body.get("runs") or [] '
        'if isinstance(r, dict) and r.get("live") is True]')
DIRECTIVE = ('    lines += _agent_directive_block([\n'
             '        f"Do not {verb} any run until the person names one. Never pick one of "\n'
             '        "these runs for them — the run they meant may be one chat cannot manage."])\n')
IF_MINE = ('    if mine:\n'
           '        lines.append("You have a run you can’t manage from chat. '
           'These are the ones I can:")')
NOT_DONE = 'so I haven’t {_NOT_DONE[verb]} anything.'

# ── anchors: the bridge ─────────────────────────────────────────────────────
DOUBT = '    s = status if isinstance(status, str) else ""'
MEANT = '    return bool(card) or s in _ATTENTION_STATUSES or not runview.is_terminal(s)'
HIDDEN_FLAG = ('            out["hiddenLiveRun"] = any(\n'
               '                _could_be_meant(u.get("status"), u.get("card"))\n'
               '                for u in getattr(rows, "unshown", ()))')
ROW_LIVE = ('                    "live": _could_be_meant(status, '
            'isinstance(r.get("pendingDecision"), dict)\n'
            '                                            and bool(r.get("pendingDecision"))),')

# ── anchors: the read ───────────────────────────────────────────────────────
HUSK_RETURN = ('    return {"status": from_value(status) if isinstance(status, dict) else None,\n'
               '            "card": bool(card.get("fields"))}')
HUSK_APPEND = "                out.unshown.append(unshown_husk(d))\n"

MUTANTS = [
    # ══ the client: each verb's consumer ignores the rule ══════════════════
    ("V-stop", "under", "⛔⛔ a bare stop ignores the hidden run and stops the "
     "person's ordinary run — the defect itself",
     [(GUARD("stop"), "    unsure = None")], SR, refuses("stop")),
    ("V-pause", "under", "a bare pause picks the ordinary run",
     [(GUARD("pause"), "    unsure = None")], SR, refuses("pause")),
    ("V-resume", "under", "a bare resume picks the ordinary run",
     [(GUARD("resume"), "    unsure = None")], SR, refuses("resume")),
    ("V-retry", "under", "a bare retry picks the ordinary run and spends on it",
     [(GUARD("retry"), "    unsure = None")], SR, refuses("retry")),
    ("V-skip", "under", "a bare skip resolves the ordinary run's blocker",
     [(GUARD("skip", "args.run"), "    unsure = None")], SR, refuses("skip")),
    ("V-skip-phase", "under", "⛔ `skip video` with no run reconfigures the "
     "ordinary run — bare means no run named, phases or not",
     [(GUARD("skip", "args.run"), "    unsure = None")], SR, refuses("skip video")),

    # ══ the client: a named verb refuses too ═══════════════════════════════
    ("N-stop", "over", "a named stop refuses though the person said which",
     [(GUARD("stop"), NO_GUARD("stop"))], SR, named("stop")),
    ("N-pause", "over", "a named pause refuses",
     [(GUARD("pause"), NO_GUARD("pause"))], SR, named("pause")),
    ("N-resume", "over", "a named resume refuses",
     [(GUARD("resume"), NO_GUARD("resume"))], SR, named("resume")),
    ("N-retry", "over", "a named retry refuses",
     [(GUARD("retry"), NO_GUARD("retry"))], SR, named("retry")),
    ("N-skip", "over", "a named skip refuses",
     [(GUARD("skip", "args.run"), NO_GUARD("skip"))], SR, named("skip")),

    # ══ the client: the refusal itself ═════════════════════════════════════
    ("G1", "over", "⛔ an older bridge that sends no flag reads as yes, so every "
     "bare verb refuses against it",
     [(FLAG_GATE, '    if not (isinstance(body, dict) and '
                  'body.get("hiddenLiveRun") is not False):')], SR, ALL),
    ("G2", "over", "the refusal offers every run it can see, finished ones "
     "included",
     [(MINE, '    mine = [r for r in body.get("runs") or [] if isinstance(r, dict)]')],
     SR, ALL),
    ("G3", "under", "⛔ the assistant is not told to wait, so a chat model shown "
     "four runs may pick one itself",
     [(DIRECTIVE, "")], SR, ALL),
    ("G4", "under", "with nothing else going, it still says 'these are the ones "
     "I can' over an empty list",
     [(IF_MINE, IF_MINE.replace("    if mine:", "    if True:"))], SR, ALL),
    ("G5", "under", "every verb says it has not STOPPED anything",
     [(NOT_DONE, "so I haven’t stopped anything.")], SR, ALL),

    # ══ the bridge ═════════════════════════════════════════════════════════
    ("B1", "under", "⛔⛔ the bridge never says a hidden run is going",
     [(HIDDEN_FLAG, '            out["hiddenLiveRun"] = False')], BRIDGE, ALL),
    ("B2", "over", "any hidden record counts, finished or not, so a record "
     "waiting to be cleared away blocks every bare verb",
     [(HIDDEN_FLAG, '            out["hiddenLiveRun"] = any(\n'
                    '                True\n'
                    '                for u in getattr(rows, "unshown", ()))')], BRIDGE, ALL),
    ("B3", "under", "⛔ the consumer drops the husks the read left it",
     [(HIDDEN_FLAG, HIDDEN_FLAG.replace('getattr(rows, "unshown", ())', '()'))],
     BRIDGE, ALL),
    ("B4", "under", "a visible run with a card on a finished status is not "
     "offered, though a bare retry or skip could mean it",
     [(ROW_LIVE, '                    "live": _could_be_meant(status, False),')],
     BRIDGE, ALL),
    ("C1", "under", "a card no longer counts, so a hidden run waiting on the "
     "person reads as over",
     [(MEANT, '    return s in _ATTENTION_STATUSES or not runview.is_terminal(s)')],
     BRIDGE, ALL),
    ("C2", "under", "a status that asks for the person no longer counts",
     [(MEANT, '    return bool(card) or not runview.is_terminal(s)')], BRIDGE, ALL),
    ("C3", "under", "⛔ when in doubt, NO: a missing or odd status reads as over",
     [(DOUBT, '    s = status if isinstance(status, str) else "completed"')],
     BRIDGE, ALL),
    ("C4", "under", "only queued and ongoing count, so a paused hidden run is "
     "invisible to the rule",
     [(MEANT, '    return bool(card) or s in _ATTENTION_STATUSES or s in ("queued", "ongoing")')],
     BRIDGE, ALL),
    ("C5", "under", "a run that is simply going no longer counts",
     [(MEANT, '    return bool(card) or s in _ATTENTION_STATUSES')], BRIDGE, ALL),

    # ══ the read ═══════════════════════════════════════════════════════════
    ("H1", "under", "the husk never carries a card",
     [(HUSK_RETURN, HUSK_RETURN.replace('bool(card.get("fields"))', 'False'))],
     REST, ALL),
    ("H2", "over", "⛔⛔ the husk carries the card's own words — the hidden "
     "run's content, held by the assistant",
     [(HUSK_RETURN, HUSK_RETURN.replace('bool(card.get("fields"))',
                                        'from_value(fields.get("pendingDecision") or {})'))],
     REST, ALL),
    ("H3", "over", "⛔⛔ the husk is the whole record",
     [(HUSK_RETURN, '    return {**fields_to_dict(doc),\n'
                    '            "status": from_value(status) if isinstance(status, dict) '
                    'else None,\n'
                    '            "card": bool(card.get("fields"))}')], REST, ALL),
    ("H4", "over", "an empty card map counts as a card",
     [(HUSK_RETURN, HUSK_RETURN.replace('bool(card.get("fields"))',
                                        '"pendingDecision" in fields'))], REST, ALL),
    ("H5", "under", "the status is not decoded, so every hidden record reads "
     "as one still going",
     [(HUSK_RETURN, HUSK_RETURN.replace(
         'from_value(status) if isinstance(status, dict) else None', 'status'))],
     REST, ALL),
    ("H6", "under", "⛔⛔ the read drops the hidden run without leaving its husk",
     [(HUSK_APPEND, "")], REST, ALL),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300


def green(tests: tuple) -> bool:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider", "-rs"],
            cwd=AGENT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. And a skip is not a pass here.
    summary = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|error)", ln)]
    if not summary:
        raise AssertionError("no pytest summary line — the run died, it did not fail:\n"
                             + out[-1500:])
    last = summary[-1]
    return ("passed" in last and " failed" not in last and " error" not in last
            and " skipped" not in last)


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweeps load
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    chosen_ids = set(sys.argv[1:])
    selected = [m for m in MUTANTS if not chosen_ids or m[0] in chosen_ids]
    print("baseline… ", end="", flush=True)
    if not green(ALL):
        print("⛔ BASELINE RED (or skipped) — fix the suite before mutating anything.")
        sys.exit(2)
    for sel in sorted({m[5] for m in selected if m[5] != ALL}):
        if not green(sel):
            print(f"⛔ BASELINE RED for the selection {sel}")
            sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    for mid, direction, why, edits, fname, tests in selected:
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
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green(tests):
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
