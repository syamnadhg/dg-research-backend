"""Mutation harness — Allow all, the chat assistant's half (wave 12, 2026-09-26).

⛔⛔ WHAT THIS CODE DECIDES.
  G* — bridge: who reads as "anyone can join" — public FIRST (by `_discovery_of`,
       never the literal field) AND strictly `True`; both prunes carry the bit.
  V* — bridge `/device/visibility`: ON is ONE patch that publishes too; OFF is
       `allowAll` alone; going private is `visibility` alone and FIRST, then a
       best-effort clear only if a tick was stored; a re-publish never brings an
       old tick back; the no-op compares BOTH fields.
  J* — bridge `/device/ask` answered "joined": never parked for the watcher,
       clears a parked ask for THAT computer, selects it only when nothing was
       routable before the join (repair 1, 2026-09-27 — see J4-J6's note), starts
       a held topic (claimed first, restored on failure), a stable reply for the
       fleet, the long wait, and an unconfirmed timeout.
  F* — firestore_rest `set_device_allow_all`: literal masks, bool values.
  S* — sr.py: the joined reply, the rows, the invite, the two owner switches, the
       owner half of device-requests, the ask confirm and the ask table.
  R* — sr.py router `do`: the allow-all arm, its vetoes, and `join` as an ask.
  T* — cli.py: the terminal's copy of the same.
  K* — SKILL.md: allow-all yes in all three confirm lists; the fourth reach.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ NO EQUIVALENT MUTANTS. `publish=want_all or …` → `publish=…` was dropped as one:
the writer publishes whenever the value is True, so the edit changes an argument
and no write.

  python .mutants/wave12_allow_all_agent_mutants.py
  python .mutants/wave12_allow_all_agent_mutants.py V3 J7 R12
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
FSR = "agent/facade/firestore_rest.py"
SR = "agent/facade/skill/scripts/sr.py"
CLI = "agent/facade/cli.py"
SKILL = "agent/facade/skill/SKILL.md"

SUITES = {
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_device_projection_795.py "
                    "tests/test_crossverify_fixes_795.py"),
    FSR: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_app_plane_unchanged.py"),
    # ⛔ + the repair's pins (2026-09-27): R10 and R18 are measured there now.
    # ⛔ + the repair-2 pins (2026-09-27): the re-aimed R mutants are measured there.
    # ⛔ + the repair-3 pins (2026-09-27): the re-aimed R mutants are measured there.
    # ⛔ + the repair-4 pins (2026-09-27): R11 R12 R15 R19 re-aimed onto repair 4's lines.
    SR: (AGENT, "tests/test_allow_all_clients_0926.py tests/test_allow_all_router_0926.py "
                "tests/test_chat_owner_793.py tests/test_allow_all_router_repair_0927.py "
                "tests/test_allow_all_whole_message_0927.py tests/test_allow_all_repair3_0927.py "
                "tests/test_allow_all_repair4_0927.py"),
    CLI: (AGENT, "tests/test_allow_all_clients_0926.py"),
    SKILL: (AGENT, "tests/test_chat_owner_793.py tests/test_chat_public_792.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_JOIN_BLOCK = (
    "                    prefs.clear_held_research()\n"
    "                    try:\n"
    "                        cfg = _resolve_run_config(fs, sess, {})\n"
    "                        rid, _qid = _enqueue_research_run(\n"
    "                            fs, sess, topic=topic, device_id=device_id, cfg=cfg,\n"
    "                            origin=_clean_origin(held.get(\"origin\")))\n")

MUTANTS = [
    # ═══ G — who reads as "anyone can join" ═══════════════════════════════════
    ("G1", BRIDGE, "⛔⛔ a PRIVATE computer's leftover tick reads as an open door — the row "
     "says 'anyone can join' over a computer nobody can find",
     [('    return _discovery_of(d) == "public" and d.get("allowAll") is True\n',
       '    return d.get("allowAll") is True\n')]),
    ("G2", BRIDGE, "⛔ a stored 'true' or 1 reads as allow-all (truthy, not strictly True)",
     [('    return _discovery_of(d) == "public" and d.get("allowAll") is True\n',
       '    return _discovery_of(d) == "public" and bool(d.get("allowAll"))\n')]),
    ("G3", BRIDGE, "⛔ public is read off the literal `visibility` — a computer public under "
     "the new name `joinPolicy` never reads allow-all",
     [('    return _discovery_of(d) == "public" and d.get("allowAll") is True\n',
       '    return d.get("visibility") == "public" and d.get("allowAll") is True\n')]),
    ("G4", BRIDGE, "⛔⛔ the own-row prune drops the bit — no client can say 'anyone can join' "
     "and device-requests tells an allow-all owner nobody is there",
     [('                       "owned", "selected", "online", "visibility", "allowAll")',
       '                       "owned", "selected", "online", "visibility")')]),
    ("G5", BRIDGE, "⛔⛔ the public-list prune drops the web app's bit — every row reads 'ask "
     "the owner'",
     [('_PUBLIC_DEVICE_KEYS = ("deviceId", "label", "osFamily", "online", "full",\n'
       '                       "allowAll")',
       '_PUBLIC_DEVICE_KEYS = ("deviceId", "label", "osFamily", "online", "full")')]),
    ("G6", BRIDGE, "⛔ the RAW stored field leaves the bridge instead of the effective one",
     [('                d["allowAll"] = _allow_all_of(d)\n', '')]),

    # ═══ V — the owner's switch ════════════════════════════════════════════════
    ("V1", BRIDGE, "⛔⛔ the no-op compares visibility only — 'stop letting anyone join' on a "
     "public computer answers 'already public' and never writes",
     [('if want == current and want_all == current_all:', 'if want == current:')]),
    ("V2", BRIDGE, "⛔⛔ going private never writes `visibility` — the close rides the allow-all "
     "writer and the computer stays listed",
     [('if want == "private" or (want_all is False and not stored\n'
       '                                         and current == "private"):',
       'if (want_all is False and not stored\n'
       '                                         and current == "private"):')]),
    ("V3", BRIDGE, "⛔⛔ the stored tick is never cleared after going private — the next "
     "Public-on reopens the door unasked",
     [('if want == "private" and stored:', 'if False:')]),
    ("V4", BRIDGE, "⛔ a second write goes out after EVERY hide, even with nothing stored — "
     "today's single-field close is no longer what it was",
     [('if want == "private" and stored:', 'if want == "private":')]),
    ("V5", BRIDGE, "⛔⛔ a re-publish ignores an old tick — a private computer carrying "
     "allowAll:true comes back letting strangers straight in",
     [('if want == "private" or (want_all is False and not stored\n',
       'if want == "private" or (want_all is False\n')]),
    ("V6", BRIDGE, "⛔ a plain publish with nothing stored writes allowAll too — not the "
     "write this bridge has always made (and a lagging ruleset refuses the publish)",
     [('if want == "private" or (want_all is False and not stored\n'
       '                                         and current == "private"):',
       'if want == "private":')]),
    ("V7", BRIDGE, "⛔ a flag-less 'make it public' on an allow-all computer switches "
     "allow-all off",
     [('                want_all = current_all\n', '                want_all = False\n')]),
    ("V8", BRIDGE, "⛔ private + allow all is not refused — somebody's machine is published "
     "or the opening half is quietly dropped",
     [('if value == "private" and allow is True:', 'if False:')]),
    ("V9", BRIDGE, "⛔ a non-boolean allowAll reaches the write — the rules refuse the WHOLE "
     "update the owner believes they made",
     [('if has_all and not isinstance(allow, bool):', 'if False:')]),
    ("V10", BRIDGE, "⛔⛔ `allowAll: false` reads as absent — 'stop letting anyone join' is "
     "refused as 'say public or private'",
     [('has_all = "allowAll" in body_in', 'has_all = bool(body_in.get("allowAll"))')]),
    ("V11", BRIDGE, "⛔ a private computer's leftover tick is never cleared by 'allow all "
     "off' — an old writer's re-publish brings it back",
     [('if stored and not want_all:', 'if False:')]),
    ("V12", BRIDGE, "⛔⛔ the stored tick is read AFTER the prune replaced it — a private "
     "computer's old true reads false and the re-publish brings it back",
     [('            self._stored_allow_all = row.get("allowAll") is True\n'
       '            self._decorate_devices([row], sess.uid,\n'
       '                                   prefs.get_selected_device(sess.uid))\n',
       '            self._decorate_devices([row], sess.uid,\n'
       '                                   prefs.get_selected_device(sess.uid))\n'
       '            self._stored_allow_all = row.get("allowAll") is True\n')]),
    ("V13", BRIDGE, "⛔ a refused write no longer says where allow-all stands",
     [('"allowAll": current_all if refused else None})', '"allowAll": None})')]),
    ("V14", BRIDGE, "⛔⛔ a refused best-effort clear turns a hide that LANDED into a failure",
     [('except (RevokedError, FirestoreError) as e:\n'
       '                    log.warning("hid %s, but could not clear its allow-all: %s",',
       'except KeyError as e:\n'
       '                    log.warning("hid %s, but could not clear its allow-all: %s",')]),

    # ═══ J — the joiner's side ═════════════════════════════════════════════════
    ("J1", BRIDGE, "⛔⛔ a join is parked like a pending ask — the watcher announces "
     "'You're in' a second time a minute later",
     [('            if body.get("status") == "joined":\n'
       '                self._json(200, self._instant_join(',
       '            if False:\n'
       '                self._json(200, self._instant_join(')]),
    ("J2", BRIDGE, "⛔ a parked ask for the joined computer is left — announced again later",
     [('prefs.clear_device_ask()\n            try:\n'
       '                devs: list[dict[str, Any]] | None',
       'pass\n            try:\n'
       '                devs: list[dict[str, Any]] | None')]),
    ("J3", BRIDGE, "⛔ a join clears a parked ask for a DIFFERENT computer — that answer is "
     "never announced",
     [('if isinstance(parked, dict) and str(parked.get("deviceId") or "") == device_id:',
       'if isinstance(parked, dict):')]),
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair, cross-verify F3) — J4, J5 AND J6. The
    # `if not saved or gone:` rule and its `gone` flag were replaced: the joined
    # computer is now selected only when `_pick_device_from` finds nothing routable
    # on the list as it was before the join, and a saved choice still on that list
    # is `kept`. Each mutant keeps its original defect on the new lines; the new
    # rule's own mutants are B1-B4 in wave12_repair1_agent_mutants.
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2, cross-verify G8): the rule became
    # `if not kept:` + `pick = device_id if routed is None else routed` (the
    # router's own pick is saved when one of the person's computers routed). A
    # bare `if True:` now re-saves a live selection as itself, so the defect —
    # the joined computer written over it — needs the pick forced too.
    ("J4", BRIDGE, "⛔⛔ a join replaces a LIVE selection — research moves to a stranger's "
     "computer without anyone asking",
     [('                if not kept:\n'
       '                    pick = device_id if routed is None else routed\n',
       '                if True:\n'
       '                    pick = device_id\n')]),
    ("J5", BRIDGE, "⛔ a selection that no longer exists is kept — the next research asks "
     "'which computer?' of somebody who just joined one",
     [('kept = bool(saved) and any(d.get("id") == saved for d in before)',
       'kept = bool(saved)')]),
    ("J6", BRIDGE, "⛔ a list that could not be READ counts as the selection being gone",
     [('            if devs is not None:\n'
       '                before = [d for d in devs if d.get("id") != device_id]\n',
       '            if True:\n'
       '                before = [d for d in (devs or []) if d.get("id") != device_id]\n')]),
    ("J7", BRIDGE, "⛔⛔ a held topic is never started on the joined computer — it sits "
     "held on a computer the person can already use",
     [('                if usable:\n                    # ⛔⛔ CLAIMED BEFORE THE ENQUEUE',
       '                if False:\n                    # ⛔⛔ CLAIMED BEFORE THE ENQUEUE')]),
    ("J8", BRIDGE, "⛔ a held topic is started on a computer that cannot take work",
     [('                if usable:\n                    # ⛔⛔ CLAIMED BEFORE THE ENQUEUE',
       '                if True:\n                    # ⛔⛔ CLAIMED BEFORE THE ENQUEUE')]),
    ("J9", BRIDGE, "⛔ a TERMINAL ask starts the topic a chat was holding",
     [('held = prefs.get_held_research(sess.uid) if ask_origin else None',
       'held = prefs.get_held_research(sess.uid)')]),
    ("J10", BRIDGE, "⛔ a failed start loses the held topic",
     [('                        prefs.set_held_research(held, sess.uid)\n',
       '                        pass\n')]),
    ("J11", BRIDGE, "⛔⛔ the hold is cleared AFTER the enqueue — a watcher answering an "
     "older ask in the same second starts the topic twice",
     [(_JOIN_BLOCK,
       _JOIN_BLOCK.replace("                    prefs.clear_held_research()\n", "")
       + "                        prefs.clear_held_research()\n")]),
    ("J12", BRIDGE, "⛔ the join reply drops a key the DG HERMES fleet branches on",
     [('"usable": usable, "autoStarted": False,', '"autoStarted": False,')]),
    ("J13", BRIDGE, "⛔⛔ the ask keeps the shared fifteen seconds — a join that committed "
     "comes back as a failure",
     [('timeout=_FE_ASK_TIMEOUT)', 'timeout=_FE_JSON_TIMEOUT)')]),
    ("J14", BRIDGE, "⛔ the long wait is no longer than the short one",
     [('_FE_ASK_TIMEOUT = 35', '_FE_ASK_TIMEOUT = 15')]),
    ("J15", BRIDGE, "⛔⛔ a timeout that may sit on a committed join is reported as 'could "
     "not reach the app' — the retry answers already_shared",
     [('if status == 0 and body.get("reason") != "revoked":', 'if False:')]),
    ("J16", BRIDGE, "⛔ a DEAD SESSION on the ask is reported as unconfirmed, not 401",
     [('if status == 0 and body.get("reason") != "revoked":', 'if status == 0:')]),
    ("J17", BRIDGE, "⛔ a join the app did not name is announced with no name",
     [('name = _device_label(row) if row is not None else None', 'name = None')]),
    ("J18", BRIDGE, "⛔ a switched-off computer reads online — 'Starting … now' over a run "
     "that is only queued",
     [('online = row is not None and _device_is_online(row)',
       'online = row is not None')]),

    # ═══ F — the Firestore writer ══════════════════════════════════════════════
    ("F1", FSR, "⛔⛔ ON without the publish flag writes allowAll ALONE — a private computer "
     "'lets anyone join' and nobody can find it",
     [('        if value or publish:\n', '        if publish:\n')]),
    ("F2", FSR, "⛔ a non-bool reaches the wire — the rules refuse the whole update",
     [('if not isinstance(value, bool) or not isinstance(publish, bool):', 'if False:')]),
    ("F3", FSR, "⛔⛔ the narrowing OFF write names `visibility` in its mask with no value — "
     "it DELETES the computer's visibility",
     [('            self._request("PATCH", f"{target}?updateMask.fieldPaths=allowAll",\n',
       '            self._request("PATCH", f"{target}?updateMask.fieldPaths=visibility"\n'
       '                          f"&updateMask.fieldPaths=allowAll",\n')]),
    ("F4", FSR, "⛔ allowAll is written as a string — `allowAllWriteIsValid` refuses the "
     "whole patch, publish and all",
     [('"allowAll": to_value(value)}})', '"allowAll": to_value(str(value).lower())}})')]),

    # ═══ S — the chat client ═══════════════════════════════════════════════════
    ("S1", SR, "⛔⛔ a join is told 'Its owner decides' — they wait for an answer that "
     "never comes",
     [('    if body.get("status") == "joined":\n'
       '        return _emit(body, args.json, _joined_lines(body, label))\n', '')]),
    ("S2", SR, "⛔ 'Your research will run on it' is said when the selection did not move",
     [('    if body.get("selected"):\n        lines.append("Your research will run on it.")',
       '    if True:\n        lines.append("Your research will run on it.")')]),
    ("S3", SR, "⛔ a topic that could not start is announced as 'Starting'",
     [('    if not body.get("autoStarted"):\n', '    if False:\n')]),
    ("S4", SR, "⛔ 'I'll tell you here' is promised with no watcher armed",
     [('if arm_payload.get("armed") else "Ask me how it’s going anytime.")',
       'if True else "Ask me how it’s going anytime.")')]),
    ("S5", SR, "⛔ a switched-off computer is told 'Starting … now'",
     [('    if body.get("online") is False:\n        lines.append(f"{quoted} is queued',
       '    if False:\n        lines.append(f"{quoted} is queued')]),
    ("S6", SR, "⛔ the chat gives up on an ask before the bridge does",
     [('code, body = _post("/device/ask", ask_payload, timeout=50)',
       'code, body = _post("/device/ask", ask_payload)')]),
    ("S7", SR, "⛔ an owned PRIVATE row says 'anyone can join'",
     [('if state == ", public" and d.get("allowAll") is True:',
       'if d.get("allowAll") is True:')]),
    ("S8", SR, "⛔ an owned row reads a truthy bit as 'anyone can join'",
     [('if state == ", public" and d.get("allowAll") is True:',
       'if state == ", public" and d.get("allowAll"):')]),
    ("S9", SR, "⛔ a FULL computer says 'joins at once' — the route refuses everybody",
     [('    return d.get("allowAll") is True and not d.get("full")\n',
       '    return d.get("allowAll") is True\n')]),
    ("S10", SR, "⛔ a public row reads a malformed bit as 'joins at once'",
     [('    return d.get("allowAll") is True and not d.get("full")\n',
       '    return bool(d.get("allowAll")) and not d.get("full")\n')]),
    ("S11", SR, "⛔⛔ the invite under a list with a joins-at-once row still says 'once the "
     "request is accepted'",
     [('return (_PUBLIC_JOIN_INVITE if any(_joins_at_once(d) for d in rows)',
       'return (_PUBLIC_JOIN_INVITE if False')]),
    ("S12", SR, "⛔ the no-computer screen keeps the ask invite over a joins-at-once row",
     [('    lines.append("")\n    lines.append(_public_invite(rows))\n    return lines\n',
       '    lines.append("")\n    lines.append(_PUBLIC_ASK_INVITE)\n    return lines\n')]),
    ("S13", SR, "⛔⛔ allow-all yes does not publish — a private computer 'lets anyone join' "
     "and nobody can find it",
     [('    if value == "yes":\n        payload["visibility"] = "public"\n', '')]),
    ("S14", SR, "⛔ allow-all NO sends a visibility — a second decision nobody made",
     [('    if value == "yes":\n        payload["visibility"] = "public"\n',
       '    payload["visibility"] = "public"\n')]),
    ("S15", SR, "⛔ private --allow-all goes to the bridge instead of being refused",
     [('if allow_all and value == "private":', 'if False:')]),
    ("S16", SR, "⛔ a plain publish decides allow-all (sends allowAll: false)",
     [('    if allow_all:\n        payload["allowAll"] = True\n',
       '    payload["allowAll"] = allow_all\n')]),
    ("S17", SR, "⛔⛔ THE ONE LIE: the reply follows what was ASKED — a plain 'make it "
     "public' on an allow-all computer says 'You still approve every person'",
     [('everyone = state == "public" and body.get("allowAll") is True',
       'everyone = asked_all is True')]),
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair): the sentence became the constant
    # `_JOINED_KEEP_ACCESS`, shared with the going-private reply. Same defect.
    ("S18", SR, "⛔ OFF never says that people who joined keep access",
     [('                  f"person again.",\n'
       '                  _JOINED_KEEP_ACCESS] if changed',
       '                  f"person again."] if changed')]),
    ("S19", SR, "⛔⛔ device-requests says 'Nobody is waiting' to an allow-all owner and "
     "nothing else",
     [('    lines += _allow_all_owner_lines(incoming)\n', '')]),
    ("S20", SR, "⛔ 'nobody waits here' is said over somebody who IS waiting",
     [('            and str(d.get("id") or "") not in waiting]', '            ]')]),
    ("S21", SR, "⛔ the owner line reports on a computer this account only shares",
     [('if isinstance(d, dict) and d.get("owned") and d.get("allowAll") is True',
       'if isinstance(d, dict) and d.get("allowAll") is True')]),
    ("S22", SR, "⛔ the picker's example names the other switch",
     [('dev, fail = _pick_owned_device(example)', 'dev, fail = _pick_owned_device()')]),
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair, cross-verify F23): the sentence now
    # points at the requests list. Same defect — the row gone.
    ("S23", SR, "⛔ ask_unconfirmed has no sentence — 'Couldn’t ask … ask_unconfirmed'",
     [('    "ask_unconfirmed": "The app didn’t answer in time — that may have gone through. "\n'
       '                       "Ask me for your requests before asking again: it’s either "\n'
       '                       "waiting there, or it let you in and it’s one of your "\n'
       '                       "computers.",\n', '')]),
    ("S24", SR, "⛔⛔ the ask confirm still promises 'They decide' — false of a computer "
     "that lets anyone in",
     [('"If its owner lets anyone in, you join straight away; otherwise "\n'
       '                  "they decide, and nothing runs on it unless they say yes. Say yes "',
       '"They decide, and nothing runs on it unless they say yes. Say yes "')]),
    ("S25", SR, "⛔ the allow-all confirm never says it publishes a private computer too",
     [('(_ALLOW_ALL_MEANS + " If it isn’t public yet, this makes "\n'
       '                         "it public too — listed under the name it reports. Say "\n'
       '                         "yes and I’ll switch it on."),',
       '(_ALLOW_ALL_MEANS + " Say yes and I’ll switch it on."),')]),

    # ═══ R — the router ════════════════════════════════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 1). The arm was rebuilt by NARROWING —
    # phrase + own computer + the words governing the phrase (`_allow_all_read`),
    # with a hide / publish / ask resolved from what the message asks once the
    # allow-all words are blanked — so R1-R6, R9, R10, R12-R15 and R17-R25 lost
    # their anchors. Each is re-aimed at the new code for the SAME defect; R7, R8,
    # R11 and R16 still match as written. The repair's own mutants are in
    # wave12_repair1_router_mutants.py.
    # ⛔⛔ RE-AIMED AGAIN 2026-09-27 (wave 12 repair 2). The arm was REBUILT on
    # whole-message commands (`_allow_all_command`'s grammar; anything else that
    # mentions Allow all gets a hide, the browse list, the person's own list or the
    # catch-all — never a write, never a switch confirm). Every R mutant whose
    # anchor was in the removed reader is re-aimed at the rule that now stops the
    # same defect; R9, R10 and R24 are RETIRED with a note, because the machinery
    # that could produce their defect no longer exists. R14 and R15 match as written.
    # ⛔⛔ RE-AIMED / RETIRED AGAIN 2026-09-27 (wave 12 repair 3). Repair 3 removed
    # the hand-off to the hide, the artefact/unlink exemption and `_join_kw`; R1, R6,
    # R12, R14-R17 are re-aimed at the rule that now stops the same defect, R4 and
    # R18 are RETIRED with a note. Repair 3's own mutants are in
    # wave12_repair3_router_mutants.py.
    ("R1", SR, "⛔⛔ THE MEASURED MISROUTES: no arm — 'turn off allow all for my mac' HIDES "
     "the computer unconfirmed, 'let anyone use my computer' raises the APPROVE confirm",
     [('    if _aa_cmd:\n        _aa_dir, _aa_obj = _aa_cmd\n',
       '    if False:\n        _aa_dir, _aa_obj = _aa_cmd\n'),
      # ⭐ RE-AIMED 2026-09-28 (last check): the gate carries `and not _aa_runctl`.
      ('    if _AA_MENTION.search(_aa_src) and not _aa_runctl:\n',
       '    if False and _AA_MENTION.search(_aa_src) and not _aa_runctl:\n')]),
    ("R2", SR, "⛔ OFF asks the ON confirm",
     [('        if _aa_dir == "off":\n            return ["device-allow-all", "no"]',
       '        if False:\n            return ["device-allow-all", "no"]')]),
    ("R3", SR, "⛔⛔ ON switches allow-all on with NO confirm",
     [('        if _aa_dir == "off":\n'
       '            return ["device-allow-all", "no"] + ([_aa_obj] if _aa_obj else []), None\n',
       '        if True:\n'
       '            return ["device-allow-all", "no" if _aa_dir == "off" else "yes"] + '
       '([_aa_obj] if _aa_obj else []), None\n')]),
    # ⛔ R4 RETIRED 2026-09-27 (wave 12 repair 3, cross-verify H1): it removed the
    # hand-off from the arm to the visibility clause's hide, so `make it private
    # and turn off allow all` ran `device-allow-all no` and stayed listed. The
    # hand-off itself is GONE (it hid `…but keep it listed`, unconfirmed), and the
    # defect it guarded cannot recur: a two-request message matches no whole-message
    # grammar row, so it can never run OFF — it is read-only, and `do` posts
    # nothing (pinned: test_allow_all_repair3_0927
    # test_do_writes_nothing_for_a_read_only_route). Its anchor is gone from sr.py.
    ("R5", SR, "⛔ 'make my mac public without allow all' raises the ON confirm, or "
     "answers a publish with allow-all off",
     [('    ("on", r"(?:make|set)\\s+{S}\\s+public\\s+(?:and|with)\\s+(?:{SET}|let\\s+{W}\\s+join)"),',
       '    ("on", r"(?:make|set)\\s+{S}\\s+public\\s+(?:and|with|without|but\\s+not)\\s+'
       '(?:{SET}|let\\s+{W}\\s+join)"),')]),
    # ⛔ R6 RE-AIMED 2026-09-27 (repair 2): the question test is the whole-message
    # command's own `?` rule. Same defect: a question acts.
    # ⛔ RE-AIMED AGAIN 2026-09-27 (repair 3): the `?` is read in `_aa_bare`.
    ("R6", SR, "⛔ a question ACTS instead of listing — 'turn off allow all on my mac?' "
     "switches it off",
     [('    if not cmd or question:\n', '    if not cmd:\n')]),
    # ⚠ RE-ANCHORED 2026-09-28 (wave 12 repair 5, router-6): `can u` is `can you`.
    ("R7", SR, "⛔ 'can you let anyone join my mac' is read as a question",
     [('                      r"|(?P<you>(?:can|could|would|will)\\s+(?:you|u)\\b)[\\s,]*(?:please\\b[\\s,]*)?"\n',
       '                      r"|(?P<you>NEVER_R7)"\n')]),
    ("R8", SR, "⛔ 'let anyone join all my computers' switches one of them",
     [('    if subj and re.fullmatch(_AA_SET_SUBJ, subj.group(0)):\n        return "set", ""\n',
       '    if subj and re.fullmatch(_AA_SET_SUBJ, subj.group(0)):\n        return direction, ""\n')]),
    # ⛔ R9 RETIRED 2026-09-27 (wave 12 repair 2): it measured a negation AFTER an
    # allow-all phrase deciding its direction (`…and don't ask me` read as OFF). No
    # code reads a direction off a phrase any more — a direction is a grammar row
    # matched over the WHOLE message, and a message with a second clause is no row.
    # The class is measured by repair1 F9 (a command read from words anywhere) and
    # repair2 W4/F19e (what may follow a command).
    # ⛔ R10 RETIRED 2026-09-27 (wave 12 repair 2): it measured a negation BEFORE the
    # phrase but not governing it (`I don't mind: let anyone join my mac`, cross-verify
    # G23 noted the why no longer described it). Same removed reader; a leading clause
    # is simply not a command now (pinned: test_allow_all_router_repair_0927).
    # ⛔ R11 RE-AIMED 2026-09-27 (wave 12 repair 4, K7): a `my` subject's filler words
    # are never and/or now, and the machine word moved to the next line. Same defect.
    ("R11", SR, "⛔ 'require my approval on my mac' names a computer 'approval on my mac'",
     [("_AA_ONE_SUBJ = (rf\"(?:qqname|(?:my|our|this)\\s+(?:own\\s+)?(?:(?!(?:and|or|nor|plus)\\b)[\\w'’-]+\\s+){{0,2}}?\"",
       "_AA_ONE_SUBJ = (rf\"(?:qqname|(?:my|our|this)\\s+(?:own\\s+)?(?:(?!(?:and|or|nor|plus)\\b)[\\w'’-]+\\s+){{0,4}}?\"")]),
    # ⛔ R12 RE-AIMED 2026-09-27 (repair 3): the `the` subject takes model words.
    # ⛔ RE-AIMED AGAIN 2026-09-27 (wave 12 repair 4, K7): its filler words are never
    # and/or. Same defect.
    ("R12", SR, "⛔ an audience plus a thing that is not a computer is a subject — 'stop "
     "letting people join the call' switches allow-all off on a computer called “call”",
     [("rf\"setting|allow|and|or|nor|plus)\\b)[\\w'’-]+\\s+){{0,3}}?{_MACHINE_SINGULAR}(?:\\s+{_MODEL_WORDS})*\"",
       "rf\"setting|allow|and|or|nor|plus)\\b)[\\w'’-]+\\s+){{0,3}}?[\\w'’-]+(?:\\s+{_MODEL_WORDS})*\"")]),
    ("R13", SR, "⛔⛔ 'stop allowing people to use my mac' — a HIDE since 7.9-3 — switches "
     "allow-all off and leaves it listed",
     [('    ("off", r"stop\\s+allowing\\s+{WO}\\s+to\\s+join(?:\\s+{S})?"),',
       '    ("off", r"stop\\s+allowing\\s+{WO}\\s+to\\s+(?:join|use)(?:\\s+{S})?"),')]),
    # ⛔ R14 RE-AIMED 2026-09-27 (repair 3): `_join_kw` became the whole-message
    # `_join_request`. Same defect: no join is read at all.
    ("R14", SR, "⛔ 'join the Studio PC' reaches the catch-all (join is not an ask verb)",
     [('    _join_obj = _join_request(t)\n', '    _join_obj = ""\n')]),
    # ⛔ R15 RE-AIMED 2026-09-27 (repair 3): the person's own computer is refused
    # inside the one-computer test (`_JOIN_NOT_ONE`). Same defect.
    # ⛔ RE-AIMED AGAIN 2026-09-27 (wave 12 repair 4, K13): the list goes on to the
    # other possessives and the plural demonstratives. Same defect.
    # ⚠ RE-ANCHORED 2026-09-28 (wave 12 repair 5, router-3): somebody else's
    # possessives moved to `_JOIN_SOMEBODYS`; the person's own stay in this list.
    ("R15", SR, "⛔ 'join my mac' files an ask for the asker's OWN computer",
     [('                           r"my|our|mine|me|us|you|this)\\b")',
       '                           r"me|us|you|this)\\b")')]),
    # ⛔ R16 RE-AIMED 2026-09-27 (repair 2): the capture is gated by `_join_kw` now.
    # ⛔ RE-AIMED AGAIN 2026-09-27 (repair 3): the whole-message join feeds the
    # capture first. Same defect: the join is read but captures nothing.
    ("R16", SR, "⛔ `join <machine>` has no capture — nothing to ask for",
     [('    if _join_obj or _om:\n        _ask_obj = re.sub(r"[?.!,]+$", "", _join_obj or _om.group(1))',
       '    if _om:\n        _ask_obj = re.sub(r"[?.!,]+$", "", _om.group(1))')]),
    # ⛔ R17 RE-AIMED 2026-09-27 (repair 2): `allow all cookies` can no longer be a
    # switch (no grammar row reads it); the rule that keeps a subject-less message off
    # the person's computers is the fallback's catch-all.
    # ⛔ RE-AIMED AGAIN 2026-09-27 (repair 3): the arm returns directly.
    ("R17", SR, "⛔ no computer in view is needed — 'let people join the call' is answered "
     "with this account's computers",
     [('            return ["devices"], None\n        return None, [_NL_CATCH_ALL]\n',
       '            return ["devices"], None\n        return ["devices"], None\n')]),
    # ⛔ R18 RETIRED 2026-09-27 (wave 12 repair 3, cross-verify H4/H5): it narrowed
    # repair 2's artefact / unlink exemption, and the podcast route it kept is the
    # defect's other face — the same exemption let `pause the Mars run when anyone
    # can join` PAUSE, unconfirmed, and `forget it, go back to approving people`
    # reach the nameless approve. The exemption is GONE: the arm owns every message
    # with Allow-all words (the podcast row FLIPPED to the catch-all,
    # test_allow_all_whole_message_0927, dated). The exemption brought back is
    # wave12_repair3_router_mutants.py C2.
    # ⛔ R19 RE-AIMED 2026-09-27 (wave 12 repair 4, K8): a quoted span that IS the
    # setting's name keeps its words first; every other quoted name is blanked. Same
    # defect.
    ("R19", SR, "⛔ a computer NAMED “Allow All Lab” is read as a request",
     [('    _aa_src = _outside_quoted_names(_unquote_setting(low))\n',
       '    _aa_src = _unquote_setting(low)\n')]),
    ("R20", SR, "⛔ 'without asking' with no audience ('switch to the office pc without asking "
     "me') counts as Allow all and loses its own route",
     [('    + rf"|\\b{_AA_WHO}\\b[^.?!]{{0,40}}\\bwithout\\s+(?:asking|approv\\w*|"\n',
       '    + rf"|\\bwithout\\s+(?:asking|approv\\w*|"\n')]),
    ("R21", SR, "⛔ 'require approval again for my mac' — an OFF phrase with no allow-all "
     "word — is not read",
     [('    ("off", r"(?:start\\s+)?requir(?:e|ing)\\s+(?:my\\s+)?approvals?{A}?{T}{A}?"),',
       '    ("off", r"NEVER_R21"),')]),
    ("R22", SR, "⛔ a bare 'turn allow all off' / 'turn off auto approve' has no subject and is "
     "not a command",
     [('_AA_ON_SUBJ = rf"(?:\\s+(?:for|on|from|of|in)\\s+{_AA_SUBJ})?"',
       '_AA_ON_SUBJ = rf"(?:\\s+(?:for|on|from|of|in)\\s+{_AA_SUBJ})"')]),
    ("R23", SR, "⛔ 'require approval again' — the phrasing SKILL.md teaches for OFF — said "
     "alone is not a command",
     [('    ("off", r"(?:start\\s+)?requir(?:e|ing)\\s+(?:my\\s+)?approvals?{A}?{T}{A}?"),',
       '    ("off", r"(?:start\\s+)?requir(?:e|ing)\\s+(?:my\\s+)?approvals?{A}?\\s+(?:for|on)\\s+{S}{A}?"),')]),
    # ⛔ R24 RETIRED 2026-09-27 (wave 12 repair 2): it measured `ask me first` alone —
    # or any OFF-kind phrase alone — switching Allow all off through the removed
    # phrase reader. `ask me first` is in no grammar row, so nothing can switch it;
    # it is a mention, which only buys a read-only answer.
    ("R25", SR, "⛔ a question about the world ('how open source projects let anyone "
     "join') is answered with this account's device list",
     [('              or (_AA_SETTING_NAME.search(_aa_src)\n', '              or (True\n')]),

    # ═══ T — the terminal ══════════════════════════════════════════════════════
    ("T1", CLI, "⛔⛔ a terminal join says 'Asked. Its owner decides'",
     [('    if body.get("status") == "joined":\n        # ⛔⛔ "ITS OWNER DECIDES" IS FALSE',
       '    if False:\n        # ⛔⛔ "ITS OWNER DECIDES" IS FALSE')]),
    ("T2", CLI, "⛔ the terminal gives up on an ask at forty seconds",
     [('res = _bridge_post("/device/ask", {"deviceId": device_id}, timeout=50.0)',
       'res = _bridge_post("/device/ask", {"deviceId": device_id}, timeout=40.0)')]),
    ("T3", CLI, "⛔⛔ allow-all yes does not publish",
     [('    if on:\n        payload["visibility"] = "public"\n', '')]),
    ("T4", CLI, "⛔ private --allow-all goes to the bridge instead of being refused",
     [('if allow_all and value != "public":', 'if False:')]),
    ("T5", CLI, "⛔⛔ THE ONE LIE, terminal: 'You still approve every person' on an "
     "allow-all computer",
     [('everyone = state == "public" and body.get("allowAll") is True',
       'everyone = asked_all is True')]),
    ("T6", CLI, "⛔ an owned PRIVATE row says 'anyone can join'",
     [('if found == ", public" and d.get("allowAll") is True:',
       'if d.get("allowAll") is True:')]),
    ("T7", CLI, "⛔ a FULL computer says '(joins at once)'",
     [('    return d.get("allowAll") is True and not d.get("full")\n',
       '    return d.get("allowAll") is True\n')]),
    ("T8", CLI, "⛔⛔ 'Nobody is waiting' and nothing else to an allow-all owner",
     [('print("Nobody is waiting on your computers.")\n'
       '        _print_allow_all_owner_lines(incoming)\n',
       'print("Nobody is waiting on your computers.")\n')]),
    ("T9", CLI, "⛔ the WSL hint for allow-all points at the generic device line",
     [('        "allow-all": "Let anyone join a computer from chat:  "\n'
       '                     "/sr let anyone join my computer",\n', '')]),
    ("T10", CLI, "⛔ the terminal invite keeps 'once the request is accepted'",
     [('return (_PUBLIC_JOIN_INVITE_T if any(_joins_at_once(d) for d in rows)',
       'return (_PUBLIC_JOIN_INVITE_T if False')]),
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair): T11's sentence became the constant
    # `_JOINED_KEEP_ACCESS_T` (the going-private reply prints it too), and T12's
    # now points at `agent device requests` (cross-verify F23). Same defects.
    ("T11", CLI, "⛔ OFF never says that people who joined keep access",
     [('            # Remove, in the web app — and it is a ban.\n'
       '            print(_JOINED_KEEP_ACCESS_T)\n',
       '            # Remove, in the web app — and it is a ban.\n')]),
    ("T12", CLI, "⛔ ask_unconfirmed has no terminal sentence",
     [('    "ask_unconfirmed": "the app did not answer in time — that may have gone "\n'
       '                       "through; check `agent device requests` (still waiting) "\n'
       '                       "and `agent device` (let straight in) before asking again",\n',
       '')]),
    ("T13", CLI, "⛔ the owner line reports on a computer this account only shares",
     [('if (isinstance(d, dict) and d.get("owned") and d.get("allowAll") is True',
       'if (isinstance(d, dict) and d.get("allowAll") is True')]),
    ("T14", CLI, "⛔ 'nobody waits here' over somebody who IS waiting",
     [('                and str(d.get("id") or "") not in waiting):', '                ):')]),
    ("T15", CLI, "⛔ with people waiting on one computer, the owner's other allow-all "
     "computer is never named",
     [('        print("     Say no with:  agent device deny <computer id> <person id>")\n'
       '        _print_allow_all_owner_lines(incoming)\n',
       '        print("     Say no with:  agent device deny <computer id> <person id>")\n')]),

    # ═══ K — SKILL.md ═══════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ the safe-defaults list licenses skipping the allow-all confirm",
     [('`device-visibility public`, `device-allow-all yes`, `update`, and `install`**',
       '`device-visibility public`, `update`, and `install`**')]),
    ("K2", SKILL, "⛔ the after-confirm list has no allow-all yes to run",
     [('device-approve/device-deny/device-visibility/device-allow-all yes/update/install/',
       'device-approve/device-deny/device-visibility/update/install/')]),
    ("K3", SKILL, "⛔ the safety list licenses skipping the allow-all confirm",
     [('  `device-deny`, `device-visibility public`, `device-allow-all yes`, `install`',
       '  `device-deny`, `device-visibility public`, `install`')]),
    ("K4", SKILL, "⛔ three things reach past the account — Allow all, the widest, unnamed",
     [('Four things reach past it, and all four', 'Three things reach past it, and all three')]),
    ("K5", SKILL, "⛔ the consent paragraph never names Allow all",
     [('**Allow all** lets any', 'Allow all lets any')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
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
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
