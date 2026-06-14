"""The streaming watchdog (sr_attention_poll.py) — phase-completion de-dup core.

Loaded standalone (as the cron `no_agent` runner would). compute() consumes the
bridge's per-run `phaseUpdates` (one entry per done phase, with the phase's
permanent SR link(s)) and posts each phase once + a needs-attention blocker.
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


def test_no_phase_or_platform_link_dump_of_raw_links():
    # The old behavior dumped run["links"] (platform URLs) per kind. The new
    # watchdog ignores run["links"] entirely — only phaseUpdates drive output.
    runs = [_run(phase_updates=[])]
    runs[0]["links"] = [{"kind": "chatgpt", "url": "https://chatgpt.com/c/x", "label": "ChatGPT"}]
    msgs, _ = poll.compute(runs, {})
    assert msgs == []  # raw platform links never posted
