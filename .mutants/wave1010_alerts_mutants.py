"""Wave 10.10 — can the guards see the clearer alert wording going back to
being switched off, or turning into something that costs the person their
plain alert?

The owner's call (2026-09-23): the AI rewrite of a vague alert is ON for
everyone, billed to the person's own AI key, and `DG_ALERT_AI_COPY=0` turns it
off. Until this wave the switch read only "1 / true / yes" and nothing outside
the tests ever set it, so the feature was built, tested and off everywhere —
and the one test of the default read the value conftest forces, so it would
have passed whatever the code said.

Every mutant below is one way the feature could slide back, or one way turning
it on could hurt the person it is for:

  D1/D2 — the default goes back to OFF (D2 is the old line, verbatim).
  D3    — the off value is read and ignored.
  G1    — the plain card is held back until the rewrite lands, so a failed
          rewrite means NO card.
  G2    — a failed draft re-emits a blank card over the plain one.
  S1    — no deadline: a hung API call keeps its upgrade alive forever.
  S2    — the draft borrows the loop's shared executor again, so a slow call
          queues the phase's own work and holds a finished run open.
  S3    — emit_decision itself waits on the call.
  K1    — the Anthropic key cards (caller-forced blockers) get rewritten,
          which can only drop the instruction and demote the class.
  C1    — the rewrite erases a parked card's countdown.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout being measured:

  <venv>/bin/python -u .mutants/wave1010_alerts_mutants.py
  <venv>/bin/python -u .mutants/wave1010_alerts_mutants.py D1 S2
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_alert_ai_copy_955.py "
          "tests/test_alert_evidence_0919.py "
          "tests/test_alert_unification.py "
          "tests/test_alert_intents.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the switch ─────────────────────────────────────────────────────
READ_SWITCH = ('    val = (os.environ.get("DG_ALERT_AI_COPY") or "").strip().lower()\n'
               '    if val in _ALERT_AI_COPY_OFF_WORDS:\n'
               '        return False')
OFF_WORDS = ('_ALERT_AI_COPY_OFF_WORDS = frozenset({"0", "false", "no", "off", '
             '"disable", "disabled"})')
SWITCH_TAIL = '    return True\n\n\ndef _alert_copy_take_slot('
WARN_GATE = ('    if val and val not in _ALERT_AI_COPY_ON_WORDS and '
             '_alert_ai_copy_warned["value"] != val:')

# ── anchors: the consumer (emit_decision) ───────────────────────────────────
PLAIN_EMIT = ('    emit_event(event_name, phase=phase, agent=agent, **_data)\n'
              '    if mirror is not None:\n'
              '        _persist_pending_decision(mirror)')
CLASS_GATE = '                and recoverability == ALERT_INTENTS[intent]["class"]\n'
SPAWN_ARGS = ('                facts=facts, actions=actions,\n'
              '                auto_skip_deadline=auto_skip_deadline, arm_registry=arm_registry)')
SPAWN_GUARD = '    except Exception as _copy_e:'

# ── anchors: the upgrade ────────────────────────────────────────────────────
DRAFT_WAIT = ('        drafted = await asyncio.wait_for(\n'
              '            _draft_alert_copy_off_loop(intent, base_title, base_details, '
              'facts, actions),\n'
              '            timeout=_ALERT_COPY_DEADLINE_S)')
DRAFT_FAILED = '        return  # brain down / draft rejected → the template stays'
THREAD_CATCH = ('            result = _draft_alert_copy(intent, base_title, base_details, '
                'facts, actions)\n'
                '        except Exception:\n'
                '            result = None')
CLOSED_LOOP = ('        except RuntimeError:\n'
               '            pass                # the loop closed while we drafted — drop it quietly')
LATE_SETTLE = ('        if not fut.done():      # abandoned at the deadline → nobody is waiting\n'
               '            fut.set_result(result)')
PARKED_DEADLINE = '        live_deadline = auto_skip_deadline'
REEMIT_ARM = '            auto_skip_deadline=live_deadline, arm_registry=arm_registry,'

# ── anchors: the burst budget ───────────────────────────────────────────────
SLOT_CHECK = ('    if not _alert_copy_take_slot():\n'
              '        _alert_copy_note(kw.get("intent"), kw.get("agent"),')
LANDED_NOTE = '    _alert_copy_note(intent, agent, "rewritten in plain words")'
SLOT_PRUNE = ('        while _alert_copy_starts and now - _alert_copy_starts[0] >= 60.0:\n'
              '            _alert_copy_starts.popleft()')
CREATE_TASK = '        task = loop.create_task(_upgrade_alert_copy(**kw))'

# ── anchors: no key, no call (the narrator brain the drafter reuses) ────────
HAIKU_NO_KEY = ('        _key = resolve_api_key()\n'
                '        if not _key:\n'
                '            return None, 0')
GEMINI_NO_KEY = ('    if use_gemini and gemini_key and not '
                 '_narrator_primary_should_skip(err_holder):')


MUTANTS = [
    # ══ the switch ═════════════════════════════════════════════════════════
    ("D1", "under", "⛔⛔ the default goes back to OFF: nothing set means no "
     "clearer wording, the exact state this wave exists to end",
     [(SWITCH_TAIL, "    return bool(val) and val in _ALERT_AI_COPY_ON_WORDS\n\n\n"
                    "def _alert_copy_take_slot(")]),
    ("D2", "under", "⛔⛔ the pre-wave switch line, verbatim — the one the old "
     "default test could not tell apart from ON",
     [(READ_SWITCH, '    return (os.environ.get("DG_ALERT_AI_COPY") or "").strip().lower() '
                    'in ("1", "true", "yes")\n'
                    '    val = ""\n'
                    '    if val in _ALERT_AI_COPY_OFF_WORDS:\n'
                    '        return False')]),
    ("D3", "over", "⛔⛔ DG_ALERT_AI_COPY=0 is read and ignored: the one way to "
     "stop spending the person's key stops working",
     [(READ_SWITCH, READ_SWITCH.replace("        return False", "        pass"))]),
    ("D4", "over", "only a literal 0 turns it off; `off` / `false` quietly keep "
     "spending",
     [(OFF_WORDS, '_ALERT_AI_COPY_OFF_WORDS = frozenset({"0"})')]),
    ("D5", "under", "a typo silently cancels the owner's decision for that machine",
     [(SWITCH_TAIL, "    return not val or val in _ALERT_AI_COPY_ON_WORDS\n\n\n"
                    "def _alert_copy_take_slot(")]),
    ("D6", "noise", "an unreadable value warns on EVERY alert instead of once",
     [(WARN_GATE, "    if val and val not in _ALERT_AI_COPY_ON_WORDS:")]),
    ("D7", "noise", "a value we understand is warned about as unreadable",
     [(WARN_GATE, '    if val and _alert_ai_copy_warned["value"] != val:')]),

    # ══ the plain card always reaches the person ═══════════════════════════
    ("G1", "under", "⛔⛔ the plain card is held back for the rewrite, so a "
     "failed or slow rewrite means the person gets NO card",
     [(PLAIN_EMIT, '    if _ai_upgraded or not ALERT_INTENTS.get(intent, {}).get("ai_upgrade"):\n'
                   '        emit_event(event_name, phase=phase, agent=agent, **_data)\n'
                   '    if mirror is not None:\n'
                   '        _persist_pending_decision(mirror)')]),
    ("G2", "under", "⛔⛔ a failed draft re-emits a BLANK card over the plain one",
     [(DRAFT_FAILED, '        drafted = ("", "")')]),
    ("G3", "under", "⛔ an error starting the rewrite escapes into the phase "
     "that raised the card",
     [(SPAWN_GUARD, "    except ZeroDivisionError as _copy_e:")]),
    ("G4", "under", "a draft that raises kills its thread, so the upgrade sits "
     "out the whole deadline and the thread's traceback lands on stderr",
     [(THREAD_CATCH, THREAD_CATCH.replace("        except Exception:",
                                          "        except ZeroDivisionError:"))]),

    # ══ nothing waits on the call ══════════════════════════════════════════
    ("S1", "under", "⛔⛔ no deadline: a hung API call keeps its upgrade alive "
     "and its late answer rewrites a card the person read long ago",
     [(DRAFT_WAIT, "        drafted = await _draft_alert_copy_off_loop("
                   "intent, base_title, base_details, facts, actions)")]),
    ("S2", "under", "⛔⛔ the draft borrows the loop's shared executor again — "
     "a slow call queues the phase's own to_thread work and holds a finished "
     "run's asyncio.run() open",
     [(DRAFT_WAIT, "        drafted = await asyncio.wait_for(\n"
                   "            asyncio.to_thread(_draft_alert_copy, intent, base_title, "
                   "base_details, facts, actions),\n"
                   "            timeout=_ALERT_COPY_DEADLINE_S)")]),
    ("S3", "under", "⛔⛔ emit_decision itself waits on the API call before the "
     "phase can move on",
     [(CREATE_TASK, '        _draft_alert_copy(kw["intent"], kw["base_title"], '
                    'kw["base_details"], kw["facts"], kw["actions"])\n'
                    "        task = loop.create_task(_upgrade_alert_copy(**kw))")]),
    ("S4", "noise", "a draft that outlives its loop raises on the closed loop",
     [(CLOSED_LOOP, CLOSED_LOOP.replace("except RuntimeError:", "except ZeroDivisionError:"))]),
    ("S5", "noise", "a late answer is set on an abandoned future and raises "
     "inside the loop",
     [(LATE_SETTLE, "        fut.set_result(result)")]),

    # ══ a burst ════════════════════════════════════════════════════════════
    ("B1", "over", "⛔⛔ no budget: every card in a burst (or a runaway loop of "
     "them) makes its own paid call",
     [(SLOT_CHECK, '    if False:\n'
                   '        _alert_copy_note(kw.get("intent"), kw.get("agent"),')]),
    ("B2", "under", "the budget never refills, so after six rewrites the "
     "process never rewrites again",
     [(SLOT_PRUNE, "        while False:\n            _alert_copy_starts.popleft()")]),
    ("B3", "under", "the window is a hair longer than a minute",
     [(SLOT_PRUNE, SLOT_PRUNE.replace(">= 60.0", "> 60.0"))]),

    # ══ the cards it must not touch, and what it must keep ═════════════════
    ("K1", "over", "⛔⛔ the Anthropic key cards are rewritten — the drafter may "
     "not name API keys, so the rewrite drops the fix, and the re-emit demotes "
     "the blocker to recoverable",
     [(CLASS_GATE, "")]),
    ("K2", "under", "inverted: ONLY the forced blockers are rewritten",
     [(CLASS_GATE, CLASS_GATE.replace("==", "!="))]),
    ("C1", "under", "⛔ the rewrite erases a parked card's countdown while the "
     "park still skips the agent on time",
     [(PARKED_DEADLINE, '        live_deadline = _pending_decisions.get(decision_id, {})'
                        '.get("deadline")')]),
    ("C2", "over", "the rewrite arms the registry for a card whose own wait is "
     "its firer — two timers, one card",
     [(REEMIT_ARM, "            auto_skip_deadline=live_deadline,")]),
    ("C3", "under", "the spawn stops carrying the card's deadline, so the "
     "upgrade cannot keep it",
     [(SPAWN_ARGS, "                facts=facts, actions=actions)")]),

    # ══ the line an end-to-end run greps for ═══════════════════════════════
    ("L1", "under", "a rewrite lands and says nothing, so the owner's run has "
     "no way to tell the feature is on",
     [(LANDED_NOTE, "    pass")]),

    # ══ no key, no call ════════════════════════════════════════════════════
    ("N1", "over", "with no Anthropic key the fallback still builds a client "
     "and calls",
     [(HAIKU_NO_KEY, HAIKU_NO_KEY.replace("        if not _key:", "        if False:"))]),
    ("N2", "over", "with no Gemini key the primary still posts, keyless",
     [(GEMINI_NO_KEY, "    if use_gemini and not _narrator_primary_should_skip(err_holder):")]),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q",
             "-p", "no:cacheprovider"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. No summary at all means the
    # suite never ran — a fault, not a kill (a harness that cannot load looks
    # exactly like one that killed everything).
    summary = re.findall(r"^.*\b\d+ (?:passed|failed|errors?)\b.* in [\d.]+s.*$",
                         out, re.M)
    if not summary:
        raise AssertionError("no pytest summary line — the suite did not run: "
                             + out[-400:])
    last = summary[-1]
    return "passed" in last and "failed" not in last and "error" not in last


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`.
if __name__ == "__main__":
    MUTANTS = [(*m, RESEARCH)[:5] for m in MUTANTS]
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    try:
        base_ok = green()
    except AssertionError as e:
        print(f"⛔ BASELINE FAULT — {e}")
        sys.exit(2)
    if not base_ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, why, edits, fname in selected:
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
