"""Track-B acting path: the research.py dispatcher (_shadow_observed_cua)
act branch + the report script's act-mode handling.

The dispatcher is the ONE switch point: DG_VISION_TIER unset/off must be
byte-identical to the pre-Vision pipeline (direct CUA), shadow must keep
observing, and act (tier2) must let Vision drive with CUA as the safety
net. Async paths use asyncio.run (no pytest-asyncio mode dependency)."""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib

import research
import vision

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_report():
    spec = importlib.util.spec_from_file_location(
        "vision_shadow_report", _ROOT / "scripts" / "vision_shadow_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeControls:
    def __init__(self, stop=False, pause=False):
        self._stop = stop
        self._pause = pause

    def is_stop(self):
        return self._stop

    def is_pause(self):
        return self._pause


def _final(action, reason="done", conf=0.9):
    return vision.ActionResult(
        action=action, reason=reason, confidence=conf,
        next_expected_state="", model_used="m", latency_ms=5.0)


class _FakeVisionModule:
    """Stands in for research._vision: scripted mode + act_loop/shadow results."""

    ACT_MAX_STEPS_DEFAULT = vision.ACT_MAX_STEPS_DEFAULT

    def __init__(self, mode="off", act_result=None, act_raises=None,
                 act_delay=0.0):
        self._mode = mode
        self._act_result = act_result
        self._act_raises = act_raises
        self._act_delay = act_delay
        self.act_calls: list[dict] = []
        self.shadow_calls = 0

    def is_vision_enabled(self):
        return self._mode

    async def act_loop(self, page, **kw):
        self.act_calls.append(kw)
        if self._act_delay:
            await asyncio.sleep(self._act_delay)
        if self._act_raises is not None:
            raise self._act_raises
        return self._act_result

    async def shadow_observe_then_cua(self, page, cua_fn, **kw):
        self.shadow_calls += 1
        return await cua_fn()


def _dispatch(monkeypatch, fake_vision, *, controls=None, **kw):
    monkeypatch.setattr(research, "_vision", fake_vision)
    monkeypatch.setattr(research, "_controls", controls or _FakeControls())
    calls = {"cua": 0}

    async def _cua():
        calls["cua"] += 1
        return {"status": "success", "text": "cua did it"}

    kw.setdefault("hotspot_id", "7c")
    kw.setdefault("phase", 2)
    kw.setdefault("platform", "chatgpt")
    kw.setdefault("current_step", "s")
    kw.setdefault("context_hint", "h")
    out = asyncio.run(research._shadow_observed_cua(
        object(), cua_coro_factory=_cua, **kw))
    return out, calls, fake_vision


# ── mode routing ─────────────────────────────────────────────────────────────

def test_off_mode_runs_cua_directly(monkeypatch):
    out, calls, fv = _dispatch(monkeypatch, _FakeVisionModule("off"))
    assert calls["cua"] == 1
    assert out["text"] == "cua did it"
    assert fv.act_calls == [] and fv.shadow_calls == 0


def test_shadow_mode_routes_to_shadow(monkeypatch):
    out, calls, fv = _dispatch(monkeypatch, _FakeVisionModule("shadow"))
    assert fv.shadow_calls == 1
    assert calls["cua"] == 1  # shadow stub runs the factory
    assert fv.act_calls == []


def test_act_success_skips_cua(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success",
                                                      "panel: open — done"))
    out, calls, fv = _dispatch(monkeypatch, fv)
    assert calls["cua"] == 0
    assert out["status"] == "vision_success" and out["vision_acted"] is True
    assert "panel: open" in out["text"]


def test_act_success_text_translation(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success",
                                                      "the side panel is now visible"))
    out, _, _ = _dispatch(monkeypatch, fv, success_text="panel: open")
    assert out["text"].startswith("panel: open | vision:")


def test_act_success_marker_not_duplicated(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success",
                                                      "Panel: OPEN as instructed"))
    out, _, _ = _dispatch(monkeypatch, fv, success_text="panel: open")
    assert out["text"].lower().count("panel: open") == 1


def test_act_escalate_falls_back_to_cua(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("escalate_to_cua", "lost"))
    out, calls, _ = _dispatch(monkeypatch, fv)
    assert calls["cua"] == 1
    assert out["text"] == "cua did it"


def test_act_failure_falls_back_to_cua(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_failure", "nope"))
    out, calls, _ = _dispatch(monkeypatch, fv)
    assert calls["cua"] == 1


def test_act_exception_falls_back_to_cua(monkeypatch):
    fv = _FakeVisionModule("tier2", act_raises=RuntimeError("engine down"))
    out, calls, _ = _dispatch(monkeypatch, fv)
    assert calls["cua"] == 1
    assert out["text"] == "cua did it"


def test_act_timeout_falls_back_to_cua(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success"),
                           act_delay=0.5)
    out, calls, _ = _dispatch(monkeypatch, fv, act_timeout_s=0.05)
    assert calls["cua"] == 1


def test_act_stop_returns_stopped_without_cua(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("escalate_to_cua", "aborted"))
    out, calls, _ = _dispatch(monkeypatch, fv,
                              controls=_FakeControls(stop=True))
    assert out["status"] == "stopped"
    assert calls["cua"] == 0


def test_act_pause_defers_to_cua(monkeypatch):
    # Pause (not stop): the CUA leg handles the pause via its own
    # wait_if_paused machinery, so the dispatcher must fall through.
    fv = _FakeVisionModule("tier2", act_result=_final("escalate_to_cua", "aborted"))
    out, calls, _ = _dispatch(monkeypatch, fv,
                              controls=_FakeControls(pause=True))
    assert calls["cua"] == 1


def test_read_only_threads_single_step(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success", "audio complete"))
    out, _, fv = _dispatch(monkeypatch, fv, read_only=True)
    assert fv.act_calls[0]["read_only"] is True
    assert fv.act_calls[0]["max_steps"] == 1


def test_mission_and_stakes_passthrough(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success"))
    _dispatch(monkeypatch, fv, mission_prompt="MISSION X", high_stakes=True,
              act_max_steps=5)
    kw = fv.act_calls[0]
    assert kw["mission_prompt"] == "MISSION X"
    assert kw["high_stakes"] is True
    assert kw["max_steps"] == 5


def test_act_flow_context_carries_hints(monkeypatch):
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success"))
    _dispatch(monkeypatch, fv, hotspot_id="7c")
    ctx = fv.act_calls[0]["flow_context"]
    assert "activity strip" in ctx["context_hint"]  # from _HOTSPOT_VISION_HINTS
    assert ctx["workflow_name"] == "7c"


def test_pre_cua_net_probe_veto_skips_cua(monkeypatch):
    # Review [4]: a partial act attempt at a non-idempotent hotspot → the probe
    # vetoes the CUA net (state already advanced) so CUA never re-acts.
    fv = _FakeVisionModule("tier2", act_result=_final("escalate_to_cua", "timed out"))

    async def _probe():
        return {"status": "vision_partial", "text": "generating"}

    out, calls, _ = _dispatch(monkeypatch, fv, pre_cua_net_probe=_probe)
    assert calls["cua"] == 0
    assert out["status"] == "vision_partial"


def test_pre_cua_net_probe_none_runs_cua(monkeypatch):
    # Probe returns None (Vision did nothing) → CUA net runs normally.
    fv = _FakeVisionModule("tier2", act_result=_final("escalate_to_cua", "nope"))

    async def _probe():
        return None

    out, calls, _ = _dispatch(monkeypatch, fv, pre_cua_net_probe=_probe)
    assert calls["cua"] == 1


def test_pre_cua_net_probe_error_runs_cua(monkeypatch):
    # A throwing probe must not break the fall-through — CUA still runs.
    fv = _FakeVisionModule("tier2", act_result=_final("escalate_to_cua"))

    async def _probe():
        raise RuntimeError("probe boom")

    out, calls, _ = _dispatch(monkeypatch, fv, pre_cua_net_probe=_probe)
    assert calls["cua"] == 1


def test_probe_not_invoked_on_vision_success(monkeypatch):
    # Vision succeeded → no CUA, and the probe is irrelevant (not called).
    fv = _FakeVisionModule("tier2", act_result=_final("declare_success", "done"))
    probed = {"n": 0}

    async def _probe():
        probed["n"] += 1
        return {"status": "x"}

    out, calls, _ = _dispatch(monkeypatch, fv, pre_cua_net_probe=_probe)
    assert calls["cua"] == 0 and probed["n"] == 0
    assert out["status"] == "vision_success"


def test_shadow_reraises_cua_origin_exception(monkeypatch):
    # Review [5]: a CUA-origin exception (tagged) must propagate, NOT trigger a
    # second CUA run.
    class _ShadowReraises(_FakeVisionModule):
        async def shadow_observe_then_cua(self, page, cua_fn, **kw):
            self.shadow_calls += 1
            try:
                return await cua_fn()  # this raises
            except Exception as e:
                e._dg_cua_origin = True
                raise

    fv = _ShadowReraises("shadow")
    monkeypatch.setattr(research, "_vision", fv)
    monkeypatch.setattr(research, "_controls", _FakeControls())
    calls = {"cua": 0}

    async def _cua():
        calls["cua"] += 1
        raise RuntimeError("cua died")

    import pytest
    with pytest.raises(RuntimeError, match="cua died"):
        asyncio.run(research._shadow_observed_cua(
            object(), hotspot_id="7c", phase=2, platform="chatgpt",
            current_step="s", context_hint="h", cua_coro_factory=_cua))
    assert calls["cua"] == 1  # ran once, not twice


def test_shadow_infra_failure_still_falls_back(monkeypatch):
    # A genuine shadow-infra error (NOT cua-origin) still falls back to a
    # direct CUA run — unchanged behavior.
    class _ShadowBroken(_FakeVisionModule):
        async def shadow_observe_then_cua(self, page, cua_fn, **kw):
            raise RuntimeError("shadow infra broke")  # no _dg_cua_origin tag

    fv = _ShadowBroken("shadow")
    monkeypatch.setattr(research, "_vision", fv)
    monkeypatch.setattr(research, "_controls", _FakeControls())
    calls = {"cua": 0}

    async def _cua():
        calls["cua"] += 1
        return {"status": "success", "text": "t"}

    out = asyncio.run(research._shadow_observed_cua(
        object(), hotspot_id="7c", phase=2, platform="chatgpt",
        current_step="s", context_hint="h", cua_coro_factory=_cua))
    assert calls["cua"] == 1 and out["text"] == "t"


def test_act_pad_ms_zero_off_and_shadow(monkeypatch):
    # Review [1][2][3]: _act_pad_ms is 0 unless the act tier is armed, so every
    # padded outer timeout stays byte-identical in off/shadow.
    monkeypatch.setattr(research, "_vision", _FakeVisionModule("off"))
    assert research._act_pad_ms(150) == 0
    assert research._act_pad_ms(120, 150) == 0
    monkeypatch.setattr(research, "_vision", _FakeVisionModule("shadow"))
    assert research._act_pad_ms(40, 40) == 0
    monkeypatch.setattr(research, "_vision", None)
    assert research._act_pad_ms(150) == 0


def test_act_pad_ms_additive_when_armed(monkeypatch):
    monkeypatch.setattr(research, "_vision", _FakeVisionModule("tier2"))
    assert research._act_pad_ms(150) == 150000
    assert research._act_pad_ms(120, 150) == 270000
    assert research._act_pad_ms(40, 40) == 80000


def test_vision_none_runs_cua(monkeypatch):
    monkeypatch.setattr(research, "_vision", None)
    calls = {"cua": 0}

    async def _cua():
        calls["cua"] += 1
        return {"status": "success", "text": "t"}

    out = asyncio.run(research._shadow_observed_cua(
        object(), hotspot_id="7c", phase=2, platform="chatgpt",
        current_step="s", context_hint="h", cua_coro_factory=_cua))
    assert calls["cua"] == 1
    assert out["text"] == "t"


# ── report script: act records are a separate population ────────────────────

def _mk_records():
    return [
        # miss-path record (no source)
        {"hotspot_id": "7c", "vision": {"action": "click", "x_ratio": 0.5, "y_ratio": 0.5},
         "cua": {"text_head": "panel: open"}},
        # dom_success record
        {"hotspot_id": "7c", "source": "dom_success",
         "vision": {"action": "click", "x_ratio": 0.5, "y_ratio": 0.5},
         "dom_ground_truth": {"true_x_ratio": 0.5, "true_y_ratio": 0.5}},
        # act step + final records
        {"hotspot_id": "7c", "source": "act", "step": 1, "max_steps": 8,
         "vision": {"action": "click", "x_ratio": 0.5, "y_ratio": 0.5}},
        {"hotspot_id": "7c", "source": "act", "step": 2, "max_steps": 8,
         "vision": {"terminal": "declare_success"}, "final": True,
         "outcome": "success", "steps_used": 2},
        {"hotspot_id": "7c", "source": "act", "step": 1, "max_steps": 8,
         "vision": {"action": "escalate_to_cua", "reason": "lost"}, "final": True,
         "outcome": "escalate", "steps_used": 1},
    ]


def test_report_misspath_excludes_act(capsys):
    mod = _load_report()
    mod.report(_mk_records(), None, False)
    out = capsys.readouterr().out
    # Only the single true miss-path record counts toward N.
    assert "7c        1" in out


def test_report_act_outcomes(capsys):
    mod = _load_report()
    mod.report_act(_mk_records(), None, False)
    out = capsys.readouterr().out
    assert "Vision-act outcomes" in out
    assert "50.0% (1/2)" in out  # 1 success of 2 missions; step records ignored


def test_report_act_silent_when_no_act_records(capsys):
    mod = _load_report()
    mod.report_act([r for r in _mk_records() if r.get("source") != "act"], None, False)
    assert "Vision-act" not in capsys.readouterr().out
