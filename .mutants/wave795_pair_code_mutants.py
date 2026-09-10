"""Mutation harness — THE PAIR CODE, THE PROJECTION, AND THE CLAIMS
(wave 7.9-5, items D1..D4, 2026-09-09. SECOND BUILD, AFTER CROSS-VERIFY.)

⛔⛔ THE FIRST BUILD SCORED 52/52 AND WAS WRONG. Cross-verify then found ~60
defects, about 25 of them in the code and guards this wave had just written —
including a bulk-request gate that refused REAL MACHINE NAMES on six verbs (96
measured phrases), two client sentences that were false, a contract bullet whose
replacement was also false, a restore guard that could not fail, and exact-key-set
assertions that compared the emitted row against the constant they were meant to
police, so a widening was invisible.

⭐⭐ SO THESE MUTANTS COME FROM THE FINDINGS, NOT FROM MY REPAIR LIST — the
owner's call, 09-09, and the reason is precise: the first harness passed because
its mutants and its guards were written from the same wrong mental model. Several
below are the cross-verify measurement restored verbatim as a mutant (P5 is the
exact widening that left 16/16 green; U6 is the false "on the device's own screen"
sentence; C2 is the false replacement bullet; G1 is the class-scoped snapshot).

⛔⛔ THE BULK GATE IS NOT IN THIS WAVE ANY MORE. It was split out to 7.9-5b and
reverted, because it regressed real machine names and nothing publishes before
stretch 8 — so the original defect reaches no user in the meantime while the
regression would have been wrong the day it shipped. Every measured finding about
it is in WAVES.md; none of it is scored here.

⛔⛔ THE SHARPEST MUTANTS HERE:
  P3  — the prune builds a NEW dict and returns it instead of narrowing in place.
        It compiles, passes a test written against the return value, and leaves
        all three routes emitting the row they still hold a reference to. This is
        the version of the fix the plan asked for.
  P5  — cross-verify's own widening, verbatim: `logins`, `workers`, `queueOwners`.
        It published which AI accounts are signed in on somebody's machine plus
        other people's uids and run ids, and left the whole file GREEN.
  P6  — the browse relay loses its prune and passes the web app's array through
        byte for byte. Measured with a stubbed upstream: a plaintext pair code
        came back whole while every other device route returned nothing.
  U6  — the false fallback restored. The route's own comment says the machine
        cannot show a rotated code; the sentence sent people to read a dead one.
  U8  — `--json` drops the warning, so the credential goes out bare to a caller
        that is still read by a person.
  T10 — the unlink goes back to the shared 15s timeout, shorter than the route's
        own 30s budget: the bridge gives up while the route SUCCEEDS and the only
        copy of the new code is discarded. T11 is the wrong fix for it.
  C2  — the contract's REPLACEMENT bullet, which was also false. `device-visibility`
        PATCHes the device document directly and the handler's docstring says so.
  G1  — the restore guard goes back to a class-scoped snapshot requested by one
        test, so nothing runs between snapshot and comparison and it cannot fail.
  G3  — the f-string goes back to PEP 701. It PARSES on 3.13, so all 7121 root
        tests stay green and only the correctness lint floor catches it.
  G5  — the TypeScript blanker goes back to Python's tokenizer, which raises on a
        .ts file and returns it UNTOUCHED, so the drift guard searches 222 live
        comment lines while claiming they are blanked.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ TWO LEGS. This wave repaired ROOT-suite things — the f-string that had CI's
lint floor red for six pushes, the harness guard, the lint guard — and an
agent-only runner would have scored all three as killed without executing one
test that could see them. The leg is derived from the mutated file's path.

⛔⛔ SCORED AGAINST THIS WAVE'S OWN GUARDS. Pass --unfiltered for the other
question — whether the TREE catches it — which is deliberately separate.

    .venv/bin/python .mutants/wave795_pair_code_mutants.py
    .venv/bin/python .mutants/wave795_pair_code_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import re as _re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

CLI = "agent/facade/cli.py"
BRIDGE = "agent/facade/bridge.py"
SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"
INIT = "agent/facade/__init__.py"
MATRIX = "agent/TESTMATRIX.md"
RESEARCH = "research.py"
HGUARD = "tests/test_mutation_harness_guards_0827.py"
CONFTEST = "agent/tests/conftest.py"
LINTG = "tests/test_lint_correctness_floor.py"
OURS = (CLI, BRIDGE, SR, SKILL, INIT, MATRIX, RESEARCH, HGUARD, CONFTEST, LINTG)

# ⭐ THE GUARDS THIS WAVE ADDED OR CORRECTED, per leg. `test_sr_client` and
# `test_sr_skip_agents` are here because this wave rewrote assertions inside
# them that were pinning the false sentence and pinning a word in the copy
# instead of the routing — those corrections are this wave's work and a score
# that skipped them would be scoring half the change.
MINE_AGENT = ("tests/test_device_projection_795.py "
              "tests/test_unlink_copy_795.py "
              # ⭐⭐ THE TWO FILES THE FIRST HARNESS RUN DEMANDED. Twelve mutants
              # survived round one and eleven were one gap in two shapes: the
              # TERMINAL's device commands were never driven (so the whole
              # pair-code print block was deletable, and `_err(res)` could go
              # back on screen), and the four DOC CLAIMS were corrected without
              # a single assertion pinning them. Both files exist because
              # mutants asked for them, which is the harness working.
              "tests/test_cli_device_commands_795.py "
              "tests/test_claims_stay_true_795.py "
              # ⭐⭐ THE FILE THE THIRD RUN DEMANDED. Eleven mutants survived
              # it, every one a fix made in response to cross-verify and then
              # left unpinned — the third wave running with that pattern, but
              # the first caught BEFORE the push, because the mutants came
              # from the findings rather than from my repair list.
              "tests/test_crossverify_fixes_795.py "
              "tests/test_route_matrix_795.py "
              "tests/test_fe_json_792.py "
              "tests/test_public_devices_792.py "
              "tests/test_bridge_device.py "
              "tests/test_sr_client.py "
              "tests/test_sr_skip_agents.py "
              "tests/test_skill_commands_resolve.py "
              "tests/test_routing_794.py "
              "tests/test_owner_verbs_793.py "
              "tests/test_chat_public_792.py "
              "tests/test_chat_owner_793.py")
MINE_ROOT = ("tests/test_lint_correctness_floor.py "
             "tests/test_mutation_harness_guards_0827.py "
             "tests/test_mutation_harness_anchors.py")
MIN_SELECTED_AGENT = 700
MIN_SELECTED_ROOT = 25

ALL_AGENT = "tests/"
ALL_ROOT = "tests/"

# Files whose repairs only the ROOT suite can see.
# ⛔ `CONFTEST` IS AN AGENT FILE even though it is a test file; only `research.py`,
# the harness guard and the lint guard are read by the ROOT suite.
ROOT_LEG_FILES = (RESEARCH, HGUARD, LINTG)

# ⛔⛔ G3 IS RUN ON ITS OWN, AND THAT IS A SCHEDULING DECISION, NOT A WEAKENING.
# It is the only mutant that touches `research.py`, and listing that file here
# LOCKS IT for the whole run — which blocks all machine-wheel work, in the same
# repo, with no "different repository" escape. 2026-09-09: that lock was the
# thing stopping the Gemini fix proceeding in parallel, so G3 is excluded from
# the default selection and run explicitly:
#
#     .venv/bin/python .mutants/wave795_pair_code_mutants.py G3
#
# ⭐ Its verdict is not lost: G3 was KILLED in both run 3 and run 4, and it is
# re-run alone before the wave is recorded. ⛔ A future wave that touches
# `research.py` must put it back in the default selection.
_SOLO = {"G3"}

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    ('P1', BRIDGE, 'under',
     '⛔⛔ THE PRUNE GOES. All three own-machine emitters hand back the whole device document again, plaintext pair code and membership included',
     [('                for k in [k for k in d if k not in _DEVICE_PUBLIC_KEYS]:\n                    del d[k]\n', '')]),
    ('P2', BRIDGE, 'over',
     "⛔⛔ THE PRUNE RUNS BEFORE THE FLAGS, so `owned` is derived from an `ownerUid` already deleted and every machine reads as somebody else's",
     [('            for d in devs:\n                d["owned"] = d.get("ownerUid") == uid', '            for d in devs:\n                for k in [k for k in d if k not in _DEVICE_PUBLIC_KEYS]:\n                    del d[k]\n                d["owned"] = d.get("ownerUid") == uid')]),
    ('P3', BRIDGE, 'over',
     '⛔⛔ THE PRUNE RETURNS A NEW LIST INSTEAD OF NARROWING IN PLACE — the version the plan asked for. It compiles, satisfies a test written against the return value, and leaves the three callers that read the ORIGINAL variable leaking',
     [('                for k in [k for k in d if k not in _DEVICE_PUBLIC_KEYS]:\n                    del d[k]\n            return devs', '                pass\n            return [{k: d[k] for k in _DEVICE_PUBLIC_KEYS if k in d} for d in devs]')]),
    ('P4', BRIDGE, 'over',
     '⛔⛔ `pairCode` JOINS THE ALLOW-LIST — the one field that hands over the machine',
     [('_DEVICE_PUBLIC_KEYS = ("id", "name", "hostname", "machineName",\n                       "owned", "selected", "online", "visibility")', '_DEVICE_PUBLIC_KEYS = ("id", "name", "hostname", "machineName",\n                       "owned", "selected", "online", "visibility", "pairCode")')]),
    ('P5', BRIDGE, 'over',
     "⛔⛔ CROSS-VERIFY'S OWN WIDENING, verbatim: `logins`, `workers` and `queueOwners` join the list, publishing which AI accounts are signed in on the machine plus other people's uids and run ids. It left 16/16 GREEN before the expected set became a literal",
     [('                       "owned", "selected", "online", "visibility")', '                       "owned", "selected", "online", "visibility",\n                       "logins", "workers", "queueOwners")')]),
    ('P6', BRIDGE, 'under',
     "⛔⛔ THE BROWSE RELAY LOSES ITS PRUNE and goes back to passing the web app's array through byte for byte — measured with a stubbed upstream to return a plaintext pair code whole",
     [('                "devices": [{k: d[k] for k in _PUBLIC_DEVICE_KEYS if k in d}\n                            for d in rows if isinstance(d, dict)],', '                "devices": rows,')]),
    ('P7', BRIDGE, 'over',
     "the browse relay reuses the OWN-machine allow-list, widening a stranger's row by four fields it has no business carrying",
     [('for k in _PUBLIC_DEVICE_KEYS if k in d}', 'for k in _DEVICE_PUBLIC_KEYS if k in d}')]),
    ('P8', BRIDGE, 'over',
     'the descriptor is REBUILT from the allow-list instead of pinned as a subset, so widening the list silently widens every chat error body',
     [('    return {"id": d.get("id"), "name": _device_label(d), "online": _device_is_online(d)}', '    out = {k: d.get(k) for k in _DEVICE_PUBLIC_KEYS if k in d}\n    out["name"] = _device_label(d)\n    out["online"] = _device_is_online(d)\n    return out')]),
    ('U1', BRIDGE, 'under',
     '⛔⛔ THE BRIDGE STOPS RELAYING THE CODE — back to the state where no client COULD tell the truth, whatever its wording said',
     [('            if body.get("pairCode"):\n                out["pairCode"] = body["pairCode"]\n', '')]),
    ('U2', BRIDGE, 'over',
     '⛔⛔ THE CODE IS RELAYED UNCONDITIONALLY, so a sharer who walked away gets the key as a null and a client testing `"pairCode" in body` prints an empty code',
     [('            if body.get("pairCode"):\n                out["pairCode"] = body["pairCode"]', '            out["pairCode"] = body.get("pairCode")')]),
    ('U3', BRIDGE, 'over',
     "the log line carries the credential's VALUE instead of the fact one was issued",
     [('                     body.get("action"), "issued" if body.get("pairCode") else "none")', '                     body.get("action"), body.get("pairCode"))')]),
    ('U4', SR, 'under',
     '⛔⛔ THE NEW CODE LINE GOES — the person is told the code changed and never shown the one that works',
     [('        f"New pair code: {new_code}",\n', '')]),
    ('U5', SR, 'under',
     'the credential warning goes, so a fresh code is printed into a chat with nothing said about what holding it means',
     [('        "Anyone who has that code can claim this computer as its owner, so keep "\n        "it like a password.",\n', '')]),
    ('U6', SR, 'over',
     "⛔⛔ CROSS-VERIFY'S OWN DEFECT, RESTORED: the fallback sends the reader to the machine's screen for a code the route says the machine cannot show",
     [('        return ["The device keeps running, but its pair code changed and the new "\n                "one did not reach me.",\n                "That code cannot be looked up anywhere — this reply was the only "\n                "copy. To use the computer again, run “superresearch --pair” on "\n                "the machine itself; it will join as a new computer."]', '        return ["The device keeps running. Its pair code changed, so the old one "\n                "no longer works — the new one is on the device\'s own screen."]')]),
    ('U7', SR, 'over',
     'the sharer branch prints the code lines too, so somebody LEAVING a machine is told about a rotation on a computer that is no longer theirs',
     [('        return _emit(body, args.json, [f"✓ Left the shared device “{label}”."])', '        return _emit(body, args.json, [f"✓ Left the shared device “{label}”.",\n                                       *_unlink_code_lines(body.get("pairCode"))])')]),
    ('U8', SR, 'under',
     '⛔⛔ `--json` DROPS THE WARNING AGAIN, so a machine-readable caller — still read by a person — gets the credential bare',
     [('        if isinstance(payload, dict) and payload.get("pairCode"):\n            payload = {**payload, "pairCodeWarning":\n                       "This is the machine\'s new pair code. Whoever holds it can "\n                       "claim the computer as its owner. The previous code no "\n                       "longer works and this is the only copy."}\n', '')]),
    ('U9', CLI, 'under',
     '⛔⛔ THE TERMINAL SAYS NOTHING ABOUT THE CODE AGAIN — "Removed device dev-a1." and stop, which is what it did for four waves',
     [('        code = body.get("pairCode")\n        if code:\n            print("  Its pair code changed — the old one no longer works.")\n            print(f"  New pair code: {code}")\n            print("  Anyone who has that code can claim this computer as its "\n                  "owner. Keep it like a password.")\n        else:\n', '        if False:\n')]),
    ('U10', CLI, 'over',
     "the terminal's fallback goes back to naming the device's screen, which cannot show a rotated code",
     [('            print("  Its pair code changed and the new one did not come back.")', '            print("  Its pair code changed — the new one is on the device\'s own screen.")')]),
    ('U11', CLI, 'over',
     "⛔⛔ THE TERMINAL'S SHARER BRANCH FALLS THROUGH TO THE OWNER PRINT, so somebody who LEFT a machine is handed its new pair code on screen",
     [('            else:\n                print(f"{_OK} Left that shared device.")\n            return 0', '            else:\n                print(f"{_OK} Left that shared device.")')]),
    ('U12', CLI, 'over',
     'the sharer line prints the raw device id again, because the route sends no `deviceName` on that branch',
     [('            if body.get("deviceName"):\n                print(f"{_OK} Left the shared device {name}.")\n            else:\n                print(f"{_OK} Left that shared device.")', '            print(f"{_OK} Left the shared device {name}.")')]),
    ('U13', SR, 'under',
     '⛔⛔ THE CONFIRM STOPS WARNING THE CODE WILL CHANGE, so the last screen before an irreversible rotation says nothing about it',
     [('"device-remove": "Unlink {name}? It keeps running, but its pair code changes — the old one stops working and I’ll show you the new one. Say yes and I’ll remove it.",', '"device-remove": "Unlink {name}? Say yes and I’ll remove it.",')]),
    ('T1', SR, 'over',
     '⛔⛔ THE CHAT CLIENT BORROWS THE PAIRING TABLE AGAIN — nothing crashes and nothing is misworded; the refusals simply stop existing',
     [('        msg = _device_refusal_line(err, _UNLINK_ERRORS, "remove the device",', '        msg = _device_refusal_line(err, _PAIR_ERRORS, "remove the device",')]),
    ('T2', SR, 'under',
     "the chat client loses its signed-out and http_ fallbacks, so a signed-out person reads the terminal's slash command and an outage prints `http_500`",
     [('    said = table.get(err)\n    if said:\n        return said\n    if str(err).lower().startswith("not signed in"):\n        return _signed_out_or(err)\n    if str(err).startswith("http_"):\n        return f"The app answered that with nothing I can read (HTTP {str(err)[5:]})."\n', '    said = table.get(err)\n    if said:\n        return said\n')]),
    ('T3', SR, 'over',
     '⛔⛔ `rotation_failed` CLAIMS NOTHING CHANGED AGAIN — the route deletes the pending customToken BEFORE it tries the rotation, so that was never true',
     [('                       "claimable by anyone holding the old one. It is still "\n                       "linked to you; try again in a moment.",', '                       "claimable by anyone holding the old one. Nothing changed; "\n                       "try again in a moment.",')]),
    ('T4', CLI, 'over',
     "⛔⛔ THE TERMINAL PRINTS THE WEB APP'S RAW CODE AGAIN for a failed unlink",
     [('            print(f"{_NO} couldn\'t remove device: "\n                  f"{_unlink_refusal(_err(res), body.get(\'retryAfterMs\'))}")', '            print(f"{_NO} couldn\'t remove device: {_err(res)}")')]),
    ('T5', CLI, 'over',
     'the terminal prints the raw code for a failed PAIR, including the recoverable `pair_bootstrap_failed`',
     [('            print(f"{_NO} couldn\'t add device: "\n                  f"{_pair_refusal(_err(res), body.get(\'retryAfterMs\'))}")', '            print(f"{_NO} couldn\'t add device: {_err(res)}")')]),
    ('T6', SR, 'over',
     '⛔ THE CHAT CLIENT GUESSES THE RATE-LIMIT WAIT AGAIN, beside a number the route handed it — and the terminal reads that number, so the two disagree',
     [('    if err == "rate_limited":\n        ms = retry_after_ms\n        ok = (not isinstance(ms, bool)) and isinstance(ms, (int, float)) and ms > 0\n        if not ok:\n            return f"Too many attempts to {what} in a row — give it a minute."', '    if err == "rate_limited":\n        return "Too many attempts — wait a few minutes and try again."\n        ms = retry_after_ms\n        ok = (not isinstance(ms, bool)) and isinstance(ms, (int, float)) and ms > 0\n        if not ok:\n            return f"Too many attempts to {what} in a row — give it a minute."')]),
    ('T7', SR, 'over',
     '`invalid_code_format` says "8 letters/digits" again, which is the opposite of the alphabet — it excludes I, L, O, 0 and 1, the five that get confused',
     [('    "invalid_code_format": "Pair codes are 8 characters and never use I, L, O, 0 or 1 — check those.",', '    "invalid_code_format": "Pair codes are 8 letters/digits (like K7XQ-9B2M) — check the device\'s screen.",')]),
    ('T8', SR, 'over',
     '`revoked_sharer` promises a remedy the blocklist refuses on every path — claim, ask AND approve all consult it, and only a Reset or an owner-unlink clears it',
     [('    "revoked_sharer": "The owner removed your access to that computer. Re-using a code "\n                      "or asking again can’t change that — only they can, from the app.",', '    "revoked_sharer": "The owner removed your access to that device — ask them to share it again.",')]),
    ('T9', SR, 'over',
     '`device_secret_missing` sends the reader to reset the code, which cannot restore the missing field — only the handshake writes it, so the fresh code loops',
     [('    "device_secret_missing": "That machine didn’t finish its side of the handshake — "\n                             "run “superresearch --pair” on it again.",', '    "device_secret_missing": "That device has lost the secret that goes with its code "\n                             "— reset the pair code on the device.",')]),
    ('T10', BRIDGE, 'under',
     "⛔⛔ THE UNLINK GOES BACK TO THE SHARED 15s TIMEOUT, shorter than the route's own 30s budget — the bridge gives up while the route SUCCEEDS and the only copy of the new pair code is discarded with the timed-out response",
     [('            status, body = _fe_api_post(sess, "/api/devices/unpair-self",\n                                        {"deviceId": device_id},\n                                        timeout=_FE_UNLINK_TIMEOUT)', '            status, body = _fe_api_post(sess, "/api/devices/unpair-self",\n                                        {"deviceId": device_id})')]),
    ('T11', BRIDGE, 'over',
     'the long wait is put back on the SHARED constant, which a guard already refuses: both clients wait 30s for the bridge and a retried generic call would outlast them',
     [('_FE_UNLINK_TIMEOUT = 35', '_FE_UNLINK_TIMEOUT = _FE_JSON_TIMEOUT')]),
    ('T12', SR, 'over',
     'the chat client stops waiting longer on unlink, so it gives up before the bridge does and reports a bridge that is not running',
     [('    code, body = _post("/device/remove", {"deviceId": dev.get("id")}, timeout=50)', '    code, body = _post("/device/remove", {"deviceId": dev.get("id")})')]),
    ('C1', INIT, 'over',
     '⛔⛔ THE CONTRACT CLAIMS IT CAN NEVER CONTROL DEVICES AGAIN — false on all four verbs since 7.9-1, in the file whose whole job is to say what it will not do',
     [('  * It never writes MEMBERSHIP.', '  * Research-only: it can never control devices (add/remove/pair/share).\n  * (was: it never writes MEMBERSHIP.)')]),
    ('C2', INIT, 'over',
     "⛔⛔ CROSS-VERIFY'S OWN FINDING, RESTORED: the contract says EVERY device verb forwards to a web route. `device-visibility` PATCHes the document directly, and the bridge handler's own docstring says so",
     [('⚠ `device-visibility` is the one device verb that does NOT\n    forward — it PATCHes the device document directly, because no web route for\n    it exists. That write is a single field and the rules check its value.', 'Every device verb here forwards to `/api/devices/*`.')]),
    ('C3', INIT, 'over',
     'the contract goes back to enumerating writers by hand — the list was wrong twice, the second time still seven writers short',
     [('    gated by the existing Firestore rules. The authoritative list is not here —\n    it is the allowlist in `tests/test_app_plane_unchanged.py`, which is derived\n    from the code and fails when a new writer appears.', '    gated by the existing Firestore rules — research docs, device-queue start\n    docs, one device field (`visibility`), and one access-request document.')]),
    ('C4', SKILL, 'over',
     '⛔⛔ SKILL.md CALLS A PAIR CODE "NOT a password" AGAIN — it is the credential that claims an ownerless machine',
     [("- **A pair code is the user's to spend — handle it, never repeat it back.** An", '- **A Super Research access code is NOT a secret — NOT a password, credential.** An')]),
    ('C5', SKILL, 'under',
     'the clause saying what holding a code MEANS is deleted rather than reverted — a sweep for the old wording cannot see this',
     [(" It DOES let whoever holds it claim\n  that computer, so don't echo it into chat; a user handing you their own is an\n  instruction, not a leak.", '')]),
    ('C6', SKILL, 'over',
     'the device table row promises the code survives an unlink again',
     [('unlinks but the device keeps running on a NEW pair code, which the reply shows; sharer just leaves).', 'unlinks but the device keeps running + re-pairs with its code; sharer just leaves).')]),
    ('C7', SKILL, 'over',
     'the SAFETY bullet promises it — the third list, and a table row alone was not enough to cover it in 7.9-2 either',
     [("`device-remove` (unlinks a device — an\n  owner's keeps running but on a NEW code), `device-ask`, `device-approve`,", "`device-remove` (unlinks a device — nothing is\n  deleted; an owner's device re-pairs with its code), `device-ask`, `device-approve`,")]),
    ('C8', MATRIX, 'under',
     '⛔⛔ THE MATRIX STOPS NAMING ITS THIN SPOTS, so the three routes driven by nothing read as covered — which is what the `/login` row used to do',
     [('ARE THE THIN SPOTS', 'are fine')]),
    ('C9', MATRIX, 'over',
     'the matrix claims a coverage credit it cannot derive — the shape that produced the false `/healthz` row from a test asserting a 403 before the handler ran',
     [("from instrumenting the bridge's own HANDLER METHODS, not its request entry\n> points", 'from a measured run')]),
    ('C10', SR, 'over',
     "the header claims a `help` subcommand again — there is none; the parser exits with `invalid choice: 'help'`",
     [('  logout             clear the account session\n', '  logout             clear the account session\n  help               this list\n')]),
    ('G1', HGUARD, 'over',
     '⛔⛔ THE RESTORE GUARD GOES BACK TO A CLASS-SCOPED SNAPSHOT REQUESTED BY ONE TEST, so pytest builds it immediately before that test and nothing runs between snapshot and comparison — the guard cannot fail, which is what cross-verify measured',
     [('@pytest.fixture(scope="module", autouse=True)', '@pytest.fixture(scope="class")')]),
    ('G2', HGUARD, 'under',
     'the crashed-harness check goes, so a run that died mid-mutation leaves a mutant in the tree with nothing in either suite noticing',
     [('        stranded = sorted(p.name for p in (ROOT / ".mutants").glob("*.inflight"))\n        assert not stranded, (\n            f"a mutation run died mid-flight and may have left a mutant in the "\n            f"tree: {stranded}")', '        pass')]),
    ('G3', RESEARCH, 'over',
     '⛔⛔ THE f-STRING GOES BACK TO PEP 701. It PARSES on 3.13, so all 7121 root tests stay green and only the correctness lint floor catches it — the mutant that proves the floor runs in the suite instead of a YAML step nobody read',
     [('        _quoted = \'"\' + ignored_topic + \'"\'\n        print(f"  {_c(_DIM, \'     To research it:\')}  {_c(_BOLD, f\'{_PROG} {_quoted}\')}")', '        print(f"  {_c(_DIM, \'     To research it:\')}  {_c(_BOLD, f\'{_PROG} \\\\"{ignored_topic}\\\\"\')}")')]),
    ('G4', LINTG, 'over',
     '⛔⛔ THE LINT GUARD SEARCHES THE WHOLE WORKFLOW AGAIN instead of the step, so the YAML COMMENT three lines above satisfies it and deleting `--ignore-noqa` from the live step leaves the file green',
     [('    step = _lint_step()\n    assert "--ignore-noqa" in step, (', '    step = _workflow()\n    assert "--ignore-noqa" in step, (')]),
    ('G5', CONFTEST, 'over',
     "⛔⛔ THE TYPESCRIPT BLANKER GOES BACK TO PYTHON'S TOKENIZER, which raises on a .ts file and returns the source UNTOUCHED — so the route-drift guard searches 222 live comment lines while claiming they are blanked",
     [('    out = list(src)\n    i, n = 0, len(src)\n    quote = None', '    return code_only(src)\n    out = list(src)\n    i, n = 0, len(src)\n    quote = None')]),
]

def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


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


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave,
    so a git check would report dirty on every run and a real leftover mutant
    would be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and
    a runner that only asks `returncode == 0` reads that as red — so one typo in
    the selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def _leg_for(fname: str) -> str:
    """Which suite can SEE a repair to this file.

    ⛔⛔ THE REASON THIS EXISTS. Every harness before this one ran the agent
    suite only, which was right while every wave was agent-only. This wave
    repaired `research.py` (the f-string that had CI's lint floor red for six
    pushes) and a ROOT-suite harness guard — and an agent-only runner would have
    scored both as killed without running one test that could see them. A score
    is only a score if the tests it ran could have failed."""
    return "root" if fname in ROOT_LEG_FILES else "agent"


def _leg_conf(leg: str):
    if leg == "root":
        return (ROOT, str(ROOT / ".venv" / "bin" / "python"),
                MINE_ROOT.split(), [ALL_ROOT], MIN_SELECTED_ROOT)
    return (AGENT, str(AGENT / ".venv" / "bin" / "python"),
            MINE_AGENT.split(), [ALL_AGENT], MIN_SELECTED_AGENT)


def run_tests(filtered: bool, leg: str = "agent") -> bool:
    cwd, py, mine, allsuites, _floor = _leg_conf(leg)
    purge_pycache(cwd if leg == "root" else AGENT)
    suites = mine if filtered else allsuites
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  cwd, ENV)
    if out == "nothing-collected":
        raise AssertionError(f"the {leg} leg collected NO tests — check the selection")
    return out == "green"


def _selected_count(leg: str) -> int:
    cwd, py, mine, _all, _floor = _leg_conf(leg)
    out = sh([py, "-B", "-m", "pytest", *mine, "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=cwd, env=ENV).stdout
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if not only:
        selected = [m for m in selected if m[0] not in _SOLO]

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

    legs = sorted({_leg_for(m[1]) for m in selected})
    if not unfiltered:
        for leg in legs:
            n = _selected_count(leg)
            floor = _leg_conf(leg)[4]
            print(f"the wave's own {leg} files collect {n} test(s)")
            if n < floor:
                print(f"⛔⛔ TOO FEW on the {leg} leg (need >= {floor}) — a selection "
                      "that matches nothing exits 5 and scores every mutant killed. "
                      "Refusing to run.")
                return 2

    before = _digest()
    for leg in legs:
        print(f"baseline [{leg}]… ", end="", flush=True)
        if not run_tests(filtered=not unfiltered, leg=leg):
            print("RED — fix the tree before mutating")
            return 2
        print("green")

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
            # substring-matches and yields an unparseable file; the suite then
            # goes red on an import error and the mutant banks a kill it never
            # earned.
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
            leg = _leg_for(fname)
            killed = not run_tests(filtered=not unfiltered, leg=leg)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered, leg=leg)
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
