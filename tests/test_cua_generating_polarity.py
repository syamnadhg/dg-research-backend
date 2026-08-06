"""2026-08-05 prod incident — "✓ CUA confirms generating" on three explicit NOs.

The ChatGPT P2 send never landed. `wait_until_verified` fell through five DOM
checks and asked the CUA to look at the bottom of the chat. The CUA answered
(backend.log 682277, three minutes after a send that produced nothing):

    1. **Stop button?** No — the bottom composer shows a **Send arrow** (↑)
       button, not a Stop/square button.
    2. **Loading animation or spinner?** No spinning ring, pulsing dot, or
       progress bar is visible.
    3. **AI actively generating?** No — the response shows
       **"Research completed in 23m · 68 citations · searches"**

and the next line was `[2A] ✓ CUA confirms generating`.

The culprit was NOT the `"stop" + "yes"` clause. It was:

    has_loading = (...) or "progress bar" in diag_text

added 2026-05-14 with the justification "the phrase only appears when the bar
is actually present". The CUA enumerates what it looked for in order to DENY
it, so the phrase appears in a sentence whose subject is "No". One
unconditioned substring turned a dead leg into a healthy one; it then ran 36
more minutes on the PREVIOUS evening's conversation and its finished answer
was harvested into the run's report.

These tests execute the SHIPPED predicate expressions — lifted from
research.py by AST, not retyped — so a re-loosening cannot pass by being
described accurately in a comment.

Run:  pytest tests/test_cua_generating_polarity.py -v
"""
import ast
import inspect
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

# The verbatim answer that shipped a broken run.
PROD_ANSWER = (
    "1. **Stop button?** No — the bottom composer shows a **Send arrow** (↑) "
    "button, not a Stop/square button.\n"
    "2. **Loading animation or spinner?** No spinning ring, pulsing dot, or "
    "progress bar is visible.\n"
    "3. **AI actively generating?** No — the response shows "
    '**"Research completed in 23m · 68 citations · searches"**'
).lower()


# ── Lift the real expressions out of the shipped source ───────────────────

def _assigned_exprs(func, names):
    """Lift `names` out of `func`'s source as compiled expressions, IN SOURCE
    ORDER so a later one can consume an earlier one's value.

    Reading the expressions back out of research.py is the whole point: a test
    that retypes them proves only that the test author can copy.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    out, seen = [], set()
    for node in sorted((n for n in ast.walk(tree) if isinstance(n, ast.Assign)),
                       key=lambda n: (n.lineno, n.col_offset)):
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if isinstance(tgt, ast.Name) and tgt.id in names and tgt.id not in seen:
            seen.add(tgt.id)
            out.append((tgt.id, compile(ast.Expression(node.value), "<lifted>", "eval")))
    missing = set(names) - seen
    assert not missing, f"could not lift {missing} — the block was renamed or restructured"
    return out


def _evaluate(exprs, diag_text: str) -> dict:
    """Run the lifted expressions against one CUA answer. Only the polarity
    primitives are supplied from research — everything else the expression
    needs must come from an expression lifted alongside it."""
    env = {"_cua_affirms": research._cua_affirms,
           "_cua_denies": research._cua_denies,
           "any": any, "all": all,
           "diag_text": diag_text.lower()}
    vals = {}
    for name, code in exprs:
        env[name] = vals[name] = eval(code, env)
    return vals


WAIT_EXPRS = _assigned_exprs(
    research.wait_until_verified,
    {"_gen_phrases", "has_stop", "has_loading", "says_generating"})


def _wait_verdict(diag_text: str) -> dict:
    vals = _evaluate(WAIT_EXPRS, diag_text)
    vals["confirms_generating"] = bool(
        vals["has_stop"] or vals["has_loading"] or vals["says_generating"])
    return vals


# ── The incident ──────────────────────────────────────────────────────────

def test_the_prod_answer_no_longer_confirms_generating():
    v = _wait_verdict(PROD_ANSWER)
    assert v["confirms_generating"] is False, (
        f"three explicit NOs still read as generating: {v!r}"
    )


def test_each_predicate_individually_rejects_the_prod_answer():
    """Naming which one fired matters — the incident report guessed the
    stop/yes clause and the actual culprit was the loading branch."""
    v = _wait_verdict(PROD_ANSWER)
    assert v["has_stop"] is False, "the echoed question 'Stop button?' counted as evidence"
    assert v["has_loading"] is False, "an enumerated-then-denied 'progress bar' counted as evidence"
    assert v["says_generating"] is False, "'actively generating? No' counted as generating"


def test_a_denied_progress_bar_is_not_a_progress_bar():
    """The precise sentence, isolated. The 2026-05-14 justification was that
    this phrase 'only appears when the bar is actually present'."""
    denied = "no spinning ring, pulsing dot, or progress bar is visible."
    assert _wait_verdict(denied)["has_loading"] is False


def test_a_real_progress_bar_still_counts():
    """The 2026-05-14 signal was added for a reason — the post-Start Deep
    Research card does surface one. Affirmed, it must still win, or this fix
    trades one broken verdict for another."""
    assert _wait_verdict("progress bar: yes, it is filling steadily.")["has_loading"] is True


@pytest.mark.parametrize("answer,expected", [
    ("stop button: yes. loading animation: no.", True),
    ("stop button: no. loading animation: yes.", True),
    ("spinner: yes", True),
    ("the model is still generating the report.", True),
    ("it is actively generating.", True),
    # …and the negatives, each of which contains every keyword.
    ("stop button: no. loading: no. spinner: no. progress bar: no.", False),
    ("stop button: no. is the response complete: yes.", False),
    ("the model is not still generating; the response is complete.", False),
    ("no longer generating — the report is fully rendered.", False),
    ("there is no stop button, no spinner, and no progress bar.", False),
])
def test_affirmation_decides_not_mention(answer, expected):
    assert _wait_verdict(answer)["confirms_generating"] is expected, (
        f"{answer!r} -> {_wait_verdict(answer)!r}"
    )


def test_a_yes_answering_a_later_question_cannot_leak_backwards():
    """The original has_stop accepted a 'yes' anywhere in the whole answer."""
    answer = ("1. stop button? no.\n2. loading? no.\n"
              "3. is the response fully rendered? yes, completely.")
    assert _wait_verdict(answer)["confirms_generating"] is False


# ── The shape that caused it ──────────────────────────────────────────────

def test_no_unconditioned_substring_survives_in_the_block():
    src = code_only(research.wait_until_verified)
    i = src.index("has_stop =")
    block = src[i:src.index("if has_stop or has_loading or says_generating:")]
    assert '"progress bar" in diag_text' not in block, (
        "the unconditioned progress-bar substring is back"
    )
    assert '"stop" in diag_text' not in block, (
        "'stop' matches the echoed question — it must be affirmed, not present"
    )
    # Every keyword test routes through the primitive.
    assert block.count("_cua_affirms(") >= 8, (
        "a keyword signal is being tested without an affirmation check"
    )


def test_the_confirmation_log_says_which_signal_fired():
    """The prod line was bare. With three OR-ed predicates and no breakdown,
    reading the incident back required re-deriving the parse by hand."""
    src = code_only(research.wait_until_verified)
    line = src[src.index("CUA confirms generating"):][:220]
    for name in ("stop=", "loading=", "says="):
        assert name in line, f"the confirmation log omits {name}"


# ── One primitive, shared ─────────────────────────────────────────────────

def test_cua_affirms_scopes_the_yes_to_its_own_clause():
    assert research._cua_affirms("stop button: yes", "stop button") is True
    assert research._cua_affirms("stop button: no. complete: yes", "stop button") is False
    assert research._cua_affirms("nothing relevant here", "stop button") is False
    # Case-insensitive on both sides of the call.
    assert research._cua_affirms("Stop Button: YES", "stop button") is True


@pytest.mark.parametrize("text,key,denied", [
    # The exact echo shape that defeated the first version of this fix.
    ("**ai actively generating?** no — the response shows", "actively generating", True),
    ("**stop button?** no — the composer shows a send arrow", "stop button", True),
    ("stop button: none visible", "stop button", True),
    ("loading? n/a", "loading", True),
    # …and the readings that are NOT denials.
    ("the model is still generating the report.", "still generating", False),
    ("stop button: yes", "stop button", False),
    ("progress bar is filling", "progress bar", False),
    ("nothing about this key at all", "stop button", False),
    # A "no" answering a LATER question must not reach back.
    ("stop button: yes. spinner? no.", "stop button", False),
])
def test_cua_denies_reads_the_answer_not_the_question(text, key, denied):
    assert research._cua_denies(text, key) is denied


def test_denial_and_affirmation_never_both_fire():
    for text in ("**stop button?** no — send arrow only",
                 "stop button: yes",
                 "the model is still generating"):
        for key in ("stop button", "still generating"):
            assert not (research._cua_affirms(text, key)
                        and research._cua_denies(text, key)), (
                f"{text!r}/{key!r} read as both yes and no"
            )


def test_the_hardened_parser_delegates_to_the_primitive():
    """_classify_completion_verdict wrote this rule first and the two sibling
    parsers never reused it. Pin the delegation so they cannot diverge again."""
    src = code_only(research._classify_completion_verdict)
    assert "_cua_affirms(" in src, "the hardened parser re-implements the primitive"
    assert 'window.find(delim)' not in src, "a second copy of the clause scan is back"


def test_delegation_did_not_change_the_hardened_parser_behaviour():
    """The extraction must be behaviour-preserving — these are the verdicts
    #753 was written to produce."""
    assert research._classify_completion_verdict("stop button: yes") == "generating"
    assert research._classify_completion_verdict("still generating") == "generating"
    assert research._classify_completion_verdict("i cannot tell") == "generating"
    assert research._classify_completion_verdict("") == "generating"
    assert research._classify_completion_verdict("response complete") == "complete"
    assert research._classify_completion_verdict(
        "stop button: no. the response is complete.") == "complete"


# ── The twin in poll_until_done ───────────────────────────────────────────

POLL_EXPRS = _assigned_exprs(research.poll_until_done,
                             {"has_stop", "has_loading", "has_response"})


def _poll_verdict(diag_text: str) -> dict:
    return _evaluate(POLL_EXPRS, diag_text)


def test_the_twin_reads_forward_like_the_cua_actually_writes():
    """It used to look for 'yes' BEFORE the keyword — the direction #753's
    docstring records as broken, which biased this branch toward 'complete',
    the dangerous side."""
    assert _poll_verdict("stop button: yes")["has_stop"] is True
    assert _poll_verdict("stop button: no")["has_stop"] is False


def test_the_twin_no_longer_accepts_a_bare_completed():
    """'Research completed in 23m · 68 citations' is a stale activity summary —
    in the incident it belonged to a different conversation entirely."""
    v = _poll_verdict('the response shows "research completed in 23m · 68 citations". '
                      "is it complete? yes")
    assert v["has_response"] is False, (
        "a bare 'completed' still reads as a finished response"
    )


def test_the_twin_still_recognises_a_real_completion():
    assert _poll_verdict("response visible")["has_response"] is True
    assert _poll_verdict("response complete: yes")["has_response"] is True


def test_the_twins_no_early_return_invariant_is_intact():
    """The twin's looseness is documented as safe ONLY because it falls through
    to a DOM re-verify. If that ever becomes an early return, the compensating
    control is gone."""
    src = code_only(research.poll_until_done)
    i = src.index("has_response =")
    window = src[i:i + 1200]
    assert "return True" not in window.split("if is_generating:")[0], (
        "the fallback branch gained an early return — route it through "
        "_classify_completion_verdict first"
    )
