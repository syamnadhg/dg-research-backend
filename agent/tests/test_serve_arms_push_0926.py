"""`serve()` arms instant delivery and starts the news peek — and nothing else does (2026-09-26).

⛔⛔ THE TWO SWITCHES NO TEST EVER FLIPPED. `push.arm()` and the "agent-news-peek"
thread are started from `serve()` and only from `serve()`, on purpose: a handler-level
test must never reach a real `hermes` on the machine running the suite. The price of
that rule was that no test ran `serve()` at all — so deleting either line left the
whole suite green while a real bridge quietly went back to the 2026-09-24 behaviour:
every "✓ Signed in", every 🎉 and every owner's yes waiting for the watcher's own
~2-minute tick and then Hermes's once-a-minute queue.

⭐ These tests run the REAL `serve()` with the one thing it cannot be given in a test
swapped out: the HTTP server. The stub binds nothing, and its `serve_forever` is where
each test looks at the bridge while it is up. `push`'s spawner (and, for the peek, the
peek's own body) are recorders, so nothing here runs a watcher, reads Firestore or
talks to a network.
"""

import threading

from facade import bridge, push

TG = {"platform": "telegram", "chat_id": "111"}

# ⛔ A DEADLINE, NOT A SLEEP: every wait below returns the moment its condition holds.
_DEADLINE_S = 10.0


def _run_serve(monkeypatch, port, during):
    """Run the real `bridge.serve()` against a stub server; `during()` runs in place of
    `serve_forever`, i.e. while the bridge is up. Returns what it saw.

    ⛔ AND THE BRIDGE MUST STOP CLEANLY: every `agent-*` thread `serve()` started is
    joined under a deadline once it returns, so no test leaves a daemon ticking."""
    seen: dict = {"servers": []}
    before = set(threading.enumerate())

    class _Server:
        def __init__(self, addr, handler):
            self.addr, self.handler, self.shut_down = addr, handler, False
            seen["servers"].append(self)

        def serve_forever(self):
            seen["threads"] = [t for t in threading.enumerate()
                               if t not in before and t.name.startswith("agent-")]
            try:
                seen["during"] = during()
            except BaseException as e:  # noqa: BLE001 — re-raised after serve() cleans up
                seen["error"] = e

        def shutdown(self):
            self.shut_down = True

    monkeypatch.setattr(bridge, "ThreadingHTTPServer", _Server)
    bridge.serve("127.0.0.1", port)
    if "error" in seen:
        raise seen["error"]
    assert [s.addr for s in seen["servers"]] == [("127.0.0.1", port)]
    assert seen["servers"][0].shut_down, "serve() returned without shutting its server down"
    for t in seen.get("threads", []):
        t.join(_DEADLINE_S)
    assert [t.name for t in seen.get("threads", []) if t.is_alive()] == [], \
        "a thread serve() started outlived it"
    return seen


def test_serve_arms_instant_delivery_for_as_long_as_it_runs(monkeypatch, _nobody_listens_port):
    """⛔⛔ THE CHAT HEARS ITS NEWS MINUTES LATE AGAIN IF `serve()` DOES NOT ARM THE
    PUSH. `push.arm()` in `serve()` is the only thing that turns instant delivery on;
    until it runs, every push request is a silent no-op ("not armed (no serve())"), so
    a sign-in, a finished run or an owner's yes waits for the watcher's own tick and
    then Hermes's queue — the late "✓ Signed in" of 2026-09-24. While the real
    `serve()` is up, a push asked for must be handed to a background run; once it
    returns, instant delivery is off again.

    Would this pass against the mutant? No: with `push.arm()` deleted from `serve()`
    the request made while the bridge is up returns False and dispatches nothing —
    PUSHER is forced off before `serve()` starts, and nothing else in the process arms
    it."""
    monkeypatch.setattr(push.PUSHER, "armed", False)
    dispatched: list = []
    monkeypatch.setattr(push.PUSHER, "_spawn",
                        lambda target, *args: dispatched.append((target, args)))

    def during():
        return {"armed": push.PUSHER.armed,
                "handed_off": push.request(TG, reason="signed-in", still_valid=lambda: True)}

    seen = _run_serve(monkeypatch, _nobody_listens_port, during)

    assert seen["during"]["armed"] is True, "serve() is up but instant delivery is off"
    assert seen["during"]["handed_off"] is True, \
        "a sign-in's push was dropped as 'not armed' while serve() was running"
    assert len(dispatched) == 1
    target, args = dispatched[0]
    assert target == push.PUSHER._fan_out and args[:2] == (TG, "signed-in")
    # …and it is serve()'s to switch off: after it returns, a push is a no-op again.
    assert push.PUSHER.armed is False
    assert push.request(TG, reason="after-serve") is False
    assert len(dispatched) == 1


def test_serve_starts_the_news_peek_and_stops_it_on_the_way_out(monkeypatch,
                                                                _nobody_listens_port):
    """⛔⛔ NEWS NOBODY ASKED FOR IS NEVER PUSHED IF THE PEEK NEVER STARTS. The
    "agent-news-peek" thread, started only by `serve()`, is what notices a run that
    finished or now needs the person, an owner's answer to a device ask and support's
    answer on a log bundle — and hands each to the push. Without it none of those is
    pushed: each waits for the watcher's own tick and Hermes's queue, minutes late.
    With a fast tick and a recording peek, the real `serve()` must run the peek on a
    daemon thread named "agent-news-peek" over its OWN bridge state while it is up,
    and that thread must be gone once it returns.

    Would this pass against the mutant? No: with `np_thread.start()` deleted from
    `serve()` no thread ever runs `_news_peek_loop`, so the recording peek — which has
    no other caller — is not called before the deadline."""
    monkeypatch.setattr(bridge, "_PEEK_TICK_SECONDS", 0.01)
    built: list = []
    real_state = bridge.BridgeState

    def _state(*a, **kw):
        s = real_state(*a, **kw)
        built.append(s)
        return s

    monkeypatch.setattr(bridge, "BridgeState", _state)
    ticked = threading.Event()
    calls: list = []

    def _peek(state, memo):
        calls.append((threading.current_thread(), state))
        ticked.set()

    monkeypatch.setattr(bridge, "_peek_once", _peek)

    seen = _run_serve(monkeypatch, _nobody_listens_port, lambda: ticked.wait(_DEADLINE_S))

    assert seen["during"] is True, "no news peek ran while serve() was up"
    thread, state = calls[0]
    assert thread.name == "agent-news-peek" and thread.daemon
    assert len(built) == 1 and state is built[0], "the peek did not read serve()'s own state"
    # Stopped cleanly: `_run_serve` joined every thread serve() started; this one too.
    assert thread in seen["threads"] and not thread.is_alive()
