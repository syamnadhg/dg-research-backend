"""Wave 15 (10-02) — a report read that fails because the browser closed is a
crash, not a card, for EVERY agent.

⛔⛔ 10-01 (logs 3NH9Q7CH, attempt 0, 11:19:09): Chrome died during ChatGPT's
extraction, every reader then failed on the closed browser, and the poll put up
"Couldn't read ChatGPT's report" a minute before the crash path unwound the run
anyway. The rule that answers it — ask the browser before an empty read becomes
a card; a dead one unwinds for the silent crash retry, with no card, no
"failed" status and nothing saved "errored" — landed for the agent it was seen
on, and only ChatGPT ever drove it (tests/test_chatgpt_dr_read_1001.py).

⭐ Both Phase-2 read sites are shared by ChatGPT, Claude and Gemini, and so is the
"no failed status" half inside the read. Here Claude and Gemini drive them: the
browser is gone before the read, the agent's REAL reader runs on it through each
of the two read sites (after the page said done, after computer use said done),
and the run unwinds. Claude's one silent re-read (#777, for a clipboard that came
back empty on a live browser) comes after the browser is asked, so a dead browser
never gets it — and never a card either.

── How it is measured ──────────────────────────────────────────────────────
As for ChatGPT: the statements of each of `poll_all_agents_round_robin`'s two
read blocks are lifted out of research.py's parse tree at test time
(`_extraction_block`, so a mutation is measured) and run with the REAL
`extract_and_record_agent` and the agent's REAL reader, in headless Chrome on a
browser context of its own that is closed before the read. Only the edges are
stood in: the event stream, the record's writes, computer use's look and the
card itself (a recorder).

Run:  pytest tests/test_w15_every_agent_crash_1002.py -v
"""
import ast
from types import SimpleNamespace

import pytest

import research
import test_chatgpt_dr_read_1001 as dr

chrome = dr.chrome
fast = dr.fast
logs = dr.logs

#: The two read sites: after the page said done, after computer use said done.
PAGE_DONE, CUA_DONE = dr.PAGE_DONE, dr.CUA_DONE

#: What the page held before Chrome died: a finished report, for each agent.
REPORT = ("<main><model-response><message-content><h1>Saint Bernard health</h1>"
          + "<p>Hip dysplasia, bloat and lifespan tables across kennel registries.</p>" * 40
          + "</message-content></model-response></main>")


@pytest.fixture(autouse=True)
def run_dir(tmp_path, monkeypatch):
    """Anything a reader writes goes to a temporary folder, never the machine's."""
    monkeypatch.setattr(research, "_active_run_sink", lambda: SimpleNamespace(dir=tmp_path))
    return tmp_path


def _read_on_a_dead_browser(chrome, monkeypatch, name, marker):
    """Run one read block for `name` on a browser that died just before it.
    Returns (the error the block raised or None, cards, emits, saved, runtime)."""
    ctx = chrome.run(chrome.ctx.browser.new_context())
    pg = chrome.run(ctx.new_page())
    chrome.run(pg.set_content(REPORT))
    chrome.run(ctx.close())
    assert pg.is_closed(), "the browser did not die"

    shell = ast.parse("async def _go():\n    for name in [NAME]:\n        pass\n")
    shell.body[0].body[0].body = dr._extraction_block(marker)
    ast.fix_missing_locations(shell)
    runtime = SimpleNamespace(agent_progress_snapshots={}, agent_findings={},
                              last_failure_kind=None)
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)

    async def _same(text, **k):
        return text

    async def _no_look(*a, **k):
        return None

    monkeypatch.setattr(research, "_rehost_document_images", _same)
    monkeypatch.setattr(research, "_shadow_observed_cua", _no_look)
    emits, saved, cards = [], [], []
    monkeypatch.setattr(research, "emit_event", lambda kind, phase=None, agent=None, **d:
                        emits.append((kind, agent, d.get("status"))))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda key, status, *a, **k:
                        saved.append((key, status)))
    key = name.lower()
    p = {"page": pg, "extraction_attempts": 1, "flat_history": [],
         "done_marker_first_at": 0.0, "start_time": 0.0}
    browser = SimpleNamespace(page=pg, context=ctx, switch_to_page=dr._to_front)
    scope = {**vars(research), "NAME": name, "p": p, "browser": browser,
             "cua_client": object(), "verbose": False, "elapsed": 1000,
             "_partial_text_len": 0, "t1": 0, "results": {}, "pending": {name: p},
             "agent_key": key, "_tracks_dir": None, "_runtime": runtime,
             "fail_agent": lambda *a, **k: cards.append(a)}
    exec(compile(shell, str(dr.SRC), "exec"), scope)
    err = None
    try:
        chrome.run(scope["_go"]())
    except RuntimeError as e:
        err = e
    return err, cards, emits, saved, runtime


@pytest.mark.parametrize("marker", [PAGE_DONE, CUA_DONE], ids=["page-said-done", "cua-said-done"])
@pytest.mark.parametrize("name", ["Claude", "Gemini"])
def test_a_dead_browser_is_a_crash_not_a_card_for_claude_and_gemini(
        chrome, fast, logs, monkeypatch, name, marker):
    """⭐⭐ The browser is gone; the agent's own reader comes back empty. The run
    unwinds for its silent crash retry — the crash path's own error, its kind
    recorded — with no card, the agent not shown "failed" and nothing saved
    "errored". For Claude that is on its FIRST empty read: its silent re-read is
    for a live browser."""
    err, cards, emits, saved, runtime = _read_on_a_dead_browser(
        chrome, monkeypatch, name, marker)
    key = name.lower()
    assert cards == [], f"a card was put up for {name} on a dead browser: {cards}"
    assert err is not None, f"{name}'s empty read on a dead browser did not unwind the run"
    assert research._is_browser_close_error(err), str(err)
    assert runtime.last_failure_kind == "browser_crash"
    # The recorder is on the path: the read's own first status went through it.
    assert ("agent_progress", key, "extracting") in emits, emits
    assert ("agent_progress", key, "failed") not in emits, f"{name} shown failed for a crash"
    assert (key, "errored") not in saved, f"'errored' saved for {name} for a crash"
    assert dr._said(logs, f"[{name}] no content, and the whole browser is gone")
    assert dr._said(logs, f"[{name}] the whole browser is gone, not just this tab")
    assert not dr._said(logs, "surfacing user decision")
    assert not dr._said(logs, "silent re-extraction before alerting")
