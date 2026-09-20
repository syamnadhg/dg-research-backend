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

⚠ WITHHELD, NEVER DISCARDED — which is the part worth testing hardest. Every
line still reaches the run file on its normal path, and the console copy replays
the instant the answer is read. A prompt that ate diagnostics would trade a
cosmetic problem for a real one: the next support bundle is built from exactly
these lines.
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
    yield
    research._CONSOLE_QUIET.clear()
    with research._CONSOLE_HELD_LOCK:
        research._CONSOLE_HELD[:] = []


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


def test_the_line_still_reaches_the_run_file(monkeypatch, capsys):
    """⛔⛔ THE GUARD THAT MATTERS MOST. Quieting the console must not quiet the
    LOG. Support bundles are assembled from these lines, and a prompt that
    silently dropped them would cost a future diagnosis — which is exactly the
    kind of loss this whole day has been about."""
    written = []
    monkeypatch.setattr(research, "_log_write_through",
                        lambda line, level: written.append((line, level)))
    with research._console_quiet_for_prompt():
        research.log("something worth keeping", "WARN")
    assert any("something worth keeping" in ln for ln, _lv in written)
    assert any(lv == "WARN" for _ln, lv in written)


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
