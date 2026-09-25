"""A login answer is about login only, and nothing false or stale is ever sent (2026-09-25).

⛔⛔ WHAT HAPPENED (owner's chat, 2026-09-24): one sign-in was announced three ways in
two minutes — "✓ Connected as … — you're all set", the watcher's "✓ Signed in as X.
Just tell me what to research.", and a run-on "Add a computer … Or ask me for a public
computer" — to somebody who had only asked whether they were logged in. The watcher's
true "✓ Signed in" then reached the chat 19 s AFTER they logged out, because SKILL.md
had Rocky tear the watcher down on logout and the runtime's queue sent it anyway. And a
`login-done` after a logout would have said "✓ Connected as None — you're all set."

⭐ THE OWNER'S DECISIONS THIS FILE PINS (binding, 2026-09-25):
  • every answer that says somebody is signed in opens with ONE line — "✓ Signed in as
    <email>." — and for a plain sign-in it IS that line: no "Add a computer", no install
    link, no public computers. Device content only in device situations;
  • every such answer tells the bridge (`POST /signin/ack`) so the watcher does not say
    it again;
  • "log me in" while signed in says so and starts nothing;
  • "Logged in?" and friends are account questions, answered by `status-account`;
  • logout keeps the watcher — only `agent disconnect` removes it;
  • the watcher ticks on minute boundaries where the runtime can compute cron;
  • the watcher prints NOTHING but the message (its record is a FILE), promises no
    per-phase progress, and says "emailed" only when email ran.
"""

from __future__ import annotations

import importlib.util
import io
import json
import threading
from contextlib import redirect_stdout
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from facade import bridge

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
_SKILL = _SCRIPTS.parent / "SKILL.md"
_README = Path(__file__).resolve().parents[1] / "README.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_login_only_0925", "sr.py")
poll = _load("poll_login_only_0925", "sr_attention_poll.py")
notice = _load("notice_login_only_0925", "sr_update_notice.py")

URL = "https://superresearch.io/install"
DEVICE_WORDS = ("Add a computer", URL, "Public computers", "access code",
                "No research computer")


def _no_device_content(out: str) -> None:
    for word in DEVICE_WORDS:
        assert word.lower() not in out.lower(), (word, out)


# ── a real bridge, an EMPTY account (the case that used to get the device lecture) ──

class FakeFS:
    devices: list = []

    def __init__(self, _tok):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def list_researches(self, uid, page_size=20, **k):
        return []

    def get_user_settings(self, uid):
        return {}


def _sess(uid="u1", email="e@x.y", cap=7_000):
    return NS(uid=uid, email=email, connected_at_ms=cap, id_token=lambda force=False: "tok")


@pytest.fixture()
def live(monkeypatch):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda **kw: None)
    FakeFS.devices = []
    state = bridge.BridgeState()
    state.set_session(_sess())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(httpd.server_address[1]))
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "111")
    monkeypatch.delenv("HERMES_SESSION_THREAD_ID", raising=False)
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _connected_flow(state):
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    flow.state = "connected"
    state.set_remote(flow)


_HERE = {"platform": "telegram", "chat_id": "111"}


# ── 1. the one sign-in line, and no device content in any login answer ──────────

def test_status_account_on_an_empty_account_is_the_sign_in_line_alone(live, capsys):
    assert sr.main(["status-account"]) == 0
    out = capsys.readouterr().out
    assert out == "✓ Signed in as e@x.y.\n", out
    _no_device_content(out)
    assert sr._AGENT_ONLY_MARKER not in out


def test_login_done_on_an_empty_account_is_the_sign_in_line_alone(live, capsys):
    _connected_flow(live)
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert out == "✓ Signed in as e@x.y.\n", out
    _no_device_content(out)


def test_login_while_signed_in_starts_nothing_and_says_so(live, capsys, monkeypatch):
    """⭐ OWNER DECISION 4. Starting a new flow here would make the bridge throw the
    parked note away — and switch accounts in one step nobody asked for."""
    started = []
    monkeypatch.setattr(bridge.devicelogin, "start",
                        lambda **kw: started.append(kw) or {})
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 0))
    live.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": _HERE,
                        "autoStarted": True, "deviceName": "Mac", "topic": "EVs"})
    assert sr.main(["login"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == ("You're already signed in as e@x.y — say log out to switch "
                           "accounts."), out
    assert not started, "no new sign-in may start"
    assert live.remote is None
    _no_device_content(out)
    # ⛔ and the note carrying news is NOT swallowed by an answer that relays none
    assert live.signed_in is not None and live.signed_in.get("autoStarted")


def test_login_signed_out_still_hands_out_a_link(monkeypatch, capsys):
    posts = []
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (200, {"authed": False}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        posts.append(p) or (200, {"verifyUrl": "https://superresearch.io/c/X"})))
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 0))
    assert sr.main(["login"]) == 0
    assert "https://superresearch.io/c/X" in capsys.readouterr().out
    assert posts == ["/login/remote/start"], posts


def test_every_watcher_sign_in_line_opens_with_the_same_line_as_the_chat():
    """⭐ ONE FIRST LINE, EVERYWHERE — the chat's `_connected_msg` and the watcher's
    first line cannot drift into two wordings again."""
    first = sr._connected_msg("e@x.y")
    notes = [
        {"email": "e@x.y"},
        {"email": "e@x.y", "pendingTopic": "EVs"},
        {"email": "e@x.y", "autoStarted": True, "deviceName": "Mac", "topic": "EVs"},
        {"email": "e@x.y", "autoStarted": True, "deviceName": "Mac", "topic": "EVs",
         "deviceOnline": False},
        {"email": "e@x.y", "needsDevice": True, "topic": "EVs"},
        {"email": "e@x.y", "needsDeviceChoice": True, "topic": "EVs",
         "devices": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]},
    ]
    for note in notes:
        line = poll._signed_in_line(note)
        assert line.splitlines()[0] == first, (note, line)
    # a plain sign-in IS that line — nothing after it
    assert poll._signed_in_line({"email": "e@x.y"}) == first
    _no_device_content(poll._signed_in_line({"email": "e@x.y"}))
    # and with no email, neither says "as None" / "as your account"
    assert poll._signed_in_line({}) == sr._connected_msg(None) == "✓ Signed in."


def test_device_content_stays_where_a_topic_has_nowhere_to_run(monkeypatch):
    """The complement: the device situation keeps its screen — in separate blocks."""
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"devices": [{"deviceId": "d1", "label": "Studio PC", "online": True}],
              "truncated": False}))
    lines = sr._signed_in_lines({"email": "e@x.y", "needsDevice": True, "topic": "EVs"})
    assert lines[0] == "✓ Signed in as e@x.y." and lines[1] == ""
    assert lines[2] == "“EVs” has nowhere to run yet." and lines[3] == ""
    blob = "\n".join(lines)
    assert sr._ADD_A_COMPUTER in lines and sr._PUBLIC_HEAD in blob
    watcher = poll._signed_in_line({"email": "e@x.y", "needsDevice": True, "topic": "EVs"})
    assert URL in watcher and "Public computers" in watcher
    assert "\n\n" in watcher


def test_the_news_blocks_are_separated_from_the_sign_in_line():
    for note in ({"email": "e@x.y", "autoStarted": True, "deviceName": "Mac", "topic": "T"},
                 {"email": "e@x.y", "pendingTopic": "T"}):
        lines = sr._signed_in_lines(note)
        assert lines[0] == "✓ Signed in as e@x.y." and lines[1] == "", lines


def test_updates_puts_a_blank_line_between_the_sign_in_and_the_runs(monkeypatch, capsys):
    monkeypatch.setattr(sr, "_fetch_runs", lambda active=False, limit=20, via_agent=False: (
        200, {"signedIn": {"ts": 1, "email": "e@x.y"}}, []))
    monkeypatch.setattr(sr, "_stream_health_lines", lambda runs: [])
    assert sr.main(["updates"]) == 0
    assert capsys.readouterr().out == "✓ Signed in as e@x.y.\n\nNo active runs.\n"


# ── 2. every "signed in" reply tells the bridge, so the watcher does not repeat it ──

def test_status_account_takes_a_plain_note_and_leaves_one_with_news(live, capsys):
    live.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": _HERE})
    assert sr.main(["status-account"]) == 0
    capsys.readouterr()
    assert live.signed_in is None, "the watcher would say it again a minute later"
    assert live.told and live.told.get("reader") == "status-account", live.told

    news = {"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": _HERE,
            "autoStarted": True, "deviceName": "Mac", "topic": "EVs"}
    live.set_signed_in(dict(news))
    assert sr.main(["status-account"]) == 0
    assert capsys.readouterr().out == "✓ Signed in as e@x.y.\n"
    assert live.signed_in is not None, "news this reply does not relay stays for the watcher"


def test_login_done_takes_the_note_with_its_news_and_relays_it(live, capsys):
    _connected_flow(live)
    live.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": _HERE,
                        "autoStarted": True, "deviceName": "Mac", "topic": "EVs"})
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("✓ Signed in as e@x.y.\n\n🚀 Started “EVs” on Mac."), out
    assert live.signed_in is None
    assert live.told.get("reader") == "login-done"


@pytest.mark.parametrize("argv, reader, news", [
    (["status-account"], "status-account", False),
    (["login-done"], "login-done", True),
    (["login"], "login", False),
])
def test_each_signed_in_reply_posts_the_ack_scoped_to_this_chat(monkeypatch, capsys,
                                                                argv, reader, news):
    posts = []

    def _post(path, body=None, timeout=None):
        posts.append((path, body))
        if path == "/login/remote/poll":
            return 200, {"state": "connected", "authed": True, "email": "e@x.y"}
        return 200, {"ok": True, "authed": True, "email": "e@x.y"}
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"authed": True, "email": "e@x.y"}))
    monkeypatch.setattr(sr, "_origin_from_env", lambda: dict(_HERE))
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 0))
    assert sr.main(argv) == 0
    acks = [b for p, b in posts if p == "/signin/ack"]
    assert len(acks) == 1, posts
    assert acks[0]["reader"] == reader
    assert acks[0]["platform"] == "telegram" and acks[0]["chat"] == "111"
    assert bool(acks[0].get("withNews")) is news
    assert "signed in as e@x.y" in capsys.readouterr().out.lower()


def test_an_older_bridge_without_the_ack_still_gets_the_note_taken(monkeypatch, capsys):
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        (404, {"error": "not found"}) if p == "/signin/ack" else
        (200, {"state": "connected", "authed": True, "email": "e@x.y"})))
    monkeypatch.setattr(sr, "_claim_signed_in_announce", lambda: {
        "ts": 1, "email": "e@x.y", "autoStarted": True, "deviceName": "Mac", "topic": "EVs"})
    assert sr.main(["login-done"]) == 0
    assert "🚀 Started “EVs” on Mac." in capsys.readouterr().out


# ── 3. nothing false after a logout ─────────────────────────────────────────────

def test_login_done_after_logout_never_says_signed_in(live, capsys):
    """⛔⛔ THE FLOW OUTLIVED THE SESSION: "connected" with nobody signed in used to
    render "✓ Connected as None — you're all set."."""
    _connected_flow(live)
    live.set_session(None)
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "Not signed in — tell me to log you in and I'll send a link.", out
    assert "Signed in" not in out and "None" not in out and "Connected" not in out


def test_the_session_flag_decides_before_anything_else_is_asked(monkeypatch, capsys):
    """The poll's `authed` is the session. With it false, nothing else is consulted —
    not even the ack, whose 401 is only the second line of defence above."""
    posts = []

    def _post(path, body=None, timeout=None):
        posts.append(path)
        if path == "/login/remote/poll":
            return 200, {"state": "connected", "authed": False}
        return 200, {"ok": True, "authed": True, "email": "stale@x.y"}
    monkeypatch.setattr(sr, "_post", _post)
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "Not signed in — tell me to log you in and I'll send a link.", out
    assert posts == ["/login/remote/poll"], posts


def test_login_done_with_no_flow_answers_from_the_account(live, capsys):
    """⛔ NEVER THE BRIDGE'S DEVELOPER WORDS ("POST /login/remote/start first")."""
    live.set_session(None)
    assert live.remote is None
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "Not signed in — tell me to log you in and I'll send a link.", out
    assert "POST" not in out and "remote" not in out


def test_login_done_with_no_flow_but_signed_in_says_the_sign_in_line(live, capsys):
    """A bridge restart forgets the flow and keeps the session."""
    assert live.remote is None
    assert sr.main(["login-done"]) == 0
    assert capsys.readouterr().out == "✓ Signed in as e@x.y.\n"


@pytest.mark.parametrize("argv", [["status-account"], ["login-done"]])
def test_a_session_that_ends_mid_answer_is_not_called_signed_in(monkeypatch, capsys, argv):
    """The ack answers 401 when the session ended between the two reads."""
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        200, {"authed": True, "email": "e@x.y"}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        (401, {"error": "not signed in", "authed": False}) if p == "/signin/ack" else
        (200, {"state": "connected", "authed": True, "email": "e@x.y"})))
    assert sr.main(argv) == 0
    out = capsys.readouterr().out
    assert "Signed in" not in out and "Not signed in" in out, out


# ── 4. the routes ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "Logged in?", "Signed in?", "logged in yet?", "logged in yet",
    "logged into super research?", "are you logged in?", "is super research logged in?",
    "login status", "Login status?", "check my login", "can you check my login",
    "did the login work?", "did the login work for the research?", "is the login done",
    "am I signed in?", "are we connected?",
])
def test_sign_in_questions_are_account_checks(said):
    assert sr._nl_resolve(said) == (["status-account"], None), said


@pytest.mark.parametrize("said, argv", [
    ("log me in", ["login"]), ("sign in", ["login"]), ("login", ["login"]),
    ("I signed in", ["login-done"]), ("I'm signed in", ["login-done"]),
    ("signed in now", ["login-done"]),
    ("research login status pages", ["research", "login status pages"]),
])
def test_the_neighbours_keep_their_routes(said, argv):
    assert sr._nl_resolve(said)[0] == argv, said


# ── 5. the watcher's schedule: minute-anchored where the runtime has croniter ────

def _arm(tmp_path, monkeypatch, *, croniter: bool, jobs=None):
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "sr_attention_poll.py").write_bytes(b"# watchdog\n")
    if jobs is not None:
        (tmp_path / "cron").mkdir(exist_ok=True)
        (tmp_path / "cron" / "jobs.json").write_bytes(json.dumps({"jobs": jobs}).encode())
    monkeypatch.setattr(sr, "_scripts_dir", lambda: scripts)
    monkeypatch.setattr(sr, "_runtime_has_croniter", lambda: croniter)
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "111")
    monkeypatch.delenv("HERMES_SESSION_THREAD_ID", raising=False)
    lines, payload, rc = sr._prepare_stream_arm()
    assert rc == 0 and lines == [] and payload["armed"] is True
    data = json.loads((tmp_path / "cron" / "jobs.json").read_bytes().decode("utf-8"))
    return payload, {j["name"]: j for j in data["jobs"]}


def test_a_new_watcher_row_is_minute_anchored_where_croniter_exists(tmp_path, monkeypatch):
    before = datetime.now(timezone.utc)
    payload, rows = _arm(tmp_path, monkeypatch, croniter=True)
    job = rows[payload["name"]]
    assert job["schedule"] == {"kind": "cron", "expr": "* * * * *", "display": "* * * * *"}
    assert payload["schedule"] == "* * * * *"
    nxt = datetime.fromisoformat(job["next_run_at"])
    # ⛔ ON the minute boundary, or the runtime re-anchors and skips the first run
    assert nxt.second == 0 and nxt.microsecond == 0, job["next_run_at"]
    assert (before - nxt).total_seconds() < 60 and nxt <= datetime.now(timezone.utc)
    # the update notice keeps its own daily interval
    assert rows["sr-update-notice"]["schedule"]["kind"] == "interval"


def test_without_croniter_the_interval_stays(tmp_path, monkeypatch):
    payload, rows = _arm(tmp_path, monkeypatch, croniter=False)
    assert rows[payload["name"]]["schedule"] == sr._STREAM_SCHEDULE
    assert payload["schedule"] == "every 1m"


def _row(name, schedule, **kw):
    return {"id": name[-6:], "name": name, "script": "sr_poll_x.py", "no_agent": True,
            "enabled": True, "state": "scheduled", "schedule": schedule,
            "schedule_display": schedule.get("display", ""),
            "next_run_at": "2026-09-25T00:00:13+00:00", **kw}


def test_existing_watcher_rows_are_migrated_once(tmp_path, monkeypatch):
    """⭐ The arm left a runnable row untouched, so every watcher already armed would
    have kept its ~2-minute interval forever. Every sr-stream row moves — once."""
    slug = sr._origin_slug({"platform": "telegram", "chat_id": "111"})
    jobs = [
        _row(f"sr-stream-{slug}", dict(sr._STREAM_SCHEDULE)),
        _row("sr-stream-whatsapp_0123456789", dict(sr._STREAM_SCHEDULE)),
        _row("sr-stream-telegram_hand", {"kind": "interval", "minutes": 5,
                                         "display": "every 5m"}),
        _row("morning-briefing", dict(sr._STREAM_SCHEDULE)),
    ]
    _payload, rows = _arm(tmp_path, monkeypatch, croniter=True, jobs=jobs)
    for name in (f"sr-stream-{slug}", "sr-stream-whatsapp_0123456789"):
        assert rows[name]["schedule"]["kind"] == "cron", name
        assert rows[name]["schedule_display"] == "* * * * *"
        assert datetime.fromisoformat(rows[name]["next_run_at"]).second == 0
    # ⛔ a schedule somebody hand-edited, and a job that is not ours, are left alone
    assert rows["sr-stream-telegram_hand"]["schedule"]["minutes"] == 5
    assert rows["morning-briefing"]["schedule"] == sr._STREAM_SCHEDULE
    assert rows["morning-briefing"]["next_run_at"] == "2026-09-25T00:00:13+00:00"

    # ONCE: a second arm finds nothing to move and writes nothing
    jobs_file = tmp_path / "cron" / "jobs.json"
    raw = jobs_file.read_bytes()
    lines, _p, rc = sr._prepare_stream_arm()
    assert rc == 0 and lines == []
    assert jobs_file.read_bytes() == raw
    log = (tmp_path / "watcher.log").read_bytes().decode("utf-8")
    assert "moved 2 watcher row(s)" in log, log


def test_a_cron_row_goes_back_to_the_interval_where_croniter_is_gone(tmp_path, monkeypatch):
    """A cron row on a runtime without croniter fires once and never again."""
    slug = sr._origin_slug({"platform": "telegram", "chat_id": "111"})
    jobs = [_row(f"sr-stream-{slug}", dict(sr._STREAM_CRON_SCHEDULE))]
    payload, rows = _arm(tmp_path, monkeypatch, croniter=False, jobs=jobs)
    assert rows[payload["name"]]["schedule"] == sr._STREAM_SCHEDULE


def test_croniter_is_looked_for_in_the_runtimes_own_environment(tmp_path, monkeypatch):
    """The `hermes` command leads to the virtualenv the gateway runs in."""
    venv = tmp_path / "hermes-agent" / ".venv"
    (venv / "bin").mkdir(parents=True)
    cli = venv / "bin" / "hermes"
    cli.write_bytes(b"#!" + str(venv / "bin" / "python3").encode() + b"\nimport sys\n")
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: str(cli) if name == "hermes" else None)
    monkeypatch.setattr(sr.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert sr._hermes_croniter_path() is None
    assert sr._stream_schedule() == sr._STREAM_SCHEDULE
    pkg = venv / "lib" / "python3.12" / "site-packages" / "croniter"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_bytes(b"")
    assert sr._hermes_croniter_path() == str(pkg / "__init__.py")
    assert sr._stream_schedule() == sr._STREAM_CRON_SCHEDULE


# ── 6. the watcher prints the message and nothing else; its record is a file ─────

def _tick(monkeypatch, tmp_path, fetched, *, origin=_HERE):
    state = tmp_path / "state.json"
    monkeypatch.setattr(poll, "_state_path", lambda o: state)
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: fetched)
    out, err = io.StringIO(), io.StringIO()
    import contextlib
    with redirect_stdout(out), contextlib.redirect_stderr(err):
        assert poll.main(origin=origin) == 0
    return out.getvalue(), err.getvalue()


def test_the_watcher_prints_nothing_but_the_message(monkeypatch, tmp_path):
    out, err = _tick(monkeypatch, tmp_path, ([], {"ts": 5, "email": "e@x.y"}))
    assert out == "✓ Signed in as e@x.y.\n", out
    assert err == ""
    log = (tmp_path / "watcher.log").read_bytes().decode("utf-8")
    slug = poll._origin_slug(_HERE)
    assert f"{slug}: printed sign-in note ts=5 (plain)" in log, log
    assert "e@x.y" not in log            # the account is masked, the way bridge.log does
    # a quiet tick prints nothing, and logs nothing new
    out2, err2 = _tick(monkeypatch, tmp_path, ([], None))
    assert out2 == "" and err2 == ""


def test_a_log_that_cannot_be_written_costs_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPER_AGENT_WATCHER_LOG", str(tmp_path))   # a DIRECTORY
    out, err = _tick(monkeypatch, tmp_path, ([], {"ts": 6, "email": "e@x.y"}))
    assert out == "✓ Signed in as e@x.y.\n" and err == ""


def test_a_signed_out_stretch_is_one_log_line_not_one_a_minute(monkeypatch, tmp_path):
    import urllib.error
    state = tmp_path / "state.json"
    poll._save_state({"__signed_in_ts__": 5}, state)
    monkeypatch.setattr(poll, "_state_path", lambda o: state)

    def _401(o=None):
        raise urllib.error.HTTPError("u", 401, "unauthorized", {}, None)
    monkeypatch.setattr(poll, "_get_updates", _401)
    buf = io.StringIO()
    with redirect_stdout(buf):
        for _ in range(3):
            assert poll.main(origin=_HERE) == 0
    assert buf.getvalue() == ""
    log = (tmp_path / "watcher.log").read_bytes().decode("utf-8")
    assert log.count("bridge read ok → http-401") == 1, log
    # ⭐ and the watcher is still there: a signed-in watcher never tears itself down
    assert "removing this listener" not in log


# ── 7. what the watcher may promise, and may claim ───────────────────────────────

def test_no_line_promises_per_phase_progress():
    lines = [
        poll._signed_in_line({"email": "e@x.y", "autoStarted": True, "deviceName": "Mac",
                              "topic": "T"}),
        poll._signed_in_line({"email": "e@x.y", "autoStarted": True, "deviceName": "Mac",
                              "topic": "T", "deviceOnline": False}),
        poll._device_access_line({"state": "approved", "deviceName": "Mac", "topic": "T",
                                  "autoStarted": True}),
        poll._device_access_line({"state": "approved", "deviceName": "Mac", "topic": "T",
                                  "autoStarted": True, "online": False}),
    ]
    for line in lines:
        assert "each phase" not in line and "post progress" not in line, line
        assert line.endswith("I'll tell you here when it finishes or needs you."), line


def test_no_list_no_invitation_to_pick_from_it():
    line = poll._signed_in_line({"email": "e@x.y", "needsDevice": True, "topic": "T"})
    assert "Tell me which one to ask for" not in line, line


@pytest.mark.parametrize("cfg, emailed", [
    ({"emailEnabled": True}, True),
    ({"emailEnabled": True, "skipPhases": []}, True),
    ({"emailEnabled": False}, False),
    ({"emailEnabled": True, "skippedPhases": [5]}, False),
    ({"skipPhases": [5]}, False),
    (None, False),          # ⛔ unknown is not "emailed": a claim we cannot back
])
def test_emailed_is_said_only_when_email_ran(cfg, emailed):
    run = {"runId": "r1", "title": "EVs", "status": "completed", "phaseUpdates": []}
    if cfg is not None:
        run["pipelineConfig"] = cfg
    banner = poll._final_lines(run)[0]
    assert ("results have been emailed" in banner) is emailed, banner
    assert banner.startswith("🎉 “EVs” · pipeline complete"), banner


def test_a_bundle_with_no_answer_is_said_once(monkeypatch, tmp_path):
    late = {"code": "AB12CD34", "deviceName": "Studio PC", "ageSeconds": 1850,
            "runCount": 2, "agentLogCode": ""}
    out, _ = _tick(monkeypatch, tmp_path, ([], None, None, None, dict(late)))
    assert "No answer yet from Studio PC about the logs for AB12CD34" in out, out
    assert "30 minutes" in out and "✓ Support has the logs" not in out
    again, _ = _tick(monkeypatch, tmp_path, ([], None, None, None, dict(late)))
    assert again == "", "said once"
    log = (tmp_path / "watcher.log").read_bytes().decode("utf-8")
    assert "support logs code=AB12CD34 still no answer after 1850s" in log


def test_the_bridge_key_reaches_the_watcher():
    """`_get_updates` must hand `supportLogsLate` on; the watcher cannot say what it
    never receives."""
    src = (_SCRIPTS / "sr_attention_poll.py").read_bytes().decode("utf-8")
    assert 'body.get("supportLogsLate")' in src


def test_the_late_notice_reaches_the_chat_through_the_real_fetch(monkeypatch, tmp_path):
    """⛔ THE SOURCE CHECK ABOVE PASSES WHILE THE KEY IS READ AND THEN DROPPED. Found
    by mutation (2026-09-25): `_get_updates` could read `supportLogsLate` and hand
    back None in its place, and nothing noticed — while the bridge marks the notice
    said the moment its bytes leave, so it is never sent again and the watch ends in
    silence after all. So the fetch is driven for real, off a stubbed loopback
    response, all the way to what the chat is shown."""
    late = {"code": "AB12CD34", "deviceName": "Studio PC", "ageSeconds": 1850,
            "runCount": 2, "agentLogCode": ""}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"runs": [], "supportLogsLate": late}).encode("utf-8")

    monkeypatch.setattr(poll.urllib.request, "urlopen", lambda req, timeout=0: _Resp())
    assert poll._get_updates(_HERE)[4] == late
    state = tmp_path / "state.json"
    monkeypatch.setattr(poll, "_state_path", lambda o: state)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert poll.main(origin=_HERE) == 0
    assert "No answer yet from Studio PC about the logs for AB12CD34" in buf.getvalue()


# ── 8. the update notice: under the lock, and said before it is recorded ───────

def _wire_notice(tmp_path, monkeypatch, body):
    state = tmp_path / ".sr_update_notice.state.json"
    monkeypatch.setattr(notice, "_state_path", lambda: state)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(body).encode()
    monkeypatch.setattr(notice.urllib.request, "urlopen", lambda url, timeout=0: _Resp())
    return state


def test_the_notice_is_recorded_only_after_it_is_printed(tmp_path, monkeypatch):
    state = _wire_notice(tmp_path, monkeypatch, {"agent": "0.1.33", "agentLatest": "0.1.34"})

    class _Broken(io.StringIO):
        def write(self, s):
            raise BrokenPipeError("the harness went away")
    with pytest.raises(BrokenPipeError), redirect_stdout(_Broken()):
        notice.main()
    saved = json.loads(state.read_bytes().decode("utf-8")) if state.exists() else {}
    assert saved.get("announced") != "0.1.34", "a notice nobody got must not be recorded"

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert notice.main() == 0
    assert "v0.1.34" in buf.getvalue()
    assert json.loads(state.read_bytes().decode("utf-8"))["announced"] == "0.1.34"
    assert "printed the update notice v0.1.33 → v0.1.34" in (
        tmp_path / "watcher.log").read_bytes().decode("utf-8")


def test_the_notice_removes_its_row_under_the_jobs_lock(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    (home / "cron").mkdir(parents=True)
    jobs = home / "cron" / "jobs.json"
    jobs.write_bytes(json.dumps({"jobs": [{"name": "sr-update-notice"},
                                          {"name": "keep-me"}]}).encode())
    monkeypatch.setattr(notice, "_hermes_home", lambda: home)
    calls = []
    replaced = []
    real_replace = notice.os.replace

    def _replace(src, dst):
        replaced.append((str(src), [c for c in calls]))
        return real_replace(src, dst)
    monkeypatch.setattr(notice, "fcntl", NS(LOCK_EX=2, LOCK_UN=8,
                                            flock=lambda fd, op: calls.append(op)))
    monkeypatch.setattr(notice.os, "replace", _replace)
    assert notice._remove_cron_entry("sr-update-notice") is True
    assert calls == [2, 8], calls                      # taken, then released
    (tmp, held_at_replace), = replaced
    assert held_at_replace == [2], "the replace happens while the lock is held"
    assert tmp.endswith(".%d" % notice.os.getpid()), tmp   # a per-process temp name
    left = json.loads(jobs.read_bytes().decode("utf-8"))["jobs"]
    assert left == [{"name": "keep-me"}]


# ── 9. the docs agree: logout keeps the watcher ──────────────────────────────────

def test_skill_md_never_tells_the_assistant_to_remove_the_watcher():
    text = " ".join(_SKILL.read_bytes().decode("utf-8").split())
    assert "tear it down" not in text
    assert 'cronjob(action="remove"' not in text
    assert "Never remove it yourself — not on `logout` either" in text
    assert "removed only by `agent disconnect`" in text


def test_skill_md_routes_login_questions_and_says_nothing_about_computers():
    text = _SKILL.read_bytes().decode("utf-8")
    row = next(ln for ln in text.splitlines() if '"Logged in?"' in ln)
    assert "`sr.py status-account`" in row and "say nothing about computers" in row
    assert "✓ Connected as" not in text
    assert "right after a fresh" in " ".join(text.split())


def test_readme_agrees_that_a_sign_out_keeps_the_watcher():
    text = " ".join(_README.read_bytes().decode("utf-8").split())
    assert "A sign-out leaves it in place" in text
    assert "only `agent disconnect` removes it" in text
