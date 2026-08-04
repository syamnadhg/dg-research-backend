"""The narrator's Gemini leg must say WHY it fell back, and say it once.

Two defects, both read off the live corpus rather than reasoned about:

  * **1125 warnings, no diagnosis.** Every one read
    `[narrator] Gemini Flash sc=400 (empty or non-200) — falling back to Haiku
    4.5`, which repeats the status code and adds nothing. The cause was in
    `resp` the whole time and was discarded. On this endpoint "API key not
    valid", "models/<name> is not found" and "Unknown name in generationConfig"
    are ALL HTTP 400 — measured against the real endpoint, a bad key returns
    400 INVALID_ARGUMENT / API_KEY_INVALID — so the status alone can never
    separate an expired key from a renamed model.

  * **"Log once" logged every tick.** The narrator loop cleared the downgrade
    flag whenever a tick succeeded. A tick succeeds on HAIKU, which is exactly
    the state the downgrade line reports, so the flag was re-armed on every
    tick. 605 copies in one log file and 520 in the other, with no successful
    Gemini call anywhere in either.

These tests EXECUTE `_call_text_narrator` against a faked transport rather than
asserting on its source. A source-shape assertion cannot tell a message that
carries the reason from one that merely mentions the word.
"""
from __future__ import annotations

import ast
import json
import sys
import textwrap
import types

import pytest
import requests

import research
from conftest import code_only


# ── doubles ──────────────────────────────────────────────────────────────────

class _Resp:
    """Just enough of a requests.Response: status, body, and a json() that can
    fail the way a truncated or HTML error page does."""

    def __init__(self, status: int, body, *, json_raises: bool = False):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return json.loads(self.text)


# The body the real endpoint returns for a rejected key — captured from
# generativelanguage.googleapis.com, not written from memory.
_API_KEY_INVALID = {
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
        "details": [{
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": "API_KEY_INVALID",
            "domain": "googleapis.com",
            "metadata": {"service": "generativelanguage.googleapis.com"},
        }],
    }
}

_MODEL_NOT_FOUND = {
    "error": {
        "code": 404,
        "message": "models/gemini-9.9-flash is not found for API version v1beta.",
        "status": "NOT_FOUND",
    }
}


def _gemini_ok(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


@pytest.fixture
def transport(monkeypatch):
    """Replace the Gemini POST and the Haiku SDK; nothing leaves the process."""
    state = types.SimpleNamespace(responses=[], posted=[], haiku_text="haiku says so",
                                  haiku_calls=[])

    def _post(url, **kw):
        state.posted.append(url)
        nxt = state.responses.pop(0) if state.responses else _Resp(500, "")
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(requests, "post", _post)

    class _RateLimitError(Exception):
        pass

    class _Anthropic:
        def __init__(self, **kw):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            state.haiku_calls.append(kw)
            block = types.SimpleNamespace(type="text", text=state.haiku_text)
            return types.SimpleNamespace(content=[block])

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    fake.RateLimitError = _RateLimitError
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(research, "resolve_api_key", lambda *a, **k: "sk-test")
    return state


def _call(holder=None, **kw):
    return research._call_text_narrator(
        "be brief", "narrate this", gemini_key="k", use_gemini=True,
        err_holder=holder, **kw)


# ── the downgrade line has to carry the reason ───────────────────────────────

def test_a_refused_call_reports_what_google_said(transport, capsys):
    """⭐ The headline. `sc=400` on its own is not a diagnosis."""
    transport.responses = [_Resp(400, _API_KEY_INVALID)]
    holder = {}
    text, status = _call(holder)
    out = capsys.readouterr().out

    assert text == "haiku says so" and status == 200, "the fallback must still carry the tick"
    assert "API key not valid" in out, (
        "the reason Google gave was thrown away again — this is the whole fix")
    assert "API_KEY_INVALID" in out, "the machine-readable reason is the greppable half"
    assert research.GEMINI_TEXT in out, (
        "the model must be named: a 400 for a renamed model reads identically")
    assert "empty or non-200" not in out, (
        "the old message described two different faults at once and neither of them")


def test_a_not_found_model_is_distinguishable_from_a_bad_key(transport, capsys):
    transport.responses = [_Resp(404, _MODEL_NOT_FOUND)]
    _call({})
    out = capsys.readouterr().out
    assert "is not found" in out and "NOT_FOUND" in out
    assert "API key" not in out, "two different causes must not print the same line"


def test_an_unreadable_error_body_still_says_something(transport, capsys):
    """A gateway can return HTML. The line must never trail off into nothing —
    an empty tail reads as "no error", which is the opposite of the truth."""
    transport.responses = [_Resp(502, "<html><body>Bad Gateway</body></html>")]
    _call({})
    out = capsys.readouterr().out
    assert "502" in out and "Bad Gateway" in out


def test_an_empty_body_says_there_was_no_body(transport, capsys):
    transport.responses = [_Resp(400, "")]
    _call({})
    assert "(no error body)" in capsys.readouterr().out


def test_a_200_with_no_text_is_reported_as_its_own_fault(transport, capsys):
    """A refusal and an empty success have different fixes. The old message
    covered both with "(empty or non-200)" and so pointed at neither."""
    transport.responses = [_Resp(200, {
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": ""}]}}],
    })]
    _call({})
    out = capsys.readouterr().out
    assert "200 with no text" in out
    assert "finishReason=MAX_TOKENS" in out, "the finish reason IS the diagnosis here"
    assert "refused" not in out, "an accepted call must not be reported as a refusal"


@pytest.mark.parametrize("candidates", [[], [{}]])
def test_a_blocked_prompt_names_the_block_reason(transport, capsys, candidates):
    """⚠ `candidates: []` is the shape a real safety block returns, and chaining
    `[0]` on it raises — which would report "we could not read the body" about
    the one case there IS a reason for. Both shapes must reach the same line."""
    transport.responses = [_Resp(200, {"candidates": candidates,
                                       "promptFeedback": {"blockReason": "SAFETY"}})]
    _call({})
    out = capsys.readouterr().out
    assert "blockReason=SAFETY" in out
    assert "could not read" not in out


def test_a_body_that_will_not_parse_is_reported_not_swallowed(transport, capsys):
    transport.responses = [_Resp(200, "not json at all", json_raises=True)]
    _call({})
    out = capsys.readouterr().out
    assert "could not read" in out and "200" in out


def test_a_transport_error_still_names_the_model(transport, capsys):
    transport.responses = [requests.exceptions.ReadTimeout("read timed out")]
    _call({})
    out = capsys.readouterr().out
    assert "ReadTimeout" in out and research.GEMINI_TEXT in out


# ── once means once ──────────────────────────────────────────────────────────

def test_the_downgrade_is_logged_once_per_holder(transport, capsys):
    transport.responses = [_Resp(400, _API_KEY_INVALID), _Resp(400, _API_KEY_INVALID)]
    holder = {}
    _call(holder)
    _call(holder)
    warns = [ln for ln in capsys.readouterr().out.splitlines() if "[narrator] Gemini" in ln]
    assert len(warns) == 1, f"one downgrade, {len(warns)} lines: {warns}"


def test_no_holder_means_no_downgrade_log_at_all(transport, capsys):
    """The alert-copy caller has no loop to dedupe over and passes None."""
    transport.responses = [_Resp(400, _API_KEY_INVALID)]
    _call(None)
    assert "[narrator] Gemini" not in capsys.readouterr().out


def test_the_winning_vendor_is_recorded_on_every_success(transport):
    """⭐ What the loop must read before it clears the flag.

    Without this the loop can only ask "did the tick succeed?", and the answer is
    yes on Haiku — the exact state the suppressed log describes.
    """
    holder = {}
    transport.responses = [_Resp(400, _API_KEY_INVALID)]
    _call(holder)
    assert holder["last_vendor"] == "haiku", "the fallback carried the tick, not Gemini"

    transport.responses = [_Resp(200, _gemini_ok("gemini says so"))]
    text, _ = _call(holder)
    assert text == "gemini says so"
    assert holder["last_vendor"] == "gemini", "Gemini answered and must be recorded as such"


def test_gemini_recovering_re_arms_the_downgrade_log(transport, capsys):
    """The anti-latch half: a transient blip must not silence the log forever."""
    holder = {}
    transport.responses = [_Resp(400, _API_KEY_INVALID)]
    _call(holder)
    transport.responses = [_Resp(200, _gemini_ok("back"))]
    _call(holder)
    holder["gemini_downgrade_logged"] = False   # what the loop does on a gemini win
    capsys.readouterr()
    transport.responses = [_Resp(400, _API_KEY_INVALID)]
    _call(holder)
    assert "[narrator] Gemini" in capsys.readouterr().out, (
        "a second outage after a recovery must be reported again")


# ── the loop must consult it ─────────────────────────────────────────────────

def test_the_loop_clears_the_flag_only_when_gemini_came_back():
    """⛔ The bug was here, not in the brain: the reset ran on ANY successful
    tick. Read as structure, not as text — an `if` mentioning last_vendor
    somewhere in the function would satisfy a substring check while the reset
    sat outside it."""
    tree = ast.parse(textwrap.dedent(code_only(research._narrator_loop)))
    resets = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "gemini_downgrade_logged"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is False):
                resets.append(node)
    assert resets, "the narrator loop no longer re-arms the downgrade log at all"

    guarded = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "last_vendor" in ast.dump(node.test):
            guarded.extend(n for n in ast.walk(node) if n in resets)
    assert len(guarded) == len(resets), (
        f"{len(resets) - len(guarded)} reset(s) run without checking which vendor "
        f"answered — a tick that succeeded on Haiku would re-arm the log, which is "
        f"how one warning became 1125")


# ── the field is the answer for INVALID_ARGUMENT ─────────────────────────────
#
# The live run said, three times: `HTTP 400 INVALID_ARGUMENT: Request contains an
# invalid argument.` That rules the API key OUT — a rejected key says so in words
# — but it names nothing to change. Google puts the offending field one level
# down, in a BadRequest detail, and reading only the top-level `reason` left the
# message no more informative than the status code it already carried.

_INVALID_ARGUMENT = {
    "error": {
        "code": 400,
        "message": "Request contains an invalid argument.",
        "status": "INVALID_ARGUMENT",
        "details": [{
            "@type": "type.googleapis.com/google.rpc.BadRequest",
            "fieldViolations": [{
                "field": "generation_config.thinking_config.thinking_budget",
                "description": "Budget 0 is invalid for this model.",
            }],
        }],
    }
}


def test_an_invalid_argument_names_the_field(transport, capsys):
    transport.responses = [_Resp(400, _INVALID_ARGUMENT)]
    _call({})
    out = capsys.readouterr().out
    assert "INVALID_ARGUMENT" in out
    assert "thinking_budget" in out, (
        "the offending field is the only actionable part of this error and it "
        "lives in a fieldViolations detail, not in the message")
    assert "Budget 0 is invalid" in out, "the description says what to change it to"


def test_several_field_violations_are_all_reported(transport, capsys):
    body = json.loads(json.dumps(_INVALID_ARGUMENT))
    body["error"]["details"][0]["fieldViolations"].append(
        {"field": "generation_config.response_schema", "description": "Unknown name."})
    transport.responses = [_Resp(400, body)]
    _call({})
    out = capsys.readouterr().out
    assert "thinking_budget" in out and "response_schema" in out, (
        "reporting only the first violation sends someone back for a second run")


def test_a_violation_with_no_field_still_reports_its_description(transport, capsys):
    body = json.loads(json.dumps(_INVALID_ARGUMENT))
    body["error"]["details"][0]["fieldViolations"] = [{"description": "Bad payload."}]
    transport.responses = [_Resp(400, body)]
    _call({})
    assert "Bad payload." in capsys.readouterr().out


def test_an_error_with_no_violations_is_unchanged(transport, capsys):
    """The key-invalid shape has no fieldViolations — it must not grow an empty
    bracket, which reads as a truncated message."""
    transport.responses = [_Resp(400, _API_KEY_INVALID)]
    _call({})
    out = [ln for ln in capsys.readouterr().out.splitlines() if "[narrator] Gemini" in ln][0]
    assert "API key not valid" in out
    assert "[]" not in out and "[; " not in out
