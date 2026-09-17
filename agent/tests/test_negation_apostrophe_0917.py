"""⛔⛔⛔ THE APOSTROPHE A MAC ACTUALLY TYPES DEFEATED EVERY VETO IN THE ROUTER.

macOS and iOS turn `don't` into `don’t` (U+2019) by default, and SKILL.md tells
the AI to run `sr.py do "<the user's message, verbatim>"` — so the CURLY form is
the spelling the router really receives. The negation vocabulary spelled only
the straight `'`, at `_NEG_WORDS` and again inside `_nl_resolve`'s
`_negated_decide`, so on the spelling a Mac types every negation veto was off.
Measured on the shipped router, the SAME SENTENCE with the two apostrophes:

    `don’t send the logs`             straight: refused   curly: SENT THEM
    `don’t hide my studio pc`         straight: refused   curly: HID IT, unconfirmed
    `don’t make my mac public`        straight: hid it    curly: offered to PUBLISH
    `don’t add device K7XQ-9B2M`      straight: refused   curly: PAIRED IT
    `please don’t switch to the office PC`  straight: refused  curly: SWITCHED
    `don’t approve sam`               straight: refused   curly: "Say yes to “sam”?"

Every case below drives BOTH spellings of one sentence and demands the SAME
answer, so every one of them was RED before the character class landed: the
straight half is the answer the product already gave, the curly half is the one
it did not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SR_PATH = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"


def _load_sr():
    spec = importlib.util.spec_from_file_location("sr_negation_apostrophe_0917", _SR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()

_STRAIGHT = "'"
_CURLY = "’"

# (sentence with `{q}` where the apostrophe goes, the argv it must resolve to —
#  None meaning no command at all, the catch-all).
# ⛔ `don{q}t make my mac public` is the one that is NOT the catch-all: negating a
#    PUBLISH names a concrete act — a hide — while negating a hide names nothing.
#    On the curly spelling it offered to PUBLISH the machine instead.
_NEGATED = [
    ("don{q}t send the logs", None),
    ("i don{q}t want to send the logs", None),
    ("don{q}t hide my studio pc", None),
    ("don{q}t make my mac public", ["device-visibility", "private"]),
    ("don{q}t add device K7XQ-9B2M", None),
    ("please don{q}t switch to the office PC", None),
    ("don{q}t unlink my studio pc", None),
    ("don{q}t ask to use the Lab Mac", None),
    ("don{q}t pause the run", None),
    ("don{q}t resume the Mars run", None),
    ("don{q}t stop the tesla run", None),
    # ⛔⛔ THE DESTRUCTIVE ONES, and the reason this is not cosmetic: a "yes" to
    # any of these confirms hands a stranger somebody else's computer.
    ("don{q}t approve sam", None),
    ("don{q}t allow anyone else to use my computer", None),
    ("shouldn{q}t approve anyone", None),
    # ⭐ These two are the ONLY ones that reach `_negated_decide` — `say yes` is
    #   not in `_ACT_VERBS`, so the general `_NEG_WORDS` veto cannot cover them.
    #   They are what pins the SECOND site; the rest pin the first.
    ("don{q}t say yes to sam", None),
    ("won{q}t say yes to sam", None),
]


@pytest.mark.parametrize("said, argv", _NEGATED)
def test_a_negation_survives_the_apostrophe_a_mac_types(said, argv):
    """⛔⛔ LIVE, not hypothetical — every one of these executed or offered its
    ACT on the curly spelling while refusing it on the straight one."""
    straight = said.format(q=_STRAIGHT)
    curly = said.format(q=_CURLY)
    expected = (argv, None) if argv else (None, [sr._NL_CATCH_ALL])
    assert sr._nl_resolve(straight) == expected, (straight, sr._nl_resolve(straight))
    assert sr._nl_resolve(curly) == expected, (curly, sr._nl_resolve(curly))


# ⛔⛔ THE REASON THE FIX IS A CHARACTER CLASS AND NOT A NORMALISE, PINNED.
# The obvious "simplification" is one line at the top of `_nl_resolve` turning
# every `’` into `'`. It would make every case above pass and it would be WRONG:
# `t` feeds EVERY NAME CAPTURE, so the router would act on a name the owner never
# typed. Measured against that variant: `switch to Sam’s Mac` captures
# "Sam's Mac", which no longer matches the device document, and `hide my Sam’s
# Mac` stops asking and runs an unconfirmed hide on the rewritten name.
# ⭐ HONEST: unlike the cases above, these two pass against today's router. They
#   are not a defect pin — they are what makes that simplification fail loudly.
@pytest.mark.parametrize("said, argv", [
    ("switch to Sam’s Mac", ["device-use", "Sam’s Mac"]),
    ("use Sam’s Mac", ["device-use", "Sam’s Mac"]),
])
def test_a_name_keeps_the_apostrophe_the_owner_typed(said, argv):
    """⛔ Do not 'simplify' the negation fix into a U+2019 -> ASCII normalise."""
    assert sr._nl_resolve(said) == (argv, None), (said, sr._nl_resolve(said))
