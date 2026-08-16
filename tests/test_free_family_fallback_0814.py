"""Non-pro Claude: when the plan excludes the family, run the FALLBACK family.

THE BUG THIS CLOSES. On a Claude account whose plan does not include Opus, every
Opus row in the model menu is a sales chip. Wave 1 taught the picker to refuse
those chips — correctly — and the consequence was that Step 1B found nothing
clickable, `setup_claude_dr` returned False, and the run went out on whatever the
menu happened to be defaulting to. That default was Sonnet, so the OUTPUT looked
plausible; what was actually happening was:

  * the model was never chosen, it was inherited;
  * Step 1C never ran, so **effort was never set to Max** — the reasoning lever
    on this family — because the FAIL branch returns before it;
  * the CUA fallback then ran on every such run, and its mission said "open the
    model menu and pick the HIGHEST Opus it offers", pointing the agent at the
    only Opus-shaped things on the page: the chips.

⭐ THE SIGNAL IS THE DOM, NOT A TIER VERDICT. "Family rows are present and ALL of
them are sales chips" is read straight off the open menu and cannot disagree with
itself. The Phase-0 tier check is a CUA opinion that fails OPEN ("unsure ⇒ assume
Pro"), so it can raise the pro_required card but must never be what selects a
model. The user reaches this state through that card's "Continue with Free"
action; what makes the run correct afterwards is this DOM read, on every setup.

⛔ AND IT IS NOT PURELY ADDITIVE. Three readers assert on the family and would
each undo a deliberate fallback pick: the pre-send re-activation check (which
would read the correct model as "mode regressed" and re-run the whole setup
before EVERY send), the two CUA missions (whose validate rung would re-click the
chips), and the known-good ledger (which is a version, and a version means
nothing without its family). All three are pinned below.

DIRECTION RULE, same as the chip guard's: falling back when we should not have
costs a downgrade to a model that still works; NOT falling back when we should
have costs every run on that account. But treating "no family rows at all" as a
plan limit would hide a real rollout regression behind a silent downgrade — so
the detection requires chips to be POSITIVELY seen, never inferred from absence.
"""
import ast
import asyncio
import inspect
import pathlib
import re

import pytest

import models
import prompts
import research

from test_claude_popover_skip import (  # noqa: E402  (shared page double)
    _EFFORT_SUBMENU_MARK,
    _PICK_OPUS_MARK,
    _POPOVER_OPEN_MARK,
    _PROBE_MARK,
    ScriptedPage,
    _isolated_overlay,  # noqa: F401  (autouse fixture)
    _no_sleeping,       # noqa: F401  (autouse fixture)
)

_VERSIONED_MODEL = re.compile(
    r"(?:opus|sonnet|haiku|flash|gemini|gpt|claude|o\d)\s*[-–]?\s*\d"
    r"|\d+(?:\.\d+)?\s*(?:pro|flash|opus|sonnet|deep\s*think)",
    re.IGNORECASE,
)


@pytest.fixture(autouse=True)
def _clean_active_family():
    """⛔ The active family is PROCESS state that outlives a call. A test that
    left "sonnet" behind would make the next one assert against a fallback it
    never triggered — and, worse, would make a pro-account regression test pass
    for the wrong reason."""
    research._P2_ACTIVE_FAMILY.clear()
    yield
    research._P2_ACTIVE_FAMILY.clear()


class FreeTierPage(ScriptedPage):
    """A Claude account whose plan excludes Opus.

    The model menu mounts and lists rows, but every Opus row is a sales chip —
    so the picker (which refuses chips) returns nothing for `fam='opus'` while
    the probe reports `n=0, chips>0`. The Sonnet rows are genuine.

    ⚠ `trigger_text` deliberately names Sonnet: that IS what the composer reads
    on such an account, and it is why the validate CUA mission's "only touch the
    model if the button shows Sonnet with no Opus" clause fired on every run.
    """

    def __init__(self, trigger_text="Sonnet 4.6", *, opus_chips=3,
                 sonnet_rows=(4.4, 4.6), **kw):
        super().__init__(trigger_text, **kw)
        self.opus_chips = opus_chips
        self.sonnet_rows = list(sonnet_rows)
        self.picked_family = None
        self.probed_families = []
        self.picked_families = []

    async def evaluate(self, script, arg=None):
        fam = str((arg or {}).get("fam") or "")
        if _PROBE_MARK in script:
            self.scripts.append(script)
            self.probed_families.append(fam)
            if not self.menu_mounts:
                return {"menu": False, "n": 0, "highest": None, "chips": 0,
                        "chipsAny": False}
            if fam == "opus":
                return {"menu": True, "n": 0, "highest": None,
                        "chips": self.opus_chips,
                        "chipsAny": bool(self.opus_chips)}
            rows = self.sonnet_rows
            return {"menu": True, "n": len(rows),
                    "highest": max(rows) if rows else None, "chips": 0,
                    "chipsAny": False}
        if _PICK_OPUS_MARK in script:
            self.scripts.append(script)
            self.picked_families.append(fam)
            if fam == "opus":
                return None            # every Opus row is refused as a chip
            rows = list(self.sonnet_rows)
            # Mirror the JS's never-click-the-trigger rule faithfully: it
            # compares against `triggerText`, which on this path is EMPTY (the
            # trigger read asked about Opus and found none), so nothing is
            # filtered. Hard-coding a filter here instead would hide the fact
            # that the highest Sonnet stays selectable even when it is the one
            # already showing.
            trig = (arg or {}).get("triggerText") or ""
            if trig:
                m = re.search(r"sonnet[^0-9]*([0-9]+(?:\.[0-9]+)?)", trig, re.I)
                if m:
                    rows = [v for v in rows if abs(v - float(m.group(1))) > 0.001]
            # ⚠ HONOUR pin/below, exactly as the base double's own comment
            # demands and for exactly its reason: a double that answers with a
            # canned hit regardless of the arguments makes every filter in the
            # real JS untestable. Measured — without this, the mutant that lets
            # the fallback inherit the FAILED family's version bounds survived,
            # because the double could not feel the bounds at all.
            pin, below = (arg or {}).get("pin"), (arg or {}).get("below")
            if pin is not None and any(abs(v - pin) <= 0.001 for v in rows):
                self._picked = pin
                self.picked_family = fam
                return {"label": f"Sonnet {pin}", "version": pin}
            if pin is not None or below is not None:
                bound = below if below is not None else pin
                rows = [v for v in rows if v < bound - 0.001]
            if not rows:
                return None
            best = max(rows)
            self._picked = best
            self.picked_family = fam
            return {"label": f"Sonnet {best}", "version": best}
        return await super().evaluate(script, arg)


class RenamedFamilyPage(ScriptedPage):
    """The menu mounts, but there are no family rows AND no chips — a rename, a
    rollout difference, or a read taken mid-render. Must NOT be read as a plan
    limit."""

    async def evaluate(self, script, arg=None):
        if _PROBE_MARK in script:
            self.scripts.append(script)
            return {"menu": True, "n": 0, "highest": None, "chips": 0,
                    "chipsAny": False}
        if _PICK_OPUS_MARK in script:
            self.scripts.append(script)
            return None
        return await super().evaluate(script, arg)


def _run(page, **kw):
    return asyncio.run(research.setup_claude_dr(page, **kw))


# ── the policy key ────────────────────────────────────────────────────────

def test_the_fallback_is_a_family_not_a_model():
    """The owner's standing directive, restated for the new key: a family word
    keeps pointing at the newest member forever; a model name is a floor that
    rots in both directions."""
    free = models.p2_free_family("claude")
    assert free == "sonnet"
    assert not any(ch.isdigit() for ch in free), (
        "a version in the fallback pins the account to one model release"
    )
    assert free != models.p2_family("claude")


def test_a_platform_without_a_fallback_reports_none():
    """Gemini's family choice is shaped by a reject list, not a plan tier —
    there is no second family to fall back to, and inventing one would make the
    Gemini picker retry with a word that matches nothing."""
    assert models.p2_free_family("gemini") == ""
    assert models.p2_free_family("chatgpt") == ""


def test_a_fallback_equal_to_the_primary_family_is_no_fallback(monkeypatch):
    """⛔ One typo in the user-editable overlay away. Left honoured, the retry
    re-runs the same picker over the same refused rows: the failure then takes
    two passes and logs a family switch that did not happen."""
    monkeypatch.setattr(models, "p2_labels",
                        lambda p: {"family": "opus", "free_family": "opus"})
    assert models.p2_free_family("claude") == ""


def test_a_regex_metacharacter_in_the_fallback_falls_back_to_the_code_default(monkeypatch):
    """The fallback word reaches the SAME `new RegExp(...)` sites the primary
    does. An unescaped metacharacter would throw inside the browser and take
    model selection down on exactly the accounts that need this path."""
    monkeypatch.setattr(models, "p2_labels",
                        lambda p: {"family": "opus", "free_family": "son(net"})
    assert models.p2_free_family("claude") == "sonnet", (
        "a malformed overlay value must degrade to the code default, not reach "
        "the browser"
    )


# ── the known-good ledger is per family ───────────────────────────────────

def test_a_version_learned_on_one_family_is_not_read_back_on_the_other(monkeypatch, tmp_path):
    """⭐ "4.6" names a real Sonnet and, on the same account, an Opus that may
    never have existed. With one slot per platform, a verified fallback run
    wrote into the slot the primary family's step-back reads — and the single
    retry that path exists to provide would be spent hunting a row that was
    never on the menu."""
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH",
                        tmp_path / "model_refresh.json")
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")

    assert models.record_known_good("claude", 5.0) is True            # primary
    assert models.record_known_good("claude", 4.6, "sonnet") is True  # fallback

    assert models.p2_known_good("claude") == 5.0
    assert models.p2_known_good("claude", "opus") == 5.0, (
        "naming the primary family explicitly must read the SAME slot as "
        "omitting it, or existing on-disk state is stranded"
    )
    assert models.p2_known_good("claude", "sonnet") == 4.6


def test_recording_the_fallback_never_disturbs_the_primary_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH",
                        tmp_path / "model_refresh.json")
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")
    models.record_known_good("claude", 5.0)
    models.record_known_good("claude", 4.6, "sonnet")
    models.record_known_good("claude", 4.4, "sonnet")
    assert models.p2_known_good("claude") == 5.0
    assert models.p2_known_good("claude", "sonnet") == 4.4


# ── the detector: three cases, three answers ──────────────────────────────

class _Probe:
    """A page whose only job is to answer the plan probe, N reads in a row."""

    def __init__(self, *answers, raises=False):
        self._answers = list(answers)
        self._raises = raises
        self.reads = 0

    async def evaluate(self, script, arg=None):
        self.reads += 1
        if self._raises:
            raise RuntimeError("evaluate blew up")
        return self._answers[min(self.reads - 1, len(self._answers) - 1)]


def _limited(page):
    return asyncio.run(research._claude_plan_limited(page, "js", {}))


def test_family_rows_that_are_all_chips_is_a_plan_limit():
    page = _Probe({"menu": True, "n": 0, "highest": None, "chips": 3, "chipsAny": True})
    assert _limited(page) is True


def test_a_menu_with_real_rows_is_never_a_plan_limit():
    """Even WITH chips beside them. A chip next to genuine rows is an upsell on
    an account that already has the family — falling back there is a downgrade
    with no cause."""
    page = _Probe({"menu": True, "n": 2, "highest": 5.0, "chips": 1, "chipsAny": True})
    assert _limited(page) is False


def test_no_rows_and_no_chips_is_not_a_plan_limit():
    """⛔ THE OVER-CORRECTION THIS MUST NOT MAKE. A rename or a rollout
    difference produces exactly this shape, and answering it with a silent
    family switch converts a loud, fixable regression into a permanent quiet
    downgrade — strictly worse than the failure it replaces."""
    page = _Probe({"menu": True, "n": 0, "highest": None, "chips": 0, "chipsAny": False})
    assert _limited(page) is False


def test_an_unmounted_menu_is_not_a_plan_limit():
    page = _Probe({"menu": False, "n": 0, "highest": None, "chips": 0, "chipsAny": False})
    assert _limited(page) is False


def test_a_menu_still_rendering_is_re_read_before_the_verdict():
    """Same reason Step 1B* retries: a menu one beat from finishing its render
    reads as the rename case, and taking that first look as final costs the
    whole run on an account that genuinely cannot select the family."""
    page = _Probe({"menu": False, "n": 0, "highest": None, "chips": 0, "chipsAny": False},
                  {"menu": True, "n": 0, "highest": None, "chips": 2, "chipsAny": True})
    assert _limited(page) is True
    assert page.reads == 2


def test_a_positive_real_row_read_is_answered_immediately():
    """⚠ A NEGATIVE that is already PROVEN must not be re-polled. Waiting cannot
    turn genuine rows into chips, and re-reading a settled menu three times adds
    a second of latency to every ordinary run that reaches this seam."""
    page = _Probe({"menu": True, "n": 3, "highest": 5.0, "chips": 0, "chipsAny": False})
    assert _limited(page) is False
    assert page.reads == 1, "a mounted menu with real rows settles the question"


def test_a_probe_that_raises_is_not_a_plan_limit():
    """Never raises, and an unreadable probe is 'not proved' — which lands on
    the pre-existing behaviour rather than on a family switch."""
    page = _Probe(raises=True)
    assert _limited(page) is False


# ── end to end, through the real coroutine ────────────────────────────────

def test_a_non_pro_account_selects_the_fallback_family_instead_of_failing():
    """⭐ THE HEADLINE. Before this, the same page made setup return False."""
    page = FreeTierPage()
    assert _run(page) is True
    assert page.picked_family == "sonnet"
    assert page.picked() == 4.6, "the HIGHEST fallback row, not merely any"
    assert research._P2_ACTIVE_FAMILY.get("claude") == "sonnet"


def test_the_fallback_run_still_reaches_the_effort_control():
    """⭐ THE PART THAT WAS SILENTLY MISSING. Step 1B's FAIL branch returns
    BEFORE Step 1C, so on every non-pro run the effort lever — the reasoning
    knob on this family — was never touched. Reaching the Effort submenu is the
    whole reason the fallback continues instead of bailing."""
    page = FreeTierPage()
    _run(page)
    assert page.evaluated(_EFFORT_SUBMENU_MARK), (
        "the fallback pick must fall through into Step 1C, or the run gets the "
        "right model at whatever effort it happened to be left on"
    )


def test_the_primary_family_is_tried_first_and_only_then_the_fallback():
    """Order matters: the fallback is a fallback. Probing or picking the
    fallback first would downgrade any account that does have the family."""
    page = FreeTierPage()
    _run(page)
    assert page.picked_families[0] == "opus"
    assert "sonnet" in page.picked_families
    assert page.picked_families.index("opus") < page.picked_families.index("sonnet")


def test_the_fallback_pick_is_not_filtered_by_the_trigger_text():
    """⚠ The trigger read asked about the EXCLUDED family and found none, so
    `trigger_text` is empty and the never-click-the-trigger rule is inactive on
    this path. That is what lets the highest fallback row be selected even when
    it is the one already displayed — filtering it out would pick the next one
    down, a downgrade produced by a guard."""
    page = FreeTierPage(trigger_text="Sonnet 4.6", sonnet_rows=(4.4, 4.6))
    _run(page)
    assert page.picked() == 4.6


def test_a_renamed_family_still_fails_loudly_instead_of_downgrading():
    """⛔⛔ THE REGRESSION THIS FIX MUST NOT INTRODUCE. No family rows and no
    chips is a rename or a rollout difference. Answering it with a family switch
    would give every affected run a quiet downgrade and remove the only signal
    that something needs fixing."""
    page = RenamedFamilyPage("Sonnet 4.6")
    assert _run(page) is False
    assert "claude" not in research._P2_ACTIVE_FAMILY
    assert ("key", "Escape") in page.events, (
        "the FAIL path must still dismiss the popover it opened"
    )


def test_a_pro_account_never_reaches_the_fallback():
    """The whole pro path, unchanged. The trigger names the family, so the
    fallback branch is not even considered."""
    page = ScriptedPage("Opus 5 Max")
    assert _run(page) is True
    assert "claude" not in research._P2_ACTIVE_FAMILY
    assert not page.evaluated(_POPOVER_OPEN_MARK)


def test_a_pro_account_whose_menu_carries_chips_stays_on_the_primary_family():
    """An upsell chip beside genuine rows ("Try Opus 6") is normal on a paid
    account. The detector requires n == 0, so it cannot fire here."""
    page = FreeTierPage("Opus 4.8", opus_chips=2)

    async def _probe_with_real_rows(script, arg=None):
        fam = str((arg or {}).get("fam") or "")
        if _PROBE_MARK in script:
            page.scripts.append(script)
            page.probed_families.append(fam)
            return {"menu": True, "n": 2, "highest": 5.0, "chips": 2, "chipsAny": True}
        return await FreeTierPage.evaluate(page, script, arg)

    page.evaluate = _probe_with_real_rows
    _run(page)
    assert "claude" not in research._P2_ACTIVE_FAMILY
    assert "sonnet" not in page.picked_families


def test_once_the_fallback_is_recorded_the_run_stops_re_probing_the_primary():
    """A second setup pass in the SAME run (the pre-send re-activation, or the
    step-back) starts from the family this run already proved. Re-deriving it
    every time would re-open the popover and re-ask a question the account has
    already answered permanently."""
    first = FreeTierPage()
    _run(first)
    assert research._P2_ACTIVE_FAMILY.get("claude") == "sonnet"

    second = FreeTierPage()
    _run(second)
    # It does not even PICK on the second pass — the trigger already names the
    # fallback family, so #744's never-re-click rule applies and the pass goes
    # through the read-only upgrade probe instead. What matters is that neither
    # the probe nor the picker is ever pointed at the excluded family again.
    assert "opus" not in second.probed_families + second.picked_families, (
        f"the second pass re-asked about the excluded family: "
        f"probed={second.probed_families} picked={second.picked_families}"
    )
    assert second.probed_families == ["sonnet"]


def test_the_learned_version_belongs_to_the_family_that_was_picked():
    """`_P2_PICKED_VERSION` feeds the known-good ledger and the step-back pin.
    On a fallback run it must carry the FALLBACK version, never the primary
    family's trigger read."""
    page = FreeTierPage()
    _run(page)
    assert research._P2_PICKED_VERSION.get("claude") == 4.6


# ── the run-scoped state itself ───────────────────────────────────────────

def test_the_active_family_defaults_to_the_policy_family():
    assert research._p2_active_family("claude") == models.p2_family("claude")


def test_a_family_the_policy_does_not_name_degrades_to_the_policy_family():
    """Stale process state from a policy edit must not be interpolated into the
    pickers as a word that no longer means anything."""
    research._P2_ACTIVE_FAMILY["claude"] = "haiku"
    assert research._p2_active_family("claude") == models.p2_family("claude")


def test_the_active_family_is_wiped_at_every_run_entry():
    """⛔⛔ THE WORST FAILURE THIS CODE CAN HAVE. The worker is long-lived and
    runs jobs sequentially. Without the wipe, ONE visit from a non-pro account
    teaches the process a fallback family that every LATER run inherits —
    including runs signed into a Pro account, which would then be steered onto
    the fallback with model selection reporting complete success. A permanent
    silent downgrade, triggered by a single unrelated run."""
    src = inspect.getsource(research.run_pipeline)
    assert "_P2_ACTIVE_FAMILY.clear()" in src, (
        "the run-entry cross-run wipe is missing — a non-pro run would poison "
        "every subsequent pro run in this worker process"
    )


# ── the three couplings ───────────────────────────────────────────────────

def test_the_pre_send_check_asserts_on_the_family_this_run_is_on():
    """⛔ The reader that made the fallback non-additive. `hasExtended` means
    "the trigger names the family we are supposed to be on". Asked about the
    primary family on a fallback run it is False for a perfectly correct
    composer, so the branch reads "mode regressed" and re-runs the ENTIRE Claude
    setup before every single send, forever."""
    src = inspect.getsource(research.ensure_deep_mode_active)
    claude_leg = src[src.index('if platform_l == "claude":'):]
    assert "_p2_active_family(\"claude\")" in claude_leg
    assert 'p2_family("claude")' not in claude_leg, (
        "the Claude leg still reads the POLICY family somewhere"
    )


def test_the_pre_send_check_re_reads_the_family_after_re_activating():
    """The setup it just ran is what DISCOVERS a plan limit, so on the first
    pass of a non-pro run the family it settled on is newer than the one read a
    moment earlier — and re-checking with the stale word reports the fix it just
    made as still broken."""
    src = inspect.getsource(research.ensure_deep_mode_active)
    after_setup = src[src.index("await setup_claude_dr(page)"):]
    assert "_cl_family = _p2_active_family(" in after_setup, (
        "the family must be re-read after the re-activation, not just the state"
    )


def test_the_ladder_outcome_probe_asserts_on_the_family_this_run_is_on():
    src = inspect.getsource(research._dr_outcome_state)
    assert "_p2_active_family(\"claude\")" in src
    assert 'p2_family("claude")' not in src


def test_the_step_back_pin_and_the_ledger_are_both_family_scoped():
    """A version is meaningless without its family — in BOTH directions. Reading
    the pin from the wrong slot spends the single retry on a row that was never
    on the menu; writing into the wrong slot plants that value for a later run
    on the other family."""
    src = pathlib.Path(research.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = {"p2_known_good": [], "record_known_good": []}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in calls:
            calls[node.func.id].append(node)
    for name, nodes in calls.items():
        assert nodes, f"{name} is no longer called from research.py"
        for node in nodes:
            assert len(node.args) >= 2 if name == "p2_known_good" else len(node.args) >= 3, (
                f"{name} at line {node.lineno} is called without a family"
            )


@pytest.mark.parametrize("render", [
    lambda f: models.p2_claude_setup_directive(f),
    lambda f: models.p2_claude_validate_directive(f),
    lambda f: prompts.claude_deep_research_prompt(f),
    lambda f: prompts.claude_validate_setup_prompt(f),
])
def test_every_claude_cua_mission_can_be_told_the_run_switched_families(render):
    """All four reach the model menu, and all four ran with "Opus" frozen in.
    The validate pair mattered most: its rule is "only touch the model if the
    button does not name <fam>", which on a fallback run fires on the CORRECT
    model and sends the agent into the menu the DOM layer just refused."""
    text = render("sonnet")
    assert "Sonnet" in text
    assert "does not include Opus" in text, (
        "the mission must say what the Opus chips MEAN, or an agent that finds "
        "nothing else Opus-shaped keeps hunting and the chip is still the most "
        "Opus-looking thing on the page"
    )
    assert "sales prompt that opens a billing page" in text, (
        "and it must be the SWITCHED-FAMILY sentence, not the generic chip "
        "warning: that one ends 'leave the model exactly as it is and move on', "
        "which flatly contradicts a mission whose job is to go select a "
        "different family"
    )
    assert not _VERSIONED_MODEL.search(text), (
        f"a model version leaked into the fallback render: {text!r}"
    )


@pytest.mark.parametrize("render,default", [
    (models.p2_claude_setup_directive, lambda: models.p2_claude_setup_directive()),
    (models.p2_claude_validate_directive, lambda: models.p2_claude_validate_directive()),
    (prompts.claude_deep_research_prompt, lambda: prompts.PROMPT_CLAUDE_DEEP_RESEARCH),
    (prompts.claude_validate_setup_prompt, lambda: prompts.PROMPT_VALIDATE_CLAUDE_SETUP),
])
def test_the_default_render_is_unchanged_for_a_pro_account(render, default):
    """⚠ The pro path must be byte-identical. Naming the primary family
    explicitly and omitting it are the same request, and neither may pick up the
    "we switched families" sentence."""
    assert render("") == default()
    assert render(models.p2_family("claude")) == default()
    assert "sales prompt that opens a billing page" not in default(), (
        "the pro render must not pick up the switched-family sentence"
    )


def test_the_validate_mission_no_longer_fires_on_a_correct_fallback_model():
    """⛔⛔ THE CLAUSE THAT UNDID THE FIX. Step 1 used to name Sonnet/Haiku as
    the wrong-model examples — true only while the target is Opus. On a fallback
    run it read "if the button shows Sonnet with no Sonnet at all", which is
    satisfied by the correct model."""
    p = prompts.claude_validate_setup_prompt("sonnet")
    assert "Sonnet/Haiku" not in p
    assert 'does not name "Sonnet" anywhere at all' in p


def test_the_system_prompt_and_the_directive_agree_on_the_family():
    """They go to ONE CUA call. A family that reaches only one of them leaves
    the agent holding two instructions that disagree about which model is
    correct — the coin-flip the family-only rewrite already produced once."""
    for fam in ("", "sonnet"):
        sys_p = prompts.claude_deep_research_prompt(fam)
        user_d = models.p2_claude_setup_directive(fam)
        want = (fam or models.p2_family("claude")).capitalize()
        assert want in sys_p and want in user_d
        other = "Sonnet" if want == "Opus" else "Opus"
        assert f"the model must be {other}" not in sys_p
        assert f"the model must be {other}" not in user_d


def test_the_cua_setup_calls_render_with_the_run_family():
    """The CUA fallback runs precisely when the DOM path failed — including the
    retry that follows a pass which already proved the plan limit."""
    src = pathlib.Path(research.__file__).read_text(encoding="utf-8")
    assert src.count('claude_deep_research_prompt(_p2_active_family("claude"))') == 2, (
        "both Claude CUA setup call sites must render per run"
    )
    assert src.count('p2_claude_setup_directive(_p2_active_family("claude"))') == 2


# ── the Vision hints mirror the prompts ───────────────────────────────────

def test_the_vision_hints_name_the_family_this_run_is_on():
    """The catalog note requires these to agree with the canonical CUA prompts —
    that agreement is what makes the shadow-vs-CUA comparison meaningful. A hint
    saying "Opus" while the prompt says "Sonnet" aims the two calls at different
    elements and poisons the promotion data."""
    research._P2_ACTIVE_FAMILY["claude"] = "sonnet"
    hint = research._sub_claude_family(research._HOTSPOT_VISION_HINTS["validate-setup"])
    assert "Sonnet" in hint["context_hint"]
    assert "{claude_family}" not in hint["context_hint"]
    assert any("Sonnet" in s for s in hint["success_signals"])


def test_substituting_a_hint_never_mutates_the_catalog():
    """It is read once per call. A run that baked its family into the module
    dict would hand it to the next run."""
    research._P2_ACTIVE_FAMILY["claude"] = "sonnet"
    before = research._HOTSPOT_VISION_HINTS["setup-dr"]["context_hint"]
    research._sub_claude_family(research._HOTSPOT_VISION_HINTS["setup-dr"])
    assert research._HOTSPOT_VISION_HINTS["setup-dr"]["context_hint"] == before
    assert "{claude_family}" in before


def test_the_other_placeholder_survives_substitution():
    """⛔ `.replace`, never `.format`. The hints also carry `{label}`, which no
    caller substitutes — a formatter would raise KeyError inside the Vision path
    and turn a wording fix into a crash."""
    hint = research._sub_claude_family(research._HOTSPOT_VISION_HINTS["validate-setup"])
    assert "{label}" in hint["context_hint"]


def test_a_plan_limit_with_nothing_to_fall_back_to_records_nothing():
    """⛔ THE FAMILY IS RECORDED FROM A PICK, NEVER FROM A DIAGNOSIS. The probe
    can prove the plan excludes the primary family and the fallback rows can
    still be unclickable — a menu mid-rotation, a selector miss. Recording the
    family there would tell every later reader in this run to assert on a family
    nothing ever selected, and the pre-send check would then read a correct
    composer as regressed."""
    page = FreeTierPage(sonnet_rows=())
    assert _run(page) is False
    assert "claude" not in research._P2_ACTIVE_FAMILY
    assert "sonnet" in page.picked_families, "the fallback was at least attempted"


def test_a_step_back_that_reaches_the_fallback_drops_the_other_family_bounds():
    """⚠ `pin` and `below` are versions of the family that FAILED. Carried into
    the fallback pick they filter rows of a family they were never measured
    against — "below 4.0" says nothing useful about a Sonnet menu — and the
    likely outcome is no row at all, which is the failure this path exists to
    avoid, reached one step later."""
    page = FreeTierPage()
    assert _run(page, pin_model=4.0, step_below=4.0) is True
    assert page.picked() == 4.6, (
        "the fallback pick must be unbounded — it is a different family, so the "
        "failed family's version bounds do not apply to it"
    )


def test_chips_reported_without_a_mounted_menu_prove_nothing():
    """⛔ THE MOUNTED-MENU REQUIREMENT, tested rather than assumed. A probe that
    has not seen a menu has not seen the account's options — `chips` from such a
    read describes whatever else was on the page, and acting on it would switch
    families off a popover that never rendered. The shipped JS returns
    `chips: 0` alongside `menu: false`, so this shape is defensive; the guard is
    still the thing that makes the rule readable in any order."""
    page = _Probe({"menu": False, "n": 0, "highest": None, "chips": 4, "chipsAny": True})
    assert _limited(page) is False


def test_the_probe_answers_with_the_same_shape_whether_or_not_a_menu_mounted():
    """A caller reading three fields must get three fields on every path. The
    unmounted early return used to omit `chips` entirely — harmless only for as
    long as nobody reordered the rule that reads it."""
    from _domshim import run_js
    from test_model_selection_precision import _claude_probe_js  # noqa: PLC0415
    out = run_js({"tag": "body", "attrs": {}, "text": "", "children": []},
                 _claude_probe_js(), {"fam": "opus"})
    assert set(out["ret"]) == {"menu", "n", "highest", "chips", "chipsAny"}
    assert out["ret"]["menu"] is False and out["ret"]["chips"] == 0
    assert out["ret"]["chipsAny"] is False


def test_the_switched_family_note_says_what_to_USE_not_only_what_to_avoid():
    """⛔⛔ THE CONTRADICTION THAT MUST NOT COME BACK. The generic chip warning
    ends "leave the model exactly as it is and move on" — correct when the
    mission's target IS the family being sold, and the exact opposite of what a
    mission sent to select a DIFFERENT family must do. Naming the family to use
    is the half that makes the two sentences distinguishable; asserting only on
    the shared opening lets one be swapped for the other."""
    for render in (models.p2_claude_setup_directive,
                   models.p2_claude_validate_directive,
                   prompts.claude_deep_research_prompt,
                   prompts.claude_validate_setup_prompt):
        text = render("sonnet")
        assert "Sonnet is the correct model on this account" in text, (
            f"{render.__name__} never tells the agent which family to select"
        )


def test_both_vision_call_sites_substitute_the_family():
    """⭐ THE BLIND SPOT THIS REPO KEEPS HITTING: the helper is pinned, the
    CALLER is not. `_sub_claude_family` has its own tests and they all passed
    while a mutant removed the call from the shadow path entirely — the hint
    then reaches Vision with a literal '{claude_family}' in it. Extracting a
    helper to make something testable does not test it.

    ⚠ Both call sites, because the shadow tier's whole purpose is COMPARING the
    success-path and miss-path reads: substituting one and not the other aims
    them at different models and silently poisons the promotion data."""
    lines = pathlib.Path(research.__file__).read_text(encoding="utf-8").splitlines()
    reads = [i for i, ln in enumerate(lines)
             if "_HOTSPOT_VISION_HINTS.get(hotspot_id" in ln]
    assert len(reads) == 2, f"expected both hint reads, found {len(reads)}"
    for i in reads:
        # Inline on the read, or applied to `_hint` immediately after it. ⛔ NOT
        # "the call appears somewhere in the file" — that phrasing passes for a
        # call site that never got one, which is the whole failure being tested.
        window = "\n".join(lines[i:i + 3])
        assert "_sub_claude_family(" in window, (
            f"the hint read at line {i + 1} is never family-substituted: "
            f"{lines[i].strip()!r}"
        )


# ── against the SHIPPED JS, not the double ────────────────────────────────
#
# ⛔ THE DOUBLE CANNOT EXPRESS THESE. `FreeTierPage` answers the probe from the
# family word alone, so every `chips` value in the tests above is its own
# arithmetic — it can never disagree with production about what a chip IS. These
# drive the real `_probe_opus_js` through the DOM shim, which is the only place
# the counting rule is actually under test.

def _probe_js():
    from _domshim import js_constant  # noqa: PLC0415
    return js_constant(research.setup_claude_dr, "_probe_opus_js")


def _probe_args():
    return {"fam": "opus", "verbs": list(models.UPSELL_VERBS),
            "upsellWindow": models.UPSELL_WINDOW}


def _menu(*rows):
    from _domshim import el  # noqa: PLC0415
    return el("body", {}, "", [el("div", {"role": "menu"}, "", list(rows))])


def test_a_chip_rendered_as_a_plain_div_still_counts_as_a_chip():
    """⭐⭐ MEASURED, NOT REASONED. The row-role filter that stops one chip being
    counted at five depths also made the probe blind to a chip rendered as a
    plain <div> or <li> — both of which ARE in the item walk. `chips` read 0, the
    detector saw no plan limit, and the entire fallback silently did nothing on
    that markup. The verdict now rests on `chipsAny`, which is the FACT rather
    than the number."""
    from _domshim import el, run_js  # noqa: PLC0415
    spec = _menu(el("div", {}, "Upgrade to Opus 5"),
                 el("li", {}, "Try Opus 4.5 with Max"),
                 el("div", {"role": "menuitem"}, "Sonnet 4.6 Balanced"))
    ret = run_js(spec, _probe_js(), _probe_args())["ret"]
    assert ret["n"] == 0
    assert ret["chipsAny"] is True, (
        "a chip with no interactive role is still a chip — a verdict blind to it "
        "turns the whole feature off on markup nobody controls"
    )


def test_a_genuine_pro_menu_reports_no_chip_at_all():
    """The other direction, and the one that must never be wrong: a real menu of
    real rows cannot be read as a plan limit."""
    from _domshim import el, run_js  # noqa: PLC0415
    spec = _menu(el("div", {"role": "menuitem"}, "Opus 5 For complex tasks"),
                 el("div", {"role": "menuitem"}, "Opus 4.5 Previous"),
                 el("div", {"role": "menuitem"}, "Sonnet 4.6 Balanced"))
    ret = run_js(spec, _probe_js(), _probe_args())["ret"]
    assert ret["chipsAny"] is False and ret["n"] == 2 and ret["highest"] == 5


def test_the_row_count_and_the_fact_are_reported_separately():
    """`chips` stays a sensible NUMBER (one per row, not one per nested node)
    while `chipsAny` carries the fact. Collapsing them is what broke it: the
    narrowing that made the count correct made the decision blind."""
    from _domshim import el, run_js  # noqa: PLC0415
    spec = _menu(el("button", {}, "Upgrade to Opus 5"),
                 el("div", {}, "", [el("span", {}, "Try Opus with Max effort")]))
    ret = run_js(spec, _probe_js(), _probe_args())["ret"]
    assert ret["chips"] == 1, "the button is one row, not one per nested node"
    assert ret["chipsAny"] is True, "and the div-wrapped chip is still seen"


def test_the_DECISION_reads_the_fact_not_the_row_count():
    """⭐⭐ THE HELPER IS PINNED, THE CALLER IS NOT — for the fifth time in this
    wave, and the mutation harness caught it again. The probe test above proves
    `chipsAny` is REPORTED for a div-rendered chip; it says nothing about which
    field the verdict reads. Reverting the decision to `chips` left that test
    green while the fallback went back to doing nothing on exactly the markup it
    was fixed for.

    This is the shape the shipped JS returns for a menu whose upsell rows are
    plain divs: the fact is true, the row count is zero."""
    page = _Probe({"menu": True, "n": 0, "highest": None,
                   "chips": 0, "chipsAny": True})
    assert _limited(page) is True, (
        "the verdict must read the FACT a sales prompt was seen, not the "
        "row-attributed count — the count is blind to a chip with no row role"
    )


def test_a_row_count_without_the_fact_is_not_a_plan_limit():
    """The mirror, so the two fields cannot simply be swapped: a count with no
    corroborating fact is a contradiction, and the safe reading of a
    contradiction is 'not proved'."""
    page = _Probe({"menu": True, "n": 0, "highest": None,
                   "chips": 3, "chipsAny": False})
    assert _limited(page) is False
