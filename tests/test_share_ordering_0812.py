"""Two share links from one run: one shipped dead, one was never reachable.

WHAT HAPPENED (2026-08-12 e2e)

CLAUDE — the link was produced, copied, and then thrown away in favour of a
mangled transcription of itself. What shipped was

    https://claude.ai/public/artifacts/4e899beb…`

a real artifact id with a markdown backtick welded onto the end. The vision
model had written the URL inside a code span in its answer; the extractor
matched that prose with `[^\\s]+`, which runs to the next whitespace rather than
to the end of a URL, and took the backtick with it. The CORRECT link was already
on the clipboard — the model had clicked Copy and said so.

The order was the whole bug. Both readings were present and the less reliable
one won because it was tried first. Prose is a TRANSCRIPTION of the link; the
clipboard IS the link.

⭐ And it happened in the PRIMARY path, not the fallback. `publish_open_claude_
artifact` carries the same prose-first ordering, and its caller accepts whatever
it returns if the string merely contains "claude." — so a mangled URL from there
never gets the chance to fall through to the twin that would have re-read the
clipboard. That copy also gated its clipboard read on `'claude.site' in c`, a
host literal Publish moved off in 2026-08, so it would have REJECTED the live
link even while holding it.

CHATGPT — the Share button was underneath a full-page document. Markdown
extraction runs first, and its tier-1 vision mission's first instruction is
"open the canvas": it enlarges the document to reach the download control and
nothing puts it back. The share extractor's close-first preamble was written
2026-04-26, before that extractor existed — it closes `[role="dialog"]` and the
citations panel, and a canvas is neither. The DOM click found nothing and the
vision fallback spent six iterations pressing icons in the canvas header.

WHAT THESE TESTS PIN

  1. The clipboard is read BEFORE the prose, in both Claude publish paths.
  2. A backticked URL in prose no longer wins over a clean clipboard.
  3. Prose is still the fallback — deleting it is not the fix.
  4. The clipboard shape test asks the one URL authority, not a host literal.
  5. An open canvas is closed before the share step, by a Playwright press.
  6. ⛔ Nothing that is not a canvas gets closed, and a canvas that will not
     close does not abort the share attempt.

⛔ NOT DOING, and deliberately: no URL trimming, no validation, no tests about
public-link shape. `_is_public_share_url` is already the single authority on
whether a link is public, and a second cleanup step here would be a second
place for the two to disagree.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js, stamp_panel_geometry  # noqa: E402

# What shipped, verbatim shape: a good URL with a code-span backtick attached.
MANGLED = "https://claude.ai/public/artifacts/4e899beb-1c4d-4f0e-9a77-2b1f6a0c33d1`"
CLEAN = "https://claude.ai/public/artifacts/4e899beb-1c4d-4f0e-9a77-2b1f6a0c33d1"
PROSE = f"I clicked Publish and copied the link. It is `{CLEAN}` — link copied."


# ══════════════════════════════════════════════════════════════════════════
# 1. the URL authority still answers as it did (context for the rest)
# ══════════════════════════════════════════════════════════════════════════

def test_nothing_downstream_catches_the_mangled_url():
    """⭐ WHY THE ORDER IS THE FIX AND VALIDATION IS NOT.

    The mangled URL PASSES the public-share gate: the host matches and the path
    still starts with the share prefix, so a trailing backtick changes nothing
    the gate looks at. It shipped verified=True and into the report, and 404s
    for whoever opens it.

    So no amount of checking downstream would have caught this. The fix is to
    stop preferring a transcription of the link over the link."""
    assert research._is_public_share_url("claude", CLEAN) is True
    assert research._is_public_share_url("claude", MANGLED) is True
    assert MANGLED != CLEAN


# ══════════════════════════════════════════════════════════════════════════
# 2. the primary publish path — clipboard before prose
# ══════════════════════════════════════════════════════════════════════════

class _NoArtifactPage:
    """A Claude tab with no artifact panel mounted.

    Every DOM tier in `publish_open_claude_artifact` comes up empty against it,
    so the function reaches its vision leg the way production does rather than
    by having the leg lifted out and run on its own."""

    def __init__(self):
        self.url = "https://claude.ai/chat/abc"
        self.main_frame = self
        self.frames = [self]

    def is_closed(self):
        return False

    async def wait_for_selector(self, sel, timeout=None):
        raise TimeoutError("no publish button mounted")

    async def evaluate(self, js, arg=None):
        return ""


class _Browser:
    """Needs to accept `_claude_publish_cua_used`, which the function sets."""


def _run_publish(monkeypatch, *, prose, clipboard):
    """Call the REAL `publish_open_claude_artifact`, with the vision answer and
    the clipboard scripted. Returns (url, [accept-predicates it used])."""
    reads = []

    async def _shadow(page, **kw):
        return {"status": "done", "text": prose}
    monkeypatch.setattr(research, "_shadow_observed_cua", _shadow)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_arm_clipboard", lambda: None)

    async def _sleep(*a, **k):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _sleep)

    async def _read_clip(accept=None, **kw):
        reads.append(accept)
        if clipboard and (accept is None or accept(clipboard)):
            return clipboard, clipboard
        return "", clipboard or ""
    monkeypatch.setattr(research, "_read_clipboard_after_copy", _read_clip)

    url = asyncio.run(research.publish_open_claude_artifact(
        _NoArtifactPage(), _Browser(), cua_client=object()))
    return url, reads


def test_the_primary_path_prefers_the_clipboard_over_its_own_prose(monkeypatch):
    """⭐ THE FIX. Prose carries the backtick; the clipboard does not."""
    url, _reads = _run_publish(monkeypatch, prose=PROSE, clipboard=CLEAN)
    assert url == CLEAN
    assert not url.endswith("`")


def test_the_primary_path_still_falls_back_to_prose(monkeypatch):
    """Deleting the prose read is not the fix — a mission that reports the URL
    without copying it is still a success worth keeping."""
    url, _reads = _run_publish(
        monkeypatch, prose=f"The published URL is {CLEAN}", clipboard="")
    assert url == CLEAN


def test_the_primary_path_asks_the_url_authority_not_a_host_literal(monkeypatch):
    """`'claude.site' in c` was not a safety check, it was rot: Publish has
    produced claude.ai/public/artifacts/… since 2026-08, so that predicate
    would have rejected the live link while holding it."""
    _url, reads = _run_publish(monkeypatch, prose=PROSE, clipboard=CLEAN)
    assert reads, "the clipboard was never read"
    accept = reads[0]
    assert accept(CLEAN) is True, "the live Publish URL is rejected by the shape test"
    assert accept("https://claude.site/artifacts/abc123") is True
    assert accept("https://claude.ai/chat/6fde90e7") is False


# ══════════════════════════════════════════════════════════════════════════
# 3. the fallback publish path — same ordering
# ══════════════════════════════════════════════════════════════════════════

def test_both_claude_publish_paths_read_the_clipboard_first():
    """The twin in `extract_share_link_claude`. Two copies of one decision is
    the defect this file's own incident report is about, so the ordering is
    asserted in both rather than in whichever one was noticed."""
    import inspect
    from conftest import code_only
    for fn in (research.publish_open_claude_artifact,
               research.extract_share_link_claude):
        src = code_only(inspect.getsource(fn))
        clip = src.index("_read_clipboard_after_copy(")
        prose = src.index("re.search(r'https://claude")
        assert clip < prose, (
            f"{fn.__name__} reads its own prose before the clipboard — that is "
            f"the 2026-08-12 dead link"
        )


# ══════════════════════════════════════════════════════════════════════════
# 4. the ChatGPT canvas
# ══════════════════════════════════════════════════════════════════════════

def _canvas_dom(*, label="Close canvas", w=1200, h=800):
    return stamp_panel_geometry(
        el("body", kids=[
            el("main", kids=[
                el("div", attrs={"data-testid": "canvas-panel"}, kids=[
                    el("button", attrs={"aria-label": label}),
                    el("div", text="the finished report"),
                ]),
            ]),
        ]),
        w=w, h=h, x=0, y=0, kid_w=w, kid_h=h)


def test_the_probe_sees_an_open_canvas():
    spec = _canvas_dom()
    assert run_js(spec, research._CANVAS_PROBE_JS,
                  list(research._CANVAS_ROOT_SELECTORS))["ret"] is True


def test_the_probe_ignores_a_small_node_that_merely_says_canvas():
    """⛔ A response container can carry "canvas" in a class name. The size
    floor is what makes this specific to the full-page document view — without
    it the share step would start pressing close buttons inside the answer."""
    spec = stamp_panel_geometry(
        el("body", kids=[el("div", attrs={"class": "canvas-hint"})]),
        w=40, h=20, x=0, y=0, kid_w=10, kid_h=10)
    assert run_js(spec, research._CANVAS_PROBE_JS,
                  list(research._CANVAS_ROOT_SELECTORS))["ret"] is False


@pytest.mark.parametrize("label", [
    "Close canvas", "Collapse", "Exit full screen", "Back to chat", "Minimize",
])
def test_the_close_control_is_marked_for_playwright_to_press(label):
    """JS MARKS, Playwright presses. A synthetic `el.click()` from
    `page.evaluate` does not close a React overlay — measured 6/6 no-effect on
    this codebase's own panels — so marking is the whole job here."""
    spec = _canvas_dom(label=label)
    out = run_js(spec, research._CANVAS_MARK_CLOSE_JS,
                 [list(research._CANVAS_ROOT_SELECTORS), research._CANVAS_CLOSE_MARK])
    assert out["ret"], f"no close control found for {label!r}"
    assert not out["clicks"], "the marker clicked something — it must only mark"


def test_an_unrelated_button_in_the_canvas_is_not_marked():
    """Download and Share live in the same header strip. Pressing either
    instead of the close control is how the vision fallback burned six
    iterations in the first place."""
    spec = _canvas_dom(label="Download")
    out = run_js(spec, research._CANVAS_MARK_CLOSE_JS,
                 [list(research._CANVAS_ROOT_SELECTORS), research._CANVAS_CLOSE_MARK])
    assert out["ret"] == ""


class _CanvasPage:
    """A page whose canvas closes when the right thing is pressed."""

    def __init__(self, *, open_=True, closes_on_click=True, closes_on_escape=True,
                 has_close_button=True):
        self.open = open_
        self.closes_on_click = closes_on_click
        self.closes_on_escape = closes_on_escape
        self.has_close_button = has_close_button
        self.clicked = 0
        self.escapes = 0
        self.keyboard = self._Keyboard(self)

    class _Keyboard:
        def __init__(self, page):
            self.page = page

        async def press(self, key):
            if key == "Escape":
                self.page.escapes += 1
                if self.page.closes_on_escape:
                    self.page.open = False

    async def evaluate(self, js, arg=None):
        if js == research._CANVAS_PROBE_JS:
            return self.open
        if js == research._CANVAS_MARK_CLOSE_JS:
            return "[data-testid*=\"canvas\"]" if self.has_close_button else ""
        return None

    async def query_selector(self, sel):
        if research._CANVAS_CLOSE_MARK in sel and self.has_close_button:
            return self._Button(self)
        return None

    class _Button:
        def __init__(self, page):
            self.page = page

        async def click(self, timeout=None):
            self.page.clicked += 1
            if self.page.closes_on_click:
                self.page.open = False


def _no_sleep(monkeypatch):
    async def _s(*a, **k):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _s)


def test_an_open_canvas_is_closed_by_its_own_control(monkeypatch):
    _no_sleep(monkeypatch)
    page = _CanvasPage()
    assert asyncio.run(research._close_chatgpt_canvas(page)).startswith("close control")
    assert page.clicked == 1
    assert page.escapes == 0, "escape was pressed even though the control worked"


def test_escape_is_the_fallback_when_the_control_does_not_work(monkeypatch):
    _no_sleep(monkeypatch)
    page = _CanvasPage(closes_on_click=False)
    assert asyncio.run(research._close_chatgpt_canvas(page)) == "escape"
    assert page.clicked == 1
    assert page.escapes == 1


def test_escape_is_used_when_there_is_no_close_control_at_all(monkeypatch):
    _no_sleep(monkeypatch)
    page = _CanvasPage(has_close_button=False)
    assert asyncio.run(research._close_chatgpt_canvas(page)) == "escape"
    assert page.escapes == 1


def test_nothing_is_pressed_when_no_canvas_is_open(monkeypatch):
    """⛔ The share step runs on every ChatGPT extraction, most of which have no
    canvas. Pressing Escape on a normal chat would close whatever the user did
    have open — and on the P1 path it would fire on every single run."""
    _no_sleep(monkeypatch)
    page = _CanvasPage(open_=False)
    assert asyncio.run(research._close_chatgpt_canvas(page)) == ""
    assert page.clicked == 0
    assert page.escapes == 0


def test_a_canvas_that_will_not_close_reports_failure_rather_than_raising(monkeypatch):
    """Best-effort by construction. A stuck canvas is not a reason to skip the
    share attempt — the Playwright click that follows has its own 3-second
    fast-fail for exactly that case."""
    _no_sleep(monkeypatch)
    page = _CanvasPage(closes_on_click=False, closes_on_escape=False)
    assert asyncio.run(research._close_chatgpt_canvas(page)) == ""


def test_a_page_that_throws_is_not_a_reason_to_stop(monkeypatch):
    _no_sleep(monkeypatch)

    class _Dead(_CanvasPage):
        async def evaluate(self, js, arg=None):
            raise RuntimeError("target closed")

    assert asyncio.run(research._close_chatgpt_canvas(_Dead())) == ""


def test_the_share_extractor_closes_the_canvas_before_looking_for_share():
    """Order is the whole point: closing it after the Share lookup would be a
    no-op, since the lookup is what the canvas was covering."""
    import inspect
    from conftest import code_only
    src = code_only(inspect.getsource(research.extract_share_link_chatgpt))
    close = src.index("_close_chatgpt_canvas(")
    lookup = src.index('button[aria-label="Share"]')
    assert close < lookup, "the canvas is closed after the Share button is sought"
