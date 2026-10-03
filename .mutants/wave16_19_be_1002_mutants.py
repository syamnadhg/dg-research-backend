"""Mutation harness — Wave 16 (one log folder per research) and Wave 19 (one
short name), the research computer's half (10-02). Run ONCE, on the new lines.

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  W*  one folder per research: a reopened run.log adopts its tail segments; a
      later attempt continues a folder carrying its first start, counters,
      attempts and events; the same research's retry JOINS the armed sink with
      one line and ends only itself; a pick-up continues only a finished folder
      of the same person, made by this build; the dead-or-alive ceiling counts
      from the current attempt; Move to queue marks the folder "moved" and
      nothing writes it back; the private run's purge waits for the outer
      attempt; the crash retry and the worker say why; Retry and the login
      resume carry the person.
  N*  one short name: the record's name is used unless it is a placeholder or
      the topic itself; the person's rename wins; made once, by the web's namer
      only on a computer connected to the app, never for a private run, and
      written back only when the record was read; the shape is five words /
      forty characters on a word boundary; the notebook, the podcast file, the
      mp3's title and the Podcasts row take the name; the podcast's name never
      reaches the log; a run the chat assistant started is named at pick-up.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/wave16_19_be_1002_mutants.py
  .venv/bin/python .mutants/wave16_19_be_1002_mutants.py W1 N2

⭐ Run once on 2026-10-02 against 187c1a5: 57/58 killed; the one survivor (W16)
was equivalent and is retired below with the reason.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

#: The tests the mutants are measured by (names joined into one string, never a
#: `*.py` value in a row: the anchor sweep reads those as target files).
_TESTS = " ".join("tests/" + n + ".py" for n in (
    "test_one_log_folder_per_research_w16", "test_run_log_capture_0818",
    "test_one_short_name_w19", "test_incognito_backend_log_109",
    "test_late_writers_name_their_run_109"))
SUITES = {RESEARCH: (ROOT, _TESTS)}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
       "PYTHONPATH": str(ROOT)}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── W: one log folder per research ──────────────────────────────────────
    ('W1', RESEARCH, '⛔ a reopened run.log adopts none of its tail — it starts again '
                     'at overflow1 and the newest-two rule breaks',
     [('        old = self._segments_on_disk()\n        if old:\n',
       '        old = []\n        if old:\n')]),
    ('W2', RESEARCH, '⛔ a reopened log keeps every old segment, more than it keeps',
     [('            for index in old[:-self.keep]:\n',
       '            for index in old[:0]:\n')]),
    ('W3', RESEARCH, '⛔ a reopened overflowed log writes as though under its head cap',
     [('            self._live_segments = old[-self.keep:]\n            self._in_overflow = True\n',
       '            self._live_segments = old[-self.keep:]\n            self._in_overflow = False\n')]),
    ('W4', RESEARCH, 'the adopted tail is counted as empty, so it outgrows its size',
     [('                self._seg_written = tail.stat().st_size\n',
       '                self._seg_written = 0\n')]),
    ('W5', RESEARCH, '⛔ any file named like a segment is taken for one — overflowX crashes the writer',
     [('            if name.startswith(prefix) and rest.isascii() and rest.isdigit():\n',
       '            if name.startswith(prefix):\n')]),
    ('W6', RESEARCH, '⛔⛔ a continued folder forgets when the research first ran',
     [('        self.first_started_utc = str(prior.get("firstStartedUtc")\n'
       '                                     or prior.get("startedUtc") or self.started_utc)\n',
       '        self.first_started_utc = self.started_utc\n')]),
    ('W7', RESEARCH, 'the counters start again at zero in a continued folder',
     [('                self.counters[key] = int(old_counters.get(key) or 0)\n',
       '                self.counters[key] = 0\n')]),
    ('W8', RESEARCH, '⛔ a continued folder forgets its earlier attempts',
     [('        self.attempts = [dict(a) for a in (prior.get("attempts") or [])\n',
       '        self.attempts = [dict(a) for a in ([])\n')]),
    ('W9', RESEARCH, 'an attempt a move left behind is closed as a death',
     [('                else ("moved" if why == "moved" else "process-died"))\n',
       '                else "process-died")\n')]),
    ('W10', RESEARCH, '⛔ a continued folder loses its earlier events',
     [('                kept = kept[-RUN_LOG_EVENT_CAP:]\n            self.events = kept\n',
       '                kept = kept[-RUN_LOG_EVENT_CAP:]\n            self.events = []\n')]),
    ('W11', RESEARCH, '⛔⛔ a joined retry keeps the first attempt\'s start — five hours in, '
                      'it reads dead while it runs',
     [('        self.close_attempt(ended_status)\n        self.started_utc = _utc_iso()\n',
       '        self.close_attempt(ended_status)\n')]),
    ('W12', RESEARCH, 'the folder\'s attempt number is not the joined attempt\'s',
     [('        self.started_mono = time.monotonic()\n        self.attempt = int(attempt or 0)\n'
       '        self.attempts.append(self._new_attempt(why))\n',
       '        self.started_mono = time.monotonic()\n'
       '        self.attempts.append(self._new_attempt(why))\n')]),
    ('W13', RESEARCH, '⛔ a joined retry adds no attempt',
     [('        self.attempt = int(attempt or 0)\n        self.attempts.append(self._new_attempt(why))\n'
       '        self.write_meta("running")\n',
       '        self.attempt = int(attempt or 0)\n        self.write_meta("running")\n')]),
    ('W14', RESEARCH, '⛔⛔ the move is forgotten — the exit writes "cancelled" over it',
     [('        self.close_attempt("moved")\n        self.forced_status = "moved"\n',
       '        self.close_attempt("moved")\n')]),
    ('W15', RESEARCH, '⛔ an attempt ending after a move writes "running" back — the '
                      'folder reads live again',
     [('        if self.forced_status:\n            status = self.forced_status\n',
       '        if False:\n            status = self.forced_status\n')]),
    # W16 RETIRED after the one run (10-02, 57/58 with W16 the survivor): it
    # dropped `status = self.forced_status or status` from `finalize`, and that
    # is EQUIVALENT — `write_meta` already puts the forced "moved" on every meta
    # write (W15 measures that), and the attempt `finalize` would close is
    # already closed by `mark_moved`. A survivor that no input can tell apart
    # is a harness fault, not a hole.
    ('W17', RESEARCH, '⛔⛔ a retry of the same research never joins — a folder per attempt again',
     [('            if parent is not None and _same_research(parent.research_id,\n'
       '                                                     self.research_id):\n',
       '            if False:\n')]),
    ('W18', RESEARCH, 'the line counts the attempt wrong',
     [('                    f"=== browser restarted — attempt {self.attempt + 1} of "\n',
       '                    f"=== browser restarted — attempt {self.attempt} of "\n')]),
    ('W19', RESEARCH, 'every retry says the browser restarted',
     [('                crashed = self.why == "browser-restart"\n',
       '                crashed = True\n')]),
    ('W20', RESEARCH, '⛔⛔ one person\'s attempt is written into another person\'s folder',
     [('        if meta.get("submitterUid") != submitter_uid:\n            continue\n', '')]),
    ('W21', RESEARCH, '⛔⛔ two processes write one run.log — a live folder is continued',
     [('        if _folder_is_live(folder) or str(folder) in live:\n            return None\n', '')]),
    ('W22', RESEARCH, 'an older build\'s split folder is merged into',
     [('        if not isinstance(meta.get("attempts"), list):\n            continue\n', '')]),
    ('W23', RESEARCH, '⛔⛔ a joined retry pops and finalizes the folder the outer run still writes',
     [('            if self.joined:\n', '            if False:\n')]),
    ('W24', RESEARCH, '⛔ a joined retry purges a private run under the outer attempt — '
                      'its folder outlives the run',
     [('        if not getattr(_capture, "joined", False):\n', '        if True:\n')]),
    ('W25', RESEARCH, 'the crash retry gives no reason — its line says nothing of a restart',
     [('                           _log_reason=("browser-restart" if _is_browser_crash\n'
       '                                        else "retry"),\n',
       '                           _log_reason=None,\n')]),
    ('W26', RESEARCH, 'the worker gives no reason for a pick-up',
     [('                                     _log_reason=("moved" if job.get("moved_run")\n'
       '                                                  else "resumed" if job.get("resume_dir")\n'
       '                                                  else None),\n',
       '                                     _log_reason=None,\n')]),
    ('W27', RESEARCH, '⛔ the reason reaches run_pipeline, which has no such parameter',
     [('    _why = kwargs.pop("_log_reason", None)\n',
       '    _why = kwargs.get("_log_reason", None)\n')]),
    ('W28', RESEARCH, '⛔⛔ Move to queue leaves its folder reading live',
     [('    _mark_run_log_moved(rid)\n    _schedule_server_exit("requeue", delay_sec=1.5)\n',
       '    _schedule_server_exit("requeue", delay_sec=1.5)\n')]),
    ('W29', RESEARCH, 'a move marks whatever research is armed',
     [('    if sink is None or not _same_research(sink.research_id, research_id):\n',
       '    if sink is None:\n')]),
    ('W30', RESEARCH, '⛔ a Retry drops the person again',
     [('                "submitted_by": sb,\n', '')]),
    ('W31', RESEARCH, '⛔ the Retry caller passes no person',
     [('                    submitted_by=data.get("submittedBy"))\n',
       '                    submitted_by=None)\n')]),
    ('W32', RESEARCH, 'the login pause records no person',
     [('        "submitted_by": _run_submitted_by(),\n', '        "submitted_by": None,\n')]),
    ('W33', RESEARCH, 'the login resume passes no person',
     [('            submitted_by=plan.get("submitted_by"))\n', '            submitted_by=None)\n')]),

    # ── N: one short name ───────────────────────────────────────────────────
    ('N1', RESEARCH, '⛔⛔ the person\'s own rename is named over when it is the topic',
     [('    if title and (bool(record.get("titleLocked"))\n'
       '                  or not _research_name_missing(title, topic)):\n',
       '    if title and not _research_name_missing(title, topic):\n')]),
    ('N2', RESEARCH, '⛔ "New Research" and the whole topic are taken for names',
     [('    return (not t or t.lower() in _RESEARCH_NAME_PLACEHOLDERS\n'
       '            or _is_the_topic(t, topic))\n',
       '    return not t\n')]),
    ('N3', RESEARCH, '⛔ the agent\'s topic is not recognised once the pipeline flattened it',
     [('    return bool(t) and t == " ".join(str(topic or "").split())\n',
       '    return bool(t) and t == str(topic or "").strip()\n')]),
    ('N4', RESEARCH, 'the name is made again on every use',
     [('    made = _RESEARCH_NAMES_MADE.get((uid, rid)) if rid else None\n',
       '    made = None\n')]),
    ('N5', RESEARCH, '⛔ a record that could not be read is written on a guess',
     [('    if found and not private and not bool(record.get("titleLocked")):\n',
       '    if not private and not bool(record.get("titleLocked")):\n')]),
    ('N6', RESEARCH, '⛔⛔ a private run\'s topic is sent to be named',
     [('    asks = bool(_firebase_db) and not private\n', '    asks = bool(_firebase_db)\n')]),
    ('N7', RESEARCH, '⛔ a computer with no app connection reaches for the keystore to ask',
     [('    asks = bool(_firebase_db) and not private\n', '    asks = not private\n')]),
    ('N8', RESEARCH, '⛔⛔ a private run\'s name is written onto its record',
     [('    if found and not private and not bool(record.get("titleLocked")):\n',
       '    if found and not bool(record.get("titleLocked")):\n')]),
    ('N9', RESEARCH, '⛔ the name is cut mid-word, past forty characters',
     [('        if len(longer) > _RESEARCH_NAME_MAX_CHARS:\n            break\n', '')]),
    ('N10', RESEARCH, 'seven words again',
     [('    words = s.split()[:_RESEARCH_NAME_MAX_WORDS]\n', '    words = s.split()[:7]\n')]),
    ('N11', RESEARCH, 'a brief\'s heading marks become the name',
     [('        line = line.strip().lstrip("#").strip()\n', '        line = line.strip()\n')]),
    ('N12', RESEARCH, 'the namer is waited on for half a minute',
     [('                              timeout=_RESEARCH_NAME_TIMEOUT_S)\n',
       '                              timeout=30)\n')]),
    ('N13', RESEARCH, 'a refusal from the namer goes unsaid',
     [('        if getattr(resp, "status_code", 0) != 200:\n'
       '            log(f"[name] the web\'s namer answered',
       '        if False:\n'
       '            log(f"[name] the web\'s namer answered')]),
    ('N14', RESEARCH, '⛔⛔ the pick-up names a web run the web is naming — they race',
     [('            or not _is_the_topic(title, topic)):\n        return ""\n',
       '            or False):\n        return ""\n')]),
    ('N15', RESEARCH, '⛔ a run the chat assistant started is never named at pick-up',
     [('            await asyncio.to_thread(_name_an_agent_started_run, uid,\n'
       '                                    research_id or run_id, topic)\n',
       '            pass\n')]),
    ('N16', RESEARCH, '⛔⛔ the notebook is named with the whole topic again',
     [('            title = (await asyncio.to_thread(_research_name, topic, _fb_uid,\n'
       '                                             _fb_research_id)) or "Research"\n',
       '            title = topic or "Research"\n')]),
    ('N17', RESEARCH, '⛔⛔ the podcast file keeps NotebookLM\'s name',
     [('        audio_path = _p3_name_podcast_file(audio_path, _podcast_name)\n', '')]),
    ('N18', RESEARCH, 'the mp3 is not handed the name',
     [('                                             title=_podcast_name)\n',
       '                                             title="")\n')]),
    ('N19', RESEARCH, 'the mp3 keeps NotebookLM\'s title inside it',
     [('             *(["-metadata", f"title={named}"] if named else []),\n', '')]),
    ('N20', RESEARCH, 'a name with nothing file-safe left gives an empty file name',
     [('    stem = safe_name(str(name), max_len=_P3_PODCAST_NAME_MAX).strip("_") or "podcast"\n',
       '    stem = safe_name(str(name), max_len=_P3_PODCAST_NAME_MAX).strip("_")\n')]),
    ('N21', RESEARCH, 'a podcast with no name to take is renamed "podcast"',
     [('    if not str(name or "").strip():\n        return path  # no name to give it',
       '    if False:\n        return path  # no name to give it')]),
    ('N22', RESEARCH, '⛔ the Podcasts row is named without the topic — an agent\'s whole '
                      'topic shows as the name',
     [('            _research_name, _p3_run_topic(audio_path.parent.parent), _fb_uid,\n',
       '            _research_name, "", _fb_uid,\n')]),
    ('N23', RESEARCH, '⛔ the resumed podcast\'s name reaches the log',
     [('        log(f"Phase 3: the podcast on disk ({audio_path.suffix.lower() or \'no type\'}) "\n'
       '            f"did not reach the app',
       '        log(f"Phase 3: the podcast on disk ({audio_path.name}) "\n'
       '            f"did not reach the app')]),
    ('N24', RESEARCH, '⛔ the transcoded podcast\'s name reaches the log',
     [('                f"({len(dst.stem)}-char name)")\n', '                f"{dst.name}")\n')]),
    ('N25', RESEARCH, '⛔ the renamed podcast\'s name reaches the log',
     [('        f"({len(stem)} chars, {path.suffix.lower() or \'no type\'})")\n',
       '        f"({stem})")\n')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
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
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
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
            if green(*SUITES[fname]):
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
