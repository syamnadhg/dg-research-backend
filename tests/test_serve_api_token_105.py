"""Wave 10.5 — the `--serve` local API asks who is calling.

⛔⛔ WHAT WAS WRONG. Open since 2026-08-31, skipped by two waves, and the last
wave on it said so in a test rather than fixing it: `--serve` ran an HTTP API
that authenticated NOBODY. Loopback binding (2026-09-05) narrowed the audience
to this machine; every route still answered whoever asked. Any process on the
computer, any script, any other login on a shared Mac could list every run on
the machine across every account, read the briefs and the reports, download the
podcasts, stop or delete somebody's research, and start a new one **billing the
Firebase account named in the request body**.

⭐ THE GATE IS ONE MIDDLEWARE, NOT FOURTEEN DECORATORS, and that is why
`test_every_route_the_machine_declares_is_behind_the_gate` below can enumerate
the routes out of `research.py` itself instead of trusting a list somebody
maintains. The wave's plan said four routes; the start-of-wave cross-check said
thirteen; the source says fourteen. A gate that counts is a gate that rots — a
gate that sits under all of them does not.

⭐ EXECUTED, NOT READ — with two named exceptions. The gate tests drive the
REAL middleware through a real ASGI app with a real client. FOUR tests call
`is_exempt` / `token_ok` directly rather than through the middleware
(`test_the_exemption_is_exactly_one_path`,
`test_the_exemption_is_an_exact_match_not_a_prefix`,
`test_a_trailing_slash_is_still_health`, `test_an_empty_token_file_is_not_a_password`),
so they would keep passing if a refactor inlined the decision into
`ServeTokenMiddleware.__call__` — which is why the prefix case is ALSO asserted
through the client in `test_the_exemption_is_an_exact_match_through_the_gate`.
The `research.py` half is source-pinned because `run_server` is a 2,000-line
async closure that cannot be called, and those tests say so where they sit.

Run:  pytest tests/test_serve_api_token_105.py -v
"""
import ast
import os
import sys
import re
import stat
import threading

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import research
from auth import keystore, serve_token
from auth.serve_token import (
    EXEMPT_PATHS,
    HEADER,
    ServeTokenMiddleware,
    ensure_token,
    is_exempt,
    read_token,
    token_ok,
    token_path,
)
from conftest import code_only


# ── the routes the machine actually declares, read from the source ───────────

def _declared_routes() -> "list[tuple[str, str]]":
    """Every `@app.<method>("<path>")` inside `run_server`, as (METHOD, path).

    ⛔ PARSED, NOT GREPPED. A regex over the file would also collect the route
    strings quoted in comments and docstrings (there are several), and the
    point of this list is that it is the set the server really serves.
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    server = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_server")
    out = []
    for node in ast.walk(server):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == "app"
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                out.append((dec.func.attr.upper(), dec.args[0].value))
    return out


ROUTES = _declared_routes()
RUN_SERVER = code_only(research.run_server)
SRC = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "research.py"), encoding="utf-8").read()


def _concrete(path: str) -> str:
    """`/api/runs/{run_id}/audio/{filename}` → `/api/runs/x/audio/x`."""
    return re.sub(r"\{[^}]+\}", "x", path)


def _shape(path: str) -> str:
    """The reference table writes `{id}`/`{type}` where the routes say
    `{run_id}`/`{doc_type}`, so parameter NAMES cannot be compared — the shape
    is what a reader matches on."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _route_keys() -> set:
    """(METHOD, shape) for every route `run_server` declares."""
    return {(m, _shape(p)) for m, p in ROUTES}


def _row_key(row: str) -> tuple:
    """(METHOD, shape) for a `_LOCAL_API_ROUTES` left-hand column."""
    method, path = row.split(None, 1)
    return (method.strip().upper(), _shape(path.strip()))


# ── a real app, wired the way research.py wires it ───────────────────────────

@pytest.fixture
def token(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    return ensure_token()


def _app(with_cors: bool = False, port: int = 8000) -> FastAPI:
    """The gate, over every route `research.py` declares.

    Order mirrors `run_server` exactly: the token gate is added FIRST so CORS,
    added second, ends up OUTERMOST. Getting that backwards is the whole
    subject of `test_a_browser_preflight_is_answered_by_cors_not_by_the_gate`.
    """
    app = FastAPI()
    app.add_middleware(ServeTokenMiddleware)
    if with_cors:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[f"http://localhost:{port}", f"http://127.0.0.1:{port}"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    async def _ok():
        return {"reached": True}

    for method, path in ROUTES:
        app.add_api_route(path, _ok, methods=[method])
    return app


@pytest.fixture
def client(token):
    with TestClient(_app(), raise_server_exceptions=False) as c:
        yield c


# ── the gate ─────────────────────────────────────────────────────────────────

def test_every_route_the_machine_declares_is_behind_the_gate(client):
    """⛔⛔ THE WHOLE WAVE, IN ONE ASSERTION. Not a list of four routes a plan
    remembered — every route `run_server` declares, enumerated from the source
    at collection time, so a fifteenth arrives already covered."""
    protected = [(m, p) for m, p in ROUTES if not is_exempt(p)]
    assert len(protected) >= 13, f"only found {len(protected)} routes — parser broke?"
    for method, path in protected:
        r = client.request(method, _concrete(path))
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} unauthenticated"


def test_the_right_token_opens_every_one_of_them(client, token):
    for method, path in ROUTES:
        r = client.request(method, _concrete(path), headers={HEADER: token})
        assert r.status_code == 200, f"{method} {path} refused a valid token"


def test_a_wrong_token_is_refused(client, token):
    r = client.get("/api/runs", headers={HEADER: token[:-1] + ("A" if token[-1] != "A" else "B")})
    assert r.status_code == 401


def test_an_empty_header_is_refused(client):
    for value in ("", "   "):
        assert client.get("/api/runs", headers={HEADER: value}).status_code == 401


def test_health_answers_without_a_token(client):
    """⭐ THE ONE EXEMPTION, AND IT IS NOT CONVENIENCE. Four callers probe
    `/api/health` and the worker watchdog FORCE-RESPAWNS a worker whose health
    goes unreachable. A liveness probe that can fail for an authentication
    reason kills healthy workers over an unreadable file."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"reached": True}


def test_the_exemption_is_exactly_one_path():
    """⛔ Growing this set is a decision about what a stranger on this machine
    may read, so it must never grow by accident."""
    assert EXEMPT_PATHS == frozenset({"/api/health"})


def test_the_exemption_is_an_exact_match_not_a_prefix(client):
    """⛔⛔ `startswith("/api/health")` would also open `/api/health-runs`, and
    the entire gate would then be one route name away from being off."""
    assert not is_exempt("/api/healthcheck")
    assert not is_exempt("/api/health/runs")
    assert not is_exempt("/api/runs")
    assert not is_exempt("")
    assert not is_exempt("/")


def test_a_trailing_slash_is_still_health():
    """⛔ THE FIRST HOP IS WHAT MATTERS. Starlette's slash redirect is issued
    by the ROUTER, which sits INSIDE this gate — so a request that arrives as
    `/api/health/` is judged here, with the slash still on it, before anything
    can redirect it. Without the normalisation that first hop answers 401 and
    the redirect never happens at all."""
    assert is_exempt("/api/health/")


def test_the_token_does_not_authenticate_from_the_query_string(client, token):
    """⛔⛔ A URL-borne secret lands in uvicorn's access log, in shell history
    and in every proxy in between. `?token=…` must NOT work even when the value
    is exactly right — this is the test that keeps somebody from 'helpfully'
    adding the convenience."""
    for url in (f"/api/runs?token={token}",
                f"/api/runs?{HEADER}={token}",
                f"/api/runs?access_token={token}"):
        assert client.get(url).status_code == 401, url


def test_no_second_header_is_accepted(client, token):
    """⛔ ONE header, named once. `Authorization: Bearer` is the reflex reach
    and it is not wired — if it ever is, it must be a decision, not a drift."""
    for name in ("authorization", "x-api-key", "x-auth-token", "cookie"):
        r = client.get("/api/runs", headers={name: f"Bearer {token}"})
        assert r.status_code == 401, name


def test_the_refusal_names_the_file_and_never_the_value(client, token):
    body = client.get("/api/runs").json()
    assert body["error"] == "unauthorized"
    assert HEADER in body["detail"]
    assert serve_token.TOKEN_FILENAME in body["detail"]
    assert token not in body["detail"], "the 401 handed out the secret it was refusing"


def test_with_no_token_file_everything_is_refused_and_health_still_answers(tmp_path, monkeypatch):
    """⛔⛔ FAIL CLOSED. 'We could not check, so allow' is how a gate becomes
    decoration. A machine whose token file is missing serves nothing but its
    own liveness — which is also what keeps the watchdog from reaping it."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    assert read_token() is None
    with TestClient(_app(), raise_server_exceptions=False) as c:
        assert c.get("/api/runs").status_code == 401
        assert c.get("/api/runs", headers={HEADER: "anything"}).status_code == 401
        assert c.get("/api/health").status_code == 200


def test_an_empty_token_file_is_not_a_password(tmp_path, monkeypatch):
    """An empty or whitespace-only file must not mean 'send an empty header'."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    token_path().write_text("   \n", encoding="utf-8")
    assert read_token() is None
    assert token_ok("") is False
    assert token_ok("   ") is False
    assert token_ok(None) is False


def test_a_websocket_is_closed_rather_than_opened(token):
    """⛔ THE GATE IS ASGI-LEVEL, SO IT COVERS PROTOCOLS NO ROUTE SPEAKS. The
    `/ws/{run_id}` route was deleted in April; if one ever returns it arrives
    gated instead of arriving open."""
    app = FastAPI()
    app.add_middleware(ServeTokenMiddleware)

    # ⛔ THE ANNOTATION IS LOAD-BEARING. Without `: WebSocket` FastAPI treats
    # the parameter as a query field and closes the connection itself with
    # 1008 — the same code this gate uses — so the refusal assertion below
    # would have passed against a handler the gate never touched.
    from starlette.websockets import WebSocket

    @app.websocket("/ws/{run_id}")
    async def _ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("reached")

    # ⛔⛔ ASSERT ON WHAT ARRIVED, NOT ON AN EXCEPTION AROUND THE BLOCK. The
    # first version of this test wrapped the whole `with` in
    # `pytest.raises(WebSocketDisconnect)` — and the CLOSE AT TEARDOWN raises
    # that too, so it passed with the gate removed and mutation caught it. The
    # close CODE and the undelivered payload are the only honest evidence.
    from starlette.websockets import WebSocketDisconnect

    def _talk(client, headers=None):
        try:
            with client.websocket_connect("/ws/abc", headers=headers or {}) as ws:
                return ws.receive_text()
        except WebSocketDisconnect as exc:
            return f"closed:{exc.code}"

    with TestClient(app) as c:
        assert _talk(c) == "closed:1008", "an unauthenticated websocket was opened"
        assert _talk(c, {HEADER: token}) == "reached", "a valid token was refused"


def test_lifespan_still_runs(token):
    """⛔ A middleware that gated `lifespan` would break startup and shutdown
    for every worker — the gate must let the protocol events it is not about
    pass straight through."""
    from contextlib import asynccontextmanager
    seen = []

    @asynccontextmanager
    async def _lifespan(_app):
        seen.append("up")
        yield
        seen.append("down")

    app = FastAPI(lifespan=_lifespan)
    app.add_middleware(ServeTokenMiddleware)
    with TestClient(app):
        pass
    assert seen == ["up", "down"]


def test_a_browser_preflight_is_answered_by_cors_not_by_the_gate(token):
    """⛔⛔ THE ORDERING, EXECUTED. Starlette makes the LAST-added middleware
    the OUTERMOST, so `research.py` adds the gate FIRST and CORS SECOND. Swap
    them and this gate answers the preflight — which carries no headers to
    authenticate with — so every legitimate cross-origin call 401s before the
    origin policy has run, and the failure looks like a CORS bug."""
    with TestClient(_app(with_cors=True), raise_server_exceptions=False) as c:
        r = c.options("/api/runs", headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": HEADER,
        })
        assert r.status_code == 200, "the preflight was refused before CORS saw it"
        assert r.headers["access-control-allow-origin"] == "http://localhost:8000"


def test_a_preflight_does_not_let_the_real_request_through(token):
    """⭐ The other half: CORS answering OPTIONS must not mean the GET behind it
    is exempt."""
    with TestClient(_app(with_cors=True), raise_server_exceptions=False) as c:
        c.options("/api/runs", headers={"Origin": "http://localhost:8000",
                                        "Access-Control-Request-Method": "GET"})
        assert c.get("/api/runs", headers={"Origin": "http://localhost:8000"}).status_code == 401


# ── the token file ───────────────────────────────────────────────────────────

def test_the_token_lives_beside_the_keystore():
    """⭐ BY CONSTRUCTION, NOT BY A MATCHING LITERAL. Two copies of the path
    drift, and the drift lands a credential in a directory nothing protects."""
    assert "_FALLBACK_DIR" in code_only(serve_token)
    assert serve_token.TOKEN_FILENAME == "serve-api.token"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(serve_token, "_KEYSTORE_DIR", keystore._FALLBACK_DIR)
        assert token_path().parent == keystore._FALLBACK_DIR


def test_the_suite_never_mints_a_token_into_the_developers_real_home():
    """⛔⛔ THE TOKEN IS A LIVE CREDENTIAL IN `~/.super-research/`, and this
    wave gave the suite a reason to write one. `conftest` redirects it for
    EVERY test — not per-file, the way the keystore's own tests each remember
    to — because isolation each test has to remember is isolation the suite
    does not have. If that fixture is ever dropped, this goes red before a
    developer's running backend is disturbed by a test run."""
    from pathlib import Path
    assert serve_token._KEYSTORE_DIR != keystore._FALLBACK_DIR
    assert str(Path.home() / ".super-research") not in str(token_path())


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX mode bits; os.chmod is a near-noop on Windows — keystore._file_save documents the same exemption")
def test_it_is_created_owner_only(tmp_path, monkeypatch):
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    ensure_token()
    mode = stat.S_IMODE(token_path().stat().st_mode)
    assert mode & 0o077 == 0, f"group/world can read the token (mode {mode:o})"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX mode bits; os.chmod is a near-noop on Windows — keystore._file_save documents the same exemption")
def test_a_widened_mode_is_pulled_back(tmp_path, monkeypatch):
    """A backup tool, an rsync or a careless chmod widens it; the next boot
    must close it again rather than trust what it finds."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    first = ensure_token()
    os.chmod(token_path(), 0o644)
    assert ensure_token() == first
    assert stat.S_IMODE(token_path().stat().st_mode) & 0o077 == 0


def test_it_is_long_enough_that_guessing_is_not_a_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    assert len(ensure_token()) >= 32


def test_an_existing_token_is_never_replaced(tmp_path, monkeypatch):
    """⛔⛔ THE MULTI-WORKER BOOT RACE, MADE DETERMINISTIC. `--serve` starts N
    worker PROCESSES together. `read_token` here answers None on the first ask
    — the window a worker sees when it looks before another worker's write has
    landed — and the file already holds a value. An exclusive create loses that
    race and re-reads; a check-then-write would overwrite, invalidating the
    token every other worker has already handed out, and the machine would 401
    itself with nothing actually wrong."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    token_path().write_text("the-token-another-worker-already-minted", encoding="utf-8")
    real_read, calls = serve_token.read_token, {"n": 0}

    def _blind_once():
        calls["n"] += 1
        return None if calls["n"] == 1 else real_read()

    monkeypatch.setattr(serve_token, "read_token", _blind_once)
    assert ensure_token() == "the-token-another-worker-already-minted"
    monkeypatch.setattr(serve_token, "read_token", real_read)
    assert read_token() == "the-token-another-worker-already-minted"


def test_workers_racing_in_parallel_agree_on_one_token(tmp_path, monkeypatch):
    """The same race, run for real. Eight threads through one barrier: every
    one must come back with the SAME secret, and it must be the one on disk."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    barrier, results, errors = threading.Barrier(8), [], []

    def _worker():
        try:
            barrier.wait()
            results.append(ensure_token())
        except Exception as exc:  # pragma: no cover — a failure is the finding
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(set(results)) == 1, f"workers minted {len(set(results))} different tokens"
    assert results[0] == read_token()


def test_the_exemption_is_an_exact_match_through_the_gate(client):
    """⭐ THE SAME FACT AS `..._not_a_prefix`, BUT THROUGH THE MIDDLEWARE. That
    one calls `is_exempt` directly, so it would stay green if a refactor
    inlined a `startswith` into `ServeTokenMiddleware.__call__`. This one asks
    the gate."""
    app = FastAPI()
    app.add_middleware(ServeTokenMiddleware)

    async def _ok():
        return {"reached": True}

    for path in ("/api/health-runs", "/api/healthcheck", "/api/health/runs"):
        app.add_api_route(path, _ok, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as c:
        for path in ("/api/health-runs", "/api/healthcheck", "/api/health/runs"):
            assert c.get(path).status_code == 401, path


def test_a_non_ascii_header_is_refused_not_a_500(client):
    """⛔⛔ `hmac.compare_digest` ON TWO `str` OBJECTS REQUIRES BOTH TO BE
    ASCII-ONLY and raises TypeError otherwise. So `curl -H 'X-Super-Research-Token: café'`
    came out of the gate as a 500 with a traceback — a refusal that depends on
    what the refused caller sent. Found by cross-verify, not by me."""
    # ⛔ DRIVEN AT THE ASGI LAYER, because httpx REFUSES TO SEND a non-ASCII
    # header value — the test client would have hidden the defect behind its
    # own validation. curl has no such scruples, and neither does any other
    # local process.
    import asyncio

    def _status(raw_value: bytes) -> int:
        sent = []

        async def _send(msg):
            sent.append(msg)

        async def _receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def _app(scope, receive, send):  # pragma: no cover — never reached
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        scope = {"type": "http", "path": "/api/runs", "method": "GET",
                 "headers": [(HEADER.encode("ascii"), raw_value)], "query_string": b""}
        asyncio.run(ServeTokenMiddleware(_app)(scope, _receive, _send))
        return sent[0]["status"]

    for raw in ("caf\u00e9".encode("utf-8"), "\u4f60\u597d".encode("utf-8"),
                b"\xff\xfe\x00", "\U0001f600".encode("utf-8")):
        assert _status(raw) == 401, f"{raw!r} did not produce a clean 401"
    assert token_ok("caf\u00e9") is False


def test_a_token_file_that_is_not_utf8_refuses_rather_than_raising(tmp_path, monkeypatch):
    """⛔ `UnicodeDecodeError` IS NOT AN `OSError`. A token file saved as UTF-16
    (Windows Notepad's legacy 'Unicode' default) or truncated by a restore used
    to raise straight out of the middleware: 500 on every request, while
    /api/health kept answering 200 so the watchdog saw a healthy worker."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    token_path().write_bytes(b"\xff\xfea\x00b\x00c\x00")
    assert read_token() is None
    with TestClient(_app(), raise_server_exceptions=False) as c:
        assert c.get("/api/runs").status_code == 401
        assert c.get("/api/health").status_code == 200


def test_an_empty_leftover_file_is_cleared_rather_than_bricking_the_machine(tmp_path, monkeypatch):
    """⛔⛔ A crash or a full disk between the exclusive create and the write
    leaves a zero-byte token file. Every later boot lost the create race to it
    and refused everything — while /api/health answered 200, so nothing
    reported a problem and no human had a reason to suspect the file."""
    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", tmp_path)
    token_path().write_text("", encoding="utf-8")
    minted = ensure_token()
    assert minted and len(minted) >= 32
    assert read_token() == minted


def test_the_refusal_does_not_hand_out_the_home_directory(client):
    """⛔ `token_path()` is `~/.super-research/...` EXPANDED — it carries the OS
    username. A page doing DNS rebinding onto 127.0.0.1 reads this body. The
    refusal is correct; telling it whose machine this is was not."""
    detail = client.get("/api/runs").json()["detail"]
    from pathlib import Path
    assert serve_token.TOKEN_FILENAME in detail
    assert str(Path.home()) not in detail
    assert str(token_path()) not in detail


def test_the_comparison_is_constant_time():
    """⛔ `==` on a secret leaks its prefix to anything that can time a request,
    and a local caller can time a local request very well. Behaviour cannot
    tell the two apart, so this reads the implementation — the one place in
    this file where that is the honest instrument."""
    # The docstring survives `code_only` (it blanks `#` comments only) and
    # this one quotes the `==` it is warning about, so read past it.
    impl = code_only(serve_token.token_ok).rsplit('"""', 1)[-1]
    assert "compare_digest" in impl
    assert "==" not in impl


# ── the wiring in research.py ────────────────────────────────────────────────
# ⛔ SOURCE-PINNED ON PURPOSE. `run_server` is a 2,000-line async closure that
# opens a browser, a Firestore client and six background loops; it cannot be
# called from a test. The gate's BEHAVIOUR is executed above — what these check
# is that `run_server` reaches for it, and in the right order.

def test_run_server_installs_the_gate():
    assert "app.add_middleware(ServeTokenMiddleware)" in RUN_SERVER


def test_the_gate_is_added_before_cors_so_cors_ends_up_outside():
    """⛔⛔ See `test_a_browser_preflight_is_answered_by_cors_not_by_the_gate`
    for what a swap costs. This is the same fact at the call site, where the
    swap would actually be made."""
    gate = RUN_SERVER.index("app.add_middleware(ServeTokenMiddleware)")
    cors = RUN_SERVER.index("CORSMiddleware,")
    assert gate < cors, "CORS is inside the gate — the preflight will be refused"


def test_the_token_exists_before_the_first_request_can_arrive():
    """⛔ ORDER, NOT PRESENCE. A plausible "mint lazily" change moves this into
    a request handler; N workers then boot with no token file, the first call
    401s, and every worker races to mint on its first request. The old version
    of this test — `"ensure_token()" in RUN_SERVER` — passed for all of that."""
    mint = RUN_SERVER.index("ensure_token()")
    gate = RUN_SERVER.index("app.add_middleware(ServeTokenMiddleware)")
    serve = RUN_SERVER.index("uvicorn.Config(app, host=")
    assert mint < gate < serve


def test_nothing_ever_captures_the_token_value_for_printing():
    """⭐ THE BANNER AND --help NAME THE FILE, NEVER THE VALUE. Terminal
    scrollback gets pasted into chats; a path is safe there and a live
    credential is not. Nothing in the file binds `ensure_token()`'s return, so
    there is no name a future print statement could reach for."""
    # ⛔⛔ THE FIRST VERSION OF THIS COULD NOT FAIL. It only rejected
    # `x = ensure_token()`, so `log(f"token: {ensure_token()}")` — the exact
    # shape that leaks — sailed through it. The honest pin is that the call
    # appears ONCE, on a line of its own, and that no f-string anywhere
    # interpolates it or `read_token`.
    calls = re.findall(r"ensure_token\(\)", SRC)
    assert len(calls) == 1, f"ensure_token() is called {len(calls)}x — only the boot mint may call it"
    assert re.search(r"\n\s*ensure_token\(\)\n", SRC), "the one call is not a bare statement"
    assert not re.search(r"\{[^}]*(?:ensure_token|read_token)\([^}]*\}", SRC), \
        "a token value is interpolated into a string"
    assert "read_token" not in SRC


def test_the_run_route_takes_the_uid_from_the_pairing_not_the_caller():
    """⛔⛔ THE ONE LINE THIS WAVE EXISTS FOR. `uid = request_data.get("uid", "")`
    let whoever could reach the port choose the Firebase account a run was
    written to and billed to."""
    assert 'uid = load_paired_uid() or ""' in RUN_SERVER
    assert 'uid = request_data.get("uid", "")' not in RUN_SERVER


def test_a_uid_the_caller_names_is_refused_rather_than_quietly_rewritten():
    """⛔⛔ AND IT IS REFUSED, NOT IGNORED. A caller naming a uid is saying
    where it believes the run is going. Running it somewhere else and
    reporting success moves somebody's work without telling anyone — the
    failure mode that is worse than the bug."""
    # ⛔⛔ THE ANCHOR IS CHECKED FOR UNIQUENESS, AND IT WAS NOT UNIQUE. Two
    # other lines in `run_server` end with the same characters —
    # `_rb_uid = load_paired_uid() or ""` and
    # `_paired_uid_for_cmds = load_paired_uid() or ""` — so the bare substring
    # matched three times and `.index()` landed on the right one only because
    # it happens to come first. Cross-verify called this out; the uniqueness
    # assertion is what turns the warning into something that stays true.
    ANCHOR = '\n        uid = load_paired_uid() or ""\n'
    assert RUN_SERVER.count(ANCHOR) == 1, "the uid anchor is ambiguous again"
    window = RUN_SERVER[RUN_SERVER.index(ANCHOR):]
    # ⛔ AND IT RUNS THROUGH THE ENQUEUE, not just to the next local. The bug
    # this pins can be reintroduced at the `_job_queue.put` — `"uid":
    # request_data.get("uid", uid)` — which is BELOW `config = ...` and so was
    # outside the window the first version of this test looked at.
    window = window[:window.index("position = _job_queue.qsize()")]
    # ⛔ THE COMPARISON ITSELF, NOT THE NAME. `if False:` keeps every symbol a
    # looser assertion looks for while turning the refusal off entirely.
    assert "if _claimed and _claimed != uid:" in window
    assert "403)" in window, "the mismatch does not end in a refusal"
    # `str(...)` because the body is arbitrary JSON: a dict here would make
    # `.strip()` raise and turn a 403 into a 500.
    assert 'str(request_data.get("uid") or "").strip()' in window
    # ⛔ WHAT ACTUALLY GETS ENQUEUED. Everything above is undone if the payload
    # re-reads the body.
    put = window[window.index("_job_queue.put("):]
    assert '"uid": uid' in put, "the enqueued payload does not carry the pairing's uid"
    assert "request_data" not in put.split(")")[0] + ")", \
        "the enqueued payload reads the request body again"
    # ⭐ AND NO `research_id`. This is the pin that makes the cross-verify's
    # loudest worry impossible by construction: a run started here can never
    # create a research document in the owner's Firestore tree, because every
    # writer is gated on a research_id this route does not supply —
    # `_flip_queued_to_ongoing` says so in its own docstring.
    assert "research_id" not in put.split(")")[0]


def test_the_bind_comment_no_longer_describes_a_posture_the_code_dropped():
    """⛔ It said "uvicorn still binds to 0.0.0.0 below so the FE web app can
    reach this BE" — untrue on both halves since 2026-09-05, and a comment
    describing the old posture is how a future edit talks itself back into it."""
    assert "uvicorn still binds" not in SRC
    assert 'host="127.0.0.1", port=port' in SRC


# ── the reference surface ────────────────────────────────────────────────────

def test_help_advertises_no_route_that_was_deleted():
    """⛔⛔ `--help` advertised `GET /api/runs/{id}/events` and `WS /ws/{run_id}`
    for FIVE MONTHS after both were deleted on 2026-04-29. The only test on the
    table asked whether each row reached the rendered output — a question about
    the renderer. This one asks the server."""
    # ⛔⛔ METHOD **AND** SHAPE. Comparing paths alone lets `DELETE
    # /api/runs/{id}` hide behind `GET /api/runs/{id}` — they share a shape —
    # so a whole row could be added or removed and nothing would notice. The
    # mutation harness found this by surviving R10.
    declared = _route_keys()
    for row, _desc in research._LOCAL_API_ROUTES:
        assert _row_key(row) in declared, f"--help advertises {row!r}, which no route serves"


def test_help_advertises_every_route_that_does_exist():
    """⛔⛔ THE OTHER DIRECTION, AND IT IS THE ONE THAT WAS MISSING. Checking
    only that listed rows exist lets a route be added, silently gated by the
    middleware, and never described anywhere a user looks. DELETE
    /api/runs/{id} — the one route that destroys data — was exactly that."""
    listed = {_row_key(row) for row, _d in research._LOCAL_API_ROUTES}
    missing = sorted(_route_keys() - listed)
    assert not missing, f"routes the machine serves but --help never mentions: {missing}"


def test_help_says_how_to_authenticate(capsys):
    """A reference whose every row answers 401 is not a reference."""
    research.run_commands_help()
    out = capsys.readouterr().out
    assert HEADER in out
    assert str(token_path()) in out


def test_help_still_lists_the_routes_that_do_exist(capsys):
    research.run_commands_help()
    out = capsys.readouterr().out
    for row, desc in research._LOCAL_API_ROUTES:
        assert row in out
        assert desc in out


def test_the_serve_banner_names_the_token_file():
    """The person who just typed `--serve` is the one who needs to find it."""
    strip = RUN_SERVER[RUN_SERVER.index("_srv_token_path"):]
    strip = strip[:strip.index("_render_context_strip")]
    assert '("API token", _c(_DIM, str(_srv_token_path())))' in strip
    assert "*_token_row," in strip, "the row is built but never put in the strip"
