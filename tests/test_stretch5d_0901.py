"""Stretch 5D — the cleanup this process was never allowed to do.

⛔⛔ THE DEFECT, AND IT IS OLDER THAN THIS FILE. Two cascades — the startup stale
sweep and `delete_run` — walked five subcollections under a research document and
deleted every doc in each. Under Track D this process authenticates as a
SYNTHETIC DEVICE user, and `firestore.rules` gates `delete` on those five at
OWNER-ONLY. So four of the five came back `PERMISSION_DENIED` on every document,
every time, into a bare `except: pass` directly underneath. Only `commands` —
gated on `deviceMemberOf` — could ever land.

⭐⭐ AND THE CODE ALREADY SAID SO. The comment inside the loop read "the other
four + the doc are OWNER-ONLY in rules (synth user denied by design)". The
knowledge was written down at #720 and the loop kept running anyway, which is the
shape worth pinning against: not a missing insight, a correct insight sitting
above code that ignored it.

⛔ WHY REMOVING IT IS NOT A BEHAVIOUR CHANGE. Nothing that used to be deleted
stops being deleted, because nothing was. What goes is a walk over every document
in four collections to issue writes that could not land, plus a log line claiming
a cascade had happened.

▶ WHO DELETES THEM, honestly stated: the FRONT-END cascades, which run as the
owner. `pipeline_events` additionally gained a 30-day TTL on 2026-09-01.
⚠ `documents`, `audios` and `messages` have NO TTL — the front end is their only
reaper, which was already true and is unchanged by this.
"""
from __future__ import annotations

import inspect
import re

import research


# ── the two cascades ────────────────────────────────────────────────────────

_DENIED = ("documents", "audios", "messages", "pipeline_events")


def _cascade_bodies() -> list[str]:
    """The two loops, sliced from module source by their own heal labels.

    ⛔ SLICED TO THE LABEL, not to a byte count. A fixed window has silently
    fallen short of a grown function three times in this repo, and a guard that
    reaches past its own subject stops meaning anything.
    """
    src = inspect.getsource(research)
    out = []
    # ⛔⛔ THE SLICE ENDS AT THE ENCLOSING BLOCK, NOT AT THE DELETE — and the first
    # draft ended at the heal label, which is BEFORE anything a regression would
    # add. Every guard below then read a window that stopped short of the code it
    # was guarding: re-adding an owner-only sweep AFTER the surviving commands
    # delete left all of them green. A window that cannot reach its own subject
    # is the exact failure this repo keeps relearning, and cross-verification
    # caught it here rather than a person finding it months later.
    bounds = (
        ("cascade-sweep cmd delete", "ref = _firebase_db", "# Nuke local queue dir."),
        ("delete_run cmd delete", "research_ref = ", 'log(f"[delete_run] cleared queued commands for "'),
    )
    for label, start_at, end_at in bounds:
        at = src.index(f'what="{label}"')
        start = src.rindex(start_at, 0, at)
        end = src.index(end_at, at)
        assert end > at, label
        out.append(src[start:end])
    assert len(out) == 2
    return out


def test_the_slice_actually_reaches_past_the_surviving_delete():
    """⛔ THE GUARD ON THE GUARD. If the window stopped at the heal call again,
    every assertion in this file would be measuring a region no regression can
    land in. Proved by content, not by length: the slice must contain the delete
    AND the code that follows it."""
    sweep, delete_run = _cascade_bodies()
    for body in (sweep, delete_run):
        assert "sd.reference.delete()" in body
    # Each window must extend past its own delete by real code.
    assert sweep.index("sd.reference.delete()") < len(sweep) - 40, sweep[-120:]
    assert delete_run.index("sd.reference.delete()") < len(delete_run) - 40


def test_neither_cascade_enumerates_a_collection_it_cannot_delete_from():
    """⛔⛔ THE FIX. Four collection names must not appear as delete targets in
    either cascade — the deletes were refused on every document."""
    for body in _cascade_bodies():
        for name in _DENIED:
            assert f'"{name}"' not in body, (
                f"{name} is back in a cascade that cannot delete from it: the rule "
                f"is owner-only and this process is a synthetic device user, so "
                f"every delete returns PERMISSION_DENIED into a bare except."
            )


def test_both_cascades_still_clear_the_one_collection_they_CAN():
    """⛔ OVER-CORRECTION GUARD, and it is the one that matters. `commands` IS
    deletable — it is gated on `deviceMemberOf`, not on ownership — and it is
    queued work for a run being torn down. Deleting the dead four by deleting the
    whole loop would strand real commands, which is a worse bug than the no-op."""
    for body in _cascade_bodies():
        assert '.collection("commands")' in body, (
            "the commands sweep went with the dead ones — it is the only one that "
            "ever worked."
        )


def test_the_research_doc_itself_is_no_longer_deleted_by_either_cascade():
    """The document delete is owner-only too, so it was the fifth no-op."""
    src = inspect.getsource(research)
    for label in ("cascade-sweep cmd delete", "delete_run cmd delete"):
        at = src.index(f'what="{label}"')
        after = src[at:at + 1200]
        assert "ref.delete()" not in after.replace("sd.reference.delete()", "")


def test_the_delete_run_log_line_no_longer_claims_a_cascade():
    """⛔ THE REAL COST OF THE DEAD LOOP was this sentence. It said "cascaded
    Firestore for …" after doing none of it — so the one place a person would
    look to check whether the cleanup ran told them it had."""
    # ⛔ CHECKED IN THE CODE, NOT THE FILE. `inspect.getsource` returns comments
    # too, and the note explaining this removal QUOTES the old sentence — a plain
    # `not in src` therefore failed against the very comment documenting the fix.
    # The mirror of the frontend trap where `srcCode` blanks comments and makes a
    # comment assertion vacuous: both are "the guard did not read what it meant".
    code = _code_only()
    assert "cascaded Firestore for" not in code
    assert "cleared queued commands for" in code
    # And it names who DOES own the rest, or the removal just reads as a gap.
    assert "owner-only rule" in code


def _code_only() -> str:
    """Module source with comment lines removed.

    ⛔ `inspect.getsource` returns COMMENTS TOO, so a guard asserting a phrase is
    present passes when the phrase only appears in the note explaining the fix —
    and a guard asserting one is ABSENT fails against that same note. Both
    directions are wrong for the same reason: the guard did not read what it
    meant. The frontend has the mirror-image trap, where `srcCode` blanks
    comments and makes a comment assertion vacuous.
    """
    return "\n".join(ln for ln in inspect.getsource(research).splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_denied_four_are_named_in_the_LOG_LINE_the_operator_reads():
    """⭐ The four names must survive in the log line explaining who deletes them
    — a removal with no forwarding address is how the next person re-adds it.
    ⛔ Asserted against CODE, not the file: the comment above the removal also
    names all four, so a raw-source check passed while the operator-facing
    sentence could be shortened away entirely."""
    assert "documents/audios/messages/pipeline_events are the app's" in _code_only()
    assert "owner-only rule" in _code_only()


# ── the property underneath, stated once ────────────────────────────────────

def test_no_bare_except_pass_hides_a_delete_in_the_trimmed_cascades():
    """⛔ The bare `except: pass` is what made four years of denials invisible.
    Whatever remains in these two loops may still swallow — a cleanup must not
    break a teardown — but it may only wrap the ONE call that can succeed, so
    there is nothing left for it to hide."""
    for body in _cascade_bodies():
        # One stream, one delete, inside each cascade.
        assert len(re.findall(r"\.stream\(\)", body)) == 1, body
        # ⛔ EVERY delete must be INSIDE the heal lambda. Counting occurrences
        # would have banned the surviving call too — the wrapped one contains the
        # same text — so the property is "no occurrence that is not preceded by
        # the lambda", which is the thing actually being claimed.
        deletes = re.findall(r"(.{18})sd\.reference\.delete\(\)", body)
        assert deletes, "the commands delete vanished entirely"
        for before in deletes:
            assert "lambda sd=sd: " in before, (
                "an UNWRAPPED delete is back — every delete left here goes through "
                f"the heal wrapper, which is what makes a denial visible: {before!r}"
            )
