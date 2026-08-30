"""A Phase-2 agent that produced nothing must not end the run looking finished.

WHAT WENT WRONG (owner report, 2026-08-29)

A run where Gemini died showed a GREEN TICK on the pipeline tile, "completed" in
the chat, and nothing streamed. The frontend half of that is fixed in the web
app; this file is the backend half, and the backend half is the reason the
frontend could not tell.

⛔⛔ `_write_agent_terminal_status(agent, "running", force=True)` IS STAMPED WHEN
AN AGENT IS OPENED. It is not a terminal status — the helper's own docstring says
so — but it is the value left on the root document by every path that ends
without writing a real one. Measured, several do: a crashed browser tab (a crash
calls no `fail_agent`, so nothing persists anything), a Stop mid-round-robin
(`partial` / `interrupted`), a leftover `paused`. The finalize loop that was
supposed to catch them wrote "complete" for four status values and had NO `else`,
under a comment claiming the rest "are written at their own emit sites".

⛔⛔ AND THE OFF-TOPIC SWEEP LEFT SOMETHING WORSE THAN A GAP — AN AFFIRMATIVELY
WRONG "complete". It runs a few lines before the finalize loop and flips a `done`
agent to `failed` when its report turns out to be about a different topic. But
"complete" was persisted when that agent finished, and nothing rewrote it. So a
report the backend DELIBERATELY REJECTED was reported to the user as a completed
agent, with a green tick, for as long as the record stood.

⛔ THE PHASE ITSELF HAD THE SAME SHAPE. `done_count` was computed and then used
for a log line and the resume marker; the phase status was written "complete"
unconditionally, so a Phase 2 in which every agent died still read as a finished
phase.

⭐ AND THE SOURCES OF A DEAD AGENT WERE THROWN AWAY TWICE. `agents[k].sources` is
a regex sweep over the agent's MARKDOWN FILE, so it exists only where a report
does; and the failure emit carried three keys, none of them the source list the
completion emit beside it carries off the same snapshot. Owner, 2026-08-29: "if
there are sources, let the narration show the sources and stuff."
"""
import inspect

import pytest

import research
from conftest import code_only


@pytest.fixture(scope="module")
def phase2_src() -> str:
    # ⛔ THE PHASE-2 FINALIZE BLOCK LIVES IN `run_pipeline`, NOT IN `run_phase2`.
    # `run_phase2` opens and polls the agents; the finalize — phase_complete, the
    # per-agent terminal statuses, the off-topic sweep — is inlined in the
    # pipeline. Reading the wrong one would make every assertion below vacuous.
    return code_only(inspect.getsource(research.run_pipeline))


@pytest.fixture(scope="module")
def save_meta_src() -> str:
    return code_only(inspect.getsource(research.save_meta))


@pytest.fixture(scope="module")
def extract_src() -> str:
    return code_only(inspect.getsource(research.extract_and_record_agent))


# ── 1. every agent ends terminal ────────────────────────────────────────────

def test_the_finalize_loop_now_has_an_else(phase2_src):
    """⛔⛔ THE HOLE. Four statuses got "complete" and everything else got
    nothing — so `partial`, `interrupted`, `browser_crashed` and `paused` all
    ended the run on the launch-time "running"."""
    assert 'reason="no_report_at_phase_end"' in phase2_src


def test_the_backstop_greys_rather_than_reddens(phase2_src):
    """We do not know that it FAILED — only that the run ended with nothing from
    it. "errored" would claim a diagnosis the run did not record."""
    i = phase2_src.index('reason="no_report_at_phase_end"')
    window = phase2_src[i - 400:i]
    assert '_write_agent_terminal_status(\n                    _ag_key_lc, "skipped"' in window \
        or '_ag_key_lc, "skipped",' in window


def test_the_backstop_never_overwrites_a_status_somebody_else_wrote(phase2_src):
    """⛔ `fail_agent` writes "errored" WITH A REASON, and the UI shows that
    reason as a sentence. A backstop that flattened it into a bare "skipped"
    would destroy the only explanation the user gets."""
    assert '_p2_recorded = _agent_status_by_rid.get(_fb_research_id, {}) or {}' in phase2_src
    assert 'if _p2_recorded.get(_ag_key_lc) in ("complete", "skipped", "errored"):' in phase2_src
    guard = phase2_src.index('if _p2_recorded.get(_ag_key_lc)')
    write = phase2_src.index('reason="no_report_at_phase_end"')
    assert guard < write, "the recorded-status guard must run before the backstop write"


def test_a_finished_agent_still_takes_the_fast_path_unchanged(phase2_src):
    assert 'if _ag_status in ("done", "complete", "completed", "done_partial"):' in phase2_src
    assert '_write_agent_terminal_status(_ag_key_lc, "complete")' in phase2_src


# ── 2. the off-topic rejection reaches the record ───────────────────────────

def test_an_off_topic_rejection_overwrites_the_stale_complete(phase2_src):
    """⛔⛔ THE WORST OF THE THREE, because it is not a missing write — it is a
    wrong one. The sweep blanks the text and flips the results status, and the
    root document went on saying "complete"."""
    assert 'if _ag_r.get("off_topic_rejected"):' in phase2_src
    assert 'reason="off_topic_rejected"' in phase2_src


def test_the_off_topic_write_is_forced(phase2_src):
    """A stale "complete" is already on the record, so an unforced write would be
    refused by nothing — but the marker exists precisely to override it, and
    `force=True` says that in the code rather than relying on the helper's
    guard happening not to cover this case."""
    i = phase2_src.index('reason="off_topic_rejected"')
    assert "force=True" in phase2_src[i - 200:i]


def test_the_off_topic_write_is_errored_not_skipped(phase2_src):
    """This one we DO know: the agent produced a report and we rejected it. That
    is a failure with a cause, and the user should be able to read the cause."""
    i = phase2_src.index('reason="off_topic_rejected"')
    assert '"errored"' in phase2_src[i - 200:i]


def test_the_sweep_still_sets_the_marker_this_reads(save_meta_src):
    """⛔ THE PRODUCER. `apply_off_topic_sweep` is what sets `off_topic_rejected`;
    if it stopped, the branch above would be unreachable and every test in this
    section would still pass."""
    sweep = code_only(inspect.getsource(research.apply_off_topic_sweep))
    assert 'r["off_topic_rejected"] = True' in sweep


# ── 3. the phase tells the truth about itself ───────────────────────────────

def test_a_phase_where_every_agent_died_is_not_complete(phase2_src):
    assert "if results and done_count == 0:" in phase2_src
    assert '_write_phase_terminal_status(2, "errored")' in phase2_src


def test_a_phase_where_some_agents_delivered_is_still_complete(phase2_src):
    """⛔ TWO OF THREE IS A FINISHED PHASE. Renaming that "errored" would be a
    second lie in the other direction — the per-agent record is where a single
    agent's fate belongs."""
    i = phase2_src.index("if results and done_count == 0:")
    tail = phase2_src[i:i + 900]
    assert '_write_phase_terminal_status(2, "complete")' in tail
    assert "else:" in tail


def test_an_empty_results_map_is_not_an_errored_phase(phase2_src):
    """Every agent disabled in config leaves `results` empty. That is a phase
    that had nothing to do, not one that failed."""
    assert "if results and done_count == 0:" in phase2_src
    assert "if done_count == 0:" not in phase2_src


# ── 4. the sources of a dead agent survive ──────────────────────────────────

def test_the_failure_emit_carries_the_sources(extract_src):
    """⛔⛔ IT CARRIED THREE KEYS AND NONE OF THEM WAS A SOURCE, while the
    completion emit twenty lines above carried the full set off the same
    snapshot."""
    assert "sourceUrls=_fail_urls," in extract_src
    assert "searches=int(_fail_snap.get(\"searches\", 0) or 0)," in extract_src
    assert "observedSources=int(_fail_snap.get(\"observed_sources\", 0) or 0)," in extract_src


def test_the_failure_emit_takes_the_larger_source_count(extract_src):
    """The counter and the url list are gathered by different readers and either
    can be the fuller one — the completion emit already does it this way."""
    assert 'sources=max(int(_fail_snap.get("sources", 0) or 0), len(_fail_urls)),' in extract_src


def test_the_failure_emit_caps_the_url_list(extract_src):
    """The shared ceiling, the same as every other source list on the wire."""
    assert "[:_SOURCE_LIST_CAP]" in extract_src
    i = extract_src.index("_fail_urls = ")
    assert "_SOURCE_LIST_CAP" in extract_src[i:i + 200]


def test_the_snapshot_read_cannot_take_the_run_down(extract_src):
    """It is a best-effort read of an in-memory ring, in the failure path of an
    agent that has already failed. An exception here would turn a bad agent into
    a bad run."""
    i = extract_src.index("_fail_snap = dict(")
    assert "try:" in extract_src[i - 120:i]
    assert "except Exception:" in extract_src[i:i + 300]


def test_save_meta_persists_sources_for_an_agent_with_no_report(save_meta_src):
    """⛔ THE DURABLE HALF. The emit above is session-volatile; this is what
    survives a reload."""
    assert 'if platform not in agents or "sources" not in agents.get(platform, {}):' in save_meta_src
    assert '_fallback_snap.get("source_urls", [])' in save_meta_src


def test_the_fallback_never_overwrites_a_real_report_s_citations(save_meta_src):
    """⛔ AN AGENT WITH A REPORT ALREADY HAS BETTER SOURCES — what the report
    actually CITED, not what the panel happened to show. `setdefault` and the
    presence check are both load-bearing."""
    i = save_meta_src.index('if platform not in agents or "sources" not in agents.get(platform, {}):')
    block = save_meta_src[i:i + 1600]
    assert '_entry.setdefault("sources", len(_fallback_urls))' in block
    assert '_entry["sources"] =' not in block
    assert '_entry.setdefault("sourceUrls", _fallback_urls)' in block


def test_the_fallback_url_list_keeps_the_shared_cap(save_meta_src):
    """⛔ THE CAP, ON THE SAME CEILING every other source list on the wire uses.
    Without it a pathological run puts an unbounded array on a root document that
    already carries three agents' worth — and this is the ONE source list that is
    written for agents nobody is watching, so nothing would notice."""
    i = save_meta_src.index("_fallback_urls = ")
    assert "[:_SOURCE_LIST_CAP]" in save_meta_src[i:i + 200]


def test_the_two_early_exits_in_the_finalize_loop_are_real(phase2_src):
    """⛔⛔ TWO DEFENCES, AND THE HARNESS PROVED THEY ARE REDUNDANT. `_p2_recorded`
    is a LIVE reference into `_agent_status_by_rid`, and the status helper records
    synchronously BEFORE its async write — so the guard below already catches what
    each `continue` prevents, and two mutants that removed a `continue` survived by
    being equivalent rather than by finding a gap.

    Redundancy is fine; SILENT redundancy is not. These are the readable defence —
    a person reading this loop should not have to know that a dict lookup three
    lines down is live to see why a finished agent is not re-stamped. Pinned so a
    tidy-up that removes them has to be a deliberate one."""
    fast = phase2_src.index('_write_agent_terminal_status(_ag_key_lc, "complete")')
    assert "continue" in phase2_src[fast:fast + 120]
    topic = phase2_src.index('f"topic, so it was not used.")')
    assert "continue" in phase2_src[topic:topic + 120]


def test_the_fallback_writes_nothing_for_an_agent_that_never_ran(save_meta_src):
    """A config-disabled platform has an empty snapshot. Writing a row of zeroes
    would invent an entry for something that never started — the exact thing the
    status re-stamp above it is careful not to do."""
    assert "if _fallback_urls or _fallback_searches or _fallback_observed:" in save_meta_src


def test_the_fallback_records_an_explicit_zero_character_count(save_meta_src):
    """⭐ The frontend reads a missing `outputChars` and a zero one the same way,
    but only the explicit zero says we LOOKED — and it is what stops these
    sources being mistaken for a report that was produced."""
    assert '_entry.setdefault("outputChars", 0)' in save_meta_src


def test_the_status_restamp_still_runs_first(save_meta_src):
    """⛔ ORDER. The status re-stamp is what puts a minimal entry there for a
    skipped agent; the source fallback checks `platform not in agents`, so
    running it first would change which agents it thinks are missing."""
    i_status = save_meta_src.index('agents.setdefault(platform, {})["status"] = _astat')
    i_sources = save_meta_src.index('if platform not in agents or "sources" not in agents.get(platform, {}):')
    assert i_status < i_sources
