"""Wave 13 — Send Logs receipts stop retrying forever (the log storm).

⛔⛔ WHAT THE OWNER'S COMPUTER SHOWED (0.1.13 logs, 09-29). Five Send Logs
receipts — `users/{owner}/logBundles/{code}` rows the account refuses — were
replayed every five seconds on each worker, forever. They were 96% and 91% of
that day's two run logs, backend.log reached 111 MB, each round spent the
research writes' re-mint and three in a row switched it off with "re-pair
required", and the replay ran on the loop the job worker shares, freezing it
about one second in six. Master then added three new ways to park a receipt that
can never land, and would have landed month-old receipts as "sent" naming
bundles storage had already deleted.

⭐ EVERY TEST DRIVES THE REAL CHAIN — the drain, `_replay_parked_bundle_row`,
`_log_bundle_row_write`, `_grpc_write_with_heal`, the refusal writer, the
send-logs command handler, `_update_research_doc` and the reconnect watcher —
against a fake Firestore whose logBundles check is a clause-by-clause port of
dg-research/firestore.rules `match /logBundles/{code}`: create only at
'collecting', the owner branch or the scoped branch (`machineIncluded == false`),
`createdAt` and `machineIncluded` frozen on update. A write the rules would take
lands; one they would refuse raises PermissionDenied.
"""
import asyncio
import base64
import collections
import json
import re
import threading
import time as _real_time
from datetime import datetime, timedelta, timezone

import pytest

import research

DEV = "9f41418747cf4a36a9b518c7697b5491"
OWNER = "An1NfSXiroOpNXA4km9sINFerps2"       # the computer's owner (token ownerUid)
SHARER = "4ddj4nwdr8fRqNrvUNt6kRY40Fc2"      # shared with this computer
EXSHARER = "ExSharerNoLongerOnThisMachine"   # no longer shared with it
RID = "chat_1790692602555_1"
CODES = ["7QK4M2XZ", "MJ72K62P", "A1B2C3D4", "ZZZZ0000", "HJKM5678"]
CODE_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")
DAY = 86400


class PermissionDenied(Exception):
    """google.api_core.exceptions.PermissionDenied — the classifier keys on the
    class NAME."""


class ServiceUnavailable(Exception):
    """A failure to reach the account — not a refusal."""


def _mk_token(claims):
    def _b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.sig"


class Clock:
    """Stands in for `research.time`, so the heal's 30-second cooldown, the
    drain's backoff and its age check all read one simulated clock."""

    def __init__(self):
        self.t = float(int(_real_time.time()))

    def time(self):
        return self.t

    def __getattr__(self, name):
        return getattr(_real_time, name)


class FakeCreds:
    def __init__(self, fs):
        self.fs = fs
        self.token = _mk_token({"deviceId": DEV, "ownerUid": OWNER})
        self.refresh_calls = 0

    def refresh(self, request):
        self.refresh_calls += 1
        self.fs.research_stale = False      # a re-mint clears a stale credential


_ALLOWED = {'code', 'deviceId', 'status', 'requestId', 'createdAt', 'updatedAt',
            'expireAt', 'runCount', 'sessionCount', 'sizeBytes', 'runsApplied',
            'buildId', 'errorClass', 'objectPath', 'machineIncluded',
            'droppedForSize', 'runsNotAttributed', 'runsOtherMembers'}


def _shape_ok(d, code):
    """firestore.rules logBundles shapeOk(), the clauses these writes can trip."""
    return (set(d) <= _ALLOWED
            and type(d.get("machineIncluded")) is bool
            and d.get("code") == code
            and isinstance(d.get("deviceId"), str)
            and d.get("status") in ('collecting', 'uploading', 'done', 'failed')
            and isinstance(d.get("createdAt"), datetime)
            and isinstance(d.get("expireAt"), datetime))


class _Snap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _Node:
    def __init__(self, fs, parts):
        self.fs, self.parts = fs, parts

    def collection(self, name):
        return _Node(self.fs, self.parts + [name])

    def document(self, did):
        return _Node(self.fs, self.parts + [did])

    def get(self):
        path = "/".join(self.parts)
        return _Snap(self.fs.device if path == f"devices/{DEV}" else self.fs.docs.get(path))

    def set(self, payload, merge=False):
        return self.fs.write("/".join(self.parts), "set", dict(payload))

    def update(self, payload):
        return self.fs.write("/".join(self.parts), "update", dict(payload))


class FakeFS:
    def __init__(self):
        self._credentials = FakeCreds(self)
        self.device = {"ownerUid": OWNER, "sharedWith": [SHARER]}
        self.docs = {}
        self.attempts = collections.Counter()
        self.attempt_times = []
        self.research_stale = False
        self.latency = 0.0
        # (n) -> an exception to raise on the n-th logBundles write, or None
        self.fail = None
        self.clock = None

    def collection(self, name):
        return _Node(self, [name])

    def write(self, path, op, payload):
        if self.latency:
            _real_time.sleep(self.latency)
        kind = ("logBundles" if "/logBundles/" in path
                else "researches" if "/researches/" in path else "other")
        self.attempts[kind] += 1
        if kind == "logBundles":
            if self.clock is not None:
                self.attempt_times.append(self.clock.t)
            exc = self.fail(self.attempts[kind]) if self.fail else None
            if exc is not None:
                raise exc
            self._logbundles(path, op, payload)
        elif kind == "researches":
            if self.research_stale:
                raise PermissionDenied("Missing or insufficient permissions.")
            self.docs[path] = {**(self.docs.get(path) or {}), **payload}

    def _member(self, uid):
        return self.device["ownerUid"] == uid or uid in self.device["sharedWith"]

    def _logbundles(self, path, op, payload):
        _, uid, _, code = path.split("/")
        old = self.docs.get(path)
        if op == "update":
            if old is None:
                # A patch on a row that is not there is judged by the CREATE rule
                # and refused (status is not 'collecting', no createdAt).
                raise PermissionDenied("Missing or insufficient permissions.")
            new = {**old, **payload}
        else:
            new = dict(payload)
        tok_dev = research._decode_jwt_claims(self._credentials.token).get("deviceId")
        writing_to = new.get("deviceId") == tok_dev and self._member(uid)
        owner_branch = writing_to and self.device["ownerUid"] == uid
        scoped_branch = writing_to and new.get("machineIncluded") is False
        ok = (owner_branch or scoped_branch) and _shape_ok(new, code)
        if ok and old is None:
            ok = bool(CODE_RE.match(code)) and new.get("status") == "collecting"
        elif ok:
            ok = (new.get("deviceId") == old.get("deviceId")
                  and new.get("createdAt") == old.get("createdAt")
                  and new.get("machineIncluded") == old.get("machineIncluded"))
        if not ok:
            raise PermissionDenied("Missing or insufficient permissions.")
        self.docs[path] = new


@pytest.fixture
def env(monkeypatch):
    fs = FakeFS()
    clock = Clock()
    fs.clock = clock
    lines = []
    monkeypatch.setattr(research, "_firebase_db", fs)
    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: lines.append((level, str(msg))))
    monkeypatch.setattr(research, "load_device_id", lambda: DEV)
    monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: DEV)
    monkeypatch.setattr(research, "_grpc_heal_last_ts", 0.0)
    monkeypatch.setattr(research, "_grpc_heal_consec_fail", 0)
    monkeypatch.setattr(research, "_grpc_heal_structural", False)
    monkeypatch.setattr(research, "WORKER_ID", 1)
    return fs, clock, lines


def _done_patch(code, owner=OWNER):
    """What the terminal's `--send-logs` parks after its upload landed."""
    return {"status": "done", "objectPath": f"logs/{owner}/{DEV}/{code}/bundle.zip",
            "runCount": 3, "sessionCount": 4, "sizeBytes": 612345}


def _park(owner=OWNER, codes=CODES, at=None):
    for c in codes:
        research._queue_log_bundle_row(owner, c, _done_patch(c, owner), device_id=DEV)
    if at is not None:
        _restamp(at)


def _parked():
    path = research._queued_bundle_rows_path()
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _restamp(epoch):
    rows = _parked()
    stamp = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    research._queued_bundle_rows_path().write_text(
        "".join(json.dumps({**r, "at": stamp}) + "\n" for r in rows), encoding="utf-8")


def _existing_open(fs, owner=OWNER, code=CODES[0], hours_ago=3):
    """A row whose OPEN landed earlier and whose patch did not."""
    then = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    fs.docs[f"users/{owner}/logBundles/{code}"] = {
        "status": "collecting", "deviceId": DEV, "requestId": "", "code": code,
        "machineIncluded": True, "createdAt": then, "updatedAt": then,
        "expireAt": then + timedelta(days=30), "buildId": "x"}


def _count(lines, needle, level=None):
    return sum(1 for lv, m in lines if needle in m and (level is None or lv == level))


def _ticks(clock, n, step=5.0):
    landed = 0
    for _ in range(n):
        landed += research._drain_queued_log_bundle_rows()
        clock.t += step
    return landed


# ══ 1. a refusal is final ══════════════════════════════════════════════
def test_a_refused_parked_row_is_dropped_with_one_line_and_never_retried(env):
    """⛔⛔ THE STORM. Five receipts for an account no longer on this computer,
    one simulated hour at the watcher's five-second tick. Before: 7,203 refused
    writes, 3,600 WARN lines, still parked. Now each row is tried once — the
    open, then the patch, each with the free same-token retry — and dropped."""
    fs, clock, lines = env
    _park(owner=EXSHARER)
    landed = _ticks(clock, 720)
    assert landed == 0
    assert fs.attempts["logBundles"] == 4 * len(CODES), fs.attempts
    assert _count(lines, "refused a saved Send Logs receipt", "WARN") == len(CODES)
    assert _count(lines, "status write failed") == 0
    assert not research._queued_bundle_rows_path().exists()


def test_the_dropped_line_names_the_receipt_without_its_whole_code(env):
    """The support code is the read capability for its bundle; the line names
    the receipt by a prefix."""
    fs, clock, lines = env
    _park(owner=EXSHARER, codes=CODES[:1])
    _ticks(clock, 1)
    said = [m for lv, m in lines if "refused a saved" in m]
    assert len(said) == 1 and "7QK4…" in said[0], said
    assert CODES[0] not in said[0]


# ══ 2. a failure to reach the account keeps the row, backing off ══════
def _unavailable(n):
    return ServiceUnavailable("503 The service is currently unavailable.")


def _denied_then_unavailable(n):
    """A refusal, and then the network dropping on the same-token retry. The
    retry's exception carries the refusal as its context; the network decides."""
    return (PermissionDenied("Missing or insufficient permissions.") if n % 2
            else ServiceUnavailable("503 The service is currently unavailable."))


@pytest.mark.parametrize("fail", [_unavailable, _denied_then_unavailable],
                         ids=["unavailable", "denied_then_unavailable"])
def test_a_row_that_cannot_reach_the_account_is_kept_and_tried_later(env, fail):
    fs, clock, lines = env
    _park(codes=CODES[:1])
    fs.fail = fail
    _ticks(clock, 720)                      # one hour of outage
    rows = _parked()
    assert len(rows) == 1, "a receipt that only failed to reach the account was dropped"
    # 0, 30, 90, 210, 450, 930 and 1890 s in: seven tries, not 720.
    tries = sorted(set(fs.attempt_times))
    assert len(tries) == 7, [t - tries[0] for t in tries]
    assert _count(lines, "refused a saved") == 0
    fs.fail = None
    _ticks(clock, 400)                      # the network is back
    assert not research._queued_bundle_rows_path().exists()
    row = fs.docs[f"users/{OWNER}/logBundles/{CODES[0]}"]
    # The terminal's bundle is the whole machine's, and its row says so.
    assert row["status"] == "done" and row["machineIncluded"] is True


def test_the_wait_between_tries_doubles_from_thirty_seconds_to_half_an_hour(env):
    fs, clock, lines = env
    _park(codes=CODES[:1])
    fs.fail = _unavailable
    _ticks(clock, 6 * 720)                  # six hours
    tries = sorted(set(fs.attempt_times))
    gaps = [b - a for a, b in zip(tries, tries[1:])]
    assert gaps[:8] == [30, 60, 120, 240, 480, 960, 1800, 1800], gaps
    assert max(gaps) == 1800


# ══ 3. a receipt older than its bundle is dropped, not landed ═════════
def test_parked_row_older_than_the_bundle_lifecycle_is_dropped(env):
    """⛔ The bucket deletes a bundle thirty days after it arrives. A receipt
    landed later shows as sent, freshly dated, naming a file that is gone."""
    fs, clock, lines = env
    _park(codes=CODES[:1], at=clock.t - 31 * DAY)
    assert _ticks(clock, 1) == 0
    assert fs.attempts["logBundles"] == 0
    assert not research._queued_bundle_rows_path().exists()
    assert _count(lines, "older than the 30 days its bundle is kept", "WARN") == 1
    assert f"users/{OWNER}/logBundles/{CODES[0]}" not in fs.docs


@pytest.mark.parametrize("age,lands", [(30 * DAY, False), (30 * DAY - 5, True)])
def test_the_age_bound_is_the_thirty_days_themselves(env, age, lands):
    fs, clock, lines = env
    _park(codes=CODES[:1], at=clock.t - age)
    assert _ticks(clock, 1) == (1 if lands else 0)
    assert (f"users/{OWNER}/logBundles/{CODES[0]}" in fs.docs) is lands


def test_a_row_with_no_readable_stamp_is_dropped(env):
    fs, clock, lines = env
    _park(codes=CODES[:1])
    rows = _parked()
    research._queued_bundle_rows_path().write_text(
        json.dumps({k: v for k, v in rows[0].items() if k != "at"}) + "\n", encoding="utf-8")
    assert _ticks(clock, 1) == 0
    assert fs.attempts["logBundles"] == 0
    assert not research._queued_bundle_rows_path().exists()


def test_a_junk_line_is_dropped_and_the_rest_still_land(env):
    fs, clock, lines = env
    _park(codes=CODES[:1])
    path = research._queued_bundle_rows_path()
    path.write_text("not json\n[1, 2]\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    assert _ticks(clock, 1) == 1
    assert not path.exists()


# ══ 4. rows master parked that could never land ═══════════════════════
def test_a_row_whose_open_landed_replays_its_patch_as_an_update(env):
    """⛔⛔ A second open is refused — the update rule freezes `createdAt` — so a
    row whose open had landed was refused on every replay and its patch never
    went."""
    fs, clock, lines = env
    _existing_open(fs)
    before = dict(fs.docs[f"users/{OWNER}/logBundles/{CODES[0]}"])
    _park(codes=CODES[:1])
    assert _ticks(clock, 1) == 1
    row = fs.docs[f"users/{OWNER}/logBundles/{CODES[0]}"]
    assert row["status"] == "done" and row["objectPath"].endswith("/bundle.zip")
    assert row["createdAt"] == before["createdAt"]
    assert not research._queued_bundle_rows_path().exists()


def test_an_owner_refusal_whose_patch_hit_a_blip_lands_on_replay(env):
    """The refusal writer's own shape of the same thing: its open landed, its
    patch hit a timeout, and it parked."""
    fs, clock, lines = env
    fs.fail = lambda n: ServiceUnavailable("deadline exceeded") if n == 2 else None
    research._refuse_log_bundle_with_row(OWNER, CODES[0], DEV, "req-1", "CooldownActive")
    assert len(_parked()) == 1
    fs.fail = None
    clock.t += 30
    assert _ticks(clock, 1) == 1
    row = fs.docs[f"users/{OWNER}/logBundles/{CODES[0]}"]
    assert row["status"] == "failed" and row["errorClass"] == "CooldownActive"
    assert not research._queued_bundle_rows_path().exists()


def _send_logs_command(submitted_by):
    return {"action": research.SEND_LOGS_SELECTED_ACTION, "code": CODES[0],
            "requestId": "req-1", "submittedBy": submitted_by, "consent": True,
            "runNames": ["chat_1790692602555_1_20260929T143731"]}


def test_a_sharer_refusal_parked_on_a_blip_lands_in_their_tree(env, monkeypatch):
    """⛔⛔ Through the command handler. A sharer's row is opened with
    `machineIncluded: false` — the only way the rules let it into their tree.
    The parked copy lost that, the replay opened it as a whole-machine row, and
    the rules refused it forever."""
    fs, clock, lines = env
    monkeypatch.setattr(research, "_send_logs_cooldown_remaining", lambda *a, **k: 42)
    fs.fail = lambda n: ServiceUnavailable("503 unavailable") if n == 1 else None
    research._handle_send_logs_command(_send_logs_command(SHARER), DEV, selected=True)
    assert len(_parked()) == 1, "the refusal that hit a blip was not kept"
    clock.t += 30
    assert _ticks(clock, 1) == 1
    row = fs.docs[f"users/{SHARER}/logBundles/{CODES[0]}"]
    assert row["status"] == "failed" and row["errorClass"] == "CooldownActive"
    assert row["machineIncluded"] is False
    assert not research._queued_bundle_rows_path().exists()


def test_a_removed_sharers_refusal_is_not_parked(env):
    """⛔⛔ Through the command handler. Somebody removed a moment before
    pressing Send Logs has a tree this computer may not write to; their refusal
    row is refused, and parking it restarted the storm."""
    fs, clock, lines = env
    research._handle_send_logs_command(_send_logs_command(EXSHARER), DEV, selected=True)
    assert _parked() == []
    assert _count(lines, "the account refused the NotDeviceMember receipt", "WARN") == 1
    assert _count(lines, "status write failed") == 0


# ══ 5. a receipt never spends the research writes' safety net ═════════
def test_a_refused_receipt_does_not_spend_the_research_writes_re_mint(env):
    """⛔⛔ One process-wide re-mint every 30 seconds. A refused receipt used it,
    and a research write that needed it ten seconds later just failed."""
    fs, clock, lines = env
    assert research._open_log_bundle_row(EXSHARER, CODES[0], DEV) is False
    clock.t += 10
    fs.research_stale = True
    assert research._update_research_doc(SHARER, RID, {"status": "ongoing"}) is True
    assert fs._credentials.refresh_calls == 1
    assert _count(lines, "research doc update failed") == 0


def test_refused_receipts_never_latch_the_heal_or_blame_the_pairing(env):
    """⛔⛔ Three refused receipts in a row switched the heal off for everything
    and printed "re-pair required" — nine times in the older logs, and once on
    worker 2 a minute after it started."""
    fs, clock, lines = env
    for i in range(4):
        assert research._open_log_bundle_row(EXSHARER, CODES[i], DEV) is False
        clock.t += 31
    assert fs._credentials.refresh_calls == 0
    assert research._grpc_heal_consec_fail == 0
    assert research._grpc_heal_structural is False
    assert _count(lines, "re-pair") == 0 and _count(lines, "STRUCTURAL") == 0
    fs.research_stale = True
    assert research._update_research_doc(SHARER, RID, {"status": "ongoing"}) is True


def _stale_token(fs, *, remint_heals=True):
    """This computer's cached token in the known stale shape: no deviceId
    claim. A re-mint brings the claim back (or, `remint_heals=False`, does not)."""
    creds = fs._credentials
    creds.token = _mk_token({"ownerUid": OWNER})
    counted = creds.refresh

    def refresh(request):
        counted(request)
        if remint_heals:
            creds.token = _mk_token({"deviceId": DEV, "ownerUid": OWNER})
    creds.refresh = refresh


def test_a_receipt_refused_only_for_a_stale_token_lands_after_one_re_mint(env):
    """⭐ w13 low. The owner's own receipt, refused only because this computer's
    cached token lacked its deviceId claim, was dropped for good: `heal=False`
    skipped the re-mint that clears exactly that. It gets ONE re-mint now — and
    the research writes' net is untouched: no cooldown stamp (a research write
    ten seconds later still gets its own re-mint), no count, no latch."""
    fs, clock, lines = env
    _stale_token(fs)
    assert research._open_log_bundle_row(OWNER, CODES[0], DEV) is True
    assert f"users/{OWNER}/logBundles/{CODES[0]}" in fs.docs
    assert fs._credentials.refresh_calls == 1
    assert research._grpc_heal_last_ts == 0.0, "the receipt stamped the research writes' cooldown"
    assert research._grpc_heal_consec_fail == 0 and research._grpc_heal_structural is False
    clock.t += 10
    fs.research_stale = True
    assert research._update_research_doc(SHARER, RID, {"status": "ongoing"}) is True
    assert fs._credentials.refresh_calls == 2


def test_a_stale_token_the_re_mint_does_not_fix_costs_one_re_mint_and_is_final(env):
    fs, clock, lines = env
    _stale_token(fs, remint_heals=False)
    assert research._open_log_bundle_row(OWNER, CODES[0], DEV) is False
    assert fs._credentials.refresh_calls == 1
    assert research._grpc_heal_consec_fail == 0 and research._grpc_heal_structural is False


def test_the_live_writer_still_says_when_a_receipt_failed(env):
    fs, clock, lines = env
    assert research._write_log_bundle_status(EXSHARER, CODES[0], {"status": "done"}) is False
    assert _count(lines, "status write failed (the account refused it)", "WARN") == 1
    fs.fail = _unavailable
    assert research._write_log_bundle_status(OWNER, CODES[0], {"status": "done"}) is False
    assert _count(lines, "status write failed (the account could not be reached)", "WARN") == 1


def test_the_terminal_parks_its_receipt_without_a_warning(env, monkeypatch, capsys):
    """A terminal `--send-logs` has no Firestore client at all, so its receipt
    parks — and that is the plan, not a failure to report."""
    fs, clock, lines = env
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(research, "_ask_yes_no_sync", lambda *a, **k: True)
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    monkeypatch.setattr(research, "_decode_jwt_claims",
                        lambda t: {"ownerUid": OWNER, "deviceId": DEV})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda p, o, d, c: f"logs/{o}/{d}/{c}/bundle.zip")
    research.cmd_send_logs(assume_yes=True)
    rows = _parked()
    assert len(rows) == 1 and rows[0]["patch"]["status"] == "done"
    assert _count(lines, "status write failed") == 0
    assert "status write failed" not in capsys.readouterr().out


# ══ 6. the replay runs off the job worker's loop, on worker 1, machine-logged
def _quiet_watcher(monkeypatch):
    monkeypatch.setattr(research.tm, "flush_in_background", lambda *a, **k: None)

    async def _no_dead_watches():
        return []
    monkeypatch.setattr(research, "_rearm_dead_watches_if_any", _no_dead_watches)


def _run_watcher(until, budget_s):
    """Run the real reconnect watcher; return the longest the event loop went
    without running another task."""
    gaps = []

    async def main():
        task = asyncio.create_task(research._firebase_reconnect_loop())
        last = _real_time.monotonic()
        end = last + budget_s
        while _real_time.monotonic() < end and not until():
            await asyncio.sleep(0.01)
            now = _real_time.monotonic()
            gaps.append(now - last)
            last = now
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    asyncio.run(main())
    return max(gaps) if gaps else 0.0


def test_the_replay_does_not_freeze_the_job_workers_loop(monkeypatch):
    """⛔⛔ Five receipts at 0.1 s a write: the watcher's loop — the one the job
    worker runs on — stalled for over a second each round."""
    fs = FakeFS()
    fs.latency = 0.1
    monkeypatch.setattr(research, "_firebase_db", fs)
    monkeypatch.setattr(research, "load_device_id", lambda: DEV)
    monkeypatch.setattr(research, "WORKER_ID", 1)
    _quiet_watcher(monkeypatch)
    _park()
    path = research._queued_bundle_rows_path()
    stall = _run_watcher(lambda: not path.exists(), budget_s=8)
    assert not path.exists(), "the watcher never replayed the parked receipts"
    assert all(fs.docs[f"users/{OWNER}/logBundles/{c}"]["status"] == "done" for c in CODES)
    assert stall < 0.3, f"the event loop froze for {stall:.2f}s"


def test_only_worker_1_replays_the_parked_receipts(monkeypatch):
    """Every worker drained the same file: twice the writes, and two processes
    rewriting it under each other."""
    fs = FakeFS()
    monkeypatch.setattr(research, "_firebase_db", fs)
    monkeypatch.setattr(research, "load_device_id", lambda: DEV)
    monkeypatch.setattr(research, "WORKER_ID", 2)
    _quiet_watcher(monkeypatch)
    _park(codes=CODES[:1])
    _run_watcher(lambda: False, budget_s=0.5)
    assert fs.attempts["logBundles"] == 0
    assert len(_parked()) == 1


def test_the_replays_lines_stay_out_of_the_armed_runs_log(monkeypatch, capsys):
    """⛔ The watcher is not machine-logged — an outage explains a run's fate —
    so the replay's lines landed in whatever run was armed: 6,925 of one run
    log's 7,763 lines. The replay is bundle administration, and says so."""
    fs = FakeFS()
    monkeypatch.setattr(research, "_firebase_db", fs)
    monkeypatch.setattr(research, "load_device_id", lambda: DEV)
    monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: DEV)
    monkeypatch.setattr(research, "WORKER_ID", 1)
    _quiet_watcher(monkeypatch)
    _park(owner=EXSHARER, codes=CODES[:1])
    path = research._queued_bundle_rows_path()
    with research._RunLogCapture(research_id=RID):
        research.log("[pipeline] a line the run wrote itself", "INFO")
        # The watcher is a task of its own, started with the server — never
        # inside a run's context — so it runs here on a thread of its own.
        t = threading.Thread(target=lambda: _run_watcher(lambda: not path.exists(), 5))
        t.start()
        t.join()
    assert not path.exists()
    assert "refused a saved Send Logs receipt" in capsys.readouterr().out
    run_logs = list(research._runs_log_root().glob(f"{RID}_*/run.log"))
    assert run_logs, "the run's own log was never written"
    text = run_logs[0].read_text(encoding="utf-8")
    assert "a line the run wrote itself" in text
    assert "[send-logs]" not in text, text
