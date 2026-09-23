"""Wave 10.10 — the chat assistant never lists an incognito research.

An incognito research (wave 10.9) runs like any other paid run and leaves
nothing in Super Research once it ends. While it runs, its record sits in the
same `users/{uid}/researches` collection as every other research, and until this
wave the assistant listed that collection whole: `sr list`, a bare `sr status`,
the run list and the send-logs picker all showed its title and topic.

⛔⛔ THE ID IS THE ONLY SIGNAL. The web app mints `incog_<13-digit ms>_<n>`, and
the web app, both rules files and the research computer all carry the same
pattern. The agent is published on its own and cannot import any of them, so
this file holds the agent's copy to research.py's by EXECUTING research.py's own
predicate (lifted out of the file by its syntax tree) next to the agent's.
research.py's copy is held to the web app's and the rules' by
`tests/test_incognito_capability_109.py` in the backend root.

⛔ EVERY CONSUMER IS PINNED THROUGH THE REAL CLIENT. The filter lives in
`FirestoreRest.list_researches`; the route tests below replace only the network
under it, never the method itself, so a route that stopped going through it
would be seen.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, firestore_rest
from facade.firestore_rest import FirestoreRest, doc_id, is_incognito_research, to_value

UID = "u1"
RESEARCH_PY = Path(__file__).resolve().parents[2] / "research.py"

# ── the shape ───────────────────────────────────────────────────────────────

#: Ids the web app's `mintIncognitoId` can produce.
MINTED = (
    "incog_1758000000000_1",
    "incog_1758000000000_999999",
    "incog_0000000000000_0",
)


def _arabic_indic(digits: str) -> str:
    """The same digits in another script. Python's `\\d` accepts them; the web
    app's and the rules' `[0-9]` do not."""
    return "".join(chr(0x0660 + int(c)) for c in digits)


#: Ids that are somebody's ORDINARY research, to the web app, the rules and the
#: research computer alike. Each one sits just outside one part of the pattern.
ORDINARY = (
    "incog_notes",                          # a hand-made record
    "incog_1_1",                            # a timestamp that is not one
    "xincog_1758000000000_1",               # start anchor
    " incog_1758000000000_1",
    "incog_1758000000000_1x",               # end anchor
    "incog_1758000000000_1-copy",
    "incog_1758000000000_1 ",
    "incog_175800000000_1",                 # twelve digits
    "incog_17580000000000_1",               # fourteen digits
    "incog_1758000000000_1234567",          # a seven-digit counter
    "incog_1758000000000_",                 # no counter
    "incog_1758000000000",
    "incog-1758000000000_1",
    "incog_1758000000000-1",
    "INCOG_1758000000000_1",
    "incog_" + _arabic_indic("1758000000000") + "_1",
    "chat_1758000000000_1",                 # the ordinary chat mint
    "agent-0f3a9c21",                       # the agent's own mint
    "",
)

NOT_STRINGS = (None, 1758000000000, b"incog_1758000000000_1",
               ["incog_1758000000000_1"], {"id": "incog_1758000000000_1"})


@pytest.mark.parametrize("rid", MINTED)
def test_an_id_the_web_app_mints_is_incognito(rid):
    assert is_incognito_research(rid) is True


@pytest.mark.parametrize("rid", ORDINARY)
def test_every_other_id_is_an_ordinary_research(rid):
    assert is_incognito_research(rid) is False, (
        f"{rid!r} is an ordinary research and would vanish from its owner's lists")


def test_a_trailing_newline_is_ordinary_as_it_is_to_the_web_app_and_the_rules():
    """⛔ Python's `$` matches before a final newline; JavaScript's and the rules'
    do not. So the agent matches the WHOLE string, and an id with a newline on
    the end stays listed, exactly as the web app keeps showing it."""
    assert is_incognito_research("incog_1758000000000_1" + chr(10)) is False


@pytest.mark.parametrize("value", NOT_STRINGS, ids=lambda v: type(v).__name__)
def test_something_that_is_not_a_string_is_not_incognito(value):
    assert is_incognito_research(value) is False


# ── held to research.py's copy ──────────────────────────────────────────────

def _lift_machine_rule(src: str, filename: str):
    """research.py's `_INCOGNITO_ID_RE` and `_is_incognito_research`, EXECUTED.

    ⭐ Lifted by syntax tree rather than imported: importing research.py would
    start its logging and read its environment inside this suite. The two nodes
    run exactly as written there, against the real `re`.

    ⛔ A MISSING RULE IS A FAILURE, NEVER A SKIP. A parity pin that cannot say
    "I found nothing" reports agreement it never checked."""
    tree = ast.parse(src, filename=filename)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_INCOGNITO_ID_RE"
                        for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "_is_incognito_research")]
    if len(keep) != 2:
        raise AssertionError(
            f"{filename} no longer defines both _INCOGNITO_ID_RE and "
            f"_is_incognito_research at module level — the agent's copy in "
            f"facade/firestore_rest.py is held to them; move this pin with them")
    ns: dict = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), filename, "exec"), ns)
    return ns["_INCOGNITO_ID_RE"], ns["_is_incognito_research"]


def _disagreements(machine_rule) -> list:
    """Every id on which the research computer and the agent answer differently."""
    return [rid for rid in (*MINTED, *ORDINARY, *NOT_STRINGS)
            if bool(machine_rule(rid)) != is_incognito_research(rid)]


@pytest.fixture(scope="module")
def machine():
    assert RESEARCH_PY.is_file(), f"research.py is not at {RESEARCH_PY}"
    return _lift_machine_rule(RESEARCH_PY.read_text(encoding="utf-8"), str(RESEARCH_PY))


def test_the_agent_carries_research_pys_pattern(machine):
    machine_re, _ = machine
    assert firestore_rest._INCOGNITO_ID_RE.pattern == machine_re.pattern, (
        f"agent {firestore_rest._INCOGNITO_ID_RE.pattern!r} vs "
        f"research.py {machine_re.pattern!r}")


def test_the_agent_and_the_research_computer_answer_alike(machine):
    _, machine_rule = machine
    assert _disagreements(machine_rule) == []
    # Not vacuous: the corpus holds both answers.
    assert {bool(machine_rule(r)) for r in (*MINTED, *ORDINARY)} == {True, False}


#: A research.py whose counter drifted to seven digits — built here rather than
#: edited out of the real file, so this pin does not break when research.py's
#: own lines are reworded.
_DRIFTED_RESEARCH_PY = (
    "import re\n"
    '_INCOGNITO_ID_RE = re.compile(r"^incog_[0-9]{13}_[0-9]{1,7}$")\n'
    "def _is_incognito_research(research_id) -> bool:\n"
    "    return isinstance(research_id, str) and "
    "bool(_INCOGNITO_ID_RE.match(research_id))\n"
)


def test_a_research_py_whose_counter_takes_seven_digits_is_caught():
    """⭐ The pin, pointed at a research.py that drifted, has to SAY so."""
    _, rule = _lift_machine_rule(_DRIFTED_RESEARCH_PY, "research.py (drifted)")
    assert _disagreements(rule) == ["incog_1758000000000_1234567"]


def test_a_research_py_without_the_rule_fails_rather_than_skipping():
    """⛔ `pytest.raises` cannot see a skip: a skip is not an exception it
    catches, so the test would be reported SKIPPED and the gate stays green."""
    try:
        _lift_machine_rule("import re\n", "research.py (moved)")
    except BaseException as err:  # noqa: BLE001 — a skip is what this looks for
        assert type(err) is AssertionError, f"answered {type(err).__name__}: {err}"
        assert "no longer defines both" in str(err)
    else:
        raise AssertionError("a research.py without the rule was accepted")


# ── the one read every list goes through ────────────────────────────────────

SECRET_TITLE = "Secret merger"
SECRET_TOPIC = "Acme quietly buying Globex"
SECRET_ID = "incog_1758000000002_1"


def _doc(rid: str, **fields) -> dict:
    return {"name": f"projects/p/databases/(default)/documents/users/{UID}/researches/{rid}",
            "fields": {k: to_value(v) for k, v in fields.items()}}


def _account_docs() -> list:
    """Newest first, as the list query orders them. The incognito run is the
    NEWEST and still going, which is exactly when a bare verb would pick it."""
    return [
        _doc(SECRET_ID, title=SECRET_TITLE, topic=SECRET_TOPIC, status="ongoing"),
        _doc("r-open", title="Tidal power", topic="tidal power", status="ongoing"),
        _doc("incog_notes", title="My incog notes", status="completed"),
        _doc("r-old", title="Old run", status="completed"),
    ]


class _WireFS(FirestoreRest):
    """The REAL client, with only the network under it replaced."""

    documents: list = []
    devices: list = []
    held: dict | None = None

    def _request(self, method, url, *, json_body=None, allow_missing=False):
        path = url.split("/documents", 1)[-1]
        base = f"/users/{UID}/researches"
        if method == "GET" and path.startswith(base + "?"):
            return {"documents": [dict(d) for d in _WireFS.documents]}
        if method == "GET" and path.startswith(base + "/"):
            rid = path[len(base) + 1:]
            match = [d for d in _WireFS.documents if doc_id(d["name"]) == rid]
            return dict(match[0]) if match else None
        raise AssertionError(f"this test did not expect {method} {path}")

    def list_devices(self, uid):
        return [dict(d) for d in _WireFS.devices]

    def held_runs(self, uid, device_id):
        return dict(_WireFS.held) if _WireFS.held is not None else None


def test_the_list_leaves_out_every_incognito_research_and_nothing_else():
    _WireFS.documents = _account_docs()
    rows = _WireFS(lambda force=False: "tok").list_researches(UID)
    assert [r["id"] for r in rows] == ["r-open", "incog_notes", "r-old"]
    assert rows[0]["title"] == "Tidal power"


def test_the_documents_path_decides_never_a_field_on_it():
    """⛔ The rules and the web app read the PATH. A field named `id` can say
    anything, and `fields_to_dict` would hand it back as if it were the id."""
    _WireFS.documents = [
        _doc(SECRET_ID, id="r7", title=SECRET_TITLE),
        _doc("r9", id="incog_1758000000000_9", title="Ordinary, whatever it says"),
    ]
    rows = _WireFS(lambda force=False: "tok").list_researches(UID)
    assert [(r["id"], r["title"]) for r in rows] == [("r9", "Ordinary, whatever it says")]


# ── the routes and the chat client, over the loopback bridge ────────────────

def _load_sr():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_incognito_hidden_1010", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()

HELD = {"runs": [
    {"name": "incognito_1758000000002_1_20260923_101500", "researchId": SECRET_ID,
     "startedUtc": "2026-09-23T10:15:00Z", "status": "running"},
    {"name": "tidal_power_20260922_090000", "researchId": "r-open",
     "startedUtc": "2026-09-22T09:00:00Z", "status": "completed"},
], "truncated": False, "updatedAt": "2026-09-23T10:16:00Z"}


@pytest.fixture()
def live(monkeypatch):
    _WireFS.documents = _account_docs()
    _WireFS.devices = [{"id": "dev1", "name": "Studio PC", "ownerUid": UID,
                        "sharedWith": [], "pairConfirmedAt": True}]
    _WireFS.held = json.loads(json.dumps(HELD))
    monkeypatch.setattr(bridge, "FirestoreRest", _WireFS)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-test")
    sel = {"v": "dev1"}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device",
                        lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device",
                        lambda: sel.__setitem__("v", None))
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


def _assert_nothing_of_it(text: str, *, words=(SECRET_TITLE, SECRET_TOPIC, SECRET_ID)) -> None:
    for word in words:
        assert word not in text, f"{word!r} reached a chat surface"


def test_the_run_list_route_never_carries_it(live):
    r = requests.get(live + "/researches")
    assert r.status_code == 200
    assert [x["id"] for x in r.json()["researches"]] == ["r-open", "incog_notes", "r-old"]
    _assert_nothing_of_it(r.text)


def test_the_updates_route_never_carries_it_without_via_agent(live):
    """⛔ The plan called this route safe because the watchdog asks for
    `via=agent`. `sr list`, `sr status` and the bare verbs do not."""
    r = requests.get(live + "/updates?limit=20")
    assert r.status_code == 200
    assert [x["runId"] for x in r.json()["runs"]] == ["r-open", "incog_notes", "r-old"]
    _assert_nothing_of_it(r.text)


def test_the_active_runs_never_include_it(live):
    r = requests.get(live + "/updates?active=1")
    assert r.status_code == 200
    assert [x["runId"] for x in r.json()["runs"]] == ["r-open"]
    _assert_nothing_of_it(r.text)


def test_its_held_logs_keep_their_row_and_lose_their_title(live):
    """⭐ The web app's rule (`labelHeldRuns`): the logs are a real folder on the
    person's own computer and stay sendable; only the words go. (A research
    computer since 10.9 leaves such a run out of what it publishes; this is the
    agent's half, for one that does not.)"""
    r = requests.get(live + "/logs/runs")
    assert r.status_code == 200
    rows = {x["name"]: x for x in r.json()["runs"]}
    assert set(rows) == {HELD["runs"][0]["name"], HELD["runs"][1]["name"]}
    assert rows[HELD["runs"][0]["name"]]["title"] == ""
    assert rows[HELD["runs"][1]["name"]]["title"] == "Tidal power"
    _assert_nothing_of_it(r.text, words=(SECRET_TITLE, SECRET_TOPIC))


def test_asking_the_assistant_for_your_researches_never_shows_it(live, capsys):
    assert sr.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Tidal power" in out and "Old run" in out and "My incog notes" in out
    _assert_nothing_of_it(out)


def test_a_bare_status_reports_the_newest_run_it_can_show(live, capsys):
    """The incognito run is the newest and still going. A bare status used to
    pick it and print its topic; it now reports the newest ordinary run, by name."""
    assert sr.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Tidal power" in out
    _assert_nothing_of_it(out)
