"""Mutation harness for stretch 3B — telling a machine's OWNER that a sharer
started a run on it, from the agent.

⛔⛔ THE GAP, MEASURED. The notice already existed and was correct: the web app
re-reads the device document, confirms the caller really is a sharer, refuses
`self`, and composes every word. Nothing was wrong with it. Its ONE caller was
the sharer's BROWSER, at submit time. So a sharer starting a run from chat, from
a terminal, or from a fleet box notified nobody — and a fleet box is exactly
where a co-tenant is most likely to be a sharer. The backend did not send it
either; unlike phase notices there is no second dispatcher to fall back on.
Owner, 2026-08-25: "I'm not getting notified in spite of being the owner."

⭐⭐ WHY THE AGENT MAY SEND IT AT ALL: this process is signed in as the ACTUAL
HUMAN, so the route sees a genuine caller and can name them without trusting
anything a machine supplied. The machine-side alternative covers strictly more
paths and was rejected for that reason — a machine has no name or email of its
own, so the notice would read "Someone started a research" unless the route
began trusting an identity a machine handed it, on the one path that writes into
somebody ELSE's inbox. O3 restores that design so the refusal is measured.

⛔⛔ AND THERE IS DELIBERATELY NO OWNERSHIP CHECK ON THIS SIDE. The plan said "the
agent already knows: `owned` comes back on the device row it just read." Measured
FALSE: `_enqueue_research_run` takes `device_id: str` and nothing else,
`_resolve_device` returns an explicit id before reading anything, and `owned` is
not a Firestore field at all — `_decorate_devices` grafts it on and no run-start
path calls it. The concern behind the plan (an owner's own runs burning the
owner's own 20/hour budget) is a fault in the ROUTE's ordering and is fixed
there, where it covers every caller.

⭐ THE SHARPEST MUTANTS HERE:
  O4 — the notice moves in FRONT of the enqueue, so it can describe a run that
       never started and send the owner to a chat that does not exist.
  O5 — the guard around it goes. In production the daemon thread swallows the
       exception anyway, so this only fails where `_spawn` is run inline — which
       is exactly where it was caught. A safety property that depends on its
       dispatcher is not a property.
  O6 — it stops being spawned, so a courtesy notice's 20-second timeout is added
       to the latency of starting a run.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor — it measured nothing while reporting a kill,
which this repo has now shipped twice.

    .venv/bin/python .mutants/agent_owner_notify_0826_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The run-start path and its neighbours. `test_bridge_device.py` owns the notice;
# the other three come along because the mutants edit a shared helper, and a
# harness that only ran the new file would call collateral damage a kill.
AGENT_SUITES = ("tests/test_bridge_device.py "
                "tests/test_bridge_routes.py "
                "tests/test_sr_client.py "
                "tests/test_remote_autopoll.py")

BRIDGE = "agent/facade/bridge.py"
MUTATED_FILES = (BRIDGE,)

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ O — the notice itself ══════════════════════════════════════
    ("O1", BRIDGE, "under",
     "⛔⛔ THE GAP ITSELF: nothing is sent, so a sharer starting a run from chat, "
     "a terminal or a fleet box notifies nobody — which is the reported state",
     # ⛔ RE-POINTED 2026-08-26 — the second time this file's compile gate has
     # earned its keep. `_spawn` gained a try/except of its own, so deleting the
     # call alone left `try:` with an empty body: a mutant that does not parse,
     # which measures nothing and WOULD have reported a kill without the gate,
     # because the suite goes red on an import error rather than on behaviour.
     # The whole block goes now.
     [("    try:\n        _spawn(_notify_device_owner_of_run, sess, device_id, rid, topic)\n"
       "    except Exception as e:  # noqa: BLE001 — a courtesy notice, never a failure\n"
       "        log.info(\"owner-notify %s: not dispatched (%s)\", rid, type(e).__name__)\n",
       "")]),
    ("O2", BRIDGE, "over",
     "⛔ the kind is misspelt, so the route refuses it with a 400 on its merits "
     "and the notice silently never lands — the literal is a wire contract with "
     "a constant that lives in the other repo",
     [('            "kind": "sharerRunStarted",', '            "kind": "sharerRunStart",')]),
    ("O3", BRIDGE, "over",
     "⛔⛔ THE REJECTED MACHINE-SIDE DESIGN: an identity is supplied from this "
     "side, which is the change to the security argument the decision refused — "
     "a machine asserting who a person is, on the one path that writes into "
     "somebody else's inbox",
     [('            "topic": topic,',
       '            "topic": topic,\n            "callerLabel": sess.email,')]),
    # ⛔ `why` CORRECTED 2026-08-26: it said the notice "MOVES" in front of the
    # enqueue, but the edit PREPENDS one and leaves the original in place, so the
    # mutant is a double-send whose first copy fires before the run is real. The
    # harm it demonstrates is the same and the description was not.
    ("O4", BRIDGE, "over",
     "⛔⛔ A SECOND NOTICE IS SPAWNED IN FRONT OF THE ENQUEUE, so one of the two "
     "announces a run that never started and sends the owner to a chat that "
     "does not exist",
     [("    try:\n        qid = fs.enqueue_start(",
       "    _spawn(_notify_device_owner_of_run, sess, device_id, rid, topic)\n"
       "    try:\n        qid = fs.enqueue_start(")]),
    # ⛔⛔ THIS MUTANT WAS A HARNESS FAULT ON ITS FIRST RUN — `try:` → `if True:`
    # leaves the `except` clause dangling, so the file did not parse and the
    # compile gate reported "! ERROR" rather than a verdict. A mutant that does
    # not parse measures nothing and, without that gate, would have reported a
    # KILL: the suite goes red on an import error rather than on the behaviour.
    # The guard is removed properly now — the call is made directly and the
    # whole try/except goes with it.
    ("O5", BRIDGE, "over",
     "⛔⛔ THE NOTICE'S OWN GUARD GOES, so whether a raising notice fails a "
     "started run depends entirely on the dispatcher putting it on a thread — "
     "the exact hole a test found on 2026-08-26",
     [("    try:\n        _notify_device_owner_of_run_inner(sess, device_id, research_id, topic)\n"
       "    except Exception as e:  # noqa: BLE001 — a courtesy notice, never a failure",
       "    if True:\n        _notify_device_owner_of_run_inner(sess, device_id, research_id, topic)\n"
       "    if False:\n        e = Exception()")]),
    ("O6", BRIDGE, "over",
     "⛔ IT STOPS BEING SPAWNED, so a courtesy notice's 20-second timeout is "
     "added to the latency of every run start",
     [("    _spawn(_notify_device_owner_of_run, sess, device_id, rid, topic)",
       "    _notify_device_owner_of_run(sess, device_id, rid, topic)")]),
    # ⛔ `why` CORRECTED 2026-08-26: no queue id is involved — the edit TRUNCATES
    # the research id to eight characters.
    ("O7", BRIDGE, "over",
     "⛔ the research id is truncated, so the dedup key names a run the owner "
     "cannot open and the route's id validation may refuse it outright",
     [("            \"researchId\": research_id,", "            \"researchId\": research_id[:8],")]),
    ("O8", BRIDGE, "over",
     "⛔ the topic is dropped, so the same event reads differently depending on "
     "which client started the run — the route picks a bodiless sentence when "
     "there is no subject",
     [('            "topic": topic,\n', "")]),
    ("O9", BRIDGE, "over",
     "⛔ it posts to the wrong route, so every notice 404s and the log says "
     "nothing was delivered — indistinguishable from an owner's own quiet run",
     [('    status, body = _fe_api_post(sess, "/api/notify", {',
       '    status, body = _fe_api_post(sess, "/api/notifyDevice", {')]),
    # ⛔ `why` CORRECTED 2026-08-26: the mutated code takes the `else` branch and
    # logs "delivered" — it does not warn. It was also an unkillable survivor
    # until this wave added `caplog` assertions on both branches.
    ("O10", BRIDGE, "over",
     "⛔⛔ AN OWNER'S QUIET NO-OP IS LOGGED AS 'delivered', so the one question "
     "this log exists to answer — did the owner actually get told — is answered "
     "wrongly on the commonest path there is",
     [('        why = body.get("skipped")', '        why = None')]),
]

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# A claimed survivor is re-run before it is believed: this venv carries an
# editable install of another checkout of these same module names and has
# produced phantom survivors before.
SURVIVOR_CONFIRMATIONS = 3


def sh(cmd: list[str], *, cwd=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                          env=env or ENV)


def purge_pycache() -> None:
    for d in (ROOT / "agent").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES,
              "agent/tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    purge_pycache()
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    return sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
               "-q", "-p", "no:cacheprovider"],
              cwd=ROOT / "agent", env=agent_env).returncode == 0


def main() -> int:
    # An optional id filter, for re-checking the mutants a previous run left
    # standing without paying for the whole sweep again.
    #
    # ⛔ A FILTERED RUN IS NOT A RESULT. It proves the ids it names and nothing
    # else, so it says so in its own output rather than printing a score that
    # would be quoted later as if the sweep had run. The full run is what a
    # wave is measured by.
    only = {a.strip() for a in sys.argv[1:] if a.strip()}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — this is a spot check, "
              f"not a score for the wave.")

    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in selected:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                # ⛔ EXACTLY ONE. A stale anchor measured nothing and would still
                # report a kill; a duplicated one mutates a place nobody meant.
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            # ⛔⛔ A MUTANT THAT DOES NOT PARSE MEASURES NOTHING, and it reports
            # a kill — the suite goes red on an import error rather than on the
            # behaviour the mutant was written about, so the harness records
            # coverage that does not exist. Mis-indented anchors are the way
            # this happens in practice: a replacement whose leading whitespace
            # differs from the anchor's still substring-matches, and produces a
            # file that looks edited and is unparseable.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                killed = not run_tests()
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed "
          f"({over} over-corrections){label}")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
