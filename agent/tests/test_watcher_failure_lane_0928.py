"""Hermes' own notices about our watcher jobs never reach the chat (2026-09-28).

A person got, out of nowhere: "⚠️ Cron job 'sr-stream-telegram-…' was interrupted —
the gateway is restarting and killed the run before it finished. No result was
produced for this run." Hermes sends that notice — and its script-failed and
timeout alerts — through a job's FAILURE lane: the row's `failure_deliver` when it
has one, which Hermes documents as "the structural opt-out" when it says `local`.
Every watcher row this client writes now carries `failure_deliver: "local"`, rows
armed before get it once on the next arm, and the assistant-only fallback asks the
cronjob tool for it. The messages themselves still follow `deliver: "origin"`.

Pinned by EXECUTION: the real `_prepare_stream_arm` against a temporary jobs store.
The mutants are in .mutants/watcher_failure_lane_0928_mutants.py.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "facade" / "skill" / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_watcher_failure_lane_0928", "sr.py")

_CHAT = {"platform": "telegram", "chat_id": "111"}


def _arm(tmp_path, monkeypatch, *, jobs=None):
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "sr_attention_poll.py").write_bytes(b"# watchdog\n")
    if jobs is not None:
        (tmp_path / "cron").mkdir(exist_ok=True)
        (tmp_path / "cron" / "jobs.json").write_bytes(json.dumps({"jobs": jobs}).encode())
    monkeypatch.setattr(sr, "_scripts_dir", lambda: scripts)
    monkeypatch.setattr(sr, "_runtime_has_croniter", lambda: True)
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", _CHAT["platform"])
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", _CHAT["chat_id"])
    monkeypatch.delenv("HERMES_SESSION_THREAD_ID", raising=False)
    lines, payload, rc = sr._prepare_stream_arm()
    assert rc == 0 and lines == [] and payload["armed"] is True
    data = json.loads((tmp_path / "cron" / "jobs.json").read_bytes().decode("utf-8"))
    return payload, {j["name"]: j for j in data["jobs"]}


def _row(name, **kw):
    """A row as an older client wrote it: already on the schedule the arm wants
    (so the schedule migration moves nothing) and with no failure lane."""
    return {"id": name[-6:], "name": name, "script": "sr_poll_x.py", "no_agent": True,
            "enabled": True, "state": "scheduled",
            "schedule": dict(sr._STREAM_CRON_SCHEDULE), "schedule_display": "* * * * *",
            "next_run_at": "2026-09-28T00:00:00+00:00", "deliver": "origin",
            "origin": dict(_CHAT), **kw}


def test_a_new_watcher_row_sends_hermes_notices_nowhere(tmp_path, monkeypatch):
    """⛔⛔ The chat's watcher and the daily update notice: the failure lane is
    local, the messages still go to the chat that armed them."""
    payload, rows = _arm(tmp_path, monkeypatch)
    for name in (payload["name"], "sr-update-notice"):
        assert rows[name]["failure_deliver"] == "local", name
        assert rows[name]["deliver"] == "origin", name
        assert rows[name]["origin"] == _CHAT, name


def test_rows_armed_before_get_the_lane_once(tmp_path, monkeypatch):
    """⭐ The arm leaves a runnable row untouched, so every watcher already armed
    would have kept posting the notice. Every row of ours gets the lane — once —
    including another chat's and the daily notice's; a job that is not ours does not."""
    slug = sr._origin_slug(_CHAT)
    jobs = [_row(f"sr-stream-{slug}"),
            _row("sr-stream-whatsapp_0123456789"),
            _row("sr-update-notice", script="sr_update_notice.py"),
            _row("morning-briefing")]
    _payload, rows = _arm(tmp_path, monkeypatch, jobs=jobs)
    for name in (f"sr-stream-{slug}", "sr-stream-whatsapp_0123456789", "sr-update-notice"):
        assert rows[name]["failure_deliver"] == "local", name
        assert rows[name]["deliver"] == "origin", name       # the messages are untouched
    assert "failure_deliver" not in rows["morning-briefing"]

    # ONCE: a second arm finds nothing to change and writes nothing
    jobs_file = tmp_path / "cron" / "jobs.json"
    raw = jobs_file.read_bytes()
    lines, _p, rc = sr._prepare_stream_arm()
    assert rc == 0 and lines == []
    assert jobs_file.read_bytes() == raw
    log = (tmp_path / "watcher.log").read_bytes().decode("utf-8")
    assert "failure lane 'local' on 3 row(s)" in log, log


def test_a_lane_somebody_set_is_left_alone(tmp_path, monkeypatch):
    """⛔ Only a row WITHOUT the key changes: a lane set by hand, or by Hermes' own
    cronjob tool, is the person's."""
    slug = sr._origin_slug(_CHAT)
    jobs = [_row(f"sr-stream-{slug}", failure_deliver="telegram:999"),
            _row("sr-update-notice", script="sr_update_notice.py", failure_deliver="origin")]
    _payload, rows = _arm(tmp_path, monkeypatch, jobs=jobs)
    assert rows[f"sr-stream-{slug}"]["failure_deliver"] == "telegram:999"
    assert rows["sr-update-notice"]["failure_deliver"] == "origin"


def test_a_revived_row_gets_the_lane_too(tmp_path, monkeypatch):
    """A paused watcher is revived in place — and carried over with it."""
    slug = sr._origin_slug(_CHAT)
    jobs = [_row(f"sr-stream-{slug}", enabled=False, state="paused")]
    payload, rows = _arm(tmp_path, monkeypatch, jobs=jobs)
    assert rows[payload["name"]]["enabled"] is True
    assert rows[payload["name"]]["failure_deliver"] == "local"


def test_the_fallback_asks_the_cronjob_tool_for_the_lane():
    """⛔ When the direct write cannot run, the assistant creates the rows with its
    cronjob tool — which takes `failure_deliver` — so they must ask for it too."""
    lines = sr._stream_arm_directive_lines("sr_poll_x.py", "sr-stream-x")
    creates = [ln for ln in lines if "cronjob: create" in ln]
    assert len(creates) == 2, lines
    for ln in creates:
        assert 'failure_deliver="local"' in ln, ln
