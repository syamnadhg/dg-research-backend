"""Wave 10.9 (#536, the machine half) — can the guards see a research computer
going back to keeping an incognito run?

The promise is "nothing stays in Super Research once the run ends". The app can
stop writing what it used to write and the rules can refuse what a browser or a
wheel sends, but the PIPELINE runs on this machine: it names the queue folder,
writes the logs, uploads the podcast, posts the notices, stamps the expiry and
recreates a record that was purged. Every mutant below is a way one of those
could go back to what it was while the code still looks like it learned.

The ones that matter most are the quiet ones:

  I2  — the id predicate loses its end anchor, so `incog_…-copy` becomes
        ephemeral: somebody's ordinary research hidden from them for good.
  I3  — the predicate answers False for everything. Nothing breaks, no test
        about an ordinary run fails, and the whole feature is decoration.
  I8  — the incognito run id drops the research id, so every incognito run of
        one second shares a queue directory and writes over the other's
        documents.
  I13 — the telemetry id is dropped for EVERYBODY, which loses the join for
        every ordinary run while looking like a privacy fix.
  N2  — the document scrub is skipped along with the upload, which writes the
        agents' signed file links into the text the email carries.
  C5  — the claim fallback recreates a purged incognito record, the exact
        resurrection the rules and this code both exist to refuse.

⛔ THOSE TWO IDS WERE WRONG UNTIL 2026-09-22: this list said N4 and C2, which
are "no run publishes its podcast at all" and "every write becomes an update".
A reader triaging a survivor by the name printed beside it was sent to the
wrong seam, which is how the wrong repair gets made under time pressure.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED. The tests run as
`sys.executable -m pytest` from the repo root, so `-m` puts this checkout first
on sys.path — which is what makes a worktree measure itself rather than the
editable install the venv points at.

⛔ SR_WEB_REPO IS REQUIRED. The capability suite's parity pins read the web
repo's `incognito.ts` and rules, and a SKIP here would read as "the suite was
fine with this mutant".

  SR_WEB_REPO=<web checkout> <venv>/bin/python -u \\
      .mutants/wave109_incognito_machine_mutants.py
  SR_WEB_REPO=<web checkout> <venv>/bin/python -u \\
      .mutants/wave109_incognito_machine_mutants.py I3 I8
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_incognito_capability_109.py "
          "tests/test_incognito_live_progress_109.py "
          "tests/test_incognito_run_id_and_logs_109.py "
          "tests/test_incognito_machine_skips_109.py "
          "tests/test_incognito_expiry_109.py "
          "tests/test_incognito_no_resurrection_109.py "
          "tests/test_incognito_teardown_109.py "
          "tests/test_pending_queue_keeps_nothing_109.py "
          "tests/test_handoff_is_the_end_109.py "
          "tests/test_cloud_handoff_record_108.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the predicate and the mint ─────────────────────────────────────
ID_RE = '_INCOGNITO_ID_RE = re.compile(r"^incog_[0-9]{13}_[0-9]{1,6}$")'
PREDICATE = ('    return isinstance(research_id, str) and '
             'bool(_INCOGNITO_ID_RE.match(research_id))')
MINT_INCOG = ('    if _is_incognito_research(research_id):\n'
              '        return f"incognito_{research_id.removeprefix(\'incog_\')}_{stamp}"')
MINT_PLAIN = '    return f"{safe_name(topic)}_{stamp}"'
LOG_TOPIC = ('    if _is_incognito_research(research_id):\n'
             '        return _BUNDLE_TOPIC_MARK\n'
             '    return str(topic or "")[:limit]')

# ── anchors: the device capability ──────────────────────────────────────────
CAP_CONST = "_INCOGNITO_RUNS_CAPABILITY = 1"
CAP_SOURCE = ('        return {"version": None, "updateAvailable": None, "sourceCheckout": True,\n'
              '                "servingVersion": None,\n'
              '                "incognitoRuns": _INCOGNITO_RUNS_CAPABILITY}')
CAP_INSTALLED = ('    return {"version": version, "updateAvailable": update_available,\n'
                 '            "sourceCheckout": False, "servingVersion": serving,\n'
                 '            "incognitoRuns": _INCOGNITO_RUNS_CAPABILITY}')

# ── anchors: the consumers ──────────────────────────────────────────────────
# ⛔ THE COMMENT IS PART OF THE ANCHOR. The idle-rescan mints with the same
# call at the same indentation, so the bare line matches twice and the mutant
# would measure nothing while reporting a kill.
LISTENER_MINT = ("            # Generate run_id\n"
                 "            run_id = _mint_run_id(topic, research_id)")
LISTENER_DEFER = ('                        f"topic={_loggable_topic(topic, research_id)!r} '
                  "submittedBy={(data.get('submittedBy') or '?')[:8]} \"\n"
                  '                        f"reason={_defer_reason}",')
LISTENER_CLAIMED = ('                    log(f"[start-listener] worker {WORKER_ID}: claimed '
                    '{research_id[:8]}… topic={_loggable_topic(topic, research_id)!r} '
                    "submittedBy={(data.get('submittedBy') or '?')[:8]}\", \"INFO\")")
LISTENER_MISSING = ('                log(f"Firestore start request missing fields: uid={uid}, '
                    'rid={research_id}, topic={_loggable_topic(topic, research_id, 30)}", "WARN")')

# ── anchors: telemetry ──────────────────────────────────────────────────────
TM_ID = "    return None if _is_incognito_research(research_id) else research_id"
TM_TAP = "    rid = _tm_research_id(rid)"
TM_STARTED = ("            tm.tm_emit(tm.Ev.RUN_STARTED,\n"
              "                       research_id=_tm_research_id(self.research_id),\n"
              "                       worker=WORKER_ID)")
TM_FINISHED = "                       research_id=_tm_research_id(sink.research_id),"

# ── anchors: the writes that outlive a run ──────────────────────────────────
IMG_SKIP = ("        if _is_incognito_research(rid):\n"
            '            log(f"[{label}] document images: a run that keeps nothing stores "\n'
            '                "none — every image becomes a caption", "INFO")\n'
            "            raise _DocImgStopRequested()")
FUNNEL = "    return _doc_scrub_private_links(await _doc_images_rehost(text, label))"
AUDIO_SKIP = ('    if _is_incognito_research(research_id):\n'
              '        log("[Phase3] a run that keeps nothing publishes no podcast — no Storage "\n'
              '            "object, no audios row, no audio_file link", "INFO")\n'
              '        return ""')
AUDIO_FALLTHROUGH = (
    '        log("[Phase3] Firebase Storage upload failed — audio still saved locally", "WARN")\n'
    "    except Exception as e:\n"
    '        log(f"Audio Firestore/Storage sync failed: {e}", "WARN")\n'
    '    return ""')
P3_REPORT_INCOG = ("    if _is_incognito_research(research_id):\n"
                   "        return (_P3_KEEPS_NOTHING_REASON, _P3_KEEPS_NOTHING_DETAIL)")
P3_REPORT_REASON = '_P3_KEEPS_NOTHING_REASON = "No podcast — this research keeps nothing"'
# ⛔ The CALL SITE is mutated by `links_out_summary_in_0828` (P5), whose suites
# include the phase-3 gate file. One address, one owner.
NOTICE_SKIP = ('    if _is_incognito_research(research_id):\n'
               '        log(f"phase-notify: {research_id[:8]}… keeps nothing — no notice asked for",\n'
               '            "INFO")\n'
               "        return False")
INDEX_SKIP = ('        if _is_incognito_research(row.get("researchId")):\n'
              "            continue")
RECOVERY_STOP = ('    if _is_incognito_research(research_id):\n'
                 '        return {\n'
                 '            "status": "stopped",')
REHYDRATE_STOP = ("                if _is_incognito_research(research_id):\n"
                  "                    if _update_research_doc(tree_uid, research_id,\n"
                  "                                            _restart_recovery_patch(research_id)):")
RECONCILE_PATCH = "        _patch = _restart_recovery_patch(research_id)"

# ── anchors: the fuse ───────────────────────────────────────────────────────
EXPIRE_HOURS = "_INCOGNITO_EXPIRE_HOURS = 24"
EXPIRE_GATE = ("    if not _is_incognito_research(research_id):\n"
               "        return None")
EXPIRE_BASE = "    base = now if now is not None else datetime.now(timezone.utc)"
DOC_EXPIRE = ('                    **({"expireAt": _expire_at} if _expire_at else {}),')
EVENT_EXPIRE = ('        "expireAt": (_incognito_expire_at(_fb_research_id)\n'
                "                     or datetime.now(timezone.utc) + timedelta(days=30)),")

# ── anchors: never bringing a purged record back ────────────────────────────
WRITE_GATE = ("    if not _is_incognito_research(research_id):\n"
              "        return doc_ref.set(payload, merge=merge)\n"
              "    return doc_ref.update(_merge_field_paths(payload))")
PATHS_DESCEND = ("            for inner, inner_value in value.items():\n"
                 '                _expand(f"{path}.{inner}", inner_value)')
PATHS_GUARD = ("        if (type(value) is dict and value\n"
               "                and all(isinstance(k, str) and _FIELD_PATH_SEGMENT_RE.match(k)\n"
               "                        for k in value)):")
PATHS_TOP_GUARD = ("        if _FIELD_PATH_SEGMENT_RE.match(str(key)):\n"
                   "            _expand(str(key), value)")
PATHS_SEGMENT_RE = '_FIELD_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")'
CLAIM_ABORT = ("                if _is_incognito_research(research_id):\n"
               '                    log(f"[start-listener] {research_id[:8]}… keeps nothing and its "')
# ⛔ `doc.reference.delete()` inside a try appears six times in this file, so the
# anchor carries the line above it — the one sentence only this branch writes.
# ── anchors: the folders this disk keeps ────────────────────────────────────
PURGE_GATE = ("    if not _is_incognito_research(research_id):\n"
              "        return False")
PURGE_ASKS_FOLDER = ("    if not research_id:\n"
                     "        research_id = _queue_dir_research_id(queue_dir)")
OWNER_UNREADABLE = ('    except Exception:\n'
                    '        return ""\n'
                    '    return str((owner or {}).get("researchId") or "").strip()')
PURGE_OVER = "    if status not in _RUN_DELIVERY_OVER:\n        return False"
PURGE_OVER_SET = '_RUN_DELIVERY_OVER = frozenset({"completed", "stopped"})'
PURGE_UNREADABLE = ("    except Exception:\n"
                    "        # ⛔ UNREADABLE MEANS LEAVE IT.")
PURGE_CALL = "            _purge_incognito_run_dirs(_run_pipeline_queue_dir(args, kwargs), _rid)"
PURGE_LOGS = ("    for folder in log_folders:\n"
              "        try:\n"
              "            _shutil.rmtree(folder)")
RECHECK = ("    if _is_incognito_research(research_id):\n"
           "        return True\n"
           "    return (float(now) - float(last_verified_at or 0.0)) >= float(recheck_sec)")
# ⛔⛔ THE CONSUMER OF THE LINE ABOVE, which had no anchor at all until
# 2026-09-22: four tests pinned the helper's truth table and nothing executed
# the one line that calls it, so putting the old inline comparison back left
# the whole suite green and the harness reporting a clean score.
RECHECK_CALL = ("                    if not _orphan_recheck_due(\n"
                "                            _orphan_verified.get(_seen_key, 0.0), now_ts_inner,\n"
                "                            rid, ORPHAN_RECHECK_SEC):\n"
                "                        continue")
QUEUE_DIR_CLAIM = ('    claim = Path(str(resume)).name if resume else bound.arguments.get("run_id")')
CATCHUP = ('    if _is_incognito_research(research_id):\n'
           '        return ("nothing here can ask the route again — a run that keeps nothing "\n'
           '                "has no chat to reopen")')

# ── anchors: the proof of the hand-off, and the queue snapshot ─────────────
HANDOFF_RECORD = ('    if _claim_is_handed_off((data or {}).get("backendRunId")):\n'
                  "        return True\n"
                  "    if _is_incognito_research(research_id):\n"
                  '        return bool((data or {}).get("beDone"))\n'
                  "    return False")
# ⛔ THE COMMENT IS PART OF THE ANCHOR: the reconcile call site is the same
# statement at a shallower indent, so the bare line is a substring of this one.
REHYDRATE_WITNESS = ("                # the re-kick. See `_recovery_sees_handoff`.\n"
                     "                if _recovery_sees_handoff(research_id, data):")
RECONCILE_WITNESS = ("        if _recovery_sees_handoff(research_id, data):\n"
                     "            continue")
SNAP_VIEW = ('    rid = (job or {}).get("research_id")\n'
             "    if not _is_incognito_research(rid):\n"
             "        return job")
SNAP_CURRENT = '        "current": _snapshot_job_view(current_job),'
SNAP_PENDING = '        "pending": list(pending_jobs or []),'
RESTORE_DROP = ("    if _is_incognito_research(cur_rid):\n"
                '        log(f"[pending_queue] {cur_rid[:24]}… keeps nothing — the run this "')
RESTORE_HELD = ("    held_a_run_that_keeps_nothing = bool(_is_incognito_research(cur_rid)) or any(\n"
                '        _is_incognito_research((j or {}).get("research_id")) for j in pending)')
RESTORE_FORGET = ("    if held_a_run_that_keeps_nothing:\n"
                  "        _forget_pending_queue_snapshot(path, job_queue)")
# ⛔ THE LINES BELOW IT ARE PART OF THE ANCHOR: the same assignment appears at
# two deeper indents elsewhere, and a four-space anchor is a substring of both.
FORGET_CURRENT = ('    current = _QUEUE_STATE.get("current_job")\n'
                  "    try:\n"
                  "        live = list(job_queue._queue)")
FORGET_WRITE = ("        if live or current:\n"
                "            _write_pending_queue_snapshot(path, current, live)")
FORGET_UNLINK = ("        else:\n"
                 "            Path(path).unlink(missing_ok=True)")

# ── anchors: the two seams a recovery status has to satisfy at once ─────────
ENQUEUE_WHITELIST = (
    'def _safe_enqueue(job_queue, job, source: str,\n'
    '                  allowed_statuses: "tuple[str, ...]" = '
    '("queued", "ongoing", "paused_backend_restart")) -> bool:')
SEQ_MONOTONIC = ("    new_seq = int(time.time() * 1000)\n"
                 "    if new_seq <= _fb_seq:\n"
                 "        new_seq = _fb_seq + 1")

# ── anchors: the web-parity pins' own guards (a TEST file) ──────────────────
# ⛔⛔ THE ONLY MECHANICAL CHECK THAT FOUR COPIES OF THE ID SHAPE AGREE lives in
# a test, and its failure mode is silence: it reaches into another checkout, so
# "found nothing" and "found nothing wrong" look identical from here. These
# three mutants are aimed at the guards that tell those apart.
CAP_TEST = "tests/test_incognito_capability_109.py"
CAP_MISSING_FILE = ('    path = web / rel\n'
                    '    assert path.exists(), (\n'
                    '        f"{rel} is missing from {web} — this pin holds four copies of one id "\n'
                    '        f"shape together and cannot do it without that file; re-anchor it if "\n'
                    '        f"the web moved the file")\n'
                    '    return path.read_text(encoding="utf-8")')
CAP_ENV_CLAIM = ('    if env:\n'
                 '        assert (Path(env) / "firestore.rules").exists(), (\n'
                 '            f"SR_WEB_REPO={env!r} is not a dg-research checkout — there is no "\n'
                 '            f"firestore.rules there, so the parity pins were aimed at nothing")')
CAP_COMMON_DIR = ("        if common.returncode == 0 and common.stdout.strip():\n"
                  '            out.append(Path(common.stdout.strip()).parent.parent / "dg-research")')

CLAIM_QUEUE_DELETE = ('                        f"recreating it", "WARN")\n'
                      "                    try:\n"
                      "                        doc.reference.delete()\n"
                      "                    except Exception:\n"
                      "                        pass\n"
                      "                    continue")

MUTANTS = [
    # ══ the one predicate ══════════════════════════════════════════════════
    ("I1", "over", "a bare prefix match — `incog_notes` becomes a run that "
     "keeps nothing, and its owner never sees it again",
     [(ID_RE, '_INCOGNITO_ID_RE = re.compile(r"^incog_")')]),
    ("I2", "over", "⛔⛔ the end anchor goes — `incog_…-copy` is ephemeral, and "
     "a TTL rule is handed an id it will expire",
     [(ID_RE, '_INCOGNITO_ID_RE = re.compile(r"^incog_[0-9]{13}_[0-9]{1,6}")')]),
    ("I3", "under", "⛔⛔ the predicate answers False for everything — nothing "
     "about an ordinary run breaks and the whole feature is decoration",
     [(PREDICATE, "    return False")]),
    ("I4", "over", "the predicate answers True for everything, so every "
     "ordinary run loses its name, its logs and its telemetry",
     [(PREDICATE, "    return True")]),
    ("I5", "under", "a non-string id raises instead of answering, which stops "
     "a sweep mid-scan",
     [(PREDICATE, "    return bool(_INCOGNITO_ID_RE.match(research_id))")]),

    # ══ the run id ═════════════════════════════════════════════════════════
    ("I6", "under", "⛔⛔ the mint forgets incognito — the topic is back in the "
     "queue folder, the backendRunId and the device document",
     [(MINT_INCOG, "    if False:\n        pass")]),
    ("I7", "under", "the ordinary mint returns the incognito shape, so every "
     "run on the machine loses its name",
     [(MINT_PLAIN, '    return f"incognito_{stamp}"')]),
    ("I8", "under", "⛔⛔ the research id leaves the incognito run id — two "
     "members claiming in the same second share one queue directory",
     [(MINT_INCOG, '    if _is_incognito_research(research_id):\n'
                   '        return f"incognito_{stamp}"')]),
    ("I9", "under", "the stamp leaves the incognito name, so `_RUN_ID_STAMP_RE` "
     "and the bundle's queue-name cut both stop finding it",
     [(MINT_INCOG, '    if _is_incognito_research(research_id):\n'
                   '        return f"incognito_{research_id.removeprefix(\'incog_\')}"')]),

    # ══ the log lines ══════════════════════════════════════════════════════
    ("I10", "under", "⛔ the topic is logged for an incognito run after all",
     [(LOG_TOPIC, '    return str(topic or "")[:limit]')]),
    ("I11", "over", "every run's topic is marked out, so `backend.log` stops "
     "saying what any run was about",
     [(LOG_TOPIC, "    return _BUNDLE_TOPIC_MARK")]),
    ("I12", "under", "the mark is a word of its own instead of the redactor's, "
     "so a bundle and a live log disagree about the same line",
     [(LOG_TOPIC, '    if _is_incognito_research(research_id):\n'
                  '        return "(hidden)"\n'
                  '    return str(topic or "")[:limit]')]),

    # ══ the consumers ══════════════════════════════════════════════════════
    ("I13", "under", "⛔⛔ the listener mints without the research id — the "
     "helper is perfect and the branch that calls it is not",
     [(LISTENER_MINT, "            # Generate run_id\n"
                      "            run_id = _mint_run_id(topic)")]),
    ("I13b", "under", "the defer line of a shared computer goes back to "
     "printing the topic — the run nobody is watching yet",
     [(LISTENER_DEFER, LISTENER_DEFER.replace(
         "{_loggable_topic(topic, research_id)!r}", "{topic[:40]!r}"))]),
    ("I14", "under", "the claim line goes back to printing the topic",
     [(LISTENER_CLAIMED, LISTENER_CLAIMED.replace(
         "{_loggable_topic(topic, research_id)!r}", "{topic[:40]!r}"))]),
    ("I15", "under", "the malformed-document line goes back to printing the "
     "topic — the case where nobody is watching",
     [(LISTENER_MISSING, LISTENER_MISSING.replace(
         "{_loggable_topic(topic, research_id, 30)}", "{topic[:30]}"))]),

    # ══ the device capability ══════════════════════════════════════════════
    ("I16", "under", "⛔⛔ the capability is never published — every app is "
     "left unable to tell an old wheel from a new one",
     [(CAP_CONST, "_INCOGNITO_RUNS_CAPABILITY = None")]),
    ("I17", "under", "the source-checkout branch drops it, which is the "
     "owner's own machine and the first one to run this",
     [(CAP_SOURCE, '        return {"version": None, "updateAvailable": None, '
                   '"sourceCheckout": True,\n                "servingVersion": None}')]),
    ("I18", "under", "the installed branch drops it, so the fleet says nothing",
     [(CAP_INSTALLED, '    return {"version": version, "updateAvailable": update_available,\n'
                      '            "sourceCheckout": False, "servingVersion": serving}')]),
    ("I19", "under", "the capability is published as a string, which the rules "
     "type-check — and `hasOnly` then refuses the WHOLE version patch",
     [(CAP_CONST, '_INCOGNITO_RUNS_CAPABILITY = "1"')]),
    ("I20", "over", "the capability is published as a bool, which is not an int "
     "to the rules either",
     [(CAP_CONST, "_INCOGNITO_RUNS_CAPABILITY = True")]),

    # ══ telemetry ══════════════════════════════════════════════════════════
    ("I21", "under", "⛔ the id reaches telemetry for an incognito run — a "
     "warning per event and an invalid counter for the whole run",
     [(TM_ID, "    return research_id")]),
    ("I22", "under", "⛔⛔ the id is dropped for EVERYBODY, which loses the join "
     "on every ordinary run while looking like a privacy fix",
     [(TM_ID, "    return None")]),
    ("I23", "under", "the per-event tap asks nobody and forwards the raw id",
     [(TM_TAP, "    rid = rid")]),
    ("I24", "under", "the run-started event forwards the raw id",
     [(TM_STARTED, "            tm.tm_emit(tm.Ev.RUN_STARTED,\n"
                   "                       research_id=self.research_id,\n"
                   "                       worker=WORKER_ID)")]),
    ("I25", "under", "the run-finished event forwards the raw id",
     [(TM_FINISHED, "                       research_id=sink.research_id,")]),

    # ══ the writes that outlive a run ══════════════════════════════════════
    ("N1", "under", "⛔ the report figures are fetched and stored again — the "
     "one residue class with no fuse, in a bucket with no TTL",
     [(IMG_SKIP, "        if False:\n            raise _DocImgStopRequested()")]),
    ("N2", "over", "⛔⛔ the skip moves to the FUNNEL, so the private-link scrub "
     "is skipped with it and the agents' signed links reach the mail",
     [(FUNNEL, "    if _is_incognito_research(_fb_research_id):\n"
               "        return text\n"
               "    return _doc_scrub_private_links(await _doc_images_rehost(text, label))")]),
    ("N3", "under", "⛔ the podcast is uploaded, the audios row written and "
     "links.audio_file stamped for a run that keeps nothing",
     [(AUDIO_SKIP, '    if False:\n        return ""')]),
    ("N4", "over", "no run publishes its podcast at all",
     [(AUDIO_SKIP, '    if True:\n        return ""')]),
    # ⛔ THE MUTANT THAT WAS HERE MEASURED NOTHING. It guarded `_p3_publish_audio`
    # at its call site as well as inside — the same observable behaviour by both
    # routes, so an EQUIVALENT mutant, which is a harness fault and not a hole.
    # What is worth refusing at this seam is a phase that calls the publisher and
    # then believes a local file is a published podcast.
    ("N5", "over", "a failed upload answers with the local path, so completion "
     "and delivery disagree about the same run again",
     [(AUDIO_FALLTHROUGH, AUDIO_FALLTHROUGH[:-len('    return ""')]
       + "    return str(audio_path or \"\")")]),
    ("N4b", "under", "⛔⛔ the phase reports the refusal to publish as an upload "
     "FAILURE again, and tells somebody running on another person's computer "
     "that their private podcast is still on it — minutes before the purge "
     "deletes the folder",
     [(P3_REPORT_INCOG, "    if False:\n"
                        "        return (_P3_KEEPS_NOTHING_REASON, _P3_KEEPS_NOTHING_DETAIL)")]),
    ("N4c", "over", "every run gets that answer, so an ordinary run stops being "
     "told which of the two happened — and loses the one sentence that says its "
     "podcast can still be fetched",
     [(P3_REPORT_INCOG, "    if True:\n"
                        "        return (_P3_KEEPS_NOTHING_REASON, _P3_KEEPS_NOTHING_DETAIL)")]),
    ("N4d", "under", "the tile line goes back to being a SLUG, which the app "
     "renders as a de-underscored word salad because it enumerates the slugs it "
     "knows and this is not one of them",
     [(P3_REPORT_REASON, '_P3_KEEPS_NOTHING_REASON = "no_podcast_kept"')]),
    ("N6", "under", "⛔ the phase notice is asked for again — an inbox row that "
     "outlives the run, linking to a chat that will not exist",
     [(NOTICE_SKIP, "    if False:\n        return False")]),
    ("N7", "over", "no run asks for a phase notice, so a closed tab never "
     "catches up on anything",
     [(NOTICE_SKIP, "    if True:\n        return False")]),
    ("N8", "under", "⛔ the Send Logs picker offers a run that keeps nothing, "
     "by id, to the person it is hidden from",
     [(INDEX_SKIP, '        if False:\n            continue')]),
    ("N9", "over", "the picker drops the whole submitter when one of their runs "
     "keeps nothing, so their ordinary runs become unsendable",
     [(INDEX_SKIP, '        if _is_incognito_research(row.get("researchId")):\n'
                   "            break")]),
    ("N10", "under", "⛔⛔ boot recovery parks a run that keeps nothing behind a "
     "Resume card in a chat nobody can reopen",
     [(RECOVERY_STOP, '    if False:\n        return {\n            "status": "stopped",')]),
    ("N11", "over", "every restarted run is ended instead of offered a Resume",
     [(RECOVERY_STOP, '    if True:\n        return {\n            "status": "stopped",')]),
    ("N12", "under", "⛔⛔ the rehydrate branch goes, so a run that keeps nothing "
     "is auto-resumed on this machine's browser profiles hours later",
     [(REHYDRATE_STOP, "                if False:\n"
                       "                    if _update_research_doc(tree_uid, research_id,\n"
                       "                                            _restart_recovery_patch(research_id)):")]),
    # ══ the fuse ═══════════════════════════════════════════════════════════
    ("E1", "under", "⛔⛔ nothing is fused, so a run whose purge never ran keeps "
     "its whole content for ever and the rules refuse its reports",
     [(EXPIRE_GATE, "    if True:\n        return None")]),
    ("E2", "over", "every run is fused, so ordinary research starts "
     "disappearing a day after it is written",
     [(EXPIRE_GATE, "    if False:\n        return None")]),
    ("E3", "under", "⛔⛔ the fuse is naive, so Firestore guesses its zone and "
     "the rules' `is timestamp` is the only thing that catches it",
     [(EXPIRE_BASE, "    base = now if now is not None else datetime.now()")]),
    ("E4", "over", "the fuse is set past the rules' 48-hour ceiling, so every "
     "incognito write is refused",
     [(EXPIRE_HOURS, "_INCOGNITO_EXPIRE_HOURS = 72")]),
    ("E5", "under", "⛔ the report is written without its fuse — the documents "
     "are the whole content of the research",
     [(DOC_EXPIRE, "")]),
    ("E6", "under", "⛔ the timeline keeps its thirty days for a run that keeps "
     "nothing, under a record that is already gone",
     [(EVENT_EXPIRE, '        "expireAt": datetime.now(timezone.utc) + timedelta(days=30),')]),
    ("E7", "over", "every run's events burn in a day, so an older research's "
     "phase dropdown empties itself",
     [(EVENT_EXPIRE, '        "expireAt": (_incognito_expire_at(_fb_research_id)\n'
                     "                     or datetime.now(timezone.utc) + timedelta(hours=24)),")]),

    # ══ never bringing a purged record back ════════════════════════════════
    ("C1", "under", "⛔⛔ every write is a set-merge again, so a purged record "
     "comes back as a fragment with no createdAt — invisible for ever",
     [(WRITE_GATE, "    return doc_ref.set(payload, merge=merge)")]),
    ("C2", "over", "every write becomes an update, so the machine loses the "
     "race the app has not finished creating the record in",
     [(WRITE_GATE, "    return doc_ref.update(_merge_field_paths(payload))")]),
    ("C3", "under", "⛔⛔ the nested map rides an update whole, so writing one "
     "agent's status deletes the other two",
     [(PATHS_DESCEND, '            out[path] = value')]),
    ("C4", "over", "a name that needs quoting is spliced into a path unquoted, "
     "so the write lands on a different field entirely",
     [(PATHS_GUARD, "        if type(value) is dict and value:")]),
    ("C7", "under", "⛔⛔ the rewrite stops after ONE level, so the write that "
     "says an agent finished deletes that agent's sources, its findings and its "
     "progress curve — the live tile going blank",
     [(PATHS_DESCEND, '            for inner, inner_value in value.items():\n'
                      '                out[f"{path}.{inner}"] = inner_value')]),
    ("C8", "over", "a top-level name the client cannot parse is spliced in "
     "anyway, so the whole write raises inside the update and is swallowed as a "
     "WARN — an ordinary run's set-merge lands and this one does not",
     [(PATHS_TOP_GUARD, "        if True:\n            _expand(str(key), value)")]),
    ("C9", "over", "the segment pattern admits a hyphen and a leading digit "
     "again, which `parse_field_path` refuses — the same swallowed write, from "
     "one level down",
     [(PATHS_SEGMENT_RE,
       '_FIELD_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")')]),
    ("C5", "under", "⛔⛔ the claim recreates a record that was deleted, which is "
     "the one thing the promise cannot survive",
     [(CLAIM_ABORT, "                if False:\n"
                    '                    log(f"[start-listener] {research_id[:8]}… keeps nothing and its "')]),
    ("C6", "under", "the abandoned start leaves its queue document, so the "
     "idle-rescan claims it again on the next pass, for ever",
     [(CLAIM_QUEUE_DELETE, '                        f"recreating it", "WARN")\n'
                           "                    continue")]),

    # ══ the folders this disk keeps ════════════════════════════════════════
    ("T1", "under", "⛔⛔ nothing is purged, so a run folder holding the "
     "documents, the delivery record and the topic waits on the hourly sweep",
     [(PURGE_GATE, "    if True:\n        return False")]),
    ("T2", "over", "every finished run's folder is deleted, taking local "
     "retention and the support bundle with it",
     [(PURGE_GATE, "    if False:\n        return False")]),
    ("T3", "over", "⛔⛔ a paused or crashed run is purged too, so the Retry and "
     "the Resume both lose the checkpoint they resume from",
     [(PURGE_OVER, "    if False:\n        return False")]),
    ("T4", "over", "an `ongoing` run — one still executing — counts as over",
     [(PURGE_OVER_SET, '_RUN_DELIVERY_OVER = frozenset({"completed", "stopped", "ongoing"})')]),
    ("T5", "over", "an unreadable delivery record is treated as over, which is "
     "the shape a run that died mid-construction has",
     [(PURGE_UNREADABLE, "    except Exception:\n"
                         "        status = \"completed\"\n"
                         "    if False:\n"
                         "        # ⛔ UNREADABLE MEANS LEAVE IT.")]),
    ("T6", "under", "⛔⛔ the wrapper stops purging, so the helper is perfect "
     "and nothing ever calls it",
     [(PURGE_CALL, "            pass")]),
    ("T6b", "under", "⛔⛔ a `--resume` that ENDS the run purges nothing, because "
     "the CLI names a directory and no research — the documents, the delivery "
     "record and the topic stay until the orphan sweep notices",
     [(PURGE_ASKS_FOLDER, "    if False:\n"
                          "        research_id = _queue_dir_research_id(queue_dir)")]),
    ("T6c", "over", "the folder's own record overrules the caller, so a stale "
     "`owner.json` beside an ordinary run takes that run's folder",
     [(PURGE_ASKS_FOLDER, "    if True:\n"
                          "        research_id = _queue_dir_research_id(queue_dir)")]),
    ("T6d", "over", "⛔ a folder that cannot name its run is GUESSED at, which is "
     "how somebody else's unfinished work disappears",
     [(OWNER_UNREADABLE, '    except Exception:\n'
                         '        return "incog_1758400000000_1"\n'
                         '    return str((owner or {}).get("researchId") or "").strip()')]),
    ("T7", "under", "the log folders stay, so the run's diagnostics outlive it",
     [(PURGE_LOGS, "    for folder in []:\n        try:\n            _shutil.rmtree(folder)")]),
    ("T8", "under", "⛔ the hourly memo holds an incognito folder after all, for "
     "sixty-five minutes after the app said nothing was kept",
     [(RECHECK, "    return (float(now) - float(last_verified_at or 0.0)) >= float(recheck_sec)")]),
    ("T9", "over", "the memo is bypassed for EVERY research, which is the "
     "per-tick Firestore read the memo was added to stop",
     [(RECHECK, "    return True")]),
    ("T8b", "under", "⛔⛔ THE SWEEP STOPS ASKING. The helper above is perfect "
     "and the one line that calls it goes back to the inline comparison, so an "
     "incognito folder is held by the hourly memo for up to sixty-five minutes "
     "after the app said nothing was kept",
     [(RECHECK_CALL, "                    if (now_ts_inner - _orphan_verified.get("
                     "_seen_key, 0.0)) < ORPHAN_RECHECK_SEC:\n"
                     "                        continue")]),
    ("T10", "under", "⛔ a resume's full path is used as a run-id claim, so the "
     "containment check is handed something it was written to refuse",
     [(QUEUE_DIR_CLAIM,
       '    claim = str(resume) if resume else bound.arguments.get("run_id")')]),
    ("T11", "under", "⛔ the run's own account promises a catch-up that cannot "
     "happen — a lying diagnostic in the file that rides the support bundle",
     [(CATCHUP, "    if False:\n        return \"\"")]),
    ("T12", "over", "every run's account stops naming the re-drive that DOES "
     "recover it, so a recoverable run reads as lost",
     [(CATCHUP, "    if True:\n"
                '        return ("nothing here can ask the route again — a run that keeps nothing "\n'
                '                "has no chat to reopen")')]),

    ("N13", "under", "the dead-worker reconciler writes the parked patch "
     "directly again, so the two recovery paths disagree",
     [(RECONCILE_PATCH, '        _patch = {"status": "paused_backend_restart",\n'
                        '                  "summary": "Backend restarted mid-run — hit Resume to '
                        'pick up from the last checkpoint."}')]),

    # ══ the proof of the hand-off ══════════════════════════════════════════
    ("H1", "under", "⛔⛔ recovery asks only the disk again — and the disk answer "
     "for a run that keeps nothing was deleted at the hand-off, so the machine "
     "stamps it terminally while its email is still in the cloud",
     [(HANDOFF_RECORD, '    return _claim_is_handed_off((data or {}).get("backendRunId"))')]),
    ("H2", "over", "every run believes the marker, so an ordinary run that went "
     "round again is kicked instead of parked for the Resume it can serve",
     [(HANDOFF_RECORD, '    if _claim_is_handed_off((data or {}).get("backendRunId")):\n'
                       "        return True\n"
                       '    return bool((data or {}).get("beDone"))')]),
    ("H3", "under", "⛔⛔ the boot rehydrate asks the disk directly again — the "
     "helper is right and the branch that ends the run does not use it",
     [(REHYDRATE_WITNESS, "                # the re-kick. See `_recovery_sees_handoff`.\n"
                          '                if _claim_is_handed_off(data.get("backendRunId")):')]),
    ("H4", "under", "the dead-worker sweep asks the disk directly again, so one "
     "worker dying ends a run the cloud is finishing",
     [(RECONCILE_WITNESS, '        if _claim_is_handed_off(data.get("backendRunId")):\n'
                          "            continue")]),

    # ══ the queue snapshot at the root of queues/ ══════════════════════════
    ("S1", "under", "⛔⛔ the claimed job goes to disk whole again — the topic, "
     "the person's address and their whole brief, in a file the purge never "
     "reaches and 'clear local storage' keeps",
     [(SNAP_VIEW, '    rid = (job or {}).get("research_id")\n'
                  "    if True:\n"
                  "        return job")]),
    ("S2", "over", "every claimed job is reduced to ids, so no interrupted run "
     "on this machine can be restored from the snapshot again",
     [(SNAP_VIEW, '    rid = (job or {}).get("research_id")\n'
                  "    if False:\n"
                  "        return job")]),
    ("S3", "under", "⛔ the writer stops asking what may be written and snapshots "
     "the job it was handed",
     [(SNAP_CURRENT, '        "current": current_job,')]),
    ("S4", "over", "the jobs still waiting their turn are redacted too, and the "
     "claim already deleted their queue documents — the work is simply lost",
     [(SNAP_PENDING, '        "pending": [_snapshot_job_view(j) for j in (pending_jobs or [])],')]),
    ("S5", "under", "⛔⛔ boot re-offers the run it has just ended, on the browser "
     "profiles of a machine whose owner was told only that a run happened",
     [(RESTORE_DROP, "    if False:\n"
                     '        log(f"[pending_queue] {cur_rid[:24]}… keeps nothing — the run this "')]),
    ("S6", "under", "⛔⛔ boot reads the snapshot and never writes it, so the "
     "entry a crash left behind stays for ever — nothing can claim it again",
     [(RESTORE_FORGET, "    if False:\n"
                       "        _forget_pending_queue_snapshot(path, job_queue)")]),
    ("S7", "over", "every boot rewrites the snapshot, which drops jobs the "
     "enqueue funnel refused this pass but a later one would have taken",
     [(RESTORE_FORGET, "    if True:\n"
                       "        _forget_pending_queue_snapshot(path, job_queue)")]),
    ("S8", "under", "only the running job counts, so a queued run that keeps "
     "nothing and is refused at boot keeps its brief on the disk",
     [(RESTORE_HELD, "    held_a_run_that_keeps_nothing = bool(_is_incognito_research(cur_rid))")]),
    ("S9", "under", "the last snapshot is left in place rather than removed, so "
     "a machine that ran one private run still says so",
     [(FORGET_UNLINK, "        else:\n            pass")]),
    ("S10", "over", "the file goes even when jobs were restored into it, so the "
     "next crash loses every one of them",
     [(FORGET_WRITE, "        if False:\n"
                     "            _write_pending_queue_snapshot(path, current, live)")]),
    ("S11", "under", "⛔⛔ the rewrite outruns the worker — a run claimed while "
     "boot was still going has its snapshot overwritten with nothing, so one "
     "run's leftovers take the next run's only crash record with them",
     [(FORGET_CURRENT, "    current = None\n"
                       "    try:\n"
                       "        live = list(job_queue._queue)")]),

    # ══ the stop has to hold at BOTH ends ══════════════════════════════════
    ("A1", "over", "⛔⛔ the enqueue funnel accepts `stopped`, so the status a "
     "restart writes over a run that keeps nothing is a LABEL: the next boot "
     "re-offers the run, on a machine whose owner was told only that a run "
     "happened",
     [(ENQUEUE_WHITELIST, ENQUEUE_WHITELIST.replace(
         '("queued", "ongoing", "paused_backend_restart")',
         '("queued", "ongoing", "paused_backend_restart", "stopped")'))]),
    ("C10", "over", "⛔⛔ a failed update FALLS BACK to the set-merge, which "
     "looks like resilience and is the resurrection itself — the purged record "
     "comes back as a fragment with no createdAt on the very next write",
     [(WRITE_GATE, "    if not _is_incognito_research(research_id):\n"
                   "        return doc_ref.set(payload, merge=merge)\n"
                   "    try:\n"
                   "        return doc_ref.update(_merge_field_paths(payload))\n"
                   "    except Exception:\n"
                   "        return doc_ref.set(payload, merge=merge)")]),
    ("E8", "under", "⛔ the seq stops being monotonic, so two events in the "
     "same millisecond tie and the app's `where(seq > lastSeq)` filter never "
     "shows the second — the fuse rides on this write and must not cost it",
     [(SEQ_MONOTONIC, "    new_seq = int(time.time() * 1000)")]),

    # ══ the pins that hold four copies of the id shape together ════════════
    # ⛔ THESE MUTATE A TEST FILE, which is the only place their decision
    # lives: a cross-repo pin that cannot say "I found nothing" is a pin that
    # reports agreement it never checked.
    ("W1", "under", "⛔⛔ the parity pin reads a web file without asking whether "
     "it is there, so a checkout whose half of this wave has not landed dies on "
     "a bare FileNotFoundError instead of saying which copy moved",
     [(CAP_MISSING_FILE, '    path = web / rel\n'
                         '    return path.read_text(encoding="utf-8")')],
     CAP_TEST),
    ("W2", "under", "⛔⛔ a mistyped SR_WEB_REPO goes back to reading as 'there "
     "is no web repo here', so the one place somebody thought they had switched "
     "the parity pins ON is the place they go quiet",
     [(CAP_ENV_CLAIM, '    if env and not (Path(env) / "firestore.rules").exists():\n'
                      '        pytest.skip("no web checkout beside this one; '
                      'set SR_WEB_REPO")')],
     CAP_TEST),
    ("W3", "under", "⛔⛔ the resolver looks only in the directory holding this "
     "checkout, so in the worktree every wave of this branch is built and gated "
     "in, both parity pins skip and nothing compares the four copies",
     [(CAP_COMMON_DIR, "        if False:\n"
                       '            out.append(Path(common.stdout.strip()).parent.parent / "dg-research")')],
     CAP_TEST),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q",
             "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    if re.search(r"SKIPPED \[\d+\] tests/test_incognito_capability_109", out):
        raise SystemExit("⛔ the web-parity pins SKIPPED — set SR_WEB_REPO")
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    # ⛔ A FIFTH COLUMN NAMES THE FILE, and most mutants do not carry one: the
    # machine's decisions live in research.py, but three of them live in the
    # parity pins themselves, which are a test file. Everything is normalised
    # to five columns here so the loop below — and the two sweeps in
    # `.mutants/_*.py`, which read this loop to learn what the columns mean —
    # see one shape.
    MUTANTS = [(*m, RESEARCH)[:5] for m in MUTANTS]
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, why, edits, fname in selected:
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
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}", flush=True)
            else:
                print(f"  {mid}  ✓ killed", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if _path(f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
