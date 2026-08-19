"""A manual `--serve` wrote no log file at all. 2026-08-19.

⛔⛔ THE GAP, and how it hid. `_session_command_name` handed a session file to
`--pair`, `--login` and `--doctor`, and its own docstring explained the omission:
"`--serve` does not: its stdout is already redirected into backend.log by the
supervisor." That sentence is true of a SUPERVISED worker and false of the case a
developer and an owner actually hit every day — `python research.py --serve` in a
terminal has no supervisor, so nothing redirects anything.

So for a foreground serve: no session file (serve was excluded), no backend.log
(the supervisor writes that, and it is not running), and only the per-run folder
capturing anything at all — which is armed inside a pipeline run and covers
nothing outside one. Startup, pairing, the device-command listener and the whole
shutdown tail lived in terminal scrollback and NOWHERE ELSE, and a support bundle
collected none of it. Same shape as wave 1's six modules logging into a void.

⭐ It is also why the e2e recording command had to wrap serve in `tee` with a
signal trap: there was no file to read. With this, plain `--serve` is enough, and
it is strictly better than the pipe — a `tee` dies with its process group on
Ctrl+C, taking the shutdown tail with it (measured 0/3 lines), while a writer
inside the process is line-buffered and keeps what it has already written.

── The discriminator, and why not isatty() ──────────────────────────────────

⛔ `--worker-id`. `_spawn_worker` always passes it, so its ABSENCE means nobody
upstream is capturing our stdout. `isatty()` would ALSO be false when the owner
pipes to `tee`, and writing a file there is right rather than redundant — the
pipe is the thing that loses the ending.

── The hazard the change introduced ─────────────────────────────────────────

⛔⛔ `--serve` IS MULTI-THREADED and the three commands that used this writer
before were not, so the unlocked writer was safe by accident. The device-command
listener, the heartbeat loop and the upload threads all print. Concurrent writes
across a rollover interleave the byte counter, the file handle and the live-segment
list, and the loss lands exactly around each rollover.
"""
import threading
import types

import research

from conftest import code_only, code_only_deep


def _args(**kw):
    """An argparse-shaped namespace with every flag this reads defaulted off."""
    base = {"pair": False, "login": False, "doctor": False,
            "serve": False, "daemon_loop": False, "worker_id": None}
    base.update(kw)
    return types.SimpleNamespace(**base)


# ══ 1. who gets a file ═════════════════════════════════════════════════

def test_a_manual_serve_gets_a_session_file():
    """⭐⭐ THE FIX. No supervisor means no redirection, so the process has to
    keep its own record."""
    assert research._session_command_name(_args(serve=True)) == "serve"


def test_a_SUPERVISED_worker_does_NOT():
    """⛔ Its stdout is already a file handle the supervisor opened
    (`_spawn_worker` → backend-N.log), so a session file would be a second copy
    of the same bytes, and the bundle would ship both."""
    assert research._session_command_name(_args(serve=True, worker_id=1)) is None
    assert research._session_command_name(_args(serve=True, worker_id=2)) is None


def test_the_supervisor_itself_does_NOT():
    """`--daemon-loop` is its own flag and already writes backend.log through
    `_sup_audit`."""
    assert research._session_command_name(_args(daemon_loop=True)) is None


def test_the_three_interactive_commands_still_get_theirs():
    for flag in ("pair", "login", "doctor"):
        assert research._session_command_name(_args(**{flag: True})) == flag


def test_a_command_with_no_output_of_its_own_gets_nothing():
    assert research._session_command_name(_args()) is None


def test_the_gate_is_worker_id_and_not_a_tty_check():
    """⛔ Pinned as CODE. `isatty()` is false when the owner pipes to `tee`, and
    a file is exactly what that case needs — the pipe is the thing that dies on
    Ctrl+C and loses the ending."""
    src = code_only_deep(research._session_command_name)
    assert 'getattr(args, "worker_id", None) is None' in src
    assert "isatty" not in src


# ══ 2. the file lands where the bundle looks ═══════════════════════════

def test_the_session_file_goes_where_a_BUNDLE_will_find_it(tmp_path):
    """⭐ `sessions/` is one of the three places `_build_log_bundle` reads, and it
    is the age-bound one with no count cap — which is the right home for a serve
    session, because the machine with no runs is exactly the machine whose only
    evidence is a session."""
    writer = research._install_session_tee("serve")
    try:
        assert writer is not None
        assert writer.primary.parent == research._sessions_log_root()
        assert writer.primary.name.startswith("serve_")
        assert research._bundle_source_is_allowed(writer.primary)
        # And the collector really does pick it up, rather than us asserting the
        # path shape and hoping.
        groups = research._select_bundle_sessions()
        assert any(writer.primary in g for g in groups)
    finally:
        research._close_session_tees()


def test_the_serve_session_survives_a_clear_only_by_being_cleared(tmp_path):
    """⛔ It is a log, so `clear-logs` must remove it like any other. A file the
    privacy button cannot reach would be the whole point of that button missed."""
    writer = research._install_session_tee("serve")
    research._close_session_tees()
    assert writer is not None and writer.primary.exists()
    out = research._clear_local_logs()
    assert not writer.primary.exists()
    assert out["sessions"] >= 1


# ══ 3. the writer is safe for a multi-threaded process ════════════════

def test_concurrent_writers_do_not_lose_lines(tmp_path):
    """⛔⛔ `self.lines += 1` is a read-modify-write, and CPython's GIL does not
    make that atomic — LOAD_ATTR / ADD / STORE_ATTR. Unlocked, concurrent threads
    lose increments, and the same race corrupts the byte counter and the
    live-segment list around every rollover."""
    writer = research._CappedLogWriter(
        tmp_path / "serve.log", max_bytes=4_000, segment_bytes=2_000, keep=2)
    threads = 8
    per_thread = 400

    def _spam(n):
        for i in range(per_thread):
            writer.write_line(f"thread {n} line {i} " + "x" * 40)

    workers = [threading.Thread(target=_spam, args=(n,)) for n in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    writer.close()
    assert writer.lines == threads * per_thread, (
        f"lost {threads * per_thread - writer.lines} lines to a race")


def test_the_write_path_is_actually_locked():
    """⛔ Behaviour alone is a probabilistic pin: a race can pass by luck on a
    quiet machine. The lock itself is the property."""
    src = code_only(research._CappedLogWriter.write_line)
    assert "with self._lock:" in src
    init = code_only(research._CappedLogWriter.__init__)
    assert "self._lock" in init


def test_a_rollover_under_load_still_produces_readable_files(tmp_path):
    """The cap drops middle segments by design, so line COUNT on disk is not the
    invariant — being parseable and non-empty is."""
    writer = research._CappedLogWriter(
        tmp_path / "serve.log", max_bytes=2_000, segment_bytes=1_000, keep=2)

    def _spam(n):
        for i in range(300):
            writer.write_line(f"t{n}-{i}-" + "y" * 30)

    workers = [threading.Thread(target=_spam, args=(n,)) for n in range(6)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    writer.close()
    paths = writer.paths()
    assert paths, "a rollover produced no files at all"
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert text, f"{path.name} is empty"
        # Every line written is one line on disk — no interleaved fragments.
        for line in text.splitlines():
            assert line.startswith(("t", "---")), f"torn line: {line[:60]!r}"
