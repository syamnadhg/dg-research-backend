"""NotebookLM on 2026-08-06: nothing was uploaded, and nothing was shared.

    [12:12:34] DOM upload: chooser never opened for gemini.md after pressing
      'or drop your filespdf, images, docs, audio, and moreuploadUpload fileslinkvideo_'
    …the same for claude.md and chatgpt.md, and the same 6/6 across two runs.

    [13:20:41] no 'Anyone with the link' option to click … dialog=yes
      option-rows=0 control=Search results rows=[]

TWO defects, both of the family this file keeps meeting.

⭐ THE UPLOAD. That 80-character label is not a control's name — it is the
CONCATENATED TEXT OF A CONTAINER. `_NLM_CLICK_JS`'s candidate list includes
`[class*="dropzone" i]`, `querySelectorAll` with a comma list returns DOCUMENT
order, and an ancestor always precedes the descendant it wraps — so the
Add-sources dropzone matched /upload file/i through its own children and won
before the "Upload files" chip was ever examined.

⭐ AND IT COULD NOT HAVE WORKED ANYWAY. The press was `el.click()` inside
`page.evaluate`. A synthetic click carries no USER ACTIVATION, and a native file
chooser is gated on exactly that — so this path could never open one however
well it aimed. This project already proved the same thing on three other
surfaces and built `_sr_real_click` (JS marks, Playwright presses) for it; the
NotebookLM tier was the only DOM path that never adopted it.

⭐ THE SHARE. `control=Search results` is the PEOPLE PICKER's listbox label. The
diagnostic took `scope.querySelector(TRIGGERS)` — the first combobox in document
order — and on a Google-style share surface the people picker comes first. Every
conclusion in that log line was about the wrong control. The dialog query was
also ungated on size while its own sibling that reads the link requires
>200x100, which is why one line said `dialog=yes` and the next said `no_dialog`
one second later.
"""

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402

CLICK_JS = research._NLM_CLICK_JS
DIAG_JS = research._NLM_ACCESS_DIAG_JS
MARK = research._SR_CLICK_MARK

# Verbatim from both runs' logs — the container's own concatenated text.
CONTAINER_TEXT = ("or drop your filespdf, images, docs, audio, and "
                  "moreuploadUpload fileslinkvideo_")


def _add_sources_dialog():
    """The Add-sources surface: a dropzone container wrapping the real chip.

    Document order matters and is the point — the container comes first.
    """
    return el("body", kids=[
        el("div", {"role": "dialog", "w": "600", "h": "400", "x": "100", "y": "50"},
           kids=[
               el("div", {"class": "dropzone", "w": "560", "h": "300",
                          "x": "120", "y": "80"}, kids=[
                   el("div", {"w": "300", "h": "20", "x": "120", "y": "90"},
                      "or drop your files"),
                   el("div", {"w": "300", "h": "20", "x": "120", "y": "110"},
                      "pdf, images, docs, audio, and more"),
                   el("button", {"w": "160", "h": "40", "x": "150", "y": "200"},
                      "upload Upload files"),
                   el("button", {"w": "160", "h": "40", "x": "330", "y": "200"},
                      "link video_"),
               ]),
           ]),
    ])


def _pick(spec, patterns):
    return run_js(spec, CLICK_JS, list(patterns))


class TestTheUploadPressAimsAtTheChip:

    def test_the_container_no_longer_wins(self):
        res = _pick(_add_sources_dialog(), [r"upload file", r"\bupload\b"])["ret"]
        assert res, "nothing matched at all"
        assert res["label"] != CONTAINER_TEXT[:80]
        assert res["tag"] == "BUTTON", res

    def test_the_label_is_the_chip_not_a_paragraph_of_children(self):
        res = _pick(_add_sources_dialog(), [r"upload file"])["ret"]
        assert "Upload files" in res["label"], res
        assert "drop your files" not in res["label"], res

    def test_the_container_would_still_have_matched(self):
        # The leaf preference is what saves us, not a narrower pattern — if the
        # pattern had simply stopped matching the container, the test above
        # would pass for the wrong reason.
        assert "upload" in CONTAINER_TEXT.lower()

    def test_nothing_is_clicked_in_the_page(self):
        # A synthetic click cannot open a native chooser. The JS must mark only.
        out = _pick(_add_sources_dialog(), [r"upload file"])
        assert out["clicks"] == [], out["clicks"]

    def test_the_chosen_element_is_marked_for_playwright(self):
        assert "setAttribute(MARK" in CLICK_JS
        assert f'const MARK = "{MARK}"' in CLICK_JS

    def test_the_js_no_longer_clicks_at_all(self):
        # Comments stripped: the note explaining WHY the click is gone naturally
        # contains the string, and matching it would make this guard unkillable.
        code = "\n".join(ln.split("//")[0] for ln in CLICK_JS.split("\n"))
        assert ".click()" not in code, (
            "a synthetic click inside page.evaluate has no user activation and "
            "can never open a file chooser"
        )

    def test_a_miss_returns_nothing_rather_than_a_stray_mark(self):
        out = _pick(_add_sources_dialog(), [r"absolutely nothing like this"])
        assert out["ret"] is None
        assert out["clicks"] == []


class _MarkingPage:
    """A page whose `evaluate` answers as the marking JS does, and whose
    file-chooser wait can be made to succeed or time out."""

    _DEFAULT = {"label": "Upload files", "tag": "BUTTON"}

    def __init__(self, picked=_DEFAULT, chooser=True):
        # Sentinel default, not `None`-means-default: `picked=None` is a real
        # case (the JS matched nothing) and must be expressible.
        self._picked = picked
        self._chooser = chooser

    async def evaluate(self, js, arg=None):
        return self._picked

    def expect_file_chooser(self, timeout=0):
        # ⚠ Modelled on the real thing: Playwright ENTERS immediately, the body
        # does the pressing, and the wait for the event happens on EXIT. A fake
        # that raised on entry would skip the press and make a timed-out chooser
        # look like a missing one — the test double answering a call the real
        # page could never make, which this project has been caught by before.
        ok = self._chooser

        class _Ctx:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, exc_type, *a):
                if exc_type is None and not ok:
                    raise TimeoutError("no chooser appeared")
                return False
        return _Ctx()


class TestThePressGoesThroughTheRealClicker:

    def _drive(self, monkeypatch, **kw):
        """Run the real helper, recording every press it makes."""
        pressed = []

        async def _fake_press(page, value, *, tag, **rest):
            pressed.append(value)
            return "playwright"
        monkeypatch.setattr(research, "_sr_real_click", _fake_press)
        page = _MarkingPage(chooser=kw.pop("chooser", True))
        label = asyncio.run(research._nlm_click_first(page, [r"upload file"], **kw))
        return label, pressed

    @pytest.mark.parametrize("expect_chooser", [False, True])
    def test_every_mode_actually_presses(self, monkeypatch, expect_chooser):
        # ⭐ Mutation escape. A source check for `_sr_real_click(` was satisfied by
        # the chooser branch alone, so deleting the press from the ORDINARY path —
        # the one that opens the notebook and the Add-sources dialog — survived.
        # Two chains, one substring: the same shape this project has been bitten
        # by before. Drive both and count the presses.
        _label, pressed = self._drive(monkeypatch, expect_chooser=expect_chooser)
        assert pressed == ["nlm-click"], (
            f"expect_chooser={expect_chooser} marked an element and never "
            f"pressed it — the mark is left on the page and nothing is clicked"
        )

    def test_the_chooser_mode_reports_the_chooser_opening(self, monkeypatch):
        label, _pressed = self._drive(monkeypatch, expect_chooser=True)
        assert label.endswith("|chooser"), label

    def test_a_chooser_that_never_opens_still_returns_the_label(self, monkeypatch):
        # The caller's own retry rungs need to know WHICH control was pressed.
        label, pressed = self._drive(monkeypatch, expect_chooser=True, chooser=False)
        assert label == "Upload files"
        assert pressed == ["nlm-click"], "a timed-out chooser must not skip the press"

    def test_nothing_is_pressed_when_nothing_matched(self, monkeypatch):
        pressed = []

        async def _fake_press(page, value, *, tag, **rest):
            pressed.append(value)
            return "playwright"
        monkeypatch.setattr(research, "_sr_real_click", _fake_press)
        page = _MarkingPage(picked=None)
        assert asyncio.run(research._nlm_click_first(page, [r"nope"])) == ""
        assert pressed == []

    def test_the_helper_presses_with_playwright(self):
        src = inspect.getsource(research._nlm_click_first)
        assert "_sr_real_click(" in src, (
            "the NotebookLM tier was the only DOM path that never adopted the "
            "mark-then-press primitive this project built for exactly this"
        )

    def test_the_upload_call_site_arms_the_chooser_wait(self):
        src = inspect.getsource(research._nlm_dom_add_files)
        assert "expect_chooser=True" in src
        assert "expect_file_chooser" in inspect.getsource(research._nlm_click_first)

    def test_an_opened_chooser_is_reported_as_a_fact(self):
        # "The chooser never opened" was an inference from a ten-second wait.
        src = inspect.getsource(research._nlm_dom_add_files)
        assert "file chooser opened from" in src

    def test_the_chooser_suffix_is_stripped_before_the_label_is_used(self):
        src = inspect.getsource(research._nlm_dom_add_files)
        assert '|chooser' in src and 'clicked[: -len("|chooser")]' in src


def _share_surface(*, people_first=True, dialog_size=("600", "400")):
    """A Google-style share dialog: people picker first, access control second."""
    picker = el("div", {"role": "combobox", "w": "400", "h": "40",
                        "x": "120", "y": "90"}, "Search results")
    access = el("div", {"role": "combobox", "w": "300", "h": "40",
                        "x": "120", "y": "200"}, "Restricted")
    kids = [picker, access] if people_first else [access, picker]
    w, h = dialog_size
    return el("body", kids=[
        el("div", {"role": "dialog", "w": w, "h": h, "x": "100", "y": "50"},
           kids=kids),
    ])


class TestTheShareDiagnosticNamesTheRightControl:

    def _diag(self, spec):
        return run_js(spec, DIAG_JS)["ret"]

    def test_the_people_picker_no_longer_wins(self):
        d = self._diag(_share_surface())
        assert d["access"] != "Search results", d
        assert "Restricted" in d["access"], d

    def test_it_says_how_it_chose(self):
        assert self._diag(_share_surface())["accessBy"] == "text"

    def test_document_order_is_still_the_fallback(self):
        # Nothing on the surface names an access level — then the first control
        # is all there is, and the log must say so rather than imply a match.
        spec = el("body", kids=[
            el("div", {"role": "dialog", "w": "600", "h": "400",
                       "x": "100", "y": "50"}, kids=[
                el("div", {"role": "combobox", "w": "400", "h": "40",
                           "x": "120", "y": "90"}, "Search results"),
            ]),
        ])
        d = self._diag(spec)
        assert d["accessBy"] == "first"
        assert d["access"] == "Search results"

    def test_the_order_of_the_two_controls_stops_mattering(self):
        for people_first in (True, False):
            d = self._diag(_share_surface(people_first=people_first))
            assert "Restricted" in d["access"], (people_first, d)

    def test_it_reports_how_many_controls_it_had_to_choose_between(self):
        assert self._diag(_share_surface())["triggers"] == 2


class TestTheDialogMustBeARealOne:

    def _diag(self, spec):
        return run_js(spec, DIAG_JS)["ret"]

    def test_a_zero_sized_dialog_is_not_a_dialog(self):
        # The stable phantom: `dialog=yes` here and `no_dialog` from the reader
        # one second later, byte-identical in two runs seven hours apart.
        spec = el("body", kids=[
            el("div", {"role": "dialog", "w": "0", "h": "0"}, kids=[]),
        ])
        assert self._diag(spec)["dialog"] is False

    def test_a_real_dialog_still_counts(self):
        assert self._diag(_share_surface())["dialog"] is True

    def test_a_phantom_does_not_shadow_the_real_one(self):
        spec = el("body", kids=[
            el("div", {"role": "dialog", "w": "0", "h": "0"}, kids=[]),
            el("div", {"role": "dialog", "w": "600", "h": "400",
                       "x": "100", "y": "50"}, kids=[
                el("div", {"role": "combobox", "w": "300", "h": "40",
                           "x": "120", "y": "200"}, "Restricted"),
            ]),
        ])
        d = self._diag(spec)
        assert d["dialog"] is True
        assert "Restricted" in d["access"], d

    def test_the_gate_matches_the_sibling_that_reads_the_link(self):
        # The two disagreeing about what a dialog is was the whole inconsistency.
        assert "r.width > 200 && r.height > 100" in DIAG_JS
        assert "width > 200 && height > 100" in research._NLM_SHARE_LINK_READ_JS \
            or "r.width > 200" in research._NLM_SHARE_LINK_READ_JS


class TestTheSafetyPass:
    """2026-08-06, after the second e2e: three symptoms this wave introduced."""

    def test_the_press_gives_up_fast_enough_to_be_a_rung(self):
        # 4s x2 was eight seconds of stall on controls the old synthetic click
        # handled. A ladder's first rung has to fail quickly or it is a wall.
        assert research._NLM_PRESS_TIMEOUT_MS <= 1500, research._NLM_PRESS_TIMEOUT_MS

    def test_both_press_sites_use_the_short_timeout(self):
        src = inspect.getsource(research._nlm_click_first)
        assert src.count("_NLM_PRESS_TIMEOUT_MS") == 2, (
            "the chooser path and the ordinary path must both fall back fast"
        )

    def test_the_upload_loop_reopens_the_picker_between_files(self):
        # Setting a file on the revealed input closes the dialog; the next
        # iteration then found no Upload control and the loop broke, abandoning
        # two of three files in the same second.
        src = inspect.getsource(research._nlm_dom_add_files)
        # There are TWO `for p in paths:` loops; the chooser fallback is the one
        # that follows `fired_any = False`. Anchoring on the bare `for` found the
        # other one and the test failed against a correct fix.
        i = src.index("fired_any = False")
        block = src[i:i + 900]
        assert "if fired_any:" in block, block
        assert "add source" in block


class TestReachIsChosenByTheCaller:
    """Widening a shared helper changed behaviour for five consumers at once."""

    def test_the_helper_takes_a_reach_flag(self):
        import inspect as _i
        assert "include_blank" in _i.signature(
            research._chatgpt_surface_frame_targets).parameters

    def test_the_walker_that_clicks_keeps_the_narrow_reach(self):
        src = inspect.getsource(research.scrape_progress_chatgpt)
        assert "include_blank=False" in src, (
            "this walker dispatches synthetic clicks inside the frames it "
            "visits; it must not reach further than it did before"
        )

    def test_the_readers_still_get_the_wide_reach(self):
        # The completion detector's whole fix depends on it.
        src = inspect.getsource(research.detect_completion_chatgpt)
        assert "_chatgpt_surface_frame_targets(page)" in src
        assert "include_blank=False" not in src

    def test_the_narrow_reach_really_is_narrower(self):
        class _F:
            def __init__(self, url):
                self.url = url

        class _P:
            def __init__(self):
                self.main_frame = _F("https://chatgpt.com/c/x")
                self.frames = [self.main_frame, _F("about:blank"),
                               _F("https://x.oaiusercontent.com/s")]
        page = _P()
        wide = research._chatgpt_surface_frame_targets(page)
        narrow = research._chatgpt_surface_frame_targets(page, include_blank=False)
        assert len(wide) == 3 and len(narrow) == 2
        assert not any(getattr(t, "url", "") == "about:blank" for t in narrow)
