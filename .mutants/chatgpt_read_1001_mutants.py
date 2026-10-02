"""Mutation harness — ChatGPT Deep research, 2026-10-01: the report read off the
app's frame, and no card for a dead browser.

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  F*  the finished report is read off the app's frame before anything else —
      nothing pressed, nothing downloaded, no computer use: where the report
      starts (past the app's header and counts, never past a heading or more
      than a line of text, never into the app's script), its citations with no
      link left out and those with one kept (without the pill's "+1"), the
      diagram, hidden text and controls' labels left out, citation token runs
      stripped.
  G*  what is not the whole report goes to computer use: no heading, too short,
      less than the done check read a moment before (handed down from the poll
      loop), a sources list.
  B*  an empty extraction on a dead browser takes the crash path with no card,
      after the page said done and after computer use said done, and sends no
      "failed" status and saves no "errored" first; a live one still does both.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline is
not a measurement, so the runner refuses to score a skipped baseline.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/chatgpt_read_1001_mutants.py
  .venv/bin/python .mutants/chatgpt_read_1001_mutants.py F1 B2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

#: The tests each group of mutants is measured by (a name, never a path: the
#: anchor sweep reads any "*.py" string in a mutant's row as its target file).
SUITES = {
    "read": ["tests/test_chatgpt_dr_read_1001.py"],
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

MUTANTS = [
    # ── F: the read ─────────────────────────────────────────────────────────
    ("F1", RESEARCH, "⛔⛔ the frame is never read — computer use downloads every report again",
     [("        md = await _chatgpt_dr_frame_report(page, label, done_text_len=done_text_len)\n",
       "        md = \"\"\n")],
     "read"),
    ("F2", RESEARCH, "⛔⛔ the app's script (13 MB on 10-01) is taken for the report",
     [("        const kids = [...root.children].filter(drawn);\n",
       "        const kids = [...root.children];\n")],
     "read"),
    ("F3", RESEARCH, "the read goes past the report's title into the element beside it",
     [("                || c.matches(HEAD) || c.querySelector(HEAD)))) break;\n",
       "                ))) break;\n")],
     "read"),
    ("F4", RESEARCH, "the read always goes down to the largest child — one paragraph",
     [("        if (!best || bestLen < total * P.share) break;\n",
       "        if (!best) break;\n")],
     "read"),
    ("F5", RESEARCH, "⛔ a citation's number stays glued to the words (\"work.1 Adult\")",
     [("        cites += 1;\n        el.remove();\n",
       "        cites += 1;\n")],
     "read"),
    ("F6", RESEARCH, "⛔ a citation that names its source loses it — no sources in the document",
     [("        if (el.querySelector('a[href^=\"http\"]')) continue;\n", "")],
     "read"),
    ("F7", RESEARCH, "a citation link keeps the pill's \"+1\"",
     [("        if (last) last.nodeValue = last.nodeValue.replace(/\\s*\\+\\d+\\s*$/, '');\n", "")],
     "read"),
    ("F8", RESEARCH, "the diagram's labels land in the report as loose words",
     [("    for (const el of [...out.querySelectorAll('svg')]) el.remove();\n", "")],
     "read"),
    ("F9", RESEARCH, "a citation token run in the frame reaches the document",
     [("        md = _strip_chatgpt_citation_tokens(html_to_markdown(best.get(\"html\") or \"\"))\n",
       "        md = html_to_markdown(best.get(\"html\") or \"\")\n")],
     "read"),
    ("F10", RESEARCH, "an opening paragraph with no heading, under a tenth of the text, is dropped",
     [("        if (kids.some((c) => c !== best && (len(c) > P.aside\n",
       "        if (kids.some((c) => c !== best && (false\n")],
     "read"),
    ("F11", RESEARCH, "the read stops at the counts line — the app's header lands in the report",
     [("_CHATGPT_DR_REPORT_ASIDE = 200\n", "_CHATGPT_DR_REPORT_ASIDE = 0\n")],
     "read"),
    ("F12", RESEARCH, "text the page does not draw (a hidden tooltip) lands in the report",
     [("        if (getComputedStyle(live[i]).display === 'none') unseen.push(copy[i]);\n", "")],
     "read"),
    ("F13", RESEARCH, "a control's label (\"Copy code\") lands in the report",
     [("        if ((el.textContent || '').trim().length > P.label) continue;\n        el.remove();\n",
       "        if ((el.textContent || '').trim().length > P.label) continue;\n")],
     "read"),
    ("F14", RESEARCH, "the controls go before the citations are counted — the log says none",
     [("    let cites = 0;\n    for (const el of [...out.querySelectorAll('[data-citation-index]')]) {\n",
       "    for (const el of [...out.querySelectorAll('button, [role=\"button\"]')]) el.remove();\n"
       "    let cites = 0;\n    for (const el of [...out.querySelectorAll('[data-citation-index]')]) {\n")],
     "read"),

    # ── G: not the whole report ─────────────────────────────────────────────
    ("G1", RESEARCH, "⛔⛔ the activity list (no heading) is taken for the report",
     [("    elif int(best.get(\"headings\") or 0) < 1:\n", "    elif False:\n")],
     "read"),
    ("G2", RESEARCH, "a card with a few lines is taken for the report",
     [("        if n <= 2000:\n            why = f\"only {n} characters of report\"\n",
       "        if False:\n            why = f\"only {n} characters of report\"\n")],
     "read"),
    ("G3", RESEARCH, "⛔ a frame that lost text after the done check is taken for the report",
     [("        elif done_text_len and text < _CHATGPT_DR_REPORT_WHOLE * done_text_len:\n",
       "        elif False:\n")],
     "read"),
    ("G4", RESEARCH, "⛔ the poll loop never hands down what the done check read",
     [("                        done_text_len=int(t1 or 0),\n",
       "                        done_text_len=0,\n")],
     "read"),
    ("G5", RESEARCH, "⛔ extract_and_record_agent drops what the done check read",
     [("                extra_kw[\"done_text_len\"] = int(done_text_len)\n",
       "                pass\n")],
     "read"),
    ("G6", RESEARCH, "a numbered list of addresses is taken for the report",
     [("        elif _is_sources_not_document(md, platform=\"chatgpt\"):\n"
       "            why = f\"what it holds",
       "        elif False:\n"
       "            why = f\"what it holds")],
     "read"),
    ("G7", RESEARCH, "a whole report is refused against the done check's own length",
     [("_CHATGPT_DR_REPORT_WHOLE = 0.9\n", "_CHATGPT_DR_REPORT_WHOLE = 1.0\n")],
     "read"),

    # ── B: a dead browser gets no card ──────────────────────────────────────
    ("B1", RESEARCH, "⛔⛔ the browser is never asked — a dead one gets the card (10-01)",
     [("    if await _browser_context_is_dead(browser):\n"
       "        log(f\"[{name}] the whole browser is gone, not just this tab — no card; \"\n",
       "    if False:\n"
       "        log(f\"[{name}] the whole browser is gone, not just this tab — no card; \"\n")],
     "read"),
    ("B2", RESEARCH, "⛔⛔ after the page said done, a dead browser gets the card again",
     [("                    await _p2_unwind_if_browser_gone(browser, name)\n"
       "                    log(f\"[{name}] Extraction attempt",
       "                    log(f\"[{name}] Extraction attempt")],
     "read"),
    ("B3", RESEARCH, "after computer use said done, a dead browser gets the card again",
     [("                await _p2_unwind_if_browser_gone(browser, name)\n"
       "                p.setdefault(\"empty_retries\", 0)\n",
       "                p.setdefault(\"empty_retries\", 0)\n")],
     "read"),
    ("B4", RESEARCH, "the unwind's message no longer says browser crash — the top level "
     "cannot tell it from an ordinary failure",
     [("        raise RuntimeError(\"research browser died during a phase 2 extraction (browser crash)\")\n",
       "        raise RuntimeError(\"research browser died during a phase 2 extraction\")\n")],
     "read"),
    ("B5", RESEARCH, "the crash kind is not recorded for the retry",
     [("        _runtime.last_failure_kind = \"browser_crash\"\n"
       "        raise RuntimeError(\"research browser died during a phase 2 extraction",
       "        raise RuntimeError(\"research browser died during a phase 2 extraction")],
     "read"),
    ("B6", RESEARCH, "⛔ a dead browser still shows ChatGPT failed and saves 'errored' (10-01)",
     [("    elif n_chars <= 0 and await _browser_context_is_dead(browser):\n",
       "    elif False:\n")],
     "read"),
    ("B7", RESEARCH, "a live browser's empty extraction no longer shows failed or saves 'errored'",
     [("    elif n_chars <= 0 and await _browser_context_is_dead(browser):\n",
       "    elif n_chars <= 0:\n")],
     "read"),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suite):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES[suite], "-q", "-x",
             "-p", "no:cacheprovider", "-rs"],
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
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    selected = [m for m in MUTANTS if not only or m[0] in only]
    print("baseline… ", end="", flush=True)
    for suite in sorted({m[4] for m in selected}):
        ok, out = green(ROOT, suite)
        if not ok:
            print(f"⛔ BASELINE RED ({suite}) — fix the suite before mutating anything.\n"
                  + out[-2000:])
            sys.exit(2)
        if re.search(r"\b\d+ skipped\b", out):
            print(f"⛔ BASELINE SKIPPED TESTS ({suite}) — the real-Chrome tests did not "
                  "run here, so no kill below would mean anything.\n" + out[-1500:])
            sys.exit(2)
    print("green\n")

    survivors = []
    for mid, fname, why, edits, suite in selected:
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
            ok, _out = green(ROOT, suite)
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
