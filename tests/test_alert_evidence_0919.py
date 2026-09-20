"""The alert must say what actually went wrong, using what the model already saw.

⛔⛔ THE INCIDENT, 2026-09-19. Claude stopped mid-run because the ACCOUNT hit its
usage limit. The vision model looked at the tab, read the banner — "Usage limit
reached · Resets Sep 20 at 1:00 AM" — and wrote it down. The user's alert said:

    Hit a snag at the research step with Claude — retrying.

Every word of that is either uninformative or false: nothing was retrying (the
agent was parked awaiting Retry/Skip), and the one sentence that explained the
whole thing had been collected and thrown away. The owner's ask was direct — "I
must say claude rate limited" — and, importantly, that the alert be determined
from what was seen rather than hardcoded, with CUA and vision working from the
same facts.

⭐ THE EVIDENCE WAS ALREADY BEING ASKED FOR. `_CUA_CONTRACT_BLOCK` has demanded
`EVIDENCE: <one short line naming what you actually saw>` since it was written,
and NOTHING in the repo has ever parsed it. `_cua_completion_report` returned
only {verdict, stop_seen, source}. This was not a missing capability; it was a
channel nobody had connected.

THREE DISCARD POINTS, all closed here:
  1. `_cua_error_evidence` — the contract's EVIDENCE line now has a reader.
  2. `poll_all_agents_round_robin` — `diag_text_raw` used to have exactly one
     consumer, the `.lower()` on the next line. It was not even logged.
  3. `fail_agent` → `facts["raw_err"]` — the key `_draft_alert_copy` reads its
     evidence from, which no caller in the repo had ever written.

⛔ AND ONE ASYMMETRY THAT IS NOT A PREFERENCE. The web classes a title carrying
"overloaded", "529" or a spelling of "rate limit" as transient infrastructure
and renders it as a passive banner with NO Retry and NO Skip. Quoting an
overload banner into a title would make the card honest and take away the two
controls the user needs. The body is not filtered, so evidence always goes
there; only the headline falls back.
"""
import pytest

import research
from conftest import code_only


def _capture_emit_event(monkeypatch):
    """Stub only the I/O seam, so the REAL emit_decision runs end to end."""
    calls = []
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(research, "_persist_pending_decision", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    return calls


LIMIT = "Usage limit reached · Resets Sep 20 at 1:00 AM"

#: The reply as the model actually writes it under the contract.
DIAG_LIMIT = (
    "I looked at the Claude tab. The composer is disabled and there is no Stop "
    "button; a banner across the top reads 'Usage limit reached · Resets Sep 20 "
    "at 1:00 AM'.\n"
    f"EVIDENCE: {LIMIT}\n"
    "CONCLUSION: ERROR"
)


# ── 1. the reader the contract never had ──────────────────────────────────

def test_the_evidence_line_is_read():
    """⛔ The headline case. Today `_cua_error_evidence` does not exist at all —
    `EVIDENCE:` appears in the contract string and in no reader."""
    assert research._cua_error_evidence(DIAG_LIMIT) == LIMIT


def test_a_model_that_ignored_the_format_still_gets_read():
    """The fallback rung: the last real line. A model that skipped the contract
    usually still ends with its observation, and "no EVIDENCE line" must not
    mean "no evidence"."""
    got = research._cua_error_evidence(
        "The tab shows a red banner: Claude is unavailable in your region.\n"
        "CONCLUSION: ERROR")
    assert "unavailable in your region" in got


def test_the_contracts_own_field_lines_are_never_mistaken_for_prose():
    """⛔ Without this the fallback hands back "CONCLUSION: ERROR" as the
    user-facing explanation — a machine token shown to a person."""
    assert research._cua_error_evidence(
        "VERDICT: unknown\nSTOP_BUTTON: no\nCONCLUSION: ERROR") == ""


def test_the_placeholder_echoed_back_is_not_evidence():
    """A model that copies the contract line verbatim has told us nothing, and
    "<one short line naming what you actually saw>" in an alert would be worse
    than the generic sentence."""
    assert research._cua_error_evidence(
        "EVIDENCE: <one short line naming what you actually saw>\n"
        "CONCLUSION: ERROR") == ""


def test_the_last_evidence_line_wins():
    """Same rule as `_last_verdict`, for the same reason: a reply that quotes
    its own instructions names the field before it answers it."""
    assert research._cua_error_evidence(
        "I should end with EVIDENCE: something\n"
        "EVIDENCE: The tab shows a network error\n"
        "CONCLUSION: ERROR") == "The tab shows a network error"


@pytest.mark.parametrize("junk", ["", None, "\n\n\n", 12, object()])
def test_the_reader_is_total(junk):
    """It runs on the failure path. A throw here replaces a bad alert with no
    alert."""
    assert isinstance(research._cua_error_evidence(junk), str)


def test_evidence_is_flattened_and_capped():
    out = research._cua_error_evidence("EVIDENCE: a   b\tc\n" + "CONCLUSION: ERROR")
    assert out == "a b c"
    long = research._cua_error_evidence("EVIDENCE: " + ("x" * 900) + "\nCONCLUSION: ERROR")
    assert len(long) <= 200


def test_the_completion_report_carries_evidence_too():
    """⭐ The fourth key. Existing callers index by name, so it is inert for
    them — but the channel is now readable from BOTH verdict surfaces rather
    than only the diagnose loop."""
    rep = research._cua_completion_report(
        "VERDICT: complete\nSTOP_BUTTON: no\nEVIDENCE: A share button is rendered.")
    assert rep["evidence"] == "A share button is rendered."
    assert rep["verdict"] == "complete" and rep["stop_seen"] is False


# ── 2. the title/body asymmetry the frontend forces ───────────────────────

def test_a_quiet_infra_word_may_not_go_in_a_title():
    """⛔⛔ `isQuietInfraCard` in the web classes such a title as transient
    infrastructure and strips Retry and Skip from the card. Faithfully quoting
    an overload banner into the headline would make the alert honest and
    simultaneously remove the two controls the user needs."""
    for bad in ("Anthropic is overloaded (529)", "rate-limit hit", "RATE_LIMIT"):
        assert research._alert_title_safe(bad) is False, bad


def test_an_ordinary_banner_may():
    assert research._alert_title_safe(LIMIT) is True


def test_empty_evidence_is_not_a_title():
    assert research._alert_title_safe("") is False
    assert research._alert_title_safe(None) is False


def test_the_quiet_word_list_matches_the_webs():
    """⚠ The list is duplicated across two repos that ship separately. This is
    the backend half of the pin; `pipelineErrors.test.ts` holds the other."""
    assert set(research._ALERT_QUIET_INFRA_WORDS) >= {
        "rate-limit", "rate_limit", "overloaded", "529"}


# ── 3. the card actually carries it ───────────────────────────────────────

def test_the_card_body_names_what_was_seen(monkeypatch):
    """⛔ Today `fail_agent` has no `raw_err` parameter — TypeError. And a
    half-fix that only puts the evidence into `facts` stays red: `emit_decision`
    builds its event payload from title/details/actions and never forwards
    `facts`, so the only route to the user is through `details`."""
    calls = _capture_emit_event(monkeypatch)
    research.fail_agent("claude", f"Claude stopped: {LIMIT}",
                        f"Claude showed: {LIMIT} — we kept what little it "
                        "produced. Retry to run it fresh, or Skip it.",
                        raw_err=DIAG_LIMIT)
    errs = [kw for (a, kw) in calls if a and a[0] == "pipeline_error"]
    assert errs, [a for (a, _k) in calls]
    body = " ".join(str(v) for v in errs[-1].values())
    assert "Usage limit reached" in body


def test_the_facts_dict_is_the_shared_one(monkeypatch):
    """⛔⛔ THE OWNER'S ASK, PINNED: "all facts must be consistent for CUA and
    vision both". `facts` is the one dict an alert is built from, and its
    evidence slot — the key `_draft_alert_copy` reads at its line 24477 — was
    dead: no caller in the repo had ever written it, so the drafter fell back
    to `details`, the same constant sentence the template already showed.

    CUA and Vision reach this through the SAME string: `_shadow_observed_cua`
    puts a vision `ActionResult.reason` into the same `text` key a CUA reply
    lands in, so one channel feeds both."""
    seen = {}
    monkeypatch.setattr(research, "emit_decision",
                        lambda **kw: seen.update(kw) or "dec_1")
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    research.fail_agent("claude", "Claude stopped: x", "body", raw_err=DIAG_LIMIT)
    assert seen["facts"]["raw_err"] == DIAG_LIMIT


def test_raw_err_defaults_so_every_existing_caller_is_byte_identical(monkeypatch):
    """32 call sites. A defaulted kwarg leaves all of them alone, and `facts`
    gains an empty slot rather than a missing key — `_draft_alert_copy` reads it
    with `.get`, but a KeyError on the failure path would be a fine way to turn
    a bad alert into no alert."""
    seen = {}
    monkeypatch.setattr(research, "emit_decision",
                        lambda **kw: seen.update(kw) or "dec_1")
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    research.fail_agent("claude", "Claude reported an error", "body")
    assert seen["facts"]["raw_err"] == ""
    assert seen["facts"]["title"] == "Claude reported an error"


# ── 4. the round-robin is wired to it ─────────────────────────────────────

def _error_branch() -> str:
    """The whole `CONCLUSION: ERROR` branch, anchor-delimited — the same helper
    shape `test_card_lifetime.py` uses, and for the reason written there."""
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("if is_error:")
    return src[i:src.index("if is_generating and not is_done:", i)]


def test_the_error_branch_reads_the_evidence_and_passes_it_on():
    """⛔ Position, not behaviour — paired with the tests above, which is what
    makes it worth having. `code_only` blanks comments in place, so the long
    explanation beside this code cannot green it.

    Today `diag_text_raw` exists only at its two lines far ABOVE this branch,
    and the `fail_agent` call inside it passes three constants."""
    branch = _error_branch()
    assert "_cua_error_evidence(" in branch
    assert "raw_err=" in branch
    assert "_alert_title_safe(" in branch


def test_the_error_log_line_quotes_what_was_seen():
    """The log said "CUA reported CONCLUSION: ERROR" and nothing else, which is
    why the incident had to be diagnosed from a screenshot rather than from the
    support bundle that was collected for exactly this."""
    assert "_evidence" in _error_branch().split("Salvaging partial output")[0]


def test_the_diagnose_prompt_asks_for_the_line_it_is_parsed_for():
    """⛔ A reader for a line the prompt never requests is a reader that fires
    on a fallback forever. `PROMPT_DIAGNOSE` — the prompt the round-robin
    actually sends — had no EVIDENCE line, unlike `_CUA_CONTRACT_BLOCK`."""
    import prompts
    assert "EVIDENCE:" in prompts.PROMPT_DIAGNOSE
    # And the CONCLUSION line must still be LAST: `_last_verdict` is
    # line-anchored and the prompt says that line is parsed programmatically.
    body = prompts.PROMPT_DIAGNOSE
    assert body.index("EVIDENCE:") < body.rindex("CONCLUSION: ERROR")
