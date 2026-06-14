import pytest

from facade.firestore_rest import (
    FirestoreError,
    FirestoreRest,
    doc_id,
    fields_to_dict,
    from_value,
    to_value,
)


def test_value_roundtrip():
    for v in ["s", 7, True, False, None, 1.5, ["a", 2], {"k": "v", "n": 3}]:
        assert from_value(to_value(v)) == v


def test_double_value_decodes_as_float():
    # Firestore serializes 5.0 as bare `5` (int after json) — must stay float.
    assert from_value({"doubleValue": 5}) == 5.0
    assert isinstance(from_value({"doubleValue": 5}), float)


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._p = payload or {}
        self.content = b"x"
        self.text = ""

    def json(self):
        return self._p


def test_401_forces_refresh_then_retries():
    tokens = []  # record (force) per provider call

    def provider(force=False):
        tokens.append(force)
        return "TOK-FORCED" if force else "TOK-CACHED"

    sends = []

    def fake_send(method, url, token, json_body):
        sends.append(token)
        return _Resp(401) if len(sends) == 1 else _Resp(200, {"ok": True})

    c = FirestoreRest(provider)
    c._send = fake_send  # type: ignore[method-assign]
    out = c._request("GET", "https://x/y")
    assert out == {"ok": True}
    assert sends == ["TOK-CACHED", "TOK-FORCED"]   # retry used a forced token
    assert tokens == [False, True]


def test_persistent_401_raises():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a, **k: _Resp(401)  # type: ignore[method-assign]
    with pytest.raises(FirestoreError):
        c._request("GET", "https://x/y")


def test_bool_not_int():
    # bools must encode as booleanValue, not integerValue (Python bool is int).
    assert to_value(True) == {"booleanValue": True}
    assert to_value(1) == {"integerValue": "1"}


def test_fields_to_dict_and_doc_id():
    doc = {
        "name": "projects/p/databases/(default)/documents/devices/dev123",
        "fields": {"ownerUid": {"stringValue": "u1"}, "n": {"integerValue": "2"}},
    }
    assert doc_id(doc["name"]) == "dev123"
    assert fields_to_dict(doc) == {"ownerUid": "u1", "n": 2}


def _capture_client():
    calls = []

    def fake_request(method, url, *, json_body=None):
        calls.append({"method": method, "url": url, "body": json_body})
        # canned responses keyed on the operation
        if url.endswith(":runQuery"):
            field = json_body["structuredQuery"]["where"]["fieldFilter"]["field"]["fieldPath"]
            if field == "ownerUid":
                return [{"document": {
                    "name": ".../devices/own1",
                    "fields": {"ownerUid": {"stringValue": "u1"}},
                }}]
            return [{"document": {
                "name": ".../devices/shared1",
                "fields": {"sharedWith": {"arrayValue": {"values": [{"stringValue": "u1"}]}}},
            }}]
        if method == "POST":  # enqueue
            return {"name": ".../queue/Q42"}
        if method == "GET":  # list researches
            return {"documents": [
                {"name": ".../researches/r1", "fields": {"title": {"stringValue": "A"}}},
            ]}
        return {}

    c = FirestoreRest(lambda: "tok")
    c._request = fake_request  # type: ignore[method-assign]
    return c, calls


def test_list_researches():
    c, _ = _capture_client()
    rows = c.list_researches("u1")
    assert rows == [{"title": "A", "id": "r1"}]


def test_list_researches_orders_by_created_desc():
    c, calls = _capture_client()
    c.list_researches("u1")
    get = [x for x in calls if x["method"] == "GET"][0]
    # newest-first ordering (mirrors the web app) so "most recent run" is correct
    assert "orderBy=createdAt%20desc" in get["url"]
    assert "pageSize=50" in get["url"]


def test_list_devices_unions_owned_and_shared():
    c, calls = _capture_client()
    devs = c.list_devices("u1")
    ids = {d["id"] for d in devs}
    assert ids == {"own1", "shared1"}
    # two runQuery calls: ownerUid EQUAL + sharedWith ARRAY_CONTAINS
    qcalls = [x for x in calls if x["url"].endswith(":runQuery")]
    ops = {x["body"]["structuredQuery"]["where"]["fieldFilter"]["op"] for x in qcalls}
    assert ops == {"EQUAL", "ARRAY_CONTAINS"}


def test_enqueue_start_payload_matches_fe_contract():
    c, calls = _capture_client()
    qid = c.enqueue_start("dev9", uid="u1", research_id="r5", topic="T", email="e@x.y")
    assert qid == "Q42"
    body = [x for x in calls if x["method"] == "POST"][0]["body"]["fields"]
    # the BE start listener requires these exact fields:
    assert body["action"] == {"stringValue": "start"}
    assert body["submittedBy"] == {"stringValue": "u1"}  # == uid → satisfies the rule
    assert body["uid"] == {"stringValue": "u1"}
    assert body["researchId"] == {"stringValue": "r5"}
    assert "timestamp" in body and "submittedAt" in body
    assert body["viaAgent"] == {"booleanValue": True}


def test_upsert_research_sets_update_mask():
    c, calls = _capture_client()
    c.upsert_research("u1", "r5", {"topic": "T", "status": "queued"})
    patch = [x for x in calls if x["method"] == "PATCH"][0]
    assert "updateMask.fieldPaths=topic" in patch["url"]
    assert "updateMask.fieldPaths=status" in patch["url"]
    assert patch["body"]["fields"]["status"] == {"stringValue": "queued"}


def test_seed_chat_messages_writes_topic_and_intro():
    c, calls = _capture_client()
    c.seed_chat_messages("u1", "agent-abc", topic="EV battery market", title="EV battery market")
    patches = [x for x in calls if x["method"] == "PATCH"]
    assert len(patches) == 2
    # topic bubble (user) at messages/topic-{rid}
    topic = next(x for x in patches if "messages/topic-agent-abc" in x["url"])
    assert topic["body"]["fields"]["role"] == {"stringValue": "user"}
    assert topic["body"]["fields"]["content"] == {"stringValue": "EV battery market"}
    assert "integerValue" in topic["body"]["fields"]["timestamp"]  # ms number
    # intro (assistant) at messages/intro-{rid} — id matches the web app's so the
    # FE phase_start upgrade rewrites it in place (no duplicate)
    intro = next(x for x in patches if "messages/intro-agent-abc" in x["url"])
    assert intro["body"]["fields"]["role"] == {"stringValue": "assistant"}
    assert "Researching" in intro["body"]["fields"]["content"]["stringValue"]


def test_seed_chat_messages_truncates_long_title():
    c, calls = _capture_client()
    c.seed_chat_messages("u1", "agent-x", topic="x" * 500, title="t" * 500)
    intro = next(x for x in calls if "messages/intro-" in x["url"])
    content = intro["body"]["fields"]["content"]["stringValue"]
    assert "…" in content and len(content) < 130  # intro stays compact


def test_get_research_returns_none_on_404():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a, **k: _Resp(404)  # type: ignore[method-assign]
    assert c.get_research("u1", "missing") is None


def test_get_research_decodes_doc():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a, **k: _Resp(200, {  # type: ignore[method-assign]
        "name": ".../researches/r1",
        "fields": {"title": {"stringValue": "Alpha"}, "phase": {"integerValue": "2"}},
    })
    assert c.get_research("u1", "r1") == {"title": "Alpha", "phase": 2, "id": "r1"}


def test_patch_pipeline_config_nested_mask():
    calls = []

    def fake_send(method, url, token, json_body):
        calls.append({"method": method, "url": url, "body": json_body})
        return _Resp(200, {})

    c = FirestoreRest(lambda force=False: "tok")
    c._send = fake_send  # type: ignore[method-assign]
    c.patch_pipeline_config("u1", "r5", {"skippedPhases": [1, 3], "videoEnabled": False})
    call = calls[0]
    assert call["method"] == "PATCH"
    # precise nested field paths → sibling pipelineConfig keys are preserved
    assert "updateMask.fieldPaths=pipelineConfig.skippedPhases" in call["url"]
    assert "updateMask.fieldPaths=pipelineConfig.videoEnabled" in call["url"]
    fields = call["body"]["fields"]["pipelineConfig"]["mapValue"]["fields"]
    assert fields["skippedPhases"]["arrayValue"]["values"] == [
        {"integerValue": "1"}, {"integerValue": "3"}]
    assert fields["videoEnabled"] == {"booleanValue": False}


def test_patch_pipeline_config_noop_on_empty():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send"))  # type: ignore[method-assign]
    c.patch_pipeline_config("u1", "r5", {})  # no updates → no request


def test_enqueue_cancel_payload():
    calls = []

    def fake_send(method, url, token, json_body):
        calls.append({"method": method, "url": url, "body": json_body})
        return _Resp(200, {"name": ".../queue/C7"})

    c = FirestoreRest(lambda force=False: "tok")
    c._send = fake_send  # type: ignore[method-assign]
    qid = c.enqueue_cancel("dev9", uid="u1", research_id="r5")
    assert qid == "C7"
    body = calls[0]["body"]["fields"]
    assert body["action"] == {"stringValue": "cancel"}
    assert body["researchId"] == {"stringValue": "r5"}
    assert body["submittedBy"] == {"stringValue": "u1"} and body["uid"] == {"stringValue": "u1"}
    assert "timestamp" in body and "submittedAt" in body
    assert "/devices/dev9/queue" in calls[0]["url"]


# ── agentSessions (#790) ─────────────────────────────────────────────────────

def test_upsert_agent_session_masked_merge():
    calls = []

    def fake_send(method, url, token, json_body):
        calls.append({"method": method, "url": url, "body": json_body})
        return _Resp(200, {})

    c = FirestoreRest(lambda force=False: "tok")
    c._send = fake_send  # type: ignore[method-assign]
    # a heartbeat touches ONLY lastSeenAt — the mask must not name siblings, so a
    # masked merge can't clobber label/runtime/connectedAt.
    c.upsert_agent_session("u1", "iid-9", {"lastSeenAt": 1234})
    call = calls[0]
    assert call["method"] == "PATCH"
    assert "/users/u1/agentSessions/iid-9?" in call["url"]
    assert "updateMask.fieldPaths=lastSeenAt" in call["url"]
    assert "updateMask.fieldPaths=label" not in call["url"]
    assert call["body"]["fields"]["lastSeenAt"] == {"integerValue": "1234"}


def test_get_agent_session_none_on_404():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a, **k: _Resp(404)  # type: ignore[method-assign]
    assert c.get_agent_session("u1", "missing") is None


def test_get_agent_session_decodes_revoked():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a, **k: _Resp(200, {  # type: ignore[method-assign]
        "name": ".../agentSessions/iid-9",
        "fields": {"label": {"stringValue": "Super Agent"}, "revoked": {"booleanValue": True}},
    })
    row = c.get_agent_session("u1", "iid-9")
    assert row == {"label": "Super Agent", "revoked": True, "id": "iid-9"}


def test_delete_agent_session_url():
    calls = []
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda m, u, t, b: calls.append((m, u)) or _Resp(200, {})  # type: ignore[method-assign]
    c.delete_agent_session("u1", "iid-9")
    assert calls[0][0] == "DELETE"
    assert calls[0][1].endswith("/users/u1/agentSessions/iid-9")
