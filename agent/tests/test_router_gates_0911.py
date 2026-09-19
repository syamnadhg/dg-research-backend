"""Wave 1.1 — THE GATES: whether the router acts at all.

⛔⛔ WHY THIS FILE EXISTS. Wave 1's measurement drove 12,700 phrasings through the
live resolver and found 124 defects, 39 of them EXECUTING. This file pins the
VETO half — the five fixes that decide whether the router acts. The capture half
(what name comes out) is wave 1.2 and is deliberately NOT pinned here, so that a
diff in either can be attributed to one kind of change.

⭐⭐ FIVE THINGS EVERY TEST HERE OBEYS, EACH ONE PAID FOR:
 1. IT DRIVES THE LIVE RESOLVER. A predicate can be 44/44 while the product is
    broken — 7.9-5b's gate scored 52/52 with 96 real machine names unusable.
 2. THE CONTROL CORPUS IS GENERATED, two- and three-token. 7.9-5b's name cases
    were all single tokens glued to a quantifier, and the defect needed two.
 3. THE WORD LISTS ARE DERIVED FROM THE MODULE. Hand-written copies of this
    file's own vocabulary have gone short by one twice, and both times the test
    went green over a live defect.
 4. A VETO'S LANDING IS ASSERTED, NOT ITS ABSENCE. Three times in one change a
    veto handed the message to the NEXT branch, which then acted on the wrong
    feature: pause fell through to a device switch, skip fell through to fetching
    a podcast. "Did not do X" is not a passing state; "did Y" is.
 5. THE BEHAVIOURAL A/B IS A TEST, not a one-off — every phrase SKILL.md and the
    routing tests already feed this resolver is replayed, because that is the
    method that measured the regression, and it costs milliseconds.
"""

from __future__ import annotations

import importlib.util
import inspect
import itertools
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "facade"
_SR_PATH = _ROOT / "skill" / "scripts" / "sr.py"
_SKILL = _ROOT / "skill" / "SKILL.md"


def _load():
    spec = importlib.util.spec_from_file_location("sr_gates_0911", _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load()
_SRC = _SR_PATH.read_text(encoding="utf-8")


def _r(text: str):
    """(argv, joined relay lines) — what the product DOES with a message."""
    argv, lines = sr._nl_resolve(text)
    return argv, " ".join(lines or [])


def _acts(text: str) -> bool:
    return _r(text)[0] is not None


def _code_only(src: str) -> str:
    """The module's source with comment lines removed.

    ⛔⛔ THE FIRST VERSION OF THE DERIVATION BELOW READ THE COMMENTS, and this
    file's history says that happened FOUR TIMES IN ONE WAVE: prose quoting the
    string a guard searches for satisfies the guard. Two of the nine refusals it
    "derived" were comments in this very file quoting the real ones.
    """
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


# ⛔ DERIVED FROM THE CODE, NOT TYPED OUT AND NOT READ OUT OF PROSE. The refusal
# wording is the product's own. ⛔⛔ AND IT IS MATCHED ON THE TAIL, because two of
# the refusals are f-strings whose VERB is a placeholder —
# `f"I {_verb} one computer at a time"` and `f"I say {_plural} one person at a
# time"` — so a pattern anchored on `I <words> one` misses exactly the two
# surfaces that mutate a setting and grant access. Missing them made four set
# tests below pass vacuously on the first run.
_SET_SUBJECTS = tuple(sorted({
    m.group(1) for m in re.finditer(r"one ([a-z]+) at a time", _code_only(_SRC))}))
_ONE_AT_A_TIME = tuple(f"one {s} at a time" for s in _SET_SUBJECTS)


def _refused_as_a_set(text: str) -> bool:
    argv, say = _r(text)
    return argv is None and any(p in say for p in _ONE_AT_A_TIME)


def _is_catch_all(text: str) -> bool:
    argv, say = _r(text)
    return argv is None and say.startswith(sr._NL_CATCH_ALL[:40])


def test_the_derived_refusal_list_is_not_empty_and_covers_every_gated_surface():
    """⛔ THE GUARD ON THE GUARD. `_ONE_AT_A_TIME` is used in NEGATIVE assertions,
    so if the regex stopped matching, every set test below would pass vacuously.
    7.9-5b shipped exactly this bug: a hand-written list missing `owner` would
    have gone green across all 384 generated cases.
    """
    assert len(_SET_SUBJECTS) >= 4, _SET_SUBJECTS
    assert {"computer", "run", "person", "owner"} <= set(_SET_SUBJECTS), _SET_SUBJECTS


# --------------------------------------------------------------------------
# FIX 1 — THE FIFTH SET SIGNAL: A CONJUNCTION.
# --------------------------------------------------------------------------

_SET_PHRASES_THAT_MUST_REFUSE = [
    # the two that EXECUTED with no confirm at all
    "hide my mac and pc",
    "pause the tesla run and the ford run",
    # the destructive one
    "remove my mac and pc",
    "delete my mac and my pc",
    "unlink my mac and pc",
    "forget my mac as well as my pc",
    # the one that grants ACCESS
    "approve my mac and pc",
    # and the rest of the eight verbs
    "make my mac and pc public",
    "unpublish my mac & pc",
    "stop my tesla and ford runs",
    "hide the Studio PC and the Lab Mac",
    "retry the tesla run, the ford run and the bmw run",
    "switch to my mac and my pc",
    "skip both my runs",
    "hide mac, pc and laptop",
    "hide my mac or pc",
    # ⭐ TWO NAMES SHARING ONE PLURAL HEAD — the third shape, and the one both
    # noun-on-each-side shapes were blind to.
    "stop my tesla and ford runs",
    "stop my tesla and ford reports",
    "pause my two tesla and ford runs",
    "hide my mac but also my pc",
]


@pytest.mark.parametrize("phrase", _SET_PHRASES_THAT_MUST_REFUSE)
def test_a_conjunction_names_a_set_and_the_set_is_refused(phrase):
    """⛔⛔ THE SIGNAL 7.9-5b DID NOT HAVE. With no conjunction shape, `my mac and
    pc` read as ONE machine with a funny name, on eight verbs.
    """
    assert _refused_as_a_set(phrase), _r(phrase)


# ⭐⭐ THE CONTROL CORPUS IS GENERATED. A real machine whose NAME holds `and`/`or`
# must keep working — that is the constraint that makes this fix hard, and a
# hand-picked sample is what let the last one through.
_NAME_LEFT = ("Rock", "Salt", "Black", "Nodes", "Cloak", "Hue", "Cat", "Trial",
              "Now", "Bits", "Stars", "Cash", "Bricks", "Bed", "Hide", "Stop")
_NAME_RIGHT = ("Roll", "Pepper", "Decker", "Bolts", "Dagger", "Cry", "Mouse",
               "Error", "Never", "Bobs", "Stripes", "Carry", "Mortar",
               "Breakfast", "Seek", "Go")
_NAME_HEAD = ("PC", "Mac", "Laptop", "Desktop", "Node")
_NAMES_WITH_A_CONJUNCTION = [
    f"{ln} {c} {r} {h}"
    for (ln, r), h, c in itertools.product(zip(_NAME_LEFT, _NAME_RIGHT),
                                          _NAME_HEAD, ("and", "or"))
]


@pytest.mark.parametrize("name", _NAMES_WITH_A_CONJUNCTION)
def test_one_machine_whose_name_holds_a_conjunction_is_never_a_set(name):
    """⛔⛔⛔ THE 84 FALSE POSITIVES I SHIPPED IN 7.9-5b, GENERATED. `hide my Nodes
    Mac` worked and `hide my Nodes and Bolts PC` came back "I hide one computer at
    a time" — I put `and`/`or` in the head test and reopened the hole the head
    test exists to close. The discriminator is NOT the conjunction: it is whether
    a machine noun sits on BOTH sides of it, in a shape a single name cannot take.
    """
    for verb in ("hide", "unlist", "unlink", "remove"):
        phrase = f"{verb} my {name}"
        assert not _refused_as_a_set(phrase), _r(phrase)


@pytest.mark.parametrize("topic", [
    "tesla and ford", "the pros and cons of solar", "risk and reward in bonds",
    "war and peace", "supply and demand", "black and white film",
    "profit and loss statements", "salt and pepper production",
])
def test_a_research_topic_that_holds_a_conjunction_still_researches(topic):
    """⛔ THIS IS A RESEARCH PRODUCT. A topic containing `and` is ordinary, and
    7.9-4 lost real topics to a widened noun list."""
    argv, _ = _r(f"research {topic}")
    assert argv and argv[0] == "research", argv
    assert topic in " ".join(argv[1:]), argv


@pytest.mark.parametrize("phrase,expected_head", [
    # the head test still protects a name whose second word is a device noun
    ("hide my Mac and PC Room", "device-visibility"),
    # a non-nominal `and` is not a set
    ("hide my mac and make it private", "device-visibility"),
])
def test_the_head_test_and_non_nominal_clauses_are_not_sets(phrase, expected_head):
    argv, say = _r(phrase)
    assert not _refused_as_a_set(phrase), (argv, say)
    if argv:
        assert argv[0] == expected_head, argv


def test_the_two_words_removed_from_the_head_test_are_still_carried():
    """⛔ `and`/`or` came OUT of the head test, and the sets they were carrying
    have to be carried by the new signal instead — otherwise the fix for the false
    positives is a hole for the true ones."""
    assert _refused_as_a_set("hide all my computers and my laptops")
    assert _refused_as_a_set("hide my computers and list them")


# --------------------------------------------------------------------------
# FIX 2 — MY OTHER THREE FALSE POSITIVES.
# --------------------------------------------------------------------------

def test_everything_followed_by_a_preposition_is_the_object_not_a_set():
    """⛔⛔ `run everything on my Studio PC` came back "I run on one computer at a
    time" — while the branch's OWN capture spells `run (?:it |everything )?on`
    verbatim. My gate refused the product's own documented phrasing."""
    argv, _ = _r("run everything on my Studio PC")
    assert argv == ["device-use", "Studio PC"], argv
    assert re.search(r"run \(\?:it \|everything \)\?on", _SRC), \
        "the phrasing this test defends is no longer in the capture"
    # and the totaliser still fires where it must
    assert _refused_as_a_set("pause everything")
    assert _refused_as_a_set("stop everything")


def test_the_publish_audience_is_not_a_count_of_machines():
    """⛔ `everyone` in `make my mac public to everyone` is WHO CAN SEE IT.
    Publishing is inherently to everyone; exactly one machine was named."""
    assert not _refused_as_a_set("make my mac public to everyone")
    # the people-collective still fires on the consent surface
    assert _refused_as_a_set("approve everyone")


def test_a_trailing_read_only_question_is_not_a_set_and_is_not_in_the_name():
    """⛔ `stop the tesla run and show me the rest` named ONE run and then asked a
    second, read-only thing. It was refused as a set — and once it stopped being
    refused, the tail was welded into the run TITLE, which is not an improvement.
    """
    assert not _refused_as_a_set("stop the tesla run and show me the rest")
    _, say = _r("stop the tesla run and show me the rest")
    assert "“tesla”" in say, say
    argv, _ = _r("hide my studio pc and show me the rest")
    assert argv == ["device-visibility", "private", "studio pc"], argv


def test_but_excludes_only_when_it_negates():
    """⛔⛔ MY OWN EXPECTATION WAS WRONG HERE FIRST, and driving it is what showed
    me: `approve everyone but Sam` is STILL A SET — everyone minus one is many
    people — so refusing it is correct and the exclusion vocabulary changes
    nothing about it.
    ⛔ AND BARE `but` WAS A HOLE I OPENED. `hide my mac but also my pc` had its
    second machine blanked away as an "exclusion", leaving ONE target and an
    unconfirmed hide. `but` excludes only when it negates; `but also` is a
    conjunction, and belongs in the conjunction list instead.
    """
    assert "but\\s+not" in sr._SET_EXCLUSION, sr._SET_EXCLUSION
    assert "but also" in sr._SET_CONJ or "but\\s+also" in sr._SET_CONJ
    assert _refused_as_a_set("approve everyone but Sam")
    assert _refused_as_a_set("hide my mac but also my pc")
    # a single target with a negating exclusion is not a set
    assert not _refused_as_a_set("hide the Studio PC but not the Lab Mac")


# --------------------------------------------------------------------------
# FIX 3 — POLARITY IS COMPUTED, NOT COLLECTED.
# --------------------------------------------------------------------------

_HIDE = "device-visibility"


@pytest.mark.parametrize("phrase,direction", [
    # ⛔⛔ FIVE THAT DID THE EXACT OPPOSITE, UNCONFIRMED.
    ("turn on sharing for my mac", "publish"),
    ("un-hide the Studio PC", "publish"),
    ("make my mac not private", "publish"),
    ("make my Now or Never Mac public", "publish"),
    # and the directions that were always right must stay right
    ("turn off sharing for my mac", "hide"),
    ("stop sharing my mac", "hide"),
    ("take my mac off the public list", "hide"),
    ("make my mac private", "hide"),
    ("hide my mac", "hide"),
    ("make my mac not public", "hide"),
    ("make my mac public", "publish"),
    # ⛔ THE ASYMMETRY: negating a PUBLISH names a concrete act; two tests in the
    # existing suite demand these, and my first veto broke both.
    ("no longer share my mac", "hide"),
    ("I do not want my computer to be public anymore", "hide"),
    ("don't make my mac public", "hide"),
])
def test_polarity_goes_the_way_the_person_asked(phrase, direction):
    argv, say = _r(phrase)
    if direction == "hide":
        assert argv and argv[0] == _HIDE and argv[1] == "private", (argv, say)
    else:
        assert argv is None and "Let other people find" in say, (argv, say)


def test_a_negator_inside_a_machine_name_is_part_of_the_name():
    """⛔⛔ `make my Now or Never Mac public` HID a machine whose own name says
    "Never", and `hide my Not My Mac` must keep its name. Position relative to the
    DETERMINER is what separates a name from a negation — not distance, because
    both shapes put a machine noun between the negator and the polarity word.
    """
    _, say = _r("make my Now or Never Mac public")
    assert "Now or Never Mac" in say, say
    argv, _ = _r("hide my Not My Mac")
    assert argv == [_HIDE, "private", "Not My Mac"], argv


def test_the_two_halves_of_the_off_arm_need_different_verbs():
    """⛔⛝ `turn on sharing` HID the machine because `off` was one alternative in a
    list shared with the -ing words, and `turn` matched the verb half."""
    assert sr._negated_command("don't turn on sharing for my mac") is False
    argv, say = _r("turn on sharing for my mac")
    assert argv is None and "Let other people find" in say, (argv, say)
    # the negative verbs still reach a hide through the -ing words
    for p in ("stop offering my machine", "shut down listing for my mac",
              "no longer publishing my mac"):
        argv, _ = _r(p)
        assert argv and argv[:2] == [_HIDE, "private"], (p, argv)


# --------------------------------------------------------------------------
# FIX 4 — A NEGATED COMMAND NEVER REACHES ITS OWN VERB.
# --------------------------------------------------------------------------

_NEGATABLE = [
    "hide my studio pc", "send the logs", "send the computer's own logs",
    "switch to the office PC", "pause the tesla run", "resume the Mars run",
    "skip this run", "unlink my studio pc", "research solar panels",
    "add device K7XQ-9B2M", "retry the tesla run", "fetch the podcast",
    "list my devices",
]
_NEGATORS = ["don't ", "do not ", "never ", "no need to ", "please don't ",
             "i don't want to ", "stop trying to ", "dont "]


@pytest.mark.parametrize("base,neg", list(itertools.product(_NEGATABLE, _NEGATORS)))
def test_a_negated_command_lands_on_the_catch_all(base, neg):
    """⛔⛔⛔ MEASURED: 81 of 112 negated forms still reached the action, across
    eight surfaces. `don't send the logs` SENT THE LOGS to support.

    ⭐ THE LANDING IS ASSERTED, not merely the absence of the action — a negation
    that got past one branch REROUTED into another: `don't research the pause
    feature` came back as ['pause','feature'].
    """
    phrase = neg + base
    assert _is_catch_all(phrase), _r(phrase)


def test_dont_and_do_not_answer_the_same_sentence_the_same_way():
    """⛔ They diverged: `don't hide my studio pc` HID IT while `do not hide my
    studio pc` listed devices."""
    assert _r("don't hide my studio pc") == _r("do not hide my studio pc")


def test_the_veto_sits_above_every_act_branch():
    """⛔ STRUCTURAL: the failure was not one branch missing a veto — it was eight.
    The check has to precede the first `return [` in the ladder, or a branch added
    later inherits the defect."""
    src = inspect.getsource(sr._nl_resolve)
    assert src.index("_negated_command(t)") < src.index("return [\"device-add\""), \
        "the negation veto must precede every act branch"


def test_a_negation_inside_a_quoted_name_does_not_veto_its_own_request():
    """⛔ Quoting is the escape every residue in this file offers, and it has to
    work here too."""
    assert sr._negated_command('hide "Don\'t Panic PC"') is False


# --------------------------------------------------------------------------
# FIX 5 — THE QUESTION GUARD, AND WHERE A VETO HANDS THE MESSAGE NEXT.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "why did it pause", "is it safe to try again", "should i skip it",
    "how do i stop a run", "what happens if i stop a run",
    "did you pause the run", "can i pause the tesla run",
])
def test_a_question_about_a_run_verb_never_executes_it(phrase):
    """⛔⛔ The question guard existed for ONE branch of five. `skip` had it because
    "skip is not confirm-gated" — and stop, pause, resume and retry are the same.
    """
    argv, _ = _r(phrase)
    assert argv is None or argv[0] not in ("pause", "resume", "retry", "skip", "stop"), argv


@pytest.mark.parametrize("phrase", [
    "i want to stop smoking", "how to stop smoking",
    "stop asking me about my mac", "please stop bothering me",
])
def test_a_topic_or_a_complaint_never_reaches_a_destructive_confirm(phrase):
    """⛔⛔ THIS IS A RESEARCH PRODUCT AND PEOPLE TYPE TOPICS.
    `i want to stop smoking` offered *Stop "smoking"?* — an ending for a run
    named after somebody's habit."""
    argv, say = _r(phrase)
    assert "It ends the run" not in say, (argv, say)
    assert argv is None or argv[0] != "stop", argv


@pytest.mark.parametrize("phrase,head", [
    ("stop the tesla run", None), ("stop it", None),
    ("pause the tesla run", "pause"), ("retry the Mars run", "retry"),
    ("resume the Mars run", "resume"), ("skip this run", "skip"),
    # ⛔ A BARE VERB NAMES THE CURRENT RUN, and the run-shape test refused it.
    ("retry", "retry"), ("pause", "pause"), ("skip", "skip"),
    ("stop", None),
])
def test_a_real_run_command_still_fires(phrase, head):
    argv, say = _r(phrase)
    if head is None:
        assert argv is None and "It ends the run" in say, (argv, say)
    else:
        assert argv and argv[0] == head, argv


@pytest.mark.parametrize("phrase,expected", [
    # ⛔⛔⛔ THE LESSON OF THIS WHOLE CHANGE, PINNED. A veto in an ordered ladder is
    # NOT inert: it hands the message to whatever comes next. Three times here a
    # new veto produced an action on the WRONG feature, and only these landings
    # catch that — "did not pause" was true in every one of them.
    ("pause the run on the shared machine", ["pause", "shared machine"]),
    # ⛔⛤ 1.2: the phase is the verb's OBJECT here, so it is extracted.
    #    Bailing sent these to branch 2, whose bare form resolves the run's
    #    BLOCKER — a different mutation than the one asked for.
    ("skip the podcast on my computer", ["skip", "podcast"]),
    ("skip the video on my mac", ["skip", "video"]),
    ("use this code K7XQ-9B2M", ["device-add", "K7XQ-9B2M"]),
])
def test_where_a_veto_hands_the_message_next(phrase, expected):
    argv, say = _r(phrase)
    assert argv == expected, (argv, say)


def test_stop_falling_through_to_a_device_switch():
    """⛔ `stop the run on the public computer` must reach the STOP confirm, not
    execute a device switch — the fall-through my first device-noun bail caused."""
    argv, say = _r("stop the run on the public computer")
    assert argv is None and "It ends the run" in say, (argv, say)


def test_the_question_guard_is_defined_once_for_all_five_branches():
    """⛔ Two copies of a guard is how this file's noun lists drifted by two words
    and silently broke four guards."""
    src = inspect.getsource(sr._nl_resolve)
    assert src.count("_q_start = re.match(") == 1, "the question guard was copied"
    # ⛔ THE ANCHOR MOVED IN 1.2, AND A STALE ANCHOR MEASURES NOTHING. The
    # run-control family's trigger phrases were folded into one pattern per verb
    # because the branch condition knew the multi-word forms and its own tail
    # strip did not — so `hold on` became a run TITLE. The subject here is the
    # ORDER, not the literal, and `_T_STOP` is where that family now begins.
    assert src.index("_q_start = re.match(") < src.index("_T_STOP = "), \
        "the guard must be defined above the run-control family"


# --------------------------------------------------------------------------
# FIX 6 — TWO WAYS TO PAIR A COMPUTER NOBODY ASKED TO PAIR.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "hide device LABPC001", "publish machine LABPC001",
    "unlist the device LABPC001", "status of support code AB12CD34",
])
def test_an_id_in_a_non_pairing_sentence_never_pairs(phrase):
    argv, _ = _r(phrase)
    assert argv is None or argv[0] != "device-add", argv


@pytest.mark.parametrize("phrase,tok", [
    ("K7XQ-9B2M", "K7XQ-9B2M"),
    ("use this code K7XQ-9B2M", "K7XQ-9B2M"),
    ("add device LABPC001", "LABPC001"),
    ("pair my PC, code is MFG8-33UD", "MFG8-33UD"),
    ("here is my access code K7XQ-9B2M", "K7XQ-9B2M"),
])
def test_pairing_itself_still_works(phrase, tok):
    """⛔⛔ AND THIS IS THE TEST THAT CAUGHT ME REPEATING A DOCUMENTED MISTAKE. The
    file says, in as many words, that a previous repair "BROKE PAIRING ITSELF" by
    excluding any message containing `use` — the word in `use this code`. My first
    version of the guard did the same thing, and answered a pasted code with the
    catch-all."""
    assert _r(phrase)[0] == ["device-add", tok], _r(phrase)


def test_the_existing_device_verbs_are_derived_not_typed_out():
    """⛔ The hand-written list named no visibility verb and no read verb, which is
    the whole defect. It has to be built from the inventory the file already
    keeps, or it drifts again."""
    src = inspect.getsource(sr._nl_resolve)
    block = src[src.index("_existing = re.search("):]
    block = block[:block.index("\n        if ")]
    assert "_VIS_SETTERS" in block, "the verb list is hand-written again"


# --------------------------------------------------------------------------
# THE STANDING A/B — the product's own phrases, replayed.
# --------------------------------------------------------------------------

def _harvested_phrases():
    out = set()
    txt = _SKILL.read_text(encoding="utf-8")
    for m in re.finditer(r'[“"]([^”"\n]{6,70})[”"]', txt):
        s = m.group(1).strip()
        if " " in s and re.match(r"^[a-z]", s) and not s.startswith(("sr ", "/", "--")):
            out.add(s)
    return sorted(out)


def test_no_harvested_phrase_crashes_the_resolver_or_is_vetoed_by_accident():
    """⭐⭐ THE A/B IS A TEST, NOT A ONE-OFF. Every phrase SKILL.md teaches is
    replayed: none may crash, and none of the ones that do NOT contain a negator
    may land on the negation veto. That second half is what would catch a veto
    widened until it ate the product's own vocabulary.
    """
    phrases = _harvested_phrases()
    assert len(phrases) >= 20, f"the harvester stopped finding phrases: {len(phrases)}"
    negwords = re.compile(r"\b(?:don'?t|do not|never|not|no longer|cannot|can'?t|"
                          r"won'?t|shouldn'?t|no need)\b", re.I)
    wrongly_vetoed = []
    for p in phrases:
        argv, say = _r(p)                      # must not raise
        if not negwords.search(p) and say.startswith(sr._NL_CATCH_ALL[:40]):
            if sr._negated_command(p):
                wrongly_vetoed.append(p)
    assert not wrongly_vetoed, wrongly_vetoed


# --------------------------------------------------------------------------
# STRUCTURAL GUARDS — the defect classes this file has shipped before.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("const", ["_SET_CONJ", "_SET_NOUN", "_NEG_WORDS",
                                   "_ACT_VERBS", "_POLARITY_WORDS", "_SET_HEAD"])
def test_every_new_constant_is_self_grouping(const):
    """⛔⛔ THIS WAVE'S PREDECESSOR SHIPPED THIS DEFECT INTO THE FIX FOR IT. I wrote
    a constant as a bare alternation, interpolated it into a larger one, and its
    first alternative became a TOP-LEVEL alternative of the whole pattern — all
    384 generated names classified as sets. Appending a suffix must bind to the
    WHOLE constant, so every one of them has to be parenthesised or a lookahead.
    """
    val = getattr(sr, const)
    assert isinstance(val, str), const
    probe = re.compile(val + r"ZZZ") if not val.startswith("(?=") else None
    if probe is None:
        return
    assert not probe.search("and"), f"{const} leaks a top-level alternative"


def test_the_head_test_no_longer_admits_a_conjunction():
    """⛔ The exact two words that reopened the 7.9-5b hole."""
    assert "and" not in sr._SET_HEAD, sr._SET_HEAD
    assert r"or\b" not in sr._SET_HEAD, sr._SET_HEAD


def test_the_conjunction_signal_has_no_unbounded_filler():
    """⛔ An unbounded span is how 7.9-5's wildcard ate real machine names. The gap
    in the named shape is capped, and the cap is what this pins."""
    assert re.search(r"\{0,2\}", sr._SET_CONJ_NAMED), sr._SET_CONJ_NAMED
    assert ".*" not in sr._SET_CONJ_NAMED and ".+" not in sr._SET_CONJ_NAMED


def test_the_catch_all_sentence_exists_once():
    """⛔ The veto has to land on the same words the ladder's own fallback uses; a
    second copy of a user-facing sentence is how this file's guards have drifted."""
    assert _SRC.count("I didn’t catch a Super Research request in that. I can research") == 1


def test_a_trim_never_returns_an_empty_name():
    """⛔ A trim that eats the whole name sends the command to the picker, which is
    the unconfirmed-wrong-target outcome these branches exist to avoid. Measured
    on `Not My Mac` in 7.9-5b."""
    for name in ("Not My Mac", "and", "show me the rest", "Rock and Roll PC"):
        assert sr._trim_trailing_clause(name), name


# ==========================================================================
# THE MUTATION SURVIVORS. 38/45 on the first run, and every one of the seven
# was a test I had not written — plus one REAL DEFECT the survival exposed.
# ⛔ Apply the mutant, don't reason about it: my first probes for four of these
# showed "no behavioural difference", which would have retired them as
# equivalent. The probes were too weak, not the mutants. The inputs below are
# the ones that actually exercise each guard.
# ==========================================================================

def test_a_double_negation_lands_on_the_catch_all():
    """⛔⛔ THE DEFECT A SURVIVOR FOUND, not a gap it found. `don't make my mac not
    private` and `never make my mac not private` negate the REQUEST and the
    POLARITY, and they reached a PUBLISH CONFIRM — the opposite of the ask, on the
    surface where one "yes" makes a machine findable by strangers. The conjunct
    that stops it was in my first draft and I dropped it when the publish-side
    asymmetry went in; nothing but the harness noticed.
    """
    for p in ("don't make my mac not private", "never make my mac not private"):
        assert _is_catch_all(p), (p, _r(p))
    # and the single negation still names its real act
    argv, say = _r("make my mac not private")
    assert argv is None and "Let other people find" in say, (argv, say)
    assert _r("make my mac not public")[0][:2] == [_HIDE, "private"]


@pytest.mark.parametrize("name", ["Not Send PC", "Do Not Delete PC", "Never Share Mac",
                                  "No Pause Laptop", "Don't Stop Desktop"])
def test_a_machine_named_after_an_act_verb_is_still_usable(name):
    """⛔⛔ THE ONLY SHAPE WHERE THE NAME-BLANKING IN THE VETO CAN MATTER, and the
    one my first probe set missed: a negator inside the NAME followed by an ACT
    VERB. `hide my Not Send PC` is a machine called "Not Send PC"; without the
    blanking the veto reads "not … send" as a refusal to send and answers the
    catch-all, so the machine cannot be hidden, unlinked or published at all.
    ⭐ This is the 7.9-4 lesson in a new place: a word list that cannot tell a
    name from a keyword eats real machines.
    """
    assert sr._negated_command(f"hide my {name}") is False, name
    assert sr._negated_command(f"unlink my {name}") is False, name


@pytest.mark.parametrize("name", ["Do Not Delete PC", "Never Share Mac", "No Publish Mac"])
def test_a_quoted_name_containing_an_act_verb_is_never_vetoed(name):
    """⛔ Quoting is the escape every residue in this file offers. `unlink "Do Not
    Delete PC"` reached the catch-all once the quoted span stopped being blanked
    in the veto — and quoting is precisely what a person reaches for when their
    machine's name fights the parser."""
    assert sr._negated_command(f'unlink "{name}"') is False, name
    assert sr._negated_command(f'hide "{name}"') is False, name


@pytest.mark.parametrize("phrase", [
    "can i switch to the office PC", "why switch to the office PC",
    "what about pause the run on the shared machine",
    "should i run it on the office PC",
])
def test_a_question_never_executes_a_device_switch(phrase):
    """⛔⛔ THE SWITCH BRANCH IS THE ONE ACT BRANCH ON THIS SURFACE THAT MUTATES
    WITH NO CONFIRM AT ALL, and it had no question guard. It also became the
    landing place for every question the run-control family started bailing on, so
    `what about pause the run on the shared machine` came out as a device switch —
    a veto on one branch turning into an action on another.
    """
    argv, _ = _r(phrase)
    assert argv is None or argv[0] != "device-use", argv


def test_a_phone_counts_as_a_device_for_the_skip_guard():
    """⛔⛝ `phones?` IS IN THE SHARED DEVICE-NOUN LIST FOR A REASON.

    ⛔⛤ AND WAVE 1.2 MOVED WHAT THAT REASON PROTECTS. The guard used to bail on
    ANY machine noun, so `skip the video on my phone` returned a bare skip — and
    the bare form resolves the run's current BLOCKER, a different mutation than
    the person asked for. The phase is the verb's OBJECT there and the phone is
    WHERE, so it is extracted now. What the shared noun list still decides, and
    what this pins, is the SET refusal and the device branches: a plural phone is
    a set of machines, and `remove my phone` is an unlink, not a skip.
    """
    assert _r("skip the video on my phone")[0] == ["skip", "video"]
    assert _refused_as_a_set("skip the podcast on my phones")
    argv, _ = _r("remove my phone")
    assert argv is None or argv[0] != "skip", argv
    assert _r("hide my phone")[0][:2] == ["device-visibility", "private"]


@pytest.mark.parametrize("name", ["Nodes and Bolts PC", "Nodes or Bolts Mac",
                                  "Devices and Things Laptop", "Macs and Cheese Desktop"])
def test_the_leading_noun_strip_never_leaves_a_dangling_conjunction(name):
    """⛔⛔ `switch to my Nodes and Bolts PC` EXECUTED `device-use` with the name
    "and Bolts PC" — the name's own first word is a device noun, so it was read as
    a category word and dropped, welding a dangling conjunction onto the front of
    a machine name. ⭐ The A/B found it, and only because the conjunction signal
    had just stopped refusing these names: the strip had ALWAYS been wrong here
    and the refusal was hiding it.
    """
    out = sr._strip_leading_noun(name)
    assert not re.match(r"^(?:and|or|&|plus)\b", out, re.I), (name, out)
    argv, _ = _r(f"switch to my {name}")
    assert argv == ["device-use", name], argv


def test_the_trim_guard_fires_on_an_input_that_actually_empties():
    """⛔⛔ MY FIRST VERSION OF THIS TEST PASSED VACUOUSLY. It fed names that the
    trim never shortens at all, so the never-empty guard was never reached and the
    mutant that removes it SURVIVED. An input that genuinely trims to nothing is
    the only thing that measures the guard.
    """
    emptying = ", not all my devices"
    assert re.sub(rf"\s*(?:,|;|\band\b)\s*{sr._SET_EXCLUSION}\s*$", "",
                  emptying, flags=re.I).strip() == "", "this input no longer empties"
    assert sr._trim_trailing_clause(emptying) == emptying
    argv, _ = _r("hide the , not all my devices")
    assert argv == [_HIDE, "private", emptying], argv


# ==========================================================================
# THE CROSS-VERIFY ROUND. Five lenses drove 22,633 phrasings AFTER the harness
# was 45/45 green and found 76 subjects, 35 of them regressions THIS WAVE
# caused. Thirteen were reproduced by hand; all thirteen were real.
# ⛔⛔ THREE OF THE FIVE ROOT CAUSES WERE THE SAME LESSON THIS WAVE IS ABOUT:
# a trim ate a real name, a veto handed its message to the wrong branch, and a
# hand-written list went short. Knowing the lesson did not stop me writing it.
# ==========================================================================

@pytest.mark.parametrize("phrase,expect_set", [
    # ⛔⛔ `everything` MEANS DIFFERENT THINGS TO DIFFERENT VERBS, and my first
    # exemption was verb-blind: it killed the totaliser for five surfaces at once.
    ("pause everything on my mac", True),
    ("retry everything on my mac", True),
    ("stop everything on my mac", True),
    ("pause everything to do with tesla", True),
    ("hide everything in my devices list", True),
    ("pause everything", True),
    ("stop everything", True),
    # ⭐ and the ONE exemption, which is the product's own wording on ONE branch
    ("run everything on my Studio PC", False),
])
def test_everything_is_a_totaliser_on_every_surface_but_the_switch(phrase, expect_set):
    assert _refused_as_a_set(phrase) is expect_set, (phrase, _r(phrase))


def test_the_switch_exemption_is_local_to_the_switch_branch():
    """⭐ The blanking lives on the branch whose own capture spells the wording,
    not in the shared signal — because on a RUN verb the same word genuinely
    means every run."""
    assert _r("run everything on my Studio PC")[0] == ["device-use", "Studio PC"]
    assert _r("run it on my Studio PC")[0] == ["device-use", "Studio PC"]
    assert "run\\s+everything\\s+on" in _SRC, "the local blanking is gone"


@pytest.mark.parametrize("name", ["Show and Tell PC", "Rack and Display PC",
                                  "Name and Shame Mac", "Show and Go Laptop",
                                  "List and Learn Desktop", "Tell and Sell PC"])
def test_the_read_tail_trim_never_truncates_a_real_name(name):
    """⛔⛝ A READ VERB IS NOT ENOUGH — IT NEEDS A QUESTION'S OBJECT AFTER IT.
    `hide my Show and Tell PC` EXECUTED a hide on a machine called "Show", and
    `pause the Show and Tell research` paused a run called "Show". That is the
    trim-eats-a-real-name class this whole wave exists to close, reintroduced by
    this wave's own new trim, and the harness was 45/45 green when it shipped.
    """
    assert sr._trim_trailing_clause(name) == name, name
    argv, _ = _r(f"hide my {name}")
    assert argv == [_HIDE, "private", name], argv


def test_the_read_tail_still_trims_a_real_follow_up_question():
    """⭐ And the trim still does its job — a follow-up question names WHO it is
    for, which a machine name never does."""
    _, say = _r("stop the tesla run and show me the rest")
    assert "“tesla”" in say, say
    assert _r("hide my studio pc and show me the rest")[0] == [_HIDE, "private", "studio pc"]


def test_not_excludes_only_when_it_opens_a_clause():
    """⛔⛔ TWO SAFE-LOOKING EDITS COMPOSING INTO ONE LIVE DEFECT. Bare `not` in the
    exclusion vocabulary was pre-existing and harmless; removing `and` from the
    head test was correct on its own. Together, `hide my computers and my Not
    Ready PC` had its second machine blanked as an "exclusion", which left the
    plural without its head and EXECUTED an unconfirmed hide on a set.
    """
    assert _refused_as_a_set("hide my computers and my Not Ready PC")
    # the real exclusion shapes still blank
    assert not _refused_as_a_set("hide the Studio PC, not all my devices")
    assert _r("hide the Studio PC, not all my devices")[0] == [_HIDE, "private", "Studio PC"]


@pytest.mark.parametrize("phrase", ["pause and switch to the Studio PC",
                                    "stop and remove the video",
                                    "cancel and switch to the office PC"])
def test_a_dropped_run_control_never_becomes_another_mutating_act(phrase):
    """⛔⛔⛔ THE THIRD AND FOURTH TIME IN ONE WAVE. A run-control verb whose branch
    bails must not hand the message to a DIFFERENT mutating branch:
    `pause and switch to the Studio PC` EXECUTED a device switch and dropped the
    pause; `stop and remove the video` EXECUTED a phase skip and dropped the stop.
    Both are compound asks naming two acts, and silently doing the second one is
    worse than asking. The harness was green for both.
    """
    argv, _ = _r(phrase)
    assert argv is None or argv[0] not in ("device-use", "skip"), argv


def test_the_drop_guard_does_not_break_the_branches_below_it():
    """⭐ It gates only what mutates BELOW. Everything that legitimately reaches
    the switch and skip branches must still get there."""
    assert _r("switch to the office PC")[0] == ["device-use", "office PC"]
    assert _r("run everything on my Studio PC")[0] == ["device-use", "Studio PC"]
    assert _r("skip the podcast on my computer")[0] == ["skip", "podcast"]
    assert _r("skip the video")[0] == ["skip", "video"]
    assert _r("pause the run on the shared machine")[0] == ["pause", "shared machine"]


@pytest.mark.parametrize("phrase", ["my computer is not listed", "my mac is not public",
                                    "my studio pc was not findable",
                                    "my computer isn't listed"])
def test_a_statement_of_state_is_not_a_request_to_hide(phrase):
    """⛔ `my computer is not listed` EXECUTED a hide. The person was telling the
    client what they already see, or asking about it, and the answer was to act on
    it. A copula in front of the negator makes it a statement, not an order."""
    argv, _ = _r(phrase)
    assert argv is None or argv[0] != _HIDE, argv


@pytest.mark.parametrize("verb", ["ask to use", "request access to", "borrow"])
def test_the_ask_surface_is_covered_by_the_negation_veto(verb):
    """⛔⛔ THE HAND-WRITTEN ACT-VERB LIST WENT SHORT BY FOUR — the failure this
    file already records twice. `don't ask to use the Lab Mac` still offered to
    hand the owner this person's name and email, which is the one verb on this
    surface that spends a request and arms a week-long refusal."""
    assert sr._negated_command(f"don't {verb} the Lab Mac") is True, verb
    assert sr._negated_command(f"never {verb} the Lab Mac") is True, verb
    # and the un-negated ask still works
    argv, say = _r("ask to use the Lab Mac")
    assert argv is None and "Ask the owner" in say, (argv, say)
