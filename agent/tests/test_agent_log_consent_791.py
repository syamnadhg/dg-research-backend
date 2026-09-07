"""What a person is told about the agent's own log before they agree to send it
(wave 7.9-1, 2026-09-06).

⛔⛔ THE CONSENT LINE SAID WHAT THE FILE IS NOT. "A connection and sign-in record,
not research content" — a category, and the half of it that is a negative. It
named no field, and it named nobody. The MACHINE's line four sentences above it
has always said whose material it sweeps up ("for everyone who uses it"), and it
says so about a computer everyone already understands to be shared. The agent's
log is on whatever host somebody happens to be typing on, which reads as personal
and is not: a second person who signed in there is in that file.

⛔⛔ AND NOTHING GATES THE UPLOAD ON WHO OWNS THAT HOST — measured at three
layers: the client does not check, the bridge route does not check, and the web
route that stores it does not check. That is not an oversight to close. An agent
host has NO owner: `owned` is a per-device fact about a research computer, and
there is no equivalent question to ask about the machine running the bridge. So
the honest move is to say it, not to invent a gate that would have to guess.

⛔ THE FIELDS ARE MEASURED, NOT IMAGINED. In the file the uploader actually reads:
the account's masked email on every connect (`a***@gmail.com`), the account id,
the ids of the computers and runs this agent touched — and, on any failed lookup,
the full Firestore document path, which carries the account id unmasked.

⛔ THE NOT-GOING SENTENCES ARE UNCHANGED ON PURPOSE. A parametrised guard in
`test_agent_log_out_0826.py` pins them as whole strings on both clients, because a
fragment match was satisfiable by a neighbouring line about a different computer.
Only the positive branch is enriched here.
"""

import contextlib
import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_consent_791", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_consent_791"] = sr
_spec.loader.exec_module(sr)

ROWS = [{"name": "r1", "title": "Tidal power", "startedUtc": "2026-08-24T10:00",
         "status": "completed", "sizeBytes": 1_100_000},
        {"name": "r2", "title": "Kelp", "startedUtc": "2026-08-25T10:00",
         "status": "completed", "sizeBytes": 2_200_000}]


# ── the terminal ──────────────────────────────────────────────────────────────

class _Wire:
    def __init__(self):
        self.posts: list = []
        self.bodies: list = []

    def get(self, path, timeout=10.0):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC", "owned": True,
                         "published": True, "truncated": False, "runs": ROWS}
        return 200, {"code": "K7XQ9B2M", "row": {"status": "done", "runCount": 1,
                                                 "sizeBytes": 10}}

    def post(self, path, body=None, timeout=30.0):
        self.posts.append(path)
        self.bodies.append(body or {})
        if path == "/logs/agent-log":
            return 200, {"ok": True, "sent": True, "bytes": 12}
        return 200, {"ok": True, "code": "K7XQ9B2M"}


def _plan(monkeypatch, **kw):
    base = dict(device=None, runs=None, none=False, machine=False, list=False,
                status=None, yes=True, no_wait=False, wait=1, verbose=False,
                agent_log=False)
    base.update(kw)
    wire = _Wire()
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_bridge_get", wire.get)
    monkeypatch.setattr(cli, "_bridge_post", wire.post)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_send_logs(SimpleNamespace(**base))
    return buf.getvalue()


def test_the_terminal_says_whose_records_are_in_it(monkeypatch):
    """⛔⛔ THE FACT THE MACHINE'S LINE HAS AND THIS ONE DID NOT."""
    out = _plan(monkeypatch, agent_log=True)
    assert "everyone who has signed in on THIS host, not only you" in out


def test_the_terminal_says_nothing_checks_who_owns_that_host(monkeypatch):
    """⛔ AND WHY, or it reads as a bug rather than a property. There is no owner
    to ask on a machine like that — `owned` is a fact about a research computer."""
    out = _plan(monkeypatch, agent_log=True)
    assert "no owner to ask" in out
    assert "nothing checks" in out


def test_the_terminal_names_the_fields(monkeypatch):
    """⛔ "Not research content" is what it is NOT. These are measured."""
    out = _plan(monkeypatch, agent_log=True)
    assert "masked form of your email address" in out
    assert "account id" in out
    assert "ids of the computers and runs" in out


def test_none_of_that_appears_when_the_log_is_not_going(monkeypatch):
    """⛔⛔ THE DIRECTION THAT MATTERS MOST. A plan that describes what is in a
    file it is NOT sending is telling somebody their address is going when it is
    not — and it would make the negative sentence beside it read as a formality."""
    out = _plan(monkeypatch, agent_log=False)
    assert "The agent's own log on this host is NOT included." in out
    assert "everyone who has signed in" not in out
    assert "masked form of your email address" not in out


def test_the_terminal_still_says_what_it_is(monkeypatch):
    """The enrichment adds; it does not replace."""
    out = _plan(monkeypatch, agent_log=True)
    assert "connection and sign-in record, not research content" in out
    assert "never leaves unless asked for" in out


def test_the_machine_line_is_untouched(monkeypatch):
    """⛔ A guard for the neighbour. The new sentences sit between two lines about
    a DIFFERENT computer, and the one failure this family keeps repeating is a
    claim landing on the wrong machine."""
    out = _plan(monkeypatch, agent_log=True, machine=True)
    assert "for everyone who uses it" in out
    assert "its pairing and sign-in records" in out


def test_neither_new_sentence_uses_the_banned_phrase(monkeypatch):
    """⛔ "this computer's own logs" means the RESEARCH computer to somebody
    running the command from a third machine. A sibling guard bans it across
    these files; this pins the sentences added here specifically, because that
    guard reads source and would not notice a runtime-composed string."""
    out = _plan(monkeypatch, agent_log=True).lower()
    assert "this computer's own log" not in out
    assert "this computer’s own log" not in out


# ── chat ──────────────────────────────────────────────────────────────────────

class _ChatWire:
    def __init__(self):
        self.posts: list = []

    def get(self, path, timeout=None):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC", "owned": True,
                         "published": True, "runs": ROWS, "truncated": False}
        return 200, {"code": "K7XQ9B2M", "row": None}

    def post(self, path, body=None):
        self.posts.append({"path": path, "body": body})
        return 200, {"ok": True, "code": "K7XQ9B2M"}


@pytest.fixture()
def chat(monkeypatch):
    w = _ChatWire()
    monkeypatch.setattr(sr, "_get", w.get)
    monkeypatch.setattr(sr, "_post", w.post)
    return w


def _chat_args(**kw):
    base = dict(json=False, confirm=False, machine=False, none=False,
                device="", status="", agent_log=False, runs="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_chat_says_whose_records_are_in_it(chat, capsys):
    sr.cmd_send_logs(_chat_args(agent_log=True))
    out = capsys.readouterr().out
    assert "everyone who has signed in on that host, not only you" in out


def test_chat_says_nothing_checks_who_owns_that_host(chat, capsys):
    sr.cmd_send_logs(_chat_args(agent_log=True))
    out = capsys.readouterr().out
    assert "no owner to ask" in out
    assert "nothing checks" in out


def test_chat_names_the_fields(chat, capsys):
    sr.cmd_send_logs(_chat_args(agent_log=True))
    out = capsys.readouterr().out
    assert "masked form of your email address" in out
    assert "account id" in out
    assert "ids of the computers and runs" in out


def test_chat_says_none_of_it_when_the_log_is_not_going(chat, capsys):
    sr.cmd_send_logs(_chat_args(agent_log=False))
    out = capsys.readouterr().out
    assert "The agent’s own log is not included." in out
    assert "everyone who has signed in" not in out


def test_the_two_clients_state_the_same_three_facts(monkeypatch, chat, capsys):
    """⛔⛔ THE FACT, NOT THE STRING. These files speak differently on purpose —
    one writes straight apostrophes and the other curly — so a byte comparison
    would either fail or force a foreign sentence into one of them. What must not
    differ is what a person is told, because somebody who asks two clients the
    same question must not get two answers."""
    sr.cmd_send_logs(_chat_args(agent_log=True))
    chat_out = capsys.readouterr().out
    term_out = _plan(monkeypatch, agent_log=True)
    for claim in ("everyone who has signed in", "no owner to ask", "nothing checks",
                  "masked form of your email address", "account id",
                  "ids of the computers and runs"):
        assert claim in chat_out, claim
        assert claim in term_out, claim
