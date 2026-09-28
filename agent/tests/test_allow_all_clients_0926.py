"""Allow all, in both clients — the chat skill (sr.py) and the terminal (cli.py).

⛔⛔ WHAT THIS CODE DECIDES. What a person is told when they join a computer at
once, what an owner is told when they open or close that door, and whether the
lists they read say which computers let people straight in. Every sentence here is
one somebody acts on: "its owner decides" over a join that already happened sends
them to wait for an answer that is never coming; "you still approve every person"
over an open door is the one lie this wave could ship.

Every test drives the real command with the bridge stubbed at the HTTP helper —
nothing here reads the source to decide what a command prints.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli

_SR_PATH = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_0926", _SR_PATH)

OWNED = {"id": "dev-a1", "name": "Studio PC", "owned": True, "selected": True,
         "online": True, "visibility": "public", "allowAll": False}
OWNED_OPEN = dict(OWNED, allowAll=True)
SHARED = {"id": "dev-b2", "name": "Their Mac", "owned": False, "selected": False,
          "online": True, "visibility": "public", "allowAll": True}
PUB_ASK = {"deviceId": "dev-k1", "label": "Lab Mac", "osFamily": "macos",
           "online": True, "full": False, "allowAll": False}
PUB_OPEN = {"deviceId": "dev-j9", "label": "DG shared", "osFamily": "linux",
            "online": True, "full": False, "allowAll": True}
PUB_OPEN_FULL = dict(PUB_OPEN, deviceId="dev-j8", label="DG full", full=True)

# ⛔⛔ THE CANONICAL DISCLOSURE (wave 12 repair, cross-verify F24 + F6) — the one
# second sentence the web's checkbox line, the machine, the chat and the agent
# terminal all say, word for word. Before the repair the chat and the terminal
# said only that joiners run research; the web and the machine also said what
# they can SEE.
CANON = ("They run research on your AI accounts and can see your email, who else "
         "is on it, and what's running on it.")


def _ns(**kw):
    kw.setdefault("json", False)
    return SimpleNamespace(**kw)


@pytest.fixture()
def chat(monkeypatch, capsys):
    gets: dict = {}
    posts: dict = {}
    calls: list = []

    def _get(path, timeout=None):
        calls.append(("GET", path, None, timeout))
        return gets.get(path, (200, {}))

    def _post(path, body=None, timeout=None):
        calls.append(("POST", path, body, timeout))
        return posts.get(path, (200, {}))

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    arm = {"armed": True}
    monkeypatch.setattr(sr, "_prepare_stream_arm",
                        lambda: ([], {"armed": arm["armed"]}, 0))
    gets["/devices"] = (200, {"devices": [dict(OWNED), dict(SHARED)],
                              "selectedDeviceId": "dev-a1"})
    return SimpleNamespace(gets=gets, posts=posts, calls=calls, arm=arm,
                           out=lambda: capsys.readouterr().out)


def _posted(chat, path):
    return [c[2] for c in chat.calls if c[0] == "POST" and c[1] == path]


# ── sr.py device-allow-all ───────────────────────────────────────────────────

def test_allow_all_yes_asks_for_public_and_allow_all_together(chat):
    """⛔⛔ "yes makes it public too" — one request, both fields. Sending allowAll
    alone would leave a private computer that "lets anyone join" letting nobody in."""
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "public", "allowAll": True,
                                              "deviceName": "Studio PC",
                                              "publicLabel": "Studio PC"})
    rc = sr.cmd_device_allow_all(_ns(value="yes", device=""))
    assert rc == 0
    assert _posted(chat, "/device/visibility") == [
        {"deviceId": "dev-a1", "visibility": "public", "allowAll": True}]
    out = chat.out()
    assert "✓ “Studio PC” now lets anyone join at once." in out
    # ⛔ RE-PINNED 2026-09-27 (wave 12 repair): the middle sentence is CANON now.
    assert ("Anyone signed in can join “Studio PC” at once — up to 25 people — "
            f"without asking you. {CANON} People you removed stay out.") in out
    assert "They see it as “Studio PC”." in out
    assert "You still approve every person yourself" not in out


@pytest.mark.parametrize("text", ["turn on allow all", "let anyone join my mac"])
def test_the_chat_asks_consent_to_the_whole_disclosure(text):
    """⛔⛔ THE CONFIRM IS THE CONSENT MOMENT (cross-verify F24). It asked for less
    than the web and the machine disclose — nothing about the owner's email, the
    other members or what is running. Driven through the router `do` runs."""
    argv, lines = sr._nl_resolve(text)
    assert argv is None, argv
    said = " ".join(lines or [])
    assert CANON in said, said


def test_allow_all_no_sends_no_visibility_and_says_who_keeps_access(chat):
    """⛔ OFF leaves the computer public — a `visibility` in this request would be
    a second decision nobody made. And the half worth saying: nobody is removed."""
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "public", "allowAll": False,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_allow_all(_ns(value="no", device=""))
    assert _posted(chat, "/device/visibility") == [{"deviceId": "dev-a1",
                                                   "allowAll": False}]
    out = chat.out()
    assert "no longer lets anyone join — you approve each person again" in out
    assert ("Anyone who already joined keeps access — remove people in the web app "
            "(Shared with).") in out


def test_allow_all_no_on_a_private_computer_says_it_is_off(chat):
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": False,
                                              "visibility": "private",
                                              "allowAll": False,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_allow_all(_ns(value="no", device=""))
    assert "✓ Allow all is off (“Studio PC” is private)." in chat.out()


def test_allow_all_no_when_already_off_changes_nothing_and_says_so(chat):
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": False,
                                              "visibility": "public",
                                              "allowAll": False,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_allow_all(_ns(value="no", device=""))
    out = chat.out()
    assert "already asks you about each person. Nothing to change." in out
    assert "keeps access" not in out


def test_allow_all_refuses_anything_but_yes_or_no(chat):
    assert sr.cmd_device_allow_all(_ns(value="maybe", device="")) == 1
    assert _posted(chat, "/device/visibility") == []


def test_allow_all_picker_example_names_this_switch(chat):
    """"make “X” public" answered "which computer should let anyone join?" with an
    example of the other switch."""
    chat.gets["/devices"] = (200, {"devices": [dict(OWNED), dict(OWNED, id="dev-a2",
                                                                 name="Lab PC")]})
    assert sr.cmd_device_allow_all(_ns(value="yes", device="")) == 1
    assert "Say for example: let anyone join “Studio PC”." in chat.out()


def test_a_refusal_is_relayed_not_wrapped(chat):
    chat.posts["/device/visibility"] = (403, {"reason": "visibility_refused",
                                              "error": "that change was refused — "
                                                       "nothing changed"})
    assert sr.cmd_device_allow_all(_ns(value="yes", device="")) != 0
    assert "✗ that change was refused — nothing changed" in chat.out()


# ── sr.py device-visibility public --allow-all ────────────────────────────────

def test_visibility_public_with_allow_all_sends_both(chat):
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "public", "allowAll": True,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_visibility(_ns(value="public", device="", allow_all=True))
    assert _posted(chat, "/device/visibility") == [
        {"deviceId": "dev-a1", "visibility": "public", "allowAll": True}]
    assert "now lets anyone join at once" in chat.out()


def test_going_private_on_an_open_computer_says_who_keeps_access(chat):
    """⛔ WAVE 12 REPAIR (cross-verify F26). Going private switches Allow all off
    as well; the machine says everyone who joined keeps access, and the chat said
    nothing — so an owner could believe the people were gone. The machine's own
    line, only when the bridge says the door WAS open."""
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "private",
                                              "allowAll": False, "allowAllWas": True,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_visibility(_ns(value="private", device="", allow_all=False))
    out = chat.out()
    assert "✓ “Studio PC” is now private." in out
    assert ("Anyone who already joined keeps access — remove people in the web app "
            "(Shared with).") in out


@pytest.mark.parametrize("extra", [{"changed": True, "allowAllWas": False},
                                   {"changed": True},        # an older bridge
                                   {"changed": False, "allowAllWas": True}])
def test_going_private_says_nothing_about_joiners_when_nobody_could_join(chat, extra):
    chat.posts["/device/visibility"] = (200, {"ok": True, "visibility": "private",
                                              "allowAll": False,
                                              "deviceName": "Studio PC", **extra})
    sr.cmd_device_visibility(_ns(value="private", device="", allow_all=False))
    assert "keeps access" not in chat.out()


def test_visibility_private_with_allow_all_is_refused_before_the_bridge(chat):
    assert sr.cmd_device_visibility(_ns(value="private", device="",
                                        allow_all=True)) == 1
    assert _posted(chat, "/device/visibility") == []
    assert "A private computer can’t let anyone join" in chat.out()


def test_plain_public_sends_no_allow_all_at_all(chat):
    """A flag-less publish must not decide allow-all either way — the bridge leaves
    an allow-all computer alone and starts a private one in approval mode."""
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "public", "allowAll": False,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_visibility(_ns(value="public", device="", allow_all=False))
    assert _posted(chat, "/device/visibility") == [{"deviceId": "dev-a1",
                                                   "visibility": "public"}]
    assert "You still approve every person yourself." in chat.out()


def test_public_on_an_allow_all_computer_never_claims_you_approve_each_person(chat):
    """⛔⛔ THE ONE LIE THIS WAVE COULD SHIP. "make it public" on a computer that
    already lets anyone in answered "You still approve every person yourself"."""
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": False,
                                              "visibility": "public", "allowAll": True,
                                              "deviceName": "Studio PC"})
    sr.cmd_device_visibility(_ns(value="public", device="", allow_all=False))
    out = chat.out()
    assert "You still approve every person yourself" not in out
    assert "already lets anyone join at once. Nothing to change." in out
    assert "Anyone signed in can join “Studio PC” at once" in out


def test_the_parser_takes_both_new_forms():
    p = sr.build_parser()
    ns = p.parse_args(["device-visibility", "public", "--allow-all", "Studio PC"])
    assert ns.allow_all is True and ns.device == "Studio PC"
    ns = p.parse_args(["device-allow-all", "no", "Studio PC"])
    assert ns.value == "no" and ns.device == "Studio PC"
    assert ns.func is sr.cmd_device_allow_all
    with pytest.raises(SystemExit):
        p.parse_args(["device-allow-all", "maybe"])


def test_the_router_argv_parses_through_do(chat):
    """The router emits positionals only; `cmd_do` puts them behind `--`."""
    chat.posts["/device/visibility"] = (200, {"ok": True, "changed": True,
                                              "visibility": "public", "allowAll": False,
                                              "deviceName": "Studio PC"})
    sr.cmd_do(_ns(text=["turn", "off", "allow", "all", "for", "my", "mac"]))
    assert _posted(chat, "/device/visibility") == [{"deviceId": "dev-a1",
                                                   "allowAll": False}]


# ── sr.py rows ────────────────────────────────────────────────────────────────

def test_an_owned_allow_all_row_says_anyone_can_join(chat):
    chat.gets["/devices"] = (200, {"devices": [dict(OWNED_OPEN), dict(SHARED)],
                                   "selectedDeviceId": "dev-a1"})
    sr.cmd_devices(_ns())
    out = chat.out()
    assert "Studio PC  (owned, public, anyone can join)" in out
    # ⛔ A SHARED row never reports somebody else's setting.
    assert "Their Mac  (shared)" in out


@pytest.mark.parametrize("row", [dict(OWNED, allowAll=False),
                                 dict(OWNED, visibility="private", allowAll=True),
                                 dict(OWNED, allowAll="true")])
def test_only_a_public_strictly_true_row_says_anyone_can_join(chat, row):
    chat.gets["/devices"] = (200, {"devices": [row], "selectedDeviceId": "dev-a1"})
    sr.cmd_devices(_ns())
    assert "anyone can join" not in chat.out()


def test_a_public_row_that_joins_at_once_says_so_and_full_wins(chat):
    chat.gets["/devices/public"] = (200, {"devices": [PUB_OPEN, PUB_ASK, PUB_OPEN_FULL],
                                          "truncated": False})
    sr.cmd_devices_public(_ns())
    out = chat.out()
    assert "  • DG shared · online · joins at once" in out
    assert "  • Lab Mac · online\n" in out
    assert "DG full · online · can’t take anyone else" in out
    assert "DG full · online · joins at once" not in out


@pytest.mark.parametrize("bit", ["true", 1, None])
def test_a_row_whose_bit_is_not_strictly_true_reads_as_ask(chat, bit):
    """⛔ STRICTLY `True`. A malformed or missing bit must read as "ask the owner",
    the direction that cannot send somebody to a computer that then files a
    request they were told would not exist."""
    chat.gets["/devices/public"] = (200, {"devices": [dict(PUB_OPEN, allowAll=bit)],
                                          "truncated": False})
    sr.cmd_devices_public(_ns())
    out = chat.out()
    assert "joins at once" not in out and sr._PUBLIC_ASK_INVITE in out


def test_the_invite_changes_only_when_a_row_joins_at_once(chat):
    """⛔⛔ "Once the request is accepted" is false for a row with no request."""
    chat.gets["/devices/public"] = (200, {"devices": [PUB_OPEN, PUB_ASK],
                                          "truncated": False})
    sr.cmd_devices_public(_ns())
    out = chat.out()
    assert sr._PUBLIC_JOIN_INVITE in out and sr._PUBLIC_ASK_INVITE not in out
    chat.gets["/devices/public"] = (200, {"devices": [PUB_ASK, PUB_OPEN_FULL],
                                          "truncated": False})
    sr.cmd_devices_public(_ns())
    out = chat.out()
    assert sr._PUBLIC_ASK_INVITE in out and sr._PUBLIC_JOIN_INVITE not in out


def test_the_no_computer_screen_takes_the_same_invite(chat):
    chat.gets["/devices/public"] = (200, {"devices": [PUB_OPEN], "truncated": False})
    lines = sr._public_offer_lines()
    assert sr._PUBLIC_JOIN_INVITE in lines
    assert any("joins at once" in line for line in lines)


# ── sr.py device-ask answered "joined" ────────────────────────────────────────

def _joined(**extra):
    body = {"ok": True, "status": "joined", "deviceId": "dev-j9",
            "deviceName": "DG shared", "selected": False, "online": True,
            "usable": True, "autoStarted": False, "runId": None}
    body.update(extra)
    return (200, body)


def test_a_join_says_youre_in_and_never_that_the_owner_decides(chat):
    """⛔⛔ The pending wording over a join that already happened sent people to
    wait for an answer that never comes — the reply IS the notice."""
    chat.posts["/device/ask"] = _joined()
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    out = chat.out()
    assert "✓ You're in — “DG shared” lets anyone join, so you can use it now." in out
    assert "owner decides" not in out
    assert "Your research will run on it." not in out


def test_a_join_that_selected_it_says_research_runs_there(chat):
    chat.posts["/device/ask"] = _joined(selected=True)
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    assert "Your research will run on it." in chat.out()


def test_a_join_that_started_the_held_topic_says_so(chat):
    chat.posts["/device/ask"] = _joined(topic="Mars habitats", autoStarted=True,
                                        runId="run-1")
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    out = chat.out()
    assert ("Starting “Mars habitats” on it now — I'll tell you here when it "
            "finishes or needs you.") in out


def test_a_start_on_a_switched_off_computer_is_queued(chat):
    chat.posts["/device/ask"] = _joined(topic="Mars", autoStarted=True, online=False)
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    assert ("“Mars” is queued on it — it's switched off, so it starts when it comes "
            "on.") in chat.out()


def test_no_promise_to_report_back_unless_a_watcher_was_armed(chat):
    """⛔ Same gate as `cmd_research`: nothing ticks unless a row was written."""
    chat.arm["armed"] = False
    chat.posts["/device/ask"] = _joined(topic="Mars", autoStarted=True)
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    out = chat.out()
    assert "I'll tell you here" not in out
    assert "Ask me how it’s going anytime." in out


def test_a_held_topic_that_could_not_start_is_still_held_and_said(chat):
    chat.posts["/device/ask"] = _joined(topic="Mars", autoStarted=False, usable=False)
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    out = chat.out()
    assert ("I'm still holding “Mars” for you, but DG shared isn't ready to take "
            "work yet.") in out
    assert "Starting" not in out


def test_a_pending_ask_keeps_todays_words(chat):
    chat.posts["/device/ask"] = (200, {"ok": True, "status": "pending",
                                       "deviceId": "dev-j9"})
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    out = chat.out()
    assert "Its owner decides — nothing runs on it until they say yes." in out
    assert "You're in" not in out


def test_the_chat_waits_fifty_seconds_for_an_ask(chat):
    """An ask is a grant on an allow-all computer; the bridge allows it 35 s plus a
    token refresh, and giving up first reported a landed join as a dead bridge."""
    chat.posts["/device/ask"] = _joined()
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    asks = [c for c in chat.calls if c[1] == "/device/ask"]
    assert asks[0][3] == 50


def test_an_unconfirmed_ask_says_it_may_have_gone_through(chat):
    chat.posts["/device/ask"] = (502, {"reason": "ask_unconfirmed",
                                       "error": "ask_unconfirmed"})
    sr.cmd_device_ask(_ns(device="dev-j9-0000"))
    out = chat.out()
    assert "may have gone through" in out
    assert "Couldn’t ask" not in out
    # ⛔ WAVE 12 REPAIR (cross-verify F23): an ask that went through waits in the
    # REQUESTS list — "your computers" alone showed only the join.
    assert "Ask me for your requests before asking again" in out


def test_an_ask_that_was_never_sent_says_so(chat):
    """⛔⛔ WAVE 12 REPAIR (cross-verify F23). A sign-in refresh that failed before
    the ask left was answered "that may have gone through"; the bridge now tells
    the two apart, and this is the sentence for the one where nothing went out."""
    chat.posts["/device/ask"] = (502, {"reason": "ask_not_sent",
                                       "error": "ask_not_sent"})
    assert sr.cmd_device_ask(_ns(device="dev-j9-0000")) != 0
    out = chat.out()
    assert "nothing was sent" in out
    assert "may have gone through" not in out and "ask_not_sent" not in out
    # ⛔ WAVE 12 REPAIR 3 (cross-verify H18): the bridge sends this code for a
    # connection that never opened too — the chat names both causes, like the
    # terminal, rather than blaming a sign-in that may have been fine.
    assert "couldn’t reach the app or refresh its sign-in" in out


# ── sr.py device-requests, owner half ─────────────────────────────────────────

def test_an_allow_all_owner_is_told_why_nobody_waits(chat):
    """⛔⛔ "Nobody is waiting on your computers" read as "nobody is using it" while
    up to 25 people were on the machine."""
    chat.gets["/devices/requests"] = (200, {"requests": [], "incoming": []})
    chat.gets["/devices"] = (200, {"devices": [dict(OWNED_OPEN), dict(SHARED)]})
    sr.cmd_device_requests(_ns())
    out = chat.out()
    assert ("“Studio PC” lets anyone join at once, so nobody waits here — see who's "
            "on it in the web app (Shared with).") in out
    # ⛔ A computer this account only shares is not its to report on.
    assert "Their Mac” lets anyone join" not in out


def test_the_line_is_not_said_over_somebody_still_waiting(chat):
    """Past the instant-join limit the web app files an ordinary ask — "nobody
    waits here" would be false over it."""
    chat.gets["/devices/requests"] = (200, {"requests": [], "incoming": [
        {"deviceId": "dev-a1", "deviceLabel": "Studio PC", "requesterUid": "u7",
         "requesterLabel": "Sam"}]})
    chat.gets["/devices"] = (200, {"devices": [dict(OWNED_OPEN)]})
    sr.cmd_device_requests(_ns())
    assert "nobody waits here" not in chat.out()


def test_no_line_for_a_computer_that_asks(chat):
    chat.gets["/devices/requests"] = (200, {"requests": [], "incoming": []})
    chat.gets["/devices"] = (200, {"devices": [dict(OWNED)]})
    sr.cmd_device_requests(_ns())
    assert "nobody waits here" not in chat.out()


def test_a_failed_second_look_adds_nothing_and_breaks_nothing(chat):
    chat.gets["/devices/requests"] = (200, {"requests": [], "incoming": []})
    chat.gets["/devices"] = (502, {"error": "boom"})
    assert sr.cmd_device_requests(_ns()) == 0
    out = chat.out()
    assert "Nobody is waiting on your computers." in out
    assert "nobody waits here" not in out


# ── the two ask tables stay in step ───────────────────────────────────────────

def test_both_clients_word_ask_unconfirmed():
    assert "ask_unconfirmed" in sr._ASK_ERRORS and "ask_unconfirmed" in cli._ASK_FAILURES
    assert "ask_not_sent" in sr._ASK_ERRORS and "ask_not_sent" in cli._ASK_FAILURES
    assert set(sr._ASK_ERRORS) == set(cli._ASK_FAILURES)


# ── the terminal ─────────────────────────────────────────────────────────────

@pytest.fixture()
def term(monkeypatch, capsys):
    calls: list = []
    box: dict = {"get": {}, "post": {}}
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _m: None)
    monkeypatch.setattr(cli, "_bridge_get",
                        lambda p, timeout=10.0: (calls.append(("GET", p, None, timeout)),
                                                 box["get"].get(p))[1])
    monkeypatch.setattr(cli, "_bridge_post",
                        lambda p, body=None, timeout=30.0: (
                            calls.append(("POST", p, body, timeout)),
                            box["post"].get(p))[1])
    box["get"]["/devices"] = (200, {"devices": [dict(OWNED)], "selectedDeviceId": "dev-a1"})
    return SimpleNamespace(box=box, calls=calls, out=lambda: capsys.readouterr().out)


def _run(argv):
    return cli.build_parser().parse_args(argv)


def test_terminal_allow_all_yes_posts_both_and_prints_what_it_means(term):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "public", "allowAll": True,
        "deviceName": "Studio PC", "publicLabel": "Studio PC"})
    ns = _run(["device", "allow-all", "dev-a1", "yes"])
    assert ns.func(ns) == 0
    posts = [c[2] for c in term.calls if c[0] == "POST"]
    assert posts == [{"deviceId": "dev-a1", "visibility": "public", "allowAll": True}]
    out = term.out()
    assert "Studio PC now lets anyone join at once." in out
    assert "Anyone signed in can join it at once — up to 25 people" in out
    # ⛔ WAVE 12 REPAIR (cross-verify F24): the canonical sentence, on one line.
    assert f"     {CANON}\n" in out
    assert "You still approve" not in out


def test_terminal_allow_all_no_posts_allow_all_alone(term):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "public", "allowAll": False,
        "deviceName": "Studio PC"})
    ns = _run(["device", "allow-all", "dev-a1", "no"])
    ns.func(ns)
    posts = [c[2] for c in term.calls if c[0] == "POST"]
    assert posts == [{"deviceId": "dev-a1", "allowAll": False}]
    out = term.out()
    assert "no longer lets anyone join" in out and "keeps access" in out


def test_terminal_visibility_public_allow_all(term):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "public", "allowAll": True,
        "deviceName": "Studio PC"})
    ns = _run(["device", "visibility", "dev-a1", "public", "--allow-all"])
    ns.func(ns)
    posts = [c[2] for c in term.calls if c[0] == "POST"]
    assert posts == [{"deviceId": "dev-a1", "visibility": "public", "allowAll": True}]


def test_terminal_visibility_private_allow_all_is_refused(term):
    ns = _run(["device", "visibility", "dev-a1", "private", "--allow-all"])
    assert ns.func(ns) == 1
    assert not [c for c in term.calls if c[0] == "POST"]


def test_terminal_plain_public_on_an_allow_all_computer_never_says_you_approve(term):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": False, "visibility": "public", "allowAll": True,
        "deviceName": "Studio PC"})
    ns = _run(["device", "visibility", "dev-a1", "public"])
    ns.func(ns)
    out = term.out()
    assert "You still approve" not in out and "already lets anyone join" in out


def test_terminal_plain_public_still_says_you_approve(term):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "public", "allowAll": False,
        "deviceName": "Studio PC"})
    ns = _run(["device", "visibility", "dev-a1", "public"])
    ns.func(ns)
    posts = [c[2] for c in term.calls if c[0] == "POST"]
    assert posts == [{"deviceId": "dev-a1", "visibility": "public"}]
    assert "You still approve every" in term.out()


def test_terminal_owned_row_says_anyone_can_join(term):
    term.box["get"]["/devices"] = (200, {"devices": [dict(OWNED_OPEN)],
                                         "selectedDeviceId": "dev-a1"})
    ns = _run(["device"])
    ns.func(ns)
    assert "(owned, online, public, anyone can join)" in term.out()


def test_terminal_public_row_joins_at_once_and_full_wins(term):
    term.box["get"]["/devices/public"] = (200, {"devices": [PUB_OPEN, PUB_OPEN_FULL],
                                                "truncated": False})
    ns = _run(["device", "public"])
    ns.func(ns)
    out = term.out()
    lines = {line.split("id=")[-1]: line for line in out.splitlines() if "id=" in line}
    assert "(joins at once)" in lines["dev-j9"]
    assert "(can't take anyone else)" in lines["dev-j8"]
    assert "(joins at once)" not in lines["dev-j8"]
    assert cli._PUBLIC_JOIN_INVITE_T in out


def test_terminal_rows_read_only_a_strict_public_true(term):
    """⛔ The terminal's own copy of both marks: a private computer's leftover tick
    and a malformed public bit read as today's approval flow."""
    term.box["get"]["/devices"] = (200, {"devices": [
        dict(OWNED, visibility="private", allowAll=True)], "selectedDeviceId": "dev-a1"})
    ns = _run(["device"])
    ns.func(ns)
    assert "anyone can join" not in term.out()
    term.box["get"]["/devices/public"] = (200, {"devices": [dict(PUB_OPEN, allowAll="true")],
                                                "truncated": False})
    ns = _run(["device", "public"])
    ns.func(ns)
    out = term.out()
    assert "(joins at once)" not in out and cli._PUBLIC_ASK_INVITE_T in out


def test_terminal_join_says_joined_and_waits_fifty(term):
    term.box["post"]["/device/ask"] = _joined(selected=True)
    ns = _run(["device", "ask", "dev-j9"])
    assert ns.func(ns) == 0
    out = term.out()
    assert "Joined — DG shared lets anyone in (now selected)." in out
    assert "owner decides" not in out
    asks = [c for c in term.calls if c[1] == "/device/ask"]
    assert asks[0][3] == 50.0


def test_terminal_unconfirmed_ask_points_at_the_requests_list(term):
    """⛔ WAVE 12 REPAIR (cross-verify F23): an ask that went through waits in
    `agent device requests`; `agent device` alone shows only a join."""
    term.box["post"]["/device/ask"] = (502, {"reason": "ask_unconfirmed",
                                             "error": "ask_unconfirmed"})
    ns = _run(["device", "ask", "dev-j9"])
    assert ns.func(ns) == 1
    out = term.out()
    assert "may have gone through" in out and "`agent device requests`" in out


def test_terminal_ask_never_sent_says_so(term):
    term.box["post"]["/device/ask"] = (502, {"reason": "ask_not_sent",
                                             "error": "ask_not_sent"})
    ns = _run(["device", "ask", "dev-j9"])
    assert ns.func(ns) == 1
    out = term.out()
    assert "nothing was sent" in out
    assert "may have gone through" not in out and "ask_not_sent" not in out
    # ⛔ WAVE 12 REPAIR 3 (cross-verify H18): the bridge sends this code for a
    # connection that never opened too, so the sentence names both causes rather
    # than blaming a sign-in that may have been fine.
    assert "could not reach the app or refresh its sign-in" in out


# ── wave 12 repair 3 (cross-verify H22): one sentence for what the owner sees ─
# ⛔⛔ THE ASK SAID "your name — or your email, if you have not set one" AND THE
# JOIN SAID "name and email" — the same exchange, two claims. The owner's Shared
# with shows both once somebody is on the computer, and the web's Join and the
# chat's ask confirm say so word for word.
OWNER_SEES = "The owner sees your name and email."


def test_terminal_ask_says_the_owner_sees_name_and_email(term):
    term.box["post"]["/device/ask"] = (200, {"ok": True, "status": "pending"})
    ns = _run(["device", "ask", "dev-j9"])
    assert ns.func(ns) == 0
    out = term.out()
    assert f"     {OWNER_SEES}\n" in out
    assert "or your email" not in out


def test_terminal_join_says_the_same_sentence(term):
    term.box["post"]["/device/ask"] = _joined()
    ns = _run(["device", "ask", "dev-j9"])
    assert ns.func(ns) == 0
    out = term.out()
    assert f"     {OWNER_SEES} Your research runs on their AI accounts.\n" in out
    assert "or your email" not in out


def test_terminal_going_private_on_an_open_computer_says_who_keeps_access(term):
    """⛔ WAVE 12 REPAIR (cross-verify F26), the terminal's copy of the chat line."""
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "changed": True, "visibility": "private", "allowAll": False,
        "allowAllWas": True, "deviceName": "Studio PC"})
    ns = _run(["device", "visibility", "dev-a1", "private"])
    assert ns.func(ns) == 0
    out = term.out()
    assert "Studio PC is now private." in out
    assert ("Anyone who already joined keeps access — remove people in the web app "
            "(Shared with).") in out


@pytest.mark.parametrize("extra", [{"changed": True, "allowAllWas": False},
                                   {"changed": True},
                                   {"changed": False, "allowAllWas": True}])
def test_terminal_going_private_is_silent_about_joiners_when_nobody_could_join(term, extra):
    term.box["post"]["/device/visibility"] = (200, {
        "ok": True, "visibility": "private", "allowAll": False,
        "deviceName": "Studio PC", **extra})
    ns = _run(["device", "visibility", "dev-a1", "private"])
    ns.func(ns)
    assert "keeps access" not in term.out()


def test_terminal_requests_tell_an_allow_all_owner_why_nobody_waits(term):
    """⛔⛔ "Nobody is waiting on your computers" read as "nobody is using it" while
    up to 25 people were on the machine — and a computer this account only
    SHARES is not its to report on."""
    term.box["get"]["/devices/requests"] = (200, {"requests": [], "incoming": []})
    term.box["get"]["/devices"] = (200, {"devices": [dict(OWNED_OPEN), dict(SHARED)]})
    ns = _run(["device", "requests"])
    ns.func(ns)
    out = term.out()
    assert ("Studio PC lets anyone join at once, so nobody waits here — see who's "
            "on it in the web app (Shared with).") in out
    assert "Their Mac lets anyone join" not in out


def test_terminal_requests_with_people_waiting_still_name_the_open_computer(term):
    """With somebody waiting on ONE computer, the owner's OTHER, allow-all computer
    still gets its line — and the one with a real ask never does: past the
    instant-join limit the web app files an ordinary ask, and "nobody waits here"
    over it would be false."""
    term.box["get"]["/devices/requests"] = (200, {"requests": [], "incoming": [
        {"deviceId": "dev-a1", "deviceLabel": "Studio PC", "requesterUid": "u7",
         "requesterLabel": "Sam"}]})
    term.box["get"]["/devices"] = (200, {"devices": [
        dict(OWNED_OPEN), dict(OWNED_OPEN, id="dev-a2", name="Lab PC")]})
    ns = _run(["device", "requests"])
    ns.func(ns)
    out = term.out()
    assert "Lab PC lets anyone join at once, so nobody waits here" in out
    assert "Studio PC lets anyone join at once" not in out


def test_terminal_wsl_hint_for_allow_all(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "_redirect_if_wsl",
                        lambda m: seen.setdefault("hint", m) and 0)
    ns = _run(["device", "allow-all", "dev-a1", "yes"])
    ns.func(ns)
    assert seen["hint"] == ("Let anyone join a computer from chat:  "
                            "/sr let anyone join my computer")


# ── wave 12 repair 2 (cross-verify G27): the WSL hint points the SAME way ────
# ⛔⛔ THE HINT WAS PICKED BY SUBCOMMAND ALONE. `agent device allow-all <id> no`
# under WSL told the person to say "/sr let anyone join my computer" — which the
# chat answers with the confirm that OPENS the door they had asked to close — and
# `visibility <id> private` pointed at "make my computer public". Each row runs
# the REAL redirect (no bridge here, the runtime in a WSL distro), takes the
# phrase it printed, and hands it to the chat's own router: the direction the
# router reads must be the direction the command was given.

def _printed_chat_phrase(out: str) -> str:
    plain =re.sub(r"\x1b\[[0-9;]*m", "", out)
    hits = [ln.split("/sr ", 1)[1].strip() for ln in plain.splitlines()
            if "from chat:" in ln and "/sr " in ln]
    assert len(hits) == 1, plain
    return hits[0]


@pytest.mark.parametrize("argv,check", [
    # OFF — the router must ACT, in the off direction, with no confirm
    (["device", "allow-all", "dev-a1", "no"],
     lambda got: got == (["device-allow-all", "no"], None)),
    (["device", "visibility", "dev-a1", "private"],
     lambda got: got == (["device-visibility", "private"], None)),
    # ON — the router must ask the confirm for THAT door, never act unasked
    (["device", "allow-all", "dev-a1", "yes"],
     lambda got: got[0] is None and "at once" in " ".join(got[1])),
    (["device", "visibility", "dev-a1", "public", "--allow-all"],
     lambda got: got[0] is None and "at once" in " ".join(got[1])),
    (["device", "visibility", "dev-a1", "public"],
     lambda got: got[0] is None and "find that computer" in " ".join(got[1])
     and "at once" not in " ".join(got[1])),
], ids=["allow-all-no", "visibility-private", "allow-all-yes",
        "public-allow-all", "public"])
def test_the_wsl_hint_says_a_phrase_the_chat_reads_the_same_way(
        monkeypatch, capsys, argv, check):
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: "Ubuntu")
    ns = _run(argv)
    assert ns.func(ns) == 0
    phrase = _printed_chat_phrase(capsys.readouterr().out)
    got = sr._nl_resolve(phrase)
    assert check(got), (argv, phrase, got)
