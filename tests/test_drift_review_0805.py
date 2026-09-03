"""The adversarial review of the 2026-08-05 tab-drift wave — the findings that survived
triage, and only those.

The review returned ~25 second-tier items. Verifying each against the real code (by
EXECUTING it, which is what moved three verdicts) left 6 worth fixing, 1 wrong as
stated, 4 not worth the churn, and 2 for later. This file covers the four that needed
new coverage of their own; the other three landed in the files that already owned their
region (`test_chatgpt_row_scope_0805.py`, `test_alert_copy_hygiene_63.py`).

  f3   Claude's Effort trigger is the one `_SR_CLICK_MARK` writer the new ChatGPT row
       filter does not cover, and it has the identical shape that navigated the ChatGPT
       tab: a candidate set matched against `document`, chosen by TEXT PREFIX, pressed
       for real. `li` is in that set.
  f1   every refusal hands back a LIVE page on the conversation it just declared
       foreign, and no identity check sits on the poll/scrape/extract path — so the
       round-robin resumes polling it, and a foreign report still lands whenever the
       topic guard cannot judge (<3 anchors, or under the 20KB floor).
  f13e the panel's structural leaf pass truncates at 6,000 nodes in DOCUMENT order,
       which drops the NEWEST rows — the same symptom DGOPS-9614 was about, one panel
       size larger. Proved by building the panel and reading the result.
  f10  the sweep clears a rejected leg's text, but `_build_phase2_to_phase3_handoff`
       adds the conversation link regardless of whether any text survived, so the run
       published the foreign chat as its ChatGPT source.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, evaluate_js, run_js  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════════
# f3 — Claude's Effort trigger must never be a link, and never be prose.
# ═════════════════════════════════════════════════════════════════════════════

EFFORT_MARK_JS = None


def _effort_js():
    global EFFORT_MARK_JS
    if EFFORT_MARK_JS is None:
        EFFORT_MARK_JS = evaluate_js(research.setup_claude_dr,
                                     contains="const linky = el =>")
    return EFFORT_MARK_JS


def _mark(spec):
    out = run_js(spec, _effort_js(),
                 {"attr": research._SR_CLICK_MARK, "value": "claude-effort"})
    return out["ret"]


def _sidebar_thread(title):
    """claude.ai lists recent conversations as links. This is the shape that made the
    ChatGPT sidebar reachable, transposed: an `li` wrapping the anchor."""
    return el("li", {}, "", [el("a", {"href": "/chat/8f3c-1029"}, title)])


def _effort_row(value="Max"):
    return el("div", {"role": "menuitem"}, f"Effort {value}")


def _popover(rows):
    return el("div", {"role": "menu"}, "", rows)


def test_the_real_effort_row_is_still_found():
    """First, the thing that must keep working — a guard that cannot find its target is
    not a guard, it is an outage."""
    ret = _mark(el("body", {}, "", [_popover([_effort_row()])]))
    assert ret["marked"] is True
    assert ret["text"] == "effort max"


def test_a_sidebar_thread_titled_effort_is_refused():
    """The document-order trap. The sidebar precedes the popover, so the old
    `els.find(...)` took the thread — and `_sr_real_click` presses for real, which on a
    link means navigation. Exactly the 11:08 chain, on the other platform."""
    spec = el("body", {}, "", [
        el("nav", {}, "", [_sidebar_thread("Effort estimates")]),
        _popover([_effort_row()]),
    ])
    ret = _mark(spec)
    assert ret["marked"] is True
    assert ret["text"] == "effort max", "the menu row must win over the sidebar link"
    assert ["link", "effort estimates"] in ret["rejected"], ret["rejected"]


def test_a_bare_anchor_row_is_refused():
    """Arm 1 on its own: the candidate IS the link."""
    spec = el("body", {}, "", [
        el("a", {"href": "/chat/1", "role": "menuitem"}, "Effort estimates"),
        _popover([_effort_row()]),
    ])
    assert _mark(spec)["text"] == "effort max"


def test_a_row_nested_inside_a_link_is_refused():
    """Arm 2: the candidate sits INSIDE the link, so pressing it still navigates."""
    spec = el("body", {}, "", [
        el("a", {"href": "/chat/1"}, "", [el("div", {"role": "menuitem"}, "Effort notes")]),
        _popover([_effort_row()]),
    ])
    assert _mark(spec)["text"] == "effort max"


def test_a_row_wrapping_a_link_is_refused():
    """Arm 3, and it is the one the ChatGPT filter does NOT have — that filter's groups
    are the rows themselves, while this candidate set includes bare `li`, which is how
    claude.ai wraps a conversation anchor. `closest` cannot see a DESCENDANT."""
    spec = el("body", {}, "", [_sidebar_thread("Effort planning"),
                               _popover([_effort_row()])])
    ret = _mark(spec)
    assert ret["text"] == "effort max"
    assert any(r[0] == "link" for r in ret["rejected"]), ret["rejected"]


def test_claudes_own_reply_is_not_mistaken_for_the_effort_row():
    """A markdown bullet in the transcript is an `li` too. This is a plausible reading
    of this step's corpus — nine "'Max' effort not found in submenu" WARNs against one
    success, i.e. presses that landed on something that was never a menu."""
    prose = ("Effort should be set to Max here because the research tool benefits from "
             "the longer reasoning budget on multi-source questions")
    spec = el("body", {}, "", [
        el("ul", {}, "", [el("li", {}, prose)]),
        _popover([_effort_row()]),
    ])
    ret = _mark(spec)
    assert ret["text"] == "effort max"
    assert any(r[0] == "long" for r in ret["rejected"]), ret["rejected"]


def test_a_row_that_merely_mentions_effort_later_is_not_a_candidate():
    """The prefix test is unchanged — this pins that the new arms did not widen it."""
    spec = el("body", {}, "", [_popover([el("div", {"role": "menuitem"}, "Set effort")])])
    assert _mark(spec)["marked"] is False


def test_an_offscreen_effort_row_is_still_skipped():
    spec = el("body", {}, "", [
        el("div", {"role": "menu", "hidden": ""}, "", [_effort_row("Low")]),
        _popover([_effort_row("Max")]),
    ])
    assert _mark(spec)["text"] == "effort max"


def test_nothing_to_mark_reports_what_it_saw():
    """`_eff_marked` false plus an empty log used to be indistinguishable from "the
    popover never opened". The rejected list is what the next capture will be read
    against — container-scoping is the stronger fix and needs one."""
    spec = el("body", {}, "", [_sidebar_thread("Effort estimates")])
    ret = _mark(spec)
    assert ret["marked"] is False
    assert ret["rejected"] == [["link", "effort estimates"]]


def test_stale_marks_are_cleared_before_a_new_one_is_written():
    """Unchanged behaviour, pinned because the rewrite touched these lines: a leftover
    mark from an earlier step would make `_sr_real_click` press the wrong element."""
    stale = el("div", {research._SR_CLICK_MARK: "claude-effort"}, "something old")
    spec = el("body", {}, "", [stale, _popover([_effort_row()])])
    js = _effort_js()
    out = run_js(spec, js + "\n", {"attr": research._SR_CLICK_MARK,
                                   "value": "claude-effort"})
    assert out["ret"]["marked"] is True
    # The shim rebuilds the tree per run, so assert the JS clears rather than that this
    # object changed: a second pass over the SAME document must still find one mark.
    assert "removeAttribute(P.attr)" in js


def test_the_effort_marker_is_bounded_and_reports_at_most_five_rejections():
    """A page with a hundred "Effort…" threads must not put a hundred titles in a log
    line — and titles are user content."""
    spec = el("body", {}, "", [
        el("nav", {}, "", [_sidebar_thread("Effort thread") for _ in range(30)]),
        _popover([_effort_row()]),
    ])
    ret = _mark(spec)
    assert ret["text"] == "effort max"
    assert len(ret["rejected"]) == 5, ret["rejected"]


# ═════════════════════════════════════════════════════════════════════════════
# f10 — a link is a SOURCE, so a rejected leg must not publish one.
# ═════════════════════════════════════════════════════════════════════════════

INCIDENT_TOPIC = ("NemoClaw vs NemoHermes vs Nemotron and also about OpenShell "
                  "and how all of these can be used for security")
FOREIGN_URL = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"  # 08-04 22:46
OURS_URL = "https://chatgpt.com/c/6a7377d5-8f14-8320-a5d5-7f9a5a5f0f10"     # 08-05 10:50


@pytest.fixture()
def run_dir():
    d = Path(tempfile.mkdtemp())
    (d / "documents").mkdir()
    (d / "meta.json").write_text(json.dumps({"topic": INCIDENT_TOPIC}),
                                 encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def _clean_runtime():
    """⛔ 2026-08-28: this used to save/restore `_runtime.agent_share_urls`, the
    P2 share-URL stash removed with the platform share step (stretch 6.6B). The
    handoff now reads each agent's conversation URL straight off `results`, so
    there is no cross-test runtime state left to isolate here — but the fixture
    stays, autouse, because `p2_links_for_p3` IS written by every `_handoff`
    call below and a leftover would make the next test pass on the last one's
    links."""
    before = dict(research._runtime.p2_links_for_p3)
    research._runtime.p2_links_for_p3 = {}
    yield
    research._runtime.p2_links_for_p3 = before


def _golden_retrievers(n=25_000):
    return ("Golden retrievers are a friendly breed with a notable cancer rate. " *
            (n // 66 + 1))[:n]


def _on_topic(n=25_000):
    return ("Nemotron and OpenShell both expose a libkrun microVM boundary. " *
            (n // 62 + 1))[:n]


RID = "rid_2026_09_02"


@pytest.fixture(autouse=True)
def _research_id(monkeypatch):
    """⭐ 2026-09-02, stretch 7.5 step 5 — the hand-off publishes each surviving
    agent's report page in OUR app, so these tests need a research id or every
    expected value collapses to the bare `/documents` index and the assertions
    stop telling one agent from another."""
    monkeypatch.setattr(research, "_fb_research_id", RID)


def _ours(agent_key: str) -> str:
    """What a surviving leg publishes now: its report page in our app."""
    return f"/documents?open={RID}:{agent_key}"


def _handoff(results, run_dir):
    research._build_phase2_to_phase3_handoff(results, run_dir)
    return dict(research._runtime.p2_links_for_p3)


def test_the_incident_link_is_not_published_after_the_sweep_rejects_it(run_dir):
    """The whole chain, executed end to end: sweep then handoff. The 11:08 run logged
    `Links saved: {'ChatGPT': '…/c/6a72ce1e…'}` with the text ALREADY blanked, because
    the builder reads the url on a line of its own."""
    results = {"ChatGPT": {"status": "done", "text": _golden_retrievers(),
                           "url": FOREIGN_URL, "verified": True}}
    assert research.apply_off_topic_sweep(results, run_dir) == ["ChatGPT"]
    assert _handoff(results, run_dir) == {}


def test_an_on_topic_leg_still_publishes_its_link(run_dir):
    """The half that must not regress: a surviving leg still publishes a row.

    ⛔⛔ 2026-09-02, stretch 7.5 step 5 — THIS DOCSTRING SAID "dropping every link
    would silently halve what NotebookLM receives", AND THAT WAS NEVER TRUE. The
    link map is written to `links.json` and returned; NotebookLM is fed
    `p2_md_files_for_p3`, the markdown FILES, and never reads this map. So the
    test defended the right behaviour with a reason that does not exist — which
    is why nobody questioned the value it was defending: an agent's private
    conversation address.

    ▶ What it defends now is the same shape with an address of ours: the leg
    survived, so it publishes; and what it publishes is the report page in our
    own app, which is the same destination phase 2 already hands the app."""
    results = {"Gemini": {"status": "done", "text": _on_topic(),
                          "url": "https://gemini.google.com/app/abc123",
                          "verified": True}}
    assert research.apply_off_topic_sweep(results, run_dir) == []
    assert _handoff(results, run_dir) == {"Gemini": _ours("gemini")}


def test_no_surviving_leg_publishes_the_conversation_address(run_dir):
    """⛔⛔ THE STEP-5 INVARIANT, stated as a universal rather than a sample. Every
    agent survives here, so every one of them publishes — and not one published
    value may be the address it was judged on."""
    convos = {
        "ChatGPT": "https://chatgpt.com/c/6a8d6000-0000-83ea-abcb-acdf3db",
        "Gemini": "https://gemini.google.com/app/abc123",
        "Claude": "https://claude.ai/chat/2f8a",
    }
    results = {n: {"status": "done", "text": _on_topic(), "url": u, "verified": True}
               for n, u in convos.items()}
    published = _handoff(results, run_dir)
    assert set(published) == set(convos), "every surviving leg still publishes"
    for name, url in published.items():
        assert url == _ours(name.lower()), name
        assert url not in convos.values()
        assert not url.startswith("http"), (
            "an in-app page is a path on our own origin, never an absolute address")


def test_the_guards_still_read_the_conversation_address_they_judge(monkeypatch, run_dir):
    """⭐ WHAT IS PUBLISHED CHANGED; WHAT IS JUDGED DID NOT. The age test decodes
    an id out of the ChatGPT address, so the hand-off must still READ it — if the
    read went away with the publish, the drop could not happen and nothing else
    in the suite would notice."""
    monkeypatch.setattr(
        research, "_run_start_epoch",
        lambda: research._chatgpt_convo_epoch(FOREIGN_URL)
        + 2 * research._CONVO_AGE_SLACK_SEC + 1.0)
    # A leg with no address at all publishes nothing — the read is load-bearing.
    empty = {"ChatGPT": {"status": "done", "text": _on_topic(), "url": "",
                         "verified": True}}
    assert _handoff(empty, run_dir) == {}
    foreign = {"ChatGPT": {"status": "done", "text": _on_topic(), "url": FOREIGN_URL,
                           "verified": True}}
    assert _handoff(foreign, run_dir) == {}, "and a foreign one is dropped"


def test_a_failed_text_extraction_does_NOT_cost_the_leg_its_link(run_dir):
    """⚠ Deliberately not gated on `text`. A URL whose scrape failed is still a
    real, on-topic source that NotebookLM can read for itself.

    ⛔ 2026-08-28: the url used to come from `_runtime.agent_share_urls` — the
    public share the P2 extractor stashed. That extractor is gone, so the url
    is the conversation URL on `results`, which is what the handoff always fell
    back to. The rule under test is unchanged: an empty `text` does not cost the
    leg its link."""
    results = {"Claude": {"status": "done", "text": "",
                          "url": "https://claude.ai/chat/2f8a", "verified": False}}
    assert _handoff(results, run_dir) == {"Claude": _ours("claude")}


def test_a_rejected_leg_cannot_smuggle_its_url_back_in(run_dir):
    """The rejection is read off the RESULT, not off the url — which is what let
    the 11:08 run ship an unrelated conversation to NotebookLM as a source.

    ⛔ 2026-08-28: this used to prove the rule against a stashed SHARE url that
    outranked the conversation one. With the share step gone there is one url,
    and the rule it has to survive is the same one: a leg the sweep rejected
    publishes nothing, however good its url looks."""
    results = {"ChatGPT": {"status": "done", "text": _golden_retrievers(),
                           "url": "https://chatgpt.com/c/deadbeef", "verified": True}}
    assert research.apply_off_topic_sweep(results, run_dir) == ["ChatGPT"]
    assert _handoff(results, run_dir) == {}


def test_a_foreign_conversation_is_dropped_even_when_the_guard_cannot_judge(monkeypatch,
                                                                           run_dir):
    """The belt, and the reason it is worth having: the sweep is INERT when the topic
    yields too few anchors or the text is under the size floor. Nothing gets marked
    rejected — but the tab is still provably not this run's."""
    monkeypatch.setattr(research, "_run_start_epoch",
                        lambda: research._chatgpt_convo_epoch(OURS_URL))
    short = "Golden retrievers are friendly."           # under the size floor
    results = {"ChatGPT": {"status": "done", "text": short, "url": FOREIGN_URL,
                           "verified": True}}
    assert research.apply_off_topic_sweep(results, run_dir) == [], (
        "precondition: the guard abstains on text this short")
    assert _handoff(results, run_dir) == {}


def test_our_own_conversation_link_survives_the_identity_belt(monkeypatch, run_dir):
    monkeypatch.setattr(research, "_run_start_epoch",
                        lambda: research._chatgpt_convo_epoch(FOREIGN_URL) + 300.0)
    results = {"ChatGPT": {"status": "done", "text": _on_topic(), "url": OURS_URL,
                           "verified": True}}
    assert _handoff(results, run_dir) == {"ChatGPT": _ours("chatgpt")}


def test_the_identity_belt_is_scoped_to_the_chatgpt_leg(monkeypatch, run_dir):
    """⚠ A false positive I nearly shipped. The date test reads an id out of
    `/c/<hex>`; run another platform's url through it and any id whose first hex group
    decodes to a plausible older timestamp loses its link for nothing.

    Scoped by OUR agent key rather than by a hostname literal — a hostname literal in
    a gate is what took Phase 3 down when NotebookLM's domain moved, four gates at
    once.
    """
    old = research._chatgpt_convo_epoch(FOREIGN_URL)
    monkeypatch.setattr(
        research, "_run_start_epoch",
        lambda: old + 2 * research._CONVO_AGE_SLACK_SEC + 1.0)
    borrowed = "https://some-other-agent.example.com/c/6a72ce1e-2284-83ea-abcb-acdf3db"
    assert research._chatgpt_tab_is_foreign(borrowed) is True, (
        "precondition: the bare predicate would reject this url")
    results = {"Gemini": {"status": "done", "text": _on_topic(), "url": borrowed,
                          "verified": True}}
    assert _handoff(results, run_dir) == {"Gemini": _ours("gemini")}


def test_the_sweep_leaves_the_url_alone_for_resume_reconnect(run_dir):
    """⚠ My first fix direction was to clear the url. It is documented "conversation
    URL — for resume reconnect", so clearing it would break reattaching. The rejection
    is recorded instead."""
    results = {"ChatGPT": {"status": "done", "text": _golden_retrievers(),
                           "url": FOREIGN_URL, "verified": True}}
    research.apply_off_topic_sweep(results, run_dir)
    assert results["ChatGPT"]["url"] == FOREIGN_URL
    assert results["ChatGPT"]["off_topic_rejected"] is True


def test_an_untouched_leg_carries_no_rejection_flag(run_dir):
    results = {"Gemini": {"status": "done", "text": _on_topic(), "url": "u",
                          "verified": True}}
    research.apply_off_topic_sweep(results, run_dir)
    assert "off_topic_rejected" not in results["Gemini"]


# ═════════════════════════════════════════════════════════════════════════════
# f1 — the poll path had no identity gate, so a refusal's live page kept polling.
# ═════════════════════════════════════════════════════════════════════════════

class _Tab:
    def __init__(self, url):
        self._url = url

    @property
    def url(self):
        return self._url


class _DeadTab:
    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")


SWEEP_BRIEF = (
    "# Research Brief\n\nInvestigate surface-code thresholds for quantum error "
    "correction, focusing on transmon qubit decoherence budgets."
)
# What each conversation's first user turn says. This is what the sweep reads now.
OURS_TEXT = ("Investigate surface-code thresholds for quantum error correction, "
             "focusing on transmon qubit decoherence budgets.")
FOREIGN_TEXT = ("Write me a 500-word essay about the history of sourdough baking "
                "in northern Europe, with attention to rye starters.")


@pytest.fixture()
def sweep(monkeypatch):
    """The sweep, wired to record instead of emitting.

    ⛔⛔ REWRITTEN 2026-09-02 (stretch 7.5), NOT SILENCED. Every test below kept
    its intent; only the evidence changed. The sweep used to decode a creation
    time out of the conversation URL and compare it to when the run started —
    this machine's clock against OpenAI's — so this fixture's job was to pin
    `_run_start_epoch` between the incident's two real ids. It now asks the
    conversation whether it still contains the brief we pasted, so the fixture's
    job is to say what each conversation CONTAINS.

    The two real incident ids are kept and still asserted to be twelve hours
    apart, because they are the evidence the incident happened — they are simply
    no longer what makes the decision.
    """
    cards = []
    disarmed = []
    monkeypatch.setattr(research, "fail_agent",
                        lambda key, title, details="", **kw: cards.append(
                            (key, title, details)))
    monkeypatch.setattr(research, "_disarm_registry", lambda k: disarmed.append(k))
    old = research._chatgpt_convo_epoch(FOREIGN_URL)
    new = research._chatgpt_convo_epoch(OURS_URL)
    assert new - old > 4 * research._CONVO_AGE_SLACK_SEC, (
        "the incident's own ids, kept as the record of it")

    research._runtime.brief_fingerprints["chatgpt"] = research.brief_fingerprint(
        SWEEP_BRIEF)
    assert research._runtime.brief_fingerprints["chatgpt"], "precondition"

    # ⭐ The conversation's first user turn, per URL. Anything unnamed reads as
    # empty, which is the sweep's ABSTAIN — a bare composer, a tab mid-navigation.
    texts = {FOREIGN_URL: FOREIGN_TEXT, OURS_URL: OURS_TEXT}

    async def _read(page):
        try:
            return texts.get(page.url or "", "")
        except Exception:
            return ""

    def _run(pending, results=None):
        results = {} if results is None else results
        dropped = asyncio.run(research._sweep_foreign_chatgpt_tabs(
            pending, results, read_first_message=_read))
        return dropped, pending, results, cards, disarmed

    yield _run
    research._runtime.brief_fingerprints.pop("chatgpt", None)


def _leg(url, start=None):
    import time as _t
    return {"page": _Tab(url), "url": url, "start_time": start or (_t.time() - 300)}


def test_a_chatgpt_leg_on_last_nights_thread_is_dropped(sweep):
    """The 39 minutes. Nothing in the round-robin ever asked whose conversation this
    was, so it polled, scraped and finally extracted it."""
    dropped, pending, results, cards, disarmed = sweep({"ChatGPT": _leg(FOREIGN_URL)})
    assert dropped == ["ChatGPT"]
    assert pending == {}
    assert results["ChatGPT"]["status"] == "wrong_conversation"
    assert results["ChatGPT"]["text"] == ""
    assert results["ChatGPT"]["page"] is None
    assert disarmed == ["chatgpt"]
    assert len(cards) == 1


def test_our_own_conversation_keeps_polling(sweep):
    """The polarity assertion. Inverting the predicate kills every healthy P2 leg on
    its first tick — this is the test that would notice."""
    dropped, pending, results, cards, _ = sweep({"ChatGPT": _leg(OURS_URL)})
    assert dropped == []
    assert "ChatGPT" in pending
    assert results == {}
    assert cards == []


def test_a_bare_composer_keeps_polling(sweep):
    """A tab that has not minted an id yet has nothing to date, and killing it would
    fail every leg in the window between send and the SPA's URL update."""
    dropped, pending, _r, cards, _ = sweep({"ChatGPT": _leg("https://chatgpt.com/")})
    assert dropped == [] and "ChatGPT" in pending and cards == []


def test_the_sweep_is_scoped_to_chatgpt(sweep):
    """Gemini and Claude URLs must never be run through a ChatGPT-shaped date test.

    ⚠ The first version of this used `…/app/6a72ce1e` and `…/chat/6a72ce1e`, which
    carry no `/c/` — so the predicate abstained on them anyway and deleting the
    `key != "chatgpt"` guard changed NOTHING. It survived mutation, correctly. A
    scoping test has to hand the predicate something it WOULD reject; the whole point
    of the guard is that another platform's url shape is not ours to interpret.

    ⛔ REWRITTEN 2026-09-02 and the trap above is the reason it needed care. The
    old precondition — "the URL-dating predicate rejects this" — no longer says
    anything about what the sweep does, because the sweep stopped dating URLs.
    A borrowed URL is now saved by the key scoping only if its CONTENT would
    otherwise condemn it, so the fixture is told this conversation holds a
    stranger's text.
    """
    borrowed = "https://claude.ai/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"
    _fp = research._runtime.brief_fingerprints["chatgpt"]
    assert research.chatgpt_identity_verdict(FOREIGN_TEXT, _fp) == "foreign", (
        "precondition: the content verdict condemns this conversation, so only "
        "the agent-key scoping can save it")
    pending = {"Claude": _leg(FOREIGN_URL),
               "Gemini": _leg(borrowed)}
    dropped, pending, _r, cards, _ = sweep(pending)
    assert dropped == []
    assert len(pending) == 2
    assert cards == []


def test_siblings_keep_polling_when_one_leg_is_dropped(sweep):
    """Dropping the whole round-robin over one bad tab would cost the run two healthy
    reports."""
    pending = {"ChatGPT": _leg(FOREIGN_URL),
               "Gemini": _leg("https://gemini.google.com/app/abc"),
               "Claude": _leg("https://claude.ai/chat/def")}
    dropped, pending, _r, _c, _d = sweep(pending)
    assert dropped == ["ChatGPT"]
    assert sorted(pending) == ["Claude", "Gemini"]


def test_a_dead_handle_is_left_to_the_crash_sweep(sweep):
    """Reading `.url` on a closed page raises. That is the crash sweep's business —
    this one must not convert a crash into a wrong-conversation card, which would
    replace an auto-recovering banner with a card demanding a human."""
    dropped, pending, results, cards, _ = sweep({"ChatGPT": {"page": _DeadTab(),
                                                            "url": FOREIGN_URL}})
    assert dropped == []
    assert "ChatGPT" in pending
    assert cards == []


def test_the_live_url_decides_not_the_seeded_one(sweep):
    """`p["url"]` is stamped at seed time. If the sweep trusted it, drift that happens
    DURING polling — a panel-open press that navigates — would be invisible."""
    leg = _leg(OURS_URL)
    leg["page"] = _Tab(FOREIGN_URL)      # the tab moved; the record did not
    dropped, _p, _r, _c, _d = sweep({"ChatGPT": leg})
    assert dropped == ["ChatGPT"]

    leg2 = _leg(FOREIGN_URL)
    leg2["page"] = _Tab(OURS_URL)        # stale record says foreign, tab is fine
    dropped2, pending2, _r2, _c2, _d2 = sweep({"ChatGPT": leg2})
    assert dropped2 == [] and "ChatGPT" in pending2


def test_the_card_does_not_say_the_brief_failed_to_send(sweep):
    """The brief DID send — the tab moved afterwards. Telling the user the send failed
    would send them looking in the wrong place."""
    _d, _p, _r, cards, _dis = sweep({"ChatGPT": _leg(FOREIGN_URL)})
    key, title, details = cards[0]
    assert key == "chatgpt"
    assert title == "ChatGPT is on a different conversation"
    assert "brief" not in title.lower()
    assert "Retry" in details and "Skip" in details


def test_a_parked_chat_mode_decision_is_retracted_with_the_leg(sweep):
    """A chat-mode park asks the user to keep output from a send. That send went into a
    conversation we are now refusing, so the card must not outlive the leg."""
    research._controls.chat_mode_pending["chatgpt"] = {"since": 1.0}
    try:
        sweep({"ChatGPT": _leg(FOREIGN_URL)})
        assert "chatgpt" not in research._controls.chat_mode_pending
    finally:
        research._controls.chat_mode_pending.pop("chatgpt", None)


def test_a_run_that_cannot_identify_its_own_brief_does_not_fail_healthy_legs(monkeypatch):
    """⛔⛔ FAILS OPEN, AND THAT DIRECTION IS THE WHOLE POINT OF THE REWRITE.

    This used to be about an unreadable `config.json` leaving the run undatable.
    The run's start time no longer enters into it; what can now be missing is the
    fingerprint of the brief — a resumed run does not carry it through the pause
    checkpoint. With nothing to compare against, the sweep must abstain.

    Abstaining costs the check its teeth. Guessing costs a healthy leg, and this
    project has already paid that twice — most recently seven seconds after Send.
    """
    cards = []
    monkeypatch.setattr(research, "fail_agent", lambda *a, **k: cards.append(a))
    monkeypatch.setattr(research, "_disarm_registry", lambda k: None)
    research._runtime.brief_fingerprints.pop("chatgpt", None)

    async def _read(_page):
        return FOREIGN_TEXT      # unmistakably not ours, and it must not matter

    pending = {"ChatGPT": _leg(FOREIGN_URL)}
    assert asyncio.run(research._sweep_foreign_chatgpt_tabs(
        pending, {}, read_first_message=_read)) == []
    assert cards == []
    assert "ChatGPT" in pending


def test_a_conversation_we_cannot_read_does_not_fail_a_healthy_leg(monkeypatch):
    """The other abstain: the DOM read came back empty — mid-navigation, a slow
    render, a markup change. Silence is not evidence of a stranger's thread."""
    cards = []
    monkeypatch.setattr(research, "fail_agent", lambda *a, **k: cards.append(a))
    monkeypatch.setattr(research, "_disarm_registry", lambda k: None)
    research._runtime.brief_fingerprints["chatgpt"] = research.brief_fingerprint(
        SWEEP_BRIEF)
    try:
        async def _read(_page):
            return ""

        pending = {"ChatGPT": _leg(FOREIGN_URL)}
        assert asyncio.run(research._sweep_foreign_chatgpt_tabs(
            pending, {}, read_first_message=_read)) == []
        assert cards == []
    finally:
        research._runtime.brief_fingerprints.pop("chatgpt", None)


def test_the_round_robin_sweeps_before_any_per_agent_work():
    """Order is the whole point: a sweep that ran after the poll body would have
    already scraped the foreign tab that tick."""
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research.poll_all_agents_round_robin)
    call = src.index("_sweep_foreign_chatgpt_tabs(pending, results)")
    loop = src.index("while pending:")
    stop = src.index("if _controls.is_stop() or _controls.is_pause():", loop)
    assert loop < call < stop, (loop, call, stop)


def test_the_sweep_has_exactly_one_caller_and_it_is_the_round_robin():
    """A guard with no caller is decorative — this suite has caught that three times."""
    from conftest import code_only  # type: ignore
    src = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    assert src.count("_sweep_foreign_chatgpt_tabs(pending, results)") == 1
    assert src.count("def _sweep_foreign_chatgpt_tabs(") == 1
