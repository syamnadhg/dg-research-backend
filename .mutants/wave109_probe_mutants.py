"""Wave 10.9 — can the guards see a hung Chrome, and a closed tab?

⛔⛔ WHAT THE WAVE CLOSED (M12). `_browser_context_is_dead` awaited
`ctx.cookies()` with no bound, and the driver gives that call no timeout of its
own. A HUNG Chrome — process alive, CDP silent — parked the probe for ever at
every call site; the notebook park sits outside any phase ceiling, so nothing
above it would ever time out. No card, no relaunch, no log line.

⛔⛔ AND THE SAME HOLE ONE STEP LATER. The probe answering "dead" sends the run
to `run_pipeline`'s finally, whose `Browser.close()` awaited the driver's close
— which sends Chrome `Browser.close` and waits, unbounded, for the process to
exit. A hung Chrome never exits. `start()`'s orphan sweep spares a Chrome
younger than the --serve process, so on the relaunch nothing would have killed
it either. The close is bounded now and its timeout reaches the existing
kill-our-profile fallback.

⭐ M8 IS THE SAME PROBE AT THE ONE SITE THAT JUDGED BY TEXT. The phase-3 upload
read "Target page, context or browser has been closed" and relaunched Chrome
when only the NotebookLM tab had gone. It asks the context first now: dead or
hung → unwind as before; alive → a fresh tab, silently, while an attempt is
left; the last attempt still reaches the card.

Every mutant below is a way the fix could go back to decoration while still
looking installed. The quiet ones:

  P3/P4 — the timeout arm deleted, or moved below `except Exception`. The
          `wait_for` is still there and still greppable; the generic arm reads
          an empty TimeoutError as "unrecognised" and answers ALIVE, so the
          caller's next CDP call hangs exactly where the probe used to.
  C3    — the close is bounded but the timeout is swallowed: "Browser closed"
          is logged over a Chrome that is still running and still hung.
  M2    — the helper reads the text BEFORE it asks the context. Every word is
          still there; a dead browser now gets a silent tab retry instead of
          the relaunch, which is the 8D9CWHZJ park by a different road.
  M5    — the silent retry spreads to the last attempt. Nothing unwinds and no
          card appears: the run quietly proceeds without NotebookLM.
  M8    — a closed tab asks the person instead of retrying: the fix the lens
          warned was WORSE than the bug under the "self-heal silent" rule.
  X5/X6 — repair round 2. The watchdog is wired to phase 2 alone again, so the
          identical freeze stays live in phase 1's poll and the phase-3 audio
          wait — both unbounded, both under a BUTTONLESS soft ceiling — while
          the decoration on phase 2 still reads as if #547 were closed.
  X7    — the wrapper finds the browser POSITIONALLY. Correct for phase 2, and
          `None` for the two waits whose signatures put it elsewhere: the mark
          says watched, the probe asks something with no context, nothing fires.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is also COMPILED before it is written: a mutant that does not
parse fails every test and would otherwise be reported as a kill.

  python .mutants/wave109_probe_mutants.py
  python .mutants/wave109_probe_mutants.py P3 M2
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_hung_browser_probe_109.py "
          "tests/test_browser_death_unwinds_0920.py "
          "tests/test_browser_death_unwinds_every_window_0920.py "
          "tests/test_browser_crash_recovery.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
# ⭐ The interpreter running this harness, not `.venv/bin/python` under ROOT: a
# builder's worktree has no venv of its own, and a missing interpreter fails
# every run — which a harness reads as every mutant killed.
PY = sys.executable

# ── anchors: the probe ─────────────────────────────────────────────────────
#: The bound itself.
P_BOUND = "        await asyncio.wait_for(ctx.cookies(), timeout=_CTX_PROBE_TIMEOUT_SEC)\n"
#: The default bound.
P_CONST = "_CTX_PROBE_TIMEOUT_SEC = 10.0\n"
#: The timeout arm, whole — its verdict, its log line and its position.
P_ARM = ("    except asyncio.TimeoutError:\n"
         "        # \u26d4 Caught BEFORE the generic arm, which would read an empty\n"
         "        # TimeoutError as \"unrecognised\" and answer alive.\n"
         "        log(f\"[browser] the context did not answer a cookie read within \"\n"
         "            f\"{_CTX_PROBE_TIMEOUT_SEC:g}s \u2014 treating a hung Chrome as a dead one \"\n"
         "            f\"so the crash path can replace it\", \"WARN\")\n"
         "        return True\n"
         "    except Exception as _e:\n"
         "        return _is_browser_close_error(_e)\n")
#: The verdict alone.
P_VERDICT = ("            f\"so the crash path can replace it\", \"WARN\")\n"
             "        return True\n")
#: The log line alone.
P_LOG = ("        log(f\"[browser] the context did not answer a cookie read within \"\n"
         "            f\"{_CTX_PROBE_TIMEOUT_SEC:g}s \u2014 treating a hung Chrome as a dead one \"\n"
         "            f\"so the crash path can replace it\", \"WARN\")\n")

# ── anchors: Browser.close ─────────────────────────────────────────────────
C_BOUND = ("                await asyncio.wait_for(self.context.close(),\n"
           "                                       timeout=_BROWSER_CLOSE_TIMEOUT_SEC)\n")
C_CONST = "_BROWSER_CLOSE_TIMEOUT_SEC = 30.0\n"
C_LOG = "            log(f\"Browser close error: {str(e) or type(e).__name__}\", \"WARN\")\n"

# ── anchors: D14, the driver the kill arm used to leave running ────────────
#: The stop, bounded, in its own try, AFTER the kill.
C_STOP = ("            if self.playwright:\n"
          "                try:\n"
          "                    await asyncio.wait_for(self.playwright.stop(),\n"
          "                                           timeout=_BROWSER_STOP_TIMEOUT_SEC)\n"
          "                except Exception as _stop_err:\n"
          "                    log(f\"Playwright stop error: \"\n"
          "                        f\"{str(_stop_err) or type(_stop_err).__name__}\", \"WARN\")\n")
#: Giving up both handles, so a second close() repeats nothing.
C_CLEAR = ("            self.context = None\n"
           "            self.playwright = None\n")
#: The head of the kill loop — the line the stop must come AFTER.
C_KILL_HEAD = "            # Kill only OUR profile's chromium — never nuke all chrome.exe\n"
C_STOP_CONST = "_BROWSER_STOP_TIMEOUT_SEC = 10.0\n"

# ── anchors: D5, the watchdog beside every soft-ceilinged browser wait ─────
#: The narrow question — did it ANSWER — and the wide one it is not.
W_ASK = "            if not await _browser_context_is_unresponsive(browser):\n"
#: An answer wipes the slate.
W_RESET = ("                silences = 0\n"
           "                continue\n")
#: The ladder.
W_LADDER = ("            if silences < _BROWSER_HANG_STRIKES:\n"
            "                continue\n")
#: The wait can come back DURING the probe that spends the ladder.
W_RACE = ("            if task.done():\n"
          "                # ⭐ THE RACE THE LADDER CREATES. Each rung costs a full probe,\n"
          "                # and the wait can come back during one — with the phase's\n"
          "                # results. Unwinding on a browser nobody is waiting on any more\n"
          "                # would buy the whole of phase 2 a second time.\n"
          "                return task.result()\n")
#: The unwind: the flag, the sweep's own sentence, and the wait it names.
W_RAISE = ("            _runtime.last_failure_kind = \"browser_crash\"\n"
           "            raise RuntimeError(\n"
           "                f\"research browser hung during {what} (browser crash)\")\n")
#: The wait must not keep driving the old tabs.
W_CANCEL = ("        if not task.done():\n"
            "            task.cancel()\n")
W_CHECK_CONST = "_BROWSER_HANG_CHECK_SEC = 120.0\n"
W_STRIKES_CONST = "_BROWSER_HANG_STRIKES = 3\n"
#: `_browser_context_is_unresponsive`: no handle is not a silence.
U_NONE = ("    ctx = getattr(browser, \"context\", None)\n"
          "    if ctx is None:\n"
          "        return False\n")
#: …and its own bound on the question.
U_BOUND = ("        await asyncio.wait_for(ctx.cookies(),\n"
           "                               timeout=_CTX_PROBE_TIMEOUT_SEC)\n")

# ── anchors: D5, the decorations that tie the watchdog to the three waits ──
X_DECO = ("@_watched_for_a_hung_browser(\"phase 2\")\n"
          "async def poll_all_agents_round_robin(agents, browser, cua_client,\n")
X_DECO_P1 = ("@_watched_for_a_hung_browser(\"phase 1's poll\")\n"
             "async def poll_until_done(page, verify_fn, label, poll_interval, max_wait_min,\n")
X_DECO_P3 = ("@_watched_for_a_hung_browser(\"the phase-3 audio wait\")\n"
             "async def run_phase3_audio(browser, cua_client, notebook_url, queue_dir,")
X_WRAPS = "        @functools.wraps(wait_fn)\n"
X_BODY = ("            return await _run_watching_for_a_hung_browser(\n"
          "                browser, wait_fn(*args, **kwargs), what)\n")
#: Finding the browser wherever the signature puts it.
X_FIND = ("                browser = signature.bind_partial(*args, **kwargs).arguments.get(\"browser\")\n")
#: …and an answer is an answer, whatever it says.
U_ARMS = ("    except asyncio.TimeoutError:\n"
          "        return True\n"
          "    except Exception:\n"
          "        # It answered. Whatever it said, it is talking to us.\n"
          "        return False\n"
          "    return False\n")

# ── anchors: M8, the helper ────────────────────────────────────────────────
H_BODY = ("    if await _browser_context_is_dead(browser):\n"
          "        return \"browser_dead\"\n"
          "    if _is_browser_close_error(exc):\n"
          "        return \"tab_closed\"\n"
          "    return \"other\"\n")

# ── anchors: M8, the consumer ──────────────────────────────────────────────
U_CALL = "            _p3_fail_kind = await _p3_upload_failure_kind(e, browser)\n"
U_DEAD = ("            if _p3_fail_kind == \"browser_dead\":\n"
          "                _runtime.last_failure_kind = \"browser_crash\"\n")
U_TAB = "            if _p3_fail_kind == \"tab_closed\" and p3_attempt < p3_max_retries:\n"
U_TAB_BODY = ("                    \"retrying the upload in a fresh tab\", \"WARN\")\n"
              "                p3_attempt += 1\n")
U_TAB_CLOSE = ("                # A crashed tab can linger as a sad tab; close it the way the\n"
               "                # Retry path below does, so the fresh one is the only one.\n"
               "                try:\n"
               "                    await page.close()\n"
               "                except Exception:\n"
               "                    pass\n"
               "                continue\n")

MUTANTS = [
    # ── M12: the probe ──
    ("P1", "under", RESEARCH,
     "\u26d4\u26d4 THE DEFECT ITSELF \u2014 the probe awaits cookies() unbounded "
     "again, and a hung Chrome parks every caller for ever",
     [(P_BOUND, "        await ctx.cookies()\n")]),

    ("P2", "under", RESEARCH,
     "\u26d4\u26d4 the bound stays and a timeout answers ALIVE \u2014 the docstring's "
     "old fail-safe, applied to the one case where alive means the next call hangs",
     [(P_VERDICT, "            f\"so the crash path can replace it\", \"WARN\")\n"
                  "        return False\n")]),

    ("P3", "under", RESEARCH,
     "\u26d4\u26d4 the timeout arm deleted: the generic arm reads an empty "
     "TimeoutError as unrecognised and answers alive, with wait_for still in place",
     [(P_ARM, "    except Exception as _e:\n"
              "        return _is_browser_close_error(_e)\n")]),

    ("P4", "under", RESEARCH,
     "\u26d4 the arms swapped \u2014 `except Exception` first swallows the "
     "TimeoutError, so the timeout arm below it is dead code that still reads right",
     [(P_ARM, "    except Exception as _e:\n"
              "        return _is_browser_close_error(_e)\n"
              "    except asyncio.TimeoutError:\n"
              "        return True\n")]),

    ("P5", "under", RESEARCH,
     "\u26d4 the bound is disabled in place (`timeout=None`) \u2014 wait_for present, "
     "bound gone",
     [(P_BOUND, "        await asyncio.wait_for(ctx.cookies(), timeout=None)\n")]),

    ("P6", "under", RESEARCH,
     "\u26d4 the default bound is an hour: a freeze with extra steps",
     [(P_CONST, "_CTX_PROBE_TIMEOUT_SEC = 3600.0\n")]),

    ("P7", "over", RESEARCH,
     "\u26d4\u26d4 THE OVER-CORRECTION \u2014 a zero bound times out every probe, "
     "so every healthy run is unwound and relaunched at its first probe",
     [(P_CONST, "_CTX_PROBE_TIMEOUT_SEC = 0.0\n")]),

    ("P8", "under", RESEARCH,
     "the hang is treated right and said nowhere: the only line that explains a "
     "relaunch on a browser that never crashed",
     [(P_LOG, "")]),

    # ── M12: the close on the unwind ──
    ("C1", "under", RESEARCH,
     "\u26d4\u26d4 THE SECOND FREEZE \u2014 Browser.close() awaits the driver "
     "unbounded, and the driver waits for a hung Chrome to exit",
     [(C_BOUND, "                await self.context.close()\n")]),

    ("C2", "under", RESEARCH,
     "\u26d4 the close bound is an hour",
     [(C_CONST, "_BROWSER_CLOSE_TIMEOUT_SEC = 3600.0\n")]),

    ("C3", "under", RESEARCH,
     "\u26d4\u26d4 bounded but SWALLOWED: 'Browser closed' is logged over a Chrome "
     "that is still running and still hung, and nothing kills it",
     [(C_BOUND, "                try:\n"
                "                    await asyncio.wait_for(self.context.close(),\n"
                "                                           timeout=_BROWSER_CLOSE_TIMEOUT_SEC)\n"
                "                except asyncio.TimeoutError:\n"
                "                    pass\n")]),

    ("C4", "under", RESEARCH,
     "the close timeout logs as 'Browser close error: ' with nothing after it",
     [(C_LOG, "            log(f\"Browser close error: {e}\", \"WARN\")\n")]),

    # ── M8: the helper ──
    ("M1", "under", RESEARCH,
     "\u26d4\u26d4 THE CONSUMER STOPS ASKING \u2014 the handler classifies by text "
     "again, and a closed tab relaunches Chrome",
     [(U_CALL, "            _p3_fail_kind = (\"browser_dead\" if _is_browser_close_error(e)\n"
               "                             else \"other\")\n")]),

    ("M2", "under", RESEARCH,
     "\u26d4\u26d4 the text is read BEFORE the context is asked: a dead browser gets "
     "a silent tab retry instead of the relaunch",
     [(H_BODY, "    if _is_browser_close_error(exc):\n"
               "        return \"tab_closed\"\n"
               "    if await _browser_context_is_dead(browser):\n"
               "        return \"browser_dead\"\n"
               "    return \"other\"\n")]),

    ("M3", "under", RESEARCH,
     "\u26d4\u26d4 the helper never asks the context at all \u2014 every close text "
     "becomes 'just a tab'",
     [(H_BODY, "    if _is_browser_close_error(exc):\n"
               "        return \"tab_closed\"\n"
               "    return \"other\"\n")]),

    ("M4", "under", RESEARCH,
     "\u26d4 the probe runs only behind close text: a dead Chrome behind a timeout "
     "gets the 'Retry to try again' card that can never work",
     [(H_BODY, "    if _is_browser_close_error(exc):\n"
               "        if await _browser_context_is_dead(browser):\n"
               "            return \"browser_dead\"\n"
               "        return \"tab_closed\"\n"
               "    return \"other\"\n")]),

    # ── M8: the consumer ──
    ("M5", "under", RESEARCH,
     "\u26d4\u26d4 the silent retry spreads to the LAST attempt: no unwind, no card, "
     "and the run quietly proceeds without NotebookLM",
     [(U_TAB, "            if _p3_fail_kind == \"tab_closed\":\n")]),

    ("M6", "under", RESEARCH,
     "\u26d4\u26d4 the silent retry spends no attempt \u2014 a tab that keeps closing "
     "loops for ever",
     [(U_TAB_BODY, "                    \"retrying the upload in a fresh tab\", \"WARN\")\n")]),

    ("M7", "over", RESEARCH,
     "\u26d4 a closed tab is still a dead browser: the relaunch and the crash-budget "
     "unit M8 exists to save",
     [(U_DEAD, "            if _p3_fail_kind in (\"browser_dead\", \"tab_closed\"):\n"
               "                _runtime.last_failure_kind = \"browser_crash\"\n")]),

    ("M8", "over", RESEARCH,
     "\u26d4\u26d4 a closed tab ASKS instead of retrying \u2014 the fix the lens "
     "warned is worse than the bug under 'self-heal silent'",
     [(U_TAB, "            if False:\n")]),

    ("M9", "under", RESEARCH,
     "the crashed tab is left open as a sad tab beside the fresh one",
     [(U_TAB_CLOSE, "                continue\n")]),

    ("M10", "under", RESEARCH,
     "\u26d4 the unwind loses its flag: the kind rides on the text alone, and the "
     "top-level login-interrupt check reads the flag",
     [(U_DEAD, "            if _p3_fail_kind == \"browser_dead\":\n")]),

    # ── D14 (repair round): the driver behind the kill ──
    ("C5", "under", RESEARCH,
     "\u26d4\u26d4 THE LEAK ITSELF \u2014 the kill arm gives up on Chrome and "
     "leaves the node driver and its pipe running for the life of --serve",
     [(C_STOP, "")]),

    ("C6", "under", RESEARCH,
     "\u26d4\u26d4 the stop is there and unbounded: the run's way out now waits "
     "on a driver that is itself waiting, which is the freeze one layer down",
     [(C_STOP, "            if self.playwright:\n"
               "                try:\n"
               "                    await self.playwright.stop()\n"
               "                except Exception as _stop_err:\n"
               "                    log(f\"Playwright stop error: \"\n"
               "                        f\"{str(_stop_err) or type(_stop_err).__name__}\", \"WARN\")\n")]),

    ("C7", "under", RESEARCH,
     "\u26d4 the handles survive the arm: the next close() repeats the bounded "
     "wait, the kill and the stop on a browser we already gave up on",
     [(C_CLEAR, "")]),

    ("C8", "under", RESEARCH,
     "\u26d4 only the context is given up \u2014 the stopped driver handle stays, "
     "so a second close() stops it again",
     [(C_CLEAR, "            self.context = None\n")]),

    ("C9", "over", RESEARCH,
     "\u26d4 the stop runs BEFORE the kill: stopping a driver that is waiting "
     "for a Chrome which never exits is the wait we are escaping",
     [(C_STOP, ""),
      (C_KILL_HEAD,
       "            if self.playwright:\n"
       "                try:\n"
       "                    await asyncio.wait_for(self.playwright.stop(),\n"
       "                                           timeout=_BROWSER_STOP_TIMEOUT_SEC)\n"
       "                except Exception as _stop_err:\n"
       "                    log(f\"Playwright stop error: \"\n"
       "                        f\"{str(_stop_err) or type(_stop_err).__name__}\", \"WARN\")\n"
       "            # Kill only OUR profile's chromium \u2014 never nuke all chrome.exe\n")]),

    ("C10", "under", RESEARCH,
     "\u26d4 a stop that throws escapes close() \u2014 out of the arm that IS the "
     "unwind, past the kill it just did",
     [(C_STOP, "            if self.playwright:\n"
               "                await asyncio.wait_for(self.playwright.stop(),\n"
               "                                       timeout=_BROWSER_STOP_TIMEOUT_SEC)\n")]),

    ("C11", "under", RESEARCH,
     "\u26d4 the driver bound is an hour",
     [(C_STOP_CONST, "_BROWSER_STOP_TIMEOUT_SEC = 3600.0\n")]),

    # ── D5 (repair round): the watchdog beside phase 2's poll ──
    ("W1", "under", RESEARCH,
     "\u26d4\u26d4 THE PAUSE ENDS IN A FAKE CRASH \u2014 the watchdog asks the "
     "wide question, so a browser somebody CLOSED reads as one gone silent",
     [(W_ASK, "            if not await _browser_context_is_dead(browser):\n")]),

    ("W2", "under", RESEARCH,
     "\u26d4 an answer stops wiping the slate: stalls minutes apart add up and "
     "a healthy run is unwound at the third one, whenever it comes",
     [(W_RESET, "                continue\n")]),

    ("W3", "under", RESEARCH,
     "\u26d4\u26d4 THE FREEZE, WITH A LOG LINE \u2014 the hang is noticed, named, "
     "and watched for ever: nothing unwinds",
     [(W_RAISE, "            silences = 0\n"
                "            continue\n")]),

    ("W4", "under", RESEARCH,
     "\u26d4 the unwind loses the marker the top-level handler re-derives the "
     "kind from, so a reset runtime downgrades it to an ordinary failure card",
     [(W_RAISE, "            _runtime.last_failure_kind = \"browser_crash\"\n"
                "            raise RuntimeError(\n"
                "                \"research browser hung during phase 2\")\n")]),

    ("W5", "under", RESEARCH,
     "\u26d4 the unwind loses its flag",
     [(W_RAISE, "            raise RuntimeError(\n"
                "                \"research browser hung during phase 2 (browser crash)\")\n")]),

    ("W6", "under", RESEARCH,
     "\u26d4\u26d4 the poll is abandoned, not cancelled: the relaunch builds a "
     "second browser under a loop still driving the first one's tabs",
     [(W_CANCEL, "        if not task.done():\n"
                 "            pass\n")]),

    ("W7", "under", RESEARCH,
     "\u26d4 the watchdog looks once an hour \u2014 a phase-long freeze with a "
     "check in it",
     [(W_CHECK_CONST, "_PHASE2_HANG_CHECK_SEC = 3600.0\n")]),

    ("W8", "over", RESEARCH,
     "\u26d4\u26d4 THE OVER-CORRECTION \u2014 one silence unwinds the run, so a "
     "single stalled cookie read costs a healthy phase 2 and a crash-budget unit",
     [(W_STRIKES_CONST, "_PHASE2_HANG_STRIKES = 1\n")]),

    ("W9", "over", RESEARCH,
     "\u26d4 a browser with no context reads as silent \u2014 the state a pause "
     "leaves behind between the close and the relaunch",
     [(U_NONE, "    ctx = getattr(browser, \"context\", None)\n"
               "    if ctx is None:\n"
               "        return True\n")]),

    ("W10", "over", RESEARCH,
     "\u26d4\u26d4 the narrow question widens back into the wide one: a close "
     "error counts as silence, and the watchdog owns the closed browser again",
     [(U_ARMS, "    except asyncio.TimeoutError:\n"
               "        return True\n"
               "    except Exception as _e:\n"
               "        return _is_browser_close_error(_e)\n"
               "    return False\n")]),

    ("W11", "under", RESEARCH,
     "\u26d4\u26d4 silence reads as an answer: the watchdog runs, probes, and "
     "can never see the one thing it is there for",
     [(U_ARMS, "    except asyncio.TimeoutError:\n"
               "        return False\n"
               "    except Exception:\n"
               "        return False\n"
               "    return False\n")]),

    ("W12", "over", RESEARCH,
     "\u26d4 the ladder is one rung whatever the constant says",
     [(W_LADDER, "            if silences < 1:\n"
                 "                continue\n")]),

    ("W13", "under", RESEARCH,
     "\u26d4\u26d4 the watchdog's own question is unbounded \u2014 the one probe "
     "left in the run hangs on the browser it is asking about",
     [(U_BOUND, "        await ctx.cookies()\n")]),

    ("W14", "under", RESEARCH,
     "⛔ a phase 2 that came back DURING the last probe is thrown away and "
     "bought again — the unwind decides on a browser nobody is waiting on",
     [(W_RACE, "")]),

    ("X1", "under", RESEARCH,
     "\u26d4\u26d4 THE WIRING \u2014 the poll is declared undecorated, so every "
     "word of the watchdog is still there and nothing runs it",
     [(X_DECO, "async def poll_all_agents_round_robin(agents, browser, cua_client,\n")]),

    ("X2", "under", RESEARCH,
     "\u26d4\u26d4 the decoration is applied and awaits the wait DIRECTLY: the "
     "mark is set, the watchdog is imported, and the freeze is unchanged",
     [(X_BODY, "            return await wait_fn(*args, **kwargs)\n")]),

    ("X3", "under", RESEARCH,
     "\u26d4 the watchdog is handed the wrong argument \u2014 it probes something "
     "with no context, which never answers 'silent', so it can never fire",
     [(X_FIND, "                browser = None\n"
               "                _ = signature\n")]),

    ("X4", "under", RESEARCH,
     "\u26d4 the wrapper stops carrying `__wrapped__`: dozens of other files read "
     "these functions' SOURCE and would silently start reading the wrapper's",
     [(X_WRAPS, "")]),

    # \u2500\u2500 D5 (repair round 2): the two waits the first repair left frozen \u2500\u2500
    ("X5", "under", RESEARCH,
     "\u26d4\u26d4 #547 STAYS LIVE IN PHASE 1 \u2014 the brief poll is declared "
     "undecorated again, under a soft ceiling whose banner has no button",
     [(X_DECO_P1,
       "async def poll_until_done(page, verify_fn, label, poll_interval, max_wait_min,\n")]),

    ("X6", "under", RESEARCH,
     "\u26d4\u26d4 #547 STAYS LIVE IN THE PHASE-3 AUDIO WAIT \u2014 90 minutes of "
     "soft ceiling and then a warning nobody can act on",
     [(X_DECO_P3,
       "async def run_phase3_audio(browser, cua_client, notebook_url, queue_dir,")]),

    ("X7", "under", RESEARCH,
     "\u26d4\u26d4 the browser is found POSITIONALLY \u2014 right for phase 2, "
     "`None` for the other two, so both keep freezing while the mark says watched",
     [(X_FIND, "                browser = args[1] if len(args) > 1 else None\n"
               "                _ = signature\n")]),

    ("X8", "under", RESEARCH,
     "\u26d4 every unwind says 'phase 2' \u2014 the line the freeze was diagnosed "
     "off, naming the wrong wait for two of the three",
     [(W_RAISE, "            _runtime.last_failure_kind = \"browser_crash\"\n"
                "            raise RuntimeError(\n"
                "                \"research browser hung during phase 2 (browser crash)\")\n")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    r = _run(f"\"{PY}\" -m pytest {SUITES} -q -p no:cacheprovider")
    # \u26d4 THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    # \u26d4 And ONLY the summary line: pytest's warnings section can quote paths
    # and messages containing "error" (tmp-dir cleanup warnings do, on this
    # machine), and a whole-output search would count a green run as a KILL.
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    summary = lines[-1] if lines else ""
    return ("passed" in summary and "failed" not in summary
            and "error" not in summary)


# \u26d4\u26d4 EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep
# loads every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it \u2014 an unguarded runner turns a seconds-long check into a full
# mutation run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}


    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")


    only = set(sys.argv[1:])
    print("baseline\u2026 ", end="", flush=True)
    if not green():
        print("\u26d4 BASELINE RED \u2014 fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, fname, why, edits in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  \u2717 SURVIVED ({direction}) \u2014 {why}")
            else:
                print(f"  {mid}  \u2713 killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  \u26d4 HARNESS FAULT \u2014 {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n\u26d4\u26d4 RESTORE FAILED for {f} \u2014 fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
