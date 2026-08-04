"""Wave 5B — a clipboard read must only accept what the copy we just made put there.

The defect, from the deep review and re-verified in the code on 2026-08-04:
`clear_clipboard()`'s own sibling docstring stated the clear "runs immediately
before `get_clipboard()` at every call site". It did not. There were NINE
clipboard reads across four share extractors — Gemini ×3, Claude ×2, the
NotebookLM share helper, the NotebookLM URL extractor, the Claude artifact
publisher ×2 — and `clear_clipboard()` was called in exactly TWO unrelated
places: once at run start, and once inside the Claude response extractor.

Why that ships a wrong link rather than merely a stale one: a single run
produces several share links in sequence, and every extractor accepts whatever
it finds provided the text merely LOOKS like that platform's share URL
(`"gemini" in clip and "share" in clip`, `"claude." in clip`,
`is_notebooklm_url(clip)`). A link this run copied twenty seconds earlier
passes all of those. The run-start clear closes the cross-RUN channel only —
which is exactly what its own comment describes — and by the time the second
extractor runs, the contaminating value was written by THIS run, minutes after
that clear.

Two shapes are covered here, because arming means something different in each:

  * DOM copy → read. The copy is ours; arm before the click.
  * mission → read. The copy happens somewhere inside a vision agent loop, so
    the only moment at which "the clipboard is empty" implies "nothing has been
    copied yet" is BEFORE the mission starts, not before the read after it.

The doubles below model the clipboard as a mutable SLOT rather than a scripted
return value. That is deliberate, and it is the lesson of Wave 5: a
`get_clipboard` double that ignores `clear_clipboard` answers identically
whether or not the fix is present, so it cannot tell the fix from the bug.
Every test here fails if the arming is removed.
"""
from __future__ import annotations

import ast
import asyncio
import inspect

import pytest

import research


_NB_STALE = "https://notebook.google.com/notebook/stale-6f3b1c22-aaaa-bbbb-cccc"
_NB_FRESH = "https://notebook.google.com/notebook/fresh-0d028786-66ef-4933-a322"
_GEM_STALE = "https://gemini.google.com/share/stale111111"
_CLAUDE_STALE = "https://claude.site/artifacts/staleaaa-1111-2222-3333-444455556666"
_TAB_URL = "https://gemini.google.com/app/abcdef0123456789"


# ── The OS clipboard, modelled as a slot ─────────────────────────────────────

class _OSClipboard:
    """One mutable slot plus an ordered trace, standing in for the OS clipboard.

    `clear()` really empties it and `read()` really returns whatever is in it,
    so a test can put a link there, run the code, and find out whether the code
    could still see it. A double that answered from a script instead would pass
    with the arming deleted — the exact failure mode that let a dead NotebookLM
    branch look tested for a fortnight.
    """

    def __init__(self, initial: str = "", trace: list | None = None):
        self.value = initial
        self.trace = trace if trace is not None else []
        self.clears = 0
        self.reads = 0
        self._late: tuple | None = None

    # The OS side ────────────────────────────────────────────────────────────
    def clear(self):
        self.clears += 1
        self.value = ""
        self.trace.append("arm")

    def read(self):
        self.reads += 1
        if self._late and self.reads >= self._late[0]:
            self.value = self._late[1]
        self.trace.append("read:" + ("empty" if not self.value else "value"))
        return self.value

    # The page side ──────────────────────────────────────────────────────────
    def copy(self, text: str):
        """What a working "Copy link" button does."""
        self.value = text
        self.trace.append("copy")

    def copy_lands_on_read(self, n: int, text: str):
        """A copy that reaches the OS only by the nth read — the case an armed
        clipboard exposes and a stale one used to mask."""
        self._late = (n, text)

    def install(self, monkeypatch):
        monkeypatch.setattr(research, "clear_clipboard", self.clear)
        monkeypatch.setattr(research, "get_clipboard", self.read)
        return self


@pytest.fixture
def clipboard(monkeypatch):
    return _OSClipboard().install(monkeypatch)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """Polling delays are real seconds; the schedule is not what is under test."""
    async def _instant(_s, *a, **k):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant)


# ── 1. The two helpers, on their own ─────────────────────────────────────────

def test_an_armed_clipboard_that_never_receives_a_copy_yields_nothing(clipboard):
    """The whole point: no copy, no link — not "whatever was lying around"."""
    clipboard.value = _NB_STALE
    research._arm_clipboard()
    got, seen = asyncio.run(research._read_clipboard_after_copy(research.is_notebooklm_url))
    assert got == ""
    assert seen == ""


def test_arming_actually_empties_the_clipboard(clipboard):
    clipboard.value = _NB_STALE
    research._arm_clipboard()
    assert clipboard.value == ""
    assert clipboard.clears == 1


def test_a_copy_that_lands_late_is_still_caught(clipboard):
    """Arming removes the value that used to be there on the first read, so the
    helper has to WAIT for the real one instead of reading once and giving up."""
    clipboard.copy_lands_on_read(3, _NB_FRESH)
    got, _ = asyncio.run(research._read_clipboard_after_copy(research.is_notebooklm_url))
    assert got == _NB_FRESH
    assert clipboard.reads == 3


def test_a_value_that_fails_the_shape_test_is_never_returned_but_is_reported(clipboard):
    """`seen` exists so a changed copy button gets NOTICED rather than silently
    producing no link — the NotebookLM helper warns with it."""
    clipboard.value = "Some notebook prose the Copy button grabbed instead"
    got, seen = asyncio.run(research._read_clipboard_after_copy(research.is_notebooklm_url))
    assert got == ""
    assert seen == "Some notebook prose the Copy button grabbed instead"


def test_polling_continues_past_a_value_that_fails_until_one_passes(clipboard):
    """A failing value must not end the poll: the clipboard can hold an
    intermediate value (a title, a heading) before the URL lands."""
    clipboard.value = "Untitled notebook"
    clipboard.copy_lands_on_read(2, _NB_FRESH)
    got, seen = asyncio.run(research._read_clipboard_after_copy(research.is_notebooklm_url))
    assert got == _NB_FRESH
    assert seen == _NB_FRESH


def test_no_shape_test_means_the_first_non_empty_value_wins(clipboard):
    clipboard.value = "anything at all"
    got, seen = asyncio.run(research._read_clipboard_after_copy())
    assert got == "anything at all"
    assert seen == "anything at all"


def test_surrounding_whitespace_is_stripped_once_centrally(clipboard):
    """Two of the four extractors stripped and two did not; the shape test now
    sees the same string every caller gets."""
    clipboard.value = f"  {_NB_FRESH}\n"
    got, _ = asyncio.run(research._read_clipboard_after_copy(research.is_notebooklm_url))
    assert got == _NB_FRESH


def test_a_whitespace_only_clipboard_counts_as_empty(clipboard):
    clipboard.value = "   \n\t "
    got, seen = asyncio.run(research._read_clipboard_after_copy())
    assert (got, seen) == ("", "")


def test_tries_bounds_how_long_a_missing_copy_is_waited_for(clipboard):
    asyncio.run(research._read_clipboard_after_copy(lambda c: False, tries=2))
    assert clipboard.reads == 2


def test_tries_below_one_still_reads_once(clipboard):
    """A misconfigured bound must not turn the read into a silent no-op."""
    clipboard.value = _NB_FRESH
    got, _ = asyncio.run(research._read_clipboard_after_copy(tries=0))
    assert got == _NB_FRESH
    assert clipboard.reads == 1


def test_the_helper_never_returns_a_value_its_caller_would_reject(clipboard):
    """Callers now act on the return value directly; if a rejected value could
    come back as `accepted`, every call site would adopt it."""
    clipboard.value = _GEM_STALE
    got, _ = asyncio.run(
        research._read_clipboard_after_copy(lambda c: "claude." in c))
    assert got == ""


# ── 2. Structural: there is exactly one door, and it is always armed ─────────

def _call_owners(tree):
    """Map every Call node to the name of the function that lexically holds it."""
    owner = {}

    def walk(node, fname):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call):
                owner[child] = fname
            nxt = (child.name
                   if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                   else fname)
            walk(child, nxt)

    walk(tree, "<module>")
    return owner


def _named_calls(owner, name):
    return [(c, owner[c]) for c in owner
            if isinstance(c.func, ast.Name) and c.func.id == name]


def test_the_os_clipboard_is_read_in_exactly_one_place():
    """`get_clipboard()` is the unarmed door. Closing the nine call sites is
    worth nothing if a tenth can be opened next to a new copy button, so the
    read is allowed in ONE function and the guard says which."""
    owner = _call_owners(ast.parse(inspect.getsource(research)))
    readers = {fn for _c, fn in _named_calls(owner, "get_clipboard")}
    assert readers == {"_read_clipboard_after_copy"}, (
        "get_clipboard() must only be called by _read_clipboard_after_copy — "
        f"found it in {sorted(readers)}. Route the new read through the helper "
        "and arm before whatever copies.")


def test_every_clipboard_read_is_preceded_by_an_arm_in_the_same_function():
    """`_read_clipboard_after_copy` without `_arm_clipboard` is exactly as wrong
    as the bare `get_clipboard()` it replaced — at the OS level there is no
    difference between a fresh copy and a stale one."""
    owner = _call_owners(ast.parse(inspect.getsource(research)))
    first_read, first_arm = {}, {}
    for call, fn in _named_calls(owner, "_read_clipboard_after_copy"):
        first_read[fn] = min(first_read.get(fn, call.lineno), call.lineno)
    for call, fn in _named_calls(owner, "_arm_clipboard"):
        first_arm[fn] = min(first_arm.get(fn, call.lineno), call.lineno)

    assert first_read, "the guard found no clipboard reads at all — it has gone blind"
    unarmed = sorted(fn for fn in first_read
                     if fn not in first_arm or first_arm[fn] > first_read[fn])
    assert not unarmed, (
        f"these read the clipboard without arming it first: {unarmed}")


def test_the_run_start_clear_is_still_there():
    """Arming closes the SAME-run channel. The run-start clear closes the
    cross-run one — yesterday's link surviving in the OS clipboard — and
    nothing else does. Neither makes the other redundant."""
    tree = ast.parse(inspect.getsource(research.run_pipeline))
    clears = [c for c in ast.walk(tree)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
              and c.func.id == "clear_clipboard"]
    assert len(clears) == 1, (
        "run_pipeline no longer clears the clipboard exactly once at start")


def test_the_suite_cannot_reach_the_real_clipboard(monkeypatch):
    """Meta, and load-bearing: `clear_clipboard()` shells out to pbcopy, so a
    test that reaches a share extractor would WIPE what the developer had
    copied. The conftest fixture prevents that, and without this assertion its
    deletion is invisible — every test passes and the damage is off-screen."""
    for fn in (research.clear_clipboard, research.get_clipboard):
        assert getattr(fn, "is_suite_clipboard_double", False), (
            f"{fn.__name__} is the REAL implementation during a test — the "
            "suite is about to touch the developer's own clipboard")


def test_all_four_extractors_are_covered():
    """Names the functions, so deleting a call site cannot quietly shrink what
    the guard above is guarding."""
    owner = _call_owners(ast.parse(inspect.getsource(research)))
    readers = {fn for _c, fn in _named_calls(owner, "_read_clipboard_after_copy")}
    assert readers == {
        "extract_share_link_gemini",
        "extract_share_link_claude",
        "_set_nlm_public_and_get_link",
        "extract_notebooklm_url",
        "publish_open_claude_artifact",
    }, sorted(readers)


# ── 3. NotebookLM share helper — the DOM-copy shape ──────────────────────────

class _NlmPage:
    """Answers `_set_nlm_public_and_get_link`, keyed on fragments of the real JS.

    `copy_writes` says what the "Copy link" button actually manages to put on
    the clipboard: the fresh link on a healthy page, nothing at all when the
    button has moved or the click missed. The second case is the one that used
    to return the PREVIOUS agent's link.
    """

    def __init__(self, clip: _OSClipboard, copy_writes: str | None = None,
                 late_on_read: int = 0):
        self._clip = clip
        self._copy_writes = copy_writes
        self._late_on_read = late_on_read
        self.trace = clip.trace

    async def evaluate(self, js, arg=None):
        if "notebook access" in js:
            return "opened"
        if "anyone with the link" in js and "opt.click()" in js:
            return "selected"
        if "isNb(val)" in js:                        # the share-link read JS
            self.trace.append("copy_click")
            if self._copy_writes and self._late_on_read:
                self._clip.copy_lands_on_read(self._late_on_read, self._copy_writes)
            elif self._copy_writes:
                self._clip.copy(self._copy_writes)
            return {"url": "clipboard", "via": "copy"}
        if "PHRASE" in js:
            return False
        return ""


def _run_nlm(page):
    return asyncio.run(research._set_nlm_public_and_get_link(page, "NotebookLM"))


def test_a_link_the_previous_agent_copied_is_not_returned_as_this_one(clipboard):
    """THE bug. The clipboard already holds a notebook URL from earlier in this
    run; the Copy click does nothing. Pre-fix the shape test passed and the
    stale link was emitted as this notebook's share link."""
    clipboard.value = _NB_STALE
    url, _public, _access = _run_nlm(_NlmPage(clipboard, copy_writes=None))
    assert _NB_STALE not in url
    assert url == ""


def test_the_link_the_copy_button_actually_writes_is_returned(clipboard):
    """Arming must not cost the healthy path its link."""
    clipboard.value = _NB_STALE
    url, _p, _a = _run_nlm(_NlmPage(clipboard, copy_writes=_NB_FRESH))
    assert url == _NB_FRESH


def test_a_copy_that_lands_after_the_first_read_is_still_returned(clipboard):
    """Before arming, a slow copy was invisible — the stale value answered the
    first read. Now the first read is empty, so the wait has to be real."""
    url, _p, _a = _run_nlm(
        _NlmPage(clipboard, copy_writes=_NB_FRESH, late_on_read=3))
    assert url == _NB_FRESH


def test_the_clipboard_is_armed_before_the_copy_click_not_after_it(clipboard):
    """The copy lives INSIDE the read JS. Arming after it would clear the very
    link that click just produced, so the ORDER is the fix, not the presence."""
    _run_nlm(_NlmPage(clipboard, copy_writes=_NB_FRESH))
    assert clipboard.trace.index("arm") < clipboard.trace.index("copy_click")


def test_a_clipboard_holding_something_else_entirely_is_reported_not_returned(
        clipboard, capsys):
    page = _NlmPage(clipboard, copy_writes="Research brief: ocean acidification")
    url, _p, _a = _run_nlm(page)
    assert url == ""
    assert "clipboard held no notebook" in capsys.readouterr().out


# ── 4. Claude artifact publisher — per-attempt arming, then the mission ──────

class _ClaudePublishPage:
    def __init__(self, clip: _OSClipboard, copy_writes: str | None = None):
        self._clip = clip
        self._copy_writes = copy_writes
        self.copy_clicks = 0

    async def wait_for_selector(self, *a, **k):
        return object()

    async def evaluate(self, js, arg=None):
        if "publish-artifact" in js:
            return "clicked"
        if "'publish'" in js or "create public link" in js:
            return "confirmed"
        if "claude.site/artifacts" in js:            # the in-dialog URL read
            return ""
        if "copy link" in js:
            self.copy_clicks += 1
            self._clip.trace.append("copy_click")
            if self._copy_writes:
                self._clip.copy(self._copy_writes)
            return "copied"
        return ""


class _Browser:
    def __init__(self, page=None, tab_url=_TAB_URL):
        self.page = page
        self.context = _Ctx()
        self._tab_url = tab_url

    async def current_url(self):
        return self._tab_url


class _Ctx:
    pages: list = []

    def on(self, *a, **k):
        pass

    def remove_listener(self, *a, **k):
        pass


def test_a_stale_claude_link_is_not_returned_as_the_published_url(clipboard):
    """`'claude.site' in clip` is satisfied by any artifact this run already
    published — including the sources checklist published moments earlier."""
    clipboard.value = _CLAUDE_STALE
    page = _ClaudePublishPage(clipboard, copy_writes=None)
    got = asyncio.run(research.publish_open_claude_artifact(page, _Browser(), None))
    assert got == ""


def test_the_link_this_publish_copies_is_returned(clipboard):
    fresh = "https://claude.site/artifacts/fresh999-0000-1111-2222-333344445555"
    clipboard.value = _CLAUDE_STALE
    page = _ClaudePublishPage(clipboard, copy_writes=fresh)
    got = asyncio.run(research.publish_open_claude_artifact(page, _Browser(), None))
    assert got == fresh


def test_every_publish_attempt_arms_before_it_clicks_copy(clipboard):
    """The DOM loop runs up to three times. Arming once outside it would let
    attempt 3 accept what attempt 1 copied — a retry that "succeeds" while the
    button it clicked did nothing."""
    page = _ClaudePublishPage(clipboard, copy_writes=None)
    asyncio.run(research.publish_open_claude_artifact(page, _Browser(), None))
    assert page.copy_clicks == 3
    pairs = [t for t in clipboard.trace if t in ("arm", "copy_click")]
    assert pairs == ["arm", "copy_click"] * 3


def test_the_vision_publish_is_armed_before_the_mission_not_after_it(
        clipboard, monkeypatch):
    """The mission is what copies. Arming after it returns would clear the link
    it just produced; arming before it is the only placement that means
    anything on the clipboard afterwards came from the mission."""
    async def _mission(*a, **k):
        clipboard.trace.append("mission")
        return {"text": ""}

    monkeypatch.setattr(research, "_shadow_observed_cua", _mission)
    clipboard.value = _CLAUDE_STALE
    page = _ClaudePublishPage(clipboard, copy_writes=None)
    got = asyncio.run(
        research.publish_open_claude_artifact(page, _Browser(), object()))

    assert got == ""                                   # the stale link is gone
    # Partitioned between the LAST copy click and the mission. "An arm happened
    # somewhere before the mission" is already true from the three the DOM loop
    # performed above, so a presence check passes with the mission's own arm
    # deleted — verified by mutation, which is exactly how this test first
    # failed to earn its keep.
    trace = clipboard.trace
    mission = trace.index("mission")
    last_copy = max(i for i, t in enumerate(trace[:mission]) if t == "copy_click")
    assert "arm" in trace[last_copy:mission], (
        "nothing re-armed the clipboard between the DOM publish attempts and "
        "the vision mission")
    assert trace[mission + 1:].count("arm") == 0


# ── 5. Gemini — the DOM copy, and the salvage read after a timeout ──────────

class _Keyboard:
    def __init__(self, trace):
        self.trace = trace

    async def press(self, key):
        self.trace.append(f"press:{key}")


class _GeminiPage:
    """`share_opens` False sends the flow straight to the vision fallback,
    which is where the timeout-salvage read lives."""

    def __init__(self, clip: _OSClipboard, share_opens=True,
                 copy_writes: str | None = None):
        self._clip = clip
        self._share_opens = share_opens
        self._copy_writes = copy_writes
        self.keyboard = _Keyboard(clip.trace)

    async def query_selector(self, sel):
        return None

    async def evaluate(self, js, arg=None):
        if "'share & export'" in js:
            return self._share_opens
        if "copy link" in js.lower():
            self._clip.trace.append("copy_click")
            if self._copy_writes:
                self._clip.copy(self._copy_writes)
            return "text"
        return ""


def _run_gemini(page, clipboard, monkeypatch, *, mission_times_out=False,
                mission_text="", mission_copies=""):
    async def _agent_loop(*a, **k):
        clipboard.trace.append("mission")
        if mission_copies:
            clipboard.copy(mission_copies)
        if mission_times_out:
            raise asyncio.TimeoutError()
        return {"text": mission_text}

    monkeypatch.setattr(research, "agent_loop", _agent_loop)
    return asyncio.run(research.extract_share_link_gemini(
        _Browser(page), cua_client=object(), label="Gemini"))


def test_a_gemini_link_from_earlier_in_the_run_cannot_survive_a_mission_timeout(
        clipboard, monkeypatch):
    """The salvage read is the most exposed of the nine: it fires precisely when
    we do NOT know how far the mission got, and it used to answer with whatever
    was on the clipboard — which on a Phase 2 run is very often a Gemini share
    link this run produced on an earlier attempt."""
    clipboard.value = _GEM_STALE
    page = _GeminiPage(clipboard, share_opens=False)
    res = _run_gemini(page, clipboard, monkeypatch, mission_times_out=True)
    assert res.url != _GEM_STALE
    assert res.verified is False


def test_the_salvage_read_still_applies_the_gemini_shape_test(
        clipboard, monkeypatch):
    """Arming alone is not the whole guarantee. A vision mission hunting for a
    place to paste copies whatever it lands on — a heading, a prompt, the page
    title — so a read that dropped its shape test would emit THAT as the share
    link, and the arm would be no defence because the value is genuinely fresh.
    """
    page = _GeminiPage(clipboard, share_opens=False)
    res = _run_gemini(page, clipboard, monkeypatch, mission_times_out=True,
                      mission_copies="Deep Research: ocean acidification")
    assert "ocean acidification" not in res.url
    assert res.verified is False


def test_the_gemini_mission_is_armed_before_it_starts(clipboard, monkeypatch):
    page = _GeminiPage(clipboard, share_opens=False)
    _run_gemini(page, clipboard, monkeypatch, mission_times_out=True)
    mission = clipboard.trace.index("mission")
    assert "arm" in clipboard.trace[:mission]


def test_a_link_the_gemini_copy_button_writes_is_still_accepted(
        clipboard, monkeypatch):
    fresh = "https://gemini.google.com/share/fresh222222"
    clipboard.value = _GEM_STALE
    page = _GeminiPage(clipboard, share_opens=True, copy_writes=fresh)
    res = _run_gemini(page, clipboard, monkeypatch)
    assert res.url == fresh
    assert res.verified is True


def test_the_gemini_dom_copy_is_armed_before_the_click(clipboard, monkeypatch):
    fresh = "https://gemini.google.com/share/fresh222222"
    page = _GeminiPage(clipboard, share_opens=True, copy_writes=fresh)
    _run_gemini(page, clipboard, monkeypatch)
    assert clipboard.trace.index("arm") < clipboard.trace.index("copy_click")


def test_a_stale_gemini_link_is_not_adopted_when_the_copy_click_misses(
        clipboard, monkeypatch):
    clipboard.value = _GEM_STALE
    page = _GeminiPage(clipboard, share_opens=True, copy_writes=None)
    res = _run_gemini(page, clipboard, monkeypatch)
    assert res.url != _GEM_STALE
    assert res.verified is False


# ── 5b. Claude share extractor — the mission that follows a failed publish ──

def _run_claude(clipboard, monkeypatch, *, published="", mission_text=""):
    async def _mission(*a, **k):
        clipboard.trace.append("mission")
        return {"text": mission_text}

    async def _publish(*a, **k):
        clipboard.trace.append("publish")
        return published

    async def _click(*a, **k):
        return False

    monkeypatch.setattr(research, "_shadow_observed_cua", _mission)
    monkeypatch.setattr(research, "publish_open_claude_artifact", _publish)
    monkeypatch.setattr(research, "_click_claude_artifact", _click)
    page = _ClaudePublishPage(clipboard)
    return asyncio.run(research.extract_share_link_claude(
        _Browser(page), cua_client=object(), label="Claude"))


def test_the_claude_share_mission_is_armed_before_it_starts(clipboard, monkeypatch):
    """The arm has to sit before the MISSION, not merely before the read. A
    line-order guard alone would accept it moved down to just above the read,
    where it clears the very link the mission copied."""
    _run_claude(clipboard, monkeypatch)
    mission = clipboard.trace.index("mission")
    assert "arm" in clipboard.trace[:mission]
    assert clipboard.trace[mission + 1:].count("arm") == 0


def test_a_stale_claude_link_cannot_survive_the_claude_share_mission(
        clipboard, monkeypatch):
    """`"claude." in clip` is the loosest shape test of the four — it is
    satisfied by the artifact the publish step copied moments earlier on the
    very path that brought us here."""
    clipboard.value = _CLAUDE_STALE
    res = _run_claude(clipboard, monkeypatch)
    assert res.url != _CLAUDE_STALE
    assert res.verified is False


def test_a_link_the_claude_mission_copies_is_still_accepted(clipboard, monkeypatch):
    fresh = "https://claude.site/artifacts/mission1-2222-3333-4444-555566667777"

    async def _mission(*a, **k):
        clipboard.trace.append("mission")
        clipboard.copy(fresh)
        return {"text": ""}

    monkeypatch.setattr(research, "_shadow_observed_cua", _mission)

    async def _publish(*a, **k):
        return ""

    async def _click(*a, **k):
        return False

    monkeypatch.setattr(research, "publish_open_claude_artifact", _publish)
    monkeypatch.setattr(research, "_click_claude_artifact", _click)
    clipboard.value = _CLAUDE_STALE
    res = asyncio.run(research.extract_share_link_claude(
        _Browser(_ClaudePublishPage(clipboard)), cua_client=object(), label="Claude"))
    assert res.url == fresh
    assert res.verified is True


# ── 6. NotebookLM URL extractor — the vision fallback ───────────────────────

class _NlmOuterPage(_NlmPage):
    async def query_selector(self, sel):
        return None

    async def wait_for_selector(self, *a, **k):
        raise RuntimeError("no share button")


def test_the_notebooklm_vision_mission_is_armed_before_it_runs(
        clipboard, monkeypatch):
    """The DOM attempt that just failed may itself have clicked Copy link — a
    notebook URL it left behind passes `is_notebooklm_url` whether or not the
    mission ever copied anything."""
    async def _mission(*a, **k):
        clipboard.trace.append("mission")
        return {"text": ""}

    async def _observe(*a, **k):
        return None

    monkeypatch.setattr(research, "_shadow_observed_cua", _mission)
    monkeypatch.setattr(research, "_selfheal_shadow_observe", _observe)
    clipboard.value = _NB_STALE
    page = _NlmOuterPage(clipboard, copy_writes=None)
    res = asyncio.run(research.extract_notebooklm_url(
        _Browser(page, tab_url=_NB_FRESH), cua_client=object()))

    mission = clipboard.trace.index("mission")
    assert "arm" in clipboard.trace[:mission]
    assert res.url != _NB_STALE
