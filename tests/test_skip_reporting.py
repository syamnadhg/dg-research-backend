"""Skips must report as skips, and must say WHY.

Two owner-reported bugs, both about a skip that lied about itself.

#100 — "When notebooklm had a bug, it raised an alert and I skipped. Instead of
greyed-out skip, it got the completed status."

    The Phase-3 link-extract Skip branch was the ONLY skip branch in the whole
    pipeline that emitted no terminal event and set no flag. It blanked
    `notebook_url` and broke, which meant: the audio block was skipped (so
    `_p3_audio_user_skipped` stayed False), the no-audio auto-retry loop is
    `while notebook_url` so it never ran either, and the terminal gate therefore
    saw every skip flag False and emitted `phase_complete:3` with the summary
    "NotebookLM notebook created" — for a notebook whose link was never
    obtained. P4 was not cascaded off either, so FE-P4 was triggered for a
    podcast that does not exist.

#101 — "Claude skip might be a platform-facing issue and it had to skip. That's
common. Our fix needs to just mention the skip reason in the phase dropdown
better rather than a vague 'skipped'."

    The auto-skip exit sweep used ONE reason (`auto_skip_setup_failed`, copy
    "couldn't start") for every unresolved agent — including one that was
    verified running at roll-call, ran a live Deep Research for 41 minutes, and
    then failed on claude.ai's side. And the durable record was
    `{"status": "skipped", "completionTimeSec": 2841}` with no reason field at
    all, so after a reload there was nothing to render but the bare word.
"""
from __future__ import annotations

import inspect
import re

import research
from conftest import code_only


# ── #100: the Phase-3 link-extract skip ──────────────────────────────────────

def _pipeline_src() -> str:
    return inspect.getsource(research.run_pipeline)


def _link_extract_skip_branch() -> str:
    """The skip body inside the P3 link-extract loop.

    2026-08-02: the condition it used to anchor on was `decision in ("skip",
    "timeout")`, which could not tell the 30-minute countdown the FE showed
    from `await_phase_decision`'s 24-hour outer backstop — so a sign-in wall
    and an auto-skip-OFF card, which arm nothing, both auto-skipped after a
    weekend. The branch now takes three outcomes — a user Skip, an ARMED
    timeout, and the unarmed 24-hour backstop — each with its own reason and all
    three sharing this one skip-and-continue exit."""
    src = _pipeline_src()
    i = src.index('if decision == "skip" or _nb_auto or _nb_backstop:')
    # Ends on the cascade, not on `break`: this source is NOT comment-stripped
    # and the branch's own explanation contains the word "break".
    return src[i:src.index("_controls.skipped_phases.add(4)", i) + 40]


def test_the_link_extract_skip_emits_a_terminal_phase_skipped():
    branch = _link_extract_skip_branch()
    assert 'emit_event("phase_skipped"' in branch, (
        "a user Skip here emitted NOTHING, which is how it ended up reported as "
        "a completed phase"
    )
    assert "user_skip_at_link_extract" in branch, (
        "the reason must be specific to this branch — a generic reason cannot be "
        "turned into honest FE copy"
    )


def test_the_link_extract_skip_blanks_the_notebook_url():
    """Not cosmetic. `notebook_url` gates the audio sub-step (`if notebook_url:`)
    and the no-audio auto-retry loop (`while bool(notebook_url)`), so leaving the
    known-bad URL in place would run the whole audio phase — up to 3 auto-retries
    at 5-minute intervals — against a notebook the user just skipped."""
    branch = _link_extract_skip_branch()
    assert 'notebook_url = ""' in branch, (
        "the skipped URL must be cleared, or the audio phase runs against it"
    )
    src = code_only(_pipeline_src())
    i_blank = src.index('notebook_url = ""')
    i_audio = src.index("if notebook_url:", i_blank)
    assert i_blank < i_audio, "the blanking must precede the audio gate it feeds"


def test_the_link_extract_skip_cascades_phase_4_off():
    branch = _link_extract_skip_branch()
    assert "_controls.skipped_phases.add(4)" in branch, (
        "no notebook means no podcast means no YouTube — every other P3 skip "
        "path cascades P4 off and this one did not, so FE-P4 was triggered for "
        "a podcast that does not exist"
    )


def test_the_link_extract_skip_uses_a_flag_the_terminal_gate_reads():
    """The flag must be one that is NOT re-initialised between the skip and the
    gate. `_p3_audio_user_skipped` looks like the natural choice and is a trap:
    it is reset to False a few lines after this loop, which would silently undo
    the whole fix."""
    src = _pipeline_src()
    branch = _link_extract_skip_branch()
    assert "_p3_link_skipped = True" in branch
    assert "_p3_audio_user_skipped = True" not in branch, (
        "_p3_audio_user_skipped is re-initialised after the link-extract loop — "
        "setting it here would be a no-op by the time the gate reads it"
    )
    # Initialised BEFORE the loop, and re-initialised nowhere after it.
    init = src.index("_p3_link_skipped = False")
    skip = src.index("_p3_link_skipped = True")
    assert init < skip, "the flag must be initialised before the loop that sets it"
    assert src.count("_p3_link_skipped = False") == 1, (
        "exactly one initialisation — a second one after the loop would clobber it"
    )


def test_the_terminal_gate_will_not_emit_phase_complete_after_a_link_skip():
    """The lie itself: `phase_complete:3` with summary 'NotebookLM notebook
    created' for a run whose notebook link was never obtained.

    Asserts on the gate's CONDITION, comment-stripped. A presence check against
    raw source passes on the explanatory comment above the gate — verified by
    mutation: deleting the conjunct survived until this was tightened.
    """
    src = code_only(_pipeline_src())
    i = src.index('emit_event("phase_complete", phase=3')
    # The `if (...)` immediately preceding the emit, as a single normalised line.
    gate = " ".join(src[max(0, i - 600):i].split())
    for conjunct in ("not _p3_audio_user_skipped", "not _p3_login_skipped",
                     "not _p3_link_skipped", "not _controls.is_stop()"):
        assert conjunct in gate, (
            f"the phase_complete gate must include `{conjunct}` — without it a "
            "skip still reports the phase as completed (#100)"
        )


def test_every_skip_decision_branch_in_the_pipeline_emits_a_terminal_event():
    """The structural guard. #100 was not a category of bug — it was ONE branch
    out of fourteen that forgot, and it went unnoticed because the other thirteen
    were right. This walks every `== "skip"` branch and requires each to emit
    something terminal, so the next added branch cannot repeat it.
    """
    src = inspect.getsource(research)
    missing = []
    # Deliberately enumerated rather than `\w+ == "skip"`: the CLI login flow
    # has its own `mode == "skip"` meaning "skip the optional VERIFICATION step",
    # which is not a pipeline decision and has no terminal event to emit. The
    # names below are the pipeline's decision variables.
    for m in re.finditer(r'\n(\s*)if (?:decision|_decision|_sd\.decision|_interrupt|'
                         r'_pk_dec|gate_decision|_bs_decision|_p3_decision'
                         r') == "skip":\n', src):
        indent = len(m.group(1))
        # Body = following lines more-indented than the `if`.
        body_lines = []
        for line in src[m.end():].split("\n"):
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body_lines.append(line)
        body = "\n".join(body_lines)
        terminal = (
            'emit_event("phase_skipped"' in body
            or 'emit_event("agent_skipped"' in body
            or 'emit_event("pipeline_stopped"' in body
            or "request_skip_agent" in body          # re-arms the marker path
            or "_finalize_agent_autoskip" in body
        )
        if not terminal:
            missing.append(src[:m.start()].count("\n") + 2)
    assert not missing, (
        "these `== \"skip\"` branches emit no terminal event, so the phase can "
        f"still report itself complete afterwards (source lines: {missing})"
    )


def test_the_primary_share_path_accepts_a_shape_ok_link_like_its_fallback_does():
    """The second blocker from the post-mortem: the share-link extractor had a
    0/44 all-time success rate.

    Not because extraction failed — because the CALLER discarded it. The primary
    gate required `nlm_share_res.verified`, which needs a DOM-confirmed "Anyone
    with the link", and `Public share DOM-verified` has NEVER once logged in the
    corpus. So the extracted link was thrown away on 100% of runs and the tab URL
    was a silent crutch on every "successful" Phase 3 — which is how a hostname
    rename turned into a total outage: when the affordance changed, the crutch
    was all there was.

    The recovery loop already accepted shape-only. This pins that the primary
    path is no longer STRICTER than its own fallback. Structural (the enclosing
    coroutine cannot be driven in a unit test) but comment-stripped and pinned to
    the condition, not to the presence of a name.
    """
    src = code_only(inspect.getsource(research.run_phase3_upload))
    i = src.index("nlm_share_res = await extract_notebooklm_url")
    # Wide window: the blanked comment between the call and the gate is ~900
    # bytes of whitespace after stripping.
    gate = " ".join(src[i:i + 2000].split())
    assert "if is_notebooklm_url(nlm_share_res.url):" in gate, (
        "the primary share path must accept a shape-OK notebook URL"
    )
    assert "nlm_share_res.verified and" not in gate, (
        "requiring DOM-verified public access here discarded the extracted link "
        "on every run in the corpus — `verified` stays an honest SIGNAL (logged), "
        "not a gate"
    )


# ── #101: the skip reason ────────────────────────────────────────────────────

def test_a_mid_run_platform_failure_is_not_reported_as_a_startup_failure():
    """The Claude case. `agent_error` is written when an agent that WAS verified
    running has its research fail on the platform's side. Reporting that as
    "couldn't start" points the user at their own login when nothing there was
    wrong."""
    reason, copy_key, why = research.autoskip_reason_for_status("agent_error")
    assert reason == "auto_skip_agent_error"
    assert copy_key == "mid_run_failed"
    assert "couldn't start" not in why
    details = research._autoskip_details(copy_key, "Claude")
    assert "started fine" in details
    assert "platform" in details
    assert "couldn't start" not in details


def test_a_genuine_startup_failure_still_reports_as_one():
    for st in ("failed_setup", "not_verified"):
        reason, copy_key, why = research.autoskip_reason_for_status(st)
        assert reason == "auto_skip_setup_failed", st
        assert copy_key == "setup_failed", st
        assert why == "couldn't start", st


def test_an_exhausted_hard_retry_reports_as_one():
    for st in ("hard_retry_failed", "hard_retry_exhausted_dead_tab"):
        reason, copy_key, _ = research.autoskip_reason_for_status(st)
        assert reason == "auto_skip_hard_retry_exhausted", st
        assert copy_key == "hard_retry_exhausted", st
        assert "retried" in research._autoskip_details(copy_key, "Gemini")


def test_an_unknown_status_defaults_to_setup_failed_not_to_a_claim_it_ran():
    """"We don't know" is closer to a setup problem than to asserting the
    research ran and died — the latter would be a fabricated story.

    ⛔ 2026-08-22 — `empty` and `browser_crashed` WERE IN THIS LIST and should
    never have been: they are not unknowns. Both are written only while iterating
    `pending`, which is seeded solely for agents whose page survived setup, so
    startup succeeding is a PRECONDITION for either of them existing. This test
    was pinning the defect — the same "couldn't start" lie the 2026-07-31 split
    was written to end, in statuses that split did not enumerate. They moved to
    the sibling below; the genuine unknowns stay here."""
    for st in ("", None, "something_new"):
        reason, copy_key, _ = research.autoskip_reason_for_status(st)
        assert reason == "auto_skip_setup_failed", st
        assert copy_key == "setup_failed", st


def test_a_lost_tab_is_not_reported_as_a_startup_failure():
    """The statuses that require a LIVE page to have existed.

    A tab that drifted into a conversation predating the run and an extraction
    that came back empty both describe an agent that started fine. Telling that
    user their agent "couldn't start" points them at their own login and setup
    when nothing there was wrong — and the reason slug reaches the FE verbatim,
    so a wrong one here is a wrong story in the phase dropdown and in the
    durable record.

    ⚠ `browser_crashed` USED TO BE IN THIS LIST and moved out on 2026-08-27 —
    see the test below. It is still not a startup failure; it now gets a
    sentence that says where it failed instead of one that says we mislaid it."""
    for st in ("wrong_conversation", "empty", "WRONG_CONVERSATION"):
        reason, copy_key, why = research.autoskip_reason_for_status(st)
        assert reason == "auto_skip_tab_lost", st
        assert copy_key == "tab_lost", st
        assert "couldn't start" not in why, st
        text = research._autoskip_details(copy_key, "Claude", why)
        assert "couldn't start" not in text, st
        assert "started and ran" in text, st
        # A crashed tab raises no decision card, so the neighbours' "and its
        # Retry/Skip alert wasn't answered" clause would be a second false claim.
        assert "wasn't answered" not in text, st


def test_a_crashed_page_is_reported_as_the_platforms_failure():
    """⛔⛔ MEASURED FROM A REAL RUN, 2026-08-27. Gemini sat on "Writing your
    report…" for forty-seven minutes with zero growth — 133 sites researched, 37
    steps, not one character of report — our own arbiter twice ruled "WORKING,
    not a frozen state" off the visible source list, and then the page died. The
    user was told "we lost the tab we were reading it through", which names OUR
    end of a failure that began on theirs and reads as though our pipeline
    dropped their research.

    ▶ Owner's standing rule: when the platform stalls or hands us something new,
    SAY PLATFORM-SIDE. Extraction is good in ordinary circumstances, and blaming
    ourselves for their stall teaches the user to distrust the part that works.
    """
    for st in ("browser_crashed", "BROWSER_CRASHED"):
        reason, copy_key, why = research.autoskip_reason_for_status(st)
        assert reason == "auto_skip_platform_crashed", st
        assert copy_key == "platform_crashed", st
        # Still not a startup failure — that half of the 2026-07-31 split holds.
        assert "couldn't start" not in why, st

        text = research._autoskip_details(copy_key, "Gemini", why)
        assert "couldn't start" not in text, st
        # No decision card is raised for a crash, so this clause would be a
        # second false claim on top of the first.
        assert "wasn't answered" not in text, st
        # ⛔ THE POINT OF THE CHANGE: it must not describe the failure as ours.
        assert "we lost the tab" not in text.lower(), st
        assert "browser tab was lost" not in text.lower(), st
        # ⭐ And it must name WHERE it failed, in the platform's own words.
        assert "Gemini's own page" in text, st
        assert "stopped responding" in text, st
        # The agent is still named as having been genuinely running, which is
        # the half of the old sentence that was true.
        assert "research was running" in text, st


def test_the_crash_copy_names_the_agent_it_was_given():
    """A sentence that hard-codes one platform is a sentence that lies about the
    other two — and this copy names the platform twice, so a single missed
    substitution is easy to ship."""
    for name in ("Gemini", "ChatGPT", "Claude"):
        _r, copy_key, why = research.autoskip_reason_for_status("browser_crashed")
        text = research._autoskip_details(copy_key, name, why)
        assert text.count(name) >= 2, (name, text)
        for other in {"Gemini", "ChatGPT", "Claude"} - {name}:
            assert other not in text, (name, other, text)


def test_the_startup_statuses_still_say_startup():
    """The other half of the split: moving three statuses out must not take the
    genuine startup failures with them."""
    for st in ("failed_setup", "not_verified"):
        reason, copy_key, why = research.autoskip_reason_for_status(st)
        assert reason == "auto_skip_setup_failed", st
        assert why == "couldn't start", st


def test_status_is_matched_case_insensitively():
    """`results[...]["status"]` is written by many sites; a casing difference
    must not silently reroute an agent_error into the setup-failed default."""
    assert research.autoskip_reason_for_status("AGENT_ERROR")[0] == "auto_skip_agent_error"


def test_every_copy_key_the_classifier_can_return_has_copy():
    """_autoskip_details raises KeyError on an unknown copy_key, and it runs
    inside the finalize path — a classifier that returned a key with no copy
    would crash the auto-skip instead of greying the tile."""
    for st in ("agent_error", "hard_retry_failed", "hard_retry_exhausted_dead_tab",
               "failed_setup", "not_verified", "whatever"):
        _, copy_key, why = research.autoskip_reason_for_status(st)
        text = research._autoskip_details(copy_key, "Claude", why)
        assert text and "Claude" in text


def test_the_skip_event_carries_the_human_sentence_not_just_the_slug():
    """The FE had no material to render beyond the slug, and any slug its map did
    not know collapsed to the word "Skipped". Sending the sentence the finalizer
    already composed for the notice banner means a NEW backend skip path explains
    itself with no FE release."""
    src = inspect.getsource(research._finalize_agent_autoskip)
    assert "_detail = _autoskip_details(" in src
    i = src.index('emit_event("agent_skipped"')
    assert "detail=_detail" in src[i:i + 260], (
        "agent_skipped must carry the composed explanation"
    )
    # And the notice must reuse the SAME string — two sources would drift.
    j = src.index('emit_event("pipeline_warning"')
    assert "details=_detail" in src[j:j + 260]


def test_the_durable_record_persists_reason_and_detail():
    """`meta.json`/root-doc held `{"status": "skipped", "completionTimeSec": …}`
    — status and a stopwatch. After a reload there was nothing to explain the
    skip with, which is the half of #101 that no amount of FE work could fix."""
    src = inspect.getsource(research._do_agent_terminal_status_write)
    assert '"statusReason"' in src and '"statusDetail"' in src
    # Only written when supplied, so existing callers' payloads keep their shape.
    assert "if reason:" in src and "if detail:" in src

    sig = inspect.signature(research._write_agent_terminal_status)
    assert "reason" in sig.parameters and "detail" in sig.parameters
    assert sig.parameters["reason"].default == ""
    assert sig.parameters["detail"].default == ""


def test_the_emit_hook_forwards_reason_and_detail_to_the_durable_write():
    src = inspect.getsource(research.emit_event)
    i = src.index('elif event_type == "agent_skipped" and agent:')
    block = src[i:i + 1600]
    assert "_write_agent_terminal_status(" in block
    assert 'data.get("reason")' in block
    assert 'data.get("detail")' in block, (
        "the persisted record must get the sentence, not only the slug"
    )


# ── Executed coverage for the durable write (adversarial review) ─────────────
#
# The first draft tested this with source-presence assertions only, which means a
# CHANNEL SWAP — writing `statusReason = detail` and `statusDetail = reason` —
# survived every one of them. That is the same class of escape as the equal-value
# fixture the share tests already had to fix: presence proves the names appear,
# not that the values go to the right place.

def test_the_durable_write_puts_each_value_in_the_right_field(monkeypatch):
    seen = {}

    def _fake_set(uid, rid, payload, merge=False):
        seen["payload"] = payload
        seen["merge"] = merge

    monkeypatch.setattr(research, "_set_research_doc", _fake_set)
    monkeypatch.setattr(research, "_firebase_db", object(), raising=False)
    monkeypatch.setattr(research, "_fb_uid", "uid-1", raising=False)
    monkeypatch.setattr(research, "_fb_research_id", "rid-1", raising=False)

    research._do_agent_terminal_status_write(
        "Claude", "skipped",
        reason="auto_skip_agent_error",
        detail="Claude started fine but its research failed on the platform's side")

    agents = seen["payload"]["agents"]
    assert set(agents) == {"claude"}, "the agent key must be lower-cased"
    entry = agents["claude"]
    assert entry["status"] == "skipped"
    assert entry["statusReason"] == "auto_skip_agent_error", (
        "the machine SLUG belongs in statusReason — a swap here would put a "
        "sentence where the FE expects a slug and vice versa"
    )
    assert entry["statusDetail"].startswith("Claude started fine"), (
        "the human SENTENCE belongs in statusDetail"
    )
    assert seen["merge"] is True, "must merge — a replace would clobber siblings"


def test_the_durable_write_omits_the_new_fields_when_not_supplied(monkeypatch):
    """Existing callers pass neither, and their payload shape must not change —
    writing empty strings would overwrite a real reason from an earlier event."""
    seen = {}
    monkeypatch.setattr(research, "_set_research_doc",
                        lambda u, r, payload, merge=False: seen.update(payload=payload))
    monkeypatch.setattr(research, "_firebase_db", object(), raising=False)
    monkeypatch.setattr(research, "_fb_uid", "uid-1", raising=False)
    monkeypatch.setattr(research, "_fb_research_id", "rid-1", raising=False)

    research._do_agent_terminal_status_write("gemini", "complete")
    assert seen["payload"]["agents"]["gemini"] == {"status": "complete"}


# ── link_extraction_failed actually gets emitted ─────────────────────────────

def test_extract_with_retry_emits_the_terminal_failure_event(monkeypatch):
    """The docstring had promised this event for as long as the function existed
    and never emitted it, so the FE's step list simply stopped mid-extraction and
    the tile kept its pre-extraction copy — the run looked FROZEN rather than
    failed, which is the symptom that was reported."""
    events = []
    monkeypatch.setattr(research, "emit_event",
                        lambda name, **kw: events.append((name, kw)))

    async def _always_fails(browser, cua_client=None, **kw):
        return research.LinkResult(url="", label="NotebookLM Notebook",
                                   platform="notebooklm", verified=False,
                                   error="nothing on any channel")

    import asyncio as _a
    _orig = _a.sleep

    async def _no_sleep(_s, *a, **k):
        return None

    _a.sleep = _no_sleep
    try:
        res = _a.run(research.extract_with_retry(
            phase=3, agent="notebooklm", browser=object(), cua_client=None,
            extractor_fn=_always_fails, max_retries=3, retry_delay=0))
    finally:
        _a.sleep = _orig

    assert res.verified is False
    names = [n for n, _ in events]
    assert "link_extraction_failed" in names, (
        "the terminal event must fire so the FE knows the step FAILED rather "
        "than just going quiet"
    )
    failed = dict(events[names.index("link_extraction_failed")][1])
    assert failed["phase"] == 3 and failed["agent"] == "notebooklm"
    assert failed["error"] == "nothing on any channel"
    assert "NotebookLM" in failed["description"], (
        "readable copy — the FE step row renders `description` and fell back to "
        "the raw event NAME without it"
    )
    # Informational only: `actions` is never set, so this cannot become a second
    # card competing with the caller's fail_phase decision.
    assert "actions" not in failed


def test_extract_with_retry_narrates_every_attempt_to_the_phase_tile(monkeypatch):
    """Link extraction is a multi-minute step that emitted nothing the phase tile
    reads, so a failing Phase 3 sat on its pre-extraction copy for ~4 minutes and
    then went silent ("stuck at copy notebook, never goes to the podcast")."""
    events = []
    monkeypatch.setattr(research, "emit_event",
                        lambda name, **kw: events.append((name, kw)))

    async def _always_fails(browser, cua_client=None, **kw):
        return research.LinkResult(url="", platform="notebooklm", verified=False,
                                   error="no link")

    import asyncio as _a
    _orig = _a.sleep

    async def _no_sleep(_s, *a, **k):
        return None

    _a.sleep = _no_sleep
    try:
        _a.run(research.extract_with_retry(
            phase=3, agent="notebooklm", browser=object(), cua_client=None,
            extractor_fn=_always_fails, max_retries=3, retry_delay=0))
    finally:
        _a.sleep = _orig

    progress = [kw for n, kw in events if n == "agent_progress"]
    assert len(progress) == 3, "one progress emit per attempt"
    for kw in progress:
        assert kw["phase"] == 3 and kw["agent"] == "notebooklm"
        assert kw["progress"] and "NotebookLM" in kw["progress"]
    # Attempts 2 and 3 must say which attempt they are — an identical line three
    # times reads as a frozen tile, which is the bug.
    assert progress[1]["progress"] != progress[0]["progress"]
    assert "2 of 3" in progress[1]["progress"]
    # Every link_extracting / link_extract_retry carries readable copy too.
    for name in ("link_extracting", "link_extract_retry"):
        for n, kw in events:
            if n == name:
                assert kw.get("description"), f"{name} must carry `description`"


# ── The sibling double-terminal bug (adversarial review) ─────────────────────

def test_the_upload_timeout_skip_does_not_also_emit_phase_complete():
    """Found reviewing the #100 fix. A Skip on the P3 UPLOAD-timeout card DOES
    emit phase_skipped:3, so it passed the structural "emits a terminal event"
    guard — but `_p3a_user_skipped` was missing from the terminal gate, so the
    phase then ALSO emitted phase_complete:3. A double terminal event: the tile
    flips greyed-skipped back to green and the durable phase status is overwritten
    skipped->complete.

    "Emits a terminal event" and "emits EXACTLY ONE terminal event" are different
    guarantees, and only the second is what the user sees.
    """
    src = code_only(_pipeline_src())
    i = src.index('emit_event("phase_complete", phase=3')
    gate = " ".join(src[max(0, i - 900):i].split())
    assert "not _p3a_user_skipped" in gate, (
        "the upload-timeout skip flag must gate phase_complete:3 too"
    )


def test_every_p3_skip_flag_that_ends_the_phase_is_in_the_terminal_gate():
    """Structural guard over the whole family, so the next flag added to this
    block cannot repeat either #100 or its sibling.

    SCOPED to flags assigned `True` INSIDE the Phase-3 execution block — from
    `_p3a_user_skipped = False` down to the phase_complete emit. That scope is
    the point: flags outside it (the pre-gate `_p3_already_skipped` config
    predicate, which is only a loop guard) short-circuit on a completely
    different path that never reaches this gate, so requiring them here would
    fail on correct code. Anything set inside the block, though, describes a
    skip of the run that IS about to reach the gate.
    """
    src = code_only(_pipeline_src())
    i_gate = src.index('emit_event("phase_complete", phase=3')
    i_block = src.index("_p3a_user_skipped = False")
    assert i_block < i_gate
    block = src[i_block:i_gate]
    gate = " ".join(src[max(0, i_gate - 900):i_gate].split())
    flags = set(re.findall(r"\b(_p3[a-z0-9_]*skipped)\s*=\s*True\b", block))
    assert flags, "expected to find the P3 skip flags set inside the block"
    missing = sorted(f for f in flags if f not in gate)
    assert not missing, (
        f"these P3 skip flags do not gate phase_complete:3, so a skip they "
        f"represent still reports the phase as completed: {missing}"
    )
