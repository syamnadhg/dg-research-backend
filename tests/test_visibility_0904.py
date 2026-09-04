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
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    assert "Let other people find this computer and ask to use it?" in src
    assert "You approve each person." in src
    assert "anyone can use" not in src.lower()


def test_the_pairing_question_defaults_to_private():
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    i = src.index("Let other people find this computer and ask to use it?")
    assert "default=False" in src[i:i + 200]


def test_an_unreadable_stdin_leaves_the_machine_private():
    """⛔⛔ THE TWO NON-INTERACTIVE PATHS MUST AGREE. `_ask_yes_no` returns the
    DEFAULT after three unreadable answers, and the EOFError branch sets its own
    value. On the On-Startup question above, whose default is True, those two
    disagree — noise on stdin arms it, no stdin does not. Here both roads have
    to lead to private, or a scripted pair publishes a machine depending on what
    happened to be in the pipe."""
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    i = src.index("Let other people find this computer and ask to use it?")
    tail = src[i:i + 700]
    assert "except EOFError:" in tail
    eof = tail[tail.index("except EOFError:"):]
    assert "discoverable = False" in eof[:400]


def test_the_answer_is_WRITTEN_before_it_is_confirmed():
    """⛔⛔ FOUND BY CROSS-VERIFY. The first version printed
    "✓ People will be able to find it" and then wrote, discarding
    `_pair_patch_device`'s bool — so the tick stood through a network failure, a
    dead token and a rules refusal alike. `supervised` survives that (Stage 5
    writes it again on both branches); `visibility` has NO second writer in the
    whole pair flow, so the answer was lost for good while the screen said
    otherwise."""
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    write = src.index("saved = _pair_patch_device(device_id_for_progress")
    tick = src.index("People will be able to find it and ask you for access.")
    assert write < tick, "the confirmation must not precede the write it reports"
    # And the question must precede the write, or the answer written is the
    # initialiser rather than the person's.
    ask = src.index("Let other people find this computer and ask to use it?")
    assert ask < write


def test_a_lost_write_is_reported_as_lost():
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    i = src.index("elif discoverable:")
    branch = src[i:i + 500]
    assert "stays private for now" in branch
    assert "--visibility public" in branch


def test_each_branch_names_the_command_that_changes_ITS_state():
    """⛔ A single hint under both answers handed whoever said yes a command that
    is a no-op for them, and named the way back nowhere in the pair session."""
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    yes = src[src.index("if discoverable and saved:"):src.index("elif discoverable:")]
    assert "--visibility private" in yes
    no = src[src.index("     Only people you give the pair code to can ask."):]
    assert "--visibility public" in no[:400]


def test_both_stage_2_answers_go_in_ONE_patch():
    """⛔ The rule this lands on is `hasOnly()`, which refuses the WHOLE update
    when one key is off-list. Two calls would mean the second answer could be
    lost on its own; one call means the pair records what the person said, or
    records neither."""
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    calls = [i for i in range(len(src)) if src.startswith("_pair_patch_device(", i)]
    assert len(calls) == 1, f"expected one device PATCH in stage 2-5, saw {len(calls)}"
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
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    i = src.index("Stage 2 — discoverability")
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


def test_the_stage_count_is_untouched():
    """⛔ The question folded into Stage 2 rather than becoming a sixth stage.
    A 5→6 renumber is ~45 sites across six files of which the suite catches
    three — and this is one of the three."""
    src = inspect.getsource(research)
    assert "_setup_step(2, 5, \"On Startup\")" in src
    assert "_setup_step(5, 5" in src
