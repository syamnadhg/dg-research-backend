"""What the person watching a run that keeps nothing actually sees.

⛔⛔ "RUNS A REAL RESEARCH, WITH LIVE PROGRESS" IS HALF THE PROMISE. Nothing is
kept afterwards — that half has its own files — but while the run is happening
the chat must show what any other run's chat shows: each agent's sources, its
findings, its progress curve and how long it took. Wave 10.9's first build
broke exactly that, twice, and in both cases the record said something the
machine knew to be false:

  · the incognito write path rewrote a payload one level deep, so an agent's
    terminal status arrived as `update({"agents.claude": {"status": …}})` — a
    map as one value, which REPLACES — and every field that agent had was
    deleted the moment it finished;
  · phase 3, on the path where it still runs, reported a deliberate refusal to
    publish as an upload FAILURE and told the person their podcast was "still
    on your research computer" — a file the purge deletes minutes later.

⭐ EVERY PIN HERE EXECUTES THE DECISION, and the document ones apply Firestore's
own two semantics (`apply_firestore_update` from the conftest for an update, a
deep merge for a set) so that "the tile keeps its sources" is measured as a
DOCUMENT, not as the shape of a payload. A payload-shape assertion is what let
this through the first time: the old pin read `{"agents.claude": {…}}` and was
satisfied by the very write that emptied the map.
"""
import asyncio
import json
import re

import pytest

import research
from conftest import apply_firestore_update

UID = "uid-sharer"
INCOG = "incog_1758400000000_7"
CHAT = "chat_1758400000000_7"

#: What `save_meta` propagates for one agent once phase 2 has its report —
#: research.py builds exactly these keys, and every one of them is a thing the
#: agent's card in the chat draws.
RICH = {
    "sources": 43,
    "sourceUrls": ["https://a.example/1", "https://b.example/2"],
    "sections": ["Background", "Findings"],
    "outputChars": 48210,
    "findings": 12,
    "progressHistory": [{"t": 1, "chars": 10}, {"t": 2, "chars": 4820}],
    "completionTimeSec": 1820,
    "status": "running",
}


def _deep_merge(dst: dict, src: dict) -> dict:
    """`set(…, merge=True)`: a nested map merges INTO the map already there.

    This is the behaviour the incognito path has to keep meaning, so it is
    written out once here rather than assumed."""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value
    return dst


class _Doc:
    """A research document that answers both verbs the way Firestore does."""

    def __init__(self):
        self.data: dict = {}
        self.writes = 0

    def set(self, payload, merge=False):
        self.writes += 1
        if merge:
            _deep_merge(self.data, payload)
        else:
            self.data = json.loads(json.dumps(payload))

    def update(self, payload):
        self.writes += 1
        apply_firestore_update(self.data, payload)


class _Ref:
    """`db.collection(…).document(…)` down to one shared document."""

    def __init__(self, doc):
        self.doc = doc

    def collection(self, _name):
        return self

    def document(self, _name):
        return self

    def set(self, payload, merge=False):
        self.doc.set(payload, merge=merge)

    def update(self, payload):
        self.doc.update(payload)


@pytest.fixture()
def live(monkeypatch):
    """The machine's real writers, pointed at one in-memory document."""
    doc = _Doc()
    monkeypatch.setattr(research, "_firebase_db", _Ref(doc))
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_be_payload", lambda d: dict(d))
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return doc


# ══ 1. an agent that finishes keeps what it found ═════════════════════════

@pytest.mark.parametrize("rid", [CHAT, INCOG])
def test_a_finishing_agent_keeps_its_sources_findings_and_stopwatch(live, rid):
    """⛔⛔ THE LIVE TILE. Phase 2 propagates the whole per-agent entry; the agent
    then finishes and `_write_agent_terminal_status` sends `{"status":
    "complete"}` for that one agent. Under a one-level rewrite that second write
    landed as a whole-map value at `agents.claude` and deleted the first — so
    the card went blank on sources, findings and the progress curve, for good if
    no `save_meta` followed.

    ⭐ PARAMETRIZED WITH THE ORDINARY RUN FIRST, because the ordinary run is the
    definition: whatever a `chat_` record holds after this sequence is what an
    `incog_` record must hold."""
    ref = research._firebase_db
    research._write_research_doc(ref, {"agents": {"claude": dict(RICH)}}, rid)
    research._write_research_doc(
        ref, {"agents": {"claude": {"status": "complete"}}}, rid)

    claude = live.data["agents"]["claude"]
    assert claude["status"] == "complete", "the terminal status did not land"
    assert claude["sources"] == 43, "the agent's sources were deleted"
    assert claude["sourceUrls"] == RICH["sourceUrls"], "its source links were deleted"
    assert claude["findings"] == 12, "its findings count was deleted"
    assert claude["progressHistory"] == RICH["progressHistory"], "its curve was deleted"
    assert claude["completionTimeSec"] == 1820, "how long it took was deleted"


@pytest.mark.parametrize("rid", [CHAT, INCOG])
def test_the_agent_that_finishes_leaves_the_others_exactly_as_they_were(live, rid):
    """The sibling half, measured on the document rather than on the payload."""
    ref = research._firebase_db
    research._write_research_doc(
        ref, {"agents": {"claude": dict(RICH), "gemini": dict(RICH)}}, rid)
    research._write_research_doc(
        ref, {"agents": {"claude": {"status": "complete"}}}, rid)

    assert live.data["agents"]["gemini"] == RICH, "another agent's card was emptied"


def test_the_record_a_run_that_keeps_nothing_builds_is_the_ordinary_one(live,
                                                                       monkeypatch):
    """⛔⛔ THE WHOLE COMPATIBILITY CLAIM, AS A DOCUMENT. `_write_research_doc`
    exists to stop an incognito write RESURRECTING a purged record; it may not
    also change what the record says. Two documents, the same sequence of real
    writes, and they have to be the same document at the end — which no payload
    shape assertion can tell you."""
    docs = {}
    for rid in (CHAT, INCOG):
        doc = _Doc()
        monkeypatch.setattr(research, "_firebase_db", _Ref(doc))
        ref = research._firebase_db
        research._write_research_doc(ref, {"backendRunId": "r_1"}, rid)
        research._write_research_doc(
            ref, {"agents": {"chatgpt": dict(RICH), "claude": dict(RICH)}}, rid)
        research._write_research_doc(
            ref, {"links": {"brief": {"url": "https://x/1", "label": "Brief"}}}, rid)
        research._write_research_doc(
            ref, {"agents": {"chatgpt": {"status": "complete"}}}, rid)
        research._write_research_doc(
            ref, {"agents": {"claude": {"status": "skipped",
                                        "statusReason": "auto_skip_agent_error"}}}, rid)
        research._write_research_doc(
            ref, {"links": {"brief": {"url": "https://x/2"}}}, rid)
        docs[rid] = doc.data

    # ⭐ ONE DIFFERENCE IS THE POINT (wave 10.9 repair): the record of a run that
    # keeps nothing carries its fuse forward on every write, and an ordinary
    # record is never handed one. Everything else must be the same document.
    fuse = docs[INCOG].pop("expireAt")
    assert "expireAt" not in docs[CHAT], "an ordinary record was handed a fuse"
    assert fuse.tzinfo is not None
    assert docs[INCOG] == docs[CHAT]
    assert docs[INCOG]["agents"]["chatgpt"]["sources"] == 43
    assert docs[INCOG]["links"]["brief"]["label"] == "Brief", (
        "a later write to one key of the same link cleared the rest")


def test_the_agent_status_writer_keeps_the_agent_it_writes_about(live, monkeypatch):
    """⛔ THE CALLER, NOT THE SEAM. `_do_agent_terminal_status_write` is what
    every finished agent goes through — `_set_research_doc` → `_be_payload` →
    `_write_research_doc` — and a helper that merges correctly while its caller
    sends something else would pass every test above."""
    monkeypatch.setattr(research, "_fb_research_id", INCOG)
    research._write_research_doc(
        research._firebase_db, {"agents": {"claude": dict(RICH)}}, INCOG)

    research._do_agent_terminal_status_write("Claude", "skipped",
                                             reason="auto_skip_agent_error",
                                             detail="Its research failed.")

    claude = live.data["agents"]["claude"]
    assert claude["status"] == "skipped"
    assert claude["statusReason"] == "auto_skip_agent_error"
    assert claude["statusDetail"] == "Its research failed."
    assert claude["sources"] == 43, "the agent's own card was emptied by its status"
    assert claude["completionTimeSec"] == 1820


@pytest.mark.parametrize("name,spliceable", [
    ("audio_file", True), ("chatgpt", True), ("_x", True), ("a9", True),
    ("audio-file", False), ("2x", False), ("a.b", False), ("a b", False),
])
def test_every_name_it_splices_into_a_path_is_one_the_client_can_parse(
        name, spliceable):
    """⛔⛔ MEASURED AGAINST THE CLIENT, NOT AGAINST A BELIEF ABOUT IT.
    `parse_field_path` accepts an unquoted segment of `[A-Za-z_][A-Za-z0-9_]*`
    and RAISES on anything else — so a name this rewriter splices in but the
    client refuses is not "at worst a replace": it is an exception thrown inside
    the write, swallowed by `_set_research_doc` as a WARN, and a write an
    ordinary run lands with a set-merge that simply never happens for a run that
    keeps nothing. The two sets have to be the same set."""
    from google.cloud.firestore_v1 import field_path as _fp

    out = research._merge_field_paths({"links": {name: {"url": "x"}}})
    assert (list(out) == [f"links.{name}.url"]) is spliceable

    for path in out:
        _fp.parse_field_path(path)  # raises if this address is unwritable


def test_an_array_append_still_appends_rather_than_being_walked_into(live,
                                                                    monkeypatch):
    """⛔ A SENTINEL IS NOT A MAP. `ArrayUnion` holds a list of dicts; a rewrite
    that descended into it would turn an append into a write to a field path
    named after a list index — or worse, land the entry somewhere else."""
    monkeypatch.setattr(research, "_fb_research_id", INCOG)
    research.append_user_source_in_firestore("doc", "https://x/2", label="A doc")

    assert type(live.data["userSources"]).__name__ == "ArrayUnion"


# ══ 2. phase 3, on the path where it still runs ═══════════════════════════
#
# Phase 3 is OFF for a run that keeps nothing. `_p3_publish_audio` is the net
# for when that configuration does not arrive — a resume whose config.json
# predates the flip, or a caller that drops the key — and on that path the
# podcast IS produced and IS refused publication. What the person is then told
# is this section.

def test_a_run_that_keeps_nothing_is_never_told_its_podcast_is_on_that_computer(
        tmp_path):
    """⛔⛔ BOTH HALVES WERE FALSE. Nothing failed — the machine declined to
    publish — and the file is not "still" anywhere: `_purge_incognito_run_dirs`
    removes that folder minutes later. The person is a guest on somebody else's
    computer; telling them their private research is sitting on it, when it is
    about to be deleted, is the opposite of what they were promised."""
    audio = tmp_path / "Deep_Dive.m4a"
    audio.write_bytes(b"audio")
    reason, detail = research._p3_no_podcast_report(audio, INCOG)

    assert "still on your research computer" not in detail
    assert reason != "audio_generated_but_upload_failed"
    assert "upload" not in reason.lower() and "upload" not in detail.lower(), (
        "a refusal to publish was reported as an upload failure")
    assert detail, "the phase must still say why it holds no podcast"


def test_what_it_says_instead_reaches_the_tile_as_written(tmp_path):
    """⛔ THE REASON IS RENDERED BY THE APP, AND IT ENUMERATES SLUGS. An unknown
    slug is de-underscored into "Skipped — a slug like this"; PROSE is returned
    untouched (`isProseReason`: lowercase, digits and underscores only is a
    slug). So a sentence written here arrives as the sentence — and a new slug
    would arrive as a slug, with no web change to make it a sentence."""
    audio = tmp_path / "Deep_Dive.m4a"
    audio.write_bytes(b"audio")
    reason, _detail = research._p3_no_podcast_report(audio, INCOG)

    assert not re.fullmatch(r"[a-z0-9_]+", reason), (
        "the tile would show a de-underscored slug, not this sentence")


def test_it_says_the_same_thing_whether_or_not_the_audio_was_made(tmp_path):
    """⭐ ONE ANSWER, because the outcome is one outcome. "We made it and threw
    it away" and "we never made it" differ only in a repair neither has: there
    is nothing to fetch and nothing to retry, and a sentence naming a podcast
    that was made would be a claim about a file nobody can reach."""
    audio = tmp_path / "Deep_Dive.m4a"
    audio.write_bytes(b"audio")
    assert (research._p3_no_podcast_report(audio, INCOG)
            == research._p3_no_podcast_report(None, INCOG))


@pytest.mark.parametrize("made_audio", [True, False])
def test_an_ordinary_run_is_still_told_exactly_which_of_the_two_failed(
        tmp_path, made_audio):
    """⭐ ACCEPT POLARITY, and it is a measured bug of its own: "no podcast" and
    "a podcast we could not upload" are different states with different repairs,
    and in the second the file really is still on the research computer."""
    audio = tmp_path / "Deep_Dive.m4a"
    audio.write_bytes(b"audio")
    reason, detail = research._p3_no_podcast_report(audio if made_audio else None, CHAT)

    if made_audio:
        assert reason == "audio_generated_but_upload_failed"
        assert "still on your research computer" in detail
    else:
        assert reason == "no_audio_generated"
        assert "No audio overview was produced" in detail


# ── …and the phase actually asks it about THIS run ─────────────────────────
#
# ⛔⛔ A TESTED HELPER IS NOT A TESTED CONSUMER. Every pin above picks the id it
# hands `_p3_no_podcast_report` itself, and the only thing tying the pipeline
# to the helper was a source read that stopped at the open parenthesis — so the
# call could pass `None`, or the wrong id, and tell a run that keeps nothing
# its podcast is "still on your research computer" with every test green.
#
# ⭐ THE BRANCH IS RUN, NOT READ. It sits a thousand lines inside a browser
# coroutine, so its statements are lifted out of `run_pipeline`'s own parse tree
# and executed as they are — only the names the pipeline would have bound around
# them are supplied here.

def _p3_no_podcast_branch():
    """The real body of `run_pipeline`'s `elif _p3_no_skip:` branch, as a
    function of no arguments whose free names are globals."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(research.run_pipeline)))
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
             and n.test.id == "_p3_no_skip"]
    assert len(found) == 1, (
        f"expected ONE `elif _p3_no_skip:` in run_pipeline, found {len(found)} — "
        "re-anchor this pin on the branch that reports a phase 3 with no podcast")
    shell = ast.parse("def _branch():\n    pass\n")
    shell.body[0].body = found[0].body
    ast.fix_missing_locations(shell)
    return compile(shell, research.__file__, "exec")


@pytest.mark.parametrize("rid", [INCOG, CHAT])
def test_the_phase_tells_the_run_it_is_running_what_is_true_of_it(tmp_path, rid):
    """⛔⛔ THE PATH THE HELPER EXISTS FOR: an incognito run resumed with a
    config.json from before the flip, so phase 3 ran and made audio, and the
    machine refused to publish it. The phase asks about the RUNNING research —
    `_fb_research_id` — and nothing else."""
    audio = tmp_path / "Deep_Dive.m4a"
    audio.write_bytes(b"audio")
    events = []
    scope = {**vars(research),
             "audio_path": audio, "_fb_research_id": rid,
             "_p3_start": 0.0, "_p3_links": {},
             "log": lambda *a, **k: None,
             "emit_event": lambda name, **kw: events.append((name, kw))}
    exec(_p3_no_podcast_branch(), scope)
    scope["_branch"]()

    [(name, data)] = events
    assert name == "phase_skipped" and data["phase"] == 3
    if rid == INCOG:
        assert "still on your research computer" not in data["detail"], (
            "a run that keeps nothing was told its podcast sits on that computer")
        assert data["reason"] == research._P3_KEEPS_NOTHING_REASON
    else:
        assert data["reason"] == "audio_generated_but_upload_failed"
        assert "still on your research computer" in data["detail"], (
            "an ordinary run lost the one sentence that says where its podcast is")


# ══ 3. a resume that ends the run still takes the folder ══════════════════

def _resumable(tmp_path, monkeypatch, rid, status="completed"):
    """A queue directory as a crashed run left it: the documents, the delivery
    record, and the `owner.json` that names whose research it is."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "_run_log_folders_for_research", lambda r: [])
    queue = tmp_path / "queues" / "incognito_1758400000000_7_20260922_101500"
    (queue / "documents").mkdir(parents=True)
    (queue / "documents" / "claude.md").write_text("the whole report", encoding="utf-8")
    (queue / "delivery.json").write_text(
        json.dumps({"topic": "a private subject", "status": status}), encoding="utf-8")
    (queue / "owner.json").write_text(
        json.dumps({"uid": UID, "researchId": rid}), encoding="utf-8")
    return queue


def test_the_folder_goes_even_when_the_caller_never_named_the_research(
        tmp_path, monkeypatch):
    """⛔⛔ `superresearch --resume <folder>` CARRIES NO RESEARCH ID. The CLI
    passes a directory and nothing else, so the wrapper's capture key resolved
    None and the purge refused at its first line — the documents, the delivery
    record and the topic stayed on the computer until the orphan sweep noticed
    the record was gone. The folder itself names the run: `owner.json` is
    written beside the checkpoint, and it is the same key the resume's own
    ownership checks read."""
    queue = _resumable(tmp_path, monkeypatch, INCOG)
    assert research._purge_incognito_run_dirs(queue, None) is True
    assert not queue.exists()


def test_an_ordinary_runs_folder_is_still_not_taken_from_it(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY. Local retention is sixty runs and thirty days, and the
    support bundle is built from exactly these folders."""
    queue = _resumable(tmp_path, monkeypatch, CHAT)
    assert research._purge_incognito_run_dirs(queue, None) is False
    assert (queue / "documents" / "claude.md").exists()


def test_a_folder_that_cannot_name_its_run_is_left_alone(tmp_path, monkeypatch):
    """⛔ NO RECORD, NO CLAIM — the rule every other reader of `owner.json`
    follows. A folder with none is a run this machine cannot attribute, and
    deleting on a guess is how somebody else's work disappears."""
    queue = _resumable(tmp_path, monkeypatch, INCOG)
    (queue / "owner.json").unlink()
    assert research._purge_incognito_run_dirs(queue, None) is False
    assert queue.exists()


def test_a_named_research_still_wins_over_the_folders_own_record(tmp_path,
                                                                monkeypatch):
    """⛔ THE FALLBACK IS FOR A CALLER THAT SAID NOTHING, never a second opinion.
    A caller that names an ordinary research must not have a stale `owner.json`
    turn its folder into an incognito one."""
    queue = _resumable(tmp_path, monkeypatch, INCOG)
    assert research._purge_incognito_run_dirs(queue, CHAT) is False
    assert queue.exists()


def test_a_terminal_resume_leaves_no_folder_behind(tmp_path, monkeypatch):
    """⛔⛔ THE CONSUMER, DRIVEN THE WAY THE CLI DRIVES IT: `resume_dir` and
    nothing else. This is the call at research.py's `--resume` branch."""
    queue = _resumable(tmp_path, monkeypatch, INCOG)

    async def _body(*a, **k):
        return "done"
    monkeypatch.setattr(research, "run_pipeline", _body)
    monkeypatch.setattr(research, "_RunLogCapture", lambda **kw: _NoCapture())

    out = asyncio.run(research.run_pipeline_captured(
        topic="", resume_dir=str(queue), verbose=False, api_key=None, email=None))
    assert out == "done", "the wrapper must still answer its caller"
    assert not queue.exists(), "the run ended and its folder stayed"


def test_a_resume_of_an_ordinary_run_keeps_its_folder(tmp_path, monkeypatch):
    queue = _resumable(tmp_path, monkeypatch, CHAT)

    async def _body(*a, **k):
        return "done"
    monkeypatch.setattr(research, "run_pipeline", _body)
    monkeypatch.setattr(research, "_RunLogCapture", lambda **kw: _NoCapture())

    asyncio.run(research.run_pipeline_captured(
        topic="", resume_dir=str(queue), verbose=False, api_key=None, email=None))
    assert queue.exists()


class _NoCapture:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False
