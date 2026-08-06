"""`--serve`'s branded surface must survive a pipe.

The owner recorded a live e2e with `--serve 2>&1 | tee run.log` and the
SUPER RESEARCH wordmark, the `Paired to / Device / Local API` strip and the
whole OK/WARN palette came out monochrome — in the TERMINAL, not just in the
file. `_USE_COLOR` was decided at import from `sys.stdout.isatty()` alone with
no override, so "record the run" and "see the brand" were mutually exclusive.

Two layers here, deliberately:

* the DECISION is pinned by calling `_color_decision` directly. It is
  import-time state otherwise, and a test that merely reads `_USE_COLOR` under
  pytest (stdout already captured, so never a tty) can never reach the pipe
  branch — the same blind spot that let the foreign-tab gate ship invertible
  with 49/49 green.
* the WIRING is pinned by a real subprocess whose stdout IS a pipe, because a
  decision helper that nothing calls is exactly the failure mode this repo
  keeps hitting. Those tests assert the escape BYTES, not the identifier.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import research

REPO = Path(research.__file__).resolve().parent


# ── The decision ────────────────────────────────────────────────────────────

def test_a_tty_still_colours_with_no_env():
    assert research._color_decision(None, None, True) is True


def test_a_pipe_is_still_monochrome_by_default():
    """The historical behaviour, kept on purpose: a plain redirect into a file
    stays clean, so `> out.log` needs no de-escaping to grep."""
    assert research._color_decision(None, None, False) is False


def test_force_color_survives_a_pipe():
    """The owner's case. This is the only way to record a run AND see brand."""
    assert research._color_decision(None, "1", False) is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "FALSE", "No", "   "])
def test_force_color_off_values_fall_through_to_the_tty(val):
    """An explicitly-off FORCE_COLOR must not *force* anything — it hands the
    decision back to the tty check rather than answering it."""
    assert research._color_decision(None, val, False) is False
    assert research._color_decision(None, val, True) is True


def test_no_color_beats_a_tty():
    assert research._color_decision("1", None, True) is False


def test_no_color_beats_force_color():
    """no-color.org: the accessibility opt-out wins. Someone who set NO_COLOR
    for a screen reader must not be overridden by a FORCE_COLOR sitting in the
    same environment (a CI image commonly exports one globally)."""
    assert research._color_decision("1", "1", True) is False


def test_no_color_zero_still_disables():
    """Deliberate spec compliance, and the surprising half of it: NO_COLOR is
    PRESENCE-based, so `NO_COLOR=0` is a set value and disables colour. Pinned
    so nobody 'fixes' it into truthiness parsing and silently breaks the
    documented contract."""
    assert research._color_decision("0", None, True) is False


@pytest.mark.parametrize("val", ["", "   "])
def test_blank_no_color_does_not_disable(val):
    """`export NO_COLOR=` in a shell profile leaves it empty, which the spec
    says is NOT set."""
    assert research._color_decision(val, None, True) is True


# ── The wiring: a real pipe, real escape bytes ──────────────────────────────

def _piped_wordmark(env_extra: "dict[str, str]") -> str:
    """Import research in a child whose stdout is a PIPE and return what the
    accent-coloured wordmark actually renders as. `capture_output=True` is what
    makes stdout a pipe — the exact condition `tee` creates."""
    env = dict(os.environ)
    env.pop("NO_COLOR", None)
    env.pop("FORCE_COLOR", None)
    env["DG_ALERT_AI_COPY"] = "0"
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.argv = ['research.py']; import research; "
         "sys.stdout.write(research._c(research._ACCENT, 'SUPER'))"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return proc.stdout


def test_wordmark_reaches_a_pipe_plain_without_the_override():
    assert _piped_wordmark({}) == "SUPER"


def test_wordmark_reaches_a_pipe_coloured_with_force_color():
    """The regression the owner saw, from the other side: with the override the
    brand renders through `tee`."""
    got = _piped_wordmark({"FORCE_COLOR": "1"})
    assert "SUPER" in got
    assert "\033[" in got, f"no escape bytes in {got!r}"


def test_no_color_is_wired_too_not_merely_implemented():
    """The strongest of the three: this can only pass if the module passes BOTH
    env values into the helper. An implementation that read only FORCE_COLOR
    would colour this and fail."""
    assert _piped_wordmark({"FORCE_COLOR": "1", "NO_COLOR": "1"}) == "SUPER"


def test_the_suite_never_inherits_a_forced_colour():
    """conftest pops FORCE_COLOR at collection. Without that pin, a CI image or
    dev shell exporting it globally would turn colour ON under pytest (stdout is
    a pipe there) and every assertion comparing a `_c()` result to plain text
    would start seeing escape bytes. Asserts the resulting CONDITION, not that
    the pop line exists.

    ⚠ Deliberately NOT `_USE_COLOR is False`: under `pytest -s` fd 1 stays the
    real terminal, colour on is then correct, and that assertion would fail an
    honest run. The invariant is that nothing OVERRODE the tty answer, so it is
    stated against the process's own stdout — `sys.__stdout__`, whose fd pytest
    redirects when capturing and leaves alone under `-s`."""
    assert not os.environ.get("FORCE_COLOR")
    real_tty = bool(sys.__stdout__ and sys.__stdout__.isatty())
    assert research._USE_COLOR is real_tty


# ── The animations stay behind the tty gate ─────────────────────────────────

def test_force_color_does_not_unlock_the_cursor_repaint(monkeypatch, capsys):
    """Colour is data; a cursor repaint is not. `_print_with_flourish` rewrites
    its own line with `\\r` + cursor-up, which through a pipe lands in the log
    as a SECOND copy of the line. So it must keep checking isatty even when
    colour is forced on — asserted by calling it, not by reading its source."""
    monkeypatch.setattr(research, "_USE_COLOR", True)
    research._print_with_flourish("  done", fade_to_color=research._DIM,
                                 hold_s=0.0)
    out = capsys.readouterr().out
    assert out == "  done\n"
    assert "\033[F" not in out
