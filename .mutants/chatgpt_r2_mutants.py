"""Mutation harness — ChatGPT, round 2 of the 09-30 run's fixes (from the captures).

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  S*  Phase 1's step list, read on the owner's recording: the line is the element
      holding a button[aria-expanded][aria-labelledby]; the list is what follows
      it; thoughts are not steps; the rows sit in one wrapper; the line is known
      whatever its label (long, drawn once; "Worked for …"); a label drawn twice
      is read once; the reply and the message are never the line; the rows reach
      the live activity feed.
  M*  Phase 2 picks "Deep research" inside the overlay the "+" opened — never the
      suggestion strip or the sidebar — and the Pro check runs after it.
  D*  Deep research as an app: done is the Stop button gone; "Worked for …" never
      decides it; the rule is the app's only.
  C*  a census of the app's frames: at launch and five minutes in, once each, no
      long text, from the Phase 2 poll for ChatGPT.
  L*  the report downloaded inside the app's frame: its download control, then
      the Markdown row; never a link in the report.
  R*  the export's citation runs become the links the report shows: before the
      cited sentence's full stop, runs side by side together, never a link's own
      words taken for the report's.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline is
not a measurement, so the runner refuses to score a skipped baseline.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/chatgpt_r2_mutants.py
  .venv/bin/python .mutants/chatgpt_r2_mutants.py S1 R2
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
    "steps": ["tests/test_chatgpt_r2_0930.py", "-k",
              "recorded or long_label or line or status_line or control"],
    "feed": ["tests/test_chatgpt_thinking_list_0929.py", "-k",
             "never_presses_the_line_while or listed_steps"],
    "menu": ["tests/test_chatgpt_r2_0930.py", "-k", "menu or deep_research_row"],
    "done": ["tests/test_chatgpt_dr_app_0930.py", "-k",
             "done or worked_for or without_the_app"],
    "census": ["tests/test_chatgpt_dr_app_0930.py", "-k", "census"],
    "download": ["tests/test_chatgpt_dr_app_0930.py", "-k", "download"],
    "sources": ["tests/test_chatgpt_dr_app_0930.py", "-k",
                "document or citation or link_goes"],
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

MUTANTS = [
    # ── S: the step list ────────────────────────────────────────────────────
    ("S1", RESEARCH, "⛔⛔ the list is never read as open — the 09-30 presses",
     [("    if (!steps.length && !out.thoughts) return out;\n    out.open = true;\n",
       "    if (!steps.length && !out.thoughts) return out;\n    out.open = false;\n")],
     "steps"),
    ("S2", RESEARCH, "⛔⛔ the line is looked for by another control — the reader is blind again",
     [("    for (const b of last.querySelectorAll('button[aria-expanded][aria-labelledby]')) {\n"
       "        // Never the reply's text, the person's message or the message box.\n",
       "    for (const b of last.querySelectorAll('button[aria-expanded][aria-controls]')) {\n"
       "        // Never the reply's text, the person's message or the message box.\n")],
     "steps"),
    ("S3", RESEARCH, "a thought (a paragraph) is taken for a step",
     [("        if (row.getAttribute('data-markdown-text-tone') === 'primary') "
       "{ out.thoughts += 1; continue; }\n", "")],
     "steps"),
    ("S4", RESEARCH, "the rows' one wrapper is taken for one row — the steps run together",
     [("            && !box.children[0].matches('[data-markdown-text-style]')) "
       "box = box.children[0];\n",
       "            && false) box = box.children[0];\n")],
     "steps"),
    ("S5", RESEARCH, "⛔ a folded list's absence is not checked — the line alone reads open",
     [("    if (!shown(list)) return out;\n    // The rows sit in ONE wrapper",
       "    // The rows sit in ONE wrapper")],
     "steps"),
    ("S6", RESEARCH, "⛔⛔ the line reader knows only a doubled label again — a long label "
     "or \"Worked for …\" and Phase 1 may press",
     [("        const t = undouble(head.innerText || '');\n        if (t) return t.slice(0, 80);\n",
       "        const t = '';\n        if (t) return t.slice(0, 80);\n")],
     "steps"),
    ("S7", RESEARCH, "a label drawn twice is read twice (\"Thinking\\nThinking\")",
     [("        if (parts.length === 2 && parts[0] === parts[1]) return parts[0];\n",
       "")],
     "steps"),
    ("S8", RESEARCH, "the reply's text can hold the line",
     [("        if (b.closest('__CG_REPLY_TEXT__') || b.closest('__CG_USER__')) continue;\n"
       "        if (b.closest('form, __CG_COMPOSER__')) continue;\n"
       "        if (!b.parentElement) continue;\n",
       "        if (b.closest('form, __CG_COMPOSER__')) continue;\n"
       "        if (!b.parentElement) continue;\n")],
     "steps"),
    ("S9", RESEARCH, "⛔⛔ the rows never reach the live activity feed (the consumer)",
     [("            if _sl and _sl.get(\"open\") and _rows:\n",
       "            if False:\n")],
     "feed"),

    # ── M: the Deep research row ───────────────────────────────────────────
    ("M1", RESEARCH, "⛔⛔ the overlay's rows are not read — 'no deep research row among 0 "
     "menu rows', computer use, no Pro check",
     [("    {\"name\": \"composer-overlay\",\n"
       "     \"sel\": ('[data-composer-overlay-floating-ui] button[data-list-navigation-item], '\n"
       "             '[data-composer-overlay-floating-ui] [data-mention-list-scroll-area] button')},\n",
       "")],
     "menu"),
    ("M2", RESEARCH, "⛔ any button on the page is a row — the strip's chip can be pressed",
     [("     \"sel\": ('[data-composer-overlay-floating-ui] button[data-list-navigation-item], '\n"
       "             '[data-composer-overlay-floating-ui] [data-mention-list-scroll-area] button')},\n",
       "     \"sel\": 'button'},\n")],
     "menu"),

    # ── D: done ─────────────────────────────────────────────────────────────
    ("D1", RESEARCH, "⛔⛔ Stop gone is not done on the app's page — the recorded finished "
     "page never reads done",
     [("        if not which_marker and dr_app:\n", "        if False:\n")],
     "done"),
    ("D2", RESEARCH, "⛔ \"Worked for 7s\" decides done again (it shows from launch)",
     [("            (\"thought_for\", lambda h, d: bool(d.get(\"thoughtFor\")) and not dr_app),\n",
       "            (\"thought_for\", lambda h, d: bool(d.get(\"thoughtFor\"))),\n")],
     "done"),
    ("D3", RESEARCH, "⛔⛔ the rule is not the app's: a page with no app and no Stop reads done",
     [("        dr_app = any(bool(d.get(\"drApp\")) for _c, h, d in readings if h)\n",
       "        dr_app = True\n")],
     "done"),
    ("D4", RESEARCH, "the app's frame is not recognised in the side viewer",
     [("        '[data-mcp-app-frame] iframe, [data-mcp-app-side-panel-frame-container] iframe, ' +\n"
       "        'iframe[src*=\"web-sandbox.oaiusercontent.com\"]');\n",
       "        '[data-mcp-app-frame] iframe');\n")],
     "done"),

    # ── C: the census ───────────────────────────────────────────────────────
    ("C1", RESEARCH, "the five-minute census never comes",
     [("        if time.time() - float(p.get(\"start_time\") or time.time()) >= 300:\n",
       "        if time.time() - float(p.get(\"start_time\") or time.time()) >= 3000:\n")],
     "census"),
    ("C2", RESEARCH, "⛔ a stage is written on every poll — the log fills",
     [("        if key in _CHATGPT_DR_CENSUS_SEEN:\n            return None\n", "")],
     "census"),
    ("C3", RESEARCH, "⛔ the report's words reach the census",
     [("return t.length <= 40 ? t : null; };", "return t; };")],
     "census"),
    ("C4", RESEARCH, "the Phase 2 poll writes no census (the consumer)",
     [("                if name == \"ChatGPT\":\n"
       "                    await _chatgpt_dr_census_tick(p, label=name)\n", "")],
     "census"),

    # ── L: the download in the frame ───────────────────────────────────────
    ("L1", RESEARCH, "⛔⛔ the page never downloads — computer use every time (the consumer)",
     [("    if _chatgpt_dr_app_frames(page):\n"
       "        await _chatgpt_dr_census(page, \"done\", label=label)\n",
       "    if False:\n"
       "        await _chatgpt_dr_census(page, \"done\", label=label)\n")],
     "download"),
    ("L2", RESEARCH, "⛔ a link in the report can be pressed as the download",
     [("        if (el.tagName === 'A' && /^https?:/i.test(el.getAttribute('href') || '')) continue;\n",
       "")],
     "download"),
    ("L3", RESEARCH, "the Markdown row is never pressed — no file",
     [("                    second = await _chatgpt_dr_press(g, \"dr-markdown\", "
       "_CHATGPT_DR_MARKDOWN_RE)\n",
       "                    second = None\n")],
     "download"),
    ("L4", RESEARCH, "a miss writes no census",
     [("            await _chatgpt_dr_census(page, \"miss-download\", label=label)\n", "")],
     "download"),

    # ── R: the sources ──────────────────────────────────────────────────────
    ("R1", RESEARCH, "⛔⛔ the export's citations are deleted again — no sources (09-30)",
     [("                md = await _chatgpt_link_citations(page, md, label)\n"
       "                log(f\"[{label}] Extracted via T1 CUA download",
       "                md = _strip_chatgpt_citation_tokens(md)\n"
       "                log(f\"[{label}] Extracted via T1 CUA download")],
     "sources"),
    ("R2", RESEARCH, "the link lands after the full stop — the NEXT sentence is numbered",
     [("            pm = re.search(r\"([.!?])(\\s*)$\", seg)\n            if pm:\n"
       "                out.append(seg[:pm.start()] + \" \" + links_md",
       "            pm = None\n            if pm:\n"
       "                out.append(seg[:pm.start()] + \" \" + links_md")],
     "sources"),
    ("R3", RESEARCH, "runs side by side are split — the second source leaves the sentence",
     [("        while j < len(runs) and not md[runs[j - 1].end():runs[j].start()].strip():\n",
       "        while False:\n")],
     "sources"),
    ("R4", RESEARCH, "⛔ another citation's words are taken for the report's — side-by-side "
     "citations no longer match",
     [("                if (n.parentElement && n.parentElement.closest('a[href]')) continue;\n",
       "")],
     "sources"),
    ("R5", RESEARCH, "a link near the start of its paragraph never matches",
     [("                    (e for e in pool if k.endswith(e[0]) or e[0].endswith(k)), None)\n",
       "                    (e for e in pool if False), None)\n")],
     "sources"),
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
