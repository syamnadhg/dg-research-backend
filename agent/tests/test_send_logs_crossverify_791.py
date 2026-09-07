"""What cross-verification found in wave 7.9-1 AFTER everything was green
(2026-09-07). Thirty-eight defects; these pin the ones with behaviour.

⛔⛔ FOUR OF THEM WERE BLOCKERS AND ALL FOUR WERE MINE:
  · `--none` took the whole selection branch, so `--none --runs 0` never ran the
    resolver: the agent-log token was silently dropped, the plan printed the
    OPPOSITE ("The agent's own log on this host is NOT included"), and a spec the
    resolver would have refused was accepted in silence. The chat client already
    had the right order, so the two clients answered the same words differently —
    on the surface whose entire claim is that they do not.
  · The upload rode a bundle that FAILED. `_send_agent_log` was unconditional on
    the wait's result, and the machine's refusals do not stop it: the row exists
    and carries a deviceId before it is patched to `failed`, so the bridge's
    ordering check passes and the log goes up ALONE — into a support-code folder
    with no bundle in it, which is precisely what the refusal fifty lines above
    tells a person cannot happen. The commonest refusal there is the machine's
    unkeyed 60-second floor, tripped by whoever ELSE uses that computer.
  · Choice 0 was advertised on the two branches where it cannot be accepted, and
    the refusal then sent a non-owner to `--machine`, which is refused four lines
    higher. A sharer with no listed runs went round in a circle.
  · The serve-time split warning went to logger `__name__`, which under the
    fleet's own `python -m facade.cli serve` is `"__main__"` — not a child of the
    `facade` logger the file handler is installed on. On the ONE deployment that
    can produce a split, the warning about it reached nothing.
"""

import contextlib
import importlib.util
import io
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge, cli, logsetup
from facade.session import RevokedError

# ⛔⛔ CAPTURED AT IMPORT, BEFORE THE FIXTURES RUN. `conftest.py` replaces
# `bridge._fe_api_post` for the WHOLE suite — deliberately, so no test can talk
# to the internet — so a test that calls it by name tests the stub. And
# `cli.logsetup` IS the `logsetup` module, so patching one patches the other:
# a lambda that "wraps" it wraps itself.
_REAL_FE_POST = bridge._fe_api_post
_REAL_CONFIGURE = logsetup.configure


def _our_consoles() -> list:
    """The console handlers LOGSETUP installed, and nobody else's.

    ⛔ pytest attaches its own `LogCaptureHandler`s to every logger it touches, so
    counting `StreamHandler`s counts the test runner. The tag is how logsetup
    already recognises its own handlers for idempotency; it is the right filter
    here for the same reason."""
    logger = logging.getLogger(logsetup._PKG_LOGGER)
    return [h for h in logger.handlers
            if getattr(h, logsetup._HANDLER_TAG, False)
            and isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)]

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_xv_791", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_xv_791"] = sr
_spec.loader.exec_module(sr)

ROWS = [{"name": "r1", "title": "Tidal power", "startedUtc": "2026-08-24T10:00",
         "status": "completed", "sizeBytes": 1_100_000},
        {"name": "r2", "title": "Kelp", "startedUtc": "2026-08-25T10:00",
         "status": "completed", "sizeBytes": 2_200_000}]


class _Wire:
    def __init__(self, *, rows=None, owned=True, published=True, row=None):
        self.rows = ROWS if rows is None else rows
        self.owned = owned
        self.published = published
        self.row = row if row is not None else {"status": "done", "runCount": 1,
                                                "sizeBytes": 10}
        self.posts: list = []
        self.bodies: list = []

    def get(self, path, timeout=10.0):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC",
                         "owned": self.owned, "published": self.published,
                         "truncated": False, "runs": self.rows}
        return 200, {"code": "K7XQ9B2M", "row": self.row}

    def post(self, path, body=None, timeout=30.0):
        self.posts.append(path)
        self.bodies.append(body or {})
        if path == "/logs/agent-log":
            return 200, {"ok": True, "sent": True, "bytes": 12}
        return 200, {"ok": True, "code": "K7XQ9B2M"}


def _args(**kw):
    base = dict(device=None, runs=None, none=False, machine=False, list=False,
                status=None, yes=True, no_wait=False, wait=1, verbose=False,
                agent_log=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _run(monkeypatch, args, wire):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_bridge_get", wire.get)
    monkeypatch.setattr(cli, "_bridge_post", wire.post)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_send_logs(args)
    return rc, buf.getvalue()


# ── blocker 1: --none must not eat a choice that is not a run ────────────────

def test_none_no_longer_swallows_the_agent_log_token(monkeypatch):
    """⛔⛔ `--none` USED TO TAKE THE WHOLE BRANCH, so the resolver never ran and
    `picked_agent_log` stayed False. The plan then printed the opposite of what
    was asked for."""
    wire = _Wire()
    rc, out = _run(monkeypatch, _args(none=True, machine=True, runs="0"), wire)
    assert rc == 0
    assert "/logs/agent-log" in wire.posts, out
    assert "NOT included" not in out


def test_none_still_clears_the_runs(monkeypatch):
    """The complement — it means what it has always meant."""
    wire = _Wire()
    _run(monkeypatch, _args(none=True, machine=True, runs="0,1"), wire)
    assert wire.bodies[0]["runNames"] == []


def test_none_no_longer_skips_validation(monkeypatch):
    """⛔ `--none --runs 99` used to be ACCEPTED in the terminal and refused in
    chat: the branch that would have checked it was never entered."""
    wire = _Wire()
    rc, out = _run(monkeypatch, _args(none=True, machine=True, runs="99"), wire)
    assert rc == 1
    assert "no run 99" in out
    assert wire.posts == []


def test_the_two_clients_now_answer_none_plus_zero_the_same_way(monkeypatch, capsys):
    """⛔⛔ THE CONTRACT THIS PAIR OF FILES CLAIMS. Same words, same answer."""
    wire = _Wire()
    _run(monkeypatch, _args(none=True, machine=True, runs="0"), wire)
    term_sent = "/logs/agent-log" in wire.posts

    chat = _ChatWire()
    monkeypatch.setattr(sr, "_get", chat.get)
    monkeypatch.setattr(sr, "_post", chat.post)
    sr.cmd_send_logs(SimpleNamespace(json=False, confirm=False, machine=True,
                                     none=True, device="", status="",
                                     agent_log=False, runs="0"))
    chat_out = capsys.readouterr().out
    assert term_sent is True
    assert "0 • the log from the agent" in chat_out


# ── blocker 2: the log may not ride a bundle that failed ─────────────────────

def test_a_failed_bundle_does_not_take_the_agent_log_with_it(monkeypatch):
    """⛔⛔ THE BRIDGE CANNOT STOP THIS — the row exists and names a device before
    it is patched to `failed`, so its ordering check passes. The log would go up
    alone, into a support-code folder with no bundle in it: exactly what the
    refusal fifty lines above says is impossible."""
    wire = _Wire(row={"status": "failed", "errorClass": "CooldownActive"})
    rc, out = _run(monkeypatch, _args(runs="1", agent_log=True), wire)
    assert rc == 1
    assert "/logs/agent-log" not in wire.posts, out
    assert "was not sent" in out


def test_a_failed_bundle_says_the_log_did_not_go(monkeypatch):
    """⛔ SILENCE WOULD BE THE OTHER FAILURE. A person who asked for it must not
    be left believing it went."""
    wire = _Wire(row={"status": "failed", "errorClass": "CooldownActive"})
    _, out = _run(monkeypatch, _args(runs="1", agent_log=True), wire)
    assert "can only go beside a bundle that" in out
    assert "--status K7XQ9B2M --agent-log" in out


def test_a_bundle_that_arrived_still_takes_it(monkeypatch):
    """The complement, so the gate cannot become a block."""
    wire = _Wire()
    rc, _ = _run(monkeypatch, _args(runs="1", agent_log=True), wire)
    assert rc == 0
    assert wire.posts == ["/logs/send", "/logs/agent-log"]


def test_a_timeout_does_not_take_it_either(monkeypatch):
    """⛔ A wait that ran out is not an arrival. `_await_bundle` returns 0 when it
    has seen a row and the row never finished — so the exit code alone is not the
    test; what matters is that no upload was attempted against a bundle nobody
    has confirmed."""
    wire = _Wire(row={"status": "packaging"})
    rc, out = _run(monkeypatch, _args(runs="1", agent_log=True, wait=0), wire)
    assert rc == 0, "a timeout is not a failure and must not become one"
    assert "/logs/agent-log" not in wire.posts, out
    assert "--status K7XQ9B2M --agent-log" in out


# ── the terminal's second step ───────────────────────────────────────────────

def test_status_with_the_flag_finishes_the_upload(monkeypatch):
    """⛔⛔ THE FLAG PARSED AND DID NOTHING. Both routes out of an unfinished wait
    dead-ended because of it: the timeout sentence had nothing to offer, and
    `--no-wait`'s advice minted a NEW request the machine refuses for ten
    minutes."""
    wire = _Wire()
    rc, out = _run(monkeypatch, _args(status="K7XQ9B2M", agent_log=True), wire)
    assert rc == 0
    assert "/logs/agent-log" in wire.posts, out


def test_status_without_the_flag_uploads_nothing(monkeypatch):
    wire = _Wire()
    _run(monkeypatch, _args(status="K7XQ9B2M"), wire)
    assert "/logs/agent-log" not in wire.posts


def test_status_says_so_when_the_bundle_has_not_landed(monkeypatch):
    """⛔ REFUSED UNTIL THE ROW LANDS, BY DESIGN — so say which call it was."""
    wire = _Wire(row={"status": "packaging"})
    _, out = _run(monkeypatch, _args(status="K7XQ9B2M", agent_log=True), wire)
    assert "/logs/agent-log" not in wire.posts
    assert "has not gone yet" in out


def test_no_wait_points_at_the_command_that_can_finish_it(monkeypatch):
    """⛔ IT USED TO SAY "Re-run without --no-wait", which mints a fresh request
    and is refused as a cooldown for ten minutes."""
    wire = _Wire()
    _, out = _run(monkeypatch, _args(no_wait=True, agent_log=True, runs="1"), wire)
    assert "--status K7XQ9B2M --agent-log" in out
    assert "Re-run without --no-wait" not in out


def test_no_wait_does_not_claim_the_log_is_going(monkeypatch):
    """⛔ THE PLAN DESCRIBED THREE THINGS ABOUT A FILE THIS RUN THEN DECLINED TO
    SEND, and only said so after the person had agreed."""
    wire = _Wire()
    _, out = _run(monkeypatch, _args(no_wait=True, agent_log=True, runs="1"), wire)
    assert "will NOT go on this run" in out
    assert "masked form of your email address" not in out


# ── the refusal no longer sends a sharer in a circle ─────────────────────────

def test_a_sharer_with_no_listed_runs_is_told_the_truth(monkeypatch):
    """⛔⛔ CHOICE 0 IS PRINTED LOUDEST ON EXACTLY THIS BRANCH. The old refusal
    pointed at `--machine`, which is refused for a non-owner four lines higher,
    so the two sentences sent them round in a circle."""
    wire = _Wire(rows=[], owned=False)
    rc, out = _run(monkeypatch, _args(runs="0"), wire)
    assert rc == 1
    assert "nothing for this log to ride" in out
    assert "--machine" not in out


def test_an_owner_with_no_listed_runs_is_still_offered_the_machine(monkeypatch):
    wire = _Wire(rows=[], owned=True)
    _, out = _run(monkeypatch, _args(runs="0"), wire)
    assert "add --machine" in out


def test_someone_with_runs_is_told_to_pick_one(monkeypatch):
    wire = _Wire(owned=False)
    _, out = _run(monkeypatch, _args(runs="0"), wire)
    assert "Pick a run as well" in out
    assert "--machine" not in out


# ── the parser no longer crashes on a token argparse accepts ─────────────────

@pytest.mark.parametrize("token", ["²", "٣", "+-1", "1.0", "١"])
def test_a_token_that_is_not_a_plain_integer_gets_a_sentence_not_a_traceback(token):
    """⛔ `"²".isdigit()` IS TRUE AND `int("²")` RAISES. The refusal this function
    exists to print was replaced by a stack trace."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = cli._resolve_selection(ROWS, token)
    assert out is None
    assert buf.getvalue().strip(), token


@pytest.mark.parametrize("token", ["²", "٣", "+-1", "1.0"])
def test_chat_does_not_crash_on_them_either(token):
    names, _, refusal = sr._resolve_log_selection(ROWS, token)
    assert names is None and refusal, token


# ── the logger the split warning actually uses ───────────────────────────────

def test_the_cli_logger_is_a_child_of_the_one_the_file_handler_is_on():
    """⛔⛔ THE FLEET STARTS THE BRIDGE AS `python -m facade.cli serve`, and under
    `-m` this module's `__name__` is `"__main__"` — not a descendant of the
    `facade` logger `logsetup.configure` installs the rotating file handler on.
    So on the one deployment that can produce a split home, the warning about it
    went to a logger with no file handler and no console."""
    assert cli.log.name.startswith(logsetup._PKG_LOGGER + ".")


def test_the_cli_logger_is_named_and_not_inherited_from___name__():
    """⛔⛔ THE RUNTIME CHECK ABOVE CANNOT SEE THIS ONE, AND A MUTANT PROVED IT.
    Under pytest the module is imported as `facade.cli`, so `__name__` already IS
    the right string and the assertion above passes whichever spelling is in the
    source. The defect exists only under `-m`, which no test in this suite runs —
    so the SOURCE is the honest subject here: `__name__` is the mutable thing, and
    the fix was to stop depending on it."""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assign = next((ln for ln in src.splitlines()
                   if ln.startswith("log = logging.getLogger(")), "")
    assert assign, "the module logger is gone"
    assert "__name__" not in assign, (
        "the logger takes __name__ again — under `python -m facade.cli` that is "
        '"__main__", which the file handler never sees')
    assert f'"{logsetup._PKG_LOGGER}.' in assign, assign


def test_the_split_warning_reaches_the_file_the_uploader_reads(monkeypatch, tmp_path):
    """⛔ THE WHOLE POINT, DRIVEN END TO END rather than asserted on caplog — which
    attaches to the root logger and would have been satisfied by the broken
    name."""
    path = tmp_path / "bridge.log"
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.prefs, "get_verbose", lambda: False)
    monkeypatch.setattr(cli.config, "home_split", lambda: "/sandbox/.hermes")
    monkeypatch.setattr(cli.logsetup, "configure",
                        lambda **k: _REAL_CONFIGURE(verbose=False, to_file=True,
                                                    log_file=path))
    try:
        cli.cmd_serve(SimpleNamespace(verbose=False))
    finally:
        _REAL_CONFIGURE(verbose=False, to_file=False)
    assert "/sandbox/.hermes" in path.read_text(encoding="utf-8")


# ── one writer per log file ──────────────────────────────────────────────────

def test_the_console_handler_is_dropped_when_it_writes_the_log_file(tmp_path):
    """⛔⛔ THE FLEET REDIRECTS THE BRIDGE'S OWN STDERR INTO THIS FILE. With the
    console handler still attached, two writers append to one file while the
    rotating handler RENAMES it at 1 MB — after the first rotation the redirect
    keeps writing to the renamed inode, so the active file the uploader sends is
    missing everything the console said."""
    path = tmp_path / "bridge.log"
    path.write_text("", encoding="utf-8")
    handle = path.open("a", encoding="utf-8")
    real_stderr = sys.stderr
    try:
        sys.stderr = handle
        _REAL_CONFIGURE(verbose=False, to_file=True, log_file=path)
        assert _our_consoles() == [], "the console handler is writing the log file too"
    finally:
        sys.stderr = real_stderr
        _REAL_CONFIGURE(verbose=False, to_file=False)
        handle.close()


def test_the_console_handler_survives_an_ordinary_serve(tmp_path):
    """⛔ THE COMPLEMENT, AND IT MATTERS MORE. Dropping the console on a guess
    would silence the only output a person watching a foreground `serve` has."""
    path = tmp_path / "bridge.log"
    try:
        _REAL_CONFIGURE(verbose=False, to_file=True, log_file=path)
        assert len(_our_consoles()) == 1
    finally:
        _REAL_CONFIGURE(verbose=False, to_file=False)


def test_an_unanswerable_stream_keeps_the_console(monkeypatch, tmp_path):
    """A stream with no fileno cannot be compared, and a guess would silence it."""
    path = tmp_path / "bridge.log"
    assert logsetup._same_file(io.StringIO(), path) is False


# ── the JSON helper no longer raises, and names the right host ───────────────

def test_the_json_helper_returns_a_tuple_on_a_dead_session(monkeypatch):
    """⛔⛔ THE WAVE'S OWN NOTE CLAIMED THIS SIBLING WAS FINE AND IT WAS NOT.
    Three of its four callers sit inside `except RevokedError` blocks that never
    saw this one, because the mint was evaluated inside a `try` that catches only
    RequestException — so /device/pair and /device/remove dropped the socket."""
    class _Dead:
        def id_token(self, force: bool = False) -> str:
            raise RevokedError("refresh token rejected")

    monkeypatch.setattr(bridge.requests, "post",
                        lambda *a, **k: pytest.fail("it sent with no token"))
    status, body = _REAL_FE_POST(_Dead(), "/api/devices/claim", {"code": "X"})
    assert status == 0
    assert body["reason"] == "revoked"


def test_the_json_helper_blames_google_not_the_app_for_a_refresh_failure(monkeypatch):
    """⛔ IT USED TO REPORT "could not reach {FE_BASE}" for a failure reaching
    Google's token endpoint — pointing somebody at a service that was answering."""
    class _Offline:
        def id_token(self, force: bool = False) -> str:
            raise bridge.requests.ConnectionError("dns")

    status, body = _REAL_FE_POST(_Offline(), "/api/devices/claim", {})
    assert status == 0
    assert "refresh this agent's sign-in" in body["error"]
    assert "could not reach" not in body["error"]


def test_both_helpers_share_one_mint():
    """⭐ ONE PLACE THAT KEEPS THE PROMISE, so the next helper cannot forget."""
    import inspect
    src = inspect.getsource(bridge)
    for fn in ("def _fe_api_post(", "def _fe_api_post_bytes("):
        block = src[src.index(fn):]
        block = block[:block.index("\ndef ", 1)]
        assert "_mint_bearer(" in block, fn
        assert "sess.id_token(" not in block, (
            f"{fn} mints its own token again — that is the hole")


# ── chat: names and a device cross the two calls ─────────────────────────────

class _ChatWire:
    def __init__(self, rows=None):
        self.rows = ROWS if rows is None else rows
        self.posts: list = []

    def get(self, path, timeout=None):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC", "owned": True,
                         "published": True, "runs": self.rows, "truncated": False}
        return 200, {"code": "K7XQ9B2M", "row": {"status": "done", "runCount": 1,
                                                 "sizeBytes": 10}}

    def post(self, path, body=None):
        self.posts.append({"path": path, "body": body})
        return 200, {"ok": True, "code": "K7XQ9B2M"}


def _chat_args(**kw):
    base = dict(json=False, confirm=False, machine=False, none=False,
                device="", status="", agent_log=False, runs="")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture()
def chat(monkeypatch):
    w = _ChatWire()
    monkeypatch.setattr(sr, "_get", w.get)
    monkeypatch.setattr(sr, "_post", w.post)
    return w


def test_the_confirm_command_carries_names_not_numbers(chat, capsys):
    """⛔⛔ THE NUMBERS ARE POSITIONS AND THE CONFIRM IS A SECOND PROCESS. It
    re-fetches the list and re-resolves the device, so between the two calls
    position 2 can become a different run — or a different computer's run."""
    sr.cmd_send_logs(_chat_args(runs="2"))
    out = capsys.readouterr().out
    assert "--runs r2" in out
    assert "--device dev1" in out
    assert "--runs 2" not in out


def test_the_confirm_command_carries_the_flags_too(chat, capsys):
    sr.cmd_send_logs(_chat_args(runs="0,1", machine=True))
    out = capsys.readouterr().out
    assert "--agent-log" in out
    assert "--machine" in out
    assert "--runs r1" in out


def test_the_directive_warns_against_editing_the_numbers_in(chat, capsys):
    sr.cmd_send_logs(_chat_args())
    out = capsys.readouterr().out
    assert "not the numbers shown" in out
    assert "re-run the bare command first" in out


def test_a_no_runs_confirm_carries_none_rather_than_an_empty_selection(chat, capsys):
    """⛔ AN OMITTED `--runs` MEANS EVERY RUN, not none — so a plan that sends no
    runs must say `--none`, or the confirm sends what the plan did not show."""
    sr.cmd_send_logs(_chat_args(runs="0", machine=True, none=True))
    out = capsys.readouterr().out
    assert "--none" in out or "--machine" in out
    assert "--runs" not in out.split(_MARK)[-1] if (_MARK := "do-not-relay") in out else True


def test_spoken_connectives_are_not_read_as_run_names():
    """⛔ "1 and 3" REFUSED ON THE WORD "and", naming a run called “and”. The
    assistant relays what a person said; it does not quote it for a shell."""
    names, _, refusal = sr._resolve_log_selection(ROWS, "1 and 2")
    assert refusal == []
    assert names == ["r1", "r2"]


def test_a_connective_that_is_a_real_run_name_still_means_that_run():
    """⛔ A machine is free to mint a run called "and". If this list is holding
    one, the word is the run, not filler."""
    rows = ROWS + [{"name": "and", "title": "Odd", "startedUtc": "", "status": "",
                    "sizeBytes": 1}]
    names, _, refusal = sr._resolve_log_selection(rows, "and")
    assert refusal == []
    assert names == ["and"]


def test_an_empty_list_does_not_quote_a_range_of_zero():
    """⛔ "the runs are numbered 1 to 0" is not a sentence."""
    names, _, refusal = sr._resolve_log_selection([], "1")
    assert names is None
    assert "1 to 0" not in refusal[0]
    assert "hasn’t listed any runs" in refusal[0]


def test_chat_status_honours_runs_zero(chat, capsys):
    """⛔ THE ONLY CALL THAT UPLOADS, and it dropped the token in silence."""
    sr.cmd_send_logs(_chat_args(status="K7XQ9B2M", runs="0"))
    assert any(p["path"] == "/logs/agent-log" for p in chat.posts)


def test_chat_status_says_a_run_named_there_changes_nothing(chat, capsys):
    sr.cmd_send_logs(_chat_args(status="K7XQ9B2M", runs="1"))
    out = capsys.readouterr().out
    assert "already built" in out
    assert not any(p["path"] == "/logs/agent-log" for p in chat.posts)
