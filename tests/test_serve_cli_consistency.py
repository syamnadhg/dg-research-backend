"""`--serve`'s terminal output must belong to the same command set as the rest.

Measured against the live boot the owner ran (2026-08-05 23:42, `--serve` piped
through `tee`):

* `--help` puts SUPER RESEARCH on line 4; `--serve` put it on line **26**,
  behind the route dump, Firestore init, six background loops, queue
  rehydration and the device-command listener.
* FOUR log formats shared one stream — ours, a Firestore `UserWarning`, gRPC's
  C++ `I0805 …  fork_posix.cc:71]` writer (3×, one of them landing between the
  banner's rule and its identity strip), and uvicorn's `INFO:` lines with no
  timestamp and no level.
* Six `[INFO]   GET /api/runs …` lines pushed a static reference through the
  timestamped logger — something no other subcommand does.
* The idle pulse alternated ◆/◇ while both lines read "standing watch", so
  every other minute the log contradicted the CLI's own lexicon, in which ◇ is
  *quiescens* — resting.

Where a claim can be pinned by EXECUTION it is (the pulse text, the boot
preview, the filter, the help section, dictConfig under a real `dictConfig`).
Driving `run_server` itself would need a fake FastAPI + Firestore larger than
the change, so the two ordering claims inside it are pinned by SOURCE ORDER via
line numbers — stated here rather than implied.
"""
import inspect
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

import research
from conftest import code_only

REPO = Path(research.__file__).resolve().parent


# ── #193  The crown leads ────────────────────────────────────────────────────

def _lineno_of(needle: str, *, func=research.run_server) -> int:
    """Absolute line number of the first CODE line of `func` containing `needle`.

    ⚠ Comments are blanked first. The first draft of this helper scanned raw
    source and the probe-ordering test failed against a correct fix, because the
    comment I had just written next to the moved probe QUOTED the footer text it
    was ordered against — so the search matched my prose, five lines above the
    real footer. Same trap `code_only` exists for; it applies to line-number
    searches too, not just substring assertions.
    """
    src, start = inspect.getsourcelines(func)
    for i, line in enumerate(code_only("".join(src)).splitlines()):
        if needle in line:
            return start + i
    raise AssertionError(f"{needle!r} not found in {func.__name__}")


def test_the_wordmark_is_printed_before_any_boot_logging():
    """Order-in-source assertion: the crown must precede the first thing serve
    says about its own startup."""
    crown = _lineno_of('_branded_header("aegis"')
    first_log = _lineno_of('log(f"Starting API server on http')
    assert crown < first_log, (
        f"wordmark at line {crown} comes after the first boot log at {first_log}")


def test_the_identity_strip_comes_after_the_crown_not_with_it():
    """The strip reads the device doc, so it cannot move up next to the crown —
    it must still land after it, as beat two."""
    crown = _lineno_of('_branded_header("aegis"')
    strip = _lineno_of("_render_context_strip(_ctx_rows_serve)")
    assert crown < strip


def test_the_crown_is_printed_exactly_once():
    """Leading with it while the old late call remained would print the wordmark
    twice in one boot."""
    assert code_only(research.run_server).count('_branded_header("aegis"') == 1


def test_the_port_probe_cannot_split_the_banner():
    """The pre-bind probe used to sit between the identity strip and the
    "Listening for pipeline jobs" footer, so its WARN tore the banner in half.
    It must still precede the strip.

    The probe is no longer advisory — it resolves the conflict rather than
    logging "binding anyway" and letting uvicorn fail with a raw errno — so the
    anchor is `_reclaim_port`. The invariant is unchanged and matters more now:
    it can print several lines (stopping an earlier backend, or refusing by pid),
    and all of them belong above the strip."""
    probe = _lineno_of("asyncio.to_thread(_reclaim_port")
    strip = _lineno_of("_render_context_strip(_ctx_rows_serve)")
    footer = _lineno_of("Listening for pipeline jobs")
    assert probe < strip < footer


def test_boot_preview_names_the_arc_and_the_port(capsys):
    research._serve_boot_preview(8123)
    out = capsys.readouterr().out
    for beat in ("Firestore", "Queue", "Listeners", "API on :8123"):
        assert beat in out, f"{beat!r} missing from {out!r}"


# ── #194a  Firestore filters, fixed at source ────────────────────────────────

class _FakeQuery:
    def __init__(self):
        self.args = None
        self.kwargs = None

    def where(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        return self


def test_fs_where_uses_the_keyword_form():
    q = _FakeQuery()
    assert research._fs_where(q, "processed", "==", True) is q
    assert q.args == (), f"positional args leaked: {q.args!r}"
    assert set(q.kwargs) == {"filter"}


def test_fs_where_carries_field_op_and_value_through():
    """Read the filter's own accessors, not its repr — `FieldFilter.__repr__` is
    the default object repr, so a repr-based assertion passes no matter what the
    filter was built from."""
    q = _FakeQuery()
    research._fs_where(q, "status", "==", "ongoing")
    filt = q.kwargs["filter"]
    assert filt.field_path == "status"
    assert filt.op_string == "=="
    assert filt.value == "ongoing"


def test_no_positional_where_call_survives_anywhere():
    """The regression guard that matters: the warning came from OUR call sites,
    so the next one added must fail here rather than print into a banner.

    ⚠ Parsed with `ast`, not grepped. A text scan cannot tell a call from prose,
    and both this module's docstrings and `_fs_where`'s own quote the deprecated
    form verbatim — the first draft failed on its own documentation.
    """
    import ast
    tree = ast.parse(REPO.joinpath("research.py").read_text(encoding="utf-8"))
    offenders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "where"
        and node.args                      # positional args are the deprecation
    ]
    assert offenders == [], (
        f"positional .where() calls at research.py lines {offenders} — "
        f"use _fs_where(col, field, op, value)")


# ── #194b  gRPC's C++ logger ─────────────────────────────────────────────────

def test_grpc_verbosity_is_pinned_to_error_on_import():
    assert os.environ.get("GRPC_VERBOSITY") == "ERROR"


def _child_env_value(preset: "str | None") -> str:
    env = dict(os.environ)
    env.pop("GRPC_VERBOSITY", None)
    env["DG_ALERT_AI_COPY"] = "0"
    if preset is not None:
        env["GRPC_VERBOSITY"] = preset
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, os; sys.argv = ['research.py']; import research; "
         "sys.stdout.write(os.environ.get('GRPC_VERBOSITY', ''))"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip()


def test_grpc_verbosity_defaults_when_unset():
    assert _child_env_value(None) == "ERROR"


def test_an_operators_own_grpc_verbosity_is_obeyed():
    """`setdefault`, not assignment: someone debugging a transport problem must
    still be able to export DEBUG and be listened to."""
    assert _child_env_value("DEBUG") == "DEBUG"


# ── #194c  uvicorn's records wear our format ─────────────────────────────────

def test_uvicorn_log_config_never_disables_the_other_loggers():
    """`disable_existing_loggers` defaults to TRUE. Leaving it out would silence
    `auth/`'s loggers as a side effect of formatting uvicorn."""
    assert research._uvicorn_log_config()["disable_existing_loggers"] is False


def test_only_the_access_logger_carries_the_probe_filter():
    cfg = research._uvicorn_log_config()
    assert cfg["handlers"]["dg_access"]["filters"] == ["no_health_probe"]
    assert "filters" not in cfg["handlers"]["dg_default"]
    assert cfg["loggers"]["uvicorn.access"]["handlers"] == ["dg_access"]
    assert cfg["loggers"]["uvicorn.error"]["handlers"] == ["dg_default"]


def test_filter_factories_are_callables_not_dotted_strings():
    """A dotted string would make dictConfig import `research` — and under
    `python research.py` this module is `__main__`, so all 60k lines would load a
    SECOND time as a separate module object with its own globals."""
    factory = research._uvicorn_log_config()["filters"]["no_health_probe"]["()"]
    assert callable(factory), f"{factory!r} is not a callable factory"
    assert not isinstance(factory, str)


@pytest.mark.parametrize("path,expected", [("/api/health", False), ("/api/runs", True)])
def test_the_probe_filter_keeps_everything_but_the_health_path(path, expected):
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                            '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", path, "1.1", 200), None)
    assert research._DropHealthProbeAccessLines().filter(rec) is expected


def test_an_unformattable_record_is_never_swallowed():
    """Fail OPEN. A filter that raises or drops on a bad record would lose real
    access lines to a formatting bug."""
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                            "%s %s", ("only-one-arg",), None)
    assert research._DropHealthProbeAccessLines().filter(rec) is True


def test_the_log_config_is_actually_handed_to_uvicorn():
    """⚠ The one mutant that survived the first pass. Every assertion around this
    one proves the config DICT is correct, and the dictConfig test below proves it
    APPLIES when applied — but nothing proved uvicorn ever receives it. Deleting
    the `log_config=` argument left 31/31 green while uvicorn's own bare `INFO:`
    format stayed live, which is the same "correct helper nobody calls" failure
    this file was written to avoid.
    """
    import ast
    tree = ast.parse(inspect.getsource(research.run_server))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "Config"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "uvicorn"]
    assert len(calls) == 1, f"expected one uvicorn.Config call, found {len(calls)}"
    kwargs = {kw.arg for kw in calls[0].keywords}
    assert "log_config" in kwargs, (
        f"uvicorn.Config received only {sorted(kwargs)} — the log config is built "
        f"but never passed, so uvicorn keeps its own format")


def test_the_config_applies_under_a_real_dictconfig():
    """End-to-end through `logging.config.dictConfig` in a child process, so the
    callable factory, the formatter and the filter are all proven together
    without mutating this process's logging state."""
    prog = (
        "import sys, json, logging, logging.config\n"
        "sys.argv = ['research.py']\n"
        "import research\n"
        "logging.config.dictConfig(research._uvicorn_log_config())\n"
        "lg = logging.getLogger('uvicorn.access')\n"
        "lg.info('%s - \"%s %s HTTP/%s\" %d', '1.2.3.4:5', 'GET', '/api/health', '1.1', 200)\n"
        "lg.info('%s - \"%s %s HTTP/%s\" %d', '1.2.3.4:5', 'GET', '/api/runs', '1.1', 200)\n"
        "logging.getLogger('uvicorn.error').info('Uvicorn running on http://0.0.0.0:8000')\n"
    )
    env = dict(os.environ, DG_ALERT_AI_COPY="0")
    out = subprocess.run([sys.executable, "-c", prog], cwd=str(REPO), env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-3000:]
    emitted = [ln for ln in out.stdout.splitlines() if ln.strip()]

    assert not any("/api/health" in ln for ln in emitted), emitted
    assert any("/api/runs" in ln for ln in emitted), emitted
    assert any("Uvicorn running" in ln for ln in emitted), emitted
    # Every surviving line wears log()'s shape: [HH:MM:SS] [LEVEL] …
    for ln in emitted:
        assert ln.startswith("["), f"not our format: {ln!r}"
        assert "] [INFO] " in ln, f"not our format: {ln!r}"
    # And uvicorn's own bare `INFO:     ` prefix is gone.
    assert not any(ln.startswith("INFO:") for ln in emitted), emitted


# ── #197  The shutdown path must not read a global nobody assigns ────────────

def test_every_global_serve_declares_actually_exists():
    """Found by running a real Ctrl+C, not by reading code.

    `run_server`'s `finally` block declared `global _token_relink_watch` and
    read it, while NOTHING in the repo ever assigned it — the relink watcher had
    become an asyncio polling loop with no subscription handle, and the cleanup
    was left pointing at the abandoned Firestore-Watch design. Every shutdown
    raised `NameError` there, which aborted the finally block, so the
    `_device_cmd_watch` unsubscribe below it had never once run.

    Asserted as a CLASS of bug rather than one name: any `global` in this
    function that is not a real module attribute is the same defect. Note a
    `global X` whose only assignment is inside the branch guarded by reading `X`
    can never create it — which is exactly how this survived.
    """
    import ast
    tree = ast.parse(inspect.getsource(research.run_server))
    declared = {name for node in ast.walk(tree)
                if isinstance(node, ast.Global) for name in node.names}
    missing = sorted(n for n in declared if not hasattr(research, n))
    assert missing == [], (
        f"run_server declares global(s) that no module-level assignment "
        f"creates: {missing} — reading one raises NameError")


def test_serve_shutdown_still_releases_the_device_command_watch():
    """The unsubscribe that the crash was hiding must survive the deletion of the
    dead one — this is the cleanup that had never run."""
    src = code_only(research.run_server)
    assert "_device_cmd_watch.unsubscribe()" in src
    assert "_token_relink_watch" not in src


# ── #195  The route table lives on the reference surface ─────────────────────

def test_the_route_table_no_longer_prints_on_boot():
    src = code_only(research.run_server)
    for route in ("GET  /api/runs", "WS   /ws/{run_id}"):
        assert f'log("  {route}' not in src, f"{route} still logged on boot"


def test_help_renders_every_route(capsys):
    research.run_commands_help()
    out = capsys.readouterr().out
    assert "Local API" in out
    for route, desc in research._LOCAL_API_ROUTES:
        assert route in out, f"{route!r} missing from --help"
        assert desc in out, f"{desc!r} missing from --help"


def test_the_route_list_is_not_silently_empty():
    """A reference section that lost its rows would still render a heading and a
    rule, and every assertion above it would still pass."""
    assert len(research._LOCAL_API_ROUTES) >= 6


# ── #196  The pulse stops contradicting the lexicon ──────────────────────────

@pytest.mark.parametrize("tick", range(6))
def test_the_pulse_never_claims_to_be_resting(tick):
    """◇ is *quiescens* — resting — everywhere else in this CLI. A line that says
    "standing watch" must not wear it."""
    line = research._aegis_pulse_line(1, tick)
    assert "standing watch" in line
    assert "◆" in line
    assert "◇" not in line


def test_the_pulse_still_pulses_when_colour_is_on(monkeypatch):
    monkeypatch.setattr(research, "_USE_COLOR", True)
    even = research._aegis_pulse_line(1, 0)
    odd = research._aegis_pulse_line(1, 1)
    assert even != odd, "the pulse lost its alternation"
    assert research._ACCENT in even
    assert research._DIM in odd


def test_the_pulse_text_is_steady_when_colour_is_off(monkeypatch):
    """Honest consequence of moving the pulse to colour: in a plain redirect the
    text repeats. That is correct — the state IS steady, and log() already
    stamps a fresh timestamp every minute."""
    monkeypatch.setattr(research, "_USE_COLOR", False)
    assert research._aegis_pulse_line(1, 0) == research._aegis_pulse_line(1, 1)


def test_the_pulse_names_its_worker():
    assert "worker 2" in research._aegis_pulse_line(2, 0)


def test_the_glyph_pair_is_gone_from_the_pulse_loop():
    """The old alternation lived inline in `run_server`; the decision now lives
    in a function a test can call. If the tuple came back, the helper would be
    dead code and every assertion above it would still pass."""
    src = code_only(research.run_server)
    assert '("◆", "◇")' not in src
    assert "_aegis_pulse_line(" in src
