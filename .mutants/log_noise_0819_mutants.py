"""Mutation harness for the 2026-08-19 log-noise wave.

⛔⛔ WHAT THIS WAVE IS. Measured on the owner's own files: two sentences were
43.7% of the bytes in the session log a support bundle carries, and one line was
91–95% of two raw machine tails while another was 95.7% of a third. Four floods,
one defect — a true statement whose information content is a single bit, emitted
on a hot path with no cadence.

⭐ THE MUTANTS THAT MATTER MOST, because each one reopens the thing this wave
exists to make impossible IN THE DIRECTION THAT IS SILENT:

  Q1  — `emits(0)` returns False. The FIRST copy of every line disappears: the
        only account of the wiring fault that made every telemetry batch
        anonymous, the only line that diagnosed a new owner's whole outage. Every
        "it is quieter now" assertion still passes.
  Q6  — an empty cadence stops raising at construction, so a malformed cadence
        silently restores the flood and the only symptom is a big log.
  C3  — the recovery reset goes. A second outage hours later is reported at
        whatever hourly cadence the first one had widened to, i.e. the new
        incident arrives late or not at all — a suppressor hiding exactly the
        transition a reader came for.
  P2  — `telemetry` leaves py-modules again and the next wheel dies with
        ModuleNotFoundError before printing anything. This is the hole the two
        pre-existing drift guards could not see, because they compare two lists
        to each other and a module in neither satisfies both.

⭐ Over-corrections (the fix going too far is its own failure mode here):
  Q2  — the suppressor stops resetting on a state change, so a broken watch is
        reported an hour after Firestore drops.
  H2  — the health filter widens to any status, deleting the 500 from the very
        endpoint the worker watchdog uses to decide a worker is wedged.
  N1  — the suppressed count stops being rendered, so "this happened 13,479
        times" collapses to "this happened".

Sibling harnesses carry the rest of this wave, each owning its own file:
  .mutants/telemetry_0818_mutants.py       D6c/D6d, T2, T8-T10  (the mirror)
  .mutants/log_bundle_0818_mutants.py      B11-B12, B11b-B11h   (the tail reader)
  .mutants/new_owner_setup_0817_mutants.py F18-F20, F20b-F20g   (the aegis pulse)

    python .mutants/log_noise_0819_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LQ = "logquiet.py"
CRED = "auth/credentials.py"
RES = "research.py"
PROJ = "pyproject.toml"
BUILD = "tools/build_compiled.py"
MUTATED_FILES = [LQ, CRED, RES, PROJ, BUILD]

T = "tests/test_log_noise_0819.py"
T_WHEEL = "tests/test_compiled_wheel_covers_every_module.py"
T_SERVE = "tests/test_serve_cli_consistency.py"
T_OUT = "tests/test_firestore_outage_speaks_0817.py"
# ⛔ ORDER MATTERS IN THIS PAIR AND THAT IS THE POINT. A `ONCE` suppressor held in
# a module global is per-PROCESS, so the first test to trip a topic silences it for
# every later one. Run the noise file FIRST and the stranded-batch file second —
# which is the ordering that turned red in the full suite on 2026-08-19 — so the
# mutants below can prove the conftest reset is what keeps it green.
T_STRANDED = "tests/test_telemetry_stranded_batch_0818.py"
CONF = "tests/conftest.py"
ALL = [T, T_WHEEL, T_SERVE, T_OUT, T_STRANDED]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 900

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str], str]] = [

    # ══ the primitive: it must never be able to delete the first copy ════
    ("Q1", "under", "⛔⛔ the FIRST occurrence of a state is suppressed. Every "
     "line this wave exists to preserve disappears and every quieter-now "
     "assertion still passes",
     [("    if n <= 0:\n        return True", "    if n <= 0:\n        return False")],
     [T], LQ),
    ("Q2", "over", "⛔ a changed state no longer restarts the cadence, so a "
     "broken watch is reported up to an hour after Firestore drops",
     [('            if self._state.get(topic) != state:',
       '            if False:')], [T], LQ),
    ("Q3", "under", "the cadence stops widening — every repeat is emitted and "
     "the flood is back verbatim",
     [("DEFAULT_CADENCE: tuple[tuple[int | None, int], ...] = (\n"
       "    (5, 1), (30, 5), (120, 15), (None, 60),\n)",
       "DEFAULT_CADENCE: tuple[tuple[int | None, int], ...] = (\n    (None, 1),\n)")],
     [T], LQ),
    ("Q4", "over", "⛔ the widest band emits nothing, so a long-running process "
     "loses its liveness pulse permanently — silence dressed as quiet",
     [("    (5, 1), (30, 5), (120, 15), (None, 60),",
       "    (5, 1), (30, 5), (120, 15), (None, 0),")], [T], LQ),
    ("Q5", "under", "ONCE says it forever",
     [('ONCE: tuple[tuple[int | None, int], ...] = ((1, 1), (None, 0))',
       'ONCE: tuple[tuple[int | None, int], ...] = ((1, 1), (None, 1))')],
     [T], LQ),
    ("Q6", "under", "⛔⛔ an empty cadence is accepted at construction. `emits` "
     "fails open on it, so the flood returns and the only symptom is a big log",
     [('    if not bands:\n        raise ValueError("cadence has no bands '
       '— every repeat would be emitted")', '    if False:\n        pass')],
     [T], LQ),
    ("Q7", "under", "a closed final band is accepted, so a cadence can read as a "
     "permanent silence while behaving open — a declaration that lies",
     [("    if bands[-1][0] is not None:", "    if False:")], [T], LQ),
    ("Q8", "under", "band boundaries may repeat or go backwards, so a band "
     "silently never applies",
     [("        if until <= seen:", "        if False:")], [T], LQ),
    ("Q8b", "under", "a SECOND open band is accepted, so every band after the "
     "first is silently dead — `emits` returns on the first `until is None`",
     [('        if until is None:\n            raise ValueError("only the LAST '
       'band may be open-ended")', '        if False:\n            pass')],
     [T], LQ),
    ("Q9", "over", "⛔ the last band stops applying, so every index past the "
     "final boundary is silent — a permanent hole on long-running processes only",
     [("        if i == last or until is None or n < until:",
       "        if until is None or n < until:")], [T], LQ),
    ("Q10", "under", "⛔ an unrecognised cadence fails toward SILENCE instead of "
     "noise, which is the one direction this module may not fail in",
     [("    # Reachable only for an EMPTY cadence, and it fails OPEN for the reason in\n"
       "    # the band comment above: a caller who passes nothing gets a noisy log, not\n"
       "    # a silent one.\n    return True",
       "    return False")], [T], LQ),
    ("Q11", "under", "the suppressed count is always zero, so a sparse line stops "
     "carrying the scale of what it replaced",
     [("                suppressed = n - self._emitted[topic] - 1",
       "                suppressed = 0")], [T], LQ),
    ("Q12", "under", "⛔⛔ `reset` is a no-op. A fault that clears and RETURNS is "
     "reported at the wide cadence the first outage reached",
     [("        with self._lock:\n            self._state.pop(topic, None)\n"
       "            self._n.pop(topic, None)\n"
       "            self._emitted.pop(topic, None)",
       "        return")], [T], LQ),
    ("Q13", "under", "topics share one counter, so one noisy topic mutes every "
     "other line in the process",
     [('            if self._state.get(topic) != state:',
       '            if self._state.get("") != state:')], [T], LQ),
    ("Q14", "under", "the suppressor loses its lock, and its consumers are a "
     "telemetry flush thread, an asyncio task and the gRPC metadata thread",
     [("        self._lock = threading.Lock()",
       "        self._lock = __import__('contextlib').nullcontext()")], [T], LQ),
    ("N1", "over", "⛔ the suppressed note renders nothing, so 'this happened "
     "13,479 times' collapses to 'this happened'",
     [('    return f" (+{int(n)} since the last of these)" if int(n) > 0 else ""',
       '    return ""')], [T], LQ),
    ("N2", "under", "a first line claims a suppressed count of zero, which reads "
     "as a bug in the very line that is supposed to be trustworthy",
     [('if int(n) > 0 else ""', 'if int(n) >= 0 else ""')], [T], LQ),
    ("Q15", "under", "logquiet grows a first-party import, breaking the two "
     "consumers that exist precisely because they cannot have one",
     [("import threading", "import threading\nimport research  # noqa: F401")],
     [T], LQ),
    ("Q16", "under", "`clear` is a no-op, so a ONCE topic tripped by one test is "
     "silent for every test after it — an order-dependent break in a file nobody "
     "touched",
     [("        with self._lock:\n            self._state.clear()\n"
       "            self._n.clear()\n            self._emitted.clear()",
       "        return")], [T, T_STRANDED], LQ),
    ("Q17", "under", "⛔⛔ the suite-wide suppressor reset goes, and the isolation "
     "becomes something every future test has to remember",
     [("            if isinstance(value, logquiet.Suppressor):\n"
       "                value.clear()",
       "            pass")], [T, T_STRANDED], CONF),
    ("Q18", "under", "the reset stops walking the first-party modules, so it only "
     "ever finds suppressors somebody remembered to name",
     [("        if not path.startswith(repo):\n            continue",
       "        if True:\n            continue")], [T, T_STRANDED], CONF),

    # ══ fix C: the refresh flood (95.7% of one .err tail) ════════════════
    ("C1", "under", "⛔⛔ the refresh error loses its cadence — 13,479 lines in "
     "one tail, and since 2026-08-17 they land in the file users send",
     [("            emit, dropped = _REFRESH_NET_QUIET.consider(\n"
       "                _REFRESH_NET_TOPIC, type(e).__name__)",
       "            emit, dropped = True, 0")], [T], CRED),
    ("C2", "over", "⛔ the refresh error is deleted outright — the single line "
     "that diagnosed a new owner's entire outage",
     [("            if emit:", "            if False:")], [T], CRED),
    ("C3", "under", "⛔⛔ RECOVERY NO LONGER RESETS. A second outage is reported "
     "at the first one's hourly cadence, so the new incident arrives late",
     [("        _REFRESH_NET_QUIET.reset(_REFRESH_NET_TOPIC)\n", "")], [T], CRED),
    ("C4", "under", "the reset moves behind the 400 handling, so a revoke during "
     "an outage leaves the cadence wide open",
     [("        _REFRESH_NET_QUIET.reset(_REFRESH_NET_TOPIC)\n\n"
       "        if resp.status_code == 400:",
       "        if resp.status_code == 400:")], [T], CRED),
    ("C5", "under", "⛔ the state becomes the MESSAGE, which embeds the resolver's "
     "own text — every failure reads as new and nothing is suppressed",
     [("                _REFRESH_NET_TOPIC, type(e).__name__)",
       "                _REFRESH_NET_TOPIC, str(e))")], [T], CRED),
    ("C6", "under", "the attempt number goes, so a surviving line cannot say "
     "whether this is the first failure or the ten-thousandth",
     [('                            "intact%s (attempt %d)", e,',
       '                            "intact%s", e,')], [T], CRED),

    # ══ fix D1: the live health-probe filter ════════════════════════════
    ("H1", "under", "⛔ the filter matches the PATH again, so 74,836 boring lines "
     "and the 500 that matters are silenced by the same rule",
     [("            return not _HEALTH_PROBE_ACCESS_RE.search(record.getMessage())",
       '            return "/api/health" not in record.getMessage()')],
     [T, T_SERVE], RES),
    ("H2", "over", "⛔⛔ the pattern accepts ANY status, so the failing probe from "
     "the endpoint the watchdog uses to decide a worker is wedged is deleted",
     [('    r\'"(?:GET|HEAD) /api/health(?:\\?[^"\\s]*)? HTTP/[0-9.]+" 2\\d\\d\\b\')',
       '    r\'"(?:GET|HEAD) /api/health(?:\\?[^"\\s]*)? HTTP/[0-9.]+"\')')],
     [T, T_SERVE], RES),
    ("H3", "under", "an unformattable record is swallowed, losing real access "
     "lines to a formatting bug",
     [("        except Exception:\n            return True          "
       "# unformattable record — never swallow it",
       "        except Exception:\n            return False")], [T, T_SERVE], RES),
    ("H4", "under", "the bytes pattern is written out a SECOND time rather than "
     "compiled from the string, so the two readers can disagree about a probe",
     [('_HEALTH_PROBE_ACCESS_RE_BYTES = re.compile(\n'
       '    _HEALTH_PROBE_ACCESS_PATTERN.encode("ascii"))',
       '_HEALTH_PROBE_ACCESS_RE_BYTES = re.compile(\n'
       '    br\'"(?:GET|HEAD) /api/health HTTP/[0-9.]+" 2\\d\\d\\b\')')],
     [T, T_SERVE], RES),
    ("H5", "under", "the filter leaves the access handler, so uvicorn logs every "
     "probe again whatever the pattern says",
     [('                "filters": ["no_health_probe"],\n', '')],
     [T, T_SERVE], RES),

    # ══ fix E2: Clear logs reaching the telemetry directory ═════════════
    ("E1", "under", "⛔⛔ the clear stops reaching the telemetry directory — "
     "2,568,739 bytes of 'everything this machine ever sent' survive the button",
     [("    for path in tm_targets:\n        try:\n            path.unlink()\n"
       "            out[\"telemetry\"] += 1",
       "    for path in []:\n        try:\n            path.unlink()\n"
       "            out[\"telemetry\"] += 1")], [T], RES),
    ("E2", "over", "⛔ the sweep takes the whole directory, so a clear removes "
     "subdirectories it does not recognise — a sweep that can be pointed anywhere",
     [('                if p.is_file() and (p.name == tm.sent_log_path().name\n'
       '                                    or p.name.startswith("pending-"))',
       '                if True')], [T], RES),
    ("E3", "under", "the spools are missed and only the mirror is cleared, so a "
     "queue of undelivered events survives a clear",
     [('or p.name.startswith("pending-")', "or False")], [T], RES),
    ("E4", "under", "the telemetry root stops being the one telemetry uses, so "
     "the clear reports success against a directory nobody writes to",
     [("              else Path(tm.sent_log_path()).parent)",
       "              else Path(base) / \"telemetry\")")], [T], RES),
    ("E5", "over", "⛔ the COLLECTOR allowlist widens to match the clear, which is "
     "the one thing the consent screen's promise is gated on",
     [("        Path(path).resolve().relative_to(_logs_root().resolve())\n        return True",
       "        Path(path).resolve().relative_to(_STATE_DIR.resolve())\n        return True")],
     [T], RES),

    # ══ fix F: the packaging hole ═══════════════════════════════════════
    ("P1", "under", "⛔⛔ `telemetry` leaves py-modules again. research.py imports "
     "it at module scope, so the next wheel dies with ModuleNotFoundError before "
     "printing a line — and the two pre-existing drift guards cannot see it",
     [('py-modules = ["research", "models", "prompts", "vision", "narrate", "selfheal",\n'
       '              "telemetry", "logquiet"]',
       'py-modules = ["research", "models", "prompts", "vision", "narrate", "selfheal"]')],
     [T_WHEEL], PROJ),
    ("P2", "under", "`logquiet` is shipped as readable source instead of compiled, "
     "the exact 2026-06-22 selfheal leak",
     [('TOP_MODULES = ["models", "prompts", "vision", "narrate", "selfheal",\n'
       '               "telemetry", "logquiet"]',
       'TOP_MODULES = ["models", "prompts", "vision", "narrate", "selfheal",\n'
       '               "telemetry"]')], [T_WHEEL], BUILD),
    ("P3", "under", "the import scan only looks at research.py, so an auth module "
     "can import something the wheel does not carry",
     [('    return [REPO / "research.py", *sorted((REPO / "auth").glob("*.py"))]',
       '    return [REPO / "research.py"]')], [T_WHEEL], "tests/test_compiled_wheel_covers_every_module.py"),
    ("P4", "under", "the scan counts GUARDED imports too, so an optional "
     "dependency starts demanding to be shipped",
     [("        for node in tree.body:            # top level ONLY",
       "        for node in ast.walk(tree):")], [T_WHEEL],
     "tests/test_compiled_wheel_covers_every_module.py"),

    # ══ dating a line in a multi-week log (owner ask 08-19) ═════════════
    ("G1", "under", "⛔⛔ the date marker is never emitted, so not one line in a "
     "multi-week machine log can be dated from its own text — the 44 MB file on "
     "this machine spans 2026-07-19 → 08-05",
     [("    marker = _log_date_marker(_stamp[:10], ts)",
       "    marker = None")], [T], RES),
    ("G2", "over", "the marker is emitted on EVERY line, which is the wider "
     "timestamp this design rejected — 15% of a 44 MB file",
     [("    if day == _LOG_DATE_STAMPED:\n        return None",
       "    if False:\n        return None")], [T], RES),
    ("G3", "under", "the marker never updates the stamp, so it prints forever",
     [("    _LOG_DATE_STAMPED = day\n", "")], [T], RES),
    ("G4", "under", "the marker drops out of `log()`'s own format, bringing back "
     "the four-formats-in-one-stream problem through the fix for dating",
     [('    return f"[{ts}] [INFO] {LOG_DATE_PREFIX} {day}"',
       '    return f"===== {day} ====="')], [T], RES),
    ("G5", "under", "the marker is printed but not written through, so an armed "
     "run folder gets the undated half only",
     [("    if marker:\n        print(marker)\n        _log_write_through(marker, \"INFO\")",
       "    if marker:\n        print(marker)")], [T], RES),
    ("G6", "under", "⛔ the printed line's own format changes, and every parser "
     "and pinned test that shares `[%H:%M:%S] [LEVEL] msg` moves with it",
     [('    line = f"[{ts}] [{level}] {msg}"',
       '    line = f"[{_stamp}] [{level}] {msg}"')], [T], RES),
    ("G7", "under", "the tail stops recording the markers it carried, so a reader "
     "cannot tell which dates the window covers",
     [("    for line in newest_first:\n        found = _LOG_DATE_MARKER_RE.search(line)",
       "    for line in []:\n        found = _LOG_DATE_MARKER_RE.search(line)")],
     [T], RES),
    ("G8", "under", "⛔⛔ the file's own last-write time is dropped — and the ZIP "
     "stamps the moment the BUNDLE was built, so a frozen machine's log wears "
     "today's date and nothing else carries the truth",
     [('        stats["lastWrittenUtc"] = _utc_iso(_dt.datetime.fromtimestamp(\n'
       '            Path(path).stat().st_mtime, _dt.timezone.utc))',
       '        stats["lastWrittenUtc"] = ""')], [T], RES),
    ("G9", "over", "the dating sentence claims a date range on a file that has no "
     "markers at all — a confident lie beats no answer only for the writer",
     [('    if oldest and newest:', '    if True:')], [T], RES),
    ("G10", "under", "the oldest marker in the window is reported as the newest, "
     "so the date a reader starts from is the wrong end of the tail",
     [('            stats.setdefault("dateNewest", day)\n            stats["dateOldest"] = day',
       '            stats["dateNewest"] = day\n            stats.setdefault("dateOldest", day)')],
     [T], RES),
    ("G10b", "under", "⛔⛔ the date range is collected during the WALK again, so "
     "the budget trim can remove the oldest marker and leave the header naming a "
     "date the reader cannot find below it",
     [("    for line in newest_first:\n        found = _LOG_DATE_MARKER_RE.search(line)\n"
       "        if found:\n            day = found.group(1).decode(\"ascii\")\n"
       "            stats.setdefault(\"dateNewest\", day)\n"
       "            stats[\"dateOldest\"] = day",
       "    for line in newest_first + [x for x in (out[-1:] if out else [])]:\n"
       "        found = _LOG_DATE_MARKER_RE.search(line)\n"
       "        if found:\n            day = found.group(1).decode(\"ascii\")\n"
       "            stats.setdefault(\"dateNewest\", day)\n"
       "            stats[\"dateOldest\"] = day")],
     [T], RES),
    ("G11", "under", "the marker pattern is written out again instead of derived "
     "from the prefix the writer uses, so the two can drift",
     [('_LOG_DATE_MARKER_RE = re.compile(\n'
       '    re.escape(LOG_DATE_PREFIX.encode("ascii")) + rb" (\\d{4}-\\d{2}-\\d{2})")',
       '_LOG_DATE_MARKER_RE = re.compile(rb"\\[day\\] (\\d{4}-\\d{2}-\\d{2})")')],
     [T], RES),
    ("G12", "under", "the suite-wide date-marker fixture goes, and exactly one "
     "test per run finds an extra line in its captured stdout — which one depends "
     "on collection order, across 26 files that capture output",
     [('    monkeypatch.setattr(research, "_LOG_DATE_STAMPED",\n'
       '                        datetime.now().strftime("%Y-%m-%d"), raising=True)',
       '    pass')], [T, T_SERVE], CONF),

    # ══ the bundle contract's silent fallback ═══════════════════════════
    ("K1", "under", "the wheel's literal fallback drifts from the file every "
     "source checkout reads, silently changing what the slider's top position means",
     [('        return {"maxRuns": 30, "maxAgeDays": 30, "minRuns": 1,',
       '        return {"maxRuns": 10, "maxAgeDays": 30, "minRuns": 1,')], [T], RES),
]

_MUTATED_TESTS = {m[5] for m in MUTANTS if m[5].startswith("tests/")}


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ A stale `__pycache__/*.pyc` served OLD bytecode for a file this
        # harness had already rewritten, and the measurement disagreed with the
        # source for three rounds. In a harness that rewrites source between every
        # run, a cached module is not a nuisance — it is a kill or a survivor
        # invented out of nothing.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    files = set(MUTATED_FILES) | _MUTATED_TESTS
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in sorted(files)}


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
    for mid, direction, why, edits, tests, target_file in MUTANTS:
        target = ROOT / target_file
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
