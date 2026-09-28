"""The chat's Allow-all handling, stripped to the bare minimum (wave 12 repair 3,
2026-09-27).

⛔⛔ EACH REVIEW ROUND'S SERIOUS FINDINGS CAME FROM MACHINERY THE REPAIR BEFORE IT
ADDED. Round 3, driven through `sr.py do` with the bridge stubbed at repair 2:

  · `turn off allow all on my mac but keep it listed` (and `…but let people find
    my mac`, `…keep sharing my mac`) POSTed {visibility: private} — an
    UNCONFIRMED HIDE, through repair 2's hand-off to the visibility clause (H1);
  · `turn on allow all so I can join the Studio PC` — a JOINER — raised the
    confirm that opens their OWN computer, through repair 2's `so …` reason tail
    (H3); `forget it, go back to approving people` reached the nameless approve
    confirm (H4); `require approval again and pause the mars run` paused (H5);
  · `my friend wants to join the Studio PC` raised the ask confirm (H7); `turn off
    allow all for my Mac mini` changed nothing (H6); `investigate why my mac won't
    let anyone join` started a PAID run (H13); `join the Studio PC now` asked about
    “Studio PC now” (H14); `sign in and turn off allow all` lost the sign-in (H15);
    `borrow K7XQ-9B2M` posted the code as a device id (H17).

⭐ THE POLICY PINNED HERE, BY EXECUTION — the router AND the `do` path:
  R1. A command is the WHOLE message: politeness in front, thanks or a time word
      behind, ONE computer (model words after its machine noun allowed). Nothing
      else — not even a reason. ON confirms, OFF acts.
  R2. ANY other message with an Allow-all phrase is READ-ONLY and the arm owns it:
      other people's computers → the browse list; the person's own computer or a
      question about the setting → their own list; otherwise the catch-all. No
      clause writes or confirms for it. Before it: a sign-in instruction (login)
      and a research verb (research — unless the person's own computer sits beside
      the Allow-all words, which is their own list, never a paid run).
  R3. An ask to join is the WHOLE message too: `(please) join|ask to join|ask to
      use|request access to|borrow <ONE computer>` (+ now/today/please). A code
      after any ask verb pairs.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

_TESTS = Path(__file__).resolve().parent
_SCRIPTS = _TESTS.parent / "facade" / "skill" / "scripts"
_SKILL = _TESTS.parent / "facade" / "skill" / "SKILL.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_repair3_0927", _SCRIPTS / "sr.py")
# The repair-2 pins hold every phrasing rounds 1 and 2 quoted, at its route; the
# `do`-path must-nots below execute all of them against THIS copy of sr.py.
_wm = _load("allow_all_whole_message_rows_for_repair3", _TESTS / "test_allow_all_whole_message_0927.py")

_HEADS = {key: sr._NL_CONFIRMS[key].split("{name}")[0]
          for key in ("device-allow-all", "device-ask", "device-visibility",
                      "device-approve", "device-deny", "stop")}
_TAG = {"device-allow-all": "ON", "device-ask": "ASK", "device-visibility": "PUBLISH",
        "device-approve": "APPROVE", "device-deny": "DENY", "stop": "STOP"}


def _route(text: str) -> str:
    """OFF[:name], ON[:name], HIDE[:name], DEVICES, PUBLIC, LOGIN, ADD:<code>,
    ASK[:name], CATCH, SET, PUBLISH, APPROVE[:name], RESEARCH, ARGV:…, LINE:…"""
    argv, lines = sr._nl_resolve(text)
    if argv is not None:
        if argv[:2] == ["device-allow-all", "no"]:
            return "OFF" + (f":{argv[2]}" if len(argv) > 2 else "")
        if argv[:2] == ["device-visibility", "private"]:
            return "HIDE" + (f":{argv[2]}" if len(argv) > 2 else "")
        simple = {("devices",): "DEVICES", ("devices-public",): "PUBLIC", ("login",): "LOGIN"}
        if tuple(argv) in simple:
            return simple[tuple(argv)]
        if argv[0] == "device-add":
            return "ADD:" + argv[1]
        if argv[0] == "research":
            return "RESEARCH"
        return "ARGV:" + json.dumps(argv, ensure_ascii=False)
    said = " ".join(lines or [])
    if said == sr._NL_CATCH_ALL:
        return "CATCH"
    for key, head in _HEADS.items():
        if said.startswith(head):
            rest = said[len(head):]
            name = rest[1:rest.index("”")] if rest.startswith("“") else ""
            return _TAG[key] + (f":{name}" if name else "")
    if said.startswith("I switch Allow all one computer at a time"):
        return "SET"
    return "LINE:" + said[:60]


# ── R1: the whole message IS the command ─────────────────────────────────────────

@pytest.mark.parametrize("text, want", [
    # H6 — model words after the machine noun: the picker, as `my mac` gets
    ("turn off allow all for my Mac mini", "OFF"),
    ("turn off allow all for my MacBook Pro", "OFF"),
    ("turn off allow all for my laptop 2", "OFF"),
    ("turn off allow all on my mac mini", "OFF"),
    ("stop letting anyone join my mac mini", "OFF"),
    ("could you turn off allow all for my Mac mini?", "OFF"),
    ("let anyone join my Mac mini", "ON"),
    ("turn on allow all for my macbook pro", "ON"),
    # …and a NAME keeps them, as the person wrote it
    ("turn off allow all on the office Mac mini", "OFF:office Mac mini"),
    # H6 — `for now` and the other time words behind a command
    ("turn off allow all for now", "OFF"), ("turn allow all off for now", "OFF"),
    ("turn off allow all today", "OFF"), ("turn off allow all on my mac please", "OFF"),
    # a quoted name stays; an unquoted one needs `the <name> <machine>`
    ("turn off allow all on “Studio PC”", "OFF:Studio PC"),
    ("let anyone join “LABPC001”", "ON:LABPC001"),
    ("publish “LABPC001” and allow all", "ON:LABPC001"),
    ("turn off allow all on Studio PC", "CATCH"),
    ("publish LABPC001 and allow all", "CATCH"),               # H19: the gap, recorded
    # not model words — a place, or a second request: read-only, as specified
    ("turn off allow all for the Mac mini in the office", "DEVICES"),
    ("turn off allow all for my computer at home", "DEVICES"),
    ("make my mac public and turn on allow all", "DEVICES"),
    ("turn off allow all for my mac for a while", "DEVICES"),
])
def test_r1_a_command_is_the_whole_message(text, want):
    assert _route(text) == want


_H3_REASONS = [
    ("turn on allow all so I can join the Studio PC", "PUBLIC"),
    ("turn on allow all so I can join “Studio PC”", "PUBLIC"),
    ("enable allow all so i can use the studio pc", "DEVICES"),
    ("let anyone join so I can get onto the Studio PC", "DEVICES"),
    ("turn on allow all because the Studio PC owner asked me to", "DEVICES"),
    ("turn on allow all for my laptop so I can join the Studio PC", "PUBLIC"),
    ("turn off allow all so strangers stop joining the Studio PC", "DEVICES"),
    ("turn off allow all for my mac so strangers stop joining", "DEVICES"),
    ("turn off allow all for my Mac mini so strangers stop joining", "DEVICES"),
    ("turn on allow all since I'm away all week", "CATCH"),
    ("let anyone join my mac mini because I'm away", "DEVICES"),
]


@pytest.mark.parametrize("text, want", _H3_REASONS)
def test_r1_a_reason_makes_it_not_a_command(text, want):
    """⛔⛔ H3: the reason tail repair 2 accepted let a JOINER's `…so I can join the
    Studio PC` raise the confirm that opens their own computer (the yes POSTed
    {deviceId: dev-mine, allowAll: true, visibility: public}); `…so strangers stop
    joining the Studio PC` switched the joiner's own computer OFF. Gone: a reason
    makes the message read-only, whichever computer it names."""
    assert _route(text) == want


# ── R2: every other message with Allow-all words is read-only ────────────────────

_R2_ROWS = [
    # H1 — keep / find / share beside OFF: never the hide (repair 2 HID every one)
    ("turn off allow all on my mac but keep it listed", "DEVICES"),
    ("switch off allow all but let people find my mac", "DEVICES"),
    ("turn off auto-join but keep sharing my mac", "DEVICES"),
    ("make my mac public and turn off approvals", "DEVICES"),
    ("turn approvals off for my mac, let people find it and join at once", "DEVICES"),
    ("turn off allow all on my mac but keep it shared", "DEVICES"),
    ("turn off allow all on my mac but keep it visible", "DEVICES"),
    ("turn off allow all on my mac but keep it findable", "DEVICES"),
    ("keep my mac listed and turn off allow all", "DEVICES"),
    ("turn off allow all on my mac and leave it listed", "DEVICES"),
    ("turn off allow all on my mac and leave it shared", "DEVICES"),
    ("turn off allow all on my mac but still let people find it", "DEVICES"),
    ("turn off allow all on my mac, people should still see it", "DEVICES"),
    ("turn off allow all on my mac and keep sharing it", "DEVICES"),
    ("turn off allow all on my mac but don't hide it", "DEVICES"),
    ("turn off allow all on my mac but don't make it private", "DEVICES"),
    ("turn off allow all on my mac but keep it public", "DEVICES"),
    ("turn off allow all but still let people find it", "CATCH"),
    ("turn off allow all, people should still see it", "CATCH"),
    ("turn off allow all and leave it listed", "CATCH"),
    ("turn off allow all but don't hide it", "CATCH"),
    # H11 — the two guards of the removed hand-off: a `?` and `leave … public`
    ("turn off allow all and make my mac private?", "DEVICES"),
    ("stop letting anyone join my mac but leave it public", "DEVICES"),
    # H4 — an unlink / `forget` beside the words: never the nameless approve
    ("forget it, go back to approving people", "CATCH"),
    ("forget it, allow anyone to join my mac", "DEVICES"),
    ("unlink my old laptop and go back to approving people", "DEVICES"),
    ("unlink my old laptop and let anyone join", "DEVICES"),
    # H5 — two commands: never half of either
    ("require approval again and pause the mars run", "CATCH"),
    ("pause the Mars run when anyone can join", "CATCH"),
    ("turn off allow all on my mac and hide the lab pc", "DEVICES"),
    ("hide the lab pc and turn off allow all on my mac", "DEVICES"),
    ("join the studio pc and turn off allow all on my mac", "PUBLIC"),
    ("turn on allow all for my mac, then pause the run", "DEVICES"),
    ("approve Sam and turn off allow all", "CATCH"),
    # H7 — the owner's own wish about approvals: their list, never an ask
    ("ask for approval before anyone can join my mac", "DEVICES"),
    # other people's computers first, then the person's own, then the catch-all
    ("which public computers let anyone join?", "PUBLIC"),
    ("since my mac is offline, list computers that let anyone join", "PUBLIC"),
    ("join the lab macs that let anyone in", "PUBLIC"),
    ("join the studio pc that lets anyone in", "PUBLIC"),
    ("my mac won't let anyone join", "DEVICES"),
    ("is allow all on?", "DEVICES"),
    # a polite question about the setting is the same question (the `can you`
    # exception belonged to the removed hand-off)
    ("tell me about allow all", "DEVICES"),
    ("can you tell me about allow all", "DEVICES"),
    ("could you explain allow all", "DEVICES"),
    ("let people join the call", "CATCH"),
    ("send me the podcast when anyone can join", "CATCH"),
]


@pytest.mark.parametrize("text, want", _R2_ROWS)
def test_r2_a_message_with_allow_all_words_that_is_not_a_command_is_read_only(text, want):
    assert _route(text) == want


@pytest.mark.parametrize("text", ["sign in and turn off allow all",
                                  "log in and turn off allow all on my mac",
                                  "sign in and let anyone join my mac",
                                  "login and let anyone join my mac",
                                  "turn on allow all and sign me in",
                                  "sign me in so I can turn off allow all"])
def test_r2_a_sign_in_beside_allow_all_words_stays_a_sign_in(text):
    """⛔ H15: `sign in and turn off allow all` reached the catch-all (base: login);
    with `on my mac` it listed the computers. e567704: a sign-in stays a sign-in."""
    assert _route(text) == "LOGIN"


@pytest.mark.parametrize("text, want", [
    ("investigate why my mac won't let anyone join", "DEVICES"),
    ("research why my mac won't let anyone join", "DEVICES"),
    ("look into why nobody can join my mac", "DEVICES"),
    ("research whether allow all is safe for my mac", "DEVICES"),
    # a topic about the world stays a topic — no own computer beside the words
    ("research why companies let anyone join their Slack", "RESEARCH"),
    ("research how open source projects let anyone join", "RESEARCH"),
    # …and one that names the person's computer far from them stays a topic too
    ("research how to let anyone join a Slack workspace from my laptop", "RESEARCH"),
    # ⛔ REPLACED 2026-09-27 (wave 12 repair 4, cross-verify K5): the row here was
    # `research the EV market on my mac, allow all agents`, and it passed under D1,
    # D2 and D3 alike — `allow all agents` is not the setting, so it measured
    # nothing. This one measures the clause boundary: the person's computer is
    # within twenty characters, but across a comma.
    ("research on my mac, how companies let anyone join Slack", "RESEARCH"),
])
def test_r2_a_research_verb_is_research_unless_it_is_about_their_own_allow_all(text, want):
    """⛔⛔ H13: `investigate why my mac won't let anyone join` POSTed /research — a
    PAID run about the person's own setting."""
    assert _route(text) == want


def test_approve_a_person_is_not_an_allow_all_phrase():
    """`approve <a person>` answers a waiting ask — outside the Allow-all words."""
    assert _route("approve Sam") == "APPROVE:Sam"
    assert _route("deny Sam") == "DENY:Sam"


# ── R3: an ask to join is the whole message ──────────────────────────────────────

@pytest.mark.parametrize("text, want", [
    # H7 — statements, reports, third person, past tense, questions: never an ask
    ("my friend wants to join the Studio PC", "DEVICES"),
    ("people keep trying to join the office pc", "CATCH"),
    ("I tried to join the Studio PC but it failed", "CATCH"),
    ("join the Studio PC but it failed", "CATCH"),
    ("join the Studio PC that Sam set up", "CATCH"),
    ("join the Studio PC because Sam said so", "CATCH"),
    ("can I join the Studio PC?", "CATCH"),
    ("should I join the Studio PC", "CATCH"),
    ("join the Studio PC?", "CATCH"),
    ("sign up and join the Studio PC", "CATCH"),
    ("join the Studio PC, Lab edition", "CATCH"),
    ("join this mac", "CATCH"),
    ("join the call from my laptop", "DEVICES"),
    ("join my mac", "DEVICES"),
    ("sign in and join the Studio PC", "LOGIN"),
    # H14 — the whole-message ask, a time word off the end of the name
    ("join the Studio PC", "ASK:Studio PC"),
    ("join the Studio PC now", "ASK:Studio PC"),
    ("join the Studio PC today", "ASK:Studio PC"),
    ("join the Studio PC now please", "ASK:Studio PC"),
    ("join the Studio PC at once", "ASK:Studio PC"),
    ("please join the Studio PC", "ASK:Studio PC"),
    ("I want to join the Studio PC", "ASK:Studio PC"),
    ("let me join the Studio PC", "ASK:Studio PC"),
    ("ask to join the Studio PC", "ASK:Studio PC"),
    ("borrow the Studio PC now", "ASK:Studio PC"),
    ("join computer Studio PC", "ASK:Studio PC"),                 # H20: the noun comes off
    ("join “DG shared”", "ASK:DG shared"),
    ("join “Lab and Studio PC”", "ASK:Lab and Studio PC"),         # quoted: verbatim
    # H17 — a code after ANY ask verb pairs; a machine id said with its noun does not
    ("borrow K7XQ-9B2M", "ADD:K7XQ-9B2M"),
    ("ask for K7XQ-9B2M", "ADD:K7XQ-9B2M"),
    ("ask to use K7XQ-9B2M", "ADD:K7XQ-9B2M"),
    ("request access to K7XQ-9B2M", "ADD:K7XQ-9B2M"),
    ("join K7XQ-9B2M now", "ADD:K7XQ-9B2M"),
    ("please let me join K7XQ-9B2M", "ADD:K7XQ-9B2M"),
    ("i want to join K7XQ-9B2M", "ADD:K7XQ-9B2M"),
    ("request access to computer LABPC001", "ASK:LABPC001"),
])
def test_r3_an_ask_to_join_is_the_whole_message(text, want):
    assert _route(text) == want


# ── the `do` path, executed with the bridge stubbed ──────────────────────────────

_MY_MAC = {"id": "dev-mac", "name": "My Mac", "owned": True, "visibility": "public",
           "allowAll": True}
_PUBLIC = {"devices": [{"deviceId": "pub-studio", "label": "Studio PC", "online": True,
                        "allowAll": True}]}


@pytest.fixture()
def bridge(monkeypatch, capsys):
    """One owned computer (“My Mac”), one public one (“Studio PC”); every POST is
    recorded. ⛔ The watcher arm is stubbed: `login` would otherwise write cron."""
    posts: list = []
    state = SimpleNamespace(owned=[dict(_MY_MAC)], ask_reply=(200, {"ok": True, "status": "pending"}))

    def _get(path, timeout=None):
        if path == "/devices/public":
            return 200, _PUBLIC
        if path == "/devices/requests":
            return 200, {"incoming": [{"requesterUid": "u-sam", "requesterLabel": "Sam",
                                       "deviceId": "dev-mac", "deviceLabel": "My Mac"}]}
        if path == "/status":
            return 200, {}
        return 200, {"devices": state.owned}

    def _post(path, body=None, timeout=None):
        posts.append((path, body))
        if path == "/device/ask":
            return state.ask_reply
        return 200, {"deviceName": "My Mac", "visibility": "public", "allowAll": False,
                     "changed": True, "ok": True, "url": "https://example.test/x"}

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 1))
    state.posts = posts
    state.out = lambda: capsys.readouterr().out
    return state


def _do(text):
    ns = sr.build_parser().parse_args(["do", text])
    return ns.func(ns)


_OFF_POST = ("/device/visibility", {"deviceId": "dev-mac", "allowAll": False})


@pytest.mark.parametrize("text", ["turn off allow all for my Mac mini", "turn off allow all for now",
                                  "stop letting anyone join my mac mini",
                                  "could you turn off allow all for my Mac mini?"])
def test_do_a_whole_off_command_writes_allow_all_off_once(bridge, text):
    """H6: the owner's one computer is called “My Mac”, so `my Mac mini` reaching
    it proves the picker took it — the model words are a KIND, not a name."""
    _do(text)
    assert bridge.posts == [_OFF_POST]


@pytest.mark.parametrize("text", ["let anyone join my Mac mini", "turn on allow all for my macbook pro"])
def test_do_a_whole_on_command_only_asks(bridge, text):
    _do(text)
    assert bridge.posts == []
    assert bridge.out().startswith(_HEADS["device-allow-all"])


_READ_ONLY = ("DEVICES", "PUBLIC", "CATCH")
_ROUND3 = ([(t, w) for t, w in _R2_ROWS] + list(_H3_REASONS)
           + [(t, "DEVICES") for t in ("investigate why my mac won't let anyone join",
                                       "research why my mac won't let anyone join")]
           + [("my friend wants to join the Studio PC", "DEVICES"),
              ("people keep trying to join the office pc", "CATCH"),
              ("I tried to join the Studio PC but it failed", "CATCH")])
_EVERY_ROUND = (_ROUND3 + [(t, w) for t, w in _wm.PINNED]
                + [(t, w) for t, w, _was, _why in _wm.FLIPPED_R3])


@pytest.mark.parametrize("text, want", [r for r in _EVERY_ROUND
                                        if r[1] in _READ_ONLY or r[1].startswith("LINE:")])
def test_do_writes_nothing_for_a_read_only_route(bridge, text, want):
    """⛔⛔ THE REVERSE MUST-NOT, EXECUTED: every phrasing the three rounds quoted
    whose route is read-only is run through `sr.py do` against the stubbed bridge —
    and posts NOTHING (no hide, no switch, no ask, no approve, no pause, no run)."""
    assert _route(text) == want
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text, want", [r for r in _EVERY_ROUND
                                        if r[1].split(":")[0] in ("ON", "ASK", "PUBLISH",
                                                                  "APPROVE", "DENY", "STOP", "SET")])
def test_do_a_confirm_route_posts_nothing(bridge, text, want):
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text, want", [r for r in _EVERY_ROUND if r[1].startswith("OFF")])
def test_do_off_writes_only_allow_all_off(bridge, text, want):
    """OFF never publishes, never hides: allowAll false on the picked computer, or
    nothing when the name it was given is not this account's."""
    _do(text)
    assert bridge.posts in ([_OFF_POST], []), (text, bridge.posts)


@pytest.mark.parametrize("text", ["sign in and turn off allow all",
                                  "log in and turn off allow all on my mac"])
def test_do_a_sign_in_beside_allow_all_starts_a_sign_in_only(bridge, text):
    _do(text)
    assert [p for p, _b in bridge.posts] == ["/login/remote/start"]


@pytest.mark.parametrize("text, code", [("borrow K7XQ-9B2M", "K7XQ-9B2M"),
                                        ("ask for K7XQ-9B2M", "K7XQ-9B2M"),
                                        ("request access to K7XQ-9B2M", "K7XQ-9B2M"),
                                        ("join K7XQ-9B2M now", "K7XQ-9B2M")])
def test_do_a_code_after_an_ask_verb_pairs_and_never_asks(bridge, text, code):
    """⛔ H17: the yes POSTed /device/ask {deviceId: 'K7XQ-9B2M'} — an ask spent,
    nothing paired."""
    _do(text)
    assert bridge.posts == [("/device/pair", {"code": code})]


def test_do_join_the_studio_pc_now_asks_about_the_computer_the_list_names(bridge):
    """⛔ H14: the yes then printed 'No public computer is called “Studio PC now”'.
    The confirm names “Studio PC”, and the yes — run as SKILL.md says — reaches it."""
    _do("join the Studio PC now")
    assert bridge.posts == []
    assert bridge.out().startswith(f"{_HEADS['device-ask']}“Studio PC”")
    assert sr.cmd_device_ask(SimpleNamespace(device="Studio PC", json=False)) == 0
    assert bridge.posts == [("/device/ask", {"deviceId": "pub-studio"})]


# ── H16 / H21 / H22 — the words, executed ────────────────────────────────────────

def test_the_hide_picker_example_hides(bridge):
    """⛔ H16: with two owned computers a nameless hide said "Say for example: make
    “My Mac” public." — said back, the PUBLISH confirm. Each example is executed."""
    bridge.owned = [dict(_MY_MAC), {"id": "dev-lab", "name": "Lab PC", "owned": True,
                                    "visibility": "public"}]
    for value, want in (("private", ["device-visibility", "private", "My Mac"]),
                        ("public", None)):
        sr.cmd_device_visibility(SimpleNamespace(value=value, device="", allow_all=False,
                                                 json=False))
        out = bridge.out()
        example = next(ln for ln in out.splitlines()
                       if ln.startswith("Say for example: "))[len("Say for example: "):].rstrip(".")
        assert example == f"make “My Mac” {value}"
        argv, lines = sr._nl_resolve(example)
        if want:
            assert argv == want, (example, argv)
        else:
            assert " ".join(lines).startswith(_HEADS["device-visibility"] + "“My Mac”")
    assert bridge.posts == []


_JOINED = {"ok": True, "status": "joined", "deviceId": "pub-studio", "deviceName": "Studio PC",
           "online": True, "usable": True, "autoStarted": False, "runId": None}


def test_a_join_that_keeps_research_on_your_computer_says_so_and_how_to_move_it(bridge):
    """⛔ H21: selected=false, and the reply said nothing — `research X on the Studio
    PC` then ran on the person's own computer. The line names the switch, and the
    switch it names is executed through the router."""
    bridge.ask_reply = (200, dict(_JOINED, selected=False))
    sr.cmd_device_ask(SimpleNamespace(device="Studio PC", json=False))
    out = bridge.out()
    line = "Your research stays on your current computer — say “use Studio PC” to run it there."
    assert line in out, out
    assert "Your research will run on it." not in out
    said = re.search(r"say “(use [^”]+)”", line).group(1)
    assert sr._nl_resolve(said) == (["device-use", "Studio PC"], None)


def test_a_join_that_selects_the_computer_does_not_say_it_stays(bridge):
    bridge.ask_reply = (200, dict(_JOINED, selected=True))
    sr.cmd_device_ask(SimpleNamespace(device="Studio PC", json=False))
    out = bridge.out()
    assert "Your research will run on it." in out
    assert "stays on your current computer" not in out


def test_the_pending_reply_says_what_the_confirm_said(bridge):
    """⛔ H22: the confirm said "The owner sees your name and email." and the pending
    reply one message later "your name — or your email". Both executed."""
    confirm = " ".join(sr._nl_resolve("join the Studio PC")[1])
    sr.cmd_device_ask(SimpleNamespace(device="Studio PC", json=False))
    out = bridge.out()
    for said in (confirm, out):
        assert "The owner sees your name and email." in said, said
        assert "or your email" not in said, said


# ── SKILL.md ─────────────────────────────────────────────────────────────────────

def _skill_row(first: str) -> str:
    return next(ln for ln in _SKILL.read_text(encoding="utf-8").splitlines()
                if ln.startswith(f'| "{first}"'))


def test_skill_says_do_switches_only_on_a_whole_message_and_takes_no_reason():
    """The OFF row carried repair 2's "and one "so …" reason"; the reason tail is
    gone (H3), so the row says what `do` does now — and its examples of what may
    follow a phrasing are executed."""
    row = _skill_row("turn off allow all")
    said = row.split(" | ", 1)[1]
    assert "ONLY when the WHOLE message is one phrasing from these two rows" in said
    assert "not even a reason" in said
    assert '"so …" reason' not in said
    for tail in re.findall(r'"((?:for|on) [^"]+)"', said):
        assert _route(f"turn off allow all {tail}").startswith("OFF"), tail


def test_skill_ask_row_says_do_asks_only_on_a_whole_message():
    """⛔ H7 in SKILL.md: the two statements it names are executed — neither asks."""
    row = _skill_row("ask for the Studio PC")
    assert "asks only when the WHOLE message is the ask" in row
    assert "“use <name>”" in row or '"use <name>"' in row
    for text in ("join the Studio PC", "join “DG shared” now"):
        assert _route(text).startswith("ASK:"), text
    for stem in ("my friend wants to join", "I tried to join"):
        assert f'"{stem}…' in row, stem
        assert not _route(f"{stem} the Studio PC").startswith("ASK"), stem


# ── generated reverse must-not: a command inside anything else is not one ───────

_COMMANDS = ["turn off allow all", "turn on allow all", "let anyone join my mac",
             "stop letting anyone join my mac", "require approval again",
             "turn off allow all for my Mac mini", "let anyone join my mac mini",
             "go back to approving people", "turn off approvals for my mac"]
_WRAP = ["{} so I can join the Studio PC", "{} because the Studio PC owner asked",
         "{} but keep it listed", "{} and pause the mars run", "forget it, {}",
         "unlink my old laptop and {}", "{} and hide the lab pc", "hide the lab pc and {}",
         "my friend wants me to {}", "I tried to {} but it failed", "{} since I'm away"]


@pytest.mark.parametrize("wrap", _WRAP)
@pytest.mark.parametrize("cmd", _COMMANDS)
def test_a_command_inside_a_longer_message_writes_and_confirms_nothing(bridge, cmd, wrap):
    """⭐ Generated: each command works said alone; wrapped in a reason, a second
    command, a keep, a report or a third person it routes read-only, and `do`
    posts nothing."""
    assert _route(cmd).split(":")[0] in ("ON", "OFF"), cmd
    text = wrap.format(cmd)
    assert _route(text) in _READ_ONLY, (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)
