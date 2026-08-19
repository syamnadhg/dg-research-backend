"""Mutation harness for wave 2 step 8 — the content-free telemetry tier.

⛔⛔ THE TWO MUTANTS THAT MATTER MOST, because each one reopens the thing this
module exists to make impossible:

  F1 — `coerce_field` checks "is it a str" BEFORE it checks "is this the one
       field allowed to be a str". Every field can then carry text, and the
       no-free-text guarantee stops being structural — it becomes a promise that
       a validator is correct.
  S3 — the spool goes back to read-POST-truncate. Between the read and the
       truncate another process appends, and the append that gets destroyed
       belongs to whichever command the user ran to recover. That collision — a
       `--doctor` while serve flushes — IS the flagship recovery flow.

⭐ AND THE POLARITY ONE, F3: the id guard reverts to `^[A-Za-z0-9]{20}$`, which
rejects EVERY real id. Every rejection test still passes; the feature silently
never works. That is why `test_a_real_research_id_is_ACCEPTED` is the first test
in the file rather than the last.

⭐ Over-corrections:
  C2  — `classify_exception` reads `str(exc)`, which on this codebase means paths
        with the OS account name, hostnames, and a Firebase Web API key that
        appeared 5,047 times in one log.
  D5  — the flush joins its thread WITHOUT a deadline, so a machine with dead DNS
        holds the user's command inside a name lookup — telemetry becoming the
        reason the product feels broken.
  T2  — the spool trim drops the NEWEST half, i.e. exactly the events describing
        whatever is going wrong right now.

    python .mutants/telemetry_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "telemetry.py"
CAT = "telemetry_catalogue.json"
MUTATED_FILES = [SRC, CAT, "research.py"]

T = "tests/test_telemetry_0818.py"
# ⛔ The 08-18 stranded-batch wave pinned the spool's recovery AND the two
# attribution bugs. A harness scoped to its own file alone reported those as
# suite gaps when the suite covers them — the harness had the gap.
T_STRANDED = "tests/test_telemetry_stranded_batch_0818.py"
ALL = [T, T_STRANDED]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str], str]] = [

    # ══ no free text, by construction ═══════════════════════════════════
    ("F1", "under", "⛔⛔ the str check moves ABOVE the field-name check, so EVERY "
     "field can carry text and the guarantee stops being structural",
     [('''    if name == "research_id" and isinstance(value, str):
        if _valid_research_id(value):
            return value
        raise TelemetryFieldError(name)
    raise TelemetryFieldError(name)''',
       '''    if isinstance(value, str):
        if _valid_research_id(value) or name != "research_id":
            return value
        raise TelemetryFieldError(name)
    raise TelemetryFieldError(name)''')], [T], SRC),
    ("F2", "under", "⛔ `**kwargs` returns to the signature, and with it every "
     "field nobody named",
     [('def tm_emit(event: Ev, *,\n            phase: "int | None" = None,',
       'def tm_emit(event: Ev, *, _extra=None, **kwargs,\n            phase: "int | None" = None,')], [T], SRC),
    ("F3", "over", "⭐ the id guard reverts to the shape that rejects EVERY real "
     "id — a feature that silently never works",
     [('RESEARCH_ID_RE = re.compile(r"^chat_[0-9]{13}_[0-9]{1,6}$")',
       'RESEARCH_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")')], [T], SRC),
    ("F4", "under", "the id guard accepts anything, so a topic arrives by looking "
     "vaguely id-shaped",
     [('RESEARCH_ID_RE = re.compile(r"^chat_[0-9]{13}_[0-9]{1,6}$")',
       'RESEARCH_ID_RE = re.compile(r"^.*$")')], [T], SRC),
    ("F5", "under", "the run_id suffix denial goes, and a one-word topic survives "
     "safe_name as bare alphanumerics",
     [('    return bool(RESEARCH_ID_RE.match(text)) and not RUN_ID_SUFFIX_RE.search(text)',
       '    return bool(RESEARCH_ID_RE.match(text))')], [T], SRC),
    ("F6", "under", "an unexpected field is dropped in silence, so absence reads "
     "as health",
     [('''            log.debug("telemetry: %s does not carry %s", ev.name, name)
            _spool({"ev": int(Ev.TELEMETRY_INVALID), "d": {"count": 1}})''',
       '''            log.debug("telemetry: %s does not carry %s", ev.name, name)''')], [T], SRC),
    ("F7", "over", "⛔ the rejection report includes the VALUE, so the leak report "
     "becomes the leak",
     [('            log.warning("telemetry: %s rejected field %s (wrong type)", ev.name, name)',
       '            log.warning("telemetry: %s rejected field %s = %r", ev.name, name, value)')], [T], SRC),
    ("F8", "under", "a wrong-typed field aborts the whole event instead of being "
     "dropped, so one bad call site silences a whole flow",
     [('        except TelemetryFieldError:\n            log.warning("telemetry: %s rejected field %s (wrong type)", ev.name, name)',
       '        except TelemetryFieldError:\n            raise')], [T], SRC),
    ("F9", "under", "the per-event field allowlist is ignored, so any event "
     "carries any field",
     [('        if name not in allowed:', '        if False:')], [T], SRC),

    # ══ the error vocabulary ════════════════════════════════════════════
    ("C1", "under", "every failure becomes UNKNOWN, so the tier reports that "
     "something broke and never which thing",
     [('    if isinstance(exc, socket.gaierror):\n        return ErrorClass.DNS',
       '    if False:\n        return ErrorClass.DNS')], [T], SRC),
    ("C2", "over", "⛔⛔ the classifier reads str(exc) — paths with the OS account "
     "name, hostnames, and a Firebase Web API key that appeared 5,047 times",
     [('    name = type(exc).__name__',
       '    name = type(exc).__name__ + str(exc)')], [T], SRC),
    ("C3", "under", "an HTTP status on the response is ignored, so a 403 and a "
     "503 read the same",
     [('    if isinstance(status, int):', '    if False:')], [T], SRC),
    ("C4", "under", "the corrected verify vocabulary reverts to describing HOW a "
     "check runs rather than what a call site knows",
     [('''class VerifyStatus(IntEnum):''', '''class VerifyStatus_UNUSED(IntEnum):''')], [T], SRC),
    ("C5", "under", "Platform stops failing closed, so an unmapped agent name "
     "could reach the wire as itself",
     [('    OTHER = 0\n    CHATGPT = 1', '    CHATGPT = 1')], [T], SRC),

    # ══ the spool ═══════════════════════════════════════════════════════
    ("S1", "under", "one shared spool file for every process, which is what makes "
     "a concurrent append destroyable",
     [('''    if worker is None:
        return _telemetry_dir() / "pending-cli.jsonl"
    return _telemetry_dir() / f"pending-w{int(worker)}.jsonl"''',
       '''    return _telemetry_dir() / "pending-cli.jsonl"''')], [T], SRC),
    ("S2", "under", "the claim is a copy rather than a rename, so the original "
     "keeps its events and they are delivered twice forever",
     [('        os.replace(str(path), str(claimed))',
       '        claimed.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")')], [T], SRC),
    ("S3", "under", "⛔⛔ READ-POST-TRUNCATE returns. A concurrent --doctor's "
     "append is destroyed between the read and the truncate — and that append "
     "belongs to whichever command the user ran to recover",
     [('''        claimed = path if ".sending." in path.name else _claim(path)
        if claimed is None:
            continue''',
       '''        claimed = path
        try:
            claimed.read_text(encoding="utf-8")
        except OSError:
            continue''')], [T], SRC),
    ("S4", "under", "the claimed file is deleted BEFORE the post, so a failed "
     "delivery loses everything it was carrying",
     [('''        ok = _post_with_deadline(sender, batch, deadline_sec)
        if ok:''',
       '''        try:
            claimed.unlink()
        except OSError:
            pass
        ok = _post_with_deadline(sender, batch, deadline_sec)
        if ok:''')], [T], SRC),
    ("S5", "under", "a failed delivery drops the owed events instead of merging "
     "them back",
     [('        else:\n            _merge_back(claimed, _unclaimed_name(path))',
       '        else:\n            pass')], [T], SRC),
    ("S6", "under", "the merge-back throws away whatever arrived while the "
     "delivery was in flight",
     [('        path.write_text(owed + newer, encoding="utf-8")',
       '        path.write_text(owed, encoding="utf-8")')], [T], SRC),
    ("S7", "under", "a file a dead process claimed is never picked back up, so "
     "one crash strands its events forever",
     [('    stranded = [p for p in everything if ".sending." in p.name and _adoptable(p)]',
       '    stranded = []')], [T], SRC),
    ("S8", "under", "⛔ FOUND BY MUTATION. A file a LIVE sibling is mid-POST on is "
     "adopted and posted a second time, doubling the traffic of the quietest "
     "thing in the product",
     [('    stranded = [p for p in everything if ".sending." in p.name and _adoptable(p)]',
       '    stranded = [p for p in everything if ".sending." in p.name]')], [T], SRC),
    ("S9", "under", "the liveness check inverts, so only files a LIVE process "
     "holds are adopted and genuinely stranded ones never are",
     [('    return not _pid_alive(pid)', '    return _pid_alive(pid)')], [T], SRC),

    # ══ bounds ══════════════════════════════════════════════════════════
    ("T1", "under", "the spool is unbounded, so an offline machine grows one file "
     "until the disk is the problem",
     [('    if len(lines) <= SPOOL_MAX_LINES:\n        return',
       '    if True:\n        return')], [T], SRC),
    ("T2", "over", "⛔ the NEWEST half is dropped — exactly the events describing "
     "whatever is going wrong right now",
     [('    keep = lines[len(lines) // 2:]', '    keep = lines[:len(lines) // 2]')], [T], SRC),
    ("T3", "under", "the drop is silent, so a count nobody can trust reads as a "
     "complete record",
     [('''    keep.append(json.dumps(
        _envelope({"ev": int(Ev.TELEMETRY_DROPPED), "d": {"count": dropped}}),
        separators=(",", ":")))''', '''    pass''')], [T], SRC),
    ("T4", "under", "the age cap goes, so month-old events are still delivered "
     "and a stale spool is never cleared",
     [('            if float(record.get("t", 0)) / 1000.0 < cutoff:\n                continue',
       '            if False:\n                continue')], [T], SRC),
    ("T5", "under", "a batch is unbounded, so one POST carries a whole offline "
     "month and is refused as too large",
     [('    batch = [r for r, _l in fresh[:BATCH_MAX_EVENTS]]', '    batch = [r for r, _l in fresh]')],
     [T], SRC),
    ("T6", "under", "⛔⛔ FOUND BY MUTATION, AND IT WAS REAL. The events past the "
     "batch cap are deleted with the claimed file instead of staying owed — and "
     "an offline machine's spool is exactly where a batch hits that cap",
     [('            if owed:\n                _write_back(owed, path)', '            pass')],
     [T], SRC),
    ("T7", "under", "the write-back drops whatever arrived while the batch was in "
     "flight",
     [('        path.write_text("\\n".join(lines) + "\\n" + newer, encoding="utf-8")',
       '        path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")')], [T], SRC),

    # ══ delivery discipline ═════════════════════════════════════════════
    ("D1", "under", "the flush blocks on the network with no deadline at all",
     [('    thread.join(max(0.1, float(deadline_sec)))', '    thread.join()')], [T], SRC),
    ("D2", "under", "an abandoned post is reported as delivered, so its events "
     "are deleted while still owed",
     [('''    if thread.is_alive():
        log.debug("telemetry: post abandoned at the %.1fs deadline", deadline_sec)
        return False''', '''    if thread.is_alive():
        return True''')], [T], SRC),
    ("D3", "under", "the post thread is not a daemon, so an unfinished flush "
     "holds the interpreter open at exit",
     [('    thread = threading.Thread(target=_run, name="telemetry-post", daemon=True)',
       '    thread = threading.Thread(target=_run, name="telemetry-post")')], [T], SRC),
    ("D4", "under", "the background flush is not a daemon either",
     [('        name="telemetry-flush", daemon=True)', '        name="telemetry-flush")')], [T], SRC),
    ("D5", "over", "⛔ a Ctrl+C inside a flush escapes the daemon thread and "
     "prints a traceback from telemetry during the user's clean exit",
     [('        except BaseException as exc:', '        except Exception as exc:')], [T], SRC),
    ("D6", "under", "an ID token becomes mandatory, so the events worth having "
     "most — the ones from a machine that cannot sign in — never go",
     [('    token = _id_token()\n    if token:',
       '    token = _id_token()\n    if not token:\n        return False\n    if True:')], [T], SRC),
    ("D6b", "under", "⛔⛔ the auth scheme goes back to `Firebase`, which the "
     "route's verifier does not accept — every batch stores unattributed",
     [('        headers["Authorization"] = f"Bearer {token}"',
       '        headers["Authorization"] = f"Firebase {token}"')], [T, T_STRANDED], SRC),
    ("D6c", "under", "a missing id-token ACCESSOR goes back to being "
     "indistinguishable from a signed-out machine",
     [('        log.debug("telemetry: no id-token accessor (%s) — batches will be "\n                  "anonymous", type(exc).__name__)\n', '')], [T, T_STRANDED], SRC),

    # ══ transparency and the switch ═════════════════════════════════════
    ("M1", "under", "the local mirror stops being written, so the claim that a "
     "user can see exactly what leaves is no longer true under --pair",
     [('        _mirror(record)\n', '')], [T], SRC),
    ("M2", "under", "the kill switch is ignored",
     [('''    return os.environ.get("SR_TELEMETRY", "1").strip().lower() not in (
        "0", "off", "false", "no")''', '''    return True''')], [T], SRC),
    ("M3", "under", "a spool write failure raises into the caller, so telemetry "
     "can take down the thing it is measuring",
     [('    except Exception as exc:\n        log.debug("telemetry: spool write failed (%s)", type(exc).__name__)\n        return False',
       '    except Exception as exc:\n        raise')], [T], SRC),
    ("M4", "under", "the sequence stops advancing, so two events in the same "
     "millisecond are indistinguishable at read time",
     [('        _seq += 1\n        return _seq', '        return _seq')], [T], SRC),

    # ══ the two repos that read the catalogue ═══════════════════════════
    ("X1", "under", "⛔ the checked-in catalogue drifts from the module, so the "
     "newest events 400 at the route and drop silently",
     [('"PIPELINE_ERROR": 48', '"PIPELINE_ERROR": 480')], [T], CAT),
    ("X4", "under", "⛔⛔ a pairing event returns to the catalogue with no call site "
     "— at read time that is indistinguishable from an event that never happens, "
     "and it is how ten of these got in",
     [('    PAIR_CODE_SHOWN = 3', '    PAIR_CODE_SHOWN = 3\n    PAIR_CLAIMED = 4'),
      ('    Ev.PAIR_CODE_SHOWN: (),', '    Ev.PAIR_CODE_SHOWN: (),\n    Ev.PAIR_CLAIMED: ("duration_ms",),')],
     [T], SRC),
    ("X5", "under", "a surviving event is renumbered, which silently reinterprets "
     "every batch already stored",
     [('    PAIR_COMPLETED = 10', '    PAIR_COMPLETED = 14')],
     [T], SRC),
    ("X2", "under", "an event ships with no field declaration, so nothing knows "
     "what it may carry",
     [('    Ev.PIPELINE_ERROR: ("research_id", "phase", "platform", "error_class"),\n', '')],
     [T], SRC),
    ("X3", "under", "the telemetry logger leaves the bridge, and becomes the "
     "seventh module logging into a void",
     [('_BRIDGED_LOGGERS = ("auth", "vision", "selfheal", "narrate", "telemetry")',
       '_BRIDGED_LOGGERS = ("auth", "vision", "selfheal", "narrate")')], [T], "research.py"),
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
