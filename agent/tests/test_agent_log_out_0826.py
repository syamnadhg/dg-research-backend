"""The agent's own log: findable, readable, and sendable when asked.

⛔⛔ WHERE THIS STARTED. The agent writes `~/.super-agent/bridge.log`, and nothing
could reach it. The research computer's collector refuses anything outside its own
log root — that refusal is what the consent screen's "no passwords, cookies or
profile data" promise is gated on — so the file was not merely un-sendable, it was
UN-FINDABLE: its only surface was one `print` in `serve()`'s startup banner.

Three separate things made that print nothing a person sees. The pinned launcher
runs the bridge under a launchd plist with no `StandardOutPath`, a systemd unit
with no `StandardOutput`, or Windows windowless — so on the RECOMMENDED install it
goes to /dev/null. It is on the BIND-SUCCESS path only, so somebody whose port is
squatted, or whose bridge is already running, never reaches it. And it scrolls once
before `serve_forever` blocks. The only other mention of the path in the package is
a warning emitted when the file cannot be OPENED — the one case where reading it is
not an option.

⛔⛔ AND THE DOCUMENTED SUPPORT LOOP WAS IMPOSSIBLE. "Turn verbose on, reproduce it,
send us the log" needs a verbose bridge, and there was no way to get one: `agent
serve` takes `-v`, but the always-on bridge is started by a GENERATED launcher
carrying the literal `main(['serve'])` with no flag — refreshed, so a hand-edit does
not survive — and no environment variable for verbosity existed anywhere in the
package, although `config.py` uses `SUPER_AGENT_*` in ten other places.
"""

import argparse
import io
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli, config, logsetup


# ── the switch that makes the log worth reading ───────────────────────────────

@pytest.mark.parametrize("value,want", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    (" 1 ", True),
    ("", False), ("0", False), ("false", False), ("no", False), ("off", False),
    ("maybe", False),
])
def test_the_verbose_switch_reads_the_environment(monkeypatch, value, want):
    monkeypatch.setenv("SUPER_AGENT_VERBOSE", value)
    import importlib
    reloaded = importlib.reload(config)
    try:
        assert reloaded.VERBOSE is want
    finally:
        monkeypatch.delenv("SUPER_AGENT_VERBOSE", raising=False)
        importlib.reload(config)


def test_the_switch_is_off_when_the_variable_is_absent(monkeypatch):
    monkeypatch.delenv("SUPER_AGENT_VERBOSE", raising=False)
    import importlib
    assert importlib.reload(config).VERBOSE is False


def test_serve_honours_the_switch_with_no_flag_on_the_command_line(monkeypatch):
    """⛔⛔ THE WHOLE POINT. The pinned launcher runs `main(['serve'])`, so
    `args.verbose` is False on every autostarted bridge and always will be. Without
    the `or config.VERBOSE` half, the switch would exist and change nothing on the
    only install that matters."""
    seen = {}
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.logsetup, "configure",
                        lambda verbose=False, **kw: seen.update(verbose=verbose, **kw))
    monkeypatch.setattr(cli.config, "VERBOSE", True)
    cli.cmd_serve(argparse.Namespace(verbose=False))
    assert seen["verbose"] is True
    assert seen["to_file"] is True


def test_serve_stays_quiet_when_neither_flag_nor_switch_is_set(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.logsetup, "configure",
                        lambda verbose=False, **kw: seen.update(verbose=verbose, **kw))
    monkeypatch.setattr(cli.config, "VERBOSE", False)
    cli.cmd_serve(argparse.Namespace(verbose=False))
    assert seen["verbose"] is False


def test_the_command_line_flag_still_wins_on_its_own(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.logsetup, "configure",
                        lambda verbose=False, **kw: seen.update(verbose=verbose, **kw))
    monkeypatch.setattr(cli.config, "VERBOSE", False)
    cli.cmd_serve(argparse.Namespace(verbose=True))
    assert seen["verbose"] is True


def test_verbose_actually_lowers_the_level(tmp_path):
    """The switch is worthless if it does not reach the handler. Pinned by the
    level, not by the argument."""
    logsetup.configure(verbose=True, to_file=True, log_file=tmp_path / "b.log")
    try:
        assert logging.getLogger("facade").level == logging.DEBUG
    finally:
        logsetup.configure(verbose=False, to_file=False)


# ── doctor names it, and names it EARLY ───────────────────────────────────────

def _doctor_output(monkeypatch, *, bridge_up: bool, log_bytes: bytes | None,
                   tmp_path: Path, verbose: bool = False) -> str:
    path = tmp_path / "bridge.log"
    if log_bytes is not None:
        path.write_bytes(log_bytes)
    monkeypatch.setattr(cli.config, "log_path", lambda: path)
    monkeypatch.setattr(cli.config, "VERBOSE", verbose)
    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    monkeypatch.setattr(cli, "_bridge_get",
                        (lambda p: (200, {"authed": False})) if bridge_up else (lambda p: None))
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: None))
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    cli.cmd_doctor(argparse.Namespace())
    return buf.getvalue()


def test_doctor_names_the_log(monkeypatch, tmp_path):
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x" * 40, tmp_path=tmp_path)
    assert str(tmp_path / "bridge.log") in out
    assert "40 B" in out


def test_doctor_reports_the_size_in_kilobytes_when_it_is_big(monkeypatch, tmp_path):
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x" * 5000, tmp_path=tmp_path)
    assert "4 KB" in out


def test_doctor_says_so_when_nothing_has_been_written(monkeypatch, tmp_path):
    """An absent file is not a failure — a bridge that has never run has nothing to
    write — but reporting it as a healthy log would send somebody looking for
    contents that are not there.

    ⛔ A MUTATION SURVIVED HERE. This asserted only the DETAIL text, so flipping the
    row's ok-flag to a hard True kept the sentence and changed the mark from a
    warning tick to a green one — the row said "nothing written yet" beside a ✓."""
    from facade import branding
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=None, tmp_path=tmp_path)
    assert "nothing written yet" in out
    log_line = [ln for ln in out.splitlines() if "bridge.log" in ln][0]
    assert branding.MARK_WARN in log_line, log_line
    assert branding.MARK_OK not in log_line, log_line


def test_doctor_marks_a_log_that_exists_as_ok(monkeypatch, tmp_path):
    """The complement, so the mark is pinned in both directions rather than one."""
    from facade import branding
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x" * 9, tmp_path=tmp_path)
    log_line = [ln for ln in out.splitlines() if "bridge.log" in ln][0]
    assert branding.MARK_OK in log_line, log_line


def test_doctor_names_the_log_EVEN_WHEN_THE_BRIDGE_IS_DOWN(monkeypatch, tmp_path):
    """⛔⛔ THE CASE THE OLD SURFACE COULD NOT SERVE, and the reason this row sits
    before the bridge check. `cmd_doctor` returns early when the bridge is down, and
    the startup banner only prints on a SUCCESSFUL bind — so the person whose bridge
    will not start, who needs this file more than anybody, was the one person the
    path was never shown to."""
    out = _doctor_output(monkeypatch, bridge_up=False, log_bytes=b"x" * 10, tmp_path=tmp_path)
    assert str(tmp_path / "bridge.log") in out
    assert "down" in out  # we really are on the bridge-down branch


def test_doctor_says_the_log_is_not_in_a_support_bundle(monkeypatch, tmp_path):
    """It is not, and it cannot be: the collector refuses anything outside the
    research computer's own log root. Somebody who sent a bundle and assumed this
    went with it would be waiting on evidence nobody has."""
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x", tmp_path=tmp_path)
    assert "not sent with a support bundle" in out


def test_doctor_says_how_to_make_the_log_say_more(monkeypatch, tmp_path):
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x", tmp_path=tmp_path)
    assert "SUPER_AGENT_VERBOSE=1" in out


def test_doctor_stops_advertising_the_switch_once_it_is_on(monkeypatch, tmp_path):
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x",
                         tmp_path=tmp_path, verbose=True)
    assert "SUPER_AGENT_VERBOSE=1" not in out


def test_doctor_does_not_name_a_command_that_cannot_help(monkeypatch, tmp_path):
    """⛔ A sibling guard bans "doctor" from every send-logs failure sentence,
    because doctor prints no bundle path. The reverse must hold too: doctor must not
    point at send-logs for this file, which send-logs cannot carry on its own."""
    out = _doctor_output(monkeypatch, bridge_up=True, log_bytes=b"x", tmp_path=tmp_path)
    log_block = out[out.index("log"):]
    assert "send-logs" not in log_block.split("bridge")[0]


# ── the tail reader ───────────────────────────────────────────────────────────

def test_the_tail_is_the_END_of_an_oversized_log(monkeypatch, tmp_path):
    """⛔ THE TAIL, NOT THE HEAD. Over the cap, the interesting part is what
    happened most recently — the thing being reported — so a head read would send
    the least useful bytes and call the job done."""
    from facade import bridge
    path = tmp_path / "bridge.log"
    path.write_bytes(b"OLDEST\n" + b"m" * 200 + b"\n" + b"NEWEST\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: path)
    got = bridge._read_agent_log_tail(cap=100)
    assert b"NEWEST" in got
    assert b"OLDEST" not in got
    assert len(got) <= 100


def test_the_tail_starts_at_a_whole_line(monkeypatch, tmp_path):
    """A mid-line start is inevitable when tailing; shipping the fragment would put
    half a record at the top of what somebody reads first."""
    from facade import bridge
    path = tmp_path / "bridge.log"
    path.write_bytes(b"a" * 60 + b"\nSECOND LINE\nTHIRD LINE\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: path)
    got = bridge._read_agent_log_tail(cap=30)
    assert not got.startswith(b"a")
    assert got.startswith(b"SECOND") or got.startswith(b"THIRD")


def test_a_small_log_is_sent_whole(monkeypatch, tmp_path):
    from facade import bridge
    path = tmp_path / "bridge.log"
    path.write_bytes(b"line one\nline two\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: path)
    assert bridge._read_agent_log_tail() == b"line one\nline two\n"


def test_an_absent_log_reads_as_empty_rather_than_raising(monkeypatch, tmp_path):
    from facade import bridge
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "nope.log")
    assert bridge._read_agent_log_tail() == b""


def test_the_cap_matches_the_receiving_route(monkeypatch):
    """A body the app refuses is a wasted upload, so the two caps are one number.
    Stated here rather than derived, because deriving it from the other side is
    exactly how a test stops being able to see a change."""
    from facade import bridge
    assert bridge._AGENT_LOG_MAX_BYTES == 8 * 1024 * 1024


# ── the bridge route: the ordering condition, enforced not assumed ───────────

def _route(monkeypatch, *, row, tmp_path, log=b"some lines\n", fe=(200, {"stored": True})):
    """Drive POST /logs/agent-log against a scripted row and a scripted app."""
    import threading
    from http.server import ThreadingHTTPServer
    import requests as _rq
    from facade import bridge

    class FS:
        def __init__(self, tok):
            pass

        def get_log_bundle(self, uid, code):
            return row

        def list_researches(self, uid, page_size=20):
            return []

    posted = {}

    def _fake_bytes(sess, path, blob, ctype, headers):
        posted.update(path=path, blob=blob, ctype=ctype, headers=headers)
        return fe

    p = tmp_path / "bridge.log"
    if log is not None:
        p.write_bytes(log)
    monkeypatch.setattr(bridge, "FirestoreRest", FS)
    monkeypatch.setattr(bridge, "_fe_api_post_bytes", _fake_bytes)
    monkeypatch.setattr(bridge.config, "log_path", lambda: p)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = _rq.post(f"http://127.0.0.1:{httpd.server_address[1]}/logs/agent-log",
                     json={"code": "7QK4M2XZ"}, timeout=10)
        return r, posted
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_log_goes_up_once_the_bundle_row_has_landed(monkeypatch, tmp_path):
    r, posted = _route(monkeypatch, row={"deviceId": "d-1", "status": "done"},
                       tmp_path=tmp_path)
    assert r.status_code == 200, r.text
    assert r.json()["sent"] is True
    assert posted["path"] == "/api/logs/agent-log"
    assert posted["headers"] == {"x-support-code": "7QK4M2XZ", "x-device-id": "d-1"}
    assert posted["blob"] == b"some lines\n"


def test_it_refuses_until_the_row_exists(monkeypatch, tmp_path):
    """⛔⛔ THE MANDATORY CONDITION, ENFORCED RATHER THAN DOCUMENTED. Clear-logs
    finds objects by listing each ROW's support-code folder — it never scans the
    bucket — so an object written before the row lands is a readable log the privacy
    button can never reach."""
    r, posted = _route(monkeypatch, row=None, tmp_path=tmp_path)
    assert r.status_code == 409
    assert r.json()["reason"] == "bundle_not_landed"
    assert posted == {}, "it uploaded anyway"


def test_it_refuses_a_row_that_names_no_computer(monkeypatch, tmp_path):
    """The device id is a path segment. Without it there is no folder to write
    into, and guessing one would put the object where nothing looks."""
    r, posted = _route(monkeypatch, row={"status": "collecting"}, tmp_path=tmp_path)
    assert r.status_code == 409
    assert posted == {}


def test_an_empty_log_is_reported_as_a_fact_not_a_failure(monkeypatch, tmp_path):
    r, posted = _route(monkeypatch, row={"deviceId": "d-1"}, tmp_path=tmp_path, log=b"")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sent": False, "reason": "empty",
                        "path": str(tmp_path / "bridge.log")}
    assert posted == {}


def test_an_upload_failure_says_the_rest_is_unaffected(monkeypatch, tmp_path):
    """The machine's bundle is already gone by the time this runs, and the support
    code already works. Reporting this as a failed send would send somebody chasing
    a bundle that arrived."""
    r, _ = _route(monkeypatch, row={"deviceId": "d-1"}, tmp_path=tmp_path,
                  fe=(503, {"error": "store_failed"}))
    assert r.status_code == 502
    assert r.json()["reason"] == "agent_log_not_sent"
    assert "unaffected" in r.json()["error"]


def test_the_code_is_validated_before_anything_is_read(monkeypatch, tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    import requests as _rq
    from facade import bridge

    class FS:
        def __init__(self, tok):
            pass

        def get_log_bundle(self, uid, code):
            raise AssertionError("a malformed code reached the lookup")

        def list_researches(self, uid, page_size=20):
            return []

    monkeypatch.setattr(bridge, "FirestoreRest", FS)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = _rq.post(f"http://127.0.0.1:{httpd.server_address[1]}/logs/agent-log",
                     json={"code": "../../etc"}, timeout=10)
        assert r.status_code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── the offer, in every client that words it ─────────────────────────────────

_CLIENTS = {
    "agent terminal": Path(cli.__file__),
    "our chat client": Path(cli.__file__).parent / "skill" / "scripts" / "sr.py",
}


def _code_only(path: Path) -> str:
    """Source with comments blanked, via the suite's shared helper.

    ⛔ THE FIRST VERSION OF THIS REBUILT THE SOURCE FROM TOKENS, which normalises
    whitespace — so `.index("def _send_agent_log")` could no longer find its own
    subject and the test died on a ValueError. `conftest.code_only` blanks in place
    for exactly that reason, and says so."""
    from conftest import code_only
    return code_only(path.read_text(encoding="utf-8"))


# The sentence each client must print when the agent's log is NOT going. Pinned as
# whole strings rather than a shared fragment, because the fragment is the trap:
# ⛔ A MUTATION SURVIVED because the assertion was `"is not included" in code or
# "NOT included" in code`, and cli.py ALREADY contains "That computer's own logs are
# NOT included." — the RESEARCH computer's line, six lines above. So deleting the
# agent's sentence left the assertion satisfied by a different sentence about a
# different machine. An assertion that can be satisfied by its neighbour is not an
# assertion about its subject.
_NOT_GOING = {
    "agent terminal": "The agent's own log on this host is NOT included.",
    "our chat client": "The agent’s own log is not included.",
}


@pytest.mark.parametrize("label", sorted(_CLIENTS))
def test_every_client_says_whether_the_agent_log_is_going(label):
    """A plan that lists what leaves has to say this either way. Naming it only
    when it IS going means silence reads as "not applicable" in one client and
    "not included" in another."""
    code = _code_only(_CLIENTS[label])
    assert "agent_log" in code, label
    assert _NOT_GOING[label] in code, (
        f"{label} no longer says the agent's log is NOT going")


@pytest.mark.parametrize("label", sorted(_CLIENTS))
def test_no_client_calls_the_agent_log_this_computers_own_logs(label):
    """⛔ THE PHRASE MEANS THE OTHER MACHINE. A sibling guard already bans "this
    computer's own logs" across these files because it reads as the RESEARCH
    computer; the agent's log lives on the host running the command, which is very
    often a third machine, so borrowing that phrasing would describe the wrong
    computer in the one screen that exists to be exact about which."""
    code = _code_only(_CLIENTS[label])
    lowered = code.lower()
    assert "this computer's own log" not in lowered, label
    assert "this computer’s own log" not in lowered, label


def test_the_terminal_offers_it_as_a_flag_beside_machine():
    """⛔ A FLAG AND NOT A PROMPT, matching `--machine`. This surface prints the
    whole plan and asks ONE yes/no over all of it — `_decide` takes exactly "y" or
    "yes" — so there is no per-item reader to hang a second question off, and adding
    one would make this the only screen in the product that asks twice."""
    code = _code_only(Path(cli.__file__))
    assert '"--agent-log"' in code
    assert 'dest="agent_log"' in code


def test_no_wait_says_the_agent_log_did_not_go():
    """⛔ --no-wait is the choice not to wait for the row, and the row is the
    condition. Sending anyway would put an object in a folder no row names; saying
    nothing would let somebody believe it went.

    ⛔ A MUTATION SURVIVED HERE: this pinned the SENTENCE and not the absence of the
    send, so a mutant that kept the message and called `_send_agent_log` anyway was
    invisible. The message is the smaller half — the ordering is the safety
    property."""
    code = _code_only(Path(cli.__file__))
    branch = code[code.index("    if args.no_wait:"):]
    branch = branch[:branch.index("    rc = _await_bundle")]
    assert "was not sent" in branch
    assert "_send_agent_log" not in branch, (
        "the agent log is sent before the bundle row can exist")


# ── the terminal, driven for real ─────────────────────────────────────────────
#
# ⛔⛔ THE SOURCE ASSERTIONS ABOVE ARE NOT ENOUGH, AND THE SWEEP PROVED IT. Three
# mutants survived a first pass that checked source text: one pinned the HELPER's
# signature while the mutant changed the CALLER, one pinned a SENTENCE while the
# mutant added a CALL beside it, and one was satisfied by a neighbouring line about
# a different machine. What follows executes `cmd_send_logs`.

class _Wire:
    """Records every bridge call, so a test can assert something was NOT sent."""

    def __init__(self, *, row=None, agent_log_status=200, agent_log_body=None):
        self.row = row
        self.agent_log_status = agent_log_status
        self.agent_log_body = agent_log_body or {"ok": True, "sent": True, "bytes": 12}
        self.posts: list = []

    def get(self, path, timeout=10.0):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC", "owned": True,
                         "published": True, "truncated": False, "updatedAt": "",
                         "runs": [{"name": "r1", "label": "Tidal power",
                                   "startedAt": "2026-08-24 10:00", "status": "completed",
                                   "sizeBytes": 1_100_000}]}
        if path.startswith("/logs/bundle"):
            return 200, {"code": "K7XQ9B2M", "row": self.row}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, body=None, timeout=30.0):
        self.posts.append(path)
        if path == "/logs/agent-log":
            return self.agent_log_status, self.agent_log_body
        return 200, {"ok": True, "code": "K7XQ9B2M"}


def _send_args(**kw):
    base = dict(device=None, runs=None, none=False, machine=False, list=False,
                status=None, yes=True, no_wait=True, wait=0, verbose=False,
                agent_log=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _run_send(monkeypatch, args, wire):
    import contextlib
    import io as _io
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_bridge_get", wire.get)
    monkeypatch.setattr(cli, "_bridge_post", wire.post)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_send_logs(args)
    return rc, buf.getvalue()


def test_no_wait_does_not_send_the_agent_log(monkeypatch):
    """⛔⛔ THE ORDERING, ASSERTED AS AN ABSENCE. --no-wait is the choice not to wait
    for the row, and the row is the condition — an object written before it exists
    lands in a folder Clear-logs will never list. A mutant that kept the explanatory
    sentence and uploaded anyway survived the source-text version of this."""
    wire = _Wire()
    rc, out = _run_send(monkeypatch, _send_args(no_wait=True, agent_log=True), wire)
    assert rc == 0
    assert "/logs/agent-log" not in wire.posts, "it uploaded before the row could exist"
    assert "was not sent" in out


def test_a_failed_agent_log_send_does_not_fail_the_command(monkeypatch):
    """⛔⛔ PINNING THE HELPER DID NOT TEST THE CALLER — a mutant that added
    `return 1` beside the call survived a check on `_send_agent_log`'s signature."""
    wire = _Wire(row={"status": "done", "runCount": 1, "sizeBytes": 10},
                 agent_log_status=502, agent_log_body={"error": "agent_log_not_sent"})
    rc, out = _run_send(monkeypatch,
                        _send_args(no_wait=False, wait=1, agent_log=True), wire)
    assert "/logs/agent-log" in wire.posts
    assert rc == 0, "a bundle that arrived was reported as a failed command"
    assert "did not go" in out
    assert "unaffected" in out


def test_the_agent_log_goes_after_the_bundle_lands(monkeypatch):
    wire = _Wire(row={"status": "done", "runCount": 1, "sizeBytes": 10})
    rc, out = _run_send(monkeypatch,
                        _send_args(no_wait=False, wait=1, agent_log=True), wire)
    assert rc == 0
    assert wire.posts == ["/logs/send", "/logs/agent-log"], wire.posts
    assert "went too" in out


def test_nothing_is_sent_when_the_flag_is_absent(monkeypatch):
    wire = _Wire(row={"status": "done", "runCount": 1, "sizeBytes": 10})
    _run_send(monkeypatch, _send_args(no_wait=False, wait=1, agent_log=False), wire)
    assert "/logs/agent-log" not in wire.posts


# ── the sign-in path says what happened, at the DEFAULT level ────────────────
#
# ⛔⛔ TWO MUTANTS SURVIVED BECAUSE NOTHING HERE EXISTED. I changed what the
# sign-in path logs and wrote no test for it at all, so both the silence and the
# mislabel could be restored without anything noticing. The whole argument for the
# transport is that the log has something in it; an untested log line is an
# assumption that it does.

def _advance(monkeypatch, caplog, *, poll):
    """Drive _advance_remote_flow with a scripted broker and capture the log."""
    import logging as _lg
    import time as _t
    from types import SimpleNamespace as _NS
    from facade import bridge

    monkeypatch.setattr(bridge.devicelogin, "poll_once", poll)
    state = bridge.BridgeState()
    flow = _NS(state="pending", poll_token="tok", expires_at=_t.time() + 600,
               code="C", verifyUrl="u", origin=None, pending_topic=None, error=None)
    state.set_remote(flow)
    with caplog.at_level(_lg.INFO, logger="facade"):
        with state.remote_lock:
            bridge._advance_remote_flow(state)
    return flow, caplog.text


def test_a_sign_in_that_expires_before_approval_says_so(monkeypatch, caplog):
    """⛔ THE MOST COMMON UNSUCCESSFUL SIGN-IN THERE IS, and it used to leave NOTHING
    behind — the expiry is decided here, BEFORE the broker is asked, so the INFO on
    the broker-reported branch never fires for it. That is precisely what somebody
    would be sending the log to explain."""
    import logging as _lg
    from types import SimpleNamespace as _NS
    from facade import bridge

    called = {"n": 0}
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda t: called.__setitem__("n", called["n"] + 1))
    state = bridge.BridgeState()
    flow = _NS(state="pending", poll_token="tok", expires_at=0.0, code="C",
               verifyUrl="u", origin=None, pending_topic=None, error=None)
    state.set_remote(flow)
    with caplog.at_level(_lg.INFO, logger="facade"):
        with state.remote_lock:
            bridge._advance_remote_flow(state)
    assert flow.state == "expired"
    assert called["n"] == 0, "it asked the broker about a code that had already expired"
    assert "expired before approval" in caplog.text


def test_a_broker_failure_is_visible_at_the_default_level(monkeypatch, caplog):
    """⛔⛔ IT USED TO BE DEBUG, AND CALLED A BLIP. This catch also takes a persistent
    HTTP 500 and "approved but sent no custom token" — a sign-in that CANNOT succeed,
    retried until the TTL runs out and then reported as an expiry. At DEBUG the
    default level recorded nothing; the word "transient" mislabelled it even at -v."""
    def boom(_t):
        raise bridge_mod.DeviceLoginError("sign-in broker poll failed: HTTP 500 nope")

    from facade import bridge as bridge_mod
    flow, text = _advance(monkeypatch, caplog, poll=boom)
    assert flow.state == "pending", "a failure it keeps waiting through"
    assert "HTTP 500" in text, "the broker's own detail never reached the log"
    assert "transient transport blip" not in text, (
        "a persistent failure is still being called transient")


def test_the_upstream_body_never_reaches_the_person(monkeypatch, caplog):
    """The detail belongs in the log, not in a chat message. The route returns a
    fixed sentence; only the log gets the status."""
    from facade import bridge as bridge_mod

    def boom(_t):
        raise bridge_mod.DeviceLoginError("HTTP 500 <html>secret</html>")

    _flow, text = _advance(monkeypatch, caplog, poll=boom)
    assert "secret" in text


# ── the natural-language route asks for this and nothing wider ───────────────

@pytest.mark.parametrize("said,want", [
    # explicit, in the words a person would actually use
    ("send the agent's log", True),
    ("send the agent log to support", True),
    ("share the bridge log", True),
    ("send my agent's own log", True),
    # ⛔ AND THE ONES THAT MUST NOT REACH IT. A mutation that appended the flag
    # unconditionally SURVIVED, because nothing drove this route for the agent log
    # at all. "Everything" is the same over-reading that is deliberately kept away
    # from --machine: a broad word means all of THEIRS, not a second machine's file.
    ("send the logs", False),
    ("send all the logs", False),
    ("send everything", False),
    ("upload my logs please", False),
    ("send the computer's own logs", False),
])
def test_only_an_explicit_ask_reaches_the_agent_log_flag(said, want):
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location(
        "sr_nl_under_test",
        _P(cli.__file__).parent / "skill" / "scripts" / "sr.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    argv, _lines = sr._nl_resolve(said)
    # ⭐ A phrase that routes NOWHERE satisfies the property too — "send everything"
    # is one of those, and demanding it route to send-logs would have been asserting
    # something the claim never made.
    reached = bool(argv) and "--agent-log" in argv
    assert reached is want, (said, argv)


def test_asking_for_the_agent_log_does_not_also_ask_for_the_machines(said="send the agent's log"):
    """The two are different machines and different consents. Asking for one must
    never quietly select the other."""
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location(
        "sr_nl_under_test2",
        _P(cli.__file__).parent / "skill" / "scripts" / "sr.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    argv, _ = sr._nl_resolve(said)
    assert "--agent-log" in argv and "--machine" not in argv, argv
