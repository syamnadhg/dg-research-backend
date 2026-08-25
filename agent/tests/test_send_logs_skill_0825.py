"""Wave 8L — sending logs from a chat runtime (`sr.py send-logs`).

⛔⛔ THE CONFIRM STEP IS THE CONSENT. The research computer refuses a request
that does not carry `consent: true`, and that flag is a claim that a person was
SHOWN what leaves their machine. In the app a modal makes it true. Here the
bare command PRINTS the plan and sends nothing; only `--confirm` sets the flag.
Nearly every test below exists to keep those two halves from collapsing into
one, because a single call that showed nothing and claimed consent anyway would
forge the one thing the machine cannot check for itself.

⭐ AND THE FLEET IS THE CASE THAT MATTERS. A chat runtime is exactly where a
shared research computer gets used by somebody who does not own it, so "may I
ask for this" is a live question here rather than a hypothetical one.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SR = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_send_logs_under_test", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_send_logs_under_test"] = sr
_spec.loader.exec_module(sr)

RUNS = [
    {"name": "run-a", "researchId": "r1", "title": "Tidal power",
     "startedUtc": "2026-08-24T10:00:00Z", "status": "completed",
     "sizeBytes": 1_200_000},
    {"name": "run-b", "researchId": "gone", "title": "",
     "startedUtc": "2026-08-21T09:12:00Z", "status": "failed",
     "sizeBytes": 400_000},
]


def _args(**kw):
    base = dict(json=False, confirm=False, machine=False, none=False,
                device="", status="")
    base.update(kw)
    return SimpleNamespace(**base)


class Wire:
    def __init__(self, *, published=True, runs=None, owned=True,
                 truncated=False, row=None, runs_code=200, runs_body=None):
        self.published = published
        self.runs = RUNS if runs is None else runs
        self.owned = owned
        self.truncated = truncated
        self.row = row
        self.runs_code = runs_code
        self.runs_body = runs_body
        self.posts: list = []
        self.gets: list = []

    def get(self, path, timeout=None):
        self.gets.append(path)
        if path.startswith("/logs/runs"):
            if self.runs_body is not None:
                return self.runs_code, self.runs_body
            # Echoes the device the caller ASKED for, like the bridge does. A
            # fake that always answered "dev1" could not tell a carried-forward
            # id from a hard-coded one.
            asked = path.split("deviceId=", 1)[1] if "deviceId=" in path else ""
            return 200, {"deviceId": asked or "dev1", "deviceName": "Studio PC",
                         "owned": self.owned, "published": self.published,
                         "runs": self.runs, "truncated": self.truncated}
        if path.startswith("/logs/bundle"):
            return 200, {"code": "K7XQ9B2M", "row": self.row}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, body=None):
        self.posts.append({"path": path, "body": body})
        return 200, {"ok": True, "code": "K7XQ9B2M"}


@pytest.fixture()
def wire(monkeypatch):
    w = Wire()
    monkeypatch.setattr(sr, "_get", w.get)
    monkeypatch.setattr(sr, "_post", w.post)
    return w


def _run(args, capsys):
    rc = sr.cmd_send_logs(args)
    return rc, capsys.readouterr().out


# ── the two halves ──────────────────────────────────────────────────────────

def test_the_bare_command_shows_and_sends_nothing(wire, capsys) -> None:
    """⛔⛔ THE WHOLE SHAPE OF THIS FEATURE. If this ever sends, the consent flag
    on the wire becomes a claim about a conversation that never happened."""
    rc, out = _run(_args(), capsys)
    assert rc == 0
    assert wire.posts == [], "the bare command sent somebody's logs"
    assert "Tidal power" in out
    assert "Say yes" in out


def test_the_plan_names_the_count_and_the_weight(wire, capsys) -> None:
    _, out = _run(_args(), capsys)
    assert "2 run(s)" in out
    assert "1.5 MB" in out


def test_the_plan_does_not_promise_a_retention_nothing_keeps(wire, capsys) -> None:
    """⛔⛔ THE APP REFUSES THIS SENTENCE ON PURPOSE, and says so twice in
    `sendLogsCopy.ts`: no bucket lifecycle rule exists, so "deleted after 30
    days" is a promise nothing keeps. This surface shipped it anyway on its
    first day — an untrue retention claim on the one screen whose entire job is
    to be true about what leaves somebody's computer.

    ⭐ Asserted as an ABSENCE, across the whole output, because the sentence is
    the kind a future edit re-adds while "improving the copy". It arrives with
    the rule (wave 8M), not before it."""
    _, out = _run(_args(), capsys)
    for claim in ("30 days", "thirty days", "deleted after"):
        assert claim not in out.lower(), f"promises a retention nothing keeps: {claim}"


def test_the_plan_still_says_who_can_read_them(wire, capsys) -> None:
    """Dropping the false half must not drop the true half with it."""
    _, out = _run(_args(), capsys)
    assert "Only Super Research support can read them" in out


def test_the_plan_says_the_machines_own_logs_are_not_included(wire, capsys) -> None:
    _, out = _run(_args(), capsys)
    assert "not included" in out


def test_the_send_goes_to_the_computer_the_plan_was_printed_for(wire, capsys) -> None:
    """Showing and sending are two calls; without this the bridge re-picks the
    selected machine and the user agreed to a different computer's list."""
    rc, _ = _run(_args(confirm=True), capsys)
    assert rc == 0
    assert wire.posts[0]["body"]["deviceId"] == "dev1"


def test_confirm_sends_and_carries_the_consent(wire, capsys) -> None:
    rc, out = _run(_args(confirm=True), capsys)
    assert rc == 0
    assert wire.posts[0]["path"] == "/logs/send"
    assert wire.posts[0]["body"]["consent"] is True
    assert "K7XQ9B2M" in out


def test_the_consent_flag_exists_only_on_the_confirmed_branch() -> None:
    """A source pin, and it is the cheapest guard against the failure this
    file is about: the flag drifting up into the shared setup where the
    unconfirmed call would carry it too."""
    src = _SR.read_text(encoding="utf-8")
    body = src.split("def cmd_send_logs(", 1)[1].split("\ndef ", 1)[0]
    assert body.count('"consent": True') == 1, (
        "consent is set more than once in send-logs — one of them is not "
        "under the confirm branch")
    before, after = body.split('"consent": True', 1)
    assert 'getattr(args, "confirm", False)' in before, (
        "consent is set before the confirm branch is decided")


# ── the machine's own logs ──────────────────────────────────────────────────

def test_asking_for_the_machines_own_logs_says_what_they_are(wire, capsys) -> None:
    """"Also the computer's own logs" is not informed consent. That material
    covers every run the machine has ever done for everyone who uses it."""
    _, out = _run(_args(machine=True), capsys)
    assert "everyone who uses it" in out


def test_a_sharer_asking_for_them_is_told_before_any_round_trip(wire, capsys) -> None:
    wire.owned = False
    rc, out = _run(_args(machine=True), capsys)
    assert rc == 1
    assert "belong to whoever owns it" in out
    assert wire.posts == []


def test_that_refusal_says_their_own_runs_still_come(wire, capsys) -> None:
    wire.owned = False
    _, out = _run(_args(machine=True), capsys)
    assert "every run of yours" in out


def test_an_owner_may_confirm_the_machines_own_logs(wire, capsys) -> None:
    rc, _ = _run(_args(machine=True, confirm=True), capsys)
    assert rc == 0
    assert wire.posts[0]["body"]["includeMachine"] is True


def test_the_flag_is_carried_as_false_not_omitted(wire, capsys) -> None:
    _run(_args(confirm=True), capsys)
    assert wire.posts[0]["body"]["includeMachine"] is False


def test_none_with_the_machines_own_logs_sends_an_empty_selection(wire, capsys) -> None:
    """The connection-problem case: nothing has run, so there are no runs to
    offer, and the computer's own logs are the entire point."""
    rc, _ = _run(_args(none=True, machine=True, confirm=True), capsys)
    assert rc == 0
    assert wire.posts[0]["body"]["runNames"] == []


# ── what we can and cannot see ──────────────────────────────────────────────

def test_a_computer_that_never_published_is_not_accused_of_holding_nothing(
        wire, capsys) -> None:
    """⛔⛔ Two sentences that look interchangeable and are not. Absent means we
    cannot see the list; empty means the machine says it holds none. The second
    tells somebody their logs are gone while that computer may hold them all."""
    wire.published = False
    wire.runs = []
    rc, out = _run(_args(), capsys)
    assert rc == 1
    assert "hasn’t told me" in out
    assert "isn’t holding logs for any of your runs" not in out
    assert wire.posts == []


def test_a_computer_that_published_an_empty_list_says_so_plainly(wire, capsys) -> None:
    wire.published = True
    wire.runs = []
    rc, out = _run(_args(), capsys)
    assert rc == 1
    assert "isn’t holding logs for any of your runs" in out
    assert "hasn’t told me" not in out


def test_an_owner_with_nothing_to_send_is_given_a_next_step(wire, capsys) -> None:
    wire.runs = []
    _, out = _run(_args(), capsys)
    assert "computer’s own logs" in out


def test_a_sharer_with_nothing_to_send_is_not_offered_what_they_cannot_have(
        wire, capsys) -> None:
    wire.runs = []
    wire.owned = False
    _, out = _run(_args(), capsys)
    assert "computer’s own logs" not in out


def test_a_run_with_no_research_document_reads_by_its_date(wire, capsys) -> None:
    _, out = _run(_args(), capsys)
    assert "a run from 2026-08-21" in out


def test_a_truncated_list_says_there_is_more(wire, capsys) -> None:
    wire.truncated = True
    _, out = _run(_args(), capsys)
    assert "holding more" in out


# ── which computer ──────────────────────────────────────────────────────────

def test_a_pick_your_computer_answer_is_relayed_as_that_question(
        wire, capsys, monkeypatch) -> None:
    """⛔ The bridge answers `no_selection` with a machine-readable reason and
    the device list attached. Rendering it as a bare error would tell somebody
    their logs cannot be sent when the truth is that they have two computers."""
    wire.runs_code = 400
    wire.runs_body = {"reason": "no_selection", "error": "no device selected",
                      "devices": [{"id": "d1", "name": "Studio PC"},
                                  {"id": "d2", "name": "Fleet Box"}]}
    rc, out = _run(_args(), capsys)
    assert rc == 1
    assert "which should run this" in out or "Studio PC" in out
    assert wire.posts == []


def test_a_device_can_be_named(wire, capsys, monkeypatch) -> None:
    monkeypatch.setattr(sr, "_resolve_device_arg",
                        lambda arg: ({"id": "dev2", "name": "Fleet Box"}, []))
    _run(_args(device="Fleet Box", confirm=True), capsys)
    assert any("deviceId=dev2" in g for g in wire.gets)
    assert wire.posts[0]["body"]["deviceId"] == "dev2"


def test_a_device_name_that_matches_nothing_stops_there(wire, capsys, monkeypatch) -> None:
    monkeypatch.setattr(sr, "_resolve_device_arg",
                        lambda arg: (None, ["I don’t know a computer called that."]))
    rc, out = _run(_args(device="nowhere", confirm=True), capsys)
    assert rc == 1
    assert wire.posts == []
    assert wire.gets == []


# ── checking on it later ────────────────────────────────────────────────────

def test_a_finished_bundle_reports_the_code_to_quote(wire, capsys) -> None:
    wire.row = {"status": "done", "runCount": 2, "sizeBytes": 1_600_000}
    rc, out = _run(_args(status="k7xq9b2m"), capsys)
    assert rc == 0
    assert "K7XQ9B2M" in out
    assert "2 run(s)" in out


def test_a_refusal_is_reported_in_words(wire, capsys) -> None:
    wire.row = {"status": "failed", "errorClass": "CooldownActive"}
    rc, out = _run(_args(status="K7XQ9B2M"), capsys)
    assert rc == 1
    assert "ten minutes" in out
    assert "CooldownActive" not in out, "a class name is not a sentence"


def test_a_refusal_we_have_no_sentence_for_still_says_something(wire, capsys) -> None:
    wire.row = {"status": "failed", "errorClass": "SomethingNewIn2027"}
    rc, out = _run(_args(status="K7XQ9B2M"), capsys)
    assert rc == 1
    assert "SomethingNewIn2027" in out


def test_nothing_back_yet_is_not_reported_as_a_failure(wire, capsys) -> None:
    """The support code is already valid and the bundle may still land. Calling
    this a failure would fire on every computer that is merely slow."""
    wire.row = None
    rc, out = _run(_args(status="K7XQ9B2M"), capsys)
    assert rc == 0
    assert "not have picked the request up" in out


def test_the_assistant_is_told_how_to_check_and_not_to_poll(wire, capsys) -> None:
    """⛔ Left to itself a chat runtime will poll a status command on a timer,
    which is a Firestore read per tick on somebody's account for as long as the
    conversation stays open."""
    _, out = _run(_args(confirm=True), capsys)
    assert sr._AGENT_ONLY_MARKER in out
    assert "--status K7XQ9B2M" in out
    assert "Do not poll" in out


# ── the words a person asks in ──────────────────────────────────────────────

def _argv(text):
    argv, lines = sr._nl_resolve(text)
    assert argv is not None, f"expected a command for {text!r}, got: {lines}"
    return argv


def _note(text):
    argv, lines = sr._nl_resolve(text)
    assert argv is None, f"expected a note for {text!r}, got: {argv}"
    return " ".join(lines)


@pytest.mark.parametrize("phrase", [
    "send my logs",
    "send the logs to support",
    "can you share the logs",
    "upload my log files please",
    "submit diagnostics",
])
def test_asking_to_send_logs_resolves(phrase) -> None:
    assert _argv(phrase)[0] == "send-logs"


@pytest.mark.parametrize("phrase", [
    "send the computer's own logs",
    "share that machine's own logs",
    "send its own logs",
])
def test_naming_the_computers_own_logs_reaches_the_flag(phrase) -> None:
    """⭐ Resolved to the FLAG rather than acted on. A sharer is then refused
    with a sentence, and an owner still sees the plan naming what that material
    actually is before anything is sent. This is the phrasing the no-runs
    branch offers, so the connection-problem case has a route."""
    argv = _argv(phrase)
    assert argv[0] == "send-logs"
    assert "--machine" in argv


@pytest.mark.parametrize("phrase", [
    "send all the logs",
    "send everything in the logs",
    "share all of my logs",
])
def test_a_broad_word_does_not_ask_for_the_whole_machine(phrase) -> None:
    """⛔⛔ "Everything" means everything of THEIRS. The machine-level material
    is every run that computer has ever done for everyone who uses it, and
    reading a broad word as a request for it makes an ask nobody made."""
    argv = _argv(phrase)
    assert argv[0] == "send-logs"
    assert "--machine" not in argv


@pytest.mark.parametrize("phrase", [
    "research how log shipping works",
    "research the history of log cabins",
])
def test_a_research_topic_about_logs_is_still_a_research_request(phrase) -> None:
    """⛔ The research rule runs first on purpose. A topic containing the word
    that routes another command must never hijack the run."""
    assert _argv(phrase)[0] == "research"


@pytest.mark.parametrize("phrase", [
    "what do the logs say",
    "check the logs",
    "show me the logs",
])
def test_reading_the_logs_is_not_sending_them(phrase) -> None:
    """Both a verb and the noun are required, so asking to LOOK at something
    never resolves to handing it to us."""
    argv, _lines = sr._nl_resolve(phrase)
    assert argv is None or argv[0] != "send-logs", (
        f"{phrase!r} resolved to sending logs")


# ── what SKILL.md tells the assistant ───────────────────────────────────────
#
# ⛔ The assistant reads SKILL.md, not this test file. Every rule the code
# enforces has to exist there in words, or the model improvises around it.

SKILL_MD = (_SR.parents[1] / "SKILL.md").read_text(encoding="utf-8")


def test_the_skill_document_explains_the_two_step() -> None:
    assert "Sending logs to support" in SKILL_MD
    assert "sends nothing" in SKILL_MD
    assert "--confirm" in SKILL_MD


def test_the_intent_table_points_at_the_bare_command_not_the_confirmed_one() -> None:
    """⛔⛔ THE TABLE IS WHAT A MODEL ACTUALLY READS. It is the lookup — "the user
    said this, run that" — and a row naming `--confirm` sends the assistant
    straight past the plan, whatever the section further down says.

    Checked as its own thing because the obvious assertions cannot see it: the
    words "sends nothing" and "--confirm" both still appear in the SECTION when
    the ROW has been rewritten, so a test looking for them anywhere in the file
    passes against precisely this change. Mutation caught that."""
    row = next((ln for ln in SKILL_MD.splitlines()
                if ln.startswith("|") and "send my logs" in ln), "")
    assert row, "the intent table no longer routes a send-logs request at all"
    assert "`sr.py send-logs`" in row, (
        "the table must send the assistant to the command that SHOWS first")
    assert "SHOWS what would go and sends nothing" in row
    before, after = row.split("`sr.py send-logs`", 1)
    assert "--confirm" not in before, (
        "the table reaches --confirm before the plan is ever printed")


def test_the_skill_document_forbids_confirming_on_the_users_behalf() -> None:
    """⛔⛔ THE ONE INSTRUCTION THAT CANNOT BE LEFT IMPLICIT. A chat model given
    a two-step and no reason will collapse it into one to be helpful, and the
    consent flag then claims a conversation that did not happen."""
    section = SKILL_MD.split("## Sending logs to support", 1)[1].split("\n## ", 1)[0]
    assert "wait for a real" in section
    assert "did not happen" in section or "consent" in section


def test_the_skill_document_says_the_machines_own_logs_are_the_owners() -> None:
    section = SKILL_MD.split("## Sending logs to support", 1)[1].split("\n## ", 1)[0]
    assert "the owner's" in section
    assert "everyone who uses it" in section


def test_the_skill_document_keeps_the_two_sentences_apart() -> None:
    """The distinction the code makes has to survive into the words, or the
    assistant paraphrases one into the other."""
    section = SKILL_MD.split("## Sending logs to support", 1)[1].split("\n## ", 1)[0]
    assert "not the same as" in section


def test_the_skill_document_forbids_polling_the_status() -> None:
    section = SKILL_MD.split("## Sending logs to support", 1)[1].split("\n## ", 1)[0]
    assert "never on a timer" in section


def test_the_safety_section_names_send_logs() -> None:
    """A reader who only skims Safety must still meet the two-step there."""
    safety = SKILL_MD.split("## Safety", 1)[1]
    assert "send-logs" in safety


# ── json mode ───────────────────────────────────────────────────────────────

def test_json_mode_says_what_would_be_sent(wire, capsys) -> None:
    _, out = _run(_args(json=True), capsys)
    body = json.loads(out)
    assert body["wouldSend"] == ["run-a", "run-b"]
    assert body["includeMachine"] is False
