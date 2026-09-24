"""Wave 10.10 — does the line-pointer guard see a pointer, and only a pointer?

⛔⛔ WHAT THE WAVE CLOSED (2026-09-23). About 215 notes in this repository
pointed at a line NUMBER; every one sampled that pointed into research.py
landed on unrelated code. Each became the name it meant, and
`tests/test_no_line_pointers.py` (with `tests/_line_pointers.py`) now holds the
count at zero. This harness asks the two questions a guard has to answer:

  F* — the FINDER. Each form is switched off in turn (every form has an example
      only it catches); each look-alike exclusion is removed in turn (ports,
      log-file lines, tracebacks, JSON messages, units, slices); and each place
      a note lives is dropped in turn (joined comment runs, docstrings, page-JS
      comments, prose). An "under" survivor is a pointer that gets through; an
      "over" survivor is a look-alike the guard would make someone rewrite.
  T* — the GUARD's own bookkeeping: an exemption must be for one file and one
      text, a stale one must be reported, and the exempt areas must be the
      closed three.
  S* — REAL POINTERS, inserted where notes live: a research.py comment, one
      split over a line break, a page-JS comment inside a research.py string,
      a docstring bare colon-number, the README, a test docstring, vision.py,
      and the present-tense "binds every interface" claim. These are what
      prove the tree scan is not passing by looking at nothing.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated Python file must still COMPILE. Both are harness faults, counted OUT.

  .venv/bin/python .mutants/wave1010_pointers_mutants.py
  .venv/bin/python .mutants/wave1010_pointers_mutants.py F3 S2
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FINDER = "tests/_line_pointers.py"
GUARD = "tests/test_no_line_pointers.py"
RESEARCH = "research.py"
README = "README.md"
CLI_TEST = "tests/test_cli_dispatcher.py"
VISION = "vision.py"
FILES = (FINDER, GUARD, RESEARCH, README, CLI_TEST, VISION)

GUARD_SUITE = "tests/test_no_line_pointers.py tests/test_doc_matches_code_0903.py"
SUITES = {FINDER: GUARD_SUITE, GUARD: GUARD_SUITE}
DEFAULT_SUITE = "tests/test_no_line_pointers.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

NEVER = "(?!x)x"  # a pattern prefix that makes a form match nothing


def _off(form):
    """Switch one form off: its pattern can no longer match anything."""
    return [(f'    "{form}": re.compile(r"', f'    "{form}": re.compile(r"{NEVER}')]


# ── anchors: the finder's exclusions and note-finding ──────────────────────
F_PORTS_USE = '            if form == ":N" and m.group(1) in PORTS:\n'
F_PORTS_SET = 'PORTS = frozenset({"80", "443",'
F_LOG = "(?<!log )"
F_TRACEBACK = '(?<!\\", )'
F_COLUMN = 'r"(?!\\s*column)", re.I),'
F_UNITS = 'r"(?<![\\w.~])~\\d{4,}(?![\\d.,]?\\d)(?!\\s*(?:-\\s*)?" + UNITS + r"\\b)"'
F_SLICE = "(?:^|(?<=[\\s(,;"
F_RUN = "            if run and line == run_last + 1:\n"
F_DOCS = "            if tok.start[0] in docs:\n"
F_JS = "                m = _JS_COMMENT.search(seg)\n"
F_PROSE = "    elif rel.endswith(PROSE_SUFFIXES):\n"
F_PARA = ('            notes.append((start, " ".join(para)))\n'
          "            para = []\n")
# ── anchors: the guard's bookkeeping ───────────────────────────────────────
T_PATH = "        if hit.path == path and hit.match in text and text in hit.block:\n"
T_STALE = "    return [e[:2] for e in EXEMPTIONS if e not in used]\n"
T_AREAS = "            if f and not any(f.startswith(area) for area, _ in EXEMPT_AREAS)]\n"
# ── anchors: places a real pointer is inserted ─────────────────────────────
S_COMMENT = "# Stamped by the argparse dispatch in `main()`. Worker 1 is"
S_SPLIT = "# Firestore start listener (module-level function) so queued research docs"
S_JS = "        // walker in `scrape_progress_claude` — without it the walker grabs any"
S_DOC = "    initialises it during startup). The pre-init"
S_BIND = "            # verbatim, and when this was written that server listened on every"
S_README = "Alerts are authored through one seam — `emit_decision` in research.py, over an"
S_TESTDOC = "`PipelineControls.await_agent_decision` polls for `consume_continue_anyway`"
S_VISION = "(`_continue_pair_stages_2_to_6`, which now also uses resolve_api_key)."

MUTANTS = [
    # ══ the finder: every form, switched off ══════════════════════════════
    ("F1", "under", FINDER, "a file name and a colon-number gets through", _off("file:N")),
    ("F2", "under", FINDER, "'setup.py line 9' gets through", _off("file line N")),
    ("F3", "under", FINDER, "a file name and a tilde-number gets through", _off("file ~N")),
    ("F4", "under", FINDER, "a bare GitHub line anchor gets through", _off("#LN")),
    ("F5", "under", FINDER, "'rules' or 'usePipeline' with a colon-number gets through",
     _off("module:N")),
    ("F6", "under", FINDER, "'~line N' gets through — the commonest research.py form",
     _off("line N")),
    ("F7", "under", FINDER, "a bare colon-number in prose gets through", _off(":N")),
    ("F8", "under", FINDER, "a parenthesised tilde-number gets through", _off("(~N)")),
    ("F9", "under", FINDER, "'@ N' and 'see ~N' get through", _off("at ~N")),
    ("F10", "under", FINDER, "a bare four-digit tilde-number gets through", _off("~N")),
    # ══ the finder: every look-alike exclusion, removed ═══════════════════
    ("F11", "under", FINDER,
     "⛔ every bare colon-number is excused as a port — the port list stops "
     "being a list",
     [(F_PORTS_USE, '            if form == ":N":\n')]),
    ("F12", "over", FINDER, "the port list is empty: ':8000' in a note is flagged",
     [(F_PORTS_SET, 'PORTS = frozenset() and frozenset({"80", "443",')]),
    ("F13", "over", FINDER, "a quoted log-file line ('log line N') is flagged",
     [(F_LOG, "")]),
    ("F14", "over", FINDER, "a Python traceback frame is flagged", [(F_TRACEBACK, "")]),
    ("F15", "over", FINDER, "a JSON parser message ('line N column M') is flagged",
     [(F_COLUMN, 'r"", re.I),')]),
    ("F16", "over", FINDER, "a count with a unit ('~1160 lines') is flagged",
     [(F_UNITS, 'r"(?<![\\w.~])~\\d{4,}(?![\\d.,]?\\d)"')]),
    ("F17", "over", FINDER, "a slice written in prose ('text[:200]') is flagged",
     [(F_SLICE, "(?:^|(?<=[\\s(\\[,;")]),
    # ══ the finder: every place a note lives, dropped ══════════════════════
    ("F18", "under", FINDER,
     "⛔ comment lines are read one at a time, so a pointer split over a line "
     "break — the shape the first scan could not see — gets through",
     [(F_RUN, "            if False:\n")]),
    ("F19", "under", FINDER, "docstrings are not read", [(F_DOCS, "            if False:\n")]),
    ("F20", "over", FINDER,
     "⛔ every string is read as a note — prompts and log lines would have to be "
     "rewritten, which is a behaviour change",
     [(F_DOCS, "            if True:\n")]),
    ("F21", "under", FINDER, "the page JavaScript's comments are not read",
     [(F_JS, "                m = None\n")]),
    ("F22", "under", FINDER, "prose files are not read", [(F_PROSE, "    elif False:\n")]),
    ("F23", "under", FINDER, "a prose paragraph is read line by line, so a split pointer gets through",
     [(F_PARA, "            notes.extend((start, p) for p in para)\n"
               "            para = []\n")]),
    # ══ the guard's bookkeeping ════════════════════════════════════════════
    ("T1", "under", GUARD, "an exemption's text licenses the same pointer in ANY file",
     [(T_PATH, "        if hit.match in text and text in hit.block:\n")]),
    ("T2", "under", GUARD,
     "an exemption licenses EVERY pointer in the note it covers, not just its own",
     [(T_PATH, "        if hit.path == path and text in hit.block:\n")]),
    ("T3", "under", GUARD, "a stale exemption is never reported",
     [(T_STALE, "    return []\n")]),
    ("T4", "over", GUARD,
     "the exempt areas are ignored — the owner's agent/ tree and the harness "
     "anchors are demanded to change",
     [(T_AREAS, "            if f]\n")]),
    # ══ real pointers, where notes live ═══════════════════════════════════
    ("S1", "under", RESEARCH, "a colon-number pointer in a research.py comment",
     [(S_COMMENT, "# Stamped by the argparse dispatch in `main()` (research.py:90251). Worker 1 is")]),
    ("S2", "under", RESEARCH, "a pointer split over a comment line break",
     [(S_SPLIT, "# Firestore start listener (module-level function, ~line\n"
                "# 15236) so queued research docs")]),
    ("S3", "under", RESEARCH, "a pointer in the page JavaScript's own comment",
     [(S_JS, "        // walker at research.py:34930 — without it the walker grabs any")]),
    ("S4", "under", RESEARCH, "a bare colon-number in a docstring",
     [(S_DOC, "    initialises it during startup at :77344). The pre-init")]),
    ("S5", "under", RESEARCH,
     "⛔ a note says the local server binds every interface again, split over a "
     "line break",
     [(S_BIND, "            # verbatim, and that server binds every")]),
    ("S6", "under", README, "a tilde pointer in the README",
     [(S_README, "Alerts are authored through one seam — `emit_decision` (research.py "
                 "~28089), over an")]),
    ("S7", "under", CLI_TEST, "a pointer in a test's docstring",
     [(S_TESTDOC, "`PipelineControls.await_agent_decision` (research.py:21025) polls for "
                  "`consume_continue_anyway`")]),
    ("S8", "under", VISION, "a pointer in vision.py",
     [(S_VISION, "(`_continue_pair_stages_2_to_6` at research.py:81319, which now also uses "
                 "resolve_api_key).")]),
]


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}

    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for suite in sorted({*SUITES.values(), DEFAULT_SUITE}):
        if not green(suite):
            print(f"⛔ BASELINE RED ({suite}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, fname, why, edits in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
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
            path.write_text(mutated, encoding="utf-8")
            if green(SUITES.get(fname, DEFAULT_SUITE)):
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
