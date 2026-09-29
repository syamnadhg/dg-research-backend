"""Claude's usage limit is named on the card, with when it resets (2026-09-16).

⛔⛔ THE DEFECT. The owner's Claude account had hit its weekly usage limit. The
page said so, and the vision step read it out loud (both runs that day):

    11:54:14  Claude: I can see a "Need more usage?" dialog blocking the screen ...
    11:54:20  - **"Usage limit reached · Resets Sep 20 at 1:00 AM"** ...
              - "You've hit your limit for Claude messages. Limits will reset
                Sep 20 at 1:00 AM."
    11:56:08  Claude: ... a "Usage limit reached" banner visible on the page ...
    11:58:53  [ERROR] [2B] Claude setup failed

and the person got "Claude didn't start — Retry or Skip". Retry could not have
worked; nobody answered; Claude was skipped ten minutes later and the report
came out without it, with nothing saying why.

⭐ NOW the Claude launch reads Claude's page on every check while it waits for
Claude to start. A limit it sees becomes the card — "Claude's usage limit is
reached — it resets Sep 20 at 1:00 AM", telling the person Retry won't help
before then — and the second, fresh-tab try (which cannot get past a limit
either) is not made.

── How it is measured ──────────────────────────────────────────────────────
The REAL `run_phase2` Claude launch (2B) runs against a local page in headless
Chrome: the real wait, the real `verify_claude_generating`, the real failure
branch with its human-check and sign-in probes, the real `fail_agent`. Only the
tab opener (`start_agent_no_gemini_wait`, which would open claude.ai) is a
stand-in that hands back the local page, and the round-robin after the launch
is stopped. The card is read off the event the app receives.

⚠ ASSUMED, NOT CAPTURED: claude.ai's markup for the limit. No capture of the
page exists; the WORDS below are the ones the vision step quoted from it on
09-16 (the banner, the note at the bottom, the "Need more usage?" dialog and
its "Wait until Sunday" button), laid out as plain elements. Whether the dialog
itself names a reset time is not known — it is built without one.
"""
import asyncio
from types import SimpleNamespace

import pytest

import research

BANNER = "Usage limit reached · Resets Sep 20 at 1:00 AM"
TOAST = "You've hit your limit for Claude messages. Limits will reset Sep 20 at 1:00 AM."
PROMPT = "Please research this brief in depth and write a full report."

CSS = """<style>
 body{margin:0;font-family:sans-serif;display:flex}
 nav{width:260px} main{flex:1;padding:24px}
 .composer{border:1px solid #ccc;padding:12px;margin-top:24px}
</style>"""


def claude_page(*, banner="inline", toast=False, dialog=False, prompt=PROMPT,
                chat_title="St Bernard breed history"):
    if banner == "inline":
        b = ('<div data-sr-limit="1"><span>Usage limit reached</span> · '
             '<span>Resets Sep 20 at 1:00 AM</span></div>')
    elif banner == "stacked":
        b = ('<div data-sr-limit="1"><div>Usage limit reached</div>'
             '<div>Resets Sep 20 at 1:00 AM</div></div>')
    else:
        b = ""
    t = f'<div role="status" data-sr-limit="1">{TOAST}</div>' if toast else ""
    d = ('<div role="dialog" data-sr-limit="1"><h2>Need more usage?</h2>'
         "<p>You've reached your weekly limit for Claude messages.</p>"
         '<button>Wait until Sunday</button><button>Get more usage</button></div>'
         if dialog else "")
    return (CSS + "<nav><a href='#'>New chat</a><div>Recents</div>"
            f"<a href='#'>{chat_title}</a></nav>"
            "<main><h1>How can I help you today?</h1>"
            '<div class="composer"><div contenteditable="true" class="ProseMirror">'
            f"<p>{prompt}</p></div><div>brief.md</div>"
            '<button aria-label="Send message" disabled>Send</button></div>'
            f"{b}{t}{d}</main>")


class _FastAsyncio:
    """research's `asyncio` with every sleep capped — the launch waits 3 s per
    check and a 30 s stagger; the local page answers at once."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(delay=0, *a, **k):
        await asyncio.sleep(0)


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
        return pw, b, await b.new_context(viewport={"width": 1280, "height": 900})

    try:
        pw, b, ctx = loop.run_until_complete(_start())
    except Exception as e:                                    # pragma: no cover
        loop.close()
        pytest.skip(f"system Chrome unavailable: {e}")
    yield SimpleNamespace(run=loop.run_until_complete, ctx=ctx)
    loop.run_until_complete(b.close())
    loop.run_until_complete(pw.stop())
    loop.close()


class _Stop(Exception):
    """The launch is over; the round-robin after it is not under test."""


@pytest.fixture
def launch(chrome, monkeypatch, tmp_path):
    events, lines, opened = [], [], []
    monkeypatch.setattr(research, "log", lambda m, level="INFO": lines.append((level, str(m))))
    monkeypatch.setattr(research, "emit_event",
                        lambda name, **k: events.append((name, k)))
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "_p2_run_dir", lambda: tmp_path)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")
    # Card bookkeeping this test must not leak into the next.
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_TS", {})
    monkeypatch.setattr(research, "_pending_decisions", {})
    monkeypatch.setattr(research, "_active_decisions", set())
    monkeypatch.setattr(research, "_active_decision_agents", {})
    ctl = research._controls
    monkeypatch.setattr(ctl, "skipped_agents", set())
    monkeypatch.setattr(ctl, "auto_skip_reasons", {})
    monkeypatch.setattr(ctl, "cookie_trust_broken", set())
    monkeypatch.setattr(ctl, "hv_blocked", {})
    monkeypatch.setattr(ctl, "hv_auto_skipped", set())
    monkeypatch.setattr(ctl, "is_stop", lambda: False)

    async def _no_poll(*a, **k):
        raise _Stop()

    monkeypatch.setattr(research, "poll_all_agents_round_robin", _no_poll)

    def run(html, *, setup_ok=True, after_open=None):
        async def _open(browser, cua_client, url, *a, **k):
            opened.append(url)
            page = await chrome.ctx.new_page()
            await page.set_content(html)
            if after_open:
                await after_open(page)
            return page, setup_ok

        monkeypatch.setattr(research, "start_agent_no_gemini_wait", _open)

        class _Browser:
            page = None

            async def switch_to_page(self, p):
                self.page = p

        try:
            chrome.run(asyncio.wait_for(research.run_phase2(
                _Browser(), None, "brief " * 40, enabled_agents=["claude"]), timeout=120))
        except _Stop:
            pass
        cards = [k for name, k in events
                 if name == "pipeline_error" and k.get("agent") == "claude"]
        return SimpleNamespace(cards=cards, lines=lines, opened=opened)

    return run


def _one_card(out):
    assert len(out.cards) == 1, [c.get("error") for c in out.cards]
    return out.cards[0]


# ═══ the card ════════════════════════════════════════════════════════════════

def test_the_card_names_claudes_usage_limit_and_when_it_resets(launch):
    """⭐⭐ THE FIX, on the 09-16 page: banner + the note at the bottom."""
    out = launch(claude_page(toast=True))
    card = _one_card(out)
    assert card["error"] == "Claude's usage limit is reached — it resets Sep 20 at 1:00 AM"
    assert "resets Sep 20 at 1:00 AM" in card["details"]
    assert "Retry won't work before then" in card["details"]
    # The web shows this title as it is; one it filed as a passing hiccup would
    # lose the card its Skip button.
    assert not research._web_swallows_title(card["error"])
    said = [m for _lv, m in out.lines if "Claude's page shows its usage limit" in m]
    assert len(said) == 1 and BANNER in said[0], said  # once, quoting the page's own line


def test_a_fresh_tab_is_not_tried_once_the_limit_is_seen(launch):
    """The second, fresh-tab try cannot get past a usage limit either."""
    out = launch(claude_page())
    assert len(out.opened) == 1, out.opened
    assert not any("Retrying Claude (fresh tab)" in m for _lv, m in out.lines)


def test_the_limit_seen_while_waiting_is_kept_when_the_page_goes_blank(launch, monkeypatch):
    """⛔ The second 09-16 run: the banner was on screen while the launch waited,
    and by the time it gave up the page showed an empty chat ("no error
    message"). What the page said while waiting is what the card says."""
    real = research.verify_claude_generating
    calls = {"n": 0}

    async def _verify(p):
        calls["n"] += 1
        if calls["n"] == 2:
            await p.evaluate("() => document.querySelectorAll('[data-sr-limit]')"
                             ".forEach(e => e.remove())")
        return await real(p)

    monkeypatch.setattr(research, "verify_claude_generating", _verify)
    out = launch(claude_page())
    card = _one_card(out)
    assert card["error"] == "Claude's usage limit is reached — it resets Sep 20 at 1:00 AM"


def test_a_launch_that_failed_before_the_wait_still_reads_the_page(launch):
    """The setup itself gave up (no wait ran): the failure branch reads the page."""
    out = launch(claude_page(), setup_ok=False)
    assert _one_card(out)["error"] == ("Claude's usage limit is reached — "
                                       "it resets Sep 20 at 1:00 AM")


def test_the_reset_time_on_the_next_line_is_found(launch):
    out = launch(claude_page(banner="stacked"))
    assert _one_card(out)["error"] == ("Claude's usage limit is reached — "
                                       "it resets Sep 20 at 1:00 AM")


def test_the_dialog_alone_names_the_limit_without_a_date(launch):
    """"Need more usage?" with no reset time: the limit is named, no date is made up."""
    out = launch(claude_page(banner="none", dialog=True))
    card = _one_card(out)
    assert card["error"] == "Claude's usage limit is reached"
    assert "until the limit resets" in card["details"]


# ═══ what is NOT a limit ══════════════════════════════════════════════════════

def test_no_limit_on_the_page_keeps_the_generic_card_and_the_second_try(launch):
    out = launch(claude_page(banner="none"))
    assert _one_card(out)["error"] == "Claude didn't start"
    assert len(out.opened) == 2


def test_the_words_in_the_message_box_or_a_chat_title_are_not_a_limit(launch):
    """The brief the program typed and a chat in the sidebar can both SAY
    "usage limit reached"; neither is Claude's limit."""
    out = launch(claude_page(banner="none", prompt=f"Research this: {BANNER}",
                             chat_title=BANNER))
    assert _one_card(out)["error"] == "Claude didn't start"
    assert len(out.opened) == 2


# ═══ the reader, on the page's words ══════════════════════════════════════════

@pytest.mark.parametrize("text,resets", [
    (BANNER, "Sep 20 at 1:00 AM"),
    (TOAST, "Sep 20 at 1:00 AM"),
    # ⚠ assumed: a sentence after the reset time is not part of it
    (TOAST + " Upgrade to keep chatting.", "Sep 20 at 1:00 AM"),
    ("Weekly limit reached · Resets Mon 9:00 AM", "Mon 9:00 AM"),
    ("Need more usage?\nYou've reached your weekly limit.\nWait until Sunday", ""),
    ("Usage limit reached\nResets soon", ""),
])
def test_the_reader_takes_the_reset_time_in_the_pages_own_words(text, resets):
    got = research._claude_usage_limit(text)
    assert got is not None and got["resets"] == resets


@pytest.mark.parametrize("text", [
    "Approaching usage limit · resets at 4:00 PM",
    "How can I help you today?",
    "",
])
def test_the_reader_sees_no_limit_where_none_is_reached(text):
    assert research._claude_usage_limit(text) is None
