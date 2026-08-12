"""Mutation harness for the three fixes from the 2026-08-11 21:00 run.

All three concern an agent whose page had stopped, and all three are the kind of
change that is invisible when it goes wrong: an arbiter that probes too often
costs money nobody is watching, a timeout that is too short loses sources
silently, and a salvage that skips a tier looks exactly like a salvage that
found nothing. So the over-corrections carry most of the weight here.

The two that could do real damage:

  * Throttling the arbiter into silence, or delaying the card a stuck verdict
    produces. The detector's whole job is the first probe.
  * Dropping the CUA salvage tiers on a leg we are BLIND to rather than one we
    can see has stopped. That is the 2026-04-28 case — 1,289 sources, 0/0 to
    every scraper, report recovered by the download tier and nothing else — and
    getting the predicate backwards would lose exactly those reports.

Safety, learned from an earlier harness on this repo that adopted a mutant as
its own baseline: refuses to start on a dirty tree, holds originals in memory
only, restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/frozen_page_wave_0812_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_arbiter_throttle_0812.py "
          "tests/test_vision_url_budget_0812.py "
          "tests/test_frozen_salvage_0812.py "
          "tests/test_queue_gate_and_vision_urls_0811.py")

MUTANTS = [
    # ══════════════════ fix 1 — the arbiter re-probe throttle ══════════════
    ("A1", "under", "⭐ the entry stamp is gone — the 08-11 storm, restored",
     [('                p["stuck_warned_at"] = time.time()\n'
       '                log(f"[{name}] No observed growth',
       '                log(f"[{name}] No observed growth')]),
    ("A2", "under", "the entry stamp is a no-op that keeps the old value",
     [('                p["stuck_warned_at"] = time.time()\n'
       '                log(f"[{name}] No observed growth',
       '                p["stuck_warned_at"] = p.get("stuck_warned_at", 0.0)\n'
       '                log(f"[{name}] No observed growth')]),
    ("A3", "under", "the entry stamp writes 0.0, so since_warn is always the whole run",
     [('                p["stuck_warned_at"] = time.time()\n'
       '                log(f"[{name}] No observed growth',
       '                p["stuck_warned_at"] = 0.0\n'
       '                log(f"[{name}] No observed growth')]),
    ("A4", "over", "⛔ stamped every tick instead of every probe — the detector goes silent",
     [('            if _active_no_growth:\n',
       '            p["stuck_warned_at"] = time.time()\n            if _active_no_growth:\n')]),
    ("A5", "under", "the throttle clause is dropped from the gate — the stamp buys nothing",
     [("                                 and since_warn > STUCK_WARN_THROTTLE_SEC\n", "")]),
    ("A6", "over", "the warm-up clause is dropped — a young agent gets probed",
     [("                                 and elapsed > STUCK_MIN_ELAPSED_SEC\n", "")]),
    ("A7", "over", "⛔ the planning clause is dropped — the 2026-07-09 false card returns",
     [("                                 and not status_is_active)", ")")]),
    ("A8", "over", "the throttle is a day long — the arbiter never re-probes at all",
     [('STUCK_WARN_THROTTLE_SEC = int(os.environ.get("DG_STUCK_WARN_THROTTLE_SEC", "600"))',
       'STUCK_WARN_THROTTLE_SEC = int(os.environ.get("DG_STUCK_WARN_THROTTLE_SEC", "86400"))')]),
    ("A9", "over", "⛔ a confirmed-stuck verdict no longer raises the card",
     [("                    fail_agent(agent_key_stuck,\n", "                    _no_card(agent_key_stuck,\n")]),
    ("A10", "over", "⛔ the card is throttled too — a stuck agent waits for the next window",
     [('                    log(f"[{name}] CUA arbiter: CONFIRMED STUCK", "WARN")',
       '                    log(f"[{name}] CUA arbiter: CONFIRMED STUCK", "WARN")\n'
       '                    if since_warn < STUCK_WARN_THROTTLE_SEC:\n'
       '                        continue')]),
    ("A11", "over", "the WORKING reset loses its cap — a dead leg can be held open again",
     [("                    _reset_ok = (not _never_grew\n"
       "                                 and p[\"arbiter_working_resets\"] <= _ARBITER_MAX_WORKING_RESETS)",
       "                    _reset_ok = True")]),
    ("A12", "over", "⛔ a never-grew leg gets its clock rewound again",
     [('                    _never_grew = (p.get("last_growth_len", 0) == 0\n'
       '                                   and p.get("last_growth_sources", 0) == 0)',
       "                    _never_grew = False")]),
    ("A13", "over", "the WORKING verdict stops resetting the clock when it is allowed to",
     [('                    if _reset_ok:\n                        p["last_growth_time"] = time.time()\n', "")]),
    ("A14", "over", "renewed growth no longer clears the throttle",
     [('                    p["stuck_alerted_at"] = 0.0\n'
       '                    p["stuck_warned_at"] = 0.0\n'
       '                    _disarm_registry(agent_key_stuck)   # #955 P2: flag↔registry lockstep\n'
       '                    log(f"[{name}] Recovered after a stuck alert (growth resumed) — "',
       '                    p["stuck_alerted_at"] = 0.0\n'
       '                    _disarm_registry(agent_key_stuck)\n'
       '                    log(f"[{name}] Recovered after a stuck alert (growth resumed) — "')]),
    ("A15", "over", "a user poke no longer restarts the escalation",
     [('                p["stuck_alerted_at"] = 0.0\n'
       '                p["stuck_warned_at"] = 0.0\n'
       '                _disarm_registry(agent_key_stuck)   # #955 P2: poke disarms the deadline',
       '                p["stuck_alerted_at"] = 0.0\n'
       '                _disarm_registry(agent_key_stuck)')]),
    ("A16", "over", "the probe stamps the completion clock again (the 2026-07-11 defect)",
     [('                    _confirmed_stuck = bool(_sp_match and _sp_match.group(1) == "stuck")',
       '                    _confirmed_stuck = bool(_sp_match and _sp_match.group(1) == "stuck")\n'
       '                    p["last_cua_check"] = time.time()')]),

    # ══════════════ fix 2 — the vision-URL budget and its clock ════════════
    ("V1", "under", "⭐ the read timeout is back to ten seconds against a 2400-token budget",
     [("timeout=_VISION_URL_TIMEOUT_S", "timeout=10.0")]),
    ("V2", "over", "the budget drops back to 800 — the invariant holds and the truncation returns",
     [('_VISION_URL_MAX_TOKENS = int(os.environ.get("DG_VISION_URL_MAX_TOKENS", "2400"))',
       '_VISION_URL_MAX_TOKENS = int(os.environ.get("DG_VISION_URL_MAX_TOKENS", "800"))')]),
    ("V3", "over", "⛔ a five-minute timeout inside a two-minute poll interval",
     [('"DG_VISION_URL_TIMEOUT_S", "30.0"', '"DG_VISION_URL_TIMEOUT_S", "300.0"')]),
    ("V4", "over", "⛔ no timeout at all — the socket can hold the whole round-robin",
     [("resp = _req.post(url, json=payload, timeout=_VISION_URL_TIMEOUT_S)",
       "resp = _req.post(url, json=payload)")]),
    ("V5", "under", "the assumed rate is raised until the invariant asserts nothing",
     [("_VISION_URL_MIN_TOKENS_PER_SEC = 100", "_VISION_URL_MIN_TOKENS_PER_SEC = 1000")]),
    ("V6", "under", "the request goes back to a literal, decoupled from the clock",
     [('"maxOutputTokens": _VISION_URL_MAX_TOKENS,', '"maxOutputTokens": 2400,')]),
    ("V7", "over", "the timeout stops being tunable without a redeploy",
     [('_VISION_URL_TIMEOUT_S = float(os.environ.get("DG_VISION_URL_TIMEOUT_S", "30.0"))',
       "_VISION_URL_TIMEOUT_S = 30.0")]),
    ("V8", "over", "the 08-11 salvage is displaced — a clipped body returns nothing again",
     [("                return _salvaged, (_VISION_URL_SALVAGE_CONFIDENCE if _salvaged else 0.0)",
       "                return [], 0.0")]),
    ("V9", "over", "⛔ a timed-out socket now takes the whole poll leg down",
     [("        except Exception as e:\n"
       '            log(f"[{agent_key}] vision-urls call error: {e}", "WARN")\n'
       "            return [], 0.0",
       "        except ValueError as e:\n"
       '            log(f"[{agent_key}] vision-urls call error: {e}", "WARN")\n'
       "            return [], 0.0"),
      ("    except Exception as e:\n"
       '        log(f"[{agent_key}] vision-urls call failed: {e}", "WARN")\n'
       "        return []",
       "    except ValueError as e:\n"
       '        log(f"[{agent_key}] vision-urls call failed: {e}", "WARN")\n'
       "        return []")]),
    ("V10", "over", "the call starts retrying every tick — the sizing rationale changes",
     [('                        p["vision_urls_done"] = True\n'
       "                    except Exception as _vue:",
       "                    except Exception as _vue:")]),
    ("V11", "over", "the panel gate is dropped — a closed panel costs the full timeout",
     [('                    (name == "ChatGPT" and p.get("chatgpt_activity_panel_open"))',
       '                    (name == "ChatGPT")')]),

    # ═══════════ fix 3 — the salvage ladder on a page that stopped ═════════
    ("F1", "under", "⭐ the hard-cap salvage runs the whole ladder again",
     [("                            browser=None if _as_frozen else browser,\n"
       "                            cua_client=None if _as_frozen else cua_client,",
       "                            browser=browser,\n"
       "                            cua_client=cua_client,")]),
    ("F2", "under", "⭐ only one of the two sites was fixed — the unacted-card firer",
     [("                        browser=None if _fz else browser,\n"
       "                        cua_client=None if _fz else cua_client,",
       "                        browser=browser,\n"
       "                        cua_client=cua_client,")]),
    ("F3", "over", "⛔ a page we are BLIND to is treated as frozen (the 2026-04-28 class)",
     [('    if not (p.get("last_growth_len", 0) or p.get("last_growth_sources", 0)):\n        return False',
       '    if not (p.get("last_growth_len", 0) or p.get("last_growth_sources", 0)):\n        return True')]),
    ("F4", "over", "⛔ every auto-skip drops its tiers — the window collapses to nothing",
     [("str(STUCK_NO_GROWTH_SEC * 2)", "str(0)")]),
    ("F5", "over", "⛔ the freshness test is gone — a producing agent loses its ladder",
     [('    return (time.time() - p.get("last_growth_time", time.time())) >= frozen_sec',
       "    return True")]),
    ("F6", "under", "the frozen window is a whole extra hour — never reached in a 90-min leg",
     [("str(STUCK_NO_GROWTH_SEC * 2)", "str(STUCK_NO_GROWTH_SEC * 20)")]),
    ("F7", "over", "an unknown growth timestamp reads as 1970, so every leg is frozen",
     [('p.get("last_growth_time", time.time())) >= frozen_sec',
       'p.get("last_growth_time", 0)) >= frozen_sec')]),
    ("F8", "over", "readable now needs BOTH signals — a sources-only panel reads blind",
     [('    if not (p.get("last_growth_len", 0) or p.get("last_growth_sources", 0)):',
       '    if not (p.get("last_growth_len", 0) and p.get("last_growth_sources", 0)):')]),
    ("F9", "over", "⛔ the decision raises on a half-built leg, taking the finalize with it",
     [('    if not (p.get("last_growth_len", 0) or p.get("last_growth_sources", 0)):',
       '    if not (int(p["last_growth_len"]) or int(p["last_growth_sources"])):')]),
    ("F10", "over", "⛔ the user-skip salvage loses its tiers too",
     [("                        _partial = await extract_fns[_agent_name](\n"
       "                            p[\"page\"], browser=browser, cua_client=cua_client,",
       "                        _partial = await extract_fns[_agent_name](\n"
       "                            p[\"page\"], browser=None, cua_client=None,")]),
    ("F11", "over", "⛔ the parked resolver's hard cap decides on a clock that stopped when it parked",
     [("                            _hc_partial = await extract_fns[name](\n"
       "                                p[\"page\"], browser=browser, cua_client=cua_client,",
       "                            _hc_partial = await extract_fns[name](\n"
       "                                p[\"page\"],\n"
       "                                browser=None if _frozen_to_a_working_scraper(p, SALVAGE_FROZEN_SEC) else browser,\n"
       "                                cua_client=None if _frozen_to_a_working_scraper(p, SALVAGE_FROZEN_SEC) else cua_client,")]),
    ("F12", "over", "⛔ the hands-off wall check is bypassed at the firer",
     [("            if _key in _controls.hv_blocked:", "            if False:")]),
    ("F13", "over", "the salvage result is dropped on the floor at the hard cap",
     [("                    partial=_as_partial, url=p.get(\"url\", \"\"),",
       "                    partial=\"\", url=p.get(\"url\", \"\"),")]),
    ("F14", "over", "the firer stops re-validating, so a user Retry during salvage is overridden",
     [("            if _did not in _pending_decisions or _nm not in pending:", "            if False:")]),
    ("F15", "over", "the 90-minute ceiling itself is moved",
     [('PER_AGENT_HARD_CAP_SEC = int(os.environ.get("DG_PER_AGENT_HARD_CAP_SEC", "5400"))',
       'PER_AGENT_HARD_CAP_SEC = int(os.environ.get("DG_PER_AGENT_HARD_CAP_SEC", "9999"))')]),
    ("F16", "over", "the frozen branch salvages silently — indistinguishable from a failed one",
     [('                    if _as_frozen:\n'
       '                        log(f"[{name}] Auto-skip — the scrape reads this page "',
       '                    if False:\n'
       '                        log(f"[{name}] Auto-skip — the scrape reads this page "')]),
    ("F17", "over", "⛔ ChatGPT's download tier stops honouring browser=None",
     [("    if browser and cua_client:\n        md = await _extract_via_cua_download(",
       "    if True:\n        md = await _extract_via_cua_download(")]),
    ("F18", "over", "⛔ ChatGPT's clipboard tier stops honouring it either",
     [('    if browser and cua_client:\n        async def _cgpt_t3_trigger():',
       '    if True:\n        async def _cgpt_t3_trigger():')]),
    ("F19", "over", "the tab is no longer focused before the DOM read",
     [('                        await browser.switch_to_page(p["page"])\n'
       "                        _as_partial = await extract_fns[name](",
       "                        _as_partial = await extract_fns[name](")]),
    ("F20", "over", "the salvage can take the run down instead of logging and moving on",
     [("                    except Exception as _ase:\n"
       '                        log(f"[{name}] Auto-skip salvage extract failed: {_ase}", "WARN")',
       "                    except KeyboardInterrupt as _ase:\n"
       '                        log(f"[{name}] Auto-skip salvage extract failed: {_ase}", "WARN")')]),
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
