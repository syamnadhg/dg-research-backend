"""Wave 3 — model-selection precision.

Every failure here is the SAME shape: the pipeline clicks something, the model
does not change, and the run reports a successful pick — then records it as a
learned known-good, so the wrong answer persists past the run that made it.

⭐ These tests EXECUTE the page JS against a DOM double (tests/_domshim.py)
rather than asserting on its source text. That is deliberate and load-bearing:
every one of the defects below (a `break` that skips a tie-break, a regex that
parses only one version order, an element set that is the whole document) is
invisible to a substring assertion, and the repo has been bitten by exactly that
before — a test asserting `"t.length < bestLen" in js` passed against a ranker
whose `break` made that comparison unreachable for the pinned path.

Covers:
  • F09 / F32 — the exact-pin `break` discards the leaf-vs-wrapper tie-break
  • F21       — each parser accepted only its own platform's version order
  • F22       — reject-matching diverged Unicode (python) vs ASCII (browser)
  • F17       — the step-back claimed "vNone" when nothing stepped back
  • F20       — the ChatGPT high-effort marker was matched document-wide
  • the owner's ask: Gemini's "Extended thinking" row must be selected
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models  # noqa: E402
import research  # noqa: E402
from _domshim import NODE, el, evaluate_js, js_constant, run_js  # noqa: E402

needs_node = pytest.mark.skipif(NODE is None, reason="node is required to run page JS")


# ── the JS under test, taken as VALUES (not scraped source) ───────────────
def _claude_pick_js():
    return js_constant(research.setup_claude_dr, "_pick_opus_js")


def _claude_probe_js():
    return js_constant(research.setup_claude_dr, "_probe_opus_js")


def _gemini_rank_js():
    return research._GEMINI_FLASH_RANK_JS


def _gemini_direct_ext_js():
    return js_constant(research._gemini_select_flash_model, "_click_direct_ext_js")


def _gemini_ext_radio_js():
    return js_constant(research._gemini_select_flash_model, "_click_ext_radio_js")


def _gemini_hover_js():
    return js_constant(research._gemini_select_flash_model, "_hover_picked_row_js")


def _p1_confirm_js():
    return evaluate_js(research._chatgpt_extended_pro_confirm, contains="extMark")


def _gem_args(**over):
    args = {"below": None, "doClick": True, "pin": None, "fam": "flash",
            "reject": ["lite*", "deep think", "pro"], "triggerText": ""}
    args.update(over)
    return args


def _claude_args(**over):
    args = {"pin": None, "below": None, "fam": "opus", "triggerText": ""}
    args.update(over)
    return args


# ═════════════════════════════════════════════════════════════════════════
# F09 / F32 — a pinned version must select the LEAF ROW, not its wrapper
# ═════════════════════════════════════════════════════════════════════════
#
# `items` is built in DOCUMENT ORDER, ancestors first, and a menu's own wrapper
# concatenates every row's text — so the first element carrying the pinned
# version is routinely the wrapper. Clicking an ancestor never reaches the row's
# handler, so the model stays put while the caller logs an upgrade, sets
# _model_changed, writes _P2_PICKED_VERSION and (on DR success) records a
# known-good for a version that was never selected.

def _claude_menu_with_wrapper():
    """A claude.ai-shaped popover: one wrapper div around four leaf rows."""
    rows = [
        el("div", {"role": "menuitemradio"}, "Fable 5 For your toughest challenges"),
        el("div", {"role": "menuitemradio"}, "Opus 5 For complex tasks"),
        el("div", {"role": "menuitemradio"}, "Sonnet 5 Most efficient for everyday use"),
        el("div", {"role": "menuitemradio"}, "Haiku 4.5 Fastest for quick answers"),
    ]
    return el("body", {}, "", [
        el("div", {"role": "menu"}, "", [el("div", {"class": "scroll"}, "", rows)]),
    ])


@needs_node
def test_a_pinned_claude_version_clicks_the_row_not_the_wrapper():
    out = run_js(_claude_menu_with_wrapper(), _claude_pick_js(), _claude_args(pin=5.0))
    assert out["ret"] is not None, "the pinned version is on the menu — it must be picked"
    assert out["ret"]["version"] == 5.0
    assert out["clicks"], "nothing was clicked"
    clicked = out["clicks"][-1]
    assert clicked.startswith("Opus 5"), f"clicked {clicked!r}"
    assert "Sonnet" not in clicked, (
        "a wrapper concatenating every row was clicked — the model never changes, "
        "but the caller logs an upgrade and records a known-good")


@needs_node
def test_a_pinned_gemini_version_clicks_the_row_not_the_wrapper():
    """⚠ The wrapper's rows must BOTH survive the reject list, or the wrapper is
    thrown out for containing 'flash-lite' and the wrapper hazard never arises —
    a DOM that quietly makes the test unfalsifiable. The pinned row also has to
    come FIRST, because the wrapper's concatenated text parses to whichever
    version appears earliest in it."""
    rows = [
        el("div", {"role": "menuitem"}, "3.6 Flash All-around help"),
        el("div", {"role": "menuitem"}, "3.5 Flash Older"),
    ]
    spec = el("body", {}, "", [el("li", {}, "", rows)])   # <li> wrapper = a ranker candidate
    out = run_js(spec, _gemini_rank_js(), _gem_args(pin=3.6))
    assert out["ret"]["clicked"] is True
    assert out["ret"]["version"] == 3.6
    clicked = out["clicks"][-1].strip().lower()
    assert clicked == "3.6 flash all-around help", (
        f"clicked {clicked!r} — the wrapper li carries the pinned version in its "
        "textContent, but clicking it never reaches the row")


@needs_node
def test_the_weekly_upgrade_end_to_end_selects_the_row_not_the_wrapper():
    """⭐ THE WHOLE F09 SCENARIO, both halves. Step 1B* probes for the highest
    offered version and then re-enters the picker with that number as the PIN.
    On the owner's captured claude.ai menu the pre-fix pair reported
    `Step 1B* UPGRADE: opus 4.8 -> 5.0`, wrote _P2_PICKED_VERSION and (on DR
    success) recorded a known-good — while the click had landed on the scroll
    wrapper and the account stayed on 4.8."""
    spec = _claude_menu_with_wrapper()
    probe = run_js(spec, _claude_probe_js(), {"fam": "opus"})
    # `chips` rides along on every probe result — it is what tells a plan limit
    # from a rename one layer up. Zero here: this menu offers genuine rows.
    assert probe["ret"] == {"menu": True, "n": probe["ret"]["n"], "highest": 5.0,
                            "chips": 0, "chipsAny": False}
    offered = probe["ret"]["highest"]
    cur = 4.8
    assert offered > cur + 0.001, "the upgrade branch must be the one taken"
    pick = run_js(spec, _claude_pick_js(), _claude_args(pin=offered, below=None))
    assert pick["ret"]["version"] == 5.0
    assert pick["clicks"][-1] == "Opus 5 For complex tasks", (
        f"the upgrade clicked {pick['clicks'][-1][:60]!r} — an element that is not "
        "the row, so the model never changes while the run reports an upgrade")


@needs_node
def test_the_body_fallback_still_picks_when_no_menu_has_mounted():
    """`roots = menus.length ? menus : [document.body]` — the branch taken while
    the popover has not mounted yet (the picker polls 8 times). It had no test,
    so the shim's `document.body` support was itself unexercised."""
    spec = el("body", {}, "", [
        el("button", {}, "Opus 5 Max"),                       # the trigger
        el("div", {}, "", [el("div", {"role": "menuitemradio"}, "Opus 4.8 Older")]),
    ])
    out = run_js(spec, _claude_pick_js(), _claude_args(triggerText="Opus 5 Max"))
    assert out["ret"] is not None, "no menu mounted and nothing was considered"
    assert out["ret"]["version"] == 4.8
    assert out["clicks"][-1] == "Opus 4.8 Older", (
        "the body fallback must still prefer the leaf, and must never click the "
        "trigger — clicking it just shuts the popover while reporting success")


@needs_node
@pytest.mark.parametrize("pick_js_name", ["claude", "gemini"])
def test_the_pin_outranks_a_newer_row_that_the_step_back_also_allows(pick_js_name):
    """⭐ The pin's rank TIER is only observable on the real step-back call, which
    passes pin AND below together: `bound` is then `below`, so rows between the
    pin and the failed version survive the filter and compete. Demote the tier to
    [1, v] and the nearer-to-current row wins — the learned known-good, the one
    version actually PROVEN to reach Deep Research, gets passed over.

    (With `below=None` the filter already drops everything at or above the pin,
    so the tier value is unobservable there — which is why the obvious version of
    this test cannot fail.)"""
    if pick_js_name == "claude":
        labels = ["Opus 4.8 Previous generation", "Opus 4.2 Known good"]
        spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
            el("div", {"role": "menuitemradio"}, t) for t in labels])])
        out = run_js(spec, _claude_pick_js(), _claude_args(pin=4.2, below=5.0))
        want = "Opus 4.2"
    else:
        labels = ["3.5 Flash Previous", "3.2 Flash Known good"]
        spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
            el("div", {"role": "menuitem"}, t) for t in labels])])
        out = run_js(spec, _gemini_rank_js(), _gem_args(pin=3.2, below=3.6))
        want = "3.2 flash"
    ver = out["ret"]["version"] if pick_js_name == "claude" else out["ret"]["version"]
    assert ver == (4.2 if pick_js_name == "claude" else 3.2), (
        f"the pin lost to a newer row: got v{ver}")
    assert out["clicks"][-1].lower().startswith(want.lower()), out["clicks"][-1]


@needs_node
def test_a_retired_pin_still_falls_back_to_the_best_strictly_older_row():
    """The pin-absent fallback must survive the rank-tier rewrite: a learned
    known-good never expires, so weeks later it may simply be gone."""
    rows = [
        el("div", {"role": "menuitemradio"}, "Opus 5 For complex tasks"),
        el("div", {"role": "menuitemradio"}, "Opus 4.8 Previous generation"),
    ]
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", rows)])
    out = run_js(spec, _claude_pick_js(), _claude_args(pin=4.2, below=5.0))
    assert out["ret"]["version"] == 4.8, "no 4.2 row exists — take the best below 5.0"
    assert out["clicks"][-1].startswith("Opus 4.8")


# ═════════════════════════════════════════════════════════════════════════
# F21 — both parsers must read both version orders
# ═════════════════════════════════════════════════════════════════════════
#
# Claude ships family-first ("Opus 5") and Gemini number-first ("3.6 Flash")
# TODAY, so each single-order parser is correct until its OWN vendor renames.
# On that day every row parses as version-less, ranking collapses to the
# "shortest label" tie-break, and the picker selects an older model — a
# downgrade, reported as a success.

CLAUDE_ORDERS = [
    ("family-first (ships today)", ["Opus 5 For complex tasks", "Opus 4.8 Older"]),
    ("number-first (a rename)", ["5 Opus For complex tasks", "4.8 Opus Older"]),
]
GEMINI_ORDERS = [
    ("number-first (ships today)", ["3.6 Flash All-around help", "3.5 Flash Older"]),
    ("family-first (a rename)", ["Flash 3.6 All-around help", "Flash 3.5 Older"]),
]


@needs_node
@pytest.mark.parametrize("label,rows", CLAUDE_ORDERS)
def test_the_claude_picker_reads_either_version_order(label, rows):
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitemradio"}, r) for r in rows])])
    out = run_js(spec, _claude_pick_js(), _claude_args())
    assert out["ret"] is not None, f"{label}: nothing picked"
    assert out["ret"]["version"] == 5.0, f"{label}: parsed {out['ret']['version']}"
    assert "4.8" not in out["clicks"][-1] and "Older" not in out["clicks"][-1], (
        f"{label}: the shortest label won, i.e. the version went unparsed — "
        "that is the downgrade this test exists for")


@needs_node
@pytest.mark.parametrize("label,rows", GEMINI_ORDERS)
def test_the_gemini_ranker_reads_either_version_order(label, rows):
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitem"}, r) for r in rows])])
    out = run_js(spec, _gemini_rank_js(), _gem_args())
    assert out["ret"]["version"] == 3.6, f"{label}: parsed {out['ret']['version']}"
    assert "older" not in out["clicks"][-1].lower(), f"{label}: picked the older row"


@needs_node
@pytest.mark.parametrize("sibling", ["Fable 5", "Fable 5.1", "Fable 4.9"])
def test_a_sibling_family_above_ours_can_never_win_the_pick(sibling):
    """⭐⭐ THE LIVE CLAUDE MENU. backend.log records the open popover as
    `Fable 5, Opus 5, Sonnet 5, Haiku 4.5` — a sibling family immediately ABOVE
    Opus, with title-only rows. The scroll container is a `div`, and `div` is in
    the picker's candidate list, so its textContent (`Fable 5.1Opus 5Sonnet 5…`)
    competes with the rows. Parsing number-first read that as the SIBLING's
    version, which outranks the real Opus leaf outright — the container gets
    clicked, the click never reaches the row, the model stays put, and the caller
    logs an upgrade and records a known-good for a version no Opus row ever had.
    Today `Fable 5` ties with `Opus 5` and the leaf tie-break hides it; the next
    asymmetric bump in either direction exposes it."""
    labels = [sibling, "Opus 5", "Sonnet 5", "Haiku 4.5"]
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"class": "scroll"}, "", [
            el("div", {"role": "menuitemradio"}, t) for t in labels])])])
    args = _claude_args(triggerText="Opus 5 Max")
    pick = run_js(spec, _claude_pick_js(), args)
    assert pick["ret"]["version"] == 5.0, (
        f"read v{pick['ret']['version']} — a sibling family's number was taken "
        "for ours")
    assert pick["clicks"][-1] == "Opus 5", f"clicked {pick['clicks'][-1]!r}"
    probe = run_js(spec, _claude_probe_js(), {"fam": "opus"})
    assert probe["ret"]["highest"] == 5.0, (
        f"the probe offers v{probe['ret']['highest']} — it would pin the picker "
        "to a version that is not on the menu, and record it as known-good")


@needs_node
@pytest.mark.parametrize("rows,want", [
    # A digit in the DESCRIPTION, glued to the title — family-first must not
    # reach across the blurb to find it.
    (["3.6 Flashall-around help, 2x faster", "3.5 Flash Older"], 3.6),
    # ⭐ A digit in the description separated only by PUNCTUATION. "No letters in
    # between" does not exclude a comma, so this row read as version 2 — and the
    # older sibling then won the rank. A downgrade, produced by the adjacency
    # guard that exists to stop one.
    (["3.6 Flash, 2x faster", "3.5 Flash Older"], 3.6),
])
def test_a_number_in_the_description_can_never_become_the_version(rows, want):
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitem"}, r) for r in rows])])
    out = run_js(spec, _gemini_rank_js(), _gem_args())
    assert out["ret"]["version"] == want, (
        f"read v{out['ret']['version']} from a description number")
    assert "older" not in out["clicks"][-1].lower(), (
        f"picked the older row: {out['clicks'][-1]!r}")


@needs_node
@pytest.mark.parametrize("label,rows", CLAUDE_ORDERS)
def test_the_claude_probe_reads_either_version_order(label, rows):
    """The probe is what DECIDES whether the weekly upgrade runs at all. If it
    could not read the renamed order it would report 'nothing newer offered'
    while the picker was perfectly able to select it — the upgrade would simply
    go quiet on the release it exists to catch."""
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitemradio"}, r) for r in rows])])
    out = run_js(spec, _claude_probe_js(), {"fam": "opus"})
    assert out["ret"]["menu"] is True
    assert out["ret"]["highest"] == 5.0, f"{label}: probe read {out['ret']['highest']}"


@pytest.mark.parametrize("text,fam,expected", [
    ("opus 5 for complex tasks", "opus", 5.0),
    ("5 opus for complex tasks", "opus", 5.0),
    ("claude 3 opus", "opus", 3.0),
    ("opus (4.8)", "opus", 4.8),
    ("3.6 flashall-around help", "flash", 3.6),
    ("flash 3.6all-around help", "flash", 3.6),
    ("opus for complex tasks", "opus", None),
    ("opus max", "opus", None),
    # ⭐⭐ THE WRAPPER. claude.ai renders a scroll container around the rows, so
    # its textContent is every label glued together and a SIBLING family's
    # number ends up sitting immediately before ours. Number-first read this as
    # 5.1, which outranks the real `Opus 5` leaf — so the picker clicked the
    # container (changing nothing) and reported an upgrade to a version no Opus
    # row ever had, which `record_known_good` then persisted as the pin target.
    ("fable 5.1opus 5sonnet 5haiku 4.5", "opus", 5.0),
    ("fable 5opus 5sonnet 5haiku 4.5", "opus", 5.0),
    ("fable 4.9opus 5sonnet 5", "opus", 5.0),
    # ⭐ And the reason the ORDER alone is not the fix: family-first must not be
    # allowed to reach across the description to a number in the blurb.
    ("3.6 flashall-around help, 2x faster", "flash", 3.6),
    ("3.5 flash-litefastest answers new3.6 flash all-around help", "flash", 3.5),
    # ⭐ …and the reason "no LETTERS in between" is not enough either: a comma is
    # not a letter, so `3.6 Flash, 2x faster` read as version 2 — a downgrade
    # produced by the very guard meant to prevent one. Only plain separators.
    ("3.6 flash, 2x faster", "flash", 3.6),
    ("5 opus, 2x faster", "opus", 5.0),
    ("opus (4.8)", "opus", 4.8),
])
def test_the_python_mirror_reads_both_orders_adjacently(text, fam, expected):
    assert models.parse_family_version(text, fam) == expected


@pytest.mark.parametrize("text", ["٣ flash", "flash ٣", "flash-٣", "٣flash"])
def test_the_mirror_parses_ascii_digits_only(text):
    """`\\d` is Unicode-aware in python and ASCII in the JS port. A mirror that
    parses a row the browser cannot is not a mirror — and BOTH patterns need the
    ASCII class, or whichever one keeps `\\d` reintroduces the divergence."""
    assert models.parse_family_version(text, "flash") is None


# ═════════════════════════════════════════════════════════════════════════
# F22 — reject-matching parity: python must decide what the browser decides
# ═════════════════════════════════════════════════════════════════════════
#
# The docstring calls reject_matches "THE SINGLE DEFINITION … ported
# character-for-character into the JS". It was not: python used Unicode
# str.isalnum(), the port uses ASCII a-z0-9, and the parity test asserted only
# that the substring "isAlnum" appeared in the JS.

REJECT_ROWS = [
    # (row text, should this row be REJECTED?)
    ("3.6 flashall-around help", False),                 # the row we want
    ("3.5 flash-litefastest answers", True),             # 'lite*' prefix match
    ("3.1 flash pro advanced maths", True),              # 'pro' whole word
    ("3.6 flashboosts your productivity", False),        # 'pro' inside a word
    ("3.1 deep think for hard problems", True),          # multi-word term
    # 'deep think' carries no trailing `*`, so a row that GLUES it to the title
    # keeps its left boundary broken and is accepted. Recorded, not asserted as
    # desirable — it is the concatenation asymmetry the policy comment describes
    # for 'lite*', and both halves of the mirror agree on it.
    ("3.6 flashdeep think sibling", False),
    # ⭐ THE DIVERGENCE, in both boundary directions. A non-ASCII neighbour is
    # alnum to python's str.isalnum() and not to the browser's ASCII isAlnum, so
    # before the fix python ACCEPTED the first row and REJECTED nothing about the
    # second while the browser did the opposite. Both now agree.
    ("3.6 flash pro高度な推論", True),
    ("3.6 flashélite answers", True),
    # A DIGIT is a boundary character on both sides of the mirror. Drop digits
    # from the class and 'pro2' starts matching the whole-word term 'pro'.
    ("3.6 flash pro2 fast", False),
    # 'lite' inside 'elite' has no LEFT boundary. Drop the left check and every
    # elite/satellite/complete row is binned as Flash-Lite.
    ("3.6 flash elite performance", False),
]


@pytest.mark.parametrize("text,rejected", REJECT_ROWS)
def test_python_reject_matches_agrees_with_the_expected_verdict(text, rejected):
    assert models.reject_matches(text, ["lite*", "deep think", "pro"]) is rejected


@needs_node
@pytest.mark.parametrize("text,rejected", REJECT_ROWS)
def test_the_browser_reject_port_agrees_with_python_row_for_row(text, rejected):
    """The SAME rows, through the real ranker. A rejected row is not picked; an
    accepted one is. Run the two halves of the mirror over one table so they
    cannot drift again without a failure."""
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitem"}, text)])])
    out = run_js(spec, _gemini_rank_js(), _gem_args())
    browser_rejected = not out["ret"]["clicked"]
    assert browser_rejected is rejected, (
        f"browser {'rejected' if browser_rejected else 'accepted'} {text!r} but "
        f"models.reject_matches says {'reject' if rejected else 'accept'}")
    assert browser_rejected is models.reject_matches(
        text, ["lite*", "deep think", "pro"])


# ═════════════════════════════════════════════════════════════════════════
# F17 — never claim a step-back that did not happen
# ═════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("picked,failed,expected", [
    (4.8, 5.0, True),        # a real retreat
    (None, 5.0, False),      # ⭐ the reported bug: DR recovered, nothing re-picked
    (5.0, 5.0, False),       # same model — not a step-back
    (5.0, 4.8, False),       # somehow newer — certainly not a step-back
    (4.9999, 5.0, False),    # inside the epsilon
    (4.8, None, False),      # unknown failed version proves nothing
    (None, None, False),
    ("4.8", 5.0, False),     # a string is not a version
    (True, 5.0, False),      # a flag must not read as v1
    (1.0, True, False),
])
def test_stepped_back_to_only_says_yes_for_a_real_retreat(picked, failed, expected):
    assert models.stepped_back_to(picked, failed) is expected


def _step_back_block():
    """The step-back result block, sliced on ANCHORS rather than a byte count:
    `code_only` blanks comments IN PLACE, so a fixed-width window shrinks to
    whitespace the moment the explanation above the code grows."""
    from conftest import code_only
    src = code_only(research.start_agent_no_gemini_wait)
    i = src.index("_stepped_to = _P2_PICKED_VERSION.get(platform_l)")
    j = src.index("record_known_good(platform_l,", i)   # the next CODE, not a comment
    return src[i:j]


def test_the_step_back_notice_is_gated_on_a_proven_retreat():
    block = _step_back_block()
    assert "if stepped_back_to(_stepped_to, _failed_f):" in block, (
        "the drift notice must be gated on the predicate, not emitted whenever "
        "the retry happened to succeed")
    alert = block.index("_emit_model_drift_alert(")
    gate = block.index("if stepped_back_to(")
    assert gate < alert, "the gate must precede the alert it guards"
    assert "recovered without a model change" in block, (
        "the un-stepped case must still be logged — it is the common one")


def test_no_user_facing_copy_interpolates_a_possibly_none_version():
    """`v{_stepped_to}` may only be built where the retreat is proven. A literal
    'vNone' in an amber notice is what this whole finding was."""
    block = _step_back_block()
    assert "v{_stepped_to}" not in block[:block.index("if stepped_back_to(")], (
        "the version is interpolated before it is known to be a version")
    tail = block[block.index("else:", block.index("if stepped_back_to(")):]
    assert "v{_stepped_to}" not in tail, (
        "the un-stepped branch must not name a version it does not have")


# ═════════════════════════════════════════════════════════════════════════
# F20 — the ChatGPT high-effort marker must come from the composer chrome
# ═════════════════════════════════════════════════════════════════════════

# ⭐ From policy, not hand-copied. The production call builds this dict the same
# way (research.py: `{k: p1_words("chatgpt", k) for k in (...)}`), so a frozen
# duplicate here would keep certifying word sets the browser no longer receives —
# the identical "the unit suite certifies what the browser never ran" failure
# this wave fixed one layer down in reject_matches.
P1_WORDS = {k: models.p1_words("chatgpt", k) for k in
            ("tier_words", "thinking_words", "downgrade_words", "upgrade_verbs")}


def test_the_p1_word_sets_used_here_are_the_ones_production_sends():
    assert all(P1_WORDS.values()), "a policy key went empty — the fixtures are inert"
    assert "pro" in P1_WORDS["tier_words"]
    assert {"extended", "reasoning"} <= set(P1_WORDS["thinking_words"])


def _chatgpt_page(sidebar_titles=(), pill_text=None, trigger_text="ChatGPT 5 Auto",
                  sidebar_form=False):
    composer_kids = [el("button", {"data-testid": "model-switcher-dropdown-button"},
                        trigger_text),
                     el("div", {"id": "prompt-textarea", "contenteditable": "true"}, "")]
    if pill_text:
        composer_kids.append(el("button", {"class": "__composer-pill"}, pill_text))
    sidebar_kids = [el("a", {"href": "/c/1"}, t) for t in sidebar_titles]
    if sidebar_form:
        # A search box that comes FIRST in document order — the trap
        # `document.querySelector('form')` walks straight into.
        sidebar_kids.insert(0, el("form", {"class": "search"}, "", [
            el("input", {"placeholder": "Search chats"}, "")]))
    return el("body", {}, "", [
        el("nav", {"class": "sidebar"}, "", sidebar_kids),
        el("form", {}, "", composer_kids),
    ])


@needs_node
def test_a_sidebar_conversation_title_can_no_longer_confirm_extended_pro():
    """⭐ THE REGRESSION. 'Pro reasoning tips' is 18 chars, visible, outside every
    overlay, and carries a thinking word AND a tier word. Under a document-wide
    scan it satisfied the high-effort marker, so a live Instant/Auto mode was
    reported as 'extended' — masking the exact silent downgrade this confirm was
    built to catch, and skipping the caller's one silent re-run."""
    out = run_js(_chatgpt_page(sidebar_titles=["Pro reasoning tips"]),
                 _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasExtended"] is False, (
        f"a page title confirmed the high-effort mode: {out['ret']['extText']!r}")
    assert out["ret"]["hasInstant"] is True, "the trigger reads Auto — a downgrade"


@needs_node
def test_a_real_composer_pill_still_confirms_extended_pro():
    """Scoping must not blind the confirm: the marker where it actually lives —
    the composer's own model/effort pill — still counts."""
    out = run_js(_chatgpt_page(pill_text="Extended Pro"), _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasExtended"] is True
    assert "extended pro" in out["ret"]["extText"].lower()


@needs_node
def test_the_marker_still_needs_a_thinking_word_and_a_tier_word():
    """Unchanged by the scoping: a bare tier word in the composer is not proof
    of the high-effort mode, or a future free 'Extended' tier reads as success."""
    out = run_js(_chatgpt_page(pill_text="Pro"), _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasExtended"] is False
    assert out["ret"]["hasPro"] is False, "the trigger says Auto, not Pro"


@needs_node
def test_an_upgrade_cta_in_the_composer_is_not_a_marker():
    """The CTA must carry BOTH word kinds, or the verb guard is never reached and
    the test is decorative — 'Upgrade to Pro' alone has no thinking word, so
    `isMark` is already false and deleting `!hasVerb` changes nothing."""
    out = run_js(_chatgpt_page(pill_text="Try Pro reasoning"), _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasExtended"] is False, (
        "an upgrade pitch naming the tier and the mode confirmed the mode")


@needs_node
def test_an_upgrade_cta_on_the_trigger_is_not_proof_of_the_tier():
    """The same verb guard, on the other consumer: `hasPro` is read off the
    trigger, where 'Upgrade to Pro' is a sales pitch, not a tier."""
    out = run_js(_chatgpt_page(trigger_text="Upgrade to Pro"), _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasPro"] is False


@needs_node
def test_the_composer_is_found_from_the_prompt_box_not_the_first_form():
    """A sidebar search form earlier in document order must not become the
    'composer' — that is the same first-match-in-document-order mistake the
    scoping exists to fix, moved one level up."""
    out = run_js(_chatgpt_page(pill_text="Extended Pro", sidebar_form=True),
                 _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasExtended"] is True, (
        "the sidebar's search form was taken for the composer, so the real "
        "marker was never searched")


@needs_node
def test_a_page_with_no_composer_at_all_reads_unsure_rather_than_guessing():
    spec = el("body", {}, "", [el("nav", {}, "", [el("a", {"href": "/c/1"},
                                                     "Pro reasoning tips")])])
    out = run_js(spec, _p1_confirm_js(), P1_WORDS)
    assert out["ret"]["hasExtended"] is False
    assert out["ret"]["hasPro"] is False and out["ret"]["hasInstant"] is False


# ═════════════════════════════════════════════════════════════════════════
# The owner's ask — Gemini's "Extended thinking" row must be selected
# ═════════════════════════════════════════════════════════════════════════
#
# Captured 2026-08-02: it is a PEER ROW of the model rows in the same menu, so
# there is no "Thinking level" submenu to open and the submenu trigger correctly
# misses. Selection therefore rests entirely on the direct-row branch, which had
# no test — it worked by accident. These pin the captured shape.

def _captured_gemini_menu(rows):
    return el("body", {}, "", [
        el("div", {"class": "cdk-overlay-container"}, "", [
            el("div", {"role": "menu", "class": "mat-mdc-menu-panel"}, "", [
                el("gem-menu-item", {"role": "menuitem"}, r) for r in rows])])])


CAPTURED_ROWS = [
    "3.5 Flash-Lite Fastest answers New",
    "3.6 Flash All-around help",
    "3.1 Pro Advanced maths and code",
    "Extended thinking Complex problem solving",
]


@needs_node
def test_the_captured_extended_thinking_row_is_the_one_clicked():
    out = run_js(_captured_gemini_menu(CAPTURED_ROWS), _gemini_direct_ext_js(), "extended")
    assert out["ret"].startswith("extended thinking"), f"returned {out['ret']!r}"
    assert len(out["clicks"]) == 1
    assert out["clicks"][0].startswith("Extended thinking"), (
        f"clicked a model row instead: {out['clicks'][0]!r}")


@needs_node
def test_a_concatenated_extended_row_still_matches():
    """Menu rows are title+description CONCATENATED, so the wanted row has no
    word boundary after the thinking word. A both-boundaries test would reject
    the very row it is meant to select."""
    out = run_js(_captured_gemini_menu(["Extendedcomplex problem solving"]),
                 _gemini_ext_radio_js(), "extended")
    assert out["ret"] == "extendedcomplex problem solving"


@needs_node
@pytest.mark.parametrize("helper", ["radio", "direct"])
@pytest.mark.parametrize("row", [
    "Standardbest for most questions",           # the low tier
    # ⭐ The low tier NAMING the high one. This is the row the 'standard' guard
    # actually exists for: "Standardbest for most questions" is already excluded
    # by not containing the thinking word at all, so a test using only that row
    # cannot tell whether the guard is there — delete the guard and it still
    # passes. Here the guard is the only thing standing between us and clicking
    # the cheap tier.
    "Standard — faster than extended thinking",
    "Thinking levelextended",                    # the trigger, once already set
    "3.6 Flash All-around help",                 # a model row
])
def test_rows_that_must_not_be_taken_for_the_thinking_choice(helper, row):
    """Both helpers, because they are separate code with the same job — the
    'standard' guard lives in each, and a test that only drove one of them let a
    deleted guard survive."""
    js = _gemini_ext_radio_js() if helper == "radio" else _gemini_direct_ext_js()
    out = run_js(_captured_gemini_menu([row]), js, "extended")
    assert out["ret"] == "", f"{row!r} was clicked by the {helper} helper"
    assert not out["clicks"]


@needs_node
def test_the_direct_branch_refuses_rows_outside_an_open_overlay():
    """Bare page text must never satisfy it — a brief can contain the word."""
    spec = el("body", {}, "", [el("li", {"role": "menuitem"}, "Extended thinking")])
    out = run_js(spec, _gemini_direct_ext_js(), "extended")
    assert out["ret"] == ""


@needs_node
def test_the_thinking_word_comes_from_the_caller_not_a_frozen_literal():
    """Pass a different word and a different row must win — proof the policy
    value is actually used, which a hardcoded /extended/ would fake."""
    rows = ["Extended thinking Complex problem solving", "Ponder deeply About it"]
    out = run_js(_captured_gemini_menu(rows), _gemini_direct_ext_js(), "ponder")
    assert out["ret"].startswith("ponder")
    out_empty = run_js(_captured_gemini_menu(rows), _gemini_direct_ext_js(), "")
    assert out_empty["ret"] == "", "no word means no click, never 'click anything'"


@needs_node
def test_the_hover_follows_the_row_the_ranker_picked():
    """It used to re-decide with its own frozen /\\bflash\\b/ + reject list. It
    now follows the ranker's answer, and prefers the leaf over the wrapper for
    the same reason the ranker does."""
    leaf = el("div", {"role": "menuitem"}, "3.6 flash all-around help")
    spec = el("body", {}, "", [
        # ⚠ The wrapper must be strictly LONGER than the leaf, or the two are
        # indistinguishable by text and the leaf preference cannot be observed.
        el("li", {}, "", [leaf, el("span", {}, " and more")]),
        el("div", {"role": "menuitem"}, "3.5 flash-lite fastest"),
    ])
    out = run_js(spec, _gemini_hover_js(), "3.6 flash all-around help")
    assert out["ret"] == "3.6 flash all-around help"
    # Two events (mouseover + pointerover) land on ONE element; what matters is
    # that only the picked row was ever touched.
    assert set(out["clicks"]) == {"3.6 flash all-around help"}, (
        "the wrapper was hovered, or a non-picked row was")


@needs_node
def test_an_empty_pick_hovers_nothing():
    out = run_js(_captured_gemini_menu(CAPTURED_ROWS), _gemini_hover_js(), "")
    assert out["ret"] == "" and not out["clicks"]


def test_the_gemini_thinking_word_is_read_from_policy():
    from conftest import code_only_deep
    src = code_only_deep(research._gemini_select_flash_model)
    assert '(p2_labels("gemini") or {}).get("thinking")' in src, (
        "the thinking word must come from the same policy key the end-of-leg "
        "advisory reads, or the two halves hunt different words")
    assert 'r"[a-z0-9 ]+"' in src, (
        "the overlay may supply any string and it is interpolated into page JS "
        "— restrict it the way p2_family does")
    assert models.p2_labels("gemini").get("thinking") == "extended"


def test_a_boolean_thinking_overlay_cannot_become_the_search_word(tmp_path, monkeypatch):
    """⛔ The overlay schema admits `thinking` as bool OR str (Claude's entry uses
    it as a flag), so `{"thinking": true}` is a VALID overlay — and `str(True)
    .lower()` is "true", which passes a characters-only guard. Every selector
    would then hunt the word 'true'. A type check is the guard, not the charset."""
    import json as _json
    ov = tmp_path / "model_refresh.json"
    ov.write_text(_json.dumps({"gemini": {"labels": {"thinking": True}}}))
    # ⚠ Patch the module ATTRIBUTE, never reload the module. The overlay path is
    # a constant bound at import, so `importlib.reload` under a monkeypatched env
    # is the only way to move it — and the reload in the teardown runs BEFORE
    # monkeypatch restores the env, so the module stays pointed at the temp file
    # and every later test in the process reads a doctored policy. (Observed: it
    # broke test_model_policy.py two files away.)
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", ov)
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")
    assert models.p2_labels("gemini").get("thinking") is True, (
        "precondition: the schema really does accept a bool here")
    from conftest import code_only_deep
    src = code_only_deep(research._gemini_select_flash_model)
    assert "isinstance(_gm_think_raw, str)" in src, (
        "a non-string policy value must fall back to the code default, not be "
        "stringified into the selector")


# ═════════════════════════════════════════════════════════════════════════
# F31 — no floor strands an account, proved by RUNNING the picker
# ═════════════════════════════════════════════════════════════════════════
#
# test_family_only_selection.py catches a floor written as a comparison against a
# literal. These catch one however it is written — a filter, a rank tier, a
# rejected row — because the only thing asserted is the outcome. That mattered:
# the reviewer's mutation (`if (v !== null && v < 4.8) continue;`) left EVERY
# behavioural test in the wave green, because the Claude page double re-implements
# the picker's contract in Python and never runs the script text.
#
# The stranding is not hypothetical. An account on an older plan sees an older
# menu; a floor there means Step 1B finds nothing, setup returns False, and the
# leg falls to vision for a model that was sitting on the menu the whole time.

@needs_node
@pytest.mark.parametrize("top", ["4.7", "4.5", "3.5"])
def test_a_claude_menu_that_tops_out_on_an_older_opus_is_still_picked(top):
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitemradio"}, f"Opus {top} For complex tasks"),
        el("div", {"role": "menuitemradio"}, "Sonnet 4.6 Most efficient for everyday use"),
        el("div", {"role": "menuitemradio"}, "Haiku 4.5 Fastest for quick answers"),
    ])])
    out = run_js(spec, _claude_pick_js(), _claude_args())
    assert out["ret"] is not None, (
        f"the highest opus offered is {top} and the picker selected nothing — a "
        f"version floor strands every account whose menu stops below it")
    assert out["ret"]["version"] == float(top), f"picked v{out['ret']['version']}"
    assert out["clicks"] and out["clicks"][-1].startswith(f"Opus {top}"), (
        f"clicked {out['clicks'][-1] if out['clicks'] else None!r}")


@needs_node
@pytest.mark.parametrize("top", ["2.5", "3.0"])
def test_a_gemini_menu_that_tops_out_on_an_older_flash_is_still_picked(top):
    spec = el("body", {}, "", [el("div", {"role": "menu"}, "", [
        el("div", {"role": "menuitem"}, f"{top} Flash Fast all-round help"),
        el("div", {"role": "menuitem"}, "2.0 Flash Older"),
    ])])
    out = run_js(spec, _gemini_rank_js(), _gem_args())
    assert out["ret"] is not None and out["ret"]["clicked"], (
        f"the highest flash offered is {top} and the ranker selected nothing")
    assert out["ret"]["version"] == float(top), f"picked v{out['ret']['version']}"
    assert "older" not in out["clicks"][-1].lower(), f"clicked {out['clicks'][-1]!r}"
