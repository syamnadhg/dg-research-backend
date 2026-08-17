"""Picking Claude's model CLOSES the popover — and Effort lives inside it.

Proven from a live capture, 2026-08-17. Immediately after the Opus 5 row is
clicked the page has NO open overlay at all and the model trigger is back to
`aria-expanded="false"`. That is the entire content of the WARN this step has
been emitting for weeks:

    Step 1C WARN: Effort control not found (older UI / popover closed?)

The question mark can come off. Everything downstream was searching a popover
that no longer existed, failing to find Effort, warning, and letting the run
continue at whatever effort the newly-selected model happened to default to —
while reporting the model selection as a success. Effort is stored PER MODEL on
this family, so the run right after a model change is exactly the run whose
effort is least likely to be right.

⭐ The same capture also hands over the strongest hooks either platform gives
us: `model-selector-dropdown`, `effort-menu-trigger`, and a test id for every
effort rung. The step's own comment had asked for precisely this — "container
scoping would be the stronger fix; it needs a live claude.ai capture we do not
have" — and an exact id is better than a container.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402

TRIG = research._CLAUDE_MODEL_TRIGGER_TESTID
MARK = research._SR_CLICK_MARK


# ── the option id map ─────────────────────────────────────────────────────────

class TestEffortOptionTestId:
    def test_the_policy_word_max_maps_to_the_captured_id(self):
        assert research._claude_effort_option_testid("max") == "effort-option-max"

    def test_EXTRA_maps_to_xhigh_not_to_extra(self):
        # ⭐⭐ THE TRAP. The captured ids read `low|medium|high|xhigh|max` while the
        # visible labels read `Low / Medium / High / Extra / Max`. The id and the
        # word disagree for exactly one rung — and it is the rung directly below
        # the one we ask for. Deriving the id from the label would address
        # nothing, silently, on the only step where being one rung out matters.
        assert research._claude_effort_option_testid("extra") == "effort-option-xhigh"
        assert research._claude_effort_option_testid("Extra High") == "effort-option-xhigh"

    def test_an_unknown_word_addresses_nothing_rather_than_guessing(self):
        # "" makes the page script skip the id lookup and use its text search.
        # A constructed id would address an element that does not exist and the
        # fallback would never run.
        assert research._claude_effort_option_testid("turbo") == ""
        assert research._claude_effort_option_testid("") == ""
        assert research._claude_effort_option_testid(None) == ""

    def test_it_is_case_and_space_insensitive(self):
        assert research._claude_effort_option_testid("  MAX ") == "effort-option-max"


# ── re-opening the popover ────────────────────────────────────────────────────

class _Page:
    """A page whose trigger opens on a real press, as the live one does."""

    def __init__(self, *, present=True, expanded=False, opens=True):
        self.present, self.expanded, self.opens = present, expanded, opens
        self.presses, self.hovers = [], []

    def _spec(self):
        kids = []
        if self.present:
            kids.append(el("button", {"data-testid": TRIG,
                                      "aria-label": "Model: Opus 5 Max",
                                      "aria-expanded": "true" if self.expanded else "false"}))
        return el("body", {}, kids=kids)

    async def evaluate(self, js, arg=None):
        return run_js(self._spec(), js, arg)["ret"]

    async def hover(self, sel, timeout=None):
        self.hovers.append(sel)

    async def click(self, sel, timeout=None):
        self.presses.append(sel)
        if not self.present:
            raise RuntimeError("no such element")
        if self.opens:
            self.expanded = True


def _reopen(page):
    return asyncio.run(research._claude_reopen_model_popover(page))


class TestReopen:
    def test_a_closed_popover_is_pressed_open_and_verified(self):
        page = _Page(expanded=False)
        assert _reopen(page) is True
        assert page.presses, "the trigger was never pressed"
        assert page.expanded is True

    def test_an_ALREADY_OPEN_popover_is_not_pressed(self):
        # ⛔⛔ The one outcome this helper must never produce. Pressing an open
        # popover CLOSES it — so a helper that pressed unconditionally would
        # create the exact state it exists to repair, on the runs that were fine.
        page = _Page(expanded=True)
        assert _reopen(page) is True
        assert page.presses == [], "pressed an already-open popover, closing it"

    def test_a_press_that_does_not_open_it_is_reported_as_failure(self):
        # "The click did not throw" is not "the popover is open". This is the
        # equivalence this repo has spent three waves removing.
        page = _Page(expanded=False, opens=False)
        assert _reopen(page) is False

    def test_a_missing_trigger_is_reported_rather_than_raised(self):
        # A failure here must not lose a run whose model and research tool are
        # both correct — the caller downgrades effort to unconfirmed and goes on.
        page = _Page(present=False)
        assert _reopen(page) is False
        assert page.presses == []

    def test_an_exploding_page_is_survived(self):
        class _Boom:
            async def evaluate(self, js, arg=None):
                raise RuntimeError("target closed")
        assert _reopen(_Boom()) is False


# ── reading whether the effort actually took ──────────────────────────────────

def _checked(rows, *, opt_testid="", word="max"):
    return run_js(el("body", {}, kids=[el("div", {"role": "menu"}, kids=rows)]),
                  research._CLAUDE_EFFORT_CHECKED_JS,
                  {"optTestid": opt_testid, "word": word})["ret"]


class TestEffortCheckedRead:
    def _row(self, label, *, checked=False, testid=None):
        attrs = {"role": "menuitemradio",
                 "aria-checked": "true" if checked else "false"}
        if testid:
            attrs["data-testid"] = testid
        return el("div", attrs, label)

    def test_the_test_id_row_is_read_directly(self):
        rows = [self._row("Low", testid="effort-option-low"),
                self._row("Max", checked=True, testid="effort-option-max")]
        out = _checked(rows, opt_testid="effort-option-max")
        assert out == {"found": True, "checked": True, "via": "testid"}

    def test_an_unchecked_row_is_NOT_reported_as_set(self):
        # The whole point of verifying: a press that landed on the right element
        # and changed nothing must read as failure.
        rows = [self._row("Max", checked=False, testid="effort-option-max")]
        out = _checked(rows, opt_testid="effort-option-max")
        assert out["found"] is True and out["checked"] is False

    def test_the_text_fallback_survives_the_icon_ligature(self):
        # ⭐ The glyphs ride on the SELECTED row — which is precisely the row this
        # read has to recognise, so stripping them is load-bearing here and not
        # merely inherited from the picker.
        rows = [self._row("Max", checked=True)]
        out = _checked(rows, opt_testid="")
        assert out["checked"] is True and out["via"] == "text"

    def test_a_row_that_is_not_there_reads_as_not_found(self):
        out = _checked([self._row("Low", checked=True)], opt_testid="")
        assert out == {"found": False, "checked": False, "via": ""}

    def test_data_state_is_honoured_where_aria_checked_is_absent(self):
        # The capture could not settle how the selection is expressed, so both
        # are accepted; dropping either would make a real success read as failure.
        row = el("div", {"role": "menuitemradio", "data-state": "checked"}, "Max")
        assert _checked([row], opt_testid="")["checked"] is True


# ── the caller: the fix is an ORDERING, and ordering is what must be pinned ───

class TestTheStepActuallyReopens:
    """⭐ Pinning the CONSUMER, not just the helper.

    A helper that is correct and never called is the failure mode this repo has
    hit five times in one effort. `setup_claude_dr` is a 900-line async function
    that no unit test can drive end to end, so the call site is pinned in source
    — but on the PROPERTIES that make it the fix, not on its mere presence.
    """

    def _src(self):
        import inspect
        return inspect.getsource(research.setup_claude_dr)

    def test_the_reopen_is_guarded_by_the_model_having_changed(self):
        src = self._src()
        assert "if _model_changed and not _effort_already_known:" in src
        at = src.index("if _model_changed and not _effort_already_known:")
        assert "_claude_reopen_model_popover(page)" in src[at:at + 400]

    def test_it_happens_BEFORE_the_effort_row_is_looked_for(self):
        # ⛔ The whole fix in one ordering. Re-opening after the search would
        # leave the search running against the closed popover exactly as today.
        src = self._src()
        assert (src.index("_claude_reopen_model_popover")
                < src.index('"claude-effort"')), "the re-open must precede the search"

    def test_a_failed_reopen_does_not_claim_the_effort_was_confirmed(self):
        src = self._src()
        at = src.index("_claude_reopen_model_popover")
        window = src[at:at + 900]
        assert "NOT reported as confirmed" in window

    def test_the_verdict_is_DERIVED_from_the_readings(self):
        # ⚠ REWRITTEN after a mutation survivor. The first version asserted that
        # `_CLAUDE_EFFORT_CHECKED_JS` and `_eff_set = None` APPEARED near the
        # press — and a mutant that turned the verification into `if False:` left
        # both strings in place and the test green. Presence of an identifier is
        # not the holding of a condition. Now the verdict comes from a pure
        # function whose polarity is unit-tested, and this pins that the call site
        # feeds it the real readings rather than constants.
        src = self._src()
        at = src.index("_claude_effort_is_set(")
        window = src[at:at + 260]
        for term in ("marked=", "already=", "pressed=", "checked="):
            assert term in window, f"the verdict must be fed {term}"
        assert "checked=_eff_checked" in window, (
            "the verification's ANSWER must reach the verdict, not a constant")
        assert "pressed=_eff_pressed" in window

    def test_the_dead_promise_is_gone_from_the_effort_warnings(self):
        # ⛔ Two sites said "CUA validate will fix". It does not: the ladder's
        # outcome check has no effort term, so it never descends to CUA — and the
        # validator's own prompt forbids touching effort. A comment that names a
        # rescue that cannot happen is worse than no comment.
        src = self._src()
        assert "CUA validate will fix" not in src


class TestEffortVerdict:
    """The four readings, one verdict — the polarity a survivor exposed."""

    def _v(self, **kw):
        base = dict(marked=True, already=False, pressed=True, checked=True)
        return research._claude_effort_is_set(**{**base, **kw})

    def test_pressed_and_checked_is_set(self):
        assert self._v() is True

    def test_ALREADY_selected_needs_no_press_and_no_verification(self):
        # The cost-free correct path. Demanding a press here would click a row
        # that is already the answer — and on some components that toggles it.
        assert self._v(already=True, pressed=False, checked=False) is True

    def test_a_press_that_changed_NOTHING_is_not_set(self):
        # ⛔⛔ The whole point. This is the shape that reported nine successes
        # against a page that had not moved.
        assert self._v(checked=False) is False

    def test_a_press_that_never_landed_is_not_set(self):
        assert self._v(pressed=False) is False

    def test_a_row_that_was_never_found_is_not_set(self):
        # Not found outranks everything: with no row there is nothing to press and
        # nothing that could have been already-selected.
        assert self._v(marked=False) is False
        assert self._v(marked=False, already=True) is False

    def test_checked_alone_without_a_press_is_not_a_claim(self):
        # A stale read from before the press must not stand in for the press.
        assert self._v(pressed=False, checked=True) is False


class TestValidatorPermission:
    """Whether the validator may repair the effort tier, and when."""

    def test_an_unrecorded_platform_gets_the_cheap_read_only_pass(self):
        # ⭐ Defaulting the other way would send the validator into the model
        # popover on every run of every platform to buy nothing.
        assert research._claude_validator_effort_ok(None) is True
        assert research._claude_validator_effort_ok({}) is True

    def test_a_confirmed_effort_keeps_the_submenu_ban(self):
        assert research._claude_validator_effort_ok({"effort": True}) is True

    def test_an_UNCONFIRMED_effort_is_what_grants_permission(self):
        # ⛔ The polarity. Inverted, the validator is told to go fixing on exactly
        # the runs that are already correct, and to stand down on the ones that
        # are not — which is worse than either behaviour applied uniformly.
        assert research._claude_validator_effort_ok({"effort": False}) is False

    def test_the_validator_asks_the_run_rather_than_assuming(self):
        # Pinning the CONSUMER: a correct decision nothing consults is not a fix.
        import inspect
        src = inspect.getsource(research.validate_setup_with_cua)
        assert "_claude_validator_effort_ok(_P2_THINKING_STATE.get(\"claude\"))" in src

    def test_both_CUA_strings_carry_the_same_permission(self):
        # They go to ONE call. A system prompt that forbids the submenu beside a
        # user message that demands it leaves the agent to pick one arbitrarily.
        import models
        import prompts
        for ok in (True, False):
            sysp = prompts.claude_validate_setup_prompt("Opus", effort_ok=ok)
            user = models.p2_claude_validate_directive("Opus", effort_ok=ok)
            bans = "DO NOT try to expand" in sysp
            assert bans is ok, (ok, "system prompt disagrees with the permission")
            asks = "Effort submenu" in user and "choose" in user
            assert asks is (not ok), (ok, "user message disagrees with the permission")
