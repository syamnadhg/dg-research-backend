"""Mutation harness — the owner verbs: answering somebody who asked for a
machine, and deciding who can find one at all (wave 7.9-3, 2026-09-07).

⛔⛔ WHAT THIS CODE DECIDES. Whether a stranger is let onto somebody's computer;
whether a refusal that costs that person a week is made knowingly; and whether a
machine's name — which on an unrenamed Mac carries its OWNER'S own name — is
published to everyone signed in. Every one of those is somebody ELSE's exposure
decided by this account, so a wrong answer here is not a wrong answer about the
person holding the terminal.

⛔⛔ THE TWO THINGS THIS WAVE IS NOT ALLOWED TO GET WRONG, both of them lessons
paid for elsewhere:

  A REFUSAL AND AN OUTAGE ARE DIFFERENT SENTENCES. The web app answers a
  non-owner with the SAME 404 it gives for a machine that does not exist, and a
  rules refusal reaches this bridge as "could not reach the research store".
  Ungated, one verb tells a sharer their own computer is not there and the other
  reports an outage that never happened. E-series is that gate.

  "NOTHING CHANGED" IS NOT ALWAYS SAYABLE. The machine's own `--visibility`
  shipped that claim on four failure paths and only two of them support it. A
  403 proves the write did not land; a 5xx happened after the request went out.
  V6/V7 are that distinction, and the absent-status case must read as UNKNOWN,
  because unknown is the direction that does not lie.

⭐⭐ THE SHARPEST MUTANTS HERE:
  E2      — `owned` is read off the device document instead of recomputed. It is
            NOT a persisted field; a document carrying one is a document that
            was allowed to nominate itself.
  E3      — the non-owner refusal becomes a 404, and a sharer is told the
            computer sitting in their own list does not exist.
  D6      — the reply echoes the decision that was ASKED FOR rather than the one
            the route made. The route closes an already-shared request as
            approved and writes nothing, so the two are not the same fact.
  V3      — absent reads as public. Every machine paired before 2026-09-04
            carries no such field, so this is most of them.
  V7      — a failure with no status is reported as a refusal, which promises
            the machine is untouched when nothing proved that.
  N1      — the machine-noun list drifts by two words again. That drift was LIVE
            when this wave started and silently broke four guards whose comments
            claimed they were fixed.
  N10     — the decide clause moves below the ask clause, and an owner trying to
            approve somebody is offered the question that hands their own name
            to a stranger. Measured live before this wave.
  C4      — chat picks the first of two people whose names both match. A wrong
            match here does not misname a thing; it lets the wrong person onto
            somebody's computer.
  S1-S3   — a new confirm goes missing from one of the THREE places this file
            enumerates them, and one of those lists ends "everything else runs
            on a clear request".

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS WAVE'S OWN GUARDS. Pass --unfiltered to ask the other
question — whether the TREE catches it — which is deliberately separate. A
borrowed kill is not evidence that the guard you just wrote works.

    .venv/bin/python .mutants/wave793_owner_verbs_mutants.py
    .venv/bin/python .mutants/wave793_owner_verbs_mutants.py --unfiltered
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
FS = "agent/facade/firestore_rest.py"
PLANE = "agent/tests/test_app_plane_unchanged.py"
OURS = (CLI, BRIDGE, SR, SKILL, FS, PLANE)

# ⭐ THE GUARDS THIS WAVE ADDED, and the only tests a score here is about.
MINE = ("tests/test_owner_verbs_793.py "
        "tests/test_chat_owner_793.py "
        "tests/test_app_plane_unchanged.py")
MIN_SELECTED = 160

ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ F — the Firestore write that has no web route ═══════════════
    ("F1", FS, "under",
     "⛔⛔ THE VALUE STOPS BEING CHECKED AT THE WIRE. This is the only field on "
     "the device document whose VALUE the rules examine, and one they reject "
     "refuses the WHOLE update — so a typo does not write a strange setting, it "
     "fails a write the caller believes it made",
     [('        if value not in ("public", "private"):\n'
       '            raise ValueError(\n'
       '                f"visibility must be \'public\' or \'private\', not {value!r}")',
       '        pass')]),
    ("F2", FS, "over",
     "⛔⛔ THE UPDATE MASK NAMES THE WHOLE DOCUMENT. The owner rule admits eight "
     "keys, so a maskless PATCH is a method that can rename a machine or write "
     "under the maintenance banner — the field IS the permission here",
     [('        self._request("PATCH", f"{target}?updateMask.fieldPaths=visibility",',
       '        self._request("PATCH", target,')]),
    ("F3", FS, "over",
     "the write aims at the commands subcollection, so a setting becomes a "
     "command nothing will ever consume",
     [('        target = f"{config.FIRESTORE_BASE}/devices/{device_id}"',
       '        target = f"{config.FIRESTORE_BASE}/devices/{device_id}/commands"')]),
    ("F4", FS, "under",
     "⛔⛔ THE ERROR STOPS CARRYING ITS STATUS, so every failure reads as the "
     "unknown case and the one sentence a refusal HAS earned — nothing changed "
     "— can never be said",
     [('                status=resp.status_code,\n',
       '')]),
    ("F5", FS, "over",
     "⛔⛔ AN ERROR WITH NO STATUS DEFAULTS TO A REFUSAL, so a transport failure "
     "— and every test double that raises this by hand — promises the machine "
     "is untouched when nothing proved that",
     [('    def __init__(self, message: str, *, status: int | None = None) -> None:',
       '    def __init__(self, message: str, *, status: int | None = 403) -> None:')]),

    # ═══════════ E — the owned gate (B7) ═════════════════════════════════════
    ("E1", BRIDGE, "under",
     "⛔⛔ THE OWNERSHIP CHECK GOES. The decide route then answers a non-owner "
     "with the same 404 it gives for a missing machine, so a sharer is told the "
     "computer in their own list does not exist",
     [('            if not row.get("owned"):\n',
       '            if False:\n')]),
    ("E2", BRIDGE, "over",
     "⛔⛔ `owned` IS READ OFF THE DOCUMENT INSTEAD OF RECOMPUTED. It is not a "
     "persisted field — a document carrying one would be nominating itself",
     [('            self._decorate_devices([row], sess.uid,\n'
       '                                   prefs.get_selected_device(sess.uid))\n'
       '            if not row.get("owned"):',
       '            if not row.get("owned"):')]),
    ("E3", BRIDGE, "over",
     "⛔⛔ THE NON-OWNER REFUSAL BECOMES A 404, indistinguishable from a machine "
     "that does not exist — which is exactly the answer this gate exists to "
     "stop the person receiving",
     [('                self._json(403, {"reason": "not_owner",',
       '                self._json(404, {"reason": "not_linked",')]),
    ("E4", BRIDGE, "under",
     "the refusal names only what they LACK, so somebody is left wondering "
     "whether the machine is even theirs to see",
     [(' — you have been given access "\n'
       '                                          "to it, which is not the same thing"',
       '"'),
      ]),
    ("E5", BRIDGE, "over",
     "⛔⛔ THE GATE FALLS BACK TO THE SELECTED MACHINE when no id is given, so a "
     "computer nobody named is published to strangers or opened to a person",
     [('            device_id = _body_str(body_in, "deviceId")\n'
       '            if not device_id:\n'
       '                self._json(400, {"error": "deviceId is required"})\n'
       '                return\n'
       '            value = _body_str(body_in, "visibility").lower()',
       '            device_id = (_body_str(body_in, "deviceId")\n'
       '                         or (prefs.get_selected_device("") or ""))\n'
       '            value = _body_str(body_in, "visibility").lower()')]),
    ("E6", BRIDGE, "under",
     "⛔ the not-linked refusal goes back to a connectivity word for a "
     "permissions state, on the one route where browsing makes strangers' ids "
     "the ids people try first",
     [('_NOT_LINKED_ERROR = "no computer with that id is linked to your account"',
       '_NOT_LINKED_ERROR = "device not reachable by this account"')]),
    ("E7", BRIDGE, "over",
     "⛔⛔ THE GATE RUNS AFTER THE WEB CALL, so a sharer's decision reaches the "
     "route — which answers 404 — and the local refusal never happens",
     [('            row = self._owned_device(fs, sess, device_id,\n'
       '                                     "answer people asking for it")\n'
       '            if row is None:\n'
       '                return\n'
       '            status, reply = _fe_api_post(',
       '            status, reply = _fe_api_post(')]),

    # ═══════════ D — answering somebody (B5) ═════════════════════════════════
    ("D1", BRIDGE, "under",
     "⛔ THE PERSON'S ID STOPS BEING SHAPE-CHECKED, so a display name reaches "
     "the route and comes back as a bare `requester_required` this client has "
     "nothing to say about",
     [('            if not _ADDRESSABLE_UID_RE.fullmatch(requester):\n',
       '            if False:\n')]),
    ("D2", BRIDGE, "over",
     "the uid predicate admits dashes and underscores, which the web app's own "
     "predicate refuses — so this client accepts what the route will not",
     [('_ADDRESSABLE_UID_RE = re.compile(r"[A-Za-z0-9]{1,128}")',
       '_ADDRESSABLE_UID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")')]),
    ("D3", BRIDGE, "over",
     "⛔ the uid test becomes a SEARCH, so any string containing one letter "
     "passes and an email address is forwarded as a person's id",
     [('            if not _ADDRESSABLE_UID_RE.fullmatch(requester):',
       '            if not _ADDRESSABLE_UID_RE.search(requester):')]),
    ("D4", BRIDGE, "over",
     "⛔⛔ ANY TRUTHY WORD DECIDES. Approving by accident grants a stranger a "
     "machine and denying by accident spends the asker's week — the one place "
     "an explicit pair is not optional",
     [('            if decision not in ("approve", "deny"):',
       '            if not decision:')]),
    ("D5", BRIDGE, "over",
     "the decision is lower-cased before the comparison, so the route is sent a "
     "word this client normalised and the two doors disagree about what was said",
     [('            decision = _body_str(body_in, "decision")',
       '            decision = _body_str(body_in, "decision").lower()')]),
    ("D6", BRIDGE, "over",
     "⛔⛔ THE REPLY ECHOES THE DECISION THAT WAS ASKED FOR rather than the one "
     "the route made. The route closes an ALREADY-SHARED request as approved "
     "and writes nothing to the machine, so those are not the same fact",
     [('                             "decision": reply.get("decision") or\n'
       '                             ("approved" if decision == "approve" else "denied"),',
       '                             "decision": ("approved" if decision == "approve"\n'
       '                                          else "denied"),')]),
    ("D7", BRIDGE, "under",
     "an upstream 200 carrying ok:false is relayed as a success, so a decision "
     "that did not happen is reported as one that did",
     [('            if not reply.get("ok"):\n',
       '            if False:\n')]),
    ("D8", BRIDGE, "over",
     "⛔⛔ THE ASKER'S ID GOES INTO THE LOG. This file is uploadable to support "
     "under a sentence about the ids of the computers and runs THIS agent has "
     "touched — a stranger who asked is none of those",
     [('            log.info("device decide: %s on %s", decision, device_id)',
       '            log.info("device decide: %s on %s for %s", decision, device_id,\n'
       '                     requester)')]),
    ("D9", BRIDGE, "under",
     "the decision stops being logged at all, so the one record that an answer "
     "left this machine is gone",
     [('            log.info("device decide: %s on %s", decision, device_id)\n',
       '')]),
    ("D10", BRIDGE, "over",
     "the decide call is aimed at the CREATE route, so answering somebody files "
     "a fresh request in their name",
     [('                sess, "/api/devices/access-request/decide",',
       '                sess, "/api/devices/access-request",')]),
    ("D11", BRIDGE, "under",
     "⛔ the relay is skipped, so a revoked session is a 502 and the one failure "
     "the person can fix is reported as the one they cannot",
     [('            if not self._fe_relay(status, reply, "could not answer that request"):\n'
       '                return\n',
       '')]),

    # ═══════════ V — who can find it (B6) ════════════════════════════════════
    ("V1", BRIDGE, "under",
     "the typed value stops being normalised, so somebody who writes Public is "
     "refused by a client whose own table would have accepted it",
     [('            value = _body_str(body_in, "visibility").lower()',
       '            value = _body_str(body_in, "visibility")')]),
    ("V2", BRIDGE, "under",
     "⛔⛔ THE VALUE IS NOT CHECKED BEFORE THE ROW IS READ, so a typo spends a "
     "Firestore read and then fails a write the person believes they made",
     [('            if value not in ("public", "private"):\n'
       '                # ⛔ REFUSED HERE, BEFORE THE ROW IS EVEN READ.',
       '            if False:\n'
       '                # ⛔ REFUSED HERE, BEFORE THE ROW IS EVEN READ.')]),
    ("V3", BRIDGE, "over",
     "⛔⛔ ABSENT READS AS PUBLIC. Every machine paired before 2026-09-04 carries "
     "no such field and nothing backfills one, so this is most of them — and it "
     "reports a private computer as findable",
     [('    # ⛔ ABSENT IS PRIVATE. A machine paired before 2026-09-04 carries neither key,\n    # and the safe direction for a discovery setting is the one that hides.\n    return "private"\n',
       '    # ⛔ ABSENT IS PRIVATE. A machine paired before 2026-09-04 carries neither key,\n    # and the safe direction for a discovery setting is the one that hides.\n    return "public"\n')]),
    ("V4", BRIDGE, "over",
     "a no-op reports that something changed, so somebody believes they just "
     "published a machine that was already published",
     [('            if value == current:\n',
       '            if False:\n')]),
    ("V5", BRIDGE, "over",
     "⛔ the two failure sentences collapse into one, so a 5xx — which happened "
     "AFTER the request went out — promises the machine is as it was",
     [('                refused = getattr(e, "status", None) == 403',
       '                refused = True')]),
    ("V6", BRIDGE, "under",
     "⛔ every refusal becomes the unconfirmed sentence, so a rules refusal that "
     "PROVES nothing was written says it may have been",
     [('                refused = getattr(e, "status", None) == 403\n',
       '                refused = False\n')]),
    ("V7", BRIDGE, "over",
     "⛔⛔ A FAILURE WITH NO STATUS IS READ AS A REFUSAL. A transport error, and "
     "every double that raises this by hand, then promises the machine is "
     "untouched — unknown is the direction that does not lie",
     [('                refused = getattr(e, "status", None) == 403',
       '                refused = (getattr(e, "status", None) or 403) == 403')]),
    ("V8", BRIDGE, "under",
     "⛔⛔ THE PUBLISHED LABEL IS NOT RETURNED, so no surface can tell an owner "
     "what strangers will see — and on an unrenamed Mac that string carries the "
     "owner's own name",
     [('            label = _public_label_of(row)',
       '            label = None')]),
    ("V9", BRIDGE, "over",
     "the label chain runs backwards, so a machine somebody deliberately renamed "
     "publishes its hostname instead",
     [('    for key in ("name", "machineName", "hostname"):',
       '    for key in ("hostname", "machineName", "name"):')]),
    ("V10", BRIDGE, "under",
     "the label stops being bounded, so a forty-character promise publishes "
     "whatever the machine reports",
     [('    return cleaned[:_PUBLIC_LABEL_MAX] if cleaned else _PUBLIC_LABEL_FALLBACK',
       '    return cleaned if cleaned else _PUBLIC_LABEL_FALLBACK')]),
    ("V11", BRIDGE, "under",
     "⛔ the characters a label may not carry stop being stripped, so what an "
     "owner is shown differs from what the listing actually publishes — and a "
     "bidi override reaches a terminal",
     [('    cleaned = _PUBLIC_LABEL_STRIP_RE.sub("", raw).strip()',
       '    cleaned = raw.strip()')]),
    ("V12", BRIDGE, "over",
     "an empty name is published rather than falling through to the next link, "
     "so a machine appears in the list with no name at all",
     [('        if isinstance(value, str) and value.strip():\n'
       '            raw = value.strip()\n'
       '            break',
       '        if isinstance(value, str):\n'
       '            raw = value.strip()\n'
       '            break')]),
    ("V13", BRIDGE, "under",
     "the fallback becomes an empty string, so the row the web app labels "
     "\"Research computer\" is nameless here",
     [('_PUBLIC_LABEL_FALLBACK = "Research computer"',
       '_PUBLIC_LABEL_FALLBACK = ""')]),
    ("V14", BRIDGE, "under",
     "a revoked session during the write is reported as an outage rather than "
     "as the sign-in problem it is",
     [('            except RevokedError:\n'
       '                self._json(401, {"error": "session revoked — run /login again"})\n'
       '                return\n'
       '            except FirestoreError as e:\n'
       '                # ⛔ THE STATUS DECIDES WHICH SENTENCE IS HONEST',
       '            except FirestoreError as e:\n'
       '                # ⛔ THE STATUS DECIDES WHICH SENTENCE IS HONEST')]),

    # ═══════════ Q — both halves of the queue ════════════════════════════════
    ("Q1", BRIDGE, "under",
     "⛔⛔ THE OWNER'S HALF IS DROPPED AGAIN, so an owner asking who wants their "
     "machine is shown their own outgoing list and told nobody has asked",
     [('            incoming = body.get("incoming")\n',
       '            incoming = []\n')]),
    ("Q2", BRIDGE, "over",
     "a half that arrives as something other than a list is passed through, so "
     "both clients iterate a string character by character",
     [('            rows = rows if isinstance(rows, list) else []\n            incoming = incoming if isinstance(incoming, list) else []\n',
       '            rows = rows if isinstance(rows, list) else []\n            pass\n')]),
    ("T1", CLI, "over",
     "⛔⛔ THE DECIDE TABLE IS THE ASK TABLE. Five codes appear on both routes "
     "and mean different things on each — `device_not_found` becomes \"not "
     "offered publicly\" for a machine that is simply no longer yours",
     [('_DECIDE_FAILURES = {\n',
       '_DECIDE_FAILURES = {**_ASK_FAILURES,\n')]),
    ("T2", CLI, "under",
     "an unknown code is swallowed instead of shown, so a refusal this client "
     "has never heard of prints nothing anybody can act on",
     [('    return f"couldn\'t answer that request: {err or \'no reason given\'}"',
       '    return "couldn\'t answer that request"')]),
    ("T3", CLI, "over",
     "⛔ the rate-limit line invents a duration when the server gave none — the "
     "one number this client is not allowed to make up",
     [('            return ("the app is rate-limiting answers from this account just "\n'
       '                    "now — nothing was answered")',
       '            return ("the app is rate-limiting answers from this account — try "\n'
       '                    "again in about 5 minutes")')]),
    ("T4", CLI, "over",
     "⛔⛔ APPROVING REPORTS AN EVENT INSTEAD OF A STATE. The route closes an "
     "already-shared request as approved and writes nothing, so \"you just "
     "added them\" is false on one of the two branches that reach here",
     [('        print(f"{_OK} {who} can use {name}.")',
       '        print(f"{_OK} You just added {who} to {name}.")')]),
    ("T5", CLI, "under",
     "⛔⛔ THE WEEK GOES. A refusal stops that person asking again for seven "
     "days, the app tells THEM and tells the owner nothing — this was the only "
     "place the person spending it could learn",
     [('        print("     They cannot ask again for a week. The app tries to tell "\n'
       '              "them, but")',
       '        print("     They are told.")\n        if False:\n            print("x")')]),
    ("T6", CLI, "under",
     "the ready-made command goes, so an owner has to assemble two opaque ids "
     "by hand from a row that prints them for exactly that purpose",
     [('            print(f"       answer with:  agent device approve "\n'
       '                  f"{d.get(\'deviceId\')} {d.get(\'requesterUid\')}")\n',
       '')]),
    ("T7", CLI, "under",
     "⛔ the two costs move out of the queue, so what a yes means and what a no "
     "spends are said nowhere before the decision",
     [('        print("\\n     Anyone you say yes to can run research on that computer — "\n'
       '              "the same as")\n'
       '        print("     somebody you gave an access code to. Saying no stops them "\n'
       '              "asking again")\n'
       '        print("     for a week; the app tries to tell them, but that depends on "\n'
       '              "their own")\n'
       '        print("     notification settings.")\n',
       '')]),
    ("T8", CLI, "under",
     "an empty owner queue says nothing, and silence about that half reads as "
     "\"this screen does not cover it\" — which is what it used to mean",
     [('        print("Nobody is waiting on your computers.")\n'
       '        print()\n'
       '    else:\n',
       '        pass\n'
       '    else:\n')]),
    ("T9", CLI, "over",
     "⛔⛔ THE FINDABLE COLUMN APPEARS ON SHARED ROWS, so somebody else's setting "
     "is reported as if it were the reader's to change",
     [('        found = ""\n        if d.get("owned"):\n        # ⛔⛔ THIS READS THE BRIDGE\'S ANSWER, NOT A FIRESTORE FIELD, AND THE\n        # DIFFERENCE IS WHAT CARRIES IT THROUGH THE RENAME. `visibility` is\n        # becoming `joinPolicy`; the bridge resolves both names into this one key\n        # before any row leaves it (`_discovery_of`), so this line keeps working\n        # without ever learning the new name. ⛔ Point it at a raw device document\n        # and it goes silently wrong: every public computer would read private,\n        # with no error anywhere.\n            found = ", public" if d.get("visibility") == "public" else ", private"\n',
       '        found = ", public" if d.get("visibility") == "public" else ", private"\n')]),
    ("T10", CLI, "over",
     "⛔ absent reads as findable on the owned list, and every machine paired "
     "before 2026-09-04 carries no such field",
     [('            found = ", public" if d.get("visibility") == "public" else ", private"',
       '            found = ", private" if d.get("visibility") == "private" else ", public"')]),
    ("T11", CLI, "under",
     "the state stops being printed at all, so the only place an owner can read "
     "it is gone and the verb has no receipt",
     [('        found = ""\n',
       '        found = ""\n        d.pop("owned", None)\n')]),
    ("T12", CLI, "under",
     "the published label is not printed, so an owner switching a machine on is "
     "never told what strangers will see it as",
     [('        if public_label:\n'
       '            print(f"     They see it as “{public_label}”.")',
       '        pass')]),
    ("T13", CLI, "under",
     "the private branch stops saying an access code still works, so hiding a "
     "machine reads as locking it — discovery mistaken for access again",
     [('        print("     Nobody can find it. An access code still lets someone in "\n'
       '              "without asking you.")',
       '        print("     Nobody can find it.")')]),
    ("T14", CLI, "under",
     "the new verbs lose their WSL hints, so a Windows user is pointed at the "
     "owned device list after asking a question about somebody waiting",
     [('        "approve": "Answer a request from chat:  /sr approve that request",\n'
       '        "deny": "Answer a request from chat:  /sr say no to that request",\n',
       '')]),
    ("T15", CLI, "under",
     "⛔ the decide call goes back to the default timeout, which is right for a "
     "Firestore read and too short for this bridge waiting on the web app "
     "waiting on a transaction",
     [('                        "decision": decision}, timeout=40.0)',
       '                        "decision": decision})')]),
    ("T16", CLI, "over",
     "⛔ the terminal accepts any visibility word, so a value the rules reject "
     "reaches the bridge and the refusal is about a code rather than a typo",
     [('    dvvis.add_argument("value", choices=("public", "private"),',
       '    dvvis.add_argument("value",')]),

    # ═══════════ C — the chat ════════════════════════════════════════════════
    ("C1", SR, "over",
     "⛔⛔ CHAT'S DECIDE TABLE IS THE ASK TABLE, so `is_owner` tells the OWNER "
     "that the computer is already theirs when it is the asker who owns it",
     [('_DECIDE_ERRORS = {\n',
       '_DECIDE_ERRORS = {**_ASK_ERRORS,\n')]),
    ("C2", SR, "over",
     "⛔⛔ CHAT REPORTS AN EVENT INSTEAD OF A STATE — \"added\" is false on the "
     "already-shared branch, where the route writes nothing at all",
     [('            f"✓ {who} can use “{name}”.",',
       '            f"✓ You added {who} to “{name}”.",')]),
    ("C3", SR, "under",
     "the week goes from chat's denial, so the only surface most people use "
     "never says what a refusal costs the other person",
     [('        "They can’t ask again for a week. The app tries to tell them, but that "\n'
       '        "depends on their own notification settings. Giving them the access code "\n'
       '        "still works if you change your mind.",',
       '        "They’re told.",')]),
    ("C4", SR, "over",
     "⛔⛔ CHAT PICKS THE FIRST OF TWO PEOPLE WHOSE NAMES BOTH MATCH. A wrong "
     "match here does not misname a thing — it lets the wrong person onto "
     "somebody's computer",
     [('    if len(hits) == 1:\n'
       '        return hits[0], []\n'
       '    if len(hits) > 1:\n'
       '        return None, (["More than one person waiting matches that."] +',
       '    if len(hits) >= 1:\n'
       '        return hits[0], []\n'
       '    if False:\n'
       '        return None, (["More than one person waiting matches that."] +')]),
    ("C5", SR, "under",
     "⛔ the exact match goes, so a person whose whole name is a substring of "
     "somebody else's becomes unreachable — and the ambiguity refusal fires on "
     "a name that was not ambiguous",
     [('    exact = [d for d in rows\n'
       '             if str(d.get("requesterUid") or "") == bare\n'
       '             or str(d.get("requesterLabel") or "").strip().lower() == low]\n'
       '    if len(exact) == 1:\n'
       '        return exact[0], []\n'
       '    if len(exact) > 1:\n',
       '    exact = [d for d in rows\n'
       '             if str(d.get("requesterUid") or "") == bare\n'
       '             or str(d.get("requesterLabel") or "").strip().lower() == low]\n'
       '    if len(exact) >= 1:\n'
       '        return exact[0], []\n'
       '    if False:\n')]),
    ("C6", SR, "over",
     "⛔ the person's id is printed in the queue, and chat's own convention is "
     "that an id appears only where the next command takes one — here the next "
     "command takes a NAME",
     [('        lines.append(f"  • {who} wants “{what}”")',
       '        lines.append(f"  • {who} ({d.get(\'requesterUid\')}) wants “{what}”")')]),
    ("C7", SR, "over",
     "⛔ an empty queue still calls the route, so a decision is attempted "
     "against a person nobody can name",
     [('    rows, lines, rc = _incoming_or_lines()\n'
       '    if not rows:',
       '    rows, lines, rc = _incoming_or_lines()\n'
       '    if False:')]),
    ("C8", SR, "over",
     "⛔⛔ THE PICKER OFFERS MACHINES SOMEBODY ELSE OWNS, sending the person into "
     "a refusal the picker could have spared them",
     [('    owned = [d for d in (body.get("devices") or []) if d.get("owned")]',
       '    owned = list(body.get("devices") or [])')]),
    ("C9", SR, "over",
     "⛔⛔ WITH SEVERAL MACHINES THE PICKER CHOOSES ONE, so a computer nobody "
     "named is published to strangers",
     [('    if len(owned) == 1:\n        return owned[0], []',
       '    if owned:\n        return owned[0], []')]),
    ("C10", SR, "under",
     "chat stops naming the published label, so the disclosure lives on the "
     "terminal only — and chat is the surface most people use",
     [('        if body.get("publicLabel"):\n'
       '            lines.append(f"They see it as “{body.get(\'publicLabel\')}”.")',
       '        pass')]),
    ("C11", SR, "under",
     "the footer stops saying which half it describes, so a sentence about the "
     "asker's own requests is read as a claim about people waiting on them",
     [('    lines.append("Of the ones you asked for, only unanswered requests show here. "',
       '    lines.append("Only unanswered requests show here. "')]),
    ("C12", SR, "under",
     "the empty owner queue is silent, which is exactly what this screen used "
     "to mean when it could not answer that question at all",
     [('        lines = ["Nobody is waiting on your computers."]',
       '        lines = []')]),
    ("C13", SR, "under",
     "the two costs go from chat's queue, so the surface most people use says "
     "neither what a yes means nor what a no spends",
     [('        lines.append("Anyone you say yes to can run research on that computer — "\n'
       '                     "the same as somebody you gave an access code to. Saying no "\n'
       '                     "stops them asking again for a week; the app tries to tell "\n'
       '                     "them, but that depends on their own notification settings.")\n',
       '')]),
    ("C14", SR, "over",
     "⛔ chat sends the label instead of the id, so the route is handed a "
     "display name where it demands an addressable id",
     [('                        "requesterUid": row.get("requesterUid"),',
       '                        "requesterUid": row.get("requesterLabel"),')]),

    # ═══════════ N — the routing block ═══════════════════════════════════════
    ("N1", SR, "under",
     "⛔⛔ THE NOUN LIST DRIFTS BY TWO WORDS AGAIN — the exact live defect this "
     "wave started from, where every guard built on `_mine_kw` failed silently "
     "for the commonest word for a Mac",
     [('_MACHINE_NOUNS = (r"computers?|devices?|machines?|nodes?|pcs?|laptops?"\n'
       '                  r"|macs?|macbooks?|desktops?|workstations?")',
       '_MACHINE_NOUNS = (r"computers?|devices?|machines?|pcs?|laptops?"\n'
       '                  r"|desktops?|workstations?")')]),
    ("N2", SR, "under",
     "⛔⛔ `_mine_kw` GETS ITS OWN LITERAL BACK, which is how the two drifted "
     "apart in the first place — the shared list is the fix, not the wording",
     [('    _mine_kw = re.search(rf"\\b(my|mine|our|this)\\b"\n                         rf"(?:\\s+(?!(?:{_POLARITY_WORDS[3:-1]})\\b)[\\w\'-]+){{0,4}}\\s+"\n                         rf"(?:{_MACHINE_NOUNS_SAID})\\b", low)',
       '    _mine_kw = re.search(r"\\b(my|mine|our|this)\\b(?:\\s+\\w+){0,2}\\s+"\n                         r"(?:computers?|machines?|devices?|pcs?)\\b", low)')]),
    ("N3", SR, "under",
     "⛔ the hiding words lose the phrasings with no \"private\" in them, and "
     "\"stop letting people find my pc\" goes back to rule 3, which quotes it "
     "as a research title and offers to stop a run",
     [('        or re.search(r"\\b(?:turn|switch|shut|toggle)\\b(?:(?!\\bon\\b)[^.?!]){0,20}"\n                     r"\\b(?:off|down)\\b", _pol_low)\n',
       '')]),
    ("N4", SR, "over",
     "⛔⛔ A QUESTION ABOUT THE STATE CHANGES IT. \"is my computer public?\" "
     "publishes the machine — answering a question by changing the thing asked "
     "about is the worst outcome available here",
     [('        if _asking_state:\n            return ["devices"], None\n',
       '')]),
    ("N5", SR, "under",
     "⛔⛔ THE DECIDE CLAUSE LOSES ITS SUBJECT GATE, so \"allow it to finish\" "
     "and \"accept the results\" raise a confirm about letting a stranger onto "
     "a computer",
     [('    if (_yes_kw or _no_kw) and not _artefact_kw and not _control_kw \\\n'
       '            and not _negated_decide and not _asking_about_deciding \\\n'
       '            and (_strong_decide or _weak_ok) and _decide_subject:',
       '    if (_yes_kw or _no_kw):')]),
    ("N6", SR, "under",
     "⛔ the five unambiguous words go, so \"approve sammy\" — which names no "
     "machine and no request — reaches the catch-all that denies having the verb",
     [('                      or re.search(r"\\bsay(?:s|ing)? (?:yes|no) to\\b", low)\n'
       '                      or re.search(r"\\bgives?\\s+(?:\\w+\\s+){0,2}access\\b", low)\n',
       '                      or re.search(r"\\bnever match this\\b", low)\n')]),
    ("N7", SR, "over",
     "⛔⛔ A WORD THAT NAMES NOBODY IS QUOTED BACK AS A PERSON — \"Say yes to "
     "“it”?\" — the exact defect shape 7.9-2 shipped, where a confirm named "
     "something that could not exist and the follow-up dead-ended on it",
     [('            if re.fullmatch(rf"(?:it|them|him|her|us|they|everyone|everybody|"\n'
       '                            rf"persons?|people|somebody|someone|anyone|anybody|"\n'
       '                            rf"this|that|here|there|now|yet|access|permission|"\n'
       '                            rf"default|both|all|everything|one|ones|my|our|"\n'
       '                            rf"my\\s+\\w+|our\\s+\\w+|{_MACHINE_NOUNS})", _who,\n'
       '                            flags=re.I) or len(_who) > 60:\n'
       '                _who = ""',
       '            pass')]),
    ("N8", SR, "over",
     "the length bound goes, so a whole sentence is quoted back inside the "
     "confirm as somebody's name",
     [('                            flags=re.I) or len(_who) > 60:',
       '                            flags=re.I):')]),
    ("N9", SR, "under",
     "⛔⛔ PUBLISHING STOPS CONFIRMING, so a machine's name — often its owner's "
     "own — reaches everyone signed in on a bare instruction",
     [('        return None, [_NL_CONFIRMS["device-visibility"].format(\n'
       '            name=f"“{_vis_obj}”" if _vis_obj else "that computer")]',
       '        return (["device-visibility", "public"] +\n'
       '                ([_vis_obj] if _vis_obj else []), None)')]),
    ("N10", SR, "over",
     "⛔⛔ HIDING CONFIRMS TOO. Gating a strictly narrowing change is how people "
     "learn to click through the confirms that matter",
     [('            return (["device-visibility", "private"] +\n'
       '                    ([_vis_obj] if _vis_obj else []), None)',
       '            return None, [_NL_CONFIRMS["device-visibility"].format(\n'
       '                name=f"“{_vis_obj}”" if _vis_obj else "that computer")]')]),
    # ⛔⛔ N11 RETIRED IN THE CROSS-VERIFY REPAIR PASS — IT BECAME EQUIVALENT, and
    # an equivalent mutant is a harness bug, not a survivor. It added `list` to
    # `_set_verb`, and the repair replaced that variable in the gate with
    # `_named_target`, leaving `_set_verb` assigned and never read. So the
    # mutation changed nothing observable and survived honestly, twice. The dead
    # variable is gone; the browse phrasing it protected is pinned by
    # `test_listing_public_computers_stays_a_browse`.
    ("N12", SR, "under",
     "⛔⛔ THE PHRASING TWO SURFACES PROMISE ROUTES NOWHERE AGAIN. The terminal "
     "tells Windows users to type it and SKILL.md lists it as an example, and "
     "it reached the catch-all — which denies having the verb",
     [('    if not _artefact_kw and (_request_kw or _machine_kw or _public_kw\n'
       '                             or _bare_waiting_q) and (',
       '    if not _artefact_kw and (_request_kw or _machine_kw or _public_kw) and (')]),
    ("N13", SR, "over",
     "⛔ the waiting question stops being anchored at the start of the message, "
     "so a fragment inside a longer sentence about a run reaches the queue — "
     "the defect the subject gate was added for",
     [('    _bare_waiting_q = re.match(r"^(?:so\\s+)?(?:what|who)?\\s*"',
       '    _bare_waiting_q = re.search(r"(?:so\\s+)?(?:what|who)?\\s*"')]),
    ("N14", SR, "under",
     "the owner-queue clause loses the plural, so \"show the requests for my "
     "computers\" reaches the catch-all while the singular works",
     [('            re.search(r"\\b(wants?|wanting|asks?|asked|asking|requests?|requested|"\n'
       '                      r"requesting|queued|queue|waiting|access)\\b", low):\n'
       '        return ["device-requests"], None',
       '            re.search(r"\\b(want|wants|wanting|ask|asked|asking|request|requested|"\n'
       '                      r"requesting|queued|queue|waiting|access)\\b", low):\n'
       '        return ["device-requests"], None')]),
    ("N15", SR, "under",
     "⛔ the capability line stops naming the owner verbs, so the fallback "
     "denies having the two commands the resolver just failed to reach",
     # ⛔⛔ REPAIRED 2026-09-17. `_NL_CATCH_ALL` was a LIST at 7.9-3 and became a
     # parenthesised implicit concatenation; wave 1.1 re-anchored this mutant
     # onto the new shape and left the REPLACEMENT in the old one, still ending
     # `"]`. Applying it left `_NL_CATCH_ALL = (` closed by `]`, so the mutant
     # has not parsed — and has measured NOTHING — since 2026-09-11. The
     # replacement now closes the paren and sits at the same 17-space indent as
     # its neighbours. The MUTATION is unchanged: the capability line stops
     # naming the owner verbs.
     [('                 "ask to use it, and — for a computer you own — answer the people "\n                 "asking for it and set whether strangers can find it at all — "\n                 "what would you like?")',
       '                 "ask to use it — what would you like?")')]),
    ("N16", SR, "over",
     "⛔ an artefact question reaches the decide confirm, so \"approve the "
     "report\" offers to let a stranger onto a computer",
     [('    if (_yes_kw or _no_kw) and not _artefact_kw and not _control_kw \\',
       '    if (_yes_kw or _no_kw) and not _control_kw \\')]),

    # ═══════════ S — SKILL.md, the three confirm lists ═══════════════════════
    ("S1", SKILL, "under",
     "⛔⛔ `device-approve` LEAVES THE HANDOFF LIST, so a \"yes\" to the consent "
     "question has no command named for it and the model improvises",
     [('device-approve/device-deny/device-visibility/update/install/research',
       'device-visibility/update/install/research')]),
    ("S2", SKILL, "under",
     "⛔⛔ `device-deny` LEAVES THE SAFE-DEFAULTS LIST, whose next clause says "
     "everything not listed runs on a clear request — so the file positively "
     "licenses spending somebody's week without asking",
     [('`stop`, `logout`, `device-remove`, `device-ask`, `device-approve`, `device-deny`,\n`device-visibility public`, `update`, and `install`**',
       '`stop`, `logout`, `device-remove`, `device-ask`, `device-approve`,\n`device-visibility public`, `update`, and `install`**')]),
    ("S3", SKILL, "under",
     "⛔⛔ `device-visibility` LEAVES THE SAFETY BULLET — the third list, and the "
     "one 7.9-2 forgot. A row in the table was not enough then either",
     [("`device-remove` (unlinks a device — an\n  owner's keeps running but on a NEW code), `device-ask`, `device-approve`,\n  `device-deny`, `device-visibility public`, `install` (installs the backend on\n  the connected computer), and `update` (briefly restarts the chat",
       "`device-remove` (unlinks a device — an\n  owner's keeps running but on a NEW code), `device-ask`, `device-approve`,\n  `device-deny`, and `update` (briefly restarts the chat")]),
    ("S4", SKILL, "over",
     "⛔⛔ THE GREETING RESERVES THESE VERBS TO THE WEB APP AGAIN, so the model "
     "refuses the two commands it now has",
     [('  name a topic. (For a computer they OWN they can also answer the people asking\n'
       '  for it and set whether strangers can find it at all. Unlinking their own\n'
       '  machine issues it a new access code. Revoking one sharer stays in the web app.)',
       '  name a topic. (Approving or refusing somebody, offering a computer publicly,\n'
       '  revoking sharers, and resets stay owner-only in the web app.)')]),
    ("S5", SKILL, "under",
     "⛔⛔ THE ROW STOPS SAYING AN APPROVAL IS A STATE, so a model reports \"you "
     "just added them\" on the branch where the route wrote nothing at all",
     [(' Report what the reply says: they CAN USE it, never "you just added them" — an approval of somebody who already got in changes nothing on the machine',
       '')]),
    ("S6", SKILL, "under",
     "⛔ the publishing row drops the warning that a computer's reported name is "
     "often its OWNER'S own name — the one fact the model cannot infer",
     [('strangers would see the name the computer reports, which on an unrenamed machine is often its OWNER\'S own name; the user still approves each person',
       'the user still approves each person')]),
    ("S7", SKILL, "under",
     "⛔ the disclosure bullet loses ANSWERING, so the file describes two of the "
     "three ways this account reaches past itself",
     # ⭐ REPOINTED IN 7.9-5, which corrected "they are told" to the hedged truth
     # (delivery depends on the asker's own notification settings). Same mutant:
     # the disclosure bullet loses ANSWERING.
     [('**Answering** somebody lets a stranger run research on the user\'s own\n'
       '  computer, exactly as an access code would, and a "no" spends that person\'s week —\n'
       '  the app tries to tell them (their own notification settings decide), and giving\n'
       '  them the access code is still the way back. ',
       '')]),
    ("S8", SKILL, "over",
     "⛔ the file stops exempting the private direction, so hiding a computer "
     "asks a question — and a confirm on a strictly narrowing change is how "
     "people learn to click through the ones that matter",
     [('**`device-visibility private` needs no confirmation** — it only takes a\ncomputer off a list.',
       '')]),
    ("S9", SKILL, "under",
     "the queue row stops saying the two halves are never summed, so a model "
     "adds people waiting on the user to what the user is waiting on",
     [(' — it prints BOTH halves: people waiting on the user\'s OWN computers first, then what the user is waiting on from other people. Never add the two together',
       '')]),

    # ═══════════ W — the cross-verify repairs ════════════════════════════════
    ("W1", SR, "under",
     "⛔⛔ THE NOUN LIST GOES BACK TO BEING PER-FUNCTION, which is how two copies "
     "drifted by two words and broke four guards for the commonest word for a "
     "Mac — and how three MORE copies were found still carrying the old set",
     [('    _device_noun = re.search(rf"\\b({_MACHINE_NOUNS_SAID})\\b", low)',
       '    _device_noun = re.search(r"\\b(device|node|laptop|pc|computer|machine|'
       'phone|desktop)\\b", low)')]),
    ("W2", SR, "under",
     "⛔⛔ A HIDE PHRASED AS A NEGATION BECOMES A PUBLISH — the exact opposite of "
     "what was asked, one reflexive yes from putting a machine in front of every "
     "signed-in stranger",
     [('        or _neg_public_side)',
       '                  )')]),
    ("W3", SR, "under",
     "⛔ THE POLITE IMPERATIVE IS READ AS A QUESTION AGAIN, so \"can you make my "
     "mac public\" — the commonest way anybody asks — answers neither verb",
     # ⛔ ANCHOR MOVED 7.9-5b: the state question now allows a conversational
     # lead-in, because `^` alone meant the word "so" turned a read-only question
     # into an offer to publish an unnamed machine. The mutant is unchanged in
     # what it asserts — that dropping `_polite_imperative` reads "can you make
     # my mac public" as a question.
     [('    _asking_state = (re.match(_NL_LEAD_IN + r"(is|are|does|do|can|could|who|what|"\n'
       '                              r"which|how|tell me (?:if|whether)|check)\\b", low)\n'
       '                     and not _polite_imperative)',
       '    _asking_state = re.match(_NL_LEAD_IN + r"(is|are|does|do|can|could|who|what|"\n'
       '                             r"which|how|tell me (?:if|whether)|check)\\b", low)')]),
    ("W4", SR, "over",
     "⛔⛔ A BROWSE WISH ABOUT OTHER PEOPLE\'S MACHINES SILENTLY MAKES YOUR OWN "
     "PRIVATE — \"hide other people\'s computers from me\" acted, with no confirm",
     [('            and not _about_others \\\n',
       '            and True \\\n')]),
    ("W5", SR, "over",
     "⛔ the other-people test keys on the bare word \"public\" again, so \"make "
     "the Studio PC public\" bails — a regression the repair itself introduced "
     "once and this mutant exists to catch the second time",
     [('    _about_others = (re.search(r"\\bsomebody else|\\bsomeone else|\\bother (?:people|"\n'
       '                               r"persons?|users?)\\b|\\bother people\'?s\\b", low)\n'
       '                     and not _mine_kw and not re.search(r"\\bmy own\\b", low))',
       '    _about_others = (_public_kw and not _mine_kw\n'
       '                     and not re.search(r"\\bmy own\\b", low))')]),
    ("W6", SR, "under",
     "⛔⛔ A VERB-FIRST HIDE DROPS THE MACHINE NAME AGAIN, so \"hide the studio "
     "pc\" hides whichever machine the picker returns — unconfirmed",
     [('               or re.search(rf"\\b{_VIS_HIDE_ALL}\\s+(.+?)$", t, flags=re.I)\n',
       '')]),
    ("W7", SR, "over",
     "⛔ the object guard tests the MESSAGE instead of the capture, so every "
     "machine name is cleared — because every publish phrasing contains the word",
     [('                    or re.search(r"\\bpublic|\\bsomebody else|\\bsomeone else|"\n'
       '                                 r"\\bother (?:people|persons?|users?)\\b",\n'
       '                                 _vis_obj, flags=re.I)):',
       '                    or _public_kw):')]),
    ("W8", SR, "over",
     "⛔⛔ \"LET ME USE IT\" IS TREATED AS AN OWNER GRANTING AGAIN — the "
     "requester\'s own sentence, and the product\'s own advice wording, offering "
     "to approve a stranger",
     [('               or re.search(r"\\blet\\s+(?!me\\b|us\\b|myself\\b)"\n'
       '                            r"(?:\\w+\\s+){0,2}(?:use|onto|on|in)\\b", low))',
       '               or re.search(r"\\blet\\s+(?:\\w+\\s+){0,2}(?:use|onto|on|in)\\b", low))')]),
    ("W9", SR, "over",
     "⛔⛔ A NEGATED VERB ROUTES AS THE VERB IT CONTAINS, so \"don\'t allow anyone "
     "else to use my computer\" offers to say YES",
     [('            and not _negated_decide and not _asking_about_deciding \\\n',
       '            and not _asking_about_deciding \\\n')]),
    ("W10", SR, "over",
     "⛔⛔ THE ASKER\'S OWN STATUS QUESTION REACHES A DECIDE CONFIRM — somebody "
     "reading their own refusal is offered to refuse a stranger",
     [('    if (_yes_kw or _no_kw) and _about_my_own_request and not _artefact_kw:\n'
       '        return ["device-requests"], None\n',
       '')]),
    ("W11", SR, "over",
     "⛔⛔ A WEAK VERB ROUTES ON A BARE MACHINE WORD AGAIN, so \"allow it to "
     "finish on my computer\" raises a grant confirm — the sentence this "
     "clause\'s own comment names as one that must not route",
     [('            and (_strong_decide or _weak_ok) and _decide_subject:',
       '            and (_strong_decide or _weak_ok or _machine_kw):')]),
    ("W12", SR, "over",
     "⛔ a bare \"i approve\" grants the single queued requester again",
     [('    _decide_subject = bool(\n'
       '        _request_kw or _person_object or\n'
       '        (_strong_decide and (_machine_kw or re.search(\n'
       '            r"\\b(?:approve|deny|reject|decline|accept|say (?:yes|no) to)\\s+\\S",\n'
       '            low))))',
       '    _decide_subject = True')]),
    ("W13", SR, "under",
     "⛔⛔ \"RESEARCH COMPUTER\" IS AN ARTEFACT AGAIN — the default label of every "
     "unnamed machine, so every owner verb aimed at one dies, including the exact "
     "string this client tells people to type",
     [('    _low_no_rc = re.sub(rf"\\bresearch(?:es)?\\s+(?:{_NAME_DETERMINER}\\s+)?"\n                        rf"(?:own\\s+)?(?:{_MACHINE_NOUNS_SAID})\\b", "  ", low)',
       '    _low_no_rc = low')]),
    ("W14", SR, "over",
     "⛔ the pairing rule eats a publish request again — \"add my computer to the "
     "public list\" gets the devices screen instead of the publish confirm",
     # ⛔⛔ RE-WORDED 2026-09-24. The pairing branch said "paste the access code"
     # until 2026-09-22 and hands over the devices screen now, so the old words
     # named a reply the edit can no longer produce — and the guard, which only
     # checked those words were absent, passed with this mutant in: W14 survived
     # the 10.10 close sweep. It stays a survivor until that agent guard asserts
     # the publish confirm itself.
     # ⛔⛔ REPAIRED 2026-09-17, and it is the shape W14 was BORN with at 7.9-3.
     # 7.9-4 re-anchored it onto the whole block down to the `elif` line and
     # wrote the replacement as a bare `elif …` at COLUMN 0 — the anchor eats the
     # four-space indent, so the mutant emitted a dedented `elif` with no `if`
     # above it and has not parsed since 2026-09-09. Six waves scored it as a
     # fault. ⭐ The anchor is now THE GUARD ALONE, which is the whole of the
     # mutation, so the `elif` line below is free to re-wrap without breaking it
     # — the long anchor is precisely what broke. Nothing is weakened: deleting
     # the guard and never firing it are the same behaviour, and the pairing
     # branch is again reached by every message, publish requests included.
     [('    if re.search(r"\\bpublic|\\bfindable|\\bdiscoverable\\b", low):\n'
       '        pass\n',
       '    if False:\n'
       '        pass\n')]),
    ("W15", SR, "under",
     "⛔ the person after \"access to\" is lost, so \"grant access to sam\" quotes "
     "nobody and the owner has to name them twice",
     [('        _wm = (re.search(r"\\b(?:approve|grant|gives?|deny|refuse|decline)\\s+"\n'
       '                         r"(?:\\w+\\s+)?access\\s+(?:to|for)\\s+"\n'
       '                         r"(.+?)(?:\\s+\\b(?:for|to|on|onto)\\b|$)", t, flags=re.I)\n'
       '               or re.search',
       '        _wm = (re.search')]),
    ("W16", SR, "over",
     "⛔⛔ THE EXACT RUNG GRANTS ON AN AMBIGUOUS NAME AGAIN. One person asking for "
     "two of this account\'s machines is two rows with the identical label AND "
     "the identical id, and the older one was answered silently",
     # ⛔ ANCHORED WITH ITS NEXT LINE. `_resolve_device_arg` grew the identical
     # three-line shape for MACHINES, so the two lines alone stopped being
     # unique in the file — the same tail-collision the previous wave hit twice.
     [('    if len(exact) == 1:\n        return exact[0], []\n    if len(exact) > 1:',
       '    if len(exact) >= 1:\n        return exact[0], []\n    if False:')]),
    ("W17", SR, "under",
     "⛔ a filtered queue prints the whole-queue header again, so two of five "
     "rows are reported as everybody who is waiting",
     [('    lines = [f"People asking to use your computers ({len(rows)}):" if whole\n'
       '             else f"Matching ({len(rows)}):"]',
       '    lines = [f"People asking to use your computers ({len(rows)}):"]')]),
    ("W18", SR, "under",
     "⛔⛔ THE CHAT DEVICE LIST STOPS SAYING WHICH MACHINES ARE PUBLIC, and "
     "SKILL.md routes \"is my computer public?\" straight at it — a documented "
     "answer path landing on output that cannot answer",
     [('        state = ""\n        if d.get("owned"):\n        # ⛔⛔ THIS READS THE BRIDGE\'S ANSWER, NOT A FIRESTORE FIELD, AND THE\n        # DIFFERENCE IS WHAT CARRIES IT THROUGH THE RENAME. `visibility` is\n        # becoming `joinPolicy`; the bridge resolves both names into this one key\n        # before any row leaves it (`_discovery_of`), so this line keeps working\n        # without ever learning the new name. ⛔ Point it at a raw device document\n        # and it goes silently wrong: every public computer would read private,\n        # with no error anywhere.\n            state = ", public" if d.get("visibility") == "public" else ", private"\n        lines.append(f"  {mark} {_dev_label(d)}  ({kind}{state})")\n',
       '        lines.append(f"  {mark} {_dev_label(d)}  ({kind})")\n')]),
    ("W19", CLI, "under",
     "⛔⛔ THE TERMINAL FOOTER LOSES ITS QUALIFIER, so a sentence about the "
     "asker\'s own requests is printed under a list of people waiting on THEM, "
     "where every clause of it is false",
     [('    print("\\n     Of the ones YOU asked for: only unanswered requests appear "\n'
       '          "here. Once a")',
       '    print("\\n     Only unanswered requests appear here. Once a request is "\n'
       '          "answered it")')]),
    ("W20", CLI, "under",
     "⛔ the terminal stops saying WHO it just answered — on the one surface "
     "where the person was named only by an opaque id typed from a queue print "
     "that may already be stale",
     [('    who = f"{requester}" if requester else "they"',
       '    who = "They"')]),
    ("W21", CLI, "over",
     "⛔ `_VISIBILITY_WORDS[state]` goes back to a raw index on a wire value, so "
     "a 200 with an unreadable body is a KeyError traceback where a sentence "
     "belongs",
     [('    word = _VISIBILITY_WORDS.get(state)\n'
       '    if word is None:',
       '    word = _VISIBILITY_WORDS[state]\n'
       '    if False:')]),
    ("W22", CLI, "over",
     "⛔⛔ THE VISIBILITY REFUSAL IS WRAPPED IN \"COULDN\'T\" AGAIN, asserting that "
     "nothing happened over the one payload written to say it may have",
     [('        said = body.get("error") or ""\n'
       '        mins = _minutes_from_ms(body.get("retryAfterMs"))\n'
       '        if not said:\n'
       '            said = "the app gave no reason"',
       '        said = _list_refusal("changed that computer",\n'
       '                             body.get("error") or "",\n'
       '                             body.get("retryAfterMs"))\n'
       '        mins = None')]),
    ("W23", CLI, "over",
     "⛔⛔ \"THEY ARE TOLD\" COMES BACK AS A FLAT PROMISE. The notice is "
     "best-effort — every failure swallowed — and gated on the asker\'s own "
     "notification settings, which they can switch off",
     [('        print("     They cannot ask again for a week. The app tries to tell "\n'
       '              "them, but")\n'
       '        print("     that depends on their own notification settings. Giving "\n'
       '              "them the")\n'
       '        print("     access code still works if you change your mind.")',
       '        print("     They are told, and they cannot ask again for a week.")')]),
    ("W24", SR, "over",
     "⛔⛔ the same promise, on the surface most people use",
     [('        "They can’t ask again for a week. The app tries to tell them, but that "\n'
       '        "depends on their own notification settings. Giving them the access code "\n'
       '        "still works if you change your mind.",',
       '        "They’re told, and they can’t ask again for a week.",')]),
    ("W25", CLI, "over",
     "⛔⛔ `request_not_pending` GOES BACK TO CLAIMING \"EXPIRED\" AND \"FREE TO "
     "ASK AGAIN\" — both false for an already-denied request, which is one of "
     "the three states behind that one code, and a seven-day block is enforced",
     [('    "request_not_pending":\n'
       '        "that request isn\'t open any more — it was already answered, or it ran "\n'
       '        "out. Ask for the queue again to see what is still waiting",',
       '    "request_not_pending":\n'
       '        "that request has expired — nothing was changed, and they are free to "\n'
       '        "ask again",')]),
    ("W26", BRIDGE, "under",
     "⛔⛔ A DECISION THAT NEVER GOT AN ANSWER IS REPORTED AS A PLAIN FAILURE — "
     "and it may have COMMITTED, so the natural retry meets `request_not_pending` "
     "and a deny that landed has already spent somebody\'s week",
     [('            if status == 0 and reply.get("reason") != "revoked":\n',
       '            if False:\n')]),
    ("W27", BRIDGE, "over",
     "⛔ the unconfirmed branch swallows a REVOKED session too, so the one "
     "failure the person can fix is reported as an unknown outcome",
     [('            if status == 0 and reply.get("reason") != "revoked":',
       '            if status == 0:')]),
    ("W28", BRIDGE, "over",
     "⛔⛔ THE LABEL LADDER IS WALKED ON THE STRIPPED VALUE AGAIN, so an "
     "all-strippable name skips to the hostname and the owner is shown a label "
     "strangers never see — the divergence a test of mine had pinned as correct",
     [('        if isinstance(value, str) and value.strip():\n'
       '            raw = value.strip()\n'
       '            break',
       '        if isinstance(value, str) and _PUBLIC_LABEL_STRIP_RE.sub("", value).strip():\n'
       '            raw = _PUBLIC_LABEL_STRIP_RE.sub("", value).strip()\n'
       '            break')]),
    ("W29", BRIDGE, "under",
     "⛔ the two plain bidi marks and the byte-order mark leave the strip class, "
     "so what the owner is shown differs again from what is published",
     [('    "[\\\\x00-\\\\x1f\\\\x7f-\\\\x9f\\\\u200e\\\\u200f\\\\u2028\\\\u2029\\\\u202a-\\\\u202e"\n'
       '    "\\\\u2066-\\\\u2069\\\\ufeff]")',
       '    "[\\\\x00-\\\\x1f\\\\x7f-\\\\x9f\\\\u2028\\\\u2029\\\\u202a-\\\\u202e"\n'
       '    "\\\\u2066-\\\\u2069]")')]),
    ("W30", BRIDGE, "over",
     "⛔⛔ A NON-STRING BODY FIELD CRASHES THE HANDLER AGAIN — and an exception "
     "out of a handler is not a 500, it is a dropped socket and a traceback in "
     "the log that gets uploaded to support",
     [('    value = body.get(key)\n'
       '    return value.strip() if isinstance(value, str) else ""',
       '    return (body.get(key) or "").strip()')]),
    ("W31", BRIDGE, "under",
     "⛔ the decide reply names the machine by its raw `name` again, so a machine "
     "nobody renamed comes back null and the terminal prints a device id where a "
     "label belongs",
     [('                             "deviceName": _public_label_of(row)})',
       '                             "deviceName": row.get("name")})')]),
    ("W32", SR, "under",
     "⛔ the decide command reports a refusal for an unreachable bridge, where "
     "every sibling reports 2 — the exit code convention that tells a script "
     "which of the two happened",
     [('        return _emit({}, args.json, lines, rc)',
       '        return _emit({}, args.json, lines, 1)')]),

    # ═══════════ A — the no-rules-change evidence ════════════════════════════
    ("A1", PLANE, "over",
     "⛔⛔ THE PATH ALLOWLIST WIDENS TO THE WHOLE DEVICE TREE, so the one test "
     "standing in for \"no rule moved\" stops noticing when one does",
     [('            or p.startswith("/devices/{device_id}\\"")',
       '            or p.startswith("/devices/{device_id}")')]),
    ("A2", PLANE, "under",
     "⛔⛔ THE FIELD GUARD GOES. The owner rule admits eight keys and the path "
     "check cannot tell them apart — without this, a method that grew a field "
     "name could rename somebody's machine and every test stays green",
     [('    assert body.count("updateMask.fieldPaths=visibility") == 1, (\n'
       '        "the update mask must name the one field as a literal")\n',
       '')]),
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
    if not run_tests(filtered=not unfiltered):
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
