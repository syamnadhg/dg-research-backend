"""Mutation harness — 2026-10-02: a report's export caught in the page (Chrome
downloads nothing), and ChatGPT's own citation numbers linked from its PDF.

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  K*  the catcher on the top page: each Blob the page makes into an address is
      kept; a click on an `<a download>` whose href is one of them — by
      `click()` or by an event — is cancelled and its file kept; nothing else
      is touched; a file let go of is not kept; it goes on once; it holds the
      last sixteen; a file is read back byte for byte, a piece at a time.
  P*  Python's side: what a caught file is; a file larger than the cap or read
      back short is not taken; the pieces are the file; only a file caught
      after the press began; a download Chrome still starts is logged;
      computer use is stopped at the catch, gets the catcher back after a
      navigation, takes only the kind asked for; nothing is pressed without
      the catcher; the export comes before the frame read, with or without the
      app's frame; a Markdown file too short or a sources list is no report;
      the PDF is pressed after the Markdown.
  C*  Claude: the page's Download as Markdown and computer use's, both caught;
      nothing pressed without the catcher.
  J*  ChatGPT's PDF: the chips and the sources pages read; every check before
      anything is written (count, per number, one address per number, the
      sources pages = the body, one address per reference id, every number
      written links, no number of its own already); each run in place, glued to
      the word before it; the brief's runs and runs in code removed; a link-less
      sources section of its own replaced, one with links kept (no numbers);
      ChatGPT's own list in its page-42 shape.
  W*  the write: ChatGPT's own list read as its list (only in that shape), its
      numbers linked, the self-check silent.

⛔ The browser tests need patchright and Chrome, and the catcher's own tests
need node; where they SKIP the baseline is not a measurement, so the runner
refuses to score a skipped baseline.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/chatgpt_exports_1002_mutants.py
  .venv/bin/python .mutants/chatgpt_exports_1002_mutants.py K1 J3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

_EXPORTS = "tests/test_chatgpt_exports_1002.py"
#: The tests each group of mutants is measured by (a name, never a path: the
#: anchor sweep reads any "*.py" string in a mutant's row as its target file).
SUITES = {
    "catch": [_EXPORTS, "-k", "click or byte_for_byte or pages_own or let_go or putting_it_on"],
    "kind": [_EXPORTS, "-k", "caught_file"],
    "read": ["tests/test_cua_download_idempotency.py"],
    "chrome": [_EXPORTS, "-k", "both_exports or saved_document or no_pdf_caught or "
               "does_not_match or without_the_catcher or no_export_control or "
               "computer_use_presses or caught_before or catcher_misses or sources_list or "
               "no_app_frame"],
    "frame": ["tests/test_chatgpt_dr_read_1001.py"],
    "claude": ["tests/test_claude_0930_r2.py", "-k",
               "exported_by_the_page or without_the_catcher or presses_the_export"],
    "pair": [_EXPORTS, "-k", "not (click or byte_for_byte or pages_own or let_go or putting_it_on or "
             "caught_file or both_exports or saved_document or no_pdf_caught or "
             "does_not_match or without_the_catcher or no_export_control or "
             "computer_use_presses or caught_before or catcher_misses or sources_list or "
             "no_app_frame)"],
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

MUTANTS = [
    # ── K: the catcher on the top page ──────────────────────────────────────
    ("K1", RESEARCH, "⛔⛔ the export's click goes through — Chrome downloads the file",
     [("        if (kept(this)) { take(this, 'anchor.click()'); return; }\n",
       "        if (kept(this)) { take(this, 'anchor.click()'); }\n")],
     "catch"),
    ("K2", RESEARCH, "⛔ a dispatched or real click on the export's link downloads it",
     [("        e.preventDefault();\n        take(a, 'click event');\n",
       "        take(a, 'click event');\n")],
     "catch"),
    ("K3", RESEARCH, "⛔⛔ no Blob the page makes is kept — nothing is ever caught",
     [("            if (obj instanceof Blob) {\n", "            if (false) {\n")],
     "catch"),
    ("K4", RESEARCH, "every Blob the page ever makes is held",
     [("                while (st.blobs.size > KEEP) st.blobs.delete(st.blobs.keys().next().value);\n",
       "")],
     "catch"),
    ("K5", RESEARCH, "a file the page let go of is still caught",
     [("        try { st.blobs.delete(String(url)); } catch (e) {}\n", "")],
     "catch"),
    ("K6", RESEARCH, "a blob link with no download attribute is swallowed",
     [("            return !!(a && a.hasAttribute && a.hasAttribute('download')\n"
       "                      && st.blobs.has(String(a.href)));\n",
       "            return !!(a && st.blobs.has(String(a.href)));\n")],
     "catch"),
    ("K7", RESEARCH, "the catcher goes on twice — every file is caught twice",
     [("    if (had && had.v === 1) return { armed: true, again: true };\n", "")],
     "catch"),
    ("K8", RESEARCH, "every caught file is held for the life of the page",
     [("        while (st.caught.length > KEEP) st.caught.shift();\n", "")],
     "catch"),
    ("K9", RESEARCH, "⛔ every piece read back is the whole file",
     [("    const bytes = new Uint8Array(await c.blob.slice(P.start, P.end).arrayBuffer());\n",
       "    const bytes = new Uint8Array(await c.blob.arrayBuffer());\n")],
     "catch"),
    ("K10", RESEARCH, "⛔ half of each 32 KB of the file is lost on the way back",
     [("        s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));\n",
       "        s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x4000));\n")],
     "catch"),

    # ── P: Python's side of the catch ───────────────────────────────────────
    ("P1", RESEARCH, "a PDF with a generic type is not a PDF",
     [("    if t.startswith(\"application/pdf\") or (not t.startswith(\"text/\") and n.endswith(\".pdf\")):\n",
       "    if t.startswith(\"application/pdf\"):\n")],
     "kind"),
    ("P2", RESEARCH, "a Markdown file with no type is not Markdown",
     [("    if t.startswith((\"text/markdown\", \"text/x-markdown\")) or n.endswith((\".md\", \".markdown\")):\n",
       "    if t.startswith((\"text/markdown\", \"text/x-markdown\")):\n")],
     "kind"),
    ("P3", RESEARCH, "⛔ a file caught before the press is taken for this export",
     [("        if int(c.get(\"id\") or 0) > since and _export_kind(c) == kind:\n",
       "        if _export_kind(c) == kind:\n")],
     "chrome"),
    ("P4", RESEARCH, "a file of any size is read back",
     [("    if size <= 0 or size > _EXPORT_MAX_BYTES:\n", "    if size <= 0:\n")],
     "read"),
    ("P5", RESEARCH, "⛔ a file read back short is taken",
     [("    if len(data) != size:\n", "    if False:\n")],
     "read"),
    ("P6", RESEARCH, "⛔ every piece reads to the end of the file",
     [("                \"id\": entry[\"id\"], \"start\": start, \"end\": min(size, start + _EXPORT_CHUNK)})\n",
       "                \"id\": entry[\"id\"], \"start\": start, \"end\": size})\n")],
     "read"),
    ("P7", RESEARCH, "⛔ a download Chrome still starts during the export is never logged",
     [("            self.page.on(\"download\", self._on_download)\n", "            pass\n")],
     "chrome"),
    ("P8", RESEARCH, "⛔⛔ computer use is never stopped at the catch — it presses again",
     [("                       abort_event=caught),\n", "                       abort_event=None),\n"),
      ("        if caught.is_set() and not loop_task.done():\n            loop_task.cancel()\n",
       "")],
     "read"),
    ("P9", RESEARCH, "⛔ a page that lost the catcher (a navigation) does not get it back",
     [("            if got is None:\n                await _export_catch_arm(page, label, quiet=True)\n",
       "            if got is None:\n                pass\n")],
     "read"),
    ("P10", RESEARCH, "computer use takes a file of the other kind",
     [("                c = next((x for x in got if int(x.get(\"id\") or 0) > since\n"
       "                          and _export_kind(x) == kind), None)\n",
       "                c = next((x for x in got if int(x.get(\"id\") or 0) > since), None)\n")],
     "read"),
    ("P11", RESEARCH, "⛔ computer use is never asked when the page cannot press the export",
     [("    if got is None and browser and cua_client:\n        prompt, msg = _CHATGPT_DR_CUA_EXPORT[kind]\n",
       "    if False:\n        prompt, msg = _CHATGPT_DR_CUA_EXPORT[kind]\n")],
     "chrome"),
    ("P12", RESEARCH, "computer use is asked for the Markdown when the PDF is wanted",
     [("        prompt, msg = _CHATGPT_DR_CUA_EXPORT[kind]\n",
       "        prompt, msg = _CHATGPT_DR_CUA_EXPORT[\"markdown\"]\n")],
     "chrome"),
    ("P13", RESEARCH, "⛔⛔ the export is pressed without the catcher — a Chrome download",
     [("    if not await _export_catch_arm(page, label):\n        return \"\"\n"
       "    with _ChromeDownloadWatch(page, label):\n",
       "    await _export_catch_arm(page, label)\n"
       "    with _ChromeDownloadWatch(page, label):\n")],
     "chrome"),
    ("P14", RESEARCH, "⛔ a ten-character Markdown file is taken for the report",
     [("        if len(md) < 500:\n            if md_file:\n",
       "        if len(md) < 5:\n            if md_file:\n")],
     "frame"),
    ("P15", RESEARCH, "⛔ a Markdown export that is a sources list is taken for the report",
     [("        if _is_sources_not_document(md, platform=\"chatgpt\"):\n"
       "            log(f\"[{label}] the Markdown export is a sources list",
       "        if False:\n"
       "            log(f\"[{label}] the Markdown export is a sources list")],
     "chrome"),
    ("P16", RESEARCH, "⛔⛔ the PDF is never pressed — no source links ever",
     [("        pdf_file = await _chatgpt_export_caught(page, browser, cua_client, \"pdf\",\n"
       "                                                label, verbose)\n",
       "        pdf_file = None\n")],
     "chrome"),
    ("P17", RESEARCH, "⛔⛔ the export is never pressed — the frame read is the document again",
     [("    if _chatgpt_dr_app_frames(page) or (browser and cua_client):\n"
       "        md = await _chatgpt_dr_export_report(",
       "    if False:\n"
       "        md = await _chatgpt_dr_export_report(")],
     "chrome"),
    ("P18", RESEARCH, "with no app frame, computer use never presses the export",
     [("    if _chatgpt_dr_app_frames(page) or (browser and cua_client):\n",
       "    if _chatgpt_dr_app_frames(page):\n")],
     "chrome"),
    ("P19", RESEARCH, "the copy tier's citation token runs reach the document",
     [("                md = _strip_chatgpt_citation_tokens(md)\n"
       "                log(f\"[{label}] Extracted via T3 CUA + clipboard hijack",
       "                log(f\"[{label}] Extracted via T3 CUA + clipboard hijack")],
     "frame"),

    # ── C: Claude ───────────────────────────────────────────────────────────
    ("C1", RESEARCH, "⛔⛔ no export by the page — computer use presses it every time",
     [("                md_page = await _claude_export_report_by_page(page, label)\n",
       "                md_page = \"\"\n")],
     "claude"),
    ("C2", RESEARCH, "⛔⛔ Claude's export is pressed without the catcher",
     [("        if await _export_catch_arm(page, label):\n            with _ChromeDownloadWatch(page, label):\n",
       "        if await _export_catch_arm(page, label) or True:\n            with _ChromeDownloadWatch(page, label):\n")],
     "claude"),
    ("C3", RESEARCH, "⛔ the page's press is made, its file never looked for",
     [("    got = await _export_catch_wait(page, \"markdown\", since, timeout_s, label)\n",
       "    got = None\n")],
     "claude"),
    ("C4", RESEARCH, "⛔ computer use never presses Claude's export",
     [("                if browser and cua_client:\n                    got = await _cua_export_caught(\n",
       "                if False:\n                    got = await _cua_export_caught(\n")],
     "claude"),

    # ── J: ChatGPT's PDF ────────────────────────────────────────────────────
    ("J1", RESEARCH, "the count check is gone (a later check says something else)",
     [("    if len(body) != len(seq):\n", "    if False:\n")],
     "pair"),
    ("J2", RESEARCH, "the per-number check is gone",
     [("    if collections.Counter(n for n, _u in body) != collections.Counter(seq):\n",
       "    if False:\n")],
     "pair"),
    ("J3", RESEARCH, "⛔ a number opening two addresses is accepted",
     [("        if number_url.setdefault(n, u) != u:\n", "        if False:\n")],
     "pair"),
    ("J4", RESEARCH, "⛔ a number listed twice on the sources pages is accepted",
     [("            if n in listed:\n", "            if False:\n")],
     "pair"),
    ("J5", RESEARCH, "⛔⛔ the sources pages need not agree with the body",
     [("    if listed != number_url:\n", "    if False:\n")],
     "pair"),
    ("J6", RESEARCH, "⛔⛔ a reference id opening two addresses is accepted — a shifted link",
     [("        if refs and ref_url.setdefault(refs[0], number_url[n]) != number_url[n]:\n",
       "        if False:\n")],
     "pair"),
    ("J7", RESEARCH, "⛔ a number that cannot link at the write is written anyway",
     [("    if got != want:\n        return _no(", "    if False:\n        return _no(")],
     "pair"),
    ("J8", RESEARCH, "⛔ an export writing bracketed numbers of its own is numbered over",
     [("    if _CG_OWN_NUMBER_RE.search(masked):\n", "    if False:\n")],
     "pair"),
    ("J9", RESEARCH, "⛔⛔ each number keeps the space before it — none links",
     [("                out.append(_CG_LINE_SPACE_END_RE.sub(\"\", seg) + \"\\\\[%d\\\\]\" % n)\n",
       "                out.append(seg + \"\\\\[%d\\\\]\" % n)\n")],
     "pair"),
    ("J10", RESEARCH, "the brief's run leaves its space behind",
     [("            out.append(_CG_LINE_SPACE_END_RE.sub(\"\", seg))\n        else:\n",
       "            out.append(seg)\n        else:\n")],
     "pair"),
    ("J11", RESEARCH, "⛔ a run inside code is numbered — a number in the code",
     [("            if any(s <= m.start() < e for s, e in code):\n", "            if False:\n")],
     "pair"),
    ("J12", RESEARCH, "⛔ the report's own link-less sources section stays — two sections",
     [("        text = text[:own_at].rstrip()\n", "        text = text\n")],
     "pair"),
    ("J13", RESEARCH, "⛔ a sources section of its own WITH links gets a second list",
     [("        if _doc_cited_public_keys(tmask[own_at:]):\n", "        if False:\n")],
     "pair"),
    ("J14", RESEARCH, "the Sources rows lose the numbers that cite them",
     [("    return \"- %s — %s — cited as %s\" % (head, label, \", \".join(str(n) for n in numbers))\n",
       "    return \"- %s — %s\" % (head, label)\n")],
     "pair"),
    ("J15", RESEARCH, "⛔ one of the agents' own pages is written as a source's link",
     [("            if _doc_is_linkable_url(url) else _doc_escape_link_text(name))\n",
       "            if url else _doc_escape_link_text(name))\n")],
     "pair"),
    ("J16", RESEARCH, "a title's backtick makes a code span of its row — nothing links",
     [("    name = (re.sub(r\"\\s+\", \" \", (title or \"\").replace(\"`\", \"'\")).strip()[:200]\n",
       "    name = (re.sub(r\"\\s+\", \" \", (title or \"\")).strip()[:200]\n")],
     "pair"),
    ("J17", RESEARCH, "⛔ the text beside a chip is read as its number",
     [("                inside = sorted((f for f in frags if f[3] <= _CG_PDF_CHIP_TEXT_MAX\n",
       "                inside = sorted((f for f in frags if True\n")],
     "pair"),
    ("J18", RESEARCH, "⛔ a title runs on into the entries below it",
     [("                            and link[2][3] < f[2] <= top + 1.0),\n",
       "                            and f[2] <= top + 1.0),\n")],
     "pair"),
    ("J19", RESEARCH, "a title takes in the chips' numbers and the address",
     [("        lines = sorted((f for f in texts[link[1]] if f[3] >= _CG_PDF_TITLE_MIN\n",
       "        lines = sorted((f for f in texts[link[1]] if f[3] >= 0\n")],
     "pair"),
    ("J20", RESEARCH, "⛔⛔ with a PDF, nothing is numbered",
     [("    if pdf:\n        numbered = _chatgpt_pdf_numbered(md, pdf, label)\n",
       "    if False:\n        numbered = _chatgpt_pdf_numbered(md, pdf, label)\n")],
     "pair"),

    # ── W: the write ────────────────────────────────────────────────────────
    ("W1", RESEARCH, "⛔⛔ ChatGPT's own list is never read — its numbers never link",
     [("    if not items:\n        return _doc_cited_rows(md, masked, own_at)[0]\n",
       "    if not items:\n        return {}\n")],
     "pair"),
    ("W2", RESEARCH, "⛔ ChatGPT's numbers never match its list",
     [("               or _doc_cited_rows(md, masked, own_at)[1])\n", "               or set())\n")],
     "pair"),
    ("W3", RESEARCH, "the check before the write logs as if it were the write",
     [("    if not quiet:\n        log(f\"[{who}] linked {linked} of its own",
       "    if True:\n        log(f\"[{who}] linked {linked} of its own")],
     "pair"),
    ("W4", RESEARCH, "a list under another heading is read as ChatGPT's",
     [("    if not lines or not _DOC_CITED_HEADING_RE.match(lines[0]):\n", "    if not lines:\n")],
     "pair"),
    ("W5", RESEARCH, "⛔ a line of prose among the rows is let through",
     [("        if m is None or seen != real:\n", "        if seen != real:\n")],
     "pair"),
    ("W6", RESEARCH, "a row holding code is let through",
     [("        if m is None or seen != real:\n", "        if m is None:\n")],
     "pair"),
    ("W7", RESEARCH, "⛔ a number listed under two sources is let through",
     [("        if written & set(numbers) or len(set(numbers)) != len(numbers):\n",
       "        if False:\n")],
     "pair"),
    ("W8", RESEARCH, "⛔ a row opening one of the agents' own pages is put behind its numbers",
     [("        if _doc_is_linkable_url(url):\n            for n in numbers:\n",
       "        if url:\n            for n in numbers:\n")],
     "pair"),
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
