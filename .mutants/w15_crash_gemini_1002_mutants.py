"""Mutation harness — wave 15 (10-02): crashes and moves rejoin, no false alarms,
the podcast without a Chrome download, Gemini just waits, three lows.

⛔⛔ WHAT THIS CODE DECIDES (research.py) — the lines this wave added or changed.
  M*  a run moved to the queue keeps its Phase-2 chats beside the worker it ran
      on (only in Phase 2 or before, never failing the move); only that worker
      gets them back (never on a value that merely equals it); the worker loop
      hands them to the run.
  K*  a crash's own retry takes down the Phase-2 cards its crashed attempt
      raised for this research: the card's alert id, no buttons, the
      recovered-by-itself flag, the durable decision, the tile — only that
      research's, only Phase 2's, never one already answered; a fresh run takes
      down nothing.
  G*  Gemini's plan wait: ten minutes, not six; never reloaded; nothing on an
      unproven tab believed or pressed; handed on with the late-Start watch
      armed on the run's own chat only; while the watch is armed the round-robin
      runs no stuck check and no computer-use completion look.
  P*  the podcast: the catch is armed around the page's own Download, lets
      thumbnails through, answers 204 (never an abort's error page), closes a
      tab the press opened; the fetch's refusals, size and content checks; the
      fallback presses Download again; the fetched file is what the step
      returns.
  L*  the done check counts only a drawn document; a 2xx that is not the
      route's JSON is a cut; the flip is a read plus a guarded update, read
      again on a race.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/w15_crash_gemini_1002_mutants.py
  .venv/bin/python .mutants/w15_crash_gemini_1002_mutants.py M1 K2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

#: Each group's measuring tests (names, never paths with a ".py" the anchor
#: sweep would read as a target: it reads any "*.py" string in a ROW).
_T = "tests/test_w15_"
SUITES = {
    "move": (_T + "move_rejoin_1002" + ".py",),
    "cards": (_T + "crash_cards_1002" + ".py",),
    "gemini": (_T + "gemini_waits_1002" + ".py", "tests/test_gemini_plan_wait_1001" + ".py"),
    "podcast": (_T + "podcast_fetch_1002" + ".py",),
    "lows": (_T + "lows_1002" + ".py",),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── M: Move to queue keeps the chats ────────────────────────────────────
    ("M1", RESEARCH, "move", "⛔⛔ the marker never keeps the chats — every move starts Phase 2 fresh",
     [("    if p2_chats:\n        rec[\"p2_chats\"] = ",
       "    if False:\n        rec[\"p2_chats\"] = ")]),
    ("M2", RESEARCH, "move", "⛔⛔ the move hands its chats to nothing",
     [("                         p2_chats=_p2_chats_to_move()) is None:",
       "                         p2_chats=None) is None:")]),
    ("M3", RESEARCH, "move", "⛔ a move after Phase 2 keeps chats it can never use",
     [("        if isinstance(phase, int) and phase > 2:\n            return {}\n",
       "        if False:\n            return {}\n")]),
    ("M4", RESEARCH, "move", "⛔⛔ a move IN Phase 2 keeps none — the phase it exists for",
     [("        if isinstance(phase, int) and phase > 2:\n            return {}\n",
       "        if isinstance(phase, int) and phase > 1:\n            return {}\n")]),
    ("M5", RESEARCH, "move", "⛔ a chat record that cannot be read fails the move itself",
     [("        return _p2_chats_to_rejoin()\n    except Exception:\n        return {}\n",
       "        return _p2_chats_to_rejoin()\n    except ZeroDivisionError:\n        return {}\n")]),
    ("M6", RESEARCH, "move", "⛔⛔ any worker takes the chats — another account's Chrome opens them",
     [("    if (isinstance(came_from, int) and not isinstance(came_from, bool)\n"
       "            and came_from == int(worker_id)):",
       "    if (isinstance(came_from, int) and not isinstance(came_from, bool)):")]),
    ("M7", RESEARCH, "move", "⛔ `True` is taken for worker 1",
     [("    if (isinstance(came_from, int) and not isinstance(came_from, bool)\n",
       "    if (isinstance(came_from, int)\n")]),
    ("M8", RESEARCH, "move", "⛔⛔ the claim drops the chats it was right to hand on",
     [("        _chats = _waiting_p2_chats(rec, worker_id)\n        if _chats:\n",
       "        _chats = _waiting_p2_chats(rec, worker_id)\n        if False:\n")]),
    ("M9", RESEARCH, "move", "⛔⛔ the worker loop never passes them into the run",
     [("                                     _p2_rejoin=job.get(\"p2_rejoin\") or None))",
       "                                     _p2_rejoin=None))")]),

    # ── K: the crash's retry takes the crashed attempt's cards down ─────────
    ("K1", RESEARCH, "cards", "⛔⛔ the retry takes no card down — 10-01's fifteen minutes",
     [("        if _crash_retries > 0:\n            _retract_crashed_attempt_cards(",
       "        if False:\n            _retract_crashed_attempt_cards(")]),
    ("K2", RESEARCH, "cards", "⛔ every run takes cards down — a person's own Retry clears live cards",
     [("        if _crash_retries > 0:\n            _retract_crashed_attempt_cards(",
       "        if True:\n            _retract_crashed_attempt_cards(")]),
    ("K3", RESEARCH, "cards", "⛔⛔ another research's card is 'taken down' into this one",
     [("        if card_rid != rid or phase != 2 or agent_key not in _AGENT_ERROR_CARD_TS:",
       "        if phase != 2 or agent_key not in _AGENT_ERROR_CARD_TS:")]),
    ("K4", RESEARCH, "cards", "⛔ a Phase-1 card is 'retracted' — a new notice instead",
     [("        if card_rid != rid or phase != 2 or agent_key not in _AGENT_ERROR_CARD_TS:",
       "        if card_rid != rid or agent_key not in _AGENT_ERROR_CARD_TS:")]),
    ("K5", RESEARCH, "cards", "⛔ a card the person already answered is taken down again",
     [("        if card_rid != rid or phase != 2 or agent_key not in _AGENT_ERROR_CARD_TS:",
       "        if card_rid != rid or phase != 2:")]),
    ("K6", RESEARCH, "cards", "⛔⛔ the durable decision stays — the card comes back on a cold open",
     [("            _clear_pending_decision(agent_key)\n            _write_agent_terminal_status(agent_key, \"running\")",
       "            _write_agent_terminal_status(agent_key, \"running\")")]),
    ("K7", RESEARCH, "cards", "⛔ the tile stays red",
     [("            _clear_pending_decision(agent_key)\n            _write_agent_terminal_status(agent_key, \"running\")",
       "            _clear_pending_decision(agent_key)")]),
    ("K8", RESEARCH, "cards", "⛔ the stamp is kept — a later completion 'retracts' again",
     [("        _AGENT_ERROR_CARD_TS.pop(agent_key, None)\n        _AGENT_ERROR_CARD_OF.pop(agent_key, None)\n        taken.append",
       "        _AGENT_ERROR_CARD_OF.pop(agent_key, None)\n        taken.append")]),
    ("K9", RESEARCH, "cards", "⛔⛔ the card's research is never recorded — nothing can be taken down",
     [("    _AGENT_ERROR_CARD_OF[agent_key] = (str(_fb_research_id or \"\"), _eff_phase)",
       "    pass")]),
    ("K10", RESEARCH, "cards", "⛔⛔ the retraction carries buttons — the app reads it as a new card",
     [("                       actions=[], alert_id=_agent_error_alert_id(agent_key, 2),\n"
       "                       auto_clear_on_resume=True)\n            _clear_pending_decision(agent_key)",
       "                       actions=[\"retry\"], alert_id=_agent_error_alert_id(agent_key, 2),\n"
       "                       auto_clear_on_resume=True)\n            _clear_pending_decision(agent_key)")]),
    ("K11", RESEARCH, "cards", "⛔ the retraction is not flagged recovered — the app leaves the card",
     [("                       actions=[], alert_id=_agent_error_alert_id(agent_key, 2),\n"
       "                       auto_clear_on_resume=True)\n            _clear_pending_decision(agent_key)",
       "                       actions=[], alert_id=_agent_error_alert_id(agent_key, 2),\n"
       "                       auto_clear_on_resume=False)\n            _clear_pending_decision(agent_key)")]),

    # ── G: Gemini just waits ────────────────────────────────────────────────
    ("G1", RESEARCH, "gemini", "⛔⛔ the six-minute hand-off is back (10-01's plan took 47)",
     [("            if _elapsed >= _start_wait_max_sec:\n                log(f\"[2D] No 'Start research' to press",
       "            if _elapsed >= 360:\n                log(f\"[2D] No 'Start research' to press")]),
    ("G2", RESEARCH, "gemini", "⛔⛔ the watch presses on a tab that is not the run's own chat",
     [("                                     and not _controls.is_stop() and _chat_ok)",
       "                                     and not _controls.is_stop())")]),
    ("G3", RESEARCH, "gemini", "⛔⛔ the wait that ended with nothing pressed arms no watch — a late Start is never pressed",
     [("                                    (not start_clicked and not _finished_handoff\n",
       "                                    (False and not _finished_handoff\n")]),
    ("G4", RESEARCH, "gemini", "⛔⛔ an unproven tab is believed — another chat's Start is pressed",
     [("    else:\n        chat[\"trusted\"] = False\n    return False\n",
       "    else:\n        chat[\"trusted\"] = False\n    return True\n")]),
    ("G5", RESEARCH, "gemini", "⛔⛔ the round-robin's 'seems stuck' check runs on a planning Gemini",
     [("                                 and not status_is_active\n"
       "                                 and not (name == \"Gemini\" and p.get(\"gemini_watch_start\")))",
       "                                 and not status_is_active)")]),
    ("G6", RESEARCH, "gemini", "⛔⛔ computer use looks at a planning Gemini — the door to a Redo, a card and a drop",
     [("            if name == \"Gemini\" and p.get(\"gemini_watch_start\"):\n                continue\n",
       "            if False:\n                continue\n")]),

    # ── P: the podcast without a Chrome download ────────────────────────────
    ("P1", RESEARCH, "podcast", "⛔⛔ the catch is never armed — Chrome downloads the podcast again",
     [("        _catch_on = await _audio_catch.arm()\n", "        _catch_on = False\n")]),
    ("P2", RESEARCH, "podcast", "⛔⛔ the request is aborted — the notebook's tab shows Chrome's error page",
     [("            await route.fulfill(status=204, body=\"\")\n        except Exception:\n            try:\n                await route.abort()",
       "            await route.abort()\n        except Exception:\n            try:\n                await route.abort()")]),
    ("P3", RESEARCH, "podcast", "⛔ a thumbnail on the same host is taken for the audio",
     [("        if kind in (\"image\", \"media\") or self.url:\n",
       "        if self.url:\n")]),
    ("P4", RESEARCH, "podcast", "⛔ the tab the Download opened is left open",
     # Re-anchored after the first run (P4 survived: a new tab's first request
     # has no frame, so the close moved to the context's tabs at disarm).
     [("            if url in (\"\", \"about:blank\") or _NLM_AUDIO_URL_RE.match(url):\n",
       "            if False:\n")]),
    ("P4b", RESEARCH, "podcast", "⛔ one of the run's own tabs, open before the press, is closed",
     [("            if id(tab) in self._tabs_before:\n                continue\n",
       "            if False:\n                continue\n")]),
    ("P5", RESEARCH, "podcast", "⛔ a refused fetch is taken for the audio",
     [("        if not resp.ok:\n            log(f\"[{label}] fetching the audio from its address was refused",
       "        if False:\n            log(f\"[{label}] fetching the audio from its address was refused")]),
    ("P6", RESEARCH, "podcast", "⛔ a page of a few bytes is checked as audio, not refused for its size",
     [("    if len(body) < _NLM_AUDIO_MIN_BYTES:\n", "    if False:\n")]),
    ("P7", RESEARCH, "podcast", "⛔⛔ what is not audio is published as the podcast",
     [("        kind = _audio_kind(tmp, trusted=True)\n        if not kind:\n",
       "        kind = _audio_kind(tmp, trusted=True)\n        if False:\n")]),
    ("P8", RESEARCH, "podcast", "⛔⛔ a failed fetch is never followed by today's download",
     [("                \"pressing Download again, and Chrome downloads it as before\", \"WARN\")\n"
       "                _dl_via_dom = await _dom_press_download()",
       "                \"pressing Download again, and Chrome downloads it as before\", \"WARN\")\n"
       "                _dl_via_dom = False")]),
    ("P9", RESEARCH, "podcast", "⛔⛔ the fetched file is not what the step returns",
     [("            if not download_future.done():\n                download_future.set_result(_fetched)\n",
       "            pass\n")]),

    # ── L: the lows ─────────────────────────────────────────────────────────
    ("L1", RESEARCH, "lows", "⛔⛔ the hidden frame's script is counted as report text again",
     [("             assistantLen, panelLen, bodyLen: drawn ? bl.length : 0, sources, steps, vw, vh,",
       "             assistantLen, panelLen, bodyLen: bl.length, sources, steps, vw, vh,")]),
    ("L2", RESEARCH, "lows", "⛔⛔ any 2xx is 'the route ran it' — the front door's error page included",
     [("        return isinstance(json.loads(body_text or \"\"), dict)\n",
       "        return True\n")]),
    ("L3", RESEARCH, "lows", "⛔ the drive never hands the verdict the body",
     [("                verdict = _dispatch_verdict(status_code=_status, body=_text)\n",
       "                verdict = _dispatch_verdict(status_code=_status)\n")]),
    ("L4", RESEARCH, "lows", "⛔⛔ the flip writes with no precondition — a cancel in between is overwritten",
     [("                    }), option=_firebase_db.write_option(\n"
       "                        last_update_time=snap.update_time))",
       "                    }))")]),
    ("L5", RESEARCH, "lows", "⛔⛔ the flip writes over any status — a cancelled run is set running",
     [("                cur = (snap.to_dict() or {}).get(\"status\")\n                if cur != \"queued\":\n"
       "                    return f\"skipped({cur})\"\n                try:\n                    doc_ref.update(_be_payload({",
       "                cur = (snap.to_dict() or {}).get(\"status\")\n                if False:\n"
       "                    return f\"skipped({cur})\"\n                try:\n                    doc_ref.update(_be_payload({")]),
    ("L6", RESEARCH, "lows", "⛔ a race is not read again — the cancel that won is not seen",
     [("            for _attempt in range(2):\n                outcome = _grpc_write_with_heal(\n                    _flip_once,",
       "            for _attempt in range(1):\n                outcome = _grpc_write_with_heal(\n                    _flip_once,")]),
    ("L7", RESEARCH, "lows", "⛔ two races hand back 'raced', which the caller does not know",
     [("            if outcome == \"raced\":\n                # Written twice under us",
       "            if False:\n                # Written twice under us")]),
]


def green(tests) -> bool:
    try:
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-x",
                            "-p", "no:cacheprovider", *tests],
                           cwd=str(ROOT), env=ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return False
    out = r.stdout + r.stderr
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too, and a
    # skipped test is not a measurement.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


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
    print("baseline… ", end="", flush=True)
    for group in sorted({m[2] for m in MUTANTS}):
        suites = SUITES[group]
        if not green(suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, group, why, edits in selected:
        suites = SUITES[group]
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
            if green(suites):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}", flush=True)
            else:
                print(f"  {mid:4} ✓ killed", flush=True)
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}", flush=True)
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
