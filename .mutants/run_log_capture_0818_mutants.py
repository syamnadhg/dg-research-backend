"""Mutation harness for wave 2 step 1 — per-run and per-session log capture.

⛔⛔ WHAT THIS WAVE IS FOR. A new owner's machine lost DNS for
firestore.googleapis.com. The owner could not send us a log, because the only
account of the failure was 4,921 byte-identical WARNs inside a 44 MB file with
no dates in it, and the pairing output the user photographed reached no file at
all. Step 1 is the capture side: a folder per run, a file per interactive
command, a traceback that lands somewhere, and rotation so none of it becomes a
second unbounded copy.

⭐⭐ THE SHARPEST MUTANTS IN THIS FILE are the ones that leave a feature that
LOOKS present and cannot work:

  M1  — meta.json written only at disarm, so the run that DIED never appears.
        That is the founding case, and the whole reason meta is written at arm.
  W2  — `_patch_run_log_status` patches only a still-armed sink. The worker
        watchdog cancels the pipeline and AWAITS it before raising, so its
        handler always runs after the capture finalized: the verdict would
        never land, and every watchdog kill would read as a plain error.
  E1  — the emit_event tap moved BELOW `if not _tracks_dir: return`, so a run
        whose Firestore setup is the thing that failed mirrors no events, and
        absence reads as health.
  R1  — rotation only in the multi-worker branch. `load_worker_count()`
        defaults to 1, so that is a guard that cannot fire where users live.
  P2  — pruning without the live-sink guard deletes the folder of the run
        currently being written, which is the folder a bundle is about to want.
  C2  — the cap keeps the head and drops every tail segment, i.e. throws away
        the LAST line, which is a wedged pairing's entire diagnostic payload.

⭐ And the over-corrections, which is where a fix of this shape goes wrong:
  K3  — the id allow-list rejects everything, so every run lands in `local_`
        and the folder never names the run (the wave-2 lesson: a guard that
        fires on every honest input ships nothing).
  M5  — every meta reads as process-died, so live runs are called corpses.
  L3  — the write-through changes what `log()` prints.
  N5  — capture failure raises into the pipeline: a diagnostic that breaks the
        thing it diagnoses.
  R4  — rotation ignores size and rolls on every restart, deleting the
        previous session's log every time the supervisor comes up.
  X3  — the traceback is printed twice, rebuilding the wall this wave removes.
  S2  — `--serve` gets a session tee too: a second full copy of backend.log.

    python .mutants/run_log_capture_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_CAP = "tests/test_run_log_capture_0818.py"
T_BRIDGE = "tests/test_stdlib_log_bridge_0817.py"
T_SERVE = "tests/test_serve_cli_consistency.py"
ALL = [T_CAP, T_BRIDGE, T_SERVE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the folder key — the one place a topic could leak ═══════════════
    ("K1", "under", "⛔⛔ any string becomes the folder name, so a topic ships "
     "inside every support bundle",
     [('    safe = bool(_RUN_FOLDER_ID_RE.match(rid)) and not _RUN_ID_SUFFIX_RE.search(rid)',
       '    safe = True')],
     [T_CAP]),
    ("K2", "under", "⛔ the run_id tail is allowed again — a one-word topic "
     "survives safe_name as bare alphanumerics and becomes the key",
     [('    safe = bool(_RUN_FOLDER_ID_RE.match(rid)) and not _RUN_ID_SUFFIX_RE.search(rid)',
       '    safe = bool(_RUN_FOLDER_ID_RE.match(rid))')],
     [T_CAP]),
    ("K3", "over", "⛔ every honest id is rejected, so no folder ever names its "
     "run — a guard that fires on every real input",
     [('    key = rid if safe else "local"', '    key = "local"')],
     [T_CAP]),
    ("K4", "under", "a retry attempt is not marked, so the two attempts of one "
     "run are indistinguishable",
     [('    if attempt:\n        name = f"{name}_retry{int(attempt)}"',
       '    if False:\n        name = f"{name}_retry{int(attempt)}"')],
     [T_CAP]),
    ("K5", "under", "the folder-key function grows a run_id parameter again — "
     "the leak becomes representable",
     [('def _run_log_folder_name(research_id, started_utc, attempt=0) -> str:',
       'def _run_log_folder_name(research_id, started_utc, attempt=0, run_id=None) -> str:')],
     [T_CAP]),

    # ══ meta at arm, and deriving the corpse ═══════════════════════════
    ("M1", "under", "⛔⛔ THE FOUNDING CASE, RESTORED. meta.json is written only "
     "at disarm, so the run that DIED never appears in the index",
     [('        self.meta_path = self.dir / "meta.json"\n        self.write_meta("running")',
       '        self.meta_path = self.dir / "meta.json"')],
     [T_CAP]),
    ("M2", "under", "a meta still saying running is taken at its word — a "
     "corpse reads as a live run forever",
     [('    if status != "running":\n        return status',
       '    if True:\n        return status')],
     [T_CAP]),
    ("M3", "under", "⛔ pid liveness ALONE: a recycled pid relabels a dead run "
     "as running, which is how the dead run stays invisible",
     [('    return "process-died" if (pid_gone or aged_out) else "running"',
       '    return "process-died" if pid_gone else "running"')],
     [T_CAP]),
    ("M4", "under", "age alone: a run killed one second ago reads as running "
     "for the next six hours",
     [('    return "process-died" if (pid_gone or aged_out) else "running"',
       '    return "process-died" if aged_out else "running"')],
     [T_CAP]),
    ("M5", "over", "⛔ every run reads as process-died, so live runs are called "
     "corpses",
     [('    return "process-died" if (pid_gone or aged_out) else "running"',
       '    return "process-died"')],
     [T_CAP]),
    ("M6", "under", "the dead-run ceiling drops below the watchdog's own "
     "ceiling, so a long healthy run is relabelled dead mid-flight",
     [('RUN_LOG_DEAD_AFTER_SEC = 6 * 60 * 60', 'RUN_LOG_DEAD_AFTER_SEC = 60 * 60')],
     [T_CAP]),
    ("M7", "under", "warn/error counters never move, so the index cannot rank "
     "which run is worth opening",
     [('        if lvl.startswith("WARN"):', '        if False:')],
     [T_CAP]),

    # ══ the cap: head AND last line ════════════════════════════════════
    ("C1", "under", "the cap never engages — the per-run folder is a second "
     "unbounded copy of an unrotated stream",
     [('            elif self._written + n > self.max_bytes:', '            elif False:')],
     [T_CAP]),
    ("C2", "under", "⛔⛔ every tail segment is deleted, so the LAST line — a "
     "wedged pairing's whole payload — is what gets thrown away",
     [('        while len(self._live_segments) > self.keep:',
       '        while len(self._live_segments) > 0:')],
     [T_CAP]),
    ("C3", "over", "segments are never pruned, so the cap is decorative and the "
     "folder grows without bound",
     [('        while len(self._live_segments) > self.keep:', '        while False:')],
     [T_CAP]),
    ("C4", "under", "the head no longer says where the rest of the log went",
     [('                f"--- head capped at {self.max_bytes} bytes; the newest "\n'
       '                f"{self.keep} x {self.segment_bytes}-byte tail segments continue in "\n'
       '                f"{self.segment_path(nxt).name} ---\\n")',
       '                f"--- capped ---\\n")')],
     [T_CAP]),
    ("C5", "over", "a write into a closed or broken handle raises, taking the "
     "run down with the log",
     [('        except Exception:\n            # A log writer that raises takes the run down with it. Never.\n            pass',
       '        except Exception:\n            raise')],
     [T_CAP]),

    # ══ what the user actually saw ═════════════════════════════════════
    ("V1", "under", "⛔ carriage returns survive, so a two-minute spinner writes "
     "1,200 identical lines — the wave-1 wall rebuilt by its own fix",
     [('    text = line.split("\\r")[-1] if "\\r" in line else line', '    text = line')],
     [T_CAP]),
    ("V2", "under", "ANSI escapes are left in the file a human has to read",
     [('    return _ANSI_RE.sub("", text).rstrip()', '    return text.rstrip()')],
     [T_CAP]),
    ("V3", "over", "the FIRST frame is kept instead of the last, so the file "
     "records what was overwritten rather than what was on screen",
     [('    text = line.split("\\r")[-1] if "\\r" in line else line',
       '    text = line.split("\\r")[0] if "\\r" in line else line')],
     [T_CAP]),

    # ══ the tee ════════════════════════════════════════════════════════
    ("T1", "under", "⛔ the tee stops writing to the terminal — the branded pair "
     "UI disappears and only the file gets it",
     [('        n = self._stream.write(s)', '        n = len(s)')],
     [T_CAP]),
    ("T2", "over", "a mirror failure propagates, so a full disk crashes the "
     "pairing command it was added to document",
     [('        try:\n            self._mirror(s)\n        except Exception:\n            pass\n        return n',
       '        self._mirror(s)\n        return n')],
     [T_CAP]),
    ("T3", "under", "the tee stops delegating, so isatty/encoding answers change "
     "under every teed command",
     [('        return getattr(self._stream, name)',
       '        raise AttributeError(name)')],
     [T_CAP]),
    ("T4", "under", "the partial final line is dropped — which is the prompt a "
     "wedged pairing died on",
     [('            if self._buf.strip():\n                self._writer.write_line(_visible_text(self._buf))',
       '            if False:\n                self._writer.write_line(_visible_text(self._buf))')],
     [T_CAP]),
    ("T5", "under", "the spinner buffer is never collapsed, so a command that "
     "never prints a newline grows it without bound",
     [('        if len(self._buf) > 4096 and "\\r" in self._buf:', '        if False:')],
     [T_CAP]),

    # ══ log() write-through ════════════════════════════════════════════
    ("L1", "under", "⛔⛔ nothing reaches the run folder at all — the capture is "
     "present, armed, and empty",
     [('    _log_write_through(line, level)', '    pass')],
     [T_CAP]),
    ("L2", "under", "the reentrancy flag is never set, so a sink failure that "
     "logs recurses through log() forever",
     [('    _RUN_LOG_TLS.busy = True', '    _RUN_LOG_TLS.busy = False')],
     [T_CAP]),
    ("L3", "over", "⛔ the printed line changes shape — every downstream log "
     "parser and every copy test in this repo is built on that format",
     [('    line = f"[{ts}] [{level}] {msg}"', '    line = f"[{ts}] {level}: {msg}"')],
     [T_CAP, T_BRIDGE, T_SERVE]),
    ("L4", "under", "a failing sink propagates out of log(), so a full disk "
     "takes down the run instead of the log line",
     [('    try:\n        sink.note_line(line, level)\n    except Exception:\n        pass',
       '    try:\n        sink.note_line(line, level)\n    except KeyboardInterrupt:\n        pass')],
     [T_CAP, T_BRIDGE]),

    # ══ the emit_event tap ═════════════════════════════════════════════
    ("E1", "under", "⛔⛔ THE TAP MOVES BELOW THE GUARD. A run whose Firestore "
     "setup is the thing that failed mirrors nothing, and absence reads as health",
     # Re-anchored 2026-08-18: step 9 added the tier-1 tap beside this one, and
     # BOTH have to move for the mutant to be the defect it names.
     [('    _run_sink_note_event(event_type, phase, agent)\n    _tm_note_event(event_type, phase, agent)\n    if not _tracks_dir:\n        return',
       '    if not _tracks_dir:\n        return\n    _run_sink_note_event(event_type, phase, agent)\n    _tm_note_event(event_type, phase, agent)')],
     [T_CAP]),
    ("E2", "over", "⛔ the tap forwards **data, so free text re-enters a path "
     "built to carry names and numbers only",
     [('    _run_sink_note_event(event_type, phase, agent)',
       '    _run_sink_note_event(event_type, phase, data)')],
     [T_CAP]),
    ("E3", "under", "the event mirror is unbounded — a long run's meta grows "
     "until the folder is the problem",
     [('        if len(self.events) > RUN_LOG_EVENT_CAP:', '        if False:')],
     [T_CAP]),

    # ══ nesting: the pipeline awaits itself ════════════════════════════
    ("N1", "under", "⛔ a singleton instead of a stack: the #725 retry replaces "
     "its parent's sink and the outer run's tail goes nowhere",
     [('            _RUN_LOG_SINKS.append(sink)', '            _RUN_LOG_SINKS[:] = [sink]')],
     [T_CAP]),
    ("N2", "under", "disarm clears the whole stack, so the outer run never "
     "resumes after a retry finishes",
     [('            if sink in _RUN_LOG_SINKS:\n                _RUN_LOG_SINKS.remove(sink)',
       '            _RUN_LOG_SINKS.clear()')],
     [T_CAP]),
    ("N3", "under", "the retry no longer records its parent, so two folders sit "
     "side by side with nothing linking them",
     [('                parent_research_id=(parent.research_id if parent is not None else None),',
       '                parent_research_id=None,')],
     [T_CAP]),
    ("N4", "under", "re-entering one capture strands a sink on the stack and "
     "every later line in the process writes to a folder nobody finalizes",
     [('        if self.sink is not None:\n            return self.sink',
       '        if False:\n            return self.sink')],
     [T_CAP]),
    ("N5", "over", "⛔ capture failure raises into the pipeline — a diagnostic "
     "that breaks the thing it diagnoses",
     [('        except Exception as exc:\n            self.sink = None\n            log(f"[run-log] capture unavailable for this run: {exc}", "WARN")',
       '        except Exception as exc:\n            raise')],
     [T_CAP]),
    ("N6", "under", "a run that raises is finalized as a clean completion, so "
     "the index cannot tell a success from a crash",
     [('            if exc_type is None:\n                status = "complete"',
       '            if True:\n                status = "complete"')],
     [T_CAP]),

    # ══ the supervisor's verdict ════════════════════════════════════════
    ("W1", "under", "the worker watchdog stops stamping the folder, so every "
     "ceiling breach reads as an ordinary error with no cause named",
     [('                _patch_run_log_status("watchdog", watchdogCeilingSec=WORKER_OUTER_TIMEOUT_SEC)',
       '                pass')],
     [T_CAP]),
    ("W2", "under", "⛔⛔ THE ORDERING TRAP. Only a still-armed sink is patched — "
     "but the watchdog awaits the cancelled task first, so the capture has "
     "always already finalized and the verdict never lands",
     [('    elif _RUN_LOG_LAST_DIR is not None:\n        target = Path(_RUN_LOG_LAST_DIR) / "meta.json"',
       '    elif False:\n        target = Path(_RUN_LOG_LAST_DIR) / "meta.json"')],
     [T_CAP]),
    ("W3", "over", "the patch claims success when no run ever ran, so a caller "
     "believes a verdict landed somewhere",
     [('    else:\n        return False\n    try:\n        data = json.loads(Path(target).read_text(encoding="utf-8"))',
       '    else:\n        return True\n    try:\n        data = json.loads(Path(target).read_text(encoding="utf-8"))')],
     [T_CAP]),
    ("W4", "under", "the last finalized folder is never remembered, so nothing "
     "after a run can add to its record",
     [('            _RUN_LOG_LAST_DIR = sink.dir', '            pass')],
     [T_CAP]),

    # ══ nothing may bypass the capture ═════════════════════════════════
    ("B1", "under", "⛔ the crash-retry call site reverts to the unwrapped "
     "pipeline, so retried runs leave no folder",
     [('        await run_pipeline_captured(topic=topic, email=email, verbose=verbose,',
       '        await run_pipeline(topic=topic, email=email, verbose=verbose,')],
     [T_CAP]),
    ("B2", "under", "⛔⛔ the WORKER call site reverts — which is every run a real "
     "user ever submits",
     [('                        run_pipeline_captured(topic=job["topic"], email=job.get("email", ""),',
       '                        run_pipeline(topic=job["topic"], email=job.get("email", ""),')],
     [T_CAP]),
    ("B3", "under", "the wrapper stops reading the real call, so every folder is "
     "named local_ and no run can be found by id",
     [('        return (bound.arguments.get("research_id"),\n                int(bound.arguments.get("_crash_retries") or 0),\n                bound.arguments.get("uid") or None)',
       '        return None, 0, None')],
     [T_CAP]),
    ("B4", "under", "the attempt counter is dropped, so a retry cannot be told "
     "from its parent",
     [('                int(bound.arguments.get("_crash_retries") or 0),',
       '                0,')],
     [T_CAP]),
    ("B5", "under", "the signature is bound against something other than the "
     "pipeline itself, so the wrapper can drift from what it forwards",
     [('_RUN_PIPELINE_SIG = _inspect_for_capture.signature(run_pipeline)',
       '_RUN_PIPELINE_SIG = _inspect_for_capture.signature(lambda *a, **k: None)')],
     [T_CAP]),

    # ══ raw-log rotation ═══════════════════════════════════════════════
    ("R1", "under", "⛔⛔ rotation removed from the SINGLE-worker loop — "
     "load_worker_count() defaults to 1, so this is where every default "
     "install lives and nothing would ever rotate",
     [('            _rotate_if_oversize(_serve_log, audit=_sup_audit)\n            _rotate_if_oversize(_serve_err, audit=_sup_audit)\n            with open(_serve_log, "ab")',
       '            with open(_serve_log, "ab")')],
     [T_CAP]),
    ("R2", "under", "rotation removed from the multi-worker spawn, so a fleet "
     "host keeps growing one file per worker",
     [('            _rotate_if_oversize(log_out_path, audit=_sup_audit)\n            _rotate_if_oversize(log_err_path, audit=_sup_audit)\n            try:',
       '            try:')],
     [T_CAP]),
    ("R3", "under", "rotation removed from supervisor start, so the file the "
     "pythonw tee is about to append to is never rolled",
     [('    _rotated_out = _rotate_if_oversize(_serve_log)\n    _rotated_err = _rotate_if_oversize(_serve_err)',
       '    _rotated_out = _rotated_err = 0')],
     [T_CAP]),
    ("R4", "over", "⛔ size is ignored, so every supervisor start rotates and the "
     "previous session's log is destroyed on each restart",
     [('    if size <= int(max_bytes):\n        return 0', '    if False:\n        return 0')],
     [T_CAP]),
    ("R5", "under", "a rename Windows refuses is swallowed, so rotation quietly "
     "stops working on the platform that needs it",
     [('        if audit is not None:\n            try:\n                audit(f"log rotation skipped for {p.name}: {exc}")',
       '        if False:\n            try:\n                audit(f"log rotation skipped for {p.name}: {exc}")')],
     [T_CAP]),
    ("R6", "under", "a failed rename loses the log instead of leaving it in "
     "place",
     [('    except OSError as exc:\n        # Windows refuses to rename a file another handle still holds open.',
       '    except OSError as exc:\n        p.unlink()\n        # Windows refuses to rename a file another handle still holds open.')],
     [T_CAP]),
    ("R7", "under", "the log root is derived separately from the supervisor's, "
     "which is how one product ends up with two log directories",
     [('    return _STATE_DIR / "logs"', '    return Path.home() / ".super-research-logs"')],
     [T_CAP]),

    # ══ local retention ════════════════════════════════════════════════
    ("P1", "under", "arming a run no longer prunes, so the capture becomes a "
     "second unbounded copy on a product with no rotation anywhere",
     [('        try:\n            _prune_local_logs()\n        except Exception:\n            pass',
       '        try:\n            pass\n        except Exception:\n            pass')],
     [T_CAP]),
    ("P2", "under", "⛔⛔ the live-sink guard is gone, so pruning deletes the "
     "folder of the run currently being written",
     [('        if str(path) in live or path.parent != runs_root:',
       '        if path.parent != runs_root:')],
     [T_CAP]),
    ("P3", "under", "the age bound is dropped, so months-old runs survive a "
     "30-day promise",
     [('        if i >= int(runs_keep) or _safe_mtime(path) < cutoff:',
       '        if i >= int(runs_keep):')],
     [T_CAP]),
    ("P4", "under", "the count bound is dropped, so a busy machine keeps every "
     "run inside the window",
     [('        if i >= int(runs_keep) or _safe_mtime(path) < cutoff:',
       '        if _safe_mtime(path) < cutoff:')],
     [T_CAP]),
    ("P5", "under", "session overflow segments are not grouped with their "
     "parent, so orphaned tails accumulate forever",
     [("        base = re.sub(r\"\\.overflow\\d+$\", \"\", path.name)",
       "        base = path.name")],
     [T_CAP]),
    ("P7", "under", "⛔⛔ FOUND BY MUTATION. The cross-process guard is gone, so "
     "worker 2's prune deletes worker 1's live run folder — and a folder's "
     "mtime stops moving while a run writes, so the age bound reaches it",
     [('        if _folder_is_live(path):\n            continue',
       '        if False:\n            continue')],
     [T_CAP]),
    ("P8", "under", "the liveness read trusts the stored status instead of "
     "deriving it, so a killed run's folder is protected forever",
     [('    return _derive_run_status(meta) == "running"',
       '    return str(meta.get("status")) == "running"')],
     [T_CAP]),
    ("P6", "over", "pruning ignores what it was asked to keep and deletes "
     "everything it can reach",
     [('    for i, path in enumerate(runs):', '    for i, path in enumerate(runs, start=10**9):')],
     [T_CAP]),

    # ══ the crash that reached no file ═════════════════════════════════
    ("X1", "under", "⛔ the crash hook is never installed, so an uncaught "
     "traceback goes back to a closing terminal or to backend.err.log",
     [('    _install_crash_log_hook()\n', '    pass\n')],
     [T_CAP]),
    ("X2", "under", "the traceback is printed raw instead of through log(), so "
     "a multi-line record becomes unparseable unstamped orphan lines",
     [('        for line in (text.splitlines() or [""]):\n            log(line, "ERROR")',
       '        for line in (text.splitlines() or [""]):\n            print(line)')],
     [T_CAP]),
    ("X3", "over", "⛔ the default hook is chained too, so every traceback is "
     "printed twice",
     [('    if _PREV_EXCEPTHOOK is not None and _PREV_EXCEPTHOOK is not sys.__excepthook__:',
       '    if _PREV_EXCEPTHOOK is not None:')],
     [T_CAP]),
    ("X4", "over", "Ctrl+C prints a full traceback again, undoing the calm exit "
     "the CLI audit added",
     [('        if issubclass(exc_type, KeyboardInterrupt):', '        if False:')],
     [T_CAP]),
    ("X5", "under", "installing twice re-captures our own hook as the previous "
     "one, which is an infinite loop on the first crash",
     [('    if _CRASH_HOOK_INSTALLED:\n        return False', '    if False:\n        return False')],
     [T_CAP]),

    # ══ the session file ═══════════════════════════════════════════════
    ("S1", "under", "⛔⛔ the tee is installed after dispatch, so --pair/--doctor "
     "return before it exists and their output reaches no file — exactly the "
     "gap the founding incident fell through",
     [('    _session_cmd = _session_command_name(args)\n    if _session_cmd:\n        _install_session_tee(_session_cmd)\n\n    if args.show_version:',
       '    if args.show_version:'),
      ('    if not args.topic:\n        parser.error(',
       '    _session_cmd = _session_command_name(args)\n    if _session_cmd:\n        _install_session_tee(_session_cmd)\n    if not args.topic:\n        parser.error(')],
     [T_CAP]),
    ("S2", "over", "--serve gets a session tee too, so backend.log is written "
     "twice and the sessions folder fills with copies of it",
     [('    for flag in ("pair", "login", "doctor"):',
       '    for flag in ("pair", "login", "doctor", "serve"):')],
     [T_CAP]),
    ("S3", "under", "the session header loses its date — the one thing log() "
     "has never stamped and the reason post-hoc splitting is impossible",
     [('        writer.write_line(\n            f"startedUtc={started} build={_sr_version()} pid={os.getpid()} "',
       '        writer.write_line(\n            f"build={_sr_version()} pid={os.getpid()} "')],
     [T_CAP]),
    ("S4", "under", "only stdout is teed, so everything a command writes to "
     "stderr — which is where failures go — reaches no file",
     [('        for name in ("stdout", "stderr"):', '        for name in ("stdout",):')],
     [T_CAP]),
]


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
