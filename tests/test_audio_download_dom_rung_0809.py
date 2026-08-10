"""The audio download had no DOM rung — only a vision agent (e2e 2026-08-09).

WHAT HAPPENED

    23:03:00  Claude: "The three-dot menu is open and I can clearly read the
              options: Share, Rename, **Download**, View prompt and sources, Delete."
    23:03:05  Claude: "the download has been initiated"
    23:03:35  Download event not received — checking common download dirs...
    23:03:45  Phase 3: audio file missing — auto-retry 1/3 in 5 min

No download event fired and no file existed anywhere on disk. Thirty seconds later
the DOM rung opened THE SAME MENU, successfully, for the share flow:

    23:03:35  [dom] p3 notebooklm.open_audio_menu: verified via=audio-card
              ('button[aria-label="More"]')

THE ACTUAL DEFECT

`_nlm_open_audio_menu` and `_nlm_menu_pick` were built for this menu. The deny-list
comment names the download case by name — "`Delete` sits two rows below `Download`
in the audio menu, so an off-by-two is not a failed download, it is a destroyed
one" — and then Share was the only caller either helper ever had. The download, the
step that actually blocks the pipeline, stayed vision-only: a model clicking a
coordinate, a 30-second wait, and a Downloads-folder scan.

So this is not a new capability. It is wiring a rung that already existed, was
already hardened, and was already proven to work on this exact menu in the same
run that failed without it.

WHAT THESE TESTS PIN

Not "the code contains a call". That would pass against a rung placed after the
vision agent, or one that clicks by index, or one that runs and is then ignored.
They pin the properties that make the rung worth having: it runs FIRST, it picks by
LABEL, the destructive guard is carried, the vision agent is skipped when it
succeeds, and — the one that nearly shipped broken — it does NOT return early past
the transcode, the cleanup and the share-link extract.
"""
import re
import textwrap
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "research.py"
SRC = RESEARCH.read_text(encoding="utf-8")


def _download_block() -> str:
    """The audio-download region: from the Playwright download future to the
    `finally` that stops the narration ticker."""
    start = SRC.index("        # Use Playwright download event to capture the file reliably")
    end = SRC.index("            await stop_narration_ticker(_stop_d, _task_d)", start)
    return SRC[start:end]


# ── the rung exists, and runs BEFORE the vision agent ───────────────────────

def test_the_download_has_a_dom_rung_at_all():
    """The whole finding. Before this, `_nlm_menu_pick` had exactly one call site
    and it was Share."""
    assert "_nlm_menu_pick(browser.page, want=(\"download\",))" in _download_block(), (
        "the audio download must drive the menu through the DOM helper, not leave it "
        "to a vision agent clicking a coordinate"
    )


def test_the_dom_rung_runs_before_the_vision_agent():
    """Position is the point. A rung placed after the CUA is decoration: by then the
    menu has been clicked at, possibly closed, possibly on the wrong row."""
    block = _download_block()
    assert block.index("_nlm_menu_pick") < block.index("_shadow_observed_cua"), (
        "the DOM rung must be attempted before the visual agent, not after it"
    )


def test_the_menu_is_opened_with_the_scoped_helper():
    """`_nlm_open_audio_menu` scopes into the Studio panel and confirms via
    aria-expanded. The alternative it replaced — clicking the first
    `aria-label*="More"` on the page — is how a menu on the wrong card gets opened."""
    assert "_nlm_open_audio_menu(browser.page)" in _download_block()


# ── it picks by LABEL, never by index ───────────────────────────────────────

def test_the_row_is_chosen_by_label():
    """`Delete` sits two rows below `Download`. An ordinal click is one layout
    change away from destroying the user's audio instead of saving it — which is
    why `_nlm_menu_pick` takes `want=` and not a position."""
    block = _download_block()
    assert 'want=("download",)' in block
    # No index-based selection anywhere in the rung.
    rung = block[block.index("_nlm_open_audio_menu(browser.page)"):block.index("_shadow_observed_cua")]
    assert not re.search(r"rows\s*\[\s*\d+\s*\]", rung), rung
    assert not re.search(r"nth\(\s*\d+\s*\)", rung), rung


def test_the_destructive_guard_is_carried_not_bypassed():
    """`_nlm_menu_pick`'s default deny-list is the guard. The rung must not pass its
    own `deny=`, and must report a block rather than swallowing it."""
    block = _download_block()
    rung = block[block.index("_nlm_open_audio_menu(browser.page)"):block.index("_shadow_observed_cua")]
    assert "deny=" not in rung, "the rung must not override the destructive deny-list"
    # STRUCTURE, not presence. `"blocked" in rung` passed against a mutant that
    # replaced the whole check with `if False:` — the word was still there and the
    # branch could never run. Assert the condition actually interrogates the pick.
    assert 'if _dl_pick.get("blocked"):' in rung, (
        "the destructive-row check must test the pick result, not a constant"
    )
    assert "download menu skipped destructive row" in rung, (
        "the skipped destructive rows must be logged, or the guard is silent"
    )


def test_delete_is_still_denied_by_default():
    """The guard this rung now relies on. If the deny-list ever loses `delete`, the
    download rung becomes the most dangerous caller in the file."""
    deny = re.search(r"_NLM_MENU_DENY = \(([^)]*)\)", SRC).group(1)
    assert "delete" in deny, deny


def test_download_is_not_itself_caught_by_the_deny_list():
    """Polarity. A deny-list that matched 'download' would make the rung a
    guaranteed no-op that always falls through to the agent — passing every
    assertion above while changing nothing."""
    deny = re.findall(r'"([a-z]+)"', re.search(r"_NLM_MENU_DENY = \(([^)]*)\)", SRC).group(1))
    for word in deny:
        assert not re.search(r"\b" + word + r"\b", "download"), word


# ── the vision agent is skipped on success ──────────────────────────────────

def test_the_vision_agent_is_skipped_when_the_dom_rung_got_the_file():
    """Not merely a saving. A second driver on a menu whose `Delete` row sits two
    below `Download` is a hazard, and re-clicking Download leaves a duplicate for
    the dup-count guards to trip over."""
    block = _download_block()
    assert "None if _dl_seen else await _shadow_observed_cua" in block, (
        "the visual agent must be skipped once the DOM rung has produced the file"
    )


def test_the_skip_is_gated_on_a_real_file_not_on_the_click():
    """`_dl_seen` must mean "the download event fired with a file", not "we clicked
    something". A click that lands on nothing would otherwise suppress the fallback
    and turn a recoverable miss into a hard failure."""
    block = _download_block()
    assert "download_future.done() and download_future.result() is not None" in block, (
        "the skip must be gated on the download event delivering a file"
    )


# ── the bug this nearly shipped with ────────────────────────────────────────

def test_the_rung_does_not_return_early_past_the_rest_of_phase_3():
    """The transcode to mp3, the panel cleanup, and the SHARE-LINK EXTRACT all run
    after the download block. A first draft of this rung returned as soon as it had
    the file, which would have traded a missing podcast for a missing link — the
    same outage wearing a different message."""
    block = _download_block()
    # Scoped to the RUNG, ending at the narration ticker — not at the CUA call.
    # The wider window swept in the nested `_audio_download_cua()` helper, whose
    # `return await agent_loop(...)` is a perfectly correct return from a closure
    # and has nothing to do with returning out of phase 3.
    rung_start = block.index("_dl_via_dom = False")
    rung = block[rung_start:block.index("_stop_d, _task_d = start_narration_ticker")]
    # COMMENTS STRIPPED FIRST. The comment above the rung explains why it must not
    # return early — and therefore contains the word — so a raw search matched the
    # explanation and failed against correct code. This project has hit that exact
    # shape before: a comment quoting the asserted text defeats a search for it.
    rung = "\n".join(l for l in rung.splitlines() if not l.lstrip().startswith("#"))
    assert "return " not in rung, (
        "the DOM rung must not return out of phase 3 — the transcode, the cleanup and "
        "the share-link extract still have to run:\n" + rung
    )


def test_the_share_link_extract_still_follows_the_download():
    """Guards the ordering the early return would have broken."""
    dl = SRC.index("        # Use Playwright download event to capture the file reliably")
    share = SRC.index("_nlm_menu_pick(page, want=(\"share\", \"share notebook\"))")
    assert dl < share, "the share-link extract must still run after the download block"


# ── failure handling ────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "menu not opened",
    "CUA will drive it",
])
def test_a_dom_miss_falls_through_instead_of_failing_the_phase(phrase):
    """The rung is an optimisation over the agent, not a replacement. Every miss
    path must hand back to it — a DOM rung that fails the phase on a selector change
    is strictly worse than the vision agent it was added to spare."""
    assert phrase in _download_block(), phrase


def test_a_dom_exception_cannot_take_phase_3_down():
    """Parsed, not grepped. `"except Exception" in rung` survived a mutant that
    narrowed the handler to ZeroDivisionError — the substring was still present in
    the file and every DOM error would have taken phase 3 down.

    The rung is an optimisation over a working fallback, so ANY failure in it must
    hand back to the vision agent rather than end the phase.
    """
    import ast

    # Parse the WHOLE file and locate the rung by LINE RANGE, rather than slicing a
    # mid-block string and dedenting it — a slice that starts inside a function body
    # has mixed indentation and does not parse on its own.
    lines = SRC.splitlines()
    first = next(i for i, l in enumerate(lines, 1) if "_dl_via_dom = False" in l)
    # Ends at the 8s-wait block, NOT at the narration ticker. The wider range swept
    # in that block's own `except Exception: pass`, which satisfied the assertion
    # while the DOM rung's handler had been narrowed to ZeroDivisionError — the
    # mutant survived because the test was reading a different try/except entirely.
    last = next(i for i, l in enumerate(lines, 1)
                if i > first and "_dl_seen = False" in l)

    tree = ast.parse(SRC)
    handlers = [
        h for node in ast.walk(tree) if isinstance(node, ast.Try)
        for h in node.handlers
        if first <= h.lineno <= last
    ]
    assert handlers, "the DOM rung must be wrapped in a try/except"
    caught = {getattr(h.type, "id", None) for h in handlers}
    assert "Exception" in caught, (
        f"the rung must catch Exception so a DOM error falls through to the visual "
        f"agent; it catches {caught or 'nothing'}"
    )


# ── the duplicate download (e2e 2026-08-10) ─────────────────────────────────
#
# The run worked and downloaded the podcast TWICE. Both halves of the skip were
# wrong, and each on its own is enough to produce it.


def test_blocked_does_not_gate_the_click():
    """`_nlm_menu_pick` returns `blocked` ALONGSIDE `clicked: true` — it is the list
    of denied rows it filtered out and skipped, not a refusal. The audio menu always
    contains Delete, so `blocked` is ALWAYS non-empty.

    The first version of this rung tested `blocked` first and treated it as failure:

        [01:20:44] [dom] p3 notebooklm.open_audio_menu: verified via=audio-card
        [01:20:44] [WARN] [Audio] download pick refused destructive row(s): ['delete']

    …so the rung clicked Download, reported failure, and the visual agent clicked
    Download again. `clicked` is the only field that says what happened.
    """
    block = _download_block()
    rung = block[block.index("_dl_via_dom = False"):block.index("_stop_d, _task_d = start_narration_ticker")]
    code = "\n".join(l for l in rung.splitlines() if not l.lstrip().startswith("#"))

    # The blocked branch must not be on the same if/elif chain as the click.
    assert "elif _dl_pick.get(\"clicked\")" not in code, (
        "`blocked` and `clicked` must be independent — an elif makes an always-present "
        "blocked list suppress a successful click"
    )
    assert 'if _dl_pick.get("clicked"):' in code, (
        "the click must be tested on its own"
    )
    # And blocked must be advisory: logged, never a reason to abandon the click.
    bi = code.index('if _dl_pick.get("blocked"):')
    ci = code.index('if _dl_pick.get("clicked"):')
    assert bi < ci, "log the skipped rows, then act on the click"
    between = code[bi:ci]
    assert "_dl_via_dom = True" not in between and "return" not in between, between


def test_the_skip_accepts_a_file_on_disk_not_only_the_event():
    """The Playwright `download` event has NEVER reached us from NotebookLM — logged
    twice, "the download event never reached us", both times with the file sitting
    complete in Playwright's artifacts directory.

    So gating the agent-skip on the event alone guarantees the agent runs after a
    good DOM click. The evidence must be the event OR a settled file, which are the
    same two channels the capture below already uses.
    """
    block = _download_block()
    wait = block[block.index("_dl_seen = False"):block.index("_stop_d, _task_d = start_narration_ticker")]
    assert "_find_recent_audio" in wait, (
        "the skip must also accept a file appearing on disk — the download event is "
        "not delivered by NotebookLM"
    )
    assert "_is_settled" in wait, (
        "a file still being written is a download in flight, not a finished one"
    )
    assert "download_future.done()" in wait, "the event remains a valid signal too"


def test_the_evidence_wait_is_bounded():
    """A wait with no deadline would hang phase 3 whenever the click missed, which is
    worse than the duplicate it replaced."""
    block = _download_block()
    wait = block[block.index("_dl_seen = False"):block.index("_stop_d, _task_d = start_narration_ticker")]
    assert "_dl_deadline" in wait and "time.time() <" in wait, wait


def test_a_missed_click_still_reaches_the_visual_agent():
    """Polarity. If no file ever appears, the agent MUST still run — otherwise this
    change trades a duplicate download for no download at all."""
    block = _download_block()
    wait = block[block.index("_dl_seen = False"):block.index("_stop_d, _task_d = start_narration_ticker")]
    assert "falling through to the visual agent" in wait
    # `_dl_seen` starts False and is only ever set on evidence.
    assert wait.lstrip().startswith("_dl_seen = False"), wait[:80]
