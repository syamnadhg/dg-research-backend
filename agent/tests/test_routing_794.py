"""THE SHARED MACHINE-NOUN LIST, AND THE FIVE DEFECTS FOUND MEASURING 7.9-4.

⛔⛔ 7.9-3 SHARED THE MACHINE-NOUN LIST BETWEEN TWO SITES AND ITS OWN COMMENT SAID
"Every site that asks 'is a computer being talked about' now reads this one name."
SIX MORE HAND-WRITTEN COPIES SURVIVED, each narrower than the shared list, and the
measurement pass for this wave found every one of them by running the resolver
rather than by reading it. That is the same false-unification shape the 7.9-3
record already logged once, in the same function.

⭐ SO THE GUARDS BELOW ARE PARAMETRISED OVER THE WHOLE LIST, NOT OVER ONE WORD. A
seventh copy that goes in narrow fails on the noun it forgot, by name.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli
from tests.conftest import code_only

_ROOT = Path(__file__).resolve().parents[1] / "facade"
_SR_PATH = _ROOT / "skill" / "scripts" / "sr.py"
_SKILL = _ROOT / "skill" / "SKILL.md"
_CLI = _ROOT / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("sr_routing_794", _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load()

# Every word the product accepts for a machine, from the shared list itself — so
# adding a word to `_MACHINE_NOUNS` widens these guards automatically.
NOUNS = [re.sub(r"s\?$", "", n) for n in sr._MACHINE_NOUNS.split("|")]


def test_the_noun_list_is_the_one_the_guards_read():
    assert "mac" in NOUNS and "workstation" in NOUNS and "computer" in NOUNS
    assert len(NOUNS) == 10, NOUNS


# ── the six sites that had their own narrower copy ───────────────────────────

@pytest.mark.parametrize("noun", NOUNS)
def test_the_add_guard_reaches_every_noun(noun):
    """MEASURED AT HEAD: "add my mac" and "connect my workstation" reached the
    catch-all, which then offered to "manage your devices"."""
    argv, lines = sr._nl_resolve(f"add my {noun}")
    assert argv is None and "access code" in lines[0], (noun, argv, lines)


@pytest.mark.parametrize("noun", NOUNS)
def test_the_device_list_clause_reaches_every_noun(noun):
    """MEASURED AT HEAD: "show my computers", "which machines do I have" and
    "which pcs do I have" all reached the catch-all."""
    argv, _lines = sr._nl_resolve(f"show my {noun}s")
    assert argv == ["devices"], (noun, argv)


@pytest.mark.parametrize("noun", NOUNS)
def test_a_category_ask_never_raises_a_consent_question_about_it(noun):
    """⛔⛔ MEASURED AT HEAD: "ask for a public mac" raised the DISCLOSING consent
    question naming a machine called “public mac”. That is the 7.9-2 defect whose
    repair comment sits thirty lines above the guard, reintroduced by a noun list
    rather than by the capture logic."""
    argv, lines = sr._nl_resolve(f"ask for a public {noun}")
    assert argv == ["devices-public"], (noun, argv, lines)


@pytest.mark.parametrize("verb,expect", [
    ("remove my", 'Unlink “LABPC001”'),
    ("switch to the", None),
])
def test_phone_is_stripped_like_every_other_noun(verb, expect):
    """⛔ `phones?` IS IN THE BARE-NOUN TEST AND HAS TO BE IN THE STRIP TOO. The
    unlink rule admits it as a thing people SAY while nothing in this product is
    one — so with it missing from the strip, "remove my phone LABPC001" quoted
    “phone LABPC001” back in a DESTRUCTIVE confirm whose own follow-up cannot
    resolve it.

    ⛔⛔ THE GUARDS EITHER SIDE OF THIS BOTH MISSED IT. The bare-noun guard covers
    "remove my phone" and the strip guard is parametrised over `NOUNS`, which is
    derived from `_MACHINE_NOUNS` and does not contain `phone`. A mutant survived
    in the gap between them.
    """
    argv, lines = sr._nl_resolve(f"{verb} phone LABPC001")
    if expect is None:
        assert argv == ["device-use", "LABPC001"], argv
    else:
        assert argv is None and expect in lines[0], lines


@pytest.mark.parametrize("noun", NOUNS)
def test_a_leading_noun_is_stripped_before_a_destructive_confirm(noun):
    argv, lines = sr._nl_resolve(f"remove my {noun} LABPC001")
    assert argv is None and "Unlink “LABPC001”" in lines[0], (noun, lines)


@pytest.mark.parametrize("noun", NOUNS)
def test_a_leading_noun_is_stripped_before_a_switch(noun):
    argv, _lines = sr._nl_resolve(f"switch to the {noun} LABPC001")
    assert argv == ["device-use", "LABPC001"], (noun, argv)


@pytest.mark.parametrize("noun", NOUNS)
def test_a_bare_noun_is_not_a_name_on_the_switch_branch_either(noun):
    """⛔ THE SAME DEFECT AS THE UNLINK BRANCH, ONE RULE OVER, and the guard above
    could not see it — every one of its cases supplies a real name after the noun.
    "switch to the mac" looked up a device literally called "mac" and reported it
    missing; the list is what the reader needs instead."""
    argv, _lines = sr._nl_resolve(f"switch to the {noun}")
    assert argv == ["devices"], (noun, argv)


def test_the_refusal_fallback_converts_the_verb_it_was_given():
    """⛔⛔ THE SIGNED-OUT ROW SITS ABOVE THE FALLBACK, so every test of that row
    passes without the conversion ever running. This drives the fallback itself,
    with an error no table has a row for — which is what a new app-side code is."""
    for phrase in sorted(sr._PLAIN_VERBS):
        said = sr._list_refusal_line(phrase, "some_new_code_nobody_mapped")
        assert sr._PLAIN_VERBS[phrase] in said, (phrase, said)
        assert phrase not in said, (phrase, said)
    for phrase in sorted(cli._PLAIN_VERBS):
        said = cli._list_refusal(phrase, "some_new_code_nobody_mapped")
        assert cli._PLAIN_VERBS[phrase] in said, (phrase, said)
        assert phrase not in said, (phrase, said)


@pytest.mark.parametrize("name", ["Mac Studio", "MacBook Air", "Workstation 3",
                                  "PC Lab", "Desktop Two", "Laptop Two"])
def test_the_strip_never_eats_the_first_word_of_a_real_name(name):
    """⛔⛔ FOUR OF THE WIDENED NOUNS ARE WORDS PEOPLE PUT IN A MACHINE'S NAME.
    "switch to the Mac Studio" reached for “Studio”, "remove my MacBook Air"
    offered to unlink “Air”, and "switch to the Workstation 3" looked up “3”.
    ⛔ `PC Lab` and `Desktop Two` were broken BEFORE this wave — `pc` and `desktop`
    were already in the strip — so this closes two older ones as well."""
    argv, _lines = sr._nl_resolve(f"switch to the {name}")
    assert argv == ["device-use", name], (name, argv)
    _argv, lines = sr._nl_resolve(f"remove my {name}")
    assert f"Unlink “{name}”" in lines[0], (name, lines)


@pytest.mark.parametrize("noun", NOUNS)
def test_the_strip_still_removes_the_noun_in_front_of_an_identifier(noun):
    """The other half: `<noun> <id>` is the shape the strip exists for."""
    argv, _lines = sr._nl_resolve(f"switch to the {noun} LABPC001")
    assert argv == ["device-use", "LABPC001"], (noun, argv)


@pytest.mark.parametrize("rest,keep", [
    ("LABPC001", False), ("PC2", False), ("Studio", True), ("Air", True),
    ("3", True), ("Two", True), ("MINI", False),
])
def test_what_counts_as_an_identifier_rather_than_the_rest_of_a_name(rest, keep):
    assert sr._looks_like_an_identifier(rest) is (not keep), rest


@pytest.mark.parametrize("said,expected", [
    ("I don't have the podcast from my computer yet", "podcast"),
    ("I don't have an update on my machine", "status"),
    ("I don't have a computer, log me in", "login"),
    ("I don't have the report from my laptop", None),
])
def test_the_no_computer_rule_claims_only_what_nothing_else_did(said, expected):
    """⛔⛔ IT WAS WRITTEN AT 2e AND STOLE FIVE RULES. A negation plus a machine
    word appears in a great many sentences that are about something else — a
    podcast, a status, a RUN STOP, a sign-in. It sits directly above the catch-all
    now, so it can only claim what nothing else wanted, and no guard list has to be
    kept in step with the rules above it."""
    argv, _lines = sr._nl_resolve(said)
    if expected is None:
        assert argv != ["devices"], (said, argv)
    else:
        assert argv and argv[0] == expected, (said, argv)


def test_a_run_stop_survives_a_sentence_that_also_says_i_do_not_have():
    argv, lines = sr._nl_resolve("I don't have time, stop the run on my mac")
    assert argv is None and "Stop" in lines[0], lines


@pytest.mark.parametrize("said", [
    "which device is my run on", "list my devices and runs",
    "show me the devices with my research", "show me my devices and their status",
])
def test_an_inventory_question_carrying_an_artefact_word_still_lists(said):
    """⛔⛔ THE ARTEFACT GATE BELONGS ONLY TO THE WORDS THIS WAVE ADMITTED. Applied
    to the whole clause it dropped these four — all plainly inventory questions —
    into the catch-all that claims it can "manage your devices"."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["devices"], (said, argv)


def test_a_progress_question_about_a_machine_is_not_an_inventory_question():
    """⛔ `running` IS NOT IN THE ARTEFACT LIST and had to be named: at HEAD the
    narrow clause let this fall through to the progress rule."""
    argv, _lines = sr._nl_resolve("what's running on my mac")
    assert argv == ["updates"], argv


def test_a_research_request_is_never_answered_with_a_pair_code():
    """⛔⛔ THE ADD/PAIR GUARD SITS ABOVE THE RESEARCH RULE, and widening its nouns
    made it swallow a topic: "research how to connect my mac" answered "paste the
    access code"."""
    argv, _lines = sr._nl_resolve("research how to connect my mac")
    assert argv and argv[0] == "research", argv
    assert argv[1] == "how to connect my mac", argv


@pytest.mark.parametrize("said", [
    "remove all my devices", "remove every computer", "unlink all of my macs",
])
def test_a_bulk_request_says_the_thing_it_cannot_do(said):
    """⛔ UNLINK TAKES EXACTLY ONE MACHINE. Answering with "which one?" hides that
    the request as made cannot be carried out; the confirm it used to raise named
    a machine called “all my devices”."""
    argv, lines = sr._nl_resolve(said)
    assert argv is None, (said, argv)
    assert "one computer at a time" in lines[0], (said, lines)


@pytest.mark.parametrize("det", ["that", "this", "their", "its", "a", "the", "my"])
def test_every_determiner_is_stripped_before_a_destructive_confirm(det):
    """⛔ THE ASK BRANCH STRIPPED EIGHT AND THIS ONE STRIPPED TWO, so "remove that
    computer" and "unlink their laptop" carried the word into the confirm."""
    argv, lines = sr._nl_resolve(f"remove {det} computer")
    assert argv is None, (det, argv)
    assert "“" not in lines[0], (det, lines)


def test_a_quoted_name_is_not_quoted_twice():
    """⛔ THIS CLIENT TELLS PEOPLE TO REPLY WITH THE NAME IN QUOTES, so a quoted one
    arrives here wrapped — and the confirm printed it doubled."""
    _argv, lines = sr._nl_resolve('remove "Studio PC"')
    assert "Unlink “Studio PC”" in lines[0], lines
    assert "““" not in lines[0], lines


def test_no_hand_written_noun_list_survives_in_the_resolver():
    """⛔ THE SOURCE GUARD THE LAST WAVE'S COMMENT NEEDED AND DID NOT HAVE. Its
    claim of unification was true of two sites and false of six."""
    src = code_only(_SR_PATH.read_text(encoding="utf-8"))
    assert "device|node|machine|computer|pc|laptop|desktop" not in src
    # ⛔⛔ ONE NARROW CLAUSE SURVIVES ON PURPOSE, AND CROSS-VERIFY IS WHY. Gating
    # the WHOLE device-list clause on `_artefact_kw` dropped four questions that
    # worked at HEAD — "which device is my run on", "list my devices and runs",
    # "show me the devices with my research", "show me my devices and their
    # status" — into the catch-all that boasts it can "manage your devices". The
    # narrow half keeps HEAD's behaviour exactly; only the widened half has to
    # prove it is not really about a podcast or a run. So it must appear ONCE.
    assert src.count("(devices?|nodes?)") == 1, src.count("(devices?|nodes?)")


# ── the defect the wider list EXPOSED, and would have made worse ────────────

@pytest.mark.parametrize("noun", NOUNS + ["phone"])
def test_a_bare_noun_is_never_quoted_as_a_name_in_a_destructive_confirm(noun):
    """⛔⛔ "remove my mac" NAMES NOTHING. Widening the noun list made the capture
    return the noun itself, and the confirm offered to unlink a machine called
    “mac” — a destructive confirm whose own "yes" resolves to "No device matching
    “mac”". `phone` is here because the unlink rule admits it as a thing people
    SAY while nothing in this product is one, so it can never be a name either."""
    argv, lines = sr._nl_resolve(f"remove my {noun}")
    assert argv is None, (noun, argv)
    assert f"“{noun}”" not in lines[0], (noun, lines)
    assert "unlink" in lines[0].lower(), (noun, lines)


@pytest.mark.parametrize("noun", NOUNS)
def test_the_list_clause_does_not_swallow_the_verbs_below_it(noun):
    """⛔⛔ THE PRE-EXISTING DEFECT THIS CLOSES. The list clause sits ABOVE the
    switch and remove branches, so "remove my node" printed the device list instead
    of offering to unlink — measured and left alone in 7.9-3. Widening the clause
    alone would have made "remove my mac" and "remove my computer" join it."""
    argv, lines = sr._nl_resolve(f"remove my {noun} LABPC001")
    assert argv != ["devices"], (noun, argv, lines)


@pytest.mark.parametrize("said,expected", [
    ("ask for the podcast on my computer", "podcast"),
    ("ask for an update on my machine", "status"),
    ("send me the report from my mac", "podcast"),
])
def test_the_list_clause_bails_on_an_artefact(said, expected):
    """⛔⛔ CAUGHT BY THE EXISTING SUITE THE MOMENT THE CLAUSE WIDENED. These carry
    both a possessive and a machine word; with the wider list they became requests
    to list devices and the artefact rules below never saw them."""
    argv, _lines = sr._nl_resolve(said)
    assert argv != ["devices"], (said, argv)


# ── four of the wider nouns double as real machine NAMES ────────────────────

@pytest.mark.parametrize("said", [
    "ask for a mac", "ask for a public mac", "ask for another macbook",
    "ask for someone else's workstation", "ask for a desktop",
])
def test_a_determiner_makes_an_ambiguous_noun_a_category(said):
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["devices-public"], (said, argv)


@pytest.mark.parametrize("said,name", [
    ("request access to that Mac", "Mac"),
    ("ask for the Lab Mac", "Lab Mac"),
    ("ask for the Studio PC", "Studio PC"),
])
def test_a_bare_or_deictic_ambiguous_noun_stays_a_name(said, name):
    """⛔⛔ THE WIDE LIST CANNOT GO IN FLAT AND A TEST CAUGHT IT. "request access to
    that Mac" points at one row; reading “Mac” as a category answered a named ask
    with a list of everybody's machines."""
    argv, lines = sr._nl_resolve(said)
    assert argv is None, (said, argv)
    assert f"“{name}”" in lines[0], (said, lines)


# ── the refusal a signed-out person with no computer actually reads ─────────

def test_the_chat_signed_out_refusal_is_a_sentence_they_can_act_on(monkeypatch):
    """⛔⛔ THE BRIDGE'S OWN 401 IS A SENTENCE, NOT A TOKEN, so it keyed no row and
    fell to a fallback that interpolated a past-tense phrase: "Couldn’t asked for
    your requests: not signed in — run /login". The people that hits are exactly
    the ones this wave is for."""
    said = sr._list_refusal_line("asked for your requests", "not signed in — run /login")
    assert "Couldn’t asked" not in said
    assert "tell me to log you in" in said.lower(), said
    # ⛔ AND NOT THE BRIDGE'S OWN TEXT: "/login" is the terminal's command and this
    # is chat, where the person says it in words.
    assert "/login" not in said, said


def test_the_terminal_signed_out_refusal_is_a_sentence_they_can_act_on():
    said = cli._list_refusal("looked for public computers", "not signed in — run /login")
    assert "couldn't looked" not in said
    assert "agent login" in said, said


@pytest.mark.parametrize("client,helper,table", [
    ("chat", "_list_refusal_line", "sr"),
    ("terminal", "_list_refusal", "cli"),
])
def test_every_caller_phrase_has_a_plain_verb_row(client, helper, table):
    """⛔ THE PAST TENSE IS LOAD-BEARING ABOVE AND WRONG BELOW. `what` reads
    "You've ASKED for your requests too many times" in the rate-limit sentence and
    "Couldn't ASK for your requests" in the fallback, and the old code patched
    exactly one word of one caller's phrase: "looked" → "look". Derived from the
    source, so a new caller with no row fails here rather than shipping broken
    English."""
    mod = sr if table == "sr" else cli
    src = (_SR_PATH if table == "sr" else _CLI).read_text(encoding="utf-8")
    phrases = set(re.findall(rf"{helper}\(\s*'([^']+)'", code_only(src)))
    assert phrases, client
    for p in phrases:
        assert p in mod._PLAIN_VERBS, (client, p)
        assert mod._PLAIN_VERBS[p] != p, (client, p)


def test_the_two_clients_agree_on_which_phrases_they_convert():
    assert set(sr._PLAIN_VERBS) == set(cli._PLAIN_VERBS)


# ── SKILL.md: two claims it made that the code has never made ───────────────

def test_the_device_row_is_documented_with_the_words_the_code_prints():
    """⛔⛔ SKILL.md SAID THE ROW READS `findable` OR `hidden`. Both clients print
    `public` / `private`, the command is `device-visibility public`, and the web
    app's toggle says "Public computer" — and this same file said `public` or
    `private` correctly 94 lines earlier, so it disagreed with itself as well as
    with the code."""
    skill = _SKILL.read_text(encoding="utf-8")
    assert "`findable` or `hidden`" not in skill
    # ⛔ THE SECOND ASSERTION USED TO BE A DISJUNCTION whose right half is the row
    # this file requires, so it could never fail. The precise claim is narrower
    # than "the word is absent": the word is fine in PROSE (it explains what
    # discovery means, and it is a word people say), and wrong in a BACKTICKED
    # span, which is how this file names a literal the client prints.
    assert "`findable`" not in skill
    assert "`hidden`" not in skill
    # ⛔ AND THE ROW THAT ANSWERS THAT QUESTION NAMES THE TWO WORDS THAT ARE PRINTED.
    row = [ln for ln in skill.splitlines()
           if "which of my computers are findable?" in ln]
    assert len(row) == 1, row
    assert "`public` or `private`" in row[0], row[0]


def test_every_confirm_gated_verb_is_in_all_three_enumerations():
    """⛔⛔ 7.9-2 ESTABLISHED THAT A SKILL.md ROW IS NOT ENOUGH — three lists have
    to agree. `install` was in `_NL_CONFIRMS` and in the handoff list and in
    NEITHER "Confirm before" list, and one of those lists ends "everything else
    runs on a clear request". The invariant was already violated at HEAD and the
    existing parametrised guard only covered the three 7.9-3 verbs."""
    skill = _SKILL.read_text(encoding="utf-8")
    handoff = skill[skill.index("run the REAL command it described"):][:400]
    safe = skill[skill.index("**Safe defaults:**"):][:600]
    safety = skill[skill.index("## Safety"):][:900]
    for verb in sorted(sr._NL_CONFIRMS):
        base = verb.split()[0]
        assert base in handoff, (verb, "handoff list")
        assert base in safe, (verb, "Safe defaults list")
        assert base in safety, (verb, "Safety bullet")
