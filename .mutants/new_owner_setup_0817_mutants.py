"""Mutation harness for wave 1: the two things that broke a new owner's setup.

⛔ WHAT HAPPENED, 2026-08-17. Someone paired a fresh machine. Stage 4 asked

    >  Add another browser profile (profile 2)? [y/N]: 2

they typed the number the question had just used, and the loop exited printing
nothing. They wanted two concurrent run slots, got one, and [5/5] Ready
reported success without ever naming the capacity. Sixty seconds later DNS for
firestore.googleapis.com stopped resolving on their network; the reconnect
ladder retried forever, the aegis pulse went on saying "standing watch", and
the only trace in 1,376,574 lines of corpus was 4,921 identical WARNs and one
DEBUG line labelled "(non-fatal)".

⭐⭐ THE OVER-CORRECTIONS ARE WHERE THIS WAVE CAN GO WRONG:
  Y4  — every digit becomes a yes, so `2` means yes at "Remove the Super
        Research backend?" too. The affordance is only safe because the caller
        declares it.
  Y23 — the uninstall prompt defaults to yes. One stray Enter removes the
        product.
  Y6  — the echo fires on plain `y`, narrating every prompt in the CLI back at
        the user, which is how a useful signal becomes noise nobody reads.
  F3  — the outage alarm fires inside the backoff ladder, so every ordinary
        network blip raises it and the next real one is ignored.
  F4  — the alarm repeats on every retry, i.e. exactly the 4,921-line wall this
        wave exists to remove.
  F17 — `spoke_at` is stamped even when nothing was said, so the FIRST real
        alarm is suppressed for five minutes.

⭐⭐ F1 IS THE SHARPEST IN THE FILE. The reconnect loop calls
`_mark_firestore_down()` on every down tick. If that re-stamped the clock, the
elapsed time would reset to ~0 every five seconds, the threshold could never be
crossed, and the entire notice would be dead code that read as protection.

    python .mutants/new_owner_setup_0817_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_YN = "tests/test_yes_no_prompts_0817.py"
T_OUT = "tests/test_firestore_outage_speaks_0817.py"
T_PAIR = "tests/test_pair_prompt.py"
T_VERIFY = "tests/test_verification_opt_in.py"
T_SERVE = "tests/test_serve_cli_consistency.py"
T_LOGIN = "tests/test_login_profile_flow.py"
T_BRIDGE = "tests/test_stdlib_log_bridge_0817.py"
T_DOC = "tests/test_doctor_network_truth_0817.py"
# ⛔ 2026-08-19 — the aegis pulse gained an emission cadence and an uptime. Those
# properties are pinned in the log-noise file, and a harness that did not run it
# would report all of them as suite gaps.
T_NOISE = "tests/test_log_noise_0819.py"
ALL = [T_YN, T_OUT, T_PAIR, T_VERIFY, T_SERVE, T_LOGIN, T_BRIDGE, T_DOC, T_NOISE]

PY = str(ROOT / ".venv" / "bin" / "python")

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the one yes/no reader ══════════════════════════════════════════
    ("Y1", "under", "a bare Enter stops meaning what the hint promised",
     [("        if ans == \"\":\n            return default",
       "        if ans == \"\":\n            return False")],
     [T_YN]),
    ("Y2", "under", "⛔⛔ an unreadable answer is applied as the default in "
     "silence — THE ORIGINAL BUG, restored",
     [("        if attempt < max(1, int(tries)):\n            print(",
       "        if False:\n            print(")],
     [T_YN]),
    ("Y3", "under", "⛔ yes_aliases dropped, so `2` at \"profile 2?\" is a no "
     "again",
     [("    yes = tuple(_YES_WORDS) + tuple(\n        a.strip().lower() for a in yes_aliases if str(a).strip())",
       "    yes = tuple(_YES_WORDS)")],
     [T_YN]),
    ("Y4", "over", "⛔⛔ every digit is a yes everywhere — including at "
     "\"Remove the Super Research backend?\"",
     [("        if ans in yes or ans in no:",
       "        if ans.isdigit() or ans in yes or ans in no:")],
     [T_YN]),
    ("Y5", "under", "an interpreted answer is acted on without being echoed",
     [("            if ans not in _OBVIOUS_ANSWERS:\n                _read_as =",
       "            if False:\n                _read_as =")],
     [T_YN]),
    ("Y6", "over", "⛔ the echo fires on plain `y` too, narrating every prompt "
     "in the product back at the reader",
     [("            if ans not in _OBVIOUS_ANSWERS:\n                _read_as = \"yes\" if verdict else \"no\"",
       "            if True:\n                _read_as = \"yes\" if verdict else \"no\"")],
     [T_YN]),
    ("Y7", "under", "the hint stops being rendered from the default, so it can "
     "drift from the parse again",
     [("    hint = \"[Y/n]\" if default else \"[y/N]\"",
       "    hint = \"[y/N]\"")],
     [T_YN]),
    ("Y8", "under", "tries is ignored — one read, then the silent default",
     [("    for attempt in range(1, max(1, int(tries)) + 1):",
       "    for attempt in range(1, 2):")],
     [T_YN]),
    ("Y9", "under", "the give-up is silent, which is the same defect one layer "
     "down",
     [("    print(\n        f\"  {_c(_WARN, '!')}  Still no answer I can read",
       "    _unused_giveup = (\n        f\"  {_c(_WARN, '!')}  Still no answer I can read")],
     [T_YN]),
    ("Y10", "under", "\"nope\" stops being a no — the word that used to mean "
     "SKIP at the verification prompt",
     [("_NO_WORDS = (\"n\", \"no\", \"nope\", \"nah\", \"naw\")",
       "_NO_WORDS = (\"n\", \"no\")")],
     [T_YN]),
    ("Y11", "over", "a collision resolves to no instead of yes, silently "
     "reversing a caller's declared affordance",
     [("    no = tuple(w for w in (tuple(_NO_WORDS) + tuple(\n        a.strip().lower() for a in no_aliases if str(a).strip())) if w not in yes)",
       "    no = tuple(_NO_WORDS) + tuple(\n        a.strip().lower() for a in no_aliases if str(a).strip())\n    yes = tuple(w for w in yes if w not in no)")],
     [T_YN]),
    ("Y12", "under", "the answer is not normalised, so \" Yes \" is unreadable",
     [("        ans = (raw or \"\").strip().lower()",
       "        ans = raw or \"\"")],
     [T_YN]),
    ("Y13", "over", "EOF is swallowed into the default, taking the choice away "
     "from callers that handle a non-interactive stdin themselves",
     [("        raw = input(prompt)",
       "        try:\n            raw = input(prompt)\n        except EOFError:\n            return default")],
     [T_YN, T_PAIR]),

    # ══ the add-loops ══════════════════════════════════════════════════
    ("Y14", "under", "⛔ the --login add-loop goes back to exiting in silence",
     [("            if not _add_more:\n                _say_profile_capacity(next_n - 1)\n                break",
       "            if not _add_more:\n                break")],
     [T_YN]),
    ("Y15", "under", "⛔ the pair add-loop goes back to exiting in silence",
     [("            if not _add_more:\n                _say_profile_capacity(next_profile_n - 1)\n                break",
       "            if not _add_more:\n                break")],
     [T_YN]),
    ("Y16", "under", "the announcement moves after the break, where it can "
     "never run — a message that reads as protection and is not",
     [("            if not _add_more:\n                _say_profile_capacity(next_profile_n - 1)\n                break",
       "            if not _add_more:\n                break\n                _say_profile_capacity(next_profile_n - 1)")],
     [T_YN]),
    ("Y17", "under", "the yes alias is a literal \"2\" instead of the counter — "
     "right once, wrong at every later profile",
     [("                    yes_aliases=(str(next_profile_n),),",
       "                    yes_aliases=(\"2\",),")],
     [T_YN]),
    ("Y18", "under", "the capacity line stops naming a way to change it",
     [("    print(f\"  {_c(_DIM, 'Add more any time with')}  {_c(_BOLD, _PROG + ' --login')}{_c(_DIM, '.')}\")",
       "    print(f\"  {_c(_DIM, 'Done.')}\")")],
     [T_YN]),
    ("Y19", "over", "the capacity line will claim zero slots on a machine that "
     "always has profile 1",
     [("    n = max(1, int(count or 1))\n    profiles = \"profile\" if n == 1 else \"profiles\"",
       "    n = int(count or 0)\n    profiles = \"profile\" if n == 1 else \"profiles\"")],
     [T_YN]),
    ("Y20", "under", "[5/5] Ready stops reporting the capacity it is calling "
     "ready — the new owner's exact screen",
     [("        _ready_cap = max(1, int(load_worker_count() or 1))",
       "        _ready_cap = None  # noqa\n        _ready_cap = max(1, int(load_worker_count() or 1))")],
     []),  # placeholder — replaced below by Y20b
    ("Y21", "under", "Ready reads the add-loop's counter, which does not exist "
     "when profile 1 failed and Ready still runs",
     [("        _ready_cap = max(1, int(load_worker_count() or 1))",
       "        _ready_cap = max(1, int(next_profile_n - 1))")],
     [T_YN]),

    # ══ the defaults each prompt kept ══════════════════════════════════
    ("Y22", "over", "⛔ \"Skip the verification step?\" flips to default-verify, "
     "undoing the 2026-07-02 bot-score direction",
     [("_ask_yes_no(\"Skip the verification step?\", default=True)",
       "_ask_yes_no(\"Skip the verification step?\", default=False)")],
     [T_YN, T_VERIFY]),
    ("Y23", "over", "⛔⛔ \"Remove the Super Research backend?\" defaults to YES "
     "— one stray Enter uninstalls the product",
     [("_ask_yes_no_sync(\"Remove the Super Research backend?\", default=False)",
       "_ask_yes_no_sync(\"Remove the Super Research backend?\", default=True)")],
     [T_YN]),
    ("Y24", "over", "\"Enable On Startup?\" flips to default-off, quietly "
     "turning the supervised install into a manual one",
     [("        enable_on_startup = await _ask_yes_no(\"Enable On Startup?\", default=True)",
       "        enable_on_startup = await _ask_yes_no(\"Enable On Startup?\", default=False)")],
     [T_YN]),
    ("Y25", "over", "\"Save this key anyway\" defaults to yes, persisting a key "
     "the provider just rejected",
     [("_ask_yes_no(\"Save this key anyway\", default=False)",
       "_ask_yes_no(\"Save this key anyway\", default=True)")],
     [T_YN]),

    # ══ the outage clock ═══════════════════════════════════════════════
    ("F1", "under", "⭐⭐ _mark_firestore_down RE-STAMPS on every call, so the "
     "elapsed time resets every 5s and the alarm can NEVER fire",
     [("    global _firestore_down_since_ts\n    if _firestore_down_since_ts is None:\n        _firestore_down_since_ts = float(now if now is not None else time.time())",
       "    global _firestore_down_since_ts\n    _firestore_down_since_ts = float(now if now is not None else time.time())")],
     [T_OUT]),
    ("F2", "under", "the clock never stops on a successful rebuild, so the next "
     "outage is measured from the previous one",
     [("    _firebase_down_reason = None\n    _clear_firestore_down()\n    log(f\"Firestore client initialized",
       "    _firebase_down_reason = None\n    log(f\"Firestore client initialized")],
     [T_OUT]),
    # ⛔ THIS MUTANT WAS BROKEN ON ITS FIRST RUN and reported as a survivor: it
    # inserted `pass` in front of the comment and left the call standing, so it
    # mutated nothing. A survivor whose edit changes no behaviour is a harness
    # fault, never a suite gap — anchor on the whole block and delete it.
    ("F3", "under", "the heartbeat's drop stops starting the clock, so the "
     "duration is short by up to a full reconnect tick",
     [('                # Start the outage clock HERE, not in the reconnect loop: this\n                # is the moment the client actually went away, and the pulse\n                # (every 60s) would otherwise report a duration up to a full\n                # reconnect tick short of the truth.\n                _mark_firestore_down()', "")],
     [T_OUT]),
    ("F4", "under", "the reconnect loop stops starting the clock, so workers "
     "2+ and a boot-time outage never measure anything",
     [("            _mark_firestore_down()\n            attempts += 1",
       "            attempts += 1")],
     [T_OUT]),

    # ══ when the outage speaks ═════════════════════════════════════════
    ("F5", "under", "⛔ the notice never reaches the log — the helper exists "
     "and nothing calls it",
     [("                for _line in _notice:\n                    log(_line, \"ERROR\")",
       "                for _line in _notice:\n                    pass")],
     [T_OUT]),
    ("F6", "over", "⛔⛔ the alarm fires inside the backoff ladder, so every "
     "ordinary blip raises it and the next real one is ignored",
     [("FIRESTORE_OUTAGE_SPEAKS_AFTER_S = 60.0",
       "FIRESTORE_OUTAGE_SPEAKS_AFTER_S = 5.0")],
     [T_OUT]),
    ("F7", "over", "⛔⛔ the alarm repeats on every retry — the 4,921-line wall "
     "this wave exists to remove",
     [("FIRESTORE_OUTAGE_REPEAT_S = 300.0",
       "FIRESTORE_OUTAGE_REPEAT_S = 0.0")],
     [T_OUT]),
    ("F8", "under", "the repeat gate is dropped entirely",
     [("    if last_spoken_ago is not None:",
       "    if False and last_spoken_ago is not None:")],
     [T_OUT]),
    ("F9", "under", "the blip gate is dropped, which is F6 by another route",
     [("    if elapsed < float(speaks_after_s):\n        return []",
       "    if False:\n        return []")],
     [T_OUT]),
    ("F10", "over", "⛔⛔ spoke_at is stamped even when nothing was said, so the "
     "FIRST real alarm is suppressed for five minutes",
     [("                if _notice:\n                    spoke_at = time.time()",
       "                spoke_at = time.time()")],
     [T_OUT]),
    ("F11", "under", "the notice drops to WARN — a machine that cannot run "
     "anything, filed with the retries",
     [("                for _line in _notice:\n                    log(_line, \"ERROR\")",
       "                for _line in _notice:\n                    log(_line, \"WARN\")")],
     [T_OUT]),

    # ══ what the outage says ═══════════════════════════════════════════
    ("F12", "under", "it stops saying the pairing is fine, so the reader's "
     "first move is to re-pair — which cannot help and costs the pairing",
     [("        f\"[firestore] While that is true the web app shows this computer \"\n        f\"offline and any research fired at it will not arrive here. Your \"\n        f\"pairing is fine — there is nothing to re-pair.\",",
       "        f\"[firestore] Firestore is unavailable.\",")],
     [T_OUT]),
    ("F13", "under", "it stops naming the causes and the one command that "
     "distinguishes them",
     [("        f\"[firestore] Check it with:  nslookup {host}  — then leave this \"",
       "        f\"[firestore] Try again later.  {host}  — then leave this \"")],
     [T_OUT]),
    ("F14", "under", "it stops naming how long and how many attempts, so a "
     "blip and a dead network read identically again",
     [("        f\"[firestore] This machine cannot reach {host} — \"\n        f\"{_outage_duration_text(elapsed)} of failed reconnects \"\n        f\"({n} attempt{'' if n == 1 else 's'}).\",",
       "        f\"[firestore] This machine cannot reach {host}.\",")],
     [T_OUT]),
    ("F15", "under", "the lines are joined into one string, so every line after "
     "the first loses its timestamp and level",
     [("    return [\n        f\"[firestore] This machine cannot reach {host} — \"",
       "    return [\"\\n\".join([\n        f\"[firestore] This machine cannot reach {host} — \"")],
     [T_OUT]),

    # ══ the aegis pulse ════════════════════════════════════════════════
    ("F16", "under", "⛔ the pulse claims a watch is being kept while the "
     "machine is cut off — the exact line the new owner's log kept printing",
     [("    if down_for is not None:", "    if False:")],
     [T_OUT, T_SERVE]),
    ("F17", "under", "a client that JUST went (down_for=0.0) reads as healthy — "
     "a falsy check putting the lie straight back",
     [("    if down_for is not None:", "    if down_for:")],
     [T_OUT]),
    # ⛔ F18-F20 RE-ANCHORED 2026-08-19. The pulse gained a widening emission
    # cadence and an uptime, so the line grew a `{note}` suffix and the loop body
    # de-indented one level out of its old `if not running:` block. Every premise
    # is unchanged.
    ("F18", "under", "the broken pulse stops saying what it costs the user",
     [("                f\"{_outage_duration_text(down_for)}; the web app shows this \"\n                f\"computer offline and runs fired at it will not arrive{note}\")",
       "                f\"{_outage_duration_text(down_for)}\")")],
     [T_OUT, T_NOISE]),
    ("F19", "under", "the broken pulse is logged at INFO, invisible in a level "
     "filter",
     [("                    ), \"WARN\" if _cut_off else \"INFO\")",
       "                    ), \"INFO\")")],
     [T_OUT, T_NOISE]),
    ("F20", "under", "the pulse loop stops reading the real client state",
     [("                    _cut_off = _firebase_db is None",
       "                    _cut_off = False")],
     [T_OUT, T_NOISE]),
    ("F20b", "under", "⛔⛔ the pulse loses its cadence and goes back to one line "
     "a minute — 2,274 and 2,754 lines in the two real machine tails",
     [("                    _emit, _dropped = _quiet.consider(\"aegis-pulse\", _state)",
       "                    _emit, _dropped = True, 0")], [T_NOISE]),
    ("F20c", "over", "⛔⛔ the TICK widens with the emission, so a broken watch is "
     "reported up to an hour after Firestore goes — the alarm this loop exists for",
     # ⛔ `await asyncio.sleep(60)` alone matches twice in research.py, so the
     # anchor carries the line that follows it. A two-hit anchor measures nothing
     # and reports a kill.
     [("                    await asyncio.sleep(60)\n"
       "                    if _QUEUE_STATE.get(\"running\"):",
       "                    await asyncio.sleep(\n"
       "                        60 * max(1, _quiet.seen(\"aegis-pulse\") // 5))\n"
       "                    if _QUEUE_STATE.get(\"running\"):")],
     [T_NOISE]),
    # ⛔ F20d RE-ANCHORED 2026-08-22. Its anchor was a bare
    # `if _QUEUE_STATE.get("running"):` at one indent, and wave 5's broken-install
    # stand-down added a second line identical to it — so the anchor matched twice
    # and measured nothing. Widened with the `await asyncio.sleep(60)` above it,
    # the same prefix F20c already uses; the premise is unchanged.
    ("F20d", "under", "a pipeline run resets the cadence, so every long run is "
     "followed by another minutely burst",
     [("                    await asyncio.sleep(60)\n"
       "                    if _QUEUE_STATE.get(\"running\"):",
       "                    await asyncio.sleep(60)\n"
       "                    if _QUEUE_STATE.get(\"running\") and _quiet.consider(\n"
       "                            \"aegis-pulse\", \"running\") and True:")],
     [T_NOISE]),
    ("F20e", "under", "the uptime clock never restarts, so a pulse reports an "
     "uptime from before the outage it is meant to reveal",
     [("                        _state_since = time.time()", "                        pass")],
     [T_NOISE]),
    ("F20f", "under", "the pulse stops carrying its uptime, so an hour-apart line "
     "cannot tell a continuous watch from a restart",
     [("                        up_for=None if _cut_off else (time.time() - _state_since),",
       "                        up_for=None,")], [T_NOISE]),
    ("F20g", "under", "a suppressed repeat is discarded instead of counted, so "
     "'this happened 2,274 times' becomes 'this happened'",
     [("                        suppressed=_dropped,", "                        suppressed=0,")],
     [T_NOISE]),

    # ══ the retry line and the recovery line ═══════════════════════════
    ("F21", "under", "⛔ the retry line goes back to being identical at attempt "
     "1 and attempt 4,921",
     [("                log(f\"[reconnect] Firestore unreachable for \"\n                    f\"{_outage_duration_text(_down_for)} (attempt {attempts}) — \"\n                    f\"retrying in {wait}s\", \"WARN\")",
       "                log(f\"[reconnect] Firestore still unreachable — retrying init in {wait}s\", \"WARN\")")],
     [T_OUT]),
    ("F22", "under", "attempts is the backoff index again, which stops climbing "
     "once the ladder caps",
     [("            attempts += 1\n            # Snapshot before the rebuild",
       "            attempts = idx\n            # Snapshot before the rebuild")],
     [T_OUT]),
    ("F23", "under", "⛔ the clock is read AFTER the rebuild that clears it, so "
     "every recovery reports 0s — my own first draft",
     [("            _down_started = _firestore_down_since_ts\n            ok = await asyncio.to_thread(init_firebase)",
       "            ok = await asyncio.to_thread(init_firebase)\n            _down_started = _firestore_down_since_ts")],
     [T_OUT]),
    ("F24", "under", "recovery is never announced, so the last word the log has "
     "on the subject is the alarm",
     [("                if spoke_at is not None:\n                    # We told the operator this machine was cut off.",
       "                if False:\n                    # We told the operator this machine was cut off.")],
     [T_OUT]),
    ("F25", "over", "recovery is announced for a blip that never raised an "
     "alarm — an all-clear for a siren nobody heard",
     [("                if spoke_at is not None:\n                    # We told the operator this machine was cut off.",
       "                if True:\n                    # We told the operator this machine was cut off.")],
     [T_OUT]),
    ("F26", "under", "init goes back to calling every outage transient",
     [("        log(f\"Firestore init: could not reach Google ({type(_net_err).__name__}: \"\n            f\"{_net_err}) — retrying\", \"WARN\")",
       "        log(f\"Firestore init: transient network error ({type(_net_err).__name__}: {_net_err}) — will retry\", \"WARN\")")],
     [T_OUT]),
    ("F27", "over", "the revoked-vs-transient classification is dropped along "
     "with the word — the relink path would never run",
     [("        log(f\"Firestore init: could not reach Google ({type(_net_err).__name__}: \"\n            f\"{_net_err}) — retrying\", \"WARN\")\n        _firebase_down_reason = \"transient\"",
       "        log(f\"Firestore init: could not reach Google ({type(_net_err).__name__}: \"\n            f\"{_net_err}) — retrying\", \"WARN\")")],
     [T_OUT]),

    # ══ duration rendering ═════════════════════════════════════════════
    ("F28", "under", "durations render as raw seconds, so one outage reads "
     "differently in each message that mentions it",
     [("    if s < 60:\n        return f\"{s}s\"\n    if s < 3600:\n        return f\"{s // 60}m{s % 60:02d}s\"",
       "    if s < 3600:\n        return f\"{s}s\"")],
     [T_OUT]),
    ("F29", "under", "minutes lose their zero-padded seconds, so 1m2s and 1m20s "
     "are one keystroke apart in a log sweep",
     [("        return f\"{s // 60}m{s % 60:02d}s\"",
       "        return f\"{s // 60}m{s % 60}s\"")],
     [T_OUT]),
    ("F30", "under", "a junk duration raises instead of rendering, taking the "
     "whole pulse down with it",
     [("    try:\n        s = max(0, int(float(seconds or 0)))\n    except (TypeError, ValueError):\n        s = 0",
       "    s = max(0, int(float(seconds or 0)))")],
     [T_OUT]),
]

# Y20 needs a real deletion, not a no-op; define it here so the table above
# stays readable.
MUTANTS = [m for m in MUTANTS if m[0] != "Y20"] + [
    ("Y20", "under", "⛔ [5/5] Ready stops reporting the capacity it is calling "
     "ready — the new owner's exact screen",
     [('        print(f"  {_c(_OK, \'✓\')}  {_ready_cap} browser {_ready_profiles} "\n'
       '              f"{_c(_DIM, f\'— {_ready_cap} concurrent run {_ready_slots}\')}")',
       '        pass')],
     [T_YN]),
]


# ══ the stdlib loggers nobody was listening to ═════════════════════════
MUTANTS += [
    ("B1", "under", "⛔⛔ the bridge is never installed — 22,758 lines back to "
     "bare stderr and every DEBUG/INFO back on the floor",
     [("def main():\n    # Before anything else can log:",
       "def main():\n    _skip_bridge = True\n    # Before anything else can log:"),
      # Re-anchored 2026-08-18: wave 2 installs the crash hook on the next
      # line, so the old "\n\n    # Super Agent" anchor stopped matching. The
      # ratchet caught it the same run.
      ("    _install_stdlib_log_bridge()\n    # And before anything can CRASH:",
       "    pass\n    # And before anything can CRASH:")],
     [T_BRIDGE]),
    ("B2", "under", "three of the six modules drop off the list and log into "
     "the void again",
     # Re-anchored 2026-08-18: wave 2's telemetry module joined the list.
     [("_BRIDGED_LOGGERS = (\"auth\", \"vision\", \"selfheal\", \"narrate\", \"telemetry\")",
       "_BRIDGED_LOGGERS = (\"auth\",)")],
     [T_BRIDGE]),
    # ⛔ B3 RE-ANCHORED 2026-08-22. The installer gained a second, third-party
    # logger with a level of its own (`google.api_core.bidi` at WARNING — the
    # only thing that says a Firestore listener has died), so the level is no
    # longer one `setLevel` line. The PREMISE is unchanged: hold OUR loggers
    # above DEBUG and the pairing poll's only account of a network failure
    # disappears again.
    ("B3", "under", "⛔ the level goes to INFO, so the pairing poll's only "
     "account of a network failure disappears again",
     [("((n, logging.DEBUG) for n in names)", "((n, logging.INFO) for n in names)")],
     [T_BRIDGE]),
    ("B4", "under", "not idempotent — a second call doubles every line",
     [("        if any(isinstance(h, _StdlibLogBridge) for h in lg.handlers):\n            continue",
       "        if False:\n            continue")],
     [T_BRIDGE]),
    ("B5", "under", "propagation left on, so a future root config double-prints "
     "everything",
     [("        lg.propagate = False\n        installed.append(name)",
       "        installed.append(name)")],
     [T_BRIDGE]),
    ("B6", "under", "levels speak the stdlib's vocabulary instead of this "
     "file's, so every WARN filter misses half the lines",
     [("        logging.WARNING: \"WARN\",", "        logging.WARNING: \"WARNING\",")],
     [T_BRIDGE]),
    ("B7", "under", "CRITICAL renders as INFO — the loudest level in the "
     "standard library, filed as routine",
     [("        logging.CRITICAL: \"ERROR\",", "        logging.NOTSET: \"ERROR\",")],
     [T_BRIDGE]),
    ("B8", "under", "the traceback is dropped, leaving a message with no cause",
     [("            if record.exc_info:", "            if False:")],
     [T_BRIDGE]),
    ("B9", "under", "⛔ the record is printed as ONE multi-line line, which is "
     "how a log grows orphan lines with no timestamp and no level",
     [("            for line in (text.splitlines() or [\"\"]):\n                log(line, level)",
       "            log(text, level)")],
     [T_BRIDGE]),
    ("B10", "under", "the logger name is dropped, so six modules share one "
     "stream with nothing to tell them apart",
     [("            text = f\"[{record.name}] {record.getMessage()}\"",
       "            text = record.getMessage()")],
     [T_BRIDGE]),
    ("B11", "under", "the raw format string is logged instead of the rendered "
     "message, so every %s stays a literal %s",
     [("            text = f\"[{record.name}] {record.getMessage()}\"",
       "            text = f\"[{record.name}] {record.msg}\"")],
     [T_BRIDGE]),
    ("B12", "over", "⛔ a bad format string escapes emit() and takes the "
     "process down — a logging call that can kill the thing it reports on",
     [("        except Exception:\n            self.handleError(record)",
       "        except ValueError:\n            self.handleError(record)")],
     [T_BRIDGE]),
    ("B13", "under", "the bridge is installed after the first thing that can log",
     [("    _install_stdlib_log_bridge()\n    # And before anything can CRASH:",
       "    # And before anything can CRASH:"),
      ("    _migrate_state_to_home()",
       "    _migrate_state_to_home()\n    _install_stdlib_log_bridge()")],
     [T_BRIDGE]),
    ("B14", "under", "uvicorn's dictConfig is allowed to disable the loggers it "
     "did not name, silencing the bridge inside --serve only",
     [("        \"disable_existing_loggers\": False,", "        \"disable_existing_loggers\": True,")],
     [T_BRIDGE]),

    # ══ --doctor and the remedies ══════════════════════════════════════
    ("D1", "under", "⛔⛔ doctor stops asking which failure it was — a "
     "DNS-blocked owner is told their token is revoked, again",
     [("    elif _firebase_down_reason == \"transient\":",
       "    elif False:")],
     [T_DOC]),
    ("D2", "over", "⛔ the network branch swallows the revoked case too, so an "
     "owner who really did reset is told to check their firewall forever",
     [("    elif _firebase_down_reason == \"transient\":", "    elif True:")],
     [T_DOC]),
    # ⛔ RE-ANCHORED SAME DAY, and the anchor sweep is what caught it: the
    # network branch grew a real triage an hour after this mutant was written,
    # and its old `manual_actions.append(f"nslookup …")` line moved into the
    # verdict's fallback. The invariant is unchanged — the network branch must
    # never hand back "re-pair" — so only the literal moved.
    ("D3", "under", "the network branch tells them to re-pair anyway — "
     "spending a working pairing to fix a network",
     [("        manual_actions.extend(_verdict[\"actions\"] or [",
       "        manual_actions.append(\"Run `python research.py --pair`\")\n        manual_actions.extend([")],
     [T_DOC]),
    ("D4", "under", "the network verdict stops saying the pairing is fine, "
     "which is the sentence that stops the reader re-pairing",
     [("              \"the network, not your pairing — nothing here needs re-pairing\")",
       "              \"connectivity problem\")")],
     [T_DOC]),
    ("D5", "under", "the remedy is requirements.txt again, on installs that "
     "have never had one",
     [("    if _is_source_checkout():\n        return \"pip install -r requirements.txt\"\n    return \"pipx install --force superresearch\"",
       "    return \"pip install -r requirements.txt\"")],
     [T_DOC]),
    ("D6", "over", "the remedy is pipx even in a source checkout, where it "
     "would install over the tree being developed",
     [("    if _is_source_checkout():\n        return \"pip install -r requirements.txt\"\n    return \"pipx install --force superresearch\"",
       "    return \"pipx install --force superresearch\"")],
     [T_DOC]),
    ("D7", "under", "the installed remedy drops --force, so pipx no-ops and "
     "exits 0 while changing nothing",
     [("    return \"pipx install --force superresearch\"",
       "    return \"pipx install superresearch\"")],
     [T_DOC]),
    ("D8", "under", "the supervisor abort points at a requirements.txt under "
     "the log directory again — a path that exists nowhere",
     [("                f\"{python_exe}, so this machine cannot start. Repair it with: \"\n                f\"{_remedy_reinstall()}. \"",
       "                f\"{python_exe}. Run: \\\"{python_exe}\\\" -m pip install -r \\\"{_log_dir / 'requirements.txt'}\\\". \"")],
     [T_DOC]),
    ("D9", "under", "the abort stops saying the machine will not start",
     [("so this machine cannot start. Repair it with: ", "Repair it with: ")],
     [T_DOC]),
    ("D10", "under", "the patchright failure goes back to asking the reader a "
     "question instead of answering one",
     [("            _fail(\"patchright imports here but not in a fresh subprocess\",\n                  f\"same interpreter ({sys.executable}) — a partial or broken install\")",
       "            _fail(\"patchright module not importable in subprocess\", \"venv mismatch?\")")],
     [T_DOC]),
    ("D11", "under", "the missing QR library is a WARN with an unrunnable "
     "remedy again, mid-pairing-screen",
     [("            log(\"    QR image skipped (the qrcode library is not installed) — \"\n                \"type the code below instead; nothing else is affected.\", \"INFO\")",
       "            log(\"    qrcode lib missing — pip install -r requirements.txt\", \"WARN\")")],
     [T_DOC]),
]


_TEST_TIMEOUT_S = 300


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing. Three earlier waves had
        # already learned this and set the flag; it was never propagated.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
