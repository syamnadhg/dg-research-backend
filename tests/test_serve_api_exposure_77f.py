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

⚠ AND IT WAS NOT AUTHENTICATION. A process or a page on THIS machine still
reached it unauthenticated. What that wave removed was the network, and the
tests below said so explicitly so nobody would read it as having solved the
larger problem.

✅ 2026-09-20, WAVE 10.5 — THE LARGER PROBLEM IS NOW SOLVED, and this file was
written to be inverted on the day it was. Its own instruction was: "If one of
them GAINS an auth check, this list should shrink and whoever shrinks it should
say so." The list did not shrink; it went to ZERO, because the gate is one ASGI
middleware under every route rather than a check per handler. The honest half
below is therefore replaced by its opposite, and the behaviour of the gate is
executed — not read — in `tests/test_serve_api_token_105.py`.

⭐ WHAT STAYS HERE: the loopback bind, the non-wildcard CORS, and the evidence
those rest on. Authentication does not retire either one — the bind is what
keeps the LAN out of a race with the gate, and the two together are the reason
neither has to be perfect alone.

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
    #
    # ⛔⛔ AND A FIFTH TIME, 2026-09-20: this anchored on `app.add_middleware(`
    # and silently assumed CORS was the FIRST one. Wave 10.5 added the token
    # gate above it, so the window slid up to include the explanatory comment —
    # which quotes `allow_origins=["*"]` to say what was removed — and this test
    # failed on the sentence documenting the fix, exactly as the note above
    # predicted for a different anchor. The anchor is now the CORS call itself.
    at = src.index("app.add_middleware(\n        CORSMiddleware,")
    window = src[at:src.index(")", src.index("allow_headers", at))]
    assert "localhost:{port}" in window
    assert "127.0.0.1:{port}" in window
    # ⛔ AND THE WILDCARD IS CHECKED IN THE CALL, NOT THE FILE — the comment above
    # the call quotes the old form to explain what was removed, so a file-wide
    # `not in` fails on the very sentence that documents the fix.
    assert '["*"]' not in window.split("allow_origins")[1].split("]")[0] + "]"
    assert 'allow_origins=["*"]' not in window


def test_the_endpoints_this_protects_now_have_a_caller_check_too():
    """✅ THE HONEST HALF, INVERTED ON THE DAY IT WAS EARNED — wave 10.5.

    The old version of this test asserted that these four routes asked NOBODY
    who was calling, and said in its own words that whoever changed that should
    say so. Here is the saying-so.

    Binding to loopback narrowed WHO could reach these routes. It is still the
    outer wall and it still matters: if somebody re-exposes the port — a
    tunnel, a container port map, a `--host` flag — the gate is now what is
    standing there, instead of nothing. The two are layers, not alternatives.
    """
    src = _src()
    # Still here, still the routes that read or drive somebody's research — and
    # now every one of them sits under a single ASGI gate rather than under a
    # per-handler check that a fifteenth route could forget.
    for route in ('@app.get("/api/runs")',
                  '@app.post("/api/runs")',
                  '@app.get("/api/runs/{run_id}/documents/{doc_type}")',
                  '@app.get("/api/runs/{run_id}/audio/{filename}")'):
        assert route in src, route
    assert "app.add_middleware(ServeTokenMiddleware)" in src, (
        "the gate is gone — every route below it is open again")
    # ⛔⛔ AND THE LINE THAT MADE THE POINT IN THE FIRST PLACE IS GONE. `POST
    # /api/runs` took the billing identity FROM THE REQUEST BODY; it now takes
    # it from the pairing, which a caller cannot forge.
    assert 'uid = request_data.get("uid", "")' not in src
    assert 'uid = load_paired_uid() or ""' in src


def test_the_gate_is_not_quietly_reduced_to_the_bind_again():
    """⛔ The failure this file was written about was a whole wave believing
    the bind WAS the fix. Both layers, named separately, so removing either one
    is a visible act."""
    src = _src()
    assert 'host="127.0.0.1", port=port' in src          # the outer wall
    assert "app.add_middleware(ServeTokenMiddleware)" in src  # the caller check
    assert "from auth.serve_token import" in src


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
