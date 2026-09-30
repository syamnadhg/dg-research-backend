"""Phase 2: while Stop shows, ChatGPT and Claude get no computer-use completion check (09-30).

⛔⛔ THE DEFECT. The round-robin ran a computer-use completion check every five
minutes per agent whatever the page said. Every ChatGPT and Claude check on
record ran right after the page read had logged `stop_btn_present`, and every
one answered "still generating" (69 of 69 for Claude). The 09-30 run:

    05:20:36 [ChatGPT] DOM not-done: stop_btn_present (text=435, src=0, st=0)
    05:20:37 [ChatGPT] CUA checking completion (11m) — scrolled to bottom
    05:26:00 [Claude]  CUA checking completion (14m) — scrolled to bottom

⭐ NOW, for ChatGPT and Claude, a page read that sees Stop moves the check clock
forward and skips the check (the owner: "the Stop button is a good
determination point"). The first look comes a full interval after the last
poll that saw Stop. Gemini stays as it was.

── How it is measured ──────────────────────────────────────────────────────
`poll_all_agents_round_robin` is 4,000 lines and cannot be run whole, so its
REAL statements — from the page read (`detect_fn = DETECT_FNS.get(name)`) down
to the check clock's stamp after the computer-use call — are LIFTED out of
research.py's parse tree (read at test time, so a mutation is measured) and run
as the body of the per-agent loop. The page read's answer and the computer-use
call are stand-ins; the clock moves 30 s per poll, the round-robin's cadence.
"""
import ast
import asyncio
import time
from pathlib import Path

import pytest

import research

SRC_PATH = Path(research.__file__).resolve()

STOP = (False, "stop_btn_present (text=435, src=0, st=0)", {"text_len": 435})
AMBIGUOUS = (False, "no_done_marker (Thought-for badge … all missing; ctx=host)",
             {"text_len": 435})
MIN_WAIT = 300
INTERVAL = 300


#: file text → its parse tree. The text is the key, so a file a mutation
#: harness rewrote is parsed again, never served stale.
_TREES: dict = {}


def _poll_statements():
    """The per-agent loop body's statements, from the page read to the stamp
    after the computer-use completion check."""
    text = SRC_PATH.read_text(encoding="utf-8")
    if text not in _TREES:
        _TREES.clear()
        _TREES[text] = ast.parse(text)
    tree = _TREES[text]
    rr = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
          and n.name == "poll_all_agents_round_robin"]
    assert len(rr) == 1
    loops = [n for n in ast.walk(rr[0]) if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == "name"
             and isinstance(n.iter, ast.Name) and n.iter.id == "_pending_keys"]
    assert len(loops) == 1, f"expected ONE `for name in _pending_keys`, found {len(loops)}"
    body = loops[0].body

    def _assigns(stmt, target_src):
        return isinstance(stmt, ast.Assign) and any(
            ast.unparse(t) == target_src for t in stmt.targets)

    start = [i for i, s in enumerate(body) if _assigns(s, "detect_fn")]
    assert len(start) == 1, "the page read moved — re-anchor this test"
    diag = [i for i, s in enumerate(body) if _assigns(s, "diag_text")]
    assert len(diag) == 1, "the completion check moved — re-anchor this test"
    stamp = [i for i, s in enumerate(body)
             if i > diag[0] and _assigns(s, "p['last_cua_check']")]
    assert stamp, "the check clock is no longer stamped after the computer-use call"
    return body[start[0]:stamp[0] + 1]


class _Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.t


class _Page:
    async def evaluate(self, *a, **k):
        return None


class _Browser:
    async def switch_to_page(self, page):
        return None


def _run_polls(name, readings, *, lines, looks):
    """Poll `name` once per reading, 30 s apart, from the moment the minimum
    wait has passed. Returns the clock times the computer-use check ran at."""
    clock = _Clock()
    shell = ast.parse("async def _one_poll():\n    for name in [NAME]:\n        pass\n")
    shell.body[0].body[0].body = _poll_statements()
    ast.fix_missing_locations(shell)

    async def _look(*a, **k):
        looks.append(clock.t)
        return {"status": "done", "text": "CONCLUSION: GENERATING"}

    reading = {}

    async def _detect(page, **kw):
        return reading["now"]

    class _FastAsyncio:
        def __getattr__(self, attr):
            return getattr(asyncio, attr)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)

    start = clock.t - MIN_WAIT
    p = {"page": _Page(), "start_time": start, "last_cua_check": start,
         "flat_history": [], "done_marker_first_at": 0.0}
    scope = {**vars(research),
             "NAME": name, "p": p, "browser": _Browser(), "cua_client": None,
             "verbose": False, "pending": {name: p}, "results": {},
             "CUA_CHECK_INTERVAL": INTERVAL,
             "MIN_WAIT": {"ChatGPT": MIN_WAIT, "Gemini": MIN_WAIT, "Claude": MIN_WAIT},
             "DETECT_FNS": {name: _detect}, "_shadow_observed_cua": _look,
             "time": clock, "asyncio": _FastAsyncio(),
             "log": lambda m, level="INFO": lines.append((level, str(m))),
             "emit_event": lambda *a, **k: None,
             "_partial_text_len": 435, "agent_key": name.lower()}
    exec(compile(shell, str(SRC_PATH), "exec"), scope)
    for r in readings:
        reading["now"] = r
        scope["elapsed"] = clock.t - p["start_time"]
        asyncio.run(scope["_one_poll"]())
        clock.t += 30
    return start


@pytest.mark.parametrize("name", ["ChatGPT", "Claude"])
def test_no_computer_use_check_while_the_page_shows_stop(name):
    """⭐⭐ THE 09-30 SHAPE. Ten minutes of polls, every one reading Stop: no
    computer-use check at all. Before the fix: one per five minutes (two)."""
    lines, looks = [], []
    _run_polls(name, [STOP] * 20, lines=lines, looks=looks)
    assert looks == [], f"{len(looks)} computer-use check(s) while Stop showed"
    said = [m for _lv, m in lines if "shows the Stop button" in m]
    assert len(said) == 1, said


@pytest.mark.parametrize("name", ["ChatGPT", "Claude"])
def test_a_page_that_cannot_tell_still_gets_one_check_per_five_minutes(name):
    """No Stop and no done mark: the page cannot tell, so the check still runs,
    once per window — exactly as before."""
    lines, looks = [], []
    _run_polls(name, [AMBIGUOUS] * 20, lines=lines, looks=looks)
    assert len(looks) == 2, looks
    assert looks[1] - looks[0] >= INTERVAL


@pytest.mark.parametrize("name", ["ChatGPT", "Claude"])
def test_the_first_look_after_stop_goes_waits_a_full_interval(name):
    """The clock moved forward on every Stop read, so a page that stops showing
    Stop (and shows no done mark either) is looked at a full five minutes after
    the last poll that saw Stop, not on the first read without it."""
    lines, looks = [], []
    start = _run_polls(name, [STOP] * 10 + [AMBIGUOUS] * 12, lines=lines, looks=looks)
    last_stop = start + MIN_WAIT + 9 * 30
    assert looks, "the check never came back once Stop was gone"
    assert looks[0] >= last_stop + INTERVAL, (looks[0] - last_stop)


def test_gemini_keeps_its_five_minute_check_even_with_stop():
    """Gemini's detector has hidden-Stop and weak-signal cases, so it keeps the
    old schedule."""
    lines, looks = [], []
    _run_polls("Gemini", [STOP] * 20, lines=lines, looks=looks)
    assert len(looks) == 2, looks
    assert not any("shows the Stop button" in m for _lv, m in lines)


def test_the_lifted_statements_are_the_round_robins_own():
    """Guard for the measurement itself: the slice holds the page read, the
    new Stop rule and the computer-use call, in that order."""
    src = "\n".join(ast.unparse(s) for s in _poll_statements())
    i_read = src.index("DETECT_FNS.get(name)")
    i_rule = src.index("stop_btn_present")
    i_look = src.index("_shadow_observed_cua(")
    assert i_read < i_rule < i_look
