"""The NotebookLM share dialog must not call a public link private.

From the 2026-08-04 live run. The notebook was set to "Anyone with the link" at
09:59 and the link copied. Eight minutes later the AUDIO share re-entered the
same helper on the same notebook and logged, in order:

    access dropdown opened but no 'Anyone with the link' option was found
    Public share NOT DOM-verified — returned link may be private
    access was NOT set (control or option not found) — audio link is likely private

Every one of those was about a link that was public and had been verified twice.

Two separate faults produced it:

  * **Nothing was left to click.** The access opener only fires on a control
    reading "Restricted" / "Private" / "not shared", so on a second share of an
    already-public notebook there is by design no option row to select — and the
    helper reported that as a failure. Finding a control already on target is
    the BEST outcome, which is the rule the DOM ledger applies everywhere else.
  * **The strict confirm is not a negative.** `public_verified` is a deliberately
    narrow own-text read that has been False on every run in the corpus, so
    warning on it fired one second after a successful set and said the opposite.

And the warning named neither of the two things it could have been, which is why
this took a log-read to settle rather than a glance.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from _domshim import NODE, el, run_js  # noqa: E402
from test_notebooklm_share_extract import ScriptedPage, _NB  # noqa: E402

needs_node = pytest.mark.skipif(NODE is None, reason="node is required to run page JS")

_PHRASE = "Anyone with the link"


def _dialog(*kids):
    return el("body", {}, "", [el("div", {"role": "dialog"}, "", list(kids))])


# ── the JS, executed ─────────────────────────────────────────────────────────

@needs_node
def test_a_trigger_whose_own_text_reads_public_is_already_public():
    spec = _dialog(el("div", {"role": "combobox"}, _PHRASE))
    out = run_js(spec, research._NLM_ACCESS_DIAG_JS)
    assert out["ret"]["already"] is True
    assert out["ret"]["dialog"] is True
    assert not out["clicks"], "the diagnostic is read-only"


@needs_node
def test_an_open_option_list_inside_the_trigger_is_not_already_public():
    """⭐ The distinction the whole check rests on. A Material dropdown parks its
    open list INSIDE the trigger, so innerText on the trigger contains every
    option — including the one nobody has selected. Reading own text only is
    what stops "the option exists" being mistaken for "the option is chosen"."""
    spec = _dialog(el("div", {"role": "combobox"}, "Restricted", [
        el("div", {"role": "option"}, _PHRASE),
        el("div", {"role": "option"}, "Restricted"),
    ]))
    out = run_js(spec, research._NLM_ACCESS_DIAG_JS)
    assert out["ret"]["already"] is False, (
        "an unselected option row was read as the current value")
    assert out["ret"]["rows"] == 2
    assert _PHRASE in out["ret"]["sample"]


@needs_node
def test_an_aria_selected_row_counts_as_already_public():
    """The other shape: some builds mark the current value on the row rather
    than reflecting it into the trigger's text."""
    spec = _dialog(el("div", {"role": "listbox"}, "", [
        el("div", {"role": "option", "aria-selected": "true"}, _PHRASE),
        el("div", {"role": "option"}, "Restricted"),
    ]))
    assert run_js(spec, research._NLM_ACCESS_DIAG_JS)["ret"]["already"] is True


@needs_node
def test_a_restricted_dialog_reports_what_is_on_screen():
    """The genuine-failure path still has to be diagnosable: how many rows, what
    they say, and what the control currently reads."""
    spec = _dialog(
        el("div", {"role": "combobox"}, "Restricted"),
        el("div", {"role": "listbox"}, "", [
            el("div", {"role": "option"}, "Restricted"),
            el("div", {"role": "option"}, "Only people I choose"),
        ]),
    )
    got = run_js(spec, research._NLM_ACCESS_DIAG_JS)["ret"]
    assert got["already"] is False
    assert got["rows"] == 2
    assert got["access"] == "Restricted"
    assert "Only people I choose" in got["sample"]


@needs_node
def test_no_dialog_is_reported_as_no_dialog():
    """`dialog=NO` is the other cause the old warning could not name: the share
    dialog was never on screen, so the opener aimed at something else."""
    spec = el("body", {}, "", [el("div", {}, "some page chrome")])
    got = run_js(spec, research._NLM_ACCESS_DIAG_JS)["ret"]
    assert got["dialog"] is False
    assert got["already"] is False


@needs_node
def test_an_offscreen_option_row_is_not_counted():
    """Same rule as the audio kebab: NotebookLM parks controls off-canvas, and a
    row nobody can see is not a row that explains anything."""
    spec = _dialog(el("div", {"role": "listbox"}, "", [
        el("div", {"role": "option", "w": "0", "h": "0"}, "Restricted"),
        el("div", {"role": "option"}, "Only people I choose"),
    ]))
    assert run_js(spec, research._NLM_ACCESS_DIAG_JS)["ret"]["rows"] == 1


@needs_node
def test_the_diagnostic_prefers_the_dialog_over_the_whole_page():
    """Scoped, so a stale value elsewhere on the page cannot answer for the
    dialog — the document-wide read is what made the audio kebab destructive."""
    spec = el("body", {}, "", [
        el("div", {"role": "combobox"}, _PHRASE),           # page chrome, not the dialog
        el("div", {"role": "dialog"}, "", [
            el("div", {"role": "combobox"}, "Restricted"),
        ]),
    ])
    got = run_js(spec, research._NLM_ACCESS_DIAG_JS)["ret"]
    assert got["already"] is False, "a control outside the dialog answered for it"
    assert got["access"] == "Restricted"


# ── the Python branch, driven ────────────────────────────────────────────────

def _share(page, label="NotebookLM"):
    """Run the real helper with sleeps and the clipboard neutralised."""
    orig_sleep, orig_clip = asyncio.sleep, research.get_clipboard
    research.get_clipboard = lambda: ""

    async def _no_sleep(_s, *a, **k):
        return None

    asyncio.sleep = _no_sleep
    research._dom_reset()
    try:
        return asyncio.run(research._set_nlm_public_and_get_link(page, label))
    finally:
        asyncio.sleep, research.get_clipboard = orig_sleep, orig_clip


def test_an_already_public_notebook_is_not_reported_as_a_failure(capsys):
    """⭐ The live case: the second share of a notebook this helper made public
    eight minutes earlier. Nothing to click is the BEST outcome, not a miss."""
    page = ScriptedPage(dom_link=_NB, access_option_found=False,
                        access_already_public=True)
    url, verified, access_set = _share(page)
    out = capsys.readouterr().out

    assert access_set is True, "already public IS access set"
    assert url == _NB
    assert "already reads 'Anyone with the link'" in out
    assert "may stay private" not in out and "may genuinely be private" not in out, (
        "a public link was described as possibly private")
    assert "WARN" not in out, f"nothing here needs a warning:\n{out}"


def test_an_already_public_notebook_counts_as_already_in_the_ledger(capsys):
    """The run summary must not read worse for a notebook that was correct on
    arrival — the exact reporting bug the ledger's `already` rule exists for."""
    page = ScriptedPage(dom_link=_NB, access_option_found=False,
                        access_already_public=True)
    _share(page)
    got = [r for r in research._DOM_ATTEMPTS if r["intent"] == "notebooklm.set_public_access"]
    assert [r["outcome"] for r in got] == ["already"]
    assert research._dom_summary()["missed"] == 0


def test_a_genuinely_missing_option_still_warns_and_says_what_was_there(capsys):
    """The other cause must stay loud, and must now be diagnosable in one line."""
    page = ScriptedPage(dom_link=_NB, access_option_found=False,
                        access_already_public=False)
    _, _, access_set = _share(page)
    out = capsys.readouterr().out

    assert access_set is False
    assert "WARN" in out
    assert "dialog=yes" in out, "whether the dialog was even open is half the diagnosis"
    assert "option-rows=2" in out and "Restricted" in out, (
        "the rows that WERE on screen are the other half")
    got = [r for r in research._DOM_ATTEMPTS if r["intent"] == "notebooklm.set_public_access"]
    assert [r["outcome"] for r in got] == ["missed"]


def test_a_successful_pick_is_not_warned_about(capsys):
    """⛔ The strict own-text confirm has been False on every run in the corpus,
    so warning on it fired one second after "Set Notebook access to 'Anyone with
    the link'" and said the opposite. Inconclusive is not negative."""
    page = ScriptedPage(dom_link=_NB, access_option_found=True, public_verified=False)
    _, verified, access_set = _share(page)
    out = capsys.readouterr().out

    assert access_set is True and verified is False
    assert "did not confirm it back" in out
    assert "WARN" not in out, f"the healthy path must not warn:\n{out}"


def test_a_control_that_was_never_found_still_warns(capsys):
    """Access untouched and not already public — this one genuinely may ship a
    private link, and it is the case every other branch must stay quiet for."""
    page = ScriptedPage(dom_link=_NB, access_control_found=False)
    _, _, access_set = _share(page)
    out = capsys.readouterr().out
    assert access_set is False
    assert "NEITHER set nor verified" in out and "WARN" in out


def test_a_failed_link_read_records_the_channel(capsys):
    """`no_dialog` (the opener aimed at nothing) and `no_link_in_dialog` (the
    field moved) need opposite fixes. Recording only "no URL" made the next run
    re-derive which it was."""
    page = ScriptedPage(dom_link="", access_already_public=True,
                        access_option_found=False)
    _share(page)
    got = [r for r in research._DOM_ATTEMPTS if r["intent"] == "notebooklm.copy_share_link"]
    assert got and got[0]["outcome"] == "missed"
    assert "no_link_in_dialog" in got[0]["detail"], got[0]["detail"]
