"""The remote-login device-flow HTTP client, against a mock FE broker."""

import pytest

from facade import devicelogin
from facade.devicelogin import DeviceLoginError


def test_start_returns_handle(mock_fe):
    base = mock_fe(start_resp={
        "code": "AB-12", "pollToken": "PT-1",
        "verifyUrl": "https://superresearch.io/connect-agent", "expiresIn": 600,
    })
    out = devicelogin.start(fe_base=base, runtime="hermes", label="Scout")
    assert out["code"] == "AB-12"
    assert out["pollToken"] == "PT-1"
    assert out["verifyUrl"].endswith("/connect-agent")
    assert out["expiresIn"] == 600


def test_start_missing_fields_errors(mock_fe):
    base = mock_fe(start_resp={"code": "AB-12"})  # no pollToken/verifyUrl
    with pytest.raises(DeviceLoginError):
        devicelogin.start(fe_base=base)


def test_start_http_error(mock_fe):
    base = mock_fe(start_status=500, start_resp={"error": "boom"})
    with pytest.raises(DeviceLoginError):
        devicelogin.start(fe_base=base)


def test_start_unreachable_broker_errors():
    with pytest.raises(DeviceLoginError):
        devicelogin.start(fe_base="http://127.0.0.1:1")  # nothing listening


def test_poll_pending_then_approved(mock_fe):
    base = mock_fe(poll_script=[
        (200, {"status": "pending"}),
        (200, {"status": "approved", "customToken": "CT-xyz"}),
    ])
    assert devicelogin.poll_once("PT", fe_base=base)["status"] == "pending"
    r = devicelogin.poll_once("PT", fe_base=base)
    assert r["status"] == "approved" and r["customToken"] == "CT-xyz"


def test_poll_410_is_expired(mock_fe):
    base = mock_fe(poll_script=[(410, {})])
    assert devicelogin.poll_once("PT", fe_base=base)["status"] == "expired"


def test_poll_approved_without_token_errors(mock_fe):
    base = mock_fe(poll_script=[(200, {"status": "approved"})])  # missing customToken
    with pytest.raises(DeviceLoginError):
        devicelogin.poll_once("PT", fe_base=base)


def test_poll_http_error(mock_fe):
    base = mock_fe(poll_script=[(503, {"error": "later"})])
    with pytest.raises(DeviceLoginError):
        devicelogin.poll_once("PT", fe_base=base)


def test_poll_transport_error_hides_polltoken(monkeypatch):
    # #12: a requests transport error embeds the prepared URL — which carries
    # ?pollToken=… — so poll_once must surface ONLY the exception type, never the
    # token, and must not chain the tokened exception into a leakable traceback.
    import requests

    secret = "PT-SECRET-abc123"

    def boom(*a, **k):
        raise requests.ConnectionError(
            "HTTPSConnectionPool(host='x'): Max retries exceeded with url: "
            f"/api/agent/login/poll?pollToken={secret}")

    monkeypatch.setattr(devicelogin.requests, "get", boom)
    with pytest.raises(DeviceLoginError) as ei:
        devicelogin.poll_once(secret, fe_base="https://x")
    msg = str(ei.value)
    assert secret not in msg                       # the token never reaches the message
    assert ei.value.__cause__ is None              # not chained via `from e`
    assert ei.value.__suppress_context__ is True   # context suppressed via `from None`
    assert "ConnectionError" in msg                # the useful type name IS surfaced
