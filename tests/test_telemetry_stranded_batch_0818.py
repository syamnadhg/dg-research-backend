"""A batch its owner died holding must survive the delivery failing.

⛔⛔ MEASURED 2026-08-18. A spool file is adopted UNDER ITS OWN NAME — nothing
renames it, because it is already claimed. The failure path then called

    _merge_back(claimed, path if ".sending." not in path.name else path)

whose ternary has the SAME expression in both arms, so for an adopted file
`claimed` and `path` were one file. `_merge_back` read it, wrote it back into
itself, and unlinked the file it had just written. Nine real events, gone in one
call.

⭐⭐ It destroyed exactly the events worth keeping. A stranded file belongs to a
process that DIED, and the trigger is delivery failing — which is the outage this
whole system exists to report. The two things that had to be true for the data to
be lost were the two things that are true during an incident.

⛔ The first repro was WRONG and said the same thing for the wrong reason: events
written without a `t` are age-expired and legitimately discarded, so the file
vanished on a path that had nothing to do with this bug. Every fixture below
carries a real timestamp.
"""
import json
import time

import pytest
from conftest import code_only_deep

import telemetry


def _fn(name: str) -> str:
    """The function's CODE, with comments and docstrings blanked.

    ⛔ `inspect.getsource` was the first attempt and it failed on the notes this
    very wave added — a test asserting the wrong scheme is absent matched the
    comment explaining why it was removed. Prose is not the artifact under test.
    """
    src = code_only_deep(telemetry)
    i = src.index(f"def {name}(")
    nxt = src.find("\ndef ", i + 1)
    return src[i:nxt if nxt != -1 else len(src)]


def _events(n: int) -> str:
    now = int(time.time() * 1000)
    return "".join(json.dumps({"v": 1, "seq": i, "ev": 49, "t": now}) + "\n"
                   for i in range(n))


@pytest.fixture()
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("SR_TELEMETRY_DIR", str(tmp_path))
    return tmp_path


def test_a_stranded_batch_survives_a_failed_delivery(spool):
    stranded = spool / "pending-cli.sending.999999.jsonl"
    stranded.write_text(_events(9), encoding="utf-8")

    assert telemetry.flush(post=lambda _b: False, deadline_sec=1.0) == 0

    left = sorted(spool.glob("*.jsonl"))
    surviving = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in left)
    assert surviving == 9, f"{surviving} of 9 events survived; files={[p.name for p in left]}"


def test_the_recovered_batch_is_delivered_on_the_next_success(spool):
    """Surviving on disk is only half of it — the events have to be reachable
    again, which means landing under the UNCLAIMED name."""
    (spool / "pending-cli.sending.999999.jsonl").write_text(_events(9), encoding="utf-8")
    telemetry.flush(post=lambda _b: False, deadline_sec=1.0)

    got: list = []
    telemetry.flush(post=lambda b: (got.extend(b), True)[1], deadline_sec=1.0)
    assert len(got) == 9
    assert not list(spool.glob("*.jsonl"))


def test_a_file_is_never_merged_into_itself(spool):
    """The invariant, pinned directly — the call site is one refactor away from
    handing the same path twice again."""
    f = spool / "pending-cli.sending.999999.jsonl"
    f.write_text(_events(9), encoding="utf-8")
    telemetry._merge_back(f, f)
    assert f.exists(), "merging a file into itself deleted it"
    assert len(f.read_text(encoding="utf-8").splitlines()) == 9


def test_the_adopted_name_resolves_to_the_live_spool(spool):
    assert telemetry._unclaimed_name(
        spool / "pending-cli.sending.8538.jsonl").name == "pending-cli.jsonl"
    # Already unclaimed — must be left exactly alone.
    assert telemetry._unclaimed_name(
        spool / "pending-cli.jsonl").name == "pending-cli.jsonl"


def test_an_ordinary_claimed_batch_still_merges_back(spool):
    """The non-adopted path is the common one and must not regress."""
    (spool / "pending-cli.jsonl").write_text(_events(4), encoding="utf-8")
    telemetry.flush(post=lambda _b: False, deadline_sec=1.0)
    left = sorted(spool.glob("*.jsonl"))
    assert [p.name for p in left] == ["pending-cli.jsonl"]
    assert len(left[0].read_text(encoding="utf-8").splitlines()) == 4


def test_events_that_arrived_during_the_attempt_are_kept_behind_the_owed_ones(spool):
    """Ordering is the reason _merge_back exists at all."""
    stranded = spool / "pending-cli.sending.999999.jsonl"
    stranded.write_text(json.dumps({"v": 1, "seq": 0, "ev": 49,
                                    "t": int(time.time() * 1000)}) + "\n",
                        encoding="utf-8")
    live = spool / "pending-cli.jsonl"
    live.write_text(json.dumps({"v": 1, "seq": 99, "ev": 41,
                                "t": int(time.time() * 1000)}) + "\n",
                    encoding="utf-8")

    telemetry.flush(post=lambda _b: False, deadline_sec=1.0)

    seqs = [json.loads(l)["seq"]
            for l in live.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert seqs == [0, 99], seqs


def test_a_live_siblings_batch_is_still_left_alone(spool):
    """⛔ The counterweight. Adoption must stay restricted to dead owners, or two
    processes double-post the quietest thing in the product."""
    import os
    mine = spool / f"pending-cli.sending.{os.getppid()}.jsonl"
    mine.write_text(_events(3), encoding="utf-8")
    if telemetry._pid_alive(os.getppid()):
        assert telemetry._adoptable(mine) is False


# ── attribution: two bugs, stacked, both silent ──────────────────────────────

def test_the_auth_scheme_is_the_one_the_route_accepts():
    """⛔⛔ MEASURED: the sender said `Authorization: Firebase <token>` while the
    route's verifier returns null unless the header starts with `Bearer `. So
    even a perfect token stored the batch unverified, with no account on it.
    Every other authenticated caller in this codebase already uses Bearer."""
    src = _fn("_post_batch")
    assert 'f"Bearer {token}"' in src
    assert "Firebase {token}" not in src


def test_a_missing_accessor_is_not_the_same_as_a_signed_out_machine(caplog):
    """⛔⛔ `auth.credentials` has no `current_id_token` and never has. The bare
    `except` swallowed the ImportError and returned None — byte-identical to the
    designed no-credential case, which is why nobody noticed that every batch
    this product ever sent was anonymous.

    ⭐ The token stays OPTIONAL. What changed is that a wiring fault is now
    legible in the very log bundle a user sends."""
    import logging
    with caplog.at_level(logging.DEBUG, logger=telemetry.log.name):
        assert telemetry._id_token() is None
    assert any("id-token accessor" in r.getMessage() for r in caplog.records), \
        "a broken accessor is still indistinguishable from a signed-out machine"


def test_the_token_path_never_forces_a_refresh_or_touches_the_keystore():
    """⛔ The only accessor that exists (`_fresh_user_mode_id_token`) does both —
    a network round trip per flush and a keystore wipe on revoke. Telemetry
    causing an auth side effect would be far worse than telemetry being
    anonymous, so wiring that one in is deliberately NOT the fix."""
    src = _fn("_id_token")
    assert "_fresh_user_mode_id_token" not in src
    assert "keystore" not in src
