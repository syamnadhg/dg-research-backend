"""Shared test helpers (importable; pytest prepends tests/ to sys.path)."""

from __future__ import annotations

import base64
import json
from typing import Any


class FakeResp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code: int, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload if payload is not None else {}
        self.text = text
        self.content = b"x" if payload is not None else b""

    def json(self) -> Any:
        return self._payload


def make_jwt(claims: dict[str, Any]) -> str:
    """A structurally-valid (UNSIGNED) JWT carrying `claims` in the payload.

    Good enough for _decode_jwt_claims, which reads claims without verifying the
    signature (we trust tokens we just minted via Google)."""

    def _seg(obj: dict[str, Any]) -> str:
        raw = json.dumps(obj).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f"{_seg({'alg': 'none', 'typ': 'JWT'})}.{_seg(claims)}.sig"
