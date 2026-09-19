"""The orphan gate — prove the landed chat is ours, else go and find it (09-10).

⛔⛔ WHAT WAS MEASURED. The post-Send landing check was `"/app/" in url`. Its own
comment two lines above said the signal is that "the URL ADVANCES to /app/<id>
— every healthy run gets one, a dropped send never does". Advancing is a
CHANGE; a substring is a SHAPE, and the two differ in exactly one case: a tab
that was already inside a conversation when the brief was pasted. There the
check passes on the first poll, the entire recovery is skipped, and the run is
confirmed against a thread that may be the previous run's — the "stuck in a past
run" failure Layer 0.6 exists to prevent, reached through the one door it does
not watch.

⭐⭐ AND THE ANSWER IS THREE-VALUED, WHICH IS THE WHOLE SAFETY OF THE CHANGE.
`False` is now ACTED on: it walks the tab back to the home and into the sidebar
hunt. So "I cannot tell" — a bubble that has not finished rendering — must come
back as `None` and behave exactly as before. The owner ruled on this shape
already, on ChatGPT's landing verdict: "the entire lesson of 2026-08-27 is that
'I cannot tell' must never come out as 'this is somebody else's'."
"""

from __future__ import annotations

import asyncio
import ast
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from _domshim import NODE, run_js, spec_from_html


BRIEF = ("# Research Brief\n\n"
         "Quantum error correction in trapped-ion systems: the 2026 landscape, "
         "vendor roadmaps and the surface-code threshold debate")


# ── The identifying chunk ────────────────────────────────────────────────────

def test_the_shared_template_header_is_dropped_before_fingerprinting():
    """⛔ EVERY BRIEF THIS PRODUCT WRITES OPENS WITH THE SAME LINE, so a chunk
    taken from the very top identifies every run this product has ever done —
    a stranger's thread and last week's alike."""
    chunk = research._gemini_brief_chunk(BRIEF)
    assert "research brief" not in chunk
    assert chunk.startswith("quantum error correction")


def test_a_brief_without_the_header_keeps_its_own_first_words():
    chunk = research._gemini_brief_chunk("Tariff pass-through in EU dairy, 2019-2025")
    assert chunk.startswith("tariff pass-through")


def test_a_header_only_brief_yields_nothing_rather_than_the_header():
    assert research._gemini_brief_chunk("# Research Brief") == ""


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_no_brief_yields_no_chunk(bad):
    assert research._gemini_brief_chunk(bad) == ""


# ── Ours / not ours / cannot tell ───────────────────────────────────────────

def test_our_own_conversation_is_recognised():
    convo = ("Quantum error correction in trapped-ion systems: the 2026 landscape, "
             "vendor roadmaps and the surface-code threshold debate")
    assert research._gemini_conversation_is_ours(convo, BRIEF) is True
    assert research._gemini_conversation_ownership(convo, BRIEF) is True


def test_a_neighbouring_run_is_refused():
    """The owner's own sidebar, measured 09-10: it must adopt this run's brief
    and refuse the neighbouring run's."""
    convo = ("Compare the best pizzerias in Naples for a long weekend, with "
             "opening hours and how to book a table")
    assert research._gemini_conversation_is_ours(convo, BRIEF) is False
    assert research._gemini_conversation_ownership(convo, BRIEF) is False


def test_a_conversation_still_rendering_answers_cannot_tell():
    """⛔⛔ THE ARM THAT KEEPS A HEALTHY RUN IN ITS OWN THREAD. `False` sends the
    tab back to the home; a bubble that painted a moment late must never reach
    that branch."""
    for partial in ("", "Q", "Quantum", "Quantum error corr"):
        assert research._gemini_conversation_ownership(partial, BRIEF) is None, partial


def test_the_threshold_is_the_one_already_written_for_this_question():
    """`_CONVO_TEXT_MIN_CHARS`'s own comment says it: "below this many
    characters the conversation text is not evidence either way". Reusing it
    beats inventing a second number that can drift from the first."""
    n = research._CONVO_TEXT_MIN_CHARS
    assert research._gemini_conversation_ownership("x" * (n - 1), BRIEF) is None
    assert research._gemini_conversation_ownership("x" * n, BRIEF) is False


def test_no_brief_to_compare_against_answers_cannot_tell():
    """Not "not ours". With nothing to compare, there is no evidence — and a
    refusal here would walk every run out of its thread."""
    convo = "A" * 200
    for empty in (None, "", "   "):
        assert research._gemini_conversation_ownership(convo, empty) is None


def test_whitespace_and_case_do_not_change_the_answer():
    convo = ("  QUANTUM   ERROR\n\nCORRECTION in TRAPPED-ION systems: the 2026 "
             "landscape, vendor roadmaps and the surface-code threshold debate  ")
    assert research._gemini_conversation_ownership(convo, BRIEF) is True


# ── The read, executed ──────────────────────────────────────────────────────

class _Page:
    def __init__(self, ret=None, raises=False):
        self._ret = ret
        self._raises = raises
        self.js = None

    async def evaluate(self, js, arg=None):
        self.js = js
        if self._raises:
            raise RuntimeError("target closed")
        return self._ret


def test_the_read_passes_the_hoisted_js_through_unchanged():
    import json
    p = _Page(ret=json.dumps({"src": "turn", "text": "the brief"}))
    assert asyncio.run(research._gemini_read_conversation_text(p)) == ("the brief", True)
    assert p.js is research._GEMINI_CONVO_TEXT_JS


@pytest.mark.skipif(NODE is None, reason="node is required to run page JS")
def test_the_read_takes_the_users_own_turn_and_not_the_whole_body():
    """⛔⛔ EXECUTED, BECAUSE THE SOURCE-ORDER VERSION OF THIS TEST WAS WORTHLESS.
    It asserted that `user-query` appears before `document.body.innerText` in
    the JS text — and a body-first mutant leaves that true, because the
    `querySelector('user-query')` line still comes first either way. It survived
    the harness. The only question worth asking is what the JS RETURNS when the
    body and the user turn differ, and the body is the case that matters: it
    carries the rail's chat titles, so judging ownership from it finds our
    brief's words in a page that merely LISTS our other conversations."""
    html = ("<body>"
            "<div class='side-nav'>Quantum error correction in trapped-ion "
            "systems<br>Naples pizza weekend</div>"
            "<user-query>THE PASTED BRIEF FOR THIS RUN</user-query>"
            "<model-response>a plan</model-response>"
            "</body>")
    out = run_js(spec_from_html(html), research._GEMINI_CONVO_TEXT_JS)
    assert "THE PASTED BRIEF FOR THIS RUN" in out["ret"]
    assert "Naples pizza weekend" not in out["ret"], (
        "the read is returning the whole body — the rail's chat titles are now "
        "evidence about whose conversation this is")


@pytest.mark.skipif(NODE is None, reason="node is required to run page JS")
def test_the_body_is_still_the_fallback_when_there_is_no_user_turn():
    import json
    out = run_js(spec_from_html("<body><div>only body text here</div></body>"),
                 research._GEMINI_CONVO_TEXT_JS)
    got = json.loads(out["ret"])
    assert got["src"] == "body"
    assert "only body text here" in got["text"]


@pytest.mark.skipif(NODE is None, reason="node is required to run page JS")
def test_an_empty_user_turn_falls_back_and_says_so():
    """⛔⛔ THE EXACT SHAPE OF THE BLOCKER, EXECUTED. `user-query` mounted but not
    yet filled is FALSY, so the read falls through to the body — and the caller
    has to be told, because body text is chrome and chrome must never condemn."""
    import json
    html = ("<body><div class='side-nav'>New chat Recent Gems Settings and help"
            "</div><user-query></user-query></body>")
    got = json.loads(run_js(spec_from_html(html),
                            research._GEMINI_CONVO_TEXT_JS)["ret"])
    assert got["src"] == "body", (
        "an empty turn must be reported as a fallback, not as turn-scoped "
        "evidence")
    assert research._gemini_conversation_ownership(
        got["text"], BRIEF, from_turn=(got["src"] == "turn")) is None


def test_a_read_that_raises_is_no_evidence_never_a_refusal():
    """⛔ THE FAIL DIRECTION IS THE WHOLE POINT. A dead page must not be able to
    conclude "this is somebody else's chat" and walk a run out of its thread."""
    text, from_turn = asyncio.run(
        research._gemini_read_conversation_text(_Page(raises=True)))
    assert (text, from_turn) == ("", False)
    assert research._gemini_conversation_ownership(
        text, BRIEF, from_turn=from_turn) is None


@pytest.mark.parametrize("ret", [None, "", 0, "not json", '{"nope": 1}', "[]"])
def test_a_read_that_returns_nothing_usable_is_no_evidence_either(ret):
    text, from_turn = asyncio.run(
        research._gemini_read_conversation_text(_Page(ret=ret)))
    assert from_turn is False
    assert research._gemini_conversation_ownership(
        text, BRIEF, from_turn=from_turn) is None


# ── Page chrome may affirm; it may never condemn ─────────────────────────────

CHROME = [
    "Gemini 2.5 Pro New chat Recent Gems Explore Gems Settings and help",
    "Something went wrong. Try again later. Gemini can make mistakes, so "
    "double-check it",
    "Gemini 2.5 Pro Deep Research New chat Recent Settings and help",
]


@pytest.mark.parametrize("chrome", CHROME)
def test_body_sourced_text_can_never_condemn_a_conversation(chrome):
    """⛔⛔ THE BLOCKER CROSS-VERIFY FOUND, AND IT IS THE 2026-08-27 RULING BROKEN
    BY A FALLBACK RATHER THAN BY A JUDGEMENT. An `user-query` that is mounted but
    not yet filled is FALSY, so the read falls through to `document.body`; and
    Gemini's chrome is always well past the minimum-evidence threshold and never
    contains this run's brief. So the answer was a hard "not ours" for a page
    that simply had not painted yet — and `False` is acted on: it navigates the
    tab away from the run's own conversation and into the sidebar hunt."""
    assert len(chrome) > research._CONVO_TEXT_MIN_CHARS, (
        "the fixture must clear the evidence threshold or it proves nothing")
    assert research._gemini_conversation_ownership(
        chrome, BRIEF, from_turn=True) is False, (
        "turn-scoped text SHOULD still be able to condemn")
    assert research._gemini_conversation_ownership(
        chrome, BRIEF, from_turn=False) is None


def test_body_sourced_text_can_still_affirm():
    """Positive evidence is positive wherever it was read: if the page contains
    our brief, it is our conversation. Only the refusal needs the narrow
    source."""
    assert research._gemini_conversation_ownership(
        "Recent  Quantum error correction in trapped-ion systems: the 2026 "
        "landscape, vendor roadmaps and the surface-code threshold debate",
        BRIEF, from_turn=False) is True


def test_the_read_tells_the_caller_which_source_it_used():
    """⛔ Without this the caller cannot tell evidence from chrome, and the
    source-order test that used to stand here could not either."""
    import json
    for src_name, expect in (("turn", True), ("body", False)):
        text, from_turn = asyncio.run(research._gemini_read_conversation_text(
            _Page(ret=json.dumps({"src": src_name, "text": "x" * 100}))))
        assert from_turn is expect, src_name
        assert text == "x" * 100


# ── One opinion, not two ────────────────────────────────────────────────────

def test_the_adoption_gate_and_the_landing_check_ask_the_same_question():
    """⛔ A GATE THAT DECIDES WHICH THREAD IS OURS MUST NOT EXIST TWICE. The
    adoption closure used to carry its own copy of the chunk match and the token
    ratio; two copies of this drift, and the drift would show up as adopting a
    chat the landing check had just rejected."""
    adopt = inspect.getsource(research._gemini_adopt_lost_conversation)
    assert "_gemini_conversation_is_ours(" in adopt
    assert "_gemini_read_conversation_text(" in adopt
    assert "_gemini_owns_candidate(b[:300]" not in adopt, (
        "the closure has a second copy of the ownership maths again")


# ── The wiring ──────────────────────────────────────────────────────────────

def _setup_src():
    return inspect.getsource(research.start_agent_no_gemini_wait)


def _nested_func(name: str) -> "ast.AsyncFunctionDef":
    """The nested coroutine `name` inside `start_agent_no_gemini_wait`, parsed.

    Used wherever the claim is "this statement is INSIDE that branch", which
    source slicing cannot express and which a comment can defeat.
    """
    import textwrap
    tree = ast.parse(textwrap.dedent(_setup_src()))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from start_agent_no_gemini_wait")


def test_the_landing_check_consults_ownership_and_only_acts_on_a_refusal():
    src = _setup_src()
    land = src[src.index("async def _gemini_conversation_is_not_foreign"):]
    land = land[:land.index("if not await _gemini_landed(")]
    assert "_gemini_conversation_ownership(" in land, (
        "the landing check is back to being a URL-shape test")
    assert "_own is False" in land, (
        "the landing must accept True AND None — treating 'cannot tell' as a "
        "refusal walks a healthy slow-rendering run out of its own thread")


def test_every_confirmation_asks_the_ownership_question_not_the_url_shape():
    """⛔⛔ THE LADDER'S CONFIRMATION WAS AN `or` STRAIGHT BACK TO THE URL SHAPE.
    `if _landed or _gemini_in_conversation():` returned "submission confirmed"
    for a tab sitting in a chat the landing check had just refused — so fixing
    only the polling check would have left the whole fix bypassed on the
    re-paste path, which is the path a recovering run actually takes."""
    src = _setup_src()
    assert "_landed or _gemini_in_conversation()" not in src, (
        "a confirmation is comparing the URL's shape again")
    assert "_landed or await _gemini_conversation_is_not_foreign()" in src
    assert src.count("async def _gemini_conversation_is_not_foreign") == 1, (
        "the ownership question must have exactly one implementation")


def test_a_proven_foreign_chat_does_not_outlast_the_wait():
    """Polling a chat that is provably not ours cannot change the answer; only
    the recovery below can. Burning the 15- or 40-second deadline on it just
    delays the fix."""
    src = _setup_src()
    land = src[src.index("async def _gemini_landed"):]
    land = land[:land.index("if not await _gemini_landed(")]
    i_check = land.index("_gemini_conversation_is_not_foreign()")
    i_bail = land.index("if _wrong_chat:")
    i_sleep = land.index("asyncio.sleep(1.5)")
    assert i_check < i_bail < i_sleep


def test_the_wrong_chat_reset_happens_before_the_sidebar_hunt():
    """⛔ NOT FOR TIDINESS. The hunt refreshes the rail to freshen a stale Recent
    list, and its own rule is that it never reloads from inside a conversation
    — handing it a tab that is in one would break that rule from the outside."""
    src = _setup_src()
    i_reset = src.index("stepping out of the wrong conversation")
    i_adopt = src.index("_gemini_adopt_lost_conversation(")
    assert i_reset < i_adopt


def test_the_hunt_is_still_never_handed_a_tab_inside_a_conversation():
    src = _setup_src()
    assert "if not _controls.is_stop() and not _gemini_in_conversation():" in src, (
        "the adopt gate no longer requires the tab to be out of a conversation")


def test_the_wrong_chat_branch_is_gated_on_a_proven_refusal():
    src = _setup_src()
    assert "if _wrong_chat and _gemini_in_conversation() and not _controls.is_stop():" in src
    assert "_wrong_chat = True" in src


def test_the_latch_is_cleared_when_the_tab_is_out_of_a_conversation():
    """⛔⛔ A BLOCKER, AND THE TEST THAT USED TO STAND HERE COULD NOT SEE IT. It
    asserted the string `_wrong_chat = False` appeared SOMEWHERE in the
    function — which it did, on the good-landing path the ladder never reaches.

    The latch is `nonlocal` and read by BOTH waits. Set on a stale conversation
    and not cleared once the reset put the tab back on the bare home, the
    ladder's own `if _wrong_chat: return False` fired on poll one — so its
    40-second wait became ZERO on all three attempts, each attempt re-pasted
    into an empty composer, and a send that HAD landed produced two or three
    duplicate Deep Research conversations on the owner's account before the
    card. That is the duplicate-run failure #955 Phase 2G exists to prevent,
    reached through the recovery built for it.

    ⛔ AND IT ASSERTS IT THROUGH THE PARSER, because the first attempt at this
    test sliced the source between two markers and the explanatory comment
    directly above the fix QUOTES the very string the slice searched for — so
    the window closed early and the guard read as failing while the code was
    right. This repo has hit "prose quoting the searched string breaks the
    guard" four times in a single wave; the parser cannot be fooled by a
    comment."""
    fn = _nested_func("_gemini_conversation_is_not_foreign")
    for node in ast.walk(fn):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)):
            continue
        if "_gemini_in_conversation" not in ast.unparse(node.test):
            continue
        assigned = {ast.unparse(s) for s in node.body if isinstance(s, ast.Assign)}
        assert "_wrong_chat = False" in assigned, (
            "the latch survives a tab that is no longer in a conversation, so "
            f"the ladder's wait collapses to zero on a stale answer: {assigned}")
        return
    raise AssertionError("the not-in-a-conversation arm is gone")


def test_the_home_reset_reports_whether_it_worked():
    """⛔ The failure log below this branch reads "adoption rejected the sidebar
    candidate(s)" — when adoption never ran at all, because its gate requires
    the tab to be out of a conversation. That line is the primary forensic
    artefact for this incident class and it would misdirect the next look."""
    src = _setup_src()
    assert "if not await _gemini_reset_to_home():" in src, (
        "the reset's answer is discarded again")
    assert "sidebar hunt cannot run from inside one" in src


def test_the_home_reset_is_one_helper_used_by_both_branches():
    src = _setup_src()
    assert src.count("async def _gemini_reset_to_home") == 1
    assert src.count("_gemini_reset_to_home()") >= 2, (
        "the wrong-chat branch and the failed-adopt branch must share it")


def test_gemini_can_never_reach_the_landing_check_without_a_pasted_brief():
    """⛔⛔ A LATENT TRAP WORTH PINNING, BECAUSE THE GUARANTEE IS 700 LINES AWAY.
    The landing check now reads `brief_to_paste`, which is bound only on the
    inline-paste arm. Gemini always takes that arm — but only because
    `use_file_attach` carries `not is_gemini`, written far above and for an
    entirely different reason (Gemini silently drops file uploads). If that
    exclusion is ever lifted, every Gemini run would raise UnboundLocalError in
    the landing check. This test is the tripwire."""
    src = _setup_src()
    decl = [ln for ln in src.splitlines() if ln.strip().startswith("use_file_attach = ")]
    assert len(decl) == 1, decl
    assert "not is_gemini" in decl[0], (
        "Gemini can now take the file-attach arm, which does not bind "
        "brief_to_paste — the landing check would raise on every Gemini run")
    land = src[src.index("async def _gemini_conversation_is_not_foreign"):]
    assert "brief_to_paste" in land[:land.index("if not await _gemini_landed(")], (
        "the ownership check no longer reads the pasted brief — it cannot be "
        "deciding whose conversation this is")
