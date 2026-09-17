"""7.7B — `--visibility` and the pairing question behind it.

⛔⛔ AN EMPTY READ IS NOT "PRIVATE". `_fetch_device_meta_rest` returns `{}` for a
network failure, an expired token, a missing device id AND a real document
alike. The absent-means-private rule is correct about a document and wrong about
a failure, and only one of those two directions matters: reporting a LISTED
machine as hidden is the answer that lets somebody believe they turned discovery
off when they did not. That is the first test below and the sharpest mutant.

⛔⛔ THE FLAG'S OWN TRAP IS ARGPARSE. `topic` is `nargs="?"`, and so is
`--visibility` — it has to be, or the bare form could not print the current
setting. So `superresearch --visibility "my topic"` binds the topic to the flag
and leaves the positional empty. argparse cannot express "optional value, but
only these two words" and there is no `choices=` anywhere in this file. The
manual check is what turns that from a silent wrong run into a sentence.

⛔ DISCOVERY, NOT ACCESS. Nothing here grants anybody anything: a discoverable
machine is one strangers can SEE and ASK about, the person approves every
request by hand, and the device document stays readable by exactly the same
three principals either way. The copy is tested for that, because copy that
promised otherwise would describe a product that was deliberately not built.
"""
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


# ── run_visibility, driven ───────────────────────────────────────────────────

@pytest.fixture
def wired(monkeypatch, capsys):
    """`run_visibility` with its three collaborators replaced, and a record of
    every device PATCH it attempted."""
    state = {"patches": [], "meta": {}, "device_id": "dev-1", "patch_ok": True}

    monkeypatch.setattr(research, "load_device_id", lambda: state["device_id"])
    monkeypatch.setattr(research, "_fetch_device_meta_rest", lambda: state["meta"])

    def _patch(device_id, fields, *a, **kw):
        state["patches"].append((device_id, dict(fields)))
        return state["patch_ok"]

    monkeypatch.setattr(research, "_pair_patch_device", _patch)
    # ⛔⛔ 7.9-0 ADDED A THIRD COLLABORATOR AND IT READS THE REAL KEYSTORE.
    # `run_visibility`'s empty-read branch now names a revoked session when it
    # can prove one, and it proves it from disk plus the OS keystore — so
    # without this line every assertion below would depend on whether the
    # developer running the suite happens to be paired, and would pass or fail
    # on a machine rather than on the code. Healthy is the default because it
    # is what the pre-existing tests were implicitly assuming.
    state["cred"] = research.CRED_HEALTHY
    monkeypatch.setattr(
        research, "credential_state_now", lambda *a, **kw: state["cred"]
    )
    # The flourish sleeps and the next-actions block prints; neither is under
    # test and both are noisy.
    monkeypatch.setattr(research, "_branded_header", lambda *a, **kw: None)
    state["out"] = lambda: capsys.readouterr().out
    return state


def test_an_unpaired_machine_is_told_so_and_nothing_is_written(wired):
    wired["device_id"] = ""
    code = research.run_visibility("public")
    assert code == 1
    assert wired["patches"] == []
    out = wired["out"]()
    assert "not paired" in out
    assert "--pair" in out


def test_a_failed_read_does_NOT_report_the_machine_as_private(wired):
    """⛔⛔ THE ONE THAT MATTERS. `{}` comes back from a network failure and from
    an expired token, not only from a document with no field. Applying
    absent-means-private to a read that never happened tells somebody their
    computer is hidden while it is listed."""
    wired["meta"] = {}
    code = research.run_visibility(research._VISIBILITY_SHOW)
    assert code == 1
    assert wired["patches"] == []
    out = wired["out"]()
    assert "Private" not in out
    assert "Public" not in out
    assert "Could not read" in out


def test_a_failed_read_refuses_to_WRITE_too(wired):
    """A set is not safer than a show here — without the current value the
    "already set" shortcut cannot be trusted either, and a blind write would
    report success against a machine nothing was read from."""
    wired["meta"] = {}
    code = research.run_visibility("public")
    assert code == 1
    assert wired["patches"] == []


def test_show_reports_public_for_a_listed_machine(wired):
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    assert wired["patches"] == []
    assert "Public" in wired["out"]()


def test_show_reports_private_when_the_field_is_absent(wired):
    """⛔ The installed base. Nothing backfills this field, so a machine paired
    before 2026-09-04 carries no key at all — and that is the most common
    document shape in production on the day this ships."""
    wired["meta"] = {"machineName": "studio"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    out = wired["out"]()
    assert "Private" in out
    assert "Public" not in out


@pytest.mark.parametrize("stored", ["Public", "PUBLIC", " public", "unlisted", "", "yes"])
def test_only_the_exact_word_public_reads_as_public(wired, stored):
    """The rules only started checking this value on 2026-09-04, so a document
    written before that can carry anything. The permissive answer must be
    reachable by exactly one value."""
    wired["meta"] = {"visibility": stored}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    assert "Private" in wired["out"]()


def test_showing_never_writes(wired):
    wired["meta"] = {"visibility": "private"}
    research.run_visibility(research._VISIBILITY_SHOW)
    assert wired["patches"] == []


def test_setting_public_writes_exactly_that_one_field(wired):
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility("public") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public"})]
    assert "Public" in wired["out"]()


def test_setting_private_writes_exactly_that_one_field(wired):
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility("private") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "private"})]


def test_setting_what_is_already_set_writes_nothing(wired):
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility("public") == 0
    assert wired["patches"] == []
    assert "Already set" in wired["out"]()


def test_an_absent_field_still_counts_as_already_private(wired):
    """No key and "private" are the same state, so `--visibility private` on an
    untouched machine must not write — a PATCH here would put the field on every
    document the flag was ever pointed at, for no change."""
    wired["meta"] = {"machineName": "studio"}
    assert research.run_visibility("private") == 0
    assert wired["patches"] == []


def test_a_refused_write_claims_NOTHING_about_the_resulting_state(wired):
    """⛔⛔ FOUND BY CROSS-VERIFY. `_pair_patch_device` returns False for four
    situations and only two of them prove the write did not land — a timeout and
    a 5xx both happen after the request went out, so Firestore may already have
    committed. The first version printed "Nothing changed. It is still: Private"
    in bold, which is the same class of lie the read guard above refuses: saying
    a machine is hidden when it may be listed."""
    wired["meta"] = {"visibility": "private"}
    wired["patch_ok"] = False
    code = research.run_visibility("public")
    assert code == 1
    out = wired["out"]()
    assert "Could not confirm" in out
    assert "may not have been saved" in out
    # ⛔ It must not assert either state as fact.
    assert "Nothing changed" not in out
    assert "It is still" not in out
    assert "Private" not in out
    assert "Public" not in out
    # ⛔ AND IT DOES NOT RETRY. A `hasOnly` refusal is a rules decision, not a
    # blip — re-sending the same PATCH cannot change the answer and only makes
    # the person wait for three of them.
    assert len(wired["patches"]) == 1


def test_the_write_is_one_of_two_words_and_never_a_boolean(wired):
    """`_pair_patch_device` maps a bool to `booleanValue` and everything it does
    not recognise to `str(v)`. A True here would land in Firestore as a boolean
    the rules refuse and the client narrows to private."""
    for asked in ("public", "private"):
        wired["patches"].clear()
        wired["meta"] = {"visibility": "public" if asked == "private" else "private"}
        research.run_visibility(asked)
        (_id, fields), = wired["patches"]
        assert fields == {"visibility": asked}
        assert isinstance(fields["visibility"], str)


def test_a_dropped_topic_is_named_back_with_the_command_that_would_run_it(wired):
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility("public", ignored_topic="why do cats purr") == 0
    out = wired["out"]()
    assert "Ignoring the topic" in out
    assert "why do cats purr" in out
    # ⛔ And it lands BEFORE the answer, not after it — a notice printed under
    # the result reads as a footnote to a run that already happened.
    assert out.index("Ignoring the topic") < out.index("Public")


def test_no_notice_when_no_topic_was_passed(wired):
    wired["meta"] = {"visibility": "private"}
    research.run_visibility("public")
    assert "Ignoring the topic" not in wired["out"]()


# ── the flag, through the real parser ────────────────────────────────────────

def _cli(*args, tmp_home):
    """Run the real CLI in a child process with a throwaway HOME, so the
    machine's own pairing state is neither read nor relocated."""
    env = dict(os.environ, HOME=str(tmp_home), DG_ALERT_AI_COPY="0")
    env.pop("SUPERRESEARCH_STATE_DIR", None)
    return subprocess.run(
        [sys.executable, "research.py", *args],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300,
    )


def test_a_topic_passed_as_the_flags_value_is_REFUSED_not_swallowed(tmp_path):
    """⛔⛔ THE MISPARSE. `topic` is `nargs="?"` and so is this flag, so argparse
    binds the next word to the flag and leaves the positional empty. Without the
    manual check the run would simply do nothing and say nothing."""
    r = _cli("--visibility", "my topic", tmp_home=tmp_path)
    assert r.returncode == 2, r.stdout[-2000:] + r.stderr[-2000:]
    err = r.stderr
    assert "--visibility" in err
    assert "public" in err and "private" in err
    # And it points at the form the person almost certainly meant.
    assert '"my topic"' in err


def test_an_unknown_word_is_refused_by_name(tmp_path):
    r = _cli("--visibility", "unlisted", tmp_home=tmp_path)
    assert r.returncode == 2
    assert "unlisted" in r.stderr


def test_the_bare_flag_reaches_the_command_rather_than_asking_for_a_topic(tmp_path):
    """The bare form must dispatch BEFORE `parser.error('Provide topic')`. With
    a throwaway HOME nothing is paired, so the honest answer is the not-paired
    refusal — exit 1, not argparse's exit 2."""
    r = _cli("--visibility", tmp_home=tmp_path)
    assert r.returncode == 1, r.stdout[-2000:] + r.stderr[-2000:]
    assert "not paired" in r.stdout
    assert "Provide topic" not in r.stderr


def test_a_topic_alongside_the_flag_is_dropped_OUT_LOUD(tmp_path):
    """⛔ Five other flags in this parser are silently ignored when passed with
    the wrong command. This is the one where silence looks exactly like the
    misparse above having gone unnoticed."""
    r = _cli("my topic", "--visibility", tmp_home=tmp_path)
    assert r.returncode == 1
    assert "Ignoring the topic" in r.stdout
    # And it certainly did not research it.
    assert "Phase" not in r.stdout


# ── the surfaces a user actually reads ───────────────────────────────────────

def test_the_flag_is_on_the_help_screen():
    """⛔ `add_help=False`, and nothing in this file calls `format_help` or
    `print_help` — every `help=` string on every add_argument is text no user
    can reach. `run_commands_help` is the only discovery surface there is, which
    is how --send-logs, --update and --uninstall all shipped undocumented."""
    src = inspect.getsource(research.run_commands_help)
    assert "--visibility" in src
    assert "python research.py --visibility" in src, (
        "rows are authored with the python prefix and rewritten to _PROG in "
        "_section — a row written the other way loses the swap"
    )


def test_the_help_row_says_FIND_not_use():
    src = inspect.getsource(research.run_commands_help)
    row = src[src.index("--visibility"):][:400]
    assert "FIND" in row
    assert "approve" in row


def test_the_pairing_question_asks_to_FIND_and_promises_approval():
    """⛔⛔ THE WORDING IS THE FEATURE. Answering yes grants nobody anything: the
    person still approves every request by hand and an approved person becomes
    an ordinary sharer. A question implying otherwise would be asking for
    consent to something that does not happen."""
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    assert "Let other people find this computer and ask to use it?" in src
    assert "You approve each person." in src
    assert "anyone can use" not in src.lower()


def test_the_pairing_question_defaults_to_private():
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    i = src.index("Let other people find this computer and ask to use it?")
    assert "default=False" in src[i:i + 200]


def test_an_unreadable_stdin_leaves_the_machine_private():
    """⛔⛔ THE TWO NON-INTERACTIVE PATHS MUST AGREE. `_ask_yes_no` returns the
    DEFAULT after three unreadable answers, and the EOFError branch sets its own
    value. On the On-Startup question above, whose default is True, those two
    disagree — noise on stdin arms it, no stdin does not. Here both roads have
    to lead to private, or a scripted pair publishes a machine depending on what
    happened to be in the pipe."""
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    i = src.index("Let other people find this computer and ask to use it?")
    tail = src[i:i + 700]
    assert "except EOFError:" in tail
    eof = tail[tail.index("except EOFError:"):]
    assert "discoverable = False" in eof[:400]


def test_the_answer_is_WRITTEN_before_it_is_confirmed():
    """⛔⛔ FOUND BY CROSS-VERIFY. The first version printed
    "✓ People will be able to find it" and then wrote, discarding
    `_pair_patch_device`'s bool — so the tick stood through a network failure, a
    dead token and a rules refusal alike. `supervised` survives that (Stage 6
    writes it again on both branches); `visibility` has NO second writer in the
    whole pair flow, so the answer was lost for good while the screen said
    otherwise."""
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    write = src.index("saved = _pair_patch_device(device_id_for_progress")
    tick = src.index("People will be able to find it and ask you for access.")
    assert write < tick, "the confirmation must not precede the write it reports"
    # And the question must precede the write, or the answer written is the
    # initialiser rather than the person's.
    ask = src.index("Let other people find this computer and ask to use it?")
    assert ask < write


def test_a_lost_write_is_reported_as_lost():
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    i = src.index("elif discoverable:")
    branch = src[i:i + 500]
    assert "stays private for now" in branch
    assert "--visibility public" in branch


def test_each_branch_names_the_command_that_changes_ITS_state():
    """⛔ A single hint under both answers handed whoever said yes a command that
    is a no-op for them, and named the way back nowhere in the pair session."""
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    yes = src[src.index("if discoverable and saved:"):src.index("elif discoverable:")]
    assert "--visibility private" in yes
    # ⛔ RE-POINTED IN WAVE 9, NOT WEAKENED. This is `str.index`, so when the
    # machine's prose moved from "pair code" to the web's word it raised
    # ValueError rather than failing — the loudest-but-least-readable way for a
    # rename to break a guard. The slice still has to start at the PRIVATE
    # branch's own sentence, which is the whole point of the assertion below.
    no = src[src.index("     Only people you give the access code to can ask."):]
    assert "--visibility public" in no[:400]
    # ⛔ AND THE OLD WORD IS GONE FROM THIS FUNCTION, so a half-migration that
    # leaves one branch saying each cannot pass: the two sentences sit four
    # printed lines apart on the same screen.
    assert "pair code" not in src, (
        "the pair session still says 'pair code' somewhere; the web app calls "
        "this value an access code in every label it has"
    )


def test_both_stage_2_answers_go_in_ONE_patch():
    """⛔ The rule this lands on is `hasOnly()`, which refuses the WHOLE update
    when one key is off-list. Two calls would mean the second answer could be
    lost on its own; one call means the pair records what the person said, or
    records neither.

    ⛔⛔ AND SINCE 2026-09-17 THE TWO ANSWERS ARE ASKED UNDER SEPARATE STEP
    HEADERS — [2/6] On Startup and [3/6] Discoverability — while still sharing
    this one write. Splitting the display is exactly what tempts someone to
    split the call, so the single-call count below now guards a boundary the
    screen appears to draw."""
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    calls = [i for i in range(len(src)) if src.startswith("_pair_patch_device(", i)]
    assert len(calls) == 1, f"expected one device PATCH in stages 2-6, saw {len(calls)}"
    # ⛔ AND IT LANDS AFTER BOTH QUESTIONS. A write hoisted up under step 2 would
    # still be one call, and would still pass the count above — while leaving the
    # step-3 answer with no writer at all.
    assert calls[0] > src.index('_setup_step(3, 6, "Discoverability")'), (
        "the shared patch must come after the discoverability question, not "
        "between the two steps"
    )
    body = src[calls[0]:calls[0] + 300]
    assert '"supervised": bool(enable_on_startup),' in body
    # ⛔ THE VALUE IS ONE OF TWO WORDS, NOT A BOOLEAN. `_pair_patch_device` maps a
    # bool to `booleanValue` and anything it does not recognise to `str(v)`, so a
    # True here would land in Firestore as a type the rules refuse and the client
    # narrows to private — a setting the person chose, stored as a lie.
    assert '"visibility": "public" if discoverable else "private",' in body


def test_the_pairing_cancel_returns_False_rather_than_falling_out():
    """⛔⛔ This function is annotated `-> None` and lies. `cmd_pair_v2` reads its
    result as `pair_completed = bool(...)`, and a falsy value runs
    `_cleanup_partial_pair`, which reverts the device doc and the token. Every
    cancel path in it must say `return False` on purpose — a bare `return` gets
    the right answer by accident and the wrong one the moment it is copied."""
    src = inspect.getsource(research._continue_pair_stages_2_to_6)
    i = src.index("Stage 3 — discoverability")
    assert "return False" in src[i:i + 120]
    # And no bare `return` anywhere in the function's own body (the nested
    # progress helper has one, so this looks only at top-level indentation).
    # ⛔⛔ THE FIRST VERSION OF THIS ASSERTION WAS INERT, and cross-verify caught
    # it: it accepted any bare `return` at 8-space indentation, which is exactly
    # where every cancel branch in this function sits. It permitted the thing it
    # was written to forbid.
    #
    # The real invariant: the ONLY bare `return` in this function belongs to the
    # nested `_push_firestore_progress` helper, at 12 spaces. Any bare `return`
    # at the function's own 8-space level is a cancel path that would silently
    # revert the whole pair, so there must be none.
    bare = [ln for ln in src.splitlines() if ln.strip() == "return"]
    assert bare, "sanity: the nested helper still has one"
    for ln in bare:
        indent = len(ln) - len(ln.lstrip())
        assert indent >= 12, (
            f"a bare `return` at indent {indent} is one of this function's own "
            f"exits; it evaluates to None, which reverts the whole pair"
        )


def test_the_discoverability_question_is_its_own_stage():
    """⭐ THE SIXTH STAGE WAS BUILT ON 2026-09-17, and this test used to refuse it.

    It was `test_the_stage_count_is_untouched`, and it pinned the old arc on the
    grounds that "a 5→6 renumber is ~45 sites across six files of which the suite
    catches three". Two things changed. The owner asked for the sixth step, which
    is not a question the renumber cost gets to answer; and the recount found the
    old figure wrong in both directions — four banner comments in this arc rather
    than six, but also this helper's own NAME, which encoded the count and is
    reached by `inspect.getsource` from ten test sites.

    So the pin is inverted, not deleted: the arc is still deliberate, it is just
    deliberately six now. Every step is anchored on its FULL call including the
    title, because `"_setup_step(2, 6" in src` alone would be satisfiable by any
    other arc that grew to six steps.
    """
    src = inspect.getsource(research)

    # The six displayed steps, in order, each with its title.
    arc = [
        '_setup_step(1, 6, "Token setup")',
        '_setup_step(2, 6, "On Startup")',
        '_setup_step(3, 6, "Discoverability")',
        '_setup_step(4, 6, "API keys")',
        '_setup_step(5, 6, "Browser logins")',
        '_setup_step(6, 6, "Ready")',
    ]
    for call in arc:
        assert call in src, call
    # …and they appear in that order in the file, so a step cannot be renumbered
    # into the wrong position and still pass on presence alone.
    where = [src.index(c) for c in arc]
    assert where == sorted(where), dict(zip(arc, where))

    # ⛔ THE OLD ARC CANNOT COME BACK. These are the exact literals the refusing
    # version of this test pinned; both must now be absent.
    assert '_setup_step(2, 5, "On Startup")' not in src
    assert "_setup_step(5, 5" not in src
    # Nor any other pair-arc call still claiming a five-step total.
    for n in (1, 2, 3, 4, 5):
        assert f"_setup_step({n}, 5," not in src, n

    # ⛔⛔ AND THE OTHER THREE ARCS DID NOT MOVE. `_setup_step` is shared with
    # --unpair (5), --resurrect (4) and --retire (3); a naive 5→6 sweep would
    # have rewritten about eighteen sites across them.
    assert "total = 5" in src, "--unpair's own five-step total"
    assert "_setup_step(5, total, " in src, "--unpair's last step"
    assert "_setup_step(1, total, " in src, "--unpair's first step"
    assert "_setup_step(4, 4, " in src, "--resurrect is four steps"
    assert "_setup_step(3, 3, " in src, "--retire is three steps"


# ── 7.9-0: the empty-read branch stops blaming the network ───────────────────

def test_a_revoked_session_is_named_instead_of_the_network(wired):
    """⛔⛔ MEASURED ON THE OWNER'S MACHINE, 2026-09-06. They reset their pair
    code — which revokes this machine's token by design — and every later run
    of this command told them to check the network. The program already knew:
    the reset wiped the keystore and the wipe logged itself. It just never
    asked before printing."""
    wired["meta"] = {}
    wired["cred"] = research.CRED_NO_TOKEN
    assert research.run_visibility(research._VISIBILITY_SHOW) == 1
    out = wired["out"]()
    assert "revoked" in out
    assert "Check the network" not in out
    assert wired["patches"] == []


def test_a_revoked_session_never_recommends_pairing(wired):
    """⛔ THE DESTRUCTIVE HALF. Pairing mints a new device id, and a new device
    is private — so the advice would have cost this owner both the machine's
    identity and the public listing they were trying to check."""
    wired["meta"] = {}
    wired["cred"] = research.CRED_NO_TOKEN
    research.run_visibility("public")
    out = wired["out"]()
    advice = "\n".join(l for l in out.splitlines() if "⛔" not in l)
    assert "--pair" not in advice
    assert "--serve" in out


def test_a_failed_SET_says_the_setting_was_not_changed(wired):
    """⛔⛔ THE OWNER ASKED FOR A WRITE AND WAS TOLD A READ FAILED. One branch
    served both requests, so the only honest reading of the output was "it
    might have worked" — about the one setting they had just tried to change."""
    wired["meta"] = {}
    research.run_visibility("public")
    assert "Nothing was changed" in wired["out"]()


def test_a_failed_SHOW_does_not_claim_nothing_was_changed(wired):
    """⛔ THE OVER-CORRECTION. Somebody who typed no value changed nothing and
    is owed no verdict on it; saying so anyway is noise that makes the real
    message harder to find."""
    wired["meta"] = {}
    research.run_visibility(research._VISIBILITY_SHOW)
    assert "Nothing was changed" not in wired["out"]()


def test_an_unprovable_failure_still_falls_back_to_the_old_sentence(wired):
    """⭐ THE READ IS STILL AMBIGUOUS AND THIS WAVE DOES NOT PRETEND OTHERWISE.
    The fetch returns {} for six reasons and only one of them is nameable from
    disk. When the credentials look healthy the cause really is unknown, and
    the honest answer is the one that does not claim to know."""
    wired["meta"] = {}
    wired["cred"] = research.CRED_HEALTHY
    research.run_visibility(research._VISIBILITY_SHOW)
    out = wired["out"]()
    assert "Could not read" in out
    assert "revoked" not in out


# ── wave 9: the rename, and the half that never learned it ───────────────────
#
# ⛔⛔ EVERY PIN ABOVE THIS LINE SETS ONLY `visibility`, so old-first and
# new-first pass all of them identically and none of them can tell the two apart.
# `visibility` is becoming `joinPolicy`; the rules learned both names in wave 7
# and the agent learned to read both in wave 8, and this file — the machine —
# never learned the new one at all. A pin that sets ONE key measures NOTHING
# here, which is why the ones below set both, in conflict, or set only the new
# one on a document the old one has already left.

def test_the_new_name_is_read_when_the_old_one_is_gone(wired):
    """⛔⛔ THE DAY THE MIGRATION LANDS. A document carrying only `joinPolicy`
    read "private" to the very machine that owns it — so `--visibility` printed
    Private on a listed computer, with no error and nothing to notice it by."""
    wired["meta"] = {"joinPolicy": "public"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    out = wired["out"]()
    assert "Public" in out
    assert "Private" not in out


def test_the_new_name_reads_private_too_when_that_is_what_it_says(wired):
    """The complement, so the fix cannot be "treat the new key as public"."""
    wired["meta"] = {"joinPolicy": "private"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    assert "Private" in wired["out"]()


def test_the_toggle_CLOSES_the_door_on_a_machine_public_under_the_NEW_name(wired):
    """⛔⛔ THE SHARPEST CONSUMER, AND THE ONE A HELPER PIN WOULD MISS. Reading
    the old literal alone, a machine public under the new name looks private
    here — so `--visibility private` is answered "Already set — nothing to
    change", NO WRITE GOES OUT, and the computer stays discoverable. Somebody is
    told a door is shut while it stands open.

    ⛔ And the write still lands on the OLD key: reading both names is
    compatible, writing the new one is not."""
    wired["meta"] = {"joinPolicy": "public"}
    assert research.run_visibility("private") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "private"})]
    assert "Already set" not in wired["out"]()


def test_the_OLD_name_wins_while_it_is_still_there(wired):
    """⛔⛔ THE ORDERING PIN, AND THE ONLY THING THAT REFUSES NEW-FIRST. Wave 8's
    first build preferred `joinPolicy`, reasoning that its presence proved the
    document had been migrated — and cross-verify overturned it. Nothing writes
    the new key yet, and everything that ACTS on the setting reads the old one:
    the app's public list queries `where("visibility", "==", "public")`, and both
    of this program's own writes put `visibility` down. A reader must agree with
    the writers, not with the migration's destination.

    ⛔ HONEST ABOUT WHAT THIS MEASURES: it cannot fail against the code as it was
    an hour ago, because old-only and old-first agree on every document that
    carries a real `visibility`. It fails against NEW-first, which is the wrong
    build this wave could have shipped instead — mutants V2b and V2c."""
    wired["meta"] = {"visibility": "public", "joinPolicy": "private"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    assert "Public" in wired["out"]()

    wired["meta"] = {"visibility": "private", "joinPolicy": "public"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    out = wired["out"]()
    assert "Private" in out
    assert "Public" not in out


def test_the_OLD_name_wins_on_the_TOGGLE_so_the_door_still_closes(wired):
    """⛔⛔ WHERE PREFERRING THE NEW KEY COSTS MONEY-SHAPED HARM. On a document
    still carrying `visibility: private` beside a stale `joinPolicy: public`, a
    new-first reader answers "already public" to `--visibility public` and writes
    nothing — and the owner's change is silently dropped."""
    wired["meta"] = {"visibility": "private", "joinPolicy": "public"}
    assert research.run_visibility("public") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public"})]


def test_a_cleared_OLD_name_falls_through_to_the_NEW_one(wired):
    """⛔ HALF-MIGRATED IS A REAL DOCUMENT SHAPE. The rules allow clearing
    `visibility` and allow writing `joinPolicy` beside it, so an empty old key
    next to a real new one can exist — and "empty" is not an answer. It must keep
    looking rather than stop and report private."""
    wired["meta"] = {"visibility": "", "joinPolicy": "public"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    assert "Public" in wired["out"]()


def test_a_NON_STRING_old_value_does_not_swallow_the_new_one(wired):
    """⛔ `_fetch_device_meta_rest` unwraps `booleanValue` to a real bool and
    `integerValue` to an int, and mutant B5 is precisely a `visibility` written
    as a bool — so a document whose old key is `True` is mintable by this repo's
    own known defect. A junk old value is not an answer either."""
    wired["meta"] = {"visibility": True, "joinPolicy": "public"}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 0
    assert "Public" in wired["out"]()


def test_the_machine_reads_both_names_and_WRITES_only_the_old_one(wired):
    """⭐ STATED AS THE RULE, NOT AS TWO EXAMPLES: the key this program believes
    FIRST must be the key it actually writes, or its own toggle and its own
    reader disagree about the machine in front of them. Derived from a real
    driven write, not from a literal this test made up.

    ⛔ Writing `joinPolicy` would take the old key off a document every
    un-upgraded machine in the field is still reading — and the app's public list
    would stop listing the computer. The old key comes off when a fleet reading
    says nobody is writing it, not when a wave number says so."""
    wired["meta"] = {"joinPolicy": "public"}
    assert research.run_visibility("private") == 0
    (_id, fields), = wired["patches"]
    written_key, = fields.keys()
    assert written_key == research._DISCOVERY_KEYS[0]
    assert "joinPolicy" not in fields
    # ⛔ And both names are known, in that order — one alone is the defect.
    assert research._DISCOVERY_KEYS == ("visibility", "joinPolicy")


@pytest.mark.parametrize(
    "meta",
    [
        {},
        {"machineName": "studio"},
        {"joinPolicy": ""},
        {"joinPolicy": None},
        {"joinPolicy": 1},
        {"visibility": "", "joinPolicy": ""},
        {"visibility": True, "joinPolicy": False},
    ],
)
def test_nothing_recognisable_under_either_name_reads_as_private(meta):
    """⛔ ABSENT IS PRIVATE, AND SO IS JUNK. A machine paired before 2026-09-04
    carries neither key and nothing backfills one; the safe direction for a
    discovery setting is the one that hides."""
    assert research._discovery_of(meta) == "private"


def test_an_EMPTY_read_still_never_reaches_the_resolver_s_answer(wired):
    """⛔⛔ THE PORT'S ONE REAL HAZARD, PINNED. `_discovery_of({})` answers
    "private" exactly like a real document with no field — so if the resolution
    were ever hoisted ABOVE the empty-read guard, a network blip would report a
    LISTED machine as hidden again. The guard is the whole difference and it
    stays on top."""
    assert research._discovery_of({}) == "private"
    wired["meta"] = {}
    assert research.run_visibility(research._VISIBILITY_SHOW) == 1
    out = wired["out"]()
    assert "Private" not in out
    assert "Could not read" in out
