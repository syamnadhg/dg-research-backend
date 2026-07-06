"""V1 test harness for vision.py.

Two modes:
    python vision_test.py --smoke          — sanity-check the API surface (no
                                              real vision call; constructs a
                                              client, sends a 1×1 PNG, verifies
                                              the failure path is graceful).
    python vision_test.py --fixtures        — replay every fixture in
                                              tests/fixtures/vision/*.png and
                                              assert each call returns the
                                              expected action verb + coords
                                              within the bbox.
    python vision_test.py --capture NAME    — drive a live Playwright session
                                              against a hotspot and save
                                              a fixture (PNG + flow_context.json)
                                              under tests/fixtures/vision/NAME.
                                              For interactive use during E2E.
    python vision_test.py --live HOTSPOT    — drive Playwright against a
                                              named hotspot and run vision.act
                                              for real. Used as a developer
                                              local sanity check, not CI.

Fixture format — for each `NAME`, two adjacent files:
    tests/fixtures/vision/NAME.png   — viewport screenshot (1280×800 ideal)
    tests/fixtures/vision/NAME.json  — { "flow_context": {...},
                                         "expected_action": "click",
                                         "expected_target_bbox": [x1,y1,x2,y2]
                                                                  in 0-1 ratios,
                                         "min_confidence": 0.6 }

V1 done = 5/8 fixtures green + 3 live (#1 Gemini, #3 NotebookLM, #6 GDoc).
See the `_HOTSPOT_VISION_HINTS` table in research.py for the current hotspot definitions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

# Allow `python vision_test.py` from any cwd.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import vision

FIXTURES_DIR = _HERE / "tests" / "fixtures" / "vision"


# ─────────────────────────────────────────────────────────────────────────
# Fixture loader + assertions
# ─────────────────────────────────────────────────────────────────────────

def _load_fixture(stem: str) -> tuple[bytes, dict]:
    """Return (png_bytes, fixture_meta_dict) for fixture NAME=stem."""
    png_path = FIXTURES_DIR / f"{stem}.png"
    json_path = FIXTURES_DIR / f"{stem}.json"
    if not png_path.exists():
        raise FileNotFoundError(f"fixture image missing: {png_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"fixture metadata missing: {json_path}")
    return png_path.read_bytes(), json.loads(json_path.read_text(encoding="utf-8"))


def _assert_fixture_pass(stem: str, fx: dict, result: vision.ActionResult) -> tuple[bool, str]:
    """Return (passed, msg). Used by --fixtures mode."""
    expected_verb = fx.get("expected_action")
    if expected_verb and result.action != expected_verb:
        return False, f"action mismatch: got {result.action}, expected {expected_verb}"
    min_conf = float(fx.get("min_confidence", 0.6))
    if result.confidence < min_conf:
        return False, f"confidence too low: {result.confidence:.2f} < {min_conf}"
    bbox = fx.get("expected_target_bbox")
    if bbox and result.action == "click":
        if result.x_ratio is None or result.y_ratio is None:
            return False, "click action without coords"
        x1, y1, x2, y2 = bbox
        if not (x1 <= result.x_ratio <= x2 and y1 <= result.y_ratio <= y2):
            return False, (
                f"coords outside bbox: ({result.x_ratio:.2f}, {result.y_ratio:.2f}) "
                f"not in [{x1:.2f}-{x2:.2f}, {y1:.2f}-{y2:.2f}]"
            )
    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────
# Smoke mode — no real network call required
# ─────────────────────────────────────────────────────────────────────────

async def smoke_test() -> int:
    """Verify VisionClient constructs, schema dataclasses serialize, and
    a deliberately-broken API key fails gracefully (declare_failure, no raise).
    Doesn't require valid credentials — uses a dummy key."""
    print("--- smoke test: API surface --------------------------------")

    # 1. ImgMeta + ActionResult are frozen dataclasses, JSON-serializable.
    meta = vision.ImgMeta(width_css=1280, height_css=800, dpr=1.5, captured_at=1.0)
    res = vision.ActionResult(
        action="click", reason="test", confidence=0.9,
        next_expected_state="dialog open",
        x_ratio=0.5, y_ratio=0.5, model_used=vision.MODEL_SONNET,
    )
    assert json.dumps(asdict(meta)), "ImgMeta should round-trip"
    assert json.dumps(asdict(res)), "ActionResult should round-trip"
    print("  [ok] dataclasses round-trip JSON")

    # 2. VisionMetrics records and reports
    m = vision.VisionMetrics()
    m.record(res)
    assert m.call_count == 1, "metrics should count"
    assert len(m.latencies_ms) == 1, "latencies recorded"
    m.reset()
    assert m.call_count == 0, "reset works"
    print("  [ok] VisionMetrics record + reset")

    # 3. _pick_model routing — instantiate a client with dummy key
    client = vision.VisionClient(api_key="sk-ant-dummy")
    assert client._pick_model({}, False) == vision.MODEL_SONNET, "default = sonnet"
    assert client._pick_model({"phase": 0}, False) == vision.MODEL_OPUS, "phase 0 = opus"
    assert client._pick_model({}, True) == vision.MODEL_OPUS, "high_stakes = opus"
    assert client._pick_model({"attempts": 2}, False) == vision.MODEL_OPUS, "retry = opus"
    print("  [ok] _pick_model routing")

    # 4. Bad API key → graceful failure path. Send a 1×1 PNG.
    tiny_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63f8cf000000000300010c00012e8a4f600000000049454e44ae426082"
    )
    fc = {"workflow_name": "smoke", "phase": 1, "current_step": "test"}
    img_meta = vision.ImgMeta(width_css=1, height_css=1, dpr=1.0, captured_at=0.0)
    result = await client.ask(tiny_png, img_meta, fc, timeout_s=5.0)
    assert result.action in ("declare_failure", "escalate_to_cua"), (
        f"bad-key call should fail gracefully, got action={result.action}"
    )
    assert result.confidence == 0.0, "failure result has zero confidence"
    print(f"  [ok] bad-key path returns declare_failure (reason: {result.reason[:60]})")

    # 5. with_vision_fallback contract — primary success returns directly
    async def primary_ok():
        return "primary-ran"
    out = await vision.with_vision_fallback(
        page=None, primary_fn=primary_ok,
        flow_context={"workflow_name": "smoke"},
        vision=client,
    )
    assert out == "primary-ran", "primary success should pass through"
    print("  [ok] with_vision_fallback: primary success path")

    print("--- smoke test PASSED --------------------------------------")
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Fixtures mode — replay saved (image, flow_context) pairs
# ─────────────────────────────────────────────────────────────────────────

async def fixtures_mode() -> int:
    """Load all fixtures from FIXTURES_DIR, run each through ask(), report."""
    if not _check_real_api_key():
        print("ERROR: ANTHROPIC_API_KEY not set — fixtures mode "
              "needs a real key. Use --smoke for an offline sanity check.")
        return 2

    fixtures = sorted(p.stem for p in FIXTURES_DIR.glob("*.png"))
    if not fixtures:
        print(f"No fixtures in {FIXTURES_DIR} yet. "
              "Use --capture NAME during a live E2E run to collect them.")
        return 0

    client = vision.VisionClient()
    passed = 0
    failed = 0
    print(f"--- fixtures mode: {len(fixtures)} fixture(s) -------------")
    for stem in fixtures:
        try:
            png, fx = _load_fixture(stem)
        except FileNotFoundError as e:
            print(f"  [{stem}] SKIP: {e}")
            continue
        flow_context = fx.get("flow_context") or {}
        # Use the screenshot's actual viewport from the fixture meta if
        # captured, otherwise default.
        vp = (flow_context.get("viewport") or {})
        meta = vision.ImgMeta(
            width_css=int(vp.get("w") or 1280),
            height_css=int(vp.get("h") or 800),
            dpr=float(vp.get("dpr") or 1.0),
            captured_at=0.0,
        )
        result = await client.ask(png, meta, flow_context)
        ok, msg = _assert_fixture_pass(stem, fx, result)
        if ok:
            passed += 1
            print(f"  [ok] {stem}: action={result.action} conf={result.confidence:.2f} "
                  f"({result.latency_ms:.0f}ms, {result.model_used})")
        else:
            failed += 1
            print(f"  [FAIL] {stem}: {msg} "
                  f"(reason: {result.reason[:60]})")

    p95 = client.metrics.p95()
    cost = client.metrics.estimated_cost_usd()
    print(f"--- {passed}/{passed+failed} passed; p95 latency {p95:.0f}ms; "
          f"estimated cost ${cost:.4f} ---")
    return 0 if failed == 0 else 1


# ─────────────────────────────────────────────────────────────────────────
# Capture mode — interactive fixture collection during live E2E
# ─────────────────────────────────────────────────────────────────────────

async def capture_mode(name: str) -> int:
    """Drive Playwright to whatever URL is in CAPTURE_URL env (or prompt),
    take a screenshot, ask the user for flow_context+expected fields, and
    save the fixture pair to FIXTURES_DIR/NAME.png + .json.

    Designed to be run during E2E by the developer when a real hotspot
    page is loaded in the test browser. The simplest integration: launch
    the test browser headed, navigate to the hotspot, then run this
    against the SAME profile (CAPTURE_PROFILE_DIR env)."""
    if not name or "/" in name or "\\" in name:
        print("ERROR: --capture NAME must be a simple identifier (no slashes)")
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed — capture mode unavailable")
        return 2

    capture_url = os.environ.get("CAPTURE_URL")
    if not capture_url:
        capture_url = input("URL to capture (e.g. paste your Gemini share dialog): ").strip()
    if not capture_url:
        print("ERROR: no URL provided")
        return 2

    profile_dir = os.environ.get("CAPTURE_PROFILE_DIR")
    print(f"--- capture mode: {name} ----------------------------------")
    async with async_playwright() as pw:
        if profile_dir:
            ctx = await pw.chromium.launch_persistent_context(
                profile_dir, headless=False, viewport={"width": 1280, "height": 800},
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        else:
            browser = await pw.chromium.launch(headless=False)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()
        await page.goto(capture_url, wait_until="domcontentloaded")
        input("-> Position the page where you want the screenshot, then press Enter...")

        client = vision.VisionClient()
        png, meta = await client.screenshot(page)

        # Prompt for the fixture metadata. Keep it terse — the developer
        # knows what they're capturing.
        print("\nFixture metadata (Enter to skip a field):")
        workflow_name = input("  workflow_name: ").strip() or "unknown"
        current_step = input("  current_step: ").strip() or "unknown"
        platform = input("  platform: ").strip() or "unknown"
        phase = input("  phase (int): ").strip() or "0"
        expected_action = input("  expected_action [click]: ").strip() or "click"
        bbox_raw = input("  expected_target_bbox as 'x1,y1,x2,y2' ratios (Enter to skip): ").strip()
        bbox = None
        if bbox_raw:
            try:
                parts = [float(p) for p in bbox_raw.split(",")]
                if len(parts) == 4:
                    bbox = parts
            except ValueError:
                pass

        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        png_path = FIXTURES_DIR / f"{name}.png"
        json_path = FIXTURES_DIR / f"{name}.json"
        png_path.write_bytes(png)
        json_path.write_text(json.dumps({
            "flow_context": {
                "workflow_name": workflow_name,
                "phase": int(phase) if phase.isdigit() else 0,
                "current_step": current_step,
                "platform": platform,
                "viewport": {"w": meta.width_css, "h": meta.height_css, "dpr": meta.dpr},
            },
            "expected_action": expected_action,
            **({"expected_target_bbox": bbox} if bbox else {}),
            "min_confidence": 0.6,
        }, indent=2), encoding="utf-8")
        print(f"  [ok] saved {png_path}")
        print(f"  [ok] saved {json_path}")

        if profile_dir:
            await ctx.close()
        else:
            await browser.close()
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Live mode — drive Playwright + run vision.act for real
# ─────────────────────────────────────────────────────────────────────────

async def live_mode(hotspot: str) -> int:
    """Stub — V1 ships with this disabled. Live exercise of vision.act
    against a real Playwright session belongs in the same harness as
    capture_mode but with assertions instead of saving. Plumb when the
    first 3 fixtures are collected."""
    print(f"live mode for hotspot '{hotspot}' is not yet implemented in V1. "
          f"Use --capture {hotspot} to collect a fixture first, then --fixtures "
          f"to replay it.")
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _check_real_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def main() -> int:
    p = argparse.ArgumentParser(description="V1 test harness for vision.py")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--smoke", action="store_true",
                   help="API surface sanity check; no network required")
    g.add_argument("--fixtures", action="store_true",
                   help="Replay all saved fixtures in tests/fixtures/vision/")
    g.add_argument("--capture", metavar="NAME",
                   help="Capture a fixture NAME from a live Playwright session")
    g.add_argument("--live", metavar="HOTSPOT",
                   help="Drive Playwright + run vision.act against a hotspot")
    args = p.parse_args()

    if args.smoke:
        return asyncio.run(smoke_test())
    if args.fixtures:
        return asyncio.run(fixtures_mode())
    if args.capture:
        return asyncio.run(capture_mode(args.capture))
    if args.live:
        return asyncio.run(live_mode(args.live))
    return 2


if __name__ == "__main__":
    sys.exit(main())
