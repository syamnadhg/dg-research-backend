"""The Gemini model menu's ADVERT rule — ported, keyed on the plan, shipped dark.

⭐⭐ THE FINDING THIS CLOSES. The Claude ranker excludes sales chips; the Gemini
ranker never had the rule at all (`models.pick_highest_model`'s own docstring
said so in as many words). A Gemini row that names the family, parses a version
AND carries an upgrade verb — "Try 4.0 Flash with Google AI Ultra" — survives the
`reject` list (no "pro", no "lite", no "deep think"), outranks every genuine row
on version, gets CLICKED, opens a billing surface over the composer, and returns
truthy, so the run reports a successful model pick into a modal.

⭐⭐ AND THE OBVIOUS PORT WOULD HAVE MATCHED NOTHING. `is_upsell` looks for a
sales verb followed by a NOUN inside 24 characters, and the two vendors put a
different noun there:

    Claude   "Upgrade to Opus"                → verb, then the FAMILY word
    Gemini   "Upgrade to Google AI Ultra …"   → verb, then the PLAN name

Copying Claude's rule across means asking for "upgrade" followed by "flash"
inside the window. Google's copy does not produce that, so the guard would read
as shipped and catch nothing. `test_the_family_keyed_rule_is_the_no_op` is the
whole item in one assertion.

⚠ SHIPPED IN SHADOW. Gemini has no `free_family`: when a guard bins every Flash
row the run does not error, it proceeds on whatever the dropdown defaulted to —
and Gemini Pro Deep Research is the 1-2h hang the Flash family choice exists to
avoid. The nouns are read off our own pre-flight blocker regex, not off a
captured menu, so the ranker SCORES every row and the caller LOGS the verdict
without acting on it. Both halves are tested here; flipping `upsell_shadow` is
the whole of enforcement.

⚠ The ranker is browser JS, so every ranking assertion below RUNS IT under node
via the DOM shim rather than reading its source. The one lesson this repo keeps
re-learning is that a source pin cannot see a gutted branch.
"""
import inspect

import pytest

import models
import research
from _domshim import el, js_constant, run_js


# ── Fixtures: a Gemini model menu, as the vendor renders one ─────────────────
#
# Row text is title+description CONCATENATED — `parse_family_version` documents
# that shape and the ranker's own comments rely on it, so the fixtures below are
# built the same way rather than as tidy one-word labels.

GENUINE_ROWS = [
    "3.6 FlashFast all-round help",
    "3.5 FlashOlder, still quick",
    "3.6 Flash-LiteFastest answers",
    "3.6 ProComplex reasoning",
]

# The sales rows. Each names a PLAN after an upgrade verb, which is the shape
# the rule keys on. The first is the dangerous one: it also names the family AND
# parses a version, so it competes on rank with every genuine row and wins.
ADVERT_VERSIONED = "Try 4.0 Flash with Google AI Ultra"
ADVERT_PLAIN = "Upgrade to Google AI Ultra"
ADVERT_ADVANCED = "Get Gemini Advanced"
# The row that separates the two noun choices: one sales verb, the plan right
# after it, and the family word 46 characters further along — inside the window
# for the plan, far outside it for the family. Deliberately free of a second
# verb ("unlock the new 4.0 Flash" would put one back within range of "flash"
# and hide the difference).
ADVERT_FAR = "Upgrade to Google AI Ultra — includes the newest 4.0 Flash"


def _menu(labels, *, trigger_text=""):
    """A Gemini dropdown: an open [role=menu] of rows, plus the trigger button.

    The trigger lives OUTSIDE the menu, which is how the ranker tells them
    apart, and it names the current model exactly as the live UI does.
    """
    rows = [el("div", {"role": "menuitem", "w": "280", "h": "44",
                       "x": "300", "y": str(120 + i * 44)}, text=t)
            for i, t in enumerate(labels)]
    kids = [el("div", {"role": "menu", "w": "300", "h": "400",
                       "x": "300", "y": "110"}, kids=rows)]
    if trigger_text:
        kids.insert(0, el("button", {"w": "160", "h": "36", "x": "40", "y": "20"},
                          text=trigger_text))
    return el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, kids=kids)


def _rank(labels, *, nouns=None, drop=False, trigger_text="",
          pin=None, below=None, do_click=True):
    """Run the SHIPPED ranker JS over `labels` and return its result dict."""
    out = run_js(_menu(labels, trigger_text=trigger_text),
                 js_constant(research, "_GEMINI_FLASH_RANK_JS"),
                 {"below": below, "doClick": do_click, "pin": pin,
                  "fam": "flash", "reject": models.reject_terms("gemini"),
                  "triggerText": trigger_text,
                  "nouns": models.upsell_nouns("gemini") if nouns is None else nouns,
                  "verbs": list(models.UPSELL_VERBS),
                  "upsellWindow": models.UPSELL_WINDOW,
                  "dropUpsell": drop})
    return out.get("ret") or {}


# ── 1. The defect, reproduced against the shipped ranker ─────────────────────


def test_a_versioned_sales_row_beats_every_genuine_row_today():
    """The live behaviour: shadow mode leaves the advert row winning."""
    got = _rank([ADVERT_VERSIONED, *GENUINE_ROWS])
    assert got["clicked"] is True
    assert got["version"] == 4.0
    assert "google ai ultra" in got["pick"]


def test_the_reject_list_does_not_absorb_it():
    """Why the existing guard is not enough: no reject term appears in the row."""
    assert not models.reject_matches(ADVERT_VERSIONED.lower(),
                                     models.reject_terms("gemini"))


# ── 2. ⭐⭐ Keying on the FAMILY word — the port that would have shipped dead ──


def test_the_family_keyed_rule_is_the_no_op():
    """Claude's noun choice, applied to Google's copy, matches nothing.

    This is the item. Both sales rows below are unambiguous adverts and the
    family-keyed rule sees neither, because Google puts the PLAN next to the
    verb and the model name — when the row carries one — further along.
    """
    for row in (ADVERT_PLAIN, ADVERT_ADVANCED):
        assert models.is_upsell(row.lower(), "flash") is False
    assert models.is_upsell_any(ADVERT_PLAIN.lower(),
                                models.upsell_nouns("gemini")) is True
    assert models.is_upsell_any(ADVERT_ADVANCED.lower(),
                                models.upsell_nouns("gemini")) is True


def test_the_family_keyed_rule_still_leaves_the_dangerous_row_clicked():
    """And on the one row it DOES catch, catching it is not what saves the run.

    "Try 4.0 Flash with Google AI Ultra" happens to put the family close enough
    to the verb for the family-keyed rule to fire — so a reader could conclude
    the Claude port was sufficient. It is not: driven through the ranker with
    the family as the noun, the two plan-only adverts stay unscored, and the
    scan that decides whether to enforce would report one row instead of three.
    """
    got = _rank([ADVERT_VERSIONED, ADVERT_PLAIN, ADVERT_ADVANCED, *GENUINE_ROWS],
                nouns=["flash"])
    assert len(got["adverts"]) == 1
    plan = _rank([ADVERT_VERSIONED, ADVERT_PLAIN, ADVERT_ADVANCED, *GENUINE_ROWS])
    assert len(plan["adverts"]) == 3


# ── 3. The rule, enforced ────────────────────────────────────────────────────


def test_enforcing_drops_the_sales_row_and_takes_the_real_winner():
    got = _rank([ADVERT_VERSIONED, *GENUINE_ROWS], drop=True)
    assert got["clicked"] is True
    assert got["version"] == 3.6
    assert got["pick"].startswith("3.6 flash")
    assert got["advertPick"] is False


def test_enforcing_does_not_touch_a_genuine_row_whose_blurb_says_advanced():
    """The documented reason bare "advanced" is NOT one of the nouns.

    A Flash row describing itself is not a sales prompt, and this platform has
    no fallback family — a rule that bins the last Flash row leaves the run on
    Gemini Pro Deep Research, which is a multi-hour hang rather than an error.
    """
    row = "3.6 FlashTry our advanced reasoning on everyday questions"
    got = _rank([row], drop=True)
    assert got["clicked"] is True
    assert got["version"] == 3.6
    assert got["adverts"] == []


def test_a_row_is_scored_before_reject_so_the_measurement_is_not_hollow():
    """Most of Google's sales copy names a plan containing "pro".

    Scoring after `rejected()` would report zero adverts for a menu full of
    them, and zero is exactly the number that would be read as "the rule found
    nothing, leave it in shadow".
    """
    got = _rank(["Upgrade to Google AI Pro for 3.6 Flash", *GENUINE_ROWS])
    assert got["adverts"] == ["upgrade to google ai pro for 3.6 flash"]
    # …and it is still not clicked, because reject bins it first.
    assert got["advertPick"] is False


# ── 4. Shadow mode does not change what is clicked ───────────────────────────


def test_shadow_scores_the_winner_without_dropping_it():
    got = _rank([ADVERT_VERSIONED, *GENUINE_ROWS], drop=False)
    assert got["advertPick"] is True
    assert got["version"] == 4.0


def test_the_two_modes_pick_differently_on_the_same_menu():
    """A single assertion that shadow is not enforcement wearing a flag."""
    menu = [ADVERT_VERSIONED, *GENUINE_ROWS]
    assert _rank(menu, drop=False)["version"] != _rank(menu, drop=True)["version"]


def test_the_ranker_bounds_what_it_ships_back():
    """A sample, not a transcript — this crosses the page.evaluate boundary."""
    got = _rank([f"Upgrade to Google One plan {i}" for i in range(12)])
    assert len(got["adverts"]) == 8


def test_the_ranker_does_not_truncate_the_plan_phrase():
    row = "Upgrade to Google AI Ultra for the newest 4.0 Flash and more"
    assert _rank([row])["adverts"] == [row.lower()]


def test_no_nouns_means_no_rule_at_all():
    """An empty noun list must not silently fall back to the family word."""
    got = _rank([ADVERT_VERSIONED, *GENUINE_ROWS], nouns=[], drop=True)
    assert got["adverts"] == []
    assert got["version"] == 4.0


# ── 5. The ported matcher agrees with its Python definition ──────────────────
#
# `is_upsell_any` IS the definition; the JS is a hand port. These drive the same
# strings through both and require the same answer, which is the only thing that
# keeps a port from becoming a second opinion.

AGREEMENT_ROWS = [
    ADVERT_VERSIONED,
    ADVERT_PLAIN,
    ADVERT_ADVANCED,
    "Upgrade to Google AI Ultra",
    "3.6 FlashFast all-round help",
    "3.6 FlashTry our advanced reasoning",
    "Get more from Google One with the new plan",
    "unlock google ai ultra",
    "subscribe to google one",
    # ⭐ Whitespace classes the two languages disagree about. The window is
    # counted in CHARACTERS on the collapsed string, so the run has to be
    # LONGER THAN THE WINDOW for the collapse to change the answer — a
    # single-character separator is collapsed to itself and both sides agree
    # whether or not either one collapses. Mutation found that: a fixture with
    # one \x85 between verb and noun killed nothing.
    #   ﻿ — JS's own \s matches it, Python's str.isspace() does not
    #   \x85, \x1c — Python's str.isspace() matches them, JS's \s does not
    "Upgrade" + "﻿" * 30 + "Google AI Ultra",
    "Upgrade" + "\x85" * 30 + "Google AI Ultra",
    "Upgrade" + "\x1c" * 30 + "Google AI Ultra",
    "Upgrade﻿to﻿Google AI Ultra",
    "Upgrade\x85to\x85Google AI Ultra",
    "Upgrade\x1cto\x1cGoogle AI Ultra",
    # Verb boundaries: "gettysburg" is not "get".
    "Gettysburg address with Google AI Ultra",
    # Window: the noun is far past 24 characters after the verb.
    "Upgrade your workflow with something else entirely — Google AI Ultra",
]

@pytest.mark.parametrize("row", AGREEMENT_ROWS)
def test_the_js_port_answers_exactly_as_the_python_definition(row):
    nouns = models.upsell_nouns("gemini")
    want = models.is_upsell_any(row.lower(), nouns)
    got = _rank([row], drop=True)
    # The ranker records a row in `adverts` exactly when its port said upsell.
    assert bool(got["adverts"]) is want, row


# ── 6. Policy ────────────────────────────────────────────────────────────────


def test_only_gemini_carries_an_advert_rule():
    assert models.upsell_nouns("gemini")
    assert models.upsell_nouns("claude") == []
    assert models.upsell_nouns("chatgpt") == []


def test_bare_advanced_is_not_a_noun_but_the_plan_name_is():
    nouns = models.upsell_nouns("gemini")
    assert "advanced" not in nouns
    assert "gemini advanced" in nouns


def test_every_noun_is_lowercase_and_stripped():
    """They are compared against a lowercased, collapsed row on both sides."""
    for n in models.upsell_nouns("gemini"):
        assert n == n.lower().strip()
        assert n


def test_the_rule_ships_in_shadow_today():
    assert models.upsell_shadow("gemini") is True


def test_shadow_defaults_true_for_a_platform_that_forgot_to_say(monkeypatch):
    monkeypatch.setitem(models.P2_MODEL_POLICY, "made_up",
                        {"upsell_nouns": ["some plan"]})
    assert models.upsell_shadow("made_up") is True


def test_shadow_is_false_for_a_platform_with_no_nouns():
    """Nothing to shadow — and the caller reads this as "no rule", not "enforce"."""
    assert models.upsell_shadow("chatgpt") is False


def test_an_explicit_false_turns_the_rule_on():
    """Flipping one word is the whole of enforcement — pinned so it stays so."""
    saved = models.P2_MODEL_POLICY["gemini"]["upsell_shadow"]
    models.P2_MODEL_POLICY["gemini"]["upsell_shadow"] = False
    try:
        assert models.upsell_shadow("gemini") is False
    finally:
        models.P2_MODEL_POLICY["gemini"]["upsell_shadow"] = saved


# ── 7. is_upsell_any ─────────────────────────────────────────────────────────


def test_any_noun_matching_is_enough():
    assert models.is_upsell_any("upgrade to google one", ["nope", "google one"])


def test_no_nouns_is_false_not_a_default_noun():
    assert models.is_upsell_any("upgrade to opus", []) is False
    assert models.is_upsell_any("upgrade to opus", None) is False


def test_empty_text_is_false():
    assert models.is_upsell_any("", ["google ai"]) is False


def test_the_window_is_honoured():
    row = "upgrade " + ("x" * 30) + " google ai"
    assert models.is_upsell_any(row, ["google ai"]) is False
    assert models.is_upsell_any(row, ["google ai"], window=60) is True


def test_the_noun_must_follow_the_verb():
    """"Google AI Ultra — upgrade for more usage" is a row with a sales tail."""
    assert models.is_upsell_any("google ai ultra, upgrade for more usage",
                                ["google ai"]) is False


# ── 8. The Python mirror keys on either noun set ─────────────────────────────


def test_pick_highest_model_can_mirror_the_gemini_rule():
    """⭐ The two noun choices must DISAGREE on the same menu, or `sale_nouns`
    could be ignored entirely and this would still pass.

    `ADVERT_FAR` is the shape that separates them: one verb, the plan right
    after it, and the family word 46 characters further along — inside the
    window for the plan, far outside it for the family.
    """
    labels = [ADVERT_FAR, *GENUINE_ROWS]
    rej = models.reject_terms("gemini")
    loose = models.pick_highest_model(labels, "flash", reject=rej,
                                      drop_upsell=True)
    tight = models.pick_highest_model(labels, "flash", reject=rej,
                                      drop_upsell=True,
                                      sale_nouns=models.upsell_nouns("gemini"))
    assert loose["version"] == 4.0        # the family-keyed rule cannot see it
    assert tight["version"] == 3.6        # the plan-keyed rule drops it


def test_sale_nouns_without_the_flag_changes_nothing():
    """`drop_upsell` stays the switch; `sale_nouns` only chooses the noun."""
    labels = [ADVERT_VERSIONED, *GENUINE_ROWS]
    got = models.pick_highest_model(labels, "flash",
                                    reject=models.reject_terms("gemini"),
                                    sale_nouns=models.upsell_nouns("gemini"))
    assert got["version"] == 4.0


# ── 9. What the caller says ──────────────────────────────────────────────────


def _lines(rank, *, live=False, nouns=("google ai",)):
    return research._gemini_advert_lines(rank, live=live, nouns=list(nouns))


def test_nothing_is_said_when_no_rule_is_configured():
    assert _lines({"adverts": ["x"], "advertPick": True}, nouns=[]) == []


def test_nothing_is_said_when_the_ranker_never_ran():
    """`{}` is what an eval error leaves behind.

    Reporting "no sales rows" for a menu that was never read is the same class
    of untruth as a source count of zero that the vendor never gave us.
    """
    assert _lines({}) == []
    assert _lines(None) == []


def test_a_zero_denominator_is_reported():
    lines = _lines({"adverts": [], "advertPick": False})
    assert len(lines) == 1
    assert lines[0][0] == "INFO"
    assert "no row" in lines[0][1]
    assert "shadow" in lines[0][1]


def test_the_sample_carries_the_vendor_copy_back_out():
    lines = _lines({"adverts": ["upgrade to google ai ultra"], "advertPick": False})
    assert "upgrade to google ai ultra" in lines[0][1]
    assert "1 row" in lines[0][1]


def test_the_sample_is_bounded():
    lines = _lines({"adverts": [f"row {i}" for i in range(8)], "advertPick": False})
    assert "row 4" not in lines[0][1]
    assert "8 row(s)" in lines[0][1]


def test_a_clicked_advert_warns_and_says_the_click_stood():
    lines = _lines({"adverts": ["a"], "advertPick": True})
    warn = [m for lvl, m in lines if lvl == "WARN"]
    assert len(warn) == 1
    assert "CLICKED" in warn[0]
    assert "click stood" in warn[0]


def test_enforced_mode_labels_itself_and_a_clicked_advert_is_a_contradiction():
    lines = _lines({"adverts": ["a"], "advertPick": True}, live=True)
    assert "enforced" in lines[0][1]
    warn = [m for lvl, m in lines if lvl == "WARN"]
    assert "disagree" in warn[0]


def test_a_clean_run_never_warns():
    assert all(lvl == "INFO" for lvl, _ in _lines({"adverts": [], "advertPick": False}))


# ── 10. The caller actually logs what the helper returns ─────────────────────
#
# ⭐ The helper is pure and pinned above; `_gemini_select_flash_model` cannot be
# executed here (it needs a live page), so the CONSUMER gets a source pin — the
# one thing a source pin is still good for is proving a call exists at all.


def test_the_selector_calls_both_helpers_and_passes_the_flag():
    body = inspect.getsource(research._gemini_select_flash_model)
    assert "_gemini_advert_rule()" in body
    assert "_gemini_advert_lines(" in body
    assert '"dropUpsell": _gm_advert_live' in body
    assert '"nouns": _gm_nouns' in body


def test_the_rule_helper_is_dark_today():
    nouns, live = research._gemini_advert_rule()
    assert nouns == models.upsell_nouns("gemini")
    assert live is False


def test_the_rule_helper_goes_live_only_when_shadow_is_lifted():
    saved = models.P2_MODEL_POLICY["gemini"]["upsell_shadow"]
    models.P2_MODEL_POLICY["gemini"]["upsell_shadow"] = False
    try:
        assert research._gemini_advert_rule()[1] is True
    finally:
        models.P2_MODEL_POLICY["gemini"]["upsell_shadow"] = saved


def test_no_nouns_can_never_be_live():
    """An empty rule that reads as enforced is worse than no rule at all."""
    saved_n = models.P2_MODEL_POLICY["gemini"]["upsell_nouns"]
    saved_s = models.P2_MODEL_POLICY["gemini"]["upsell_shadow"]
    models.P2_MODEL_POLICY["gemini"]["upsell_nouns"] = []
    models.P2_MODEL_POLICY["gemini"]["upsell_shadow"] = False
    try:
        assert research._gemini_advert_rule() == ([], False)
    finally:
        models.P2_MODEL_POLICY["gemini"]["upsell_nouns"] = saved_n
        models.P2_MODEL_POLICY["gemini"]["upsell_shadow"] = saved_s


def test_an_overlay_cannot_turn_the_rule_on_remotely():
    """⛔ NEITHER KEY IS OVERLAY-SETTABLE, and that is a safety property.

    The overlay exists so a vendor rename can be answered without a release.
    Enforcement is the opposite kind of change: on a platform with no fallback
    family, a rule that bins every row does not error — it leaves the run on
    Gemini Pro Deep Research for hours. Flipping it is a code change that ships
    with the tests above, not a remote switch.
    """
    assert "upsell_nouns" not in models._OVERLAY_LABEL_SCHEMA
    assert "upsell_shadow" not in models._OVERLAY_LABEL_SCHEMA
