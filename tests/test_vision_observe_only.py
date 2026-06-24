"""Track-B success-path observer (DG_VISION_OBSERVE_SUCCESS).

Covers vision.observe_only (the DOM-success Vision observer), the
research.py helpers that feed it (_gt_from_box / _dom_gt_from_res /
_observe_dom_success + its flag gate), and the report scorer's new
source=="dom_success" population.

Async paths use asyncio.run (no pytest-asyncio mode dependency)."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib

import vision

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_report():
    spec = importlib.util.spec_from_file_location(
        "vision_shadow_report", _ROOT / "scripts" / "vision_shadow_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakePage:
    """Records any interaction so a test can assert observe_only never touches it."""
    def __init__(self):
        self.interactions: list[str] = []

    async def click(self, *a, **k):
        self.interactions.append("click")

    async def evaluate(self, *a, **k):
        self.interactions.append("evaluate")
        return None


class _FakeVC:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.asked = 0

    async def screenshot(self, page, *, full_page=False):
        return b"img", None

    async def ask(self, img, meta, ctx, *, high_stakes=False, transport_retry=True):
        self.asked += 1
        if self._raises is not None:
            raise self._raises
        return self._result


def _click_result(x=0.5, y=0.5):
    return vision.ActionResult(
        action="click", reason="found the panel toggle", confidence=0.9,
        next_expected_state="panel open", x_ratio=x, y_ratio=y,
        model_used="m", latency_ms=12.0, input_tokens=3, output_tokens=4)


def _set_log(monkeypatch, tmp_path):
    p = tmp_path / "vs.jsonl"
    monkeypatch.setenv("DG_VISION_SHADOW_LOG", str(p))
    return p


# ── vision.observe_only ──────────────────────────────────────────────────────

def test_observe_only_logs_dom_success_record(monkeypatch, tmp_path):
    log = _set_log(monkeypatch, tmp_path)
    vc = _FakeVC(result=_click_result(0.5, 0.5))
    page = _FakePage()
    gt = {"true_x_ratio": 0.51, "true_y_ratio": 0.49, "label": "Pro thinking…"}
    rec = asyncio.run(vision.observe_only(
        page, flow_context={"phase": 1, "platform": "chatgpt"},
        hotspot_id="7c-p1", vision=vc, run_id="run-123", dom_ground_truth=gt))

    assert vc.asked == 1
    assert rec["source"] == "dom_success"
    assert rec["hotspot_id"] == "7c-p1"
    assert rec["run_id"] == "run-123"
    assert rec["agent"] == "chatgpt" and rec["phase"] == 1
    assert rec["vision"]["action"] == "click" and rec["vision"]["x_ratio"] == 0.5
    assert rec["dom_ground_truth"] == gt
    # exactly one record persisted, carrying the source discriminator
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1 and json.loads(lines[0])["source"] == "dom_success"
    # observe_only is outcome-neutral: it NEVER interacts with the page
    assert page.interactions == []


def test_observe_only_swallows_ask_error(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC(raises=RuntimeError("boom"))
    rec = asyncio.run(vision.observe_only(
        _FakePage(), flow_context={"phase": 2, "platform": "claude"},
        hotspot_id="7d", vision=vc))
    assert rec["source"] == "dom_success"
    assert "error" in rec["vision"]  # swallowed into the record, never raised


def test_observe_only_records_timeout(monkeypatch, tmp_path):
    _set_log(monkeypatch, tmp_path)
    vc = _FakeVC(raises=asyncio.TimeoutError())
    rec = asyncio.run(vision.observe_only(
        _FakePage(), flow_context={"phase": 2, "platform": "chatgpt"},
        hotspot_id="7c", vision=vc))
    assert rec["vision"].get("timeout") is True


# ── report scorer (source=="dom_success") ────────────────────────────────────

def test_coord_close():
    vsr = _load_report()
    assert vsr._coord_close(0.5, 0.5, 0.55, 0.52) is True   # within 0.10
    assert vsr._coord_close(0.5, 0.5, 0.8, 0.8) is False     # far
    assert vsr._coord_close(0.5, 0.5, None, 0.5) is None     # missing ground truth


def test_report_dom_success_scoring(capsys):
    vsr = _load_report()
    recs = [{"source": "dom_success", "hotspot_id": "7c-p1",
             "vision": {"action": "click", "x_ratio": 0.50, "y_ratio": 0.50},
             "dom_ground_truth": {"true_x_ratio": 0.51, "true_y_ratio": 0.49}}
            for _ in range(12)]
    # a legacy miss-path record (has cua, no source) must be IGNORED here
    recs.append({"hotspot_id": "7c-p1", "vision": {"action": "click"},
                 "cua": {"text_head": "panel: open"}})
    vsr.report_dom_success(recs, None, False)
    out = capsys.readouterr().out
    assert "dom_success" in out and "7c-p1" in out and "PASS" in out
    assert "(12/12)" in out  # only the 12 dom_success records scored


def test_report_excludes_dom_success_from_misspath(capsys):
    vsr = _load_report()
    recs = [{"source": "dom_success", "hotspot_id": "7c-p1",
             "vision": {"action": "click", "x_ratio": 0.5, "y_ratio": 0.5},
             "dom_ground_truth": {"true_x_ratio": 0.5, "true_y_ratio": 0.5}}]
    vsr.report(recs, None, False)
    out = capsys.readouterr().out
    assert "No miss-path" in out  # dom_success records are not scored as miss-path


# ── research.py helpers ──────────────────────────────────────────────────────

def test_gt_helpers():
    import research
    gt = research._gt_from_box({"cx": 100, "cy": 50, "vw": 200, "vh": 100}, url="u")
    assert gt["true_x_ratio"] == 0.5 and gt["true_y_ratio"] == 0.5 and gt["url"] == "u"
    assert research._gt_from_box(None)["true_x_ratio"] is None
    gt2 = research._dom_gt_from_res({"bbox": {"cx": 10, "cy": 10, "vw": 100, "vh": 100},
                                     "label": "L", "clickedTag": "DIV"})
    assert gt2["true_x_ratio"] == 0.1 and gt2["label"] == "L" and gt2["clickedTag"] == "DIV"


def test_observe_dom_success_respects_flag(monkeypatch):
    import research
    calls: list[str] = []

    class _Spy:
        async def observe_only(self, *a, **k):
            calls.append(k.get("hotspot_id"))
            return {}

    monkeypatch.setattr(research, "_vision", _Spy())

    async def _fire():
        research._observe_dom_success(object(), hotspot_id="7c", phase=2,
                                      platform="chatgpt", current_step="open_activity_panel")
        await asyncio.sleep(0.05)  # let any scheduled fire-and-forget task run

    # flag OFF → strict no-op (observe_only never scheduled)
    monkeypatch.setattr(research, "observe_success_enabled", lambda: False)
    asyncio.run(_fire())
    assert calls == []

    # flag ON → schedules the observe
    monkeypatch.setattr(research, "observe_success_enabled", lambda: True)
    asyncio.run(_fire())
    assert calls == ["7c"]
