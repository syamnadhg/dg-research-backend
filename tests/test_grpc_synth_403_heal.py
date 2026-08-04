"""#720 — synth-user 403 self-heal for the gRPC `_firebase_db` write path.

Incident shape: the Track-D rules (deviceMemberOf / deviceWritingTo /
deviceUpdatingFor) are correct AND deployed, the synth user's persisted custom
claims carry `deviceId`, and the device doc has the right ownerUid — yet every
user-tree research write (flip queued→ongoing, emit_event, status updates,
links) 403s with "Missing or insufficient permissions". Root cause: the gRPC
`_firebase_db` client's CACHED idToken doesn't present the live `deviceId`
claim (stale token / bootstrap claim-propagation race). The REST force-refresh
path (`_fresh_user_mode_id_token`) works because it re-mints every call; the
gRPC path reuses a cached token.

Fix: `_grpc_write_with_heal` wraps each gRPC user-tree write — on a synth-user
rules denial it force-refreshes the credential (re-reading live claims) and
retries once, throttled so a 403 storm can't hammer securetoken. Instruments
the token's actual claims vs the local config deviceId so the exact mechanism
(stale token / config-claim mismatch / multi-device doc mismatch) is
diagnosable on the next run.

Functional tests exercise the heal directly; source guards pin that every gRPC
user-tree write site is wrapped + the startup claim-verification exists.
"""
import base64
import inspect
import json

import pytest

import research
from conftest import code_only


# ── helpers ──────────────────────────────────────────────────────────────────
class PermissionDenied(Exception):
    """Mimics google.api_core.exceptions.PermissionDenied — the heal's detector
    keys on the class NAME, not the import, so this stands in faithfully."""


def _mk_token(claims: dict) -> str:
    """Build a fake but structurally-valid (header.payload.sig) Firebase JWT
    whose payload base64url-decodes to `claims`."""
    def _b64(obj):
        raw = json.dumps(obj).encode("ascii")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.sig"


class _FakeCreds:
    def __init__(self, token=None, token_after_refresh=None):
        self.token = token
        self.refresh_calls = 0
        self._after = token_after_refresh

    def refresh(self, request):  # signature mirrors google.auth Credentials
        self.refresh_calls += 1
        if self._after is not None:
            self.token = self._after


class _FakeDb:
    def __init__(self, creds):
        self._credentials = creds


@pytest.fixture(autouse=True)
def _reset_heal_state(monkeypatch):
    # Each test starts with the throttle + structural latch clear, and a stable
    # UNCACHED config deviceId so the diagnostic doesn't touch the real
    # research_config.json (the heal reads _config_device_id_uncached, not the
    # cached load_device_id).
    monkeypatch.setattr(research, "_grpc_heal_last_ts", 0.0, raising=False)
    monkeypatch.setattr(research, "_grpc_heal_consec_fail", 0, raising=False)
    monkeypatch.setattr(research, "_grpc_heal_structural", False, raising=False)
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: "cfg-device-xyz")
    yield


# ── _decode_jwt_claims ─────────────────────────────────────────────────────
def test_decode_valid_token():
    tok = _mk_token({"deviceId": "abc", "ownerUid": "u1"})
    assert research._decode_jwt_claims(tok) == {"deviceId": "abc", "ownerUid": "u1"}


def test_decode_none_and_malformed_return_empty():
    assert research._decode_jwt_claims(None) == {}
    assert research._decode_jwt_claims("") == {}
    assert research._decode_jwt_claims("not-a-jwt") == {}
    assert research._decode_jwt_claims("a.b") == {}  # only 2 segments


# ── _is_synth_permission_denied ────────────────────────────────────────────
def test_detects_direct_permission_denied():
    assert research._is_synth_permission_denied(PermissionDenied("denied")) is True


def test_detects_via_cause_context_chain():
    # The flip's "transaction has no transaction ID" ValueError masks the real
    # PermissionDenied as __context__ — the detector must walk the chain.
    ve = ValueError("The transaction has no transaction ID, so it cannot be rolled back.")
    ve.__context__ = PermissionDenied("Missing or insufficient permissions.")
    assert research._is_synth_permission_denied(ve) is True


def test_detects_message_substring():
    assert research._is_synth_permission_denied(
        RuntimeError("403 Missing or insufficient permissions")) is True
    assert research._is_synth_permission_denied(
        RuntimeError("rpc error: PERMISSION_DENIED")) is True


def test_ignores_unrelated_errors():
    assert research._is_synth_permission_denied(ValueError("totally unrelated")) is False
    assert research._is_synth_permission_denied(None) is False


def test_handles_cyclic_cause_chain():
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__context__ = b
    b.__context__ = a  # cycle — must not infinite-loop
    assert research._is_synth_permission_denied(a) is False


# ── _grpc_write_with_heal ──────────────────────────────────────────────────
def test_success_passes_through_without_refresh(monkeypatch):
    creds = _FakeCreds(token=_mk_token({"deviceId": "cfg-device-xyz"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    assert research._grpc_write_with_heal(lambda: "ok", what="t") == "ok"
    assert creds.refresh_calls == 0


def test_non_permission_error_reraises_without_refresh(monkeypatch):
    creds = _FakeCreds(token=_mk_token({"deviceId": "x"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))

    def op():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        research._grpc_write_with_heal(op, what="t")
    assert creds.refresh_calls == 0


def test_permission_denied_force_refreshes_and_retries_once(monkeypatch):
    # Stale token (no deviceId) → refresh mints a claim-bearing token → retry ok.
    creds = _FakeCreds(
        token=_mk_token({"ownerUid": "u1"}),  # NO deviceId — the bug
        token_after_refresh=_mk_token({"ownerUid": "u1", "deviceId": "cfg-device-xyz"}),
    )
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionDenied("Missing or insufficient permissions.")
        return "flipped"

    assert research._grpc_write_with_heal(op, what="flip") == "flipped"
    assert creds.refresh_calls == 1
    assert calls["n"] == 2  # original + one retry


def test_throttle_blocks_second_refresh_within_cooldown(monkeypatch):
    # A 403 storm: simulate a heal that JUST happened — the next 403 must NOT
    # force-refresh again (would hammer securetoken); it re-raises so the caller
    # degrades.
    creds = _FakeCreds(token=_mk_token({"ownerUid": "u1"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    import time as _t
    monkeypatch.setattr(research, "_grpc_heal_last_ts", _t.time(), raising=False)

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(op, what="emit_event")
    assert creds.refresh_calls == 0  # throttled — no refresh


def test_persistent_denial_refreshes_once_then_reraises(monkeypatch):
    # Token never gets a deviceId (e.g. config/claim mismatch a refresh can't
    # fix): heal refreshes ONCE, retry still 403s, exception propagates to the
    # caller's existing WARN+degrade handler.
    creds = _FakeCreds(token=_mk_token({"ownerUid": "u1"}))  # refresh changes nothing
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(op, what="update research")
    assert creds.refresh_calls == 1  # exactly one heal attempt


def test_no_credentials_object_is_safe(monkeypatch):
    # If _firebase_db has no _credentials, the heal must not crash — it logs and
    # re-attempts (op still 403s → re-raises).
    monkeypatch.setattr(research, "_firebase_db", object())

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(op, what="t")


def test_structural_latch_stops_refreshing_after_n_failures(monkeypatch):
    # A deterministic denial a refresh can't fix (config != claim deviceId):
    # after _GRPC_HEAL_STRUCTURAL_AFTER unhealed heals the heal latches
    # structural and STOPS force-refreshing (no more securetoken churn).
    creds = _FakeCreds(token=_mk_token({"ownerUid": "u1", "deviceId": "claim-abc"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: "cfg-different")
    monkeypatch.setattr(research, "_GRPC_HEAL_COOLDOWN_S", 0.0, raising=False)

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    n = research._GRPC_HEAL_STRUCTURAL_AFTER
    for _ in range(n):
        with pytest.raises(PermissionDenied):
            research._grpc_write_with_heal(op, what="update research")
    assert research._grpc_heal_structural is True
    assert creds.refresh_calls == n  # exactly n heals
    # Latched — a further denial must NOT force-refresh again.
    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(op, what="update research")
    assert creds.refresh_calls == n  # unchanged


def test_success_resets_structural_latch(monkeypatch):
    monkeypatch.setattr(research, "_firebase_db",
                        _FakeDb(_FakeCreds(token=_mk_token({"deviceId": "x"}))))
    monkeypatch.setattr(research, "_grpc_heal_structural", True, raising=False)
    monkeypatch.setattr(research, "_grpc_heal_consec_fail", 5, raising=False)
    assert research._grpc_write_with_heal(lambda: "ok", what="t") == "ok"
    assert research._grpc_heal_structural is False
    assert research._grpc_heal_consec_fail == 0


# ── source guards ──────────────────────────────────────────────────────────
# Each wrapped site carries a UNIQUE `what=` label; scanning the whole module
# source for every label proves all sites are wrapped, INCLUDING the run_server
# closures (flip, queue-pos batch) that inspect.getsource can't reach per-fn.
_EXPECTED_HEAL_LABELS = [
    "emit_event", "update research", "set research", "link ", "userSource ",
    "audio ", "document ", "phase-status phase=", "cmd-sweep delete",
    "cmd stale-skip mark", "cmd ping pong", "cmd stop mark",
    "cmd agent-decision-stop mark", "cmd tail delete", "flip queued→ongoing",
    "queue-pos batch", "deferred queue-pos batch", "sweep:",
    "cascade-sweep cmd delete", "delete_run cmd delete",
]


def test_every_grpc_user_tree_write_site_is_wrapped():
    src = inspect.getsource(research)
    missing = [lbl for lbl in _EXPECTED_HEAL_LABELS
               if f'what=f"{lbl}' not in src and f'what="{lbl}' not in src]
    assert not missing, (
        f"these gRPC user-tree write sites are not wrapped in _grpc_write_with_heal "
        f"(no matching what= label found): {missing} (#720)."
    )


def test_routed_writers_use_wrapped_helpers():
    # These route through the already-wrapped centralized helpers (which inject
    # _be_payload AND heal) instead of writing the gRPC client inline.
    agent_src = inspect.getsource(research._do_agent_terminal_status_write)
    assert "_set_research_doc(" in agent_src and ".collection(" not in agent_src, (
        "per-agent terminal status must route through _set_research_doc (#720)."
    )
    # #725 (DRY): the owner inline rehydration was migrated into
    # _rehydrate_ongoing_for_tree (run_server now delegates to it for BOTH the
    # owner and each sharer tree), so the paused_backend_restart mark lives in
    # the helper. The invariant is unchanged — it must still route through
    # _update_research_doc for deviceId injection + heal.
    rehydrate_src = inspect.getsource(research._rehydrate_ongoing_for_tree)
    assert "_update_research_doc(tree_uid, research_id" in rehydrate_src, (
        "rehydration's paused_backend_restart mark must route through "
        "_update_research_doc (deviceId injection + heal) (#720)."
    )
    # And run_server must actually delegate to the helper (no resurrected
    # inline duplicate).
    server_src = inspect.getsource(research.run_server)
    assert "_rehydrate_ongoing_for_tree(" in server_src, (
        "run_server must delegate rehydration to _rehydrate_ongoing_for_tree (#725 DRY)."
    )


def test_previously_raw_writes_now_inject_be_payload():
    # phase-status + stuck-sweep wrote RAW dicts (no deviceId) → denied even with
    # a fresh token under deviceUpdatingFor's payload clause. Must _be_payload now.
    assert "_be_payload({" in inspect.getsource(research._do_phase_terminal_status_write), (
        "phase-status update must _be_payload (#720).")
    assert "_be_payload(patch)" in inspect.getsource(research._sweep_stuck_research_docs), (
        "stuck-sweep update must _be_payload (#720).")


def test_credentials_refresh_serialized_by_shared_lock():
    from auth import credentials as _creds
    src = inspect.getsource(_creds.RefreshTokenCredentials.refresh)
    assert "_REFRESH_LOCK" in src, (
        "RefreshTokenCredentials.refresh must serialize via the shared "
        "_REFRESH_LOCK so concurrent refreshers can't corrupt the keystore "
        "rotation (#720)."
    )


def test_init_firebase_verifies_token_claim():
    src = inspect.getsource(research.init_firebase)
    assert "_grpc_token_claims()" in src and "deviceId" in src, (
        "init_firebase must verify the gRPC token carries the deviceId claim "
        "at bootstrap (force-refresh on miss) so the first write doesn't 403 "
        "(#720)."
    )


def test_heal_is_throttled_and_latches_structural():
    src = inspect.getsource(research._grpc_write_with_heal)
    assert "_GRPC_HEAL_COOLDOWN_S" in src, (
        "the heal MUST throttle force-refreshes — emit_event fires thousands of "
        "times per run; an unthrottled heal would hammer securetoken (#720)."
    )
    assert "_grpc_heal_structural" in src, (
        "heal must latch structural after repeated unhealed denials so a "
        "deterministic mismatch escalates once instead of churning (#720)."
    )
    # The misleading hard-coded '(deviceMemberOf)' cause label must be GONE —
    # write-side denials are deviceWritingTo/deviceUpdatingFor, not deviceMemberOf.
    assert "403 (deviceMemberOf)" not in src, (
        "heal must not hard-code '(deviceMemberOf)' as the cause (#720)."
    )


# ── the diagnosis must come from the outcome, not from a guess ─────────────
#
# 2026-08-04, from the live corpus. All 34 heals in it printed
# `likely cause: token+config deviceId AGREE — deviceOwnership / doc-deviceId
# mismatch` — a document problem. About half of them were then cleared by the
# re-mint, which a document problem cannot be. The deviceIds agreeing rules the
# write-side payload clause OUT; it says nothing about which of the survivors is
# at fault, and naming one sent every reader at the wrong thing.
#
# The retry IS the experiment, so both of its outcomes are now logged. The
# corpus recorded only that a heal was ATTEMPTED, so establishing whether any of
# the 34 worked meant pairing timestamps against the caller's degrade line by
# hand.

def _agreeing_creds():
    """Token and config carry the SAME deviceId — the branch every live denial
    lands in, and the one that used to assert a document mismatch."""
    return _FakeCreds(token=_mk_token({"deviceId": "cfg-device-xyz", "ownerUid": "u1"}))


def test_a_heal_that_worked_reports_a_stale_credential(monkeypatch, capsys):
    creds = _agreeing_creds()
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionDenied("Missing or insufficient permissions.")
        return "ok"

    assert research._grpc_write_with_heal(op, what="flip queued→ongoing abc…") == "ok"
    out = capsys.readouterr().out
    assert "cleared by the re-minted token" in out, (
        "a heal that worked leaves no record of having worked — which is why "
        "nobody could tell 34 attempts from 34 failures")
    assert "stale" in out
    assert "re-pair" not in out, (
        "a denial a re-mint fixed must never be reported as needing a re-pair")


def test_a_heal_that_failed_rules_the_credential_out(monkeypatch, capsys):
    creds = _agreeing_creds()
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(op, what="flip queued→ongoing abc…")
    out = capsys.readouterr().out
    assert "did NOT clear" in out, "an unhealed denial says nothing about itself"
    assert "WARN" in out, "an unhealed denial is not an INFO"
    assert "a stale credential was not the cause" in out


def test_the_agreeing_branch_no_longer_asserts_a_document_mismatch(monkeypatch, capsys):
    """⭐ The finding itself. The one certainty is what has been ruled OUT."""
    creds = _agreeing_creds()
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionDenied("Missing or insufficient permissions.")
        return "ok"

    research._grpc_write_with_heal(op, what="flip queued→ongoing abc…")
    attempt = [ln for ln in capsys.readouterr().out.splitlines()
               if "likely cause" in ln]
    assert len(attempt) == 1, attempt
    assert "deviceOwnership / doc-deviceId mismatch" not in attempt[0], (
        "the attempt line still names a document mismatch as THE cause, on the "
        "very path where a token re-mint then fixes it")
    assert "payload clause is satisfied" in attempt[0], (
        "it must still say what the agreeing deviceIds actually rule out")


def test_a_token_missing_the_claim_is_still_diagnosed_up_front(monkeypatch, capsys):
    """The two branches that CAN be decided before the retry still are — the
    change is only to the branch where the evidence does not decide."""
    creds = _FakeCreds(token=_mk_token({"ownerUid": "u1"}),
                       token_after_refresh=_mk_token({"deviceId": "cfg-device-xyz"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionDenied("Missing or insufficient permissions.")
        return "ok"

    research._grpc_write_with_heal(op, what="t")
    out = capsys.readouterr().out
    assert "token MISSING deviceId claim" in out


def test_a_mismatched_deviceid_is_still_diagnosed_up_front(monkeypatch, capsys):
    creds = _FakeCreds(token=_mk_token({"deviceId": "claim-abc", "ownerUid": "u1"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: "cfg-different")

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(op, what="t")
    out = capsys.readouterr().out
    assert "token/config deviceId MISMATCH" in out and "re-pair" in out


def test_an_unhealed_denial_is_visible_before_the_latch_ever_fires(monkeypatch, capsys):
    """⚠ Why this is per-occurrence. `_grpc_heal_consec_fail` is global and any
    successful write resets it — and the heartbeat succeeds constantly. The live
    corpus holds 16 unhealed denials and ZERO structural latches, so the ERROR
    that was meant to carry this never printed once."""
    creds = _agreeing_creds()
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    monkeypatch.setattr(research, "_GRPC_HEAL_COOLDOWN_S", 0.0, raising=False)

    def denied():
        raise PermissionDenied("Missing or insufficient permissions.")

    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(denied, what="t")
    research._grpc_write_with_heal(lambda: "ok", what="t")   # a heartbeat lands
    with pytest.raises(PermissionDenied):
        research._grpc_write_with_heal(denied, what="t")

    out = capsys.readouterr().out
    assert research._grpc_heal_structural is False, "precondition: the latch never fired"
    assert out.count("did NOT clear") == 2, (
        "each unhealed denial must report itself; the latch cannot be relied on")
    assert "STRUCTURAL" not in out


def test_the_latch_line_is_not_doubled_by_the_per_occurrence_warn(monkeypatch, capsys):
    """The escalation says everything the per-occurrence line does. Printing
    both on the same denial is how a real signal starts reading as noise."""
    creds = _FakeCreds(token=_mk_token({"deviceId": "claim-abc", "ownerUid": "u1"}))
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(creds))
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: "cfg-different")
    monkeypatch.setattr(research, "_GRPC_HEAL_COOLDOWN_S", 0.0, raising=False)

    def op():
        raise PermissionDenied("Missing or insufficient permissions.")

    for _ in range(research._GRPC_HEAL_STRUCTURAL_AFTER):
        with pytest.raises(PermissionDenied):
            research._grpc_write_with_heal(op, what="t")

    out = capsys.readouterr().out
    latch = [ln for ln in out.splitlines() if "STRUCTURAL" in ln]
    assert len(latch) == 1, latch
    # The denial that latched reports once, not twice.
    assert out.count("did NOT clear") == research._GRPC_HEAL_STRUCTURAL_AFTER - 1


def test_the_flip_degrade_leads_with_the_root_cause():
    """The masking is real and stays: google-cloud-firestore turns a denied read
    inside a transaction into "The transaction has no transaction ID, so it
    cannot be rolled back". Appending the root was not enough — the line still
    OPENED with the rollback artifact, and every occurrence in the corpus reads
    that way."""
    src = code_only(inspect.getsource(research.run_server))
    assert 'f"Failed to flip queued→ongoing for {research_id_val}: {_head}"' in src, (
        "the flip degrade no longer leads with the root cause")
    assert 'f"Failed to flip queued→ongoing for {research_id_val}: {e}"' not in src, (
        "the wrapper's rollback message is back in front of the real fault")
    head = src.split("_head =", 1)[1].split("\n", 1)[0]
    assert "_root" in head, "the head must be built from the root, not from the wrapper"
