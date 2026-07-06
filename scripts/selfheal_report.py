#!/usr/bin/env python3
"""Phoenix self-heal SELECTOR engine — shadow-log observability report (read-only).

Summarises what the PX-0 shadow layer observed, per (platform, intent):
  * how often the outcome predicate PASSED on the live verify path,
  * how many WOULD-HEAL opportunities were seen (predicate failed → PX-2 would
    attempt a heal here),
  * probe coverage (how many DOM elements probe_region returned).
Then checks the PX-0 Definition of Done: all 6 P2 intents
observed, probe deployed on all 3 platforms, ≥1 heal shadowed per platform.

It parses the structured JSONL the pipeline already emits
(``logs/selfheal_shadow.jsonl``) — purely read-only, so it can never affect a
run. This is the deliberately-zero-risk form of PX-0 telemetry.

    python scripts/selfheal_report.py [path/to/selfheal_shadow.jsonl ...]

If no path is given it tries ./logs/selfheal_shadow.jsonl then
./selfheal_shadow.jsonl. Honours $DG_SELFHEAL_SHADOW_LOG as a default too.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

# The 6 P2 intents PX-0 wires + the 3 platforms (kept local so the report has no
# import dependency on the runtime module — it can run anywhere the log lands).
INTENTS = (
    "chatgpt.enable_deep_research",
    "gemini.enable_deep_research",
    "claude.enable_deep_research",
    "chatgpt.select_model",
    "gemini.select_model",
    "claude.select_model",
)
PLATFORMS = ("chatgpt", "gemini", "claude")


def _default_paths() -> list[str]:
    env = os.environ.get("DG_SELFHEAL_SHADOW_LOG")
    cands = [env] if env else []
    cands += [os.path.join("logs", "selfheal_shadow.jsonl"), "selfheal_shadow.jsonl"]
    return [p for p in cands if p and os.path.exists(p)]


def load_records(paths: list[str]) -> list[dict]:
    """Read + parse shadow JSONL from each path. Malformed lines are skipped
    (each line is its own object, so a torn write can't break the report)."""
    out: list[dict] = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(rec, dict):
                        out.append(rec)
        except OSError:
            continue
    return out


def summarize(records: list[dict]) -> dict:
    """Aggregate records into a pure, testable summary structure."""
    per_intent: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "pass": 0, "would_heal": 0, "probe_sum": 0, "probe_max": 0,
                 "resolver_seen": 0, "resolver_matched": 0, "heal_conf_sum": 0.0, "heal_conf_n": 0,
                 "heal_attempts": 0, "heal_acted": 0, "heal_ok": 0}
    )
    platforms_seen: set[str] = set()
    for rec in records:
        intent = rec.get("intent") or "?"
        s = per_intent[intent]
        s["total"] += 1
        if rec.get("outcome_pass") is True:
            s["pass"] += 1
        if rec.get("would_heal") is True:
            s["would_heal"] += 1
        pc = rec.get("probe_count")
        if isinstance(pc, int):
            s["probe_sum"] += pc
            s["probe_max"] = max(s["probe_max"], pc)
        # PX-2 telemetry. Shadow records (resolved_by="shadow") carry the heal
        # DECISION (did the resolver find a candidate?); heal records
        # (resolved_by="heal") carry the ACTIVATION outcome (acted/healed).
        if "heal_match_found" in rec:
            s["resolver_seen"] += 1
            if rec.get("heal_match_found") is True:
                s["resolver_matched"] += 1
            hc = rec.get("heal_confidence")
            if isinstance(hc, (int, float)):
                s["heal_conf_sum"] += float(hc)
                s["heal_conf_n"] += 1
        if rec.get("resolved_by") == "heal":
            s["heal_attempts"] += 1
            if rec.get("acted") is True:
                s["heal_acted"] += 1
            if rec.get("outcome_pass") is True:
                s["heal_ok"] += 1
        plat = rec.get("platform")
        if plat:
            platforms_seen.add(plat)

    intents_seen = set(per_intent)
    heals_by_platform = {p: 0 for p in PLATFORMS}
    for intent, s in per_intent.items():
        plat = intent.split(".", 1)[0]
        if plat in heals_by_platform:
            heals_by_platform[plat] += s["would_heal"]

    return {
        "records": len(records),
        "per_intent": {k: dict(v) for k, v in per_intent.items()},
        "platforms_seen": sorted(platforms_seen),
        "intents_seen": sorted(intents_seen),
        "heals_by_platform": heals_by_platform,
        "dod": {
            "all_six_intents": set(INTENTS).issubset(intents_seen),
            "all_three_platforms": set(PLATFORMS).issubset(platforms_seen),
            "heal_shadowed_per_platform": all(heals_by_platform[p] > 0 for p in PLATFORMS),
        },
    }


def format_report(summary: dict) -> str:
    lines = []
    lines.append("=" * 68)
    lines.append("Phoenix self-heal - PX-0 shadow report")
    lines.append("=" * 68)
    lines.append(f"records: {summary['records']}   platforms: {', '.join(summary['platforms_seen']) or '(none)'}")
    lines.append("")
    lines.append(f"{'intent':<34}{'n':>5}{'pass':>6}{'pass%':>7}{'wheal':>7}{'probe~':>8}")
    lines.append("-" * 68)
    for intent in INTENTS:
        s = summary["per_intent"].get(intent)
        if not s:
            lines.append(f"{intent:<34}{'-':>5}{'-':>6}{'-':>7}{'-':>7}{'-':>8}   (not observed)")
            continue
        n = s["total"]
        pct = (100.0 * s["pass"] / n) if n else 0.0
        avg = (s["probe_sum"] / n) if n else 0.0
        lines.append(f"{intent:<34}{n:>5}{s['pass']:>6}{pct:>6.0f}%{s['would_heal']:>7}{avg:>8.1f}")
    # any intents in the log that aren't one of the 6 expected
    extra = [i for i in summary["intents_seen"] if i not in INTENTS]
    for intent in extra:
        s = summary["per_intent"][intent]
        lines.append(f"{intent:<34}{s['total']:>5}{s['pass']:>6}{'':>7}{s['would_heal']:>7}{'':>8}   (UNEXPECTED)")
    lines.append("-" * 68)
    dod = summary["dod"]
    lines.append("PX-0 Definition of Done:")
    lines.append(f"  [{'x' if dod['all_six_intents'] else ' '}] all 6 P2 intents observed")
    lines.append(f"  [{'x' if dod['all_three_platforms'] else ' '}] probe deployed on all 3 platforms")
    heals = ", ".join(f"{p}:{summary['heals_by_platform'][p]}" for p in PLATFORMS)
    lines.append(f"  [{'x' if dod['heal_shadowed_per_platform'] else ' '}] >=1 heal shadowed per platform ({heals})")
    # PX-2 — resolver match quality (shadow) + activation results (heal records).
    rows = [(i, s) for i in INTENTS if (s := summary["per_intent"].get(i))
            and (s["resolver_seen"] or s["heal_attempts"])]
    if rows:
        lines.append("")
        lines.append("PX-2 heal resolver / activation:")
        lines.append(f"{'intent':<34}{'rslv':>6}{'match':>7}{'acts':>6}{'ok':>5}")
        lines.append("-" * 58)
        for intent, s in rows:
            mr = f"{(100.0 * s['resolver_matched'] / s['resolver_seen']):.0f}%" if s["resolver_seen"] else "-"
            lines.append(f"{intent:<34}{s['resolver_seen']:>6}{mr:>7}{s['heal_acted']:>6}{s['heal_ok']:>5}")
    # PX-4 — drift canary: anchor-strength early warning per intent. A heal rests on
    # the durable anchor semantic_match locked onto; a weak/falling confidence is the
    # drift signal (robust to the noisy fingerprint). 'weak' can be benign (a control
    # that doesn't exist, e.g. ChatGPT has no P2 model picker). Floor mirrors
    # selfheal._DRIFT_CONF_FLOOR (kept inline so the report stays import-free).
    drift_rows = [(i, s) for i in INTENTS if (s := summary["per_intent"].get(i)) and s["resolver_seen"]]
    if drift_rows:
        lines.append("")
        lines.append("PX-4 drift canary (anchor strength):")
        lines.append(f"{'intent':<34}{'found%':>7}{'conf~':>7}  verdict")
        lines.append("-" * 60)
        for intent, s in drift_rows:
            seen = s["resolver_seen"]
            fr = (s["resolver_matched"] / seen) if seen else 0.0
            mc = (s["heal_conf_sum"] / s["heal_conf_n"]) if s["heal_conf_n"] else 0.0
            verdict = "DRIFT" if (seen and fr < 1.0) else ("weak" if mc < 0.35 else "stable")
            lines.append(f"{intent:<34}{100.0 * fr:>6.0f}%{mc:>7.2f}  {verdict}")
    lines.append("=" * 68)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = argv or _default_paths()
    if not paths:
        print("no shadow log found (looked for logs/selfheal_shadow.jsonl). "
              "Run with DG_SELFHEAL_ENABLED=1 during a P2 run to generate one.")
        return 0
    records = load_records(paths)
    print(format_report(summarize(records)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
