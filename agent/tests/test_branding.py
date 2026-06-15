"""Branded terminal UI helpers: brand_mark (gold/red glyph + glowing name), the
channel row, and the grouped Next block. Capture via redirect_stdout (everything
goes through print → stdout)."""

import contextlib
import io
import time

import pytest

from facade import branding as b


def _out(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **k)
    return buf.getvalue()


def test_brand_mark_contains_glyph_label_and_suffix():
    s = b.brand_mark("⚚", (224, 163, 58), "Hermes", "· WSL · Ubuntu-24.04")
    assert "⚚" in s and "Hermes" in s and "WSL" in s


def test_brand_mark_without_suffix():
    s = b.brand_mark("🦞", (231, 76, 60), "OpenClaw")
    assert "🦞" in s and "OpenClaw" in s


def test_channels_prints_every_name():
    # Names-only (no glyph): each channel name appears in the row.
    out = _out(b.channels, [
        ("WhatsApp", (37, 211, 102)),
        ("Telegram", (34, 158, 217)),
        ("iMessage", (52, 199, 89)),
        ("Twilio", (242, 47, 70)),
    ])
    for name in ("WhatsApp", "Telegram", "iMessage", "Twilio"):
        assert name in out


def test_channels_empty_is_noop():
    assert _out(b.channels, []) == ""


def test_next_grouped_prints_labels_and_commands():
    out = _out(b.next_grouped, [
        ("in this terminal", [("python research.py agent status", "check")]),
        ("in your chat", [("/sr", "help")]),
    ])
    assert "in this terminal" in out and "in your chat" in out
    assert "agent status" in out and "/sr" in out


def test_next_grouped_drops_empty_groups():
    out = _out(b.next_grouped, [("kept", [("a", "b")]), ("gone", [])])
    assert "kept" in out and "gone" not in out


def test_next_grouped_all_empty_is_noop():
    assert _out(b.next_grouped, [("x", []), ("y", [])]) == ""


# confirm(): an interrupt must NEVER silently proceed as the default (the
# `wsl --shutdown` / install footgun the review caught).

def test_confirm_ctrl_c_returns_false_even_when_default_true(monkeypatch):
    def _interrupt(_prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _interrupt)
    assert b.confirm("Run wsl --shutdown?", default=True) is False
    assert b.confirm("Install?", default=False) is False


def test_confirm_eof_returns_false(monkeypatch):
    def _eof(_prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", _eof)
    assert b.confirm("x", default=True) is False


def test_confirm_enter_takes_default_and_explicit_answers(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p="": "")     # bare Enter
    assert b.confirm("x", default=True) is True
    assert b.confirm("x", default=False) is False
    monkeypatch.setattr("builtins.input", lambda _p="": "y")
    assert b.confirm("x", default=False) is True
    monkeypatch.setattr("builtins.input", lambda _p="": "n")
    assert b.confirm("x", default=True) is False


# spinner(): a blocking step should never just look hung. On a TTY it animates a
# brand glyph on one rewritten line then clears it; off-TTY it degrades to a
# single static line (no carriage-return spam).

class _FakeTTY:
    """A stdout stand-in that reports as a terminal and records what was written."""

    def __init__(self):
        self.chunks: list[str] = []

    def write(self, s):
        self.chunks.append(s)

    def flush(self):
        pass

    def isatty(self):
        return True


def test_spinner_non_tty_prints_static_line_no_animation():
    # Captured / piped stdout (StringIO.isatty() is False) → one static line,
    # never a \r animation that would garble logs.
    out = _out(lambda: _spin_noop("working"))
    assert "working" in out and "\r" not in out


def _spin_noop(msg):
    with b.spinner(msg):
        pass


def test_spinner_animates_on_tty_then_clears(monkeypatch):
    fake = _FakeTTY()
    monkeypatch.setattr(b.sys, "stdout", fake)
    monkeypatch.setattr(b, "_USE_COLOR", True)
    with b.spinner("loading"):
        time.sleep(0.25)  # let the daemon thread paint a few frames
    out = "".join(fake.chunks)
    assert "\r" in out and "loading" in out             # animated in place
    assert "\033[?25l" in out and "\033[?25h" in out    # cursor hidden, then restored
    assert "\033[K" in out                              # line cleared on exit


def test_spinner_clears_and_reraises_on_exception(monkeypatch):
    fake = _FakeTTY()
    monkeypatch.setattr(b.sys, "stdout", fake)
    monkeypatch.setattr(b, "_USE_COLOR", True)
    with pytest.raises(ValueError):
        with b.spinner("x"):
            raise ValueError("boom")  # must propagate (spinner never suppresses)
    out = "".join(fake.chunks)
    assert "\033[K" in out and "\033[?25h" in out  # still cleaned up on error
