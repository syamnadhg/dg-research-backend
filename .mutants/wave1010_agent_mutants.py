"""Wave 10.10 (the chat assistant) — can the guards see the assistant listing
an incognito research again?

The promise is "nothing of an incognito run stays in Super Research". The chat
assistant reads the person's researches through ONE call,
`FirestoreRest.list_researches`, and every list it shows is built on it: the
run list, `/updates` (which `sr list`, `sr status` and the bare verbs read
without `via=agent`), and the send-logs picker's titles. Every mutant below is a
way that read could go back to showing a run that keeps nothing, or start hiding
somebody's ordinary research.

The ones that matter most are the quiet ones:

  F1-*  — the filter is gone, measured against EACH CONSUMER'S OWN TEST ALONE.
          One kill against the whole file would prove only that one of them
          measures; this proves every one does.
  F2    — the filter reads a FIELD instead of the document's path, so a record
          whose `id` field says anything is believed.
  P1    — the predicate answers False for everything. Nothing about an
          ordinary research fails, and the feature is decoration.
  P3    — `match` instead of `fullmatch`: Python's `$` matches before a final
          newline and the web app's does not, so the two disagree.
  W1    — the parity pin compares the agent with ITSELF and reports agreement
          it never checked.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⛔ ANY SKIP IN THE MEASURED FILE IS A FAULT. This file has no legitimate skip,
so a skip is the pin going quiet — the baseline refuses to start on one.

⚠ The tests run as `sys.executable -m pytest` from `agent/`, so `-m` puts this
checkout's `facade` first on sys.path — a worktree measures itself rather than
the editable install the venv points at.

    <venv>/bin/python -u .mutants/wave1010_agent_mutants.py
    <venv>/bin/python -u .mutants/wave1010_agent_mutants.py P3 W1
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
PIN = "agent/tests/test_incognito_hidden_1010.py"
# What the tests are called from inside `agent/`, where they run.
SUITE = "tests/test_incognito_hidden_1010.py"
ALL = (SUITE,)


def only(name: str) -> tuple:
    return (f"{SUITE}::{name}",)


# ── anchors: the read ───────────────────────────────────────────────────────
# ⭐ The husk line sits inside the filter since the bare-verb follow-up: what is
# left out is counted (`ResearchList.unshown`) — every replacement keeps it, so
# each mutant still changes only what it says it changes.
HUSK = "                out.unshown.append(unshown_husk(d))\n"
FILTER = ("            if is_incognito_research(rid):\n"
          + HUSK +
          "                continue\n")

# ── anchors: the rule ───────────────────────────────────────────────────────
PATTERN = '_INCOGNITO_ID_RE = re.compile(r"^incog_[0-9]{13}_[0-9]{1,6}$")'
PREDICATE = ("    return isinstance(research_id, str) and "
             "_INCOGNITO_ID_RE.fullmatch(research_id) is not None")

# ── anchors: the parity pin itself ──────────────────────────────────────────
LIFT_RETURN = '    return ns["_INCOGNITO_ID_RE"], ns["_is_incognito_research"]'
LIFT_REFUSAL = ("    if len(keep) != 2:\n"
                "        raise AssertionError(")
DISAGREE = "            if bool(machine_rule(rid)) != is_incognito_research(rid)]"

MUTANTS = [
    # ══ the read every list goes through ═══════════════════════════════════
    ("F1", "under", "⛔⛔ the list keeps every research, so the assistant shows "
     "an incognito run's title and topic again",
     [(FILTER, "")], REST, ALL),
    ("F1-list", "under", "the filter is gone — does the client's own test see it?",
     [(FILTER, "")], REST,
     only("test_the_list_leaves_out_every_incognito_research_and_nothing_else")),
    ("F1-researches", "under", "the filter is gone — does the run list route's "
     "test see it?",
     [(FILTER, "")], REST, only("test_the_run_list_route_never_carries_it")),
    ("F1-updates", "under", "⛔ the filter is gone — does the test of the route "
     "the plan called safe see it?",
     [(FILTER, "")], REST,
     only("test_the_updates_route_never_carries_it_without_via_agent")),
    ("F1-active", "under", "the filter is gone — do the active runs see it?",
     [(FILTER, "")], REST, only("test_the_active_runs_never_include_it")),
    ("F1-logs", "under", "the filter is gone — does the send-logs picker lend "
     "the run its title again?",
     [(FILTER, "")], REST,
     only("test_its_held_logs_keep_their_row_and_lose_their_title")),
    ("F1-sr-list", "under", "⛔⛔ the filter is gone — does asking the "
     "assistant for your researches show it?",
     [(FILTER, "")], REST,
     only("test_asking_the_assistant_for_your_researches_never_shows_it")),
    ("F1-sr-status", "under", "the filter is gone — does a bare status pick "
     "the incognito run and print its topic?",
     [(FILTER, "")], REST,
     only("test_a_bare_status_reports_the_newest_run_it_can_show")),
    ("F2", "under", "⛔ the filter believes a field on the record instead of "
     "its path, which is the one signal the rules and the web app read",
     [(FILTER, "            if is_incognito_research(fields_to_dict(d).get(\"id\")):\n"
               + HUSK + "                continue\n")], REST, ALL),
    ("F3", "over", "the filter is a prefix test, so `incog_notes` — somebody's "
     "ordinary research — vanishes from their lists",
     [(FILTER, "            if rid.startswith(\"incog\"):\n"
               + HUSK + "                continue\n")], REST, ALL),
    ("F4", "over", "the list stops at the first incognito row, so every older "
     "ordinary research goes with it",
     [(FILTER, "            if is_incognito_research(rid):\n"
               + HUSK + "                break\n")], REST, ALL),

    # ══ the rule ═══════════════════════════════════════════════════════════
    ("P1", "under", "⛔⛔ the predicate answers False for everything",
     [(PREDICATE, "    return False")], REST, ALL),
    ("P2", "over", "the predicate is a bare prefix, the shape both other "
     "copies' comments warn against",
     [(PREDICATE, '    return isinstance(research_id, str) and '
                  'research_id.startswith("incog_")')], REST, ALL),
    ("P3", "over", "⛔ `match` instead of `fullmatch`, so an id with a newline "
     "on the end is hidden here and shown by the web app",
     [(PREDICATE, "    return isinstance(research_id, str) and "
                  "_INCOGNITO_ID_RE.match(research_id) is not None")], REST, ALL),
    ("P4", "under", "the string check is gone, so a missing id raises instead "
     "of reading as ordinary",
     [(PREDICATE, "    return _INCOGNITO_ID_RE.fullmatch(research_id) is not None")],
     REST, ALL),
    ("R1", "over", "the counter takes seven digits",
     [(PATTERN, PATTERN.replace("{1,6}", "{1,7}"))], REST, ALL),
    ("R2", "over", "the timestamp takes twelve to fourteen digits",
     [(PATTERN, PATTERN.replace("{13}", "{12,14}"))], REST, ALL),
    ("R3", "over", "`\\d` for `[0-9]`, which in Python takes every script's "
     "digits and in JavaScript takes only ASCII",
     [(PATTERN, PATTERN.replace("[0-9]", r"\d"))], REST, ALL),
    ("R4", "under", "the counter stops at five digits, so the web app's "
     "999999th incognito chat of a millisecond is listed",
     [(PATTERN, PATTERN.replace("{1,6}", "{1,5}"))], REST, ALL),

    # ══ the parity pin itself ══════════════════════════════════════════════
    # ⛔ THESE MUTATE THE TEST FILE, which is the only place their decision
    # lives: a cross-copy pin that cannot say "I found nothing" is a pin that
    # reports agreement it never checked.
    ("W1", "under", "⛔⛔ the lifter ignores research.py and hands back the "
     "agent's own rule, so the parity pin compares the agent with itself",
     [(LIFT_RETURN, "    return firestore_rest._INCOGNITO_ID_RE, is_incognito_research")],
     PIN, ALL),
    ("W2", "under", "⛔ a research.py that moved its rule turns the pin into a "
     "SKIP, which the gate reads as fine",
     [(LIFT_REFUSAL, "    if len(keep) != 2:\n"
                     "        pytest.skip(")], PIN, ALL),
    ("W3", "under", "the comparison asks the agent twice, so no drift in "
     "research.py can ever be seen",
     [(DISAGREE, "            if bool(is_incognito_research(rid)) != "
                 "is_incognito_research(rid)]")], PIN, ALL),
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
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. And a skip is not a pass here:
    # nothing in the measured file may skip.
    summary = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|error)", ln)]
    if not summary:
        raise AssertionError("no pytest summary line — the run died, it did not fail:\n"
                             + out[-1500:])
    last = summary[-1]
    return ("passed" in last and " failed" not in last and " error" not in last
            and " skipped" not in last)


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    chosen_ids = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green(ALL):
        print("⛔ BASELINE RED (or skipped) — fix the suite before mutating anything.")
        sys.exit(2)
    for _m in MUTANTS:
        if _m[5] != ALL and not green(_m[5]):
            print(f"⛔ BASELINE RED for {_m[0]}'s own selection {_m[5]}")
            sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not chosen_ids or m[0] in chosen_ids]
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
