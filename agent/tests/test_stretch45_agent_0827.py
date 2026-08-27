"""Stretch 4.5, the agent's half — the five things the agent side told somebody
that were not true, or did not tell them at all.

⛔⛔ EVERY PREMISE THIS STRETCH STARTED FROM CAME BACK PARTLY WRONG, and the
corrections are what these tests pin, not the original claims:

  • The port bug was read as "a non-numeric value crashes the bridge". It does,
    and it takes `doctor`, `version`, `status` and `connect` down with it because
    `cli.py` imports `config` at module scope. But the incident that produced it
    was port NINE — numeric, in range, and accepted by the very range check the
    clients were held up as getting right. The crash is not the defect; the
    DISAGREEMENT is, and the fleet's watcher spawns the bridge with no `env=`, so
    the client and the bridge it just started can aim at two different ports and
    the only symptom is "unreachable", forever.

  • The bind failure was read as one message being rude. It is a false statement
    of fact: `EACCES` on an AF_INET bind is the privileged-port guard, so there is
    no holder, and the line told somebody to go and find one — four times, in a
    real log. And the one command offered to find it was Windows-only, printed on
    darwin and written down on Linux.

  • "Re-arm at sign-in capture" could not happen as described: a remote flow is
    clamped to 900s and the watcher outlives it. The real shape is worse — the
    give-up returns BEFORE the state write, so `__login_wait__` is left at the
    limit forever and EVERY later sign-in in that chat dies on its first tick.

  • "`login-done` eats the answer" is refuted: it renders everything it takes.
    The eater is `updates`, which took the same one-shot note, moved the delivered
    watermark past it, and rendered runs only.

  • "The wheel ships no scheduler" is refuted: the bridge starts two daemon
    threads and `autostart` writes a launchd plist, a systemd unit and a Scheduled
    Task. What is true is narrower and is the thing that matters — the bridge has
    no OUTBOUND channel, so the only thing that can deliver a promised follow-up
    is a cron row in the host runtime's store, which `_prepare_stream_arm` either
    writes or reports it could not.
"""
import errno
import importlib
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, config

sr = importlib.import_module("facade.skill.scripts.sr")
poll = importlib.import_module("facade.skill.scripts.sr_attention_poll")
notice = importlib.import_module("facade.skill.scripts.sr_update_notice")


class FakeFS:
    """Only what these tests drive. ⚠ A local copy, like every sibling suite: each
    test module owns its own because a shared one would let one file's device
    fixture leak into another's route assertions."""

    devices: list[dict] = []

    def __init__(self, token):
        self.token = token

    def list_devices(self, uid):
        return list(FakeFS.devices)

    def list_researches(self, uid, page_size=20):
        return []

    def get_user_settings(self, uid):
        return {}


def _sess(uid="u1", email="e@x.y"):
    return SimpleNamespace(uid=uid, email=email, id_token=lambda force=False: "tok")


# ── 1. the bridge port: one rule, five copies, one answer ────────────────────

@pytest.mark.parametrize("raw,port,rejected", [
    ("", 9876, ""),                 # unset
    ("   ", 9876, ""),              # whitespace is unset, not a value
    ("8080", 8080, ""),
    ("1", 1, ""),                   # the low end IS in range
    ("65535", 65535, ""),
    ("9", 9, ""),                   # ⛔ the incident's port: numeric, in range, ACCEPTED
    ("abc", 9876, "abc"),           # used to raise at import and kill every subcommand
    ("0", 9876, "0"),
    ("-1", 9876, "-1"),
    ("65536", 9876, "65536"),
    ("99999", 9876, "99999"),
])
def test_the_port_is_read_the_same_way_the_clients_read_it(monkeypatch, raw, port, rejected):
    """⛔⛔ THE POINT IS AGREEMENT, NOT SURVIVAL. Five copies of this rule exist —
    this module and four stdlib-only clients — and the fleet's watcher spawns the
    bridge with `Popen([...], )` and no `env=`, so the child inherits the same
    variable. Before this, a value the clients shrugged off either killed the
    bridge at import or was taken verbatim by one side only, and the client then
    reported an unreachable bridge with nothing anywhere saying why.

    ⚠ 9 IS IN RANGE ON PURPOSE. Two fleet tests use it as a nothing-answers port;
    narrowing the range here would make this module the one copy that disagrees,
    which is the defect. A port this user cannot bind is caught at bind time,
    where the errno can say so.
    """
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", raw)
    fresh = importlib.reload(config)
    try:
        assert fresh.BRIDGE_PORT == port
        assert fresh.BRIDGE_PORT_REJECTED == rejected
        # ⛔⛔ AND THE CLIENTS ARE ACTUALLY READ, which this test's own name claims
        # and its first version did not do — it reloaded `config` and asserted on
        # `config`, so "five copies land on the same answer" was pinned by nothing.
        # The two bundled clients resolve their port lazily from the same variable,
        # so the port they would REACH is what has to match.
        assert sr._base().rsplit(":", 1)[1] == str(port), sr._base()
        assert poll._base().rsplit(":", 1)[1] == str(port), poll._base()
        assert notice._base().rsplit(":", 1)[1] == str(port), notice._base()
    finally:
        monkeypatch.delenv("SUPER_AGENT_BRIDGE_PORT", raising=False)
        importlib.reload(config)


def test_a_variable_that_is_set_but_empty_is_unset_everywhere(monkeypatch, capsys):
    """⛔⛔ FOUND BY EXECUTING THE COPIES AGAINST EACH OTHER, not by reading them.
    `os.environ.get(name, default)` returns "" for a variable that is SET AND
    EMPTY — a shape a shell exports readily — so the default never applies. The
    bridge and two clients treated that as unset; the chat client called it a bad
    value and printed "(ignoring bad SUPER_AGENT_BRIDGE_PORT ''; using 9876)" to
    stderr ON EVERY INVOCATION. Same value, four answers, one of them noisy."""
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "")
    try:
        fresh = importlib.reload(config)
        assert fresh.BRIDGE_PORT == 9876
        assert fresh.BRIDGE_PORT_REJECTED == "", (
            "an empty variable is not a value somebody chose badly")
        capsys.readouterr()
        for mod in (sr, poll, notice):
            assert mod._base().endswith(":9876"), mod._base()
        assert capsys.readouterr().err == "", (
            "a client complained about a value the bridge did not even see")
    finally:
        monkeypatch.delenv("SUPER_AGENT_BRIDGE_PORT", raising=False)
        importlib.reload(config)


def test_a_rejected_port_is_recorded_rather_than_printed_at_import(monkeypatch, capsys):
    """⛔ IT MUST NOT SPEAK AT IMPORT TIME. `cli.py` imports this module at the top,
    before `logsetup.configure` has run and on EVERY subcommand — a print here
    would be noise on nine commands and a log line would go nowhere at all. The
    value is recorded so `serve` and `doctor` can say it where somebody is
    actually looking at a bridge that will not come up."""
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "not-a-port")
    try:
        fresh = importlib.reload(config)
        assert fresh.BRIDGE_PORT_REJECTED == "not-a-port"
        assert capsys.readouterr().out == ""
    finally:
        monkeypatch.delenv("SUPER_AGENT_BRIDGE_PORT", raising=False)
        importlib.reload(config)


# ── 2. the bind failure names only what the errno supports ───────────────────

class _Boom:
    """A ThreadingHTTPServer stand-in that fails to bind with one chosen errno."""

    def __init__(self, code):
        self.code = code

    def __call__(self, *a, **kw):
        raise OSError(self.code, {errno.EACCES: "Permission denied",
                                  errno.EADDRINUSE: "Address already in use"}
                      .get(self.code, "Some other problem"))


def test_a_privileged_port_is_not_reported_as_a_squatter(monkeypatch, capsys):
    """⛔⛔ THE MEASURED FALSEHOOD. `~/.super-agent/bridge.log` carries four lines
    reading `bridge port 127.0.0.1:9 held by a NON-bridge process ([Errno 13]
    Permission denied)`. Errno 13 is EACCES, which on an AF_INET bind means the
    port is below 1024 and this process is not root. Nothing holds it. The message
    named a culprit that cannot exist and told somebody to go and find it — the
    same rule the send-logs refusals already follow: name neither a number nor a
    culprit you have not measured."""
    monkeypatch.setattr(bridge, "ThreadingHTTPServer", _Boom(errno.EACCES))
    monkeypatch.setattr(bridge, "BridgeState", lambda: SimpleNamespace(session=None))
    probed = []
    monkeypatch.setattr(bridge, "_port_holder_is_bridge",
                        lambda h, p: probed.append((h, p)) or False)
    bridge.serve(host="127.0.0.1", port=9)
    out = capsys.readouterr().out
    assert "held by another process" not in out, out
    assert "cannot be opened by this user account" in out, out
    assert "below 1024" in out, out
    assert not probed, (
        "an EACCES bind cannot have a holder, so probing for one is asking a "
        "question whose answer cannot change what we say", probed)


def test_a_real_squatter_is_still_called_one(monkeypatch, capsys):
    """The other half, and it must not be lost while fixing the first: EADDRINUSE
    genuinely means somebody is there. Without this pin, "stop claiming a holder"
    reads as a pass while silently removing the only true holder message."""
    monkeypatch.setattr(bridge, "ThreadingHTTPServer", _Boom(errno.EADDRINUSE))
    monkeypatch.setattr(bridge, "BridgeState", lambda: SimpleNamespace(session=None))
    monkeypatch.setattr(bridge, "_port_holder_is_bridge", lambda h, p: False)
    bridge.serve(host="127.0.0.1", port=9876)
    out = capsys.readouterr().out
    assert "held by another process" in out, out
    assert "cannot be opened by this user account" not in out, out


def test_an_already_running_bridge_is_only_claimed_on_eaddrinuse(monkeypatch, capsys):
    """The benign idempotent re-fire. Kept in the same file as the two above so a
    change to the errno branching cannot quietly reroute it."""
    monkeypatch.setattr(bridge, "ThreadingHTTPServer", _Boom(errno.EADDRINUSE))
    monkeypatch.setattr(bridge, "BridgeState", lambda: SimpleNamespace(session=None))
    monkeypatch.setattr(bridge, "_port_holder_is_bridge", lambda h, p: True)
    bridge.serve(host="127.0.0.1", port=9876)
    assert "already running" in capsys.readouterr().out


def test_an_unrecognised_errno_says_what_the_system_said_and_stops(monkeypatch, capsys):
    """⛔ THE HABIT THAT PRODUCED THE EACCES LINE. Inventing a cause for an errno
    nobody thought about is exactly how "held by another process" came to be
    printed for a port with no holder. Anything that is neither in-use nor
    privileged is reported as itself."""
    monkeypatch.setattr(bridge, "ThreadingHTTPServer", _Boom(errno.EAFNOSUPPORT))
    monkeypatch.setattr(bridge, "BridgeState", lambda: SimpleNamespace(session=None))
    monkeypatch.setattr(bridge, "_port_holder_is_bridge", lambda h, p: True)
    bridge.serve(host="127.0.0.1", port=9876)
    out = capsys.readouterr().out
    assert "could not be opened" in out, out
    assert "held by another process" not in out and "below 1024" not in out, out


def test_a_rejected_port_is_said_where_somebody_is_watching_a_bridge_start(monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "abc")
    try:
        importlib.reload(config)
        monkeypatch.setattr(bridge, "ThreadingHTTPServer", _Boom(errno.EADDRINUSE))
        monkeypatch.setattr(bridge, "BridgeState", lambda: SimpleNamespace(session=None))
        monkeypatch.setattr(bridge, "_port_holder_is_bridge", lambda h, p: True)
        bridge.serve()
        out = capsys.readouterr().out
        assert "'abc'" in out and "9876" in out, out
    finally:
        monkeypatch.delenv("SUPER_AGENT_BRIDGE_PORT", raising=False)
        importlib.reload(config)


@pytest.mark.parametrize("platform,must,mustnt", [
    ("win32", "findstr", "lsof"),
    ("darwin", "lsof", "findstr"),
    ("linux", "ss -lptn", "findstr"),
])
def test_the_holder_hint_runs_on_the_machine_that_prints_it(monkeypatch, platform, must, mustnt):
    """⛔⛔ THE ONE DIAGNOSTIC THIS PACKAGE HANDED OUT WAS WINDOWS-ONLY, EVERYWHERE.
    `netstat -ano | findstr :PORT` — `findstr` is a Windows built-in that exists on
    neither macOS nor Linux, and the fleet's Linux sandbox is the one deployment
    whose stdout is kept, so the unrunnable command is the one that got written
    down. A command that cannot exist is worse than no command: the person
    concludes the tool is broken some other way and stops looking."""
    monkeypatch.setattr(bridge.sys, "platform", platform)
    hint = bridge._find_holder_hint(9876)
    assert must in hint and mustnt not in hint, hint
    assert "9876" in hint, hint


def _doctor_output(monkeypatch, tmp_path) -> str:
    """`doctor` with everything else stubbed out, so only the port row varies.

    Mirrors `test_agent_log_out_0826._doctor_output` deliberately rather than
    importing it — a shared fixture would make one file's stubs decide another
    file's assertions, and this one has to control `config` itself."""
    import argparse
    import io as _io
    from facade import cli
    monkeypatch.setattr(cli.config, "log_path", lambda: tmp_path / "bridge.log")
    monkeypatch.setattr(cli.config, "VERBOSE", False)
    monkeypatch.setattr(cli.requests, "get",
                        lambda *a, **k: SimpleNamespace(status_code=200))
    monkeypatch.setattr(cli, "_bridge_get", lambda p: None)   # bridge down
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: None))
    buf = _io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    cli.cmd_doctor(argparse.Namespace())
    return buf.getvalue()


def test_doctor_names_a_refused_port_before_it_calls_the_bridge_down(monkeypatch, tmp_path):
    """⛔⛔ A MUTATION SURVIVED HERE. `doctor` is the one command somebody runs when
    the bridge is unreachable — and a refused SUPER_AGENT_BRIDGE_PORT is a reason
    it would be, because this command and the bridge then look for each other on
    two different ports. Every symptom of that is indistinguishable from "the
    bridge is down", which is exactly what the next row says. Nothing tested it, so
    the row could be deleted with a green suite."""
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "not-a-port")
    try:
        importlib.reload(config)
        from facade import cli
        monkeypatch.setattr(cli, "config", config)
        out = _doctor_output(monkeypatch, tmp_path)
        assert "not-a-port" in out, out
        assert "9876" in out, out
        assert out.index("not-a-port") < out.index("down"), (
            "the reason must come before the symptom it explains", out)
        # ⚠ `_doctor_row` pads its label with ljust(10); an eleven-character label
        # renders welded to its own text. Found by cross-verification, not by a
        # test, which is why there is one now.
        assert "portignoring" not in out, ("label welded to the detail", out)
    finally:
        monkeypatch.delenv("SUPER_AGENT_BRIDGE_PORT", raising=False)
        importlib.reload(config)


def test_doctor_stays_quiet_about_a_port_it_accepted(monkeypatch, tmp_path):
    """⛔ INCLUDING PORT 9 — the incident's own value. It is numeric and in range,
    so it is ACCEPTED, and the row must not appear. A version that reported every
    non-default port would put a warning in front of everyone who legitimately
    moved the bridge."""
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "9")
    try:
        importlib.reload(config)
        from facade import cli
        monkeypatch.setattr(cli, "config", config)
        out = _doctor_output(monkeypatch, tmp_path)
        assert "ignoring SUPER_AGENT_BRIDGE_PORT" not in out, out
    finally:
        monkeypatch.delenv("SUPER_AGENT_BRIDGE_PORT", raising=False)
        importlib.reload(config)


# ── 3. `updates` owes the person the note it just took ───────────────────────

def _updates_body(**signed):
    return {"runs": [], "signedIn": signed} if signed else {"runs": []}


def test_updates_renders_the_signin_note_it_consumed(monkeypatch, capsys):
    """⛔⛔ THE SILENT EATER. `?via=agent` is the bridge's sole take-and-clear
    trigger and it does not care which agent-side reader asked. An `updates` call
    consumed the one-shot announce, moved the delivered watermark with it — so the
    re-mint could not recover it either — and then rendered runs only. Permanent,
    silent, and produced by somebody asking a reasonable question.

    ⭐ RENDER, DO NOT PEEK. Taking is right: it is what stops the watchdog saying
    the same news a minute later, and it is what the fleet's `login-done` already
    does with the same call. The rule the take implies is the one that was broken —
    whoever takes this note owes the person its contents."""
    monkeypatch.setattr(sr, "_fetch_runs",
                        lambda **kw: (200, _updates_body(email="a@x.y", topic="EVs",
                                                         autoStarted=True,
                                                         deviceName="Office PC"), []))
    monkeypatch.setattr(sr, "_stream_health_lines", lambda runs: [])
    sr.main(["updates"])
    out = capsys.readouterr().out
    assert "a@x.y" in out, out
    assert "EVs" in out and "Office PC" in out, out


def test_updates_still_asks_via_agent(monkeypatch):
    """⭐ THE TAKE IS DELIBERATE AND MUST NOT BE REMOVED BY A FIX FOR THE RENDER.
    Dropping `via=agent` would stop the eating and also stop the per-phase link
    minting this command exists for."""
    seen = {}
    monkeypatch.setattr(sr, "_fetch_runs",
                        lambda **kw: seen.update(kw) or (200, _updates_body(), []))
    monkeypatch.setattr(sr, "_stream_health_lines", lambda runs: [])
    sr.main(["updates"])
    assert seen.get("via_agent") is True, seen


def test_a_plain_signin_says_that_and_nothing_it_cannot_know(monkeypatch, capsys):
    """⛔ NAMED AND DOCUMENTED FOR THE OPPOSITE OF WHAT IT ASSERTED, until
    cross-verification read it. It used to be called "..._adds_nothing" and to
    claim `[]` was the honest answer — while asserting, correctly, that the line
    IS printed. Saying nothing here would be the silent eater one function
    further in: this read has already CONSUMED the announce, so the news would be
    destroyed and never reach anybody. One line, and not a word beyond it."""
    monkeypatch.setattr(sr, "_fetch_runs",
                        lambda **kw: (200, _updates_body(email="a@x.y"), []))
    monkeypatch.setattr(sr, "_stream_health_lines", lambda runs: [])
    sr.main(["updates"])
    out = capsys.readouterr().out
    assert "Signed in" in out, out
    assert "nowhere to run" not in out and "Continue with" not in out, out


def test_the_which_computer_ask_is_not_worded_a_third_time(monkeypatch):
    """⛔ THAT QUESTION ALREADY EXISTS IN TWO PLACES THAT A TEST PINS AGAINST EACH
    OTHER, precisely so one question does not get two phrasings depending which
    door the person came through. This renderer delegates rather than writing a
    third — asserted on the delegation, because asserting on the words would pass
    against a copy."""
    called = {}
    monkeypatch.setattr(sr, "_pick_device_lines",
                        lambda body, reason: called.update(body=body, reason=reason) or ["X"])
    out = sr._signed_in_lines({"email": "a@x.y", "needsDeviceChoice": True,
                               "devices": [{"name": "PC"}], "staleSelection": True})
    assert out[-1] == "X"
    assert called["reason"] == "stale_selection", called
    assert called["body"]["devices"] == [{"name": "PC"}], called


@pytest.mark.parametrize("note", [None, {}, "nope", 7, []])
def test_a_missing_or_malformed_note_renders_nothing(note):
    assert sr._signed_in_lines(note) == []


# ── 3b. a promise is a claim about a sender ──────────────────────────────────
#
# ⛔⛔ THESE FOUR EXIST BECAUSE THREE MUTANTS SURVIVED. The commit's own headline —
# "I'll post here when it's done" made conditional on a cron row actually being
# written — had NO test anywhere in either repo, so it could be reverted to the
# exact sentence it fixes with a fully green suite. Found by the harness (A1, A2,
# A3) and by cross-verification independently, which is the only reason it is not
# still true.

def _research_started(monkeypatch, capsys, armed):
    monkeypatch.setattr(sr, "_post", lambda path, body=None: (200, {"deviceId": "d1"}))
    monkeypatch.setattr(sr, "_device_names", lambda: {"d1": "Office PC"})
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {"armed": armed}, 0))
    sr.main(["research", "the EV battery market"])
    return capsys.readouterr().out


def test_a_started_run_promises_a_follow_up_only_when_one_was_armed(monkeypatch, capsys):
    """⛔⛔ NOTHING IN THIS PACKAGE SCHEDULES. The only thing that ticks is a cron
    row in the host runtime's own store, and `_prepare_stream_arm` either writes it
    or reports that it could not — it hard-codes `armed: False` on the legacy
    no-origin branch, where a runtime that supplies no chat origin can never be
    delivered to at all. The promise was printed three lines ABOVE that call."""
    out = _research_started(monkeypatch, capsys, False)
    assert "Started" in out, out
    assert "post here when it" not in out, (
        "it promised a message with no sender", out)
    assert "Ask me how it" in out, out


def test_the_armed_case_still_promises_it_because_there_it_is_true(monkeypatch, capsys):
    """The other half, pinned against the first. A fix that made the unarmed branch
    honest while quietly dropping the promise from the armed one would read as a
    pass and would be a regression — the armed case is the common one."""
    out = _research_started(monkeypatch, capsys, True)
    assert "post here when it" in out, out
    assert "going anytime" in out, ("the invitation to ask is in both arms", out)


def _research_signed_out(monkeypatch, capsys, armed, *, in_flight):
    def _post(path, body=None):
        if path == "/research":
            return 401, {"error": "not signed in"}
        if path == "/login/remote/pending":
            return 200, {"ok": True}
        if path == "/login/remote/start":
            return 200, {"verifyUrl": "https://superresearch.io/c/XYZ"}
        return 200, {}
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_get", lambda path, **kw: (
        200, {"remoteLogin": "pending"} if in_flight else {"authed": False}))
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {"armed": armed}, 0))
    sr.main(["research", "the EV battery market"])
    return capsys.readouterr().out


@pytest.mark.parametrize("in_flight", [True, False])
def test_neither_signed_out_door_promises_a_pickup_with_nothing_armed(
        monkeypatch, capsys, in_flight):
    """Both doors carried the same claim and only one of them was pinned, so a
    mutant of the other survived. "I'll pick this up" is the watchdog's job; with
    no watchdog there is nobody to pick anything up."""
    out = _research_signed_out(monkeypatch, capsys, False, in_flight=in_flight)
    assert "pick this up" not in out, out
    assert "tell me and I" in out, out


@pytest.mark.parametrize("in_flight", [True, False])
def test_both_signed_out_doors_promise_it_when_the_arm_landed(
        monkeypatch, capsys, in_flight):
    out = _research_signed_out(monkeypatch, capsys, True, in_flight=in_flight)
    assert "pick this up" in out, out


# ── 4. arming forgets the previous attempt's countdown ───────────────────────

def test_arming_clears_a_poisoned_login_wait(tmp_path, monkeypatch):
    """⛔⛔ ONE ABANDONED SIGN-IN POISONED THE CHAT FOREVER. `_tick_unauthed` counts
    401 ticks into `__login_wait__` and tears the cron row down once the count
    passes the limit — and the give-up returns BEFORE the state write, so the file
    is left holding the limit permanently. Nothing else reset it: arming rewrites
    the shim and the cron row and never touches the state file, and the only other
    reset is a 200 tick, which a signed-out chat cannot reach. So every later
    `login` armed a listener that died on its FIRST tick, and a sign-in completed
    ninety seconds later announced nothing at all.

    ⚠ THE LITERAL SCENARIO IN THE PLAN CANNOT HAPPEN, and this is the shape that
    can. A remote flow is clamped to 900s, so a sign-in cannot complete at minute
    19 of the attempt that armed the listener; the watcher outliving one flow is
    correct. It is the SECOND attempt that dies."""
    state = tmp_path / ".sr_poll_telegram-111.state.json"
    state.write_text(json.dumps({"__login_wait__": 18, "abc123": {"needs": False}}),
                     encoding="utf-8")
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    sr._clear_login_wait("telegram-111")
    left = json.loads(state.read_text(encoding="utf-8"))
    assert "__login_wait__" not in left
    assert left["abc123"] == {"needs": False}, (
        "the run de-dup keys must survive — dropping those re-announces every "
        "finished run", left)


def test_arming_is_what_clears_it(tmp_path, monkeypatch):
    """⭐ ARMING IS THE EVENT "a new sign-in attempt begins for this chat", which is
    exactly the scope `_LOGIN_WAIT_LIMIT`'s own docstring claims to bound. Pinned
    through `_prepare_stream_arm` rather than the helper, because a helper nobody
    calls is the failure this whole stretch keeps finding."""
    cleared = []
    monkeypatch.setattr(sr, "_clear_login_wait", lambda slug: cleared.append(slug))
    monkeypatch.setattr(sr, "_origin_from_env",
                        lambda: {"platform": "telegram", "chat_id": "111"})
    monkeypatch.setattr(sr, "_write_poll_shim", lambda d, n, o: "")
    monkeypatch.setattr(sr, "_arm_stream_cron", lambda *a, **kw: True)
    sr._prepare_stream_arm()
    assert cleared == [sr._origin_slug({"platform": "telegram", "chat_id": "111"})], cleared


def test_a_missing_or_unreadable_state_file_never_blocks_an_arm(tmp_path, monkeypatch):
    """Best-effort, like the rest of the arm path. A state file we cannot read is
    not a reason to refuse to arm the thing that delivers the news."""
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    sr._clear_login_wait("telegram-111")            # nothing there at all
    (tmp_path / ".sr_poll_telegram-111.state.json").write_text("{not json", encoding="utf-8")
    sr._clear_login_wait("telegram-111")            # unreadable
    (tmp_path / ".sr_poll_telegram-111.state.json").write_text("[]", encoding="utf-8")
    sr._clear_login_wait("telegram-111")            # right JSON, wrong shape
    assert (tmp_path / ".sr_poll_telegram-111.state.json").read_text(encoding="utf-8") == "[]"


# ── 5. the first-come guard stops naming a chat it has not seen ──────────────

def _live(monkeypatch, uid="u1"):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    FakeFS.devices = []
    state = bridge.BridgeState()
    state.set_session(_sess(uid))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", state, httpd


def _arm_pending(state, *, topic, origin):
    flow = SimpleNamespace(state="pending", pending_topic=topic, origin=origin,
                           code="C", verifyUrl="u", poll_token="p")
    state.set_remote(flow)
    return flow


def test_an_origin_less_chat_may_correct_its_own_topic(monkeypatch):
    """⛔⛔ THE CELL THE GUARD SHOULD NEVER HAVE REFUSED. Both sides anonymous: the
    bridge holds no evidence a second chat exists at all — both `_clean_origin`
    calls returned None — so "from another chat" was an assertion about the world
    made from nothing, and it cost the origin-less client the ability to correct or
    retry its OWN topic, permanently.

    ⭐ AND `/login/remote/start` — the door that MINTS the flow — already takes
    exactly this trade for exactly this population ("there is no way to tell them
    from themselves"). Until now `/pending` was STRICTER than the door upstream of
    it, which is incoherent."""
    base, state, httpd = _live(monkeypatch)
    try:
        flow = _arm_pending(state, topic="first try", origin=None)
        r = requests.post(base + "/login/remote/pending",
                          json={"pending_topic": "what I actually meant"})
        assert r.status_code == 200, r.text
        assert flow.pending_topic == "what I actually meant"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("held,incoming", [
    # ⛔ THE CLAUSE IS `and`, NEVER `or`. These are the two thefts cross-verification
    # found; an `or` in the carve-out reopens both, and each is worse than the bug
    # the carve-out fixes.
    ({"platform": "telegram", "chat_id": "111"}, None),
    (None, {"platform": "whatsapp", "chat_id": "222"}),
    # A half-origin is anonymous on the side that sends it and must not pass as
    # proof — the same treatment `_same_origin` already gives it.
    ({"platform": "telegram", "chat_id": "111"}, {"platform": "telegram"}),
])
def test_one_anonymous_side_is_not_two(monkeypatch, held, incoming):
    base, state, httpd = _live(monkeypatch)
    try:
        flow = _arm_pending(state, topic="A's research", origin=held)
        body = {"pending_topic": "B's research"}
        if incoming is not None:
            body["origin"] = incoming
        r = requests.post(base + "/login/remote/pending", json=body)
        assert r.status_code == 409, r.text
        assert flow.pending_topic == "A's research"
        assert flow.origin == held
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_two_unusable_origins_are_two_anonymous_sides(monkeypatch):
    """⛔ `_clean_origin` IS THE TEST, NOT `isinstance`, and this is the only case
    that can tell them apart. A half-origin — a platform with no chat id — is a
    dict, so an isinstance check would call both sides identified, fall through to
    `_same_origin`, and refuse. But `_same_origin` itself treats a half-origin as
    unusable, so the refusal would rest on evidence the comparison it delegates to
    has already thrown away. Neither side can be shown to be a different chat, so
    neither is treated as one."""
    base, state, httpd = _live(monkeypatch)
    try:
        flow = _arm_pending(state, topic="first try", origin={"platform": "telegram"})
        r = requests.post(base + "/login/remote/pending",
                          json={"pending_topic": "what I meant",
                                "origin": {"platform": "telegram"}})
        assert r.status_code == 200, r.text
        assert flow.pending_topic == "what I meant"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_refusal_no_longer_names_a_chat_it_cannot_see(monkeypatch):
    """⛔ THE CELL THAT STILL REFUSES IS ALSO WHAT A CHAT THAT LOST ITS SESSION
    ENVIRONMENT LOOKS LIKE. "from another chat" is a fact the bridge does not
    have — it knows only that something is held and this caller cannot show it
    made it. Say that."""
    base, state, httpd = _live(monkeypatch)
    try:
        _arm_pending(state, topic="A's research",
                     origin={"platform": "telegram", "chat_id": "111"})
        r = requests.post(base + "/login/remote/pending",
                          json={"pending_topic": "B's research"})
        assert r.status_code == 409
        err = r.json()["error"]
        assert r.json()["reason"] == "topic_taken", r.text
        assert "from another chat" not in err, err
        assert "can't be shown to be the one that made it" in err, err
    finally:
        httpd.shutdown()
        httpd.server_close()
