"""The owner's switches from chat — the Windows review of wave 12 (2026-09-28).

An eight-agent review on Windows drove `sr.py do` at d51e7dc and found readings
that turned the WRONG way — and since wave 12 a hide also switches Allow all off:

  hide-1  a request to KEEP a computer public hid it, unconfirmed: `stop hiding my
          mac`, `don't take my mac off the public list`, `my mac shouldn't be
          private`.
  hide-2  a QUESTION hid it: `why is my mac private?`, `should I hide my mac?`,
          `did you hide my mac?`.
  hide-3  `turn off public for my mac` took “off” as a computer's name, and the
          resolver matched it inside “Office PC” — which it hid.
  hide-4  `turn off approving for my mac` (Allow all ON) hid it; `remove approval
          for my mac` offered to UNLINK a computer called “approval for my mac”.
  run-1   `stop research on allow all` could not stop the run of that name.
  name-1  `my research computer` — the product's own noun — was looked up as a name.
  said-1  a lost reply on the owner switch said the bridge "isn't running on this
          machine yet", though the write may have landed.
  said-2  signed out, the owner switches relayed the terminal's "run /login".

Pinned by EXECUTION: `sr._nl_resolve`, and `sr.py do` / the commands with
`_get`/`_post` stubbed, asserting the POSTs a message makes — or that it makes
none. The mutants are in .mutants/wave12_windows_review_mutants.py.
"""
from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
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


sr = _load("sr_allow_all_windows_review_0928", _SCRIPTS / "sr.py")


def _route(text: str) -> str:
    """HIDE[:name], OFF[:name], DEVICES, CATCH, STOP:<title>, ARGV:…, LINE:…"""
    argv, lines = sr._nl_resolve(text)
    if argv is not None:
        if argv[:2] == ["device-visibility", "private"]:
            return "HIDE" + (f":{argv[2]}" if len(argv) > 2 else "")
        if argv[:2] == ["device-allow-all", "no"]:
            return "OFF" + (f":{argv[2]}" if len(argv) > 2 else "")
        if argv == ["devices"]:
            return "DEVICES"
        return "ARGV:" + json.dumps(argv, ensure_ascii=False)
    said = " ".join(lines or [])
    if said == sr._NL_CATCH_ALL:
        return "CATCH"
    stop = sr._NL_CONFIRMS["stop"].split("{name}")[0]
    if said.startswith(stop):
        rest = said[len(stop):]
        return "STOP:" + rest[1:rest.index("”")]
    return "LINE:" + said[:60]


# ── the `do` path, with the bridge stubbed ───────────────────────────────────────

_MY_MAC = {"id": "dev-mac", "name": "My Mac", "owned": True, "visibility": "public",
           "allowAll": True}
_OFFICE = {"id": "dev-office", "name": "Office PC", "owned": True, "visibility": "public",
           "allowAll": False}


@pytest.fixture()
def bridge(monkeypatch, capsys):
    """“My Mac” owned, public, letting anyone join — where a wrong hide costs the
    most. `state.owned` can be widened per test. Every POST is recorded."""
    posts: list = []
    state = SimpleNamespace(owned=[dict(_MY_MAC)])

    def _get(path, timeout=None):
        if path == "/devices/public":
            return 200, {"devices": []}
        if path == "/devices/requests":
            return 200, {"incoming": []}
        if path == "/status":
            return 200, {}
        if path.startswith("/updates"):
            return 200, {"updates": []}
        return 200, {"devices": state.owned}

    def _post(path, body=None, timeout=None):
        posts.append((path, body))
        return 200, {"deviceName": "My Mac", "visibility": "private", "allowAll": False,
                     "changed": True, "ok": True}

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 1))
    state.posts = posts
    state.out = lambda: capsys.readouterr().out
    return state


def _do(text):
    ns = sr.build_parser().parse_args(["do", text])
    return ns.func(ns)


def _run(*argv):
    ns = sr.build_parser().parse_args(list(argv))
    return ns.func(ns)


def _visibility_posts(bridge):
    return [b for p, b in bridge.posts if p == "/device/visibility"]


# ── hide-1: a request to keep it public never hides it ──────────────────────────

_KEEP_PUBLIC = [
    "stop hiding my mac",
    "stop keeping my mac private",
    "stop my mac from being private",
    "turn off hiding for my mac",
    "don't take my mac off the public list",
    "don't remove my mac from the public list",
    "I don't want my mac off the public list",
    "don't stop offering my mac",
    "my mac is private but it should be public",
    "my mac shouldn't be private",
    "I don't want my mac private",
]


@pytest.mark.parametrize("said", _KEEP_PUBLIC)
def test_a_request_to_keep_it_public_is_never_a_hide(said):
    """⛔⛔ hide-1. Each of these HID the computer, unconfirmed, at d51e7dc. Like
    `don't hide my mac`, they reach the catch-all: guessing which opposite was
    meant is worse than asking."""
    assert _route(said) == "CATCH", said


@pytest.mark.parametrize("said", ["stop hiding my mac", "my mac shouldn't be private"])
def test_a_request_to_keep_it_public_writes_nothing(bridge, said):
    _do(said)
    assert _visibility_posts(bridge) == [], (said, bridge.posts)


@pytest.mark.parametrize("said", ["hide my mac", "take my mac off the public list",
                                  "can you hide my mac?", "make my mac private"])
def test_a_plain_hide_still_hides(said):
    """The control: the guard is on the keep-public shapes, never on a hide."""
    assert _route(said) == "HIDE", said


def test_a_quoted_name_with_a_negation_in_it_is_still_hidden():
    """⛔ The wish list reads the words OUTSIDE quotes: “Never Mind PC” is a name."""
    assert _route("make “Never Mind PC” private").startswith("HIDE"), \
        _route("make “Never Mind PC” private")


# ── hide-2: a question changes nothing ──────────────────────────────────────────

_QUESTIONS = [
    "why is my mac private?",
    "why is my mac hidden?",
    "did you hide my mac?",
    "should I hide my mac?",
    "if I hide my mac can people still use it?",
    "why is my mac not public",
    "why did my mac go private",
    "why is my mac public?",
    "should I make my mac public?",
    # a statement asked as a question — only the “?” says so
    "my mac is private now?",
    "my mac went private?",
    "my mac is hidden?",
]


@pytest.mark.parametrize("said", _QUESTIONS)
def test_a_question_about_public_or_private_reads_the_list(said):
    """⛔⛔ hide-2. At d51e7dc these HID the computer, except the two “public” ones,
    which asked to publish it. `_asking_state` now knows the question words
    `_aa_asking` does, and a trailing “?”."""
    assert _route(said) == "DEVICES", said


@pytest.mark.parametrize("said", ["why is my mac private?", "should I hide my mac?"])
def test_a_question_writes_nothing(bridge, said):
    _do(said)
    assert _visibility_posts(bridge) == [], (said, bridge.posts)


# ── hide-3: a particle is never a computer's name ───────────────────────────────

@pytest.mark.parametrize("said", ["turn off public for my mac", "switch off public for my mac"])
def test_off_is_never_read_as_a_computer(said):
    """⛔⛔ hide-3. At d51e7dc this was ["device-visibility", "private", "off"], and
    the resolver's substring match found “Office PC”."""
    assert _route(said) == "HIDE", said


def test_off_never_hides_the_office_pc(bridge):
    bridge.owned = [dict(_MY_MAC), dict(_OFFICE)]
    _do("turn off public for my mac")
    assert all(b.get("deviceId") != "dev-office" for b in _visibility_posts(bridge)), \
        bridge.posts


@pytest.mark.parametrize("span, is_name", [("off", False), ("on", False), ("Out", False),
                                          ("Kick Off", True), ("Office PC", True)])
def test_names_a_machine_refuses_a_lone_particle(span, is_name):
    assert sr._names_a_machine(span) is is_name


# ── hide-4: approval words are the Allow-all setting, never a hide or an unlink ──

@pytest.mark.parametrize("said", ["turn off approving for my mac",
                                  "switch off approving for my mac",
                                  "disable approvals for my mac",
                                  "remove approval for my mac",
                                  "remove approvals from my mac"])
def test_turning_approvals_off_is_read_only(said):
    """⛔ hide-4. The first two HID the computer; `remove approval…` offered to
    UNLINK a computer called “approval for my mac”. They read the list now."""
    assert _route(said) == "DEVICES", said


def test_turning_approvals_off_writes_nothing(bridge):
    _do("turn off approving for my mac")
    assert bridge.posts == [], bridge.posts


# ── run-1: a run named with Allow-all words can be stopped ───────────────────────

@pytest.mark.parametrize("said, want", [
    ("stop research on allow all", "STOP:allow all"),
    ("cancel research on allow all", "STOP:allow all"),
    ("stop run on allow all", "STOP:allow all"),
    ("stop research on letting anyone join", "STOP:letting anyone join"),
    ("stop research “allow all”", "STOP:allow all"),
    ("pause research on auto-approve", 'ARGV:["pause", "auto-approve"]'),
    ("resume research on allow all", 'ARGV:["resume", "allow all"]'),
])
def test_a_run_on_allow_all_words_answers_to_its_verb(said, want):
    """run-1. These reached the catch-all (or the device list) at d51e7dc; the
    `the …` shapes already worked."""
    assert _route(said) == want, said


def test_the_setting_itself_still_switches_off():
    assert _route("turn off allow all").startswith("OFF")


# ── name-1: “research computer” is a kind ────────────────────────────────────────

@pytest.mark.parametrize("said, want", [
    ("make my research computer private", "HIDE"),
    ("turn off allow all for my research computer", "OFF"),
    ("turn off allow all for my sr computer", "OFF"),
    ("hide my super research pc", "HIDE"),
])
def test_the_products_own_noun_goes_to_the_picker(said, want):
    """⛔ name-1. At d51e7dc these looked for a computer CALLED “research
    computer” and answered "No device matching"."""
    assert _route(said) == want, said


def test_the_allow_all_flag_is_read_after_the_name_on_every_python(monkeypatch):
    """⛔⛔ Python 3.12's argparse refuses `device-visibility public --allow-all
    "Studio PC"` ("unrecognized arguments"); the WSL chat runtime is 3.12. The
    parser hands argparse the flag AFTER the words — pinned on the argv it passes,
    because 3.13+ accept either order and would hide a revert."""
    seen = []
    real = sr.argparse.ArgumentParser.parse_known_args

    def spy(self, args=None, namespace=None):
        seen.append(list(args) if args is not None else None)
        return real(self, args, namespace)

    monkeypatch.setattr(sr.argparse.ArgumentParser, "parse_known_args", spy)
    ns = sr.build_parser().parse_args(["--json", "device-visibility", "public",
                                       "--allow-all", "Studio PC"])
    assert ns.allow_all is True and ns.device == "Studio PC"
    assert seen[0] == ["--json", "device-visibility", "public", "Studio PC", "--allow-all"]


def test_my_research_computer_acts_on_the_one_this_account_owns(bridge):
    _do("turn off allow all for my research computer")
    assert _visibility_posts(bridge) == [{"deviceId": "dev-mac", "allowAll": False}]


# ── said-1: a lost reply cannot confirm; it is not a missing bridge ──────────────

class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen_timing_out_on_post(devices):
    def _urlopen(req, timeout=None):
        if req.get_method() == "POST":
            raise TimeoutError("timed out")
        return _Resp(json.dumps({"devices": devices}).encode("utf-8"))
    return _urlopen


@pytest.mark.parametrize("argv", [("device-allow-all", "yes"), ("device-allow-all", "no"),
                                  ("device-visibility", "public"),
                                  ("device-visibility", "private")])
def test_a_lost_reply_says_it_could_not_confirm(monkeypatch, capsys, argv):
    """⛔⛔ said-1. The GET reached the bridge a moment earlier; "isn't running on
    this machine yet" sent the owner to reinstall while Allow all might be on."""
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_timing_out_on_post([dict(_MY_MAC)]))
    rc = _run(*argv)
    out = capsys.readouterr().out
    assert rc != 0
    assert "could not confirm that change" in out, out
    assert "isn't running" not in out, out


def test_a_bridge_that_is_down_still_says_so(monkeypatch):
    """The control: a refused CONNECT is not marked — it stays "unreachable"."""
    def _down(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    monkeypatch.setattr(urllib.request, "urlopen", _down)
    code, body = sr._post("/device/visibility", {"deviceId": "x"})
    assert code == 0 and "reason" not in body
    assert "bridge unreachable" in body["error"]


def test_a_read_timeout_is_marked_for_every_reader(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_timing_out_on_post([]))
    code, body = sr._post("/device/visibility", {"deviceId": "x"})
    assert code == 0 and body.get("reason") == "timeout"
    assert "bridge unreachable" in body["error"]    # the same line for every reader


# ── said-2: signed out, the chat's words ─────────────────────────────────────────

@pytest.mark.parametrize("argv", [("device-allow-all", "yes"), ("device-visibility", "private"),
                                  ("device-visibility", "private", "My Mac"),
                                  ("device-allow-all", "no", "My Mac")])
def test_signed_out_owner_switches_never_say_slash_login(monkeypatch, capsys, argv):
    """⛔ said-2. `_signed_out_or` says it the chat's way; `/login` is the terminal's."""
    monkeypatch.setattr(sr, "_get", lambda path, timeout=None:
                        (401, {"error": "not signed in — run /login"}))
    monkeypatch.setattr(sr, "_post", lambda path, body=None, timeout=None:
                        (401, {"error": "not signed in — run /login"}))
    _run(*argv)
    out = capsys.readouterr().out
    assert "/login" not in out, out
    assert "log you in" in out, out


@pytest.mark.parametrize("argv", [("device-allow-all", "yes"), ("device-visibility", "private")])
def test_signed_out_between_the_list_and_the_switch_is_said_the_chats_way(
        monkeypatch, capsys, argv):
    """⛔ said-2, on the WRITE: the list still answered, the switch met a 401 (the
    session ended in between)."""
    monkeypatch.setattr(sr, "_get", lambda path, timeout=None:
                        (200, {"devices": [dict(_MY_MAC)]}))
    monkeypatch.setattr(sr, "_post", lambda path, body=None, timeout=None:
                        (401, {"error": "not signed in — run /login"}))
    _run(*argv)
    out = capsys.readouterr().out
    assert "/login" not in out, out
    assert "log you in" in out, out
