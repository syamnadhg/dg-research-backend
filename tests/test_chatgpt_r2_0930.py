"""ChatGPT, round 2 of the 09-30 run's fixes (1 of 2) — every page here is built
from the owner's own recordings of chatgpt.com (tests/fixtures/chatgpt_0930/,
copied from #Dev/wave12/fix14/captures with account and conversation ids blanked),
through `_capture_page`, and every reader is run in headless Chrome.

  1. Phase 1's step list (4-chatgpt-p1-thinking.json): the 09-29 reader was
     pinned on a rebuild of a page that did not exist and read the real, open
     list as closed on every poll. Now it reads the recorded markup: open while
     the list is on the page, its steps in order, its label once.
  2. The Deep research row inside the menu the "+" opened
     (3-chatgpt-dr-toppage.json, the press at 3885 ms) — never a suggestion chip
     or a sidebar link — and the Phase 2 Pro check after it.

Deep research as an app (done, census, download, sources): test_chatgpt_dr_app_0930.py.
Nothing leaves the machine: pages are set with `set_content`.
"""
import json
from pathlib import Path

import pytest

import research
import _capture_page as cp
import test_chatgpt_new_page_0928 as base

chrome = base.chrome
page = base.page
fast = base.fast
logs = base.logs

FIX0928 = Path(__file__).parent / "fixtures" / "chatgpt_0928"
P1 = cp.load("4-chatgpt-p1-thinking.json")
DR = cp.load("3-chatgpt-dr-toppage.json")


# ═══ 1. Phase 1's step list, on the recorded markup ═══════════════════════════

def _turn_page(capture, index):
    """The recorded latest exchange of frame `index`, inside <main>."""
    fr = capture["frames"][index]
    return cp.page_html("<main>" + "".join(cp.node_html(n) for n in fr["lastTurn"]) + "</main>")


def _probe(chrome, page, index, js):
    chrome.run(page.set_content(_turn_page(P1, index)))
    return chrome.run(page.evaluate(js))


#: Frames of the recording in which the list is on the page under the line
#: (the recorder's "after-click" and "dom" moments), with what it shows.
OPEN = {
    8: ("Thinking", []),                                      # a thought, no step yet
    17: ("Searching the web", ["Planning research scope", "Searched 37 websites",
                               "Read PDF research instructions"]),
    30: ("Thinking", ["Planned research scope", "Searched 37 websites",
                      "Read PDF research instructions", "Refined insurance evidence",
                      "Built budget scenarios"]),
    71: ("Worked for 7m 59s", ["Planned research scope", "Searched 37 websites",
                               "Read PDF research instructions", "Refined insurance evidence"]),
}
#: Frames in which a press took the list off the page (thinking and finished).
FOLDED = [13, 20, 59, 60, 67, 68]
#: Frames whose label is long (a summary of the thinking), drawn ONCE.
LONG = [43, 53]


@pytest.mark.parametrize("index", sorted(OPEN))
def test_the_recorded_open_list_reads_open_with_its_steps(chrome, page, index):
    """⭐⭐ THE DEFECT: on these very frames the 09-29 reader said "closed"."""
    label, first_steps = OPEN[index]
    sl = _probe(chrome, page, index, research._CHATGPT_STEP_LIST_JS)
    assert sl["open"] is True, sl
    assert sl["label"] == label, sl
    assert sl["steps"][:len(first_steps)] == first_steps, sl["steps"]
    assert sl["rows"] == len(sl["steps"]) or sl["rows"] > 15


def test_the_finished_list_carries_its_last_steps(chrome, page):
    sl = _probe(chrome, page, 71, research._CHATGPT_STEP_LIST_JS)
    # 18 steps on the page: the feed takes the first 15, and never a thought.
    assert sl["rows"] == 18 and len(sl["steps"]) == 15, sl
    assert sl["thoughts"] == 2
    assert all(len(s) <= 220 for s in sl["steps"])


@pytest.mark.parametrize("index", LONG)
def test_a_long_label_drawn_once_still_reads_its_open_list(chrome, page, index):
    sl = _probe(chrome, page, index, research._CHATGPT_STEP_LIST_JS)
    assert sl["open"] is True and sl["rows"] >= 10, sl
    assert "\n" not in sl["label"] and len(sl["label"]) > 40


@pytest.mark.parametrize("index", FOLDED)
def test_a_recorded_folded_list_reads_closed(chrome, page, index):
    sl = _probe(chrome, page, index, research._CHATGPT_STEP_LIST_JS)
    assert sl["open"] is False and sl["line"] is True, sl


def test_a_list_on_the_page_but_hidden_reads_closed(chrome, page):
    """⚠ The recording folds the list by taking it off the page. A list kept on
    the page but hidden (another way a fold could be drawn) is not open either."""
    chrome.run(page.set_content(_turn_page(P1, 30)))
    chrome.run(page.evaluate("""() => {
        const b = document.querySelector('button[aria-expanded][aria-labelledby]');
        b.parentElement.nextElementSibling.style.display = 'none';
    }"""))
    sl = chrome.run(page.evaluate(research._CHATGPT_STEP_LIST_JS))
    assert sl["open"] is False and sl["line"] is True, sl


@pytest.mark.parametrize("index", sorted(OPEN) + FOLDED + LONG)
def test_the_new_pages_line_is_read_whatever_its_label(chrome, page, index):
    """Phase 1 never presses the line (round 1's rule). Round 1 knew the line
    only by a label drawn twice; a long label and "Worked for …" are drawn
    once, and while they showed the line was not known."""
    line = _probe(chrome, page, index, research._CHATGPT_DOUBLED_LINE_JS)
    assert line and "\n" not in line, repr(line)
    if index in OPEN:
        assert line == OPEN[index][0]


def test_the_status_line_is_read_once(chrome, page):
    """The inline walker's status line: "Thinking", not "Thinking\\nThinking"."""
    il = _probe(chrome, page, 8, research._CHATGPT_INLINE_ACTIVITY_JS)
    assert il["status_line"] == "Thinking", il["status_line"]


@pytest.mark.parametrize("host", ["reply", "message"])
def test_a_control_in_the_reply_or_the_message_is_not_the_line(chrome, page, host):
    """The recorded thinking block (frame 30) moved into a reply's text, or into
    the person's message: neither is the line."""
    chrome.run(page.set_content(_turn_page(P1, 30)))
    assert chrome.run(page.evaluate("""(host) => {
        const b = document.querySelector('button[aria-expanded][aria-labelledby]');
        const block = b.parentElement.parentElement.parentElement;
        let h = document.querySelector('[data-user-message-bubble="true"]');
        if (host === 'reply') {
            h = document.createElement('div');
            h.setAttribute('data-markdown-text-style', 'assistant-message');
            block.parentElement.appendChild(h);
        }
        h.appendChild(block);
        return document.querySelectorAll('button[aria-expanded][aria-labelledby]').length === 1;
    }""", host))
    assert chrome.run(page.evaluate(research._CHATGPT_STEP_LIST_JS))["line"] is False
    assert chrome.run(page.evaluate(research._CHATGPT_DOUBLED_LINE_JS)) == ""


# ═══ 2. The Deep research row, inside the menu the "+" opened ═════════════════

#: The menu's rows, as the 09-30 run's own dump read them (title and subtitle
#: joined by textContent). The row's attributes and its container are the
#: recording's (3885 ms); that its siblings carry the same is ASSUMED.
MENU_ROWS = [("Add photos & files", "Upload from computer"),
             ("Add Space files", "Browse and search your files"),
             ("Create image", "Visualize anything"),
             ("Work in a project", "Start a chat in a project"),
             ("Web search", "Find real-time news and info"),
             ("Sketch", "Draw and attach an image"),
             ("Deep research", "Get a detailed report"),
             ("Presentations", "Create and edit presentations")]


def _clicked_chain(capture, ms):
    return next(f for f in capture["frames"] if f["ms"] == ms)["clicked"]


def _menu_script(rows=True):
    chain = _clicked_chain(DR, 3885)            # BUTTON, DIV, scroll area, DIV, shell, fixed, BODY
    row_a, wrap_a, scroll_a, col_a, shell_a, fixed_a = [c["a"] for c in chain[:6]]
    esc = lambda d: json.dumps(d)                                    # noqa: E731
    return """<script>
(() => {
  const ROWS = %s;
  const rowA = %s, wrapA = %s, scrollA = %s, colA = %s, shellA = %s, fixedA = %s;
  const set = (el, a) => { for (const [k, v] of Object.entries(a)) el.setAttribute(k, v); return el; };
  const press = (what) => {
    const p = JSON.parse(document.body.dataset.srPressed || '[]');
    p.push(what); document.body.dataset.srPressed = JSON.stringify(p);
  };
  // Decoys: a suggestion-strip chip and a sidebar conversation, both saying it.
  const strip = document.createElement('section');
  strip.className = 'group/home-suggestions relative flex min-w-0';
  strip.innerHTML = '<button type="button" class="cursor-interaction outline-none">Search the web</button>'
      + '<button type="button" class="cursor-interaction outline-none" data-sr-decoy="chip">Deep research</button>';
  document.querySelector('main').prepend(strip);
  const nav = document.createElement('nav');
  nav.innerHTML = '<a href="#c-deep-research" data-sr-decoy="sidebar">Deep research request</a>';
  document.body.prepend(nav);
  document.addEventListener('click', (e) => {
    const d = e.target.closest('[data-sr-decoy]');
    if (d) { e.preventDefault(); press('decoy:' + d.getAttribute('data-sr-decoy')); }
  }, true);
  const plus = document.querySelector('button[data-composer-navigation-target="add-context"]');
  let portal = null;
  plus.addEventListener('click', () => {
    press('plus');
    if (portal) return;
    plus.setAttribute('aria-expanded', 'true'); plus.setAttribute('data-state', 'open');
    portal = set(document.createElement('div'), fixedA);
    portal.style.cssText = 'position:fixed;left:40px;top:120px;width:320px;z-index:50';
    const shell = set(document.createElement('div'), shellA);
    const col = set(document.createElement('div'), colA);
    const scroll = set(document.createElement('div'), scrollA);
    const wrap = set(document.createElement('div'), wrapA);
    for (const [title, sub] of ROWS) {
      const b = set(document.createElement('button'), rowA);
      b.removeAttribute('aria-current');
      b.innerHTML = '<span>' + title + '</span><span>' + sub + '</span>';
      b.addEventListener('click', () => {
        press('row:' + title);
        portal.remove(); portal = null;
        plus.setAttribute('aria-expanded', 'false'); plus.setAttribute('data-state', 'closed');
        if (title === 'Deep research') {
          const pill = document.createElement('span');
          pill.textContent = 'Deep research';
          document.querySelector('form').appendChild(pill);
        }
      });
      wrap.appendChild(b);
    }
    scroll.appendChild(wrap); col.appendChild(scroll); shell.appendChild(col); portal.appendChild(shell);
    document.body.appendChild(portal);
  });
})();
</script>""" % (esc(MENU_ROWS if rows else []), esc(row_a), esc(wrap_a), esc(scroll_a),
                 esc(col_a), esc(shell_a), esc(fixed_a))


def _menu_page(rows=True):
    src = (FIX0928 / "new_page.html").read_text(encoding="utf-8")
    assert src.count("</body>") == 1
    return src.replace("</body>", _menu_script(rows) + "</body>")


def test_the_menu_fixture_is_the_recorded_press():
    """The row and every container up to <body> carry the recording's attributes."""
    chain = _clicked_chain(DR, 3885)
    assert chain[0]["tag"] == "BUTTON" and chain[0]["label"] == "Deep research Get a detailed report"
    assert chain[0]["a"]["data-list-navigation-item"] == "true"
    assert chain[4]["a"]["data-composer-overlay-floating-ui"] == "true"
    assert "data-mention-list-scroll-area" in chain[2]["a"]
    assert chain[5]["a"]["class"] == "z-50 flex flex-col fixed" and chain[6]["tag"] == "BODY"
    plus = _clicked_chain(DR, 2276)[0]["a"]
    assert plus["data-composer-navigation-target"] == "add-context"
    assert plus["aria-label"] == "Add files and more"


def _setup(chrome, page, monkeypatch, *, rows=True):
    tiers = []

    async def _tier(p, label="", phase=0):
        tiers.append(phase)
        return "already"

    monkeypatch.setattr(research, "_chatgpt_select_effort_tier", _tier)
    chrome.run(page.set_content(_menu_page(rows)))
    ok = chrome.run(research.setup_chatgpt_dr(page, allow_model_pick=True))
    pressed = json.loads(chrome.run(page.evaluate("() => document.body.dataset.srPressed || '[]'")))
    return ok, pressed, tiers


def test_the_deep_research_row_in_the_menu_is_pressed_and_the_pro_check_runs(
        chrome, page, fast, logs, monkeypatch):
    """⭐⭐ 09-30: 'no deep research row among 0 menu rows' → computer use, and the
    Pro check never ran. Now the row inside the "+" menu is pressed by the page
    read, and the Pro check runs after it."""
    ok, pressed, tiers = _setup(chrome, page, monkeypatch)
    assert ok is True, logs[-12:]
    assert pressed == ["plus", "row:Deep research"], pressed
    assert tiers == [2], "the Phase 2 Pro check did not run"
    assert any("Step 2 pressed 'Deep researchGet a detailed report' (via composer-overlay"
               in m for _lv, m in logs), [m for _lv, m in logs if "Step 2" in m]


def test_an_empty_menu_presses_no_chip_and_no_sidebar_link(chrome, page, fast, logs, monkeypatch):
    """⛔ With no row in the menu the step misses — and neither the strip's
    'Deep research' chip nor the sidebar's 'Deep research request' is pressed."""
    ok, pressed, tiers = _setup(chrome, page, monkeypatch, rows=False)
    assert ok is False
    assert pressed == ["plus"], pressed
    assert tiers == []
