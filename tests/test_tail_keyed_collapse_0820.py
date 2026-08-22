"""The read-time collapse recognises a repeated MESSAGE, not a repeated byte.

⛔⛔ THE DOCSTRING CLAIMED COVERAGE IT DID NOT HAVE. `_filter_tail_lines` said its
byte-identical run-collapse was "general — it catches the refresh flood, our own
aegis pulse, and whatever the next one turns out to be, without anybody having to
add a pattern for it." It could not catch the aegis pulse, and only measuring a
real support bundle showed it:

    system/backend-2.log   29,543 lines, 2,340 distinct messages  (92.1% repeat)
        10,839   [aegis] worker 2: ◆ standing watch
        10,832   [aegis] worker 2: ◇ standing watch

That one line defeats adjacency comparison TWICE over: every copy carries its own
timestamp, so no two are byte-identical — and the glyph ALTERNATES, so no two are
even the same message in a row. 94% of the bundle a user sends was these tails and
the collapse had removed none of it.

⭐ The principle in that comment was right and the comparison was wrong. Repeats
are now keyed on the message with the timestamp stripped, held back at the same
widening cadence the source-side suppressor uses, and every held copy is COUNTED
onto the next one that gets through. No pattern list; nothing named.

MEASURED after, on the same machine's real logs:
    bundle raw      8,364,273 → 2,178,321 bytes
    backend-2.log      29,543 → 5,881 lines   (heartbeat 21,705 → 401)
    machine-log share    94.2% → 75.9%,  the run's own folder 3.3% → 13.1%

Run: pytest tests/test_tail_keyed_collapse_0820.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

FILTER_SRC = inspect.getsource(research._filter_tail_lines)


def _hb(i: int) -> bytes:
    """The heartbeat exactly as the frozen logs carry it: own timestamp, and a
    glyph that alternates between ticks."""
    glyph = "◆" if i % 2 == 0 else "◇"
    return f"[21:{i // 60:02d}:{i % 60:02d}] [INFO] [aegis] worker 2: {glyph} standing watch".encode()


def _real(i: int) -> bytes:
    return f"[21:{i // 60:02d}:{i % 60:02d}] [INFO] a thing actually happened #{i}".encode()


def _run(lines, limit=10 ** 9):
    stats: dict = {}
    return research._filter_tail_lines(lines, limit=limit, stats=stats), stats


# ── 1. the line that defeated the old rule ──────────────────────────────────

class TestTheHeartbeatIsFinallyCollapsed:

    def test_a_timestamped_alternating_pulse_collapses(self):
        """⛔ THE BUG. Byte-identical adjacency sees no repetition here at all:
        200 lines in, 200 lines out, which is what put 21,705 copies of this into
        a support bundle."""
        out, stats = _run([_hb(i) for i in range(200)])
        assert stats["throttled"] > 150, stats
        kept = [b for b in out if b"standing watch" in b]
        assert len(kept) < 40, f"{len(kept)} copies kept of 200"

    def test_the_key_ignores_the_timestamp(self):
        a = b"[21:00:01] [INFO] [aegis] worker 2: same message"
        b = b"[21:44:59] [INFO] [aegis] worker 2: same message"
        assert research._tail_msg_key(a) == research._tail_msg_key(b)

    def test_the_key_ignores_the_level_too(self):
        a = b"[21:00:01] [INFO] the same sentence"
        b = b"[21:00:02] [WARN] the same sentence"
        assert research._tail_msg_key(a) == research._tail_msg_key(b)

    def test_a_line_with_no_timestamp_keys_on_itself(self):
        raw = b"INFO:     127.0.0.1:1 - GET /api/health HTTP/1.1 200 OK"
        assert research._tail_msg_key(raw) == raw

    def test_two_different_messages_never_collapse_into_each_other(self):
        out, _ = _run([b"[21:00:01] [INFO] alpha", b"[21:00:02] [INFO] beta"])
        body = [b for b in out if b"[bundle]" not in b]
        assert len(body) == 2, body


# ── 2. what must survive — the whole point of a support bundle ──────────────

class TestNothingWorthReadingIsLost:

    def test_every_distinct_event_survives_a_flood_around_it(self):
        """⭐ The reason to collapse rather than truncate: the budget stops being
        spent on repetition, so the content a reader came for stays in."""
        lines = []
        for i in range(400):
            lines.append(_hb(i))
            if i % 50 == 0:
                lines.append(_real(i))
        out, stats = _run(lines)
        survived = [b for b in out if b"actually happened" in b]
        assert len(survived) == 8, f"{len(survived)} of 8 real events survived"

    def test_a_held_copy_is_counted_never_discarded(self):
        """A suppressed repeat carries its count onto the next copy through —
        the same contract the source-side rule has. Silence would make the
        bundle lie by omission."""
        out, stats = _run([_hb(i) for i in range(60)])
        notes = [b for b in out if b"[bundle]" in b]
        assert notes, "repeats vanished with no count"
        counted = sum(int(b.split(b"occurred ")[1].split(b" more")[0])
                      for b in notes if b"occurred " in b)
        # ⛔ Plus the REMAINDER. A message held back at the end of the scan has no
        # later copy to ride out on — 8 of 40 went unaccounted until this test
        # said so, which is the exact failure the contract forbids.
        #
        # ⭐ 2026-08-22: parsed off `_TAIL_KEYED_TAIL_PREFIX` rather than off the
        # first `] `. The remainder note grew a fixed opening phrase so
        # `_tail_bytes` can tell it apart from the two markers that describe the
        # line above them — all three used to begin `[bundle] `, which is what a
        # positional split was really keying on.
        counted += sum(
            int(b.split(research._TAIL_KEYED_TAIL_PREFIX)[1].split(b" further")[0])
            for b in notes if b.startswith(research._TAIL_KEYED_TAIL_PREFIX))
        assert counted == stats["throttled"], (counted, stats["throttled"])

    def test_the_remainder_is_reported_even_with_no_later_copy(self):
        """One message, repeats still held when the scan ends: the count has to
        appear somewhere.

        ⭐ The timestamps VARY on purpose. Byte-identical copies never reach the
        keyed rule at all — the adjacency rule catches them first — so a fixture
        that repeats one exact line tests the wrong branch entirely."""
        lines = [f"[21:00:{i:02d}] [INFO] [aegis] worker 2: {chr(9670)} standing watch".encode()
                 for i in range(40)]
        out, stats = _run(lines)
        assert stats["throttled"] > 0, stats
        assert any(b"further repeated" in b for b in out), out[:6]

    def test_the_adjacency_rule_still_answers_first(self):
        """⭐ Order matters: its note says something stronger — that the repeats
        were consecutive — and that has to stay true where it applies."""
        same = b"[21:00:01] [INFO] byte identical"
        out, stats = _run([same] * 5)
        assert stats["collapsed"] == 4, stats
        assert any(b"then repeated" in b for b in out), out

    def test_the_byte_limit_is_still_honoured(self):
        out, stats = _run([_real(i) for i in range(500)], limit=400)
        assert stats["keptBytes"] <= 400 + 200, stats


# ── 3. the claim that was false ─────────────────────────────────────────────

class TestTheDocstringNoLongerOverclaims:

    def test_it_no_longer_says_adjacency_catches_the_pulse(self):
        """⛔ The sentence that stopped anyone looking: it named the aegis pulse
        as already handled. Pinned so the claim cannot come back."""
        assert "aegis\n        pulse, and whatever the next one" not in FILTER_SRC
        joined = " ".join(FILTER_SRC.split())
        assert "it catches the refresh flood above, our own aegis pulse" not in joined

    def test_the_measurement_is_recorded_beside_the_rule(self):
        joined = " ".join(FILTER_SRC.split())
        assert "21,671" in joined and "29,543" in joined, (
            "the numbers that justify the keyed rule are not written down"
        )

    def test_the_keyed_rule_uses_the_shared_cadence(self):
        """Not a hand-rolled schedule: the same widening bands the source-side
        suppressor uses, so the two halves of this wave cannot drift apart."""
        assert "logquiet.Suppressor()" in FILTER_SRC
