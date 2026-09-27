"""The chat router reads the codes a person pastes, and a question about a
COMPUTER being connected gets the computers (2026-09-26, the Windows-sync review
and two cross-verify rounds on the fix).

⛔⛔ TWO DEFECTS, both driven through `sr._nl_resolve` — the function `sr.py do`
runs on every natural-language message:

  · CODES WITH NO DIGIT WERE NEVER READ. The pattern required a digit, on the
    claim that "every real access code has one". The web app draws all eight
    characters uniformly from 31 (2-9, A-Z minus I, L, O), so ~1 in 11 access
    codes has none — pasted alone it reached the catch-all. And the connection
    code the chat now prints never has a digit: "sign in with WDJB-MJHT" went to
    `login`, whose fresh sign-in voided the page already open.
  · "ARE YOU CONNECTED TO MY MAC?" became an account question when rule 2 was
    widened to `are you`, and was answered "✓ Signed in as …" alone — read, by
    somebody with no computer or an offline one, as "yes, your Mac is connected".

⛔⛔ AND WHAT THE FIX MUST NOT DO. Two cross-verify rounds found my first two
versions pairing ordinary words ("the Claude Code research", a machine named
STARGATE, "I can't find my access code anywhere") and listing computers for
account questions and run titles. Those messages are here too.

The end-to-end half (the pasted connection code reaching the bridge's refusal,
never a new sign-in) is in test_connection_code_0925.py, beside its live bridge.
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


sr = _load("sr_router_codes_0926", "sr.py")


def _argv(said):
    return sr._nl_resolve(said)[0]


# ── codes with no digit: read ─────────────────────────────────────────────────

@pytest.mark.parametrize("said,tok", [
    ("KXMHWRTQ", "KXMHWRTQ"),                  # an access code with no digit, alone
    ("KXMH-WRTQ", "KXMH-WRTQ"),
    ("KAXE-WRTQ", "KAXE-WRTQ"),                # …vowels and all: A, E, U, Y are in it
    ("KXMH WRTQ", "KXMH WRTQ"),                # two halves in capitals, alone
    ("use this code KXMH-WRTQ", "KXMH-WRTQ"),
    ("my code is KXMHWRTQ", "KXMHWRTQ"),
    ("my code is KAXE-WRTQ", "KAXE-WRTQ"),     # capitals right after "code is"
    ("pair KAXE-WRTQ", "KAXE-WRTQ"),          # after "pair", capitals need a dash
    ("add my computer KXMH-WRTQ", "KXMH-WRTQ"),
    ("add my computer KAXE-WRTQ", "KAXE-WRTQ"),    # vowels: only split by a dash
    ("connect my mac KXMHWRTQ", "KXMHWRTQ"),
])
def test_an_access_code_with_no_digit_is_paired(said, tok):
    """⛔⛔ ~1 IN 11 REAL ACCESS CODES HAS NO DIGIT, and each of these reached the
    catch-all (or the devices screen) instead of pairing.

    Would this pass against the code an hour ago? No: the code pattern required
    a digit, so none of these was read as a code."""
    assert sr._nl_resolve(said) == (["device-add", tok], None), said


@pytest.mark.parametrize("said,tok", [
    ("WDJB-MJHT", "WDJB-MJHT"),
    ("wdjb-mjht", "wdjb-mjht"),
    ("WDJBMJHT", "WDJBMJHT"),
    ("WDJB MJHT", "WDJB MJHT"),
    ('"WDJB-MJHT"', "WDJB-MJHT"),                       # quoted, and nothing else
    ("WDJB–MJHT", "WDJB–MJHT"),                         # an en dash, as phones substitute
    ("WDJB‑MJHT", "WDJB‑MJHT"),                         # a non-breaking hyphen
    ("WDJB — MJHT", "WDJB — MJHT"),                     # a spaced em dash
    ("WDWD-MJMJ", "WDWD-MJMJ"),                         # only four different letters
    ("sign in with WDJB-MJHT", "WDJB-MJHT"),
    ("log in with wdjb-mjht", "wdjb-mjht"),
    ("log me in with WDJB-MJHT", "WDJB-MJHT"),
    ("sign me in with WDJB-MJHT", "WDJB-MJHT"),
    ("can you sign me in with WDJB-MJHT", "WDJB-MJHT"),
    ("please log me in with WDJB-MJHT", "WDJB-MJHT"),
    ("log me in: WDJB-MJHT", "WDJB-MJHT"),
    ("log me in please, WDJB-MJHT", "WDJB-MJHT"),
    ("LOG ME IN WITH WDJB-MJHT", "WDJB-MJHT"),
    ("wdjb-mjht please sign me in", "wdjb-mjht"),
    ("use WDJB-MJHT to sign me in", "WDJB-MJHT"),
    ("sign in with wdjb mjht", "wdjb mjht"),
    ("login wdjb mjht", "wdjb mjht"),
    ("sign in with WDJB—MJHT", "WDJB—MJHT"),
    ("log me in with code WDJB-MJHT", "WDJB-MJHT"),
    ("login code WDJB-MJHT", "WDJB-MJHT"),
    ("the connection code is WDJB-MJHT", "WDJB-MJHT"),
    ("here's the code: WDJB-MJHT", "WDJB-MJHT"),
    ("add device WDJB-MJHT", "WDJB-MJHT"),
    ("https://superresearch.io/connect?runtime=hermes&code=WDJB-MJHT", "WDJB-MJHT"),
    # any other sign-in message carrying it (cross-verify r3)
    ("WDJB-MJHT sign in", "WDJB-MJHT"),
    ("WDJB-MJHT, log in", "WDJB-MJHT"),
    ("WDJB-MJHT login", "WDJB-MJHT"),
    ("sign in again with WDJB-MJHT", "WDJB-MJHT"),
    ("sign in to Super Research: WDJB-MJHT", "WDJB-MJHT"),
    ("how do I sign in with WDJB-MJHT?", "WDJB-MJHT"),
    ('sign in with "WDJB-MJHT"', "WDJB-MJHT"),
    ("I tapped authenticate, code WDJB-MJHT", "WDJB-MJHT"),
    ("I haven't tapped anything yet, sign in with WDJB-MJHT", "WDJB-MJHT"),
])
def test_a_pasted_connection_code_goes_to_the_bridges_check_never_to_login(said, tok):
    """⛔⛔ THE CONNECTION CODE COMES BACK. `device-add` hands it to /device/pair,
    which refuses the sign-in's own code in its own words and claims nothing.
    `login` would start a NEW sign-in and void the page the person has open.

    Would this pass against the code an hour ago? No: every sign-in form went to
    `login`, and the bare code to the catch-all."""
    assert _argv(said) == ["device-add", tok], said


@pytest.mark.parametrize("said", [
    "I'm signed in with WDJB-MJHT",
    "I signed in with the code WDJB-MJHT",
    "ok I logged in with WDJB-MJHT",
])
def test_a_report_that_the_sign_in_is_done_still_reaches_login_done(said):
    """⛔ A REPORT, NOT AN ASK (cross-verify r2). Said after tapping Authenticate,
    these run `login-done` — which takes the sign-in note and the research waiting
    on it — and must never be turned into a pairing of the code."""
    assert _argv(said) == ["login-done"], said


# ── codes with no digit: words that must never be paired ──────────────────────

@pytest.mark.parametrize("said,expect", [
    # "code" / "pair" before an ordinary word (cross-verify r2)
    ("pause the Claude Code research", ["pause", "Claude Code"]),
    ("send me the podcast of the Claude Code research", ["podcast", "Claude Code"]),
    ("Any update on the code research?", ["status", "code"]),
    ("any pair requests?", ["device-requests"]),
    ("my code is rejected", None),
    ("tell me about code breakers", None),
    ("I get a new code whenever I restart", None),
    ("I don't see the code anywhere on my Mac", ["devices"]),
    # a machine named in capitals (cross-verify r2)
    ("connect to the public computer STARGATE", ["devices-public"]),
    ("ask to connect to the public computer STARGATE", ["devices-public"]),
    ("connect to my computer STARGATE", ["devices"]),
    ("add my Mac STARGATE back", ["devices"]),
    ("pair my laptop called STARGATE", ["devices"]),
    ("add my computer to SUPER RESEARCH", ["devices"]),
    # acronyms, interjections, words in any case
    ("stop the HTTP SMTP login research", None),         # the stop confirm, a reply
    ("pause the sign in UX research for MSFT TSMC", ["pause", "MSFT TSMC"]),
    ("psst hmmm", None),
    ("hmmmmmmm", None),
    ("HAHAHAHA", None),
    ("YESSSSSS", None),
    ("zzzzzzzz", None),
    ("SELF-HELP", None),                                  # an L: never an access code
    ("wdjb mjht", None),                                  # lower-case halves, alone
    ("whatever", None),
    ("database", None),
    ("feedback", None),
    ("add FEEDBACK to my research", None),
    ("real-time data", None),
    ("research FEEDBACK loops", ["research", "FEEDBACK loops"]),
    ("research sign in with WDJB-MJHT flows", ["research", "sign in with WDJB-MJHT flows"]),
    ("add WDJB-MJHT to my notes", None),                  # `add`, but no machine noun
    ("add my computer KXMH-WRTQ to the public list", None),   # a publish, not a pairing
    ("research how login codes like WDJB-MJHT work", ["research", "how login codes like WDJB-MJHT work"]),
    ('pause "sign in with WDJB-MJHT"', ["pause", "sign in with WDJB-MJHT"]),   # a quoted title
    ('podcast for "the code KXMHWRTQ story"', ["podcast", "the code KXMHWRTQ story"]),
    ("what is code KXMHWRTQ for?", None),                 # a question about a code
    ("send the logs code KXMHWRTQ", ["send-logs"]),       # a support code
    ("pair STARGATE", None),                              # a machine's name (cross-verify r3)
    ("log me in to the HTTP SMTP research", ["login"]),   # two acronyms are not a code
])
def test_words_shaped_like_a_code_are_never_paired(said, expect):
    """⛔ THE COST OF READING DIGITLESS CODES. A digitless code pairs only when the
    message IS the code, when it sits RIGHT NEXT TO a sign-in instruction or
    "code" / "pair" (eight consonants — never a word — or capitals), or after a
    pairing verb and a machine noun when it cannot be a name. None of these.

    Would this pass against the first two versions of the fix? No: each of the
    cross-verify rows was paired by one of them."""
    argv = _argv(said)
    assert argv == expect, (said, argv)


@pytest.mark.parametrize("said", [
    "pair my computer STARGATE with code K7XQ-9B2M",
    "add my laptop THEBEAST, code K7XQ-9B2M",
    "my mac STARGATE has access code K7XQ-9B2M",
    "access code K7XQ-9B2M — not the connection code WDJB-MJHT",   # both shapes readable
])
def test_a_digit_code_wins_over_a_machine_name_in_capitals(said):
    """⛔⛔ THE LEFTMOST MATCH (cross-verify r1). The first version read digitless
    codes inside the same pattern, which returns the leftmost match — so the
    machine's name in capitals was paired instead of the code."""
    assert sr._nl_resolve(said) == (["device-add", "K7XQ-9B2M"], None), said


@pytest.mark.parametrize("said", [
    "I lost my access code for THEBEAST",
    "I need a new access code for STARGATE",
    "my access code for STARGATE doesn't work",
    "share my access code for STARGATE",
    "I can't find my access code anywhere",
])
def test_a_lost_code_question_gets_the_lost_code_answer(said):
    """⛔ Windows host names are often capitals, and "anywhere" is an ordinary word
    with no I, L or O: none of these is a pairing (cross-verify r1, r2)."""
    assert sr._nl_resolve(said) == (None, [sr._LOST_CODE_REPLY]), said


def test_a_support_code_question_is_still_not_a_pairing():
    argv = _argv("status of support code KXMHWRTQ")
    assert argv is None or argv[0] != "device-add", argv


# ── connected TO a computer ───────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "are you connected to my mac?",
    "are you connected to my computer",
    "are you logged in to my mac?",
    "are you connected to the office pc?",
    "is super research connected to my office pc?",
    "are you connected with my laptop?",
    "hey, are you connected to my Mac?",
    "btw are you connected to my mac?",
    "is it signed into the office PC?",
    "are we connected to my mac?",
    "is it connected to my laptop?",
])
def test_connected_to_a_computer_lists_the_computers(said):
    """⛔⛔ "✓ Signed in as …" IS NOT AN ANSWER TO "ARE YOU CONNECTED TO MY MAC?" —
    it reads as yes to somebody whose Mac is offline or was never added. The
    computers screen says which are there and, per row, online or offline.

    Would this pass against the code an hour ago? No: these answered with the
    account line (rule 2's `are you` / `is it`) or the catch-all."""
    assert sr._nl_resolve(said) == (["devices"], None), said


@pytest.mark.parametrize("said", [
    "are you logged in?",
    "am I logged in?",
    "are you connected?",
    "is super research connected?",
    "am i signed in to super research?",
    "are you connected to my account?",
    "am I signed in with google?",
    "am I signed in on this computer?",
    "are you connected to the internet?",
    "which account am I signed in with?",
    "logged in?",
    "did the login work?",
    "login status",
    "am I signed in with the right account?",
    "am I logged in with my work email?",
    "am I signed in to SR?",
    "are you signed in to the same account as me?",
    "am I signed in with google on this laptop?",
    "am i signed in to sr on this computer?",
    "are you logged in to my account on this mac?",
    "is it signed in with my email on this pc?",
    "are you logged in with my laptop's Google account?",   # the noun names an account
    "am I signed in to my work laptop account?",
])
def test_the_account_questions_still_get_the_account_answer(said):
    """The owner's rule of 2026-09-25 stands for every question that is about the
    ACCOUNT — including ones that also name this machine ("… on this laptop"):
    the words between the verb and a machine noun may not be a preposition or
    "account" (cross-verify r2)."""
    assert sr._nl_resolve(said) == (["status-account"], None), said


@pytest.mark.parametrize("said,expect", [
    ("research which apps are connected to my mac", ["research", "which apps are connected to my mac"]),
    ('pause "how the gut is connected to the brain"', ["pause", "how the gut is connected to the brain"]),
    ("hide the mac connected to my pc", ["device-visibility", "private", "mac connected to my pc"]),
    ("switch to the laptop connected to my desktop", ["device-use", "laptop connected to my desktop"]),
    ("I'm signed in with the wrong account", ["login-done"]),
    ("I logged in with the connection code", ["login-done"]),
])
def test_connected_to_inside_other_requests_keeps_their_route(said, expect):
    """⛔⛔ ANCHORED TO THE QUESTION (cross-verify r1). The first version searched
    "connected / signed in … to" anywhere: run control on a run titled after a
    topic, device commands naming a machine by what it is connected to, and
    sign-in statements all got the computer list."""
    assert _argv(said) == expect, said


# ── the computers screen says online or offline ───────────────────────────────

def test_each_computer_row_says_online_or_offline(monkeypatch, capsys):
    """⛔ SKILL.md sends "are you connected to my Mac?" to `devices`, and its rows
    never said online or offline — an offline Mac read as "yes, connected"
    (cross-verify r2).

    Would this pass against the code an hour ago? No: the row was
    "→ MacBook Pro  (owned, private)" either way."""
    body = {"devices": [
        {"id": "a", "name": "MacBook Pro", "owned": True, "selected": True, "online": False},
        {"id": "b", "name": "Studio PC", "owned": False, "selected": False, "online": True},
    ], "selectedDeviceId": "a"}
    monkeypatch.setattr(sr, "_get", lambda path, timeout=None: (200, body))
    assert sr.main(["devices"]) == 0
    out = capsys.readouterr().out
    assert "MacBook Pro  (owned, private) · offline" in out, out
    assert "Studio PC  (shared) · online" in out, out
