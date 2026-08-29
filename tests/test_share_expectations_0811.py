"""NotebookLM warned on every run that a public notebook "may be private".

The pipeline warned that a notebook's "public access [was] NOT DOM-verified —
the link may be private". The owner reports these notebooks come out public
every time, and the comment above the check records that `verified` has NEVER
once been true in the whole corpus. So the message was wrong on 100% of runs.
What actually broke is the read-BACK: the control that used to expose "Anyone
with the link" no longer matches. The share step itself ran, and its genuine
failures have their own separate warnings, which are untouched.

WHAT THESE TESTS PIN

  1. NotebookLM's read-back failure says what failed (the detector) instead of
     what did not (the sharing).
  2. Both read-back sites were changed, not one.
  3. NotebookLM's REAL access failures keep their warnings.

⛔ EIGHT TESTS LEFT THIS FILE ON 2026-08-28 (stretch 6.6B). They were the
ChatGPT half of the same 2026-08-11 finding: that a missing public share should
warn for Gemini and Claude and stay quiet for ChatGPT, held in one
`_PUBLIC_SHARE_EXPECTED` table so the predicate could not drift. That whole
expectation is gone with the P2 platform share step — there is no share to
expect, for any agent — so the tests are not stale, their subject was deleted.
The NotebookLM half below is untouched and is why the file survives.
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
