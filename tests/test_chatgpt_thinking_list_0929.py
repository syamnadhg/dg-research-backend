"""ChatGPT's new page: the step list under "Thinking ▾" is open — leave it alone.

⛔⛔ THE DEFECT (runs of 2026-09-29). While ChatGPT thinks, the new page shows a
"Thinking ▾" line with the model's steps listed under it, and the list is
ALREADY OPEN. Phase 1 could not see it — its idea of "open" was a side panel, a
region named "thought"/"activity", or a row of website chips — so it read the
open list as closed and pressed the line, which is a toggle:

    07:40:26 [WARN] [Phase1] DOM clicked but no activity shape verified — miss #1
             (anchor=global label="Searching the web" chips 0->0)
    07:40:58 DOM missed strip 2x — escalating to CUA tier-3 (attempt 1/3, elapsed=63s)
    07:41:56 activity drawer collapsed — will re-open (reopen #1/3)
    07:44:45 escalating to CUA tier-3 (attempt 2/3) ... misses with label="Thinking"
    10:10:18 Claude: I can see that clicking on "Thinking ▾" collapsed the activity
             list (it was previously expanded showing the steps)… I accidentally
             closed what was already open.

About every 30 s the list folded shut and open again in the person's tab, and the
paid vision step was called up to three times a brief to "open" it.

⭐ NOW `_CHATGPT_STEP_LIST_JS` recognises the open list — a line whose label is
drawn twice, and right after it a shown list of short step rows — and Phase 1's
open check accepts it, so the line is never pressed while the list shows. The
vision step's mission no longer promises website chips; it looks for the list
first.

── The page ──────────────────────────────────────────────────────────────────
The owner's capture of ChatGPT's new page (tests/fixtures/chatgpt_0928/
new_page.html) with the Thinking block rebuilt from that day's own panel-miss
snapshot rows (0.1.13's census of the live page), as the audit did
(aud-p1/tests/aud_p1_page.py).

MEASURED (panel-miss snapshots, runs chat_1790692602555_1_20260929T143731 and
T170309; first class token in brackets):
  * the line: SPAN[inline-flex] reading the label TWICE ("Thinking\\nThinking"),
    one copy a SPAN[cadencedShimmerSweep-ICUAVH] — in every capture, whatever
    the label ("Searching the web", "Extracting Credit Map Research Images");
  * the list: DIV[-ms-2]; rows DIV[MarkdownRoot-rZKhxa] (a P of word spans,
    SPAN[FadeIn-RqQvGR]) or DIV[min-w-0] ("Searched 69 websites",
    "Extracted credit map research images");
  * their container DIV[min-w-0] reads "Thinking\\nThinking\\n\\n<first step>…";
  * finished: the line reads "Worked for 7m 23s", once, and the list is gone.
  ⭐ The doubled label with a newline is what Chrome gives for two flex items in
  an `inline-flex` span, which is what the class says — checked in section 0.
ASSUMED (in no capture and no log): which container the block sits in (`place`:
straight in the exchange's column, the one the census agrees with, and the
audit's three guesses), whether step rows carry data-markdown-text-style (`md_attr`),
that a press on the line toggles the list (the vision step saw exactly that
twice), that the list starts open, how a folded list is hidden (`collapsed`:
display none, invisible, or taken off the page), and what sits around the two
copies of the label (`header`, see HEADERS). The census skips any element with
more than two children, so a row holding the copies with an icon and the
chevron the vision step saw ("Thinking ▾") never shows in a capture; each
layout here gives back that day's rows (section 0).

⛔ 2026-09-29 review: the first version found the list only when it came right
after the element holding the copies. With the chevron in between — in a row
around the copies, or inside the inline-flex span — it read the open list as
closed and Phase 1 pressed it as before. An icon placed between the line and
the list (the old `iconBetween`) was dropped: its block has three children, so
the census would have skipped the block row the 07:40:58 capture has.

Nothing leaves the machine: the page is set in headless Chrome, and a Phase 1
run is served from a reserved never-resolving host through a route that answers
every request locally.
"""
import asyncio
import html as _html
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import research
import test_chatgpt_new_page_0928 as base
import test_p1_inline_chips_0819 as _chips
from _domshim import js_constant

chrome = base.chrome
page = base.page
fast = base.fast
logs = base.logs

FIX = Path(__file__).parent / "fixtures" / "chatgpt_0928"
PROMPT = ("Please create a detailed research report brief for a deep research LLM "
          "agent that covers this topic: the St Bernard. Be as thorough as you can.")
HEADING = "Research brief: the St Bernard"

#: The steps of the 10:09:02 capture, in its order: (row kind, text).
ROWS = [
    ["md", "Validated financial claims"],
    ["md", "Refined forensic questions"],
    ["md", "Finalized evidence checks"],
    ["count", "Searched 69 websites"],
    ["plain", "Extracted credit map research images"],
    ["md", "Structured the mandate and planned the report"],
]

SCRIPT = r"""
<style>
.inline-flex { display: inline-flex; } .flex { display: flex; } .flex-col { flex-direction: column; }
[hidden] { display: none !important; }  /* Tailwind's own preflight rule */
@keyframes srSweep { from { background-position: 0 0; } to { background-position: 200px 0; } }
@keyframes srFade { from { opacity: 0; } to { opacity: 1; } }
.cadencedShimmerSweep-ICUAVH { animation: srSweep 2s linear infinite; }
.FadeIn-RqQvGR { animation: srFade .3s ease-out both; }
</style>
<script>
(() => {
  const cfg = JSON.parse(document.body.dataset.srVariant || '{}');
  const ROWS = cfg.rows || [];
  const labels = cfg.labels || ['Thinking'];
  const BTN = 'cursor-interaction size-token-button-composer flex items-center justify-center rounded-ful';
  let mode = 'idle', stash = null, block = null, labelIx = 0, labelTimer = null;
  window.__srToggles = 0;
  const words = (t) => t.split(' ').map((w, i) =>
      (i ? ' ' : '') + (/^[0-9]+$/.test(w) ? '<span>' + w + '</span>'
                                           : '<span class="FadeIn-RqQvGR">' + w + '</span>')).join('');
  function row(kind, t) {
    const d = document.createElement('div');
    if (kind === 'md') {
      d.className = 'MarkdownRoot-rZKhxa [&>*:first-child]:mt-0';
      if (cfg.mdAttr) d.setAttribute('data-markdown-text-style', cfg.mdAttr);
      d.innerHTML = '<p class="Paragraph-kKnbIo" dir="auto">' + words(t) + '</p>';
    } else {
      d.className = 'min-w-0 flex';
      d.innerHTML = '<span>' + words(t) + '</span>';
    }
    return d;
  }
  // The line: the label twice (a shimmer copy and a plain one) — or, for the
  // old page's shape, once. Three layouts, all giving back the census rows the
  // live page gave (section 0):
  //   'pair'  — the element holding the two copies is the line, the list right
  //             after it (the audit's layout);
  //   'row'   — the two copies sit in a row with an icon before them and the
  //             chevron after ("Thinking ▾"; the vision step also saw a globe
  //             icon while searching). The row has three children, which the
  //             census skips, so it never shows in a capture;
  //   'stack' — the chevron is inside the inline-flex span, and the two copies
  //             are stacked in one grid cell (one label on screen, the label
  //             twice in the page's text);
  //   'overlay' — the row again, but the inline-flex span holds ONE wrapper
  //             in which the plain copy lies over the shimmer copy — so the
  //             list is two elements out from the one holding the copies, and
  //             one of them has nothing beside it.
  function header(label) {
    const two = cfg.once ? '' : '<span aria-hidden="true">' + label + '</span>';
    const chevron = '<svg class="chev" width="12" height="12" aria-hidden="true"></svg>';
    const icon = '<span class="icon-slot"><svg width="12" height="12" aria-hidden="true"></svg></span>';
    if (cfg.header === 'row') {
      return '<div class="flex items-center gap-1" data-sr-toggle="1">' + icon
           + '<span class="inline-flex items-center">'
           + '<span class="cadencedShimmerSweep-ICUAVH">' + label + '</span>' + two + '</span>'
           + chevron + '</div>';
    }
    if (cfg.header === 'overlay') {
      return '<div class="flex items-center gap-1" data-sr-toggle="1">' + icon
           + '<span class="inline-flex items-center"><span style="position:relative">'
           + '<span class="cadencedShimmerSweep-ICUAVH">' + label + '</span>'
           + (cfg.once ? '' : '<span aria-hidden="true" style="position:absolute;inset:0">'
                              + label + '</span>')
           + '</span></span>' + chevron + '</div>';
    }
    if (cfg.header === 'stack') {
      return '<span class="inline-flex items-center" data-sr-toggle="1">'
           + '<span style="display:grid">'
           + '<span class="cadencedShimmerSweep-ICUAVH" style="grid-area:1/1">' + label + '</span>'
           + (cfg.once ? '' : '<span aria-hidden="true" style="grid-area:1/1">' + label + '</span>')
           + '</span>' + chevron + '</span>';
    }
    if (cfg.bareCopy) {
      // 09-30: one copy a bare text node, the other the shimmer span.
      return '<span class="inline-flex items-center" data-sr-toggle="1">' + label
           + '<span class="cadencedShimmerSweep-ICUAVH">' + label + '</span></span>';
    }
    return '<span class="inline-flex items-center" data-sr-toggle="1">'
         + '<span class="cadencedShimmerSweep-ICUAVH">' + label + '</span>' + two + '</span>';
  }
  function makeBlock() {
    const b = document.createElement('div');
    b.className = 'min-w-0 flex flex-col';
    b.setAttribute('data-sr-think', '1');
    // The list holds its rows through one inner container: the capture reported
    // DIV[-ms-2] WITH its rows' text, and that census skips an element with more
    // than two children, while each row was the outermost element of its text.
    let list = '<div class="-ms-2 flex flex-col" data-sr-list="1">'
               + '<div class="flex flex-col" data-sr-rows="1"></div></div>';
    // 09-30: the list inside a zero-size `display: contents` box.
    if (cfg.listWrap === 'contents') list = '<div class="contents" style="display:contents">' + list + '</div>';
    b.innerHTML = header(labels[0]) + list;
    const l = b.querySelector('[data-sr-list]');
    for (const [k, t] of ROWS) b.querySelector('[data-sr-rows]').appendChild(row(k, t));
    // Folded: hidden, invisible, or taken off the page altogether.
    if (cfg.collapsed === 'invisible') l.style.visibility = 'hidden';
    else if (cfg.collapsed === 'removed') l.remove();
    else if (cfg.collapsed) l.hidden = true;
    b.addEventListener('click', (e) => {
      if (!e.target.closest('[data-sr-toggle]')) return;
      window.__srPresses = (window.__srPresses || 0) + 1;
      document.body.dataset.srPresses = String(window.__srPresses);
      document.body.dataset.srPressTimes = (document.body.dataset.srPressTimes || '') + Date.now() + ',';
      if (cfg.deadToggle) return;
      if (cfg.collapsed === 'removed') {
        if (l.isConnected) l.remove(); else b.appendChild(l);
      } else {
        l.hidden = !l.hidden;
      }
      window.__srToggles += 1;
      document.body.dataset.srToggles = String(window.__srToggles);
    });
    return b;
  }
  function place(turnCol, replyBlock) {
    if (cfg.place === 'column') {
      if (replyBlock && replyBlock.parentElement === turnCol) turnCol.insertBefore(block, replyBlock);
      else turnCol.appendChild(block);
      return;
    }
    if (cfg.place === 'unit') {
      const unit = replyBlock.querySelector('[data-chatgpt-search-unit-key$=":assistant"]');
      unit.insertBefore(block, unit.querySelector('h4'));
      return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'block-BQZwFn';
    if (cfg.place === 'block-unit') {
      const u = document.createElement('div');
      u.setAttribute('data-chatgpt-search-unit-key', 'fallback-turn-0:1:assistant');
      u.setAttribute('data-content-search-unit-key', 'fallback-turn-0:1:assistant');
      u.appendChild(block);
      wrap.appendChild(u);
    } else {
      wrap.appendChild(block);
    }
    if (replyBlock && replyBlock.parentElement === turnCol) turnCol.insertBefore(wrap, replyBlock);
    else turnCol.appendChild(wrap);
  }
  function setVoice() {
    document.getElementById('sr-action').innerHTML =
      '<button type="button" class="' + BTN + '" aria-label="Start Voice" data-state="closed"><svg></svg></button>';
  }
  // The newest exchange starts thinking: the block is drawn at once, as ChatGPT
  // draws "Thinking" the moment the message is sent.
  const newestCol = () => [...document.querySelectorAll(
      '#sr-transcript div[class="flex flex-col gap-3 browser:gap-1"]')].pop();
  const replyIn = (col) => [...col.children].find(
      c => c.querySelector('[data-chatgpt-search-unit-key$=":assistant"]'));
  function startThinking(turnCol) {
    if (cfg.tall && !document.querySelector('[data-sr-spacer]')) {
      // An earlier, long part of the thread, so the page can be scrolled.
      const sp = document.createElement('div');
      sp.setAttribute('data-sr-spacer', '1');
      sp.style.height = '4000px';
      const tr = document.getElementById('sr-transcript');
      tr.insertBefore(sp, tr.firstChild);
    }
    block = makeBlock();
    mode = 'generating';
    turnCol.appendChild(block);
    if (labels.length > 1) labelTimer = setInterval(() => {
      labelIx = (labelIx + 1) % labels.length;
      const h = block.querySelector('[data-sr-toggle]');
      if (h) h.outerHTML = header(labels[labelIx]);
    }, cfg.labelMs || 1500);
  }
  // The reply's block arrives: its text is held back (or the block is taken out)
  // until the thinking is over, and the Thinking block moves to its place.
  function adoptReply(turnCol, reply) {
    const root = reply.querySelector('[data-markdown-text-style="assistant-message"]');
    stash = { reply: reply, root: root, kids: [...root.childNodes] };
    root.replaceChildren();
    if (cfg.reply === 'absent') { stash.parent = turnCol; place(turnCol, reply); reply.remove(); }
    else place(turnCol, reply);
  }
  window.__srThink = () => {
    const turnCol = newestCol();
    if (!turnCol) return false;
    startThinking(turnCol);
    const reply = replyIn(turnCol);
    if (reply) adoptReply(turnCol, reply);
    return true;
  };
  // Finished: the line reads "Worked for …" once, the list is gone, the reply
  // text is back, no Stop.
  window.__srFinish = () => {
    if (mode !== 'generating') return false;
    mode = 'done';
    document.body.dataset.srFinishedAt = String(Date.now());
    if (labelTimer) clearInterval(labelTimer);
    block.innerHTML = '<span>' + (cfg.doneLabel || 'Worked for 7m 23s') + '</span>';
    if (stash && stash.reply) {
      if (cfg.reply === 'absent') stash.parent.appendChild(stash.reply);
      for (const k of stash.kids) stash.root.appendChild(k);
    }
    // streamMs: the thinking is over but the reply is still being written —
    // the Stop button stays that long.
    if (cfg.streamMs) setTimeout(setVoice, cfg.streamMs); else setVoice();
    return true;
  };
  // Test hooks across worlds (patchright evaluates in an isolated world).
  document.addEventListener('sr-think', () => { document.body.dataset.srThink = String(window.__srThink()); });
  document.addEventListener('sr-finish', () => { document.body.dataset.srFinish = String(window.__srFinish()); });
  document.body.dataset.srToggles = '0';
  document.body.dataset.srPresses = '0';
  // A live send: think as soon as the message is on the page, and hold the
  // reply back when its block arrives.
  const tr = document.getElementById('sr-transcript');
  new MutationObserver(() => {
    if (document.body.dataset.srFixture !== 'chat') return;
    const turnCol = newestCol();
    if (!turnCol) return;
    if (mode === 'idle') {
      startThinking(turnCol);
      if (cfg.finishMs) setTimeout(window.__srFinish, cfg.finishMs);
    }
    if (mode === 'generating' && !stash) {
      const reply = replyIn(turnCol);
      if (reply) adoptReply(turnCol, reply);
    }
  }).observe(tr, { childList: true, subtree: true });
  // The model button as 0.1.13 read it on dg's page.
  const mb = document.getElementById('radix-_r_4k_');
  mb.innerHTML = '<span>Thinking effort</span><span>Pro</span>';
})();
</script>
"""


def thinking_page(*, thread=False, streaming=True, **cfg):
    src = (FIX / "new_page.html").read_text(encoding="utf-8")
    body = '<body data-sr-fixture="chat" data-sr-prompt="">'
    assert src.count(body) == 1, "the fixture's <body> contract changed"
    cfg.setdefault("rows", ROWS)
    attrs = (f'<body data-sr-fixture="{"thread" if thread else "chat"}" '
             f'data-sr-prompt="{_html.escape(PROMPT, quote=True)}"'
             + (' data-streaming="1"' if streaming else "")
             + f" data-sr-variant='{_html.escape(json.dumps(cfg), quote=True)}'>")
    src = src.replace(body, attrs)
    assert src.count("</body>") == 1
    return src.replace("</body>", SCRIPT + "</body>")


def _thinking(chrome, page, **cfg):
    """A thread whose newest exchange is mid-thought, the list as `cfg` says."""
    chrome.run(page.set_content(thinking_page(thread=True, **cfg)))
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-think'))"))
    assert chrome.run(page.evaluate("() => document.body.dataset.srThink")) == "true"


def _state(chrome, page):
    return chrome.run(research._chatgpt_activity_state(page))


def _list_shown(chrome, page):
    return chrome.run(page.evaluate(
        "() => { const l = document.querySelector('[data-sr-list]');"
        " return !!l && !l.hidden; }"))


#: Where the block sits. "column" (straight in the exchange's column, before the
#: reply) is the one placement the census agrees with: it reported the block as
#: the OUTERMOST element of its text, so no wrapper holding only the block sits
#: around it — which rules out the audit's three, kept here as the other guesses.
PLACES = ["column", "unit", "block-unit", "block-plain"]

#: What sits around the two copies of the label (see `header` in SCRIPT):
#: "pair" — nothing, the list right after them; "row" — an icon before and the
#: chevron after, in a row of three; "stack" — the chevron inside the inline-flex
#: span, the copies stacked in a grid cell; "overlay" — the row, with the copies
#: overlaid in a lone wrapper inside the inline-flex span.
HEADERS = ["pair", "row", "stack", "overlay"]


# ═══ 0. The rebuilt block IS the captured one ═════════════════════════════════

#: Two of that day's captures, as the census recorded them: the label, the steps
#: on screen, and rows it reported (text cut at 60 characters, tag, first class).
CAPTURES = {
    "07:40:58": ("Searching the web", [["md", "Crafted a refined research brief and prompt"]], [
        ("Searching the web\nSearching the web\n\nCrafted a refined resea", "DIV", "min-w-0"),
        ("Searching the web\nSearching the web", "SPAN", "inline-flex"),
        ("Searching the web", "SPAN", "cadencedShimmerSweep-ICUAVH"),
        ("Crafted a refined research brief and prompt", "DIV", "-ms-2"),
    ]),
    "10:06:27": ("Extracting Credit Map Research Images", ROWS[:4], [
        ("Extracting Credit Map Research Images\nExtracting Credit Map ", "SPAN", "inline-flex"),
        ("Extracting Credit Map Research Images", "SPAN", "cadencedShimmerSweep-ICUAVH"),
        ("Validated financial claims\n\nRefined forensic questions\n\nFina", "DIV", "-ms-2"),
        ("Validated financial claims", "DIV", "MarkdownRoot-rZKhxa"),
        ("Refined forensic questions", "DIV", "MarkdownRoot-rZKhxa"),
        ("Finalized evidence checks", "DIV", "MarkdownRoot-rZKhxa"),
        ("Searched 69 websites", "DIV", "min-w-0"),
    ]),
}


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("when", sorted(CAPTURES))
def test_the_rebuilt_block_reads_like_the_captured_one(chrome, page, logs, when, header):
    """The fixture, through the program's own panel-miss census, gives back the
    rows the live page gave that day — in every layout of the line, none of
    them inside anything the census calls interactive (`inter`: false, as
    captured)."""
    label, rows, want = CAPTURES[when]
    _thinking(chrome, page, place="column", labels=[label], rows=rows, header=header)
    got = chrome.run(page.evaluate(js_constant(research._log_chatgpt_thread_snapshot, "JS")))["rows"]
    for w in want:
        assert w in [(r["t"], r["tag"], r["cl"]) for r in got], (w, got)
    line = [r for r in got if r["cl"] == "inline-flex"]
    assert len(line) == 1 and line[0]["inter"] is False, line


# ═══ 1. Open is open; folded, finished and the old shape are not ══════════════

@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("md_attr", ["", "assistant-message"])
@pytest.mark.parametrize("place", PLACES)
def test_the_open_step_list_reads_as_open(chrome, page, logs, place, md_attr, header):
    """⭐⭐ THE FIX, where the audit measured it read as closed in all six
    variants — and, since the 09-29 review, with the chevron between the copies
    and the list ("row", "stack", "overlay"), where the first version still read
    it as closed."""
    _thinking(chrome, page, place=place, mdAttr=md_attr, header=header)
    assert _list_shown(chrome, page)
    st = _state(chrome, page)
    assert research._chatgpt_p1_activity_open(st) is True, st
    assert research._chatgpt_open_shape(st) == "steps"
    assert st["inline_step_rows"] == len(ROWS)


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("how", [True, "invisible", "removed"])
@pytest.mark.parametrize("place", PLACES)
def test_a_folded_list_reads_as_closed(chrome, page, logs, place, how, header):
    """⛔ Folded, whatever the fold does. Taken off the page ("removed"), the
    line is alone in its block and the look for the list carries on past the
    block — where, with the block inside the reply's unit, the next thing is
    the reply's own "ChatGPT said:" heading. That is never the list."""
    _thinking(chrome, page, place=place, collapsed=how, header=header)
    assert research._chatgpt_p1_activity_open(_state(chrome, page)) is False


def test_the_finished_line_reads_as_closed(chrome, page, logs):
    _thinking(chrome, page, place="column")
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-finish'))"))
    assert research._chatgpt_p1_activity_open(_state(chrome, page)) is False


@pytest.mark.parametrize("header", HEADERS)
def test_a_line_drawn_once_is_not_this_list(chrome, page, logs, header):
    """⛔ The doubled label is what keeps this off the OLD page: its status line
    is drawn once, and rows under it are not the new page's list — reading them
    as open would stop Phase 1 ever opening the old page's chip row."""
    _thinking(chrome, page, place="column", once=True, header=header)
    assert research._chatgpt_p1_activity_open(_state(chrome, page)) is False


# ── pages that are not this list at all ─────────────────────────────────────

PANELS = Path(__file__).parent / "fixtures" / "panels"
_OTHER_PAGES = (
    [(f"{layout}_page{'_thread' if thread else ''}", lambda layout=layout, thread=thread:
      base._html_for(layout, thread=thread))
     for layout in ("new", "old") for thread in (False, True)]
    + [(p.name, lambda p=p: p.read_text(encoding="utf-8"))
       for p in sorted(PANELS.glob("chatgpt_*.html"))]
    + [("chips_searching", lambda: _chips._page(_chips._turn("Searching the web", chips=True))),
       ("chips_none", lambda: _chips._page(_chips._turn("Mapped security coverage"))),
       ("chips_done", lambda: _chips._page(_chips._turn("Searched 20 websites", chips=True,
                                                         shimmer=False)))])


@pytest.mark.parametrize("name,build", _OTHER_PAGES, ids=[n for n, _b in _OTHER_PAGES])
def test_the_captured_pages_and_the_older_shapes_are_not_this_list(chrome, page, logs,
                                                                   name, build):
    """The owner's captures of the new and old pages (a chat and a thread), the
    08-06 panel captures and the 08-19 chip-row pages: none holds this list, and
    the look for it — which now moves out from the line — finds none."""
    chrome.run(page.set_content(build()))
    assert chrome.run(page.evaluate(research._CHATGPT_STEP_LIST_JS))["open"] is False


# ── what may LOOK like the line and a list, and is not ──────────────────────

DOUBLED = ('<span class="inline-flex"><span>Findings</span><span>Findings</span></span>'
           '<div><div>First point</div><div>Second point</div></div>')


def _static(chrome, page, body):
    chrome.run(page.set_content(
        "<style>.inline-flex{display:inline-flex}</style><main>" + body + "</main>"))
    return research._chatgpt_p1_activity_open(_state(chrome, page))


def test_the_bare_shape_reads_as_open(chrome, page, logs):
    """The control for the three below: the same markup, loose in the page."""
    assert _static(chrome, page, f"<div>{DOUBLED}</div>") is True


def test_the_shape_inside_the_reply_is_not_the_list(chrome, page, logs):
    assert _static(chrome, page, '<div data-markdown-text-style="assistant-message">'
                   f"<div>{DOUBLED}</div></div>") is False


def test_the_shape_inside_the_persons_message_is_not_the_list(chrome, page, logs):
    assert _static(chrome, page, f'<div data-user-message-bubble="true"><div>{DOUBLED}</div>'
                   "</div>") is False


def test_the_shape_inside_the_message_box_is_not_the_list(chrome, page, logs):
    assert _static(chrome, page, f"<form><div>{DOUBLED}</div></form>") is False


def test_the_container_of_a_folded_line_is_not_the_line(chrome, page, logs):
    """⛔ Folded, the block's own text is the label twice too — and what comes
    after the BLOCK is the reply. Only the element holding the two copies is
    the line."""
    assert _static(chrome, page, '<div><div><span class="inline-flex"><span>Thinking</span>'
                   '<span>Thinking</span></span><div hidden>Validated financial claims</div>'
                   '</div><div><p>Scope: the breed</p></div></div>') is False


LONE = '<div><span class="inline-flex"><span>Thinking</span><span>Thinking</span></span></div>'


def test_the_reply_after_a_lone_line_is_not_its_list(chrome, page, logs):
    """⛔ A folded list taken off the page leaves the line alone in its block,
    and the look carries on past the block. When what it meets there is the
    reply — its "ChatGPT said:" heading and its words — that is not the list."""
    assert _static(chrome, page, f'<div>{LONE}<div><h4 class="sr-only" data-conversation-role='
                   '"assistant">ChatGPT said:</h4><div>Scope: the breed</div></div></div>') is False


def test_the_look_for_the_list_never_leaves_the_conversation(chrome, page, logs):
    """A line that is all the conversation holds: the words after the
    conversation (the page's own footer) are not its list."""
    chrome.run(page.set_content("<style>.inline-flex{display:inline-flex}</style>"
                                f"<main>{LONE}</main>"
                                "<div>ChatGPT can make mistakes. Check important info.</div>"))
    assert research._chatgpt_p1_activity_open(_state(chrome, page)) is False


@pytest.mark.parametrize("header", HEADERS)
@pytest.mark.parametrize("place", ["column", "block-plain"])
def test_a_folded_line_at_the_end_of_the_exchange_is_not_open(chrome, page, logs, place,
                                                              header):
    """⛔ The list taken off the page and no reply yet — which is what that
    day's snapshots show while ChatGPT thinks (no "ChatGPT said:" anywhere).
    The look moves out only through what holds no other words, so it stops at
    the exchange (it holds the person's message) and never reaches the message
    box below."""
    _thinking(chrome, page, place=place, reply="absent", collapsed="removed", header=header)
    assert research._chatgpt_p1_activity_open(_state(chrome, page)) is False


# ═══ 2. Phase 1, executed: the line is never pressed while the list shows ═════

FAKE_URL = "http://sr-fixture.invalid/c/68da1b2c-w13"


def _load_at_url(chrome, page, **cfg):
    """Served from a reserved never-resolving host through a route that answers
    EVERY request locally (nothing leaves the machine), so the page has an http
    address like ChatGPT's."""
    html = thinking_page(**cfg)

    async def _serve(route):
        if route.request.url == FAKE_URL:
            await route.fulfill(status=200, content_type="text/html", body=html)
        else:
            await route.abort()

    async def _go():
        await page.route("**/*", _serve)
        await page.goto(FAKE_URL)
        await page.add_style_tag(content=(
            "form { position: fixed; left: 140px; right: 140px; bottom: 16px; "
            "background: #fff; }"))

    chrome.run(_go())


class _Cua:
    """The vision client. It answers every mission "panel: open" without
    touching the page, and keeps each mission's instruction and when it came."""

    def __init__(self):
        self.missions = []
        self.at = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, *, system, messages, **kw):
        if len(messages) == 1:
            first = messages[0]["content"]
            self.missions.append(next((c["text"] for c in first
                                       if isinstance(c, dict) and c.get("type") == "text"), ""))
            self.at.append(time.time() * 1000)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="panel: open")])


@pytest.fixture
def p1run(chrome, page, fast, logs, monkeypatch):
    async def _nothing(*_a, **_k):
        return None

    async def _yes(*_a, **_k):
        return True

    real_wait_sent = research._chatgpt_wait_prompt_sent

    def _wait_sent(p, prompt, timeout_s=10.0):
        return real_wait_sent(p, prompt, timeout_s=min(timeout_s, 1.0))

    monkeypatch.setattr(research, "_work_tab_signed_out", _nothing)
    monkeypatch.setattr(research, "check_hv_gate", _yes)
    monkeypatch.setattr(research, "_chatgpt_wait_prompt_sent", _wait_sent)
    rt, ctl = research._runtime, research._controls
    monkeypatch.setattr(rt, "register_page", lambda *a, **k: None)
    monkeypatch.setattr(rt, "unregister_page", lambda *a, **k: None)
    monkeypatch.setattr(rt, "phase", rt.phase)
    monkeypatch.setattr(rt, "sub_state", rt.sub_state)
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)
    monkeypatch.setattr(ctl, "peek_extra_context", lambda: "")
    monkeypatch.setattr(ctl, "pop_extra_context", lambda: "")
    monkeypatch.setattr(ctl, "consume_phase_skip", lambda *a, **k: False)
    if research._vision is not None:
        monkeypatch.setattr(research._vision, "is_vision_enabled", lambda: "off")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    browser = research.Browser.__new__(research.Browser)
    browser.page = page

    async def _navigate(url):
        pass                              # ⛔ never leaves the fixture page

    async def _switch(p):
        browser.page = p

    browser.navigate = _navigate
    browser.switch_to_page = _switch

    def run(**cfg):
        _load_at_url(chrome, page, **cfg)
        cua = _Cua()
        out = chrome.run(asyncio.wait_for(
            research.run_phase1(browser, cua, "the St Bernard", []), timeout=240))
        body = chrome.run(page.evaluate("() => ({t: document.body.dataset.srToggles,"
                                        " p: document.body.dataset.srPresses,"
                                        " f: document.body.dataset.srFinishedAt})"))
        text = (out or {}).get("text", "") if isinstance(out, dict) else ""
        finished = float(body["f"] or "inf")
        return SimpleNamespace(text=text, toggles=int(body["t"] or 0),
                               presses=int(body["p"] or 0), cua=cua,
                               while_thinking=[m for m, at in zip(cua.missions, cua.at)
                                               if at < finished],
                               lines=[m for _lv, m in logs])

    return run


@pytest.mark.parametrize("place,reply,header", [
    ("column", "empty", "pair"), ("column", "absent", "pair"), ("unit", "empty", "pair"),
    ("block-unit", "empty", "pair"), ("block-plain", "absent", "pair"),
    # ⛔ 09-29 review: the chevron between the copies and the list — the first
    # version pressed the line 49-50 times in these nine seconds, as before.
    ("column", "empty", "row"), ("column", "empty", "stack"), ("unit", "empty", "overlay")])
def test_phase1_never_presses_the_line_while_the_list_shows(p1run, place, reply, header):
    """⭐⭐ THE OWNER'S SYMPTOM, executed: the real Phase 1 (submit, poll, open
    check, opener, vision escalation, extraction) on the thinking page. Before
    the fix the audit counted 50 presses in nine seconds and three vision calls;
    now the line is left alone and, while ChatGPT thinks, the vision step is
    never asked. (Once it has finished the list is gone and Phase 1 may still
    try to open the finished line — that is not this defect, and it presses
    nothing here.)"""
    out = p1run(place=place, reply=reply, finishMs=9000, header=header,
                labels=["Searching the web", "Thinking", "Searching liquidcompute.com"])
    assert HEADING in out.text, out.text[:200]
    assert out.presses == 0 and out.toggles == 0, (out.presses, out.toggles)
    assert out.while_thinking == [], out.while_thinking
    assert any("activity already open (shape=steps, 6 step lines showing)" in m
               for m in out.lines), [m for m in out.lines if "activity" in m][:10]


@pytest.mark.parametrize("header,how", [("pair", True), ("pair", "removed"), ("row", True)])
def test_a_folded_list_on_the_new_page_is_left_alone(p1run, header, how):
    """⛔ 2026-09-30 (was: "opened once and then left alone"). On the new page
    Phase 1 never presses the line: its list shows by default, the 09-30 run
    pressed it shut and open six times while this reader was blind to it, and
    the owner's fix is that the line is not pressed at all. A list the person
    folded stays folded, and no vision step is spent on it."""
    out = p1run(place="column", reply="empty", finishMs=9000, collapsed=how, header=header)
    assert HEADING in out.text
    assert out.presses == 0 and out.toggles == 0, (out.presses, out.toggles)
    assert any("shows by default on this page" in m for m in out.lines)
    assert out.while_thinking == []


def test_the_vision_step_is_told_to_look_for_the_list_first(p1run):
    """When the press does nothing and the vision step is asked, its mission
    names the new page's list and says to leave an open one alone — not "expect
    a row of website chips", which is what it pressed the list shut for."""
    # The line drawn once (the older shape): on the new page, whose line reads
    # its label twice, the vision step is never asked (2026-09-30).
    out = p1run(place="column", reply="empty", finishMs=15000, collapsed=True, deadToggle=True,
                once=True)
    assert out.while_thinking, [m for m in out.lines if "tier-3" in m][:5]
    mission = out.while_thinking[0]
    assert "list of the model's steps" in mission
    assert "'Thinking ▾'" in mission
    assert "LOOK FIRST" in mission
    assert "Expected result: a row of small website chips" not in mission


def test_the_listed_steps_reach_the_live_activity_feed(p1run, monkeypatch):
    """⛔ Wave 13: the rows under "Thinking ▾" are the model's own steps, but
    they are written in the past tense ("Validated financial claims", "Searched
    69 websites"), so the walker's verb gate passed none of them and the app's
    live activity feed showed only the status word. Now, while ChatGPT thinks,
    Phase 1's progress events carry every row, in the page's order."""
    events = []
    monkeypatch.setattr(research, "emit_event", lambda name, **k: events.append((name, k)))
    out = p1run(place="column", reply="empty", finishMs=9000, header="pair")
    assert HEADING in out.text
    fed = [k.get("steps") or [] for name, k in events
           if name == "agent_progress" and k.get("phase") == 1]
    rows = [t for _kind, t in ROWS]
    assert any([s for s in steps if s in rows] == rows for steps in fed), (
        [steps for steps in fed if steps][-3:])
