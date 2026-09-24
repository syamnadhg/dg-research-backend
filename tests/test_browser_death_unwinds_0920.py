"""A dead browser unwinds to the checkpoint. It does not look like three
agents failing one at a time.

⛔⛔ THE INCIDENT — support bundle 8D9CWHZJ, 2026-09-20. Chrome's BROWSER
process took a SIGSEGV. macOS wrote the report itself
(`Google Chrome-2026-09-20-003359.ips`: EXC_BAD_ACCESS, faulting thread
CrBrowserMain, pid parented by the patchright driver, launched at the same
second as our run's browser). Nothing in this repo closed it, and no commit
caused it — the segfault is in third-party code on a very new Chrome/macOS
pair.

WHAT WAS OURS IS EVERYTHING THAT HAPPENED NEXT:

    00:34:40  [Claude] Browser tab crashed — failing agent
    00:34:41  [Gemini] Browser tab crashed — failing agent
    00:34:42  PHASE 2 COMPLETE: 1/3 agents finished
    00:34:43  [gate] cookie probe failed (… context or browser has been closed)   ← DEBUG
    00:34:44  NotebookLM upload error: BrowserContext.new_page: … has been closed
    00:49:44  Phase 3 active-time ceiling 15min hit — surfacing to user
    09:37:10  Command received: STOP                                   ← nine hours later

The sweep asked `page.is_closed()`, which is a question about ONE TAB. A whole
browser dying is indistinguishable from N independent tab crashes through that
lens, so it failed each agent, emptied `pending`, and let Phase 2 report
success at 1/3.

⭐ AND THE RECOVERY ALREADY EXISTED. `_plan_pipeline_auto_retry` +
`BROWSER_CRASH_MAX_RETRIES` silently relaunch Chrome and resume from the
checkpoint on exactly this failure. The sweep's own comment claimed "outer
run_pipeline.finally rebuilds the browser session and resumes from checkpoint"
— but setting `last_failure_kind` unwinds nothing, and it never raised. The
`--login` branch twenty lines above always got this right; so did Phase 3's
audio poll. Phase 2 — the longest phase, and the one most likely to be running
when Chrome dies — was the only one that did not.
"""
import asyncio

import pytest

import research
from conftest import code_only


CLOSED = "BrowserContext.cookies: Target page, context or browser has been closed"


class _Ctx:
    def __init__(self, dead: bool, exc: Exception | None = None):
        self.dead, self.exc = dead, exc
        self.asked = 0

    async def cookies(self):
        self.asked += 1
        if self.dead:
            raise (self.exc or Exception(CLOSED))
        return []


class _Browser:
    def __init__(self, ctx):
        self.context = ctx


def dead(exc=None):
    return _Browser(_Ctx(True, exc))


def alive():
    return _Browser(_Ctx(False))


# ── the probe ─────────────────────────────────────────────────────────────

def test_a_closed_context_is_recognised():
    """⛔ THE MISSING DISTINCTION. The live failure's own words."""
    assert asyncio.run(research._browser_context_is_dead(dead())) is True


def test_a_live_context_is_not():
    b = alive()
    assert asyncio.run(research._browser_context_is_dead(b)) is False
    assert b.context.asked == 1, "the probe must actually ask"


def test_a_missing_context_counts_as_dead():
    class _NoCtx:
        context = None
    assert asyncio.run(research._browser_context_is_dead(_NoCtx())) is True


@pytest.mark.parametrize("msg", [
    "BrowserContext.new_page: Target page, context or browser has been closed",
    "browser has been closed",
    "Page, context or browser has been closed",
])
def test_every_spelling_the_driver_uses(msg):
    assert asyncio.run(research._browser_context_is_dead(dead(Exception(msg)))) is True


def test_TargetClosedError_is_matched_by_its_TYPE_not_its_message():
    """⭐ The classifier matches `targetclosed` against the type name on
    purpose, so a future message-wording change in the driver still classifies.
    My first draft of this test asserted the message "Target closed" and failed
    — correctly: that string is NOT in the set, and only the type name is."""
    class TargetClosedError(Exception):
        pass
    assert asyncio.run(
        research._browser_context_is_dead(dead(TargetClosedError("anything at all")))) is True


def test_an_unrelated_error_does_NOT_read_as_a_dead_browser():
    """⛔⛔ FAILS SAFE TOWARDS ALIVE. A wrong True unwinds a HEALTHY run and
    relaunches Chrome underneath it; a wrong False costs only what today
    already costs. A transient network or permission error must not unwind."""
    for msg in ("net::ERR_INTERNET_DISCONNECTED", "Timeout 30000ms exceeded",
                "Permission denied", ""):
        assert asyncio.run(research._browser_context_is_dead(dead(Exception(msg)))) is False, msg


def test_the_probe_shares_the_classifier_rather_than_a_second_opinion():
    """Two string sets for "the browser went away" would drift, and the one
    that drifted would be the one nobody looked at."""
    assert "_is_browser_close_error" in code_only(research._browser_context_is_dead)


# ── the sweep, which is what actually failed ──────────────────────────────

def _sweep() -> str:
    """The phase-2 crash sweep, comments stripped."""
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("for _crash_name in list(pending.keys()):")
    return src[i:src.index("_crash_grew", i)]


def test_the_sweep_asks_whether_the_whole_browser_died():
    body = _sweep()
    assert "_browser_context_is_dead(browser)" in body


def test_and_RAISES_so_the_checkpoint_recovery_can_run():
    """⛔⛔ THE WHOLE DEFECT IN ONE ASSERTION. Setting `last_failure_kind`
    unwinds nothing — `run_pipeline`'s failure path is what calls
    `_plan_pipeline_auto_retry`, and it only runs if something raises. Without
    this the sweep sets the flag, deletes the agent, and lets Phase 2 report
    "COMPLETE: 1/3" on a browser that no longer exists."""
    body = _sweep()
    i = body.index("_browser_context_is_dead(browser)")
    assert "raise RuntimeError" in body[i:], body[i:i + 400]
    assert 'last_failure_kind = "browser_crash"' in body[i:]


def test_a_single_dead_tab_is_still_just_a_failed_agent():
    """⛔ THE NO-WIDENING GUARD, and the reason the probe is context-level. One
    tab crashing is a legitimate per-agent failure and must NOT unwind the run
    — that would turn a recoverable single-agent loss into a full relaunch."""
    body = _sweep()
    # The per-agent path still exists, after the context check.
    assert "Browser tab crashed — failing agent" in body
    assert body.index("_browser_context_is_dead(browser)") < body.index("Browser tab crashed")


def test_a_user_skip_is_still_not_a_crash():
    """#906 must survive: a tab WE closed on a Skip is not a browser death."""
    body = _sweep()
    assert "_controls.skipped_agents" in body
    assert body.index("_controls.skipped_agents") < body.index("_browser_context_is_dead(browser)")


def test_the_login_interrupt_still_wins():
    """#907 must survive and must be checked FIRST: --login kills Chrome on
    purpose, and that has its own honest card and its own resume path."""
    body = _sweep()
    assert body.index("_login_interrupt_active()") < body.index("_browser_context_is_dead(browser)")


# ── phase 3, which reported an upload failure about a dead browser ────────

def test_phase_three_classifies_a_dead_browser_before_blaming_the_upload(tmp_path, monkeypatch):
    """"We couldn't upload the reports to NotebookLM. Retry to try again" was
    said about a browser that no longer existed. Retry could not have worked.

    ⛔ FLIPPED FROM A SOURCE PIN TO AN EXECUTION (wave 10.9). This used to
    assert that `_is_browser_close_error(e)` appeared in the handler text. The
    handler now asks `_p3_upload_failure_kind`, which probes the context first,
    so that text is gone — and the pin could never tell "present" from
    "reachable" anyway. The property is driven for real instead: a dead context
    behind the incident's own error unwinds, and no upload card is raised."""
    md = tmp_path / "claude.md"
    md.write_text("x" * 200, encoding="utf-8")
    monkeypatch.setattr(research._runtime, "p2_links_for_p3", {"claude": "u"})
    monkeypatch.setattr(research._runtime, "p2_md_files_for_p3", [md])
    monkeypatch.setattr(research._runtime, "last_failure_kind", "")
    monkeypatch.setattr(research._controls, "skipped_agents", set())
    cards = []
    monkeypatch.setattr(research, "fail_phase", lambda *a, **k: cards.append(a))

    class _Dead(_Browser):
        async def new_tab(self, url):
            raise Exception("BrowserContext.new_page: Target page, context or browser has been closed")

    with pytest.raises(RuntimeError, match=r"\(browser crash\)"):
        asyncio.run(research.run_phase3_upload(_Dead(_Ctx(True)), None, {}, "t", tmp_path))
    assert research._runtime.last_failure_kind == "browser_crash"
    assert cards == [], "an upload card about a browser that no longer exists"


def test_the_cookie_gate_no_longer_buries_a_browser_death_at_debug():
    """It was the earliest honest signal in the run — one second ahead of
    Phase 3 — and it went out at a level the console does not show."""
    src = code_only(open(research.__file__, encoding="utf-8").read())
    i = src.index("cookie probe failed")
    window = src[max(0, i - 400):i + 400]
    assert "_is_browser_close_error(e)" in window
    assert '"WARN"' in window


# ── a Chrome window closed BY HAND in the middle of phase 2 (wave 10.9) ───

def test_a_hand_closed_chrome_window_mid_phase_two_relaunches_silently_and_keeps_the_finished_agents(
        tmp_path, monkeypatch):
    """⛔⛔ AN OWNER DECISION, PINNED SO THAT CHANGING IT MEANS FACING IT.

    A person closing the research Chrome window leaves no `.stop` and no
    `.pause`, and nothing at the CDP level tells a deliberate close from a
    segfault — so it takes the crash path: a SILENT relaunch that resumes from
    the checkpoint, up to BROWSER_CRASH_MAX_RETRIES times, then the card. That is
    the self-heal rule ("alert only when the user must act"), and it stays. (On
    macOS closing the window usually leaves Chrome alive, so this is mostly the
    Windows and Linux path, where the last window quits Chrome.)

    What made it expensive was not the relaunch but what the relaunch did: it
    bought every finished Deep Research again. So the pin runs on in to the
    relaunch's own plan — the agent that finished is kept, the rest launch.

    ⚠ The budget belongs to the RELAUNCHES (resume_dir set). The first failure
    always gets its one shot whatever the counter says, so the spent-budget case
    is asked the way the recursion asks it."""
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: False)
    q = tmp_path / "run"
    (q / "documents").mkdir(parents=True)
    (q / "documents" / "brief.md").write_text("# Research Brief\n\n" + "b" * 200,
                                              encoding="utf-8")
    (q / "documents" / "chatgpt.md").write_text("# ChatGPT Deep Research\n\n" + "c" * 400,
                                                encoding="utf-8")
    research._p2_mark_agent_done(q, "chatgpt", True, elapsed_sec=600)

    # The window closes mid-phase-2: no sentinel, no delivery status.
    assert research._plan_pipeline_auto_retry(q, None, "browser_crash", 0) == (True, 2, True)
    # …and the silent relaunch buys only the agents that had not finished.
    launch, kept = research._p2_resume_plan(q, ["chatgpt", "gemini", "claude"])
    assert launch == ["gemini", "claude"]
    assert list(kept) == ["ChatGPT"] and kept["ChatGPT"]["status"] == "done"
    # One close short of the budget still relaunches silently…
    assert research._plan_pipeline_auto_retry(
        q, str(q), "browser_crash", research.BROWSER_CRASH_MAX_RETRIES - 1) == (True, 2, True)
    # …and once it is spent, the next close puts the card in front of them.
    assert research._plan_pipeline_auto_retry(
        q, str(q), "browser_crash", research.BROWSER_CRASH_MAX_RETRIES)[0] is False
