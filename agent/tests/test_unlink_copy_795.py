"""`device-remove` tells the truth about the code, and both clients word the
same nine refusals.

⛔⛔ WHAT WAS WRONG. Since 7.7A an owner-unlink ROTATES the pair code before it
clears `ownerUid` — it has to, because `/api/devices/claim` hands OWNERSHIP to
whoever presents a valid code against an ownerless device, and unlinking creates
exactly that state. Seven places in this tree told the person the opposite:
"nothing is destroyed — re-pairable with its code". The route has always sent
the new `pairCode` on the owner branch; the bridge discarded it, so no client
could have said the true thing even if its copy had been right. And the
terminal said nothing at all — "Removed device dev-a1." and stop.

⛔⛔ AND ONE TEST PINNED THE LIE. `test_sr_client.py` asserted `"re-paired" in
out`. A guard written against wording rather than behaviour holds the wording in
place, which is what it did for four waves.

⛔⛔ THE TWO ERROR TABLES SHARED NOT ONE CODE WITH THE ROUTE THEY SERVED. The
chat client ran `device-remove` failures through `_PAIR_ERRORS` — the CLAIM
route's table. `unpair-self` emits nine codes, that table held seven, and the
intersection is EMPTY: every way an unlink can fail printed the raw identifier,
including `rotation_failed`, which is the one refusal in the product that exists
to protect the person reading it. The terminal had no table at all.

── how the route contract is pinned, and where each half actually runs ──

`_UNPAIR_SELF_CODES` / `_CLAIM_CODES` below are the recorded contract. Two
guards use them, and they run in different places on purpose:

  · The CLIENT guards (both tables cover the route's codes exactly, and the two
    clients agree with each other) run everywhere, agent CI included. That is
    the half that catches somebody wording a code in one client and not the
    other, or adding a code to the contract and wording it nowhere.

  · The ROUTE guard (the recorded list still equals what the real route emits)
    needs `dg-research/`, which agent CI does not check out — `be-tests.yml`
    checks out the backend repo alone. So it SKIPS there, exactly as
    `test_chat_owner_793.py` already does for the same reason, and runs on any
    machine holding both repos, which is where the route gets edited.

⛔ A route-source regex as the ONLY guard would therefore have been decorative
in CI by construction. Recording the contract in this tree and pinning the
clients to it is what makes the check real where the clients are edited; the
route read is the drift detector on top.
"""

import importlib.util
import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge, cli


def _load_sr():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_unlink_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()

# ── the recorded route contracts ──────────────────────────────────────────────

_UNPAIR_SELF_CODES = {
    "auth_delete_failed", "device_not_found", "deviceId_mismatch",
    "deviceId_missing", "internal_error", "not_authorized", "rate_limited",
    "rotation_failed", "unauthorized",
}

_CLAIM_CODES = {
    "code_expired", "code_not_found", "device_secret_missing", "internal_error",
    "invalid_code_format", "invalid_json", "not_previous_owner",
    "pair_bootstrap_failed", "rate_limited", "revoked_sharer",
    "share_cap_reached", "unauthorized",
}

_ROUTES = {
    "unpair-self": _UNPAIR_SELF_CODES,
    "claim": _CLAIM_CODES,
}


def _route_src(name: str) -> str:
    """The real route's source with TypeScript comments blanked, or None when the
    app repo is not checked out beside this one (which is the case in agent CI)."""
    p = (Path(__file__).resolve().parents[3] / "dg-research" / "src" / "app"
         / "api" / "devices" / name / "route.ts")
    if not p.exists():
        return None
    # ⛔⛔ `ts_code_only`, NOT `code_only`. `code_only` is Python's tokenizer; on a
    # `.ts` file it raises TokenError and returns the source UNTOUCHED, so this
    # guard was searching 222 live `//` comment lines while its docstring said
    # they were blanked. A commented-out `error: "…"` then counts as an emitted
    # code, and deleting a real one keeps the exact-set assertion green.
    from conftest import ts_code_only
    return ts_code_only(p.read_text(encoding="utf-8"))


def _codes_in(src: str) -> set[str]:
    """Every error code the route source can send.

    ⛔ `[a-zA-Z_]`, NOT `[a-z_]`. Two of `unpair-self`'s nine are camelCase
    (`deviceId_missing`, `deviceId_mismatch`) and a lowercase-only class silently
    reports seven of nine — which is how a "the table matches the route" guard
    passes while missing a third of the contract. This bit me while measuring
    this very wave.
    """
    out = set()
    for pat in (r'error:\s*"([a-zA-Z_]+)"', r'new ClaimError\(\s*"([a-zA-Z_]+)"'):
        out |= set(re.findall(pat, src))
    return out


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_recorded_contract_still_matches_the_route(route):
    """The drift detector. Skips in agent CI (no app repo), runs where the route
    is edited."""
    src = _route_src(route)
    if src is None:
        pytest.skip("dg-research/ not checked out beside this repo (agent CI)")
    assert _codes_in(src) == _ROUTES[route]


# ── both clients cover both routes, exactly ───────────────────────────────────

def test_chat_unlink_table_covers_the_unlink_route_exactly():
    assert set(sr._UNLINK_ERRORS) == _UNPAIR_SELF_CODES


def test_chat_pair_table_covers_the_claim_route_exactly():
    assert set(sr._PAIR_ERRORS) == _CLAIM_CODES


def test_terminal_unlink_table_covers_the_unlink_route_exactly():
    """`rate_limited` is answered ahead of the table because its wait comes off
    the reply, so the table plus that one key is the coverage."""
    assert set(cli._UNLINK_FAILURES) | {"rate_limited"} == _UNPAIR_SELF_CODES


def test_terminal_pair_table_covers_the_claim_route_exactly():
    assert set(cli._PAIR_FAILURES) | {"rate_limited"} == _CLAIM_CODES


@pytest.mark.parametrize("code", sorted(_UNPAIR_SELF_CODES))
def test_every_unlink_code_is_worded_by_both_clients(code):
    """⛔ THE TWO TABLES PINNED TO EACH OTHER. `sr.py` is standalone and cannot
    import `facade`, so there is no way to make them literally one table — which
    means the only thing that keeps them together is this assertion. Neither
    client may word a refusal the other leaves as a bare code."""
    assert code in sr._UNLINK_ERRORS
    said = cli._unlink_refusal(code, 90_000)
    assert said and said != code, f"terminal leaves {code} unworded"


@pytest.mark.parametrize("code", sorted(_CLAIM_CODES))
def test_every_claim_code_is_worded_by_both_clients(code):
    assert code in sr._PAIR_ERRORS
    said = cli._pair_refusal(code, 90_000)
    assert said and said != code, f"terminal leaves {code} unworded"


def test_the_two_tables_are_not_the_same_table():
    """⛔ THE SHORTCUT THIS FILE EXISTS TO BLOCK. The intersection of the two
    routes' codes is exactly {internal_error, rate_limited, unauthorized} — three
    generic codes — so a client serving unlink failures out of the pairing table
    covers none of the seven that matter."""
    assert _UNPAIR_SELF_CODES & _CLAIM_CODES == {
        "internal_error", "rate_limited", "unauthorized"}


def test_rotation_failed_says_the_machine_is_still_yours():
    """The one refusal that is protecting the reader. It must say the unlink did
    NOT happen — a person who reads it as "unlinked, but something went wrong"
    will go looking for a machine that is still theirs.

    ⛔⛔ AND IT USED TO DEMAND THE WORD "NOTHING", WHICH PINNED A FALSE CLAIM.
    Both clients said "Nothing changed", and the route deletes the device's
    pending customToken BEFORE it attempts the rotation — so an unlink stopping
    here has already destroyed a handoff. Cross-verify caught the copy; this
    guard was requiring it. The true claim is narrower and is what is pinned
    now: the machine is STILL LINKED to the reader."""
    chat = sr._UNLINK_ERRORS["rotation_failed"].lower()
    term = cli._unlink_refusal("rotation_failed").lower()
    for said in (chat, term):
        assert "still linked" in said
        assert "old one" in said
        assert "nothing changed" not in said and "nothing was changed" not in said


def test_rate_limited_wait_is_read_not_guessed():
    """Both clients name a duration only from `retryAfterMs`."""
    assert "2 minute" in cli._unlink_refusal("rate_limited", 61_000)
    assert "1 minute" in cli._unlink_refusal("rate_limited", 30_000)
    assert "minute" in cli._unlink_refusal("rate_limited", None)
    assert not re.search(r"\d+\s*minute", cli._unlink_refusal("rate_limited", None))


# ── the copy: the sentence that was false is gone, in every copy of it ────────

# ⛔ EVERY PHRASING THE SEVEN SITES ACTUALLY USED, not a canonical one. They did
# not agree with each other: four spellings of the re-pair promise and four of
# the nothing-was-lost promise, across four files. A guard on one spelling would
# have swept green over the other six.
_FALSE_PHRASES = ("re-paired with its code", "re-pairs with its code",
                  "re-pair with its code", "re-pairable with its code",
                  "keeps it re-pairable", "stays installed + re-pairable",
                  "Nothing was deleted", "Nothing gets deleted",
                  "nothing is deleted", "nothing is destroyed")


@pytest.mark.parametrize("rel", [
    "facade/bridge.py",
    "facade/cli.py",
    "facade/skill/scripts/sr.py",
    "facade/skill/SKILL.md",
])
def test_the_false_sentence_is_gone_from_every_shipped_file(rel):
    """⛔⛔ SEVEN UPSTREAM COPIES OF ONE FALSE CLAIM, in four files. A sweep, not
    a spot check, because the wave before this one found five of its own guards
    measuring nothing — a phrase quoted in a comment satisfies a substring search
    just as well as the live copy does, so the comparison runs on CODE ONLY."""
    from conftest import code_only
    p = Path(__file__).resolve().parents[1] / rel
    src = p.read_text(encoding="utf-8")
    if rel.endswith(".py"):
        src = code_only(src)
    for phrase in _FALSE_PHRASES:
        assert phrase not in src, f"{rel} still says “{phrase}”"


def test_the_chat_confirm_warns_the_code_changes_before_anyone_says_yes():
    """The confirm is the last screen before an irreversible rotation, so this is
    where the warning has to land — telling somebody afterwards is a receipt, not
    a choice."""
    said = sr._NL_CONFIRMS["device-remove"].lower()
    assert "pair code changes" in said or "pair code change" in said
    assert "old one" in said


# ── the bridge relays what the route sends, and only that ─────────────────────

class FakeFS:
    devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]

    def __init__(self, _tp):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]


@pytest.fixture()
def live(monkeypatch):
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
    try:
        yield f"http://127.0.0.1:{port}", sel
    finally:
        httpd.shutdown()
        httpd.server_close()


def _script(monkeypatch, reply, status=200):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda sess, path, payload, **kw: (status, reply))


def test_bridge_relays_the_rotated_code_on_the_owner_branch(live, monkeypatch):
    import requests
    base, _ = live
    _script(monkeypatch, {"ok": True, "action": "owner-unlinked",
                          "pairCode": "K7XQ-9B2M", "deviceName": "My PC"})
    body = requests.post(base + "/device/remove", json={"deviceId": "dev-a"}).json()
    assert body["pairCode"] == "K7XQ-9B2M"
    assert body["deviceName"] == "My PC"
    assert body["action"] == "owner-unlinked"


def test_bridge_sends_no_code_when_the_route_sends_none(live, monkeypatch):
    """⛔ THE SHARER BRANCH. Somebody walking away from a machine must not be
    handed the key to it. The route enforces that by omitting `pairCode`, and the
    bridge MIRRORS the route rather than branching on `action` — so the decision
    lives in exactly one place. The key must be ABSENT, not null: a null would
    let a client's `"pairCode" in body` test pass and print an empty code."""
    import requests
    base, _ = live
    _script(monkeypatch, {"ok": True, "action": "left-shared"})
    body = requests.post(base + "/device/remove", json={"deviceId": "dev-a"}).json()
    assert "pairCode" not in body
    assert body["action"] == "left-shared"


def test_bridge_never_logs_the_code(live, monkeypatch, caplog):
    """A credential is not log material. The line records that one was ISSUED."""
    import logging

    import requests
    base, _ = live
    _script(monkeypatch, {"ok": True, "action": "owner-unlinked",
                          "pairCode": "K7XQ-9B2M"})
    with caplog.at_level(logging.INFO):
        requests.post(base + "/device/remove", json={"deviceId": "dev-a"})
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "K7XQ-9B2M" not in joined
    assert "issued" in joined


def test_unlink_failure_is_worded_not_relayed_raw(live, monkeypatch):
    """End to end through the chat client: `rotation_failed` must not reach a
    person as `rotation_failed`."""
    import requests
    base, _ = live
    _script(monkeypatch, {"error": "rotation_failed"}, status=500)
    r = requests.post(base + "/device/remove", json={"deviceId": "dev-a"})
    assert r.status_code == 500
    assert r.json()["error"] == "rotation_failed"     # the bridge stays a relay
    said = sr._UNLINK_ERRORS[r.json()["error"]]        # the client is where it is worded
    assert "rotation_failed" not in said


# ── the sharer is not handed the code, all the way to the screen ──────────────

def test_the_no_code_fallback_does_not_send_anybody_to_a_dead_screen():
    """⛔⛔ THIS TEST WAS NAMED FOR THE SHARER BRANCH AND NEVER REACHED IT —
    `cmd_device_remove` returns before `_unlink_code_lines` on `left-shared`, so
    it was always exercising the OWNER's no-code fallback. Worse, it ASSERTED the
    false sentence: "the new one is on the device's own screen". The route says
    the opposite in its own comment — the machine cannot show a rotated code,
    because the backend only learns a code from the pairing response and cannot
    read the admin-only entry it now lives in — and the ex-owner cannot use the
    reveal either. The sharer branch is pinned by
    `test_chat_sharer_leave_is_exactly_one_line`; this one pins the fallback."""
    said = " ".join(sr._unlink_code_lines(None)).lower()
    assert "device's own screen" not in said
    assert "cannot be looked up anywhere" in said
    assert "--pair" in said and "new computer" in said
    # and the owner form is the one that carries a code
    owner = sr._unlink_code_lines("K7XQ-9B2M")
    assert any("K7XQ-9B2M" in ln for ln in owner)
    assert any("owner" in ln for ln in owner)


def test_chat_sharer_leave_is_exactly_one_line(monkeypatch):
    """⛔⛔ THE SURVIVOR THIS KILLS (U7). Appending the owner's code lines to the
    sharer branch left every test green — because every assertion about that
    branch was an `in`, and adding lines cannot break an `in`. A branch whose
    whole point is that it says LESS has to be pinned by its LENGTH.

    ⛔ AND THE FIRST VERSION OF THIS TEST WAS DECORATIVE: it built a
    one-element list itself and asserted `len(...) == 1`, which is a fact about
    the test. It has to intercept what the COMMAND passes to `_emit`."""
    seen = {}
    monkeypatch.setattr(sr, "_resolve_device_arg",
                        lambda a: ({"id": "dev-s", "name": "Boss PC"}, []))
    monkeypatch.setattr(sr, "_post", lambda path, body=None, **kw: (
        200, {"ok": True, "action": "left-shared", "pairCode": "LEAK-ME-9999"}))
    monkeypatch.setattr(sr, "_emit",
                        lambda body, as_json, lines, rc=0: (seen.update(lines=lines), rc)[1])
    args = SimpleNamespace(device="boss pc", json=False)
    assert sr.cmd_device_remove(args) == 0
    assert len(seen["lines"]) == 1, f"the sharer branch emitted {seen['lines']}"
    assert "Left the shared device" in seen["lines"][0]
    # ⛔ AND THE ROUTE'S CODE IS IGNORED EVEN IF ONE ARRIVES. The bridge should
    # never relay it on this branch, but a client that would print one anyway is
    # a client that leaks the moment the bridge changes.
    assert "LEAK-ME-9999" not in " ".join(seen["lines"])


def test_chat_unlink_uses_the_unlink_table_not_the_pairing_one(monkeypatch, capsys):
    """⛔⛔ THE SURVIVOR THIS KILLS (T1). Every guard proved the TABLE matched the
    route; none proved `cmd_device_remove` READ that table. Swapping it back to
    `_PAIR_ERRORS` crashes nothing and misspells nothing — the refusals simply
    stop existing, because the two routes' code sets share only three generic
    names. So this drives the command and asserts the SENTENCE."""
    monkeypatch.setattr(sr, "_resolve_device_arg",
                        lambda a: ({"id": "dev-a", "name": "My PC"}, []))
    monkeypatch.setattr(sr, "_post",
                        lambda path, body=None, **kw: (500, {"error": "rotation_failed"}))
    args = SimpleNamespace(device="my pc", json=False)
    assert sr.cmd_device_remove(args) != 0
    out = capsys.readouterr().out
    assert "rotation_failed" not in out
    assert "pair code wouldn’t change" in out
    assert "still linked to you" in out


def test_chat_owner_lines_call_the_code_a_credential():
    """⛔ SKILL.md CALLED A PAIR CODE "NOT a password". On an ownerless machine it
    is stronger than one — it hands the machine over. This is the moment the
    person is holding a fresh one, so it is the moment to say so."""
    said = " ".join(sr._unlink_code_lines("K7XQ-9B2M")).lower()
    assert "password" in said
    assert "claim" in said and "owner" in said

# ── the timeout chain, which is three numbers in three files ──────────────────

def test_the_unlink_timeout_chain_is_ordered():
    """⛔⛔ A TIMEOUT ON THIS ROUTE DESTROYS A CREDENTIAL, which is why the chain
    is pinned rather than left to three unrelated literals.

    `unpair-self` declares `maxDuration = 30` and can use it: up to 26 sequential
    user-tree sweeps on a machine shared with a full cohort, plus a mint, a
    rotate, a token revoke and an access-request sweep. At the shared 15s default
    the bridge gave up while the route went on to SUCCEED — and the rotated pair
    code, the only copy that ever exists, was discarded with the timed-out
    response. Both clients then said the request never landed, the retry answered
    `not_authorized` because the machine really was unlinked, and the ex-owner
    cannot use the reveal. The machine became permanently un-re-linkable by a
    timeout. Cross-verify found it.

    ⛔ AND RAISING THE SHARED DEFAULT WAS THE WRONG FIX — a guard in
    `test_fe_json_792.py` caught it, correctly: both clients wait 30s for the
    bridge and past that they report a bridge that is not running. So the order
    that has to hold is
        route maxDuration  <  bridge unlink timeout
        bridge unlink timeout + refresh cap + 1  <  each client's unlink timeout
    and every link is in a different file, which is exactly when a chain needs a
    test rather than three comments.
    """
    import inspect
    import re as _re

    refresh_cap = 10   # session.py's cap, the same figure test_fe_json_792 uses
    route_max = 30     # unpair-self/route.ts `export const maxDuration`

    assert bridge._FE_UNLINK_TIMEOUT > route_max, (
        "the bridge must outwait the route or it throws away the new pair code")

    # ⛔⛔ AND THE CALL SITE MUST ACTUALLY PASS IT. A mutant deleted the
    # `timeout=` argument from `_device_remove` and this whole test stayed green,
    # because everything above pins the CONSTANTS: the value was still 35, the
    # clients still waited 50, and the unlink quietly reverted to the shared 15s
    # default. Pinning a helper is not pinning its consumer — the lesson this
    # repo has recorded three times, found here by mutant T10.
    remove_src = inspect.getsource(
        [v for k, v in vars(bridge._make_handler(bridge.BridgeState())).items()
         if k == "_device_remove"][0])
    assert "timeout=_FE_UNLINK_TIMEOUT" in remove_src, (
        "/device/remove must pass the long timeout, not inherit the shared default")

    chat = inspect.getsource(sr.cmd_device_remove)
    m = _re.search(r'"/device/remove".*?timeout=(\d+)', chat, _re.S)
    assert m, "the chat client's unlink call must set its own timeout"
    assert int(m.group(1)) > bridge._FE_UNLINK_TIMEOUT + refresh_cap, (
        f"chat waits {m.group(1)}s, the bridge can take "
        f"{bridge._FE_UNLINK_TIMEOUT + refresh_cap}s")

    term = inspect.getsource(cli.cmd_device)
    m = _re.search(r'"/device/remove".*?timeout=([\d.]+)', term, _re.S)
    assert m, "the terminal's unlink call must set its own timeout"
    assert float(m.group(1)) > bridge._FE_UNLINK_TIMEOUT + refresh_cap, (
        f"the terminal waits {m.group(1)}s, the bridge can take "
        f"{bridge._FE_UNLINK_TIMEOUT + refresh_cap}s")


def test_the_route_still_declares_the_duration_this_chain_assumes():
    """The drift detector on the other end. Skips in agent CI, runs where the
    route is edited — if `maxDuration` rises, the chain above needs re-deriving."""
    src = _route_src("unpair-self")
    if src is None:
        pytest.skip("dg-research/ not checked out beside this repo (agent CI)")
    import re as _re
    m = _re.search(r"maxDuration\s*=\s*(\d+)", src)
    assert m, "unpair-self no longer declares maxDuration — re-derive the chain"
    assert int(m.group(1)) <= bridge._FE_UNLINK_TIMEOUT, (
        f"the route now declares {m.group(1)}s and the bridge waits "
        f"{bridge._FE_UNLINK_TIMEOUT}s — a slow unlink loses the new pair code")
