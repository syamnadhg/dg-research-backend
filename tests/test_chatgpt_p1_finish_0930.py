"""Phase 1 on ChatGPT's new page finishes the moment ChatGPT does (09-30 run).

⛔⛔ THE RUN (chat_1790769799998_1_20260930T120329, P1 lines 31-89). The brief
finished at about 05:07:16 and was read at 05:08:31:

    05:04:24 .. 05:07:13  DOM clicked but no activity shape verified — miss #1..#4
                          (six presses of the new page's "Searching the web ▾"
                          line, every one folding or unfolding the step list in
                          the owner's tab; the snapshots after two of them show
                          the list OPEN)
    05:05:02              activity panel opened via CUA tier-3 ("This list of
                          steps is **already showing**")
    05:05:33              activity drawer collapsed — will re-open (reopen #1/3)
                          (a read that had never seen the list open overruled
                          the vision step's sighting)
    05:07:44              "Worked for 3m 25s" on screen, no Stop — panel DOM
                          miss #5; the DOM says not generating, wait 5 s
    05:07:49              miss #6 → CUA tier-3 attempt 2/3 on the FINISHED
                          brief: 35 s, three scrolls "up" executed as "down"
    05:08:24              "the page itself shows 'worked for 3m'" → 3 s → done

and every 30 s poll scrolled the page to the bottom first.

⭐ NOW, in Phase 1 (each section below fails on 2eddcf8):
  1. while the page may be finished (the DOM's last read said "not generating")
     nothing presses the activity line and no vision step is called for it;
  2. the finish — no Stop button and "Worked for …" in the latest exchange — is
     looked for once a second, and one steady re-read a second later replaces
     the 5 s + 3 s double-check;
  3. the new page's line (its label drawn twice) is never pressed: its step
     list shows by default, so it is latched open and no vision step is spent;
  4. a vision step's "already open" is not overruled by a read that has never
     seen that shape open;
  5. the poll no longer scrolls the page to the bottom.

── The page ──────────────────────────────────────────────────────────────────
The owner's capture of the new page (tests/fixtures/chatgpt_0928/new_page.html)
with the thinking block rebuilt as test_chatgpt_thinking_list_0929 does — the
same page, its SCRIPT, its `p1run` (the real `run_phase1`: submit, verify,
poll, extraction) and its vision stub, which answers "panel: open" to every
mission without touching the page.

MEASURED (09-30 snapshots): the line reads its label twice ("Searching the web
\\nSearching the web", SPAN[inline-flex]), inside the exchange; the finished
row DIV[min-w-0] "Worked for 3m 25s", inside the exchange, above "ChatGPT
said:"; the composer's Stop is `button[aria-label="Stop"]` (09-28 capture).
NOT CAPTURED (round 2 captures it): why the 09-29 step-list reader reads the
live, open list as closed. Section 3 builds the two shapes the census rows
allow that make it blind — the list inside a zero-size `display: contents`
box, and one copy of the label a bare text node — and checks both give back
that day's rows. The fix does not depend on either: it reads the doubled label.

Nothing leaves the machine: pages are set in headless Chrome, and Phase 1 is
served from a reserved never-resolving host through a route that answers every
request locally.
"""
import asyncio
import time
import pytest

import research
import test_chatgpt_thinking_list_0929 as tl
from _domshim import js_constant

chrome = tl.chrome
page = tl.page
fast = tl.fast
logs = tl.logs
p1run = tl.p1run

HEADING = tl.HEADING
OPEN_MISSION = "Open the research activity"
LABELS = ["Searching the web", "Thinking", "Searching liquidcompute.com"]


def _times(csv):
    return [float(t) for t in (csv or "").split(",") if t]


def _finished_at(chrome, page):
    return float(chrome.run(page.evaluate("() => document.body.dataset.srFinishedAt")) or "inf")


# ═══ 1. A finished-looking page gets no press and no vision step ═════════════

def test_no_press_and_no_vision_step_once_the_dom_says_not_generating(p1run, chrome, page,
                                                                      monkeypatch):
    """⭐ THE 05:07:49 ESCALATION. The line is the old page's (drawn once) and
    every press misses, so the vision step is due at the second miss. The reply
    finishes right after the first — as 09-30's did between miss #5 and #6 —
    and its header here is not a time, so only the DOM's "not generating" says
    it may be finished. Before: the 5 s re-poll pressed again, missed a second
    time and sent the vision step to open the activity of a finished answer.
    Now nothing is pressed and nothing is asked after the finish."""
    real_open = research._open_chatgpt_activity_panel
    opened_at = []

    async def _open(pg, *a, **k):
        res = await real_open(pg, *a, **k)
        opened_at.append(time.time() * 1000)
        if len(opened_at) == 1:
            await pg.evaluate("() => document.dispatchEvent(new CustomEvent('sr-finish'))")
        return res

    monkeypatch.setattr(research, "_open_chatgpt_activity_panel", _open)
    out = p1run(place="column", reply="empty", header="pair", once=True, deadToggle=True,
                doneLabel="Answer ready", finishMs=20000)
    assert HEADING in out.text, out.text[:200]
    fin = _finished_at(chrome, page)
    assert opened_at and opened_at[0] < fin + 50, opened_at        # the setup happened
    after = [t for t in opened_at[1:] if t >= fin]
    assert after == [], f"the line was pressed {len(after)} time(s) after the reply finished"
    late = [m[:60] for m, at in zip(out.cua.missions, out.cua.at)
            if at >= fin and OPEN_MISSION in m]
    assert late == [], f"the vision step was sent to open the activity after the finish: {late}"


# ═══ 2. The brief is read within about a second of the finish ═══════════════

@pytest.fixture
def still(monkeypatch):
    """No Stop, Pause or Skip from the app, and no vision or narration keys —
    what `p1run` sets, for a test that drives the poll by itself."""
    ctl = research._controls
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)
    monkeypatch.setattr(ctl, "consume_phase_skip", lambda *a, **k: False)
    if research._vision is not None:
        monkeypatch.setattr(research._vision, "is_vision_enabled", lambda: "off")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_the_brief_is_read_within_seconds_of_the_finish(chrome, page, logs, still):
    """⭐⭐ THE OWNER'S "NOT SEAMLESS". The real `poll_until_done`, real sleeps,
    a 10 s poll, the reply finishing 1.5 s in. Before: the finish was seen at
    the next poll (10 s) and then waited 5 s + 3 s more — about 17 s. Now the
    wait between polls looks for it once a second and one steady re-read ends
    the poll: about 2 s."""
    # At an http address, like ChatGPT's (a page at about:blank is a dead tab).
    tl._load_at_url(chrome, page, thread=True, place="column", header="pair")
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-think'))"))
    assert chrome.run(page.evaluate("() => document.body.dataset.srThink")) == "true"
    assert chrome.run(page.evaluate(
        "() => !!document.querySelector('button[aria-label=\"Stop\"]')")), "no Stop while thinking"
    chrome.run(page.evaluate(
        "() => { setTimeout(() => document.dispatchEvent(new CustomEvent('sr-finish')), 1500); }"))
    done = chrome.run(asyncio.wait_for(research.poll_until_done(
        page, getattr(research, "verify_chatgpt_p1_generating",       # the base had one check
                      research.verify_chatgpt_generating), "Phase1", 10, 60, phase=1), timeout=60))
    returned = time.time() * 1000
    assert done is True
    fin = _finished_at(chrome, page)
    assert fin != float("inf"), "the page never finished"
    lag = returned - fin
    assert lag < 3000, f"the brief was read {lag / 1000:.1f} s after ChatGPT finished"


def _poll_on_thinking_page(chrome, page, after_finish_js, *, timeout=60):
    """The real poll on the thinking page (at an http address), the reply
    finishing at once and `after_finish_js` run right after. Returns (the poll's
    answer or "still polling", when it returned in ms)."""
    tl._load_at_url(chrome, page, thread=True, place="column", header="pair")
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-think'))"))
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-finish'))"))
    chrome.run(page.evaluate(after_finish_js))
    try:
        done = chrome.run(asyncio.wait_for(research.poll_until_done(
            page, research.verify_chatgpt_p1_generating, "Phase1", 10, 60, phase=1),
            timeout=timeout))
    except asyncio.TimeoutError:
        done = "still polling"
    return done, time.time() * 1000


def test_a_reply_still_being_written_is_not_read_yet(chrome, page, logs, still):
    """⛔ The steady re-read is a re-READ: with the Stop gone and the header up
    but the reply still growing, the brief is not taken half-written."""
    done, at = _poll_on_thinking_page(chrome, page, """() => {
        const reply = document.querySelector('[data-markdown-text-style="assistant-message"]');
        let n = 0;
        const t = setInterval(() => {
            const p = document.createElement('p');
            p.textContent = 'A further paragraph of the brief, number ' + (++n) + '.';
            reply.appendChild(p);
            if (n >= 12) { clearInterval(t); document.body.dataset.srGrowEnd = String(Date.now()); }
        }, 250);
    }""")
    assert done is True
    grown = float(chrome.run(page.evaluate("() => document.body.dataset.srGrowEnd")) or "inf")
    assert at >= grown, f"read {(grown - at) / 1000:.1f} s before the reply stopped growing"


def test_the_pages_own_working_check_can_still_say_not_yet(chrome, page, logs, still,
                                                         monkeypatch):
    """⛔ Both signs up, but the page's own "still working?" check sees work
    running (a live animation, its long-standing sign): the finish waits — and
    while it does, the page looks finished, so the activity line is left alone."""
    opened = []

    async def _open(pg, *a, **k):
        opened.append(1)
        return {"found": False}

    monkeypatch.setattr(research, "_open_chatgpt_activity_panel", _open)
    done, _at = _poll_on_thinking_page(chrome, page, """() => {
        const s = document.createElement('span');
        s.className = 'animate-pulse';
        s.style.cssText = 'display:inline-block;width:12px;height:12px;'
                        + 'animation: srSweep 1s linear infinite';
        document.getElementById('sr-transcript').appendChild(s);
    }""", timeout=6)
    assert done == "still polling"
    assert opened == [], f"the activity line was looked for {len(opened)} time(s)"


def test_the_finish_is_read_in_the_latest_exchange_only(chrome, page, logs):
    """The header of an earlier exchange never answers for this one, and a
    brief that writes "worked for 5 hours" in its own text is not the header."""
    tl._thinking(chrome, page, place="column", header="pair")
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-finish'))"))
    got = chrome.run(research._chatgpt_p1_finish_signs(page))
    assert got["done"] is True and got["header"].lower().startswith("worked for 7m"), got
    # The same row, moved into the reply's text: prose, not the header.
    chrome.run(page.evaluate("""() => {
        const row = [...document.querySelectorAll('[data-sr-think] span')]
            .find(s => /Worked for/.test(s.textContent));
        const reply = document.querySelector('[data-markdown-text-style="assistant-message"]');
        reply.appendChild(row);
    }"""))
    assert chrome.run(research._chatgpt_p1_finish_signs(page))["done"] is False
    # …nor when that is ALL the reply says (the boxes around a short reply read
    # exactly like it).
    chrome.run(page.evaluate("""() => {
        const reply = document.querySelector('[data-markdown-text-style="assistant-message"]');
        reply.replaceChildren(document.createTextNode('We worked for 5 hours on it.'));
    }"""))
    assert chrome.run(research._chatgpt_p1_finish_signs(page))["done"] is False
    # …and with a newer exchange below it, still thinking: not this one's.
    chrome.run(page.set_content(tl.thinking_page(thread=True, place="column", header="pair")))
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-think'))"))
    chrome.run(page.evaluate("() => document.dispatchEvent(new CustomEvent('sr-finish'))"))
    chrome.run(page.evaluate("""() => {
        const tr = document.getElementById('sr-transcript');
        const t = document.getElementById('sr-turn').content.cloneNode(true);
        tr.appendChild(t);
        document.querySelector('#sr-action button').setAttribute('aria-label', 'Start Voice');
    }"""))
    assert chrome.run(research._chatgpt_p1_finish_signs(page))["done"] is False


# ═══ 3. The new page's line is never pressed ═════════════════════════════════

#: The two shapes the census rows allow in which the 09-29 step-list reader
#: cannot see the open list (see the module note).
BLIND = [{"listWrap": "contents"}, {"bareCopy": True}]
BLIND_IDS = ["list-in-contents-box", "one-copy-bare-text"]


@pytest.mark.parametrize("shape", BLIND, ids=BLIND_IDS)
def test_the_blind_shapes_give_back_the_captured_rows(chrome, page, logs, shape):
    """Each shape, through the program's own panel-miss census, gives back the
    rows the 07:40:58 capture gave — and the 09-29 reader reads the list, which
    is on screen, as closed: the live symptom."""
    label, rows, want = tl.CAPTURES["07:40:58"]
    tl._thinking(chrome, page, place="column", labels=[label], rows=rows, header="pair", **shape)
    got = chrome.run(page.evaluate(js_constant(research._log_chatgpt_thread_snapshot, "JS")))["rows"]
    for w in want:
        assert w in [(r["t"], r["tag"], r["cl"]) for r in got], (w, got)
    assert tl._list_shown(chrome, page)
    assert chrome.run(page.evaluate(research._CHATGPT_STEP_LIST_JS))["open"] is False
    assert chrome.run(research._chatgpt_doubled_line(page)) == label


@pytest.mark.parametrize("shape", BLIND, ids=BLIND_IDS)
def test_phase1_never_presses_the_new_pages_line(p1run, shape):
    """⭐⭐ THE FLAPPING. The real Phase 1 on the new page, with the step list
    showing and the reader blind to it, as on 09-30. Before: pressed on every
    poll, folding the list shut and open, and the vision step called at the
    second miss. Now: no press, no vision step while ChatGPT thinks."""
    out = p1run(place="column", reply="empty", finishMs=9000, header="pair", labels=LABELS,
                **shape)
    assert HEADING in out.text, out.text[:200]
    assert out.presses == 0 and out.toggles == 0, (out.presses, out.toggles)
    assert out.while_thinking == [], out.while_thinking
    assert any("shows by default on this page" in m for m in out.lines), (
        [m for m in out.lines if "activity" in m or "step list" in m][:10])


def test_the_new_pages_line_is_left_alone_after_it_reads_worked_for(p1run, chrome, page,
                                                                    monkeypatch):
    """The thinking is over ("Worked for 7m 23s", the list gone) and the reply
    is still being written, Stop showing. On the new page the line is never
    pressed — not while it thinks, and not once it reads "Worked for …" either.
    Before: the list's going read as "collapsed" and the opener went looking
    for the line again."""
    real_open = research._open_chatgpt_activity_panel
    opened = []

    async def _open(pg, *a, **k):
        opened.append(time.time() * 1000)
        return await real_open(pg, *a, **k)

    monkeypatch.setattr(research, "_open_chatgpt_activity_panel", _open)
    out = p1run(place="column", reply="empty", finishMs=5000, streamMs=4000, header="pair")
    assert HEADING in out.text, out.text[:200]
    assert any("activity already open (shape=steps" in m for m in out.lines)
    assert opened == [], f"the opener went looking for the line {len(opened)} time(s)"
    assert out.presses == 0 and out.cua.missions == [], (out.presses, out.cua.missions)


def test_a_line_drawn_once_is_not_the_new_pages_line(chrome, page, logs):
    """⛔ The old page draws its line once: that one is still opened."""
    tl._thinking(chrome, page, place="column", header="pair", once=True)
    assert chrome.run(research._chatgpt_doubled_line(page)) == ""


@pytest.mark.parametrize("where", ["reply", "user"])
def test_a_doubled_label_in_the_reply_or_the_message_is_not_the_line(chrome, page, logs, where):
    tl._thinking(chrome, page, place="column", header="pair", once=True)
    chrome.run(page.evaluate("""(where) => {
        const host = where === 'reply'
            ? document.querySelector('[data-markdown-text-style="assistant-message"]')
            : document.querySelector('[data-user-message-bubble="true"]');
        const s = document.createElement('span');
        s.style.display = 'inline-flex';
        s.innerHTML = '<span>Findings</span><span>Findings</span>';
        host.appendChild(s);
    }""", where))
    assert chrome.run(research._chatgpt_doubled_line(page)) == ""


# ═══ 4. A vision step's "already open" stands ════════════════════════════════

def test_a_vision_sighting_is_not_overruled_by_a_blind_read(p1run, chrome, page):
    """The line drawn once (the reader cannot see its list), presses that
    verify nothing, the vision step at the second miss answering "panel: open".
    Before: 31 s later a read that had never once seen the list open said
    "collapsed", and the presses began again. Now the sighting stands."""
    out = p1run(place="column", reply="empty", finishMs=9000, header="pair", once=True,
                deadToggle=True)
    assert HEADING in out.text, out.text[:200]
    assert out.while_thinking, "the setup needs the vision step to have been asked"
    first = out.cua.at[0]
    pressed = _times(chrome.run(page.evaluate("() => document.body.dataset.srPressTimes")))
    assert pressed and pressed[0] < first, "the setup needs presses before the vision step"
    later = [t for t in pressed if t > first]
    assert later == [], f"{len(later)} press(es) after the vision step said it was open"
    assert len([m for m in out.while_thinking if OPEN_MISSION in m]) == 1


# ═══ 5. The poll leaves the page where the person put it ═════════════════════

def test_phase1_polling_never_scrolls_the_page(p1run, chrome, page, monkeypatch):
    """A long thread, scrolled to its top when the poll starts, as a person
    reading the start of it would. Before: every poll scrolled it to the bottom.
    Now the poll ends with the page where it was."""
    real_poll = research.poll_until_done
    seen = {}

    async def _poll(pg, *a, **k):
        await pg.evaluate("() => { window.scrollTo(0, 0);"
                          " for (const e of document.querySelectorAll('*')) e.scrollTop = 0; }")
        seen["room"] = await pg.evaluate(
            "() => document.scrollingElement.scrollHeight - window.innerHeight")
        try:
            return await real_poll(pg, *a, **k)
        finally:
            seen["at"] = await pg.evaluate(
                "() => Math.max(window.scrollY,"
                " ...[...document.querySelectorAll('*')].map(e => e.scrollTop))")

    monkeypatch.setattr(research, "poll_until_done", _poll)
    out = p1run(place="column", reply="empty", finishMs=6000, header="pair", tall=True)
    assert HEADING in out.text, out.text[:200]
    assert seen["room"] > 2000, seen
    assert seen["at"] == 0, f"the poll scrolled the page to {seen['at']}px"
