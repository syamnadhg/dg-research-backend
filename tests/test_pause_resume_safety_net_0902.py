"""STRETCH 7.5 STEP 1 — THE SAFETY NET. No product change; this file only executes.

⛔⛔ WHY THIS FILE EXISTS AT ALL, AND WHY IT IS STEP 1

The conversation URL that stretch 7.5 is removing from every DISPLAY and DELIVERY surface is
*also*, quietly, the **pause/resume reattachment key**. On pause every still-running agent's live
URL is written into `checkpoint_pause.json`; on resume the tab is re-opened AT THAT URL. Take the
URL away and you do not lose a link — **you lose an AGENT**, because the round-robin's per-tick
browser-crash sweep classifies a `None` page as a crashed tab (`research.py:38584`,
`page is None or page.is_closed()`), and the user is told the browser crashed.

Before this file, `pause_and_close_browser`, `resume_browser_from_checkpoint`,
`save_pause_checkpoint` and `load_pause_checkpoint` had **ZERO test references anywhere in the
repo** — measured 2026-09-02, backend + agent + tests. So that break would have stayed green.

⚠ HONEST LIMIT OF THIS NET. The crash-sweep tick itself lives inside `poll_all_agents_round_robin`,
which the codebase says a test cannot drive (see the docstring of `_autoskip_reason_for_status`,
`research.py:50206`). This file therefore pins the reattachment chain up to and including
"the agent came back with no page and nothing told anyone" — the *input* the sweep then reads. It
does not execute the sweep. That linkage gets its cover when step 5 edits that loop.

WHAT IS PINNED HERE — all by EXECUTION, none by reading source as text:
  A  pause writes the reconnect key to disk, closes the browser, drops the dead page handles
  B  pause genuinely BLOCKS and is released by resume — and by stop
  C  the reattachment both ways round — from the live dict (the path production
     actually runs) AND from disk alone once memory is cleared. ⭐ Measured while
     writing this: `resume_browser_from_checkpoint` has exactly ONE caller
     (research.py:38701), in the same coroutine that paused, so the live
     `_runtime.agent_chat_urls` is the primary key and the file is the belt.
  D  ⛔⛔ an agent with NO url is silently NOT reattached — the headline break
  E  one bad leg does not take the others: session expiry fails just that agent, loudly
  F  a reopen that throws does not take the others either
  G  the research -> podcast crossing, and that it keys on the links file's EXISTENCE
  H  the whole thing end to end: pause in phase 2, resume, hand off into phase 3

Run:  pytest tests/test_pause_resume_safety_net_0902.py -v
"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


# ── Doubles that match the real browser's contract ──────────────────────
# Real shapes: `Browser.start()` research.py:33091 · `new_tab(url=None)` :33613 ·
# `close()` :33660 · `.context` truthy while a session is live.

class _FakePage:
    def __init__(self, url):
        self.url = url
        self._closed = False

    def is_closed(self):
        return self._closed


class _FakeBrowser:
    def __init__(self, *, raise_for=()):
        self.context = object()
        self.started = 0
        self.closed = 0
        self.opened = []           # every URL new_tab was asked for, in order
        self._raise_for = set(raise_for)

    async def start(self):
        self.started += 1
        self.context = object()

    async def close(self):
        self.closed += 1
        self.context = None

    async def new_tab(self, url=None):
        self.opened.append(url)
        if url in self._raise_for:
            raise RuntimeError("Target page, context or browser has been closed")
        return _FakePage(url)


CHATGPT_URL = "https://chatgpt.com/c/68b1a0f0-1111-2222-3333-444455556666"
GEMINI_URL = "https://gemini.google.com/app/9f41418747cf4a36"
CLAUDE_URL = "https://claude.ai/chat/aaaa1111-bbbb-2222-cccc-333344445555"


@pytest.fixture(autouse=True)
def _clean_runtime_and_controls(monkeypatch):
    """`_runtime` and `_controls` are module singletons — a leaked URL or a set
    pause event would make the next test lie. Reset both ends of every test."""
    research._runtime.reset()
    research._controls.reset()
    # ⚠ HARNESS, NOT PRODUCT. `_controls` is a module singleton and its three
    # asyncio.Events bind to the first loop that AWAITS them; `reset()` clears
    # them without rebinding. pytest-asyncio hands every test a fresh loop, so
    # a second awaiting test would find the events bound to the dead one and
    # `asyncio.wait` would return instantly — a pause that never paused, which
    # would fake a pass. Rebinding here reproduces what a fresh process gets.
    # ⭐ Measured, so it is not a lurking product defect: `--serve` runs ONE
    # `asyncio.run` for the whole process (research.py:75947) and the CLI one
    # per process, so production never has a second loop to be bound to.
    research._controls.stop_event = asyncio.Event()
    research._controls.pause_event = asyncio.Event()
    research._controls.resume_event = asyncio.Event()
    monkeypatch.setattr(research, "_cli_mode", False)
    # The resume path sleeps 3s per reopened tab (research.py:19969).
    _real_sleep = asyncio.sleep

    async def _fast_sleep(_secs, *a, **kw):
        return await _real_sleep(0)

    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)
    yield
    research._runtime.reset()
    research._controls.reset()


@pytest.fixture
def events(monkeypatch):
    """Record what the real pause/resume functions emit."""
    seen = []
    monkeypatch.setattr(research, "emit_event",
                        lambda kind, **kw: seen.append((kind, kw)))
    return seen


@pytest.fixture
def failed(monkeypatch):
    """Record fail_agent calls — the only loud channel the resume path has."""
    seen = []
    monkeypatch.setattr(research, "fail_agent",
                        lambda key, title, details="", **kw: seen.append((key, title)))
    return seen


@pytest.fixture
def authed(monkeypatch):
    """`check_auth` does real DOM work. Default: everyone is signed in."""
    async def _ok(_page, _platform):
        return True
    monkeypatch.setattr(research, "check_auth", _ok)
    return _ok


def _two_live_agents_and_one_done():
    """The state a real phase-2 pause leaves behind (research.py:38668-38679)."""
    research._runtime.phase = 2
    research._runtime.sub_state = "2_parallel_polling"
    research._runtime.agent_chat_urls = {
        "chatgpt": CHATGPT_URL,
        "gemini": GEMINI_URL,
        "claude": CLAUDE_URL,
    }
    research._runtime.agent_statuses = {
        "chatgpt": "generating",
        "gemini": "generating",
        "claude": "done",
    }
    research._runtime.original_inputs = {"topic": "quantum error correction", "brief": "x" * 400}
    research._runtime.active_pages = {
        "chatgpt": _FakePage(CHATGPT_URL),
        "gemini": _FakePage(GEMINI_URL),
    }


# ── A · PAUSE WRITES THE RECONNECT KEY TO DISK ──────────────────────────

@pytest.mark.asyncio
async def test_pause_writes_every_live_agents_url_into_the_checkpoint(tmp_path, events):
    _two_live_agents_and_one_done()
    browser = _FakeBrowser()

    stopped = await research.pause_and_close_browser(browser, tmp_path, phase=2)

    assert stopped is False
    cp = json.loads((tmp_path / "checkpoint_pause.json").read_text(encoding="utf-8"))
    # ⛔ THE RECONNECT KEY. If a change makes these empty, resume has nowhere to go.
    assert cp["agent_chat_urls"]["chatgpt"] == CHATGPT_URL
    assert cp["agent_chat_urls"]["gemini"] == GEMINI_URL
    assert cp["paused"] is True
    assert cp["phase"] == 2
    assert cp["sub_state"] == "2_parallel_polling"
    assert cp["original_inputs"]["topic"] == "quantum error correction"


@pytest.mark.asyncio
async def test_pause_closes_the_browser_and_drops_the_dead_page_handles(tmp_path, events):
    _two_live_agents_and_one_done()
    browser = _FakeBrowser()

    await research.pause_and_close_browser(browser, tmp_path, phase=2)

    assert browser.closed == 1
    # Page objects are dead once the context closes; keeping them would hand a
    # zombie handle to the crash sweep.
    assert research._runtime.active_pages == {}
    # The URLs, by contrast, MUST survive in memory as well as on disk.
    assert research._runtime.agent_chat_urls["chatgpt"] == CHATGPT_URL


@pytest.mark.asyncio
async def test_the_paused_event_does_NOT_carry_the_reconnect_key(tmp_path, events):
    """⛔⛔ 2026-09-02, stretch 7.5 step 5 — THIS TEST USED TO ASSERT THE OPPOSITE,
    AND ITS NAME WAS ITS OWN REFUTATION. It was called "…carries the urls so the
    app can show the run" and ended `assert payload["snapshot"]["agent_chat_urls"]
    ["gemini"] == GEMINI_URL`. The app shows nothing from that payload: its only
    `pipeline_paused` handler reads no field of it at all.

    ⛔ What DID read it was a model. Every emitted event is persisted to
    Firestore for thirty days, and the follow-up chat's recent-events tool hands
    whole event documents to the model, filtering only progress noise — so all
    three private conversation addresses went into a model's context on any
    paused run. Step 2 closed the links-array channel into that same context;
    this was the same three addresses arriving by the other door.

    ⭐ The guard is inverted rather than deleted, because "the app is not told"
    is a promise that needs keeping, not an absence of a promise."""
    _two_live_agents_and_one_done()

    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    kinds = [k for k, _ in events]
    assert "pipeline_paused" in kinds
    payload = dict(events[kinds.index("pipeline_paused")][1])
    assert payload["phase"] == 2
    snap = payload["snapshot"]
    assert "agent_chat_urls" not in snap
    # ⛔ THE UNIVERSAL, not the one key: no value anywhere in the streamed payload
    # may be one of the addresses, however it got there.
    flat = json.dumps(payload)
    for url in (CHATGPT_URL, GEMINI_URL):
        assert url not in flat, url


@pytest.mark.asyncio
async def test_the_paused_event_still_says_what_the_app_actually_uses(tmp_path, events):
    """The other half: stripping one field must not empty the payload. Phase and
    per-agent status are what a resumed run and any future reader need."""
    _two_live_agents_and_one_done()

    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    kinds = [k for k, _ in events]
    snap = dict(events[kinds.index("pipeline_paused")][1])["snapshot"]
    assert snap["phase"] == 2
    assert snap["agent_statuses"]["gemini"] == "generating"
    assert snap["agent_statuses"]["claude"] == "done"


@pytest.mark.asyncio
async def test_the_checkpoint_keeps_what_the_event_dropped(tmp_path, events):
    """⛔⛔ THE PAIR THAT MAKES THE STRIP SAFE, ASSERTED IN ONE PLACE. The same
    pause writes both, and they must disagree: the disk keeps the reconnect key
    (without it a restored agent comes back with no page and the next poll tick's
    crash sweep deletes it from the run), the wire does not. Stripping inside
    `snapshot()` would have satisfied the test above and cost an agent on every
    resume."""
    _two_live_agents_and_one_done()

    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    cp = research.load_pause_checkpoint(tmp_path)
    assert cp["agent_chat_urls"]["gemini"] == GEMINI_URL
    assert cp["agent_chat_urls"]["chatgpt"] == CHATGPT_URL
    kinds = [k for k, _ in events]
    streamed = dict(events[kinds.index("pipeline_paused")][1])["snapshot"]
    assert "agent_chat_urls" not in streamed


@pytest.mark.asyncio
async def test_pause_with_no_queue_dir_writes_nothing_but_still_closes_the_browser(tmp_path, events):
    """The silent bug the comment at research.py:38681-38687 describes: the
    phase-2 site once passed a run NAME instead of the queue dir, so the write
    landed relative to cwd. `save_pause_checkpoint` no-ops on a falsy dir —
    pin that the BROWSER still closes, so a bad dir costs the checkpoint and
    not the machine's memory."""
    _two_live_agents_and_one_done()
    browser = _FakeBrowser()

    stopped = await research.pause_and_close_browser(browser, None, phase=2)

    assert stopped is False
    assert browser.closed == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_pause_survives_a_browser_that_is_already_gone(tmp_path, events):
    """Phase 0 passes `browser=None`, and a crash-then-pause race passes one
    whose context is already None. Neither may lose the checkpoint."""
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(None, tmp_path, phase=1)
    assert (tmp_path / "checkpoint_pause.json").exists()

    (tmp_path / "checkpoint_pause.json").unlink()
    dead = _FakeBrowser()
    dead.context = None
    await research.pause_and_close_browser(dead, tmp_path, phase=1)
    assert (tmp_path / "checkpoint_pause.json").exists()
    assert dead.closed == 0  # nothing to close; must not raise trying


# ── B · PAUSE GENUINELY BLOCKS, AND RESUME RELEASES IT ──────────────────

@pytest.mark.asyncio
async def test_pause_blocks_until_the_user_resumes(tmp_path, events):
    """Not "the flag is set" — the coroutine must actually be parked. Proven by
    the pause returning ONLY after another task calls request_resume()."""
    _two_live_agents_and_one_done()
    research._controls.request_pause("test-pause")
    released = []

    async def _resume_after_a_tick():
        for _ in range(3):
            await asyncio.sleep(0)
        released.append("resumed")
        research._controls.request_resume()

    task = asyncio.create_task(_resume_after_a_tick())
    stopped = await asyncio.wait_for(
        research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2), timeout=10)
    await task

    assert released == ["resumed"], "the pause returned before anything resumed it"
    assert stopped is False
    assert research._controls.is_pause() is False


@pytest.mark.asyncio
async def test_a_stop_during_the_pause_reports_stopped_not_resumed(tmp_path, events):
    _two_live_agents_and_one_done()
    research._controls.request_pause("test-pause")

    async def _stop_after_a_tick():
        for _ in range(3):
            await asyncio.sleep(0)
        research._controls.request_stop()

    task = asyncio.create_task(_stop_after_a_tick())
    stopped = await asyncio.wait_for(
        research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2), timeout=10)
    await task

    # The caller returns early on True — a stopped run must not walk into resume.
    assert stopped is True


# ── C · THE REATTACHMENT, BOTH WAYS ROUND ──────────────────────────────
# ⭐ MEASURED, because it changes what "the reconnect key" means:
# `resume_browser_from_checkpoint` has exactly ONE caller — research.py:38701,
# inside the same coroutine that paused. So in production the LIVE dict
# `_runtime.agent_chat_urls` is the primary key and `checkpoint_pause.json` is
# the belt. Both are pinned here: the same-memory path because it is the one
# production runs, and the disk round trip because it is what is left if the
# in-memory copy is ever cleared.


@pytest.mark.asyncio
async def test_the_production_path_reattaches_from_memory_with_the_file_as_a_belt(
        tmp_path, events, authed, failed):
    """Pause and resume with nothing cleared in between — the real shape."""
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert sorted(restored) == ["chatgpt", "gemini"]
    assert sorted(browser.opened) == sorted([CHATGPT_URL, GEMINI_URL])
    assert [k for k, _ in failed] == []


@pytest.mark.asyncio
async def test_a_missing_checkpoint_must_not_wipe_the_live_reattachment_keys(
        tmp_path, events, authed):
    """⛔ The restore only runs `if cp:` — and that guard is load-bearing. Read
    the file unconditionally and a resume with no checkpoint on disk (a cleared
    file, a bad queue dir, a pause that failed to write) would overwrite the
    live URLs with an empty dict and lose every agent that was still running."""
    _two_live_agents_and_one_done()
    assert not (tmp_path / "checkpoint_pause.json").exists()

    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert sorted(restored) == ["chatgpt", "gemini"]
    assert sorted(browser.opened) == sorted([CHATGPT_URL, GEMINI_URL])

@pytest.mark.asyncio
async def test_resume_reopens_exactly_the_saved_urls_after_memory_is_lost(tmp_path, events, authed):
    """The real hazard is a fresh process (or `_runtime.reset()`) — so the disk
    file has to be sufficient on its own."""
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    research._runtime.reset()                      # everything in memory is gone
    assert research._runtime.agent_chat_urls == {}

    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert browser.started == 1
    # Exactly the two live agents, at exactly their own URLs. Not a superset.
    assert sorted(browser.opened) == sorted([CHATGPT_URL, GEMINI_URL])
    assert sorted(restored) == ["chatgpt", "gemini"]
    assert restored["chatgpt"].url == CHATGPT_URL
    # Restored pages are re-registered so the poll loop can find them again.
    assert research._runtime.active_pages["gemini"].url == GEMINI_URL
    # And the phase came back with them, or the run resumes in the wrong place.
    assert research._runtime.phase == 2
    assert research._runtime.sub_state == "2_parallel_polling"
    assert research._runtime.original_inputs["topic"] == "quantum error correction"


@pytest.mark.asyncio
async def test_a_second_pause_wins_so_a_resume_never_reattaches_to_a_stale_url(
        tmp_path, events, authed):
    """⛔⛔ A conversation URL captured EARLIER can be the wrong one now — both
    ChatGPT and Gemini rewrite the address once the first answer lands, and the
    mid-poll pause branch re-reads `page.url` every time it pauses
    (research.py:38670-38676). So the newest pause has to win outright. If the
    checkpoint were ever reused instead of rebuilt, a resume would reopen the
    address the agent had at the FIRST pause — a stale conversation, which is
    the exact class of failure this whole stretch is about."""
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    moved = GEMINI_URL + "?after-the-first-answer"
    research._runtime.agent_chat_urls["gemini"] = moved
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)

    research._runtime.reset()
    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert GEMINI_URL not in browser.opened, "reattached to the URL from the FIRST pause"
    assert moved in browser.opened
    assert restored["gemini"].url == moved


@pytest.mark.asyncio
async def test_resume_does_not_reopen_an_agent_that_already_finished(tmp_path, events, authed):
    """Claude was `done` at pause time. Reopening it would re-poll a finished
    leg and could overwrite a report that is already on disk."""
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()

    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert CLAUDE_URL not in browser.opened
    assert "claude" not in restored


@pytest.mark.asyncio
async def test_resume_clears_the_checkpoint_so_a_later_crash_cannot_replay_it(tmp_path, events, authed):
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()

    await research.resume_browser_from_checkpoint(_FakeBrowser(), tmp_path)

    assert not (tmp_path / "checkpoint_pause.json").exists()


@pytest.mark.asyncio
async def test_the_resumed_event_names_the_agents_that_actually_came_back(tmp_path, events, authed):
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()
    events.clear()

    await research.resume_browser_from_checkpoint(_FakeBrowser(), tmp_path)

    kinds = [k for k, _ in events]
    assert "pipeline_resumed" in kinds
    payload = dict(events[kinds.index("pipeline_resumed")][1])
    assert sorted(payload["restored"]) == ["chatgpt", "gemini"]
    assert payload["phase"] == 2


@pytest.mark.asyncio
async def test_resume_with_no_checkpoint_on_disk_restores_nobody_and_does_not_raise(tmp_path, events, authed):
    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)
    assert restored == {}
    assert browser.opened == []
    assert browser.started == 1


# ── D · ⛔⛔ THE HEADLINE: NO URL MEANS NO AGENT, SILENTLY ───────────────

@pytest.mark.asyncio
async def test_an_agent_with_no_saved_url_is_not_reattached_at_all(tmp_path, events, authed, failed):
    """⛔⛔ THIS IS THE BREAK STRETCH 7.5 COULD SHIP.

    Remove the conversation-URL capture as "a display sink" and this is what
    happens: the leg is still `generating`, so the run still expects a report
    from it — but resume opens no tab for it, registers no page, and says
    nothing to anybody. The next poll tick reads its `None` page as a crashed
    tab (research.py:38584) and the user is told the browser crashed.
    """
    _two_live_agents_and_one_done()
    research._runtime.agent_chat_urls["gemini"] = ""      # the URL never got captured
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()

    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert browser.opened == [CHATGPT_URL], "a tab was opened for an agent with no URL"
    assert "gemini" not in restored
    assert "gemini" not in research._runtime.active_pages
    # ⛔ AND IT IS SILENT. Nothing failed it, nothing warned the user — which is
    # why the crash sweep is what eventually speaks, with the wrong story.
    assert [k for k, _ in failed] == []
    # The healthy leg is unaffected — the loss is exactly one agent.
    assert restored["chatgpt"].url == CHATGPT_URL


@pytest.mark.asyncio
async def test_a_checkpoint_with_no_urls_at_all_reattaches_nothing(tmp_path, events, authed):
    """The whole-run version of the same break: every URL gone, so a resume
    brings the browser up and reattaches nobody."""
    research._runtime.phase = 2
    research._runtime.agent_chat_urls = {"chatgpt": "", "gemini": "", "claude": ""}
    research._runtime.agent_statuses = {"chatgpt": "generating", "gemini": "generating",
                                        "claude": "generating"}
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()

    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert restored == {}
    assert browser.opened == []
    assert browser.started == 1      # the browser came up; there was just nowhere to go


# ── E/F · ONE BAD LEG DOES NOT TAKE THE OTHERS ──────────────────────────

@pytest.mark.asyncio
async def test_a_signed_out_agent_is_failed_loudly_and_the_others_still_come_back(
        tmp_path, events, failed, monkeypatch):
    async def _auth(_page, platform):
        if platform == "gemini":
            raise research.SessionExpiredError("Gemini signed out")
        return True
    monkeypatch.setattr(research, "check_auth", _auth)

    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()

    restored = await research.resume_browser_from_checkpoint(_FakeBrowser(), tmp_path)

    assert "gemini" not in restored
    assert [k for k, _ in failed] == ["gemini"]        # loud, unlike case D
    assert "chatgpt" in restored


@pytest.mark.asyncio
async def test_a_tab_that_refuses_to_open_costs_one_agent_not_the_resume(
        tmp_path, events, authed, failed):
    _two_live_agents_and_one_done()
    await research.pause_and_close_browser(_FakeBrowser(), tmp_path, phase=2)
    research._runtime.reset()

    browser = _FakeBrowser(raise_for=[CHATGPT_URL])
    restored = await research.resume_browser_from_checkpoint(browser, tmp_path)

    assert "chatgpt" not in restored
    assert "gemini" in restored                        # the resume kept going
    assert CHATGPT_URL in browser.opened               # it did try


# ── G · THE RESEARCH -> PODCAST CROSSING ────────────────────────────────

def _run_dir(tmp_path, name, *, brief=False, links=None, marker=False,
             audio=False, youtube=False, delivery=None, partial_md=False):
    q = tmp_path / name
    (q / "documents").mkdir(parents=True, exist_ok=True)
    if brief:
        (q / "documents" / "brief.md").write_text("# Brief\n" + "x" * 300, encoding="utf-8")
    if partial_md:
        (q / "documents" / "chatgpt.md").write_text("# Report\n" + "y" * 500, encoding="utf-8")
    if links is not None:
        (q / "links.json").write_text(json.dumps(links), encoding="utf-8")
    if marker:
        (q / "phase2_complete.marker").write_text("", encoding="utf-8")
    if audio:
        (q / "podcasts").mkdir(exist_ok=True)
        (q / "podcasts" / "episode.mp3").write_text("ID3", encoding="utf-8")
    if youtube:
        (q / "checkpoint.json").write_text(
            json.dumps({"youtube_url": "https://youtu.be/abc"}), encoding="utf-8")
    if delivery is not None:
        (q / "delivery.json").write_text(json.dumps({"status": delivery}), encoding="utf-8")
    return q


def test_the_links_file_hands_the_run_over_to_the_podcast_phase(tmp_path):
    q = _run_dir(tmp_path, "handoff", brief=True, links={"notebook": "https://notebook.google.com/x"})
    phase, why = research.detect_resume_phase(q)
    assert phase == 3, why


def test_an_EMPTY_links_file_still_hands_the_run_over(tmp_path):
    """⛔ THE ONE STEP 5 MUST NOT MISS: the hand-off reads the file's EXISTENCE,
    never its contents. So emptying it is safe and deleting the WRITE is not —
    that drops the run back into phase 2 for a full research restart."""
    q = _run_dir(tmp_path, "empty-links", brief=True, links={})
    assert research.detect_resume_phase(q)[0] == 3


def test_removing_the_links_write_costs_a_whole_phase_when_the_marker_is_absent(tmp_path):
    """Flow B/C runs never write the phase-2 marker. With the links file gone
    too, a resumed run re-runs phase 2 from scratch — the measured cost of
    deleting the write instead of emptying the file."""
    q = _run_dir(tmp_path, "no-links-no-marker", brief=True, partial_md=True)
    phase, why = research.detect_resume_phase(q)
    assert phase == 2, why


def test_the_phase2_marker_alone_also_hands_over(tmp_path):
    """The second, independent hand-off signal — so a replacement for the links
    file has somewhere to live."""
    q = _run_dir(tmp_path, "marker-only", brief=True, marker=True)
    assert research.detect_resume_phase(q)[0] == 3


def test_a_finished_podcast_carries_the_run_past_phase_3(tmp_path):
    q = _run_dir(tmp_path, "audio-done", brief=True, links={"notebook": "u"}, audio=True)
    assert research.detect_resume_phase(q)[0] == 4


def test_a_published_video_and_a_completed_delivery_are_both_terminal(tmp_path):
    q = _run_dir(tmp_path, "yt-done", brief=True, links={"notebook": "u"}, youtube=True)
    assert research.detect_resume_phase(q)[0] == 5
    done = _run_dir(tmp_path, "all-done", delivery="completed")
    assert research.detect_resume_phase(done)[0] == 6


# ── H · THE WHOLE THING, END TO END ─────────────────────────────────────

@pytest.mark.asyncio
async def test_pause_in_research_resume_reattach_then_hand_off_to_the_podcast(
        tmp_path, events, authed, failed):
    """⭐ THE ONE TEST THE STRETCH IS BUILT ON: a run pauses mid-research with
    two live agents, loses every scrap of in-memory state, comes back attached
    to the same two conversations, finishes phase 2, and hands over to the
    podcast phase.

    Every product function here is the real one: `pause_and_close_browser`,
    `save_pause_checkpoint`, `load_pause_checkpoint`, `resume_browser_from_checkpoint`,
    `detect_resume_phase`.
    """
    q = _run_dir(tmp_path, "e2e", brief=True)
    _two_live_agents_and_one_done()

    # 1 · the user hits Pause mid-phase-2
    research._controls.request_pause("user paused")

    async def _resume_shortly():
        for _ in range(3):
            await asyncio.sleep(0)
        research._controls.request_resume()

    task = asyncio.create_task(_resume_shortly())
    stopped = await asyncio.wait_for(
        research.pause_and_close_browser(_FakeBrowser(), q, phase=2), timeout=10)
    await task
    assert stopped is False
    # Mid-pause, the run is recoverable from disk alone.
    assert research.load_pause_checkpoint(q)["agent_chat_urls"]["chatgpt"] == CHATGPT_URL
    # And the on-disk state still says "research", because phase 2 is unfinished.
    assert research.detect_resume_phase(q)[0] == 2

    # 2 · the process forgets everything, then resumes
    research._runtime.reset()
    browser = _FakeBrowser()
    restored = await research.resume_browser_from_checkpoint(browser, q)
    assert sorted(restored) == ["chatgpt", "gemini"]
    assert sorted(browser.opened) == sorted([CHATGPT_URL, GEMINI_URL])
    assert [k for k, _ in failed] == []

    # 3 · phase 2 finishes and writes its hand-off signal
    (q / "links.json").write_text(json.dumps({"notebook": "https://notebook.google.com/x"}),
                                  encoding="utf-8")

    # 4 · the run is now a podcast run
    phase, why = research.detect_resume_phase(q)
    assert phase == 3, why
