"""Mutation harness for stretch 6.6 — the backend half.

Two changes, and the dangerous direction is opposite for each.

6.6B removed the P2 platform share step (~1,800 lines). The danger is a removal
that took something with it, or left a name behind: the cuts ran BETWEEN Claude's
markdown extractors, and the `_LINK_VALIDATORS` agent lambdas called the deleted
authority from inside a `validate_link` that is still live for NotebookLM. So the
under-corrections here PUT REMOVED CODE BACK, and the over-corrections take more.

6.6C moved Phase 3's completion onto the podcast. The danger is the opposite: a
gate that is too LOOSE emits a green `phase_complete:3` and a "Podcast ready"
notice for a run whose audio never reached Storage — the exact bug it replaced —
and a gate that is too TIGHT reports a skip for a run that delivered fine.

⛔⛔ THIS HARNESS DOES ITS OWN ANCHOR-UNIQUENESS CHECK, and the other harnesses in
this directory do not. Their driver is `if frm not in mutated: raise` followed by
`replace(frm, to, 1)` — a PRESENCE test and a first-occurrence replace, so an
anchor matching twice silently mutates a place the mutant was never about and
reports a kill. The frontend runner learned this on 2026-08-28 (`permanent: true,`
occurs twice in p5-handlers.ts and was reported as a stale anchor only because
that runner counts). Counting here too.

⛔ AND A SKIP IS NOT A PASS. pytest exits 0 for a run in which tests were skipped
and for a run that collected far fewer tests than it should. This runner reads the
summary line and refuses a verdict rather than guessing — the backend suite learned
that on 2026-08-27, when 68 tests skipped for a missing `node`, pytest exited 0,
and a mutant three tests kill was reported as a survivor.

    .venv/bin/python .mutants/links_out_summary_in_0828_mutants.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_p2_share_removed_0828.py tests/test_p3_audio_gate_0828.py "
          "tests/test_worktab_preflight_899.py tests/test_drift_review_0805.py "
          "tests/test_skip_reporting.py tests/test_phase_notices_0816.py "
          "tests/test_secondaries_prod0805.py tests/test_clipboard_arming_wave5b.py "
          "tests/test_vision_act_wiring.py tests/test_vision_engine.py")

# The smallest passing-test count this harness accepts. A run that collects fewer
# has measured something other than the suite; the verdict is refused, not
# reported. Measured at 291 on 2026-08-28.
FLOOR = 260

MUTANTS = [
    # ══ P — Phase 3 completes on the podcast ═══════════════════════════════

    ("P1", "over",
     "⛔⛔ THE GATE GOES BACK TO THE FOUR SKIP FLAGS. A run whose audio never "
     "reached Storage emits a green phase_complete:3, and the FE fires "
     "'Podcast ready' for a podcast that is not there",
     [("            if _p3_no_skip and _p3_audio_stored:",
       "            if _p3_no_skip:")]),

    ("P2", "over",
     "⛔⛔ THE GATE ACCEPTS THE LOCAL FILE. `audio_path` proves only that a file "
     "is on the research computer — on the Playwright-download path it is set "
     "from `download.save_as()` with no size, format or settle check — while "
     "FE-P4 reads `links.audio_file` and would skip the video anyway",
     [("            if _p3_no_skip and _p3_audio_stored:",
       "            if _p3_no_skip and (_p3_audio_stored or audio_path):")]),

    ("P3", "under",
     "⛔ the artefact alone decides, so a user's Skip is overridden and the run "
     "emits BOTH phase_skipped:3 and phase_complete:3 — a double terminal event "
     "that flips the tile from greyed-skipped back to green",
     [("            if _p3_no_skip and _p3_audio_stored:",
       "            if _p3_audio_stored:")]),

    ("P4", "under",
     "⛔ the no-podcast branch goes silent. Phase 3 emits no terminal event at "
     "all, the tile spins and the FE waits — worse than the bug",
     [('                emit_event("phase_skipped", phase=3, reason=_p3_audio_reason,',
       '                _ = ("phase_skipped", phase, 3, _p3_audio_reason) if False else None\n'
       '                _suppressed = lambda *a, **k: None\n'
       '                _suppressed("phase_skipped", phase=3, reason=_p3_audio_reason,')]),

    ("P5", "under",
     "⛔ the skip stops distinguishing the two failures, so a user whose podcast "
     "is sitting on the research computer is told only that the phase did not "
     "finish",
     [('                _p3_audio_reason = (\n'
       '                    "audio_generated_but_upload_failed" if audio_path\n'
       '                    else "no_audio_generated")',
       '                _p3_audio_reason = "no_audio_generated"')]),

    ("P6", "over",
     "⛔ the Storage URL is set from the local path, so the gate is satisfied by "
     "a file that never uploaded — the same lie with a new name",
     [("                audio_stored_url = audio_url",
       "                audio_stored_url = str(audio_path)")]),

    ("P7", "under",
     "⛔ the assignment leaves the `if audio_url:` guard, so a failed upload "
     "still sets the artefact",
     [("            if audio_url:\n"
       "                update_link_in_firestore(\"audio_file\", audio_url,",
       "            audio_stored_url = audio_url or \"\"\n"
       "            if audio_url:\n"
       "                update_link_in_firestore(\"audio_file\", audio_url,")]),

    ("P8", "under",
     "⛔ the function stops returning the artefact, so the gate reads \"\" on every "
     "run and every phase 3 reports a skip",
     [('    return {"audio_path": audio_path, "audio_stored_url": audio_stored_url}',
       '    return {"audio_path": audio_path}')]),

    ("P9", "under",
     "⛔ the initialisation goes, so any of the eight early returns raises "
     "UnboundLocalError instead of reporting no audio",
     [('    audio_stored_url = ""\n\n    # ── The audio SHARE page: REMOVED',
       "    # ── The audio SHARE page: REMOVED")]),

    ("P10", "under",
     "⛔⛔ THE AUTO-RETRY LEG READS THE REMOVED KEY AGAIN. `.get(…, \"\")` on a "
     "key the function no longer returns is permanently falsy, so the recovery "
     "leg silently stops recording anything about the podcast it just recovered",
     [('                    _p3_audio_stored = _p3_audio.get("audio_stored_url", "")',
       '                    _p3_audio_stored = _p3_audio.get("audio_overview_url", "")')]),

    ("P11", "under",
     "⛔ delivery.json's audio reference goes back to the removed share page, so "
     "P5's report and email point at a NotebookLM page instead of the podcast",
     [("update_delivery(audio_url=_p3_audio_stored or audio_overview_url or notebook_url)",
       "update_delivery(audio_url=audio_overview_url or notebook_url)")]),

    ("P12", "under",
     "⛔⛔ THE CARD BLAMES THE LINK AGAIN. The gate fires when the tab is not on "
     "a /notebook/{id} page — the UPLOAD did not land — and its own retry re-runs "
     "run_phase3_upload for exactly that reason",
     [('                            error="Couldn\'t open the NotebookLM notebook",',
       '                            error="Couldn\'t get the NotebookLM link",')]),

    ("P13", "under",
     "⛔ the notebook URL stops gating the audio STEP, so run_phase3_audio is "
     "entered with nothing to navigate to and every run produces no podcast",
     [("            if notebook_url:\n                while True:  # timeout-retry loop",
       "            if True:\n                while True:  # timeout-retry loop")]),

    ("P14", "under",
     "⛔ the four skip flags leave the gate, so a login Skip or a Stop still "
     "reports a completed phase 3",
     [("            _p3_no_skip = (not _p3_audio_user_skipped and not _p3_login_skipped\n"
       "                           and not _p3_link_skipped\n"
       "                           and not _p3a_user_skipped\n"
       "                           and not _controls.is_stop())",
       "            _p3_no_skip = not _controls.is_stop()")]),

    # ══ R — the removal, put back ══════════════════════════════════════════

    ("R1", "under",
     "⛔⛔ THE REMOVED AUTHORITY COMES BACK. A second copy of the share predicate "
     "is the duplicated-predicate shape that cost a production run on 2026-08-05, "
     "and the guard that says it is gone must notice",
     [("_LINK_VALIDATORS = {",
       'def _is_public_share_url(platform: str, url: str) -> bool:\n'
       '    return "/share/" in url\n\n\n'
       "_LINK_VALIDATORS = {")]),

    ("R2", "under",
     "⛔⛔ THE THREE AGENT LAMBDAS COME BACK, calling a name that no longer "
     "exists — a NameError the first time anything validates a chatgpt URL, "
     "inside a validate_link that is still live for NotebookLM",
     [('_LINK_VALIDATORS = {\n    "notebooklm": is_notebooklm_url,',
       '_LINK_VALIDATORS = {\n'
       '    "chatgpt": lambda u: _is_public_share_url("chatgpt", u),\n'
       '    "notebooklm": is_notebooklm_url,')]),

    ("R3", "under",
     "⛔ a removed hotspot comes back in the vision hint table — a row that can "
     "never fire and an id a reader will hunt for",
     [('_HOTSPOT_VISION_HINTS = {',
       '_HOTSPOT_VISION_HINTS = {\n'
       '    "p2-share": {\n'
       '        "expected_outcome": "a public share URL is produced",\n'
       '        "context_hint": "Get the report\'s public share link.",\n'
       '        "success_signals": ["a share modal"],\n'
       '    },')]),

    ("R4", "under",
     "⛔ the removed op comes back in the tier-transition table, so telemetry "
     "carries an op nothing emits",
     [('_HOTSPOT_TO_OP = {',
       '_HOTSPOT_TO_OP = {\n    "p2-share": "p2_share_extract",')]),

    ("R5", "under",
     "⛔⛔ THE STALE DOCSTRING COMES BACK — the line that claimed the removal for "
     "four months while three extractors ran directly beneath it, and that an "
     "auditor read as proof the work was done",
     [("    ⛔ 2026-08-28 (stretch 6.6B): share-link extraction is NOW genuinely removed",
       "    Share-link extraction is REMOVED from P2 entirely — Phase 5's\n"
       "    Google Doc creation uses Phase 3's link extraction instead.\n"
       "    ⛔ 2026-08-28 (stretch 6.6B): share-link extraction is NOW genuinely removed")]),

    ("R6", "under",
     "⛔⛔ THE P2→P3 HANDOFF STOPS READING A URL. links.json goes empty on every "
     "run, and the resume-from-Phase-3 rung reads its existence — the one silent, "
     "hours-later failure in the whole wave",
     [('        _url = _r.get("url") or ""', '        _url = ""')]),

    ("R7", "under",
     "⛔ the handoff stops dropping an off-topic leg's link, so the 11:08 run's "
     "unrelated conversation ships to NotebookLM as a source again",
     [('        if _url and _r.get("off_topic_rejected"):', "        if False:")]),

    ("R8", "under",
     "⛔ the handoff stops dropping a conversation that predates the run",
     [('        if _url and normalize_agent_key(_name) == "chatgpt" and _chatgpt_tab_is_foreign(_url):',
       "        if False:")]),

    ("R9", "over",
     "⛔ the removal goes further and takes the notebook link's recovery loop, "
     "so a notebook whose URL needs re-reading never gets one",
     [("                    nb_res = await extract_with_retry(",
       "                    nb_res = None and await extract_with_retry(")]),

    ("R10", "under",
     "⛔ the audio SHARE extraction comes back — CUA calls spent re-deriving the "
     "notebook URL we already hold, and `links.audio` written again",
     [('    # ── The audio SHARE page: REMOVED 2026-08-28 (stretch 6.6C) ──',
       '    if audio_done:\n'
       '        emit_validated_link(3, "notebooklm", notebook_url, "Audio Overview", link_kind="audio")\n'
       '    # ── The audio SHARE page: REMOVED 2026-08-28 (stretch 6.6C) ──')]),

    ("R11", "under",
     "⛔ the audio DOWNLOAD leg goes with the share leg — the step that produces "
     "the file the phase now completes on",
     [('                _dl_pick = await _nlm_menu_pick(browser.page, want=("download",))',
       '                _dl_pick = {"clicked": False}')]),

    ("R12", "under",
     "⛔ the destructive-row deny list stops defaulting on, and 'Delete' sits two "
     "rows below 'Download' in that menu",
     [("async def _nlm_menu_pick(page, want, deny=_NLM_MENU_DENY) -> dict:",
       "async def _nlm_menu_pick(page, want, deny=()) -> dict:")]),

    # ⛔⛔ 2026-09-02, stretch 7.5 step 5 — R13'S REASON WAS FALSE AND ITS TARGET
    # HAS MOVED. It said removing this write would make "the delivered doc lose
    # the one platform link"; measured, the Doc builder declares `brief_url` and
    # never reads it, and the video description refuses `links.brief` by name. And
    # the value it wrote was the raw ChatGPT conversation address, past this
    # module's own deny list — step 5 replaced it with the brief's page in our own
    # app, moved into `_record_brief_in_aggregate`, and made all three brief
    # branches use it. What the slot buys is that the record says WHERE THE BRIEF
    # IS; that is what this mutant now takes away.
    ("R13", "under",
     "⛔ the brief slot is written under a key nothing reads, so the research "
     "record stops saying where the brief is — and the guard that pins which kinds "
     "this module may write no longer sees a brief write at all",
     [('        update_link_in_firestore("brief", url, label="Research Brief",',
       '        update_link_in_firestore("brief_disabled", url, label="Research Brief",')]),
]

TESTS_LINE = re.compile(r"^(\d+) (passed|failed)", re.M)


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> tuple[bool, str | None]:
    """(green, refuse). `refuse` non-None means the run cannot be scored at all —
    the caller must treat it as an ERROR, never as a kill and never as a survivor."""
    proc = sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q", "--no-header"])
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    passed = re.search(r"(\d+) passed", tail)
    failed = re.search(r"(\d+) failed", tail)
    errors = re.search(r"(\d+) error", tail)
    skipped = re.search(r"(\d+) skipped", tail)
    if not passed and not failed:
        return False, f"pytest printed no counts — the run did not happen: {tail!r}"
    if skipped:
        return False, f"{skipped.group(1)} test(s) SKIPPED — a skip is the absence of a measurement"
    n = int(passed.group(1) if passed else 0) + int(failed.group(1) if failed else 0)
    if n < FLOOR:
        return False, (f"only {n} tests collected, expected at least {FLOOR}"
                       " — the run measured something other than this suite")
    green = proc.returncode == 0 and not failed and not errors
    return green, None


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    green, refuse = run_tests()
    if refuse:
        print(f"REFUSED: {refuse}")
        return 2
    if not green:
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
                # ⛔⛔ UNIQUENESS, NOT PRESENCE. An anchor matching twice mutates
                # a place the mutant was never about, silently, and reports a kill.
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                if frm == to:
                    raise AssertionError(f"replacement equals the anchor: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed, refuse = run_tests()
            if refuse:
                raise AssertionError(f"verdict refused — {refuse}")
            killed = not killed
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, f"STALE ANCHOR — measured nothing ({exc})"))
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
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
