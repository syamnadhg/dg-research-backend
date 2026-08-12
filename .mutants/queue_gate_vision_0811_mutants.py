"""Mutation harness for the queue gate's false wait and the truncated vision read.

Two log lines lied on 2026-08-11. One announced a 70-minute wait and ended it in
the same second; the other called an exhausted token budget a parse error and
threw away every source in the panel.

The over-corrections are the ones to fear. The gate is the last thing standing
between a finishing run and the next one starting on top of it, and every
release path in it was root-caused separately after a real hang. A "fix" that
removes the deadline, or reads before checking for a stop, trades a wrong
sentence for a wedged worker. On the vision side the danger is the salvage
letting a HALF-read URL into the report — a truncated link is worse than a
missing one, and the prompt already tells the model the same thing about
truncated text on screen.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/queue_gate_vision_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = "tests/test_queue_gate_and_vision_urls_0811.py"

MUTANTS = [
    # ── the gate's false claims, restored ───────────────────────────────────
    ("G1", "under", "the deadline test goes back above the read — the gate gives up unread",
     [("            now_ms = int(time.time() * 1000)\n            try:",
       "            now_ms = int(time.time() * 1000)\n"
       "            if now_ms >= deadline:\n"
       "                _QUEUE_STATE.pop(\"gate_pending_job\", None)\n"
       "                return\n            try:")]),
    ("G2", "under", "the entry line quotes the constant again instead of what is left",
     [("                f\"(fallback in {int(_gate_left_ms / 1000)}s)\")",
       "                f\"(fallback in {BE_PHASES_TIMEOUT_SEC}s)\")")]),
    ("G3", "under", "an already-expired window is announced as a fresh wait",
     [("        if _gate_left_ms > 0:", "        if True:")]),
    ("G4", "under", "the give-up line asserts what it never checked",
     [('                log(f"[queue-gate] prior run {_prid[:8]}… is "\n'
       '                    f"{int((now_ms - _pdone) / 1000)}s past its backend finish with no "\n'
       '                    f"terminal status seen (FE-P5 window {BE_PHASES_TIMEOUT_SEC}s) — "\n'
       '                    f"force-dequeueing")',
       '                log(f"[queue-gate] FE never reported completed in {BE_PHASES_TIMEOUT_SEC}s — force-dequeueing")')]),

    # ── ⛔ over-corrections: the gate must still let go ──────────────────────
    ("X1", "over", "the deadline is deleted — a stuck prior run wedges the queue forever",
     [("            if now_ms >= deadline:\n"
       '                log(f"[queue-gate] prior run {_prid[:8]}… is "',
       "            if False:\n"
       '                log(f"[queue-gate] prior run {_prid[:8]}… is "')]),
    ("X2", "over", "a failed read skips the deadline test, so the gate spins forever",
     [('                log(f"[queue-gate] Firestore read failed: {e}", "WARN")',
       '                log(f"[queue-gate] Firestore read failed: {e}", "WARN")\n'
       "                await asyncio.sleep(2)\n                continue")]),
    ("X3", "over", "the terminal-status release is gone",
     [('                        log(f"[queue-gate] prior run terminal (status={status}) — dequeueing")\n'
       '                        _QUEUE_STATE.pop("gate_pending_job", None)\n'
       '                        return\n', "")]),
    ("X4", "over", "the deleted-prior-doc release is gone",
     [('                    log(f"[queue-gate] prior run {_prid[:8]}… doc missing — dequeueing")\n'
       '                    _QUEUE_STATE.pop("gate_pending_job", None)\n'
       '                    return\n', "")]),
    ("X5", "over", "the FE-P5-failed fast release is gone",
     [('                    if fe_p5_state == "failed":', "                    if False:")]),
    ("X6", "over", "the 5-minute ghosted-FE self-heal is gone",
     [("                            f\"FE-P5 ghosted, force-dequeueing\"\n"
       "                        )\n"
       '                        _QUEUE_STATE.pop("gate_pending_job", None)\n'
       "                        return\n", "")]),
    ("X7", "over", "the synth-user 403 release is gone — a 2s poll loop spams denials",
     [('                    log("[queue-gate] read denied (synth user) — releasing gate (Track D)", "DEBUG")\n'
       '                    _QUEUE_STATE.pop("gate_pending_job", None)\n'
       "                    return\n", "")]),
    # NOTE the context: `if _controls.is_stop():` occurs dozens of times in this
    # file and the first is ~40k lines above the gate. A bare anchor mutated a
    # completely different function and this mutant "survived" without ever
    # touching the code under test.
    ("X8", "over", "a cancel during the gate wait is ignored again",
     [("                if _controls.is_stop():\n"
       '                    log("[queue-gate] stop requested during gate wait — releasing", "INFO")',
       "                if False:\n"
       '                    log("[queue-gate] stop requested during gate wait — releasing", "INFO")')]),
    ("X9", "over", "the resume-path short-circuit is gone — the gate waits on itself",
     [('        if _current_job and (_current_job.get("research_id") or "") == _prid:',
       "        if False:")]),

    # ── the vision read ─────────────────────────────────────────────────────
    # Re-anchored 2026-08-12: the call site's literal became a named constant when
    # the read timeout was bound to it, so this mutant stopped applying at all —
    # and an anchor that cannot apply is a guard that has silently stopped guarding.
    ("V1", "under", "the token ceiling goes back under narrate's — the truncation returns",
     [('_VISION_URL_MAX_TOKENS = int(os.environ.get("DG_VISION_URL_MAX_TOKENS", "2400"))',
       '_VISION_URL_MAX_TOKENS = int(os.environ.get("DG_VISION_URL_MAX_TOKENS", "800"))')]),
    ("V2", "under", "a truncated response is called a parse error again",
     [('                log(f"[{agent_key}] vision-urls response was not complete JSON "\n'
       '                    f"(finishReason={_finish or \'unset\'}, {len(text)} chars): {_je} — "\n'
       '                    f"salvaged {len(_salvaged)} whole URLs from it", "WARN")',
       '                log(f"[{agent_key}] vision-urls call/parse error: {_je}", "WARN")')]),
    ("V3", "under", "finishReason is never read, so a ceiling looks like a safety stop",
     [('            _finish = _cand.get("finishReason") or ""\n', "            _finish = \"\"\n")]),
    ("V4", "under", "nothing is salvaged — one clipped URL discards the whole panel",
     [("                _salvaged = _salvage_urls_from_truncated_json(text)",
       "                _salvaged = []")]),
    ("V5", "under", "the salvage confidence sits under the gate that admits it",
     [("_VISION_URL_SALVAGE_CONFIDENCE = 0.5", "_VISION_URL_SALVAGE_CONFIDENCE = 0.3")]),

    # ── ⛔ over-corrections: never publish half a URL ────────────────────────
    ("S1", "over", "the closing quote is optional — the clipped last URL comes through",
     [("_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]{4,500})\"')",
       "_VISION_URL_SALVAGE_RE = re.compile(r'\"?(https?://[^\"\\\\\\s]{4,500})')")]),
    ("S2", "over", "the length cap is dropped, so the salvage outruns the parsed path",
     [("_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]{4,500})\"')",
       "_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]+)\"')")]),
    ("S3", "over", "any quoted string counts as a URL",
     [("_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]{4,500})\"')",
       "_VISION_URL_SALVAGE_RE = re.compile(r'\"([^\"]{4,500})\"')")]),
    ("S4", "over", "an empty salvage is still handed a confidence",
     [("                return _salvaged, (_VISION_URL_SALVAGE_CONFIDENCE if _salvaged else 0.0)",
       "                return _salvaged, _VISION_URL_SALVAGE_CONFIDENCE")]),
    ("S5", "over", "the salvage claims the clean-read confidence it never observed",
     [("_VISION_URL_SALVAGE_CONFIDENCE = 0.5", "_VISION_URL_SALVAGE_CONFIDENCE = 0.9")]),
    ("S6", "over", "every exception takes the salvage branch, so a network error reads as truncation",
     [("            except ValueError as _je:", "            except Exception as _je:")]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
