"""#708 — Step 3A (tools "+" menu) has a composer-scoped detector + diagnostic.

The precise aria-label selectors matched NOTHING on every prod run
(backend.log: "Step 3A FAIL" x100%), so Research never enabled via DOM and
setup_claude_dr always returned False → the CUA fallback fired needlessly on
every run. The CUA fallback proved the real control is the composer's "+"
button. Step 3A now: (1) precise selectors, (2) a composer-scoped "+" detector
that skips the model/send buttons, (3) on total failure, a one-shot dump of the
composer buttons so the next E2E pins the exact selector. Source-inspection.
"""
import inspect

import research


def test_step3a_has_composer_scoped_plus_detector():
    src = inspect.getsource(research.setup_claude_dr)
    assert "composer-plus" in src, (
        "Step 3A must fall back to a composer-scoped '+' detector when the "
        "precise tools-menu selectors miss (#708)."
    )
    # The detector must NOT pick the model selector or the send button.
    assert "isModel" in src and "isSend" in src, (
        "the '+' detector must exclude the model-selector and send buttons so "
        "it doesn't re-open the model popover or fire Send (#708)."
    )


def test_step3a_plus_detector_never_clicks_page_wide():
    """Review blocker: if no composer is found, the detector must bail rather
    than fall back to document.body and risk clicking a sidebar "+"/menu."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "if (!ce) return null;" in src, (
        "the '+' detector must return null (and let the diagnostic dump + CUA "
        "fallback handle it) when no composer editor is found — never click "
        "page-wide (#708 review blocker)."
    )
    assert "never document.body" in src, (
        "the '+' detector scope must stay inside the composer subtree, never "
        "the whole document (#708 review blocker)."
    )


def test_step3a_dumps_composer_buttons_on_failure():
    src = inspect.getsource(research.setup_claude_dr)
    assert "composer-button dump" in src, (
        "on Step 3A total failure, setup_claude_dr must dump the composer "
        "buttons so the exact tools-menu selector can be pinned from a real "
        "run instead of guessed (#708)."
    )
