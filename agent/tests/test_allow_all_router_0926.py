"""The chat router and Allow all (wave 12, 2026-09-26).

⛔⛔ THE ROUTER TOOK LIVE WRONG ACTIONS ON THESE WORDS BEFORE THE ARM EXISTED.
Driven through `sr._nl_resolve` — the function `sr.py do` runs on every
natural-language message — at the commit this wave started from:

  · `turn off allow all for my mac` and `switch off auto join for my mac` RAN AN
    UNCONFIRMED HIDE (the hide arm's turn/switch…off): with one owned computer the
    picker hid it at once, and for the DG fleet that computer is the only way in.
    `disable allow all on my mac` hid a machine called “allow all on my mac”.
  · `let anyone use my computer`, `allow everyone to join my computer` and
    `auto-approve requests for my mac` raised the APPROVE confirm — a yes with no
    name lets the ONE waiting stranger in, which nobody asked for.
  · `make my mac public and allow all` raised the PUBLISH confirm, which promises
    "you would still approve every person yourself".
  · `join the Studio PC` reached the catch-all: `join` was not an ask verb, though
    it is the web app's word on a computer that lets anyone in.

⛔ AND WHAT THE ARM MUST NOT TAKE. A hide stays a hide, a question changes nothing,
"stop the run without asking me" is a run stop, and a request that is not about a
research computer falls through untouched. Every phrase whose route the arm moved
was compared against the starting commit (every string the agent tests carry,
3,400 of them); only allow-all and `join` phrasings moved.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_router_0926", "sr.py")

# The confirm's own first words — what somebody agrees to before a yes.
_ON = "Anyone signed in can join"


def _said(text):
    return sr._nl_resolve(text)


def _confirm(text) -> str:
    argv, lines = _said(text)
    assert argv is None, f"{text!r} ran {argv} without a confirm"
    return " ".join(lines or [])


# ── ON: the confirm, never an approve and never a plain publish ──────────────

@pytest.mark.parametrize("text", [
    "let anyone use my computer",               # was the APPROVE confirm
    "allow everyone to join my computer",       # was the APPROVE confirm
    "auto-approve requests for my mac",         # was the APPROVE confirm
    "approve everyone automatically",           # was 'Say yes to “everyone automatically”?'
    "make my mac public and allow all",         # was the PUBLISH confirm
    "let anyone join my mac",                   # was the device list
    "can you let anyone join my mac",           # a polite imperative, not a question
    "turn on allow all",
    "let everyone in",
])
def test_switching_allow_all_on_asks_first_with_what_it_costs(text):
    """⛔⛔ Before the arm these raised the approve confirm (whose yes lets the one
    waiting stranger in), the publish confirm (which promises the owner still
    approves every person), or listed the computers. ON is the widest door on this
    surface, so it confirms — with the sentence the reply repeats afterwards."""
    said = _confirm(text)
    assert said.startswith(_ON), said
    assert "up to 25 people" in said and "People you removed stay out." in said
    assert "makes it public too" in said
    assert "Say yes to" not in said and "still approve every person" not in said


def test_the_setting_named_alone_or_a_statement_is_not_a_command():
    """⛔ FLIPPED 2026-09-27 (wave 12 repair 2 — the whole-message policy). These
    two were ON-confirm rows above. `allow all` alone is the checkbox's LABEL, not
    an order, and `anyone can use my computer without asking me` is a statement
    (with its question mark stripped it reads the same as the question). Neither
    is a whole-message command, so neither may raise the switch confirm: the
    label gets the catch-all, which now names the two phrasings that DO work, and
    the statement about the person's own computer gets their list, whose row says
    "anyone can join"."""
    assert _said("allow all") == (None, [sr._NL_CATCH_ALL])
    assert _said("anyone can use my computer without asking me") == (["devices"], None)


def test_the_confirm_names_a_quoted_computer_verbatim():
    said = _confirm('turn on allow all for "Studio PC"')
    assert said.startswith(f"{_ON} “Studio PC” at once"), said


def test_an_unnamed_computer_is_left_to_the_picker():
    """The hint is never invented: a bare machine noun names nothing, and the
    command's picker takes the one computer this account owns or asks which."""
    assert _confirm("let anyone join my mac").startswith(f"{_ON} that computer at once")


def test_dont_ask_me_is_not_an_off_word():
    """⛔ "don't" is an OFF word, and `…and don't ask me` asks for exactly the
    opposite: it was read as "switch allow all off".
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): it was pinned to the ON confirm. An
    `and …` second clause makes the message not a whole command, so it is never
    a switch confirm either — it is the person's own list. Still never OFF."""
    assert _said("let anyone join my mac and don't ask me") == (["devices"], None)


# ── OFF: acts at once, and names nothing it was not told ─────────────────────

@pytest.mark.parametrize("text", [
    "turn off allow all for my mac",            # was an UNCONFIRMED HIDE
    "switch off auto join for my mac",          # was an UNCONFIRMED HIDE
    "disable allow all on my mac",              # hid “allow all on my mac”
    "stop letting anyone join my mac",          # hid “anyone join my mac”
    "don't let anyone join my mac",
    "require approval again for my mac",
    "make everyone ask before joining my mac",
    "turn off auto approve",
    "turn allow all off",
])
def test_switching_allow_all_off_runs_the_off_command_and_nothing_else(text):
    """⛔⛔ Two of these HID the owner's computer with no confirm; two more hid a
    machine named after the words. OFF only narrows — the computer stays public
    and people ask again — so it acts, like hiding does, without a confirm."""
    assert _said(text) == (["device-allow-all", "no"], None)


@pytest.mark.parametrize("text", ["require approval again", "require my approval"])
def test_the_taught_off_phrase_works_said_alone(text):
    """⛔ SKILL.md teaches "require approval again" for OFF, and said alone — no
    machine word — it reached the catch-all ("I didn't catch a Super Research
    request"). The whole message only: "ask me first" inside a longer one is how
    people talk about anything, so that stays out."""
    assert _said(text) == (["device-allow-all", "no"], None)
    assert _said("ask me first")[0] != ["device-allow-all", "no"]


def test_a_preposition_is_never_part_of_the_name():
    """⛔ `require my approval on my mac` captured “approval on my mac” from the
    FIRST `my`, and the command then went looking for a computer called that."""
    assert _said("require my approval on my mac") == (["device-allow-all", "no"], None)


def test_off_passes_a_named_computer_through():
    assert _said("switch off allow all on the office pc") == (
        ["device-allow-all", "no", "office pc"], None)


# ── what the arm must leave where it was ──────────────────────────────────────

@pytest.mark.parametrize("text", ["is allow all on for my mac?",
                                  "can anyone join my mac?",
                                  "does my mac let anyone join?"])
def test_a_question_changes_nothing(text):
    """The owned row answers it ("public, anyone can join")."""
    assert _said(text) == (["devices"], None)


@pytest.mark.parametrize("text", ["how open source projects let anyone join",
                                  "what happens if I let anyone join"])
def test_a_question_about_the_world_is_not_answered_with_the_computers(text):
    """⛔ An audience and a question word, with no computer in view, is a question
    about something else — it was answered with this account's device list. It
    keeps the route it had before the arm existed."""
    assert _said(text)[0] != ["devices"]


@pytest.mark.parametrize("text", ["stop allowing people to use my mac",
                                  "hide my mac"])
def test_a_hide_stays_a_hide(text):
    """`stop allowing people to use my mac` has been a hide since 7.9-3."""
    assert _said(text)[0] == ["device-visibility", "private"]


@pytest.mark.parametrize("text", ["make it private and turn off allow all",
                                  "make my mac private and turn off allow all"])
def test_a_hide_beside_allow_all_writes_nothing(text):
    """Taken by the first allow-all arm, `make my mac private and turn off allow
    all` ran `device-allow-all no` and the computer stayed LISTED under a ✓.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 3): these were in the hide list above.
    The hand-off to the visibility clause's hide is gone (cross-verify H1: it hid
    `turn off allow all on my mac but keep it listed`, unconfirmed), and a message
    with Allow-all words that is not one whole command is READ-ONLY — the
    person's own list. Neither switch is ever half-done: `make my mac private`
    said alone still hides."""
    assert _said(text) == (["devices"], None)
    assert _said("make my mac private")[0] == ["device-visibility", "private"]


@pytest.mark.parametrize("text", ["make my mac public without allow all",
                                  "make my mac public but not allow all"])
def test_public_without_allow_all_is_a_plain_publish(text):
    """⛔ Taken by the arm, `…without allow all` raised the ON confirm and `…but not
    allow all` answered a request to be FOUND with `device-allow-all no`, which
    publishes nothing.
    ⛔ FLIPPED 2026-09-27 (wave 12 repair 2): pinned to the plain PUBLISH confirm,
    which needed the arm to read the allow-all words' direction and hand the rest
    on — the machinery that misrouted twice. Not a whole command, so no switch
    confirm of either kind: the person's own list, and "make my mac public" said
    alone is the publish."""
    assert _said(text) == (["devices"], None)
    assert _confirm("make my mac public").startswith("Let other people find")


@pytest.mark.parametrize("text", ["let people join the call",
                                  "stop letting people join the call"])
def test_an_audience_joining_something_else_is_not_this(text):
    """⛔ An audience alone was enough of a subject, so `let people join the call`
    raised the ON confirm and `stop letting…` switched Allow all off on the one
    computer this account owns."""
    argv, lines = _said(text)
    assert argv != ["device-allow-all", "no"]
    assert not " ".join(lines or []).startswith(_ON)


@pytest.mark.parametrize("text, argv", [
    ("research how open source projects let anyone join",
     ["research", "how open source projects let anyone join"]),
    ('switch to "Allow All Lab"', ["device-use", "Allow All Lab"]),
])
def test_other_requests_keep_their_route(text, argv):
    """A research topic is a topic, and a computer somebody NAMED “Allow All Lab”
    is not a request — quoted names are blanked before a word is read."""
    assert _said(text)[0] == argv


def test_a_run_stop_without_asking_is_still_a_run_stop():
    """"without asking" counts only beside an audience; on its own it is how people
    say "stop the run without asking me"."""
    assert _confirm("stop the run without asking me").startswith("Stop “")


def test_allow_all_cookies_is_not_about_a_computer():
    assert not _confirm("allow all cookies").startswith(_ON)


def test_without_asking_counts_only_beside_an_audience():
    """⛔ `restart my mac without asking me` names a computer and "without asking",
    and nothing in it is about who may join — it must not raise the ON confirm."""
    argv, lines = _said("restart my mac without asking me")
    assert not " ".join(lines or []).startswith(_ON)


@pytest.mark.parametrize("text", ["email me the brief when anyone can join",
                                  "podcast: allow all requests"])
def test_a_request_about_an_artefact_is_not_this(text):
    """A brief, a podcast or a report with no computer in view is the artefact
    rules' — an audience or the queue word beside it does not make it a switch."""
    argv, lines = _said(text)
    assert not " ".join(lines or []).startswith(_ON)
    assert argv != ["device-allow-all", "no"]


def test_a_set_of_computers_is_refused_one_at_a_time():
    said = _confirm("let anyone join all my computers")
    assert said.startswith("I switch Allow all one computer at a time.")


# ── join <computer> is an ask ─────────────────────────────────────────────────

def test_join_a_named_computer_is_the_ask_confirm():
    """⛔ `join the Studio PC` reached the catch-all — `join` was not an ask verb,
    though it is what the web app's button says on a computer that lets anyone in."""
    said = _confirm("join the Studio PC")
    assert said.startswith("Ask the owner of “Studio PC” to let you use it?"), said


def test_join_my_own_computer_is_not_an_ask():
    assert _said("join my mac") == (["devices"], None)


def test_the_ask_confirm_is_true_of_both_kinds_of_computer():
    """⛔⛔ Built from the words alone, it cannot know whether the target lets
    anyone in — and "They decide, and nothing runs on it unless they say yes" was
    false of one that does. The confirm stays: consent matters more when joining
    is instant."""
    said = _confirm("ask for the Studio PC")
    assert "If its owner lets anyone in, you join straight away; otherwise they " \
           "decide" in said
    assert "Say yes and I’ll ask." in said
