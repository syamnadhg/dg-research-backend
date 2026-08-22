"""Wave 4: a filtered tail says what it removed — all three ways, and under budget.

⭐⭐ MEASURED FIRST, on this machine's own frozen logs, which are the bytes a real
support bundle carries (2026-08-22):

    backend.log      dropped 621,067 · collapsed      4 · throttled 48,630
    backend-2.log    dropped 627,284 · collapsed      0 · throttled 24,386
    backend.err.log  dropped       0 · collapsed  3,905 · throttled  4,750

`backend-2.log` shipped a header reading "0 consecutive duplicate lines
collapsed" and nothing else. True, and the reason it misleads: 24,386 lines had
been removed by the rule the header does not mention, so the single number the
reader was handed was the only one that was zero.

⛔⛔ AND THE GATE WAS SHORT THE SAME RULE. `_build_log_bundle` attached the header
only when `dropped or collapsed` — so a file whose ONLY filtering was the keyed
rule shipped a filtered tail with no admission anywhere in it.

⛔⛔ THE BUDGET WAS EXEMT FROM THE WHOLE CONTRACT. The keyed rule promises that a
held repeat is counted, never discarded. The remainder line that keeps that
promise ran only when the scan finished naturally, and a 44 MB log does not
finish naturally — it hits the byte budget. Measured on the real `backend.log` at
a 200 KB budget: 6,286 repeats held, none reported. And emitting it there is not
enough on its own — the line is appended at the OLDEST end, which is exactly
where the byte trim starts eating, so the line reporting what the budget cost was
the first thing the budget removed.

⭐ FOUND WHILE MEASURING, not asked for: the orphan sweep knew one of the two
anchored markers. At budgets of 1500 / 2500 / 4000 bytes over a heartbeat
fixture the tail's FIRST line came back as
`[bundle] ^ this message occurred 14 more times nearby`, sitting above an
unrelated real event and attributing a heartbeat's repeat count to it — the
fabricated count that sweep exists to prevent, in the marker it did not know.

Run: pytest tests/test_bundle_tail_honesty_0822.py -v
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


PROBE = b'127.0.0.1:1 - "GET /api/health HTTP/1.1" 200 OK'


def _hb(i: int) -> bytes:
    """The heartbeat exactly as the frozen logs carry it: its own timestamp, and
    a glyph that alternates — so no two copies are byte-identical AND no two in a
    row are even the same message. Only the keyed rule can see it."""
    glyph = "◆" if i % 2 == 0 else "◇"
    return f"[21:{i // 60:02d}:{i % 60:02d}] [INFO] [aegis] worker 2: {glyph} standing watch".encode()


def _real(i: int) -> bytes:
    return f"[21:{i // 60:02d}:{i % 60:02d}] [INFO] real event {i:04d} with some padding".encode()


def _filter(lines, limit=10 ** 9):
    stats: dict = {}
    return research._filter_tail_lines(lines, limit=limit, stats=stats), stats


# ── the counts a body carries, read back with the templates that wrote them ──

_KEYED_COUNT = re.compile(re.escape(research._TAIL_KEYED_NOTE_PREFIX) + rb"(\d+)")
_REMAINDER_COUNT = re.compile(
    re.escape(research._TAIL_KEYED_TAIL_PREFIX) + rb"(\d+)")


def _throttled_reported(lines) -> int:
    """Every keyed repeat the BODY accounts for: the ones that rode out on a
    later copy, plus the remainder line for the ones that never met one."""
    total = 0
    for line in lines:
        for pat in (_KEYED_COUNT, _REMAINDER_COUNT):
            m = pat.match(line)
            if m:
                total += int(m.group(1))
    return total


# ══════════════════════════════════════════════════════════════════════════
#  1. the header names every kind of removal
# ══════════════════════════════════════════════════════════════════════════

class TestTheHeaderCountsAllThreeKinds:

    def test_every_removal_kind_appears_with_its_own_number(self):
        """⛔ DISTINCT NUMBERS ON PURPOSE. Three counts and three sentences, so a
        header that reads the wrong field — or reuses one number for two kinds —
        fails here instead of shipping."""
        stats = {"dropped": 11, "collapsed": 22, "throttled": 33,
                 "scannedBytes": 44, "reachedStart": True}
        head = research._tail_filter_header("backend-2.log", stats).decode()
        assert "11" in head and "22" in head and "33" in head

    @pytest.mark.parametrize("kind", research._TAIL_REMOVAL_KINDS)
    def test_no_kind_can_be_added_without_a_sentence_to_report_it(self, kind):
        """⭐ THE DRIFT GUARD. `_TAIL_REMOVAL_KINDS` is what the gate reads, so a
        fourth rule added there without a fourth sentence would flip the gate on
        and still say nothing. Each kind is given a value nothing else has."""
        stats = {k: 0 for k in research._TAIL_REMOVAL_KINDS}
        stats[kind] = 987654
        stats.update(scannedBytes=1, reachedStart=True)
        assert "987654" in research._tail_filter_header("x.log", stats).decode(), (
            f"the header reports nothing for {kind!r}")

    def test_the_keyed_count_is_the_one_that_used_to_be_missing(self):
        """The exact `backend-2.log` shape: nothing adjacent, 24,386 keyed."""
        stats = {"dropped": 627284, "collapsed": 0, "throttled": 24386,
                 "scannedBytes": 40920568, "reachedStart": True}
        head = research._tail_filter_header("backend-2.log", stats).decode()
        assert "24386" in head, (
            "the header still stops at the two rules that removed the least — "
            "this file's only real filtering is unreported")

    def test_the_header_says_which_window_its_numbers_describe(self):
        """⛔ It used to say the collapsed lines were counted "into the counts
        marked below", which is false once the budget trims: the counts are over
        the whole SCAN and the body only marks what fitted. A reader who adds up
        the notes and finds a shortfall must be told why."""
        stats = {"dropped": 1, "collapsed": 1, "throttled": 1,
                 "scannedBytes": 9, "reachedStart": True}
        head = research._tail_filter_header("x.log", stats).decode()
        assert "whole scan" in head
        assert "into the counts marked below" not in head

    def test_a_truncated_scan_still_says_so(self):
        """Pre-existing contract, re-pinned across the rewording."""
        stats = {"dropped": 0, "collapsed": 0, "throttled": 5,
                 "scannedBytes": 9, "reachedStart": False}
        head = research._tail_filter_header("x.log", stats).decode()
        assert "did not reach the start of the file" in head


class TestTheGateReadsTheSameList:

    @pytest.mark.parametrize("kind", research._TAIL_REMOVAL_KINDS)
    def test_any_single_kind_makes_the_tail_a_filtered_one(self, kind):
        assert research._tail_removed_anything({kind: 1}) is True

    def test_a_tail_that_lost_nothing_gets_no_header(self):
        assert research._tail_removed_anything(
            {k: 0 for k in research._TAIL_REMOVAL_KINDS}) is False
        assert research._tail_removed_anything({}) is False

    def test_the_gate_and_the_header_cannot_disagree(self):
        """⛔ TWO LISTS IS THE BUG. The gate carried its own `dropped or
        collapsed` and the header carried its own two sentences, and both were
        short the same rule. One list now, read by both."""
        src = code_only_deep(research._build_log_bundle)
        assert "_tail_removed_anything(stats)" in src
        assert 'stats.get("collapsed")' not in src, (
            "the gate has grown its own list of removal kinds again")

    def test_a_bundle_whose_only_filtering_was_keyed_still_admits_it(self, tmp_path):
        """⛔⛔ THE GATE'S OWN DEFECT, end to end through the real builder. No
        health probes and nothing adjacent — only the rule the gate did not
        know — so this tail used to travel with no header at all."""
        root = research._logs_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / "backend.log").write_bytes(
            b"\n".join(_hb(i) for i in range(200)) + b"\n")
        out = research._build_log_bundle(tmp_path / "b.zip", support_code="ABCD2345")
        with zipfile.ZipFile(out["path"]) as zf:
            body = zf.read("system/backend.log")
            stats = json.loads(zf.read("collected.json"))["systemTailFilter"]
        assert stats["backend.log"]["dropped"] == 0
        assert stats["backend.log"]["collapsed"] == 0
        assert stats["backend.log"]["throttled"] > 0
        assert body.startswith(b"[bundle] backend.log:"), (
            "a filtered tail travelled with no admission that it was filtered")

    def test_the_header_numbers_are_the_manifest_numbers(self, tmp_path):
        """⭐ THE ACCEPTANCE TEST FOR THIS ITEM: the totals in the file match the
        totals in the archive index. A reader who opens the tail and a reader who
        opens `collected.json` must not be told two different stories."""
        root = research._logs_root()
        root.mkdir(parents=True, exist_ok=True)
        lines = []
        for i in range(300):
            lines.append(_hb(i))
            lines.append(PROBE)
            if i % 40 == 0:
                lines.extend([_real(i)] * 3)
        (root / "backend.log").write_bytes(b"\n".join(lines) + b"\n")
        out = research._build_log_bundle(tmp_path / "b.zip", support_code="ABCD2345")
        with zipfile.ZipFile(out["path"]) as zf:
            head = zf.read("system/backend.log").split(b"\n", 1)[0].decode()
            stats = json.loads(zf.read("collected.json"))["systemTailFilter"]
        recorded = stats["backend.log"]
        for kind in research._TAIL_REMOVAL_KINDS:
            assert recorded[kind] > 0, f"the fixture exercises no {kind}"
            assert str(recorded[kind]) in head, (
                f"{kind}={recorded[kind]} is in the index and not in the header")


# ══════════════════════════════════════════════════════════════════════════
#  2. the remainder line survives the budget
# ══════════════════════════════════════════════════════════════════════════

class TestTheRemainderReachesTheCutoff:

    def test_the_body_accounts_for_every_held_repeat_when_the_scan_ends_naturally(self):
        out, stats = _filter([_hb(i) for i in range(120)])
        assert stats["throttled"] > 0
        assert _throttled_reported(out) == stats["throttled"]

    def test_the_body_accounts_for_them_at_the_budget_cutoff_too(self):
        """⛔⛔ THE DEFECT. The early return skipped the remainder entirely, and
        the cutoff is the exit a real 40 MB log takes. Measured on this machine's
        `backend.log` at a 200 KB budget: 6,286 held, 0 reported."""
        lines = []
        for i in range(400):
            lines.append(_hb(i))
            lines.append(_real(i))
        out, stats = _filter(lines, limit=2000)
        assert stats["keptBytes"] >= 2000, "the fixture never reached the cutoff"
        assert stats["throttled"] > 0
        assert _throttled_reported(out) == stats["throttled"]

    def test_the_remainder_line_is_written_by_one_author(self):
        """⛔ Two spellings of the same accounting line is how one exit keeps a
        promise the other quietly drops — which is exactly what happened. Both
        exits are pinned WHOLE, so a mutation that leaves the call in place and
        moves it after the return cannot pass."""
        src = code_only_deep(research._filter_tail_lines)
        assert src.count("_TAIL_KEYED_TAIL_NOTE %") == 1
        assert ('            _remainder()\n'
                '            stats["keptBytes"] = kept\n'
                '            return out') in src, "the budget cutoff exit"
        assert ('    _remainder()\n'
                '    stats["keptBytes"] = kept\n'
                '    return out') in src, "the natural end-of-scan exit"

    def test_the_remainder_survives_the_size_trim(self, tmp_path):
        """⛔⛔ EMITTING IT IS NOT ENOUGH. `_filter_tail_lines` appends it LAST,
        i.e. at the oldest end, and the byte trim pops from that end — so the one
        line reporting what the budget cost was the first thing the budget
        removed, and the fix above would have delivered nothing.

        ⭐ The filter is run over the SAME lines first, so the expectation comes
        from what the filter actually produced at that budget rather than from a
        guess about which budgets are interesting."""
        lines = [_hb(i) for i in range(400)]
        p = tmp_path / "hb.log"
        p.write_bytes(b"\n".join(lines) + b"\n")
        checked = 0
        for limit in (600, 1200, 2500, 5000, 9000, 20000):
            pure = research._filter_tail_lines(reversed(lines), limit, {})
            if not any(x.startswith(research._TAIL_KEYED_TAIL_PREFIX)
                       for x in pure):
                continue          # the filter itself ended holding nothing
            checked += 1
            out = research._tail_bytes(p, limit=limit)
            assert _REMAINDER_COUNT.search(out), (
                f"limit={limit}: the filter reported the repeats it was still "
                f"holding and the byte trim ate the line that said so")
        assert checked >= 2, "the sweep never exercised a tail with a remainder"

    @pytest.mark.parametrize("limit", [2000, 10 ** 9])
    def test_kept_bytes_counts_every_line_the_filter_returned(self, limit):
        """⛔ FOUND BY MUTATION. `keptBytes` is reported to the reader in
        `collected.json`, so a line the filter emits without charging itself for
        it makes that number smaller than the tail it describes — a wrong number
        in the archive index, in the wave about the archive telling the truth.
        The remainder line is the one that was free."""
        lines = []
        for i in range(400):
            lines.append(_hb(i))
            lines.append(_real(i))
        out, stats = _filter(lines, limit=limit)
        assert stats["keptBytes"] == sum(len(x) + 1 for x in out)

    def test_the_remainder_line_costs_the_log_content_nothing(self, tmp_path):
        """⛔ FOUND BY MUTATION. The note is detached before the trim, so its
        bytes have to come off the running total too — otherwise the budget is
        charged for it twice and the trim throws away log lines that had room.

        ⭐ A SWEEP, not one budget, and that is not belt-and-braces: the orphan
        sweep legitimately removes bytes after the size trim, so at any single
        budget the content can sit well under the limit for an honest reason. The
        claim that separates the two is that SOME budget spends itself down to
        the last byte — measured, the best case here is exact. Charge the note to
        the log's share and every budget in the sweep falls at least a note-width
        short, so the minimum is what tells them apart."""
        lines = [_hb(i) for i in range(60)]
        assert len({len(x) for x in lines}) == 1, "the fixture is not uniform"
        p = tmp_path / "hb.log"
        p.write_bytes(b"\n".join(lines) + b"\n")
        deficits = []
        note_width = 0
        for limit in range(600, 1200):
            body = research._tail_bytes(p, limit=limit).splitlines()
            note = [x for x in body
                    if x.startswith(research._TAIL_KEYED_TAIL_PREFIX)]
            if not note:
                continue
            note_width = len(note[0]) + 1
            content = sum(len(x) + 1 for x in body if x not in note)
            assert content <= limit, f"limit={limit}: over budget"
            deficits.append(limit - content)
        assert len(deficits) > 50, "the sweep never produced a tail with a remainder"
        assert min(deficits) < note_width, (
            f"no budget in the sweep came within {note_width} bytes of being "
            f"spent, which is the remainder line's own width — it is being "
            f"charged to the log content's share of the budget")

    def test_the_body_never_claims_more_repeats_than_were_held(self, tmp_path):
        """⭐ THE HONEST INVARIANT FOR A TRIMMED TAIL, and the reason it is `<=`
        rather than `==`: the trim removes ordinary log lines too, and a window
        cannot account for what fell outside it. What it must never do is
        over-report — the header states the totals for the whole scan and says so
        in as many words."""
        lines = []
        for i in range(400):
            lines.append(_hb(i))
            lines.append(_real(i))
        p = tmp_path / "mixed.log"
        p.write_bytes(b"\n".join(lines) + b"\n")
        for limit in (600, 1200, 2500, 5000, 9000, 20000):
            stats: dict = {}
            out = research._tail_bytes(p, limit=limit, stats=stats)
            assert _throttled_reported(out.splitlines()) <= stats["throttled"], (
                f"limit={limit}: the body claims more collapsed repeats than the "
                f"scan ever held")

    def test_the_remainder_line_can_be_told_apart_from_the_other_two_markers(self):
        """⭐ THE PROPERTY THE DETACH RESTS ON. The two anchored markers both open
        `[bundle] ^ `, so a prefix derived the usual way would be `[bundle] ` and
        would match all three — `_tail_bytes` would then rescue whichever marker
        happened to be last and leave it dangling."""
        rem = research._TAIL_KEYED_TAIL_PREFIX
        assert research._TAIL_KEYED_TAIL_NOTE.startswith(rem)
        for anchored in research._TAIL_ANCHORED_NOTE_PREFIXES:
            assert not anchored.startswith(rem)
            assert not rem.startswith(anchored)

    def test_the_remainder_prefix_has_one_spelling(self):
        src = inspect.getsource(research)
        assert src.count("_TAIL_KEYED_TAIL_PREFIX = ") == 1
        assert "_TAIL_KEYED_TAIL_PREFIX +" in src, (
            "the note is spelled out again instead of being built from the "
            "prefix, so the two can drift and the detach stops matching")


# ══════════════════════════════════════════════════════════════════════════
#  3. no marker is left describing a line that is gone
# ══════════════════════════════════════════════════════════════════════════

class TestNoOrphanedMarkerOfAnyKind:

    def test_both_anchored_prefixes_are_derived_from_their_templates(self):
        assert research._TAIL_REPEAT_NOTE.startswith(
            research._TAIL_REPEAT_NOTE_PREFIX)
        assert research._TAIL_KEYED_NOTE.startswith(
            research._TAIL_KEYED_NOTE_PREFIX)
        src = inspect.getsource(research)
        assert '_TAIL_KEYED_NOTE_PREFIX = _TAIL_KEYED_NOTE.split(b"%")[0]' in src
        assert set(research._TAIL_ANCHORED_NOTE_PREFIXES) == {
            research._TAIL_REPEAT_NOTE_PREFIX, research._TAIL_KEYED_NOTE_PREFIX}

    def test_a_keyed_marker_never_survives_the_line_it_describes(self, tmp_path):
        """⛔⛔ MEASURED REACHABLE BEFORE IT WAS FIXED — at 1500, 2500 and 4000
        bytes over this exact shape the tail's first line was
        `[bundle] ^ this message occurred 14 more times nearby`, above an
        unrelated real event.

        ⭐ EXHAUSTIVE, and the sibling test for the adjacency marker records why:
        a sampled sweep steps over the narrow band where an orphan can appear and
        becomes a guard that cannot fire. `seen_marker` proves the sweep reached
        the interesting region at all.

        ⭐ THIRTY heartbeats, and the number is measured rather than chosen: the
        keyed rule holds copies back at a widening cadence, so at 12 repeats it
        has emitted no marker at all and at 16 it emits only the remainder. The
        first `^ this message occurred N more times nearby` appears at 30."""
        p = tmp_path / "orphan.log"
        p.write_bytes(b"\n".join(
            [_hb(i) for i in range(30)] + [_real(i) for i in range(3)]) + b"\n")
        size = p.stat().st_size
        seen_marker = False
        for limit in range(1, size + 160):
            out = research._tail_bytes(p, limit=limit)
            for i, line in enumerate(out.splitlines()):
                if line.startswith(research._TAIL_KEYED_NOTE_PREFIX):
                    seen_marker = True
                    assert i > 0, (
                        f"limit={limit}: a keyed marker is the FIRST line, so its "
                        f"count is attached to a line that is no longer here")
        assert seen_marker, (
            "no limit in the sweep produced a keyed marker at all, so this test "
            "proved nothing about orphaning")

    def test_the_sweep_takes_the_whole_tuple_not_one_prefix(self):
        src = code_only_deep(research._tail_bytes)
        assert "startswith(_TAIL_ANCHORED_NOTE_PREFIXES)" in src
        assert "startswith(_TAIL_REPEAT_NOTE_PREFIX)" not in src, (
            "the sweep is back to knowing one of the two anchored markers")


# ══════════════════════════════════════════════════════════════════════════
#  4. the counters exist before anything is scanned
# ══════════════════════════════════════════════════════════════════════════

def test_an_unreadable_file_still_answers_every_count(tmp_path):
    """⛔ The header reads all three from `stats`. A file that returns early —
    missing, empty, unreadable — must still leave numbers behind, or building a
    bundle raises inside the one feature a broken machine has left."""
    stats: dict = {}
    assert research._tail_bytes(tmp_path / "nope.log", stats=stats) == b""
    for kind in research._TAIL_REMOVAL_KINDS:
        assert stats[kind] == 0, kind


def test_the_seeded_counters_come_from_the_shared_list(self=None):
    src = code_only_deep(research._tail_bytes)
    assert "for _kind in _TAIL_REMOVAL_KINDS" in src
    assert 'stats.setdefault("collapsed", 0)' not in src, (
        "the seeds are a hand-written list again, so a fourth kind reaches the "
        "header as a KeyError")
