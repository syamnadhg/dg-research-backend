"""The NotebookLM share step must not claim a working link might be private.

WHAT WAS WRONG

`_set_nlm_public_and_get_link` runs the notebook's Share dialog and reads back
whether "Anyone with the link" is set. The strict DOM confirm has been False on
every run in the corpus, so a WARN saying "the link may genuinely be private"
fired on the healthy path — and the control genuinely not being found is real
DOM rot, which stays a WARN and stays `missed` in the run summary, because that
is how selector rot on this dialog gets noticed at all.

⛔⛔ SEVEN TESTS LEFT THIS FILE ON 2026-08-28 (stretch 6.6C), and all seven were
about the AUDIO card's dialog rather than the notebook's. That block is gone: it
opened the audio card's ⋮ menu to read a URL its own documented fallback already
held — "NotebookLM emits the SAME /notebook/{id} link whether you arrive via the
audio card's ⋮ or via the notebook's own Share button" — so `links.audio` and
`links.notebooklm` carried the same string on the healthy path, for 2.2 minutes
of CUA time a run.

⭐ THE ONE THAT MATTERS MOST STAYS, and it is the one this file was written to
protect: the shared helper KEEPS the "may genuinely be private" wording, because
the NOTEBOOK dialog has no earlier authority to defer to. Scoping the change to
the audio call site was the whole point; the audio call site going away must not
become an excuse to blanket-remove a true warning from the one that remains.
"""
import ast
from pathlib import Path

from conftest import code_only

RESEARCH = Path(__file__).resolve().parents[1] / "research.py"
SRC = RESEARCH.read_text(encoding="utf-8")


def _helper_src() -> str:
    """The shared helper the notebook dialog calls."""
    tree = ast.parse(SRC)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                n.name == "_set_nlm_public_and_get_link":
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError("_set_nlm_public_and_get_link not found")


def test_the_shared_helper_KEEPS_that_wording():
    """Deliberately untouched. The NOTEBOOK dialog has no earlier authority to
    defer to — if it finds neither the control nor an already-public state, the
    link may really be private and saying so is correct."""
    helper = _helper_src()
    assert "may genuinely be private" in helper, (
        "the notebook dialog has no earlier authority to defer to — if IT finds "
        "neither the control nor an already-public state, the link may really be "
        "private and saying so is correct"
    )


def test_the_helper_still_reports_the_three_outcomes_apart():
    """verified / access-set-but-unconfirmed / neither. Collapsing them is how
    the original confusion started — the middle case had already been demoted
    out of WARN for firing on the healthy path."""
    helper = code_only(_helper_src())
    assert "verified" in helper
    assert "access_set" in helper or "access " in helper
    assert helper.count("log(") >= 2


def test_the_dom_note_still_records_missed():
    """The run summary's ✗ is what makes this visible across runs at all. The
    change was to the operator line, not to the telemetry."""
    helper = SRC[SRC.index('_dom_note("notebooklm.set_public_access"'):][:600]
    assert '"missed"' in helper or "missed" in helper


def test_the_notebook_dialog_is_the_helpers_only_caller_now():
    """⛔ It had TWO. The audio call site went with the share block; if the
    notebook one ever goes too, this helper is dead code wearing three passing
    tests."""
    calls = code_only(SRC).count("_set_nlm_public_and_get_link(")
    assert calls == 2, f"expected the def plus exactly one caller, found {calls}"
