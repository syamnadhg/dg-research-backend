"""Chat can name a subset, the numbers are on screen, and the flags the router
emits actually survive the trip to argparse (wave 7.9-1, 2026-09-06).

⛔⛔ A LIVE DEFECT, REPRODUCED BEFORE IT WAS FIXED. `_nl_resolve` has emitted
`--machine` and `--agent-log` since the send-logs routing row was written, and
`_DO_FLAGS` — the set `cmd_do` uses to decide what is a flag and what is free
text — listed neither. So both were classified as positionals and passed AFTER
`--`; `send-logs` takes no positional, argparse exited 2, and the SystemExit
handler turned the whole thing into "I didn't catch a Super Research request in
that." Not a dropped flag: a dropped REQUEST, on the route somebody reaches
because something is already wrong.

⛔ AND THE ALLOWLIST IS WHY IT WENT UNNOTICED FOR A WAVE. A hand-kept list beside
a function that grows new flags falls behind silently, and nothing reads one
against the other. The guard below regexes `_nl_resolve`'s own source, so any
future flag it learns to emit fails here rather than in a chat.

⛔ EVERY FLAG IN THAT SET MUST TAKE NO VALUE. A value-taking flag would put its
VALUE in the positional list and behind `--` — the same failure one argument
along — which is why `--runs` is reachable as an argument and NOT from natural
language.
"""

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"
_spec = importlib.util.spec_from_file_location("sr_chat_791", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_chat_791"] = sr
_spec.loader.exec_module(sr)

ROWS = [{"name": "r1", "title": "Tidal power", "startedUtc": "2026-08-24T10:00",
         "status": "completed", "sizeBytes": 1_100_000},
        {"name": "r2", "title": "Kelp", "startedUtc": "2026-08-25T10:00",
         "status": "completed", "sizeBytes": 2_200_000},
        {"name": "r3", "title": "Tides again", "startedUtc": "2026-08-26T10:00",
         "status": "failed", "sizeBytes": 300}]


class _Wire:
    def __init__(self, *, rows=None, published=True, owned=True, truncated=False):
        self.rows = ROWS if rows is None else rows
        self.published = published
        self.owned = owned
        self.truncated = truncated
        self.posts: list = []

    def get(self, path, timeout=None):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC",
                         "owned": self.owned, "published": self.published,
                         "runs": self.rows, "truncated": self.truncated}
        return 200, {"code": "K7XQ9B2M", "row": None}

    def post(self, path, body=None):
        self.posts.append({"path": path, "body": body})
        return 200, {"ok": True, "code": "K7XQ9B2M"}


@pytest.fixture()
def wire(monkeypatch):
    w = _Wire()
    monkeypatch.setattr(sr, "_get", w.get)
    monkeypatch.setattr(sr, "_post", w.post)
    return w


def _args(**kw):
    base = dict(json=False, confirm=False, machine=False, none=False,
                device="", status="", agent_log=False, runs="")
    base.update(kw)
    return SimpleNamespace(**base)


# ── the plan carries numbers now ──────────────────────────────────────────────

def test_the_plan_numbers_every_run(wire, capsys):
    """⛔⛔ EVERY ROW, NOT ONLY THE ONES GOING. A list of what is going stopped
    being a list somebody could pick FROM the moment a subset became expressible,
    and a run that is not on screen cannot be asked for."""
    sr.cmd_send_logs(_args(runs="1"))
    out = capsys.readouterr().out
    assert "1 • Tidal power" in out
    assert "2 · Kelp" in out
    assert "3 · Tides again" in out


def test_the_plan_says_which_are_not_picked_in_words(wire, capsys):
    """⛔ A MARKER ALONE IS NOT A SENTENCE. `•` versus `·` is one glyph apart and
    is the only thing separating "this is going" from "this is not" — in a chat
    relayed through a model and read on a phone."""
    sr.cmd_send_logs(_args(runs="1"))
    out = capsys.readouterr().out
    assert "Kelp — 2.1 MB   (not picked)" in out
    assert "Tidal power — 1.0 MB\n" in out


def test_the_count_still_names_only_what_is_going(wire, capsys):
    """⛔ THE ROWS GREW AND THE COUNT MUST NOT. Listing three and sending one is
    exactly the confusion the marker exists to prevent, so the words repeat it."""
    sr.cmd_send_logs(_args(runs="1"))
    out = capsys.readouterr().out
    assert "That’s 1 run(s)" in out


def test_the_zero_row_is_printed_even_when_it_is_not_going(wire, capsys):
    """⛔⛔ OR IT IS NOT AN OFFER. `--agent-log` shipped 2026-08-26 and has been
    reachable only by somebody who already knew it existed."""
    sr.cmd_send_logs(_args())
    out = capsys.readouterr().out
    assert "0 · the log from the agent on THIS host" in out
    assert "(not picked)" in out


def test_the_zero_row_flips_when_it_is_going(wire, capsys):
    sr.cmd_send_logs(_args(agent_log=True))
    out = capsys.readouterr().out
    assert "0 • the log from the agent on THIS host" in out


def test_the_plan_tells_them_the_numbers_are_sayable(wire, capsys):
    """⛔ THE NUMBERS ARE USELESS WITHOUT THIS LINE. Nothing else in the
    conversation says that saying a number is a thing they may do."""
    sr.cmd_send_logs(_args())
    out = capsys.readouterr().out
    assert "say which numbers to send instead" in out
    assert "0 is the agent’s own log" in out


def test_the_selection_reaches_the_wire(wire, capsys):
    sr.cmd_send_logs(_args(confirm=True, runs="1,3"))
    assert wire.posts[0]["body"]["runNames"] == ["r1", "r3"]


def test_runs_zero_turns_the_agent_log_on_in_chat(wire, capsys):
    sr.cmd_send_logs(_args(runs="0,1"))
    out = capsys.readouterr().out
    assert "0 • the log from the agent" in out
    assert "signed in through this agent since that file last rotated" in out


def test_a_refusal_stops_the_plan(wire, capsys):
    """⛔ REFUSES, NEVER DROPS — and never prints a plan for a selection it could
    not build. A plan is a consent screen; one built from a half-read request is
    a claim about a conversation that did not happen."""
    rc = sr.cmd_send_logs(_args(runs="9"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "numbered 1 to 3" in out
    assert "Say yes" not in out
    assert wire.posts == []


def test_the_agent_log_alone_is_refused_in_chat(wire, capsys):
    rc = sr.cmd_send_logs(_args(runs="0", none=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert "only go up beside a bundle" in out
    assert wire.posts == []


def test_the_default_is_still_every_listed_run(wire, capsys):
    sr.cmd_send_logs(_args(confirm=True))
    assert wire.posts[0]["body"]["runNames"] == ["r1", "r2", "r3"]


def test_none_still_wins_in_chat(wire, capsys):
    sr.cmd_send_logs(_args(confirm=True, machine=True, runs="1,2", none=True))
    assert wire.posts[0]["body"]["runNames"] == []


# ── the router's flags survive the trip ───────────────────────────────────────

@pytest.mark.parametrize("message,flag", [
    ("send the computer's own logs to support", "machine"),
    ("send the agent's log too to support", "agent_log"),
])
def test_a_natural_language_ask_reaches_the_command_with_its_flag(monkeypatch, message, flag):
    """⛔⛔ THE LIVE ONE. Before this, both of these ended in "I didn't catch a
    Super Research request in that" — argparse exited 2 on a flag pushed behind
    `--`, and the handler turned that into the clarify line."""
    # ⛔⛔ THROUGH `cmd_do`, NOT AROUND IT. The first version of this test
    # re-implemented cmd_do's argv assembly and then asserted on its own copy —
    # so it pinned the reasoning rather than the caller, and a change to cmd_do
    # itself would have left it green. Run the real dispatcher and look at the
    # namespace it actually handed to the command.
    seen = {}

    def _capture(ns):
        seen["ns"] = ns
        return 0

    monkeypatch.setattr(sr, "cmd_send_logs", _capture)
    rc = sr.main(["do", message])
    assert "ns" in seen, (
        f"cmd_do never reached send-logs for {message!r} — rc={rc}")
    assert getattr(seen["ns"], flag) is True, vars(seen["ns"])


def test_every_flag_the_router_can_emit_is_in_the_allowlist():
    """⛔⛔ THE STRUCTURAL GUARD, and the reason this defect is not coming back.
    A hand-kept list beside a growing function falls behind silently; this reads
    the function's own source, so a new flag fails here instead of in a chat."""
    import inspect
    src = inspect.getsource(sr._nl_resolve)
    emitted = set(re.findall(r'"(--[a-z][a-z0-9-]*)"', src))
    assert emitted, "the regex found no flags at all — it has stopped reading"
    missing = emitted - set(sr._DO_FLAGS)
    assert not missing, (
        f"_nl_resolve can emit {sorted(missing)}, which cmd_do will treat as free "
        "text and push behind `--` — the whole request then fails to parse")


def test_no_flag_in_the_allowlist_takes_a_value():
    """⛔ A VALUE-TAKING FLAG BREAKS THE SAME WAY ONE ARGUMENT ALONG: the flag is
    kept and its VALUE goes behind `--`. This is why `--runs` is an argument and
    not a natural-language route."""
    parser = sr.build_parser()
    seen = {}
    for action in parser._subparsers._group_actions[0].choices.values():
        for act in action._actions:
            for opt in act.option_strings:
                if opt in sr._DO_FLAGS:
                    seen[opt] = act.nargs
    assert seen, "no subcommand declares any of the routed flags"
    for opt, nargs in seen.items():
        assert nargs == 0, f"{opt} takes a value and cannot be routed from chat"


def test_the_runs_flag_is_actually_registered_on_the_chat_parser():
    """⛔ NOTHING IN THE SUITE WENT THROUGH THE PARSER. Every chat test built a
    namespace by hand, so `sl.add_argument("--runs", …)` could be deleted and the
    whole picker would still pass — while the real client exited 2 on the flag."""
    ns = sr.build_parser().parse_args(["send-logs", "--runs", "1,3"])
    assert ns.runs == "1,3"
    assert sr.build_parser().parse_args(["send-logs"]).runs == ""


def test_the_skill_routes_a_subset_ask_to_the_flag():
    """⛔ THE ROUTING TABLE IS WHAT THE ASSISTANT READS. A picker the table never
    mentions is reachable only by somebody typing at a terminal."""
    text = _SKILL.read_text(encoding="utf-8")
    row = next((ln for ln in text.splitlines()
                if ln.startswith("|") and "--runs" in ln), "")
    assert row, "the routing table has no --runs row"
    assert "only the first two" in row or "not all of them" in row, row
    assert "--confirm" in row, "the row does not say to pass it on the send too"


def test_the_allowlist_still_holds_the_two_it_always_had():
    """⛔ The repair is an addition. Dropping either of the research flags would
    break `research --no-video` the same way, silently."""
    assert {"--no-video", "--no-email"} <= set(sr._DO_FLAGS)


# ── the document a model actually reads ───────────────────────────────────────

def test_the_skill_tells_the_model_the_numbers_can_be_passed_back():
    """⛔ THE ROUTING TABLE IS WHAT THE ASSISTANT READS TO DECIDE WHAT TO RUN. A
    picker the document never mentions is a picker only a person typing at a
    terminal can reach — which is the gap this wave exists to close."""
    text = _SKILL.read_text(encoding="utf-8")
    # ⛔ THE LEAD-IN TOO. A first version of this asserted only the two backtick
    # phrases, which live on the bullet's CONTINUATION lines — so a mutant that cut
    # the sentence introducing them was satisfied by the wreckage it left behind.
    # The same neighbouring-line shape three mutants in this family have exploited.
    assert "**Which runs go** is the user's to choose, and the plan numbers them" in text
    assert "`--runs` takes the" in text
    assert "`0` is the agent's own log and `all` is every" in text
    assert "A run the plan did not list" in text


def test_the_skill_says_to_pass_the_selection_on_confirm_too():
    """⛔⛔ TWO PROCESSES, AND THE SECOND REMEMBERS NOTHING. The plan and the send
    are separate invocations; a selection given only to the first would be
    silently replaced by the default — every run — on the call that actually
    sends."""
    text = _SKILL.read_text(encoding="utf-8")
    assert "Pass the same `--runs` on `--confirm`" in text


def test_the_skill_says_what_the_agent_log_holds_and_whose_it_is():
    text = _SKILL.read_text(encoding="utf-8")
    assert "everyone who has signed in on that host" in text
    assert "masked form of their email address" in text
    assert "not only them" in text


def test_the_skill_says_the_agent_log_cannot_go_alone():
    text = _SKILL.read_text(encoding="utf-8")
    assert "`--runs 0`\n  alone is refused with that sentence" in text
