"""Mutation harness — Wave 13's smaller fixes from the 0.1.13 logs (2026-09-29).

⛔⛔ WHAT THIS CODE DECIDES.
  E* — the vision step never sends an empty picture. A busy page's screenshot
       timed out twice, the "" went to Anthropic as an image, the whole request
       came back 400 ("image cannot be empty") and the step ended. Every picture
       after the first now goes through one helper: an empty one is taken once
       more, then the model is told in words. Five places send a picture; each
       is driven by the real agent_loop.
  U* — Claude's usage limit is named on the card. The 2B launch reads Claude's
       page on every check while it waits (09-16: the page had gone blank by
       the time the launch gave up), again in the failure branch, and a limit
       it saw becomes "Claude's usage limit is reached — it resets <when>";
       the fresh-tab second try is not made. Driven through the real
       run_phase2 launch against a local page in headless Chrome.
  T* — ChatGPT's new page: the step list under "Thinking ▾" is open, and
       Phase 1 leaves it alone. `_CHATGPT_STEP_LIST_JS` sees a line holding its
       label twice with a shown list after it; the P1 open check accepts it;
       the vision step's mission names the list and looks for it first. Driven
       by the real state read and the real run_phase1 on the rebuilt page.
       T17+ (09-29 review): the chevron may sit between the copies and the list
       (in a row around them, or inside the inline-flex span), so the list is
       looked for outward from the line, through what holds no other words, and
       never taken from the reply's own heading.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant here must die on behaviour:
the real agent_loop, Browser.screenshot and execute_action; the real run_phase2
Claude launch in headless Chrome.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/small_w13_mutants.py
  .venv/bin/python .mutants/small_w13_mutants.py E1 E4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_cua_empty_screenshot_0929.py", "tests/test_claude_usage_limit_0916.py",
         "tests/test_chatgpt_thinking_list_0929.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_IMG_OLD = ('{"type": "image", "source": {"type": "base64", "media_type": "image/png", '
            '"data": await _anchored_screenshot()}}')

#: The P1 vision mission, as this wave writes it and as it was before.
NEW_MISSION = '                                    "Open the research activity for the latest response in "\n                                    "this ChatGPT Pro/Thinking conversation. The target is "\n                                    "the line directly below the last sent message — on "\n                                    "the newer page a line such as \'Thinking ▾\' or "\n                                    "\'Searching the web ▾\', otherwise a shimmering status "\n                                    "line; whatever its wording, that line is the target. "\n                                    "ONE click only — it is a toggle. LOOK FIRST: if a "\n                                    "list of the model\'s steps (short lines such as "\n                                    "\'Searched 48 websites\' or \'Validated financial "\n                                    "claims\') is ALREADY showing directly under that line, "\n                                    "or a row of small website chips (favicon + domain), "\n                                    "it is already open — do not click at all. Otherwise "\n                                    "click the line once; expected result: that list of "\n                                    "steps appears directly under it (on the older page, a "\n                                    "row of website chips). A right-side panel is a valid "\n                                    "outcome too but is not what this mode does any more. "\n                                    "Never click \'Answer now\', the X, a step or a chip.",'
OLD_MISSION = '                                    "Open the research activity for the latest response in "\n                                    "this ChatGPT Pro/Thinking conversation: click the "\n                                    "shimmering status line directly below the last sent "\n                                    "message — whatever its wording, the shimmer is the "\n                                    "target. ONE click only — it is a toggle. Expected "\n                                    "result: a row of small website chips (favicon + "\n                                    "domain, e.g. a few site names side by side, possibly "\n                                    "ending in an \'N more\' chip) appears INLINE directly "\n                                    "under that line. If those chips are ALREADY showing, "\n                                    "it is already open — do not click at all. A right-"\n                                    "side panel is a valid outcome too but is not what "\n                                    "this mode does any more. Never click \'Answer now\', "\n                                    "the X, or a chip.",'

MUTANTS = [
    # ═══ E — never an empty picture ═════════════════════════════════════════
    ("E1", RESEARCH, "⛔ no second try — a screenshot that would have worked the "
     "second time is replaced by words",
     [("        if not ss:\n            ss = await _anchored_screenshot()\n", "")]),
    ("E2", RESEARCH, "⛔⛔ the empty picture is sent anyway — Anthropic refuses the "
     "request and the step ends",
     [("        if ss:\n            return {\"type\": \"image\", \"source\": {\"type\": "
       "\"base64\", \"media_type\": \"image/png\",\n"
       "                                                \"data\": ss}}",
       "        if True:\n            return {\"type\": \"image\", \"source\": {\"type\": "
       "\"base64\", \"media_type\": \"image/png\",\n"
       "                                                \"data\": ss}}")]),
    ("E3", RESEARCH, "a fresh picture is never taken first — the places that need a new "
     "screenshot get only one try",
     [("        if ss is None:\n            ss = await _anchored_screenshot()\n", "")]),
    ("E4", RESEARCH, "⛔ the 'you seem stuck' hint sends the raw screenshot again",
     [("                    {\"type\": \"text\", \"text\": \"You seem stuck. Try a different "
       "approach.\"},\n                    await _screen_block(),\n",
       "                    {\"type\": \"text\", \"text\": \"You seem stuck. Try a different "
       "approach.\"},\n                    " + _IMG_OLD + ",\n")]),
    ("E5", RESEARCH, "⛔ a screenshot the model asked for is sent raw",
     [("                    \"content\": [await _screen_block()]})",
       "                    \"content\": [" + _IMG_OLD + "]})")]),
    ("E6", RESEARCH, "⛔ the picture after a refused action is sent raw",
     [("f\"may only use: {_may}. Do not type or press Enter.\"},\n"
       "                    await _screen_block(),\n",
       "f\"may only use: {_may}. Do not type or press Enter.\"},\n"
       "                    " + _IMG_OLD + ",\n")]),
    ("E7", RESEARCH, "⛔ the picture after a refused click on Send is sent raw",
     [("f\"clicked {_nc_btn}. {_nc_hint}\"},\n"
       "                    await _screen_block(),\n",
       "f\"clicked {_nc_btn}. {_nc_hint}\"},\n"
       "                    " + _IMG_OLD + ",\n")]),
    ("E8", RESEARCH, "⛔⛔ the picture after an action is sent raw — the 09-29 site",
     [("                    await _screen_block(ss),\n",
       "                    {\"type\": \"image\", \"source\": {\"type\": \"base64\", "
       "\"media_type\": \"image/png\", \"data\": ss}},\n")]),
    ("E9", RESEARCH, "OVER-REACH: every picture is taken twice — a good screenshot "
     "costs a second capture on every step",
     [("        if not ss:\n            ss = await _anchored_screenshot()\n",
       "        if True:\n            ss = await _anchored_screenshot()\n")]),
    ("E10", RESEARCH, "the missing picture leaves no line in the log",
     [("        log(\"[cua] The page did not give a screenshot twice in a row (it is busy) — \"\n"
       "            \"telling the vision model in words instead of sending an empty picture\", "
       "\"WARN\")\n", "")]),

    # ═══ U — Claude's usage limit, named ════════════════════════════════════
    ("U1", RESEARCH, "⛔⛔ the wait never reads the page — a limit seen while waiting "
     "is lost once the page goes blank (the second 09-16 run)",
     [("            await _note_claude_usage_limit(p, _cl_limit)\n            return False\n",
       "            return False\n")]),
    ("U2", RESEARCH, "⛔ the launch waits with the plain check, not the one that reads "
     "the page",
     [("verified_c = await wait_until_verified(_verify_claude_2b, claude_page, \"2B\",",
       "verified_c = await wait_until_verified(verify_claude_generating, claude_page, \"2B\",")]),
    ("U3", RESEARCH, "a fresh tab is tried after the limit was seen — minutes spent on "
     "a try that cannot work",
     [("            if verified_c or _cl_limit:\n", "            if verified_c:\n")]),
    ("U4", RESEARCH, "⛔ the failure branch does not read the page — a launch that gave "
     "up before the wait gets 'didn't start'",
     [("                    await _note_claude_usage_limit(claude_page, _cl_limit)\n", "")]),
    ("U5", RESEARCH, "⛔⛔ the limit is seen and the card still says 'Claude didn't start'",
     [("                    elif _cl_limit:\n", "                    elif False:\n")]),
    ("U6", RESEARCH, "⛔ the card drops when the limit resets",
     [("_claude_limit_card(_cl_limit.get(\"resets\", \"\"))", "_claude_limit_card(\"\")")]),
    ("U7", RESEARCH, "⛔ the message box is read — a brief ABOUT usage limits reads "
     "as Claude's limit",
     [("            'div[contenteditable=\"true\"], .ProseMirror, textarea, nav, aside')) {",
       "            'textarea, nav, aside')) {")]),
    ("U8", RESEARCH, "the sidebar is read — a chat titled with the words reads as the limit",
     [("            'div[contenteditable=\"true\"], .ProseMirror, textarea, nav, aside')) {",
       "            'div[contenteditable=\"true\"], .ProseMirror, textarea')) {")]),
    ("U9", RESEARCH, "⛔ 'approaching' reads as reached",
     [("_CLAUDE_LIMIT_RE = re.compile(r\"\\blimit reached\\b|\\bhit your limit\\b|"
       "\\bneed more usage\\?\", re.I)",
       "_CLAUDE_LIMIT_RE = re.compile(r\"\\blimit\\b|\\bhit your limit\\b|"
       "\\bneed more usage\\?\", re.I)")]),
    ("U10", RESEARCH, "the 'Need more usage?' dialog is not read",
     [("_CLAUDE_LIMIT_RE = re.compile(r\"\\blimit reached\\b|\\bhit your limit\\b|"
       "\\bneed more usage\\?\", re.I)",
       "_CLAUDE_LIMIT_RE = re.compile(r\"\\blimit reached\\b|\\bhit your limit\\b\", re.I)")]),
    ("U11", RESEARCH, "the 'You've hit your limit' note is not read",
     [("_CLAUDE_LIMIT_RE = re.compile(r\"\\blimit reached\\b|\\bhit your limit\\b|"
       "\\bneed more usage\\?\", re.I)",
       "_CLAUDE_LIMIT_RE = re.compile(r\"\\blimit reached\\b|"
       "\\bneed more usage\\?\", re.I)")]),
    ("U12", RESEARCH, "a reset time on the line after the limit is missed",
     [("        for near in lines[i:i + 3]:\n", "        for near in lines[i:i + 1]:\n")]),
    ("U13", RESEARCH, "words with no date or time are kept as the reset time "
     "('resets soon')",
     [("            if re.search(r\"\\d\", when):\n                resets = when[:40]\n",
       "            if when:\n                resets = when[:40]\n")]),
    ("U14", RESEARCH, "the sentence after the reset time is kept as part of it",
     [("            when = re.split(r\"\\.(?:\\s|$)\", m.group(1))[0].strip(\" .,;:\")\n",
       "            when = m.group(1).strip(\" .,;:\")\n")]),
    ("U15", RESEARCH, "the limit leaves no line in the log",
     [("        log(f\"[{label}] Claude's page shows its usage limit: \\\"{seen['line']}\\\" — \"\n"
       "            \"nothing can be sent to Claude until it resets\", \"WARN\")\n",
       "        pass\n")]),
    ("U16", RESEARCH, "the page is read again after the limit was noted — the same line "
     "every three seconds",
     [("    if note or page is None:\n        return\n", "    if page is None:\n        return\n")]),

    # ═══ T — the new page's step list is open ═══════════════════════════════
    ("T1", RESEARCH, "⛔⛔ Phase 1's open check ignores the list — it presses the line "
     "every 30 s (the 09-29 defect)",
     [('                or st.get("inline_chip_row") or st.get("inline_step_list"))',
       '                or st.get("inline_chip_row"))')]),
    ("T2", RESEARCH, "⛔⛔ the state read never records the list",
     [('        if isinstance(sl, dict) and sl.get("open"):\n',
       '        if False:\n')]),
    ("T3", RESEARCH, "⛔ any element with words is the line — a folded list's block, "
     "or the old page's single line, reads as open",
     [("        if (texts.length !== 2 || texts[0] !== texts[1]) continue;\n",
       "        if (!texts.length) continue;\n")]),
    ("T4", RESEARCH, "⛔ two DIFFERENT texts count as the doubled label — a folded "
     "block (line + hidden list) reads as open",
     [("        if (texts.length !== 2 || texts[0] !== texts[1]) continue;\n",
       "        if (texts.length !== 2) continue;\n")]),
    ("T5", RESEARCH, "the reply's own text can be the line",
     [("        if (h.closest('__CG_REPLY_TEXT__')) continue;\n", "")]),
    ("T6", RESEARCH, "the person's message can be the line",
     [("        if (h.closest('__CG_USER__')) continue;\n", "")]),
    ("T7", RESEARCH, "the message box can be the line",
     [("        if (h.closest('form, __CG_COMPOSER__')) continue;\n", "")]),
    ("T8", RESEARCH, "⛔ the chevron (or an icon) after the copies is taken for the "
     "list — open reads as closed in the review's layouts",
     [("            while (s && !words(s)) s = s.nextElementSibling;\n", "")]),
    ("T9", RESEARCH, "⛔⛔ a folded (hidden) list reads as open — Phase 1 never opens it",
     [("        if (!shown(list)) continue;\n", "")]),
    ("T10", RESEARCH, "a list folded by hiding its words reads as open",
     [("        if (!steps.length) continue;\n", "")]),
    ("T11", RESEARCH, "⛔ OVER-REACH: the look moves out past what holds other words — "
     "a folded line at the end of the exchange takes the message box for its list",
     [("            if (words(n) !== own) break;\n", "")]),
    ("T12", RESEARCH, "the log names no shape for the list",
     [('    if st.get("inline_step_list"):\n        return "steps"\n', "")]),
    ("T13", RESEARCH, "the log does not say how much of the list shows",
     [("""                                + (f", {_st_pre.get('inline_step_rows', 0)} step lines showing\"\n""",
       """                                + (f", step lines showing\"\n""")]),
    ("T14", RESEARCH, "the count of step lines is wrong",
     [("        out.rows = steps.length;\n", "        out.rows = 1;\n")]),
    ("T15", RESEARCH, "⛔⛔ the vision step's mission promises website chips again — "
     "it presses the open list shut (10:10:18)",
     [(NEW_MISSION, OLD_MISSION)]),
    ("T16", RESEARCH, "the mission no longer names the list of steps",
     [("\"list of the model's steps (short lines such as \"",
       "\"row of website chips (such as \"")]),

    # ═══ T17+ — the 09-29 review: the list is looked for OUTWARD from the line ═══
    ("T17", RESEARCH, "⛔⛔ the look never moves out from the element holding the copies — "
     "with the chevron after them the open list reads as closed and Phase 1 presses "
     "it (the review's two layouts)",
     [("        for (let n = h; n && n !== main; n = n.parentElement) {\n",
       "        for (let n = h; n === h; n = n.parentElement) {\n")]),
    ("T18", RESEARCH, "⛔ the look moves out only past something with a neighbour — a "
     "lone wrapper around the copies hides the list",
     [("            if (words(n) !== own) break;\n",
       "            if (words(n) !== own || (n !== h && n.children.length < 2)) break;\n")]),
    ("T19", RESEARCH, "⛔⛔ the reply's own heading is taken for the list — a folded list "
     "taken off the page reads as open and is never opened",
     [("        if (!list || list.matches('[data-conversation-role]')\n"
       "                || list.querySelector('[data-conversation-role]')) continue;\n",
       "        if (!list) continue;\n")]),
    ("T20", RESEARCH, "the reply is taken for the list when its heading is inside it",
     [("        if (!list || list.matches('[data-conversation-role]')\n"
       "                || list.querySelector('[data-conversation-role]')) continue;\n",
       "        if (!list || list.matches('[data-conversation-role]')) continue;\n")]),
    ("T21", RESEARCH, "the look leaves the conversation — the page's footer reads as "
     "a lone line's list",
     [("        for (let n = h; n && n !== main; n = n.parentElement) {\n",
       "        for (let n = h; n; n = n.parentElement) {\n")]),
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
    # ⛔ UTF-8 OUT (Windows review, 2026-09-29): a redirected run on Windows has a
    # cp1252 stdout, and the first "✓ killed" raised UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # ⛔⛔ AN IN-FLIGHT MARKER (Windows review, 2026-09-29). Windows ends a process
    # with TerminateProcess — no SIGTERM handler, no `finally:` — so a killed run
    # left a mutant in research.py silently. Now it leaves this file naming the
    # file that holds one, and the next run refuses to start until it is restored.
    # Run harnesses in a throwaway worktree, never in the live checkout.
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
