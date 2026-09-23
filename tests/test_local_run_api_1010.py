"""The local serve API's two views of a run tell the same story.

⛔⛔ WHAT WAS WRONG (wave 10.10). `GET /api/runs/{id}` read a run's state from
its stop and pause markers and its delivery status. `GET /api/runs`, for a
folder with no `meta.json`, read "delivery.json exists" as "completed" — and
delivery.json is written at the START of a run, as "ongoing". So the list
called a run finished the moment it began, while the single-run route said it
was running. Both now ask `_local_run_state`.

⭐ EXECUTED, NOT READ. The helpers run on real temporary folders, and both
routes run as the real closures `run_server` builds — the code objects are the
real ones, only the values `run_server` would have closed over are supplied —
so a route that went back to its own inline reading fails here.
"""
import asyncio
import json
import types

import pytest

import research

INCOG = "incog_1758400000000_2"
CHAT = "chat_1758400000000_2"


def _route(name):
    """The real route closure `run_server` defines, rebuilt over test values."""
    code = next((c for c in research.run_server.__code__.co_consts
                 if isinstance(c, types.CodeType) and c.co_name == name), None)
    assert code is not None, f"{name} is no longer a closure of run_server"

    def build(queues_root):
        cells = {"queues_root": queues_root,
                 "JSONResponse": lambda body, status=200: ("json", status, body)}
        return types.FunctionType(
            code, research.__dict__, name, None,
            tuple(types.CellType(cells[v]) for v in code.co_freevars))
    return build


def _folder(root, name, *, delivery=None, meta=None, checkpoint=None,
            marker=None, owner_rid=None):
    d = root / name
    d.mkdir(parents=True)
    if delivery is not None:
        (d / "delivery.json").write_text(json.dumps(delivery), encoding="utf-8")
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if checkpoint is not None:
        (d / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    if marker:
        (d / marker).write_text(marker.strip("."), encoding="utf-8")
    if owner_rid:
        (d / "owner.json").write_text(
            json.dumps({"uid": "u1", "researchId": owner_rid}), encoding="utf-8")
    return d


# ══ 1. the one reading ════════════════════════════════════════════════════

@pytest.mark.parametrize("delivery,marker,expected", [
    ({"status": "ongoing"}, None, "running"),
    ({"status": "completed"}, None, "completed"),
    ({"status": "completed"}, ".stop", "stopped"),
    ({"status": "ongoing"}, ".pause", "paused"),
    (None, None, "running"),
])
def test_the_state_a_folder_reads_as(tmp_path, delivery, marker, expected):
    d = _folder(tmp_path, "run_x", delivery=delivery, marker=marker)
    assert research._local_run_state(d) == expected


def test_an_unreadable_delivery_says_nothing_either_way(tmp_path):
    d = _folder(tmp_path, "run_x")
    (d / "delivery.json").write_text("{not json", encoding="utf-8")
    assert research._local_run_state(d) == "running"


def test_a_row_without_meta_says_ongoing_while_the_run_runs(tmp_path):
    """⛔⛔ THE DEFECT: delivery.json exists from the first second, as ongoing."""
    d = _folder(tmp_path, "topic_20260923_101500", delivery={"status": "ongoing"},
                checkpoint={"topic": "a topic", "last_completed_phase": 2})
    row = research._local_run_row(d)
    assert row["status"] == "ongoing", row
    assert row["phase"] == 1 and row["topic"] == "a topic"


@pytest.mark.parametrize("delivery,marker,expected", [
    ({"status": "completed"}, None, "completed"),
    ({"status": "ongoing"}, ".stop", "stopped"),
    ({"status": "ongoing"}, ".pause", "paused"),
])
def test_a_row_without_meta_follows_the_same_reading(tmp_path, delivery, marker,
                                                      expected):
    d = _folder(tmp_path, "run_y", delivery=delivery, marker=marker)
    assert research._local_run_row(d)["status"] == expected


def test_a_row_with_meta_is_the_meta(tmp_path):
    """⭐ NO WIDENING: a folder with its own meta.json is listed as it was."""
    meta = {"id": "run_z", "status": "ongoing", "title": "t"}
    d = _folder(tmp_path, "run_z", delivery={"status": "completed"}, meta=meta)
    assert research._local_run_row(d) == meta


# ══ 2. both routes ask it ═════════════════════════════════════════════════

def test_the_list_route_says_ongoing_for_a_run_that_just_started(tmp_path):
    """⛔⛔ THE CONSUMER. The helper is right and nothing matters unless the
    route that builds the list calls it."""
    _folder(tmp_path, "topic_20260923_101500", delivery={"status": "ongoing"})
    runs = asyncio.run(_route("list_runs")(tmp_path)())
    assert [r["status"] for r in runs] == ["ongoing"], runs


def test_the_single_run_route_and_the_list_agree(tmp_path):
    for i, (delivery, marker) in enumerate([({"status": "ongoing"}, None),
                                            ({"status": "completed"}, None),
                                            ({"status": "ongoing"}, ".stop"),
                                            ({"status": "ongoing"}, ".pause")]):
        _folder(tmp_path, f"run_{i}", delivery=delivery, marker=marker)
    listed = {r["id"]: r["status"]
              for r in asyncio.run(_route("list_runs")(tmp_path)())}
    for name, status in listed.items():
        one = asyncio.run(_route("get_run")(tmp_path)(name))
        assert research._LOCAL_RUN_LIST_STATUS.get(
            one["pipeline_state"], one["pipeline_state"]) == status, (name, one)
