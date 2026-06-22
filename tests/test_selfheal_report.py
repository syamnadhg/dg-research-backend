"""PX-0 C3 guards — the read-only selfheal_report.py + the golden-corpus seeds.

The report is pure log-parsing (no runtime import), so we exercise its
load/summarize/format/main directly. The golden corpus seeds are pinned to the
documented schema (README.md) and cross-checked against the live selfheal
contracts so a malformed or drifted seed fails CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

import selfheal

_ROOT = Path(__file__).resolve().parent.parent
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "selfheal_golden"


def _load_report():
    spec = importlib.util.spec_from_file_location(
        "selfheal_report", os.path.join(str(_ROOT), "scripts", "selfheal_report.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


report = _load_report()


# ── report: load + summarize + format + main ────────────────────────────────
def _rec(intent, platform, outcome_pass, probe=5):
    return {"platform": platform, "intent": intent, "tier": "builtin",
            "outcome_pass": outcome_pass, "would_heal": not outcome_pass,
            "probe_count": probe, "selector_or_box": None, "resolved_by": "shadow"}


def test_summarize_aggregates_pass_and_would_heal():
    records = [
        _rec("gemini.enable_deep_research", "gemini", True),
        _rec("gemini.enable_deep_research", "gemini", False),
        _rec("claude.select_model", "claude", True),
    ]
    s = report.summarize(records)
    assert s["records"] == 3
    g = s["per_intent"]["gemini.enable_deep_research"]
    assert g["total"] == 2 and g["pass"] == 1 and g["would_heal"] == 1
    assert s["heals_by_platform"]["gemini"] == 1
    assert "gemini" in s["platforms_seen"] and "claude" in s["platforms_seen"]


def test_summarize_dod_flags_complete_corpus():
    # one pass + one fail per intent → all 6 intents, all 3 platforms, heal/plat
    records = []
    for iid in report.INTENTS:
        plat = iid.split(".")[0]
        records.append(_rec(iid, plat, True))
        records.append(_rec(iid, plat, False))
    dod = report.summarize(records)["dod"]
    assert dod["all_six_intents"] and dod["all_three_platforms"]
    assert dod["heal_shadowed_per_platform"]


def test_summarize_tracks_resolver_match_quality():
    # shadow records carry the heal DECISION (heal_match_found)
    records = [
        {"platform": "gemini", "intent": "gemini.enable_deep_research", "resolved_by": "shadow",
         "outcome_pass": False, "would_heal": True, "probe_count": 4, "heal_match_found": True},
        {"platform": "gemini", "intent": "gemini.enable_deep_research", "resolved_by": "shadow",
         "outcome_pass": False, "would_heal": True, "probe_count": 4, "heal_match_found": False},
    ]
    g = report.summarize(records)["per_intent"]["gemini.enable_deep_research"]
    assert g["resolver_seen"] == 2 and g["resolver_matched"] == 1


def test_summarize_tracks_activation_results():
    # heal records (resolved_by="heal") carry the ACTIVATION outcome
    records = [
        {"platform": "gemini", "intent": "gemini.enable_deep_research", "resolved_by": "heal",
         "acted": True, "outcome_pass": True},
        {"platform": "gemini", "intent": "gemini.enable_deep_research", "resolved_by": "heal",
         "acted": True, "outcome_pass": False},
    ]
    g = report.summarize(records)["per_intent"]["gemini.enable_deep_research"]
    assert g["heal_attempts"] == 2 and g["heal_acted"] == 2 and g["heal_ok"] == 1


def test_format_report_shows_px2_section_only_when_heal_data_present():
    plain = report.format_report(report.summarize([_rec("gemini.enable_deep_research", "gemini", True)]))
    assert "PX-2 heal resolver" not in plain  # no heal/resolver telemetry → section omitted
    withheal = report.format_report(report.summarize([
        {"platform": "gemini", "intent": "gemini.enable_deep_research", "resolved_by": "heal",
         "acted": True, "outcome_pass": True}]))
    assert "PX-2 heal resolver / activation:" in withheal


def test_summarize_dod_incomplete_when_missing_platform():
    records = [_rec("gemini.enable_deep_research", "gemini", False)]
    dod = report.summarize(records)["dod"]
    assert not dod["all_six_intents"]
    assert not dod["all_three_platforms"]
    assert not dod["heal_shadowed_per_platform"]


def test_load_records_skips_malformed_lines(tmp_path):
    p = tmp_path / "shadow.jsonl"
    p.write_text(
        json.dumps(_rec("gemini.enable_deep_research", "gemini", True)) + "\n"
        + "{ this is not json\n"
        + "\n"
        + json.dumps(_rec("claude.select_model", "claude", False)) + "\n",
        encoding="utf-8",
    )
    recs = report.load_records([str(p)])
    assert len(recs) == 2  # the two valid lines; junk + blank skipped


def test_format_report_renders_dod_and_intents():
    records = [_rec("gemini.enable_deep_research", "gemini", True)]
    out = report.format_report(report.summarize(records))
    assert "PX-0" in out and "gemini.enable_deep_research" in out
    assert "Definition of Done" in out
    # an unobserved intent is shown as not-observed, not omitted
    assert "chatgpt.select_model" in out


def test_main_runs_on_a_file_and_returns_zero(tmp_path, capsys):
    p = tmp_path / "shadow.jsonl"
    p.write_text(json.dumps(_rec("claude.enable_deep_research", "claude", True)) + "\n", encoding="utf-8")
    assert report.main([str(p)]) == 0
    assert "Phoenix self-heal" in capsys.readouterr().out


def test_main_no_log_is_graceful(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no logs/ here
    monkeypatch.delenv("DG_SELFHEAL_SHADOW_LOG", raising=False)
    assert report.main([]) == 0
    assert "no shadow log found" in capsys.readouterr().out


def test_report_constants_match_runtime_contracts():
    # the report's local copies must not drift from selfheal's truth
    assert set(report.INTENTS) == set(selfheal.load_intents())
    assert set(report.PLATFORMS) == set(selfheal.PLATFORMS)


# ── golden corpus seeds ─────────────────────────────────────────────────────
def _golden_files():
    return sorted(_GOLDEN.glob("*.json"))


def test_golden_corpus_has_seeds():
    files = _golden_files()
    assert files, "golden corpus must ship at least one seed"
    # at least one platform represented (scaffolding seeds all three today)
    plats = {json.loads(f.read_text(encoding="utf-8"))["platform"] for f in files}
    assert plats, "seeds must declare a platform"


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.name)
def test_golden_corpus_seeds_are_schema_valid(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["platform"] in selfheal.PLATFORMS
    assert f"{d['platform']}.{d['intent_id']}" in selfheal.load_intents()
    assert d["region"] in selfheal.REGIONS
    assert isinstance(d.get("ui_fingerprint"), str) and d["ui_fingerprint"]
    ks = d["known_good_selector"]
    assert isinstance(ks, dict) and "by" in ks and "value" in ks
    assert isinstance(d["outcome_predicate"], str) and d["outcome_predicate"]
    # a11y_snapshot must be in the probe_region record shape
    snap = d["a11y_snapshot"]
    assert isinstance(snap, list) and snap
    for el in snap:
        for field in ("role", "accessible_name", "text", "attrs", "bounds", "visible"):
            assert field in el, f"{path.name}: a11y element missing {field!r}"
        assert isinstance(el["attrs"], dict)
        assert set(el["bounds"]) == {"x", "y", "w", "h"}
    # filename encodes platform + fingerprint + intent
    assert path.name == f"{d['platform']}_{d['ui_fingerprint']}_{d['intent_id']}.json"
