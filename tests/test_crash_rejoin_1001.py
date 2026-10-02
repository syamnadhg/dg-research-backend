"""A browser crash in Phase 2 goes back into each agent's own chat (10-01).

⛔⛔ THE 09-30 EVENING RUN. At 18:33:45 Chrome crashed with ChatGPT's report
finished on its page and Claude and Gemini researching. The crash retry
("auto-retrying from checkpoint") then set all three up again and sent the brief
three more times (`…_retry1/run.log`: 2A, 2B and 2C all over again), throwing
away seventeen minutes of three Deep Researches. The wave 10.9 record keeps an
agent only once its report is EXTRACTED, and ChatGPT's extraction was exactly
what the crash interrupted.

⭐ WHAT IS DRIVEN HERE.
  * the REAL `run_pipeline`, crashed in Phase 2 with this run's chats in
    `_runtime`: its own retry is handed those chats, the three-attempt cap still
    ends it with the card, and no other failure carries anything;
  * the retry's Phase 2 — the REAL `_p2_run_with_resume` and `run_phase2`, the
    attempt runner shaped as `run_pipeline`'s own `_p2_attempt` (the wiring of
    that closure is pinned by AST at the bottom, as the 10.9 suite pins its
    neighbours): each chat is opened, proved, and handed to the round-robin;
    nothing is sent the brief again; an agent with no chat, or one whose chat
    cannot be opened or proved, is set up the usual way — only that one;
  * the notes Phase 2 takes as each agent is sent the brief, at the launch
    sites themselves.
Only the edges are stubbed: Chrome, the pages' readers, the round-robin.
"""
import ast
import asyncio
import inspect
import textwrap

import pytest

import research
from _domshim import NODE, el, run_js


ALL = ["chatgpt", "gemini", "claude"]

# The three chats of the 09-30 evening run (run.log, 18:21:36).
CG_URL = "https://chatgpt.com/c/6abdb44f-8908-83ea-a52a-620821c03ae9"
CL_URL = "https://claude.ai/chat/4d24eb39-f33d-41ac-a659-9e89c477701f"
GM_URL = "https://gemini.google.com/app/e91e413e201fee2a"
CHATS = {"chatgpt": CG_URL, "claude": CL_URL, "gemini": GM_URL}

# What a fresh set-up would land on instead.
NEW_CG = "https://chatgpt.com/c/6abdb8d7-c264-83e9-994e-2a94839dc3d3"
NEW_CL = "https://claude.ai/chat/99999999-aaaa-4bbb-8ccc-dddddddddddd"

#: When the 09-30 evening run began: its folder's own stamp, 18:09:08 Pacific —
#: 411 s before ChatGPT's chat id (hex seconds) was minted at 18:15:59. Pinned as
#: an instant, so the dating does not move with the machine's time zone.
RUN_START = int("6abdb44f", 16) - 411
#: The previous evening's research chat in the same account: one day older.
OLD_CG = f"https://chatgpt.com/c/{int('6abdb44f', 16) - 86400:08x}-1111-82aa-b3cc-0123456789ab"
OLD_CL = "https://claude.ai/chat/0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"

BRIEF = ("# Research Brief\n\n## Objective\nSaint Bernard breed health, longevity, "
         "working history and rescue lineage across alpine hospices, kennel clubs "
         "and veterinary registries.\n\n## Scope\nCanine cardiology, hip dysplasia, "
         "bloat, lifespan tables.\n")

#: The line typed beside an attached brief, as the chat shows it — written out
#: rather than read off the constant, so a change to the words is a change here.
ASK_TURN = ("Please perform deep research on the topic described in the attached "
            "brief. Use the brief as the complete context — objectives, scope, "
            "sections, sources to target. Produce a comprehensive research report. "
            "Cite primary and authoritative sources inline with links, and list "
            "them at the end.")
FOREIGN_TURN = ("Write me a packing list for a week of hiking in the Dolomites in "
                "late September, with layers for cold mornings and warm afternoons.")


# ── doubles ───────────────────────────────────────────────────────────────────

class _Page:
    def __init__(self, url, turn="", *, done=False, started=True, ours=True,
                 signed_out=False):
        self.url = url
        self.turn = turn
        self.done = done
        self.started = started
        self.ours = ours
        self.signed_out = signed_out
        self.closed = False

    async def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed

    async def evaluate(self, *_a, **_k):
        return None

    async def bring_to_front(self):
        return None


class _Browser:
    """`open_isolated_tab(url)` hands back the page that address LANDS on.

    `context` answers the dead-browser probe: a bare object reads as a live
    Chrome (its cookie read fails with an error that is not a close)."""

    def __init__(self, lands=None, refuse=(), error=None, context=None):
        self.page = None
        self.context = context if context is not None else object()
        self.opened = []
        self.lands = dict(lands or {})
        self.refuse = set(refuse)
        self.error = error or (lambda _url: RuntimeError(
            "Target page, context or browser has been closed"))

    async def open_isolated_tab(self, url=None):
        self.opened.append(url)
        if url in self.refuse:
            raise self.error(url)
        return self.lands.get(url) or _Page(url)


class _DeadContext:
    """The context of a Chrome that has died: its cookie read says so."""

    async def cookies(self):
        raise RuntimeError("BrowserContext.cookies: Target page, context or browser "
                           "has been closed")

    async def switch_to_page(self, page):
        self.page = page


def _lands(**over):
    """The three chats, each landing on itself and holding this run's send."""
    lands = {CG_URL: _Page(CG_URL, ASK_TURN, done=True),
             CL_URL: _Page(CL_URL, ASK_TURN, done=False),
             GM_URL: _Page(GM_URL, started=True)}
    lands.update(over)
    return lands


class _Launched(Exception):
    """Gemini's set-up was reached — the test stops there, before the plan wait."""


class _Soft(Exception):
    def __init__(self, decision):
        super().__init__(decision)
        self.decision = decision


@pytest.fixture
def p2(monkeypatch, tmp_path):
    """The retry's Phase 2, run for real down to the round-robin."""
    q = tmp_path / "St_Bernard_20260930_180908"
    (q / "documents").mkdir(parents=True)
    research._runtime.reset()
    research._controls.reset()
    monkeypatch.setattr(research._controls, "pro_warning_acknowledged", True)
    ns = type("P2", (), {})()
    ns.q = q
    ns.logs, ns.events, ns.launched, ns.polled = [], [], [], []
    ns.statuses = []

    monkeypatch.setattr(research, "log", lambda msg, *a, **k: ns.logs.append(str(msg)))
    monkeypatch.setattr(research, "emit_event",
                        lambda kind, **kw: ns.events.append((kind, kw)))
    monkeypatch.setattr(research, "_write_agent_terminal_status",
                        lambda key, status, **k: ns.statuses.append((key, status)))
    monkeypatch.setattr(research, "_p2_run_dir", lambda: q)
    monkeypatch.setattr(research, "_run_start_epoch", lambda: RUN_START)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")
    _real_sleep = asyncio.sleep

    async def _fast_sleep(*_a, **_k):
        return await _real_sleep(0)
    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)

    async def _auth(page, platform):
        if getattr(page, "signed_out", False):
            raise research.SessionExpiredError(f"{platform} session expired")
        return True
    monkeypatch.setattr(research, "check_auth", _auth)

    # Each platform's reader reads only its own platform's page, so a chat read
    # with the other platform's reader reads as nothing.
    async def _cg_turn(page, *a, **k):
        return getattr(page, "turn", "") if "chatgpt.com" in page.url else ""

    async def _cl_turn(page, *a, **k):
        return getattr(page, "turn", "") if "claude.ai" in page.url else ""
    monkeypatch.setattr(research, "read_chatgpt_first_user_message", _cg_turn)
    # raising=False: so that against the code before this fix the tests below FAIL
    # on what the retry does, rather than error in this fixture.
    monkeypatch.setattr(research, "_claude_first_user_message", _cl_turn, raising=False)

    async def _detect(page, **_k):
        return (bool(getattr(page, "done", False)), "probe", {})
    monkeypatch.setitem(research.DETECT_FNS, "ChatGPT", _detect)
    monkeypatch.setitem(research.DETECT_FNS, "Claude", _detect)

    async def _gm_ident(page, convo_id, pasted_text, **_k):
        return (bool(getattr(page, "ours", False))
                and research._gemini_convo_url_id(page.url) == convo_id
                and pasted_text == ns.brief_seen)
    monkeypatch.setattr(research, "_gemini_reload_identity_ok", _gm_ident)
    ns.adoptions = []
    ns.adopt_to = None
    ns.adopt_raises = None

    async def _adopt(page, pasted_text, label, **kw):
        ns.adoptions.append(kw)
        if ns.adopt_raises is not None:
            raise ns.adopt_raises
        if ns.adopt_to is None:
            return page, False
        return ns.adopt_to, True
    monkeypatch.setattr(research, "_gemini_adopt_lost_conversation", _adopt)

    async def _gm_done(page):
        return (bool(getattr(page, "done", False)), "stop_btn_present")
    monkeypatch.setattr(research, "_gemini_done_read", _gm_done)

    async def _gm_started(page):
        return bool(getattr(page, "started", False))
    monkeypatch.setattr(research, "_gemini_research_started", _gm_started)

    async def _observer(*_a, **_k):
        return None
    monkeypatch.setattr(research, "inject_agent_observer", _observer)

    async def _start(*a, **k):
        name = a[7]
        ns.launched.append(name)
        if name == "Gemini":
            raise _Launched()
        return _Page(NEW_CG if name == "ChatGPT" else NEW_CL), True
    monkeypatch.setattr(research, "start_agent_no_gemini_wait", _start)

    async def _verified(*_a, **_k):
        return True
    monkeypatch.setattr(research, "wait_until_verified", _verified)

    async def _poll(agents, browser, cua_client, **_k):
        ns.polled.append(dict(agents))
        return {n: {"status": "done", "text": f"{n} report " * 40,
                    "url": a.get("url", ""), "page": a.get("page")}
                for n, a in agents.items()}
    monkeypatch.setattr(research, "poll_all_agents_round_robin", _poll)
    monkeypatch.setattr(research, "apply_off_topic_sweep", lambda *a, **k: 0)

    def run(carried, *, browser, enabled=ALL, done=(), seeded=False):
        """`_p2_run_with_resume` with `run_pipeline`'s attempt runner.

        `seeded`: the retry's `_runtime` already holds the carried chats, as
        `run_pipeline` puts them there at its start."""
        ns.brief_seen = BRIEF
        if seeded:
            research._runtime.p2_chat_urls.update(carried)
        for key in done:
            (q / "documents" / f"{key}.md").write_text(
                f"# {research._agent_display_name(key)} Deep Research\n\n"
                + "A finished report about Saint Bernards. " * 20, encoding="utf-8")
            research._p2_mark_agent_done(q, key, True)
        left = dict(carried)

        async def _attempt(launch, brief):
            rejoin = research._p2_take_rejoin(left, new_input=False)
            return await research.run_phase2(browser, None, brief,
                                             enabled_agents=launch, rejoin=rejoin)

        async def _hard():
            return "stop"

        return asyncio.run(research._p2_run_with_resume(
            q, list(enabled), BRIEF, run_attempt=_attempt, soft_decision_exc=_Soft,
            hard_timeout_decision=_hard))

    ns.run = run
    yield ns
    research._runtime.reset()
    research._controls.reset()


def _resume_lines(logs):
    return [ln for ln in logs if ln.startswith("[resume]")]


# ══ 1. the 09-30 evening, after the fix ══════════════════════════════════════

def test_after_the_crash_nothing_is_sent_again_and_all_three_are_back_on_their_chats(p2):
    """⛔⛔ THE DEFECT. Before this fix the retry set up and sent the brief to all
    three (`launched` would read ChatGPT, Claude, Gemini — and stop at Gemini's
    set-up). Now each goes back into its own chat and nothing is set up."""
    browser = _Browser(_lands())
    results, skipped, stopped = p2.run(CHATS, browser=browser)
    assert p2.launched == []
    assert sorted(browser.opened) == sorted(CHATS.values())
    assert len(p2.polled) == 1
    agents = p2.polled[0]
    assert list(agents) == ["ChatGPT", "Claude", "Gemini"]
    for name, url in (("ChatGPT", CG_URL), ("Claude", CL_URL), ("Gemini", GM_URL)):
        assert agents[name]["page"] is browser.lands[url], name
        assert agents[name]["url"] == url
        assert agents[name]["verified"] is True
    assert sorted(results) == ["ChatGPT", "Claude", "Gemini"]
    assert (skipped, stopped) == (False, False)


def test_the_finished_chatgpt_goes_to_be_extracted_and_the_others_to_be_polled(p2):
    """One line per agent, saying what its chat showed — and the round-robin is
    handed ChatGPT's OWN finished chat, which is where it extracts the report."""
    browser = _Browser(_lands())
    p2.run(CHATS, browser=browser)
    assert _resume_lines(p2.logs) == [
        "[resume] ChatGPT: back on its own chat — finished, extracting",
        "[resume] Claude: back on its own chat — still researching",
        "[resume] Gemini: back on its own chat — still researching",
    ]
    cg = p2.polled[0]["ChatGPT"]
    assert cg["page"].url == CG_URL and cg["page"].done is True
    assert not cg["page"].closed


def test_a_rejoined_agent_tells_the_app_it_is_running_again(p2):
    """The retry's full `phase_restart` re-seeds every tile, and ChatGPT's card
    from the failed extraction left its tile on "errored"."""
    p2.run(CHATS, browser=_Browser(_lands()))
    assert sorted(k for k, s in p2.statuses if s == "running") == ["chatgpt", "claude", "gemini"]
    progress = {k["agent"]: k for t, k in p2.events
                if t == "agent_progress" and "Back on its own chat" in k.get("progress", "")}
    assert sorted(progress) == ["chatgpt", "claude", "gemini"]
    assert all(k["status"] == "generating" for k in progress.values())


def test_a_second_crash_rejoins_the_same_chats_again(p2):
    """The retry's `_runtime` starts empty; a rejoined chat must be noted again,
    or a SECOND crash would send the brief to it after all."""
    p2.run(CHATS, browser=_Browser(_lands()))
    assert research._p2_chats_to_rejoin() == CHATS


# ══ 2. an agent with no chat is set up as today ══════════════════════════════

def test_an_agent_the_crash_caught_before_its_brief_went_is_set_up_and_sent_it(p2):
    browser = _Browser(_lands())
    p2.run({"chatgpt": CG_URL, "gemini": GM_URL}, browser=browser)
    assert p2.launched == ["Claude"]
    assert sorted(browser.opened) == sorted([CG_URL, GM_URL])
    agents = p2.polled[0]
    assert agents["Claude"]["page"].url == NEW_CL
    assert agents["ChatGPT"]["page"] is browser.lands[CG_URL]
    assert ("[resume] Claude: no chat of its own to go back to — starting it the "
            "usual way") in p2.logs


def test_an_address_that_is_not_a_chat_is_nothing_to_go_back_to(p2):
    browser = _Browser(_lands())
    p2.run({"chatgpt": "https://chatgpt.com/", "claude": CL_URL, "gemini": GM_URL},
           browser=browser)
    assert p2.launched == ["ChatGPT"]
    assert "https://chatgpt.com/" not in browser.opened


# ══ 3. a chat that cannot be proven costs only that agent ═══════════════════

_FALLBACKS = {
    "someone else's first message": lambda url: _Page(url, FOREIGN_TURN, done=True),
    "an empty first message": lambda url: _Page(url, "", done=True),
    "landed on another chat": lambda url: _Page(
        NEW_CG if "chatgpt" in url else NEW_CL, ASK_TURN, done=True),
    "signed out": lambda url: _Page(url, ASK_TURN, signed_out=True),
}


@pytest.mark.parametrize("how", sorted(_FALLBACKS))
@pytest.mark.parametrize("who,url", [("ChatGPT", CG_URL), ("Claude", CL_URL)])
def test_a_chat_that_cannot_be_proven_falls_back_for_that_agent_only(p2, who, url, how):
    page = _FALLBACKS[how](url)
    browser = _Browser(_lands(**{url: page}))
    p2.run(CHATS, browser=browser)
    assert p2.launched == [who]
    assert page.closed, "the tab that could not be proven is closed again"
    agents = p2.polled[0]
    assert agents[who]["page"].url == (NEW_CG if who == "ChatGPT" else NEW_CL)
    others = [n for n in ("ChatGPT", "Claude", "Gemini") if n != who]
    for n in others:
        assert agents[n]["page"] is browser.lands[{"ChatGPT": CG_URL, "Claude": CL_URL,
                                                    "Gemini": GM_URL}[n]]
    assert any(ln.startswith(f"[resume] {who}: ") and ln.endswith("starting it again")
               for ln in p2.logs)


def test_a_chat_that_will_not_open_falls_back_for_that_agent_only(p2):
    browser = _Browser(_lands(), refuse={CL_URL})
    p2.run(CHATS, browser=browser)
    assert p2.launched == ["Claude"]
    assert p2.polled[0]["ChatGPT"]["page"] is browser.lands[CG_URL]


def test_a_brief_that_was_pasted_proves_the_chat_by_its_head(p2):
    """Paste mode: the chat's first message IS the brief."""
    browser = _Browser(_lands(**{CG_URL: _Page(CG_URL, BRIEF, done=True)}))
    p2.run(CHATS, browser=browser)
    assert p2.launched == []


def test_a_first_message_read_late_still_proves_the_chat(p2, monkeypatch):
    """The first message mounts after the URL: two empty reads, then the text."""
    reads = {"n": 0}

    async def _late(page, *a, **k):
        reads["n"] += 1
        return "" if reads["n"] <= 2 else page.turn
    monkeypatch.setattr(research, "read_chatgpt_first_user_message", _late)
    p2.run(CHATS, browser=_Browser(_lands()))
    assert p2.launched == []
    assert reads["n"] == 3


# ══ 4. Gemini ═════════════════════════════════════════════════════════════════

def test_gemini_landing_on_its_home_is_found_again_by_its_own_chat_id(p2):
    """#897a: Gemini does not reopen a chat from its address. The sidebar hunt
    that exists for exactly that brings it back — scoped to the chat's id."""
    home = _Page("https://gemini.google.com/app", ours=False)
    p2.adopt_to = _Page(GM_URL, started=True)
    browser = _Browser(_lands(**{GM_URL: home}))
    p2.run(CHATS, browser=browser)
    assert p2.adoptions == [{"post_start": True, "lost_convo_id": "e91e413e201fee2a"}]
    assert p2.launched == []
    assert p2.polled[0]["Gemini"]["page"] is p2.adopt_to
    assert home.closed


def test_gemini_found_on_another_chat_is_set_up_again(p2):
    home = _Page("https://gemini.google.com/app", ours=False)
    p2.adopt_to = _Page("https://gemini.google.com/app/0000aaaa1111bbbb", started=True)
    with pytest.raises(_Launched):
        p2.run(CHATS, browser=_Browser(_lands(**{GM_URL: home})))
    assert p2.launched == ["Gemini"]


def test_gemini_not_found_at_all_is_set_up_again(p2):
    home = _Page("https://gemini.google.com/app", ours=False)
    with pytest.raises(_Launched):
        p2.run(CHATS, browser=_Browser(_lands(**{GM_URL: home})))
    assert p2.launched == ["Gemini"]
    assert home.closed


def test_a_gemini_plan_not_yet_started_gets_its_start_pressed_by_the_round_robin(p2):
    """The plan waits for "Start research": the round-robin's start watch is the
    thing that presses it (enabled-only, three at most, checked on the next leg)."""
    browser = _Browser(_lands(**{GM_URL: _Page(GM_URL, started=False)}))
    p2.run(CHATS, browser=browser)
    gm = p2.polled[0]["Gemini"]
    assert gm["gemini_watch_start"] is True
    assert gm["verified"] is False
    assert gm["brief"] == BRIEF
    assert ("[resume] Gemini: back on its own chat — its plan has not started — "
            "the round-robin presses 'Start research'") in p2.logs
    assert [k["stage"] for t, k in p2.events if t == "agent_progress"
            and k.get("agent") == "gemini"] == ["planning"]


def test_a_gemini_already_researching_is_not_watched_for_a_start(p2):
    p2.run(CHATS, browser=_Browser(_lands()))
    gm = p2.polled[0]["Gemini"]
    assert gm["gemini_watch_start"] is False and gm["verified"] is True


def test_a_finished_gemini_is_collected(p2):
    browser = _Browser(_lands(**{GM_URL: _Page(GM_URL, done=True, started=True)}))
    p2.run(CHATS, browser=browser)
    assert "[resume] Gemini: back on its own chat — finished, extracting" in p2.logs


# ══ 5. what was already kept stays kept ══════════════════════════════════════

def test_an_agent_already_extracted_and_recorded_is_not_opened_or_redone(p2):
    """Wave 10.9's record keeps it; the rejoin never sees it."""
    browser = _Browser(_lands())
    results, _s, _st = p2.run(CHATS, browser=browser, done=["chatgpt"])
    assert CG_URL not in browser.opened
    assert p2.launched == []
    assert sorted(p2.polled[0]) == ["Claude", "Gemini"]
    assert results["ChatGPT"]["_restored"] is True


def test_a_stop_before_phase_2_rejoins_nothing(p2):
    research._controls.stop_event.set()
    browser = _Browser(_lands())
    with pytest.raises(_Launched):
        p2.run(CHATS, browser=browser)
    assert browser.opened == []


# ══ 6. the carried chats are spent once ══════════════════════════════════════

def test_the_carried_chats_go_to_one_attempt_only():
    left = dict(CHATS)
    assert research._p2_take_rejoin(left, new_input=False) == CHATS
    assert research._p2_take_rejoin(left, new_input=False) == {}


def test_new_input_from_the_person_means_no_chat_is_rejoined():
    """The old chats never saw it — every agent is sent the brief with it."""
    left = dict(CHATS)
    assert research._p2_take_rejoin(left, new_input=True) == {}
    assert left == {}


# ══ 7. the crash hands its chats to its own retry — the REAL run_pipeline ═══

class _FakeBrowser:
    def __init__(self, *a, **k):
        self.context = None

    async def start(self):
        return None

    async def close(self):
        return None


@pytest.fixture
def crash(tmp_path, monkeypatch):
    """`run(exc, at_phase=…, crash_retries=…)` → (retry kwargs list, cards)."""
    queue_dir = tmp_path / "St_Bernard_20260930_180908"
    (queue_dir / "documents").mkdir(parents=True)
    (queue_dir / "documents" / "brief.md").write_text(BRIEF * 3, encoding="utf-8")
    cards, retries = [], []
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
    monkeypatch.setattr(research, "_run_start_epoch", lambda: RUN_START)

    async def _noop_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop_dispatcher)
    monkeypatch.setattr(research, "fail_phase", lambda **kw: cards.append(kw))

    async def _retry(*a, **k):
        retries.append(k)
    monkeypatch.setattr(research, "run_pipeline_captured", _retry)
    _real_sleep = asyncio.sleep

    async def _fast_sleep(*_a, **_k):
        return await _real_sleep(0)
    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)

    def _run(exc, *, at_phase=2, crash_retries=0, rejoin=None, chats=CHATS, modes=None,
             tabs=None):
        """`rejoin`: what this attempt was itself handed by the crash before it.
        `chats`: what Phase 2 noted before Chrome died (None: it got nowhere).
        `modes`: the agents' recorded modes at the crash.
        `tabs`: {agent: the address its tab is on when Chrome dies}."""
        def _emit(name, phase=None, **_kw):
            # The first thing the main `try` does is announce phase 0; the run is
            # put where the 09-30 crash found it, then Chrome dies.
            if name == "phase_start" and phase == 0:
                research._runtime.phase = at_phase
                if chats is not None:
                    research._runtime.agent_chat_urls = dict(chats)
                    research._runtime.p2_chat_urls = dict(chats)
                if tabs:
                    research._runtime.p2_chat_pages = {k: _Page(u) for k, u in tabs.items()}
                if modes:
                    research._runtime.agent_modes = dict(modes)
                raise exc
        monkeypatch.setattr(research, "emit_event", _emit)
        asyncio.run(research.run_pipeline(
            topic="St Bernard", resume_dir=str(queue_dir), uid=None, email=None,
            api_key="test-key", _crash_retries=crash_retries, _p2_rejoin=rejoin))
        return retries, cards

    yield _run
    research._runtime.reset()
    research._controls.reset()


def _chrome_died():
    return RuntimeError("research browser died during phase 2 (browser crash)")


def test_a_chrome_death_in_phase_2_hands_its_chats_to_its_own_retry(crash):
    """⛔⛔ The half of the fix nothing else can see: the `finally` resets
    `_runtime` BEFORE the retry starts, so the chats must be taken first."""
    retries, cards = crash(_chrome_died())
    assert len(retries) == 1
    assert retries[0]["_p2_rejoin"] == CHATS
    assert retries[0]["_crash_retries"] == 1
    assert cards == [], "a silent retry still shows no card"


def test_the_retry_cap_still_holds(crash):
    retries, cards = crash(_chrome_died(),
                           crash_retries=research.BROWSER_CRASH_MAX_RETRIES)
    assert retries == []
    assert [c["intent"] for c in cards] == ["crash_loop"]


def test_a_chrome_death_outside_phase_2_carries_no_chats(crash):
    retries, _cards = crash(_chrome_died(), at_phase=3)
    assert len(retries) == 1
    assert retries[0]["_p2_rejoin"] == {}


def test_a_failure_that_is_not_chrome_carries_no_chats(crash, monkeypatch):
    """The one-shot retry of an ordinary failure re-runs Phase 2 as before. The
    planner is stubbed only to reach that door; its gates have their own suite."""
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry",
                        lambda *a, **k: (True, 2, False))
    retries, _cards = crash(RuntimeError("the notebook upload was refused"))
    assert len(retries) == 1
    assert retries[0]["_p2_rejoin"] == {}


# ══ 8. Phase 2 notes each chat as the brief goes into it ═════════════════════

class _Noted(Exception):
    pass


@pytest.mark.parametrize("agent,url,verified", [
    ("chatgpt", NEW_CG, True), ("chatgpt", NEW_CG, False),
    ("claude", NEW_CL, True), ("claude", NEW_CL, False),
])
def test_chatgpt_and_claude_are_noted_once_their_brief_is_in(monkeypatch, agent, url,
                                                              verified):
    """Both hand-offs to the round-robin: verified running, and the "page is at
    this run's chat" hand-off when the verify could not read it. Driven up to the
    observer, which comes right after the note."""
    research._runtime.reset()
    research._controls.reset()
    monkeypatch.setattr(research._controls, "pro_warning_acknowledged", True)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_p2_run_dir", lambda: None)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")

    async def _start(*a, **k):
        return _Page(url), True

    async def _verified(*a, **k):
        return verified

    async def _observer(page, key):
        raise _Noted(key)
    monkeypatch.setattr(research, "start_agent_no_gemini_wait", _start)
    monkeypatch.setattr(research, "wait_until_verified", _verified)
    monkeypatch.setattr(research, "inject_agent_observer", _observer)
    with pytest.raises(_Noted):
        asyncio.run(research.run_phase2(_Browser(), None, BRIEF, enabled_agents=[agent]))
    assert research._runtime.p2_chat_urls == {agent: url}
    research._runtime.reset()


def test_gemini_is_noted_once_its_brief_is_in(monkeypatch):
    research._runtime.reset()
    research._controls.reset()
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_p2_run_dir", lambda: None)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")

    def _emit(kind, **kw):
        if kw.get("agent") == "gemini" and kw.get("stage") == "planning":
            raise _Noted("gemini")
    monkeypatch.setattr(research, "emit_event", _emit)

    async def _start(*a, **k):
        return _Page(GM_URL), True
    monkeypatch.setattr(research, "start_agent_no_gemini_wait", _start)
    with pytest.raises(_Noted):
        asyncio.run(research.run_phase2(_Browser(), None, BRIEF, enabled_agents=["gemini"]))
    assert research._runtime.p2_chat_urls == {"gemini": GM_URL}
    research._runtime.reset()


def test_a_chat_that_moves_is_followed_and_phase_1s_chat_is_never_taken():
    rt = research.PipelineRuntime()
    # Phase 1 registers ChatGPT's brief chat: not a Phase-2 chat.
    rt.register_page("chatgpt", _Page("https://chatgpt.com/c/p1-brief-chat"))
    assert rt.p2_chat_urls == {}
    rt.p2_chat_urls["gemini"] = GM_URL
    rt.register_page("gemini", _Page("https://gemini.google.com/app/1111222233334444"))
    assert rt.p2_chat_urls == {"gemini": "https://gemini.google.com/app/1111222233334444"}


# ══ 9. the pieces, on their own ══════════════════════════════════════════════

def test_the_plan_takes_only_chats_of_agents_this_attempt_would_launch():
    carried = {"chatgpt": CG_URL, "claude": "https://claude.ai/new", "gemini": GM_URL}
    assert research._p2_rejoin_plan(carried, ["chatgpt", "claude"]) == {"chatgpt": CG_URL}
    assert research._p2_rejoin_plan(carried, []) == {}


@pytest.mark.parametrize("key,url,want", [
    ("chatgpt", CG_URL, "6abdb44f-8908-83ea-a52a-620821c03ae9"),
    ("chatgpt", "https://chatgpt.com/", ""),
    ("claude", CL_URL, "4d24eb39-f33d-41ac-a659-9e89c477701f"),
    ("claude", "https://claude.ai/new", ""),
    ("gemini", GM_URL, "e91e413e201fee2a"),
    ("gemini", "https://gemini.google.com/app", ""),
    ("notebooklm", GM_URL, ""),
])
def test_a_chat_is_known_by_its_own_id(key, url, want):
    assert research._p2_chat_id(key, url) == want


@pytest.mark.parametrize("turn,ours", [
    (ASK_TURN, True),
    (BRIEF, True),
    (FOREIGN_TURN, False),
    ("", False),
])
def test_a_first_message_holds_what_this_run_sent_or_it_is_not_ours(turn, ours):
    assert research._p2_turn_holds_our_send(turn, BRIEF) is ours


@pytest.mark.skipif(NODE is None, reason="node runs the page JS")
def test_claudes_first_message_is_read_off_the_message_never_the_page():
    """Executed against a page that lists the run's words in its sidebar too —
    the sidebar must never be the evidence."""
    spec = el("div", kids=[
        el("nav", text="Recents Saint Bernard breed health " + ASK_TURN),
        el("div", {"data-testid": "user-message"}, text=ASK_TURN),
        el("div", {"data-testid": "user-message"}, text="a later follow-up"),
    ])
    assert run_js(spec, research._CLAUDE_FIRST_USER_MSG_JS, 4000)["ret"] == ASK_TURN
    bare = el("div", kids=[el("nav", text="Recents " + ASK_TURN)])
    assert run_js(bare, research._CLAUDE_FIRST_USER_MSG_JS, 4000)["ret"] == ""


def test_an_unreadable_claude_page_reads_as_nothing():
    class _Gone:
        async def evaluate(self, *a, **k):
            raise RuntimeError("Target page, context or browser has been closed")
    assert asyncio.run(research._claude_first_user_message(_Gone())) == ""


def test_the_line_typed_beside_the_brief_is_unchanged_and_is_what_the_retry_knows(
        monkeypatch):
    """Executed: what `type_short_inline_prompt` types, character for character —
    the refactor that named its first sentence changed nothing — and that line,
    alone, proves a chat whose brief went as a file."""
    typed = []

    class _Box:
        async def click(self):
            return None

    class _Keys:
        async def type(self, text, delay=0):
            typed.append(text)

    class _Composer:
        keyboard = _Keys()

        async def query_selector(self, sel):
            return _Box()

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    assert asyncio.run(research.type_short_inline_prompt(_Composer(), "chatgpt", "2A"))
    assert typed == [ASK_TURN]
    assert research._p2_turn_holds_our_send(typed[0], "") is True


# ══ 10. the wiring inside run_pipeline, by AST ═══════════════════════════════
# `run_pipeline` cannot be driven into Phase 2 (5,000 lines, every service on
# the way); the attempt runner above is shaped as its `_p2_attempt`, and this is
# what holds the two together.

def _tree(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def test_the_first_phase_2_attempt_takes_the_carried_chats_and_no_other_call_does():
    tree = _tree(research.run_pipeline)
    starts = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and ast.unparse(n.targets[0]) == "_p2_rejoin_left"]
    assert starts == ["dict(_p2_rejoin or {})"]
    attempt = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "_p2_attempt")
    takes = [ast.unparse(n.value) for n in ast.walk(attempt) if isinstance(n, ast.Assign)
             and ast.unparse(n.targets[0]) == "_rejoin"]
    assert takes == ["_p2_take_rejoin(_p2_rejoin_left, new_input=bool(extra_ctx or fb2))"]
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "run_phase2"]
    mine = [c for c in ast.walk(attempt) if isinstance(c, ast.Call)
            and ast.unparse(c.func) == "run_phase2"]
    assert len(mine) == 1
    assert {k.arg: ast.unparse(k.value) for k in mine[0].keywords}["rejoin"] == "_rejoin"
    assert not [k for c in calls if c not in mine for k in c.keywords if k.arg == "rejoin"]
    # ⛔ And NOTHING ELSE touches the carried chats: one assignment, one take. A
    # `_p2_rejoin_left.clear()` (or a reassignment) anywhere else empties the
    # rejoin while every behaviour test above, which builds its own runner,
    # stays green.
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
            and n.id == "_p2_rejoin_left"]
    assert len(uses) == 2, [ast.unparse(n) for n in uses]
    assert len([n for n in ast.walk(attempt) if isinstance(n, ast.Name)
                and n.id == "_p2_rejoin_left"]) == 1


# ══ 11. Gemini: the chat its TAB is on at the crash, not the one it was sent in
# (ChatGPT and Claude keep the chat noted at the send — section 17.)
# 09-30 evening run.log:146 — Gemini's send landed on #1cb56678, the digest of
# /app/3a6f3707328a6fa8. At 18:21:17 the tab navigated, and from 18:21:27 its plan
# and its research were on /app/e91e413e201fee2a. Nothing in 2D notes the move;
# Playwright keeps a page's last address after Chrome dies.

GM_SENT = "https://gemini.google.com/app/3a6f3707328a6fa8"
GM_HOME = "https://gemini.google.com/app"


class _ChromeDied(RuntimeError):
    def __init__(self):
        super().__init__("Page.bring_to_front: Target page, context or browser has "
                         "been closed")


class _GonePage(_Page):
    """A tab whose address can no longer be read once `gone`."""

    def __init__(self, url, *a, **k):
        self.gone = False
        super().__init__(url, *a, **k)

    @property
    def url(self):
        if self.gone:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._url

    @url.setter
    def url(self, value):
        self._url = value


@pytest.fixture
def phase2(monkeypatch):
    """The real `run_phase2`, its set-up and observer stubbed — as section 8."""
    research._runtime.reset()
    research._controls.reset()
    monkeypatch.setattr(research._controls, "pro_warning_acknowledged", True)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_p2_run_dir", lambda: None)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")
    yield monkeypatch
    research._runtime.reset()
    research._controls.reset()


@pytest.mark.parametrize("sent_on", [GM_SENT, GM_HOME])
def test_a_gemini_that_moved_chat_after_its_send_is_carried_on_the_chat_it_moved_to(
        phase2, sent_on):
    """Driven through the real 2C note: the brief goes in on `sent_on` (its own
    chat, or Gemini's bare home before the address settles), the tab then moves to
    the chat that holds the plan, and Chrome dies."""
    page = _Page(sent_on)

    async def _start(*a, **k):
        return page, True

    def _emit(kind, **kw):
        if kw.get("agent") == "gemini" and kw.get("stage") == "planning":
            page.url = GM_URL
            raise _ChromeDied()
    phase2.setattr(research, "start_agent_no_gemini_wait", _start)
    phase2.setattr(research, "emit_event", _emit)
    with pytest.raises(_ChromeDied):
        asyncio.run(research.run_phase2(_Browser(), None, BRIEF, enabled_agents=["gemini"]))
    assert research._p2_chats_to_rejoin() == {"gemini": GM_URL}


@pytest.mark.parametrize("where", ["on Gemini's home", "unreadable"])
def test_a_tab_off_its_chats_at_the_crash_carries_the_chat_its_brief_went_into(where):
    """Mid-reset on a home page, or a tab whose address cannot be read: the
    address noted at the send is what the retry gets."""
    research._runtime.reset()
    page = _GonePage(GM_SENT)
    research._p2_note_chat("gemini", page)
    if where == "unreadable":
        page.gone = True
    else:
        page.url = GM_HOME
    assert research._p2_chats_to_rejoin() == {"gemini": GM_SENT}
    research._runtime.reset()


def test_a_tab_registered_in_place_of_the_noted_one_is_the_one_read_at_the_crash():
    """Gemini re-adopted from its sidebar, a hard retry's fresh tab: the NEW tab is
    registered. The old one still reads the chat it was on, and must not win."""
    research._runtime.reset()
    research._p2_note_chat("gemini", _Page(GM_SENT))
    research._runtime.register_page("gemini", _Page(GM_URL))
    assert research._p2_chats_to_rejoin() == {"gemini": GM_URL}
    research._runtime.reset()


# ══ 12. the chats outlive a crash of the retry itself ════════════════════════

@pytest.mark.parametrize("at_phase", [0, 2])
def test_a_retry_that_crashes_before_it_gets_back_to_the_chats_hands_them_on(
        crash, at_phase):
    """Chrome dies again before the retry's Phase 2 reopened anything (its start,
    or Phase 2 before the first attempt): the next retry gets the same chats, not
    nothing — the 09-30 defect one retry later."""
    retries, cards = crash(_chrome_died(), at_phase=at_phase, crash_retries=1,
                           rejoin=CHATS, chats=None)
    assert len(retries) == 1
    assert retries[0]["_p2_rejoin"] == CHATS
    assert retries[0]["_crash_retries"] == 2
    assert cards == []


@pytest.mark.parametrize("how", ["would not open", "cannot be proven"])
def test_chrome_dying_during_the_rejoin_unwinds_and_keeps_every_chat(p2, how):
    """ChatGPT is back on its chat; then Chrome dies as Claude's opens (or while
    it is read). A dead browser is not an agent that cannot come back: nothing is
    set up on it, the run unwinds as a crash, and the next retry gets all three —
    the one not reached yet included."""
    if how == "would not open":
        browser = _Browser(_lands(), refuse={CL_URL}, context=_DeadContext())
    else:
        browser = _Browser(_lands(**{CL_URL: _Page(CL_URL, "")}), context=_DeadContext())
    with pytest.raises(RuntimeError, match=r"\(browser crash\)") as died:
        p2.run(CHATS, browser=browser, seeded=True)
    assert research._is_browser_close_error(died.value)
    assert research._runtime.last_failure_kind == "browser_crash"
    assert p2.launched == []
    assert GM_URL not in browser.opened
    assert research._p2_chats_to_rejoin() == CHATS


# ══ 13. an agent set up again leaves its old chat behind ═════════════════════

def test_a_relaunch_that_dies_before_any_new_brief_carries_none_of_the_old_chats(phase2):
    """A person's Retry or new input re-runs Phase 2: the chats the first attempt
    noted are the ones being left. Chrome dies in ChatGPT's set-up, before Claude
    and Gemini are reached — none of the three old chats may be carried."""
    research._runtime.p2_chat_urls.update(CHATS)

    async def _start(*a, **k):
        raise _ChromeDied()
    phase2.setattr(research, "start_agent_no_gemini_wait", _start)
    with pytest.raises(_ChromeDied):
        asyncio.run(research.run_phase2(_Browser(), None, BRIEF, enabled_agents=ALL))
    assert research._p2_chats_to_rejoin() == {}


def test_a_rejoin_that_could_not_prove_one_chat_still_carries_the_others(p2):
    """Only the agent set up again leaves its chat: ChatGPT's is unprovable and it
    starts again, Claude and Gemini stay carried."""
    browser = _Browser(_lands(**{CG_URL: _Page(CG_URL, FOREIGN_TURN, done=True)}))
    p2.run(CHATS, browser=browser, seeded=True)
    assert p2.launched == ["ChatGPT"]
    assert research._p2_chats_to_rejoin() == {"chatgpt": NEW_CG, "claude": CL_URL,
                                               "gemini": GM_URL}


class _Halt(BaseException):
    """Stops the round-robin where the test has seen enough."""


@pytest.fixture
def hard_retry(monkeypatch):
    """The REAL round-robin, one ChatGPT on its chat, with the person's Retry
    (a hard retry) waiting for it."""
    research._runtime.reset()
    research._controls.reset()
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)

    async def _no_sleep(*_a, **_k):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    page = _Page(CG_URL)
    research._p2_note_chat("chatgpt", page)
    research._controls.retry_agents_hard.add("chatgpt")

    def _run():
        return asyncio.run(research.poll_all_agents_round_robin(
            {"ChatGPT": {"page": page, "url": CG_URL, "verified": True}},
            browser=None, cua_client=None))
    yield monkeypatch, page, _run
    research._runtime.reset()
    research._controls.reset()


def test_a_hard_retry_that_dies_in_its_set_up_does_not_carry_the_chat_it_left(hard_retry):
    """The warm tab is reused for the restart and is off its chat when Chrome dies:
    the chat the retry was leaving must not come back."""
    monkeypatch, page, run = hard_retry

    async def _restart(name, browser, cua, brief, path, verbose, reuse_page=None):
        if reuse_page is not None:
            reuse_page.url = "https://chatgpt.com/"
        raise RuntimeError("Target page, context or browser has been closed")

    async def _dead(_browser):
        return True
    monkeypatch.setattr(research, "_restart_phase2_agent", _restart)
    monkeypatch.setattr(research, "_browser_context_is_dead", _dead)
    with pytest.raises(RuntimeError, match="hard retry"):
        run()
    assert research._p2_chats_to_rejoin() == {}


def test_a_hard_retry_that_set_its_agent_up_again_carries_the_new_chat(hard_retry):
    monkeypatch, page, run = hard_retry
    fresh = _Page(NEW_CG)

    async def _restart(name, browser, cua, brief, path, verbose, reuse_page=None):
        return fresh, True

    async def _observer(*_a, **_k):
        raise _Halt()
    monkeypatch.setattr(research, "_restart_phase2_agent", _restart)
    monkeypatch.setattr(research, "inject_agent_observer", _observer)
    with pytest.raises(_Halt):
        run()
    assert research._p2_chats_to_rejoin() == {"chatgpt": NEW_CG}


# ══ 14. a Stop stops the rejoin ══════════════════════════════════════════════

def test_a_stop_while_the_first_chat_is_proven_opens_no_other_chat(p2, monkeypatch):
    async def _turn_then_stop(page, *a, **k):
        research._controls.stop_event.set()
        return getattr(page, "turn", "")
    monkeypatch.setattr(research, "read_chatgpt_first_user_message", _turn_then_stop)
    browser = _Browser(_lands())
    with pytest.raises(_Launched):
        p2.run(CHATS, browser=browser)
    assert browser.opened == [CG_URL]


def test_a_stop_while_gemini_is_proven_runs_no_sidebar_hunt(p2, monkeypatch):
    """The hunt clicks rail entries — a page action after Stop (#737)."""
    p2.adopt_to = _Page(GM_URL, started=True)

    async def _ident_then_stop(page, convo_id, pasted_text, **_k):
        research._controls.stop_event.set()
        return False
    monkeypatch.setattr(research, "_gemini_reload_identity_ok", _ident_then_stop)
    with pytest.raises(_Launched):
        p2.run(CHATS, browser=_Browser(_lands(**{GM_URL: _Page(GM_HOME, ours=False)})))
    assert p2.adoptions == []


# ══ 15. an agent in chat mode is not carried ═════════════════════════════════

def test_an_agent_in_chat_mode_is_set_up_again_not_rejoined(crash):
    """The retry's reset drops its mode and its keep/skip hold, and a rejoin puts
    neither back: it would be read as a Deep Research. Its own set-up finds its
    mode again, as before."""
    retries, _cards = crash(_chrome_died(), modes={
        "claude": {"requested": "research", "actual": "chat",
                   "user_acknowledged_chat": True},
        "chatgpt": {"requested": "research", "actual": "research",
                    "user_acknowledged_chat": False}})
    assert retries[0]["_p2_rejoin"] == {"chatgpt": CG_URL, "gemini": GM_URL}


# ══ 16. no chat address reaches the run log from the rejoin ══════════════════

def test_the_rejoin_lines_keep_chat_addresses_out_of_the_run_log(p2):
    """Playwright's goto error holds the address twice, and Send logs uploads the
    run log."""
    def _goto_error(url):
        return RuntimeError(f"Page.goto: net::ERR_ABORTED at {url}\nCall log:\n"
                            f"  - navigating to \"{url}\", waiting until \"load\"")
    p2.adopt_raises = RuntimeError(f"Page.goto: Timeout 30000ms exceeded at {GM_URL}")
    browser = _Browser(_lands(**{GM_URL: _Page(GM_HOME, ours=False)}),
                       refuse={CL_URL}, error=_goto_error)
    with pytest.raises(_Launched):
        p2.run(CHATS, browser=browser)
    lines = _resume_lines(p2.logs)
    assert any("would not open" in ln for ln in lines)
    assert any("sidebar hunt raised" in ln for ln in lines)
    for chat_id in ("4d24eb39", "e91e413e201fee2a"):
        assert not [ln for ln in lines if chat_id in ln], chat_id


# ══ 17. only this run's chats are carried (review, 10-02) ════════════════════
# ⛔⛔ ChatGPT's and Claude's brief goes as a file, so the chat's first message is
# the same fixed line on every run (`ASK_TURN`), and the retry's proof cannot
# tell this run's chat from an older research chat of the same account. Their
# tabs are known to wander — 2026-08-05: a press landed on a sidebar link titled
# "Deep research request" and ChatGPT ran on the previous evening's chat. So for
# them the crash carries the chat noted when the brief went in, never the one the
# tab wandered to; only Gemini, which really does move its research to another
# chat, follows its tab. A ChatGPT chat dated older than the run is never carried.

GM_MOVED = "https://gemini.google.com/app/1111222233334444"


def test_a_crash_carries_the_chats_chatgpt_and_claude_were_sent_the_brief_in(crash):
    """⭐ Through the REAL `run_pipeline`: Chrome dies with ChatGPT's and Claude's
    tabs on older chats and Gemini's on the chat it moved its research to. The
    retry is handed ChatGPT's and Claude's own chats, and Gemini's new one.
    Before: ChatGPT and Claude were carried on the older chats."""
    retries, _cards = crash(_chrome_died(),
                            tabs={"chatgpt": OLD_CG, "claude": OLD_CL, "gemini": GM_MOVED})
    assert retries[0]["_p2_rejoin"] == {"chatgpt": CG_URL, "claude": CL_URL,
                                        "gemini": GM_MOVED}


@pytest.mark.parametrize("noted, tab, carried", [
    ("https://chatgpt.com/", OLD_CG, None),
    (OLD_CG, OLD_CG, None),
    ("https://chatgpt.com/", NEW_CG, NEW_CG),
], ids=["tab-on-older-chat", "noted-on-older-chat", "own-new-chat"])
def test_a_chatgpt_chat_older_than_the_run_is_never_carried(crash, noted, tab, carried):
    """The note is not a chat (the send went in on ChatGPT's home): the tab's chat
    is taken — but never one its own id dates as older than this run. Beside it,
    the tab on a chat of this run is carried. Before: the older chat was carried."""
    retries, _cards = crash(_chrome_died(), chats={"chatgpt": noted, "claude": CL_URL},
                            tabs={"chatgpt": tab})
    want = {"claude": CL_URL}
    if carried:
        want["chatgpt"] = carried
    assert retries[0]["_p2_rejoin"] == want


def test_the_retry_never_collects_an_older_chats_finished_report(p2):
    """⛔⛔ THE HARM, through the retry's REAL Phase 2: the older chat is finished
    and its first message is the same line. ChatGPT goes back into its own chat,
    still researching; the older chat is never opened."""
    tab = _Page(CG_URL)
    research._p2_note_chat("chatgpt", tab)
    tab.url = OLD_CG
    carried = research._p2_chats_to_rejoin()
    research._runtime.reset()
    browser = _Browser({CG_URL: _Page(CG_URL, ASK_TURN, done=False),
                        OLD_CG: _Page(OLD_CG, ASK_TURN, done=True)})
    p2.run(carried, browser=browser, enabled=["chatgpt"])
    assert browser.opened == [CG_URL]
    assert p2.launched == []
    assert p2.polled[0]["ChatGPT"]["url"] == CG_URL
    assert _resume_lines(p2.logs) == [
        "[resume] ChatGPT: back on its own chat — still researching"]


def test_a_chatgpt_left_with_only_an_older_chat_starts_again_and_says_why(p2):
    """Its brief went in on ChatGPT's home and its tab is on an older chat: nothing
    is carried, the log says why without the address, and ChatGPT is set up the
    usual way."""
    tab = _Page("https://chatgpt.com/")
    research._p2_note_chat("chatgpt", tab)
    tab.url = OLD_CG
    carried = research._p2_chats_to_rejoin()
    assert carried == {}
    said = [ln for ln in p2.logs if "older than this run" in ln]
    assert said == ["[resume] ChatGPT: the chat it was on is older than this run — "
                    "not going back into it"]
    research._runtime.reset()
    p2.run(carried, browser=_Browser({OLD_CG: _Page(OLD_CG, ASK_TURN, done=True)}),
           enabled=["chatgpt"])
    assert p2.launched == ["ChatGPT"]
    assert p2.polled[0]["ChatGPT"]["url"] == NEW_CG
