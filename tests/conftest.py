"""Shared pytest fixtures / environment pins for the dg-research-backend suite.

#955 Phase 3: the async AI copy sharpen (`DG_ALERT_AI_COPY`) is OFF in prod by
default and MUST stay off across the whole suite so every alert-copy assertion
sees the deterministic TEMPLATE, never a live (or mocked) LLM rewrite. Without
this pin a developer with the flag exported in their shell would see spurious
byte-parity failures. Tests that exercise the enabled path opt in explicitly
with `monkeypatch.setenv("DG_ALERT_AI_COPY", "1")` (pytest restores it after).
"""
import ast
import inspect
import io
import os
import textwrap
import tokenize

import pytest

# Force OFF at collection time — before any test module imports `research`.
os.environ["DG_ALERT_AI_COPY"] = "0"

# Same reason, different flag: `FORCE_COLOR` makes `_USE_COLOR` true even when
# stdout is a pipe, which is precisely the case under pytest. Several CI images
# and dev shells export it globally, and every assertion that compares a `_c()`
# result to plain text would then see ANSI escapes. Colour is a display
# decision, never test input — pin it off for the whole suite. Tests that need
# it on pass the value into `_color_decision` directly or set it on a
# subprocess env (see tests/test_cli_color_decision.py).
os.environ.pop("FORCE_COLOR", None)


def serving_version(monkeypatch, version: "str | None"):
    """Say what the process publishing the update verdict is executing.

    That is `_BOOT_VERSION`, frozen at import, and NOT the on-disk version: the
    two diverge the moment pipx finishes, which is the whole distinction the
    verdict turns on. Shared because two files need the same fact.

    Deliberately not the `running-version.json` marker, which an earlier draft
    used. That file is a single path with no worker id written by every `--serve`,
    so on a multi-worker host it names whichever worker started last while the
    verdict is published by worker 1 — a test built on it would be asserting
    about the wrong process."""
    import research
    monkeypatch.setattr(research, "_BOOT_VERSION", version)


def code_only(target) -> str:
    """Source of `target` (a function, or a source string) with `#` comments
    stripped and all other layout preserved byte-for-byte.

    MANDATORY for any assertion that checks what the CODE does. Verified by
    mutation twice over: a mutation that DELETED `and not _p3_link_user_skipped`
    from the Phase-3 terminal gate — i.e. re-introduced the exact bug the test
    was written for — SURVIVED, because the explanatory comment directly above
    the gate names the flag and a presence assertion cannot tell code from prose.
    The same trap ate a share-dialog selector assertion whose fix comment quoted
    the selector it replaced.

    Comments are blanked IN PLACE rather than the source rebuilt from tokens:
    rebuilding normalises whitespace, which would make every assertion depend on
    how the tokenizer happens to space a condition.
    """
    src = target if isinstance(target, str) else inspect.getsource(target)
    lines = src.splitlines(keepends=True)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        r, c0 = tok.start[0] - 1, tok.start[1]
        lines[r] = (lines[r][:c0] + " " * len(tok.string)
                    + lines[r][c0 + len(tok.string):])
    return "".join(lines)


def code_only_deep(target) -> str:
    """`code_only`, plus DOCSTRINGS and the `//` comments inside embedded JS.

    Half of research.py's logic lives in page.evaluate JS held in Python string
    literals, so `code_only` alone leaves those comments intact — and the same
    trap applies there: a comment explaining "this used to be `>= floor`" makes
    an assertion that the floor is GONE pass or fail on prose rather than code.
    Docstrings do it too, and worse, because they quote example values ("3.5
    FlashAll-around help") that read exactly like the pinned literals a
    no-version-literals assertion is hunting for.

    Everything is blanked IN PLACE, same as `code_only`, so column positions and
    any ordering/index assertions built on them stay valid. Only whole-line `//`
    comments are blanked: a `//` mid-line could be inside a regex literal
    (`/https?:\\/\\//`), and mangling one of those would be worse than leaving a
    trailing comment in.

    Use `code_only` when the assertion is about Python code and the docstring is
    irrelevant; use this when prose of ANY kind could satisfy the match.
    """
    src = code_only(target)
    # ── docstrings, via ast so the span is exact ──
    try:
        tree = ast.parse(textwrap.dedent(src))
        dedented = textwrap.dedent(src)
        pad = len(src.splitlines()[0]) - len(dedented.splitlines()[0]) if src.splitlines() else 0
        lines = dedented.splitlines(keepends=True)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            body = getattr(node, "body", None)
            if not body or not isinstance(body[0], ast.Expr):
                continue
            val = body[0].value
            if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
                continue
            for ln in range(val.lineno - 1, val.end_lineno):
                start = val.col_offset if ln == val.lineno - 1 else 0
                end = val.end_col_offset if ln == val.end_lineno - 1 else len(lines[ln].rstrip("\r\n"))
                nl = lines[ln][len(lines[ln].rstrip("\r\n")):]
                body_txt = lines[ln].rstrip("\r\n")
                lines[ln] = body_txt[:start] + " " * (end - start) + body_txt[end:] + nl
        src = "".join(" " * pad + ln if ln.strip() or pad == 0 else ln for ln in lines)
    except SyntaxError:
        pass  # not parseable standalone (a raw JS string) — comments-only is fine
    return js_code_only(src)


def js_code_only(js: str) -> str:
    """Whole-line `//` comments blanked IN PLACE, for a BARE JS string.

    `code_only_deep` already does this to JS embedded in Python source, but a
    module-level JS constant (`research._GEMINI_FLASH_RANK_JS`) is not Python
    and `code_only`'s tokenizer refuses it outright — so assertions run straight
    against such a constant were matching the explanatory PROSE above the code.
    That is precisely the trap `code_only` exists to close, one layer down: a
    no-version-literals guard failed on a comment naming two model rows by way
    of explaining why the parser must accept BOTH version orders.

    Only whole-line comments are blanked, same rule and same reason as
    `code_only_deep`: a mid-line `//` may live inside a regex literal.
    """
    out = []
    for line in js.splitlines(keepends=True):
        if line.lstrip().startswith("//"):
            body = line.rstrip("\r\n")
            out.append(" " * len(body) + line[len(body):])
        else:
            out.append(line)
    return "".join(out)


@pytest.fixture(autouse=True)
def _update_sentinels_never_touch_the_real_home(tmp_path_factory, monkeypatch):
    """Point the self-update sentinels at a scratch dir for EVERY test.

    These are module constants baked from `_STATE_DIR` at import, so a test that
    patches `_STATE_DIR` does NOT move them — which meant exercising the real
    `_spawn_detached_lifecycle` wrote a live `update_intent.json` into the
    developer's own `~/.super-research`, where the next run read it back and a
    completely unrelated test failed. Redirecting by default makes the isolation a
    property of the suite instead of something each test has to remember; tests
    that care still patch these explicitly and win, because they run after this."""
    import research
    d = tmp_path_factory.mktemp("sr-update-state")
    # raising=True on purpose: renaming either constant must BREAK here, not
    # silently turn this fixture into a no-op that lets the suite write to the
    # developer's real ~/.super-research again — the exact failure it prevents.
    monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", d / "update_result.json")
    monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", d / "update_intent.json")
    # The live-serve marker joins them for the same reason: `_restart_pending`
    # reads it, so leaving it pointed at the real home would make a test's answer
    # depend on whether the developer happens to have a backend running.
    monkeypatch.setattr(research, "_RUNNING_VERSION_PATH", d / "running_version.json")
    # And the DIRECTORY those constants were baked from, because redirecting only
    # the constants leaves everything that derives a path at call time still
    # writing to the real home — `_spawn_detached_lifecycle` creates `_STATE_DIR`
    # and opens `upgrade.log` inside it, which is the same class of leak.
    monkeypatch.setattr(research, "_STATE_DIR", d)
    yield


def _clipboard_double(value):
    """A stand-in carrying a flag that says it IS one.

    The flag exists so the isolation below can be asserted rather than assumed:
    without it, deleting the fixture is invisible to the suite — every test
    still passes while quietly shelling out to pbcopy on the developer's
    machine. Verified by mutation; that deletion survived a full sweep.
    """
    def _double():
        return value
    _double.is_suite_clipboard_double = True
    return _double


@pytest.fixture(autouse=True)
def _the_suite_never_touches_the_real_clipboard(monkeypatch):
    """Neutralise the OS clipboard for EVERY test.

    `clear_clipboard()` shells out to pbcopy / wl-copy / Set-Clipboard, so any
    test that reaches a share extractor would WIPE whatever the developer had
    copied — a real side effect on their machine from running the suite, and
    invisible until they went to paste something. `get_clipboard()` is the same
    hazard read-side: left unpatched it makes a test's answer depend on what
    happens to be on the developer's clipboard at the time.

    Same rationale as the update-sentinel fixture above: isolation belongs to
    the suite, not to whichever test remembers. Tests that want to observe or
    script either function patch them explicitly and win, because they run
    after this.

    raising=True on purpose — renaming either function must BREAK here rather
    than silently turn this into a no-op.
    """
    import research
    monkeypatch.setattr(research, "clear_clipboard", _clipboard_double(None))
    monkeypatch.setattr(research, "get_clipboard", _clipboard_double(""))
    yield


@pytest.fixture(autouse=True)
def _alert_ai_copy_off_by_default():
    """Re-assert the OFF default before every test so one test flipping it on
    via a raw os.environ write (rather than monkeypatch) can't leak forward."""
    os.environ["DG_ALERT_AI_COPY"] = "0"
    yield
