"""Wave 1.2 — THE CAPTURES: what NAME comes out.

⛔⛔ WHY THIS FILE EXISTS. Wave 1.1 pinned whether the router ACTS. This file pins
what it acts ON. The seam is deliberate: a diff in one is attributable to one kind
of change, which is the only reason the regression 1.1 shipped was findable.

⭐⭐ THE MEASUREMENT THAT SET THE BAR: 7,091 phrases were BUILT from targets whose
expected name is known by construction, and only 2,428 came out right — 34%. The
biggest single class was a POLITENESS WORD: 592 phrasings where a command that
worked refused because the person said please.

⭐⭐ SIX THINGS EVERY TEST HERE OBEYS, EACH ONE PAID FOR:
 1. IT DRIVES THE LIVE RESOLVER, never a helper in isolation.
 2. THE EXPECTED NAME IS KNOWN BY CONSTRUCTION. A test that reads the name out of
    the code it is testing cannot see the name move.
 3. THE WORD LISTS ARE DERIVED FROM THE MODULE. Wave 1.2's own finding was that
    FOUR hand copies of one verb list existed and every dead-word defect was a
    copy gone short.
 4. THE NAME SURFACE DIFFERS BY DIRECTION. A hide returns argv; a PUBLISH is a
    CONFIRM and carries the name inside the sentence. Reading only argv reported
    2,700 working phrasings as broken during the measurement.
 5. WHAT THE NAME *DOES* IS ASSERTED, NOT JUST WHAT IT IS. A captured name goes
    through a unique-SUBSTRING match, so a truncated one can resolve to a
    DIFFERENT machine — which is exactly how the apostrophe defect hid the wrong
    computer. Those tests stub the device list and call the resolver for real.
 6. A CONTROL NAME IS PINNED BESIDE EVERY TRIM. Every trim here can eat a real
    name, and the quoted form is the escape people are told to use.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "facade"
# ⭐⭐ RULE 16 — A TEST WRITTEN ALONGSIDE A FIX IS SHOWN RED AGAINST THE PRE-FIX
# REVISION, and that demonstration has to be repeatable or it is a claim rather
# than a measurement. Point this at the baseline copy and every test below runs
# against the revision the wave started from:
#   SR_UNDER_TEST=../router-harness/sr_at_11.py pytest tests/test_router_captures_0911.py
# ⛔ IT NEVER DEFAULTS TO ANYTHING BUT THE LIVE FILE.
_SR_PATH = Path(os.environ.get("SR_UNDER_TEST")
                or _ROOT / "skill" / "scripts" / "sr.py").resolve()


def _load(name="sr_captures_0911"):
    spec = importlib.util.spec_from_file_location(name, _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load()
_SRC = _SR_PATH.read_text(encoding="utf-8")
_VIS = "device-visibility"
_CONFIRM_HEAD, _CONFIRM_TAIL = sr._NL_CONFIRMS[_VIS].split("{name}", 1)
_CONFIRM_RE = re.compile(re.escape(_CONFIRM_HEAD) + r"(.+?)" + re.escape(_CONFIRM_TAIL[:24]))
_GENERIC = "that computer"


def _r(text: str):
    argv, lines = sr._nl_resolve(text)
    return argv, " ".join(lines or [])


def _name_of(text: str):
    """The machine name the router came out with, whichever surface carries it.

    '' means the picker/generic rendering — the person named nothing usable.
    None means this message reached neither a visibility command nor its confirm.
    """
    argv, say = _r(text)
    if argv is not None:
        if not argv or argv[0] != _VIS:
            return None
        return argv[2] if len(argv) > 2 else ""
    m = _CONFIRM_RE.search(say)
    if not m:
        return None
    got = m.group(1).strip()
    return "" if got == _GENERIC else got.strip("“”\"'")


def _run_name_of(text: str):
    """The run title a run verb came out with; '' for the most-recent default."""
    argv, say = _r(text)
    if argv is not None:
        return argv[1] if len(argv) > 1 else ""
    m = re.search(r"Stop “([^”]*)”", say)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# A1 · THE TRAILING TAIL — 592 phrasings broke on one courteous word.
# --------------------------------------------------------------------------

# ⛔⛔⛔ THE TAIL WORDS SPLIT BY CONSEQUENCE, AND CROSS-VERIFY IS WHY THIS LIST
# IS TWO LISTS. Trimming every one of them unconditionally — which is what I
# built first, and what these tests pinned — produced the outcome this file
# refuses above all others: an act on the WRONG MACHINE. On an account holding
# both “Studio PC Now” and “Studio PC”, `hide my Studio PC Now` HID Studio PC,
# with no confirm; 118 distinct name→machine pairs, 430 of them on branches that
# never confirm. So:
#   ALWAYS — nobody calls a machine `please` or `thanks`. Trim on sight.
#   COMMA-GATED — real machines are called `Studio PC Now` and `PC Alone`, so
#   these come off only when a COMMA separates them, which is the person
#   themselves saying the word is not part of the name.
# ⛔ A FIX THAT TURNS A WRONG REFUSAL INTO A WRONG ACTION IS NOT A FIX. These
# tests were pinning exactly that, which is the third wave running in which my
# own tests pinned a defect.
_TAILS_ALWAYS = ["please", "thanks", ", thanks", "for me", "ok", "pls",
                 "right now", "when you get a chance", "if you can", "of course"]
_TAILS_COMMA_ONLY = ["today", "now", "instead", "also", "again", "anymore",
                     "alone", "too"]


@pytest.mark.parametrize("tail", _TAILS_ALWAYS)
@pytest.mark.parametrize("frame", ["hide my {t}", "unlist my {t}", "unpublish my {t}",
                                   "disable my {t}", "make my {t} private",
                                   "set my {t} to private"])
def test_politeness_never_joins_a_named_machine(frame, tail):
    """`hide my Studio PC please` must hide Studio PC, not “Studio PC please”."""
    assert _name_of(frame.format(t="Studio PC") + " " + tail) == "Studio PC"


@pytest.mark.parametrize("tail", _TAILS_COMMA_ONLY)
def test_an_ambiguous_tail_word_comes_off_behind_a_comma_and_not_otherwise(tail):
    """⛔⛔ THE WRONG-MACHINE GUARD. `Studio PC Now` is a machine somebody owns;
    `Studio PC, now` is a machine and an urgency. The comma is the person telling
    you which, and it is the only evidence there is."""
    assert _name_of(f"hide my Studio PC {tail}") == f"Studio PC {tail}"
    assert _name_of(f"hide my Studio PC, {tail}") == "Studio PC"


def test_the_ambiguous_words_are_exactly_the_ones_a_machine_can_be_called():
    """⛔ DERIVED, so a word cannot be moved between the halves without moving
    this test too. `please` is in the always half by name — it is the commonest
    of them and no machine is called it."""
    assert "please" not in sr._NAME_TAIL_COMMA_ONLY
    for w in _TAILS_COMMA_ONLY:
        assert re.search(rf"\b{w}\b", sr._NAME_TAIL_COMMA_ONLY), w


@pytest.mark.parametrize("tail", _TAILS_ALWAYS)
@pytest.mark.parametrize("frame", ["hide my {t}", "make my {t} private"])
def test_politeness_never_invents_a_name_for_a_bare_noun(frame, tail):
    """`hide my mac please` worked without the word; it must work with it.

    ⛔ The landing is the PICKER (no name), not a refusal — `mac please` resolves
    to nothing, and a command that degrades from acting to refusing because of a
    politeness word is the defect, not the fix.
    """
    assert _name_of(frame.format(t="mac") + " " + tail) == ""


@pytest.mark.parametrize("tail", ["please", "thanks", ", thanks", ", today"])
def test_politeness_comes_off_every_other_capture_site(tail):
    """The trim is ONE copy called from every site — that is the whole design."""
    assert _run_name_of(f"stop the tesla run {tail}") == "tesla"
    assert _r(f"pause the tesla run {tail}")[0] == ["pause", "tesla"]
    assert _r(f"resume the tesla run {tail}")[0] == ["resume", "tesla"]
    assert _r(f"switch to my Studio PC {tail}")[0] == ["device-use", "Studio PC"]
    assert "“Studio PC”" in _r(f"remove my Studio PC {tail}")[1]
    assert "“Sam”" in _r(f"approve Sam {tail}")[1]
    assert "“Studio PC”" in _r(f"ask for the Studio PC {tail}")[1]


def test_stacked_politeness_all_comes_off():
    assert _name_of("hide my Studio PC, now, thanks") == "Studio PC"
    assert _name_of("hide my Studio PC please, thanks") == "Studio PC"


# ⭐ THE CONTROL. Every trim above can eat a real name; these are the names it
# must not eat, and the quoted form is the escape people are told to use.
@pytest.mark.parametrize("name", ["Not My Mac", "Now or Never Mac", "Studio PC Now",
                                  "Please PC", "Thanks Mac", "Today Box"])
def test_a_quoted_name_survives_every_trim(name):
    assert _name_of(f'hide "{name}"') == name


def test_an_unquoted_name_whose_first_word_is_a_tail_word_survives():
    """The trim is a TAIL trim — a tail word inside or in front of a name stays."""
    assert _name_of("hide my Now or Never Mac") == "Now or Never Mac"
    assert _name_of("hide my Please Wait PC") == "Please Wait PC"


# --------------------------------------------------------------------------
# A2 · THE LINKING PREPOSITION belongs to the polarity, not the name.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("frame,polarity", [
    ("set my {t} to private", "private"), ("switch my {t} to private", "private"),
    ("put my {t} on private", "private"), ("turn my {t} into private", "private"),
    ("set my {t} to public", "public"), ("switch my {t} to public", "public"),
    ("put my {t} on public", "public"), ("turn my {t} into public", "public"),
    ("put my {t} on the public list", "public"),
])
def test_a_preposition_is_not_part_of_the_name(frame, polarity):
    assert _name_of(frame.format(t="Studio PC")) == "Studio PC"


# --------------------------------------------------------------------------
# A3 · THE APOSTROPHE — the one defect in this wave that acted on the WRONG
#      machine. `<First>'s MacBook Pro` is what a Mac calls itself out of the box.
# --------------------------------------------------------------------------

_APOSTROPHE_NAMES = ["Sam's MacBook Pro", "Sam’s MacBook Pro", "Don't Send PC",
                     "Don’t Send PC", "Rock 'n' Roll PC", "Nodes & Bolts",
                     "Lab, Room 2"]


@pytest.mark.parametrize("name", _APOSTROPHE_NAMES)
@pytest.mark.parametrize("frame", ['hide "{n}"', 'unlist "{n}"', 'make "{n}" public',
                                   'set "{n}" to private', 'disable "{n}"'])
def test_an_apostrophe_inside_a_quoted_name_is_content(frame, name):
    assert _name_of(frame.format(n=name)) == name


@pytest.mark.parametrize("name", ["Sam’s MacBook Pro", "Don’t Send PC"])
def test_curly_quotes_around_a_curly_apostrophe(name):
    """What macOS and iOS autocorrect actually type — so this is the DEFAULT."""
    assert _name_of(f"hide “{name}”") == name


def test_the_truncated_name_hid_a_different_machine(monkeypatch):
    """⛔⛔ THE PROOF, and it is why this is a blocker and not a tidy-up.

    An account holding only “Donna Mac”, told to hide “Don't Send PC”, captured
    “Don”, which uniquely SUBSTRING-matched Donna Mac — and hid it, with a ✓.
    """
    mod = _load("sr_captures_wrongmachine")
    devices = [{"id": "d2", "name": "Donna Mac", "hostname": "donna", "owned": True}]
    monkeypatch.setattr(mod, "_get", lambda p, timeout=None: (200, {"devices": devices}))
    argv, _ = mod._nl_resolve('hide "Don\'t Send PC"')
    assert argv is not None and argv[0] == _VIS
    hint = argv[2] if len(argv) > 2 else ""
    dev, fail = (mod._resolve_device_arg(hint) if hint else mod._pick_owned_device())
    assert dev is None, f"asked for “Don't Send PC”, would act on {dev!r}"
    assert "Don't Send PC" in " ".join(fail)


def test_a_correct_name_still_resolves_through_the_substring_match(monkeypatch):
    """⭐ THE CONTROL for the test above: the lookup itself is not broken."""
    mod = _load("sr_captures_rightmachine")
    devices = [{"id": "d1", "name": "Don't Send PC", "hostname": "ds", "owned": True},
               {"id": "d2", "name": "Donna Mac", "hostname": "donna", "owned": True}]
    monkeypatch.setattr(mod, "_get", lambda p, timeout=None: (200, {"devices": devices}))
    argv, _ = mod._nl_resolve('hide "Don\'t Send PC"')
    dev, _fail = mod._resolve_device_arg(argv[2])
    assert dev and dev["name"] == "Don't Send PC"


# --------------------------------------------------------------------------
# A4 · THE LEADING CATEGORY WORD — 7.9-3's defect, still live on hide/publish.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ["hide the {n}", "make the {n} public",
                                   "unlist the {n}"])
@pytest.mark.parametrize("noun", ["machine", "computer", "device", "node"])
def test_a_category_word_in_front_is_not_part_of_the_machine_name(frame, noun):
    assert _name_of(frame.format(n=f"{noun} LABPC001")) == "LABPC001"


def test_a_category_word_in_front_is_not_part_of_a_person_name():
    for lead in ("person", "user", "colleague", "requester"):
        assert f"“Sam”" in _r(f"approve the {lead} Sam")[1]
    assert "“Sam”" in _r("approve my colleague Sam")[1]


def test_a_name_whose_own_first_word_is_a_device_noun_survives():
    """⭐ 1.1's guard: a remainder opening with a conjunction proves the strip
    was wrong. `Nodes and Bolts PC` must not become `and Bolts PC`."""
    assert _r("switch to my Nodes and Bolts PC")[0] == ["device-use", "Nodes and Bolts PC"]
    assert _name_of("hide my Nodes and Bolts PC") == "Nodes and Bolts PC"


# --------------------------------------------------------------------------
# A5 · THE DETERMINER LIST is shared — switch stripped two of twelve.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("det", ["the", "a", "an", "my", "our", "your", "their",
                                 "its", "his", "her", "that", "this"])
def test_every_determiner_comes_off_the_switch_name(det):
    assert _r(f"switch to {det} Studio PC")[0] == ["device-use", "Studio PC"]


@pytest.mark.parametrize("det", ["that", "their", "this", "a"])
def test_a_determiner_plus_a_bare_noun_never_executes_a_switch(det):
    """⛔ This branch MUTATES WITH NO CONFIRM. `switch to that mac` used to run
    `device-use` on the literal string “that mac”, which resolves to nothing."""
    argv, _ = _r(f"switch to {det} mac")
    assert argv == ["devices"], argv


# --------------------------------------------------------------------------
# A6 · EVERY VERB THE SIGNAL ADMITS HAS A CAPTURE ARM — derived, not listed.
# --------------------------------------------------------------------------

# ⛔ DERIVED FROM THE MODULE — but with a pinned fallback, because rule 16 runs
# this same file against the PRE-FIX revision, where the constant does not exist
# yet. The fallback is not a second source of truth: `test_the_verb_roles_are_the
# _ones_this_wave_signed` below asserts the live module matches it exactly, so a
# word added to the code without a thought here fails rather than slips.
_HIDE_PINNED = ("hide", "unlist", "unpublish", "delist", "disable", "unshare",
                "deregister")
_PUBLISH_PINNED = ("publish", "offer", "share", "advertise", "expose")


def _hide_verbs():
    return list(getattr(sr, "_VIS_HIDE_VERBS", _HIDE_PINNED))


def _publish_verbs():
    return list(getattr(sr, "_VIS_PUBLISH_VERBS", _PUBLISH_PINNED))


def test_the_verb_roles_are_the_ones_this_wave_signed():
    assert tuple(sr._VIS_HIDE_VERBS) == _HIDE_PINNED
    assert tuple(sr._VIS_PUBLISH_VERBS) == _PUBLISH_PINNED


@pytest.mark.parametrize("verb", _hide_verbs())
def test_every_hide_verb_keeps_the_machine_name(verb):
    argv, _ = _r(f"{verb} my Studio PC")
    assert argv is not None and argv[0] == _VIS and argv[1] == "private", argv
    assert argv[2:] == ["Studio PC"], f"{verb} lost the name: {argv}"


@pytest.mark.parametrize("verb", _publish_verbs())
def test_every_publish_verb_keeps_the_machine_name(verb):
    assert _name_of(f"{verb} my Studio PC") == "Studio PC"


@pytest.mark.parametrize("phrase", [
    "stop sharing my Studio PC", "stop offering my Studio PC",
    "stop listing my Studio PC", "turn off sharing for my Studio PC",
    "take my Studio PC private", "take my Studio PC public",
    "make my Studio PC undiscoverable", "make my Studio PC invisible",
    "share my Studio PC with other people", "offer my Studio PC to everyone",
    "take my Studio PC off the public list",
])
def test_the_routes_that_carried_no_capture_arm_now_name_the_machine(phrase):
    assert _name_of(phrase) == "Studio PC", phrase


def test_a_setting_word_is_only_a_setting_when_a_machine_follows_it():
    """⛔ MY OWN A/B CAUGHT THIS. `disable sharing on my mac` captured
    “sharing on my mac” as a machine name once every hide verb got a bare arm."""
    assert _name_of("disable sharing on my mac") == ""
    assert _name_of("disable sharing on my Studio PC") == "Studio PC"
    assert _name_of("hide my Sharing Mac") == "Sharing Mac"


# --------------------------------------------------------------------------
# A8 · A NEGATOR IN FRONT OF THE POLARITY WORD is not part of the name.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("make my Studio PC not private", "Studio PC"),
    ("make my Studio PC no longer public", "Studio PC"),
    ("make my Studio PC never public", "Studio PC"),
])
def test_a_negator_before_the_polarity_word_leaves_the_name_alone(phrase, expected):
    assert _name_of(phrase) == expected


def test_a_negator_inside_a_name_is_still_ignored():
    """⭐ 1.1's rule, unchanged: adjacency to the POLARITY word is what counts."""
    assert _name_of("make my Now or Never Mac public") == "Now or Never Mac"


# ==========================================================================
# B · THE VOCABULARY. ⭐⭐ THE FACT THAT EXPLAINS THE WHOLE GROUP: the setter
# list is a TARGET list, not a SIGNAL list. Eleven of its sixteen words were in
# no signal, so `my Studio PC public` — no verb at all — reached the publish
# confirm while `publish my Studio PC` reached the DEVICE LIST.
# ==========================================================================

def test_the_setter_list_is_built_from_the_four_roles():
    """⛔ FOUR HAND COPIES OF THIS LIST EXISTED and every dead-word defect in the
    wave was a copy gone short. If a role gains a word, every reader gains it."""
    roles = (sr._VIS_POLAR_VERBS + sr._VIS_HIDE_VERBS
             + sr._VIS_PUBLISH_VERBS + sr._VIS_OFF_VERBS)
    for word in roles:
        assert re.search(rf"\b{word}\b", sr._VIS_SETTERS), word
    assert re.search(r"\bdelist\b", sr._VIS_SETTERS), "a role word went missing"


@pytest.mark.parametrize("copy", ["_polite_imperative", "_named_target"])
def test_no_hand_copy_of_the_setter_list_survives_in_the_source(copy):
    """⛔ The copies are gone as COPIES — each now interpolates the constant."""
    src = _SRC[_SRC.index(f"{copy} = "):][:900]
    assert "_VIS_SETTERS" in src, f"{copy} spells its own verb list again"


@pytest.mark.parametrize("verb", ["hide", "unlist", "unpublish", "delist",
                                  "disable", "unshare", "deregister"])
def test_every_hide_verb_admits_a_message_on_its_own(verb):
    argv, _ = _r(f"{verb} my Studio PC")
    assert argv is not None and argv[0] == _VIS and argv[1] == "private"


@pytest.mark.parametrize("verb", ["publish", "offer", "share", "advertise", "expose"])
def test_every_publish_verb_admits_a_message_on_its_own(verb):
    """⛔ These reached the DEVICE LIST — 312 measured shapes. The fix WIDENS the
    signal; narrowing the branch that stole them sends them to the catch-all
    instead, because a veto in an ordered ladder is not inert."""
    assert _name_of(f"{verb} my Studio PC") == "Studio PC"


@pytest.mark.parametrize("verb", ["publish", "offer", "share", "advertise", "expose",
                                  "hide", "unlist", "unpublish", "delist", "disable"])
@pytest.mark.parametrize("form", ["{v}s", "{v}ing"])
def test_every_inflection_of_every_visibility_verb_fires(verb, form):
    """⛔⛔ NO `-s` FORM ANYWHERE IN THIS FILE FIRED, and the two sides were exact
    inverses: the hide side had only the bare form, the publish side only `-ing`."""
    word = sr._inflect((verb,))
    said = [w for w in word if (w.endswith("ing") if "ing" in form else
                                w != verb and not w.endswith("ing"))]
    assert said, f"no {form} built for {verb}"
    argv, say = _r(f"{said[0]} my Studio PC")
    assert argv is not None or "Let other people find" in say, (said[0], argv, say)


@pytest.mark.parametrize("word", ["visible", "shared", "listed", "invisible",
                                  "undiscoverable"])
def test_the_polarity_words_that_were_in_no_signal_now_fire(word):
    """`make my mac invisible` answered with a device LIST while
    `make my mac not invisible` published it."""
    argv, say = _r(f"make my mac {word}")
    assert argv != ["devices"], (word, argv)
    assert argv is not None or "Let other people find" in say


def test_the_two_polarity_lists_are_one_list_split_by_side():
    """⛔ There were TWO, neither derived from the other. They are one now — but
    SPLIT BY SIDE, because 1.1's asymmetry is real: negating a publish is a
    concrete hide, negating a hide names no state at all."""
    assert set(sr._PUBLISH_POLARITY_WORDS) & set(sr._HIDE_POLARITY_WORDS) == set()
    for w in sr._PUBLISH_POLARITY_WORDS + sr._HIDE_POLARITY_WORDS:
        assert re.search(rf"\b{w}\b", sr._POLARITY_WORDS), w


def test_negating_a_publish_is_a_hide_and_negating_a_hide_is_not():
    """⭐ 1.1's rule, and deriving the publish-side test from the WHOLE polarity
    list broke it within minutes. This is the pin that caught it."""
    argv, say = _r("make my mac not private")
    assert argv is None and "Let other people find" in say
    assert _r("no longer publishing my mac")[0][:2] == [_VIS, "private"]


# --- B8 · the un- guard covers EVERY hide arm ------------------------------

@pytest.mark.parametrize("verb", ["hide", "unlist", "delist", "unpublish",
                                  "disable", "unshare"])
@pytest.mark.parametrize("prefix", ["un-", "un "])
def test_un_prefixing_a_hide_verb_publishes(verb, prefix):
    """⛔⛔⛔ `un-delist my Studio PC` HID THE MACHINE. The guard sat on one arm
    and `delist|disable|unshare|deregister` lived in a second arm without it, so
    the person asked to un-hide and got a hide — while `un-unlist` published.
    Two arms, two answers to the same question."""
    argv, say = _r(f"{prefix}{verb} my Studio PC")
    assert argv is None or argv[1] != "private", (verb, prefix, argv)
    assert "Let other people find" in say, (verb, prefix, say)


# --- B4/B5/B7/B10 · the words that could not fire --------------------------

def test_drop_works_on_both_sides_and_still_belongs_to_skip():
    """⛔ `drop` was in the setter list AND the control-word list, so it VETOED
    the branch it belongs to: `drop my Studio PC` reached the catch-all. It is
    THREE-way ambiguous, and the object settles it."""
    assert "“Studio PC”" in _r("drop my Studio PC")[1]
    argv, _ = _r("drop the video")
    assert argv is not None and argv[0] == "skip" and "video" in argv


def test_link_can_pair_a_computer():
    """⛔ `link` sat in the act-verb list and in NO other, so `link my computer`
    reached the catch-all — which also meant its negation veto could never fire."""
    assert "access code" in _r("link my computer")[1]


def test_phone_is_a_word_people_say_even_though_nothing_is_a_phone():
    """⛔ FIVE sites hand-spliced `|phones?` back on and the admission tests were
    the ones that didn't, so `hide my phone` died and `hide my phones` got the
    set refusal."""
    assert _r("hide my phone")[0][:2] == [_VIS, "private"]
    assert _name_of("hide my Studio Phone") == "Studio Phone"
    assert _r("hide my phones")[0] is None


def test_cancel_and_stop_answer_the_same_sentence_the_same_way():
    """⛔ `cancel` was in the run-control verb list and not the control-word list;
    the two differed by exactly that word."""
    assert _r("cancel on my Studio PC")[0] == _r("stop on my Studio PC")[0]


# --- B9/C5 · a bare machine token, and the pairing it must not become ------

@pytest.mark.parametrize("phrase,kind", [
    ("hide LABPC001", "hide"), ("make LABPC001 public", "publish"),
    ("unlist LABPC001", "hide"), ("make DESKTOP-7H3K public", "publish"),
])
def test_a_bare_machine_token_names_a_machine(phrase, kind):
    """⛔ 432 of the 1,225 dead phrasings in the corpus were this ONE shape —
    more than a third. `switch to LABPC001` worked, so nothing told the person
    which verbs would take it."""
    assert _name_of(phrase) in ("LABPC001", "DESKTOP-7H3K"), phrase


def test_remove_takes_a_bare_machine_token_too():
    assert "“LABPC001”" in _r("remove LABPC001")[1]


@pytest.mark.parametrize("phrase", ["hide 2024", "hide mars", "hide it", "hide one"])
def test_a_word_that_is_not_a_machine_token_still_names_nothing(phrase):
    """⭐ THE CONTROL. A bare number or an English word is not a hostname."""
    assert _name_of(phrase) in (None, ""), phrase


@pytest.mark.parametrize("phrase", [
    "stop the machine LABPC001 run", "approve the machine LABPC001",
    "did my logs go through? code AB12CD34",
])
def test_a_code_shaped_token_in_a_sentence_never_pairs_a_device(phrase):
    """⛔⛔ A RUN-STOP AND A CONSENT DECISION BOTH PAIRED A DEVICE, and a SUPPORT
    code — taught in two places in the document and not a pair code at all — was
    paired as a computer. The existing-machine verb list had gone short again."""
    argv, _ = _r(phrase)
    assert argv is None or argv[0] != "device-add", (phrase, argv)


@pytest.mark.parametrize("phrase", ["K7XQ-9B2M", "use this code K7XQ-9B2M",
                                    "add device K7XQ-9B2M",
                                    "pair my computer with code K7XQ-9B2M"])
def test_the_real_pairing_phrasings_still_pair(phrase):
    """⭐ THE CONTROL, and it is the exact repair a previous wave had to make:
    `use this code K7XQ-9B2M` is the commonest way anybody pairs."""
    assert _r(phrase)[0] == ["device-add", "K7XQ-9B2M"], phrase


# ==========================================================================
# C · THE SURFACE. `_nl_resolve` is an ORDERED LADDER: an earlier branch that
# matches steals the message from a later one, and a veto does not make a
# message go away — it hands it to the NEXT branch.
# ==========================================================================

@pytest.mark.parametrize("verb", ["publish", "offer", "share", "advertise", "expose"])
@pytest.mark.parametrize("target", ["my mac", "my Studio PC", "my laptop"])
def test_the_device_list_no_longer_steals_a_publish(verb, target):
    """⛔ 312 measured shapes answered with `['devices']` — the possessive reads
    as a list request and the publish verbs had no signal to beat it with."""
    argv, say = _r(f"{verb} {target}")
    assert argv != ["devices"], (verb, target, argv)
    assert argv is None and "Let other people find" in say


@pytest.mark.parametrize("phrase", [
    "list the Studio PC publicly", "advertise the Studio PC publicly",
    "list my Studio PC publicly", "take my Studio PC public",
])
def test_a_persons_own_machine_is_never_answered_with_strangers_machines(phrase):
    """⛔ Somebody's OWN named machine answered with the BROWSE list of other
    people's computers."""
    argv, say = _r(phrase)
    assert argv != ["devices-public"], (phrase, argv)
    assert "Let other people find" in say, (phrase, say)


def test_a_three_word_machine_name_is_still_the_askers_own():
    """⛔ The own-machine test allowed a two-word gap, so `my Now or Never Mac`
    was routed as somebody else's and answered with the browse list."""
    assert _name_of("advertise my Now or Never Mac publicly") == "Now or Never Mac"
    assert _name_of("hide my Show and Tell PC") == "Show and Tell PC"


# --- C4 · the research branch took 100% of research-verb openings ----------

@pytest.mark.parametrize("phrase,expected", [
    ("research my devices", ["devices"]),
    ("research my computers", ["devices"]),
    ("research the status of my run", ["status"]),
    ("research the podcast from my mac", ["podcast"]),
])
def test_an_inventory_or_a_runs_own_status_is_not_a_research_topic(phrase, expected):
    """⛔⛔ `research my devices` STARTED A PAID RUN titled “my devices”. The veto
    was a fullmatch on three bare words, so anything longer was a topic."""
    assert _r(phrase)[0] == expected, phrase


@pytest.mark.parametrize("topic", [
    "the status of the EV market", "how to stop smoking",
    "the history of the podcast industry", "progress in fusion energy",
    "why airlines cancel flights", "the pause feature",
])
def test_a_real_topic_that_merely_mentions_those_words_is_still_research(topic):
    """⭐ THE CONTROL, and an existing test caught me writing the veto too wide:
    `research the status of the EV market` is a subject, not a run of mine. What
    makes a phrase not-a-topic is WHOSE thing it names, not which noun."""
    argv, _ = _r(f"research {topic}")
    assert argv is not None and argv[0] == "research" and argv[1] == topic


@pytest.mark.parametrize("topic", ["a bank run", "the print run", "a trial run",
                                   "the fun run", "the long run", "a dry run",
                                   "the marathon run"])
def test_an_idiom_ending_in_run_is_still_a_research_topic(topic):
    """⛔⛤ THE VETO I SHIPPED HERE WAS WITHDRAWN, AND THE COST IS WHY. I refused
    any `<word> run` topic to stop `look into the Mars run` starting a paid run,
    stated the cost as `the marathon run`, and cross-verify measured the class at
    22 driven idioms wide. One case does not buy twenty-two real subjects. The
    Mars-run shape reverts to its pre-wave behaviour and is recorded as an open
    defect rather than paid for out of the product's vocabulary."""
    argv, _ = _r(f"research {topic}")
    assert argv is not None and argv[0] == "research", topic


# --- C6 · a compound ask never loses half of itself silently ---------------

@pytest.mark.parametrize("phrase", [
    "pause the run and switch to the office PC",
    "stop the tesla run and hide my mac",
    "stop the run and unlink my Studio PC",
    "pause the run and use my Studio PC",
])
def test_a_run_command_plus_a_device_command_goes_to_the_catch_all(phrase):
    """⛔ Measured three times across 1.1 and 1.2: it paused a run called “run and
    switch to the office PC” and dropped the switch. The person asked for two
    things and watched one happen to a name they never said."""
    argv, say = _r(phrase)
    assert argv is None and "didn’t catch" in say, (phrase, argv)


@pytest.mark.parametrize("phrase", [
    "stop the tesla run and show me the rest",
    "skip the video and drop claude",
    "hide my mac and make it private",
    "find a public one and ask its owner for access",
    "research how to stop smoking and start running",
    "hide my Nodes and Bolts PC",
])
def test_one_ask_with_a_conjunction_in_it_is_not_compound(phrase):
    """⭐ THE CONTROL, and my own A/B caught the first version refusing all four
    of these — one of them a phrasing the document itself teaches. Two halves of
    the SAME act are one ask, and a trailing READ request is a follow-up."""
    argv, say = _r(phrase)
    assert not (argv is None and "didn’t catch" in say), (phrase, say[:70])


def test_a_negated_publish_phrasing_hides_rather_than_publishing():
    """⛔ A NEW SIGNAL OWNS ITS OWN NEGATION. The moment `let people find my mac`
    got one, `don't let people find my mac` reached the publish CONFIRM — the
    exact opposite of the ask. My own A/B is what caught it."""
    assert _r("don't let people find my mac")[0][:2] == [_VIS, "private"]
    assert _name_of("don't let people find my Studio PC") == "Studio PC"


# ==========================================================================
# D · SKIP. ⛔⛔ THE MEASURED HEADLINE: a person could not skip a phase of any
# run but the newest active one, from chat, AT ALL. The branch had exactly two
# returns and neither ever appended a run name; 13,874 driven phrasings produced
# twelve distinct skip argvs and not one carried a run or a number. The
# capability existed only at the raw CLI.
# ==========================================================================

def test_the_chat_phase_and_agent_words_come_from_the_commands_own_maps():
    """⛔ Hand-written they went short, and the shortfall was invisible:
    `sr skip audio` works at the CLI while `skip the audio` reached the bare
    form, which resolves the run's BLOCKER — a mutation nobody asked for."""
    assert set(sr._NL_PHASE_WORDS) == set(sr._SKIP_NAMES)
    assert set(sr._NL_AGENT_WORDS) == set(sr._SKIP_AGENTS)
    assert set(sr._SKIP_PHASE_NUMBERS) == set(sr._SKIP_NAMES.values())


@pytest.mark.parametrize("phrase,expected", [
    ('skip the podcast on "Mars Water"', ["skip", "--run=Mars Water", "podcast"]),
    ("skip the video on the Mars Water run", ["skip", "--run=Mars Water", "video"]),
    ("skip the brief for the Mars Water run", ["skip", "--run=Mars Water", "brief"]),
])
def test_skip_passes_the_run_name(phrase, expected):
    assert _r(phrase)[0] == expected, phrase


@pytest.mark.parametrize("phrase", [
    "skip the video and the report", "skip the podcast", "skip the video",
    "skip chatgpt", "skip it",
])
def test_a_phase_list_is_never_mistaken_for_a_run_name(phrase):
    """⛔ The shared run-name helper falls back to "everything after the verb",
    which here is the PHASE LIST: `skip the video and the report` came out naming
    a run called “video and the report”. A skip names a run in exactly two ways —
    a quoted title, or an explicit `on|for|of <title> run`."""
    argv, _ = _r(phrase)
    assert not any(a.startswith("--run=") for a in (argv or [])), (phrase, argv)


def test_the_run_flag_survives_the_relay_into_argparse():
    """⛔ `cmd_do` sorts each token into flags-or-positionals by membership, so a
    bare `--run` lands in flags and its value becomes the topic. One glued token
    is what makes a value-carrying flag routable at all."""
    ns = sr.build_parser().parse_args(["skip", "--run=Mars Water", "--", "podcast"])
    assert ns.run == "Mars Water" and ns.phases == ["podcast"]


@pytest.mark.parametrize("phrase,expected", [
    ("skip phase 3", ["skip", "3"]),
    ("skip phase 4 and 5", ["skip", "4", "5"]),
    ("skip phases 1 and 3", ["skip", "1", "3"]),
])
def test_phase_numbers_route(phrase, expected):
    """⛔⛔ Numbers were unroutable AND landed on a mutation: `skip phase 3` reached
    the bare form, which resolves the run's current BLOCKER. The CLI has accepted
    numbers all along."""
    assert _r(phrase)[0] == expected, phrase


@pytest.mark.parametrize("phrase", ["skip step 2", "skip phase 0", "skip phase 99"])
def test_an_unskippable_phase_number_is_refused_by_name(phrase):
    argv, say = _r(phrase)
    assert argv is None and "isn’t one I can skip" in say, (phrase, argv, say)


@pytest.mark.parametrize("phrase,kept", [
    ("skip all but the podcast", "podcast"),
    ("skip everything except the brief", "brief"),
    ("skip all except the report", "report"),
    ("skip everything but the video", "video"),
])
def test_an_exclusion_skips_the_complement_not_the_keeper(phrase, kept):
    """⛔ `skip all but the podcast` SKIPPED THE PODCAST — the one thing the person
    said to keep — because the phase words were collected by presence."""
    argv, say = _r(phrase)
    assert argv and argv[0] == "skip", (phrase, argv, say)
    assert kept not in argv, (phrase, argv)
    assert len(argv) > 1, (phrase, argv)
    # every other phase NUMBER is named, exactly once
    nums = {sr._SKIP_NAMES[w] for w in argv[1:] if w in sr._SKIP_NAMES}
    assert nums == set(sr._SKIP_PHASE_NUMBERS) - {sr._SKIP_NAMES[kept]}, argv


def test_a_machine_word_no_longer_eats_the_phase():
    """⛔ `skip the podcast on my computer` bailed on the device noun and branch 2
    returned the bare form — which resolves the BLOCKER. The machine is WHERE."""
    assert _r("skip the podcast on my computer")[0] == ["skip", "podcast"]
    assert _r("skip the video on my Studio PC")[0] == ["skip", "video"]


def test_a_phase_word_inside_a_machine_name_still_bails_to_the_device_branch():
    """⭐ THE CONTROL, and the exception above could have reopened exactly the
    swap the device bail exists to prevent."""
    assert "“video PC”" in _r("remove my video PC")[1]
    argv, _ = _r("remove claude's laptop")
    assert argv is None or argv[0] != "skip"


@pytest.mark.parametrize("phrase", [
    "skip the podcast on all my runs", "skip the video in all my runs",
    "skip the brief on both runs", "skip the report in all of them",
])
def test_the_phase_arm_has_the_set_gate_the_bare_arm_already_had(phrase):
    """⛔ This was the ONLY mutating act branch with no set gate on its phase arm:
    it applied the change to ONE run and said nothing about the rest."""
    argv, say = _r(phrase)
    assert argv is None and "one run at a time" in say, (phrase, argv)


@pytest.mark.parametrize("phrase,expected", [
    ("skip the video and chatgpt", ["skip", "video", "chatgpt"]),
    ("skip chatgpt and the video", ["skip", "video", "chatgpt"]),
])
def test_agent_adjacency_is_order_independent(phrase, expected):
    """⛔ The same ask said the other way round silently dropped ChatGPT."""
    assert _r(phrase)[0] == expected, phrase


@pytest.mark.parametrize("word,canonical", [("openai", "chatgpt"), ("anthropic", "claude"),
                                            ("gpt", "chatgpt"), ("gemini", "gemini")])
def test_every_agent_alias_the_command_accepts_works_in_chat(word, canonical):
    argv, _ = _r(f"skip {word}")
    assert argv == ["skip", canonical], (word, argv)


@pytest.mark.parametrize("word", ["audio", "youtube"])
def test_every_phase_alias_the_command_accepts_works_in_chat(word):
    assert _r(f"skip the {word}")[0] == ["skip", word]


@pytest.mark.parametrize("phrase", ["can i skip the podcast", "should i skip the video",
                                    "is the podcast skipped"])
def test_a_question_about_skipping_never_downloads_anything(phrase):
    """⛔ `can i skip the podcast` fell past both branches and reached the PODCAST
    branch, which DOWNLOADS THE AUDIO. Bailing is not enough — a veto in an
    ordered ladder hands the message to the next branch."""
    argv, _ = _r(phrase)
    assert argv is None or argv[0] not in ("podcast", "skip"), (phrase, argv)


def test_skip_nothing_skips_nothing():
    """⛔ It reached the bare form and resolved the run's blocker — the one thing
    it says not to do."""
    argv, say = _r("skip nothing")
    assert argv is None and "didn’t catch" in say


# ==========================================================================
# E · THE TWO VOCABULARIES. SKILL.md puts phrasings in a person's mouth; the
# router decides what they reach. Wave 1.2 drove all 150 and found ~20 that
# resolved nowhere — including `use <name>`, which is the phrasing the client's
# OWN PICKER prints at the end of every ask.
# ==========================================================================

_SKILL_MD = _ROOT / "skill" / "SKILL.md"


def _taught_phrases():
    """Every quoted phrasing SKILL.md puts in a person's mouth.

    ⛔⛔ THE FILTER IS THE WHOLE TEST. A measurement lens reported 34 dead
    phrasings and I cut it to ~20 by hand: a TEMPLATE (`a brief on <subject>`),
    a SHELL LINE from a code fence (`curl -fsSL … | sh`) and a CONFIRM REPLY
    (`yes`, `done`, `continue`) are not things anybody types at this router, and
    driving them proves nothing. Encoding the filter here is what stops the next
    wave re-reporting them.
    """
    text = _SKILL_MD.read_text(encoding="utf-8")
    # table rows only — the left column is what the person says
    out = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        left = line.split("|")[1] if line.count("|") > 2 else ""
        for m in re.finditer(r'"([^"]{3,60})"', left):
            p = m.group(1).strip()
            if not p or p.startswith("--") or p.startswith("/"):
                continue
            if "<" in p or ">" in p:            # a template, not a phrase
                continue
            if re.search(r"\b(?:curl|irm|pipx|sr\.py|superresearch|npm|sh)\b", p):
                continue                         # a shell line from a fence
            if p.lower() in {"yes", "no", "done", "continue", "ok", "okay"}:
                continue                         # a reply to a confirm, not an ask
            out.append(p)
    return sorted(set(out))


# ⛔ THE ROWS THAT ARE ANSWERS INSIDE A FLOW, NOT STANDALONE ASKS. Each needs
# something only the previous reply carries — a support code, or the numbers the
# plan just printed — so a stateless router cannot resolve them and the document
# now says so in the row itself. They are listed here, once, rather than silently
# excluded by a pattern that would also hide a real gap.
_IN_FLOW_ONLY = {
    "did my logs go through?", "check on that support code",
    "just the one about X", "only the first two", "not all of them",
    "send the agent's log too", "include the bridge log",
    "the log from this chat",
}


def test_the_document_teaches_at_least_a_hundred_phrasings():
    """⭐ A harvester that quietly finds nothing would make the test below pass
    for the wrong reason."""
    assert len(_taught_phrases()) >= 100, len(_taught_phrases())


@pytest.mark.parametrize("phrase", _taught_phrases())
def test_every_phrasing_the_document_teaches_resolves(phrase):
    """⛔⛔ ~20 REACHED "I didn't catch a Super Research request in that", and one
    of them — `use <name>` — is what the picker itself tells people to type."""
    if phrase in _IN_FLOW_ONLY:
        pytest.skip("an answer inside the send-logs flow; the row says so")
    argv, say = _r(phrase)
    assert not (argv is None and "didn’t catch" in say), (phrase, say[:80])


@pytest.mark.parametrize("phrase", sorted(_IN_FLOW_ONLY))
def test_the_in_flow_rows_say_they_are_in_flow(phrase):
    """⭐ THE OTHER HALF OF THE RECONCILIATION. If a phrase cannot resolve, the
    row that teaches it has to say why — otherwise the next measurement reports
    it as a defect again, which is how it arrived in this wave."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    row = next(l for l in text.splitlines()
               if l.startswith("|") and f'"{phrase}"' in l)
    assert "FOLLOW-UP" in row or "IN-FLOW" in row or "ANSWERS TO" in row \
        or "INSIDE THE SEND-LOGS FLOW" in row, row[:120]


@pytest.mark.parametrize("phrase,expected", [
    ("my past research", "list"),
    ("my past research", "list"), ("my runs", "list"),
    ("did they answer?", "device-requests"),
    ("the brief link", "status"), ("the doc", "status"),
    ("use Studio PC", "device-use"),
    ("ask its owner if I can use it", "devices-public"),
])
def test_the_newly_taught_phrasings_reach_the_surface_the_row_promises(phrase, expected):
    argv, _ = _r(phrase)
    assert argv and argv[0] == expected, (phrase, argv)


@pytest.mark.parametrize("phrase", ["help", "what can you do?", "what is Super Research",
                                   "how do I start", "options", "commands"])
def test_help_answers_with_the_capability_line_and_no_blame(phrase):
    """⛔⛤ I ROUTED THESE TO THE ACCOUNT CHECK, which prints `✓ Signed in as
    <email>` and nothing else once the account has a machine — so `help` answered
    a question nobody asked. The right answer was always the catch-all's own
    list; what was wrong with it is the sentence in front that tells the person
    they failed to say anything."""
    argv, say = _r(phrase)
    assert argv is None, (phrase, argv)
    assert "didn’t catch" not in say, (phrase, say[:60])
    assert "research a topic" in say, (phrase, say[:60])


def test_take_it_off_the_public_list_hides_something():
    """⛔ A pronoun points at the machine on screen. This reached the catch-all
    while `take my mac off the public list` worked."""
    assert _r("take it off the public list")[0][:2] == [_VIS, "private"]


@pytest.mark.parametrize("phrase,expected", [
    ("hold on", ["pause"]), ("hold it", ["pause"]),
    ("continue the paused run", ["resume"]), ("try again", ["retry"]),
])
def test_a_multiword_trigger_is_never_its_own_run_title(phrase, expected):
    """⛔ The branch condition knew the multi-word forms and its own tail strip
    did not, so the trigger phrase stayed in the message and became the TITLE:
    `hold on` paused a run called “hold on”."""
    assert _r(phrase)[0] == expected, phrase


def test_thats_enough_stops_the_current_run_without_naming_it():
    argv, say = _r("that's enough")
    assert argv is None and "Stop the current run?" in say, say[:80]


# ==========================================================================
# THE SURVIVORS. ⛔⛔ THIRTEEN MUTANTS LIVED THROUGH THE FIRST RUN AND TWELVE OF
# THEM WERE REAL — my PROBE SET was weak, not the mutants. "No behavioural
# difference" is a claim about the inputs you tried before it is a claim about
# the code. Chasing two of them found DEFECTS in this wave's own repairs.
# ==========================================================================

@pytest.mark.parametrize("name", ["Nodes Mac", "Node PC", "Devices Desktop",
                                  "Machines Mac", "Computers Laptop"])
def test_a_name_that_is_two_device_nouns_keeps_both(name):
    """⛔ L3 SURVIVED AND WAS REAL. `my Nodes Mac` has a device noun for its FIRST
    word and another for its LAST, so stripping the first leaves a bare noun that
    every caller blanks — twenty frames of that one machine lost their name."""
    assert _name_of(f"hide my {name}") == name
    assert _r(f"switch to my {name}")[0] == ["device-use", name]
    assert f"“{name}”" in _r(f"remove my {name}")[1]


@pytest.mark.parametrize("q", ['"{n}"', "“{n}”"])
@pytest.mark.parametrize("tail", ["", ", thanks", " please", " today"])
def test_a_quoted_name_wins_outright_at_switch_and_unlink(q, tail):
    """⛔⛤ D2 SURVIVED AND CHASING IT FOUND A DEFECT OF MINE. Stripping quote
    characters off the EDGES works only while the quote IS the edge:
    `switch to “Nodes Mac”, thanks` kept the closing `”`, the leading-noun strip
    then ate `Nodes`, and the lookup got `Mac”` — which matched TWO machines.

    ⛔⛔ THE UNLINK LINE USED TO READ `"“Nodes Mac”" in say` AND COULD NOT FAIL ON
    THE CURLY HALF. The confirm wraps the name in those same curly quotes, so the
    doubled ““Nodes Mac”” CONTAINS the expected substring — a containment
    assertion about a string the code wraps in the same character never sees a
    doubling. Measured against the mutant that drops the unlink branch's quote
    strip: `in` caught 3 of these 8 rows, all STRAIGHT-double; equality catches 6.
    Curly is what macOS types, so the half that matters most was unpinned."""
    said = q.format(n="Nodes Mac") + tail
    assert _r(f"switch to {said}")[0] == ["device-use", "Nodes Mac"], said
    assert _r(f"use {said}")[0] == ["device-use", "Nodes Mac"], said
    argv, say = _r(f"remove {said}")
    assert argv is None, (said, argv)
    assert say == sr._NL_CONFIRMS["device-remove"].format(
        name="“Nodes Mac”"), (said, say)


@pytest.mark.parametrize("verb", ["list", "post", "advertise"])
def test_the_shape_fallback_names_the_machine_for_a_verb_no_list_holds(verb):
    """⛔ R5 SURVIVED AND WAS REAL — `list my Studio PC publicly` reached the
    confirm with no name, and `list` is deliberately not a setter."""
    assert _name_of(f"{verb} my Studio PC publicly") == "Studio PC"


@pytest.mark.parametrize("phrase", ["my mac is not public", "my studio pc was not findable",
                                    "my computer is not listed", "my laptop has not been shared"])
def test_a_copula_statement_never_becomes_a_machine_name(phrase):
    """⛔ R6 SURVIVED AND WAS REAL: the fallback captured “is not” and
    “pc was not” as machine names and offered to PUBLISH them."""
    assert _name_of(phrase) in (None, ""), (phrase, _name_of(phrase))


@pytest.mark.parametrize("phrase", ["offer all my macs to everyone",
                                    "publish all my machines to the world",
                                    "share all my computers with anyone"])
def test_naming_an_audience_never_exempts_a_genuine_set(phrase):
    """⛔ A3 SURVIVED AND WAS REAL. Blanking the whole span from the verb — the
    40-character window 1.1 had to remove — makes `offer all my macs to everyone`
    exempt, so a BULK publish executes on one machine."""
    argv, say = _r(phrase)
    assert argv is None and "one computer at a time" in say, (phrase, argv, say[:60])


@pytest.mark.parametrize("verb,expect_public", [("publishes", True), ("unpublishes", False),
                                                ("shares", True), ("disables", False),
                                                ("advertises", True), ("hides", False)])
def test_the_s_form_of_every_visibility_verb_is_spelled_the_way_english_spells_it(verb, expect_public):
    """⛔ V4 SURVIVED AND WAS REAL: with the `-es` rule broken, `publish` inflects
    to `publishs` and the words people actually type stop matching."""
    argv, say = _r(f"{verb} my Studio PC")
    assert argv != ["devices"], (verb, argv)
    if expect_public:
        assert "Let other people find" in say, (verb, say[:60])
    else:
        assert argv and argv[:2] == [_VIS, "private"], (verb, argv)


@pytest.mark.parametrize("phrase,expected", [
    ("show me public phones", "devices-public"),
    ("what phones are public", "devices-public"),
    ("is there a public phone i can use", "devices-public"),
])
def test_phone_reaches_the_public_surfaces_too(phrase, expected):
    """⛔ V11 SURVIVED because my first probe only asked about the OWNER surfaces,
    which read a different noun list. The browse and ask surfaces read the shared
    one, and without `phone` they answer the wrong question."""
    assert _r(phrase)[0] == [expected], phrase


@pytest.mark.parametrize("phrase", ['take "Studio PC" public', 'delist "Studio PC"',
                                    'unshare "Studio PC"', 'advertise "Studio PC" publicly',
                                    'expose "Studio PC" publicly'])
def test_a_quoted_name_is_a_named_target_after_every_setter(phrase):
    """⛔ V13 SURVIVED AND WAS REAL: the quoted arm held twelve of twenty-one
    setters, so a quoted name after nine of them was not a named target at all —
    and the browse list of strangers' machines answered instead."""
    argv, say = _r(phrase)
    assert argv != ["devices-public"], (phrase, argv)
    assert _name_of(phrase) == "Studio PC", phrase


@pytest.mark.parametrize("word", ["mars", "tesla", "quantum", "solar", "topic"])
def test_an_ordinary_word_after_a_setter_never_names_a_machine(word):
    """⛔ V19 SURVIVED AND WAS REAL. Without the digit-or-separator test any
    five-letter word becomes a machine — the shape that once turned
    `ask for feedback` into a consent question about a stranger."""
    argv, say = _r(f"hide {word}")
    assert argv is None and "didn’t catch" in say, (word, argv)


@pytest.mark.parametrize("phrase,expected", [
    ("who wants to use my Now or Never Mac", "device-requests"),
])
def test_a_three_word_name_is_still_the_askers_own_on_every_surface(phrase, expected):
    """⛔ S1 SURVIVED because my first probe used phrasings another clause also
    caught. The requests surface reads the own-machine test ALONE."""
    assert _r(phrase)[0] == [expected], phrase


@pytest.mark.parametrize("topic", [
    "how to stop a leak and hide the damage",
    "why people pause and switch to decaf",
    "how to cancel a booking and remove the fee",
    "pause and share strategies",
])
def test_a_topic_may_contain_both_halves_of_a_compound_shape(topic):
    """⛔ S11 SURVIVED because my first probe never built a topic carrying a
    run-control verb AND a device verb. The compound check sits BELOW the
    research branch for exactly this reason, and above it these are refused."""
    argv, _ = _r(f"research {topic}")
    assert argv is not None and argv[0] == "research", topic


@pytest.mark.parametrize("phrase,run,phases", [
    ("skip the report for the brief run", "brief", ["report"]),
    ("skip the brief on the podcast run", "podcast", ["brief"]),
    ("skip the podcast on the video run", "video", ["podcast"]),
])
def test_a_run_named_after_a_phase_is_still_a_run(phrase, run, phases):
    """⛔⛤ K5 SURVIVED AND CHASING IT FOUND TWO DEFECTS OF MINE.
    (1) The phase scan read the WHOLE message, so `skip the report for the brief
        run` skipped the BRIEF as well — the run is CALLED brief.
    (2) My own guard then threw the run name away because it looked like a phase
        word — but all three capture shapes are EXPLICIT run-naming, so a run
        genuinely called “brief” lost the only means the product offers of
        naming it, and the skip landed on the newest run instead."""
    assert _r(phrase)[0] == ["skip", f"--run={run}"] + phases, phrase


def test_drop_is_settled_by_the_device_verbs_not_by_a_veto():
    """⛔⛤ V15 IS THE ONE MUTANT THAT WAS GENUINELY EQUIVALENT, and the harness
    refuting my reasoning is what it is for. I wrote a machine-noun exclusion so
    `drop` would stop vetoing the visibility branch — and `drop` is in the device
    verbs and the unlink verbs now, so every `drop <machine>` phrasing reaches
    the unlink confirm by that road whether the veto fires or not. The guard
    could not change an outcome, so it went; this pins what actually decides."""
    assert re.search(r"\bdrop\b", sr._UNLINK_VERBS)
    assert "“Studio PC”" in _r("drop my Studio PC")[1]
    assert _r("drop the video")[0] == ["skip", "video"]


# ==========================================================================
# THE CROSS-VERIFY ROUND. ⛔⛔ FIVE LENSES FOUND 62 REGRESSIONS ACROSS 37 SHAPES
# AFTER THE HARNESS WAS GREEN, AND MOST OF THEM WERE MINE. The pattern is one
# thing said five ways: I widened, and a widening that turns a harmless refusal
# into a MUTATION is not a fix. This file's own words, from the wave before.
# ==========================================================================

# --- the capture arms stopped minting names out of sentence fragments -----

@pytest.mark.parametrize("phrase", [
    "why is my mac not public", "make sure my mac is not public",
    "my mac should not be public", "add my computer to the public list",
    "I don't want my mac to be public", "my mac must not be public",
])
def test_a_sentence_fragment_is_never_a_machine_name(phrase):
    """⛔⛔ THE MOST DANGEROUS THING THE ROUND FOUND. `why is my mac not public`
    captured “mac not”, which SUBSTRING-MATCHED “Mac Notebook” and HID IT with no
    confirm — a read-only question mutating a machine nobody named. The test is
    the LAST WORD: a name never ends in a copula, a modal or a preposition."""
    assert _name_of(phrase) in (None, ""), (phrase, _name_of(phrase))


@pytest.mark.parametrize("name", ["Studio PC", "Now or Never Mac", "LABPC001",
                                  "Show and Tell PC"])
def test_a_real_name_still_survives_the_last_word_test(name):
    assert _name_of(f"hide my {name}") == name


# --- the wrong-machine class, closed ---------------------------------------

@pytest.mark.parametrize("tail", ["Now", "Today", "Also", "Alone", "Too", "Again"])
@pytest.mark.parametrize("frame", ["hide my {n}", "make my {n} public",
                                   "set my {n} to private"])
def test_a_machine_named_after_a_tail_word_keeps_its_last_word(frame, tail):
    """⛔⛔⛔ THE OUTCOME THIS FILE REFUSES ABOVE ALL OTHERS, AND MY OWN TRIM
    PRODUCED IT. On an account holding both “Studio PC Now” and “Studio PC”,
    `hide my Studio PC Now` HID Studio PC with no confirm — 118 distinct
    name→machine pairs, 430 on branches that never confirm. The truncation is
    always a substring of the real name, so the real machine always matches too;
    the wrong one wins whenever the account holds a machine whose whole name IS
    the truncation, which is what happens when somebody buys a second one."""
    said = frame.format(n=f"Studio PC {tail}")
    assert _name_of(said) == f"Studio PC {tail}", said
    # the branches that carry the name elsewhere keep it too
    assert _r(f"switch to my Studio PC {tail}")[0] == ["device-use", f"Studio PC {tail}"]
    assert f"Studio PC {tail}" in _r(f"remove my Studio PC {tail}")[1]


def test_the_wrong_machine_is_never_the_one_that_acts(monkeypatch):
    """⛔⛔ THE PROOF, measured the way the apostrophe blocker was."""
    mod = _load("sr_captures_tailmachine")
    devices = [{"id": "d1", "name": "Studio PC Now", "hostname": "spn", "owned": True},
               {"id": "d2", "name": "Studio PC", "hostname": "sp", "owned": True}]
    monkeypatch.setattr(mod, "_get", lambda p, timeout=None: (200, {"devices": devices}))
    argv, _ = mod._nl_resolve("hide my Studio PC Now")
    dev, _fail = mod._resolve_device_arg(argv[2])
    assert dev and dev["name"] == "Studio PC Now", dev


@pytest.mark.parametrize("word", ["now", "today", "instead", "also"])
def test_the_comma_is_what_says_the_word_is_not_the_name(word):
    assert _name_of(f"hide my Studio PC, {word}") == "Studio PC"
    assert _name_of(f"hide my Studio PC {word}") == f"Studio PC {word}"


@pytest.mark.parametrize("frame", ['hide "{n}"', 'switch to "{n}"',
                                   'remove the "{n}" laptop',
                                   'pause "{n}"', 'stop "{n}"'])
def test_quoting_is_an_escape_hatch_at_every_site(frame):
    """⛔ IT WORKED AT ONE SITE OF SIX, and even there it tested the matched
    PATTERN's group count rather than whether anything had been quoted — so
    `pause “Not Today”` captured “Not” and paused a DIFFERENT run."""
    said = frame.format(n="Not Today")
    argv, say = _r(said)
    assert "Not Today" in (repr(argv) + say), (said, argv, say[:70])


# --- the widenings that turned a refusal into a mutation -------------------

@pytest.mark.parametrize("obj", ["the web", "plain english", "bullet points",
                                 "dark mode", "google", "my judgment",
                                 "the latest data", "the default"])
def test_bare_use_never_switches_machine_on_an_ordinary_object(obj):
    """⛔⛔ 24 of 24 driven objects EXECUTED a device switch with no confirm,
    repointing where every future run would run. A stop-list of phase and agent
    words cannot cover the English language; the object must name a machine."""
    argv, _ = _r(f"use {obj}")
    assert argv is None or argv[0] != "device-use", (obj, argv)


@pytest.mark.parametrize("phrase", [
    "show my shared computers", "list my visible machines",
    "my mac is listed as offline", "my laptop is shared with three people",
    "who has access to my shared mac", "my mac is not visible on the network",
])
def test_a_statement_or_a_list_ask_never_becomes_a_publish_confirm(phrase):
    """⛔⛔ THE SINGLE COSTLIEST WIDENING: admitting the bare publish-side
    polarity words moved 192 driven DEVICE LIST requests onto a publish confirm,
    and every copula statement with them — including one that says the OPPOSITE.
    The hide side has carried a copula guard for a wave; the publish side got the
    same words with none."""
    argv, say = _r(phrase)
    assert "Let other people find" not in say, (phrase, say[:70])


@pytest.mark.parametrize("phrase", ["make my mac public", "make my Studio PC visible",
                                    "make my mac shared", "publish my Studio PC"])
def test_the_publish_phrasings_the_document_teaches_still_publish(phrase):
    assert "Let other people find" in _r(phrase)[1], phrase


def test_turn_it_off_is_not_a_hide():
    """⛔ `turn it off` is the commonest way anybody says STOP THE RUN, and the
    pronoun target let it execute an UNCONFIRMED HIDE."""
    argv, _ = _r("turn it off")
    assert argv is None or argv[0] != _VIS
    assert _r("take it off the public list")[0][:2] == [_VIS, "private"]


def test_a_negated_gerund_is_still_a_negation():
    """⛔ `don't keep hiding my Studio PC` ran an UNCONFIRMED HIDE — the ask was
    to STOP hiding it. The gerunds entered the act verbs this wave and the filler
    between the negator and the verb had never had to carry `keep`."""
    argv, say = _r("don't keep hiding my Studio PC")
    assert argv is None and "didn’t catch" in say


@pytest.mark.parametrize("phrase", ["share COVID-19 findings", "publish RFC-2119 to the list",
                                    "take GPT-4 off the list", "share ISO-8601 with the team"])
def test_an_identifier_inside_a_sentence_never_names_a_machine(phrase):
    """⛔ The bare machine token fired on any hyphenated token after a setter, so
    ordinary sentences reached a publish confirm — and one EXECUTED a hide."""
    argv, say = _r(phrase)
    assert argv is None or argv[0] != _VIS, (phrase, argv)


@pytest.mark.parametrize("phrase", ["show me this week's public computers",
                                    "this is a public computer",
                                    "this must be a public machine"])
def test_a_polarity_word_in_the_gap_does_not_make_a_machine_mine(phrase):
    """⛔ Widening the own-machine gap to four turned these into MY machine, which
    vetoed the browse surface and sent them to a publish confirm."""
    assert _r(phrase)[0] == ["devices-public"], phrase


# --- the widenings that turned a working ask into a refusal ---------------

@pytest.mark.parametrize("tail", ["take a break", "put it on hold", "turn on the video",
                                  "drop me a link", "set it aside", "make a note",
                                  "keep the rest"])
def test_an_ordinary_follow_up_is_not_a_second_command(tail):
    """⛔ Splicing the SETTER list into the compound rule refused 56 driven
    follow-ups. The file's own point about that list is that it is a TARGET list,
    not a signal one."""
    argv, say = _r(f"stop the run and {tail}")
    assert not (argv is None and "didn’t catch" in say), (tail, say[:60])


@pytest.mark.parametrize("title", ["Pause and Share", "Stop and Remove", "Hide and Seek"])
def test_a_run_title_containing_a_conjunction_is_one_ask(title):
    """⛔ 16 driven titles were refused because the conjunction inside the NAME
    read as a second command, and quoting was the only escape."""
    argv, say = _r(f"stop the {title} run")
    assert not (argv is None and "didn’t catch" in say), (title, say[:60])


@pytest.mark.parametrize("topic", ["phones", "laptops", "macs", "macbooks",
                                   "the laptop market", "desktops"])
def test_a_product_noun_is_a_research_topic(topic):
    """⛔ The inventory veto had an OPTIONAL determiner, so a bare plural product
    noun counted as an inventory of this account's machines — 90 of 96 driven."""
    argv, _ = _r(f"research {topic}")
    assert argv is not None and argv[0] == "research", topic


def test_the_inventory_veto_still_catches_the_real_thing():
    assert _r("research my devices")[0] == ["devices"]
    assert _r("research my computers")[0] == ["devices"]


@pytest.mark.parametrize("phrase,expected", [
    ("the audio overview", "podcast"), ("audio overview", "podcast"),
    ("any news", "device-requests"), ("any news yet", "device-requests"),
])
def test_the_new_early_returns_stopped_eating_their_neighbours(phrase, expected):
    """⛔ `the audio overview` moved off the podcast branch — two spellings, two
    answers — and the did-they-answer bare arm was dead on a mandatory space."""
    assert _r(phrase)[0][0] == expected, phrase


def test_an_artefact_link_is_never_answered_with_pairing_instructions():
    """⛔ `link` joined the pairing words in the same wave that added the artefact
    LINK surface — 8 driven shapes answered with a pair code."""
    assert "access code" not in _r("the brief link for my mac")[1]
    assert "access code" in _r("link my computer")[1]


def test_ask_the_owner_for_an_artefact_is_a_fetch():
    assert _r("ask the owner for the podcast")[0][0] == "podcast"
    assert _r("ask its owner if I can use it")[0] == ["devices-public"]


@pytest.mark.parametrize("phrase", ["research tesla without audio",
                                    "research the EV market without youtube"])
def test_the_research_exclusion_reads_the_derived_phase_words(phrase):
    """⛔ The flag gate was a hand copy short by audio, youtube, openai and
    anthropic against the very lists the loop below it iterates — so the
    exclusion was silently dropped and a PAID RUN started on the whole string."""
    argv, say = _r(phrase)
    assert argv is None or "without" not in " ".join(argv), (phrase, argv)


@pytest.mark.parametrize("det", ["our", "your", "his", "her", "that", "this"])
def test_every_determiner_comes_off_at_unlink_and_ask(det):
    assert f"“Studio PC”" in _r(f"remove {det} Studio PC")[1], det


# --- skip, after the round ------------------------------------------------

@pytest.mark.parametrize("phrase,expected", [
    ("skip all but phase 3", ["brief", "video", "report"]),
    ("skip all but the podcast and the brief", ["video", "report"]),
    ("skip everything but the podcast and the video", ["brief", "report"]),
    ("skip all but claude and gemini", ["chatgpt"]),
    ("skip all but chatgpt", ["claude", "gemini"]),
])
def test_an_exclusion_reads_every_keeper_in_its_own_domain(phrase, expected):
    """⛔⛔ THE FIRST VERSION KNEW ONE SHAPE AND ONE KEEPER, and everything else
    INVERTED: `skip all but phase 3` skipped phase 3, `skip all but claude and
    gemini` turned off both keepers, and a second keeper was always skipped."""
    assert _r(phrase)[0] == ["skip"] + expected, phrase


@pytest.mark.parametrize("phrase,expected", [
    ("skip the video but keep the report", ["video"]),
    ("skip the podcast but not the video", ["podcast"]),
    ("skip the report but leave the brief", ["report"]),
    ("skip claude but keep gemini", ["claude"]),
])
def test_a_subtractive_exclusion_keeps_what_it_says_to_keep(phrase, expected):
    """⛔ The `but keep | but not | but leave | keep` family was not read as an
    exclusion at all, so the keeper was collected by presence and SKIPPED."""
    assert _r(phrase)[0] == ["skip"] + expected, phrase


@pytest.mark.parametrize("phrase", ["please could you skip the brief",
                                    "hey can you skip the video",
                                    "would you skip the report"])
def test_a_polite_order_to_skip_is_an_order(phrase):
    """⭐ THE CONTROL for the guard below: `could YOU skip` is an order — this
    file already has a polite-imperative rule for that shape."""
    argv, _ = _r(phrase)
    assert argv is not None and argv[0] == "skip", phrase


@pytest.mark.parametrize("phrase", ["can i skip the podcast", "should i skip the video",
                                    "btw can i skip the podcast",
                                    "quick question - can i skip the email",
                                    "i wonder if i should skip the podcast",
                                    "is the podcast skipped"])
def test_a_question_about_skipping_never_posts_a_skip(phrase):
    """⛔⛔ The guard was a `re.match` anchored at character 0, so ANY preamble
    defeated it and POSTED a real skip. Skip is not confirm-gated."""
    argv, _ = _r(phrase)
    assert argv is None or argv[0] != "skip", (phrase, argv)


@pytest.mark.parametrize("obj", ["the summary", "the sources", "the transcript",
                                 "the pdf", "the intro", "my computer"])
def test_an_unrecognised_object_never_resolves_the_runs_blocker(obj):
    """⛔ The bare arm was `^skip\\b`, so ANY object it did not recognise reached
    it — and the bare form resolves the run's current BLOCKER, a mutation none of
    those asked for."""
    argv, _ = _r(f"skip {obj}")
    assert argv != ["skip"], (obj, argv)


@pytest.mark.parametrize("phrase,expected", [
    ("skip 3", ["3"]), ("skip 4 and 5", ["4", "5"]),
])
def test_a_bare_number_after_skip_is_a_phase(phrase, expected):
    """⛔ The refusal this command prints NAMES the numbers, so it invites exactly
    `skip 3` — which reached the bare arm and resolved the blocker."""
    assert _r(phrase)[0] == ["skip"] + expected, phrase


@pytest.mark.parametrize("phrase,run", [
    ("skip the podcast on run called Deep Research", "Deep Research"),
    ("skip the video on run named Mars Landing", "Mars Landing"),
])
def test_the_explicit_called_shape_is_read_before_the_bare_one(phrase, run):
    """⛔ The `<name> run` shape ate it: `on run called Deep Research` came out
    naming a run “run called Deep”."""
    assert f"--run={run}" in _r(phrase)[0], phrase


@pytest.mark.parametrize("phrase", ["skip the podcast on the run",
                                    "skip the podcast on the current run",
                                    "skip the video on my run"])
def test_a_determiner_is_never_a_run_title(phrase):
    """⛔ `skip the podcast on the run` named a run “the”, which then
    SUBSTRING-MATCHED an arbitrary run and skipped a phase of it."""
    assert not any(a.startswith("--run=") for a in _r(phrase)[0]), phrase


def test_a_number_inside_a_run_title_is_not_a_phase():
    """⛔ The number scan read the unblanked message, so `skip phase 3 for the
    2024 run` was refused as “Phase 2024”."""
    assert _r("skip phase 3 for the 2024 run")[0] == ["skip", "--run=2024", "3"]


@pytest.mark.parametrize("phrase", ["skipping the podcast", "skipping the video"])
def test_the_ing_form_reaches_skip_and_not_the_podcast_download(phrase):
    """⛔ `skipping the podcast` fell past the skip branch into the PODCAST
    branch, which makes the bridge download the audio."""
    argv, _ = _r(phrase)
    assert argv is not None and argv[0] == "skip", (phrase, argv)


@pytest.mark.parametrize("phrase", ["skip all my runs", "skip both my runs",
                                    "skip the podcast on all my runs but the brief"])
def test_the_set_refusal_does_not_depend_on_the_object(phrase):
    """⛔ Narrowing the bare arm's object sent these to the CATCH-ALL, which says
    nothing about the thing being asked for."""
    argv, say = _r(phrase)
    assert argv is None and "one run at a time" in say, (phrase, say[:60])


# --- the last round: what the corrected corpus then measured ---------------

@pytest.mark.parametrize("phrase", ["hide LABPC001 please", "set LABPC001 to private",
                                    "make LABPC001 private today",
                                    "set LABPC001 to private today"])
def test_a_bare_machine_token_survives_a_tail_and_a_preposition(phrase):
    """⛔ Narrowing the token test to the WHOLE object left no room for the two
    things a person always adds — a linking preposition and a courtesy — so 231
    driven phrasings reached the catch-all."""
    assert _name_of(phrase) == "LABPC001", phrase


def test_a_quoted_name_is_verbatim_even_when_it_is_a_bare_noun():
    """⛔ The escape hatch means VERBATIM. A machine somebody called “my mac” is
    theirs to call that, and both the bare-noun blank and the determiner strip
    were running on the quoted capture."""
    assert _name_of('hide "my mac"') == "my mac"
    assert _name_of('publish "my mac"') == "my mac"
    assert _name_of("hide my mac") == ""       # unquoted is still the picker


def test_a_politeness_object_is_not_a_run_title():
    """⛔ `for` is one of the title prepositions, so `resume the Mars run for me`
    came out naming a run “me”."""
    assert _r("resume the Mars run for me")[0] == ["resume", "Mars"]
    assert _r("stop the Mars run for me")[1].count("“Mars”") == 1


def test_the_leading_noun_guard_looks_past_a_tail_word():
    """⛔ `my Nodes Mac today` left “Mac today”, which is not a bare noun — so the
    guard passed and the strip still ate half the name."""
    assert _name_of("hide my Nodes Mac today") == "Nodes Mac today"
    assert _name_of("hide my Nodes Mac") == "Nodes Mac"


@pytest.mark.parametrize("phrase,expected", [
    ("skip the Mars run", ["--run=Mars"]),
    ("skip the Mars Water run", ["--run=Mars Water"]),
    ('skip "Mars Water"', ["--run=Mars Water"]),
])
def test_a_named_run_with_no_phase_is_a_bare_skip_on_that_run(phrase, expected):
    """⛔ It named a run and no phase — which is exactly what the bare form is
    for — and reached the catch-all instead."""
    assert _r(phrase)[0] == ["skip"] + expected, phrase


@pytest.mark.parametrize("phrase", ["skip the podcast on the run",
                                    "skip the podcast on the current run",
                                    "skip the video on my run"])
def test_the_prepositionless_title_carries_no_preposition_of_its_own(phrase):
    """⛔ A space-tolerant capture reached ACROSS one: `skip the podcast on the
    run` came out naming a run “podcast on the”."""
    assert not any(a.startswith("--run=") for a in _r(phrase)[0]), phrase


def test_a_quoted_run_title_keeps_a_politeness_word_that_is_part_of_it():
    """⛔ FROM THE RE-MUTATION ROUND. The quoted bypass has to reach the RUN verbs
    too: `pause "Mars Please"` is a run somebody called that, and without it the
    always-trim list took the last word and paused a different run."""
    assert _r('pause "Mars Please"')[0] == ["pause", "Mars Please"]
    assert "“Studio PC Please”" in _r('stop sharing "Studio PC Please"')[1]
