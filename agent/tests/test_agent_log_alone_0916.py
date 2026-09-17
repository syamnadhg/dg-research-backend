"""The agent's own log travels ALONE, with a support code of its own (wave 8).

⛔⛔ THE PERSON WHO MOST NEEDS TO SEND THIS FILE COULD NOT SEND IT. Every route to
support went through a research computer: the machine zips its own logs and
uploads them with its own device token, and the agent's log could only ride along
in the folder that bundle's row named. So the two commonest reasons to be reading
an agent log at all — no computer paired yet, or one you cannot reach — were
exactly the two states in which no bundle exists for it to ride. The client said
so in a sentence that was true about the transport and useless to the reader.

⛔⛔ AND IT CAME BACK WITH NO CODE. Every other send-logs hands somebody a number
to quote; this one did not, because it had no row of its own to take one from —
which is the difference between an artifact a person can forward to a developer
and a file that went somewhere nobody can name. The owner's instruction, 2026-09-16:
"every send logs gets a code … even that should be giving a code".

⛔ AND ONLY THE ACTIVE FILE WENT. The handler rotates at 1 MB with three backups,
so a problem that had already scrolled past a rotation was unsendable, and nothing
said so.
"""

import contextlib
import importlib.util
import json
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge, cli

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_alone_0916", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_alone_0916"] = sr
_spec.loader.exec_module(sr)


# ── the reader: the rotated copies come too ─────────────────────────────────

def _rotation(tmp_path, **files):
    """Write an agent log and any of its backups. Returns the active path."""
    active = tmp_path / "bridge.log"
    for name, body in files.items():
        (tmp_path / name.replace("_", ".")).write_bytes(body)
    return active


def test_the_rotated_backups_are_sent_too(monkeypatch, tmp_path):
    """⛔⛔ THE WHOLE REASON SOMEBODY SENDS THIS FILE IS USUALLY ALREADY IN THE
    PAST. The handler turns 1 MB over in a busy session, and the old reader took
    the active file and nothing else — so the evidence scrolled past the rotation
    and there was no way to ask for it."""
    _rotation(tmp_path, bridge_log=b"NEWEST\n", bridge_log_1=b"MIDDLE\n",
              bridge_log_3=b"OLDEST\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "bridge.log")
    got = bridge._read_agent_log_tail()
    for marker in (b"OLDEST", b"MIDDLE", b"NEWEST"):
        assert marker in got, marker
    # ⛔ OLDEST FIRST. A log read backwards is not a log, and the budget is spent
    # newest-first only so that what SURVIVES is the recent material.
    assert got.index(b"OLDEST") < got.index(b"MIDDLE") < got.index(b"NEWEST")


def test_each_file_is_named_where_it_starts(monkeypatch, tmp_path):
    """A reader handed four files under one name cannot tell where one ends."""
    _rotation(tmp_path, bridge_log=b"a\n", bridge_log_1=b"b\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "bridge.log")
    got = bridge._read_agent_log_tail().decode()
    assert "===== bridge.log.1 =====" in got
    assert "===== bridge.log =====" in got


def test_one_file_is_still_sent_byte_for_byte(monkeypatch, tmp_path):
    """⛔ A SEPARATOR ONLY WHERE THERE IS SOMETHING TO SEPARATE. With one file
    there is nothing to mark a boundary between, and adding a banner would mean
    what support receives is no longer what is on the disk."""
    _rotation(tmp_path, bridge_log=b"line one\nline two\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "bridge.log")
    assert bridge._read_agent_log_tail() == b"line one\nline two\n"


def test_the_budget_is_spent_on_the_most_recent_material(monkeypatch, tmp_path):
    """⛔ THE TAIL RULE, ONE LEVEL UP. Over the cap the oldest rotation is what
    gets dropped, not the newest — the same reasoning that makes a single oversized
    file read from its end."""
    _rotation(tmp_path, bridge_log=b"N" * 80 + b"\n", bridge_log_1=b"O" * 80 + b"\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "bridge.log")
    got = bridge._read_agent_log_tail(cap=110)
    assert b"N" in got
    assert b"O" not in got
    assert len(got) <= 110
    # ⛔⛔ AND THE OLDER FILE WAS REALLY CONSIDERED. The pre-wave reader never opened
    # a backup at all, so "the oldest rotation was dropped" and "no rotation was
    # ever read" produced the SAME bytes — this test passed against it. A banner is
    # only written when the multi-file path ran, so it tells the two apart.
    assert b"===== bridge.log =====" in got


def test_the_reader_looks_for_exactly_the_backups_the_handler_keeps(monkeypatch):
    """⛔⛔ TWO NUMBERS THAT MUST NOT DRIFT. A handler configured for more backups
    than this reader looks for would silently drop the oldest of them from every
    support bundle — silently, because the bundle would still arrive."""
    from facade import logsetup
    assert bridge._AGENT_LOG_BACKUPS == logsetup._FILE_BACKUPS


def test_a_missing_backup_is_skipped_rather_than_ending_the_read(monkeypatch, tmp_path):
    _rotation(tmp_path, bridge_log=b"NEW\n", bridge_log_2=b"OLD\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "bridge.log")
    got = bridge._read_agent_log_tail()
    assert b"OLD" in got and b"NEW" in got


def test_a_cap_too_tight_for_a_banner_still_sends_the_newest_line(monkeypatch, tmp_path):
    """⛔⛔ IT RETURNED b"" AND THE CALLER CALLED THAT "your log was empty". With two
    files and a cap under one banner's width, every read passed a NEGATIVE cap,
    every chunk came back empty, and the whole budget was spent on nothing — while
    the SAME cap on a one-file host returned the last whole line. Found by
    cross-verification, which ran it."""
    _rotation(tmp_path, bridge_log=b"AAAA\nBBBB\nCCCC\n", bridge_log_1=b"OLD1\nOLD2\n")
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "bridge.log")
    got = bridge._read_agent_log_tail(cap=8)
    assert got == b"CCCC\n", got
    # ⭐ AND IT IS NEVER WORSE THAN THE ONE-FILE HOST, which is the bound that makes
    # the fallback right rather than arbitrary.
    (tmp_path / "bridge.log.1").unlink()
    assert bridge._read_agent_log_tail(cap=8) == got


def test_nothing_anywhere_still_reads_as_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge.config, "log_path", lambda: tmp_path / "nope.log")
    assert bridge._read_agent_log_tail() == b""


# ── the bridge route ────────────────────────────────────────────────────────

def _route(monkeypatch, tmp_path, *, body, log=b"some lines\n",
           fe=(200, {"stored": True, "code": "SOLO7X2M"}), row=None):
    """Drive POST /logs/agent-log with an arbitrary body."""
    import threading
    from http.server import ThreadingHTTPServer
    import requests as _rq

    class FS:
        def __init__(self, tok):
            pass

        def get_log_bundle(self, uid, code):
            return row

    posted = {}

    def _fake_bytes(sess, path, blob, ctype, headers):
        posted.update(path=path, blob=blob, ctype=ctype, headers=headers)
        return fe

    p = tmp_path / "bridge.log"
    if log is not None:
        p.write_bytes(log)
    monkeypatch.setattr(bridge, "FirestoreRest", FS)
    monkeypatch.setattr(bridge, "_fe_api_post_bytes", _fake_bytes)
    monkeypatch.setattr(bridge.config, "log_path", lambda: p)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = _rq.post(f"http://127.0.0.1:{httpd.server_address[1]}/logs/agent-log",
                     json=body, timeout=10)
        return r, posted
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_standalone_needs_no_row_no_device_and_no_code(monkeypatch, tmp_path):
    """⛔⛔ IT ASKS FOR NO COMPUTER, WHICH IS THE POINT. `row=None` here is the
    person with nothing paired — the exact state the attached route answers 409
    for — and this one uploads."""
    r, posted = _route(monkeypatch, tmp_path, body={"standalone": True}, row=None)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "sent": True, "standalone": True,
                        "code": "SOLO7X2M", "bytes": len(b"some lines\n")}
    assert posted["path"] == "/api/logs/agent-log"
    # ⛔ THE MODE IS DECLARED AND NOTHING ELSE IS SENT WITH IT. A support code or a
    # device id alongside it is two requests in one, and the app refuses it.
    assert posted["headers"] == {"x-agent-log-mode": "standalone"}


def test_the_code_reaches_the_caller(monkeypatch, tmp_path):
    """⛔ THE OWNER'S ASK. Without it this is a file that went somewhere nobody can
    name, and the person cannot forward anything to a developer."""
    r, _ = _route(monkeypatch, tmp_path, body={"standalone": True},
                  fe=(200, {"stored": True, "code": "ABCD1234"}))
    assert r.json()["code"] == "ABCD1234"


def test_standalone_with_a_code_is_refused_rather_than_resolved(monkeypatch, tmp_path):
    """⛔⛔ TWO DIFFERENT THINGS WERE ASKED FOR. Picking one of them is how a log
    ends up in a folder the person did not expect."""
    r, posted = _route(monkeypatch, tmp_path,
                       body={"standalone": True, "code": "7QK4M2XZ"})
    assert r.status_code == 400
    assert r.json()["reason"] == "contradictory_request"
    assert posted == {}


def test_a_missing_standalone_flag_still_means_attach(monkeypatch, tmp_path):
    """⛔⛔ NEVER INFERRED FROM AN ABSENT CODE. A client that lost its support code
    must take the refusal rather than silently opening a fresh bundle under a code
    nobody was told about."""
    r, posted = _route(monkeypatch, tmp_path, body={})
    assert r.status_code == 400
    assert r.json()["error"] == "that isn't a support code"
    assert posted == {}


def test_an_empty_log_mints_nothing_and_says_so(monkeypatch, tmp_path):
    r, posted = _route(monkeypatch, tmp_path, body={"standalone": True}, log=b"")
    assert r.status_code == 200
    assert r.json()["sent"] is False
    assert r.json()["reason"] == "empty"
    assert posted == {}


def test_a_two_hundred_that_stored_nothing_is_not_a_send(monkeypatch, tmp_path):
    """⛔ A code that names nothing, or a sentence claiming the log went with no
    code under it, are both worse than saying it was empty."""
    r, _ = _route(monkeypatch, tmp_path, body={"standalone": True},
                  fe=(200, {"stored": False}))
    assert r.status_code == 200
    assert r.json()["sent"] is False


def test_an_app_failure_is_a_502_and_names_nothing_else(monkeypatch, tmp_path):
    r, _ = _route(monkeypatch, tmp_path, body={"standalone": True},
                  fe=(503, {"error": "store_failed"}))
    assert r.status_code == 502
    assert r.json()["reason"] == "agent_log_not_sent"


def test_a_revoked_session_says_so_rather_than_could_not_be_sent(monkeypatch, tmp_path):
    """The sentence a person can act on — the same one the attached path gives."""
    r, _ = _route(monkeypatch, tmp_path, body={"standalone": True},
                  fe=(401, {"reason": "revoked"}))
    assert r.status_code == 401
    assert "run /login again" in r.json()["error"]


# ── the two clients agree on what "only the agent log" means ────────────────

SPECS = [
    # (runs, agent_log, none, machine) -> is this the agent log ALONE?
    (("0", False, False, False), True),
    (("", True, True, False), True),
    (("0", False, True, False), True),
    (("0", True, True, False), True),
    ((" 0 ", False, False, False), True),
    # ⛔ BARE `--agent-log` IS "EVERYTHING, AND THE LOG AS WELL" — the runs default
    # to every listed row, so it is emphatically not the log alone.
    (("", True, False, False), False),
    (("0,1", False, False, False), False),
    (("1", True, False, False), False),
    # ⛔ `--machine` IS A COMPUTER'S MATERIAL, so there is a computer in it.
    (("0", False, True, True), False),
    (("", True, True, True), False),
    (("", False, False, False), False),
]


def test_list_means_send_nothing_in_both_clients():
    """⛔⛔ A LIVE REGRESSION THIS WAVE INTRODUCED, found by cross-verification,
    which ran it. `--list` is the one flag on this command that promises no side
    effect — "show me what it is holding, send nothing". The new early return sat
    ABOVE the `if args.list: return 0` short-circuit, so
    `send-logs --list --runs 0 -y` printed the standalone plan and UPLOADED."""
    for runs, agent_log, none in (("0", False, False), ("", True, True)):
        args = SimpleNamespace(runs=runs, agent_log=agent_log, none=none,
                               machine=False, device="", list=True)
        assert sr._agent_log_only_request(args) is False, (runs, agent_log, none)
        assert cli._agent_log_only_request(args) is False, (runs, agent_log, none)
        # ⛔ AND THE COMPLEMENT, so the new clause cannot swallow the feature: the
        # same request without --list is still the standalone send.
        args.list = False
        assert sr._agent_log_only_request(args) is True
        assert cli._agent_log_only_request(args) is True


@pytest.mark.parametrize("spec,want", SPECS)
def test_both_clients_read_the_same_request_the_same_way(spec, want):
    """⛔⛔ THE TWIN GUARD. `sr.py` is stdlib-only by contract and cannot import the
    facade, so this rule exists twice — and the two send-logs resolvers have
    already drifted once. Somebody who asks two clients the same thing must not get
    two answers."""
    runs, agent_log, none, machine = spec
    args = SimpleNamespace(runs=runs, agent_log=agent_log, none=none,
                           machine=machine, device="", list=False)
    assert sr._agent_log_only_request(args) is want, spec
    assert cli._agent_log_only_request(args) is want, spec


# ── the hint is an extra, never a gate ──────────────────────────────────────

def test_a_failed_lookup_costs_the_hint_and_not_the_send(monkeypatch, capsys):
    """⛔⛔ THIS IS THE WHOLE DISTINCTION. `/logs/runs` refuses somebody with no
    computer, and that person is who this branch exists for — so its answer may
    decorate the plan and may never decide whether the send happens."""
    posts = []
    monkeypatch.setattr(sr, "_get", lambda p, **k: (409, {"reason": "no_devices"}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (
        posts.append((p, b)) or (200, {"ok": True, "sent": True, "code": "SOLO7X2M"})))
    rc = sr.cmd_send_logs(SimpleNamespace(
        json=False, confirm=True, machine=False, none=True, device="",
        status="", agent_log=True, runs=""))
    out = capsys.readouterr().out
    assert rc == 0
    assert posts == [("/logs/agent-log", {"standalone": True})]
    assert "SOLO7X2M" in out
    assert "--machine" not in out


def test_someone_with_no_computer_is_told_this_door_exists(monkeypatch, capsys):
    """⛔⛔ THE SCREEN HAD NO DOOR IN IT. Every sentence on the no-computer refusal
    is about picking a computer, and somebody whose problem IS that they have none
    was left with nothing to do on the surface built for reporting problems."""
    monkeypatch.setattr(sr, "_get", lambda p, **k: (409, {"reason": "no_devices"}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (200, {}))
    rc = sr.cmd_send_logs(SimpleNamespace(
        json=False, confirm=False, machine=False, none=False, device="",
        status="", agent_log=False, runs=""))
    out = capsys.readouterr().out
    assert rc != 0
    assert "its own log on its own" in out
    assert "no computer needed" in out


def test_the_machine_offer_names_the_command_that_delivers_it(monkeypatch, capsys):
    """⛔⛔ AN OFFER WITH NOTHING BEHIND IT IS THE CIRCLE AGAIN. The plan tells an
    OWNER their computer's own logs can go in the same breath — and the only
    command on the screen sends the agent's log ALONE. An assistant relaying the
    offer had no way to carry it out, which is the same shape as the refusal that
    pointed a non-owner at a flag they would be refused for."""
    monkeypatch.setattr(sr, "_get", lambda p, **k: (200, {
        "deviceId": "d1", "deviceName": "Studio PC", "owned": True,
        "published": True, "runs": [], "truncated": False}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (200, {}))
    sr.cmd_send_logs(SimpleNamespace(
        json=False, confirm=False, machine=False, none=True, device="",
        status="", agent_log=True, runs=""))
    out = capsys.readouterr().out
    assert "Studio PC" in out
    assert "send-logs --confirm --machine --none --agent-log" in out


def test_a_sharer_is_offered_neither_the_machine_nor_its_command(monkeypatch, capsys):
    """⛔ THE OFFER IS STILL OWNER-ONLY — `--machine` is refused for anybody else,
    and so is the command that carries it."""
    monkeypatch.setattr(sr, "_get", lambda p, **k: (200, {
        "deviceId": "d1", "deviceName": "Studio PC", "owned": False,
        "published": True, "runs": [], "truncated": False}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (200, {}))
    sr.cmd_send_logs(SimpleNamespace(
        json=False, confirm=False, machine=False, none=True, device="",
        status="", agent_log=True, runs=""))
    out = capsys.readouterr().out
    assert "--machine" not in out


def test_the_json_plan_discloses_what_the_words_disclose(monkeypatch, capsys):
    """⛔⛔ `--json` PRINTS THE PAYLOAD *INSTEAD OF* THE LINES. A consent plan whose
    whole job is disclosure disclosed nothing at all on that path, and its
    `wouldSend: []` read as "nothing would be sent" about a call that sends a file.
    The relay reading JSON is relaying to a person either way."""
    monkeypatch.setattr(sr, "_get", lambda p, **k: (409, {"reason": "no_devices"}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (200, {}))
    sr.cmd_send_logs(SimpleNamespace(
        json=True, confirm=False, machine=False, none=True, device="",
        status="", agent_log=True, runs="", list=False))
    body = json.loads(capsys.readouterr().out)
    assert body["agentLogOnly"] is True
    assert body["agentLogWouldSend"] is True
    assert body["retentionDays"] == 30
    blob = " ".join(body["consentIncluded"]) + " " + " ".join(body["plan"])
    assert "signed in through this agent" in blob
    assert "rotated copies go too" in blob
    assert "masked form of your email address" in blob
    assert "support code of its own" in blob


def test_the_check_route_carries_the_facts_in_the_chat_client_too(monkeypatch, capsys):
    """⛔ THE ONLY GUARD FOR THIS READ cli.py's SOURCE and never looked at the chat
    client, so the same hole could reopen on the surface an assistant actually
    drives. Asserted on the OUTPUT, and on the order the person reads it in."""
    posts = []
    monkeypatch.setattr(sr, "_get", lambda p, **k: (200, {
        "code": "K7XQ9B2M",
        "row": {"status": "done", "runCount": 1, "sizeBytes": 10, "deviceId": "d1"}}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (
        posts.append(p) or (200, {"ok": True, "sent": True, "bytes": 12})))
    sr.cmd_send_logs(SimpleNamespace(
        json=False, confirm=False, machine=False, none=False, device="",
        status="K7XQ9B2M", agent_log=True, runs="", list=False))
    out = capsys.readouterr().out
    assert posts == ["/logs/agent-log"]
    assert "signed in through this agent" in out
    assert "rotated copies go too" in out
    # ⭐ ABOVE the result, which is the order that matters to the person reading it.
    assert out.index("signed in through this agent") < out.index("went up too")


def test_the_plan_names_no_computer_at_all(monkeypatch, capsys):
    """⛔ IT IS A DIFFERENT MACHINE, AND THE PLAN MAY NOT IMPLY OTHERWISE. Every
    other send-logs plan describes material leaving a research computer."""
    monkeypatch.setattr(sr, "_get", lambda p, **k: (409, {"reason": "no_devices"}))
    monkeypatch.setattr(sr, "_post", lambda p, b=None: (200, {}))
    sr.cmd_send_logs(SimpleNamespace(
        json=False, confirm=False, machine=False, none=True, device="",
        status="", agent_log=True, runs=""))
    out = capsys.readouterr().out
    assert "No research computer is involved" in out
    assert "deleted automatically 30 days after it arrives" in out
    assert "send-logs --confirm --agent-log --none" in out
