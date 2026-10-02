"""Wave 15 (10-02) — a crash that recovers leaves no alert behind.

⛔⛔ 10-01, research computer (logs 3NH9Q7CH). Chrome died during ChatGPT's
extraction at 11:19:09; the attempt put up "Couldn't read ChatGPT's report",
the crash retry relaunched Chrome at 11:19:17 and carried on — and the card
stayed up for fifteen minutes, until ChatGPT finished again in the retry and its
completion took it down. The attempt that raised it was gone; its Retry and Skip
were about a browser that no longer existed. 10-02 (CJFYMAB1) shows the same:
"[pending-decision] persisted … phase2_agent_chatgpt_error" at 00:12:38, the
crash at 00:13:41, and "Retracted the stale failure card" only at 00:26:42.

⭐ So the crash's own retry takes down every Phase-2 card its crashed attempt
raised for this research, as soon as its record is bound.

⭐ DRIVEN THROUGH THE REAL `run_pipeline`, twice: the attempt that raises its
cards with the REAL `fail_agent` and then loses Chrome, and the retry it hands
its arguments to. Only the edges are stubbed — Chrome, Firestore's writes, the
app's event stream. Every case that leaves a card alone sits beside one that
takes a card down, so code that does nothing is red too.

Run:  pytest tests/test_w15_crash_cards_1002.py -v
"""
import asyncio

import pytest

import research

UID = "uid-w15-cards-0000000000001"
RID = "chat_1790923944235_2"
OTHER_RID = "chat_1790923091895_1"
BRIEF = "# Research Brief\n\n## Objective\nSaint Bernard health.\n" * 4
CG_CARD = ("chatgpt", "Couldn't read ChatGPT's report", 2)
CL_CARD = ("claude", "Couldn't read Claude's report", 2)


class _FakeBrowser:
    def __init__(self, *a, **k):
        self.context = None

    async def start(self):
        return None

    async def close(self):
        return None


class _StopHere(BaseException):
    """Ends the retry once it has started: what it did at its start is all this
    file measures."""


@pytest.fixture
def machine(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queues" / "St_Bernard_20261002_071346"
    (queue_dir / "documents").mkdir(parents=True)
    (queue_dir / "documents" / "brief.md").write_text(BRIEF, encoding="utf-8")
    m = type("M", (), {})()
    m.events, m.record, m.tiles, m.retries, m.lines = [], [], [], [], []
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(research, "resolve_api_key", lambda _k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: m.lines.append(str(msg)))
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    monkeypatch.setattr(research, "_profile_dir", lambda *_a, **_k: tmp_path / "profile")
    monkeypatch.setattr(research, "_update_firestore_research",
                        lambda patch, *a, **k: m.record.append(dict(patch)))
    monkeypatch.setattr(research, "_write_agent_terminal_status",
                        lambda key, status, *a, **k: m.tiles.append((key, status)))
    monkeypatch.setattr(research, "fail_phase", lambda **kw: None)

    async def _noop_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop_dispatcher)

    async def _retry(*a, **k):
        m.retries.append(k)
    monkeypatch.setattr(research, "run_pipeline_captured", _retry)
    _real_sleep = asyncio.sleep

    async def _fast_sleep(*_a, **_k):
        return await _real_sleep(0)
    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_TS", {})
    # raising=False: on a tree without it, the test fails on what it measures.
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_OF", {}, raising=False)

    def _attempt(*, crash_retries=0, research_id=RID, cards=(CG_CARD,)):
        """Attempt number `crash_retries` of the run. The first attempt (0)
        raises `cards` — (agent, title, phase) — with the real `fail_agent`,
        then Chrome dies in Phase 2. A retry (≥ 1) is stopped as its first phase
        starts."""
        def _emit(name, phase=None, **kw):
            m.events.append((name, phase, dict(kw)))
            if name == "phase_start" and phase == 0:
                if crash_retries > 0:
                    raise _StopHere()
                for agent, title, card_phase in cards:
                    research._runtime.phase = card_phase
                    research.fail_agent(agent, title, "Retry to run it fresh, or Skip it.")
                research._runtime.phase = 2
                raise RuntimeError("research browser died during phase 2 (browser crash)")
        monkeypatch.setattr(research, "emit_event", _emit)
        try:
            asyncio.run(research.run_pipeline(
                topic="St Bernard", resume_dir=str(queue_dir), uid=UID,
                research_id=research_id, email=None, api_key="test-key",
                _crash_retries=crash_retries))
        except _StopHere:
            pass

    def _restart(research_id=RID):
        """The crash's own retry, from what attempt 0 handed it."""
        m.events.clear()
        m.record.clear()
        m.tiles.clear()
        _attempt(crash_retries=1, research_id=research_id)
        return [kw for name, _p, kw in m.events
                if name == "pipeline_warning" and kw.get("actions") == []
                and kw.get("auto_clear_on_resume") is True]

    m.attempt, m.restart = _attempt, _restart
    yield m
    research._runtime.reset()
    research._controls.reset()


def test_the_retry_takes_down_the_card_its_crashed_attempt_raised(machine):
    """⭐ THE FEATURE, end to end: the crashed attempt's card is taken down by
    its own retry as it starts — with the alert id the card went up under, no
    buttons, the app's recovered-by-itself flag, the durable decision cleared,
    and the tile running again."""
    machine.attempt()
    assert len(machine.retries) == 1 and machine.retries[0]["_crash_retries"] == 1
    assert "chatgpt" in research._AGENT_ERROR_CARD_TS, "the card was not raised"
    [kw] = machine.restart()
    assert (kw["agent"], kw["alert_id"]) == ("chatgpt", "phase2_agent_chatgpt_error")
    assert machine.record and "pendingDecision" in machine.record[0], machine.record
    assert ("chatgpt", "running") in machine.tiles
    assert "chatgpt" not in research._AGENT_ERROR_CARD_TS
    assert any("took down the card(s) the crashed attempt raised: ChatGPT" in s
               for s in machine.lines), machine.lines


def test_it_is_taken_down_before_the_retrys_first_phase_starts(machine):
    """Before anything else the retry does — not when the agent next finishes."""
    machine.attempt()
    machine.restart()
    names = [n for n, _p, _k in machine.events]
    assert "pipeline_warning" in names and "phase_start" in names, names
    assert names.index("pipeline_warning") < names.index("phase_start"), names


def test_only_a_crash_retry_takes_cards_down(machine):
    """⛔ A run that is not a crash's retry — a new job, a person's Retry — has
    no crashed attempt behind it and leaves the card as it is. Beside it, the
    crash's own retry takes the same card down."""
    machine.attempt()
    machine.events.clear()
    machine.attempt(crash_retries=0, cards=())
    assert not [k for n, _p, k in machine.events
                if n == "pipeline_warning" and k.get("actions") == []]
    assert "chatgpt" in research._AGENT_ERROR_CARD_TS
    assert [kw["agent"] for kw in machine.restart()] == ["chatgpt"]


def test_only_this_researchs_cards_are_taken_down(machine):
    """⛔ The card stamps outlive a run in a long-lived worker: a card another
    research raised is never 'taken down' into this one."""
    machine.attempt(research_id=OTHER_RID, cards=(CG_CARD,))
    machine.attempt(research_id=RID, cards=(CL_CARD,))
    assert [kw["agent"] for kw in machine.restart(RID)] == ["claude"]
    assert "chatgpt" in research._AGENT_ERROR_CARD_TS


def test_only_phase_2_cards_are_taken_down(machine):
    """The app reads a retraction only for a Phase-2 agent card; on another
    phase it would put up a new notice instead of clearing one."""
    machine.attempt(cards=(("chatgpt", "ChatGPT couldn't write the brief", 1), CL_CARD))
    assert [kw["agent"] for kw in machine.restart()] == ["claude"]


def test_a_card_the_person_already_answered_is_not_taken_down_again(machine):
    """Skip and Retry drop the stamp; nothing is left to take down for it."""
    machine.attempt(cards=(CG_CARD, CL_CARD))
    research._AGENT_ERROR_CARD_TS.pop("chatgpt")
    assert [kw["agent"] for kw in machine.restart()] == ["claude"]


def test_every_agents_card_is_taken_down(machine):
    machine.attempt(cards=(CG_CARD, CL_CARD,
                           ("gemini", "Gemini couldn't start Deep Research", 2)))
    got = {kw["agent"]: kw["alert_id"] for kw in machine.restart()}
    assert got == {a: f"phase2_agent_{a}_error" for a in ("chatgpt", "claude", "gemini")}
