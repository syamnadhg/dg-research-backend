"""The local sign-in page's Google window opens on superresearch.io.

The web app moved its Firebase `authDomain` to superresearch.io, so Google's
account picker names that site. The agent's own page (`agent login --local`)
still handed the SDK the project's firebaseapp.com host, and `test_config.py`
only checked that the value was non-empty, so nothing could see it.

⛔ AND THE MOVE HAS A COST THAT HAS TO BE SAID OUT LOUD. The window is now served
by the web app itself (it proxies /__/auth/ to the Firebase helper), so --local
is no longer a way round a superresearch.io outage. Every line that offers
--local says so, and so does --local itself. Nothing else does: a timeout or an
expired link is not a reason to reach for the fallback, so it gets no caveat.

⛔ EVERY DEFAULT PIN RELOADS `config` WITH THE VARIABLE REMOVED. The module reads
the environment once, at import. Asserting on the already-imported value would
pass for whatever the developer running the suite happened to export, and a
monkeypatched attribute would pass against the old default too. Reloaded with the
variable gone, only the default in the source can answer.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, cli, config

_ENV = "SUPER_AGENT_AUTH_DOMAIN"
_NEW = "superresearch.io"
_OLD = "super-research-492814.firebaseapp.com"


@contextlib.contextmanager
def _config_with(monkeypatch, tmp_path, value):
    """`config` re-executed with the variable set to ``value`` (None = removed),
    and put back exactly as the rest of the suite expects it afterwards.

    ⛔ A RELOAD RE-RUNS EVERY MODULE-LEVEL ASSIGNMENT, including the two that
    conftest patched on this module for every test: `store_dir` (so prefs never
    touch the real ~/.super-agent) and `FE_BASE` (so nothing reaches the real web
    app). Both are re-applied straight after the reload, or this test would run
    with the suite's isolation silently switched off.

    ⛔ THE VARIABLE IS RESTORED BEFORE THE SECOND RELOAD, by hand. `monkeypatch`
    would restore it only at teardown — after the reload in the finally — which
    leaves the module holding the default while the variable says otherwise."""
    saved = os.environ.pop(_ENV, None)
    if value is not None:
        os.environ[_ENV] = value
    try:
        fresh = importlib.reload(config)
        monkeypatch.setattr(config, "store_dir", lambda: tmp_path)
        monkeypatch.setattr(config, "FE_BASE", "http://127.0.0.1:9")
        yield fresh
    finally:
        os.environ.pop(_ENV, None)
        if saved is not None:
            os.environ[_ENV] = saved
        importlib.reload(config)
        monkeypatch.setattr(config, "store_dir", lambda: tmp_path)
        monkeypatch.setattr(config, "FE_BASE", "http://127.0.0.1:9")


# ── the value ─────────────────────────────────────────────────────────────────

def test_the_default_sign_in_host_is_superresearch_io(monkeypatch, tmp_path):
    with _config_with(monkeypatch, tmp_path, None) as fresh:
        assert fresh.AUTH_DOMAIN == _NEW
        assert fresh.web_config()["authDomain"] == _NEW


def test_the_override_still_wins(monkeypatch, tmp_path):
    # Accept polarity: the staging knob is the one way to point a foreground
    # `agent serve` somewhere else, and a default that ignored it would pass the
    # pin above.
    with _config_with(monkeypatch, tmp_path, "auth.staging.example.test") as fresh:
        assert fresh.web_config()["authDomain"] == "auth.staging.example.test"


def test_the_bridge_serves_the_new_host_to_the_page(monkeypatch, tmp_path):
    """The consumer: `login.html` calls `initializeApp` on exactly what
    GET /login/config returns, so the served JSON is the value that decides which
    host the popup opens on."""
    with _config_with(monkeypatch, tmp_path, None):
        state = bridge.BridgeState()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            cfg = requests.get(base + "/login/config", timeout=5).json()
        finally:
            httpd.shutdown()
            httpd.server_close()
    assert cfg["authDomain"] == _NEW
    assert _OLD not in cfg.values()


# ── the lines that offer --local ──────────────────────────────────────────────

def _cap(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rv = fn(*a, **k)
    return rv, buf.getvalue()


def _caveat_after_offer(out: str, host: str) -> bool:
    """The host is named on a line AFTER the one offering --local — the caveat
    belongs to that offer, not floating somewhere else in the output."""
    lines = out.splitlines()
    offers = [i for i, ln in enumerate(lines) if "agent login --local" in ln]
    return bool(offers) and any(host in ln and "must be up" in ln
                                for ln in lines[offers[0] + 1:])


@pytest.fixture()
def _host(monkeypatch):
    # A value no source default spells, so the line can only have come from
    # reading `config.AUTH_DOMAIN` at the moment it is printed.
    monkeypatch.setattr(config, "AUTH_DOMAIN", "auth.example.test")
    return "auth.example.test"


def test_login_says_what_the_fallback_needs_when_the_web_start_fails(monkeypatch, _host):
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: "start-failed")
    rc, out = _cap(cli._login_remote, SimpleNamespace(runtime="", label=""))
    assert rc == 1
    assert _caveat_after_offer(out, _host), out


@pytest.mark.parametrize("state", ["expired", "timeout", "error", "cancelled"])
def test_login_does_not_add_the_caveat_where_it_offers_no_fallback(monkeypatch, _host, state):
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: state)
    rc, out = _cap(cli._login_remote, SimpleNamespace(runtime="", label=""))
    assert rc == 1
    assert _host not in out and "--local" not in out, out


def test_connect_step_says_what_the_fallback_needs_when_the_web_start_fails(monkeypatch, _host):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: "start-failed")
    rv, out = _cap(cli._signin_step, assume_yes=True)
    assert rv is False
    assert _caveat_after_offer(out, _host), out


@pytest.mark.parametrize("state", ["expired", "timeout", "error", "cancelled"])
def test_connect_step_does_not_add_the_caveat_where_it_offers_no_fallback(monkeypatch, _host, state):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: state)
    rv, out = _cap(cli._signin_step, assume_yes=True)
    assert rv is False
    assert _host not in out and "--local" not in out, out


def test_login_local_names_the_host_its_window_opens_on(monkeypatch, _host):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "")
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    rc, out = _cap(cli.cmd_login, SimpleNamespace(local=True))
    assert rc == 0
    assert opened == [config.login_origin() + "/login"]
    assert any(_host in ln and "must be up" in ln for ln in out.splitlines()), out


def test_the_caveat_names_the_real_default_host(monkeypatch, tmp_path):
    # End to end on the shipped value, not the stand-in: with no override, the
    # line a person reads names superresearch.io.
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: "start-failed")
    with _config_with(monkeypatch, tmp_path, None):
        _, out = _cap(cli._login_remote, SimpleNamespace(runtime="", label=""))
    assert _caveat_after_offer(out, _NEW), out
    assert _OLD not in out
