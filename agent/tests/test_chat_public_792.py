"""The chat surface for public computers: the three verbs, the routing rules that
had to go above two older ones, and the copy contract with the terminal
(wave 7.9-2, B2 / B3 / B4 / B8).

⛔⛔ A VERB WITH NO NATURAL-LANGUAGE ENTRY POINT REACHES THE CLI ONLY. Section B's
own header says "every surface"; without these rules it would be false, and the
fork's port in 7.9-7 would have nothing to carry over.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli
from tests.conftest import code_only

_SR_PATH = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"


def _load_sr():
    spec = importlib.util.spec_from_file_location("sr_public_792", _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()

ROW = {"deviceId": "dev-a1", "label": "Studio PC", "osFamily": "macos",
       "online": True, "full": False}
UNNAMED_A = {"deviceId": "dev-b2", "label": "Research computer", "osFamily": "linux",
             "online": False, "full": False}
UNNAMED_B = {"deviceId": "dev-c3", "label": "Research computer", "osFamily": "windows",
             "online": True, "full": False}


@pytest.fixture()
def chat(monkeypatch, capsys):
    gets: dict = {}
    posts: dict = {}
    calls: list = []

    def _get(path, timeout=None):
        calls.append(("GET", path, timeout))
        return gets.get(path, (200, {}))

    def _post(path, body=None, timeout=None):
        calls.append(("POST", path, body))
        return posts.get(path, (200, {}))

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    return SimpleNamespace(gets=gets, posts=posts, calls=calls,
                           out=lambda: capsys.readouterr().out)


def _ns(**kw):
    kw.setdefault("json", False)
    return SimpleNamespace(**kw)


# ── routing: the two rules that used to eat these phrasings ──────────────────

@pytest.mark.parametrize("said", [
    "show me public devices",
    "which devices can I ask for",
    "are there any public computers",
    "find me a public computer",
    "what public computers are available",
    "ask to use someone else's computer",
    "can I borrow a computer",
])
def test_browse_phrasings_reach_the_public_list(said):
    # ⛔⛔ MEASURED BEFORE THE RULE WAS WRITTEN: every one of these returned
    # ["devices"] — the account's OWN machines. A complete-looking answer to a
    # different question is worse than no answer.
    assert sr._nl_resolve(said)[0] == ["devices-public"], said


@pytest.mark.parametrize("said", [
    "what did I ask for",
    "any pending requests",
    "has the owner answered yet",
    "list my requests for other devices",
])
def test_waiting_phrasings_reach_the_requests_list(said):
    assert sr._nl_resolve(said)[0] == ["device-requests"], said


@pytest.mark.parametrize("said,name", [
    ("ask for the Studio PC", "Studio PC"),
    ("ask for dev-a1b2c3", "dev-a1b2c3"),
    ("request access to the Lab Mac", "Lab Mac"),
    ("ask to use the Lab Mac", "Lab Mac"),
    ("ask the owner of Studio PC for access", "Studio PC"),
])
def test_asking_for_a_named_machine_confirms_first(said, name):
    argv, lines = sr._nl_resolve(said)
    assert argv is None, said
    # ⛔⛔ CONFIRM-GATED THOUGH IT DESTROYS NOTHING. It is the only verb here that
    # hands the person's NAME AND EMAIL to a stranger, spends one of five asks an
    # hour, and arms a week-long refusal if the answer is no. Without this the
    # chat path is the one door into the feature with no consent moment at all.
    assert name in lines[0]
    assert "name and email" in lines[0]
    assert "they decide" in lines[0] or "owner" in lines[0]


def test_the_stop_rule_no_longer_eats_a_cancelled_request():
    # ⛔ MEASURED: "cancel my access request" produced “Stop “access request”? It
    # ends the run” — the person's own words quoted back as a research title.
    argv, lines = sr._nl_resolve("cancel my access request")
    assert argv is None
    assert "Stop" not in lines[0]
    assert "can’t be taken back" in lines[0]


def test_the_unlink_rule_no_longer_eats_a_withdrawn_request():
    # ⛔⛔ MEASURED, AND IT WAS A DESTRUCTIVE CONFIRM: "remove my request for the
    # Studio PC" produced “Unlink “request for the Studio PC”?”, because "PC"
    # satisfied its device noun. Say yes and it dead-ends on a device that never
    # existed.
    argv, lines = sr._nl_resolve("remove my request for the Studio PC")
    assert argv is None
    assert "Unlink" not in lines[0]
    assert "can’t be taken back" in lines[0]


def test_there_is_no_withdraw_and_the_answer_says_so():
    # ⛔ THE APP EXPOSES TWO OPERATIONS ON THIS COLLECTION — make one, list them.
    # Nothing cancels a filed request, so the honest answer is a dead end rather
    # than a verb that does something else.
    _argv, lines = sr._nl_resolve("withdraw my request")
    said = " ".join(lines).lower()
    assert "week" in said
    assert "cancel" not in said.replace("can’t", "")


@pytest.mark.parametrize("said,expected", [
    ("ask for the podcast", "podcast"),
    ("research iphone17 pricing", "research"),
    ("stop it", None),
    ("skip the video", "skip"),
    ("devices", "devices"),
    ("remove the old laptop", None),
    ("K7XQ-9B2M", "device-add"),
    ("what's the status", "status"),
    ("any updates?", "status"),
])
def test_the_new_rules_do_not_steal_the_old_ones(said, expected):
    argv, _lines = sr._nl_resolve(said)
    if expected is None:
        assert argv is None, said
    else:
        assert argv and argv[0] == expected, (said, argv)


@pytest.mark.parametrize("said", [
    "ask to use it",
    "request access to them",
    "ask to use one of them",
])
def test_a_pronoun_is_never_read_as_a_machine_name(said):
    # ⛔⛔ "ask to use it" IS THE CASE THE GUARD IS FOR, and the first version of
    # this test used "ask them to share it again" — which is stopped one check
    # earlier by not being about a machine at all, so the pronoun guard could be
    # deleted with the test still green. A mutant proved it.
    argv, lines = sr._nl_resolve(said)
    if argv is not None:
        assert argv[0] == "devices-public", (said, argv)
    else:
        assert "Ask the owner of “it”" not in lines[0]
        assert "Ask the owner of “them”" not in lines[0]


def test_our_own_advice_line_is_not_read_back_as_a_request():
    argv, lines = sr._nl_resolve("ask them to share it again")
    assert argv is None and "Ask the owner of" not in lines[0]


# ── the two live routing defects the measurement reproduced ──────────────────

def test_switching_to_a_code_shaped_name_is_not_a_pairing_attempt():
    # ⛔⛔ MEASURED: "switch to the machine LABPC001" resolved to
    # ["device-add", "LABPC001"] and came back "That code didn't match any
    # device" — a switch refused as a bad code. The rule's own comment claimed a
    # code inside a sentence could not hijack it; the device keyword WAS the
    # whole guard, and this sentence carried both.
    assert sr._nl_resolve("switch to the machine LABPC001")[0] == \
        ["device-use", "LABPC001"]


def test_a_bare_code_still_pairs():
    assert sr._nl_resolve("K7XQ-9B2M")[0] == ["device-add", "K7XQ-9B2M"]
    assert sr._nl_resolve("pair my PC, code is K7XQ-9B2M")[0] == \
        ["device-add", "K7XQ-9B2M"]


def test_the_phrasing_the_picker_tells_people_to_say_actually_routes():
    # ⛔ The picker ends every ask with 'Just say: use “<name>”.' — the one
    # phrasing this resolver did not route, so following the instruction on
    # screen reached "I didn't catch a Super Research request in that".
    argv, _ = sr._nl_resolve('use "Studio PC"')
    assert argv and argv[0] == "device-use"
    assert sr._nl_resolve("use less video")[0] is None


def test_a_quoted_name_survives_the_lookup(monkeypatch):
    # ⛔ AND ROUTING IT WAS ONLY HALF. `_resolve_device_arg` matched on name,
    # hostname and substring — none of which contains a quote mark — so the
    # quoted reply resolved to "No device matching".
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"devices": [{"id": "dev-a1", "name": "Studio PC"}]}))
    dev, fail = sr._resolve_device_arg('“Studio PC”')
    assert dev and dev["id"] == "dev-a1", fail


# ── the chat verbs ───────────────────────────────────────────────────────────

def test_chat_browse_prints_the_id_beside_every_row(chat):
    chat.gets["/devices/public"] = (200, {"devices": [ROW, UNNAMED_A],
                                          "truncated": False})
    assert sr.cmd_devices_public(_ns()) == 0
    out = chat.out()
    assert "dev-a1" in out and "dev-b2" in out
    assert "online" in out and "offline" in out
    assert "name and email" in out


def test_chat_browse_says_truncation_is_about_the_scan(chat):
    chat.gets["/devices/public"] = (200, {"devices": [ROW], "truncated": True})
    sr.cmd_devices_public(_ns())
    out = chat.out()
    assert "scan" in out and "next page" not in out


def test_chat_browse_empty_explains_why(chat):
    chat.gets["/devices/public"] = (200, {"devices": [], "truncated": False})
    assert sr.cmd_devices_public(_ns()) == 0
    assert "switches that on" in chat.out()


def test_chat_ask_resolves_an_exact_id_without_touching_names(chat):
    chat.gets["/devices/public"] = (200, {"devices": [UNNAMED_A, UNNAMED_B]})
    chat.posts["/device/ask"] = (200, {"ok": True, "status": "pending"})
    assert sr.cmd_device_ask(_ns(device="dev-c3")) == 0
    sent = [c for c in chat.calls if c[0] == "POST"][0]
    assert sent[2] == {"deviceId": "dev-c3"}


def test_chat_ask_refuses_to_guess_between_two_identical_public_names(chat):
    # ⛔⛔ PUBLIC LABELS COLLIDE BY DESIGN. A machine nobody has renamed is the
    # literal string "Research computer" for everybody, so a name match over a
    # list of them is a coin flip — and the coin decides whose computer gets a
    # request naming this person.
    chat.gets["/devices/public"] = (200, {"devices": [UNNAMED_A, UNNAMED_B]})
    assert sr.cmd_device_ask(_ns(device="Research computer")) == 1
    out = chat.out()
    assert "More than one" in out and "id" in out
    assert not [c for c in chat.calls if c[0] == "POST"]


def test_chat_ask_takes_a_unique_name(chat):
    chat.gets["/devices/public"] = (200, {"devices": [ROW, UNNAMED_A]})
    chat.posts["/device/ask"] = (200, {"ok": True})
    assert sr.cmd_device_ask(_ns(device="Studio PC")) == 0
    assert [c for c in chat.calls if c[0] == "POST"][0][2] == {"deviceId": "dev-a1"}


def test_chat_ask_says_nothing_runs_until_the_owner_agrees(chat):
    chat.gets["/devices/public"] = (200, {"devices": [ROW]})
    chat.posts["/device/ask"] = (200, {"ok": True})
    sr.cmd_device_ask(_ns(device="dev-a1"))
    out = chat.out()
    assert "owner decides" in out and "until they say yes" in out


def test_chat_requests_says_what_a_missing_row_means(chat):
    chat.gets["/devices/requests"] = (200, {"requests": [
        {"deviceId": "dev-a1", "deviceLabel": "Studio PC", "createdAt": 1}]})
    assert sr.cmd_device_requests(_ns()) == 0
    out = chat.out()
    assert "Studio PC" in out
    assert "leaves this list" in out


def test_chat_requests_says_it_on_the_empty_branch_too(chat):
    chat.gets["/devices/requests"] = (200, {"requests": []})
    sr.cmd_device_requests(_ns())
    out = chat.out()
    assert "not waiting on any computer" in out.replace("’", "'").replace(
        "You're", "you're").lower()
    assert "leaves this list" in out


@pytest.mark.parametrize("fn", ["cmd_device_requests"])
def test_no_chat_verb_calls_a_missing_request_a_refusal(fn):
    low = code_only(inspect.getsource(getattr(sr, fn))).lower()
    assert "denied" not in low and "refused" not in low and "said no" not in low


# ── the two clients must make the same claims ────────────────────────────────

def test_both_clients_word_the_same_refusal_codes():
    # ⭐ THE CLAIMS MATCH; THE VOICES DO NOT HAVE TO. `cli.py` carries no curly
    # apostrophes and this file is full of them, so a byte comparison would be
    # the wrong assertion — the SET of codes is the contract.
    assert set(cli._ASK_FAILURES) == set(sr._ASK_ERRORS)


def test_neither_client_reuses_the_pairing_sentences():
    # ⛔⛔ THREE CODES APPEAR IN BOTH TABLES AND MEAN DIFFERENT THINGS. Pairing's
    # `revoked_sharer` ends "ask them to share it again", which on the ask route
    # is exactly what is being refused.
    shared = set(sr._PAIR_ERRORS) & set(sr._ASK_ERRORS)
    assert shared, "if these stop overlapping this guard has lost its subject"
    for code in shared:
        assert sr._PAIR_ERRORS[code] != sr._ASK_ERRORS[code], code


@pytest.mark.parametrize("code", ["revoked_sharer", "recently_denied",
                                  "is_owner", "already_shared"])
def test_a_permanent_refusal_invites_no_retry_in_either_client(code):
    for said in (cli._ASK_FAILURES[code], sr._ASK_ERRORS[code]):
        low = said.lower()
        assert "try again" not in low
        assert "ask them" not in low
        assert "ask again" not in low or "can change" in low or "refused for" in low


def test_the_hour_ceiling_is_never_called_a_few_minutes():
    for line in (cli._ask_refusal("rate_limited"), sr._ask_refusal_line("rate_limited")):
        low = line.lower()
        assert "few minutes" not in low
        assert "hour" in low


def test_both_clients_round_a_sub_minute_wait_up():
    assert "1 minute" in cli._ask_refusal("rate_limited", 50_000)
    assert "1 minute" in sr._ask_refusal_line("rate_limited", 50_000)
    assert "0 minute" not in cli._ask_refusal("rate_limited", 50_000)


@pytest.mark.parametrize("junk", [None, True, "soon", -1, 0, [1]])
def test_a_junk_wait_names_no_number_at_all(junk):
    for line in (cli._ask_refusal("rate_limited", junk),
                 sr._ask_refusal_line("rate_limited", junk)):
        assert "minute" not in line, (junk, line)


# ── the skill document ───────────────────────────────────────────────────────

def _skill() -> str:
    return _SKILL.read_text(encoding="utf-8")


@pytest.mark.parametrize("verb", ["devices-public", "device-ask", "device-requests"])
def test_every_new_verb_has_a_row_and_a_real_subparser(verb):
    assert f"sr.py {verb}" in _skill(), verb
    ns = sr.build_parser().parse_args([verb] + (["x"] if verb == "device-ask" else []))
    assert callable(ns.func)


def test_the_skill_says_an_answered_request_leaves_the_list():
    # ⛔⛔ THE ONE FACT THE MODEL CANNOT INFER. `device-requests` returns rows with
    # no status at all; every absence looks identical. Without this line the
    # model's own summary of an empty list is a guess, and the likeliest guess is
    # "they said no".
    low = " ".join(_skill().lower().split())
    assert "leaves the list" in low and "either way" in low
    assert "never read a missing row as a refusal" in low


def test_the_skill_says_asking_discloses_the_person():
    low = " ".join(_skill().lower().split())
    assert "name + email" in low or "name and email" in low


def test_the_skill_no_longer_promises_it_cannot_reach_anyone_elses_data():
    # ⛔⛔ IT SAID "you cannot reach anyone else's data" — true until this wave and
    # false the moment browse lists other people's machines and an ask hands an
    # owner this person's name and address. A safety promise that has quietly
    # stopped being true is worse than none.
    low = " ".join(_skill().lower().split())
    assert "you cannot reach anyone else's data" not in low
    assert "public-computer list" in low


def test_the_skill_no_longer_says_sharing_is_owner_only_in_the_web_app():
    # ⛔ The parenthetical told the model that everything about sharing "stays
    # owner-only in the web app" — after this wave the ASKER's half is right
    # here, and a model reading that line would refuse the verbs it now has.
    low = " ".join(_skill().lower().split())
    assert "sharing a device with other people, revoking sharers, and resets stay owner-only" not in low
    assert "asking to use somebody else's public computer" in low


def test_the_capability_line_the_fallback_prints_names_the_new_surface():
    # ⛔ IT IS WHAT SOMEBODY READS AFTER A PHRASING THIS RESOLVER COULD NOT PLACE,
    # so a verb missing from it is a verb the fallback denies having.
    _argv, lines = sr._nl_resolve("zzzz not a request zzzz")
    assert "public computer" in lines[0]


def test_the_intro_enumeration_lists_the_new_surface():
    low = " ".join(_skill().lower().split())
    assert "find a public one and ask its owner for access" in low


# ── the flag list the closed wave's harness pins ─────────────────────────────

def test_the_new_rules_route_no_flags():
    # ⛔⛔ `_DO_FLAGS` IS UNTOUCHED ON PURPOSE. Three anchors in a CLOSED wave's
    # harness pin that line verbatim, and a stale anchor is a hard red on the
    # backend suite's ratchet — not a survivor. Every object here is a
    # POSITIONAL, which is also what the store_true rule requires.
    assert sr._DO_FLAGS == frozenset({"--no-video", "--no-email", "--machine",
                                      "--agent-log"})
    # ⛔ SLICED ON CODE, NOT ON THE COMMENT HEADINGS. `code_only` blanks comments
    # — which is the point of it — so a slice keyed on "2d. PUBLIC COMPUTERS"
    # finds nothing and the guard dies with a ValueError instead of an assertion.
    # It did exactly that on the first run of this test.
    src = code_only(inspect.getsource(sr._nl_resolve))
    start = src.index("_public_kw = re.search(")
    end = src.index('r"\\b(stop|end|abort|cancel)\\b"')
    block = src[start:end]
    assert "devices-public" in block and "device-requests" in block, \
        "the slice lost its own subject"
    assert not re.findall(r'"(--[a-z-]+)"', block), "a routed flag must be in _DO_FLAGS"


def test_an_unrecognised_refusal_code_is_relayed_and_invites_nothing():
    # ⛔⛔ THE FALLBACK IS WHERE THE PAIRING TABLE CREPT BACK IN. A mutant that
    # replaced the unknown-code branch with pairing's `revoked_sharer` sentence
    # survived every guard in this file: each of them names a code that IS in the
    # table, so none of them ever reached the branch. An unknown code has to
    # relay the code and promise nothing.
    for said in (cli._ask_refusal("some_new_code_the_app_grew"),
                 sr._ask_refusal_line("some_new_code_the_app_grew")):
        assert "some_new_code_the_app_grew" in said
        low = said.lower()
        assert "ask them" not in low and "try again" not in low
        assert "share it again" not in low


def test_an_empty_refusal_code_still_says_something():
    for said in (cli._ask_refusal(""), sr._ask_refusal_line("")):
        assert len(said.strip()) > 15 and "None" not in said


def test_the_skill_ask_row_is_confirm_gated():
    # ⛔⛔ THE ROW IS THE ONLY THING THAT TELLS THE ASSISTANT TO ASK FIRST. The
    # client cannot enforce it — `sr.py device-ask` fires immediately — so a row
    # that loses its **confirm** is a request naming the person, sent to a
    # stranger, with nobody having agreed to it.
    row = next(ln for ln in _skill().splitlines() if "sr.py device-ask" in ln)
    assert "**confirm**" in row
    assert "name + email" in row or "name and email" in row


def test_the_skill_keeps_the_row_for_the_thing_that_cannot_be_done():
    # ⛔ Without it the assistant improvises an answer to "cancel my request" for
    # an operation the product does not have — and the two nearest verbs it could
    # improvise with are an unlink and a run-stop.
    low = " ".join(_skill().lower().split())
    assert "nothing withdraws a request" in low
