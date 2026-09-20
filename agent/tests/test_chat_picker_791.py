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
import inspect
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
        if path == "/logs/agent-log":
            # ⛔⛔ ROUTE-SHAPED, NOT ONE REPLY FOR EVERY POST. This used to answer
            # every path with the send-logs body, which has no `sent` key — so the
            # agent-log client read every upload as an EMPTY log and the "nothing
            # to send" branch swallowed every assertion about a successful one.
            # A fixture that cannot tell the two apart tests neither.
            return 200, {"ok": True, "sent": True, "standalone": True,
                         "code": "K7XQ9B2M", "bytes": 4096}
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


def _status_out(monkeypatch, capsys, **extra):
    """Run `--status CODE` against a bridge reply with no row and the given
    diagnostic extras."""
    def get(path, timeout=None):
        return 200, {"code": "BUNDLE11", "row": None, **extra}
    monkeypatch.setattr(sr, "_get", get)
    sr.cmd_send_logs(_args(status="BUNDLE11"))
    return capsys.readouterr().out


def test_a_machine_that_took_the_request_is_reported_as_packaging(monkeypatch, capsys):
    """⭐ THE COMMAND IS GONE, SO A MACHINE READ IT. Worker 1 deletes the command
    before dispatching, which makes its absence a delivery receipt — the only one
    this protocol has."""
    out = _status_out(monkeypatch, capsys, picked=True, deviceOnline=True,
                      deviceName="Macbook", ageSeconds=90)
    assert "HAS picked the request up" in out, out
    assert "packaging it" in out


def test_a_machine_that_never_took_it_and_is_not_answering_is_terminal(monkeypatch, capsys):
    """⛔⛔ THE CASE THAT USED TO BE UNSAYABLE, AND THE ONE THAT HAPPENED. The
    command is still sitting there, so nothing read it; the device is not
    answering, so nothing will until it is back. The device's stale gate MARKS
    rather than deletes, so an unread command persists indefinitely — this is not
    a race, it is a standing state. Telling somebody to keep waiting would be
    telling them to wait for nothing."""
    out = _status_out(monkeypatch, capsys, picked=False, deviceOnline=False,
                      deviceName="Macbook", ageSeconds=1020)
    assert "hasn’t picked up the request" in out, out
    assert "isn’t answering right now" in out
    assert "17 minutes" in out
    # ⛔ NEVER "it is off" — a late heartbeat reads identically to a dead machine
    assert "is off" not in out


def test_an_unknown_receipt_keeps_the_honest_ambiguity(monkeypatch, capsys):
    """⛔ `picked` IS ABSENT WHEN THIS BRIDGE DID NOT MINT THE CODE — restarted
    since the send, or a code from another host. Then nothing distinguishes the
    two causes and the old sentence is the true one. It is the FALLBACK, not the
    default; making it the default is what produced four identical non-answers."""
    out = _status_out(monkeypatch, capsys, deviceName="Macbook")
    assert "may still be packaging it, or may not have picked the request up" in out


def test_the_half_that_did_arrive_is_named_on_the_waiting_branch(monkeypatch, capsys):
    """⛔ ON THIS BRANCH THE AGENT'S LOG IS THE ONLY THING SUPPORT CAN READ. A
    message about the half that did not arrive is exactly where somebody forgets
    the other half went at all."""
    out = _status_out(monkeypatch, capsys, picked=False, deviceOnline=False,
                      deviceName="Macbook", agentLogCode="AGENTLOG")
    assert "AGENTLOG" in out, out
    assert "did go, separately" in out


def _two_code_wire(monkeypatch):
    """A wire that answers the two routes with DIFFERENT codes, so a test can
    tell which code came from which send. The shared fixture answers both with
    one string, which cannot distinguish them."""
    seen = []

    def post(path, body=None):
        seen.append({"path": path, "body": body})
        if path == "/logs/agent-log":
            return 200, {"ok": True, "sent": True, "standalone": True,
                         "code": "AGENTLOG", "bytes": 4096}
        return 200, {"ok": True, "code": "BUNDLE11"}

    w = _Wire()
    monkeypatch.setattr(sr, "_get", w.get)
    monkeypatch.setattr(sr, "_post", post)
    return seen


def test_the_agent_log_goes_first_and_alone_on_a_combined_confirm(monkeypatch, capsys):
    """⭐⭐ THE LOCAL FILE STOPS WAITING FOR A REMOTE MACHINE. It used to be
    DEFERRED: the confirmed send printed "the agent's own log goes up once that
    computer's bundle lands" and handed over `--status <CODE> --agent-log`, which
    the bridge refuses until the machine's row exists. On 2026-09-20 the Macbook
    never answered, so the refusal never lifted — and a file sitting readable on
    THIS disk, needing no device and nobody's permission, was lost along with a
    bundle it had no reason to be attached to.

    ⛔ ORDER IS THE FIX, NOT A DETAIL. `/logs/agent-log` must be posted BEFORE
    `/logs/send`, because `/logs/send` writes a Firestore command and answers 502
    when Firestore is the broken thing — which is one of the states people send
    agent logs about."""
    seen = _two_code_wire(monkeypatch)
    sr.cmd_send_logs(_args(confirm=True, runs="1", agent_log=True))
    assert [p["path"] for p in seen] == ["/logs/agent-log", "/logs/send"], seen
    # ⛔ STANDALONE, AND CARRYING THE CONSENT CLAIM — symmetric with /logs/send.
    assert seen[0]["body"] == {"standalone": True, "consent": True}


def test_both_codes_are_reported_and_each_is_named(monkeypatch, capsys):
    """⛔ TWO BARE CODES IN A CHAT MESSAGE IS HOW SOMEBODY QUOTES THE WRONG ONE AT
    SUPPORT. Each has to arrive with its role attached."""
    _two_code_wire(monkeypatch)
    sr.cmd_send_logs(_args(confirm=True, runs="1", agent_log=True))
    out = capsys.readouterr().out
    assert "AGENTLOG" in out and "BUNDLE11" in out, out
    said = out[:out.index(sr._AGENT_ONLY_MARKER)]
    assert "agent’s own log" in said and "AGENTLOG" in said
    assert "BUNDLE11" in said


def test_the_already_sent_log_is_never_offered_a_second_time(monkeypatch, capsys):
    """⛔⛔ THE DUPLICATE IS REFUSED BY NAME, NOT LEFT TO JUDGEMENT. The old
    directive pointed at `--status <CODE> --agent-log`; run after a two-code send
    that uploads the SAME file again under the other code, spending one of the
    account's ten hourly uploads on a copy of material carrying a masked email and
    a whole sign-in trail."""
    _two_code_wire(monkeypatch)
    sr.cmd_send_logs(_args(confirm=True, runs="1", agent_log=True))
    out = capsys.readouterr().out
    directives = out[out.index(sr._AGENT_ONLY_MARKER):]
    assert "ALREADY SENT" in directives, directives
    assert "Do NOT run" in directives
    # ⛔ and the old deferral promise is gone from the whole message
    assert "goes up once that computer’s bundle lands" not in out


def test_a_failed_local_send_does_not_stop_the_machine_request(monkeypatch, capsys):
    """⛔ NEVER FATAL, IN EITHER DIRECTION. The local upload runs first, so a
    failure there must not take the machine request with it — and the person must
    be told which half did not go rather than left to infer it from one code."""
    seen = []

    def post(path, body=None):
        seen.append(path)
        if path == "/logs/agent-log":
            return 500, {"error": "storage unreachable"}
        return 200, {"ok": True, "code": "BUNDLE11"}

    w = _Wire()
    monkeypatch.setattr(sr, "_get", w.get)
    monkeypatch.setattr(sr, "_post", post)
    rc = sr.cmd_send_logs(_args(confirm=True, runs="1", agent_log=True))
    out = capsys.readouterr().out
    assert seen == ["/logs/agent-log", "/logs/send"], seen
    assert rc == 0, "a failed local half must not fail the whole command"
    assert "didn’t go" in out and "BUNDLE11" in out, out


def test_no_research_computer_still_sends_the_local_half(monkeypatch, capsys):
    """⭐⭐ THE STATE THE OLD CODE LOST IT IN MOST RELIABLY. `/logs/runs` refuses
    with `no_devices`, and the whole command used to return on that branch — so
    somebody whose problem WAS having no reachable computer could not send the one
    file that describes it. The upload now happens above that fetch."""
    seen = []

    def get(path, timeout=None):
        if path.startswith("/logs/runs"):
            return 400, {"reason": "no_devices", "error": "no computer"}
        return 200, {"devices": [], "selectedDeviceId": None}

    def post(path, body=None):
        seen.append(path)
        return 200, {"ok": True, "sent": True, "standalone": True,
                     "code": "AGENTLOG", "bytes": 10}

    monkeypatch.setattr(sr, "_get", get)
    monkeypatch.setattr(sr, "_post", post)
    sr.cmd_send_logs(_args(confirm=True, runs="1", agent_log=True))
    out = capsys.readouterr().out
    assert seen == ["/logs/agent-log"], seen
    # ⛔ AND THE RECEIPT IS PRINTED ON THAT BRANCH, not swallowed by the refusal
    assert "AGENTLOG" in out, out


def test_row_zero_leads_and_the_list_counts_up(wire, capsys):
    """⭐⭐ READING ORDER MUST MATCH NUMBERING ORDER. Row 0 printed LAST, after
    runs 1..N, so the plan handed a relay a list that counts 1, 2, 0 — and no
    assistant will show a person a list that counts down. On 2026-09-20 one
    renumbered into its own "1."/"2.", the person answered in the RELAY's numbers,
    and those are not this command's numbers. With one run that refused loudly;
    with two it would have sent a valid but WRONG run's results, links and account
    email to support under a consent given for a different row."""
    sr.cmd_send_logs(_args())
    rows = [ln for ln in capsys.readouterr().out.splitlines()
            if ln.startswith("  Run ")]
    assert [ln.split()[1] for ln in rows] == ["0", "1", "2", "3"], rows


def test_the_machine_header_scopes_only_what_is_under_it(wire, capsys):
    """⛔ ROW 0 IS NOT ON THE RESEARCH COMPUTER, so it must not sit under a line
    naming one. The header used to read "the logs from “Studio PC”:" and cover
    the whole list — survivable only while row 0 was far enough down to read as
    an aside. Moving 0 to the top without de-scoping the header would have traded
    a numbering confusion for a locality one, in a CONSENT screen, reversing the
    reason cli.py:2688 gives for `_print_agent_log_choice` existing at all."""
    out = (sr.cmd_send_logs(_args()), capsys.readouterr().out)[1]
    lines = out.splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith("I can send"))
    zero = next(i for i, ln in enumerate(lines) if ln.startswith("  Run 0 "))
    scope = next(i for i, ln in enumerate(lines) if ln.startswith("From “"))
    one = next(i for i, ln in enumerate(lines) if ln.startswith("  Run 1 "))
    assert head < zero < scope < one, lines
    # ⛔ and the top line names NO computer
    assert "Studio PC" not in lines[head]


def test_every_row_carries_its_number_inside_the_text(wire, capsys):
    """⭐⭐ THE NUMBER RIDES IN THE TEXT, NOT IN THE POSITION. A bare leading digit
    is positional, so a relay that re-wraps the rows into its own ordered list
    creates a SECOND numbering with equal authority and the two silently disagree.
    A label the client supplies cannot be re-wrapped away — the relay's own index
    becomes visibly redundant beside it instead of competing with it.

    ⛔ THIS IS MEASURED, NOT ASSUMED. In the 2026-09-20 transcript the assistant
    invented exactly these labels and mapped them CORRECTLY while getting the
    order wrong. The label is the part that already survives a relay; the bare
    digit is the part that did not."""
    sr.cmd_send_logs(_args())
    out = capsys.readouterr().out
    for n in range(4):
        assert len([ln for ln in out.splitlines()
                    if ln.startswith(f"  Run {n} ")]) == 1, (n, out)


def test_the_row_carries_the_runs_own_status(wire, capsys):
    """⛔ THE TERMINAL HAS ALWAYS PRINTED IT AND THE CHAT DROPPED IT. `/logs/runs`
    forwards each run's status; `_log_run_label` discarded it, so a run that had
    STOPPED mid-phase was offered as a plain title and a size. Somebody choosing
    what to send support is choosing between runs, and which one broke is the
    thing they are choosing on."""
    sr.cmd_send_logs(_args(runs="all"))
    out = capsys.readouterr().out
    failed = next(ln for ln in out.splitlines() if "Tides again" in ln)
    assert "failed" in failed, failed
    ok = next(ln for ln in out.splitlines() if "Tidal power" in ln)
    assert "completed" in ok, ok


def test_a_machine_that_is_not_answering_says_so_before_the_offer(monkeypatch, capsys):
    """⭐⭐ THE FACT WAS ON THE WIRE AND NEVER PRINTED. `/logs/runs` returns
    `online`; this client dropped it. The MACHINE zips and uploads the bundle —
    the app only mints the code — so a machine that is not answering yields a
    support code that names nothing, with no error anywhere. On 2026-09-20 that
    produced four status checks over seventeen minutes, each answered "nothing
    has come back yet", while the fact that explained it was already in hand.

    ⛔ IT SAYS SO; IT DOES NOT REFUSE. This is heartbeat freshness, not truth."""
    wire = _Wire()
    base = wire.get

    def off(path, timeout=None):
        code, body = base(path, timeout)
        if path.startswith("/logs/runs"):
            body = {**body, "online": False}
        return code, body

    monkeypatch.setattr(sr, "_get", off)
    monkeypatch.setattr(sr, "_post", wire.post)
    sr.cmd_send_logs(_args())
    out = capsys.readouterr().out
    scope = next(ln for ln in out.splitlines() if ln.startswith("From “"))
    assert "isn’t answering right now" in scope, scope
    # ⛔ NEVER "is off" — a late heartbeat reads identically to a dead machine
    assert "is off" not in out
    # ⛔ AND ROW 0 IS STILL OFFERED: it needs no machine at all, which is exactly
    # why it must survive this branch
    assert any(ln.startswith("  Run 0 ") for ln in out.splitlines()), out


def test_the_relay_rule_rides_with_the_rows_not_only_in_skill_md(wire, capsys):
    """⭐⭐ SKILL.md SAYS "relay verbatim" TWELVE TIMES — once in bold and
    output-specific to this exact plan — and on 2026-09-20 the plan was reflowed
    into a Markdown list under a second set of numbers anyway. Prose three hundred
    lines away is measured-failed. The two relay rules in this skill that have
    NEVER failed are both carried IN BAND (`_AGENT_ONLY_MARKER`, the `MEDIA:`
    line), attached to the bytes they govern. So is this one.

    ⛔ AND IT IS LAST. The action directive is what the assistant must DO; a
    formatting rule placed above it pushes the thing that matters into second
    place."""
    sr.cmd_send_logs(_args())
    lines = capsys.readouterr().out.splitlines()
    marker = next(i for i, ln in enumerate(lines) if sr._AGENT_ONLY_MARKER in ln)
    rule = next(i for i, ln in enumerate(lines) if "Do NOT re-number them" in ln)
    action = next(i for i, ln in enumerate(lines) if ln.startswith("If they say yes"))
    rows = [i for i, ln in enumerate(lines) if ln.startswith("  Run ")]
    # rows above the marker (the user sees them), rule below it, action first
    assert max(rows) < marker < action < rule, (rows, marker, action, rule)
    assert "Run N" in lines[rule]


def test_the_plan_says_which_are_not_picked_in_words(wire, capsys):
    """⛔ A MARKER ALONE IS NOT A SENTENCE. `•` versus `·` is one glyph apart and
    is the only thing separating "this is going" from "this is not" — in a chat
    relayed through a model and read on a phone."""
    sr.cmd_send_logs(_args(runs="1"))
    out = capsys.readouterr().out
    # ⚠ REPINNED 2026-09-20: each row now also carries the RUN'S OWN STATUS,
    # which the terminal twin has always printed and this client dropped — so a
    # run that had stopped mid-phase was offered as a plain size. The property
    # under test is untouched: "not picked" is stated in words, not left to one
    # glyph. Split in two so the status between them is not re-pinned here;
    # `test_the_row_carries_the_runs_own_status` owns that claim.
    kelp = next(ln for ln in out.splitlines() if "Kelp" in ln)
    assert kelp.startswith("  Run 2 · Kelp — 2.1 MB"), kelp
    assert kelp.endswith("   (not picked)"), kelp
    tidal = next(ln for ln in out.splitlines() if "Tidal power" in ln)
    assert tidal.startswith("  Run 1 • Tidal power — 1.0 MB"), tidal
    assert "(not picked)" not in tidal


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
    assert "signed in through this agent" in out
    # ⛔⛔ RE-AIMED IN WAVE 8 AND ASSERTING MORE. The old claim was "since that
    # file last rotated" — true while the uploader sent the active file alone, and
    # an understatement now that the rotated backups go too.
    assert "rotated copies go too" in out


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


def test_the_agent_log_alone_is_SENT_in_chat(wire, capsys):
    """⛔⛔ RE-AIMED IN WAVE 8: THIS USED TO BE A REFUSAL AND IS NOW THE FEATURE.
    The old sentence — "can only go up beside a bundle from that computer" — was
    true about the transport and useless to the reader, because the two commonest
    reasons to be sending an agent log are having no research computer and having
    one you cannot reach, and neither can produce a bundle. It asserts MORE than
    the refusal did: the plan is still a consent screen (nothing leaves without
    `--confirm`), and the follow-up it hands back is the command that finishes it.
    """
    rc = sr.cmd_send_logs(_args(runs="0", none=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "only go up beside a bundle" not in out
    # Still two steps: the plan alone uploads nothing.
    assert wire.posts == []
    assert "log from the agent on THIS host" in out
    assert "support code of its own" in out
    assert "send-logs --confirm --agent-log --none" in out


def test_the_agent_log_alone_reaches_the_wire_on_confirm(wire, capsys):
    """⛔ AND IT GOES WITHOUT A DEVICE AND WITHOUT A CODE. Anything else on that
    body is a second request the receiving route refuses."""
    rc = sr.cmd_send_logs(_args(runs="0", none=True, confirm=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert [p["path"] for p in wire.posts] == ["/logs/agent-log"]
    assert wire.posts[0]["body"] == {"standalone": True}
    assert "support code is" in out


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
    src = inspect.getsource(sr._nl_resolve)
    emitted = set(re.findall(r'"(--[a-z][a-z0-9-]*)"', src))
    assert emitted, "the regex found no flags at all — it has stopped reading"
    missing = emitted - set(sr._DO_FLAGS)
    assert not missing, (
        f"_nl_resolve can emit {sorted(missing)}, which cmd_do will treat as free "
        "text and push behind `--` — the whole request then fails to parse")


def test_every_value_taking_routed_flag_is_emitted_glued_to_its_value():
    """⛔ A VALUE-TAKING FLAG BREAKS THE SAME WAY ONE ARGUMENT ALONG: the relay
    sorts each resolved token into flags-or-positionals by membership, so a bare
    `--run` lands in flags and its value behind `--`, where it becomes a topic.

    ⛔⛤ THE RULE CHANGED IN WAVE 1.2 AND THE INVARIANT DID NOT. `skip` genuinely
    needs a run name — a person could not skip a phase of any run but the newest,
    from chat, at all — so `--run` joined the allowlist. What keeps the relay
    honest is not "no flag takes a value"; it is that a value-taking flag is
    emitted as ONE `--flag=value` token, which argparse accepts and the splitter
    cannot come apart. This asserts that, which is the property the old test was
    standing in for."""
    parser = sr.build_parser()
    seen = {}
    for action in parser._subparsers._group_actions[0].choices.values():
        for act in action._actions:
            for opt in act.option_strings:
                if opt in sr._DO_FLAGS:
                    seen[opt] = act.nargs
    assert seen, "no subcommand declares any of the routed flags"
    valued = [opt for opt, nargs in seen.items() if nargs != 0]
    src = inspect.getsource(sr._nl_resolve)
    for opt in valued:
        assert f'"{opt} ' not in src and f"'{opt} " not in src, \
            f"{opt} is emitted as a bare token — its value will become a topic"
        assert f"{opt}=" in src, f"{opt} takes a value and is never emitted glued"
    # and the relay matches on the part before the `=`
    assert 'split("=", 1)[0] in _DO_FLAGS' in inspect.getsource(sr.cmd_do)


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


def test_the_skill_says_the_agent_log_CAN_go_alone():
    """⛔⛔ RE-AIMED IN WAVE 8, AND THE OLD PIN WOULD NOW HOLD THE DOCUMENT WRONG.
    It required the sentence "`--runs 0` alone is refused with that sentence" —
    true until the log got a route and a support code of its own, and from that
    day an instruction that talks an assistant out of the only send available to
    somebody with no research computer.

    ⭐ IT ASSERTS MORE THAN IT DID: both spellings of the request, the code that
    comes back, and that the document no longer carries the refusal anywhere."""
    text = _SKILL.read_text(encoding="utf-8")
    assert "cannot go on its own" not in text
    assert "alone is refused" not in text
    assert "`--agent-log --none`" in text
    assert "`--runs 0` with nothing else" in text
    assert "support code of its own" in text
