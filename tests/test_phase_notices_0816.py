"""Two events that did not say what the phase actually produced.

The owner asked for a notification as each phase lands (2026-08-16). Building it
surfaced two places where the backend's own terminal event was missing the fact
the web app needed, and neither could be fixed on the frontend alone.

1. PHASE 1 ANNOUNCED A BRIEF THAT WAS SKIPPED.

   A Skip after a brief-generation error sets an empty BriefArtifact, emits a
   plain `phase_complete:1`, and writes the phase's durable status as "skipped"
   three lines later. The web app read the event, saw a completed phase 1, and
   pushed "Brief ready — your research brief is ready".

   It had nothing else to go on. The summary is prose, and phase 1 legitimately
   completes with no links at all — the resume-with-input regen path emits
   `links=[]` whenever no share URL was captured — so link presence cannot
   stand in for it either. Phase 5 solved the identical problem in July with a
   `skipped` marker on the event; this is that marker, one phase over.

   ⛔ The emit itself stays. Same contract as phase 5's: the tile hangs without
   it. Mark it, don't delete it.

2. PHASE 3 THREW AWAY A NOTEBOOK IT HAD BUILT.

   When the Audio Overview cannot be downloaded after three auto-retries, phase
   3 gives up and emits `phase_skipped:3` — never `phase_complete:3`. The
   notebook was created successfully and is delivered in the report and the
   email; the warning card emitted immediately above says exactly that
   ("continuing with the notebook link only"). But the terminal event carried no
   links, so the only notification the user got said the phase was skipped.

   ⛔ The gate on the frontend is link PRESENCE, so it matters that no OTHER
   phase_skipped:3 carries links — a config skip or a user Skip must not be able
   to announce a notebook the run never made. That is asserted here, on the
   syntax tree, because it is a property of every call site rather than of one.
"""
import ast
import inspect

import pytest

import research


def _tree():
    return ast.parse(inspect.getsource(research))


def _emit_calls(event_type, **match_kwargs):
    """Every `emit_event("<event_type>", ...)` call in research.py whose keyword
    arguments include the given literal values."""
    out = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") != "emit_event":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != event_type:
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        ok = True
        for name, want in match_kwargs.items():
            v = kw.get(name)
            if not isinstance(v, ast.Constant) or v.value != want:
                ok = False
                break
        if ok:
            out.append(kw)
    return out


# ── 1. the skipped brief ────────────────────────────────────────────────────

def _p1_src():
    # The skip branch lives in the pipeline body, not in run_phase1 — run_phase1
    # returns the brief and the caller decides what a Skip meant.
    src = inspect.getsource(research)
    at = src.index('summary="Phase 1 skipped after error — no brief generated"')
    # Bounded by the branch itself rather than a character count: the next
    # branch also emits phase_complete:1, and a window that spilled into it
    # would let THAT emit satisfy assertions about this one.
    end = src.index("elif _brief_from_file:", at)
    return src[max(0, at - 900):end]


def test_the_skipped_brief_emit_is_marked_skipped():
    """⭐ The fix. Without this the web app says "Brief ready" for a brief that
    is an empty string."""
    src = _p1_src()
    at = src.index('emit_event("phase_complete", phase=1')
    assert "skipped=True" in src[at:], (
        "the phase-1 skip emit must carry skipped=True — it is the only signal "
        "the notifier can read"
    )


def test_it_still_emits_the_event():
    """⛔ The over-correction that would pass a 'no false notification' test and
    hang the tile instead. Phase 5's twin carries the same warning in a comment
    because it was considered there too."""
    assert 'emit_event("phase_complete", phase=1' in _p1_src()


def test_the_marker_rides_the_same_call_not_a_second_emit():
    """A separate `emit_event("phase_skipped", ...)` alongside the completion
    would leave the completion event unmarked and give the phase two terminal
    events — the double-terminal bug #899 fixed for this same phase."""
    marked = [kw for kw in _emit_calls("phase_complete", phase=1, skipped=True)]
    assert len(marked) == 1, "exactly one phase-1 completion is a skip"


def test_no_real_phase_1_completion_claims_to_be_skipped():
    """⛔ The polarity. Marking every phase-1 emit would silence the notice for
    every run — including the three paths that produce a real brief."""
    all_p1 = _emit_calls("phase_complete", phase=1)
    assert len(all_p1) >= 4, "phase 1 completes from several branches; found too few"
    marked = [kw for kw in all_p1 if "skipped" in kw]
    assert len(marked) == 1, (
        f"exactly one phase-1 completion may be marked skipped; {len(marked)} are"
    )


def test_the_marker_is_a_literal_true_not_a_variable():
    """The frontend tests `=== true` on a value read back from Firestore. A
    truthy-but-not-true value (an empty string, a 0) would read as 'not
    skipped' and put the false notification straight back."""
    kw = _emit_calls("phase_complete", phase=1, skipped=True)[0]
    node = kw["skipped"]
    assert isinstance(node, ast.Constant) and node.value is True


def test_the_durable_phase_status_still_says_skipped():
    """The event marker and the persisted tile status are two different readers
    of the same fact. They must not drift apart — a tile that says complete and
    a notification that stays silent is the same inconsistency inverted."""
    assert '_write_phase_terminal_status(1, "skipped")' in _p1_src()


# ── 2. the notebook on the give-up path ─────────────────────────────────────

GIVE_UP = "audio_unavailable_after_auto_retries"


def test_the_audio_giveup_carries_the_notebook():
    """⭐ The fix. This branch is the only way a successfully-built notebook
    reaches a terminal phase-3 event that is not phase_complete."""
    calls = _emit_calls("phase_skipped", phase=3, reason=GIVE_UP)
    assert len(calls) == 1, f"expected exactly one give-up emit, found {len(calls)}"
    assert "links" in calls[0], "the give-up emit must carry the links it built"
    assert getattr(calls[0]["links"], "id", "") == "_p3_links", (
        "it must carry the phase's own link list, not a fresh literal"
    )


def test_every_emit_that_carries_links_carries_the_PHASES_OWN_list():
    """⛔ THE LOAD-BEARING HALF, restated 2026-08-28. This asserted that exactly
    ONE phase_skipped:3 emit carried links, and stretch 6.6C added a second: the
    branch that fires when the notebook was built but no podcast reached Storage.
    That branch is the give-up's twin — same state, different cause — and the
    notebook it built is exactly the thing the user should hear about.

    ⭐ The count was never the protection, and the docstring it replaced was
    imprecise about why. The frontend's gate is `hasLink(links, /notebook/i)`
    (phase-notice.ts) — it looks for a ROW with a notebook label and a non-empty
    url, not for the kwarg. And `_p3_links` is built from `notebook_url` only
    after `validate_link` accepts it, so it is EMPTY on exactly the paths where
    there is nothing to announce. The real rule is that the kwarg must be that
    list and never a fresh literal: a literal is how an emit would announce a
    notebook the run never made."""
    with_links = [kw for kw in _emit_calls("phase_skipped", phase=3) if "links" in kw]
    assert with_links, "no phase_skipped:3 emit carries links — the give-up must"
    for kw in with_links:
        assert getattr(kw["links"], "id", "") == "_p3_links", (
            "a phase_skipped:3 emit may carry the phase's own validated link "
            "list and nothing else — a literal here announces a notebook that "
            "may never have been made"
        )
    reasons = {kw["reason"].value for kw in with_links
               if isinstance(kw.get("reason"), ast.Constant)}
    assert GIVE_UP in reasons, f"the give-up emit lost its links: {reasons}"


def test_the_links_are_built_before_the_give_up_can_fire():
    """A NameError here would take down the phase instead of notifying about
    it. `_p3_links` is built once, above the retry loop the give-up breaks out
    of; this pins that order rather than trusting the read."""
    src = inspect.getsource(research)
    built = src.index("_p3_links = []")
    giveup = src.index(f'reason="{GIVE_UP}"')
    assert built < giveup


def test_the_notebook_row_is_what_the_frontend_matches_on():
    """The frontend tells the notebook from the Audio Overview by LABEL —
    NotebookLM serves the same /notebook/{id} URL for both share dialogs, so a
    url-based split cannot work. Renaming this label silently breaks the
    notice."""
    src = inspect.getsource(research)
    assert '{"label": "NotebookLM Notebook", "url": notebook_url, "verified": True}' in src
    # ⛔ THE "Audio Overview" ROW LEFT THIS LIST ON 2026-08-28 (stretch 6.6C),
    # and it was DEAD before it left: its guard was `audio_overview_url`, which
    # is "" for the whole ordinary run path — the only other writer is the
    # Flow-C hydration of a link the USER pasted, on the mutually-exclusive arm
    # of the same if/elif. So the append could never fire, while its comment
    # still explained how the frontend would render the row.
    #
    # ⭐ The frontend injects that row itself now, from
    # `research.audios[].audioUrl` — the playable Storage file, which is the
    # artefact Phase 3 completes on rather than a NotebookLM page
    # (`src/lib/audio-row.ts`). The LABEL contract this test protects is
    # unchanged and is now asserted where the row is actually built.
    assert '{"label": "Audio Overview", "url": audio_overview_url' not in src


def test_the_give_up_still_marks_phase_4_skipped():
    """The notebook notice must not come at the cost of the behaviour around
    it: no audio means no video, and phase 4 is stood down explicitly."""
    src = inspect.getsource(research)
    at = src.index(f'reason="{GIVE_UP}"')
    after = src[at:at + 400]
    assert "_controls.skipped_phases.add(4)" in after
    assert "_p3_audio_user_skipped = True" in after


@pytest.mark.parametrize("phase", [0, 1, 2, 4, 5])
def test_no_other_phase_grew_a_links_kwarg_on_its_skip(phase):
    """Sibling check. The frontend only reads links off a skipped phase 3; a
    links kwarg elsewhere is dead weight that a future change would mistake for
    a supported signal."""
    with_links = [kw for kw in _emit_calls("phase_skipped", phase=phase) if "links" in kw]
    assert with_links == []


# ── 3. asking the web app to notify, so it works with the app CLOSED ────────
#
# Every phase notification in the product is dispatched by a React component, so
# it needs an OPEN BROWSER TAB. That is the owner's whole report: phase 1
# arrived live, phase 2 arrived "after the end of the research" — deferred, not
# lost, because the tab was closed. A run takes ninety minutes.

def _emit_event_src():
    return inspect.getsource(research.emit_event)


def test_the_terminal_events_ask_the_web_app_to_notify():
    """⭐ The feature. One seam, at the single funnel every event passes."""
    src = _emit_event_src()
    assert "_post_fe_phase_notice(" in src, (
        "nothing asks — every phase notice still needs an open browser tab"
    )


def test_only_terminal_and_trouble_events_ask():
    """A phase emits thousands of PROGRESS events. Asking on any of them would
    be a notification per heartbeat.

    ⭐ 2026-09-01: the accepted set grew from two to four. What it still refuses
    is progress — the two additions are `pipeline_error` and `pipeline_stopped`,
    both of which mean the run is no longer advancing. Before that widening this
    gate was the ONLY thing the machine could ever say, and both of its events
    were good news, so a run blocked at 02:00 told nobody anything.
    """
    src = _emit_event_src()
    at = src.index("_post_fe_phase_notice(")
    guard = src[:at]
    assert '_NOTIFY_TERMINAL = ("phase_complete", "phase_skipped")' in guard
    # ⭐⭐ The second half is NOT an event list. Blockers are emitted under four
    # different event names (`emit_decision` takes an `event_name` override), so
    # a name list missed every one of them; the card's own catalog class is the
    # question, and it cannot be defeated by a rename.
    assert 'data.get("recoverability") == "blocker"' in guard
    # ⛔ The refusal is still the point: progress must reach nothing.
    for progress in ("phase_start", "agent_progress", "link_extracted"):
        assert progress not in guard


def test_preflight_does_not_ask():
    """⛔ Phase 0 produces nothing the user asked for. The web app would answer
    with an empty list, so this is about not making the call at all — one
    pointless round trip per run, on every run."""
    src = _emit_event_src()
    at = src.index("_post_fe_phase_notice(")
    assert "1 <= phase <= 5" in src[:at]
    # ⛔ …and the range stays on the TERMINAL branch only. A blocker during
    # preflight is exactly the kind that strands a run overnight, so trouble is
    # deliberately not phase-scoped.
    gate = src[:at]
    trouble = gate[gate.index('or data.get("recoverability") == "blocker"'):]
    assert "1 <= phase <= 5" not in trouble


def test_the_ask_carries_ids_only():
    """⭐⭐ THE SECURITY OF IT. The request names an event; the web app reads
    that event out of Firestore and composes every word from what it says. A
    body carrying a title, a summary or a link would make this a relay: a
    machine could announce whatever it liked into its owner's inbox, push and
    email."""
    src = inspect.getsource(research._post_fe_phase_notice)
    at = src.index('"phaseNotice"')
    body = src[at:at + 500]
    for allowed in ("kind", "ownerUid", "researchId", "phase", "eventType", "seq"):
        assert f'"{allowed}"' in body, f"the ask must carry {allowed}"
    for forbidden in ("title", "body", "summary", "links", "message", "text"):
        assert f'"{forbidden}"' not in body, (
            f"the ask must NOT carry {forbidden} — the web app composes every word"
        )


def test_the_ask_uses_the_seq_of_the_event_just_written():
    """⭐ Not the module global. `_emit_to_firestore` bails without writing when
    Firestore is not configured, and the global then still holds the PREVIOUS
    event's seq — which names a real document from an earlier phase."""
    src = _emit_event_src()
    assert "_emitted_seq = _emit_to_firestore(event)" in src
    at = src.index("_post_fe_phase_notice(")
    assert "_emitted_seq" in src[at:at + 400], "the ask must pass the returned seq"
    # ⛔ A failed write must not be announced. The clause moved to the FRONT of
    # the gate when the trouble branch was added — `_emitted_seq and (...)` —
    # so it now guards both branches instead of only the terminal one, which is
    # stronger than the phrasing this used to match.
    gate = src[:at]
    assert "_notify_ok = bool(_emitted_seq) and (" in gate, "a failed write must not be announced"


def test_a_write_that_did_not_happen_returns_no_seq():
    """The other half of the same guarantee, at the source."""
    src = inspect.getsource(research._emit_to_firestore)
    at = src.index("if not _firebase_db or not _fb_uid or not _fb_research_id:")
    assert "return None" in src[at:at + 120], "the bail must return None, not fall through"
    err = src.index('log(f"Firestore emit failed')
    assert "return None" in src[err:err + 160], "a failed write must return None too"
    ok = src.index("return _fb_seq")
    assert ok < err, "the success path must return the seq it wrote"


def test_the_ask_goes_to_the_notify_route_with_the_device_token():
    src = inspect.getsource(research._post_fe_phase_notice)
    assert "_fresh_user_mode_id_token()" in src
    assert '/api/notify"' in src
    assert 'f"Bearer {id_token}"' in src


def test_the_ask_never_blocks_the_run_and_never_raises():
    """A notification is not worth holding the worker for, and the run must
    finish whether or not the web app answered."""
    src = inspect.getsource(research._post_fe_phase_notice)
    assert "_threading.Thread(" in src
    assert "daemon=True" in src
    assert "timeout=20" in src
    # ⭐ `.start()`, not `.run()`. `Thread(...).run()` executes the body INLINE on
    # the calling thread — it keeps every identifier above exactly where it is,
    # `daemon=True` included, and blocks the worker for the full HTTP timeout on
    # a slow or unreachable web app. Asserting the constructor is not asserting
    # the concurrency; that mutant survived the first version of this test.
    at = src.index("_threading.Thread(")
    assert ").start()" in src[at:], "the thread must be STARTED, not run inline"
    assert ").run()" not in src[at:]
    # the emit-side call is wrapped too — emit_event is the critical path for
    # every FE state update and must not be breakable by a notification
    at = _emit_event_src().index("_post_fe_phase_notice(")
    assert "try:" in _emit_event_src()[max(0, at - 200):at]


def test_a_machine_with_no_credentials_still_runs():
    """⛔ An unpaired or revoked machine must skip the ask, not fail the phase.
    The browser's own notifier remains the backstop."""
    src = inspect.getsource(research._post_fe_phase_notice)
    at = src.index("if not id_token:")
    assert "return False" in src[at:at + 300]
