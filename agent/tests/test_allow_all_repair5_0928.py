"""The chat's message reading — the last repair before the owner's E2E (wave 12
repair 5, 2026-09-28).

The final focused review drove `sr.py do` at repair 4 (8936aa8), with repair 3
(413e986) beside it, and found seven readings repair 4 over-reached or left half
done. Where repair 4 over-reached, repair 3's behaviour is restored:

  router-1  research topics stopped starting: `…without my permission` beside the
            person's own computer, and `people join this computer science
            program` / `…my mac's wifi network` (a compound or a possessive).
  router-2  a code after an ask verb outside repair 4's six-verb list raised the
            ask confirm, whose yes posts the code as a device id (H17's class):
            `ask for access to K7XQ-9B2M`, `Hi! borrow K7XQ-9B2M`, `can I borrow
            K7XQ-9B2M?`; `join K7XQ–9B2M` (a phone's en dash) and `join YGXU7WH2`
            (no dash, as SKILL.md allows) never paired.
  router-3  `borrow her laptop now` asked about a computer called “laptop now”.
  router-4  `am I logged into the mac app, it says I need to log in` listed the
            computers instead of the sign-in line.
  router-5  `stop “auto-approve”` switched Allow all OFF instead of stopping the run
            of that name.
  router-6  `go back to approving each request` changed nothing; `can u sign me in
            and turn off allow all` never signed in.
  router-7  `research EV batteries on my mac “Allow All Lab”` stored its title with
            one quote.

Each is pinned by EXECUTION: `sr._nl_resolve`, and `sr.py do` with `_get`/`_post`
stubbed, asserting the POSTs a message makes — or that it makes none. The mutants
are in .mutants/wave12_repair5_router_mutants.py.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_TESTS = Path(__file__).resolve().parent
_SCRIPTS = _TESTS.parent / "facade" / "skill" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_repair5_0928", _SCRIPTS / "sr.py")

_HEADS = {key: sr._NL_CONFIRMS[key].split("{name}")[0]
          for key in ("device-allow-all", "device-ask", "device-visibility",
                      "device-approve", "device-deny", "stop")}
_TAG = {"device-allow-all": "ON", "device-ask": "ASK", "device-visibility": "PUBLISH",
        "device-approve": "APPROVE", "device-deny": "DENY", "stop": "STOP"}


def _route(text: str) -> str:
    """OFF[:name], HIDE[:name], DEVICES, PUBLIC, LOGIN, ADD:<code>, ASK[:name],
    STOP[:name], CATCH, RESEARCH, ACCOUNT, ARGV:…, LINE:…"""
    argv, lines = sr._nl_resolve(text)
    if argv is not None:
        if argv[:2] == ["device-allow-all", "no"]:
            return "OFF" + (f":{argv[2]}" if len(argv) > 2 else "")
        if argv[:2] == ["device-visibility", "private"]:
            return "HIDE" + (f":{argv[2]}" if len(argv) > 2 else "")
        simple = {("devices",): "DEVICES", ("devices-public",): "PUBLIC", ("login",): "LOGIN",
                  ("status-account",): "ACCOUNT"}
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
    return "LINE:" + said[:60]


# ── the `do` path, with the bridge stubbed ───────────────────────────────────────

_MY_MAC = {"id": "dev-mac", "name": "My Mac", "owned": True, "visibility": "public",
           "allowAll": True}
_PUBLIC = {"devices": [{"deviceId": "pub-studio", "label": "Studio PC", "online": True,
                        "allowAll": True}]}


@pytest.fixture()
def bridge(monkeypatch, capsys):
    """“My Mac” owned and letting anyone join (Allow all ON — where an unconfirmed
    OFF changes something), one public “Studio PC”. Every GET and POST is recorded.
    ⛔ The watcher arm is stubbed: `login` would otherwise write cron."""
    posts: list = []
    gets: list = []
    state = SimpleNamespace(owned=[dict(_MY_MAC)])

    def _get(path, timeout=None):
        gets.append(path)
        if path == "/devices/public":
            return 200, _PUBLIC
        if path == "/devices/requests":
            return 200, {"incoming": []}
        if path == "/status":
            return 200, {}
        if path.startswith("/updates"):
            return 200, {"updates": []}
        return 200, {"devices": state.owned}

    def _post(path, body=None, timeout=None):
        posts.append((path, body))
        if path == "/device/ask":
            return 200, {"ok": True, "status": "pending"}
        return 200, {"deviceName": "My Mac", "visibility": "public", "allowAll": False,
                     "changed": True, "ok": True, "url": "https://example.test/x", "runId": "r1"}

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 1))
    state.posts = posts
    state.gets = gets
    state.out = lambda: capsys.readouterr().out
    return state


def _do(text):
    ns = sr.build_parser().parse_args(["do", text])
    return ns.func(ns)


_OFF_POST = ("/device/visibility", {"deviceId": "dev-mac", "allowAll": False})
_LOGIN_POST = "/login/remote/start"


# ── router-1: a research topic about people and computers STARTS ─────────────────

_R1_TOPICS = [
    # `permission` only after somebody who would join (413e986's rule)
    "research why my mac installs updates without my permission",
    "look into why my laptop restarts without my permission",
    "research which apps can access my mac's camera without my permission",
    "research why Windows reboots my desktop without permission",
    # the machine word opens a compound, or is somebody's (`my mac's …`)
    "research why people join this computer science program",
    "research why everyone joins this machine learning course",
    "research why people join our computer club",
    "research why people are joining our pc gaming guild",
    "research how people join my mac's wifi network",
    "research why anyone would join this computer science degree",
]


@pytest.mark.parametrize("text", _R1_TOPICS)
def test_router1_a_topic_about_people_joining_things_starts_its_run(bridge, text):
    """⛔⛔ Repair 4 read `without my permission` beside the person's computer, and
    people joining `this computer science program`, as the person's own Allow all:
    the run never started and they got their Devices list with no reason. Every
    one started at 413e986. `do` POSTs /research with the topic as typed."""
    assert _route(text) == "RESEARCH", (text, _route(text))
    _do(text)
    topic = text.split(" ", 2)[2] if text.startswith("look into") else text.split(" ", 1)[1]
    assert bridge.posts == [("/research", {"topic": topic})], (text, bridge.posts)


_R1_OWN = [
    "look into why people join my mac without my permission",
    "look into why people join my mac",
    "research why strangers keep joining my mac",
    "research why strangers join my mac mini",
    "research why strangers join my mac, and how to stop it",
    "research why people join my mac at once",
    "research why people use my mac without my permission",
]


@pytest.mark.parametrize("text", _R1_OWN)
def test_router1_people_joining_the_person_s_own_computer_is_still_their_list(bridge, text):
    """K5 stands: the person's own computer, ending there (or its model word, a
    clause end, `at once`), is their Allow all — their list, and nothing posted."""
    assert _route(text) == "DEVICES", (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)
    assert "/devices" in bridge.gets


# ── router-2: a code after an ask verb pairs, or changes nothing ─────────────────

_R2_PAIRS = [
    ("ask for access to K7XQ-9B2M", "K7XQ-9B2M"), ("request K7XQ-9B2M", "K7XQ-9B2M"),
    ("please request K7XQ-9B2M", "K7XQ-9B2M"), ("ask to borrow K7XQ-9B2M", "K7XQ-9B2M"),
    ("ok, ask for access to K7XQ-9B2M", "K7XQ-9B2M"), ("apply for K7XQ-9B2M", "K7XQ-9B2M"),
    ("go ahead and borrow K7XQ-9B2M", "K7XQ-9B2M"), ("go ask for K7XQ-9B2M", "K7XQ-9B2M"),
    ("Hi! Borrow K7XQ-9B2M", "K7XQ-9B2M"), ("Hello, borrow K7XQ-9B2M", "K7XQ-9B2M"),
    ("thanks! borrow K7XQ-9B2M", "K7XQ-9B2M"),
    ("join K7XQ–9B2M", "K7XQ–9B2M"), ("join K7XQ—9B2M", "K7XQ—9B2M"),
    ("join YGXU7WH2", "YGXU7WH2"), ("borrow YGXU7WH2", "YGXU7WH2"),
    ("join K7XQ9B2M", "K7XQ9B2M"), ("request access to ygxu7wh2", "ygxu7wh2"),
]


@pytest.mark.parametrize("text, code", _R2_PAIRS)
def test_router2_a_whole_message_ask_on_a_code_pairs_it(bridge, text, code):
    """⛔⛔ H17's class, back for every ask verb outside repair 4's list: the ask
    confirm's yes posts the code to /device/ask as a device id — one of the five
    asks an hour spent, and nothing ever paired. 413e986 paired each one."""
    assert _route(text) == f"ADD:{code}", (text, _route(text))
    _do(text)
    assert bridge.posts == [("/device/pair", {"code": code})], (text, bridge.posts)


_R2_NEVER = [
    "can I borrow K7XQ-9B2M?", "borrow K7XQ-9B2M?", "my friend wants to borrow K7XQ-9B2M",
    "should I borrow K7XQ-9B2M", "can I request access to K7XQ-9B2M?",
    "my friend wants to borrow YGXU7WH2", "can I borrow YGXU7WH2?",
    "my friend wants to borrow WDJB-MJHT",
]


@pytest.mark.parametrize("text", _R2_NEVER)
def test_router2_a_code_in_a_question_or_a_statement_is_never_asked_for(bridge, text):
    """⛔⛔ An unquoted code is never a computer to ask for, and outside a
    whole-message ask it is never paired (repair 4's K3): nothing is posted."""
    got = _route(text)
    assert not got.startswith(("ASK", "ADD")), (text, got)
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text, want", [
    ("borrow “K7XQ-9B2M”", "ASK:K7XQ-9B2M"), ('ask for access to "K7XQ-9B2M"', "ASK:K7XQ-9B2M"),
    ("borrow FEEDBACK", "ASK:FEEDBACK"), ("borrow Studio22", "ASK:Studio22"),
])
def test_router2_a_quoted_token_or_a_word_is_a_name(bridge, text, want):
    """A quoted token stays a name, and so does a word in capitals with no digit
    (RESEARCH, FEEDBACK — the access letters include vowels) or one with letters
    outside the access code's (Studio22): each asks, and the ask only asks."""
    assert _route(text) == want, (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


# ── router-3: somebody's computer is no ask; the older capture's name trimmed ────

@pytest.mark.parametrize("text", ["borrow her laptop now", "ask to use her laptop today",
                                  "request access to their Studio PC now",
                                  "ask to use its Studio PC now", "borrow your Studio PC",
                                  "borrow his mac tonight"])
def test_router3_somebody_s_computer_is_never_one_ask(bridge, text):
    """⛔ Repair 4 refused these in the whole-message join, and the older capture
    took them — `borrow her laptop now` asked about a computer called “laptop
    now”. No ask, nothing posted."""
    assert not _route(text).startswith("ASK"), (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text", ["request access to all their computers", "borrow all their machines",
                                  "ask to use all my computers"])
def test_router3_a_set_still_gets_one_owner_at_a_time(bridge, text):
    """A set is not somebody's ONE computer: the older capture's refusal still
    answers it (test_bulk_gate_0910), and nothing is posted."""
    assert _route(text).startswith("LINE:I ask one owner at a time"), (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text", ["ask for the Studio PC now", "ask for the Studio PC again",
                                  "request the Studio PC tonight", "apply for the Studio PC now",
                                  "ask for the Studio PC for today"])
def test_router3_the_older_capture_drops_the_join_s_tail_words(bridge, text):
    """⛔ `ask for the Studio PC now` asked about “Studio PC now”, and the yes found
    no such computer. The confirm names “Studio PC”, and the yes reaches it."""
    assert _route(text) == "ASK:Studio PC", (text, _route(text))
    _do(text)
    assert bridge.posts == []
    assert sr.cmd_device_ask(SimpleNamespace(device="Studio PC", json=False)) == 0
    assert bridge.posts == [("/device/ask", {"deviceId": "pub-studio"})]


# ── router-4: what the app says about signing in is a sign-in question ───────────

@pytest.mark.parametrize("text", [
    "am I logged into the mac app, it says I need to log in",
    "am I signed in to the desktop app, it shows I'm signed out",
    "are you logged in to the pc client, it shows the wrong account",
    "am I signed in to the Mac version, it says signed in",
    "am I signed in to the mac app, which shows my email?",
])
def test_router4_an_app_that_says_something_about_signing_in_answers_the_account(bridge, text):
    """⛔ Repair 4 read anything the app says after a comma as being about the
    computer, and these got the computer list (413e986: the sign-in line)."""
    assert _route(text) == "ACCOUNT", (text, _route(text))
    _do(text)
    assert bridge.posts == [] and bridge.gets == ["/status"], (text, bridge.gets)


@pytest.mark.parametrize("text", ["are you connected to my mac app, it shows as offline",
                                  "are you connected to my laptop app, it says that it's disconnected",
                                  "are you connected to my mac app, it says not connected"])
def test_router4_an_app_that_says_the_computer_is_unreachable_lists_the_computers(bridge, text):
    """K14 stands: offline / disconnected / not connected is about the computer."""
    assert _route(text) == "DEVICES", (text, _route(text))
    _do(text)
    assert bridge.posts == [] and bridge.gets == ["/devices"], (text, bridge.gets)


# ── router-5: a quoted setting name governed by a run verb is a run's title ──────

@pytest.mark.parametrize("text, want", [
    ("stop “auto-approve”", "STOP:auto-approve"), ("stop “allow all”", "STOP:allow all"),
    ("cancel “auto-approve”", "STOP:auto-approve"), ("end “allow all”", "STOP:allow all"),
    ("stop “auto-approve” please", "STOP:auto-approve"),
])
def test_router5_stopping_a_run_titled_like_the_setting_asks_to_stop_it(bridge, text, want):
    """⛔⛔ `stop “auto-approve”` POSTed Allow all OFF, unconfirmed, and the run the
    person named kept going. 413e986 asked to stop it; nothing is posted."""
    assert _route(text) == want, (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)
    assert bridge.out().startswith(_HEADS["stop"])


@pytest.mark.parametrize("text, want", [
    ("status of “allow all”", ["status", "allow all"]),
    ("what's the status of “Allow all”", ["status", "Allow all"]),
    ("podcast for “allow all”", ["podcast", "allow all"]),
    ("skip the podcast on “Allow all”", ["skip", "--run=Allow all", "podcast"]),
    ("pause “Allow all”", ["pause", "Allow all"]),
    ("resume “allow all”", ["resume", "allow all"]),
])
def test_router5_run_controls_on_a_run_titled_like_the_setting_reach_that_run(text, want):
    assert sr._nl_resolve(text) == (want, None), (text, sr._nl_resolve(text))


@pytest.mark.parametrize("text", ["turn off “Allow all”", "disable “Allow all”",
                                  'switch "Allow all" off', "turn off “allow all” for my mac",
                                  "stop “Allow all” on my mac", "pause “Allow all” for my mac"])
def test_router5_the_quoted_setting_itself_still_switches_off(bridge, text):
    """K8 stands: with no run verb, or with more after the quote than thanks, a
    quoted setting name is the setting."""
    assert _route(text) == "OFF", (text, _route(text))
    _do(text)
    assert bridge.posts == [_OFF_POST], (text, bridge.posts)


# ── router-6: `each request` is `each person`; `u` is `you` ──────────────────────

@pytest.mark.parametrize("text", ["go back to approving each request", "approve each request again",
                                  "go back to approving each request on my mac",
                                  "approve each request again on my mac",
                                  "approve each request myself from now on",
                                  "can u turn off allow all?", "could u turn off allow all for my mac?"])
def test_router6_approving_each_request_again_and_can_u_switch_off(bridge, text):
    """⛔ Repair 4 put `each request` with everyone/every request, which need
    `myself`; `approve each request again` reached the catch-all (413e986: OFF)."""
    assert _route(text) == "OFF", (text, _route(text))
    _do(text)
    assert bridge.posts == [_OFF_POST], (text, bridge.posts)


@pytest.mark.parametrize("text", ["can u sign me in and turn off allow all",
                                  "could u log me in and let anyone join my mac"])
def test_router6_can_u_sign_me_in_signs_in(bridge, text):
    """⛔ `can u …` read as a question, so the sign-in never started."""
    assert _route(text) == "LOGIN", (text, _route(text))
    _do(text)
    assert [p for p, _b in bridge.posts] == [_LOGIN_POST], (text, bridge.posts)


# ── router-7: a topic's quote comes off only with its partner ────────────────────

@pytest.mark.parametrize("text, topic", [
    ("research EV batteries on my mac “Allow All Lab”", "EV batteries on my mac “Allow All Lab”"),
    ("research “Allow All Lab” EV batteries on my mac", "“Allow All Lab” EV batteries on my mac"),
    ("research EV batteries “Allow All Lab”.", "EV batteries “Allow All Lab”"),
    ("research “EV batteries on my mac “Allow All Lab””", "EV batteries on my mac “Allow All Lab”"),
    ('research "tesla" and "ford"', '"tesla" and "ford"'),
    ("research “tesla”", "tesla"), ('research "tesla"', "tesla"), ("research tesla”", "tesla"),
    ("research the students'", "the students"),
])
def test_router7_the_run_s_title_keeps_a_quoted_name_whole(bridge, text, topic):
    """⛔ K17's own row started a paid run titled “EV batteries on my mac “Allow All
    Lab”: the closing quote was trimmed off, the opening one kept."""
    _do(text)
    assert bridge.posts == [("/research", {"topic": topic})], (text, bridge.posts)


# ── the rows earlier repairs pinned that this repair flips ───────────────────────
# ⛔ FLIPPED 2026-09-28 (wave 12 repair 5, router-2). Each was PINNED at the route in
# its third column (test_allow_all_repair4_0927 FLIPPED_R4 / K3, and
# test_allow_all_whole_message_0927 PINNED). Repair 4's own reason for the first
# ("an access code retyped without its dash is not guessed at, as `_NL_CAPS_CODE_RE`
# states for a code said alone") holds only for a code with NO digit — rule 1 pairs
# `K7XQ9B2M` said alone, and 413e986 paired it after `join`.
FLIPPED_R5 = [
    ("join K7XQ9B2M", "ADD:K7XQ9B2M", "CATCH", "a digit code without its dash, as rule 1 reads it"),
    ("join K7XQ–9B2M", "ADD:K7XQ–9B2M", "CATCH", "a phone's en dash is a dash"),
    ("can I borrow K7XQ-9B2M?", "CATCH", "ASK:K7XQ-9B2M", "a question never asks for a code"),
    ("borrow K7XQ-9B2M?", "CATCH", "ASK:K7XQ-9B2M", "a question never asks for a code"),
    ("my friend wants to borrow K7XQ-9B2M", "CATCH", "ASK:K7XQ-9B2M",
     "a statement never asks for a code"),
]


@pytest.mark.parametrize("text, want, was, why", FLIPPED_R5)
def test_repair5_flips_five_code_rows(text, want, was, why):
    assert _route(text) == want, (text, _route(text), why)


# ── the last check before the push (2026-09-28) ─────────────────────────────────
# ⛔⛔ paid-runs-1: a run whose TITLE holds Allow-all words could be started through
# `do` but never stopped, paused, resumed or retried — the Allow-all arm's
# read-only catch-all took the message first. Each row routes as it did at a3b4466.
_RUNCTL_ON_ALLOW_ALL_TITLES = [
    ("pause the auto-approve research", 'ARGV:["pause", "auto-approve"]'),
    ("stop the auto-approve run", "STOP:auto-approve"),
    ("resume the auto-approve run", 'ARGV:["resume", "auto-approve"]'),
    ("retry the auto-approve research", 'ARGV:["retry", "auto-approve"]'),
    ("stop the Teams auto-join meetings run", "STOP:Teams auto-join meetings"),
    ("pause the FDA drugs that require approval research",
     'ARGV:["pause", "FDA drugs that require approval"]'),
    ("stop the Slack channels that let anyone join run",
     "STOP:Slack channels that let anyone join"),
    ("cancel my auto-joining wifi research", "STOP:auto-joining wifi"),
    ("continue the paused run people joining without permission",
     'ARGV:["resume", "people joining without permission"]'),
]


@pytest.mark.parametrize("text, want", _RUNCTL_ON_ALLOW_ALL_TITLES)
def test_last_check_a_run_named_with_allow_all_words_can_be_controlled(text, want):
    assert _route(text) == want, (text, _route(text))


@pytest.mark.parametrize("text", ["stop the auto-approve run",
                                  "stop the Slack channels that let anyone join run"])
def test_last_check_stopping_such_a_run_asks_first_and_never_touches_allow_all(bridge, text):
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)
    assert "Stop “" in bridge.out()


# The setting itself is still the setting: a whole command, and no run word.
@pytest.mark.parametrize("text, want", [
    ("stop letting anyone join my mac", "OFF"),
    ("stop allow all on my mac", "OFF"),
    # ⛔ Windows review (09-28, owner-approved): "research computer" is the KIND —
    # it goes to the owned-computer picker, never looked up as a name.
    ("stop letting anyone join the research computer", "OFF"),
])
def test_last_check_the_setting_s_own_off_words_are_still_the_setting(text, want):
    assert _route(text) == want, (text, _route(text))


# ⛔ …and a message that is NOT a run control stays read-only, however it mentions
# a run or research: a verb straight on the setting, or "research computer".
@pytest.mark.parametrize("text", [
    "pause allow all on my mac so the run can finish",
    "stop letting anyone join the research computer and keep it listed",
    "stop letting people join my mac while the run is going",
    # "research computer / machine" is a computer, never a run's name
    "stop the research computer from letting anyone join",
    "pause the research machine so nobody can auto-join",
])
def test_last_check_a_setting_message_that_mentions_a_run_is_not_a_run_control(bridge, text):
    got = _route(text)
    assert not got.startswith(("STOP", 'ARGV:["pause"', 'ARGV:["resume"', 'ARGV:["retry"')), (text, got)
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


# ⛔ last-repair-1: `approve each request` with a from-now-on tail reads as the ON
# wish (K2's `approve every request going forward`) — never the unconfirmed OFF.
@pytest.mark.parametrize("text", ["just approve each request from now on",
                                  "approve each request going forward",
                                  "approve each request each time",
                                  "approve each request from now on for my mac"])
def test_last_check_approving_each_request_from_now_on_is_never_the_off_switch(bridge, text):
    assert not _route(text).startswith("OFF"), (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text", ["approve each request again",
                                  "go back to approving each request",
                                  "go back to approving each request from now on"])
def test_last_check_each_request_again_is_still_off(bridge, text):
    assert _route(text) == "OFF", (text, _route(text))
    _do(text)
    assert bridge.posts == [_OFF_POST], (text, bridge.posts)
