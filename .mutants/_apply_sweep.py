"""APPLY-EVERY-MUTANT sweep — the thing `_anchor_sweep.py` structurally cannot be.

⛔⛔ WHY THIS EXISTS BESIDE THE OTHER SWEEP. The resting-file sweep counts each
anchor against the file AS IT SITS. That misses the two ways a mutant measures
nothing, both of them live on 2026-09-17:

  1. THE MUTANT DOES NOT PARSE. A re-anchor updated the ANCHOR to the re-wrapped
     source and left the REPLACEMENT in the old shape; the mutated file is a
     SyntaxError. Where the harness compiles first this is counted OUT of the
     denominator as a "fault" and the score line still reads clean. Where it does
     NOT — eleven of the sixteen harnesses holding a break — the unparseable file
     is WRITTEN, the suite reds on an import error, and `killed = not green`
     BANKS A KILL THAT WAS NEVER EARNED. Those scores are not narrower than they
     claim, they are INFLATED.  (wave793 N15/W14, wave794 R2/X3/X10, and 20 more.)
  2. THE ANCHOR IS UNIQUE UNTIL THE MUTANT'S OWN EARLIER EDIT RUNS. Edit 1's
     REPLACEMENT contains edit 2's ANCHOR as a substring, so edit 2 then matches
     twice. Unique at rest, ambiguous mid-mutant — a resting sweep can NEVER see
     it, however carefully it is written.  (device_visibility_0904 V2, wave 9's
     own joinPolicy mutant: the only mutation evidence for that lane.)

⛔ SO THE SEQUENTIAL PART IS THE POINT, not an implementation detail. This tool
does what a harness does: applies each mutant's edits IN ORDER to an in-memory
copy, asserting EXACTLY-ONE against the CURRENT, partially mutated text, then
ast.parse()s the result. Checking the anchors against the resting file instead
would reproduce the blind spot it is here to close.

Nothing is written. No test runs, no file is mutated on disk, no repo is touched
— and the two harnesses that snapshot their targets at IMPORT time and register
atexit/signal handlers to write them back are DEFANGED for the duration of the
import (see `load_module`), because a read-only tool that makes its own importer
a writer is not read-only.

⛔ IT MUST NOT BE ABLE TO REPORT CLEAN BY DOING NOTHING. It prints harnesses
loaded / mutants checked / edits applied, and FAILS LOUDLY if any harness yields
zero mutants, if any harness applies zero edits, or if the totals are empty. A
sweep that finds nothing because it looked at nothing is the exact defect it is
hunting.

MEASURED 2026-09-17: 106 harnesses, 3428 mutants, 3457 edits, and 27 mutants
that measure nothing — the six the harnesses found by running, and 21 nobody had
seen. 26 of the 27 predate wave 9; the oldest has never measured anything since
2026-08-11, and one (telemetry F2) could not have worked on any day of Python.

    python .mutants/_apply_sweep.py                  # everything, fast parse
    python .mutants/_apply_sweep.py --jobs 5         # same, fanned out
    python .mutants/_apply_sweep.py --slow           # whole-file parse, ~10 min
    python .mutants/_apply_sweep.py --no-parse       # anchors only, ~6 s
    python .mutants/_apply_sweep.py --only wave794   # a slice

The default fast parse re-parses the statement an edit lands in rather than the
82k-line file, and CONFIRMS every failure against the whole file before reporting
it — so it can only ever be faster, never more accusing. `--no-parse` is the half
that costs seconds: it still applies every edit in order, so it still catches the
mid-mutant ambiguity that nothing else can.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import importlib.util
import json
import os
import re
import sys
import traceback
from pathlib import Path

SUFFIXES = (".py", ".ts", ".tsx", ".mjs", ".js", ".json", ".rules", ".md",
            ".toml", ".yml", ".yaml", ".txt", ".sh", ".css", ".html")
FILE_COLS = ("fname", "file", "path", "rel", "target", "target_file", "src",
             "relpath", "filename")
# The loop header of the harness's own apply loop: the one place that says what
# each column of its MUTANTS table MEANS. Parsed rather than guessed, because
# the tables are not one shape (5 different column orders across 107 harnesses).
LOOP_RE = re.compile(
    r"^[ \t]*for[ \t]+([A-Za-z_][\w ,]*?)[ \t]+in[ \t]+"
    r"(MUTANTS|selected|chosen|targets)[ \t]*:", re.M)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# ⛔⛔ THREE CHECKOUTS, AND CI HAS ONE. `_anchor_sweep.py` learned this the
# expensive way: for fifteen days every anchor whose target lives in the app repo
# or the fork reported as STALE on a runner that simply never had those files.
# The split is made by looking at the DISK, never by pattern-matching a path — if
# every root is present, a file that resolves nowhere has genuinely moved; if a
# root is absent, this checkout may not hold an opinion at all.
FE = REPO.parent / "dg-research"
FORK = REPO.parent / "dg-hermes-fleet"
ROOT_SPEC = (("backend", REPO), ("app", FE), ("fork", FORK))


def absent_roots():
    """The declared target checkouts that are not on this disk."""
    return [name for name, path in ROOT_SPEC if not Path(path).is_dir()]


def present_roots():
    return [(name, Path(path)) for name, path in ROOT_SPEC
            if Path(path).is_dir()]


def _indents(text):
    """The leading whitespace of every line — what `if 1:` cannot police."""
    return [re.match(r"[ \t]*", line).group(0) for line in text.split("\n")]


# ⛔⛔ THE OBVIOUS `while a[p] == b[p]: p += 1` IS A PYTHON LOOP OVER 4.5 MB, and
# it was 29 of every 31 seconds this sweep spent — six minutes for the full pass
# instead of twenty seconds. That is the difference between a guard that sits in
# the suite and a script somebody means to run one day, which is exactly how
# twenty broken mutants survived five weeks. Blocks make the comparison C-level;
# the result is identical by construction (the last block that matches is still
# compared character by character).
_BLOCKS = (1 << 20, 1 << 12, 1)


def _common_prefix(a, b):
    n = min(len(a), len(b))
    i = 0
    for block in _BLOCKS:
        while i + block <= n and a[i:i + block] == b[i:i + block]:
            i += block
    return i


def _common_suffix(a, b, floor):
    """Shared tail length, never eating into the first `floor` characters."""
    n = min(len(a), len(b)) - floor
    la, lb, i = len(a), len(b), 0
    for block in _BLOCKS:
        while (i + block <= n
               and a[la - i - block:la - i] == b[lb - i - block:lb - i]):
            i += block
    return i


class Fail(Exception):
    """A mutant that would measure nothing."""

    def __init__(self, kind, detail, edit_no=None):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.edit_no = edit_no


# ───────────────────────── loading a harness ──────────────────────────────────

WRITE_ATTEMPTS = []


class _NoWrite:
    """Import-time file writes are recorded, never performed."""

    def __init__(self, what):
        self.what = what

    def __call__(self, *a, **k):
        WRITE_ATTEMPTS.append(self.what)
        return None


def load_module(path: Path):
    """Import a harness with its EXIT HOOKS DEFANGED.

    ⛔⛔ Two harnesses read their targets at import and register atexit/signal
    handlers that write them back, so importing them makes the importing process
    a writer. This audit is read-only and stays that way: the hooks are replaced
    for the duration of the import and any write is recorded as a note."""
    import atexit
    import signal
    name = "_audit_" + path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    saved = (atexit.register, signal.signal,
             Path.write_text, Path.write_bytes, os.replace)
    atexit.register = _NoWrite(f"{path.name}: atexit.register")
    signal.signal = _NoWrite(f"{path.name}: signal.signal")
    Path.write_text = _NoWrite(f"{path.name}: Path.write_text")
    Path.write_bytes = _NoWrite(f"{path.name}: Path.write_bytes")
    os.replace = _NoWrite(f"{path.name}: os.replace")
    try:
        spec.loader.exec_module(mod)      # execution proper is behind __main__
    finally:
        (atexit.register, signal.signal, Path.write_text, Path.write_bytes,
         os.replace) = saved
    return mod


class AstNamespace:
    """Fallback when a harness will not import: evaluate its module-level
    assignments with a tiny literal interpreter, enough to reconstruct MUTANTS
    (constants, string concatenation, tuples/lists/dicts, os.path-free)."""

    def __init__(self, path: Path):
        self.env = {}
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value is None:
                    continue
                try:
                    val = self.ev(node.value)
                except Exception:
                    continue
                for t in targets:
                    if isinstance(t, ast.Name):
                        self.env[t.id] = val

    def ev(self, n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            return self.env[n.id]
        if isinstance(n, ast.Tuple):
            return tuple(self.ev(e) for e in n.elts)
        if isinstance(n, (ast.List, ast.Set)):
            return [self.ev(e) for e in n.elts]
        if isinstance(n, ast.Dict):
            return {self.ev(k): self.ev(v) for k, v in zip(n.keys, n.values)}
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Mod)):
            left, right = self.ev(n.left), self.ev(n.right)
            return left + right if isinstance(n.op, ast.Add) else left % right
        if isinstance(n, ast.JoinedStr):
            out = []
            for v in n.values:
                out.append(v.value if isinstance(v, ast.Constant)
                           else str(self.ev(v.value)))
            return "".join(out)
        raise ValueError(ast.dump(n)[:60])

    def __getattr__(self, item):
        try:
            return self.env[item]
        except KeyError:
            raise AttributeError(item)


# ───────────────────────── shape detection ────────────────────────────────────

PATH_ASSIGN_RE = re.compile(
    r"^[ \t]*[\w]+[ \t]*=[ \t]*((?:\(.*?\)|[\w.]+)[ \t]*/[ \t]*"
    r"(?:[A-Za-z_]\w*|\"[^\"]+\"|'[^']+')|_path_for\([^)]*\))[ \t]*(?:#.*)?$")


def loop_shape(source: str):
    """(column names, the expression the loop body resolves the file with).

    ⛔ THE PATH IS NOT ALWAYS INSIDE THE LOOP. `chatgpt_landing` hoists
    `path = ROOT / "research.py"` ABOVE its loop, and reading only the body left
    all 14 of its mutants "unresolved" — i.e. this tool reporting on ITSELF
    rather than on the harness, which is the exact mistake two of the original
    seventeen stale anchors made. So the lines before the loop are read too."""
    matches = list(LOOP_RE.finditer(source))
    if not matches:
        return None, None
    m = matches[-1]                         # the apply loop; dry runs come first
    names = [n.strip() for n in m.group(1).split(",") if n.strip()]
    tail = source[m.end():].split("\n")[1:12]
    expr = None
    for line in tail:
        if re.match(r"^[ \t]*(for|if|while|def|class)\b", line):
            if "originals" not in line:
                break
        hit = re.match(r"^[ \t]*[\w]+[ \t]*=[ \t]*(.+?)(?:[ \t]*#.*)?$", line)
        if not hit:
            continue
        rhs = hit.group(1).strip()
        if ("_path_for(" in rhs or re.search(r"\b(ROOT|REPO|FORK|FE|WEB|BASE)\b"
                                             r"[ \t]*/", rhs)):
            expr = rhs
            break
        if rhs.startswith("{") and "MUTATED_FILES" in rhs:
            expr = "@MUTATED_FILES"
            break
    if expr is None:
        head = source[:m.start()].split("\n")
        for line in reversed(head[-25:]):
            hit = PATH_ASSIGN_RE.match(line)
            if hit:
                expr = hit.group(1).strip()
                break
    return names, expr


def mutant_files(mod, names, expr, entry, mod_dict):
    """The relative path(s) this mutant's edits live in, the harness's way.

    ⛔⛔ THE COLUMN NAME IS NOT THE AUTHORITY — the loop body is. `serve_stop_rearm`
    names its last column `target` and it holds a TEST SELECTION ("tests/a.py
    tests/b.py"); the file is hoisted above the loop as `path = ROOT / RESEARCH`.
    Reading the column made all 15 of its mutants report "target file not found",
    which is this tool accusing a harness of the fault it itself just committed.
    So a column is only believed when the loop body actually divides ROOT by it.
    """
    # 1. an explicit per-mutant file column THAT THE LOOP BODY USES
    used = set(re.findall(r"[A-Za-z_]\w*", expr or "")) if expr else set(names)
    for col in FILE_COLS:
        if col in names and (not expr or col in used):
            i = names.index(col)
            val = entry[i] if i < len(entry) else None
            if isinstance(val, str) and " " not in val and val.endswith(SUFFIXES):
                return [val], f"column {col!r}"
    # 2. a whole-table file set the harness spreads each anchor over
    if expr == "@MUTATED_FILES" or (not expr and getattr(mod, "MUTATED_FILES", None)):
        files = list(getattr(mod, "MUTATED_FILES", []) or [])
        if files:
            return files, "MUTATED_FILES"
    # 3. the constant the loop body divides ROOT by (SRC / TARGET / RESEARCH …)
    if expr:
        const = re.search(r"/[ \t]*([A-Za-z_]\w*|\"[^\"]+\"|'[^']+')[ \t]*$", expr)
        if const:
            tok = const.group(1)
            if tok[:1] in "\"'":
                return [tok[1:-1]], "literal in loop"
            val = mod_dict.get(tok)
            if isinstance(val, str):
                return [val], f"constant {tok}"
            if isinstance(val, (list, tuple)) and val:
                return [str(v) for v in val], f"constant {tok}"
    # 4. last resort — the sweep's heuristic: any column that looks like a path
    cols = [c for c in entry if isinstance(c, str) and c.endswith(SUFFIXES)
            and " " not in c]
    if cols:
        return cols, "heuristic column"
    for attr in ("MUTATED_FILES", "SRC", "TARGET", "RESEARCH", "FILE"):
        val = getattr(mod, attr, None)
        if isinstance(val, str):
            return [val], f"module {attr}"
        if isinstance(val, (list, tuple)) and val:
            return [str(v) for v in val], f"module {attr}"
    return [], "UNRESOLVED"


def find_edits(names, entry):
    if "edits" in names:
        i = names.index("edits")
        if i < len(entry) and isinstance(entry[i], (list, tuple)):
            cand = entry[i]
            if cand and isinstance(cand[0], (tuple, list)):
                return list(cand), True
    for col in entry:                      # heuristic: first list of pairs
        if isinstance(col, (list, tuple)) and col and \
                isinstance(col[0], (tuple, list)) and len(col[0]) == 2 and \
                all(isinstance(x, str) for x in col[0]):
            return list(col), False
    return None, False


# ───────────────────────── the audit itself ───────────────────────────────────

class Auditor:
    def __init__(self, base: Path, roots, fast: bool = False,
                 parse: bool = True, missing_roots=()):
        self.base = base
        self.parse = parse
        self.roots = roots                 # [(label, Path)]
        self.fast = fast
        # ⛔ The ONLY thing that may excuse a mutant: a whole target checkout
        # being off this disk. Never "the file is missing", which is the same
        # excuse a renamed fork file would hide behind.
        self.missing_roots = list(missing_roots)
        self.cache = {}
        self.stats = dict(harnesses=0, imported=0, ast=0, mutants=0, edits=0,
                          py_parsed=0, skipped_parse=0)
        self.failures = []
        self.unreachable = []
        self.notes = []
        self.per_harness = {}

    def read(self, rel: str, hint: Path | None):
        key = (rel, str(hint))
        if key in self.cache:
            return self.cache[key]
        if hint is not None and hint.exists():
            text = hint.read_text(encoding="utf-8", errors="replace")
            self.cache[key] = (text, "harness path")
            return self.cache[key]
        for label, root in self.roots:
            p = root / rel
            if p.exists():
                self.cache[key] = (p.read_text(encoding="utf-8", errors="replace"),
                                   label)
                return self.cache[key]
        self.cache[key] = (None, None)
        return self.cache[key]

    def audit_mutant(self, mod, harness, names, expr, entry, mod_dict):
        edits, _by_name = find_edits(names, entry)
        if edits is None:
            raise Fail("no-edits", "no edit list found in this table row")
        files, how = mutant_files(mod, names, expr, entry, mod_dict)
        if not files:
            raise Fail("unresolved-target", "cannot tell which file this mutant edits")

        texts, where = {}, {}
        for rel in files:
            hint = None
            path_for = getattr(mod, "_path_for", None)
            if callable(path_for):
                try:
                    hint = Path(path_for(rel))
                except Exception:
                    hint = None
            if hint is None:
                root = getattr(mod, "ROOT", self.base)
                try:
                    hint = Path(root) / rel
                except Exception:
                    hint = None
            text, src = self.read(rel, hint)
            texts[rel] = text
            where[rel] = src
        missing = [f for f, t in texts.items() if t is None]
        if missing:
            raise Fail("target-missing", f"target file(s) not found: {missing}")
        originals = dict(texts)

        touched, reindented = set(), set()
        for n, pair in enumerate(edits, 1):
            if len(pair) != 2:
                raise Fail("bad-edit", f"edit {n} is not a (from, to) pair", n)
            frm, to = pair
            if not isinstance(frm, str) or not isinstance(to, str):
                raise Fail("bad-edit", f"edit {n} is not two strings", n)
            if frm == to:
                raise Fail("no-op-edit",
                           f"edit {n}: replacement equals anchor — mutates nothing", n)
            counts = {f: texts[f].count(frm) for f in files}
            total = sum(counts.values())
            hit = [f for f in files if counts[f] == 1]
            if total != 1 or len(hit) != 1:
                kind = ("anchor-0x" if total == 0 else "anchor-2x+")
                stage = ("at rest" if n == 1 else
                         f"AFTER THIS MUTANT'S OWN EDIT{'S' if n > 2 else ''} "
                         f"1..{n - 1} — invisible to a resting-file sweep")
                raise Fail(kind,
                           f"edit {n}: anchor occurs {total}x in {files} ({stage}): "
                           f"{frm[:90]!r}", n)
            f = hit[0]
            if _indents(frm) != _indents(to):
                reindented.add(f)
            texts[f] = texts[f].replace(frm, to, 1)
            touched.add(f)
            self.stats["edits"] += 1

        for f in sorted(touched):
            if not self.parse or not f.endswith(".py"):
                self.stats["skipped_parse"] += 1
                continue
            try:
                self.parse_check(f, originals[f], texts[f],
                                 whole=f in reindented)
            except SyntaxError as syn:
                raise Fail("parse-error",
                           f"the mutant does not parse: {f} line {syn.lineno}: "
                           f"{syn.msg}", None)
            self.stats["py_parsed"] += 1
        return sorted(where[f] for f in touched), len(edits)

    # ⭐ WHY THERE IS A FAST PATH. research.py is 82k lines and ast.parse costs
    # ~1.5s, so parsing it once per mutant is ~an hour for the 3.5k mutants —
    # too slow to sit in the suite, which is where a guard has to live to keep
    # its grip. A python file's TOP-LEVEL statements are independent, so an edit
    # confined to one of them can be judged by re-parsing that statement alone
    # (milliseconds), and anything that fails there is re-checked against the
    # WHOLE file before it is reported. False alarms are impossible by
    # construction; the mode is validated against a full-parse run of every
    # mutant, and any edit that is not confined falls back to the full parse.
    def spans(self, rel, text):
        """The statement NESTING of a file: (top, innermost-by-line, parent, starts).

        ⭐ A nested block is parsed back by putting `if 1:` in front of it, so the
        unit re-parsed for a one-line edit is the FUNCTION it sits in rather than
        the 5000-line class — which is the difference between 1.5s and under a
        millisecond, i.e. between a gate that runs and a script somebody means to
        run.

        ⛔ IT IS AN INDEX, NOT A LIST, and that is what lets this live in the
        suite. The first cut kept every statement span in one size-sorted list and
        scanned it per edit: ~100k spans × 3.4k edits is 350 SECONDS, so the guard
        would have been a script somebody means to run — which is how the twenty
        pre-existing breaks survived for five weeks. Here each line carries its
        INNERMOST statement and each statement its parent, so the smallest
        statement containing a change is found by walking up a chain of depth ~6.
        Same verdicts, 20x faster: proven by re-running the whole sweep against
        the list version — 27 findings, byte-identical."""
        key = ("spans", rel, len(text))
        if key in self.cache:
            return self.cache[key]
        starts = [0]
        for line in text.split("\n")[:-1]:
            starts.append(starts[-1] + len(line) + 1)
        n_lines = len(starts)

        def span(node):
            first = min([node.lineno] + [d.lineno for d in
                                         getattr(node, "decorator_list", [])])
            last = node.end_lineno
            a = starts[first - 1]
            b = starts[last] if last < len(starts) else len(text)
            return first, last, a, b

        tree = ast.parse(text, filename=rel)
        top = [span(n)[2:] for n in tree.body]
        innermost = [None] * (n_lines + 1)
        parent = {}

        def visit(node, cur):
            # ⛔ Walk EVERY child, not just `body`/`orelse`/`finalbody`: an
            # except handler's statements hang off `handlers`, and a `body` is
            # not always a list — a lambda's and an inline conditional's are
            # single EXPRESSIONS. Iterating those threw a TypeError that the
            # first version of this tool reported as 23 broken mutants: itself,
            # mistaken for the thing it audits.
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    first, last, a, b = span(child)
                    sp = (a, b)
                    # Pre-order, so a child overwrites the lines its parent
                    # claimed — the last write for a line is its INNERMOST
                    # statement. Siblings never overlap, so nothing else can.
                    for ln in range(first - 1, min(last, n_lines)):
                        innermost[ln] = sp
                    if cur is not None and cur != sp:
                        parent[sp] = cur
                    visit(child, sp)
                else:
                    visit(child, cur)

        visit(tree, None)
        self.cache[key] = (top, innermost, parent, starts)
        return self.cache[key]

    def parse_check(self, rel, original, mutated, whole=False):
        if not self.fast:
            ast.parse(mutated, filename=rel)
            return
        try:
            top, innermost, parent, starts = self.spans(rel, original)
        except SyntaxError:
            ast.parse(mutated, filename=rel)       # the file is already broken
            return
        p = _common_prefix(original, mutated)
        tail = _common_suffix(original, mutated, p)
        q, r = len(original) - tail, len(mutated) - tail
        # smallest statement that wholly contains the change, nested or not.
        # ⛔ Skipped when the edit RE-INDENTS: `if 1:` accepts any consistent
        # indent, so a dedent that matches no enclosing level parses there and
        # breaks the file. That one goes straight to the top-level statement,
        # which carries every level the line could have belonged to.
        pick = None
        if not whole:
            ln = bisect.bisect_right(starts, p) - 1
            sp = innermost[ln] if 0 <= ln < len(innermost) else None
            seen = 0
            while sp is not None and not (sp[0] <= p and q <= sp[1]):
                nxt = parent.get(sp)
                seen += 1
                if nxt is sp or seen > 500:        # a one-line `with x: pass`
                    nxt = None                     # shares its child's span
                sp = nxt
            pick = sp
        if pick is not None:
            a, b = pick
            snippet = original[a:p] + mutated[p:r] + original[q:b]
            try:
                ast.parse("if 1:\n" + snippet, filename=rel)
                self.stats["fast_snippets"] = self.stats.get("fast_snippets", 0) + 1
                return
            except SyntaxError:
                pass                               # widen before believing it
        outer = [(a, b) for a, b in top if a <= p and q <= b]
        if outer:
            a, b = outer[-1]
            snippet = original[a:p] + mutated[p:r] + original[q:b]
            try:
                ast.parse(snippet, filename=rel)
                self.stats["fast_snippets"] = self.stats.get("fast_snippets", 0) + 1
                return
            except SyntaxError:
                pass
        # ⛔ NOTHING IS REPORTED ON A SNIPPET'S WORD. Every failure, and every
        # edit that does not sit inside one statement, is judged by parsing the
        # WHOLE mutated file — so the fast path can only ever be faster, never
        # more accusing.
        ast.parse(mutated, filename=rel)
        self.stats["full_parses"] = self.stats.get("full_parses", 0) + 1

    def audit_harness(self, path: Path):
        harness = path.name
        self.stats["harnesses"] += 1
        source = path.read_text(encoding="utf-8")
        mode = "import"
        try:
            mod = load_module(path)
            self.stats["imported"] += 1
            mod_dict = vars(mod)
        except Exception as exc:
            mode = "ast"
            self.notes.append(f"{harness}: would not import "
                              f"({type(exc).__name__}: {exc}) — parsed with ast")
            try:
                mod = AstNamespace(path)
                self.stats["ast"] += 1
                mod_dict = mod.env
            except Exception as exc2:
                self.failures.append(dict(harness=harness, mutant="-",
                                          kind="harness-unloadable",
                                          detail=f"{type(exc2).__name__}: {exc2}"))
                self.per_harness[harness] = dict(mode="FAILED", mutants=0, edits=0)
                return
        if WRITE_ATTEMPTS:
            for what in WRITE_ATTEMPTS:
                self.notes.append(f"{what} at IMPORT time — neutralised here, "
                                  f"but it fires in any process that imports "
                                  f"this harness, pytest included")
            WRITE_ATTEMPTS.clear()
        names, expr = loop_shape(source)
        mutants = getattr(mod, "MUTANTS", None)
        if not mutants:
            self.failures.append(dict(harness=harness, mutant="-",
                                      kind="no-mutants",
                                      detail="harness yields ZERO mutants — "
                                             "a score from it measures nothing"))
            self.per_harness[harness] = dict(mode=mode, mutants=0, edits=0)
            return
        if not names:
            self.notes.append(f"{harness}: no apply loop found — column shape guessed")
            names = []
        n_ok = n_edits = 0
        roots_used = set()
        for entry in mutants:
            entry = list(entry)
            mid = entry[0] if entry else "?"
            self.stats["mutants"] += 1
            try:
                used, ne = self.audit_mutant(mod, harness, names, expr, entry, mod_dict)
                roots_used.update(used)
                n_ok += 1
                n_edits += ne
            except Fail as f:
                rec = dict(harness=harness, mutant=str(mid),
                           kind=f.kind, detail=f.detail, edit=f.edit_no)
                if f.kind == "target-missing" and self.missing_roots:
                    rec["detail"] += (f" — not this checkout's call, missing "
                                      f"root(s): {self.missing_roots}")
                    self.unreachable.append(rec)
                else:
                    self.failures.append(rec)
            except Exception as exc:
                self.failures.append(
                    dict(harness=harness, mutant=str(mid), kind="auditor-error",
                         detail=f"{type(exc).__name__}: {exc}\n"
                                f"{traceback.format_exc(limit=3)}"))
        self.per_harness[harness] = dict(mode=mode, mutants=len(mutants),
                                         clean=n_ok, edits=n_edits,
                                         columns=",".join(names) or "?",
                                         roots=sorted(roots_used))

    def run(self, mut_dir: Path, verbose=True, jobs=1, only=""):
        wanted = [w for w in (only or "").split(",") if w]
        paths = [p for p in sorted(mut_dir.glob("*.py"))
                 if not p.name.startswith("_")
                 and (not wanted or any(w in p.name for w in wanted))]
        if jobs <= 1:
            for path in paths:
                self.one(path, verbose)
            return
        # ⭐ research.py is 82k lines and ast.parse costs ~1.5s, so a serial pass
        # over ~3.5k mutants is 40 minutes. Harnesses are independent; fan them
        # out. Nothing is written, so there is nothing to race over.
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        args = [(str(p), str(self.base),
                 [(lab, str(r)) for lab, r in self.roots],
                 self.fast, self.parse, self.missing_roots) for p in paths]
        with ctx.Pool(jobs) as pool:
            for res in pool.imap_unordered(_worker, args):
                self.absorb(res, verbose)

    def one(self, path: Path, verbose=True):
        import time
        t0 = time.time()
        self.audit_harness(path)
        d = self.per_harness.get(path.name, {})
        if verbose:
            print(f"  {path.name:52s} {d.get('mutants', 0):4d} mutants "
                  f"{d.get('edits', 0):5d} edits  {time.time() - t0:6.1f}s",
                  flush=True)

    def absorb(self, res, verbose=True):
        stats, failures, unreachable, notes, per_harness, secs = res
        for k, v in stats.items():
            self.stats[k] = self.stats.get(k, 0) + v
        self.failures.extend(failures)
        self.unreachable.extend(unreachable)
        self.notes.extend(notes)
        self.per_harness.update(per_harness)
        if verbose:
            for name, d in per_harness.items():
                print(f"  {name:52s} {d.get('mutants', 0):4d} mutants "
                      f"{d.get('edits', 0):5d} edits  {secs:6.1f}s", flush=True)


def _worker(arg):
    """One harness, in its own process. Returns everything the parent sums."""
    import time
    path, base, roots, fast, parse, missing = arg
    t0 = time.time()
    mut_dir = str(Path(path).parent)
    if mut_dir not in sys.path:
        sys.path.insert(0, mut_dir)
    a = Auditor(Path(base), [(lab, Path(r)) for lab, r in roots], fast=fast,
                parse=parse, missing_roots=missing)
    a.audit_harness(Path(path))
    return (a.stats, a.failures, a.unreachable, a.notes, a.per_harness,
            time.time() - t0)


# ───────────────────────── the API the suite calls ────────────────────────────

def sweep(fast=True, parse=True, jobs=1, only="", verbose=False):
    """Apply every mutant in every harness, in order, in memory.

    Returns (stats, broken, unreachable, notes, per_harness):

      stats       — harnesses / mutants / edits, the non-vacuity numbers
      broken      — [{harness, mutant, kind, detail}] : mutants measuring NOTHING
      unreachable — the same shape, for mutants whose target checkout is not on
                    this disk. ⛔ Only an ABSENT ROOT may put a mutant here; a
                    file that is simply gone while its repo is present is BROKEN.
      notes       — harnesses that would not import, import-time write attempts
      per_harness — {name: {mutants, clean, edits, …}} : the vacuity floor

    ⛔ The caller must judge `stats` as well as `broken`. A run that checked no
    harnesses, no mutants or applied no edits is not a clean run — it is the
    silence this tool exists to break. `vacuity()` below names it.
    """
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    a = Auditor(REPO, present_roots(), fast=fast, parse=parse,
                missing_roots=absent_roots())
    a.run(HERE, verbose=verbose, jobs=jobs, only=only)
    return a.stats, a.failures, a.unreachable, a.notes, a.per_harness


def vacuity(stats, per_harness):
    """The ways this sweep could report clean by having done nothing.

    ⛔⛔ A harness yielding ZERO mutants, or applying ZERO edits, is a HOLE in
    the audit — not a clean harness and not a broken wave. It is named as loudly
    as an empty run, because an auditor that passes by looking at nothing is the
    precise defect being fixed here."""
    reasons = []
    if not stats.get("harnesses"):
        reasons.append("no harnesses were loaded at all")
    if not stats.get("mutants"):
        reasons.append("no mutants were checked at all")
    if not stats.get("edits"):
        reasons.append("no edit was applied at all")
    empty = sorted(h for h, d in per_harness.items() if not d.get("mutants"))
    if empty:
        reasons.append(f"harness(es) yielding ZERO mutants: {empty}")
    unapplied = sorted(h for h, d in per_harness.items()
                       if d.get("mutants") and not d.get("edits"))
    if unapplied:
        reasons.append(f"harness(es) where NOT ONE edit applied: {unapplied}")
    return reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--jobs", type=int, default=1,
                    help="harnesses swept in parallel (nothing is written)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--only", default="",
                    help="sweep just the harnesses whose name contains this")
    ap.add_argument("--no-parse", action="store_true",
                    help="apply the edits in order and check the anchors only "
                         "— the half that costs seconds and catches the "
                         "mid-mutant ambiguity nothing else can see")
    ap.add_argument("--slow", action="store_true",
                    help="parse the WHOLE mutated file every time instead of "
                         "the statement the edit lands in (same verdicts, ~10 min)")
    args = ap.parse_args()

    missing = absent_roots()
    for label in missing:
        print(f"⚠ root {label} absent — its anchors cannot be judged here")

    sys.path.insert(0, str(HERE))
    stats, failures, unreachable, notes, per_harness = sweep(
        fast=not args.slow, parse=not args.no_parse, jobs=args.jobs,
        only=args.only, verbose=not args.quiet)

    print(f"\nbackend  {REPO}")
    for label, p in present_roots():
        print(f"root {label:8s} {p}")
    print(f"\nharnesses loaded : {stats['harnesses']}  "
          f"({stats['imported']} imported, {stats['ast']} via ast)")
    print(f"mutants checked  : {stats['mutants']}")
    print(f"edits applied    : {stats['edits']}  "
          f"({stats['py_parsed']} python files parsed, "
          f"{stats['skipped_parse']} non-python targets not parsed)")

    if notes:
        print("\nnotes:")
        for n in notes:
            print(f"  · {n}")
    if unreachable:
        print(f"\n… {len(unreachable)} mutant(s) NOT CHECKED — their target "
              f"files live in a repo this checkout does not have ({missing}):")
        for f in unreachable:
            print(f"  {f['harness']}  {f['mutant']}  {f['detail']}")

    if failures:
        print(f"\n⛔ {len(failures)} MUTANT(S) MEASURE NOTHING:")
        for f in failures:
            print(f"  {f['harness']}  {f['mutant']}  [{f['kind']}]  {f['detail']}")
    else:
        print("\n✓ every mutant applies in order and every python mutant parses")

    if args.json:
        Path(args.json).write_text(json.dumps(
            dict(stats=stats, failures=failures, unreachable=unreachable,
                 per_harness=per_harness, notes=notes), indent=1),
            encoding="utf-8")
        print(f"\nwrote {args.json}")

    reasons = vacuity(stats, per_harness)
    if reasons:
        print("\n⛔⛔ VACUOUS RUN — this sweep measured nothing:")
        for r in reasons:
            print(f"    {r}")
        return 3
    print(f"\nSUMMARY: {stats['harnesses']} harnesses, {stats['mutants']} "
          f"mutants, {stats['edits']} edits applied, {len(failures)} measuring "
          f"nothing")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
