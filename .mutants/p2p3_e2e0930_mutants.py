"""Mutation harness — the owner's 09-30 run, Phase 2 setup and Phase 3 (round 1).

⛔⛔ WHAT THIS CODE DECIDES.
  A* — NotebookLM's audio card is read by its icon name, and the name changed
       (`audio_magic_eraser` → `audio_spark`). ONE list; every reader uses it.
  G* — no computer-use look while the page itself says "Generating".
  U* — the upload waits for the Add-sources dialog, and a control SEEN ends it.
  S* — no computer-use source check when the Sources panel lists every file.
  C* — ChatGPT Phase 2: the "+" by its durable marker; New chat waits for the
       old thread to leave before calling it a miss.
  E* — Claude's effort: Extra high is the wanted tier; the LAST read before Send
       decides what the run says (log, tile, end-of-run summary); computer use
       never gets an effort job, and gets only the Research switch when the page
       already confirmed the model.

⛔ The browser test needs patchright and Chrome; where it SKIPS the baseline is
not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/p2p3_e2e0930_mutants.py
  .venv/bin/python .mutants/p2p3_e2e0930_mutants.py A1 E2
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
PROMPTS = "prompts.py"

TESTS = ["tests/test_e2e0930_p2_p3.py", "tests/test_claude_popover_reopen_0817.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ A — the audio icon, one list, every reader ═════════════════════════
    ("A1", RESEARCH, "⛔⛔ the list loses the new name — the 09-30 run again: the "
     "finished audio is invisible to every page read",
     [('_NLM_AUDIO_ICONS = ("audio_magic_eraser", "audio_spark")',
       '_NLM_AUDIO_ICONS = ("audio_magic_eraser",)')]),
    ("A2", RESEARCH, "⛔ the done check is back on the old literal — computer use "
     "carries completion alone",
     [("                if (__NLM_AUDIO_ICON__.test(el.innerText || el.textContent || '')) return true;",
       "                if ((el.innerText || el.textContent || '').includes('audio_magic_eraser')) return true;")]),
    ("A3", RESEARCH, "the card count is back on the old literal — '0 total' after cleanup",
     [("                if (__NLM_AUDIO_ICON__.test(t)) count++;",
       "                if (t.includes('audio_magic_eraser')) count++;")]),
    ("A4", RESEARCH, "the Deep Dive count is back on the old literal",
     [("                if (__NLM_AUDIO_ICON__.test(t) && /deep dive/i.test(t)) count++;",
       "                if (t.includes('audio_magic_eraser') && /deep dive/i.test(t)) count++;")]),
    ("A5", RESEARCH, "⛔ the download picker is back on the old literal — 'no_cards'",
     [("                    && __NLM_AUDIO_ICON__.test(el.innerText || el.textContent || ''));",
       "                    && (el.innerText || el.textContent || '').includes('audio_magic_eraser'));")]),
    ("A6", RESEARCH, "⛔ the ⋮-menu scope is back on the old name — it falls to 'any "
     "artifact item', and a study guide listed first gets its menu opened",
     [('    {"name": "audio-card", "sel": "artifact-library-item", "needs": list(_NLM_AUDIO_ICONS)},',
       '    {"name": "audio-card", "sel": "artifact-library-item", "needs": ["audio_magic_eraser"]},')]),
    ("A7", RESEARCH, "the ⋮-menu scope reads only the FIRST name of the list",
     [("                    if (!g.needs.some(n => st.indexOf(n) !== -1)) continue;",
       "                    if (st.indexOf(g.needs[0]) === -1) continue;")]),

    # ═══ G — no computer-use look at a card the page says is generating ═════
    ("G1", RESEARCH, "⛔⛔ computer use looks on every poll again — 11 looks at a "
     "'Generating' card on 09-30",
     [("        _gen_now = await _count_nlm_audio_generating(browser.page)\n"
       "        if _gen_now > 0:",
       "        _gen_now = await _count_nlm_audio_generating(browser.page)\n"
       "        if False:")]),
    ("G2", RESEARCH, "⛔ computer use never looks — a poll the page cannot answer "
     "has no fallback",
     [("        _gen_now = await _count_nlm_audio_generating(browser.page)\n"
       "        if _gen_now > 0:",
       "        _gen_now = await _count_nlm_audio_generating(browser.page)\n"
       "        if True:")]),

    # ═══ U — the upload waits for the dialog ════════════════════════════════
    ("U1", RESEARCH, "⛔⛔ the wait is back to about 2 s — the dialog mounts after we "
     "gave both files to computer use",
     [("_NLM_UPLOAD_CONTROL_WAIT_S = 15", "_NLM_UPLOAD_CONTROL_WAIT_S = 2")]),
    ("U2", RESEARCH, "⛔ an upload control on screen does not end the wait — 15 s "
     "lost and 'Add source' pressed over an open dialog",
     [('    return bool(isinstance(picked, dict) and picked.get("label"))\n\n\n'
       'async def _nlm_dom_add_files(',
       '    return False\n\n\n'
       'async def _nlm_dom_add_files(')]),
    ("U3", RESEARCH, "the look and the press no longer share one list of upload "
     "labels — the look sees nothing the press would press",
     [("        picked = await page.evaluate(_NLM_CLICK_JS, list(_NLM_UPLOAD_CONTROL_PATTERNS))",
       "        picked = await page.evaluate(_NLM_CLICK_JS, [r\"choose file\"])")]),

    # ═══ S — no computer-use look at a listed set of sources ════════════════
    ("S1", RESEARCH, "⛔ computer use checks a Sources panel that already lists "
     "every file (2 steps on 09-30)",
     [("        if _rows > 0:\n            log(f\"[NotebookLM] source census (round {_round}): all \"",
       "        if False:\n            log(f\"[NotebookLM] source census (round {_round}): all \"")]),
    ("S2", RESEARCH, "names found only in the page's text skip the check too",
     [("        if _rows > 0:\n            log(f\"[NotebookLM] source census (round {_round}): all \"",
       "        if True:\n            log(f\"[NotebookLM] source census (round {_round}): all \"")]),

    # ═══ C — ChatGPT Phase 2 ═══════════════════════════════════════════════
    ("C1", RESEARCH, "⛔ the '+' has no durable marker — a reworded label sends "
     "Step 1 nowhere (or to another button)",
     [("                    'button[data-composer-navigation-target=\"add-context\"]',\n", "")]),
    ("C2", RESEARCH, "⛔⛔ New chat is judged once, 2 s after the press — the old "
     "thread still on screen reads as 'NOT a fresh chat' (09-30, 17 s lost)",
     [("        cur2 = \"\"\n"
       "        for _ in range(int(_CHATGPT_NEW_CHAT_SETTLE_S / 0.5)):\n"
       "            await asyncio.sleep(0.5)\n"
       "            cur2 = (page.url or \"\").lower()\n"
       "            if \"/c/\" not in cur2 and await _thread_cleared():\n"
       "                break\n",
       "        await asyncio.sleep(2)\n"
       "        cur2 = (page.url or \"\").lower()\n")]),
    ("C3", RESEARCH, "the settle window is too short for a thread that clears at 3 s",
     [("_CHATGPT_NEW_CHAT_SETTLE_S = 5.0", "_CHATGPT_NEW_CHAT_SETTLE_S = 2.0")]),
    ("C4", RESEARCH, "the wait ends on the address alone, before the old thread left",
     [("            if \"/c/\" not in cur2 and await _thread_cleared():",
       "            if \"/c/\" not in cur2:")]),

    # ═══ E — Claude's effort, told honestly ════════════════════════════════
    ("E1", MODELS, "the wanted tier is Max again — six times the usage",
     [('        "effort": "extra", "thinking": False, "tool": "research",',
       '        "effort": "max", "thinking": False, "tool": "research",')]),
    ("E2", RESEARCH, "⛔⛔ setup's flag decides again — setup read the wanted tier, "
     "it was Low by Send, and nothing says so (09-30)",
     [("    s = str(shown or \"\").strip().lower()\n"
       "    if s and s != w:\n"
       "        return {\"missing\": f\"effort is '{s}', not the '{w}' wanted\", \"note\": None}\n",
       "")]),
    ("E3", RESEARCH, "⛔ the consumer never hands over the last read before Send",
     [("                    shown=(mode_state or {}).get(\"effortShown\"))",
       "                    shown=None)")]),
    ("E4", RESEARCH, "⛔ the run's ledger keeps setup's '✓ already' — the end-of-run "
     "summary says the run was at the wanted tier",
     [("                _claude_effort_ledger_at_send(_pol.get(\"effort\"),\n"
       "                                              (mode_state or {}).get(\"effortShown\"),\n"
       "                                              label=label)",
       "                pass")]),
    ("E5", RESEARCH, "the ledger gains a second line instead of correcting the "
     "first — '✓ already' and '✗ missed' for one intent",
     [("    for rec in reversed(_DOM_ATTEMPTS):\n        if rec.get(\"intent\") != intent:",
       "    for rec in []:\n        if rec.get(\"intent\") != intent:")]),
    ("E6", RESEARCH, "the tile names the menu word, not the tier people call it",
     [("                       f\"{effort_label(w)} could not be set\")}",
       "                       f\"{w.capitalize()} could not be set\")}")]),
    ("E7", RESEARCH, "⛔ the ladder descends on effort again — two computer-use rungs "
     "that are told to leave the tier alone",
     [("            return (\"on\" if (st.get(\"hasExtended\") and st.get(\"researchOn\"))\n"
       "                    else \"unknown\")",
       "            return (\"on\" if (st.get(\"hasExtended\") and st.get(\"researchOn\")\n"
       "                             and st.get(\"effortOk\")) else \"unknown\")")]),
    ("E8", RESEARCH, "⛔⛔ the computer-use setup gets the full mission — it reopens "
     "a model menu the page already read (3 of 8 steps on 09-30)",
     [("        _sys_p, _user_p = _claude_cua_setup_mission(platform_l, prompt_system, prompt_user,\n"
       "                                                    label=label)",
       "        _sys_p, _user_p = prompt_system, prompt_user")]),
    ("E9", RESEARCH, "the mission choice ignores what the page confirmed",
     [("    if not (_P2_THINKING_STATE.get(\"claude\") or {}).get(\"model\"):",
       "    if True:")]),
    ("E10", RESEARCH, "setup never records that the page confirmed the model",
     [("                                        \"model\": bool(opus_selected)}",
       "                                        \"model\": False}")]),
    ("E11", MODELS, "⛔ the validator is told to set the effort again",
     [("        f\"{swapped}Verify Claude is on {fam} with the {tool} tool ON. \"\n"
       "        f\"{EFFORT_HANDS_OFF} \"",
       "        f\"{swapped}Verify Claude is on {fam} with the {tool} tool ON. \"\n"
       "        f\"Open the Effort submenu, choose the tier, and close it. \"")]),
    ("E12", PROMPTS, "the setup system prompt picks an effort again",
     [("{VERSION_ORDER_RULE} {no_upsell} {EFFORT_HANDS_OFF} If the menu will not open",
       "{VERSION_ORDER_RULE} {no_upsell} In that SAME popover, choose \"Max\" in the "
       "Effort submenu. If the menu will not open")]),
    ("E13", MODELS, "the Research-only mission sends the agent into the model menu",
     [("        f\"The model is already correct — do NOT open the model menu. Open the '+' \"",
       "        f\"Open the model menu once and check the model. Open the '+' \"")]),
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
