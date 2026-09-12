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
    "has the owner answered my request",
    "list my requests for other devices",
    "am I still waiting for that computer",
])
def test_waiting_phrasings_reach_the_requests_list(said):
    assert sr._nl_resolve(said)[0] == ["device-requests"], said


@pytest.mark.parametrize("said", [
    "still waiting for the podcast",
    "waiting for the report",
    "has anyone answered my email",
])
def test_the_waiting_rule_needs_its_own_subject(said):
    # ⛔⛔ A BARE "waiting for …" ANSWERED EVERY RUN-PROGRESS QUESTION with
    # "You're not waiting on any computer." The clause sits above the status and
    # phase rules, so with no subject of its own it took all of theirs.
    # Cross-verify found it after the wave was green.
    argv, _lines = sr._nl_resolve(said)
    assert argv != ["device-requests"], said


@pytest.mark.parametrize("said,name", [
    ("ask for the Studio PC", "Studio PC"),
    ("ask for the Studio PC please", "Studio PC"),
    ("ask for dev-a1b2c3", "dev-a1b2c3"),
    ("request access to the Lab Mac", "Lab Mac"),
    ("request access to that Mac", "Mac"),
    ("request access to computer LABPC001", "LABPC001"),
    ("ask to use the Lab Mac", "Lab Mac"),
    ("ask the owner of Studio PC for access", "Studio PC"),
    ("ask for access to the studio pc", "studio pc"),
])
def test_asking_for_a_named_machine_confirms_first(said, name):
    argv, lines = sr._nl_resolve(said)
    assert argv is None, said
    # ⛔⛔ CONFIRM-GATED THOUGH IT DESTROYS NOTHING. It is the only verb here that
    # tells somebody else who the user is, spends one of five asks an hour, and
    # arms a week-long refusal if the answer is no. Without this the chat path is
    # the one door into the feature with no consent moment at all.
    #
    # ⛔⛔ AND THE NAME IS THE MACHINE'S, NOT THE SENTENCE'S. "ask for access to
    # the studio pc" produced “access to the studio pc” — a computer that cannot
    # exist, quoted in a request to disclose somebody, whose follow-up then
    # dead-ended on it. Cross-verify found it; so did the trailing "please".
    assert f"“{name}”" in lines[0], lines[0]
    assert "they decide" in lines[0] or "They decide" in lines[0]


def test_the_consent_question_carries_all_three_disclosures():
    # ⛔⛔ THE FIRST VERSION SAID "your name and email address" AND THAT IS WRONG
    # TWICE. The owner sees the name, and the email only when no name is set
    # (`requesterLabelOf`) — and it left out the two facts that cost the reader
    # most, which the web app puts FIRST: the research runs on somebody else's
    # computer using their paid AI accounts, and that computer can read the
    # research in this account.
    _argv, lines = sr._nl_resolve("ask for the Studio PC")
    said = lines[0]
    assert "their computer" in said and "their ChatGPT" in said
    assert "read the research in your account" in said
    assert "or your email, if you haven’t set one" in said
    assert "name and email address" not in said


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
    # ⛔⛔ THE ARTEFACT GUARD IS ONLY OBSERVABLE WITH A MACHINE WORD IN THE SAME
    # MESSAGE. "ask for the podcast" alone is stopped one check earlier by not
    # being about a machine at all, so the guard could be deleted with the test
    # still green — a mutant proved it. This phrasing needs the guard.
    ("ask for the podcast on my computer", "podcast"),
    ("ask for the podcast from that machine", "podcast"),
    ("ask for an update on my machine", "status"),
    # ⛔ AND THE BROWSE CLAUSE'S BAILS ARE ONLY OBSERVABLE HERE: a run control
    # that mentions a public machine reached the browse list when the bail was
    # removed, and no other case in this file could see it.
    ("stop the run on the public computer", None),
    ("pause the run on the shared machine", "pause"),
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
    # ⛔⛔ THIS ASSERTION PINNED THE WRONG CLAIM FOR TWO WAVES. Its sibling
    # `test_the_consent_question_carries_all_three_disclosures` forbids "name and
    # email address" BY NAME as wrong twice — the owner sees the name, and the
    # email only when no name is set — and this line demanded it on the screen
    # where somebody decides whether to ask at all. One claim, both screens.
    assert "or your email, if you haven’t set one" in out
    assert "name and email address" not in out


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
    # ⛔ 7.9-3: the row now says WHICH HALF it is about, because the owner's queue
    # sits above it and loses a row for entirely different reasons. The fact
    # being pinned is unchanged.
    low = " ".join(_skill().lower().split())
    assert "leaves that half" in low and "either way" in low
    assert "never read a missing row as a refusal" in low
    assert "of the ones the user asked for" in low, (
        "the row must say which half it describes now that both are printed")


def test_the_skill_says_asking_discloses_the_person():
    low = " ".join(_skill().lower().split())
    # ⛔ THE SAME CORRECTION AS THE CLIENT'S. "name + email" was wrong: the owner
    # sees the name, or the email only when there is no name.
    assert "email, if no name is set" in low or "email if no name is set" in low
    assert "their ai accounts" in low or "their computer using their ai accounts" in low


def test_the_skill_no_longer_promises_it_cannot_reach_anyone_elses_data():
    # ⛔⛔ IT SAID "you cannot reach anyone else's data" — true until this wave and
    # false the moment browse lists other people's machines and an ask hands an
    # owner this person's name and address. A safety promise that has quietly
    # stopped being true is worse than none.
    # ⛔ 7.9-3: what reaches past the account went from ONE thing to THREE, so the
    # positive half names all three. Asserted positively for the reason 7.9-2
    # recorded: "the false promise is absent" is satisfied by deleting the whole
    # bullet, and a mutant proved that.
    low = " ".join(_skill().lower().split())
    assert "you cannot reach anyone else's data" not in low
    assert "three things reach past it" in low
    for reach in ("**asking**", "**answering**", "**publishing**"):
        assert reach in low, reach


def test_the_skill_no_longer_says_sharing_is_owner_only_in_the_web_app():
    # ⛔ The parenthetical told the model that everything about sharing "stays
    # owner-only in the web app" — after this wave the ASKER's half is right
    # here, and a model reading that line would refuse the verbs it now has.
    # ⛔⛔ 7.9-3 WENT FURTHER AND THE OLD ASSERTION WOULD NOW ENSHRINE A LIE. The
    # parenthetical used to grant the ASKER's half and reserve everything else to
    # the web app; this wave brought two of those reserved verbs here, so what it
    # must not say has grown, and the sentence it must contain has changed.
    low = " ".join(_skill().lower().split())
    assert "sharing a device with other people, revoking sharers, and resets stay owner-only" not in low
    assert "approving or refusing somebody, offering a computer publicly" not in low, (
        "the greeting still reserves approve/publish to the web app — the model "
        "would refuse the verbs it now has")
    assert "answer the people asking" in low
    assert "set whether strangers can find it" in low
    # ⛔⛔ HALF OF THIS STOPPED BEING TRUE IN 7.9-5, and the identical assertion
    # stood in `test_chat_owner_793.py` — two files pinning one sentence, which
    # is how the sentence outlived the fact. Revoking ONE sharer is still
    # web-app only. "Resetting a pair code" is not the whole story any more: an
    # owner-unlink from chat rotates the machine's code and hands the new one
    # back. Reset itself is still the web app's, and that is what is pinned.
    assert "revoking one sharer stays in the web app" in low
    assert "unlinking their own machine issues it a new pair code" in low
    assert "resetting a pair code stay in the web app" not in low


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
    # ⛔⛤ `--run` JOINED IN WAVE 1.2. A person could not skip a phase of any run but
    # the newest active one, from chat, at all — nineteen phrasings dropped the
    # name. It is the first routed flag that carries a VALUE, which is why it is
    # emitted as one `--run=<name>` token; see the picker suite for that invariant.
    assert sr._DO_FLAGS == frozenset({"--no-video", "--no-email", "--machine",
                                      "--agent-log", "--run"})
    # ⛔ SLICED ON CODE, NOT ON THE COMMENT HEADINGS. `code_only` blanks comments
    # — which is the point of it — so a slice keyed on "2d. PUBLIC COMPUTERS"
    # finds nothing and the guard dies with a ValueError instead of an assertion.
    # It did exactly that on the first run of this test.
    src = code_only(inspect.getsource(sr._nl_resolve))
    # ⛔ THE START ANCHOR MOVED ON 09-11, AND THE GUARD'S SUBJECT DID NOT. Wave 1.1
    # made `_public_kw` a parenthesised OR — polarity is computed now, not
    # collected — so the literal gained one character. The slice still has to open
    # at the public-computer block, which is what the two asserts below check.
    start = src.index("_public_kw = (re.search(")
    # ⛔ THE END ANCHOR MOVED ON 09-11 TOO. Wave 1.2 folded the three spellings of
    # the stop-verb list into one constant, so the literal this looked for is gone.
    # A stale anchor here does not fail loudly — `.index` raises, which is why the
    # guard above exists — but the SLICE is the subject, not the literal.
    end = src.index('_stop_verbs = ')
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
    assert "their ai accounts" in row.lower()


def test_the_skill_names_device_ask_in_both_of_its_confirm_lists():
    # ⛔⛔ THE ROW WAS NOT ENOUGH. Two other places in this file enumerate what
    # needs a confirm — the handoff instruction and the Safe-defaults line — and
    # the second one ends "everything else runs on a clear request". So a model
    # reading either list was positively licensed to skip the one consent moment
    # this wave added. Cross-verify found it from four independent angles.
    text = _skill()
    handoff = next(ln for ln in text.splitlines()
                   if "run the REAL command it described" in ln)
    assert "device-ask" in handoff, handoff
    safe = text[text.index("**Safe defaults:**"):]
    safe = safe[:safe.index("everything else runs on a clear request")]
    assert "`device-ask`" in safe, safe[:400]


def test_the_skill_keeps_the_row_for_the_thing_that_cannot_be_done():
    # ⛔ Without it the assistant improvises an answer to "cancel my request" for
    # an operation the product does not have — and the two nearest verbs it could
    # improvise with are an unlink and a run-stop.
    low = " ".join(_skill().lower().split())
    assert "nothing withdraws a request" in low


# ── the six regressions cross-verify found after the wave was green ──────────

@pytest.mark.parametrize("said", [
    "use this code K7XQ-9B2M",
    "K7XQ-9B2M",
    "pair my PC, code is K7XQ-9B2M",
    "here is the code K7XQ9B2M",
    "add device K7XQ-9B2M",
])
def test_a_pair_code_still_pairs_however_it_is_offered(said):
    # ⛔⛔ MY FIRST REPAIR OF THE HIJACK BROKE PAIRING ITSELF. It excluded any
    # message containing "use" — which is the word in "use this code K7XQ-9B2M",
    # the commonest way anybody types one — so the client answered by asking for
    # the code that was already in the sentence. A message that says "code" is
    # about a code whatever else it says.
    argv, _lines = sr._nl_resolve(said)
    assert argv and argv[0] == "device-add", (said, argv)


@pytest.mark.parametrize("said,verb", [
    ("switch to the machine LABPC001", "device-use"),
    ("request access to computer LABPC001", None),
])
def test_a_code_shaped_name_is_still_not_a_pairing(said, verb):
    argv, _lines = sr._nl_resolve(said)
    got = argv[0] if argv else None
    assert got != "device-add", (said, argv)
    if verb:
        assert got == verb, (said, argv)


@pytest.mark.parametrize("said", [
    "is my computer public?",
    "make my computer public",
    "stop sharing my machine",
])
def test_offering_your_own_machine_is_not_answered_with_other_peoples(said):
    """⛔⛔ THE INVARIANT SURVIVES THE WAVE; THE ANSWER DOES NOT.

    7.9-2 pinned these three on a RELAY naming the web app, because the verb did
    not exist here. 7.9-3 built it, so demanding the relay would now be demanding
    that the client refuse something it can do. What has to stay true either way
    is what the browse clause got wrong: none of these may be answered with a
    list of OTHER people's machines — a list that structurally cannot contain the
    asker's own, because the projection drops it.

    ⛔ AND EACH IS STILL ASSERTED POSITIVELY. "not the public list" was satisfied
    by the catch-all too, so the answer could vanish entirely and this test would
    stay green; a mutant proved that in 7.9-2.
    """
    argv, lines = sr._nl_resolve(said)
    assert argv != ["devices-public"], said
    if said.startswith("is "):
        # A question about the state is answered by the list that carries it,
        # never by changing the thing asked about.
        assert argv == ["devices"], (said, argv)
    elif "stop" in said:
        assert argv == ["device-visibility", "private"], (said, argv)
    else:
        assert argv is None, (said, argv)
        assert "Let other people find" in lines[0], lines


@pytest.mark.parametrize("said", [
    "who wants to use my computer",
    "is anyone waiting for my computer",
    "how many people asked for my machine",
])
def test_an_owner_asking_about_their_own_queue_gets_their_own_queue(said):
    """⛔⛔ REVERSED IN 7.9-3, AND THE OLD DEFECT IS WHY IT IS SAFE TO REVERSE.

    In 7.9-2 routing this to `device-requests` was the defect: the bridge dropped
    the owner's half, so an owner asking who wanted their machine was shown their
    own empty OUTGOING list and told nobody had asked when somebody had. This
    wave makes that route carry both halves, so the same command is now the right
    answer — and the guard that matters moved to the bridge, where
    `test_requests_forwards_and_keeps_the_two_halves_apart` pins that the owner's
    queue is present and separate.
    """
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["device-requests"], (said, argv)


@pytest.mark.parametrize("said", [
    "ask for feedback",
    "ask about pricing",
    "request refund",
    "ask for access",
])
def test_an_ordinary_word_never_reaches_the_disclosing_consent(said):
    # ⛔⛔ THE IS-THIS-AN-ID TEST WAS A BARE LENGTH CHECK, so any six-letter word
    # counted as a machine and these all raised the question that hands somebody's
    # name to a stranger. An id carries a separator; a word does not.
    argv, lines = sr._nl_resolve(said)
    if argv is None:
        assert "Ask the owner of" not in lines[0], (said, lines[0])


@pytest.mark.parametrize("said", [
    "cancel the video",
    "cancel my video request",
])
def test_the_no_withdraw_line_is_only_about_a_machine(said):
    # ⛔ UNGATED, IT ANSWERED "cancel the video" WITH A SENTENCE ABOUT OWNERS AND
    # WEEKS. The clause sits above the run controls, so it needed its own subject.
    _argv, lines = sr._nl_resolve(said)
    assert "taken back" not in " ".join(lines), (said, lines)


def test_the_unlink_confirm_no_longer_keeps_the_device_noun():
    # ⛔ THE STRIP LANDED ON THE SWITCH BRANCH AND NOT ON THIS ONE, four lines
    # below — and this is the DESTRUCTIVE branch, whose own follow-up then
    # cannot resolve the name it just quoted.
    _argv, lines = sr._nl_resolve("remove device LABPC001")
    assert "“LABPC001”" in lines[0], lines[0]


# ── the list surfaces' own refusals ─────────────────────────────────────────

@pytest.mark.parametrize("code", ["rate_limited", "unauthorized", "internal_error",
                                  "http_502"])
def test_neither_list_screen_prints_a_machine_code(chat, code):
    # ⛔⛔ BOTH LIST ROUTES CAN REFUSE — thirty browse looks per five minutes,
    # sixty queue reads — and neither had a table, so the wave whose purpose was
    # to word refusals shipped two screens that printed the code. Every chat ask
    # spends a browse call, so the limit is genuinely reachable.
    chat.gets["/devices/public"] = (429, {"error": code, "retryAfterMs": 120_000})
    chat.gets["/devices/requests"] = (429, {"error": code, "retryAfterMs": 120_000})
    assert sr.cmd_devices_public(_ns()) != 0
    assert sr.cmd_device_requests(_ns()) != 0
    out = chat.out()
    assert code not in out, out


@pytest.mark.parametrize("code", ["rate_limited", "unauthorized", "internal_error",
                                  "http_502"])
def test_neither_terminal_list_screen_prints_a_machine_code(monkeypatch, capsys, code):
    monkeypatch.setattr(cli, "_bridge_get",
                        lambda p, timeout=10.0: (429, {"error": code,
                                                       "retryAfterMs": 120_000}))
    cli._device_public()
    cli._device_requests()
    out = capsys.readouterr().out
    assert code not in out, out


def test_a_list_rate_limit_names_the_wait_the_server_sent(chat):
    chat.gets["/devices/public"] = (429, {"error": "rate_limited",
                                          "retryAfterMs": 120_000})
    sr.cmd_devices_public(_ns())
    assert "2 minutes" in chat.out()


def test_the_list_wait_is_not_the_asks_hourly_one(chat):
    # ⛔ BROWSE IS THIRTY EVERY FIVE MINUTES, not five an hour. Reusing the ask's
    # sentence here would be wrong by nearly an hour in the other direction.
    chat.gets["/devices/public"] = (429, {"error": "rate_limited"})
    sr.cmd_devices_public(_ns())
    assert "hour" not in chat.out()


def test_internal_error_is_worded_by_both_clients():
    # ⛔ THE ASK ROUTE'S OWN CATCH-ALL, in neither table in the first pass.
    for said in (cli._ask_refusal("internal_error"),
                 sr._ask_refusal_line("internal_error")):
        assert "internal_error" not in said
        assert "safe to try again" in said.lower()


def test_a_status_only_failure_is_worded_once_not_twice():
    # ⛔ THE BRIDGE USED TO SYNTHESISE THE SAME PHRASE THE CLIENTS WRAP IT IN, so
    # an unworded failure read "couldn't ask for that computer: could not ask for
    # that computer (HTTP 500)". The bridge hands over a status; the client
    # writes the sentence.
    said = cli._ask_refusal("http_500")
    assert said.count("ask for that computer") == 0
    assert "HTTP 500" in said


# ── the full row, and the id path ───────────────────────────────────────────

def test_a_full_row_says_it_cannot_take_anyone(chat):
    chat.gets["/devices/public"] = (200, {"devices": [
        {"deviceId": "dev-f", "label": "Busy PC", "online": True, "full": True}]})
    sr.cmd_devices_public(_ns())
    out = chat.out()
    # ⛔⛔ `full` IS A REFUSAL IN ADVANCE. The route answers `share_cap_reached`
    # for these with certainty, so a quiet label beside an invitation to ask spent
    # one of five hourly asks on a guaranteed no.
    assert "can’t take anyone else" in out


def test_asking_for_a_full_machine_is_refused_before_it_is_spent(chat):
    chat.gets["/devices/public"] = (200, {"devices": [
        {"deviceId": "dev-f", "label": "Busy PC", "online": True, "full": True}]})
    assert sr.cmd_device_ask(_ns(device="Busy PC")) == 1
    assert not [c for c in chat.calls if c[0] == "POST"]
    assert "as many people as it can hold" in chat.out()


def test_an_id_goes_straight_to_the_route_without_the_list(chat):
    # ⛔⛔ RESOLVING EVERYTHING THROUGH THE BROWSE LIST WAS WRONG TWICE. The
    # projection drops machines this account is already on, so after an approval
    # the person just granted a computer was told no such public computer exists;
    # and it drops the caller's own and the private ones, so `is_owner`,
    # `already_shared` and `revoked_sharer` could never be reached from chat.
    chat.posts["/device/ask"] = (200, {"ok": True})
    assert sr.cmd_device_ask(_ns(device="dev-a1b2c3")) == 0
    assert not [c for c in chat.calls if c[0] == "GET"]
    assert [c for c in chat.calls if c[0] == "POST"][0][2] == {"deviceId": "dev-a1b2c3"}


@pytest.mark.parametrize("code", ["is_owner", "already_shared", "revoked_sharer"])
def test_the_three_refusals_the_list_used_to_hide_are_reachable(chat, code):
    chat.posts["/device/ask"] = (403, {"error": code})
    assert sr.cmd_device_ask(_ns(device="dev-a1b2c3")) == 1
    out = chat.out()
    assert code not in out and len(out.strip()) > 20


@pytest.mark.parametrize("wanted,is_id", [
    ("dev-a1b2c3", True), ("dev_a1b2c3", True),
    ("Studio PC", False), ("feedback", False), ("Mac", False), ("short-1", False),
])
def test_what_counts_as_an_id(wanted, is_id):
    assert sr._looks_like_a_device_id(wanted) is is_id, wanted


def test_a_quoted_id_resolves_too(chat):
    chat.gets["/devices/public"] = (200, {"devices": [ROW]})
    chat.posts["/device/ask"] = (200, {"ok": True})
    # ⛔ THE ID WAS COMPARED AGAINST THE RAW ARGUMENT, so a quoted one matched
    # nothing — and only four of the six quote marks this file enumerates were
    # stripped for the name compare.
    dev, fail = sr._resolve_public_device("“dev-a1”")
    assert dev and dev["deviceId"] == "dev-a1", fail
    dev2, fail2 = sr._resolve_public_device("‘Studio PC’")
    assert dev2 and dev2["deviceId"] == "dev-a1", fail2


def test_a_name_that_is_gone_names_the_likeliest_reason(chat):
    # ⛔ THE COMMONEST CAUSE IS AN APPROVAL. The machine leaves the public list
    # the moment this account is put on it, so "no public computer is called
    # that" is true and useless on its own.
    chat.gets["/devices/public"] = (200, {"devices": [ROW]})
    assert sr.cmd_device_ask(_ns(device="Lab Mac")) == 1
    out = chat.out()
    assert "one of YOUR computers now" in out


def test_neither_client_promises_an_approval_can_be_read_back(chat):
    chat.gets["/devices/requests"] = (200, {"requests": []})
    sr.cmd_device_requests(_ns())
    said = chat.out()
    # ⛔⛔ "ask again and I'll tell you which it was" IS FALSE FOR A YES. An
    # approval puts this account on the machine and the browse projection drops
    # machines you are already on, so asking again answers "no public computer is
    # called that". A yes reports itself by the machine turning up in your list.
    assert "tell you which it was" not in said
    assert "appearing in your own list" in said


def test_chat_reports_a_truncated_scan_on_the_empty_branch_too(chat):
    chat.gets["/devices/public"] = (200, {"devices": [], "truncated": True})
    sr.cmd_devices_public(_ns())
    assert "not be the whole story" in chat.out()


def test_the_skills_safety_bullet_says_name_or_email_not_both():
    # ⛔⛔ THE ROW AND THE BULLET BOTH SAY IT, and the guard that read the whole
    # file was satisfied by the row alone — so the BULLET could revert to "name
    # and email address" with nothing red. A mutant proved it. The bullet is the
    # normative one: it is what the model reads about what it may reach.
    text = _skill()
    bullet = text[text.index("- You drive the user's own account only"):]
    bullet = bullet[:bullet.index("\n- ") if "\n- " in bullet else 600]
    assert "name and email address" not in bullet, bullet
    assert "or their email, if no name is set" in bullet, bullet


def test_the_suite_wide_post_stub_tolerates_the_retry_argument():
    # ⛔ THE SEAM'S STUB HAS TO BE AT LEAST AS TOLERANT AS THE THING IT REPLACES.
    # `_fe_api_post` grew a `retry_401` opt-out in this wave, and a stub with a
    # fixed signature turned that into a TypeError in a dozen unrelated tests.
    # No test in THIS file passed the argument, so nothing here noticed — a
    # mutant proved it.
    from facade import bridge as _b
    status, _body = _b._fe_api_post(None, "/api/mintSrLinks", {}, retry_401=False)
    assert status == 200
