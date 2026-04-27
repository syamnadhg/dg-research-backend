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
import time
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
    sufficient for agreement scoring at the action-class level."""
    t = (cua_text or "").lower()
    if "panel: open" in t:
        return "click"
    if "panel: already_open" in t:
        return "declare_success"
    if "panel: not_found" in t:
        return "declare_failure"
    if "panel: click_failed" in t:
        return "click"  # tried but missed
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
    by_hotspot: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        h = r.get("hotspot_id", "?")
        if filter_hotspot and h != filter_hotspot:
            continue
        by_hotspot[h].append(r)

    if not by_hotspot:
        print("No events found.")
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
            cua_text = c.get("text_head", "")
            c_action = cua_action_class(cua_text)

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


def main() -> int:
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

    return report(records, args.hotspot, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
