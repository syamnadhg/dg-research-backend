"""No text a MODEL reads may point at a line number.

⛔ THE NOTE GUARD CANNOT SEE THIS, BY DESIGN. `test_no_line_pointers.py` reads
comments, docstrings and prose only: "a prompt, a log line or a fixture is
behaviour, and changing one to satisfy a guard would be a behaviour change". So
when the 10.10 sweep re-anchored every note, `PROMPT_DIAGNOSE` kept telling the
computer-use model that "legacy callers" at two research.py line numbers
parse its answer. Those lines had long since moved to unrelated code. A model can do
nothing with a line number, and a reader who followed one went the wrong way.

The fix was a deliberate prompt edit, not a sweep: the sentence stays, because
the diagnose callers still look for 'still generating' / 'response complete' in
the answer. Only the numbers went. This file keeps prompts.py at zero, which is
the one place the note guard leaves open.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A file name with a code or prose extension, then a colon and a number.
_POINTER = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|mjs|md|json|yaml|rules):\d+")


def _runtime_strings(path: Path) -> "list[tuple[int, str]]":
    """Every string constant in the file that is NOT a docstring — the text that
    ends up in a prompt. Docstrings are notes, and the note guard reads those."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def _pointers(strings: "list[tuple[int, str]]") -> "list[tuple[int, str]]":
    return [(line, m.group(0)) for line, text in strings for m in _POINTER.finditer(text)]


def test_no_prompt_points_at_a_line_number():
    hits = _pointers(_runtime_strings(ROOT / "prompts.py"))
    assert not hits, (
        "a prompt tells the model a line number — name what it means instead, "
        f"or drop it (a model cannot follow one): {hits}")


def test_the_diagnose_prompt_still_names_the_phrases_its_callers_read():
    """The numbers went; the instruction did not. The diagnose callers still
    look for these phrases in the answer, so dropping the sentence with the
    pointer would have been a real behaviour change."""
    import prompts
    text = prompts.PROMPT_DIAGNOSE
    assert "'still generating'" in text and "'response complete'" in text
    assert "parse for those substrings rather than the CONCLUSION marker" in text


def test_the_scan_reads_prompt_text_and_skips_docstrings(tmp_path):
    """⛔ Driven, so the guard above cannot pass by reading nothing: the same
    pointer is found in a constant, and not in a docstring."""
    probe = tmp_path / "probe.py"
    probe.write_text('"""A note: see research.py:12."""\n'
                     'P = """Callers (research.py:6509) parse this."""\n',
                     encoding="utf-8")
    assert _pointers(_runtime_strings(probe)) == [(2, "research.py:6509")]
