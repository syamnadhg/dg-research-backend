"""PX-0 foundation guards for the Phoenix self-healing SELECTOR engine.

Covers the five C1 pieces of ``selfheal.py``: intent/outcome contracts, the
``probe_region`` scanner, the ``selectors.json`` schema + atomic locked overlay,
the ``decide_toggle`` pre-act guard (the #709 firewall), and the kill-switch +
shadow log. Also pins the PX-0 invariant that NOTHING is wired into the pipeline
yet (research.py must not reference selfheal until C2).

Pure / hermetic: the async ``probe_region`` is driven with a fake page via
``asyncio.run`` (no pytest-asyncio dependency), and every filesystem path is
redirected into ``tmp_path`` so no test touches ``~/.super-research``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

import selfheal


# ── fixtures / helpers ────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect all selfheal state into tmp_path and start every test flag-OFF."""
    monkeypatch.setenv("DG_SELFHEAL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DG_SELFHEAL_SELECTORS", str(tmp_path / "state" / "selectors.json"))
    monkeypatch.setenv("DG_SELFHEAL_SHADOW_LOG", str(tmp_path / "logs" / "selfheal_shadow.jsonl"))
    monkeypatch.delenv("DG_SELFHEAL_ENABLED", raising=False)
    monkeypatch.delenv("DG_SELFHEAL_INTENTS", raising=False)


class FakePage:
    """Minimal Playwright-page double: records evaluate() calls, returns canned."""

    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    async def evaluate(self, js, params=None):
        self.calls.append((js, params))
        return self.ret


class BoomPage:
    async def evaluate(self, js, params=None):
        raise RuntimeError("no live page")


def _run(coro):
    return asyncio.run(coro)


# ── 1. Intent / outcome contracts ─────────────────────────────────────────────
def test_six_intents_cover_the_p2_surfaces():
    it = selfheal.load_intents()
    assert set(it) == {
        f"{p}.{i}"
        for p in ("chatgpt", "gemini", "claude")
        for i in ("enable_deep_research", "select_model")
    }


def test_every_intent_is_schema_valid():
    # The embedded baseline must itself satisfy the validator.
    selfheal._validate_intents(selfheal._INTENTS)
    for key, it in selfheal.load_intents().items():
        assert key == f"{it['platform']}.{it['intent_id']}"
        assert it["type"] in selfheal.INTENT_TYPES
        assert isinstance(it["outcome_predicate"], str) and it["outcome_predicate"]
        assert isinstance(it["signal_hints"], dict)
        assert it["tier_sequence"] and all(t in selfheal.KNOWN_TIERS for t in it["tier_sequence"])
        assert it["irreversible"] is False  # none of the 6 P2 setup intents send/publish
        assert it["region"] in selfheal.REGIONS


def test_signal_hints_lead_with_durable_signals_never_class():
    # §3.2: rank by accessible name + role; CSS class is NEVER a signal hint.
    for it in selfheal.load_intents().values():
        hints = it["signal_hints"]
        assert "accessible_name" in hints
        assert "class" not in hints and "cls" not in hints


def test_intents_manifest_file_matches_embedded_baseline():
    # The shipped editable manifest must never drift from the compiled-in baseline.
    path = Path(selfheal.__file__).resolve().parent / "selfheal_intents.json"
    assert path.exists(), "selfheal_intents.json must ship beside selfheal.py"
    assert json.loads(path.read_text(encoding="utf-8")) == selfheal._INTENTS


def test_intents_are_pure_json_serialisable():
    assert json.loads(json.dumps(selfheal._INTENTS)) == selfheal._INTENTS


def test_load_intents_prefers_external_manifest(tmp_path, monkeypatch):
    override = dict(selfheal._INTENTS)
    f = tmp_path / "custom_intents.json"
    f.write_text(json.dumps(override), encoding="utf-8")
    monkeypatch.setenv("DG_SELFHEAL_INTENTS", str(f))
    assert selfheal.load_intents() == override


def test_load_intents_falls_back_to_baseline_on_corrupt_or_missing(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("DG_SELFHEAL_INTENTS", str(bad))
    assert selfheal.load_intents() == selfheal._INTENTS  # corrupt → embedded
    monkeypatch.setenv("DG_SELFHEAL_INTENTS", str(tmp_path / "nope.json"))
    assert selfheal.load_intents() == selfheal._INTENTS  # missing → embedded


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update({"x.y": {**d["claude.select_model"], "platform": "x", "intent_id": "y"}}),
        lambda d: d["claude.select_model"].update({"platform": "bogus"}),
        lambda d: d["claude.select_model"].update({"type": "press"}),
        lambda d: d["claude.select_model"].update({"outcome_predicate": ""}),
        lambda d: d["claude.select_model"].update({"tier_sequence": ["nope"]}),
        lambda d: d["claude.select_model"].update({"irreversible": "yes"}),
        lambda d: d["claude.select_model"].update({"region": "nowhere"}),
        lambda d: d["claude.select_model"].update({"signal_hints": "x"}),
    ],
)
def test_validator_rejects_malformed_intents(mutate):
    import copy as _c

    d = _c.deepcopy(selfheal._INTENTS)
    mutate(d)
    with pytest.raises(ValueError):
        selfheal._validate_intents(d)


def test_validator_accepts_a_dict_spec_region():
    # A spec-dict region is valid per the contract — and must not crash the
    # membership test (the `region in REGIONS` TypeError-on-dict regression).
    import copy as _c

    d = _c.deepcopy(selfheal._INTENTS)
    d["claude.select_model"]["region"] = {"scopeSel": "form", "candSel": "button", "cap": 5}
    assert selfheal._validate_intents(d) is d  # no raise


def test_validator_rejects_key_mismatch():
    with pytest.raises(ValueError):
        selfheal._validate_intents(
            {"gemini.enable_deep_research": {**selfheal._INTENTS["claude.select_model"]}}
        )


# ── 2. DOM probe ───────────────────────────────────────────────────────────────
def test_probe_region_returns_records_and_passes_region_params():
    canned = [{"role": "button", "accessible_name": "deep research", "text": "Deep research",
               "attrs": {}, "bounds": {"x": 1, "y": 2, "w": 3, "h": 4}, "visible": True}]
    page = FakePage(canned)
    out = _run(selfheal.probe_region(page, "composer"))
    assert out == canned
    _, params = page.calls[0]
    assert params["scopeClimb"] == 5 and "contenteditable" in params["scopeSel"]
    assert params["cap"] == selfheal._PROBE_CAP


def test_probe_region_accepts_explicit_spec_dict():
    page = FakePage([])
    _run(selfheal.probe_region(page, {"scopeSel": "form", "candSel": "button", "cap": 7}))
    assert page.calls[0][1]["cap"] == 7


def test_probe_region_unknown_named_region_raises():
    with pytest.raises(KeyError):
        _run(selfheal.probe_region(FakePage([]), "does-not-exist"))


def test_probe_region_bad_arg_type_raises():
    with pytest.raises(TypeError):
        _run(selfheal.probe_region(FakePage([]), 123))


def test_probe_region_eval_failure_returns_empty_list():
    assert _run(selfheal.probe_region(BoomPage(), "menu")) == []


def test_probe_region_non_list_result_coerced_to_empty():
    assert _run(selfheal.probe_region(FakePage({"oops": 1}), "menu")) == []


def test_probe_js_is_read_only_and_extracts_the_unified_shape():
    js = selfheal.PROBE_REGION_JS
    # READ-ONLY: the scanner must never act on the page.
    for forbidden in (".click(", ".focus(", ".dispatchEvent(", "p.click", "scrollIntoView"):
        assert forbidden not in js, f"probe JS must be read-only — found {forbidden!r}"
    # Visibility uses the hardened rule (rects OR offsetParent) + bounds.
    assert "getClientRects()" in js and "offsetParent" in js
    assert "getBoundingClientRect()" in js
    # Emits the §4.4 record fields.
    for field in ("role:", "accessible_name:", "text:", "attrs:", "bounds:", "visible:"):
        assert field in js


# ── 3. Selector registry (selectors.json) ──────────────────────────────────────
_KEY = "gemini|enable_deep_research|f3a9"
_ENTRY = {"strategy_rank": [{"by": "role+name", "value": "button|deep research"}], "confidence": 0.9}


def test_load_selectors_absent_is_empty():
    assert selfheal.load_selectors() == {}


def test_load_selectors_corrupt_is_empty():
    p = selfheal._selectors_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert selfheal.load_selectors() == {}


def test_load_selectors_drops_malformed_entries():
    p = selfheal._selectors_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"badkey": {"x": 1}, "p|i": {"no_rank": True}, _KEY: _ENTRY}), encoding="utf-8")
    assert selfheal.load_selectors() == {_KEY: _ENTRY}


@pytest.mark.parametrize(
    "key,entry,ok",
    [
        (_KEY, _ENTRY, True),
        ("only|one", _ENTRY, False),  # wrong fingerprint-key shape (needs 2 pipes)
        (_KEY, {"strategy_rank": []}, False),  # empty rank
        (_KEY, {"strategy_rank": [{"by": "role"}]}, False),  # rank entry missing 'value'
        (_KEY, {}, False),  # no rank
        (123, _ENTRY, False),  # non-str key
    ],
)
def test_valid_selector_entry(key, entry, ok):
    assert selfheal._valid_selector_entry(key, entry) is ok


def test_persist_selectors_round_trip():
    new = selfheal.persist_selectors(lambda cur: {**cur, _KEY: _ENTRY})
    assert new == {_KEY: _ENTRY}
    assert selfheal.load_selectors() == {_KEY: _ENTRY}


def test_persist_writes_evict_audit_before_the_op():
    selfheal.persist_selectors(lambda cur: {**cur, _KEY: _ENTRY})
    selfheal.persist_selectors(lambda cur: {})  # remove → eviction
    rec = json.loads(selfheal._audit_log_path().read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["event"] == "evict"
    assert _KEY in rec["detail"]["keys"]
    assert rec["pid"] and "stack" in rec  # attributable


def test_persist_no_audit_when_nothing_evicted():
    selfheal.persist_selectors(lambda cur: {**cur, _KEY: _ENTRY})  # pure add
    assert not selfheal._audit_log_path().exists()


def test_persist_mutator_raising_leaves_overlay_unchanged():
    selfheal.persist_selectors(lambda cur: {**cur, _KEY: _ENTRY})

    def boom(cur):
        raise RuntimeError("mutator blew up")

    assert selfheal.persist_selectors(boom) == {_KEY: _ENTRY}
    assert selfheal.load_selectors() == {_KEY: _ENTRY}


def test_lock_is_single_yield_and_uses_its_own_path():
    src = inspect.getsource(selfheal._selfheal_lock)
    yield_stmts = [ln for ln in src.splitlines() if ln.strip().startswith("yield")]
    assert len(yield_stmts) == 1, f"lock contextmanager must yield exactly once, found {yield_stmts}"
    assert "_lock_path()" in src
    # Must NOT borrow the keystore refresh-token lock (false coupling) — copying
    # its shape is fine (and named in the docstring), but the CODE must not CALL
    # it or reuse its hardcoded path constant. Use ast.unparse to drop the
    # docstring + comments and check the executable body only.
    import ast

    fn = ast.parse(src).body[0]
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(getattr(fn.body[0], "value", None), ast.Constant):
        fn.body = fn.body[1:]  # strip docstring
    body = ast.unparse(fn)
    assert "cross_process_refresh_lock" not in body and "_REFRESH_LOCK_PATH" not in body
    # Both platform primitives present (degrade-to-unlocked shape preserved).
    assert "msvcrt" in body and "fcntl" in body


def test_atomic_write_leaves_no_tmp_on_unserialisable_payload():
    # A non-JSON-serialisable payload must fail closed AND leave no orphaned .tmp.
    target = selfheal._selectors_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    assert selfheal._atomic_write_json(target, {"x": {1, 2, 3}}) is False  # set() not serialisable
    assert not target.exists()  # nothing half-written
    assert not target.with_name(target.name + ".tmp").exists()  # no leaked temp


def test_persist_unserialisable_mutator_result_leaves_overlay_and_no_tmp():
    selfheal.persist_selectors(lambda cur: {**cur, _KEY: _ENTRY})
    # mutator returns a dict the writer can't serialise → overlay unchanged, no temp
    bad = selfheal.persist_selectors(lambda cur: {**cur, "p|i|f": {"strategy_rank": [{"by": "x", "value": {1, 2}}]}})
    assert bad == {_KEY: _ENTRY}
    assert not selfheal._selectors_path().with_name(selfheal._selectors_path().name + ".tmp").exists()


def test_persisted_file_is_valid_json_atomic_write():
    selfheal.persist_selectors(lambda cur: {**cur, _KEY: _ENTRY})
    # whole, parseable file (no torn write); no leftover temp file
    json.loads(selfheal._selectors_path().read_text(encoding="utf-8"))
    assert not selfheal._selectors_path().with_name(selfheal._selectors_path().name + ".tmp").exists()


# ── 4. Pre-act toggle guard (the #709 firewall) ────────────────────────────────
@pytest.mark.parametrize(
    "target_active,opposite_confirmed,expected",
    [
        (True, False, "skip"),
        (True, True, "skip"),  # already-active wins — never act
        (False, True, "act"),
        (False, False, "ambiguous"),
        (None, None, "ambiguous"),  # unreadable state → never blind-click
        (None, True, "act"),
        (None, False, "ambiguous"),
    ],
)
def test_decide_toggle_truth_table(target_active, opposite_confirmed, expected):
    assert selfheal.decide_toggle(target_active, opposite_confirmed) == expected


# ── 5. Kill-switch + shadow log ────────────────────────────────────────────────
def test_kill_switch_default_off():
    assert selfheal.is_enabled() is False


@pytest.mark.parametrize("val,on", [("1", True), ("true", True), ("yes", True),
                                     ("0", False), ("false", False), ("no", False), ("", False)])
def test_kill_switch_truthy_idiom(monkeypatch, val, on):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", val)
    assert selfheal.is_enabled() is on


def test_shadow_log_noop_when_disabled():
    selfheal.shadow_log({"platform": "gemini", "intent": "enable_deep_research", "tier": "heal"})
    assert not Path(selfheal._shadow_log_path()).exists()


def test_shadow_log_writes_and_stamps_ts_when_enabled(monkeypatch):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    rec = {"platform": "gemini", "intent": "enable_deep_research", "tier": "heal",
           "outcome_pass": True, "resolved_by": "shadow", "confidence": 0.8}
    selfheal.shadow_log(rec)
    line = Path(selfheal._shadow_log_path()).read_text(encoding="utf-8").strip().splitlines()[-1]
    j = json.loads(line)
    assert j["platform"] == "gemini" and j["outcome_pass"] is True and j["resolved_by"] == "shadow"
    assert "ts" in j


def test_shadow_log_never_raises_on_bad_path(monkeypatch):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    # point the log at a path whose parent is a FILE → mkdir/open will fail
    blocker = Path(selfheal._shadow_log_path()).parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    selfheal.shadow_log({"platform": "x"})  # must swallow, not raise


# ── PX-0 invariant: the C2 wiring is import-guarded ─────────────────────────────
def test_research_import_of_selfheal_is_guarded():
    """research.py imports selfheal inside a try/except (so an import error can
    never break the pipeline) and tolerates ``selfheal is None``. (The detailed
    flag-gated wiring guards live in test_selfheal_wiring.py.)"""
    research_py = Path(selfheal.__file__).resolve().parent / "research.py"
    src = research_py.read_text(encoding="utf-8", errors="ignore")
    assert "import selfheal" in src
    i = src.index("import selfheal")
    assert "try:" in src[max(0, i - 60):i], "selfheal import must be inside a try/except"
    assert "selfheal = None" in src, "must degrade to None on import failure"
