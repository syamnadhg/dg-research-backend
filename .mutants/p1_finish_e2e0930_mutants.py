"""Mutation harness — ChatGPT Phase 1 finishes the moment ChatGPT does (09-30 run).

⛔⛔ WHAT THIS CODE DECIDES.
  F1  while the page may be finished (the DOM's last read said "not generating"),
      nothing presses the activity line and no vision step is sent for it;
  F1b …and the same while both finish signs are up but not yet settled;
  F2  the finish — no Stop, "Worked for …" in the latest exchange — ends the
      poll at the top of a cycle, after ONE steady re-read;
  F3  the wait between polls looks for that finish once a second;
  F4a the steady re-read refuses a reply that is still growing;
  F4b …and a page whose own "still working?" check says it is;
  F5  the new page's line (its label drawn twice) is latched open, never pressed;
  F6  …for the rest of the poll, also once it reads "Worked for …";
  F7  a vision step's "already open" is only undone by a DOM that saw it open;
  F8  the brief's poll runs the check that does not scroll the page;
  F9  …and so does the follow-up's;
  F10 …and that check really does not scroll.
  G1  the doubled line is never a box around the reply or the person's message;
  G2  the header is never read inside the reply's text;
  G3  …nor off a box around a short reply;
  G4  …and only in the latest exchange.

⛔ The browser tests need patchright and Chrome; where they SKIP the baseline
is not a measurement, so the runner refuses to score a skipped baseline.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/p1_finish_e2e0930_mutants.py
  .venv/bin/python .mutants/p1_finish_e2e0930_mutants.py F2 F7
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_chatgpt_p1_finish_0930.py",
         "tests/test_chatgpt_long_brief_w13.py::"
         "test_live_phase1s_polls_leave_a_long_brief_where_the_person_scrolled"]
DESELECT = "not nothing_is_deselected_here"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_RUN_TIMEOUT_S = 900

MUTANTS = [
    ("F1", RESEARCH, "⛔⛔ the opener runs while the DOM says not generating — the 05:07:49 "
     "vision step on a finished brief",
     [("                        and not _panel_open_done and not _p1_quiet):",
       "                        and not _panel_open_done):")]),
    ("F1b", RESEARCH, "the finish signs up but unsettled no longer quiet the opener",
     [("            _p1_quiet = bool(_fin[\"done\"]) or consecutive_not_generating >= 1",
       "            _p1_quiet = consecutive_not_generating >= 1")]),
    ("F2", RESEARCH, "⛔⛔ no finish at the top of a cycle — back to the 5 s + 3 s "
     "double-check",
     [("            if _fin[\"done\"] and await _chatgpt_p1_finish_holds(page, verify_fn, _fin):",
       "            if False and await _chatgpt_p1_finish_holds(page, verify_fn, _fin):")]),
    ("F3", RESEARCH, "⛔ the wait between polls is one blind sleep again — the finish is "
     "seen up to a whole poll late",
     [("            await _chatgpt_p1_wait_for_finish(page, poll_interval)",
       "            await asyncio.sleep(poll_interval)")]),
    ("F4a", RESEARCH, "⛔ the steady re-read ignores a growing reply — a half-written "
     "brief is read",
     [("    if not again[\"done\"] or again[\"reply_len\"] != first.get(\"reply_len\"):",
       "    if not again[\"done\"]:")]),
    ("F4b", RESEARCH, "the steady re-read ignores the page's own still-working check",
     [("        return not await verify_fn(page)\n",
       "        return True\n")]),
    ("F5", RESEARCH, "⛔⛔ the new page's line is pressed again — the list flaps shut and "
     "open every poll",
     [("                        elif _line:\n",
       "                        elif False:\n")]),
    ("F6", RESEARCH, "the new page's latch lapses once the line reads \"Worked for\"",
     [("                        and not _panel_by_page_shape):",
       "                        ):")]),
    ("F7", RESEARCH, "⛔⛔ a blind read undoes the vision step's \"already open\" — the "
     "05:05:33 re-open",
     [("                        elif _panel_dom_seen_open:\n"
       "                            _panel_reopens += 1",
       "                        else:\n"
       "                            _panel_reopens += 1")]),
    ("F8", RESEARCH, "⛔ the brief's poll scrolls the page to the bottom every check again",
     [("poll_until_done(browser.page, verify_chatgpt_p1_generating, \"Phase1\", POLL_PRO",
       "poll_until_done(browser.page, verify_chatgpt_generating, \"Phase1\", POLL_PRO")]),
    ("F9", RESEARCH, "the follow-up's poll scrolls the page to the bottom every check",
     [("poll_until_done(browser.page, verify_chatgpt_p1_generating, \"Phase1-followup\",",
       "poll_until_done(browser.page, verify_chatgpt_generating, \"Phase1-followup\",")]),
    ("F10", RESEARCH, "Phase 1's check scrolls after all",
     [("    return await verify_chatgpt_generating(page, scroll=False)",
       "    return await verify_chatgpt_generating(page, scroll=True)")]),
    ("G1", RESEARCH, "a box around a short reply passes for the new page's line",
     [("        if (el.querySelector('__CG_REPLY_TEXT__') || el.querySelector('__CG_USER__')) continue;\n"
       "        const r = el.getBoundingClientRect();",
       "        const r = el.getBoundingClientRect();")]),
    ("G2", RESEARCH, "⛔ \"worked for 5 hours\" in the reply's text passes for the header",
     [("        if (el.closest('__CG_REPLY_TEXT__') || el.closest('__CG_USER__')) continue;\n"
       "        if (el.querySelector('__CG_REPLY_TEXT__') || el.querySelector('__CG_USER__')) continue;\n"
       "        out.header = m[0];",
       "        if (el.querySelector('__CG_REPLY_TEXT__') || el.querySelector('__CG_USER__')) continue;\n"
       "        out.header = m[0];")]),
    ("G3", RESEARCH, "a box around a short reply passes for the header",
     [("        if (el.querySelector('__CG_REPLY_TEXT__') || el.querySelector('__CG_USER__')) continue;\n"
       "        out.header = m[0];",
       "        out.header = m[0];")]),
    ("G4", RESEARCH, "⛔ an earlier exchange's header answers for this one",
     [("    const last = turns.length ? turns[turns.length - 1] : null;\n    if (!last) return out;",
       "    const last = document.body;\n    if (!last) return out;")]),
]


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider",
             "-k", DESELECT, "-rs"],
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
    print("clean.\n")
