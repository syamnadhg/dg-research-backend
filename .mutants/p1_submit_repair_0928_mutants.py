"""Mutation harness — the 2026-09-29 repair of ChatGPT's Phase 1 submit.

⛔⛔ WHAT THIS CODE DECIDES.
  F* — "sent" reads the user message's OWN text. An attached file is drawn in
       the message above the prompt; read whole, the message did not start with
       the prompt, and a real send was refused (Phase 1 with sources failed
       while ChatGPT wrote the brief). The text is the message's LAST
       whitespace-pre-wrap block; a message without one is read whole.
  A* — "the CUA never types" is MECHANICAL: CUA_CLICK_ONLY lets a CUA point,
       click once, scroll, wait and press Escape, and agent_loop refuses
       anything else before it runs, logs it and tells the model. A Vision act
       step is held to the same list (vision.act_loop's refuse hook).
  W* — the list is WIRED where the program owns the typing: both caret
       placements (brief, follow-up), the gate's diagnosis and fix while a
       ChatGPT prompt is in play — for the CUA and the Vision act step alike —
       and nowhere else.
  P* — Phase 1's own wiring, killed by run_phase1 EXECUTED against the page
       (the lane harness's S16-S18 used to die only on a source-count pin):
       verify with the prompt, the fallback only when nothing was sent, the
       second submit on the focused box — for the brief and the follow-up.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant here must die on behaviour:
real Chrome against the rebuilt pages, the real agent_loop / execute_action,
the real vision.act_loop.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline
is not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/p1_submit_repair_0928_mutants.py
  .venv/bin/python .mutants/p1_submit_repair_0928_mutants.py A1 W5
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
VISION = "vision.py"

TESTS = ["tests/test_chatgpt_p1_repair_0928.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ F — "sent" reads the message's own text ════════════════════════════
    ("F1", RESEARCH, "⛔⛔ the whole message is read — an attached file's card comes "
     "first, and a real send is refused",
     [("    const own = last.querySelectorAll('.whitespace-pre-wrap');\n"
       "    const el = own.length ? own[own.length - 1] : last;\n",
       "    const el = last;\n")]),
    ("F2", RESEARCH, "the FIRST text block is read — the file card's own name line",
     [("    const el = own.length ? own[own.length - 1] : last;",
       "    const el = own.length ? own[0] : last;")]),
    ("F3", RESEARCH, "a message with no text block reads as nothing — the prompt is "
     "never seen as sent",
     [("    const el = own.length ? own[own.length - 1] : last;",
       "    const el = own[own.length - 1];")]),

    # ═══ A — the allow-list ═════════════════════════════════════════════════
    ("A1", RESEARCH, "⛔⛔ agent_loop ignores the list — the CUA types \"test\" and sends it",
     [("            elif refused := _cua_refusal(act, tb.input, allow):",
       "            elif refused := _cua_refusal(act, tb.input, None):")]),
    ("A2", RESEARCH, "⛔⛔ any key passes — Enter sends what the box holds",
     [("        return \"\" if f\"key:{combo}\" in allow else f\"key {combo!r}\"",
       "        return \"\"")]),
    ("A3", RESEARCH, "⛔⛔ the list allows typing",
     [("CUA_CLICK_ONLY = frozenset({\"left_click\", \"mouse_move\", \"scroll\", \"wait\", "
       "\"key:Escape\"})",
       "CUA_CLICK_ONLY = frozenset({\"left_click\", \"mouse_move\", \"scroll\", \"wait\", "
       "\"key:Escape\", \"type\"})")]),
    ("A4", RESEARCH, "Escape is refused — a menu over the box stays open",
     [("CUA_CLICK_ONLY = frozenset({\"left_click\", \"mouse_move\", \"scroll\", \"wait\", "
       "\"key:Escape\"})",
       "CUA_CLICK_ONLY = frozenset({\"left_click\", \"mouse_move\", \"scroll\", \"wait\"})")]),
    ("A5", RESEARCH, "⛔ the click is refused — the fallback can no longer place the caret",
     [("CUA_CLICK_ONLY = frozenset({\"left_click\", \"mouse_move\", \"scroll\", \"wait\", "
       "\"key:Escape\"})",
       "CUA_CLICK_ONLY = frozenset({\"mouse_move\", \"scroll\", \"wait\", \"key:Escape\"})")]),
    ("A6", RESEARCH, "a key is judged by its raw name — \"esc\" is refused",
     [("        combo = _cua_key_combo(p.get(\"key\") or p.get(\"text\", \"\"))",
       "        combo = p.get(\"key\") or p.get(\"text\", \"\")")]),
    ("A7", RESEARCH, "a Vision click is not read as a click — every Vision step hands over",
     [("    if act == \"click\":\n        act = \"left_click\"\n", "")]),
    ("A8", RESEARCH, "a Vision key is judged without its key — Escape is refused",
     [("    return _cua_refusal(act, {\"key\": getattr(result, \"key\", None) or \"\"}, allow)",
       "    return _cua_refusal(act, {}, allow)")]),
    ("A9", VISION, "⛔⛔ vision.act_loop ignores the refuse hook — Vision types and sends",
     [("        refused = refuse(result) if refuse is not None else \"\"",
       "        refused = \"\"")]),
    ("A10", RESEARCH, "⛔ the Vision dispatch never passes the list",
     [("            _act_kw[\"refuse\"] = lambda r: _vision_refusal(r, act_allow)\n",
       "            pass\n")]),
    ("A11", RESEARCH, "the model is not told its action was refused",
     [("                    {\"type\": \"text\", \"text\": f\"Action '{act}' was NOT carried "
       "out: this task \"\n"
       "                     f\"may only use: {_may}. Do not type or press Enter.\"},\n", "")]),
    ("A12", RESEARCH, "a refused action leaves no line in the log",
     [("                log(f\"[cua] REFUSED {refused} — this task may only use: {_may}; \"\n"
       "                    f\"nothing was typed, pressed or sent\", \"WARN\")\n",
       "")]),

    # ═══ W — the list is wired where the program owns the typing ════════════
    ("W1", RESEARCH, "⛔⛔ the brief's caret CUA runs without the list — \"test\" is sent",
     [("max_iterations=8, verbose=verbose, allow=CUA_CLICK_ONLY,\n"
       "                never_click=CUA_NEVER_CLICK_SEND)",
       "max_iterations=8, verbose=verbose,\n"
       "                never_click=CUA_NEVER_CLICK_SEND)")]),
    ("W2", RESEARCH, "⛔ the follow-up's caret CUA runs without the list",
     [("                    model=CUA_MODEL, max_iterations=8, verbose=verbose,\n"
       "                    allow=CUA_CLICK_ONLY, never_click=CUA_NEVER_CLICK_SEND)",
       "                    model=CUA_MODEL, max_iterations=8, verbose=verbose,\n"
       "                    never_click=CUA_NEVER_CLICK_SEND)")]),
    ("W3", RESEARCH, "⛔ the gate's diagnosis CUA runs without the list",
     [("                    allow=CUA_LOOK_ONLY if _cua_allow is not None else None)",
       "                    allow=None)")]),
    ("W4", RESEARCH, "⛔⛔ the gate's fix CUA runs without the list — it types and sends",
     [("max_iterations=10, verbose=verbose, allow=_cua_allow)",
       "max_iterations=10, verbose=verbose)")]),
    ("W5", RESEARCH, "⛔ the brief's caret step lets Vision type (act mode)",
     [("            cua_coro_factory=_submit_cua,\n"
       "            mission_prompt=PROMPT_SUBMIT_FALLBACK,\n"
       "            act_allow=CUA_CLICK_ONLY)",
       "            cua_coro_factory=_submit_cua,\n"
       "            mission_prompt=PROMPT_SUBMIT_FALLBACK)")]),
    ("W6", RESEARCH, "the follow-up's caret step lets Vision type (act mode)",
     [("                cua_coro_factory=_submit_fu_cua,\n"
       "                mission_prompt=PROMPT_SUBMIT_FALLBACK,\n"
       "                act_allow=CUA_CLICK_ONLY)",
       "                cua_coro_factory=_submit_fu_cua,\n"
       "                mission_prompt=PROMPT_SUBMIT_FALLBACK)")]),
    ("W7", RESEARCH, "the gate's fix lets Vision type (act mode)",
     [("                mission_prompt=PROMPT_FIX_ISSUE,\n                act_allow=_cua_allow)",
       "                mission_prompt=PROMPT_FIX_ISSUE)")]),
    ("W8", RESEARCH, "⛔⛔ a ChatGPT prompt in play never turns the list on",
     [("        _cua_allow = CUA_CLICK_ONLY\n", "        _cua_allow = None\n")]),
    ("W9", RESEARCH, "every platform's fix is held to the list — another platform can "
     "no longer press Enter on a prompt the program typed",
     [("    _cua_allow = None\n    if chatgpt_prompt:",
       "    _cua_allow = CUA_CLICK_ONLY\n    if chatgpt_prompt:")]),

    # ═══ P — Phase 1's wiring, executed ═════════════════════════════════════
    ("P1", RESEARCH, "⛔⛔ Phase 1 verifies without its prompt — Stop beside other text "
     "reads as \"✓ Verified\"",
     [("verbose=verbose,\n        chatgpt_prompt=prompt)", "verbose=verbose)")]),
    ("P2", RESEARCH, "⛔ the fallback runs after Send was pressed — the prompt goes in twice",
     [("    if not submitted and cua_client and _p1_submit.get(\"state\") == \"not_sent\":",
       "    if not submitted and cua_client:")]),
    ("P3", RESEARCH, "after the CUA places the caret, the submit ignores it",
     [("            submitted = await submit_chatgpt_direct(browser, prompt, use_focused=True,\n",
       "            submitted = await submit_chatgpt_direct(browser, prompt,\n")]),
    ("P4", RESEARCH, "the fallback never runs — a box no marker names sends nothing",
     [("    if not submitted and cua_client and _p1_submit.get(\"state\") == \"not_sent\":",
       "    if not submitted and cua_client and _p1_submit.get(\"state\") == \"never\":")]),
    ("P5", RESEARCH, "⛔ the follow-up is verified without its text",
     [("verbose=verbose,\n            chatgpt_prompt=followup)", "verbose=verbose)")]),
    ("P6", RESEARCH, "the follow-up's fallback runs after its Send was pressed",
     [("        if not submitted_fu and cua_client and _fu_submit.get(\"state\") == \"not_sent\":",
       "        if not submitted_fu and cua_client:")]),
    ("P7", RESEARCH, "the follow-up's second submit ignores the caret",
     [("                submitted_fu = await submit_chatgpt_direct(browser, followup, "
       "use_focused=True,\n",
       "                submitted_fu = await submit_chatgpt_direct(browser, followup,\n")]),
    ("P8", RESEARCH, "the follow-up's fallback never runs",
     [("        if not submitted_fu and cua_client and _fu_submit.get(\"state\") == \"not_sent\":",
       "        if not submitted_fu and cua_client and _fu_submit.get(\"state\") == \"never\":")]),

    # ═══ N — no click sends (09-29 verify) ══════════════════════════════════
    ("N1", RESEARCH, "⛔⛔ agent_loop ignores never_click — the caret CUA clicks Send "
     "over a leftover draft",
     [("            elif (never_click and act == \"left_click\"",
       "            elif (False and never_click and act == \"left_click\"")]),
    ("N2", RESEARCH, "⛔ the Send guard never sees Send under a click",
     [("        if (n.closest(s)) return true;\n", "        if (false) return true;\n")]),
    ("N3", RESEARCH, "⛔ the brief's caret CUA may click Send",
     [("max_iterations=8, verbose=verbose, allow=CUA_CLICK_ONLY,\n"
       "                never_click=CUA_NEVER_CLICK_SEND)",
       "max_iterations=8, verbose=verbose, allow=CUA_CLICK_ONLY)")]),
    ("L1", RESEARCH, "⛔⛔ the diagnosis may click — before the box guard, a click on "
     "Send sends the leftover",
     [("                    allow=CUA_LOOK_ONLY if _cua_allow is not None else None)",
       "                    allow=_cua_allow)")]),
    ("L2", RESEARCH, "the look-only list lets a click through",
     [("CUA_LOOK_ONLY = frozenset({\"mouse_move\", \"scroll\", \"wait\"})",
       "CUA_LOOK_ONLY = frozenset({\"left_click\", \"mouse_move\", \"scroll\", \"wait\"})")]),
    ("S1", RESEARCH, "⛔⛔ text the box would not give up is handed to the caret CUA — "
     "one click on Send sends it",
     [("                out[\"state\"] = \"not_cleared\"\n", "                pass\n")]),
    ("S2", RESEARCH, "the stuck box is never reported to the submit",
     [("                if why is not None:\n                    why[\"stuck\"] = True\n", "")]),
    ("B1", RESEARCH, "⛔⛔ the belt is off on the brief — the prompt is typed after a "
     "message the program did not send",
     [("        if _chatgpt_caret_step_sent(_msgs_before, await _chatgpt_user_msg_count(browser.page),",
       "        if False and _chatgpt_caret_step_sent(_msgs_before, "
       "await _chatgpt_user_msg_count(browser.page),")]),
    ("B2", RESEARCH, "⛔ the belt never sees a new message",
     [("    if before is None or after is None or after == before:\n        return False",
       "    if True:\n        return False")]),
    ("B3", RESEARCH, "⛔ the belt is off on the follow-up",
     [("            if _chatgpt_caret_step_sent(_fu_msgs_before,",
       "            if False and _chatgpt_caret_step_sent(_fu_msgs_before,")]),
    ("B4", RESEARCH, "OVER-REACH: the belt fires on every caret step — a caret placed "
     "cleanly never gets its prompt",
     [("    if before is None or after is None or after == before:\n        return False",
       "    if before is None or after is None:\n        return False")]),

    # ═══ R — the last review's items (09-29 re-verify) ═════════════════════
    ("N4", RESEARCH, "⛔ the follow-up's caret CUA may click Send",
     [("                    allow=CUA_CLICK_ONLY, never_click=CUA_NEVER_CLICK_SEND)",
       "                    allow=CUA_CLICK_ONLY)")]),
    ("N5", RESEARCH, "the Send guard stops at a shadow root's host — the button inside "
     "is clicked",
     [("        const inner = e.shadowRoot.elementFromPoint(x, y);\n"
       "        if (!inner || inner === e) break;\n",
       "        const inner = null;\n"
       "        if (!inner || inner === e) break;\n")]),
    ("N6", RESEARCH, "a click into a frame is judged as not Send",
     [("    if (e.tagName === 'IFRAME' || e.tagName === 'FRAME') return true;\n", "")]),
    ("N7", RESEARCH, "⛔ a click the guard cannot judge is let through",
     [("        return bool(await browser.page.evaluate(_CUA_CLICK_TARGET_JS, [x, y, sel]))\n"
       "    except Exception:\n        return True",
       "        return bool(await browser.page.evaluate(_CUA_CLICK_TARGET_JS, [x, y, sel]))\n"
       "    except Exception:\n        return False")]),
    ("B5", RESEARCH, "⛔ the belt only counts upward — a caret step that opened a new "
     "chat passes, and the follow-up goes into it",
     [("    if before is None or after is None or after == before:\n        return False",
       "    if before is None or after is None or after[0] <= before[0]:\n        return False")]),
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
