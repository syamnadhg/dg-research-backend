"""Wave 9: the heartbeat carries a stamp Firestore writes, not one this machine
guesses.

WHAT WAS WRONG

`lastHeartbeat` is `int(time.time() * 1000)` — THIS COMPUTER'S clock — and every
reader ages it against a DIFFERENT clock. So the answer to "is that machine on?"
was the difference between two unsynchronised clocks, and it was wrong in both
directions:

  * a machine whose clock runs fast reads ONLINE after it is switched off, for
    as long as the skew lasts;
  * a machine whose clock runs slow reads OFFLINE while it is working, and every
    run is refused.

Neither reports anything. The fix is a SECOND field, `heartbeatAt`, written with
Firestore's `SERVER_TIMESTAMP` sentinel, which resolves server-side to
`request.time` — one clock for the writer and the reader both. It is the only
form the rules can also enforce, because a millis int can be forged to any value
and no rule can tell.

WHAT THIS FILE PINS

That the stamp is a SENTINEL and not a number, and that it rides in the SAME
`update()` as `lastHeartbeat`. Both halves matter:

  * a number would just be a second field this machine's clock also writes —
    server-stamped in name only;
  * a stamp written by a SEPARATE request can land before or after the liveness
    write it is supposed to date, and a liveness stamp that can lag its own
    liveness write is not worth reading. That is why this key may NOT use the
    throttled best-effort update the version/updateAvailable signal uses.

⛔ THE COST OF THAT CHOICE IS A RELEASE ORDER, not a code change. The update is
atomic, so one key the deployed `firestore.rules` does not admit 403s the
`expireAt: DELETE_FIELD` cancel with it — and a machine pairing inside the claim
Cloud Function's 5-minute TTL window then loses its whole device document. The
rules deploy must land and be verified in production BEFORE this wheel publishes.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

import research

from conftest import code_only


def _heartbeat_src() -> str:
    """Comment-blanked source of the loop. MANDATORY here: the paragraph beside
    the new key names `SERVER_TIMESTAMP` and `heartbeatAt` in prose, so a raw
    substring search would pass against the explanation and keep passing after
    the code was gone."""
    return textwrap.dedent(code_only(research._heartbeat_loop))


def _liveness_payload() -> ast.Dict:
    """The one `update({...})` dict in the heartbeat loop that writes
    `lastHeartbeat` — found on the syntax tree, so 'which dict' is not a
    guess about indentation."""
    tree = ast.parse(_heartbeat_src())
    found: list[ast.Dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "update":
            continue
        if not node.args or not isinstance(node.args[0], ast.Dict):
            continue
        keys = {k.value for k in node.args[0].keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "lastHeartbeat" in keys:
            found.append(node.args[0])
    assert len(found) == 1, (
        f"expected exactly one liveness update() writing lastHeartbeat, "
        f"found {len(found)}"
    )
    return found[0]


def _payload_keys(d: ast.Dict) -> dict[str, ast.expr]:
    return {k.value: v for k, v in zip(d.keys, d.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


# ── the stamp ───────────────────────────────────────────────────────────────

def test_the_heartbeat_writes_a_server_stamped_field():
    """⛔⛔ THE WHOLE POINT, AND IT IS THE VALUE THAT CARRIES IT. Asserted on the
    syntax tree: the value of `heartbeatAt` must be the bare name
    `SERVER_TIMESTAMP`. A millis int, a `datetime.now()`, or anything else
    computed on this side would be this machine's clock again under a new name —
    which is the defect, not the fix."""
    payload = _payload_keys(_liveness_payload())
    assert "heartbeatAt" in payload, (
        "the heartbeat writes no server-stamped field — every reader is still "
        "aging this machine's own clock against its own"
    )
    value = payload["heartbeatAt"]
    assert isinstance(value, ast.Name) and value.id == "SERVER_TIMESTAMP", (
        f"heartbeatAt is written as {ast.dump(value)} — it must be Firestore's "
        f"SERVER_TIMESTAMP sentinel, because a value this side computes is not "
        f"server-stamped in any sense a rule could enforce"
    )


def test_the_sentinel_is_imported_from_the_firestore_sdk():
    """So the name in the payload resolves to the real sentinel. A local
    `SERVER_TIMESTAMP = int(time.time() * 1000)` would satisfy the test above
    and write a number."""
    tree = ast.parse(_heartbeat_src())
    imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "google.cloud.firestore":
            names = {a.name for a in node.names}
            if "SERVER_TIMESTAMP" in names:
                imported = True
                # The TTL cancel shares this import line; losing it silently
                # would take the pairing contract down with it.
                assert "DELETE_FIELD" in names
    assert imported, (
        "SERVER_TIMESTAMP is not imported from google.cloud.firestore inside "
        "the heartbeat loop — the name in the payload is something else"
    )
    assert "SERVER_TIMESTAMP =" not in _heartbeat_src(), (
        "the sentinel name is being reassigned locally, so the payload is not "
        "carrying the SDK's sentinel"
    )


def test_the_stamp_rides_the_SAME_update_as_the_liveness_write():
    """⛔⛔ ONE ATOMIC WRITE, DELIBERATELY. The version/updateAvailable signal is
    published by a SEPARATE throttled update precisely so a rules lag on those
    keys cannot flip the device offline — and that pattern is explicitly NOT
    available here. A stamp written by another request can land before or after
    the liveness write it dates, so a reader preferring it would be trusting a
    value that may be older than the number beside it."""
    payload = _payload_keys(_liveness_payload())
    # `_liveness_payload` already asserts there is exactly ONE update() writing
    # lastHeartbeat; this pins that the stamp is inside that same one, next to
    # the TTL cancel the atomicity is protecting.
    assert {"lastHeartbeat", "heartbeatAt", "expireAt"} <= set(payload), (
        f"the liveness payload is {sorted(payload)} — the stamp must sit with "
        f"lastHeartbeat and the expireAt cancel in one all-or-nothing update"
    )


def test_the_plain_number_is_never_retired():
    """⛔ `lastHeartbeat` STAYS FOREVER. The agent reaches Firestore over REST and
    the web's legacy mapper reads a plain number; a device doc under the old
    `users/{uid}/devices` tree will never carry the stamp at all. Replacing the
    number rather than adding beside it would blank the tile on every reader
    that cannot decode a Timestamp."""
    payload = _payload_keys(_liveness_payload())
    assert {"lastHeartbeat", "heartbeatAt"} <= set(payload), (
        f"the liveness payload is {sorted(payload)} — the stamp is an ADDITION, "
        f"and a device doc that carries only one of the two is a device some "
        f"reader cannot age at all"
    )
    value = payload["lastHeartbeat"]
    assert isinstance(value, ast.Call), (
        f"lastHeartbeat is written as {ast.dump(value)} — it must stay the "
        f"computed millis int every REST reader depends on"
    )
    assert "int(time.time() * 1000)" in _heartbeat_src()


# ── the prose the constants had outgrown ────────────────────────────────────

@pytest.mark.parametrize("stale", [
    "15s offline threshold",
    "15s offline window",
    "Offline at ~15s",
])
def test_no_copy_of_the_old_offline_threshold_survives(stale):
    """The FE threshold has been 30_000 since 2026-05-20 and five prose copies in
    this file still said 15s four months later — including the heartbeat loop's
    own docstring, which is the first thing anybody reads to find out what the
    cadence is paired with. Docstrings included (`code_only` would leave them),
    because that is where four of the five lived."""
    src = inspect.getsource(research)
    assert stale not in src, f"a stale copy of the 15s threshold survives: {stale!r}"


def test_the_cadence_comment_names_where_the_threshold_actually_LIVES():
    """It pointed at `web/src/lib/firestore.ts` — a path with a directory that
    does not exist in this repo, naming a file that only RE-EXPORTS the constant.
    A reader who went looking found nothing and had no way to check the number
    against its source."""
    src = inspect.getsource(research)
    assert "web/src/lib/firestore.ts" not in src
    i = src.index("HEARTBEAT_INTERVAL_SEC = 5")
    block = src[i - 1200:i]
    assert "30s offline threshold" in block
    assert "device-order.ts" in block


def test_the_reconnect_ladder_is_described_as_the_ladder_it_runs():
    """The docstring said 5→10→30s and the tuple is (5, 5, 10, 30) — four steps,
    not three. The expected sentence is BUILT FROM THE TUPLE, so prose and code
    cannot drift apart again: change the ladder and this test names the
    docstring."""
    tree = ast.parse(textwrap.dedent(code_only(research._firebase_reconnect_loop)))
    ladders = [
        [e.value for e in node.value.elts]
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "BACKOFF" for t in node.targets)
        and isinstance(node.value, ast.Tuple)
    ]
    assert len(ladders) == 1, f"expected one BACKOFF tuple, found {len(ladders)}"
    expected = "→".join(str(s) for s in ladders[0]) + "s"
    doc = research._firebase_reconnect_loop.__doc__ or ""
    assert expected in doc, (
        f"the docstring does not describe the ladder it runs ({expected})"
    )
