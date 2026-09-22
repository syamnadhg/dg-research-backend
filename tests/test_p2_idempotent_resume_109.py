"""A crash retry re-runs only the Phase-2 agents that had not finished.

⛔⛔ THE DEFECT (wave 10.9, D5). An interrupted Phase 2 resumes through
`run_phase2`, and it launched EVERY enabled agent from zero. `detect_resume_phase`
said so in its own comment — "re-running P2 re-extracts ALL enabled agents from
scratch" — and priced it at "a few extra minutes". It was every finished Deep
Research bought again on each silent relaunch after a Chrome death (up to
BROWSER_CRASH_MAX_RETRIES of them; a daemon restart resumes the same way), with
the finished tile flipped back to "running".

⭐ THE FIX HAS FOUR PARTS, AND EACH ONE IS EXECUTED HERE:
  * `extract_and_record_agent` writes a durable completion record in the ONE
    branch that announces `complete` — driven end to end below;
  * every launch in `run_phase2` takes its agent back out of the record — driven
    below up to the moment the agent would open;
  * `_p2_resume_plan` keeps an agent only with BOTH the record and its report;
  * `_p2_announce_restored` re-ticks the kept agent's tile, which the resume's
    full `phase_restart` has just re-seeded on the web.

The wiring inside `run_pipeline` — a 5,000-line coroutine that cannot be driven
here — is pinned by AST SHAPE, not by name: each statement must be a direct,
unconditional child of the block it belongs to, in order, so `if False:` or a
moved line fails the pin.
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
    def __init__(self):
        self.agent_findings = {}
        self.agent_progress_snapshots = {}


def _drive_the_extractor(monkeypatch, tmp_path, report, *, saved_ok=True,
                         research_id="rid-1"):
    """The REAL `extract_and_record_agent`, with only the browser, the network
    and Firestore stubbed."""
    async def _extract(page, **kw):
        return report

    async def _rehost(text, label=None, **kw):
        return text

    async def _save(doc_type, content, name=None, **kw):
        return saved_ok

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(research, "_runtime", _Runtime(), raising=False)
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


def _plan_block():
    for owner, block in _blocks(_tree(research.run_pipeline)):
        for i, st in enumerate(block):
            if (isinstance(st, ast.Assign) and _names(st.targets[0]) == ["_p2_launch", "_p2_restored"]
                    and _is_call(st.value, "_p2_resume_plan")):
                return block, i, st
    raise AssertionError("the Phase-2 plan is not assigned anywhere in run_pipeline")


def test_the_plan_is_made_announced_and_merged_unconditionally_in_order():
    block, i, st = _plan_block()
    assert [ast.unparse(a) for a in st.value.args] == ["queue_dir", "enabled_agents"]
    # Announced at once, as the very next statement.
    assert ast.unparse(block[i + 1]) == "_p2_announce_restored(_p2_restored)"
    rest = block[i + 1:]
    loop = next(j for j, s in enumerate(rest)
                if isinstance(s, ast.For) and ast.unparse(s.target) == "_p2_attempt")
    merge = next(j for j, s in enumerate(rest)
                 if ast.unparse(s) == "results.update(_p2_restored)")
    sweep = next(j for j, s in enumerate(rest)
                 if isinstance(s, ast.Assign) and "apply_off_topic_sweep" in ast.unparse(s.value))
    # After the attempts, ahead of the off-topic sweep and everything it guards.
    assert loop < merge < sweep
    # ⛔ The roster is never trimmed to the launch list: the safety filter below
    # keeps only `enabled_agents`, so a trimmed roster throws the kept reports away.
    for s in rest[:sweep]:
        for n in ast.walk(s):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                assert "enabled_agents" not in {ast.unparse(t) for t in targets}, ast.unparse(n)


def test_the_main_call_launches_the_plan_and_the_deliberate_reruns_do_not():
    tree = _tree(research.run_pipeline)
    calls = [n for n in ast.walk(tree) if _is_call(n, "run_phase2")]
    lam = [n.body for n in ast.walk(tree) if isinstance(n, ast.Lambda)
           and _is_call(n.body, "run_phase2")]
    assert len(lam) == 1
    kw = {k.arg: ast.unparse(k.value) for k in lam[0].keywords}
    assert kw["enabled_agents"] == "_p2_launch"
    # The pause's Resume-with-input and the Phase-3 gate's Retry re-run on
    # purpose, and keep their own full rosters.
    others = sorted({ast.unparse(k.value) for c in calls if c not in lam
                     for k in c.keywords if k.arg == "enabled_agents"})
    assert others == ["_retry_enabled", "enabled_agents_now"]


def test_a_persons_retry_skip_or_new_input_decides_for_the_whole_phase():
    """A Retry or Skip on the soft-timeout card, the legacy timeout card, and a
    restart with new input all mean the WHOLE phase, as they always did: each
    widens the launch back to the roster and drops the kept results, first
    thing, before any decision is acted on."""
    block, _i, _st = _plan_block()
    loop = next(s for s in block if isinstance(s, ast.For)
                and ast.unparse(s.target) == "_p2_attempt")
    reset = "_p2_launch, _p2_restored = (list(enabled_agents), {})"
    owners = []
    for owner, body in _blocks(loop):
        for j, s in enumerate(body):
            if ast.unparse(s) == reset:
                if isinstance(owner, ast.ExceptHandler):
                    owners.append(ast.unparse(owner.type))
                    # Before the handler acts on the decision.
                    first_if = next(k for k, x in enumerate(body) if isinstance(x, ast.If))
                    assert j < first_if
                else:
                    owners.append(type(owner).__name__)
    assert sorted(owners) == ["For", "_PhaseSoftDecision", "asyncio.TimeoutError"]
    # The restart site sits in the attempt loop itself, ahead of the restart emit.
    body = loop.body
    j = next(k for k, s in enumerate(body) if ast.unparse(s) == reset)
    emit = next(k for k, s in enumerate(body) if "mid_phase_input_on_resume" in ast.unparse(s))
    assert j < emit


def test_the_finalize_resave_asks_the_helper():
    tree = _tree(research.run_pipeline)
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and ast.unparse(n.iter) == "results.items()"
             and "save_document_to_firestore(_agent_lc" in ast.unparse(n)]
    assert len(loops) == 1
    assert isinstance(loops[0].body[0], ast.If)
    assert ast.unparse(loops[0].body[0].test) == "_p2_needs_resave(r)"
