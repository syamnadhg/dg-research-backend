"""Guards for the repairs 7.9-5's CROSS-VERIFY round demanded.

⛔⛔ WHY THIS FILE EXISTS: ELEVEN MUTANTS SURVIVED THE THIRD HARNESS RUN, AND ALL
ELEVEN WERE THE SAME SHAPE — a fix I made in response to cross-verify and then
did not pin. It is the third wave running with that pattern (7.9-3 recorded 17
undefended repairs; 7.9-5's first run had 12).

⭐⭐ WHAT WAS DIFFERENT THIS TIME: the mutants were derived from the cross-verify
FINDINGS rather than from my repair list (the owner's rule, 09-09), so the gap
was caught BEFORE the push instead of by the next wave's review. That is the
whole point of the rule, and this file is the evidence it works.

Everything here pins a repair whose defect was MEASURED by an outside reader —
not a behaviour I invented a test for.
"""

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, cli

AGENT = Path(__file__).resolve().parents[1]


def _load_sr():
    p = AGENT / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_cvfix_795", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sr = _load_sr()


# ── P6 · the browse relay must prune, not pass the upstream array through ─────

class _FS:
    devices: list = []

    def __init__(self, _tp):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in _FS.devices]


@pytest.fixture()
def live(monkeypatch):
    _FS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    monkeypatch.setattr(bridge, "FirestoreRest", _FS)
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
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_browse_prunes_a_leaky_upstream_row(live, monkeypatch):
    """⛔⛔ MEASURED BY CROSS-VERIFY WITH A STUBBED UPSTREAM: `/devices/public`
    relayed the web app's array BYTE FOR BYTE, so a row carrying a plaintext
    `pairCode` came back whole while every other device route returned nothing.
    The web app's own projection is correct today — that is exactly why this
    matters: the bridge should not be one upstream regression away from
    publishing a credential."""
    leaky = {
        "deviceId": "dev-x", "label": "Someone's Mac", "osFamily": "mac",
        "online": True, "full": False,
        # —— none of this may survive the relay ——
        "pairCode": "SR-PLAINTEXT-CODE", "pollSecretHash": "sha256:beef",
        "syntheticDeviceUid": "synth-x", "ownerUid": "u9",
        "sharedWith": ["u2", "u3"], "people": {"u2": {"joinedAt": 1}},
        "workers": {"1": {"uid": "u2", "runId": "r-2"}},
        "queueOwners": [{"uid": "u3", "runId": "r-3"}],
    }
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, p, params=None, **kw: (200, {"devices": [leaky],
                                                               "truncated": False}))
    r = requests.get(live + "/devices/public")
    body = r.json()
    assert set(body["devices"][0]) == set(bridge._PUBLIC_DEVICE_KEYS)
    for secret in ("SR-PLAINTEXT-CODE", "pollSecretHash", "syntheticDeviceUid",
                   "ownerUid", "sharedWith", "people", "workers", "queueOwners"):
        assert secret not in r.text, f"{secret} survived the browse relay"


def test_browse_uses_the_public_key_set_not_the_own_machine_one(live):
    """⛔ A BROWSE ROW IS A STRANGER'S MACHINE. Reusing `_DEVICE_PUBLIC_KEYS`
    here would widen it by four fields that are about the ASKING account —
    `owned`, `selected`, `visibility` and the hostname ladder."""
    assert set(bridge._PUBLIC_DEVICE_KEYS) == {"deviceId", "label", "osFamily",
                                               "online", "full"}
    # ⛔ `online` IS LEGITIMATELY IN BOTH — a browse row and an own row both
    # carry a power state, and asserting the sets were disjoint was my own
    # overreach. What must hold is that the browse row carries NOTHING about the
    # asking account's relationship to the machine.
    owner_only = {"owned", "selected", "visibility", "hostname", "machineName",
                  "id", "name"}
    assert not (set(bridge._PUBLIC_DEVICE_KEYS) & owner_only), (
        "a stranger's row must say nothing about the asking account")


# ── U8 · --json must carry the warning with the credential ────────────────────

def test_json_output_carries_the_pair_code_warning(capsys):
    """⛔⛔ `--json` PRINTS THE PAYLOAD INSTEAD OF THE RENDERED LINES, so the
    rotated code went out with none of the three sentences saying the old one is
    dead, that this one claims the machine, and to keep it like a password. A
    machine-readable caller is still read by a person."""
    sr._emit({"ok": True, "action": "owner-unlinked", "pairCode": "K7XQ-9B2M"},
             True, ["ignored"])
    out = json.loads(capsys.readouterr().out)
    # ⛔⛔ THE WIRE NAMES, WHICH WAVE 9's RENAME WAS NOT ALLOWED TO TOUCH. A chat
    # runtime reads these two keys; renaming either to match the new prose would
    # break every consumer silently, and a bulk find-and-replace over this file
    # would have done exactly that. They are asserted in the same test as the
    # renamed sentence so neither half can drift without the other going red.
    assert out["pairCode"] == "K7XQ-9B2M"
    assert "pairCodeWarning" in out
    w = out["pairCodeWarning"].lower()
    assert "claim the computer" in w and "only copy" in w
    # …and the SENTENCE inside uses the web app's word.
    assert "new access code" in w, (
        "the value is prose a person reads, and the app calls it an access code"
    )
    assert "pair code" not in w


def test_json_adds_no_warning_when_there_is_no_code(capsys):
    sr._emit({"ok": True, "action": "left-shared"}, True, ["ignored"])
    assert "pairCodeWarning" not in json.loads(capsys.readouterr().out)


# ── U12 · the sharer line must not print a raw device id ──────────────────────

def test_sharer_line_says_no_id_when_the_route_sends_no_name(live, monkeypatch, capsys):
    """⛔ THE ROUTE SENDS NO `deviceName` ON THE SHARER BRANCH — only the owner
    branch carries one — so the terminal printed "Left the shared device
    dev-a1c9f2." An id nobody recognises is worse than a neutral sentence."""
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda s, p, b, **kw: (200, {"ok": True, "action": "left-shared"}))
    monkeypatch.setattr(cli.config, "bridge_origin", lambda: live)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _h: None)
    monkeypatch.setattr(cli.connect, "detect_targets", lambda *a, **k: [])
    rc = cli.cmd_device(SimpleNamespace(device_command="remove", deviceId="dev-a1c9f2",
                                        runtime=None, dest=None, verbose=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dev-a1c9f2" not in out, "the raw device id reached the screen"
    assert "Left that shared device" in out


# ── T2 / T6 · the chat client's refusal helper ────────────────────────────────

def test_chat_refusal_words_a_signed_out_bridge_reply():
    """⛔ THE BRIDGE ANSWERS A SIGNED-OUT CALLER WITH A SENTENCE, not a code, and
    `/login` is the TERMINAL's command. Relaying it hands a chat user something
    that does nothing."""
    said = sr._device_refusal_line("not signed in — run /login",
                                   sr._UNLINK_ERRORS, "remove the device")
    assert "/login" not in said
    assert "tell me to log you in" in said


def test_chat_refusal_words_a_synthesised_http_status():
    """A Firestore outage inside the route's rate limiter (outside its try)
    answers HTML 500, which the bridge synthesises as `http_500`."""
    said = sr._device_refusal_line("http_500", sr._UNLINK_ERRORS, "remove the device")
    assert "http_500" not in said
    assert "HTTP 500" in said


@pytest.mark.parametrize("ms,expect", [(61_000, "2 minutes"), (30_000, "1 minute")])
def test_chat_reads_the_rate_limit_wait_off_the_reply(ms, expect):
    """⛔ BOTH ROUTES SEND `retryAfterMs` AND THE BRIDGE RELAYS IT. The chat
    client read it on four other routes and not on these two, so it invented "a
    few minutes" beside a number it had been handed — while the terminal said
    "about 5 minutes" for the same reply. The two clients disagreed about one
    429."""
    said = sr._device_refusal_line("rate_limited", sr._UNLINK_ERRORS,
                                   "remove the device", ms)
    assert expect in said


def test_chat_invents_no_wait_when_the_reply_gave_none():
    import re
    said = sr._device_refusal_line("rate_limited", sr._UNLINK_ERRORS,
                                   "remove the device", None)
    assert not re.search(r"\d+\s*minute", said)


def test_the_two_clients_agree_on_the_same_429():
    """The disagreement itself, pinned: same reply, same number, both clients."""
    chat = sr._device_refusal_line("rate_limited", sr._UNLINK_ERRORS,
                                   "remove the device", 61_000)
    term = cli._unlink_refusal("rate_limited", 61_000)
    assert "2 minutes" in chat and "2 minutes" in term


# ── T7 / T8 / T9 · sentences that named a cause or remedy that is not true ────

def test_the_code_alphabet_is_stated_correctly():
    """⛔ THE ALPHABET EXCLUDES I, L, O, 0 AND 1 — the five that get confused —
    and "8 letters/digits" told people the opposite, so somebody who typed an O
    for a zero read a rule their input satisfied and retyped the same code."""
    for said in (sr._PAIR_ERRORS["invalid_code_format"],
                 cli._PAIR_FAILURES["invalid_code_format"]):
        assert "letters/digits" not in said
        assert "I, L, O, 0" in said


def test_revoked_sharer_does_not_promise_a_refused_remedy():
    """⛔⛔ "ask them to share it again" IS REFUSED ON EVERY PATH — the blocklist
    is consulted by claim, by the ask route and by approve, and only a Reset or
    an owner-unlink clears it. The web app's own table says it too."""
    for said in (sr._PAIR_ERRORS["revoked_sharer"], cli._PAIR_FAILURES["revoked_sharer"]):
        low = said.lower()
        assert "ask them to share it again" not in low
        assert "only they can" in low


def test_device_secret_missing_names_the_remedy_that_works():
    """⛔ RESETTING THE CODE CANNOT RESTORE THE MISSING FIELD — only the pairing
    handshake writes it, so a fresh code throws this again, indefinitely."""
    for said in (sr._PAIR_ERRORS["device_secret_missing"],
                 cli._PAIR_FAILURES["device_secret_missing"]):
        assert "--pair" in said
        # ⛔ BOTH SPELLINGS. Wave 9 renamed the user-visible word to "access
        # code", so a negative pin on "pair code" alone could no longer fail.
        assert "reset the pair code" not in said.lower()
        assert "reset the access code" not in said.lower()


# ── C10 · the header may name only real subcommands ───────────────────────────

def test_the_header_names_only_real_subcommands():
    """⛔ THE HEADER CLAIMED A `help` SUBCOMMAND. There is none — the parser is
    `required=True` and exits with `invalid choice: 'help'`. A command list that
    names something that errors is worse than no list."""
    from conftest import code_only
    src = (AGENT / "facade" / "skill" / "scripts" / "sr.py").read_text(encoding="utf-8")
    header = code_only(src).split('"""')[1]
    assert "\n  help " not in header
    # and the descriptions corrected alongside it stay corrected
    assert "prints a code" not in header          # login prints only a link
    assert "poll until the sign-in" not in header  # login-done checks once
    assert "list reachable devices" not in header  # /devices returns all of them


# ── G5 · the TypeScript blanker must actually blank ───────────────────────────

def test_the_typescript_blanker_blanks_and_preserves_offsets():
    """⛔⛔ `code_only` IS PYTHON'S TOKENIZER: on a `.ts` file it raises and
    returns the source UNTOUCHED, so the route-drift guard was searching 222
    live comment lines while its docstring said they were blanked. A commented-out
    `error: "…"` then counts as an emitted code."""
    from conftest import ts_code_only
    src = (
        'const a = 1; // error: "commented_out"\n'
        '/* block\n   error: "also_commented" */\n'
        'const url = "https://x.test/a//b";  // trailing\n'
        'throw new ClaimError("real_code", 409);\n'
    )
    out = ts_code_only(src)
    assert len(out) == len(src), "byte offsets must be preserved"
    assert "commented_out" not in out
    assert "also_commented" not in out
    assert "real_code" in out
    assert "https://x.test/a//b" in out, "a // inside a string is not a comment"


def test_the_drift_guard_uses_the_typescript_blanker():
    """The consumer, not just the helper — extracting a blanker does not test
    the guard that needed it."""
    from conftest import code_only
    src = (AGENT / "tests" / "test_unlink_copy_795.py").read_text(encoding="utf-8")
    body = code_only(src)
    assert "ts_code_only(p.read_text" in body
    assert "code_only(p.read_text" not in body.replace("ts_code_only(p.read_text", "")
