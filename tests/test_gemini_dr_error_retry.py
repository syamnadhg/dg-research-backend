"""Phase-2 Gemini Deep-Research error recovery.

Root-caused 2026-06-29 from three concurrent runs whose Gemini DR all errored
("Sorry, something went wrong. Please try your request again." /
"I encountered an error doing what you asked. Could you try again?"). The brief DID
enter the conversation, but an errored DR leaves the URL bare /app, so the [2C]
submit-confirmation (which watches for /app/<id>) re-submitted once then FAILED FAST,
skipping [2D] and silently dropping Gemini (no gemini.md, run still "done").

Fix invariants this guards:
  1. The in-page Retry/Regenerate detector recognises the failure text for BOTH
     Gemini error variants, and matches the regenerate control via title= too
     (icon-only buttons), not just aria-label/text.
  2. The [2C] confirmation loops (click Retry on an error, else re-submit) in a
     bounded retry instead of re-submitting once + failing fast.
  3. Persistent failure surfaces a real Retry/Skip blocker (fail_agent) — never a
     silent skip / false "done".
"""
import inspect
import re

import research

MODSRC = inspect.getsource(research)
RETRYSRC = inspect.getsource(research._try_inpage_retry_on_research_fail)


def _fail_regex():
    """Reconstruct the failure-text regex from the source (it lives as a local
    `fail_re = ( r"..." r"..." )` block, double-escaped to survive the Python-raw ->
    JS-template-literal hop) so we can assert its real matching behaviour."""
    collecting, parts = False, []
    for ln in RETRYSRC.splitlines():
        if "fail_re" in ln and "=" in ln and "(" in ln:
            collecting = True
            continue
        if collecting:
            m = re.findall(r'r"([^"]*)"', ln)
            if m:
                parts.extend(m)
            else:
                break  # the closing ")" line
    assert parts, "could not extract fail_re from _try_inpage_retry_on_research_fail"
    return re.compile("".join(parts).replace("\\\\", "\\"), re.IGNORECASE)


def test_fail_regex_matches_both_gemini_dr_errors():
    rx = _fail_regex()
    assert rx.search("Sorry, something went wrong. Please try your request again.")
    assert rx.search("I encountered an error doing what you asked. Could you try again?")


def test_fail_regex_ignores_healthy_text():
    rx = _fail_regex()
    assert not rx.search("Researching your topic — this may take a few minutes.")
    assert not rx.search("Here is your research plan. Start research?")


def test_retry_detector_checks_title_attribute():
    # icon-only regenerate buttons may carry their label in title=, not aria-label
    assert "getAttribute('title')" in RETRYSRC
    assert "retryWords.test(title)" in RETRYSRC


def test_2c_confirmation_has_bounded_retry_loop():
    assert "for _att in range(1, _max_attempts" in MODSRC, (
        "Gemini [2C] confirmation must retry in a bounded loop, not re-submit once"
    )
    assert "_try_inpage_retry_on_research_fail(" in MODSRC


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
