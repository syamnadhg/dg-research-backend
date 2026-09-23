"""When Chrome keeps closing, the last card says so and says what to try.

⛔⛔ THE DEFECT (wave 10.10). `run_pipeline`'s terminal card — the one shown
after the silent relaunches are used up — said **"The run kept hitting errors …
We tried to recover a couple of times and it didn't take"** for every kind of
failure. The machine KNEW when the kind was a Chrome death: it classifies it,
captures it before the `finally` wipes it, spends a separate relaunch budget on
it and writes it into the no-auto-retry marker. Only the sentence threw it
away, so a person whose research Chrome closed three times in a row was told
"errors" and offered a Retry that would meet the same Chrome.

⭐ SO THE CARD BRANCHES ON THE CAPTURED KIND. A Chrome death names Chrome, says
how many times it closed when it closed more than once, and says what to change
before Retry. Every other kind keeps today's sentence word for word.

⛔ WHY NOT `browser_crash_copy`, the Chrome wording helper the plan named. That
helper describes ONE page dying under a run that carried on — its details end
"Nothing on your side caused this; the run continued without it", and its own
contract is that it never names a cause. On this card the run did NOT carry on,
and the whole point is the advice about the person's side. Reusing it would have
printed two false sentences.

▶ EXECUTED, NOT READ. Every test below drives the REAL `run_pipeline` into its
catch-all by making the very first thing inside its `try` raise, and reads the
card off the one `fail_phase` call the terminal branch makes. Only the edges of
the run are stubbed: the network, the clipboard, the log file and the browser.
"""
import asyncio
import re

import pytest

import research


class _FakeBrowser:
    """Never launched: the run dies before phase 0 asks it to start."""

    def __init__(self, *a, **k):
        self.context = None

    async def start(self):
        return None

    async def close(self):
        return None


@pytest.fixture
def crashed_run(tmp_path, monkeypatch):
    """Returns `run(exc, crash_retries=…)` → the terminal card's kwargs.

    `exc` is what the first statement inside `run_pipeline`'s main `try` raises.
    A resume dir is used so the run's own one-shot retry for ordinary failures
    is already spent, exactly as on the attempt that shows this card."""
    queue_dir = tmp_path / "Grid_storage_20260923_120000"
    (queue_dir / "documents").mkdir(parents=True)
    cards = []

    monkeypatch.setattr(research, "resolve_api_key", lambda _k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    monkeypatch.setattr(research, "_profile_dir", lambda *_a, **_k: tmp_path / "profile")
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)

    async def _noop_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop_dispatcher)
    monkeypatch.setattr(research, "fail_phase", lambda **kw: cards.append(kw))

    def _run(exc, crash_retries=0):
        def _emit(name, phase=None, **_kw):
            # The first thing the main `try` does is announce phase 0.
            if name == "phase_start" and phase == 0:
                raise exc
        monkeypatch.setattr(research, "emit_event", _emit)
        asyncio.run(research.run_pipeline(
            topic="Grid storage", resume_dir=str(queue_dir),
            uid=None, email=None, api_key="test-key",
            _crash_retries=crash_retries))
        assert len(cards) == 1, (
            f"expected the one terminal card, got {len(cards)} — the run did not "
            f"reach the crash-loop branch this test is about")
        return cards[0]

    return _run, queue_dir


def _chrome_died():
    # The unwind sites' own wording; `_is_browser_close_error` keys on the tag.
    return RuntimeError("research browser died during phase 2 (browser crash)")


def _something_else():
    return RuntimeError("the notebook upload was refused")


# ══ 1. a Chrome death that used up its relaunches ══════════════════════
def test_after_chrome_closed_over_and_over_the_card_names_chrome(crashed_run):
    """⛔⛔ THE DEFECT. Against the code before this wave the title here was
    "The run kept hitting errors" — which says nothing about Chrome at all."""
    run, _qd = crashed_run
    card = run(_chrome_died(), crash_retries=research.BROWSER_CRASH_MAX_RETRIES)
    assert card["error"] == "Research stopped: Chrome kept closing"
    closes = research.BROWSER_CRASH_MAX_RETRIES + 1
    assert f"Chrome closed {closes} times in a row" in card["reason"], (
        "the card must say how many times Chrome closed — it is the fact that "
        "separates a flaky machine from a one-off")
    assert "kept hitting errors" not in card["error"] + card["reason"]


def test_the_chrome_card_says_what_to_change_before_retry(crashed_run):
    """⭐ The advice is the half that helps. A Retry into the same Chrome buys the
    same three closes; these three are what change it."""
    run, _qd = crashed_run
    card = run(_chrome_died(), crash_retries=research.BROWSER_CRASH_MAX_RETRIES)
    reason = card["reason"]
    assert "Quit other Chrome windows" in reason
    assert "update Chrome" in reason
    assert "restart that computer" in reason
    # …and it still says what the two buttons do.
    assert "Retry to start again from the last checkpoint" in reason
    assert "Skip to stop here" in reason


def test_the_chrome_card_keeps_its_identity(crashed_run):
    """⛔ Only the WORDS change. The intent picks the buttons (Retry resumes from
    the checkpoint, Skip discards) and the alert id keeps a dismissed timeout
    card from silencing this one; both must stay what the web and the chat
    assistant key on."""
    run, _qd = crashed_run
    card = run(_chrome_died(), crash_retries=research.BROWSER_CRASH_MAX_RETRIES)
    assert card["intent"] == "crash_loop"
    assert card["alert_id"].endswith("_crash_loop")
    assert card["agent"] is None


# ══ 2. every other kind keeps today's card ═════════════════════════════
def test_an_ordinary_failure_keeps_todays_sentence(crashed_run):
    """⭐ ACCEPT POLARITY. A card that named Chrome for EVERY failure would pass
    every test above and send somebody off to update a browser that was fine."""
    run, _qd = crashed_run
    card = run(_something_else())
    assert card["error"] == "The run kept hitting errors"
    assert card["reason"] == (
        "We tried to recover a couple of times and it didn't take. Retry to start "
        "again from the last checkpoint, or Skip to stop here.")
    assert "Chrome" not in card["error"] + card["reason"]


# ══ 3. one close is not "kept closing" ═════════════════════════════════
def test_a_single_close_does_not_claim_a_streak(crashed_run, monkeypatch):
    """⛔ The card is also reached by a Chrome death the relaunch planner refuses
    outright (the run is past the phases it can re-enter). Chrome closed once
    there, and "kept closing … 1 times in a row" would be the kind of sentence
    this wave exists to remove. The planner is stubbed only to reach that door;
    its own gates are pinned by their own suites."""
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry",
                        lambda *a, **k: (False, 0, True))
    run, _qd = crashed_run
    card = run(_chrome_died(), crash_retries=0)
    assert card["error"] == "Research stopped: Chrome closed unexpectedly"
    assert "times in a row" not in card["reason"]
    assert "Quit other Chrome windows" in card["reason"], (
        "the advice is the same whichever way Chrome went")


# ══ 4. the title reaches the screen ════════════════════════════════════
#: The web's `humanizeError` (src/lib/pipeline-errors.ts) passes a title through
#: verbatim when it matches this, on the lower-cased title; anything it does not
#: recognise becomes "Hit a snag at the research step — retrying." — a false
#: line above a body saying we stopped.
_WEB_VERBATIM_STOPPED = re.compile(r"\bstopped:\s*\S")


@pytest.mark.parametrize("streak", [False, True])
def test_the_chrome_title_is_one_the_web_shows_as_written(crashed_run, monkeypatch,
                                                         streak):
    """⛔ Wave 10.10's first cut titled the card "Chrome kept closing"; the web
    matched it to nothing and showed "Hit a snag … — retrying." instead, so the
    new title never reached the screen. Both close counts are driven."""
    retries = research.BROWSER_CRASH_MAX_RETRIES if streak else 0
    if not streak:
        monkeypatch.setattr(research, "_plan_pipeline_auto_retry",
                            lambda *a, **k: (False, 0, True))
    run, _qd = crashed_run
    title = run(_chrome_died(), crash_retries=retries)["error"]
    assert _WEB_VERBATIM_STOPPED.search(title.lower()), title
    assert "Chrome" in title.split("stopped:", 1)[1]
    assert not research._web_swallows_title(title)


def test_the_card_still_records_that_the_run_gave_up(crashed_run):
    """The marker the card writes is untouched by the wording — and it is what
    keeps a supervised boot from relaunching this run at attempt zero."""
    run, qd = crashed_run
    run(_chrome_died(), crash_retries=research.BROWSER_CRASH_MAX_RETRIES)
    assert research._no_auto_retry_marked(qd)
