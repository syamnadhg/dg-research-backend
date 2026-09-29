"""Mutation harness — ChatGPT's new page (2026-09-28): the markers, the checked
submit, "sent" means our prompt, and the CUA's keys on macOS.

⛔⛔ WHAT THIS CODE DECIDES.
  M* — the ONE set of ChatGPT page markers: each list must carry the NEW page's
       marker next to the old one, or that step goes blind on the new page.
  R* — the consumers read the markers: the census and its turn test, the
       scraper's own host read (reply length, links, headings, model), the done
       probe, the brief extractor, the first-message reader, the new-chat count,
       the stream observer, the session-expiry composer check.
  S* — the Phase 1 submit and what may count as sent: the menu is closed by the
       submit's own Escape, the box is found through the whole marker set and
       CLICKED before typing, leftover text is cleared first, the typing is READ
       BACK and a mismatch is retyped once and then nothing is sent, the select-
       all is the platform's, "sent" needs the last user message to start with
       the prompt (in the submit, the verifier, the CUA confirm), the CUA fix
       runs only when the box holds the prompt or nothing, the CUA fallback only
       places the caret and never runs after Send was pressed, and ctrl+a/c/v/x/z
       are Command on macOS. The comparison folds what a rich-text box does to
       typing (curled quotes, "- " lines made bullets) and nothing else.

⛔ THE STATIC MARKER PIN IS DESELECTED (`-k "not every_marker_accepts"`). It
would kill every M* mutant by reading the constant, and a harness that scores
kills a pin made cannot say whether a single consumer noticed. Every M* here
must die on BEHAVIOUR — a real-Chrome test against the rebuilt page.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline
is not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/chatgpt_new_page_0928_mutants.py
  .venv/bin/python .mutants/chatgpt_new_page_0928_mutants.py S5 S8
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
PROMPTS = "prompts.py"

TESTS = ["tests/test_chatgpt_new_page_0928.py", "tests/test_p1_no_deep_research_923.py",
         "tests/test_vision_act_wiring.py"]
DESELECT = "not every_marker_accepts"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ M — the markers carry the new page ═════════════════════════════════
    ("M1", RESEARCH, "⛔⛔ the composer marker loses the new box — \"no textarea found\" "
     "again, and nothing is typed",
     [("                        'div.ProseMirror[contenteditable=\"true\"][role=\"textbox\"], '\n"
       "                        '[contenteditable=\"true\"][aria-label=\"Ask ChatGPT\"], '\n",
       "")]),
    ("M2", RESEARCH, "⛔⛔ the user marker loses the new bubble — the census says \"no "
     "user message on screen\" and \"sent\" can never be confirmed",
     [("CHATGPT_USER_MSG_SEL = ('[data-message-author-role=\"user\"], '\n"
       "                        '[data-user-message-bubble=\"true\"]')",
       "CHATGPT_USER_MSG_SEL = ('[data-message-author-role=\"user\"]')")]),
    ("M3", RESEARCH, "⛔ the reply marker loses the new reply — its length, links and "
     "headings read zero",
     [("CHATGPT_ASSISTANT_MSG_SEL = ('[data-message-author-role=\"assistant\"], '\n"
       "                             '[data-markdown-text-style=\"assistant-message\"]')",
       "CHATGPT_ASSISTANT_MSG_SEL = ('[data-message-author-role=\"assistant\"]')")]),
    ("M4", RESEARCH, "⛔⛔ the reply-text marker loses the new root — Phase 1 extracts "
     "NOTHING from a finished brief",
     [("CHATGPT_REPLY_TEXT_SEL = ('[data-message-author-role=\"assistant\"] .markdown, '\n"
       "                          '[data-markdown-text-style=\"assistant-message\"]')",
       "CHATGPT_REPLY_TEXT_SEL = ('[data-message-author-role=\"assistant\"] .markdown')")]),
    ("M5", RESEARCH, "⛔ the any-message count is blind on the new page — a long thread "
     "reads as a fresh chat",
     [("CHATGPT_ANY_MSG_SEL = ('[data-message-author-role], '\n"
       "                       '[data-user-message-bubble=\"true\"], '\n"
       "                       '[data-markdown-text-style=\"assistant-message\"]')",
       "CHATGPT_ANY_MSG_SEL = ('[data-message-author-role]')")]),
    ("M6", RESEARCH, "the turn marker loses the new turn — the census reads the reply's "
     "own label as outside every turn",
     [("CHATGPT_TURN_SEL = '[data-testid^=\"conversation-turn\"], [data-turn-key]'",
       "CHATGPT_TURN_SEL = '[data-testid^=\"conversation-turn\"]'")]),
    ("M7", RESEARCH, "⛔ the Send marker loses the new Send — the submit falls back to "
     "Enter on every send",
     [("                    'button[aria-label=\"Send prompt\"], '\n"
       "                    'button[aria-label=\"Send\"]')",
       "                    'button[aria-label=\"Send prompt\"]')")]),
    ("M8", RESEARCH, "the Stop marker loses the new Stop — the named composer check goes "
     "blind and only the loose aria scan is left",
     [("CHATGPT_STOP_SEL = ('button[data-testid=\"stop-button\"], '\n"
       "                    'button[aria-label=\"Stop\"], '\n",
       "CHATGPT_STOP_SEL = ('button[data-testid=\"stop-button\"], '\n")]),
    ("M9", RESEARCH, "the model marker loses the new button — the scraper reads no model",
     [("CHATGPT_MODEL_TRIGGER_SEL = ('[data-testid=\"model-selector\"], '\n"
       "                             'button[aria-label=\"Select ChatGPT model\"][aria-haspopup=\"menu\"]')",
       "CHATGPT_MODEL_TRIGGER_SEL = ('[data-testid=\"model-selector\"]')")]),

    # ═══ R — the consumers read the markers ═════════════════════════════════
    ("R1", RESEARCH, "⛔⛔ the picker's census is back on the old user marker — "
     "\"structural pass DID NOT RUN (no user message on screen)\"",
     [("        let lub = -1;\n        try {\n            document.querySelectorAll('__CG_USER__')",
       "        let lub = -1;\n        try {\n            document.querySelectorAll("
       "'[data-message-author-role=\"user\"]')")]),
    ("R2", RESEARCH, "⛔ the thread snapshot's lub is back on the old marker — every miss "
     "line reads lub -1",
     [("        let lub = -1;\n        document.querySelectorAll('__CG_USER__')",
       "        let lub = -1;\n        document.querySelectorAll('[data-message-author-role=\"user\"]')")]),
    ("R3", RESEARCH, "the inline walker's lub is back on the old marker",
     [("        main.querySelectorAll('__CG_USER__').forEach(u => {",
       "        main.querySelectorAll('[data-message-author-role=\"user\"]').forEach(u => {")]),
    ("R4", RESEARCH, "⛔ the scraper's host read of the reply length is back on the old "
     "marker",
     [("            const msgs = document.querySelectorAll('__CG_ASSISTANT__');\n"
       "            if (msgs.length > 0) r.partial_text_len",
       "            const msgs = document.querySelectorAll('[data-message-author-role=\"assistant\"]');\n"
       "            if (msgs.length > 0) r.partial_text_len")]),
    ("R5", RESEARCH, "⛔ the scraper's reply links are back on the old marker — sources 0",
     [("                within('__CG_ASSISTANT__', 'a[href*=\"http\"]') + ', ' +",
       "                '[data-message-author-role=\"assistant\"] a[href*=\"http\"], ' +")]),
    ("R6", RESEARCH, "the scraper's reply headings are back on the old marker",
     [("                ['h1', 'h2', 'h3'].map(h => within('__CG_ASSISTANT__', h)).join(', '));",
       "                '[data-message-author-role=\"assistant\"] h1');")]),
    ("R7", RESEARCH, "the scraper's model read is back on the old testid",
     [("            const modelEl = document.querySelector('__CG_MODEL__, .model-label');",
       "            const modelEl = document.querySelector('[data-testid=\"model-selector\"], .model-label');")]),
    ("R8", RESEARCH, "⛔ the done probe's reply length is back on the old marker — the "
     "flatness gate measures 0 forever",
     [("    const msgs = document.querySelectorAll('__CG_ASSISTANT__');\n    const assistantLen",
       "    const msgs = document.querySelectorAll('[data-message-author-role=\"assistant\"]');\n"
       "    const assistantLen")]),
    ("R9", RESEARCH, "⛔⛔ the brief extractor is back on `:last-of-type .markdown` — "
     "Phase 1 gets an empty brief from a finished reply",
     [("        CHATGPT_REPLY_TEXT_SEL,\n"
       "        '[data-message-author-role=\"assistant\"]:last-of-type [class*=\"prose\"]',",
       "        '[data-message-author-role=\"assistant\"]:last-of-type .markdown',\n"
       "        '[data-message-author-role=\"assistant\"]:last-of-type [class*=\"prose\"]',")]),
    ("R10", RESEARCH, "the first-message reader is back on the old marker — the pre-send "
     "identity check abstains on every new-page thread",
     [("            \"'__CG_USER__');\"",
       "            \"'[data-message-author-role=\\\"user\\\"]');\"")]),
    ("R11", RESEARCH, "⛔ the new-chat count is back on the old marker — someone else's "
     "thread reads as a fresh chat",
     [("    \" msgs: document.querySelectorAll('__CG_ANY_MSG__').length })\")",
       "    \" msgs: document.querySelectorAll('[data-message-author-role]').length })\")")]),
    ("R12", RESEARCH, "the stream observer is back on the old marker — no token-level "
     "preview on the new page",
     [("    \"chatgpt\": [\", \".join(f\"{_m.strip()}:last-of-type\"\n"
       "                          for _m in CHATGPT_ASSISTANT_MSG_SEL.split(\",\")),\n",
       "    \"chatgpt\": ['[data-message-author-role=\"assistant\"]:last-of-type',\n")]),
    ("R13", RESEARCH, "the session-expiry check is back on the old composer strings — a "
     "password box beside the new composer reads as signed out",
     [("                '__CG_SEND__, [data-testid=\"send-button\"], button[aria-label*=\"Send prompt\"], ' +\n"
       "                '__CG_COMPOSER__, ' +\n",
       "                '[data-testid=\"send-button\"], button[aria-label*=\"Send prompt\"], ' +\n"
       "                'div[contenteditable=\"true\"]#prompt-textarea, ' +\n")]),
    ("R14", RESEARCH, "the snapshot's in-turn test is back on the old turn marker",
     [("            try {\n                inTurn = !!el.closest('__CG_TURN__, '",
       "            try {\n                inTurn = !!el.closest('[data-testid^=\"conversation-turn\"], '")]),

    # ═══ S — the submit, and what counts as sent ════════════════════════════
    ("S1", RESEARCH, "the submit no longer closes the tier step's menu itself",
     [("        # A menu left open by the tier step sits over the box; close it first.\n"
       "        await _chatgpt_close_open_menus(page, tag=tag)\n", "")]),
    ("S2", RESEARCH, "the menu closer never presses Escape",
     [("        if n == 0:\n            return True\n        if i == tries:",
       "        if True:\n            return True\n        if i == tries:")]),
    ("S3", RESEARCH, "⛔⛔ the box lookup is back on `#prompt-textarea` alone",
     [("            for h in await page.query_selector_all(CHATGPT_COMPOSER_SEL):",
       "            for h in await page.query_selector_all('#prompt-textarea'):")]),
    ("S4", RESEARCH, "⛔ the box is typed into without being clicked — after the menu "
     "closes, focus is on the model button",
     [("        try:\n            await box.click()\n        except Exception:\n            pass\n"
       "        await asyncio.sleep(0.2)\n        if _norm_prompt_text(",
       "        await asyncio.sleep(0.2)\n        if _norm_prompt_text(")]),
    ("S5", RESEARCH, "⛔⛔ the read-back is skipped — whatever landed is sent (\"est\")",
     [("        if have == want:\n            if attempt > 1:",
       "        if True:\n            if attempt > 1:")]),
    ("S6", RESEARCH, "a lossy read-back is never retyped — one dropped key fails the run",
     [("    for attempt in (1, 2):\n        try:\n            await box.click()",
       "    for attempt in (1,):\n        try:\n            await box.click()")]),
    ("S7", RESEARCH, "⛔⛔ select-all is Control everywhere — on macOS that is 'line "
     "start', and the clear leaves text behind",
     [("    return \"Meta+a\" if sys.platform == \"darwin\" else \"Control+a\"",
       "    return \"Control+a\"")]),
    ("S8", RESEARCH, "⛔⛔ the submit's sent-check accepts ANY last user message",
     [("        if last is not None and _chatgpt_text_is_prompt_start(last, prompt):\n"
       "            return True",
       "        if last is not None:\n            return True")]),
    ("S9", RESEARCH, "⛔⛔ \"starts with the prompt\" accepts any text at all — \"est\" "
     "passes",
     [("    return len(have) >= n and have[:n] == want[:n]", "    return len(have) >= 1")]),
    ("S10", RESEARCH, "⛔⛔ the Phase 1 verifier ignores what the last message says — the "
     "Stop button alone verifies \"est\" again",
     [("        if last is None or not _chatgpt_text_is_prompt_start(last, prompt):\n"
       "            seen = ",
       "        if last is None:\n            seen = ")]),
    ("S11", RESEARCH, "⛔⛔ wait_until_verified never applies the prompt check",
     [("    if chatgpt_prompt:\n"
       "        verify_fn = _chatgpt_sent_prompt_verifier(chatgpt_prompt, label, inner=verify_fn)\n",
       "")]),
    ("S12", RESEARCH, "⛔ the CUA's \"still generating\" verifies a wrong send",
     [("            if (has_stop or has_loading or says_generating) and chatgpt_prompt:",
       "            if False:")]),
    ("S13", RESEARCH, "⛔⛔ the CUA fix runs whatever the box holds — it sent \"est\"",
     [("            if chatgpt_prompt and not await _chatgpt_guard_box_before_fix(\n"
       "                    page, chatgpt_prompt, label):",
       "            if False:")]),
    ("S14", RESEARCH, "⛔ the fix guard leaves wrong text in the box",
     [("    if not have or have == _norm_prompt_text(prompt):\n        return True\n"
       "    log(f\"[{label}] the message box holds",
       "    if True:\n        return True\n    log(f\"[{label}] the message box holds")]),
    ("S15", RESEARCH, "the fix guard lets the fix run on a box it cannot read",
     [("        log(f\"[{label}] skipping the CUA fix — it could click Send on text nobody checked\",\n"
       "            \"WARN\")\n        return False",
       "        log(f\"[{label}] skipping the CUA fix — it could click Send on text nobody checked\",\n"
       "            \"WARN\")\n        return True")]),
    ("S16", RESEARCH, "⛔⛔ Phase 1 verifies without its prompt",
     [("verbose=verbose,\n        chatgpt_prompt=prompt)", "verbose=verbose)")]),
    ("S17", RESEARCH, "⛔ the CUA fallback runs after Send was already pressed — the "
     "prompt goes in twice",
     [("    if not submitted and cua_client and _p1_submit.get(\"state\") == \"not_sent\":",
       "    if not submitted and cua_client:")]),
    ("S18", RESEARCH, "after the CUA places the caret, the submit ignores it",
     [("        submitted = await submit_chatgpt_direct(browser, prompt, use_focused=True,\n",
       "        submitted = await submit_chatgpt_direct(browser, prompt,\n")]),
    ("S19", RESEARCH, "⛔⛔ ctrl+a stays Control on macOS — \"test\" becomes \"est\"",
     [("    if (plat == \"darwin\" and len(keys) >= 2 and \"Control\" in keys[:-1]",
       "    if (plat == \"never\" and len(keys) >= 2 and \"Control\" in keys[:-1]")]),
    ("S20", RESEARCH, "⛔ the CUA key action bypasses the mapping",
     [("        await self.page.keyboard.press(_cua_key_combo(combo))",
       "        await self.page.keyboard.press(_cua_key_combo(combo, platform=\"linux\"))")]),
    ("S21", RESEARCH, "the focused-box path is ignored",
     [("        if box is None and use_focused:", "        if box is None and False:")]),
    ("S22", RESEARCH, "⛔ a pressed Send is reported as nothing sent — the fallback "
     "types the prompt again",
     [("        out[\"state\"] = \"sent_unconfirmed\"\n", "")]),
    ("S23", PROMPTS, "⛔⛔ the CUA fallback is told to type the prompt again",
     [("3. Do NOT type anything — not even a test word. Do NOT paste. Do NOT press\n"
       "   Enter. Do NOT click Send. Do NOT use select-all or Delete.",
       "3. Type the provided research prompt, then press Enter or click Send.")]),
    ("S24", RESEARCH, "⛔⛔ a box that never held the prompt is reported as ready — and "
     "sent",
     [("        f\"sending anything\", \"ERROR\")\n    return False",
       "        f\"sending anything\", \"ERROR\")\n    return True")]),
    ("S25", RESEARCH, "Phase 1 leaves the tier step's menu open",
     [("    try:\n        await _chatgpt_close_open_menus(browser.page, tag=\"[Phase1]\")\n"
       "    except Exception:\n        pass\n", "")]),
    ("S26", RESEARCH, "a missing box says nothing about why",
     [("            await _log_chatgpt_composer_diag(page, \"no message box found\", tag=tag)\n",
       "")]),
    ("S27", RESEARCH, "leftover text is not cleared before typing — the prompt is appended "
     "to it",
     [("        if _norm_prompt_text(await _chatgpt_box_text(box)):\n"
       "            # Something is already in the box",
       "        if False:\n            # Something is already in the box")]),
    ("S28", RESEARCH, "⛔ a bullet the box made from \"- item\" reads as a different prompt "
     "— the read-back refuses EVERY send on a box with markdown shortcuts",
     [("    return \" \".join(_PROMPT_MD_LINE_MARK.sub(\"\", t).split())",
       "    return \" \".join(t.split())")]),
    ("S29", RESEARCH, "⛔ a curled apostrophe reads as a different prompt — any topic with "
     "\"don't\" in it is never sent",
     [("    t = _PROMPT_NORM_DROP.sub(\"\", str(s or \"\")).translate(_PROMPT_TYPO_ASCII)",
       "    t = _PROMPT_NORM_DROP.sub(\"\", str(s or \"\"))")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider",
             "-k", DESELECT, "-rs"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    ok = (re.search(r"\b\d+ (failed|errors?)\b", out) is None
          and re.search(r"\b\d+ passed\b", out) is not None)
    return ok, out


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, TESTS)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — the real-Chrome tests did not run here, so "
              "no kill below would mean anything.\n" + out[-1500:])
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            ok, _out = green(ROOT, TESTS)
            if ok:
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
