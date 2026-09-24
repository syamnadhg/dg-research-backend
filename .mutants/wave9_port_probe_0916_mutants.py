"""Wave 9 — a probe that could not run is not a port that is free.

⛔⛔ THE EMPTY LIST WAS THE DEFECT, AND P3 IS THAT MUTANT. `_free_port` — the
blunt clear-the-port helper on the install and crash-respawn paths — ran
`lsof -ti :<port>` as its ONLY POSIX probe, inside a bare
`except Exception: return []`. Plenty of Linux images ship without lsof, and on
one of those `[]` meant both "nothing is listening" and "I could not look". Three
callers finished that sentence and every one of them picked the kinder reading:
the supervisor logged "freed nothing" and respawned into the identical
EADDRINUSE forever (a port conflict is deliberately exempt from the crash
tracker); the installer printed its "Cleared port 8000" line on success only, so
a probe that never ran left no line at all; `--doctor` said "Port 8000 not bound
— API unreachable" about a port it had never managed to examine.

⛔⛔ THE TWO QUERIES WERE DIFFERENT AND ONE WAS WRONG, AND P2 IS THAT MUTANT.
`_port_holders` asked `lsof -nP -iTCP:<port> -sTCP:LISTEN -t` — listeners only.
`_free_port` asked `lsof -ti :<port>`, which matches any socket whose LOCAL **or
REMOTE** port is that number and applies no LISTEN filter at all, so the path
that FORCE-KILLS what it finds would kill a process merely holding an outbound
connection to somebody else's port 8000. There is one query now and it is the
listener one.

⭐ THE OTHERS WORTH READING:
  P1  — the psutil branch goes and lsof is the only probe again. This is the
        original defect in its purest form: on a box WITH psutil and WITHOUT
        lsof the function can no longer answer at all.
  P4  — the fallback is gated on psutil RAISING instead of on psutil finding
        nothing. psutil hands back LISTEN rows it could not attribute with
        `pid=None` (macOS without root, routinely), and those rows are dropped
        — so a held port comes back empty from a source that never raised, and
        the one probe sees LESS than the two it replaced. Its killer did not
        exist; it was added with this harness, see OWN PINS below.
  P7  — the self-skip exists in BOTH probe branches and only the psutil one was
        driven. Handing our own pid back to `_free_port` is the backend
        force-killing itself at boot, on exactly the lsof-only images this wave
        is about. Its killer did not exist either.
  F3  — an OVER-correction, and the one the lane's own docstring refuses by
        name: `_free_port` starts honouring `_port_holders`' `ours` flag and
        stops clearing strangers. It reads like a safety fix and it silently
        changes the kill policy of the install and crash-respawn paths, which
        is a decision for the owner and not a side effect of swapping probes.
  H4  — the other over-correction: "unknown" refuses at once instead of waiting
        the settle window out. A socket in TIME_WAIT clears on its own, and that
        is true whether or not we could see who left it; refusing there turns a
        self-healing boot into a hard stop.
  C1  — the `unknown` branch in `run_server` goes and `stuck` widens to cover
        it. That is where this state used to arrive, and "still held after
        stopping the earlier backend" tells a person we stopped something we
        never even saw.
  C4  — the supervisor fetches `_probed` and never consults it. The flag is the
        whole fix on the path where the silence was actually paid for.

⛔ DELIBERATELY ABSENT — recorded so the next reader does not re-add them:
  * "the refusal's WORDING changes". Every guard on the three new copies is a
    source-inspection test, and this repo's rule is never to assert on prose
    through one. A reworded refusal would be a guaranteed survivor that measures
    the guards' shape, not the code. The mutants here make the copy VANISH
    (C1/C2/C3, C6) or go un-actionable (C3/C5/C7), which is what the guards
    actually claim.
  * "the installer's `elif not _port_probed:` becomes a bare `else:`" — it dies
    on the identical assertion as C6 and tells the reader nothing C6 does not.
    One reversion of that branch is enough.
  * "`_free_port` stops killing at all". `_kill_pids` removed is not a wave-9
    reversion; it deletes an eight-week-old feature that four suites already
    cover, so it would measure those suites rather than this lane. F3 is the
    scope question this lane actually raises and it is here.
  * "the Windows netstat branch loses its LISTENING filter". No guard drives
    the Windows branch on any machine in this project, so it could only be a
    survivor. Filed, not built: the pin would need a netstat fixture, which is
    wave-10 work, not a mutant.

⭐ OWN PINS ADDED WITH THIS HARNESS (tests/test_serve_port_reclaim_0810.py):
  test_the_shell_tool_is_tried_whenever_psutil_FOUND_nothing  → kills P4
  test_the_shell_fallback_does_not_report_us_either           → kills P7
Nothing already in either suite could fail on those two mutants: every other
case has psutil RAISING (so a fallback gated on the exception still opens) or
drives the shell branch with somebody else's pid.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/wave9_port_probe_0916_mutants.py
  .venv/bin/python .mutants/wave9_port_probe_0916_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The two files this wave owns, plus the two neighbours that read the same
# helpers — the doctor's port row and 7.9's `_port_holders` coverage. The
# neighbours are here so a mutant that breaks THEM is not reported clean; the
# -k filter below is what keeps them out of the per-mutant runs.
SUITES = ("tests/test_port_probe_0916.py "
          "tests/test_serve_port_reclaim_0810.py "
          "tests/test_doctor_network_truth_0817.py "
          "tests/test_stretch7_0902.py")

MINE = (
    # tests/test_port_probe_0916.py — the lane's own file
    "probe_that_could_not_run or probe_that_ran_and_found_nothing or "
    "psutil_answering_survives or shell_tool_answering_survives or "
    "unprobeable_platform or never_in_our_own_answer or only_LISTENERS_count or "
    "free_port_tells_the_two_empties or back_compat_alias or "
    "blunt_path_still_kills or OUTBOUND_connection or "
    "every_caller_reads_the_probe_flag or stops_saying_freed_nothing or "
    "installer_says_something or port_holders_tells_the_two_empties or "
    "doctors_could_not_look or unknown_not_stuck or "
    "TIME_WAIT_socket_still_clears or identifiable_holder_is_unaffected or "
    "serve_refuses_with_its_own_words or "
    # ⛔ Wave 10.9 (09-21, the Windows netstat fix) added thirteen guards to this
    # file after the harness was written: the parse on four languages of
    # Windows, the real probe against a netstat stand-in, and the German
    # `_free_port`. Every one of them runs the probe this harness mutates.
    "windows_parse or translated_state_column or windows_probe or "
    "translated_windows or windows_netstat or german_windows or "
    # tests/test_serve_port_reclaim_0810.py — the 08-10 reclaim suite, which
    # this wave re-pointed at `_listening_pids`, plus the two pins added with
    # this harness.
    "own_backend_is_recognised or everything_else_is_NOT_ours or "
    "argv_is_accepted_as_a_list or recognition_needs_BOTH or "
    "free_port_is_left_alone or stale_copy_of_ours_is_stopped or "
    "FOREIGN_holder_is_refused or MIXED_set_is_refused or WORKING_is_refused or "
    "QUEUED_work_too or IDLE_holder_is_still_reclaimed or "
    "immovable_is_reported_stuck or waited_out_not_killed or "
    "never_clears_is_stuck or boot_no_longer_binds_anyway or "
    "boot_refuses_on_a_foreign_holder or boot_refuses_when_the_port_stays_stuck or "
    "refusal_names_the_holder or refusal_tells_them_how_to_look or "
    "port_check_that_itself_fails or reclaim_runs_off_the_event_loop or "
    "signal_module_is_imported or holder_lookup_survives_both_sources or "
    "vanishes_mid_stop or we_never_signal_ourselves or "
    "psutil_FOUND_nothing or shell_fallback_does_not_report_us"
)

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one. Both owned files are checked, because P4 and P7's
# only killers live in the 08-10 file, not in the lane's own.
OWNED_FILES = ("tests/test_port_probe_0916.py",
               "tests/test_serve_port_reclaim_0810.py")

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The psutil attempt that opens `_listening_pids`. `psutil_ok` is named in one
#: function only, so these three lines are unique.
PSUTIL_TRY = ('    psutil_ok = False\n'
              '    try:\n'
              '        import psutil as _ps')
#: The row filter inside the psutil loop — the psutil copy of the self-skip.
PSUTIL_ROW = '            if conn.laddr.port != port or not conn.pid or conn.pid == me:'
#: The gate that decides whether the shell tool is asked at all. Anchored with
#: the two lines above it because `    if not pids:` alone occurs three times.
FALLBACK_GATE = ('    shell_ok = False\n'
                 '    plat = _supervisor_platform()\n'
                 '    if not pids:')
#: The ONE lsof query, listeners only. `"lsof", "-nP"` occurs once.
LSOF_QUERY = ('                r = _sp.run(\n'
              '                    ["lsof", "-nP", f"-iTCP:{_p}", "-sTCP:LISTEN", "-t"],\n'
              '                    capture_output=True, text=True, timeout=10,\n'
              '                )')
#: The shell copy of the self-skip. `if pid > 0 and pid != me:` appears in the
#: Windows branch too, so the anchor starts at the POSIX tokeniser.
SHELL_ROW = ('                for tok in (r.stdout or "").split():\n'
             '                    try:\n'
             '                        pid = int(tok.strip())\n'
             '                    except ValueError:\n'
             '                        continue\n'
             '                    if pid > 0 and pid != me:')
#: The signal itself — the raise that replaced the swallow.
PROBE_RAISE = ('    if not psutil_ok and not shell_ok:\n'
               '        raise _PortProbeUnavailable(\n'
               '            f"could not look at port {port} — " + ("; ".join(why) or "no source"))\n'
               '    return pids')
#: Just the message, for the mutant that keeps the raise and loses the port.
PROBE_MESSAGE = ('        raise _PortProbeUnavailable(\n'
                 '            f"could not look at port {port} — " + ("; ".join(why) or "no source"))')
#: `_free_port`'s handler — where "could not look" becomes `probed=False`.
FREE_PORT_CATCH = ('    try:\n'
                   '        pids = _listening_pids(port)\n'
                   '    except _PortProbeUnavailable:\n'
                   '        return [], False')
#: `_free_port`'s kill, which is deliberately NOT ownership-gated.
FREE_PORT_KILL = ('    if not pids:\n'
                  '        return [], True\n'
                  '    ordered = sorted(pids)\n'
                  '    _kill_pids(ordered)\n'
                  '    return ordered, True')
#: `_port_holders`' loop — the layer the doctor and the reclaim both read.
HOLDERS_LOOP = ('    holders = []\n'
                '    for pid in sorted(_listening_pids(port)):')
#: `_reclaim_port`'s answer when nothing could look: wait the socket out first,
#: then say the honest thing.
RECLAIM_UNKNOWN = ('        return ("free", []) if _wait_for_port_free(port, settle_s) '
                   'else ("unknown", [])')
#: `run_server`'s two refusals, and the line inside the new one that tells a
#: person how to look for themselves.
SERVE_STUCK = '    if _port_state == "stuck":'
SERVE_UNKNOWN = '    if _port_state == "unknown":'
SERVE_UNKNOWN_HINT = '        print(f"      Look yourself with:  {_port_holder_hint(port)}")'
SERVE_UNKNOWN_EXIT = ('        print("      Or start this backend on another port.\\n")\n'
                      '        raise SystemExit(3)')
#: The supervisor's branch on the probe flag, and its hint.
SUPERVISOR_FLAG = '                            if _probed:'
SUPERVISOR_HINT = '                                    f"{_port_holder_hint(_w_port)}",'
#: The installer's "could not check" branch, and its hint.
INSTALLER_BRANCH = '        elif not _port_probed:'
INSTALLER_HINT = ("            print(f\"  {_c(_DIM, f'     If the backend does not start, "
                  "look yourself: {_port_holder_hint(8000)}')}\")")
#: The installer's call site — the one that unpacks the pair.
INSTALLER_CALL = '        port_squatters, _port_probed = _free_port_8000()'

MUTANTS = [
    # ═════════ P — `_listening_pids`, the one probe ══════════════════════════
    ("P1", "under",
     "⛔⛔ THE PSUTIL BRANCH GOES AND lsof IS THE ONLY PROBE AGAIN — the wave-9 "
     "defect in its purest form. On a box WITH psutil and WITHOUT lsof the "
     "function can no longer answer at all, which is the machine the original "
     "bug was reported from. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_psutil_answering_survives_a_missing_shell_tool — psutil says the "
     "port is free, lsof is absent, and the real code still answers `set()` "
     "while this one raises _PortProbeUnavailable",
     [(PSUTIL_TRY,
       '    psutil_ok = False\n'
       '    try:\n'
       '        raise ImportError("no psutil on this image")\n'
       '        import psutil as _ps')]),
    ("P2", "under",
     "⛔⛔ THE LISTEN FILTER GOES AND THE OLD `lsof -ti :<port>` IS BACK. That "
     "query matches any socket whose LOCAL **or REMOTE** port is this number, so "
     "the path that force-kills what it finds would kill a process merely "
     "holding an outbound connection to somebody else's port 8000. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_free_port_no_longer_kills_an_OUTBOUND_connection, which captures the "
     "argv and asserts -sTCP:LISTEN is in it and -ti is not",
     [(LSOF_QUERY,
       '                r = _sp.run(\n'
       '                    ["lsof", "-ti", f":{_p}"],\n'
       '                    capture_output=True, text=True, timeout=10,\n'
       '                )')]),
    ("P3", "under",
     "⛔⛔ THE SIGNAL IS SWALLOWED BACK INTO AN EMPTY SET. Both sources gone "
     "returns `set()`, which is the same value a probe that RAN and found "
     "nothing returns — the bare `except Exception: return []` restored one "
     "layer in, and every caller downstream reads the kinder half. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_a_probe_that_could_not_run_raises_instead_of_answering_empty",
     [(PROBE_RAISE, '    return pids')]),
    ("P4", "under",
     "⛔⛔ THE FALLBACK IS GATED ON psutil RAISING, NOT ON psutil FINDING "
     "NOTHING. psutil hands back LISTEN rows it could not attribute with "
     "`pid=None` — macOS without root, routinely — and those rows are dropped, "
     "so a HELD port comes back empty from a source that never raised and the "
     "one probe sees less than the two it replaced. "
     "KILLED BY tests/test_serve_port_reclaim_0810.py::"
     "test_the_shell_tool_is_tried_whenever_psutil_FOUND_nothing, ADDED WITH "
     "THIS HARNESS because nothing else in either suite could fail on it",
     [(FALLBACK_GATE,
       '    shell_ok = False\n'
       '    plat = _supervisor_platform()\n'
       '    if not psutil_ok:')]),
    ("P5", "under",
     "⛔ the refusal stops naming the port it could not look at. `--doctor` "
     "catches this and prints only the exception's TYPE, so the message is the "
     "only place the port survives into a log a person reads on a multi-worker "
     "box where four ports are in play. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_the_doctors_could_not_look_handler_can_finally_fire, which asserts "
     "the port number is in str(exc)",
     [(PROBE_MESSAGE,
       '        raise _PortProbeUnavailable("could not look")')]),
    ("P6", "under",
     "⛔⛔ THE PSUTIL BRANCH REPORTS THE CALLER'S OWN PID. In some restart paths "
     "this process is the one listening, and `_free_port` force-kills what it "
     "is handed — this is the backend killing itself at boot. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_we_are_never_in_our_own_answer",
     [(PSUTIL_ROW,
       '            if conn.laddr.port != port or not conn.pid:')]),
    ("P7", "under",
     "⛔⛔ THE SHELL BRANCH REPORTS THE CALLER'S OWN PID — the same defect as P6 "
     "in the copy of the self-skip nobody was driving, and it is the branch that "
     "runs on exactly the lsof-only images this wave is about. A safety gate "
     "that exists twice with one half measured is this repo's recorded shape "
     "for losing a fix. "
     "KILLED BY tests/test_serve_port_reclaim_0810.py::"
     "test_the_shell_fallback_does_not_report_us_either, ADDED WITH THIS "
     "HARNESS because nothing drove that branch with our own pid",
     [(SHELL_ROW,
       '                for tok in (r.stdout or "").split():\n'
       '                    try:\n'
       '                        pid = int(tok.strip())\n'
       '                    except ValueError:\n'
       '                        continue\n'
       '                    if pid > 0:')]),

    # ═════════ F — `_free_port`, the blunt path ══════════════════════════════
    ("F1", "under",
     "⛔⛔ \"I COULD NOT LOOK\" IS REPORTED AS A CLEAN PROBE THAT FOUND NOTHING. "
     "The raise survives and the handler lies about it, which puts the whole "
     "defect back at the layer every caller actually reads — the supervisor's "
     "\"freed nothing\", the installer's silence, one flag apart. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_free_port_tells_the_two_empties_apart, which compares the two calls "
     "and asserts they differ",
     [(FREE_PORT_CATCH,
       '    try:\n'
       '        pids = _listening_pids(port)\n'
       '    except _PortProbeUnavailable:\n'
       '        return [], True')]),
    ("F2", "under",
     "⛔ a call site binds the pair to ONE name again. HELPER PINNED, CONSUMER "
     "NOT is how this repo loses fixes: `port_squatters` becomes the whole "
     "tuple, which is permanently truthy, and the installer's \"could not "
     "check\" branch can never be reached. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_every_caller_reads_the_probe_flag, which walks the AST for every "
     "_free_port/_free_port_8000 assignment and requires a 2-tuple target",
     [(INSTALLER_CALL, '        port_squatters = _free_port_8000()')]),
    ("F3", "over",
     "⛔⛔ AN OVER-CORRECTION THE LANE REFUSES BY NAME. `_free_port` starts "
     "honouring `_port_holders`' `ours` flag and stops clearing strangers. It "
     "reads like a safety fix and it silently changes the kill policy of the "
     "install and crash-respawn paths — where nothing of ours is running yet "
     "and the only question is whether the port is clear. Whether it SHOULD "
     "keep killing strangers is an open question for the owner; it is not a "
     "side effect of swapping probes. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_the_blunt_path_still_kills_what_it_finds",
     [(FREE_PORT_KILL,
       '    if not pids:\n'
       '        return [], True\n'
       '    _own = {h["pid"] for h in _port_holders(port) if h["ours"]}\n'
       '    ordered = sorted(pids & _own)\n'
       '    if not ordered:\n'
       '        return [], True\n'
       '    _kill_pids(ordered)\n'
       '    return ordered, True')]),

    # ═════════ H — `_port_holders` and `_reclaim_port`, the careful path ═════
    ("H1", "under",
     "⛔⛔ `_port_holders` RE-SWALLOWS INTO []. This is the exact line the "
     "doctor's own handler was written for and could not fire against: `[]` is "
     "read as \"unbound — API unreachable\" by `_port_row_verdict` and as "
     "\"nothing identifiable, wait it out\" by `_reclaim_port`. One missing "
     "binary, two confident wrong answers. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_port_holders_tells_the_two_empties_apart",
     [(HOLDERS_LOOP,
       '    holders = []\n'
       '    try:\n'
       '        _found = sorted(_listening_pids(port))\n'
       '    except _PortProbeUnavailable:\n'
       '        return []\n'
       '    for pid in _found:')]),
    ("H2", "under",
     "⛔⛔ \"unknown\" COMES OUT AS \"stuck\" AGAIN — where it used to arrive. "
     "The stuck refusal's words are \"still held after stopping the earlier "
     "backend\", and nothing was stopped, or even identified. A probe that could "
     "not run is not a holder that would not let go. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_reclaim_says_unknown_not_stuck_when_nothing_could_look",
     [(RECLAIM_UNKNOWN,
       '        return ("free", []) if _wait_for_port_free(port, settle_s) '
       'else ("stuck", [])')]),
    ("H3", "under",
     "⛔⛔ THE UNPROBEABLE PORT IS REPORTED AS FREE. The settle wait goes with "
     "it, so `run_server` has nothing to branch on and binds into the "
     "EADDRINUSE this whole path exists to explain — the outcome the reclaim "
     "replaced, reached through the new code. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_reclaim_says_unknown_not_stuck_when_nothing_could_look",
     [(RECLAIM_UNKNOWN, '        return "free", []')]),
    ("H4", "over",
     "⛔ AN OVER-CORRECTION: \"unknown\" refuses at once instead of waiting the "
     "settle window out. A socket left in TIME_WAIT clears on its own, and that "
     "is true whether or not we could see who left it — refusing there turns a "
     "boot that heals itself in twelve seconds into a hard stop, on every "
     "lsof-less image, for a port that was never really held. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_a_TIME_WAIT_socket_still_clears_itself_when_the_probe_failed",
     [(RECLAIM_UNKNOWN, '        return "unknown", []')]),

    # ═════════ C — the copy: three refusals the lane added ═══════════════════
    ("C1", "under",
     "⛔⛔ THE `unknown` BRANCH GOES AND `stuck` WIDENS TO COVER IT — where this "
     "state used to arrive. The person reads \"still held after stopping the "
     "earlier backend (pid unknown)\" about a machine where nothing was stopped "
     "and nothing was seen, which is a sentence that sends them hunting a "
     "process that may not exist. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_serve_refuses_with_its_own_words_when_it_could_not_look, whose first "
     "assertion is that run_server still branches on the state at all",
     [(SERVE_STUCK, '    if _port_state in ("stuck", "unknown"):'),
      (SERVE_UNKNOWN, '    if False:')]),
    ("C2", "under",
     "⛔⛔ THE REFUSAL PRINTS AND BINDS ANYWAY. \"It noticed, said so, and let "
     "the confusing failure happen regardless\" is the 08-10 finding this whole "
     "path replaced; reaching it through the newest branch is the same defect "
     "with better copy in front of it. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_serve_refuses_with_its_own_words_when_it_could_not_look, which "
     "RUNS the branch (wave 10.10) and requires it to exit 3",
     [(SERVE_UNKNOWN_EXIT,
       '        print("      Or start this backend on another port.\\n")')]),
    ("C3", "under",
     "⛔ THE REFUSAL BECOMES A DEAD END. It still refuses and still explains, "
     "and it no longer says how to look — and the tool differs per platform, "
     "which is the one thing a person on an lsof-less image cannot guess. An "
     "unactionable refusal is where the raw EADDRINUSE left them. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_serve_refuses_with_its_own_words_when_it_could_not_look, which "
     "RUNS the branch and requires the platform's hint to be PRINTED",
     [(SERVE_UNKNOWN_HINT,
       '        print("      Nothing here can say what is on it.")')]),
    ("C4", "under",
     "⛔⛔ THE SUPERVISOR FETCHES `_probed` AND NEVER CONSULTS IT, so every "
     "respawn logs \"freed nothing\" — including the one where nothing could "
     "look. This is the path the silence was actually paid for on: the worker "
     "had ALREADY proved the port was occupied, and a port conflict is exempt "
     "from the crash tracker, so it respawns into the same EADDRINUSE forever. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_the_supervisor_stops_saying_freed_nothing_when_it_could_not_look",
     [(SUPERVISOR_FLAG, '                            if True:')]),
    ("C5", "under",
     "⛔ the supervisor says nothing could look and not how to look. This log is "
     "the only trace a crash-looping worker leaves, and the tool that exists "
     "differs per platform — which is exactly what the operator on the box in "
     "the original report did not know. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_the_supervisor_stops_saying_freed_nothing_when_it_could_not_look, "
     "which RUNS the branch and requires this worker's hint in the log line",
     [(SUPERVISOR_HINT, '                                    "",')]),
    ("C6", "under",
     "⛔⛔ THE INSTALLER'S \"COULD NOT CHECK\" BRANCH NEVER FIRES, so it prints "
     "on success only again and a probe that never ran leaves no line at all — "
     "on the arming path, where the very next thing is a daemon-loop that will "
     "crash-loop on the bind we could not clear. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_the_installer_says_something_when_it_could_not_check",
     [(INSTALLER_BRANCH, '        elif not _port_probed and False:')]),
    ("C7", "under",
     "⛔ the installer says it could not check and not how to check. At install "
     "time there is no log to go back to and no run to inspect; the printed "
     "line is the whole record. "
     "KILLED BY tests/test_port_probe_0916.py::"
     "test_the_installer_says_something_when_it_could_not_check, which RUNS "
     "the lines and requires port 8000's hint to be PRINTED",
     [(INSTALLER_HINT,
       "            print(f\"  {_c(_DIM, '     If the backend does not start, "
       "try again in a moment.')}\")")]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> str | None:
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _digest() -> dict:
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}


def _pytest(kfilter: str | None) -> str:
    """'green' | 'red' | 'nothing-collected'."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    code = sh(args, cwd=ROOT, env=ENV).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(kfilter: str | None) -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: str | None) -> set:
    args = [sys.executable, "-B", "-m", "pytest", *files,
            "--collect-only", "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    out = sh(args, cwd=ROOT, env=ENV).stdout
    return {ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(" ")}


def _filter_misses(kfilter: str) -> set:
    return _collected(OWNED_FILES, None) - _collected(OWNED_FILES, kfilter)


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    kfilter = None if unfiltered else MINE

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — spot check, not a score.")
    print("scope: THE WHOLE SELECTION (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this wave's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS WAVE'S OWN GUARDS, so "
                  "any mutant only they could kill would report as a SURVIVOR:")
            for tid in sorted(missed):
                print(f"    {tid}")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(kfilter) or not run_tests(None):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green (filtered and whole)\n")

    path = ROOT / TARGET
    survivors, faults, flaky = [], [], []
    for mid, direction, why, edits in selected:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            try:
                compile(mutated, TARGET, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            _mark(mid)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. On disagreement,
            # run a third time and take the majority — reported separately,
            # because "the guards cannot see this" and "that run was noisy" are
            # different claims and collapsing them sends the next reader hunting
            # a defect that is not there.
            verdicts = [not run_tests(kfilter) for _ in range(SURVIVOR_CONFIRMATIONS)]
            flapped = len(set(verdicts)) > 1
            if flapped:
                verdicts.append(not run_tests(kfilter))
            killed = sum(verdicts) * 2 > len(verdicts)
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = (f"  ⚠ FLAPPED {sum(verdicts)}/{len(verdicts)} — tie broken by "
                    "majority" if flapped else "")
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
            elif flapped:
                flaky.append((mid, sum(verdicts), len(verdicts)))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in selected if m[1] == "over")
    scope = " [whole selection]" if unfiltered else " [own guards]"
    label = " (SPOT CHECK)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority — killed, "
              f"but this selection is not perfectly stable:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
