"""The owner verbs on the two clients: routing, wording, and the confirm
contract (wave 7.9-3, B5 / B6 / B8).

⛔⛔ SEVEN OF 7.9-2'S BLOCKERS WERE IN THIS ONE ROUTING BLOCK, and four of them
were still live when this wave started: a noun list that had drifted by two
words meant every guard built on it failed for the commonest word for a Mac, and
an owner trying to APPROVE somebody was offered the consent question that hands
their own name to a stranger. A rule placed high sees every message, so every
clause here needs its own subject and every one of them is pinned by name.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli
from tests.conftest import code_only

_SR_PATH = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"


def _load_sr():
    spec = importlib.util.spec_from_file_location("sr_owner_793", _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()


def _skill() -> str:
    return _SKILL.read_text(encoding="utf-8")


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


@pytest.fixture()
def term(monkeypatch, capsys):
    calls: list = []
    box: dict = {"get": {}, "post": {}}

    def _bridge_get(path, timeout=10.0):
        calls.append(("GET", path, timeout))
        return box["get"].get(path)

    def _bridge_post(path, body=None, timeout=30.0):
        # ⛔ THE TIMEOUT IS RECORDED. Without it the guard below could not see
        # the thing it claims to check, and asserted that a POST happened at all
        # — a test that passes whatever the timeout is.
        calls.append(("POST", path, body, timeout))
        return box["post"].get(path)

    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _msg: None)
    monkeypatch.setattr(cli, "_bridge_get", _bridge_get)
    monkeypatch.setattr(cli, "_bridge_post", _bridge_post)
    return SimpleNamespace(box=box, calls=calls, out=lambda: capsys.readouterr().out)


def _ns(**kw):
    kw.setdefault("json", False)
    return SimpleNamespace(**kw)


def _run(**kw):
    return cli.cmd_device(argparse.Namespace(**kw))


INCOMING = {"deviceId": "dev-a1", "deviceLabel": "Studio PC",
            "requesterUid": "abc123", "requesterLabel": "Sam Jones",
            "createdAt": 5}


# ── the noun list that had drifted ───────────────────────────────────────────

@pytest.mark.parametrize("noun", ["computer", "machine", "device", "pc", "laptop",
                                  "mac", "macbook", "desktop", "node",
                                  "workstation"])
def test_every_machine_word_is_recognised_as_MINE_too(noun):
    """⛔⛔ THE DEFECT THIS WAVE STARTED FROM. `_machine_kw` and `_mine_kw` were
    two literals two lines apart and had drifted by two words, so four guards
    that comments claimed were fixed silently failed for "mac". One list now —
    this test is what stops the next word landing in only one of them."""
    assert sr._nl_resolve(f"make my {noun} public")[0] is None, noun
    assert sr._nl_resolve(f"who is waiting on my {noun}")[0] == ["device-requests"], noun
    assert sr._nl_resolve(f"make my {noun} private")[0] == \
        ["device-visibility", "private"], noun


@pytest.mark.parametrize("said", [
    "make my mac public",
    "is my mac public",
    "let other people find my mac",
])
def test_a_question_about_my_own_machine_never_lists_strangers(said):
    """⛔⛔ THE LIST STRUCTURALLY CANNOT CONTAIN THE ASKER'S OWN MACHINE — the
    projection drops it — so answering any of these with it is answering a
    question about one computer with a list that excludes it."""
    argv, _lines = sr._nl_resolve(said)
    assert argv != ["devices-public"], said


# ── approve / deny routing ───────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "approve that request",
    "approve sammy",
    "approve Bob's request",
    "say yes to sammy",
    "accept that request",
    "let them use my computer",
    "allow that person on my machine",
    "approve the request for my Mac",
    "approve the request from sammy for my mac",
])
def test_approve_phrasings_confirm_before_anything_happens(said):
    argv, lines = sr._nl_resolve(said)
    assert argv is None, (said, argv)
    assert "Say yes to" in lines[0], (said, lines)
    # The web app's own sentence, because the same owner reads both surfaces.
    assert "the same as somebody you gave an access code to" in lines[0], said


@pytest.mark.parametrize("said", [
    "deny that request",
    "say no to sammy",
    "reject the request for my mac",
    "refuse that request",
    "decline sammy",
    "turn down that request",
    "deny that request for my Mac",
])
def test_deny_phrasings_confirm_and_state_the_week(said):
    """⛔⛔ THE COST NOBODY IS TOLD. A refusal stops that person asking again for a
    week; the app tells THEM and tells the owner nothing at all — the fact lives
    in a code comment over there. Here it is in front of the decision."""
    argv, lines = sr._nl_resolve(said)
    assert argv is None, (said, argv)
    assert "Say no to" in lines[0], (said, lines)
    assert "week" in lines[0], said
    # ⛔ And the way back, or a recoverable cost reads as a bigger decision.
    assert "access code" in lines[0], said


@pytest.mark.parametrize("said", [
    "approve the request for my Mac",
    "deny that request for my Mac",
    "accept the request for the Studio PC",
    "reject the request for my mac",
])
def test_answering_never_reaches_the_asking_consent(said):
    """⛔⛔ LIVE WHEN THIS WAVE STARTED. An owner answering somebody was offered
    the question that hands the owner's own name to a stranger, for a computer
    named "for my Mac" that cannot exist."""
    _argv, lines = sr._nl_resolve(said)
    assert "Ask the owner of" not in lines[0], (said, lines)


@pytest.mark.parametrize("said,named", [
    ("approve sammy", "sammy"),
    ("approve Bob's request", "Bob"),
    ("deny the request from sammy", "sammy"),
])
def test_a_person_named_in_the_message_is_quoted_back(said, named):
    _argv, lines = sr._nl_resolve(said)
    assert f"“{named}”" in lines[0], (said, lines)


@pytest.mark.parametrize("said", [
    "approve that request",
    "let them use my computer",
    "allow that person on my machine",
    "approve it",
    "deny it",
])
def test_a_word_that_names_nobody_is_never_quoted_as_a_person(said):
    """⛔⛔ THE 7.9-2 DEFECT SHAPE. Quoting a captured fragment back — "for my
    Mac", "access to X" — names something that cannot exist and dead-ends the
    follow-up. A capture that names nobody becomes "that request", and the
    command resolves it against the real queue."""
    _argv, lines = sr._nl_resolve(said)
    for junk in ("“it”", "“them”", "“person”", "“my computer”", "“my machine”"):
        assert junk not in lines[0], (said, lines)


@pytest.mark.parametrize("said", [
    "allow it to finish",
    "accept the results",
    "approve the report",
    "let it finish",
    "let me know when it is done",
])
def test_ordinary_english_never_reaches_a_decide_confirm(said):
    """⛔⛔ THE SUBJECT GATE IS THE SAFETY OF THAT CLAUSE. `accept`, `allow` and
    `grant` are ordinary words; only the five that mean nothing else in this
    product may route on their own."""
    _argv, lines = sr._nl_resolve(said)
    joined = " ".join(lines or [])
    assert "Say yes to" not in joined, (said, lines)
    assert "Say no to" not in joined, (said, lines)


# ── visibility routing ───────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "make my computer public",
    "make my computer findable",
    "let other people find my mac",
    "put my computer on the public list",
    "offer my machine to other people",
    "make the Studio PC public",
])
def test_publishing_confirms_and_names_the_disclosure(said):
    argv, lines = sr._nl_resolve(said)
    assert argv is None, (said, argv)
    assert "Let other people find" in lines[0], (said, lines)
    # ⛔⛔ The name a computer reports is often its OWNER'S own name, and that is
    # what publishing exposes. The web app's toggle says so; so does this.
    assert "owner’s own name" in lines[0], said
    assert "approve every person yourself" in lines[0], said


@pytest.mark.parametrize("said", [
    "make my computer private",
    "make my mac private",
    "hide my computer",
    "unlist my computer",
    "take my computer off the public list",
    "stop sharing my machine",
    "stop offering my mac",
    "stop letting people find my pc",
])
def test_hiding_runs_without_a_confirm(said):
    """⛔ A strictly narrowing change confirms nothing. Confirming one is how
    people learn to click through the confirms that matter. ⛔⛔ And two of these
    were being answered by rule 3, which quoted the phrase back as a research
    title and offered to STOP A RUN."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["device-visibility", "private"], (said, argv)


@pytest.mark.parametrize("said", [
    "is my computer public",
    "is my mac findable",
    "which of my computers are findable",
])
def test_a_question_about_the_state_changes_nothing(said):
    """⛔⛔ ANSWERING A QUESTION BY CHANGING THE THING ASKED ABOUT is the worst
    outcome available here. The state has a home: the device list prints it on
    every row this account owns."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["devices"], (said, argv)


def test_a_named_machine_becomes_a_hint_and_never_a_confirmed_name():
    """⛔ The hint is validated against the account's OWN list by the command; an
    unresolvable one degrades to the picker rather than to a wrong machine."""
    argv, _lines = sr._nl_resolve("make the Studio PC private")
    assert argv == ["device-visibility", "private", "Studio PC"], argv


# ── the queue, both halves ───────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "who wants to use my machine",
    "any requests for my mac",
    "is anyone waiting on my pc",
    "how many people asked for my computer",
    "show the requests for my computers",
    "my incoming requests",
    "what am I waiting on",
    "am i waiting on anything",
])
def test_every_queue_question_reaches_the_one_command_that_answers_both(said):
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["device-requests"], (said, argv)


@pytest.mark.parametrize("said", [
    "still waiting for the podcast",
    "waiting for the report",
])
def test_a_run_progress_question_is_still_not_the_queue(said):
    """⛔⛔ THE DEFECT THE SUBJECT GATE EXISTS FOR. A bare "waiting for …"
    answered every run-progress question with "You're not waiting on any
    computer"; widening that gate for the phrasing two surfaces promise must not
    reopen it."""
    argv, _lines = sr._nl_resolve(said)
    assert argv != ["device-requests"], said


def test_the_phrasing_the_terminal_tells_windows_users_to_type_routes():
    """⛔⛔ IT DID NOT. `agent device requests` under WSL prints exactly this, and
    SKILL.md lists it as an example — and it reached the catch-all, which denies
    having the verb. Found while testing 7.9-3; the defect is 7.9-2's."""
    # ⛔ EVERY PHRASE THE TERMINAL PRINTS AS A CHAT EXAMPLE, not one of them.
    # The hint that shipped named only half the screen; whatever it names has to
    # reach the command, and so does the phrase SKILL.md gives as an example.
    src = code_only(Path(cli.__file__).read_text(encoding="utf-8"))
    hints = re.findall(r"/sr ([a-z][^\"\n]*)", src)
    assert hints, "no chat examples found in the terminal's WSL hints"
    for phrase in ("what am I waiting on", "who wants to use my computer"):
        assert sr._nl_resolve(phrase)[0] == ["device-requests"], phrase
    assert "who wants to use my computer" in src


# ── the chat commands ────────────────────────────────────────────────────────

def test_the_chat_queue_prints_both_halves_apart(chat):
    chat.gets["/devices/requests"] = (200, {
        "incoming": [INCOMING],
        "requests": [{"deviceId": "dev-z9", "deviceLabel": "Their Mac"}],
    })
    assert sr.cmd_device_requests(_ns()) == 0
    out = chat.out()
    assert "People asking to use your computers (1):" in out
    assert "Sam Jones wants “Studio PC”" in out
    assert "Waiting on (1):" in out
    assert "Their Mac" in out


def test_an_empty_owner_queue_is_said_out_loud(chat):
    """⛔ Silence about the owner's half reads as "this screen does not cover
    that" — which is exactly what it used to mean."""
    chat.gets["/devices/requests"] = (200, {"incoming": [], "requests": []})
    assert sr.cmd_device_requests(_ns()) == 0
    out = chat.out()
    assert "Nobody is waiting on your computers." in out
    assert "You’re not waiting on any computer." in out


def test_the_footer_says_which_half_it_describes(chat):
    """⛔ It used to be the only half on screen, so it needed no qualifier. With
    the owner's queue above it, an unqualified sentence claims something about
    people waiting on YOU as well — and the two halves lose a row for entirely
    different reasons."""
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING], "requests": []})
    sr.cmd_device_requests(_ns())
    out = chat.out()
    assert "Of the ones you asked for" in out


def test_the_queue_states_both_costs_before_any_decision(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING], "requests": []})
    sr.cmd_device_requests(_ns())
    out = chat.out()
    assert "the same as somebody you gave an access code to" in out
    assert "week" in out


def test_approving_names_the_person_and_reports_a_state_not_an_event(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (200, {"ok": True, "decision": "approved",
                                          "deviceName": "Studio PC"})
    assert sr.cmd_device_approve(_ns(person="sam")) == 0
    out = chat.out()
    assert "Sam Jones can use “Studio PC”" in out
    # ⛔⛔ The route closes an ALREADY-SHARED request as approved and writes
    # nothing to the machine, so "you just added them" is false on one branch.
    assert "added" not in out.lower()


def test_the_chat_sends_the_uid_and_never_prints_it(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (200, {"ok": True, "decision": "approved"})
    sr.cmd_device_approve(_ns(person="Sam Jones"))
    sent = [c for c in chat.calls if c[0] == "POST"][0][2]
    assert sent["requesterUid"] == "abc123"
    assert "abc123" not in chat.out()


def test_one_waiting_person_needs_no_name(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (200, {"ok": True, "decision": "denied"})
    assert sr.cmd_device_deny(_ns(person="")) == 0
    assert "Sam Jones" in chat.out()


def test_an_ambiguous_person_is_never_guessed(chat):
    """⛔⛔ A WRONG MATCH HERE DOES NOT MISNAME A THING — it lets a stranger onto
    somebody's computer. Ambiguity prints the queue instead of choosing."""
    other = dict(INCOMING, requesterUid="def456", requesterLabel="Sam Smith")
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING, other]})
    assert sr.cmd_device_approve(_ns(person="sam")) == 1
    out = chat.out()
    assert "More than one person waiting matches that." in out
    assert not [c for c in chat.calls if c[0] == "POST"], "it decided anyway"


def test_an_exact_name_beats_a_substring(chat):
    """The same ladder `_resolve_device_arg` uses for machines: exact first, so a
    person whose whole name is a substring of another's is still reachable."""
    other = dict(INCOMING, requesterUid="def456", requesterLabel="Sam Jones Jr")
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING, other]})
    chat.posts["/device/decide"] = (200, {"ok": True, "decision": "approved"})
    assert sr.cmd_device_approve(_ns(person="Sam Jones")) == 0
    sent = [c for c in chat.calls if c[0] == "POST"][0][2]
    assert sent["requesterUid"] == "abc123"


def test_a_person_nobody_is_waiting_under_prints_who_is(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    assert sr.cmd_device_approve(_ns(person="nobody")) == 1
    out = chat.out()
    assert "Nobody called “nobody” is waiting" in out
    assert "Sam Jones" in out


def test_an_empty_queue_refuses_rather_than_asking_the_web_app(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": []})
    assert sr.cmd_device_approve(_ns(person="sam")) == 1
    assert "Nobody is waiting on your computers." in chat.out()
    assert not [c for c in chat.calls if c[0] == "POST"]


def test_visibility_picks_the_only_owned_machine(chat):
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True},
        {"id": "dev-b2", "name": "Their Mac", "owned": False},
    ]})
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "public",
                                              "deviceName": "Studio PC",
                                              "publicLabel": "Studio PC"})
    assert sr.cmd_device_visibility(_ns(value="public", device="")) == 0
    sent = [c for c in chat.calls if c[0] == "POST"][0][2]
    assert sent == {"deviceId": "dev-a1", "visibility": "public"}


def test_visibility_never_offers_a_machine_somebody_else_owns(chat):
    """⛔ Offering one would send the person into a refusal the picker could have
    spared them — the reasoning the terminal's send-logs advice already uses."""
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-b2", "name": "Their Mac", "owned": False},
    ]})
    assert sr.cmd_device_visibility(_ns(value="public", device="")) == 1
    out = chat.out()
    assert "yours to change" in out
    assert not [c for c in chat.calls if c[0] == "POST"]


def test_several_owned_machines_are_listed_rather_than_chosen(chat):
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True},
        {"id": "dev-c3", "name": "Loft Mac", "owned": True},
    ]})
    assert sr.cmd_device_visibility(_ns(value="public", device="")) == 1
    out = chat.out()
    assert "Which computer?" in out
    assert "Studio PC" in out and "Loft Mac" in out
    assert not [c for c in chat.calls if c[0] == "POST"]


def test_the_published_label_is_reported_after_the_switch(chat):
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True}]})
    chat.posts["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "public",
        "deviceName": "Studio PC", "publicLabel": "Jane Smith's MacBook Pro"})
    sr.cmd_device_visibility(_ns(value="public", device=""))
    assert "They see it as “Jane Smith's MacBook Pro”." in chat.out()


def test_hiding_does_not_claim_anybody_is_still_locked_out(chat):
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True}]})
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "private",
                                              "deviceName": "Studio PC"})
    sr.cmd_device_visibility(_ns(value="private", device=""))
    out = chat.out()
    # ⛔ The access code still works and the copy says so — hiding is discovery,
    # not access, and implying otherwise is the misreading this whole feature
    # has to keep correcting.
    assert "An access code still lets someone in" in out


# ── the terminal ─────────────────────────────────────────────────────────────

def test_the_terminal_queue_prints_the_whole_next_command(term):
    """⛔ BOTH IDS, because neither name identifies a row: a label is a snapshot
    from the day of the ask, an unnamed machine is the identical string for
    everybody, and a person with no display name shows as their email or as a
    word shared with everyone the lookup failed on."""
    term.box["get"]["/devices/requests"] = (200, {"incoming": [INCOMING],
                                                  "requests": []})
    assert _run(device_command="requests") == 0
    out = term.out()
    assert "agent device approve dev-a1 abc123" in out


def test_the_terminal_states_both_costs_before_the_decision(term):
    term.box["get"]["/devices/requests"] = (200, {"incoming": [INCOMING],
                                                  "requests": []})
    _run(device_command="requests")
    out = term.out()
    assert "the same as" in out
    assert "for a week" in out
    # ⛔ AND IT MUST NOT PROMISE DELIVERY. The notice is best-effort and gated on
    # the asker's own notification settings, so "they are told" is a promise the
    # product cannot keep.
    assert "tries to tell them" in out
    assert "agent device deny" in out


def test_the_terminal_says_when_nobody_is_waiting(term):
    term.box["get"]["/devices/requests"] = (200, {"incoming": [], "requests": []})
    _run(device_command="requests")
    assert "Nobody is waiting on your computers." in term.out()


def test_the_terminal_reports_a_state_not_an_event(term):
    term.box["post"]["/device/decide"] = (200, {"ok": True, "decision": "approved",
                                                "deviceName": "Studio PC"})
    assert _run(device_command="approve", deviceId="dev-a1",
                requesterUid="abc123") == 0
    out = term.out()
    # ⛔ AND IT NAMES WHO. The terminal identifies a person only by the opaque id
    # typed out of a queue print that may already be stale, and it was the one
    # surface that never echoed it back.
    assert "abc123 can use Studio PC." in out
    assert "added" not in out.lower()


def test_the_terminal_denial_states_the_week_and_the_way_back(term):
    term.box["post"]["/device/decide"] = (200, {"ok": True, "decision": "denied",
                                                "deviceName": "Studio PC"})
    assert _run(device_command="deny", deviceId="dev-a1",
                requesterUid="abc123") == 0
    # ⛔ WHITESPACE-NORMALISED. These sentences are hand-wrapped to a terminal
    # width, so a copy guard keyed on the raw output breaks whenever a line is
    # rewrapped — and the fix somebody reaches for is weakening the assertion.
    out = " ".join(term.out().split())
    assert "abc123" in out, "the terminal must say who it just refused"
    assert "for a week" in out
    assert "access code still works" in out
    assert "tries to tell them" in out
    assert "They are told" not in out


@pytest.mark.parametrize("code,said", [
    ("device_not_found", "isn't yours any more"),
    ("request_not_found", "no request from that person"),
    ("request_not_pending", "isn't open any more"),
    ("is_owner", "owns that computer"),
    ("revoked_sharer", "removed this person"),
    ("share_cap_reached", "as many people as it can hold"),
    ("internal_error", "problem of its own"),
])
def test_every_decide_code_has_words_of_its_own(term, code, said):
    """⛔ A wave whose whole point is to stop machine codes reaching people must
    not print one of its own."""
    term.box["post"]["/device/decide"] = (400, {"error": code})
    assert _run(device_command="approve", deviceId="dev-a1",
                requesterUid="abc123") == 1
    out = term.out()
    assert said in out, (code, out)
    assert code not in out, (code, out)


def test_an_unknown_code_is_still_shown_rather_than_swallowed(term):
    term.box["post"]["/device/decide"] = (400, {"error": "brand_new_code"})
    _run(device_command="approve", deviceId="dev-a1", requesterUid="abc123")
    assert "brand_new_code" in term.out()


def test_a_rate_limit_uses_the_servers_number_or_none_at_all(term):
    term.box["post"]["/device/decide"] = (429, {"error": "rate_limited",
                                                "retryAfterMs": 61_000})
    _run(device_command="approve", deviceId="dev-a1", requesterUid="abc123")
    assert "about 2 minutes" in term.out()
    term.box["post"]["/device/decide"] = (429, {"error": "rate_limited"})
    _run(device_command="approve", deviceId="dev-a1", requesterUid="abc123")
    out = term.out()
    assert "just now" in out
    assert "minute" not in out


def test_the_owned_list_says_findable_only_on_rows_it_is_true_of(term):
    """⛔⛔ ONLY AN OWNER CAN CHANGE THIS, so a shared row saying "hidden" would
    report somebody else's setting as if it were the reader's to change. ⛔ And
    absent means private: a machine paired before 2026-09-04 carries no field."""
    term.box["get"]["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Mine Public", "owned": True,
         "visibility": "public", "online": True},
        {"id": "dev-a2", "name": "Mine Unset", "owned": True, "online": True},
        {"id": "dev-b2", "name": "Theirs", "owned": False,
         "visibility": "public", "online": True},
    ]})
    _run(device_command=None)
    out = term.out()
    lines = {ln.split("  (")[0].strip().lstrip("→ ").strip(): ln
             for ln in out.splitlines() if "id=" in ln}
    # ⛔⛔ THE SAME TWO WORDS THE COMMAND AND THE WEB APP USE. This column said
    # "findable"/"hidden" while the verb said "public"/"private" — three
    # vocabularies for one setting, which is how somebody comes to believe there
    # are two settings.
    assert ", public" in lines["Mine Public"]
    assert ", private" in lines["Mine Unset"]
    assert ", public" not in lines["Theirs"] and ", private" not in lines["Theirs"]
    for word in ("findable", "hidden"):
        assert word not in out, f"{word} is a third vocabulary for one setting"


def test_the_terminal_verb_is_not_called_public(term):
    """⛔⛔ `device public` IS THE BROWSE LIST — other people's machines. One word
    meaning both "show me theirs" and "give them mine" is a mistake somebody
    makes once and cannot undo."""
    p = cli.build_parser()
    ns = p.parse_args(["device", "public"])
    assert ns.device_command == "public"
    assert not hasattr(ns, "value"), "the browse verb grew a visibility value"
    ns = p.parse_args(["device", "visibility", "dev-a1", "public"])
    assert (ns.deviceId, ns.value) == ("dev-a1", "public")


def test_the_terminal_refuses_a_value_argparse_would_not_recognise():
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["device", "visibility", "dev-a1", "findable"])


# ── the copy contract between the two clients ────────────────────────────────

def test_the_two_clients_cover_the_same_decide_codes():
    """⛔ A guard compares WHAT the two say, not how. A code worded on one
    surface and raw on the other is the defect this pair of tables exists to
    prevent — cross-verify found exactly that on four surfaces in 7.9-2."""
    assert set(cli._DECIDE_FAILURES) == set(sr._DECIDE_ERRORS)


def test_no_decide_sentence_is_borrowed_from_the_ask_table():
    """⛔⛔ FIVE CODES APPEAR ON BOTH ROUTES AND MEAN DIFFERENT THINGS. Borrowing
    would say the wrong TRUE thing, which is worse than saying a code."""
    for code in ("device_not_found", "is_owner", "revoked_sharer"):
        assert cli._DECIDE_FAILURES[code] != cli._ASK_FAILURES[code], code
        assert sr._DECIDE_ERRORS[code] != sr._ASK_ERRORS[code], code


# ── SKILL.md: the three places that enumerate confirms ───────────────────────

@pytest.mark.parametrize("verb", ["device-approve", "device-deny",
                                  "device-visibility"])
def test_every_new_confirm_lands_in_all_three_lists(verb):
    """⛔⛔ THE 7.9-2 BLOCKER, VERBATIM. A row in the table was not enough: two
    OTHER places enumerate what needs a confirmation, and one of them ends
    "everything else runs on a clear request" — so a name missing from it is a
    name the file positively licenses skipping.
    ⛔⛔ AND EACH IS READ AS THE ENUMERATION ITSELF, NOT AS A BLOCK OF TEXT
    AROUND IT. The first version sliced 900 characters and asked whether the name
    appeared anywhere in them — and the prose two lines below each list explains
    what every verb costs, BY NAME. So the list could lose a verb entirely and
    this test stayed green; two mutants proved it. Fifth time in this project
    that a neighbouring line has satisfied a guard aimed at its neighbour.
    """
    text = _skill()

    def _enumeration(after: str, upto: str) -> str:
        start = text.index(after)
        return text[start:text.index(upto, start)]

    # The handoff list is the slash-separated run of command names.
    handoff = _enumeration("run the REAL command it described", ", with the")
    # Both confirm lists are the run of back-ticked names inside the bold
    # "Confirm before …**" phrase, and nothing after it — the explanation that
    # follows names every verb again and would satisfy any looser slice.
    marker = "**Confirm before\n"
    start = text.index(marker) + len(marker)
    safe = text[start:text.index("**", start)]
    safety = _enumeration("- **Confirm before** `stop`", "(briefly restarts")
    for where, block in (("handoff", handoff), ("safe-defaults", safe),
                         ("safety", safety)):
        assert verb in block, f"{verb} missing from the {where} enumeration"


def test_the_skill_says_hiding_needs_no_confirmation():
    """⛔ Both confirm lists carry `device-visibility public`, so both have to say
    which direction they mean, or the file gates a strictly narrowing change."""
    low = " ".join(_skill().lower().split())
    assert "`device-visibility private` needs no confirmation" in low
    assert "`device-visibility private` is not on the list" in low


def test_the_skill_no_longer_reserves_these_verbs_to_the_web_app():
    low = " ".join(_skill().lower().split())
    assert "answering people who ask for it, are done in the web app" not in low
    assert "approving or refusing somebody, offering a computer publicly" not in low


def test_the_skill_still_reserves_what_really_is_web_app_only():
    """⛔ Revoking ONE sharer is still web-app-only, and the greeting is the only
    place that says where it lives.

    ⛔⛔ AND HALF OF WHAT THIS USED TO ASSERT STOPPED BEING TRUE IN 7.9-5. The
    sentence it pinned was "revoking a sharer and resetting a pair code stay in
    the web app". The first half holds. The second does not: an owner-unlink
    from chat ROTATES the machine's access code and now hands the new one back, so
    chat does produce a fresh code — just not through Reset, which is still the
    web app's. A guard on the old wording would have held a sentence that had
    become misleading about the one thing this wave was correcting, so it pins
    the two facts separately instead of the sentence that used to carry both."""
    low = " ".join(_skill().lower().split())
    assert "revoking one sharer stays in the web app" in low
    # chat CAN produce a new code, and only this way
    assert "unlinking their own machine issues it a new access code" in low
    # …and the blanket claim is gone. ⛔ BOTH SPELLINGS ARE FORBIDDEN: after
    # wave 9's rename the old one could no longer appear anywhere, so keeping
    # only it would have left this half of the guard unable to fail.
    assert "resetting a pair code stay in the web app" not in low
    assert "resetting an access code stay in the web app" not in low


def test_the_skill_warns_that_publishing_can_expose_the_owners_name():
    low = " ".join(_skill().lower().split())
    assert "owner's own name" in low


def test_the_skill_says_an_approval_is_a_state_not_an_event():
    """⛔⛔ The route closes an already-shared request as approved and writes
    nothing, so a model reporting "you just added them" would be inventing an
    event on one of the two branches."""
    # ⛔ ONE ASSERTION, NOT A DISJUNCTION. The first draft of this said `X in low
    # or Y in low`, which either half satisfies — a decorative guard of exactly
    # the kind this project has shipped before.
    low = " ".join(_skill().lower().split())
    assert 'they can use it, never "you just added them"' in low


def test_every_new_verb_resolves_in_the_parser():
    """A row naming a command the parser does not have is a row that dead-ends."""
    p = sr.build_parser()
    for verb in ("device-approve", "device-deny", "device-visibility"):
        assert re.search(rf"`sr\.py {verb}", _skill()), verb
    p.parse_args(["device-approve"])
    p.parse_args(["device-deny", "sam"])
    p.parse_args(["device-visibility", "public"])


def test_the_terminal_prints_the_published_label(term):
    """⛔⛔ THE DISCLOSURE, AND NOTHING PINNED IT. A computer nobody has renamed
    reports a hostname carrying its owner's own name; switching it on is what
    puts that in front of every signed-in stranger."""
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "public",
        "deviceName": "Studio PC", "publicLabel": "Jane Smith's MacBook Pro"})
    assert _run(device_command="visibility", deviceId="dev-a1",
                value="public") == 0
    out = term.out()
    assert "They see it as “Jane Smith's MacBook Pro”." in out
    assert "approve every" in out


def test_the_terminal_hiding_says_a_pair_code_still_works(term):
    """⛔ Discovery is not access, and implying otherwise is the misreading this
    whole feature keeps having to correct."""
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "private",
        "deviceName": "Studio PC"})
    _run(device_command="visibility", deviceId="dev-a1", value="private")
    out = term.out()
    assert "Nobody can find it." in out
    assert "An access code still lets someone in without asking you." in out


def test_an_already_set_machine_reports_no_change_and_still_explains(term):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": False, "visibility": "private",
        "deviceName": "Studio PC"})
    _run(device_command="visibility", deviceId="dev-a1", value="private")
    out = term.out()
    assert "already private" in out
    assert "Nothing to change." in out
    assert "An access code still lets someone in" in out


@pytest.mark.parametrize("sub,phrase", [
    ("approve", "approve that request"),
    ("deny", "say no to that request"),
    ("visibility", "make my computer public"),
])
def test_each_new_verb_has_its_own_wsl_hint(monkeypatch, sub, phrase):
    """⛔ The redirect runs BEFORE the dispatch, so without an entry a Windows
    user asking about somebody waiting is pointed at the owned device list — a
    different question. Cross-verify caught exactly this in 7.9-2."""
    seen = {}
    monkeypatch.setattr(cli, "_redirect_if_wsl",
                        lambda msg: seen.setdefault("msg", msg) and 0 or 0)
    _run(device_command=sub, deviceId="d", requesterUid="u", value="public")
    assert phrase in seen["msg"], (sub, seen)


@pytest.mark.parametrize("sub,path", [("approve", "/device/decide"),
                                      ("visibility", "/device/visibility")])
def test_the_owner_verbs_wait_longer_than_a_firestore_read(term, sub, path):
    """⛔ The default is right for the Firestore-backed routes it was written
    for; these wait on the bridge waiting on the web app waiting on a
    transaction, and that call is allowed fifteen seconds on its own before a
    retry doubles it."""
    _run(device_command=sub, deviceId="dev-a1", requesterUid="abc123",
         value="public")
    sent = [c for c in term.calls if c[0] == "POST" and c[1] == path]
    assert sent, (sub, term.calls)
    assert sent[0][3] == 40.0, (sub, sent)


def test_the_chat_denial_states_the_week(chat):
    """⛔ Pinned on the terminal and not on the surface most people use — so the
    week could vanish from chat with nothing red."""
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (200, {"ok": True, "decision": "denied",
                                          "deviceName": "Studio PC"})
    sr.cmd_device_deny(_ns(person="sam"))
    out = chat.out()
    assert "can’t ask again for a week" in out
    assert "access code still works" in out


def test_a_captured_name_longer_than_a_name_is_not_quoted():
    """⛔ Without the bound a whole sentence is quoted back inside the confirm as
    somebody's name."""
    said = "approve " + "x" * 80
    _argv, lines = sr._nl_resolve(said)
    assert "x" * 80 not in lines[0], lines
    assert "that request" in lines[0]


@pytest.mark.parametrize("said", ["list public computers",
                                  "list the public computers"])
def test_listing_public_computers_stays_a_browse(said):
    """⛔ `list` is a browse word, not a setter. With it among the setter verbs
    this phrasing is answered as a request to PUBLISH one."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["devices-public"], (said, argv)


@pytest.mark.parametrize("said", ["stop the run, what am i waiting on",
                                  "cancel it and tell me what am i waiting on"])
def test_a_waiting_fragment_inside_a_stop_request_does_not_steal_it(said):
    """⛔⛔ THE WAITING SUBJECT IS ANCHORED AT THE START OF THE MESSAGE. Unanchored,
    a fragment inside a longer sentence reaches the queue — which is the defect
    the subject gate was added for, arriving through a different door."""
    argv, lines = sr._nl_resolve(said)
    assert argv != ["device-requests"], said
    assert "Stop" in lines[0], (said, lines)


def test_the_publishing_row_warns_about_the_owners_own_name():
    """⛔ The one fact about publishing a model cannot infer."""
    row = next(ln for ln in _skill().splitlines()
               if "sr.py device-visibility public" in ln)
    assert "OWNER'S own name" in row, row
    assert "still approves each person" in row, row


def test_the_disclosure_bullet_names_all_three_reaches():
    text = _skill()
    # ⛔ TO THE NEXT BULLET, OR THE END — it is currently the last one, and a
    # slice keyed on a blank line simply raised.
    bullet = text[text.index("- You drive the user's own account only"):]
    nxt = bullet.find("\n- ", 1)
    bullet = bullet[:nxt] if nxt != -1 else bullet
    for reach, word in (("**Asking**", "week"), ("**Answering**", "access code"),
                        ("**Publishing**", "owner's own name")):
        assert reach in bullet, reach
        assert word in bullet, (reach, word)


def test_the_queue_row_forbids_summing_the_two_halves():
    row = next(ln for ln in _skill().splitlines()
               if "it prints BOTH halves" in ln)
    assert "Never add the two together" in row, row


def test_the_capability_line_names_the_owner_verbs():
    """⛔ The fallback line is what somebody reads after a phrasing the resolver
    could not place, so a verb missing from it is a verb the fallback denies
    having."""
    _argv, lines = sr._nl_resolve("zzzz nothing matches this")
    assert "answer the people asking for it" in lines[0]
    assert "whether strangers can find it" in lines[0]


# ── the client paths cross-verify found untested ─────────────────────────────

@pytest.mark.parametrize("code,said", [
    ("device_not_found", "isn’t yours any more"),
    ("request_not_pending", "isn’t open any more"),
    ("share_cap_reached", "as many people as it can hold"),
    ("internal_error", "problem of its own"),
])
def test_the_chat_decide_refusals_are_actually_executed(chat, code, said):
    """⛔⛔ NOT ONE TEST RAN THIS PATH. Every chat stub for the decide route
    returned 200, so `_decide_refusal_line` — the whole refusal ladder on the
    surface this wave calls "the one most people use" — was pinned only by a
    key-set comparison. A mutant pointing it at the ASK table survived."""
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (400, {"error": code})
    assert sr.cmd_device_approve(_ns(person="sam")) == 1
    out = chat.out()
    assert said in out, (code, out)
    assert code not in out, (code, out)


def test_the_chat_rate_limit_uses_the_servers_number_or_none(chat):
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (429, {"error": "rate_limited",
                                          "retryAfterMs": 61_000})
    sr.cmd_device_approve(_ns(person="sam"))
    assert "about 2 minutes" in chat.out()
    chat.posts["/device/decide"] = (429, {"error": "rate_limited"})
    sr.cmd_device_approve(_ns(person="sam"))
    out = chat.out()
    assert "just now" in out and "minute" not in out


def test_a_named_machine_is_resolved_and_sent(chat):
    """⛔ The hint branch had no test at all, while the router emits the hint and
    SKILL.md documents it."""
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True},
        {"id": "dev-c3", "name": "Loft Mac", "owned": True},
    ]})
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "private",
                                              "deviceName": "Loft Mac"})
    assert sr.cmd_device_visibility(_ns(value="private", device="Loft")) == 0
    sent = [c for c in chat.calls if c[0] == "POST"][0][2]
    assert sent["deviceId"] == "dev-c3"


def test_an_unresolvable_hint_never_falls_back_to_some_other_machine(chat):
    """⛔ It must degrade to a question, not to a confident wrong machine."""
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True}]})
    assert sr.cmd_device_visibility(_ns(value="public", device="Nonesuch")) == 1
    assert not [c for c in chat.calls if c[0] == "POST"]


def test_the_visibility_refusal_is_not_wrapped_in_a_couldnt(chat):
    """⛔⛔ THE WRAPPER CONTRADICTED THE PAYLOAD. The bridge distinguishes a rules
    refusal from an unconfirmed write; `_list_refusal_line`'s "Couldn’t …"
    prefix asserted that nothing happened over the sentence saying it may
    have — and read "Couldn’t changed that computer" while doing it."""
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True}]})
    chat.posts["/device/visibility"] = (502, {
        "reason": "visibility_unconfirmed",
        "error": "could not confirm that change — it may or may not have been saved"})
    sr.cmd_device_visibility(_ns(value="public", device=""))
    out = " ".join(chat.out().split())
    assert "may or may not have been saved" in out
    assert "Couldn’t" not in out and "couldn't" not in out
    assert "changed that computer" not in out


def test_the_chat_device_list_says_which_of_your_machines_are_public(chat):
    """⛔⛔ SKILL.md ROUTES "is my computer public?" HERE AND SAYS THE ROW SAYS
    WHICH — and this list printed neither word, so the documented answer path
    landed on output that could not answer it. Only on rows the account OWNS:
    a shared row would report somebody else's setting as the reader's to
    change. ⛔ And absent means private."""
    chat.gets["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Mine Public", "owned": True,
         "visibility": "public"},
        {"id": "dev-a2", "name": "Mine Unset", "owned": True},
        {"id": "dev-b2", "name": "Theirs", "owned": False,
         "visibility": "public"},
    ]})
    assert sr.cmd_devices(_ns()) == 0
    rows = {ln.split("  (")[0].strip().lstrip("→ ").strip(): ln
            for ln in chat.out().splitlines() if "(" in ln and ")" in ln}
    assert ", public" in rows["Mine Public"]
    assert ", private" in rows["Mine Unset"]
    assert ", public" not in rows["Theirs"] and ", private" not in rows["Theirs"]
    assert sr._nl_resolve("is my computer public")[0] == ["devices"]


def test_an_ambiguous_exact_name_is_never_granted(chat):
    """⛔⛔ THE EXACT RUNG HAD NO UNIQUENESS TEST while the substring rung below
    it carefully did. The queue holds one row per MACHINE per person, so
    somebody who asked for two of this account's computers is two rows with the
    identical label AND the identical id — and the first was answered silently.
    Two askers with no display name are both the neutral fallback word."""
    two_machines = [INCOMING,
                    dict(INCOMING, deviceId="dev-c3", deviceLabel="Loft Mac")]
    chat.gets["/devices/requests"] = (200, {"incoming": two_machines})
    assert sr.cmd_device_approve(_ns(person="Sam Jones")) == 1
    assert not [c for c in chat.calls if c[0] == "POST"], "it granted one anyway"
    assert sr.cmd_device_approve(_ns(person="abc123")) == 1
    assert not [c for c in chat.calls if c[0] == "POST"]

    nameless = [dict(INCOMING, requesterUid="u1", requesterLabel="Someone"),
                dict(INCOMING, requesterUid="u2", requesterLabel="Someone")]
    chat.gets["/devices/requests"] = (200, {"incoming": nameless})
    assert sr.cmd_device_approve(_ns(person="Someone")) == 1
    assert not [c for c in chat.calls if c[0] == "POST"]


def test_a_filtered_queue_never_prints_a_whole_queue_header(chat):
    """⛔ The header counts what it shows; called with a subset it claimed to be
    everybody."""
    five = [dict(INCOMING, requesterUid=f"u{i}", requesterLabel=f"Sam {i}")
            for i in range(5)]
    chat.gets["/devices/requests"] = (200, {"incoming": five})
    sr.cmd_device_approve(_ns(person="Sam"))
    out = chat.out()
    assert "People asking to use your computers (5)" not in out
    assert "People asking to use your computers (2)" not in out


def test_the_chat_uid_absence_check_is_not_vacuous(chat):
    """⛔ An absence assertion an empty capture satisfies is not an assertion —
    the same shape this wave fixed in the bridge's log guard."""
    chat.gets["/devices/requests"] = (200, {"incoming": [INCOMING]})
    chat.posts["/device/decide"] = (200, {"ok": True, "decision": "approved",
                                          "deviceName": "Studio PC"})
    assert sr.cmd_device_approve(_ns(person="Sam Jones")) == 0
    out = chat.out()
    assert out.strip(), "nothing was printed — the absence check below is vacuous"
    assert "abc123" not in out


def test_ordinary_english_check_is_not_vacuous_on_the_argv_branch():
    """⛔ `" ".join(lines or [])` is empty whenever a command was returned, so
    both assertions passed for any message that ROUTED somewhere."""
    for said in ("allow it to finish", "accept the results", "approve the report"):
        argv, lines = sr._nl_resolve(said)
        assert argv is None, (said, argv)
        joined = " ".join(lines)
        assert joined, said
        assert "Say yes to" not in joined and "Say no to" not in joined, said


def test_the_two_clients_say_the_same_thing_for_each_decide_code():
    """⛔ The guard compared KEY SETS only, though its docstring claimed to
    compare what the two say. Two tables can share every key and disagree about
    every meaning."""
    import re as _re

    def _words(s):
        return set(_re.findall(r"[a-z]{4,}", s.lower()))

    for code in cli._DECIDE_FAILURES:
        a, b = cli._DECIDE_FAILURES[code], sr._DECIDE_ERRORS[code]
        shared = _words(a) & _words(b)
        assert len(shared) >= 2, (code, a, b)


def test_every_code_the_decide_route_can_return_is_worded_on_both_surfaces():
    """⛔ Enumerated from the route itself, not from the tables — a table cannot
    prove its own completeness."""
    route = (Path(__file__).resolve().parents[3] / "dg-research" / "src" / "app" /
             "api" / "devices" / "access-request" / "decide" / "route.ts")
    if not route.exists():
        pytest.skip("web app not checked out beside the backend")
    import re as _re
    codes = set(_re.findall(r'DecideError\("([a-z_]+)"', route.read_text()))
    codes |= set(_re.findall(r'error: "([a-z_]+)"', route.read_text()))
    missing = codes - set(cli._DECIDE_FAILURES) - {"rate_limited"}
    assert not missing, missing
    assert missing == (codes - set(sr._DECIDE_ERRORS) - {"rate_limited"})


def test_the_confirm_lists_gate_the_public_direction_only():
    """⛔ Nothing required the word `public` beside `device-visibility`, so both
    lists could regress to a bare name and gate the private direction by
    inclusion while the exemption sentence stayed green."""
    text = _skill()
    marker = "**Confirm before\n"
    start = text.index(marker) + len(marker)
    safe = text[start:text.index("**", start)]
    safety = text[text.index("- **Confirm before** `stop`"):]
    safety = safety[:safety.index("(briefly restarts")]
    for where, block in (("safe-defaults", safe), ("safety", safety)):
        assert "device-visibility public" in block, where
        assert "`device-visibility`," not in block, (
            f"{where} gates the private direction by inclusion")


def test_device_ask_is_in_the_safety_list_this_wave_added_it_to():
    """⛔ The wave added it and the parametrised guard covers only the three NEW
    verbs, so this addition had none."""
    safety = _skill()[_skill().index("- **Confirm before** `stop`"):]
    assert "`device-ask`" in safety[:safety.index("(briefly restarts")]


def test_the_skill_warns_about_the_two_near_miss_commands():
    """⛔ The author judged this load-bearing enough to write in the source, and
    the file the MODEL reads had no caution at all — the two names are one
    letter apart and point in opposite directions."""
    low = " ".join(_skill().lower().split())
    assert "devices-public` is the opposite direction" in low


# ── the cross-verify repairs, pinned ─────────────────────────────────────────
#
# ⛔⛔ EVERY ONE OF THESE WAS VERIFIED BY HAND AND NOT WRITTEN DOWN, and the
# harness said so: seventeen repair mutants survived because the fix existed and
# the guard did not. A fix nothing defends is a fix that comes back.

# ⛔ `node` IS DELIBERATELY ABSENT AND THE REASON IS NOT THIS WAVE'S. Rule 4's
# device-LIST clause matches `my … node` and sits above the remove clause, so
# "remove my node" prints the list. That ordering predates these verbs and
# changing it is not this wave's business — but it is measured, not assumed.
@pytest.mark.parametrize("noun", ["computer", "machine", "mac", "macbook",
                                  "workstation"])
def test_the_shared_noun_list_reaches_the_skip_guard_too(noun):
    """⛔⛔ THE THIRD COPY, and it guards a command that is NOT confirm-gated.
    `skip` bails when the message names a machine, precisely so "remove my mac"
    cannot silently skip a phase of a live run — and that copy of the noun list
    was missing `mac`, `macbook` and `workstation` too. The unlink test below
    covers a different site; this one covers the one where being wrong changes
    a run rather than a setting.
    """
    # ⛔⛔ MEASURED, NOT GUESSED. The first two forms of this guard asserted
    # things the mutant did not change, and it survived twice. What the third
    # noun-list copy actually decides is whether a message naming a MACHINE is
    # allowed to extract a phase: with `mac` missing, "skip the video on my mac"
    # became `skip video` on the live run instead of a bare skip. `skip` is not
    # confirm-gated, so this is the copy where being wrong changes a RUN rather
    # than a setting.
    # ⛔⛤ WAVE 1.2 SPLIT THIS QUESTION IN TWO, AND THE GUARD KEPT THE HALF THAT
    # MATTERS. Bailing on every machine noun ALSO killed `skip the podcast on my
    # computer`: branch 2 caught it and returned the bare form, which resolves
    # the run's current BLOCKER — so a person who named a PHASE got a different
    # mutation, silently. The machine in that sentence is WHERE, not WHAT.
    # What still bails is a message where the phase word is not the verb's
    # object — `remove my mac`, `remove claude's laptop` — and a phase word that
    # is part of a machine NAME, `remove my video PC`, which is the swap this
    # guard exists to prevent and which the exception could have reopened.
    for phase in ("video", "podcast", "report"):
        argv, _lines = sr._nl_resolve(f"skip the {phase} on my {noun}")
        assert argv == ["skip", phase], (noun, phase, argv)
        # the machine-named forms still cannot reach a phase
        for said in (f"remove my {noun}", f"unlink my {noun}",
                     f"remove my {phase} {noun}"):
            argv2, _l2 = sr._nl_resolve(said)
            assert argv2 is None or argv2[0] != "skip", (said, argv2)


@pytest.mark.parametrize("noun", ["computer", "machine", "mac", "macbook",
                                  "workstation"])
def test_the_shared_noun_list_reaches_the_unlink_gate_too(noun):
    """⛔⛔ W1. Three MORE hand-written noun lists were found after the first two
    were unified, each missing `mac` — so "remove my mac" reached nothing while
    "remove my computer" worked.

    ⛔⛔ AND THIS TEST PINNED A DEFECT WHILE PROVING THE FIX. It demanded the
    reply be `Unlink “computer”?` — a DESTRUCTIVE confirm quoting a word that is
    not a name, whose own "yes" runs a remove that resolves to "No device matching
    “computer”". That is the same defect 7.9-3 fixed one rung up for "remove
    device LABPC001", and the assertion enshrined it here. What the gate has to
    prove is that the message REACHES the unlink rule at all — which the
    "which one?" answer proves, and the catch-all disproves.
    """
    argv, lines = sr._nl_resolve(f"remove my {noun}")
    assert argv is None, (noun, argv)
    assert "unlink" in lines[0].lower(), (noun, lines)
    # ⛔ THE CATCH-ALL IS THE FAILURE THIS GUARDS AGAINST. It is the thing every
    # one of these five said before the noun list was shared.
    assert "didn’t catch" not in lines[0], (noun, lines)
    # ⛔ AND NO NAME IS QUOTED, because none was given.
    assert f"“{noun}”" not in lines[0], (noun, lines)


@pytest.mark.parametrize("noun", ["computer", "machine", "mac", "macbook",
                                  "workstation", "laptop", "device", "node"])
def test_a_named_machine_still_confirms_by_name_after_the_noun_is_stripped(noun):
    """The other half of the rung above: a real name behind the noun still gets
    the destructive confirm, and the confirm quotes the NAME with the noun gone."""
    argv, lines = sr._nl_resolve(f"remove my {noun} LABPC001")
    assert argv is None, (noun, argv)
    assert "Unlink “LABPC001”" in lines[0], (noun, lines)


@pytest.mark.parametrize("said", [
    "I do not want my computer to be public anymore",
    "my mac should not be public",
    "remove my computer from the public list",
    "disable sharing on my mac",
    "undo making my mac public",
    "turn off sharing on my mac",
    "no longer share my mac",
    "stop allowing people to use my mac",
])
def test_a_hide_phrased_as_a_negation_hides(said):
    """⛔⛔ W2. Every one of these reached the PUBLISH confirm — the exact
    opposite of what was asked, one reflexive yes from putting a machine in
    front of every signed-in stranger."""
    argv, _lines = sr._nl_resolve(said)
    assert argv[:2] == ["device-visibility", "private"], (said, argv)


@pytest.mark.parametrize("said,want", [
    ("can you make my mac public", "confirm"),
    ("could you hide my mac", "private"),
    ("please make my computer public", "confirm"),
    ("is my mac public", "devices"),
    ("what computers do I have", "other"),
])
def test_a_polite_imperative_is_not_a_question(said, want):
    """⛔⛔ W3. "can you make my mac public" is the commonest way anybody asks for
    either verb and it was read as a state question, so it answered neither. The
    discriminator is whether a SETTER follows the politeness — "is my mac
    public" has none and stays a question."""
    argv, lines = sr._nl_resolve(said)
    if want == "confirm":
        assert argv is None and "Let other people find" in lines[0], (said, lines)
    elif want == "private":
        assert argv[:2] == ["device-visibility", "private"], (said, argv)
    elif want == "devices":
        assert argv == ["devices"], (said, argv)
    else:
        assert argv != ["device-visibility", "private"], (said, argv)


@pytest.mark.parametrize("said", [
    "hide other people's computers from me",
    "hide someone else's computers",
    # ⛔⛔ THESE TWO ARE WHAT THE GATE ACTUALLY DECIDES. The first pair never
    # reach it — an earlier gate turns them away — so a guard built only on
    # them let the mutant survive twice. These carry a named target, which is
    # the arm that has no possessive and therefore needs the other-people test.
    "hide the mac of other people",
    "make the computer of someone else private",
])
def test_a_browse_wish_never_changes_your_own_machine(said):
    """⛔⛔ W4. This ACTED, with no confirm — a wish about other people's machines
    silently made the asker's own private."""
    # ⛔⛔ THE VERB, NOT THE WHOLE ARGV. The first form of this compared against
    # the exact two-element list — and with the gate removed the router emits a
    # THIRD element (the captured object), so the comparison passed while the
    # machine was being made private anyway. A mutant proved it. That is the
    # same vacuous shape this wave has now found four times.
    argv, _lines = sr._nl_resolve(said)
    assert (argv or [""])[0] != "device-visibility", (said, argv)


@pytest.mark.parametrize("said,name", [
    ("hide the studio pc", "studio pc"),
    ("unlist the lab mac", "lab mac"),
    ("take the studio pc off the public list", "studio pc"),
])
def test_a_verb_first_hide_carries_the_machine_name(said, name):
    """⛔⛔ W6. These dropped the name, so the picker hid whichever machine it
    liked — unconfirmed."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["device-visibility", "private", name], (said, argv)


@pytest.mark.parametrize("said,name", [
    ("make the Studio PC public", "Studio PC"),
    ("make “Research computer” public", "Research computer"),
])
def test_a_named_machine_survives_the_object_guard(said, name):
    """⛔ W7. The guard tested the MESSAGE, not the capture — and every publish
    phrasing contains the word it tested for, so every name was cleared."""
    _argv, lines = sr._nl_resolve(said)
    assert f"“{name}”" in lines[0], (said, lines)


@pytest.mark.parametrize("said", [
    "let me use the studio pc",
    "ask them to let me use their computer",
    "let us use that machine",
])
def test_the_requesters_own_phrasing_never_reaches_a_grant(said):
    """⛔⛔ W8. "let me use it" was written for "let Sam use it" and matched the
    commonest way anybody ASKS for a computer — offering to approve a stranger,
    and with one person queued a "yes" would have granted them."""
    _argv, lines = sr._nl_resolve(said)
    assert "Say yes to" not in " ".join(lines or []), (said, lines)


@pytest.mark.parametrize("said", [
    "don't allow anyone else to use my computer",
    "never allow strangers on my mac",
    "do not let them use my machine",
    # ⛔⛔ THE THREE ABOVE STOPPED MEASURING THIS CLAUSE and nothing said so.
    # Wave 1.1, three days after this wave, took `allow` and `use` into
    # `_ACT_VERBS`, so `_negated_command` now vetoes all three ABOVE the decide
    # clause is ever reached — delete `_negated_decide` from the gate and they
    # all still pass. `say yes to` is NOT in that list, and SKILL.md teaches it
    # as the owner's own approve phrasing, so these are what this clause alone
    # stands in front of. Each was checked to FAIL with `_negated_decide` gone.
    "don't say yes to sam",
    "never say yes to anyone",
    "no longer say yes to that request",
    "won't say yes to sam",
    "shouldn't say yes to anyone",
])
def test_a_negated_verb_does_not_route_as_that_verb(said):
    """⛔⛔ W9. These returned an APPROVE confirm — the exact opposite verb."""
    _argv, lines = sr._nl_resolve(said)
    joined = " ".join(lines or [])
    assert "Say yes to" not in joined, (said, lines)


@pytest.mark.parametrize("said", [
    "has my request been approved yet",
    "was my request approved",
    "why was my request denied",
    "my access request was declined",
])
def test_the_askers_own_status_question_is_their_own_queue(said):
    """⛔⛔ W10. Somebody reading their own refusal was offered to refuse a
    stranger, and a "yes" would have spent that stranger's week."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["device-requests"], (said, argv)


@pytest.mark.parametrize("said", [
    "allow it to finish on my computer",
    "accept the risk on my machine",
    "allow my laptop to sleep",
])
def test_a_weak_verb_needs_more_than_a_machine_word(said):
    """⛔⛔ W11. The gate accepted a bare machine word as the subject of `allow`
    and `accept`, so these raised a grant confirm — and this clause's own
    comment names them as sentences that must not route anywhere."""
    _argv, lines = sr._nl_resolve(said)
    assert "Say yes to" not in " ".join(lines or []), (said, lines)


@pytest.mark.parametrize("said", ["i approve", "approved", "i accept"])
def test_a_bare_assent_grants_nobody(said):
    """⛔ W12. On its own this granted the single queued requester after one
    reflexive yes."""
    _argv, lines = sr._nl_resolve(said)
    assert "Say yes to" not in " ".join(lines or []), (said, lines)


@pytest.mark.parametrize("said,kind", [
    ("make my research computer public", "confirm"),
    ("hide my research computer", "private"),
    ("approve sam for the Research computer", "approve"),
])
def test_a_research_computer_is_a_machine_not_an_artefact(said, kind):
    """⛔⛔ W13. `research` is in the artefact list and "Research computer" is the
    DEFAULT LABEL of every unnamed machine — printed verbatim by the browse list
    and by this client's own picker — so every owner verb aimed at one died,
    including the exact string the client had just told the person to type."""
    argv, lines = sr._nl_resolve(said)
    if kind == "private":
        assert argv[:2] == ["device-visibility", "private"], (said, argv)
    elif kind == "confirm":
        assert argv is None and "Let other people find" in lines[0], (said, lines)
    else:
        assert argv is None and "Say yes to" in lines[0], (said, lines)


@pytest.mark.parametrize("said", [
    "add my computer to the public list",
    "add my mac to the public directory",
])
def test_a_publish_request_is_not_a_pairing_request(said):
    """⛔ W14. Answered with "paste the access code" — the pairing rule sits above
    everything and its verb list contains `add`."""
    _argv, lines = sr._nl_resolve(said)
    assert "access code" not in " ".join(lines or []), (said, lines)


@pytest.mark.parametrize("said,who", [
    ("grant access to sam", "sam"),
    ("approve access for jane", "jane"),
])
def test_the_person_after_access_to_is_the_person(said, who):
    """⛔ W15. The capture stopped at "access", so the name was cleared and the
    owner had to name them twice."""
    _argv, lines = sr._nl_resolve(said)
    assert f"“{who}”" in lines[0], (said, lines)


def test_the_chat_decide_exit_code_tells_the_two_failures_apart(chat,
                                                                monkeypatch):
    """⛔ W32. An unreachable bridge is 2 everywhere else in this client and this
    command reported 1 — a refusal the person could act on."""
    monkeypatch.setattr(sr, "_get", lambda *a, **k: (0, {"error": "down"}))
    assert sr.cmd_device_approve(_ns(person="sam")) == 2
    monkeypatch.setattr(sr, "_get", lambda *a, **k: (200, {"incoming": []}))
    assert sr.cmd_device_approve(_ns(person="sam")) == 1


def test_the_terminal_visibility_refusal_is_not_wrapped_in_a_couldnt(term):
    """⛔⛔ W22. The wrapper asserted that nothing happened OVER the one payload
    written to say it may have — and read "couldn't changed that computer" while
    doing it. Pinned on the chat client and not on the terminal."""
    term.box["post"]["/device/visibility"] = (502, {
        "reason": "visibility_unconfirmed",
        "error": "could not confirm that change — it may or may not have been saved"})
    assert _run(device_command="visibility", deviceId="dev-a1",
                value="public") == 1
    out = " ".join(term.out().split())
    assert "may or may not have been saved" in out
    assert "couldn't changed" not in out.lower()
    assert "changed that computer" not in out


def test_an_unreadable_visibility_reply_is_a_sentence_not_a_traceback(term):
    """⛔ W21. `_VISIBILITY_WORDS[state]` was the only raw index on a wire value
    in the file, and a 200 whose body fails to parse arrives as {}."""
    term.box["post"]["/device/visibility"] = (200, {})
    assert _run(device_command="visibility", deviceId="dev-a1",
                value="public") == 0
    out = term.out()
    assert "did not say to what" in out


def test_the_terminal_footer_names_the_half_it_describes(term):
    """⛔⛔ W19. Printed under BOTH halves, and every clause of it is false of the
    owner's queue: an incoming row also vanishes when the machine changes hands,
    and "a yes shows up as the computer appearing in `agent device`" means
    nothing for a machine already in your own list."""
    term.box["get"]["/devices/requests"] = (200, {
        "incoming": [INCOMING],
        "requests": [{"deviceId": "dev-z9", "deviceLabel": "Their Mac"}]})
    _run(device_command="requests")
    out = " ".join(term.out().split())
    assert "Of the ones YOU asked for" in out
    assert "leaves that half either way" in out
    # ⛔ The unqualified form must not come back.
    assert "Only unanswered requests appear here" not in out
    assert "leaves this list either way" not in out
