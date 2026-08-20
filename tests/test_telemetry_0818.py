"""Wave 2 step 8 — the content-free tier, and the ways it could stop being one.

⛔⛔ THE STRUCTURAL CLAIM THIS FILE EXISTS TO HOLD. There is no free text in this
module. Every field is an int, a bool or an enum; `research_id` is the single
string parameter, regex-guarded to the shape the frontend actually mints. A
research topic here is a TypeError, not a scrubbing miss — and a scrubber leaks
the first time somebody adds a line, which somebody always does.

⭐⭐ AND THE POLARITY TEST NOBODY WRITES. The first draft of the id guard was
`^[A-Za-z0-9]{20}$`, which rejects EVERY real id. Every rejection test would
have passed; the feature would have silently never worked. So a REAL id being
ACCEPTED is asserted first, before any of the refusals.
"""
import importlib
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import code_only_deep

import telemetry as tm


SENTINEL = "KALKI-2898-AD-SENTINEL"
REAL_ID = "chat_1755500000000_3"
RUN_ID = "kalki_20260818_153044"


@pytest.fixture(autouse=True)
def _scratch_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("SR_WORKER_ID", raising=False)
    monkeypatch.setenv("SR_TELEMETRY", "1")
    monkeypatch.setattr(tm, "_install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(tm, "_build", lambda: "0.1.13")
    yield


def _spooled():
    path = tm.spool_path()
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ══ 1. accept polarity FIRST ═══════════════════════════════════════════
def test_a_real_research_id_is_ACCEPTED():
    """⭐⭐ THE MISSING TEST. `^[A-Za-z0-9]{20}$` rejects every real id — a guard
    that fires on every honest input is a feature that never works, and every
    rejection test below would still have passed."""
    assert tm.coerce_field("research_id", REAL_ID) == REAL_ID
    assert tm.tm_emit(tm.Ev.RUN_STARTED, research_id=REAL_ID) is True
    assert _spooled()[0]["d"]["research_id"] == REAL_ID


def test_the_ids_the_frontend_really_mints_all_pass():
    for rid in ("chat_1700000000000_1", "chat_1799999999999_999999",
                "chat_1755500000000_42"):
        assert tm.coerce_field("research_id", rid) == rid


# ══ 2. no free text, by construction ═══════════════════════════════════
def test_the_signature_admits_no_free_text():
    """⛔ Read from the SIGNATURE, not the body. A body is audited once; a
    signature is checked on every commit."""
    sig = inspect.signature(tm.tm_emit)
    kinds = {p.kind for p in sig.parameters.values()}
    assert inspect.Parameter.VAR_KEYWORD not in kinds, "**kwargs reopens free text"
    assert inspect.Parameter.VAR_POSITIONAL not in kinds
    named = [n for n, p in sig.parameters.items()
             if p.kind is inspect.Parameter.KEYWORD_ONLY]
    assert named, "every field must be keyword-only and therefore named"
    for name in named:
        assert name in tm.FIELD_TYPES, f"{name} is not in the field vocabulary"
    strings = [n for n in named if tm.FIELD_TYPES[n] is str]
    assert strings == ["research_id"], f"more than one string field: {strings}"


def test_a_string_in_any_other_field_raises_even_with_validation_defeated(monkeypatch):
    """⭐ THE PROPERTY THAT DOES NOT REST ON A VALIDATOR. A `str` reaches the id
    branch only when the field is literally named `research_id`, so a regex
    monkeypatched to match anything still cannot get text into `phase`."""
    monkeypatch.setattr(tm, "RESEARCH_ID_RE", __import__("re").compile(r".*"))
    monkeypatch.setattr(tm, "RUN_ID_SUFFIX_RE", __import__("re").compile(r"(?!)"))
    for field in ("phase", "duration_ms", "count", "platform", "error_class", "ok"):
        with pytest.raises(tm.TelemetryFieldError):
            tm.coerce_field(field, SENTINEL)


def test_a_topic_shaped_research_id_is_refused():
    for hostile in (SENTINEL, RUN_ID, "Kalki 2898 AD box office",
                    "chat_123_1", "chat_1755500000000_", "../../etc/passwd"):
        with pytest.raises(tm.TelemetryFieldError):
            tm.coerce_field("research_id", hostile)


def test_a_run_id_shaped_string_is_refused_by_its_own_guard(monkeypatch):
    """⭐ Two independent guards. `run_id` is `safe_name(topic)_YYYYMMDD_HHMMSS`,
    and a one-word topic survives `safe_name` as bare alphanumerics — so the
    suffix denial has to hold even if the shape regex is loosened."""
    monkeypatch.setattr(tm, "RESEARCH_ID_RE", __import__("re").compile(r".*"))
    with pytest.raises(tm.TelemetryFieldError):
        tm.coerce_field("research_id", RUN_ID)


def test_a_rejected_field_is_byte_absent_from_the_spool_and_the_mirror():
    tm.tm_emit(tm.Ev.RUN_STARTED, research_id=SENTINEL)
    for path in (tm.spool_path(), tm.sent_log_path()):
        if path.exists():
            assert SENTINEL not in path.read_text(encoding="utf-8"), path


def test_a_rejected_field_reports_ITSELF_and_not_its_value(caplog):
    with caplog.at_level("WARNING", logger="telemetry"):
        tm.tm_emit(tm.Ev.PHASE_START, research_id=SENTINEL)
    text = caplog.text
    assert "research_id" in text
    assert SENTINEL not in text, "the leak report leaked the thing it reported"


def test_a_rejection_still_records_that_something_was_rejected():
    tm.tm_emit(tm.Ev.RUN_STARTED, research_id=SENTINEL)
    events = [r["ev"] for r in _spooled()]
    assert int(tm.Ev.TELEMETRY_INVALID) in events, (
        "a silently dropped field means absence reads as health")


def test_a_field_the_event_does_not_carry_is_dropped_not_sent():
    tm.tm_emit(tm.Ev.LOGIN_STARTED, phase=3)
    rows = _spooled()
    login = [r for r in rows if r["ev"] == int(tm.Ev.LOGIN_STARTED)]
    assert login and login[0]["d"] == {}
    assert int(tm.Ev.TELEMETRY_INVALID) in [r["ev"] for r in rows]


# ══ 3. the catalogue, and the two repos that read it ═══════════════════
def test_the_catalogue_file_matches_the_module():
    """⛔ A fork makes the newest events 400 at the route and drop silently, and
    absence reads as health."""
    on_disk = json.loads(Path("telemetry_catalogue.json").read_text(encoding="utf-8"))
    assert on_disk == tm.catalogue(), (
        "regenerate telemetry_catalogue.json — the module moved without it")


def test_the_app_repo_carries_a_byte_identical_copy():
    here = Path("telemetry_catalogue.json")
    there = Path(__file__).resolve().parents[2] / "dg-research" / "src" / "lib" / "telemetry-catalogue.json"
    if not there.exists():
        pytest.skip("sibling app repo not checked out")
    assert json.loads(there.read_text(encoding="utf-8")) == json.loads(
        here.read_text(encoding="utf-8"))


def test_every_event_declares_its_fields():
    for ev in tm.Ev:
        assert ev in tm.EVENT_FIELDS, f"{ev.name} carries no field declaration"
        for name in tm.EVENT_FIELDS[ev]:
            assert name in tm.FIELD_TYPES, f"{ev.name} declares unknown field {name}"


def test_every_event_has_a_call_site():
    """⛔⛔ A DECLARED EVENT THAT NOTHING EMITS is worse than an absent one. At read
    time it is indistinguishable from an event that never HAPPENS — so a reader
    concludes "nobody ever completes stage 3", and `PAIR_FAILED` has nothing to be
    a fraction of.

    This test found TEN of them on 2026-08-18. Five had a real moment in the flow
    and were wired; five had none and were deleted as dead vocabulary. The two
    exemptions below are emitted by this module about ITSELF, so they are the only
    events whose call site is not in research.py."""
    from pathlib import Path
    src = Path("research.py").read_text(encoding="utf-8")
    self_reported = {tm.Ev.TELEMETRY_INVALID, tm.Ev.TELEMETRY_DROPPED}
    own = Path("telemetry.py").read_text(encoding="utf-8")
    for ev in tm.Ev:
        if ev in self_reported:
            assert f"Ev.{ev.name}" in own, f"{ev.name} is not even emitted here"
            continue
        assert f"Ev.{ev.name}" in src, (
            f"{ev.name} is declared and never emitted — at read time that is "
            f"indistinguishable from an event that never happens"
        )


def test_the_dead_pairing_events_are_gone_and_the_numbers_did_not_shift():
    """⛔ Renumbering silently reinterprets every stored batch, so deleting members
    must leave the survivors' wire numbers untouched."""
    names = {e.name for e in tm.Ev}
    for dead in ("PAIR_INITIATED", "PAIR_CLAIMED", "PAIR_API_KEY_VERIFIED",
                 "PAIR_PLATFORM_VERIFIED", "PAIR_PROFILES_CHOSEN"):
        assert dead not in names, f"{dead} came back with no call site"
    assert int(tm.Ev.PAIR_STARTED) == 1
    assert int(tm.Ev.PAIR_CODE_SHOWN) == 3
    assert int(tm.Ev.PAIR_TOKEN_EXCHANGED) == 5
    assert int(tm.Ev.PAIR_STAGE_REACHED) == 6
    assert int(tm.Ev.PAIR_COMPLETED) == 10
    assert int(tm.Ev.PAIR_FAILED) == 11


def test_event_numbers_are_unique_and_stable():
    values = [int(e) for e in tm.Ev]
    assert len(values) == len(set(values))
    # A renumbering silently reinterprets every stored batch, so the wire
    # numbers of the events that already shipped are pinned.
    assert int(tm.Ev.PAIR_STARTED) == 1
    assert int(tm.Ev.RUN_STARTED) == 40
    assert int(tm.Ev.PIPELINE_ERROR) == 48
    assert int(tm.Ev.TELEMETRY_INVALID) == 90


def test_the_verify_vocabulary_is_the_corrected_one():
    """⛔ An earlier draft used {COOKIE, DOM, CUA} — how a check is PERFORMED,
    which is not what any call site knows."""
    assert {m.name for m in tm.VerifyStatus} == {"NO_CHECK", "OK", "FREE", "MISSING"}


def test_platform_fails_closed():
    assert tm.Platform(0) is tm.Platform.OTHER
    assert int(tm.Platform.OTHER) == 0


# ══ 4. error classes come from TYPES ═══════════════════════════════════
def test_classify_never_reads_the_message():
    """⛔⛔ An exception message carries paths — and therefore the OS account name
    — hostnames, URLs with query strings, and on this codebase a Firebase Web API
    key, measured 5,047 times in one log.

    ⛔ Read through `code_only_deep`. The docstring of the function under test
    QUOTES `str(exc)` to explain why it is forbidden, so a plain source search
    matches the prose and passes no matter what the code does — the trap that
    helper exists for, hit on the first try here."""
    src = code_only_deep(tm.classify_exception)
    assert "str(exc)" not in src
    assert ".args" not in src
    assert "exc.message" not in src
    assert "repr(exc)" not in src
    # And the polarity: it really does read the type.
    assert "type(exc).__name__" in src


def test_classify_maps_the_failures_this_wave_is_about():
    import socket
    assert tm.classify_exception(socket.gaierror("nope")) is tm.ErrorClass.DNS
    assert tm.classify_exception(ConnectionRefusedError()) is tm.ErrorClass.CONNECT_REFUSED
    assert tm.classify_exception(TimeoutError()) is tm.ErrorClass.TIMEOUT
    assert tm.classify_exception(PermissionError()) is tm.ErrorClass.PERMISSION
    assert tm.classify_exception(FileNotFoundError()) is tm.ErrorClass.NOT_FOUND
    assert tm.classify_exception(ValueError("x")) is tm.ErrorClass.UNKNOWN


def test_classify_reads_an_http_status_off_a_response_object():
    class _Resp:
        status_code = 403

    class _Err(Exception):
        response = _Resp()

    assert tm.classify_exception(_Err()) is tm.ErrorClass.HTTP_4XX
    _Resp.status_code = 503
    assert tm.classify_exception(_Err()) is tm.ErrorClass.HTTP_5XX


def test_an_optional_dependency_is_matched_by_type_name_not_imported():
    class SSLError(Exception):
        pass

    assert tm.classify_exception(SSLError()) is tm.ErrorClass.TLS


# ══ 5. the spool ══════════════════════════════════════════════════════
def test_each_process_owns_its_own_spool_file(monkeypatch):
    """⛔ A shared file plus read-POST-truncate loses whatever another process
    appended mid-flush — and "--doctor while serve flushes" IS the recovery flow."""
    cli = tm.spool_path()
    monkeypatch.setenv("SR_WORKER_ID", "2")
    assert tm.spool_path(2) != cli
    assert "w2" in tm.spool_path(2).name


def test_the_envelope_carries_what_a_reader_needs_and_nothing_else():
    tm.tm_emit(tm.Ev.SERVE_STARTED, worker=1, supervised=True)
    row = _spooled()[0]
    assert set(row) == {"v", "iuid", "sid", "seq", "t", "b", "os", "ev", "d"}
    assert row["iuid"] == "iuid-test"
    assert row["d"] == {"worker": 1, "supervised": True}


def test_the_sequence_is_monotonic_within_a_session():
    for _ in range(5):
        tm.tm_emit(tm.Ev.LOGIN_STARTED)
    seqs = [r["seq"] for r in _spooled()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_an_accepted_event_is_mirrored_to_a_file_a_user_can_read():
    """⭐ A FILE, not a log line: under `--pair` this process's logger reaches no
    file at all, and the transparency claim has to hold there too."""
    tm.tm_emit(tm.Ev.PAIR_STARTED, supervised=False)
    assert tm.sent_log_path().exists()
    assert "PAIR" not in tm.sent_log_path().read_text(encoding="utf-8")  # numbers, not names
    assert json.loads(tm.sent_log_path().read_text(encoding="utf-8").splitlines()[0])["ev"] \
        == int(tm.Ev.PAIR_STARTED)


def test_the_spool_is_bounded_and_says_what_it_dropped(monkeypatch):
    monkeypatch.setattr(tm, "SPOOL_MAX_LINES", 10)
    for _ in range(30):
        tm.tm_emit(tm.Ev.LOGIN_STARTED)
    rows = _spooled()
    assert len(rows) <= 12, len(rows)
    assert any(r["ev"] == int(tm.Ev.TELEMETRY_DROPPED) for r in rows), (
        "a silent drop is a count nobody can trust")


def test_the_oldest_half_is_what_gets_dropped(monkeypatch):
    """⭐ The newest events describe whatever is going wrong right now."""
    monkeypatch.setattr(tm, "SPOOL_MAX_LINES", 10)
    for i in range(1, 21):
        tm.tm_emit(tm.Ev.LOGIN_FINISHED, count=i)
    counts = [r["d"].get("count") for r in _spooled() if r["ev"] == int(tm.Ev.LOGIN_FINISHED)]
    assert 20 in counts, "the newest event was dropped"
    assert 1 not in counts, "nothing was dropped at all"


def test_the_kill_switch_is_env_only(monkeypatch):
    monkeypatch.setenv("SR_TELEMETRY", "0")
    assert tm.enabled() is False
    assert tm.tm_emit(tm.Ev.LOGIN_STARTED) is False
    assert not tm.spool_path().exists()
    assert tm.flush(post=lambda batch: True) == 0


def test_a_write_failure_never_raises_into_the_caller(monkeypatch, tmp_path):
    # ⛔ The unwritable path has to be unwritable EVERYWHERE.
    # "/does/not/exist" only fails on POSIX, where / is not user-writable; on
    # Windows it resolves to C:\does\not\exist, the writer's own
    # mkdir(parents=True) HAPPILY CREATES IT, the write succeeds, and this
    # returns True -- so the test both failed and left a directory at the
    # drive root.
    #
    # A file standing where a directory must go is refused by every platform:
    # mkdir cannot descend through it.
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"")
    monkeypatch.setattr(tm, "spool_path",
                        lambda worker=None: blocker / "sub" / "x.jsonl")
    assert tm.tm_emit(tm.Ev.LOGIN_STARTED) is False


# ══ 6. delivery ═══════════════════════════════════════════════════════
def test_a_flush_delivers_and_clears():
    for _ in range(3):
        tm.tm_emit(tm.Ev.LOGIN_STARTED)
    seen = []
    assert tm.flush(post=lambda batch: seen.append(batch) or True) == 3
    assert len(seen) == 1 and len(seen[0]) == 3
    assert not tm.spool_path().exists()


def test_a_failed_delivery_keeps_every_event():
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    assert tm.flush(post=lambda batch: False) == 0
    assert len(_spooled()) == 1
    # And it goes out on the next attempt rather than being lost.
    assert tm.flush(post=lambda batch: True) == 1


def test_the_claim_is_an_atomic_rename_not_a_truncate():
    src = code_only_deep(tm._claim)
    assert "os.replace" in src
    assert "truncate" not in code_only_deep(tm.flush)


def test_an_append_during_a_flush_is_not_lost():
    """⛔⛔ THE COLLISION THIS DESIGN EXISTS FOR: a `--doctor` appending while a
    serve process flushes. Read-POST-truncate destroys the append — and the
    append belongs to whichever command the user ran to recover."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)

    def _post(batch):
        # Another process appends while we are mid-delivery.
        tm.tm_emit(tm.Ev.DOCTOR_RUN, count=1)
        return True

    assert tm.flush(post=_post) == 1
    remaining = [r["ev"] for r in _spooled()]
    assert remaining == [int(tm.Ev.DOCTOR_RUN)], remaining


def test_two_real_processes_appending_during_a_flush_lose_nothing(tmp_path):
    """The same property, driven by an actual second interpreter."""
    home = tmp_path
    child = subprocess.run(
        [sys.executable, "-c",
         "import telemetry as t\n"
         "for _ in range(5): t.tm_emit(t.Ev.DOCTOR_RUN, count=1)\n"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "HOME": str(home), "SR_TELEMETRY": "1"},
        capture_output=True, text=True)
    assert child.returncode == 0, child.stderr
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    delivered = []
    landed = tm.flush(post=lambda b: delivered.extend(b) or True)
    assert landed == 6, [r["ev"] for r in delivered]


def test_a_crash_between_the_2xx_and_the_cleanup_re_sends_rather_than_loses():
    """⭐ At-least-once with an idempotent sink is the honest guarantee: the
    route's document id is a hash of the events, so a byte-identical resend
    collapses onto one document."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    sent = []

    def _post_then_die(batch):
        sent.append(batch)
        raise KeyboardInterrupt("killed after the 2xx")

    tm.flush(post=_post_then_die)
    assert len(_spooled()) == 1, "the event was lost on a crash mid-cleanup"
    assert tm.flush(post=lambda b: sent.append(b) or True) == 1
    assert sent[0][0]["seq"] == sent[1][0]["seq"], (
        "the resend is not byte-identical, so the sink cannot collapse it")


def test_an_append_during_a_FAILED_flush_keeps_both_halves():
    """⛔ Found by mutation. The success path was covered; the merge-back was not,
    and it is the half that runs when the network is the thing that is broken."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)

    def _fail_but_something_arrives(batch):
        tm.tm_emit(tm.Ev.DOCTOR_RUN, count=1)
        return False

    assert tm.flush(post=_fail_but_something_arrives) == 0
    events = sorted(r["ev"] for r in _spooled())
    assert events == sorted([int(tm.Ev.LOGIN_STARTED), int(tm.Ev.DOCTOR_RUN)]), events


def test_a_batch_past_the_cap_leaves_the_rest_OWED_not_deleted(monkeypatch):
    """⛔⛔ Found by mutation, and it was a real defect: capping the batch while
    the caller deletes the whole claimed file loses every event past the cap —
    and an offline machine's spool is exactly where a batch hits that cap."""
    monkeypatch.setattr(tm, "BATCH_MAX_EVENTS", 5)
    monkeypatch.setattr(tm, "SPOOL_MAX_LINES", 10_000)
    for i in range(1, 13):
        tm.tm_emit(tm.Ev.LOGIN_FINISHED, count=i)
    first = []
    assert tm.flush(post=lambda b: first.extend(b) or True) == 5
    assert [r["d"]["count"] for r in first] == [1, 2, 3, 4, 5]
    assert len(_spooled()) == 7, "the events past the cap were deleted"
    second = []
    assert tm.flush(post=lambda b: second.extend(b) or True) == 5
    assert [r["d"]["count"] for r in second] == [6, 7, 8, 9, 10]
    assert tm.flush(post=lambda b: True) == 2


def test_an_append_during_a_CAPPED_batch_survives_alongside_the_leftover(monkeypatch):
    """⛔ Found by mutation. Two things are owed after a capped delivery — the
    events past the cap, and whatever arrived while the batch was in flight — and
    the write-back has to keep both."""
    monkeypatch.setattr(tm, "BATCH_MAX_EVENTS", 2)
    monkeypatch.setattr(tm, "SPOOL_MAX_LINES", 10_000)
    for i in range(1, 6):
        tm.tm_emit(tm.Ev.LOGIN_FINISHED, count=i)

    def _post_and_something_arrives(batch):
        tm.tm_emit(tm.Ev.DOCTOR_RUN, count=99)
        return True

    assert tm.flush(post=_post_and_something_arrives) == 2
    left = _spooled()
    counts = [r["d"].get("count") for r in left]
    assert [3, 4, 5] == [c for c in counts if c != 99], counts
    assert 99 in counts, "the event that arrived mid-flight was lost"


def test_a_file_a_LIVE_sibling_is_posting_is_left_alone():
    """⛔ Found by mutation. Two processes flushing at once: A claims a file and
    B's glob sees the claimed name and posts it too. Not data loss — the sink
    collapses byte-identical resends — but it doubles the traffic of the quietest
    thing in the product for no reason."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    path = tm.spool_path()
    # os.getpid() is alive by definition, but it is OUR claim, so it is adoptable;
    # a DIFFERENT live pid is not. Use the parent process, which is alive.
    live_other = os.getppid()
    mine = path.with_name(f"{path.stem}.sending.{live_other}{path.suffix}")
    path.rename(mine)
    assert tm._adoptable(mine) is False
    assert tm.flush(post=lambda b: True) == 0
    assert mine.exists(), "another process's in-flight file was taken"


def test_our_own_stranded_claim_IS_adoptable():
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    path = tm.spool_path()
    mine = path.with_name(f"{path.stem}.sending.{os.getpid()}{path.suffix}")
    path.rename(mine)
    assert tm._adoptable(mine) is True
    assert tm.flush(post=lambda b: True) == 1


def test_a_ctrl_c_during_a_flush_does_not_print_a_traceback(recwarn):
    """⭐ Found while writing the test above: the sender raising a BaseException
    escaped the daemon thread and printed a traceback from telemetry in the
    middle of the user's own clean exit — noise from the quietest thing in the
    process."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)

    def _ctrl_c(batch):
        raise KeyboardInterrupt("user pressed Ctrl+C mid-flush")

    import threading as _th
    escaped = []
    previous = _th.excepthook
    _th.excepthook = lambda args: escaped.append(args.exc_type)
    try:
        assert tm.flush(post=_ctrl_c) == 0
    finally:
        _th.excepthook = previous
    assert len(_spooled()) == 1
    # ⛔ Found by mutation: pytest surfaces the escape as a warning at TEARDOWN,
    # which `recwarn` inside the test cannot see. The thread excepthook measures
    # the escape itself.
    assert escaped == [], f"the exception escaped the flush thread: {escaped}"


def test_a_file_a_dead_process_claimed_is_picked_back_up():
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    path = tm.spool_path()
    # A pid high enough to be unused on any of our platforms.
    stranded = path.with_name(f"{path.stem}.sending.4194303{path.suffix}")
    path.rename(stranded)
    assert tm._adoptable(stranded) is True
    assert tm.flush(post=lambda b: True) == 1
    assert not stranded.exists()


def test_events_past_the_age_cap_are_not_delivered():
    tm.tm_emit(tm.Ev.LOGIN_STARTED)
    old = time.time() + tm.EVENT_MAX_AGE_SEC + 86400
    assert tm.flush(post=lambda b: True, now=old) == 0
    assert not tm.spool_path().exists(), "the stale file was left to grow forever"


def test_a_hanging_post_is_abandoned_at_the_deadline():
    """⛔ `requests`' timeout does not bound `getaddrinfo`, and DNS-dead is the
    incident. A telemetry flush must never be why a command feels broken."""
    tm.tm_emit(tm.Ev.LOGIN_STARTED)

    def _hang(batch):
        time.sleep(30)
        return True

    started = time.monotonic()
    assert tm.flush(post=_hang, deadline_sec=0.4) == 0
    assert time.monotonic() - started < 5.0
    assert len(_spooled()) == 1, "the events were lost to a hang"


def test_the_flush_runs_on_a_daemon_thread():
    src = code_only_deep(tm._post_with_deadline)
    assert "daemon=True" in src
    assert "thread.join(" in src
    bg = code_only_deep(tm.flush_in_background)
    assert "daemon=True" in bg


def test_the_default_transport_is_our_own_host():
    src = code_only_deep(tm._post_batch)
    assert "/api/telemetry" in src
    assert "FE_BASE_URL" in src


def test_a_token_is_optional_and_never_required():
    """⭐ The events worth having most exist precisely when no credential does."""
    src = code_only_deep(tm._post_batch)
    i = src.index("token = _id_token()")
    assert "if token:" in src[i:i + 200]


def test_this_module_never_imports_research():
    """A telemetry module that imports the 69,000-line file it instruments makes
    every import in that file a telemetry dependency."""
    src = Path("telemetry.py").read_text(encoding="utf-8")
    assert "import research" not in src
    assert "from research" not in src


def test_the_module_logger_is_one_the_bridge_listens_to():
    """⛔ Six modules in this process logged into a void because nothing attached
    a handler. This one must not become the seventh."""
    import research
    assert "telemetry" in research._BRIDGED_LOGGERS
    assert tm.log.name == "telemetry"
