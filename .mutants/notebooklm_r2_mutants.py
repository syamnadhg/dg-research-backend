"""Mutation harness — NotebookLM Customise Audio Overview, round 2 of the 09-30 run.

⛔⛔ WHAT THIS CODE DECIDES (capture 5, tests/fixtures/notebooklm_0930/).
  O* — Customise is opened from the Audio Overview tile, and the window is
       waited for before anything is chosen.
  C* — the configured length keeps its meaning: long = Deep dive + Long,
       default = Deep dive + Default, short = Brief (no Length row).
  F* — the format is chosen first and read back by its radio's checked state
       (the row's class lags the click), and the Length row is waited for.
  L* — the length is chosen and read back by aria-checked; a length that does
       not read back is never generated.
  G* — "Generate now", never "Generate later"; a press counts only when the
       window closes or the audio shows as generating; computer use never runs
       after the page's own Generate took, and gets the SAME open window when
       the page could not finish.
  P* — the computer-use prompt and the vision hints open Customise from the tile.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline is
not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/notebooklm_r2_mutants.py
  .venv/bin/python .mutants/notebooklm_r2_mutants.py O1 G2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
PROMPTS = "prompts.py"

TESTS = ["tests/test_nlm_customise_0930.py", "tests/test_nlm_dup_audio_778.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ O — open Customise from the tile, and wait for it ══════════════════
    ("O1", RESEARCH, "⛔⛔ the tile is not a way in — only the arrow that is gone; "
     "the 09-30 run's 10 computer-use steps again",
     [("        if (!/^\\s*audio overview\\s*$/i.test(el.getAttribute('aria-label') || '')) continue;",
       "        continue;")]),
    ("O2", RESEARCH, "⛔ the window is not waited for — the format read finds no "
     "window and hands the job to computer use",
     [('    how = await _sr_real_click(page, "nlm-audio-open", tag="[Phase3] Audio Overview")\n'
       '    if not how:',
       '    how = await _sr_real_click(page, "nlm-audio-open", tag="[Phase3] Audio Overview")\n'
       '    return bool(how)\n'
       '    if not how:')]),

    # ═══ C — the configured length → Format + Length ═══════════════════════
    ("C1", RESEARCH, "⛔⛔ the default (long) generates Deep dive + Default",
     [('    "long": ("Deep dive", "Long"),\n}',
       '    "long": ("Deep dive", "Default"),\n}')]),
    ("C2", RESEARCH, "short generates a Deep dive instead of Brief",
     [('    "short": ("Brief", None),',
       '    "short": ("Deep dive", "Short"),')]),
    ("C3", RESEARCH, "default generates Long",
     [('    "default": ("Deep dive", "Default"),\n    "long"',
       '    "default": ("Deep dive", "Long"),\n    "long"')]),

    # ═══ F — the format: chosen first, read back by the radio ══════════════
    ("F1", RESEARCH, "⛔ the format is never chosen — a window on Critique or Brief "
     "stays there",
     [('    for op, want in (("format", fmt), ("length", length)):',
       '    for op, want in (("length", length),):')]),
    ("F2", RESEARCH, "⛔ the format is read by the row's class, which lags the click "
     "by seconds — every format change looks like a miss",
     [("        if (radio) return !!radio.checked;",
       "        if (radio) return r.classList.contains('mat-mdc-radio-checked');")]),
    ("F3", RESEARCH, "the wanted option is not waited for — the Length row redrawn "
     "after a format change is read before it exists",
     [('        if not st.get("dialog") or time.monotonic() >= deadline:\n'
       '            offered =',
       '        if True:\n'
       '            offered =')]),

    # ═══ L — the length: chosen, read back ═════════════════════════════════
    ("L1", RESEARCH, "⛔ the length is never chosen — Long is never pressed",
     [('    for op, want in (("format", fmt), ("length", length)):',
       '    for op, want in (("format", fmt),):')]),
    ("L2", RESEARCH, "⛔⛔ a choice that did not take reads as taken — Generate now "
     "on the wrong length",
     [("        opts = (await _nlm_customise_read(page, op, want)).get(\"options\") or []\n"
       "        if _nlm_reads_as(opts, want):",
       "        opts = (await _nlm_customise_read(page, op, want)).get(\"options\") or []\n"
       "        if True:")]),
    ("L3", RESEARCH, "the length is read by a class instead of aria-checked",
     [("        return r.getAttribute('aria-checked') === 'true';",
       "        return r.classList.contains('mat-button-toggle-checked');")]),

    # ═══ G — Generate now, counted only when it took ═══════════════════════
    ("G1", RESEARCH, "⛔⛔ the first Generate-something is pressed — that is "
     "\"Generate later\"",
     [("        const b = btns.find((x) => said(x) === 'generate now')",
       "        const b = btns.find((x) => said(x).startsWith('generate'))")]),
    ("G2", RESEARCH, "⛔ a press counts as generated whether or not it took — a "
     "window left open is never handed on",
     [('    res["pressed"] = True\n    deadline = time.monotonic() + 8.0',
       '    res["pressed"] = True\n    res["generated"] = True\n    return res\n'
       '    deadline = time.monotonic() + 8.0')]),
    ("G3", RESEARCH, "⛔⛔ computer use runs after the page's own Generate took — "
     "the one way to a second Generate",
     [('            if _dom_gen.get("generated"):\n'
       '                # The page\'s own "Generate now" took',
       '            if False:\n'
       '                # The page\'s own "Generate now" took')]),
    ("G4", RESEARCH, "the page never does Customise at all — only computer use",
     [("                _dom_gen = await _nlm_customise_and_generate(browser.page, podcast_length)",
       "                _dom_gen = {}")]),
    ("G5", RESEARCH, "⛔ computer use is not told the window is open — it clicks the "
     "tile a second time",
     [("            _prompt = make_prompt_audio_generate(podcast_length,\n"
       "                                                 panel_already_open=_panel_opened)",
       "            _prompt = make_prompt_audio_generate(podcast_length,\n"
       "                                                 panel_already_open=False)")]),

    # ═══ P — the computer-use prompt and vision hints open it from the tile ══
    ("P1", PROMPTS, "⛔ the fallback may click only the gear that is gone",
     [('- The "Audio Overview" tile in the Studio panel\'s grid of create tiles (the tile '
       'itself — its › arrow only shows on hover), ONCE. It opens the "Customise Audio '
       'Overview" window.',
       '- The gear / settings icon, "Customize" link, or three-dot menu on the Audio '
       'Overview card.')]),
    ("P2", PROMPTS, "step 3 hunts for the gear again (four hovers on 09-30)",
     [('3. If the "Customise Audio Overview" window is already open, go to step 5. '
       'Otherwise click the "Audio Overview" tile in the Studio panel ONCE.',
       "3. Find the Audio Overview card's gear / Customize / three-dot affordance and "
       "click ONLY that.")]),
    ("P3", PROMPTS, "step 6 names no button — \"Generate later\" is as good as now",
     [('6. Click "Generate now" (never "Generate later") EXACTLY ONCE.',
       '6. Click the Generate button inside the customize panel EXACTLY ONCE.')]),
    ("P4", PROMPTS, "the tile is back on the never-click list",
     [('- "Generate later" in the Customise window\n',
       '- "Generate later" in the Customise window\n- The "Audio Overview" card body itself\n')]),
    ("P5", RESEARCH, "the vision hint aims at the gear again",
     [('            "\'Audio Overview\' tile in the Studio panel\'s grid of create tiles (right side) "',
       '            "gear / \'Customise\' arrow ON the Audio Overview card (right side) "')]),
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
