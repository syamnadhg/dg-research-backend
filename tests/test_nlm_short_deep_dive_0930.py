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
    card) where default and long take the LAST Deep dive card.

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
from test_nlm_customise_0930 import (  # noqa: F401  (chrome is a fixture)
    NB_URL, _QuickAsyncio, _fixture_html, chrome)


def _card(fmt, dur, title):
    """A finished audio card, shaped like the 09-30 run's #757-B dump
    (artifact-library-item > … > mat-icon audio_spark, "Unread", the title).
    ASSUMED: the second line "<m:ss> · <format> · N sources · <ago>" — the
    computer-use readings in this machine's logs quote "1:38 · Brief · 3
    sources" and "53:50 · Deep dive"."""
    return (
        '<artifact-library-item class="has-unseen-dot" data-studio-accent="blue">'
        '<div class="artifact-item-button"><div class="artifact-button-content">'
        '<div class="artifact-primary-content" aria-hidden="true">'
        f'<mat-icon>audio_spark</mat-icon><span>Unread</span><span>{title}</span></div>'
        f'<div class="artifact-secondary">{dur} · {fmt} · 3 sources · 2m ago</div>'
        '</div></div>'
        '<button aria-label="More" aria-haspopup="menu"><mat-icon>more_vert</mat-icon></button>'
        '</artifact-library-item>')


BRIEF = _card("Brief", "1:38", "Golden Retrievers in Brief")
DEEP_8 = _card("Deep dive", "7:55", "Golden Retriever Science Versus Marketing Myths")
DEEP_14 = _card("Deep dive", "14:10", "The Golden Retriever Question")

_LIBRARY = '<div class="artifact-library-ungrouped-items" id="library"></div>'


def _studio(*cards):
    """The notebook with the Customise window closed and these finished cards
    in the Studio list (none: nothing generating, nothing finished)."""
    src = _fixture_html()
    assert src.count(_LIBRARY) == 1, "the fixture's Studio list moved"
    return src.replace(_LIBRARY, _LIBRARY[:-len("</div>")] + "".join(cards) + "</div>")


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
         prefer_existing=False):
    """Run the audio step. Returns (presses on the page, computer-use calls,
    log lines)."""
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
    monkeypatch.setattr(research, "_nlm_open_audio_menu", _menu_not_opened)
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
# The download pick: every length takes the LAST Deep dive card
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("length,cards,want", [
    ("short", (BRIEF, DEEP_8), 2),       # was 1: the Brief card
    ("short", (DEEP_8, BRIEF), 1),       # was 2: the Brief card
    ("short", (DEEP_14, DEEP_8), 2),     # was 1: the first card, "no Brief label found"
    ("default", (DEEP_14, DEEP_8), 2),
    ("long", (DEEP_14, DEEP_8), 2),
    ("long", (BRIEF, DEEP_14), 2),
], ids=["short-brief-then-deep", "short-deep-then-brief", "short-two-deep",
        "default-two-deep", "long-two-deep", "long-brief-then-deep"])
def test_the_download_takes_the_last_deep_dive_card(chrome, monkeypatch, tmp_path,
                                                    length, cards, want):
    """The no-audio retry (prefer_existing_audio): two finished cards are
    already there, so nothing is generated and the picker chooses which one
    computer use downloads. Short follows default and long: the LAST complete
    Deep dive card, never a Brief."""
    presses, cua, lines = _run(chrome, monkeypatch, tmp_path, length, _studio(*cards),
                               go=1, prefer_existing=True)
    assert presses == [], presses
    assert [c.get("current_step") for c in cua] == ["download_audio_overview"], cua
    download = _step(cua, "download_audio_overview")
    assert f"download ONLY entry #{want} counting from the TOP" in download, download
    target = [m for m in lines if m.startswith("[Phase3] Download target:")]
    assert len(target) == 1 and f"ordinal={want}/2" in target[0], lines
    assert f"{length}→last deep-dive card" in target[0], target
