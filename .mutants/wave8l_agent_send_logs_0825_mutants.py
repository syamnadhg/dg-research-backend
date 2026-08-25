"""Mutation harness for wave 8L — asking a research computer for logs, from
the agent.

⛔ WHAT THIS CODE DECIDES. Not whether a feature works — whether a request may
ASK for material belonging to people who are not the person asking. A fleet box
is shared by design: one research computer, many co-tenants, and the agent's
user is usually a sharer rather than the owner. Every mutant below is either
"asks for more than was agreed to" or "says something about a machine that is
not true", and the first kind is the reason this file exists.

⭐⭐ THE SHARPEST MUTANTS HERE:
  A1/A2 — the action name widens to a whole-machine one. On the owner's own box
          the feature keeps working perfectly; on a fleet it becomes either a
          silent refusal for every sharer or, if a rule ever loosened, every
          co-tenant's runs in one archive.
  M1    — the owner check on the machine-logs flag goes. The machine still ANDs
          it with ownership, so nothing leaks — what breaks is that a sharer is
          no longer TOLD, and quietly gets a smaller bundle than they asked for.
  S2    — a malformed run name is DROPPED instead of refused: the person ticks
          a run, does not get it, and is told the send succeeded.
  P1    — "never published" collapses into "holds nothing", so we accuse a
          computer of having lost logs it may be holding right now.
  F2    — the command's timestamp stops being wall-clock ms and every send
          silently vanishes into the machine's 30-second stale gate.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor — it measured nothing while reporting
a kill, which this repo has now shipped twice.

    .venv/bin/python .mutants/wave8l_agent_send_logs_0825_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The agent keeps its own pytest rootdir and imports `facade`, so this runs from
# `agent/`. The neighbouring route suites come along because several mutants
# below are edits to shared helpers (`_resolve_device`, the JSON reply) and a
# harness that only runs the new file would call collateral damage a kill.
AGENT_SUITES = ("tests/test_send_logs_agent_0825.py "
                "tests/test_send_logs_cli_0825.py "
                "tests/test_send_logs_skill_0825.py "
                "tests/test_app_plane_unchanged.py "
                "tests/test_bridge_routes.py "
                "tests/test_bridge_device.py "
                "tests/test_firestore_rest.py "
                "tests/test_skill_commands_resolve.py "
                "tests/test_sr_do.py "
                "tests/test_cli_parser.py")

BRIDGE = "agent/facade/bridge.py"
REST = "agent/facade/firestore_rest.py"
CLI = "agent/facade/cli.py"
SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"
MUTATED_FILES = (BRIDGE, REST, CLI, SR, SKILL)

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ A — the action name is the permission ══════════════════════
    ("A1", BRIDGE, "over",
     "⛔⛔ the whole-machine action goes on the wire — every run the computer "
     "has ever done, for everyone who uses it, asked for by one co-tenant",
     [('_SEND_LOGS_ACTION = "send-logs-selected"',
       '_SEND_LOGS_ACTION = "send-logs"')]),
    ("A2", BRIDGE, "over",
     "⛔ the newest-N action instead — also unscoped to a person, and it would "
     "read as working on the owner's own machine",
     [('_SEND_LOGS_ACTION = "send-logs-selected"',
       '_SEND_LOGS_ACTION = "send-logs-limited"')]),
    ("A3", BRIDGE, "under",
     "the action name is misspelt, so worker 1 deletes a command it does not "
     "recognise and nothing ever leaves the machine",
     [('_SEND_LOGS_ACTION = "send-logs-selected"',
       '_SEND_LOGS_ACTION = "send-logs-select"')]),

    # ═══════════ C — consent ════════════════════════════════════════════════
    ("C1", BRIDGE, "over",
     "⛔⛔ the consent check goes: this bridge starts claiming, on the wire, "
     "that a person was shown what leaves their computer when nobody was",
     [('            if body.get("consent") is not True:\n'
       '                self._json(400, {"reason": "no_consent",\n'
       '                                 "error": "logs are only sent after the person has been "\n'
       '                                          "shown what leaves the computer"})\n'
       '                return\n', "")]),
    ("C2", BRIDGE, "over",
     "consent is accepted from any truthy value, so a client that sends "
     "`consent: 1` records a conversation that never happened",
     [('            if body.get("consent") is not True:',
       '            if not body.get("consent"):')]),
    ("C3", BRIDGE, "under",
     "consent is never forwarded, so the machine refuses every send as "
     "ConsentMissing and the agent path is dead on arrival",
     [('                    extra={"code": code, "requestId": request_id,\n'
       '                           "consent": True, "runNames": names,',
       '                    extra={"code": code, "requestId": request_id,\n'
       '                           "runNames": names,')]),

    # ═══════════ M — the machine-logs boundary ══════════════════════════════
    ("M1", BRIDGE, "under",
     "⛔⛔ the owner check on the machine-logs flag goes — a sharer is no longer "
     "TOLD, and silently gets a smaller bundle than the one they asked for",
     [('            if include_machine and not dev.get("owned"):\n'
       '                self._json(403, {"reason": "machine_logs_owner_only",\n'
       '                                 "error": "this computer\'s own logs belong to whoever "\n'
       '                                          "owns it — ask again without them, and you "\n'
       '                                          "will still get every run of yours it holds"})\n'
       '                return\n', "")]),
    ("M2", BRIDGE, "over",
     "the check is inverted: the OWNER is refused their own machine's logs and "
     "a sharer is waved through to a request the machine will shrink anyway",
     [('            if include_machine and not dev.get("owned"):',
       '            if include_machine and dev.get("owned"):')]),
    ("M3", BRIDGE, "over",
     "the machine-logs flag is read from any truthy value, so a client sending "
     "the string \"no\" asks for the whole computer",
     [('            include_machine = body.get("includeMachine") is True',
       '            include_machine = bool(body.get("includeMachine"))')]),
    ("M4", BRIDGE, "under",
     "⛔ the flag is omitted when false, so an explicit 'no' and a client too "
     "old to have the box become indistinguishable in the row we show back",
     # ⛔ The bare field name appears TWICE — once on the wire and once in the
     # reply. Anchored on its comment, which belongs to the wire copy alone.
     [('                           # the row this produces records what was chosen.\n'
       '                           "includeMachine": include_machine})',
       '                           # the row this produces records what was chosen.\n'
       '                           **({"includeMachine": True} if include_machine else {})})')]),
    ("M5", BRIDGE, "over",
     "the flag is hard-wired on, so every send from every co-tenant asks for "
     "the machine-level material",
     [('            include_machine = body.get("includeMachine") is True',
       '            include_machine = True')]),

    # ═══════════ S — the selection ══════════════════════════════════════════
    ("S1", BRIDGE, "under",
     "⛔ the empty-selection refusal goes: a zip of three JSON files is uploaded "
     "under a support code and the person believes they have sent something",
     [('            if not names and not include_machine:\n'
       '                self._json(400, {"reason": "nothing_selected",\n'
       '                                 "error": "nothing was chosen to send"})\n'
       '                return\n', "")]),
    ("S2", BRIDGE, "under",
     "⛔⛔ a malformed run name is DROPPED rather than refused — the person ticks "
     "a run, does not get it, and is told the send succeeded",
     [('                if not isinstance(item, str) or not _RUN_NAME_RE.match(item):\n'
       '                    self._json(400, {"reason": "bad_selection",\n'
       '                                     "error": "one of the run names isn\'t a run name"})\n'
       '                    return\n'
       '                names.append(item)',
       '                if not isinstance(item, str) or not _RUN_NAME_RE.match(item):\n'
       '                    continue\n'
       '                names.append(item)')]),
    ("S3", BRIDGE, "over",
     "the run-name shape check goes entirely, so a megabyte of junk reaches the "
     "machine before anything looks at it",
     [('                if not isinstance(item, str) or not _RUN_NAME_RE.match(item):',
       '                if False:')]),
    ("S4", BRIDGE, "over",
     "a string is accepted where a list belongs, so \"run-a\" becomes five "
     "single-character names and the person's actual choice is sent nowhere",
     [('            if not isinstance(raw, list) or len(raw) > _SEND_LOGS_MAX_NAMES:',
       '            if raw is None or len(raw) > _SEND_LOGS_MAX_NAMES:')]),
    ("S5", BRIDGE, "under",
     "the cap is off by one against the machine's published maximum, so the "
     "oldest run is unsendable from every full selection",
     [('            if not isinstance(raw, list) or len(raw) > _SEND_LOGS_MAX_NAMES:',
       '            if not isinstance(raw, list) or len(raw) >= _SEND_LOGS_MAX_NAMES:')]),
    ("S6", BRIDGE, "over",
     "the cap goes, so a selection larger than anything the machine ever "
     "published is put on the wire for it to refuse whole",
     [('            if not isinstance(raw, list) or len(raw) > _SEND_LOGS_MAX_NAMES:',
       '            if not isinstance(raw, list):')]),

    # ═══════════ K — the support code ═══════════════════════════════════════
    ("K1", BRIDGE, "under",
     "⛔ the alphabet grows the letters people misread, so a code read aloud on "
     "a support call names a bundle nobody can find",
     [('_SUPPORT_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"',
       '_SUPPORT_CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"')]),
    ("K2", BRIDGE, "under",
     "the code is shorter than the machine's pattern, so every request is "
     "refused with 'no valid support code' and the agent looks broken",
     [("_SUPPORT_CODE_LENGTH = 8", "_SUPPORT_CODE_LENGTH = 6")]),
    ("K3", BRIDGE, "under",
     "⛔ every send mints the SAME code, so the second bundle overwrites the "
     "first and one of two people's logs is gone",
     [('    return "".join(secrets.choice(_SUPPORT_CODE_ALPHABET)\n'
       '                   for _ in range(_SUPPORT_CODE_LENGTH))',
       '    return "A" * _SUPPORT_CODE_LENGTH')]),

    # ═══════════ P — what the machine published ═════════════════════════════
    ("P1", BRIDGE, "under",
     "⛔⛔ never-published collapses into holds-nothing, so we accuse a computer "
     "of having lost logs it may be holding right now",
     [('                "published": held is not None,', '                "published": True,')]),
    ("P2", REST, "under",
     "the missing document becomes an empty one at the REST layer, which is the "
     "same lie one layer lower where nothing above can see it",
     [('        url = f"{config.FIRESTORE_BASE}/users/{uid}/deviceRunLogs/{device_id}"\n'
       '        body = self._request("GET", url, allow_missing=True)\n'
       '        if body is None:\n'
       '            return None',
       '        url = f"{config.FIRESTORE_BASE}/users/{uid}/deviceRunLogs/{device_id}"\n'
       '        body = self._request("GET", url, allow_missing=True) or {}\n'
       '        if False:\n'
       '            return None')]),
    ("P3", BRIDGE, "under",
     "⛔ a run whose research document is gone is dropped from the list — which "
     "hides exactly the runs most likely to need sending",
     [('                rows.append({\n                    "name": name,',
       '                if rid not in titles:\n'
       '                    continue\n'
       '                rows.append({\n                    "name": name,')]),
    ("P4", BRIDGE, "over",
     "an entry with no usable name is offered anyway, so a person ticks a row "
     "that is sent as nothing and reads the result as being ignored",
     [('                if not isinstance(name, str) or not name:\n'
       '                    continue\n', "")]),
    ("P5", BRIDGE, "under",
     "the machine's truncation flag is dropped, so a list that is missing the "
     "oldest runs presents itself as the whole of what is held",
     [('                "truncated": bool((held or {}).get("truncated")),',
       '                "truncated": False,')]),
    ("P6", BRIDGE, "under",
     "ownership is not reported with the list, so a caller cannot tell whether "
     "to offer the machine's own logs and offers them to everyone",
     [('                "owned": bool(dev.get("owned")),',
       '                "owned": True,')]),

    # ═══════════ D — which machine ══════════════════════════════════════════
    ("D1", BRIDGE, "over",
     "⛔ the membership lookup goes, so a request aimed at a machine this "
     "account cannot reach is refused by the rule as 'the store is unreachable'",
     [('            match = next((d for d in devs if d.get("id") == device_id), None)\n'
       '            if match is None:\n'
       '                self._json(404, {"reason": "not_a_member",\n'
       '                                 "error": "that computer isn\'t on your account — "\n'
       '                                          "add it, or pick one from the device list"})\n'
       '                return None\n', "")]),

    # ═══════════ B — reading the row back ═══════════════════════════════════
    ("B1", BRIDGE, "over",
     "the support-code shape check goes, so a crafted code is interpolated "
     "straight into a Firestore path",
     [('            if not _SUPPORT_CODE_RE.match(code):\n'
       '                self._json(400, {"error": "that isn\'t a support code"})\n'
       '                return\n', "")]),
    ("B2", BRIDGE, "under",
     "the code is not upper-cased, so a person typing back the code they were "
     "given is told it is not a support code",
     [('            code = (qs.get("code") or [""])[0].strip().upper()',
       '            code = (qs.get("code") or [""])[0].strip()')]),
    ("B3", REST, "over",
     "⛔ a row that has not appeared yet raises instead of reading as absent — "
     "so every successful send reports a failure during its first seconds",
     [('        url = f"{config.FIRESTORE_BASE}/users/{uid}/logBundles/{code}"\n'
       '        body = self._request("GET", url, allow_missing=True)',
       '        url = f"{config.FIRESTORE_BASE}/users/{uid}/logBundles/{code}"\n'
       '        body = self._request("GET", url)')]),

    # ═══════════ F — what actually reaches the document ═════════════════════
    ("F1", REST, "under",
     "⛔⛔ the submitter is not encoded, so the create rule refuses the write and "
     "the person is told the research store is unreachable",
     [('            "submittedBy": uid,\n        }\n        if extra:', '        }\n        if extra:')]),
    ("F2", REST, "under",
     "⛔⛔ the timestamp is a server sentinel, so the machine's 30-second stale "
     "gate drops every command and no send ever produces a bundle",
     [('            "timestamp": int(time.time() * 1000),',
       '            "timestamp": 0,')]),
    ("F3", REST, "under",
     "the command arrives already marked processed, which is the marker a "
     "reconnect is meant to skip — so the machine skips it",
     # ⛔ `processed: False` also appears in `write_command` (the per-RUN
     # writer). Anchored with the action line above it, which is this one's.
     [('            "action": action,\n            "processed": False,',
       '            "action": action,\n            "processed": True,')]),
    ("F4", REST, "under",
     "⛔ the command lands under the LEGACY per-user path the machine does not "
     "subscribe to — no error, and a spinner that can never resolve",
     [('        url = f"{config.FIRESTORE_BASE}/devices/{device_id}/commands"',
       '        url = f"{config.FIRESTORE_BASE}/users/{uid}/devices/{device_id}/commands"')]),
    ("F5", REST, "under",
     "the held list is read from the device document's own tree, which every "
     "sharer of that machine can read — one co-tenant learns another's history",
     [('        url = f"{config.FIRESTORE_BASE}/users/{uid}/deviceRunLogs/{device_id}"',
       '        url = f"{config.FIRESTORE_BASE}/devices/{device_id}/runLogs/{uid}"')]),

    # ═══════════ T — the terminal: showing before claiming ══════════════════
    ("T1", CLI, "over",
     "⛔⛔ --yes skips the PRINTING as well as the asking, so `consent: true` "
     "goes on the wire having shown the person nothing at all",
     [('    print(f"This will send {len(names)} run(s) ({_size_words(total)}) from {name}.")',
       '    if not args.yes:\n'
       '        print(f"This will send {len(names)} run(s) ({_size_words(total)}) from {name}.")')]),
    ("T2", CLI, "over",
     "the prompt defaults to YES, so a bare Enter sends somebody's logs",
     [('    if not _decide(None, bool(args.yes), "Send these logs?", default=False):',
       '    if not _decide(None, bool(args.yes), "Send these logs?", default=True):')]),
    ("T3", CLI, "over",
     "⛔ a declined prompt sends anyway — the confirmation becomes decorative",
     [('    if not _decide(None, bool(args.yes), "Send these logs?", default=False):\n'
       '        print("Nothing was sent.")\n'
       '        return 1\n', "")]),
    ("T4", CLI, "under",
     "a run the person named that the machine is not holding is DROPPED rather "
     "than refused — fewer runs go than were asked for, reported as success",
     [('            if not 1 <= index <= len(rows):\n'
       '                print(f"{_NO} There is no run {index} in that list.")\n'
       '                return None\n',
       '            if not 1 <= index <= len(rows):\n'
       '                continue\n')]),
    ("T5", CLI, "over",
     "a name the machine is not holding is passed through to the wire instead "
     "of being refused, where it silently matches nothing",
     [('            print(f"{_NO} That computer isn\'t holding a run called “{token}”.")\n'
       '            return None',
       '            name = token')]),
    ("T6", CLI, "under",
     "⛔⛔ the two sentences collapse: a machine that never published is "
     "reported as holding none of the person's runs",
     [('        print("  That computer hasn\'t told us which runs it still holds.")',
       '        print("  It isn\'t holding logs for any of your runs.")')]),
    ("T7", CLI, "over",
     "the sharer refusal goes from the terminal, so the sentence only arrives "
     "after a round trip — or not at all on an older bridge",
     [('    if machine and not owned:\n'
       '        # Refused here as well as at the bridge, so the sentence arrives before\n'
       '        # a round trip rather than after one.\n'
       '        print(f"{_NO} That computer\'s own logs belong to whoever owns it.")\n'
       '        print("    Ask again without --machine and you will still get every "\n'
       '              "run of yours it holds.")\n'
       '        return 1\n', "")]),
    ("T8", CLI, "under",
     "⛔ a timeout is reported as a failure, which is a lie about somebody "
     "else's computer and fires on every machine that is merely slow",
     [('    if seen_any:\n'
       '        print(f"  Still packaging. Check again with:  agent send-logs --status {code}")',
       '    if True:\n'
       '        print(f"{_NO} That computer never answered.")\n'
       '        return 1\n'
       '    if seen_any:\n'
       '        print(f"  Still packaging. Check again with:  agent send-logs --status {code}")')]),
    ("T9", CLI, "under",
     "'never picked up' and 'still packaging' become one sentence, so somebody "
     "waiting on an asleep machine is told to keep waiting",
     [('        print("  That computer hasn\'t picked the request up yet — it may be "\n'
       '              "asleep or offline.")',
       '        print("  Still packaging.")')]),
    ("T10", CLI, "under",
     "a refusal is reported as its class name, which is not a sentence anybody "
     "can act on",
     [('    known = _SEND_LOGS_FAILURES.get(str(error_class or ""))\n'
       '    if known:\n'
       '        return known',
       '    known = None\n'
       '    if known:\n'
       '        return known')]),
    ("T11", CLI, "under",
     "an owner with no runs is not told the machine's own logs exist, which is "
     "the one case that most needs them",
     [('        if owned:\n'
       '            print("    To send that computer\'s own logs instead, add --machine.")\n', "")]),
    ("T12", CLI, "over",
     "a sharer with no runs is offered the machine's own logs, which they "
     "cannot have — a next step that dead-ends",
     [('        if owned:\n'
       '            print("    To send that computer\'s own logs instead, add --machine.")',
       '        if True:\n'
       '            print("    To send that computer\'s own logs instead, add --machine.")')]),

    # ═══════════ H — the chat skill ═════════════════════════════════════════
    ("H1", SR, "over",
     "⛔⛔ the bare command SENDS — the plan is never shown and the consent flag "
     "claims a conversation that did not happen",
     [('    if not getattr(args, "confirm", False):\n'
       '        lines = [f"I can send Super Research support the logs from “{name}”:"]',
       '    if False:\n'
       '        lines = [f"I can send Super Research support the logs from “{name}”:"]')]),
    ("H2", SR, "over",
     "the sharer refusal goes, so somebody on a shared computer asks for its "
     "own logs and is silently given a smaller bundle",
     [('    if machine and not owned:\n'
       '        # Said here rather than after a round trip. The computer would refuse\n'
       '        # this anyway; what this decides is whether the person is TOLD, and on\n'
       '        # a shared computer that is the ordinary case rather than the odd one.\n'
       '        return _emit(body, args.json, [\n'
       '            f"“{name}”’s own logs belong to whoever owns it, so I can’t include "\n'
       '            "them. Ask again without them and you’ll still get every run of "\n'
       '            "yours it’s holding."], 1)\n', "")]),
    ("H3", SR, "under",
     "⛔⛔ the two sentences collapse in chat: a computer we cannot see is "
     "reported to the user as holding none of their runs",
     [('                f"“{name}” hasn’t told me which runs it’s still holding, so I "\n'
       '                "can’t offer you a list yet."',
       '                f"“{name}” isn’t holding logs for any of your runs."')]),
    ("H4", SR, "under",
     "the plan stops naming what the machine's own logs actually are, so the "
     "user agrees to a phrase instead of to the material",
     [('            lines.append("Plus that computer’s own logs: its pairing and sign-in "\n'
       '                         "records and its raw activity trail, which cover every "\n'
       '                         "run it has ever done, for everyone who uses it.")',
       '            lines.append("Plus that computer’s own logs.")')]),
    ("H5", SR, "under",
     "the plan stops saying how long the logs are kept and who can read them",
     [('        lines.append(f"That’s {len(names)} run(s), about {_size_words(total)}. "\n'
       '                     "They’re kept for 30 days and only Super Research support "\n'
       '                     "can read them.")',
       '        lines.append(f"That’s {len(names)} run(s).")')]),
    ("H6", SR, "under",
     "⛔ the assistant is no longer told not to poll, so a chat runtime checks "
     "the status on a timer for as long as the conversation stays open",
     [('            "Do not poll on a timer — only when the user asks.",\n', "")]),
    ("H7", SR, "over",
     "a broad word like 'everything' asks for the whole machine, turning a "
     "phrase into a request nobody made",
     [('        if re.search(r"\\b(computer|machine|device)(?:’s|\'s)?\\s+own\\b", low) or \\',
       '        if re.search(r"\\b(everything|all|whole|full)\\b", low) or \\')]),
    ("H8", SR, "over",
     "⛔ reading the logs resolves to SENDING them: 'check the logs' hands "
     "somebody's research history to support",
     [('    if re.search(r"\\b(logs?|log ?files?|diagnostics?)\\b", low) and re.search(\n'
       '            r"\\b(send|share|upload|submit|report|give|email|hand)\\b", low):',
       '    if re.search(r"\\b(logs?|log ?files?|diagnostics?)\\b", low):')]),
    ("H9", SR, "under",
     "a 'which computer?' answer is rendered as a bare error, so somebody with "
     "two computers is told their logs cannot be sent",
     [('        if body.get("reason") in ("no_selection", "stale_selection", "no_devices"):\n'
       '            return _emit(body, args.json,\n'
       '                         _pick_device_lines(body, body.get("reason", "")), _fail_code(code))\n', "")]),
    ("H10", SR, "under",
     "a refusal in chat is reported as its class name",
     [('    known = _SEND_LOGS_FAILURES.get(str(error_class or ""))\n'
       '    if known:\n'
       '        return known',
       '    known = None\n'
       '    if known:\n'
       '        return known')]),
    ("H11", SR, "under",
     "nothing back yet is reported as a failure, which fires on every computer "
     "that is merely slow to package",
     [('            return _emit(body, args.json, [\n'
       '                f"Nothing has come back for {want} yet. That computer may still "\n'
       '                "be packaging it, or may not have picked the request up."])',
       '            return _emit(body, args.json, [f"✗ {want} failed."], 1)')]),

    # ═══════════ W — what the assistant is told to do ═══════════════════════
    ("W1", SKILL, "over",
     "⛔⛔ SKILL.md sends the assistant straight to --confirm, so the model "
     "never shows the plan and the two-step exists only in code",
     [("| \"send my logs\", \"share the logs with support\", \"submit diagnostics\" | "
       "`sr.py send-logs` — it SHOWS what would go and sends nothing. On \"yes\", "
       "run `sr.py send-logs --confirm`. See **Sending logs to support** |",
       "| \"send my logs\", \"share the logs with support\", \"submit diagnostics\" | "
       "`sr.py send-logs --confirm` |")]),
    ("W2", SKILL, "under",
     "the section stops telling the assistant to wait for a real yes, which is "
     "the instruction a helpful model collapses first",
     [("**Relay the plan\nverbatim and wait for a real \"yes\".**",
       "Relay the plan.")]),
    ("W3", SKILL, "under",
     "the section stops saying the machine's own logs are the owner's, so the "
     "assistant offers them to every user of a shared computer",
     [("are a separate thing and are **the owner's**",
       "are also available")]),
    ("W4", SKILL, "under",
     "⛔ the assistant is no longer told to check only when asked, so it polls "
     "the support code on a timer",
     [("Check with `sr.py send-logs --status <CODE>` **when the user asks** —\n  never on a timer.",
       "Check with `sr.py send-logs --status <CODE>`.")]),
    ("W5", SKILL, "under",
     "the two sentences are documented as interchangeable, so the assistant "
     "paraphrases 'we cannot see the list' into 'your logs are gone'",
     [("- **\"Hasn't told me which runs it's holding\"** is not the same as \"isn't holding\n"
       "  any\". The first means we cannot see the list; do not turn it into a statement\n"
       "  about the user's logs being gone.\n", "")]),
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
    for mid, fname, direction, why, edits in MUTANTS:
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

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
