"""Mutation harness — the owner's 09-30 run, Claude, round 2 (from the captures).

⛔⛔ WHAT THIS CODE DECIDES.
  E* — effort by the page: the option found by its captured `data-effort-id`,
       the tier believed from the MODEL BUTTON after the press (the menus close),
       set again right before Send when it drifted, and that re-set touching
       nothing else; the run says the page's word, "Extra".
  R* — the Research switch: found in the "+" menu past its icon glyph, pressed
       for real, and on only when the row reads checked (the menu opened again
       to read it, and closed after).
  P* — the Research panel: the card pressed for real, the panel waited for.
  S* — its sources rows read on every check, pressing nothing, kept for the run.
  V* — the vision rescue is not spent on a panel that has listed its sites.
  N* — Claude's left sidebar kept out of the steps.
  D* — the report: its card pressed, its panel seen, downloaded by the page; the
       sidebar is not an open panel.
  M* — one Sources list for a report shaped like Claude's.
  H*/X* — no Max in the hints or the narration; the narrator hears the sites.

⛔ The browser tests need patchright and Chrome; where they SKIP, the baseline is
not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/claude_r2_mutants.py
  .venv/bin/python .mutants/claude_r2_mutants.py E1 R3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
MODELS = "models.py"

TESTS = ["tests/test_claude_0930_r2.py", "tests/test_e2e0930_p2_p3.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ E — effort by the page ═════════════════════════════════════════════
    ("E1", RESEARCH, "⛔⛔ the read after the press is the row again — the menus have "
     "closed, so a set tier reads unset (df26bdd)",
     [("    if (P.trigTestid) {\n        const trig = [...document.querySelectorAll(",
       "    if (false && P.trigTestid) {\n        const trig = [...document.querySelectorAll(")]),
    ("E2", RESEARCH, "the option is no longer found by its captured data-effort-id",
     [("                            if (P.effortId) {\n                                hit = rows.find(",
       "                            if (false && P.effortId) {\n                                hit = rows.find(")]),
    ("E3", RESEARCH, "⛔⛔ no re-set before Send — the 09-30 run: Low by hand, researched at Low",
     [("            if (reactivate and _eff_want and _eff_seen and _eff_seen != _eff_want",
       "            if (False and reactivate and _eff_want and _eff_seen and _eff_seen != _eff_want")]),
    ("E4", RESEARCH, "⛔ the re-set runs the whole setup: the '+' menu opens seconds before Send",
     [("        if effort_only:\n            # ⭐ The pre-send re-set ends here",
       "        if False:\n            # ⭐ The pre-send re-set ends here")]),
    ("E5", MODELS, "the run says 'Extra high' where the page says 'Extra'",
     [('_EFFORT_LABELS: dict = {}', '_EFFORT_LABELS: dict = {"extra": "Extra high"}')]),

    # ═══ R — the Research switch ════════════════════════════════════════════
    ("R1", RESEARCH, "the captured test id is no longer looked for",
     [("        const hit = [...m.querySelectorAll('[data-testid=\"' + P.testid + '\"]')].find(vis);",
       "        const hit = null;")]),
    ("R2", RESEARCH, "⛔⛔ the icon glyph stays in the text — the exact match fails again "
     "(every run since 09-03)",
     [('_CLAUDE_RESEARCH_ROW_JS = r"""(P) => {\n    const norm = s => (s || \'\')'
       ".replace(/[\\ue000-\\uf8ff]/g, ' ')",
       '_CLAUDE_RESEARCH_ROW_JS = r"""(P) => {\n    const norm = s => (s || \'\')'
       ".replace(/[\\u0000-\\u0000]/g, ' ')")]),
    ("R3", RESEARCH, "⛔ the row is clicked from inside the page, not pressed for real",
     [("    if (!on && P.attr) (sw || row).setAttribute(P.attr, P.value);",
       "    if (!on && P.attr) (sw || row).click();")]),
    ("R4", RESEARCH, "⛔⛔ a press counts as on without the row's read-back",
     [("                research_enabled = await _claude_research_reads_on(page)",
       "                research_enabled = True")]),
    ("R5", RESEARCH, "the closed menu is not opened again to read the row",
     [("            await page.click(f'button[data-testid=\"{_CLAUDE_TOOLS_TRIGGER_TESTID}\"]',",
       "            raise RuntimeError('no reopen'); await page.click(f'button[data-testid=\"{_CLAUDE_TOOLS_TRIGGER_TESTID}\"]',")]),
    ("R6", RESEARCH, "the menu opened for the read-back is left open over the composer",
     [('    if st.get("found"):\n        await _close()\n    return on',
       '    return on')]),

    # ═══ P — the Research panel ═════════════════════════════════════════════
    ("P1", RESEARCH, "⛔ the research card is back on the dispatched pointer chain",
     [("            _rp = await _claude_open_research_panel(page)",
       "            _rp = {}")]),
    ("P2", RESEARCH, "one look instead of up to 5 s — 'did not mount' on a slow panel",
     [('    how = await _sr_real_click(page, "claude-research-card", tag="[Claude]")\n'
       '    for _ in range(max(1, int(wait_s / 0.25))):',
       '    how = await _sr_real_click(page, "claude-research-card", tag="[Claude]")\n'
       '    for _ in range(1):')]),

    # ═══ S — the sources rows ═══════════════════════════════════════════════
    ("S1", RESEARCH, "⛔⛔ no row is read while the run goes (09-30: url=0 until done)",
     [('                    _cl_rows = await _claude_panel_source_rows(p["page"])',
       '                    _cl_rows = {}')]),
    ("S2", RESEARCH, "the union is per check — the sites are lost when the rows go",
     [('                    _cl_union = p.setdefault("_claude_row_hosts", {})',
       '                    _cl_union = {}')]),
    ("S3", RESEARCH, "the finished read drops the sites the run saw",
     [('                                 + list((p or {}).get("_claude_row_hosts") or {}),',
       '                                 + [],')]),
    ("S4", RESEARCH, "the host and its count run together ('royalcanin.com19 sources')",
     [("                else if (c.nodeType === 1) { t += ' '; walk(c); t += ' '; }",
       "                else if (c.nodeType === 1) { walk(c); }")]),
    ("S5", RESEARCH, "the rows' counts no longer reach the source number",
     [('                        rows=sum(_cl_union.values()),',
       '                        rows=0,')]),

    # ═══ V — the vision rescue, not spent on a panel that lists sites ═══════
    ("V1", RESEARCH, "⛔⛔ listed sites do not count — a screenshot and a model call on "
     "every Claude run, finding nothing (09-30 review)",
     [('    if agent == "Claude" and int(listed_sites or 0) > 0:\n'
       '        return False, "panel-lists-sites"\n',
       '')]),
    ("V2", RESEARCH, "⛔ the panel opened in this check is not read before the rescue "
     "decides — the rows were read while it was shut",
     [('                    if _panel_open_now and not _cl_sites:',
       '                    if False and _panel_open_now and not _cl_sites:')]),

    # ═══ N — the sidebar ════════════════════════════════════════════════════
    ("N1", RESEARCH, "⛔ Claude's left sidebar is read as a panel — 'Chats and tasks' steps",
     [("                    if (root.closest(APP_NAV + ', nav') || root.querySelector(APP_NAV)) continue;\n",
       "")]),

    # ═══ D — the report ═════════════════════════════════════════════════════
    ("D1", RESEARCH, "⛔ the report card is back on the dispatched pointer chain",
     [("        _rep = await _claude_open_report_panel(page)",
       "        _rep = {}")]),
    ("D2", RESEARCH, "⛔⛔ no download by the page — computer use downloads it again",
     [("        md_page = await _claude_download_report_by_page(page, label)",
       '        md_page = ""')]),
    ("D3", RESEARCH, "⛔ the mount probe cannot see the captured panel — computer use opens it",
     [("                f'{_CLAUDE_REPORT_PANEL_SEL}, '\n",
       "")]),
    ("D4", RESEARCH, "Claude's sidebar is taken for an open panel and 'closed' first",
     [("                    if (el.closest(APP_NAV)) continue;\n",
       "")]),

    # ═══ M — one Sources list ═══════════════════════════════════════════════
    ("M1", RESEARCH, "⛔⛔ a listed-only source is numbered into a second list (09-30's doc)",
     [("        if own_at is not None and url_end > own_at:\n            continue\n",
       "")]),

    # ═══ H/X — the words ════════════════════════════════════════════════════
    ("H1", RESEARCH, "Max is back in the computer-use setup hint",
     [('            "that is already active. Claude: the model must be {claude_family} "',
       '            "that is already active. Claude: the model must be {claude_family} with Max effort "')]),
    ("H2", RESEARCH, "Max is back in Claude's narration timeline",
     [('        + effort_label(p2_labels("claude").get("effort")) + " effort) + Research tools",',
       '        + "Max effort) + Research tools",')]),
    ("X1", RESEARCH, "the narrator does not hear the panel's sites",
     [('        hv = d.get("sourceHosts")',
       '        hv = None')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider",
             "-rs"],
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
    # ⛔⛔ AN IN-FLIGHT MARKER: a run killed mid-mutant leaves this file naming the
    # file that holds one, and the next run refuses to start until it is restored.
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
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, TESTS)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — the real-Chrome or node tests did not run "
              "here, so no kill below would mean anything.\n" + out[-1500:])
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
