"""Wave 8 step C — a bundle scoped to the runs one person actually picked.

⛔⛔ THE DIRECTION THIS MUST NEVER FAIL IN. Every ambiguity here resolves toward
collecting LESS, because the failure that matters is a machine shipping material
nobody agreed to send. The collector's own docstring already said so before this
wave — "falling back would resolve every malformed request toward MORE collection
than was agreed to" — and this file is that sentence turned into assertions.

⭐⭐ THE ONE THAT DECIDES THE WAVE: attribution fails CLOSED. Not one run folder
in the field records a submitter — the field landed 2026-08-21 and the shipped
0.1.13 wheel contains zero occurrences of it — so "unknown submitter" is the
COMMON case, not an edge. Treating unknown as "matches whoever asked" would give
a sharer who ticked two runs the whole machine.

⛔ AND THE MACHINE-LEVEL MATERIAL IS NOT A SMALLER VERSION OF THE RUNS. Measured
on this machine: `backend.log` carries 18 distinct research ids and 15 topics in
queue paths, against 5 run folders on disk. There is no filter that makes those
tails honest inside a one-person bundle — only omission.
"""
import json
import zipfile
from pathlib import Path

import pytest

import research


def _row(name, uid=None, source="queue", epoch=1_000.0):
    return {"name": name, "startedEpoch": epoch, "submitterUid": uid,
            "submitterSource": source, "dir": Path("/tmp") / name}


def _sel(rows, picked, **kw):
    got, report = research._pick_selected_runs(rows, picked, **kw)
    return [r["name"] for r in got], report


# ══ 1. the selection policy, pure ══════════════════════════════════════
def test_a_selection_takes_exactly_what_was_ticked():
    rows = [_row("a", "U1", epoch=3), _row("b", "U1", epoch=2), _row("c", "U1", epoch=1)]
    names, report = _sel(rows, ["a", "c"])
    assert names == ["a", "c"]
    assert report["runsRequested"] == 2
    assert report["runsNotOnDisk"] == []
    assert report["runsNotAttributed"] == 0


def test_the_result_is_newest_first_whatever_order_was_ticked():
    """The archive's cap protects position 0, so the order the person clicked in
    must not decide which run survives a size trim."""
    rows = [_row("old", "U1", epoch=1), _row("new", "U1", epoch=9)]
    names, _ = _sel(rows, ["old", "new"])
    assert names == ["new", "old"]


def test_a_name_that_is_not_on_disk_is_reported_not_guessed():
    """⛔ The owner's decision was that runs whose logs are gone are HIDDEN from
    the list. A name that arrives anyway is a stale page, not an attack — and it
    must produce a stated absence rather than a silently shorter bundle."""
    rows = [_row("a", "U1")]
    names, report = _sel(rows, ["a", "vanished"])
    assert names == ["a"]
    assert report["runsNotOnDisk"] == ["vanished"]


def test_a_duplicate_tick_is_counted_once():
    rows = [_row("a", "U1")]
    names, report = _sel(rows, ["a", "a", "a"])
    assert names == ["a"]
    assert report["runsRequested"] == 1


def test_an_empty_selection_collects_no_runs_at_all():
    """⭐ NOT "no selection". An owner who ticks nothing is asking for the
    machine-level bundle — the pairing-failure case, which is exactly when there
    are no runs to tick. `None` means the old behaviour; `[]` means none."""
    rows = [_row("a", "U1")]
    names, report = _sel(rows, [])
    assert names == []
    assert report["runsRequested"] == 0


# ══ 2. attribution fails closed ════════════════════════════════════════
def test_a_run_someone_else_fired_is_refused():
    rows = [_row("mine", "U1"), _row("theirs", "U2")]
    names, report = _sel(rows, ["mine", "theirs"], requester_uid="U1")
    assert names == ["mine"]
    assert report["runsNotAttributed"] == 1


def test_an_unattributed_run_matches_NOBODY():
    """⛔⛔ THE ONE THAT DECIDES THE WAVE. Every run folder in the field today has
    no submitter recorded, so this is the common case. If it matched the
    requester, a sharer ticking two runs would collect the machine."""
    rows = [_row("legacy", None, source="unclaimed"),
            _row("disputed", None, source="disputed")]
    names, report = _sel(rows, ["legacy", "disputed"], requester_uid="U1")
    assert names == []
    assert report["runsNotAttributed"] == 2


def test_an_unattributed_run_is_not_matched_by_an_empty_requester_either():
    """⛔ `""` is not `None`. A caller that passes a blank uid — a missing claim,
    a stripped field — must not accidentally match every unattributed run by
    comparing None-to-empty in some looser way."""
    rows = [_row("legacy", None, source="unclaimed")]
    names, _ = _sel(rows, ["legacy"], requester_uid="")
    assert names == []


def test_no_requester_means_no_attribution_filter():
    """⭐ THE OWNER AT THE MACHINE. They already hold every one of these files on
    their own disk, so filtering grants nothing — and it would hide the
    unattributed runs from the only person who can act on them."""
    rows = [_row("mine", "U1"), _row("theirs", "U2"), _row("legacy", None)]
    names, _ = _sel(rows, ["mine", "theirs", "legacy"])
    assert names == ["mine", "theirs", "legacy"]


def test_the_refused_runs_are_counted_but_never_named():
    """⚠ The count tells support a selection was narrowed. Naming the folders
    would tell the REQUESTER which runs on this machine are somebody else's."""
    rows = [_row("theirs", "U2")]
    _, report = _sel(rows, ["theirs"], requester_uid="U1")
    assert report["runsNotAttributed"] == 1
    assert "theirs" not in json.dumps(report)


# ══ 3. the count bound survives, and says what it took ═════════════════
def test_the_signed_off_ceiling_still_applies_to_a_selection():
    rows = [_row(f"r{i}", "U1", epoch=i) for i in range(10)]
    names, report = _sel(rows, [f"r{i}" for i in range(10)],
                         requester_uid="U1", max_runs=3)
    assert names == ["r9", "r8", "r7"]
    assert report["runsOverCap"] == ["r6", "r5", "r4", "r3", "r2", "r1", "r0"]


def test_what_the_cap_removed_is_reported_not_dropped_quietly():
    rows = [_row("a", "U1", epoch=2), _row("b", "U1", epoch=1)]
    _, report = _sel(rows, ["a", "b"], requester_uid="U1", max_runs=1)
    assert report["runsOverCap"] == ["b"]


def test_no_age_bound_is_applied_to_an_explicit_pick(monkeypatch):
    """⛔ DELIBERATE. On-disk retention and the bundle's age bound are the same
    30 days, so anything still on disk is inside the window by construction —
    re-applying it could only ever drop a run the person explicitly ticked, and
    it would do it silently. A very old epoch survives here."""
    rows = [_row("ancient", "U1", epoch=1.0)]
    names, _ = _sel(rows, ["ancient"], requester_uid="U1")
    assert names == ["ancient"]


# ══ 4. through the real builder ════════════════════════════════════════
@pytest.fixture()
def machine(tmp_path, monkeypatch):
    """A whole fake `~/.super-research` with two runs, a session and a tail."""
    root = tmp_path / "logs"
    (root / "runs").mkdir(parents=True)
    (root / "sessions").mkdir(parents=True)
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    monkeypatch.setattr(research, "_runs_log_root", lambda: root / "runs")
    monkeypatch.setattr(research, "_sessions_log_root", lambda: root / "sessions")

    import time as _t
    now = _t.time()
    for name, uid in (("alice_20260824T000001", "U_ALICE"),
                      ("bob_20260824T000002", "U_BOB")):
        folder = root / "runs" / name
        folder.mkdir()
        (folder / "meta.json").write_text(json.dumps({
            "schema": 1, "status": "complete", "researchId": name.split("_")[0],
            "startedUtc": "2026-08-24T00:00:01Z", "submitterUid": uid,
            "submitterSource": "queue",
        }), encoding="utf-8")
        (folder / "run.log").write_text(f"log for {name}\n", encoding="utf-8")
        import os
        os.utime(folder / "meta.json", (now, now))
    (root / "sessions" / "pair_20260824T000000.log").write_text(
        "pairing session\n", encoding="utf-8")
    (root / "backend.log").write_text("machine tail line\n", encoding="utf-8")
    return root


def _members(dest):
    with zipfile.ZipFile(dest) as zf:
        return zf.namelist()


def test_a_sharer_bundle_carries_only_their_own_run(machine, tmp_path):
    dest = tmp_path / "sharer.zip"
    summary = research._build_log_bundle(
        dest, support_code="ABCD2345",
        only_runs=["alice_20260824T000001", "bob_20260824T000002"],
        requester_uid="U_ALICE", include_machine=False)
    names = _members(dest)
    assert any(n.startswith("runs/alice_") for n in names)
    assert not any(n.startswith("runs/bob_") for n in names), \
        "another person's run reached a scoped bundle"
    assert not any(n.startswith("sessions/") for n in names)
    assert not any(n.startswith("system/") for n in names)
    assert summary["runsNotAttributed"] == 1
    assert summary["machineIncluded"] is False


def test_the_owner_bundle_still_carries_the_machine(machine, tmp_path):
    """⭐ THE ACCEPT-POLARITY PIN. An omission that omits everything ships a
    bundle with no evidence in it, and every assertion above still passes."""
    dest = tmp_path / "owner.zip"
    research._build_log_bundle(dest, support_code="ABCD2345")
    names = _members(dest)
    assert any(n.startswith("sessions/") for n in names)
    assert any(n.startswith("system/") for n in names)
    assert any(n.startswith("runs/alice_") for n in names)
    assert any(n.startswith("runs/bob_") for n in names)


def test_an_owner_who_ticks_nothing_still_gets_the_machine(machine, tmp_path):
    """⭐ THE PAIRING-FAILURE CASE, and the founding incident's shape: no run was
    ever produced, so the whole evidence is a session and a tail."""
    dest = tmp_path / "none.zip"
    summary = research._build_log_bundle(
        dest, support_code="ABCD2345", only_runs=[], include_machine=True)
    names = _members(dest)
    assert not any(n.startswith("runs/") for n in names)
    assert any(n.startswith("sessions/") for n in names)
    assert any(n.startswith("system/") for n in names)
    assert summary["runCount"] == 0


def test_the_builder_reports_the_selection_it_applied(machine, tmp_path):
    """⛔⛔ THE ACCEPTED-AND-IGNORED TRAP. Every existing stub for this function is
    `lambda dest, **k`, so a caller that drops the selection keyword is invisible
    to all of them and silently collects the newest thirty. The BUILDER says."""
    dest = tmp_path / "r.zip"
    summary = research._build_log_bundle(
        dest, support_code="ABCD2345", only_runs=["alice_20260824T000001"],
        requester_uid="U_ALICE", include_machine=False)
    assert summary["selectionApplied"] is True
    assert summary["requesterScoped"] is True
    assert summary["runsRequested"] == 1

    plain = research._build_log_bundle(tmp_path / "p.zip", support_code="ABCD2345")
    assert plain["selectionApplied"] is False
    assert plain["requesterScoped"] is False
    assert plain["machineIncluded"] is True
    assert "runsRequested" not in plain, (
        "a whole-machine bundle must not report a selection it never had")


def test_the_manifest_says_which_kind_of_bundle_this_is(machine, tmp_path):
    """A reader who cannot tell a scoped bundle from a whole-machine one reads a
    short archive as a broken machine."""
    dest = tmp_path / "r.zip"
    research._build_log_bundle(
        dest, support_code="ABCD2345", only_runs=["alice_20260824T000001"],
        requester_uid="U_ALICE", include_machine=False)
    with zipfile.ZipFile(dest) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        collected = json.loads(zf.read("collected.json").decode("utf-8"))
    assert manifest["selectionApplied"] is True
    assert manifest["machineIncluded"] is False
    assert collected["runsRequested"] == 1
    assert collected["machineIncluded"] is False


def test_a_bogus_folder_name_reaches_no_path(machine, tmp_path):
    """⛔ The caller's string is matched against scanned rows and never joined
    onto a path, so traversal is unrepresentable rather than defended against."""
    dest = tmp_path / "x.zip"
    summary = research._build_log_bundle(
        dest, support_code="ABCD2345",
        only_runs=["../../../../etc/passwd", "runs/../../secrets"],
        requester_uid="U_ALICE", include_machine=False)
    assert summary["runCount"] == 0
    assert len(summary["runsNotOnDisk"]) == 2
    assert not any(n.startswith("runs/") for n in _members(dest))


def test_the_default_call_is_byte_for_byte_the_old_behaviour(machine, tmp_path):
    """⛔ EVERY PRE-WAVE-8 CALLER STILL GOES THROUGH THIS FUNCTION. If the new
    keywords changed what they get, the terminal command and the device handler
    would both quietly start shipping something else."""
    dest = tmp_path / "d.zip"
    summary = research._build_log_bundle(dest, support_code="ABCD2345")
    assert summary["runCount"] == 2
    assert summary["sessionCount"] == 1
    assert summary["machineIncluded"] is True
