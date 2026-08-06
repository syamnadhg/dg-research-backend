"""#708 — Claude Step 1B model-pick never downgrades.

Two prod runs (backend.log 48681/49653) had setup_claude_dr select an older
Opus than the one offered, because (1) the model-selector trigger button (which
shows the CURRENT model) was a candidate and (2) the newer menu item hadn't
rendered when the old "any Opus 4.x" priority ran.

The hardened Step 1B must: scope candidates to the open popover, take the
HIGHEST offered (never downgrade), and poll for the options to render.
Source-inspection guards (the JS runs in a live page; no live browser here).

Rewritten 2026-08-01: never-downgrade used to be a version FLOOR passed into the
picker. It is structural now — "highest offered" cannot be a downgrade, because
nothing else on the menu is higher — and a floor could only ever have rejected
the row that should have won.
"""
import inspect

import research
from conftest import code_only, code_only_deep


def test_step1b_takes_the_highest_offered():
    """Never-downgrade, done structurally. The old guard was `v < floor`; the
    ranking itself now guarantees it, so #708 cannot recur without the ranking
    being broken outright."""
    src = code_only(inspect.getsource(research.setup_claude_dr))
    assert "rank[1] > bestRank[1]" in src, (
        "Step 1B must rank by version and take the highest — that IS the "
        "never-downgrade guarantee (#708)."
    )
    # Version is parsed from the option text, not a brittle substring, so a
    # newer release is picked as the strongest with no code change.
    assert "verOf" in src, "Step 1B should parse the version, not substring-match."
    # The family word comes from policy — the only model identity in the code.
    assert "_claude_family" in src and 'p2_family("claude")' in src


def test_step1b_scopes_to_open_popover_excluding_trigger():
    src = inspect.getsource(research.setup_claude_dr)
    assert '[role="menu"], [role="listbox"], [role="dialog"]' in src, (
        "Step 1B must scope candidates to the OPEN popover so the model-"
        "selector trigger button (which shows the current model) is excluded."
    )


def test_step1b_polls_for_the_option():
    src = inspect.getsource(research.setup_claude_dr)
    assert "_pick_opus_js" in src and "for _attempt in range(8)" in src, (
        "Step 1B must poll for the options to render rather than reading the "
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
    assert "model_ok" in src and "_trigger_has_family" in src, (
        "Step 1 must derive model_ok from whether the trigger names the FAMILY "
        "(#744). A version comparison here is what stranded the account: any "
        "number it is compared against ages out."
    )
    assert ("not re-picked" in src) or ("NOT re-picking" in src), (
        "an already-correct model must be recorded but NOT re-picked (#744)."
    )
    # The model-pick poll must run ONLY when the model is not already correct.
    pick_idx = src.find("_picked = await page.evaluate(_pick_opus_js, _pick_args)")
    assert pick_idx != -1, "the _pick_opus_js poll must still exist."
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
    assert "else await page.evaluate" in src, (
        "the Effort submenu must still be opened via DOM, not left to CUA (#745)."
    )
    assert "'max effort'" in src, (
        "Effort=Max must still be selected via DOM (#745)."
    )
    # The Effort submenu must be opened BEFORE anything nested inside it is
    # touched (selecting an effort radio can collapse the submenu).
    # 2026-08-04: the Effort row is MARKED here and pressed by Playwright, then
    # the submenu is polled for. The old anchor clicked from inside the page and
    # called that "opened" — nine "Max not found" WARNs in the corpus against one
    # success say it never was.
    # 2026-08-05 (review, f3): `_eff_marked` became `_eff_mark`, a dict, so the marker
    # can report the row it chose and the anchor-shaped candidates it refused.
    eff_idx = src.find("_eff_mark = {} if _effort_already_known")
    set_idx = src.find("'max effort'")
    assert eff_idx != -1 and eff_idx < set_idx, (
        "the Effort submenu must open before Max is selected inside it (#745)."
    )


def test_step1b_escapes_before_bailing():
    """#744: a Step 1B miss must dismiss the OPEN popover (Escape) before
    returning False — never strand an open dropdown over the composer."""
    # ⚠ code_only + the LOG call as the anchor. A comment elsewhere in the
    # function now also contains the words "Step 1B FAIL", and a raw-source
    # find() landed on it — the assertion then measured the wrong region.
    src = code_only(inspect.getsource(research.setup_claude_dr))
    # The fail path between the FAIL log and `return False` must press Escape.
    fail_idx = src.find('log(f"[setup_claude_dr] Step 1B FAIL')
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


def test_an_acceptable_model_is_still_checked_for_a_newer_one():
    """2026-07-26 — "acceptable" is not "the latest".

    `model_ok` skipped Step 1B entirely, so once Claude.ai showed an acceptable
    version the picker never opened and a newer flagship was never selected:
    P2 kept running Opus 4.8 through the whole Opus-5 rollout, even though the
    policy says pick "highest". The already-open popover must be probed and a
    STRICTLY higher version selected.
    """
    src = code_only(inspect.getsource(research.setup_claude_dr))
    assert "_probe_opus_js" in src, (
        "an already-acceptable model must still probe the open popover for a "
        "newer one — otherwise the pipeline pins itself forever."
    )
    up = src.find("_probe = await page.evaluate(_probe_opus_js")
    assert up != -1, "the upgrade branch must exist"
    assert "Step 1B* UPGRADE" in src, "an upgrade must be logged when it happens"
    # It must be reached exactly when the model is ALREADY ok (the branch the
    # old code short-circuited), i.e. the else of `if not model_ok`.
    assert src.find("if not model_ok") < up, (
        "the upgrade probe belongs on the already-ok path, not the pick path."
    )


def test_upgrade_only_fires_on_a_strictly_higher_version():
    """The #744 re-click loop must stay dead: an upgrade may never re-select the
    version already showing on the trigger. Strictly-greater is what guarantees
    that structurally, so the comparison must not be a plain >=."""
    src = code_only(inspect.getsource(research.setup_claude_dr))
    assert "_offered > _cur + 0.001" in src, (
        "the upgrade must require a STRICTLY higher version than the trigger "
        "(a >= comparison would re-click the current model and revive #744)."
    )
    # The click itself must go through the single existing picker, so there is
    # exactly one code path that can ever select a model.
    up = src.find("_probe = await page.evaluate(_probe_opus_js")
    assert "_pick_opus_js" in src[up:up + 2500], (
        "the upgrade must select via _pick_opus_js, not a second bespoke clicker."
    )


def test_upgrade_probe_never_breaks_an_acceptable_run():
    """A probe failure is advisory: the model is already >= floor, so a failed
    upgrade must never fail the setup."""
    src = code_only(inspect.getsource(research.setup_claude_dr))
    up = src.find("_probe = await page.evaluate(_probe_opus_js")
    tail = src[up:up + 2900]
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
    import re
    assert not re.search(r"(?:opus|sonnet|claude)\s*\d", line[0], re.I), (
        "progress copy must not pin a model version — it goes stale silently."
    )


# ── invariants that live in the JS, so only a code-shape assertion reaches ──
# them. Both were found by mutation: breaking each one changed nothing that any
# test could see, because the scripted page double returns canned values and
# never executes the script text.

def test_the_probe_requires_a_mounted_menu():
    """⭐ The picker keeps a `document.body` fallback for UIs that use no
    role=menu. The read-only PROBE must NOT: with a body fallback the trigger
    button itself counts as a row, so "the highest offered" comes back equal to
    what is already selected. Harmless when the probe was incidental — but under
    the weekly cadence that answer burns the entire interval's check on a
    popover that simply had not rendered yet."""
    src = code_only_deep(research.setup_claude_dr)
    probe = src[src.find("_probe_opus_js = "):]
    probe = probe[:probe.find('"""', probe.find('"""') + 3)]
    assert "if (!menus.length) return {menu: false" in probe, (
        "the probe must report 'no menu' rather than falling back to the body"
    )
    assert "document.body" not in probe, (
        "a body fallback lets the trigger button masquerade as a menu row"
    )
    # …and the caller must treat a menu-less probe as no answer, not as
    # "nothing newer is offered".
    assert '_probe_saw_menu = bool((_probe or {}).get("menu") and (_probe or {}).get("n"))' in src


def test_the_picker_never_clicks_the_trigger_button():
    """With no floor, every family-named element is an eligible row — including
    the model-selector TRIGGER, which the picker's body fallback can see. Clicking
    it just toggles the popover shut while the picker reports success, so the run
    proceeds believing it selected a model it never touched."""
    src = code_only_deep(research.setup_claude_dr)
    assert "if (trig && norm(t) === trig) continue;" in src, (
        "the picker must skip the element whose text matches the trigger"
    )
    # The trigger text has to actually reach the picker for that to mean anything.
    assert '"triggerText": (_trigger_read or {}).get("trigger_text") or ""' in src, (
        "the guard is inert unless the trigger text is passed into the JS"
    )
