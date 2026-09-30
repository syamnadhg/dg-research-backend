"""Mutation harness — wave 13: Phase 1 takes the brief from ChatGPT's Copy
button when the page read comes back empty.

⛔⛔ WHAT THIS CODE DECIDES.
  P* — run_phase1's wiring: the page read first and alone when it works; the
       Copy fallback AT ONCE when it comes back empty (not after the 3-minute
       re-read), again on every re-read, with the CUA handed in, and with every
       prompt we sent (the brief's and the follow-up's) as "ours".
  C* — chatgpt_brief_via_copy: the clipboard marker is written AND read back
       before anything is pressed; the CUA is held to clicks, never Send or
       Regenerate, told the copy mission's words, given the copy mission's
       prompt; no CUA → no click; citation tokens dropped; the clipboard is
       waited for after the click; never Share, Share prompt or Edit message,
       never a table's Copy table or Expand table, never Copy message;
       the ChatGPT tab brought to the front first; a Copy button that cannot be
       clicked is left to the CUA; a copy that is not on this page is refused.
  L* — which button (aimed at the owner's capture, 2026-09-29): a Copy in a
       turn's own row (turn-action-controls), labelled exactly "Copy" — never a
       code block's or a side panel's, never the user's "Copy message"; inside
       the turn that holds the latest reply — never an earlier reply's, never a
       later turn's with no reply in it, never the latest turn when that holds
       only our follow-up; with no reply marker, the last such row on the page;
       a reply no turn marker holds gets none (the CUA presses it); never a
       hidden one.
  H* — the page read of a long brief (HTML→markdown, on the capture's shapes):
       a source chip's site icon dropped (only a chip's), inline code written
       as a marked span comes out as code, from its own unescaped letters and
       fenced as markdown fences code; every other span keeps its spacing.
  V* — what counts as the brief: not the marker, MORE than 2000 characters of
       prose (the page read's own floor; an image's address does not count),
       not our prompt (anywhere near its start), three lines of prose — a code
       comment, a markdown table's row and a line crowded with code symbols are
       not prose; a line in a script written without spaces counts by its
       letters (twenty or more).
  N* — on this page: two of the first three lines of prose open (their first
       sixty letters and digits) with words the page shows; a link shows only
       its words, a list's number is drawn by the page.
  T*, R* — the same chat (wave 13 review): the chat is marked (address and the
       number of the person's messages) before anything is pressed and the
       clipboard is not read when it changed — another address (a sidebar
       conversation) or another count (a suggested reply sent) — and a chat
       that cannot be read is not taken; run_phase1 marks the chat before the
       first read and reads nothing from another one, while a mark that cannot
       be read leaves the page read as it was.
  S* — the LATEST reply (wave 13 review): a copy must be text of the last reply
       its marker names; with no reply marker, of what follows the person's
       newest message; with no marker on that message either, of the page. With
       no reply marker, a Copy row before the person's newest message is never
       pressed; with one, the latest reply's own turn decides, as before.
  Z* — the clipboard given back (wave 13 review): what it held is read before
       the marker goes on and written back whatever happened; unreadable →
       emptied, never left holding the marker.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant here must die on behaviour:
real headless Chrome against the rebuilt pages (served at a routed local
address), the real run_phase1, agent_loop and execute_action.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline
is not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/copy_fallback_w13_mutants.py
  .venv/bin/python .mutants/copy_fallback_w13_mutants.py P1 L4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_chatgpt_copy_fallback_w13.py", "tests/test_chatgpt_long_brief_w13.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ P — run_phase1's wiring ═══════════════════════════════════════════
    ("P1", RESEARCH, "⛔ the first read skips the Copy button — the brief waits three "
     "minutes for the re-read",
     [("    brief_text = await _p1_read_brief()",
       "    brief_text = await extract_chatgpt_response(browser.page)")]),
    ("P2", RESEARCH, "the re-reads never try the Copy button again",
     [("            _retry_text = await _p1_read_brief()",
       "            _retry_text = await extract_chatgpt_response(browser.page)")]),
    ("P3", RESEARCH, "⛔⛔ the Copy button is pressed even when the page read worked — "
     "the owner's clipboard is overwritten on every run",
     [("        if len(text or \"\") >= 100:",
       "        if False:")]),
    ("P4", RESEARCH, "⛔ the brief's own prompt is not \"ours\" — a copy of it could pass "
     "as the brief",
     [("    _p1_ours = [prompt]",
       "    _p1_ours = []")]),
    ("P5", RESEARCH, "⛔ the follow-up is not \"ours\" — a copy of it could pass as the brief",
     [("        _p1_ours.append(followup)\n",
       "")]),
    ("P6", RESEARCH, "the CUA is never handed to the Copy fallback — no rename can be "
     "survived",
     [("cua_client=cua_client, ours=_p1_ours,",
       "cua_client=None, ours=_p1_ours,")]),

    # ═══ C — chatgpt_brief_via_copy ════════════════════════════════════════
    ("C1", RESEARCH, "⛔⛔ no marker on the clipboard — a click that copied nothing hands "
     "back an EARLIER brief as this run's",
     [("        armed = await page.evaluate(_CG_COPY_ARM_JS, marker)",
       "        armed = \"\"")]),
    ("C2", RESEARCH, "⛔ a clipboard that cannot be read is pressed on anyway",
     [("    if armed:\n        log(f\"Phase 1: can't use the clipboard",
       "    if False:\n        log(f\"Phase 1: can't use the clipboard")]),
    ("C3", RESEARCH, "the marker is never read back — a clipboard that does not keep it "
     "is trusted",
     [("=== s ? '' : 'the marker did not come back'",
       "=== s ? '' : ''")]),
    ("C4", RESEARCH, "⛔⛔ the copy CUA may type and press Enter — a word goes into the "
     "box and is sent",
     [("allow=CUA_CLICK_ONLY, never_click=CUA_NEVER_CLICK_COPY,",
       "never_click=CUA_NEVER_CLICK_COPY,")]),
    ("C5", RESEARCH, "⛔⛔ the copy CUA may click Send and Regenerate",
     [("allow=CUA_CLICK_ONLY, never_click=CUA_NEVER_CLICK_COPY,",
       "allow=CUA_CLICK_ONLY, never_click=None,")]),
    ("C6", RESEARCH, "⛔ Regenerate is off the never-click list — one stray click throws "
     "the finished brief away",
     [("CUA_NEVER_CLICK_SEND + ', button[aria-label=\"Regenerate response\"]'",
       "CUA_NEVER_CLICK_SEND + ''")]),
    ("C7", RESEARCH, "the copy CUA is told the caret mission's words on a refusal",
     [("never_click_say=\"copy\"), timeout=_CG_COPY_CUA_S)",
       "never_click_say=\"caret\"), timeout=_CG_COPY_CUA_S)")]),
    ("C8", RESEARCH, "agent_loop ignores the mission's refusal words",
     [("_nc_btn, _nc_task, _nc_hint = _NEVER_CLICK_SAY[never_click_say]",
       "_nc_btn, _nc_task, _nc_hint = _NEVER_CLICK_SAY[\"caret\"]")]),
    ("C9", RESEARCH, "the copy CUA gets another mission's prompt",
     [("                cua_client, browser, PROMPT_COPY_REPLY_CHATGPT,",
       "                cua_client, browser, PROMPT_SUBMIT_FALLBACK,")]),
    ("C10", RESEARCH, "no CUA is not noticed — a None client is asked to click",
     [("        if not (browser and cua_client):",
       "        if not browser:")]),
    ("C11", RESEARCH, "citation token runs reach the brief",
     [("    text = _strip_chatgpt_citation_tokens(text).strip()",
       "    text = text.strip()")]),
    ("C12", RESEARCH, "⛔ the clipboard is read once, at once — a copy that lands a "
     "moment after the click is refused",
     [("        if time.monotonic() >= deadline:\n            return marker",
       "        if True:\n            return marker")]),
    ("C13", RESEARCH, "⛔ Share is off the never-click list — a stray click next to Copy "
     "opens the dialog that makes a public link to the chat",
     [("', button[aria-label=\"Share\"], button[aria-label=\"Share prompt\"]'",
       "', button[aria-label=\"Share prompt\"]'")]),
    ("C14", RESEARCH, "Share prompt is off the never-click list",
     [("', button[aria-label=\"Share\"], button[aria-label=\"Share prompt\"]'",
       "', button[aria-label=\"Share\"]'")]),
    ("C15", RESEARCH, "⛔ Edit message is off the never-click list — its Send re-submits "
     "the prompt and throws the brief away",
     [("\n                        ', button[aria-label=\"Edit message\"]'",
       "")]),
    ("C16", RESEARCH, "the ChatGPT tab is not brought to the front — behind another tab "
     "the clipboard reads back empty and the brief is lost",
     [("        await page.bring_to_front()\n    try:\n"
       "        held = await page.evaluate(_CG_COPY_READ_JS)",
       "        pass\n    try:\n"
       "        held = await page.evaluate(_CG_COPY_READ_JS)")]),
    ("C17", RESEARCH, "a Copy button that cannot be clicked ends the fallback — the CUA "
     "never gets to press it",
     [("could not be clicked \"\n"
       "                f\"({(str(e) or type(e).__name__)[:120]})\", \"WARN\")\n",
       "could not be clicked \"\n"
       "                f\"({(str(e) or type(e).__name__)[:120]})\", \"WARN\")\n"
       "            return \"\"\n")]),
    ("C18", RESEARCH, "⛔⛔ a copy that is not on this page is kept — another worker's "
     "brief on the shared clipboard becomes this run's",
     [("    if not await _chatgpt_copy_on_page(page, text):",
       "    if False:")]),
    ("C19", RESEARCH, "⛔⛔ Copy table is off the never-click list — the CUA copies one table "
     "and it becomes Phase 1's whole brief",
     [("\n                        ', button[aria-label=\"Copy table\"]'",
       "")]),
    ("C20", RESEARCH, "Expand table is off the never-click list",
     [("\n                        ', button[aria-label=\"Expand table\"]'",
       "")]),
    ("C21", RESEARCH, "Copy message is off the never-click list — the CUA copies our own "
     "prompt",
     [("\n                        ', button[aria-label=\"Copy message\"]')",
       ")")]),

    # ═══ L — which button ══════════════════════════════════════════════════
    ("L1", RESEARCH, "⛔⛔ the marker drops the turn's row — a code block's own Copy, or a "
     "side panel's, is pressed",
     [("'.turn-action-controls button[aria-label=\"Copy\"]')",
       "'button[aria-label=\"Copy\"]')")]),
    ("L2", RESEARCH, "⛔⛔ the whole page, not the latest reply's turn — an earlier reply's "
     "Copy, or a later turn's, is pressed",
     [("const scope = replies.length ? replies[replies.length - 1].closest('__CG_TURN__') : document;",
       "const scope = document;")]),
    ("L3", RESEARCH, "⛔ the latest TURN, not the latest reply's — after a follow-up with "
     "no reply yet, no Copy is found and the brief is lost",
     [("const scope = replies.length ? replies[replies.length - 1].closest('__CG_TURN__') : document;",
       "const scope = replies.length ? [...document.querySelectorAll('__CG_TURN__')].pop() : document;")]),
    ("L4", RESEARCH, "⛔ the FIRST Copy row on the page is pressed — after a follow-up, the "
     "first draft",
     [("    return ok.length ? ok[ok.length - 1] : null;",
       "    return ok.length ? ok[0] : null;")]),
    ("L5", RESEARCH, "a hidden Copy is pressed — the click times out and the brief is lost",
     [("[...scope.querySelectorAll('__CG_COPY__')].filter(shown)",
       "[...scope.querySelectorAll('__CG_COPY__')].filter(() => true)")]),
    ("L6", RESEARCH, "⛔ the marker matches \"Copy message\" — the user's own message is "
     "copied",
     [("'.turn-action-controls button[aria-label=\"Copy\"]')",
       "'.turn-action-controls button[aria-label^=\"Copy\"]')")]),
    ("L7", RESEARCH, "⛔⛔ with no reply marker (the owner's run) no Copy is looked for at "
     "all — the fallback's own case finds nothing",
     [("const scope = replies.length ? replies[replies.length - 1].closest('__CG_TURN__') : document;",
       "const scope = replies.length ? replies[replies.length - 1].closest('__CG_TURN__') : null;")]),
    ("L8", RESEARCH, "⛔ a reply no turn marker holds is searched for across the whole page — "
     "where the Copy found could be an earlier reply's",
     [("const scope = replies.length ? replies[replies.length - 1].closest('__CG_TURN__') : document;",
       "const scope = replies.length ? (replies[replies.length - 1].closest('__CG_TURN__') "
       "|| document) : document;")]),

    # ═══ V — what counts as the brief ══════════════════════════════════════
    ("V1", RESEARCH, "the marker coming back is not recognised as \"nothing was copied\"",
     [("    if not t or t == marker:",
       "    if not t:")]),
    ("V2", RESEARCH, "no length floor",
     [("    if (n := _doc_img_prose_len(t)) <= _CG_COPY_MIN_CHARS:",
       "    if False:")]),
    ("V9", RESEARCH, "⛔ the floor is 500 again — a clarifying question from ChatGPT "
     "becomes the brief",
     [("_CG_COPY_MIN_CHARS = _MIN_SALVAGEABLE_BRIEF_LEN",
       "_CG_COPY_MIN_CHARS = 500")]),
    ("V10", RESEARCH, "exactly 2000 characters passes — the page read keeps only MORE",
     [("    if (n := _doc_img_prose_len(t)) <= _CG_COPY_MIN_CHARS:",
       "    if (n := _doc_img_prose_len(t)) < _CG_COPY_MIN_CHARS:")]),
    ("V11", RESEARCH, "an image's address counts toward the floor",
     [("    if (n := _doc_img_prose_len(t)) <= _CG_COPY_MIN_CHARS:",
       "    if (n := len(t)) <= _CG_COPY_MIN_CHARS:")]),
    ("V12", RESEARCH, "a script written without spaces never reads like prose — a "
     "Japanese brief is refused",
     [("            and len(_CG_UNSPACED_RE.findall(line)) < 20):",
       "            and True):")]),
    ("V13", RESEARCH, "one letter of such a script makes a line prose — a list of short "
     "labels passes as a brief",
     [("            and len(_CG_UNSPACED_RE.findall(line)) < 20):",
       "            and len(_CG_UNSPACED_RE.findall(line)) < 1):")]),
    ("V3", RESEARCH, "⛔⛔ our own prompt passes as the brief",
     [("        if want and want in head:",
       "        if False:")]),
    ("V4", RESEARCH, "our prompt is looked for only at the very start — a file card in "
     "front of it hides it",
     [("    head = _norm_prompt_text(t)[:400]",
       "    head = _norm_prompt_text(t)[:60]")]),
    ("V5", RESEARCH, "two lines of prose pass as a brief",
     [("    if sum(1 for ln in t.splitlines() if _brief_prose_line(ln)) < 3:",
       "    if sum(1 for ln in t.splitlines() if _brief_prose_line(ln)) < 2:")]),
    ("V6", RESEARCH, "code comments count as prose — a commented code block passes",
     [("    if line.lstrip().startswith((\"#\", \"//\")):\n        return False\n",
       "")]),
    ("V7", RESEARCH, "lines crowded with code symbols count as prose",
     [("    return sum(ch in _CG_CODE_CHARS for ch in line) < 0.05 * len(line)",
       "    return True")]),
    ("V8", RESEARCH, "a single word is a line of prose",
     [("    if (len(re.findall(r\"[^\\W\\d_]{2,}\", line)) < 8\n",
       "    if (len(re.findall(r\"[^\\W\\d_]{2,}\", line)) < 1\n")]),
    ("V14", RESEARCH, "⛔ a markdown table's rows count as prose — one table, copied under "
     "some other label, passes as the brief",
     [("    if line.lstrip().startswith(\"|\"):\n        return False\n",
       "")]),
]

MUTANTS += [
    # ═══ H — the page read of a long brief ═══════════════════════════════════
    ("H1", RESEARCH, "⛔ a source chip's site icon stays — every chip is a link around an "
     "image the document funnel fetches",
     [("                if el.find_parent(\"a\", attrs={\"data-testid\": \"chatgpt-citation\"}) is not None:\n"
       "                    _doc_img_note_decorative()\n"
       "                    return \"\"\n"
       "                out = _doc_img_markdown_for_tag(dict(el.attrs))",
       "                out = _doc_img_markdown_for_tag(dict(el.attrs))")]),
    ("H2", RESEARCH, "inline code written as a span comes out as prose",
     [("                if el.get(\"data-markdown-copy\") == \"inline-code\":",
       "                if False:")]),
    ("H3", RESEARCH, "inline code is written from the prose-escaped text — its underscores "
     "come out as \\_",
     [("self.convert_code(el, el.get_text(), parent_tags)",
       "self.convert_code(el, text, parent_tags)")]),
    ("H4", RESEARCH, "⛔ every image inside any link is dropped, not only a chip's icon — a "
     "chart behind a link is lost",
     [("el.find_parent(\"a\", attrs={\"data-testid\": \"chatgpt-citation\"})",
       "el.find_parent(\"a\", attrs={})")]),
    ("H5", RESEARCH, "a plain span's edge spaces are dropped — words run together at a bold "
     "run or a chip (`pass.**Paintings`)",
     [("                return text\n        cls = _doc_img_converter_classes[base]",
       "                return text.strip()\n        cls = _doc_img_converter_classes[base]")]),
    ("H6", RESEARCH, "inline code is fenced by hand — a backtick inside it breaks the fence, "
     "and its edge spaces go inside it",
     [("                    return self.convert_code(el, el.get_text(), parent_tags)",
       "                    return \"`\" + el.get_text() + \"`\"")]),
]

MUTANTS += [
    # ═══ N — is it on this page ═══════════════════════════════════════════
    ("N1", RESEARCH, "⛔⛔ one shared line is enough — another worker's brief that ends "
     "the way every brief ends passes",
     [("sum(p in shown for p in probes) >= min(2, len(probes))",
       "sum(p in shown for p in probes) >= 1")]),
    ("N2", RESEARCH, "every one of the first three lines must be on the page — a source "
     "chip inside a sentence costs the brief",
     [("sum(p in shown for p in probes) >= min(2, len(probes))",
       "sum(p in shown for p in probes) >= len(probes)")]),
    ("N3", RESEARCH, "a link's address is looked for on the page, where only its words "
     "show",
     [(r'''    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)''' + "\n",
       "")]),
    ("N4", RESEARCH, "a list's numbers are looked for on the page, which draws them — a "
     "brief written as a numbered list is refused",
     [(r'''    line = re.sub(r"^\s*(?:(?:[-*+>]|\d+[.)])\s+)+", "", line)''' + "\n",
       "")]),
    ("N5", RESEARCH, "the whole line is looked for — a source chip late in a line costs "
     "that line",
     [("    return _cg_letters(line)[:_CG_ON_PAGE_PROBE]",
       "    return _cg_letters(line)")]),
]

MUTANTS += [
    # ═══ T — the same chat, in the Copy fallback ═══════════════════════════
    ("T1", RESEARCH, "⛔⛔ the chat is not checked before the clipboard is read — one CUA "
     "click on a sidebar conversation and another run's brief is this run's",
     [("    if moved := _chatgpt_chat_moved(chat, await _chatgpt_user_msg_count(page)):",
       "    if False and (moved := _chatgpt_chat_moved(chat, "
       "await _chatgpt_user_msg_count(page))):")]),
    ("T2", RESEARCH, "⛔ only the number of messages is compared — another address with "
     "as many messages (a sidebar conversation) passes",
     [("    if before is not None and after == before:\n        return \"\"",
       "    if before is not None and after is not None and after[0] == before[0]:\n"
       "        return \"\"")]),
    ("T3", RESEARCH, "⛔ only the address is compared — a suggested reply sent and answered "
     "at the same address passes",
     [("    if before is not None and after == before:\n        return \"\"",
       "    if before is not None and after is not None and after[1] == before[1]:\n"
       "        return \"\"")]),
    ("T4", RESEARCH, "a chat that cannot be read counts as the same chat — the Copy "
     "fallback takes a brief it cannot place",
     [("    if before is not None and after == before:\n        return \"\"",
       "    if after == before:\n        return \"\"")]),

    # ═══ R — the same chat, in run_phase1's reads ═══════════════════════════
    ("R1", RESEARCH, "⛔⛔ the re-reads read whatever chat the tab shows — three minutes "
     "after a CUA misclick, another run's brief is read from the page",
     [("        if _p1_chat is not None and (moved := _chatgpt_chat_moved(",
       "        if False and _p1_chat is not None and (moved := _chatgpt_chat_moved(")]),
    ("R2", RESEARCH, "OVER-REACH: a mark that could not be taken refuses every read — "
     "the page read, which clicks nothing, loses the brief",
     [("        if _p1_chat is not None and (moved := _chatgpt_chat_moved(",
       "        if (moved := _chatgpt_chat_moved(")]),

    # ═══ S — the latest reply ═══════════════════════════════════════════════
    ("S1", RESEARCH, "OVER-REACH: the latest reply its marker names is not used — after a "
     "follow-up with no reply yet, the latest reply's own copy is refused",
     [("    if (replies.length) return [replies[replies.length - 1].innerText || '', null];\n",
       "")]),
    ("S2", RESEARCH, "⛔⛔ with no reply marker the whole page counts — after a follow-up, "
     "the CUA's press on the first draft's Copy passes and the user's added context "
     "is dropped",
     [("            users.length ? (users[users.length - 1].innerText || '') : null];",
       "            null];")]),
    ("S3", RESEARCH, "OVER-REACH: a person's message with no marker makes every copy "
     "fail — a second rename costs the brief",
     [("    return page_letters[at + len(own):] if at >= 0 else page_letters",
       "    return page_letters[at + len(own):] if at >= 0 else \"\"")]),
    ("S4", RESEARCH, "⛔ with no reply marker the last Copy row on the page is pressed "
     "even before the person's newest message — an earlier reply's",
     [(".filter(shown).filter(latest)", ".filter(shown)")]),
    ("S5", RESEARCH, "OVER-REACH: with a reply marker too, rows before the newest message "
     "are passed over — after a follow-up with no reply yet, no Copy is found",
     [("    const latest = (b) => replies.length > 0 || !mine",
       "    const latest = (b) => !mine")]),
    ("S6", RESEARCH, "the rows BEFORE the person's newest message are the ones kept",
     [("& Node.DOCUMENT_POSITION_FOLLOWING) !== 0;",
       "& Node.DOCUMENT_POSITION_FOLLOWING) === 0;")]),

    # ═══ Z — the clipboard given back ═══════════════════════════════════════
    ("Z1", RESEARCH, "⛔ the clipboard is never given back — the marker, or the whole "
     "brief, stays on the clipboard every worker and the owner share",
     [("        await _cg_put_back_clipboard(page, held)", "        pass")]),
    ("Z2", RESEARCH, "a clipboard that could not be read is \"given back\" as the word "
     "null",
     [("_CG_COPY_WRITE_JS, \"\" if held is None else held)",
       "_CG_COPY_WRITE_JS, held)")]),
    ("Z3", RESEARCH, "what the clipboard held is never read — it is emptied, and the "
     "owner's own clipboard is lost",
     [("        held = await page.evaluate(_CG_COPY_READ_JS)\n    except Exception:\n"
       "        held = None",
       "        held = None\n    except Exception:\n        held = None")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider", "-rs"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S, stdin=subprocess.DEVNULL)
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
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # ⛔⛔ AN IN-FLIGHT MARKER: a killed run leaves this file naming the file that
    # holds a mutant, and the next run refuses to start until it is restored.
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
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
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
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
            if _digest(path.read_bytes()) == DIGESTS[fname]:
                try:
                    _INFLIGHT.unlink()
                except FileNotFoundError:
                    pass

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
