"""Wave 8 step I — choosing which runs `--send-logs` includes, from the terminal.

⛔⛔ WHAT `--runs N` COULD NOT DO. It took a COUNT, and the collector applied it
as "the newest N inside the age window" — so a person reporting one run that hung
on Tuesday either sent thirty or guessed how far back theirs was. There was no
list and no numbers; `_select_bundle_runs` picked for them.

⭐⭐ THE OWNER AT THE MACHINE SEES EVERY RUN ON IT, including the ones attributable
to nobody — which today is all of them, since no shipped build recorded a
submitter. They already hold these files on their own disk, so listing them
grants nothing; withholding them would hide the machine's whole history from the
one person who can act on it. That is the deliberate difference from the app,
where everybody sees only the runs they fired.

⛔ AND THE PROMPT REFUSES RATHER THAN GUESSING, on this file's standing rule: a
malformed request must never resolve toward MORE collection than was agreed to.
"""
import re

import pytest

import research


# ══ 1. what a numbered row may say ═════════════════════════════════════
def test_a_row_says_when_it_ran_how_it_ended_and_how_big_it_is():
    line = research._format_run_choice(3, {
        "startedUtc": "2026-08-20T04:41:11Z", "status": "complete",
        "sizeBytes": 123456})
    assert line.strip().startswith("3.")
    assert "2026-08-20 04:41:11" in line
    assert "complete" in line
    assert "120 KB" in line


def test_a_row_carries_NO_topic_and_NO_title():
    """⛔⛔ NOT BECAUSE THE PERSON MAY NOT SEE IT — they are standing at their own
    machine and hold every one of these files. It is because there is nowhere to
    READ one from. A run folder carries no topic and no title anywhere, by
    design; the only topic text is inside `run.log`, and a parser over
    user-controlled text feeding a disclosure decision is what this wave's design
    rejected outright."""
    row = {"startedUtc": "2026-08-20T04:41:11Z", "status": "complete",
           "sizeBytes": 1, "topic": "the owner's private research subject",
           "researchId": "chat_1787200458393_2"}
    line = research._format_run_choice(1, row)
    assert "private research subject" not in line
    assert "chat_1787200458393_2" not in line


def test_a_row_with_nothing_recorded_still_renders():
    """A folder with a broken meta still becomes a row, and a row that renders as
    a traceback is a list nobody can choose from."""
    line = research._format_run_choice(1, {})
    assert "unknown" in line
    assert "0 KB" in line


# ══ 2. the answer parser ═══════════════════════════════════════════════
@pytest.mark.parametrize("answer,expect", [
    ("1", [0]),
    ("1,3", [0, 2]),
    ("1, 3", [0, 2]),
    ("1 3", [0, 2]),
    ("3,1", [2, 0]),
    ("2,2,2", [1]),
    ("all", [0, 1, 2, 3, 4]),
    ("ALL", [0, 1, 2, 3, 4]),
    ("a", [0, 1, 2, 3, 4]),
    ("*", [0, 1, 2, 3, 4]),
    ("", []),
    ("   ", []),
])
def test_the_answers_a_person_actually_types(answer, expect):
    assert research._parse_run_choice(answer, 5) == expect


@pytest.mark.parametrize("answer", ["1-3", "0", "6", "-1", "two", "1;3", "1.5", "y"])
def test_an_unreadable_answer_REFUSES(answer):
    """⛔⛔ INCLUDING `1-3`, WHICH IS THE ONE THAT MATTERS. A range is the obvious
    thing to accept, and accepting it silently would send run 2 to somebody who
    typed a dash meaning "1 and 3". Every ambiguity here resolves toward
    collecting LESS or toward asking again — never toward more."""
    assert research._parse_run_choice(answer, 5) is None


def test_an_empty_answer_is_a_CHOICE_not_an_absence():
    """⭐ It means the machine-level bundle — the pairing-failure case, which is
    exactly when there are no runs to choose from. `[]` and `None` are different
    answers and the caller branches on which."""
    assert research._parse_run_choice("", 5) == []
    assert research._parse_run_choice("nonsense", 5) is None


def test_a_count_of_zero_accepts_only_the_empty_answers():
    assert research._parse_run_choice("", 0) == []
    assert research._parse_run_choice("all", 0) == []
    assert research._parse_run_choice("1", 0) is None


# ══ 3. the prompt ══════════════════════════════════════════════════════
def _rows(n):
    return [{"name": f"chat_{i}_1_2026082{i}T000000", "startedUtc": f"2026-08-2{i}T00:00:00Z",
             "status": "complete", "sizeBytes": 1024} for i in range(n)]


def test_the_chosen_names_come_back_in_the_order_typed(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _p: "3,1")
    picked = research._choose_runs_interactively(_rows(3))
    assert picked == ["chat_2_1_20260822T000000", "chat_0_1_20260820T000000"]


def test_every_run_is_offered_including_unattributed_ones(monkeypatch, capsys):
    """⭐⭐ THE DELIBERATE DIFFERENCE FROM THE APP. Every run folder in the field
    is attributable to nobody, so an attribution filter here would show the owner
    an empty list on their own machine."""
    rows = _rows(3)
    for r in rows:
        r["submitterUid"] = None
    monkeypatch.setattr("builtins.input", lambda _p: "all")
    assert len(research._choose_runs_interactively(rows)) == 3
    out = capsys.readouterr().out
    assert out.count("complete") >= 3


def test_an_unreadable_answer_is_re_asked_and_then_GIVES_UP_OUT_LOUD(monkeypatch, capsys):
    """⛔ The same rule the yes/no reader gives up under: never apply a default
    nobody chose, and never decide in silence."""
    monkeypatch.setattr("builtins.input", lambda _p: "banana")
    assert research._choose_runs_interactively(_rows(3)) is None
    out = capsys.readouterr().out
    assert out.count("Numbers from the list") == 3
    assert "Nothing was sent" in out


def test_a_readable_answer_after_a_bad_one_is_accepted(monkeypatch, capsys):
    answers = iter(["nope", "2"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    assert research._choose_runs_interactively(_rows(3)) == ["chat_1_1_20260821T000000"]


def test_ctrl_c_at_the_prompt_quits_rather_than_choosing(monkeypatch, capsys):
    def _boom(_p):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _boom)
    assert research._choose_runs_interactively(_rows(3)) is None


def test_a_machine_with_no_runs_says_so_and_does_not_prompt(monkeypatch, capsys):
    def _never(_p):
        raise AssertionError("it prompted with nothing to choose from")
    monkeypatch.setattr("builtins.input", _never)
    assert research._choose_runs_interactively([]) == []
    assert "holding no run logs" in capsys.readouterr().out


def test_the_prompt_echoes_what_it_understood(monkeypatch, capsys):
    """⛔ A silent interpretation is how "2" became a yes at a prompt that never
    offered it — the defect that produced this file's yes/no reader."""
    monkeypatch.setattr("builtins.input", lambda _p: "1,2")
    research._choose_runs_interactively(_rows(3))
    assert "Sending 2 run(s)." in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda _p: "")
    research._choose_runs_interactively(_rows(3))
    assert "own logs only" in capsys.readouterr().out


# ══ 4. the consent screen the choice produces ══════════════════════════
def test_a_selection_states_an_EXACT_count_not_a_ceiling():
    """⛔⛔ "at most n" is a CEILING, and it is the honest reading when the
    collector picks — it sorts age-eligible runs newest-first and takes the top
    n, so a machine with fifty inside the window sends thirty. With a selection
    the person named them, so the count is exact and "at most" would understate
    a request they made precisely."""
    line = research._send_logs_consent_lines(2, chosen_exactly=True)[0]
    assert line == "the 2 runs you chose, and only those"
    assert "at most" not in line


def test_and_the_age_bound_drops_with_it():
    """It can no longer remove anything that was picked — every name came from a
    list of what the machine actually holds. Repeating it would describe a filter
    with nothing left to filter."""
    line = research._send_logs_consent_lines(2, chosen_exactly=True)[0]
    assert str(research.BUNDLE_MAX_AGE_DAYS) not in line


def test_choosing_NOTHING_says_so_rather_than_reading_as_all():
    line = research._send_logs_consent_lines(0, chosen_exactly=True)[0]
    assert "no runs" in line
    assert "own log files only" in line


def test_one_run_reads_as_one_run():
    assert "the 1 run you chose" in research._send_logs_consent_lines(1, chosen_exactly=True)[0]


def test_without_a_selection_the_copy_is_untouched():
    """⛔ EVERY EXISTING CALLER GOES THROUGH THIS FUNCTION. If the default changed,
    the plain `--send-logs` screen would start describing a different bundle."""
    line = research._send_logs_consent_lines(5)[0]
    assert line.startswith("at most 5 runs from this machine")
    assert f"last {research.BUNDLE_MAX_AGE_DAYS} days" in line


def test_the_honesty_line_survives_a_selection_and_names_it_correctly():
    """⛔⛔ THE SENTENCE THAT KEEPS THE SCREEN HONEST. Everything below the first
    line is unaffected by the choice: the sessions are age-bound only and the raw
    tails have no bound at all, and those tails carry the same topics, links and
    account email for the machine's whole history."""
    lines = research._send_logs_consent_lines(2, chosen_exactly=True)
    warn = [l for l in lines if l.startswith("⚠")]
    assert len(warn) == 1
    assert "only the first line above" in warn[0]
    assert "whichever runs you pick" in warn[0]
    # …and it does NOT talk about a number, because there is no longer a control
    # with a number on it.
    assert "-run choice" not in warn[0]


def test_the_lines_the_choice_does_not_govern_are_identical_either_way():
    """The middle of the list is the same facts whatever was chosen — which is
    what the ⚠ line above asserts in words."""
    a = research._send_logs_consent_lines(2, chosen_exactly=True)
    b = research._send_logs_consent_lines(9, chosen_exactly=True)
    assert a[1:-1] == b[1:-1]


def test_no_replacement_field_spans_lines():
    """⛔⛔ CAUGHT BY RUFF, NOT BY A TEST, AND IT WAS A REAL BREAK. The first draft
    of the chooser's hint line put a LINE BREAK inside an f-string replacement
    field. That is Python 3.12+ syntax, and `pyproject` declares
    `requires-python = ">=3.11"` — so on the floor this repo supports it is a
    SyntaxError at IMPORT: the whole backend fails to start, on every command,
    with nothing in this suite noticing because the dev interpreter is newer.

    ⛔⛔ AND MY FIRST TWO GUARDS FOR IT WERE BOTH WRONG, in opposite directions.

    The first called `ast.parse(..., feature_version=(3, 11))` and asserted the
    module still parsed — which it does either way: `feature_version` does not
    restore the pre-3.12 f-string tokenizer. MEASURED: the exact construct that
    broke parses happily under both `(3, 11)` and `(3, 12)`. A guard that cannot
    fire, added while fixing a real defect, is this codebase's signature mistake.

    The second flagged any f-string LITERAL spanning lines — and MEASURED, this
    file has 814 of those. They are implicit concatenations of adjacent string
    literals, which every version allows and which this file uses everywhere.

    ⭐ The distinction is the REPLACEMENT FIELD, not the literal: `ast` gives a
    `FormattedValue` its own span, and only a field whose braces contain a
    newline is the 3.12-only construct. Measured on this file: 814 spanning
    literals, ZERO spanning fields, and the broken line yields exactly one."""
    from pathlib import Path as _Path
    offenders = _multiline_replacement_fields(
        _Path(research.__file__).read_text(encoding="utf-8"))
    assert not offenders, (
        f"f-string replacement field(s) spanning lines at {offenders} — 3.12+ "
        f"syntax, and this package declares >=3.11, so importing research.py on "
        f"the declared floor raises SyntaxError")


def test_and_that_guard_catches_the_construct_without_flagging_the_legal_one():
    """⛔ BOTH POLARITIES, because this guard has already been wrong both ways."""
    broken = (
        'def f(_c, _DIM):\n'
        '    print(f"  {_c(_DIM, \'Type numbers like  1,3\'\n'
        '                 \' more\')}")\n'
    )
    assert _multiline_replacement_fields(broken) == [2], "it missed the break"

    # Implicit concatenation across lines — legal on every version, and the shape
    # 814 f-strings in research.py already use.
    legal = 'x = (f"a {1} "\n     f"b {2}")\n'
    assert _multiline_replacement_fields(legal) == [], "it flagged a legal one"


def _multiline_replacement_fields(source: str) -> "list[int]":
    """Lines where an f-string's `{...}` itself contains a newline."""
    import ast
    return sorted(
        n.lineno for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FormattedValue) and n.lineno != n.end_lineno)


# ══ 5. the wiring ══════════════════════════════════════════════════════
def test_the_flag_is_wired_all_the_way_from_argparse():
    from conftest import code_only
    src = code_only(research.main)
    assert 'parser.add_argument("--select"' in src
    assert "select=bool(args.send_logs_select)" in src


def test_the_choice_is_made_BEFORE_the_disclosure_is_printed():
    """⛔ The consent screen names a count, and until the person has chosen there
    is no count to name — printing "at most 30" and then asking for two would
    describe a bundle nobody is about to build."""
    from conftest import code_only
    src = code_only(research.cmd_send_logs)
    choose = src.index("_choose_runs_interactively(")
    disclose = src.index("_send_logs_consent_lines(")
    assert choose < disclose


def test_the_TERMINAL_always_sends_the_machine_material(monkeypatch):
    """⛔⛔ FOUND BY MUTATION — nothing asserted this, so the terminal could have
    silently stopped carrying it.

    The web app made this material opt-in (owner's call, 2026-08-25) and the
    terminal deliberately did NOT follow: the person running this command is
    physically at the machine, and the founding incident was a pairing failure
    that produced NO RUN AT ALL — so the sessions and the raw tails are the whole
    evidence there. A `--send-logs` that dropped them would send an archive with
    nothing in it in the one case this feature exists for."""
    seen = {}

    def _build(dest, **k):
        seen.update(k)
        raise RuntimeError("stop after the builder call")

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    research.cmd_send_logs(assume_yes=True)
    # Absent means the builder's own default, which is True. An explicit False
    # is the regression; either shape of "not False" is correct.
    assert seen.get("include_machine", True) is True


def test_and_it_still_does_when_the_person_CHOSE_no_runs(monkeypatch):
    """⭐ THE PAIRING-FAILURE CASE THROUGH THE CHOOSER. Pressing Enter at the
    prompt means "no runs" — and at a terminal that must still send the machine's
    own logs, because otherwise the one command available to somebody whose
    pairing never completed produces an empty archive."""
    seen = {}

    def _build(dest, **k):
        seen.update(k)
        raise RuntimeError("stop after the builder call")

    monkeypatch.setattr(research, "_scan_run_folders", lambda: _rows(2))
    monkeypatch.setattr(research, "_build_log_bundle", _build)
    monkeypatch.setattr("builtins.input", lambda _p: "")
    research.cmd_send_logs(assume_yes=True, select=True)
    assert seen["only_runs"] == []
    assert seen.get("include_machine", True) is True


def test_the_selection_reaches_the_builder():
    """⛔⛔ THE ACCEPTED-AND-IGNORED TRAP. `_build_log_bundle` takes the selection
    as a keyword, and every test stub for it is `lambda dest, **k` — so a caller
    that forgets it is invisible to all of them and silently collects the newest
    thirty."""
    from conftest import code_only
    src = code_only(research.cmd_send_logs)
    assert "only_runs=only_runs" in src


def test_quitting_the_prompt_sends_NOTHING(monkeypatch, tmp_path):
    """⛔ A person who Ctrl-Cs the chooser must not end up with a bundle built
    from a default they never picked."""
    built = []
    monkeypatch.setattr(research, "_scan_run_folders", lambda: _rows(2))
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda *a, **k: built.append(k) or {})

    def _boom(_p):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _boom)
    assert research.cmd_send_logs(assume_yes=True, select=True) == 130
    assert built == [], "it built a bundle after the person quit"


def test_the_PRINTED_consent_screen_describes_the_selection_exactly(
        monkeypatch, capsys):
    """⛔⛔ FOUND BY MUTATION. Every assertion about this copy called the helper
    DIRECTLY, so a mutant that dropped `chosen_exactly=` from the command's own
    call survived untouched: the helper stayed correct and the screen the person
    actually reads described a ceiling — "at most 2" for a request they made
    precisely, re-introducing the ambiguity the list exists to remove.

    ⭐ Drives the real command and reads its real stdout. A helper being right is
    not the same fact as the screen being right."""
    monkeypatch.setattr(research, "_scan_run_folders", lambda: _rows(3))
    monkeypatch.setattr("builtins.input", lambda _p: "1,2")

    def _build(dest, **k):
        raise RuntimeError("stop after the disclosure")

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    research.cmd_send_logs(assume_yes=True, select=True)
    out = capsys.readouterr().out
    assert "the 2 runs you chose, and only those" in out
    assert "at most" not in out
    assert "whichever runs you pick" in out


def test_and_WITHOUT_the_flag_the_printed_screen_is_the_old_one(
        monkeypatch, capsys):
    """⛔ THE ACCEPT-POLARITY HALF. A command that always printed the selection
    copy would describe a choice nobody made — and every existing caller of this
    command goes through the same lines."""
    def _build(dest, **k):
        raise RuntimeError("stop after the disclosure")

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    research.cmd_send_logs(assume_yes=True, runs=4)
    out = capsys.readouterr().out
    assert "at most 4 runs from this machine" in out
    assert "you chose" not in out


def test_a_selection_survives_the_confirm_prompt(monkeypatch, tmp_path):
    """The chosen names must reach the builder, not be re-derived from a count."""
    seen = {}
    monkeypatch.setattr(research, "_scan_run_folders", lambda: _rows(3))

    def _build(dest, **k):
        seen.update(k)
        raise RuntimeError("stop here — the selection is what this pins")

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    monkeypatch.setattr("builtins.input", lambda _p: "2")
    assert research.cmd_send_logs(assume_yes=True, select=True) == 1
    assert seen["only_runs"] == ["chat_1_1_20260821T000000"]
