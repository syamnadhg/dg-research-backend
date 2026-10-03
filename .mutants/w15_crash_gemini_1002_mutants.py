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
  E*  a report read that fails because the browser closed is a crash, not a
      card, for EVERY agent — Claude's and Gemini's too, not only ChatGPT's.
  G*  Gemini's plan wait: ten minutes, not six; never reloaded; nothing on an
      unproven tab believed or pressed; handed on with the late-Start watch
      armed on the run's own chat only; while the watch is armed the round-robin
      runs no stuck check and no computer-use completion look. After a person's
      Retry the same (G7-G15): no computer use, no planning card, an unstarted
      Gemini handed back watched — only when its brief went in — and no
      "Gemini recovered" notice unless a card is up to take down.
  P*  the podcast: the catch is armed around the page's own Download, lets
      thumbnails through, answers 204 (never an abort's error page), closes a
      tab the press opened; the fetch's refusals, size and content checks; the
      fallback presses Download again; the fetched file is what the step
      returns.
  L*  the done check counts only a drawn document; a 2xx that is not the
      route's JSON is a cut; the flip is a read plus a guarded update, read
      again on a race.

  ── review 10-02 (the repair batch) ──
  R*  a crash or a move carries the chat ChatGPT's and Claude's brief went into,
      never one their tab wandered to (only Gemini follows its tab, and a note
      that is not a chat gives way to the tab's chat); a ChatGPT chat dated
      older than the run is never carried, and the log says so; any worker of
      this computer takes a moved run's chats (M6/M7, "only the worker it left",
      went with that decision).
  K12+ an automatic skip drops the card stamp (both finalizers); a crash after
      Phase 2 forgets this research's stamps, and only this research's.
  G16+ auto-skip off: one ask at the 90-minute ceiling for a Gemini whose
      research has not started; a failed plan is one honest card, parked as a
      mid-run error (a fresh chat on Retry, "couldn't start" when unanswered),
      never read as a report or salvaged; only a settled failed turn counts.
  P10+ the player's own stream is let through; the no-address line is said.

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
    "every": (_T + "every_agent_crash_1002" + ".py",),
    "rejoin": ("tests/test_crash_rejoin_1001" + ".py", _T + "move_rejoin_1002" + ".py"),
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
    # M6/M7 ("only the worker it was moved off") were removed with that rule in
    # the review repair of 10-02 — see R6.
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
    # ── G7-G15: after a person's Retry, Gemini just waits too ───────────────
    ("G7", RESEARCH, "gemini", "⛔⛔ a Gemini the Retry handed back unstarted is not watched — its late Start is never pressed, and the stuck check looks at its plan",
     [("                \"gemini_watch_start\": _agent_name == \"Gemini\" and verified_h is None,\n",
       "                \"gemini_watch_start\": False,\n")]),
    ("G8", RESEARCH, "gemini", "⛔⛔ a Retry whose brief did not go in is watched — the watch presses on a tab that is not provably the run's",
     [("                \"gemini_watch_start\": _agent_name == \"Gemini\" and verified_h is None,\n",
       "                \"gemini_watch_start\": _agent_name == \"Gemini\" and not verified_h,\n")]),
    ("G9", RESEARCH, "gemini", "⛔⛔ the planning card is back after a person's Retry (\"Gemini couldn't start Deep Research\")",
     [("        return (new_page, None)\n",
       "        fail_agent(\"gemini\", *_GEMINI_CANT_START)\n        return (new_page, None)\n")]),
    ("G10", RESEARCH, "gemini", "⛔⛔ computer use is pointed at the plan again after a person's Retry",
     [("        return (new_page, None)\n",
       "        await agent_loop(cua_client, browser, PROMPT_DIAGNOSE, \"Start research\",\n"
       "                         model=CUA_MODEL, max_iterations=10, verbose=verbose)\n"
       "        return (new_page, None)\n")]),
    ("G11", RESEARCH, "gemini", "⛔ an unstarted Gemini is handed back as researching — no watch, the stuck check and computer use look at its plan",
     [("        return (new_page, None)\n", "        return (new_page, True)\n")]),
    ("G12", RESEARCH, "gemini", "⛔⛔ a Start confirmed a leg late puts up \"Gemini recovered\" with no card to take down",
     [("                        if _AGENT_ERROR_CARD_TS.get(\"gemini\"):\n",
       "                        if True:\n")]),
    ("G13", RESEARCH, "gemini", "⛔ the card's stamp outlives its retraction — a later completion 'retracts' it again",
     [("                                _clear_pending_decision(\"gemini\")\n"
       "                                _AGENT_ERROR_CARD_TS.pop(\"gemini\", None)\n",
       "                                _clear_pending_decision(\"gemini\")\n")]),
    ("G14", RESEARCH, "gemini", "⛔ a Start the Retry pressed and saw take is never believed — a running research is watched for a Start",
     [("                if await verify_gemini_generating(new_page):\n                    return (new_page, True)\n",
       "                if await verify_gemini_generating(new_page):\n                    return (new_page, None)\n")]),
    ("G15", RESEARCH, "gemini", "the log never says the Retry's Gemini is waiting for its own start",
     [("            elif verified_h is None:\n", "            elif False:\n")]),

    # ── E: a dead browser is a crash, not a card, for every agent ──────────
    ("E1", RESEARCH, "every", "⛔⛔ only ChatGPT's empty read asks the browser — Claude's and Gemini's crash gets a card",
     [("    if await _browser_context_is_dead(browser):\n"
       "        log(f\"[{name}] the whole browser is gone, not just this tab — no card; \"",
       "    if name == \"ChatGPT\" and await _browser_context_is_dead(browser):\n"
       "        log(f\"[{name}] the whole browser is gone, not just this tab — no card; \"")]),
    ("E2", RESEARCH, "every", "⛔ Claude and Gemini are shown \"failed\" and saved \"errored\" for a crash the run retries silently",
     [("    elif n_chars <= 0 and await _browser_context_is_dead(browser):\n",
       "    elif name == \"ChatGPT\" and n_chars <= 0 and await _browser_context_is_dead(browser):\n")]),

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

    # ══ review 10-02 ══════════════════════════════════════════════════════
    # ── R: only this run's chats are carried ────────────────────────────────
    ("R1", RESEARCH, "rejoin", "⛔⛔ ChatGPT and Claude follow a tab that wandered to an older chat — its report is collected as this run's",
     [("            pick = live if (_p2_chat_id(k, live) and not _p2_chat_id(k, u)) else u\n",
       "            pick = live if _p2_chat_id(k, live) else u\n")]),
    ("R2", RESEARCH, "rejoin", "⛔ a note that is not a chat never gives way to the tab's own chat",
     [("            pick = live if (_p2_chat_id(k, live) and not _p2_chat_id(k, u)) else u\n",
       "            pick = u\n")]),
    ("R3", RESEARCH, "rejoin", "⛔⛔ a ChatGPT chat older than the run is carried",
     [("        if k == \"chatgpt\" and _chatgpt_tab_is_foreign(pick):\n",
       "        if False:\n")]),
    ("R4", RESEARCH, "rejoin", "⛔⛔ every agent follows its tab, not only Gemini",
     [("        if k == \"gemini\":\n            pick = live",
       "        if True:\n            pick = live")]),
    ("R5", RESEARCH, "rejoin", "the log never says why ChatGPT starts again",
     [("            log(\"[resume] ChatGPT: the chat it was on is older than this run — \"\n"
       "                \"not going back into it\", \"WARN\")\n",
       "            pass\n")]),
    ("R6", RESEARCH, "move", "⛔⛔ only the worker it was moved off takes the chats — the worker that does take it sends every brief again",
     [("    rid = str((rec or {}).get(\"research_id\") or \"\")\n"
       "    log(f\"[moved-run] {rid[:8]}… comes back to worker {worker_id} (it was moved off \"",
       "    rid = str((rec or {}).get(\"research_id\") or \"\")\n"
       "    if came_from != worker_id:\n        return {}\n"
       "    log(f\"[moved-run] {rid[:8]}… comes back to worker {worker_id} (it was moved off \"")]),

    # ── K12+: a card that is gone is never taken down again ─────────────────
    ("K12", RESEARCH, "cards", "⛔⛔ the unanswered-card / time-limit auto-skip keeps the stamp — a later crash says the skipped agent 'is going again'",
     [("               auto_clear_on_resume=True)\n    _drop_agent_card_stamp(key)\n",
       "               auto_clear_on_resume=True)\n")]),
    ("K13", RESEARCH, "cards", "⛔ the verification-wall auto-skip keeps the stamp",
     [("    _drop_agent_card_stamp(agent_key)\n    _clear_pending_decision()\n",
       "    _clear_pending_decision()\n")]),
    ("K14", RESEARCH, "cards", "⛔⛔ a crash after Phase 2 keeps its cards' stamps — the retry takes down a card that is long gone",
     [("        elif _captured_failure_kind == \"browser_crash\":\n            # Review 10-02",
       "        elif False:\n            # Review 10-02")]),
    ("K15", RESEARCH, "cards", "⛔ a crash forgets ANOTHER research's cards",
     [("        if card_rid == rid:\n            _drop_agent_card_stamp(agent_key)\n",
       "        if True:\n            _drop_agent_card_stamp(agent_key)\n")]),

    # ── G16+: what still reaches the person ─────────────────────────────────
    ("G16", RESEARCH, "gemini", "⛔⛔ auto-skip off: a Gemini that never starts waits for ever, nothing asked",
     [("            if (_hit_hard_cap and name == \"Gemini\" and p.get(\"gemini_watch_start\")\n"
       "                    and not p.get(\"hard_cap_asked\")):\n",
       "            if False:\n")]),
    ("G17", RESEARCH, "gemini", "⛔ the ask goes up on every tick past the ceiling",
     [("            if (_hit_hard_cap and name == \"Gemini\" and p.get(\"gemini_watch_start\")\n"
       "                    and not p.get(\"hard_cap_asked\")):\n",
       "            if (_hit_hard_cap and name == \"Gemini\" and p.get(\"gemini_watch_start\")):\n")]),
    ("G18", RESEARCH, "gemini", "⛔ a Gemini whose research started is asked too — its own checks already run",
     [("            if (_hit_hard_cap and name == \"Gemini\" and p.get(\"gemini_watch_start\")\n"
       "                    and not p.get(\"hard_cap_asked\")):\n",
       "            if (_hit_hard_cap and name == \"Gemini\"\n"
       "                    and not p.get(\"hard_cap_asked\")):\n")]),
    ("G19", RESEARCH, "gemini", "⛔⛔ a failed plan is read as a finished report — computer use and 'Couldn't read Gemini's report' every ten minutes",
     # 10-03: the watch now asks `_gemini_plan_redo_tick` (Redo first, card after).
     [("                _redo, _ws_failed = await _gemini_plan_redo_tick(p[\"page\"], p, name)\n",
       "                _redo, _ws_failed = \"not_failed\", \"\"\n")]),
    ("G20", RESEARCH, "gemini", "⛔⛔ the failed plan is not parked — a card on every leg",
     [("                    p[\"awaiting_decision\"] = {\"kind\": \"agent_error\", \"key\": \"gemini\",\n"
       "                                              \"since\": time.time(), \"timeout\": _pf_window}\n"
       "                    continue\n",
       "                    continue\n")]),
    ("G21", RESEARCH, "gemini", "⛔⛔ after the card the leg goes on into the done check",
     [("                                              \"since\": time.time(), \"timeout\": _pf_window}\n"
       "                    continue\n",
       "                                              \"since\": time.time(), \"timeout\": _pf_window}\n")]),
    ("G22", RESEARCH, "gemini", "⛔ an unanswered failed-plan card says Gemini 'started fine' and failed partway",
     [("                    results[name] = {\"status\": \"plan_failed\", \"text\": \"\",",
       "                    results[name] = {\"status\": \"agent_error\", \"text\": \"\",")]),
    ("G23", RESEARCH, "gemini", "⛔ the failed-plan card ignores the auto-skip setting",
     [("                    _pf_window = unacted_window_sec(_runtime.auto_skip_stuck)\n",
       "                    _pf_window = unacted_window_sec(True)\n")]),
    ("G24", RESEARCH, "gemini", "⛔ the time limit 'salvages' a failed plan — an extraction on a page that holds nothing",
     [("                            and (results.get(name) or {}).get(\"status\") != \"plan_failed\"):",
       "                            and True):")]),
    ("G25", RESEARCH, "gemini", "⛔⛔ a turn still changing is called failed — a plan that restates a brief about a failure gets a card",
     [("        if not second.get(\"found\") or (_gemini_norm(second.get(\"text\") or \"\")\n"
       "                                       != _gemini_norm(latest)):\n",
       "        if not second.get(\"found\"):\n")]),
    ("G26", RESEARCH, "gemini", "⛔⛔ a failure line above an enabled Start, or under a running research, gets a card",
     [("    return \" \".join(latest.split())[:200] if verdict == \"failed\" else \"\"\n",
       "    return \" \".join(latest.split())[:200]\n")]),
    ("G27", RESEARCH, "gemini", "⛔⛔ a half-read 'done' survives into the park — the person's Retry is swallowed as 'already completed'",
     [("                    void_completion_signals(p)\n"
       "                    p[\"awaiting_decision\"] = {\"kind\": \"agent_error\", \"key\": \"gemini\",\n",
       "                    p[\"awaiting_decision\"] = {\"kind\": \"agent_error\", \"key\": \"gemini\",\n")]),

    # ── P10+: the podcast's two unmeasured lines ────────────────────────────
    ("P10", RESEARCH, "podcast", "⛔ the player's own stream is stopped and its address fetched",
     [("        if kind in (\"image\", \"media\") or self.url:\n",
       "        if kind in (\"image\",) or self.url:\n")]),
    ("P11", RESEARCH, "podcast", "the log never says Chrome downloads it when the Download asked for nothing",
     [("            log(\"[Audio] the page's Download asked for no audio address this run \"\n"
       "                \"knows — Chrome downloads it, as before\", \"WARN\")\n",
       "            pass\n")]),
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
