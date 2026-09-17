"""The send-logs picker: a number for the agent's own log, and a chat that can
express a subset at all (wave 7.9-1, 2026-09-06).

⛔⛔ THE PLAN SAID "ADD 0 TO THE NUMBERED PICKER" AND THERE WAS NO PICKER. Measured
before building: `_print_held_runs` prints an index column and returns; nothing
reads a number from stdin on this surface, and a guard written in 2026-08-26
(`test_the_terminal_offers_it_as_a_flag_beside_machine`) records the decision NOT
to add a prompt — this screen prints one plan and asks one yes/no over all of it,
and a second reader would make it the only screen in the product that asks twice.
So the picker is the printed numbers plus `--runs`, and that is where `0` lands.
The terminal's default is unchanged: every run the list showed.

⛔⛔ AND CHAT COULD NOT NAME A SUBSET AT ALL. `sr.py send-logs` picked every run
the machine reported and offered `--none` as the only way to change that — all of
them, or none. The bridge has always accepted an arbitrary list; only the client
could not build one. So "the same picker in chat" is not a port of a prompt, it is
the first selection this surface has ever had.

⛔ THREE THINGS `--runs` NOW ACCEPTS AND DID NOT: `0` (the agent's own log), `all`
(which used to fail with "isn't holding a run called “all”" — a sentence naming a
run that never existed, while the flag's own help said the default was all), and a
signed number (`-1` fell through to the NAME branch and was refused as a missing
run name rather than as an index out of range).
"""

import contextlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli

SR = Path(cli.__file__).resolve().parent / "skill" / "scripts" / "sr.py"


def _sr():
    """The chat client, loaded by path — it is stdlib-only and not importable as
    part of the package."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sr_791", SR)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:  # pragma: no cover - the script guards its own __main__
        pass
    return mod


ROWS = [
    {"name": "r1", "title": "Tidal power", "startedUtc": "2026-08-24T10:00",
     "status": "completed", "sizeBytes": 1_100_000},
    {"name": "r2", "title": "Kelp", "startedUtc": "2026-08-25T10:00",
     "status": "completed", "sizeBytes": 2_200_000},
    {"name": "r3", "title": "Tides again", "startedUtc": "2026-08-26T10:00",
     "status": "failed", "sizeBytes": 300},
]


# ── the terminal's token vocabulary ───────────────────────────────────────────

def _resolve(spec):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = cli._resolve_selection(ROWS, spec)
    return out, buf.getvalue()


def test_zero_is_the_agents_own_log_and_not_a_run():
    """⛔⛔ THE WHOLE POINT, AND IT IS TWO ASSERTIONS. `0` must turn the agent log
    ON, and it must NOT appear among the run names — everything downstream of that
    list (the size total, the "N run(s)" sentence, the machine's own refusal to
    build an empty archive) is about material on the research computer, and this
    file is on the host running the command. Counting it would overstate what that
    computer was asked for by exactly one."""
    (names, agent_log), out = _resolve("0")
    assert agent_log is True
    assert names == []
    assert out == "", f"picking the agent log printed a complaint: {out!r}"


def test_zero_was_refused_before_and_the_refusal_is_gone():
    """⛔ IT USED TO PRINT "There is no run 0 in that list." and return None — the
    caller turns that into exit 1 and sends nothing. The slot was free BECAUSE it
    was rejected; this pins that the rejection went with the change."""
    (names, agent_log), out = _resolve("0")
    assert "no run 0" not in out
    assert (names, agent_log) == ([], True)


def test_zero_composes_with_runs():
    (names, agent_log), _ = _resolve("0,2")
    assert names == ["r2"]
    assert agent_log is True


def test_the_order_of_the_tokens_does_not_matter():
    """A person types what they think of first."""
    assert _resolve("2,0")[0] == _resolve("0,2")[0]


def test_all_is_a_word_the_picker_understands():
    """⛔⛔ IT WAS NOT. `--runs all` fell through to the name branch and printed
    "That computer isn't holding a run called “all”" — a run that never existed —
    while `--runs`'s own help said the default was all of them. Somebody who types
    the obvious word got an error about a fiction."""
    (names, agent_log), out = _resolve("all")
    assert names == ["r1", "r2", "r3"]
    assert agent_log is False
    assert out == ""


def test_all_is_case_insensitive_because_a_person_types_it_in_a_sentence():
    assert _resolve("ALL")[0][0] == ["r1", "r2", "r3"]


def test_all_and_zero_together_are_everything():
    (names, agent_log), _ = _resolve("all,0")
    assert names == ["r1", "r2", "r3"]
    assert agent_log is True


def test_all_does_not_duplicate_a_run_already_named():
    (names, _), _ = _resolve("2,all")
    assert names == ["r2", "r1", "r3"], "a run was listed twice"


def test_a_number_out_of_range_still_refuses_the_whole_request():
    """⛔ REFUSES, NEVER DROPS. Sending fewer runs than were asked for and
    reporting success is the one direction this must not fail in."""
    out, printed = _resolve("1,9")
    assert out is None
    assert "no run 9" in printed


def test_a_negative_number_is_named_as_an_index_not_as_a_run_name():
    """⛔ `"-1".isdigit()` is False, so a signed number fell through to the NAME
    branch and was refused with "isn't holding a run called “-1”" — a sentence
    about a run name nobody typed, on the one surface whose job is to say exactly
    what it could not place."""
    out, printed = _resolve("-1")
    assert out is None
    assert "no run -1" in printed
    assert "called" not in printed, "a number was reported as a missing run NAME"


def test_a_zero_spelled_some_other_way_is_still_out_of_range():
    """`00` is not the token `0` and is not a run. The ordinary sentence is the
    true one — a special case for a typo nobody types is a branch no test can
    justify."""
    out, printed = _resolve("00")
    assert out is None
    assert "no run 0" in printed


def test_a_name_that_is_not_held_still_refuses():
    """⚠ The terminal writes a straight apostrophe and the chat client a curly
    one, deliberately and throughout — see the note beside the retention line in
    `sr.py`. What must not differ is the CLAIM, which the agreement test below
    compares; the glyph is house style per file."""
    out, printed = _resolve("nope")
    assert out is None
    assert "holding a run called" in printed


def test_names_still_work_beside_the_numbers():
    (names, _), _ = _resolve("r3,1")
    assert names == ["r3", "r1"]


# ── the terminal's caller ─────────────────────────────────────────────────────

class _Wire:
    def __init__(self, *, rows=None, published=True, owned=True, row=None):
        self.rows = ROWS if rows is None else rows
        self.published = published
        self.owned = owned
        self.row = row or {"status": "done", "runCount": 1, "sizeBytes": 10}
        self.posts: list = []
        self.bodies: list = []

    def get(self, path, timeout=10.0):
        if path.startswith("/logs/runs"):
            return 200, {"deviceId": "dev1", "deviceName": "Studio PC",
                         "owned": self.owned, "published": self.published,
                         "truncated": False, "runs": self.rows}
        if path.startswith("/logs/bundle"):
            return 200, {"code": "K7XQ9B2M", "row": self.row}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, body=None, timeout=30.0):
        self.posts.append(path)
        self.bodies.append(body or {})
        if path == "/logs/agent-log":
            # ⛔⛔ THE STANDALONE REPLY CARRIES A CODE AND THE ATTACHED ONE DOES
            # NOT, exactly as the bridge answers. A fixture that returned the same
            # body for both would let the client print an empty support code and
            # still pass — which is what it did before this branch existed.
            if (body or {}).get("standalone"):
                return 200, {"ok": True, "sent": True, "standalone": True,
                             "code": "SOLO7X2M", "bytes": 12}
            return 200, {"ok": True, "sent": True, "bytes": 12}
        return 200, {"ok": True, "code": "K7XQ9B2M"}


def _args(**kw):
    base = dict(device=None, runs=None, none=False, machine=False, list=False,
                status=None, yes=True, no_wait=False, wait=1, verbose=False,
                agent_log=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _run(monkeypatch, args, wire):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_bridge_get", wire.get)
    monkeypatch.setattr(cli, "_bridge_post", wire.post)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_send_logs(args)
    return rc, buf.getvalue()


def test_runs_zero_actually_uploads_the_agent_log(monkeypatch):
    """⛔⛔ THE CALLER, NOT THE HELPER. A resolver that returns the flag and a
    caller that ignores it is the exact shape that has survived a sweep in this
    file's family before — the helper was pinned and the call site was mutated."""
    wire = _Wire()
    rc, out = _run(monkeypatch, _args(runs="0,1"), wire)
    assert rc == 0
    assert wire.posts == ["/logs/send", "/logs/agent-log"], wire.posts


def test_the_flag_and_the_number_are_the_same_request(monkeypatch):
    """Either route, never one overriding the other."""
    a = _Wire()
    _run(monkeypatch, _args(runs="1", agent_log=True), a)
    b = _Wire()
    _run(monkeypatch, _args(runs="0,1"), b)
    assert a.posts == b.posts == ["/logs/send", "/logs/agent-log"]


def test_saying_it_both_ways_is_not_answered_no(monkeypatch):
    """⛔ A person who passes the flag AND the number must not be answered by
    whichever the code read second."""
    wire = _Wire()
    _run(monkeypatch, _args(runs="0,1", agent_log=True), wire)
    assert "/logs/agent-log" in wire.posts


def test_the_agent_log_alone_is_SENT_with_its_own_code(monkeypatch):
    """⛔⛔ RE-AIMED IN WAVE 8: THIS WAS A REFUSAL AND IS NOW THE FEATURE. The old
    sentence — "it can only go up beside a bundle from that computer" — described
    the transport truthfully and left the reader with nothing to do, because the
    two commonest reasons to be sending an agent log are having no research
    computer and having one you cannot reach, and neither can produce a bundle.

    ⭐ IT ASSERTS MORE THAN THE REFUSAL DID: no bundle is requested (the old
    "an empty bundle was requested" guard survives verbatim), the ONE call made is
    the standalone upload, its body names nothing else, and the person is handed a
    support code — which is the thing the owner asked for and the thing that makes
    this artifact reachable by a developer at all."""
    wire = _Wire()
    rc, out = _run(monkeypatch, _args(runs="0"), wire)
    assert rc == 0
    assert "/logs/send" not in wire.posts, "an empty bundle was requested"
    assert wire.posts == ["/logs/agent-log"]
    assert wire.bodies[-1] == {"standalone": True}
    assert "Support code: SOLO7X2M" in out
    assert "only go up beside a bundle" not in out
    assert "There's nothing to send" not in out, (
        "the one thing they picked was reported as nothing")


def test_the_standalone_plan_is_still_a_consent_screen(monkeypatch):
    """⛔ NOTHING LEAVES BEFORE THE PROMPT. `--yes` is what the fixture passes, so
    the complement has to be driven explicitly — the plan has to be printed and the
    refusal has to send nothing."""
    wire = _Wire()
    # ⛔ THE PROMPT IS THE SUBJECT, so it is answered rather than assumed away.
    # `input()` raises under pytest's capture, which would make this test pass on
    # an exception instead of on a refusal.
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    rc, out = _run(monkeypatch, _args(runs="0", yes=False), wire)
    assert rc == 1
    assert wire.posts == []
    assert "Nothing was sent." in out
    # The three facts are stated BEFORE the prompt, not after it.
    assert "signed in through this agent" in out
    assert "rotated copies go too" in out
    assert "masked form of your email address" in out


def test_the_ordinary_nothing_to_send_sentence_survives(monkeypatch):
    """The complement, so the new branch cannot swallow the old one."""
    wire = _Wire(rows=[])
    rc, out = _run(monkeypatch, _args(none=True), wire)
    assert rc == 1
    assert "There's nothing to send" in out
    assert "beside a bundle" not in out


def test_the_agent_log_still_rides_a_machine_only_bundle(monkeypatch):
    """`--none --machine` is the documented pairing for a pairing problem, and it
    is exactly when the agent's log is worth having."""
    wire = _Wire()
    rc, out = _run(monkeypatch, _args(none=True, machine=True, agent_log=True), wire)
    assert rc == 0
    assert wire.posts == ["/logs/send", "/logs/agent-log"]


def test_none_still_wins_over_runs(monkeypatch):
    """⛔ It is checked first and it means what it has always meant."""
    wire = _Wire()
    _run(monkeypatch, _args(none=True, machine=True, runs="1,2"), wire)
    assert wire.bodies[0]["runNames"] == []


def test_all_reaches_the_wire_as_every_listed_run(monkeypatch):
    wire = _Wire()
    _run(monkeypatch, _args(runs="all"), wire)
    assert wire.bodies[0]["runNames"] == ["r1", "r2", "r3"]


def test_the_default_is_unchanged_by_the_new_tokens(monkeypatch):
    """⛔ NO --runs STILL MEANS EVERY LISTED RUN. The plan's line about an Enter
    default was written against a prompt this surface does not have; changing the
    default here would silently send less than a person asked for."""
    wire = _Wire()
    _run(monkeypatch, _args(), wire)
    assert wire.bodies[0]["runNames"] == ["r1", "r2", "r3"]
    assert "/logs/agent-log" not in wire.posts


# ── the choice is on screen ───────────────────────────────────────────────────

@pytest.mark.parametrize("published,rows", [
    (True, ROWS),          # the ordinary list
    (True, []),            # holding none of this person's runs
    (False, []),           # the machine has published no list at all
])
def test_the_zero_choice_is_printed_on_every_branch(monkeypatch, published, rows):
    """⛔⛔ ESPECIALLY THE EMPTY ONES. The no-runs cases are when somebody most
    wants this — the trouble is reaching the computer at all — and they are the
    branches with no list to hang a row off. `--agent-log` shipped in 2026-08-26
    and has been reachable only by somebody who already knew it existed; offering
    it only when there is something else to offer is how that happened."""
    wire = _Wire(rows=rows, published=published)
    _, out = _run(monkeypatch, _args(list=True), wire)
    assert "   0  the log from the agent on THIS host" in out


def test_the_zero_row_names_the_other_computer(monkeypatch):
    """⛔ IT IS NOT INDENTED INTO THE MACHINE'S TABLE, and it says whose it is.
    Every row above it is material on the research computer; this file is on the
    host running the command, and a sibling guard already polices the same
    confusion in the consent copy."""
    wire = _Wire()
    _, out = _run(monkeypatch, _args(list=True), wire)
    block = [ln for ln in out.splitlines() if ln.startswith("   0  ")
             or ln.startswith("      which may not be")]
    assert len(block) == 2, out
    assert "the machine you are typing on" in block[0]
    # ⛔ AND IT DOES NOT ASSERT THEY DIFFER. The recommended install co-locates
    # the agent and the backend — `_local_superresearch` exists because that is
    # the standard setup — so "a different computer" was false on most screens
    # that printed it, and a claim plainly wrong in front of you teaches you to
    # discount the rest of the plan.
    assert "which may not be that computer" in block[1]
    assert "a different computer, not that one" not in out


def test_the_runs_are_still_numbered_from_one(monkeypatch):
    """⛔ 0 IS FREE ONLY BECAUSE THE LIST STARTS AT 1. If the runs ever renumbered
    from zero the agent log would silently become run one."""
    wire = _Wire()
    _, out = _run(monkeypatch, _args(list=True), wire)
    assert "   1  Tidal power" in out
    assert "   0  Tidal power" not in out


# ── chat: the first selection this surface has ever had ───────────────────────

def _chat_resolve(spec):
    return _sr()._resolve_log_selection(ROWS, spec)


def test_chat_understands_zero():
    names, agent_log, refusal = _chat_resolve("0")
    assert (names, agent_log, refusal) == ([], True, [])


def test_chat_understands_all():
    names, agent_log, refusal = _chat_resolve("all")
    assert names == ["r1", "r2", "r3"]
    assert refusal == []


def test_chat_takes_a_spoken_list_with_spaces():
    """⭐ A CHAT, NOT A SHELL. The assistant relays what a person said, and "1 and
    3" reaches the client as an argument nobody quoted for argparse. Spaces are
    separators here for the same reason commas are."""
    names, _, refusal = _chat_resolve("1 3")
    assert names == ["r1", "r3"]
    assert refusal == []


def test_chat_refuses_an_index_it_cannot_place_and_says_the_range():
    names, _, refusal = _chat_resolve("9")
    assert names is None
    assert refusal and "numbered 1 to 3" in refusal[0]
    assert "0 is the agent" in refusal[0]


def test_chat_refuses_an_unknown_name():
    names, _, refusal = _chat_resolve("nope")
    assert names is None
    assert refusal and "isn’t holding a run called" in refusal[0]


def test_chat_and_the_terminal_agree_on_every_spec():
    """⛔⛔ TWO IMPLEMENTATIONS, ONE VOCABULARY. `sr.py` is stdlib-only and cannot
    import the facade, so this logic is a fourth copy of a thing that already
    exists twice — the same duplication `_SEND_LOGS_FAILURES` carries, policed the
    same way. A person told two different answers by two clients is the failure
    this file's family exists to prevent."""
    for spec in ("0", "all", "1", "1,3", "0,2", "r2", "ALL", "0,all"):
        term = cli._resolve_selection(ROWS, spec)
        chat_names, chat_agent, chat_refusal = _chat_resolve(spec)
        assert chat_refusal == [], spec
        assert term is not None, spec
        assert (chat_names, chat_agent) == term, spec


def test_chat_and_the_terminal_agree_on_what_they_refuse():
    for spec in ("9", "-1", "nope", "00"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            term = cli._resolve_selection(ROWS, spec)
        printed = buf.getvalue()
        chat_names, _, chat_refusal = _chat_resolve(spec)
        assert term is None, spec
        assert chat_names is None and chat_refusal, spec
        # ⛔ BOTH MUST SAY SOMETHING. A refusal nobody can read is the same as no
        # refusal at all, and this is reached only because something already
        # went wrong.
        assert "holding a run called" in printed or "no run" in printed, spec
        assert chat_refusal[0].strip(), spec
