"""THE ONE ADD-A-COMPUTER LINE — the install link inside it, on every surface.

⭐⭐ MEASURED, NOT GUESSED (owner, 2026-09-24). In the Hermes history the install
link survived 0 of 3 relays of the no-computer `devices` screen. The screen put the
link LAST, as its own paragraph ("Don't have your own Research Computer yet? Set one
up: …") with a second code sentence under it ("It gives you an 8-char access
code…"). A condensing model drops a trailing paragraph and a conditional aside,
keeps ONE sentence about connecting a computer, and resolves a pronoun on its own —
"It" (the page) came back as "an 8-character access code from the Super Research
app", which is false for anybody without a computer.

⭐ THE OWNER'S LAYOUT, top to bottom: [any lead the caller prints] · "No research
computer on this account yet." · "Add a computer: set one up at
https://superresearch.io/install, then send me the 8-character access code the
computer shows (or one a computer's owner gave you)." · the Public computers
section · the in-band relay rule LAST, carrying the URL itself.

Every guard below reads what a surface PRINTS, not its source, except where the
surface cannot be driven here (the skill's frontmatter, the bridge's wire sentence).
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from facade import cli

_ROOT = Path(__file__).resolve().parents[1] / "facade"
sys.path.insert(0, str(_ROOT / "skill" / "scripts"))
import sr  # noqa: E402

_SKILL = _ROOT / "skill" / "SKILL.md"
_BRIDGE = _ROOT / "bridge.py"
URL = "https://superresearch.io/install"
M = sr._AGENT_ONLY_MARKER
PUB = {"devices": [{"deviceId": "d1", "label": "Macbook", "online": False,
                    "full": False}], "truncated": False}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


poll = _load("poll_add_line_0924", _ROOT / "skill" / "scripts" / "sr_attention_poll.py")


def _run(fn, ns) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(ns)
    return buf.getvalue()


def _get_empty(path, timeout=None):
    if path == "/status":
        return 200, {"authed": True, "email": "s@x.y", "agentUpdate": "0.1.34"}
    if path == "/devices":
        return 200, {"devices": [], "selectedDeviceId": None}
    if path.startswith("/devices/public"):
        return 200, PUB
    return 200, {}


_NEEDS_DEVICE = {"ts": 1, "email": "s@x.y", "needsDevice": True,
                 "topic": "creativity", "pendingTopic": ""}


@pytest.fixture()
def empty_account(monkeypatch):
    monkeypatch.setattr(sr, "_get", _get_empty)
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        400, {"reason": "no_devices", "error": "no devices yet"}))
    monkeypatch.setattr(sr, "_origin_from_env",
                        lambda: {"platform": "hermes", "chat_id": "c1"})


def _login_done(mp):
    # ⚠ 2026-09-25: `login-done` takes the note through `POST /signin/ack` (with
    # its news), and a "connected" flow counts only while `authed` says so.
    def _post(p, b=None, timeout=None):
        if p == "/signin/ack":
            return 200, {"ok": True, "authed": True, "email": "s@x.y",
                         "consumed": True, "signedIn": dict(_NEEDS_DEVICE)}
        return 200, {"state": "connected", "authed": True, "email": "s@x.y",
                     "pendingTopic": "creativity"}
    mp.setattr(sr, "_post", _post)
    return sr.cmd_login_wait, NS(json=False)


def _updates(mp):
    mp.setattr(sr, "_fetch_runs", lambda active=False, limit=20, via_agent=False: (
        200, {"signedIn": dict(_NEEDS_DEVICE)}, []))
    return sr.cmd_updates, NS(json=False, active=False)


# Every chat door that prints the whole no-computer screen and ENDS on it.
# ⚠ 2026-09-25 (owner): `status-account` left this table — a login answer is
# about login only (test_login_answers_login_only_0925.py pins what it says now).
CHAT_SCREENS = {
    "devices": lambda mp: (sr.cmd_devices, NS(json=False)),
    "research no_devices": lambda mp: (sr.cmd_research, NS(
        json=False, topic="creativity", device="", no_video=False, no_email=False)),
    "sign-in needsDevice": _login_done,
    "name lookup": lambda mp: (sr.cmd_device_use, NS(json=False, device="Macbook")),
    # ⛔ the door that printed the screen with no relay rule at all
    "updates needsDevice": _updates,
}


def _above(out: str) -> str:
    return out.partition(M)[0]


def _sentences(text: str) -> list[str]:
    """Sentences of a rendered screen. A line break ends one too — the rows and
    headings are their own units — and a URL's dots do not (no space follows)."""
    out = []
    for ln in text.splitlines():
        out += [s for s in re.split(r"(?<=[.!?])\s+", ln) if s.strip()]
    return out


def _bridge_no_devices_sentence() -> str:
    """The `no_devices` refusal exactly as the bridge sends it — read off the dict
    literal in its source, so the guard sees the implicit concatenation resolved."""
    tree = ast.parse(_BRIDGE.read_bytes().decode("utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {k.value: v for k, v in zip(node.keys, node.values)
                 if isinstance(k, ast.Constant)}
        reason = pairs.get("reason")
        if isinstance(reason, ast.Constant) and reason.value == "no_devices":
            return ast.literal_eval(pairs["error"])
    raise AssertionError("the bridge's no_devices refusal was not found")


def _term_out(monkeypatch, capsys, public=(200, PUB)) -> str:
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _m: None)
    monkeypatch.setattr(cli, "_bridge_get", lambda p, timeout=10.0: (
        public if p == "/devices/public"
        else (200, {"devices": [], "selectedDeviceId": None})))
    capsys.readouterr()
    assert cli.cmd_device(argparse.Namespace(device_command=None)) == 0
    return capsys.readouterr().out


def _watcher() -> str:
    return poll._signed_in_line({"email": "e@x.y", "needsDevice": True,
                                 "topic": "Golden Retrievers", "pendingTopic": ""})


# ── the layout: the URL on the add line, the add line before the public list ──

@pytest.mark.parametrize("name", list(CHAT_SCREENS))
def test_the_url_is_on_the_add_line_and_the_add_line_precedes_public_computers(
        empty_account, monkeypatch, name):
    fn, ns = CHAT_SCREENS[name](monkeypatch)
    lines = _above(_run(fn, ns)).splitlines()
    add = [i for i, ln in enumerate(lines) if "Add a computer:" in ln]
    pub = [i for i, ln in enumerate(lines) if ln.startswith(sr._PUBLIC_HEAD)]
    assert len(add) == 1 and pub, (name, lines)
    assert URL in lines[add[0]], (name, lines[add[0]])
    assert add[0] < pub[0], (name, add, pub)
    # ⛔ and the state line comes first — the screen says what happened before
    # what to do about it
    state = next(i for i, ln in enumerate(lines)
                 if "no research computer on this account yet" in ln.lower())
    assert state < add[0], (name, lines)


@pytest.mark.parametrize("name", list(CHAT_SCREENS))
def test_the_relay_rule_is_the_last_block_and_there_is_one(empty_account, monkeypatch,
                                                           name):
    fn, ns = CHAT_SCREENS[name](monkeypatch)
    out = _run(fn, ns)
    assert out.count(M) == 1, (name, out.count(M))
    assert out.rstrip().endswith(sr._EMPTY_STATE_RELAY), (name, out[-300:])


def test_the_relay_rule_carries_the_url_itself():
    """⛔ A RULE THAT ONLY NAMES "the install link" CANNOT PUT ONE BACK. The URL
    is written into it so a model that dropped it from the screen still has it."""
    assert URL in sr._EMPTY_STATE_RELAY
    assert "never say it comes from the app" in sr._EMPTY_STATE_RELAY


def test_updates_keeps_one_marker_when_a_re_arm_directive_is_already_there(
        empty_account, monkeypatch):
    """⛔ THE RULE JOINS THE BLOCK, IT DOES NOT OPEN A SECOND ONE. `updates` can
    already end on a re-arm directive under the marker; the rule is appended to
    that block as its last line."""
    fn, ns = _updates(monkeypatch)
    monkeypatch.setattr(sr, "_stream_health_lines",
                        lambda runs: sr._agent_directive_block(["ARM-DIRECTIVE"]))
    out = _run(fn, ns)
    assert out.count(M) == 1, out
    below = out.partition(M)[2]
    assert "ARM-DIRECTIVE" in below
    assert below.rstrip().endswith(sr._EMPTY_STATE_RELAY), below


def test_updates_attaches_no_rule_when_the_announce_did_not_need_a_device(monkeypatch):
    monkeypatch.setattr(sr, "_fetch_runs", lambda active=False, limit=20, via_agent=False: (
        200, {"signedIn": {"ts": 1, "email": "s@x.y", "autoStarted": True,
                           "topic": "creativity"}}, []))
    out = _run(sr.cmd_updates, NS(json=False, active=False))
    assert sr._EMPTY_STATE_RELAY not in out


# ── one shared constant for every chat surface that says how to add a computer ─

def test_every_chat_add_a_computer_surface_renders_the_shared_constant(monkeypatch):
    """⛔ ONE SENTENCE, NOT FOUR. The empty screen, the populated list's tail and
    the router's answer to "install Super Research" all print the SAME line — a
    second wording is how the link went missing from three of them.
    ⚠ 2026-09-25 (owner): the one-line sign-in confirmation was the fourth and
    carries NO add line now — a login answer is about login only."""
    monkeypatch.setattr(sr, "_RENDERING_LINES", False)
    assert sr._ADD_A_COMPUTER in sr._no_device_lines()
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (200, {
        "devices": [{"id": "m1", "name": "Studio Mac", "owned": True}],
        "selectedDeviceId": "m1"}))
    assert sr._ADD_A_COMPUTER in _run(sr.cmd_devices, NS(json=False)).splitlines()
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (200, {"devices": []}))
    assert sr._ADD_A_COMPUTER not in sr._connected_msg("e@x.y")
    assert sr._nl_resolve("how do I install super research") == (None, [sr._ADD_A_COMPUTER])


def test_the_shared_line_is_the_owners_wording():
    assert sr._ADD_A_COMPUTER == (
        "Add a computer: set one up at https://superresearch.io/install, then send me "
        "the 8-character access code the computer shows (or one a computer's owner "
        "gave you).")


# ── the three things a relay invented must not be in the bytes ───────────────

def _every_person_facing_screen(monkeypatch, capsys) -> dict:
    """Every no-computer screen a person reads, above any marker."""
    screens = {}
    for name, make in CHAT_SCREENS.items():
        with monkeypatch.context() as mp:
            mp.setattr(sr, "_get", _get_empty)
            mp.setattr(sr, "_post", lambda p, b=None, timeout=None: (
                400, {"reason": "no_devices", "error": "no devices yet"}))
            mp.setattr(sr, "_origin_from_env",
                       lambda: {"platform": "hermes", "chat_id": "c1"})
            fn, ns = make(mp)
            screens[f"chat: {name}"] = _above(_run(fn, ns))
    # ⚠ 2026-09-25 (owner): the one-line sign-in confirmation is not a
    # no-computer screen any more — it names no computer at all.
    screens["watcher: sign-in announce"] = _watcher()
    screens["terminal: agent device"] = _term_out(monkeypatch, capsys)
    screens["terminal: agent device, failed look"] = _term_out(monkeypatch, capsys,
                                                               public=None)
    screens["terminal: agent research (bridge)"] = _bridge_no_devices_sentence()
    return screens


def test_no_rendered_line_starts_with_it_gives_you(monkeypatch, capsys):
    """⛔⛔ "It gives you an 8-char access code" — "It" read as the web page."""
    for name, text in _every_person_facing_screen(monkeypatch, capsys).items():
        for ln in text.splitlines():
            assert not ln.strip().lower().startswith("it gives you"), (name, ln)


def test_no_screen_puts_app_in_the_sentence_that_says_where_the_code_comes_from(
        monkeypatch, capsys):
    """⛔⛔ THE INVENTED SENTENCE WAS "the access code from the Super Research app".
    The code comes from the computer, at the end of its setup; the app only TAKES
    one (or shows its owner the code of a computer already linked). So no sentence
    that names the access code may also name the app."""
    for name, text in _every_person_facing_screen(monkeypatch, capsys).items():
        named = [s for s in _sentences(text) if "access code" in s.lower()]
        assert named, (name, "no sentence names the access code")
        for s in named:
            assert not re.search(r"\bapp\b", s, re.I), (name, s)


def test_every_screen_carries_the_url_and_never_the_pair_command(monkeypatch, capsys):
    for name, text in _every_person_facing_screen(monkeypatch, capsys).items():
        assert URL in text, name
        assert "superresearch --pair" not in text, name


def test_the_watcher_and_the_terminal_carry_the_url_before_the_public_section(
        monkeypatch, capsys):
    """Neither can import the chat constant; both say it in their own file, in the
    same order — the page first, then the public computers."""
    for name, text in (("watcher", _watcher()),
                       ("terminal", _term_out(monkeypatch, capsys))):
        assert text.index(URL) < text.index("Public computers"), name
        add = next(ln for ln in text.splitlines() if "Add a computer:" in ln)
        assert URL in add, (name, add)


def test_the_watcher_says_the_chat_add_line_word_for_word():
    """The watcher imports nothing from sr.py, so its copy of the line can drift
    silently; this is the guard its comment promises."""
    assert sr._ADD_A_COMPUTER in " ".join(_watcher().split())


def test_the_watcher_names_the_path_that_renders_for_a_first_computer():
    """The web-app route is "Account → Pipeline Connection": the "+ add device"
    button only renders once a computer is already listed."""
    line = _watcher()
    assert "Account → Pipeline Connection" in line
    assert "Add Device" not in line
    assert "/sr device-add YOUR-CODE" in line and "ONE message" in line


def test_the_bridge_sentence_leads_with_the_page_and_keeps_its_matchers():
    """The terminal prints it word for word; an OLDER sr.py recognises it by
    "grab the access code", so that phrase must survive any rewording."""
    said = _bridge_no_devices_sentence()
    for keep in ("no research computer on this account yet", "grab the access code",
                 "agent device add <code>", "agent device public",
                 "or one a computer's owner gave you"):
        assert keep in said, keep
    assert said.index(URL) < said.index("grab the access code"), said


# ── the router: "install Super Research" is answered with the page ───────────

@pytest.mark.parametrize("said", [
    "install super research",
    "Install Super Research",
    "how do I install super research",
    "how do i install super research?",
    "set up super research",
    "setup super research",
    "how do I set up super research",
    "install super research on my laptop",
    # ⛔⛔ "here" / "host" BEFORE THE VERB, OR WITH NO MACHINE NAMED, IS NOT THE
    # EXPLICIT ASK. The first cut matched them anywhere in the message, so the
    # newcomer below was offered the install on the chat's own host.
    "I'm new here, how do I set up super research",
    "how do I host super research for my team",
])
def test_install_phrasings_route_to_the_page(said):
    """⭐ OWNER DECISION 3 (2026-09-24). These used to reach the confirm that
    installs the backend on the machine the CHAT runs on — and a yes told a
    brand-new person to run `superresearch --pair`."""
    assert sr._nl_resolve(said) == (None, [sr._ADD_A_COMPUTER]), said


@pytest.mark.parametrize("said", [
    "Install Super Research from superresearch.io/skills.md",
    "install super research from https://superresearch.io/skills.md",
    "install the super research skill",
])
def test_a_message_that_names_the_skill_gets_the_account_check(said):
    """⛔ THE WEB APP'S OWN PASTE-TO-YOUR-AGENT LINE. It is shown to people whose
    agent still has this skill, and its Drive-from-Agent tile relies on the router
    keeping it off the install page. Before 2026-09-24 it reached the confirm that
    installs the BACKEND on the chat's host; it is the skill that was named."""
    assert sr._nl_resolve(said) == (["status-account"], None), said


@pytest.mark.parametrize("said", [
    "install super research here",
    "install it on this machine",
    "install super research on this pc",
    "host the backend on this PC",
    "install the backend",
    "install super research on this laptop",
])
def test_an_explicit_install_on_this_machine_still_reaches_the_confirm(said):
    """The narrow, explicit ask keeps the install command — and its confirm opens
    with the page too."""
    argv, lines = sr._nl_resolve(said)
    assert argv is None and lines == [sr._NL_CONFIRMS["install"]], (said, argv, lines)
    assert lines[0].startswith(f"The setup steps are at {URL}"), lines[0]


@pytest.mark.parametrize("said", [
    "where do I get an access code",
    "where do i get a pair code",
    "get a pair code",
    "how do I get an access code?",
    "where does the access code come from",
    "I need an access code",
])
def test_where_a_code_comes_from_has_a_real_answer(said):
    """⛔ THESE REACHED THE CATCH-ALL, so nothing anywhere said where a code comes
    from and the assistant made one up."""
    assert sr._nl_resolve(said) == (None, [sr._ADD_A_COMPUTER]), said


@pytest.mark.parametrize("said", [
    "I lost my access code, how do I get it back?",
    "how do I get a new access code",
    "I need a new access code",
    "my access code expired how do I get another one",
    "the access code doesn't work, how do I find the right one",
    "the access code doesn’t work, where do I get it",
    "how do i get the access code to show again",
    "how does my friend get an access code from me",
    "where can I find my access code to give to my wife",
    "I need an access code for my friend",
    "I forgot my pairing code",
])
def test_a_recovery_or_sharing_question_gets_the_lost_code_answer(said):
    """⛔⛔ THESE COME FROM SOMEBODY WHOSE COMPUTER ALREADY EXISTS, so they are
    never sent to set one up — that setup ends in the pairing step, which on a
    machine that still exists mints a NEW computer and drops everybody it was
    shared with (`_PAIR_ERRORS`).
    ⭐ AND SINCE 2026-09-24 THEY GET A REAL ANSWER (owner) instead of the catch-all:
    reveal it in Account, Reset for a new one, or the screen of a computer still
    being set up (`_LOST_CODE_REPLY`)."""
    assert sr._nl_resolve(said) == (None, [sr._LOST_CODE_REPLY]), said


@pytest.mark.parametrize("said", [
    "how do i get the access code into the web app",
    "how do I enter my access code",
    "where do I paste my access code",
    "how do I use my access code",
])
def test_a_question_about_entering_a_code_is_not_answered_as_a_lost_one(said):
    """⛔ HANDING A CODE OVER IS A DIFFERENT QUESTION, and the lost-code reply
    does not answer it — these keep the catch-all."""
    assert sr._nl_resolve(said) == (None, [sr._NL_CATCH_ALL]), said


def test_the_lost_code_answer_is_the_owners_and_is_true():
    """The owner approved this answer on 2026-09-24; each place it names was
    checked against the web app: the owner's PIN-gated tap-to-reveal on the
    computer's tile in Account, Reset under Settings → Manage devices (the new
    code is emailed), and the screen of a computer still being set up."""
    said = sr._LOST_CODE_REPLY
    assert said.startswith("If the computer's already on your account, open Account")
    assert "reveal the access code on that computer's tile" in said
    assert "(you'll enter your PIN)" in said
    assert "Reset in Settings → Manage devices and we'll email it to you" in said
    assert "the code is on that computer's screen" in said
    assert "superresearch.io/install" not in said and "--pair" not in said


@pytest.mark.parametrize("said,expect", [
    ("add a device K7XQ9B2M", ["device-add", "K7XQ9B2M"]),
    ("use this code K7XQ-9B2M", ["device-add", "K7XQ-9B2M"]),
    ("research how to get an access code for my building",
     ["research", "how to get an access code for my building"]),
    ("Add device to my Super Research", ["devices"]),
    ("List devices on super Research", ["devices"]),
    ("Login to Super Research", ["login"]),
    # ⛔⛔ A RUN TITLED WITH THE WORDS IS NOT A QUESTION ABOUT THE CODE. Written at
    # rule 5, the code-origin rule answered all four of these with the add line.
    ("status of the research on where to get access codes",
     ["status", "research on where to get access codes"]),
    ("what's the status of \"how do hotels get access codes\"",
     ["status", "how do hotels get access codes"]),
    ("show me the results of how to get pairing codes for bluetooth",
     ["status", "how to get pairing codes for bluetooth"]),
    ("podcast for how to get access codes", ["podcast", "how to get access codes"]),
])
def test_the_new_rules_steal_nothing_they_were_not_written_for(said, expect):
    assert sr._nl_resolve(said)[0] == expect, said


# ── `sr.py install`: opens with the page, never hands over `--pair` ──────────

@pytest.mark.parametrize("already", [False, True])
def test_the_install_command_opens_with_the_page(monkeypatch, already):
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        200, {"already": already}))
    out = _run(sr.cmd_install, NS(json=False))
    assert URL in out.splitlines()[0], out
    assert "--pair" not in out
    # ⛔ `devices` lists; it cannot pair — the old reply promised it could
    assert "see/pair" not in out
    assert "8-character access code" in out
    # ⛔ and the code's origin is this device, never the app
    for s in _sentences(out):
        if "access code" in s:
            assert not re.search(r"\bapp\b", s, re.I), s
            assert "this device then shows" in s, s


# ── the refusal a first-timer meets when they mistype the code ───────────────

@pytest.mark.parametrize("table", ["chat", "terminal"])
def test_code_not_found_first_says_to_check_the_code_on_that_computers_screen(table):
    line = (sr._PAIR_ERRORS if table == "chat" else cli._PAIR_FAILURES)["code_not_found"]
    low = line.lower()
    assert "screen" in low
    assert low.index("screen") < low.index("reset"), line


def test_device_add_success_says_what_the_device_list_says(monkeypatch):
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        200, {"action": "initial-pair", "deviceName": "Studio Mac", "selected": True}))
    out = _run(sr.cmd_device_add, NS(json=False, code="K7XQ9B2M"))
    assert "You can remove or switch computers anytime — just ask." in out
    assert "You can add, remove, or switch devices anytime" not in out


# ── SKILL.md: the `sr` skill must win skill selection ────────────────────────

def _description() -> str:
    fm = _SKILL.read_text(encoding="utf-8").split("---")[1]
    out, started = [], False
    for ln in fm.split("\n"):
        if ln.startswith("description:"):
            started = True
            continue
        if started:
            if ln and not ln.startswith(" "):
                break
            out.append(ln.strip())
    return " ".join(x for x in out if x)


def test_the_description_names_sign_in_and_devices_in_its_first_sentence():
    """⛔⛔ A MODEL-AUTHORED SKILL BEAT `sr` IN SKILL SELECTION for "Login to Super
    Research" and "List devices" — `sr` led with research, and named sign-in and
    devices only in its tail. Both failed `devices` relays ran under the other
    skill (owner, 2026-09-24). The first sentence now names all three."""
    first = _description().split(". ", 1)[0]
    for kw in ("sign in", "devices", "Research Computers", "research a topic",
               "Login to Super Research", "List devices", "Add device", "access code"):
        assert kw in first, (kw, first)


def test_the_skill_file_hands_out_the_page_and_never_the_setup_commands():
    skill = _SKILL.read_text(encoding="utf-8")
    folded = " ".join(skill.split())
    for gone in ("install.ps1", "install.sh", "superresearch --pair\n",
                 "unavoidable machine-setup", "guide pairing",
                 "add your own with an access code", "pair/install step"):
        assert gone not in skill, gone
    # the one place `--pair` is named, it is named to forbid it
    assert skill.count("superresearch --pair") == 1
    assert "no install commands, no `superresearch --pair`" in folded
    assert "If they explicitly ask how to set up a machine, the answer is " \
           "https://superresearch.io/install" in folded
    assert "never say it comes from the app" in folded


def test_the_connect_closing_card_carries_the_link_in_its_add_line():
    """⛔ THE FIRST THING A NEW TERMINAL USER READS AFTER `connect`. It used to say
    "make sure one computer is running Super Research and paired" — assuming one
    exists, naming no way to get one. Read off the AST, where implicit string
    concatenation is already one constant, so a wrapped literal cannot hide the URL
    on a line of its own. (Mutation T2 survived every rendered-screen guard.)"""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_connect")
    adds = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)
            and isinstance(n.value, str) and n.value.startswith("Add a computer:")]
    assert len(adds) == 1, adds
    assert URL in adds[0], adds[0]
    assert "access code the computer shows" in adds[0], adds[0]
    assert "--pair" not in adds[0]


def test_the_skill_file_routes_a_lost_code_to_the_lost_code_answer():
    """⭐ The model reads the table before it runs anything, so the lost-code row is
    what sends "I lost my access code" to `do` instead of to a guess — and every
    phrase that row teaches must really reach `_LOST_CODE_REPLY`."""
    skill = _SKILL.read_text(encoding="utf-8")
    rows = [ln for ln in skill.splitlines() if ln.startswith('| "I lost my access code"')]
    assert len(rows) == 1, rows
    row = rows[0]
    assert '`sr.py do "<message>"`' in row
    assert "never send them to set up a new computer" in row
    taught = re.findall(r'"([^"]+)"', row.split("|")[1])
    assert len(taught) >= 4, taught
    for said in taught:
        assert sr._nl_resolve(said) == (None, [sr._LOST_CODE_REPLY]), said
