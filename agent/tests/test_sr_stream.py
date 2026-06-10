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
