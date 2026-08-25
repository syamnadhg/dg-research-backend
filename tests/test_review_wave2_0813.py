"""Wave 2 of the 2026-08-13 repair plan — the backend review remainder.

Four findings, and one of them was found by neither reviewer:

  4. `_looks_like_our_backend` never stripped `.exe`, so the Windows console
     script — the documented way to start the backend — read as a STRANGER.
     When it was later orphaned and still holding the port, the pre-flight
     printed "already in use by something that is not Super Research" and
     refused to boot. Fail-safe, but a permanent refusal on the one platform
     that needs the reclaim most.

  5. The title path kept a 120-token ceiling after `thinkingBudget: 0` was
     removed. Thinking is ON by default at the endpoint, so the budget is spent
     on reasoning and the call returns HTTP 200 with `finishReason=MAX_TOKENS`
     and no parts: the status check passes, the `.get()` chain walks to "", the
     except never fires, and the title is silently never refreshed. The narrator
     took the same removal and went to 800.

 10. narrate.py kept a hand-rolled `generationConfig` after research.py
     consolidated four of them, and had to take the same fixes by hand. It is
     now shared — ⚠ WITH AN EXPLICIT OPT-OUT, because narrate deliberately
     refuses `DG_GEMINI_THINKING_BUDGET` and the shared builder honours it.

 12. ⭐ NEW. In the compiled wheel `research.py` is a launcher shim exporting
     only `main`; the pipeline is `_sr_core`. So `from research import
     resolve_api_key` inside vision.py raised in EVERY shipped build, was
     swallowed, and key resolution degraded to a bare `os.environ` read — the
     only other source that construction has. Anyone whose Anthropic key lived
     in the app rather than the machine's env file had a CUA last resort with no
     key, silently. narrate.py had the identical defect on the Gemini key.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys
import types

import pytest

import models
import narrate
import prompts
import research
import vision

REPO = pathlib.Path(__file__).resolve().parents[1]


# ── the suite is testing THIS tree ───────────────────────────────────────────

def test_the_suite_is_testing_THIS_tree() -> None:
    """Wave 1's scar. The dev venv carries an editable install of a DIFFERENT
    checkout, so `import research` has two possible answers and the winner is a
    sys.path accident. Every assertion in this file is worthless against the
    other copy — fail here, loudly, rather than pass there, quietly."""
    for mod in (research, models, vision, narrate):
        got = pathlib.Path(mod.__file__).resolve()
        assert got.parent == REPO, (
            f"the suite imported {mod.__name__} from {got}, not from {REPO}"
        )


# ── 4. the Windows console script is ours ────────────────────────────────────

def test_a_windows_console_backend_is_recognised_as_ours() -> None:
    """The finding, in the exact shape the reviewer named. `superresearch.exe`
    matched none of the three tests: not the bare-name console check, not
    `is_python`, not `runs_script`."""
    assert research._looks_like_our_backend("superresearch.exe --serve") is True
    assert research._looks_like_our_backend(
        "C:/Users/x/.local/bin/superresearch.exe --serve --port 8765") is True


def test_the_posix_console_script_and_the_checkout_still_match() -> None:
    """What already worked has to keep working — the fix is a strip, not a
    rewrite of the predicate."""
    assert research._looks_like_our_backend("superresearch --serve") is True
    assert research._looks_like_our_backend("/usr/bin/python3 research.py --serve") is True
    assert research._looks_like_our_backend("python.exe research.py --serve") is True


def test_stripping_exe_does_not_widen_what_we_will_kill() -> None:
    """⛔ The over-correction, and it is the dangerous direction. Everything
    downstream of this predicate can END a process, so a looser match is not a
    cosmetic regression — it is someone else's work terminated. `.exe` comes off
    the basename; nothing else about the match may relax."""
    for stranger in (
        "notsuperresearch.exe --serve",          # not us, merely ends in our name
        "superresearchd.exe --serve",            # a different program
        "supersearch.exe --serve",
        "grep --serve research.py",              # a word on the line, not the program
        "python3 other.py --serve",
        "superresearch.exe.bak --serve",         # only a trailing .exe is a suffix
    ):
        assert research._looks_like_our_backend(stranger) is False, stranger


def test_a_non_serve_process_of_ours_is_still_left_alone() -> None:
    """`--serve` remains the gate. A user's own `superresearch --pair` must not
    become reclaimable just because its name now matches."""
    assert research._looks_like_our_backend("superresearch.exe --pair") is False
    assert research._looks_like_our_backend("superresearch.exe --doctor") is False


def test_strip_exe_leaves_everything_else_alone() -> None:
    assert research._strip_exe("superresearch.exe") == "superresearch"
    assert research._strip_exe("SUPERRESEARCH.EXE") == "SUPERRESEARCH"
    assert research._strip_exe("research.py") == "research.py"
    assert research._strip_exe("") == ""
    assert research._strip_exe(".exe") == ""


def test_both_call_sites_share_one_stripper() -> None:
    """The finding existed because two places needed the same rule and only one
    had it. Duplicating the expression back into either would let them diverge
    again, which is how this arrived."""
    src = REPO.joinpath("research.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fname in ("_prog_name", "_looks_like_our_backend"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == fname)
        calls = {c.func.id for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_strip_exe" in calls, (
            f"{fname}() hand-rolls the .exe strip again instead of sharing it"
        )


# ── 5. a Gemini 200 that came back empty says why ────────────────────────────

class _Resp:
    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _gemini_stub(monkeypatch, resp, sent: list):
    """Answer the Gemini POST with `resp` and record the payload we sent."""
    fake = types.SimpleNamespace(post=lambda url, json=None, timeout=None:
                                 (sent.append(json), resp)[1])
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setattr(research, "resolve_gemini_api_key", lambda: "gk")
    monkeypatch.setattr(research, "resolve_api_key", lambda *a, **k: "")   # skip Haiku


def _logs(monkeypatch) -> list:
    seen: list = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: seen.append((level, msg)))
    return seen


_EMPTY_200 = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {}}]}


def test_the_title_leg_asks_for_a_ceiling_that_survives_thinking(monkeypatch) -> None:
    """The finding. 40 → 120 was the compensating raise when the thinking-disable
    field came out; the narrator needed 200 → 800 for the same removal. A ceiling
    sized for a non-thinking request is spent before any answer is produced."""
    sent: list = []
    _logs(monkeypatch)
    _gemini_stub(monkeypatch, _Resp(200, {"candidates": [
        {"content": {"parts": [{"text": "A Fine Title"}]}}]}), sent)

    assert research._try_llm_title("t", "b") == "A Fine Title"
    assert sent, "the Gemini leg was never reached"
    ceiling = sent[0]["generationConfig"]["maxOutputTokens"]
    assert ceiling >= 600, (
        f"the title leg still asks for {ceiling} output tokens with thinking on — "
        f"the budget is spent reasoning and the 200 comes back with no parts"
    )


def test_an_empty_200_on_the_title_leg_is_logged_with_its_reason(monkeypatch) -> None:
    """The other half. The status check made a REFUSAL visible; an ACCEPTED call
    that produced nothing was still silent, and produced the identical "" out of
    this function. Zero log evidence is what made this survive."""
    seen = _logs(monkeypatch)
    _gemini_stub(monkeypatch, _Resp(200, _EMPTY_200), [])

    assert research._try_llm_title("t", "b") == ""
    warned = [m for lvl, m in seen if lvl == "WARN" and "no text" in m]
    assert warned, f"an empty 200 was swallowed with no log at all: {seen!r}"
    assert "finishReason=MAX_TOKENS" in warned[0], (
        f"the log fired but does not name the cause: {warned[0]!r}"
    )


def test_a_blocked_prompt_reads_differently_from_a_spent_budget(monkeypatch) -> None:
    """Two different faults with two different fixes — a blocked prompt is ours
    to change, a spent budget is a config value. The old single silence
    described neither."""
    seen = _logs(monkeypatch)
    _gemini_stub(monkeypatch, _Resp(200, {"candidates": [{}],
                                          "promptFeedback": {"blockReason": "SAFETY"}}), [])

    assert research._try_llm_title("t", "b") == ""
    warned = [m for lvl, m in seen if lvl == "WARN" and "no text" in m]
    assert warned and "blockReason=SAFETY" in warned[0], f"{seen!r}"


def test_a_good_title_is_not_logged_as_a_failure(monkeypatch) -> None:
    """⛔ Over-correction: a log that fires on every call is noise, and this one
    would fire on the success path of every run."""
    seen = _logs(monkeypatch)
    _gemini_stub(monkeypatch, _Resp(200, {"candidates": [
        {"content": {"parts": [{"text": "Good Title Here"}]}}]}), [])

    assert research._try_llm_title("t", "b") == "Good Title Here"
    assert not [m for lvl, m in seen if "no text" in m], f"{seen!r}"


def test_the_refusal_log_still_fires_and_still_returns_empty(monkeypatch) -> None:
    """The status check this sits next to must not have been displaced by it."""
    seen = _logs(monkeypatch)
    _gemini_stub(monkeypatch, _Resp(400, {"error": {"message": "bad key"}}), [])

    assert research._try_llm_title("t", "b") == ""
    assert [m for lvl, m in seen if lvl == "WARN" and "refused" in m], f"{seen!r}"


def test_the_summary_leg_names_its_empty_200_too(monkeypatch) -> None:
    """Same shape one screen down. 900 tokens is enough headroom that MAX_TOKENS
    is unlikely there — which is exactly why the reason matters if it ever
    fires, since it is the only thing separating it from a blocked prompt."""
    seen = _logs(monkeypatch)
    _gemini_stub(monkeypatch, _Resp(200, _EMPTY_200), [])

    assert research._try_llm_summary("t", "b") == ""
    warned = [m for lvl, m in seen if lvl == "WARN" and "no text" in m]
    assert warned and "finishReason=MAX_TOKENS" in warned[0], f"{seen!r}"


# ── 10. one generationConfig builder, with a deliberate opt-out ──────────────

def test_narrate_no_longer_hand_rolls_a_generation_config() -> None:
    """The finding: research.py consolidated four builders and this fifth copy
    stayed behind, taking the same fixes by hand — the thinking-disable removal
    and the compensating ceiling raise both had to be applied here separately."""
    tree = ast.parse(REPO.joinpath("narrate.py").read_text(encoding="utf-8"))
    hits = []
    for n in ast.walk(tree):
        # A dict literal: {"maxOutputTokens": …}
        if isinstance(n, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "maxOutputTokens"
                for k in n.keys):
            hits.append(n.lineno)
        # ⚠ …and the two shapes a literal-only scan cannot see, which is how a
        # re-forked builder would slip straight back past this guard:
        # `dict(maxOutputTokens=…)`
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "dict"
                and any(kw.arg == "maxOutputTokens" for kw in n.keywords)):
            hits.append(n.lineno)
        # `cfg["maxOutputTokens"] = …`
        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and n.slice.value == "maxOutputTokens"):
            hits.append(n.lineno)
    assert not hits, (
        f"narrate.py hand-rolls a generationConfig again at line(s) {sorted(hits)}"
    )


def test_the_panel_narrator_still_refuses_the_thinking_budget_env(monkeypatch) -> None:
    """⛔ THE OVER-CORRECTION THAT CONSOLIDATION INVITES, and the reason the
    shared builder takes an opt-out at all. This module sends a `responseSchema`,
    and with thinking on the structured response can truncate mid-field — a
    worse failure here than a slow one. Consolidating naively would have handed
    that decision to an env var without anyone deciding to."""
    monkeypatch.setenv("DG_GEMINI_THINKING_BUDGET", "2048")
    posted: list = []

    class _R:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    monkeypatch.setattr(narrate.requests, "post",
                        lambda url, json=None, timeout=None: (posted.append(json), _R())[1])
    narrate._call_gemini("k", "m", b"png", "u")

    cfg = posted[0]["generationConfig"]
    assert "thinkingConfig" not in cfg, (
        f"the panel narrator now honours DG_GEMINI_THINKING_BUDGET: {cfg!r}"
    )
    assert cfg["responseSchema"] and cfg["responseMimeType"] == "application/json", (
        "the schema this opt-out exists to protect is no longer being sent"
    )
    assert cfg["maxOutputTokens"] == 1400, "the ceiling that covers schema + reasoning moved"


def _narrate_call(monkeypatch, payload, status=200):
    """Drive the REAL panel-narrator request and return its result dict."""
    class _R:
        status_code = status
        text = json.dumps(payload)

        def json(self):
            return payload

    monkeypatch.setattr(narrate.requests, "post",
                        lambda url, json=None, timeout=None: _R())
    return narrate._call_gemini("k", "m", b"png", "u")


def test_the_panel_narrator_names_why_a_200_came_back_empty(monkeypatch) -> None:
    """⭐ Found by a surviving mutant: nothing drove this response path at all.

    An accepted call that produced no text used to reach `json.loads("")` and
    surface as `parse: Expecting value` — which sends the next reader after the
    JSON decoder when the answer is in the response: the budget went on
    reasoning. It was the last Gemini leg in the product still describing the
    parser instead of the cause, and no test noticed either way."""
    out = _narrate_call(monkeypatch, {"candidates": [{"finishReason": "MAX_TOKENS"}]})
    assert out["ok"] is False
    assert "MAX_TOKENS" in out["error"], (
        f"an empty 200 is still reported as a parse fault: {out['error']!r}")
    assert "parse:" not in out["error"]


def test_a_blocked_prompt_surfaces_its_reason_through_the_narrate_call(monkeypatch) -> None:
    """Two faults, two fixes: a blocked prompt is ours to change, a spent budget
    is a config value.

    ⛔⛔ RENAMED 2026-08-25. This shared a name with the log-side test 130 lines
    above, so Python bound the name to THIS one and the earlier test was never
    collected — it had not run since the day it was written. Same failure this
    repo has now had three times; here CI was the thing that caught it, and had
    been failing on it since 2026-08-24 (ruff F811, which the correctness floor
    selects precisely because a shadowed test is a silent loss of coverage).
    The two are genuinely different subjects: that one reads the LOG line, this
    one reads what the narrate call returns.
    """
    out = _narrate_call(monkeypatch, {"candidates": [{}],
                                      "promptFeedback": {"blockReason": "SAFETY"}})
    assert out["ok"] is False and "SAFETY" in out["error"]


def test_a_genuinely_malformed_body_is_still_a_parse_fault(monkeypatch) -> None:
    """⛔ Over-correction: the empty-200 branch must not swallow real parse
    errors, or a broken schema response reads as a token-budget problem."""
    out = _narrate_call(monkeypatch, {"candidates": [
        {"content": {"parts": [{"text": "{not json"}]}}]})
    assert out["ok"] is False and out["error"].startswith("parse:")


def test_a_good_narration_still_comes_back(monkeypatch) -> None:
    """Guard against the guard: the new early return sits on the success path."""
    good = json.dumps({"narration": "Reading sources", "progress": "p",
                       "steps": [], "phase_signal": "reading", "confidence": 0.9})
    out = _narrate_call(monkeypatch, {"candidates": [
        {"content": {"parts": [{"text": good}]}}]})
    assert out["ok"] is True and out["data"]["narration"] == "Reading sources"


def test_research_still_honours_the_thinking_budget_env(monkeypatch) -> None:
    """Guard against the guard: the opt-out must be per-call-site, not a global
    disable. If nobody reads the env var, the flag proves nothing."""
    monkeypatch.setenv("DG_GEMINI_THINKING_BUDGET", "2048")
    cfg = research._gemini_gen_config(temperature=0.2, max_tokens=800)
    assert cfg["thinkingConfig"] == {"thinkingBudget": 2048}


def test_the_shared_builder_omits_thinking_by_default(monkeypatch) -> None:
    """Omission is the only variant with a live 200 behind it — the endpoint
    rejects `{"thinkingBudget": 0}` with a 400 that names no field."""
    monkeypatch.delenv("DG_GEMINI_THINKING_BUDGET", raising=False)
    assert models.gemini_gen_config(temperature=0.1, max_tokens=10) == {
        "temperature": 0.1, "maxOutputTokens": 10}


def test_a_junk_thinking_budget_is_ignored_rather_than_fatal(monkeypatch) -> None:
    monkeypatch.setenv("DG_GEMINI_THINKING_BUDGET", "lots")
    assert "thinkingConfig" not in models.gemini_gen_config(temperature=0.1, max_tokens=10)


def test_research_delegates_instead_of_keeping_a_second_body() -> None:
    """The consolidation has to be real. Two builders that agree today are the
    starting condition of this finding, not the fix."""
    tree = ast.parse(REPO.joinpath("research.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_gemini_gen_config")
    # The docstring still explains the env var and where it moved — what must be
    # gone is the CODE that reads it.
    statements = [n for n in fn.body
                  if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    body = "\n".join(ast.unparse(n) for n in statements)
    assert "DG_GEMINI_THINKING_BUDGET" not in body, (
        "research.py kept its own copy of the env read"
    )
    assert "_models_gemini_gen_config" in body, "it no longer delegates to the shared builder"


# ── 12. the compiled wheel can still reach the key resolvers ────────────────

def _wheel_shim() -> str:
    """The literal launcher shim the build script writes into the wheel."""
    spec = importlib.util.spec_from_file_location(
        "_build_compiled", REPO / "tools" / "build_compiled.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SHIM


def test_the_shipped_research_module_really_is_only_a_launcher() -> None:
    """The premise, read from the build script rather than assumed. If the wheel
    ever ships the real module again, the tests below stop describing anything —
    and this is the line that would say so."""
    shim = _wheel_shim()
    assert "def main(" in shim
    for name in ("resolve_api_key", "resolve_gemini_api_key"):
        assert name not in shim, (
            f"the wheel's research.py now exports {name} — re-check finding 12"
        )


def _as_wheel(monkeypatch):
    """Put the process into the shape a compiled wheel has: `research` is the
    launcher shim, and the pipeline is a separate module called `_sr_core`."""
    shim = types.ModuleType("research")
    shim.main = lambda: 0
    core = types.ModuleType("_sr_core")
    core.resolve_api_key = lambda *a, **k: "sk-ant-from-the-app"
    core.resolve_gemini_api_key = lambda *a, **k: "gemini-from-the-app"
    monkeypatch.setitem(sys.modules, "research", shim)
    monkeypatch.setitem(sys.modules, "_sr_core", core)
    return core


def test_the_key_resolver_is_found_under_the_compiled_core_name(monkeypatch) -> None:
    """The defect. `from research import resolve_api_key` raised ImportError in
    every shipped build — the shim has no such name — and both call sites
    swallowed it."""
    _as_wheel(monkeypatch)
    fn = models.core_attr("resolve_api_key")
    assert fn is not None and fn() == "sk-ant-from-the-app"


def test_a_source_checkout_still_resolves_from_research() -> None:
    """What already worked. In a checkout the pipeline IS `research`, and that
    must stay the first answer — it is the module already imported."""
    assert models.core_attr("resolve_api_key") is research.resolve_api_key


def test_a_standalone_caller_with_nothing_loaded_still_finds_the_core(
        monkeypatch, tmp_path) -> None:
    """Found by the mutation run, not by review: every other test here had the
    core ALREADY in sys.modules, so the real-import leg was never exercised and
    deleting it changed nothing.

    That leg is not decoration. `vision_test.py` and any other standalone entry
    point reach `VisionClient()` with the pipeline not imported at all, and a
    lookup that only reads sys.modules answers None there — skipping the app's
    key and falling through to the machine env, which is the exact degradation
    this whole fix removes.

    Driven through a stand-in module rather than by evicting the real one:
    re-importing the pipeline mid-suite would take seconds and re-run its
    module-level side effects."""
    (tmp_path / "wave2_fake_core.py").write_text(
        "def resolve_api_key():\n    return 'sk-ant-cold-import'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "wave2_fake_core", raising=False)
    monkeypatch.setattr(models, "CORE_MODULE_NAMES", ("wave2_fake_core",))

    fn = models.core_attr("resolve_api_key")
    assert fn is not None and fn() == "sk-ant-cold-import", (
        "nothing resolved with the core not yet imported — the real-import leg "
        "is the only thing a standalone caller has"
    )


def test_a_name_that_exists_nowhere_returns_none(monkeypatch) -> None:
    """⛔ Over-correction: a resolver that returns something for any name would
    make every caller's `if fn is not None` meaningless."""
    _as_wheel(monkeypatch)
    assert models.core_attr("no_such_helper_anywhere") is None


def test_the_resolver_never_raises_into_its_caller(monkeypatch) -> None:
    """Every call site treats this as best-effort and falls through to the next
    key source. An exception here would take out the fallback too."""
    broken = types.ModuleType("research")

    class _Boom:
        def __getattr__(self, name):
            raise RuntimeError("half-initialised module")

    monkeypatch.setitem(sys.modules, "research", broken)
    monkeypatch.setitem(sys.modules, "_sr_core", _Boom())
    try:
        models.core_attr("resolve_api_key")
    except Exception as exc:                                    # pragma: no cover
        raise AssertionError(f"core_attr raised into its caller: {exc!r}") from exc


def test_the_vision_client_gets_the_app_key_in_a_wheel_shaped_process(monkeypatch) -> None:
    """⭐ The consequence, end to end. `VisionClient()` is constructed with NO
    api_key everywhere in production, so the swallowed import left `os.environ`
    as its only source — and on any machine whose Anthropic key lives in the app
    rather than the supervisor's env file, that is empty. The CUA last resort
    ran with no key and said nothing."""
    _as_wheel(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stale-machine-env")

    client = vision.VisionClient()
    assert client._client.api_key == "sk-ant-from-the-app", (
        "the app's key lost to the machine env — the core lookup is still failing"
    )


def test_the_machine_env_is_still_the_last_resort(monkeypatch) -> None:
    """Guard against the guard: the env read is a real fallback for standalone
    callers (vision_test.py), not dead code. Removing it would be an
    over-correction that breaks a working path."""
    shim = types.ModuleType("research")
    shim.main = lambda: 0
    monkeypatch.setitem(sys.modules, "research", shim)
    monkeypatch.delitem(sys.modules, "_sr_core", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-machine-env")

    assert vision.VisionClient()._client.api_key == "sk-ant-machine-env"


def _narrate_reached_the_key(monkeypatch) -> bool:
    """Run the REAL `narrate_panel` far enough to see whether the key resolved.

    ⚠ This exists because the test it replaces never touched narrate at all — it
    asserted on `models.core_attr` directly, so breaking the actual call site
    (`narrate.py`, the lookup inside `narrate_panel`) left it green. That call
    site is executed by nothing else either: the only other `narrate_panel` tests
    run with `PHASE_BUDGET == 0`, which returns before the key is ever asked for.

    The observable is the COOLDOWN counter. Key resolved → execution continues
    past the key gate and trips the cooldown; key not resolved → it returns
    earlier, and the counter does not move. No screenshot is ever taken.
    """
    import asyncio
    import time as _time

    monkeypatch.setattr(narrate, "PHASE_BUDGET", 1)
    monkeypatch.setattr(narrate, "MIN_GAP_S", 10_000.0)
    monkeypatch.setattr(narrate._M, "last_call_ts", _time.time())
    monkeypatch.setattr(narrate._M, "skipped_cooldown", 0)
    monkeypatch.setattr(narrate._M, "calls_this_phase", 0)

    assert asyncio.run(narrate.narrate_panel(object(), agent="chatgpt", phase=2)) is None
    return narrate._M.skipped_cooldown == 1


def test_the_narrator_key_lookup_took_the_same_fix(monkeypatch) -> None:
    """narrate.py had the identical defect on the Gemini key, and its own
    docstring DOCUMENTED the failure rather than fixing it: with the import
    dead, the Windows User-scope probe became the sole lookup, which returns ""
    unconditionally off Windows. Anyone whose Gemini key lived in the app had no
    narrator at all.

    Driven through `narrate_panel` itself, not through the shared helper — the
    helper working proves nothing about whether narrate calls it."""
    _as_wheel(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert _narrate_reached_the_key(monkeypatch) is True, (
        "narrate stopped at the key gate in a wheel-shaped process — the "
        "Account-page Gemini key is unreachable again and the narrator is off"
    )


def test_the_narrator_still_gives_up_when_no_key_exists_anywhere(monkeypatch) -> None:
    """Guard against the guard: the probe above must distinguish "resolved" from
    "ran at all". With the core absent AND no env key there is genuinely no key,
    and narrate must return before the cooldown gate."""
    shim = types.ModuleType("research")
    shim.main = lambda: 0
    monkeypatch.setitem(sys.modules, "research", shim)
    monkeypatch.delitem(sys.modules, "_sr_core", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # ⛔ "nowhere" has to include the Windows User-scope environment. The lookup
    # under test is `os.environ.get(...) or _read_user_scope_env_safe(...)`, and
    # deleting only the process variable leaves the second source live: on a
    # Windows box whose owner actually has a Gemini key saved, the key resolves,
    # narrate runs on past the gate, and this test fails for a reason that has
    # nothing to do with the code. It passed off Windows only because the probe
    # returns "" there unconditionally -- machine configuration, not coverage.
    monkeypatch.setattr(narrate, "_read_user_scope_env_safe", lambda _name: "")
    assert _narrate_reached_the_key(monkeypatch) is False


def test_the_shared_resolver_finds_the_gemini_key_under_the_core_name(monkeypatch) -> None:
    _as_wheel(monkeypatch)
    fn = models.core_attr("resolve_gemini_api_key")
    assert fn is not None and fn() == "gemini-from-the-app"


def _wheel_shipped_sources() -> "list[pathlib.Path]":
    """Every first-party .py the WHEEL contains, read from the two declarations
    that decide it rather than from a hand-kept list here.

    ⚠ A hardcoded list is what made the first version of the guard below useless:
    it named the five compiled sibling modules, so it could not see the same
    defect sitting in the `scripts/` package — which pyproject ships wholesale,
    minus whatever the build script drops. Deriving the set means a new shipped
    file is covered the day it is added, by the person who added it."""
    import tomllib
    pyproject = tomllib.loads(REPO.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    tool = (pyproject.get("tool") or {}).get("setuptools") or {}

    build = REPO / "tools" / "build_compiled.py"
    btree = ast.parse(build.read_text(encoding="utf-8"))
    dropped = set()
    for node in ast.walk(btree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "DROP_FROM_WHEEL" for t in node.targets)):
            dropped = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    assert dropped, "DROP_FROM_WHEEL could not be read — this scan would over-report"

    out = [REPO / f"{m}.py" for m in tool.get("py-modules", []) if m != "research"]
    for pkg in tool.get("packages", []):
        for path in sorted((REPO / pkg).rglob("*.py")):
            if path.relative_to(REPO).as_posix() in dropped:
                continue
            out.append(path)
    return [p for p in out if p.exists()]


def test_nothing_the_wheel_ships_reaches_the_pipeline_by_the_name_research() -> None:
    """The rule, and now the whole shipped surface rather than two instances.

    In the wheel `research.py` is a launcher shim exporting only `main`, so ANY
    `import research` in a file that ships alongside it is broken there — either
    loudly (an AttributeError on first use) or, when it is wrapped in a bare
    except as both key lookups were, silently.

    ⚠ The first version of this test scanned a hardcoded list of five compiled
    modules. It passed while `scripts/claude_popover_capture.py` — which the
    wheel shipped, and which calls `research.p2_family` and `research.Browser` —
    had exactly the defect the test claimed to have closed as a class."""
    offenders = []
    for path in _wheel_shipped_sources():
        rel = path.relative_to(REPO).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "research":
                offenders.append(f"{rel}:{node.lineno}")
            if isinstance(node, ast.Import) and any(a.name == "research" for a in node.names):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"these ship in the wheel and reach the pipeline by a name it does not "
        f"have: {offenders}. Use models.core_attr(), which finds the core under "
        f"either name — or drop the file from the wheel if it is a source-tree "
        f"diagnostic (tools/build_compiled.py DROP_FROM_WHEEL)."
    )


def test_the_shipped_surface_scan_is_not_empty() -> None:
    """Guard against the guard: a derivation that silently resolved to nothing
    would make the test above unfailable. It must see the compiled siblings AND
    the shipped package files."""
    rels = {p.relative_to(REPO).as_posix() for p in _wheel_shipped_sources()}
    assert {"vision.py", "narrate.py", "models.py"} <= rels, rels
    assert any(r.startswith("scripts/") for r in rels), (
        f"the scan no longer covers the shipped scripts package: {sorted(rels)}"
    )
    assert "scripts/dump_push_audit.py" not in rels, (
        "a file the build script drops is being scanned as if it shipped"
    )


def test_the_scan_for_direct_imports_can_actually_fire() -> None:
    """Guard against the guard: a green list above must mean 'none found', not
    'the walk matched nothing'."""
    tree = ast.parse("from research import resolve_api_key\nimport research\n")
    hits = [n for n in ast.walk(tree)
            if (isinstance(n, ast.ImportFrom) and n.module == "research")
            or (isinstance(n, ast.Import) and any(a.name == "research" for a in n.names))]
    assert len(hits) == 2


# ── the CUA missions refuse the sales chip too ───────────────────────────────
#
# The DOM picker learned to refuse upsell chips in wave 1. The CUA missions did
# not — and CUA is what runs AFTER the DOM tier fails, which on an account whose
# plan does not include the family is EVERY run. So the missions were the
# mainline for exactly the accounts the guard was written for, and they said
# "open the model menu and select the HIGHEST Opus it offers".

_CUA_MISSIONS = (
    ("p2_claude_setup_directive", lambda: models.p2_claude_setup_directive()),
    ("p2_claude_validate_directive", lambda: models.p2_claude_validate_directive()),
    ("PROMPT_CLAUDE_DEEP_RESEARCH", lambda: prompts.PROMPT_CLAUDE_DEEP_RESEARCH),
    ("PROMPT_VALIDATE_CLAUDE_SETUP", lambda: prompts.PROMPT_VALIDATE_CLAUDE_SETUP),
)


@pytest.mark.parametrize("name,get", _CUA_MISSIONS)
def test_every_claude_cua_mission_refuses_the_sales_chip(name, get) -> None:
    """⭐ All four, because all four can reach the model menu. The validate one
    matters most: its own step 1 says "ONLY touch the model if the button shows
    Sonnet/Haiku with no Opus at all: then open it once, pick the
    highest-numbered Opus" — and on a non-pro account the button ALWAYS reads
    Sonnet, so that clause fires on every run and points the agent straight at
    the chips."""
    text = get()
    assert "sales prompt" in text, f"{name} never tells the agent a chip is not a model"
    assert "Upgrade to Opus" in text, f"{name} does not name the chip shape"


@pytest.mark.parametrize("name,get", _CUA_MISSIONS)
def test_every_claude_cua_mission_says_what_an_all_chip_menu_MEANS(name, get) -> None:
    """⛔ The half that is easy to omit, and the reason "ignore the chips" alone
    is not enough: an agent told only to ignore them, finding nothing else that
    matches the family, keeps hunting — and the most Opus-looking thing left on
    the page is still the chip. It has to be told the absence means the plan
    does not include the family."""
    text = get()
    assert "plan does not include" in text, (
        f"{name} says to ignore chips but never says what a chips-only menu means")


def test_the_warning_is_rendered_from_the_shared_verb_list(monkeypatch) -> None:
    """Not a literal. The missions and the DOM selectors must not develop
    separate ideas of what a sales prompt looks like — that split is the whole
    reason the CUA layer kept clicking what the picker had learned to refuse."""
    monkeypatch.setattr(models, "UPSELL_VERBS", ("purchase", "rent", "get"))
    out = models.upsell_warning("Opus")
    assert '"Purchase to Opus"' in out and '"Rent to Opus"' in out
    assert "Upgrade" not in out


def test_the_warning_follows_the_family_rather_than_naming_opus() -> None:
    """The family is policy, not a literal — a mission built for another family
    must warn about that family's chips."""
    out = models.upsell_warning("Sonnet")
    assert "Sonnet" in out and "Opus" not in out
