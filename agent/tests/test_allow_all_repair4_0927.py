"""The chat's message reading, single-site repairs (wave 12 repair 4, 2026-09-27).

Round 4 of cross-verify, driven through `sr.py do` with the bridge stubbed at repair
3 (413e986):

  K2  `just approve everyone from now on` / `approve every request going forward`
      switched Allow all OFF, unconfirmed — the OFF row read the ON wish.
  K3  `ask to use Studio22` and `request access to “Studio22”` PAIRED a computer's
      name; `status of support request AB12CD34` paired the support code; `can I
      borrow K7XQ-9B2M?` and `my friend wants to borrow K7XQ-9B2M` paired.
  K4  `research why my laptop keeps auto-joining public wifi` got the Devices list.
  K5  `look into why people join my mac without my permission` POSTed /research.
  K6  `turn off the auto-approve for my mac` looked for a computer called
      “auto-approve for my mac”.
  K7  `turn off allow all on the lab pc and mac` switched off the Lab PC alone.
  K8  `turn off “Allow all”` — the catch-all's own suggestion, quoted — got the
      catch-all again; `switch "Allow all" off` HID a computer called “Allow all”.
  K11 `join the Studio PC to sign in` asked about “Studio PC to sign in”.
  K13 `join the Studio PC again` asked about “Studio PC again”.
  K14 `are you connected to my mac mini app, it says it's offline` answered
      “✓ Signed in as …” alone (the owner's Windows rule 2).
  K17 `research EV batteries on my mac “Allow All Lab”` got the Devices list.
  K18 `can people join my mac without a login?` started a sign-in.

Each is pinned by EXECUTION: the router (`sr._nl_resolve`) AND the `do` path with
`_get`/`_post` stubbed, asserting the POSTs a message makes — or that it makes none.
The mutants are in .mutants/wave12_repair4_router_mutants.py.
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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_repair4_0927", _SCRIPTS / "sr.py")

_HEADS = {key: sr._NL_CONFIRMS[key].split("{name}")[0]
          for key in ("device-allow-all", "device-ask", "device-visibility",
                      "device-approve", "device-deny", "stop")}
_TAG = {"device-allow-all": "ON", "device-ask": "ASK", "device-visibility": "PUBLISH",
        "device-approve": "APPROVE", "device-deny": "DENY", "stop": "STOP"}


def _route(text: str) -> str:
    """OFF[:name], ON[:name], HIDE[:name], DEVICES, PUBLIC, LOGIN, ADD:<code>,
    ASK[:name], CATCH, SET, RESEARCH, ACCOUNT, ARGV:…, LINE:…"""
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
    if said.startswith("I switch Allow all one computer at a time"):
        return "SET"
    return "LINE:" + said[:60]


# ── the `do` path, with the bridge stubbed ───────────────────────────────────────

_MY_MAC = {"id": "dev-mac", "name": "My Mac", "owned": True, "visibility": "public",
           "allowAll": True}
_LAB_PC = {"id": "dev-lab", "name": "Lab PC", "owned": True, "visibility": "public",
           "allowAll": True}
_PUBLIC = {"devices": [{"deviceId": "pub-studio", "label": "Studio PC", "online": True,
                        "allowAll": True}]}


@pytest.fixture()
def bridge(monkeypatch, capsys):
    """“My Mac” owned and letting anyone join (Allow all ON — the case where an
    unconfirmed OFF changes something), one public “Studio PC”. Every GET and POST
    is recorded. ⛔ The watcher arm is stubbed: `login` would otherwise write cron."""
    posts: list = []
    gets: list = []
    state = SimpleNamespace(owned=[dict(_MY_MAC)], ask_reply=(200, {"ok": True, "status": "pending"}))

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
            return state.ask_reply
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


# ── K2: everyone / every request is OFF only with `myself` ───────────────────────

_K2_NOT_OFF = ["just approve everyone from now on", "approve every request going forward",
               "approve everyone each time", "go back to approving everyone",
               "approve everybody going forward", "approve everyone again",
               "go back to approving every request", "approve every person going forward"]
_K2_OFF = ["approve everyone myself", "approve everyone myself on my mac",
           "go back to approving everyone myself", "approve people again",
           "approve people from now on", "go back to approving people",
           "approve each person again", "approve people on my mac again"]


@pytest.mark.parametrize("text", _K2_NOT_OFF)
def test_k2_approving_everyone_from_now_on_is_never_the_off_switch(bridge, text):
    """⛔⛔ The OFF row read `everyone` beside `from now on` as "back to approving",
    and `just approve everyone from now on` — the ON wish — switched Allow all OFF
    with no confirm. Read-only now, and `do` posts nothing."""
    assert _route(text) in ("CATCH", "DEVICES"), (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text", _K2_OFF)
def test_k2_approving_people_again_and_everyone_myself_stay_off(bridge, text):
    assert _route(text) == "OFF", text
    _do(text)
    assert bridge.posts == [_OFF_POST], (text, bridge.posts)


# ── K3: a code after an ask verb pairs only as the whole message ─────────────────

_K3_NOT_A_PAIRING = [
    ("ask to use Studio22", "ASK:Studio22"),
    ("borrow Studio22", "ASK:Studio22"),
    ("request access to “Studio22”", "ASK:Studio22"),
    ('request access to "Studio22"', "ASK:Studio22"),
    ("borrow “K7XQ-9B2M”", "ASK:K7XQ-9B2M"),
    ("borrow tech-debt", "ASK:tech-debt"),
    ("status of support request AB12CD34", 'ARGV:["status", "support request AB12CD34"]'),
    # ⛔ FLIPPED 2026-09-28 (wave 12 repair 5, router-2): a question or a statement
    # naming an unquoted code is no ask either — the ask's yes posts the code as a
    # device id (H17). Each was "ASK:K7XQ-9B2M"; test_allow_all_repair5_0928 FLIPPED_R5.
    ("can I borrow K7XQ-9B2M?", "NOT_ASK_OR_ADD"),
    ("borrow K7XQ-9B2M?", "NOT_ASK_OR_ADD"),
    ("my friend wants to borrow K7XQ-9B2M", "NOT_ASK_OR_ADD"),
]
_K3_PAIRS = [("borrow K7XQ-9B2M", "K7XQ-9B2M"), ("request access to K7XQ-9B2M", "K7XQ-9B2M"),
             ("ask for K7XQ-9B2M", "K7XQ-9B2M"), ("ask to use K7XQ-9B2M", "K7XQ-9B2M"),
             ("please let me join K7XQ-9B2M", "K7XQ-9B2M"), ("borrow WDJB-MJHT", "WDJB-MJHT"),
             ("borrow k7xq-9b2m", "k7xq-9b2m"), ("join K7XQ-9B2M now", "K7XQ-9B2M")]


@pytest.mark.parametrize("text, want", _K3_NOT_A_PAIRING)
def test_k3_a_name_a_question_or_a_statement_is_never_paired(bridge, text, want):
    """⛔⛔ Repair 3 read the code from a capture that searched ANYWHERE, before every
    guard: a computer's name (`Studio22`, quoted or not), a support code in a status
    question, a question and a third person all POSTed /device/pair — spending one
    of the claim route's tries, and with nothing saved the pairing could pick the
    stranger's computer. None of them pairs; `do` posts nothing (an ask confirm
    only asks)."""
    got = _route(text)
    if want == "NOT_ASK_OR_ADD":
        assert not got.startswith(("ASK", "ADD")), (text, got)
    else:
        assert got == want, (text, got)
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text, code", _K3_PAIRS)
def test_k3_a_whole_message_ask_on_a_code_still_pairs(bridge, text, code):
    """H17 stays fixed: the whole message, an unquoted code in the access code's
    shape (any case once it has a digit) or the connection code's."""
    assert _route(text) == f"ADD:{code}", text
    _do(text)
    assert bridge.posts == [("/device/pair", {"code": code})], (text, bridge.posts)


# ── K4 / K5 / K17: a research verb, and the person's own Allow all ───────────────

_K4_RESEARCH = [
    "research why my laptop keeps auto-joining public wifi",
    "research why my phone keeps auto-joining public wifi",
    "research why my laptop auto-accepts every update",
    "research how my laptop lets everyone in on the guest network",
    "research why my phone lets anyone join without approval",
    "research how to join my laptop to a domain",
    # K5: replaces repair 3's EV-market row, which passed under every D mutant — this
    # one measures the clause boundary (the person's computer across a comma)
    "research on my mac, how companies let anyone join Slack",
    # K17: a quoted name at the end of the topic is a name, not the setting
    "research EV batteries on my mac “Allow All Lab”",
    "research “Allow All Lab” EV batteries on my mac",
    "research why companies let anyone join their Slack",
    "research how to let anyone join a Slack workspace from my laptop",
    # ⚠ ADDED 2026-09-28 (wave 12 repair 5): repair 5 made the machine word END the
    # people-join phrase, so the domain row above no longer measures K4c (nobody
    # joining); this one ends on `without`. And a topic's quote now comes off only
    # with its partner, so the EV row no longer measures K17; a topic quoted WHOLE
    # does — its quotes come off, and only the blanking before that keeps it a topic.
    "research how to join my laptop without admin rights",
    "research “how Allow All Lab uses my laptop”",
]
_K5_OWN = [
    "look into why people join my mac without my permission",
    "look into why people join my mac",
    "research why strangers keep joining my mac",
    "investigate why my mac won't let anyone join",
    "look into why nobody can join my mac",
    "research whether allow all is safe for my mac",
    "research whether auto-approve is safe on my mac",
    "look into why my mac joins at once",
]


@pytest.mark.parametrize("text", _K4_RESEARCH)
def test_k4_k17_a_topic_about_wifi_a_phone_or_a_quoted_name_is_research(bridge, text):
    """⛔ K4: the veto counted every `_AA_MENTION` word — auto-join, auto-accept, let
    everyone in — beside the person's laptop or phone, and a paid run's topic got
    the Devices list with no reason given. ⛔ K17: `…on my mac “Allow All Lab”` lost
    its closing quote before the name was blanked. `do` POSTs the run."""
    assert _route(text) == "RESEARCH", (text, _route(text))
    _do(text)
    assert [p for p, _b in bridge.posts] == ["/research"], (text, bridge.posts)


@pytest.mark.parametrize("text", _K5_OWN)
def test_k5_the_person_s_own_computer_inside_the_words_is_never_a_paid_run(bridge, text):
    """⛔⛔ K5: `people join my mac without my permission` swallowed “my mac”, so
    nothing sat BESIDE the phrase and `do` POSTed /research — a paid run about the
    person's own setting. Their list, and nothing posted."""
    assert _route(text) == "DEVICES", (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)
    assert "/devices" in bridge.gets


# ── K6: the setting's name is not the computer's ─────────────────────────────────

@pytest.mark.parametrize("text, want", [
    ("turn off the auto-approve for my mac", "OFF"),
    ("turn off the auto-join for my mac", "OFF"),
    ("turn off the auto-accept on my mac", "OFF"),
    ("turn off the auto-approve on the office pc", "OFF:office pc"),
])
def test_k6_the_auto_approve_is_the_setting_not_a_computer_name(bridge, text, want):
    """⛔ `turn off the auto-approve for my mac` replied 'No device matching
    “auto-approve for my mac”' and Allow all stayed on."""
    assert _route(text) == want
    if want == "OFF":
        _do(text)
        assert bridge.posts == [_OFF_POST], (text, bridge.posts)


# ── K7: two computers are never one ──────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "turn off allow all on the lab pc and mac",
    "turn off allow all on the lab pc or mac",
    "turn off allow all on my laptop and mac",
    "turn off allow all on the office and lab pc",
    "stop letting anyone join the lab pc and mac",
    "let anyone join the lab pc or the mac",
])
def test_k7_a_subject_naming_two_computers_is_read_only(bridge, text):
    """⛔⛔ W5's retirement was false: `the <name> <machine>` took `and` as a filler
    word, so `…the lab pc and mac` fullmatched and the SHORTEST subject was read
    back — only the Lab PC was switched off and the Mac stayed open. Read-only now,
    on an account that owns both."""
    bridge.owned = [dict(_MY_MAC), dict(_LAB_PC)]
    assert _route(text) == "DEVICES", (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


def test_k7_one_named_computer_still_switches(bridge):
    bridge.owned = [dict(_MY_MAC), dict(_LAB_PC)]
    assert _route("turn off allow all on the lab pc") == "OFF:lab pc"
    _do("turn off allow all on the lab pc")
    assert bridge.posts == [("/device/visibility", {"deviceId": "dev-lab", "allowAll": False})]


# ── K8: a quoted setting name is the setting ─────────────────────────────────────

@pytest.mark.parametrize("text, want", [
    ("turn off “Allow all”", "OFF"), ('turn off "Allow all"', "OFF"),
    ('switch "Allow all" off', "OFF"), ("switch “Allow all” off on my mac", "OFF"),
    ("turn off “allow all” for my mac", "OFF"),
    ("“turn off Allow all”", "OFF"), ("“turn off Allow all”.", "OFF"),
    ("“turn on Allow all”", "ON"), ('"turn on Allow all"', "ON"),
    ("turn on “Allow all”", "ON"), ("turn on “Allow all” for my mac", "ON"),
    ("turn off “Allow all” on “Studio PC”", "OFF:Studio PC"),
    # not a whole command: read-only — never the hide that took `…but keep it listed`
    ("turn off “Allow all” for my mac but keep it listed", "DEVICES"),
    ("hide my mac and turn off “Allow all”", "DEVICES"),
    ("is “Allow all” on?", "DEVICES"),
])
def test_k8_a_quoted_setting_name_is_the_setting(bridge, text, want):
    assert _route(text) == want, (text, _route(text))
    _do(text)
    if want == "OFF":
        assert bridge.posts == [_OFF_POST], (text, bridge.posts)
    else:
        assert bridge.posts == [], (text, bridge.posts)


def test_k8_the_catch_all_s_own_suggestions_never_loop():
    """⛔⛔ The catch-all names the two phrasings that work, in quotes — and pasted
    back WITH the quotes (or with the setting's name quoted) they got the same
    catch-all. Each suggestion is executed three ways."""
    said = re.findall(r"“([^”]+)”", sr._NL_CATCH_ALL)
    assert said == ["turn on Allow all", "turn off Allow all"], said
    for s in said:
        want = "ON" if " on " in f" {s} " else "OFF"
        for text in (s, f"“{s}”", f'"{s}"', s.replace("Allow all", "“Allow all”")):
            assert _route(text) == want, (text, _route(text))


# ── K11: a sign-in beside a join is a sign-in ────────────────────────────────────

@pytest.mark.parametrize("text", ["join the Studio PC to sign in", "sign in to join the Studio PC",
                                  "join the Studio PC and log me in"])
def test_k11_signing_in_to_join_starts_the_sign_in_only(bridge, text):
    """⛔ F21's retirement was false: `join the Studio PC to sign in` is a
    whole-message join, and it asked about “Studio PC to sign in”."""
    assert _route(text) == "LOGIN", (text, _route(text))
    _do(text)
    assert [p for p, _b in bridge.posts] == [_LOGIN_POST], (text, bridge.posts)


# ── K13: the join's name, trimmed; one computer ──────────────────────────────────

@pytest.mark.parametrize("text", [
    "join the Studio PC again", "join the Studio PC tonight", "join the Studio PC tomorrow",
    "join the Studio PC instead", "join the Studio PC too", "join the Studio PC later",
    "join the Studio PC via the web", "join the Studio PC for today",
    "join the Studio PC again now", "join the computer called Studio PC",
    "join the computer named Studio PC", "join a pc called Studio PC",
])
def test_k13_the_asked_name_is_the_computer_the_list_names(bridge, text):
    """⛔ `join the Studio PC again` asked about “Studio PC again”, and the yes — run
    as SKILL.md says — found no such computer. The confirm names “Studio PC”, and
    the yes reaches it."""
    assert _route(text) == "ASK:Studio PC", (text, _route(text))
    _do(text)
    assert bridge.posts == []
    assert sr.cmd_device_ask(SimpleNamespace(device="Studio PC", json=False)) == 0
    assert bridge.posts == [("/device/ask", {"deviceId": "pub-studio"})]


def test_k13_a_quoted_name_after_called_is_taken_verbatim():
    assert _route("join a pc called “DG shared”") == "ASK:DG shared"


@pytest.mark.parametrize("text", ["join your Studio PC", "join his Studio PC", "join their Studio PC",
                                  "join these Studio PCs", "join the Studio PCs", "join those macs"])
def test_k13_somebody_s_computer_or_a_set_is_not_one_ask(bridge, text):
    assert not _route(text).startswith("ASK"), (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


# ── K14: the owner's Windows rule 2 ──────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "are you connected to my mac mini app, it says it's offline",
    "are you connected to my mac mini app but it says offline",
    "are you connected to my mac mini app, but it says it's offline",
    "are you connected to my mac app, which says offline",
    "are you connected to my mac mini app says it's offline",
])
def test_k14_an_app_that_says_the_computer_is_offline_lists_the_computers(bridge, text):
    """⛔ "…my mac mini app, it says it's offline" answered "✓ Signed in as …" alone,
    which reads as "yes, your Mac is connected"."""
    assert _route(text) == "DEVICES", (text, _route(text))
    _do(text)
    assert bridge.posts == [] and bridge.gets == ["/devices"], (text, bridge.gets)


@pytest.mark.parametrize("text", ["am I signed in to the desktop app, and is it fast?",
                                  "am I signed in to the mac app, is it working?",
                                  "are you connected to my mac mini app?"])
def test_k14_a_second_question_about_the_app_is_still_about_the_app(bridge, text):
    """Only what the app SAYS makes it about the computer (9ac9abf's rows stay)."""
    assert _route(text) == "ACCOUNT", (text, _route(text))
    _do(text)
    assert bridge.posts == [] and bridge.gets == ["/status"], (text, bridge.gets)


# ── K18: a question that mentions a login is a question ──────────────────────────

@pytest.mark.parametrize("text", ["can people join my mac without a login?",
                                  "can people join my mac without a login",
                                  "people can join my mac without a login?",
                                  "do people need a login to join my mac?",
                                  "how do I sign in and turn off allow all?"])
def test_k18_a_question_mentioning_a_login_never_starts_one(bridge, text):
    assert _route(text) == "DEVICES", (text, _route(text))
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)


@pytest.mark.parametrize("text", ["sign in and turn off allow all",
                                  "login and let anyone join my mac",
                                  "turn on allow all and sign me in",
                                  "can you sign me in and turn off allow all?",
                                  "will you sign me in and let anyone join my mac"])
def test_k18_an_instruction_to_sign_in_still_signs_in(bridge, text):
    assert _route(text) == "LOGIN", (text, _route(text))
    _do(text)
    assert [p for p, _b in bridge.posts] == [_LOGIN_POST], (text, bridge.posts)


# ── the two rows repair 3 pinned that this repair flips ──────────────────────────
# ⛔ FLIPPED 2026-09-27 (wave 12 repair 4, K3) — each was in
# test_allow_all_whole_message_0927 PINNED at the route in its third column.
# A code after an ask verb pairs only as an UNQUOTED token in the access code's
# dashed shape (or the connection code's): a quoted token is a name (it asks), and
# an access code retyped without its dash is not guessed at — the same rule
# `_NL_CAPS_CODE_RE` states for a code said alone (base a3b4466: the catch-all).
# ⛔ `join K7XQ9B2M` (→ CATCH here) FLIPPED BACK 2026-09-28 (wave 12 repair 5,
# router-2): a code WITH a digit pairs without its dash — rule 1 pairs it said
# alone, SKILL.md allows it, and 413e986 paired it after `join`. The dash rule above
# holds for a code with no digit. test_allow_all_repair5_0928 FLIPPED_R5.
FLIPPED_R4 = [
    ('join "K7XQ-9B2M"', "ASK:K7XQ-9B2M", "ADD:K7XQ-9B2M", "K3: a quoted token is a name"),
]


@pytest.mark.parametrize("text, want, was, why", FLIPPED_R4)
def test_repair4_flips_a_code_row_and_it_does_not_pair(bridge, text, want, was, why):
    assert _route(text) == want, (text, _route(text), why)
    _do(text)
    assert bridge.posts == [], (text, bridge.posts)
