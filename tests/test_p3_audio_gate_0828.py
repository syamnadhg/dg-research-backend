"""Phase 3 completes on the podcast it actually holds.

WHAT CHANGED (stretch 6.6C, owner decision 2026-08-28)

P3 used to emit `phase_complete:3` purely on the ABSENCE of four skip flags. Not
one of them read the audio. The invariant everything downstream relies on —
"phase 3 completed, therefore there is a podcast" — held only by an accident of
coupling elsewhere in the function, and the frontend's phase-notice file states
that invariant IN PROSE as "a hard backend rule" while firing "Podcast ready"
unconditionally off the event. It was not a rule. It was a coincidence.

⛔⛔ AND THE STRONGEST PROOF WAS INVISIBLE. `run_phase3_audio` returned only
`{audio_path, audio_overview_url}` — the Firebase Storage URL from
`upload_audio_to_storage` was written to Firestore and then dropped, and its
failure is a WARN inside a swallowing `except`. So a run whose bytes never
reached Storage produced a green `phase_complete:3` and a "Podcast ready"
notice, while FE-P4 read `links.audio_file`, found nothing, and silently skipped
the video. Completion and delivery disagreed about the same run.

⭐ THE AUDIO SHARE PAGE WENT IN THE SAME ROUND, and it cost nothing. The block
that produced `links.audio` opened the audio card's ⋮ menu, picked Share, set
public access and read the URL back — and its own documented fallback was
"NotebookLM emits the SAME /notebook/{id} URL either way", falling through to
`notebook_url`. It spent CUA calls to re-derive a link we were already holding.

⛔ WHAT DID NOT CHANGE: the notebook URL is still the NAVIGATION TARGET for the
audio step (`run_phase3_audio` cannot reach the notebook without it), so the
recovery loop that recovers it stays. What stopped being true is that a link
decides whether the phase succeeded.
"""
import inspect

import pytest

import research
from conftest import code_only, code_only_deep


@pytest.fixture(scope="module")
def pipeline_src() -> str:
    return code_only(inspect.getsource(research.run_pipeline))


@pytest.fixture(scope="module")
def audio_src() -> str:
    return code_only(inspect.getsource(research.run_phase3_audio))


# ── 1. the artefact is returned, not just written ───────────────────────────

def test_the_audio_phase_returns_the_storage_url():
    """⛔ THE RETURN SIGNATURE IS THE FIX. Without this the completion gate
    below has nothing to read: the Storage URL was written to Firestore inside a
    best-effort block and never surfaced to the caller."""
    src = code_only(inspect.getsource(research.run_phase3_audio))
    assert 'return {"audio_path": audio_path, "audio_stored_url": audio_stored_url}' in src


def test_the_storage_url_is_only_set_when_the_upload_returned_one(audio_src):
    """`upload_audio_to_storage` returns None on a failed upload AND on a
    response with no downloadTokens. `audio_stored_url` must inherit exactly
    that — assigning `audio_path` or a truthy default here would put the old
    lie back with a new name."""
    assert "audio_stored_url = audio_url" in audio_src
    i_guard = audio_src.index("if audio_url:")
    i_set = audio_src.index("audio_stored_url = audio_url")
    assert i_guard < i_set, "the assignment must sit inside the `if audio_url` guard"


def test_the_storage_url_is_initialised_before_any_return(audio_src):
    """The function has eight early returns. `audio_stored_url` is initialised
    at the top so the caller's `.get(...)` never depends on which one fired."""
    assert 'audio_stored_url = ""' in audio_src
    assert audio_src.index('audio_stored_url = ""') < audio_src.index("audio_stored_url = audio_url")


def test_the_early_returns_carry_no_audio(audio_src):
    """Every bail-out returns `{"audio_path": None}` — no stored url key, which
    the caller reads with a default. A bail that claimed one would be the same
    bug in the other direction."""
    assert audio_src.count('return {"audio_path": None}') >= 5
    assert 'return {"audio_path": None, "audio_stored_url"' not in audio_src


# ── 2. the completion gate reads it ─────────────────────────────────────────

def test_phase_three_completes_only_when_a_podcast_reached_storage(pipeline_src):
    """⛔⛔ THE CONDITION THE WHOLE WAVE IS ABOUT. Four skip flags decided this
    event and none of them was the podcast."""
    assert "if _p3_no_skip and _p3_audio_stored:" in pipeline_src
    i_gate = pipeline_src.index("if _p3_no_skip and _p3_audio_stored:")
    i_emit = pipeline_src.index('emit_event("phase_complete", phase=3', i_gate)
    assert i_emit - i_gate < 400, "the complete emit must belong to that branch"


def test_the_four_skip_flags_are_still_all_required(pipeline_src):
    """The new condition is an ADDITION. Each of the four flags was a separate
    measured bug — a double terminal event, a green tile over a skip — and
    dropping any of them re-opens it."""
    block = pipeline_src[pipeline_src.index("_p3_no_skip = ("):]
    block = block[:block.index("if _p3_no_skip")]
    for flag in ("_p3_audio_user_skipped", "_p3_login_skipped",
                 "_p3_link_skipped", "_p3a_user_skipped", "_controls.is_stop()"):
        assert flag in block, f"{flag} left the gate"


def test_a_run_with_no_deliverable_podcast_reports_a_skip_not_a_silence(pipeline_src):
    """⛔ SILENCE WOULD BE WORSE THAN THE BUG. Phase 3 emitting no terminal event
    at all leaves the tile spinning and the FE waiting; the fix is a DIFFERENT
    terminal event, not a missing one."""
    assert "elif _p3_no_skip:" in pipeline_src
    tail = pipeline_src[pipeline_src.index("elif _p3_no_skip:"):]
    assert 'emit_event("phase_skipped", phase=3' in tail[:1400]


def test_the_skip_names_which_of_the_two_failed(pipeline_src):
    """"No audio was generated" and "a podcast we could not upload" are
    different states with different repairs — and in the second one the file is
    still on the research computer, which the user needs to be told."""
    assert '"audio_generated_but_upload_failed" if audio_path' in pipeline_src
    assert '"no_audio_generated"' in pipeline_src
    assert "still on the research computer" in pipeline_src


def test_the_complete_summary_no_longer_claims_an_audio_link(pipeline_src):
    """The old summary appended ", audio link extracted" off
    `audio_overview_url` — the share page removed in this wave."""
    assert "audio link extracted" not in pipeline_src
    assert "notebook link recorded" in pipeline_src


# ── 3. the notebook link stops deciding, but keeps navigating ───────────────

def test_the_notebook_url_is_still_the_audio_step_input(pipeline_src):
    """⛔⛔ IT IS NOT JUST A GATE, IT IS THE NAVIGATION TARGET. `run_phase3_audio`
    early-returns with no audio when `notebook_url` is empty, and the no-audio
    auto-retry loop is `while bool(notebook_url)`. A change that merely stopped
    treating a missing URL as a failure would turn every link failure into a run
    that silently produces no podcast and then fails the NEW gate — strictly
    worse than the card it replaced."""
    assert "if notebook_url:" in pipeline_src
    assert "while bool(notebook_url) and not audio_path" in pipeline_src
    assert "if not notebook_url:" in code_only(inspect.getsource(research.run_phase3_audio))


def test_the_upload_card_says_the_upload_failed_not_the_link(pipeline_src):
    """⛔⛔ THE CARD BLAMED THE WRONG THING. It fires when the tab is not on a
    `/notebook/{id}` page, which means the UPLOAD did not land — `notebook_url`
    is `current_url()`, captured before any share step, so there is no link
    extraction to fail. Its own retry re-runs `run_phase3_upload` from scratch
    for exactly that reason."""
    assert "Couldn't get the NotebookLM link" not in pipeline_src
    assert 'error="Couldn\'t open the NotebookLM notebook"' in pipeline_src
    assert "the notebook didn't open" in pipeline_src


def test_the_notebook_link_is_still_recorded_when_we_have_one(pipeline_src):
    """Best-effort means RECORDED, not discarded."""
    assert 'emit_validated_link(3, "notebooklm"' in pipeline_src


# ── 4. the audio share page is gone ─────────────────────────────────────────

def test_the_audio_share_extraction_is_gone(audio_src):
    """The block spent CUA calls re-deriving the notebook URL it already held."""
    assert "_set_nlm_public_and_get_link(page, \"Audio\")" not in audio_src
    assert "audio_overview_url" not in audio_src
    assert '_notebook_share_fallback' not in audio_src


def test_no_audio_share_link_is_SCRAPED_any_more(pipeline_src):
    """`links.audio` was the NotebookLM share PAGE. `links.audio_file` — the
    playable Storage file that gates FE-P4 — stays.

    ⛔ ONE `link_kind="audio"` WRITER SURVIVES ON PURPOSE, and it is the Flow-C
    hydration of a link the USER pasted. That is a source they gave us, not one
    we scraped, and this wave is about what we scrape."""
    src = code_only_deep(inspect.getsource(research))
    assert src.count('link_kind="audio"') == 1
    flow_c = 'elif _kind == "audio" and not audio_overview_url:'
    assert pipeline_src.index(flow_c) < pipeline_src.index('link_kind="audio"')
    assert 'update_link_in_firestore("audio_file"' in src


def test_the_auto_retry_leg_reads_the_artefact_not_the_removed_share_link(pipeline_src):
    """⛔⛔ A BRANCH THAT WOULD HAVE GONE PERMANENTLY DEAD. The no-audio
    auto-retry pulled `audio_overview_url` off the result dict; the key is gone,
    `.get(…, "")` is falsy, and the recovery leg would have silently stopped
    recording anything about the podcast it had just recovered — while still
    LOOKING like it did."""
    tail = pipeline_src[pipeline_src.index("auto_retry_audio_missing"):]
    assert '_p3_audio.get("audio_stored_url", "")' in tail[:1800]
    assert '_p3_audio.get("audio_overview_url"' not in pipeline_src


def test_delivery_prefers_the_playable_file_over_the_notebook_page(pipeline_src):
    """delivery.json's audio reference was `audio_overview_url or notebook_url`
    — two arms that held the same string on the healthy path. It is now the file
    when we hold one, falling back only so an existing consumer never reads an
    empty field."""
    assert "update_delivery(audio_url=_p3_audio_stored or audio_overview_url or notebook_url)" in pipeline_src


def test_the_audio_download_leg_survived(audio_src):
    """⛔ `_nlm_open_audio_menu` / `_nlm_menu_pick` had two callers and only the
    SHARE one goes. The DOWNLOAD is the step that produces the file the phase
    now completes on — removing it would have deleted the artefact and the gate
    in one edit."""
    assert "_nlm_open_audio_menu(browser.page)" in audio_src
    assert 'want=("download",)' in audio_src
    assert "upload_audio_to_storage" in audio_src


def test_the_pasted_audio_link_path_is_untouched(pipeline_src):
    """Flow C — a user who pastes their own audio link — writes
    `audio_overview_url` at hydration. That is a user-supplied source, not a
    scraped one, and it was never part of this wave."""
    assert 'elif _kind == "audio" and not audio_overview_url:' in pipeline_src
