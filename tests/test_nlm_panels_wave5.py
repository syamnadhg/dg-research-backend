"""Wave 5 — the NotebookLM panels.

Four defects, all on surfaces that had passed source-text tests for months:

* the share-link read handed a JS function to `page.evaluate` as an ARGUMENT, so
  it threw on line one — and the throw took the public-access verify and the
  Save click down with it, every run;
* the audio ⋮ query was document-wide and the topmost `aria-label="More"` on a
  NotebookLM page is always a SOURCE row's kebab, whose destructive item is
  "Remove source";
* `Chat options` renders at x=-36 with a full-size rect and a live
  offsetParent, so a size-only visibility gate calls it clickable;
* Material icon ligatures bleed into innerText (`share Share`, `edit Rename`,
  `save_alt Download`, `delete Delete`) and `Delete` sits two rows below
  `Download` in the menu we now actually open.

Everything here that concerns page JS EXECUTES it, against the markup in the
owner's captures. A source-text assertion cannot distinguish a selector that
matches from one that matches nothing — and, as the first defect shows, cannot
distinguish JS that runs from JS that throws.
"""
import ast
import asyncio
import inspect

import pytest

import prompts
import research
from conftest import code_only, code_only_deep
from _domshim import NODE, el, run_js

pytestmark = pytest.mark.skipif(NODE is None, reason="node required to execute page JS")


# ── fixtures built from the owner's captures ──────────────────────────────

def _icon_row(icon, label, **attrs):
    """A Material menu row: `<mat-icon>ligature</mat-icon><span>Label</span>`.

    The ligature is a real text node inside the icon element, which is exactly
    why it lands in innerText.
    """
    return el("div", {"role": "menuitem", **attrs},
              kids=[el("mat-icon", text=icon), el("span", text=label)])


def _audio_menu(**attrs):
    """Captures §7 — the audio card's ⋮ menu, in its captured row order."""
    return el("div", {"role": "menu", "w": "260", "h": "220", **attrs}, kids=[
        _icon_row("share", "Share"),
        _icon_row("edit", "Rename"),
        _icon_row("save_alt", "Download"),
        _icon_row("info_spark", "View prompt and sources"),
        _icon_row("delete", "Delete"),
    ])


def _source_row(name, y):
    """Captures §6 — a source row, kebab included. Same aria-label as the audio
    card's, which is the whole problem."""
    return el("div", {"class": "source-row"}, kids=[
        el("span", text=name),
        el("button", {"aria-label": "More", "x": "654", "y": str(y),
                      "w": "40", "h": "40"}, kids=[el("mat-icon", text="more_vert")]),
    ])


def _studio_panel(kebab_attrs=None, extra=()):
    """Captures §8 — studio-panel → artifact-library → artifact-library-item →
    button[aria-label="More"]."""
    ka = {"aria-label": "More", "x": "668", "y": "398", "w": "40", "h": "40"}
    ka.update(kebab_attrs or {})
    return el("studio-panel", {"w": "400", "h": "600"}, kids=[
        el("div", kids=[
            el("artifact-library", kids=[
                el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
                    el("mat-icon", text="audio_magic_eraser"),
                    el("span", text="Deep dive - 3 sources"),
                    el("button", ka, kids=[el("mat-icon", text="more_vert")]),
                ]),
            ]),
        ]),
        *extra,
    ])


def _notebook_page(*, studio=True, sources=True, extra=()):
    """The whole notebook view. Source rows come FIRST in document order — that
    ordering IS the bug, so a fixture that put the audio card first would prove
    nothing."""
    kids = []
    if sources:
        kids += [_source_row("chatgpt.md", 364), _source_row("claude.md", 416),
                 _source_row("gemini.md", 468)]
    if studio:
        kids.append(_studio_panel())
    kids += list(extra)
    return el("body", {"w": "1440", "h": "900"}, kids=kids)


# ── item 11 — the share-link read has never executed ──────────────────────

def test_no_page_evaluate_is_handed_a_js_function_as_an_argument():
    """The general form of the defect, not just its one instance.

    `page.evaluate(js, <a JS function>)` serializes the second argument, so the
    function arrives in the page as a STRING and the first call of it throws.
    Nothing in the type system, the linter or a source-text test objects.

    ⚠ The first version of this guard keyed on names ENDING in `_JS`, and the
    constant that caused the bug is called `_JS_IS_NLM_URL` — it starts with it.
    A mutation that put the argument straight back survived, which is how that
    was found. The rule now looks at the VALUE: whatever the constant is called,
    a string holding an arrow function cannot cross this boundary.
    """
    tree = ast.parse(inspect.getsource(research))

    def is_js_function(value):
        return isinstance(value, str) and "=>" in value and value.lstrip().startswith("(")

    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "evaluate" and len(node.args) >= 2):
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Name) and is_js_function(getattr(research, arg.id, None)):
            bad.append(f"line {node.lineno}: evaluate(..., {arg.id})")
        elif isinstance(arg, ast.Constant) and is_js_function(arg.value):
            bad.append(f"line {node.lineno}: evaluate(..., <inline JS function>)")
    assert not bad, (
        "a JS function cannot cross the page.evaluate argument boundary — embed "
        "it in the source instead: " + "; ".join(bad))


def test_that_guard_can_actually_see_the_constant_that_caused_the_bug():
    """A guard whose detector cannot recognise the original offender is a guard
    that would not have fired. Prove the predicate on the real value."""
    v = research._JS_IS_NLM_URL
    assert isinstance(v, str) and "=>" in v and v.lstrip().startswith("(")


def test_the_read_embeds_the_predicate_rather_than_passing_it():
    src = code_only(inspect.getsource(research._set_nlm_public_and_get_link))
    assert "page.evaluate(_NLM_SHARE_LINK_READ_JS," in src, (
        "the share-link read must go through the constant that embeds the "
        "predicate")
    assert research._JS_IS_NLM_URL in research._NLM_SHARE_LINK_READ_JS, (
        "the constant must EMBED the one predicate definition, not re-spell the "
        "host — re-spelling is how the four gates drifted apart in the first "
        "place")


def _read(spec):
    return run_js(spec, research._NLM_SHARE_LINK_READ_JS,
                  {"scopes": research._NLM_DIALOG_SCOPES})


def test_share_read_returns_the_notebook_url_from_the_dialog():
    got = _read(el("body", kids=[
        el("div", {"role": "dialog", "w": "480", "h": "320"}, kids=[
            el("input", {"readonly": "", "value": "https://notebooklm.google.com/notebook/abc123",
                         "w": "300", "h": "32"}),
        ]),
    ]))
    assert got["ret"] == {"url": "https://notebooklm.google.com/notebook/abc123",
                          "via": "input"}


def test_share_read_accepts_whatever_google_host_serves_notebooks():
    """The point of routing through the shared predicate: a rename of the host
    must not need a code change here."""
    for host in ("notebooklm.google.com", "labs.google.com", "google.com"):
        got = _read(el("body", kids=[
            el("div", {"role": "dialog", "w": "480", "h": "320"}, kids=[
                el("input", {"readonly": "", "value": f"https://{host}/notebook/xyz",
                             "w": "300", "h": "32"}),
            ]),
        ]))
        assert got["ret"]["url"] == f"https://{host}/notebook/xyz", host


@pytest.mark.parametrize("value", [
    "https://example.com/notebook/abc",          # right path, wrong host
    "https://notebooklm.google.com/",            # right host, no notebook
    "https://notebooklm.google.com/notebook/",   # notebook path with no id
    "javascript:alert(1)",                       # not http(s)
    "",
])
def test_share_read_rejects_anything_that_is_not_a_notebook_url(value):
    got = _read(el("body", kids=[
        el("div", {"role": "dialog", "w": "480", "h": "320"}, kids=[
            el("input", {"readonly": "", "value": value, "w": "300", "h": "32"}),
        ]),
    ]))
    assert got["ret"]["url"] == "", value


def test_copy_link_is_clicked_when_the_dialog_holds_no_input():
    got = _read(el("body", kids=[
        el("div", {"role": "dialog", "w": "480", "h": "320"}, kids=[
            el("button", {"aria-label": "Copy link", "w": "90", "h": "32"},
               text="Copy link"),
        ]),
    ]))
    assert got["ret"] == {"url": "clipboard", "via": "copy"}
    assert got["clicks"] == ["Copy link"]


def test_the_copy_click_never_leaves_the_dialog():
    """⛔ The asymmetry is the point. Reading a value is harmless anywhere and
    every candidate is gated by the predicate, so the READ may range over the
    page. Clicking is not harmless: this block is being brought back to life for
    the first time, and a document-wide "any button whose text contains copy"
    search would, outside a dialog, be a real press on whatever the notebook
    renders."""
    got = _read(el("body", kids=[
        el("button", {"aria-label": "Copy all", "w": "90", "h": "32"}, text="Copy"),
    ]))
    assert got["ret"] == {"url": "", "via": "no_dialog"}
    assert got["clicks"] == []


def test_an_off_canvas_copy_button_is_not_pressed():
    """Every CLICK in this wave goes through the same gate, including this one."""
    got = _read(el("body", kids=[
        el("div", {"role": "dialog", "w": "480", "h": "320"}, kids=[
            el("button", {"aria-label": "Copy link", "x": "-90", "y": "40",
                          "w": "80", "h": "32"}, text="Copy link"),
        ]),
    ]))
    assert got["ret"]["url"] == ""
    assert got["clicks"] == []


def test_the_read_still_ranges_over_the_page_when_no_dialog_matched():
    got = _read(el("body", kids=[
        el("input", {"readonly": "", "value": "https://notebooklm.google.com/notebook/zz",
                     "w": "300", "h": "32"}),
    ]))
    assert got["ret"] == {"url": "https://notebooklm.google.com/notebook/zz",
                          "via": "input"}


def test_a_dialog_with_neither_input_nor_copy_reports_itself():
    """`no_dialog` and `no_link_in_dialog` are different failures needing
    different fixes, and the old code returned '' for both."""
    got = _read(el("body", kids=[
        el("div", {"role": "dialog", "w": "480", "h": "320"}, kids=[
            el("span", text="Notebook access"),
        ]),
    ]))
    assert got["ret"] == {"url": "", "via": "no_link_in_dialog"}


def test_the_throw_used_to_swallow_save_so_save_must_stay_downstream():
    """The read is not the only casualty: it sits inside the helper's one
    try/except, so the throw skipped the public-access verify AND the Save
    click. Both must remain AFTER the read for the fix to have bought anything.
    """
    src = code_only(inspect.getsource(research._set_nlm_public_and_get_link))
    _, _, after = src.partition("page.evaluate(_NLM_SHARE_LINK_READ_JS,")
    assert "public_verified = bool(await page.evaluate(" in after, (
        "the public-access verify must run after the read")
    assert "txt === 'save'" in after, "the Save click must run after the read"


# ── item 13 — the audio ⋮ query was document-wide ─────────────────────────

def _open(spec):
    return run_js(spec, research._NLM_OPEN_AUDIO_MENU_JS,
                  {"scopes": research._NLM_AUDIO_MENU_SCOPES,
                   "triggers": research._NLM_AUDIO_TRIGGER_SELS})


def test_the_document_wide_kebab_query_is_gone():
    src = code_only_deep(inspect.getsource(research))
    assert 'button[aria-label*="More"], button[aria-label*="more"], ' not in src, (
        "the document-wide kebab query is what opened a source row's menu")
    assert 'button[aria-label*="Options"]' not in src, (
        'that query also matched `Chat options`, which is parked off-canvas')


def test_it_opens_the_audio_card_kebab_and_not_the_topmost_source_row():
    got = _open(_notebook_page())
    assert got["ret"]["opened"] is True
    assert got["ret"]["via"] == "audio-card"
    assert got["ret"]["in_audio_card"] is True, (
        "the aria-label is identical on both kebabs, so containment is the only "
        "proof the right one was clicked")
    assert got["ret"]["in_studio"] is True
    assert len(got["clicks"]) == 1


def test_a_page_of_source_rows_alone_opens_nothing():
    """⛔ The single most important assertion in this file. The old query would
    click here — a source row's kebab, whose menu offers "Remove source". The
    correct answer is to decline and let the caller take the notebook-level
    Share button."""
    got = _open(_notebook_page(studio=False))
    assert got["ret"] == {"opened": False, "via": "", "reason": "no_scoped_trigger"}
    assert got["clicks"] == []


def test_scope_falls_back_through_the_container_chain():
    """An artifact item that has lost the audio ligature still resolves — via
    the next scope down, not via the page."""
    panel = el("studio-panel", {"w": "400", "h": "600"}, kids=[
        el("artifact-library", kids=[
            el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
                el("span", text="Deep dive"),
                el("button", {"aria-label": "More", "x": "668", "y": "398",
                              "w": "40", "h": "40"}),
            ]),
        ]),
    ])
    got = _open(el("body", {"w": "1440", "h": "900"},
                   kids=[_source_row("chatgpt.md", 364), panel]))
    assert got["ret"]["opened"] is True
    assert got["ret"]["via"] == "artifact-item"
    assert got["ret"]["in_studio"] is True


def test_the_containment_flags_are_measured_and_can_be_false():
    """⚠ A flag that is only ever asserted true on the happy path is not a
    measurement — a mutation that hardcoded `inCard = true` survived exactly
    that. The third scope resolves a kebab that is inside the Studio panel but
    NOT inside an artifact item, and the two flags must disagree there."""
    panel = el("studio-panel", {"w": "400", "h": "600"}, kids=[
        el("div", {"class": "studio-header"}, kids=[
            el("button", {"aria-label": "More", "x": "668", "y": "120",
                          "w": "40", "h": "40"}),
        ]),
    ])
    got = _open(el("body", {"w": "1440", "h": "900"}, kids=[panel]))
    assert got["ret"]["via"] == "studio-panel"
    assert got["ret"]["in_studio"] is True
    assert got["ret"]["in_audio_card"] is False, (
        "containment must be read from the DOM, not asserted")


def test_a_studio_panel_taller_than_the_viewport_still_resolves():
    """⚠ The container is NOT gated on visibility, on purpose. A Studio panel
    with several cards is taller than the viewport, so its centre is below the
    fold — gating the container would reject exactly the page this is for. Only
    the button being clicked has to be reachable."""
    panel = el("studio-panel", {"w": "400", "h": "2400", "y": "0"}, kids=[
        el("artifact-library", {"h": "2300"}, kids=[
            el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
                el("span", text="Deep dive"),
                el("button", {"aria-label": "More", "x": "668", "y": "398",
                              "w": "40", "h": "40"}),
            ]),
        ]),
    ])
    got = _open(el("body", {"w": "1440", "h": "900"}, kids=[panel]))
    assert got["ret"]["opened"] is True
    assert got["ret"]["via"] == "artifact-item"


def test_the_hooks_are_ordered_and_the_exact_label_wins():
    """A rename to "More options" must degrade to the substring rung rather than
    silently matching nothing."""
    panel = _studio_panel(kebab_attrs={"aria-label": "More options"})
    got = _open(el("body", {"w": "1440", "h": "900"}, kids=[panel]))
    assert got["ret"]["opened"] is True
    assert got["ret"]["hook"] == 'button[aria-label*="more" i]'


def test_scoping_is_containment_and_never_an_exclusion_list():
    """"Scope in, never exclude by name" — an exclusion keyed on source labels
    reopens the hole the day a source is renamed."""
    js = research._NLM_OPEN_AUDIO_MENU_JS
    for banned in ("chatgpt.md", "Remove source", "source-row", ".md"):
        assert banned not in js, f"{banned!r} is an exclusion, not a scope"
    sels = [g["sel"] for g in research._NLM_AUDIO_MENU_SCOPES]
    assert sels[0] == "artifact-library-item"
    assert all("studio-panel" in s for s in sels[1:])


# ── the aria-expanded proof ───────────────────────────────────────────────

def _verify(spec):
    return run_js(spec, research._NLM_AUDIO_MENU_VERIFY_JS,
                  {"scopes": research._NLM_AUDIO_MENU_SCOPES,
                   "triggers": research._NLM_AUDIO_TRIGGER_SELS})


def test_the_trigger_itself_reports_that_it_expanded():
    panel = _studio_panel(kebab_attrs={"aria-expanded": "true"})
    got = _verify(el("body", {"w": "1440", "h": "900"}, kids=[panel]))
    assert got["ret"] == {"in_scope": 1, "outside": 0,
                          "trigger_found": True, "trigger_expanded": True}


def test_an_expanded_source_kebab_counts_as_not_ours():
    """This is the state the old code could not distinguish from success: a menu
    IS open, and it is the wrong one."""
    row = _source_row("chatgpt.md", 364)
    row["kids"][1]["attrs"]["aria-expanded"] = "true"
    got = _verify(el("body", {"w": "1440", "h": "900"}, kids=[row, _studio_panel()]))
    assert got["ret"] == {"in_scope": 0, "outside": 1,
                          "trigger_found": True, "trigger_expanded": False}


def test_a_control_that_was_already_open_is_not_our_proof():
    """⭐ The reason verification asks the TRIGGER rather than counting.

    A Studio panel with an expanded section header satisfies "something inside
    the scope is expanded" before we have clicked anything. A count would have
    verified a click that did nothing and handed the run an audio menu that was
    never opened.
    """
    panel = el("studio-panel", {"w": "400", "h": "600"}, kids=[
        el("div", {"aria-expanded": "true", "class": "section-header"},
           text="Studio"),
        el("artifact-library", kids=[
            el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
                el("mat-icon", text="audio_magic_eraser"),
                el("button", {"aria-label": "More", "aria-expanded": "false",
                              "x": "668", "y": "398", "w": "40", "h": "40"}),
            ]),
        ]),
    ])
    got = _verify(el("body", {"w": "1440", "h": "900"}, kids=[panel]))
    assert got["ret"]["in_scope"] == 1, "the count alone would say yes"
    assert got["ret"]["trigger_expanded"] is False, (
        "…and the trigger says no, which is the answer that decides")


def test_the_opener_and_the_verifier_resolve_the_same_button():
    """They share one finder on purpose. If they could disagree, "the trigger is
    expanded" would be a claim about a different button than the one clicked."""
    assert research._NLM_FIND_AUDIO_TRIGGER_JS in research._NLM_OPEN_AUDIO_MENU_JS
    assert research._NLM_FIND_AUDIO_TRIGGER_JS in research._NLM_AUDIO_MENU_VERIFY_JS


class _EvalPage:
    """A page double whose evaluate answers per JS constant, and can raise.

    Scripted on the CONSTANT rather than on call order: the helper's two
    evaluates are an open and a verify, and keying on order would pass a
    re-ordering that swapped their meanings.
    """

    def __init__(self, *, open_ret, verify_ret=None, verify_raises=False,
                 open_raises=False, verify_late=0):
        self._open = open_ret
        self._verify = verify_ret
        self._verify_raises = verify_raises
        self._open_raises = open_raises
        # How many verifies answer "not expanded yet" before the real one. A
        # menu that mounts a moment late used to fail the single post-sleep
        # check and be reported as a menu that opened somewhere else.
        self._verify_late = verify_late
        self.keyboard = _NoKeyboard()
        self.calls = []
        self.args = []

    async def evaluate(self, js, arg=None):
        # ⚠ The double HONOURS its arguments. Without this, a caller that
        # verified against an empty scope list — i.e. against nothing — would be
        # indistinguishable from one that verified against the Studio panel,
        # and every test below would still pass.
        self.args.append(arg)
        if "no_scoped_trigger" in js:
            self.calls.append("open")
            assert (arg or {}).get("scopes") == research._NLM_AUDIO_MENU_SCOPES
            assert (arg or {}).get("triggers") == research._NLM_AUDIO_TRIGGER_SELS
            if self._open_raises:
                raise RuntimeError("Execution context was destroyed")
            return self._open
        if "trigger_expanded" in js:
            self.calls.append("verify")
            if self._verify_late:
                self._verify_late -= 1
                return {"in_scope": 0, "outside": 0,
                        "trigger_found": True, "trigger_expanded": False}
            assert (arg or {}).get("scopes") == research._NLM_AUDIO_MENU_SCOPES, (
                "the verify must be scoped to the SAME containers the open was")
            assert (arg or {}).get("triggers") == research._NLM_AUDIO_TRIGGER_SELS, (
                "…and must resolve the SAME trigger the open clicked")
            if self._verify_raises:
                raise RuntimeError("Execution context was destroyed")
            return self._verify
        raise AssertionError(f"unexpected evaluate: {js[:60]!r}")


class _NoKeyboard:
    def __init__(self):
        self.presses = []

    async def press(self, key):
        self.presses.append(key)


def _run(coro):
    return asyncio.run(coro)


def test_a_scoped_trigger_that_expands_inside_the_panel_is_verified():
    page = _EvalPage(open_ret={"opened": True, "via": "audio-card"},
                     verify_ret={"trigger_expanded": True, "in_scope": 1,
                                 "outside": 0})
    got = _run(research._nlm_open_audio_menu(page))
    assert got["verified"] is True
    assert page.calls == ["open", "verify"]


def test_a_menu_that_expands_a_moment_late_is_still_verified():
    """2026-08-04, from the P1/P2/P3 DOM audit: the verify is right — it
    re-resolves the trigger and asks THAT button — but it used to run once after
    a fixed second, so a menu that mounted late failed it and the caller read
    that as "a menu opened somewhere outside the Studio panel", which is a
    different and more alarming thing than "not yet"."""
    page = _EvalPage(open_ret={"opened": True, "via": "audio-card"},
                     verify_late=2,
                     verify_ret={"trigger_expanded": True, "in_scope": 1,
                                 "outside": 0})
    got = _run(research._nlm_open_audio_menu(page))
    assert got["verified"] is True
    assert page.calls == ["open", "verify", "verify", "verify"]


def test_the_verify_poll_is_bounded():
    page = _EvalPage(open_ret={"opened": True, "via": "audio-card"},
                     verify_late=99,
                     verify_ret={"trigger_expanded": True})
    got = _run(research._nlm_open_audio_menu(page))
    assert got["verified"] is False
    assert page.calls.count("verify") <= 6, "the poll must give up, not spin"


def test_an_open_that_expands_nothing_in_scope_is_not_verified():
    page = _EvalPage(open_ret={"opened": True, "via": "audio-card"},
                     verify_ret={"trigger_expanded": False, "in_scope": 1,
                                 "outside": 1})
    got = _run(research._nlm_open_audio_menu(page))
    assert got["verified"] is False
    assert got["outside"] == 1


def test_a_failed_open_reports_verified_false_rather_than_omitting_it():
    """⚠ Behavioural, deliberately. The source-text version of this assertion
    was satisfied by the identical literal on the EXCEPTION path — a mutation
    that dropped the key from the failure return survived it. What matters is
    that a caller's `.get("verified")` cannot fall through to a default."""
    page = _EvalPage(open_ret={"opened": False, "via": "", "reason": "no_scoped_trigger"})
    got = _run(research._nlm_open_audio_menu(page))
    assert got["verified"] is False
    assert "verified" in got
    assert page.calls == ["open"], "a failed open must not go on to verify"


def test_a_verify_that_throws_is_not_a_pass():
    """A page that navigated out from under us fails the verify. That is an
    absence of proof, and an absence of proof is not proof."""
    page = _EvalPage(open_ret={"opened": True, "via": "audio-card"},
                     verify_raises=True)
    got = _run(research._nlm_open_audio_menu(page))
    assert got["verified"] is False
    assert got["opened"] is True


def test_an_open_that_throws_reports_both_flags_false():
    page = _EvalPage(open_ret=None, open_raises=True)
    got = _run(research._nlm_open_audio_menu(page))
    assert got["opened"] is False
    assert got["verified"] is False
    assert got["reason"].startswith("evaluate_failed:")


def test_verification_is_the_triggers_own_state():
    src = code_only(inspect.getsource(research._nlm_open_audio_menu))
    assert 'verified = bool(chk.get("trigger_expanded"))' in src, (
        "verification is the trigger's own state, not a count of what happens "
        "to be expanded inside the scope")


def test_the_share_step_is_gated_on_verified_not_on_opened():
    """⚠ Scoped to the gate itself. `_menu.get("opened")` legitimately appears
    in the else-branch, so an unscoped "does the function mention verified"
    assertion passes with the gate flipped — a mutation did exactly that."""
    src = code_only(inspect.getsource(research.run_phase3_audio))
    _, _, after = src.partition("_menu = await _nlm_open_audio_menu(page)")
    gate = after.split("\n", 2)[1]
    assert gate.strip() == 'if _menu.get("verified"):', (
        f"the audio ⋮ path must be gated on the proof, not on the click: {gate!r}")


def test_an_unverified_open_is_closed_before_the_fallback():
    """⚠ Scoped to the audio-share block. A bare "Escape appears somewhere in
    this 200-line function" assertion is satisfied by the Escape at the end of
    the block, which fires on the happy path too — a mutation that deleted the
    one guarding the wrong-menu branch would survive it.

    Leaving a menu open is not cosmetic: an unattended overlay one stray click
    from "Remove source" is the residue the whole fix is about.
    """
    src = code_only(inspect.getsource(research.run_phase3_audio))
    _, _, block = src.partition("_menu = await _nlm_open_audio_menu(page)")
    wrong_menu, _, _ = block.partition("await _notebook_share_fallback(_menu.get(")
    assert 'if _menu.get("opened"):' in wrong_menu
    _, _, after_open = wrong_menu.partition('if _menu.get("opened"):')
    assert 'await page.keyboard.press("Escape")' in after_open, (
        "a menu we opened by mistake must be closed before the fallback clicks "
        "anything else")


def test_a_missing_share_row_also_closes_the_menu_it_opened():
    src = code_only(inspect.getsource(research.run_phase3_audio))
    _, _, block = src.partition("_pick = await _nlm_menu_pick(page, want=")
    branch, _, _ = block.partition("else:\n                if _menu.get(\"opened\")")
    assert 'await page.keyboard.press("Escape")' in branch, (
        "an open audio menu with no Share row must be closed, not abandoned")
    assert "_notebook_share_fallback(" in branch


# ── the off-canvas control ────────────────────────────────────────────────

def test_a_control_parked_off_canvas_is_not_clicked():
    """`Chat options` renders at x=-36: full-size rect, live offsetParent,
    unreachable by a click. Both of the visibility idioms this codebase uses
    would have called it clickable."""
    panel = el("studio-panel", {"w": "400", "h": "600"}, kids=[
        el("artifact-library", kids=[
            el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
                el("mat-icon", text="audio_magic_eraser"),
                el("button", {"aria-label": "Chat options", "aria-haspopup": "menu",
                              "x": "-36", "y": "300", "w": "40", "h": "40"}),
            ]),
        ]),
    ])
    got = _open(el("body", {"w": "1440", "h": "900"}, kids=[panel]))
    assert got["ret"]["opened"] is False
    assert got["clicks"] == []


def test_an_off_canvas_kebab_does_not_shadow_the_real_one():
    item = el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
        el("mat-icon", text="audio_magic_eraser"),
        el("button", {"aria-label": "More", "x": "-36", "y": "300",
                      "w": "40", "h": "40"}),
        el("button", {"aria-label": "More", "x": "668", "y": "398",
                      "w": "40", "h": "40", "id": "real"}),
    ])
    panel = el("studio-panel", {"w": "400", "h": "600"},
               kids=[el("artifact-library", kids=[item])])
    got = run_js(el("body", {"w": "1440", "h": "900"}, kids=[panel]),
                 research._NLM_OPEN_AUDIO_MENU_JS,
                 {"scopes": research._NLM_AUDIO_MENU_SCOPES,
                  "triggers": ['button[aria-label="More"]#real',
                               'button[aria-label="More"]']})
    # The first hook can only match the on-screen one; if the off-canvas button
    # were reachable the second hook would have taken it first in DOM order.
    assert got["ret"]["opened"] is True
    assert got["ret"]["hook"] == 'button[aria-label="More"]#real'


@pytest.mark.parametrize("x,y,clickable", [
    (668, 398, True),     # the captured audio kebab
    (-36, 300, False),    # the captured Chat options
    (-20, 300, True),     # straddling the edge, centre still on screen
    (1430, 300, False),   # past the right edge
    (300, 890, False),    # past the bottom edge
])
def test_the_gate_is_the_point_a_click_would_land_on(x, y, clickable):
    """Not "does it have a rect" and not "does it have an offsetParent" — a
    click lands on the centre, so the centre is what has to be reachable."""
    item = el("artifact-library-item", {"w": "360", "h": "90"}, kids=[
        el("mat-icon", text="audio_magic_eraser"),
        el("button", {"aria-label": "More", "x": str(x), "y": str(y),
                      "w": "40", "h": "40"}),
    ])
    got = _open(el("body", {"w": "1440", "h": "900"}, kids=[item]))
    assert got["ret"]["opened"] is clickable, (x, y)


# ── the icon ligature and the destructive neighbour ───────────────────────

def _pick(spec, want, deny=research._NLM_MENU_DENY):
    return run_js(spec, research._NLM_MENU_PICK_JS,
                  {"scopes": research._NLM_MENU_PANEL_SCOPES,
                   "rowSel": research._NLM_MENU_ROW_SEL,
                   "want": list(want), "deny": list(deny)})


def test_the_ligature_is_stripped_and_share_is_found():
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[_audio_menu()]),
                ("share", "share notebook"))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["label"] == "share"
    assert got["clicks"] == ["shareShare"]


def test_edit_rename_is_the_row_no_regex_can_repair():
    """⭐ `share Share` and `save_alt Download` fall to the doubled-token and
    snake_case regexes the NotebookLM click helper already carried. `edit
    Rename` falls to neither — the ligature and the label are different words —
    which is why the strip has to be structural."""
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[_audio_menu()]),
                ("rename",))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["label"] == "rename"


def test_without_the_icon_element_the_regex_fallback_still_covers_the_easy_ones():
    """Markup that does not tag its icons keeps the old behaviour — the regexes
    are a fallback, not dead weight."""
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        el("div", {"role": "menuitem"}, text="share Share"),
        el("div", {"role": "menuitem"}, text="save_alt Download"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("download",))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["label"] == "download"


def test_download_is_selected_by_label_and_delete_is_refused_outright():
    """Delete is two rows below Download in the captured menu. Selection is by
    label, never by index, and the destructive rows are removed from the pool
    before anything is chosen."""
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[_audio_menu()]),
                ("download",))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["label"] == "download"
    assert got["ret"]["blocked"] == ["delete"]
    assert got["clicks"] == ["save_altDownload"]


def test_a_destructive_row_is_refused_even_when_it_is_what_was_asked_for():
    """NotebookLM is detect-and-fail_phase only. The deny list outranks `want`,
    so no future caller can talk this picker into a delete."""
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[_audio_menu()]),
                ("delete",))
    assert got["ret"]["clicked"] is False
    assert got["ret"]["reason"] == "no_match"
    assert got["ret"]["blocked"] == ["delete"]
    assert got["clicks"] == []


def test_a_denied_row_cannot_be_reached_by_the_prefix_rung():
    """Exact match first, then prefix. A row that merely starts with the wanted
    word is still refused if it is destructive."""
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        _icon_row("delete", "Share and delete original"),
        _icon_row("share", "Share"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("share",))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["label"] == "share"
    assert got["clicks"] == ["shareShare"]


def test_the_exact_label_outranks_a_longer_row_that_merely_starts_with_it():
    """⚠ The fixtures above cannot reach this: when only one row matches, exact
    and prefix agree and a mutation that deleted the exact rung survives. The
    case that separates them is a menu carrying BOTH `Share notebook` and
    `Share` — which is what a Material share menu looks like — with the longer
    one first in DOM order."""
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        _icon_row("share", "Share notebook"),
        _icon_row("share", "Share"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("share",))
    assert got["ret"]["label"] == "share", (
        "the row whose label IS the wanted word must win over one that merely "
        "begins with it")


def test_the_doubled_token_fallback_is_what_makes_that_ranking_work_untagged():
    """⭐ The same menu without <mat-icon> elements. Without the doubled-token
    regex both labels keep their ligature (`share share notebook`, `share
    share`), neither is an exact match, and the prefix rung takes the FIRST —
    the wrong row. The regex is a fallback, not decoration."""
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        el("div", {"role": "menuitem"}, text="share Share notebook"),
        el("div", {"role": "menuitem"}, text="share Share"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("share",))
    assert got["ret"]["label"] == "share"


def test_the_first_panel_that_answers_is_the_only_one_read():
    """The panel scopes are ordered, and the ordering has to end the search.
    Without that, a stale overlay's rows join the live menu's in one pool and a
    row from the wrong surface can outrank the right one."""
    live = el("div", {"role": "menu", "w": "260", "h": "120"},
              kids=[_icon_row("share", "Share notebook")])
    stale = el("div", {"class": "cdk-overlay-pane", "w": "260", "h": "120"},
               kids=[_icon_row("share", "Share")])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[live, stale]), ("share",))
    assert got["ret"]["via"] == '[role="menu"]'
    assert got["ret"]["label"] == "share notebook", (
        "the exact match in the LATER panel must never be reachable — the first "
        "panel that yields rows ends the search")
    assert got["clicks"] == ["shareShare notebook"]


def test_the_prefix_rung_still_works_when_nothing_matches_exactly():
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        _icon_row("share", "Share notebook with anyone"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("share",))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["label"] == "share notebook with anyone"


def test_a_substring_never_answers_for_a_prefix():
    """"Delete this share" contains "share". It must not be a candidate — and
    not only because the deny list would catch this one."""
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        _icon_row("link", "Unlink this share"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("share",))
    assert got["ret"]["clicked"] is False
    assert got["clicks"] == []


def test_rows_are_read_from_the_open_panel_and_never_from_the_page():
    """The old Step 2 queried `[role="menuitem"], [role="option"], li, button`
    across the whole document and clicked the first text starting with
    "share" — the notebook's own Share button, mid-menu, among others."""
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[
        el("button", {"aria-label": "Share", "w": "80", "h": "32"}, text="Share"),
    ]), ("share",))
    assert got["ret"] == {"clicked": False, "reason": "no_menu_rows"}
    assert got["clicks"] == []


def test_the_panel_rows_win_over_an_identically_named_page_button():
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[
        el("button", {"aria-label": "Share", "w": "80", "h": "32"}, text="Share"),
        _audio_menu(),
    ]), ("share",))
    assert got["ret"]["clicked"] is True
    assert got["ret"]["via"] == '[role="menu"]'
    assert got["clicks"] == ["shareShare"]


def test_an_off_canvas_menu_row_is_not_pickable():
    menu = el("div", {"role": "menu", "w": "260", "h": "220"}, kids=[
        _icon_row("share", "Share", x="-200", y="300", w="180", h="40"),
    ])
    got = _pick(el("body", {"w": "1440", "h": "900"}, kids=[menu]), ("share",))
    assert got["ret"]["clicked"] is False
    assert got["clicks"] == []


def test_the_deny_list_is_the_pipelines_no_delete_constraint():
    assert set(research._NLM_MENU_DENY) >= {"delete", "remove", "trash"}, (
        "NotebookLM is detect-and-fail_phase only — the pipeline never deletes "
        "a card, a source or a notebook")


def test_the_share_call_site_takes_the_deny_default():
    src = code_only(inspect.getsource(research.run_phase3_audio))
    assert '_nlm_menu_pick(page, want=("share", "share notebook"))' in src, (
        "the call site must not pass its own deny list — the default is the "
        "constraint, and an override is how it would get lost")


# ── the acting surface ────────────────────────────────────────────────────

def test_the_download_prompt_warns_the_agent_off_delete():
    """No DOM download tier exists — Download is driven by the vision/CUA
    surface, so that is where the Delete adjacency has to be stated. It reads
    the menu as glyphs, not innerText, so the ligature is not its problem; the
    two-rows-below is."""
    p = prompts.make_prompt_audio_download("long")
    low = p.lower()
    assert "delete is two rows below download" in low
    assert "never click delete, remove or trash" in low
    assert "abort: cannot read menu" in p, (
        "an unreadable menu must abort rather than be clicked by position")


def test_the_delete_warning_is_on_every_length_variant():
    for length in ("short", "long", "default"):
        assert "NEVER click Delete" in prompts.make_prompt_audio_download(length), length
