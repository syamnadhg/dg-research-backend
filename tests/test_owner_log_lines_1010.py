"""The lines that explain a run's fate always reach the owner's log.

⛔⛔ WHAT WAS WRONG (wave 10.10, found by wave 10.9's last repair round). Wave
10.9 kept an incognito run's own lines out of `backend.log`: while such a run is
armed, every line not marked as the machine's is withheld from the console and
written only into the run's folder — which is deleted when the run ends. Four
standing loops were deliberately NOT marked as machine lines, because each
explains a run's fate and the run's folder is where that belongs: the Firestore
reconnect loop, the revoked-credential loop, the device-command listener and
the worker watchdog. So for as long as a private run was armed, a revoked
credential, a Reset Backend or a watchdog kill vanished from the computer
owner's log — exactly the lines that owner needs.

⭐ HELD BY THE LINE'S ORIGIN, NOT BY A MARKING. The branch first added a third
log scope for these four ("owner lines"). Wave 10.9's last repair, which shipped
first, made the console decide by where a line CAME FROM (`_LOG_RUN`, set around
exactly the run's own work), and none of these four is a run's work: the server
starts the two loops, the SDK's own thread runs the device-command callback,
and the worker writes the watchdog's verdict outside the pipeline's task. So
their lines carry no run origin and reach the owner's log, and — being
unmarked — still reach the armed run's folder, so an ordinary run's folder says
exactly what it said before (the 08-24 decision in
`test_machine_log_scope_0824.py` still holds). The third scope was dropped at
the integration; these pins now hold that the origin rule covers each loop.

⛔ AND THEY CARRY NO TOPIC. Every line these loops write names a run, if at all,
by its research id prefix or its queue folder name — and a private run's folder
name is minted without the topic (`_mint_run_id`).

Each loop is EXECUTED here with a private run armed. Each test fails if the
console goes back to judging a line by the run that is armed, and each loses
the run's folder if the loop is marked as the machine's.
"""
import asyncio
import json
import types

import pytest

import research

INCOG = "incog_1758400000000_2"


class _Sink:
    """An armed run's log capture — a private one unless told otherwise."""

    def __init__(self, research_id=INCOG, meta_path=None):
        self.research_id = research_id
        self.meta_path = meta_path
        self.lines = []

    def note_line(self, line, level):
        self.lines.append(line)


class _Stop(BaseException):
    """⛔ NOT an `Exception`: the loops swallow those to survive a bad pass."""


@pytest.fixture()
def armed(monkeypatch):
    """A private run's folder armed, as it is for the whole of that run. Its
    ORIGIN is not set here: the run's own work carries it, in its own task,
    and the loops below are not that work."""
    assert research._LOG_RUN.get() is None, "a test before this one leaked a run origin"
    sink = _Sink()
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [sink])
    monkeypatch.setattr(research, "_fb_research_id", None)
    return sink


def _printed(capsys, fragment):
    return [ln for ln in capsys.readouterr().out.splitlines() if fragment in ln]


# ══ 1. the rule these loops rest on ═══════════════════════════════════════

def test_the_private_runs_own_line_is_withheld(armed, capsys):
    """⭐ POLARITY FIRST: the armed run really is one whose own lines stay off
    the owner's log — so the loops' lines reaching it below are not a console
    that prints everything."""
    token = research._LOG_RUN.set(INCOG)
    try:
        research.log("about the private run")
    finally:
        research._LOG_RUN.reset(token)
    assert _printed(capsys, "about the private run") == []
    assert any("about the private run" in ln for ln in armed.lines)


def test_a_line_with_no_run_origin_reaches_the_console_and_still_the_run(armed, capsys):
    """⭐ BOTH HALVES, which is what the dropped third scope was for: the
    owner's log gets it, and the armed run's folder keeps it."""
    research.log("[reconnect] the machine's own business")
    assert len(_printed(capsys, "the machine's own business")) == 1
    assert any("the machine's own business" in ln for ln in armed.lines)


# ══ 2. each loop, executed with a private run armed ═══════════════════════

def _fake_asyncio(monkeypatch):
    async def _sleep(_sec):
        raise _Stop()
    monkeypatch.setattr(research, "asyncio", types.SimpleNamespace(
        sleep=_sleep, to_thread=asyncio.to_thread,
        CancelledError=asyncio.CancelledError))


def test_the_reconnect_loop_s_outage_line_reaches_the_owner(armed, monkeypatch, capsys):
    """⛔⛔ AN OUTAGE IS WHY A RUN'S COMMANDS STOPPED ARRIVING. The owner must see
    it in backend.log even while a private run is armed."""
    _fake_asyncio(monkeypatch)
    monkeypatch.setattr(research.tm, "flush_in_background", lambda *a, **k: None)
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(research, "_firebase_down_reason", "transient")
    monkeypatch.setattr(research, "_mark_firestore_down", lambda *a, **k: None)
    monkeypatch.setattr(research, "init_firebase", lambda: False)
    monkeypatch.setattr(research, "_firestore_outage_notice", lambda **kw: [])
    with pytest.raises(_Stop):
        asyncio.run(research._firebase_reconnect_loop())
    assert len(_printed(capsys, "[reconnect] Firestore unreachable")) == 1
    assert any("[reconnect] Firestore unreachable" in ln for ln in armed.lines), (
        "the run's own folder lost the line that explains its silence")


def test_the_revoked_credential_loop_reaches_the_owner(armed, monkeypatch, capsys):
    _fake_asyncio(monkeypatch)
    monkeypatch.setattr(research, "_firebase_db", object())
    with pytest.raises(_Stop):
        asyncio.run(research._revoked_recovery_loop())
    assert len(_printed(capsys, "[relink] watcher armed")) == 1
    assert any("[relink] watcher armed" in ln for ln in armed.lines)


def test_a_device_command_reaches_the_owner(armed, monkeypatch, capsys):
    """⛔⛔ A RESET BACKEND IS WHY THE ARMED RUN DIED. The listener runs on the
    SDK's own thread, which starts with no run origin."""
    captured = {}

    class _Col:
        def on_snapshot(self, cb):
            captured["cb"] = cb
            return object()

    class _Chain:
        def collection(self, _n):
            return _Col() if _n == "commands" else self

        def document(self, _n):
            return self

    monkeypatch.setattr(research, "_firebase_db", _Chain())
    monkeypatch.setattr(research, "_device_cmd_watch", None)
    monkeypatch.setattr(research, "_fs_where",
                        lambda *a, **k: types.SimpleNamespace(stream=lambda: []))
    research._start_device_command_listener("uid-1", "dev-1")
    deleted = []
    doc = types.SimpleNamespace(
        id="d1", to_dict=lambda: {"action": "noop-1010"},
        reference=types.SimpleNamespace(delete=lambda: deleted.append("d1"),
                                        update=lambda _d: None))
    change = types.SimpleNamespace(type=types.SimpleNamespace(name="ADDED"),
                                   document=doc)
    capsys.readouterr()
    captured["cb"](None, [], None)          # the first attach: nothing waiting
    captured["cb"](None, [change], None)    # a live command
    assert deleted == ["d1"], "the fake command never reached the handler"
    assert len(_printed(capsys, "[device-cmds] received action='noop-1010'")) == 1
    assert any("received action='noop-1010'" in ln for ln in armed.lines)


def test_the_worker_watchdog_s_verdict_reaches_the_owner(armed, monkeypatch, capsys,
                                                         tmp_path):
    """⛔⛔ A WATCHDOG KILL IS THE LAST WORD ON A RUN. Executed through the real
    `_job_worker` closure rebuilt from `run_server`, with the pipeline replaced
    by one that never finishes, framed the way `run_pipeline_captured` frames
    it — its private origin set inside its own task — and a capture still
    armed when the verdict is written. The verdict is the worker's, outside the
    pipeline's task, so it carries no origin and the owner sees it.

    ⚠ In the ordinary shape the capture has already closed by then (the
    watchdog awaits the cancelled pipeline first), so the line reached the
    owner anyway; this holds it whatever is still armed."""
    code = next((c for c in research.run_server.__code__.co_consts
                 if isinstance(c, types.CodeType) and c.co_name == "_job_worker"), None)
    assert code is not None, "the job worker is no longer a closure of run_server"

    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    armed.meta_path = meta
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    exits = []

    async def _pipeline(**kw):
        research._RUN_LOG_SINKS.append(armed)       # armed, and never disarmed
        origin = research._LOG_RUN.set(kw["research_id"])
        try:
            research.log("the private run's own line")
            await asyncio.Event().wait()
        finally:
            research._LOG_RUN.reset(origin)

    class _Queue:
        def __init__(self):
            self.jobs = [{"uid": "u1", "research_id": INCOG, "run_id": "incognito_x",
                          "topic": "a private subject"}]

        async def get(self):
            if not self.jobs:
                raise _Stop()
            return self.jobs.pop(0)

        def task_done(self):
            pass

    async def _nothing(*a, **k):
        return None

    async def _fast_sleep(_sec):
        await asyncio.sleep(0)

    cells = {
        "WORKER_OUTER_TIMEOUT_SEC": 10,
        "_flip_queued_to_ongoing": lambda *a, **k: None,
        "_job_queue": _Queue(),
        "_persist_pending_queue": lambda *a, **k: None,
        "_recompute_queue_positions": lambda *a, **k: None,
        "_rescan_queue_for_unclaimed": _nothing,
    }
    env = dict(research.__dict__)
    env.update(
        asyncio=types.SimpleNamespace(
            sleep=_fast_sleep, ensure_future=asyncio.ensure_future,
            create_task=asyncio.create_task, TimeoutError=asyncio.TimeoutError,
            CancelledError=asyncio.CancelledError),
        run_pipeline_captured=_pipeline,
        _firebase_db=None,
        load_device_id=lambda: None,
        _pending_enq_dec=lambda: None,
        _write_worker_lock=lambda *a, **k: None,
        _delete_worker_lock=lambda *a, **k: None,
        _clear_current_run_id_best_effort=lambda *a, **k: None,
        _recompute_deferred_queue_positions=lambda *a, **k: None,
        _schedule_server_exit=lambda source, **k: exits.append(source),
    )
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    worker = types.FunctionType(code, env, "_job_worker", None,
                                tuple(types.CellType(cells[n]) for n in code.co_freevars))
    research._controls.reset()
    try:
        with pytest.raises(_Stop):
            asyncio.run(worker())
    finally:
        research._controls.reset()
    assert exits == ["worker-watchdog"], "the watchdog never fired"
    out = capsys.readouterr().out
    # ⭐ POLARITY: the pipeline's own line WAS the private run's, and held back.
    assert "the private run's own line" not in out
    assert any("the private run's own line" in ln for ln in armed.lines)
    verdict = [ln for ln in out.splitlines() if "[worker-watchdog] Pipeline exceeded" in ln]
    assert len(verdict) == 1, "the watchdog's verdict never reached the owner's log"
    assert "a private subject" not in verdict[0]
    assert any("[worker-watchdog]" in ln for ln in armed.lines)
