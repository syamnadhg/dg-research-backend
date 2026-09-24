"""A crash retry re-runs only the Phase-2 agents that had not finished.

⛔⛔ THE DEFECT (wave 10.9, D5). An interrupted Phase 2 resumes through
`run_phase2`, and it launched EVERY enabled agent from zero. `detect_resume_phase`
said so in its own comment — "re-running P2 re-extracts ALL enabled agents from
scratch" — and priced it at "a few extra minutes". It was every finished Deep
Research bought again on each silent relaunch after a Chrome death (up to
BROWSER_CRASH_MAX_RETRIES of them; a daemon restart resumes the same way), with
the finished tile flipped back to "running".

⭐ THE FIX HAS FIVE PARTS, AND EACH ONE IS EXECUTED HERE:
  * `extract_and_record_agent` writes a durable completion record in the ONE
    branch that announces `complete` — driven end to end below;
  * every launch in `run_phase2` takes its agent back out of the record — driven
    below up to the moment the agent would open;
  * `_p2_resume_plan` keeps an agent only with BOTH the record and its report,
    and hands back the text a fresh extraction would have returned;
  * `_p2_announce_restored` re-ticks the kept agent's tile — with the sources,
    sections and steps its own completion carried — which the resume's full
    `phase_restart` has just re-seeded on the web;
  * `_p2_run_with_resume` is the phase itself: plan → attempts → merge → safety
    filter, driven below with a fake attempt runner.

⛔⛔ THAT LAST ONE USED TO BE NINETY LINES INSIDE `run_pipeline`, a 5,000-line
coroutine nothing can drive, pinned only by AST SHAPE — and one added line
reassigning the launch list or the kept results put every finished Deep Research
back on the bill with this whole suite green. What is left in `run_pipeline` is
one call, one `return`, and the promise that nothing stands between the phase
and the off-topic sweep; those three are what the AST still checks.
"""
import ast
import asyncio
import inspect
import json
import textwrap

import pytest

import research


ALL = ["chatgpt", "gemini", "claude"]

REPORT = {
    "chatgpt": "## Findings\n\nThe grid market consolidated in three waves, and the "
               "third is still under way across every region we looked at.\n",
    "gemini": "## Summary\n\nStorage prices fell faster than any forecast made in "
              "the last decade, and the curve has not flattened yet at all.\n",
    "claude": "## Overview\n\nTransmission, not generation, is the binding constraint "
              "in most of the markets studied, and permitting sets its pace.\n",
}

FINDING = [{"url": "https://e.example.com/a", "snippet": "a cited line",
            "sourceTitle": "A page"}]


def _queue(tmp_path, done=(), docs=()):
    """A run folder: `docs` get a report file, `done` get a completion record."""
    q = tmp_path / "run"
    (q / "documents").mkdir(parents=True, exist_ok=True)
    for key in docs:
        name = research._agent_display_name(key)
        (q / "documents" / f"{key}.md").write_text(
            f"# {name} Deep Research\n\n{REPORT[key]}", encoding="utf-8")
    for key in done:
        research._p2_mark_agent_done(q, key, True, elapsed_sec=1234, findings=FINDING)
    return q


def _record(q):
    return json.loads((q / research._P2_AGENTS_DONE_FILE).read_text(encoding="utf-8"))["agents"]


# ── the decision: which agents are kept ───────────────────────────────────────

def test_a_recorded_agent_with_its_report_is_kept_and_its_header_comes_off(tmp_path):
    q = _queue(tmp_path, done=["chatgpt"], docs=["chatgpt"])
    got = research._p2_restorable_agents(q, ALL)
    assert list(got) == ["chatgpt"]
    # Exactly the extractor's `text`: our own header stripped, nothing else.
    assert got["chatgpt"]["text"] == REPORT["chatgpt"]
    assert got["chatgpt"]["elapsed_sec"] == 1234
    assert got["chatgpt"]["findings"] == FINDING


def test_a_report_file_with_no_record_is_a_salvaged_partial_and_runs_again(tmp_path):
    """⛔⛔ THE CASE NOTHING ELSE CAN SATISFY. The Stop path and the finalize
    re-save both write `documents/<agent>.md` from a salvaged partial, so a
    plain file-existence scan would keep an agent that never finished. Only the
    record can tell the two apart."""
    q = _queue(tmp_path, docs=["chatgpt", "gemini"], done=["gemini"])
    assert list(research._p2_restorable_agents(q, ALL)) == ["gemini"]


def test_a_record_whose_report_was_deleted_runs_again(tmp_path):
    """A feedback-targeted resume unlinks every agent report and leaves the
    record — the person asked for that phase to be redone."""
    q = _queue(tmp_path, done=["chatgpt", "claude"], docs=["chatgpt", "claude"])
    (q / "documents" / "chatgpt.md").unlink()
    assert list(research._p2_restorable_agents(q, ALL)) == ["claude"]


def test_a_near_empty_report_runs_again(tmp_path):
    q = _queue(tmp_path, done=["chatgpt", "gemini"], docs=["gemini"])
    (q / "documents" / "chatgpt.md").write_text("# ChatGPT Deep Research\n\nshort",
                                              encoding="utf-8")
    assert list(research._p2_restorable_agents(q, ALL)) == ["gemini"]


def test_an_agent_switched_off_since_is_not_kept(tmp_path):
    q = _queue(tmp_path, done=["chatgpt", "claude"], docs=["chatgpt", "claude"])
    assert list(research._p2_restorable_agents(q, ["claude", "gemini"])) == ["claude"]


def test_an_unreadable_record_keeps_nothing(tmp_path):
    q = _queue(tmp_path, docs=["chatgpt"])
    (q / research._P2_AGENTS_DONE_FILE).write_text("{not json", encoding="utf-8")
    assert research._p2_restorable_agents(q, ALL) == {}
    assert research._p2_restorable_agents(None, ALL) == {}


def test_the_regenerated_header_comes_off_too(tmp_path):
    q = _queue(tmp_path, done=["gemini"])
    (q / "documents" / "gemini.md").write_text(
        "# Gemini Deep Research (retry)\n\n" + REPORT["gemini"], encoding="utf-8")
    assert research._p2_restorable_agents(q, ALL)["gemini"]["text"] == REPORT["gemini"]


def test_the_plan_launches_the_rest_in_order_and_keeps_the_finished_as_done(
        tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    q = _queue(tmp_path, done=["gemini"], docs=["chatgpt", "gemini", "claude"])
    launch, kept = research._p2_resume_plan(q, ALL)
    assert launch == ["chatgpt", "claude"]
    assert list(kept) == ["Gemini"]
    g = kept["Gemini"]
    # Every field a phase-2 reader keys on: the done count, the linked bucket,
    # the per-agent "complete", completionTimeSec, and the re-save skip.
    assert g["status"] == "done" and g["verified"] is True and g["md_saved"] is True
    assert g["_in_app_url"] == "/documents?open=rid-1:gemini"
    assert g["text"] == REPORT["gemini"]
    assert g["elapsed_sec"] == 1234 and g["_restored"] is True
    assert g["url"] == ""


def test_a_fresh_run_launches_every_agent(tmp_path):
    q = _queue(tmp_path, docs=ALL)
    assert research._p2_resume_plan(q, ALL) == (ALL, {})


def test_the_finalize_resave_skips_only_a_kept_agent():
    assert research._p2_needs_resave({"text": "report"}) is True
    assert research._p2_needs_resave({"text": "report", "_restored": True}) is False
    assert research._p2_needs_resave({"text": ""}) is False


# ── the record's writer: the complete branch, executed ────────────────────────

class _Page:
    url = "https://chatgpt.com/c/abc"


class _Browser:
    async def switch_to_page(self, page):
        return None


class _Runtime:
    def __init__(self, snapshots=None, history=None):
        self.agent_findings = {}
        self.agent_progress_snapshots = dict(snapshots or {})
        # ⛔⛔ `save_meta` reads TWO rings off `_runtime` per agent, and the
        # first repair round restored one of them. This is the other.
        self.agent_progress_history = dict(history or {})
        self.restart_requested = False


def _drive_the_extractor(monkeypatch, tmp_path, report, *, saved_ok=True,
                         research_id="rid-1", snapshot=None, history=None):
    """The REAL `extract_and_record_agent`, with only the browser, the network
    and Firestore stubbed. `snapshot` seeds the agent's live progress ring and
    `history` its progress-history ring, the way the pollers fill both while the
    agent works."""
    async def _extract(page, **kw):
        return report

    async def _rehost(text, label=None, **kw):
        return text

    async def _save(doc_type, content, name=None, **kw):
        return saved_ok

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(research, "_runtime",
                        _Runtime({"chatgpt": snapshot} if snapshot else None,
                                 {"chatgpt": history} if history else None),
                        raising=False)
    monkeypatch.setattr(research, "extract_chatgpt_response", _extract)
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)
    monkeypatch.setattr(research, "_rehost_document_images", _rehost)
    monkeypatch.setattr(research, "save_document_to_firestore_with_retry", _save)
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_fb_uid", "uid-1")
    monkeypatch.setattr(research, "_fb_research_id", research_id)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    q = tmp_path / "run"
    q.mkdir(exist_ok=True)
    res = asyncio.run(research.extract_and_record_agent(
        "ChatGPT", _Page(), _Browser(), None, q, elapsed_sec=777))
    return q, res


CITED = ("## Battery prices\n\nPack prices fell by a fifth, reported at "
         "https://bnef.example.com/packs in a note nobody has disputed since.\n")


def test_a_completed_agent_is_recorded_and_comes_back_whole(monkeypatch, tmp_path):
    q, res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"])
    assert res["status"] == "done"
    rec = _record(q)
    assert list(rec) == ["chatgpt"] and rec["chatgpt"]["elapsedSec"] == 777
    # The round trip: what a crash retry reads back is what the phase got.
    got = research._p2_restorable_agents(q, ALL)
    assert got["chatgpt"]["text"] == res["text"]


def test_the_record_carries_the_findings_the_extraction_built(monkeypatch, tmp_path):
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, CITED)
    urls = [f.get("url") for f in _record(q)["chatgpt"]["findings"]]
    assert urls == ["https://bnef.example.com/packs"]


def test_a_report_the_app_cannot_find_is_not_recorded(monkeypatch, tmp_path):
    """The same gate as `complete`: the Firestore copy failed, so the file on
    disk is not something the app can open, and a crash retry must re-run it."""
    q, res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"], saved_ok=False)
    assert res["status"] == "failed"
    assert (q / "documents" / "chatgpt.md").exists()
    assert not (q / research._P2_AGENTS_DONE_FILE).exists()


def test_an_empty_extraction_is_not_recorded(monkeypatch, tmp_path):
    q, res = _drive_the_extractor(monkeypatch, tmp_path, "")
    assert res["status"] == "failed"
    assert not (q / research._P2_AGENTS_DONE_FILE).exists()


def test_a_report_with_no_research_anchor_is_not_recorded(monkeypatch, tmp_path):
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   research_id=None)
    assert not (q / research._P2_AGENTS_DONE_FILE).exists()


# ── what a kept agent hands back: the extraction's text, not the file's ───────

OWN_LIST = ("## Battery prices\n\nPack prices fell by a fifth, reported at "
            "https://bnef.example.com/packs in a note nobody has disputed, and "
            "[the agency](https://iea.example.com/renewables) agreed with it.\n\n"
            "## Sources\n\n1. [BNEF pack survey](https://bnef.example.com/packs)\n")


def test_a_kept_agents_text_is_what_a_fresh_extraction_returned(monkeypatch, tmp_path):
    """⛔⛔ THE DOCUMENT IS NUMBERED AND THE `text` NEVER WAS. Every
    `documents/<agent>.md` is written with our inline `[\\[n\\]]` markers and a
    `##### Sources` list on the end, while the agents that re-ran hand back plain
    text. Read the file back as it stands and the kept agent's bibliography lands
    in the MIDDLE of the consolidated report — where the web's end-anchored strip
    leaves it, beside the web's own differently numbered list, in the Summary
    prompt and in the machine's own summary and title steps."""
    q, res = _drive_the_extractor(monkeypatch, tmp_path, CITED)
    on_disk = (q / "documents" / "chatgpt.md").read_text(encoding="utf-8")
    # The published document keeps its numbering — this is not a rollback of it.
    assert "##### Sources" in on_disk and "[\\[1\\]](" in on_disk
    got = research._p2_restorable_agents(q, ALL)["chatgpt"]["text"]
    # Trailing newlines are the one thing the numbering cannot give back: it
    # rstrips the document before appending its list.
    assert got == res["text"].rstrip("\n")


def test_the_agents_own_links_and_its_own_sources_list_are_left_alone(
        monkeypatch, tmp_path):
    """Accept polarity: only what this machine added comes off. An agent's own
    markdown links and its own trailing sources list are the report."""
    q, res = _drive_the_extractor(monkeypatch, tmp_path, OWN_LIST)
    got = research._p2_restorable_agents(q, ALL)["chatgpt"]["text"]
    assert got == res["text"].rstrip("\n")
    assert "[the agency](https://iea.example.com/renewables)" in got
    assert got.endswith("## Sources\n\n1. [BNEF pack survey](https://bnef.example.com/packs)")


# ── the record's eraser: every launch, executed ───────────────────────────────

class _Launched(Exception):
    pass


@pytest.mark.parametrize("agent", ALL)
def test_launching_an_agent_takes_it_out_of_the_record_before_it_opens(
        agent, monkeypatch, tmp_path):
    """⛔ WITHOUT THIS THE RECORD LIES. Retry, a restart with new input, and the
    Phase-3 gate's Retry all relaunch finished agents on purpose; if the new
    attempt dies with a salvaged partial, the partial overwrites the report file
    and an entry left over from the LAST attempt would hand it back as done.

    Driven up to the moment the agent's tab would open: the stub raises there, so
    the entry must already be gone — and only that agent's."""
    q = _queue(tmp_path, done=ALL, docs=ALL)
    opened = []

    async def _open(*a, **k):
        opened.append(a[5] if len(a) > 5 else "")
        raise _Launched()

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(research, "_p2_run_dir", lambda: q)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "start_agent_no_gemini_wait", _open)
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")

    class _B:
        page = None

    with pytest.raises(_Launched):
        asyncio.run(research.run_phase2(_B(), None, "brief " * 40, enabled_agents=[agent]))
    assert opened, "the stub never ran — the launch site was not reached"
    assert sorted(_record(q)) == sorted(a for a in ALL if a != agent)


def test_nothing_left_to_launch_opens_nothing(monkeypatch, tmp_path):
    """Every enabled agent was kept: `run_phase2` is handed an empty list and
    must return at once, without opening a tab or polling anything."""
    async def _boom(*a, **k):
        raise AssertionError("nothing should be launched or polled")

    monkeypatch.setattr(research, "_p2_run_dir", lambda: tmp_path)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "start_agent_no_gemini_wait", _boom)
    monkeypatch.setattr(research, "poll_all_agents_round_robin", _boom)

    class _B:
        page = None

    assert asyncio.run(research.run_phase2(_B(), None, "brief", enabled_agents=[])) == {}


def test_a_launch_on_a_fresh_run_writes_nothing(tmp_path):
    q = tmp_path / "run"
    q.mkdir()
    research._p2_mark_agent_done(q, "chatgpt", False)
    assert not (q / research._P2_AGENTS_DONE_FILE).exists()
    # …and never resurrects a deleted run's folder.
    research._p2_mark_agent_done(tmp_path / "gone", "chatgpt", True)
    assert not (tmp_path / "gone").exists()


# ── the kept agent's tile ─────────────────────────────────────────────────────

def test_a_kept_agent_is_announced_complete_and_persisted(monkeypatch, tmp_path):
    """⛔ The resume's full `phase_restart` re-seeds every Phase-2 agent on the
    web, so a kept agent that says nothing sits on its seed row all phase."""
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    rt = _Runtime()
    monkeypatch.setattr(research, "_runtime", rt, raising=False)
    events, statuses = [], []
    monkeypatch.setattr(research, "emit_event",
                        lambda t, **k: events.append((t, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status",
                        lambda *a, **k: statuses.append(a))
    q = _queue(tmp_path, done=["claude"], docs=["claude", "gemini"])
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._p2_announce_restored(kept)

    progress = [k for t, k in events if t == "agent_progress"]
    links = [k for t, k in events if t == "link_extracted"]
    assert [(p["agent"], p["status"]) for p in progress] == [("claude", "complete")]
    assert progress[0]["partialTextLen"] == len(REPORT["claude"])
    assert progress[0]["links"][0]["url"] == "/documents?open=rid-1:claude"
    assert [(k["agent"], k["url"], k["label"], k["primary"]) for k in links] == [
        ("claude", "/documents?open=rid-1:claude", "Read Claude report", True)]
    assert statuses == [("claude", "complete")]
    assert rt.agent_findings == {"claude": FINDING}


SNAP = {"source_urls": ["https://a.example/one", "https://b.example/two"],
        "sections": ["Overview", "Prices"],
        "steps": ["searched the web", "read 12 pages"],
        "searches": 12, "observed_sources": 7, "sources": 1,
        # The findings extractor's raw input — the big one, and not worth keeping.
        "source_items": [{"url": "https://a.example/one", "title": "One"}]}


def test_the_record_keeps_the_progress_the_completion_emit_carried(
        monkeypatch, tmp_path):
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   snapshot=SNAP)
    prog = _record(q)["chatgpt"]["progress"]
    assert prog["source_urls"] == SNAP["source_urls"]
    assert prog["sections"] == SNAP["sections"]
    assert prog["steps"] == SNAP["steps"]
    assert prog["searches"] == 12 and prog["observed_sources"] == 7
    assert "source_items" not in prog


def test_a_kept_agents_card_carries_the_sources_sections_and_steps_it_had(
        monkeypatch, tmp_path):
    """⛔⛔ A RESUME RE-SEEDS THE WEB'S PHASE-2 DETAILS, and the `agent_progress`
    merge keeps the seed for every field an event does not carry. Announced
    without these, a kept agent read "complete — 0 sources, no sections, no
    steps" for the rest of the phase, while the agents still working filled in."""
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   snapshot=SNAP)
    # A daemon restart: a NEW process, so the in-process snapshot ring is empty
    # and the durable record is the only place this can come from.
    rt = _Runtime()
    monkeypatch.setattr(research, "_runtime", rt, raising=False)
    events = []
    monkeypatch.setattr(research, "emit_event", lambda t, **k: events.append((t, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._p2_announce_restored(kept)

    prog = [k for t, k in events if t == "agent_progress"][0]
    assert prog["sourceUrls"] == SNAP["source_urls"]
    assert prog["sections"] == SNAP["sections"]
    assert prog["steps"] == SNAP["steps"]
    assert prog["searches"] == 12 and prog["observedSources"] == 7
    # Never smaller than the list of sources the card is about to draw.
    assert prog["sources"] == 2
    # …and save_meta's own readers get the ring back with it.
    assert rt.agent_progress_snapshots["chatgpt"]["source_urls"] == SNAP["source_urls"]


def test_the_snapshot_is_kept_in_the_shapes_the_card_needs():
    got = research._p2_progress_snapshot(
        {"source_urls": ["https://a.example/one"], "sections": "not a list",
         "steps": ["read 12 pages"], "searches": "12", "observed_sources": None,
         "sources": 3, "source_items": [{"url": "https://a.example/one"}]})
    assert got == {"source_urls": ["https://a.example/one"],
                   "steps": ["read 12 pages"], "searches": 12,
                   "observed_sources": 0, "sources": 3}
    assert research._p2_progress_snapshot(None) == {}


def test_a_record_whose_counts_are_not_numbers_still_announces(
        monkeypatch, tmp_path):
    """⛔ THE SAME EMIT CARRIES THE REPORT LINK. A snapshot read back off disk is
    not trusted to be well shaped — a count that raised inside the emit would
    cost the kept agent its whole progress event, not just its number."""
    q = _queue(tmp_path, done=["claude"], docs=["claude"])
    rec = json.loads((q / research._P2_AGENTS_DONE_FILE).read_text(encoding="utf-8"))
    rec["agents"]["claude"]["progress"] = {"searches": "many", "sections": "none",
                                           "source_urls": ["https://a.example/one"]}
    (q / research._P2_AGENTS_DONE_FILE).write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(research, "_runtime", _Runtime(), raising=False)
    events = []
    monkeypatch.setattr(research, "emit_event", lambda t, **k: events.append((t, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._p2_announce_restored(kept)

    prog = [k for t, k in events if t == "agent_progress"][0]
    assert prog["status"] == "complete" and prog["searches"] == 0
    assert prog["sections"] == [] and prog["sourceUrls"] == ["https://a.example/one"]


def test_a_record_written_before_the_snapshot_existed_still_announces(
        monkeypatch, tmp_path):
    """Accept polarity: a run interrupted across an upgrade has no `progress` in
    its record, and its kept agent must still be announced complete."""
    q = _queue(tmp_path, done=["claude"], docs=["claude"])
    rec = json.loads((q / research._P2_AGENTS_DONE_FILE).read_text(encoding="utf-8"))
    del rec["agents"]["claude"]["progress"]
    (q / research._P2_AGENTS_DONE_FILE).write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(research, "_runtime", _Runtime(), raising=False)
    events = []
    monkeypatch.setattr(research, "emit_event", lambda t, **k: events.append((t, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._p2_announce_restored(kept)

    prog = [k for t, k in events if t == "agent_progress"][0]
    assert prog["status"] == "complete"
    assert prog["sourceUrls"] == [] and prog["sections"] == [] and prog["sources"] == 0


# ── the kept agent's curve ────────────────────────────────────────────────────
#
# ⛔⛔ THE SECOND THING `save_meta` READS OFF `_runtime`, AND THE FIRST REPAIR
# ROUND PUT BACK ONLY THE FIRST. A kept agent is never relaunched, so nothing
# ticks its `agent_progress_history` on the attempt that finishes the run — and
# `run_pipeline` resets the ring on every re-entry. `save_meta` then wrote
# `progressHistory: []` for it, into meta.json and into a whole-FIELD Firestore
# replace, so the web's All-Agents sparkline and the post-reload chart read
# "No data" for the one agent that actually did the work, while the relaunched
# ones kept their curves. Before this wave the kept agent re-ran and rebuilt
# its history, which is what hid it.

CURVE = [{"t": i * 60_000, "sources": i, "chars": i * 900, "sections": i,
          "searches": i * 2, "sectionsDone": 0, "sectionsTotal": 4}
         for i in range(1, 7)]


def test_the_record_keeps_the_curve_the_agent_earned(monkeypatch, tmp_path):
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   history=CURVE)
    assert _record(q)["chatgpt"]["progressHistory"] == CURVE


def test_the_record_stores_the_curve_downsampled_the_way_save_meta_would(
        monkeypatch, tmp_path):
    """⭐ ONE DOWNSAMPLER, TWO WRITERS. The live ring holds 240 samples and
    `save_meta` persists 60 of them; a record that kept all 240 would hand back
    a curve the run's own save would never have written."""
    ring = [{"t": i * 1000, "chars": i * 10} for i in range(240)]
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   history=ring)
    stored = _record(q)["chatgpt"]["progressHistory"]
    assert len(stored) == 60
    assert stored == research._downsample_progress_history(ring)


def test_the_downsampler_samples_evenly_and_leaves_a_short_ring_alone():
    """⛔⛔ THE ARITHMETIC, PINNED ON A RING WHERE IT IS EXACT. 119 samples into
    60 points is every second one, first and last included — the step spans the
    GAPS, `(n-1)/(cap-1)`, not the samples. A step of `n/cap` gives 60 points
    with the right endpoints and the wrong curve in between, and the two lines
    that used to overwrite the endpoints would have hidden exactly that; they
    are gone, and this is what replaced them."""
    ring = [{"t": i} for i in range(119)]
    assert research._downsample_progress_history(ring) == ring[::2]
    assert research._downsample_progress_history(ring)[-1] is ring[-1]
    long_ring = [{"t": i} for i in range(500)]
    assert len(research._downsample_progress_history(long_ring)) == 60
    short = [{"t": 1}, {"t": 2}]
    assert research._downsample_progress_history(short) == short
    assert research._downsample_progress_history(None) == []


def test_a_kept_agent_gets_its_curve_back_into_the_ring(monkeypatch, tmp_path):
    """The restore, executed: a daemon restart starts with an empty ring, and
    the durable record is the only place the curve can come from."""
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   history=CURVE)
    rt = _Runtime()
    monkeypatch.setattr(research, "_runtime", rt, raising=False)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._p2_announce_restored(kept)
    assert rt.agent_progress_history["chatgpt"] == CURVE


def _save_meta_env(monkeypatch, tmp_path):
    """The REAL `save_meta`, with only the Firestore propagation captured."""
    captured = {}
    monkeypatch.setattr(research, "_update_firestore_research",
                        lambda updates: captured.update(updates))
    monkeypatch.setattr(research, "_agent_status_by_rid", {}, raising=False)
    monkeypatch.setattr(research, "_phase_status_by_rid", {}, raising=False)
    return captured


def test_the_run_that_keeps_an_agent_persists_its_curve_not_an_empty_one(
        monkeypatch, tmp_path):
    """⛔⛔ THE DEFECT, END TO END, over the two records the web reads: the run
    resumes, keeps ChatGPT, and saves. Against round 1's code the curve reaching
    both meta.json and the Firestore payload here is `[]`."""
    q, _res = _drive_the_extractor(monkeypatch, tmp_path, REPORT["chatgpt"],
                                   history=CURVE)
    rt = _Runtime()          # a fresh worker: run_pipeline has reset the ring
    monkeypatch.setattr(research, "_runtime", rt, raising=False)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._p2_announce_restored(kept)

    captured = _save_meta_env(monkeypatch, tmp_path)
    research.save_meta(q, "Grid storage", 2)
    meta = json.loads((q / "meta.json").read_text(encoding="utf-8"))
    assert meta["agents"]["chatgpt"]["progressHistory"] == CURVE
    assert captured["agents"]["chatgpt"]["progressHistory"] == CURVE


def test_a_save_with_nothing_to_say_does_not_erase_a_persisted_curve(
        monkeypatch, tmp_path):
    """⛔ THE BELT, for a record written before the curve was kept in it — or
    one that failed to write. `save_meta` consults `existing` for every other
    field it cannot rebuild; the history does too now. The Firestore write is a
    whole-field replace, so an empty rebuild used to destroy the curve there as
    well as on disk."""
    q = _queue(tmp_path, done=["chatgpt"], docs=["chatgpt"])
    (q / "meta.json").write_text(json.dumps(
        {"agents": {"chatgpt": {"progressHistory": CURVE}}}), encoding="utf-8")
    monkeypatch.setattr(research, "_runtime", _Runtime(), raising=False)
    captured = _save_meta_env(monkeypatch, tmp_path)
    research.save_meta(q, "Grid storage", 2)
    meta = json.loads((q / "meta.json").read_text(encoding="utf-8"))
    assert meta["agents"]["chatgpt"]["progressHistory"] == CURVE
    assert captured["agents"]["chatgpt"]["progressHistory"] == CURVE


def test_a_live_ring_still_wins_over_what_was_persisted(monkeypatch, tmp_path):
    """⭐ ACCEPT POLARITY, and the reason the carry-forward is gated on an EMPTY
    rebuild: an agent that ran again this attempt has a newer curve, and the
    fallback must never hold the old one in front of it."""
    q = _queue(tmp_path, docs=["chatgpt"])
    (q / "meta.json").write_text(json.dumps(
        {"agents": {"chatgpt": {"progressHistory": CURVE}}}), encoding="utf-8")
    fresh = [{"t": 1, "chars": 1}, {"t": 2, "chars": 2}]
    monkeypatch.setattr(research, "_runtime", _Runtime(history={"chatgpt": fresh}),
                        raising=False)
    captured = _save_meta_env(monkeypatch, tmp_path)
    research.save_meta(q, "Grid storage", 2)
    assert captured["agents"]["chatgpt"]["progressHistory"] == fresh


# ── the kept agent's row in links.json ────────────────────────────────────────
#
# ⛔⛔ A KEPT AGENT HANDED OVER A FILE AND NO LINK. `_p2_resume_plan` sets
# `url=""` — the conversation address is only a reattach key and a kept agent is
# not reattached — and the P2→P3 handoff read that as "this agent contributed
# nothing". So `links.json`, delivery.json's `research_links`, the "Links saved:"
# line and `/api/runs/{id}` listed only the agents that re-ran, while the kept
# agent's markdown went to NotebookLM as usual. The handoff's own docstring says
# the map exists so "produced no reports" and "refused its reports" are
# different records on disk; a kept agent was a third state reading like the
# first.

def _merged_with_a_fresh_gemini(kept):
    out = dict(kept)
    out["Gemini"] = {"status": "done", "text": REPORT["gemini"], "verified": True,
                     "url": "https://gemini.google.com/app/0f1e2d3c4b5a"}
    return out


def test_a_kept_agent_still_gets_its_row_in_the_links_map(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    q = _queue(tmp_path, done=["chatgpt"], docs=["chatgpt", "gemini"])
    _launch, kept = research._p2_resume_plan(q, ALL)
    research._build_phase2_to_phase3_handoff(_merged_with_a_fresh_gemini(kept), q)
    assert dict(research._runtime.p2_links_for_p3) == {
        "ChatGPT": research.in_app_document_url("chatgpt"),
        "Gemini": research.in_app_document_url("gemini")}
    # …and the file half, which was never the broken one.
    assert sorted(p.name for p in research._runtime.p2_md_files_for_p3) == [
        "chatgpt.md", "gemini.md"]


def test_a_kept_agent_the_sweep_refused_publishes_nothing(monkeypatch, tmp_path):
    """⛔ ACCEPT POLARITY. The off-topic sweep runs over the MERGED results, kept
    legs included, and a refused leg is not a source however it got here."""
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    q = _queue(tmp_path, done=["chatgpt"], docs=["chatgpt"])
    _launch, kept = research._p2_resume_plan(q, ALL)
    kept["ChatGPT"]["off_topic_rejected"] = True
    research._build_phase2_to_phase3_handoff(kept, q)
    assert dict(research._runtime.p2_links_for_p3) == {}
    assert list(research._runtime.p2_md_files_for_p3) == []


def test_a_leg_that_never_reached_a_page_still_publishes_nothing(
        monkeypatch, tmp_path):
    """⛔ ACCEPT POLARITY, and the whole reason the new arm asks `_restored`
    rather than "no url": an agent that never opened a tab has an empty address
    too, and publishing a row for it would skip both drop guards on the way."""
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    q = _queue(tmp_path, docs=["chatgpt"])
    research._build_phase2_to_phase3_handoff(
        {"ChatGPT": {"status": "done", "text": REPORT["chatgpt"], "url": "",
                     "verified": True}}, q)
    assert dict(research._runtime.p2_links_for_p3) == {}


# ── the wiring inside run_pipeline, by AST shape ──────────────────────────────

def _tree(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _blocks(tree):
    """Every statement list in the tree, with the node that owns it."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield node, block


def _names(target):
    if isinstance(target, ast.Tuple):
        return [e.id for e in target.elts if isinstance(e, ast.Name)]
    return []


def _is_call(node, func):
    if isinstance(node, ast.Expr):
        node = node.value
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return ast.unparse(f) == func


def _phase2_call():
    """The one place `run_pipeline` runs Phase 2."""
    for owner, block in _blocks(_tree(research.run_pipeline)):
        for i, st in enumerate(block):
            if (isinstance(st, ast.Assign)
                    and _names(st.targets[0]) == ["results", "_p2_user_skipped", "_p2_stopped"]
                    and isinstance(st.value, ast.Await)
                    and _is_call(st.value.value, "_p2_run_with_resume")):
                return block, i, st.value.value
    raise AssertionError("run_pipeline does not run Phase 2 through _p2_run_with_resume")


def test_run_pipeline_runs_the_phase_through_the_helper_and_returns_on_a_stop():
    """⛔ THE CONSUMER CALLS THE DECISION UNCONDITIONALLY, and the decision
    itself is executed by the tests below rather than read. This pin is what is
    left over once the plan, the attempts, the merge and the safety filter live
    in `_p2_run_with_resume`: the call, the stop, and the promise that nothing
    stands between the phase and the sink."""
    block, i, call = _phase2_call()
    assert [ast.unparse(a) for a in call.args] == [
        "queue_dir", "enabled_agents", "research_brief"]
    kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert kw["run_attempt"] == "_p2_attempt"
    assert kw["soft_decision_exc"] == "_PhaseSoftDecision"
    # A person who stopped the run at the timeout card ends the pipeline here.
    nxt = block[i + 1]
    assert isinstance(nxt, ast.If) and ast.unparse(nxt.test) == "_p2_stopped"
    assert isinstance(nxt.body[0], ast.Return) and nxt.body[0].value is None
    # ⛔ The off-topic sweep judges exactly what the helper returned, and the
    # roster stays the roster — a trimmed `enabled_agents` would drop the kept
    # reports out of the phase_start emits and out of the helper's own filter.
    rest = block[i + 1:]
    sweep = next(j for j, s in enumerate(rest)
                 if isinstance(s, ast.Assign) and "apply_off_topic_sweep" in ast.unparse(s.value))
    for s in rest[:sweep]:
        for n in ast.walk(s):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                assert not ({"results", "enabled_agents"}
                            & {ast.unparse(t) for t in targets}), ast.unparse(n)


def test_the_main_call_launches_what_it_is_handed_and_the_deliberate_reruns_do_not():
    tree = _tree(research.run_pipeline)
    calls = [n for n in ast.walk(tree) if _is_call(n, "run_phase2")]
    lam = [n.body for n in ast.walk(tree) if isinstance(n, ast.Lambda)
           and _is_call(n.body, "run_phase2")]
    assert len(lam) == 1
    kw = {k.arg: ast.unparse(k.value) for k in lam[0].keywords}
    # `_launch` is the attempt runner's own parameter, and only the helper calls
    # it — so the roster cannot reach `run_phase2` through this site at all.
    assert kw["enabled_agents"] == "_launch"
    attempt = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "_p2_attempt")
    assert [a.arg for a in attempt.args.args] == ["_launch", "_brief"]
    # The pause's Resume-with-input and the Phase-3 gate's Retry re-run on
    # purpose, and keep their own full rosters.
    others = sorted({ast.unparse(k.value) for c in calls if c not in lam
                     for k in c.keywords if k.arg == "enabled_agents"})
    assert others == ["_retry_enabled", "enabled_agents_now"]


# ── the phase itself, RUN: plan → attempts → merge → filter ───────────────────


class _Soft(Exception):
    """Stands in for `run_pipeline`'s own `_PhaseSoftDecision`, which is defined
    inside that coroutine and handed to the helper as a parameter."""

    def __init__(self, decision):
        super().__init__(decision)
        self.decision = decision


class _Controls:
    def __init__(self, extra=()):
        self.extra = list(extra)

    def pop_extra_context(self):
        return self.extra.pop(0) if self.extra else ""


BRIEF = "research this: the grid"


def _drive_the_phase(monkeypatch, q, enabled, outcomes, *, extra=(), decisions=()):
    """The REAL `_p2_run_with_resume`, with a fake attempt runner.

    `outcomes` is one entry per attempt — a results dict to return, an exception
    to raise, or a callable that does something first and returns one."""
    launched, events = [], []
    decisions = list(decisions)
    rt = _Runtime()
    monkeypatch.setattr(research, "_runtime", rt, raising=False)
    monkeypatch.setattr(research, "_controls", _Controls(extra), raising=False)
    monkeypatch.setattr(research, "emit_event", lambda t, **k: events.append((t, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")

    async def _attempt(launch, brief):
        launched.append((list(launch), brief))
        # In the same list as the emits, so "announced before the phase ran" is
        # a thing a test can read rather than a thing a comment claims.
        events.append(("attempt", {"launch": list(launch)}))
        out = outcomes[len(launched) - 1]
        if callable(out) and not isinstance(out, BaseException):
            out = out()
        if isinstance(out, BaseException):
            raise out
        return dict(out)

    async def _hard():
        return decisions.pop(0) if decisions else "stop"

    got = asyncio.run(research._p2_run_with_resume(
        q, enabled, BRIEF, run_attempt=_attempt, soft_decision_exc=_Soft,
        hard_timeout_decision=_hard))
    return got, launched, events, rt


def _fresh(*keys):
    """What `run_phase2` hands back for the agents it actually ran."""
    return {research._agent_display_name(k): {"status": "done", "text": REPORT[k]}
            for k in keys}


def test_the_phase_launches_only_the_unfinished_and_hands_back_the_kept_with_them(
        tmp_path, monkeypatch):
    """⛔⛔ THE WHOLE POINT, EXECUTED. Gemini finished before the crash; it is not
    launched again, and it is in the results the rest of the pipeline reads."""
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (results, skipped, stopped), launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_fresh("chatgpt", "claude")])
    assert [lst for lst, _b in launched] == [["chatgpt", "claude"]]
    assert sorted(results) == ["ChatGPT", "Claude", "Gemini"]
    assert results["Gemini"]["_restored"] is True
    assert results["Gemini"]["text"] == REPORT["gemini"]
    assert (skipped, stopped) == (False, False)
    # ⛔ And it was announced BEFORE the phase ran, not at the end of it: the
    # resume's full `phase_restart` has just re-seeded its row on the web, and
    # the agents that did launch have the rest of the phase to run.
    assert [(t, k.get("agent") or k.get("launch")) for t, k in events] == [
        ("link_extracted", "gemini"),
        ("agent_progress", "gemini"),
        ("attempt", ["chatgpt", "claude"])]
    assert [k["status"] for t, k in events if t == "agent_progress"] == ["complete"]


def test_a_fresh_run_launches_the_whole_roster(tmp_path, monkeypatch):
    q = _queue(tmp_path, docs=ALL)
    (results, _s, _st), launched, _ev, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_fresh(*ALL)])
    assert [lst for lst, _b in launched] == [ALL]
    assert sorted(results) == ["ChatGPT", "Claude", "Gemini"]
    assert not any(r.get("_restored") for r in results.values())


def test_a_soft_timeout_retry_buys_the_whole_phase_again(tmp_path, monkeypatch):
    """A person's Retry means the WHOLE phase: the launch widens back to the
    roster and the kept report is dropped, so Gemini's tile is the new run's."""
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (results, skipped, stopped), launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_Soft("retry"), _fresh(*ALL)])
    assert [lst for lst, _b in launched] == [["chatgpt", "claude"], ALL]
    assert sorted(results) == ["ChatGPT", "Claude", "Gemini"]
    assert not any(r.get("_restored") for r in results.values())
    assert ("phase_restart", {"phase": 2, "reason": "user_retry_after_soft_timeout"}) in events
    assert (skipped, stopped) == (False, False)


def test_a_soft_timeout_skip_ends_the_phase_with_nothing(tmp_path, monkeypatch):
    """⛔ AND THE KEPT RESULTS GO WITH IT. A phase the person SKIPPED must not be
    recorded complete off the back of a report the last attempt left on disk —
    `phase_skipped` has already said otherwise."""
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (results, skipped, stopped), launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_Soft("skip")])
    assert results == {}
    assert (skipped, stopped) == (True, False)
    assert len(launched) == 1
    assert ("phase_skipped", {"phase": 2, "reason": "user_skip_after_soft_timeout"}) in events


def test_a_soft_decision_that_is_neither_surfaces(tmp_path, monkeypatch):
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    with pytest.raises(_Soft):
        _drive_the_phase(monkeypatch, q, ALL, [_Soft("wait")])


def test_the_legacy_timeout_cards_retry_buys_the_whole_phase_again(tmp_path, monkeypatch):
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (results, _s, _st), launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [asyncio.TimeoutError(), _fresh(*ALL)], decisions=["retry"])
    assert [lst for lst, _b in launched] == [["chatgpt", "claude"], ALL]
    assert not any(r.get("_restored") for r in results.values())
    assert ("phase_restart", {"phase": 2, "reason": "user_retry_after_timeout"}) in events


def test_the_legacy_timeout_cards_skip_ends_the_phase_with_nothing(tmp_path, monkeypatch):
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (results, skipped, stopped), _launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [asyncio.TimeoutError()], decisions=["skip"])
    assert results == {}
    assert (skipped, stopped) == (True, False)
    assert ("phase_skipped", {"phase": 2, "reason": "user_skip_after_timeout"}) in events


def test_a_stop_at_the_timeout_card_tells_the_caller_to_end_the_run(tmp_path, monkeypatch):
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (_results, _skipped, stopped), _launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [asyncio.TimeoutError()], decisions=["stop"])
    assert stopped is True
    assert ("pipeline_stopped", {"phase": 2, "reason": "user_stop_after_timeout"}) in events


def test_new_input_mid_phase_re_runs_the_whole_phase_with_it(tmp_path, monkeypatch):
    q = _queue(tmp_path, done=["gemini"], docs=ALL)

    def _asks_for_a_restart():
        research._runtime.restart_requested = True
        return _fresh("chatgpt", "claude")

    (results, _s, _st), launched, events, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_asks_for_a_restart, _fresh(*ALL)],
        extra=["also cover permitting"])
    assert [lst for lst, _b in launched] == [["chatgpt", "claude"], ALL]
    assert "also cover permitting" in launched[1][1]
    assert "ADDITIONAL USER CONTEXT (restart #1)" in launched[1][1]
    assert launched[0][1] == BRIEF  # the first attempt got the brief as handed in
    assert not any(r.get("_restored") for r in results.values())
    assert [k for t, k in events if t == "phase_restart"] == [
        {"phase": 2, "reason": "mid_phase_input_on_resume",
         "chars": len("also cover permitting"), "attempt": 1}]


def test_a_restart_asked_for_with_no_input_does_not_re_run(tmp_path, monkeypatch):
    q = _queue(tmp_path, done=["gemini"], docs=ALL)

    def _asks_for_a_restart():
        research._runtime.restart_requested = True
        return _fresh("chatgpt", "claude")

    (results, _s, _st), launched, _ev, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_asks_for_a_restart, _fresh(*ALL)])
    assert len(launched) == 1
    assert results["Gemini"]["_restored"] is True


def test_three_restarts_are_the_cap(tmp_path, monkeypatch):
    q = _queue(tmp_path, docs=ALL)

    def _asks_for_a_restart():
        research._runtime.restart_requested = True
        return _fresh(*ALL)

    _got, launched, _ev, _rt = _drive_the_phase(
        monkeypatch, q, ALL, [_asks_for_a_restart] * 4, extra=["a", "b", "c", "d"])
    assert len(launched) == 3


def test_only_the_enabled_agents_come_out_of_the_phase(tmp_path, monkeypatch):
    """The safety filter, with a kept agent in the results: it keeps the ROSTER,
    never the launch list, or every kept report would be thrown away here."""
    q = _queue(tmp_path, done=["gemini"], docs=ALL)
    (results, _s, _st), launched, _ev, _rt = _drive_the_phase(
        monkeypatch, q, ["gemini", "claude"], [_fresh("claude", "chatgpt")])
    assert [lst for lst, _b in launched] == [["claude"]]
    assert sorted(results) == ["Claude", "Gemini"]


def test_the_safety_filter_reads_the_display_names_the_phase_writes():
    r = {"ChatGPT": {"text": "a"}, "Gemini": {"text": "b"}}
    assert sorted(research._p2_only_enabled(r, ["gemini"])) == ["Gemini"]
    assert sorted(research._p2_only_enabled(r, ["ChatGPT"])) == ["ChatGPT"]
    # No roster configured at all is not "drop everything".
    assert research._p2_only_enabled(r, []) == r


def test_the_finalize_resave_asks_the_helper():
    """⭐ Wave 10.9, 2026-09-22 — the finalize re-save moved out of
    `run_pipeline` into `_p2_persist_reports` (so a test could drive the writes
    against a fake Firestore) and the loop moved with it, unchanged. Re-pointed,
    not relaxed: the gate is still the helper call, and it is still the loop's
    first statement."""
    tree = _tree(research._p2_persist_reports)
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and ast.unparse(n.iter) == "results.items()"
             and "save_document_to_firestore(_agent_lc" in ast.unparse(n)]
    assert len(loops) == 1
    assert isinstance(loops[0].body[0], ast.If)
    assert ast.unparse(loops[0].body[0].test) == "_p2_needs_resave(r)"
