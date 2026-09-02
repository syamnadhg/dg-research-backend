"""STRETCH 7.5 STEP 3 — identity by CONTENT, not by the shape of an address.

⛔⛔ WHAT THIS REPLACES. The check that decides whether a ChatGPT tab is
somebody else's decodes a creation time out of the URL and compares it to when
this run started — THIS machine's clock against OpenAI's, with 120 seconds of
slack. It runs on every poll tick, and on a "foreign" verdict it drops the
agent, stamps it wrong_conversation and fails it. It has been repaired twice
after near-misses:

  · 2026-08-05 — a mid-run settings write moved the run's own start time
    forward, so the run began dating itself later than it started.
  · 2026-08-27 — ChatGPT served `/c/WEB:<uuid>`; the id became undatable, the
    predicate failed CLOSED, and a HEALTHY leg was killed seven seconds after
    Send, on every tick.

A guard comparing two machines' clocks is a class this project has already been
bitten by twice, and the address format is not ours to control.

▶ The question a conversation can answer about ITSELF: does it hold the brief we
  put there?

⛔⛔ AND THE ANSWER IS THREE-VALUED. The whole lesson of 08-27 is that "I cannot
tell" must never come out as "somebody else's". That is what most of this file
is about — every abstain below is a leg that stays alive.

⚠ WHAT THIS IS NOT. Gemini has a content-ownership gate of a similar shape, and
it is deliberately NOT reused: measured 2026-09-02, both of its callers sit
inside the sidebar/tab hunt that exists because Gemini ORPHANS its own runs.
ChatGPT does not — we always know which tab we sent into. Nothing here searches
for a conversation and nothing here adopts one. Same shape, opposite placement.

Run:  pytest tests/test_conversation_identity_by_content_0902.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import research

BRIEF = (
    "# Research Brief\n\n"
    "Investigate surface-code thresholds for quantum error correction, "
    "focusing on transmon qubit decoherence budgets and the Fowler cycle."
)

# A real conversation that holds that brief, plus an answer.
OURS = (
    "Investigate surface-code thresholds for quantum error correction, focusing "
    "on transmon qubit decoherence budgets and the Fowler cycle.\n\n"
    "Certainly — I'll start by surveying the literature on surface codes..."
)

# Somebody else's finished thread: fluent, long, and about nothing we asked.
STRANGER = (
    "Write me a 500-word essay about the history of sourdough baking in "
    "northern Europe, with particular attention to rye starters and the "
    "influence of Baltic trade routes on regional bread culture."
)


# ── the fingerprint ─────────────────────────────────────────────────────
def test_the_fingerprint_drops_the_shared_template_header():
    """⛔ Every brief this product writes opens with the same boilerplate. A
    fingerprint taken from the top would match every run we have ever done —
    it would say "ours" about a stranger's thread just as readily."""
    fp = research.brief_fingerprint(BRIEF)
    assert "research" not in fp
    assert "brief" not in fp
    assert "surface" in fp


def test_the_fingerprint_is_deduplicated_and_capped():
    fp = research.brief_fingerprint("alpha beta alpha gamma " + " ".join(
        f"word{i:02d}" for i in range(40)))
    assert len(fp) == research._BRIEF_FINGERPRINT_TOKENS
    assert len(set(fp)) == len(fp)


def test_short_tokens_are_not_evidence():
    # "the", "of", "a" identify nothing.
    assert research.brief_fingerprint("the of a an is to in on at by") == []


def test_a_brief_too_thin_to_identify_anything_abstains():
    # ⛔ An empty list is ABSTAIN, and the predicate below turns it into None.
    assert research.brief_fingerprint("") == []
    assert research.brief_fingerprint("# Research Brief") == []
    assert research.brief_fingerprint("quantum error") == []


def test_a_brief_with_exactly_the_floor_number_of_tokens_is_usable():
    fp = research.brief_fingerprint("quantum surface transmon")
    assert fp == ["quantum", "surface", "transmon"]


# ── does the conversation hold our brief? ───────────────────────────────
def test_our_own_conversation_is_recognised():
    fp = research.brief_fingerprint(BRIEF)
    assert research.conversation_holds_brief(OURS, fp) is True


def test_a_strangers_finished_thread_is_not_ours():
    fp = research.brief_fingerprint(BRIEF)
    assert research.conversation_holds_brief(STRANGER, fp) is False


def test_the_answer_growing_underneath_our_brief_stays_ours():
    """The conversation gets very long as the agent works. The brief is still
    at the top, so identity must not decay as the report grows."""
    fp = research.brief_fingerprint(BRIEF)
    grown = OURS + ("\n\nSection %d: further analysis of unrelated matters. " * 400) % tuple(range(400))
    assert research.conversation_holds_brief(grown, fp) is True


def test_no_fingerprint_ABSTAINS_rather_than_refusing():
    # ⛔⛔ THE 08-27 LESSON. Nothing to compare against is not evidence of guilt.
    assert research.conversation_holds_brief(OURS, []) is None
    assert research.conversation_holds_brief(STRANGER, []) is None


def test_too_little_conversation_text_ABSTAINS():
    # A freshly opened tab, a composer that has not been submitted, a DOM read
    # that came back nearly empty — none of these is a stranger's thread.
    fp = research.brief_fingerprint(BRIEF)
    assert research.conversation_holds_brief("", fp) is None
    assert research.conversation_holds_brief("Loading…", fp) is None
    assert research.conversation_holds_brief("   \n  \t ", fp) is None


def test_the_text_floor_is_measured_on_the_collapsed_text_not_the_raw():
    """Whitespace is not evidence — a page of blank lines must abstain."""
    fp = research.brief_fingerprint(BRIEF)
    assert research.conversation_holds_brief("\n" * 500, fp) is None


def test_matching_is_word_boundary_so_a_token_cannot_hide_inside_a_word():
    fp = ["surface", "transmon", "fowler"]
    # Every token present only as a substring of something else.
    assert research.conversation_holds_brief(
        "resurfaced transmonitor fowlerish " * 20, fp) is False
    assert research.conversation_holds_brief(
        "surface transmon fowler " * 20, fp) is True


def test_a_partial_match_at_the_ratio_boundary():
    fp = ["alpha", "beta", "gamma", "delta", "epsilon"]  # 5 tokens, 60% = 3
    three = "alpha beta gamma " + "padding words to clear the text floor here"
    two = "alpha beta " + "padding words to clear the text floor here now"
    assert research.conversation_holds_brief(three, fp) is True
    assert research.conversation_holds_brief(two, fp) is False


def test_matching_ignores_case_and_collapsed_whitespace():
    fp = research.brief_fingerprint(BRIEF)
    shouty = OURS.upper().replace(" ", "   \n ")
    assert research.conversation_holds_brief(shouty, fp) is True


# ── the verdict ─────────────────────────────────────────────────────────
def test_the_verdict_is_one_of_three_words():
    fp = research.brief_fingerprint(BRIEF)
    assert research.chatgpt_identity_verdict(OURS, fp) == "ours"
    assert research.chatgpt_identity_verdict(STRANGER, fp) == "foreign"
    assert research.chatgpt_identity_verdict(OURS, []) == "unknown"
    assert research.chatgpt_identity_verdict("", fp) == "unknown"


def test_only_foreign_can_cost_a_leg_and_nothing_else_returns_it():
    """⛔⛔ THE PROPERTY THE WHOLE STEP TURNS ON. Every input that is not a
    positive content mismatch must come back as something a caller cannot act
    on destructively."""
    fp = research.brief_fingerprint(BRIEF)
    for text, fingerprint in [
        ("", fp), ("   ", fp), ("Loading…", fp),
        (OURS, []), (STRANGER, []), ("", []),
        (OURS, fp),
    ]:
        assert research.chatgpt_identity_verdict(text, fingerprint) != "foreign"


def test_the_url_argument_cannot_change_the_verdict():
    """⛔ The clock and the address are OBSERVATIONS now. If a URL could move
    this verdict, the address would still be deciding — which is the entire
    thing this step removes."""
    fp = research.brief_fingerprint(BRIEF)
    for url in ("", "https://chatgpt.com/c/68b1a0f0-aaaa-bbbb-cccc-dddddddddddd",
                "https://chatgpt.com/c/WEB:c3a7026f-1111-2222-3333-444444444444",
                "https://chatgpt.com/", "not a url at all"):
        assert research.chatgpt_identity_verdict(OURS, fp, url) == "ours"
        assert research.chatgpt_identity_verdict(STRANGER, fp, url) == "foreign"
        assert research.chatgpt_identity_verdict("", fp, url) == "unknown"


def test_an_undatable_id_is_no_longer_able_to_condemn_a_leg():
    """The 2026-08-27 kill, asked of the new decision: `/c/WEB:<uuid>` made the
    old predicate return False from `_chatgpt_convo_epoch`, every caller read
    that as "refuse", and a healthy leg died 7s after Send. Content does not
    care what the id looks like."""
    fp = research.brief_fingerprint(BRIEF)
    web_id = "https://chatgpt.com/c/WEB:c3a7026f-1111-2222-3333-444444444444"
    # The old address-shaped answer for this URL, unchanged and still available
    # as an observation:
    assert research._chatgpt_convo_epoch(web_id) is None
    # The new one, on the same healthy leg:
    assert research.chatgpt_identity_verdict(OURS, fp, web_id) == "ours"


# ── the cheap read ──────────────────────────────────────────────────────
class _Page:
    """A page that honours the SCRIPT it is handed, not just the call.

    ⛔⛔ THE FIRST VERSION IGNORED THE SCRIPT AND RETURNED A FIXED STRING, and
    mutation proved what that cost: restoring the `document.body.innerText`
    fallback — the defect this reader was corrected for — changed nothing any
    test could see, because no fake ever ran the JS. A double that cannot tell
    two implementations apart is not testing the implementation.

    `user_turn` is the conversation's opening user message; `body_text` is what
    the whole page reads as, which on a FRESH chat is the app chrome plus the
    sidebar listing the person's OTHER conversations.
    """

    def __init__(self, value=None, raises=False, body_text=""):
        self.value = value
        self.raises = raises
        self.body_text = body_text
        self.calls = 0

    async def evaluate(self, script, *args):
        self.calls += 1
        if self.raises:
            raise RuntimeError("Target page, context or browser has been closed")
        cap = args[0] if args else 4000
        out = self.value or ""
        if not out and "document.body.innerText" in script:
            out = self.body_text
        return out[:cap]


@pytest.mark.asyncio
async def test_the_first_user_message_is_read_from_the_page():
    page = _Page("Investigate surface-code thresholds")
    assert await research.read_chatgpt_first_user_message(page) == (
        "Investigate surface-code thresholds")
    assert page.calls == 1


@pytest.mark.asyncio
async def test_an_unreadable_page_abstains_instead_of_raising():
    # ⛔ A dead tab is the crash sweep's business, not this check's. Returning ""
    # makes the verdict `unknown`, which costs nothing.
    page = _Page(raises=True)
    assert await research.read_chatgpt_first_user_message(page) == ""
    fp = research.brief_fingerprint(BRIEF)
    assert research.chatgpt_identity_verdict("", fp) == "unknown"


@pytest.mark.asyncio
async def test_a_page_that_returns_nothing_abstains():
    assert await research.read_chatgpt_first_user_message(_Page(None)) == ""


@pytest.mark.asyncio
async def test_the_read_is_capped_so_a_huge_thread_cannot_be_pulled_whole():
    page = _Page("x" * 10)
    await research.read_chatgpt_first_user_message(page, cap=123)
    # The cap is passed to the page, not applied after — a 300KB read that is
    # then truncated has already crossed the bridge.
    assert page.calls == 1


# ── the sweep, driven ───────────────────────────────────────────────────
class _Tab:
    def __init__(self, url):
        self.url = url


def _sweep_leg(url):
    import time
    return {"page": _Tab(url), "url": url, "start_time": time.time() - 300}


@pytest.fixture()
def swept(monkeypatch):
    """The per-tick sweep, wired to record, with a counting reader."""
    import asyncio
    cards, reads = [], []
    monkeypatch.setattr(research, "fail_agent",
                        lambda key, title, details="", **kw: cards.append(key))
    monkeypatch.setattr(research, "_disarm_registry", lambda k: None)
    research._runtime.brief_fingerprints["chatgpt"] = research.brief_fingerprint(BRIEF)
    texts = {}

    async def _read(page):
        reads.append(page.url)
        return texts.get(page.url, "")

    def _run(pending, results=None):
        return asyncio.run(research._sweep_foreign_chatgpt_tabs(
            pending, {} if results is None else results, read_first_message=_read))

    yield _run, texts, reads, cards
    research._runtime.brief_fingerprints.pop("chatgpt", None)


def test_the_conversation_that_holds_our_brief_keeps_polling(swept):
    run, texts, _reads, cards = swept
    url = "https://chatgpt.com/c/68b1a0f0-1111-2222-3333-444455556666"
    texts[url] = OURS
    pending = {"ChatGPT": _sweep_leg(url)}
    assert run(pending) == []
    assert "ChatGPT" in pending and cards == []


def test_a_conversation_holding_someone_elses_brief_is_dropped(swept):
    run, texts, _reads, cards = swept
    url = "https://chatgpt.com/c/68b1a0f0-1111-2222-3333-444455556666"
    texts[url] = STRANGER
    pending = {"ChatGPT": _sweep_leg(url)}
    results = {}
    assert run(pending, results) == ["ChatGPT"]
    assert pending == {}
    assert results["ChatGPT"]["status"] == "wrong_conversation"
    assert cards == ["chatgpt"]


def test_an_UNDATABLE_id_no_longer_kills_a_healthy_leg(swept):
    """⛔⛔ THE 2026-08-27 KILL, ASKED OF THE NEW SWEEP. `/c/WEB:<uuid>` made the
    old predicate refuse, on this exact path, every tick, seven seconds after
    Send. The conversation holds our brief, so it lives."""
    run, texts, _reads, cards = swept
    url = "https://chatgpt.com/c/WEB:c3a7026f-1111-2222-3333-444444444444"
    texts[url] = OURS
    assert research._chatgpt_convo_epoch(url) is None      # still undatable
    pending = {"ChatGPT": _sweep_leg(url)}
    assert run(pending) == []
    assert cards == []


def test_the_read_is_not_repeated_while_the_tab_stays_put(swept):
    """Sixty-odd ticks in a half-hour run. The first user turn cannot change
    within one conversation, so paying a DOM read for each of them is waste."""
    run, texts, reads, _cards = swept
    url = "https://chatgpt.com/c/68b1a0f0-1111-2222-3333-444455556666"
    texts[url] = OURS
    pending = {"ChatGPT": _sweep_leg(url)}
    for _ in range(5):
        run(pending)
    assert reads == [url]


def test_A_DRIFT_MID_RUN_IS_CAUGHT_BECAUSE_THE_CACHE_IS_KEYED_ON_THE_URL(swept):
    """⛔⛔⛔ THE BUG THIS TEST EXISTS FOR, AND IT WAS NEARLY SHIPPED. Caching the
    first user turn PER PAGE is the obvious optimisation and it is wrong: it
    freezes the answer from before the drift, so the one thing this sweep exists
    to catch becomes the one thing it cannot see. A drift always lands on a
    different conversation id, so the cache is keyed on the URL."""
    run, texts, reads, cards = swept
    ours = "https://chatgpt.com/c/68b1a0f0-1111-2222-3333-444455556666"
    theirs = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"
    texts[ours], texts[theirs] = OURS, STRANGER
    leg = _sweep_leg(ours)
    pending = {"ChatGPT": leg}

    assert run(pending) == []            # healthy, and the read is now cached
    leg["page"].url = theirs             # the panel press navigated the tab
    assert run(pending) == ["ChatGPT"]   # ...and the sweep sees it
    assert reads == [ours, theirs]
    assert cards == ["chatgpt"]


def test_a_leg_with_no_fingerprint_is_never_dropped_however_foreign_it_reads(swept):
    run, texts, _reads, cards = swept
    research._runtime.brief_fingerprints.pop("chatgpt", None)
    url = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"
    texts[url] = STRANGER
    pending = {"ChatGPT": _sweep_leg(url)}
    assert run(pending) == []
    assert cards == []


class _HostilePage:
    """Every DOM call fails. The recording block runs before any of them."""
    url = "https://chatgpt.com/"

    def __getattr__(self, _name):
        async def _boom(*_a, **_k):
            raise RuntimeError("no browser in a unit test")
        return _boom


def test_the_real_paste_function_records_the_fingerprint_and_a_followup_cannot_replace_it():
    """⛔⛔ DRIVEN THROUGH THE REAL `verified_paste_brief`, not a copy of its
    recording block. A test that re-implements the code it is checking proves the
    test author can write the code twice — the failure this repo has hit nine
    times is the helper being right while nothing calls it.

    ⛔ FIRST PASTE ONLY. This same function pastes MID-RUN FOLLOW-UPS. If a
    follow-up replaced the fingerprint, the run would start identifying its own
    tab by the newest thing typed into it, so a resume-with-added-input would
    make the run stop recognising the conversation it is sitting in.
    """
    import asyncio
    research._runtime.brief_fingerprints.clear()
    try:
        async def _paste(text):
            try:
                await research.verified_paste_brief(
                    _HostilePage(), text, "ChatGPT", "test")
            except Exception:
                pass          # the paste itself cannot work here; the record does

        expected = research.brief_fingerprint(BRIEF)
        assert expected, "precondition"
        asyncio.run(_paste(BRIEF))
        assert research._runtime.brief_fingerprints["chatgpt"] == expected

        asyncio.run(_paste("Also please cover the Baltic rye trade routes and "
                           "sourdough starter cultures in considerable depth"))
        assert research._runtime.brief_fingerprints["chatgpt"] == expected
    finally:
        research._runtime.brief_fingerprints.clear()


def test_a_brief_too_thin_to_fingerprint_records_nothing_rather_than_an_empty_list():
    """An empty list and a missing key both abstain, but storing the empty list
    would block the real brief from ever being recorded on a later paste."""
    import asyncio
    research._runtime.brief_fingerprints.clear()
    try:
        async def _paste(text):
            try:
                await research.verified_paste_brief(
                    _HostilePage(), text, "ChatGPT", "test")
            except Exception:
                pass

        asyncio.run(_paste("too short"))
        assert "chatgpt" not in research._runtime.brief_fingerprints
        asyncio.run(_paste(BRIEF))
        assert research._runtime.brief_fingerprints["chatgpt"] == research.brief_fingerprint(BRIEF)
    finally:
        research._runtime.brief_fingerprints.clear()


def test_each_platform_gets_its_own_fingerprint():
    """Three agents, three tabs, three briefs — and only ChatGPT's is consulted
    by the sweep, so a shared slot would let Gemini's paste answer for it."""
    import asyncio
    research._runtime.brief_fingerprints.clear()
    try:
        async def _paste(text, platform):
            try:
                await research.verified_paste_brief(
                    _HostilePage(), text, platform, "test")
            except Exception:
                pass

        asyncio.run(_paste(BRIEF, "ChatGPT"))
        asyncio.run(_paste("Entirely different subject matter about maritime "
                           "insurance underwriting practices", "Gemini"))
        assert research._runtime.brief_fingerprints["chatgpt"] != \
            research._runtime.brief_fingerprints["gemini"]
        assert research._runtime.brief_fingerprints["chatgpt"] == research.brief_fingerprint(BRIEF)
    finally:
        research._runtime.brief_fingerprints.clear()


# ── the liveness helper, and the two sites that ran the old broken copy ──
def test_a_live_conversation_needs_BOTH_an_id_and_no_positive_foreign_verdict(monkeypatch):
    """⛔ NOT simply `not _chatgpt_tab_is_foreign(url)`. That predicate abstains
    on a bare host, so the naive inversion calls an EMPTY COMPOSER alive — the
    exact false-health claim the 2026-08-05 incident was made of, where being in
    A conversation was read as being in OURS."""
    old = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"   # 08-04
    new = "https://chatgpt.com/c/6a7377d5-8f14-8320-a5d5-7f9a5a5f0f10"   # 08-05
    between = research._chatgpt_convo_epoch(old) + 2 * research._CONVO_AGE_SLACK_SEC
    monkeypatch.setattr(research, "_run_start_epoch", lambda: between)

    assert research.chatgpt_tab_is_live_conversation("https://chatgpt.com/") is False
    assert research.chatgpt_tab_is_live_conversation("") is False
    assert research.chatgpt_tab_is_live_conversation(old) is False       # positively stale
    assert research.chatgpt_tab_is_live_conversation(new) is True


def test_an_undatable_id_now_reads_as_LIVE_not_as_a_dead_page(monkeypatch):
    """⛔⛔ THE 2026-08-27 BUG IN TWO MORE PLACES. Both liveness reads called the
    dating predicate directly, so `/c/WEB:<uuid>` came back False — and False
    here means "not alive". One of them logs `page is at a conversation that is
    NOT this run's` about a healthy leg and drops it into the dead-page path."""
    monkeypatch.setattr(research, "_run_start_epoch", lambda: 1_800_000_000.0)
    web = "https://chatgpt.com/c/WEB:c3a7026f-1111-2222-3333-444444444444"
    assert research._chatgpt_convo_epoch(web) is None            # still undatable
    assert research._chatgpt_conversation_is_ours(web) is False  # the old answer
    assert research.chatgpt_tab_is_live_conversation(web) is True


def test_both_liveness_sites_go_through_the_one_helper():
    """⭐ Stretch 7 spent a day on a safety gate that existed TWICE, where the
    copy everybody remembered got fixed and the copy every Settings button used
    did not. Neither site may re-inline the predicate."""
    from conftest import code_only
    from pathlib import Path
    src = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    assert src.count("chatgpt_tab_is_live_conversation(") == 3   # 1 def + 2 sites
    # And nothing outside the identity block dates a conversation directly.
    body = src[src.index("async def run_phase2"):]
    assert "_chatgpt_conversation_is_ours(" not in body


# ── the landing override: content may only SAVE a leg ───────────────────
def test_content_can_turn_a_foreign_landing_verdict_around():
    """The 2026-08-05 shape: a mid-run settings write moved the run's own start
    time forward, so the run began calling its OWN fresh conversation foreign
    seconds after creating it. If our brief is in there, the clock is wrong."""
    fp = research.brief_fingerprint(BRIEF)
    assert research.chatgpt_landing_content_override("foreign", OURS, fp) == "ours"


def test_content_can_NEVER_create_a_foreign_verdict():
    """⛔⛔ THE ASYMMETRY IS THE WHOLE DESIGN. Thirty seconds after Send is the
    worst moment to ask a conversation what it contains — the turn may not have
    rendered — so every non-foreign verdict must pass through untouched, and a
    stranger's text must not be able to condemn one that was fine."""
    fp = research.brief_fingerprint(BRIEF)
    for verdict in ("ours", "unchanged", "undatable", "no_conversation"):
        for text in (OURS, STRANGER, ""):
            assert research.chatgpt_landing_content_override(verdict, text, fp) == verdict


def test_an_unrendered_or_unreadable_conversation_leaves_foreign_standing():
    """Silence is not an acquittal either — the override needs positive proof."""
    fp = research.brief_fingerprint(BRIEF)
    for text in ("", "   ", "Loading…"):
        assert research.chatgpt_landing_content_override("foreign", text, fp) == "foreign"
    # ...and with nothing to compare against, likewise.
    assert research.chatgpt_landing_content_override("foreign", OURS, []) == "foreign"


def test_a_strangers_thread_still_lands_as_foreign():
    fp = research.brief_fingerprint(BRIEF)
    assert research.chatgpt_landing_content_override("foreign", STRANGER, fp) == "foreign"


def test_the_landing_loop_consults_the_override_before_refusing():
    """⛔ The helper being right proves nothing if the loop does not ask it. The
    loop lives in a closure inside the 700-line send function, so this is a
    call-site pin — read with comments blanked."""
    import inspect
    from conftest import code_only
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    at = src.index('_verdict = _chatgpt_landing_verdict(_last, _pre_send_url)')
    window = src[at:at + 1200]
    assert "chatgpt_landing_content_override(" in window
    # ...and it must sit BEFORE the refusal, or it changes nothing.
    assert (window.index("chatgpt_landing_content_override(")
            < window.index('return False, _last, "conversation_predates_this_run"'))


# ── the pre-send / setup-failure gate, driven ───────────────────────────
class _GatePage:
    """A tab whose conversation opens with `first_turn`. "" = a FRESH chat, which
    has no user turn at all — the case the gate must never refuse.

    `body_text` is what the whole page reads as: on a fresh chat that is the app
    chrome plus the SIDEBAR, which lists the person's other conversations. It is
    only reachable by a reader that falls back to the page's own text — which is
    the mistake this double exists to make visible.
    """

    def __init__(self, url, first_turn="", body_text=""):
        self.url = url
        self._first_turn = first_turn
        self._body_text = body_text

    async def evaluate(self, script, *args):
        cap = args[0] if args else 4000
        out = self._first_turn
        if not out and "document.body.innerText" in script:
            out = self._body_text
        return out[:cap]


@pytest.fixture()
def gate(monkeypatch):
    import asyncio
    cards = []
    monkeypatch.setattr(research, "fail_agent",
                        lambda key, title, details="", **kw: cards.append(key))

    async def _new_chat(page, label):
        return True

    monkeypatch.setattr(research, "_chatgpt_force_new_chat", _new_chat)
    research._runtime.brief_fingerprints["chatgpt"] = research.brief_fingerprint(BRIEF)

    def _run(page, *, platform_l="chatgpt", recover=True):
        return asyncio.run(research._refuse_foreign_chatgpt_tab(
            page, "ChatGPT", platform_l, "ChatGPT", page.url,
            recover=recover, why="send")), cards

    yield _run
    research._runtime.brief_fingerprints.pop("chatgpt", None)


def test_the_gate_refuses_a_strangers_finished_thread(gate):
    """⛔ TEETH KEPT. This is the only thing between a composer holding THIS
    run's brief and somebody else's finished conversation."""
    refused, cards = gate(_GatePage("https://chatgpt.com/c/abc", STRANGER))
    assert refused is True
    assert cards == ["chatgpt"]


def test_the_gate_does_NOT_refuse_a_fresh_chat(gate):
    """⛔⛔ THE CASE THE ADDRESS-BASED CHECK COULD NOT SEE, AND THE ONE A NAIVE
    CONTENT CHECK GETS WRONG. A fresh chat has NO user turn — the read returns
    "" and the verdict is `unknown`. Refusing here would mean no run ever sends
    anything, and a reader that fell back to the page's own text would find the
    sidebar full of the person's other conversations and refuse on those."""
    refused, cards = gate(_GatePage("https://chatgpt.com/", ""))
    assert refused is False
    assert cards == []


def test_the_gate_does_not_refuse_our_own_conversation(gate):
    refused, cards = gate(_GatePage("https://chatgpt.com/c/abc", OURS))
    assert refused is False and cards == []


def test_the_gate_abstains_on_an_undatable_id_that_holds_our_brief(gate):
    """The 2026-08-27 kill asked of the gate: the id cannot be dated, and it
    does not matter, because the conversation says whose it is."""
    refused, cards = gate(_GatePage(
        "https://chatgpt.com/c/WEB:c3a7026f-1111-2222-3333-444444444444", OURS))
    assert refused is False and cards == []


def test_the_gate_is_scoped_to_chatgpt(gate):
    """Another platform's tab is not ours to judge — and the fingerprint we hold
    is ChatGPT's, so judging Claude's conversation against it would refuse every
    healthy Claude leg."""
    refused, cards = gate(_GatePage("https://claude.ai/chat/abc", STRANGER),
                          platform_l="claude")
    assert refused is False and cards == []


def test_the_gate_abstains_when_this_run_has_no_fingerprint(gate, monkeypatch):
    research._runtime.brief_fingerprints.pop("chatgpt", None)
    refused, cards = gate(_GatePage("https://chatgpt.com/c/abc", STRANGER))
    assert refused is False and cards == []


SIDEBAR = (
    "ChatGPT  New chat  Search chats  Library  Sora  GPTs  Projects  Chats  "
    "Sourdough baking history in northern Europe  Baltic rye starters and trade  "
    "Maritime insurance underwriting practices  Regional bread culture notes  "
    "Upgrade plan  More access to the best models"
)


def test_a_fresh_chats_SIDEBAR_must_never_become_the_evidence(gate):
    """⛔⛔⛔ THE DEFECT THIS READER WAS CORRECTED FOR, AND MUTATION IS WHAT FOUND
    THE HOLE IN THE GUARD. The reader used to fall back to the page's own text
    when no user turn was found. On a FRESH chat there is no user turn — so it
    would return the app chrome and the sidebar, which lists the person's OTHER
    conversations, none of them matching our brief. The pre-send gate would read
    that as a stranger's finished thread and refuse a perfectly healthy send.
    The sidebar would literally be the evidence against the run.
    """
    refused, cards = gate(_GatePage("https://chatgpt.com/", "", body_text=SIDEBAR))
    assert refused is False, "the sidebar was read as somebody else's conversation"
    assert cards == []


@pytest.mark.asyncio
async def test_the_reader_returns_NOTHING_when_there_is_no_user_turn():
    """The same rule one level down, so the property is pinned where it lives."""
    page = _Page(value="", body_text=SIDEBAR)
    assert await research.read_chatgpt_first_user_message(page) == ""


@pytest.mark.asyncio
async def test_the_reader_returns_the_user_turn_when_there_is_one():
    page = _Page(value=OURS, body_text=SIDEBAR)
    assert await research.read_chatgpt_first_user_message(page) == OURS


def test_a_leg_with_no_fingerprint_is_not_even_READ(swept):
    """⛔ AND THE GUARD MUST COME FIRST, not merely produce the same answer. With
    no fingerprint every verdict is `unknown`, so a sweep that read the page
    anyway would behave identically — and pay a DOM round-trip per leg on every
    one of the sixty-odd ticks a half-hour run makes, forever, for an answer it
    cannot use. Mutation caught this: deleting the guard changed no outcome."""
    run, texts, reads, cards = swept
    research._runtime.brief_fingerprints.pop("chatgpt", None)
    url = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"
    texts[url] = STRANGER
    pending = {"ChatGPT": _sweep_leg(url)}
    assert run(pending) == []
    assert reads == [], "the sweep read a page it had nothing to compare against"
    assert cards == []
