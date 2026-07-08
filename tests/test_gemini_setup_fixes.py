"""Tests for the 2026-05-27 Gemini P2 setup + extraction fixes.

All four changes shipped this session are covered here:

  1. Clipboard permission granted browser-wide at browser bootstrap
     (`_grant_clipboard_permission` returns bool; `Browser.start` wires it).
     Root cause it fixes: P2 extraction (Gemini "Copy contents") ran without
     clipboard perms, so the write was denied and T1 fell to T2 every run.

  2. `setup_gemini_dr` "+" detection — the composer "+" is an SVG icon-morph
     button whose real aria-label is "Upload & tools" (NOT in the old
     add/attach/more whitelist). Now structure-based (anchor on the composer
     input, require a NEWLY-opened menu via a before/after delta), with the
     recent-chats sidebar "More options for <chat>" buttons excluded.

  3. `_gemini_select_flash_model` — selects the "3.5 Flash" model AND sets the
     "Thinking level" submenu to "Extended" (the pipeline wants "Flash
     Extended"). Menu rows are title+description concatenated ("3.5 FlashAll-
     around help"), so the model match must NOT anchor a trailing word
     boundary (the bug: a bare /\\bflash\\b/ can't match "flashall...").

  4. `PROMPT_GEMINI_DEEP_RESEARCH` (CUA fallback) realigned: Deep Research is at
     the TOP LEVEL of the "+" menu (2 clicks), with More tools as the 3-click
     fallback — the prompt previously drove "+ -> More tools" first.

Because the matching logic lives inside in-page JS strings (run by the real
browser, not importable into Python), the JS rules are covered by (a) source-
contract "alarm" tests that fail if the pattern is reverted, and (b) behavior
mirrors that replicate the JS predicate in Python and assert it against the
exact DOM strings captured from live Gemini.

Run:  pytest tests/test_gemini_setup_fixes.py -v
"""
import asyncio
import inspect
import os
import re
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────
# 1. Clipboard permission grant (real unit tests)
# ─────────────────────────────────────────────────────────────────────

class TestGrantClipboardPermission:
    """`_grant_clipboard_permission(page)` now returns True/False (it used to
    return None). The bool is what `Browser.start` logs at bootstrap."""

    def _page_with_cdp(self):
        page = mock.MagicMock()
        cdp = mock.MagicMock()
        cdp.send = mock.AsyncMock()
        cdp.detach = mock.AsyncMock()
        page.context.new_cdp_session = mock.AsyncMock(return_value=cdp)
        return page, cdp

    def test_returns_true_and_sends_clipboard_readwrite(self):
        import research
        page, cdp = self._page_with_cdp()
        result = _run(research._grant_clipboard_permission(page))
        assert result is True
        cdp.send.assert_awaited_once()
        args, _ = cdp.send.call_args
        assert args[0] == "Browser.grantPermissions"
        perms = args[1]["permissions"]
        assert "clipboardReadWrite" in perms
        assert "clipboardSanitizedWrite" in perms

    def test_detaches_cdp_session(self):
        import research
        page, cdp = self._page_with_cdp()
        _run(research._grant_clipboard_permission(page))
        cdp.detach.assert_awaited_once()

    def test_returns_false_on_failure(self):
        """A denied/raised CDP grant must NOT crash setup — returns False so
        the keyboard-typing paste fallback still applies."""
        import research
        page = mock.MagicMock()
        page.context.new_cdp_session = mock.AsyncMock(
            side_effect=Exception("no cdp session"))
        result = _run(research._grant_clipboard_permission(page))
        assert result is False

    def test_send_failure_returns_false(self):
        import research
        page = mock.MagicMock()
        cdp = mock.MagicMock()
        cdp.send = mock.AsyncMock(side_effect=Exception("grant rejected"))
        cdp.detach = mock.AsyncMock()
        page.context.new_cdp_session = mock.AsyncMock(return_value=cdp)
        assert _run(research._grant_clipboard_permission(page)) is False


class TestBrowserStartWiresClipboardGrant:
    """Source-contract: the grant must be invoked ONCE at browser bootstrap
    (not only inside verified_paste_brief — that gap was the original bug)."""

    def test_browser_start_calls_grant(self):
        import research
        src = inspect.getsource(research.Browser.start)
        assert "_grant_clipboard_permission(self.page)" in src

    def test_grant_helper_requests_readwrite(self):
        import research
        src = inspect.getsource(research._grant_clipboard_permission)
        assert "clipboardReadWrite" in src
        assert "Browser.grantPermissions" in src


# ─────────────────────────────────────────────────────────────────────
# 2. setup_gemini_dr "+" (Upload & tools) detection — source + mirrors
# ─────────────────────────────────────────────────────────────────────

class TestPlusDetectionSourceContract:
    """Alarm tests: fail if the structure-based "+" detection or its
    guardrails are reverted."""

    def _src(self):
        import research
        return inspect.getsource(research.setup_gemini_dr)

    def test_matches_upload_tools_label(self):
        # The real composer "+" aria-label is "Upload & tools".
        assert "includes('upload')" in self._src()

    def test_excludes_recent_chats_sidebar_menus(self):
        src = self._src()
        assert "actions-menu-button" in src
        assert "conversation-actions" in src
        assert "more options for" in src

    def test_menu_open_assertion_is_a_delta_not_absolute(self):
        # The mandatory "a menu actually opened" check compares the visible-
        # menu count AFTER the click against the baseline BEFORE it, so a
        # menu already on the page can't false-positive a dead click.
        src = self._src()
        assert "v > before" in src
        assert "_menu_before" in src

    def test_uses_candidate_tagging_and_cleanup(self):
        src = self._src()
        assert "data-dg-plus-cand" in src

    def test_constrains_candidates_left_of_input(self):
        # Position anchor: candidates must be on the composer input's row and
        # to its left (excludes send/mic on the right, sidebar handled above).
        src = self._src()
        assert "leftOfInput" in src
        assert "sameRow" in src


def _mirror_looks_plus(aria_label="", title="", text="", has_add_icon=False):
    """Python mirror of the in-page `looksPlus(b)` predicate (setup_gemini_dr).
    Kept in lock-step with the JS by the source-contract tests above."""
    a = (aria_label or "").lower()
    tt = (title or "").lower()
    tx = (text or "").strip()
    return (
        "upload" in a or a == "add" or a == "add files" or "add files" in a
        or a == "attach" or a == "attachments" or a == "more"
        or a == "more options" or tt == "add" or tt == "more"
        or "attach" in tt or tx == "+" or has_add_icon
    )


def _mirror_is_bad(aria_label="", title="", class_name="", data_test_id=""):
    """Python mirror of the in-page `isBad(b)` exclusion predicate."""
    lbl = ((aria_label or "") + " " + (title or "")).lower()
    if re.search(r"mic|microph|voice|dictat|speak|send|submit|stop|cancel", lbl):
        return True
    cls = (class_name or "").lower()
    tid = (data_test_id or "").lower()
    return (tid == "actions-menu-button" or "conversation-actions" in cls
            or bool(re.search(r"more options for", lbl)))


class TestPlusDetectionBehaviorMirror:
    """Mirrors of the JS predicates, asserted against the EXACT DOM strings
    captured from live Gemini (new-chat composer, 2026-05-27)."""

    def test_real_plus_button_is_a_candidate(self):
        # Captured: <button aria-label="Upload & tools" aria-haspopup="menu">
        assert _mirror_looks_plus(aria_label="Upload & tools") is True
        # ...and is NOT excluded (no data-test-id, no conversation-actions cls).
        assert _mirror_is_bad(
            aria_label="Upload & tools",
            class_name="mdc-icon-button mat-mdc-icon-button mat-badge",
            data_test_id="",
        ) is False

    def test_legacy_plus_labels_still_match(self):
        for lbl in ("Add", "Add files", "Attach", "Attachments", "More"):
            assert _mirror_looks_plus(aria_label=lbl) is True, lbl
        assert _mirror_looks_plus(text="+") is True
        assert _mirror_looks_plus(has_add_icon=True) is True

    def test_sidebar_conversation_menus_are_excluded(self):
        # Captured: <button data-test-id="actions-menu-button"
        #   class="... gem-conversation-actions-menu-button"
        #   aria-label="More options for Kalki 2">  (x=244, on composer row)
        assert _mirror_is_bad(
            aria_label="More options for Kalki 2",
            class_name="mdc-icon-button mat-mdc-menu-trigger "
                       "gem-conversation-actions-menu-button mat-unthemed",
            data_test_id="actions-menu-button",
        ) is True

    def test_send_and_mic_excluded(self):
        assert _mirror_is_bad(aria_label="Send message") is True
        assert _mirror_is_bad(aria_label="Use microphone") is True


# ─────────────────────────────────────────────────────────────────────
# 3. _gemini_select_flash_model — 3.5 Flash + Extended thinking
# ─────────────────────────────────────────────────────────────────────

def _make_model_pick_eval(opened, picked, tl_seq, ext_picked, mode_txt):
    """Dispatch page.evaluate by a distinctive token in each JS block so the
    test isn't coupled to the exact call ORDER/COUNT (the Extended step may
    re-open + retry). Returns a sync fn usable as AsyncMock side_effect."""
    tl_iter = iter(tl_seq)

    def fake_eval(js, *a, **k):
        if "inViewableArea" in js:            # Step 1: open the model menu
            return opened
        if "doClick" in js:                    # Step 2: ranker picks+clicks the row
            # Phoenix B2: the ranker returns a dict (was a bare string for the
            # frozen /3.5 flash/ pick). `clicked` mirrors a successful pick.
            return {"pick": picked, "version": 3.5, "legacy": picked,
                    "clicked": bool(picked)}
        if "thinking level" in js:             # Step 3a: open Thinking submenu
            return next(tl_iter)
        if "startsWith('extended')" in js:     # Step 3b: pick Extended
            return ext_picked
        if "aria-label" in js:                 # verify: read the mode button
            return mode_txt
        if "bard-mode-menu-button" in js:      # reopen guard
            return True
        return None

    return fake_eval

def _model_page(eval_fn):
    page = mock.MagicMock()
    page.evaluate = mock.AsyncMock(side_effect=eval_fn)
    page.keyboard = mock.MagicMock()
    page.keyboard.press = mock.AsyncMock()
    return page


class TestGeminiModelPickFlow:
    """Drives `_gemini_select_flash_model` with mocked page.evaluate results
    (asyncio.sleep + log patched out) to lock the orchestration contract."""

    def _call(self, page):
        import research
        with mock.patch.object(research.asyncio, "sleep", mock.AsyncMock()), \
             mock.patch.object(research, "log", mock.MagicMock()) as logm:
            result = _run(research._gemini_select_flash_model(page))
        return result, logm

    def test_model_and_extended_returns_true(self):
        eval_fn = _make_model_pick_eval(
            opened=True, picked="3.5 flashall-around help",
            tl_seq=[True], ext_picked="extendedcomplex problem solving",
            mode_txt="open mode picker, currently flash extended flash extended")
        result, logm = self._call(_model_page(eval_fn))
        assert result is True
        logged = " ".join(str(c) for c in logm.call_args_list).lower()
        assert "extended" in logged  # Thinking-level step logged

    def test_model_picked_but_extended_missing_still_true(self):
        """Extended is best-effort: if the submenu/option can't be found
        (even after a reopen), the model is still selected -> return True,
        run proceeds on the default thinking level."""
        eval_fn = _make_model_pick_eval(
            opened=True, picked="3.5 flashall-around help",
            tl_seq=[False, False],  # first try + post-reopen retry both miss
            ext_picked="", mode_txt="currently flash")
        result, logm = self._call(_model_page(eval_fn))
        assert result is True
        logged = " ".join(str(c) for c in logm.call_args_list).lower()
        assert "thinking level" in logged  # the WARN about the missing submenu

    def test_no_model_row_returns_false(self):
        eval_fn = _make_model_pick_eval(
            opened=True, picked="", tl_seq=[True],
            ext_picked="", mode_txt="")
        result, _ = self._call(_model_page(eval_fn))
        assert result is False

    def test_no_dropdown_button_returns_false(self):
        eval_fn = _make_model_pick_eval(
            opened=False, picked="3.5 flash", tl_seq=[True],
            ext_picked="extended", mode_txt="")
        result, _ = self._call(_model_page(eval_fn))
        assert result is False

    def test_no_model_row_closes_menu_with_escape(self):
        page = _model_page(_make_model_pick_eval(
            opened=True, picked="", tl_seq=[True], ext_picked="", mode_txt=""))
        self._call(page)
        page.keyboard.press.assert_any_await("Escape")


class TestGeminiModelPickSourceContract:
    def _src(self):
        import research
        return inspect.getsource(research._gemini_select_flash_model)

    def test_sets_extended_thinking_level(self):
        src = self._src()
        assert "thinking level" in src.lower()
        assert "Extended" in src

    def test_targets_three_five_flash_not_bare_flash(self):
        # Guards against re-introducing the /\\bflash\\b/ bug: the model match
        # must anchor on "3.5" (with \\s* for the space), NOT a bare flash with
        # a trailing word boundary (which can't match "3.5 FlashAll-around").
        src = self._src()
        assert "3" in src and "flash" in src.lower()
        # The fix's rationale comment is a stable marker of the corrected match.
        assert "trailing word boundary" in src

    # ── #919 (2026-07-08): 'Thinking level' vanished from the menu overnight
    # (last hit 07-07 21:55, misses 07-08 02:02 + 11:17 — user screenshot
    # showed the run on plain Flash). Hardened walk + self-documenting miss.

    def test_919_trigger_match_broadened_beyond_literal_thinking_level(self):
        src = self._src()
        assert "t.startsWith('thinking')" in src, (
            "a renamed trigger ('Thinking', 'Thinking: Standard') must still "
            "match — the literal 'thinking level' text is what vanished")

    def test_919_direct_extended_fallback_is_overlay_scoped(self):
        src = self._src()
        assert "directExtended" in src
        assert "cdk-overlay-container" in src, (
            "the direct 'Extended…' click must be pinned to an OPEN overlay "
            "menu — never bare page text (the brief itself can contain the "
            "word 'extended')")
        assert "t.length >= 60" in src, "container-node guard"

    def test_919_reopen_retry_hovers_flash_row(self):
        src = self._src()
        assert "hoverFlashRow" in src, (
            "row-nested Thinking submenus only render on hover of the "
            "selected model row — the reopen-retry must hover first")

    def test_919_menu_dump_on_every_miss(self):
        src = self._src()
        assert "menuDump" in src
        assert src.count("_dump_thinking_menu(") >= 4, (
            "define + first-miss + final-miss + extended-option-miss — every "
            "miss path must leave a menu snapshot in backend.log "
            "(instrument-with-logs)")
        assert "thinking-menu snapshot" in src

    def test_919_no_literal_backspace_in_model_pick_strings(self):
        # #913 VERB_GATE lesson: a lone \b in a NON-raw Python string parses
        # to a literal backspace and the JS regex silently never matches.
        import ast
        import textwrap
        import research
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(research._gemini_select_flash_model)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "\x08" not in node.value, (
                    "_gemini_select_flash_model embeds a literal backspace — "
                    "a lone \\b in a non-raw string; escape it as \\\\b")


class TestGeminiDirectExtendedFallbackFlow:
    """#919 functional: when the 'Thinking level' trigger is gone but a
    direct 'Extended…' item exists in the open menu, the fallback clicks it,
    confirmation is recorded, and NO 'submenu not found' WARN fires."""

    def test_direct_extended_path_confirms_without_warn(self):
        import research
        base = _make_model_pick_eval(
            opened=True, picked="3.5 flashall-around help",
            tl_seq=[False], ext_picked="",
            mode_txt="currently flash extended")

        def fake_eval(js, *a, **k):
            if "directExtended" in js:
                return "extended thinking"
            if "menuDump" in js or "hoverFlashRow" in js:
                return None
            return base(js, *a, **k)

        page = _model_page(fake_eval)
        with mock.patch.object(research.asyncio, "sleep", mock.AsyncMock()), \
             mock.patch.object(research, "log", mock.MagicMock()) as logm:
            result = _run(research._gemini_select_flash_model(page))
        assert result is True
        logged = " ".join(str(c) for c in logm.call_args_list).lower()
        assert "direct extended item clicked" in logged
        assert "submenu not found" not in logged
        assert research._P2_THINKING_STATE.get("gemini", {}).get("thinking") is True


# Mirror of the model-row matcher, asserted against captured DOM row text.
_MODEL_RE = re.compile(r"3\.5\s*flash", re.I)


def _mirror_model_reject(t):
    t = t.lower()
    return ("lite" in t) or ("deep think" in t) or bool(re.search(r"\bpro\b", t))


def _mirror_is_extended(t):
    t = t.strip().lower()
    if t.startswith("standard"):
        return False
    return t.startswith("extended") or bool(re.search(r"\bextended\b", t))


class TestModelMatchBehaviorMirror:
    """Captured model-menu rows are title+description concatenated (NO
    separator) — these mirror tests pin why the match avoids a trailing
    word boundary."""

    # Exact captured rows (lowercased as the JS does):
    ROW_FLASH = "3.5 flashall-around help"
    ROW_LITE = "3.1 flash-litefastest answers"
    ROW_PRO = "3.1 proadvanced math and code"

    def test_three_five_flash_row_matches(self):
        assert _MODEL_RE.search(self.ROW_FLASH)

    def test_bare_flash_word_boundary_would_fail_the_real_row(self):
        # This is the bug that /3\\.5\\s*flash/ fixes: the concatenated
        # description means there's no word boundary after "flash".
        assert re.search(r"\bflash\b", self.ROW_FLASH, re.I) is None

    def test_does_not_match_lite_or_pro_rows(self):
        assert _MODEL_RE.search(self.ROW_LITE) is None
        assert _MODEL_RE.search(self.ROW_PRO) is None
        # Flash-Lite is also caught by the explicit reject guard.
        assert _mirror_model_reject(self.ROW_LITE) is True

    def test_extended_thinking_row_selected_standard_skipped(self):
        # Captured submenu rows (concatenated title+description):
        assert _mirror_is_extended("extendedcomplex problem solving") is True
        assert _mirror_is_extended("standardbest for most questions") is False
        # The "Thinking level" trigger row itself must NOT be taken as the
        # Extended option even though it contains the substring "extended"
        # once the level has been set.
        assert _mirror_is_extended("thinking levelextended") is False


# ─────────────────────────────────────────────────────────────────────
# 4. CUA fallback prompt realignment
# ─────────────────────────────────────────────────────────────────────

class TestCuaFallbackPromptRealignment:
    """`PROMPT_GEMINI_DEEP_RESEARCH` must drive the current 2-click top-level
    path (+ -> Deep Research), with More tools as the 3-click fallback, and
    name the real "+" button label so CUA can find it."""

    def test_primary_path_is_top_level_two_click(self):
        from prompts import PROMPT_GEMINI_DEEP_RESEARCH
        assert "TOP LEVEL" in PROMPT_GEMINI_DEEP_RESEARCH
        assert "2 clicks" in PROMPT_GEMINI_DEEP_RESEARCH

    def test_more_tools_is_the_secondary_path(self):
        from prompts import PROMPT_GEMINI_DEEP_RESEARCH
        assert "More tools" in PROMPT_GEMINI_DEEP_RESEARCH
        assert "3 clicks" in PROMPT_GEMINI_DEEP_RESEARCH

    def test_names_the_upload_tools_button(self):
        from prompts import PROMPT_GEMINI_DEEP_RESEARCH
        assert "Upload & tools" in PROMPT_GEMINI_DEEP_RESEARCH
