"""The three access-setting outcomes must be distinguishable in the log.

Before this, `_set_nlm_public_and_get_link` had TWO silent failure shapes and one
misleading success:

  * the "Notebook access" control was not found at all → the helper skipped
    straight to reading the link, logging NOTHING about access. The run shipped a
    link with no hint that access had never been touched.
  * the dropdown opened but no "Anyone with the link" option matched → it logged
    "Set Notebook access to 'Anyone with the link'" ANYWAY, because that line sat
    after the click with no check on the result.

Both end with a link that may be PRIVATE — which downstream means the Phase-5
email and Google Doc hand the recipient "Request access" instead of a notebook.
`public_verified` cannot distinguish them (it is False in every case, and has been
False on every run in the corpus), so the log is the only place the difference can
live, and it is what the self-heal shadow observation will be read against.
"""
from __future__ import annotations

import asyncio

import research


class _Keyboard:
    async def press(self, key):
        return None


class _AccessPage:
    """Scripted page for the access-setting half of the share dialog."""

    def __init__(self, *, control_found: bool, option_found: bool):
        self.keyboard = _Keyboard()
        self._control_found = control_found
        self._option_found = option_found

    async def query_selector(self, sel):
        return None

    async def evaluate(self, js, arg=None):
        if "notebook access" in js:
            return "opened" if self._control_found else ""
        if "anyone with the link" in js and "opt.click()" in js:
            return "selected" if self._option_found else ""
        if "isNb(val)" in js:
            return ""
        if "PHRASE" in js:
            return False
        if "'save'" in js:
            return "saved"
        return ""


def _run(page, caplog):
    orig_sleep = asyncio.sleep

    async def _no_sleep(_s, *a, **k):
        return None

    asyncio.sleep = _no_sleep
    try:
        return asyncio.run(research._set_nlm_public_and_get_link(page, "NotebookLM"))
    finally:
        asyncio.sleep = orig_sleep


def test_a_missing_access_control_is_reported_not_silent(capsys):
    _run(_AccessPage(control_found=False, option_found=False), None)
    out = capsys.readouterr().out
    assert "could not find the 'Notebook access' control" in out
    assert "may be private" in out
    assert "Set Notebook access to 'Anyone with the link'" not in out, (
        "a control that was never found must not log as if access was set"
    )


def test_an_opened_dropdown_with_no_matching_option_is_not_reported_as_success(capsys):
    _run(_AccessPage(control_found=True, option_found=False), None)
    out = capsys.readouterr().out
    assert "no 'Anyone with the link' option was found" in out
    assert "may be private" in out
    assert "Set Notebook access to 'Anyone with the link'" not in out, (
        "the success line used to fire whether or not the option was clicked — "
        "a restructured option list read as a success in the log"
    )


def test_a_real_access_change_still_logs_the_success_line(capsys):
    _run(_AccessPage(control_found=True, option_found=True), None)
    out = capsys.readouterr().out
    assert "Set Notebook access to 'Anyone with the link'" in out
    # Neither ACCESS-setting warning may fire. The separate
    # "Public share NOT DOM-verified — returned link may be private" line is
    # expected here and is a different signal: access was set, but the strict
    # own-text read could not CONFIRM it. Conflating the two is what made the
    # old log unreadable.
    assert "could not find the 'Notebook access' control" not in out
    assert "no 'Anyone with the link' option was found" not in out


def test_the_three_outcomes_produce_three_different_messages(capsys):
    """The point of the change: a log reader can tell them apart. If two shapes
    collapse to the same line, the next incident cannot be diagnosed from logs —
    which is exactly what happened here."""
    seen = set()
    for control, option in ((False, False), (True, False), (True, True)):
        _run(_AccessPage(control_found=control, option_found=option), None)
        # ACCESS-setting lines only — the shared "NOT DOM-verified" line fires in
        # all three cases and would mask the differences we are pinning.
        lines = [ln for ln in capsys.readouterr().out.splitlines()
                 if "Notebook access" in ln or "Anyone with the link" in ln]
        seen.add(" | ".join(sorted(lines)))
    assert len(seen) == 3, f"expected 3 distinct log shapes, got {len(seen)}"
