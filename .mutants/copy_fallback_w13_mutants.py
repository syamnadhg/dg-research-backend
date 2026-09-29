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
       waited for after the click.
  L* — which button: the last Copy on the page, never a code block's, never one
       inside a reply's text, never one before the latest reply, never a hidden
       one, never the user's "Copy message".
  V* — what counts as the brief: not the marker, long enough, not our prompt
       (anywhere near its start), three lines of prose — a code comment and a
       line crowded with code symbols are not prose.

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

TESTS = ["tests/test_chatgpt_copy_fallback_w13.py"]
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
     [("CUA_NEVER_CLICK_COPY = CUA_NEVER_CLICK_SEND + ', button[aria-label=\"Regenerate "
       "response\"]'",
       "CUA_NEVER_CLICK_COPY = CUA_NEVER_CLICK_SEND")]),
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

    # ═══ L — which button ══════════════════════════════════════════════════
    ("L1", RESEARCH, "⛔⛔ a code block's Copy is pressed",
     [("        && !b.closest('pre, code')\n",
       "")]),
    ("L2", RESEARCH, "⛔ a Copy inside the reply's own text is pressed",
     [("        && !texts.some((t) => t.contains(b))\n",
       "")]),
    ("L3", RESEARCH, "⛔⛔ an earlier reply's Copy is pressed — an older brief comes back "
     "as the latest",
     [("(!latest || !!(latest.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING))",
       "true")]),
    ("L4", RESEARCH, "⛔ the FIRST Copy on the page is pressed — after a follow-up, the "
     "first draft",
     [("    return ok.length ? ok[ok.length - 1] : null;",
       "    return ok.length ? ok[0] : null;")]),
    ("L5", RESEARCH, "a hidden Copy is pressed — the click times out and the brief is lost",
     [(".filter((b) => shown(b)",
       ".filter((b) => true")]),
    ("L6", RESEARCH, "⛔ the marker matches \"Copy message\" — the user's own message is "
     "copied",
     [("                          'button[aria-label=\"Copy\"]')",
       "                          'button[aria-label^=\"Copy\"]')")]),

    # ═══ V — what counts as the brief ══════════════════════════════════════
    ("V1", RESEARCH, "the marker coming back is not recognised as \"nothing was copied\"",
     [("    if not t or t == marker:",
       "    if not t:")]),
    ("V2", RESEARCH, "no length floor",
     [("    if len(t) < _CG_COPY_MIN_CHARS:",
       "    if False:")]),
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
     [("    if len(re.findall(r\"[^\\W\\d_]{2,}\", line)) < 8:",
       "    if len(re.findall(r\"[^\\W\\d_]{2,}\", line)) < 1:")]),
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
