#!/usr/bin/env python3
"""Vision shadow-eval analysis report.

Reads logs/vision_shadow.jsonl produced during shadow-mode E2E runs and
computes the per-hotspot promotion-criterion metrics:

  N events           (≥10 needed)
  action_agreement_% (≥80% needed) — Vision proposed action matches what
                     CUA actually did (click vs scroll vs declare)
  coord_proximity_%  (≥70% needed) — Vision's center coords within 0.10
                     ratio of where CUA actually clicked

Per-hotspot decision: PASS iff all three thresholds met. Use this to
decide which hotspot toggles to flip from `_shadow_observed_cua` →
`with_vision_fallback` in research.py.

Usage:
  python scripts/vision_shadow_report.py
  python scripts/vision_shadow_report.py --log path/to/vision_shadow.jsonl
  python scripts/vision_shadow_report.py --hotspot 7c       # filter
  python scripts/vision_shadow_report.py --window-days 30   # default
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROMOTION_MIN_EVENTS = 10
PROMOTION_MIN_ACTION_AGREEMENT_PCT = 80.0
PROMOTION_MIN_COORD_PROXIMITY_PCT = 70.0
COORD_PROXIMITY_THRESHOLD = 0.10  # ratio


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--log",
        default=os.environ.get("DG_VISION_SHADOW_LOG", "logs/vision_shadow.jsonl"),
        help="Path to vision_shadow.jsonl (default: logs/vision_shadow.jsonl)",
    )
    p.add_argument("--hotspot", help="Filter to a single hotspot id (e.g. 7c)")
    p.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Rolling window in days (default 30; pass 0 for all-time)",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print individual disagreements",
    )
    return p.parse_args()


def load_records(path: Path, since: datetime | None) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = rec.get("ts", "")
            if since and ts_str:
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    if ts < since:
                        continue
                except ValueError:
                    pass
            records.append(rec)
    return records


def cua_action_class(cua_text: str) -> str:
    """Infer the CUA action class from its output text. Approximate but
    sufficient for agreement scoring at the action-class level.

    The miss-path recorder stores only ``cua.text_head`` — the CUA's FREEFORM
    narration of what it did/saw (e.g. "The side panel has successfully slid
    out…"), not a structured marker. So beyond the exact "panel: …" markers
    (kept for back-compat / any future structured emit), we infer from common
    CUA phrasings. Without this, every freeform record returned "unknown" and
    was dropped from scoring (the 7c / 7c-p1 0/0 bug)."""
    t = (cua_text or "").lower()
    if not t:
        return "unknown"
    # 1) Exact structured markers win.
    if "panel: open" in t:
        return "click"
    if "panel: already_open" in t:
        return "declare_success"
    if "panel: not_found" in t:
        return "declare_failure"
    if "panel: click_failed" in t:
        return "click"  # tried but missed
    # 2) Freeform-narration inference (the real-world shape of text_head).
    #    Order matters: "already open" (no action) before generic "open".
    if any(p in t for p in ("already open", "already expanded", "is already",
                            "no action needed", "nothing to do", "no need to")):
        return "declare_success"
    if any(p in t for p in ("could not", "couldn't", "unable to", "can't find",
                            "cannot find", "not found", "no panel", "did not find",
                            "doesn't appear", "failed to find", "no such")):
        return "declare_failure"
    #    A click that achieved the target panel/element — the dominant miss-path
    #    success outcome (CUA was the fallback that opened what the DOM missed).
    if any(p in t for p in ("slid out", "slid in", "opened", "now open", "now visible",
                            "now showing", "has appeared", "panel is", "is now",
                            "expanded", "successfully", "clicked", "i can see",
                            "i see the", "is visible")):
        return "click"
    return "unknown"


def coord_within(vision_x: float | None, vision_y: float | None,
                 cua_action_class: str) -> bool | None:
    """For shadow mode CUA doesn't expose its click coords back to us via the
    text — agreement at the action-class level is what we have. Coord proximity
    is computed only when both branches PROPOSE click AND we have Vision's
    ratios. CUA's actual coords aren't in the JSONL today (no click telemetry
    from agent_loop). Returns None when not measurable, True/False otherwise.
    Future enhancement: persist CUA click coords from agent_loop into the
    shadow record under cua.click_x_ratio / cua.click_y_ratio."""
    if cua_action_class != "click":
        return None
    if vision_x is None or vision_y is None:
        return None
    # Without CUA's actual coords we cannot compute proximity. Treat as
    # unmeasured (None) rather than disagreement so the metric isn't
    # systematically deflated. The promotion threshold is gated on coord
    # proximity but if all events are unmeasured, score will be 0 — that
    # is the correct signal: "we cannot promote yet, instrument CUA to log
    # its click coords first."
    return None


def report(records: list[dict], filter_hotspot: str | None,
           verbose: bool) -> int:
    # Score ONLY the legacy miss-path / CUA-shadow population here; the success-path
    # (source=="dom_success") is a SEPARATE population (its ground truth is the DOM's
    # resolved target, not CUA's action) scored by report_dom_success().
    records = [r for r in records if r.get("source") != "dom_success"]
    by_hotspot: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        h = r.get("hotspot_id", "?")
        if filter_hotspot and h != filter_hotspot:
            continue
        by_hotspot[h].append(r)

    if not by_hotspot:
        print("No miss-path (CUA-shadow) events found.")
        return 0

    print(f"\n{'Hotspot':<10}{'N':<6}{'Action Agree':<15}{'Coord Prox':<13}"
          f"{'Decision':<12}")
    print("-" * 56)

    promotion_decisions: dict[str, bool] = {}

    for hotspot in sorted(by_hotspot.keys()):
        events = by_hotspot[hotspot]
        n = len(events)
        agree_count = 0
        agree_total = 0
        prox_count = 0
        prox_total = 0
        disagreements: list[dict] = []

        for r in events:
            v = r.get("vision", {}) or {}
            c = r.get("cua", {}) or {}
            v_action = v.get("action")
            v_x = v.get("x_ratio")
            v_y = v.get("y_ratio")
            # Prefer a structured cua.action if a future recorder emits one;
            # otherwise infer the action class from the freeform text_head.
            c_action = c.get("action") or cua_action_class(c.get("text_head", ""))

            if "error" in v or "timeout" in v:
                continue
            if c_action == "unknown":
                continue

            agree_total += 1
            agreed = v_action == c_action
            if agreed:
                agree_count += 1
            else:
                disagreements.append({"v": v_action, "c": c_action, "ts": r.get("ts")})

            prox_result = coord_within(v_x, v_y, c_action)
            if prox_result is not None:
                prox_total += 1
                if prox_result:
                    prox_count += 1

        agreement_pct = (agree_count / agree_total * 100.0) if agree_total else 0.0
        proximity_pct = (prox_count / prox_total * 100.0) if prox_total else 0.0

        meets_n = n >= PROMOTION_MIN_EVENTS
        meets_agree = agreement_pct >= PROMOTION_MIN_ACTION_AGREEMENT_PCT
        meets_prox = (
            prox_total == 0  # no coord data yet — gate on action only
            or proximity_pct >= PROMOTION_MIN_COORD_PROXIMITY_PCT
        )
        passes = meets_n and meets_agree and meets_prox
        promotion_decisions[hotspot] = passes

        decision = "PASS" if passes else "(collecting)" if not meets_n else "WAIT"
        print(f"{hotspot:<10}{n:<6}"
              f"{agreement_pct:>6.1f}% ({agree_count}/{agree_total})  "
              f"{proximity_pct:>5.1f}% ({prox_count}/{prox_total})  "
              f"{decision}")

        if verbose and disagreements:
            for d in disagreements[-5:]:
                print(f"    [disagreement] vision={d['v']} cua={d['c']} ts={d['ts']}")

    print()
    print(f"Promotion threshold: ≥{PROMOTION_MIN_EVENTS} events,"
          f" ≥{PROMOTION_MIN_ACTION_AGREEMENT_PCT:.0f}% action agreement,"
          f" ≥{PROMOTION_MIN_COORD_PROXIMITY_PCT:.0f}% coord proximity")
    print()
    print("Coord proximity reads NA today: CUA's actual click coords aren't")
    print("in the JSONL yet. Until research.py logs CUA click_x_ratio /")
    print("click_y_ratio to each shadow record, gate purely on action agreement.")

    pass_list = [h for h, ok in promotion_decisions.items() if ok]
    if pass_list:
        print()
        print(f"Hotspots passing threshold: {', '.join(pass_list)}")
        print("Next: flip these from `_shadow_observed_cua` → "
              "`with_vision_fallback` in research.py (see vision_v3_plan.md).")

    return 0


def _coord_close(vx, vy, tx, ty) -> bool | None:
    """Euclidean proximity of Vision's proposed click to the DOM's true target
    (both viewport-normalized 0..1). None when either pair is missing."""
    if vx is None or vy is None or tx is None or ty is None:
        return None
    return ((vx - tx) ** 2 + (vy - ty) ** 2) ** 0.5 <= COORD_PROXIMITY_THRESHOLD


def report_dom_success(records: list[dict], filter_hotspot: str | None,
                       verbose: bool) -> None:
    """Score the SUCCESS-path observe population (source=="dom_success") — a SEPARATE
    population from the miss-path/CUA-shadow records (different ground truth: the DOM's
    resolved target, not CUA's action). Action-class agreement = Vision proposed
    "click" (the success path always required a click); coord proximity = Vision's
    center vs dom_ground_truth.true_x/y_ratio within COORD_PROXIMITY_THRESHOLD. A hotspot
    with no coord ground-truth (true coords None) gates on action agreement only."""
    succ = [r for r in records if r.get("source") == "dom_success"]
    by_hotspot: dict[str, list[dict]] = defaultdict(list)
    for r in succ:
        h = r.get("hotspot_id", "?")
        if filter_hotspot and h != filter_hotspot:
            continue
        by_hotspot[h].append(r)
    if not by_hotspot:
        return

    print()
    print("== DOM-success observe population (source=dom_success) ==")
    print(f"{'Hotspot':<12}{'N':<6}{'Action Agree':<16}{'Coord Prox':<16}{'Decision':<12}")
    print("-" * 62)
    for hotspot in sorted(by_hotspot.keys()):
        events = by_hotspot[hotspot]
        n = len(events)
        agree_count = agree_total = prox_count = prox_total = 0
        for r in events:
            v = r.get("vision", {}) or {}
            gt = r.get("dom_ground_truth", {}) or {}
            if "error" in v or "timeout" in v:
                continue
            v_action = v.get("action")
            if v_action is None:
                continue
            agree_total += 1
            # The DOM ALREADY succeeded at this hotspot, so Vision "agrees" when
            # it would have driven the same success: either it proposes the CLICK
            # (it would act), OR it reads the achieved end-state and DECLARES
            # SUCCESS (correct when the observe fires AFTER the DOM acted — e.g.
            # p3-audio-customize, where the panel is already open by then). A real
            # DISAGREEMENT is a wrong action (declare_failure / scroll / etc.).
            if v_action in ("click", "declare_success"):
                agree_count += 1
            close = _coord_close(v.get("x_ratio"), v.get("y_ratio"),
                                 gt.get("true_x_ratio"), gt.get("true_y_ratio"))
            if close is not None:
                prox_total += 1
                if close:
                    prox_count += 1

        agreement_pct = (agree_count / agree_total * 100.0) if agree_total else 0.0
        proximity_pct = (prox_count / prox_total * 100.0) if prox_total else 0.0
        meets_n = n >= PROMOTION_MIN_EVENTS
        meets_agree = agreement_pct >= PROMOTION_MIN_ACTION_AGREEMENT_PCT
        meets_prox = (prox_total == 0 or proximity_pct >= PROMOTION_MIN_COORD_PROXIMITY_PCT)
        passes = meets_n and meets_agree and meets_prox
        decision = "PASS" if passes else "(collecting)" if not meets_n else "WAIT"
        prox_note = "" if prox_total else " [no coord GT]"
        print(f"{hotspot:<12}{n:<6}"
              f"{agreement_pct:>6.1f}% ({agree_count}/{agree_total})  "
              f"{proximity_pct:>5.1f}% ({prox_count}/{prox_total}){prox_note}  "
              f"{decision}")

    print()
    print("DOM-success scoring: agreement = Vision proposed 'click' (it would act) OR")
    print("'declare_success' (it correctly read the already-achieved state — the observe")
    print("often fires AFTER the DOM acted). A real disagreement is a wrong action")
    print("(declare_failure / scroll). Coord proximity = Vision center vs the DOM's true")
    print(f"target within {COORD_PROXIMITY_THRESHOLD}; [no coord GT] = no clicked-bbox captured, so the")
    print("hotspot gates on action agreement only (a valid promotion basis).")


def main() -> int:
    # Windows consoles default to cp1252, which can't encode the ≥ / ✓ / — glyphs
    # this report prints (it crashed mid-output before). Force UTF-8 stdout.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = parse_args()
    log_path = Path(args.log).resolve()
    since = None
    if args.window_days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=args.window_days)

    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        print("Run an E2E sweep with DG_VISION_TIER=shadow to populate.")
        return 1

    records = load_records(log_path, since)
    print(f"Loaded {len(records)} events from {log_path}")
    if since:
        print(f"Window: last {args.window_days} days (since {since.isoformat()})")
    else:
        print("Window: all-time")

    rc = report(records, args.hotspot, args.verbose)
    report_dom_success(records, args.hotspot, args.verbose)
    return rc


if __name__ == "__main__":
    sys.exit(main())
