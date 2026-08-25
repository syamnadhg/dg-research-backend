"""The standing module-boundary rule, and the claims the doc makes about it.

⛔⛔ THE RULE LIVED ONLY IN A CLOSED JIRA COMMENT until 2026-08-25. DGOPS-9506
was closed will-not-do on 2026-08-05 with "a new subsystem goes in a new module"
as the compensating control, and nothing in this repository said so — not the
README, not ARCHITECTURE.md, not a test. A rule nobody working here can find is
not a rule, and the reviewer who raised the ticket had no way to check it was
being honoured.

⭐ SO THIS GUARDS THE STRUCTURE, NOT THE ARITHMETIC. Asserting the exact line
count would fail on every commit that touches `research.py`, which trains people
to edit the number without reading the section. What is worth pinning is the
thing the rule is actually about:

  · every module the section names still exists,
  · and no root-level module exists that the section does NOT name.

The second is the one with teeth. Adding a subsystem as a new module now forces
an update to the section that explains why the rule exists — and adding a
subsystem *inside* `research.py` is what the rule forbids in the first place.
The line-count claims are checked only for direction and staleness, which is all
a prose figure can honestly promise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARCH = ROOT / "ARCHITECTURE.md"
README = ROOT / "README.md"
SECTION_TITLE = "## Module boundaries — what may be added to `research.py`"

# ⛔ NOT a subsystem: a fixture-replay tool that only runs by hand. Named here
# so the exclusion is a decision on the record rather than a silent skip.
NOT_A_SUBSYSTEM = {"vision_test.py"}


def _section() -> str:
    text = ARCH.read_text(encoding="utf-8")
    start = text.index(SECTION_TITLE)
    nxt = text.index("\n## ", start + len(SECTION_TITLE))
    body = text[start:nxt]
    # A section that shrank to its own heading would satisfy every `in` check
    # below by containing nothing to contradict them.
    assert len(body) > 1500, "the module-boundaries section has been gutted"
    return body


def _root_modules() -> set[str]:
    return {
        p.name
        for p in ROOT.glob("*.py")
        if p.name != "research.py" and p.name not in NOT_A_SUBSYSTEM
    }


def test_the_rule_is_written_down_where_it_can_be_found():
    body = _section()
    assert "A new subsystem goes in a new module" in body
    # ⛔ AND THE OTHER HALF. Without it the rule reads as advice about new
    # modules rather than a bound on what this file may absorb.
    assert "phase-by-phase flow lands in `research.py`" in body
    # ⛔⛔ IT MUST SAY WHERE IT CAME FROM, and this assertion had to be rewritten
    # because the first version could not see its own subject. It asserted
    # `"DGOPS-9506" in body` and `"will-not-do" in body` — both of which the
    # GROWTH TABLE below satisfies on its own ("when DGOPS-9506 was filed", "at
    # the will-not-do decision"). Deleting the entire provenance sentence left
    # the mutant alive. Anchored on the sentence's own words now.
    assert "only in a closed Jira comment" in body, (
        "the section no longer says the rule was invisible before this — which is "
        "the reason it is written here rather than merely followed"
    )
    assert "A rule nobody reading this repo can find is not a rule" in body
    assert "closed will-not-do" in body


def test_the_decision_can_be_reopened_and_says_when():
    # ⛔ A WILL-NOT-DO WITH NO REVISIT CONDITIONS BECOMES PERMANENT BY OMISSION.
    # Nothing here asserted these existed, so a mutant deleting the whole block
    # survived: the section kept every word of its argument and quietly lost the
    # part that lets the argument expire. The second-engineer condition is the
    # likeliest to come true and the one nobody would think to re-derive.
    body = _section()
    assert "Revisit the decision if any of these becomes true" in body
    assert "A second engineer edits `research.py` regularly" in body
    assert "genuinely separable subsystem" in body
    assert "live end-to-end run stops being the primary verification" in body


def test_a_contributor_is_pointed_at_it_before_they_add_anything():
    # ⛔ THE SECTION IS ONLY REACHABLE IF SOMETHING POINTS AT IT. The repo has
    # no CLAUDE.md by convention — both repos keep agent docs under `.claude/`
    # — so the entry point is the README's own layout listing.
    readme = README.read_text(encoding="utf-8")
    assert "§ Module boundaries" in readme
    assert "a new subsystem goes in a NEW module" in readme


def test_every_module_the_section_names_exists():
    body = _section()
    for module in _root_modules():
        assert f"`{module}`" in body, (
            f"{module} exists but the module-boundaries section never names it — "
            "a subsystem was added without recording why it earned its own module"
        )


def test_no_root_module_is_missing_from_the_section():
    # ⛔⛔ THE ONE WITH TEETH, and the inverse of the test above. The rule's
    # whole point is that a new subsystem becomes a new module; this makes that
    # step visible in review by failing until the section explains the new one.
    body = _section()
    # ⭐ MATCHED ON FILENAMES, and the section was rewritten to make that
    # possible. It listed the subsystems in prose — "model policy, the vision
    # layer, narration" — which no test can line up with `models.py`,
    # `vision.py`, `narrate.py`. A reader could not either.
    claimed = {
        w + ".py"
        for w in re.findall(r"`([a-z_]+)\.py`", body)
        if w != "research" and w + ".py" not in NOT_A_SUBSYSTEM
    }
    unexplained = _root_modules() - claimed
    assert not unexplained, (
        f"root modules the section does not account for: {sorted(unexplained)}"
    )


def test_the_count_the_section_states_is_the_real_count():
    body = _section()
    stated = re.search(r"(\w+) subsystems live in their own modules", body)
    assert stated, "the section stopped saying how many there are"
    words = {"five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    assert words.get(stated.group(1).lower()) == len(_root_modules()), (
        f"the section says {stated.group(1)}, the repo has {len(_root_modules())}"
    )


def test_research_py_is_still_the_overwhelming_majority():
    # The "91%" claim, checked for direction rather than to the decimal: the
    # section's argument depends on this file dominating, and if it ever stopped
    # dominating the whole decision would be worth revisiting.
    big = len((ROOT / "research.py").read_text(encoding="utf-8").splitlines())
    siblings = sum(
        len((ROOT / m).read_text(encoding="utf-8").splitlines()) for m in _root_modules()
    )
    assert big > siblings * 5


@pytest.mark.parametrize("label", ["today (2026-08-25)"])
def test_the_stated_growth_figure_has_not_gone_badly_stale(label):
    """⚠ A FLOOR AND A CEILING, NOT AN EQUALITY.

    An exact assertion would fail on every commit that touches `research.py`,
    and a figure people edit reflexively is worse than no figure. So: the doc
    may never OVERSTATE the size (that would flatter the argument), and it may
    understate it only by so much before the number stops meaning anything.
    """
    body = _section()
    row = re.search(r"\*\*" + re.escape(label) + r"\*\* \| \*\*([\d,]+)\*\*", body)
    assert row, f"the growth table no longer carries a row for {label}"
    doc_says = int(row.group(1).replace(",", ""))
    actual = len((ROOT / "research.py").read_text(encoding="utf-8").splitlines())
    assert doc_says <= actual, (
        f"ARCHITECTURE.md claims {doc_says:,} lines, the file has {actual:,} — "
        "the doc overstates the problem, which is the one direction it must not"
    )
    assert actual - doc_says < 12_000, (
        f"ARCHITECTURE.md says {doc_says:,}, the file is now {actual:,} — "
        f"{actual - doc_says:,} lines of undocumented growth. Re-measure the "
        "table and re-read the revisit conditions; the growth objection is the "
        "part of that section that expires."
    )
