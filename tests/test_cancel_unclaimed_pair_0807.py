"""An abandoned `--pair` must not leave a device behind.

`/api/devices/initiate-pair` creates THREE things before the human has typed
anything: the device doc, the pollSecretHash entry, and the synthetic Firebase
Auth user. Until now, giving up between the code appearing and the claim landing
left all three — and the terminal printed "nothing to clean up server-side",
which was simply false. The doc showed up later as a stale
`awaiting-initial-claim` tile; the auth user showed up nowhere, which is how
orphaned machine logins accumulated for months without anyone noticing.

Two properties are worth pinning, and they fail differently:

  1. `cancel_pair_remote` maps the server's answers correctly — in particular
     that a 409 means "someone claimed it, leave it alone" rather than an error,
     and that it sends the SECRET, not the hash (the hash is what the server
     already has; sending it would authenticate nobody).

  2. Every failure path that can run AFTER the code is on screen actually calls
     the cleanup. That one is structural, so it is checked by walking the AST of
     the real handlers rather than grepping for a name — a substring match would
     be satisfied by the call sitting in a comment or in one branch of four.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import research
from auth import v2_flow


# ── 1. cancel_pair_remote: the wire contract ───────────────────────────────


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@pytest.fixture()
def posted(monkeypatch):
    """Capture the outbound POST instead of making one."""
    seen: dict = {}

    def _fake_post(url, json=None, timeout=None, **kw):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return seen.get("resp", _Resp(200))

    monkeypatch.setattr(v2_flow.requests, "post", _fake_post)
    return seen


DEVICE_ID = "e0c8bedf4c544eca803bcc40fd863a5e"
SECRET = "s" * 64


def test_posts_the_secret_preimage_not_its_hash(posted):
    # The server stores SHA-256(pollSecret). Presenting the hash would prove
    # nothing — it is exactly the value an attacker reading the doc would need
    # us to accept. The preimage is the whole credential.
    v2_flow.cancel_pair_remote(device_id=DEVICE_ID, poll_secret=SECRET)
    assert posted["json"] == {"deviceId": DEVICE_ID, "pollSecret": SECRET}
    body = posted["json"]
    assert v2_flow.compute_poll_secret_hash(SECRET) not in body.values()


def test_posts_to_the_cancel_endpoint(posted):
    v2_flow.cancel_pair_remote(device_id=DEVICE_ID, poll_secret=SECRET)
    assert posted["url"].endswith("/api/devices/cancel-pair")
    assert posted["url"].startswith(v2_flow.FE_BASE_URL)


def test_sends_a_timeout_so_a_hung_server_cannot_wedge_the_cancel(posted):
    # This runs on the Ctrl+C path. A cancel that blocks forever is worse than
    # one that fails, because the user has already asked to stop.
    v2_flow.cancel_pair_remote(device_id=DEVICE_ID, poll_secret=SECRET)
    assert isinstance(posted["timeout"], (int, float))
    assert 0 < posted["timeout"] <= 30


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, "cancelled"),
        (409, "claimed"),
        (403, "failed"),
        (400, "failed"),
        (404, "failed"),
        (500, "failed"),
        (503, "failed"),
    ],
)
def test_maps_each_status_to_an_outcome(posted, status, expected):
    posted["resp"] = _Resp(status, "body")
    assert (
        v2_flow.cancel_pair_remote(device_id=DEVICE_ID, poll_secret=SECRET)
        == expected
    )


def test_409_is_not_an_error(posted):
    # A claimed device is a REAL device with a real owner. Reporting that as a
    # failure would push the user to retry a cancel the server will keep
    # refusing, instead of telling them to run --unpair.
    posted["resp"] = _Resp(409, '{"error":"already_claimed"}')
    assert (
        v2_flow.cancel_pair_remote(device_id=DEVICE_ID, poll_secret=SECRET)
        == "claimed"
    )


def test_network_failure_returns_failed_and_does_not_raise(monkeypatch):
    # Every caller is already handling a cancel or an error. A raise here would
    # replace the message that explains WHY we are cleaning up.
    def _boom(*a, **kw):
        raise v2_flow.requests.RequestException("no route to host")

    monkeypatch.setattr(v2_flow.requests, "post", _boom)
    assert (
        v2_flow.cancel_pair_remote(device_id=DEVICE_ID, poll_secret=SECRET)
        == "failed"
    )


# ── 2. _cancel_unclaimed_pair: the outcome the user is told ────────────────


@pytest.fixture()
def logged(monkeypatch):
    lines: list[tuple[str, str]] = []
    monkeypatch.setattr(
        research, "log", lambda msg, level="INFO", *a, **kw: lines.append((str(msg), level))
    )
    return lines


def _stub_cancel(monkeypatch, outcome):
    calls: list[dict] = []

    def _fake(*, device_id, poll_secret, **kw):
        calls.append({"device_id": device_id, "poll_secret": poll_secret})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(v2_flow, "cancel_pair_remote", _fake)
    return calls


def test_no_device_id_means_nothing_was_created(monkeypatch, logged):
    # initiate-pair never returned, so there is genuinely nothing server-side —
    # and we must not fire a request that can only 400.
    calls = _stub_cancel(monkeypatch, "cancelled")
    assert research._cancel_unclaimed_pair(None, SECRET) == "nothing"
    assert research._cancel_unclaimed_pair("", SECRET) == "nothing"
    assert calls == []


def test_cancelled_tells_the_user_no_device_was_added(monkeypatch, logged):
    _stub_cancel(monkeypatch, "cancelled")
    assert research._cancel_unclaimed_pair(DEVICE_ID, SECRET) == "cancelled"
    text = " ".join(m for m, _ in logged)
    assert "no device was added" in text.lower()


def test_claimed_points_at_unpair_rather_than_pretending_it_cleaned_up(
    monkeypatch, logged
):
    _stub_cancel(monkeypatch, "claimed")
    assert research._cancel_unclaimed_pair(DEVICE_ID, SECRET) == "claimed"
    text = " ".join(m for m, _ in logged)
    assert "--unpair" in text
    # It must NOT claim success — a device really does exist at this point.
    assert "no device was added" not in text.lower()


def test_failed_says_so_and_names_the_device(monkeypatch, logged):
    # A silent failure here recreates the original bug with extra steps: the user
    # believes it was cleaned up and never checks.
    _stub_cancel(monkeypatch, "failed")
    assert research._cancel_unclaimed_pair(DEVICE_ID, SECRET) == "failed"
    text = " ".join(m for m, _ in logged)
    assert DEVICE_ID[:12] in text
    assert any(level == "WARN" for _, level in logged)


def test_an_unexpected_raise_is_contained(monkeypatch, logged):
    _stub_cancel(monkeypatch, RuntimeError("kaboom"))
    assert research._cancel_unclaimed_pair(DEVICE_ID, SECRET) == "failed"


def test_forwards_the_id_and_secret_verbatim(monkeypatch, logged):
    calls = _stub_cancel(monkeypatch, "cancelled")
    research._cancel_unclaimed_pair(DEVICE_ID, SECRET)
    assert calls == [{"device_id": DEVICE_ID, "poll_secret": SECRET}]


def test_does_not_wipe_local_state(monkeypatch, logged):
    # _cleanup_partial_pair is the POST-exchange path: it needs an idToken we do
    # not have yet, and it deletes the keystore + research_config.json, which at
    # this point still belong to whatever pairing was here before. Calling it
    # from a pre-claim cancel would destroy a working, unrelated pairing.
    _stub_cancel(monkeypatch, "cancelled")
    called = []
    monkeypatch.setattr(
        research, "_cleanup_partial_pair", lambda *a, **kw: called.append(a)
    )
    research._cancel_unclaimed_pair(DEVICE_ID, SECRET)
    assert called == []


# ── 3. Every post-code failure path actually cleans up ─────────────────────


def _pair_flow_try_node() -> ast.Try:
    """The try/except wrapping the `do_pair_v2` call, from the real source."""
    src = Path(research.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        calls = [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "do_pair_v2"
        ]
        if calls and node.handlers:
            return node
    raise AssertionError("could not locate the do_pair_v2 try/except")


def _handler_name(h: ast.ExceptHandler) -> str:
    t = h.type
    if t is None:
        return "bare"
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    return ast.dump(t)


def _calls_cleanup(h: ast.ExceptHandler) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_cancel_unclaimed"
        for n in ast.walk(h)
    )


# PollTimeout and KeyboardInterrupt are the two the owner actually hits (waiting
# too long, or Ctrl+C); the bare Exception is everything else after the code has
# already been displayed. InitiatePairError is the deliberate exception: it is
# raised by the initiate call itself, so no device id exists to cancel.
MUST_CLEAN_UP = {"PollTimeout", "KeyboardInterrupt", "Exception"}
MUST_NOT_NEED_IT = {"InitiatePairError"}


def test_every_post_code_failure_path_cancels_the_pair():
    node = _pair_flow_try_node()
    handlers = {_handler_name(h): h for h in node.handlers}
    missing = [n for n in MUST_CLEAN_UP if n not in handlers]
    assert not missing, f"handlers vanished from the pair flow: {missing}"
    for name in MUST_CLEAN_UP:
        assert _calls_cleanup(handlers[name]), (
            f"the `except {name}` path returns without cancelling the pair — "
            "an abandoned pair leaves a stale device doc AND a live machine login"
        )


def test_a_new_handler_forces_a_decision_about_cleanup():
    # Not decoration: the original defect was a handler that returned early and
    # told the user there was nothing to clean up. Freezing the handler set means
    # the next person adding one has to come here and choose.
    node = _pair_flow_try_node()
    names = {_handler_name(h) for h in node.handlers}
    assert names == MUST_CLEAN_UP | MUST_NOT_NEED_IT, (
        f"pair-flow handlers changed to {sorted(names)} — decide whether the new "
        "one can leave an unclaimed device behind, then update MUST_CLEAN_UP"
    )


def test_the_false_reassurance_is_gone():
    # The exact sentence the terminal used to print on Ctrl+C. It was wrong: a
    # device doc, a secret entry and an auth user all existed at that moment.
    src = Path(research.__file__).read_text(encoding="utf-8")
    assert "nothing to clean up server-side" not in src


def test_the_closure_reads_the_id_captured_when_the_code_appeared():
    # `captured["device_id"]` is written by _on_code, which fires the instant
    # initiate-pair returns. Reading the post-exchange variable instead would
    # make the cleanup a no-op on exactly the paths it exists for.
    src = inspect.getsource(research)
    start = src.index("def _cancel_unclaimed()")
    body = src[start : start + 600]
    assert 'captured.get("device_id")' in body
    assert "captured_device_id" not in body
