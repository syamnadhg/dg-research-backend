"""The streaming watchdog (sr_attention_poll.py) — the de-dup core.

Loaded standalone (as the cron `no_agent` runner would), exercising compute()'s
transition logic: post a NEW link / blocker / completion once, then stay silent.
"""

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr_attention_poll.py"
    spec = importlib.util.spec_from_file_location("sr_stream_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


poll = _load()


def test_first_link_posts_then_dedups():
    runs = [{"runId": "r1", "title": "EV market", "status": "ongoing",
             "links": [{"kind": "brief", "label": "Brief", "url": "u-b"}]}]
    msgs, state = poll.compute(runs, {})
    assert any("Brief" in m and "u-b" in m for m in msgs)
    msgs2, _ = poll.compute(runs, state)  # nothing changed
    assert msgs2 == []  # silent


def test_only_the_new_link_posts_incrementally():
    _, state = poll.compute(
        [{"runId": "r1", "title": "EV", "status": "ongoing",
          "links": [{"kind": "brief", "url": "u-b"}]}], {})
    runs = [{"runId": "r1", "title": "EV", "status": "ongoing",
             "links": [{"kind": "brief", "url": "u-b"}, {"kind": "chatgpt", "url": "u-c"}]}]
    msgs, _ = poll.compute(runs, state)
    assert len(msgs) == 1 and "u-c" in msgs[0]  # only the NEW kind, not the old


def test_needs_attention_posts_once_then_on_reason_change():
    runs = [{"runId": "r1", "title": "EV", "status": "ongoing", "links": [],
             "needsAttention": True, "attention": "Sign in to ChatGPT"}]
    msgs, state = poll.compute(runs, {})
    assert any("needs you" in m and "Sign in to ChatGPT" in m and "retry" in m for m in msgs)
    msgs2, state2 = poll.compute(runs, state)  # same blocker
    assert msgs2 == []
    runs[0]["attention"] = "Solve the verification check"  # reason changes
    msgs3, _ = poll.compute(runs, state2)
    assert any("Solve the verification check" in m for m in msgs3)


def test_terminal_announced_once():
    runs = [{"runId": "r1", "title": "EV", "status": "completed", "links": []}]
    msgs, state = poll.compute(runs, {})
    assert any("finished" in m for m in msgs)
    msgs2, _ = poll.compute(runs, state)
    assert msgs2 == []  # announced exactly once


def test_error_and_watchdog_point_at_retry():
    err, _ = poll.compute([{"runId": "r1", "title": "EV", "status": "error", "links": []}], {})
    assert any("hit an error" in m and "retry" in m for m in err)
    wd, _ = poll.compute([{"runId": "r2", "title": "X", "status": "stopped_by_watchdog", "links": []}], {})
    assert any("retry" in m for m in wd)


def test_user_stop_is_not_an_error():
    msgs, _ = poll.compute([{"runId": "r1", "title": "EV", "status": "stopped", "links": []}], {})
    assert any("stopped" in m and "kept" in m for m in msgs)
    assert not any("error" in m for m in msgs)


def test_runs_without_id_are_ignored():
    msgs, state = poll.compute([{"title": "no id", "status": "ongoing", "links": []}], {})
    assert msgs == [] and state == {}


# ── baseline (the first tick after arming): silent on history, loud on live ──

def test_baseline_first_tick_is_silent_on_history():
    # Arming must NOT replay recent history (old links + finish notices) into
    # the chat — up to 20 runs' worth would flood it.
    runs = [
        {"runId": "old", "title": "Old run", "status": "completed",
         "links": [{"kind": "brief", "url": "u-b"}, {"kind": "doc", "url": "u-d"}]},
        {"runId": "live", "title": "Live run", "status": "ongoing",
         "links": [{"kind": "brief", "url": "u-b2"}]},
    ]
    msgs, state = poll.compute(runs, {}, baseline=True)
    assert msgs == []  # fully silent
    # …but the delta machinery still works from here: a NEW link posts.
    runs[1]["links"].append({"kind": "chatgpt", "url": "u-c"})
    msgs2, state2 = poll.compute(runs, state)
    assert len(msgs2) == 1 and "u-c" in msgs2[0]
    # …and the live run's eventual completion IS announced (baseline must not
    # pre-mark an ongoing run as already-announced).
    runs[1]["status"] = "completed"
    msgs3, _ = poll.compute(runs, state2)
    assert any("finished" in m for m in msgs3)


def test_baseline_still_raises_a_live_blocker():
    # A run stuck RIGHT NOW is exactly what the watchdog is for — it must post
    # even on the baseline tick.
    runs = [{"runId": "r1", "title": "EV", "status": "ongoing",
             "links": [{"kind": "brief", "url": "u-b"}],
             "needsAttention": True, "attention": "Sign in to ChatGPT"}]
    msgs, state = poll.compute(runs, {}, baseline=True)
    assert len(msgs) == 1  # the blocker only — the old link stays silent
    assert "needs you" in msgs[0] and "Sign in to ChatGPT" in msgs[0]
    msgs2, _ = poll.compute(runs, state)  # next tick, unchanged → silent
    assert msgs2 == []


def test_baseline_skips_stale_terminal_blockers():
    # A long-dead errored run is history the user already saw — re-alerting it
    # on every arm would be noise.
    runs = [{"runId": "r1", "title": "Old fail", "status": "error", "links": [],
             "needsAttention": True, "attention": "the run hit an error"}]
    msgs, _ = poll.compute(runs, {}, baseline=True)
    assert msgs == []


def test_load_state_none_on_missing_and_corrupt(tmp_path, monkeypatch):
    # No file AND a corrupt file must both trigger baseline (None) — a corrupt
    # state treated as "empty but valid" would replay all history.
    monkeypatch.setattr(poll, "_STATE_FILE", tmp_path / "state.json")
    assert poll._load_state() is None  # missing
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    assert poll._load_state() is None  # corrupt
    (tmp_path / "state.json").write_text('{"r1": {"status": "ongoing"}}', encoding="utf-8")
    assert poll._load_state() == {"r1": {"status": "ongoing"}}  # valid
