"""Wave 9: the agent reads the server's stamp, not the machine's guess.

⛔⛔ THE AGENT COULD NOT READ A TIMESTAMP FIELD AT ALL. Over REST a Firestore
Timestamp arrives as ``{"timestampValue": "2026-09-16T12:34:56.789123456Z"}`` and
``from_value`` hands back that STRING — so a reader that subtracted it from
``time.time() * 1000`` raised, and a reader that guarded with
``isinstance(x, (int, float))`` fell through and never saw the field. A
server-stamped heartbeat the agent cannot decode is a field written for nobody.

⛔⛔ AND THE READ ORDER IS NEW-FIRST, WHICH IS THE OPPOSITE OF ``joinPolicy`` IN
THE SAME WAVE. ``joinPolicy`` reads OLD-first because ``visibility`` is still the
authoritative copy until a later flip; liveness reads NEW-first because
``heartbeatAt`` is not a second opinion about the same fact but a better-sourced
one — ``lastHeartbeat`` is the machine's clock aged against this host's, and the
stamp is one clock for both ends. The two orderings are here on purpose and the
reason is in the code beside each.
"""

from __future__ import annotations

import time

import pytest

from facade import bridge
from facade.firestore_rest import FirestoreRest, timestamp_millis


def _iso(ms: float, *, digits: int = 6) -> str:
    """An RFC3339 string the way Firestore REST writes one — 'Z'-suffixed, with
    `digits` fractional digits."""
    import datetime as dt
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    frac = f"{t.microsecond:06d}".ljust(digits, "0")[:digits]
    head = t.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{head}.{frac}Z" if digits else f"{head}Z"


# ── the preference ──────────────────────────────────────────────────────────

def test_the_server_stamp_overrules_a_machine_clock_that_says_long_offline():
    """⛔⛔ THE SLOW-CLOCK HALF. A machine whose clock runs ten minutes behind
    stamps `lastHeartbeat` ten minutes in the past while it is working — so the
    agent called it offline, refused to route runs to it, and said nothing about
    why. Firestore's stamp says it wrote a second ago, and Firestore is the one
    party to this that cannot have the wrong time."""
    now_ms = time.time() * 1000
    d = {"heartbeatAt": _iso(now_ms - 1_000),
         "lastHeartbeat": now_ms - 10 * 60_000}
    assert bridge._device_is_online(d)


def test_the_server_stamp_overrules_a_machine_clock_that_says_online():
    """⛔⛔ THE FAST-CLOCK HALF, AND THE ONE THAT NEVER DECAYED. A computer
    switched off with a clock ten minutes fast kept a `lastHeartbeat` in the
    future for as long as the skew lasted. The future tolerance bounds how far,
    but inside that window it still read ONLINE — and a run announced "Started"
    on a machine that was off. The stamp stopped a quarter of an hour ago and
    that is the end of it."""
    now_ms = time.time() * 1000
    d = {"heartbeatAt": _iso(now_ms - 15 * 60_000),
         "lastHeartbeat": now_ms + 60_000}
    assert not bridge._device_is_online(d)


def test_the_stamp_alone_is_enough_and_is_still_bounded():
    """The stamp does not merely break ties — it can decide on its own, and the
    30s bound applies to it exactly as it does to the number. Both halves in one
    test: a device with only a fresh stamp must read ONLINE (which nothing could
    do before this), and one with only a stale stamp must read OFFLINE."""
    now_ms = time.time() * 1000
    assert bridge._device_is_online({"heartbeatAt": _iso(now_ms - 5_000)})
    assert not bridge._device_is_online({"heartbeatAt": _iso(now_ms - 60_000)})


def test_a_device_with_no_stamp_reads_exactly_as_it_did():
    """⛔ THE FALLBACK IS PERMANENT, NOT A MIGRATION STEP. A legacy
    `users/{uid}/devices` row never carries the stamp, and a machine on an older
    wheel will not write one until it updates. Both wave-8 bounds must still
    decide those rows."""
    now_ms = time.time() * 1000
    assert bridge._device_is_online({"lastHeartbeat": now_ms - 5_000})
    assert bridge._device_is_online({"lastHeartbeat": now_ms + 45_000})
    assert not bridge._device_is_online({"lastHeartbeat": now_ms - 60_000})
    assert not bridge._device_is_online({"lastHeartbeat": now_ms + 10 * 60_000})
    assert not bridge._device_is_online({})


@pytest.mark.parametrize("junk", ["", "   ", "not-a-timestamp", "2026-13-45T99:99:99Z",
                                  None, True, [], {"seconds": 1}])
def test_an_unreadable_stamp_falls_back_instead_of_taking_a_machine_offline(junk):
    """⛔ A STAMP THAT CANNOT BE PARSED MUST NOT BE ABLE TO KILL A TILE. The
    failure mode of a decoder is silence, so the wrong shape here is a decoder
    that returns 0 (everything reads offline forever) or raises (the whole device
    list dies on one bad row)."""
    now_ms = time.time() * 1000
    assert bridge._device_is_online({"heartbeatAt": junk,
                                     "lastHeartbeat": now_ms - 5_000})
    assert not bridge._device_is_online({"heartbeatAt": junk,
                                         "lastHeartbeat": now_ms - 60_000})


# ── the decode, against the real wire shape ─────────────────────────────────

# A verbatim `:runQuery` response row for `devices/{id}`, in the shape the
# Firestore REST API actually returns one: `integerValue` arrives as a STRING,
# `timestampValue` as RFC3339 with NINE fractional digits (which
# `datetime.fromisoformat` refuses outright), and `updateTime`/`readTime` ride
# alongside `fields` rather than inside it.
_REAL_RUNQUERY_ROW = {
    "document": {
        "name": "projects/dg-research/databases/(default)/documents/devices/dev-7f3a",
        "fields": {
            "ownerUid": {"stringValue": "u1"},
            "name": {"stringValue": "Macbook"},
            "status": {"stringValue": "active"},
            "pairConfirmedAt": {"booleanValue": True},
            "workerCount": {"integerValue": "2"},
            "lastHeartbeat": {"integerValue": "1600000000000"},
            "heartbeatAt": {"timestampValue": "2026-09-16T12:34:56.789123456Z"},
        },
        "createTime": "2026-05-02T09:11:03.512345Z",
        "updateTime": "2026-09-16T12:34:56.789123456Z",
    },
    "readTime": "2026-09-16T12:34:57.001002003Z",
}


def _client_returning(row):
    calls = []

    def fake_request(method, url, *, json_body=None):
        calls.append(url)
        if url.endswith(":runQuery"):
            field = json_body["structuredQuery"]["where"]["fieldFilter"]["field"]["fieldPath"]
            return [row] if field == "ownerUid" else []
        return {}

    c = FirestoreRest(lambda: "tok")
    c._request = fake_request  # type: ignore[method-assign]
    return c


def test_the_real_rest_payload_decodes_to_the_millis_the_server_meant():
    """Driven through the REAL list path, not a hand-made dict: the row is
    decoded by `fields_to_dict` exactly as `list_devices` decodes a live one.
    Nine fractional digits is the case that matters — `fromisoformat` raises on
    it, so a decoder written against a tidy example returns None here and the
    stamp is silently never read."""
    rows = _client_returning(_REAL_RUNQUERY_ROW).list_devices("u1")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "dev-7f3a"
    # The REST decode leaves the wire string in place; only the arithmetic
    # reader converts, so no other field's type moves.
    assert row["heartbeatAt"] == "2026-09-16T12:34:56.789123456Z"
    assert row["lastHeartbeat"] == 1600000000000
    # 2026-09-16T12:34:56.789123Z — truncated to the microseconds a datetime
    # holds, never rounded up into the next second.
    assert timestamp_millis(row["heartbeatAt"]) == pytest.approx(1789562096789.123, abs=0.01)


def test_the_decoded_row_is_what_decides_online():
    """⛔ THE CONSUMER, NOT THE HELPER. The same real row, aged by the real
    reader: its `lastHeartbeat` is September 2020 and its stamp is now, so a
    reader that still preferred the number calls this machine offline."""
    row = dict(_REAL_RUNQUERY_ROW["document"]["fields"])
    now_ms = time.time() * 1000
    decoded = _client_returning({
        "document": {
            "name": ".../devices/dev-7f3a",
            "fields": {**row,
                       "heartbeatAt": {"timestampValue": _iso(now_ms - 2_000, digits=9)}},
        }
    }).list_devices("u1")[0]
    assert decoded["lastHeartbeat"] == 1600000000000  # years stale
    assert bridge._device_is_online(decoded)


@pytest.mark.parametrize("digits", [0, 3, 6, 9])
def test_every_fraction_width_firestore_emits_is_readable(digits):
    """Firestore serializes zero, three, six or nine fractional digits depending
    on the value. All four are the same instant to the nearest millisecond."""
    now_ms = float(int(time.time() * 1000))
    got = timestamp_millis(_iso(now_ms, digits=digits))
    assert got is not None
    assert abs(got - now_ms) < 1000


def test_an_explicit_offset_is_honoured_not_dropped():
    """Reading `+05:30` as UTC would move a machine's liveness by five and a half
    hours — offline everywhere, or online for hours after it was switched off."""
    z = timestamp_millis("2026-09-16T12:34:56.000Z")
    plus = timestamp_millis("2026-09-16T18:04:56.000+05:30")
    assert z is not None and plus is not None
    assert z == plus


def test_a_number_passes_through_so_a_caller_need_not_care():
    """The Admin SDK and the browser hand the same field over as millis. A
    decoder that only understood strings would make every caller branch."""
    assert timestamp_millis(1_600_000_000_000) == 1_600_000_000_000.0
    assert timestamp_millis(True) is None  # a bool is not a timestamp


# ── the two orderings, and why they differ ──────────────────────────────────

def test_the_two_read_orders_in_this_wave_point_opposite_ways_on_purpose():
    """⛔⛔ THE THING A LATER READER GETS WRONG. Liveness prefers the NEW key and
    `joinPolicy` prefers the OLD one, in the same wave, in the same file — so
    each must carry its reason where it is read. Executed both ways rather than
    grepped for a comment: the old visibility value still wins while it is
    there, and the new stamp still wins the moment it appears."""
    now_ms = time.time() * 1000
    # joinPolicy: OLD wins while the old key is present.
    assert bridge._discovery_of({"visibility": "private", "joinPolicy": "public"}) == "private"
    # liveness: NEW wins the moment the stamp is present.
    assert bridge._device_is_online({"lastHeartbeat": now_ms - 10 * 60_000,
                                     "heartbeatAt": _iso(now_ms - 1_000)})
