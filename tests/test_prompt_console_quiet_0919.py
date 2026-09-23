"""A question on screen is not somewhere to print log lines.

⛔⛔ WHAT THE OWNER SAW, 2026-09-19, verbatim from their terminal:

    >  Send this to the team? [y/N]: [18:48:25] [INFO] [date] 2026-09-19
  [18:48:25] [DEBUG] [telemetry] telemetry: no id-token accessor (ImportError) …
  y

Their words: "because of the noise, it's very unclear what to even type."

⭐ AND IT CANNOT BE FIXED BY ORDERING. The lines land INSIDE the prompt because
another thread writes them: the telemetry flusher is a daemon started at the top
of `main()`, and its stdlib `log.debug` reaches `log()` through the bridge, which
is attached at DEBUG deliberately. The main thread is parked in `input()` while
that happens, so no amount of moving statements around on the main thread helps.

⚠ WITHHELD FROM THE SCREEN, NEVER FROM THE FILES — which is the part worth
testing hardest. Every line still reaches the run file on its normal path and
the session log the moment it arrives, and the screen replays the newest 500
the instant the answer is read. A prompt that ate diagnostics would trade a
cosmetic problem for a real one: the next support bundle is built from exactly
these lines. (Until wave 10.10 this said "never discarded" while line 501 onward
reached no file at all.)
"""
import threading
import time

import pytest

import research


@pytest.fixture(autouse=True)
def _reset():
    research._CONSOLE_QUIET.clear()
    with research._CONSOLE_HELD_LOCK:
        research._CONSOLE_HELD[:] = []
        research._CONSOLE_HELD_DROPPED[0] = 0
    yield
    research._CONSOLE_QUIET.clear()
    with research._CONSOLE_HELD_LOCK:
        research._CONSOLE_HELD[:] = []
        research._CONSOLE_HELD_DROPPED[0] = 0


def test_a_log_line_does_not_print_while_a_question_is_open(capsys):
    """⛔ THE DEFECT. Today this prints straight over the prompt."""
    with research._console_quiet_for_prompt():
        research.log("telemetry: no id-token accessor (ImportError)", "DEBUG")
        during = capsys.readouterr().out
    assert during == "", f"printed over the prompt: {during!r}"


def test_and_it_replays_the_moment_the_prompt_closes(capsys):
    with research._console_quiet_for_prompt():
        research.log("telemetry: no id-token accessor (ImportError)", "DEBUG")
    after = capsys.readouterr().out
    assert "no id-token accessor" in after


def test_a_line_from_ANOTHER_THREAD_is_held_too(capsys):
    """⭐ The real shape. The telemetry flusher is a daemon thread; a fix that
    only worked for the main thread would not have touched this incident."""
    def bg():
        time.sleep(0.02)
        research.log("telemetry: batch posted", "DEBUG")

    t = threading.Thread(target=bg)
    with research._console_quiet_for_prompt():
        t.start()
        t.join()
        during = capsys.readouterr().out
    assert during == "", f"a background thread printed over the prompt: {during!r}"
    assert "batch posted" in capsys.readouterr().out


def _session(tmp_path, monkeypatch):
    """A real session tee on `sys.stdout`, as `--pair`/`--login`/`--doctor`
    install one: the screen is a buffer, the file is a real capped writer."""
    import io
    import sys
    screen = io.StringIO()
    path = tmp_path / "session.log"
    writer = research._CappedLogWriter(path)
    monkeypatch.setattr(sys, "stdout", research._SessionTee(screen, writer))
    return screen, writer, path


def test_every_held_line_reaches_the_session_log_exactly_once(tmp_path, monkeypatch):
    """⛔⛔ THE GUARD THAT MATTERS MOST, AND IT USED TO PASS EITHER WAY. It
    logged one line and looked for it in the run file — true before and after
    the defect it was named for. What was really lost: while a question was
    open, line 501 onward was neither shown NOR written anywhere, because the
    session log is a copy of the screen and those lines never reached the
    screen. Every held line must now be in the session file exactly once — not
    missing, and not written again when the screen replays it — and in the run
    file exactly once too."""
    screen, writer, path = _session(tmp_path, monkeypatch)
    written = []
    monkeypatch.setattr(research, "_log_write_through",
                        lambda line, level: written.append(line))
    n = research._CONSOLE_HELD_MAX + 50
    with research._console_quiet_for_prompt():
        for i in range(n):
            research.log(f"held line {i:04d}", "WARN")
    writer.close()
    kept = path.read_text(encoding="utf-8")
    missing = [i for i in range(n) if f"held line {i:04d}" not in kept]
    twice = [i for i in range(n) if kept.count(f"held line {i:04d}") > 1]
    assert not missing, f"{len(missing)} held line(s) never reached the session log"
    assert not twice, f"{len(twice)} held line(s) were written to it twice"
    assert all(sum(f"held line {i:04d}" in w for w in written) == 1 for i in range(n)), (
        "a held line did not reach the run file exactly once")


def test_the_screen_replays_the_newest_and_says_where_the_rest_are(tmp_path,
                                                                    monkeypatch):
    """⭐ WHAT A PERSON SEES: the newest 500, and one line saying how many
    earlier lines arrived and which file has them."""
    screen, writer, path = _session(tmp_path, monkeypatch)
    n = research._CONSOLE_HELD_MAX + 50
    with research._console_quiet_for_prompt():
        for i in range(n):
            research.log(f"held line {i:04d}")
        assert screen.getvalue() == "", "a held line printed over the question"
    shown = screen.getvalue()
    assert shown.count("held line") == research._CONSOLE_HELD_MAX
    assert "held line 0049" not in shown and "held line 0050" in shown
    assert f"held line {n - 1:04d}" in shown
    assert "50 earlier line(s)" in shown and str(path) in shown
    # the note comes BEFORE the lines it explains are missing from
    assert shown.index("50 earlier line(s)") < shown.index("held line 0050")


def test_without_a_session_log_the_note_says_they_were_not_kept(capsys):
    """⛔ `--send-logs` keeps no session log, so there is no file to point at —
    and the note must not claim one."""
    n = research._CONSOLE_HELD_MAX + 3
    with research._console_quiet_for_prompt():
        for i in range(n):
            research.log(f"held line {i:04d}")
    shown = capsys.readouterr().out
    assert shown.count("held line") == research._CONSOLE_HELD_MAX
    assert "3 earlier line(s)" in shown and "were not kept" in shown


def test_a_short_prompt_says_nothing_extra(tmp_path, monkeypatch):
    """⭐ The ordinary case: a handful of lines replay as they were, with no note
    — even right after a long prompt, whose count must not carry over."""
    screen, writer, path = _session(tmp_path, monkeypatch)
    with research._console_quiet_for_prompt():
        for i in range(research._CONSOLE_HELD_MAX + 5):
            research.log(f"held line {i:04d}")
    assert "5 earlier line(s)" in screen.getvalue()
    screen.seek(0)
    screen.truncate()
    with research._console_quiet_for_prompt():
        research.log("one quiet line")
    writer.close()
    assert "one quiet line" in screen.getvalue()
    assert "earlier line(s)" not in screen.getvalue(), screen.getvalue()
    assert path.read_text(encoding="utf-8").count("one quiet line") == 1


def test_the_hold_is_bounded(capsys):
    """A prompt left open overnight must not grow one line per flush until the
    process dies."""
    with research._console_quiet_for_prompt():
        for i in range(research._CONSOLE_HELD_MAX + 50):
            research.log(f"line {i}")
        with research._CONSOLE_HELD_LOCK:
            assert len(research._CONSOLE_HELD) == research._CONSOLE_HELD_MAX
    capsys.readouterr()


def test_the_console_reopens_even_when_the_read_raises(capsys):
    """⛔ Ctrl+C and EOF both propagate out of the prompt by design — every
    caller handles them differently. If either left the console held, the CLI
    would go silent for the rest of its life."""
    for exc in (KeyboardInterrupt, EOFError):
        with pytest.raises(exc):
            with research._console_quiet_for_prompt():
                raise exc()
        assert not research._CONSOLE_QUIET.is_set()
    research.log("back on")
    assert "back on" in capsys.readouterr().out


def test_printing_is_normal_when_no_prompt_is_open(capsys):
    """The no-widening guard: this must change nothing about ordinary logging."""
    research.log("ordinary line")
    assert "ordinary line" in capsys.readouterr().out


# ── the prompts are actually wrapped ──────────────────────────────────────

def test_both_interactive_reads_are_wrapped():
    """⛔ There are exactly two `input()` calls in this file and BOTH are
    exposed — fixing the yes/no reader and leaving the menu would be half a
    fix. Source-level, because driving a real `input()` under capsys tests the
    harness rather than the CLI; paired with the behaviour tests above."""
    from conftest import code_only
    with open(research.__file__, encoding="utf-8") as f:
        src = code_only(f.read())
    sites = [i for i, ln in enumerate(src.splitlines()) if "input(" in ln and "_input" not in ln]
    assert len(sites) == 2, f"a third interactive read appeared: {len(sites)}"
    lines = src.splitlines()
    for i in sites:
        window = "\n".join(lines[max(0, i - 3):i + 1])
        assert "_console_quiet_for_prompt()" in window, f"unwrapped input() at line {i + 1}"
