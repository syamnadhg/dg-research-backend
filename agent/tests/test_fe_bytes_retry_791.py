"""The log upload retries once on a 401 with a freshly minted token (wave 7.9-1,
2026-09-06).

⛔⛔ THE FIRESTORE CLIENT HAS DONE THIS SINCE IT WAS WRITTEN AND THE FE HELPERS
NEVER HAVE. Freshness is decided by the LOCAL clock alone: `id_token()` refreshes
only inside a five-minute margin, so a server that disagrees, a signing key
rotated under us, or simply a token that dies mid-call all produce a 401 against
a token the caller believes is good. Of the two FE helpers the BYTES one is the
likeliest to hit it — a sixty-second timeout and a multi-megabyte body — and it
was the one with no second chance.

⛔ WAVE 1 OWNS THIS HALF AND ONLY THIS HALF. `_fe_api_post_bytes` has exactly one
caller in the package, the send-logs upload route, which is this wave's own. The
JSON sibling's retry is wave 2's: its four callers are device pair, device remove,
the owner notice and the link mint, and three of them sit inside `except
RevokedError` blocks that would stop firing if the helper stopped raising.

⛔⛔ AND THE RETRY NEARLY BROKE THE HELPER'S "NEVER RAISES" CONTRACT. Minting a
token can fail two ways — `RevokedError` when the refresh token is dead, and a
transport error reaching Google — and the one caller makes this call OUTSIDE its
`except RevokedError`. `do_POST` has no blanket handler, so an escaping exception
unwinds into `http.server`, which closes the connection: the person waiting on the
upload gets a dropped socket instead of the sentence this file wrote for them.
Both mints are wrapped, and the FIRST one too — it could already raise before any
retry existed.

⛔ NOTHING IN THE SUITE EXECUTED THESE HELPER BODIES. An autouse fixture replaces
the JSON one for the whole run and every route test stubs the bytes one, so there
was no no-retry behaviour to rewrite — and no coverage either. These call the real
function.
"""

from types import SimpleNamespace

import pytest

from facade import bridge
from facade.session import RevokedError


class _Sess:
    """A session that hands out a different token each time it is forced."""

    def __init__(self, *, fail=None):
        self.calls: list = []
        self._fail = fail
        self._n = 0

    def id_token(self, force: bool = False) -> str:
        self.calls.append(force)
        if self._fail is not None:
            raise self._fail
        if force:
            self._n += 1
            return f"fresh-{self._n}"
        return "cached"


def _fake_post(script, seen):
    """`requests.post` replaced by a scripted sequence of statuses."""
    def post(url, data=None, headers=None, timeout=None):
        seen.append({"url": url, "data": data,
                     "auth": (headers or {}).get("Authorization")})
        status = script[min(len(seen) - 1, len(script) - 1)]
        if isinstance(status, Exception):
            raise status
        return SimpleNamespace(status_code=status, content=b'{"stored":true}',
                               json=lambda: {"stored": True})
    return post


def _call(monkeypatch, script, sess=None):
    seen: list = []
    monkeypatch.setattr(bridge.requests, "post", _fake_post(script, seen))
    sess = sess or _Sess()
    status, body = bridge._fe_api_post_bytes(
        sess, "/api/logs/agent-log", b"hello", "text/plain", {"x-support-code": "K7XQ9B2M"})
    return status, body, sess, seen


# ── the happy path is untouched ───────────────────────────────────────────────

def test_a_200_sends_once_with_the_cached_token(monkeypatch):
    """⛔ NO EXTRA MINT ON THE ORDINARY PATH. A helper that forced a refresh every
    call would burn a network round trip against Google on every upload."""
    status, body, sess, seen = _call(monkeypatch, [200])
    assert (status, body) == (200, {"stored": True})
    assert len(seen) == 1
    assert sess.calls == [False]
    assert seen[0]["auth"] == "Bearer cached"


def test_the_body_and_the_headers_still_go(monkeypatch):
    _, _, _, seen = _call(monkeypatch, [200])
    assert seen[0]["data"] == b"hello"


@pytest.mark.parametrize("status", [400, 403, 404, 409, 500, 502, 503])
def test_no_other_status_is_retried(monkeypatch, status):
    """⛔ ONLY 401. Any other status is the caller's to interpret, and a helper
    that retried a 500 would double a body the app already choked on."""
    got, _, sess, seen = _call(monkeypatch, [status])
    assert got == status
    assert len(seen) == 1
    assert sess.calls == [False]


# ── the retry ─────────────────────────────────────────────────────────────────

def test_a_401_is_retried_once_with_a_FORCED_token(monkeypatch):
    """⛔⛔ THE ORDER OF THE TOKENS IS THE PROPERTY, not the fact that it
    succeeded. Re-sending the token the app just refused would 401 again and call
    itself a retry — the exact mutant a "did it eventually work" assertion cannot
    see."""
    status, body, sess, seen = _call(monkeypatch, [401, 200])
    assert status == 200
    assert sess.calls == [False, True], sess.calls
    assert [s["auth"] for s in seen] == ["Bearer cached", "Bearer fresh-1"]


def test_the_retry_re_sends_the_same_bytes(monkeypatch):
    """⭐ The blob is already in memory, so the second send needs no re-read of the
    log — and must not send something else."""
    _, _, _, seen = _call(monkeypatch, [401, 200])
    assert [s["data"] for s in seen] == [b"hello", b"hello"]


def test_a_second_401_comes_back_as_a_401_and_does_not_loop(monkeypatch):
    """⛔⛔ EXACTLY TWICE. Without the count, an infinite-retry mutant lives: the
    outcome is identical and only the number of requests tells them apart."""
    status, _, sess, seen = _call(monkeypatch, [401, 401])
    assert status == 401
    assert len(seen) == 2, seen
    assert sess.calls == [False, True]


# ── it still never raises ─────────────────────────────────────────────────────

def test_a_revoked_session_comes_back_as_a_tuple(monkeypatch):
    """⛔⛔ THE ONE CALLER MAKES THIS CALL OUTSIDE ITS `except RevokedError`, and
    `do_POST` has no blanket handler. An escaping exception is not a 502 — it is a
    closed socket and no reply at all."""
    sess = _Sess(fail=RevokedError("refresh token rejected"))
    status, body, _, _ = _call(monkeypatch, [200], sess)
    assert status == 0
    assert body["reason"] == "revoked"
    assert "login again" in body["error"]


def test_a_revoked_session_on_the_RETRY_also_comes_back_as_a_tuple(monkeypatch):
    """⛔ THE SECOND MINT IS THE ONE THE RETRY ADDED, and it is the likelier of the
    two to fail — a 401 is exactly what a revoked session produces."""
    class _Dies:
        def __init__(self):
            self.calls: list = []

        def id_token(self, force: bool = False) -> str:
            self.calls.append(force)
            if force:
                raise RevokedError("refresh token rejected")
            return "cached"

    sess = _Dies()
    status, body, _, seen = _call(monkeypatch, [401, 200], sess)
    assert status == 0
    assert body["reason"] == "revoked"
    assert len(seen) == 1, "it sent again with no token"


def test_a_refresh_that_cannot_reach_google_is_not_reported_as_the_app(monkeypatch):
    """⛔ THE OLD SHAPE BLAMED THE WRONG HOST. `id_token()` was evaluated inside a
    `try` that caught `requests.RequestException`, so a network failure reaching
    Google's token endpoint was reported as "could not reach" the web app — a
    sentence pointing somebody at a service that was answering fine."""
    sess = _Sess(fail=bridge.requests.ConnectionError("dns"))
    status, body, _, _ = _call(monkeypatch, [200], sess)
    assert status == 0
    assert "refresh this agent's sign-in" in body["error"]
    assert "could not reach" not in body["error"]


def test_a_transport_failure_on_the_send_still_reads_as_the_app(monkeypatch):
    """The complement: when the POST itself fails, naming the app IS right."""
    status, body, _, _ = _call(monkeypatch, [bridge.requests.ConnectionError("boom")])
    assert status == 0
    assert "could not reach" in body["error"]


def test_a_transport_failure_on_the_retry_is_reported_not_raised(monkeypatch):
    status, body, _, seen = _call(
        monkeypatch, [401, bridge.requests.ConnectionError("boom")])
    assert status == 0
    assert "could not reach" in body["error"]
    assert len(seen) == 2


def test_a_body_that_is_not_json_is_still_a_dict(monkeypatch):
    """Unchanged, and pinned because the rewrite moved this code."""
    seen: list = []

    def post(url, data=None, headers=None, timeout=None):
        seen.append(url)
        def _boom():
            raise ValueError("not json")
        return SimpleNamespace(status_code=200, content=b"<html>", json=_boom)

    monkeypatch.setattr(bridge.requests, "post", post)
    status, body = bridge._fe_api_post_bytes(_Sess(), "/p", b"x", "text/plain", {})
    assert (status, body) == (200, {})


# ── the route turns a dead session into the sentence the rest of the file uses ─

def test_the_route_relays_a_revoked_session_as_401():
    """⛔ THE GENERIC 502 NAMES NO CAUSE AND OFFERS NO ACTION, on a route whose
    retry has just proved the session is the problem. `get_log_bundle` above it
    answers 401 for exactly this, and it is the only reason a person can act on.
    Read from source: the branch has to sit BEFORE the generic one, or it is
    unreachable."""
    import inspect
    src = inspect.getsource(bridge)
    start = src.index("def _log_agent_log(self)")
    # ⛔⛔ TO THE END OF THE METHOD, NOT A BYTE COUNT. The first version took a
    # 4000-byte window whose far edge sat within a line or two of the last thing
    # it needed to find — so a comment added anywhere above would have pushed the
    # generic branch out of the window and the ordering assertion would have died
    # on a ValueError rather than caught anything.
    end = src.index("def _research(self)", start)
    block = src[start:end]
    revoked = block.index('reply.get("reason") == "revoked"')
    generic = block.index('"reason": "agent_log_not_sent"')
    assert revoked < generic, "the revoked branch is behind the generic one"
    assert "session revoked — run /login again" in block[revoked:generic]
