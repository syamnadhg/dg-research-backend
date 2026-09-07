"""Mutation harness — the agent's authenticated read, the JSON POST's 401 retry,
and the three public-computer verbs (wave 7.9-2, 2026-09-07).

⛔⛔ WHAT THIS CODE DECIDES. Whether somebody with no computer of their own can
find one from the agent at all; whether asking for one says who is told what
before it is asked; whether an ANSWERED request is reported as an answer rather
than as a silence each client is free to interpret; and whether a session that
died an hour ago is named as a sign-in problem rather than as an outage.

⛔⛔ THE PLAN CALLED THE MISSING RETRY "A LIVE BUG: pair/remove drop a revoked
session TODAY", and the first measurement round said the opposite — that a
revoked session raises before any 401, so the retry is a non-fix. BOTH were
wrong, and the truth is why R-series exists: `id_token(force=False)` hands back a
CACHED token with no call to Google, and the cache stays fresh for about
fifty-five minutes past the death of the refresh token. So a revoked session
really does produce a 401, the retry really is reached, and what it buys is the
right SENTENCE rather than a recovery. Verified against session.py and
firebase-admin.ts before a line was written.

⭐⭐ THE SHARPEST MUTANTS HERE:
  G3/G4   — the GET's retry re-sends the cached token, or loops. It retries, it
            fails the same way, and every "did it eventually work" assertion is
            satisfied.
  P4      — the public row goes through `_decorate_devices`. Three answers come
            back from ABSENT fields and the route's own liveness is overwritten;
            every one of them is shaped like a real answer.
  Q2      — the requests route relays the OWNER's queue as well. Names of people
            whose request nothing on this surface can answer.
  Q4/Q5   — the "an answered request leaves this list" sentence moves inside the
            non-empty branch, or goes. Empty is exactly when somebody decides for
            themselves that the silence means no.
  A6      — the ask table falls back to the PAIRING table. `revoked_sharer` then
            ends "ask them to share it again" — the one thing that cannot work.
  A9      — the rate-limit wait rounds DOWN, so a fifty-second wait is printed as
            "0 minutes": a sentence that invites the retry it is refusing.
  N1      — the browse rule moves below the owned-devices rule and every browse
            phrasing is answered with the account's own machines again.
  N3      — the withdraw rule goes and "remove my request for the Studio PC" is
            a DESTRUCTIVE unlink confirm again.
  L1      — the stranger's device id goes back into the log that gets uploaded
            to support under a sentence that does not cover it.
  S3      — the skill's "you cannot reach anyone else's data" promise comes back,
            beside the verbs that make it false.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS WAVE'S OWN GUARDS by running this wave's three test files.
Pass --unfiltered to ask the other question — whether the TREE catches it — which
is deliberately separate. A borrowed kill is not evidence that the guard you just
wrote works.

    .venv/bin/python .mutants/wave792_public_devices_mutants.py
    .venv/bin/python .mutants/wave792_public_devices_mutants.py --unfiltered
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
SKILL = "agent/facade/skill/SKILL.md"
CONFTEST = "agent/tests/conftest.py"
OURS = (CLI, BRIDGE, SR, SKILL, CONFTEST)

# ⭐ THE GUARDS THIS WAVE ADDED, and the only tests a score here is about.
MINE = ("tests/test_fe_json_792.py "
        "tests/test_public_devices_792.py "
        "tests/test_chat_public_792.py")
MIN_SELECTED = 120

ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ G — the authenticated GET that did not exist ════════════════
    ("G1", BRIDGE, "under",
     "⛔⛔ THE GET STOPS SENDING THE SESSION, which is the whole of B1 — the two "
     "GETs that already existed carry no Authorization header either, so a "
     "helper copied from those compiles, runs, and is refused by every route it "
     "was written for",
     [('                headers={"Authorization": f"Bearer {token}"},\n'
       '                timeout=_FE_JSON_TIMEOUT,\n'
       '            )\n'
       '        except requests.RequestException as e:\n'
       '            return 0, {"error": f"could not reach {config.FE_BASE} ({type(e).__name__})"}\n'
       '        return r.status_code, _fe_json_body(r)\n'
       '\n'
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post',
       '                timeout=_FE_JSON_TIMEOUT,\n'
       '            )\n'
       '        except requests.RequestException as e:\n'
       '            return 0, {"error": f"could not reach {config.FE_BASE} ({type(e).__name__})"}\n'
       '        return r.status_code, _fe_json_body(r)\n'
       '\n'
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post')]),
    ("G2", BRIDGE, "under",
     "⛔ THE GET MINTS BY HAND AGAIN, so a dead session raises out of a helper "
     "that promises it never does — and its one caller is a route with no "
     "blanket handler, which means a dropped socket rather than a sentence",
     [('    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post(sess: "AccountSession", path: str, payload: dict)',
       '    token = sess.id_token(force=False)\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    return _send(sess.id_token(force=True))\n'
       '\n'
       '\n'
       'def _fe_api_post(sess: "AccountSession", path: str, payload: dict)')]),
    ("G3", BRIDGE, "over",
     "⛔⛔ THE GET'S RETRY RE-SENDS THE CACHED TOKEN. It retries, it fails the "
     "same way, and every \"did it eventually work\" assertion is satisfied",
     [('    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post(sess: "AccountSession", path: str, payload: dict)',
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post(sess: "AccountSession", path: str, payload: dict)')]),
    ("G4", BRIDGE, "over",
     "⛔ THE RETRY BECOMES A LOOP, hammering the app with a token it has already "
     "refused",
     [('    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post(sess: "AccountSession", path: str, payload: dict)',
       '    status, body = _send(token)\n'
       '    while status == 401:\n'
       '        token, why = _mint_bearer(sess, force=True)\n'
       '        if token is None:\n'
       '            return 0, why\n'
       '        status, body = _send(token)\n'
       '    return status, body\n'
       '\n'
       '\n'
       'def _fe_api_post(sess: "AccountSession", path: str, payload: dict)')]),
    ("G5", BRIDGE, "over",
     "⛔ EVERY STATUS IS RETRIED, so a 429 spends a second slice of a five-an-hour "
     "budget and a 500 is asked twice for the same answer",
     [('        return r.status_code, _fe_json_body(r)\n'
       '\n'
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post',
       '        return r.status_code, _fe_json_body(r)\n'
       '\n'
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status == 200:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       'def _fe_api_post')]),
    ("G6", BRIDGE, "under",
     "⛔⛔ A NON-JSON ERROR PAGE RAISES. Two statements in the web app's device "
     "routes sit outside their own try, so a Firestore outage there comes back as "
     "HTML — and every caller reads body.get(\"error\")",
     [('    try:\n'
       '        body = r.json() if r.content else {}\n'
       '    except ValueError:\n'
       '        return {}\n'
       '    return body if isinstance(body, dict) else {}\n',
       '    body = r.json() if r.content else {}\n'
       '    return body if isinstance(body, dict) else {}\n')]),
    ("G7", BRIDGE, "under",
     "a JSON array comes back as a list where every caller does `.get`, so the "
     "next line is an AttributeError inside a helper that promises not to raise",
     [('    return body if isinstance(body, dict) else {}\n',
       '    return body\n')]),
    ("G8", BRIDGE, "under",
     "⛔ THE GET STOPS PASSING QUERY PARAMETERS, which nothing in this wave sends "
     "yet — so it is silently unusable for the first caller that needs one",
     [('                params=params or None,\n', '')]),

    # ═══════════ R — the JSON POST's 401 retry (#324) ════════════════════════
    ("R1", BRIDGE, "under",
     "⛔⛔ THE POST'S RETRY GOES AND `device add` ANSWERS \"unauthorized\" AGAIN "
     "for the fifty-five minutes a cached token outlives a revoked session",
     [('    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       '# The most of the agent\'s own log',
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       '# The most of the agent\'s own log')]),
    ("R2", BRIDGE, "over",
     "⛔ THE POST'S RETRY RE-SENDS THE CACHED TOKEN — the same shape as G3, on "
     "the helper four routes go through",
     [('    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       '# The most of the agent\'s own log',
       '    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       '# The most of the agent\'s own log')]),
    ("R3", BRIDGE, "under",
     "⛔ THE FIRST MINT IS UNWRAPPED on the POST, so a transport failure reaching "
     "GOOGLE escapes as an exception from a helper whose callers sit outside any "
     "handler for it",
     [('    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       "# The most of the agent's own log",
       '    token = sess.id_token(force=False)\n'
       '    status, body = _send(token)\n'
       '    if status != 401:\n'
       '        return status, body\n'
       '    token, why = _mint_bearer(sess, force=True)\n'
       '    if token is None:\n'
       '        return 0, why\n'
       '    return _send(token)\n'
       '\n'
       '\n'
       "# The most of the agent's own log")]),
    ("R4", BRIDGE, "over",
     "⛔⛔ THE TIMEOUT GOES BACK TO TWENTY. One quick 401, a ten-second refresh "
     "and one full second attempt is then thirty-one seconds — past what BOTH "
     "clients wait, so a slow web app is reported as a bridge that is not "
     "running and somebody is told to reinstall one that is fine",
     [("_FE_JSON_TIMEOUT = 15", "_FE_JSON_TIMEOUT = 20")]),
    ("R5", BRIDGE, "over",
     "the bytes upload is dragged onto the JSON timeout, so a multi-megabyte log "
     "gets fifteen seconds and a wave's fix is silently undone",
     [("                timeout=60,\n", "                timeout=_FE_JSON_TIMEOUT,\n")]),

    # ═══════════ P — browse ══════════════════════════════════════════════════
    ("P1", BRIDGE, "under",
     "⛔ THE BROWSE ROUTE STOPS DISPATCHING, so every phrasing this wave routes "
     "reaches a 404 the clients word as an unknown error",
     [('            elif path == "/devices/public":\n'
       '                self._devices_public()\n', '')]),
    ("P2", BRIDGE, "under",
     "⛔⛔ `truncated` IS DROPPED and the list silently becomes \"some of them\" "
     "wearing the shape of \"all of them\"",
     [('            self._json(200, {"devices": devices if isinstance(devices, list) else [],\n'
       '                             "truncated": bool(body.get("truncated"))})',
       '            self._json(200, {"devices": devices if isinstance(devices, list) else []})')]),
    ("P3", BRIDGE, "over",
     "`truncated` is inverted, so the caption cries wolf on every ordinary list "
     "and is silent on the one that is short",
     [('                             "truncated": bool(body.get("truncated"))})',
       '                             "truncated": not body.get("truncated")})')]),
    ("P4", BRIDGE, "over",
     "⛔⛔ THE PUBLIC ROW GOES THROUGH `_decorate_devices`. Three answers come "
     "back from ABSENT fields — owned from a missing ownerUid, selected from an "
     "id under another key, and online OVERWRITING the liveness the route "
     "computed correctly. Every one of them is shaped like a real answer",
     [('            devices = body.get("devices")\n'
       '            self._json(200, {"devices": devices if isinstance(devices, list) else [],',
       '            devices = body.get("devices")\n'
       '            if isinstance(devices, list):\n'
       '                self._decorate_devices(devices, sess.uid, None)\n'
       '            self._json(200, {"devices": devices if isinstance(devices, list) else [],')]),
    ("P5", BRIDGE, "under",
     "a non-list body reaches the clients unchecked, so a malformed reply is a "
     "traceback in a loop rather than an empty list",
     [('            self._json(200, {"devices": devices if isinstance(devices, list) else [],',
       '            self._json(200, {"devices": devices,')]),
    ("P6", CLI, "under",
     "⛔ THE ID LEAVES THE PUBLIC ROW, so the one thing on it that is unique — and "
     "the only thing the next command takes — is not on screen",
     [('    return f"  {i:>2}  {label.ljust(34)}  {state.ljust(8)}{full}  id={d.get(\'deviceId\')}"',
       '    return f"  {i:>2}  {label.ljust(34)}  {state.ljust(8)}{full}"')]),
    ("P7", CLI, "under",
     "⛔⛔ THE DISCLOSURE LEAVES THE SCREEN THAT OFFERS THE ASK. A person decides "
     "HERE whether to ask at all, and the fact that asking names them was the "
     "thing they needed before deciding",
     [('    print("     Its owner decides. Asking tells them your name and email address.")\n',
       '')]),
    ("P8", CLI, "over",
     "⛔ THE TRUNCATION CAPTION PROMISES A NEXT PAGE. There is no cursor, no "
     "ordering and no second request — the rest are unreachable, permanently",
     [('        print("  (there are more public computers than one look can scan, so some "\n'
       '              "may be missing)")',
       '        print("  (only the first page is shown — ask again for the next page)")')]),
    ("P9", CLI, "over",
     "the browse call falls back to `_bridge_get`'s ten-second default, which is "
     "shorter than the fifteen the bridge's own web-app call is allowed before it "
     "even retries",
     [('    res = _bridge_get("/devices/public", timeout=40.0)',
       '    res = _bridge_get("/devices/public")')]),
    ("P10", CLI, "under",
     "⛔ THE EMPTY LIST STOPS SAYING WHY IT IS EMPTY, so \"nobody is offering\" "
     "reads as a fault rather than as the ordinary state of an opt-in feature",
     [('        print("     A computer is offered only when its owner switches that on.")\n',
       '')]),
    ("P11", SR, "under",
     "⛔⛔ CHAT'S PUBLIC LIST DROPS THE ID, and chat is the surface where public "
     "names collide worst — every unrenamed machine is the identical string",
     [('        lines.append(f"  • {label}{dot}{full}  (id {d.get(\'deviceId\')})")',
       '        lines.append(f"  • {label}{dot}{full}")')]),
    ("P12", SR, "under",
     "chat stops saying that asking names the person, so the disclosure exists on "
     "one client and not the other",
     [('    lines.append("Tell me which one to ask for and I’ll ask its owner. Asking tells "\n'
       '                 "them your name and email address.")\n',
       '    lines.append("Tell me which one to ask for and I’ll ask its owner.")\n')]),

    # ═══════════ A — ask ═════════════════════════════════════════════════════
    ("A1", BRIDGE, "under",
     "⛔ THE ASK ROUTE STOPS DISPATCHING",
     [('            elif path == "/device/ask":\n'
       '                self._device_ask()\n', '')]),
    ("A2", BRIDGE, "under",
     "⛔ AN EMPTY deviceId REACHES THE WEB APP, spending one of five asks an hour "
     "on a request that cannot succeed",
     [('            device_id = (self._read_json().get("deviceId") or "").strip()\n'
       '            if not device_id:\n'
       '                self._json(400, {"error": "deviceId is required"})\n'
       '                return\n'
       '            acct = self._account()\n'
       '            if acct is None:\n'
       '                return\n'
       '            sess, _fs = acct\n'
       '            status, body = _fe_api_post(sess, "/api/devices/access-request",',
       '            device_id = (self._read_json().get("deviceId") or "").strip()\n'
       '            acct = self._account()\n'
       '            if acct is None:\n'
       '                return\n'
       '            sess, _fs = acct\n'
       '            status, body = _fe_api_post(sess, "/api/devices/access-request",')]),
    ("A3", BRIDGE, "under",
     "⛔ `retryAfterMs` IS DROPPED FROM THE RELAY, so the one refusal in the "
     "product where the server knows the wait arrives without it and both clients "
     "fall back to naming nothing",
     [('                           {"error": body.get("error") or f"{what} (HTTP {status})",\n'
       '                            "retryAfterMs": body.get("retryAfterMs")})',
       '                           {"error": body.get("error") or f"{what} (HTTP {status})"})')]),
    ("A4", BRIDGE, "over",
     "⛔⛔ A REVOKED SESSION IS A 502 AGAIN — the one failure the person can fix, "
     "reported as the one they cannot, on all five routes that reach the web app",
     [('            if status == 0:\n'
       '                if body.get("reason") == "revoked":\n',
       '            if status == 0:\n'
       '                if False:\n')]),
    ("A5", BRIDGE, "over",
     "an unreachable web app is reported as a dead session, so somebody signs in "
     "again and again against an outage",
     [('                if body.get("reason") == "revoked":\n',
       '                if True:\n')]),
    ("A6", CLI, "over",
     "⛔⛔ THE ASK FALLS BACK TO THE PAIRING TABLE. `revoked_sharer` then ends "
     "\"ask them to share it again\" — on this route being on that list is "
     "exactly what the refusal IS, so the sentence invites the one retry "
     "guaranteed to fail",
     [('    said = _ASK_FAILURES.get(err)\n'
       '    if said is None:\n'
       '        return f"couldn\'t ask for that computer: {err or \'no reason given\'}"\n'
       '    return said',
       '    said = _ASK_FAILURES.get(err)\n'
       '    if said is None:\n'
       '        return ("the owner removed your access to that device — ask them to "\n'
       '                "share it again")\n'
       '    return said')]),
    ("A7", CLI, "under",
     "⛔ THE REFUSAL BECOMES THE MACHINE'S CODE. `revoked_sharer` and "
     "`device_queue_full` are not sentences anybody outside this repo can read",
     [('        print(f"{_NO} {_ask_refusal(body.get(\'error\') or \'\', body.get(\'retryAfterMs\'))}")',
       '        print(f"{_NO} {body.get(\'error\') or \'\'}")')]),
    ("A8", CLI, "over",
     "⛔⛔ THE PER-HOUR CEILING IS CALLED \"A FEW MINUTES\" — wrong by up to "
     "fifty-five of them, and the exact habit the house rule bans",
     [('        if mins is None:\n'
       '            return ("you have asked for as many computers as an account may in "\n'
       '                    "one hour")\n',
       '        if mins is None:\n'
       '            return "too many attempts — wait a few minutes and try again"\n')]),
    ("A9", CLI, "over",
     "⛔⛔ THE WAIT ROUNDS DOWN, so fifty seconds prints as \"0 minutes\" — a "
     "sentence that invites the retry it is refusing",
     [('    return max(1, int((retry_after_ms + 59_999) // 60_000))',
       '    return int(retry_after_ms // 60_000)')]),
    ("A10", CLI, "under",
     "a boolean is a number in Python, so `retryAfterMs: true` prints \"in about "
     "1 minute\" from a reply that named no wait at all",
     [('    if isinstance(retry_after_ms, bool) or not isinstance(retry_after_ms, (int, float)):',
       '    if not isinstance(retry_after_ms, (int, float)):')]),
    ("A11", CLI, "under",
     "⛔ THE ASK STOPS NAMING WHO DECIDES, so a request that has gone nowhere yet "
     "reads as access granted",
     [('    print(f"{_OK} Asked. Its owner decides — nothing happens on that computer "\n'
       '          f"until they say yes.")',
       '    print(f"{_OK} Asked.")')]),
    ("A12", SR, "over",
     "⛔⛔ CHAT GUESSES BETWEEN TWO MACHINES WEARING THE SAME DEFAULT NAME, and "
     "the coin decides whose computer gets a request naming this person",
     [('    if len(hits) == 1:\n'
       '        return hits[0], []\n'
       '    if len(hits) > 1:\n',
       '    if len(hits) >= 1:\n'
       '        return hits[0], []\n'
       '    if False:\n')]),
    ("A13", SR, "under",
     "⛔ AN EXACT ID STOPS WINNING OUTRIGHT, so the only unique thing on a public "
     "row is resolved by the same name match that cannot separate two of them",
     [('    for d in rows:\n'
       '        if str(d.get("deviceId") or "") == wanted:\n'
       '            return d, []\n', '')]),
    ("A14", SR, "under",
     "⛔ THE ASK CONFIRM LOSES THE DISCLOSURE, so the only consent moment on the "
     "chat path stops saying what is disclosed",
     [('    "device-ask": "Ask the owner of {name} to let you use it? They’ll see your name "\n'
       '                  "and email address, and they decide — nothing runs on it unless they "\n'
       '                  "say yes. Say yes and I’ll ask.",',
       '    "device-ask": "Ask the owner of {name} to let you use it? Say yes and I’ll ask.",')]),

    # ═══════════ Q — what you are waiting on ═════════════════════════════════
    ("Q1", BRIDGE, "under",
     "⛔ THE REQUESTS ROUTE STOPS DISPATCHING, so the ask has nothing to report "
     "back to and B4's whole reason for existing is gone",
     [('            elif path == "/devices/requests":\n'
       '                self._device_requests()\n', '')]),
    ("Q2", BRIDGE, "over",
     "⛔⛔ THE OWNER'S QUEUE IS RELAYED TOO — names of people whose request "
     "nothing on this surface can approve or deny, which is a dead end wearing a "
     "list's clothes",
     [('            rows = body.get("outgoing")\n'
       '            self._json(200, {"requests": rows if isinstance(rows, list) else []})',
       '            rows = (body.get("outgoing") or []) + (body.get("incoming") or [])\n'
       '            self._json(200, {"requests": rows if isinstance(rows, list) else []})')]),
    ("Q3", BRIDGE, "over",
     "the two halves are swapped, so a person is shown other people's requests "
     "for THEIR machine and told it is what they are waiting on",
     [('            rows = body.get("outgoing")\n',
       '            rows = body.get("incoming")\n')]),
    ("Q4", CLI, "over",
     "⛔⛔ THE SENTENCE MOVES INSIDE THE NON-EMPTY BRANCH. Empty is exactly when "
     "somebody decides for themselves that the silence means no",
     [('        print("You are not waiting on any computer.")\n'
       '    else:\n'
       '        print(f"Waiting on ({len(rows)}):")\n'
       '        for d in rows:\n'
       '            label = str(d.get("deviceLabel") or "").strip() or "(unnamed)"\n'
       '            print(f"     {label.ljust(34)}  id={d.get(\'deviceId\')}")\n',
       '        print("You are not waiting on any computer.")\n'
       '        return 0\n'
       '    else:\n'
       '        print(f"Waiting on ({len(rows)}):")\n'
       '        for d in rows:\n'
       '            label = str(d.get("deviceLabel") or "").strip() or "(unnamed)"\n'
       '            print(f"     {label.ljust(34)}  id={d.get(\'deviceId\')}")\n')]),
    ("Q5", CLI, "under",
     "⛔⛔ THE SENTENCE GOES ENTIRELY, and every client is then free to read an "
     "absence as a refusal — a field that never crossed the wire",
     [('    print("\\n     Only unanswered requests appear here. Once a request is "\n'
       '          "answered it")\n'
       '    print("     leaves this list either way — ask again and you will be told "\n'
       '          "which it was.")\n', '')]),
    ("Q6", SR, "over",
     "⛔ CHAT CALLS A MISSING ROW A REFUSAL — the exact fabrication B4 was written "
     "to prevent, and the one the web app already ships one layer down",
     [('    lines.append("Only unanswered requests show here. Once one is answered it leaves "\n'
       '                 "this list whichever way it went — ask for that computer again and "\n'
       '                 "I’ll tell you which it was.")',
       '    lines.append("Anything that has dropped off this list was denied.")')]),
    ("Q7", SR, "over",
     "⛔ CHAT'S SENTENCE MOVES INSIDE THE NON-EMPTY BRANCH, so the empty screen "
     "says nothing about what an empty screen means",
     [('        lines = ["You’re not waiting on any computer."]\n',
       '        return _emit(body, args.json, ["You’re not waiting on any computer."])\n')]),

    # ═══════════ N — natural language ════════════════════════════════════════
    ("N1", SR, "over",
     "⛔⛔ THE BROWSE RULE MOVES BELOW THE OWNED-DEVICES RULE, so every browse "
     "phrasing is answered with the account's own machines again — a "
     "complete-looking answer to a different question, which is the state this "
     "wave found",
     [('    if _machine_kw and (_public_kw\n'
       '                        or (_ask_kw and re.search(r"\\bto use\\b|\\baccess\\b|"\n'
       '                                                  r"\\bborrow\\b|\\bask for\\b", low))):\n'
       '        return ["devices-public"], None\n',
       '    if False:\n'
       '        return ["devices-public"], None\n')]),
    ("N2", SR, "under",
     "⛔ THE WAITING RULE GOES, so \"what did I ask for\" is answered by the "
     "capabilities line on the one screen a person opens because they are waiting",
     [('    if (_ask_kw and re.search(r"\\b(my|any|outstanding|pending|open|all)\\b.{0,24}"',
       '    if False and (_ask_kw and re.search(r"\\b(my|any|outstanding|pending|open|all)\\b.{0,24}"')]),
    ("N3", SR, "under",
     "⛔⛔ THE WITHDRAW RULE GOES AND \"remove my request for the Studio PC\" IS A "
     "DESTRUCTIVE UNLINK CONFIRM AGAIN, because \"PC\" satisfies the device noun "
     "one rule down. Say yes and it dead-ends on a device that never existed",
     [('    if _ask_kw and re.search(r"\\b(cancel|withdraw|remove|delete|take back|undo|"\n'
       '                             r"retract|forget)\\b", low) and \\\n'
       '            re.search(r"\\b(requests?|asks?|application)\\b", low):\n',
       '    if False:\n')]),
    ("N4", SR, "over",
     "⛔ A CATEGORY BECOMES A NAME, so \"ask to use someone else's computer\" "
     "confirms a request for a machine called \"someone else's\" instead of "
     "showing the list",
     [('    if _ask_kw and _ask_obj and _ask_is_about_a_machine and not _ask_obj_is_thing \\\n'
       '            and not _ask_obj_is_pronoun and not _ask_obj_is_category:',
       '    if _ask_kw and _ask_obj and _ask_is_about_a_machine and not _ask_obj_is_thing \\\n'
       '            and not _ask_obj_is_pronoun:')]),
    ("N5", SR, "over",
     "⛔ AN ARTEFACT BECOMES A MACHINE, so \"ask for the podcast\" is a request "
     "for somebody's computer",
     [('    _ask_obj_is_thing = bool(re.search(', '    _ask_obj_is_thing = False and bool(re.search(')]),
    ("N6", SR, "over",
     "⛔ A PRONOUN BECOMES A NAME — this product's own advice line, \"ask them to "
     "share it again\", read back as a request for a computer called \"them\"",
     [('    _ask_obj_is_pronoun = bool(re.match(',
       '    _ask_obj_is_pronoun = False and bool(re.match(')]),
    ("N7", SR, "over",
     "⛔ THE ASK STOPS NEEDING TO BE ABOUT A MACHINE, so any unfamiliar \"ask\" "
     "object is read as a request for somebody's computer",
     [('    if _ask_kw and _ask_obj and _ask_is_about_a_machine and not _ask_obj_is_thing \\\n',
       '    if _ask_kw and _ask_obj and not _ask_obj_is_thing \\\n')]),
    ("N8", SR, "under",
     "⛔⛔ THE CODE-HIJACK COMES BACK: \"switch to the machine LABPC001\" is a "
     "pairing attempt again and is refused as a code that matched no device",
     [('        _existing = re.search(r"\\b(switch to|run (?:it |everything )?on|use|select|"\n'
       '                              r"remove|unlink|forget|delete|ask for)\\b", low)\n'
       '        if (_kw or _bare) and not (_existing and not _bare):\n',
       '        if _kw or _bare:\n')]),
    ("N9", SR, "over",
     "⛔ ONLY A CODE ON ITS OWN PAIRS, so \"pair my PC, code is K7XQ-9B2M\" — the "
     "phrasing the skill document itself teaches — stops being a pairing at all. "
     "⚠ THE FIRST VERSION OF THIS MUTANT WAS EQUIVALENT: it dropped `not _bare` "
     "from the guard, and a message that IS the token can never also contain a "
     "switch verb, so the two forms could not disagree. It survived honestly",
     [('        if (_kw or _bare) and not (_existing and not _bare):\n',
       '        if _bare:\n')]),
    ("N10", SR, "under",
     "⛔ THE PHRASING THE PICKER TELLS PEOPLE TO SAY STOPS ROUTING — 'Just say: "
     "use “<name>”' answered with \"I didn't catch a Super Research request\"",
     [('    _bare_use = t[:4].lower() == "use " and t[4:5] in _NL_QUOTE_CHARS\n'
       '    if m and (re.search(r"\\b(switch to|run (it |everything )?on)\\b", low) or _bare_use):',
       '    if m and re.search(r"\\b(switch to|run (it |everything )?on)\\b", low):')]),
    ("N11", SR, "over",
     "the bare `use` gate loses its quote requirement, so \"use less video\" is a "
     "device switch",
     [('    _bare_use = t[:4].lower() == "use " and t[4:5] in _NL_QUOTE_CHARS\n',
       '    _bare_use = t[:4].lower() == "use "\n')]),
    ("N12", SR, "under",
     "⛔ A QUOTED NAME STOPS RESOLVING, so routing the picker's own phrasing was "
     "only half the repair and the other half is gone",
     [('    a = arg.strip().strip("“”\\"\'‘’").strip().lower()\n',
       '    a = arg.strip().lower()\n')]),
    ("N13", SR, "under",
     "⛔ A LEADING DEVICE NOUN GOES BACK INTO THE NAME, so \"switch to the machine "
     "LABPC001\" looks up a device called \"machine LABPC001\"",
     [('        name = re.sub(r"^(?:device|node|machine|computer|pc|laptop|desktop)\\s+",\n'
       '                      "", name, flags=re.I).strip()\n', '')]),
    ("N14", SR, "under",
     "⛔ THE CAPABILITIES LINE STOPS NAMING THE NEW SURFACE, so the fallback "
     "denies having the verbs the resolver just failed to reach",
     [('                  "your researches, manage your devices, or find a public computer "\n'
       '                  "and ask to use it — what would you like?"]',
       '                  "your researches, or manage your devices — what would you like?"]')]),

    # ═══════════ L — what the uploadable log carries ═════════════════════════
    ("L1", BRIDGE, "over",
     "⛔⛔ THE STRANGER'S DEVICE ID GOES BACK INTO THE LOG THAT GETS UPLOADED TO "
     "SUPPORT, under a consent sentence that covers \"the computers this agent "
     "has touched\" — which a machine that merely refused a request is not",
     [('            log.info("device ask: sent")',
       '            log.info("device ask: %s", device_id)')]),

    # ═══════════ S — the skill document ══════════════════════════════════════
    ("S1", SKILL, "under",
     "⛔ THE BROWSE ROW GOES. The table is what the assistant reads to decide "
     "what to run; a verb with no row reaches the CLI only",
     [('| "are there any public computers?", "show me computers I could ask to use", '
       '"I don\'t have a computer of my own" | `sr.py devices-public` (only machines '
       'whose owners offer them; the id on each row is what the next command takes — '
       'public names collide, an unnamed one reads as "Research computer" for '
       'everybody) |\n', '')]),
    ("S2", SKILL, "over",
     "⛔⛔ THE ASK ROW LOSES ITS CONFIRM, so the assistant fires a request that "
     "names the person to a stranger without asking them first",
     [('| "ask for the Studio PC", "request access to that Mac", "ask its owner if I '
       'can use it" | **confirm** (the client prints the question — it tells the owner '
       "the user's name + email, and a \"no\" blocks asking again for a week), then "
       '`sr.py device-ask "<name or id>"` |',
       '| "ask for the Studio PC", "request access to that Mac", "ask its owner if I '
       'can use it" | `sr.py device-ask "<name or id>"` |')]),
    ("S3", SKILL, "over",
     "⛔⛔ THE SAFETY PROMISE COMES BACK. \"You cannot reach anyone else's data\" "
     "was true until this wave and is false the moment browse lists other "
     "people's machines — a promise that has quietly stopped being true is worse "
     "than none",
     [("""- You drive the user's own account only. The one thing that reaches past it is the
  public-computer list: it names machines other people chose to offer, and asking
  for one tells that owner the user's name and email address. Never ask on the
  user's behalf without a real "yes" to the client's own question first — the
  client refuses nothing, so YOU are the consent step, and a refusal from the
  owner blocks a fresh request for a week.""",
       "- You drive the user's own account only — you cannot reach anyone else's data.")]),
    ("S4", SKILL, "under",
     "⛔⛔ THE ROW STOPS SAYING AN ANSWERED REQUEST LEAVES THE LIST, which is the "
     "one fact the model cannot infer — every absence looks identical, and the "
     "likeliest guess is \"they said no\"",
     [('| "what am I waiting on?", "did they answer?", "my pending requests" | '
       '`sr.py device-requests` — ONLY unanswered ones appear. A request that has been '
       'answered leaves the list **either way**; never read a missing row as a '
       'refusal. Ask for that computer again and the reply says which it was |',
       '| "what am I waiting on?", "did they answer?", "my pending requests" | '
       '`sr.py device-requests` |')]),
    ("S5", SKILL, "over",
     "⛔ THE PARENTHETICAL TELLS THE MODEL SHARING IS OWNER-ONLY IN THE WEB APP "
     "AGAIN, so it refuses the verbs it now has",
     [("""  name a topic. (Approving or refusing somebody, offering a computer publicly,
  revoking sharers, and resets stay owner-only in the web app — but ASKING to use
  somebody else's public computer is something you can do from here.)""",
       """  name a topic. (Sharing a device with other people, revoking sharers, and resets
  stay owner-only in the web app.)""")]),
    ("S6", SKILL, "under",
     "the withdraw row goes, so the assistant improvises an answer to \"cancel my "
     "request\" for an operation the product does not have",
     [('| "cancel my request", "withdraw that request" | nothing withdraws a request '
       '— relay the client\'s line. It stays with the owner until they answer, or '
       'lapses after a week |\n', '')]),

    # ═══════════ T — the tree's own guards ═══════════════════════════════════
    ("T1", CONFTEST, "under",
     "⛔⛔ THE GET SEAM IS UNSTUBBED, so the suite is back on the internet through "
     "the door the POST stub closed — a GET is not safer than a POST for that, "
     "only quieter",
     [('    monkeypatch.setattr(bridge, "_fe_api_get", _stub_get)\n', '')]),
    ("T2", CLI, "over",
     "⛔ THE WINDOWS HINT NAMES `/sr device` AGAIN — the singular resolves to "
     "nothing, so it sends every Windows user to the one phrasing answered with "
     "\"I didn't catch a Super Research request in that\"",
     [('    rc = _redirect_if_wsl("Manage devices from chat:  /sr devices")',
       '    rc = _redirect_if_wsl("Manage devices from chat:  /sr device")')]),
    ("T3", CLI, "over",
     "⛔ THE BODYLESS FAILURE PRINTS THE LITERAL WORD None AGAIN",
     [('            print(f"{_NO} couldn\'t select device: {_err(res)}")',
       '            print(f"{_NO} couldn\'t select device: {res[1].get(\'error\') if res else \'no response\'}")')]),
    ("T4", CLI, "over",
     "⛔ THE SIGNED-OUT LIST PRINTS A PYTHON DICT AGAIN, so the repair is on "
     "screen wearing punctuation nobody outside this repo reads",
     [('        print(f"{_NO} list devices failed: {_err(dr)}")\n'
       '        return 1\n'
       '    devices = dr[1].get("devices", [])\n'
       '    selected = dr[1].get("selectedDeviceId")',
       '        print(f"{_NO} list devices failed: {dr[1] if dr else \'no response\'}")\n'
       '        return 1\n'
       '    devices = dr[1].get("devices", [])\n'
       '    selected = dr[1].get("selectedDeviceId")')]),
    ("T5", CLI, "under",
     "⛔ THE OWNED LIST DROPS `online` AGAIN — the bridge has always sent it, and "
     "\"which of my computers is on?\" is answered by this list",
     [('        state = "online" if d.get("online") else "offline"\n'
       '        print(f"  {mark} {d.get(\'name\') or d.get(\'id\')}  ({kind}, {state})  "\n'
       '              f"id={d.get(\'id\')}")',
       '        print(f"  {mark} {d.get(\'name\') or d.get(\'id\')}  ({kind})  "\n'
       '              f"id={d.get(\'id\')}")')]),
    ("T6", BRIDGE, "over",
     "⛔ THE SELECT REFUSAL GOES BACK TO A CONNECTIVITY WORD for a permissions "
     "state, in the one moment browsing makes it most likely to be read",
     [('                self._json(404, {"error": "no computer with that id is linked to "\n'
       '                                          "your account",\n'
       '                                 "reason": "not_linked"})',
       '                self._json(404, {"error": "device not reachable by this account"})')]),
    ("T7", CLI, "over",
     "the two clients stop making the same claims: one refusal code is dropped "
     "from the terminal's table and only chat can word it",
     [('    "is_owner": "that one is already yours",\n', '')]),
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
