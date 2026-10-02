"""The owner's 09-30 run, Claude, round 2 — built on the captures.

Every test here loads a LOCAL page rebuilt from the owner's two claude.ai
captures (tests/fixtures/claude_0930, see `_claude_0930_pages`) into headless
Chrome, drives the production code the run goes through, and fails on the code
the run used (df26bdd):

  1. Effort by the page: the model button → hover "Effort" → press "Extra" →
     read the BUTTON back ("Opus 5.5 Extra"). The press closes both menus, so
     the old read of the row after it found nothing and called a set tier unset.
     And right before Send, a tier that drifted (the owner moved it to Low by
     hand on 09-30) is set again by the page.
  2. The Research switch: found in the "+" menu past its icon glyph, pressed for
     real, read back from the row.
  3. The Research panel: the research card pressed for real and waited for; its
     sources rows read on every check without pressing anything; Claude's new
     left sidebar kept out of the steps.
  4. The report: its card pressed, its panel detected, and "Download as
     Markdown" taken by the page — no computer use, and (2026-10-02) its file
     caught on the page, never downloaded by Chrome.
  5. One Sources list: a report shaped like Claude's (no url in the prose, its
     own numbered "## Sources") is no longer given a second numbered copy.

Nothing opens a real website: the pages are set as content and every network
request from the context is refused.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import textwrap
from types import SimpleNamespace

import pytest

import models
import research
import _claude_0930_pages as P


# ═════════════════════════════════════════════════════════════════════════════
# The browser
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def chrome():
    try:
        from patchright.async_api import async_playwright
    except Exception as e:                                    # pragma: no cover
        pytest.skip(f"patchright unavailable: {e}")
    loop = asyncio.new_event_loop()

    async def _start():
        pw = await async_playwright().start()
        try:
            b = await pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            await pw.stop()
            raise
        ctx = await b.new_context(viewport={"width": 1280, "height": 800},
                                  accept_downloads=True)
        await ctx.route("**/*", lambda route: route.abort())   # no real site, ever
        return pw, b, ctx

    try:
        pw, b, ctx = loop.run_until_complete(_start())
    except Exception as e:                                    # pragma: no cover
        loop.close()
        pytest.skip(f"system Chrome unavailable: {e}")
    yield SimpleNamespace(run=loop.run_until_complete, ctx=ctx)
    loop.run_until_complete(b.close())
    loop.run_until_complete(pw.stop())
    loop.close()


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(research, "log",
                        lambda m, lv="INFO", *a, **k: out.append((lv, str(m))))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_DOM_ATTEMPTS", [])
    monkeypatch.setattr(research, "_P2_THINKING_STATE", {})
    monkeypatch.setattr(research, "_P2_PICKED_VERSION", {})
    return out


@pytest.fixture
def open_page(chrome):
    pages = []

    def _open(**kw):
        pg = chrome.run(chrome.ctx.new_page())
        pages.append(pg)
        chrome.run(pg.set_content(P.page(**kw)))
        return pg

    yield _open
    for pg in pages:
        chrome.run(pg.close())


def _presses(chrome, page):
    return chrome.run(page.evaluate(
        "() => JSON.parse(document.documentElement.getAttribute('data-sr-presses'))"))


def _button(chrome, page):
    return chrome.run(page.evaluate(
        "() => document.querySelector('[data-testid=\"model-selector-dropdown\"]')"
        ".getAttribute('aria-label')"))


# ═════════════════════════════════════════════════════════════════════════════
# 1. Effort by the page
# ═════════════════════════════════════════════════════════════════════════════

def test_setup_sets_extra_by_the_page_and_believes_the_button(chrome, open_page, lines):
    """Capture 1, frames 2-6: "Opus 5.5 Medium" → hover Effort → press Extra →
    the menus close and the button reads "Opus 5.5 Extra". The run must say the
    tier is SET — on df26bdd it pressed Extra, read the row that had just
    disappeared, and reported the tier unconfirmed."""
    assert models.p2_labels("claude")["effort"] == "extra"
    page = open_page(tier="Medium")
    chrome.run(research.setup_claude_dr(page))
    assert _button(chrome, page) == "Model: Opus 5.5 Extra"
    assert {"what": "effort:xhigh", "trusted": True} in _presses(chrome, page)
    st = research._P2_THINKING_STATE["claude"]
    assert st["effort"] is True and st["effort_got"] == "extra", (st, lines)
    ledger = [r for r in research._DOM_ATTEMPTS if r["intent"] == "claude.select_effort_tier"]
    assert ledger and ledger[-1]["outcome"] in research._DOM_OK, (ledger, lines)
    assert not any(lv == "WARN" and "effort" in m.lower() for lv, m in lines), lines
    # The option was found by its captured `data-effort-id`, not by its text.
    assert any("Step 1C OK: Effort 'extra' selected via effort-id" in m
               for _, m in lines), lines


def test_a_tier_moved_by_hand_before_send_is_set_again_by_the_page(chrome, open_page, lines):
    """09-30: setup read the wanted tier, the owner moved it to Low by hand, and
    Claude researched at Low. The pre-send check now sets it again — and never
    touches the model or the "+" menu doing it."""
    page = open_page(tier="Extra", research_on=True)
    chrome.run(page.evaluate(
        "() => document.dispatchEvent(new CustomEvent('sr-set-tier', {detail: 'Low'}))"))
    assert _button(chrome, page) == "Model: Opus 5.5 Low"
    research._P2_THINKING_STATE["claude"] = {"effort": True, "effort_got": "extra",
                                             "thinking": False, "model": True}
    state = chrome.run(research.ensure_deep_mode_active(page, "claude", "2B"))
    assert state.get("effortShown") == "extra", (state, lines)
    assert _button(chrome, page) == "Model: Opus 5.5 Extra"
    presses = _presses(chrome, page)
    assert {"what": "effort:xhigh", "trusted": True} in presses, presses
    assert not [p for p in presses if p["what"] in ("plus", "research-row")], presses
    assert research._P2_THINKING_STATE["claude"]["model"] is True


def test_a_wanted_tier_at_send_touches_nothing(chrome, open_page, lines):
    page = open_page(tier="Extra", research_on=True)
    state = chrome.run(research.ensure_deep_mode_active(page, "claude", "2B"))
    assert state.get("effortShown") == "extra"
    assert _presses(chrome, page) == []


# ═════════════════════════════════════════════════════════════════════════════
# 2. The Research switch
# ═════════════════════════════════════════════════════════════════════════════

def test_research_is_switched_on_by_a_real_press_and_read_back(chrome, open_page, lines):
    """Capture 1, frames 16-22: the row is `menuitemcheckbox` "\\ue0d0Research"
    (data-testid add-menu-research); pressing it closes the menu, and the menu
    opened again shows it checked. On df26bdd Step 3B looked for the text
    'research' exactly, never matched the glyph, and handed the switch to
    computer use (7 steps on 09-30)."""
    page = open_page(tier="Extra")
    ok = chrome.run(research.setup_claude_dr(page))
    row = chrome.run(page.evaluate(
        "() => document.querySelector('[data-testid=\"add-menu-research\"]')"
        ".getAttribute('aria-checked')"))
    assert row == "true", lines
    assert ok is True, lines
    presses = _presses(chrome, page)
    assert [p for p in presses if p["what"] == "research-row"] == [
        {"what": "research-row", "trusted": True}], presses
    assert chrome.run(page.evaluate(
        "() => document.getElementById('sr-plus-menu').hasAttribute('hidden')")), \
        "the menu opened to read the row back must be closed again"
    assert any("Step 3B: pressed Research (playwright, via testid)" in m
               for _, m in lines), lines


def test_research_is_found_by_its_text_past_the_icon_glyph(chrome, open_page, lines):
    """The row without its test id: its text is "\ue0d0Research" — the glyph that
    has defeated the exact match since 09-03."""
    page = open_page(tier="Extra", research_testid=False)
    assert chrome.run(research.setup_claude_dr(page)) is True, lines
    assert chrome.run(page.evaluate(
        "() => document.querySelector('[data-sr-research-row]')"
        ".getAttribute('aria-checked')")) == "true"
    assert any("via text)" in m and "Step 3B: pressed Research" in m for _, m in lines), lines


def test_a_press_that_did_not_take_is_not_called_on(chrome, open_page, lines):
    """Found is not on, and pressed is not on: only the row read back decides."""
    page = open_page(tier="Extra", research_sticks=False)
    assert chrome.run(research.setup_claude_dr(page)) is False, lines
    assert any(lv == "WARN" and "the row now reads NOT checked" in m
               for lv, m in lines), lines


def test_research_already_on_is_left_alone(chrome, open_page, lines):
    page = open_page(tier="Extra", research_on=True)
    assert chrome.run(research.setup_claude_dr(page)) is True
    assert not [p for p in _presses(chrome, page) if p["what"] == "research-row"]


# ═════════════════════════════════════════════════════════════════════════════
# 3. The Research panel: a real press, its sources rows, no sidebar
# ═════════════════════════════════════════════════════════════════════════════

def test_the_research_card_is_pressed_for_real_and_the_panel_waited_for(
        chrome, open_page, lines):
    """Capture 2: the card is a <button> ending "Open research panel.". The panel
    here opens 2 s after the press; df26bdd dispatched a synthetic pointer chain
    and looked once at 1.5 s ("did not mount the side panel", 39 times against
    33 opens in the corpus)."""
    page = open_page(running=True)
    chrome.run(research.scrape_claude_artifact_tracking(
        page, keep_open=True, already_open=False))
    presses = [p for p in _presses(chrome, page) if p["what"] == "research-card"]
    assert presses == [{"what": "research-card", "trusted": True}], (presses, lines)
    assert any("research panel open after a real press" in m for _, m in lines), lines
    st = chrome.run(research._claude_artifact_panel_state(page))
    assert st.get("open") is True, st


def _sources_block_source() -> str:
    """The poll loop's Claude sources block, as the loop runs it."""
    src = inspect.getsource(research.poll_all_agents_round_robin)
    head = '            if name == "Claude" and scrape_ok:\n'
    tail = '                    log(f"[Claude] source-count union skipped: {_cl_se}", "DEBUG")\n'
    assert src.count(head) == 1 and src.count(tail) == 1, "the sources block moved"
    i = src.index(head)
    block = textwrap.dedent(src[i:src.index(tail, i) + len(tail)])
    return ("async def __sources__(name, scrape_ok, p, progress):\n"
            + textwrap.indent(block, "    "))


def _run_sources_block(chrome, page, p, lines):
    ns = dict(vars(research))
    ns["log"] = lambda m, lv="INFO", *a, **k: lines.append((lv, str(m)))
    exec(compile(_sources_block_source(), "<sources>", "exec"), ns)
    progress = {"observed_sources": 0, "printed_sources": 0, "source_urls": []}
    chrome.run(ns["__sources__"]("Claude", True, p, progress))
    return progress


def test_the_sources_rows_are_read_on_every_check_without_a_press(
        chrome, open_page, lines):
    """Capture 2, frames 49 and 64: the panel's rows read "royalcanin.com 19
    sources …", "petsmart.com 42 sources …". df26bdd read no row while the run
    went (09-30: 'toggle=336 … url=0') and the list is gone at the end."""
    page = open_page(running=True, panel="research")
    p = {"page": page}
    progress = _run_sources_block(chrome, page, p, lines)
    assert progress.get("source_hosts") == ["royalcanin.com", "petsmart.com"], (
        progress, lines)
    assert progress["observed_sources"] == 19 + 42
    assert _presses(chrome, page) == [], "the rows are read, never pressed"
    # The research finishes and the rows are gone: the run keeps what it saw.
    chrome.run(page.evaluate("() => { document.getElementById('sr-panel-slot')"
                             ".innerHTML = ''; }"))
    again = _run_sources_block(chrome, page, p, lines)
    assert again.get("source_hosts") == ["royalcanin.com", "petsmart.com"]
    # …and the finished read hands them to the run's record.
    snaps = {"claude": {"source_urls": [], "observed_sources": 61}}
    chrome.run(research.claude_finished_sources_read(page, p, snaps))
    assert snaps["claude"].get("source_host_count") == 2, snaps


def _rescue_block_source() -> str:
    """The poll loop's one-shot vision rescue (Block 3), as the loop runs it."""
    src = inspect.getsource(research.poll_all_agents_round_robin)
    head = "            # ── Block 3: vision-extract source URLs from side panel ──\n"
    tail = "                        p[\"vision_urls_done\"] = True  # don't retry on failure\n"
    assert src.count(head) == 1 and src.count(tail) == 1, "the rescue block moved"
    i = src.index(head)
    block = textwrap.dedent(src[i:src.index(tail, i) + len(tail)])
    return ("async def __rescue__(name, p, progress, elapsed):\n"
            + textwrap.indent(block, "    "))


def _run_rescue_block(chrome, p, progress, lines, monkeypatch):
    """Run the rescue with the screenshot-and-model call replaced by a
    recorder. Returns the calls it made."""
    shots = []

    async def _vision(page, agent_key, last_dom_count=0):
        shots.append(agent_key)
        return []

    monkeypatch.setenv("DG_VISION_URL_EXTRACT", "1")
    ns = dict(vars(research))
    ns["log"] = lambda m, lv="INFO", *a, **k: lines.append((lv, str(m)))
    ns["extract_source_urls_via_vision"] = _vision
    exec(compile(_rescue_block_source(), "<rescue>", "exec"), ns)
    chrome.run(ns["__rescue__"]("Claude", p, progress, 900))
    return shots


def test_the_vision_rescue_is_not_spent_once_the_research_panel_lists_sites(
        chrome, open_page, lines, monkeypatch):
    """⛔ 09-30 review: the rows reach `_claude_row_hosts` and never `sources`,
    which stays 0 for Claude, so the one-shot vision rescue took a screenshot
    and a model call on every Claude run and found nothing — the panel lists
    sites, not urls. Driven in the order one check runs — the logs show the
    rescue in the same check the panel first opened: the rows are read with the
    panel shut, the panel is opened, then the rescue decides."""
    page = open_page(running=True)
    p = {"page": page}
    progress = _run_sources_block(chrome, page, p, lines)
    assert not p.get("_claude_row_hosts"), "the panel was shut: no rows yet"
    assert chrome.run(research._claude_open_research_panel(page)).get("open") is True
    p["artifact_panel_open"] = True
    shots = _run_rescue_block(chrome, p, progress, lines, monkeypatch)
    assert shots == [], (shots, lines)
    assert list(p["_claude_row_hosts"]) == ["royalcanin.com", "petsmart.com"]
    assert p.get("vision_urls_done") is True
    assert any("vision-urls rescue not needed: the research panel lists 2 site(s)" in m
               for _, m in lines), lines


def test_an_open_panel_that_lists_no_sites_is_still_rescued(
        chrome, open_page, lines, monkeypatch):
    """The no-change guard: no sites kept, so the open panel's rescue runs as it
    always has — once."""
    page = open_page(running=True, panel="report")
    p = {"page": page, "artifact_panel_open": True}
    progress = _run_sources_block(chrome, page, p, lines)
    shots = _run_rescue_block(chrome, p, progress, lines, monkeypatch)
    assert shots == ["claude"], (shots, lines)
    assert p.get("vision_urls_done") is True
    assert not p.get("_claude_row_hosts")


def test_the_steps_leave_claudes_left_sidebar_out(chrome, open_page, lines):
    """Capture 2's sidebar is an <aside aria-label="Sidebar">; on 09-30 the
    saved steps began "Artifacts", "Projects", "Pin projects to keep them
    here", "Pinned… Drag to pin", "Chats and tasks"."""
    page = open_page(running=True, panel="research")
    got = chrome.run(research.scrape_progress_claude(page))
    steps = got.get("steps") or []
    joined = "\n".join(steps)
    for side in ("Chats and tasks", "Pin projects", "Shift", "Boss"):
        assert side not in joined, (side, steps)
    assert "Searching for large-breed dog food brand comparisons" in joined, steps


# ═════════════════════════════════════════════════════════════════════════════
# 4. The report, by the page
# ═════════════════════════════════════════════════════════════════════════════

def _downloads(page):
    got = []
    page.on("download", lambda d: got.append(d))
    return got


def test_the_report_is_opened_and_exported_by_the_page_and_chrome_downloads_nothing(
        chrome, open_page, lines, monkeypatch):
    """Capture 2, frames 86-91: the report card (`artifact-card-open`), its
    panel (`[role=region][aria-label^="Artifact panel"]`), "Copy options", then
    "Download as Markdown" (`export-download`). Computer use is THERE and must
    not be called: on 09-30 it opened the report (3 steps) and downloaded it
    (2), and the mount probe never once saw Claude's panel in the corpus.
    ⛔⛔ 2026-10-02 — and Chrome downloads NOTHING: the page makes the file as
    claude.ai does (a Blob's address on an `<a download>`, then `click()`), and
    the export catcher takes it instead of Chrome."""
    cua = []

    async def _cua(*a, **k):
        cua.append(k.get("current_step") or (a[4] if len(a) > 4 else "?"))
        return {"text": ""}

    async def _cua_export(*a, **k):
        cua.append("cua_export")
        return None

    async def _agent_loop(*a, **k):
        cua.append("agent_loop")
        return {}

    class _Browser:
        async def switch_to_page(self, page):
            return None

    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    monkeypatch.setattr(research, "_cua_export_caught", _cua_export)
    monkeypatch.setattr(research, "agent_loop", _agent_loop)
    page = open_page(finished=True)
    downloads = _downloads(page)
    text = chrome.run(research.extract_claude_response(page, browser=_Browser(),
                                                       cua_client=object()))
    assert text == P.REPORT_MD, (text[:200], lines)
    assert cua == [], (cua, lines)
    assert downloads == [], "Chrome downloaded Claude's report"
    presses = _presses(chrome, page)
    for what in ("report-card", "copy-options", "download-md"):
        assert {"what": what, "trusted": True} in presses, (what, presses)
    assert any("export caught in the page, no download: markdown "
               "\"large-breed-dog-food.md\"" in m for _, m in lines), lines
    assert any("Chrome downloads seen during the export: 0" in m for _, m in lines), lines
    assert any("Extracted via the page's Download as Markdown, caught in the page" in m
               for _, m in lines), lines
    # Claude's own left sidebar is not an open panel to close first.
    assert not any("Closing artifact panel" in m for _, m in lines), lines


def test_nothing_is_pressed_for_the_export_without_the_catcher(chrome, open_page, lines,
                                                               monkeypatch):
    """⛔ The catcher cannot be put on the page: neither the page nor computer
    use presses the export (a press would be a Chrome download); the report is
    read from its open panel instead."""
    calls = []

    async def _cua(*a, **k):
        return {"text": ""}

    async def _cua_export(*a, **k):
        calls.append("cua_export")
        return None

    real = research._page_world_evaluate

    async def _no_catcher(target, js, *a, **k):
        if js == research._EXPORT_CATCH_JS:
            raise RuntimeError("the page refused the script")
        return await real(target, js, *a, **k)

    class _Browser:
        async def switch_to_page(self, page):
            return None

    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    monkeypatch.setattr(research, "_cua_export_caught", _cua_export)
    monkeypatch.setattr(research, "_page_world_evaluate", _no_catcher)
    page = open_page(finished=True)
    downloads = _downloads(page)
    chrome.run(research.extract_claude_response(page, browser=_Browser(), cua_client=object()))
    presses = _presses(chrome, page)
    for what in ("copy-options", "download-md"):
        assert not any(p.get("what") == what for p in presses), (what, presses)
    assert calls == [] and downloads == []
    assert any("the export catcher could not be put on the page" in m for _, m in lines), lines


def test_computer_use_presses_the_export_when_the_page_cannot(chrome, open_page, lines,
                                                              monkeypatch):
    """The page cannot press the export (a future rename): computer use presses
    Copy options and Download as Markdown — stood in here by presses on the
    page's own controls — and the catcher still takes the file: no download."""
    prompts = []

    async def _cua(*a, **k):
        return {"text": ""}

    async def _no_page_export(*a, **k):
        return ""

    async def _agent_loop(client, browser, prompt, msg, *, abort_event=None, target_page=None,
                          **k):
        prompts.append(prompt)
        await research._page_world_evaluate(target_page, """() => {
            document.querySelector('#sr-copy-options').click();
            document.querySelector('[data-testid="export-download"]').click(); }""")
        for _ in range(100):
            if abort_event is not None and abort_event.is_set():
                return {"status": "aborted"}
            await asyncio.sleep(0.05)
        return {"status": "max_iterations"}

    class _Browser:
        async def switch_to_page(self, page):
            return None

    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    monkeypatch.setattr(research, "_claude_export_report_by_page", _no_page_export)
    monkeypatch.setattr(research, "agent_loop", _agent_loop)
    page = open_page(finished=True)
    downloads = _downloads(page)
    text = chrome.run(research.extract_claude_response(page, browser=_Browser(),
                                                       cua_client=object()))
    assert prompts == [research.PROMPT_CLAUDE_DOWNLOAD_MD], (prompts, lines)
    assert text == P.REPORT_MD, (text[:200], lines)
    assert downloads == [], "Chrome downloaded Claude's report"
    assert any("Extracted via T1 computer use export (.md), caught in the page" in m
               for _, m in lines), lines


# ═════════════════════════════════════════════════════════════════════════════
# The words: no Max for Claude's effort; the narrator hears the panel's sites
# ═════════════════════════════════════════════════════════════════════════════

def test_claude_effort_is_not_max_in_the_hints_or_the_narration():
    for key in ("setup-dr", "validate-setup"):
        hint = research._sub_claude_family(research._HOTSPOT_VISION_HINTS[key])
        text = hint["context_hint"] + " ".join(hint.get("success_signals") or [])
        assert not re.search(r"\bmax\b", text, re.I), (key, text)
    assert "Extra effort" in research.PHASE_FLOW_CONTEXT[2]
    assert not re.search(r"\bmax effort\b", research.PHASE_FLOW_CONTEXT[2], re.I)
    flow = " ".join(research.AGENT_PHASE_FLOWS[("claude", 2)])
    assert "(Extra effort)" in flow and "Max" not in flow


def test_the_narrator_hears_the_sites_the_research_panel_lists():
    events = [{"type": "agent_progress",
               "data": {"sourceUrls": [], "sourceHosts": ["royalcanin.com", "petsmart.com"]}}]
    assert research._extract_top_hosts(events) == ["royalcanin.com", "petsmart.com"]


# ═════════════════════════════════════════════════════════════════════════════
# 5. One Sources list
# ═════════════════════════════════════════════════════════════════════════════

CLAUDE_SHAPED = (
    "# The Golden Retriever: An Evidence-Based Guide\n\n"
    "A Golden Retriever is a good choice mainly for households that can give a "
    "large, athletic dog one to two hours of daily engagement.\n\n"
    "## Health\n\n"
    "The largest breed-specific burdens are cancer and hip dysplasia, and a "
    "breeder's health records are the best predictor a buyer has.\n\n"
    "## Sources\n\n"
    "1. [Golden Retriever](https://www.fci.be/Nomenclature/Standards/111g08-en.pdf)\n"
    "2. [Breed Standards : Golden Retriever](https://www.ukcdogs.com/golden-retriever)\n"
    "3. [Longevity of UK Dog Breeds](https://www.dogstrust.org.uk/about-us/longevity)\n")


class _Runtime:
    def __init__(self):
        self.agent_findings = {}
        self.agent_progress_snapshots = {}


def test_a_report_shaped_like_claudes_ends_with_one_sources_list(monkeypatch, tmp_path):
    """⛔ 09-30: Claude's document ended with its own "## Sources" AND
    "##### Sources (numbered)" holding the same ten entries, each row of the
    first also carrying a number link. Driven through the real phase-2 write."""
    saved = []

    async def _extract(page, **kw):
        return CLAUDE_SHAPED

    async def _same(text, label=None, **kw):
        return text

    async def _save(doc_type, content, name=None, **kw):
        saved.append((doc_type, content))
        return True

    async def _no_sleep(*a, **k):
        return None

    class _Page:
        url = "https://claude.ai/chat/abc"

    class _Browser:
        async def switch_to_page(self, page):
            return None

    monkeypatch.setattr(research, "_runtime", _Runtime(), raising=False)
    monkeypatch.setattr(research, "extract_claude_response", _extract)
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)
    monkeypatch.setattr(research, "_rehost_document_images", _same)
    monkeypatch.setattr(research, "save_document_to_firestore_with_retry", _save)
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_fb_uid", "uid-1")
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    asyncio.run(research.extract_and_record_agent("Claude", _Page(), _Browser(), None,
                                                  tmp_path))
    doc = (tmp_path / "documents" / "claude.md").read_text(encoding="utf-8")
    headings = re.findall(r"(?im)^#{1,6}[ \t]+(sources\b.*)$", doc)
    assert headings == ["Sources"], (headings, doc[-900:])
    for url in ("https://www.fci.be/Nomenclature/Standards/111g08-en.pdf",
                "https://www.ukcdogs.com/golden-retriever",
                "https://www.dogstrust.org.uk/about-us/longevity"):
        assert doc.count(url) == 1, (url, doc[-900:])
    assert saved and saved[-1][1] == doc


def test_a_report_citing_in_its_prose_is_still_numbered():
    """The other half: a url cited in the prose keeps its number and its row."""
    md = ("## Findings\n\nPack prices fell by a fifth, reported at "
          "https://bnef.example.com/packs in a note nobody disputed.\n\n"
          "## Sources\n\n1. [BNEF](https://bnef.example.com/packs)\n")
    out = research._document_with_sources(md)
    assert "[\\[1\\]](https://bnef.example.com/packs)" in out
    assert "##### Sources (numbered)" in out
