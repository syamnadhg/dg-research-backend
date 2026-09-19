"""The bulk gate, rebuilt. 7.9-5b.

⛔⛔ WHY THIS FILE EXISTS AND THE LAST ONE DID NOT DO ITS JOB. `test_bulk_gate_795.py`
scored 52/52 while the gate it guarded had made 96 real machine names unusable
across six verbs. Its name-safety cases were all SINGLE TOKENS glued to a
quantifier — `alldesk`, `allan's pc`, `all-in-one`, `everest` — and the defect
needed TWO tokens: `<quantifier> <word> <machine-noun>` full-matched a wildcard
filler. No two-token control existed, so nothing could see it.

⭐⭐ SO THE NAME CORPUS HERE IS GENERATED, TWO- AND THREE-TOKEN, and it runs
against the live resolver rather than against the predicate alone. It already
earned that: it caught me reintroducing this wave's own defect — I wrote
`_QUANTIFIERS` as a bare alternation, interpolated it into a larger one, `all`
became a top-level alternative, and all 384 names classified as sets.

⭐⭐ AND THE BEHAVIOURAL A/B IS A TEST, NOT A ONE-OFF. Every phrase SKILL.md and
the routing tests already feed this resolver is replayed here, because that is the
method that measured the regression in the first place and it costs milliseconds.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "facade"
_SR_PATH = _ROOT / "skill" / "scripts" / "sr.py"
_SKILL = _ROOT / "skill" / "SKILL.md"


def _load():
    spec = importlib.util.spec_from_file_location("sr_bulk_0910", _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load()


def _said(text: str) -> tuple[list[str] | None, str]:
    """(argv, joined relay lines) — what the product DOES with a message."""
    argv, lines = sr._nl_resolve(text)
    return argv, " ".join(lines or [])


# ⭐ THE REFUSAL THIS WAVE ADDS, RECOGNISED BY ITS CLAIM AND NOT BY ITS WORDING.
# 7.9-4's lesson: answering a bulk request with "which one?" hides that the thing
# asked for cannot be done at all. So the mark of this refusal is that it says
# ONE AT A TIME.
# ⛔ THE NOUN LIST HERE IS THE FOUR SURFACES' OWN WORDS. It was missing `owner`,
# which is the ask surface's — so the six ask cases failed on the recogniser, not
# on the gate. A recogniser short by one word is how a guard passes on a phrase
# it never actually read.
_ONE_AT_A_TIME = re.compile(r"\bone (?:computer|run|person|owner) at a time\b", re.I)

# ⛔⛔ DERIVED FROM THE PRODUCT'S OWN CONFIRM TABLE, NOT HAND-LISTED. I wrote the
# prefixes out by hand first and left off the ASK surface's — "Ask the owner of
# {name} to let you use it?" — so the guard was blind on exactly the surface
# whose mutant had already survived once. That is the second hand-written list
# in this file to go short by one entry, so this one is generated: every confirm
# that interpolates a NAME is a confident single-target answer, and no set may
# reach one.
_CONFIRM_PREFIXES = tuple(
    v.split("{name}")[0].strip() for v in sr._NL_CONFIRMS.values()
    if "{name}" in v and v.split("{name}")[0].strip())


def test_the_confirm_prefixes_are_derived_and_cover_every_named_confirm():
    """⛔ A DERIVED LIST THAT SILENTLY DERIVES NOTHING IS THE SAME BLINDNESS."""
    assert len(_CONFIRM_PREFIXES) >= 5, _CONFIRM_PREFIXES
    named = [k for k, v in sr._NL_CONFIRMS.items() if "{name}" in v]
    assert len(_CONFIRM_PREFIXES) == len(named), (named, _CONFIRM_PREFIXES)
    assert any("Ask the owner of" in p for p in _CONFIRM_PREFIXES)


def _refuses_as_a_set(text: str) -> bool:
    argv, lines = _said(text)
    return argv is None and bool(_ONE_AT_A_TIME.search(lines))


# ─────────────────────────────────────────────────────────────────────────────
# 1. THE NAME CORPUS — GENERATED, TWO- AND THREE-TOKEN, EIGHT VERBS.
# ─────────────────────────────────────────────────────────────────────────────
# ⛔⛔ THIS IS THE GUARD `test_bulk_gate_795.py` DID NOT HAVE. Its name-safety
# cases were single tokens glued to a quantifier (`alldesk`, `allan's pc`,
# `all-in-one`, `everest`), and the defect needed TWO — so 96 real phrases went
# green through 52/52 while six verbs could not touch a machine called "All Hands
# Mac". These are generated from the SHAPE that broke, not hand-picked, so a
# future filler cannot be written around them.
_QUANTIFIER_WORDS = ("All", "Every", "Each", "Both")
_MIDDLES = ("Hands", "Day", "Lab", "Hands On")     # two- and three-token names
_TAILS = ("Mac", "PC", "Laptop")

_GENERATED_NAMES = tuple(
    f"{q} {m} {t}" for q, m, t in
    itertools.product(_QUANTIFIER_WORDS, _MIDDLES, _TAILS))

# The eight surfaces a name has to survive, phrased the way people phrase them.
_VERB_TEMPLATES = (
    "remove my {n}", "unlink {n}", "make {n} public", "hide {n}",
    "ask for {n}", "approve {n}", "deny {n}", "switch to {n}",
)


def test_the_corpus_is_generated_and_covers_both_token_counts():
    """⛔ A CORPUS THAT IS SECRETLY ONE SHAPE PROVES ONE SHAPE."""
    assert len(_GENERATED_NAMES) == 48
    by_tokens: dict[int, int] = {}
    for n in _GENERATED_NAMES:
        by_tokens[len(n.split())] = by_tokens.get(len(n.split()), 0) + 1
    assert sorted(by_tokens) == [3, 4], by_tokens
    assert by_tokens[3] >= 12 and by_tokens[4] >= 12, by_tokens
    assert len(_GENERATED_NAMES) * len(_VERB_TEMPLATES) == 384


@pytest.mark.parametrize("name", _GENERATED_NAMES)
@pytest.mark.parametrize("template", _VERB_TEMPLATES)
def test_a_real_machine_name_is_never_read_as_a_set(template, name):
    """⛔⛔ THE 96-PHRASE REGRESSION, GENERALISED TO 384."""
    said = template.format(n=name)
    assert not _refuses_as_a_set(said), said


@pytest.mark.parametrize("name", _GENERATED_NAMES)
def test_the_predicate_itself_clears_every_generated_name(name):
    assert not sr._names_a_set(name), name


def test_the_quantifier_alone_does_not_make_a_set():
    """⭐ THE SIGNAL IS A PLURAL NOUN, NOT A QUANTIFIER — stated as a test.

    ⛔ Pairwise, not a loop over one direction: the quantifier is held constant
    and only the NOUN's number changes, so a predicate that keyed on the
    quantifier fails here and a predicate that keyed on the noun passes.
    """
    assert sr._names_a_set("all my computers")
    assert not sr._names_a_set("All Hands Mac")
    assert sr._names_a_set("every computer of mine")
    assert not sr._names_a_set("Every Hands On PC")


# ─────────────────────────────────────────────────────────────────────────────
# 2. EVERY MEASURED SET PHRASE, ON THE SURFACE THAT ACTS.
# ─────────────────────────────────────────────────────────────────────────────
# ⛔⛔ THESE ARE THE MEASURED FINDINGS, NOT MY REPAIR LIST. Each was reproduced
# against this resolver before a line was changed, and the comment on each says
# what it DID, because "it refuses now" is not the claim worth pinning — "it used
# to run the unconfirmed hide" is.
_SETS_THAT_MUST_REFUSE = (
    # ⛔ RAN the unconfirmed hide, with no name, so the picker hid whichever
    #    machine it landed on.
    "hide my machines", "hide my computers", "hide any of my machines",
    "hide the 4 machines",
    # ⛔ reached the publish confirm quoting a name that cannot exist.
    "make my computers public", "make my 3 pcs public",
    "make all my computers public",
    # ⛔ reached the BROWSE list of STRANGERS' machines.
    "make all the computers public",
    # ⛔ reached the catch-all, which denies having the verb.
    "hide every computer",
    # ⛔ reached the DESTRUCTIVE unlink confirm.
    "remove my two macs", "remove my 2 computers", "remove any of my computers",
    "remove my machines", "unlink my devices", "remove all my devices",
    # ⛔⛔ THE CONSENT SURFACE. These capture NOTHING, `_resolve_asker("")` returns
    #    the sole waiting row, and one stranger is let in — or one person refused
    #    for seven days — while the person believes they answered the queue.
    "approve them all", "approve everyone waiting", "approve all pending requests",
    "approve the queue", "approve the rest", "let them all in",
    "deny them all", "deny everyone waiting", "deny all pending requests",
    "deny the queue", "deny the rest", "refuse everyone",
    # ⛔ stop had no message-level check at all.
    "stop all of my research", "stop all my research on tesla",
    "stop all three runs", "stop all my runs",
    # ⛔ and the three that were graded minor for ending in "No run matching".
    "pause all my runs", "resume all my runs", "retry all my runs",
    # ⛔⛔ THE ASK SURFACE HAD NO CASE AT ALL, and its mutant SURVIVED on that.
    # One ask names one owner; a set would file a disclosure against every owner
    # in it while the confirm can only name one.
    "ask for all my computers", "ask for all the public computers",
    "ask to use all my computers", "request access to all their computers",
    "borrow all their machines", "ask for every public computer",
)


@pytest.mark.parametrize("said", _SETS_THAT_MUST_REFUSE)
def test_a_set_is_refused_and_told_it_cannot_be_done(said):
    argv, lines = _said(said)
    assert argv is None, f"{said} still EXECUTES: {argv}"
    # ⛔ 7.9-4's LESSON: answering a bulk request with "which one?" hides that the
    # thing asked for cannot be done at all. The refusal has to make the claim.
    assert _ONE_AT_A_TIME.search(lines), f"{said} -> {lines}"


@pytest.mark.parametrize("said", _SETS_THAT_MUST_REFUSE)
def test_no_set_phrase_reaches_a_confirm_that_names_one_thing(said):
    """⛔⛔ THE REAL COST WAS A CONFIDENT SINGLE-TARGET ANSWER, not a bad question.

    `Stop “all three runs”?`, `Unlink “two macs”?` and `Say yes to “them all”?`
    each quoted a set back as though it were one thing, and a "yes" then acted on
    whatever the resolver landed on.
    """
    _argv, lines = _said(said)
    for prefix in _CONFIRM_PREFIXES:
        assert prefix not in lines, f"{said} -> {lines}"


def test_the_consent_surface_is_the_one_the_signed_signal_could_not_see():
    """⭐⭐ MEASURED: the plural-machine-noun signal caught 27 of 44 phrases, and
    every one of the 17 misses needed a signal it does not have. The queue is the
    biggest group — there is no machine noun in it at all.
    """
    queue = ["approve them all", "approve the queue", "let them all in",
             "refuse everyone", "deny the rest"]
    for said in queue:
        assert not sr._SET_SIGNAL_PLURAL.search(said), said
        assert sr._names_a_set(said), said


# ─────────────────────────────────────────────────────────────────────────────
# 3. THE STRUCTURAL GUARDS — each pins a mistake that was actually made.
# ─────────────────────────────────────────────────────────────────────────────
_NEW_ALTERNATIONS = ("_MACHINE_PLURAL", "_MACHINE_SINGULAR", "_RUN_PLURAL",
                     "_RUN_MASS", "_QUANTIFIERS", "_VIS_SETTERS")


@pytest.mark.parametrize("const_name", _NEW_ALTERNATIONS)
def test_an_alternation_constant_cannot_leak_its_alternatives(const_name):
    """⛔⛔ THE BUG I WROTE WHILE WRITING THE FIX FOR THE SAME BUG.

    `_QUANTIFIERS` started as a bare `all|every|each|both|any`. Interpolated into
    a larger alternation, a trailing `\\s+…` bound only to the LAST alternative,
    so `all`, `every`, `each` and `both` became TOP-LEVEL alternatives — the bare
    word "All" in "All Hands Mac" matched and all 384 generated names classified
    as sets. It survived my reading of the code and died on the corpus.

    ⭐ THE PROPERTY, STATED SO IT IS FALSIFIABLE: appending a suffix must bind to
    the WHOLE constant. With a bare alternation the suffix binds to one branch and
    the constant matches on its own; with a grouped one it cannot.
    """
    const = getattr(sr, const_name)
    first = re.fullmatch(r"\(\?:([^|)]+)[|)].*", const, re.S)
    assert first, f"{const_name} is not a non-capturing group: {const[:40]}"
    word = first.group(1)
    assert re.search(const + r"\s+zzz", f"{word} zzz", re.I), const_name
    # The suffix must make the whole thing unmatchable without it.
    assert not re.search(const + r"\s+zzz", word, re.I), (
        f"{const_name} leaks alternatives when a suffix is appended")


@pytest.mark.parametrize("signal_name", ("_SET_SIGNAL_PLURAL",
                                         "_SET_SIGNAL_QUANTIFIED",
                                         "_SET_SIGNAL_COLLECTIVE"))
def test_no_signal_carries_a_wildcard_filler(signal_name):
    """⛔⛔ THE 7.9-5 DEFECT IN ONE PROPERTY. Its `_BULK_MACHINES` carried a
    filler that full-matched any `<quantifier> <word> <machine-noun>` name. A
    word-class or dot filler is what makes a pattern able to swallow a name, and
    none of these three needs one — the determiner slot does that work with a
    closed list. `\\d` is allowed and load-bearing: "my 3 pcs".
    """
    # ⛔⛔ MY FIRST VERSION BLOCKED FOUR SPELLINGS and cross-verify walked a fifth
    # straight past it: `\S+\s+` in the determiner slot restores the whole
    # 96-phrase defect and contains none of the four. A blocklist of spellings is
    # not a property. What a filler IS, structurally, is a character CLASS under
    # a REPETITION — so that is what is forbidden, whatever it is spelled.
    pattern = getattr(sr, signal_name).pattern
    filler = re.findall(r"(?:\\[wWsSdD]|\[\^?[^\]]*\]|(?<!\\)\.)\s*[+*]", pattern)
    # ⭐ TWO REPETITIONS ARE LEGITIMATE AND NEITHER CAN SWALLOW A NAME:
    #   · `\s+` is the space BETWEEN words — it cannot cross one.
    #   · `\d+` is a count, which the slot needs for "my 3 pcs".
    # Everything else — a word class, a dot, a negated class — can eat a name,
    # and eating a name is the 96-phrase defect.
    filler = [f for f in filler if not f.startswith(("\\d", "\\s"))]
    assert filler == [], f"{signal_name} carries wildcard filler: {filler}"


def test_the_determiner_slot_is_a_closed_list_and_binds_the_noun():
    """⭐ WHY "All Hands Mac" SURVIVES, as a property rather than an example."""
    assert "\\w" not in sr._SET_DETERMINER
    # A word that is not in the list cannot stand between the quantifier and the
    # noun — which is exactly what a name does.
    assert sr._SET_SIGNAL_QUANTIFIED.search("all my computer")
    assert not sr._SET_SIGNAL_QUANTIFIED.search("all hands mac")
    assert not sr._SET_SIGNAL_QUANTIFIED.search("every hands on pc")


def test_the_captured_name_is_not_the_override():
    """⛔⛔ MY FIRST VERSION MADE IT ONE, AND IT DEFEATED FOUR REAL SETS.

    A branch that captured a non-set name won over the message. It read well and
    it silently unrefused `approve the queue` ("queue"), `approve the rest`
    ("rest") and `stop all my research on tesla` ("tesla") — on those the capture
    is a FRAGMENT OF the set phrase, not a name beside it. The A/B against the
    pre-build revision is what found it; the predicate was 44/44 either way.

    ⭐ So the answer must not depend on `captured` at all.
    """
    for said in ("approve the queue", "approve the rest",
                 "stop all my research on tesla", "hide my machines"):
        base = sr._request_names_a_set(said)
        for cap in (None, "", "queue", "rest", "tesla", "Studio PC", "machines"):
            assert sr._request_names_a_set(said, cap) is base, (said, cap)
        assert base is True, said


def test_there_is_one_predicate_for_this_question_not_two():
    """⛔⛔ 7.9-5 ADDED A SECOND ANSWER TO A QUESTION 7.9-4 ALREADY ANSWERED, and
    the two disagreed. Duplication also produced an EQUIVALENT MUTANT twice in the
    Gemini wave, which is a harness bug and not a survivor.
    """
    assert not hasattr(sr, "_is_bulk_machine_phrase")
    assert not hasattr(sr, "_asks_about_every_machine")
    assert not hasattr(sr, "_BULK_MACHINES")
    assert not hasattr(sr, "_BULK_RUNS")
    assert not hasattr(sr, "_BARE_QUANTIFIER")
    # And the fold kept the 7.9-4 unlink behaviour it replaced.
    for phrase in ("all my devices", "every computer", "each machine",
                   "both laptops", "all the pcs", "all of my macs",
                   "every phone", "all my phones", "all devices"):
        assert sr._names_a_set(phrase), phrase
    for name in ("All Hands Mac", "Studio PC", "LABPC001", "mac", "computer",
                 "Air", "Workstation 3"):
        assert not sr._names_a_set(name), name


# ─────────────────────────────────────────────────────────────────────────────
# 4. QUOTING IS THE ESCAPE, AND AN EXCLUSION CLAUSE DOES NOT COUNT.
# ─────────────────────────────────────────────────────────────────────────────
def test_quoting_a_name_exempts_it_outright():
    """⛔⛔ THE RESIDUE THIS DESIGN ACCEPTS AND THE ESCAPE IT OWES.

    A genuinely plural machine NAME is caught — "All Dev Laptops" — and quoting
    is how a person says "this is a name". It also restores three run titles 7.9-5
    ate, one of which the picker's own worked example tells people to type.
    """
    # ⭐ THE RESIDUE IS NARROWER THAN THE DESIGN BUDGETED FOR, and this test used
    # to assert the wider one. After cross-verify forced the plural signal to
    # require a POSSESSED HEAD, "All Dev Laptops" is no longer caught at all —
    # "Dev" is not a determiner. What survives as residue is the shape where a
    # possessive really does sit against a plural head, which is genuinely
    # ambiguous: `remove my Laptops` cannot be told from `remove my laptops`.
    assert not sr._names_a_set("All Dev Laptops")
    assert sr._names_a_set("my Laptops")                 # the residue, stated
    assert not sr._request_names_a_set('remove "my Laptops"')
    for said in ('stop "All Reports"', 'stop "Every Report"',
                 'make "All Hands Mac" public', 'make “All Hands Mac” public',
                 'remove "All Hands Mac"', 'hide "All Hands Mac"'):
        assert not _refuses_as_a_set(said), said


def test_a_quoted_span_is_blanked_and_not_deleted():
    """⛔⛔ MY FIRST VERSION OF THIS TEST WAS DECORATIVE and a mutant proved it.

    It asserted that a space survives and that a message carrying both a name and
    a set is still a set — BOTH of which deletion also satisfies. What actually
    separates the two is that deletion JOINS the characters either side, so it can
    manufacture a word nobody typed; blanking cannot.
    """
    assert sr._outside_quoted_names('hide "x" now') == "hide   now"
    # Deletion would weld these into the plural noun and invent a set.
    # ⛔ THE CONTROL CARRIES A POSSESSIVE, because a bare plural is no longer a
    # set on its own — cross-verify made the signal require a possessed head.
    assert not sr._names_a_set('my comput"x"ers')
    assert sr._names_a_set("my computers")


def test_an_apostrophe_is_not_a_quote_delimiter():
    """⛔⛔ A BLOCKER OF MINE, FOUND BY A MUTATION SURVIVOR.

    `_NL_QUOTE_CHARS` contains both apostrophes, so I blanked the span between ANY
    two of the six quote characters — and TWO CONTRACTIONS made a span. `don't
    hide all my computers, it's fine` blanked to "don s fine", the set vanished,
    and the unconfirmed hide RAN: the exact defect this wave closes, reintroduced
    by the line that grants the escape from it. This file had already written the
    warning — `_NL_QUOTED_RE` says apostrophes are not delimiters, for this reason.
    """
    for said in ("don't hide all my computers, it's fine",
                 "i can't approve everyone, it's too many",
                 "don't remove all my devices",
                 "that isn't my machine, don't hide all my computers"):
        assert sr._request_names_a_set(said), said
    # ⭐ And the picker's curly singles are still a pair, because a contraction
    #   cannot forge the OPENING one.
    for said in ("stop ‘All Reports’", 'stop "All Reports"', "stop “All Reports”"):
        assert not sr._request_names_a_set(said), said


def test_only_matched_pairs_delimit_a_name():
    """⛔ THE PROPERTY, so a future widening of the character class cannot undo it."""
    assert "_NL_QUOTE_CHARS" not in sr._SET_QUOTED_SPAN.pattern
    for opener, closer in (('"', '"'), ("“", "”"), ("‘", "’")):
        assert sr._SET_QUOTED_SPAN.search(f"{opener}All Reports{closer}"), opener
    # A right-curly or straight apostrophe cannot OPEN a span.
    for bad in ("’All Reports’", "”All Reports”"):
        assert not sr._SET_QUOTED_SPAN.search(bad), bad


_EXCLUSIONS = (
    "make my Studio PC public, not all my devices",
    "hide the Studio PC and leave all my other machines alone",
    "hide the Studio PC, not all my devices",
    "make my Studio PC public except all my other macs",
)


@pytest.mark.parametrize("said", _EXCLUSIONS)
def test_a_set_named_only_in_an_exclusion_clause_is_not_the_target(said):
    """⛔⛔ TWO MEASURED 7.9-5 DEFECTS: its gate was a `search` over the WHOLE
    message, so naming one target and saying which set to leave out was refused.
    """
    assert not _refuses_as_a_set(said), said


def test_the_exclusion_clause_is_clause_bounded_not_a_wildcard():
    """⛔ AN UNBOUNDED SPAN IS HOW 7.9-5's FILLER ATE REAL NAMES."""
    assert "\\w" not in sr._SET_EXCLUSION
    assert "[^,.;]" in sr._SET_EXCLUSION
    # It stops at the clause boundary, so a set AFTER one still counts.
    assert sr._request_names_a_set("not now. hide all my macs")


def test_an_exclusion_clause_is_not_part_of_a_captured_name():
    """⛔ MEASURED: the whole tail became the machine name and resolved to
    nothing, so the request dropped to the picker.
    """
    argv, _lines = _said("hide the Studio PC and leave all my other machines alone")
    assert argv == ["device-visibility", "private", "Studio PC"], argv


# ─────────────────────────────────────────────────────────────────────────────
# 5. A READING VERB GETS THE LIST. ONLY AN ACTING VERB REFUSES.
# ─────────────────────────────────────────────────────────────────────────────
_READS = ("show my computers", "show my machines", "show my macs",
          "list my devices", "which machines do I have",
          "show me computers I could ask to use", "find public computers",
          "what public computers are there", "are all my computers public?",
          "which of my computers are public?")


@pytest.mark.parametrize("said", _READS)
def test_a_set_on_a_reading_verb_is_served_not_refused(said):
    """⭐⭐ MEASURED, AND IT IS WHY THE GATE SITS INSIDE THE ACT BRANCHES. Every
    one of the 13 set-hits over the product's own phrase corpus is a request to
    LIST. 7.9-5's message-level search could not tell the two apart.
    """
    argv, lines = _said(said)
    assert argv is not None, f"{said} -> {lines}"
    assert not _ONE_AT_A_TIME.search(lines), f"{said} -> {lines}"


_LEAD_INS = ("", "so ", "and ", "hey ", "ok ", "also ", "then ", "just ")


@pytest.mark.parametrize("lead", _LEAD_INS)
def test_a_lead_in_word_does_not_turn_a_question_into_an_offer(lead):
    """⛔⛔ MEASURED: `so are all my computers public?` reached the PUBLISH confirm
    and offered to publish "that computer" — with no name — so a "yes" published
    whichever one the picker landed on. `_asking_state` was anchored at `^`, and
    one conversational word broke it. The research pattern already allowed for
    these words; the state-question test did not.
    """
    argv, lines = _said(lead + "are all my computers public?")
    assert argv == ["devices"], f"{lead!r} -> {argv} / {lines[:90]}"


def test_the_lead_in_list_is_shared_with_the_research_pattern():
    """⛔ TWO COPIES OF A COURTESY LIST IS HOW THIS FILE'S NOUN LISTS DRIFTED."""
    assert sr._NL_LEAD_IN in sr._NL_RESEARCH_RE.pattern
    for word in ("so ", "and ", "hey "):
        assert word in sr._NL_LEAD_IN


# ─────────────────────────────────────────────────────────────────────────────
# 6. THE BEHAVIOURAL A/B, AS A STANDING TEST.
# ─────────────────────────────────────────────────────────────────────────────
# ⭐⭐ WAVES.md ITEM 2 FOR THIS WAVE: "it runs a behavioural A/B against the
# previous revision over every phrase in SKILL.md and in the four routing test
# files — the method that found this, and cheap enough to be standard."
# ⛔ WHAT IT CAN AND CANNOT CLAIM. It cannot diff against a revision that is not
# on disk, so it does not pretend to: it replays every phrase the product's own
# sources feed this resolver and asserts the ONE property the regression
# violated — that nothing the product tells a person to type is answered with a
# set refusal. That is falsifiable, and it is what 52/52 could not see.


def _phrases_from_the_routing_tests() -> list[str]:
    """Literal and f-string arguments to `_nl_resolve` across the routing tests.

    ⛔ THE f-STRING TEMPLATES ARE EXPANDED OVER THE REAL NOUN LIST, not guessed
    at — a template read as a literal would test the string "{noun}".
    """
    out: list[str] = []
    # ⛔ SINGULARISE, AND DO IT WITHOUT `strip`. My first version stripped the
    # characters "(?:)" off both ends of the whole list, which removed the
    # trailing "?" from the LAST alternative only — so "workstations?" became
    # "workstations" and the corpus asked the gate to clear a genuine plural.
    # The A/B caught it on its first run, which is the argument for the A/B.
    nouns = [re.sub(r"s\?$", "", n.strip())
             for n in re.sub(r"^\(\?:|\)$", "", sr._MACHINE_NOUNS).split("|")]
    assert all(not n.endswith("s") for n in nouns), nouns
    # ⛔ encoding="utf-8" on BOTH harvesting reads (here and in
    # `_phrases_from_skill_md`). Without it Python decodes with the LOCALE
    # codec — cp1252 on Windows — and dies on the codebase's own ⛔/⭐ markers:
    # 39 of the 71 files this walks cannot be decoded as cp1252 at all. The
    # product never reads them that way: connect.py opens SKILL.md with
    # encoding="utf-8", and sr.py is loaded through importlib, which decodes
    # source per PEP 263 regardless of locale. Test-side only.
    here = Path(__file__).resolve().parent
    for f in sorted(here.glob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:                                  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_nl_resolve" and node.args):
                continue
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                out.append(a.value)
            elif isinstance(a, ast.JoinedStr):
                parts, ok = [], True
                for v in a.values:
                    if isinstance(v, ast.Constant):
                        parts.append(str(v.value))
                    elif (isinstance(v, ast.FormattedValue)
                          and getattr(v.value, "id", None) in ("noun", "n")):
                        parts.append("\x00")
                    else:
                        ok = False
                if ok and parts.count("\x00") == 1:
                    out += ["".join(parts).replace("\x00", n) for n in nouns]
    return out


def _phrases_from_skill_md() -> list[str]:
    """The example sentences SKILL.md tells people to type."""
    out = []
    for m in re.finditer(r"[“\"]([a-z][^”\"\n]{4,70})[”\"]", _SKILL.read_text(encoding="utf-8")):
        s = m.group(1).strip()
        if re.search(r"\b(research|stop|pause|resume|retry|remove|unlink|forget|"
                     r"delete|add|pair|connect|switch|use|make|set|hide|unlist|"
                     r"publish|share|offer|ask|approve|deny|show|list|send|"
                     r"status|podcast|links|skip)\b", s, re.I):
            out.append(s)
    return out


def test_the_ab_corpus_is_actually_populated():
    """⛔ AN EMPTY CORPUS PASSES EVERY ASSERTION MADE ABOUT IT. This wave's
    predecessor scored 52/52 on a name-safety set that could not see the defect;
    a harvester that silently returns nothing is the same failure with no cases
    at all.
    """
    tests = _phrases_from_the_routing_tests()
    skill = _phrases_from_skill_md()
    assert len(tests) >= 100, len(tests)
    assert len(skill) >= 40, len(skill)
    assert any(" " in p for p in skill)


def test_no_phrase_the_product_itself_teaches_is_refused_as_a_set():
    """⭐⭐ THE ONE PROPERTY THE 96-PHRASE REGRESSION VIOLATED."""
    refused = [p for p in _phrases_from_the_routing_tests() + _phrases_from_skill_md()
               if _refuses_as_a_set(p)]
    assert refused == [], refused


def test_the_reading_requests_in_that_corpus_still_reach_a_command():
    """⛔ AND THEY MUST NOT HAVE GONE QUIET EITHER — a set on a reading verb is a
    list to serve. 13 of the corpus phrases name sets and every one is a `show my
    computers`-shaped request.
    """
    # ⛔⛔ THIS SAID ">= 8" AND THE REAL COUNT IS 12, so a third of the corpus
    # could vanish unseen — cross-verify dropped four machine nouns from the
    # plural list and this assertion still passed. The claim is not "some" but
    # "EVERY machine noun this product accepts", so it is derived from the noun
    # list itself and cannot go short when a word is dropped.
    sets = [p for p in _phrases_from_the_routing_tests() + _phrases_from_skill_md()
            if sr._names_a_set(p) and re.match(r"^(show|list|which|what)\b", p, re.I)]
    nouns = [re.sub(r"s\?$", "", n.strip())
             for n in re.sub(r"^\(\?:|\)$", "", sr._MACHINE_NOUNS).split("|")]
    unseen = [n for n in nouns
              if not any(re.search(rf"\b{n}s\b", p, re.I) for p in sets)]
    assert unseen == [], f"these machine nouns lost their corpus phrase: {unseen}"
    assert len(sets) >= len(nouns), (len(sets), len(nouns))
    for p in sets:
        argv, lines = _said(p)
        assert argv is not None, f"{p} -> {lines}"


def test_the_refusal_recogniser_covers_every_refusal_this_gate_EMITS():
    """⛔⛔ THE RECOGNISER IS USED IN NEGATIVE ASSERTIONS, SO A GAP IN IT PASSES.

    `_ONE_AT_A_TIME` was short by one word — `owner`, the ask surface's — and
    `_refuses_as_a_set` is what all 384 name cases are asserted NOT to do. A name
    refused on the ask surface would have gone green. Five guards in 7.9-4
    measured nothing for the same reason, so the recogniser's completeness is a
    property here rather than a list I keep in my head.

    ⭐ One probe per surface that CAN refuse, each a phrase measured to reach it.
    """
    per_surface = {
        "unlink": "remove my machines",
        "visibility-hide": "hide my machines",
        "visibility-publish": "make my computers public",
        "ask": "ask for all my computers",
        "approve": "approve them all",
        "deny": "deny them all",
        "stop": "stop all my runs",
        "pause": "pause all my runs",
        "resume": "resume all my runs",
        "retry": "retry all my runs",
    }
    unseen = []
    for surface, said in per_surface.items():
        argv, lines = _said(said)
        assert argv is None, f"{surface}: {said} EXECUTES {argv}"
        if not _ONE_AT_A_TIME.search(lines):
            unseen.append((surface, lines))
    assert unseen == [], (
        "the recogniser cannot see these refusals, so every negative assertion "
        f"made with it is blind to them: {unseen}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. THE PLURAL MUST BE A POSSESSED HEAD — cross-verify measured 15 regressions.
# ─────────────────────────────────────────────────────────────────────────────
# ⛔⛔ I SHIPPED THE SIGNED SIGNAL AS A BARE WORD MATCH and every one of these
# worked at the revision this wave started from. The design authorised ONE
# residue — "a genuinely plural machine NAME" — and a bare-word match is far
# wider than that. Generated where the shape allows, so the corpus cannot be
# quietly narrowed to what already passes.
_PLURAL_WORDS = ("Nodes", "PCs", "Workstations", "Reports", "Briefs", "Laptops",
                 "Machines", "Desktops")
_NAME_TAILS = ("Mac", "Room", "Desktop", "East", "Box")

_NAMES_CONTAINING_A_PLURAL = tuple(
    f"{w} {t}" for w in _PLURAL_WORDS for t in _NAME_TAILS)


@pytest.mark.parametrize("name", _NAMES_CONTAINING_A_PLURAL)
def test_a_singular_machine_whose_NAME_holds_a_plural_word_is_not_a_set(name):
    """⛔⛔ `unlink my Nodes Mac`, `hide my Backup PCs Room`, `remove my Reports
    Desktop` — all refused by the first build, all working before this wave.
    """
    for said in (f"unlink my {name}", f"remove my {name}", f"hide my {name}"):
        assert not _refuses_as_a_set(said), said


# ⛔⛔ RUN TITLES ARE THE WORST OF THE FIFTEEN, because this is a RESEARCH
# product: a topic containing `reports`, `briefs` or `laptops` is ordinary, and
# `_RUN_PLURAL` carries the product's own artefact words.
_RUN_TITLES = (
    "stop my Quarterly Reports run",
    "stop my Executive Briefs Review",
    "stop the laptops comparison",
    "stop my research how to compare laptops",
    "stop my Machines Learning Report",
    "pause the quarterly reports research",
)


@pytest.mark.parametrize("said", _RUN_TITLES)
def test_a_research_topic_is_not_a_set_of_runs(said):
    assert not _refuses_as_a_set(said), said


def test_the_plural_signal_needs_a_possessive_AND_a_head():
    """⭐ THE TWO REQUIREMENTS, PAIRWISE — each shown to be load-bearing on its
    own by holding the other constant.
    """
    # possessive present, plural is the head -> a set
    assert sr._SET_SIGNAL_PLURAL.search("my computers")
    # head present, possessive absent -> not a set ("Francois Laptops")
    assert not sr._SET_SIGNAL_PLURAL.search("Francois Laptops")
    # possessive present, plural NOT the head -> not a set ("my Nodes Mac")
    assert not sr._SET_SIGNAL_PLURAL.search("my Nodes Mac")
    # and the closed continuation list keeps the verb's own object word working
    assert sr._SET_SIGNAL_PLURAL.search("my computers public")


def test_a_person_labelled_everyone_can_still_be_answered():
    """⛔ `approve Everyone Smith` was refused — `everyone` matched as a bare word."""
    for said in ("approve Everyone Smith", "deny Everyone Chen",
                 "approve Everybody Jones"):
        assert not _refuses_as_a_set(said), said
    # and the real collectives still are sets
    for said in ("approve everyone", "approve everyone waiting", "refuse everyone"):
        assert _refuses_as_a_set(said), said


def test_the_determiner_slot_is_composed_not_enumerated():
    """⛔ I WROTE IT AS A FLAT LIST OF WHOLE PHRASES and it went short on the
    first combination nobody had listed: `all the public computers` needs `the`
    AND `public` and matched neither alone. Three independent optional parts
    cover every pairing; a list of pairings is always one behind.
    """
    for said in ("ask for all the public computers",
                 "remove all my three macs",
                 "hide all the other computers",
                 "approve all of my pending requests"):
        assert sr._names_a_set(said), said
    # ⛔ and every part is still closed — a wildcard in any of them reopens the
    #   96 phrases this wave exists to keep working.
    for part in (sr._SET_POSS_WORD, sr._SET_COUNT, sr._SET_ADJECTIVE, sr._SET_OF):
        assert "\\w" not in part, part
        assert "[A-Za-z]" not in part, part


# ─────────────────────────────────────────────────────────────────────────────
# 8. THE CROSS-VERIFY REPAIRS. Five lenses found eleven defects after 30/30
#    green; these pin every repair, because a fix without a mutant is a fix
#    waiting to be undone — 7.9-3 closed fourteen blockers by editing and 17
#    repair mutants then survived.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lead", ("hey ", "so ", "please ", "and ", "ok ",
                                  "also ", "then ", "just ", "now ", ""))
@pytest.mark.parametrize("said", ("can you hide my computer",
                                  "could you make my computer public"))
def test_a_lead_in_does_not_turn_a_polite_ORDER_into_a_question(lead, said):
    """⛔⛔ MY OWN REGRESSION. `_asking_state` is 'question-word AND NOT
    `_polite_imperative`'. I gave the lead-in to the question test and left the
    veto anchored at bare `^`, so the question fired while its own veto silently
    could not — and `hey can you hide my computer` was answered with a bare
    device list instead of hiding anything. Eleven phrasings, measured against
    the revision this wave started from.
    """
    argv, lines = _said(lead + said)
    assert argv != ["devices"], f"{lead + said} -> downgraded to a list: {lines[:80]}"


_NAMES_STARTING_WITH_A_TRIGGER = ("Not My Mac", "Other Than Desktop",
                                  "Not Mine PC", "Instead Of Laptop")


@pytest.mark.parametrize("name", _NAMES_STARTING_WITH_A_TRIGGER)
def test_the_exclusion_trim_never_eats_the_WHOLE_name(name):
    """⛔⛔ MY OWN REGRESSION. The trim was written to remove a trailing clause and
    took everything when the NAME opens with a trigger word — the capture came
    back empty and the command fell to the picker, which is the
    unconfirmed-wrong-machine outcome this branch exists to avoid.
    """
    argv, _lines = _said(f"hide my {name}")
    assert argv == ["device-visibility", "private", name], argv


# ⛔⛔ THE ROOT CAUSE CROSS-VERIFY NAMED: the words the collective signal missed
# are exactly the words this file's three capture-blankers erase to "" — so a
# blank capture IS the tell, and the message holds nothing the other signals see.
_TOTALISERS = (
    ("pause everything", "run"), ("resume all of it", "run"),
    ("retry it all", "run"), ("stop everything", "run"),
    ("approve the whole queue", "person"), ("approve the lot", "person"),
    ("deny the batch", "person"), ("approve the pending ones", "person"),
    ("approve both of them", "person"), ("deny all of them", "person"),
)


@pytest.mark.parametrize("said,noun", _TOTALISERS)
def test_a_totalising_generic_is_a_set(said, noun):
    argv, lines = _said(said)
    assert argv is None, f"{said} EXECUTES {argv}"
    assert f"one {noun} at a time" in lines, f"{said} -> {lines}"


def test_a_singular_they_is_not_a_totaliser():
    """⛔⛔ BARE `them` WAS IN THE LIST AND THE PRODUCT'S OWN CORPUS REMOVED IT.
    English has a singular `them`: `let them use my computer` is a phrasing this
    client teaches, and it means ONE person. The A/B caught it on its first run.
    """
    assert not _refuses_as_a_set("let them use my computer")
    assert not sr._names_a_set("let them use my computer")
    # ⭐ and the forms that cannot be singular are still sets
    assert sr._names_a_set("approve them all")
    assert sr._names_a_set("approve all of them")


@pytest.mark.parametrize("said", ("pause every run i have", "retry each run",
                                  "resume every run", "stop all runs",
                                  "pause each run"))
def test_the_singular_run_noun_is_a_set_under_a_TOTAL_quantifier(said):
    """⛔ NOTHING SAW `every run`: `_RUN_MASS` is research|work and `_RUN_PLURAL`
    is plural-only. pause/resume/retry EXECUTE with no confirm, so all three ran
    against whichever run was current.
    """
    assert _refuses_as_a_set(said), said


@pytest.mark.parametrize("said", ("stop any run", "approve any", "deny Both",
                                  "approve Any", "pause any run"))
def test_any_means_whichever_one_and_is_never_a_set(said):
    """⛔ `any` IS ON 7.9-5's MEASURED TOO-WIDE LIST — refusing `stop any run` and
    `approve any` is the defect, not the fix. It means whichever one; `every`
    means all of them. `_resolve_asker` already asks which when several wait.
    """
    assert not _refuses_as_a_set(said), said


@pytest.mark.parametrize("said", ("switch to every computer i have",
                                  "switch to my two macs",
                                  "run it on my remaining laptops",
                                  "switch to all my computers",
                                  "run everything on all my machines"))
def test_switch_to_is_gated_because_it_mutates_with_no_confirm(said):
    """⛔⛔ THE ONE ACT BRANCH ON THIS SURFACE WITH NO CONFIRM AT ALL, and the one
    I did not gate. `_is_bare_machine_noun` caught only `<quantifier> <bare
    noun>`, which is why `switch to all my computers` looked safe while `switch
    to my two macs` executed `device-use` with a set as the machine name.
    """
    argv, lines = _said(said)
    assert argv is None or argv == ["devices"], f"{said} EXECUTES {argv}"
    if argv is None:
        assert _ONE_AT_A_TIME.search(lines), f"{said} -> {lines}"


def test_switch_to_still_resolves_a_real_name():
    """⛔ AND THE GATE MUST NOT COST THE VERB ITS JOB."""
    for name in ("All Hands Mac", "Studio PC", "LABPC001"):
        argv, _l = _said(f"switch to {name}")
        assert argv == ["device-use", name], (name, argv)
