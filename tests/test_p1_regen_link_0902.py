"""STRETCH 7.5 STEP 2 (backend half) — the one emit that shipped a private address.

⛔⛔ WHAT WAS HAPPENING. After a pause on phase 1 where the user typed extra
context, the brief is regenerated — and that branch alone emitted
`current_url()` of the ChatGPT tab as a `phase_complete` link labelled
"ChatGPT Brief", with no `primary` and no `verified`. Its three sibling
branches all emit the brief's in-app page. The app STORES every link a phase
reports, so it outlived the run: a row in the agent drill-down, a line in the
follow-up chat's context (which is sent to a model), and a candidate for the
public video description.

⛔ The comment ~55 lines above it said the conversation URL "isn't streamed as a
separate link_extracted" — true of `link_extracted`, and false of the event
this branch actually used. A correct sentence about the wrong channel.

⚠ HONEST LIMIT. This branch lives inside `run_pipeline`, which no test in this
repo can drive, so these are SOURCE guards over that function — read with
`code_only`, because the fix comment quotes the very strings the assertions look
for and a presence check cannot tell code from prose. The behavioural proof that
a link of this shape can no longer reach a user is on the frontend, in
tests/unit/privateChatLinks.test.ts, which drives the filters and the video
description directly.

Run:  pytest tests/test_p1_regen_link_0902.py -v
"""
import inspect
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

REPO = Path(__file__).resolve().parents[1]


def _pipeline_src() -> str:
    return code_only(inspect.getsource(research.run_pipeline))


def _regen_branch(src: "str | None" = None) -> str:
    """The resume-with-added-input regen block.

    ⛔ ANCHORED ON THE EMIT, NOT ON A BYTE COUNT, and the first draft of this
    file got it wrong: `code_only` blanks comments IN PLACE to keep offsets
    intact, so a fixed-size window is eaten by however long the explanatory
    comment happens to be. A window that stops short of the thing it is meant
    to read fails for a reason that has nothing to do with the code.
    """
    src = _pipeline_src() if src is None else src
    at = src.index('emit_event("phase_restart", phase=1, reason="user_input_on_resume"')
    emit = src.index('emit_event("phase_complete", phase=1,', at)
    return src[at:emit + 500]


def test_the_regen_emits_the_in_app_brief_page_not_the_conversation():
    block = _regen_branch()
    assert '"url": _regen_in_app_url' in block
    # ⛔⛔ 2026-09-02, step 5 — THIS USED TO PIN THE EXPRESSION, AND THAT IS WHY
    # IT WENT RED FOR A NON-REASON. It asserted the f-string literally; step 5
    # lifted the identical expression out of four branches into
    # `in_app_document_url`, the answer did not change by one character, and the
    # guard failed anyway. A source pin on a SPELLING breaks on a refactor and
    # survives a change of meaning — exactly backwards. The value is now pinned
    # by executing the helper (below); this line only pins that the branch asks
    # the shared question instead of re-deriving it.
    assert '_regen_in_app_url = in_app_document_url("brief")' in block


def test_the_regen_no_longer_passes_the_conversation_url_to_the_app():
    # ⛔ `brief_url` at this point is `p1_new["url"]` — `current_url()` of the
    # ChatGPT tab. It may still be assigned (the checkpoint reads it); it may
    # not be handed to the app.
    block = _regen_branch()
    assert '"url": brief_url' not in block
    assert '{"label": "ChatGPT Brief"' not in block


def test_the_label_is_the_load_bearing_one():
    # #746: the FE's reopen-hydration backfill synthesizes "Read Brief report"
    # for the same URL. A different label here and the (label, url) dedup cannot
    # collapse the pair, so a phone or cold reopen renders the brief TWICE.
    assert '"label": "Read Brief report"' in _regen_branch()


def test_the_regen_link_is_marked_primary_and_verified_like_its_siblings():
    # Without `primary`, the FE's in-app-primary filter treats it as a
    # secondary share row; without `verified` the phase summary can pick up the
    # "(no verified links)" suffix.
    block = _regen_branch()
    assert '"verified": True' in block
    assert '"primary": True' in block


def test_no_phase_1_link_emit_anywhere_carries_the_conversation_url():
    # ⭐ THE UNIVERSAL, not a sample. Four branches emit `phase_complete phase=1`
    # and only one of them was wrong — so the check has to look at all of them.
    src = _pipeline_src()
    for m in re.finditer(r'emit_event\("phase_complete", phase=1', src):
        window = src[m.start():m.start() + 600]
        # Cut the window at the closing paren of the emit call, so the next
        # statement's use of `brief_url` cannot be read as part of this emit.
        end = window.find(")\n")
        call = window[:end if end > 0 else len(window)]
        assert '"url": brief_url' not in call, call
        assert "links=[{\"label\": \"ChatGPT Brief\"" not in call, call


def test_the_stale_comment_that_justified_it_is_corrected():
    # The old comment claimed the in-app primary "is the only link surfaced to
    # the FE" while a branch 54 lines below surfaced the conversation URL. The
    # replacement has to say what the code does.
    block = _regen_branch()
    prose = _regen_branch(inspect.getsource(research.run_pipeline))
    assert "USED TO SHIP THE RAW CHATGPT CONVERSATION" in prose
    # And the code the prose describes is really there (code_only view).
    assert "_regen_in_app_url" in block


def test_no_link_labelled_chatgpt_brief_survives_anywhere_in_the_backend():
    # A repo-wide sweep, because the label was the only thing that made this
    # emit findable and a copy elsewhere would be invisible to the guards above.
    hits = []
    for path in list(REPO.glob("*.py")) + list((REPO / "agent").rglob("*.py")):
        if any(part in (".venv", "org-stage", "__pycache__", "build", "dist")
               for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '"label": "ChatGPT Brief"' in text:
            hits.append(str(path.relative_to(REPO)))
    assert hits == []


def test_the_in_app_url_has_a_fallback_for_a_run_with_no_firestore_id(monkeypatch):
    # A CLI run with no Firestore doc has no research id. Without the fallback
    # the link reads `/documents?open=None:brief`, which resolves to nothing.
    #
    # ⛔⛔ THE CONDITION, NOT JUST THE FALLBACK VALUE. The first version of this
    # guard asserted only `else "/documents")` — and mutation caught that a
    # mutant replacing the test with `if True` keeps that substring intact, so
    # the guard passed while the fallback had become unreachable and every run
    # got `/documents`. Checking that a branch EXISTS is not checking what
    # decides it.
    #
    # ⭐ 2026-09-02, step 5 — SO IT NOW DRIVES BOTH SIDES INSTEAD OF READING THE
    # BRANCH. `if True` and `if False` both survive a substring check and neither
    # survives being run twice with the two inputs that are supposed to disagree.
    monkeypatch.setattr(research, "_fb_research_id", "")
    without = research.in_app_document_url("brief")
    monkeypatch.setattr(research, "_fb_research_id", "rid123")
    with_id = research.in_app_document_url("brief")
    assert without == "/documents"
    assert with_id == "/documents?open=rid123:brief"
    assert without != with_id, "the research id must be what decides it"


def test_a_missing_document_kind_falls_back_too(monkeypatch):
    # ⛔ THE SECOND WAY TO GET AN UNOPENABLE LINK, and the inline copies never
    # covered it: an id with no kind yields `/documents?open=rid123:`, which
    # anchors at nothing. The helper answers the index instead.
    monkeypatch.setattr(research, "_fb_research_id", "rid123")
    assert research.in_app_document_url("") == "/documents"


def test_the_link_points_at_the_brief_specifically_not_the_documents_index(monkeypatch):
    # `/documents?open={id}` without `:brief` opens the index, not the brief —
    # a link that goes somewhere is not the same as a link that goes there.
    monkeypatch.setattr(research, "_fb_research_id", "rid123")
    url = research.in_app_document_url("brief")
    assert url.endswith(":brief")
    assert url != "/documents?open=rid123"


def test_every_phase_1_branch_and_phase_2_ask_the_same_helper(monkeypatch):
    # ⭐ 2026-09-02, step 5 — THE POINT OF EXTRACTING IT. Four sites built this
    # address by hand and three agreed; the fourth is the one this file exists
    # for. Asking the same function is what makes "they agree" a fact about the
    # code rather than about who last copied it.
    src = code_only(inspect.getsource(research.run_pipeline))
    assert src.count('in_app_document_url("brief")') == 3, (
        "the from-file, live and regenerated brief branches, and no others")
    p2 = code_only(inspect.getsource(research.extract_and_record_agent))
    assert "in_app_document_url(agent_key)" in p2
    # And no branch anywhere still spells it out by hand. ⛔ ONE occurrence is
    # correct and it is the helper's own body — a `not in` here would fail on the
    # very function it is checking everyone uses.
    whole = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    assert whole.count('f"/documents?open={_fb_research_id}') == 1, (
        "the helper builds it; nobody else may")
    assert 'f"/documents?open={_fb_research_id}' in code_only(
        inspect.getsource(research.in_app_document_url))
