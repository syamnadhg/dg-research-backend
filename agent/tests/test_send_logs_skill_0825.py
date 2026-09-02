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


def test_the_plan_names_everything_the_apps_modal_names(wire, capsys) -> None:
    """Same requirement as the terminal's — see that test. Chat is where a fleet
    sharer actually confirms, so this is the copy that matters most."""
    _, out = _run(_args(), capsys)
    assert "anyone holding one can read them" in out
    assert "email address" in out
    assert "agent screens showed" in out


def test_the_plan_promises_a_retention_that_a_rule_now_keeps(wire, capsys) -> None:
    """✅ INVERTED 2026-08-26 — the sentence arrived with its rule.

    ⛔⛔ Every client refused this sentence until then, and `sendLogsCopy.ts`
    said so twice: no bucket lifecycle rule existed, so "deleted after 30 days"
    was a promise nothing kept. This surface shipped it anyway on its first day
    — an untrue retention claim on the one screen whose entire job is to be true
    about what leaves somebody's computer. The rule is live on the `logs/`
    prefix now and was read back by two independent tools before this changed.

    ⭐ Asserted on the OUTPUT, not the source, because a person reads the
    output — and this surface has already proved that a sentence can be right in
    the file and absent from the screen."""
    _, out = _run(_args(), capsys)
    assert "deleted automatically 30 days after it arrives" in out


def test_the_plan_does_not_promise_that_the_record_goes_too(wire, capsys) -> None:
    """⛔ The rule deletes the bundle. The row naming it survives — its TTL was
    measured undeployed the same day — and the sentence must not be widened."""
    _, out = _run(_args(), capsys)
    low = out.lower()
    for overreach in ("no record", "nothing is kept", "no trace",
                      "we keep nothing", "erased completely"):
        assert overreach not in low, f"claims the record goes too: {overreach}"


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
    """⛔ "ten minutes" was the assertion here, and it was the defect. A sharer
    refused because a co-tenant went first waits about a minute; nothing on the
    wire says which window fired."""
    wire.row = {"status": "failed", "errorClass": "CooldownActive"}
    rc, out = _run(_args(status="K7XQ9B2M"), capsys)
    assert rc == 1
    assert "very recently" in out
    assert "Try again shortly" in out
    assert "counts everyone who uses it" in out
    assert "perhaps for someone else" not in out
    assert "ten minutes" not in out, "the wait is not always ten minutes"
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


def test_the_skill_document_does_not_hand_the_model_a_wait_to_quote() -> None:
    """⛔⛔ THE DOCUMENT USED TO SAY "One bundle per ten minutes per person" AND
    CALL "Give it ten minutes" THE HONEST ANSWER. The assistant reads this and
    repeats it, so the wrong number reached a person through the document as
    well as through the client's own table. Both windows have to be in here, or
    the model reconstructs the single number from the one it was given."""
    section = SKILL_MD.split("## Sending logs to support", 1)[1].split("\n## ", 1)[0]
    assert "not always ten minutes" in section, (
        "the document must say the cooldown is not one number")
    assert "never a number" in section, (
        "the document must tell the assistant not to quote a duration")
    # ⛔⛔ MUTATION FOUND THIS ONE. Dropping the co-tenant clause left the document
    # describing a SINGLE window again, with the two assertions above still
    # passing — "not always ten minutes" says a number is wrong without saying
    # what is right, and a model handed only the long wait reconstructs it. The
    # fork's copy of this guard already asserted the short wait; ours did not,
    # so the two documents' guards had drifted while the documents agreed.
    assert "another user of that computer" in section, (
        "the document must name the co-tenant case, or only the long wait is known")
    assert "about a minute" in section, (
        "the document must describe the SHORT wait as well as the long one")
    assert '"Give it ten minutes" is the honest' not in section
    assert "One bundle per ten minutes per person" not in section


def test_the_safety_section_names_send_logs() -> None:
    """A reader who only skims Safety must still meet the two-step there."""
    safety = SKILL_MD.split("## Safety", 1)[1]
    assert "send-logs" in safety


# ── the agent's own log, as the ASSISTANT sees it ────────────────────────────
#
# ⛔⛔ THE CLIENT COULD DO THIS AND THE DOCUMENT NEVER OFFERED IT. `--agent-log`
# has been built, tested and mutated since 2026-08-26; the natural-language router
# reaches it, so a user who said the exact words got it. But the document is what
# an assistant reads to decide what to OFFER, and it named neither the flag nor
# the follow-up — so the option only ever existed for someone who already knew it
# existed. Measured against this file before these tests were written.


def _sending_logs_section() -> str:
    return SKILL_MD.split("## Sending logs to support", 1)[1].split("\n## ", 1)[0]


def _agent_log_bullet() -> str:
    """The agent-log bullet, whitespace-flattened.

    ⭐ FLATTENED ON PURPOSE. These guards are about the WORDS a model reads; the
    markdown is hand-wrapped, so a sentence that survives intact but crosses a
    line break differently would fail a raw substring match and teach the next
    reader to loosen the assertion instead of the wrapping.
    """
    section = _sending_logs_section()
    bullet = section[section.index("The agent's own log on THIS host"):]
    return " ".join(bullet[:bullet.index("\n- ")].split())


def test_the_document_offers_the_agents_own_log_at_all() -> None:
    assert "--agent-log" in _sending_logs_section()


def test_the_table_routes_someone_who_asks_for_it() -> None:
    """⛔⛔ THE TABLE IS THE LOOKUP, and the sibling guard above exists because a
    section can be right while the row is wrong. A section-only assertion cannot
    see a missing row: `--agent-log` still appears further down."""
    row = next((ln for ln in SKILL_MD.splitlines()
                if ln.startswith("|") and "--agent-log" in ln), "")
    assert row, "nothing in the intent table routes a request for the agent's log"
    assert "second" in row.lower() or "--status" in row, (
        "the row names the flag without the follow-up that actually sends it", row)


def test_the_document_names_the_follow_up_command_this_client_prints() -> None:
    """⛔ PINNED AGAINST THE CLIENT'S OWN DIRECTIVE, not against a remembered
    string. The client hands the assistant `--status <CODE> --agent-log`; a
    document that named a different spelling would hand it a second, conflicting
    instruction at exactly the moment it is deciding what to run."""
    src = _SR.read_text(encoding="utf-8")
    # ⛔ NOT an `or` against a looser pattern. The first draft accepted
    # "--status {support}" as a fallback — a string the UNCONDITIONAL check
    # directive already contains — so the guard passed with the agent-log
    # directive deleted. Mutation found it. This names the agent-log line alone.
    assert "--agent-log   (it is refused until then, by design)" in src, (
        "the client stopped printing the follow-up this document promises")
    assert "--agent-log" in _sending_logs_section()
    assert "--status <CODE> --agent-log" in SKILL_MD, (
        "the document must spell the follow-up the way the client prints it")


def test_the_document_does_not_let_it_ride_the_send() -> None:
    """⛔⛔ THE UPLOAD IS A SEPARATE STEP AND ALWAYS WAS. `cmd_send_logs` reads
    `agent_log` on the plan branch and on the `--status` branch; the confirmed send
    never posts it. An assistant told to add the flag to `--confirm` and left there
    would report a log as sent that no one ever uploaded.

    Pinned against the client so this fails loudly if the send path ever learns to
    carry it, rather than quietly documenting the old shape forever."""
    src = _SR.read_text(encoding="utf-8")
    body = src[src.index("def cmd_send_logs"):]
    body = body[:body.index("\ndef ", 1)]
    send = body[body.index('code, sent = _post("/logs/send"'):] \
        if 'code, sent = _post("/logs/send"' in body else body[body.index('"/logs/send"'):]
    assert "/logs/agent-log" not in send, (
        "the send path uploads it now — the document must stop saying it does not")
    assert "does not ride the send" in _agent_log_bullet()


def test_the_document_says_to_pass_it_on_the_confirmed_call_too() -> None:
    """⛔⛔ WITHOUT THE FLAG ON `--confirm` THIS CLIENT SAYS NOTHING AT ALL.
    `agent_log` is read a second time after the send, and that branch appends both
    the "goes up once that computer's bundle lands" line the PERSON hears and the
    follow-up command the ASSISTANT runs.

    The first draft of this row told the assistant to add the flag to the bare
    command and then claimed the client hands over the follow-up. Driven both
    ways, a plain `--confirm` printed neither line — so the row promised a
    directive the flow it prescribed could not produce, and the second step was
    left resting on a model remembering a command out of prose. Cross-verification
    measured that.

    Pinned against the branch rather than the sentence, so the day the client
    stops needing the flag there, this says so instead of going stale."""
    src = _SR.read_text(encoding="utf-8")
    body = src[src.index("def cmd_send_logs"):]
    body = body[:body.index("\ndef ", 1)]
    after_send = body[body.index('code, sent = _post("/logs/send", payload)'):]
    assert "if agent_log:" in after_send, (
        "the client no longer reads the flag after the send — the instruction to "
        "pass it on --confirm may now be stale")
    bullet = _agent_log_bullet()
    assert "pass it on `--confirm` too" in bullet, bullet
    row = next((ln for ln in SKILL_MD.splitlines()
                if ln.startswith("|") and "--agent-log" in ln), "")
    assert "`--confirm`" in row, (
        "the row omits the call that produces the follow-up it promises", row)


def test_the_document_does_not_borrow_the_owner_gate() -> None:
    """⛔⛔ MEASURED: THERE IS NO OWNERSHIP GATE ON THIS ONE. `--machine` is
    refused for a non-owner before any round trip, and it is documented in the
    bullet directly above. A reader carrying that gate across would withhold, on a
    rule that does not exist, something a person asked for — so the absence has to
    be stated rather than left to be inferred from silence."""
    src = _SR.read_text(encoding="utf-8")
    body = src[src.index("def cmd_send_logs"):]
    body = body[:body.index("\ndef ", 1)]
    code = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
    assert "if machine and not owned:" in code, "the gate this contrasts with is gone"
    assert "agent_log and not owned" not in code, (
        "a gate appeared — the document now understates what stops this")
    bullet = _agent_log_bullet()
    assert "no ownership gate" in bullet, bullet


def test_the_document_says_which_machine_the_log_is_on() -> None:
    """⛔ TWO DIFFERENT COMPUTERS. "The computer's own logs" is this document's
    phrase for the Research Computer, six lines above. Reads the BULLET rather
    than lines containing "agent", because a sentence that borrowed the wrong
    phrase would lose that word and duck a filter keyed on it."""
    bullet = _agent_log_bullet()
    assert "not their Research Computer" in bullet, bullet
    assert "the program running this chat" in bullet, bullet


def test_the_document_says_a_refusal_before_the_bundle_is_not_a_fault() -> None:
    """The ordering is the safety property, so its refusal is the design working.
    Read as a failure it becomes either a retry loop or a person told their log
    was lost."""
    bullet = _agent_log_bullet()
    assert "by design, not a fault" in bullet, bullet
    assert "leaves the bundle and the support code" in bullet, (
        "a failure here still reads as the whole send failing", bullet)
    assert "the log was empty" in bullet, "an empty log still reads as a failure"


def test_the_document_does_not_promise_it_covers_only_this_conversation() -> None:
    """⛔⛔ THE FILE IS NOT PER-SESSION. It is uploaded whole below the cap and
    tailed above it, covering everything since the last rotation — which on a
    quiet host is weeks, and can reach past the run being reported. A document
    that implied a session's worth would understate what leaves."""
    bullet = _agent_log_bullet()
    assert "since it last rotated" in bullet, bullet
    assert "not just this conversation" in bullet, bullet


# ── json mode ───────────────────────────────────────────────────────────────

def test_json_mode_says_what_would_be_sent(wire, capsys) -> None:
    _, out = _run(_args(json=True), capsys)
    body = json.loads(out)
    assert body["wouldSend"] == ["run-a", "run-b"]
    assert body["includeMachine"] is False
