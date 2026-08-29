"""Phase 1 recorded "errored" for a phase that succeeded.

WHAT HAPPENED (2026-08-11 e2e)

The run shipped a 64 KB brief with `phases[1].status = "errored"` and
`durationSec: 0` in meta.json. `save_meta` rebuilds the phases array from the
recorded terminal statuses, and it ran BEFORE the "complete" was recorded — so
when phase 1 had surfaced a stall card earlier, `fail_phase`'s "errored" was
still the recorded value. It went to disk and was never rewritten, while
Firestore (written afterwards) said complete. The two disagreed about the same
phase, and the file is the one the resume path reads.

⛔ THIS FILE WAS `test_share_links_0811.py` UNTIL 2026-08-28. The other fourteen
tests in it guarded the P2 platform share-link gate — the host literals that had
rotted, the shared `_is_public_share_url` authority, the two extractors that
delegated to it. Stretch 6.6B removed that whole step from Phase 2 (2.2 minutes
and 21.7 CUA calls a run for a link nothing gated on), so the subject of those
tests no longer exists. This one never was about share links: it is about the
order of two writes in Phase 1, and it is the only reason the file survives.
Renamed rather than left standing, because a file called
`test_share_links_0811` holding no share-link test is the exact stale signal the
wave that emptied it exists to remove.
"""

import inspect
import re

import research
from conftest import code_only


# ── the phase that succeeded but was recorded as errored ────────────────────

def test_the_phase_status_is_recorded_before_the_file_that_reads_it():
    """⭐ 2026-08-11: the run shipped a 64 KB brief with
    `phases[1].status = "errored"` and `durationSec: 0` in meta.json.

    `save_meta` rebuilds the phases array from the recorded terminal statuses.
    It used to run BEFORE the "complete" was recorded, so when phase 1 had
    surfaced a stall card earlier, `fail_phase`'s "errored" was still the
    recorded value — it was written to disk and never rewritten, while
    Firestore (written afterwards) said complete."""
    src = code_only(inspect.getsource(research.run_pipeline))
    marker = 'save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())'
    record = '_write_phase_terminal_status(1, "complete")'
    # ⭐ EVERY phase-1 save_meta, not the first one found. The first version of
    # this test checked only `src.index(marker)` and so tested one of the two
    # branches — the other (brief supplied by file) had the identical bug and
    # would have shipped unfixed.
    saves = [m.start() for m in re.finditer(re.escape(marker), src)]
    assert len(saves) >= 2, f"expected both phase-1 save_meta branches, found {len(saves)}"
    for save_at in saves:
        before = src[:save_at]
        assert record in before, (
            "the terminal status must be recorded BEFORE save_meta rebuilds the "
            "phases array, or a phase that recovered stays 'errored' on disk"
        )
        # …and recorded in THIS branch, not merely somewhere earlier in the file
        assert save_at - before.rindex(record) < 900, (
            "the status record must belong to this branch's completion block"
        )
