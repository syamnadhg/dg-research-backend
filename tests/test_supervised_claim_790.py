"""7.9-0 — two more sentences that were true regardless of what happened.

⛔⛔ SAME SHAPE AS THE WAVE'S HEADLINE DEFECT, found while fixing it. `--resurrect`
and `--retire` end with "✓ Synced to the Super Research app" at five sites, and
the helper that does the syncing returned NOTHING — it logged its own failures
and handed the caller no way to know. Both of its failure paths are reachable: a
machine with no device id, and a REST patch the rules refused. On either one the
person watching was told the app had been updated when it had not, about the
setting they had just changed.

⛔⛔ AND ONE DEAD FUNCTION WAS WORSE THAN A WRONG MESSAGE. `generate_device_id`
had zero callers and a docstring reading "subsequent --pair runs reuse the
persisted id" — the exact opposite of the truth, on the one question that decides
whether pairing repairs a machine or replaces it. Anyone reasoning from it
concludes that recommending `--pair` after a reset is harmless. It is how this
whole wave's defect looks defensible from the inside.
"""
import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


def _code_only(text: str) -> str:
    doc_lines = set()
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            doc_lines.update(
                range(first.lineno, (first.end_lineno or first.lineno) + 1)
            )
    return "\n".join(
        l for i, l in enumerate(text.splitlines(), 1)
        if i not in doc_lines and not l.strip().startswith("#")
    )


CODE = _code_only(Path(research.__file__).read_text(encoding="utf-8"))


def test_the_sync_helper_reports_whether_the_app_heard():
    src = inspect.getsource(research._write_supervised_flag)  # noqa: SLF001
    assert "return False" in src and "return True" in src


def test_no_device_id_is_a_failure_not_a_silent_success(monkeypatch):
    """⛔ THE PATH THAT MATTERS MOST: an unpaired machine could not possibly
    have told the app anything, and this was the branch that returned early."""
    monkeypatch.setattr(research, "load_device_id", lambda: None)
    assert research._write_supervised_flag(True) is False  # noqa: SLF001


def test_a_refused_patch_is_a_failure(monkeypatch):
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(
        research, "_pair_patch_device", lambda *a, **kw: False
    )
    assert research._write_supervised_flag(False) is False  # noqa: SLF001


def test_a_written_patch_is_a_success(monkeypatch):
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(
        research, "_pair_patch_device", lambda *a, **kw: True
    )
    assert research._write_supervised_flag(True) is True  # noqa: SLF001


def test_every_synced_tick_is_guarded():
    """⛔ FIVE SITES, AND THE COUNT IS THE POINT: a sixth added without a guard
    reintroduces the defect."""
    assert CODE.count("Synced to the Super Research app") == 5
    for chunk in CODE.split("Synced to the Super Research app")[:-1]:
        assert "_synced" in chunk[-400:], (
            "a tick is printed without checking whether the app heard"
        )


def test_the_guard_variable_is_actually_bound_everywhere_it_is_read():
    """⛔⛔ THE PREVIOUS TEST PASSED ON CODE THAT RAISED, and this one exists
    because of it. Cross-verify found that one of the five sites had its PRINT
    converted to `if _synced:` while its CALL still discarded the result — so
    the name was read and never bound on the default `--pair` path. The textual
    check above was satisfied by the very line that crashed, because the string
    it looks for is IN that line.

    An UnboundLocalError there is not a cosmetic failure: `cmd_pair_v2`'s
    `finally` reads any exception as an interrupted pair and runs
    `_cleanup_partial_pair`, which deletes the device server-side, revokes the
    synthetic user and wipes the local config. The pairing flow would have
    destroyed the machine it had just created.

    ⭐ PROXIMITY IS THE WRONG PROPERTY; BINDING IS THE RIGHT ONE. CPython emits
    LOAD_FAST_CHECK only for a local it has proven MAY be unbound, so asking the
    compiler is exact — no AST walking, no guessing about branches."""
    import dis

    code = compile(
        Path(research.__file__).read_text(encoding="utf-8"),
        research.__file__,
        "exec",
    )

    def _walk(c):
        yield c
        for const in c.co_consts:
            if hasattr(const, "co_code"):
                yield from _walk(const)

    unbound = [
        (c.co_name, ins.positions.lineno)
        for c in _walk(code)
        for ins in dis.get_instructions(c)
        if ins.opname == "LOAD_FAST_CHECK" and ins.argval == "_synced"
    ]
    assert not unbound, (
        f"_synced is read on a path where it may be unbound: {unbound}"
    )


def test_the_misleading_dead_generator_is_gone():
    """⛔ IT HAD NO CALLERS AND STILL DID DAMAGE — a reader trusting it
    concludes that pairing after a reset is harmless."""
    assert not hasattr(research, "generate_device_id")
    # ⛔⛔ THE SCOPE HERE IS COMMENTS-OUT, DOCSTRINGS-IN, AND BOTH HALVES ARE
    # LOAD-BEARING. The claim only ever lived in a DOCSTRING, so searching the
    # fully stripped text (which drops docstrings) could never have caught it
    # coming back — vacuous in the one direction that matters. But searching the
    # RAW text fails on the tombstone COMMENT left where the function was, which
    # quotes the sentence in order to explain why it is gone. That is the fourth
    # time in this wave that prose quoting the thing being searched for has
    # broken a guard, so the scope is stated rather than rediscovered.
    raw = Path(research.__file__).read_text(encoding="utf-8")
    no_comments = "\n".join(
        l for l in raw.splitlines() if not l.strip().startswith("#")
    )
    assert "reuse the persisted id" not in no_comments
    assert "reuses the persisted id" not in no_comments
