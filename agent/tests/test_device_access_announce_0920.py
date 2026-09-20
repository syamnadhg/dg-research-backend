"""The two things a person waits on that nobody was ever told about (2026-09-20).

⛔⛔ BOTH FAILURES HAD THE SAME SHAPE: the product knew something the person
wanted to know, and there was no path from the knowing to the telling.

1. THE OWNER APPROVED AND NOBODY SAID SO. A person with no research computer
   asked to use a public one. The owner said yes. Twenty minutes later the person
   asked "done?" and only then found out. The approval lands in
   `deviceAccessRequests`, which is `allow read, write: if false` to EVERY
   credential this agent holds — so it cannot be watched in Firestore at all, and
   nothing on this side ever knocked on the web route unprompted.

2. THE LOGS ARRIVED AND NOBODY SAID SO. `send-logs` returns the moment the
   request is WRITTEN, because a machine somewhere else does the packaging and the
   upload. "Asked" was the last thing anybody heard.

⭐ THE ONE CHANNEL THAT CAN SPEAK UNPROMPTED is the per-chat watchdog
(`sr_attention_poll`), so both answers ride it — behind an EXPLICIT `?watchdog=1`
marker rather than `?via=agent`, which has three readers and would let the other
two silently consume an announcement nobody is listening for.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


poll = _load("poll_0920", _SCRIPTS / "sr_attention_poll.py")
sr = _load("sr_0920", _SCRIPTS / "sr.py")


# ── the door ─────────────────────────────────────────────────────────────────

def test_the_poller_asks_as_the_watchdog_not_merely_as_the_agent():
    """⛔⛔ `?via=agent` HAS THREE READERS — this poller, sr.py's sign-in claim, and
    `sr updates`. A side effect hung off it fires on all three, so whichever ran
    first would consume an approval nobody was listening for. Only this file can
    deliver a proactive message, so only this file asks for the answer."""
    import inspect
    src = inspect.getsource(poll._get_updates)
    assert "watchdog=1" in src, src
    assert "via=agent" in src, "the existing scope must not be dropped"


def test_an_older_shim_that_returns_two_values_still_works(monkeypatch, tmp_path):
    """⛔⛔ THE SHIM ON DISK IS NOT THE SHIM IN THE PACKAGE. A generated
    `sr_poll_<slug>.py` lives in every chat that ever armed one, and this file is
    deployed by `connect`/`update` rather than by `pip install` — so the old
    2-tuple shape and the new 4-tuple shape genuinely coexist on real hosts. An
    unpack that assumed the new arity would take the watchdog down in exactly the
    chats that had been running longest."""
    monkeypatch.setattr(poll, "_get_updates", lambda origin=None: ([], None))
    monkeypatch.setattr(poll, "_state_path", lambda origin: tmp_path / "s.json")
    assert poll.main({"platform": "hermes", "chat_id": "c1"}) == 0


# ── what the approval says ───────────────────────────────────────────────────

def test_an_approval_says_you_are_in_and_names_the_computer():
    """The owner's ask, verbatim: "You are in... you can use MacBook for your
    researches, and then the run should start if a run is gated by this step." """
    line = poll._device_access_line(
        {"state": "approved", "deviceName": "Macbook", "usable": True,
         "online": True, "topic": "creativity", "autoStarted": True})
    assert "You're in" in line
    assert "Macbook" in line
    assert "Starting “creativity”" in line


def test_a_gated_run_that_could_not_start_is_not_claimed_to_have_started():
    """⛔⛔ A COMPUTER CAN BE SHARED WITH YOU AND NOT BE READY TO TAKE WORK. Saying
    "starting" about one that is not is the shape of falsehood this codebase keeps
    writing comments about — and the topic is still held, so there is a true and
    useful thing to say instead."""
    line = poll._device_access_line(
        {"state": "approved", "deviceName": "Macbook", "usable": False,
         "topic": "creativity", "autoStarted": False})
    assert "still holding “creativity”" in line
    assert "Starting" not in line


def test_a_sleeping_computer_is_queued_not_started():
    """⛔ "STARTED" READS AS WORK IN PROGRESS. A machine that is off takes the run
    when it wakes, which could be tomorrow."""
    line = poll._device_access_line(
        {"state": "approved", "deviceName": "Macbook", "usable": True,
         "online": False, "topic": "creativity", "autoStarted": True})
    assert "queued" in line and "switched off" in line


def test_an_approval_with_no_held_topic_is_still_announced():
    """⛔ THE ACCESS IS NEWS ON ITS OWN. Somebody who asked for a computer before
    asking for any research still wants to know they can use it."""
    line = poll._device_access_line({"state": "approved", "deviceName": "Macbook"})
    assert "You're in" in line and "Macbook" in line


@pytest.mark.parametrize("state", ["denied", "expired", "", "pending"])
def test_only_a_yes_is_ever_spoken(state):
    """⛔⛔ A REFUSAL IS NOT ANNOUNCED, and that is a decision rather than an
    omission. The app tells them, subject to their own notification settings, and
    a "no" repeated by a second channel is worse than one delivered once. Expiry
    is indistinguishable from a refusal from outside, which is the second reason
    not to put words to either."""
    assert poll._device_access_line({"state": state, "deviceName": "Macbook"}) == ""


# ── what the landed bundle says ──────────────────────────────────────────────

def test_a_landed_bundle_is_announced_with_its_code():
    line = poll._support_log_line(
        {"code": "SSBYXEGD", "status": "done", "deviceName": "Macbook",
         "runCount": 1})
    assert "Support has the logs" in line
    assert "SSBYXEGD" in line and "Macbook" in line


def test_both_codes_are_quoted_when_the_agent_log_went_too():
    """⛔ TWO BARE CODES IS HOW SOMEBODY OPENS THE WRONG ONE AT SUPPORT."""
    line = poll._support_log_line(
        {"code": "SSBYXEGD", "status": "done", "deviceName": "Macbook",
         "runCount": 2, "agentLogCode": "AGENTLOG"})
    assert "SSBYXEGD" in line and "AGENTLOG" in line
    assert "agent's own log" in line


def test_a_failed_bundle_is_announced_too():
    """⛔⛔ THE ONE CASE WHERE SILENCE ACTIVELY MISLEADS. The person believes they
    have sent something. A bundle that failed quietly leaves them waiting on
    support for a file support never got."""
    line = poll._support_log_line(
        {"code": "SSBYXEGD", "status": "failed", "deviceName": "Macbook"})
    assert "couldn't package" in line
    assert "try again" in line


def test_a_note_with_no_code_says_nothing():
    assert poll._support_log_line({"status": "done"}) == ""


# ── the chat ask carries the chat ────────────────────────────────────────────

def test_the_ask_tells_the_bridge_which_chat_is_waiting(monkeypatch, capsys):
    """⭐⭐ WITHOUT THIS THERE IS NOWHERE TO DELIVER THE ANSWER. The bridge cannot
    watch the approval in Firestore, so it has to knock on the web route — and it
    only knows to knock, and where to send the result, because the ask said which
    chat made it."""
    seen = {}

    def post(path, body=None):
        seen["path"], seen["body"] = path, body
        return 200, {"ok": True, "deviceId": "dev1", "status": "pending"}

    monkeypatch.setattr(sr, "_post", post)
    monkeypatch.setattr(sr, "_origin_from_env",
                        lambda: {"platform": "hermes", "chat_id": "c1"})
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"devices": [{"deviceId": "dev1", "label": "Macbook",
                           "online": True, "full": False}], "truncated": False}))
    sr.cmd_device_ask(type("N", (), {"device": "a1b2c3d4e5f60718"
                                               "29304a5b6c7d8e9f", "json": False,
                                     "yes": True})())
    assert seen.get("path") == "/device/ask"
    assert seen["body"].get("origin") == {"platform": "hermes", "chat_id": "c1"}


def test_a_terminal_ask_carries_no_origin_and_parks_nothing(monkeypatch):
    """⛔ NO ORIGIN MEANS NO CHAT COULD EVER BE TOLD, so parking the ask would buy
    nothing but a week of pointless reads against the web route. A terminal
    `agent device ask` behaves exactly as it did."""
    seen = {}

    def post(path, body=None):
        seen["body"] = body
        return 200, {"ok": True, "deviceId": "dev1", "status": "pending"}

    monkeypatch.setattr(sr, "_post", post)
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"devices": [{"deviceId": "dev1", "label": "Macbook",
                           "online": True, "full": False}], "truncated": False}))
    sr.cmd_device_ask(type("N", (), {"device": "a1b2c3d4e5f60718"
                                               "29304a5b6c7d8e9f", "json": False,
                                     "yes": True})())
    assert "origin" not in seen["body"]


# ── the branch ruff caught and no test did ───────────────────────────────────

def _research_out(monkeypatch, capsys, origin):
    """`sr research "<topic>"` against an account with no research computer."""
    monkeypatch.setattr(sr, "_origin_from_env", lambda: origin)
    monkeypatch.setattr(sr, "_post",
                        lambda p, b=None: (400, {"reason": "no_devices",
                                                 "error": "no devices yet"}))
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"devices": [], "truncated": False}))
    sr.cmd_research(type("N", (), {"topic": "creativity", "device": "",
                                   "json": False, "no_video": False,
                                   "no_email": False})())
    return capsys.readouterr().out


def test_a_topic_with_nowhere_to_run_is_promised_not_dropped(monkeypatch, capsys):
    """⭐⭐ THE BRIDGE HOLDS IT AND STARTS IT BY ITSELF when a computer arrives —
    which is only a kindness if it was promised. Unannounced it is research
    starting on its own, minutes or hours later, for a reason nobody can see.

    ⛔⛔ AND THIS BRANCH HAD NO TEST AT ALL. A `NameError` was shipped into it and
    caught by ruff rather than by the suite — `f"“{topic}”"` naming a local that
    does not exist in `cmd_research`. Every run reaching here would have died with
    a traceback instead of printing the empty state. That absence is why this
    exists, not the wording."""
    out = _research_out(monkeypatch, capsys,
                        {"platform": "hermes", "chat_id": "c1"})
    assert "“creativity” has nowhere to run yet" in out, out
    assert "I’ll hold it" in out
    # ⛔ AND THE TWO WAYS IN STILL FOLLOW IT — the promise replaces neither
    assert "Add your own computer" in out
    assert "Public computers" in out


def test_no_chat_means_no_promise_because_nothing_is_held(monkeypatch, capsys):
    """⛔ THE BRIDGE PARKS ONLY WHEN THE ASK CAME FROM A CHAT — without an origin
    there is nowhere to deliver the news, so it holds nothing. Promising it here
    would be a claim this client cannot keep, and a terminal `agent research`
    reaches exactly this path."""
    out = _research_out(monkeypatch, capsys, None)
    assert "hold it" not in out, out
    # ⛔ the empty state itself is unchanged — only the lead is conditional
    assert "Add your own computer" in out
    assert "Public computers" in out
