"""One yes/no reader for the whole CLI — and it never decides in silence.

⛔ THE LIVE BUG. A new owner pairing their machine on 2026-08-17 answered

    >  Add another browser profile (profile 2)? [y/N]: 2

with `2` — the number the question had just used — and the loop exited
printing nothing at all. They wanted two concurrent run slots, got one, and
`[5/5] Ready` then reported success. Nothing in the whole session named the
capacity they actually ended up with.

⭐⭐ THE PARSING IS THE TRIGGER; THE SILENCE IS THE DEFECT. Before this wave
every prompt in research.py parsed its own answer, and no two did it the same
way — `in ("y","yes")`, `in ("","y","yes")`, `"verify" if ans in ("n","no")
else "skip"`. Five rule sets over nine prompts, so one word meant different
things at different prompts ("nope" was a no at one and a yes at another), and
an answer none of them recognised was applied as the default without a word.

So the fix is one reader with one rule set that (a) says when it cannot read
an answer and asks again instead of quietly defaulting, (b) echoes any answer
it had to interpret, and (c) renders the [y/N] hint FROM the default so the
promise and the parse cannot drift apart.
"""
import inspect
import re

import pytest

import research


# ── helpers ──────────────────────────────────────────────────────────────────

def _answers(monkeypatch, *replies):
    """Feed `replies` to the reader's `input()`, capturing the prompts it shows."""
    seen = {"prompts": [], "left": list(replies)}

    def fake_input(prompt=""):
        seen["prompts"].append(prompt)
        if not seen["left"]:
            raise EOFError("no more input")
        return seen["left"].pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return seen


def _ask(monkeypatch, *replies, **kw):
    seen = _answers(monkeypatch, *replies)
    kw.setdefault("default", False)
    return research._ask_yes_no_sync("Do the thing?", **kw), seen


# ── the rule set ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("default", [True, False])
def test_a_bare_enter_means_whatever_the_hint_promised(monkeypatch, default):
    got, _ = _ask(monkeypatch, "", default=default)
    assert got is default


@pytest.mark.parametrize("word", ["y", "Y", "yes", "YES", " Yes ", "ye"])
def test_the_plain_yes_words(monkeypatch, word):
    got, _ = _ask(monkeypatch, word, default=False)
    assert got is True


@pytest.mark.parametrize("word", ["n", "N", "no", "NO", " No "])
def test_the_plain_no_words(monkeypatch, word):
    got, _ = _ask(monkeypatch, word, default=True)
    assert got is False


@pytest.mark.parametrize("word", ["yeah", "yep", "yup", "ok", "okay", "sure"])
def test_the_conversational_yes_words_are_a_yes(monkeypatch, word):
    got, _ = _ask(monkeypatch, word, default=False)
    assert got is True


@pytest.mark.parametrize("word", ["nope", "nah", "naw"])
def test_the_conversational_no_words_are_a_no(monkeypatch, word):
    """⛔ 'nope' used to mean SKIP at the verification prompt — the one place a
    typo could silently defeat the answer the user was giving."""
    got, _ = _ask(monkeypatch, word, default=True)
    assert got is False


# ── the bug the new owner hit ────────────────────────────────────────────────

def test_the_number_the_question_just_used_is_a_yes(monkeypatch, capsys):
    got, _ = _ask(monkeypatch, "2", default=False, yes_aliases=("2",))
    assert got is True
    assert "'2' as yes" in capsys.readouterr().out


def test_the_count_already_held_is_a_no(monkeypatch, capsys):
    got, _ = _ask(monkeypatch, "1", default=False,
                  yes_aliases=("2",), no_aliases=("1",))
    assert got is False
    assert "'1' as no" in capsys.readouterr().out


def test_a_digit_is_not_globally_a_yes(monkeypatch, capsys):
    """⛔ OVER-CORRECTION GUARD. `2` means yes only where the question named it.
    At "Remove the Super Research backend?" a bare digit means nothing, and
    guessing would be worse than asking again."""
    got, seen = _ask(monkeypatch, "2", "n", default=False)
    assert got is False
    assert len(seen["prompts"]) == 2, "an unreadable digit must be re-asked, not assumed"
    assert "Did not understand '2'" in capsys.readouterr().out


def test_an_alias_declared_both_ways_reads_as_yes_and_says_so(monkeypatch, capsys):
    got, _ = _ask(monkeypatch, "2", default=False,
                  yes_aliases=("2",), no_aliases=("2",))
    assert got is True
    assert "'2' as yes" in capsys.readouterr().out


# ── never decide in silence ──────────────────────────────────────────────────

def test_an_unreadable_answer_is_named_and_re_asked(monkeypatch, capsys):
    got, seen = _ask(monkeypatch, "maybe", "y", default=False)
    assert got is True
    assert len(seen["prompts"]) == 2
    out = capsys.readouterr().out
    assert "Did not understand 'maybe'" in out
    assert "Enter alone means no" in out, "the re-ask must restate what Enter does"


def test_the_re_ask_restates_the_other_default_too(monkeypatch, capsys):
    _ask(monkeypatch, "maybe", "y", default=True)
    assert "Enter alone means yes" in capsys.readouterr().out


def test_it_gives_up_out_loud_rather_than_defaulting_quietly(monkeypatch, capsys):
    got, seen = _ask(monkeypatch, "a", "b", "c", default=True, tries=3)
    assert got is True
    assert len(seen["prompts"]) == 3
    out = capsys.readouterr().out
    assert "Still no answer I can read" in out
    assert "taking the default" in out
    assert "yes" in out


def test_giving_up_names_the_default_it_actually_took(monkeypatch, capsys):
    got, _ = _ask(monkeypatch, "a", "b", "c", default=False, tries=3)
    assert got is False
    assert re.search(r"taking the default:\s*no", capsys.readouterr().out)


def test_tries_is_honoured(monkeypatch):
    _, seen = _ask(monkeypatch, "a", "b", "c", default=False, tries=1)
    assert len(seen["prompts"]) == 1


def test_a_canonical_answer_is_not_echoed_back(monkeypatch, capsys):
    """The echo exists for answers we had to INTERPRET. Narrating 'y' back
    would be noise on every prompt in the product."""
    _ask(monkeypatch, "yes", default=False)
    assert "as yes" not in capsys.readouterr().out


# ── the hint cannot disagree with the parse ──────────────────────────────────

def test_the_hint_is_rendered_from_the_default(monkeypatch):
    _, yes_seen = _ask(monkeypatch, "", default=True)
    _, no_seen = _ask(monkeypatch, "", default=False)
    assert "[Y/n]" in yes_seen["prompts"][0]
    assert "[y/N]" in no_seen["prompts"][0]
    assert "[y/N]" not in yes_seen["prompts"][0]
    assert "[Y/n]" not in no_seen["prompts"][0]


def test_the_question_reaches_the_prompt(monkeypatch):
    _, seen = _ask(monkeypatch, "", default=False)
    assert "Do the thing?" in seen["prompts"][0]


# ── cancellation belongs to the caller, not the reader ───────────────────────

def test_eof_propagates(monkeypatch):
    _answers(monkeypatch)  # no replies at all
    with pytest.raises(EOFError):
        research._ask_yes_no_sync("Do the thing?", default=False)


def test_eof_propagates_from_a_retry_too(monkeypatch):
    """A pipe that yields one unreadable line then ends must not spin."""
    _answers(monkeypatch, "wat")
    with pytest.raises(EOFError):
        research._ask_yes_no_sync("Do the thing?", default=False)


def test_keyboard_interrupt_propagates(monkeypatch):
    def boom(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", boom)
    with pytest.raises(KeyboardInterrupt):
        research._ask_yes_no_sync("Do the thing?", default=False)


def test_the_async_wrapper_gives_the_same_answer(monkeypatch):
    import asyncio
    _answers(monkeypatch, "yep")
    got = asyncio.run(research._ask_yes_no("Do the thing?", default=False))
    assert got is True


# ── the class-level guard ────────────────────────────────────────────────────

def test_no_prompt_parses_its_own_answer_any_more():
    """⭐ THE POINT OF THE WAVE. Nine prompts, five hand-rolled rule sets. If a
    new one appears, this fails — a second rule set is how the class comes back."""
    src = inspect.getsource(research)
    for hand_rolled in ('not in ("y", "yes")', 'in ("y", "yes")',
                        'in ("", "y", "yes")', 'in ("n", "no")'):
        assert hand_rolled not in src, (
            f"{hand_rolled!r} is a second yes/no rule set — route it through "
            f"_ask_yes_no instead"
        )


def test_every_yn_hint_in_the_file_is_rendered_by_the_reader():
    """A `[y/N]` written by hand beside a prompt is a hint that can drift from
    the parse. The reader owns the only two."""
    src = inspect.getsource(research)
    hints = [m for m in re.findall(r"\[[yY]/[nN]\]", src)]
    reader = inspect.getsource(research._ask_yes_no_sync)
    assert hints, "sanity: the file should still contain hints"
    outside = src.replace(reader, "")
    # Docstrings and comments quote the prompts; code must not build them.
    for line in outside.splitlines():
        if re.search(r"\[[yY]/[nN]\]", line) and "_c(_DIM," in line:
            pytest.fail(f"hand-built y/N hint still in code: {line.strip()}")


def test_every_call_site_states_its_default_explicitly():
    """`default` decides both the parse AND the printed hint, so a call site
    that leaves it implicit is a prompt whose promise nobody chose."""
    src = inspect.getsource(research)
    sites = [m.start() for m in re.finditer(r"_ask_yes_no(?:_sync)?\(", src)]
    # Minus the two definitions and the async wrapper's own delegation.
    calls = [p for p in sites
             if not src[max(0, p - 10):p].rstrip().endswith("def")
             and "_ask_yes_no_sync, question" not in src[p:p + 60]]
    # 9 since 2026-08-18: `--send-logs` asks before anything leaves the machine.
    # 10 since 2026-09-04 (7.7B): pair Stage 2 also asks whether other people
    # may FIND this computer — the second question in that stage, and the one
    # whose default being False is what keeps an unattended pair private.
    # The count is deliberate rather than a lower bound — a new prompt should
    # have to come past this test and state its default on purpose.
    assert len(calls) == 10, f"expected 10 wired prompts, saw {len(calls)}"
    for p in calls:
        window = src[p:p + 400]
        assert "default=" in window.split(")\n")[0] or "default=" in window[:300], (
            f"call site with no explicit default: {window[:120]!r}"
        )


# ── the two add-loops ────────────────────────────────────────────────────────

@pytest.mark.parametrize("counter", ["next_n", "next_profile_n"])
def test_the_add_loops_bind_the_alias_to_the_number_the_prompt_names(counter):
    """⭐ The affordance is only correct because it is the SAME variable the
    question interpolates. A literal "2" would be right once and wrong after."""
    src = _source_containing("Add another browser profile", counter)
    assert f"yes_aliases=(str({counter}),)" in src
    assert f"no_aliases=(str({counter} - 1),)" in src


def _source_containing(needle, counter):
    src = inspect.getsource(research)
    blocks = [b for b in src.split("\n\n") if needle in b and counter in b]
    assert blocks, f"no block with {needle!r} and {counter!r}"
    return "\n\n".join(blocks)


@pytest.mark.parametrize("counter", ["next_n", "next_profile_n"])
def test_declining_the_add_loop_says_what_capacity_it_settled_on(counter):
    """⛔ THE ACTUAL DEFECT. Both loops used to leave on a bare `break`."""
    src = _source_containing("Add another browser profile", counter)
    assert f"_say_profile_capacity({counter} - 1)" in src, (
        "declining must announce the capacity, not exit silently"
    )
    body = src[src.index("if not _add_more:"):]
    assert body.index("_say_profile_capacity") < body.index("break"), (
        "the announcement has to happen BEFORE the break, or it never happens"
    )


def test_the_capacity_line_names_slots_and_how_to_add_more(capsys):
    research._say_profile_capacity(2)
    out = capsys.readouterr().out
    assert "2 browser profiles" in out
    assert "2 concurrent run slots" in out
    assert "--login" in out, "a capacity the user did not want needs a way out"


def test_the_capacity_line_is_singular_for_one(capsys):
    research._say_profile_capacity(1)
    out = capsys.readouterr().out
    assert "1 browser profile " in out
    assert "1 concurrent run slot." in out
    assert "profiles" not in out and "slots" not in out


@pytest.mark.parametrize("bad", [0, None])
def test_the_capacity_line_never_claims_zero(capsys, bad):
    """A paired machine always has profile 1. Zero would be a lie, and it is
    the value a caller reaches for when a counter has not been set."""
    research._say_profile_capacity(bad)
    assert "1 browser profile" in capsys.readouterr().out


# ── [5/5] Ready ──────────────────────────────────────────────────────────────

def test_ready_reports_the_capacity_it_is_calling_ready():
    """The new owner's Ready screen listed platforms and never once said how
    many concurrent slots they had ended up with."""
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    ready = src[src.index("_setup_step(5, 5"):]
    assert "load_worker_count()" in ready, (
        "read the persisted count — the add-loop's counter does not exist when "
        "profile 1 failed, and Ready still runs"
    )
    assert "concurrent run" in ready
    assert ready.index("_ready_cap") < ready.index("Browser closed")


# ── the individual prompts keep the defaults they had ────────────────────────

@pytest.mark.parametrize("question,default", [
    ("Save this key anyway", "default=False"),
    ("Skip the verification step?", "default=True"),
    ("Enable On Startup?", "default=True"),
    # ⛔⛔ FALSE, AND IT HAS TO STAY FALSE. It is the private answer, so an
    # unattended pair publishes nothing — and it is what makes the two
    # non-interactive paths AGREE: `_ask_yes_no` returns the DEFAULT after three
    # unreadable answers while the EOFError branch forces False. On the line
    # above, whose default is True, those two disagree.
    ("Let other people find this computer and ask to use it?", "default=False"),
    ("Continue anyway?", "default=False"),
    ("Remove the Super Research backend?", "default=False"),
])
def test_each_prompt_kept_its_original_default(question, default):
    src = inspect.getsource(research)
    m = re.search(re.escape(question) + r'"[^)]{0,120}', src)
    assert m, f"{question!r} not found at a call site"
    assert default in m.group(0), f"{question!r} should be {default}"


def test_open_chrome_keeps_its_two_different_defaults():
    """One prompt, two questions: signed in → default NO (leave the session
    alone), signed out → default YES (open the browser)."""
    src = inspect.getsource(research._login_one_profile)
    assert "default_open = False" in src and "default_open = True" in src
    assert "_ask_yes_no(question, default=default_open)" in src
