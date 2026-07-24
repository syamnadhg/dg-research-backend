"""The streaming watchdog (sr_attention_poll.py) — quiet-until-completion core.

Loaded standalone (as the cron `no_agent` runner would). compute() consumes the
bridge's per-run `phaseUpdates` (one entry per done phase, with the phase's
permanent SR link(s)) but is QUIET by design: it does NOT push per-phase progress.
The only run-progress message it posts on its own is ONE completion banner + all
the run's permanent SR links when the final phase lands. Blockers (needs-you) and
stop/cancel notices are the other two proactive messages. Per-phase progress is
on-demand via sr.py `status` (covered in test_sr_client).
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


def test_non_final_phase_is_silent_but_recorded():
    # A finished non-final phase is NOT announced proactively (per-phase progress is
    # on-demand only) — but it IS tracked so the final completion fires exactly once.
    runs = [_run(phase_updates=[_pu(1, "Research Brief", [("Brief", "https://sr.io/shared/doc/B", True)])])]
    msgs, state = poll.compute(runs, {})
    assert msgs == []                      # quiet — no per-phase push
    assert state["r1"]["announced"] == [1]


def test_completion_posts_all_sr_links_once_then_dedups():
    # When the run finishes, ONE message: the banner + every phase's permanent SR
    # link (Brief, the three reports, the Podcast), deduped — then silent.
    runs = [_run(status="completed", phase_updates=[
        _pu(1, "Research Brief", [("Brief", "https://sr.io/shared/doc/B", True)]),
        _pu(2, "Deep Research", [("ChatGPT", "u-c", True), ("Gemini", "u-g", True), ("Claude", "u-cl", True)]),
        _pu(3, "Audio Overview", [("Podcast", "https://sr.io/shared/podcast/P", True)]),
        _pu(5, "Delivery", [], final=True),
    ])]
    msgs, state = poll.compute(runs, {})
    blob = "\n".join(msgs)
    assert "pipeline complete" in blob and "emailed" in blob
    assert blob.count("🔒") == 5  # Brief + 3 reports + Podcast, each once
    for url in ("https://sr.io/shared/doc/B", "u-c", "u-g", "u-cl", "https://sr.io/shared/podcast/P"):
        assert url in blob
    assert state["r1"]["announced"] == [1, 2, 3, 5]
    msgs2, _ = poll.compute(runs, state)  # nothing new
    assert msgs2 == []


def test_final_message_includes_sr_and_platform_links():
    # Policy: SR permanent links (🔒) for Brief/reports/Podcast PLUS the real
    # platform links (🔗) for NotebookLM / YouTube / Google Doc (public / unlisted /
    # shareable — they open fine signed out).
    runs = [_run(status="completed", phase_updates=[
        _pu(3, "Audio Overview", [("NotebookLM", "https://notebooklm.google.com/n/1", False),
                                  ("Podcast", "https://sr.io/shared/podcast/P", True)]),
        _pu(4, "Video", [("YouTube", "https://youtu.be/abc", False)]),
        _pu(5, "Delivery", [("Google Doc", "https://docs.google.com/d/x", False)], final=True),
    ])]
    blob = "\n".join(poll.compute(runs, {})[0])
    assert "pipeline complete" in blob and "emailed" in blob
    assert "🔒 Podcast: https://sr.io/shared/podcast/P" in blob
    assert "🔗 NotebookLM: https://notebooklm.google.com/n/1" in blob
    assert "🔗 YouTube: https://youtu.be/abc" in blob
    assert "🔗 Google Doc: https://docs.google.com/d/x" in blob


def test_skipped_phase_is_silent_but_recorded():
    # Skipped phases are progress → not announced proactively, just tracked so the
    # completion still fires once.
    runs = [_run(phase_updates=[_pu(4, "Video", [], status="skipped")])]
    msgs, state = poll.compute(runs, {})
    assert msgs == []
    assert state["r1"]["announced"] == [4]


def test_baseline_silent_then_quiet_until_completion():
    # Baseline records silently; subsequent non-final phases stay silent too (per-
    # phase is on-demand) — only the final completion ever posts, with all SR links.
    runs = [_run(phase_updates=[_pu(1, "Research Brief", [("Brief", "u-b", True)])])]
    msgs, state = poll.compute(runs, {}, baseline=True)
    assert msgs == []
    assert state["r1"]["announced"] == [1]
    runs[0]["phaseUpdates"].append(_pu(2, "Deep Research", [("ChatGPT", "u-c", True)]))
    msgs2, state2 = poll.compute(runs, state)  # new non-final phase → still silent
    assert msgs2 == []
    assert state2["r1"]["announced"] == [1, 2]
    runs[0]["status"] = "completed"
    runs[0]["phaseUpdates"].append(_pu(5, "Delivery", [], final=True))
    msgs3, _ = poll.compute(runs, state2)  # completion → one message, all SR links
    blob = "\n".join(msgs3)
    assert "pipeline complete" in blob and "u-b" in blob and "u-c" in blob


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


def test_teardown_removes_cron_but_keeps_shim(tmp_path, monkeypatch):
    # A gateway-armed cron lives in the gateway's in-memory registry and gets
    # re-persisted after any host-side jobs.json edit; a no_agent script can't call
    # cronjob:delete. So teardown removes the cron entry (best-effort) but KEEPS the
    # shim + state — a lingering / re-added cron then runs a script that EXISTS and
    # exits silently, instead of firing "Script not found" every tick.
    monkeypatch.setattr(poll, "_hermes_home", lambda: tmp_path)
    origin = {"platform": "telegram", "chat_id": "111"}
    slug = poll._origin_slug(origin)
    (tmp_path / "cron").mkdir()
    jobs = tmp_path / "cron" / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [
        {"id": "1", "name": "memory-dreaming"},
        {"id": "2", "name": f"sr-stream-{slug}"},
    ]}), "utf-8")
    (tmp_path / "scripts").mkdir()
    shim = tmp_path / "scripts" / f"sr_poll_{slug}.py"
    shim.write_text("x", "utf-8")
    state = tmp_path / f".sr_poll_{slug}.state.json"
    state.write_text("{}", "utf-8")
    monkeypatch.setattr(poll, "_state_path", lambda o: state)
    poll._teardown(origin)
    assert shim.exists() and state.exists()  # NEVER deleted — no "Script not found" risk
    names = [j["name"] for j in json.loads(jobs.read_text("utf-8"))["jobs"]]
    assert names == ["memory-dreaming"]  # our cron removed (best-effort), user job kept


def test_teardown_keeps_shim_even_when_cron_removal_fails(tmp_path, monkeypatch):
    # If the cron removal can't stick (write fails / gateway race — simulated by a
    # False return), teardown must not raise and must STILL leave the shim in place
    # (a silent lingering cron, never a "Script not found" crash).
    monkeypatch.setattr(poll, "_hermes_home", lambda: tmp_path)
    origin = {"platform": "telegram", "chat_id": "111"}
    slug = poll._origin_slug(origin)
    monkeypatch.setattr(poll, "_remove_cron_entry", lambda name: False)
    (tmp_path / "scripts").mkdir()
    shim = tmp_path / "scripts" / f"sr_poll_{slug}.py"
    shim.write_text("x", "utf-8")
    monkeypatch.setattr(poll, "_state_path", lambda o: tmp_path / "st.json")
    poll._teardown(origin)  # must not raise
    assert shim.exists()


def _main_with(monkeypatch, *, runs, lines, origin):
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: runs)
    monkeypatch.setattr(poll, "_load_state", lambda path=None: {})  # not baseline
    monkeypatch.setattr(poll, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(poll, "compute",
                        lambda r, prior, baseline=False, suppress_replay=False: (lines, {}))
    torn = {}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("o", o))
    assert poll.main(origin) == 0
    return torn


def test_main_persists_when_all_terminal(monkeypatch):
    # Persistent watchdog: a completed run + nothing new must NOT tear the watchdog
    # down — it keeps ticking silently and streams the NEXT run. (Re-arming on every
    # fire was unreliable: the chat AI skipped arming when no run looked active.)
    # Only `agent disconnect` removes it.
    origin = {"platform": "telegram", "chat_id": "111"}
    torn = _main_with(monkeypatch, runs=[{"runId": "r1", "status": "completed"}], lines=[], origin=origin)
    assert "o" not in torn  # NOT torn down — persists to stream future runs


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


# ── post-login proactive "signed in" announce ─────────────────────────────────

def test_signed_in_line_offers_to_continue_pending_topic():
    line = poll._signed_in_line({"email": "e@x.y", "pendingTopic": "the EV battery market"})
    assert "Signed in as e@x.y" in line
    assert "continue" in line.lower() and "the EV battery market" in line


def test_signed_in_line_without_topic_invites_a_topic():
    line = poll._signed_in_line({"email": "e@x.y", "pendingTopic": ""})
    assert "Signed in as e@x.y" in line and "what to research" in line.lower()


def test_signed_in_line_announces_an_auto_started_run():
    """Bridge started the pending research server-side → report it as started, NOT
    a 'reply yes' offer (no fragile handoff)."""
    line = poll._signed_in_line({
        "email": "e@x.y", "autoStarted": True, "runId": "agent-abc",
        "deviceName": "Office PC", "topic": "Golden Retriever", "pendingTopic": "",
    })
    assert "starting" in line.lower()
    assert "Golden Retriever" in line and "Office PC" in line
    assert "reply" not in line.lower()  # never asks to confirm — it already ran


def test_signed_in_line_prompts_to_pair_a_node_when_none():
    """No Research Computer on the account → surface the pair step (the flow the
    agent failed to show), not a 'reply yes' offer."""
    line = poll._signed_in_line({
        "email": "e@x.y", "needsDevice": True, "topic": "Golden Retriever", "pendingTopic": "",
    })
    assert "no research computer" in line.lower()  # #894 terminology
    # Points at the reliable web-app path + the exact one-message chat form.
    assert "superresearch --pair" in line
    assert "Add Device" in line and "/sr device-add" in line
    assert "reply" not in line.lower()
    # Multi-line / readable (the user complained the old one was a wall of text).
    assert line.count("\n") >= 4


def test_main_announces_signed_in_once_then_dedups(monkeypatch, capsys):
    origin = {"platform": "telegram", "chat_id": "111"}
    saved = {"s": None}
    si = {"ts": 5, "email": "e@x.y", "pendingTopic": "EV market"}
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: ([], si))
    monkeypatch.setattr(poll, "_load_state", lambda path=None: saved["s"])
    monkeypatch.setattr(poll, "_save_state", lambda state, path=None: saved.__setitem__("s", state))
    monkeypatch.setattr(poll, "_teardown", lambda o: None)  # don't wipe the de-dup state
    poll.main(origin)
    out1 = capsys.readouterr().out
    assert "Signed in as e@x.y" in out1 and "EV market" in out1
    # the same event ts is now recorded → a later tick is silent (belt-and-suspenders
    # on top of the bridge's one-shot clear).
    poll.main(origin)
    assert "Signed in" not in capsys.readouterr().out


def test_main_persists_after_signed_in_when_idle(monkeypatch):
    # Persistent: a sign-in announce with nothing running no longer tears the
    # watchdog down — it stays armed so a run fired later streams immediately
    # (no re-arm needed). Removed only by `agent disconnect`.
    origin = {"platform": "telegram", "chat_id": "111"}
    monkeypatch.setattr(poll, "_get_updates",
                        lambda o=None: ([], {"ts": 1, "email": "e@x.y", "pendingTopic": ""}))
    monkeypatch.setattr(poll, "_load_state", lambda path=None: None)
    monkeypatch.setattr(poll, "_save_state", lambda *a, **k: None)
    torn = {}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("o", o))
    poll.main(origin)
    assert "o" not in torn  # stays armed (persistent)


def test_main_keeps_running_after_signed_in_if_a_run_is_active(monkeypatch):
    origin = {"platform": "telegram", "chat_id": "111"}
    monkeypatch.setattr(poll, "_get_updates",
                        lambda o=None: ([{"runId": "r1", "status": "ongoing"}],
                                        {"ts": 2, "email": "e@x.y", "pendingTopic": ""}))
    monkeypatch.setattr(poll, "_load_state", lambda path=None: None)
    monkeypatch.setattr(poll, "_save_state", lambda *a, **k: None)
    torn = {}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("o", o))
    poll.main(origin)
    assert "o" not in torn  # a live run → keep streaming after the sign-in announce


def test_tick_unauthed_waits_then_gives_up(monkeypatch, tmp_path):
    origin = {"platform": "telegram", "chat_id": "111"}
    sf = tmp_path / "st.json"
    torn = {}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("o", o))
    for _ in range(poll._LOGIN_WAIT_LIMIT):
        poll._tick_unauthed(origin, sf)
        assert "o" not in torn  # still within the wait window → stay armed, silent
    poll._tick_unauthed(origin, sf)  # one past the limit
    assert torn.get("o") == origin  # a sign-in that never completes can't poll forever


def test_tick_unauthed_persists_a_signed_in_watchdog(monkeypatch, tmp_path):
    # A watchdog that was ALREADY signed in (a run tracked in state) must NOT be torn
    # down by a 401 outage (web-app logout / revoked-token mid-run) — it persists
    # silently (a 200 resumes; a revoke re-arms later). Only a genuine never-signed-in
    # listener is bounded. (Persistent-watchdog invariant, ROUND 6.)
    origin = {"platform": "telegram", "chat_id": "111"}
    sf = tmp_path / "st.json"
    sf.write_text(json.dumps({"r1": {"completed": True}, "__signed_in_ts__": 9}), "utf-8")
    torn = {}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("o", o))
    for _ in range(poll._LOGIN_WAIT_LIMIT + 5):  # well past the never-signed-in limit
        poll._tick_unauthed(origin, sf)
    assert "o" not in torn  # signed-in watchdog persists through sustained 401s
    assert "__login_wait__" not in json.loads(sf.read_text("utf-8"))  # counter never started


def test_main_authed_tick_clears_login_wait(monkeypatch, tmp_path):
    # A successful (authed, 200) tick must DROP any accumulated __login_wait__ so
    # transient 401s never accumulate toward the never-signed-in give-up on a live
    # watchdog. This is the crux of "no wrongful teardown of a live watchdog".
    origin = {"platform": "telegram", "chat_id": "111"}
    sf = tmp_path / "st.json"
    sf.write_text(json.dumps({"__login_wait__": 17}), "utf-8")
    monkeypatch.setattr(poll, "_state_path", lambda o: sf)
    monkeypatch.setattr(poll, "_get_updates",
                        lambda o=None: ([{"runId": "r1", "status": "ongoing"}], None))
    poll.main(origin)
    saved = json.loads(sf.read_text("utf-8"))
    assert "__login_wait__" not in saved  # cleared on the authed tick
    assert "r1" in saved                  # normal streaming state persisted


def test_main_reserved_only_state_is_baseline_not_a_replay(monkeypatch, capsys):
    # After unauthed login-wait ticks the state file holds ONLY __login_wait__; the
    # first authed tick must treat that as baseline and NOT replay an already-finished
    # run as "just completed".
    origin = {"platform": "telegram", "chat_id": "111"}
    run = _run(status="completed", phase_updates=[_pu(5, "Delivery", [], final=True)])
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: ([run], None))
    monkeypatch.setattr(poll, "_load_state", lambda path=None: {"__login_wait__": 3})
    monkeypatch.setattr(poll, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(poll, "_teardown", lambda o: None)
    poll.main(origin)
    assert "pipeline complete" not in capsys.readouterr().out  # silent baseline


def test_main_401_routes_to_unauthed_wait(monkeypatch):
    origin = {"platform": "telegram", "chat_id": "111"}
    seen = {}

    def _raise_401(o=None):
        raise poll.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(poll, "_get_updates", _raise_401)
    monkeypatch.setattr(poll, "_tick_unauthed", lambda o, sf: seen.__setitem__("o", o) or 0)
    assert poll.main(origin) == 0
    assert seen.get("o") == origin  # 401 → login-listener waiting path, not an error exit


# ── #3: completion driven by terminal STATUS (not a phase `final` flag) ──────

def test_completion_fires_on_terminal_status_even_without_final_flag():
    # A run whose last phase is disabled (e.g. email off) completes with NO
    # phaseUpdate flagged final. Completion must still fire off the run's status,
    # exactly once — the old design keyed on `final` and would miss this run.
    runs = [_run(status="completed", phase_updates=[
        _pu(1, "Research Brief", [("Brief", "https://sr.io/shared/doc/B", True)]),
        _pu(3, "Audio Overview", [("Podcast", "https://sr.io/shared/podcast/P", True)], final=False),
    ])]
    msgs, state = poll.compute(runs, {})
    blob = "\n".join(msgs)
    assert "pipeline complete" in blob and "https://sr.io/shared/podcast/P" in blob
    assert state["r1"]["completed"] is True
    assert poll.compute(runs, state)[0] == []            # exactly once


def test_baseline_announces_recent_completion():
    # Watchdog armed LATE (after the run finished — e.g. after an update/restart):
    # a RECENT completion must still post on the baseline tick, not be swallowed.
    now = 10_000_000_000
    runs = [_run(status="completed", phase_updates=[
        _pu(1, "Research Brief", [("Brief", "u-b", True)]),
        _pu(5, "Delivery", [], final=True),
    ])]
    runs[0]["updatedAt"] = now - 60_000        # finished a minute ago → recent
    msgs, state = poll.compute(runs, {}, baseline=True, now_ms=now)
    assert any("pipeline complete" in m for m in msgs)
    assert state["r1"]["completed"] is True


def test_baseline_suppresses_stale_completion():
    # Arming while an OLD finished run sits in the /updates window must NOT replay a
    # stale 🎉 — but it's marked completed so it never fires on a later tick either.
    now = 10_000_000_000
    runs = [_run(status="completed", phase_updates=[_pu(5, "Delivery", [], final=True)])]
    runs[0]["updatedAt"] = now - 7 * 3600 * 1000   # 7h ago → stale (> 6h window)
    msgs, state = poll.compute(runs, {}, baseline=True, now_ms=now)
    assert msgs == []
    assert state["r1"]["completed"] is True
    assert poll.compute(runs, state, now_ms=now)[0] == []


# ── #3: teardown race — don't delete the watchdog that must stream a fresh run ──

def test_teardown_not_on_autostart_login_tick(monkeypatch):
    # Sign-in auto-started a run, but it's not visible in /updates yet (Firestore
    # lag). The watchdog must stay alive to stream it — NOT tear down on this tick.
    origin = {"platform": "telegram", "chat_id": "c1"}
    signed_in = {"ts": 1, "autoStarted": True, "runId": "r9", "topic": "X"}
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: ([], signed_in))
    monkeypatch.setattr(poll, "_load_state", lambda p=None: None)
    monkeypatch.setattr(poll, "_save_state", lambda s, p=None: None)
    torn = {"v": False}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("v", True))
    poll.main(origin)
    assert torn["v"] is False


def test_no_teardown_on_login_with_nothing_to_stream(monkeypatch):
    # Persistent: sign-in that didn't auto-start a run (needs a device) + nothing
    # active used to tear the login-listener down; now it PERSISTS (armed + silent)
    # so the eventual run streams without a re-arm. (Removed only by disconnect.)
    origin = {"platform": "telegram", "chat_id": "c1"}
    signed_in = {"ts": 1, "needsDevice": True}
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: ([], signed_in))
    monkeypatch.setattr(poll, "_load_state", lambda p=None: None)
    monkeypatch.setattr(poll, "_save_state", lambda s, p=None: None)
    torn = {"v": False}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("v", True))
    poll.main(origin)
    assert torn["v"] is False  # persists — no self-teardown


# ── stale-result leak: a sign-in tick must not dump a PRIOR run's completion ──

def test_compute_suppress_replay_hides_completion_but_marks_it_seen():
    # suppress_replay (a sign-in tick): a recent prior completion is NOT posted, but
    # is still marked completed so it can never replay on a later tick either.
    now = 10_000_000_000
    runs = [_run(status="completed", phase_updates=[
        _pu(1, "Research Brief", [("Brief", "u-b", True)]),
        _pu(5, "Delivery", [], final=True),
    ])]
    runs[0]["updatedAt"] = now - 60_000  # finished a minute ago → would normally post on baseline
    msgs, state = poll.compute(runs, {}, baseline=True, now_ms=now, suppress_replay=True)
    assert msgs == []                       # NOT dumped on the sign-in tick
    assert state["r1"]["completed"] is True  # but marked seen → never replays later
    # a normal later tick with that state stays silent (already completed)
    assert poll.compute(runs, state, now_ms=now)[0] == []


def test_main_signin_tick_does_not_replay_prior_completion(monkeypatch, capsys):
    # THE #leak: reconnect + sign in for NEW work must announce ONLY the sign-in —
    # not the LAST run's 🎉 results (Golden Retriever), which a fresh login-listener
    # (no de-dup state after disconnect) would otherwise replay as a recent completion.
    origin = {"platform": "telegram", "chat_id": "111"}
    now = 10_000_000_000
    prior_run = _run(rid="old", title="Golden Retriever", status="completed",
                     phase_updates=[_pu(5, "Delivery", [("Doc", "u-doc", True)], final=True)])
    prior_run["updatedAt"] = now - 60_000  # recent
    si = {"ts": 7, "email": "e@x.y", "pendingTopic": "German Shepherd"}
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: ([prior_run], si))
    monkeypatch.setattr(poll, "_load_state", lambda path=None: None)  # fresh (post-disconnect)
    monkeypatch.setattr(poll, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(poll, "_teardown", lambda o: None)
    monkeypatch.setattr(poll, "_now_ms", lambda: now)
    poll.main(origin)
    out = capsys.readouterr().out
    assert "Signed in as e@x.y" in out              # sign-in announced
    assert "German Shepherd" in out                 # the pending topic offered
    assert "Golden Retriever" not in out            # the LAST run's results are NOT dumped
    assert "pipeline complete" not in out


def test_compute_suppress_replay_still_announces_a_tracked_run_completion():
    # suppress_replay must hide ONLY an untracked prior run (the leak). A run we were
    # streaming live (prior state exists) still announces its completion even if a
    # re-sign-in event lands on the exact tick it finishes — those are the results the
    # user is actually waiting on. (Guards the over-suppression the review caught.)
    prior = {"r1": {"announced": [1], "needs": False, "attention": "", "completed": False}}
    runs = [_run(status="completed", phase_updates=[
        _pu(1, "Research Brief", [("Brief", "u-b", True)]),
        _pu(5, "Delivery", [], final=True)])]
    msgs, state = poll.compute(runs, prior, baseline=False, suppress_replay=True)
    blob = "\n".join(msgs)
    assert "pipeline complete" in blob and "u-b" in blob  # tracked completion NOT suppressed
    assert state["r1"]["completed"] is True


def test_compute_suppress_replay_still_announces_a_tracked_run_stop():
    # Same for a stop/cancel of a tracked run on a sign-in tick — the ended branch
    # must not be suppressed (it already only fires for runs we tracked live).
    prior = {"r1": {"announced": [], "needs": False, "attention": "", "ended": False}}
    runs = [_run(status="cancelled")]
    msgs, _ = poll.compute(runs, prior, baseline=False, suppress_replay=True)
    assert any("stopped" in m for m in msgs)


# ── persistence across the sign-in → run-start handoff ─────────────────────────
# Supersedes the old __await_run__ keep-alive: the watchdog now never self-tears-
# down, so the sign-in→run gap (a just-fired run not yet in /updates) is covered for
# free. Re-arming on every fire was the unreliable part — the chat AI skipped arming
# whenever no run looked active yet.

def test_main_keeps_alive_when_signin_offers_a_pending_run(monkeypatch):
    # "Continue with X? Reply yes to start" — the run isn't in /updates yet. The
    # persistent watchdog stays armed regardless (it never self-tears-down), so the
    # run streams the moment it appears — the gap the user hit.
    origin = {"platform": "telegram", "chat_id": "c1"}
    si = {"ts": 1, "email": "e@x.y", "pendingTopic": "German Shepherd"}
    saved = {}
    monkeypatch.setattr(poll, "_get_updates", lambda o=None: ([], si))
    monkeypatch.setattr(poll, "_load_state", lambda p=None: None)
    monkeypatch.setattr(poll, "_save_state", lambda s, p=None: saved.__setitem__("s", s))
    torn = {"v": False}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("v", True))
    poll.main(origin)
    assert torn["v"] is False                    # NOT torn down — persists to stream the run
    assert "__await_run__" not in saved["s"]     # no keep-alive counter — persistence replaces it


def test_main_streams_the_offered_run_once_it_starts(monkeypatch):
    # The offered run is now live → keep streaming (still no teardown). A stale
    # __await_run__ left by an older build is simply ignored (compute rebuilds state
    # from runs), so it never resurfaces in the persisted state.
    origin = {"platform": "telegram", "chat_id": "c1"}
    saved = {}
    monkeypatch.setattr(poll, "_load_state",
                        lambda p=None: {"__await_run__": 5, "__signed_in_ts__": 1})
    monkeypatch.setattr(poll, "_get_updates",
                        lambda o=None: ([{"runId": "r1", "status": "ongoing"}], None))
    monkeypatch.setattr(poll, "_save_state", lambda s, p=None: saved.__setitem__("s", s))
    torn = {"v": False}
    monkeypatch.setattr(poll, "_teardown", lambda o: torn.__setitem__("v", True))
    poll.main(origin)
    assert torn["v"] is False                     # active run → keep streaming
    assert "__await_run__" not in saved["s"]      # stale leftover dropped from persisted state
