"""Wave 2 step 2 — the bundle a user actually sends.

⭐ BOTH signed-off bounds apply as an INTERSECTION, never as a branch that
picks one: thirty runs can span a year, and a busy fortnight can be hundreds of
runs. So: drop everything past the age bound, then keep the newest thirty of
what is left.

⭐⭐ AND IT IS NOT ONLY RUNS. The incident this feature exists for produced NO
RUN — a paired machine whose Google DNS died — so a per-run-only bundle would
have held zero evidence of the failure it was built to explain. Sessions and
byte-tails of the raw device logs ride along, and the session stream is
deliberately NOT count-bound because the machine with no runs is exactly the
machine with nothing else to send.
"""
import json
import os
import re
import time
import zipfile

import pytest

import research


def _row(name, age_days, size=1000):
    return {"dir": None, "name": name, "sizeBytes": size,
            "startedEpoch": time.time() - age_days * 86400}


def _make_run(name, age_days=0, status="complete", research_id=None,
              body="a log line\n", meta=True):
    folder = research._runs_log_root() / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.log").write_text(body, encoding="utf-8")
    if meta:
        research._atomic_write_json(folder / "meta.json", {
            "schema": 1, "status": status, "pid": os.getpid(),
            "researchId": research_id, "attempt": 0,
            "startedUtc": research._utc_iso(
                __import__("datetime").datetime.fromtimestamp(
                    time.time() - age_days * 86400,
                    __import__("datetime").timezone.utc)),
            "counters": {"lines": 1, "warns": 0, "errors": 0},
        })
    when = time.time() - age_days * 86400
    os.utime(folder, (when, when))
    return folder


# ══ 1. the selection is an intersection, and it is pure ════════════════
def test_forty_recent_runs_yield_thirty():
    rows = [_row(f"r{i}", age_days=i * 0.1) for i in range(40)]
    out = research._select_bundle_runs(rows)
    assert len(out) == 30


def test_thirty_runs_spread_over_ninety_days_yield_only_the_recent_ones():
    rows = [_row(f"r{i}", age_days=i * 3) for i in range(30)]
    out = research._select_bundle_runs(rows)
    assert len(out) == 10, [r["name"] for r in out]
    assert all(r["startedEpoch"] >= time.time() - 30 * 86400 for r in out)


def test_both_bounds_apply_and_neither_is_a_branch_that_wins():
    """⛔ "whichever is smaller" has to PICK, and the two bounds answer
    different questions. Forty runs inside the window: the count bites. Five
    runs spread over a year: the age bites. Both in one set: both bite."""
    count_bound = research._select_bundle_runs(
        [_row(f"c{i}", age_days=i * 0.1) for i in range(40)])
    age_bound = research._select_bundle_runs(
        [_row(f"a{i}", age_days=i * 40) for i in range(5)])
    mixed = research._select_bundle_runs(
        [_row(f"m{i}", age_days=i * 0.5) for i in range(40)]
        + [_row(f"old{i}", age_days=200 + i) for i in range(10)])
    assert len(count_bound) == 30
    assert len(age_bound) == 1
    assert len(mixed) == 30
    assert not any(r["name"].startswith("old") for r in mixed)


def test_the_newest_run_is_first_so_the_cap_can_never_drop_it():
    rows = [_row("oldest", age_days=5), _row("newest", age_days=0),
            _row("middle", age_days=2)]
    assert research._select_bundle_runs(rows)[0]["name"] == "newest"


def test_the_selection_touches_no_filesystem(tmp_path):
    """A policy that needs a disk to test is a policy nobody tests."""
    rows = [{"name": "x", "startedEpoch": time.time()}]
    assert research._select_bundle_runs(rows)[0]["name"] == "x"


def test_a_zero_bound_is_honoured_rather_than_ignored():
    rows = [_row("a", 0), _row("b", 0)]
    assert research._select_bundle_runs(rows, max_runs=0) == []


# ══ 2. the metas ARE the index ═════════════════════════════════════════
def test_a_run_whose_meta_write_failed_still_appears():
    """⛔ The folder missing from a desynced index is the CRASHED one, because
    that is the write that failed. So the scan lists folders, not entries."""
    _make_run("chat_1_nometa_20260818T000001", meta=False)
    rows = research._scan_run_folders()
    assert [r["name"] for r in rows] == ["chat_1_nometa_20260818T000001"]
    assert rows[0]["status"] == "unknown"


def test_the_scan_derives_the_corpse_rather_than_repeating_the_stored_word():
    folder = _make_run("chat_1_dead_20260818T000002", status="running")
    research._atomic_write_json(folder / "meta.json", {
        "status": "running", "pid": 999_999_999,
        "startedUtc": research._utc_iso()})
    row = research._scan_run_folders()[0]
    assert row["storedStatus"] == "running"
    assert row["status"] == "process-died"


def test_the_scan_is_newest_first():
    _make_run("chat_1_old_20260818T000001", age_days=5)
    _make_run("chat_1_new_20260818T000002", age_days=0)
    assert [r["name"] for r in research._scan_run_folders()][0].endswith("000002")


# ══ 3. what ends up in the archive ═════════════════════════════════════
def _build(tmp_path, **kw):
    out = research._build_log_bundle(tmp_path / "bundle.zip",
                                    support_code="ABCD2345", **kw)
    return out, zipfile.ZipFile(out["path"])


def test_the_bundle_carries_a_manifest_an_index_and_the_runs(tmp_path):
    _make_run("chat_1_a_20260818T000001", research_id="chat_1755500000000_1")
    out, zf = _build(tmp_path)
    names = zf.namelist()
    assert "manifest.json" in names and "index.json" in names
    assert "runs/chat_1_a_20260818T000001/run.log" in names
    assert "runs/chat_1_a_20260818T000001/meta.json" in names
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["supportCode"] == "ABCD2345"
    assert manifest["runsSelected"] == 1
    assert out["runCount"] == 1


def test_the_manifest_names_the_bounds_it_applied(tmp_path):
    """⛔ Found by mutation. Without the bounds written down, a reader cannot
    tell a small bundle from a truncated one."""
    _make_run("chat_1_b_20260818T000001")
    _out, zf = _build(tmp_path)
    bounds = json.loads(zf.read("manifest.json"))["bounds"]
    assert bounds["maxRuns"] == research.BUNDLE_MAX_RUNS
    assert bounds["maxAgeDays"] == research.BUNDLE_MAX_AGE_DAYS
    assert bounds["maxBytes"] == research.BUNDLE_MAX_BYTES
    assert bounds["systemTailBytes"] == research.BUNDLE_SYSTEM_TAIL_BYTES


def test_the_manifest_carries_the_install_id_in_the_bundle_itself(tmp_path):
    """⭐ The only key that links a bundle sent while pairing was broken to the
    account once pairing works — so it has to be IN the file, not merely
    available to the code that writes it."""
    _make_run("chat_1_i_20260818T000001")
    _out, zf = _build(tmp_path)
    assert json.loads(zf.read("manifest.json"))["installUuid"] == \
        research._install_uuid_best_effort()


def test_the_index_says_how_big_each_run_is(tmp_path):
    """Found by mutation: without it the owner cannot see which run is the one
    that filled the bundle."""
    _make_run("chat_1_s_20260818T000001", body="x" * 5000)
    _out, zf = _build(tmp_path)
    row = json.loads(zf.read("index.json"))[0]
    assert row["sizeBytes"] > 4000, row


def test_sessions_ride_along_because_the_founding_case_had_no_run(tmp_path):
    """⭐⭐ A machine that never got a run to start is the case this exists for."""
    root = research._sessions_log_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "pair_20260818T000000.log").write_text("pairing failed here\n",
                                                   encoding="utf-8")
    out, zf = _build(tmp_path)
    assert "sessions/pair_20260818T000000.log" in zf.namelist()
    assert out["runCount"] == 0, "there are no runs — that is the whole point"
    assert out["sessionCount"] == 1
    assert b"pairing failed here" in zf.read("sessions/pair_20260818T000000.log")


def test_sessions_are_age_bounded_but_not_count_bounded(tmp_path):
    root = research._sessions_log_root()
    root.mkdir(parents=True, exist_ok=True)
    for i in range(50):
        p = root / f"pair_2026081{i % 10}T00000{i // 10}.log"
        p.write_text("x", encoding="utf-8")
    ancient = root / "pair_20250101T000000.log"
    ancient.write_text("x", encoding="utf-8")
    os.utime(ancient, (time.time() - 400 * 86400,) * 2)
    out, zf = _build(tmp_path)
    assert out["sessionCount"] == 50, (
        "the session stream must not be count-bound — the machine with no runs "
        "has nothing else to send")
    assert "sessions/pair_20250101T000000.log" not in zf.namelist()


def test_the_raw_device_logs_ride_along_as_tails_with_their_last_line(tmp_path):
    root = research._logs_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "backend.log").write_text("head line\n" + "x" * 100 + "\nLAST RAW LINE\n",
                                      encoding="utf-8")
    _out, zf = _build(tmp_path)
    assert b"LAST RAW LINE" in zf.read("system/backend.log")


def test_only_real_device_logs_are_collected(tmp_path):
    """⛔ The log directory also holds DOM dumps and page snapshots this repo
    writes while debugging. Those carry the CONTENT of a research session, and
    nothing in the consent screen offers them."""
    root = research._logs_root()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("backend.log", "backend.err.log", "backend-2.log",
                 "backend.log.1", "supervisor.log"):
        (root / name).write_text("device log\n", encoding="utf-8")
    for name in ("p2_panel_dump_1.html", "claude_model_popover_x.json",
                 "e2e-0806.log", "requirements.txt"):
        (root / name).write_text("SENSITIVE PAGE CONTENT\n", encoding="utf-8")
    _out, zf = _build(tmp_path)
    collected = [n for n in zf.namelist() if n.startswith("system/")]
    assert sorted(collected) == sorted([
        "system/backend.log", "system/backend.err.log", "system/backend-2.log",
        "system/backend.log.1", "system/supervisor.log"])
    body = b"".join(zf.read(n) for n in zf.namelist())
    assert b"SENSITIVE PAGE CONTENT" not in body


def test_a_tail_starts_at_a_whole_line(tmp_path):
    p = tmp_path / "big.log"
    # ⚠ write_BYTES, not write_text: on Windows write_text translates
    # \n to \r\n, so the fixture would not hold the bytes this test
    # asserts on. The reader under test is byte-oriented by design.
    p.write_bytes("".join(f"line {i:05d} padded out\n"
                          for i in range(2000)).encode())
    tail = research._tail_bytes(p, limit=500).decode()
    assert tail.startswith("line "), repr(tail[:40])
    assert tail.endswith("line 01999 padded out\n")
    # ⛔ Found by mutation: seeking to 0 and read()ing everything also ends with
    # the last line. The point of a tail is that it is BOUNDED.
    assert len(tail) <= 500, f"the tail is {len(tail)} bytes for a 500-byte limit"
    assert "line 00000" not in tail, "this is the head, not the tail"


# ══ 4. the collector cannot be pointed anywhere else ═══════════════════
def test_the_collector_allowlist_refuses_anything_outside_the_log_root():
    """⛔ The consent screen's promise that we collect no passwords, cookies or
    profile data is GATED on this. A collector that can be pointed anywhere
    eventually is."""
    inside = research._logs_root() / "runs" / "x" / "run.log"
    assert research._bundle_source_is_allowed(inside) is True
    for outside in ("/etc/passwd", str(research._STATE_DIR / "keystore-audit.log"),
                    str(research._STATE_DIR / "research_config.json")):
        assert research._bundle_source_is_allowed(outside) is False, outside


def test_a_symlink_out_of_the_log_root_is_refused(tmp_path):
    root = research._logs_root()
    root.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("token", encoding="utf-8")
    link = root / "escape.log"
    try:
        os.symlink(secret, link)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert research._bundle_source_is_allowed(link) is False


def test_every_archived_path_came_from_under_the_log_root(tmp_path):
    _make_run("chat_1_x_20260818T000001")
    root = research._sessions_log_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "doctor_20260818T000000.log").write_text("x", encoding="utf-8")
    _out, zf = _build(tmp_path)
    for name in zf.namelist():
        assert name.split("/")[0] in ("manifest.json", "index.json",
                                      "collected.json", "runs", "sessions",
                                      "system"), name
        assert ".." not in name and not name.startswith("/")


# ══ 5. a topic never reaches a PATH ════════════════════════════════════
def test_a_topic_never_reaches_an_archive_member_name(tmp_path):
    """The run body legitimately contains the topic — that is what the consent
    screen names. The FILENAMES must not, because a filename is what a support
    ticket, a bucket listing and a screenshot all show."""
    sentinel = "KALKI-2898-AD-SENTINEL"
    with research._RunLogCapture(research_id=None) as sink:
        research.log(f"Topic: {sentinel}", "INFO")
    assert sentinel in (sink.writer.primary.read_text(encoding="utf-8"))
    _out, zf = _build(tmp_path)
    for name in zf.namelist():
        assert sentinel not in name, name
    assert sentinel not in json.dumps(json.loads(zf.read("index.json")))


def test_the_index_carries_no_local_filesystem_paths(tmp_path):
    """An absolute path names the operating-system account. The index is the
    part of the bundle a support ticket quotes, so it stays free of it."""
    _make_run("chat_1_p_20260818T000001", research_id="chat_1755500000000_2")
    _out, zf = _build(tmp_path)
    index = zf.read("index.json").decode()
    assert "/Users/" not in index and "/home/" not in index, index[:400]
    assert str(research._logs_root()) not in index


# ══ 6. the size cap, exercised rather than assumed ═════════════════════
def test_the_cap_drops_the_oldest_and_never_the_newest(tmp_path):
    """⛔ At sixty times headroom this branch would never run in production, so
    it is dead code unless CI drives it — the surviving-mutant rule."""
    big = "y" * 200_000
    for i in range(5):
        _make_run(f"chat_1_{i}_2026081{i}T000001", age_days=5 - i, body=big)
    out, zf = _build(tmp_path, max_bytes=300_000)
    included = [n for n in zf.namelist() if n.startswith("runs/")]
    assert any("chat_1_4_" in n for n in included), (
        "the newest run was dropped by the cap — the run the user is "
        "complaining about")
    assert out["droppedForSize"], "the cap branch never ran; this test measured nothing"
    collected = json.loads(zf.read("collected.json"))
    assert collected["runsDroppedForSize"], collected
    assert "chat_1_0_" in "".join(collected["runsDroppedForSize"]), (
        "the cap dropped from the wrong end")


def test_a_run_is_whole_or_absent_never_half_in(tmp_path):
    """⛔ Found while driving the cap in CI. File-at-a-time, a folder's small
    meta.json fits where its 200 KB run.log does not — so the archive lists a
    run whose log is not there, and the index insists it is."""
    for i in range(4):
        _make_run(f"chat_1_{i}_2026081{i}T000001", age_days=4 - i, body="w" * 200_000)
    _out, zf = _build(tmp_path, max_bytes=250_000)
    names = zf.namelist()
    for name in names:
        if name.startswith("runs/") and name.endswith("meta.json"):
            run = name.rsplit("/", 1)[0]
            assert f"{run}/run.log" in names, f"{run} is in the archive with no log"


def test_the_newest_run_ships_even_when_it_alone_exceeds_the_cap(tmp_path):
    """⛔ Found by mutation. At a cap larger than one run the exemption is
    invisible — both the guarded and unguarded code include the newest run. The
    exemption only shows when the newest run is bigger than the entire budget,
    which is exactly the pathological run somebody is complaining about."""
    _make_run("chat_1_old_20260810T000001", age_days=3, body="o" * 200_000)
    _make_run("chat_1_new_20260814T000001", age_days=0, body="n" * 200_000)
    out, zf = _build(tmp_path, max_bytes=1000)
    assert "runs/chat_1_new_20260814T000001/run.log" in zf.namelist(), (
        "the newest run was dropped by the cap")
    assert "chat_1_old_20260810T000001" in out["droppedForSize"]


def test_a_source_outside_the_log_root_is_recorded_not_just_skipped(tmp_path):
    """⛔ Found by mutation. A collector that quietly skips is a collector whose
    misconfiguration nobody ever learns about."""
    folder = _make_run("chat_1_l_20260818T000001")
    secret = tmp_path / "outside.txt"
    secret.write_text("a token", encoding="utf-8")
    try:
        os.symlink(secret, folder / "escape.log")
    except OSError:
        pytest.skip("symlinks unavailable")
    out, zf = _build(tmp_path)
    assert out["sourcesRefused"], "the refusal left no trace"
    assert json.loads(zf.read("collected.json"))["sourcesRefused"]
    assert b"a token" not in b"".join(zf.read(n) for n in zf.namelist())


def test_the_archive_is_actually_compressed(tmp_path):
    """⛔ Found by mutation. 18 MB of raw log compresses to well under one, and
    the connection is often the thing that is broken."""
    _make_run("chat_1_c_20260818T000001", body="repeated line\n" * 5000)
    _out, zf = _build(tmp_path)
    info = zf.getinfo("runs/chat_1_c_20260818T000001/run.log")
    assert info.compress_type == zipfile.ZIP_DEFLATED
    assert info.compress_size * 10 < info.file_size, (
        f"{info.compress_size} of {info.file_size} — this is not compressed")


def test_the_system_tails_respect_the_ceiling_too(tmp_path):
    root = research._logs_root()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("backend.log", "backend-2.log", "backend.err.log"):
        (root / name).write_text("q" * 100_000, encoding="utf-8")
    _out, zf = _build(tmp_path, max_bytes=150_000)
    collected = json.loads(zf.read("collected.json"))
    assert any(d.startswith("system/") for d in collected["droppedForSize"]), (
        collected["droppedForSize"])


def test_what_the_cap_dropped_is_written_down(tmp_path):
    for i in range(4):
        _make_run(f"chat_1_{i}_2026081{i}T000001", age_days=4 - i, body="z" * 150_000)
    _out, zf = _build(tmp_path, max_bytes=200_000)
    collected = json.loads(zf.read("collected.json"))
    assert set(collected) >= {"runsIncluded", "runsDroppedForSize",
                              "sessionsIncluded", "uncompressedBytes"}
    assert collected["runsIncluded"], "nothing was included at all"


# ══ 7. one name for the format ═════════════════════════════════════════
def test_the_content_type_and_suffix_are_single_named_constants():
    """⛔ The rule cap, the local pre-check and the request header must read the
    SAME name, or an honest upload gets a 403 the retry ladder mislabels as
    transient."""
    assert research.BUNDLE_CONTENT_TYPE == "application/zip"
    assert research.BUNDLE_SUFFIX == ".zip"


def test_the_bundle_really_is_a_zip(tmp_path):
    _make_run("chat_1_z_20260818T000001")
    out = research._build_log_bundle(tmp_path / f"b{research.BUNDLE_SUFFIX}")
    assert zipfile.is_zipfile(out["path"])


def test_the_manifest_carries_the_install_id_that_survives_pairing():
    """⭐ The only key that links a bundle sent while pairing was broken to the
    account once pairing works."""
    import auth.keystore as ks
    assert research._install_uuid_best_effort() == ks.install_uuid()
