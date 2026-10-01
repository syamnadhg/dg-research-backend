"""NotebookLM audio: short is Deep dive + Short in the WHOLE run, not only in
the Customise window.

The owner's decision (09-30): every podcast length is a Deep dive — short =
Deep dive + Short, default = Deep dive + Default, long = Deep dive + Long.
Brief is never chosen ("a two-minute podcast is not really a podcast"; the
Brief cards in this machine's logs ran 1:32 to 1:59). The page's own choice
changed first (test_nlm_customise_0930.py). These tests cover the rest of the
step, which still took short to mean Brief:

  - the words computer use is handed when it takes the open window,
  - the completion check and the download, which were told to look for a
    Brief card,
  - the download pick, which took the Brief card (or, with none, the FIRST
    card). Short now takes the SHORTEST Deep dive card and long the LONGEST,
    by the duration each card shows; default, or no duration shown, the LAST.
  - the download's own menu click, which opened the TOPMOST audio card's ⋮
    whatever the pick said.

Every test runs Phase 3's real audio step, `run_phase3_audio`, in headless
Chrome on the capture-5 page (test_nlm_customise_0930's fixture), with the
Studio list filled by finished audio cards shaped like the 09-30 run's dump.
Computer use is a recorder. Nothing opens a real website.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import research
from test_nlm_customise_0930 import (  # noqa: F401  (_customise_chrome is a fixture)
    NB_URL, _QuickAsyncio, _fixture_html, chrome as _customise_chrome)


@pytest.fixture(scope="module")
def chrome(request):
    """test_nlm_customise_0930's headless Chrome, under the name these tests
    ask for. Imported as `chrome` itself — or taken as an argument here — it
    reads as a redefinition to the lint floor (F811, run with --ignore-noqa)."""
    return request.getfixturevalue("_customise_chrome")


def _card(fmt, dur, title):
    """A finished audio card, shaped like the 09-30 run's #757-B dump
    (artifact-library-item > … > mat-icon audio_spark, "Unread", the title).
    The second line is capture 5's `span.artifact-details`, "61:59 · Deep dive
    · 2 sources · 6h ago"; `dur` empty gives the 06-03 dump's line, which
    showed no duration."""
    return (
        '<artifact-library-item class="has-unseen-dot" data-studio-accent="blue">'
        '<div class="artifact-item-button"><div class="artifact-button-content">'
        '<div class="artifact-primary-content" aria-hidden="true">'
        '<mat-icon>audio_spark</mat-icon><span>Unread</span>'
        f'<span class="artifact-title">{title}</span></div>'
        f'<span class="artifact-details">{dur + " · " if dur else ""}{fmt} · 3 sources'
        ' · 2m ago</span>'
        '</div></div>'
        '<button aria-label="More" aria-haspopup="menu"><mat-icon>more_vert</mat-icon></button>'
        '</artifact-library-item>')


BRIEF = _card("Brief", "1:38", "Golden Retrievers in Brief")
DEEP_8 = _card("Deep dive", "7:55", "Golden Retriever Science Versus Marketing Myths")
DEEP_14 = _card("Deep dive", "14:10", "The Golden Retriever Question")
DEEP_62 = _card("Deep dive", "61:59", "Golden Retrievers, the Long Story")
UNTIMED_A = _card("Deep dive", "", "Retrievers Without a Clock")
UNTIMED_B = _card("Deep dive", "", "Retrievers Without a Clock, Again")

_LIBRARY = '<div class="artifact-library-ungrouped-items" id="library"></div>'


def _studio(*cards):
    """The notebook with the Customise window closed and these finished cards
    in the Studio list (none: nothing generating, nothing finished)."""
    src = _fixture_html()
    assert src.count(_LIBRARY) == 1, "the fixture's Studio list moved"
    return src.replace(_LIBRARY, _LIBRARY[:-len("</div>")] + "".join(cards) + "</div>")


# Each card's ⋮ opens its menu as the download step reads it (Share / Rename /
# Download / View prompt and sources / Delete) and marks itself expanded. Every
# press is recorded with the title of the card it belongs to.
_CARD_MENUS = """<script>
document.addEventListener('click', (e) => {
  const rec = (x) => {
    const got = JSON.parse(document.body.dataset.menus || '[]');
    got.push(x);
    document.body.dataset.menus = JSON.stringify(got);
  };
  const more = e.target.closest('artifact-library-item button[aria-label="More"]');
  if (!more) return;
  const title = more.closest('artifact-library-item').querySelector('.artifact-title').textContent;
  more.setAttribute('aria-expanded', 'true');
  rec('menu:' + title);
  const menu = document.createElement('div');
  menu.setAttribute('role', 'menu');
  menu.style.cssText = 'position:fixed;left:300px;top:120px;width:220px;background:#fff';
  for (const row of ['Share', 'Rename', 'Download', 'View prompt and sources', 'Delete']) {
    const b = document.createElement('button');
    b.setAttribute('role', 'menuitem');
    b.style.cssText = 'display:block;width:200px;height:32px';
    b.textContent = row;
    b.addEventListener('click', () => rec(row.toLowerCase() + ':' + title));
    menu.append(b);
  }
  document.getElementById('overlay').append(menu);
});
</script>"""


def _studio_with_menus(*cards):
    src = _studio(*cards)
    assert src.count("</body>") == 1, "the fixture's end moved"
    return src.replace("</body>", _CARD_MENUS + "</body>")


class _Reloads:
    """The real page, except that each reload shows the next Studio state (the
    last one stays), as NotebookLM serves a fresh page on every poll. The
    presses the page recorded are kept across a reload."""

    def __init__(self, page, *states):
        self._page, self._states, self.presses = page, list(states), []

    def __getattr__(self, name):
        return getattr(self._page, name)

    async def presses_now(self):
        return self.presses + json.loads(
            await self._page.evaluate("() => document.body.dataset.log || '[]'"))

    async def reload(self, **kw):
        if self._states:
            self.presses = await self.presses_now()
            await self._page.set_content(self._states.pop(0))


class _Controls:
    """The waits after Generate and between polls: the first `go` go on, then
    the step is stopped."""
    skipped_agents: set = set()

    def __init__(self, go):
        self.go = go

    async def interruptible_sleep(self, *a, **k):
        self.go -= 1
        return None if self.go >= 0 else "stop"

    def is_stop(self):
        return False

    def is_pause(self):
        return False


class _HandedTheDownload(BaseException):
    """Raised by the recorder once the download is handed to computer use:
    everything this file measures has happened by then."""


def _run(chrome, monkeypatch, tmp_path, length, page_html, *reloads, go=0,
         prefer_existing=False, menus=None):
    """Run the audio step. Returns (presses on the page, computer-use calls,
    log lines). With a `menus` list the download's own menu click is real:
    the step stops once it has pressed a menu row, and the card menu presses
    are added to `menus`."""
    lines, cua = [], []

    async def _cua(page, **k):
        cua.append(k)
        if k.get("current_step") == "download_audio_overview":
            raise _HandedTheDownload()
        if k.get("current_step") == "poll_audio_complete":
            return {"text": "still generating"}
        return {"text": "generating"}

    async def _false(*a, **k):
        return False

    async def _true(*a, **k):
        return True

    async def _none(*a, **k):
        return None

    async def _menu_not_opened(*a, **k):
        return {"verified": False, "why": "not measured here"}

    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append(str(m)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _QuickAsyncio())
    monkeypatch.setattr(research, "_controls", _Controls(go))
    monkeypatch.setattr(research, "_work_tab_signed_out", _false)
    monkeypatch.setattr(research, "_browser_context_is_dead", _false)
    monkeypatch.setattr(research, "check_hv_gate", _true)
    monkeypatch.setattr(research, "start_narration_ticker", lambda *a, **k: (None, None))
    monkeypatch.setattr(research, "stop_narration_ticker", _none)
    monkeypatch.setattr(research, "_observe_dom_success", lambda *a, **k: None)
    monkeypatch.setattr(research, "_dump_nlm_audio_dom", _none)
    if menus is None:
        monkeypatch.setattr(research, "_nlm_open_audio_menu", _menu_not_opened)
    else:
        real_pick = research._nlm_menu_pick

        async def _pick_then_stop(page, *a, **k):
            await real_pick(page, *a, **k)
            raise _HandedTheDownload()
        monkeypatch.setattr(research, "_nlm_menu_pick", _pick_then_stop)
    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)

    page = chrome.run(chrome.ctx.new_page())
    try:
        chrome.run(page.set_content(page_html))
        shown = _Reloads(page, *reloads)

        async def _url():
            return NB_URL

        browser = SimpleNamespace(page=shown, current_url=_url)
        try:
            chrome.run(research.run_phase3_audio.__wrapped__(
                browser, object(), NB_URL, tmp_path, podcast_length=length,
                prefer_existing_audio=prefer_existing))
        except _HandedTheDownload:
            pass
        presses = chrome.run(shown.presses_now())
        if menus is not None:
            menus += json.loads(chrome.run(page.evaluate(
                "() => document.body.dataset.menus || '[]'")))
    finally:
        chrome.run(page.close())
    return presses, cua, lines


def _step(cua, name):
    got = [c for c in cua if c.get("current_step") == name]
    assert len(got) == 1, [c.get("current_step") for c in cua]
    return got[0]["mission_prompt"]


# ═════════════════════════════════════════════════════════════════════════════
# Computer use, handed the open window, is told Deep dive + the length
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("length,want", [("short", "Short"), ("default", "Default"),
                                         ("long", "Long")])
def test_computer_use_is_told_deep_dive_and_the_length(chrome, monkeypatch, tmp_path,
                                                        length, want):
    """The app ignores the page's Deep dive on a window that opened on Critique,
    so computer use takes the open window. For short it was told "Choose the
    Brief format (no separate length step)" and FORMAT="Brief" with no length;
    default and long are unchanged."""
    presses, cua, lines = _run(chrome, monkeypatch, tmp_path, length,
                               _fixture_html(start="Critique", ignored="Deep dive"))
    assert presses == ["tile", "format:Deep dive"], (presses, lines)
    mission = _step(cua, "configure_generate_audio_panel_open")
    assert f'FORMAT="Deep dive" and LENGTH="{want}". Anything else is a failure.' in mission
    assert f'LENGTH = "{want}"' in mission, mission
    assert f"Choose Deep dive + {want} length in it" in mission, mission
    assert 'FORMAT="Brief"' not in mission and 'FORMAT = "Brief"' not in mission, mission
    assert f"Starting audio generation (Deep dive + {want} length)..." in lines, lines


# ═════════════════════════════════════════════════════════════════════════════
# The completion check and the download look for the Deep dive, not a Brief
# ═════════════════════════════════════════════════════════════════════════════

def test_short_is_checked_and_downloaded_as_the_deep_dive_it_made(chrome, monkeypatch,
                                                                 tmp_path):
    """Generated by the page; the first poll's page shows neither a
    placeholder nor a card, so computer use checks; the next shows the
    finished Deep dive. Both computer-use missions name the Deep dive + Short
    card — never "the Brief audio overview", which this run never made."""
    presses, cua, lines = _run(chrome, monkeypatch, tmp_path, "short", _fixture_html(),
                               _studio(), _studio(DEEP_8), go=3)
    assert presses == ["tile", "length:Short", "generate-now:Deep dive|Short"], (presses, lines)
    check = _step(cua, "poll_audio_complete")
    assert "the Deep Dive · Short audio overview you generated" in check, check
    assert "Brief audio overview" not in check, check
    download = _step(cua, "download_audio_overview")
    assert "Download the Deep Dive · Short audio overview you generated." in download, download
    assert "Brief audio overview" not in download, download
    assert "NOT a Deep Dive entry" not in download, download
    assert "target the BRIEF entry" not in download, download
    assert "MULTIPLE AUDIO ENTRIES EXIST" not in download, download


# ═════════════════════════════════════════════════════════════════════════════
# The download pick: Short the shortest Deep dive, Long the longest, by the
# duration each card shows; default (or no duration shown) the LAST
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("length,cards,want,how", [
    ("short", (BRIEF, DEEP_8), 2, "shortest deep-dive card (7:55)"),    # was 1: the Brief
    ("short", (DEEP_8, BRIEF), 1, "shortest deep-dive card (7:55)"),    # was 2: the Brief
    ("short", (DEEP_14, DEEP_8), 2, "shortest deep-dive card (7:55)"),
    # ⛔ The Short ABOVE a longer Deep dive (a misclick or a leftover card made
    # after it): "the last card" handed over the 14:10 or the 61:59 as the Short.
    ("short", (DEEP_8, DEEP_14), 1, "shortest deep-dive card (7:55)"),
    ("short", (DEEP_8, DEEP_62), 1, "shortest deep-dive card (7:55)"),
    ("long", (DEEP_62, DEEP_14), 1, "longest deep-dive card (61:59)"),
    ("long", (DEEP_14, DEEP_62), 2, "longest deep-dive card (61:59)"),
    ("long", (BRIEF, DEEP_14), 2, "longest deep-dive card (14:10)"),
    ("default", (DEEP_14, DEEP_8), 2, "last deep-dive card"),
    ("short", (UNTIMED_A, UNTIMED_B), 2, "last deep-dive card"),
], ids=["short-brief-then-deep", "short-deep-then-brief", "short-two-deep",
        "short-above-default", "short-above-long", "long-above-default",
        "long-below-default", "long-brief-then-deep", "default-two-deep",
        "short-no-duration-shown"])
def test_the_download_picks_the_deep_dive_of_the_asked_length(chrome, monkeypatch,
                                                              tmp_path, length, cards,
                                                              want, how):
    """The no-audio retry (prefer_existing_audio): two finished cards are
    already there, so nothing is generated and the picker chooses which one
    computer use downloads — never a Brief. Every length is a Deep dive, so
    the card's duration tells them apart; card order only when no card shows
    one. The mission's "Entry #N is the Short" and its "SHORTEST-DURATION"
    tie-break now name the same card."""
    presses, cua, lines = _run(chrome, monkeypatch, tmp_path, length, _studio(*cards),
                               go=1, prefer_existing=True)
    assert presses == [], presses
    assert [c.get("current_step") for c in cua] == ["download_audio_overview"], cua
    download = _step(cua, "download_audio_overview")
    assert f"download ONLY entry #{want} counting from the TOP" in download, download
    target = [m for m in lines if m.startswith("[Phase3] Download target:")]
    assert len(target) == 1 and f"ordinal={want}/2" in target[0], lines
    assert f"{length}→{how}" in target[0], target


@pytest.mark.parametrize("length,cards,want", [
    ("short", (DEEP_14, DEEP_8), "Golden Retriever Science Versus Marketing Myths"),
    ("long", (DEEP_14, DEEP_62), "Golden Retrievers, the Long Story"),
], ids=["short-below-default", "long-below-default"])
def test_the_page_downloads_the_card_the_pick_chose(chrome, monkeypatch, tmp_path,
                                                    length, cards, want):
    """⛔ The download that runs FIRST is the page's own ⋮ → Download, and it
    opened the TOPMOST audio card's menu whatever the pick said — computer use,
    told the picked entry, runs only when that click misses. Here the menu
    click is real: with the asked-for card second, it must open THAT card's ⋮
    and press ITS Download."""
    menus = []
    _run(chrome, monkeypatch, tmp_path, length, _studio_with_menus(*cards),
         go=1, prefer_existing=True, menus=menus)
    assert menus == [f"menu:{want}", f"download:{want}"], menus
