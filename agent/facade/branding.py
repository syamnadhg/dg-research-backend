"""Branded terminal UI for the Super Agent CLI.

A self-contained mirror of the backend's `--pair` aesthetic (research.py) so the
agent's interactive screens read as the same "Super Research" product. This
module deliberately imports NOTHING from the app (research.py) — the facade
stays an isolated sub-package (see test_app_plane_unchanged).

Pure rendering + a tiny `input()`-based picker. No network, no side effects
beyond stdout/stdin, so cli.py remains the only place that orchestrates I/O.
"""

from __future__ import annotations

import os
import shutil
import sys

# ── Color support (tty + Windows VT enable) — mirrors research.py ───────────
_USE_COLOR = False
try:
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        _USE_COLOR = True
        if sys.platform == "win32":
            # Enable ANSI escape processing on Win10+ consoles.
            import ctypes

            try:
                _k32 = ctypes.windll.kernel32
                _k32.SetConsoleMode(_k32.GetStdHandle(-11), 7)
            except Exception:
                pass
except Exception:
    _USE_COLOR = False

# 256-color palette matching the app's "Super Research" brand.
_ACCENT = "\033[38;5;75m"   # bright blue — matches the wordmark
_DIM = "\033[38;5;244m"     # muted grey — auxiliary lines
_OK = "\033[38;5;108m"      # muted green — success marks
_WARN = "\033[38;5;214m"    # amber — warnings
_BRIGHT = "\033[38;5;231m"  # glowing white
_RED = "\033[38;5;160m"     # deep red — failure marks
_BOLD = "\033[1m"
_RESET = "\033[0m"

_SIGIL = "◆"
MARK_OK = "✓"
MARK_WARN = "⚠"
MARK_NO = "✗"
ARROW = "→"
CARET = "›"


def c(color: str, text: str) -> str:
    """Wrap text in an ANSI color (no-op when color is disabled)."""
    return f"{color}{text}{_RESET}" if _USE_COLOR else text


def rgb(r: int, g: int, b: int) -> str:
    """TrueColor foreground escape — used for the runtime brand marks
    (Hermes gold, OpenClaw orange). Degrades to no color off-tty."""
    return f"\033[38;2;{r};{g};{b}m"


def rule(char: str = "─", color: str = _DIM, max_width: int = 62) -> str:
    """Width-aware horizontal rule (sizes to the terminal, capped)."""
    cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    width = max(10, min(max_width, cols - 4))
    return c(color, char * width)


def header(tagline: str, gloss: str, *, tagline_color: str | None = None) -> None:
    """The shared SUPER RESEARCH banner + a ◆ tagline · gloss line, so every
    agent subcommand wears the same crown as `--pair` / `--resurrect`."""
    tc = tagline_color or (_BOLD + _ACCENT)
    bar = rule("━")
    print()
    print(f"  {bar}")
    print()
    print(f"                   {c(_BOLD + _ACCENT, 'SUPER')} {c(_BOLD, 'RESEARCH')}")
    print(
        f"                {c(tc, _SIGIL)}  {c(tc, tagline)} "
        f"{c(_DIM, '·')} {c(_DIM, gloss)}"
    )
    print()
    print(f"  {bar}")


def step_arc(steps: list[str]) -> None:
    """Compact preview of the whole step sequence (like --pair's 'Five steps')."""
    parts = []
    for i, name in enumerate(steps, 1):
        parts.append(f"{c(_ACCENT, str(i))} {name}")
    print()
    print(f"  {c(_DIM, 'Steps:')}   " + f"   {c(_DIM, ARROW)}   ".join(parts))


def step(n: int, total: int, title: str) -> None:
    """Section header for one step inside a subcommand."""
    print()
    print(f"  {c(_ACCENT + _BOLD, f'[{n}/{total}]')} {c(_BOLD, title)}")
    print(f"  {rule(max_width=58)}")


def ok(msg: str) -> None:
    print(f"  {c(_OK, MARK_OK)}  {msg}")


def warn(msg: str) -> None:
    print(f"  {c(_WARN, MARK_WARN)}  {msg}")


def no(msg: str) -> None:
    print(f"  {c(_RED, MARK_NO)}  {msg}")


def dim(msg: str) -> None:
    print(f"  {c(_DIM, msg)}")


def line(msg: str = "") -> None:
    print(f"  {msg}" if msg else "")


def brand_mark(icon: str, color_rgb: tuple[int, int, int], label: str, suffix: str = "") -> str:
    """A runtime brand chip: a full-glow brand-tinted glyph + a brand-tinted
    OUTLINE name (the symbol glows, the text doesn't). The tint lands on vector
    glyphs (⚚ → gold); emoji (🦞) ignore ANSI foreground and keep their own native
    color — which is the intent.
    e.g.  ⚚  Hermes   · WSL · Ubuntu-24.04"""
    glyph = c(rgb(*color_rgb) + _BOLD, icon)   # symbol: full-on glow (bold + brand color)
    name = c(rgb(*color_rgb), label)            # name: brand-colored OUTLINE only (not bold)
    tail = f"   {c(_DIM, suffix)}" if suffix else ""
    return f"{glyph}  {name}{tail}"


def channels(items: list[tuple[str, str, tuple[int, int, int]]]) -> None:
    """A decorative row of the chat channels Super Research reaches, under the
    header — each a brand-colored glyph + name. (Vector glyphs take the tint;
    emoji render native.) items = (name, glyph, (r,g,b))."""
    if not items:
        return
    chips = [f"{c(rgb(*col), glyph)} {c(rgb(*col), name)}" for name, glyph, col in items]
    print()
    print(f"  {c(_DIM, 'reach it from')}   " + "   ".join(chips))


def next_actions(items: list[tuple[str, str]]) -> None:
    """Compact 'Next' block — 2-3 likely follow-up commands with one-liners."""
    if not items:
        return
    bar = rule("┈")
    width = min(max(len(cmd) for cmd, _ in items), 44)
    print()
    print(f"  {bar}")
    print(f"  {c(_DIM, 'Next')}")
    for cmd, desc in items:
        print(f"    {c(_ACCENT, ARROW)}  {c(_BOLD, cmd.ljust(width))}   {c(_DIM, desc)}")
    print()


def next_grouped(groups: list[tuple[str, list[tuple[str, str]]]]) -> None:
    """Closing 'Next' block split into labelled groups — e.g. terminal commands
    vs in-chat slash commands — so the user can tell them apart. Empty groups are
    dropped. groups = [(group_label, [(cmd, desc), …]), …]."""
    groups = [(lbl, items) for lbl, items in groups if items]
    if not groups:
        return
    bar = rule("┈")
    all_cmds = [cmd for _, items in groups for cmd, _ in items]
    width = min(max((len(cmd) for cmd in all_cmds), default=0), 40)
    print()
    print(f"  {bar}")
    print(f"  {c(_DIM, 'Next')}")
    for label, items in groups:
        print(f"    {c(_BOLD + _ACCENT, label)}")
        for cmd, desc in items:
            print(f"      {c(_ACCENT, ARROW)}  {c(_BOLD, cmd.ljust(width))}   {c(_DIM, desc)}")
    print()


def ask(prompt: str, default: str = "", *, cancel_on_interrupt: bool = False) -> str | None:
    """Blocking prompt with a branded caret.

    On EOF/Ctrl-C: returns None when ``cancel_on_interrupt`` (so a caller can
    treat an abort as cancel — distinct from an empty Enter that accepts the
    default), otherwise returns ``default`` (the convenient behavior for
    confirm-style prompts)."""
    try:
        ans = input(f"  {c(_ACCENT, CARET)} {prompt} ").strip()
        return ans or default
    except (EOFError, KeyboardInterrupt):
        print()
        return None if cancel_on_interrupt else default


def confirm(prompt: str, default: bool = True) -> bool:
    """Yes/No prompt. A bare Enter takes `default` (and sets the [Y/n] hint). A
    Ctrl-C / EOF returns False — an interrupt must NEVER silently proceed as a
    default 'yes' (e.g. it must not trigger an install or a `wsl --shutdown`)."""
    hint = "[Y/n]" if default else "[y/N]"
    ans = ask(f"{prompt} {c(_DIM, hint)}", cancel_on_interrupt=True)
    if ans is None:        # Ctrl-C / EOF → abort, not the default
        return False
    if not ans:            # bare Enter → the default
        return default
    return ans.lower() in ("y", "yes")
