"""`agent device remove` and `agent device add` — the SCREEN, not the helpers.

⛔⛔ WHY THIS FILE EXISTS: FOUR MUTANTS SURVIVED 7.9-5's FIRST HARNESS RUN AND
ALL FOUR WERE THE SAME GAP. `test_unlink_copy_795.py` pins `cli._unlink_refusal`
and `cli._pair_refusal` as FUNCTIONS, and pins their tables against the routes'
codes — and nothing anywhere drove the COMMANDS. So a mutant could delete the
whole pair-code print block from `agent device remove` (back to "Removed device
dev-a1." and stop, which is what the terminal did for four waves), or put
`_err(res)` back so the web app's raw identifier reached the screen again, and
every test stayed green.

⭐⭐ IT IS THE LESSON THIS PROJECT HAS ALREADY WRITTEN DOWN TWICE: extracting a
helper does not test it — pin the CONSUMER. A table that matches its route
proves the table; only the command proves the screen.

⛔ AND THE MUTANTS THAT SURVIVED WERE ALL ON THE TERMINAL, none on the chat
client, because the chat client had an end-to-end file (`test_sr_client.py`) and
this surface had command-body tests that stopped at the device verbs. The
asymmetry was the whole of it.
"""

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from facade import bridge, cli


class FakeFS:
    devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]

    def __init__(self, _tp):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]


@pytest.fixture()
def live(monkeypatch):
    """A real bridge on loopback, with `cli` pointed at it — so these tests drive
    the same two hops a person does: `agent …` → HTTP → bridge → (faked) web app."""
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device",
                        lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device",
                        lambda: sel.__setitem__("v", None))
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(cli.config, "bridge_origin", lambda: base)
    # `cmd_device` refuses before dispatch when the bridge is down or when a WSL
    # runtime is detected; neither is what these tests are about.
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _hint: None)
    monkeypatch.setattr(cli.connect, "detect_targets", lambda *a, **k: [])
    try:
        yield sel
    finally:
        httpd.shutdown()
        httpd.server_close()


def _fe(monkeypatch, reply, status=200):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda sess, path, payload, **kw: (status, reply))


def _remove(deviceId="dev-a"):
    return cli.cmd_device(SimpleNamespace(device_command="remove", deviceId=deviceId,
                                          runtime=None, dest=None, verbose=False))


def _add(code="K7XQ9B2M"):
    return cli.cmd_device(SimpleNamespace(device_command="add", code=code,
                                          runtime=None, dest=None, verbose=False))


# ── the rotated code reaches the screen ───────────────────────────────────────

def test_unlink_prints_the_new_code_and_calls_it_a_credential(live, monkeypatch, capsys):
    """⛔⛔ THE SURVIVOR THIS KILLS (U9). The whole block was deletable with the
    suite staying green — and the terminal had printed nothing about the code for
    four waves, which is the state the deletion restores."""
    _fe(monkeypatch, {"ok": True, "action": "owner-unlinked",
                      "pairCode": "K7XQ-9B2M", "deviceName": "My PC"})
    assert _remove() == 0
    out = capsys.readouterr().out
    assert "Unlinked My PC" in out
    assert "New access code: K7XQ-9B2M" in out
    assert "no longer works" in out
    assert "claim this computer as its owner" in out
    assert "password" in out


def test_unlink_fallback_is_honest_when_no_code_came_back(live, monkeypatch, capsys):
    """⛔⛔ THIS USED TO PIN A FALSE SENTENCE. It asserted the screen said "the new
    one is on the device's own screen", and the route says in its own comment that
    the machine cannot show a rotated code. Somebody following it read a dead code
    off a machine. What is true is that the code is gone and the machine has to be
    paired again — which joins it as a NEW computer."""
    _fe(monkeypatch, {"ok": True, "action": "owner-unlinked", "deviceName": "My PC"})
    assert _remove() == 0
    out = capsys.readouterr().out
    assert "access code changed" in out
    assert "device's own screen" not in out
    assert "cannot be looked up anywhere" in out
    assert "superresearch --pair" in out and "new computer" in out
    assert "New access code:" not in out


def test_unlink_prints_no_code_for_a_sharer(live, monkeypatch, capsys):
    """A sharer walking away is not handed the key to the machine they left, and
    is not told about a rotation on a computer that is no longer theirs.

    ⛔⛔ RE-POINTED IN WAVE 9, AND IT WOULD HAVE GONE ON PASSING FOREVER. This
    asserted `"pair code" not in out.lower()` — a NEGATIVE test on the exact
    words the wave renamed. The rename satisfied it trivially: the screen could
    have started printing "New access code: …" to every sharer and this would
    still have been green, because the string it forbids no longer exists
    anywhere in the program. A negative pin on retired wording is a decoration.
    ⭐ SO IT NOW FORBIDS BOTH SPELLINGS, and the old one stays listed precisely
    so a half-revert cannot sneak the leak back either."""
    _fe(monkeypatch, {"ok": True, "action": "left-shared", "deviceName": "Boss PC"})
    assert _remove() == 0
    out = capsys.readouterr().out
    assert "Left the shared device Boss PC" in out
    assert "access code" not in out.lower()
    assert "pair code" not in out.lower()
    assert "K7XQ" not in out


# ── refusals are worded, not relayed ──────────────────────────────────────────

def test_unlink_refusal_is_worded_on_screen(live, monkeypatch, capsys):
    """⛔⛔ THE SURVIVOR THIS KILLS (T4). `rotation_failed` is the one refusal in
    the product that exists to protect the reader, and it reached the terminal as
    that identifier."""
    _fe(monkeypatch, {"error": "rotation_failed"}, status=500)
    assert _remove() == 1
    out = capsys.readouterr().out
    assert "rotation_failed" not in out
    assert "access code would not change" in out
    assert "still linked to this account" in out
    assert "nothing was changed" not in out.lower()


def test_pair_refusal_is_worded_on_screen(live, monkeypatch, capsys):
    """⛔ THE SURVIVOR THIS KILLS (T5). `pair_bootstrap_failed` is RECOVERABLE by
    running the same command again, and as a bare code it reads like a dead end."""
    _fe(monkeypatch, {"error": "pair_bootstrap_failed"}, status=503)
    assert _add() == 1
    out = capsys.readouterr().out
    assert "pair_bootstrap_failed" not in out
    assert "same command again" in out


# ⛔⛔ TWO ROWS RE-AIMED IN WAVE 8, AND BOTH USED TO PIN THE DEFECT. `code_expired`
# required the sentence to name `superresearch --pair`, which on a computer that
# still exists does not refresh a code — it sets that machine up as a NEW one with
# a new id and everybody it was shared with loses access. `code_not_found` pinned
# "re-check it on the device", which says nothing about the reset-email case that
# actually produces it. A pin that requires the wrong remedy is worse than no pin:
# it holds the defect in place.
@pytest.mark.parametrize("code,fragment", [
    ("code_not_found", "press Reset again"),
    ("code_expired", "press Reset again"),
    ("share_cap_reached", "as many people as it can hold"),
    ("device_secret_missing", "did not finish its side of the handshake"),
])
def test_every_pair_refusal_reaches_the_screen_as_english(live, monkeypatch, capsys,
                                                          code, fragment):
    _fe(monkeypatch, {"error": code}, status=400)
    assert _add() == 1
    out = capsys.readouterr().out
    assert code not in out
    assert fragment in out


def test_rate_limited_reads_the_wait_off_the_reply(live, monkeypatch, capsys):
    """⛔ THE SURVIVOR THIS KILLS (T7). Guessing a window beside a number the
    server already sent is the mistake this file has twice been bitten by — and
    the guard existed for the unlink helper and not for the pair one."""
    _fe(monkeypatch, {"error": "rate_limited", "retryAfterMs": 61_000}, status=429)
    assert _add() == 1
    assert "2 minutes" in capsys.readouterr().out
    _fe(monkeypatch, {"error": "rate_limited", "retryAfterMs": 30_000}, status=429)
    assert _add() == 1
    assert "1 minute" in capsys.readouterr().out


def test_rate_limited_names_no_number_it_was_not_given(live, monkeypatch, capsys):
    import re
    _fe(monkeypatch, {"error": "rate_limited"}, status=429)
    assert _add() == 1
    out = capsys.readouterr().out
    assert not re.search(r"\d+\s*minute", out), "a duration was invented"
    assert "give it a minute" in out


def test_the_two_tables_are_not_swapped_on_screen(live, monkeypatch, capsys):
    """⛔ THE SHAPE OF THE ORIGINAL DEFECT, asked of the screen. An unlink failure
    must never be answered with pairing words, and the reverse: the two routes
    share three generic codes and nothing else."""
    _fe(monkeypatch, {"error": "not_authorized"}, status=403)
    assert _remove() == 1
    unlink_out = capsys.readouterr().out
    assert "isn't linked to this account" in unlink_out
    assert "device's screen" not in unlink_out       # a pairing sentence

    _fe(monkeypatch, {"error": "code_not_found"}, status=404)
    assert _add() == 1
    pair_out = capsys.readouterr().out
    assert "nothing to unlink" not in pair_out       # an unlink sentence
