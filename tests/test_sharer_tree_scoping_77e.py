"""7.7E — a shared machine rehydrates only the runs IT ran out of a sharer's tree.

⛔⛔ WHY THIS FILE EXISTS RATHER THAN A CASE IN test_sharer_rehydration.py. That
suite's collection fake is `def where(self, *a, **k): return self` — it neither
records the predicate nor filters on it, so a test written against it cannot see
a `deviceId` filter appear OR vanish, and would stay green with the fix reverted.
A test double that cannot tell two implementations apart is not testing one. The
fake here records every FieldFilter and actually applies it.

The behaviour under test has two halves and they pull in opposite directions:

  SHARER tree  — the query MUST carry `deviceId == this machine`. The rules
                 narrowing of 7.7E requires it once the compatibility clause
                 comes out, and it is independently a correctness fix: nothing
                 in the rehydration loop looks at `deviceId` at all. Ownership
                 is decided by `assignedWorker`, a worker NUMBER, so a run that
                 executed on somebody's OTHER computer — `assignedWorker` unset,
                 which defaults to worker 1 — satisfies `_i_own` on this one.
                 Unscoped, this machine marks that machine's healthy run
                 `paused_backend_restart`, and on a supervised device auto-
                 resumes it against the wrong browser profiles.

  OWNER tree   — the query MUST NOT carry it. The tightened rule admits an
                 owner-tree list with no per-document test, the orphan safety net
                 is meant to reach runs whose owning worker is out of this fleet,
                 and an equality filter would silently drop every document
                 written before the `deviceId` stamp existed.

Run:  pytest tests/test_sharer_tree_scoping_77e.py -v
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


OWNER = "owner-uid"
SHARER = "sharer-uid"
MY_DEVICE = "dev-mine"
THEIR_DEVICE = "dev-theirs"


class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._d = data

    def to_dict(self):
        return self._d


class _DevSnap:
    def __init__(self, exists, data=None):
        self.exists = exists
        self._d = data or {}

    def to_dict(self):
        return self._d


class _RecordingQuery:
    """A query that REMEMBERS its filters and APPLIES them.

    ⭐ Both halves matter. Recording alone would pass a fix that added the
    predicate and then ignored it; filtering alone would pass a fix that
    filtered on the wrong field. The assertions below use both.
    """

    def __init__(self, snaps, log, filters=None):
        self._snaps = snaps
        self._log = log
        self._filters = list(filters or [])

    def where(self, filter=None, **_kw):  # noqa: A002 — Firestore's own kwarg name
        field = getattr(filter, "field_path", None)
        op = getattr(filter, "op_string", None)
        value = getattr(filter, "value", None)
        self._log.append((field, op, value))
        return _RecordingQuery(self._snaps, self._log, self._filters + [(field, op, value)])

    def _matches(self, snap):
        d = snap.to_dict()
        for field, op, value in self._filters:
            assert op == "==", f"this fake only implements '==', got {op!r}"
            if d.get(field) != value:
                return False
        return True

    def get(self):
        return [s for s in self._snaps if self._matches(s)]


class _UserDocRef:
    def __init__(self, db, uid):
        self._db, self._uid = db, uid

    def collection(self, name):
        if name == "researches":
            return _RecordingQuery(self._db.researches.get(self._uid, []), self._db.filters)
        return _UserDevicesCol()


class _MissingDocRef:
    def get(self):
        return _DevSnap(False)


class _UserDevicesCol:
    def document(self, _id):
        return _MissingDocRef()


class _DeviceDocRef:
    def __init__(self, db, device_id):
        self._db, self._id = db, device_id

    def get(self):
        return self._db.devices.get(self._id, _DevSnap(False))


class _UsersCol:
    def __init__(self, db):
        self._db = db

    def document(self, uid):
        return _UserDocRef(self._db, uid)


class _DevicesCol:
    def __init__(self, db):
        self._db = db

    def document(self, device_id):
        return _DeviceDocRef(self._db, device_id)


class _FakeDB:
    def __init__(self):
        self.researches = {}
        self.devices = {}
        self.filters = []   # every (field, op, value) any query applied

    def collection(self, name):
        if name == "users":
            return _UsersCol(self)
        if name == "devices":
            return _DevicesCol(self)
        raise AssertionError(f"unexpected collection {name}")


def _setup(monkeypatch, *, researches, devices=None, device_id=MY_DEVICE):
    db = _FakeDB()
    db.researches = researches
    db.devices = devices or {}
    monkeypatch.setattr(research, "_firebase_db", db, raising=False)
    monkeypatch.setattr(research, "load_device_id", lambda: device_id)
    updates = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda uid, rid, patch: (updates.append((uid, rid, patch)) or True))
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: True)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, wid: [])
    return db, updates


def _run(tree_uid, owner_uid):
    return asyncio.run(
        research._rehydrate_ongoing_for_tree(tree_uid, owner_uid, set())
    )


def _fields(db):
    return [f for (f, _op, _v) in db.filters]


def test_sharer_tree_query_carries_the_device_predicate(monkeypatch):
    db, _updates = _setup(
        monkeypatch,
        researches={SHARER: [_Snap("r1", {"deviceId": MY_DEVICE, "status": "ongoing"})]},
        devices={MY_DEVICE: _DevSnap(True, {"supervised": False})},
    )
    _run(SHARER, OWNER)
    assert ("deviceId", "==", MY_DEVICE) in db.filters, db.filters
    assert ("status", "==", "ongoing") in db.filters, db.filters


def test_owner_tree_query_does_NOT_carry_it(monkeypatch):
    # ⛔ THE POLARITY PIN. Without it, "scope everything" passes every other test
    # in this file while silently dropping legacy owner-tree documents from the
    # orphan safety net — and the rules do not even ask for it.
    db, _updates = _setup(
        monkeypatch,
        researches={OWNER: [_Snap("r1", {"deviceId": MY_DEVICE, "status": "ongoing"})]},
        devices={MY_DEVICE: _DevSnap(True, {"supervised": False})},
    )
    _run(OWNER, OWNER)
    assert "deviceId" not in _fields(db), db.filters
    assert ("status", "==", "ongoing") in db.filters


def test_another_machines_live_run_is_left_alone(monkeypatch):
    # ⛔⛔ THE DEFECT THIS FIXES, END TO END. `assignedWorker` is absent, which
    # the loop reads as worker 1 — so before the predicate this run satisfied
    # `_i_own` on a machine that never touched it, and got marked paused. The
    # person's Resume CTA would appear on a run that was running perfectly well
    # somewhere else.
    db, updates = _setup(
        monkeypatch,
        researches={SHARER: [
            _Snap("r-mine", {"deviceId": MY_DEVICE, "status": "ongoing"}),
            _Snap("r-theirs", {"deviceId": THEIR_DEVICE, "status": "ongoing"}),
        ]},
        devices={
            MY_DEVICE: _DevSnap(True, {"supervised": False}),
            THEIR_DEVICE: _DevSnap(True, {"supervised": False}),
        },
    )
    _run(SHARER, OWNER)
    touched = {rid for (_uid, rid, _patch) in updates}
    assert "r-theirs" not in touched, updates
    assert "r-mine" in touched, updates


def test_another_machines_SUPERVISED_run_is_not_auto_resumed_here(monkeypatch):
    # The worse half of the same defect: a supervised device meant this machine
    # would RE-OPEN somebody else's run on its own browser profiles — the wrong
    # logged-in accounts — which is the exact failure the per-worker affinity
    # logic exists to prevent, arriving through the machine dimension instead.
    enqueued = []
    db, _updates = _setup(
        monkeypatch,
        researches={SHARER: [
            _Snap("r-theirs", {"deviceId": THEIR_DEVICE, "status": "ongoing",
                               "backendRunId": "run-1", "topic": "their topic"}),
        ]},
        devices={THEIR_DEVICE: _DevSnap(True, {"supervised": True})},
    )
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: (enqueued.append(job) or True))
    _run(SHARER, OWNER)
    assert enqueued == [], enqueued


def test_a_machine_with_no_id_yet_does_not_query_for_an_empty_one(monkeypatch):
    # ⛔ A machine mid-pairing has no device id. Filtering on "" would match
    # nothing and silently disable rehydration for every sharer — a guard that
    # fires on the wrong input is worse than no guard, so the predicate is only
    # added when there is something to add.
    db, _updates = _setup(
        monkeypatch,
        researches={SHARER: [_Snap("r1", {"deviceId": MY_DEVICE, "status": "ongoing"})]},
        devices={MY_DEVICE: _DevSnap(True, {"supervised": False})},
        device_id="",
    )
    _run(SHARER, OWNER)
    assert "deviceId" not in _fields(db), db.filters


def test_the_denial_is_loud():
    # ⛔⛔ SOURCE PIN, AND IT PINS A SEVERITY, WHICH IS THE WHOLE FINDING. Rules
    # deploy in seconds; a wheel arrives when its owner upgrades. At DEBUG the
    # only symptom of a rules/wheel mismatch was that a run killed by a restart
    # quietly stopped being resumable — nothing in any log a person reads.
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research.py"), encoding="utf-8").read()
    at = src.index('f"[rehydrate:{status_val}] read denied for tree')
    # The severity is the argument on the line after the message closes.
    window = src[at:at + 260]
    assert '"WARN"' in window, window
    assert '"DEBUG"' not in window, window


def test_the_dead_worker_reconcile_stays_unscoped():
    # ⛔⛔ THE OTHER QUERY, AND THREE SEPARATE REVIEWS SAID TO SCOPE IT. Its only
    # caller passes load_paired_uid(), so its tree is ALWAYS the paired owner and
    # never a sharer — the tightened rule admits that list with no per-document
    # test. Scoping it would buy no permission and would drop every pre-stamp
    # document from the abandoned-run safety net. This pins the reasoning in
    # place so the next reader does not re-derive it wrongly.
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research.py"), encoding="utf-8").read()
    at = src.index("async def _reconcile_dead_worker_runs")
    body = src[at:at + 4000]
    assert '_fs_where(researches_col, "status", "==", "ongoing")' in body
    assert '"deviceId"' not in body, "the dead-worker reconcile must stay unscoped"


# ── the title carriers, pinned at the write ──────────────────────────────────
#
# ⛔⛔ SOURCE PINS, AND THEY ARE THE ONLY KIND AVAILABLE HERE. Every one of these
# writes sits inside `_job_worker`'s claim path or the queue recompute — an async
# loop with a Firestore handle, a worker id and a live job, several layers below
# anything a unit test can call. A mutation run put each title back and all four
# survived the behavioural suite, which is exactly the shape a pin exists for.
#
# ⭐ WHAT THEY PIN IS THE ABSENCE OF A VALUE, not the presence of one. That is
# unusual and it is the point: `devices/{deviceId}` is read WHOLE by the owner,
# every sharer and the machine, so the defect is a topic being ADDED back to a
# payload — which no assertion about correct output can ever see.
def _src() -> str:
    return open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research.py"), encoding="utf-8").read()


def test_current_run_title_is_cleared_not_written():
    src = _src()
    # ⭐ A DELETE, NOT AN OMISSION. Omitting the key would stop adding new titles
    # and leave whatever this machine last wrote sitting on the shared record
    # until the next STOP — so the pickup that would have published one now
    # removes the one before it.
    assert '"currentRunTitle": _crun_delete_field(),' in src
    assert '"currentRunTitle": (job.get("topic") or "")[:60],' not in src
    # ⛔ AND THE SIBLINGS STAY. currentRunId, the owner uid and the phase are what
    # let the FE say "you are second in the queue" — the reader's own business.
    assert '"currentRunId": job.get("research_id") or "",' in src
    assert '"currentRunOwnerUid": job.get("uid") or "",' in src


def test_the_busy_worker_map_carries_no_title():
    src = _src()
    at = src.index('f"workers.{WORKER_ID}": {')
    entry = src[at:src.index("},", at)]
    assert '"title"' not in entry, entry
    # The fields the badges actually render survive.
    for field in ('"uid"', '"runId"', '"phase"', '"totalPhases"'):
        assert field in entry, (field, entry)


def test_no_topic_is_extracted_for_the_run_queued_AHEAD():
    src = _src()
    # ⛔⛔ TWO HELPERS, AND A FIX THAT PATCHED ONE WOULD LEAVE THE OTHER LIVE — a
    # mutation run restored each separately and the second survived. Both read the
    # research document of the person queued ahead, which on a shared machine is
    # another account, and both used to slice its topic out.
    assert '(prev_data.get("topic") or "")[:60]' not in src
    # ⭐ THE RUN ID STAYS in both. It routes and names nothing; dropping it would
    # break the queue banner's ordering to buy no privacy at all.
    assert src.count('behind_rid = (prev_data.get("researchId") or "")') == 2


def test_no_queue_carrier_slices_a_topic_at_all():
    """⛔⛔ THE CATCH-ALL, AND THE FIRST VERSION OF IT WAS NOT ONE.

    It listed the two spellings the four known carriers happened to use —
    `d.get("topic")` and `job.get("topic")` — so it was green while a FIFTH
    carrier sat in the start listener spelled `_prior_data.get("title") or
    _prior_data.get("topic")`, doing a cross-tree read of another account's
    research document to fetch it. Cross-verify found that; a guard that
    enumerates the instances it already knows about is a list, not a catch-all.

    ⭐ SO IT MATCHES THE SHAPE INSTEAD: a topic or title sliced to sixty
    characters, however the value is spelled. Sixty is the length every carrier
    used, and it is not a coincidence — it is the width the banner was designed
    around, so anything new that leaks one will almost certainly wear it too.
    """
    import re
    src = _src()
    # `.get("topic")` or `.get("title")` anywhere on a line that also slices [:60]
    offenders = [
        line.strip()
        for line in src.split("\n")
        if re.search(r'get\(\s*"(topic|title)"\s*\)', line) and "[:60]" in line
    ]
    assert offenders == [], offenders
