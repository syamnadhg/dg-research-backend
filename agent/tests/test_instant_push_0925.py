"""Instant delivery through Hermes's own CLI, and the news peek that feeds it (2026-09-25).

⛔⛔ THE DELAY THIS REMOVES. Hermes v0.21.3 queues every scheduled message for a
housekeeping loop that sends about once a minute (up to ~6 min under load), and the
watcher's "every 1m" interval runs every ~2 min. A true "✓ Signed in" reached the
chat 19 s after the person had logged out on 2026-09-24.

⭐ THE DECISION (owner, 2026-09-25): WITHOUT changing Hermes, the bridge runs
`hermes cron run <that chat's sr-stream job>` the moment it has news; run outside
the gateway, Hermes runs the job in that process and sends directly. These tests pin
the rules that make that safe: found by origin, READ-ONLY; off the caller's thread;
one run in flight per job; re-checked immediately before every spawn; bounded
retries; a no-op without Hermes; every step logged. Nothing here ever runs a real
`hermes` — the runner and spawner are injected, and `push` is armed only by
`serve()`.
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge, prefs, push

TG = {"platform": "telegram", "chat_id": "111"}
WA = {"platform": "whatsapp", "chat_id": "222"}


def _jobs_file(home: Path, jobs: list) -> Path:
    (home / "cron").mkdir(parents=True, exist_ok=True)
    f = home / "cron" / "jobs.json"
    f.write_bytes(json.dumps({"jobs": jobs}).encode("utf-8"))
    return f


def _job(jid, name, origin, **kw):
    return {"id": jid, "name": name, "script": f"sr_poll_{jid}.py", "origin": origin,
            "enabled": True, "state": "scheduled", **kw}


class _Runs:
    """A fake `hermes cron run`: records calls, answers from a script."""

    def __init__(self, answers=None):
        self.calls: list = []
        self.answers = list(answers or [])

    def __call__(self, cli, home, job_id, timeout):
        self.calls.append(job_id)
        if self.answers:
            return self.answers.pop(0)
        return ("sent", "Ran now: succeeded")


def _pusher(runs, *, sleeps=None, why=None, home=None):
    p = push.Pusher(runner=runs, sleeper=(sleeps.append if sleeps is not None else lambda s: None),
                    spawner=lambda target, *a: target(*a),
                    home=lambda: home, cli=lambda: "/abs/hermes",
                    reason_unavailable=lambda: why)
    p.armed = True
    return p


# ── finding the job: by origin, read-only ─────────────────────────────────────

def test_the_job_is_found_by_its_origin_and_jobs_json_is_never_written(tmp_path):
    f = _jobs_file(tmp_path, [
        _job("aaa111", "sr-stream-telegram_x", TG),
        _job("bbb222", "sr-stream-whatsapp_y", WA),
        _job("ccc333", "sr-stream-telegram_z", {"platform": "Telegram", "chat_id": "111"},
             enabled=False),                                     # disabled
        {"id": "ddd444", "name": "daily-digest", "script": "digest.py", "origin": TG},
        _job("eee555", "sr-stream-telegram_w", {**TG, "thread_id": "9"}, state="paused"),
    ])
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    jobs = push.watcher_jobs(tmp_path, TG)
    assert [j["id"] for j in jobs] == ["aaa111"]
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before, "READ-ONLY"


def test_an_account_wide_note_runs_every_watcher_on_this_computer(tmp_path):
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG), _job("bbb222", "sr-stream-b", WA),
                          {"id": "x", "name": "sr-stream", "script": "sr_attention_poll.py",
                           "origin": None}])
    assert sorted(j["id"] for j in push.watcher_jobs(tmp_path, None)) == ["aaa111", "bbb222", "x"]


def test_the_platform_is_case_folded_like_the_bridges_own_gate(tmp_path):
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", {"platform": "Telegram", "chat_id": "111"})])
    assert [j["id"] for j in push.watcher_jobs(tmp_path, TG)] == ["aaa111"]


def test_a_missing_or_broken_store_finds_nothing(tmp_path):
    assert push.watcher_jobs(tmp_path, TG) == []
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_bytes(b"{not json")
    assert push.watcher_jobs(tmp_path, TG) == []


def test_the_slug_is_the_same_one_sr_py_names_the_job_by():
    import importlib.util
    scripts = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
    spec = importlib.util.spec_from_file_location("sr_slug_0925", scripts / "sr.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    for o in (TG, {**TG, "thread_id": "7"}, {"platform": "Telegram", "chat_id": "-100"}):
        assert push.origin_slug(o) == sr._origin_slug(o)


# ── running it ────────────────────────────────────────────────────────────────

def test_a_request_runs_the_chats_job_through_the_cli(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="facade")
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG), _job("bbb222", "sr-stream-b", WA)])
    runs = _Runs()
    assert _pusher(runs, home=tmp_path).request(TG, reason="signed-in") is True
    assert runs.calls == ["aaa111"]
    # ⛔ every step leaves a line: trigger + job ids, spawn, result line, duration
    assert "push signed-in → telegram_" in caplog.text and "aaa111" in caplog.text
    assert "running `hermes cron run` (attempt 1)" in caplog.text
    assert "sent in" in caplog.text and "Ran now: succeeded" in caplog.text


def test_it_is_a_silent_no_op_without_hermes(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="facade")
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    runs = _Runs()
    p = _pusher(runs, home=tmp_path, why="the chat runtime is openclaw, not Hermes")
    p.request(TG, reason="signed-in")
    assert runs.calls == []
    assert "not run" in caplog.text


def test_the_real_availability_check_needs_the_hermes_runtime_and_its_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(push, "hermes_cli", lambda: "/abs/hermes")
    monkeypatch.setattr(push, "hermes_home", lambda: tmp_path)
    assert "not recorded" in push.unavailable_reason()          # no runtime recorded
    prefs.set_runtime("openclaw")
    assert "openclaw" in push.unavailable_reason()
    prefs.set_runtime("hermes")
    assert push.unavailable_reason() is None
    monkeypatch.setattr(push, "hermes_cli", lambda: None)
    assert "CLI" in push.unavailable_reason()
    monkeypatch.setenv("DG_AGENT_PUSH", "0")
    assert "switched off" in push.unavailable_reason()


def test_not_armed_is_a_no_op():
    """⛔ `serve()` arms it; nothing else may. A handler-level test can therefore
    never reach a real Hermes on the machine running the suite."""
    runs = _Runs()
    p = push.Pusher(runner=runs, spawner=lambda t, *a: t(*a))
    assert p.request(TG, reason="signed-in") is False
    assert runs.calls == []
    assert push.PUSHER.armed is False
    assert push.has_target(TG) is False


def test_the_session_is_re_checked_immediately_before_the_spawn(tmp_path, caplog):
    """⛔⛔ THE RULE THIS WHOLE UNIT EXISTS UNDER: nothing false or stale may be sent.
    The person logged out between the event and the run — nothing is run."""
    caplog.set_level(logging.INFO, logger="facade")
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    runs = _Runs()
    _pusher(runs, home=tmp_path).request(TG, reason="signed-in", still_valid=lambda: False)
    assert runs.calls == []
    assert "skipped — no longer current" in caplog.text


def test_a_re_check_that_cannot_answer_is_a_no(tmp_path, caplog):
    """⛔ A PREDICATE THAT RAISES IS "NO LONGER CURRENT", NEVER "STILL TRUE". The
    re-check reads the live session and prefs.json; a read that fails mid-logout
    (the Windows read/replace collision, a torn file) cannot vouch for the news, and
    a watcher run on a guess is how something stale gets said. Found by mutation
    (2026-09-25): `_still` could answer True on an exception and no test noticed."""
    caplog.set_level(logging.DEBUG, logger="facade")
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    runs = _Runs()

    def cannot_tell():
        raise PermissionError("prefs.json is being replaced")

    _pusher(runs, home=tmp_path).request(TG, reason="signed-in", still_valid=cannot_tell)
    assert runs.calls == [], "nothing is run on a check that could not answer"
    assert "push re-check raised PermissionError" in caplog.text
    assert "skipped — no longer current" in caplog.text


def test_a_busy_job_is_retried_on_a_bounded_ladder_re_checking_each_time(tmp_path):
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    runs = _Runs(answers=[("busy", "already being fired")] * 10)
    sleeps: list = []
    _pusher(runs, sleeps=sleeps, home=tmp_path).request(TG, reason="signed-in")
    assert len(runs.calls) == 1 + len(push._RETRY_DELAYS), "bounded"
    assert sleeps == list(push._RETRY_DELAYS)
    # …and the re-check runs before EVERY retry: flip it after the first attempt.
    runs2 = _Runs(answers=[("busy", "already being fired")] * 10)
    live = [True]

    def still():
        ok = live[0]
        live[0] = False
        return ok

    _pusher(runs2, home=tmp_path).request(TG, reason="signed-in", still_valid=still)
    assert runs2.calls == ["aaa111"]


def test_a_note_the_gateways_tick_took_during_a_busy_run_is_logged_as_queued(tmp_path, caplog):
    """⛔ THE RESIDUAL, NAMED IN THE LOG (2026-09-25). The gateway's own tick held
    the job, its run took the note first, and that copy went through Hermes's
    queue — late. The log used to call that "no longer current (signed out, or
    already told)", indistinguishable from a logout."""
    caplog.set_level(logging.INFO, logger="facade")
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    runs = _Runs(answers=[("busy", "already being fired")] * 10)
    live = [True]

    def still():
        ok = live[0]
        live[0] = False
        return ok

    _pusher(runs, home=tmp_path).request(TG, reason="signed-in", still_valid=still)
    assert "most likely took it: that copy goes through Hermes's queue" in caplog.text
    caplog.clear()
    _pusher(_Runs(), home=tmp_path).request(TG, reason="signed-in",
                                            still_valid=lambda: False)
    assert "Hermes's queue" not in caplog.text, "no run yet: nothing to blame on the tick"


def test_only_busy_is_retried(tmp_path):
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    for outcome in ("sent", "failed", "missing", "error", "timeout", "unknown"):
        runs = _Runs(answers=[(outcome, "x")])
        _pusher(runs, home=tmp_path).request(TG, reason="signed-in")
        assert runs.calls == ["aaa111"], outcome


def test_requests_during_a_run_coalesce_into_ONE_follow_up_run(tmp_path, caplog):
    """⛔ ONE RUN IN FLIGHT PER JOB — two runs of one watcher would race each
    other's de-dup state. Three requests while one is running → one more run."""
    caplog.set_level(logging.INFO, logger="facade")
    _jobs_file(tmp_path, [_job("aaa111", "sr-stream-a", TG)])
    gate = threading.Event()
    started = threading.Event()
    calls: list = []

    def runner(cli, home, job_id, timeout):
        calls.append(job_id)
        if len(calls) == 1:
            started.set()
            gate.wait(10)
        return ("sent", "Ran now: succeeded")

    p = push.Pusher(runner=runner, home=lambda: tmp_path, cli=lambda: "/abs/hermes",
                    reason_unavailable=lambda: None, sleeper=lambda s: None)
    p.armed = True
    p.request(TG, reason="signed-in")
    assert started.wait(10)
    for r in ("device-answered", "run-completed", "support-logs"):
        p.request(TG, reason=r)
    deadline = time.time() + 10
    while time.time() < deadline and "folded into one" not in caplog.text:
        time.sleep(0.02)
    time.sleep(0.2)                          # let every fan-out thread reach _enqueue
    gate.set()
    deadline = time.time() + 10
    while time.time() < deadline and (p._inflight or len(calls) < 2):
        time.sleep(0.02)
    assert calls == ["aaa111", "aaa111"], calls
    assert not p._inflight


def test_classify_reads_the_clis_own_words():
    assert push.classify(0, "…\r\nRan now: succeeded\r\n") == ("sent", "Ran now: succeeded")
    assert push.classify(0, "Ran now: failed (script error)")[0] == "failed"
    assert push.classify(1, "Job aaa111 is already being fired")[0] == "busy"
    assert push.classify(1, "No such job: aaa111")[0] == "missing"
    assert push.classify(2, "Traceback …\nboom")[0] == "error"
    assert push.classify(0, "")[0] == "unknown"
    # ⛔ an email in the CLI's output never reaches bridge.log whole
    assert "erin@" not in push.classify(0, "Ran now: succeeded for erin@example.com")[1]


def test_the_cli_is_run_by_absolute_path_with_bytes_and_this_hermes_home(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, stdout="✓ Ran now: succeeded\r\n".encode("utf-8"))

    monkeypatch.setattr(push.subprocess, "run", fake_run)
    out = push._run_cli("/abs/hermes", tmp_path, "aaa111", 90.0)
    assert out[0] == "sent"
    assert seen["argv"] == ["/abs/hermes", "cron", "run", "aaa111"]
    assert seen["kw"]["env"]["HERMES_HOME"] == str(tmp_path)
    assert seen["kw"]["stdin"] is subprocess.DEVNULL
    assert "text" not in seen["kw"] and "encoding" not in seen["kw"], "bytes, decoded here"
    assert seen["kw"]["timeout"] == 90.0

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 90)

    monkeypatch.setattr(push.subprocess, "run", slow)
    assert push._run_cli("/abs/hermes", tmp_path, "aaa111", 90.0)[0] == "timeout"


def test_the_cli_is_found_in_local_bin_when_path_does_not_have_it(monkeypatch, tmp_path):
    monkeypatch.setattr(push.shutil, "which", lambda name: None)
    monkeypatch.setattr(push.Path, "home", classmethod(lambda cls: tmp_path))
    assert push.hermes_cli() is None
    b = tmp_path / ".local" / "bin"
    b.mkdir(parents=True)
    exe = b / ("hermes.exe" if os.name == "nt" else "hermes")
    exe.write_bytes(b"#!/bin/sh\n")
    exe.chmod(0o755)
    assert push.hermes_cli() == str(exe)


def test_hermes_home_is_the_candidate_that_holds_the_cron_store(monkeypatch, tmp_path):
    env_home, rec_base, default_base = tmp_path / "env", tmp_path / "rec", tmp_path / "def"
    monkeypatch.setattr(push.Path, "home", classmethod(lambda cls: default_base))
    monkeypatch.setenv("HERMES_HOME", str(env_home))
    prefs.set_runtime("hermes", home=str(rec_base), location="local")
    assert push.hermes_home() is None
    _jobs_file(default_base / ".hermes", [])
    assert push.hermes_home() == default_base / ".hermes"
    _jobs_file(rec_base / ".hermes", [])
    assert push.hermes_home() == rec_base / ".hermes"
    _jobs_file(env_home, [])
    assert push.hermes_home() == env_home, "$HERMES_HOME first, as sr.py does"


# ── the bridge's triggers ─────────────────────────────────────────────────────

class _Rec:
    def __init__(self):
        self.calls: list = []

    def __call__(self, origin, *, reason, still_valid=None):
        self.calls.append((origin, reason, still_valid))
        return True


def _sess(cap=7_000):
    return SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok",
                           connected_at_ms=cap, logout=lambda: None)


def test_a_captured_sign_in_pushes_its_chat_and_the_push_re_checks(monkeypatch):
    """⭐ The capture parks the note and runs the chat's watcher at once. The
    predicate the push re-checks answers False once the note is gone (a chat reply
    already said it) or the person logged out."""
    rec = _Rec()
    monkeypatch.setattr(bridge.push, "request", rec)
    monkeypatch.setattr(bridge, "_write_agent_session_connected", lambda *a, **k: None)
    monkeypatch.setenv("DG_AGENT_AUTOSTART", "0")
    sess = _sess()
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda tok: {"status": bridge.devicelogin.APPROVED, "customToken": "CT"})
    monkeypatch.setattr(bridge.AccountSession, "from_custom_token",
                        classmethod(lambda cls, tok, **k: sess))
    state = bridge.BridgeState()
    flow = bridge.RemoteFlow(poll_token="PT", code="AB", verify_url="u", expires_at=9e12)
    flow.origin = dict(TG)
    state.set_remote(flow)
    with state.remote_lock:
        bridge._advance_remote_flow(state)
    assert len(rec.calls) == 1
    origin, reason, valid = rec.calls[0]
    assert origin == TG and reason == "signed-in"
    assert valid() is True
    state.take_signed_in("u1", sess=sess)          # somebody told them
    assert valid() is False
    state.set_signed_in({"ts": 7_000, "uid": "u1", "origin": TG}, sess=sess)
    assert valid() is True
    bridge._self_logout(state, sess)
    assert valid() is False


def test_the_auto_start_worker_pushes_only_what_it_parked(monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(bridge.push, "request", rec)
    monkeypatch.setattr(bridge, "_run_autostart",
                        lambda s, t, o: {"autoStarted": True, "runId": "r1",
                                         "deviceName": "Mac", "topic": t})
    state = bridge.BridgeState()
    sess = _sess()
    state.set_session(sess)
    base = {"ts": 7_000, "email": "e@x.y", "uid": "u1", "origin": TG}
    bridge._autostart_worker(state, sess, "EVs", TG, base)
    assert [c[1] for c in rec.calls] == ["signed-in"]
    # a session that ended during the worker's Firestore I/O parks nothing, pushes nothing
    rec.calls.clear()
    other = _sess()
    state.set_session(other)
    bridge._autostart_worker(state, sess, "EVs", TG, base)
    assert rec.calls == []


def test_a_put_back_never_pushes(monkeypatch):
    """Only a FRESH park is news; a note handed back to its own chat is not."""
    import threading as _t
    from http.server import ThreadingHTTPServer
    import requests

    class _FS:
        def __init__(self, _t):
            pass

        def list_researches(self, uid, page_size=20, **k):
            return []

    rec = _Rec()
    monkeypatch.setattr(bridge.push, "request", rec)
    monkeypatch.setattr(bridge, "FirestoreRest", _FS)
    state = bridge.BridgeState()
    state.set_session(_sess())
    state.set_signed_in({"ts": 7_000, "uid": "u1", "origin": TG})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    _t.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        requests.get(f"http://127.0.0.1:{httpd.server_address[1]}"
                     "/updates?via=agent&watchdog=1&platform=telegram&chat=999", timeout=10)
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert rec.calls == []
    assert state.peek_signed_in("u1") is not None


# ── the news peek ─────────────────────────────────────────────────────────────

class _PeekFS:
    docs: dict = {}
    bundles: dict = {}
    reads = 0

    def __init__(self, _tok):
        pass

    def get_research(self, uid, rid):
        _PeekFS.reads += 1
        return _PeekFS.docs.get(rid)

    def get_log_bundle(self, uid, code):
        _PeekFS.reads += 1
        return _PeekFS.bundles.get(code)


@pytest.fixture()
def peek_env(monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(bridge.push, "request", rec)
    monkeypatch.setattr(bridge.push, "available", lambda: True)
    monkeypatch.setattr(bridge.push, "has_target", lambda origin: True)
    monkeypatch.setattr(bridge.push.PUSHER, "armed", True)
    monkeypatch.setattr(bridge, "FirestoreRest", _PeekFS)
    _PeekFS.docs, _PeekFS.bundles, _PeekFS.reads = {}, {}, 0
    bridge._forget_runs()
    bridge._DEVICE_ASK_CURSOR.clear()
    state = bridge.BridgeState()
    sess = _sess()
    state.set_session(sess)
    yield SimpleNamespace(rec=rec, state=state, sess=sess, memo=bridge._peek_memo())
    bridge._forget_runs()


def test_the_peek_costs_nothing_without_instant_delivery(monkeypatch, peek_env):
    """⛔⛔ NO FIRESTORE, NO WEB CALL unless a push could deliver the news."""
    monkeypatch.setattr(bridge.push, "available", lambda: False)
    bridge._watch_run("u1", "r1", TG)
    prefs.set_device_ask({"deviceId": "d1", "origin": TG, "at": time.time()}, "u1")
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert _PeekFS.reads == 0 and bridge._fe_calls == []
    assert peek_env.rec.calls == []


def test_the_peek_pushes_when_a_watched_run_completes_and_only_once(peek_env):
    bridge._watch_run("u1", "r1", TG)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "ongoing"}
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert peek_env.rec.calls == []
    _PeekFS.docs["r1"] = {"id": "r1", "status": "completed"}
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [(c[0], c[1]) for c in peek_env.rec.calls] == [(TG, "run-completed")]
    assert peek_env.rec.calls[0][2]() is True        # re-check: still signed in
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert len(peek_env.rec.calls) == 1, "unwatched once announced"


def test_the_peek_pushes_when_a_run_starts_needing_the_person(peek_env):
    bridge._watch_run("u1", "r1", TG)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "errored"}
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["run-needs-you"]
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert len(peek_env.rec.calls) == 1, "one push per transition, not per peek"


def test_the_watchers_own_read_moves_the_watch_so_nothing_is_pushed_twice(peek_env):
    """⛔ If the watcher's tick already SAW the completion, a push would only
    re-run a watcher that has nothing new to say."""
    bridge._watch_run("u1", "r1", TG)
    bridge._note_run_seen("u1", {"id": "r1", "chatOrigin": TG}, "completed", False,
                          watchdog=True)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "completed"}
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert peek_env.rec.calls == []


def test_another_readers_glimpse_does_not_move_the_watch(peek_env):
    bridge._watch_run("u1", "r1", TG)
    bridge._note_run_seen("u1", {"id": "r1", "chatOrigin": TG}, "completed", False,
                          watchdog=False)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "completed"}
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["run-completed"]


def test_a_run_that_stops_needing_reads_costs_a_bounded_number_of_reads(peek_env):
    """⛔⛔ AN ERRORED RUN WAS RE-READ EVERY 30 s FOREVER after its one push — one
    Firestore read per pass for as long as the bridge ran. It is not in flight, so
    nothing happens to it until the person acts; the peek stops reading it."""
    bridge._watch_run("u1", "r1", TG)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "errored"}
    for _ in range(100):
        peek_env.memo["runs_at"] = -1e9
        bridge._peek_once(peek_env.state, peek_env.memo)
    assert _PeekFS.reads == 1, _PeekFS.reads
    assert [c[1] for c in peek_env.rec.calls] == ["run-needs-you"]
    assert "r1" not in bridge._RUN_WATCH


@pytest.mark.parametrize("status", ["errored", "stopped_by_watchdog", "paused",
                                    "paused_backend_restart", "paused_backend_restart_failed",
                                    "stopped", "completed"])
def test_the_watchers_read_never_starts_watching_a_run_not_in_flight(peek_env, status):
    """⛔ The watcher lists the chat's newest twenty runs. Old errored / paused ones
    among them must not become a Firestore read every 30 s."""
    needs = status in bridge._ATTENTION_STATUSES
    for watchdog in (True, False):
        bridge._note_run_seen("u1", {"id": "old", "chatOrigin": TG}, status, needs,
                              watchdog=watchdog, akey="a")
        assert "old" not in bridge._RUN_WATCH


def test_the_watchers_read_of_a_run_in_flight_still_starts_the_watch(peek_env):
    bridge._note_run_seen("u1", {"id": "r1", "chatOrigin": TG}, "ongoing", False,
                          watchdog=True, akey="\x1f")
    assert bridge._RUN_WATCH["r1"]["status"] == "ongoing"


def test_a_stopped_run_is_pushed_once(peek_env):
    """⭐ The watcher's "⏹ stopped" line — a stop from the web app included — is
    news too; it used to wait for the watcher's own tick and Hermes's queue."""
    bridge._watch_run("u1", "r1", TG)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "stopped"}
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["run-ended"]
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert len(peek_env.rec.calls) == 1 and _PeekFS.reads == 1


def test_a_run_the_person_paused_is_not_pushed_and_not_read_again(peek_env):
    """The watcher treats a pause as still going (its `_ACTIVE`) and says nothing."""
    bridge._watch_run("u1", "r1", TG)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "paused"}
    bridge._peek_once(peek_env.state, peek_env.memo)
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert peek_env.rec.calls == [] and _PeekFS.reads == 1


def test_a_second_different_blocker_on_a_flagged_run_is_pushed(peek_env):
    """⭐ The watcher re-announces when the card changes (`_attention_key`), so a
    second card on a run still waiting on the person is news; the SAME card twice
    is not."""
    bridge._watch_run("u1", "r1", TG)
    _PeekFS.docs["r1"] = {"id": "r1", "status": "ongoing",
                          "pendingDecision": {"title": "Sign in to Claude"}}
    bridge._peek_once(peek_env.state, peek_env.memo)
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["run-needs-you"], "same card: once"
    _PeekFS.docs["r1"] = {"id": "r1", "status": "ongoing",
                          "pendingDecision": {"title": "Verify you are human"}}
    peek_env.memo["runs_at"] = -1e9
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["run-needs-you", "run-needs-you"]
    assert bridge._RUN_WATCH["r1"]["needs"] is True, "still in flight → still read"


def test_a_run_the_bridge_starts_is_watched_from_its_one_write_path(monkeypatch):
    class _EnqFS:
        def __init__(self, _t=None):
            pass

        def upsert_research(self, *a, **k):
            return None

        def enqueue_start(self, *a, **k):
            return "q1"

        def seed_chat_messages(self, *a, **k):
            return None

    monkeypatch.setattr(bridge, "_spawn", lambda *a, **k: None)
    bridge._forget_runs()
    rid, _q = bridge._enqueue_research_run(_EnqFS(), _sess(), topic="EVs", device_id="d1",
                                           cfg={}, origin=TG)
    assert bridge._RUN_WATCH[rid]["origin"] == TG
    bridge._forget_runs()


def test_logout_stops_the_watch():
    bridge._watch_run("u1", "r1", TG)
    state = bridge.BridgeState()
    sess = _sess()
    state.set_session(sess)
    bridge._self_logout(state, sess)
    assert "r1" not in bridge._RUN_WATCH


def test_the_peek_pushes_the_approval_and_opens_the_watchers_next_look(monkeypatch, peek_env):
    prefs.set_device_ask({"deviceId": "d1", "origin": TG, "at": time.time()}, "u1")
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, path, params=None, **k: (200, {"outgoing": [{"deviceId": "d1"}]}))
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert peek_env.rec.calls == [], "still unanswered"
    bridge._DEVICE_ASK_CURSOR.clear()
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, path, params=None, **k: (200, {"outgoing": []}))
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [(c[0], c[1]) for c in peek_env.rec.calls] == [(TG, "device-answered")]
    assert "d1" not in bridge._DEVICE_ASK_CURSOR, "the watcher's own check is due at once"
    assert peek_env.rec.calls[0][2]() is True
    prefs.clear_device_ask()
    assert peek_env.rec.calls[0][2]() is False, "delivered → nothing left to push for"


def test_the_peek_pushes_a_landed_support_bundle_and_the_late_notice(peek_env):
    now = time.time()
    bridge._remember_log_request("AAAA1111", {"uid": "u1", "deviceId": "d1", "at": now,
                                              "origin": TG, "announced": False})
    bridge._remember_log_request("BBBB2222", {"uid": "u1", "deviceId": "d1",
                                              "at": now - bridge._BUNDLE_WATCH_SECONDS - 5,
                                              "origin": TG, "announced": False})
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["support-logs"], "the late one only"
    _PeekFS.bundles["AAAA1111"] = {"status": "done"}
    peek_env.memo["logs_checked"].clear()
    bridge._peek_once(peek_env.state, peek_env.memo)
    assert [c[1] for c in peek_env.rec.calls] == ["support-logs", "support-logs"]
    assert peek_env.rec.calls[1][2]() is True
    prefs.update_log_request("AAAA1111", "u1", {"announced": True})
    assert peek_env.rec.calls[1][2]() is False
