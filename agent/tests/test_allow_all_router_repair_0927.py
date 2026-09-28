"""The chat router's Allow-all arm, repaired by narrowing (wave 12 repair, 2026-09-27).

⛔⛔ CROSS-VERIFY FOUND THE FIRST ARM ACTING ON GUESSES, and every guess came from
reading the WHOLE message. Driven through `sr._nl_resolve` at the wave-12 commit:

  · `turn on allow all so I stop getting requests for my mac` switched Allow all
    OFF, unconfirmed — the `stop` of a purpose clause read as the direction;
  · `uncheck allow all for my mac`, `allow all no for my mac` and eleven more OFF
    phrasings raised the ON confirm — a yes publishes and opens the computer;
  · `list public computers that let anyone join` — a JOINER looking for a way in
    — raised the confirm that opens the asker's own computer;
  · `take my mac off the public list and turn off allow all` left it listed;
  · `join K7XQ-9B2M` asked the owner of a computer called “K7XQ-9B2M”, `don't
    join the Studio PC` and `did I join…` reached the ask confirm, `sign in to
    join the Studio PC` stopped being a sign-in.

⭐ The arm now ACTS only when an allow-all phrase is present, the subject is the
person's OWN computer, and the words governing the phrase give one direction.
Everything else goes to the clause that owns it — and nothing here reads source:
every test drives the router, or the command with the bridge stubbed.

⛔ REPAIR 2 (2026-09-27) REBUILT THE ARM ON WHOLE-MESSAGE COMMANDS, and the pins
in this file that depended on the round-1 reading are FLIPPED in place, each with
a dated note: a second clause, a leading clause, a statement or the bare label is
not a command, so it is the person's own list or the catch-all — never a write,
never a switch confirm, never the removed "on or off?" ask-back. The new policy's
own pins are in test_allow_all_whole_message_0927.py.

⛔ REPAIR 3 (2026-09-27) TOOK OUT WHAT REPAIR 2 ADDED — the `so …` reason tail, the
hand-off to the hide, the join route inside the arm — and the pins here that
stood on them are FLIPPED in place, each with a dated note. The repair-3 pins are
in test_allow_all_repair3_0927.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_router_repair_0927", "sr.py")

# The three confirms' first words, read off the router's own table so a wording
# change after the name cannot break a ROUTING pin.
_ON = sr._NL_CONFIRMS["device-allow-all"].split("{name}")[0].strip()
_OFF = ["device-allow-all", "no"]
_ASK = sr._NL_CONFIRMS["device-ask"].split("{name}")[0].strip()
_PUBLISH = sr._NL_CONFIRMS["device-visibility"].split("{name}")[0].strip()
assert _ON and _ASK and _PUBLISH


def _said(text):
    return sr._nl_resolve(text)


def _line(text) -> str:
    return " ".join(_said(text)[1] or [])


# ── F9: a purpose clause never flips ON to OFF ────────────────────────────────

_ON_WITH_A_STOP_WORD = [
    "turn on allow all so I stop getting requests for my mac",
    "turn on allow all so I don't have to approve people on my mac",
    "turn on allow all for my mac so I never have to approve anyone",
    "auto-approve requests for my mac so I stop getting pinged",
    "enable auto-approve for my mac so I don't have to keep approving",
]
# ⛔ FLIPPED 2026-09-27 (wave 12 repair 2 — the whole-message policy). These three
# were in the list above, pinned to the ON confirm. `, stop asking me` and `, no
# more approvals` are a SECOND clause, not a purpose clause, and `keep allow all
# on` is not a command to change anything — so none is a whole-message command,
# and none may raise a switch confirm. They get the person's own list.
_ON_WITH_A_SECOND_CLAUSE = [
    "turn on allow all for my mac, stop asking me",
    "let anyone join my mac, no more approvals",
    "keep allow all on for my mac so I stop getting requests",
]


@pytest.mark.parametrize("text", _ON_WITH_A_STOP_WORD)
def test_an_on_request_with_a_reason_is_the_list_never_a_switch(text):
    """⛔⛔ Every one of these POSTed allowAll:false with no confirm — the `stop`,
    `don't`, `never` or `no more` of a PURPOSE clause read as the direction.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 3): pinned to the ON confirm, through
    repair 2's `so/because/since …` reason tail. That tail is gone (cross-verify
    H3: `turn on allow all so I can join the Studio PC` — a JOINER — raised the
    confirm that opens their OWN computer). A command is the whole message; with
    a reason it is read-only — the person's own list — and still never OFF."""
    assert _said(text) == (["devices"], None)


@pytest.mark.parametrize("text", _ON_WITH_A_SECOND_CLAUSE)
def test_an_on_request_with_a_second_clause_is_the_list_never_a_switch(text):
    assert _said(text) == (["devices"], None)


@pytest.mark.parametrize("text", _ON_WITH_A_STOP_WORD + _ON_WITH_A_SECOND_CLAUSE + [
    "turn off approval for my mac", "make it public and allow all",
    "let anyone join my mac and don't ask me"])
def test_no_on_phrasing_ever_switches_allow_all_off(text):
    assert _said(text)[0] != _OFF


# ── F19: the OFF words people actually use ────────────────────────────────────

_OFF_PHRASINGS = [
    "allow all no for my mac", "uncheck allow all for my mac",
    "untick allow all for my mac", "clear allow all for my mac",
    "remove allow all from my mac", "set allow all to no for my mac",
    "allow all false for my mac", "get rid of allow all on my mac",
    "drop allow all on my mac", "kill allow all on my mac",
    "end allow all on my mac", "pause allow all on my mac",
    "remove auto-approve from my mac", "turn allow all on my mac off",
]


@pytest.mark.parametrize("text", _OFF_PHRASINGS)
def test_the_checkbox_and_command_line_off_words_switch_it_off(text):
    """⛔⛔ These raised the ON confirm, and the yes — run as the real command —
    POSTed {allowAll: true, visibility: public}: the opposite of the ask, on the
    widest door this surface has. `uncheck` is the web checkbox's word and
    `to no` the command line's; `remove allow all from my mac` was an UNLINK."""
    assert _said(text) == (_OFF, None)


@pytest.mark.parametrize("text", _OFF_PHRASINGS + [
    "turn off allow all for my mac", "stop letting anyone join my mac",
    "don't let anyone join my mac", "I don't want to let anyone join my mac",
    "require approval again for my mac", "I want to approve people on my mac again"])
def test_no_off_phrasing_ever_raises_the_on_confirm(text):
    assert not _line(text).startswith(_ON), text


def test_a_negated_governing_verb_is_not_a_direction():
    """`never enable allow all` / `don't stop letting anyone join` name no single
    direction; guessing either one acts on a guess. Nothing changes.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): the assertion was `argv is None` (the
    ask-back line). Not a whole command, so the read-only list — still never a
    write and never the ON confirm. `don't stop …` never reaches the arm: the
    negation veto above every act branch answers it with the catch-all."""
    assert _said("never enable allow all for my mac") == (["devices"], None)
    assert _said("don't stop letting anyone join my mac") == (None, [sr._NL_CATCH_ALL])


def test_on_and_off_together_is_never_acted_on():
    """⛔ FLIPPED 2026-09-27 (wave 12 repair 2): this answered "Should Allow all be
    on or off?" — the round-1 ask-back, which round 2 measured trapping plain
    requests (cross-verify G11). It is removed; two commands in one message are
    not a whole command, so the person's own list. The two phrasings the
    catch-all now teaches each route to one direction."""
    assert _said("turn on allow all for my mac and turn off auto approve") == (
        ["devices"], None)
    assert _line("turn on Allow all").startswith(_ON)
    assert _said("turn off Allow all") == (_OFF, None)


# ── F8 / F11: somebody else's computers are the browse list ───────────────────

_JOINER = [
    "list public computers that let anyone join",
    "show me public computers that let anyone join",
    "show public computers anyone can join",
    "find me a public computer that lets anyone join",
    "list the public macs where anyone can join",
    "join a public computer that lets anyone in",
    "list public computers with allow all",
    "show public computers that auto accept",
    "find a computer that lets anyone join",
    "show me machines that auto-approve",
    "ask to use a public computer that lets anyone join",
    "which public computers let anyone join",               # F11
    "are there any computers that let anyone join?",
]


@pytest.mark.parametrize("text", _JOINER)
def test_looking_for_computers_that_let_anyone_join_lists_them(text):
    """⛔⛔ The joiner half of this wave — and wave 11's fleet way in — answered
    with the OWNER's ON confirm; the yes published the asker's own computer and
    let anyone in (executed: POST {deviceId: dev1, allowAll: true, visibility:
    public}). `which public computers…` listed the asker's OWN computers."""
    assert _said(text) == (["devices-public"], None)


@pytest.mark.parametrize("text", _JOINER)
def test_no_joiner_request_ever_opens_the_askers_computer(text):
    argv, lines = _said(text)
    assert (argv or [""])[0] != "device-allow-all", argv
    assert not " ".join(lines or []).startswith(_ON)


# ── F7: a hide beside Allow all off is a hide ─────────────────────────────────

@pytest.mark.parametrize("text", [
    "take my mac off the public list and turn off allow all",
    "take my mac off the public list and disable allow all",
    "remove my mac from the public list and turn off allow all",
    "stop sharing my mac and turn off allow all",
    "stop offering my mac and turn allow all off",
    "turn off sharing on my mac and turn off allow all",
    "no longer share my mac and stop allowing anyone to join",
    "my mac should not be public, and turn off allow all",
    "undo making my mac public and turn off allow all",
])
def test_hiding_and_switching_allow_all_off_writes_nothing(text):
    """⛔⛔ These ran `device-allow-all no` with no confirm: the bridge wrote only
    allowAll:false and the computer stayed LISTED, under a reply with a ✓.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 3): pinned to the HIDE, through repair
    2's hand-off from the allow-all arm to the visibility clause. That hand-off is
    gone: it could not tell `…and turn off allow all` from `…but keep it listed`
    and HID the second, unconfirmed (cross-verify H1, H11). Two requests in one
    message are read-only now — the person's own list, never half of either — and
    each still works said alone."""
    assert _said(text) == (["devices"], None)
    assert _said("take my mac off the public list")[0] == ["device-visibility", "private"]
    assert _said("turn off allow all on my mac") == (_OFF, None)


@pytest.mark.parametrize("text", [
    "make my mac public but require my approval",
    "publish my mac but ask me first",
    "make my mac public but make people ask",
    "list my mac publicly but require approval",
    "make my mac public without allow all",
])
def test_public_but_approve_each_person_is_a_plain_publish(text):
    """The mirror: a request to be FOUND in approval mode ran `device-allow-all
    no`, which publishes nothing.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): pinned to the plain PUBLISH confirm,
    which needed the arm to read which way the allow-all words pointed and hand
    the rest to the publish — the reading that misrouted in two review rounds.
    Not a whole command, so no confirm of either switch and never a write: the
    person's own list. `make my mac public` said alone is still the publish, and
    that confirm no longer promises approval on a computer that lets anyone join.
    (Repair 3 left these where they were: read-only.)"""
    assert _said(text) == (["devices"], None)
    assert _line("make my mac public").startswith(f"{_PUBLISH} that computer ")


# ── F12 / F13 / F14 ──────────────────────────────────────────────────────────

def test_a_pronoun_subject_publishes_and_allows_all_in_one_confirm():
    """⛔ `make it public and allow all` got the plain publish confirm, whose yes
    publishes in approval mode and drops the Allow all that was asked for."""
    assert _line("make it public and allow all").startswith(_ON)


@pytest.mark.parametrize("text, route", [
    ("keep it public and let anyone join", (["devices"], None)),
    ("publish LABPC001 and allow all", (None, [sr._NL_CATCH_ALL])),
])
def test_each_road_to_a_subject_is_its_own(text, route):
    """⛔ FLIPPED 2026-09-27 (wave 12 repair 2). Both were pinned to the ON confirm
    through two roads repair 1 built — a pronoun the visibility clause resolves,
    and a publish of a named computer handed on by the arm. Neither is ever a
    write or a switch confirm.
    ⛔⛔ CORRECTED 2026-09-27 (wave 12 repair 3, cross-verify H19). The note here
    said "an `and …` is not a whole command" — FALSE for the publish row: the
    grammar DOES read `publish <one computer> and allow all` as one command
    (`publish my mac and allow all` is the ON confirm, executed below). `publish
    LABPC001 and allow all` is the catch-all ONLY because a bare, unquoted id is
    never a subject — an unquoted name must be `the <name> <machine>`. That is a
    GAP, recorded as one: the quoted form is the command."""
    assert _said(text) == route
    assert _line("publish my mac and allow all").startswith(_ON)
    assert _line("publish “LABPC001” and allow all").startswith(f"{_ON} “LABPC001”")


def test_a_negation_before_a_phrase_but_not_governing_it_is_not_a_direction():
    """⛔ `I don't mind: let anyone join my mac` switched Allow all OFF — a
    negation earlier in the message is not the verb governing the phrase.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): pinned to the ON confirm. A leading
    clause makes it not a whole command — the person's own list, never OFF."""
    assert _said("I don't mind: let anyone join my mac") == (["devices"], None)


def test_joins_at_once_alone_is_a_row_of_the_list_not_a_request():
    argv, lines = _said("joins at once")
    assert argv is None and not " ".join(lines).startswith(_ON)


def test_an_artefact_request_keeps_its_own_route():
    """The artefact rules own `podcast: …` — the allow-all words inside it are the
    podcast's business, and a catch-all here would lose the podcast."""
    assert _said("podcast: allow all requests") == (["podcast"], None)


def test_approval_off_is_allow_all_on_and_never_a_hide():
    """⛔⛔ `turn off approval for my mac` made the computer PRIVATE with no
    confirm — the hide arm's turn…off — and cleared Allow all with it."""
    argv, lines = _said("turn off approval for my mac")
    assert argv is None, argv
    assert " ".join(lines).startswith(_ON)


@pytest.mark.parametrize("text", ["turn on approval for my mac",
                                  "turn approval back on for my mac"])
def test_approval_on_is_allow_all_off(text):
    """The same switch the other way round: approval ON means each person waits."""
    assert _said(text) == (_OFF, None)


def test_a_negation_on_the_checkbox_verb_is_never_a_switch():
    """`don't tick allow all` switched it OFF on the first arm's whole-message read;
    a negated governing verb names no single direction.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): pinned to the round-1 ask-back line,
    which is removed (cross-verify G11). The person's own list."""
    assert _said("don't tick allow all for my mac") == (["devices"], None)


def test_approving_people_again_is_allow_all_off_never_the_approve_confirm():
    """⛔⛔ It raised "Say yes to that request?", whose nameless yes admits the one
    waiting stranger (`_resolve_asker("")` takes the sole row) — and Allow all
    stayed on."""
    assert _said("I want to approve people on my mac again") == (_OFF, None)
    assert not _line("I want to approve people on my mac again").startswith("Say yes to")


# ── F5 / F10 / F15 / F21: `join` ──────────────────────────────────────────────

@pytest.mark.parametrize("text, code", [
    ("join K7XQ-9B2M", "K7XQ-9B2M"), ("please join K7XQ-9B2M", "K7XQ-9B2M"),
    ("join BCDF-GHJK", "BCDF-GHJK"), ("join KAXE-WRTQ", "KAXE-WRTQ"),
])
def test_join_an_access_code_pairs_it(text, code):
    """⛔⛔ The code was POSTed to /device/ask as a device id — one of five asks an
    hour spent on "isn't offered publicly any more" — and never paired.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 3): `can I join K7XQ-9B2M` was a row
    here. A join is read only as the WHOLE message now (cross-verify H7), and a
    question is not one — it neither pairs nor asks (the catch-all); the
    whole-message forms above still pair."""
    assert _said(text) == (["device-add", code], None)
    assert _ASK not in _line(text)
    assert _said("can I join K7XQ-9B2M") == (None, [sr._NL_CATCH_ALL])


@pytest.mark.parametrize("text", ["don't join the Studio PC", "did I join the Studio PC",
                                  "never join the Studio PC"])
def test_a_negated_or_past_join_is_not_an_ask(text):
    """⛔ `join` was missing from the negation guard's verbs, and a question about
    joining read as a request to — both reached the ask confirm, whose yes can
    instant-join a stranger's computer."""
    argv, lines = _said(text)
    assert argv is None
    assert not " ".join(lines).startswith(_ASK), text


def test_join_one_of_the_public_computers_is_the_list():
    """It was refused as a set ("I ask one owner at a time") — a round trip where
    the list used to be."""
    assert _said("join one of the public computers") == (["devices-public"], None)


@pytest.mark.parametrize("text", ["sign in to join the Studio PC",
                                  "sign in and join the Studio PC",
                                  "log in to join the Studio PC"])
def test_signing_in_to_join_stays_a_sign_in(text):
    """⛔ e567704: a sign-in stays a sign-in. The join capture took these to the
    ask confirm, so somebody signed out was asked to disclose themselves first."""
    assert _said(text) == (["login"], None)


def test_join_a_named_computer_is_still_the_ask():
    assert _line("join the Studio PC").startswith(f"{_ASK} “Studio PC”")


# ── what the narrowing must not lose ──────────────────────────────────────────

@pytest.mark.parametrize("text", ["✓ Allow all is off (“Studio PC” is private).",
                                  "allow all is on for my mac"])
def test_a_statement_of_state_changes_nothing(text):
    argv, lines = _said(text)
    assert argv in (None, ["devices"]), argv
    assert not " ".join(lines or []).startswith(_ON)


def test_off_passes_a_quoted_name_through():
    assert _said("stop letting anyone join “Studio Mac”") == (_OFF + ["Studio Mac"], None)


@pytest.mark.parametrize("text", ["keep my mac public but turn off allow all",
                                  "turn off allow all but keep my mac public"])
def test_keeping_it_public_while_switching_off_is_never_a_hide_or_publish(text):
    """Read as a publish, it would raise the plain publish confirm; read as the
    visibility clause's `turn … off`, it would HIDE the computer the person said
    to keep public.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): pinned to OFF. Two clauses are not a
    whole command, so nothing is written — the person's own list, never a hide.
    (Repair 3 removed the hand-off to the hide altogether, cross-verify H1.)"""
    assert _said(text) == (["devices"], None)


def test_a_joiner_naming_a_computer_gets_the_browse_list():
    """`join the Studio PC, it lets anyone in` raised the OWNER's ON confirm naming
    “Studio PC” — a yes opens the asker's own computer.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 3): pinned to the ASK, through repair
    2's join route inside the allow-all arm. A message with Allow-all words that is
    not a whole command is READ-ONLY and the arm owns it — no ask confirm — so a
    joiner gets the browse list, whose row for that computer says "joins at once".
    `join the Studio PC` said alone is still the ask."""
    assert _said("join the Studio PC, it lets anyone in") == (["devices-public"], None)
    assert _line("join the Studio PC").startswith(f"{_ASK} “Studio PC” ")


def test_a_joiner_naming_a_code_with_allow_all_words_gets_the_browse_list():
    """`join K7XQ-9B2M, it lets anyone in` raised the ON confirm for the asker's own
    computer.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 3): pinned to the pairing, through the
    same removed join route. Read-only like every non-command message with
    Allow-all words; the code said alone, or after any ask verb, still pairs."""
    assert _said("join K7XQ-9B2M, it lets anyone in") == (["devices-public"], None)
    assert _said("join K7XQ-9B2M") == (["device-add", "K7XQ-9B2M"], None)


def test_check_if_is_a_question_and_check_alone_is_the_checkbox():
    assert _said("check if allow all is on for my mac") == (["devices"], None)
    assert _line("check allow all for my mac").startswith(_ON)


# ── F20: the OFF picker suggests OFF ──────────────────────────────────────────

_OWNED = [{"id": "dev-a1", "name": "Studio PC", "owned": True, "visibility": "public",
           "allowAll": True},
          {"id": "dev-a2", "name": "Lab PC", "owned": True, "visibility": "public",
           "allowAll": True}]


@pytest.fixture()
def two_owned(monkeypatch, capsys):
    posts: list = []
    monkeypatch.setattr(sr, "_get", lambda path, timeout=None: (200, {"devices": _OWNED}))
    monkeypatch.setattr(sr, "_post",
                        lambda path, body=None, timeout=None: posts.append(body) or (200, {}))
    return SimpleNamespace(posts=posts, out=lambda: capsys.readouterr().out)


def _example(out: str) -> str:
    line = next(ln for ln in out.splitlines() if ln.startswith("Say for example: "))
    return line[len("Say for example: "):].rstrip(".")


def test_the_off_picker_suggests_a_phrase_that_switches_off(two_owned):
    """⛔⛔ `device-allow-all no` with two owned computers suggested “let anyone join
    “Studio PC””; said back, that is the ON confirm, and a yes opens the door the
    person was closing. The example is executed through the router here."""
    sr.cmd_device_allow_all(SimpleNamespace(value="no", device="", json=False))
    example = _example(two_owned.out())
    assert two_owned.posts == []
    assert _said(example) == (_OFF + ["Studio PC"], None), example


def test_the_on_picker_still_suggests_a_phrase_that_asks_to_switch_on(two_owned):
    sr.cmd_device_allow_all(SimpleNamespace(value="yes", device="", json=False))
    example = _example(two_owned.out())
    assert _line(example).startswith(f"{_ON} “Studio PC”"), example
