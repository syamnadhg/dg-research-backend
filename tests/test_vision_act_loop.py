"""Track-B acting path: vision.act_loop (DG_VISION_TIER=act / tier2).

Covers the bounded multi-step acting engine: terminal pass-throughs, the
safety rails (step cap, repeat guard, low-confidence refusal, read-only
hotspots, wait cap, abort probe, execute errors, budget), breadcrumb
threading, mission-prompt adaptation, and the `act` env alias.

Async paths use asyncio.run (no pytest-asyncio mode dependency)."""
from __future__ import annotations

import asyncio
import json

import vision


_META = vision.ImgMeta(width_css=1000, height_css=800, dpr=1.0, captured_at=0.0)


class _FakePage:
    """Records mouse/keyboard interactions so tests can assert exactly what
    the loop executed (or that it executed nothing)."""

    class _Mouse:
        def __init__(self, sink):
            self._sink = sink

        async def click(self, x, y):
            self._sink.append(("click", x, y))

        async def wheel(self, dx, dy):
            self._sink.append(("wheel", dx, dy))

    class _Keyboard:
        def __init__(self, sink):
            self._sink = sink

        async def type(self, text, delay=0):
            self._sink.append(("type", text))

        async def press(self, key):
            self._sink.append(("press", key))

    def __init__(self):
        self.interactions: list[tuple] = []
        self.mouse = self._Mouse(self.interactions)
        self.keyboard = self._Keyboard(self.interactions)


class _FakeVC:
    """Scripted VisionClient: returns queued ActionResults; records the
    prompts and contexts each ask() received."""

    def __init__(self, results, raises=None):
        self._results = list(results)
        self._raises = raises
        self.prompts: list = []
        self.contexts: list = []

    async def screenshot(self, page, *, full_page=False):
        return b"img", _META

    async def ask(self, img, meta, ctx, *, prompt=None, high_stakes=False,
                  transport_retry=True):
        if self._raises is not None:
            raise self._raises
        self.prompts.append(prompt)
        self.contexts.append(dict(ctx))
        return self._results.pop(0)


def _res(action, *, conf=0.9, x=None, y=None, text=None, key=None,
         reason="r", dur=None):
    return vision.ActionResult(
        action=action, reason=reason, confidence=conf,
        next_expected_state="n", x_ratio=x, y_ratio=y, text=text, key=key,
        duration_ms=dur, low_confidence=(conf < vision.LOW_CONFIDENCE_THRESHOLD),
        model_used="m", latency_ms=5.0)


def _run(vc, page=None, **kw):
    kw.setdefault("flow_context", {"phase": 2, "platform": "chatgpt"})
    kw.setdefault("hotspot_id", "7c")
    return asyncio.run(vision.act_loop(page or _FakePage(), vision=vc, **kw))


def _set_log(monkeypatch, tmp_path):
    p = tmp_path / "vs.jsonl"
    monkeypatch.setenv("DG_VISION_SHADOW_LOG", str(p))
    return p


# ── terminal pass-throughs ───────────────────────────────────────────────────

def test_immediate_success_touches_nothing(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    page = _FakePage()
    vc = _FakeVC([_res("declare_success", reason="panel: open — it was there")])
    out = _run(vc, page)
    assert out.action == "declare_success"
    assert "panel: open" in out.reason
    assert page.interactions == []


def test_escalate_passes_through(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([_res("escalate_to_cua", reason="captcha visible")])
    out = _run(vc)
    assert out.action == "escalate_to_cua"
    assert "captcha" in out.reason


def test_declare_failure_passes_through(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([_res("declare_failure", reason="mission impossible")])
    out = _run(vc)
    assert out.action == "declare_failure"


# ── acting steps ─────────────────────────────────────────────────────────────

def test_click_then_success_executes_and_breadcrumbs(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "ACT_STEP_SETTLE_S", 0.0)
    page = _FakePage()
    vc = _FakeVC([
        _res("click", x=0.5, y=0.25, reason="clicking the strip"),
        _res("declare_success", reason="panel: open"),
    ])
    out = _run(vc, page)
    assert out.action == "declare_success"
    assert page.interactions == [("click", 500.0, 200.0)]
    # Step 2's context carries step 1 as a breadcrumb.
    assert "clicking the strip" in vc.contexts[1].get("last_action", "")
    assert "last_action" not in vc.contexts[0]


def test_mission_prompt_is_adapted_and_threaded(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([_res("declare_success")])
    _run(vc, mission_prompt="Open the panel and say 'panel: open'.")
    assert "MULTI-STEP MISSION" in vc.prompts[0]
    assert "say 'panel: open'" in vc.prompts[0]
    assert "declare_success" in vc.prompts[0]


def test_no_mission_prompt_uses_default_task(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([_res("declare_success")])
    _run(vc)
    assert vc.prompts[0] is None


# ── rails ────────────────────────────────────────────────────────────────────

def test_step_cap_escalates(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "ACT_STEP_SETTLE_S", 0.0)
    # Alternate two different clicks so the repeat guard never fires first.
    seq = [_res("click", x=0.2 + 0.1 * (i % 2), y=0.5) for i in range(8)]
    vc = _FakeVC(seq)
    out = _run(vc, max_steps=8)
    assert out.action == "escalate_to_cua"
    assert "step cap" in out.reason


def test_repeat_guard_escalates_before_cap(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "ACT_STEP_SETTLE_S", 0.0)
    page = _FakePage()
    vc = _FakeVC([_res("click", x=0.5, y=0.5) for _ in range(8)])
    out = _run(vc, page, max_steps=8)
    assert out.action == "escalate_to_cua"
    assert "repeated identical" in out.reason
    # 3 identical proposals; the 3rd trips the guard BEFORE executing.
    assert len(page.interactions) == 2


def test_low_confidence_action_not_executed(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    page = _FakePage()
    vc = _FakeVC([_res("click", x=0.9, y=0.9, conf=0.3)])
    out = _run(vc, page)
    assert out.action == "escalate_to_cua"
    assert "low-confidence" in out.reason
    assert page.interactions == []


def test_low_confidence_success_not_trusted(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([_res("declare_success", conf=0.4, reason="maybe done?")])
    out = _run(vc)
    assert out.action == "escalate_to_cua"
    assert "not trusted" in out.reason


def test_read_only_never_executes(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    page = _FakePage()
    vc = _FakeVC([_res("click", x=0.5, y=0.5)])
    out = _run(vc, page, read_only=True)
    assert out.action == "escalate_to_cua"
    assert "read-only" in out.reason
    assert page.interactions == []


def test_read_only_verdict_passes_through(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    page = _FakePage()
    vc = _FakeVC([_res("declare_success", reason="audio complete")])
    out = _run(vc, page, read_only=True)
    assert out.action == "declare_success"
    assert page.interactions == []


def test_wait_is_capped(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    slept: list[float] = []

    async def _fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(vision.asyncio, "sleep", _fake_sleep)
    vc = _FakeVC([
        _res("wait", dur=999_999),
        _res("declare_success"),
    ])
    out = _run(vc)
    assert out.action == "declare_success"
    assert max(slept) <= vision.ACT_MAX_WAIT_MS / 1000.0


def test_abort_probe_stops_before_any_vision_call(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([_res("declare_success")])
    out = _run(vc, should_abort=lambda: True)
    assert out.action == "escalate_to_cua"
    assert "aborted" in out.reason
    assert vc.prompts == []  # never asked


def test_execute_error_escalates(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)

    class _BrokenPage(_FakePage):
        def __init__(self):
            super().__init__()

            class _M:
                async def click(self, x, y):
                    raise RuntimeError("page closed")

            self.mouse = _M()

    vc = _FakeVC([_res("click", x=0.5, y=0.5)])
    out = _run(vc, _BrokenPage())
    assert out.action == "escalate_to_cua"
    assert "execute_action" in out.reason


def test_budget_exceeded_escalates(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([], raises=vision.BudgetExceeded("50"))
    out = _run(vc)
    assert out.action == "escalate_to_cua"
    assert "budget" in out.reason


def test_never_raises_on_unexpected_error(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC([], raises=RuntimeError("boom"))
    out = _run(vc)
    assert out.action == "escalate_to_cua"
    assert "boom" in out.reason


# ── telemetry ────────────────────────────────────────────────────────────────

def test_act_steps_logged_with_source_act(monkeypatch, tmp_path):
    log = _set_log(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "ACT_STEP_SETTLE_S", 0.0)
    vc = _FakeVC([
        _res("click", x=0.5, y=0.25),
        _res("declare_success", reason="panel: open"),
    ])
    _run(vc, run_id="r1")
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    assert all(r["source"] == "act" for r in recs)
    assert all(r["run_id"] == "r1" for r in recs)
    finals = [r for r in recs if r.get("final")]
    assert len(finals) == 1 and finals[0]["outcome"] == "success"
    assert finals[0]["steps_used"] == 2
    # the non-final step record carries the full proposed action
    steps = [r for r in recs if not r.get("final")]
    assert steps[0]["vision"]["action"] == "click"


def test_synthesized_final_logged_as_escalate(monkeypatch, tmp_path):
    log = _set_log(monkeypatch, tmp_path)
    page = _FakePage()
    vc = _FakeVC([_res("click", x=0.5, y=0.5, conf=0.2)])
    _run(vc, page)
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    finals = [r for r in recs if r.get("final")]
    assert len(finals) == 1 and finals[0]["outcome"] == "escalate"


# ── env alias ────────────────────────────────────────────────────────────────

def test_act_env_alias_maps_to_tier2(monkeypatch):
    monkeypatch.setenv("DG_VISION_TIER", "act")
    assert vision.is_vision_enabled() == "tier2"


def test_other_modes_unchanged(monkeypatch):
    for v, want in (("off", "off"), ("shadow", "shadow"), ("tier2", "tier2"),
                    ("tier3", "tier3"), ("bogus", "off"), ("", "off")):
        monkeypatch.setenv("DG_VISION_TIER", v)
        assert vision.is_vision_enabled() == want
