"""P3 NotebookLM share extraction — the four structural defects, driven for real.

Every test here calls the REAL `extract_notebooklm_url` coroutine against a
scripted page double. Source-text assertions cannot check any of these: they are
all decisions (does the fallback run? which channel wins? what does `error`
carry?), and the 2026-07-30 post-mortem exists precisely because four gates that
each *looked* right in isolation were wrong as a system.

The defects, from the post-mortem:

  1. HOSTNAME LITERAL — the clipboard held the correct link on every failing run
     and the containment guard `"notebooklm.google.com" in clip` threw it away.
  2. SHARED try/except — the DOM click and the vision fallback lived in ONE try,
     so a CDK-backdrop click timeout jumped past the fallback entirely and the
     attempt degraded straight to the tab URL. The fallback exists for exactly
     that failure and never got to run.
  3. BLANK `error` — never populated, so the one warning that should have named
     this bug rendered "falling back to tab URL: " with nothing after the colon,
     on 35 of 35 occurrences in the corpus.
  4. CUA ASKED TO READ A URL IT CANNOT READ — the mission said "Tell me the EXACT
     URL"; the app has no address bar and no scratch field, so the vision layer
     clicked Copy link at iteration 2 and burned the remaining eight hunting for
     somewhere to paste, while the link sat on the clipboard we can read.
"""
from __future__ import annotations

import asyncio
import inspect
import re

import research
from conftest import code_only


# The share link and the tab URL are DELIBERATELY different notebook ids.
# In production they are the same URL, but a fixture where they match cannot tell
# "the clipboard channel worked" from "the clipboard was rejected and we fell
# back to the tab URL" — the two produce byte-identical results. Verified by
# mutation: with matching fixtures, reverting the clipboard guard to the old
# hostname literal (i.e. re-introducing the outage) passed every test.
_NB = "https://notebook.google.com/notebook/clip-0d028786-66ef-4933-a322-ed66c7b5"
_NB_OLD = "https://notebooklm.google.com/notebook/clip-2300054c-fab9-4080-8e11-5ec"
_TAB_URL = "https://notebook.google.com/notebook/tab-0d028786-66ef-4933-a322-ed66c"
_HOME = "https://notebook.google.com/"


# ── Doubles ──────────────────────────────────────────────────────────────────

class _Keyboard:
    def __init__(self, trace=None):
        self.presses = []
        self._trace = trace if trace is not None else []

    async def press(self, key):
        self.presses.append(key)
        self._trace.append(f"press:{key}")


class _Handle:
    """An ElementHandle double. `boom` reproduces the CDK-backdrop timeout."""

    def __init__(self, boom: bool = False):
        self.boom = boom
        self.clicks = 0
        self.click_kwargs = []

    async def click(self, **kw):
        self.clicks += 1
        self.click_kwargs.append(kw)
        if self.boom:
            raise TimeoutError(
                "ElementHandle.click: Timeout 30000ms exceeded.\nCall log:\n"
                '  - <div class="cdk-overlay-backdrop cdk-overlay-dark-backdrop '
                'cdk-overlay-backdrop-showing"></div> intercepts pointer events')


_PHRASE_PUBLIC = "Anyone with the link"


class ScriptedPage:
    """Dispatches page.evaluate on distinctive fragments of the real JS.

    Keyed on fragments rather than call order so the tests survive a reordering
    of the share flow — matching the lesson from the Claude popover tests.
    """

    def __init__(self, *, share_click_boom=False, dom_link="",
                 public_verified=False, dialog_after_click=True,
                 overlay_present=False, share_btn_missing=False,
                 access_control_found=True, access_option_found=True,
                 access_already_public=False):
        # ONE ordered trace across keyboard + evaluate + clicks. Presence alone
        # is not enough: the flow presses Escape anyway when it closes the share
        # dialog, so "Escape was pressed" is true even if the pre-click dismissal
        # never happened. Verified by mutation — deleting the Escape-first step
        # survived a presence assertion.
        self.trace: list = []
        self.keyboard = _Keyboard(self.trace)
        self.share = _Handle(boom=share_click_boom)
        self._dom_link = dom_link
        self._public_verified = public_verified
        self._dialog_after_click = dialog_after_click
        self._overlay_present = overlay_present
        self.overlay_removed = 0
        self.evaluated = []
        self.url = _TAB_URL
        self._share_btn_missing = share_btn_missing
        self._access_control_found = access_control_found
        self._access_option_found = access_option_found
        self._access_already_public = access_already_public

    async def query_selector(self, sel):
        if "cdk-overlay-backdrop" in sel:
            return _Handle() if self._overlay_present else None
        if "Share" in sel or "share" in sel:
            return None if self._share_btn_missing else self.share
        if "dialog" in sel:
            return _Handle() if self._dialog_after_click else None
        return None

    async def evaluate(self, js, arg=None):
        self.evaluated.append(js)
        if "cdk-overlay-backdrop" in str(arg or ""):        # overlay removal
            self.overlay_removed += 1
            self._overlay_present = False
            self.trace.append("overlay_removed")
            return 1
        if "notebook access" in js:                          # open access dropdown
            return "opened" if self._access_control_found else ""
        if "anyone with the link" in js and "opt.click()" in js:
            return "selected" if self._access_option_found else ""
        if "isNb(val)" in js:                                # the link read
            # ⭐ 2026-08-03: this double used to answer with a bare string, and
            # every test in this file passed on that answer — while the REAL
            # page could not answer at all. The predicate was handed to
            # `page.evaluate` as an ARGUMENT, so `isNb` arrived in the page as a
            # string and `isNb(val)` threw on the first input it reached. The
            # double was simulating a branch that had never executed.
            #
            # A double is only evidence if it answers the way the page does, so
            # the shape lives here now: {url, via}. `via` is the channel, and
            # naming it is what lets a caller tell "no dialog was open" from "an
            # open dialog with no link in it".
            if self._dom_link == "clipboard":
                return {"url": "clipboard", "via": "copy"}
            if self._dom_link:
                return {"url": self._dom_link, "via": "input"}
            return {"url": "", "via": "no_link_in_dialog"}
        # ⚠ BEFORE the PHRASE branch. The access diagnostic also mentions the
        # phrase, so ordering it after would hand it a bare bool, `.get` would
        # raise, the helper's try/except would swallow it and the already-public
        # path would be untestable — silently. Keyed on TRIGGERS, which only the
        # diagnostic defines. The returned SHAPE is the one the real JS produces
        # (proved against a DOM in test_nlm_access_already_public.py).
        if "const TRIGGERS =" in js:                         # access diagnostic
            return {"already": self._access_already_public,
                    "dialog": self._dialog_after_click,
                    "rows": 0 if self._access_already_public else 2,
                    "sample": [] if self._access_already_public
                              else ["Restricted", "Only people I choose"],
                    "access": _PHRASE_PUBLIC if self._access_already_public
                              else "Restricted"}
        if "PHRASE" in js:                                   # public-access verify
            return self._public_verified
        if "'save'" in js or "=== 'save'" in js:             # Save/Done
            return "saved"
        return ""


class _Browser:
    def __init__(self, page, tab_url=_TAB_URL):
        self.page = page
        self._tab_url = tab_url

    async def current_url(self):
        return self._tab_url


def _run(page, *, cua_client=None, tab_url=_TAB_URL, clipboard="", cua_text=""):
    """Drive the real coroutine with `get_clipboard` / `_shadow_observed_cua`
    monkeypatched at module scope, and return (LinkResult, calls)."""
    calls = {"cua": 0}
    orig_clip = research.get_clipboard
    orig_cua = research._shadow_observed_cua
    orig_sleep = asyncio.sleep

    async def _no_sleep(_s, *a, **k):
        return None

    async def _fake_cua(*a, **k):
        calls["cua"] += 1
        return {"text": cua_text}

    research.get_clipboard = lambda: clipboard
    research._shadow_observed_cua = _fake_cua
    asyncio.sleep = _no_sleep
    try:
        res = asyncio.run(research.extract_notebooklm_url(
            _Browser(page, tab_url), cua_client=cua_client))
    finally:
        research.get_clipboard = orig_clip
        research._shadow_observed_cua = orig_cua
        asyncio.sleep = orig_sleep
    return res, calls


# ── 1. The clipboard channel — the link that was thrown away ─────────────────

def test_clipboard_link_on_the_new_host_is_accepted():
    """THE outage, reproduced on its PRIMARY channel.

    The share dialog has no readable link field, so the DOM read clicks
    "Copy link" and returns the sentinel 'clipboard'; the helper then reads the
    clipboard, which holds a notebook URL on the lm-less host. Pre-fix the guard
    `"notebooklm.google.com" in clip` threw that away — the correct link, in
    hand, discarded — and the run fell back to the tab URL, which the validator
    then rejected: no podcast, no P4, no P5. No vision needed on this path.
    """
    page = ScriptedPage(dom_link="clipboard")
    res, calls = _run(page, cua_client=object(), clipboard=_NB)
    assert res.url == _NB, "the CLIPBOARD value must win, not the tab URL"
    assert res.url != _TAB_URL, (
        "falling back to the tab URL here is the bug: the correct link was in "
        "hand and the hostname guard discarded it"
    )
    assert calls["cua"] == 0, "the DOM clipboard channel must not need vision"
    assert res.error == ""


def test_clipboard_link_on_the_original_host_still_works():
    """The fix must not trade one host for the other — both are live."""
    page = ScriptedPage(dom_link="clipboard")
    res, _ = _run(page, cua_client=object(), clipboard=_NB_OLD)
    assert res.url == _NB_OLD


def test_clipboard_whitespace_is_stripped_before_the_url_is_returned():
    """A clipboard read routinely carries a trailing newline. Emitting it would
    put a stray character into the link that ends up in the Doc and the email."""
    page = ScriptedPage(dom_link="clipboard")
    res, _ = _run(page, cua_client=object(), clipboard=f"  {_NB}\n")
    assert res.url == _NB


def test_a_clipboard_click_that_copied_junk_does_not_become_the_link():
    """`Copy link` may click something that is not the link button. The
    clipboard's contents get shape-tested, never trusted."""
    page = ScriptedPage(dom_link="clipboard")
    res, _ = _run(page, cua_client=None, clipboard="Link copied!", tab_url=_HOME)
    assert res.url == _HOME
    assert res.error


def test_a_clipboard_holding_something_else_does_not_become_the_link():
    """Copy link may not have landed at all — the clipboard could still hold
    whatever the user last copied. That must never be emitted as a notebook."""
    page = ScriptedPage(dom_link="")
    res, _ = _run(page, cua_client=object(), clipboard="some unrelated text",
                  tab_url=_HOME)  # not on a notebook page -> vision escalates
    assert res.url == _HOME          # falls back to the tab URL
    assert research.is_notebooklm_url(res.url) is False
    assert res.error, "a miss must explain itself"


def test_the_dom_link_field_wins_without_ever_invoking_vision():
    """The fast path: a readable link field in the dialog means no 10-iteration
    vision mission and no 49-60s cost. This is the 6-second happy path the
    corpus lost."""
    page = ScriptedPage(dom_link=_NB, public_verified=True)
    res, calls = _run(page, cua_client=object(), clipboard="")
    assert res.url == _NB
    assert calls["cua"] == 0, "vision must not run when the DOM already answered"
    assert res.verified is True


# ── 2. The shared try/except — the fallback that could not run ───────────────

def test_a_share_click_timeout_still_reaches_the_vision_fallback():
    """Defect 2. The CDK backdrop made `share_btn.click()` raise, and because the
    fallback lived inside the same `try`, the except swallowed the error and the
    fallback was SKIPPED — on all three retry attempts, each burning a full 30s
    timeout for nothing. The fallback exists for exactly this failure.

    Mechanically it now escalates because a click that never landed means the
    helper never ran, so `access_set` is False. That is the point of gating on
    access rather than on the exception: the observable behaviour is the same and
    it also covers the failures that DON'T raise."""
    page = ScriptedPage(share_click_boom=True)
    res, calls = _run(page, cua_client=object(), clipboard=_NB)
    assert calls["cua"] == 1, (
        "a DOM click failure must fall through to vision, not abort the attempt"
    )
    assert res.url == _NB, "the vision path's clipboard read must win"
    assert res.url != _TAB_URL


def test_a_share_click_timeout_with_no_cua_client_still_returns_the_tab_url():
    """No vision client configured: the attempt must degrade quietly rather than
    raise out of the extractor."""
    page = ScriptedPage(share_click_boom=True)
    res, calls = _run(page, cua_client=None, tab_url=_HOME)
    assert calls["cua"] == 0
    assert res.url == _HOME
    assert res.verified is False


def test_the_share_click_is_bounded_so_three_retries_cannot_burn_90_seconds():
    page = ScriptedPage()
    _run(page, cua_client=object(), clipboard=_NB)
    assert page.share.click_kwargs, "the share click must pass an explicit timeout"
    assert page.share.click_kwargs[0].get("timeout") == 8000


# ── 3. `error` actually says something ──────────────────────────────────────

def test_error_names_the_failure_instead_of_being_blank():
    """Defect 3. `error` was never set, so the caller's warning rendered
    'falling back to tab URL: ' — 35/35 occurrences with nothing after the
    colon. The one log line that should have identified this outage identified
    nothing."""
    page = ScriptedPage(share_click_boom=True)
    res, _ = _run(page, cua_client=None, tab_url=_HOME)
    assert res.error
    assert "no notebook URL on any read channel" in res.error
    assert _HOME in res.error, "the URL we DID get must be in the message"
    assert "cdk-overlay-backdrop" in res.error, (
        "the underlying DOM failure must be carried, not swallowed — the "
        "backdrop is the actionable detail"
    )


def test_error_is_empty_on_success_so_LinkResult_success_is_true():
    """`LinkResult.success` is `bool(url) and not error`, and extract_with_retry
    gates on it — a non-empty error on a good URL would discard a valid link."""
    page = ScriptedPage(dom_link=_NB)
    res, _ = _run(page, cua_client=object())
    assert res.error == ""
    assert res.success is True


# ── 4. The CUA mission no longer asks for something unreadable ──────────────

def test_the_mission_does_not_ask_the_vision_layer_to_read_the_url_back():
    """Defect 4. `Tell me the EXACT URL` sent the vision layer looking for a
    paste target in an app with no address bar; it spent 8 of 10 iterations on
    that and reported nothing, while the link sat on the clipboard."""
    # Join implicitly-concatenated string literals first: the mission is a
    # multi-line parenthesised string, so a phrase that reads as one sentence in
    # the source is split across `" ... "` boundaries.
    src = re.sub(r'"\s*\n\s*"', "", inspect.getsource(research.extract_notebooklm_url))
    assert "Tell me the EXACT URL" not in src
    assert "I read the clipboard myself" in src
    assert "must NOT try to paste it anywhere" in src


def test_a_url_quoted_in_the_vision_answer_is_still_accepted_as_a_bonus():
    """Clipboard is primary, but if the model happens to see the full URL we
    take it — dropping a correct answer because it arrived on the second-choice
    channel is how the original bug felt from the user's side."""
    page = ScriptedPage(dom_link="")
    res, _ = _run(page, cua_client=object(), clipboard="",
                  cua_text=f"Copied. The URL is {_NB} — done.", tab_url=_HOME)
    assert res.url == _NB


def test_a_non_notebook_url_in_the_vision_answer_is_ignored():
    """The narration is prose and routinely contains other links (help pages,
    the app root). Only a notebook URL may be promoted."""
    page = ScriptedPage(dom_link="")
    res, _ = _run(page, cua_client=object(), clipboard="",
                  cua_text="See https://support.google.com/notebooklm for help.",
                  tab_url=_HOME)
    assert res.url == _HOME


# ── The stale-overlay dismissal ──────────────────────────────────────────────

def test_a_stale_backdrop_is_dismissed_with_escape_before_any_node_removal():
    """Escape is the SUPPORTED dismissal; ripping nodes out of an Angular app's
    overlay container is a last resort that can leave the CDK's own state
    inconsistent. Asserted as ORDER, not presence — the flow presses Escape
    anyway when it closes the dialog."""
    page = ScriptedPage(overlay_present=True)
    _run(page, cua_client=object(), clipboard=_NB)
    assert "press:Escape" in page.trace
    if "overlay_removed" in page.trace:
        assert page.trace.index("press:Escape") < page.trace.index("overlay_removed"), (
            "Escape must be tried BEFORE removing nodes from the page"
        )


def test_a_backdrop_that_survives_escape_is_removed_as_a_last_resort():
    class _Stubborn(ScriptedPage):
        async def query_selector(self, sel):
            if "cdk-overlay-backdrop" in sel:
                # Survives Escape; only the removal clears it.
                return None if self.overlay_removed else _Handle()
            return await ScriptedPage.query_selector(self, sel)

    page = _Stubborn(overlay_present=True)
    _run(page, cua_client=object(), clipboard=_NB)
    assert page.trace and page.trace[0] == "press:Escape", (
        "the FIRST thing the dismissal does must be Escape — a removal-first "
        "implementation would rip out overlays a plain Escape would have closed"
    )
    assert page.overlay_removed == 1, (
        "a backdrop that ignores Escape must be removed — otherwise every click "
        "under it times out at 30s, three times per link-extract cycle"
    )


def test_no_overlay_means_no_escape_and_no_removal():
    """Pressing Escape unconditionally would close a dialog the flow is about to
    use. The dismissal must be a no-op when there is nothing stale."""
    page = ScriptedPage(overlay_present=False)
    _run(page, cua_client=object(), clipboard=_NB)
    assert page.overlay_removed == 0
    # The flow's own post-dialog Escape still fires; what must NOT happen is an
    # extra pre-click Escape. One press, from closing the dialog.
    assert page.keyboard.presses.count("Escape") == 1


# ── public_verified stays an honest, separate signal ─────────────────────────

def test_a_shape_ok_link_is_returned_even_when_public_access_is_unverified():
    """`Public share DOM-verified` has never once logged in the corpus, so
    requiring it discarded the extracted link on 100% of runs and left the tab
    URL as a silent crutch. The link is returned; `verified` stays False so
    callers know the access state is unconfirmed."""
    page = ScriptedPage(dom_link=_NB, public_verified=False)
    res, _ = _run(page, cua_client=object())
    assert res.url == _NB
    assert res.verified is False


def test_verified_requires_both_the_shape_and_dom_confirmed_public_access():
    page = ScriptedPage(dom_link=_NB, public_verified=True)
    res, _ = _run(page, cua_client=object())
    assert res.verified is True


def test_the_vision_path_never_claims_verified():
    """Vision cannot read the access dropdown, so it must never report the link
    as DOM-confirmed public — that would let a private link reach the email and
    the Google Doc, where the recipient gets 'Request access' instead of a
    notebook. Driven via a DOM click failure, which is how the vision path is
    reached in production."""
    page = ScriptedPage(share_click_boom=True, public_verified=False)
    res, calls = _run(page, cua_client=object(), clipboard=_NB)
    assert calls["cua"] == 1
    assert res.url == _NB
    assert res.verified is False


# ── The quiet DOM failures (adversarial review, 2026-07-31) ──────────────────
#
# The first version of this fix escalated to vision on `not is_notebooklm_url(url)
# or _dom_err`. Review traced two paths that satisfy NEITHER and still leave the
# notebook PRIVATE, which downstream means the Phase-5 email and Google Doc hand
# the recipient "Request access" instead of a notebook:
#
#   * the Share button selector rotates -> query_selector returns None -> there
#     was no else branch at all: no log, no error, no escalation, and the
#     selfheal watcher added to catch exactly this rot sat INSIDE `if share_btn:`
#     so it never observed the failure either.
#   * the access dropdown or its option list moves -> the dialog opens, the link
#     read still works, so `url` is shape-valid and nothing raises.
#
# In both, `url` keeps the tab-URL seed, which on a notebook page is itself
# shape-valid — so the run ships a link and reports success.

def test_a_missing_share_button_escalates_to_vision_and_says_so(capsys):
    page = ScriptedPage(share_btn_missing=True)
    res, calls = _run(page, cua_client=object(), clipboard=_NB)
    assert calls["cua"] == 1, (
        "a rotated Share selector is the quietest possible failure on the one "
        "control the whole share flow depends on — it must escalate"
    )
    assert res.url == _NB
    out = capsys.readouterr().out
    assert "share button not found" in out


def test_a_missing_share_button_with_no_vision_client_reports_the_reason():
    page = ScriptedPage(share_btn_missing=True)
    res, calls = _run(page, cua_client=None, tab_url=_HOME)
    assert calls["cua"] == 0
    assert "share button not found" in res.error


def test_access_never_being_set_escalates_even_though_nothing_raised():
    """The restructured-dialog case. The incident report grades "the dialog was
    restructured" as EQUALLY consistent with the evidence as the host rename, so
    this is not a hypothetical."""
    page = ScriptedPage(dom_link=_NB_OLD, access_option_found=False)
    res, calls = _run(page, cua_client=object(), clipboard=_NB)
    assert calls["cua"] == 1, (
        "the dialog opened and the link read worked, so neither the URL-shape "
        "gate nor _dom_err fires — without an access-based trigger the run "
        "silently ships a PRIVATE link"
    )


def test_a_missing_access_control_also_escalates():
    page = ScriptedPage(dom_link=_NB_OLD, access_control_found=False)
    _, calls = _run(page, cua_client=object(), clipboard=_NB)
    assert calls["cua"] == 1


def test_a_healthy_run_does_not_pay_for_a_vision_mission():
    """The cost guard. `access_set` is used as the trigger rather than
    `public_verified` precisely because public_verified has been False on EVERY
    run in the corpus — escalating on it would escalate forever."""
    page = ScriptedPage(dom_link=_NB, public_verified=False,
                        access_control_found=True, access_option_found=True)
    res, calls = _run(page, cua_client=object(), clipboard="")
    assert calls["cua"] == 0, (
        "access WAS set; an unverifiable public_verified must not cost a "
        "10-iteration vision mission on every single run"
    )
    assert res.url == _NB
    assert res.verified is False   # still honest about the unconfirmed access


def test_the_helper_reports_access_set_as_a_third_return_value():
    """`public_verified` cannot carry this signal — it is a deliberately strict
    own-text read that never passes. `access_set` is the positive one."""
    orig_sleep = asyncio.sleep

    async def _no_sleep(_s, *a, **k):
        return None

    asyncio.sleep = _no_sleep
    try:
        ok = asyncio.run(research._set_nlm_public_and_get_link(
            ScriptedPage(dom_link=_NB), "NotebookLM"))
        moved = asyncio.run(research._set_nlm_public_and_get_link(
            ScriptedPage(dom_link=_NB, access_option_found=False), "NotebookLM"))
    finally:
        asyncio.sleep = orig_sleep
    assert len(ok) == 3 and len(moved) == 3
    assert ok[2] is True
    assert moved[2] is False


def test_the_share_dialog_selfheal_observation_runs_even_when_the_button_is_gone():
    """It used to sit inside `if share_btn:`, so the watcher added to catch
    Share-button rot could never observe Share-button rot.

    Asserts on the guarding CONDITION, not just on position: moving the
    observation after the if/else but re-adding `and share_btn` to its guard
    restores the blind spot while leaving the ordering intact.
    """
    src = inspect.getsource(research.extract_notebooklm_url)
    i_else = src.index("        else:\n            # 2026-07-31 (adversarial review)")
    i_obs = src.index('"notebooklm.open_share_dialog"')
    assert i_obs > i_else, (
        "the observation must sit AFTER the if/else so it fires on both branches"
    )
    # The `if` that guards the observation must not depend on the share button.
    guard = src[src.rindex("if selfheal", 0, i_obs):i_obs]
    assert "share_btn" not in guard, (
        "the observation must not be gated on the Share button existing — a "
        "missing button is the rot it exists to record"
    )


# ── Channel priority + the terminal event (reviewer-found gaps) ──────────────

def test_the_clipboard_wins_over_a_url_quoted_in_the_vision_answer():
    """Both channels populated with DIFFERENT values. The clipboard is what the
    mission actually fills; the narration is prose and can quote a stale link."""
    page = ScriptedPage(share_click_boom=True)
    res, _ = _run(page, cua_client=object(), clipboard=_NB,
                  cua_text=f"Copied. Earlier I saw {_NB_OLD} on screen.")
    assert res.url == _NB, "clipboard first — the vision answer is the fallback"


def test_the_escalation_gate_does_not_depend_on_an_exception_being_raised():
    """`_dom_err` was in this gate and is deliberately not any more: every path
    that sets it also leaves `access_set` False (so it was redundant), and its one
    unique case — the trailing Escape throwing AFTER the helper already succeeded
    — is one where escalating burns a vision mission for nothing. It is still
    carried into `error`.

    Pinned because the reverse mistake is the tempting one: gating on the
    exception is the obvious reading of "the DOM failed", and it silently misses
    every quiet failure, which is the whole finding here.
    """
    src = code_only(research.extract_notebooklm_url)
    i = src.index("if cua_client and (")
    gate = " ".join(src[i:src.index(":", i)].split())
    assert "not access_set" in gate
    assert "not is_notebooklm_url(url)" in gate
    assert "_dom_err" not in gate, (
        "escalating on the exception is redundant with access_set and wasteful "
        "in its one unique case"
    )
    # It must still reach `error`, which is what makes the failure diagnosable.
    assert "_dom_err" in src


def test_a_successful_dom_share_whose_escape_throws_does_not_escalate():
    """The one case `_dom_err` uniquely covered. Access was set and the link was
    read; a trailing Escape failure must not cost a vision mission."""
    class _EscapeBoom(ScriptedPage):
        def __init__(self, **kw):
            ScriptedPage.__init__(self, **kw)

            class _K:
                async def press(_self, key):
                    raise RuntimeError("target page closed")
            self.keyboard = _K()

    page = _EscapeBoom(dom_link=_NB)
    res, calls = _run(page, cua_client=object(), clipboard="")
    assert res.url == _NB
    assert calls["cua"] == 0, (
        "access was set and the link was read — nothing needs re-doing"
    )
