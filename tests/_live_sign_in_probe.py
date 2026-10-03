"""The suite-wide sign-in guard's own probe — NOT part of the suite.

⛔ The leading underscore keeps it out of the ordinary run: it is a test that
FORGETS to stub the web's namer on purpose, and it must fail. Only
`tests/test_one_short_name_w19.py` runs it, in a child pytest, and reads that
run's verdict: the guard (conftest `live_sign_in_reached`) has to fail it.

⭐ Safe even if the guard is broken: the keystore and the network are stubbed
underneath, so a reach of the real helpers touches nothing real — it only shows
up as a probe that passes, which is the failure the parent test reports.
"""
import types

import research

UID = "uid-probe-w19-000000000000001"
RID = "chat_1790000000019_9"
TOPIC = "Grid storage economics for a small utility"


class _Store:
    def __init__(self, records):
        self.records = records

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
        data = self._s.records.get((self.path[1], self.path[3]))
        return types.SimpleNamespace(exists=data is not None,
                                     to_dict=lambda: dict(data or {}))


def test_a_test_that_forgets_to_stub_the_namer(monkeypatch):
    from auth import keystore
    import sys
    monkeypatch.setattr(keystore, "install_uuid", lambda: "probe")
    monkeypatch.setattr(keystore, "try_recover", lambda *_a: None)
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(
        post=lambda *a, **k: types.SimpleNamespace(status_code=599)))
    monkeypatch.setattr(research, "_firebase_db",
                        _Store({(UID, RID): {"title": "New Research"}}))
    monkeypatch.setattr(research, "_RESEARCH_NAMES_MADE", {})
    monkeypatch.setattr(research, "_update_research_doc", lambda *a, **k: True)
    assert research._research_name(TOPIC, UID, RID) == "Grid storage economics for a"
