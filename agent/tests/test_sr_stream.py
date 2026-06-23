"""The streaming watchdog (sr_attention_poll.py) — phase-completion de-dup core.

Loaded standalone (as the cron `no_agent` runner would). compute() consumes the
bridge's per-run `phaseUpdates` (one entry per done phase, with the phase's
permanent SR link(s)) and posts each phase once + a needs-attention blocker.
"""

import importlib.util
import json
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr_attention_poll.py"
    spec = importlib.util.spec_from_file_location("sr_stream_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


poll = _load()


def _pu(phase, name, links, status="complete", final=False):
    return {"phase": phase, "name": name, "status": status, "final": final,
            "links": [{"label": lbl, "url": url, "permanent": perm} for (lbl, url, perm) in links]}


def _run(rid="r1", title="EV market", status="ongoing", phase_updates=None, needs=False, attention=""):
    return {"runId": rid, "title": title, "status": status,
            "phaseUpdates": phase_updates or [], "needsAttention": needs, "attention": attention}


def test_phase_complete_posts_sr_link_once_then_dedups():
    runs = [_run(phase_updates=[_pu(1, "Research Brief", [("Brief", "https://sr.io/shared/doc/B", True)])])]
    msgs, state = poll.compute(runs, {})
    blob = "\n".join(msgs)
    assert "Phase 1 (Research Brief) complete" in blob
    assert "🔒 Brief: https://sr.io/shared/doc/B" in blob
    assert state["r1"]["announced"] == [1]
    msgs2, _ = poll.compute(runs, state)  # nothing new
    assert msgs2 == []


def test_each_phase_announced_incrementally():
    s1 = {"r1": {"announced": [1], "needs": False, "attention": ""}}
    runs = [_run(phase_updates=[
        _pu(1, "Research Brief", [("Brief", "u-b", True)]),
        _pu(2, "Deep Research", [("ChatGPT", "u-c", True), ("Gemini", "u-g", True), ("Claude", "u-cl", True)]),
    ])]
    msgs, state = poll.compute(runs, s1)
    blob = "\n".join(msgs)
    assert "Phase 2 (Deep Research)" in blob
    assert "Phase 1" not in blob  # already announced
    # all three reports, each a permanent 🔒 link
    assert blob.count("🔒") == 3 and "ChatGPT" in blob and "Gemini" in blob and "Claude" in blob
    assert state["r1"]["announced"] == [1, 2]


def test_final_phase_says_emailed_with_doc_link():
    runs = [_run(status="completed", phase_updates=[
        _pu(5, "Delivery", [("Google Doc", "https://docs.google.com/d/x", False)], final=True)])]
    msgs, _ = poll.compute(runs, {})
    blob = "\n".join(msgs)
    assert "pipeline complete" in blob and "emailed" in blob
    assert "📄 Google Doc: https://docs.google.com/d/x" in blob


def test_p3_mixes_platform_and_permanent_icons():
    runs = [_run(phase_updates=[_pu(3, "Audio Overview", [
        ("NotebookLM", "https://notebooklm.google.com/n/1", False),  # platform → 🔗
        ("Podcast", "https://sr.io/shared/podcast/P", True),         # SR → 🔒
    ])])]
    blob = "\n".join(poll.compute(runs, {})[0])
    assert "🔗 NotebookLM: https://notebooklm.google.com/n/1" in blob
    assert "🔒 Podcast: https://sr.io/shared/podcast/P" in blob


def test_skipped_phase_has_no_links():
    runs = [_run(phase_updates=[_pu(4, "Video", [], status="skipped")])]
    msgs, _ = poll.compute(runs, {})
    assert any("Phase 4 (Video) skipped" in m for m in msgs)
    assert not any("http" in m for m in msgs)


def test_baseline_silent_on_done_phases_but_records():
    # First tick after arming: don't replay phases already done on pre-existing
    # runs — record them silently so only FUTURE completions post.
    runs = [_run(phase_updates=[_pu(1, "Research Brief", [("Brief", "u-b", True)])])]
    msgs, state = poll.compute(runs, {}, baseline=True)
    assert msgs == []
    assert state["r1"]["announced"] == [1]
    runs[0]["phaseUpdates"].append(_pu(2, "Deep Research", [("ChatGPT", "u-c", True)]))
    msgs2, _ = poll.compute(runs, state)  # only the NEW phase posts
    blob = "\n".join(msgs2)
    assert "Phase 2" in blob and "Phase 1" not in blob


def test_baseline_still_raises_a_live_blocker():
    runs = [_run(status="ongoing", needs=True, attention="Sign in to ChatGPT")]
    msgs, _ = poll.compute(runs, {}, baseline=True)
    assert any("needs you" in m and "Sign in to ChatGPT" in m and "retry" in m for m in msgs)


def test_needs_attention_posts_once_then_on_change():
    runs = [_run(status="ongoing", needs=True, attention="Sign in")]
    msgs, state = poll.compute(runs, {})
    assert any("needs you" in m for m in msgs)
    msgs2, state2 = poll.compute(runs, state)  # same blocker
    assert not any("needs you" in m for m in msgs2)
    runs[0]["attention"] = "Solve the check"  # reason changed
    msgs3, _ = poll.compute(runs, state2)
    assert any("Solve the check" in m for m in msgs3)


def test_runs_without_id_are_ignored():
    msgs, state = poll.compute([{"title": "x", "phaseUpdates": [_pu(1, "Research Brief", [])]}], {})
    assert msgs == [] and state == {}


def test_load_state_migrates_old_format_to_baseline(tmp_path, monkeypatch):
    # A pre-phaseUpdates state file (old keys, no "announced") must be treated as
    # no-state → silent baseline, NOT re-announce every done phase on upgrade.
    import json as _json
    monkeypatch.setattr(poll, "_STATE_FILE", tmp_path / "state.json")
    assert poll._load_state() is None  # missing → baseline
    (tmp_path / "state.json").write_text(
        _json.dumps({"r1": {"status": "completed", "links": ["brief", "chatgpt"],
                            "announced_terminal": True}}), encoding="utf-8")
    assert poll._load_state() is None  # old format → baseline (no replay)
    (tmp_path / "state.json").write_text(
        _json.dumps({"r1": {"announced": [1, 2], "needs": False, "attention": ""}}), encoding="utf-8")
    assert poll._load_state() == {"r1": {"announced": [1, 2], "needs": False, "attention": ""}}


def test_no_phase_or_platform_link_dump_of_raw_links():
    # The old behavior dumped run["links"] (platform URLs) per kind. The new
    # watchdog ignores run["links"] entirely — only phaseUpdates drive output.
    runs = [_run(phase_updates=[])]
    runs[0]["links"] = [{"kind": "chatgpt", "url": "https://chatgpt.com/c/x", "label": "ChatGPT"}]
    msgs, _ = poll.compute(runs, {})
    assert msgs == []  # raw platform links never posted


# ── #851 item 3: a stop/cancel (incl. from the web app) is announced once ──────

def test_stopped_run_announced_once_when_tracked():
    # We tracked the run while it was live (prior exists); it's now cancelled
    # (e.g. stopped from the app) → one ⏹ notice, then silent.
    prior = {"r1": {"announced": [], "needs": False, "attention": ""}}
    runs = [_run(status="cancelled")]
    msgs, state = poll.compute(runs, prior)
    assert any("stopped" in m for m in msgs)
    assert state["r1"]["ended"] is True
    msgs2, _ = poll.compute(runs, state)  # already announced
    assert not any("stopped" in m for m in msgs2)


def test_stop_silent_on_baseline_but_recorded():
    # First tick after arming must not replay an already-stopped run, but records
    # it as ended so it never surfaces later either.
    msgs, state = poll.compute([_run(status="cancelled")], {}, baseline=True)
    assert not any("stopped" in m for m in msgs)
    assert state["r1"]["ended"] is True


def test_stop_not_announced_for_untracked_run():
    # A terminal run we never saw live (no prior state) must NOT surface as a
    # stop — only a real active→stopped transition we witnessed counts.
    msgs, _ = poll.compute([_run(status="cancelled")], {})
    assert not any("stopped" in m for m in msgs)


def test_completed_run_not_announced_as_stopped():
    # A normal finish (final phase) is the 🎉 line, never a ⏹ stop.
    prior = {"r1": {"announced": [5], "needs": False, "attention": "", "ended": False}}
    runs = [_run(status="completed",
                 phase_updates=[_pu(5, "Delivery", [("Doc", "u", False)], final=True)])]
    msgs, _ = poll.compute(runs, prior)
    assert not any("stopped" in m for m in msgs)


# ── #819 per-chat scoping: origin threads into the query + a per-chat state file ──

def test_state_path_distinct_per_origin():
    assert poll._state_path(None) == poll._STATE_FILE  # account-wide default
    a = poll._state_path({"platform": "telegram", "chat_id": "1"})
    b = poll._state_path({"platform": "telegram", "chat_id": "2"})
    assert a != b and a != poll._STATE_FILE
    assert a.name.startswith(".sr_poll_telegram_") and a.name.endswith(".state.json")


def test_get_updates_scopes_query_by_origin(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"runs": []}'

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(poll.urllib.request, "urlopen", fake_urlopen)
    poll._get_updates({"platform": "telegram", "chat_id": "-100/x"})
    assert "via=agent" in captured["url"]
    assert "platform=telegram" in captured["url"]
    assert "chat=-100" in captured["url"]  # url-encoded; the / becomes %2F
    poll._get_updates()  # account-wide form omits the scope params
    assert "platform=" not in captured["url"] and "chat=" not in captured["url"]


def test_main_scoped_threads_origin_to_query_and_state(monkeypatch):
    origin = {"platform": "telegram", "chat_id": "111"}
    seen = {}
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: seen.__setitem__("origin", o) or [])
    monkeypatch.setattr(poll, "_load_state", lambda path=None: seen.__setitem__("load", path) or None)
    monkeypatch.setattr(poll, "_save_state", lambda state, path=None: seen.__setitem__("save", path))
    assert poll.main(origin) == 0
    assert seen["origin"] == origin
    expected = poll._state_path(origin)
    assert seen["load"] == expected and seen["save"] == expected and expected != poll._STATE_FILE


# ── strict run-linked teardown ───────────────────────────────────────────────

def test_is_active():
    assert poll._is_active({"status": "ongoing"})
    assert poll._is_active({"status": "queued"})
    assert poll._is_active({"status": "completed", "needsAttention": True})  # blocked = still live
    assert not poll._is_active({"status": "completed"})
    assert not poll._is_active({"status": "error"})


def test_remove_cron_entry_drops_only_named_job(tmp_path, monkeypatch):
    monkeypatch.setattr(poll, "_hermes_home", lambda: tmp_path)
    (tmp_path / "cron").mkdir()
    jobs = tmp_path / "cron" / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [
        {"id": "1", "name": "memory-dreaming"},
        {"id": "2", "name": "sr-stream-telegram_abc"},
    ]}), "utf-8")
    assert poll._remove_cron_entry("sr-stream-telegram_abc") is True
    assert [j["name"] for j in json.loads(jobs.read_text("utf-8"))["jobs"]] == ["memory-dreaming"]
    assert poll._remove_cron_entry("sr-stream-telegram_abc") is False  # idempotent — already gone


def test_remove_cron_entry_noop_when_missing_or_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(poll, "_hermes_home", lambda: tmp_path)
    assert poll._remove_cron_entry("sr-stream-x") is False        # no cron/jobs.json
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_text("not json", "utf-8")
    assert poll._remove_cron_entry("sr-stream-x") is False        # unreadable → no-op


def test_teardown_removes_cron_shim_and_state(tmp_path, monkeypatch):
    monkeypatch.setattr(poll, "_hermes_home", lambda: tmp_path)
    origin = {"platform": "telegram", "chat_id": "111"}
    slug = poll._origin_slug(origin)
    (tmp_path / "cron").mkdir()
    jobs = tmp_path / "cron" / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [{"id": "2", "name": f"sr-stream-{slug}"}]}), "utf-8")
    (tmp_path / "scripts").mkdir()
    shim = tmp_path / "scripts" / f"sr_poll_{slug}.py"
    shim.write_text("x", "utf-8")
    state = tmp_path / f".sr_poll_{slug}.state.json"
    state.write_text("{}", "utf-8")
    monkeypatch.setattr(poll, "_state_path", lambda o: state)
    poll._teardown(origin)
    assert not shim.exists() and not state.exists()
    assert json.loads(jobs.read_text("utf-8"))["jobs"] == []


def _main_with(monkeypatch, *, runs, lines, origin):
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: runs)
    monkeypatch.setattr(poll, "_load_state", lambda path=None: {})  # not baseline
    monkeypatch.setattr(poll, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(poll, "compute", lambda r, prior, baseline=False: (lines, {}))
    torn = {}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("o", o))
    assert poll.main(origin) == 0
    return torn


def test_main_self_teardown_when_all_terminal(monkeypatch):
    origin = {"platform": "telegram", "chat_id": "111"}
    torn = _main_with(monkeypatch, runs=[{"runId": "r1", "status": "completed"}], lines=[], origin=origin)
    assert torn.get("o") == origin  # done + nothing new → stop + clean up


def test_main_no_teardown_while_active(monkeypatch):
    torn = _main_with(monkeypatch, runs=[{"runId": "r1", "status": "ongoing"}], lines=[],
                      origin={"platform": "telegram", "chat_id": "111"})
    assert "o" not in torn


def test_main_no_teardown_while_posting_final(monkeypatch):
    # The tick that posts the final phase must NOT also tear down — wait for delivery.
    torn = _main_with(monkeypatch, runs=[{"runId": "r1", "status": "completed"}], lines=["🎉 done"],
                      origin={"platform": "telegram", "chat_id": "111"})
    assert "o" not in torn


def test_main_no_teardown_on_empty_window(monkeypatch):
    torn = _main_with(monkeypatch, runs=[], lines=[], origin={"platform": "telegram", "chat_id": "111"})
    assert "o" not in torn  # no runs yet (race) → don't tear down


def test_main_no_teardown_account_wide(monkeypatch):
    # The shared (origin=None) watchdog is never self-removed (its script serves all chats).
    torn = _main_with(monkeypatch, runs=[{"runId": "r1", "status": "completed"}], lines=[], origin=None)
    assert "o" not in torn
