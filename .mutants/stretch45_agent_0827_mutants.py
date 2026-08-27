"""Mutation harness for stretch 4.5 — the agent conversation.

⛔ WHAT THIS CODE DECIDES. Whether a person who asks for research while signed
out ever gets it; whether the sentences we say about a follow-up, a computer or a
port are things we can show to be true; and whether a chat can correct its own
request.

⭐⭐ THE SHARPEST MUTANTS HERE:
  P2      — the range check goes and `0`, `-1`, `65536` are taken verbatim. The
            bridge and its five clients then aim at different ports and the only
            symptom is "unreachable", forever, with nothing saying why.
  E1      — the bind failure goes back to one message for every errno. EACCES on
            an AF_INET bind is the privileged-port guard: there IS no holder, and
            the old line told somebody to go and find one. Four real log lines.
  E4      — the holder hint goes back to `netstat … | findstr`, a Windows built-in
            printed on darwin and written down on Linux.
  U1      — `updates` stops rendering the announce it took. That is the whole
            silent eater: the note is consumed, the delivered-watermark moves past
            it so the re-mint cannot recover it, and runs are printed alone.
  W1      — arming stops clearing `__login_wait__`. One abandoned sign-in then
            poisons the chat forever: every later listener dies on its FIRST tick.
  G1/G2   — the pending guard's carve-out goes (G1: back to refusing an
            origin-less client its own retry) or turns into `or` (G2: reopens both
            thefts cross-verification found). G2 is the one that looks like a fix.
  A1      — "I'll post here when it's done" goes back to unconditional, printed
            above the call that decides whether anything will ever post.
  F1      — the fork's signed-out research branch goes back to dropping the topic.
            Measured in a real transcript: the person had to ask twice.
  F2      — the fork's stash carries a chat origin. It looks like the obvious way
            to earn ownership and it silences the announce completely: an
            origin-bearing event is delivered only to a watcher that asks with a
            matching platform and chat, and this fleet's watcher asks with
            neither. Two successes, no error, nobody told.
  L1      — `login` mints a fresh flow every time again, orphaning the address the
            person is already looking at.
  D1      — `all` becomes `any`, so one sleeping computer beside two awake ones is
            announced as "none of their computers is switched on".
  X2      — `_require_bridge` reaches for a bridge BEFORE the shared-host guard.
            Starting one on a shared machine is the act the guard exists to stop.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⚠ TWO SUITES, AND BOTH MUST BE GREEN FOR A MUTANT TO COUNT AS SURVIVING. The
bridge, its client and its watchdog are in the agent package; the fourth client,
the skill prose and the cron provisioner are the fork, which has its own
virtualenv. A harness that ran one leg would report every mutant in the other as
killed.

⚠ `test_bridge_device.py` IS DELIBERATELY NOT IN THE PER-MUTANT LEG, unlike the
4A harness that included it as an over-correction guard. It costs 43 seconds a
mutant and nothing here touches the bridge's device decision — every device
change in this stretch is in the fork's rendering of a list the bridge already
sent. The pin that DOES matter for that, `test_the_two_device_asks_share_their
_stem_and_their_answer_form`, lives in `test_sr_stream.py`, which is in. The full
agent suite is run once as the final gate instead.

    .venv/bin/python .mutants/stretch45_agent_0827_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT.parent / "dg-hermes-fleet"

AGENT_SUITES = ("tests/test_stretch45_agent_0827.py "
                "tests/test_sr_client.py "
                "tests/test_signin_announce_0826.py "
                "tests/test_bridge.py "
                "tests/test_sr_stream.py "
                "tests/test_config.py")

FORK_SUITES = "skills/tests/test_super_research_skill.py"

CONF = "agent/facade/config.py"
BRIDGE = "agent/facade/bridge.py"
CLI = "agent/facade/cli.py"
SR_BE = "agent/facade/skill/scripts/sr.py"
OURS = (CONF, BRIDGE, CLI, SR_BE)

# ⚠ RELATIVE TO THE FORK, not to this repo.
FORK_SR = "skills/super-research/scripts/sr.py"
FORK_SKILL = "skills/super-research/SKILL.md"
FORK_CRON = "deploy/bin/sr-reconcile-cron.py"
FORK_POLL = "skills/super-research/scripts/sr_attention_poll.py"
THEIRS = (FORK_SR, FORK_SKILL, FORK_CRON, FORK_POLL)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ P — one port rule, five copies, one answer ═══════════
    ("P1", CONF, "under",
     "⛔ the try/except goes, so a non-numeric value raises at MODULE SCOPE — and "
     "`cli.py` imports this at the top, so it takes `doctor`, `version`, `status` "
     "and `connect` down with it, including the two commands somebody would reach "
     "for to find out what was wrong",
     [("    try:\n        port = int(raw)\n    except ValueError:\n"
       "        BRIDGE_PORT_REJECTED = raw\n        return DEFAULT_BRIDGE_PORT",
       "    port = int(raw)")]),
    ("P2", CONF, "under",
     "⛔⛔ THE RANGE CHECK GOES and `0`, `-1`, `65536` are taken verbatim, while "
     "all five clients fall back to 9876 — so the bridge and the client that "
     "spawned it aim at different ports and the only symptom is an unreachable "
     "bridge, forever",
     [("    if not (1 <= port <= 65535):\n        BRIDGE_PORT_REJECTED = raw\n"
       "        return DEFAULT_BRIDGE_PORT",
       "    if False:\n        pass")]),
    ("P3", CONF, "under",
     "the value stops being trimmed, so a variable set to whitespace is a REJECTED "
     "value rather than an unset one — the clients treat it as unset",
     [('    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "").strip()',
       '    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "")')]),
    ("P4", CONF, "under",
     "⛔ the rejection stops being recorded on the out-of-range branch, so `serve` "
     "and `doctor` cannot say why the port they are on is not the one that was "
     "asked for — the fact exists and reaches nobody",
     [("    if not (1 <= port <= 65535):\n        BRIDGE_PORT_REJECTED = raw",
       "    if not (1 <= port <= 65535):\n        pass")]),
    ("P5", CONF, "over",
     "⛔ it speaks at IMPORT time instead of recording — noise on every one of the "
     "nine subcommands that never touch a port, and before logging is configured",
     [("    except ValueError:\n        BRIDGE_PORT_REJECTED = raw\n"
       "        return DEFAULT_BRIDGE_PORT",
       "    except ValueError:\n        BRIDGE_PORT_REJECTED = raw\n"
       "        print('bad port')\n        return DEFAULT_BRIDGE_PORT")]),
    ("P6", BRIDGE, "under",
     "the rejected port stops being said where somebody is watching a bridge start",
     [('    if config.BRIDGE_PORT_REJECTED:\n        # Said here because this is where a person is watching a bridge start.',
       '    if False:\n        # Said here because this is where a person is watching a bridge start.')]),
    ("P7", CLI, "under",
     "⛔ `doctor` stops naming the refused port — the one command somebody runs "
     "when the bridge is unreachable, and the refusal is the reason it is",
     [('    if config.BRIDGE_PORT_REJECTED:\n        # ⚠ NINE CHARACTERS OR FEWER.',
       '    if False:\n        # ⚠ NINE CHARACTERS OR FEWER.')]),

    # ═══════════ E — the bind failure names only what the errno supports ═══════════
    ("E1", BRIDGE, "under",
     "⛔⛔ BACK TO ONE MESSAGE FOR EVERY ERRNO. EACCES on an AF_INET bind is the "
     "privileged-port guard — there is no holder — and the line told somebody to "
     "go and find one. Four times, in a real bridge.log, for 127.0.0.1:9",
     [("        code = getattr(e, \"errno\", None)\n        if code == errno.EADDRINUSE and _port_holder_is_bridge(host, port):",
       "        code = getattr(e, \"errno\", None)\n        if _port_holder_is_bridge(host, port):")]),
    ("E2", BRIDGE, "under",
     "the privileged-port arm goes, so EACCES falls to the generic branch and the "
     "one thing the person can act on — use a port above 1024 — is never said",
     [("        elif code == errno.EACCES:", "        elif False:")]),
    ("E3", BRIDGE, "over",
     "⛔ the two errnos swap: a real squatter is called a permissions problem and "
     "a permissions problem is called a squatter. Both sentences are then wrong in "
     "the direction that sends the person to the other one's fix",
     [("        elif code == errno.EADDRINUSE:\n            log.warning(\"bridge port %s:%d held by a NON-bridge process (%s)\", host, port, e)",
       "        elif code == errno.EACCES:\n            log.warning(\"bridge port %s:%d held by a NON-bridge process (%s)\", host, port, e)")]),
    ("E4", BRIDGE, "under",
     "⛔⛔ THE HINT GOES BACK TO `netstat -ano | findstr` EVERYWHERE — a Windows "
     "built-in, printed on darwin, and written down on the Linux sandbox that is "
     "the one deployment whose stdout is actually kept",
     [('    if sys.platform.startswith("win"):\n        return f"netstat -ano | findstr :{port}"\n'
       '    if sys.platform == "darwin":\n        return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"\n'
       "    return f\"ss -lptn 'sport = :{port}'\"",
       '    return f"netstat -ano | findstr :{port}"')]),
    ("E5", BRIDGE, "under",
     "the darwin arm goes, so a Mac is handed the Linux command",
     [('    if sys.platform == "darwin":\n        return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"',
       '    if False:\n        return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"')]),
    ("E6", BRIDGE, "over",
     "⛔ an unrecognised errno is reported as a squatter again — the exact habit "
     "that produced the EACCES line: inventing a cause for a case nobody thought "
     "about",
     [("            log.warning(\"bridge port %s:%d could not be opened — %s\", host, port, e)\n"
       "            print(f\"Port {port} could not be opened: {e}\")",
       "            log.warning(\"bridge port %s:%d could not be opened — %s\", host, port, e)\n"
       "            print(f\"Port {port} is held by another process that isn't a Super Agent bridge.\")")]),
    ("E7", BRIDGE, "over",
     "the EACCES arm probes for a holder first — asking a question whose answer "
     "cannot change what we say, and paying three HTTP timeouts to not use it",
     [("        elif code == errno.EACCES:\n            log.warning(",
       "        elif code == errno.EACCES and not _port_holder_is_bridge(host, port):\n            log.warning(")]),

    # ═══════════ U — whoever takes the note owes the person its contents ═══════════
    ("U1", SR_BE, "under",
     "⛔⛔ THE SILENT EATER RETURNS. `?via=agent` takes the one-shot announce and "
     "moves the delivered watermark past it, so the re-mint cannot recover it "
     "either; the command then prints runs alone and the sign-in is lost for good",
     [('    lines = _signed_in_lines(body.get("signedIn"))\n    for r in runs:',
       "    lines = []\n    for r in runs:")]),
    ("U2", SR_BE, "under",
     "the renderer answers nothing for every note, which is the same loss one "
     "function further in — and passes any test that only checks the call happens",
     [('    if not isinstance(note, dict) or not note:\n        return []',
       "    if True:\n        return []")]),
    ("U3", SR_BE, "over",
     "⛔ the malformed guard narrows to None, so `{}`, a string or a list reach "
     "`.get` and take the command down with an AttributeError — a chat command "
     "that raises tells the person nothing at all",
     [("    if not isinstance(note, dict) or not note:", "    if note is None:")]),
    ("U4", SR_BE, "over",
     "⛔ the which-computer ask is worded a THIRD time instead of delegating. Two "
     "copies already exist with a test holding them together, precisely so one "
     "question does not get two phrasings depending which door the person came "
     "through",
     [('    if note.get("needsDeviceChoice"):\n        return [head] + _pick_device_lines(\n'
       '            {"devices": note.get("devices")},\n'
       '            "stale_selection" if note.get("staleSelection") else "no_selection",\n'
       "            about=quoted)",
       '    if note.get("needsDeviceChoice"):\n        return [head, "Which computer should run this?"]')]),
    ("U5", SR_BE, "under",
     "the reason stops being read, so somebody whose chosen computer has gone is "
     "told to pick from a list rather than that the one they used is unreachable",
     [('            "stale_selection" if note.get("staleSelection") else "no_selection",',
       '            "no_selection",')]),
    ("U6", SR_BE, "under",
     "⛔ `via=agent` goes. That stops the eating by stopping the per-phase link "
     "minting this command exists for — a fix that removes the feature",
     [("    code, body, runs = _fetch_runs(active=args.active, via_agent=True)",
       "    code, body, runs = _fetch_runs(active=args.active, via_agent=False)")]),

    # ═══════════ W — arming forgets the previous attempt's countdown ═══════════
    ("W1", SR_BE, "under",
     "⛔⛔ ARMING STOPS CLEARING THE COUNTER. One abandoned sign-in then poisons "
     "the chat forever — the give-up returns before the state write, so the file "
     "keeps the limit, and every later listener dies on its FIRST tick",
     [("    _clear_login_wait(slug)\n", "")]),
    ("W2", SR_BE, "over",
     "⛔ the whole state file is emptied instead of one key, so every finished run "
     "is announced again — a fix that produces the spam the watcher exists to avoid",
     [('    raw.pop("__login_wait__", None)', "    raw = {}")]),
    ("W3", SR_BE, "under",
     "the cleared state is never written back: read, edited in memory, discarded",
     [("    try:\n        path.write_text(json.dumps(raw), encoding=\"utf-8\")\n    except Exception:\n        pass",
       "    return")]),
    ("W4", SR_BE, "over",
     "⛔ the read stops being best-effort, so a missing or unreadable state file "
     "takes the arm down with it — and the arm is what delivers the news",
     [("    try:\n        path = _scripts_dir() / f\".sr_poll_{slug}.state.json\"\n"
       "        raw = json.loads(path.read_text(encoding=\"utf-8\"))\n    except Exception:\n        return",
       "    path = _scripts_dir() / f\".sr_poll_{slug}.state.json\"\n"
       "    raw = json.loads(path.read_text(encoding=\"utf-8\"))")]),

    # ═══════════ G — the guard stops naming a chat it has not seen ═══════════
    ("G1", BRIDGE, "under",
     "⛔⛔ THE CARVE-OUT GOES. An origin-less chat can set a topic once and never "
     "correct or retry it — and that is the population the fleet's ordinary "
     "research-before-login order reaches first",
     [("                        and not both_anonymous\n", "")]),
    ("G2", BRIDGE, "over",
     "⛔⛔ THE ONE THAT LOOKS LIKE A FIX. `and` becomes `or`, so ONE anonymous side "
     "is enough — which reopens both thefts cross-verification found: B posting "
     "with no origin lands its topic on A's destination, and a legacy origin-less "
     "held topic can be taken outright",
     [("                both_anonymous = held_origin is None and caller_origin is None",
       "                both_anonymous = held_origin is None or caller_origin is None")]),
    ("G3", BRIDGE, "over",
     "⛔ `_clean_origin` becomes `isinstance`, so a half-origin — a platform with "
     "no chat id — counts as identified on both sides and is refused, while the "
     "comparison it falls through to has already thrown that same half away",
     [("                held_origin = _clean_origin(flow.origin)\n"
       "                caller_origin = _clean_origin(origin)",
       "                held_origin = flow.origin if isinstance(flow.origin, dict) else None\n"
       "                caller_origin = origin if isinstance(origin, dict) else None")]),
    ("G4", BRIDGE, "over",
     "⛔ the refusal claims another chat again. The cell that still refuses is also "
     "what a chat that simply lost its session environment looks like, and the "
     "bridge has read nothing that says a second chat exists",
     [('                                              "research request, and this chat "\n'
       '                                              "can\'t be shown to be the one that "\n'
       '                                              "made it — ask again once you\'re "\n'
       '                                              "signed in"})',
       '                                              "research request from another chat — "\n'
       '                                              "ask again once you\'re signed in"})')]),
    ("G5", BRIDGE, "over",
     "the held-topic test goes, so a flow carrying nothing refuses the first topic "
     "anybody attaches — the terminal sign-in can never be given one",
     [('                if ((flow.pending_topic or "").strip()\n                        and not both_anonymous',
       "                if (True\n                        and not both_anonymous")]),

    # ═══════════ A — a promise is a claim about a sender ═══════════
    ("A1", SR_BE, "over",
     "⛔⛔ \"I'll post here when it's done\" GOES BACK TO UNCONDITIONAL, printed "
     "above the call that decides whether anything will ever post. On the legacy "
     "no-origin branch there is no chat to deliver to at all",
     [('    if arm_payload.get("armed"):\n        lines.append("I’ll post here when it’s done',
       '    if True:\n        lines.append("I’ll post here when it’s done')]),
    ("A2", SR_BE, "under",
     "the opposite over-correction: the promise is never made even when the cron "
     "row was written, so the common case under-sells a follow-up that really comes",
     [('    if arm_payload.get("armed"):\n        lines.append("I’ll post here when it’s done',
       '    if False:\n        lines.append("I’ll post here when it’s done')]),
    ("A3", SR_BE, "over",
     "the signed-out link promises a pick-up again with nothing armed to do it",
     [('                         + (". I\'ll post here when it\'s done."\n'
       '                            if arm_payload.get("armed")\n'
       '                            else " — ask me once you\'re in and I\'ll tell you where "\n'
       '                                 "it got to.")]',
       '                         + ". I\'ll post here when it\'s done."]')]),
    ("A4", SR_BE, "over",
     "the other signed-out door promises it too",
     [('                    ("You\'re not signed in yet. Log in here and I\'ll pick this "\n'
       '                     "up — I\'ll post here when it\'s done:"\n'
       '                     if arm_payload.get("armed") else\n'
       '                     "You\'re not signed in yet. Log in here and I\'ll pick this "\n'
       '                     "up — ask me once you\'re in:"),',
       '                    "You\'re not signed in yet. Log in here and I\'ll pick this "\n'
       '                    "up — I\'ll post here when it\'s done:",')]),

    # ═══════════ F — the fork: the topic survives a sign-in ═══════════
    ("F1", FORK_SR, "under",
     "⛔⛔ THE TOPIC IS DROPPED AGAIN. Measured in a real transcript: the person "
     "asked, was told to sign in, signed in, asked what happened, was told only "
     "that they were signed in — and had to ask for the research a second time",
     [("        if not _sign_in_carrying(topic):\n            _say_signed_out()\n        return 0\n    if reason == \"no_devices\":",
       "        _say_signed_out()\n        return 0\n    if reason == \"no_devices\":")]),
    ("F2", FORK_SR, "over",
     "⛔⛔ THE STASH CARRIES A CHAT ORIGIN. It looks like the obvious way to earn "
     "ownership and it silences the announce completely: an origin-bearing event "
     "is handed only to a watcher that asks with a matching platform and chat id, "
     "and this fleet's watcher asks with neither. Two successes, no error, nobody "
     "told",
     [('    stash = {"pending_topic": topic}\n    scode, sbody = _get("/status")',
       '    stash = {"pending_topic": topic,\n             "origin": {"platform": "imessage", "chat_id": "dm"}}\n'
       '    scode, sbody = _get("/status")')]),
    ("F3", FORK_SR, "over",
     "⛔ any reply from the attach door counts as success, so the 409 that means "
     "the sign-in ended between the probe and the post becomes a promise that "
     "their research is waiting on a flow that no longer exists",
     [("        if pcode == 200:\n            # ⛔⛔ NOT \"IT STARTS ON ITS OWN\".",
       "        if pcode:\n            # ⛔⛔ NOT \"IT STARTS ON ITS OWN\".")]),
    ("F4", FORK_SR, "under",
     "the probe goes, so a sign-in already in flight is replaced by a fresh one — "
     "voiding the address the person is about to tap",
     [('    if scode == 200 and str(sbody.get("remoteLogin") or "") == "pending":',
       "    if False:")]),
    ("F5", FORK_SR, "under",
     "⛔ the address is printed without being vouched for, on the one channel that "
     "reaches the person character for character",
     [('    if lcode == 200 and _is_https(url):', "    if lcode == 200:")]),
    ("F6", FORK_SR, "under",
     "the last resort goes: when no address can be minted at all, nothing is said",
     [("        if not _sign_in_carrying(topic):\n            _say_signed_out()\n        return 0\n    if reason == \"no_devices\":",
       "        _sign_in_carrying(topic)\n        return 0\n    if reason == \"no_devices\":")]),
    ("F7", FORK_SR, "under",
     "the SECOND door loses it — the session lapsing between the two run attempts "
     "puts somebody with no computer of their own back at the dead end, which is "
     "the population the shared-computer rescue exists for",
     [("            if not _sign_in_carrying(topic):\n                _say_signed_out()\n            return 0",
       "            _say_signed_out()\n            return 0")]),

    # ═══════════ L — a second sign-in must not orphan the first ═══════════
    ("L1", FORK_SR, "under",
     "⛔⛔ IT MINTS A FRESH FLOW EVERY TIME AGAIN. The previous token is never "
     "polled, so the address the person is looking at stops working and any "
     "research attached to it goes with it — and nothing tells them",
     [('    state = str(pbody.get("state") or "") if pstatus == 200 else ""',
       '    state = ""')]),
    ("L2", FORK_SR, "over",
     "⛔ any state is reprinted, so an EXPIRED link is handed out again — to "
     "somebody who is asking precisely because the first one stopped working",
     [('    if state == "pending":\n        live = str(pbody.get("verifyUrl") or "").strip()',
       '    if state:\n        live = str(pbody.get("verifyUrl") or "").strip()')]),
    ("L3", FORK_SR, "over",
     "⛔⛔ THE PROMISE COMES BACK. A five-minute job and a one-shot in memory "
     "cannot keep it, and the measured ordinary case is a person asking after "
     "seventy-eight seconds",
     [('            _say("Tell them to take their time, and to message you once they are in.")\n            return 0\n    _fail(status, body, "start the sign in")',
       '            _say("Tell them to take their time, and that you will text once they are in.")\n            return 0\n    _fail(status, body, "start the sign in")')]),

    # ═══════════ D — a computer that is switched off ═══════════
    ("D1", FORK_SR, "over",
     "⛔⛔ `all` BECOMES `any`: one sleeping computer beside two awake ones is "
     "announced as \"none of their computers is switched on\", which is the "
     "measured transcript's exact list said back to them as a falsehood",
     [("    return bool(devices) and all(d.get(\"online\") is False for d in devices",
       "    return bool(devices) and any(d.get(\"online\") is False for d in devices")]),
    ("D2", FORK_SR, "under",
     "⛔ `all([])` is True: with no list attached it announces that computers it "
     "has never seen are switched off — the same unfounded claim as naming a "
     "squatter that does not exist",
     [('    return bool(devices) and all(d.get("online") is False for d in devices',
       '    return all(d.get("online") is False for d in devices')]),
    ("D3", FORK_SR, "under",
     "the offer stops putting awake computers first, so the one that cannot start "
     "for hours is as likely to be picked as the two that can",
     [("    ordered = devices\n    if for_running:\n        ordered = ([d for d in devices if d.get(\"online\") is not False]\n"
       "                   + [d for d in devices if d.get(\"online\") is False])",
       "    ordered = devices")]),
    ("D4", FORK_SR, "under",
     "\"(off)\" says nothing about what picking it MEANS again — which is the whole "
     "defect: the mark was always there and told a person choosing between three "
     "names nothing about the wait",
     [('            marks.append("off — waits until it is switched on" if for_running else "off")',
       '            marks.append("off")')]),
    ("D5", FORK_SR, "over",
     "⛔ an inventory is rendered as an offer: a list somebody asked to SEE is "
     "reordered, silently disagreeing with every other surface",
     [("    _say(\"Their research computers:\")\n    _print_devices(devices)",
       "    _say(\"Their research computers:\")\n    _print_devices(devices, for_running=True)")]),
    ("D6", FORK_SR, "under",
     "⛔ the three cases collapse back into one sentence, and it is false in the "
     "commonest of them: the program only asks this when the number of AWAKE "
     "computers is zero or more than one",
     [("        if _waits_for_power(listed):\n            _say(\"None of their computers is switched on right now. Whichever they \"\n"
       "                 \"pick, the research waits until that computer is on. Ask which one:\")\n"
       "        elif reason == \"stale_selection\":",
       "        if False:\n            pass\n        elif reason == \"stale_selection\":")]),
    ("D7", FORK_SR, "under",
     "a run queued to a sleeping computer is announced as \"Running on\" it again — "
     "the power state is fetched on the very next line and thrown away",
     [('                    if entry.get("online") is False:\n'
       '                        _say("Waiting for %s — it is switched off, so this starts "\n'
       '                             "when it comes on." % _device_label(entry))\n'
       "                    else:\n"
       '                        _say("Running on %s." % _device_label(entry))',
       '                    _say("Running on %s." % _device_label(entry))')]),
    ("D8", FORK_SR, "under",
     "switching to a sleeping computer hides the wait entirely",
     [('        if match.get("online") is False:\n'
       '            _say("Research will now run on %s. It is switched off, so anything "\n'
       '                 "started waits until it comes on." % _device_label(match))\n'
       "        else:\n"
       '            _say("Research will now run on %s." % _device_label(match))',
       '        _say("Research will now run on %s." % _device_label(match))')]),

    # ═══════════ X — the guard that keeps the client off a shared machine ═══════════
    ("X1", FORK_SR, "under",
     "⛔⛔ THE SHARED-HOST GUARD ALWAYS PASSES. The loopback bridge authenticates "
     "nobody, so off a per-tenant namespace this client would talk to whatever "
     "answers the port",
     [("    return SANDBOX_DIR.is_dir()", "    return True")]),
    ("X2", FORK_SR, "over",
     "⛔⛔ THE BRIDGE IS REACHED FOR BEFORE THE GUARD RUNS — and starting one on a "
     "shared machine is precisely the act the guard exists to prevent, so the "
     "refusal arrives after the damage",
     [("def _require_bridge() -> None:\n    if not _guard_shared_host():\n"
       "        _say(\"Research is not set up to run on this computer.\")\n        raise SystemExit(0)\n"
       "    if not ensure_bridge():",
       "def _require_bridge() -> None:\n    up = ensure_bridge()\n"
       "    if not _guard_shared_host():\n"
       "        _say(\"Research is not set up to run on this computer.\")\n        raise SystemExit(0)\n"
       "    if not up:")]),
    ("X3", FORK_SR, "over",
     "⛔ the guard becomes switchable from the environment, which is exactly what "
     "it must never be: anything on a native VM could then turn it off",
     [('SANDBOX_DIR = Path("/sandbox")',
       'SANDBOX_DIR = Path(os.environ.get("SR_SANDBOX_DIR", "/sandbox"))')]),

    # ═══════════ R — the round-2 fixes, every one found by cross-verification ═══════════
    ("R1", FORK_SR, "over",
     "⛔⛔ THE POLL GOES BACK TO BEING TREATED AS A READ. A poll REDEEMS an approval "
     "the person has already given — it signs them in and mints the one-shot note — "
     "so falling through to a fresh sign-in CAUSES the capture and then destroys it: "
     "somebody who has just signed in is told to sign in, and the next check answers "
     "'not signed in yet' about an account that is",
     [('    if state == "connected" and pbody.get("authed"):', "    if False:")]),
    ("R2", FORK_SR, "under",
     "⛔ the flow's own LABEL decides it instead of the live session. A flow is left "
     "at connected after a capture, so it outlives the session it made — after a sign "
     "out this would refuse to ever mint another sign-in",
     [('    if state == "connected" and pbody.get("authed"):',
       '    if state == "connected":')]),
    ("R3", FORK_SR, "under",
     "the topic the poll reported is dropped, so somebody who asked for research "
     "before signing in is told only that they are in",
     [('        pending = str(pbody.get("pendingTopic") or "").strip()\n        if pending:',
       "        pending = \"\"\n        if pending:")]),
    ("R4", SR_BE, "under",
     "⛔⛔ THE NO-RUNS LINE GOES BACK TO BEING KEYED ON `lines`, which the sign-in "
     "announce made dead: somebody who asked what was running gets a sign-in line "
     "and NO statement about their runs at all",
     [("    if not runs:\n        lines.append(\"No active runs.\")",
       "    if not lines:\n        lines.append(\"No active runs.\")")]),
    ("R5", BRIDGE, "over",
     "⛔ the privileged-port sentence is said for EVERY EACCES again, so a port "
     "above 1024 refused by a firewall is given a false reason and then advised to "
     "be set to the value that has just failed",
     [("            if port < 1024:", "            if True:")]),
    ("R6", CLI, "under",
     "the doctor label goes back to eleven characters, and `_doctor_row` pads with "
     "ljust(10) — so it renders welded to its own text: `bridge portignoring ...`",
     [('        _doctor_row("port", False,', '        _doctor_row("bridge port", False,')]),
    ("R7", SR_BE, "over",
     "⛔⛔ EMPTY STOPS BEING UNSET IN THE CHAT CLIENT, so a variable that is set and "
     "empty — a shape a shell exports readily — prints `(ignoring bad "
     "SUPER_AGENT_BRIDGE_PORT ''; using 9876)` to stderr on EVERY invocation while "
     "the bridge treats the same value as absent",
     [('    raw = (os.environ.get("SUPER_AGENT_BRIDGE_PORT") or "").strip()\n'
       "    port = 9876\n"
       "    if raw:\n"
       "        try:\n"
       "            val = int(raw)\n"
       "            if 1 <= val <= 65535:\n"
       "                port = val\n"
       "            else:\n"
       "                raise ValueError\n"
       "        except ValueError:\n"
       '            print(f"(ignoring bad SUPER_AGENT_BRIDGE_PORT {raw!r}; using 9876)",\n'
       "                  file=sys.stderr)",
       '    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "9876")\n'
       "    try:\n"
       "        port = int(raw)\n"
       "        if not (1 <= port <= 65535):\n"
       "            raise ValueError\n"
       "    except ValueError:\n"
       '        print(f"(ignoring bad SUPER_AGENT_BRIDGE_PORT {raw!r}; using 9876)",\n'
       "              file=sys.stderr)\n"
       "        port = 9876")]),
    ("R8", FORK_POLL, "under",
     "⛔⛔ THE VERBATIM SURFACE STOPS ORDERING ITS OFFER, so the worked example — "
     "which names the first computer in the list — can tell somebody word for word "
     "to pick the one machine that will not start their work until it is switched on",
     [("        devs = ([d for d in devs if d.get(\"online\") is not False]\n"
       "                + [d for d in devs if d.get(\"online\") is False])",
       "        devs = list(devs)")]),
    ("R9", FORK_POLL, "under",
     "the off mark in the texted offer goes back to a bare (off), which says nothing "
     "about the wait — in the one message that reaches the person with no turn in "
     "between to add it",
     [('                    (" (off - waits until it is switched on)" if up is False else ""))',
       '                    (" (off)" if up is False else ""))')]),
    ("R10", FORK_POLL, "under",
     "the texted offer claims 'more than one of their computers could run it' when "
     "none of them is awake — the same falsehood the sibling client stopped saying, "
     "in the surface where it is delivered word for word",
     [('        if devs and all(d.get("online") is False for d in devs):',
       "        if False:")]),

    # ═══════════ Q — round 3: the sentences that were still false ═══════════
    ("Q1", SR_BE, "over",
     "⛔⛔ THE UNARMED COPY REWRITES WHAT THE BRIDGE DOES again — \"then tell me and "
     "I'll start it\", as though an unwritten cron row stopped the research "
     "starting. Capture claims the topic and enqueues the run SERVER-SIDE before "
     "any tick, on by default; arming decides who TELLS them",
     [('                         + (". I\'ll post here when it\'s done."\n'
       '                            if arm_payload.get("armed")\n'
       '                            else " — ask me once you\'re in and I\'ll tell you where "\n'
       '                                 "it got to.")]',
       '                         + (". I\'ll post here when it\'s done."\n'
       '                            if arm_payload.get("armed")\n'
       '                            else ", then tell me and I\'ll start it.")]')]),
    ("Q2", SR_BE, "under",
     "⛔ a run queued on a switched-off computer is announced as STARTED again — "
     "\"Started your research on Macbook\" reads as work in progress when it means "
     "\"waiting until somebody switches it on\", which could be tomorrow",
     [('        if where and note.get("deviceOnline") is False:', "        if False:")]),
    ("Q3", SR_BE, "over",
     "⛔⛔ AN UNKNOWN POWER STATE IS TREATED AS OFF, so an announce that simply "
     "could not read the device invents a wait that may not exist — the same "
     "defect as the missing sentence, pointing the other way",
     [('        if where and note.get("deviceOnline") is False:',
       '        if where and not note.get("deviceOnline"):')]),
    ("Q4", BRIDGE, "under",
     "the power state never reaches the announce, so all three renderers are back "
     "to not being able to say it however carefully they are written",
     [('            "deviceOnline": _device_is_online(chosen) if chosen else None,',
       '            "deviceOnline": None,')]),
    ("Q5", BRIDGE, "under",
     "the field is dropped at the wire instead, which looks like a different bug "
     "from Q4 and produces the identical silence",
     [('                            "deviceOnline": ev.get("deviceOnline"),',
       '                            "deviceOnline": None,')]),
    ("Q6", BRIDGE, "over",
     "⛔ the device lookup stops being best-effort, so a Firestore blip takes a "
     "STARTED run's whole announce down with it — a courtesy field failing the "
     "thing it is a courtesy about",
     [("    except Exception as e:  # noqa: BLE001 — a courtesy field, never a failure\n"
       "        log.warning(\"could not read the auto-start device's power state (%s)\",\n"
       "                    type(e).__name__)\n    return None",
       "    except Exception:\n        raise")]),
    ("Q7", SR_BE, "under",
     "⛔ the sign-in door asks \"which should run this?\" again, in a place where "
     "there is no \"this\" — it is telling somebody what has been WAITING, and the "
     "run path's object is the wrong one there",
     [("            about=quoted)", "            about=\"this\")")]),
    ("Q8", CLI, "under",
     "⛔ `doctor` stops naming the origin it probed, so somebody whose client and "
     "bridge are on different ports — the incident's own shape, and one the "
     "refused-port row cannot report because port 9 is ACCEPTED — is told only "
     "that the bridge is down",
     [('                    f"down at {config.bridge_origin()} "\n'
       '                    f"(run: superresearch-agent serve)")',
       '                    "down (run: superresearch-agent serve)")')]),
    ("Q9", SR_BE, "under",
     "⛔⛔ ARMING STOPS RESETTING THE COUNTER FOR A FILE THE WATCHDOG CAN ACTUALLY "
     "PRODUCE. The guard narrows to a shape that only exists if a chat was already "
     "signed in — which is precisely when the counter is never written — so the "
     "fix is dead and the suite stays green",
     [('    if not isinstance(raw, dict) or "__login_wait__" not in raw:',
       '    if not isinstance(raw, dict) or len(raw) < 2:')]),
    ("Q10", FORK_SR, "over",
     "⛔⛔ THE FLEET IS PROMISED A START AGAIN. Against the pinned wheel a stashed "
     "topic runs only if the account already has a computer, and a first-ever "
     "signer-in has none — which is the entire population a shared research "
     "computer exists for",
     [('        _say("They are not signed in yet. Send them this — it remembers %s and "\n'
       '             "picks it up the moment they are in:" % _topic_phrase(topic))',
       '        _say("They are not signed in yet. Send them this — their research "\n'
       '             "starts by itself once they are in:")')]),
    ("Q11", FORK_SR, "under",
     "the attach door stops naming the topic it now carries, so a second ask "
     "silently replaces a first with nothing on screen to say so",
     [('                 "%s, and it is picked up the moment they finish in the browser."\n'
       "                 % _topic_phrase(topic))",
       '                 "their research, and it is picked up the moment they finish."\n'
       "                 % ())")]),
    ("Q12", FORK_SR, "under",
     "⛔⛔ THE THIRD COPY OF THE QUESTION LOSES THE POWER STATE AGAIN — the reply "
     "somebody gets when they say they are done goes back to a bare comma list "
     "that never reads `online`, while the other two surfaces keep it",
     [('            rows.append(label + (" (on)" if up is True else\n'
       '                                 (" (off - waits until it is switched on)"\n'
       '                                  if up is False else "")))',
       "            rows.append(label)")]),
    ("Q13", FORK_SR, "under",
     "the sign-in relay claims a choice when none of their computers is awake",
     [('        if devs and all(d.get("online") is False for d in devs):\n'
       '            return ["%s has not started: none of their computers is switched on, so "',
       '        if False:\n'
       '            return ["%s has not started: none of their computers is switched on, so "')]),
    ("Q14", FORK_SR, "under",
     "the relay announces a run queued on a switched-off computer as already "
     "started",
     [('        if where and note.get("deviceOnline") is False:\n'
       '            return ["%s is queued on %s, which is switched off — it starts when "',
       '        if False:\n'
       '            return ["%s is queued on %s, which is switched off — it starts when "')]),
    ("Q15", FORK_POLL, "under",
     "⛔ the VERBATIM surface announces a queued run as starting now. This one "
     "reaches the person with no model turn to soften it",
     [('        if where and signed.get("deviceOnline") is False:', "        if False:")]),
    ("Q16", FORK_SKILL, "under",
     "the skill goes back to telling the assistant the research starts by itself, "
     "which is false for anybody signing in for the first time",
     [("Do not tell them it will start by itself.",
       "Tell them it will start by itself.")]),

    # ═══════════ S — the prose and the provisioner say one thing ═══════════
    ("S1", FORK_SKILL, "under",
     "⛔⛔ THE SKILL AND THE PROVISIONER DISAGREE ABOUT THE CADENCE. Both create "
     "this job and both are idempotent BY NAME, so whichever runs first wins and "
     "the other silently agrees to a cadence it did not choose — invisible by "
     "construction, because the job exists either way",
     [('schedule "every 5m"', 'schedule "every 2m"')]),
    ("S2", FORK_CRON, "under",
     "the same disagreement from the other side",
     [('JOB_SCHEDULE = "every 5m"', 'JOB_SCHEDULE = "every 1m"')]),
    ("S3", FORK_SKILL, "under",
     "⛔ the ban on promising a text goes, so the assistant is free to say the one "
     "thing a five-minute job and a one-shot note cannot deliver on time",
     [("**Never promise to text them once they are in.**",
       "**Tell them you will text them once they are in.**")]),
    ("S4", FORK_SKILL, "under",
     "⛔⛔ THE ASK GOES. The only reliable answer is gated on the person speaking "
     "first, and nothing anywhere asked them to — which is why the reliable path "
     "was reached by accident in the one transcript we have",
     [("Tell them to take their time, **and to message you once they are in** — that",
       "Tell them to take their time — that")]),
    ("S5", FORK_SKILL, "over",
     "the instruction stops telling the assistant to do the watcher check FIRST — "
     "it now reads 'Later in this section', so the commonest door (the research "
     "command, which mints an address of its own) can send a link with nothing "
     "watching for the answer.\n"
     "     ⚠ RESTATED. This survived its first run and the reason was the `why`, "
     "not the tests: it claimed the check 'moves back below the sign-in command' "
     "and the edit moves NO text at all — only the word that tells the assistant "
     "when to act. An ordering assertion could never have seen it. A `why` must be "
     "what the edit does",
     [("Before anything else in this section, make sure the watcher described in",
       "Later in this section, make sure the watcher described in")]),
]


_INFLIGHT = Path(__file__).with_suffix(".inflight")


def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> str | None:
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *OURS, "agent/tests"],
             cwd=ROOT).stdout
    ours = [f"[be] {ln}" for ln in out.splitlines() if ln and not ln.startswith("?? ")]
    out2 = sh(["git", "status", "--porcelain", "--", *THEIRS,
               "skills/tests"], cwd=FORK).stdout
    theirs = [f"[fork] {ln}" for ln in out2.splitlines() if ln and not ln.startswith("?? ")]
    return ours + theirs


def run_tests() -> bool:
    """Both legs, and both must pass.

    ⛔ The agent package and the fork are separate programs with separate rootdirs,
    and the fork has its own virtualenv because its suite imports modules this repo
    does not have. A harness that ran one leg would report every mutant in the
    other as killed.

    ⛔⛔ AND THE FORK LEG DEMANDS A CLEAN EXIT WITH NO TOLERANCE. The fork's
    `skills/tests` DIRECTORY carries pre-existing failures, so an earlier harness
    in this repo allowed a budget — and because the leg runs ONE FILE, which is
    clean, that budget silently absorbed the first real kills and reported every
    fork mutant as a survivor."""
    purge_pycache(ROOT)
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    agent = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
                "-q", "-p", "no:cacheprovider"],
               cwd=ROOT / "agent", env=agent_env)
    if agent.returncode != 0:
        return False
    purge_pycache(FORK)
    fork_py = FORK / ".venv" / "bin" / "python"
    if not fork_py.exists():
        raise AssertionError(
            f"the fork's virtualenv is missing at {fork_py} — this harness cannot "
            "measure the fourth client without it, and skipping that leg would "
            "report every fork mutant as killed")
    fork = sh([str(fork_py), "-B", "-m", "pytest", FORK_SUITES,
               "-q", "-p", "no:cacheprovider"], cwd=FORK, env=ENV)
    return fork.returncode == 0


def _path_for(fname: str) -> Path:
    return (FORK / fname) if fname in THEIRS else (ROOT / fname)


def main() -> int:
    only = {a.strip() for a in sys.argv[1:] if a.strip()}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — this is a spot check, "
              f"not a score for the stretch.")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\n"
              "Restore that file (git checkout -- <file>), then delete\n"
              f"    {_INFLIGHT}")
        return 2

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
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the stretch's score)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out "
              f"of the score above:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
