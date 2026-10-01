"""The approving review of org PR #4 (2026-09-23): items 2-7, each driven
through the code that consumes the fix. Item 1 (the chat assistant's update
waiter) is in agent/tests/test_selfupdate_waiter_path_1001.py.

  2. The narrator's callers no longer cap Gemini below the ceiling thinking
     needs, and an empty MAX_TOKENS answer counts toward the breaker.
  3. A serve process owns its own telemetry spool; a command never keeps a
     worker id it inherited.
  4. NotebookLM: a file the chooser already took is not set on the input too.
  5. An update started with no target version, killed after its install, says
     so and offers Restart.
  6. The phase notice fetches its token on its own thread, not the caller's.
  7. Telemetry: a POST that outlives the flush deadline is not re-spooled until
     it has actually failed, so events it delivered are not sent again.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest
import requests

import research
import telemetry as tm
from conftest import serving_version


# ═════════════════════════════════════════════════════════════════════════════
# 2. the narrator's token ceiling, and the breaker
# ═════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, status: int, body):
        self.status_code = status
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


def _empty(finish: str) -> dict:
    return {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": ""}]}}]}


def _said(text: str) -> dict:
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}


@pytest.fixture
def no_haiku(monkeypatch):
    """No Anthropic key, so a Gemini miss cannot be rescued by the fallback —
    the host the review describes, where narration goes silent."""
    monkeypatch.setattr(research, "resolve_api_key", lambda *a, **k: None)
    monkeypatch.delenv("DG_NARRATOR_USE_HAIKU", raising=False)
    monkeypatch.delenv("DG_NARRATOR_USE_GEMINI", raising=False)
    monkeypatch.delenv("DG_GEMINI_THINKING_BUDGET", raising=False)


def test_the_alert_copy_rewrite_is_answered_with_thinking_on(monkeypatch, no_haiku):
    """Gemini with thinking on spends a small ceiling on reasoning and answers
    empty (finishReason=MAX_TOKENS). The fake answers exactly that below the
    narrator's own 800 default, so the rewrite only lands if its caller stopped
    passing the 220 it used to."""
    caps = []

    def _gemini(url, json=None, timeout=None, **kw):
        cap = json["generationConfig"]["maxOutputTokens"]
        caps.append(cap)
        if cap < 800:
            return _Resp(200, _empty("MAX_TOKENS"))
        return _Resp(200, _said('{"title": "Sharp", "details": "Sharp details."}'))

    monkeypatch.setattr(requests, "post", _gemini)
    monkeypatch.setattr(research, "resolve_gemini_api_key", lambda: "k")
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    out = research._draft_alert_copy("agent_failed", "t", "d", {"agent": "gemini"},
                                     [{"label": "Retry"}])
    assert caps, "the rewrite never asked Gemini — this test measured nothing"
    assert out == ("Sharp", "Sharp details."), (caps, out)


def _narrator_calls(tree):
    """Every call of `_call_text_narrator`, direct or through asyncio.to_thread."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "_call_text_narrator":
            yield node
        elif (isinstance(f, ast.Attribute) and f.attr == "to_thread" and node.args
              and isinstance(node.args[0], ast.Name)
              and node.args[0].id == "_call_text_narrator"):
            yield node


def test_no_narrator_caller_caps_gemini_below_the_default():
    """Per-agent narration and Tier-3 live inside the 700-line narrator loop,
    which nothing in the suite can drive one tick at a time, so their calls are
    read off the parse tree: every caller either leaves the ceiling to the
    default or passes a literal at least that large."""
    default = inspect.signature(research._call_text_narrator).parameters["max_tokens"].default
    assert default >= 800, "the default itself is below what thinking needs"
    tree = ast.parse(Path(research.__file__).read_text(encoding="utf-8"))
    calls = list(_narrator_calls(tree))
    # The phase narrator, Tier-3, per-agent narration and the alert-copy rewrite.
    assert len(calls) >= 4, f"found {len(calls)} narrator calls — the walk is blind"
    low = []
    for call in calls:
        for kw in call.keywords:
            if kw.arg != "max_tokens":
                continue
            ok = isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int) \
                and kw.value.value >= default
            if not ok:
                low.append((call.lineno, ast.unparse(kw.value)))
    assert low == [], f"narrator calls capped below {default}: {low}"


@pytest.fixture
def gemini_transport(monkeypatch):
    state = types.SimpleNamespace(answer=None, posted=0, logged=[])

    def _post(url, json=None, timeout=None, **kw):
        state.posted += 1
        return _Resp(200, state.answer)

    monkeypatch.setattr(requests, "post", _post)
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: state.logged.append(msg))
    monkeypatch.setattr(research, "resolve_api_key", lambda *a, **k: None)
    return state


def _loop_holder() -> dict:
    # The shape `_narrator_loop` creates once per phase.
    return {"gemini_downgrade_logged": False, "last_vendor": "",
            "gemini_consecutive_fail": 0, "gemini_tripped": False}


def _tick(holder):
    return research._call_text_narrator("be brief", "narrate this", gemini_key="k",
                                        use_gemini=True, err_holder=holder)


def test_two_empty_max_tokens_answers_write_gemini_off_for_the_phase(gemini_transport):
    """Each one waited out Gemini's thinking and came back empty, and the next
    tick does the same. Two in a row trip the breaker the way two timeouts do,
    so the third tick does not pay that wait again."""
    gemini_transport.answer = _empty("MAX_TOKENS")
    holder = _loop_holder()
    for _ in range(3):
        _tick(holder)
    assert gemini_transport.posted == 2, (
        f"Gemini was asked {gemini_transport.posted} times — an empty MAX_TOKENS "
        f"answer is not counted toward the breaker")
    assert holder["gemini_tripped"] is True
    trip = [m for m in gemini_transport.logged if "written off for this phase" in m]
    assert len(trip) == 1, gemini_transport.logged
    assert "MAX_TOKENS" in trip[0], "the trip line must say what kind of failure tripped it"


def test_an_empty_stop_answer_is_not_counted(gemini_transport):
    """An empty answer that finished normally came back at once; retrying it
    costs nothing, so it never writes the primary off."""
    gemini_transport.answer = _empty("STOP")
    holder = _loop_holder()
    for _ in range(3):
        _tick(holder)
    assert gemini_transport.posted == 3
    assert holder["gemini_tripped"] is False


# ═════════════════════════════════════════════════════════════════════════════
# 3. the serve entry point owns its telemetry spool
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def main_env(monkeypatch, tmp_path):
    for name in ("_install_stdlib_log_bridge", "_install_crash_log_hook",
                 "_migrate_state_to_home", "_warn_if_restart_pending",
                 "_harden_owner_only_paths", "_migrate_legacy_api_keys",
                 "_write_running_version"):
        monkeypatch.setattr(research, name, lambda *a, **k: None)
    monkeypatch.setattr(research, "_detect_supervised", lambda *a, **k: False)
    monkeypatch.setattr(research, "_SUPERVISOR_ENV_FILE_DEFAULT_PATH",
                        tmp_path / "no-such.env")
    monkeypatch.setattr(research.tm, "flush_in_background", lambda *a, **k: None)
    import atexit
    monkeypatch.setattr(atexit, "register", lambda *a, **k: None)
    # main() stamps these module globals; give them back afterwards.
    monkeypatch.setattr(research, "WORKER_ID", research.WORKER_ID)
    monkeypatch.setattr(research, "_FLEET_MEMBER", research._FLEET_MEMBER)
    monkeypatch.setenv("SR_TELEMETRY", "1")
    monkeypatch.setattr(tm, "_install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(tm, "_build", lambda: "0.1.13")
    # Recorded (and so restored) by monkeypatch whatever main() does to it.
    monkeypatch.setenv("SR_WORKER_ID", "")
    seen = {}

    async def _server(port):
        seen["port"] = port
        seen["worker_env"] = os.environ.get("SR_WORKER_ID")

    monkeypatch.setattr(research, "run_server", _server)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["research.py", *argv])
        research.main()
        return seen
    return run


def _events_in(name: str) -> list:
    path = tm._telemetry_dir() / name
    if not path.exists():
        return []
    return [json.loads(ln)["ev"] for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_a_fleet_worker_records_into_its_own_spool(main_env):
    seen = main_env("--serve", "--worker-id", "3")
    assert seen["worker_env"] == "3"
    assert int(tm.Ev.SERVE_STARTED) in _events_in("pending-w3.jsonl")
    assert _events_in("pending-cli.jsonl") == [], (
        "a serve worker is still writing the shared command spool")


def test_a_standalone_serve_records_into_worker_ones_spool(main_env):
    """The daemon-loop's single worker is started with no --worker-id; it is
    still a serve, and still not a command."""
    seen = main_env("--serve")
    assert seen["worker_env"] == "1"
    assert int(tm.Ev.SERVE_STARTED) in _events_in("pending-w1.jsonl")
    assert _events_in("pending-cli.jsonl") == []


def test_a_command_does_not_keep_a_worker_id_it_inherited(main_env, monkeypatch):
    """The update waiter starts `--restart` with a worker's environment. A
    command that kept SR_WORKER_ID would append to that worker's spool while
    the worker trims it."""
    monkeypatch.setenv("SR_WORKER_ID", "4")
    monkeypatch.setattr(research, "run_commands_help",
                        lambda: tm.tm_emit(tm.Ev.LOGIN_STARTED))
    main_env("--help")
    assert "SR_WORKER_ID" not in os.environ
    assert int(tm.Ev.LOGIN_STARTED) in _events_in("pending-cli.jsonl")
    assert _events_in("pending-w4.jsonl") == []


# ═════════════════════════════════════════════════════════════════════════════
# 4. NotebookLM: one file, one source
# ═════════════════════════════════════════════════════════════════════════════

class _Browser:
    """The real browser's one-entry upload queue."""

    def __init__(self):
        self._upload_queue = []

    def set_upload_file(self, path):
        self._upload_queue = [str(path)]

    def clear_upload_file(self):
        self._upload_queue = []


class _Input:
    def __init__(self, delivered):
        self.delivered = delivered

    async def set_input_files(self, files):
        self.delivered.extend(files)


class _Page:
    """No file input until the Upload control has been pressed; after that the
    input stays in the dialog, which is the case that added a file twice.
    `before_each_await` runs first on every await, which is where a pending
    filechooser handler gets its turn on the real event loop."""

    def __init__(self, delivered, before_each_await):
        self.pressed = False
        self.input = _Input(delivered)
        self.url = "https://notebooklm.google.com/notebook/nb-1001"
        self._before = before_each_await

    async def query_selector(self, sel):
        self._before()
        if sel == 'input[type="file"]' and self.pressed:
            return self.input
        return None


def _upload(monkeypatch, paths, *, chooser_seen: bool, handler: str):
    """Drive `_nlm_dom_add_files` down its chooser path.

    `handler` is when the browser's global filechooser handler takes the armed
    file (pops the queue and sets the file): "next_await" is the real order when
    a chooser opens — Playwright schedules the handler, which runs at the upload's
    next await, after the press has returned; "before_return" is a handler that
    already ran; "none" is no chooser at all. `chooser_seen` is whether the
    press's own chooser wait noticed."""
    delivered: list = []
    browser = _Browser()
    pending = []

    def _handler_turn():
        while pending:
            pending.pop()
            if browser._upload_queue:
                delivered.append(browser._upload_queue.pop(0))

    page = _Page(delivered, _handler_turn)

    async def _click(pg, patterns, *, expect_chooser=False):
        if not expect_chooser:
            return ""                  # "Add source": nothing to press here
        pg.pressed = True
        if handler == "before_return" and browser._upload_queue:
            delivered.append(browser._upload_queue.pop(0))
        elif handler == "next_await":
            pending.append(True)
        return "Upload files|chooser" if chooser_seen else "Upload files"

    async def _on_screen(pg):
        return True

    async def _nap(*a, **k):
        _handler_turn()

    monkeypatch.setattr(research, "_nlm_click_first", _click)
    monkeypatch.setattr(research, "_nlm_upload_control_on_screen", _on_screen)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    fast = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio)
                                    if not k.startswith("__")})
    fast.sleep = _nap
    monkeypatch.setattr(research, "asyncio", fast)
    ok = asyncio.run(research._nlm_dom_add_files(browser, page, paths))
    return ok, delivered


def test_a_file_the_chooser_took_is_not_set_on_the_input_too(monkeypatch):
    """The review's case: the press opened a chooser, the handler sets the file
    at the next await — which, on the old code, was the input lookup — and the
    input left in the dialog then took the same file again."""
    ok, delivered = _upload(monkeypatch, ["/q/chatgpt.md", "/q/claude.md"],
                            chooser_seen=True, handler="next_await")
    assert ok is True
    assert delivered == ["/q/chatgpt.md", "/q/claude.md"], (
        f"a file reached NotebookLM more than once: {delivered}")


def test_an_empty_queue_means_the_handler_already_took_it(monkeypatch):
    """The press's own chooser wait can miss a chooser the global handler still
    answered; the emptied queue is the evidence then."""
    ok, delivered = _upload(monkeypatch, ["/q/gemini.md"],
                            chooser_seen=False, handler="before_return")
    assert ok is True
    assert delivered == ["/q/gemini.md"], delivered


def test_with_no_chooser_the_revealed_input_still_takes_the_file(monkeypatch):
    """⭐ ACCEPT POLARITY. When no chooser opened and the file is still armed,
    the input the press revealed is the way in (the 2026-08-05 fix)."""
    ok, delivered = _upload(monkeypatch, ["/q/gemini.md"],
                            chooser_seen=False, handler="none")
    assert ok is True
    assert delivered == ["/q/gemini.md"], delivered


# ═════════════════════════════════════════════════════════════════════════════
# 5. an update with no target version
# ═════════════════════════════════════════════════════════════════════════════

def _intent(monkeypatch, tmp_path, **over):
    p = tmp_path / "update_intent.json"
    payload = {"action": "upgrade", "waiter_pid": None,
               "at": int(time.time() * 1000) - 120_000,
               "current": "0.1.10", "latest": ""}       # PyPI did not answer
    payload.update(over)
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", p)
    monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "absent.json")


def test_installed_but_not_restarted_with_no_target_offers_restart(tmp_path, monkeypatch):
    """The waiter was killed after pipx installed 0.1.11 and before its restart:
    the new build is on disk, the old one is serving. That is a restart owed,
    not a failure — with or without a version from PyPI."""
    _intent(monkeypatch, tmp_path)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.11")
    serving_version(monkeypatch, "0.1.10")
    st = research._consume_pending_update_result()
    assert st["state"] == "installed", st
    assert st["needsRestart"] is True
    assert st["latest"] == "0.1.11"
    assert "0.1.10" in st["reason"] and "restart" in st["reason"].lower()


def test_installed_and_already_serving_with_no_target_is_done(tmp_path, monkeypatch):
    _intent(monkeypatch, tmp_path)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.11")
    serving_version(monkeypatch, "0.1.11")
    st = research._consume_pending_update_result()
    assert st == {"state": "installed", "current": "0.1.11", "latest": "0.1.11",
                  "needsRestart": False, "reason": ""}


def test_nothing_moved_with_no_target_is_still_a_failure(tmp_path, monkeypatch):
    """⭐ The other half: the disk still holds the build the update started from,
    so nothing was installed and nothing is owed but the truth."""
    _intent(monkeypatch, tmp_path)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
    serving_version(monkeypatch, "0.1.10")
    st = research._consume_pending_update_result()
    assert st["state"] == "failed"
    assert "still on v0.1.10" in st["reason"]


def test_a_source_checkout_label_is_never_a_target(tmp_path, monkeypatch):
    _intent(monkeypatch, tmp_path)
    monkeypatch.setattr(research, "_sr_version", lambda: "(source checkout)")
    serving_version(monkeypatch, "0.1.10")
    st = research._consume_pending_update_result()
    assert st["state"] == "failed", st


# ═════════════════════════════════════════════════════════════════════════════
# 6. the phase notice's token is fetched off the caller's thread
# ═════════════════════════════════════════════════════════════════════════════

UID = "uid-1001"
CHAT = "chat_1755500000000_3"


@pytest.fixture
def notice_world(monkeypatch):
    w = types.SimpleNamespace(token_thread=None, posted=threading.Event(),
                              release=threading.Event(), block=False)

    def token():
        w.token_thread = threading.get_ident()
        if w.block:
            w.release.wait(3)
        return "tok-1"

    def post(url, headers=None, json=None, timeout=None, **kw):
        w.posted.set()
        return types.SimpleNamespace(status_code=200, text='{"delivered": []}')

    monkeypatch.setattr(research, "_fresh_user_mode_id_token", token)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return w


def test_the_phase_notice_fetches_its_token_on_its_own_thread(notice_world):
    """It is called from emit_event on the worker's event loop. A token refresh
    there is a network round-trip at every phase boundary."""
    assert research._post_fe_phase_notice(UID, CHAT, 2, "phase_complete", 7) is True
    assert notice_world.posted.wait(5), "the notice was never sent"
    assert notice_world.token_thread is not None
    assert notice_world.token_thread != threading.get_ident(), (
        "the token was refreshed on the caller's thread")


def test_a_slow_token_refresh_does_not_hold_the_caller(notice_world):
    notice_world.block = True
    started = time.monotonic()
    try:
        research._post_fe_phase_notice(UID, CHAT, 2, "phase_complete", 7)
        took = time.monotonic() - started
    finally:
        notice_world.release.set()
    assert took < 1.0, f"the caller waited {took:.1f}s for a token refresh"
    assert notice_world.posted.wait(5)


# ═════════════════════════════════════════════════════════════════════════════
# 7. telemetry: a POST that outlives the deadline is settled on its outcome
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def spool(monkeypatch):
    monkeypatch.setenv("SR_TELEMETRY", "1")
    monkeypatch.setenv("SR_WORKER_ID", "")
    monkeypatch.setattr(tm, "_install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(tm, "_build", lambda: "0.1.13")


def _late_post(answer: bool):
    """A POST that is still out at the flush deadline and answers `answer` once
    `gate` is set. `done` is set after the flush machinery has settled it."""
    gate, sent = threading.Event(), []

    def post(batch):
        sent.append([r["seq"] for r in batch])
        gate.wait(10)
        return answer
    return post, gate, sent


def _claimed_files():
    return sorted(tm._telemetry_dir().glob("pending-*.sending.*.jsonl"))


def _wait_until(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _live_spool_seqs():
    path = tm.spool_path()
    if not path.exists():
        return []
    return [json.loads(ln)["seq"] for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def _late_then_flushed(answer: bool):
    """One event goes out on a POST still out at the deadline; a second event
    arrives and this process flushes while that POST is out; the POST then
    answers `answer`; one more flush. Returns (first, newer, delivered while the
    late POST was out, every delivery that landed, in order)."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    first = _live_spool_seqs()
    post, gate, sent = _late_post(answer)
    assert tm.flush(post=post, deadline_sec=0.2) == 0
    assert _live_spool_seqs() == [], "re-spooled while the POST could still land"

    tm.tm_emit(tm.Ev.DOCTOR_RUN, count=1)
    newer = [s for s in _live_spool_seqs() if s not in first]
    landed: list = []
    tm.flush(post=lambda b: landed.extend(r["seq"] for r in b) or True, deadline_sec=2)
    during = list(landed)

    gate.set()
    assert _wait_until(lambda: not _claimed_files()), "the late POST was never settled"
    if answer:
        landed[:0] = sent[0]          # the late POST did land
    tm.flush(post=lambda b: landed.extend(r["seq"] for r in b) or True, deadline_sec=2)
    # Everything delivered is also SETTLED: nothing left claimed, nothing owed.
    assert _claimed_files() == [] and _live_spool_seqs() == [], (
        f"left behind after delivery: claimed={_claimed_files()} "
        f"spool={_live_spool_seqs()}")
    return first, newer, during, landed


def test_a_post_that_lands_after_the_deadline_is_not_sent_again(spool):
    """The review's case: the flush stops waiting at its deadline, the POST
    lands anyway, and the old code had already put the events back — so the
    next flush sent them again inside a different batch, which the sink's
    batch-hash de-duplication cannot catch."""
    first, newer, during, landed = _late_then_flushed(True)
    assert first and newer
    assert not set(first) & set(during), (
        f"events whose POST was still out were sent again: {during}")
    assert sorted(landed) == sorted(first + newer), (
        f"each event must land exactly once: {landed}")


def test_a_post_that_fails_after_the_deadline_loses_nothing(spool):
    """⭐ Not re-spooling at the deadline must not become losing. ⛔ Found by
    mutation: the claimed name is per process, so a flush while the POST was out
    renamed the live spool over the late POST's file — and when that POST then
    failed, its events were gone. Once it really fails they are back in the live
    spool, ahead of the newer one, and both go out once."""
    first, newer, during, landed = _late_then_flushed(False)
    assert first and newer
    assert not set(first) & set(during), during
    assert sorted(landed) == sorted(first + newer), (
        f"each event must land exactly once: {landed}")
