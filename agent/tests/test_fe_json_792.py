"""The agent's two JSON calls to the web app: the GET that did not exist, and the
POST's missing 401 force-refresh retry (wave 7.9-2, B1 / #324 / #325).

⛔⛔ THE REAL FUNCTIONS, CAPTURED AT IMPORT. `conftest.py` replaces
`bridge._fe_api_post` AND `bridge._fe_api_get` for the whole suite so nothing can
talk to the real web app by accident. A test written against the module attribute
would therefore be testing that stub. These are bound before any fixture runs —
the same escape hatch `test_send_logs_crossverify_791.py` records.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge, config
from facade.session import RevokedError
from tests.conftest import code_only

_REAL_GET = bridge._fe_api_get
_REAL_POST = bridge._fe_api_post

_SRC = Path(bridge.__file__).read_text(encoding="utf-8")


class _Sess:
    """A session whose token behaviour a test scripts outright."""

    def __init__(self, tokens=("t1", "t2"), raise_on_force=None):
        self.tokens = list(tokens)
        self.calls: list[bool] = []
        self.raise_on_force = raise_on_force

    def id_token(self, force: bool = False) -> str:
        self.calls.append(force)
        if force and self.raise_on_force is not None:
            raise self.raise_on_force
        return self.tokens[min(len(self.calls) - 1, len(self.tokens) - 1)]


class _Reply:
    def __init__(self, status: int, payload=b"{}", boom: bool = False):
        self.status_code = status
        self.content = payload
        self._boom = boom

    def json(self):
        if self._boom:
            raise ValueError("not json")
        import json as _json
        return _json.loads(self.content.decode())


def _script(monkeypatch, verb: str, replies):
    """Answer each call in turn; record (url, headers, params/json, timeout)."""
    seen: list[dict] = []
    box = list(replies)

    def _fake(url, **kw):
        seen.append({"url": url, **kw})
        r = box.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(bridge.requests, verb, _fake)
    return seen


# ── the GET helper exists at all ─────────────────────────────────────────────

def test_the_agent_has_an_authenticated_get_to_the_web_app():
    # ⛔ THE POINT OF B1. Before this the facade carried exactly two GETs to
    # FE_BASE — the sign-in poll and the doctor's reachability probe — and
    # NEITHER sent the session. There was no authenticated read at all.
    assert callable(_REAL_GET)
    params = list(inspect.signature(_REAL_GET).parameters)
    assert params[:2] == ["sess", "path"], params


def test_the_get_sends_the_bearer_and_reads_the_body(monkeypatch):
    monkeypatch.setattr(config, "FE_BASE", "https://app.test")
    seen = _script(monkeypatch, "get", [_Reply(200, b'{"devices": [], "truncated": true}')])
    status, body = _REAL_GET(_Sess(), "/api/devices/public")
    assert status == 200 and body["truncated"] is True
    assert seen[0]["url"] == "https://app.test/api/devices/public"
    assert seen[0]["headers"]["Authorization"] == "Bearer t1"


def test_the_get_passes_query_params_through(monkeypatch):
    seen = _script(monkeypatch, "get", [_Reply(200)])
    _REAL_GET(_Sess(), "/api/x", {"a": "b"})
    assert seen[0]["params"] == {"a": "b"}


def test_the_get_never_raises_on_a_transport_failure(monkeypatch):
    monkeypatch.setattr(config, "FE_BASE", "https://app.test")
    _script(monkeypatch, "get", [bridge.requests.RequestException("down")])
    status, body = _REAL_GET(_Sess(), "/api/devices/public")
    assert status == 0
    # ⛔ AND IT NAMES THE WEB APP, not Google. The two hosts fail separately and
    # `_mint_bearer` exists because reporting one as the other sent people to
    # look at a service that was answering.
    assert "app.test" in body["error"]


def test_the_get_never_raises_when_the_session_is_dead(monkeypatch):
    _script(monkeypatch, "get", [])
    sess = _Sess()
    sess.raise_on_force = None

    def _dead(force=False):
        raise RevokedError("gone")

    sess.id_token = _dead
    status, body = _REAL_GET(sess, "/api/devices/public")
    assert status == 0 and body["reason"] == "revoked"


def test_the_get_survives_a_non_json_error_page(monkeypatch):
    # ⛔⛔ A NON-2xx IS NOT NECESSARILY JSON. Two statements in the web app's
    # device routes sit outside their own try, so a Firestore outage there comes
    # back as an HTML error page. Every caller reads body.get("error").
    _script(monkeypatch, "get", [_Reply(500, b"<html>boom</html>", boom=True)])
    status, body = _REAL_GET(_Sess(), "/api/devices/public")
    assert status == 500 and body == {}


def test_the_get_coerces_a_non_dict_body(monkeypatch):
    _script(monkeypatch, "get", [_Reply(200, b"[1, 2, 3]")])
    assert _REAL_GET(_Sess(), "/api/x") == (200, {})


# ── the 401 retry, on BOTH JSON helpers ──────────────────────────────────────

@pytest.mark.parametrize("helper,verb,call", [
    ("get", "get", lambda s: _REAL_GET(s, "/api/devices/public")),
    ("post", "post", lambda s: _REAL_POST(s, "/api/devices/claim", {"code": "X"})),
])
def test_a_401_is_retried_exactly_once_with_a_forced_token(monkeypatch, helper, verb, call):
    seen = _script(monkeypatch, verb, [_Reply(401), _Reply(200, b'{"ok": true}')])
    sess = _Sess(tokens=("stale", "fresh"))
    status, body = call(sess)
    assert status == 200 and body == {"ok": True}
    # ⛔ FORCED, NOT CACHED. Re-sending the token the app just refused would
    # produce the same 401 and call it a retry.
    assert sess.calls == [False, True]
    assert seen[0]["headers"]["Authorization"] == "Bearer stale"
    assert seen[1]["headers"]["Authorization"] == "Bearer fresh"


@pytest.mark.parametrize("verb,call", [
    ("get", lambda s: _REAL_GET(s, "/api/x")),
    ("post", lambda s: _REAL_POST(s, "/api/x", {})),
])
def test_a_second_401_is_not_retried_again(monkeypatch, verb, call):
    seen = _script(monkeypatch, verb, [_Reply(401), _Reply(401)])
    status, _body = call(_Sess())
    assert status == 401
    assert len(seen) == 2, "a loop would hammer the app with a token it refused"


@pytest.mark.parametrize("verb,call", [
    ("get", lambda s: _REAL_GET(s, "/api/x")),
    ("post", lambda s: _REAL_POST(s, "/api/x", {})),
])
def test_only_a_401_is_retried(monkeypatch, verb, call):
    for code in (403, 404, 409, 429, 500):
        seen = _script(monkeypatch, verb, [_Reply(code)])
        status, _ = call(_Sess())
        assert status == code and len(seen) == 1, code


@pytest.mark.parametrize("verb,call", [
    ("get", lambda s: _REAL_GET(s, "/api/x")),
    ("post", lambda s: _REAL_POST(s, "/api/x", {})),
])
def test_a_revoked_session_on_the_retry_answers_with_the_repair(monkeypatch, verb, call):
    # ⛔⛔ THE CASE THE DEFERRAL NOTE GOT WRONG. `id_token(force=False)` returns
    # the CACHED token without calling Google, so a genuinely revoked session
    # DOES reach a 401 — for about the fifty-five minutes the cache stays fresh.
    # The forced re-mint is what finally raises, and the sentence names the fix.
    _script(monkeypatch, verb, [_Reply(401)])
    sess = _Sess(raise_on_force=RevokedError("gone"))
    status, body = call(sess)
    assert status == 0 and body["reason"] == "revoked"
    assert "login again" in body["error"]


def test_the_post_still_never_raises_when_the_first_mint_dies(monkeypatch):
    _script(monkeypatch, "post", [])
    sess = _Sess()

    def _dead(force=False):
        raise RuntimeError("token endpoint down")

    sess.id_token = _dead
    status, body = _REAL_POST(sess, "/api/x", {})
    assert status == 0 and "could not refresh" in body["error"]


# ── the timeout the retry made load-bearing ──────────────────────────────────

def test_both_json_helpers_use_the_shared_timeout(monkeypatch):
    seen_g = _script(monkeypatch, "get", [_Reply(200)])
    _REAL_GET(_Sess(), "/api/x")
    seen_p = _script(monkeypatch, "post", [_Reply(200)])
    _REAL_POST(_Sess(), "/api/x", {})
    assert seen_g[0]["timeout"] == bridge._FE_JSON_TIMEOUT
    assert seen_p[0]["timeout"] == bridge._FE_JSON_TIMEOUT


def test_two_attempts_fit_inside_what_the_clients_wait(monkeypatch):
    # ⛔⛔ THE NUMBER IS SET BY THE RETRY, NOT BY THE ROUTE. `sr.py` waits 30
    # seconds and `cli.py`'s `_bridge_post` waits 30.0; past that the client does
    # not report a slow web app, it says the bridge is not running and tells
    # somebody to reinstall one that is fine. A quick 401, a token refresh
    # (capped at 10s in session.py) and one full second attempt must fit.
    refresh_cap = 10
    worst = bridge._FE_JSON_TIMEOUT + refresh_cap + 1
    assert worst < 30, f"a retried call can outlast both clients ({worst}s)"


def test_the_bytes_upload_keeps_its_own_longer_timeout():
    # ⛔ IT IS NOT SHARED. That one carries megabytes and its caller is already
    # waiting on a bundle; shortening it here would be a silent regression of a
    # different wave's fix.
    body = code_only(inspect.getsource(bridge._fe_api_post_bytes))
    assert "timeout=60" in body
    assert "_FE_JSON_TIMEOUT" not in body


# ── source guards ────────────────────────────────────────────────────────────

def test_neither_json_helper_mints_a_token_by_hand():
    # ⛔ THE MINT GOES THROUGH `_mint_bearer`, WHICH NEVER RAISES. Calling
    # `sess.id_token` directly here is what broke the never-raises promise once,
    # and the retry is a second chance to break it the same way.
    for fn in (_REAL_GET, _REAL_POST):
        body = code_only(inspect.getsource(fn))
        assert "sess.id_token(" not in body, fn.__name__
        assert body.count("_mint_bearer(") == 2, fn.__name__


def test_the_get_is_modelled_on_the_post_and_not_on_the_login_poll():
    # ⛔ The two GETs that already existed (`devicelogin.poll_once`, the doctor's
    # probe) send no Authorization header at all. A helper copied from those
    # would compile, run, and be refused by every route it was written for.
    body = code_only(inspect.getsource(_REAL_GET))
    assert 'Bearer {token}' in body


def test_the_deferral_note_is_gone_from_the_post():
    # ⛔ It said "NO 401 RETRY HERE YET … it belongs with the wave that revisits
    # those callers". This is that wave; a stale note beside a live retry is how
    # the next reader is told the opposite of what the code does.
    src = inspect.getsource(_REAL_POST)
    assert "NO 401 RETRY HERE YET" not in src


def test_the_suite_wide_stub_actually_replaces_the_get(monkeypatch):
    # ⛔⛔ THE STUB EXISTS SO NO TEST CAN REACH THE REAL WEB APP BY ACCIDENT, and
    # nothing noticed when it was removed: every test in this file captured the
    # REAL helper at import, and every test in the route file patches the seam
    # itself. So the one thing the fixture is for had no guard at all. A mutant
    # proved it.
    assert bridge._fe_api_get is not _REAL_GET, (
        "conftest's autouse fixture must replace _fe_api_get for the whole suite")
    assert bridge._fe_api_post is not _REAL_POST
    # And it must be inert — a call goes nowhere and records itself.
    status, _body = bridge._fe_api_get(None, "/api/devices/public")
    assert status == 200
    assert ("/api/devices/public", {}) in bridge._fe_calls


# ── the retry's one opt-out ─────────────────────────────────────────────────

def test_the_post_can_be_asked_not_to_retry(monkeypatch):
    # ⛔⛔ ONE CALLER RUNS IN A LOOP. `/updates` re-mints share links for EVERY
    # row it returns, inside one request — so on a session whose refresh token
    # died while its ID token is still cached, the retry turned one poll into one
    # forced Google token call PER RUN, all failing the same way, for a link the
    # caller treats as optional. Cross-verify found it.
    seen = _script(monkeypatch, "post", [_Reply(401)])
    sess = _Sess()
    status, _body = _REAL_POST(sess, "/api/mintSrLinks", {}, retry_401=False)
    assert status == 401
    assert len(seen) == 1 and sess.calls == [False]


def test_every_write_keeps_the_retry_by_default(monkeypatch):
    seen = _script(monkeypatch, "post", [_Reply(401), _Reply(200)])
    sess = _Sess()
    _REAL_POST(sess, "/api/devices/claim", {"code": "X"})
    assert len(seen) == 2 and sess.calls == [False, True]


def test_the_link_mint_is_the_only_caller_that_opts_out():
    # ⛔ A SOURCE PIN, because the whole point is WHICH call site does this. Any
    # other caller reaching for the opt-out is a write that lost its second
    # chance, which is the opposite of what this wave added.
    # ⛔ MATCHED AS A CALL ARGUMENT, NOT AS A SUBSTRING. The first version counted
    # every occurrence and found two — the call site and the docstring that
    # explains it — so the guard failed on prose about itself, which is this
    # project's most repeated test defect.
    src = code_only(_SRC)
    sites = [i for i, ln in enumerate(src.splitlines())
             if re.fullmatch(r"\s*retry_401=False\)\s*", ln)]
    assert len(sites) == 1, sites
    lines = src.splitlines()
    block = "\n".join(lines[max(0, sites[0] - 6):sites[0] + 1])
    assert "mintSrLinks" in block, block
