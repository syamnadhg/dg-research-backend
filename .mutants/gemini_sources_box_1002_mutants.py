"""Mutation harness — the 10-02 review of Gemini's own sources list (be-0115):
the list ends where its own box ends, words in no row refuse it, the toggle
counts the rows in its own list's box, a list that opens late is closed again,
and the press step on a browser that dies right after it.

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  B*  the list is its title and the box its first row sits in: row 1 is looked
      for before the next list's title only, and the list ends where that box
      ends — never at the next title (a title worded otherwise, or no second
      list and the thinking trace's site links after it, add nothing to it).
  L*  words in the list that are in no row (a row drawn by another element,
      with no address) refuse the join; notes and spaces between rows are not
      words; a row's own words are in its row; the log names the element in the
      list's box that holds them, never the words.
  J*  the page script counts the links in the element right after the
      toggle's holder, never every link after the toggle; nothing after the
      toggle is no row.
  W*  a list pressed open that showed no row in time is watched for as long
      again after the read and pressed closed the moment it shows; a list left
      alone at the start is never watched; the watch waits between looks, stops
      at its press, and says when the list stayed closed; the press step never
      raises, so Chrome dying right after it is still a crash, never a card.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline is
not a measurement, so the runner refuses to score a skipped baseline.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/gemini_sources_box_1002_mutants.py
  .venv/bin/python .mutants/gemini_sources_box_1002_mutants.py B1 W7
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
    "gemini": ["tests/test_gemini_footnotes_1002.py"],
    "crash": ["tests/test_w15_every_agent_crash_1002.py", "-k", "sources_press"],
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

MUTANTS = [
    # ── B: the list ends where its own box ends ─────────────────────────────
    ("B1", RESEARCH, "⛔⛔ the list ends at the next list's title again — a title worded otherwise adds its rows",
     [("    end_at = next_at if row1 is None else order[id(list(row1.parent.descendants)[-1])] + 1\n",
       "    end_at = next_at\n")],
     "gemini"),
    ("B2", RESEARCH, "⛔ row 1 is looked for past the next list's title — a closed list takes the next list's rows",
     [("    row1 = next((n for n in _after_title(next_at)\n",
       "    row1 = next((n for n in _after_title(len(order))\n")],
     "gemini"),
    ("B3", RESEARCH, "⛔ the list is its first row alone",
     [("    end_at = next_at if row1 is None else order[id(list(row1.parent.descendants)[-1])] + 1\n",
       "    end_at = next_at if row1 is None else order[id(list(row1.descendants)[-1])] + 1\n")],
     "gemini"),
    ("B4", RESEARCH, "row 1 is any element after the title",
     [('                 if getattr(n, "name", None) == _GEMINI_ROW_TAG), None)\n',
       '                 if getattr(n, "name", None) is not None), None)\n')],
     "gemini"),
    ("B5", RESEARCH, "⛔ the list never ends — everything after its title is its",
     [("            if order[id(node)] >= end:\n                return\n",
       "            if False:\n                return\n")],
     "gemini"),
    # ── L: words in no row refuse the join ──────────────────────────────────
    ("L1", RESEARCH, "⛔⛔ words in no row are let through — a row of another kind shifts every number after it",
     [("    if loose:\n        held = ", "    if False:\n        held = ")],
     "gemini"),
    ("L2", RESEARCH, "a note between rows counts as words — the list is refused",
     [("            if (not isinstance(node, Comment) and node.strip()\n",
       "            if (node.strip()\n")],
     "gemini"),
    ("L3", RESEARCH, "spaces between rows count as words — the list is refused",
     [("            if (not isinstance(node, Comment) and node.strip()\n",
       "            if (not isinstance(node, Comment) and str(node)\n")],
     "gemini"),
    ("L4", RESEARCH, "⛔ a row's own words count as in no row — every list is refused",
     [("                    and not any(id(p) in row_ids for p in node.parents)):\n",
       "                    and True):\n")],
     "gemini"),
    ("L5", RESEARCH, "the log names the words' own element, not the row of another kind holding them",
     [("        held = next((p for p in loose[0].parents if p.parent is first.parent), loose[0].parent)\n",
       "        held = loose[0].parent\n")],
     "gemini"),
    # ── J: the toggle counts the rows in its own list's box ────────────────
    ("J1", RESEARCH, "⛔⛔ the toggle counts every link after it again — a closed list is never opened",
     [("  const rows = box ? box.querySelectorAll('a[href]').length : 0;\n",
       "  const rows = [...document.querySelectorAll('a[href]')].filter((a) =>"
       " !!(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING)).length;\n")],
     "gemini"),
    ("J2", RESEARCH, "the list's box is the button's own next element — no row is ever seen",
     [("  const box = b.parentElement ? b.parentElement.nextElementSibling : null;\n",
       "  const box = b.nextElementSibling;\n")],
     "gemini"),
    ("J3", RESEARCH, "every link on the page is the list's — a closed list is never opened",
     [("  const rows = box ? box.querySelectorAll('a[href]').length : 0;\n",
       "  const rows = box ? document.querySelectorAll('a[href]').length : 0;\n")],
     "gemini"),
    ("J4", RESEARCH, "a toggle with nothing after it breaks the page script — it is never pressed",
     [("  const rows = box ? box.querySelectorAll('a[href]').length : 0;\n",
       "  const rows = box.querySelectorAll('a[href]').length;\n")],
     "gemini"),
    # ── W: a list that opens late is closed again; the press never raises ──
    ("W1", RESEARCH, "⛔⛔ a list that opens after the read gave up is left open",
     [('    if want == "close" and isinstance(got, dict) and got.get("state") == "left":\n',
       "    if False:\n")],
     "gemini"),
    ("W2", RESEARCH, "⛔ a list found open is watched by the open step — and pressed closed",
     [('    if want == "close" and isinstance(got, dict) and got.get("state") == "left":\n',
       '    if isinstance(got, dict) and got.get("state") == "left":\n')],
     "gemini"),
    ("W3", RESEARCH, "the close step watches for no time",
     [("        for _tick in range(int(_GEMINI_SOURCES_WAIT_S / 0.2)):\n",
       "        for _tick in range(0):\n")],
     "gemini"),
    ("W4", RESEARCH, "the watch never waits between looks — over before the list shows",
     [('            await asyncio.sleep(0.2)\n            got = await _ask("close")\n',
       '            got = await _ask("close")\n')],
     "gemini"),
    ("W5", RESEARCH, "⛔ the watch goes on after its press — the toggle is pressed again",
     [('            if not isinstance(got, dict) or got.get("state") != "left":\n                break\n',
       '            if not isinstance(got, dict) or got.get("state") != "left":\n                continue\n')],
     "gemini"),
    ("W6", RESEARCH, "a list that stayed closed is not said to",
     [("            log(f\"[{who}] Gemini's \\\"Sources used in the report\\\" stayed closed after the \"\n"
       "                \"read — left as it was found\")\n",
       "            pass\n")],
     "gemini"),
    ("W7", RESEARCH, "⛔⛔ the press step's read error escapes — Chrome dying after the press is an error out of the reader",
     [("        except Exception as e:\n            log(f\"[{who}] Gemini's sources list could not be read",
       "        except ImportError as e:\n            log(f\"[{who}] Gemini's sources list could not be read")],
     "crash"),
    ("W8", RESEARCH, "⛔ the press step raises — the reader is cut short",
     [("    got = await _ask(want)\n",
       "    got = await _ask(want)\n    if want == \"close\":\n"
       "        raise RuntimeError(\"the press step raised\")\n")],
     "crash"),
]

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
