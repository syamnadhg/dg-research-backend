"""#708 — Claude Step 1B model-pick never downgrades to Opus 4.7.

Two prod runs (backend.log 48681/49653) had setup_claude_dr select
"Opus 4.7 Extra" instead of "Opus 4.8 Max" because (1) the model-selector
trigger button (which shows the CURRENT model) was a candidate and (2) the
4.8 menu item hadn't rendered when the old "any Opus 4.x" priority ran.

The hardened Step 1B must: scope candidates to the open popover, version-gate
to Opus >= 4.8 (never downgrade), and poll for the option. Source-inspection
guards (the JS runs in a live page; no live browser in unit tests).
"""
import inspect

import research


def test_step1b_version_gates_to_floor():
    src = inspect.getsource(research.setup_claude_dr)
    # The numeric guard that forbids picking sub-floor Opus must be present.
    # The floor is now policy-driven (p2_floor → models.P2_MODEL_POLICY,
    # default 4.8) and injected into the picker JS as `floor`, so a floor bump
    # touches one place — but the never-downgrade gate itself is unchanged (#708).
    assert "< floor" in src, (
        "Step 1B must version-gate candidates to Opus >= the policy floor so it "
        "never silently selects a lower Opus (#708)."
    )
    assert "p2_floor" in src and "_claude_floor" in src, (
        "the floor must come from the central P2_MODEL_POLICY (p2_floor), not a "
        "hardcoded literal scattered across sites (Phoenix A2)."
    )
    # Version is parsed from the option text, not a brittle '4.8' substring,
    # so a future Opus 4.9/5 is still picked as the strongest.
    assert "verOf" in src, "Step 1B should parse the Opus version, not substring-match."


def test_step1b_scopes_to_open_popover_excluding_trigger():
    src = inspect.getsource(research.setup_claude_dr)
    assert '[role="menu"], [role="listbox"], [role="dialog"]' in src, (
        "Step 1B must scope candidates to the OPEN popover so the model-"
        "selector trigger button (which shows the current model) is excluded."
    )


def test_step1b_polls_for_the_option():
    src = inspect.getsource(research.setup_claude_dr)
    assert "_pick_opus_js" in src and "for _attempt in range(8)" in src, (
        "Step 1B must poll for the 4.8 option to render rather than reading the "
        "dropdown once at a fixed 0.8s mark (#708)."
    )


def test_step1b_no_legacy_any_opus_4x_fallback():
    """The old 'any Opus 4.x' / 'any Opus at all' fallbacks are what grabbed
    the trigger's 4.7 — they must be gone."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "Priority 3: any Opus at all" not in src, (
        "the unconditional 'any Opus' fallback must be removed — it could "
        "select Opus 4.7 (#708)."
    )


# ── #744 — re-click loop / P2-stuck fixes ─────────────────────────────


def test_step1_does_not_repick_already_correct_model():
    """#744/#745: setup_claude_dr reads the model-selector TRIGGER first and,
    when it already shows Opus >= 4.8, must NOT re-pick the model — re-clicking a
    correct option was the loop that wedged P2. The model PICK (the _pick_opus_js
    poll) must be gated behind `if not model_ok:`. (#745 reopened the popover for
    the Effort/Thinking knobs, so the OLD "skip the whole dropdown" contract no
    longer holds — only the model PICK is skipped, never re-clicked.)"""
    src = inspect.getsource(research.setup_claude_dr)
    assert "model_trigger_ver" in src, (
        "Step 1 must read the model-selector trigger version first (#744)."
    )
    assert "model_ok" in src and "model_trigger_ver >= _claude_floor" in src, (
        "Step 1 must derive model_ok from the trigger version vs the policy "
        "floor (#744; floor now from p2_floor, Phoenix A2)."
    )
    assert ("not re-picked" in src) or ("NOT re-picking" in src), (
        "an already-correct model must be recorded but NOT re-picked (#744)."
    )
    # The model-pick poll must run ONLY when the model is not already correct.
    pick_idx = src.find("opus_selected = await page.evaluate(_pick_opus_js, {")
    assert pick_idx != -1, "the _pick_opus_js poll must still exist (now passing {floor, pin})."
    guard_idx = src.rfind("if not model_ok:", 0, pick_idx)
    assert guard_idx != -1, (
        "the model-pick poll must be guarded by `if not model_ok:` so a correct "
        "model is never re-clicked (#744)."
    )


def test_step1_sets_effort_via_dom():
    """#745: Effort=Max is set via DOM, not left to CUA (whose screenshots kept
    collapsing the Effort submenu).

    REVISED 2026-07-30. This used to also assert that the popover opens
    unconditionally — branching on `dropdown_clicked`, never on `model_ok` — so
    the Thinking toggle got re-asserted every run. Opus 5 removed that toggle,
    and the trigger already displays the effort ("Opus 5 Max"), so opening the
    popover when both facts are already known was pure cost: it logged "NOT
    re-picking" and then opened the model menu anyway, and handed the quality
    knobs to the CUA validate layer, which clicked in a second time. Whether the
    popover opens is now a DECISION, and a source-text assertion cannot check a
    decision — `tests/test_claude_popover_skip.py` drives the real coroutine for
    that. What stays here is the DOM-not-CUA structure the ticket asked for.
    """
    src = inspect.getsource(research.setup_claude_dr)
    assert "if dropdown_clicked:" in src, (
        "Step 1A must still branch on dropdown_clicked once it decides to open "
        "the popover (#745)."
    )
    assert "_eff_opened = await page.evaluate" in src, (
        "the Effort submenu must still be opened via DOM, not left to CUA (#745)."
    )
    assert "'max effort'" in src, (
        "Effort=Max must still be selected via DOM (#745)."
    )
    # The Effort submenu must be opened BEFORE anything nested inside it is
    # touched (selecting an effort radio can collapse the submenu).
    eff_idx = src.find("_eff_opened = await page.evaluate")
    set_idx = src.find("'max effort'")
    assert eff_idx != -1 and eff_idx < set_idx, (
        "the Effort submenu must open before Max is selected inside it (#745)."
    )


def test_step1b_escapes_before_bailing():
    """#744: a Step 1B miss must dismiss the OPEN popover (Escape) before
    returning False — never strand an open dropdown over the composer."""
    src = inspect.getsource(research.setup_claude_dr)
    # The fail path between the FAIL log and `return False` must press Escape.
    fail_idx = src.find("Step 1B FAIL")
    assert fail_idx != -1
    tail = src[fail_idx:fail_idx + 700]
    assert 'press("Escape")' in tail and "return False" in tail, (
        "Step 1B FAIL must Escape the dropdown before `return False` (#744)."
    )


def test_step1b_selector_handles_menuitemradio_and_fixed_popover():
    """#744: the option picker must see role=menuitemradio/div options (the
    #709 lesson) and use getClientRects() so a fixed-position popover (whose
    offsetParent is null) is not filtered out."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "menuitemradio" in src, (
        "the picker must include role=menuitemradio options (#744)."
    )
    assert "getClientRects()" in src, (
        "the picker/trigger-read must use getClientRects() for visibility so "
        "fixed-position popovers aren't filtered by offsetParent (#744)."
    )


def test_already_at_floor_still_upgrades_to_a_newer_opus():
    """2026-07-26 — "at or above the floor" is not "the latest".

    `model_ok` (trigger >= floor) skipped Step 1B entirely, so once Claude.ai
    showed the floor version the picker never opened and a newer flagship was
    never selected: P2 kept running Opus 4.8 through the whole Opus-5 rollout,
    even though P2_MODEL_POLICY says pick "highest". The already-open popover
    must be probed and a STRICTLY higher Opus selected.
    """
    src = inspect.getsource(research.setup_claude_dr)
    assert "_probe_opus_js" in src, (
        "an already-acceptable model must still probe the open popover for a "
        "newer Opus — otherwise the pipeline pins itself to the floor forever."
    )
    up = src.find("Step 1B*: already")
    assert up != -1, "the upgrade branch must exist and be logged"
    # It must be reached exactly when the model is ALREADY ok (the branch the
    # old code short-circuited), i.e. the else of `if not model_ok`.
    assert src.find("if not model_ok") < up, (
        "the upgrade probe belongs on the already-ok path, not the pick path."
    )


def test_upgrade_only_fires_on_a_strictly_higher_version():
    """The #744 re-click loop must stay dead: an upgrade may never re-select the
    version already showing on the trigger. Strictly-greater is what guarantees
    that structurally, so the comparison must not be a plain >=."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "> model_trigger_ver + 0.001" in src, (
        "the upgrade must require a STRICTLY higher version than the trigger "
        "(a >= comparison would re-click the current model and revive #744)."
    )
    # The click itself must go through the single existing picker, so there is
    # exactly one code path that can ever select a model.
    up = src.find("Step 1B*: already")
    assert "_pick_opus_js" in src[up:up + 2500], (
        "the upgrade must select via _pick_opus_js, not a second bespoke clicker."
    )


def test_upgrade_probe_never_breaks_an_acceptable_run():
    """A probe failure is advisory: the model is already >= floor, so a failed
    upgrade must never fail the setup."""
    src = inspect.getsource(research.setup_claude_dr)
    up = src.find("Step 1B*: already")
    tail = src[up:up + 2600]
    assert "except Exception" in tail, "the upgrade probe must be wrapped"
    assert "return False" not in tail, (
        "an upgrade failure must NOT abort setup — the current model is already "
        "acceptable and the run should proceed."
    )


def test_progress_copy_does_not_pin_a_model_version():
    """The canned P2 progress line hardcoded "Opus 4.8" while the runtime picks
    the highest offered — so it misreported the model for the entire rollout."""
    line = [s for s in research.AGENT_PHASE_FLOWS.get(("claude", 2), [])
            if "Opening Claude" in s]
    assert line, "the claude P2 progress hint must still exist"
    assert "4.8" not in line[0], (
        "progress copy must not pin a model version — it goes stale silently."
    )
