"""Phase-2 Gemini Deep-Research error recovery.

Root-caused 2026-06-29 from three concurrent runs whose Gemini DR all errored
("Sorry, something went wrong. Please try your request again." /
"I encountered an error doing what you asked. Could you try again?"). The brief DID
enter the conversation, but an errored DR leaves the URL bare /app, so the [2C]
submit-confirmation (which watches for /app/<id>) re-submitted once then FAILED FAST,
skipping [2D] and silently dropping Gemini (no gemini.md, run still "done").

Fix invariants this guards:
  1. The failure text for BOTH Gemini error variants is still recognised, and the
     regenerate control is still findable by title= too (icon-only buttons), not
     just aria-label/text.
  2. The [2C] confirmation loops (re-draft a failed turn on an error, else
     re-submit) in a bounded retry instead of re-submitting once + failing fast.
  3. Persistent failure surfaces a real Retry/Skip blocker (fail_agent) — never a
     silent skip / false "done".

⛔⛔ REWRITTEN 2026-09-18, AND THE REASON IS THE THING THIS FILE GOT WRONG FOR
FIFTEEN MONTHS. Every assertion here used to read
`inspect.getsource(research._try_inpage_retry_on_research_fail)` — including one
that re-extracted that helper's `fail_re` literal, un-doubled its backslashes,
compiled it in PYTHON, and fed it a sentence a human had written to satisfy it.
It never ran what the browser ran. The helper it certified could not click
Gemini's control (`aria-label="Redo"` against a word list of
`retry|regenerate|try again|rerun|restart`) and never did, in 96 MB of logs.

The helper is now RETIRED and its two send-path callers go through
`_gemini_retry_failed_turn` into the machinery built from the owner's 09-10
capture. So invariant 1 is re-pointed at the reader that actually runs — through
`_gemini_reads_as_failed`, its real consumer, not through a regex lifted out of
the source — and the behaviour it stands for is EXECUTED against the captured
DOM in test_gemini_redraft_0910.py. The two 2026-06-29 wordings above are kept
verbatim: they are this file's own evidence and they must not stop being
recognised because a reader changed hands.

Run:  pytest tests/test_gemini_dr_error_retry.py -v
"""
import ast
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from _domshim import run_js, spec_from_html  # noqa: E402

MODSRC = inspect.getsource(research)
# Both retry call sites live on the Gemini send path, in ONE function — so the
# wiring assertions below are scoped to it rather than to the whole 80k-line
# module, where "somewhere in the file" is all they could ever have meant.
SENDPATH = inspect.getsource(research.start_agent_no_gemini_wait)


def test_the_retired_helper_is_gone_and_nothing_calls_it():
    """⛔⛔ THE RETIREMENT ITSELF. Two readers of one screen is the shape this
    file's own history forbids, and a mutation harness cannot police two copies
    of a pattern: whichever one it mutates, the other keeps the tests green."""
    assert not hasattr(research, "_try_inpage_retry_on_research_fail")
    # ⛔⛔ PARSED, BECAUSE THE CONTAINMENT VERSION OF THIS LINE COULD NO LONGER
    # FAIL. `"_try_inpage_retry_on_research_fail(" not in MODSRC` was written
    # while the helper existed; with the helper gone the string is unreachable
    # by any realistic edit, so it certified the retirement while measuring
    # nothing — and the NAME deliberately survives in six tombstone comments
    # and docstrings, which is exactly what a containment pin cannot tell from
    # a live definition. The tree can: a re-added `def`, or a call from
    # anywhere in the module, fails here; prose does not.
    tree = ast.parse(MODSRC)
    assert [] == [n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "_try_inpage_retry_on_research_fail"], (
        "the retired helper was defined again")
    assert [] == [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_try_inpage_retry_on_research_fail"], (
        "something calls the retired helper again")
    # and the page JS that went with it — its own regex, its own word list, its
    # own assistant-scope walk — is gone from the module, not merely unreferenced
    for dead in ("retryWords", "failPattern", "isInComposerOrToolbar",
                 "isAssistantScoped"):
        assert dead not in MODSRC, f"{dead} survived the retirement"
    # the event nobody ever saw fired goes with it. ⛔ The NAME still appears in
    # the tombstone and in the capture notes, deliberately — "96 MB of logs and
    # not one of these" is the evidence for the deletion, so the assertion is on
    # the EMIT, not on the word.
    assert 'emit_event("inpage_retry_clicked"' not in MODSRC


def test_both_gemini_dr_errors_are_still_read_as_failures():
    """The two wordings from the 2026-06-29 incident, through the reader that
    replaced the one this file used to lift out of the source."""
    assert research._gemini_reads_as_failed(
        "Sorry, something went wrong. Please try your request again.")
    assert research._gemini_reads_as_failed(
        "I encountered an error doing what you asked. Could you try again?")


def test_healthy_text_is_still_not_read_as_a_failure():
    assert not research._gemini_reads_as_failed(
        "Researching your topic — this may take a few minutes.")
    assert not research._gemini_reads_as_failed(
        "Here is your research plan. Start research?")


#: An errored turn whose regenerate control is named by `title` ALONE — no
#: `data-test-id`, no `aria-label`, no text: the icon-only shape invariant 1 is
#: about. Every other way of finding it has been removed on purpose, so the
#: title read is the only thing that can succeed.
TITLE_ONLY_TURN = """
<model-response>
  <div class="response-container">
    <structured-content-container class="model-response-text">
      <message-content>I encountered an error doing what you asked. Could you try again?</message-content>
    </structured-content-container>
    <message-actions>
      <div class="actions-container-v2">
        <div class="buttons-container-v2">
          <button title="Redo"><mat-icon fonticon="refresh"></mat-icon></button>
        </div>
      </div>
    </message-actions>
  </div>
</model-response>
"""


def test_the_control_is_still_findable_by_its_title_attribute():
    """Icon-only regenerate buttons may carry their label in title=, not
    aria-label. The retired helper checked `title` explicitly; the reader that
    replaced it folds it into one accessible-name read, and that read is what
    the `label` shape falls back to when every test id has drifted.

    ⛔⛔ EXECUTED, NOT GREPPED — AND THAT IS THE WHOLE POINT OF THIS FILE'S
    REWRITE. The assertions this replaces were `"getAttribute('title')" in js`
    on the JS blob: they would have passed IDENTICALLY the day before the
    retirement, so they were evidence for nothing the wave did, and a read that
    is present but never reached would satisfy them. This runs the production
    reader under node against markup whose ONLY accessible name is a `title`
    and then asks the real picker what it chose.

    ⛔ NO `skipif(NODE is None)`. node is a requirement of this suite, stated
    once in `test_node_is_required_not_skipped_0917.py`; a pin that disappears
    on the machines that lack it is how lanes report done having proved
    nothing."""
    out = run_js(spec_from_html("<body>" + TITLE_ONLY_TURN + "</body>"),
                 research._GEMINI_LATEST_TURN_JS)
    reading = json.loads(out["ret"])
    assert reading["found"] is True, "the reader did not even find the turn"
    control, why = research._gemini_regen_control(reading["controls"])
    assert control is not None, why
    assert control["name"] == "Redo"
    assert control["visible"] is True and control["disabled"] is False
    # the wording fallback still knows the only word Gemini has ever shown
    assert research._GEMINI_REGEN_LABEL_RE.search("redo")


def test_2c_confirmation_has_bounded_retry_loop():
    assert "for _att in range(1, _max_attempts" in SENDPATH, (
        "Gemini [2C] confirmation must retry in a bounded loop, not re-submit once"
    )
    # ⛔ BOTH call sites, and ONLY these two: the send-path guard after the send,
    # and the re-paste ladder's per-attempt retry. A count, not a containment —
    # the assertion this replaces was satisfied by either one alone.
    assert SENDPATH.count("_gemini_retry_failed_turn(") == 2


def test_2c_persistent_failure_raises_blocker_not_silent_skip():
    # a real Retry/Skip blocker on persistent failure ...
    # #63: the couldn't-start copy is centralized in the _GEMINI_CANT_START
    # constant; the persistent-failure site spreads it.
    assert 'fail_agent("gemini", *_GEMINI_CANT_START)' in MODSRC, (
        "persistent Gemini submit failure must call fail_agent (no silent skip)"
    )
    assert research._GEMINI_CANT_START[0] == "Gemini couldn't start Deep Research"
    # ... and the old single-resubmit silent fail-fast log is gone
    assert "skips the 10-min plan wait" not in MODSRC, (
        "old silent fail-fast path should be replaced by the retry loop + blocker"
    )
