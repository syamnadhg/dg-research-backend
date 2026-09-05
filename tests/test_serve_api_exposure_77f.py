"""The local API stops being reachable from the network.

⛔⛔ WHAT IT WAS. `--serve` runs an HTTP API on the machine with NO authentication
of any kind, and it bound `0.0.0.0` — every interface — with `allow_origins=["*"]`.
So anything on the same network could:

  GET  /api/runs                          every run's meta, for EVERY account
                                          that shares the machine — topics included
  GET  /api/runs/{id}/documents/{type}    the brief, the agent markdown, the report
  GET  /api/runs/{id}/audio/{name}        the podcast
  POST /api/runs                          start a run, taking `uid` FROM THE BODY
  POST /api/runs/{id}/stop|pause|resume   stop or steer somebody else's research

A coffee-shop wifi, an office LAN, a shared house. And the wildcard origin meant
any page in any tab could do the same from the browser.

⭐ THE FIX IS ONE LINE BECAUSE NOTHING EVER USED THE NETWORK. Measured before it
was made: the web app contains zero references to this API (it reaches the machine
through Firestore); the health probe asks `http://localhost:{port}`; the `--serve`
banner advertises `http://localhost:{port}`. The bind address was the only thing
claiming a remote consumer existed.

⚠ AND IT IS NOT AUTHENTICATION. A process or a page on THIS machine still reaches
it unauthenticated. What this removes is the network. The tests below say so
explicitly, so nobody reads the wave as having solved the larger problem.

Run:  pytest tests/test_serve_api_exposure_77f.py -v
"""
import os
import re


def _src() -> str:
    return open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research.py"), encoding="utf-8").read()


def test_the_api_binds_loopback_only():
    src = _src()
    assert 'host="127.0.0.1", port=port' in src
    # ⛔ AND `0.0.0.0` APPEARS NOWHERE AS A BIND. It survives in a docstring that
    # quotes uvicorn's own banner, which is why this checks the bind form rather
    # than the string.
    assert 'host="0.0.0.0"' not in src
    assert "uvicorn.Config(app, host=" in src


def test_cors_is_not_a_wildcard():
    src = _src()
    # ⛔ ANCHORED ON THE CALL, NOT THE NAME — `src.index("CORSMiddleware")` finds
    # the IMPORT, hundreds of lines above, and the window then contains none of
    # the configuration. Fourth time that has bitten this codebase in one wave.
    at = src.index("app.add_middleware(")
    window = src[at:src.index(")", src.index("allow_headers", at))]
    assert "localhost:{port}" in window
    assert "127.0.0.1:{port}" in window
    # ⛔ AND THE WILDCARD IS CHECKED IN THE CALL, NOT THE FILE — the comment above
    # the call quotes the old form to explain what was removed, so a file-wide
    # `not in` fails on the very sentence that documents the fix.
    assert '["*"]' not in window.split("allow_origins")[1].split("]")[0] + "]"
    assert 'allow_origins=["*"]' not in window


def test_the_endpoints_this_protects_still_have_no_auth_of_their_own():
    """⛔⛔ THE HONEST HALF, AND IT IS A TEST SO IT CANNOT BE FORGOTTEN.

    Binding to loopback narrows WHO can reach these routes; it does not add a
    caller check to any of them. If somebody later re-exposes the port — a
    tunnel, a container port map, a `--host` flag — every one of these is open
    again. This test exists to make that explicit rather than to pass.
    """
    src = _src()
    # The routes that read or drive somebody's research, none of which asks who
    # is calling. If one of them GAINS an auth check, this list should shrink and
    # whoever shrinks it should say so.
    for route in ('@app.get("/api/runs")',
                  '@app.post("/api/runs")',
                  '@app.get("/api/runs/{run_id}/documents/{doc_type}")',
                  '@app.get("/api/runs/{run_id}/audio/{filename}")'):
        assert route in src, route
    # `POST /api/runs` still takes the uid from the body — the single clearest
    # statement that this is exposure reduction and not authentication.
    assert 'uid = request_data.get("uid", "")' in src


def test_the_health_probe_and_the_banner_agree_with_the_bind():
    """⭐ THE EVIDENCE THE FIX RESTS ON, PINNED. The claim that loopback breaks
    nothing is only as good as "everything already used loopback". If a future
    edit points the probe or the banner at a routable address, the claim stops
    being true and this goes red."""
    src = _src()
    assert 'f"http://localhost:{port}/api/health"' in src
    assert 'f"http://localhost:{port}"' in src
    # No caller anywhere asks for a LAN address.
    assert not re.search(r'http://0\.0\.0\.0:\{?port', src)
