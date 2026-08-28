"""The 2026-08-05 tab-drift wave.

ROOT CAUSE, proven from Chrome's own History DB rather than inferred. `setup_chatgpt_dr`
Step 2 located the Deep-Research menu row with the bare class `.__menu-item` matched
against `document`, then pressed it. ChatGPT's left sidebar lists recent conversations
as `<a href="/c/<id>">`, the previous evening's Deep Research thread was TITLED "Deep
research request", and the row matcher takes the FIRST row whose text starts with the
policy tool word and breaks — so it selected a sidebar conversation LINK, because the
sidebar precedes the composer in document order. Pressing an anchor navigates:

    visits 237  2026-08-05 11:08:14  0x30000000  /c/6a72ce1e…  "Deep research request"
    visits 250  2026-08-05 11:14:44  0x30000000  /c/6a72ce1e…  "Deep research request"

0x30000000 is PAGE_TRANSITION_LINK | CHAIN_START | CHAIN_END — a link activation, not
one of our own `goto`s (those carry FROM_API: 0x38000001, visits 243/246 in the same
minute). Both land in the SAME SECOND as Step 2's press, on the first attempt and again
on the retry — and on the retry Playwright's real click landed, so the technique was
never the fault. The element was.

⭐ EVERY GUARD DOWNSTREAM WAS SATISFIED BY THE MIS-CLICK ITSELF:
  * the click JS re-checks the row's LABEL, which passes because it is the same element;
  * Step 3's "verified DR active" came from the composer PLACEHOLDER alone (`pill=''`),
    and an old Deep-Research thread's composer reads "Get a detailed report";
  * the model tier read 'Pro' off the old thread's own pill;
  * `_pre_send_url` was recorded and only compared AFTER the send, so on the retry the
    brief was actually submitted into last night's thread before anything objected.

These tests EXECUTE the page JS through the node DOM shim and the Python through fake
pages. A presence assertion would pass against a filter that cannot run.
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
from _domshim import el, run_js  # noqa: E402

TOOL_GROUPS = [
    {"name": "menu-item-class", "sel": ".__menu-item"},
    {"name": "role", "sel": '[role="menuitemradio"], [role="menuitem"], [role="option"]'},
]

# The live sidebar title, verbatim from Chrome's History (urls.id=87). It starts with
# the policy tool word, which is the entire reason the matcher chose it.
SIDEBAR_TITLE = "Deep research request"
MENU_ROW = "Deep research Get a detailed report"


def _rows(spec, seen=None, groups=None):
    return run_js(spec, research._CHATGPT_MENU_ROWS_JS,
                  {"groups": groups or TOOL_GROUPS, "seen": list(seen or [])})["ret"]


def _incident_page(sidebar_kids=None, menu_kids=None):
    """The 2026-08-05 page: sidebar recents FIRST (document order matters), composer
    second. This ordering is what made the sidebar win the matcher's `break`."""
    return el("body", kids=[
        el("nav", kids=sidebar_kids if sidebar_kids is not None else [
            el("a", {"class": "__menu-item", "href": "/c/6a72ce1e-2284"}, SIDEBAR_TITLE),
            el("a", {"class": "__menu-item", "href": "/c/6a7377d5-d8f4"},
               "Research Brief Request"),
        ]),
        el("form", kids=menu_kids if menu_kids is not None else [
            el("div", {"class": "__menu-item"}, MENU_ROW),
            el("div", {"class": "__menu-item"}, "Web search"),
        ]),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# The row filter — each arm proved on its own, so a mutant that disables one is
# not covered by the other.
# ─────────────────────────────────────────────────────────────────────────────

def test_sidebar_conversation_link_is_never_a_candidate():
    """The incident shape. With BOTH arms live, only the composer's own row survives."""
    seen = run_js(_incident_page(menu_kids=[]), research._CHATGPT_ROWS_SEEN_JS,
                  {"groups": TOOL_GROUPS})["ret"]
    got = _rows(_incident_page(), seen)
    assert got["rows"] == [MENU_ROW, "Web search"], got
    assert SIDEBAR_TITLE not in got["rows"]
    assert got["rejected"] == 2, "both sidebar links must be counted as rejected"


def test_anchor_arm_alone_excludes_the_link():
    """No census at all — the href exclusion must carry it by itself.

    This is the arm that is exact rather than heuristic: a composer tool row is a
    div/button, a conversation row is always a link.
    """
    got = _rows(_incident_page(sidebar_kids=[
        el("a", {"class": "__menu-item", "href": "/c/6a72ce1e"}, SIDEBAR_TITLE)]), seen=[])
    assert got["rows"] == [MENU_ROW, "Web search"], got
    assert got["rejected"] == 1


def test_anchor_arm_covers_a_row_nested_inside_the_link():
    """ChatGPT wraps its row content in the anchor rather than putting the class on it,
    so `el.tagName === 'A'` alone would miss — `closest('a[href]')` is load-bearing."""
    got = _rows(_incident_page(sidebar_kids=[
        el("a", {"href": "/c/6a72ce1e"},
           kids=[el("div", {"class": "__menu-item"}, SIDEBAR_TITLE)])]), seen=[])
    assert got["rows"] == [MENU_ROW, "Web search"], got
    assert got["rejected"] == 1


def test_census_arm_alone_excludes_a_pre_existing_non_link_row():
    """The durable arm. A future surface that borrows `.__menu-item` WITHOUT being a
    link is still excluded, because it was on screen before the menu opened."""
    chip = "Deep research chip that was already here"
    spec = el("body", kids=[
        el("div", {"class": "__menu-item"}, chip),
        el("form", kids=[el("div", {"class": "__menu-item"}, MENU_ROW)]),
    ])
    got = _rows(spec, seen=[chip])
    assert got["rows"] == [MENU_ROW], got
    assert got["rejected"] == 1
    # …and without the census it WOULD be a candidate — proving the arm does work.
    assert chip in _rows(spec, seen=[])["rows"]


def test_when_only_the_sidebar_is_there_we_find_nothing_rather_than_the_wrong_thing():
    """The exact incident, with the menu never mounted.

    Empty rows make Step 2 report a MISS, which hands the intent to the CUA rung. The
    old behaviour returned the sidebar link and pressed it. `rejected` must survive the
    empty return, because "0 rows" and "0 rows and 1 conversation link we refused" are
    otherwise the same log line — and only the second says the menu never opened.
    """
    got = _rows(_incident_page(menu_kids=[]), seen=[SIDEBAR_TITLE])
    assert got["rows"] == []
    assert got["via"] == ""
    assert got["rejected"] >= 1, (
        "the empty return must still report what the filter threw away")


def test_hidden_rows_stay_excluded():
    """The pre-existing on-screen gate must survive the rewrite."""
    got = _rows(el("body", kids=[
        el("form", {"hidden": "1"}, kids=[el("div", {"class": "__menu-item"}, MENU_ROW)])]),
        seen=[])
    assert got["rows"] == []


def test_role_group_rows_are_filtered_the_same_way():
    """The second hook group must not be a hole. A `[role=menuitem]` that is a
    conversation link is exactly as dangerous as a class-matched one."""
    spec = el("body", kids=[
        el("nav", kids=[el("a", {"role": "menuitem", "href": "/c/6a72ce1e"}, SIDEBAR_TITLE)]),
        el("form", kids=[el("div", {"role": "menuitem"}, MENU_ROW)]),
    ])
    got = _rows(spec, seen=[])
    assert got["via"] == "role"
    assert got["rows"] == [MENU_ROW], got


# ─────────────────────────────────────────────────────────────────────────────
# The click JS must re-resolve the index against the SAME filtered list.
# ─────────────────────────────────────────────────────────────────────────────

def test_click_js_marks_the_menu_row_not_the_sidebar_link():
    """The read and the click used to carry the filter TWICE, and the design's promise
    ("the index is re-resolved against the same filter") held only while the two were
    typed identically. Both now embed one string.

    Asserting the marked TEXT, not that a mark happened: the label re-check in this JS
    passed in the incident precisely because it was re-checking the wrong element
    against its own label.
    """
    spec = _incident_page()
    seen = run_js(_incident_page(menu_kids=[]), research._CHATGPT_ROWS_SEEN_JS,
                  {"groups": TOOL_GROUPS})["ret"]
    got = _rows(spec, seen)
    res = run_js(spec, research._CHATGPT_CLICK_ROW_JS,
                 {"groups": TOOL_GROUPS, "via": got["via"], "index": 0,
                  "expect": got["rows"][0], "seen": seen,
                  "attr": research._SR_CLICK_MARK, "value": "tool-row"})["ret"]
    assert res.get("clicked") is True, res
    assert res.get("text") == MENU_ROW, (
        f"index 0 must resolve to the composer's row, got {res.get('text')!r}")


def test_click_js_shares_the_filter_string_with_the_read():
    """One filter, embedded in both — not two copies that happen to agree today."""
    assert research._CHATGPT_ROW_FILTER_JS in research._CHATGPT_MENU_ROWS_JS
    assert research._CHATGPT_ROW_FILTER_JS in research._CHATGPT_CLICK_ROW_JS
    # And it is a real filter, not an empty string that trivially satisfies both.
    assert "closest" in research._CHATGPT_ROW_FILTER_JS
    assert "indexOf" in research._CHATGPT_ROW_FILTER_JS
    assert "offsetParent" in research._CHATGPT_ROW_FILTER_JS


def test_click_js_refuses_an_index_that_the_filter_removed():
    """A stale index from a wider list must not fall through onto a link. Under the old
    filter index 0 was the sidebar row; the click must now fail closed."""
    spec = _incident_page()
    res = run_js(spec, research._CHATGPT_CLICK_ROW_JS,
                 {"groups": TOOL_GROUPS, "via": "menu-item-class", "index": 0,
                  "expect": SIDEBAR_TITLE, "seen": [SIDEBAR_TITLE],
                  "attr": research._SR_CLICK_MARK, "value": "tool-row"})["ret"]
    assert res.get("clicked") is not True, res
    assert res.get("reason") == "label_changed", res


# ─────────────────────────────────────────────────────────────────────────────
# The pointer fallback must aim at the same element the Playwright rung did.
# ─────────────────────────────────────────────────────────────────────────────

def test_pointer_press_aims_by_value_not_document_order():
    """The Playwright rung selects `[attr="value"]`; this one used the bare `[attr]`, so
    a stray marker with a different value would win on document order and the fallback
    would press something the caller never ranked. No live repro — this is the class of
    aiming bug that produced the navigation, closed while the lesson is fresh."""
    spec = el("body", kids=[
        el("div", {research._SR_CLICK_MARK: "model-row"}, "WRONG first in document order"),
        el("div", {research._SR_CLICK_MARK: "tool-row"}, "RIGHT the ranked row"),
    ])
    out = run_js(spec, research._SR_POINTER_PRESS_JS,
                 {"attr": research._SR_CLICK_MARK, "value": "tool-row"})
    assert out["ret"].get("pressed") is True, out
    assert out["clicks"], "the pointer chain must actually dispatch"
    assert all("RIGHT" in c for c in out["clicks"]), out["clicks"]


def test_sr_real_click_TELLS_the_pointer_fallback_which_value_to_aim_at():
    """⭐ Mutation-found gap. The JS above can aim by value, and the test above proves
    it does — but that test hands it the value directly. Dropping `"value": value` from
    the Python call site leaves the JS correct and the aiming broken, and every JS-level
    test still passes.

    So execute the real `_sr_real_click`: make the Playwright rung throw, and capture
    what the fallback evaluate was actually given.
    """
    seen = {}

    class _P:
        async def click(self, sel, timeout=None):
            raise RuntimeError("not actionable")

        async def evaluate(self, js, arg=None):
            if js is research._SR_POINTER_PRESS_JS:
                seen["arg"] = dict(arg or {})
                return {"pressed": True}
            return 0        # the unmark pass

    how = asyncio.run(research._sr_real_click(_P(), "tool-row", tag="[t]"))
    assert how == "pointer", how
    assert seen["arg"].get("attr") == research._SR_CLICK_MARK, seen
    assert seen["arg"].get("value") == "tool-row", (
        f"the fallback must be told which marker to press, got {seen.get('arg')!r}")


def test_pointer_press_reports_marker_gone_when_its_value_is_absent():
    """Failing closed matters more than pressing something: the caller treats an
    unpressed row as not-clicked and hands the intent to the next rung."""
    spec = el("body", kids=[el("div", {research._SR_CLICK_MARK: "model-row"}, "other")])
    out = run_js(spec, research._SR_POINTER_PRESS_JS,
                 {"attr": research._SR_CLICK_MARK, "value": "tool-row"})
    assert out["ret"].get("pressed") is not True
    assert out["ret"].get("reason") == "marker_gone", out["ret"]
    assert not out["clicks"], "nothing may be pressed when our own marker is missing"


# ─────────────────────────────────────────────────────────────────────────────
# setup_chatgpt_dr — the census must precede the press, and Step 2½ must abort.
# ─────────────────────────────────────────────────────────────────────────────

class _SetupPage:
    """A ChatGPT composer that answers the way the live page did on 2026-08-05.

    `navigate_on_press` reproduces the incident: the marked row's press moves the tab.
    The composer then answers with the DR placeholder — which is what an old Deep
    Research thread does, and is why Step 3 could not tell the difference.
    """

    def __init__(self, *, navigate_on_press=False, rows_after_open=(MENU_ROW,)):
        self.url = "https://chatgpt.com/"
        self._navigate = navigate_on_press
        self._rows_after_open = list(rows_after_open)
        self.menu_open = False
        self.calls = []          # ordered record of what the page was asked
        self.seen_arg = None     # what `seen` the row read was given

    async def query_selector(self, sel):
        page = self

        class _Btn:
            async def click(self):
                page.calls.append(("click-plus", sel))
                page.menu_open = True
        return _Btn() if "composer-plus-btn" in sel else None

    async def evaluate(self, js, arg=None):
        if js is research._CHATGPT_ROWS_SEEN_JS:
            self.calls.append(("census", self.menu_open))
            return [SIDEBAR_TITLE]
        if js is research._CHATGPT_MENU_ROWS_JS:
            self.calls.append(("rows", self.menu_open))
            self.seen_arg = list((arg or {}).get("seen") or [])
            return {"via": "menu-item-class", "rows": list(self._rows_after_open),
                    "rejected": 1}
        if js is research._CHATGPT_CLICK_ROW_JS:
            self.calls.append(("mark", (arg or {}).get("value")))
            return {"clicked": True, "text": (arg or {}).get("expect")}
        if js is research._CHATGPT_DR_ACTIVE_JS:
            self.calls.append(("dr-state", self.url))
            # Both a fresh composer with DR on and an old DR thread say this.
            return {"active": self.menu_open, "pillText": "",
                    "placeholder": "get a detailed report" if self.menu_open
                    else "ask chatgpt"}
        self.calls.append(("other-js", None))
        return {}


def _run_setup(page, *, navigate_to=None):
    async def _press(p, value, *, tag, **kw):
        p.calls.append(("press", value))
        if navigate_to:
            p.url = navigate_to
        return "playwright"

    async def _tier(p):
        return "already"

    real_press, real_tier = research._sr_real_click, research._chatgpt_p2_effort_tier
    research._sr_real_click = _press
    research._chatgpt_p2_effort_tier = _tier
    try:
        return asyncio.run(research.setup_chatgpt_dr(page, allow_model_pick=False))
    finally:
        research._sr_real_click = real_press
        research._chatgpt_p2_effort_tier = real_tier


def test_census_is_taken_before_the_plus_button_is_pressed():
    """"New since the menu opened" is meaningless if the census runs after the open.

    Asserting the ORDER of the real calls, not that a census exists: a census taken
    one line later would still be present in the source and would still be passed to
    the row read, and it would silently match everything.
    """
    p = _SetupPage()
    assert _run_setup(p) is True, p.calls
    kinds = [c[0] for c in p.calls]
    assert "census" in kinds, p.calls
    assert kinds.index("census") < kinds.index("click-plus"), p.calls
    # …and it was taken while the menu was still shut.
    assert p.calls[kinds.index("census")][1] is False, p.calls


def test_the_census_reaches_the_row_read():
    """A census nobody threads through is decoration."""
    p = _SetupPage()
    assert _run_setup(p) is True, p.calls
    assert p.seen_arg == [SIDEBAR_TITLE], p.seen_arg


def test_step_2_and_a_half_aborts_when_the_press_moved_the_tab():
    """⭐ The incident, end to end. The press navigates, the new page truthfully reports
    the DR placeholder, and setup must still refuse.

    Asserting the RETURN VALUE and that Step 3 never ran: Step 3 read `active=True` on
    2026-08-05 and reported success, so any assertion that only checks "we logged
    something" would have passed on the broken code too.
    """
    p = _SetupPage()
    out = _run_setup(p, navigate_to="https://chatgpt.com/c/6a72ce1e-2284")
    assert out is False, p.calls
    # Step 3's composer read must never happen on the page we were moved to.
    dr_reads_after_press = [
        c for i, c in enumerate(p.calls)
        if c[0] == "dr-state" and any(x[0] == "press" for x in p.calls[:i])]
    assert dr_reads_after_press == [], (
        f"nothing may be verified on the new page: {dr_reads_after_press}")


def test_setup_still_succeeds_when_the_tab_does_not_move():
    """The guard must not fail a healthy run — the whole point of comparing rather
    than testing the new page for anything."""
    p = _SetupPage()
    assert _run_setup(p) is True, p.calls
    assert p.url == "https://chatgpt.com/"


def _run_setup_with_recovery(*, moves_on_press, new_chat_works=True,
                             url_suffix_on_press=None):
    """Drive the real `setup_chatgpt_dr` with a page that navigates on the Nth press.

    `moves_on_press` is the set of 1-based press numbers that move the tab. {1} is the
    2026-08-05 shape: the first press lands on a conversation, and a recovered fresh
    chat then behaves. {1, 2} is the pathological page that moves every time.

    `url_suffix_on_press` appends a QUERY STRING on the first press without changing
    the path — what ChatGPT itself does while streaming. The tab has not moved, and
    Step 2½ must not say it has.
    """
    p = _SetupPage()
    state = {"presses": 0, "new_chats": 0, "setups": 0}

    async def _press(pg, value, *, tag, **kw):
        state["presses"] += 1
        pg.calls.append(("press", value))
        if state["presses"] in moves_on_press:
            pg.url = f"https://chatgpt.com/c/6a72ce1e-press{state['presses']}"
        elif url_suffix_on_press and state["presses"] == 1:
            pg.url = pg.url.split("?", 1)[0] + url_suffix_on_press
        return "playwright"

    async def _new_chat(pg, label):
        state["new_chats"] += 1
        if not new_chat_works:
            return False
        pg.url = "https://chatgpt.com/"
        pg.menu_open = False
        return True

    async def _tier(pg):
        return "already"

    real = (research._sr_real_click, research._chatgpt_force_new_chat,
            research._chatgpt_p2_effort_tier)
    research._sr_real_click = _press
    research._chatgpt_force_new_chat = _new_chat
    research._chatgpt_p2_effort_tier = _tier
    try:
        out = asyncio.run(research.setup_chatgpt_dr(p, allow_model_pick=False))
    finally:
        (research._sr_real_click, research._chatgpt_force_new_chat,
         research._chatgpt_p2_effort_tier) = real
    return out, p, state


def test_a_drifted_setup_RECOVERS_rather_than_handing_the_page_on():
    """⛔ Returning False is not enough. The ladder's next rung is a VISION pass with a
    real mouse, and pointing one at someone else's finished thread is how the run ends
    up harvesting it. So setup presses New chat and retries itself once.

    Asserting the OUTCOME plus that a new chat was actually pressed — a version that
    logged the intent and returned False would satisfy any string assertion.
    """
    out, page, state = _run_setup_with_recovery(moves_on_press={1})
    assert out is True, page.calls
    assert state["new_chats"] == 1, state
    assert page.url == "https://chatgpt.com/", page.url


def test_the_drift_recovery_is_bounded_to_one_attempt():
    """A page that navigates on every press must not recurse. `_drift_retry` is the
    bound, and it has to be a real bound, not a comment."""
    out, page, state = _run_setup_with_recovery(moves_on_press={1, 2, 3, 4})
    assert out is False, page.calls
    assert state["new_chats"] == 1, (
        f"exactly one recovery attempt, got {state['new_chats']}")


def test_setup_gives_up_when_the_new_chat_cannot_be_reached():
    """`_chatgpt_force_new_chat` returns True only on a verified fresh composer. When
    it cannot get there, the tab is still foreign and setup must NOT report success."""
    out, page, state = _run_setup_with_recovery(moves_on_press={1},
                                                new_chat_works=False)
    assert out is False, page.calls
    assert state["new_chats"] == 1


def test_step_2_and_a_half_runs_before_step_3_in_source_order():
    """Order is the fix, not the presence of a check: nothing on the page we were moved
    to can answer "is this still the same page?", so the comparison has to come first.
    """
    src = research.code_only_deep(research.setup_chatgpt_dr) \
        if hasattr(research, "code_only_deep") else None
    if src is None:
        from conftest import code_only_deep  # type: ignore
        src = code_only_deep(research.setup_chatgpt_dr)
    abort = src.index("Step 2½ ABORT")
    step3 = src.index("Step 3 OK: verified DR active")
    assert abort < step3, "the URL comparison must precede the DR verification"
    # The guard must be REACHABLE — an `if False` mutant leaves both strings intact.
    guard = src[src.index("_url_after = \"\""):abort]
    assert "False" not in guard, guard


# ─────────────────────────────────────────────────────────────────────────────
# The pre-send gate — a gate, not a note.
# ─────────────────────────────────────────────────────────────────────────────

def test_a_conversation_that_predates_the_run_is_not_ours():
    """The primitive the gate leans on, on the incident's real ids.

    6a72ce1e = 2026-08-04 22:46:06 (last night). 6a7377d5 = 2026-08-05 10:50:13.
    """
    run_start = 1786000000.0  # after both, so both are foreign
    assert research._chatgpt_conversation_is_ours(
        "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0", run_start) is False
    # A conversation minted after the run started is ours.
    later = research._chatgpt_convo_epoch(
        "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0")
    assert later is not None
    assert research._chatgpt_conversation_is_ours(
        "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0",
        later + 1.0) is True


# ── The decision, DRIVEN. ────────────────────────────────────────────────────
#
# ⭐ f12, the worst finding of the review pass: both gates used to be spelled
# inline inside `start_agent_no_gemini_wait`, and NOTHING in the suite executes
# that function — all ~30 references to it read it as SOURCE. Mutation proved the
# cost: dropping one `not` from the pre-send gate left 49 of 49 tests green, so
# the guard this whole wave exists for could have shipped inverted.
#
# The decision and the refusal now live in `_chatgpt_tab_is_foreign` and
# `_refuse_foreign_chatgpt_tab`, which a test can actually CALL. Everything below
# runs them. The two call sites are still pinned by shape and order (driving the
# 700-line send function would need a fake browser larger than the fix), but each
# site is now one `if await …: return page, False` — there is no logic left there
# to get subtly wrong.

FOREIGN_URL = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"  # 08-04 22:46
OURS_URL = "https://chatgpt.com/c/6a7377d5-8f14-8320-a5d5-7f9a5a5f0f10"     # 08-05 10:50


class _FakePage:
    def __init__(self, url):
        self._url = url

    @property
    def url(self):
        return self._url


def _stub_run_start(monkeypatch, when):
    monkeypatch.setattr(research, "_run_start_epoch", lambda: when)


def _between():
    """A run start after last night's thread but before this morning's.

    ⚠ Clear of `_CONVO_AGE_SLACK_SEC` on BOTH sides — the 120s slack covers clock
    skew and a same-minute resume, so a run start only a minute after the foreign
    thread would legitimately still call it ours. The real gap here is 12 hours.
    """
    old = research._chatgpt_convo_epoch(FOREIGN_URL)
    new = research._chatgpt_convo_epoch(OURS_URL)
    assert old is not None and new is not None, (old, new)
    slack = research._CONVO_AGE_SLACK_SEC
    assert new - old > 4 * slack, (old, new, slack)
    return old + 2 * slack + 1.0


def test_the_foreign_predicate_says_yes_only_to_a_datably_older_conversation(monkeypatch):
    """Executed, both ways. This is the assertion whose absence let a `not` vanish."""
    _stub_run_start(monkeypatch, _between())
    assert research._chatgpt_tab_is_foreign(FOREIGN_URL) is True
    assert research._chatgpt_tab_is_foreign(OURS_URL) is False


def test_the_foreign_predicate_is_inert_on_a_bare_host(monkeypatch):
    """A healthy first send happens at `https://chatgpt.com/` before the SPA mints an
    id. If the predicate fired there it would fail every good run."""
    _stub_run_start(monkeypatch, _between())
    assert research._chatgpt_tab_is_foreign("https://chatgpt.com/") is False
    assert research._chatgpt_tab_is_foreign("") is False
    assert research._chatgpt_tab_is_foreign("https://chatgpt.com/?model=gpt-5") is False


def test_the_foreign_predicate_is_open_on_an_unreadable_id_and_on_no_run(monkeypatch):
    """The two asymmetric fallbacks, each driven. NEITHER may condemn a leg.

    ⛔⛔ THIS TEST ASSERTED THE OPPOSITE UNTIL 2026-08-27, AND IT WAS ENSHRINING A
    DEFECT. It required an id we cannot date to be refused — "fails closed on an
    unreadable id" — and the function's own docstring simultaneously claimed it
    returned True "only for a conversation we can positively date as older than
    the run". Both could not be true, and the code followed the assertion.

    Then ChatGPT began serving `/c/WEB:<uuid>`, whose id carries no timestamp.
    Measured from a real run: a healthy Deep Research leg was declared foreign and
    skipped seven seconds after Send, and the same predicate would have killed it
    again on every tick of the poll loop.

    ▶ AN ID WE CANNOT READ IS A QUESTION, NOT A VERDICT. Refusing on it means any
    format change the platform makes reads to us as theft. The 2026-08-05
    incident stays caught because that conversation's id was perfectly readable
    and simply old — see `tests/test_chatgpt_landing_0827.py` for the full set.
    """
    _stub_run_start(monkeypatch, _between())
    assert research._chatgpt_tab_is_foreign("https://chatgpt.com/c/not-a-timestamp") is False
    assert research._chatgpt_tab_is_foreign(
        "https://chatgpt.com/c/WEB:c3a7026f-6c11-4179-9003-0ba4c93a18f3") is False
    # ⭐ And the half that was always right: a datable, older conversation is
    # still refused, so widening the unreadable case cost nothing.
    assert research._chatgpt_tab_is_foreign(FOREIGN_URL) is True
    _stub_run_start(monkeypatch, None)
    assert research._chatgpt_tab_is_foreign(FOREIGN_URL) is False


def test_the_query_string_does_not_hide_the_conversation_id(monkeypatch):
    """ChatGPT appends `?messageId=finalAgentTurnStart` — confirmed on the incident's
    own URLs in Chrome's history. The `/c/` test strips it before looking."""
    _stub_run_start(monkeypatch, _between())
    assert research._chatgpt_tab_is_foreign(
        FOREIGN_URL + "?messageId=finalAgentTurnStart") is True


def _drive_refusal(monkeypatch, url, *, recover, platform_l="chatgpt",
                   run_start=None, new_chat=True):
    cards, new_chats = [], []
    monkeypatch.setattr(research, "fail_agent",
                        lambda key, title, details="", **kw: cards.append(
                            (key, title, details)))

    async def _fake_new_chat(page, label):
        new_chats.append(label)
        return new_chat

    monkeypatch.setattr(research, "_chatgpt_force_new_chat", _fake_new_chat)
    _stub_run_start(monkeypatch, _between() if run_start is None else run_start)
    research._controls.chat_mode_pending[platform_l] = {"since": 1.0}
    try:
        refused = asyncio.run(research._refuse_foreign_chatgpt_tab(
            _FakePage(url), "ChatGPT", platform_l, "ChatGPT", url,
            recover=recover, why="send"))
    finally:
        research._controls.chat_mode_pending.pop(platform_l, None)
    return refused, cards, new_chats


def test_the_refusal_fires_on_last_nights_thread(monkeypatch):
    refused, cards, _ = _drive_refusal(monkeypatch, FOREIGN_URL, recover=True)
    assert refused is True
    assert len(cards) == 1, cards


def test_the_refusal_stays_out_of_the_way_of_our_own_conversation(monkeypatch):
    """The polarity assertion. Inverting the predicate makes THIS fail, not the one
    above — a healthy leg would be killed on every send."""
    refused, cards, new_chats = _drive_refusal(monkeypatch, OURS_URL, recover=True)
    assert refused is False
    assert cards == [], cards
    assert new_chats == [], "a healthy tab must not be reset"


def test_the_refusal_is_scoped_to_chatgpt(monkeypatch):
    """Gemini and Claude URLs never carry a datable ChatGPT id, but the platform test
    is the belt: this must not become a cross-platform gate by accident."""
    refused, cards, _ = _drive_refusal(monkeypatch, FOREIGN_URL, recover=True,
                                       platform_l="claude")
    assert refused is False
    assert cards == []


def test_the_refusal_retracts_the_tentative_chat_mode_marker(monkeypatch):
    """A parked chat-mode decision belongs to a send that happened. This one did not,
    so leaving the marker asks the user to keep output that will never exist."""
    cards = []
    monkeypatch.setattr(research, "fail_agent",
                        lambda *a, **k: cards.append(a))

    async def _fake_new_chat(page, label):
        return True

    monkeypatch.setattr(research, "_chatgpt_force_new_chat", _fake_new_chat)
    _stub_run_start(monkeypatch, _between())
    research._controls.chat_mode_pending["chatgpt"] = {"since": 1.0}
    try:
        assert asyncio.run(research._refuse_foreign_chatgpt_tab(
            _FakePage(FOREIGN_URL), "ChatGPT", "chatgpt", "ChatGPT", FOREIGN_URL,
            recover=False, why="send")) is True
        assert "chatgpt" not in research._controls.chat_mode_pending
    finally:
        research._controls.chat_mode_pending.pop("chatgpt", None)


def test_only_the_pre_send_site_presses_new_chat(monkeypatch):
    """`recover` is the one behavioural difference between the two call sites, and it
    is a real one: setup already tried and failed, so pressing again there would only
    add another touch on a surface that may be walled."""
    _, _, with_recovery = _drive_refusal(monkeypatch, FOREIGN_URL, recover=True)
    assert with_recovery == ["ChatGPT"]
    _, _, without = _drive_refusal(monkeypatch, FOREIGN_URL, recover=False)
    assert without == []


def test_a_failing_new_chat_does_not_change_the_outcome(monkeypatch):
    """Recovery is for the NEXT attempt. Its failure must not turn a refusal into a
    send."""
    cards = []
    monkeypatch.setattr(research, "fail_agent", lambda *a, **k: cards.append(a))

    async def _explodes(page, label):
        raise RuntimeError("navigation timeout")

    monkeypatch.setattr(research, "_chatgpt_force_new_chat", _explodes)
    _stub_run_start(monkeypatch, _between())
    assert asyncio.run(research._refuse_foreign_chatgpt_tab(
        _FakePage(FOREIGN_URL), "ChatGPT", "chatgpt", "ChatGPT", FOREIGN_URL,
        recover=True, why="send")) is True
    assert len(cards) == 1


def test_the_card_does_not_claim_an_upload_was_rejected(monkeypatch):
    """f8. Both sites used to pass `rejected=True`, so the card read "ChatGPT kept
    rejecting the brief upload" on a path where nothing was ever uploaded — the brief
    was never handed over at all. The default body is already true here, and a third
    copy variant for a case the default describes is not worth the string."""
    _, cards, _ = _drive_refusal(monkeypatch, FOREIGN_URL, recover=True)
    (_key, title, details) = cards[0]
    assert title == "Couldn't send the brief to ChatGPT"
    assert "rejecting" not in details.lower(), details
    assert details == research._brief_send_fail_copy("ChatGPT")[1]


def test_the_pre_send_gate_decides_before_the_send_loop():
    """`_pre_send_url` used to be recorded and compared only AFTER the send. On the
    11:14 retry Playwright found an enabled Send, clicked it, and the brief went into
    last night's thread three seconds before anything objected.

    Order and polarity of the CALL SITE (the decision itself is driven above).
    """
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research.start_agent_no_gemini_wait)
    call = src.index("_refuse_foreign_chatgpt_tab(page, platform, platform_l, label,\n"
                     "                                         _pre_send_url")
    send_loop = src.index("_send_sels = [")
    assert call < send_loop, "the refusal must be decided before the send selectors"
    stmt = src[src.rindex("if ", 0, call):src.index("\n", src.index("return page, False", call))]
    assert "if await _refuse_foreign_chatgpt_tab(" in stmt, stmt
    assert "if not await" not in stmt, stmt
    assert "recover=True" in stmt, stmt


def test_the_setup_side_twin_refuses_to_run_the_vision_rung_on_a_foreign_tab():
    """The belt for the recovery above. `setup_chatgpt_dr` gives up only when it could
    not get back to a fresh chat, so reaching the rungs on a dated conversation means
    recovery failed — and the rungs are a vision pass with a real mouse."""
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research.start_agent_no_gemini_wait)
    guard = src.index('why="run the vision/CUA setup rung"')
    rung = src.index("async def _rung_cua_setup():")
    assert guard < rung, "the guard must precede the vision/CUA rung"
    stmt = src[src.rindex("if ", 0, guard):src.index("\n", src.index("return page, False",
                                                                    guard))]
    assert "if await _refuse_foreign_chatgpt_tab(" in stmt, stmt
    assert "if not await" not in stmt, stmt
    assert "recover=False" in stmt, stmt
    # and it reads the LIVE url, not a value captured earlier in setup
    assert "page.url" in src[src.index("HV wall mid-setup"):guard]


def test_neither_call_site_still_spells_the_decision_inline():
    """The extraction is the fix. If a future edit re-inlines `"/c/" in u and not
    _chatgpt_conversation_is_ours(u)` into the send function, the executable tests
    above stop covering the thing that ships."""
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research.start_agent_no_gemini_wait)
    assert "_chatgpt_conversation_is_ours" not in src.split("_chatgpt_landed")[0], (
        "the pre-send and setup-fail gates must go through the extracted helper")


# ─────────────────────────────────────────────────────────────────────────────
# The off-topic guard at the sink.
# ─────────────────────────────────────────────────────────────────────────────

INCIDENT_TOPIC = ("NemoClaw vs NemoHermes vs Nemotron and also about OpenShell "
                  "and how all of these can be used for security")


@pytest.fixture()
def run_dir():
    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(json.dumps({"topic": INCIDENT_TOPIC}),
                                 encoding="utf-8")
    return d


def _golden_retrievers(n=25_000):
    return ("Golden retrievers are a friendly breed with a notable cancer rate. " *
            (n // 66 + 1))[:n]


def _on_topic(n=25_000):
    return ("Nemotron and OpenShell both expose a libkrun microVM boundary. " *
            (n // 62 + 1))[:n]


def test_reject_off_topic_text_blanks_the_incident_document(run_dir):
    text = _golden_retrievers()
    assert len(text) >= research._TOPIC_GUARD_MIN_CHARS
    assert research.reject_off_topic_text(
        text, run_dir, "ChatGPT", "chatgpt", op="t") == ""


def test_reject_off_topic_text_passes_the_run_s_own_research(run_dir):
    text = _on_topic()
    assert research.reject_off_topic_text(
        text, run_dir, "Gemini", "gemini", op="t") == text


def test_reject_off_topic_text_abstains_without_a_run_dir():
    """Everything uncertain passes — this gate can lose a leg when it fires."""
    text = _golden_retrievers()
    assert research.reject_off_topic_text(
        text, None, "ChatGPT", "chatgpt", op="t") == text


def test_reject_off_topic_text_abstains_on_a_topic_with_no_distinctive_words():
    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(
        json.dumps({"topic": "best practices for team retrospectives"}),
        encoding="utf-8")
    text = _golden_retrievers()
    assert len(research.topic_anchors("best practices for team retrospectives")) \
        < research._TOPIC_GUARD_MIN_ANCHORS
    assert research.reject_off_topic_text(text, d, "ChatGPT", "chatgpt", op="t") == text


def test_reject_off_topic_text_abstains_on_a_short_partial(run_dir):
    short = _golden_retrievers(research._TOPIC_GUARD_MIN_CHARS - 1)
    assert research.reject_off_topic_text(
        short, run_dir, "ChatGPT", "chatgpt", op="t") == short


def test_the_sweep_clears_text_verified_and_a_done_status(run_dir):
    """All three mutations matter: `text` keeps it off disk / out of Firestore /
    out of consolidated.md / away from NotebookLM, `verified` keeps it out of the
    linked bucket, and the status keeps the tile from going green over nothing."""
    results = {
        "ChatGPT": {"status": "done", "text": _golden_retrievers(), "verified": True},
        "Gemini": {"status": "done", "text": _on_topic(), "verified": True},
    }
    assert research.apply_off_topic_sweep(results, run_dir) == ["ChatGPT"]
    assert results["ChatGPT"]["text"] == ""
    assert results["ChatGPT"]["verified"] is False
    assert results["ChatGPT"]["status"] == "failed"
    # The healthy agent is untouched in all three fields.
    assert results["Gemini"]["text"] == _on_topic()
    assert results["Gemini"]["verified"] is True
    assert results["Gemini"]["status"] == "done"


def test_the_sweep_covers_the_user_skip_status_too(run_dir):
    """The 2026-08-05 leg was `skipped_by_user`, not `done` — a sweep that only looked
    at completed agents would have missed the one that actually shipped."""
    results = {"ChatGPT": {"status": "skipped_by_user",
                           "text": _golden_retrievers(), "verified": False}}
    assert research.apply_off_topic_sweep(results, run_dir) == ["ChatGPT"]
    assert results["ChatGPT"]["text"] == ""
    # A non-terminal status is left alone — only done→failed is rewritten.
    assert results["ChatGPT"]["status"] == "skipped_by_user"


def test_the_sweep_says_when_it_is_INERT(run_dir, capsys):
    """⭐ Mutation-found gap. On a run whose meta.json is missing, the topic falls back
    to the run DIRECTORY'S name, and a short or generic one yields fewer than
    `_TOPIC_GUARD_MIN_ANCHORS` distinctive words — so the guard abstains on everything.
    Failing open is deliberate, but an operator must be able to tell "nothing was
    off-topic" from "nothing could be judged".

    Executed, not a source scan: drive the sweep with an unguardable topic and read the
    log the operator would read.
    """
    import json as _json
    import tempfile as _tempfile
    d = Path(_tempfile.mkdtemp())
    (d / "meta.json").write_text(
        _json.dumps({"topic": "best practices for team retrospectives"}),
        encoding="utf-8")
    results = {"ChatGPT": {"status": "done", "text": _golden_retrievers(),
                           "verified": True}}
    assert research.apply_off_topic_sweep(results, d) == []
    out = capsys.readouterr().out
    assert "INERT" in out, out
    # It must name the count, or the operator cannot act on it.
    assert "distinctive word" in out, out
    # …and a guardable topic must NOT produce the line.
    research.apply_off_topic_sweep(
        {"Gemini": {"status": "done", "text": _on_topic(), "verified": True}}, run_dir)
    assert "INERT" not in capsys.readouterr().out


def test_the_sweep_is_a_no_op_on_a_clean_run(run_dir):
    results = {"Gemini": {"status": "done", "text": _on_topic(), "verified": True}}
    assert research.apply_off_topic_sweep(results, run_dir) == []
    assert results["Gemini"]["text"] == _on_topic()


def test_the_sweep_survives_malformed_entries(run_dir):
    results = {"ChatGPT": None, "Gemini": {}, "Claude": {"text": ""}}
    assert research.apply_off_topic_sweep(results, run_dir) == []


def test_run_phase2_sweeps_before_it_returns():
    """⭐ Adversarial review's finding, and the correction of my own second mistake.

    Round one put the guard at ONE writer. Round two moved it to "the finalize block" —
    which widened the same mistake, because `run_phase2` has THREE consumers and the
    other two (the pause + extra-context resume, and the Retry at the Phase-3
    "no documents" gate) each re-write `documents/<agent>.md` and mirror it to Firestore
    from a `results` that had been handed back UNSWEPT.

    There is exactly one `return results`, so guarding it is the only placement a future
    consumer cannot out-flank. Asserted as ORDER inside the function, plus reachability.
    """
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research.run_phase2)
    sweep = src.index("apply_off_topic_sweep(results, _p2_run_dir())")
    # ⭐ Mutation-found: `rindex` was the wrong end. Inserting an EARLY `return results`
    # above the sweep leaves the last one below it, so the ordering assertion passed
    # against a function that handed back unswept results — the exact defect, wearing
    # the shape of the fix. Assert there is exactly ONE hand-back, and that it is after.
    assert src.count("return results") == 1, (
        f"run_phase2 must have a single hand-back or the sweep can be bypassed; "
        f"found {src.count('return results')}")
    assert sweep < src.index("return results"), (
        "the sweep must run before run_phase2 hands results back")
    # No `if` may gate it out — an `if False:` would leave both strings in place.
    guard = src[src.index("results = await poll_all_agents_round_robin("):sweep]
    assert "if " not in guard, guard
    assert "return" not in guard, guard


def test_EVERY_writer_of_an_agent_md_is_downstream_of_the_sweep():
    """The invariant, enumerated rather than sampled.

    The previous version of this test named the two writers I happened to know about
    while its docstring claimed a universal rule — and there were four. So find them
    all, and require each to be reached only from a swept `results`.
    """
    from conftest import code_only  # type: ignore
    src = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    writers = [i for i in range(len(src))
               if src.startswith('(queue_dir / "documents" / fname).write_text', i)]
    assert len(writers) >= 3, (
        f"expected at least 3 per-agent MD writers, found {len(writers)} — if the "
        f"count dropped, confirm a path was removed rather than renamed")
    # Every one of them consumes a `results` that run_phase2 already swept, so the
    # single in-function sweep is what covers them. Pin that there is exactly one
    # `run_phase2` definition and that its return is guarded (above), plus that no
    # writer reads a `results` built anywhere else.
    assert src.count("async def run_phase2(") == 1
    for i in writers:
        head = src[max(0, i - 4000):i]
        assert ("results = await run_phase2(" in head
                or "for name, r in results.items():" in head), (
            f"the MD writer at offset {i} does not visibly consume run_phase2's "
            f"results — it may be a new unswept path")


def test_the_consolidated_build_is_downstream_of_the_sweep():
    from conftest import code_only  # type: ignore
    src = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    sweep = src.index("apply_off_topic_sweep(results, _p2_run_dir())")
    consolidated = src.index('"consolidated.md").write_text(_consolidated_md')
    assert sweep < consolidated


def test_the_skip_branch_runs_the_guard_on_what_it_extracted():
    """The path that actually shipped the wrong report. It calls `extract_fns[...]`
    directly, so `extract_and_record_agent`'s guard never sees the text.

    Asserting the guard sits between the extract and the results write — the ordering
    is the fix; a call placed after the write would still be present in the source.
    """
    from conftest import code_only  # type: ignore
    src = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    extract = src.index("_partial = await extract_fns[_agent_name](")
    guard = src.index("op=\"skip_extract_topic_guard\"")
    write = src.index('"status": "skipped_by_user",', extract)
    assert extract < guard < write, (extract, guard, write)
    # It must be handed a real run directory, not None.
    call = src[src.index("_partial = reject_off_topic_text("):guard]
    assert "_p2_run_dir()" in call, call


def test_reject_off_topic_text_is_the_only_place_the_decision_is_made():
    """One predicate. The wave that produced this defect had the check written out
    inline at its single call site, which is how the two paths that reach the same
    files ended up with no check at all."""
    from conftest import code_only  # type: ignore
    src = code_only(Path(research.__file__).read_text(encoding="utf-8"))
    # `text_is_off_topic` is consulted by the two DECIDERS and by nothing else:
    # `reject_off_topic_text`, which gates what reaches disk, and (2026-08-06)
    # `title_refusal_verdict`, which decides whether a refused title is worth
    # telling the user about. Both are named functions with their own tests; a
    # THIRD caller would mean the predicate had been inlined at a call site
    # again, which is the shape that produced the original defect.
    assert src.count("text_is_off_topic(") == 3, (
        "expected the definition plus exactly two callers "
        "(reject_off_topic_text, title_refusal_verdict)")
    for caller in ("reject_off_topic_text", "title_refusal_verdict"):
        body = src[src.index(f"def {caller}("):]
        body = body[:body.index("\ndef ", 1)]
        assert "text_is_off_topic(" in body, caller


# ─────────────────────────────────────────────────────────────────────────────
# The narrator HTTP budget.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_primary_gets_more_than_the_five_seconds_that_timed_out():
    """30 ReadTimeouts at exactly `read timeout=5` in one run, all after the
    thinking-disable field was removed because the endpoint rejects it."""
    primary, _ = research._narrator_http_timeouts()
    assert primary > 5.0, primary


def test_the_two_vendors_share_one_budget():
    """Raising both sides would make a fully failing tick a 20-second tick, and the
    P1/P2 narrator cadence is 6 seconds."""
    primary, fresh_fallback = research._narrator_http_timeouts(0.0)
    assert primary + research.NARRATOR_FALLBACK_FLOOR_S <= \
        research.NARRATOR_HTTP_BUDGET_S + 1e-9
    assert fresh_fallback <= research.NARRATOR_HTTP_BUDGET_S + 1e-9
    # After the primary burns its whole share, the fallback still gets the floor.
    _, spent_fallback = research._narrator_http_timeouts(primary)
    assert spent_fallback == research.NARRATOR_FALLBACK_FLOOR_S


def test_the_fallback_share_shrinks_as_the_primary_spends():
    a = research._narrator_http_timeouts(0.5)[1]
    b = research._narrator_http_timeouts(5.0)[1]
    assert a > b, (a, b)


def test_neither_vendor_can_be_handed_a_useless_timeout():
    """requests treats a zero/negative timeout as fail-immediately, which would
    silence narration rather than degrade it."""
    for spent in (0.0, 1.0, 999.0, -5.0):
        primary, fallback = research._narrator_http_timeouts(spent)
        assert primary >= research.NARRATOR_FALLBACK_FLOOR_S, (spent, primary)
        assert fallback >= research.NARRATOR_FALLBACK_FLOOR_S, (spent, fallback)


def test_a_misconfigured_budget_below_the_floor_still_leaves_room_for_both(monkeypatch):
    monkeypatch.setattr(research, "NARRATOR_HTTP_BUDGET_S", 1.0)
    primary, fallback = research._narrator_http_timeouts()
    assert primary >= research.NARRATOR_FALLBACK_FLOOR_S
    assert fallback >= research.NARRATOR_FALLBACK_FLOOR_S


def test_the_gemini_post_actually_uses_the_computed_timeout(monkeypatch):
    """Executed, not read. The literal `5` was in the call for months; a shape test
    that looked for a name would pass against `timeout=_primary_timeout` even if the
    helper returned 5."""
    seen = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "narration"}]}}]}

    import requests as _rq

    def _post(url, json=None, timeout=None, **kw):
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(_rq, "post", _post)
    text, sc = research._call_text_narrator(
        "sys", "user", gemini_key="k", use_gemini=True)
    assert (text, sc) == ("narration", 200)
    assert seen["timeout"] == research._narrator_http_timeouts()[0]
    assert seen["timeout"] > 5.0


def _fallback_timeout_after(monkeypatch, primary_seconds):
    """Run the real narrator with a primary that burns `primary_seconds` then fails,
    and report the timeout the Anthropic client was constructed with.

    The content block carries `type="text"` because production filters on it — a
    double that answered without it would prove nothing about the fallback.
    """
    import requests as _rq
    import time as _t

    def _slow_post(url, json=None, timeout=None, **kw):
        if primary_seconds:
            _t.sleep(primary_seconds)
        raise _rq.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(_rq, "post", _slow_post)
    seen = {}

    class _FakeAnthropic:
        def __init__(self, api_key=None, timeout=None):
            seen["timeout"] = timeout
            self.messages = self

        def create(self, **kw):
            class _M:
                content = [type("B", (), {"text": "haiku narration",
                                          "type": "text"})()]
            return _M()

    import anthropic as _anth
    monkeypatch.setattr(_anth, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(research, "resolve_api_key", lambda *a, **k: "key")

    text, sc = research._call_text_narrator(
        "sys", "user", gemini_key="k", use_gemini=True)
    assert (text, sc) == ("haiku narration", 200), (text, sc)
    return seen["timeout"]


def test_the_fallback_client_is_given_what_the_primary_left(monkeypatch):
    """Measured, not assumed: a fallback that always got the full budget would make a
    doubly-failing tick take budget + budget."""
    spent = _fallback_timeout_after(monkeypatch, 1.0)
    assert spent <= research.NARRATOR_HTTP_BUDGET_S - 0.9, spent
    assert spent >= research.NARRATOR_FALLBACK_FLOOR_S, spent


def test_an_instantly_failing_primary_does_not_starve_the_fallback(monkeypatch):
    """A refused connection or a bad key costs no time, so the fallback should get the
    whole budget — the split debits what was actually spent, not a fixed share."""
    fresh = _fallback_timeout_after(monkeypatch, 0.0)
    assert fresh > research._narrator_http_timeouts(
        research.NARRATOR_HTTP_BUDGET_S)[1], fresh
    assert fresh <= research.NARRATOR_HTTP_BUDGET_S + 1e-9, fresh


def test_no_bare_five_second_timeout_survives_in_the_narrator():
    """The two literals this wave replaced, so a future edit cannot quietly restore
    the ceiling that produced 30 fallbacks in one run."""
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research._call_text_narrator)
    assert "timeout=5)" not in src, src
    assert "timeout=5.0)" not in src, src
    assert "_primary_timeout" in src
    assert "_fallback_timeout" in src


# ── f13c: the override has to be reachable from where it is actually set. ─────

def test_the_budget_override_is_read_at_call_time_not_at_import(monkeypatch):
    """`_load_env_file(args.env_file)` runs inside `main()`, i.e. long after this
    module's constants bind — so a module-level `os.environ.get` could never see
    `DG_NARRATOR_HTTP_BUDGET` from `.dg-supervisor.env`. Measured before the fix: env
    set before import gave 99.0, set after import still gave 14.0.

    Setting it here simulates exactly that ordering: the module is already imported.
    """
    monkeypatch.setenv("DG_NARRATOR_HTTP_BUDGET", "40")
    assert research._narrator_http_budget_s() == 40.0
    primary, fallback = research._narrator_http_timeouts()
    assert primary == 36.0
    assert fallback == 40.0


def test_the_budget_falls_back_to_the_default_when_unset(monkeypatch):
    monkeypatch.delenv("DG_NARRATOR_HTTP_BUDGET", raising=False)
    assert research._narrator_http_budget_s() == research.NARRATOR_HTTP_BUDGET_S
    assert research._narrator_http_timeouts() == (10.0, 14.0)


def test_a_typo_in_the_env_file_does_not_stop_narration(monkeypatch):
    """Narration is a nicety. A bad value degrades to the default rather than raising
    out of a P2 tick."""
    monkeypatch.setenv("DG_NARRATOR_HTTP_BUDGET", "14s")
    assert research._narrator_http_budget_s() == research.NARRATOR_HTTP_BUDGET_S
    monkeypatch.setenv("DG_NARRATOR_HTTP_BUDGET", "")
    assert research._narrator_http_budget_s() == research.NARRATOR_HTTP_BUDGET_S


def test_the_module_constant_no_longer_reads_the_environment():
    """If the constant went back to `float(os.environ.get(...))` the tests above would
    still pass in a fresh process where the var happens to be set at import — so pin
    the shape too. The constant is a plain default; the env read lives in the helper."""
    src = Path(research.__file__).read_text(encoding="utf-8")
    line = [ln for ln in src.splitlines()
            if ln.startswith("NARRATOR_HTTP_BUDGET_S")][0]
    assert "os.environ" not in line, line
    from conftest import code_only_deep  # type: ignore
    assert "DG_NARRATOR_HTTP_BUDGET" in code_only_deep(research._narrator_http_budget_s)


# ── f9: Step 2½ must compare paths, not raw URLs. ────────────────────────────

# ⚠ BOTH of the next two asserted `out` alone, and BOTH survived mutation. The outcome
# cannot tell the branches apart: on a FALSE abort the recovery presses New chat, the
# retry runs with no suffix, and setup succeeds — so `out is True` either way. The
# discriminator is whether the drift branch FIRED AT ALL, and `state["new_chats"]` is
# the only thing that reports it. Same lesson this codebase keeps paying for: assert the
# condition, not an end state a second path can also reach.


def test_a_streaming_query_param_is_not_a_tab_move(monkeypatch):
    """ChatGPT appends `?messageId=finalAgentTurnStart` to the SAME conversation as it
    streams — it is on the incident's own URLs in Chrome's history. A raw string
    comparison calls that a tab move, and this branch does not merely warn: it gives
    the DR intent up entirely rather than handing it to the next rung.
    """
    out, page, state = _run_setup_with_recovery(
        moves_on_press=set(),
        url_suffix_on_press="?messageId=finalAgentTurnStart")
    assert out is True, page.calls
    assert state["new_chats"] == 0, (
        "a query param appearing on the same conversation triggered the drift "
        "recovery — the comparison is reading the raw URL")
    # One pass through Step 2 only. A silent abort+retry would double the presses.
    assert state["presses"] == 1, state


def test_a_real_path_change_is_still_a_tab_move():
    """The other half — stripping the query must not blind the check to the thing it
    exists for. This is the incident's own shape: `/` → `/c/<last night's id>`.

    `new_chats == 1` is the assertion that matters: it is the only proof the drift
    branch ran. A comparison normalised past the path never aborts, so it never
    recovers — and with `new_chat_works=False` the outcome is False in both worlds.
    """
    out, page, state = _run_setup_with_recovery(moves_on_press={1},
                                                new_chat_works=False)
    assert out is False, page.calls
    assert state["new_chats"] == 1, (
        "the tab moved to a different PATH and nothing aborted — the comparison is "
        "normalising away more than the query string")
