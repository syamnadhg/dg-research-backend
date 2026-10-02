"""Mutation harness — Wave 14 (rest), 2026-10-02: every document faithful to the
original — equations from their source, Gemini's own citation numbers and list,
a report's pictures kept as pictures, and the export catcher put back before the
page presses Export to PDF.

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  M*  equations: an element keeping its TeX (Gemini's `data-math`, a KaTeX root
      with its TeX annotation, MathML) is written from it, never its drawing;
      a block on its own lines, with no blank line; inline in a sentence, one
      line; inside a table cell, a heading, bold, italics, a link or a quote
      always inline (with its own spaces); in a cell a bare `|` written `\\vert `
      (the single bar), a `\\|` kept; an inline one written `$$ tex $$`, a space
      between it and any dollar outside it; inside code nothing is maths; an
      element with no source is converted as before.
  G*  Gemini's citations: the panel read uses Gemini's own conversion; chip N
      is row N of "Sources used in the report", by its place (the owner's 18:45
      recording) — every chip and mark numbered and none 0, the list found, its
      rows Gemini's own row elements (one inside another is one), each with one
      web address, no link outside a row, a row for the highest number, nothing
      glued to a bullet, every number written links; chips and table marks
      become `\\[N\\]` glued to the word before; marks inside code stay; ALL of
      Gemini's rows listed in its order, row N as number N, each with its own
      title; a row we never put in a document listed by title only; a link-less
      own section replaced, one with links refused; any failure is today's
      document; "Copy contents" gets a short cap. A closed list is opened by a
      press of its own toggle and closed again — only for a report that cites,
      only a closed list showing no row, never a toggle in a link or one of two,
      waiting for its rows to come and go. The write links Gemini's list, whose
      rows count 1, 2, 3 one number each, though some rows go uncited; every
      other list still matches one for one.
  F*  pictures: an svg, a canvas and a blob image drawn by the page with the
      page's colours, on the ground they sit on, at twice their size; never an
      icon, a control's glyph, a hidden drawing or one under the rehost's size;
      a web image left to the rehost; the read's copy carries them and the log
      counts them; ChatGPT's frame read draws its diagram; the read's limits —
      20 pictures, its time, one picture's size, one svg's wait, a copy that
      matches the page — each hold, and each picture left by one is counted.
  C*  the export catcher: put back before the page's own PDF press after a
      navigation, and nothing pressed when it cannot be.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline is
not a measurement, so the runner refuses to score a skipped baseline.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/w14_rest_1002_mutants.py
  .venv/bin/python .mutants/w14_rest_1002_mutants.py M1 G3
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
    "math": ["tests/test_doc_math_1002.py"],
    "gemini": ["tests/test_gemini_footnotes_1002.py"],
    "figures": ["tests/test_doc_figures_1002.py"],
    "frame": ["tests/test_chatgpt_dr_read_1001.py", "-k",
              "cannot_draw or read_off_the_frame_when"],
    "catch": ["tests/test_chatgpt_exports_1002.py", "-k",
              "navigated_before or cannot_be_put_back"],
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

MUTANTS = [
    # ── M: equations keep their source ──────────────────────────────────────
    ("M1", RESEARCH, "⛔⛔ every equation is written from its drawing again",
     [('                if found is not None and "_noformat" not in (parent_tags or ()):\n',
       "                if False:\n")],
     "math"),
    ("M2", RESEARCH, "an equation inside code is made maths",
     [('                if found is not None and "_noformat" not in (parent_tags or ()):\n',
       "                if found is not None:\n")],
     "math"),
    ("M3", RESEARCH, "a `div` with `data-math` and no class is written inline",
     [('        return tex, "math-block" in cls or (name == "div" and "math-inline" not in cls)\n',
       '        return tex, "math-block" in cls\n')],
     "math"),
    ("M4", RESEARCH, "a KaTeX display equation is written inline",
     [('    return tex, "katex-display" in cls or (name == "math" and el.get("display") == "block")\n',
       '    return tex, (name == "math" and el.get("display") == "block")\n')],
     "math"),
    ("M5", RESEARCH, "a MathML block is written inline",
     [('    return tex, "katex-display" in cls or (name == "math" and el.get("display") == "block")\n',
       '    return tex, "katex-display" in cls\n')],
     "math"),
    ("M6", RESEARCH, "a block keeps its blank lines — the web ends it early",
     [("        lines = [ln.rstrip() for ln in tex.strip().splitlines() if ln.strip()]\n",
       "        lines = [ln.rstrip() for ln in tex.strip().splitlines()]\n")],
     "math"),
    ("M7", RESEARCH, "a block in a table cell or heading breaks the line",
     [('    if block and not ({"_inline"} | _DOC_MATH_WRAPPED) & tags:\n', "    if block:\n")],
     "math"),
    ("M8", RESEARCH, "a `|` in an equation in a table cell ends the cell",
     [(r'        one = " ".join(re.sub(r"\\.|\|", lambda m: r"\vert " if m.group(0) == "|"' + "\n"
       r'                              else m.group(0), one).split())' + "\n",
       "        one = one\n")],
     "math"),
    ("M9", RESEARCH, "an inline equation keeps its line breaks",
     [('    one = " ".join(tex.split())\n', "    one = tex\n")],
     "math"),
    ("M10", RESEARCH, "a block written inline is glued to the words beside it",
     [('    return " %s " % one if block else one\n', "    return one\n")],
     "math"),
    ("M11", RESEARCH, "⛔ a KaTeX root with its TeX is written from its drawing",
     [('    if not ({"katex", "katex-display"} & cls or name == "math"):\n',
       '    if not (name == "math"):\n')],
     "math"),
    ("M12", RESEARCH, "an empty `data-math` is written as an empty equation",
     [("    if isinstance(tex, str) and tex.strip():\n", "    if isinstance(tex, str):\n")],
     "math"),
    # (Review 10-02: the cell's bar, a dollar beside an equation, a block in a mark.)
    ("M13", RESEARCH, "⛔ a block inside bold, italics, a link or a quote breaks the line — raw TeX",
     [('    if block and not ({"_inline"} | _DOC_MATH_WRAPPED) & tags:\n',
       '    if block and "_inline" not in tags:\n')],
     "math"),
    ("M14", RESEARCH, "a block inside a link breaks the line",
     [('_DOC_MATH_WRAPPED = frozenset({"a", "b", "strong", "i", "em", "del", "s", "q"})\n',
       '_DOC_MATH_WRAPPED = frozenset({"b", "strong", "i", "em", "del", "s", "q"})\n')],
     "math"),
    ("M15", RESEARCH, "a block inside a quote breaks the line",
     [('_DOC_MATH_WRAPPED = frozenset({"a", "b", "strong", "i", "em", "del", "s", "q"})\n',
       '_DOC_MATH_WRAPPED = frozenset({"a", "b", "strong", "i", "em", "del", "s"})\n')],
     "math"),
    ("M16", RESEARCH, "a block inside strike-through breaks the line",
     [('_DOC_MATH_WRAPPED = frozenset({"a", "b", "strong", "i", "em", "del", "s", "q"})\n',
       '_DOC_MATH_WRAPPED = frozenset({"a", "b", "strong", "i", "em", "s", "q"})\n')],
     "math"),
    ("M17", RESEARCH, "⛔⛔ a `|` in a cell is the DOUBLE bar again — \"p(j | x)\" draws \"p(j‖x)\"",
     [(r'lambda m: r"\vert " if', r'lambda m: r"\|" if')],
     "math"),
    ("M18", RESEARCH, "a `\\|` the TeX holds in a cell is split — its bar made a second one",
     [(r're.sub(r"\\.|\|", lambda m', r're.sub(r"\|", lambda m')],
     "math"),
    ("M19", RESEARCH, "the cell's `\\vert` runs into the letter after it — a KaTeX error",
     [(r'r"\vert " if m.group(0)', r'r"\vert" if m.group(0)')],
     "math"),
    ("M20", RESEARCH, "the cell's bar leaves two spaces where there was one",
     [(r'else m.group(0), one).split())' + "\n", r'else m.group(0), one).split(" "))' + "\n")],
     "math"),
    ("M21", RESEARCH, "⛔ an inline equation has no space inside — `100\\$` runs into its close",
     [('    one = "%s$$ %s $$%s" % (_DOC_MATH_OPEN, one, _DOC_MATH_CLOSE)\n',
       '    one = "%s$$%s$$%s" % (_DOC_MATH_OPEN, one, _DOC_MATH_CLOSE)\n')],
     "math"),
    ("M22", RESEARCH, "⛔ an inline equation is not marked — two touching ones become one",
     [('    one = "%s$$ %s $$%s" % (_DOC_MATH_OPEN, one, _DOC_MATH_CLOSE)\n',
       '    one = "$$ %s $$" % one\n')],
     "math"),
    ("M23", RESEARCH, "⛔ two equations side by side are written as one broken equation",
     [('    text = text.replace(_DOC_MATH_CLOSE + _DOC_MATH_OPEN, _DOC_MATH_CLOSE + " " + _DOC_MATH_OPEN)\n',
       "")],
     "math"),
    ("M24", RESEARCH, "a dollar right before an equation runs into its opening",
     [('    text = text.replace("$" + _DOC_MATH_OPEN, "$ " + _DOC_MATH_OPEN)\n', "")],
     "math"),
    ("M25", RESEARCH, "a dollar right after an equation runs into its close",
     [('    text = text.replace(_DOC_MATH_CLOSE + "$", _DOC_MATH_CLOSE + " $")\n', "")],
     "math"),
    ("M26", RESEARCH, "⛔⛔ the invisible marks stay in the saved document",
     [('    return text.replace(_DOC_MATH_OPEN, "").replace(_DOC_MATH_CLOSE, "")\n',
       "    return text\n")],
     "math"),
    ("M27", RESEARCH, "⛔⛔ the converter's markdown is never joined — the marks stay in",
     [("            text = _doc_math_join(_doc_img_converter_cls(MarkdownConverter)(\n",
       "            text = (_doc_img_converter_cls(MarkdownConverter)(\n")],
     "math"),
    ("M28", RESEARCH, "the join stops before it starts — the marks stay in",
     [("    if _DOC_MATH_OPEN not in text and _DOC_MATH_CLOSE not in text:\n        return text\n",
       "    if True:\n        return text\n")],
     "math"),
    # ── G: Gemini's own numbers and its own list ────────────────────────────
    ("G1", RESEARCH, "⛔⛔ Gemini's panel is converted as before — no numbers, no list",
     [("                md_text = convert(html) if convert else html_to_markdown(html)\n",
       "                md_text = html_to_markdown(html)\n")],
     "gemini"),
    ("G3", RESEARCH, "a chip with no number is let through",
     [("    if any(n is None for n in numbers):\n", "    if False:\n")],
     "gemini"),
    ("G4", RESEARCH, "a page with no list is read anyway",
     [("    if used is None:\n        return _no(", "    if False:\n        return _no(")],
     "gemini"),
    ("G5", RESEARCH, "⛔ the rows of \"read but not used\" are read as the list's",
     [("        if at is None or at >= next_at:\n", "        if at is None:\n")],
     "gemini"),
    # (G6-G10, G12, G21-G23, G26, G27 were the dormant join's — a number only on a
    # row that carries it, every row cited, a row's host off its title. The
    # owner's 18:45 recording proved the join by place: G32 on are its mutants.)
    ("G11", RESEARCH, "⛔ a link in no row is ignored",
     [("    if any(id(a) not in in_rows for a in links):\n", "    if False:\n")],
     "gemini"),
    ("G13", RESEARCH, "a number keeps the space before it — it never links",
     [(r"""_GEMINI_NUMBER_SLOT_RE = re.compile('[ \t]*\ue300""",
       r"""_GEMINI_NUMBER_SLOT_RE = re.compile('\ue300""")],
     "gemini"),
    ("G14", RESEARCH, "a mark inside code is turned into a number",
     [('        (in_code if s.find_parent(["pre", "code"]) is not None else marks).append((s, ns))\n',
       "        marks.append((s, ns))\n")],
     "gemini"),
    ("G15", RESEARCH, "a table's raw marks stay as text",
     [("    for s, _ns in marks:\n        s.replace_with(", "    for s, _ns in []:\n        s.replace_with(")],
     "gemini"),
    ("G16", RESEARCH, "where Gemini's list began is never marked",
     [("    used.insert_before(NavigableString(_GEMINI_CUT_SLOT))\n", "")],
     "gemini"),
    ("G17", RESEARCH, "⛔ a report's own list WITH links gets a second list",
     [("        if _doc_cited_public_keys(tmask[own_at:]):\n            return _no(\"the report ends",
       "        if False:\n            return _no(\"the report ends")],
     "gemini"),
    ("G18", RESEARCH, "the report's own link-less list stays — two sections",
     [("        text = text[:own_at].rstrip()\n        tmask = _mask_code_spans(text)[0]\n"
       "        log(f\"[{who}] the report's own sources section holds no link — replaced by \"\n"
       "            \"Gemini's own",
       "        text = text\n        tmask = _mask_code_spans(text)[0]\n"
       "        log(f\"[{who}] the report's own sources section holds no link — replaced by \"\n"
       "            \"Gemini's own")],
     "gemini"),
    ("G19", RESEARCH, "⛔ a number glued to a bullet is written — the list item is lost",
     [("    if _CG_BARE_MARKER_RE.search(tmask):\n"
       "        return _no(\"a citation comes right after a bullet, a list number or a heading mark \"\n"
       "                   \"at the start of its line\")\n"
       "    if not _CG_OWN_NUMBER_RE.search(tmask):",
       "    if False:\n"
       "        return _no(\"a citation comes right after a bullet, a list number or a heading mark \"\n"
       "                   \"at the start of its line\")\n"
       "    if not _CG_OWN_NUMBER_RE.search(tmask):")],
     "gemini"),
    ("G24", RESEARCH, "a row that is not a public page is written as one",
     [("    if url:\n        return _cg_pdf_source_row(url, title, [n])\n",
       "    if True:\n        return _cg_pdf_source_row(url, title, [n])\n")],
     "gemini"),
    ("G25", RESEARCH, "⛔ a number that cannot link at the write is written anyway",
     [("    if got != want:\n        return _no(f\"{got} of {want} numbers would link at the write\")\n"
       "    log(f\"[{who}] Gemini's own",
       "    if False:\n        return _no(f\"{got} of {want} numbers would link at the write\")\n"
       "    log(f\"[{who}] Gemini's own")],
     "gemini"),
    ("G28", RESEARCH, "the numbers' summary never says they skip",
     [('              else (f", {span[0]} to {span[-1]} with gaps" if span else "")))\n',
       '              else ""))\n')],
     "gemini"),
    ("G29", RESEARCH, "⛔ a failure while reading them is not caught — the panel read fails",
     [("    except Exception as e:\n        log(f\"[{label or 'Gemini'}] Gemini's citations stay as they are",
       "    except ImportError as e:\n        log(f\"[{label or 'Gemini'}] Gemini's citations stay as they are")],
     "gemini"),
    ("G30", RESEARCH, "⛔ \"Copy contents\" is waited on for 90 s again",
     [("                timeout=_GEMINI_COPY_CONTENTS_S)\n", "                timeout=90.0)\n")],
     "gemini"),
    ("G31", RESEARCH, "a report citing nothing is not quiet",
     [("    if not (chips or marks or in_code):\n        return None\n",
       "    if not (chips or marks or in_code):\n        return _no(\"nothing\")\n")],
     "gemini"),
    # ── G (10-02 18:45): chip N is row N of Gemini's list, by its place ─────
    ("G32", RESEARCH, "⛔ a citation numbered 0 is let through",
     [("    if 0 in cited:\n", "    if False:\n")],
     "gemini"),
    ("G33", RESEARCH, "⛔⛔ rows are found by the old rule (a number on the row) — the recorded list joins nothing",
     [("        if node.name == _GEMINI_ROW_TAG and not any(",
       "        if node.has_attr(_GEMINI_INDEX_ATTR) and not any(")],
     "gemini"),
    ("G34", RESEARCH, "⛔ a row element inside a row is a second row — every row after it shifts",
     [("        if node.name == _GEMINI_ROW_TAG and not any(id(p) in row_ids for p in node.parents):\n",
       "        if node.name == _GEMINI_ROW_TAG:\n")],
     "gemini"),
    ("G35", RESEARCH, "a closed list is not said to be closed",
     [("    if not (links or row_els):\n        return _no(", "    if False:\n        return _no(")],
     "gemini"),
    ("G36", RESEARCH, "⛔ a row with two addresses is joined to one of them",
     [("        if len(urls) != 1:\n", "        if not urls:\n")],
     "gemini"),
    ("G37", RESEARCH, "⛔ a row with no web address is not said to have none",
     [("        if len(urls) != 1:\n", "        if len(urls) > 1:\n")],
     "gemini"),
    ("G38", RESEARCH, "each row loses its title — the list shows hosts",
     [('        sub = r.find(attrs={"data-test-id": "sub-title"})\n', "        sub = None\n")],
     "gemini"),
    ("G39", RESEARCH, "⛔⛔ a row on the owner's Drive or an agent's own host is listed with its address",
     [("        rows.append((_doc_public_source_url(next(iter(urls))), title))\n",
       "        rows.append((next(iter(urls)), title))\n")],
     "gemini"),
    ("G40", RESEARCH, "⛔ a number past the end of the list is let through",
     [("    if max(cited) > len(rows):\n", "    if False:\n")],
     "gemini"),
    ("G41", RESEARCH, "a list exactly as long as the highest number is refused",
     [("    if max(cited) > len(rows):\n", "    if max(cited) >= len(rows):\n")],
     "gemini"),
    ("G42", RESEARCH, "a report with nothing left to number gets the list anyway",
     [("    if not _CG_OWN_NUMBER_RE.search(tmask):\n        return _no(",
       "    if False:\n        return _no(")],
     "gemini"),
    ("G43", RESEARCH, "⛔⛔ row N is written as number N - 1",
     [("    out_rows = [_gemini_source_row(url, title, k) for k, (url, title) in enumerate(rows, 1)]\n",
       "    out_rows = [_gemini_source_row(url, title, k) for k, (url, title) in enumerate(rows)]\n")],
     "gemini"),
    ("G44", RESEARCH, "⛔ only the rows the text cites are listed — not Gemini's list",
     [("    out_rows = [_gemini_source_row(url, title, k) for k, (url, title) in enumerate(rows, 1)]\n",
       "    out_rows = [_gemini_source_row(url, title, k) for k, (url, title) in enumerate(rows, 1)\n"
       "                if k in cited]\n")],
     "gemini"),
    ("G45", RESEARCH, "a number whose row is not listed is counted as one that must link",
     [("    want = sum(1 for n in _CG_OWN_NUMBER_RE.findall(tmask) if rows[int(n) - 1][0])\n",
       "    want = sum(1 for n in _CG_OWN_NUMBER_RE.findall(tmask))\n")],
     "gemini"),
    ("G46", RESEARCH, "⛔ row N + 1 decides whether number N must link",
     [("    want = sum(1 for n in _CG_OWN_NUMBER_RE.findall(tmask) if rows[int(n) - 1][0])\n",
       "    want = sum(1 for n in _CG_OWN_NUMBER_RE.findall(tmask) if rows[int(n)][0])\n")],
     "gemini"),
    # ── G: a closed list is opened for the read, and closed again ──────────
    ("G47", RESEARCH, "⛔⛔ a closed list is never opened",
     [('    _sources_pressed = await _gemini_used_sources(page, label, "open")\n',
       "    _sources_pressed = False\n")],
     "gemini"),
    ("G48", RESEARCH, "⛔ a list opened for the read is left open",
     [("        if _sources_pressed:\n", "        if False:\n")],
     "gemini"),
    ("G49", RESEARCH, "the read does not wait for the rows",
     [("    for _ in range(int(_GEMINI_SOURCES_WAIT_S / 0.2)):\n", "    for _ in range(0):\n")],
     "gemini"),
    ("G50", RESEARCH, "a list showing no row yet is said to be open",
     [('        done = rows > 0 if want == "open" else',
       '        done = rows >= 0 if want == "open" else')],
     "gemini"),
    ("G51", RESEARCH, "a list is said closed while its toggle still says open",
     [('        done = rows > 0 if want == "open" else not (rows or (now or {}).get("open"))\n',
       '        done = rows > 0 if want == "open" else not rows\n')],
     "gemini"),
    ("G52", RESEARCH, "⛔ a toggle left alone is pressed after the read anyway — an open list is closed",
     [('    if not isinstance(got, dict) or got.get("state") != "pressed":\n',
       "    if not isinstance(got, dict):\n")],
     "gemini"),
    ("G53", RESEARCH, "⛔ a list pressed open is never pressed closed",
     [("    return True\n\n\nasync def extract_gemini_response",
       "    return False\n\n\nasync def extract_gemini_response")],
     "gemini"),
    ("G54", RESEARCH, "the toggle is pressed for a report that cites nothing",
     [("      ? !rows && !open && !!document.querySelector('source-footnote')\n",
       "      ? !rows && !open\n")],
     "gemini"),
    ("G55", RESEARCH, "a list that says it is open is pressed — and so closed",
     [("      ? !rows && !open && !!document.querySelector('source-footnote')\n",
       "      ? !rows && !!document.querySelector('source-footnote')\n")],
     "gemini"),
    ("G56", RESEARCH, "⛔ a toggle inside a link is pressed — the link opens",
     [("  if (b.closest('a')) return {state: 'not a toggle', rows, open};\n", "")],
     "gemini"),
    ("G57", RESEARCH, "the first of two toggles is pressed",
     [("  if (used.length !== 1) return", "  if (!used.length) return")],
     "gemini"),
    ("G58", RESEARCH, "the report's own links count as the list's rows — a closed list stays closed",
     [("      follows(b, a) && (!next || follows(a, next))).length;\n",
       "      (!next || follows(a, next))).length;\n")],
     "gemini"),
    ("G59", RESEARCH, "\"read but not used\" rows count as the list's — a closed list stays closed",
     [("      follows(b, a) && (!next || follows(a, next))).length;\n",
       "      follows(b, a)).length;\n")],
     "gemini"),
    ("G60", RESEARCH, "a list that opened with no row in it is left open",
     [("      : rows > 0 || open;\n", "      : rows > 0;\n")],
     "gemini"),
    ("G61", RESEARCH, "the toggle's own open/closed is never read",
     [("  const open = b.getAttribute('aria-expanded') === 'true';\n", "  const open = false;\n")],
     "gemini"),
    # ── G: the write links Gemini's list, which has rows nobody cites ──────
    ("G62", RESEARCH, "⛔⛔ Gemini's list never links — its rows nobody cites refuse it",
     [("    if cited < written and _doc_cited_rows(md, masked, own_at)[2]:\n", "    if False:\n")],
     "gemini"),
    ("G63", RESEARCH, "⛔ any list in ChatGPT's shape may have rows nobody cites",
     [("    if cited < written and _doc_cited_rows(md, masked, own_at)[2]:\n",
       "    if cited < written:\n")],
     "gemini"),
    ("G64", RESEARCH, "⛔ a number past the end of Gemini's list is linked",
     [("    if cited < written and _doc_cited_rows(md, masked, own_at)[2]:\n",
       "    if _doc_cited_rows(md, masked, own_at)[2]:\n")],
     "gemini"),
    ("G65", RESEARCH, "every list in ChatGPT's shape counts up",
     [("    counts_up = per_row == [[k] for k in range(1, len(per_row) + 1)]\n",
       "    counts_up = True\n")],
     "gemini"),
    ("G66", RESEARCH, "a list counts up from 0 — Gemini's never does",
     [("    counts_up = per_row == [[k] for k in range(1, len(per_row) + 1)]\n",
       "    counts_up = per_row == [[k] for k in range(0, len(per_row))]\n")],
     "gemini"),
    ("G67", RESEARCH, "the rows' numbers are never kept — every list counts up",
     [("        per_row.append(numbers)\n", "")],
     "gemini"),
    # ── F: a report's pictures kept as pictures ─────────────────────────────
    ("F1", RESEARCH, "⛔⛔ the read hands back the page as it is — every picture lost",
     [("        if (got.made || got.failed) {\n", "        if (false) {\n")],
     "figures"),
    ("F2", RESEARCH, "a drawn chart loses the page's colours",
     [("    const KEEP = ['fill', 'fill-opacity',", "    const KEEP = ['fill-opacity',")],
     "figures"),
    ("F3", RESEARCH, "a picture is drawn on a transparent ground",
     [("            if (c && !/^(transparent|rgba\\([^)]*,\\s*0\\))$/i.test(c)) return c;\n",
       "            if (c) return c;\n")],
     "figures"),
    ("F4", RESEARCH, "a picture with no ground of its own is drawn on none",
     [("        return '#ffffff';\n", "        return 'rgba(0, 0, 0, 0)';\n")],
     "figures"),
    ("F5", RESEARCH, "a picture is drawn at the size it shows, not twice it",
     [("        const k = Math.max(0.1, Math.min(2, MAXPX / Math.max(w, h)));\n",
       "        const k = 1;\n")],
     "figures"),
    ("F6", RESEARCH, "⛔ a glyph in a button is drawn as a picture",
     [("            if (n.matches('button, [role=\"button\"], a, .katex, [data-math], math, svg')) return true;\n",
       "            if (n.matches('a, .katex, [data-math], math, svg')) return true;\n")],
     "figures"),
    ("F7", RESEARCH, "⛔ nothing inside ChatGPT's report card (a button) is drawn",
     [("        for (let n = el.parentElement; n && n !== live; n = n.parentElement) {\n",
       "        for (let n = el.parentElement; n; n = n.parentElement) {\n")],
     "frame"),
    ("F8", RESEARCH, "a hidden drawing is drawn",
     [("        if (held(el) || getComputedStyle(el).visibility === 'hidden') continue;\n",
       "        if (held(el)) continue;\n")],
     "figures"),
    ("F9", RESEARCH, "a picture one side of which is under the rehost's size is drawn",
     [("        if (w < MIN || h < MIN) continue;\n", "        if (w < MIN && h < MIN) continue;\n")],
     "figures"),
    ("F10", RESEARCH, "a web image is redrawn by the page instead of left to the rehost",
     [("        if (tag === 'img' && !/^blob:/i.test(el.currentSrc || el.getAttribute('src') || '')) continue;\n",
       "")],
     "figures"),
    ("F11", RESEARCH, "a canvas with no name is named nothing",
     [("        return el.tagName.toLowerCase() === 'svg' ? 'Diagram' : 'Chart';\n",
       "        return '';\n")],
     "figures"),
    ("F12", RESEARCH, "the read's pictures go unlogged",
     [("                    _doc_figures_note(html, label)\n", "")],
     "figures"),
    ("F13", RESEARCH, "⛔ ChatGPT's frame read leaves its diagram out again",
     [("    try { pictures = await (__FIGURES__)(root, out); } catch (e) {}\n", "")],
     "frame"),
    ("F14", RESEARCH, "a picture the page cannot draw is not counted",
     [("        if (!/^data:image\\/png;base64,/.test(url) || url.length > CHARS) { got.failed += 1; continue; }\n",
       "        if (!/^data:image\\/png;base64,/.test(url) || url.length > CHARS) { continue; }\n")],
     "figures"),
    # (Review 10-02: none of the read's own limits was pinned.)
    ("F15", RESEARCH, "⛔ a read draws every picture — no cap of 20",
     [("        if (swaps.length >= MAX) { got.failed += 1; continue; }\n", "")],
     "figures"),
    ("F16", RESEARCH, "a picture past the 20 is not counted — the log says only \"20 drawn\"",
     [("        if (swaps.length >= MAX) { got.failed += 1; continue; }\n",
       "        if (swaps.length >= MAX) { continue; }\n")],
     "figures"),
    ("F17", RESEARCH, "⛔ a read draws past its time",
     [("        if (Date.now() - started >= BUDGET) { got.failed += 1; continue; }\n", "")],
     "figures"),
    ("F18", RESEARCH, "a picture past the read's time is not counted",
     [("        if (Date.now() - started >= BUDGET) { got.failed += 1; continue; }\n",
       "        if (Date.now() - started >= BUDGET) { continue; }\n")],
     "figures"),
    ("F19", RESEARCH, "⛔ a picture too big for the image store is put in anyway",
     [("        if (!/^data:image\\/png;base64,/.test(url) || url.length > CHARS) { got.failed += 1; continue; }\n",
       "        if (!/^data:image\\/png;base64,/.test(url)) { got.failed += 1; continue; }\n")],
     "figures"),
    ("F20", RESEARCH, "⛔⛔ an svg that never finishes drawing holds the page read forever",
     [("    const svgPicture = (el, w, h) => timed(new Promise((ok, no) => {\n",
       "    const svgPicture = (el, w, h) => (new Promise((ok, no) => {\n")],
     "figures"),
    ("F21", RESEARCH, "⛔ a copy that does not match the page gets its pictures in the wrong places",
     [("    if (L.length !== C.length) return got;\n", "")],
     "figures"),
    ("F22", RESEARCH, "ChatGPT's frame read is sent without its picture drawing",
     [('            r = await f.evaluate(_CHATGPT_DR_REPORT_JS.replace("__FIGURES__", _doc_figures_js()),\n',
       "            r = await f.evaluate(_CHATGPT_DR_REPORT_JS,\n")],
     "frame"),
    ("F23", RESEARCH, "⛔ the page read is sent without its picture drawing — every picture lost",
     [('    return _DOC_HTML_READ_JS.replace("__FIGURES__", _doc_figures_js()).replace(\n',
       "    return _DOC_HTML_READ_JS.replace(\n")],
     "figures"),
    # ── C: the export catcher, put back before the page's own PDF press ─────
    ("C1", RESEARCH, "⛔⛔ the page presses Export to PDF with no catcher — Chrome downloads it",
     [("    if await _export_catch_list(page) is None:\n", "    if False:\n")],
     "catch"),
    ("C2", RESEARCH, "⛔ the page presses with no catcher when it cannot be put back",
     [("                f\"— the {kind} export is not pressed\", \"WARN\")\n            return None\n",
       "                f\"— the {kind} export is not pressed\", \"WARN\")\n")],
     "catch"),
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
