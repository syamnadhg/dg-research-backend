"""The chat's Allow-all arm acts only on a WHOLE-MESSAGE command (wave 12 repair 2,
2026-09-27).

⛔⛔ THREE REVIEW ROUNDS FOUND MISROUTES IN AN ARM THAT READ INTENT FROM FREE TEXT
BY SHAPE. Round 2, driven through `sr._nl_resolve` at repair 1 (850334c):

  · `my mac stopped letting anyone join, can you fix it` — a FAULT REPORT —
    switched Allow all OFF, unconfirmed (cmd_do POSTed {allowAll: false});
  · `turn off allow all and sharing on my mac` raised the PUBLISH confirm;
  · `since my mac is offline, list computers that let anyone join` — a JOINER —
    raised the confirm that opens the joiner's own computer;
  · `leave the lab pc alone and turn off allow all on my mac` switched it off on
    the LAB PC; `turn off allow all on my mac and stop the Mars run` dropped the
    stop; `allow all on my mac, turn it off` hid the computer;
  · the round-1 "on or off?" ask-back trapped plain requests; `research why people
    don't join unions` was refused; `sign in and ask to join the Studio PC` asked
    to disclose the person's name instead of signing in.

⭐ THE POLICY PINNED HERE, BY EXECUTING THE ROUTER — never by reading source:
  1. A whole-message command acts (OFF) or confirms (ON). Politeness in front,
     thanks behind, one `so/because/since …` purpose clause; ONE computer at most.
  2. A hide in the visibility clause's own words is that clause's hide.
  3. Other people's computers are the browse list, or the ask for the ONE computer
     a whole-message `join X` names.
  4. Anything else that talks about Allow all is NEVER a write and NEVER a switch
     confirm: the person's own list, or the catch-all, which names the phrasings.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
_SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_whole_message_0927", "sr.py")

_TAGS = (("device-allow-all", "ON"), ("device-ask", "ASK"), ("device-visibility", "PUBLISH"),
         ("device-approve", "APPROVE"), ("device-deny", "DENY"), ("stop", "STOP"))


def _route(text: str) -> str:
    """The route as a short tag: OFF[:name], ON[:name], HIDE[:name], DEVICES,
    PUBLIC, LOGIN, ADD:<code>, ASK[:name], CATCH, SET, PUBLISH, APPROVE[:name], …"""
    argv, lines = sr._nl_resolve(text)
    if argv is not None:
        if argv[:2] == ["device-allow-all", "no"]:
            return "OFF" + (f":{argv[2]}" if len(argv) > 2 else "")
        if argv[:2] == ["device-visibility", "private"]:
            return "HIDE" + (f":{argv[2]}" if len(argv) > 2 else "")
        if argv == ["devices"]:
            return "DEVICES"
        if argv == ["devices-public"]:
            return "PUBLIC"
        if argv == ["login"]:
            return "LOGIN"
        if argv[0] == "device-add":
            return "ADD:" + argv[1]
        return "ARGV:" + json.dumps(argv, ensure_ascii=False)
    said = " ".join(lines or [])
    if said == sr._NL_CATCH_ALL:
        return "CATCH"
    for key, tag in _TAGS:
        head = sr._NL_CONFIRMS[key].split("{name}")[0]
        if said.startswith(head):
            rest = said[len(head):]
            name = rest[1:rest.index("”")] if rest.startswith("“") else ""
            return tag + (f":{name}" if name else "")
    if said.startswith("I switch Allow all one computer at a time"):
        return "SET"
    return "LINE:" + said[:60]


# ── 1. every phrasing the two cross-verify rounds and their refuters quoted ──────
# The findings' own strings (scenario, evidence, refuter reason) plus every message
# in the refuters' probe lists, each at its route under the new policy. Reviewed
# row by row; the reverse must-nots below say what none of them may ever be.
PINNED = [
    ('join BCDF-GHJK', 'ADD:BCDF-GHJK'),  # F5
    ('join BCDF-GHJK please', 'ADD:BCDF-GHJK'),  # t6
    ('i want to join K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # t6
    ('join "K7XQ-9B2M"', 'ADD:K7XQ-9B2M'),  # t6
    ('join computer K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # t6
    ('join K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # F5
    ('join K7XQ-9B2M please', 'ADD:K7XQ-9B2M'),  # t6
    ('join K7XQ-9B2M thanks', 'ADD:K7XQ-9B2M'),  # t6
    ('join K7XQ-9B2M, it lets anyone in', 'ADD:K7XQ-9B2M'),  # F5
    ("join my friend's computer K7XQ-9B2M", 'ADD:K7XQ-9B2M'),  # t6
    ("join my friend's mac with K7XQ-9B2M", 'ADD:K7XQ-9B2M'),  # t6
    ('join the computer K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # t6
    ('join the mac with K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # t6
    ('join using code K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # t6
    ('K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # F5
    ('please let me join K7XQ-9B2M', 'ADD:K7XQ-9B2M'),  # t6
    ('join K7XQ9B2M', 'ADD:K7XQ9B2M'),  # t6
    ('join WDJB-MJHT', 'ADD:WDJB-MJHT'),  # t6
    ('sign in with WDJB-MJHT and join the Studio PC', 'ADD:WDJB-MJHT'),  # t6
    ('join bcdf-ghjk', 'ADD:bcdf-ghjk'),  # t6
    ('join k7xq-9b2m', 'ADD:k7xq-9b2m'),  # t6
    ('approve the request to join my mac', 'APPROVE'),  # t9
    ('Sam is asking to join my mac, approve him', 'APPROVE'),  # t9
    ('anyone asking to join my mac should get in automatically', 'ARGV:["device-requests"]'),  # t9
    ('did my request to join the Studio PC go through', 'ARGV:["device-requests"]'),  # t9
    ('I asked to join the Studio PC, did they answer', 'ARGV:["device-requests"]'),  # t9
    ("I don't want anyone joining or finding my mac", 'ARGV:["device-requests"]'),  # t4
    ("I'd prefer people ask first on my mac", 'ARGV:["device-requests"]'),  # t7
    ('let anyone asking to join my mac in', 'ARGV:["device-requests"]'),  # t9
    ('make my mac open to anyone who asks', 'ARGV:["device-requests"]'),  # t13
    ('open my mac to anyone who asks', 'ARGV:["device-requests"]'),  # t13
    ('people keep asking to join my mac', 'ARGV:["device-requests"]'),  # t9
    ('people should ask before joining my mac', 'ARGV:["device-requests"]'),  # t3
    ('someone is asking to join my mac', 'ARGV:["device-requests"]'),  # t9
    ('someone requested to join my mac', 'ARGV:["device-requests"]'),  # t9
    ('start making people ask on my mac', 'ARGV:["device-requests"]'),  # t16
    ('stop asking me to approve people for my mac', 'ARGV:["device-requests"]'),  # t2
    ('stop making people ask on my mac', 'ARGV:["device-requests"]'),  # t2
    ('stop people asking to join my mac', 'ARGV:["device-requests"]'),  # t9
    ('who is asking to join my mac', 'ARGV:["device-requests"]'),  # t9
    ('join the Mars run on the Studio PC', 'ARGV:["device-use", "Studio PC"]'),  # t10
    ("pause the why people don't join unions run", 'ARGV:["pause", "why people don\'t join unions"]'),  # t10
    ('send me the podcast for the why people never join gyms research', 'ARGV:["podcast", "why people never join gyms"]'),  # t10
    ('research the EV market on my mac, allow all agents', 'ARGV:["research", "the EV market on my mac, allow all agents"]'),  # t10
    ('research whether to join the EU', 'ARGV:["research", "whether to join the EU"]'),  # t10
    ("research why employees won't join the pension plan", 'ARGV:["research", "why employees won\'t join the pension plan"]'),  # t1
    ('look into why nobody wants to join our team', 'ARGV:["research", "why nobody wants to join our team"]'),  # t10
    ("research why people don't join unions", 'ARGV:["research", "why people don\'t join unions"]'),  # G12
    ("research why people don't join, and skip the video", 'ARGV:["research", "why people don\'t join, and", "--no-video"]'),  # t10
    ('look into why users never join the beta', 'ARGV:["research", "why users never join the beta"]'),  # G12
    ("research why young people don't join the military", 'ARGV:["research", "why young people don\'t join the military"]'),  # t1
    ("skip the video on the why people don't join clubs run", 'ARGV:["skip", "--run=why people don\'t join clubs", "video"]'),  # t10
    ("status of the why people don't join unions run", 'ARGV:["status", "why people don\'t join unions"]'),  # t10
    ("join Sam's computer", "ASK:Sam's computer"),  # t10
    ("join Sam's mac", "ASK:Sam's mac"),  # t10
    ('can I join the Studio PC?', 'ASK:Studio PC'),  # t6
    ('join public computer Studio PC', 'ASK:Studio PC'),  # G20
    ('join the Studio PC, it lets anyone in', 'ASK:Studio PC'),  # G4
    ('should I join the Studio PC', 'ASK:Studio PC'),  # t6
    ('sign up and join the Studio PC', 'ASK:Studio PC'),  # t6
    ('ask for the studio pc', 'ASK:studio pc'),  # in1
    ('join studio pc', 'ASK:studio pc'),  # in1
    ('join the studio pc', 'ASK:studio pc'),  # in1
    ('join the studio pc that lets anyone in', 'ASK:studio pc'),  # G29
    ('allow all', 'CATCH'),  # in1
    ('allow all on the Mars run', 'CATCH'),  # t10
    ('allow all three agents on the Mars run', 'CATCH'),  # t10
    ('did I join the Studio PC', 'CATCH'),  # F10
    ('do not allow all on my mac', 'CATCH'),  # t13
    ("don't allow anyone to join my mac", 'CATCH'),  # t15
    ("don't ask me, just let anyone join my mac", 'CATCH'),  # t7
    ("don't ask to join the Studio PC", 'CATCH'),  # t9
    ("don't disable allow all on my mac", 'CATCH'),  # t7
    ("don't join the Studio PC", 'CATCH'),  # F10
    ("don't make me approve anyone on my mac", 'CATCH'),  # t2
    ("don't turn off allow all on my mac", 'CATCH'),  # t7
    ('explain allow all', 'CATCH'),  # t7
    ('find a computer i can join', 'CATCH'),  # in2
    ('hide it and turn off allow all', 'CATCH'),  # t4
    ('how do I join the Studio PC', 'CATCH'),  # t6
    ('I already asked to join the Studio PC', 'CATCH'),  # t9
    ('I asked to join the Studio PC', 'CATCH'),  # t9
    ("I don't need to approve people on my mac", 'CATCH'),  # t2
    ("i don't want to approve people anymore", 'CATCH'),  # in2
    ("I don't want to approve people on my mac anymore", 'CATCH'),  # t2
    ("I don't want to ask to join the Studio PC", 'CATCH'),  # t9
    ('i no longer want to approve each person on my mac', 'CATCH'),  # in2
    ('I no longer want to approve people on my mac', 'CATCH'),  # t2
    ('I regret turning on allow all, turn it off', 'CATCH'),  # t3
    ('I turned on allow all by mistake, undo it', 'CATCH'),  # t3
    ('I want the one that lets me straight in', 'CATCH'),  # t14
    ('join a computer', 'CATCH'),  # t10
    ('join K7XQ 9B2M', 'CATCH'),  # t6
    ('join K7XQ-9B2M now', 'CATCH'),  # t6
    ('join K7XQ-9B2M — my friend gave it to me', 'CATCH'),  # t6
    ('join K7XQ–9B2M', 'CATCH'),  # t6
    ('join me on the Studio PC', 'CATCH'),  # t10
    ('join the research on the Studio PC', 'CATCH'),  # t10
    ('join using K7XQ-9B2M', 'CATCH'),  # t6
    ('join with K7XQ-9B2M', 'CATCH'),  # t6
    ('join with this: K7XQ-9B2M', 'CATCH'),  # t6
    ("keep allow all on for my mac, don't turn it off", 'CATCH'),  # t7
    ("let anyone join my mac, I don't want to approve anymore", 'CATCH'),  # t7
    ('let people in', 'CATCH'),  # t10
    ('let the people waiting in', 'CATCH'),  # t10
    ('never ask me again, let anyone join my mac', 'CATCH'),  # t7
    ('never ask to join the Studio PC', 'CATCH'),  # t9
    ('never join the Studio PC', 'CATCH'),  # F10
    ('no longer allow people to join my mac', 'CATCH'),  # t15
    ('no need to approve people on my mac anymore', 'CATCH'),  # t2
    ('pause the run and turn off allow all', 'CATCH'),  # t11
    ('please switch off the allow all I just turned on', 'CATCH'),  # t3
    ("research why people don't use linux", 'CATCH'),  # t1
    ('show allow all', 'CATCH'),  # in2
    ('skip the approval step on my mac', 'CATCH'),  # t2
    ('stop allow all and sharing on my mac', 'CATCH'),  # t5
    ('stop asking me first on my mac', 'CATCH'),  # t2
    ('stop the Mars run and turn off allow all', 'CATCH'),  # t11
    ("strangers can't get in, my mac won't let anyone in", 'CATCH'),  # t1
    ('Studio PC (joins at once)', 'CATCH'),  # t14
    ('the Studio PC, since it lets you straight in', 'CATCH'),  # t14
    ('turn allow all off and hide it', 'CATCH'),  # t4
    ('turn off allow all and log me out', 'CATCH'),  # t11
    ('turn off allow all and sharing', 'CATCH'),  # t5
    ('turn off allow all and sign out', 'CATCH'),  # G15
    ('turn off allow all and stop the run', 'CATCH'),  # t11
    ('turn off allow all and update', 'CATCH'),  # t11
    ('turn on allow all and stop requiring my approval', 'CATCH'),  # G11
    ("turn on allow all for my mac, don't make me approve people", 'CATCH'),  # t7
    ('which ones let me in straight away', 'CATCH'),  # t14
    ('• Studio PC · online · joins at once', 'CATCH'),  # t14
    ('deny the request to join my mac', 'DENY'),  # t9
    ('accept anyone who asks for my mac', 'DEVICES'),  # t13
    ('accept everyone on my mac', 'DEVICES'),  # t13
    ('allow all agents on my mac', 'DEVICES'),  # t10
    ('allow all apps on my laptop', 'DEVICES'),  # G20
    ('allow all for my mac no matter who asks', 'DEVICES'),  # G2
    ('allow all for my studio pc', 'DEVICES'),  # in1
    ('allow all for the EV research on my mac', 'DEVICES'),  # G20
    ('allow all is off for my mac, turn it on', 'DEVICES'),  # t7
    ('allow all is on for my mac, turn it off', 'DEVICES'),  # t7
    ('allow all notifications on my mac', 'DEVICES'),  # t10
    ('allow all off on my mac?', 'DEVICES'),  # t8
    ('allow all on my mac', 'DEVICES'),  # in1
    ('allow all on my mac — switch it off please', 'DEVICES'),  # t3
    ('allow all on my mac, turn it off', 'DEVICES'),  # G16
    ('allow all phases on my mac', 'DEVICES'),  # t10
    ('allow all status', 'DEVICES'),  # G26
    ('allow all was a mistake, turn it off for my mac', 'DEVICES'),  # t3
    ("allow all's off for my mac now?", 'DEVICES'),  # t8
    ('allow anybody onto my mac', 'DEVICES'),  # t13
    ('allow anyone in to my mac', 'DEVICES'),  # t13
    ('allow anyone to get on my mac', 'DEVICES'),  # t13
    ('allow everyone onto my mac', 'DEVICES'),  # t13
    ('allow people in on my mac', 'DEVICES'),  # t13
    ('allow strangers on my mac', 'DEVICES'),  # t13
    ('anyone can join my computer', 'DEVICES'),  # in1
    ('anyone can join my mac right now?', 'DEVICES'),  # t7
    ('approvals back on for my mac', 'DEVICES'),  # t3
    ('approve anyone asking to join my mac', 'DEVICES'),  # t9
    ('approve anyone who asks for my mac', 'DEVICES'),  # t13
    ('approve whoever asks for my mac', 'DEVICES'),  # t13
    ('auto approve anyone asking to join my mac', 'DEVICES'),  # t9
    ('auto-approve whoever asks for my mac', 'DEVICES'),  # t13
    ('bring back approvals on my mac', 'DEVICES'),  # t3
    ('can anyone join my mac?', 'DEVICES'),  # in2
    ('check require approval for my mac', 'DEVICES'),  # t16
    ('did you turn off allow all for my mac?', 'DEVICES'),  # t8
    ('disable approval on my mac', 'DEVICES'),  # t2
    ('does anyone need approval to join my mac?', 'DEVICES'),  # in2
    ('does my mac allow all?', 'DEVICES'),  # in1
    ('does not need approval on my mac', 'DEVICES'),  # t13
    ('does the Studio PC let anyone join', 'DEVICES'),  # t1
    ("don't ever let anyone join my mac", 'DEVICES'),  # t7
    ("don't let people in to my mac anymore", 'DEVICES'),  # t4
    ("don't let strangers join my mac without asking", 'DEVICES'),  # t3
    ('enable require approval for my mac', 'DEVICES'),  # t16
    ('get rid of approvals on my mac', 'DEVICES'),  # t2
    ('give me the Studio PC, it lets anyone in', 'DEVICES'),  # t14
    ("hmm my mac won't let anyone join, can you check", 'DEVICES'),  # G2
    ('how many people joined my mac', 'DEVICES'),  # t7
    ("I can't let anyone join my mac", 'DEVICES'),  # G2
    ('I cannot let anyone join my mac from the web app', 'DEVICES'),  # t1
    ("I don't mind: let anyone join my mac", 'DEVICES'),  # G23
    ("I don't want allow all on my mac", 'DEVICES'),  # t7
    ("I don't want anyone joining my mac without asking", 'DEVICES'),  # t7
    ("I don't want strangers finding or joining my mac", 'DEVICES'),  # t15
    ('I heard the Studio PC lets anyone join', 'DEVICES'),  # t1
    ('I never let anyone join my mac', 'DEVICES'),  # t1
    ('I never want allow all on my mac', 'DEVICES'),  # t7
    ("I shouldn't have to approve everyone on my mac", 'DEVICES'),  # t2
    ('I tried to let anyone join my mac but nobody can get in', 'DEVICES'),  # t1
    ('I turned on allow all by mistake for my mac, turn it off', 'DEVICES'),  # G16
    ('I want allow all off on my mac', 'DEVICES'),  # t7
    ('I want approval back on my mac', 'DEVICES'),  # t3
    ('I want to approve each request on my mac', 'DEVICES'),  # t3
    ('I want to approve people before they join my mac', 'DEVICES'),  # t3
    ('I want “Studio PC” — it joins at once', 'DEVICES'),  # t14
    ("I'd rather not let anyone join my mac", 'DEVICES'),  # t7
    ("I'll approve people on my mac from now on", 'DEVICES'),  # G14
    ("I'll take the Studio PC, it joins at once", 'DEVICES'),  # G4
    ("I'm tired of approving people on my mac, let them in automatically", 'DEVICES'),  # t2
    ('is allow all on for my mac?', 'DEVICES'),  # G26
    ('is allow all on?', 'DEVICES'),  # G26
    ('is allow all safe', 'DEVICES'),  # t7
    ('is allow all still on?', 'DEVICES'),  # G26
    ('is my computer allow all?', 'DEVICES'),  # in2
    ('is my mac letting anyone join', 'DEVICES'),  # g2
    ('it says my mac no longer lets anyone join, why', 'DEVICES'),  # t8
    ('it says “Studio PC” no longer lets anyone join', 'DEVICES'),  # t8
    ("it still doesn't let anyone join my mac", 'DEVICES'),  # t1
    ("it won't let anyone join my mac", 'DEVICES'),  # G2
    ('join my mac without asking me', 'DEVICES'),  # G13
    ('join the call from my laptop', 'DEVICES'),  # t10
    ('keep allow all on for my mac so I stop getting requests', 'DEVICES'),  # F9
    ('keep allow all on the lab pc, but turn it off on my mac', 'DEVICES'),  # G16
    ('keep requiring approval on my mac', 'DEVICES'),  # t16
    ('kick everyone off my mac', 'DEVICES'),  # t7
    ('leave allow all on for my mac', 'DEVICES'),  # t7
    ('leave the lab pc alone and turn off allow all on my mac', 'DEVICES'),  # G5
    ("let anyone join my mac and don't ask me", 'DEVICES'),  # G23
    ('let anyone join my mac and never ask me again', 'DEVICES'),  # t7
    ('let anyone join my mac and stop the Mars run', 'DEVICES'),  # t11
    ('let anyone join my mac but not the lab pc', 'DEVICES'),  # t12
    ('let anyone join my mac without requiring my approval', 'DEVICES'),  # G11
    ('let anyone join my mac, no approval needed', 'DEVICES'),  # t2
    ('let anyone join my mac, no more approvals', 'DEVICES'),  # F9
    ('let anyone join my mac, stop requiring approval', 'DEVICES'),  # G11
    ('let folks in to my mac without my ok', 'DEVICES'),  # t2
    ('let me approve each person for my mac', 'DEVICES'),  # t3
    ('let me decide who joins my mac', 'DEVICES'),  # t3
    ('let people join my mac without asking me', 'DEVICES'),  # in2
    ('let strangers use my computer', 'DEVICES'),  # in1
    ('let whoever asks join my mac', 'DEVICES'),  # t13
    ('let whoever asks use my mac', 'DEVICES'),  # t13
    ('list my mac publicly but require approval', 'DEVICES'),  # F7
    ('make my mac an open computer', 'DEVICES'),  # t13
    ('make my mac ask me first', 'DEVICES'),  # t3
    ('make my mac auto-approve requests', 'DEVICES'),  # t2
    ('make my mac free for anyone to join', 'DEVICES'),  # t13
    ('make my mac open to anyone', 'DEVICES'),  # in1
    ('make my mac open to everyone', 'DEVICES'),  # t13
    ('make my mac public but make people ask', 'DEVICES'),  # F7
    ('make my mac public but require my approval', 'DEVICES'),  # F7
    ('my friend asked to join my mac', 'DEVICES'),  # G13
    ("my friend says the Studio PC won't let anyone join", 'DEVICES'),  # G2
    ('my mac does not let anyone join even though I turned it on', 'DEVICES'),  # t1
    ("my mac doesn't let anyone join anymore, why", 'DEVICES'),  # G2
    ("my mac doesn't let anyone join anymore?", 'DEVICES'),  # t8
    ("my mac isn't letting anyone join", 'DEVICES'),  # G2
    ('my mac no longer lets anyone join?', 'DEVICES'),  # t8
    ('my mac should ask me first', 'DEVICES'),  # t3
    ("my mac still won't let anyone in", 'DEVICES'),  # t1
    ('my mac stopped letting anyone join', 'DEVICES'),  # t8
    ('my mac stopped letting anyone join, can you fix it', 'DEVICES'),  # G2
    ("my mac won't let anyone join", 'DEVICES'),  # t1
    ("my mac won't let anyone join?", 'DEVICES'),  # G2
    ('never let anyone join my mac', 'DEVICES'),  # t7
    ('no allow all on my mac please', 'DEVICES'),  # t7
    ('no approval, no asking, just let anyone join my mac', 'DEVICES'),  # t2
    ('no let anyone join my mac', 'DEVICES'),  # t2
    ('no longer let anyone join or find my mac', 'DEVICES'),  # G3
    ('no one should join my mac without asking me', 'DEVICES'),  # t3
    ('nobody can join my mac without asking me', 'DEVICES'),  # G13
    ('nobody can join my mac, help', 'DEVICES'),  # g2
    ('nobody joins my mac without my approval', 'DEVICES'),  # G6
    ('nobody should join my mac without asking me first', 'DEVICES'),  # t9
    ('nobody should need my approval on my mac', 'DEVICES'),  # t2
    ('now that the lab pc is set up, turn off allow all on my mac', 'DEVICES'),  # t12
    ('ok the Studio PC then, anyone can join it', 'DEVICES'),  # t14
    ('open my computer to everyone', 'DEVICES'),  # in1
    ('open my mac to everyone', 'DEVICES'),  # t13
    ('open up my mac to anyone', 'DEVICES'),  # t13
    ("people say my mac won't let anyone join", 'DEVICES'),  # t1
    ("people shouldn't need my approval to join my mac", 'DEVICES'),  # t2
    ('publish my mac but ask me first', 'DEVICES'),  # F7
    ('put my mac back on approval', 'DEVICES'),  # t3
    ('put my mac back to asking me first', 'DEVICES'),  # t3
    ('reinstate approval for my mac', 'DEVICES'),  # t3
    ('remove the need for approval on my mac', 'DEVICES'),  # t2
    ('remove the people who joined my mac through allow all', 'DEVICES'),  # G6
    ('restore approvals on my mac', 'DEVICES'),  # t3
    ('revert my mac to asking me first', 'DEVICES'),  # t3
    ('run it on my mac with all agents allowed', 'DEVICES'),  # t10
    ('set my mac to require approval', 'DEVICES'),  # t3
    ('set my mac to require my approval again', 'DEVICES'),  # t16
    ('should I turn on allow all for my mac', 'DEVICES'),  # t7
    ('show me the approvals for my mac', 'DEVICES'),  # G18
    ('so allow all is off on my mac?', 'DEVICES'),  # t8
    ('so my mac no longer lets anyone join?', 'DEVICES'),  # t8
    ('so nobody can join my mac without asking now?', 'DEVICES'),  # G13
    ('start asking me first on my mac', 'DEVICES'),  # t16
    ('stop letting anyone join my mac — the lab pc is fine as is', 'DEVICES'),  # t12
    ('stop needing my approval on my mac', 'DEVICES'),  # t2
    ('stop the Mars run and turn off allow all on my mac', 'DEVICES'),  # t11
    ('switch allow all for my mac', 'DEVICES'),  # t3
    ('switch my mac back to approval mode', 'DEVICES'),  # t3
    ('switch on requiring approval for my mac', 'DEVICES'),  # t16
    ('switch to the office pc and allow all', 'DEVICES'),  # G20
    ('tell me about allow all', 'DEVICES'),  # t7
    ('the allow all setting on my mac, switch it off', 'DEVICES'),  # G16
    ("the app didn't let anyone join my mac", 'DEVICES'),  # t1
    ('the lab pc can stay open, but turn off allow all on my mac', 'DEVICES'),  # G5
    ('the Studio PC lets anyone join', 'DEVICES'),  # t1
    ('the Studio PC no longer lets anyone join?', 'DEVICES'),  # G2
    ('the Studio PC please — anyone can join it', 'DEVICES'),  # t14
    ('the web app says allow all is off for my mac but I turned it on', 'DEVICES'),  # t8
    ('tick require approval on my mac', 'DEVICES'),  # t16
    ('toggle allow all for my mac', 'DEVICES'),  # t3
    ('turn off allow all and sharing on “Studio Mac”', 'DEVICES'),  # G3
    ('turn off allow all and sharing on “Studio PC”', 'DEVICES'),  # t5
    ('turn off allow all and switch to the office pc', 'DEVICES'),  # G5
    ('turn off allow all and unlink my old laptop', 'DEVICES'),  # t11
    ('turn off allow all on my mac and deny Sam', 'DEVICES'),  # t11
    ('turn off allow all on my mac and leave the lab pc open', 'DEVICES'),  # t12
    ('turn off allow all on my mac and remove Sam', 'DEVICES'),  # t11
    ('turn off allow all on my mac and stop the Mars run', 'DEVICES'),  # t11
    ('turn off allow all on my mac and switch to the office pc', 'DEVICES'),  # t11
    ('turn off allow all on my mac but not on the lab pc', 'DEVICES'),  # t12
    ('turn off allow all on my mac, not the lab pc', 'DEVICES'),  # t12
    ('turn off allow all on my mac, the one next to the office pc', 'DEVICES'),  # t12
    ("turn on allow all for my mac and don't require approval", 'DEVICES'),  # G11
    ('turn on allow all for my mac, not the lab pc', 'DEVICES'),  # t12
    ('turn on allow all for my mac, stop asking me', 'DEVICES'),  # F9
    ('turn on require approval for my mac', 'DEVICES'),  # t16
    ('use all agents on my mac and allow all', 'DEVICES'),  # t10
    ('wait so the Studio PC no longer lets anyone join?', 'DEVICES'),  # t8
    ('wait, you switched off allow all on my mac?', 'DEVICES'),  # t8
    ('what does allow all do', 'DEVICES'),  # t7
    ('what does allow all do?', 'DEVICES'),  # G26
    ('what happens if I turn on allow all', 'DEVICES'),  # t7
    ('what is allow all', 'DEVICES'),  # t7
    ("what's the allow all setting on my mac?", 'DEVICES'),  # in2
    ('which of my computers let anyone join?', 'DEVICES'),  # in1
    ('who can join my computer?', 'DEVICES'),  # in2
    ('who can join my mac', 'DEVICES'),  # t7
    ('who joined my mac', 'DEVICES'),  # t7
    ('who joined my mac since I turned on allow all', 'DEVICES'),  # t7
    ('why does it say my mac no longer lets anyone join', 'DEVICES'),  # t8
    ('why does my mac not let anyone join', 'DEVICES'),  # g2
    ("why won't my mac let anyone join", 'DEVICES'),  # g2
    ('you did not let anyone join my mac', 'DEVICES'),  # G2
    ("you didn't turn off allow all on my mac?", 'DEVICES'),  # t8
    ('you turned allow all off for my mac?', 'DEVICES'),  # t8
    ('“Studio PC” joins at once, I want that one', 'DEVICES'),  # t14
    ('“Studio PC” · joins at once', 'DEVICES'),  # t14
    ('✓ “Studio PC” no longer lets anyone join — you approve each person again.', 'DEVICES'),  # t8
    ('disable allow all and public listing on my mac', 'HIDE'),  # G3
    ('disable allow all and sharing for my mac', 'HIDE'),  # G3
    ('hide my computer', 'HIDE'),  # in1
    ('hide my mac and stop auto approving', 'HIDE'),  # t4
    ('hide my mac and stop letting anyone join', 'HIDE'),  # in2
    ('hide my mac, no more letting anyone join', 'HIDE'),  # t4
    ('make it private and stop letting anyone join', 'HIDE'),  # t4
    ('make it private and turn off allow all', 'HIDE'),  # F7
    ('make my computer private', 'HIDE'),  # in1
    ('make my mac private', 'HIDE'),  # in2
    ('make my mac private and no allow all', 'HIDE'),  # t4
    ('make my mac private — and allow all off', 'HIDE'),  # t4
    ('make my mac private, no allow all', 'HIDE'),  # t4
    ('my mac should not be public, and turn off allow all', 'HIDE'),  # F7
    ('no longer share my mac and stop allowing anyone to join', 'HIDE'),  # F7
    ('remove my mac from the public list and turn off allow all', 'HIDE'),  # F7
    ('stop letting anyone join or see my mac', 'HIDE'),  # G3
    ('stop letting anyone join or use my mac', 'HIDE'),  # g3
    ('stop offering my mac and turn allow all off', 'HIDE'),  # F7
    ('stop sharing and letting anyone join my mac', 'HIDE'),  # t4
    ('stop sharing my mac and turn off allow all', 'HIDE'),  # F7
    ('switch off allow all and sharing for my mac', 'HIDE'),  # G3
    ('switch off allow all and unlist my mac', 'HIDE'),  # t4
    ('take my mac off the public list and disable allow all', 'HIDE'),  # F7
    ('take my mac off the public list and turn off allow all', 'HIDE'),  # F7
    ('take my mac off the public list, stop letting anyone join', 'HIDE'),  # t4
    ('take my mac private and stop letting anyone join', 'HIDE'),  # t4
    ('turn off allow all and hide my mac', 'HIDE'),  # G3
    ('turn off allow all and make my mac private', 'HIDE'),  # g3
    ('turn off allow all and public for my mac', 'HIDE'),  # g3
    ('turn off allow all and public sharing for my mac', 'HIDE'),  # t5
    ('turn off allow all and sharing on my mac', 'HIDE'),  # G3
    ('turn off allow all and the public listing for my mac', 'HIDE'),  # g3
    ('turn off allow all and turn off public for my mac', 'HIDE'),  # t4
    ('turn off allow all, and hide my mac', 'HIDE'),  # t4
    ('turn off allow all, then hide my mac', 'HIDE'),  # t4
    ('turn off auto-accept and public sharing on my mac', 'HIDE'),  # G3
    ('turn off both allow all and sharing on my mac', 'HIDE'),  # t5
    ('turn off public and allow all for my mac', 'HIDE'),  # t4
    ('turn off sharing and allow all for my mac', 'HIDE'),  # t4
    ('turn off sharing and allow all on my mac', 'HIDE'),  # G3
    ('turn off sharing on my mac', 'HIDE'),  # g3
    ('turn off sharing on my mac and turn off allow all', 'HIDE'),  # F7
    ('undo making my mac public and turn off allow all', 'HIDE'),  # F7
    ('unshare my mac and turn off auto join', 'HIDE'),  # t4
    ('join any computer', 'LINE:I ask one owner at a time. Show me the public computers and '),  # t10
    ('help', 'LINE:I can research a topic, check a run’s status, fetch its podc'),  # G25
    ('what can you do', 'LINE:I can research a topic, check a run’s status, fetch its podc'),  # G25
    ('what can you do?', 'LINE:I can research a topic, check a run’s status, fetch its podc'),  # G25
    ('turn off everything public on my mac including allow all', 'LINE:I hide one computer at a time. Ask me to list them and name '),  # G6
    ('approve everyone waiting', 'LINE:I say yes to one person at a time. Ask me who is waiting and'),  # t10
    ('let them all in', 'LINE:I say yes to one person at a time. Ask me who is waiting and'),  # t10
    ('people keep asking to join my mac, let them all in', 'LINE:I say yes to one person at a time. Ask me who is waiting and'),  # t9
    ('remove everyone who joined my mac', 'LINE:I unlink one computer at a time. Ask me to list them and nam'),  # t7
    ('authenticate me and join the Studio PC', 'LOGIN'),  # t6
    ('I need to sign in to join the Studio PC', 'LOGIN'),  # t6
    ('I want to sign in and join the Studio PC', 'LOGIN'),  # t6
    ('join the Studio PC after I sign in', 'LOGIN'),  # t6
    ('join the Studio PC so I can sign in', 'LOGIN'),  # t6
    ('let me log in and join the Studio PC', 'LOGIN'),  # t6
    ('log in then join K7XQ-9B2M', 'LOGIN'),  # t6
    ('log in to join the Studio PC', 'LOGIN'),  # F21
    ('log me in to join the Studio PC', 'LOGIN'),  # t6
    ('login and join the Studio PC', 'LOGIN'),  # t6
    ('sign in and ask to join the Studio PC', 'LOGIN'),  # G13
    ('sign in and join the Studio PC', 'LOGIN'),  # F21
    ('sign in first then join the Studio PC', 'LOGIN'),  # t6
    ('sign in so I can ask to join the Studio PC', 'LOGIN'),  # t9
    ('sign in so I can join the Studio PC', 'LOGIN'),  # t6
    ('sign in to join the Studio PC', 'LOGIN'),  # F21
    ('sign me in and join Studio PC', 'LOGIN'),  # t6
    ('allow all false for my mac', 'OFF'),  # F19
    ('allow all no for my mac', 'OFF'),  # F19
    ('allow all off', 'OFF'),  # in1
    ('allow all off for my mac please', 'OFF'),  # t7
    ('Approve people from now on', 'OFF'),  # G14
    ('clear allow all for my mac', 'OFF'),  # F19
    ('disable allow all', 'OFF'),  # in1
    ('do not let anyone join my mac', 'OFF'),  # t13
    ("don't let anyone join my mac", 'OFF'),  # g2
    ('drop allow all on my mac', 'OFF'),  # F19
    ('end allow all on my mac', 'OFF'),  # F19
    ('get rid of allow all on my mac', 'OFF'),  # F19
    ('go back to approving people on my mac', 'OFF'),  # G14
    ('i want to approve people again', 'OFF'),  # in1
    ('I want to approve people on my mac again', 'OFF'),  # F14
    ("I'd like to approve people on my mac from now on", 'OFF'),  # G14
    ('kill allow all on my mac', 'OFF'),  # F19
    ('make people ask again', 'OFF'),  # in1
    ('pause allow all on my mac', 'OFF'),  # F19
    ("please don't let strangers join my mac", 'OFF'),  # t7
    ('remove allow all from my mac', 'OFF'),  # F19
    ('remove auto-approve from my mac', 'OFF'),  # F19
    ('require approval', 'OFF'),  # G11
    ('require approval again', 'OFF'),  # in1
    ('reverse allow all on my mac', 'OFF'),  # t3
    ('revert allow all on my mac', 'OFF'),  # t3
    ('roll back allow all on my mac', 'OFF'),  # t3
    ('set allow all back to off for my mac', 'OFF'),  # G6
    ('set allow all to no for my mac', 'OFF'),  # F19
    ('start requiring approval on my mac', 'OFF'),  # G11
    ('start requiring my approval again on my mac', 'OFF'),  # t16
    ('stop allowing anyone to join my mac', 'OFF'),  # t15
    ('stop letting anyone in to my mac', 'OFF'),  # t4
    ('stop letting anyone join', 'OFF'),  # in1
    ('stop letting anyone join my mac', 'OFF'),  # g2
    ('stop letting others in to my mac', 'OFF'),  # t4
    ('stop letting people join my mac', 'OFF'),  # in1
    ('stop letting strangers onto my mac', 'OFF'),  # t4
    ('switch allow all back off on my mac', 'OFF'),  # G6
    ('take off allow all from my mac', 'OFF'),  # G6
    ('turn allow all back off', 'OFF'),  # t3
    ('turn allow all back off for my mac', 'OFF'),  # G6
    ('turn allow all off', 'OFF'),  # F19
    ('turn allow all off for my mac', 'OFF'),  # g456
    ('turn off allow all', 'OFF'),  # in1
    ('turn off allow all for my mac', 'OFF'),  # t0
    ('turn off allow all on my mac', 'OFF'),  # g2
    ('turn the allow all option off for my mac', 'OFF'),  # t3
    ('uncheck allow all', 'OFF'),  # F19
    ('uncheck allow all for my mac', 'OFF'),  # F19
    ('undo auto approve on my mac', 'OFF'),  # t3
    ('untick allow all for my mac', 'OFF'),  # F19
    ('stop letting anyone join “Studio Mac”', 'OFF:Studio Mac'),  # F20
    ('stop allowing people to join the Studio PC', 'OFF:Studio PC'),  # t15
    ('accept everyone automatically', 'ON'),  # t10
    ('allow anyone to join my computer', 'ON'),  # in1
    ('allow anyone to use my mac without asking', 'ON'),  # t13
    ('approve everyone automatically on my mac', 'ON'),  # in2
    ('auto approve requests for my mac', 'ON'),  # in1
    ('auto-accept people on my computer', 'ON'),  # in1
    ('auto-approve requests for my mac so I stop getting pinged', 'ON'),  # F9
    ('check allow all', 'ON'),  # G26
    ("don't require approval on my mac", 'ON'),  # G11
    ('enable allow all', 'ON'),  # in1
    ("enable auto-approve for my mac so I don't have to keep approving", 'ON'),  # F9
    ('let anyone join', 'ON'),  # G2
    ('let anyone join my computer', 'ON'),  # in1
    ('let anyone join my mac', 'ON'),  # in1
    ('let anyone join my mac without approval', 'ON'),  # t2
    ('let anyone join my mac without my approval', 'ON'),  # in2
    ('let everybody in', 'ON'),  # t10
    ('let everyone join my computer at once', 'ON'),  # in1
    ('make it public and allow all', 'ON'),  # F12
    ('make my computer public and allow all', 'ON'),  # in1
    ('make my mac public and let anyone join', 'ON'),  # in2
    ('make my mac public with allow all', 'ON'),  # in1
    ('no longer require approval on my mac', 'ON'),  # t2
    ('no more approvals for my mac', 'ON'),  # in2
    ('no more approvals on my mac', 'ON'),  # t2
    ('publish my mac and allow all', 'ON'),  # in2
    ('put my mac on auto-accept', 'ON'),  # t2
    ('set my computer to allow all', 'ON'),  # in1
    ('set my mac to auto approve', 'ON'),  # t2
    ('stop requiring approval for my mac', 'ON'),  # t2
    ('stop requiring approval on my mac', 'ON'),  # G11
    ('switch my mac to auto-approve', 'ON'),  # t2
    ('switch on allow all for my laptop', 'ON'),  # in1
    ('tick allow all', 'ON'),  # in1
    ('turn allow all on', 'ON'),  # in1
    ('turn allow all on for my mac so i stop getting requests', 'ON'),  # in2
    ('turn off approval for my mac', 'ON'),  # F13
    ('turn off approvals on my mac', 'ON'),  # t2
    ('turn on allow all', 'ON'),  # in1
    ('turn on allow all for my mac', 'ON'),  # t0
    ('turn on allow all for my mac so I never have to approve anyone', 'ON'),  # F9
    ("turn on allow all so I don't have to approve people on my mac", 'ON'),  # F9
    ('turn on allow all so I stop getting requests for my mac', 'ON'),  # F9
    ('let anyone join “Studio Mac”', 'ON:Studio Mac'),  # F20
    ('are there any computers that let anyone join?', 'PUBLIC'),  # in2
    ('are there any public computers?', 'PUBLIC'),  # F8
    ('ask for the one that joins at once', 'PUBLIC'),  # t14
    ('ask to use a public computer that lets anyone join', 'PUBLIC'),  # F8
    ('ask to use one of them', 'PUBLIC'),  # G22
    ('find a computer that lets anyone join', 'PUBLIC'),  # F8
    ('find me a public computer that lets anyone join', 'PUBLIC'),  # F8
    ('find my team a computer that lets anyone join', 'PUBLIC'),  # t1
    ('find the shared computer where anyone can join', 'PUBLIC'),  # G17
    ('for my research I need a computer that lets anyone join', 'PUBLIC'),  # t1
    ('I want my mac to use a public computer that lets anyone join', 'PUBLIC'),  # t1
    ('i want to join a public computer', 'PUBLIC'),  # in2
    ('is there a computer that lets anyone join', 'PUBLIC'),  # g456
    ('join a computer that lets anyone in', 'PUBLIC'),  # in2
    ('join a public computer that lets anyone in', 'PUBLIC'),  # F8
    ('join one of the public computers', 'PUBLIC'),  # F15
    ('join the one that joins at once', 'PUBLIC'),  # t14
    ('join the public computer', 'PUBLIC'),  # t10
    ('list computers that let anyone join', 'PUBLIC'),  # G4
    ('list public computers that let anyone join', 'PUBLIC'),  # F8
    ('list public computers with allow all', 'PUBLIC'),  # F8
    ('list the public macs where anyone can join', 'PUBLIC'),  # F8
    ('my computer is broken, which computers let anyone join', 'PUBLIC'),  # G4
    ("my laptop can't run research, find one that lets anyone join", 'PUBLIC'),  # t1
    ('my laptop is too slow, show me machines that let anyone join', 'PUBLIC'),  # t1
    ('my mac died so I need a public computer that lets anyone join', 'PUBLIC'),  # t1
    ('my mac is off, is there a computer that lets anyone join', 'PUBLIC'),  # G4
    ('my mac is offline — any public computer that lets anyone join?', 'PUBLIC'),  # t1
    ('pick one of them that lets anyone join', 'PUBLIC'),  # G18
    ('run my research on a computer that lets anyone join', 'PUBLIC'),  # G4
    ('show me computers i can join at once', 'PUBLIC'),  # in2
    ('show me computers that let anyone join, mine is offline', 'PUBLIC'),  # t1
    ('show me machines that auto-approve', 'PUBLIC'),  # F8
    ('show me public computers', 'PUBLIC'),  # in1
    ('show me public computers that let anyone join', 'PUBLIC'),  # F8
    ('show me the public computer that lets anyone join', 'PUBLIC'),  # G17
    ('show public computers anyone can join', 'PUBLIC'),  # F8
    ('show public computers that auto accept', 'PUBLIC'),  # F8
    ('since my mac is offline, list computers that let anyone join', 'PUBLIC'),  # G4
    ('switch from my mac to a computer that lets anyone join', 'PUBLIC'),  # G4
    ('the DG shared computer lets anyone in, can I use it', 'PUBLIC'),  # t1
    ('the one that joins at once', 'PUBLIC'),  # t14
    ('the Studio PC one that joins at once', 'PUBLIC'),  # t14
    ('use a computer that lets anyone join instead of my mac', 'PUBLIC'),  # G4
    ('use the one that joins at once', 'PUBLIC'),  # t14
    ('which computers can i join right away?', 'PUBLIC'),  # in2
    ('which public computers let anyone join', 'PUBLIC'),  # F11
    ('which public computers let anyone join?', 'PUBLIC'),  # in1
    ('and public for my mac', 'PUBLISH'),  # t5
    ('and public listing on my mac', 'PUBLISH'),  # t5
    ('and public sharing on my mac', 'PUBLISH'),  # t5
    ('and sharing for my mac', 'PUBLISH'),  # t5
    ('and sharing on my mac', 'PUBLISH'),  # t5
    ('make my computer public', 'PUBLISH'),  # G28
    ('make my mac public', 'PUBLISH'),  # G28
    ('stop the join the dots run', 'STOP:join the dots'),  # t10
    ("stop the why people won't join the gym run", "STOP:why people won't join the gym"),  # t10
]


@pytest.mark.parametrize("text, want", PINNED)
def test_every_finding_phrasing_takes_its_route_under_the_whole_message_policy(text, want):
    assert _route(text) == want


# ── 2. what no message but a whole command may ever be ───────────────────────────

_NEVER_A_SWITCH = [
    # fault reports (G2) — every one of these switched Allow all OFF, unconfirmed
    "my mac stopped letting anyone join, can you fix it", "it won't let anyone join my mac",
    "my mac won't let anyone join?", "hmm my mac won't let anyone join, can you check",
    "I can't let anyone join my mac", "you did not let anyone join my mac",
    "my friend says the Studio PC won't let anyone join", "the Studio PC no longer lets anyone join?",
    "my mac isn't letting anyone join", "my mac doesn't let anyone join anymore, why",
    "my mac still won't let anyone in", "people say my mac won't let anyone join",
    "I tried to let anyone join my mac but nobody can get in",
    "allow all for my mac no matter who asks",
    # questions and statements of state
    "is allow all on?", "is allow all on for my mac?", "turn off allow all?",
    "did you turn off allow all for my mac?", "you turned allow all off for my mac?",
    "allow all off on my mac?", "so allow all is off on my mac?",
    "✓ “Studio PC” no longer lets anyone join — you approve each person again.",
    "✓ “Studio PC” now lets anyone join at once.",
    "Anyone signed in can join “Studio PC” at once",
    "allow all is on for my mac", "why is my mac private if allow all is on",
    # joiners (G4) — each raised the confirm that opens the joiner's OWN computer
    "since my mac is offline, list computers that let anyone join",
    "my mac is off, is there a computer that lets anyone join",
    "switch from my mac to a computer that lets anyone join",
    "run my research on a computer that lets anyone join",
    "find my team a computer that lets anyone join", "I'll take the Studio PC, it joins at once",
    "give me the Studio PC, it lets anyone in", "the Studio PC please — anyone can join it",
    "list public computers that let anyone join", "join the studio pc that lets anyone in",
    # two computers (G5)
    "leave the lab pc alone and turn off allow all on my mac",
    "the lab pc can stay open, but turn off allow all on my mac",
    "now that the lab pc is set up, turn off allow all on my mac",
    "turn off allow all on my mac but not on the lab pc",
    "turn on allow all for my mac, not the lab pc",
    "turn off allow all on my mac since the lab pc is set up",
    # two commands (G15)
    "turn off allow all on my mac and stop the Mars run",
    "stop the Mars run and turn off allow all", "turn off allow all and switch to the office pc",
    "turn off allow all and sign out", "let anyone join my mac and stop the Mars run",
    "turn on allow all for my mac and turn off auto approve",
    # the pronoun that lost its referent (G16)
    "allow all on my mac, turn it off", "the allow all setting on my mac, switch it off",
    "I turned on allow all by mistake for my mac, turn it off",
]


@pytest.mark.parametrize("text", _NEVER_A_SWITCH)
def test_nothing_but_a_whole_command_switches_allow_all_or_asks_to(text):
    """⛔⛔ THE REVERSE MUST-NOT. A problem report, a question, a statement, a
    joiner's message, two computers or a second clause is never a write and never
    a switch confirm — and never the HIDE a bare `turn it off` used to run."""
    route = _route(text)
    assert not route.startswith(("OFF", "ON")), (text, route)
    if "turn it off" in text or "switch it off" in text:
        assert not route.startswith("HIDE"), (text, route)


_COMMANDS = ["turn off allow all", "turn on allow all", "let anyone join my mac",
             "stop letting anyone join my mac", "require approval again",
             "disable allow all", "auto-approve requests", "uncheck allow all",
             "turn allow all back off", "set allow all to no"]
_WRAPPED = ["{} and stop the Mars run", "{} and switch to the office pc", "{}, and sign me out",
            "why did you {}?", "did you {}?", "{}?", "my friend said {}",
            "I asked you to {} yesterday", "{} on the lab pc and my mac",
            "{} for my mac since the lab pc is set up", "first {} then hide the Studio PC"]


@pytest.mark.parametrize("wrap", _WRAPPED)
@pytest.mark.parametrize("cmd", _COMMANDS)
def test_a_command_inside_a_longer_message_is_not_the_command(cmd, wrap):
    """⭐ The whole-message rule, generated: each command works said alone, and
    none of them switches anything once it is one clause of a longer message."""
    assert _route(cmd).startswith(("OFF", "ON")), cmd
    text = wrap.format(cmd)
    assert not _route(text).startswith(("OFF", "ON")), (text, _route(text))


# ── 3. the grammar, family by family — each row is the only thing some family reads

@pytest.mark.parametrize("text, want", [
    # ON
    ("turn on allow all for my mac", "ON"), ("switch on allow all on the Office PC", "ON:Office PC"),
    ("turn allow all on", "ON"), ("turn allow all back on for my mac", "ON"),
    ("turn allow all for my mac on", "ON"), ("allow all on", "ON"), ("allow all yes for my mac", "ON"),
    ("allow all: on", "ON"), ("set allow all to yes", "ON"), ("enable allow all", "ON"),
    ("tick allow all for my mac", "ON"), ("check allow all", "ON"),
    ("set my mac to allow all", "ON"), ("switch my mac to auto-approve", "ON"),
    ("let anyone join my mac", "ON"), ("let anyone join “Studio PC”", "ON:Studio PC"),
    ("let anyone use my computer", "ON"), ("let anyone join", "ON"),
    ("let everyone in", "ON"), ("let anyone in to my mac", "ON"),
    ("allow everyone to join my computer", "ON"), ("auto-approve requests for my mac", "ON"),
    ("auto approve", "ON"), ("approve everyone automatically", "ON"),
    ("automatically approve everyone", "ON"), ("turn off approval for my mac", "ON"),
    ("turn approvals off", "ON"), ("no approval needed", "ON"), ("no more approvals", "ON"),
    ("stop requiring approval on my mac", "ON"), ("don't require approval on my mac", "ON"),
    ("make my mac public and allow all", "ON"), ("make it public with allow all", "ON"),
    ("make my mac public and let anyone join", "ON"), ("publish my mac with allow all", "ON"),
    # OFF
    ("turn off allow all for my mac", "OFF"), ("switch off allow all on the Office PC", "OFF:Office PC"),
    ("turn allow all off", "OFF"), ("turn allow all back off for my mac", "OFF"),
    ("turn allow all on my mac off", "OFF"), ("allow all off", "OFF"), ("allow all no for my mac", "OFF"),
    ("allow all: off", "OFF"), ("allow all false", "OFF"), ("set allow all back to off for my mac", "OFF"),
    ("disable allow all on my mac", "OFF"), ("uncheck allow all", "OFF"), ("untick allow all", "OFF"),
    ("remove allow all from my mac", "OFF"), ("take off allow all from my mac", "OFF"),
    ("revert allow all on my mac", "OFF"), ("roll back allow all on my mac", "OFF"),
    ("get rid of allow all on my mac", "OFF"), ("switch off auto join for my mac", "OFF"),
    ("stop letting anyone join my mac", "OFF"), ("don't let anyone join my mac", "OFF"),
    ("stop letting anyone join “Studio Mac”", "OFF:Studio Mac"),
    ("stop letting strangers onto my mac", "OFF"), ("stop allowing anyone to join my mac", "OFF"),
    ("require approval again", "OFF"), ("require my approval on my mac", "OFF"),
    ("start requiring approval on my mac", "OFF"), ("turn on approval for my mac", "OFF"),
    ("turn approval back on for my mac", "OFF"), ("go back to approving people on my mac", "OFF"),
    ("approve people on my mac again", "OFF"), ("approve everyone myself on my mac", "OFF"),
    ("make everyone ask before joining my mac", "OFF"), ("make people ask again", "OFF"),
])
def test_each_grammar_family_is_one_whole_command(text, want):
    assert _route(text) == want


@pytest.mark.parametrize("text, want", [
    ("please turn off allow all for my mac", "OFF"), ("hey, turn off allow all", "OFF"),
    ("ok turn on allow all", "ON"), ("could you please turn on allow all for my mac", "ON"),
    ("I want to turn off allow all", "OFF"), ("I'd like to turn on allow all", "ON"),
    ("turn off allow all for my mac please", "OFF"), ("turn off allow all, thanks", "OFF"),
    ("Turn Off Allow All.", "OFF"), ("turn off allow all now!", "OFF"),
    ("turn off allow all 🙏", "OFF"), ("turn on allow all please 👍", "ON"),
])
def test_politeness_thanks_and_emoji_do_not_change_a_command(text, want):
    assert _route(text) == want


def test_a_question_mark_is_a_question_unless_the_person_asked_us_to_act():
    """⛔ `my mac won't let anyone join?` switched Allow all OFF: the `?` was
    stripped before anything read it. A trailing `?` is a question — unless the
    message opens `can/could/would/will you`, which is how people ask for things."""
    assert _route("turn off allow all on my mac?") == "DEVICES"
    assert _route("can you turn off allow all on my mac?") == "OFF"
    assert _route("could you let anyone join my mac?") == "ON"
    assert _route("can I turn off allow all?") == "DEVICES"


@pytest.mark.parametrize("text, want", [
    ("turn off allow all for my mac so strangers stop joining", "OFF"),
    ("turn off allow all for my mac, because too many people joined", "OFF"),
    ("turn on allow all since I'm away all week", "ON"),
    ("turn on allow all so I stop getting requests for my mac", "ON"),
])
def test_one_purpose_clause_never_changes_the_command_or_its_direction(text, want):
    assert _route(text) == want


@pytest.mark.parametrize("text", [
    "turn off allow all on my mac since the lab pc is set up",
    "turn on allow all for “Studio PC” so “Lab PC” can stay private",
])
def test_a_purpose_clause_that_names_another_computer_makes_two(text):
    """⛔ ONE COMPUTER. With the subject in the command AND another in the reason,
    which one is meant is a guess — the round-2 G5 defect switched the LAB PC."""
    assert _route(text) == "DEVICES"


@pytest.mark.parametrize("text", ["let anyone join all my computers",
                                  "turn off allow all on all my macs",
                                  "disable allow all for every computer"])
def test_a_set_of_computers_is_one_at_a_time(text):
    assert _route(text) == "SET"


def test_the_name_after_the_needs_a_machine_word_and_keeps_its_capitals():
    """⛔ `stop letting anyone join the call` would switch Allow all off on a
    computer called “call”; and a name is passed as the person wrote it."""
    assert not _route("stop letting anyone join the call").startswith("OFF")
    assert _route("turn off allow all on the Lab PC") == "OFF:Lab PC"
    assert _route("turn off allow all for my mac") == "OFF"          # bare noun: picker


# ── 4. a hide first, others' computers second, and a read-only answer for the rest ─

@pytest.mark.parametrize("text", [
    "turn off allow all and sharing on my mac", "disable allow all and public listing on my mac",
    "turn off auto-accept and public sharing on my mac", "turn off allow all and hide my mac",
    "take my mac off the public list and turn off allow all", "make my mac private and turn off allow all",
    "stop letting anyone join or see my mac", "stop letting anyone join or use my mac",
    "can you make my mac private and turn off allow all",      # a polite imperative
])
def test_a_hide_in_the_visibility_clauses_words_is_that_hide_by_the_picker(text):
    """⭐ G3: the base revision hid these, and repair 1 raised the PUBLISH confirm
    or dropped the hide. The allow-all words welded onto the name (“allow all and
    make my mac”, “anyone join or see my mac”) made the hide REFUSE — so the name
    goes to the picker, which takes the one computer this account owns."""
    assert _route(text) == "HIDE"


@pytest.mark.parametrize("text", [
    "allow all on my mac, turn it off", "turn off allow all but keep my mac public",
    "why is my mac private if allow all is on", "since my mac is private, list computers that let anyone join",
    "my mac is hidden and allow all is off",
])
def test_no_hide_without_hide_words_over_keep_public_or_on_a_question_or_statement(text):
    assert not _route(text).startswith("HIDE"), (text, _route(text))


@pytest.mark.parametrize("text", [
    "list computers that let anyone join", "which public computers let anyone join",
    "is there anything that lets anyone join", "pick one of them that lets anyone join",
    "the one that joins at once on the lab pc", "show me machines that auto-approve",
    "show me the public computer that lets anyone join", "find the shared computer where anyone can join",
    "I want to borrow a machine that lets anyone join",
    "can I borrow the studio pc, it lets anyone in",          # the joiner's own verb
    "let anyone join the public computer",                    # not the owner's subject
])
def test_other_peoples_computers_are_the_browse_list(text):
    assert _route(text) == "PUBLIC"


@pytest.mark.parametrize("text", [
    "which of my computers let anyone join?", "does my mac let anyone join?",
    "so friends can join my mac, is allow all on",
    "don't join the studio pc that lets anyone in",
])
def test_the_persons_own_computers_are_never_the_browse_list(text):
    assert _route(text) == "DEVICES"


@pytest.mark.parametrize("text, want", [
    ("join the studio pc that lets anyone in", "ASK:studio pc"),
    ("join the Studio PC, it lets anyone in", "ASK:Studio PC"),
    ("join the Studio PC which lets anyone in", "ASK:Studio PC"),
    ("join the mac mini that lets anyone in", "ASK:mac mini"),
    ("join “DG shared”, it lets anyone in", "ASK:DG shared"),
    ("join K7XQ-9B2M, it lets anyone in", "ADD:K7XQ-9B2M"),
    ("join a public computer that lets anyone in", "PUBLIC"),
    ("join the computer that lets anyone in", "PUBLIC"),
    ("join my mac, it lets anyone in", "DEVICES"),
    ("sign in and join the studio pc that lets anyone in", "LOGIN"),
])
def test_a_whole_message_join_names_one_computer_and_nothing_else(text, want):
    """⛔ G29: `join the studio pc that lets anyone in` asked the owner of “studio pc
    that”, a name no row carries — the yes then failed."""
    assert _route(text) == want


@pytest.mark.parametrize("text, want", [
    ("my mac won't let anyone join", "DEVICES"),              # own computer
    ("anyone can join “Studio PC” now", "DEVICES"),           # a quoted name
    ("keep it public and let anyone join", "DEVICES"),        # a pronoun target
    ("the office pc lets anyone join", "DEVICES"),            # the <name> <machine>
    ("is allow all on?", "DEVICES"),                          # a question about the setting
    ("allow all status", "DEVICES"),
    ("allow all", "CATCH"),                                   # the label, nothing else
    ("how open source projects let anyone join", "CATCH"),
    ("let people join the call", "CATCH"),
])
def test_everything_else_is_read_only(text, want):
    """⛔⛔ NEVER A WRITE, NEVER A SWITCH CONFIRM: the person's own list (whose row
    says "anyone can join"), or the catch-all, which names the phrasings."""
    assert _route(text) == want


@pytest.mark.parametrize("text", ["let strangers use my computer", "let whoever asks use my mac",
                                  "accept everyone on my mac",
                                  "I'm tired of approving people on my mac, let them in automatically",
                                  "let me approve each person for my mac",
                                  "approve anyone who asks for my mac"])
def test_an_allow_all_wish_never_reaches_the_nameless_approve(text):
    """⛔⛔ These raised "Say yes to that request?" (or to “anyone who”), whose
    nameless yes admits the ONE waiting stranger — the approve clause's yes words
    are `allow`, `accept`, `let … use`."""
    assert _route(text) == "DEVICES"


@pytest.mark.parametrize("text, want", [
    ("allow all cookies", "CATCH"), ("allow all agents on my mac", "DEVICES"),
    ("podcast: allow all requests", 'ARGV:["podcast"]'),
    # an audience phrase beside an artefact, or `without asking` with no audience,
    # keeps the route it had before the arm existed
    ("send me the podcast when anyone can join", 'ARGV:["podcast"]'),
    ("switch to the office pc without asking me", 'ARGV:["device-use"'),
])
def test_allow_all_with_another_noun_is_not_the_setting(text, want):
    """G20: `allow all agents on my mac` raised the Allow-all ON confirm. With a
    noun after it, `allow all` is not the checkbox: the route it had before the
    arm existed. (The switch's own name capture is the switch clause's business.)"""
    assert _route(text).startswith(want)
    assert not _route("approve Sam automatically").startswith("ON")


# ── 5. the words around the arm ──────────────────────────────────────────────────

def test_the_catch_all_names_allow_all_and_two_phrasings_that_work():
    """⛔ G25: the catch-all — where every allow-all message this arm cannot read
    lands — never mentioned Allow all. The two phrasings it gives are EXECUTED:
    one asks to switch on, the other switches off."""
    said = sr._NL_CATCH_ALL
    assert "Allow all" in said
    on, off = re.findall(r"“([^”]+)”", said)
    assert _route(on) == "ON" and _route(off) == "OFF"
    help_line = " ".join(sr._nl_resolve("what can you do?")[1])
    assert f"“{on}”" in help_line and f"“{off}”" in help_line


def test_the_publish_confirm_does_not_promise_approval_on_an_allow_all_computer():
    """⛔ G28: "you would still approve every person yourself" was false on a
    computer that already lets anyone join — a plain publish leaves Allow all. The
    SKILL.md row the model relays it by says the same."""
    said = " ".join(sr._nl_resolve("make my mac public")[1])
    assert "you would still approve every person yourself, unless Allow all is already on" in said
    row = next(ln for ln in _SKILL.read_text(encoding="utf-8").splitlines()
               if "sr.py device-visibility public" in ln)
    assert "still approves each person unless Allow all is already on" in row, row


def test_the_ask_confirm_says_the_owner_sees_name_and_email():
    """⛔ G24 (chat half): the owner's Shared with row shows the name AND the email;
    the confirm said "your name — or your email". One sentence on every Join
    surface."""
    said = " ".join(sr._nl_resolve("join the Studio PC")[1])
    assert "The owner sees your name and email." in said and "or your email" not in said


def _skill_row(first: str) -> "list[str]":
    row = next(ln for ln in _SKILL.read_text(encoding="utf-8").splitlines()
               if ln.startswith(f'| "{first}"'))
    return re.findall(r'"([^"]+)"', row.split(" | ")[0])


def test_the_skills_allow_all_rows_list_phrasings_that_route_that_way():
    """⭐ The two SKILL.md rows name the exact phrasings, and every one of them is
    executed: the ON row's all ask to switch on, the OFF row's all switch off."""
    on_row, off_row = _skill_row("turn on allow all"), _skill_row("turn off allow all")
    assert len(on_row) >= 10 and len(off_row) >= 10
    for text in on_row:
        assert _route(text) == "ON", text
    for text in off_row:
        assert _route(text) == "OFF", text


def test_the_skills_off_row_sends_a_problem_report_to_the_list():
    """⛔⛔ G2's refuter: SKILL.md sends anything no row clearly fits to `sr do`, and
    a fault report was read there as OFF. The row now says it in so many words —
    and the example it gives is executed, and lists the computers."""
    row = next(ln for ln in _SKILL.read_text(encoding="utf-8").splitlines()
               if ln.startswith('| "turn off allow all"'))
    said = row.split(" | ", 1)[1]
    report = re.search(r'"(my mac won[^"]+)" is a problem report, not an order — run `sr\.py '
                       r'devices`', said)
    assert report, said
    assert _route(report.group(1)) == "DEVICES"


# ── 6. join, the ask verb, and what it must not take ─────────────────────────────

@pytest.mark.parametrize("text", ["research why people don't join unions",
                                  "look into why users never join the beta",
                                  "research why employees won't join the pension plan"])
def test_a_research_topic_with_a_negated_join_is_research(text):
    """⛔ G12: `join` in the negation vocabulary refused these as negated commands."""
    assert _route(text).startswith('ARGV:["research"'), _route(text)


@pytest.mark.parametrize("text, want", [
    ("sign in and ask to join the Studio PC", "LOGIN"),
    ("sign in so I can ask to join the Studio PC", "LOGIN"),
    ("my friend asked to join my mac", "DEVICES"),
    ("I asked to join the Studio PC", "CATCH"),
    ("I already asked to join the Studio PC", "CATCH"),
    ("don't join the Studio PC", "CATCH"),
    ("never join the Studio PC", "CATCH"),
    ("join the Studio PC", "ASK:Studio PC"),
    ("join public computer Studio PC", "ASK:Studio PC"),
])
def test_the_join_capture_obeys_its_own_guards(text, want):
    """⛔ G13: the capture was taken whenever ANY ask word was present, so sign-in,
    the asker's own computer and a past or negated join all reached the ask
    confirm. ⛔ G20: `public computer` rode into the name."""
    assert _route(text) == want


# ── 7. the `do` path, executed with the bridge stubbed ───────────────────────────

@pytest.fixture()
def bridge(monkeypatch, capsys):
    posts: list = []
    owned = {"devices": [{"id": "dev-mac", "name": "My Mac", "owned": True,
                          "visibility": "public", "allowAll": True}]}
    monkeypatch.setattr(sr, "_get", lambda path, timeout=None: (200, owned))
    monkeypatch.setattr(sr, "_post", lambda path, body=None, timeout=None: posts.append(
        (path, body)) or (200, {"deviceName": "My Mac", "visibility": "public",
                                "allowAll": False, "changed": True}))
    return SimpleNamespace(posts=posts, out=lambda: capsys.readouterr().out)


def _do(text):
    ns = sr.build_parser().parse_args(["do", text])
    return ns.func(ns)


@pytest.mark.parametrize("text", ["my mac stopped letting anyone join, can you fix it",
                                  "allow all for my mac no matter who asks",
                                  "leave the lab pc alone and turn off allow all on my mac",
                                  "since my mac is offline, list computers that let anyone join",
                                  "turn on allow all for my mac"])
def test_do_writes_nothing_for_anything_but_a_whole_off_command(bridge, text):
    """⛔⛔ Round 2's refuters drove these through `sr.py do` and watched POST
    /device/visibility {allowAll: false} (or the ON confirm's yes publish the
    joiner's computer). Nothing is written now; ON only asks."""
    _do(text)
    assert not [p for p in bridge.posts if p[0] == "/device/visibility"], bridge.posts


def test_do_switches_off_on_the_whole_command(bridge):
    _do("turn off allow all on my mac")
    assert bridge.posts == [("/device/visibility", {"deviceId": "dev-mac", "allowAll": False})]
