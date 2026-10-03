"""Wave 19 — one short name for the research, made once from the topic.

The owner (10-02): the chat's title, the NotebookLM notebook, the podcast (file
and title) and the YouTube video carry ONE short name — "a few words
meaningfully making the research's name, not too many" — made once from the
topic and reused everywhere.

⛔⛔ WHAT WAS MEASURED (10-02). The computer named the research a SECOND time
after Phase 2, from its findings, and wrote over the chat's name; the notebook
took the second one ('Renaming notebook (smart title, 52 chars)'). The podcast
file was NotebookLM's name cut at 40 characters
('OpenAI_Decisions_API_versus_TypeSafe_Jev'), or a random id when the fallback
scan found it. A run started from the chat assistant had its WHOLE topic as its
title until that second naming.

⭐ What holds now, each through the code that does it:
  · Phase 2's end renames nothing — the record keeps the chat's name;
  · the notebook, the podcast row and the podcast FILE take that same name —
    lifted from the real call sites in `run_phase3_upload` /
    `run_phase3_audio` and executed;
  · a research nobody named yet (the chat assistant's, or a web run whose tab
    closed) is named ONCE, by the web's namer, with a five-word fallback;
  · the person's own rename wins; a run that keeps nothing asks no one;
  · the podcast's name never reaches the computer's log.

⭐ And from the review (10-02), each measured on 34d980c:
  · the end of Phase 2 names a research still on "New Research" — with the
    podcast off nothing after it does;
  · only the chat assistant's record (`viaAgent`) counts its topic as no
    name — a web research named like its short topic is never asked again;
  · the chat's opening line takes the name at pick-up, not the topic;
  · no test reaches this computer's real sign-in (conftest's guard).

Run:  pytest tests/test_one_short_name_w19.py -v
"""
import ast
import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

import research

#: Read before any test points `research.__file__` somewhere else.
_SOURCE = Path(research.__file__).resolve()

UID = "uid-alice-w19-0000000000000001"
RID = "chat_1790000000019_1"
TOPIC = ("OpenAI's new Decisions API versus TypeSafe Jev for structured outputs:\n"
         "what changes for a team shipping agents next quarter?\n"
         "Links: https://example.com/a https://example.com/b")
CHAT_NAME = "Decisions API vs TypeSafe Jev"


class _Store:
    """`users/{uid}/researches/{rid}` — reads answered from `records`; every
    `.update()` on any document (the chat's messages included) recorded in
    `updates` as (path, data)."""

    def __init__(self, records):
        self.records = dict(records)
        self.reads, self.writes, self.updates = [], [], []

    def collection(self, name):
        return _Node(self, (name,))


class _Node:
    def __init__(self, store, path):
        self._s, self.path = store, path

    def collection(self, name):
        return _Node(self._s, self.path + (name,))

    def document(self, name):
        return _Node(self._s, self.path + (name,))

    def get(self):
        self._s.reads.append(self.path)
        key = (self.path[1], self.path[3]) if len(self.path) >= 4 else None
        data = self._s.records.get(key)
        return types.SimpleNamespace(exists=data is not None,
                                     to_dict=lambda: dict(data or {}))

    def update(self, data):
        self._s.updates.append(("/".join(self.path), dict(data)))


#: The chat assistant's record of a research it started (agent/facade/bridge.py
#: `_new_research_fields`): its title IS its whole topic, and it says so.
AGENT_RECORD = {"title": TOPIC, "topic": TOPIC, "viaAgent": True}
#: Where the chat's opening line lives (`seed_chat_messages`, `intro-{rid}`).
INTRO = f"users/{UID}/researches/{RID}/messages/intro-{RID}"


@pytest.fixture
def world(monkeypatch):
    """A record, the web's namer and the writes, all recorded."""
    w = types.SimpleNamespace(asked=[], wrote=[], logs=[])
    w.store = _Store({(UID, RID): {"title": CHAT_NAME, "topic": TOPIC}})
    monkeypatch.setattr(research, "_firebase_db", w.store)
    monkeypatch.setattr(research, "_RESEARCH_NAMES_MADE", {})
    monkeypatch.setattr(research, "_ask_web_namer",
                        lambda topic: w.asked.append(topic) or "Decisions API Versus Jev")
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, p: w.wrote.append((u, r, dict(p))) or True)
    # The device's own id on every write it makes (`_be_payload`), stated.
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "dev-w19"})
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: w.logs.append(str(msg)))
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)

    def _set(**rec):
        w.store.records[(UID, RID)] = rec
    w.set = _set
    return w


# ══ the real call sites, lifted and executed ═════════════════════════════════

def _fn(name):
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    return next(n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _compile(params, stmts, ret):
    """`async def _lifted(<params>): <stmts>; return <ret>`, against research's
    own globals — the real names the real statements call."""
    body = "\n".join("    " + line for s in stmts for line in ast.unparse(s).splitlines())
    src = f"async def _lifted({', '.join(params)}):\n{body}\n    return {ret}\n"
    code = compile(src, str(_SOURCE), "exec")
    inner = next(c for c in code.co_consts if isinstance(c, types.CodeType))
    return types.FunctionType(inner, research.__dict__, "_lifted")


def _notebook_title_site():
    """The `title = …` the notebook rename types — the statement just before the
    'Renaming notebook' line in `run_phase3_upload`."""
    fn = _fn("run_phase3_upload")
    for node in ast.walk(fn):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for i, s in enumerate(body):
            if (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                    and getattr(s.value.func, "id", "") == "log"
                    and "Renaming notebook" in ast.unparse(s.value.args[0])):
                assigns = [b for b in body[:i] if isinstance(b, ast.Assign)
                           and any(getattr(t, "id", "") == "title" for t in b.targets)]
                return _compile(["topic"], [assigns[-1]], "title")
    raise AssertionError("the notebook rename is not where it was")


def _podcast_file_site():
    """The block in `run_phase3_audio` that hands the podcast to the mp3
    transcode — everything the fresh Phase 3 does to the file before it."""
    fn = _fn("run_phase3_audio")
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and any(
                isinstance(c, ast.Call) and "_transcode_audio_to_mp3" in ast.unparse(c)
                for c in ast.walk(node)) and "audio_path.exists()" in ast.unparse(node.test):
            return _compile(["audio_path", "queue_dir"], [node], "audio_path")
    raise AssertionError("the podcast's transcode is not where it was")


# ══ 1. Phase 2's end renames nothing ═════════════════════════════════════════

class _Threads:
    started: list = []

    def __init__(self, target=None, args=(), kwargs=None, name=None, daemon=None):
        self.name = name

    def start(self):
        _Threads.started.append(self.name)


def test_the_end_of_phase_2_renames_nothing(world, monkeypatch, tmp_path):
    """⛔⛔ THE MEASURED DEFECT. The after-Phase-2 rename started a thread that
    named the research from its findings and wrote over the chat's name."""
    monkeypatch.setattr(_Threads, "started", [])
    monkeypatch.setattr(research, "_threading", types.SimpleNamespace(Thread=_Threads))
    monkeypatch.setattr(research, "save_document_to_firestore", lambda *a, **k: True)

    async def _rehost(text, label=None, **kw):
        return text
    monkeypatch.setattr(research, "_rehost_document_images", _rehost)
    monkeypatch.setattr(research, "_runtime", types.SimpleNamespace(
        agent_findings={}, agent_progress_snapshots={}), raising=False)
    (tmp_path / "documents").mkdir()
    results = {"ChatGPT": {"text": "## A\n\nThe Decisions API ships next month.\n",
                           "status": "done"},
               "Claude": {"text": "## B\n\nTypeSafe Jev validates at the edge.\n",
                          "status": "done"}}
    asyncio.run(research._p2_persist_reports(results, tmp_path, TOPIC, "a brief"))
    assert "research-summary" in _Threads.started, "the drive never reached the dispatch"
    assert "research-title-refresh" not in _Threads.started, (
        "Phase 2's end named the research again, from its findings")
    assert not [p for _u, _r, p in world.wrote if "title" in p]


# ══ 2. the notebook, the podcast row and the podcast file take the name ══════

def test_the_notebook_is_named_what_the_chat_shows(world):
    assert asyncio.run(_notebook_title_site()(TOPIC)) == CHAT_NAME
    assert world.asked == [], "the web was asked to name a research already named"


def test_an_agent_started_research_gets_its_short_name_on_the_notebook(world):
    """The chat assistant creates its research with `title: topic` — the whole
    paragraph — and on 10-02 the notebook got 52 characters of it."""
    world.set(**AGENT_RECORD)
    name = asyncio.run(_notebook_title_site()(TOPIC))
    assert name == "Decisions API Versus Jev"
    assert world.asked == [TOPIC]
    assert [(u, r, p["title"]) for u, r, p in world.wrote] == [
        (UID, RID, "Decisions API Versus Jev")]


def test_the_podcast_file_takes_the_name_whatever_notebooklm_called_it(
        world, monkeypatch, tmp_path):
    """⛔⛔ 'OpenAI_Decisions_API_versus_TypeSafe_Jev' (NotebookLM's) and a
    random id (the fallback scan's) were both measured. The file — and so the
    Storage object, the `audios` row and the share link — carries the name."""
    seen = []
    monkeypatch.setattr(research, "_transcode_audio_to_mp3",
                        lambda p, title="": seen.append((p.name, title)) or p)
    (tmp_path / "podcasts").mkdir()
    nlm = tmp_path / "podcasts" / "The_AI_that_refuses_to_speak.m4a"
    nlm.write_bytes(b"audio")
    out = asyncio.run(_podcast_file_site()(nlm, tmp_path))
    assert out.name == "Decisions_API_vs_TypeSafe_Jev.m4a"
    assert out.exists() and not nlm.exists()
    assert seen == [("Decisions_API_vs_TypeSafe_Jev.m4a", CHAT_NAME)], (
        "the mp3 was not handed the name to carry inside it")


def test_the_podcast_row_shows_the_name_not_the_whole_topic(world, monkeypatch, tmp_path):
    """The Podcasts page row: an agent-shaped record (title = whole topic) is
    named once and the row shows the short name."""
    world.set(**AGENT_RECORD)
    (tmp_path / "checkpoint.json").write_text(json.dumps({"topic": TOPIC}),
                                              encoding="utf-8")
    (tmp_path / "podcasts").mkdir()
    audio = tmp_path / "podcasts" / "Decisions_API_Versus_Jev.mp3"
    audio.write_bytes(b"audio")
    rows = []
    monkeypatch.setattr(research, "upload_audio_to_storage", lambda p: "https://s/a.mp3")
    monkeypatch.setattr(research, "save_audio_to_firestore", lambda *a: rows.append(a))
    monkeypatch.setattr(research, "update_link_in_firestore", lambda *a, **k: None)
    monkeypatch.setattr(research, "_audio_duration_sec", lambda p: 600)
    assert asyncio.run(research._p3_publish_audio(audio, RID)) == "https://s/a.mp3"
    assert [(r[0], r[1]) for r in rows] == [(audio.stem, "Decisions API Versus Jev")]


def test_a_podcast_name_with_nothing_file_safe_left_is_podcast(tmp_path):
    p = tmp_path / "x.m4a"
    p.write_bytes(b"a")
    assert research._p3_name_podcast_file(p, "???").name == "podcast.m4a"


def test_the_mp3_carries_the_name_as_its_title(monkeypatch, tmp_path):
    ran = []

    def _run(args, **_k):
        ran.append(args)
        Path(args[-1]).write_bytes(b"mp3")
        return types.SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(research.subprocess, "run", _run)
    src = tmp_path / "Decisions_API_vs_TypeSafe_Jev.m4a"
    src.write_bytes(b"m4a")
    out = research._transcode_audio_to_mp3(src, title="Decisions API vs\nTypeSafe Jev")
    assert out.suffix == ".mp3"
    args = ran[0]
    at = args.index("-metadata")
    assert args[at + 1] == "title=Decisions API vs TypeSafe Jev"
    assert args.index("-map_metadata") < at, "the name must override NotebookLM's own"
    # And the resume path, which passes none, keeps what is there.
    src.write_bytes(b"m4a")
    research._transcode_audio_to_mp3(src)
    assert "-metadata" not in ran[1]


# ══ 3. naming a research nobody named yet ════════════════════════════════════

@pytest.mark.parametrize("placeholder", ["", "New Research", "New Chat", "new research"])
def test_a_placeholder_is_not_a_name(world, placeholder):
    world.set(title=placeholder, topic=TOPIC)
    assert research._research_name(TOPIC, UID, RID) == "Decisions API Versus Jev"
    assert world.asked == [TOPIC]


def test_the_persons_own_rename_wins_even_when_it_is_the_topic(world):
    world.set(**AGENT_RECORD, titleLocked=True)
    assert research._research_name(TOPIC, UID, RID) == TOPIC.strip()
    assert world.asked == [] and world.wrote == []


def test_a_name_is_made_once(world):
    world.set(title="New Research")
    first = research._research_name(TOPIC, UID, RID)
    world.set(title="New Research")      # the write-back did not land
    assert research._research_name(TOPIC, UID, RID) == first
    assert len(world.asked) == 1


def test_an_unreadable_record_is_named_but_never_written(world, monkeypatch):
    class _Down:
        def collection(self, _n):
            raise TimeoutError("DeadlineExceeded")
    monkeypatch.setattr(research, "_firebase_db", _Down())
    assert research._research_name(TOPIC, UID, RID) == "Decisions API Versus Jev"
    assert world.wrote == []


def test_when_the_web_cannot_answer_the_topics_first_words_name_it(world, monkeypatch):
    monkeypatch.setattr(research, "_ask_web_namer", lambda topic: "")
    world.set(title="New Research")
    assert research._research_name(TOPIC, UID, RID) == "OpenAI's new Decisions API versus"


def test_a_computer_not_connected_to_the_app_asks_no_one(world, monkeypatch):
    """No Firestore (a terminal run): no sign-in to ask the app with, so the
    topic's first words name it — and nothing reaches for the keystore."""
    monkeypatch.setattr(research, "_firebase_db", None)
    assert research._research_name(TOPIC, UID, RID) == "OpenAI's new Decisions API versus"
    assert world.asked == [] and world.wrote == []


def test_a_podcast_with_no_name_to_take_keeps_its_own(tmp_path):
    p = tmp_path / "The_AI_that_refuses_to_speak.m4a"
    p.write_bytes(b"a")
    assert research._p3_name_podcast_file(p, "  ") == p and p.exists()


def test_the_names_shape(world):
    """Owner question 1, the recommendation taken: two to five words, about
    forty characters, never cut in the middle of a word."""
    shape = research._shape_research_name
    assert shape('"The Global Market For Small Modular Nuclear Reactors."') == \
        "The Global Market For Small"
    assert shape("Supercalifragilistic Expialidocious Hyperventilation Words") == \
        "Supercalifragilistic Expialidocious"
    assert len(shape("a " * 40)) <= 40
    assert shape("x" * 60) == "x" * 40
    assert shape("Line one\nline two") == "Line one line two"
    assert shape("") == ""
    assert research._research_name_from_topic("# Research Brief\n\nSecond line") == \
        "Research Brief"


@pytest.mark.real_sign_in("_ask_web_namer")
def test_the_computer_asks_the_web_namer_with_its_own_sign_in(monkeypatch):
    sent = []

    def _post(url, headers=None, json=None, timeout=None):
        sent.append((url, headers, json, timeout))
        return types.SimpleNamespace(status_code=200, json=lambda: {
            "title": "Commercial Fusion Energy Outlook For The Next Decade"})
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=_post))
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    from auth.v2_flow import FE_BASE_URL
    assert research._ask_web_namer("fusion?") == "Commercial Fusion Energy Outlook For"
    assert sent == [(f"{FE_BASE_URL}/api/title", {"Authorization": "Bearer tok"},
                     {"topic": "fusion?"}, research._RESEARCH_NAME_TIMEOUT_S)]
    assert research._RESEARCH_NAME_TIMEOUT_S == 10


@pytest.mark.real_sign_in("_ask_web_namer")
@pytest.mark.parametrize("answer", [
    types.SimpleNamespace(status_code=500, json=lambda: {"fallback": True}),
    TimeoutError("read timed out"),
])
def test_a_namer_that_cannot_answer_says_nothing_of_the_topic(monkeypatch, answer):
    logs = []

    def _post(*_a, **_k):
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=_post))
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    assert research._ask_web_namer("my divorce settlement options") == ""
    assert logs and not any("divorce" in m for m in logs)


@pytest.mark.real_sign_in("_ask_web_namer")
def test_no_sign_in_no_question(monkeypatch):
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setitem(sys.modules, "requests", None)
    assert research._ask_web_namer("anything") == ""


# ══ 4. at pick-up: only the chat assistant's research is named ═══════════════

def test_at_pick_up_an_agent_started_research_is_named(world):
    world.set(**AGENT_RECORD)
    assert research._name_an_agent_started_run(UID, RID, TOPIC) == "Decisions API Versus Jev"
    assert [p["title"] for _u, _r, p in world.wrote] == ["Decisions API Versus Jev"]


@pytest.mark.parametrize("rec", [
    {"title": "New Research"},            # the web is naming it — nothing races
    {"title": CHAT_NAME},                 # already named
    {**AGENT_RECORD, "titleLocked": True},
    {"title": TOPIC, "topic": TOPIC},     # a WEB record named like its topic
    None,                                 # no record
])
def test_at_pick_up_nothing_else_is_named(world, rec):
    if rec is None:
        world.store.records.clear()
    else:
        world.set(**rec)
    assert research._name_an_agent_started_run(UID, RID, TOPIC) == ""
    assert world.asked == [] and world.wrote == []
    assert world.store.updates == [], "a chat's opening line was rewritten"


# ══ 4b. a web research named exactly like its topic IS named (review) ════════

SHORT = "Quantum Computing"


def test_a_web_research_named_like_its_topic_is_never_asked_again(world):
    """⛔⛔ MEASURED (review, 10-02): {topic: 'Quantum Computing', title: 'Quantum
    Computing'} with no `viaAgent` was taken for the chat assistant's record —
    asked again at pick-up, the chat's name written over mid-run, and asked
    again by every later process because the title still equalled the topic."""
    world.set(title=SHORT, topic=SHORT)
    assert research._name_an_agent_started_run(UID, RID, SHORT) == ""
    for _process in range(2):                 # a later process: an empty cache
        research._RESEARCH_NAMES_MADE.clear()
        assert research._research_name(SHORT, UID, RID) == SHORT
    asyncio.run(_notebook_title_site()(SHORT))
    assert world.asked == [] and world.wrote == []


def test_the_assistants_record_named_like_its_short_topic_is_still_named(world):
    """The other side of the same line: the assistant's record of a short topic
    is its topic too, and it has no web page to name it."""
    world.set(title=SHORT, topic=SHORT, viaAgent=True)
    assert research._name_an_agent_started_run(UID, RID, SHORT) == "Decisions API Versus Jev"
    assert world.asked == [SHORT]


# ══ 4c. the chat's opening line says the name, not the topic (review) ════════

def test_at_pick_up_the_chats_opening_line_takes_the_name(world):
    """⛔ MEASURED (review): the assistant seeds `Researching **"<the first 100
    characters of the topic>…"**`, and only a web tab open at the first
    phase_start rewrote it. The same id and the same words the web writes."""
    world.set(**AGENT_RECORD)
    research._name_an_agent_started_run(UID, RID, TOPIC)
    assert world.store.updates == [
        (INTRO, {"content": 'Researching **"Decisions API Versus Jev"**',
                 "deviceId": "dev-w19"})]


def test_an_opening_line_that_cannot_be_written_leaves_the_name_made(world, monkeypatch):
    """No intro to update (the assistant's seeding is best-effort) is a WARN
    line with no name in it, and the name stands."""
    def _gone(self, data):
        raise LookupError("404 No document to update")
    monkeypatch.setattr(_Node, "update", _gone)
    world.set(**AGENT_RECORD)
    assert research._name_an_agent_started_run(UID, RID, TOPIC) == "Decisions API Versus Jev"
    warned = [m for m in world.logs if "opening line" in m]
    assert warned and not any("Decisions" in m or "OpenAI" in m for m in warned)


def test_no_name_made_leaves_the_opening_line_alone(world, monkeypatch):
    """A topic with no words left to name it by, and a namer that cannot
    answer: no name, and no `Researching **""**`."""
    monkeypatch.setattr(research, "_ask_web_namer", lambda topic: "")
    world.set(title="###", topic="###", viaAgent=True)
    assert research._name_an_agent_started_run(UID, RID, "###") == ""
    assert world.store.updates == []


def test_a_run_that_keeps_nothing_has_no_opening_line_rewritten(world):
    incog = "incog_1790831743868_4"
    world.store.records[(UID, incog)] = dict(AGENT_RECORD)
    research._name_an_agent_started_run(UID, incog, TOPIC)
    assert world.store.updates == [] and world.asked == []


# ══ 4d. the end of Phase 2 names a research still without one (review) ═══════

def _persist(monkeypatch, tmp_path, topic):
    """The REAL `_p2_persist_reports`, its writes stubbed, with two reports."""
    monkeypatch.setattr(research, "save_document_to_firestore", lambda *a, **k: True)
    monkeypatch.setattr(research, "_generate_research_summary_async", lambda *a, **k: None)

    async def _rehost(text, label=None, **kw):
        return text
    monkeypatch.setattr(research, "_rehost_document_images", _rehost)
    monkeypatch.setattr(research, "_runtime", types.SimpleNamespace(
        agent_findings={}, agent_progress_snapshots={}), raising=False)
    (tmp_path / "documents").mkdir(exist_ok=True)
    results = {"ChatGPT": {"text": "## A\n\nThe Decisions API ships next month.\n",
                           "status": "done"},
               "Claude": {"text": "## B\n\nTypeSafe Jev validates at the edge.\n",
                          "status": "done"}}
    asyncio.run(research._p2_persist_reports(results, tmp_path, topic, "a brief"))


@pytest.mark.parametrize("placeholder", ["New Research", "New Chat", ""])
def test_the_end_of_phase_2_names_a_research_still_without_a_name(
        world, monkeypatch, tmp_path, placeholder):
    """⛔⛔ MEASURED (review, 10-02): with the podcast off nothing after Phase 2
    names a research, so a "New Research" record (a two-letter topic the web
    never sends to its namer; a tab closed before the answer) kept it for good —
    and Phase 5 put it into the mail and the share links. The old after-Phase-2
    rename fixed this case; the name now comes from the topic, once."""
    world.set(title=placeholder, topic=TOPIC)
    _persist(monkeypatch, tmp_path, TOPIC)
    assert world.asked == [TOPIC]
    assert [(u, r, p["title"]) for u, r, p in world.wrote] == [
        (UID, RID, "Decisions API Versus Jev")]


def test_the_end_of_phase_2_names_the_assistants_record_its_pick_up_missed(
        world, monkeypatch, tmp_path):
    world.set(**AGENT_RECORD)
    _persist(monkeypatch, tmp_path, TOPIC)
    assert [p["title"] for _u, _r, p in world.wrote] == ["Decisions API Versus Jev"]


def test_a_naming_failure_never_fails_phase_2(world, monkeypatch, tmp_path):
    def _boom(*_a):
        raise RuntimeError("the record went away")
    monkeypatch.setattr(research, "_name_a_research_left_unnamed", _boom)
    _persist(monkeypatch, tmp_path, TOPIC)
    assert any("naming after Phase 2 failed (RuntimeError)" in m for m in world.logs)


def test_a_two_letter_topic_the_web_cannot_name_is_named_by_its_words(
        world, monkeypatch, tmp_path):
    monkeypatch.setattr(research, "_ask_web_namer",
                        lambda topic: world.asked.append(topic) or "")
    world.set(title="New Research", topic="AI")
    _persist(monkeypatch, tmp_path, "AI")
    assert [p["title"] for _u, _r, p in world.wrote] == ["AI"]


@pytest.mark.parametrize("rec", [
    {"title": CHAT_NAME},                          # named — the measured defect's other half
    {"title": "New Research", "titleLocked": True},  # the person's own choice
    {"title": SHORT, "topic": SHORT},              # a web record named like its topic
    None,                                          # no record to read
])
def test_the_end_of_phase_2_names_nothing_else(world, monkeypatch, tmp_path, rec):
    if rec is None:
        world.store.records.clear()
    else:
        world.set(**rec)
    _persist(monkeypatch, tmp_path, SHORT if rec and rec.get("topic") == SHORT else TOPIC)
    assert world.asked == [] and world.wrote == []


# ══ 4e. no test reaches this computer's real sign-in (review) ════════════════

def _nothing_real_under_the_namer(monkeypatch):
    """The keystore and the network, stubbed UNDER the helpers — so a guard
    that failed would show here as a reach that did not register, never as a
    real sign-in read or a real POST."""
    from auth import keystore
    touched = []
    monkeypatch.setattr(keystore, "install_uuid",
                        lambda: touched.append("install_uuid") or "probe")
    monkeypatch.setattr(keystore, "try_recover",
                        lambda *_a: touched.append("try_recover"))
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(
        post=lambda *a, **k: touched.append("post")))
    return touched


def test_a_test_that_forgets_the_namer_reaches_the_guard_not_the_sign_in(
        monkeypatch, live_sign_in_reached):
    touched = _nothing_real_under_the_namer(monkeypatch)
    monkeypatch.setattr(research, "_firebase_db",
                        _Store({(UID, RID): {"title": "New Research"}}))
    monkeypatch.setattr(research, "_RESEARCH_NAMES_MADE", {})
    monkeypatch.setattr(research, "_update_research_doc", lambda *a, **k: True)
    assert research._research_name(TOPIC, UID, RID) == "OpenAI's new Decisions API versus"
    assert [name for name, _where in live_sign_in_reached] == ["_ask_web_namer"]
    assert touched == []
    live_sign_in_reached.clear()      # reached on purpose: this is the guard's test


@pytest.mark.real_sign_in("_ask_web_namer")
def test_the_real_namer_in_a_test_reaches_the_guard_not_the_token(
        monkeypatch, live_sign_in_reached):
    touched = _nothing_real_under_the_namer(monkeypatch)
    assert research._ask_web_namer("Grid storage") == ""
    assert [name for name, _where in live_sign_in_reached] == ["_fresh_user_mode_id_token"]
    assert touched == []
    live_sign_in_reached.clear()


def test_a_test_that_forgets_the_namer_fails():
    """The consumer is pytest itself: a test that forgets the stub must FAIL,
    naming the helper. `tests/_live_sign_in_probe.py` is that test, run in a
    child pytest (its underscore keeps it out of the ordinary run)."""
    import os
    import subprocess
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/_live_sign_in_probe.py", "-q",
         "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(root)}, timeout=300)
    out = r.stdout + r.stderr
    assert "1 passed, 1 error" in out, out[-3000:]
    assert "_ask_web_namer was reached UNSTUBBED" in out, out[-3000:]
    assert "_research_name" in out, "the failure does not say where it was reached from"


class _FakeBrowser:
    def __init__(self, *a, **k):
        self.context = None

    async def start(self):
        return None

    async def close(self):
        return None


def test_the_pipeline_names_an_agent_started_run_when_it_picks_it_up(
        world, monkeypatch, tmp_path):
    """The consumer: the REAL `run_pipeline`, stopped at its first phase — the
    tile's name AND the chat's opening line."""
    world.set(**AGENT_RECORD)
    queue_dir = tmp_path / "Agent_run_20261002_051554"
    (queue_dir / "documents").mkdir(parents=True)
    for name, value in (("resolve_api_key", lambda _k: "k"),
                        ("_capture_anthropic_attribution", lambda *a, **k: None),
                        ("clear_clipboard", lambda *a, **k: None),
                        ("init_tracks", lambda *a, **k: None),
                        ("_login_interrupt_active", lambda: False),
                        ("Browser", _FakeBrowser),
                        ("_profile_dir", lambda *a, **k: tmp_path / "profile"),
                        ("_update_firestore_research", lambda *a, **k: None),
                        ("setup_firestore_run", lambda *a, **k: None),
                        ("teardown_firestore_run", lambda *a, **k: None),
                        ("fail_phase", lambda **kw: None)):
        monkeypatch.setattr(research, name, value)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)

    async def _noop():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop)

    def _emit(name, phase=None, **_kw):
        if name == "phase_start" and phase == 0:
            raise RuntimeError("stop here")
    monkeypatch.setattr(research, "emit_event", _emit)
    _real_sleep = asyncio.sleep

    async def _fast(*_a, **_k):
        return await _real_sleep(0)
    monkeypatch.setattr(research.asyncio, "sleep", _fast)
    try:
        asyncio.run(research.run_pipeline(
            topic=TOPIC, resume_dir=str(queue_dir), uid=UID, research_id=RID,
            api_key="k", email=None))
    finally:
        research._runtime.reset()
        research._controls.reset()
    assert [(u, r, p["title"]) for u, r, p in world.wrote] == [
        (UID, RID, "Decisions API Versus Jev")], world.logs
    assert world.store.updates == [
        (INTRO, {"content": 'Researching **"Decisions API Versus Jev"**',
                 "deviceId": "dev-w19"})], world.logs


# ══ 5. the podcast's name never reaches the computer's log ═══════════════════

def test_a_resumed_podcast_is_published_without_its_name_in_the_log(
        world, monkeypatch, tmp_path):
    (tmp_path / "podcasts").mkdir()
    audio = tmp_path / "podcasts" / "Bobs_Divorce_Shortlist.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(research, "_p3_publish_audio", lambda *a, **k: _done(""))
    research._RESEARCH_NAMES_MADE.clear()
    asyncio.run(research._p3_publish_on_resume(tmp_path, {}, RID))
    monkeypatch.setattr(research, "_p3_publish_audio", lambda *a, **k: _done("https://s"))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    asyncio.run(research._p3_publish_on_resume(tmp_path, {}, RID))
    p3 = [m for m in world.logs if "podcast on disk" in m]
    assert len(p3) == 2, world.logs
    assert not any("Divorce" in m or "Bobs" in m for m in world.logs), world.logs


def test_the_rename_and_the_transcode_say_only_length_and_type(world, monkeypatch, tmp_path):
    p = tmp_path / "The_AI_that_refuses_to_speak.m4a"
    p.write_bytes(b"a")
    out = research._p3_name_podcast_file(p, "Bobs Divorce Shortlist")
    monkeypatch.setattr(research, "_ffmpeg_bin", lambda: "ffmpeg")

    def _run(args, **_k):
        Path(args[-1]).write_bytes(b"mp3")
        return types.SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(research.subprocess, "run", _run)
    research._transcode_audio_to_mp3(out, title="Bobs Divorce Shortlist")
    assert world.logs and not any("Divorce" in m or "refuses" in m for m in world.logs)


async def _done(value):
    return value
