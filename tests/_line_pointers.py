"""Finds notes that point at a LINE NUMBER instead of naming what they mean.

⛔⛔ WHY THIS EXISTS (wave 10.10). The notes in this repository are the only index
anyone has into a 90,000-line file, and 217 of them pointed somewhere by number.
Sampled by hand, every one that pointed into research.py landed on unrelated
code: the file moves by thousands of lines a wave and nothing re-anchors a
number. Each was replaced with the name of the function, closure, rule or
constant it meant, and this module is what keeps a new one from creeping back.

WHAT IS READ — notes, never runtime text:
  · Python: comments (consecutive comment lines joined, so a pointer split over
    a line break is still one pointer), docstrings, and the `//` comments of the
    page JavaScript that research.py hands the browser inside Python strings.
    Other strings are runtime text (prompts, log lines, fixtures, assertion
    messages) and are not read: changing one changes behaviour.
  · Prose files (.md, .txt, .toml, .yml, .cfg, .ini, .cmd, .example): every
    paragraph, lines joined.

THE FORMS (examples in `tests/test_no_line_pointers.py`, built at run time so
this file carries none): a file name followed by a colon and a number or a
GitHub-style line anchor; a file name followed by "line", "L" or a tilde and a
number; the bare module shorthands (`rules`, `route`, `page`, ...) with a colon;
the word "line(s)" with a tilde or a three-digit number; a bare colon-number in
prose; a parenthesised tilde-number; "at/near/around/see" plus a tilde-number,
or "@" plus a number; and a bare tilde-number of four digits with no unit after.

WHAT IS NOT A POINTER, and why the forms above already leave it alone: ports
(`PORTS`), counts with a unit ("about 600 KB" written with a tilde), log-file
lines quoted as evidence ("log line N"), JSON parser messages ("line N
column M"), Python tracebacks (`File "x", line N`), zero-padded fixture text,
times, dates, versions and permission bits. Anything else that trips a form
goes on the closed exemption list in the test, by file and exact text.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

EXT = r"(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|rules|md|css|sh|json|ya?ml|toml)"
UNITS = (r"(?:k|K|KB|MB|GB|KiB|MiB|ms|s|sec|secs|seconds?|mins?|minutes?|h|hrs?|hours?|"
         r"days?|px|chars?|characters?|bytes?|lines?|tokens?|words?|rows?|items?|entries|"
         r"entry|calls?|runs?|files?|commits?|tests?|mutants?|sites?|times|x|of|per|URLs?|"
         r"sources?|steps?|searches|writes?|reads?|iterations?|attempts?|frames?|spawns?|"
         r"scans?|ops?|nodes?)")

#: Ports this project listens on or talks to. A bare `:8000` in a note is the
#: server's address, not a line.
PORTS = frozenset({"80", "443", "3000", "5000", "8000", "8001", "8080", "8443", "9222"})

FORMS: "dict[str, re.Pattern]" = {
    "file:N": re.compile(r"\w\." + EXT + r"(?::~?\d+|#L\d+)(?![\d.])"),
    "file line N": re.compile(r"\w\." + EXT + r"`?,?\s+(?:at\s+|on\s+)?~?\s*(?:lines?|L)\s*~?\d+"),
    "file ~N": re.compile(r"\w\." + EXT + r"`?\s+\(?~\d+"),
    "#LN": re.compile(r"#L\d+\b"),
    "module:N": re.compile(r"\b(?:rules|route|layout|page|research|usePipeline|firestore):~?\d+"),
    # ⛔ The match may START only at the tilde or the word, never at the space
    # before it — a leading `\s*` would step past the three look-behinds.
    "line N": re.compile(r"(?<![\w-])(?<!log )(?<!\", )(?:~\s*)?lines?\s+(?:~\s*\d+|[1-9]\d{2,})"
                         r"(?!\s*column)", re.I),
    # ⛔ NOT after `[`: `text[:200]` is a slice written in prose, not a line.
    ":N": re.compile(r"(?:^|(?<=[\s(,;·]))~?:~?(\d{3,})(?:[-–]\d+)?(?![\d.:])"),
    "(~N)": re.compile(r"\(\s*~\d{3,}(?:\s*[-,/]\s*~?\d+)*\s*\)"),
    "at ~N": re.compile(r"(?:\b(?:at|near|around|see)\s+~|@\s*~?)\d{3,}\b(?![.,]?\d)"
                        r"(?!\s*(?:-\s*)?" + UNITS + r"\b)"),
    "~N": re.compile(r"(?<![\w.~])~\d{4,}(?![\d.,]?\d)(?!\s*(?:-\s*)?" + UNITS + r"\b)"
                     r"(?!\s*[-–]\s*~?\d)"),
}


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    form: str
    match: str
    block: str  # the note the pointer sits in, lines joined

    def __str__(self):
        return f"{self.path}:{self.line}  [{self.form}]  {self.match!r}  in: {self.block[:160]!r}"


_PATH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-()[]")


def find_in_text(text: str) -> "list[tuple[str, str]]":
    """Every (form, matched text) in one note. Overlapping forms report once.
    A file-name form is widened leftwards to the whole path, so the report and
    the exemption list carry the whole file name, not its last letter."""
    out, taken = [], []
    for form, rx in FORMS.items():
        for m in rx.finditer(text):
            if form == ":N" and m.group(1) in PORTS:
                continue
            start = m.start()
            if form.startswith("file"):
                while start > 0 and text[start - 1] in _PATH_CHARS:
                    start -= 1
            if any(a < m.end() and start < b for a, b in taken):
                continue
            taken.append((start, m.end()))
            out.append((form, text[start:m.end()]))
    return out


# ── where the notes are ─────────────────────────────────────────────────────
_JS_COMMENT = re.compile(r"(?:^|\s)//(.*)$")


def _docstring_lines(src: str) -> "set[int]":
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    return {n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)}


def python_notes(src: str) -> "list[tuple[int, str]]":
    """(first line, text) for every note in a Python source: joined comment
    runs, docstrings, and joined runs of `//` comments inside other strings."""
    docs = _docstring_lines(src)
    notes: "list[tuple[int, str]]" = []
    run_start, run_last, run = None, None, []

    def flush():
        nonlocal run_start, run_last, run
        if run:
            notes.append((run_start, " ".join(run)))
        run_start, run_last, run = None, None, []

    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            line = tok.start[0]
            body = tok.string.lstrip("#").lstrip(":").strip()
            if run and line == run_last + 1:
                run.append(body)
            else:
                flush()
                run_start, run = line, [body]
            run_last = line
        elif tok.type == tokenize.STRING:
            if tok.start[0] in docs:
                notes.append((tok.start[0], " ".join(tok.string.split())))
                continue
            js, js_start, prev = [], None, None
            for k, seg in enumerate(tok.string.split("\n")):
                m = _JS_COMMENT.search(seg)
                if m and prev is not None and k == prev + 1:
                    js.append(m.group(1).strip())
                elif m:
                    if js:
                        notes.append((js_start, " ".join(js)))
                    js, js_start = [m.group(1).strip()], tok.start[0] + k
                else:
                    if js:
                        notes.append((js_start, " ".join(js)))
                    js, js_start = [], None
                prev = k if m else None
            if js:
                notes.append((js_start, " ".join(js)))
    flush()
    return notes


def prose_notes(text: str) -> "list[tuple[int, str]]":
    """(first line, paragraph) for a prose file: blank lines split paragraphs."""
    notes, start, para = [], None, []
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not para:
                start = i
            para.append(line.strip())
        elif para:
            notes.append((start, " ".join(para)))
            para = []
    if para:
        notes.append((start, " ".join(para)))
    return notes


PROSE_SUFFIXES = (".md", ".txt", ".toml", ".yml", ".yaml", ".cfg", ".ini", ".cmd", ".example")


def find_in_file(rel: str, text: str) -> "list[Hit]":
    if rel.endswith(".py"):
        notes = python_notes(text)
    elif rel.endswith(PROSE_SUFFIXES):
        notes = prose_notes(text)
    else:
        return []
    return [Hit(rel, line, form, match, block)
            for line, block in notes for form, match in find_in_text(block)]


#: The phrase two notes carried for a month after the server stopped doing it:
#: the local API has bound the loopback address behind a token since 09-05.
BIND_EVERYWHERE = re.compile(r"\bbinds\s+every\s+interface\b", re.I)
