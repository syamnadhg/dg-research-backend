"""Wave 17 — Phase 3 tells the NotebookLM pop-up what it is really doing.

The owner (10-01) wants a live walkthrough of NotebookLM built from the run's
REAL events: the notebook made, each source landing by name, the podcast
setting (e.g. "Deep dive · Long"), generating, ready. Until now Phase 3 sent
free-text `progress` lines and nothing else: the moment the notebook was made
was only logged, the census knew each source's name and emitted nothing, the
setting NotebookLM read back was only logged, and "ready" and "saved" were log
lines too.

Each step is now a row on the ordinary `agent_progress` event —
`timeline=[{id, label, state, at, detail?, url?}]` — which the app folds by id
(dg-research src/lib/activity-timeline.ts).

▶ EXECUTED AT THE CALL SITES, NOT AT THE HELPER. Every test drives the real
Phase 3 function that owns the step — the DOM upload and its census, the repair
rounds, the reopen, the upload phase's rename and share, the computer-use
fallback, the podcast step, the publish — with NotebookLM's page replaced by
small fakes. Only the events are read. Nothing opens a browser or a website.

⛔ THE WORDS ARE OURS. A label is built from this run's file list and title,
and from NotebookLM's state as our code read it — never from page text.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import research

NB_URL = "https://notebooklm.google.com/notebook/0d1f9c2e-aaaa-bbbb-cccc-1234567890ab"
HOME_URL = "https://notebooklm.google.com/"
FILES = [Path("chatgpt.md"), Path("gemini.md"), Path("claude.md")]
NAMES = [p.name for p in FILES]


class _QuickAsyncio:
    """The step's own sleeps cut to nothing; everything else is real asyncio."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(secs=0, *a, **k):
        await asyncio.sleep(0)


async def _none(*a, **k):
    return None


async def _false(*a, **k):
    return False


async def _true(*a, **k):
    return True


@pytest.fixture
def sent(monkeypatch):
    """Every Phase 3 event the code emits, as (data) dicts, in order."""
    out: list = []

    def _emit(event_type, phase=None, agent=None, **data):
        out.append({"type": event_type, "phase": phase, "agent": agent, **data})

    monkeypatch.setattr(research, "emit_event", _emit)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _QuickAsyncio())
    return out


def _rows(events) -> list:
    """Every activity row sent, in order, with the event that carried it."""
    return [(row, e) for e in events if e["type"] == "agent_progress" and e["phase"] == 3
            for row in (e.get("timeline") or [])]


def _ids(events) -> list:
    return [(r["id"], r["state"]) for r, _ in _rows(events)]


def _row(events, step_id) -> dict:
    found = [r for r, _ in _rows(events) if r["id"] == step_id]
    assert found, f"no {step_id!r} row in {_ids(events)}"
    return found[-1]


def _no_page_text(events):
    """A label or detail is one of ours — never anything a page said."""
    for r, _ in _rows(events):
        for k in ("label", "detail"):
            assert "@" not in str(r.get(k, "")), r


# ═════════════════════════════════════════════════════════════════════════════
# 1. The DOM upload: the notebook made, then each source as it lands
# ═════════════════════════════════════════════════════════════════════════════

def _upload(monkeypatch, sent, start_url, censuses, reach=True):
    page = SimpleNamespace(url=start_url)

    async def _click(pg, patterns, **k):
        if reach:
            pg.url = NB_URL
        return "Create new notebook"

    seen = iter(censuses)

    async def _census(pg, expected):
        try:
            names = next(seen)
        except StopIteration:
            names = set(NAMES)
        return set(names), len(names)

    monkeypatch.setattr(research, "_nlm_click_first", _click)
    monkeypatch.setattr(research, "_nlm_dom_add_files", _true)
    monkeypatch.setattr(research, "_nlm_visible_source_names", _census)
    monkeypatch.setattr(research, "_nlm_close_dialogs", _none)
    return asyncio.run(research._nlm_dom_upload_sources(None, page, FILES))


def test_the_notebook_then_each_source_as_it_lands_in_order(monkeypatch, sent):
    present = _upload(monkeypatch, sent, HOME_URL,
                      [{"gemini.md"}, {"gemini.md", "claude.md"}, set(NAMES)])
    assert present == set(NAMES)
    # ⛔ WHY IT FAILS ON THE OLD CODE: the create was only logged and the census
    # emitted nothing at all.
    assert _ids(sent) == [("notebook", "done"), ("source:gemini.md", "done"),
                          ("source:claude.md", "done"), ("source:chatgpt.md", "done")]
    assert _row(sent, "notebook")["label"] == "Notebook created"
    assert _row(sent, "source:gemini.md")["label"] == "Gemini report added"
    # Each row is on its own event, its label on the line, the stage explicit.
    for r, e in _rows(sent):
        assert e["stage"] == "uploading" and e["progress"] == r["label"]
    _no_page_text(sent)
    # ⛔ And a create that never reached a notebook announces nothing.
    sent.clear()
    assert _upload(monkeypatch, sent, HOME_URL, [], reach=False) == set()
    assert _ids(sent) == []


def test_a_source_seen_twice_is_announced_once(monkeypatch, sent):
    _upload(monkeypatch, sent, HOME_URL, [{"gemini.md"}, {"gemini.md"}, set(NAMES)])
    assert [i for i, _ in _ids(sent)].count("source:gemini.md") == 1


def test_a_notebook_already_open_is_not_announced_as_created(monkeypatch, sent):
    _upload(monkeypatch, sent, NB_URL, [set(NAMES)])
    assert "notebook" not in [i for i, _ in _ids(sent)]
    assert [i for i, _ in _ids(sent)] == ["source:chatgpt.md", "source:gemini.md", "source:claude.md"]


def test_the_persons_own_file_is_named_by_its_own_name(monkeypatch, sent):
    files = [Path("Q3 board notes.pdf")]
    page = SimpleNamespace(url=NB_URL)

    async def _census(pg, expected):
        return set(expected), 1

    monkeypatch.setattr(research, "_nlm_dom_add_files", _true)
    monkeypatch.setattr(research, "_nlm_visible_source_names", _census)
    monkeypatch.setattr(research, "_nlm_close_dialogs", _none)
    asyncio.run(research._nlm_dom_upload_sources(None, page, files))
    assert _row(sent, "source:Q3 board notes.pdf")["label"] == "Q3 board notes.pdf added"


# ═════════════════════════════════════════════════════════════════════════════
# 2. The repair rounds: a source added again says so, and ends done or failed
# ═════════════════════════════════════════════════════════════════════════════

def _repair(monkeypatch, censuses, verdicts=(), cua=None, final=None):
    browser = SimpleNamespace(page=object(), set_upload_file=lambda *a: None,
                              clear_upload_file=lambda: None)
    seen = iter(censuses)

    async def _settled(pg, expected, attempts=4, interval=3.0):
        try:
            return next(seen)
        except StopIteration:
            return final if final is not None else (set(NAMES), 3)

    said = iter(verdicts)

    async def _cua(page, **k):
        return {"text": next(said, "ALL OK")}

    monkeypatch.setattr(research, "_nlm_close_dialogs", _none)
    monkeypatch.setattr(research, "_nlm_census_settled", _settled)
    monkeypatch.setattr(research, "_nlm_dom_add_files", _true)
    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    return asyncio.run(research._verify_and_repair_nlm_sources(browser, cua, FILES))


def test_a_missing_source_is_added_again_then_done(monkeypatch, sent):
    left = _repair(monkeypatch, [({"chatgpt.md", "claude.md"}, 2), (set(NAMES), 3)])
    assert left == set()
    assert _ids(sent) == [("source:gemini.md", "active"), ("source:gemini.md", "done")]
    assert _row(sent, "source:gemini.md")["label"] == "Gemini report added"
    # The "adding it again" row rides the line that already said so.
    active = next(e for r, e in _rows(sent) if r["state"] == "active")
    assert active["progress"] == "Re-adding 1 missing source(s)…"
    assert [r["label"] for r, _ in _rows(sent)][0] == "Adding the Gemini report again"
    # ⛔ And a notebook that was healthy all along sends no repair rows.
    sent.clear()
    assert _repair(monkeypatch, [(set(NAMES), 3)]) == set()
    assert _ids(sent) == []


def test_a_source_that_never_comes_back_ends_failed(monkeypatch, sent):
    gone = ({"chatgpt.md", "claude.md"}, 2)
    left = _repair(monkeypatch, [gone, gone], final=({"chatgpt.md", "claude.md"}, 2))
    assert left == {"gemini.md"}
    assert _ids(sent)[-1] == ("source:gemini.md", "failed")
    assert _row(sent, "source:gemini.md")["label"] == "Gemini report didn't go in"


def test_a_red_source_repaired_by_computer_use_is_done_only_on_the_healthy_verdict(monkeypatch, sent):
    # Text-only census (no rows) → the read-only health check runs.
    left = _repair(monkeypatch, [(set(NAMES), 0), (set(NAMES), 0)],
                   verdicts=["FAILED: gemini.md", "ALL OK"], cua=object())
    assert left == set()
    assert _ids(sent) == [("source:gemini.md", "active"), ("source:gemini.md", "done")]


# ═════════════════════════════════════════════════════════════════════════════
# 3. A resumed run goes back to its notebook
# ═════════════════════════════════════════════════════════════════════════════

def test_going_back_to_the_notebook_says_so_then_shows_what_it_holds(monkeypatch, sent):
    page = SimpleNamespace(url=NB_URL)

    async def _new_tab(url):
        return page

    monkeypatch.setattr(research, "_work_tab_signed_out", _false)
    monkeypatch.setattr(research, "_nlm_census_settled",
                        lambda *a, **k: _ret(({"chatgpt.md", "claude.md"}, 2)))
    monkeypatch.setattr(research, "_count_nlm_audio_cards", lambda *a, **k: _ret(0))
    monkeypatch.setattr(research, "_count_nlm_audio_generating", lambda *a, **k: _ret(1))
    browser = SimpleNamespace(new_tab=_new_tab)
    assert asyncio.run(research._p3_reopen_recorded_notebook(browser, NB_URL, FILES)) is True
    assert _ids(sent) == [("notebook", "active"), ("notebook", "done"),
                          ("source:chatgpt.md", "done"), ("source:claude.md", "done")]
    assert _row(sent, "notebook")["label"] == "Went back to this research's notebook"


def test_a_notebook_that_would_not_open_is_never_marked_gone_back_to(monkeypatch, sent):
    async def _new_tab(url):
        raise RuntimeError("no tab")

    browser = SimpleNamespace(new_tab=_new_tab)
    assert asyncio.run(research._p3_reopen_recorded_notebook(browser, NB_URL, FILES)) is False
    assert _ids(sent) == [("notebook", "active")]


async def _ret(v):
    return v


# ═════════════════════════════════════════════════════════════════════════════
# 4. The upload phase: named, shared — and the computer-use fallback's sources
# ═════════════════════════════════════════════════════════════════════════════

class _Controls:
    skipped_agents: set = set()

    async def interruptible_sleep(self, *a, **k):
        return None

    def is_stop(self):
        return False

    def is_pause(self):
        return False

    async def wait_if_paused(self):
        return None


class _Button:
    async def click(self, *a, **k):
        return None


#: The Share control's selector, as the real extractor asks for it.
_SHARE_SELECTOR = 'button[aria-label*="Share"]'
#: The computer-use jobs the upload phase asked for, by hotspot, in order.
_CUA_ASKED: list = []


def _upload_phase(monkeypatch, tmp_path, dom_uploaded, *, share="set", rename=True, rename_cua="done"):
    """Run the real upload phase. ⭐ The share step is the REAL extractor
    (`extract_notebooklm_url`) driving a fake page — only its dialog helper is
    replaced:

      share="set"      the Share control is there and its dialog presses
                       "Anyone with the link" (the helper answers access_set);
      share="missing"  the Share control is not on the page, and the extractor
                       falls back to the tab's own (notebook) address.

    rename: whether the page's own rename worked; rename_cua: what computer use
    answered when it did not."""
    page = SimpleNamespace(url=HOME_URL, keyboard=SimpleNamespace(press=_none))

    async def _query(sel):
        if _SHARE_SELECTOR in sel:
            return _Button() if share == "set" else None
        return None   # no stale overlay, no dialog

    page.query_selector = _query

    async def _new_tab(url):
        page.url = url
        return page

    async def _current_url():
        return page.url

    browser = SimpleNamespace(page=page, new_tab=_new_tab, current_url=_current_url,
                              set_upload_file=lambda *a: None, clear_upload_file=lambda: None)

    async def _dom_upload(b, pg, md_files, **k):
        if dom_uploaded:
            pg.url = NB_URL
        return set(dom_uploaded)

    _CUA_ASKED.clear()

    async def _cua(pg, **k):
        _CUA_ASKED.append(k.get("hotspot_id"))
        if k.get("hotspot_id") == "nlm-rename":
            return {"status": rename_cua}
        page.url = NB_URL     # computer use made the notebook / added the file
        return {"status": "done"}

    async def _census(pg, names, attempts=4, interval=3.0):
        return set(names), 1

    async def _visible(pg, names):
        return set(), 0

    monkeypatch.setattr(research._runtime, "p2_links_for_p3", {"ChatGPT": "https://chatgpt.com/s/x"})
    monkeypatch.setattr(research._runtime, "p2_md_files_for_p3", list(FILES))
    monkeypatch.setattr(research, "_controls", _Controls())
    monkeypatch.setattr(research, "_work_tab_signed_out", _false)
    monkeypatch.setattr(research, "_nlm_dom_upload_sources", _dom_upload)
    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    monkeypatch.setattr(research, "_nlm_census_settled", _census)
    monkeypatch.setattr(research, "_nlm_visible_source_names", _visible)
    monkeypatch.setattr(research, "_nlm_dom_add_files", _true)
    monkeypatch.setattr(research, "_verify_and_repair_nlm_sources", lambda *a, **k: _ret(set()))
    monkeypatch.setattr(research, "start_narration_ticker", lambda *a, **k: (None, None))
    monkeypatch.setattr(research, "stop_narration_ticker", _none)
    monkeypatch.setattr(research, "smart_title", lambda t: "Fusion economics")
    monkeypatch.setattr(research, "_nlm_dom_rename", _true if rename else _false)
    # The share dialog's own work: it hands back the link and that it pressed
    # "Anyone with the link". Everything around it is the real extractor.
    monkeypatch.setattr(research, "_set_nlm_public_and_get_link",
                        lambda *a, **k: _ret((NB_URL, False, True)))
    monkeypatch.setattr(research, "selfheal", None)
    monkeypatch.setattr(research, "_observe_dom_success", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_validated_link", lambda *a, **k: None)
    return asyncio.run(research.run_phase3_upload(browser, None, {}, "fusion", tmp_path))


def test_the_notebook_is_named_then_shared_with_its_link(monkeypatch, sent, tmp_path):
    out = _upload_phase(monkeypatch, tmp_path, set(NAMES))
    assert out["notebook_url"] == NB_URL
    ids = [i for i, _ in _ids(sent)]
    assert ids.index("renamed") < ids.index("shared")
    assert _row(sent, "renamed")["label"] == "Named “Fusion economics”"
    shared = _row(sent, "shared")
    assert (shared["state"], shared["label"], shared.get("url")) == (
        "done", "Shared: anyone with the link can view", NB_URL)
    for r, e in _rows(sent):
        assert e["stage"] == "notebook"


def test_a_share_that_never_happened_is_not_shown_as_shared(monkeypatch, sent, tmp_path):
    # ⛔⛔ REVIEW (wave 17): the Share control is not on the page, so nothing set
    # "Anyone with the link" — and the REAL extractor still hands back a
    # notebook address: the tab's own. ⛔ WHY IT FAILS ON THE LANE'S CODE: the
    # row was sent for any notebook-shaped address, so this run told the person
    # a possibly private notebook was public.
    out = _upload_phase(monkeypatch, tmp_path, set(NAMES), share="missing")
    assert out["notebook_url"] == NB_URL      # the link is still kept, as before
    assert "shared" not in [i for i, _ in _ids(sent)]
    assert "renamed" in [i for i, _ in _ids(sent)]


def test_the_extractor_says_whether_access_was_set(monkeypatch, sent):
    """The real extractor: access is "set" only when its own share dialog set it.
    A link copied by computer use is kept, but nothing read the access back."""
    monkeypatch.setattr(research, "selfheal", None)
    monkeypatch.setattr(research, "_arm_clipboard", lambda: None)
    monkeypatch.setattr(research, "_read_clipboard_after_copy", lambda *a, **k: _ret((NB_URL, NB_URL)))
    monkeypatch.setattr(research, "_shadow_observed_cua", lambda *a, **k: _ret({"status": "done"}))

    def _browser(has_share):
        async def _query(sel):
            return _Button() if has_share and _SHARE_SELECTOR in sel else None
        page = SimpleNamespace(query_selector=_query, keyboard=SimpleNamespace(press=_none))
        return SimpleNamespace(page=page, current_url=lambda: _ret(NB_URL))

    for answer, expected in (((NB_URL, False, True), True), ((NB_URL, False, False), False)):
        monkeypatch.setattr(research, "_set_nlm_public_and_get_link", lambda *a, _v=answer, **k: _ret(_v))
        res = asyncio.run(research.extract_notebooklm_url(_browser(True), cua_client=None))
        assert (res.url, res.access_set) == (NB_URL, expected)
    # The Share control missing, computer use copies the link: the link is
    # kept, and access is NOT claimed — nothing read it back.
    res = asyncio.run(research.extract_notebooklm_url(_browser(False), cua_client=object()))
    assert (res.url, res.access_set) == (NB_URL, False)
    # The tab's own address, with no computer use at all.
    res = asyncio.run(research.extract_notebooklm_url(_browser(False), cua_client=None))
    assert (res.url, res.access_set) == (NB_URL, False)
    # ⭐ And the plain result keeps its old default: no access claimed.
    assert research.LinkResult(url=NB_URL).access_set is False


def test_a_rename_that_failed_does_not_name_the_notebook(monkeypatch, sent, tmp_path):
    # ⛔⛔ REVIEW (wave 17): the page's rename failed and so did computer use.
    # ⛔ WHY IT FAILS ON THE LANE'S CODE: "Named “…”" was sent however the
    # rename ended.
    for answer in ("failed", "max_iterations", "error", "stopped"):
        sent.clear()
        _upload_phase(monkeypatch, tmp_path, set(NAMES), rename=False, rename_cua=answer)
        assert "renamed" not in [i for i, _ in _ids(sent)], answer
        assert "shared" in [i for i, _ in _ids(sent)]
        assert "nlm-rename" in _CUA_ASKED
    # …and when computer use did rename it (or Vision did), it is named.
    for answer in ("done", "vision_success"):
        sent.clear()
        _upload_phase(monkeypatch, tmp_path, set(NAMES), rename=False, rename_cua=answer)
        assert _row(sent, "renamed")["label"] == "Named “Fusion economics”", answer
    # ⭐ The page's own rename worked: named, and computer use is never asked —
    # so its answer, whatever it would have been, cannot unname it.
    sent.clear()
    _upload_phase(monkeypatch, tmp_path, set(NAMES), rename=True, rename_cua="failed")
    assert _row(sent, "renamed")["label"] == "Named “Fusion economics”"
    assert "nlm-rename" not in _CUA_ASKED


def test_the_fallback_confirms_each_source_and_announces_the_notebook_once(monkeypatch, sent, tmp_path):
    _upload_phase(monkeypatch, tmp_path, set())
    ids = [i for i, _ in _ids(sent)]
    assert ids[:4] == ["notebook", "source:chatgpt.md", "source:gemini.md", "source:claude.md"]
    assert ids.count("notebook") == 1
    assert _row(sent, "source:claude.md")["label"] == "Claude report added"


def test_the_fallback_does_not_announce_a_notebook_the_dom_path_already_did(monkeypatch, sent, tmp_path):
    # The DOM path took two files; computer use adds the third.
    _upload_phase(monkeypatch, tmp_path, {"chatgpt.md", "gemini.md"})
    ids = [i for i, _ in _ids(sent)]
    assert "notebook" not in ids
    assert ids[0] == "source:claude.md"


# ═════════════════════════════════════════════════════════════════════════════
# 5. The podcast: the setting read back, made, ticking, ready
# ═════════════════════════════════════════════════════════════════════════════

class _Reached(Exception):
    pass


class _Page:
    async def reload(self, *a, **k):
        return None

    def is_closed(self):
        return False

    def on(self, *a, **k):
        return None


def _podcast(monkeypatch, tmp_path, dom_gen, cards=0, complete_after=1):
    polls = {"n": 0}

    async def _complete(pg):
        polls["n"] += 1
        return polls["n"] > complete_after

    async def _pick(*a, **k):
        raise _Reached()

    async def _url():
        return NB_URL

    async def _gen(pg, length):
        return dict(dom_gen)

    monkeypatch.setattr(research, "_controls", _Controls())
    monkeypatch.setattr(research, "_work_tab_signed_out", _false)
    monkeypatch.setattr(research, "_count_nlm_audio_cards", lambda *a, **k: _ret(cards))
    monkeypatch.setattr(research, "_count_nlm_audio_generating", lambda *a, **k: _ret(1))
    monkeypatch.setattr(research, "_check_audio_generating", _false)
    monkeypatch.setattr(research, "_open_nlm_audio_customize", _true)
    monkeypatch.setattr(research, "_nlm_customise_and_generate", _gen)
    monkeypatch.setattr(research, "_dump_nlm_audio_dom", _none)
    monkeypatch.setattr(research, "_observe_dom_success", lambda *a, **k: None)
    monkeypatch.setattr(research, "start_narration_ticker", lambda *a, **k: (None, None))
    monkeypatch.setattr(research, "stop_narration_ticker", _none)
    monkeypatch.setattr(research, "_shadow_observed_cua", lambda *a, **k: _ret({"text": "generating"}))
    monkeypatch.setattr(research, "wait_until_verified", lambda *a, **k: _ret(True))
    monkeypatch.setattr(research, "_browser_context_is_dead", _false)
    monkeypatch.setattr(research, "_check_audio_complete_dom", _complete)
    monkeypatch.setattr(research, "_pick_nlm_audio_card", _pick)
    browser = SimpleNamespace(page=_Page(), current_url=_url)
    with pytest.raises(_Reached):
        asyncio.run(research.run_phase3_audio.__wrapped__(
            browser, None, NB_URL, tmp_path, podcast_length="long"))


READ_BACK = {"generated": True, "pressed": True, "format": "Deep dive", "length": "Long", "reason": ""}


def test_the_setting_as_read_back_then_making_ticking_and_ready(monkeypatch, sent, tmp_path):
    _podcast(monkeypatch, tmp_path, READ_BACK)
    # ⛔ WHY IT FAILS ON THE OLD CODE: the read-back setting, "ready" and the
    # start were log lines only; the tick sent words and no row.
    assert _ids(sent) == [("setting", "done"), ("podcast", "active"), ("podcast", "active"),
                          ("podcast", "done")]
    assert _row(sent, "setting")["detail"] == "Deep dive · Long"
    lo, hi = research._AUDIO_TYPICAL_RANGE_MIN["long"]
    tick = [r for r, _ in _rows(sent) if r["id"] == "podcast"][1]
    assert tick["detail"] == f"5 min so far · usually {lo}–{hi} min"
    assert _row(sent, "podcast")["label"] == "Podcast ready"
    for _, e in _rows(sent):
        assert e["stage"] == "podcast"
    # The tick still says what it always said on the line.
    tick_event = [e for r, e in _rows(sent) if r is tick][0]
    assert tick_event["progress"].startswith("NotebookLM still generating audio overview…")


def test_no_setting_is_claimed_when_the_page_never_read_one_back(monkeypatch, sent, tmp_path):
    # The page could not finish Customise; computer use generated instead.
    _podcast(monkeypatch, tmp_path, {"generated": False, "pressed": False,
                                     "format": "Deep dive", "length": "Long", "reason": "x"})
    ids = [i for i, _ in _ids(sent)]
    assert "setting" not in ids
    assert ("podcast", "active") in _ids(sent)


def test_a_podcast_already_there_is_ready_without_being_made(monkeypatch, sent, tmp_path):
    _podcast(monkeypatch, tmp_path, READ_BACK, cards=1, complete_after=0)
    assert _ids(sent) == [("podcast", "done")]


# ═════════════════════════════════════════════════════════════════════════════
# 6. Saved where the app plays it from
# ═════════════════════════════════════════════════════════════════════════════

def _publish(monkeypatch, tmp_path, stored="https://firebasestorage.googleapis.com/v0/b/x/o/pod.mp3", rid="chat_1"):
    audio = tmp_path / "pod.mp3"
    audio.write_bytes(b"ID3")
    monkeypatch.setattr(research, "_audio_duration_sec", lambda p: 60)
    monkeypatch.setattr(research, "upload_audio_to_storage", lambda p: stored)
    monkeypatch.setattr(research, "save_audio_to_firestore", lambda *a, **k: None)
    monkeypatch.setattr(research, "update_link_in_firestore", lambda *a, **k: None)
    monkeypatch.setattr(research, "smart_title", lambda t: "Fusion")
    return asyncio.run(research._p3_publish_audio(audio, rid))


def test_the_podcast_saved_is_the_last_card(monkeypatch, sent, tmp_path):
    assert _publish(monkeypatch, tmp_path)
    assert _ids(sent) == [("podcast_saved", "done")]
    assert _row(sent, "podcast_saved")["label"] == "Podcast saved to your research"
    assert _rows(sent)[0][1]["stage"] == "podcast"
    # ⛔ A podcast that did not reach Storage is never "saved"…
    sent.clear()
    assert _publish(monkeypatch, tmp_path, stored="") == ""
    assert _ids(sent) == []
    # ⛔ …and a run that keeps nothing saves nothing and says nothing.
    monkeypatch.setattr(research, "_is_incognito_research", lambda rid: True)
    assert _publish(monkeypatch, tmp_path) == ""
    assert _ids(sent) == []


# ═════════════════════════════════════════════════════════════════════════════
# 7. The row's shape — what the app's fold accepts
# ═════════════════════════════════════════════════════════════════════════════

def test_a_row_carries_only_what_it_was_given_and_is_bounded():
    row = research._p3_timeline_step("x" * 300, "y" * 300, "active")
    assert set(row) == {"id", "label", "state", "at"}
    assert len(row["id"]) == 100 and len(row["label"]) == 160
    assert isinstance(row["at"], int) and row["at"] > 1_700_000_000_000
    full = research._p3_timeline_step("shared", "Shared", detail="d" * 300, url=NB_URL)
    assert full["url"] == NB_URL and len(full["detail"]) == 160
