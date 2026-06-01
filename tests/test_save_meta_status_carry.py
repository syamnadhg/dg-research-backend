"""Regression tests for #722 Bug A — save_meta() must not clobber the
per-agent / per-phase terminal `status`.

Background: save_meta() rebuilds the whole `agents` map + `phases` array and
propagates them with `_update_firestore_research({"agents": …, "phases": …})`,
which becomes a Firestore `.update()` — a whole-FIELD REPLACE, not a recursive
merge. That wiped the `status="complete"` that _write_agent/phase_terminal_status
had merge-written moments earlier, so chatgpt/claude/gemini icons never
green-ticked on reload. The fix records each terminal status synchronously in
module dicts (keyed by research id) and re-stamps it onto the rebuilt entries.

A cross-check found the first cut only stamped status for agents WITH a
markdown file — so skipped/errored agents (no .md) silently lost their status
(and worse, vanished from the map entirely under the whole-field replace).
These tests lock in: completed agents keep status, skipped/errored agents keep
status even without a .md, an agent with neither status nor .md stays absent
(config-disabled), and phases carry status.

Run:  pytest tests/test_save_meta_status_carry.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


_MD = (
    "# ChatGPT Deep Research\n\n## Findings\n\n"
    "Some substantial body text well over one hundred bytes so the "
    "size guard (st_size > 100) passes and the agent entry is rebuilt "
    "with real stats. https://example.com/a https://example.com/b\n"
)


@pytest.fixture
def meta_env(tmp_path, monkeypatch):
    """Isolate save_meta: a temp queue dir with documents/, a captured
    Firestore propagation, and fresh per-rid status dicts bound to a known
    research id."""
    (tmp_path / "documents").mkdir()
    captured = {}

    def _capture(updates):
        captured["updates"] = updates

    monkeypatch.setattr(research, "_update_firestore_research", _capture)
    monkeypatch.setattr(research, "_fb_research_id", "rid-test", raising=False)
    monkeypatch.setattr(research, "_fb_uid", "uid-test", raising=False)
    monkeypatch.setattr(research, "_agent_status_by_rid", {}, raising=False)
    monkeypatch.setattr(research, "_phase_status_by_rid", {}, raising=False)
    return tmp_path, captured


def _write_md(queue_dir, platform):
    (queue_dir / "documents" / f"{platform}.md").write_text(_MD, encoding="utf-8")


def test_completed_agents_with_md_carry_status(meta_env):
    queue_dir, captured = meta_env
    _write_md(queue_dir, "chatgpt")
    _write_md(queue_dir, "gemini")
    research._agent_status_by_rid["rid-test"] = {"chatgpt": "complete", "gemini": "complete"}

    research.save_meta(queue_dir, "Topic", 2)

    agents = captured["updates"]["agents"]
    assert agents["chatgpt"]["status"] == "complete"
    assert agents["gemini"]["status"] == "complete"
    # Real stats are still present alongside the status (not clobbered).
    assert agents["chatgpt"]["outputChars"] > 0
    assert "sourceUrls" in agents["chatgpt"]


def test_skipped_agent_without_md_keeps_status(meta_env):
    """The blocker the cross-check caught: a skipped/errored agent has no .md,
    so it never entered the stats rebuild — but its status must still be
    stamped (a minimal entry created) so the whole-field replace doesn't drop
    it from the map."""
    queue_dir, captured = meta_env
    _write_md(queue_dir, "chatgpt")
    research._agent_status_by_rid["rid-test"] = {
        "chatgpt": "complete",
        "claude": "skipped",   # no claude.md on disk
        "gemini": "errored",   # no gemini.md on disk
    }

    research.save_meta(queue_dir, "Topic", 2)

    agents = captured["updates"]["agents"]
    assert agents["chatgpt"]["status"] == "complete"
    assert agents["claude"]["status"] == "skipped"
    assert agents["gemini"]["status"] == "errored"


def test_agent_with_no_status_and_no_md_is_absent(meta_env):
    """A config-disabled agent never calls _write_*_terminal_status and has no
    .md — it must NOT get a spurious entry (no blanket status)."""
    queue_dir, captured = meta_env
    _write_md(queue_dir, "chatgpt")
    research._agent_status_by_rid["rid-test"] = {"chatgpt": "complete"}

    research.save_meta(queue_dir, "Topic", 2)

    agents = captured["updates"]["agents"]
    assert agents["chatgpt"]["status"] == "complete"
    assert "claude" not in agents
    assert "gemini" not in agents


def test_phases_carry_status(meta_env):
    queue_dir, captured = meta_env
    _write_md(queue_dir, "chatgpt")
    research._phase_status_by_rid["rid-test"] = {1: "complete", 2: "complete"}

    research.save_meta(queue_dir, "Topic", 2)

    phases = captured["updates"]["phases"]
    by_num = {p["phase"]: p for p in phases if isinstance(p, dict)}
    assert by_num[1]["status"] == "complete"
    assert by_num[2]["status"] == "complete"


def test_resume_preserves_prior_status_when_runtime_dict_empty(meta_env):
    """Fresh resumed worker: the per-rid dict is empty, but a prior process
    persisted status into meta.json — the rebuild must fall back to it."""
    queue_dir, captured = meta_env
    _write_md(queue_dir, "chatgpt")
    # Simulate a meta.json written by a prior (fixed) process carrying status.
    import json
    meta_seed = {"id": queue_dir.name, "agents": {"chatgpt": {"status": "complete"}}}
    (queue_dir / "meta.json").write_text(json.dumps(meta_seed), encoding="utf-8")
    # Runtime dict intentionally empty (fresh process).

    research.save_meta(queue_dir, "Topic", 2)

    agents = captured["updates"]["agents"]
    assert agents["chatgpt"]["status"] == "complete"
