"""The local serve API never tells the computer's owner a private run's subject.

⛔⛔ WHAT WAS WRONG (wave 10.10, found by wave 10.9's last repair round). The
incognito feature promises the research computer's owner is told only that a
run happened. `backend.log` keeps that promise (`_loggable_topic`), but the
local serve API — which answers whoever holds its token, i.e. the owner —
returned an in-flight incognito run's folder whole: `GET /api/runs` its title
and topic, `GET /api/runs/{id}` its meta (with every report's section titles),
its checkpoint and its delivery record, and `/documents/{type}` and `/audio/…`
the reports and the podcast themselves.

⭐ SAME MARK, SAME TEST. A private run's folder is now described by what
carries no subject — its folder name (minted without the topic), its state,
its phase and its times — with `<topic removed>` where the subject was, the
mark the log and the support bundle already use. Its documents and audio are
refused. Every other run is served exactly as before.

EXECUTED: the routes are the real closures `run_server` builds, run over real
temporary folders, and each assertion is on the whole JSON a caller receives.
"""
import asyncio
import json
import types

import research

INCOG = "incog_1758400000000_2"
CHAT = "chat_1758400000000_2"
SECRET = "the history of a very private subject"
HEADING = "Private heading about it"


def _route(name, queues_root):
    code = next((c for c in research.run_server.__code__.co_consts
                 if isinstance(c, types.CodeType) and c.co_name == name), None)
    assert code is not None, f"{name} is no longer a closure of run_server"
    cells = {"queues_root": queues_root,
             "JSONResponse": lambda body, status=200: ("json", status, body)}
    return types.FunctionType(code, research.__dict__, name, None,
                              tuple(types.CellType(cells[v]) for v in code.co_freevars))


def _run_folder(root, name, rid=None, *, with_meta=True):
    """A run mid-flight, as the pipeline leaves it: every file that carries
    the subject is there."""
    d = root / name
    (d / "documents").mkdir(parents=True)
    (d / "podcasts").mkdir()
    (d / "delivery.json").write_text(json.dumps(
        {"topic": SECRET, "status": "ongoing"}), encoding="utf-8")
    (d / "checkpoint.json").write_text(json.dumps(
        {"topic": SECRET, "last_completed_phase": 2}), encoding="utf-8")
    if with_meta:
        (d / "meta.json").write_text(json.dumps({
            "id": name, "title": SECRET, "topic": SECRET, "status": "ongoing",
            "phase": 2, "agents": {"chatgpt": {"sections": [HEADING]}},
        }), encoding="utf-8")
    (d / "documents" / "chatgpt.md").write_text(f"# {HEADING}\n\n{SECRET}",
                                                encoding="utf-8")
    (d / "podcasts" / "episode.mp3").write_bytes(b"ID3 not really audio")
    if rid:
        (d / "owner.json").write_text(json.dumps({"uid": "u1", "researchId": rid}),
                                      encoding="utf-8")
    return d


def _run(coro):
    return asyncio.run(coro)


# ══ 1. the list ═══════════════════════════════════════════════════════════

def test_the_list_carries_no_subject_of_a_private_run(tmp_path):
    """⛔⛔ THE LEAK: title, topic and meta all used to come back whole."""
    _run_folder(tmp_path, "incognito_1758400000000_2_20260923_101500", INCOG)
    rows = _run(_route("list_runs", tmp_path)())
    dumped = json.dumps(rows)
    assert SECRET not in dumped and HEADING not in dumped, dumped
    [row] = rows
    assert row["title"] == row["topic"] == research._BUNDLE_TOPIC_MARK
    assert row["status"] == "ongoing" and row["phase"] == 1
    assert row["id"] == "incognito_1758400000000_2_20260923_101500"


def test_it_is_known_by_its_record_even_under_another_name(tmp_path):
    _run_folder(tmp_path, "renamed_by_hand", INCOG)
    assert SECRET not in json.dumps(_run(_route("list_runs", tmp_path)()))


def test_it_is_known_by_its_name_when_its_record_was_never_written(tmp_path):
    _run_folder(tmp_path, "incognito_1758400000000_2_20260923_101500", None,
                with_meta=False)
    assert SECRET not in json.dumps(_run(_route("list_runs", tmp_path)()))


def test_an_ordinary_run_is_listed_as_it_always_was(tmp_path):
    """⭐ ACCEPT POLARITY: the owner's own and their members' ordinary runs keep
    their titles — they are in the app and in the folder names already."""
    _run_folder(tmp_path, "a_topic_20260923_101500", CHAT)
    [row] = _run(_route("list_runs", tmp_path)())
    assert row["title"] == SECRET and row["agents"]["chatgpt"]["sections"] == [HEADING]


# ══ 2. one run ════════════════════════════════════════════════════════════

def test_one_private_run_carries_no_subject_anywhere(tmp_path):
    name = "incognito_1758400000000_2_20260923_101500"
    _run_folder(tmp_path, name, INCOG)
    got = _run(_route("get_run", tmp_path)(name))
    dumped = json.dumps(got)
    assert SECRET not in dumped and HEADING not in dumped, dumped
    assert got["pipeline_state"] == "running"
    assert got["meta"]["title"] == research._BUNDLE_TOPIC_MARK


def test_one_ordinary_run_is_served_whole(tmp_path):
    _run_folder(tmp_path, "a_topic_20260923_101500", CHAT)
    got = _run(_route("get_run", tmp_path)("a_topic_20260923_101500"))
    assert got["checkpoint"]["topic"] == SECRET
    assert got["delivery"]["topic"] == SECRET
    assert got["meta"]["title"] == SECRET


# ══ 3. the report and the podcast ═════════════════════════════════════════

def test_a_private_runs_report_is_not_served(tmp_path):
    """⛔⛔ The subject in its strongest form: the report itself."""
    name = "incognito_1758400000000_2_20260923_101500"
    _run_folder(tmp_path, name, INCOG)
    got = _run(_route("get_document", tmp_path)(name, "chatgpt"))
    assert got[0] == "json" and got[1] == 403, got
    assert SECRET not in json.dumps(got[2]) and HEADING not in json.dumps(got[2])


def test_a_private_runs_podcast_is_not_served(tmp_path):
    name = "incognito_1758400000000_2_20260923_101500"
    _run_folder(tmp_path, name, INCOG)
    got = _run(_route("get_audio", tmp_path)(name, "episode.mp3"))
    assert isinstance(got, tuple) and got[1] == 403, got


def test_an_ordinary_runs_report_and_podcast_are_served(tmp_path):
    _run_folder(tmp_path, "a_topic_20260923_101500", CHAT)
    doc = _run(_route("get_document", tmp_path)("a_topic_20260923_101500", "chatgpt"))
    assert SECRET in doc["content"]
    audio = _run(_route("get_audio", tmp_path)("a_topic_20260923_101500", "episode.mp3"))
    assert not isinstance(audio, tuple), audio
