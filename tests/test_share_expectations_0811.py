"""Two warnings that fired on every single run, and so warned about nothing.

BOTH ARE FALSE ALARMS, AND BOTH WERE CONFIRMED FALSE BY THE OWNER.

ChatGPT. The pipeline warned on every run that it had fallen back to a
conversation URL "which is NOT viewable by anyone else". That fallback is the
intended ending for this agent: durable links reach the owner by email in the
Google Doc, and no public ChatGPT share is wanted. So the line described a
correct outcome in the language of a failure, once per run, forever.

That is not merely noise. Gemini and Claude really DID lose their public share
links on 2026-08-11 — both vendors had moved hosts and both links were silently
discarded — and the line that should have made that obvious was already
indistinguishable from ChatGPT's routine one. A warning that fires when nothing
is wrong is how a warning that matters gets skipped.

NotebookLM. The pipeline warned that a notebook's "public access [was] NOT
DOM-verified — the link may be private". The owner reports these notebooks come
out public every time, and the comment sitting above the check records that
`verified` has NEVER once been true in the whole corpus. So the message was
wrong on 100% of runs. What actually broke is the read-BACK: the control that
used to expose "Anyone with the link" no longer matches. The share step itself
ran, and its genuine failures have their own separate warnings, which are
untouched.

WHAT THESE TESTS PIN

  1. A missing public share still WARNS for Gemini and Claude — the regression
     that already happened once must stay loud.
  2. It does not warn for ChatGPT, and the ChatGPT line still carries the same
     detail, so the outcome is quiet but not unexplained.
  3. The expectation is one table, consulted — not a literal spelled out at the
     log call, which is how the duplicated share predicate drifted before.
  4. NotebookLM's read-back failure says what failed (the detector) instead of
     what did not (the sharing), and NotebookLM's REAL access failures keep
     their warnings.
"""
import functools
import inspect
import io
import re
import tokenize

import pytest

import research


@functools.lru_cache(maxsize=8)
def code_only(src: str) -> str:
    """`src` with comments blanked, offsets preserved. Required here: the
    comments explaining both fixes quote the old wording verbatim."""
    out = list(src)
    starts, pos = [], 0
    for line in src.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            (srow, scol), (erow, ecol) = tok.start, tok.end
            if srow != erow or srow > len(starts):
                continue
            line_start = starts[srow - 1]
            for i in range(line_start + scol, min(line_start + ecol, len(out))):
                out[i] = " "
    except (tokenize.TokenError, IndentationError):
        return src
    return "".join(out)


@functools.lru_cache(maxsize=1)
def fallback_src() -> str:
    """The share-link fallback block in extract_and_record_agent."""
    src = code_only(inspect.getsource(research.extract_and_record_agent))
    at = src.index("_detail = ")
    return src[at:at + 1200]


# ------------------------------------------------- which agents are expected


@pytest.mark.parametrize("agent", ["gemini", "claude"])
def test_a_missing_public_link_is_still_a_fault_for_these(agent):
    """⭐ Both lost their public links for real on 2026-08-11. Silencing them
    is the way this fix could do damage."""
    assert research._public_share_is_expected(agent) is True


def test_chatgpt_is_not_expected_to_produce_one():
    """The owner's call: the conversation URL is the intended ending."""
    assert research._public_share_is_expected("chatgpt") is False


@pytest.mark.parametrize("agent", ["ChatGPT", "  chatgpt  ", "CHATGPT"])
def test_the_agent_name_is_matched_case_and_space_insensitively(agent):
    """Call sites pass the agent key in whatever case they hold it."""
    assert research._public_share_is_expected(agent) is False


@pytest.mark.parametrize("agent", ["Gemini", " CLAUDE "])
def test_expected_agents_match_the_same_way(agent):
    assert research._public_share_is_expected(agent) is True


@pytest.mark.parametrize("agent", ["", None, "notebooklm", "perplexity"])
def test_an_unknown_agent_is_not_treated_as_expecting_a_share(agent):
    """Quiet is the safe default for something we have never shipped: a new
    agent must not start warning about a link nobody asked it for."""
    assert research._public_share_is_expected(agent) is False


def test_the_expectation_lives_in_one_table():
    """The share-link outage of this same day was caused by the SAME predicate
    existing twice and the copies drifting. One table, consulted."""
    src = fallback_src()
    assert "_public_share_is_expected(agent_key)" in src
    assert '"chatgpt"' not in src, (
        "the agent is named at the log call again — that is the duplicated "
        "predicate shape that lost every share link this morning"
    )


# ------------------------------------------------------ what each branch says


def test_the_expected_branch_still_warns_that_the_link_is_private():
    src = fallback_src()
    warn = src[:src.index("else:")]
    assert "no public share link" in warn
    assert "NOT" in warn and "viewable by anyone else" in warn
    assert re.search(r'"WARN"\)', warn), "a lost public share is not an INFO line"


def test_the_quiet_branch_does_not_warn():
    src = fallback_src()
    quiet = src[src.index("else:"):]
    assert '"WARN"' not in quiet
    assert '"DEBUG"' in quiet


def test_the_quiet_branch_does_not_borrow_the_alarming_copy():
    """It describes a correct outcome; it must not read like a failure."""
    quiet = fallback_src()[fallback_src().index("else:"):]
    assert "viewable by anyone else" not in quiet
    assert "no public share expected" in quiet


def test_the_quiet_branch_still_carries_the_reason():
    """Quiet, not unexplained — the detail that names WHICH failure happened
    reaches both branches, so a genuine ChatGPT breakage is still diagnosable
    from a verbose log."""
    src = fallback_src()
    assert src.count("{_detail}") == 2


def test_the_detail_still_distinguishes_the_two_failures():
    src = fallback_src()
    detail = src[:src.index("if _public_share_is_expected")]
    assert "did not pass the public-share" in detail
    assert "returned no URL at all" in detail
    assert "{_got[:120]}" in detail


# ------------------------------------------------------------- notebooklm


@functools.lru_cache(maxsize=1)
def module_src() -> str:
    return code_only(inspect.getsource(research))


def test_notebooklm_no_longer_calls_a_shared_notebook_maybe_private():
    """The claim was wrong on every run in the corpus."""
    src = module_src()
    assert "public access NOT DOM-verified" not in src
    assert "URL-shape OK but public-share NOT DOM-verified" not in src


def test_notebooklm_names_the_detector_as_what_failed():
    """Saying nothing at all would be the other kind of wrong — the read-back
    IS broken and someone should eventually fix the selector."""
    src = module_src()
    assert "could not read the sharing state back" in src
    assert "detector \n" not in src  # readability guard on the wrapped literal
    joined = re.sub(r'"\s*\n\s*f?"', "", src)
    assert "detector gap, not evidence the link is private" in joined


def test_both_notebooklm_read_back_sites_were_changed():
    """There were two — the primary share path and the recovery loop. Fixing
    one and leaving the other is how a message half-disappears and the next
    reader concludes the fix did not work."""
    joined = re.sub(r'"\s*\n\s*f?"', "", module_src())
    assert joined.count("detector gap, not evidence the link is private") == 2


def test_the_read_back_notice_is_not_a_warning():
    """It fires on 100% of runs and asks nothing of anyone."""
    src = module_src()
    at = src.index("could not read the sharing state back")
    assert '"DEBUG"' in src[at:at + 400]
    assert '"WARN"' not in src[at:at + 400]


@pytest.mark.parametrize("real_failure", [
    "could not find the 'Notebook access' control",
    "no 'Anyone with the link' option to click",
    "access was NOT changed; the link may be private",
])
def test_notebooklms_genuine_access_failures_keep_their_warnings(real_failure):
    """⛔ These are different signals and they are NOT false positives: the
    control was missing, or found and never changed. Only the strict read-BACK
    of an access that was set went quiet."""
    src = module_src()
    assert real_failure in src
    at = src.index(real_failure)
    # These are long multi-field diagnostics, so a fixed window either truncates
    # the level off the end or runs into the NEXT log call. Bound it at the next
    # call instead: the level belongs to this one or to nothing.
    nxt = src.find("log(", at)
    call = src[at:nxt if nxt != -1 else at + 2000]
    assert '"WARN"' in call, f"{real_failure!r} must still warn"
