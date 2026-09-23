"""Wave 10.10 — a bare run verb in chat never lands on a run the person did not mean.

The chat assistant leaves an incognito research out of every list it reads
(`test_incognito_hidden_1010.py`). That fix had a cost: a bare stop, pause,
resume, retry or skip then acted on the newest run the assistant could SEE. With
an incognito run and an ordinary run both going, "stop" — said about the run the
person had just started, the incognito one — stopped their ORDINARY run. A stop
cannot be undone.

⭐ THE HONEST RULE. The assistant can know a run it must not show is still going
without reading what it is about: the document's PATH marks it, and its
`status` (plus whether a decision card sits on it) says whether a person could
still mean it. Nothing else of it is decoded. While such a run exists, a bare
verb refuses to guess and names the runs the assistant CAN manage; a named verb
works exactly as before.

⛔ EVERYTHING HERE RUNS THROUGH THE REAL CLIENT. `sr.py` → the real loopback
bridge → the real `FirestoreRest`, with only its `_request` (the network)
replaced. Every write the bridge would make is recorded off that wire, so "did
nothing" is measured as "sent nothing", not as a sentence printed.
"""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge
from facade.firestore_rest import FirestoreRest, doc_id, to_value

UID = "u1"

SECRET_ID = "incog_1758000000009_4"
SECRET_TITLE = "Quiet acquisition"
SECRET_TOPIC = "Initech buying Hooli before the earnings call"
SECRET_WORDS = (SECRET_ID, SECRET_TITLE, SECRET_TOPIC, "Hooli", "1758000000009")

CARD = {"kind": "pipeline_error", "phase": 2, "title": "Hit a snag"}


def _doc(rid: str, **fields) -> dict:
    return {"name": f"projects/p/databases/(default)/documents/users/{UID}/researches/{rid}",
            "fields": {k: to_value(v) for k, v in fields.items()}}


def _secret(**fields) -> dict:
    """The incognito run, newest of all. Its words are everywhere in it,
    including inside its decision card, so a leak of any part shows."""
    base = {"title": SECRET_TITLE, "topic": SECRET_TOPIC, "deviceId": "dev1"}
    return _doc(SECRET_ID, **{**base, **fields})


#: The runs the assistant CAN show, newest first. The first three are going,
#: "Stuck run" is stopped but still carries a card, "Old run" is over.
VISIBLE = [
    _doc("r-card", title="Mars colony", topic="mars colony", status="ongoing",
         deviceId="dev1", pendingDecision=CARD),
    _doc("r-open", title="Tidal power", topic="tidal power", status="ongoing",
         deviceId="dev1"),
    _doc("r-paused", title="Reef survey", topic="reef survey", status="paused",
         deviceId="dev1"),
    _doc("r-stuck", title="Stuck run", status="stopped", deviceId="dev1",
         pendingDecision=CARD),
    _doc("r-old", title="Old run", status="completed", deviceId="dev1"),
]
LIVE_TITLES = ("Mars colony", "Tidal power", "Reef survey", "Stuck run")


def _steady(value):
    """A write body with its clock readings replaced, so the same write made a
    moment later compares equal. Only readings of NOW are replaced: a
    millisecond count (13 digits and up) or a timestamp."""
    if isinstance(value, dict):
        if set(value) == {"integerValue"} and len(str(value["integerValue"])) >= 13:
            return {"integerValue": "<now>"}
        if set(value) == {"timestampValue"}:
            return {"timestampValue": "<now>"}
        return {k: _steady(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_steady(v) for v in value]
    return value


class _Wire(FirestoreRest):
    """The REAL client; only the network under it is replaced. Reads come from
    `documents`; every write is recorded in `sent` and answered like Firestore."""

    documents: list = []
    sent: list = []

    def _request(self, method, url, *, json_body=None, allow_missing=False):
        path = url.split("/documents", 1)[-1]
        base = f"/users/{UID}/researches"
        if method == "GET" and path.startswith(base + "?"):
            return {"documents": json.loads(json.dumps(_Wire.documents))}
        if method == "GET" and path.startswith(base + "/"):
            rid = path[len(base) + 1:]
            match = [d for d in _Wire.documents if doc_id(d["name"]) == rid]
            return json.loads(json.dumps(match[0])) if match else None
        if method in ("POST", "PATCH"):
            _Wire.sent.append((method, path, _steady(json_body)))
            return {"name": "projects/p/databases/(default)/documents/x/written-1"}
        raise AssertionError(f"this test did not expect {method} {path}")


def _load_sr():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_bare_verb_hidden_1010", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()


@pytest.fixture()
def live(monkeypatch):
    _Wire.documents = []
    _Wire.sent = []
    monkeypatch.setattr(bridge, "FirestoreRest", _Wire)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-test")
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: "dev1")
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda **kw: None)
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: None)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid=UID, email="e@x.y",
                                      id_token=lambda force=False: "tok",
                                      logout=lambda: None))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(port))
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _say(argv, capsys, docs):
    """Run one chat command against an account holding `docs`.
    Returns (exit code, what the chat was shown, what went over the wire)."""
    _Wire.documents = list(docs)
    _Wire.sent = []
    rc = sr.main(list(argv))
    out = capsys.readouterr().out
    return rc, out, list(_Wire.sent)


def _touched(sent) -> set:
    """Every research id a write named — in its path, or in a queue job's body."""
    ids = set()
    for _method, path, body in sent:
        parts = path.split("?", 1)[0].split("/")
        if "researches" in parts:
            ids.add(parts[parts.index("researches") + 1])
        rid = ((body or {}).get("fields") or {}).get("researchId")
        if rid:
            ids.add(rid.get("stringValue"))
    return ids


def _nothing_of_it(text: str) -> None:
    for word in SECRET_WORDS:
        assert word not in text, f"{word!r} reached the chat"


#: (verb, a bare form, the same verb naming a run, the run that names).
VERBS = [
    ("stop", ["stop"], ["stop", "Tidal power"], "r-open"),
    ("pause", ["pause"], ["pause", "Tidal power"], "r-open"),
    ("resume", ["resume"], ["resume", "Reef survey"], "r-paused"),
    ("retry", ["retry"], ["retry", "Mars colony"], "r-card"),
    ("skip", ["skip"], ["skip", "--run", "Mars colony"], "r-card"),
    ("skip", ["skip", "video"], ["skip", "video", "--run", "Tidal power"], "r-open"),
]
VERB_IDS = [" ".join(v[1]) for v in VERBS]

#: What each bare form acts on when nothing is hidden — the behaviour it had
#: before this wave, and keeps.
BARE_TARGET = {"stop": "r-card", "pause": "r-card", "resume": "r-paused",
               "retry": "r-card", "skip": "r-card", "skip video": "r-card"}

DONE = {"stop": "stopped", "pause": "paused", "resume": "resumed",
        "retry": "retried", "skip": "skipped"}


# ── the defect ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("verb,bare,_named,_rid", VERBS, ids=VERB_IDS)
def test_a_bare_verb_beside_a_hidden_run_refuses_to_guess(live, capsys, verb, bare, _named, _rid):
    """⛔⛔ The defect: a bare verb acted on the newest run the chat could see.
    Before the fix every one of these wrote to "Mars colony"; before the fix
    under it, to the incognito run, printing its title."""
    rc, out, sent = _say(bare, capsys, [_secret(status="ongoing"), *VISIBLE])
    assert sent == [], f"a bare {verb} still wrote {sent}"
    assert rc == 1
    assert out.startswith(f"I can’t tell which run you mean, so I haven’t {DONE[verb]} anything.")
    assert "You have a run you can’t manage from chat." in out
    for title in LIVE_TITLES:
        assert f"“{title}”" in out, f"{title} is a run the person can choose"
    assert "Old run" not in out, "a finished run is not one a bare verb could mean"
    _nothing_of_it(out)


def test_the_refusal_tells_the_assistant_not_to_choose_for_them(live, capsys):
    """The list is for the PERSON. A chat model shown four runs and asked to
    stop "the run" could pick one itself — so the do-not-relay block says not to."""
    _rc, out, _sent = _say(["stop"], capsys, [_secret(status="ongoing"), *VISIBLE])
    shown, _, hidden = out.partition(sr._AGENT_ONLY_MARKER)
    assert "Tell me which one by name." in shown
    assert "Never pick one of these runs for them" in hidden
    assert "Do not stop any run until the person names one." in hidden


def test_with_nothing_else_going_it_says_so_and_lists_nothing(live, capsys):
    rc, out, sent = _say(["stop"], capsys,
                         [_secret(status="ongoing"), VISIBLE[-1]])
    assert sent == [] and rc == 1
    assert "You have a run you can’t manage from chat, and no other run in progress." in out
    assert "•" not in out and "Old run" not in out
    _nothing_of_it(out)


def test_the_json_refusal_carries_the_same_choice_and_nothing_hidden(live, capsys):
    rc, out, sent = _say(["--json", "pause"], capsys, [_secret(status="ongoing"), *VISIBLE])
    assert sent == [] and rc == 1
    payload = json.loads(out)
    assert payload["reason"] == "which_run" and payload["ok"] is False
    assert [r["title"] for r in payload["runs"]] == list(LIVE_TITLES)
    assert [r["runId"] for r in payload["runs"]] == ["r-card", "r-open", "r-paused", "r-stuck"]
    _nothing_of_it(out)


@pytest.mark.parametrize("said", ["pause", "resume", "retry", "skip"])
def test_the_chat_phrase_reaches_the_same_refusal(live, capsys, said):
    """The router hands a bare phrase to the same command; it must not find a
    path around the refusal."""
    rc, out, sent = _say(["do", said], capsys, [_secret(status="ongoing"), *VISIBLE])
    assert sent == [] and rc == 1
    assert out.startswith("I can’t tell which run you mean")
    _nothing_of_it(out)


# ── named verbs are untouched ───────────────────────────────────────────────

@pytest.mark.parametrize("verb,_bare,named,rid", VERBS, ids=VERB_IDS)
def test_a_named_verb_acts_exactly_as_it_does_with_nothing_hidden(live, capsys, verb, _bare, named, rid):
    rc, out, sent = _say(named, capsys, [_secret(status="ongoing"), *VISIBLE])
    assert _touched(sent) == {rid}, f"{' '.join(named)} wrote to {_touched(sent)}"
    assert rc == 0, out
    assert "can’t tell which run" not in out
    _nothing_of_it(out)
    # Exactly as today: the same words and the same writes as on an account
    # with no hidden run at all.
    assert _say(named, capsys, VISIBLE) == (rc, out, sent)


# ── a bare verb with nothing hidden, or only a finished hidden run ─────────

@pytest.mark.parametrize("verb,bare,_named,_rid", VERBS, ids=VERB_IDS)
def test_a_bare_verb_with_nothing_hidden_acts_on_its_usual_run(live, capsys, verb, bare, _named, _rid):
    rc, out, sent = _say(bare, capsys, VISIBLE)
    assert rc == 0, out
    assert _touched(sent) == {BARE_TARGET[" ".join(bare)]}


@pytest.mark.parametrize("verb,bare,_named,_rid", VERBS, ids=VERB_IDS)
def test_a_finished_hidden_run_does_not_stop_a_bare_verb(live, capsys, verb, bare, _named, _rid):
    """⭐ The rule is about a run the person could still MEAN. An incognito
    record that has finished and not yet been cleared away is not one."""
    with_it = _say(bare, capsys, [_secret(status="completed"), *VISIBLE])
    assert with_it == _say(bare, capsys, VISIBLE)
    assert with_it[0] == 0


def test_an_older_bridge_that_does_not_say_leaves_the_bare_verb_as_it_was(live, capsys, monkeypatch):
    """⛔ ABSENT IS NOT YES. A bridge from before this wave sends no
    `hiddenLiveRun`; it also lists every run, so the old pick is the right one."""
    real_get = sr._get

    def older_bridge(path, *a, **kw):
        code, body = real_get(path, *a, **kw)
        if path.startswith("/updates") and isinstance(body, dict):
            body.pop("hiddenLiveRun", None)
        return code, body

    monkeypatch.setattr(sr, "_get", older_bridge)
    rc, _out, sent = _say(["stop"], capsys, VISIBLE)
    assert rc == 0 and _touched(sent) == {"r-card"}


# ── what the bridge knows, and says ─────────────────────────────────────────

#: (the hidden record's fields beyond title/topic, whether it counts as going).
HIDDEN_STATES = [
    ({"status": "ongoing"}, True),
    ({"status": "queued"}, True),
    ({"status": "paused"}, True),
    ({"status": "errored"}, True),
    ({}, True),                                        # no status: when in doubt, yes
    ({"status": 3}, True),                             # not a string: the same
    ({"status": "stopped_by_watchdog"}, True),         # over, but waiting on the person
    ({"status": "paused_backend_restart_failed"}, True),
    ({"status": "stopped", "pendingDecision": CARD}, True),
    ({"status": "completed"}, False),
    ({"status": "stopped"}, False),
    ({"status": "archived"}, False),
    ({"status": "error"}, False),
    ({"status": "completed", "pendingDecision": {}}, False),  # an empty map is no card
]


@pytest.mark.parametrize("fields,going", HIDDEN_STATES,
                         ids=[f"{f.get('status', 'no-status')}{'+card' if f.get('pendingDecision') else ''}"
                              for f, _ in HIDDEN_STATES])
def test_the_bridge_says_a_hidden_run_is_going_and_nothing_more(live, fields, going):
    _Wire.documents = [_secret(**fields), *VISIBLE]
    r = requests.get(live + "/updates?limit=100")
    assert r.status_code == 200
    body = r.json()
    assert body["hiddenLiveRun"] is going
    assert [x["runId"] for x in body["runs"]] == [doc_id(d["name"]) for d in VISIBLE]
    _nothing_of_it(r.text)


def test_no_hidden_run_at_all_is_not_one_going(live):
    _Wire.documents = list(VISIBLE)
    assert requests.get(live + "/updates?limit=100").json()["hiddenLiveRun"] is False


def test_each_visible_run_carries_the_same_test(live):
    """The runs offered are the ones that pass the test the hidden run is held
    to: going, or waiting on the person (a card — "Stuck run" is stopped but
    carries one)."""
    _Wire.documents = list(VISIBLE)
    rows = requests.get(live + "/updates?limit=100").json()["runs"]
    assert {x["runId"]: x["live"] for x in rows} == {
        "r-card": True, "r-open": True, "r-paused": True, "r-stuck": True, "r-old": False}


def test_what_the_read_keeps_of_a_hidden_run_is_its_status_and_whether_a_card_is_on_it():
    """⛔ The husk is all the assistant holds of a run it must not show. The
    card's words are about the run, so they are never decoded."""
    _Wire.documents = [_secret(status="paused", pendingDecision={
        "kind": "login_required", "title": f"Sign in to continue {SECRET_TOPIC}"}), *VISIBLE]
    rows = _Wire(lambda force=False: "tok").list_researches(UID)
    assert rows.unshown == [{"status": "paused", "card": True}]
    assert [r["id"] for r in rows] == [doc_id(d["name"]) for d in VISIBLE]
