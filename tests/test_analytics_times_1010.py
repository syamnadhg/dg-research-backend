"""Analytics shows phase and agent times even for runs nobody watched.

Two holes, both in `save_meta`, both visible only when no browser tab was open
— because an open tab writes its own copy of each number and hides them.

⛔⛔ 1. PHASE 0 NEVER ENDED. `save_meta` is first called at the END of phase 1,
and it backfills every earlier phase as `{completedAt: None, durationSec: 0}`,
closing only the phase it was called for. So phase 0 never got an end, and phase
1 — which took its start from the run's start — silently carried phase 0's whole
span. The web's timeline module records exactly this and prints "—" for it
rather than invent a number (dg-research `src/lib/analytics-timeline.ts`).

⭐ A PHASE ENDS WHEN THE NEXT ONE STARTS. The phase-1 saves now say when phase 1
began, and that instant closes phase 0 and opens phase 1. It is the one open row
whose own start is real (the run's start); every other row `save_meta` leaves
open is a backfill whose start is a guess, so closing it would print a duration
for a phase that may never have run — the invention the web refuses.

⛔⛔ 2. EACH AGENT'S TIME REACHED THE DISK ONLY. The phase-2 block wrote
`completionTimeSec` into meta.json AFTER `save_meta` had already sent the agents
to the cloud carrying whatever meta.json held before — 0 on a fresh run. Only an
open tab wrote the real time, so an unwatched run's analytics said "—" for every
agent. `save_meta` now takes the phase's results and puts each time into the
one entry it builds, so the disk and the cloud get the same number in the same
write, next to every sibling field that write already carried.

▶ EXECUTED: the REAL `save_meta`, against a cloud double that applies each
`update()` the way Firestore does (`conftest.apply_firestore_update`). The two
call sites inside `run_pipeline` — a 5,000-line coroutine nothing can drive this
far — are pinned by their parse tree, and their argument expressions are
EVALUATED, not read.

⚠ NOT FIXED HERE, and said so rather than implied: phase 3 still has no
`save_meta` at a normal finish (only on a stop), so its row is still the web's
status-only stub. That call belongs at the phase-3 hand-off, which another round
is editing, and after the hand-off the machine must not write the phases array
at all — the cloud owns phases 4 and 5.
"""
import ast
import inspect
import json
import os
import textwrap
import time

import pytest

import research
from conftest import apply_firestore_update

TOPIC = "Grid storage"
RID = "chat_1758400000000_1"


class _Cloud:
    """One research document; `update()` applied the way Firestore applies it."""

    def __init__(self):
        self.data = {}
        self.writes = 0

    def collection(self, _name):
        return self

    def document(self, _id):
        return self

    def update(self, patch):
        self.writes += 1
        apply_firestore_update(self.data, patch)


@pytest.fixture
def cloud(monkeypatch):
    c = _Cloud()
    monkeypatch.setattr(research, "_firebase_db", c)
    monkeypatch.setattr(research, "_fb_uid", "uid-1")
    monkeypatch.setattr(research, "_fb_research_id", RID)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "_agent_status_by_rid", {}, raising=False)
    monkeypatch.setattr(research, "_phase_status_by_rid", {}, raising=False)
    monkeypatch.setattr(research, "_runtime", research.PipelineRuntime())
    return c


@pytest.fixture
def run_dir(tmp_path):
    """A run folder whose creation files are backdated: the run began 30 min ago."""
    d = tmp_path / "Grid_storage_20260923_120000"
    (d / "documents").mkdir(parents=True)
    started = time.time() - 1800
    for name in ("config.json", "owner.json"):
        p = d / name
        p.write_text("{}")
        os.utime(p, (started, started))
    return d, int(started * 1000)


def _meta(d):
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _report(d, platform):
    body = ("## Findings\n\nTransmission, not generation, is the binding "
            "constraint in most of the markets studied, and permitting sets "
            "its pace across every region we looked at.\n")
    (d / "documents" / f"{platform}.md").write_text(body, encoding="utf-8")


def _result(secs, status="done"):
    """One entry of phase 2's `results`, keyed by the display name."""
    return {"status": status, "text": "report", "elapsed_sec": secs}


# ══ 1. phase rows ═══════════════════════════════════════════════════════
def test_every_phase_the_machine_closes_has_an_end_and_a_duration(run_dir, cloud):
    """⛔⛔ THE DEFECT, over the saves a real run makes: phase 1's end (with its
    start), phase 2's end, and the phase-3 save a stop makes. Against the code
    before this wave phase 0 came out `completedAt: None`, `durationSec: 0`."""
    d, run_start = run_dir
    p1_start = run_start + 90_000                  # phase 0 took 90 seconds
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=p1_start)
    research.save_meta(d, TOPIC, 2)
    research.save_meta(d, TOPIC, 3, status="stopped")

    rows = _meta(d)["phases"]
    assert [r["phase"] for r in rows] == [0, 1, 2, 3]
    for r in rows:
        assert isinstance(r["completedAt"], int), f"phase {r['phase']} has no end"
        assert r["completedAt"] >= r["startedAt"], f"phase {r['phase']} ends before it starts"
        assert r["durationSec"] == (r["completedAt"] - r["startedAt"]) // 1000
    # the cloud row is the same array — it is what the analytics page reads
    assert cloud.data["phases"] == rows


def test_phase_zero_ends_when_phase_one_starts(run_dir, cloud):
    d, run_start = run_dir
    p1_start = run_start + 90_000
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=p1_start)
    p0, p1 = _meta(d)["phases"][:2]
    assert p0["startedAt"] == run_start
    assert p0["completedAt"] == p1_start
    assert p0["durationSec"] == 90


def test_phase_one_no_longer_carries_phase_zeros_span(run_dir, cloud):
    """⛔ The other half of the same hole: with no end for phase 0, phase 1 began
    at the run's start and its duration silently included all of phase 0."""
    d, run_start = run_dir
    p1_start = run_start + 90_000
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=p1_start)
    p1 = _meta(d)["phases"][1]
    assert p1["startedAt"] == p1_start
    assert p1["durationSec"] == (p1["completedAt"] - p1_start) // 1000


def test_phase_two_still_chains_off_phase_one(run_dir, cloud):
    """The arithmetic that was already right stays right."""
    d, run_start = run_dir
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=run_start + 90_000)
    p1_end = _meta(d)["phases"][1]["completedAt"]
    research.save_meta(d, TOPIC, 2)
    assert _meta(d)["phases"][2]["startedAt"] == p1_end


# ── accept polarity: nothing is invented ────────────────────────────────
def test_without_a_start_phase_zero_stays_open_rather_than_invented(run_dir, cloud):
    """⭐ A save that does not know when its phase began changes nothing — the
    web prints "—" for an open row, which is true; a closed row with a made-up
    end would not be."""
    d, _ = run_dir
    research.save_meta(d, TOPIC, 1, summary="x")
    p0 = _meta(d)["phases"][0]
    assert p0["completedAt"] is None and p0["durationSec"] == 0


def test_a_backfilled_phase_is_not_closed_by_the_next_ones_start(run_dir, cloud):
    """⛔ Phase 1 skipped: the first save is phase 2's, and rows 0 and 1 are both
    backfills. Row 1's start is a guess, so a "duration" for it would be a phase
    that may never have run wearing phase 0's span — and row 0's end is not
    phase 2's start either. Both stay open."""
    d, run_start = run_dir
    p2_start = run_start + 120_000
    research.save_meta(d, TOPIC, 2, started_ms=p2_start)
    rows = _meta(d)["phases"]
    assert rows[0]["completedAt"] is None
    assert rows[1]["completedAt"] is None
    assert rows[2]["startedAt"] == p2_start, "the phase that DID say when it began is believed"


@pytest.mark.parametrize("bad", [
    pytest.param("before", id="before-the-run-began"),
    pytest.param("future", id="in-the-future"),
    pytest.param(True, id="a-bool"),
    pytest.param("123", id="a-string"),
])
def test_a_start_that_cannot_be_true_is_ignored(run_dir, cloud, bad):
    """A clock disagreement is not a duration. Each of these would print a
    negative or nonsense span if believed."""
    d, run_start = run_dir
    started = {"before": run_start - 60_000,
               "future": int(time.time() * 1000) + 3_600_000}.get(bad, bad)
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=started)
    p0, p1 = _meta(d)["phases"][:2]
    assert p0["completedAt"] is None
    assert p1["startedAt"] == run_start


def test_a_closed_phase_is_never_rewritten(run_dir, cloud):
    """A repeat save (a stop right after phase 1 re-saves phase 1) must not move
    boundaries that were already recorded."""
    d, run_start = run_dir
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=run_start + 90_000)
    before = _meta(d)["phases"][:2]
    research.save_meta(d, TOPIC, 1, status="stopped", started_ms=run_start + 400_000)
    assert _meta(d)["phases"][:2] == before


# ══ 2. each agent's time, in the cloud ══════════════════════════════════
RESULTS = {"ChatGPT": _result(1510), "Gemini": _result(905), "Claude": _result(1820)}


def test_an_unwatched_runs_cloud_row_carries_each_agents_time(run_dir, cloud):
    """⛔⛔ THE DEFECT. No tab, so nothing but this machine writes the record.
    Against the code before this wave every `completionTimeSec` here was 0."""
    d, run_start = run_dir
    for p in ("chatgpt", "gemini", "claude"):
        _report(d, p)
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=run_start + 90_000)
    research.save_meta(d, TOPIC, 2, agent_results=RESULTS)

    agents = cloud.data["agents"]
    assert agents["chatgpt"]["completionTimeSec"] == 1510
    assert agents["gemini"]["completionTimeSec"] == 905
    assert agents["claude"]["completionTimeSec"] == 1820
    # …and the disk holds the same numbers, from the same write
    disk = _meta(d)["agents"]
    assert {k: disk[k]["completionTimeSec"] for k in disk} == {
        "chatgpt": 1510, "gemini": 905, "claude": 1820}


def test_the_time_rides_beside_every_sibling_field(run_dir, cloud):
    """⛔ The lesson recorded at `_merge_field_paths`: a write that carries one
    field of an agent's entry as a map erased the rest of it. This one is the
    whole entry the rebuild already sends — so the report's own fields are all
    still there beside the time."""
    d, _ = run_dir
    _report(d, "claude")
    research.save_meta(d, TOPIC, 2, agent_results={"Claude": _result(1820)})
    claude = cloud.data["agents"]["claude"]
    assert claude["completionTimeSec"] == 1820
    for field in ("sources", "sourceUrls", "sections", "outputChars", "findings",
                  "searches", "observedSources", "progressHistory"):
        assert field in claude, f"the agent's {field} is missing beside its time"
    assert claude["outputChars"] > 0


def test_an_agent_that_died_without_a_report_still_says_how_long_it_ran(run_dir, cloud):
    """⭐ It ran for 25 minutes and produced nothing. Before, that time existed
    on disk only; the rebuild never made it an entry because there was no
    report to build one from."""
    d, _ = run_dir
    research.save_meta(d, TOPIC, 2,
                       agent_results={"Gemini": _result(1500, status="error")})
    assert cloud.data["agents"]["gemini"]["completionTimeSec"] == 1500


def test_an_agent_that_never_ran_gets_no_entry(run_dir, cloud):
    """⛔ ACCEPT POLARITY. An agent the person switched off is absent from the
    results and must not be given a row of zeroes — the status re-stamp in the
    same function is careful about exactly this."""
    d, _ = run_dir
    _report(d, "claude")
    research.save_meta(d, TOPIC, 2, agent_results={"Claude": _result(1820),
                                                   "Gemini": _result(0)})
    assert "gemini" not in cloud.data["agents"]
    assert "chatgpt" not in cloud.data["agents"]


def test_a_kept_agent_with_no_new_time_keeps_the_one_it_had(run_dir, cloud):
    """⭐ A resume that keeps a finished agent may hand back no time for it this
    attempt. Its earlier time must survive — the old disk write set a zero here,
    and the next save sent that zero to the cloud."""
    d, _ = run_dir
    _report(d, "claude")
    (d / "meta.json").write_text(json.dumps(
        {"agents": {"claude": {"completionTimeSec": 1820}}}), encoding="utf-8")
    research.save_meta(d, TOPIC, 2, agent_results={"Claude": _result(0)})
    assert cloud.data["agents"]["claude"]["completionTimeSec"] == 1820


def test_a_time_that_is_not_a_number_is_ignored(run_dir, cloud):
    d, _ = run_dir
    _report(d, "claude")
    research.save_meta(d, TOPIC, 2, agent_results={"Claude": _result("soon"),
                                                   "Gemini": _result(True),
                                                   "Oracle": _result(99)})
    assert cloud.data["agents"]["claude"]["completionTimeSec"] == 0
    assert "gemini" not in cloud.data["agents"]
    assert "oracle" not in cloud.data["agents"]


# ══ 3. the call sites inside run_pipeline ═══════════════════════════════
def _saves(phase):
    """Every ONGOING `save_meta(queue_dir, topic, <phase>, …)` in run_pipeline.

    A stop or pause save carries `status=` and is not the save this wave is
    about."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(research.run_pipeline)))
    out = []
    for c in ast.walk(tree):
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "save_meta" and len(c.args) >= 3
                and isinstance(c.args[2], ast.Constant) and c.args[2].value == phase
                and not any(k.arg == "status" for k in c.keywords)):
            out.append(c)
    return out


def test_both_phase_one_saves_say_when_phase_one_began():
    """⛔⛔ A TESTED WRITER IS NOT A TESTED CALLER. Every test above passes with
    both saves still silent about their start, and then no run ever closes
    phase 0. The expression is EVALUATED against a known start, so a save that
    passed the wrong clock (or a second, not a millisecond) fails here."""
    calls = _saves(1)
    assert len(calls) == 2, "the brief-from-file and the generated-brief saves"
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert "started_ms" in kw, f"line {c.lineno}: phase 1's save does not say when it began"
        got = eval(compile(ast.Expression(kw["started_ms"]), "<call>", "eval"),
                   {"int": int, "_p1_start": 1_758_400_000.25})
        assert got == 1_758_400_000_250


def test_the_phase_two_save_hands_over_the_results():
    calls = _saves(2)
    assert len(calls) == 1
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "agent_results" in kw, "phase 2's save never sees how long each agent took"
    assert isinstance(kw["agent_results"], ast.Name) and kw["agent_results"].id == "results"
