"""Mutation harness for wave 2 step 9 — where the content-free tier is wired in.

⛔⛔ THE THREE CANNOT-FIRE TRAPS, restored one at a time:

  E1 — the outage emit moves OUT of the edge branch. `_mark_firestore_down` is
       called on every down tick — 4,921 times in the measured incident — so the
       tier would flood its own rate limit and evict the pairing events that
       explain the outage.
  E4 — `_clear_firestore_down` emits unconditionally. It runs at the one place a
       client is built, which is every reconnect AND every boot, so it would
       report outages that never happened.
  P1 — the tap moves below `if not _tracks_dir: return`, so a run whose Firestore
       setup is the thing that failed reports nothing, and absence reads as health.

⭐ AND THE ONE THIS WAVE'S OWN TESTS CAUGHT AS A LIVE DEFECT: the outage emit
originally read a `_firestore_down_reason` global that does not exist, which
would have raised a NameError on the ONE code path that runs only while the
product is already broken. E6 restores the direct read.

⭐ Over-corrections:
  P3  — the tap forwards `**data`, and free text re-enters a content-free path.
  F3  — the flush becomes synchronous, so a machine with dead DNS holds the
        user's command inside a name lookup.
  R3  — `run_finished` moves to `teardown_firestore_run`, measured to be a
        context-free cleanup with nothing in scope: an event that says nothing.

    python .mutants/telemetry_sites_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
FLOW = "auth/v2_flow.py"
MUTATED_FILES = [SRC, FLOW]

T = "tests/test_telemetry_call_sites_0818.py"
T_CAP = "tests/test_run_log_capture_0818.py"
ALL = [T, T_CAP]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str], str]] = [

    # ══ the outage edge ═════════════════════════════════════════════════
    ("E1", "under", "⛔⛔ the outage emit leaves the edge branch — 4,921 events per "
     "incident, flooding the rate limit and evicting the pairing events that "
     "explain it",
     [('''    if _firestore_down_since_ts is None:
        _firestore_down_since_ts = float(now if now is not None else time.time())''',
       '''    if True:
        _firestore_down_since_ts = float(now if now is not None else time.time())''')],
     [T], SRC),
    ("E2", "under", "the outage start is never reported at all",
     [('        tm.tm_emit(tm.Ev.FIRESTORE_OUTAGE_STARTED, worker=WORKER_ID,',
       '        _unused = (tm.Ev.FIRESTORE_OUTAGE_STARTED, WORKER_ID) and None or (lambda **k: None)(')],
     [T], SRC),
    ("E3", "under", "the outage END is never reported, so every incident reads as "
     "still ongoing",
     [('''        tm.tm_emit(tm.Ev.FIRESTORE_OUTAGE_ENDED, worker=WORKER_ID,
                   duration_ms=int((time.time() - _firestore_down_since_ts) * 1000))''',
       '''        pass''')],
     [T], SRC),
    ("E4", "over", "⛔⛔ the end is reported unconditionally, and this runs at the "
     "one place a client is BUILT — every reconnect and every boot — so it "
     "reports outages that never happened",
     [('    if _firestore_down_since_ts is not None:', '    if True:')],
     [T], SRC),
    ("E5", "under", "the outage duration is not reported, so the longitudinal "
     "signal cannot tell a blip from an afternoon",
     [('                   duration_ms=int((time.time() - _firestore_down_since_ts) * 1000))',
       '                   duration_ms=None)')],
     [T], SRC),
    ("E6", "under", "⛔⛔ THE DEFECT THIS WAVE'S OWN TESTS CAUGHT. The reason is read "
     "directly instead of through globals(), which is a NameError on the one code "
     "path that runs only while the product is already broken",
     [('                                if globals().get("_firebase_down_reason") == "revoked"',
       '                                if _firestore_down_reason == "revoked"')],
     [T], SRC),
    ("E7", "over", "a cause is claimed that nothing at mark time can know",
     [('''                   error_class=(tm.ErrorClass.AUTH_REVOKED
                                if globals().get("_firebase_down_reason") == "revoked"
                                else None))''',
       '''                   error_class=tm.ErrorClass.DNS)''')],
     [T], SRC),

    # ══ the tap ═════════════════════════════════════════════════════════
    ("P1", "under", "⛔⛔ the tap moves BELOW the _tracks_dir guard, so a run whose "
     "Firestore setup is the thing that failed reports nothing",
     [('''    _run_sink_note_event(event_type, phase, agent)
    _tm_note_event(event_type, phase, agent)
    if not _tracks_dir:
        return''',
       '''    _run_sink_note_event(event_type, phase, agent)
    if not _tracks_dir:
        return
    _tm_note_event(event_type, phase, agent)''')],
     [T], SRC),
    ("P2", "under", "⛔ the mapped name reverts to the one that occurs ZERO times "
     "in this file, so phase failures are never captured",
     [('    "pipeline_error": tm.Ev.PIPELINE_ERROR,', '    "fail_phase": tm.Ev.PIPELINE_ERROR,')],
     [T], SRC),
    ("P3", "over", "⛔⛔ the tap forwards **data, and free text re-enters a "
     "content-free path",
     [('def _tm_note_event(event_type, phase=None, agent=None) -> None:',
       'def _tm_note_event(event_type, phase=None, agent=None, **data) -> None:'),
      ('    tm.tm_emit(mapped, **fields)', '    tm.tm_emit(mapped, **fields, **data)'),
      ('    _tm_note_event(event_type, phase, agent)\n    if not _tracks_dir:',
       '    _tm_note_event(event_type, phase, agent, **data)\n    if not _tracks_dir:')],
     [T], SRC),
    ("P4", "under", "an unmapped agent name reaches the wire as itself instead of "
     "landing on OTHER",
     [('    }.get(key, tm.Platform.OTHER)', '    }.get(key, key)')],
     [T], SRC),
    ("P5", "under", "the run id is dropped, so no phase event can be tied to the "
     "run it belongs to",
     [('    if rid:\n        fields["research_id"] = rid', '    if False:\n        fields["research_id"] = rid')],
     [T], SRC),
    ("P6", "under", "the phase number is dropped, so every phase event looks the "
     "same",
     [('    if isinstance(phase, int):\n        fields["phase"] = phase',
       '    if False:\n        fields["phase"] = phase')],
     [T], SRC),
    ("P7", "under", "an unmapped event is guessed at instead of ignored",
     [('    mapped = _TM_EVENT_MAP.get(str(event_type))\n    if mapped is None:\n        return',
       '    mapped = _TM_EVENT_MAP.get(str(event_type), Ev_default) if False else _TM_EVENT_MAP.get(str(event_type), tm.Ev.PHASE_START)\n    if False:\n        return')],
     [T], SRC),

    # ══ the run lifecycle ═══════════════════════════════════════════════
    ("R1", "under", "a run never reports that it started",
     [('            tm.tm_emit(tm.Ev.RUN_STARTED,\n                       research_id=self.research_id, worker=WORKER_ID)', '            pass')],
     [T], SRC),
    ("R2", "under", "a run never reports how it ended, so a machine that fails "
     "every run looks identical to one that succeeds",
     [('            tm.tm_emit(tm.Ev.RUN_FINISHED,', '            (lambda *a, **k: None)(')],
     [T], SRC),
    ("R3", "over", "every outcome is UNKNOWN — the event that says nothing, which "
     "is exactly what anchoring this at the teardown would have produced",
     [('''                       outcome={"complete": tm.RunOutcome.COMPLETE,
                                "errored": tm.RunOutcome.ERRORED,
                                "cancelled": tm.RunOutcome.STOPPED,
                                "interrupted": tm.RunOutcome.STOPPED}.get(
                                    status, tm.RunOutcome.UNKNOWN),''',
       '''                       outcome=tm.RunOutcome.UNKNOWN,''')],
     [T], SRC),
    ("R4", "under", "a cancelled run is reported as an error, so a user pressing "
     "Stop shows up in the failure rate",
     [('                                "cancelled": tm.RunOutcome.STOPPED,',
       '                                "cancelled": tm.RunOutcome.ERRORED,')],
     [T], SRC),

    # ══ the commands ════════════════════════════════════════════════════
    ("C1", "under", "⛔ the pairing timeout returns without reporting — the abort a "
     "broken machine actually takes",
     [('            tm.tm_emit(tm.Ev.PAIR_FAILED, stage=1,\n                       error_class=tm.ErrorClass.TIMEOUT)\n', '')],
     [T], SRC),
    ("C2", "under", "the unreachable-service abort returns silently",
     [('''            tm.tm_emit(tm.Ev.PAIR_FAILED, stage=1,
                       error_class=tm.classify_exception(e))
            _pt(f"could not reach the pairing service "''',
       '''            _pt(f"could not reach the pairing service "''')],
     [T], SRC),
    ("C3", "under", "the catch-all abort returns silently, and it is the branch "
     "that by definition has no better diagnosis",
     [('''            tm.tm_emit(tm.Ev.PAIR_FAILED, stage=1,
                       error_class=tm.classify_exception(e))
            _pt(f"pairing stopped on an error we have no specific advice for "''',
       '''            _pt(f"pairing stopped on an error we have no specific advice for "''')],
     [T], SRC),
    ("C4", "under", "a cancel is reported as a failure, so a person changing their "
     "mind shows up as a broken install",
     [('            tm.tm_emit(tm.Ev.PAIR_CANCELLED, stage=1)',
       '            tm.tm_emit(tm.Ev.PAIR_FAILED, stage=1)')],
     [T], SRC),
    ("C5", "under", "pairing never reports that it started, so the only thing "
     "visible is the failures — and a machine that never got that far is silent",
     [('    tm.tm_emit(tm.Ev.PAIR_STARTED, supervised=_detect_supervised())', '    pass')],
     [T], SRC),
    ("C6", "under", "the doctor stops reporting, and it is the command a person "
     "runs precisely when something is wrong",
     [('        tm.tm_emit(tm.Ev.DOCTOR_RUN, count=int(issues_found),\n                   supervised=_detect_supervised())', '        pass')],
     [T], SRC),
    ("C7", "under", "serve never reports starting, so an install that crash-loops "
     "on boot is indistinguishable from one nobody uses",
     [('        tm.tm_emit(tm.Ev.SERVE_STARTED, worker=WORKER_ID,\n                   supervised=_detect_supervised())', '        pass')],
     [T], SRC),
    ("C8", "under", "login never reports",
     [('    tm.tm_emit(tm.Ev.LOGIN_STARTED)\n', '')],
     [T], SRC),
    ("C9", "under", "send-logs never reports its own outcome, so the feature built "
     "to give us visibility is the one thing we cannot see",
     [('    tm.tm_emit(tm.Ev.SEND_LOGS_RESULT, ok=bool(landed_via),\n               count=int(summary["runCount"]))', '    pass')],
     [T], SRC),

    ("C10", "under", "⛔⛔ pairing never reports COMPLETING, so PAIR_FAILED has no "
     "denominator and \"no completions recorded\" reads as \"nobody ever pairs\"",
     [('        tm.tm_emit(tm.Ev.PAIR_COMPLETED, stage=5,\n                   profiles=max(1, int(next_profile_n) - 1),\n                   supervised=bool(enable_on_startup))', '        pass')],
     [T], SRC),
    ("C11", "under", "the completion drops the capacity — the question the founding "
     "incident turned on, where the owner wanted two run slots and got one",
     [('                   profiles=max(1, int(next_profile_n) - 1),', '                   profiles=None,')],
     [T], SRC),
    ("C12", "over", "the stage emit moves INTO _setup_step, which is shared with "
     "--retire and --unpair — so their steps are reported as pairing progress",
     [('    print()\n    print(f"  {_c(_ACCENT + _BOLD, f\'[{n}/{total}]\')} {_c(_BOLD, title)}")',
       '    tm.tm_emit(tm.Ev.PAIR_STAGE_REACHED, stage=n)\n    print()\n    print(f"  {_c(_ACCENT + _BOLD, f\'[{n}/{total}]\')} {_c(_BOLD, title)}")')],
     [T], SRC),
    ("C13", "under", "a stage stops reporting, so the one thing the incident needed "
     "— how far pairing got — has a hole in it",
     [('    tm.tm_emit(tm.Ev.PAIR_STAGE_REACHED, stage=4)\n', '')],
     [T], SRC),
    ("C14", "under", "⛔ the failed token refresh stops reporting — the line that "
     "diagnosed the founding incident and that nobody ever saw",
     [('        tm.tm_emit(tm.Ev.TOKEN_REFRESH_FAILED,\n                   error_class=tm.classify_exception(e))', '        pass')],
     [T], SRC),
    ("C15", "over", "the refresh failure reports the MESSAGE, which carries a "
     "hostname, a path and a Firebase Web API key",
     [('                   error_class=tm.classify_exception(e))\n        log(f"user-mode id-token: refresh failed: {e}", "WARN")',
       '                   error_class=str(e))\n        log(f"user-mode id-token: refresh failed: {e}", "WARN")')],
     [T], SRC),
    ("C16", "under", "a revoke is reported as an unknown failure, so the one cause "
     "that needs a re-pair looks like a network blip",
     [('                   error_class=tm.ErrorClass.AUTH_REVOKED)', '                   error_class=None)')],
     [T], SRC),
    ("C17", "under", "login never reports finishing, so a machine where sign-in "
     "silently fails every time looks the same as one that works",
     [('    tm.tm_emit(tm.Ev.LOGIN_FINISHED, ok=bool(_any_ok),\n               count=len(_missing_names))', '    pass')],
     [T], SRC),
    ("C18", "under", "the pair code is never reported as shown, so a machine that "
     "got a code and a machine that never reached the service look identical",
     [('        tm.tm_emit(tm.Ev.PAIR_CODE_SHOWN)\n', '')],
     [T], SRC),

    # ══ the flush ═══════════════════════════════════════════════════════
    ("F1", "under", "⛔⛔ nothing flushes at the top of main, so a machine whose "
     "pairing succeeded but whose POST failed never sends again — it never pairs "
     "again either",
     [('    tm.flush_in_background()\n\n    # Super Agent (chat-runtime bridge)',
       '\n    # Super Agent (chat-runtime bridge)')],
     [T], SRC),
    ("F2", "under", "the per-worker drain goes, so a worker-2 spool never leaves "
     "the machine",
     [('            tm.flush_in_background()\n            if _firebase_db is not None:',
       '            if _firebase_db is not None:')],
     [T], SRC),
    ("F3", "over", "⛔ the flush becomes synchronous, so a machine with dead DNS "
     "holds the user's command inside a name lookup",
     [('    tm.flush_in_background()\n\n    # Super Agent (chat-runtime bridge)', '    tm.flush()\n\n    # Super Agent (chat-runtime bridge)')],
     [T], SRC),
    ("F4", "under", "a finished run does not flush what it just recorded",
     [('            tm.flush_in_background()\n        except Exception:',
       '            pass\n        except Exception:')],
     [T], SRC),

    # ══ the correlation key ═════════════════════════════════════════════
    ("I1", "under", "⛔⛔ the install id stops reaching the device doc, so a bundle "
     "or a batch sent while pairing was broken is attributable to nobody, forever",
     [('        "installUuid": _install_uuid_best_effort(),\n', '')],
     [T], FLOW),
    ("I2", "under", "a keystore failure takes the pairing down with it, for a "
     "correlation id",
     [('''    try:
        from .keystore import install_uuid
        return str(install_uuid())
    except Exception:
        return None''',
       '''    from .keystore import install_uuid
    return str(install_uuid())''')],
     [T], FLOW),
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
