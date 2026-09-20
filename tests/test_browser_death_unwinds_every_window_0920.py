"""Every window a browser can die in unwinds to the checkpoint, and the
exception says so on its own.

⛔⛔ WHAT THE 09-20 PASS SHIPPED, AND WHAT AN ADVERSARIAL PASS FOUND LEFT OVER.
Bundle 8D9CWHZJ was Chrome's browser process taking a SIGSEGV. The repair added
a context-level probe and wired it into the phase-2 crash sweep — one window,
out of five that can park a run on a browser that no longer exists:

  · phase-2 HARD RETRY — `except Exception` → fail one agent → `del pending`.
    The same draining the sweep used to do, reached without the sweep. A
    browser dying while the last agents restart empties `pending` one agent at
    a time and Phase 2 reports COMPLETE.
  · phase-3 AUDIO POLL — asked `_poll_pg.is_closed()`, a question about ONE
    TAB. That lens is precisely what cost nine hours in the sweep.
  · phase-3 ENTRY GATE — "None of the agents produced a report", a true
    sentence about a dead browser and a useless one. 24-hour default wait.
  · the NOTEBOOK PARK — the worst of them: every rung answers softly on a dead
    page (`extract_notebooklm_url` returns a result, `_page_shows_login_wall`
    never raises), and this block sits OUTSIDE
    `_await_phase_with_active_deadline`, so there is no 15-minute ceiling
    either. A straight 24-hour hang behind a Retry that cannot work.

⛔⛔ AND THE COUPLING NOBODY PINNED. Each site raises a RuntimeError in OUR
words, and none of those words matched `_is_browser_close_error` — the whole
recovery rode on `_runtime.last_failure_kind`, one side channel set on the line
before the raise. A `_runtime.reset()` anywhere on the unwind would downgrade a
crash to an ordinary failure in total silence. Every crash message now ends in
`(browser crash)` and the classifier knows that marker, so the kind survives
the flag being lost.

⭐ THESE TESTS EXECUTE. The 09-20 batch was ten source pins and one probe, and
the refuters were right that a source pin cannot tell "the guard is present"
from "the guard is reachable".
"""
from __future__ import annotations

import json

import pytest

import research
from conftest import code_only


CLOSED = "BrowserContext.cookies: Target page, context or browser has been closed"


# ── the marker, which is what makes the unwind self-describing ────────────

#: Every site that concludes the browser is gone, and the sentence it raises.
CRASH_MESSAGES = [
    "research browser died during phase 2 (browser crash)",
    "research browser died during a phase 2 hard retry (browser crash)",
    "research browser died before the NotebookLM upload (browser crash)",
    "research browser closed mid-audio-poll (browser crash)",
    "research browser died before phase 3 could start (browser crash)",
    "research browser died before the notebook could be opened (browser crash)",
]


@pytest.mark.parametrize("msg", CRASH_MESSAGES)
def test_every_crash_we_raise_classifies_from_its_own_text(msg):
    """⛔⛔ THE COUPLING. Without this the kind exists only in `_runtime`, and
    the top-level handler cannot re-derive it from the exception it caught."""
    assert research._is_browser_close_error(RuntimeError(msg)) is True, msg


@pytest.mark.parametrize("msg", CRASH_MESSAGES)
def test_and_every_one_of_them_is_actually_in_the_source(msg):
    """⭐ The list above is only evidence if it is the list the code raises. A
    fixture naming messages nobody raises would pass forever and measure
    nothing — which is the failure mode this whole file exists to answer."""
    src = code_only(open(research.__file__, encoding="utf-8").read())
    assert msg in src, f"no site raises this any more: {msg}"


def test_a_login_interrupt_is_NOT_swept_up_by_the_marker():
    """⛔⛔ THE NO-WIDENING GUARD, and it is the one that matters. `--login`
    kills Chrome ON PURPOSE. If its message classified as a crash, the run
    would silently relaunch Chrome onto the very profile the person is signing
    into — and the login side would kill it again. A fight, not a recovery."""
    for msg in ("research browser closed by the login command (login interrupt)",):
        assert research._is_browser_close_error(RuntimeError(msg)) is False, msg


def test_the_login_sites_carry_no_crash_marker_in_the_source():
    """The same rule, asserted where it can rot: a future edit that tidies all
    these messages into one shape would reintroduce the fight."""
    src = code_only(open(research.__file__, encoding="utf-8").read())
    for line in src.splitlines():
        if "login interrupt)" in line:
            assert "browser crash" not in line, line


def test_an_ordinary_failure_is_still_not_a_crash():
    """Fails safe towards "alive": a wrong True relaunches a HEALTHY run."""
    for msg in ("Timeout 30000ms exceeded", "net::ERR_INTERNET_DISCONNECTED",
                "the browser crashed the party", "", "crash"):
        assert research._is_browser_close_error(RuntimeError(msg)) is False, msg


# ── the unwind, executed rather than read ─────────────────────────────────

def _queue(tmp_path, status="ongoing"):
    q = tmp_path / "queues" / "r1"
    q.mkdir(parents=True)
    (q / "delivery.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    return q


def test_a_crash_at_phase_two_really_does_plan_a_silent_retry(tmp_path, monkeypatch):
    """⛔⛔ THE END OF THE CHAIN, EXECUTED. Everything before this was verified
    by reading. `_plan_pipeline_auto_retry` is what turns a raise into a
    relaunch-and-resume, and this asserts it says yes for the incident's own
    shape: phase 2, first failure, nothing terminal on disk."""
    q = _queue(tmp_path)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _d: (2, None))
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)

    will_retry, phase, is_crash = research._plan_pipeline_auto_retry(
        q, None, "browser_crash", 0)
    assert (will_retry, phase, is_crash) == (True, 2, True)


@pytest.mark.parametrize("phase", [0, 1, 2, 3, 4])
def test_a_crash_in_any_phase_the_recovery_covers_is_planned(tmp_path, monkeypatch, phase):
    """⭐ 0 and 1 are included ON PURPOSE (#725): a crash before the brief is
    written reports phase 0, and the old `1 < phase` gate excluded it."""
    q = _queue(tmp_path)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _d: (phase, None))
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    assert research._plan_pipeline_auto_retry(q, None, "browser_crash", 0)[0] is True


def test_the_retry_is_capped_and_the_cap_is_not_infinity(tmp_path, monkeypatch):
    """⚠ SAID PLAINLY, BECAUSE IT IS A REAL LIMIT: a DETERMINISTIC Chrome
    segfault — which is what 8D9CWHZJ was — still ends at a card after the
    budget. The fix makes the crash visible and recoverable, not survivable."""
    q = _queue(tmp_path)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _d: (2, None))
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    cap = research.BROWSER_CRASH_MAX_RETRIES
    assert cap >= 1
    assert research._plan_pipeline_auto_retry(q, q, "browser_crash", cap - 1)[0] is True
    assert research._plan_pipeline_auto_retry(q, q, "browser_crash", cap)[0] is False


def test_a_user_stop_is_never_auto_retried(tmp_path, monkeypatch):
    """⛔⛔ The owner stopped bundle 8D9CWHZJ by hand after nine hours. A stop
    that came back as a relaunch would be the worst possible reading of it."""
    q = _queue(tmp_path)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _d: (2, None))
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    (q / ".stop").touch()
    assert research._plan_pipeline_auto_retry(q, None, "browser_crash", 0)[0] is False


@pytest.mark.parametrize("status", ["completed", "stopped", "paused"])
def test_nor_is_a_terminal_delivery_status(tmp_path, monkeypatch, status):
    q = _queue(tmp_path, status)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _d: (2, None))
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    assert research._plan_pipeline_auto_retry(q, None, "browser_crash", 0)[0] is False


def test_a_login_interrupt_stands_down_rather_than_fighting(tmp_path, monkeypatch):
    """#907, executed. Relaunching onto the profile being signed into starts a
    kill-fight between the two halves."""
    q = _queue(tmp_path)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _d: (2, None))
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: True)
    assert research._plan_pipeline_auto_retry(q, None, "browser_crash", 0)[0] is False


# ── the four windows that were still soft ─────────────────────────────────

def _window(start: str, end: str) -> str:
    src = code_only(open(research.__file__, encoding="utf-8").read())
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_the_audio_poll_asks_the_CONTEXT_not_just_the_tab():
    """⛔⛔ It was on `_poll_pg.is_closed()` alone — the exact lens the commit
    message says cost the nine hours in the sweep, left in place one phase
    over."""
    # ⚠ CODE anchors, not comment text: `code_only` blanks comments in place,
    # so a window opened on a comment can never be found.
    body = _window('_poll_pg = getattr(browser, "page", None)', "browser.page.reload")
    assert "_browser_context_is_dead(browser)" in body
    # The cheap per-tab question still comes first; the round-trip is the
    # fallback, not the default.
    assert body.index("is_closed()") < body.index("_browser_context_is_dead(browser)")


def test_the_phase_two_hard_retry_no_longer_drains_pending_on_a_dead_browser():
    """This catch fails ONE agent on ANY exception. It is the one path that can
    empty `pending` without the sweep ever running."""
    body = _window("restart = await _restart_phase2_agent", "hard_retry_failed")
    assert "_browser_context_is_dead(browser)" in body
    assert "raise RuntimeError" in body


def test_the_phase_three_entry_gate_does_not_park_for_a_day_on_a_dead_browser():
    body = _window("No research output (attempt", "if _flow_b_intent:")
    assert "_browser_context_is_dead(browser)" in body
    assert "raise RuntimeError" in body


def test_the_notebook_park_classifies_before_offering_an_impossible_retry():
    """⛔⛔ THE WORST OF THE FOUR: no 15-minute ceiling covers this block, so it
    is a straight 24-hour hang. And it must be asked BEFORE the login-wall
    probe, which answers None on a dead page and would send it down the
    'signed out' branch."""
    body = _window("no verified NotebookLM URL after retries", "_nb_skip_in = 0.0")
    assert "_browser_context_is_dead(browser)" in body
    assert body.index("_browser_context_is_dead(browser)") < body.index("_page_shows_login_wall")
