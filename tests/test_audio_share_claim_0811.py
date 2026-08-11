"""The audio share step must not claim a working link might be private.

WHAT WAS WRONG

`_set_nlm_public_and_get_link` runs twice in a Phase 3: once for the NOTEBOOK's
Share dialog, once for the AUDIO card's. They are two different dialogs, and both
e2e runs on 2026-08-10 produced this pair:

    22:00:26  ✓ set_public_access: verified      (notebook)
    22:05:22  ✗ set_public_access: missed        (audio)

The audio branch then logged "audio link may genuinely be private". It was not:
NotebookLM emits the SAME /notebook/{id} URL from either dialog — the fallback
directly beneath that branch depends on exactly that identity — so the notebook
step had already settled public access minutes earlier and logged its own verdict.

So the only line an operator reads about the audio link asserted a privacy problem
on a link that demonstrably worked, in a run that ALSO said verified. Two
verifications disagreeing, and the pessimistic one shown.

The control genuinely was not found, and that stays a WARN and stays `missed` in
the run summary — that is how selector rot on this dialog gets noticed at all.
What changed is that it now reports the control it could not find, instead of
guessing at an outcome it has no evidence for.

Nothing about the pipeline's behaviour changes: this branch only ever logged.
"""
import ast
from pathlib import Path

from conftest import code_only

RESEARCH = Path(__file__).resolve().parents[1] / "research.py"
SRC = RESEARCH.read_text(encoding="utf-8")


def _helper_src() -> str:
    """The shared helper both dialogs call."""
    tree = ast.parse(SRC)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                n.name == "_set_nlm_public_and_get_link":
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError("_set_nlm_public_and_get_link not found")


def _audio_share_block() -> str:
    """The audio share region, CODE ONLY — comments blanked.

    ⚠ The comment on this very fix quotes the phrase the first test bans, and the
    prose explaining the new message repeats its wording. Both assertions passed
    against my own commentary before this stripped them. Same trap `code_only`
    exists for, and the third time it has bitten in a day.
    """
    start = SRC.index('_set_nlm_public_and_get_link(page, "Audio")')
    end = SRC.index("if not audio_overview_url:", start)
    return code_only(SRC[start:end])


def test_the_audio_branch_no_longer_claims_the_link_may_be_private():
    """THE fix. It was the only line the operator saw about the audio link."""
    block = _audio_share_block()
    assert "may genuinely be private" not in block, block[-700:]


def test_the_shared_helper_KEEPS_that_wording():
    """Deliberately untouched. The helper is also used by the NOTEBOOK dialog,
    where there is no earlier authority to defer to — if that one finds neither
    the control nor an already-public state, the link may really be private and
    saying so is correct. Scoping the change to the audio call site is the whole
    point; blanket-removing the phrase would delete a true warning."""
    helper = _helper_src()
    assert "may genuinely be private" in helper, (
        "the notebook dialog has no earlier authority to defer to — if IT finds "
        "neither the control nor an already-public state, the link may really be "
        "private and saying so is correct"
    )


def test_the_missed_control_is_still_a_WARN():
    """The control not being found is real DOM rot. Softening this to INFO would
    trade a misleading line for an invisible one, which is worse — this dialog's
    selector rot was invisible for the entire life of the corpus once already."""
    block = _audio_share_block()
    at = block.rindex("log(")
    assert '"WARN"' in block[at:], block[at:at + 400]


def test_the_new_line_points_at_the_authority():
    """An operator reading it has to know where the real answer is. Otherwise it
    is just a quieter version of the same dead end."""
    block = _audio_share_block()
    assert "share step set" in block, block[-500:]


def test_the_new_line_says_what_was_actually_not_found():
    """"Something went wrong" is what made this take two runs to understand."""
    # The sentence is built from adjacent string literals, so it is split by
    # quotes mid-phrase in the source. Assert on a fragment that lives inside one
    # literal rather than flattening whitespace, which leaves the quotes behind.
    block = _audio_share_block()
    assert "access control was not" in block, block[-500:]


def test_the_dom_note_still_records_missed():
    """The run summary's ✗ is what makes this visible across runs at all. The
    change is to the operator line, not to the telemetry."""
    helper = SRC[SRC.index('_dom_note("notebooklm.set_public_access"'):][:600]
    assert '"missed"' in helper or "missed" in helper


def test_the_branch_only_logs_and_changes_no_control_flow():
    """The safety property. This was a logging defect on a healthy path, and the
    fix must not be able to alter what Phase 3 does — no return, no raise, no
    assignment to anything the pipeline reads."""
    block = _audio_share_block()
    tail = block[block.rindex("else:"):]
    for forbidden in ("return", "raise", "continue", "break", "audio_overview_url ="):
        assert forbidden not in tail, f"{forbidden!r} appeared in a log-only branch:\n{tail}"


def test_the_url_fallback_that_makes_this_true_is_still_there():
    """The claim rests on both dialogs emitting one URL. If that fallback ever
    goes, the reasoning in the new message goes with it."""
    at = SRC.index('_set_nlm_public_and_get_link(page, "Audio")')
    after = SRC[at:at + 3000]
    assert "audio_overview_url = notebook_url" in after or "current_url" in after


def test_the_three_outcomes_are_still_distinguished():
    """verified / access-set-but-unconfirmed / neither. Collapsing them is how the
    original confusion started — the middle case had already been demoted out of
    WARN for firing on the healthy path, and this is the third."""
    block = _audio_share_block()
    assert "audio_public_verified" in block
    assert "audio_access_set" in block
    assert block.count("log(") >= 3
