"""Mutation harness — wave 13, the platform lane's small items before the publish.

⛔⛔ WHAT THIS CODE DECIDES (one letter per item).
  G — a Gemini that started AND finished its research on its own inside the
      plan wait is handed to the round-robin: no "couldn't start" card, no
      vision re-drafts.
  A — agent_loop's call to Claude runs off the event loop.
  T — the rows under ChatGPT's "Thinking ▾" reach Phase 1's live activity feed.
  U — a brief that is on ChatGPT's page but could not be read gets its own card,
      and Retry re-reads it (never a new brief); a short reply keeps the old card.
  L — Claude's usage-limit card keeps the reset time: the first limit line with
      a date wins, and later checks keep reading while no date is known.
  C — the Copy backup compares the WHOLE copy against the latest reply, and a
      follow-up ChatGPT never answered is passed over (no reply marker).
  P — a resumed podcast signs in to NotebookLM before trusting the notebook it
      recorded, and the sign-in brings the tab back to that notebook.

⛔ EACH MUTANT RUNS ONLY ITS OWN TESTS (the fifth column), so a run costs
minutes, not the whole of each file. Every test is behaviour: real headless
Chrome on local pages (T, U, C, G, L), the real run_pipeline (U, P), the real
agent_loop (A). NO SOURCE PIN.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/platform_w13low_mutants.py
  .venv/bin/python .mutants/platform_w13low_mutants.py G1 C2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

GEMINI = ["tests/test_gemini_finished_on_its_own_w13.py"]
OFFLOOP = ["tests/test_cua_off_loop_w13.py"]
STEPS = ["tests/test_chatgpt_thinking_list_0929.py::"
         "test_the_listed_steps_reach_the_live_activity_feed"]
CARD = ["tests/test_p1_unread_brief_card_w13.py"]
REREAD = ["tests/test_chatgpt_long_brief_w13.py::"
          "test_live_phase1_a_brief_on_the_page_that_cannot_be_read_is_read_again"]
SHORT = ["tests/test_chatgpt_copy_fallback_w13.py::"
         "test_live_p1_a_short_reply_is_never_taken_as_the_brief"]
LIMIT = ["tests/test_claude_usage_limit_0916.py"]
SAME_OPENING = ["tests/test_chatgpt_copy_fallback_w13.py::"
                "test_live_p1_after_a_follow_up_a_first_draft_that_opens_the_same_is_refused"]
UNANSWERED = ["tests/test_chatgpt_copy_fallback_w13.py::"
              "test_live_p1_with_no_reply_marker_a_follow_up_with_no_reply_keeps_the_brief"]
PODCAST = ["tests/test_p3_resume_reuses_notebook_w13.py"]

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ G — Gemini finished on its own ═════════════════════════════════════
    ("G1", RESEARCH, "⛔⛔ the plan wait never looks for a finished report — five "
     "minutes later \"Gemini couldn't start\" and three vision re-drafts",
     [("            if await _gemini_finished_on_its_own(gemini_page):\n"
       "                _finished_handoff = True",
       "            if False:\n"
       "                _finished_handoff = True")], GEMINI),

    # ═══ A — off the event loop ═════════════════════════════════════════════
    ("A1", RESEARCH, "⛔⛔ the call to Claude blocks the event loop again — the online "
     "signal, Stop and every command wait up to ~24 s a turn",
     [("                    response = await asyncio.to_thread(\n"
       "                        client.beta.messages.create,\n",
       "                    response = (lambda f, **kw: f(**kw))(\n"
       "                        client.beta.messages.create,\n")], OFFLOOP),

    # ═══ T — ChatGPT's listed steps ═════════════════════════════════════════
    ("T1", RESEARCH, "the rows under \"Thinking ▾\" never reach the feed — only the "
     "status word does",
     [("            if _sl and _sl.get(\"open\") and _rows:",
       "            if False:")], STEPS),

    # ═══ U — a brief on the page that could not be read ═════════════════════
    ("U1", RESEARCH, "⛔ run_phase1 never says the reply is there — the card blames "
     "the sign-in and Retry asks for a new brief",
     [("        if shown > _CG_COPY_MIN_CHARS:\n",
       "        if False:\n")], REREAD),
    ("U2", RESEARCH, "OVER-REACH: any empty read is \"written but could not be read\" — "
     "a clarifying question too",
     [("        if shown > _CG_COPY_MIN_CHARS:\n",
       "        if True:\n")], SHORT),
    ("U3", RESEARCH, "⛔ the card still says \"No brief was generated — check the "
     "sign-in\" for a brief that is on the page",
     [("                    elif p1 and p1.get(\"reread\"):",
       "                    elif False:")], CARD),
    ("U4", RESEARCH, "⛔ Retry on the new card asks ChatGPT for a whole new brief "
     "instead of reading the one on the page",
     [("                                lambda: (_p1_reread() if _p1_reread else",
       "                                lambda: (_p1_reread() if False else")], CARD),

    # ═══ L — Claude's reset time ════════════════════════════════════════════
    ("L1", RESEARCH, "the first limit line is kept even without a date — a dialog "
     "above the banner costs the card its reset time",
     [("        if resets:\n            return {\"line\": ln[:160], \"resets\": resets}",
       "        if True:\n            return {\"line\": ln[:160], \"resets\": resets}")],
     LIMIT),
    ("L2", RESEARCH, "the first read is kept for good — a reset time shown on a later "
     "check is never read",
     [("    if page is None or (note and note.get(\"resets\")):",
       "    if page is None or note:")], LIMIT),

    # ═══ C — the Copy backup ════════════════════════════════════════════════
    ("C1", RESEARCH, "⛔⛔ only the first three lines are compared — after a follow-up "
     "a first draft that opens the same is taken, and the added context is lost",
     [("    hits = sum(p in shown for p in probes)",
       "    probes = probes[:3]; hits = sum(p in shown for p in probes)")], SAME_OPENING),
    ("C2", RESEARCH, "⛔ a follow-up with no reply is never passed over — with no reply "
     "marker the original brief the log says is used is lost",
     [("            if submitted_fu:\n                _p1_unanswered = 1",
       "            if False:\n                _p1_unanswered = 1")], UNANSWERED),
    ("C3", RESEARCH, "the Copy button finder ignores the unanswered follow-up — no "
     "Copy row after it, so no brief",
     [("    const mine = users.length > k ? users[users.length - 1 - k] : null;",
       "    const mine = users.length ? users[users.length - 1] : null;")], UNANSWERED),
    ("C4", RESEARCH, "the on-page check ignores the unanswered follow-up — the original "
     "brief's copy is refused as \"not the latest reply\"",
     [("            users.length > k ? (users[users.length - 1 - k].innerText || '') "
       ": null];\n}\"\"\")\n\n\ndef _cg_letters",
       "            users.length ? (users[users.length - 1].innerText || '') "
       ": null];\n}\"\"\")\n\n\ndef _cg_letters")], UNANSWERED),

    # ═══ P — the podcast resume signs in first ══════════════════════════════
    ("P1", RESEARCH, "⛔⛔ a sign-in page is trusted as \"carry on\" — a notebook deleted "
     "while Chrome was down gets the podcast step",
     [("    if await _work_tab_signed_out(page, \"notebooklm\", \"NotebookLM\"):\n"
       "        log(\"Phase 3: NotebookLM is asking to sign in — waiting for the sign-in \"",
       "    if await _work_tab_signed_out(page, \"notebooklm\", \"NotebookLM\"):\n"
       "        return True\n"
       "        log(\"Phase 3: NotebookLM is asking to sign in — waiting for the sign-in \"")],
     PODCAST),
    ("P2", RESEARCH, "the sign-in brings the tab to NotebookLM's home, not the notebook "
     "— a notebook that is still there reads as gone and a second one is made",
     [("                                                work_url=notebook_url)",
       "                                                work_url=\"https://notebooklm.google.com\")")],
     PODCAST),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider", "-rs"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S, stdin=subprocess.DEVNULL)
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
    # ⛔ The baseline is every test the selected mutants will run, green and
    # with nothing skipped — a skipped Chrome test would make every kill below
    # mean nothing.
    base_tests = sorted({t for m in selected for t in m[4]})
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, base_tests)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — the real-Chrome tests did not run here, so "
              "no kill below would mean anything.\n" + out[-1500:])
        sys.exit(2)
    print("green\n")

    survivors = []
    for mid, fname, why, edits, tests in selected:
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
            ok, _out = green(ROOT, tests)
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
