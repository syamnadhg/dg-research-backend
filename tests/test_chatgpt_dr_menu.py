"""#709 — setup_chatgpt_dr Step 2 finds the "Deep research" menu item.

Last E2E (backend-2.log): ChatGPT's + menu opened (Step 1 OK) but Step 2 FAILed
100% on EVERY worker — the run only succeeded when the non-deterministic CUA
fallback happened to recover it. ROOT CAUSE (live "+" dump captured by the
user): "Deep research" is a **role="menuitemradio"** with exact text
"Deep research" and EMPTY aria-label + EMPTY data-testid — but the prior
selector set ('[role="menuitem"], button, div[role="option"]') OMITTED
role="menuitemradio", so the item was never a candidate. The fix puts
menuitemradio in the selector and matches the exact text (role+text is the only
signal); on a miss it dumps the menu items. Source-inspection guards.
"""
import inspect

import research


def test_step2_selector_includes_menuitemradio_role():
    """The real bug: the DR row is a role="menuitemradio", which the prior
    selector set omitted. The fix MUST query that role."""
    src = inspect.getsource(research.setup_chatgpt_dr)
    assert '[role="menuitemradio"]' in src, (
        "Step 2 must include role=\"menuitemradio\" in its selector — that's "
        "the actual role of the Deep research item and the real root cause of "
        "the 100% Step 2 FAIL (#709)."
    )


def test_step2_exact_text_match():
    src = inspect.getsource(research.setup_chatgpt_dr)
    # Exact-match on the clean text (siblings "Create image"/"Web search" are
    # also radios, so a precise === is required, not a loose contains alone).
    assert "=== 'deep research'" in src, (
        "Step 2 must exact-match the 'deep research' text/aria (role+text is "
        "the only signal — aria-label + data-testid are empty) (#709)."
    )


def test_step2_dumps_menu_items_on_failure():
    src = inspect.getsource(research.setup_chatgpt_dr)
    assert "Step 2 menu-item dump" in src, (
        "on Step 2 total failure, setup_chatgpt_dr must dump the menu items "
        "so the exact Deep-research selector can be pinned from a real run "
        "instead of guessed (#709)."
    )
