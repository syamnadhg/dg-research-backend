"""The connection code: the link first, the code as the "or" — and never taken for an access code (Mac brief, 2026-09-25).

⭐⭐ WHAT CHANGED ON THE SERVER. superresearch.io/connect is the sign-in page now, and
the broker's reply keeps its shape {code, pollToken, verifyUrl, expiresIn} with new
values: `code` is a short connection code ("WDJB-MJHT", eight letters shown
XXXX-XXXX), `verifyUrl` is https://superresearch.io/connect?runtime=hermes&code=WDJB-MJHT
(the code always LAST), and the code lives ten minutes. Opened without a link, the
page takes the code typed. The chat printed only the link, so a person whose link
would not open — on another device, say — had nothing to type.

⭐ WHAT THIS FILE PINS:
  • `login`, a research asked while signed out, and the terminal's `agent login` all
    print the link FIRST, then — only for a short code — "Or, if the link won't
    open …: go to <the link's page> and enter this connection code: <code>", then
    "Either way, check the page shows the same connection code, then tap
    Authenticate." The chat's copy and the terminal's are held to each other.
  • The page address is the link up to its "?", so it always matches the link.
  • An older broker's 43-character token, or no code at all: the link alone.
  • Nothing but a space or the line's end follows a URL ("/connect." is a 404).
  • ⛔⛔ /device/pair refuses the pending sign-in's connection code — any case, dash
    or space — BEFORE it asks whether anyone is signed in, and claims nothing; the
    chat and the terminal word the refusal from their own tables, keyed on the
    reply's `reason`.
  • ⛔ A connection code pasted into the chat never claims anything, whichever way
    it travels: through `do` (the router), or through `device-add`, which SKILL.md
    sends any bare 8-character code to.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import requests

from facade import bridge, cli

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
_SKILL = _SCRIPTS.parent / "SKILL.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_connection_code_0925", "sr.py")

CODE = "WDJB-MJHT"
LINK = "https://superresearch.io/connect?runtime=hermes&code=WDJB-MJHT"
PAGE = "https://superresearch.io/connect"
LONG = "Qm9vUGFpckNvZGVfbG9uZ190b2tlbl9mb3JfYWdlbnQ"  # an older broker's 43-char token
assert len(LONG) == 43

LINK_LINE = f"Log in here: {LINK}"
OR_LINE = ("Or, if the link won't open (for example on another device): go to "
           f"{PAGE} and enter this connection code: {CODE}")
CHECK_LINE = ("Either way, check the page shows the same connection code, then tap "
              "Authenticate.")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_URL = re.compile(r"https?://\S+")


def _reply(code=CODE, url=LINK) -> dict:
    out = {"verifyUrl": url, "expiresIn": 600}
    if code is not None:
        out["code"] = code
    return out


def _login(monkeypatch, capsys, reply: dict) -> str:
    posts = []
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (200, {"authed": False}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        posts.append(p) or (200, reply)))
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 0))
    assert sr.main(["login"]) == 0
    assert posts == ["/login/remote/start"], posts
    return capsys.readouterr().out


def _terminal(monkeypatch, capsys, reply: dict) -> list[str]:
    monkeypatch.setattr(cli, "_bridge_post",
                        lambda path, body=None, timeout=30.0: (200, reply))
    assert cli._remote_signin(open_browser=False, poll=False) == "started"
    out = _ANSI.sub("", capsys.readouterr().out)
    return [ln[2:] if ln.startswith("  ") else ln for ln in out.splitlines()]


# ── 1. the sign-in message ────────────────────────────────────────────────────

def test_login_prints_the_link_then_the_code_then_the_check(monkeypatch, capsys):
    out = _login(monkeypatch, capsys, _reply())
    assert out.splitlines() == [LINK_LINE, OR_LINE, CHECK_LINE], out


def test_the_page_address_is_the_link_up_to_its_question_mark(monkeypatch, capsys):
    """⛔ Never a literal. The web app builds the link on SUPER_AGENT_CONNECT_ORIGIN
    when a local E2E sets it, and the typed code has to go to the same page."""
    out = _login(monkeypatch, capsys,
                 _reply(url="http://localhost:3000/connect?code=WDJB-MJHT"))
    lines = out.splitlines()
    assert lines[0] == "Log in here: http://localhost:3000/connect?code=WDJB-MJHT"
    assert ("go to http://localhost:3000/connect and enter this connection code: "
            "WDJB-MJHT") in lines[1], out
    assert "superresearch.io" not in out, out


def test_the_code_is_printed_as_the_bridge_handed_it(monkeypatch, capsys):
    """⛔ Never reformatted: the person compares it with the page, character for
    character."""
    out = _login(monkeypatch, capsys, _reply(code="wdjb-mjht"))
    assert out.splitlines()[1].endswith("enter this connection code: wdjb-mjht"), out


@pytest.mark.parametrize("code", [LONG, None, "", "   "],
                         ids=["43-char token", "no code", "empty", "blank"])
def test_a_long_code_or_none_is_the_link_alone(monkeypatch, capsys, code):
    """The brief's "link only, no code printed", read as: no code lines. `login`'s
    "Tap Authenticate when the page opens" line, which it printed before this
    change, stays after the link — it names no code."""
    out = _login(monkeypatch, capsys, _reply(code=code))
    lines = out.splitlines()
    assert lines[0] == LINK_LINE, out
    assert LONG not in out.replace(LINK, ""), "the long token is never printed as a code"
    assert "connection code" not in out and "Or," not in out and "Either way" not in out, out
    assert "Tap Authenticate" in out, ("the link alone still says what to tap", out)


@pytest.mark.parametrize("n,shown", [(12, True), (13, False)])
def test_the_code_lines_stop_at_twelve_characters(monkeypatch, capsys, n, shown):
    code = ("WDJB-MJHT-KLMN" * 2)[:n]
    out = _login(monkeypatch, capsys, _reply(code=code))
    assert (f"enter this connection code: {code}" in out) is shown, out


def test_nothing_but_a_space_follows_a_url(monkeypatch, capsys):
    """⛔ Chat apps link a trailing "." or ",", and "/connect." is a 404 — the web
    app redirects /install's punctuation and has no such rule for /connect."""
    out = _login(monkeypatch, capsys, _reply())
    urls = _URL.findall(out)
    assert urls == [LINK, PAGE], urls


@pytest.mark.parametrize("armed", [True, False])
def test_a_research_asked_while_signed_out_prints_the_same_lines(monkeypatch, capsys,
                                                                 armed):
    def _post(path, body=None):
        if path == "/research":
            return 401, {"error": "not signed in"}
        if path == "/login/remote/start":
            return 200, _reply()
        return 200, {}
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_get", lambda path, **kw: (200, {"authed": False}))
    monkeypatch.setattr(sr, "_prepare_stream_arm",
                        lambda: (["cronjob: create …"], {"armed": armed}, 0))
    sr.main(["research", "the EV battery market"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[1:4] == [LINK_LINE, OR_LINE, CHECK_LINE], out
    assert "pick this up" in lines[0], out
    # ⛔ "Log in here" opens the link's own line now; said in the line above too it
    # read as a stutter.
    assert out.count("Log in here") == 1, out
    assert out.index(CHECK_LINE) < out.index(sr._AGENT_ONLY_MARKER), (
        "the sign-in lines are the person's, above the assistant-only block")


def test_json_carries_the_code_for_a_signed_out_research(monkeypatch, capsys):
    monkeypatch.setattr(sr, "_post", lambda path, body=None: (
        (401, {"error": "not signed in"}) if path == "/research" else (200, _reply())))
    monkeypatch.setattr(sr, "_get", lambda path, **kw: (200, {"authed": False}))
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {"armed": True}, 0))
    sr.main(["--json", "research", "the EV battery market"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["verifyUrl"] == LINK and payload["code"] == CODE, payload


def test_the_terminal_prints_the_same_three_lines(monkeypatch, capsys):
    lines = _terminal(monkeypatch, capsys, _reply())
    assert lines[:3] == [LINK_LINE, OR_LINE, CHECK_LINE], lines
    text = "\n".join(lines)
    assert "Approve & connect" not in text, "the page's button is Authenticate"
    assert text.count("tap Authenticate") == 1, ("said once, not twice in a row", text)


@pytest.mark.parametrize("code", [LONG, None, "", "   "],
                         ids=["43-char token", "no code", "empty", "blank"])
def test_the_terminal_with_a_long_code_or_none_is_the_link_alone(monkeypatch, capsys,
                                                                 code):
    lines = _terminal(monkeypatch, capsys, _reply(code=code))
    text = "\n".join(lines)
    assert lines[0] == LINK_LINE, lines
    assert LONG not in text.replace(LINK, "") and "connection code" not in text, text
    assert "then tap Authenticate." in text, text


@pytest.mark.parametrize("reply", [
    _reply(), _reply(code=LONG), _reply(code=None), _reply(code="ABCDEFGHJKLM"),
    _reply(code="ABCDEFGHJKLMN"), _reply(url="http://localhost:3000/connect?code=WDJB-MJHT"),
    _reply(url="https://superresearch.io/c/XYZ"),
], ids=["short", "long", "none", "12", "13", "local origin", "no query"])
def test_the_chat_and_the_terminal_print_one_message(monkeypatch, capsys, reply):
    """⛔ TWO COPIES, ONE MESSAGE. sr.py is standalone and cannot import the package,
    so this assertion is the only thing that keeps them together."""
    want = sr._signin_link_lines(reply)
    got = _terminal(monkeypatch, capsys, reply)
    assert got[:len(want)] == want, got
    assert not any("connection code" in ln for ln in got[len(want):]), (
        "the terminal printed a code line the chat did not", got)


# ── 2. /device/pair refuses the pending sign-in's connection code ─────────────

class _FS:
    def __init__(self, _tp):
        pass

    def list_devices(self, uid):
        return [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]


@contextmanager
def _bridge(monkeypatch, *, signed_in: bool, flow_state: str | None = "pending",
            verify_url: str = LINK, expires_in: float = 600):
    """A real bridge on loopback with a sign-in in `flow_state` (None: no sign-in),
    every claim recorded, and both clients pointed at it."""
    claims: list = []
    monkeypatch.setattr(bridge, "_fe_api_post", lambda sess, path, payload, **kw: (
        claims.append((path, payload)) or (200, {"ok": True, "action": "initial-pair",
                                                 "deviceId": "dev-new"})))
    monkeypatch.setattr(bridge, "FirestoreRest", _FS)
    sel = {"v": "dev-a"}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device",
                        lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda **kw: None)
    monkeypatch.setattr(bridge, "_backend_version", lambda: None)
    state = bridge.BridgeState()
    state.set_session(NS(uid="u1", email="e@x.y", id_token=lambda force=False: "tok")
                      if signed_in else None)
    if flow_state:
        flow = bridge.RemoteFlow("PT", CODE, verify_url, time.time() + expires_in)
        flow.state = flow_state
        state.set_remote(flow)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(httpd.server_address[1]))
    monkeypatch.setattr(cli.config, "bridge_origin", lambda: base)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _hint: None)
    monkeypatch.setattr(cli.connect, "detect_targets", lambda *a, **k: [])
    try:
        yield base, claims
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("typed", ["WDJB-MJHT", "wdjb-mjht", "WDJBMJHT", "wdjbmjht",
                                   " WDJB MJHT ", "WDJB–MJHT", "wdjb_mjht"])
@pytest.mark.parametrize("signed_in", [False, True], ids=["signed out", "signed in"])
def test_the_pending_sign_ins_code_is_refused_and_nothing_is_claimed(
        monkeypatch, typed, signed_in):
    """⛔⛔ SIGNED OUT IS THE USUAL CASE: a pending sign-in almost always means nobody
    is signed in. Checked after the session, the person would read "not signed in"
    — and the fresh sign-in that invites voids the code on the page they have open."""
    with _bridge(monkeypatch, signed_in=signed_in) as (base, claims):
        r = requests.post(base + "/device/pair", json={"code": typed}, timeout=10)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["reason"] == "signin_code", body
    assert "connection code" in body["error"] and PAGE in body["error"], body
    assert claims == [], "nothing may be claimed for a connection code"


def test_the_refusal_names_the_links_own_page_and_nothing_is_glued_to_it(monkeypatch):
    """An older chat client relays this sentence as it stands, so it must read on its
    own — and nothing but a space may follow the URL."""
    with _bridge(monkeypatch, signed_in=False,
                 verify_url="http://localhost:3000/connect?code=WDJB-MJHT") as (base, _c):
        body = requests.post(base + "/device/pair", json={"code": CODE}, timeout=10).json()
    assert _URL.findall(body["error"]) == ["http://localhost:3000/connect"], body
    assert body["error"].startswith("that's your connection code"), body


def test_the_refusal_is_logged_and_the_code_is_not(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="facade.bridge"):
        with _bridge(monkeypatch, signed_in=True) as (base, _c):
            requests.post(base + "/device/pair", json={"code": CODE}, timeout=10)
    text = caplog.text
    assert "connection code" in text and "nothing claimed" in text, text
    assert "WDJB" not in text.upper() and "MJHT" not in text.upper(), (
        "bridge.log goes to support — the code is never written to it", text)


@pytest.mark.parametrize("flow_state", [None, "pending"], ids=["no sign-in", "pending"])
def test_an_access_code_is_still_claimed(monkeypatch, flow_state):
    with _bridge(monkeypatch, signed_in=True, flow_state=flow_state) as (base, claims):
        r = requests.post(base + "/device/pair", json={"code": "K7XQ-9B2M"}, timeout=10)
    assert r.status_code == 200, r.text
    assert claims == [("/api/devices/claim", {"code": "K7XQ-9B2M"})], claims


@pytest.mark.parametrize("flow_state", ["expired", "error"])
def test_an_expired_or_failed_sign_ins_code_is_not_refused(monkeypatch, flow_state):
    """A flow that expired or failed is not checked: its code goes to the claim
    route like any other."""
    with _bridge(monkeypatch, signed_in=True, flow_state=flow_state) as (base, claims):
        r = requests.post(base + "/device/pair", json={"code": CODE}, timeout=10)
    assert r.status_code == 200, r.text
    assert claims == [("/api/devices/claim", {"code": CODE})], claims


@pytest.mark.parametrize("typed", ["WDJB-MJHT", "wdjbmjht", "wdjb mjht"])
def test_a_just_connected_sign_ins_code_is_refused_in_its_own_words(monkeypatch, typed):
    """⭐ OWNER, 2026-09-25: right after signing in is the likeliest moment somebody
    pastes the code back into the chat. For the rest of the code's life it is
    refused — "you're already signed in with it" — and nothing is claimed."""
    with _bridge(monkeypatch, signed_in=True, flow_state="connected") as (base, claims):
        r = requests.post(base + "/device/pair", json={"code": typed}, timeout=10)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["reason"] == "signin_code_used", body
    assert "already signed in" in body["error"], body
    assert "open the link" not in body["error"], body
    assert claims == [], claims


def test_a_connected_sign_ins_code_is_claimed_like_any_other_once_it_has_expired(monkeypatch):
    """Past the code's life it can mean nothing, so it is no longer refused."""
    with _bridge(monkeypatch, signed_in=True, flow_state="connected",
                 expires_in=-1) as (base, claims):
        r = requests.post(base + "/device/pair", json={"code": CODE}, timeout=10)
    assert r.status_code == 200, r.text
    assert claims == [("/api/devices/claim", {"code": CODE})], claims


def test_both_clients_word_the_just_connected_refusal(monkeypatch, capsys):
    with _bridge(monkeypatch, signed_in=True, flow_state="connected") as (_base, claims):
        rc = sr.main(["device-add", "wdjb-mjht"])
        out = capsys.readouterr().out
        assert rc == 1
        assert out.strip() == "✗ " + sr._PAIR_ERRORS["signin_code_used"], out
        rc = cli.cmd_device(NS(device_command="add", code="WDJB-MJHT", runtime=None,
                               dest=None, verbose=False))
        out = _ANSI.sub("", capsys.readouterr().out)
    assert rc == 1
    assert cli._PAIR_FAILURES["signin_code_used"] in out, out
    assert claims == []


def test_the_chat_words_the_refusal_from_its_own_table(monkeypatch, capsys):
    """⛔ Keyed on `reason`: a lookup by `error` alone never reaches the entry and
    prints "couldn’t add the device: that's your connection code — …"."""
    with _bridge(monkeypatch, signed_in=False) as (_base, claims):
        rc = sr.main(["device-add", "wdjb-mjht"])
    out = capsys.readouterr().out
    assert rc == 1
    assert out.strip() == "✗ " + sr._PAIR_ERRORS["signin_code"], out
    assert "couldn’t add" not in out and "not signed in" not in out.lower(), out
    assert claims == []


def test_the_terminal_words_the_refusal_from_its_own_table(monkeypatch, capsys):
    with _bridge(monkeypatch, signed_in=True) as (_base, claims):
        rc = cli.cmd_device(NS(device_command="add", code="WDJB-MJHT", runtime=None,
                               dest=None, verbose=False))
    out = _ANSI.sub("", capsys.readouterr().out)
    assert rc == 1
    assert cli._PAIR_FAILURES["signin_code"] in out, out
    assert "not here" not in out, ("the bridge's raw sentence reached the screen", out)
    assert claims == []


def test_a_revoked_session_keeps_its_signed_out_sentence(monkeypatch, capsys):
    """⛔ Only a reason the table words wins. The 401 relay's `reason: "revoked"`
    looked up as a key would print "couldn’t add the device: revoked"."""
    reply = (401, {"reason": "revoked", "error": "not signed in — run /login"})
    monkeypatch.setattr(sr, "_post", lambda path, body=None, **kw: reply)
    assert sr.main(["device-add", "K7XQ-9B2M"]) == 1
    assert "log you in" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_bridge_post", lambda path, body=None, timeout=30.0: reply)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _hint: None)
    monkeypatch.setattr(cli.connect, "detect_targets", lambda *a, **k: [])
    cli.cmd_device(NS(device_command="add", code="K7XQ-9B2M", runtime=None, dest=None,
                      verbose=False))
    assert "agent login" in _ANSI.sub("", capsys.readouterr().out)


# ── a connection code pasted into the chat ────────────────────────────────────

_PASTED = ["WDJB-MJHT", "wdjbmjht", "WDJB MJHT", "code WDJB-MJHT", "pair WDJB-MJHT",
           "use this code WDJB-MJHT", "my connection code is WDJB-MJHT",
           "add device WDJB-MJHT", "here's the code: WDJB-MJHT", LINK]


@pytest.mark.parametrize("said", _PASTED)
def test_a_connection_code_pasted_in_chat_claims_nothing_through_the_router(
        monkeypatch, capsys, said):
    """⛔⛔ THROUGH THE REAL ROUTER AND WHATEVER IT RUNS. Today `do` sends none of
    these to `device-add` — its code pattern needs a digit, and a connection code
    never has one — so the invariant is written so it survives a router that one
    day does: nothing is claimed, and a `device-add` it runs answers `signin_code`."""
    argv, _lines = sr._nl_resolve(said)
    with _bridge(monkeypatch, signed_in=True) as (_base, claims):
        sr.main(["do", said])
        out = capsys.readouterr().out
    assert claims == [], (said, argv, out)
    if argv and argv[0] == "device-add":
        assert sr._PAIR_ERRORS["signin_code"] in out, (said, out)


@pytest.mark.parametrize("pasted", ["WDJB-MJHT", "wdjbmjht"])
def test_the_skills_device_add_route_gets_the_connection_code_answer(monkeypatch, capsys,
                                                                     pasted):
    """⛔⛔ THE PATH A PASTED CODE ACTUALLY TAKES. SKILL.md sends any bare 8-character
    code straight to `sr.py device-add <code>`, with no `do` in between — so this is
    where the bridge's refusal has to land, signed in or out."""
    for signed_in in (True, False):
        with _bridge(monkeypatch, signed_in=signed_in) as (_base, claims):
            assert sr.main(["device-add", pasted]) == 1
            out = capsys.readouterr().out
        assert sr._PAIR_ERRORS["signin_code"] in out, (signed_in, out)
        assert claims == []


def test_the_chat_refusal_ends_with_the_page(monkeypatch):
    for said in (sr._PAIR_ERRORS["signin_code"], cli._PAIR_FAILURES["signin_code"]):
        assert said.rstrip().endswith(PAGE), said
        assert "connection code" in said


# ── SKILL.md ──────────────────────────────────────────────────────────────────

def test_the_skill_relays_the_link_and_the_code_and_never_pairs_with_it():
    text = " ".join(_SKILL.read_bytes().decode("utf-8").split())
    for phrase in (
        "relay the link AND the connection code exactly as it prints them, link first",
        "never shorten, invent or reformat the code",
        "checks the page shows the same connection code, then taps Authenticate",
        "typed only at superresearch.io/connect",
        "it is not an access code: **never** run `device-add` with it",
        "send the user **one** message: the link and connection code lines the "
        "client returned, as printed",
    ):
        assert phrase in text, phrase
