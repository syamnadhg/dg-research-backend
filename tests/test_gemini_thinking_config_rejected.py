"""2026-08-05 — every Gemini text call carried a field the endpoint rejects.

Prod log (backend.log:682170), and it repeated for the whole run:

    [07:01:14] [WARN] [narrator] Gemini gemini-3.6-flash refused the call —
    HTTP 400 INVALID_ARGUMENT: Request contains an invalid argument. —
    narration is running on claude-haiku-4-5 until this is fixed

⭐ HOW IT WAS FOUND, because the error body could not tell us. Google returned
`INVALID_ARGUMENT` with the boilerplate "Request contains an invalid argument."
and NO `details`, so there were no fieldViolations to surface — the diagnostic
work of the previous wave was on this exact path, shipped in 0.1.12, and worked
perfectly; there was simply nothing to report. What settled it was a
differential INSIDE ONE PROCESS: the vision-URL extractor sends the same model
id (both constants default to the same literal), to the same v1beta path, with
the same role/parts, the same systemInstruction shape, an int maxOutputTokens
and a float temperature — and NO thinkingConfig — and returns 200 in the same
run where every narrator call returns 400.

Two corrections to the first read fall out of this:
  * The model id is NOT the fault, and must not be bumped. It is a plain literal
    in models.py, the family-only directive is scoped to a different subsystem,
    and a missing model on this endpoint is 404/NOT_FOUND, not 400.
  * The field appeared at FOUR sites, and two of them — the title and summary
    builders — never checked the status before parsing. On a 400 the body is
    `{"error": {...}}`, so `.get("candidates", [{}])` walks the default chain to
    "" without raising, the `except` never fires, and a hard refusal is reported
    as "the model had nothing to say". The corpus confirms it: zero
    "Gemini Flash failed" lines anywhere, ever, while every call was refused.

Run:  pytest tests/test_gemini_thinking_config_rejected.py -v
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models
import narrate
import research
from conftest import code_only, code_only_deep

# The exact body from the incident: INVALID_ARGUMENT, no details.
PROD_400 = {"error": {"code": 400,
                      "message": "Request contains an invalid argument.",
                      "status": "INVALID_ARGUMENT"}}
# What a MISSING MODEL actually returns on this endpoint.
MISSING_MODEL_404 = {"error": {"code": 404,
                               "message": "models/whatever is not found.",
                               "status": "NOT_FOUND"}}


class _Resp:
    """A response double that honours its status AND its body — the two things a
    caller can branch on."""

    text = ""

    def __init__(self, body, status=400):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body


# ── The shared config ─────────────────────────────────────────────────────

def test_the_thinking_budget_is_not_sent_by_default(monkeypatch):
    monkeypatch.delenv("DG_GEMINI_THINKING_BUDGET", raising=False)
    cfg = research._gemini_gen_config(temperature=0.2, max_tokens=800)
    assert "thinkingConfig" not in cfg, (
        "omission is the only variant with a live HTTP 200 behind it"
    )
    assert cfg == {"temperature": 0.2, "maxOutputTokens": 800}


def test_the_budget_can_be_opted_back_in(monkeypatch):
    """Kept as a lever for a future model that accepts the field — removing it
    outright would make that untestable without a code change."""
    monkeypatch.setenv("DG_GEMINI_THINKING_BUDGET", "0")
    cfg = research._gemini_gen_config(temperature=0.2, max_tokens=800)
    assert cfg["thinkingConfig"] == {"thinkingBudget": 0}


def test_a_nonzero_budget_is_honoured(monkeypatch):
    monkeypatch.setenv("DG_GEMINI_THINKING_BUDGET", "512")
    cfg = research._gemini_gen_config(temperature=0.2, max_tokens=800)
    assert cfg["thinkingConfig"] == {"thinkingBudget": 512}


@pytest.mark.parametrize("bad", ["", "   ", "nonsense", "1.5", "-"])
def test_a_malformed_budget_is_ignored_rather_than_crashing(monkeypatch, bad):
    """This builds a payload on the live pipeline. A ValueError here would take
    the narrator down instead of degrading it."""
    monkeypatch.setenv("DG_GEMINI_THINKING_BUDGET", bad)
    cfg = research._gemini_gen_config(temperature=0.2, max_tokens=800)
    assert "thinkingConfig" not in cfg


def test_max_tokens_is_always_an_int():
    """Gemini rejects a float here, and callers pass values that arrive from
    env / config."""
    cfg = research._gemini_gen_config(temperature=0.2, max_tokens=800.0)
    assert isinstance(cfg["maxOutputTokens"], int)


def test_extra_config_keys_pass_through():
    cfg = research._gemini_gen_config(temperature=0.0, max_tokens=800,
                                      responseMimeType="application/json")
    assert cfg["responseMimeType"] == "application/json"


# ── Every builder uses it ─────────────────────────────────────────────────

def test_no_python_module_hand_rolls_a_thinking_budget_any_more():
    """The field lived at four sites and only ONE of them logged when it was
    rejected. A shared builder is what stops it surviving somewhere nobody
    watches."""
    # code_only_deep, not code_only: the explanatory comments and docstrings
    # around these fixes NAME the field, and a presence assertion cannot tell
    # code from prose. That trap is exactly what conftest's deep stripper is for.
    #
    # The SHARED builder is the one legitimate home — it owns the opt-in — so cut
    # it out and require the rest of both modules to be clean. Counting instead
    # of excluding would pass on a build where the shared one was deleted and a
    # hand-rolled one added back.
    #
    # ⓘ 2026-08-13 — the shared builder MOVED to models.py, and the move is the
    # point rather than a detail. narrate.py was the fifth site and could not
    # share research.py's copy at all: it is compiled into the wheel alongside a
    # `research.py` that is only a launcher shim, so importing from it raises
    # there. models.py is the one module all of them already import.
    assert "thinkingBudget" in code_only_deep(models.gemini_gen_config), (
        "the opt-in lever is gone from the shared builder — if that is deliberate, "
        "this test's whole shape needs revisiting"
    )
    # Excise the shared builder by LINE RANGE, not by substring: the two
    # strippers dedent differently, so a function's stripped text is not a
    # substring of its module's stripped text.
    for mod in (research, narrate, models):
        lines = code_only_deep(inspect.getsource(mod)).splitlines()
        if mod is models:
            _, start = inspect.getsourcelines(models.gemini_gen_config)
            span = len(inspect.getsourcelines(models.gemini_gen_config)[0])
            lines[start - 1:start - 1 + span] = []
        offenders = [(i + 1, ln) for i, ln in enumerate(lines)
                     if "thinkingBudget" in ln]
        assert not offenders, (
            f"{mod.__name__} hand-rolls the thinking budget outside the shared "
            f"builder, at line(s) {[n for n, _ in offenders]}"
        )


def test_the_panel_narrator_opts_out_of_the_budget_rather_than_forgetting_it():
    """⚠ The one call site that must NOT honour the env var, and the reason the
    shared builder takes a flag instead of reading the variable unconditionally.

    narrate.py sends a `responseSchema`; with thinking on, structured JSON can
    truncate mid-field, which is a worse failure there than a slow one. Before
    consolidation that refusal was expressed by simply not having the code —
    silence. Consolidating without the flag would have converted a decision into
    an accident, and nothing would have failed."""
    assert "thinking_budget_env=False" in code_only(narrate._call_gemini), (
        "the panel narrator no longer opts out of DG_GEMINI_THINKING_BUDGET — a "
        "truncated responseSchema is now one env var away"
    )


@pytest.mark.parametrize("fn", [
    research._call_text_narrator,
    research._try_llm_title,
    research._try_llm_summary,
])
def test_each_gemini_text_builder_routes_through_the_shared_config(fn):
    assert "_gemini_gen_config(" in code_only(fn), (
        f"{fn.__name__} builds its own generationConfig"
    )


def test_the_vision_url_extractor_is_the_exoneration_witness_and_stays_clean():
    """⚠ The whole diagnosis rests on this builder returning 200 with the same
    model and path. If it ever gains the field, or the two model constants
    diverge, the evidence silently stops applying."""
    src = code_only_deep(research.extract_source_urls_via_vision)
    assert "thinkingBudget" not in src
    # It is the same endpoint and the same auth — that is what makes it a witness
    # rather than an unrelated call.
    assert "generativelanguage.googleapis.com/v1beta/models/" in src
    assert "GEMINI_NARRATE" in src
    assert models.GEMINI_TEXT == models.GEMINI_NARRATE, (
        "the two paths must share a model or the 200-vs-400 differential proves "
        "nothing"
    )


# ── The ceiling had to rise with the field's removal ──────────────────────

def test_the_narrator_ceiling_rose_when_thinking_came_back_on():
    """The 200-token default was sized for a request that disabled thinking. With
    thinking on, 200 output tokens returns a 200-with-no-text
    (`finishReason=MAX_TOKENS`) — trading a 400 for a silent empty."""
    sig = inspect.signature(research._call_text_narrator)
    assert sig.parameters["max_tokens"].default >= 600, (
        "removing the disable without raising the ceiling swaps one failure for "
        "another"
    )


def test_the_vision_narrator_ceiling_rose_too(monkeypatch):
    """Read from the payload the module actually POSTS, not from its source.

    ⓘ This used to `index('"maxOutputTokens"')` in narrate.py's text and check
    the 60 characters after it. That stopped finding anything the moment the
    literal dict became a call to the shared builder — and a source scan that
    finds nothing is one edit away from an assertion that cannot fail. Building
    the real request answers the same question and cannot be emptied by a
    refactor."""
    posted: list = []

    class _R:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    monkeypatch.setattr(narrate.requests, "post",
                        lambda url, json=None, timeout=None:
                        (posted.append(json), _R())[1])
    narrate._call_gemini("k", "m", b"png", "u")

    ceiling = posted[0]["generationConfig"]["maxOutputTokens"]
    assert ceiling > 600, (
        f"narrate.py asks for {ceiling} output tokens. It disabled thinking "
        f"specifically so all 600 went to the structured JSON; with thinking on, "
        f"600 truncates it mid-field"
    )


def test_that_empty_failure_mode_is_still_diagnosable():
    """The one this trade could produce. It was already named — keep it named."""
    assert research._gemini_empty_reason(
        {"candidates": [{"finishReason": "MAX_TOKENS"}]}) == "finishReason=MAX_TOKENS"


# ── The error line now names what we sent ─────────────────────────────────

def test_the_prod_body_still_produces_a_readable_line():
    out = research._gemini_error_detail(_Resp(PROD_400))
    assert "INVALID_ARGUMENT" in out
    assert "Request contains an invalid argument." in out
    assert "[]" not in out, "an empty violations tail reads as 'no detail found'"


def test_an_invalid_argument_with_no_violations_names_our_config_keys():
    """The change that would have put `thinkingConfig` in the prod log directly,
    with no code archaeology."""
    out = research._gemini_error_detail(
        _Resp(PROD_400),
        {"temperature": 0.2, "maxOutputTokens": 200,
         "thinkingConfig": {"thinkingBudget": 0}})
    assert "thinkingConfig" in out
    assert "generationConfig" in out


def test_the_config_tail_prints_keys_only_never_values():
    """This line goes to the log, and the payload carries user prompt text."""
    out = research._gemini_error_detail(
        _Resp(PROD_400), {"temperature": 0.2, "maxOutputTokens": 200})
    assert "0.2" not in out and "200" not in out


def test_a_real_field_violation_still_wins_over_the_config_tail():
    body = {"error": {"message": "Invalid JSON payload received.",
                      "status": "INVALID_ARGUMENT",
                      "details": [{"fieldViolations": [
                          {"field": "generationConfig.thinkingConfig",
                           "description": 'Unknown name "thinkingConfig"'}]}]}}
    out = research._gemini_error_detail(_Resp(body), {"temperature": 0.2})
    assert "generationConfig.thinkingConfig" in out
    assert "we sent" not in out, "Google named the field; do not guess over it"


def test_the_config_tail_is_scoped_to_invalid_argument():
    """On a bad key or a missing model, listing our config keys is noise."""
    out = research._gemini_error_detail(
        _Resp(MISSING_MODEL_404, status=404), {"thinkingConfig": {}})
    assert "we sent" not in out
    assert "NOT_FOUND" in out


def test_a_missing_model_is_404_not_400():
    """The docstring used to list `models/<name> is not found` among the 400s and
    sent a reader hunting a phantom rename."""
    doc = research._gemini_error_detail.__doc__
    assert "404" in doc
    out = research._gemini_error_detail(_Resp(MISSING_MODEL_404, status=404))
    assert "NOT_FOUND" in out


def test_a_bad_key_still_reads_clearly():
    body = {"error": {"code": 400, "message": "API key not valid. Please pass a "
                                             "valid API key.",
                      "status": "INVALID_ARGUMENT"}}
    out = research._gemini_error_detail(_Resp(body))
    assert "API key not valid" in out


@pytest.mark.parametrize("cfg", [None, {}, 5, "nope"])
def test_a_bad_sent_config_never_raises(cfg):
    """It comes from `payload.get(...)`, which can be anything after an edit."""
    out = research._gemini_error_detail(_Resp(PROD_400), cfg)
    assert "INVALID_ARGUMENT" in out


def test_an_unparseable_body_never_returns_an_empty_string():
    class _Broken:
        status_code = 400
        text = ""

        def json(self):
            raise ValueError("not json")

    assert research._gemini_error_detail(_Broken()).strip() != ""


# ── The two sites that swallowed a 400 in silence ─────────────────────────

@pytest.mark.parametrize("fn,tag", [
    (research._try_llm_title, "title-refresh"),
    (research._try_llm_summary, "summary"),
])
def test_a_refusal_is_logged_before_the_body_is_parsed(fn, tag):
    src = code_only(fn)
    assert "status_code" in src, (
        f"{fn.__name__} parses the body without checking the status — on a 400 "
        f"the candidates chain walks to '' and the except never fires"
    )
    assert src.index("status_code") < src.index("resp.json()"), (
        "the status check must precede the parse, or it gates nothing"
    )
    assert "refused" in src


@pytest.mark.parametrize("fn", [research._try_llm_title, research._try_llm_summary])
def test_a_refusal_returns_empty_so_the_caller_still_falls_back(fn):
    """Behaviour must not change — only the silence. Both have a non-LLM
    fallback and must keep reaching it."""
    src = code_only(fn)
    tail = src[src.index("status_code"):]
    assert 'return ""' in tail[:400]


@pytest.mark.parametrize("fn", [research._try_llm_title, research._try_llm_summary])
def test_the_refusal_log_carries_googles_reason(fn):
    assert "_gemini_error_detail(" in code_only(fn), (
        "logging the bare status repeats what we already knew — the cause is in "
        "the body"
    )


def test_the_narrator_reporting_path_was_never_broken():
    """A correction worth pinning: the previous wave's diagnostic DID ship and IS
    on this path. The prod string is character-identical to this f-string, so it
    can only have come from here. The gap was in the response, not the code."""
    src = code_only(research._call_text_narrator)
    assert "_gemini_error_detail(" in src
    assert "refused the call" in src
    assert "until this is fixed" in src
