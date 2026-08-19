"""Six modules were logging into a void. Measured, not suspected.

⛔⛔ THE FINDING. `auth/credentials`, `auth/keystore`, `auth/v2_flow`, `vision`,
`selfheal` and `narrate` all log through the standard library, and not one of
them had a handler anywhere in this process. `_uvicorn_log_config` carried a
comment asserting "`auth/` configures its own" — it does not, and never did.

What that cost, checked against this machine's real logs rather than reasoned
about:

  * WARNING and above fell through to `logging.lastResort` — a bare
    StreamHandler on STDERR, no timestamp, no level. **22,758** such lines sit
    in backend.err.log + backend-2.err.log, and **zero** are in backend.log,
    which is the file a user sends and the file the log bundle will collect.
  * DEBUG and INFO were dropped entirely. `poll_pending_token: transient HTTP
    error …` — the pairing poll's ONLY account of a network failure — appears
    in no log on this machine, ever.
  * The single line that explains the new owner's whole outage,
    `refresh: network error … Failed to resolve 'securetoken.googleapis.com'`,
    lives in the half of the logs nobody thinks to ask for.

⛔ And `_uvicorn_log_config` could never have fixed it: it is handed to
`uvicorn.Config(log_config=…)`, so it only exists inside `--serve`. `--pair`,
`--login` and `--doctor` configure no logging at all — which is exactly the
window a new owner is in when they need it.

⭐ The class guard is `test_every_stdlib_logger_in_this_repo_is_bridged`. A
seventh module added later, logging into the same void, fails that test.
"""
import inspect
import io
import logging
import re
from pathlib import Path

import pytest

import research


ROOT = Path(research.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _fresh_bridge():
    """Detach, run, re-attach — so ordering between tests cannot decide a result."""
    saved = {}
    for name in research._BRIDGED_LOGGERS:
        lg = logging.getLogger(name)
        saved[name] = (list(lg.handlers), lg.level, lg.propagate)
        lg.handlers = [h for h in lg.handlers
                       if not isinstance(h, research._StdlibLogBridge)]
    yield
    for name, (handlers, level, propagate) in saved.items():
        lg = logging.getLogger(name)
        lg.handlers = handlers
        lg.level = level
        lg.propagate = propagate


# ── the class guard ──────────────────────────────────────────────────────────

def _repo_logger_roots() -> "set[str]":
    """Every stdlib logger our own shipped code creates, by root name."""
    roots = set()
    skip = {".venv", "agent", "tests", ".mutants", "node_modules", "build", "dist"}
    for path in ROOT.rglob("*.py"):
        if any(part in skip for part in path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"getLogger\(\s*(__name__|\"([^\"]+)\"|'([^']+)')\s*\)", text):
            if m.group(1) == "__name__":
                rel = path.relative_to(ROOT).with_suffix("")
                roots.add(rel.parts[0])
            else:
                roots.add((m.group(2) or m.group(3)).split(".")[0])
    return roots


def test_every_stdlib_logger_in_this_repo_is_bridged():
    """⭐ THE ONE THAT KEEPS THIS FIXED. Any module that starts logging through
    the standard library and is not listed here logs into the same void."""
    found = _repo_logger_roots()
    assert found, "sanity: the scan should find some loggers"
    missing = found - set(research._BRIDGED_LOGGERS)
    assert not missing, (
        f"{sorted(missing)} log through the standard library with no handler — "
        f"their WARNs go to bare stderr and their DEBUG/INFO go nowhere"
    )


def test_the_bridged_list_is_the_measured_set():
    """⚠ 2026-08-18: `telemetry` joined. It is the one logger in the repo that
    exists to talk about a module whose whole job is being quiet, so it would be
    the easiest one to leave unbridged and never notice — which is precisely the
    failure this file was written for.

    (The name said "six" for a list of four: the SIX was the count of modules
    logging into the void, and four logger ROOTS cover them — `auth` covers
    credentials, keystore and v2_flow.)"""
    assert set(research._BRIDGED_LOGGERS) == {
        "auth", "vision", "selfheal", "narrate", "telemetry"}


def test_the_modules_still_have_no_logging_config_of_their_own():
    """The premise of the whole fix. If one of them ever configures itself, this
    bridge would be a second policy — the exact thing that caused the bug."""
    for rel in ("vision.py", "selfheal.py", "narrate.py",
                "auth/credentials.py", "auth/keystore.py", "auth/v2_flow.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for configurator in ("basicConfig", "addHandler", "dictConfig"):
            assert configurator not in text, f"{rel} now configures logging itself"


# ── installation ─────────────────────────────────────────────────────────────

def test_install_attaches_to_every_named_logger():
    installed = research._install_stdlib_log_bridge()
    assert set(installed) == set(research._BRIDGED_LOGGERS)
    for name in research._BRIDGED_LOGGERS:
        lg = logging.getLogger(name)
        assert any(isinstance(h, research._StdlibLogBridge) for h in lg.handlers)


def test_install_is_idempotent():
    """`main()` is not the only way into this file."""
    research._install_stdlib_log_bridge()
    assert research._install_stdlib_log_bridge() == []
    lg = logging.getLogger("auth")
    assert sum(isinstance(h, research._StdlibLogBridge) for h in lg.handlers) == 1


def test_the_level_is_debug_not_info():
    """`log()` has no level filter, so every DEBUG written through it prints.
    Holding these to INFO would be a SECOND policy in the same process."""
    research._install_stdlib_log_bridge()
    for name in research._BRIDGED_LOGGERS:
        assert logging.getLogger(name).level == logging.DEBUG


def test_propagation_is_off_so_a_future_root_config_cannot_double_print():
    research._install_stdlib_log_bridge()
    for name in research._BRIDGED_LOGGERS:
        assert logging.getLogger(name).propagate is False


def test_main_installs_it_before_anything_can_log():
    src = inspect.getsource(research.main)
    assert "_install_stdlib_log_bridge()" in src
    body = src[src.index("def main():"):]
    assert body.index("_install_stdlib_log_bridge()") < body.index("_migrate_state_to_home()"), (
        "the bridge has to be up before the first thing that can log"
    )


def test_the_uvicorn_config_no_longer_claims_auth_configures_itself():
    src = inspect.getsource(research._uvicorn_log_config)
    # The old claim survives only as history, and history has to be marked as
    # such — a corrected comment that still reads like an assertion is the same
    # defect in a nicer font.
    assert "Leave every logger we did not name alone: `auth/` configures its own" not in src
    assert "It does not, and" in src and "never did" in src
    assert "_install_stdlib_log_bridge" in src, (
        "the comment should point at what actually handles these"
    )


def test_the_uvicorn_config_still_leaves_other_loggers_alone():
    """`disable_existing_loggers: False` is what stops uvicorn's dictConfig
    silencing our bridge as a side effect."""
    cfg = research._uvicorn_log_config()
    assert cfg["disable_existing_loggers"] is False
    assert set(cfg["loggers"]) == {"uvicorn", "uvicorn.error", "uvicorn.access"}


# ── what comes out ───────────────────────────────────────────────────────────

def _emit(name, level, msg, *args, **kw):
    research._install_stdlib_log_bridge()
    getattr(logging.getLogger(name), level)(msg, *args, **kw)


def test_a_record_reaches_the_one_writer(capsys):
    _emit("auth.keystore", "warning", "keyring read of slot=%s failed: %s", "refresh", "boom")
    out = capsys.readouterr()
    assert "[WARN] [auth.keystore] keyring read of slot=refresh failed: boom" in out.out
    assert out.err == "", "nothing may reach stderr any more"


def test_the_dropped_debug_line_now_exists(capsys):
    """This exact call is the pairing poll's only account of a network failure,
    and it appears in no log on this machine."""
    _emit("auth.v2_flow", "debug", "poll_pending_token: transient HTTP error %s", "timeout")
    assert "[DEBUG] [auth.v2_flow] poll_pending_token: transient HTTP error timeout" \
        in capsys.readouterr().out


def test_every_line_carries_a_timestamp(capsys):
    _emit("vision", "info", "hello")
    line = capsys.readouterr().out.strip()
    assert re.match(r"^\[\d\d:\d\d:\d\d\] \[INFO\] \[vision\] hello$", line), line


def test_the_logger_name_is_in_the_message(capsys):
    """Six modules share one stream now; without the name a reader cannot tell
    a keystore failure from a vision one."""
    _emit("selfheal", "warning", "something")
    assert "[selfheal] something" in capsys.readouterr().out


@pytest.mark.parametrize("level,rendered", [
    ("debug", "DEBUG"), ("info", "INFO"),
    ("warning", "WARN"), ("error", "ERROR"), ("critical", "ERROR"),
])
def test_levels_speak_this_file_s_vocabulary(capsys, level, rendered):
    """The stdlib says WARNING; every level filter in this repo says WARN."""
    _emit("narrate", level, "x")
    assert f"[{rendered}] [narrate] x" in capsys.readouterr().out


def test_a_traceback_becomes_lines_that_are_each_timestamped(capsys):
    """⛔ A multi-line record through a single print is how a log grows orphan
    lines with no timestamp and no level — precisely what this replaces."""
    research._install_stdlib_log_bridge()
    try:
        raise ValueError("inner cause")
    except ValueError:
        logging.getLogger("selfheal").error("outer message", exc_info=True)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) >= 3
    assert all(re.match(r"^\[\d\d:\d\d:\d\d\] \[ERROR\] ", l) for l in lines), lines
    assert any("outer message" in l for l in lines)
    assert any("ValueError: inner cause" in l for l in lines)
    assert any("Traceback (most recent call last)" in l for l in lines)


def test_a_broken_format_string_does_not_take_the_process_down(capsys):
    research._install_stdlib_log_bridge()
    logging.getLogger("vision").warning("needs %s and %s", "only-one")
    # No exception escaped; that is the assertion.


def test_lastresort_is_no_longer_reachable_for_these(capsys):
    """The old behaviour, exactly: a WARNING with no handler prints bare text to
    stderr. Both halves must now be false."""
    _emit("auth.credentials", "warning", "refresh: network error boom")
    out = capsys.readouterr()
    assert "refresh: network error boom" not in out.err
    assert "refresh: network error boom" in out.out
