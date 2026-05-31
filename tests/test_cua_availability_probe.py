"""#705 — CUA/Anthropic availability is INFRA, not a login nicety, so it must
be probed at Phase 0 regardless of "Skip login verification".

Incident shape: the Anthropic key powers BOTH the Vision and CUA tiers. The
ONLY place a dead key (capped / invalid / 429) surfaced was the P0 per-platform
login walk (verify_login_cua) — and `skipInitVerify` blanks that walk entirely
(preflight_platforms=[]). So with skip-verify on, a dead key flowed straight
into the run and FAILED OPEN at every phase-time gate (_phase_verify_gate),
silently degrading to the raw-DOM tier the codebase distrusts — no alert ever.

Fix: `_probe_cua_available` makes ONE minimal Anthropic call at P0, ABOVE the
skipInitVerify blanking, and reuses the existing fail-closed `cua_unavailable`
card. It fail-closes ONLY on structural classes (bad/capped key, rate-limit);
transient blips (529 / 5xx / net) stay non-blocking per the #705 taxonomy
(transient → silent, structural → paused decision).

Functional tests exercise the classification directly; source guards pin the
P0 wiring (runs before the skip-verify blanking, fail-closed, no Skip branch).
"""
import asyncio
import inspect

import pytest

import research
from research import CuaUnavailableError


# ── functional harness ──────────────────────────────────────────────────────
class _FakeMessages:
    def __init__(self, exc=None):
        self._exc = exc
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):  # sync — invoked via asyncio.to_thread
        self.calls += 1
        self.last_kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        return object()  # truthy; the probe ignores the body


class _FakeClient:
    def __init__(self, exc=None):
        self.messages = _FakeMessages(exc)


def _run(coro):
    return asyncio.run(coro)


def test_none_client_is_unavailable():
    with pytest.raises(CuaUnavailableError):
        _run(research._probe_cua_available(None))


def test_invalid_key_401_fails_closed():
    client = _FakeClient(exc=Exception(
        "Error code: 401 - {'error': {'type': 'authentication_error', "
        "'message': 'invalid x-api-key'}}"))
    with pytest.raises(CuaUnavailableError):
        _run(research._probe_cua_available(client))
    assert client.messages.calls == 1


def test_workspace_cap_fails_closed():
    client = _FakeClient(exc=Exception(
        "Error code: 400 - your workspace api usage limits have been reached"))
    with pytest.raises(CuaUnavailableError):
        _run(research._probe_cua_available(client))


def test_rate_limit_429_fails_closed():
    client = _FakeClient(exc=Exception(
        "Error code: 429 - {'error': {'type': 'rate_limit_error'}}"))
    with pytest.raises(CuaUnavailableError):
        _run(research._probe_cua_available(client))


def test_overload_529_is_non_blocking():
    # 529 is server-side transient — the run must proceed (per-phase CUA paths
    # own the retry); carding the user before the run even starts would violate
    # the #705 transient→silent rule.
    client = _FakeClient(exc=Exception(
        "Error code: 529 - {'error': {'type': 'overloaded_error'}}"))
    _run(research._probe_cua_available(client))  # must NOT raise
    assert client.messages.calls == 1


def test_transient_5xx_is_non_blocking():
    client = _FakeClient(exc=Exception("Error code: 503 - service unavailable"))
    _run(research._probe_cua_available(client))  # must NOT raise


def test_connection_blip_is_non_blocking():
    client = _FakeClient(exc=Exception("Connection error: failed to establish"))
    _run(research._probe_cua_available(client))  # must NOT raise


def test_success_makes_one_minimal_text_only_call():
    client = _FakeClient()
    _run(research._probe_cua_available(client))
    assert client.messages.calls == 1
    kw = client.messages.last_kwargs
    assert kw.get("max_tokens", 999) <= 4, "probe must be a minimal call"
    # text-only — no screenshot/image content (unlike _cua_login_call)
    assert "image" not in repr(kw.get("messages", [])), (
        "the availability probe must be text-only — it checks key/quota health, "
        "not a screenshot verdict."
    )


# ── source guards on the P0 wiring ───────────────────────────────────────────
def test_probe_classifies_structural_only():
    psrc = inspect.getsource(research._probe_cua_available)
    assert 'in ("rate_limit", "key")' in psrc, (
        "the probe must fail-closed ONLY on structural classes (key / "
        "rate_limit); transient + overload stay non-blocking (#705 taxonomy)."
    )
    assert "max_tokens=1" in psrc, "the probe must be a minimal one-token call."


def test_p0_runs_probe_above_skip_verify_blanking():
    src = inspect.getsource(research.run_pipeline)
    assert "_probe_cua_available(" in src, (
        "Phase 0 must invoke the CUA availability probe (#705)."
    )
    probe_at = src.index("_probe_cua_available(")
    # The DISTINCT skip-verify blanking line (not the initial empty init).
    blank_at = src.index("preflight_platforms = []  # Nothing to verify below")
    assert probe_at < blank_at, (
        "the probe must run BEFORE skipInitVerify blanks preflight_platforms — "
        "otherwise it gets skipped alongside login verification, which is the "
        "exact bug it closes (#705)."
    )


def test_p0_probe_is_fail_closed_with_no_skip_branch():
    src = inspect.getsource(research.run_pipeline)
    # Locate the probe block (from its call to the next phase-0 comment after).
    start = src.index("if preflight_platforms:")
    # The probe-loop body up to the skip-verify handling.
    block = src[start:src.index("preflight_platforms = []  # Nothing to verify below")]
    assert 'request_pause("cua_unavailable")' in block, (
        "the probe must raise the fail-closed cua_unavailable pause (#705)."
    )
    assert "fail_phase(" in block, (
        "the probe must surface the same Retry card via fail_phase (#705)."
    )
    # Fail-closed: no Skip — skipInitVerify must NOT bypass an infra failure.
    assert "skip_init_verify" not in block, (
        "the probe loop must NOT honor a skip signal — a dead-key infra failure "
        "is fail-closed; skip-verify is a login switch, not an infra bypass "
        "(#705)."
    )


def test_p0_probe_retracts_durable_card_on_resume():
    # REGRESSION (cross-check blocker): the #715 durable mirror is cleared by
    # the central seam ONLY on pipeline_resumed/stopped. In the skipInitVerify
    # path no downstream P0 gate emits one, so the probe MUST emit
    # pipeline_resumed when its pause resolves — else the resolved
    # cua_unavailable card re-surfaces on a cold chat-open during a healthy run.
    src = inspect.getsource(research.run_pipeline)
    start = src.index("if preflight_platforms:")
    block = src[start:src.index("preflight_platforms = []  # Nothing to verify below")]
    assert 'emit_event("pipeline_resumed"' in block, (
        "the probe retry path must emit pipeline_resumed so the central "
        "_clear_pending_decision seam retracts the durable cua_unavailable card "
        "on resume — parity with the sibling P0 gates (#705)."
    )
    # And it must fire BEFORE the retry is consumed / the loop re-probes, so the
    # mirror is gone before any re-card or the eventual success-break.
    assert (block.index('emit_event("pipeline_resumed"')
            < block.index("consume_retry_phase(0)")), (
        "pipeline_resumed must be emitted before consume_retry_phase so the "
        "durable card is retracted on every resume cycle (#705)."
    )
