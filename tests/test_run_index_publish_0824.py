"""Wave 8 step D — the machine tells each person which of their runs it holds.

⛔⛔ WHY THIS CANNOT BE DERIVED IN THE APP. Local retention is 60 runs / 30 days;
the research documents outlive it, and a machine that has been reset keeps none
of them. The owner decided (2026-08-23) that a run whose logs are gone is HIDDEN
from the picker rather than greyed out — "the list shows only what can actually
be sent" — and only the machine knows what that is.

⭐⭐ IT PUBLISHES IDS, NEVER LABELS. There is no topic and no title anywhere in a
run folder: not in `meta.json`, not in `events.json`. That absence is deliberate
— `_run_log_folder_name` has no `run_id` parameter precisely so a topic cannot
reach a folder name — and this channel preserves it. The app already holds the
titles in its own research documents and joins them on `researchId`.

⭐ ONE DOCUMENT PER SUBMITTER, IN THAT SUBMITTER'S OWN TREE. A field on the
device document would be readable by the owner AND every sharer, so one sharer
would learn every other sharer's run history.

⛔ Unattributed runs go to NOBODY. Every run folder in the field today is
unattributed, so on day one every list is empty — the accepted consequence of not
backfilling, and why the terminal's `--select` shows the owner everything.
"""
import json

import pytest

import research


def _row(name, uid=None, epoch=1.0, rid=None, size=10, status="complete", attempt=0):
    return {"name": name, "submitterUid": uid, "startedEpoch": epoch,
            "researchId": rid if rid is not None else name.split("_")[0],
            "startedUtc": "2026-08-24T00:00:00Z", "status": status,
            "sizeBytes": size, "attempt": attempt}


@pytest.fixture(autouse=True)
def _clean_publisher(monkeypatch):
    monkeypatch.setattr(research, "_run_index_published", {})
    monkeypatch.setattr(research, "_run_index_next_ms", 0)
    yield


# ══ 1. the grouping, pure ══════════════════════════════════════════════
def test_each_submitter_gets_only_their_own_runs():
    out = research._run_index_by_submitter(
        [_row("a", "U1"), _row("b", "U2"), _row("c", "U1")])
    assert set(out) == {"U1", "U2"}
    assert {e["name"] for e in out["U1"]["runs"]} == {"a", "c"}
    assert {e["name"] for e in out["U2"]["runs"]} == {"b"}


def test_an_unattributed_run_is_published_to_nobody():
    """⛔⛔ THE DAY-ONE CASE, not an edge one. No run folder in the field records
    a submitter, so this is every run on every machine until the next release."""
    out = research._run_index_by_submitter(
        [_row("legacy", None), _row("blank", "")])
    assert out == {}


def test_newest_first_then_truncated():
    """⛔ THE DIRECTION, not just the number. Truncating the newest would hide
    exactly the run a person is about to complain about — and this file has
    already been wrong about a truncation direction once, on the source cap."""
    rows = [_row(f"r{i}", "U1", epoch=i) for i in range(research.RUN_INDEX_MAX + 5)]
    out = research._run_index_by_submitter(rows)["U1"]
    assert len(out["runs"]) == research.RUN_INDEX_MAX
    assert out["truncated"] is True
    assert out["runs"][0]["name"] == f"r{research.RUN_INDEX_MAX + 4}"
    assert "r0" not in {e["name"] for e in out["runs"]}


def test_truncated_is_false_when_nothing_was_dropped():
    out = research._run_index_by_submitter([_row("a", "U1")])["U1"]
    assert out["truncated"] is False


# ══ 2. what a descriptor may carry ═════════════════════════════════════
def test_a_descriptor_carries_ids_and_never_a_label():
    """⭐⭐ THE POINT OF THE WHOLE CHANNEL. A topic reaching this document would
    put every sharer's research subject into a Firestore write the machine makes
    on their behalf — and the folder-name design exists to make that
    unrepresentable."""
    entry = research._run_index_entry(_row("chat_1_1_20260824T000000", "U1"))
    assert set(entry) == {"name", "researchId", "startedUtc", "status",
                          "sizeBytes", "attempt"}
    assert "topic" not in entry and "title" not in entry


def test_a_descriptor_survives_a_row_with_a_topic_glued_to_it():
    """Defence in depth: even if some future scan grew a topic key, the
    descriptor is built by naming fields rather than by copying the row."""
    row = _row("a", "U1")
    row["topic"] = "the owner's private research subject"
    row["title"] = "and its title"
    assert "topic" not in json.dumps(research._run_index_entry(row))
    assert "title" not in json.dumps(research._run_index_entry(row))


def test_every_string_field_is_bounded():
    """⛔ The rule that accepts this document caps its size; a machine that sent
    an unbounded string would be refused and its picker would stay empty."""
    row = _row("N" * 500, "U1", rid="R" * 500, status="S" * 500)
    row["startedUtc"] = "T" * 500
    entry = research._run_index_entry(row)
    assert len(entry["name"]) == 96
    assert len(entry["researchId"]) == 64
    assert len(entry["startedUtc"]) == 32
    assert len(entry["status"]) == 24


def test_a_missing_status_reads_as_unknown_not_as_empty():
    entry = research._run_index_entry({"name": "a"})
    assert entry["status"] == "unknown"
    assert entry["sizeBytes"] == 0 and entry["attempt"] == 0


# ══ 3. the publisher ═══════════════════════════════════════════════════
class _FakeDoc:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def collection(self, name):
        return _FakeCol(self.db, f"{self.path}/{name}")

    def set(self, payload, **_kw):
        # ⛔ THE RAISE LIVES ON THE LEAF, and getting that wrong is how the first
        # version of these two tests passed while measuring nothing: the
        # publisher calls `.set` on `users/{uid}/deviceRunLogs/{deviceId}`, three
        # levels down, so a failure planted on the `users` collection is never
        # reached.
        if self.db.fail_writes:
            raise PermissionError("403 Missing or insufficient permissions")
        self.db.store[self.path] = payload


class _FakeCol:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, name):
        return _FakeDoc(self.db, f"{self.path}/{name}")


class _FakeDb:
    def __init__(self):
        self.store = {}
        self.fail_writes = False

    def collection(self, name):
        return _FakeCol(self, name)


@pytest.fixture()
def db(monkeypatch):
    fake = _FakeDb()
    monkeypatch.setattr(research, "_firebase_db", fake)
    monkeypatch.setattr(research, "load_device_id", lambda: "DEV1")
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "DEV1"})
    return fake


def test_the_publish_lands_in_each_submitters_own_tree(db, monkeypatch):
    monkeypatch.setattr(research, "_scan_run_folders",
                        lambda: [_row("a", "U1"), _row("b", "U2")])
    written = research._publish_run_log_index()
    assert written == {"U1": True, "U2": True}
    assert "users/U1/deviceRunLogs/DEV1" in db.store
    assert "users/U2/deviceRunLogs/DEV1" in db.store
    u1 = db.store["users/U1/deviceRunLogs/DEV1"]
    assert [e["name"] for e in u1["runs"]] == ["a"]
    assert u1["deviceId"] == "DEV1"


def test_nothing_is_rewritten_when_nothing_changed(db, monkeypatch):
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [_row("a", "U1")])
    assert research._publish_run_log_index(now_ms=0) == {"U1": True}
    assert research._publish_run_log_index(now_ms=10 ** 12) == {}


def test_a_changed_list_is_republished(db, monkeypatch):
    rows = [_row("a", "U1")]
    monkeypatch.setattr(research, "_scan_run_folders", lambda: list(rows))
    research._publish_run_log_index(now_ms=0)
    rows.append(_row("b", "U1", epoch=2))
    assert research._publish_run_log_index(now_ms=10 ** 12) == {"U1": True}
    names = [e["name"] for e in db.store["users/U1/deviceRunLogs/DEV1"]["runs"]]
    assert names == ["b", "a"]


def test_a_submitter_whose_last_run_was_pruned_is_emptied(db, monkeypatch):
    """⛔⛔ THE ONE A CHANGE-GATE GETS WRONG. When a uid drops out of the scan
    there is nothing to compare, so the obvious implementation simply skips it —
    and the picker goes on offering a run whose logs are gone, which is exactly
    what the hidden-not-greyed decision was meant to prevent."""
    rows = [_row("a", "U1")]
    monkeypatch.setattr(research, "_scan_run_folders", lambda: list(rows))
    research._publish_run_log_index(now_ms=0)
    rows.clear()
    assert research._publish_run_log_index(now_ms=10 ** 12) == {"U1": True}
    assert db.store["users/U1/deviceRunLogs/DEV1"]["runs"] == []


def test_the_empty_write_happens_once_and_then_settles(db, monkeypatch):
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [_row("a", "U1")])
    research._publish_run_log_index(now_ms=0)
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [])
    assert research._publish_run_log_index(now_ms=10 ** 12) == {"U1": True}
    assert research._publish_run_log_index(now_ms=2 * 10 ** 12) == {}


def test_the_throttle_holds_the_scan_off_the_heartbeat_tick(db, monkeypatch):
    calls = {"n": 0}

    def _scan():
        calls["n"] += 1
        return [_row("a", "U1")]

    monkeypatch.setattr(research, "_scan_run_folders", _scan)
    research._publish_run_log_index(now_ms=0)
    research._publish_run_log_index(now_ms=1_000)
    research._publish_run_log_index(now_ms=2_000)
    assert calls["n"] == 1, "the directory walk ran on a throttled tick"


def test_force_ignores_the_throttle_and_the_change_gate(db, monkeypatch):
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [_row("a", "U1")])
    research._publish_run_log_index(now_ms=0)
    assert research._publish_run_log_index(force=True, now_ms=0) == {"U1": True}


def test_no_firestore_client_publishes_nothing_and_raises_nothing(monkeypatch):
    monkeypatch.setattr(research, "_firebase_db", None)
    assert research._publish_run_log_index() == {}


def test_an_unpaired_machine_publishes_nothing(db, monkeypatch):
    """No deviceId means no document path — and the picker has nothing to point
    at either, since a machine that is not paired has no row in the app."""
    monkeypatch.setattr(research, "load_device_id", lambda: "")
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [_row("a", "U1")])
    assert research._publish_run_log_index() == {}


def test_a_denied_write_is_reported_not_raised(db, monkeypatch):
    """⛔ The rule ships separately from the code, so a 403 on every tick is the
    NORMAL state until it is deployed. It must not raise into the heartbeat and
    it must not be recorded as published."""
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [_row("a", "U1")])
    db.fail_writes = True
    assert research._publish_run_log_index() == {"U1": False}
    assert db.store == {}
    assert research._run_index_published == {}, (
        "a failed write was recorded as published, so the retry never happens")


def test_a_retry_after_a_denial_actually_republishes(db, monkeypatch):
    """The other half of the one above: a machine whose rule lands later must
    publish on its next tick rather than believing it already did."""
    monkeypatch.setattr(research, "_scan_run_folders", lambda: [_row("a", "U1")])
    db.fail_writes = True
    assert research._publish_run_log_index(now_ms=0) == {"U1": False}
    db.fail_writes = False
    assert research._publish_run_log_index(now_ms=10 ** 12) == {"U1": True}
    assert "users/U1/deviceRunLogs/DEV1" in db.store


def test_the_heartbeat_publishes_it_off_the_liveness_write():
    """⛔ In a thread with a deadline. This loop owns the liveness write, and a
    slow publish that delayed a heartbeat would flip the device to Offline in the
    app — turning a diagnostics feature into an availability bug."""
    from conftest import code_only
    src = code_only(research._heartbeat_loop.__wrapped__)
    assert "asyncio.to_thread(_publish_run_log_index)" in src
    assert "asyncio.wait_for(" in src
    idx = src.index("_publish_run_log_index")
    assert "try:" in src[max(0, idx - 300):idx], "an unguarded publish can raise"
