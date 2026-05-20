"""Unit tests for Track D `auth/v2_flow.py` — PR-D3 surface.

Covers the deterministic helpers (pollSecret, hash, REST envelope
unwrap) + the HTTP error paths via `monkeypatch`-injected fake
`requests.post/get`. The full async polling loop is exercised against
a mocked Firestore that flips from empty → token on the third tick.
The actual end-to-end FE↔BE pair handshake is an integration test that
needs both sides live; not run here.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from auth import v2_flow


# ─── Pure helpers ─────────────────────────────────────────────────────


class TestPollSecret:
    def test_generate_returns_64_hex(self):
        for _ in range(20):
            s = v2_flow.generate_poll_secret()
            assert re.fullmatch(r"[0-9a-f]{64}", s), s

    def test_generate_is_unique(self):
        # 256 bits of entropy — collisions across 200 draws are
        # astronomically unlikely.
        samples = {v2_flow.generate_poll_secret() for _ in range(200)}
        assert len(samples) == 200

    def test_hash_is_deterministic(self):
        # SHA-256 of the same input always produces the same hash.
        secret = "abc123" * 10  # 60-char input; not real format but valid for hash test
        assert v2_flow.compute_poll_secret_hash(secret) == v2_flow.compute_poll_secret_hash(secret)

    def test_hash_format(self):
        secret = v2_flow.generate_poll_secret()
        h = v2_flow.compute_poll_secret_hash(secret)
        assert re.fullmatch(r"[0-9a-f]{64}", h), h

    def test_hash_changes_with_input(self):
        a = v2_flow.compute_poll_secret_hash("secret-a")
        b = v2_flow.compute_poll_secret_hash("secret-b")
        assert a != b

    def test_hash_of_known_input(self):
        # Lock the algorithm — SHA-256 of "hello" should be exactly this.
        # If this fails, someone swapped the hash function.
        import hashlib
        expected = hashlib.sha256(b"hello").hexdigest()
        assert v2_flow.compute_poll_secret_hash("hello") == expected


# ─── Firestore REST envelope unwrap ────────────────────────────────────


class TestExtractCustomToken:
    def test_extracts_string_value(self):
        payload = {
            "name": "projects/.../documents/devices/abc/pending/xyz",
            "fields": {
                "customToken": {"stringValue": "the.jwt.string"},
                "createdAt": {"timestampValue": "2026-05-20T12:00:00Z"},
            },
        }
        assert v2_flow._extract_custom_token(payload) == "the.jwt.string"

    def test_missing_field_returns_none(self):
        payload = {"fields": {"createdAt": {"timestampValue": "..."}}}
        assert v2_flow._extract_custom_token(payload) is None

    def test_empty_fields_returns_none(self):
        assert v2_flow._extract_custom_token({"fields": {}}) is None

    def test_empty_envelope_returns_none(self):
        assert v2_flow._extract_custom_token({}) is None

    def test_wrong_value_type_returns_none(self):
        # The field exists but stringValue is missing (e.g., someone
        # wrote it as integerValue by mistake). Don't crash — return None.
        payload = {"fields": {"customToken": {"integerValue": 42}}}
        assert v2_flow._extract_custom_token(payload) is None

    def test_empty_string_value_returns_none(self):
        # An empty string is treated as "not ready yet" — don't propagate
        # an empty customToken to the exchange call.
        payload = {"fields": {"customToken": {"stringValue": ""}}}
        assert v2_flow._extract_custom_token(payload) is None


# ─── initiate_pair_remote ─────────────────────────────────────────────


class TestInitiatePairRemote:
    def _make_response(self, status: int, body: dict | str = ""):
        class FakeResp:
            ok = 200 <= status < 300
            status_code = status
            text = body if isinstance(body, str) else ""

            def json(self):
                if isinstance(body, dict):
                    return body
                raise ValueError("not JSON")

        return FakeResp()

    def test_success_returns_device_id_and_pair_code(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["body"] = kwargs.get("json", {})
            return self._make_response(200, {"deviceId": "dev-xyz", "pairCode": "K7XQ9B2M"})

        monkeypatch.setattr(v2_flow.requests, "post", fake_post)
        out = v2_flow.initiate_pair_remote(
            poll_secret_hash="a" * 64,
            machine_name="mach-1",
            hostname="host-1",
            os_string="Linux 6.1",
        )
        assert out == {"deviceId": "dev-xyz", "pairCode": "K7XQ9B2M"}
        # Verify it hit the right URL + sent the hash in the body
        assert captured["url"].endswith("/api/devices/initiate-pair")
        assert captured["body"]["pollSecretHash"] == "a" * 64

    def test_http_500_raises(self, monkeypatch):
        monkeypatch.setattr(
            v2_flow.requests, "post",
            lambda url, **kw: self._make_response(500, "Internal Server Error"),
        )
        with pytest.raises(v2_flow.InitiatePairError) as exc:
            v2_flow.initiate_pair_remote(
                poll_secret_hash="a" * 64, machine_name="m", hostname="h", os_string="o",
            )
        assert "500" in str(exc.value)

    def test_http_400_with_json_error_surfaces_message(self, monkeypatch):
        monkeypatch.setattr(
            v2_flow.requests, "post",
            lambda url, **kw: self._make_response(400, {"error": "invalid_poll_secret_hash"}),
        )
        with pytest.raises(v2_flow.InitiatePairError) as exc:
            v2_flow.initiate_pair_remote(
                poll_secret_hash="bad", machine_name="m", hostname="h", os_string="o",
            )
        msg = str(exc.value)
        assert "400" in msg
        assert "invalid_poll_secret_hash" in msg

    def test_missing_fields_raises(self, monkeypatch):
        monkeypatch.setattr(
            v2_flow.requests, "post",
            lambda url, **kw: self._make_response(200, {"deviceId": "dev-xyz"}),  # no pairCode
        )
        with pytest.raises(v2_flow.InitiatePairError) as exc:
            v2_flow.initiate_pair_remote(
                poll_secret_hash="a" * 64, machine_name="m", hostname="h", os_string="o",
            )
        assert "missing" in str(exc.value).lower()

    def test_network_error_raises_initiate_pair_error(self, monkeypatch):
        def fake_post(url, **kw):
            raise v2_flow.requests.ConnectionError("dns fail")

        monkeypatch.setattr(v2_flow.requests, "post", fake_post)
        with pytest.raises(v2_flow.InitiatePairError) as exc:
            v2_flow.initiate_pair_remote(
                poll_secret_hash="a" * 64, machine_name="m", hostname="h", os_string="o",
            )
        assert "network error" in str(exc.value)


# ─── poll_pending_token ───────────────────────────────────────────────


class TestPollPendingToken:
    """Mocked Firestore REST. Each call to requests.get returns the next
    queued response, simulating the "doc appears on the Nth tick" path."""

    def _make_response(self, status: int, body=None):
        class FakeResp:
            status_code = status

            def json(self):
                return body if body is not None else {}

        return FakeResp()

    def _queued_get(self, monkeypatch, responses):
        idx = {"i": 0}

        def fake_get(url, **kw):
            i = idx["i"]
            idx["i"] = min(i + 1, len(responses) - 1)
            return responses[i]

        monkeypatch.setattr(v2_flow.requests, "get", fake_get)

    def test_returns_token_when_doc_appears(self, monkeypatch):
        ready = self._make_response(
            200,
            {"fields": {"customToken": {"stringValue": "the-jwt"}}},
        )
        self._queued_get(monkeypatch, [
            self._make_response(404),
            self._make_response(404),
            ready,
        ])
        result = asyncio.run(
            v2_flow.poll_pending_token(
                device_id="dev-xyz",
                poll_secret_hash="a" * 64,
                timeout_seconds=30,
                interval_seconds=0.01,  # fast-forward poll loop
            )
        )
        assert result == "the-jwt"

    def test_raises_poll_timeout_when_window_expires(self, monkeypatch):
        self._queued_get(monkeypatch, [self._make_response(404)])
        with pytest.raises(v2_flow.PollTimeout):
            asyncio.run(
                v2_flow.poll_pending_token(
                    device_id="dev-xyz",
                    poll_secret_hash="a" * 64,
                    timeout_seconds=0.05,  # window closes almost immediately
                    interval_seconds=0.01,
                )
            )

    def test_keeps_polling_through_transient_network_error(self, monkeypatch):
        # First call raises, second returns the token. The poll loop must
        # swallow transient errors instead of bailing.
        idx = {"i": 0}
        ready = self._make_response(
            200, {"fields": {"customToken": {"stringValue": "got-it"}}}
        )

        def fake_get(url, **kw):
            i = idx["i"]
            idx["i"] += 1
            if i == 0:
                raise v2_flow.requests.ConnectionError("transient")
            return ready

        monkeypatch.setattr(v2_flow.requests, "get", fake_get)
        result = asyncio.run(
            v2_flow.poll_pending_token(
                device_id="dev-xyz",
                poll_secret_hash="a" * 64,
                timeout_seconds=5,
                interval_seconds=0.01,
            )
        )
        assert result == "got-it"

    def test_on_tick_callback_fires(self, monkeypatch):
        # Callback should fire at least once before the token appears.
        ready = self._make_response(
            200, {"fields": {"customToken": {"stringValue": "tok"}}}
        )
        self._queued_get(monkeypatch, [
            self._make_response(404),
            self._make_response(404),
            ready,
        ])
        ticks = []
        asyncio.run(
            v2_flow.poll_pending_token(
                device_id="dev-xyz",
                poll_secret_hash="a" * 64,
                timeout_seconds=30,
                interval_seconds=0.01,
                on_tick=lambda elapsed: ticks.append(elapsed),
            )
        )
        assert len(ticks) >= 1
        # First tick should be near 0 (we tick BEFORE polling).
        assert ticks[0] == pytest.approx(0.0, abs=0.05)


# ─── URL construction ─────────────────────────────────────────────────


class TestFirestoreRestUrl:
    def test_uses_project_id_from_config(self):
        url = v2_flow._firestore_rest_url("dev-abc", "deadbeef" * 8)
        assert v2_flow.PROJECT_ID in url
        assert "/devices/dev-abc/pending/" in url
        assert url.endswith("deadbeef" * 8)


# ─── JWT user_id fallback (signInWithCustomToken localId drop) ────────


class TestUidFromIdToken:
    """The signInWithCustomToken REST response stopped including `localId`
    at some point in 2026; the uid only lives in the idToken JWT now.
    `_uid_from_id_token` is the no-verify base64 decoder that pulls it
    out. These tests pin its happy path + every malformed-input branch
    so a future refactor can't quietly break pair on a Firebase API
    drift again."""

    import base64
    import json

    @staticmethod
    def _make_jwt(payload: dict) -> str:
        """Build a synthetic 3-segment JWT with the given payload. No
        signature verification anywhere in the helper, so the header
        + signature can be arbitrary strings."""
        import base64 as _b64
        import json as _j
        payload_b64 = (
            _b64.urlsafe_b64encode(_j.dumps(payload).encode("ascii"))
            .decode("ascii")
            .rstrip("=")
        )
        return f"header.{payload_b64}.signature"

    def test_extracts_user_id_claim(self):
        jwt = self._make_jwt({"user_id": "device-abc123", "iss": "test"})
        assert v2_flow._uid_from_id_token(jwt) == "device-abc123"

    def test_falls_back_to_sub_when_user_id_missing(self):
        # Some Firebase ID tokens carry only `sub` (standard JWT subject
        # claim) without the user_id alias. The helper accepts either.
        jwt = self._make_jwt({"sub": "device-fallback", "iss": "test"})
        assert v2_flow._uid_from_id_token(jwt) == "device-fallback"

    def test_user_id_wins_over_sub(self):
        # If both are present, prefer user_id — it's Firebase's
        # canonical field name in their ID tokens.
        jwt = self._make_jwt({"user_id": "via-user-id", "sub": "via-sub"})
        assert v2_flow._uid_from_id_token(jwt) == "via-user-id"

    def test_returns_none_on_missing_segments(self):
        assert v2_flow._uid_from_id_token("not.a.jwt") is None
        assert v2_flow._uid_from_id_token("only.two") is None
        assert v2_flow._uid_from_id_token("") is None
        assert v2_flow._uid_from_id_token("one") is None

    def test_returns_none_on_garbage_payload(self):
        # Middle segment isn't valid base64 → catch + return None.
        assert v2_flow._uid_from_id_token("header.!!!garbage!!!.sig") is None

    def test_returns_none_when_no_uid_claim(self):
        jwt = self._make_jwt({"iss": "test", "exp": 9999})
        assert v2_flow._uid_from_id_token(jwt) is None

    def test_returns_none_on_non_string_uid(self):
        # JWT spec allows arbitrary types; we want a string only.
        jwt = self._make_jwt({"user_id": 12345})
        assert v2_flow._uid_from_id_token(jwt) is None

    def test_handles_payload_with_uncommon_padding(self):
        # Build a JWT whose payload b64-encodes to a length needing 1
        # padding char (`{"u":"a"}` → 10 chars, base64 → 16 chars = no
        # padding needed). Force a different shape:
        jwt = self._make_jwt({"user_id": "abc"})  # likely needs padding
        # No exception, returns the value cleanly.
        assert v2_flow._uid_from_id_token(jwt) == "abc"
