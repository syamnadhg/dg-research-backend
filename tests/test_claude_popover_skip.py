"""Claude P2 setup: the model popover must open ONLY when it has work to do.

Background (2026-07-30). `setup_claude_dr` opened the model popover on EVERY
run, unconditionally, because the Thinking toggle lived inside the Effort
submenu and had to be re-asserted each time (#745). Opus 5 removed that toggle,
so every run produced this pair of log lines back to back:

    Step 1 OK: model already Opus 5 (trigger) — NOT re-picking (#744)
    Step 1A OK: opened model popover                 <-- opened it anyway

followed by `Step 1D WARN: 'Thinking' toggle not found`, `Step 1C WARN: 'Max'
effort not found`, and then the CUA validate layer being invited in to "fix" the
quality knobs — where it clicked into the model menu a second time. That second
interaction is what the owner reported as "it opens the modal selector twice".

The trigger already carries BOTH facts ("Opus 5 Max"), so when the model is at
or above the policy floor and the trigger shows the target effort there is
nothing behind the popover left to set.

These tests DRIVE the real coroutine against a scripted page and assert on
whether the popover-opening script was evaluated. A source-text assertion would
not do: the whole class of bug here is a decision that reads correct in source
and still fires, and this repo has been burned by exactly that before (37
rehydration tests once passed against a guaranteed crash).
"""
import asyncio

import pytest

import models
import research


# Distinctive fragments of the real scripts inside setup_claude_dr. Matching on
# these is what makes "did the popover open?" observable.
_POPOVER_OPEN_MARK = "includes('opus')"          # Step 1A: clicks the model trigger
_PICK_OPUS_MARK = "floor, pin"                   # Step 1B: the picker
_EFFORT_SUBMENU_MARK = "t === 'effort'"          # Step 1C: opens the Effort submenu
_THINKING_MARK = "isThinking"                    # Step 1D: the Thinking toggle probe
_EFFORT_SET_MARK = "'max effort'"                # Step 1C': selects Max
_TRIGGER_READ_MARK = "trigger_text"              # Step 1: reads model + effort


class _Keyboard:
    def __init__(self, log):
        self._log = log

    async def press(self, key):
        self._log.append(("key", key))


class ScriptedPage:
    """Minimal page double. `evaluate` dispatches on distinctive fragments of the
    real script text, records every call, and returns scripted values.

    `trigger_text` is the crucial input: it is what the model-selector button
    reads on the live page, e.g. "Opus 5 Max" or just "Opus 5".
    """

    def __init__(self, trigger_text, *, chat_tab="chat", research_on=True):
        self.trigger_text = trigger_text
        self.chat_tab = chat_tab
        self.research_on = research_on
        self.scripts = []           # every JS string evaluated, in order
        self.events = []            # keyboard presses
        self.keyboard = _Keyboard(self.events)

    # -- helpers the tests assert on -------------------------------------
    def evaluated(self, mark):
        return any(mark in s for s in self.scripts)

    def count(self, mark):
        return sum(1 for s in self.scripts if mark in s)

    # -- the page API surface setup_claude_dr actually touches ------------
    async def query_selector(self, sel):
        return None  # no precise tools-menu selector matches; falls to the '+' detector

    async def evaluate(self, script, arg=None):
        self.scripts.append(script)

        if _TRIGGER_READ_MARK in script:
            # Mirror the real script's own contract: parse the version out of the
            # trigger text, and report the effort word only when it appears as a
            # token in that SAME text.
            import re
            m = re.search(r"opus[^0-9]*([0-9]+(?:\.[0-9]+)?)", self.trigger_text, re.I)
            ver = float(m.group(1)) if m else None
            toks = re.split(r"[^a-z0-9.]+", self.trigger_text.lower())
            effort = arg if (ver is not None and arg and str(arg).lower() in toks) else None
            return {"ver": ver, "effort": effort, "trigger_text": self.trigger_text}

        if _POPOVER_OPEN_MARK in script:
            return True                       # the popover opens when asked
        if _PICK_OPUS_MARK in script:
            return {"n": 1, "highest": 5.0}
        if _EFFORT_SUBMENU_MARK in script:
            return True
        if _THINKING_MARK in script:
            return {"found": True, "toggled": False}
        if _EFFORT_SET_MARK in script:
            return "max (already)"
        if "cowork" in script.lower():
            return self.chat_tab
        if "aria-label" in script and "cand.click()" in script:
            return "plus"                     # the '+' tools-menu detector
        if "research" in script.lower():
            return self.research_on
        return None


def _run(page, **kw):
    return asyncio.run(research.setup_claude_dr(page, **kw))


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """setup_claude_dr sleeps ~5s in fixed waits. Keep the ordering, drop the
    wall-clock — patched on the asyncio module research.py actually calls."""
    async def _instant(_secs):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _instant)


# ── the fix ───────────────────────────────────────────────────────────────

def test_popover_is_not_opened_when_the_trigger_already_shows_model_and_effort():
    """The reported bug. Trigger reads "Opus 5 Max": model is above the floor and
    effort is already Max, so there is nothing behind the popover to set."""
    page = ScriptedPage("Opus 5 Max")
    _run(page)
    assert page.evaluated(_TRIGGER_READ_MARK), "the trigger must still be read"
    assert not page.evaluated(_POPOVER_OPEN_MARK), (
        "the model popover was opened even though the trigger already showed a "
        "model above the floor AND the target effort — this is the duplicate "
        "model-menu interaction the fix removes"
    )
    # Nothing behind the popover ran either.
    assert not page.evaluated(_EFFORT_SUBMENU_MARK)
    assert not page.evaluated(_THINKING_MARK)


def test_research_tool_is_still_enabled_on_the_skip_path():
    """Skipping the popover must not skip the correctness gate. The Research tool
    lives in a different menu and is a hard requirement."""
    page = ScriptedPage("Opus 5 Max")
    assert _run(page) is True
    assert page.evaluated("cand.click()"), (
        "Step 3 must still open the tools menu and enable Research when Step 1A "
        "is skipped — the skip is about quality knobs, not the hard gate"
    )


# ── every fall-through path still opens it ────────────────────────────────

def test_popover_opens_when_the_trigger_shows_no_effort():
    """Effort unknown ⇒ not confirmed. The skip requires a POSITIVE read of both
    facts, so an effort-less trigger must behave exactly as before the fix."""
    page = ScriptedPage("Opus 5")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK)
    assert page.evaluated(_EFFORT_SUBMENU_MARK), "the Effort submenu must still be reached"


def test_popover_opens_when_the_model_is_below_the_floor():
    page = ScriptedPage("Opus 4.7 Max")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK)
    assert page.evaluated(_PICK_OPUS_MARK), "a below-floor model must still be re-picked"


def test_popover_opens_when_the_trigger_has_no_model_at_all():
    """Sonnet/Haiku, or a layout the version regex misses: no version ⇒ the model
    is not confirmed ⇒ open the picker."""
    page = ScriptedPage("Sonnet 4.6")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK)


def test_pin_model_still_forces_the_popover_open():
    """The Phoenix known-good fallback pins a specific version BECAUSE the higher
    one failed Deep-Research verification. A trigger reading higher-and-Max must
    NOT short-circuit that deliberate downgrade."""
    page = ScriptedPage("Opus 5 Max")
    _run(page, pin_model=4.8)
    assert page.evaluated(_POPOVER_OPEN_MARK), (
        "pin_model must always reach the picker — skipping it would silently "
        "keep the model that just failed verification"
    )
    assert page.evaluated(_PICK_OPUS_MARK)


def test_policy_thinking_true_reopens_the_popover(monkeypatch):
    """The skip is policy-driven, not hardcoded. If a future model reinstates a
    control that lives behind the popover, flipping one dict value must bring the
    popover back — including on a trigger that reads model AND effort."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["claude"], "thinking", True)
    page = ScriptedPage("Opus 5 Max")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK), (
        "with thinking re-enabled in policy there IS something behind the "
        "popover again, so it must open"
    )
    assert page.evaluated(_THINKING_MARK), "and the Thinking probe must run"


# ── the thinking probe is gated, not deleted ──────────────────────────────

def test_thinking_probe_does_not_run_when_policy_says_the_toggle_is_gone():
    """Opus 5 has no Thinking toggle. Probing for it produced a WARN on every
    single healthy run, which is what made a working setup look broken."""
    page = ScriptedPage("Opus 5")          # forces the popover open via no-effort
    _run(page)
    assert page.evaluated(_EFFORT_SUBMENU_MARK), "the Effort submenu still opens (Max lives there)"
    assert not page.evaluated(_THINKING_MARK), (
        "the Thinking toggle must not be searched for when policy says the "
        "model family no longer has one"
    )


def test_policy_is_the_only_lever_for_thinking():
    """Guards against re-hardcoding: the decision must read the policy dict."""
    import inspect
    src = inspect.getsource(research.setup_claude_dr)
    assert "_claude_wants_thinking" in src
    assert 'p2_labels("claude")' in src, (
        "effort/thinking must come from the policy accessor, not literals"
    )
