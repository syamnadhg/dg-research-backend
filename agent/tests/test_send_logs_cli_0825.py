"""Wave 8L — `agent send-logs` at a terminal.

⛔⛔ THE ONE THING THIS SURFACE IS FOR. `consent: true` on the wire is a claim
that a person was SHOWN what leaves their computer. The web app's modal is what
makes that claim true; here the printed plan is. So the tests below care far
more about what gets PRINTED before the flag is set than about the flag itself
— a command that sends the right bytes after printing nothing has forged the
only thing the machine cannot check.

⭐ AND ABOUT WHAT IS NOT PRINTED. Two sentences look interchangeable and are
not: "that computer hasn't told us which runs it holds" and "it isn't holding
logs for any of your runs". The first is about us; the second accuses a machine
of having lost something. There is a test for each, and a mutant that collapses
them dies on both.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli

CLI_SRC = Path(cli.__file__).read_text(encoding="utf-8")
SR_SRC = (Path(cli.__file__).parent / "skill" / "scripts" / "sr.py").read_text(
    encoding="utf-8")

RUNS = [
    {"name": "run-a", "researchId": "r1", "title": "Tidal power",
     "startedUtc": "2026-08-24T10:00:00Z", "status": "completed",
     "sizeBytes": 1_200_000, "attempt": 1},
    {"name": "run-b", "researchId": "gone", "title": "",
     "startedUtc": "2026-08-21T09:12:00Z", "status": "failed",
     "sizeBytes": 400_000, "attempt": 2},
]


def _args(**kw):
    base = dict(device=None, runs=None, none=False, machine=False, list=False,
                status=None, yes=True, no_wait=True, wait=0, verbose=False)
    base.update(kw)
    return SimpleNamespace(**base)


class Wire:
    """Records every bridge call so a test can assert a refusal SENT NOTHING."""

    def __init__(self, *, published=True, runs=None, owned=True,
                 truncated=False, row=None, send_status=200, send_body=None):
        self.published = published
        self.runs = RUNS if runs is None else runs
        self.owned = owned
        self.truncated = truncated
        self.row = row
        self.send_status = send_status
        self.send_body = send_body or {"ok": True, "code": "K7XQ9B2M"}
        self.posts: list = []
        self.gets: list = []

    def get(self, path, timeout=10.0):
        self.gets.append(path)
        if path.startswith("/logs/runs"):
            # Echoes the device the caller ASKED for, defaulting to the
            # selected one — which is what the bridge does. A fake that
            # answered "dev1" whatever it was handed could not tell a
            # carried-forward id from a hard-coded one.
            asked = path.split("deviceId=", 1)[1] if "deviceId=" in path else ""
            return 200, {"deviceId": asked or "dev1", "deviceName": "Studio PC",
                         "owned": self.owned, "published": self.published,
                         "runs": self.runs, "truncated": self.truncated,
                         "updatedAt": ""}
        if path.startswith("/logs/bundle"):
            return 200, {"code": "K7XQ9B2M", "row": self.row}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, body=None, timeout=30.0):
        self.posts.append({"path": path, "body": body})
        return self.send_status, self.send_body


@pytest.fixture()
def wire(monkeypatch):
    w = Wire()
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_bridge_get", w.get)
    monkeypatch.setattr(cli, "_bridge_post", w.post)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    return w


def _run(args, wire_obj=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_send_logs(args)
    return rc, buf.getvalue()


# ── the plan is shown before anything is claimed ────────────────────────────

def test_the_runs_are_listed_before_the_send(wire) -> None:
    rc, out = _run(_args())
    assert rc == 0
    assert "Tidal power" in out
    assert "Studio PC" in out


def test_the_plan_names_the_count_and_the_weight(wire) -> None:
    _, out = _run(_args())
    assert "2 run(s)" in out
    assert "1.5 MB" in out, f"the size a person weighs the decision against: {out}"


def test_the_plan_says_the_machines_own_logs_are_not_included(wire) -> None:
    _, out = _run(_args())
    assert "NOT included" in out


def test_the_plan_names_everything_the_apps_modal_names(wire) -> None:
    """⛔⛔ THE HEADER CLAIMS THIS PLAN IS THE MODAL'S EQUIVALENT, so it has to
    name what the modal names. The app's consent list has four things that
    always leave; only the first — topics and titles — was conveyed here, by
    the run list itself. A claim of equivalence that is not equivalent is
    exactly the forging this surface exists to prevent, and it reaches a fleet
    sharer confirming in chat."""
    _, out = _run(_args())
    assert "anyone holding one can read them" in out, "the shareable result links"
    assert "email address" in out, "the account email"
    assert "agent screens showed" in out, "what the screens showed while running"


def test_the_plan_does_not_promise_a_retention_nothing_keeps(wire) -> None:
    """⛔⛔ THE APP REFUSES THIS SENTENCE ON PURPOSE and says so twice in
    `sendLogsCopy.ts`: no bucket lifecycle rule exists, so "deleted after 30
    days" is a promise nothing keeps. This surface shipped it anyway on its
    first day, in three places — an untrue retention claim on the one screen
    whose entire job is to be true about what leaves somebody's computer.

    ⭐ Asserted as an ABSENCE across the whole output, because this is the kind
    of sentence a future edit re-adds while "improving the copy". It arrives
    with the rule (wave 8M), not before it."""
    _, out = _run(_args())
    for claim in ("30 days", "thirty days", "deleted after"):
        assert claim not in out.lower(), f"promises a retention nothing keeps: {claim}"


def test_the_plan_still_says_who_can_read_them(wire) -> None:
    """Dropping the false half must not drop the true half with it."""
    _, out = _run(_args())
    assert "Only Super Research support can read them" in out


def test_asking_for_the_machines_own_logs_says_what_they_are(wire) -> None:
    """⛔ "also include the computer's own logs" is not informed consent. That
    material covers every run the machine has ever done for everyone who uses
    it, and the sentence has to say so before the person agrees."""
    _, out = _run(_args(machine=True))
    assert "everyone who uses it" in out


def test_the_plan_is_printed_even_when_the_prompt_is_skipped(wire) -> None:
    """⛔⛔ `--yes` skips the ASKING, never the SHOWING. If it skipped the
    printing, this command would put `consent: true` on the wire having shown
    the person nothing — which is the one claim the machine cannot check for
    itself, and therefore the one we have to keep true."""
    _, out = _run(_args(yes=True))
    assert "This will send" in out
    assert wire.posts[0]["body"]["consent"] is True


def test_declining_the_prompt_sends_nothing(wire, monkeypatch) -> None:
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    rc, out = _run(_args(yes=False))
    assert rc == 1
    assert "Nothing was sent" in out
    assert wire.posts == []


def test_the_prompt_defaults_to_no(wire, monkeypatch) -> None:
    """A bare Enter must not send somebody's logs anywhere."""
    seen: dict = {}

    def fake_confirm(prompt, default=True):
        seen["default"] = default
        return default

    monkeypatch.setattr(cli.b, "confirm", fake_confirm)
    rc, _ = _run(_args(yes=False))
    assert seen["default"] is False
    assert rc == 1
    assert wire.posts == []


# ── what reaches the bridge ─────────────────────────────────────────────────

def test_the_default_selection_is_every_run_of_theirs_it_holds(wire) -> None:
    _run(_args())
    assert wire.posts[0]["body"]["runNames"] == ["run-a", "run-b"]


def test_runs_can_be_chosen_by_the_numbers_on_screen(wire) -> None:
    _run(_args(runs="2"))
    assert wire.posts[0]["body"]["runNames"] == ["run-b"]


def test_runs_can_be_chosen_by_name(wire) -> None:
    _run(_args(runs="run-a"))
    assert wire.posts[0]["body"]["runNames"] == ["run-a"]


def test_a_run_named_twice_is_sent_once(wire) -> None:
    _run(_args(runs="1,run-a"))
    assert wire.posts[0]["body"]["runNames"] == ["run-a"]


def test_a_number_that_is_not_on_the_list_refuses_and_sends_nothing(wire) -> None:
    """⛔ Dropping it would send fewer runs than were asked for and report
    success — the person believes a run went and it did not."""
    rc, out = _run(_args(runs="1,9"))
    assert rc == 1
    assert "no run 9" in out
    assert wire.posts == []


def test_a_name_the_machine_is_not_holding_refuses_and_sends_nothing(wire) -> None:
    rc, out = _run(_args(runs="run-a,run-ghost"))
    assert rc == 1
    assert "run-ghost" in out
    assert wire.posts == []


def test_the_machine_flag_is_carried(wire) -> None:
    _run(_args(machine=True))
    assert wire.posts[0]["body"]["includeMachine"] is True


def test_the_machine_flag_is_carried_as_false_not_omitted(wire) -> None:
    _run(_args())
    assert wire.posts[0]["body"]["includeMachine"] is False


def test_a_named_device_is_carried_to_both_calls(wire) -> None:
    _run(_args(device="dev2"))
    assert any("deviceId=dev2" in g for g in wire.gets)
    assert wire.posts[0]["body"]["deviceId"] == "dev2"


def test_the_send_goes_to_the_computer_the_plan_was_printed_for(wire) -> None:
    """⛔⛔ Showing and sending are two round trips. With no deviceId on the
    second, the bridge picks the SELECTED machine again — so a selection that
    changed in between (in the app, or because the old one stopped being
    reachable) prints one computer's runs and sends from another. The person
    consented to what they were shown."""
    rc, _ = _run(_args())
    assert rc == 0
    assert wire.posts[0]["body"]["deviceId"] == "dev1", (
        "the send did not name the machine whose runs were listed")


# ── the sharer boundary, said before a round trip ───────────────────────────

def test_a_sharer_asking_for_the_machines_own_logs_is_told_here(wire) -> None:
    wire.owned = False
    rc, out = _run(_args(machine=True))
    assert rc == 1
    assert "belong to whoever owns it" in out
    assert wire.posts == [], "told no and sent anyway"


def test_that_refusal_says_their_own_runs_still_come(wire) -> None:
    wire.owned = False
    _, out = _run(_args(machine=True))
    assert "every run of yours" in out


def test_a_sharer_sending_their_own_runs_is_ordinary(wire) -> None:
    wire.owned = False
    rc, _ = _run(_args())
    assert rc == 0
    assert wire.posts[0]["body"]["includeMachine"] is False


# ── nothing to send ─────────────────────────────────────────────────────────

def test_no_runs_and_no_machine_logs_refuses(wire) -> None:
    wire.runs = []
    rc, out = _run(_args())
    assert rc == 1
    assert "nothing to send" in out
    assert wire.posts == []


def test_an_owner_with_no_runs_is_told_how_to_send_the_computers_own(wire) -> None:
    """The pairing-failure case: nothing has run, so there is nothing to tick,
    and the machine's own logs are the entire point of the send. A refusal that
    stops there leaves the one person who needs this most with no next step."""
    wire.runs = []
    _, out = _run(_args())
    assert "--machine" in out


def test_a_sharer_with_no_runs_is_not_offered_something_they_cannot_have(wire) -> None:
    wire.runs = []
    wire.owned = False
    _, out = _run(_args())
    assert "--machine" not in out


def test_none_with_machine_logs_sends_an_empty_selection(wire) -> None:
    rc, _ = _run(_args(none=True, machine=True))
    assert rc == 0
    assert wire.posts[0]["body"]["runNames"] == []
    assert wire.posts[0]["body"]["includeMachine"] is True


# ── what we can and cannot see ──────────────────────────────────────────────

def test_a_machine_that_never_published_is_not_accused_of_holding_nothing(wire) -> None:
    """⛔⛔ THE TWO SENTENCES ARE NOT INTERCHANGEABLE. Absent means we cannot
    see the list; empty means the machine says it holds none. Printing the
    second when the first is true tells somebody their logs are gone while that
    computer may be holding all of them."""
    wire.published = False
    wire.runs = []
    _, out = _run(_args())
    assert "hasn't told us" in out
    assert "isn't holding logs for any of your runs" not in out


def test_a_machine_that_published_an_empty_list_says_so_plainly(wire) -> None:
    wire.published = True
    wire.runs = []
    _, out = _run(_args())
    assert "isn't holding logs for any of your runs" in out
    assert "hasn't told us" not in out


def test_a_truncated_list_says_there_is_more(wire) -> None:
    wire.truncated = True
    _, out = _run(_args())
    assert "it holds more" in out


def test_a_run_with_no_research_document_reads_by_its_date(wire) -> None:
    _, out = _run(_args(list=True))
    assert "a run from 2026-08-21" in out


def test_list_shows_and_sends_nothing(wire) -> None:
    rc, out = _run(_args(list=True))
    assert rc == 0
    assert "Tidal power" in out
    assert wire.posts == []


# ── waiting for the machine ─────────────────────────────────────────────────

def test_a_finished_bundle_reports_the_code_to_quote(wire) -> None:
    wire.row = {"status": "done", "runCount": 2, "sizeBytes": 1_600_000,
                "machineIncluded": False}
    rc, out = _run(_args(no_wait=False, wait=5))
    assert rc == 0
    assert "K7XQ9B2M" in out
    assert "2 run(s)" in out


def test_a_finished_bundle_says_when_the_machines_own_logs_went_too(wire) -> None:
    wire.row = {"status": "done", "runCount": 1, "sizeBytes": 10,
                "machineIncluded": True}
    _, out = _run(_args(no_wait=False, wait=5, machine=True))
    # ⛔ "THAT computer", not "this". The machine is the RESEARCH computer, which
    # is usually not the one this command is typed on. This assertion pinned the
    # wrong pronoun — inside a test whose own name means the research machine —
    # so the harness enshrined the slip instead of catching it.
    assert "that computer's own logs" in out


def test_a_refusal_is_reported_in_words(wire) -> None:
    """⛔⛔ THIS USED TO ASSERT "ten minutes", WHICH IS THE THING THAT WAS WRONG.
    The machine keeps two windows and the refusal row names neither, so the one
    honest answer is that it was recent. See the duration test below."""
    wire.row = {"status": "failed", "errorClass": "CooldownActive"}
    rc, out = _run(_args(no_wait=False, wait=5))
    assert rc == 1
    assert "very recently" in out
    assert "Try again shortly" in out
    # ⭐ THE RULE, NOT THE CULPRIT. An earlier draft said "perhaps for someone
    # else who uses it" — a claim about WHO, and wrong on a machine nobody else
    # uses when it was the reader's own second press.
    assert "counts everyone who uses it" in out
    assert "perhaps for someone else" not in out
    assert "ten minutes" not in out, "the wait is not always ten minutes"
    assert "CooldownActive" not in out, "the class name is not a sentence"


def test_a_refusal_we_have_no_sentence_for_still_says_something(wire) -> None:
    """⛔ An error nobody can read is the same as no error, and this is the
    surface a person only reaches because something already went wrong."""
    wire.row = {"status": "failed", "errorClass": "SomethingNewIn2027"}
    rc, out = _run(_args(no_wait=False, wait=5))
    assert rc == 1
    assert "SomethingNewIn2027" in out
    assert len(out.strip()) > 20


def test_running_out_of_patience_is_not_reported_as_a_failure(wire) -> None:
    """⛔⛔ The support code is already valid and the bundle may still land.
    Calling this a failure is a lie about somebody else's computer, and it
    would fire on every machine that is merely slow."""
    wire.row = None
    rc, out = _run(_args(no_wait=False, wait=1))
    assert rc == 0
    assert "--status" in out


def test_never_picked_up_reads_differently_from_still_packaging(wire) -> None:
    """No row at all may mean the request was never picked up — an asleep
    machine. Telling somebody "still packaging" then sends them away to wait
    for something that is not happening."""
    wire.row = None
    _, no_row = _run(_args(no_wait=False, wait=1))
    assert "asleep or offline" in no_row

    wire.row = {"status": "collecting"}
    _, mid = _run(_args(no_wait=False, wait=1))
    assert "Still packaging" in mid
    assert "asleep or offline" not in mid


def test_no_wait_hands_back_the_code_and_how_to_look(wire) -> None:
    rc, out = _run(_args(no_wait=True))
    assert rc == 0
    assert "K7XQ9B2M" in out
    assert "--status" in out


# ── --status on its own ─────────────────────────────────────────────────────

def test_status_reports_a_finished_bundle(wire) -> None:
    wire.row = {"status": "done", "runCount": 3, "sizeBytes": 2048}
    rc, out = _run(_args(status="k7xq9b2m"))
    assert rc == 0
    assert "3 run(s)" in out
    assert wire.posts == []


def test_status_upper_cases_what_a_person_typed(wire) -> None:
    """People type the code back out of a chat message."""
    wire.row = {"status": "done", "runCount": 1, "sizeBytes": 1}
    _run(_args(status="k7xq9b2m"))
    assert any("code=K7XQ9B2M" in g for g in wire.gets)


def test_status_on_a_code_nothing_has_answered_is_not_an_error(wire) -> None:
    wire.row = None
    rc, out = _run(_args(status="K7XQ9B2M"))
    assert rc == 0
    assert "Nothing recorded" in out


def test_status_reports_a_refusal_in_words(wire) -> None:
    wire.row = {"status": "failed", "errorClass": "NotDeviceMember"}
    rc, out = _run(_args(status="K7XQ9B2M"))
    assert rc == 1
    assert "one of its people" in out


# ── the two copies of the sentences ─────────────────────────────────────────

def _failure_keys(table: dict) -> set:
    """The error classes a table has a sentence for.

    ⛔⛔ THIS USED TO REGEX THE SOURCE TEXT, AND THE SOURCE TEXT INCLUDES
    COMMENTS. `re.findall(r'"([A-Za-z]+)":')` over the table block counted any
    quoted word followed by a colon anywhere inside it — so a comment that
    quoted the shape of a Firestore patch reported `status` and `errorClass` as
    error classes this client has sentences for. It found that the moment a
    comment was added; before that it was simply waiting. Both tables are
    readable as VALUES — cli.py by import, sr.py through `ast.literal_eval` —
    so nothing here needs to guess from text."""
    return set(table)


def test_the_chat_skill_has_a_sentence_for_every_refusal_the_cli_does() -> None:
    """⛔⛔ TWO COPIES, AND THE DUPLICATION IS FORCED. `sr.py` runs inside a chat
    runtime and is stdlib-only by contract — it cannot import this module, and
    a test in this repo already pins that. So the tables drift unless something
    reads both, and the failure mode of drift is a person being told nothing at
    all about why their logs did not send."""
    assert _failure_keys(cli._SEND_LOGS_FAILURES) == _failure_keys(_sr_failure_table())


def test_both_clients_say_the_same_words_and_not_merely_the_same_classes() -> None:
    """⛔⛔ THE KEY-SET TEST ABOVE PASSES WHILE THE TWO CLIENTS SAY DIFFERENT
    THINGS, and that is exactly how the cooldown sentence came to be corrected
    in one copy and not the other in an earlier draft of this very wave. A
    person on the terminal and a person in chat are being told about the same
    machine and the same refusal; the words are the product, so the words are
    what has to match, not the dictionary keys around them.

    ⭐ Values, not source text: read through `ast.literal_eval`, so the comment
    that explains a sentence is free to differ between the two files while the
    sentence itself may not."""
    assert cli._SEND_LOGS_FAILURES == _sr_failure_table()


def test_no_refusal_sentence_tells_a_person_how_long_to_wait() -> None:
    """⛔⛔ NO CLIENT MAY NAME A DURATION, BECAUSE NO CLIENT CAN KNOW ONE. The
    machine writes `{"status": "failed", "errorClass": ...}` and nothing else —
    the seconds it computed are logged locally and thrown away. Meanwhile it
    keeps TWO windows: the whole cooldown for your own second press, and a much
    shorter unkeyed floor when somebody ELSE who uses that computer went first.
    "Give it ten minutes" was written for the first and said to both, on the one
    surface whose ordinary caller is a sharer on a shared research computer.

    ⭐ A ban rather than a corrected number, because a corrected number would be
    wrong for the other case in exactly the same way. `try again shortly` is
    true whichever window fired.

    ⭐ Values only, so the comment explaining the ban does not trip it — the
    same trap the retention guard hit on its first run."""
    for name, table in (("cli.py", cli._SEND_LOGS_FAILURES),
                        ("sr.py", _sr_failure_table())):
        for cls, words in table.items():
            for unit in ("second", "minute", "hour", " day"):
                assert unit not in words.lower(), (
                    f"{name}/{cls} names a {unit.strip()} — the refusal row carries "
                    f"no remaining time, so any duration here is a guess")


def test_the_machine_keeps_two_cooldown_windows_and_they_differ() -> None:
    """⭐⭐ THE FACT THE SENTENCE ABOVE DEPENDS ON, PINNED AT ITS SOURCE. If the
    floor and the per-person window were ever made equal, one number WOULD be
    honest and the ban above would be needless caution. They are not equal, and
    nothing anywhere pinned that until now — `SEND_LOGS_MACHINE_FLOOR_SEC` had
    zero test references in either suite, so the constant that makes every
    client's copy wrong could have moved without a single failure.

    Read out of the backend's source rather than imported: `research.py` is a
    separate program from this package and importing it here would pull in the
    whole pipeline."""
    root = Path(__file__).resolve().parents[2]      # agent/tests -> repo root
    src_path = root / "research.py"
    assert src_path.exists(), (
        f"{src_path} is missing — this suite runs from the backend checkout, and "
        f"without it the client copy's premise is unchecked rather than checked")
    src = src_path.read_text(encoding="utf-8")
    window = _int_const(src, "SEND_LOGS_COOLDOWN_SEC")
    floor = _int_const(src, "SEND_LOGS_MACHINE_FLOOR_SEC")
    assert window == 600, f"per-person window moved to {window}"
    assert floor == 60, f"machine floor moved to {floor}"
    assert floor < window, (
        "the floor is a concurrency bound, not a fairness one — making it equal "
        "to the per-person window recreates the shared lockout it exists to fix")


def _int_const(src: str, name: str) -> int:
    """One module-level integer constant, folded from the source text."""
    import ast
    m = re.search(rf"^{name}\s*=\s*([0-9 */+]+?)\s*(?:#.*)?$", src, re.M)
    assert m, f"{name} is not a plain integer constant in research.py"

    def fold(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add)):
            left, right = fold(node.left), fold(node.right)
            return left * right if isinstance(node.op, ast.Mult) else left + right
        raise AssertionError(f"{name} is not plain integer arithmetic")

    return fold(ast.parse(m.group(1).strip(), mode="eval").body)


def test_every_refusal_the_machine_can_write_has_a_sentence() -> None:
    """⛔⛔ ITS DOCSTRING SAID THE NAMES CAME FROM THE BACKEND'S OWN REFUSAL SITES
    AND THEY DID NOT — the list was hand-typed here, so it could only ever prove
    that a set somebody wrote down matches a table somebody wrote down. Add a
    new refusal to `research.py` and this passed, while the person met the
    fallback that names the class and admits we have no words for it.

    It reads the refusal sites now. The mechanism was already in this file, one
    test away: `_int_const` reads `research.py`'s source for the two cooldown
    constants, and this needs no more than that."""
    root = Path(__file__).resolve().parents[2]      # agent/tests -> repo root
    src_path = root / "research.py"
    assert src_path.exists(), (
        f"{src_path} is missing — this suite runs from the backend checkout, and "
        f"without it this guard proves only that two lists agree with each other")
    src = src_path.read_text(encoding="utf-8")

    # Every class literal handed to the row-writing refusal helper, plus the one
    # written directly onto the row by the upload rung.
    written = set(re.findall(
        r"_refuse_log_bundle_with_row\((?:[^()]|\([^()]*\))*?\"([A-Za-z]+)\"",
        src, re.S))
    written |= set(re.findall(r'"errorClass":\s*"([A-Za-z]+)"', src))
    assert len(written) >= 10, (
        f"only found {sorted(written)} — the scan stopped seeing the refusal "
        f"sites, which would make this guard vacuous rather than failing")

    have = _failure_keys(cli._SEND_LOGS_FAILURES)
    assert written <= have, (
        f"{sorted(written - have)} can be written by the machine with no sentence "
        f"in either client — a person meets the fallback instead")


def test_the_unknown_class_fallback_still_earns_its_place() -> None:
    """⭐ AND IT DOES, MEASURABLY. The upload rung records `type(exc).__name__`
    on the row, so the class name is whatever Python raised — unbounded, and
    impossible to enumerate above. That is the one refusal no table can cover,
    which is why the fallback exists and why it names the class rather than
    hiding it."""
    root = Path(__file__).resolve().parents[2]
    src = (root / "research.py").read_text(encoding="utf-8")
    assert 'type(exc).__name__' in src, (
        "no dynamic error class is written any more — if that is true, the "
        "fallback's justification has changed and should be re-argued")


def test_no_client_calls_the_research_computer_this_one() -> None:
    """⛔ ONE MACHINE, ONE PRONOUN, ACROSS THREE FILES. The research computer is
    "that computer" — the agent usually runs somewhere else entirely, and on a
    fleet it always does. One line said "this computer's own logs" while every
    other sentence in the same command said "that", and the difference is which
    machine a person believes they just sent.

    Scanned at the source across the clients AND the bridge, because the three
    are separate copies and the slip appeared in two of them independently."""
    from facade import bridge as _bridge
    bridge_src = Path(_bridge.__file__).read_text(encoding="utf-8")
    for name, src in (("cli.py", CLI_SRC), ("sr.py", SR_SRC), ("bridge.py", bridge_src)):
        code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
        for wrong in ("this computer's own logs", "this computer\u2019s own logs"):
            assert wrong not in code, (
                f"{name} calls the research computer 'this' one — it is 'that computer'")


def test_neither_client_carries_the_retention_promise_in_source() -> None:
    """⛔ Both clients said it, and both were wrong the same way. Pinned at the
    SOURCE as well as in the output, because the two files are separate copies
    (the chat client is stdlib-only and cannot import the other) — so a fix in
    one is not a fix in the other, which is exactly how it got in twice."""
    for name, src in (("cli.py", CLI_SRC), ("sr.py", SR_SRC)):
        body = src.split("def cmd_send_logs(", 1)[1]
        # ⛔ COMMENTS STRIPPED FIRST. The comment explaining WHY the sentence is
        # absent contains the sentence, so a raw search fails on the very fix it
        # is guarding — which it did, on the first run. This is the Python twin
        # of the FE suite's `codeOnly`.
        code = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
        for claim in ("kept for 30 days", "deleted after 30"):
            assert claim not in code, f"{name} promises a retention nothing keeps"


def test_no_failure_sentence_names_a_command_that_cannot_help() -> None:
    """⛔⛔ THE UPLOAD-FAILED SENTENCE SENT PEOPLE TO `--doctor`, WHICH PRINTS NO
    BUNDLE PATH. Measured: `run_doctor` prints none anywhere; the path is
    printed only by send-logs itself, and only after building a NEW bundle —
    never the one the person was told about. So the sentence a person reads at
    their worst moment pointed at a dead end.

    ⭐ AND THE FIX WENT UNPINNED. Mutation restored the false claim and nothing
    noticed: the copy had been corrected in both clients with no assertion
    behind it, which is a fix that lasts exactly until the next edit. Both
    tables are checked, since they are separate copies by contract."""
    for name, table in (("cli.py", cli._SEND_LOGS_FAILURES),
                        ("sr.py", _sr_failure_table())):
        for cls, words in table.items():
            assert "--doctor" not in words, (
                f"{name}/{cls} sends the person to a command that cannot help")
            assert "doctor" not in words.lower(), (
                f"{name}/{cls} names doctor, which prints no bundle path")


def _sr_failure_table() -> dict:
    """The chat client's copy of the sentences, read from source — it is
    stdlib-only by contract and cannot be imported for its module object."""
    import ast
    tree = ast.parse(SR_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_SEND_LOGS_FAILURES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("sr.py has no _SEND_LOGS_FAILURES table")


def test_no_sentence_is_empty() -> None:
    for cls, words in cli._SEND_LOGS_FAILURES.items():
        assert len(words.strip()) > 10, f"{cls} has no readable sentence"


# ── plumbing ────────────────────────────────────────────────────────────────

def test_a_bridge_that_is_not_running_says_how_to_start_it(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    rc, out = _run(_args())
    assert rc == 1
    assert "agent serve" in out


def test_sizes_read_as_something_a_person_can_weigh() -> None:
    assert cli._size_words(0) == "0 bytes"
    assert cli._size_words(1536) == "1.5 KB"
    assert cli._size_words(5 * 1024 ** 2) == "5.0 MB"
    assert cli._size_words(3 * 1024 ** 3) == "3.0 GB"
    assert cli._size_words(None) == "0 bytes"
    assert cli._size_words("nonsense") == "unknown size"
