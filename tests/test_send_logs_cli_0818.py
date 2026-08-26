"""Wave 2 step 5 — `--send-logs` from the terminal.

⛔⛔ THE FOUNDING BLOCKER. The machine that started this wave was PAIRED, with
Google DNS dead: securetoken, firestore and firebasestorage were all
unreachable, so the authenticated path was not slow — it was gone. An
unpaired-only fallback would have excluded exactly the case it exists for, so
the fallback is reached for paired machines too.

⭐ AND THE FLOOR. The local file is written FIRST and printed, before anything
touches the network, because it is the one rung that cannot fail. A diagnostic
that only works over the channel whose failure it diagnoses is not a diagnostic.
"""
import inspect
import io
import json
import re
import sys

import pytest

import research


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Everything network-shaped stubbed out; the archive is built for real."""
    state = {"uploads": [], "posts": [], "rows": [], "parked": [], "opened": []}
    monkeypatch.setattr(research, "_ask_yes_no_sync", lambda *a, **k: True)
    monkeypatch.setattr(research, "load_device_id", lambda: "d-1")
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    monkeypatch.setattr(research, "_decode_jwt_claims",
                        lambda t: {"ownerUid": "user-rocky", "deviceId": "d-1"})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda p, o, d, c: state["uploads"].append((o, d, c))
                        or f"logs/{o}/{d}/{c}/bundle.zip")
    monkeypatch.setattr(research, "_post_bundle_to_ingest",
                        lambda p, c, email=None: state["posts"].append((c, email)) or c)
    monkeypatch.setattr(research, "_write_log_bundle_status",
                        lambda o, c, patch, create=False:
                        state["rows"].append((o, c, patch)) or True)
    monkeypatch.setattr(research, "_queue_log_bundle_row",
                        lambda o, c, patch, device_id="":
                        state["parked"].append((o, c, patch, device_id)))
    monkeypatch.setattr(research, "_open_log_bundle_row",
                        lambda o, c, d, r="": state["opened"].append((o, c, d)) or True)
    return state


def _one_run():
    with research._RunLogCapture(research_id="chat_1755500000000_1"):
        research.log("a run happened", "INFO")


# ══ 1. consent comes first, and it is explicit ═════════════════════════
def test_the_consent_screen_names_everything_that_leaves(capsys, cli, monkeypatch):
    asked = []
    monkeypatch.setattr(research, "_ask_yes_no_sync",
                        lambda q, **k: asked.append((q, k)) or False)
    assert research.cmd_send_logs() == 0
    out = capsys.readouterr().out
    for fact in ("30 runs", "topics", "links that open your research results",
                 "email address", "agent screens", "hostname",
                 "log files"):
        assert fact in out, fact
    for absent in ("passwords", "cookies", "API keys"):
        assert absent in out, f"the copy no longer says {absent} stay put"
    assert asked and asked[0][1]["default"] is False, (
        "a bare Enter must not send somebody's logs")


def test_declining_sends_nothing_at_all(capsys, cli, monkeypatch):
    monkeypatch.setattr(research, "_ask_yes_no_sync", lambda *a, **k: False)
    assert research.cmd_send_logs() == 0
    assert cli["uploads"] == [] and cli["posts"] == []
    assert "Nothing was sent" in capsys.readouterr().out


def test_ctrl_c_at_the_prompt_sends_nothing(capsys, cli, monkeypatch):
    def _boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(research, "_ask_yes_no_sync", _boom)
    assert research.cmd_send_logs() == 130
    assert cli["uploads"] == [] and cli["posts"] == []


def test_the_thirty_day_deletion_promise_is_made_because_a_rule_now_keeps_it():
    """✅ INVERTED 2026-08-26, AND BOTH VERSIONS WERE RIGHT AT THE TIME.

    Until that date no bucket lifecycle rule existed in any repo, so this
    asserted the flag was False and the sentence absent — "deleted after 30
    days" would have been a lie of exactly the kind wave 1 spent itself
    removing. The rule is now live on the `logs/` prefix (action Delete, age
    30) and was read back by two independent tools before the flag moved.

    ⛔ WHAT THIS TEST IS REALLY FOR IS THE OTHER DIRECTION. If the rule is ever
    withdrawn, the flag has to come back with it — the flag is not a feature
    switch, it is a claim about a bucket."""
    assert research.BUNDLE_LIFECYCLE_VERIFIED is True, (
        "if this is False again the lifecycle rule must have been withdrawn — "
        "and the runbook's `verified:` block must be withdrawn in the same "
        "commit, or the front end still promises deletion")
    lines = " ".join(research._send_logs_consent_lines())
    assert "deleted automatically 30 days after it arrives" in lines


def test_the_gate_still_gates_when_it_is_closed(monkeypatch):
    """The gate has to be a gate in both directions, or it is decoration.

    ⛔ Kept as a monkeypatch rather than deleted now that the flag ships True:
    a flag with only one tested value is indistinguishable from a constant, and
    the day it needs to close is the day nobody remembers whether it can."""
    monkeypatch.setattr(research, "BUNDLE_LIFECYCLE_VERIFIED", False)
    lines = " ".join(research._send_logs_consent_lines())
    assert "deleted" not in lines
    # ⛔ "last 30 days" is the run AGE BOUND and has nothing to do with
    # retention. Stripping it is what stops this assertion passing vacuously.
    assert "30 days" not in lines.replace("last 30 days", "")


def test_the_retention_line_names_the_arrival_and_not_the_request():
    """⭐ The two clocks are different and only one of them is the bucket's.

    The lifecycle rule counts from the object's creation — the upload. The
    index row's `expireAt` is stamped when the row is OPENED, before a byte
    moves, and is never refreshed. A sentence that said "30 days from when you
    asked" would be describing the row's clock while the deletion runs on the
    object's."""
    line = [l for l in research._send_logs_consent_lines() if "deleted" in l]
    assert len(line) == 1
    assert "after it arrives" in line[0]


def test_the_promise_covers_the_material_and_never_the_record():
    """⛔⛔ The rule deletes the OBJECT. The index row that names it is not
    covered by it, and that row's own TTL was measured undeployed on 08-26 — so
    the receipt outlives the file. That is tolerable only because the row
    carries no log content; it is NOT a licence to widen the sentence."""
    lines = " ".join(research._send_logs_consent_lines()).lower()
    for overreach in ("no record", "nothing is kept", "no trace",
                      "we keep nothing", "erased completely"):
        assert overreach not in lines, (
            f"{overreach!r} claims the record goes too, and it does not")


def test_the_run_bounds_and_the_raw_logs_are_named_separately():
    """⛔ The raw device tails have NO age bound — a machine older than per-run
    capture has its whole history only there. Folding them into the 30-day
    sentence would make that half a claim about bytes it does not cover."""
    lines = research._send_logs_consent_lines()
    runs_line = [l for l in lines if "30 runs" in l]
    raw_line = [l for l in lines if "log files" in l]
    assert len(runs_line) == 1 and len(raw_line) == 1
    assert runs_line != raw_line
    assert "whatever their age" in raw_line[0]


# ══ 1b. --runs, from the terminal ══════════════════════════════════════
def test_the_chosen_count_reaches_the_builder(cli, monkeypatch):
    """⛔ A flag that is accepted and ignored is worse than no flag: the consent
    screen names a number and the archive is cut with another."""
    seen = {}

    def _build(dest, **k):
        seen.update(k)
        return {"path": dest, "sizeBytes": 1, "runCount": 1, "sessionCount": 0,
                "maxRunsApplied": k.get("max_runs"), "uncompressedBytes": 1,
                "droppedForSize": [], "sourcesRefused": []}

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    research.cmd_send_logs(assume_yes=True, runs=4)
    assert seen["max_runs"] == 4


def test_the_consent_screen_names_the_number_it_will_actually_use(capsys, cli,
                                                                  monkeypatch):
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 1,
                                           "runCount": 1, "sessionCount": 0,
                                           "maxRunsApplied": k.get("max_runs"),
                                           "uncompressedBytes": 1,
                                           "droppedForSize": [],
                                           "sourcesRefused": []})
    research.cmd_send_logs(assume_yes=True, runs=4)
    out = capsys.readouterr().out
    assert "at most 4 runs" in out, out
    assert "at most 30 runs" not in out


def test_an_out_of_range_count_from_the_terminal_is_clamped(cli, monkeypatch):
    seen = []
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: seen.append(k.get("max_runs")) or
                        {"path": dest, "sizeBytes": 1, "runCount": 0,
                         "sessionCount": 0, "maxRunsApplied": k.get("max_runs"),
                         "uncompressedBytes": 1, "droppedForSize": [],
                         "sourcesRefused": []})
    research.cmd_send_logs(assume_yes=True, runs=0)
    research.cmd_send_logs(assume_yes=True, runs=999)
    assert seen == [research.BUNDLE_MIN_RUNS, research.BUNDLE_MAX_RUNS]


def test_no_flag_means_the_machines_own_cap(cli, monkeypatch):
    seen = []
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: seen.append(k.get("max_runs")) or
                        {"path": dest, "sizeBytes": 1, "runCount": 0,
                         "sessionCount": 0, "maxRunsApplied": k.get("max_runs"),
                         "uncompressedBytes": 1, "droppedForSize": [],
                         "sourcesRefused": []})
    research.cmd_send_logs(assume_yes=True)
    assert seen == [research.BUNDLE_MAX_RUNS]


def test_the_flag_is_wired_all_the_way_from_argparse(cli):
    src = inspect.getsource(research.main)
    assert 'add_argument("--runs"' in src
    assert "runs=args.send_logs_runs" in src


# ══ 2. the local file is the floor ═════════════════════════════════════
def test_the_bundle_is_written_and_its_path_printed_before_any_network(capsys, cli):
    _one_run()
    assert research.cmd_send_logs(assume_yes=True) == 0
    out = capsys.readouterr().out
    m = re.search(r"Bundle written\s+(\S+\.zip)", out)
    assert m, out
    from pathlib import Path
    assert Path(m.group(1)).exists()
    assert out.index("Bundle written") < out.index("support code")


def test_the_local_file_survives_both_channels_failing(capsys, cli, monkeypatch):
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setattr(research, "_post_bundle_to_ingest", lambda *a, **k: None)
    _one_run()
    assert research.cmd_send_logs(assume_yes=True) == 0
    out = capsys.readouterr().out
    assert "Nothing could be sent" in out
    assert "--doctor" in out, "no next step offered"
    m = re.search(r"(\S+support-[0-9A-HJKMNP-TV-Z]{8}\.zip)", out)
    assert m, out
    from pathlib import Path
    assert Path(m.group(1)).exists(), "the floor was not left standing"


def test_the_failure_block_repeats_the_path_where_a_reader_will_look(capsys, cli,
                                                                    monkeypatch):
    """⛔ Found by mutation. The earlier "Bundle written" line already contains
    the path, so a regex over the whole output passes with the closing line
    deleted — and the closing line is the one a person reads after being told
    nothing could be sent."""
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setattr(research, "_post_bundle_to_ingest", lambda *a, **k: None)
    _one_run()
    research.cmd_send_logs(assume_yes=True)
    out = capsys.readouterr().out
    m = re.search(r"(\S+support-[0-9A-HJKMNP-TV-Z]{8}\.zip)", out)
    assert m, out
    path = m.group(1)
    assert out.count(path) >= 2, (
        "the path is named once, at the top, and not again where the reader "
        "actually needs it")
    assert path in out[out.index("Nothing could be sent"):]


def test_a_bundle_that_left_things_out_says_so(capsys, cli, monkeypatch):
    """⛔ Found by mutation. Silent truncation reads as complete coverage, and
    the thing quietly left out is the OLDEST run — which on a busy machine is
    exactly the one somebody is asking about."""
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 10,
                                           "runCount": 2, "sessionCount": 0,
                                           "uncompressedBytes": 10,
                                           "droppedForSize": ["r1", "r2"],
                                           "sourcesRefused": []})
    research.cmd_send_logs(assume_yes=True)
    out = capsys.readouterr().out
    assert "2 older item(s) left out for size" in out, out


def test_a_total_failure_still_exits_zero(cli, monkeypatch):
    """⭐ The local file IS a successful outcome — it is what a person attaches
    to an email when their network is the thing that is broken."""
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setattr(research, "_post_bundle_to_ingest", lambda *a, **k: None)
    assert research.cmd_send_logs(assume_yes=True) == 0


def test_a_bundle_that_cannot_be_built_says_where_the_raw_logs_are(capsys, cli,
                                                                   monkeypatch):
    def _boom(dest, **k):
        raise OSError("no space left on device")

    monkeypatch.setattr(research, "_build_log_bundle", _boom)
    assert research.cmd_send_logs(assume_yes=True) == 1
    out = capsys.readouterr().out
    assert "Could not build" in out
    assert str(research._logs_root()) in out


# ══ 3. the ladder, in order ════════════════════════════════════════════
def test_the_authenticated_route_is_tried_first(capsys, cli):
    _one_run()
    research.cmd_send_logs(assume_yes=True)
    assert cli["uploads"] == [("user-rocky", "d-1", cli["uploads"][0][2])]
    assert cli["posts"] == [], "it went to the open route while the account worked"
    assert "your account" in capsys.readouterr().out


def test_no_token_falls_through_to_our_own_host(capsys, cli, monkeypatch):
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    _one_run()
    assert research.cmd_send_logs(assume_yes=True) == 0
    out = capsys.readouterr().out
    assert cli["uploads"] == []
    assert len(cli["posts"]) == 1
    assert "superresearch.io" in out
    assert "could not sign in" in out


def test_a_PAIRED_machine_also_falls_through_when_the_upload_dies(capsys, cli,
                                                                  monkeypatch):
    """⛔⛔ THE FOUNDING CASE. Paired, with Google DNS dead. An unpaired-only
    fallback would have excluded exactly this machine."""
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: None)
    _one_run()
    assert research.cmd_send_logs(assume_yes=True) == 0
    assert len(cli["posts"]) == 1, "a paired machine was denied the open route"
    assert "superresearch.io" in capsys.readouterr().out


def test_the_support_code_is_printed_only_after_something_landed(capsys, cli,
                                                                monkeypatch):
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setattr(research, "_post_bundle_to_ingest", lambda *a, **k: None)
    research.cmd_send_logs(assume_yes=True)
    out = capsys.readouterr().out
    assert "support code" not in out, (
        "a code was handed out for a bundle that is nowhere — quoting it would "
        "lead a support conversation to an empty bucket")


def test_the_printed_code_is_the_one_the_object_was_stored_under(capsys, cli):
    _one_run()
    research.cmd_send_logs(assume_yes=True)
    out = capsys.readouterr().out
    m = re.search(r"support code is\s+(\S+)", out)
    assert m, out
    code = re.sub(r"\x1b\[[0-9;]*m", "", m.group(1))
    assert cli["uploads"][0][2] == code
    assert research._SUPPORT_CODE_RE.match(code), code


def test_the_code_the_SERVER_minted_is_the_one_printed(capsys, cli, monkeypatch):
    """⛔ The open route mints its own code and ignores ours, because on that path
    there is no uid and no deviceId to scope an object under — a caller-chosen
    folder name would let anyone who learned a code overwrite the bundle it
    names. Printing our local code would send a person into a support
    conversation quoting something that indexes nothing."""
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setattr(research, "_post_bundle_to_ingest",
                        lambda p, c, email=None: "SRVR1234")
    research.cmd_send_logs(assume_yes=True)
    out = capsys.readouterr().out
    m = re.search(r"support code is\s+(\S+)", out)
    assert m, out
    assert re.sub(r"\x1b\[[0-9;]*m", "", m.group(1)) == "SRVR1234"


def test_the_email_is_optional_and_rides_only_the_open_route(cli, monkeypatch):
    """⛔ Unverified and typed by somebody already having a bad time — a typo's
    failure mode IS the failure being fixed. Never a key, never the identity."""
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    research.cmd_send_logs(assume_yes=True, email="rocky@example.com")
    assert cli["posts"][0][1] == "rocky@example.com"


# ══ 4. the row appears late, never never ═══════════════════════════════
def test_a_row_that_cannot_be_written_is_parked(cli, monkeypatch):
    monkeypatch.setattr(research, "_write_log_bundle_status",
                        lambda *a, **k: False)
    monkeypatch.setattr(research, "_open_log_bundle_row", lambda *a, **k: False)
    _one_run()
    research.cmd_send_logs(assume_yes=True)
    assert len(cli["parked"]) == 1
    assert cli["parked"][0][2]["status"] == "done"


def test_a_row_whose_OPEN_failed_is_parked_too(cli, monkeypatch):
    """⛔ Found 2026-08-18. The row is opened at 'collecting' before the upload
    and advanced afterwards, so there are now TWO writes that can fail. Parking
    only on the second would lose every send whose open was refused — and the
    row is the ONLY thing Clear Shared Logs can see."""
    monkeypatch.setattr(research, "_open_log_bundle_row", lambda *a, **k: False)
    _one_run()
    research.cmd_send_logs(assume_yes=True)
    assert len(cli["parked"]) == 1


def test_parked_rows_are_replayed_and_then_forgotten(monkeypatch):
    written = []
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_write_log_bundle_status",
                        lambda o, c, patch, create=False:
                        written.append((o, c, patch.get("status"))) or True)
    research._queue_log_bundle_row("user-rocky", "7QK4M2XZ", {"status": "done"},
                                   device_id="d-1")
    research._queue_log_bundle_row("user-rocky", "MJ72K62P", {"status": "done"},
                                   device_id="d-1")
    assert research._drain_queued_log_bundle_rows() == 2
    # ⛔⛔ TWO writes per row, in this order. The rule only permits a CREATE whose
    # status is 'collecting', so replaying the patch alone as a create is what
    # production refuses — the defect the emulator caught on 2026-08-18, which
    # this replay path was itself reproducing.
    assert [w[2] for w in written] == ["collecting", "done", "collecting", "done"], written
    assert not research._queued_bundle_rows_path().exists()
    assert research._drain_queued_log_bundle_rows() == 0


def test_a_row_that_still_cannot_be_written_stays_parked(monkeypatch):
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_write_log_bundle_status", lambda *a, **k: False)
    research._queue_log_bundle_row("user-rocky", "7QK4M2XZ", {"status": "done"})
    assert research._drain_queued_log_bundle_rows() == 0
    assert research._queued_bundle_rows_path().exists(), "the row was lost"


def test_the_drain_is_a_no_op_with_no_firestore(monkeypatch):
    monkeypatch.setattr(research, "_firebase_db", None)
    research._queue_log_bundle_row("user-rocky", "7QK4M2XZ", {"status": "done"})
    assert research._drain_queued_log_bundle_rows() == 0
    assert research._queued_bundle_rows_path().exists()


def test_the_drain_runs_on_every_worker_not_on_an_outage_edge():
    """⛔ A `--send-logs` run from the terminal has no Firestore client at all, so
    it parks its row even when nothing was ever down. An outage-cleared edge
    would never fire for it."""
    src = inspect.getsource(research._firebase_reconnect_loop)
    assert "_drain_queued_log_bundle_rows()" in src
    clear = inspect.getsource(research._clear_firestore_down)
    assert "_drain_queued_log_bundle_rows" not in clear


# ══ 5. the open route's own limits ═════════════════════════════════════
def test_the_ingest_route_refuses_an_oversized_body_locally(monkeypatch, tmp_path):
    posted = []

    class _Requests:
        RequestException = RuntimeError

        @staticmethod
        def post(*a, **k):
            posted.append(a)
            raise AssertionError("should never be reached")

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    big = tmp_path / "b.zip"
    big.write_bytes(b"x" * 64)
    monkeypatch.setattr(research, "BUNDLE_INGEST_MAX_BYTES", 8)
    assert research._post_bundle_to_ingest(big, "7QK4M2XZ") is None
    assert posted == []


def test_the_ingest_post_carries_the_install_id_and_the_code(monkeypatch, tmp_path):
    seen = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"supportCode": "7QK4M2XZ"}

    class _Requests:
        RequestException = RuntimeError

        @staticmethod
        def post(url, headers=None, data=None, timeout=None):
            seen["url"] = url
            seen["headers"] = dict(headers or {})
            return _Resp()

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    bundle = tmp_path / "b.zip"
    bundle.write_bytes(b"PK")
    out = research._post_bundle_to_ingest(bundle, "7QK4M2XZ", email="a@b.c")
    assert out == "7QK4M2XZ"
    assert seen["url"].endswith("/api/logs/ingest")
    assert seen["headers"]["X-Support-Code"] == "7QK4M2XZ"
    assert seen["headers"]["Content-Type"] == research.BUNDLE_CONTENT_TYPE
    assert seen["headers"]["X-Install-Id"]
    assert seen["headers"]["X-Contact-Email"] == "a@b.c"


def test_a_refusal_from_the_route_is_not_reported_as_a_send(monkeypatch, tmp_path):
    """⛔ Found by mutation: nothing exercised a non-200 from the open route, so
    a 413 or a 429 would have been announced to the user as delivered."""
    class _Resp:
        def __init__(self, status):
            self.status_code = status
            self.text = "too large"

        def json(self):
            return {}

    for status in (400, 413, 429, 500):
        class _Requests:
            RequestException = RuntimeError

            @staticmethod
            def post(url, headers=None, data=None, timeout=None):
                return _Resp(status)

        monkeypatch.setitem(sys.modules, "requests", _Requests)
        bundle = tmp_path / "b.zip"
        bundle.write_bytes(b"PK")
        assert research._post_bundle_to_ingest(bundle, "7QK4M2XZ") is None, status


def test_no_email_means_no_header_rather_than_an_empty_one(monkeypatch, tmp_path):
    seen = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {}

    class _Requests:
        RequestException = RuntimeError

        @staticmethod
        def post(url, headers=None, data=None, timeout=None):
            seen["headers"] = dict(headers or {})
            return _Resp()

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    bundle = tmp_path / "b.zip"
    bundle.write_bytes(b"PK")
    research._post_bundle_to_ingest(bundle, "7QK4M2XZ")
    assert "X-Contact-Email" not in seen["headers"]


def test_an_unreachable_host_is_a_None_not_an_exception(monkeypatch, tmp_path):
    class _Requests:
        RequestException = RuntimeError

        @staticmethod
        def post(*a, **k):
            raise RuntimeError("Failed to resolve 'superresearch.io'")

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    bundle = tmp_path / "b.zip"
    bundle.write_bytes(b"PK")
    assert research._post_bundle_to_ingest(bundle, "7QK4M2XZ") is None


# ══ 6. the doctor now names the command, and probes the host it uses ═══
def test_the_doctor_probes_the_host_the_upload_actually_uses():
    hosts = [h for h, _why, _kind in research._DOCTOR_NET_TARGETS]
    assert "firebasestorage.googleapis.com" in hosts, (
        "the bundle upload rides this host; a machine that reaches firestore but "
        "not storage is a different diagnosis")
    assert "securetoken.googleapis.com" in hosts


def test_the_command_is_dispatched_before_the_doctor():
    """A person reads the doctor's hand-over line and types this next."""
    src = inspect.getsource(research.main)
    assert src.index("if args.send_logs:") < src.index("if args.doctor:")
