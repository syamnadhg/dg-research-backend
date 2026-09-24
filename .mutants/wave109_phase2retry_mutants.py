"""Wave 10.9 — does a crash retry still buy every finished Deep Research again?

⛔⛔ WHAT THE WAVE CLOSED (D5). An interrupted Phase 2 resumes through
`run_phase2`, and it launched EVERY enabled agent from zero. Each silent
relaunch after a Chrome death — up to BROWSER_CRASH_MAX_RETRIES of them, and a
daemon restart resumes the same way — paid again for reports already on disk and
in Firestore, and flipped their finished tiles back to "running". The comment in
`detect_resume_phase` admitted it and priced it at "a few extra minutes".

⭐ THE FIX: a durable per-agent completion record, written ONLY by the branch of
`extract_and_record_agent` that announces `complete`, and taken out again by
every LAUNCH in `run_phase2`; `_p2_resume_plan` keeps an agent only with BOTH
the record and its report on disk; `_p2_announce_restored` re-ticks the kept
tile the resume's full `phase_restart` has just re-seeded; and
`_p2_run_with_resume` is the phase itself — plan, attempts, merge, safety filter.

⭐ WHAT THE REPAIR ROUND ADDED (the cross-verify's D8, D15, D16):
  * the phase used to be ninety lines inside `run_pipeline`, pinned only by AST
    SHAPE — M12/M13 are the two added lines that re-opened the defect with the
    whole suite green, and they are killed by RUNNING the phase now;
  * N — a kept agent's text is what a fresh extraction returned, not the numbered
    file: its `##### Sources` list used to land in the MIDDLE of the consolidated
    report, where the web's end-anchored strip leaves it;
  * S — a kept agent's card carries the sources, sections and steps its own
    completion emit carried, because the resume re-seeds the web's details and
    the merge keeps the seed for anything an event omits.

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The quiet ones:

  P1  — the record stops being consulted, so a plain file-existence scan keeps a
        SALVAGED PARTIAL (the Stop path and the finalize re-save both write the
        report file) as a finished agent. The case nothing but the record can
        tell apart.
  W2  — the record is written on the FAILED branch too: every extraction looks
        finished, including one whose Firestore copy the app cannot open.
  L4  — the launch still clears the record, but only after the tab opens: a
        crash in between hands back the LAST attempt's file as done.
  M3  — the kept reports are dropped between the phase and the sink, so the
        off-topic sweep and everything after it judge a phase without them.
        Still present, still greppable, and the call above reads right.
  M9  — a person's Skip stops dropping the kept results, so a phase they SKIPPED
        is recorded complete after `phase_skipped` already said otherwise.
  M10 — the roster is trimmed to the launch list — the "obvious" simplification
        the spec warns against: the safety filter then throws the kept reports
        away and their tiles vanish from every phase_start.

⭐ WHAT REPAIR ROUND 2 ADDED (M5 and M9): the first round put back HALF of what
a kept agent owns.
  H*  — `save_meta` reads TWO rings off `_runtime` per agent and round 1
        restored one. A kept agent is never relaunched, so nothing ticks its
        `agent_progress_history`, and the run's final save — a whole-FIELD
        replace — wrote `progressHistory: []` over the curve the agent earned.
        The sparkline read "No data" for the one agent that did the work.
  K*  — `_p2_resume_plan` hands back `url=""`, and the P2→P3 handoff read that
        as "contributed nothing". A kept agent's markdown reached NotebookLM
        while `links.json`, delivery.json's `research_links` and the "Links
        saved:" line listed only the agents that re-ran.

⭐ M11 (the owner decision): a Chrome window closed by hand mid-phase-2 takes the
silent-relaunch path, and that stays. B1/B2 are that decision being reversed or
its budget going off by one.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT.

  python .mutants/wave109_phase2retry_mutants.py
  python .mutants/wave109_phase2retry_mutants.py P1 W2
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_p2_idempotent_resume_109.py "
          "tests/test_browser_death_unwinds_0920.py "
          "tests/test_p2_share_removed_0828.py "
          "tests/test_link_sinks_removed_0902.py "
          "tests/test_save_meta_status_carry.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
# ⭐ The interpreter running this harness, not `.venv/bin/python` under ROOT: a
# builder's worktree has no venv of its own, and a missing interpreter fails
# every run — which a harness reads as every mutant killed.
PY = sys.executable

# ── anchors: research.py ────────────────────────────────────────────────────
#: The record half of "keep only with BOTH".
REC_CHECK = ("        entry = done.get(key)\n"
             "        if not isinstance(entry, dict):\n"
             "            continue")
#: The report half.
DOC_READ = ("            md = doc.read_text(encoding=\"utf-8\")\n"
            "        except Exception:\n"
            "            continue")
DOC_SIZE = "            if doc.stat().st_size <= 100:"
HEADER = "            md = rest.lstrip(\"\\n\")"
ROSTER = "    for agent in enabled_agents or ():"
LAUNCH = "    launch = [a for a in (enabled_agents or []) if str(a).lower() not in restored]"
VERIFIED = ("            \"_in_app_url\": in_app_document_url(key),\n"
            "            \"verified\": True,")
RESTORED_FLAG = "            \"_restored\": True,"
RESAVE = "    return bool(r.get(\"text\")) and not r.get(\"_restored\")"
KEPT_KEY = "        kept[_agent_display_name(key)] = {"
#: The de-numbering a kept agent's text goes through (wave 10.9 repair, D15).
DENUMBER_CALL = "        md = _document_without_sources(md)"
DENUMBER_BODY = ("    return _DOC_SOURCE_MARK_INLINE_RE.sub(\"\", "
                 "_strip_numbered_sources_section(md))")
#: Raw — the pattern it anchors on is itself a pile of backslashes.
MARK_INLINE_RE = r"""    r'(?:(?<=\S) )?\[\\\[\d{1,3}\\\]\]\([^()\s]*\)')"""
MARK_INLINE_WIDE = r"""    r'(?:(?<=\S) )?\[[^\]]*\]\([^()\s]*\)')"""
#: The progress snapshot a kept agent's card is drawn from (wave 10.9 repair, D16).
SNAP_LISTS = "_P2_SNAPSHOT_LISTS = (\"source_urls\", \"sections\", \"steps\")"
SNAP_COERCE = ("            try:\n"
               "                out[k] = int(snapshot[k] or 0)\n"
               "            except (TypeError, ValueError):\n"
               "                pass")
SNAP_STORED = "                       \"progress\": _p2_progress_snapshot(progress),"
SNAP_PASSED = "                            progress=_snap,"
SNAP_RESTORE = "            _runtime.agent_progress_snapshots[key] = dict(snap)"
A_SOURCE_URLS = "                       sourceUrls=snap.get(\"source_urls\", []),"
A_SOURCES_MAX = ("                       sources=max(int(snap.get(\"sources\", 0) or 0),\n"
                 "                                   len(snap.get(\"source_urls\", []) or [])),")
#: The writer, in the complete branch.
WRITER = ("        _p2_mark_agent_done(queue_dir, agent_key, True, elapsed_sec=elapsed_sec,\n"
          "                            findings=getattr(_runtime, \"agent_findings\", {}).get(agent_key),\n"
          "                            progress=_snap,\n"
          "                            history=getattr(_runtime, \"agent_progress_history\", {}).get(agent_key))")
FAILED_BRANCH = ("        try:\n"
                 "            _write_agent_terminal_status(agent_key, \"errored\")\n"
                 "        except Exception:\n"
                 "            pass")
FINDINGS = "findings=getattr(_runtime, \"agent_findings\", {}).get(agent_key),"
ERASE = "        del agents[key]"
NO_WRITE = ("        # never creates the file, or recreates a deleted run's folder.\n"
            "        return")
NO_PARENTS = "_atomic_write_text(path, json.dumps({\"agents\": agents}), create_parents=False)"
#: The three launch sites.
L_CHATGPT = "        _p2_mark_agent_done(_p2_run_dir(), \"chatgpt\", False)"
L_CLAUDE = "        _p2_mark_agent_done(_p2_run_dir(), \"claude\", False)"
L_GEMINI = "        _p2_mark_agent_done(_p2_run_dir(), \"gemini\", False)"
AFTER_2A_OPEN = "        # #905: stamp research start at SUBMIT time"
#: The main Phase-2 entry — the decision itself is `_p2_run_with_resume` now, and
#: what is left in `run_pipeline` is the call, the stop and the sweep.
MAIN_CALL = "enabled_agents=_launch),"
MERGE = "    results.update(kept)"
FILTER = "    return _p2_only_enabled(results, enabled_agents), user_skipped, False"
FILTER_BODY = "    names = {_agent_display_name(a) for a in enabled_agents}"
FILTER_EMPTY = ("    if not enabled_agents:\n"
                "        return dict(results or {})")
CAP = "    for _p2_attempt in range(3):"
STOPPED = "                return results, user_skipped, True"
CONSUMER_STOP = ("            if _p2_stopped:\n"
                 "                return")
ANNOUNCE = ("    launch, kept = _p2_resume_plan(queue_dir, enabled_agents)\n"
            "    _p2_announce_restored(kept)")
PLAN = "    launch, kept = _p2_resume_plan(queue_dir, enabled_agents)"
R_SOFT = ("                # phase, as it always has — kept agents included.\n"
          "                launch, kept = list(enabled_agents), {}")
R_SOFT_RETRY = ("                    emit_event(\"phase_restart\", phase=2, "
                "reason=\"user_retry_after_soft_timeout\")")
R_LEGACY = "                launch, kept = list(enabled_agents), {}  # wave 10.9, as above"
R_RESTART = ("        # ⭐ Wave 10.9: new input re-runs the whole phase, kept agents too.\n"
             "        launch, kept = list(enabled_agents), {}")
#: Wave 10.9, 09-22: the finalize re-save moved into `_p2_persist_reports` so a
#: test could drive the writes; the line is unchanged, the indent is not.
RESAVE_SITE = "        if _p2_needs_resave(r):"
#: The announce.
A_STATUS = "            _write_agent_terminal_status(key, \"complete\")"
A_PROGRESS = "            emit_event(\"agent_progress\", phase=2, agent=key, status=\"complete\","
A_FINDINGS = "            _runtime.agent_findings[key] = list(r[\"_findings\"])"
A_URL = "        url = r.get(\"_in_app_url\") or in_app_document_url(key)"
A_LINK = ("            emit_event(\"link_extracted\", phase=2, agent=key, url=url, label=label,\n"
          "                       verified=True, primary=True)")
#: M11 — the relaunch itself.
ELIGIBLE = "    eligible = (1 < phase <= 4) or (is_crash and 0 <= phase <= 4)"
BUDGET = "    crash_budget_ok = crash_retries < BROWSER_CRASH_MAX_RETRIES"

# ── anchors: M5, the curve a kept agent earned (repair round 2) ────────────
#: The record's half of it, downsampled the way save_meta writes.
H_RECORD = "                       \"progressHistory\": _downsample_progress_history(history)}"
#: The one branch that has a curve to record.
H_CALL = "                            history=getattr(_runtime, \"agent_progress_history\", {}).get(agent_key))"
#: Reading it back off disk…
H_READ = "                    \"history\": history if isinstance(history, list) else []}"
#: …onto the kept result…
H_PLAN = "            \"_history\": r[\"history\"],"
#: …and into the ring save_meta persists from.
H_RESTORE = ("        if hist:\n"
             "            _runtime.agent_progress_history[key] = list(hist)\n")
#: The belt: an empty rebuild does not erase what is already persisted.
H_CARRY = ("            if not _down_hist:\n"
           "                _prev_hist = existing.get(\"progressHistory\")\n"
           "                if isinstance(_prev_hist, list) and _prev_hist:\n"
           "                    _down_hist = _prev_hist\n")
#: The step spans the GAPS, so the last index is exactly the last sample.
H_STEP = "    step = (len(raw) - 1) / float(cap - 1)\n"

# ── anchors: M9, the kept agent's row in links.json (repair round 2) ───────
#: The sweep's veto, first.
L_VETO = ("    if r.get(\"off_topic_rejected\"):\n"
          "        return \"\"\n")
#: The kept agent's own arm: no conversation address, and a report all the same.
L_KEPT = ("    if not conversation_url and not r.get(\"_restored\"):\n"
          "        return \"\"\n")
#: What is published — our page, never the address that was judged.
L_VALUE = "    return in_app_document_url(name.lower().replace(\" \", \"\"))\n"
#: The consumer, which must ask.
L_CALL = "        _link_url = _p2_to_p3_link_for(_name, _r, _url)\n"

MUTANTS = [
    # ── P: the decision ─────────────────────────────────────────────────────
    ("P1", "over", RESEARCH,
     "⛔⛔ THE RECORD STOPS BEING CONSULTED — a plain file-existence scan keeps a "
     "salvaged partial (the Stop path's, the finalize re-save's) as a finished agent",
     [(REC_CHECK, "        entry = done.get(key)\n"
                  "        if not isinstance(entry, dict):\n"
                  "            entry = {}")]),
    ("P2", "over", RESEARCH,
     "⛔ the report stops being required — the record alone keeps an agent whose "
     "report a feedback-targeted resume deleted, and the person's redo never runs",
     [(DOC_READ, "            md = doc.read_text(encoding=\"utf-8\")\n"
                 "        except Exception:\n"
                 "            md = \"kept on the record alone\"")]),
    ("P3", "over", RESEARCH,
     "the size bar goes, so a near-empty report counts as a finished one",
     [(DOC_SIZE, "            if doc.stat().st_size <= 0:")]),
    ("P4", "under", RESEARCH,
     "our header stays on the kept text, and every reader downstream sees a "
     "second `# X Deep Research` inside the report",
     [(HEADER, "            pass")]),
    ("P5", "over", RESEARCH,
     "an agent switched off since the crash is kept anyway — its old report "
     "rejoins a phase the person configured without it",
     [(ROSTER, "    for agent in list(done):")]),
    ("P6", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the launch list is the whole roster again, so every "
     "finished Deep Research is bought a second time",
     [(LAUNCH, "    launch = list(enabled_agents or [])")]),
    ("P7", "under", RESEARCH,
     "a kept agent is not `verified`, so it lands in the errored bucket and loses "
     "its 'Read report' link",
     [(VERIFIED, "            \"_in_app_url\": in_app_document_url(key),\n"
                 "            \"verified\": False,")]),
    ("P8", "under", RESEARCH,
     "the kept marker goes, so the finalize re-save re-writes a kept report",
     [(RESTORED_FLAG, "            \"_restored\": False,")]),
    ("P9", "under", RESEARCH,
     "the re-save helper ignores the kept marker",
     [(RESAVE, "    return bool(r.get(\"text\"))")]),
    ("P10", "under", RESEARCH,
     "kept results keyed by agent key, not display name — the safety filter drops "
     "every one of them in silence",
     [(KEPT_KEY, "        kept[key] = {")]),

    # ── W: the writer ───────────────────────────────────────────────────────
    ("W1", "under", RESEARCH,
     "⛔⛔ the complete branch stops recording — nothing is ever kept",
     [(WRITER, "        pass")]),
    ("W2", "over", RESEARCH,
     "⛔⛔ THE FAILED BRANCH RECORDS TOO — an extraction whose Firestore copy the "
     "app cannot open looks finished, and a crash retry never re-runs it",
     [(FAILED_BRANCH, FAILED_BRANCH + "\n        _p2_mark_agent_done(queue_dir, agent_key, True)")]),
    ("W3", "under", RESEARCH,
     "the findings are not carried, so a kept agent's Findings tab falls back to "
     "section headings",
     [(FINDINGS, "findings=None,")]),
    ("W4", "under", RESEARCH,
     "taking an agent out does nothing — a relaunched agent keeps its old entry",
     [(ERASE, "        pass")]),
    ("W5", "over", RESEARCH,
     "a launch on a fresh run writes the file anyway",
     [(NO_WRITE, "        # never creates the file, or recreates a deleted run's folder.\n"
                 "        pass")]),
    ("W6", "over", RESEARCH,
     "the write recreates a deleted run's folder",
     [(NO_PARENTS, "_atomic_write_text(path, json.dumps({\"agents\": agents}), create_parents=True)")]),

    # ── L: the eraser, at each launch ───────────────────────────────────────
    ("L1", "under", RESEARCH,
     "⛔ ChatGPT's launch stops un-finishing it — a salvaged partial from the new "
     "attempt is handed back as the old attempt's finished report",
     [(L_CHATGPT, "        pass")]),
    ("L2", "under", RESEARCH, "the same, for Claude",
     [(L_CLAUDE, "        pass")]),
    ("L3", "under", RESEARCH, "the same, for Gemini",
     [(L_GEMINI, "        pass")]),
    ("L4", "under", RESEARCH,
     "⛔⛔ THE CLEAR MOVES BELOW THE TAB OPENING — still present, still greppable, "
     "and a crash in between keeps the stale entry",
     [(L_CHATGPT, "        pass"),
      (AFTER_2A_OPEN, L_CHATGPT + "\n" + AFTER_2A_OPEN)]),
    ("L5", "over", RESEARCH,
     "one launch clears EVERY agent — a Gemini relaunch re-buys a finished ChatGPT",
     [(L_CHATGPT, "        for _k in (\"chatgpt\", \"gemini\", \"claude\"):\n"
                  "            _p2_mark_agent_done(_p2_run_dir(), _k, False)")]),

    # ── M: the phase itself, `_p2_run_with_resume` ──────────────────────────
    ("M1", "under", RESEARCH,
     "⛔⛔ the main call launches the roster, not the plan",
     [(MAIN_CALL, "enabled_agents=enabled_agents),")]),
    ("M2", "under", RESEARCH,
     "the kept results never join — the phase reports them as missing",
     [(MERGE, "    pass")]),
    ("M3", "over", RESEARCH,
     "⛔ THE KEPT REPORTS ARE DROPPED BETWEEN THE PHASE AND THE SINK — the "
     "off-topic sweep, the links and the hand-off judge a phase that is missing "
     "them, and the call above still reads exactly right",
     [(CONSUMER_STOP, CONSUMER_STOP + "\n"
       "            results = {n: r for n, r in results.items() if not r.get(\"_restored\")}")]),
    ("M4", "under", RESEARCH,
     "the kept agents are never announced — they sit on the web's re-seeded row "
     "for the whole phase",
     [(ANNOUNCE, PLAN)]),
    ("M5", "under", RESEARCH,
     "the plan is asked about no run at all, so it keeps nothing",
     [(PLAN, "    launch, kept = _p2_resume_plan(None, enabled_agents)")]),
    ("M6", "over", RESEARCH,
     "a person's soft-timeout Retry/Skip stops meaning the whole phase",
     [(R_SOFT, "                # phase, as it always has — kept agents included.")]),
    ("M7", "over", RESEARCH,
     "the legacy timeout card's Retry/Skip stops meaning the whole phase",
     [(R_LEGACY, "                pass  # wave 10.9, as above")]),
    ("M8", "over", RESEARCH,
     "new input mid-phase stops reaching the kept agents",
     [(R_RESTART, "        # ⭐ Wave 10.9: new input re-runs the whole phase, kept agents too.")]),
    ("M9", "over", RESEARCH,
     "⛔ ONLY RETRY WIDENS — a Skip keeps the kept results, so a phase the person "
     "skipped is recorded complete after `phase_skipped` said otherwise",
     [(R_SOFT, "                # phase, as it always has — kept agents included."),
      (R_SOFT_RETRY, "                    launch, kept = list(enabled_agents), {}\n"
                     + R_SOFT_RETRY)]),
    ("M10", "over", RESEARCH,
     "⛔⛔ THE SAFETY FILTER IS GIVEN THE LAUNCH LIST INSTEAD OF THE ROSTER — the "
     "obvious simplification, and it throws every kept report away on its way out",
     [(FILTER, "    return _p2_only_enabled(results, launch), user_skipped, False")]),
    ("M11", "under", RESEARCH,
     "the finalize re-save re-writes kept reports again",
     [(RESAVE_SITE, "        if r[\"text\"]:")]),
    ("M12", "under", RESEARCH,
     "⛔⛔ THE DEFECT, RE-OPENED BY ONE ADDED LINE — the launch list is widened "
     "back to the roster after the plan was made, so every finished Deep Research "
     "is bought again while the plan above still looks installed",
     [(ANNOUNCE, ANNOUNCE + "\n    launch = list(enabled_agents)")]),
    ("M13", "under", RESEARCH,
     "⛔⛔ THE SAME, FROM THE OTHER END — one added line empties the kept results, "
     "so they are announced and persisted complete and then dropped from the phase",
     [(MERGE, "    kept = {}\n" + MERGE)]),
    ("M14", "over", RESEARCH,
     "a person's Stop at the timeout card no longer ends the run — the pipeline "
     "carries an empty Phase 2 into Phase 3",
     [(STOPPED, "                return results, user_skipped, False")]),
    ("M15", "over", RESEARCH,
     "the restart cap goes from three attempts to one",
     [(CAP, "    for _p2_attempt in range(1):")]),
    ("M16", "over", RESEARCH,
     "the safety filter drops a kept agent as well as the disabled ones",
     [(FILTER_BODY, "    names = {_agent_display_name(a) for a in enabled_agents}\n"
                    "    results = {n: r for n, r in (results or {}).items() "
                    "if not r.get(\"_restored\")}")]),
    ("M17", "over", RESEARCH,
     "no roster configured means DROP EVERYTHING rather than keep everything",
     [(FILTER_EMPTY, "    if not enabled_agents:\n        return {}")]),

    # ── A: the announce ─────────────────────────────────────────────────────
    ("A1", "under", RESEARCH,
     "the kept agent's persisted status is not written — a daemon restart's empty "
     "status map lets a stale Retry reach it",
     [(A_STATUS, "            pass")]),
    ("A2", "under", RESEARCH,
     "the kept agent is announced as still generating",
     [(A_PROGRESS, "            emit_event(\"agent_progress\", phase=2, agent=key, status=\"generating\",")]),
    ("A3", "under", RESEARCH,
     "the kept agent's findings are not restored for save_meta",
     [(A_FINDINGS, "            pass")]),
    ("A4", "under", RESEARCH,
     "the kept agent's link points at the bare Documents page",
     [(A_URL, "        url = \"/documents\"")]),
    ("A5", "under", RESEARCH,
     "the kept agent's report link is never re-emitted",
     [(A_LINK, "            pass")]),

    # ── N: the kept agent's TEXT is the extraction's, not the file's (D15) ──
    ("N1", "under", RESEARCH,
     "⛔⛔ THE NUMBERED FILE IS HANDED BACK AS THE EXTRACTION — a kept agent's "
     "`##### Sources` list lands in the MIDDLE of the consolidated report, where "
     "the web's end-anchored strip leaves it",
     [(DENUMBER_CALL, "        pass")]),
    ("N2", "under", RESEARCH,
     "only the markers come off — the bibliography still rides into the middle of "
     "the consolidated report",
     [(DENUMBER_BODY, "    return _DOC_SOURCE_MARK_INLINE_RE.sub(\"\", md)")]),
    ("N3", "under", RESEARCH,
     "only the bibliography comes off — the inline `[n]` numbers point at a list "
     "that is no longer there",
     [(DENUMBER_BODY, "    return _strip_numbered_sources_section(md)")]),
    ("N4", "over", RESEARCH,
     "⛔ THE MARKER PATTERN IS WIDENED TO ANY MARKDOWN LINK — every link the agent "
     "wrote itself is deleted out of its own report",
     [(MARK_INLINE_RE, MARK_INLINE_WIDE)]),
    ("N5", "under", RESEARCH,
     "⛔ THE TWO STEPS SWAP — the strip is gated on the markers being present, so "
     "removing them first makes it a no-op and the bibliography survives",
     [(DENUMBER_BODY, "    return _strip_numbered_sources_section("
                      "_DOC_SOURCE_MARK_INLINE_RE.sub(\"\", md))")]),

    # ── S: the kept agent's CARD keeps what its completion showed (D16) ─────
    ("S1", "under", RESEARCH,
     "⛔ the record stops keeping the progress snapshot, so a resumed agent's card "
     "shows complete with 0 sources and no sections for the rest of the phase",
     [(SNAP_STORED, "                       \"progress\": {},")]),
    ("S2", "under", RESEARCH,
     "the completion branch stops handing the snapshot to the record",
     [(SNAP_PASSED, "                            progress=None,")]),
    ("S3", "under", RESEARCH,
     "the announce stops carrying the sources it kept — the web's merge keeps the "
     "re-seeded empty row",
     [(A_SOURCE_URLS, "                       sourceUrls=[],")]),
    ("S4", "under", RESEARCH,
     "the sources COUNT ignores the list it is drawn beside — a panel that never "
     "reported a count leaves the card saying 0 sources over a list of them",
     [(A_SOURCES_MAX, "                       sources=int(snap.get(\"sources\", 0) or 0),")]),
    ("S5", "under", RESEARCH,
     "the in-process snapshot ring is not put back, so save_meta's own readers "
     "see a kept agent with nothing",
     [(SNAP_RESTORE, "            pass")]),
    ("S6", "over", RESEARCH,
     "the record keeps the findings extractor's raw input too — the one field "
     "with no reader and all of the size",
     [(SNAP_LISTS, "_P2_SNAPSHOT_LISTS = (\"source_urls\", \"sections\", \"steps\", "
                   "\"source_items\")")]),
    ("S7", "under", RESEARCH,
     "a count that is not a number goes through as it is, and the emit that "
     "carries the kept agent's report link raises on it",
     [(SNAP_COERCE, "            out[k] = snapshot[k]")]),

    # ── B: M11, the owner decision ──────────────────────────────────────────
    ("B1", "over", RESEARCH,
     "⛔ A HAND-CLOSED WINDOW IN PHASE 2 PUTS A CARD IN FRONT OF THE PERSON — "
     "the self-heal rule reversed without anyone deciding it",
     [(ELIGIBLE, "    eligible = (1 < phase <= 4) and not is_crash")]),
    ("B2", "over", RESEARCH,
     "the crash budget is off by one — a spent budget still relaunches silently",
     [(BUDGET, "    crash_budget_ok = crash_retries <= BROWSER_CRASH_MAX_RETRIES")]),

    # ── H: M5 (repair round 2), the curve a kept agent earned ───────────────
    ("H1", "under", RESEARCH,
     "⛔⛔ THE RECORD STOPS KEEPING THE CURVE — there is nothing to "
     "restore, and the kept agent's sparkline reads 'No data' after the reload",
     [(H_RECORD, "                       \"progressHistory\": []}")]),

    ("H2", "under", RESEARCH,
     "⛔ the whole 240-sample ring goes into the record — four times the "
     "curve the run's own save would have written, and a different one",
     [(H_RECORD, "                       \"progressHistory\": list(history or [])}")]),

    ("H3", "under", RESEARCH,
     "⛔ the completion never reads the ring, so the record is written empty "
     "by the one branch that has a curve to write",
     [(H_CALL, "                            history=None)")]),

    ("H4", "under", RESEARCH,
     "⛔ the reader drops the curve on its way off disk: recorded, and never "
     "handed to the plan",
     [(H_READ, "                    \"history\": []}")]),

    ("H5", "under", RESEARCH,
     "⛔ the plan drops it one step later — the kept result the phase "
     "merges carries everything but the curve",
     [(H_PLAN, "            \"_history\": [],")]),

    ("H6", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the announce restores the snapshot and "
     "not the history, which is exactly what repair round 1 did",
     [(H_RESTORE, "        if hist:\n"
                  "            pass\n")]),

    ("H7", "under", RESEARCH,
     "⛔⛔ THE BELT GOES — a rebuild with an empty ring erases the "
     "curve a previous attempt persisted, in meta.json and in the whole-field "
     "Firestore replace",
     [(H_CARRY, "            if False:\n"
                "                _prev_hist = existing.get(\"progressHistory\")\n"
                "                if isinstance(_prev_hist, list) and _prev_hist:\n"
                "                    _down_hist = _prev_hist\n")]),

    ("H8", "over", RESEARCH,
     "⛔ the persisted curve is preferred to the LIVE ring — an agent "
     "that ran again this attempt is frozen on its first attempt's curve",
     [(H_CARRY, "            _prev_hist = existing.get(\"progressHistory\")\n"
                "            if isinstance(_prev_hist, list) and _prev_hist:\n"
                "                _down_hist = _prev_hist\n")]),

    # ⭐ H9 WAS AN EQUIVALENT MUTANT AND IS GONE. It deleted the two lines that
    # overwrote `out[0]`/`out[-1]` with `raw[0]`/`raw[-1]`, and with a step of
    # (n-1)/(cap-1) those lines never had anything to correct — no test could
    # tell them from nothing, and against a WRONG step they would have made a
    # mis-sampled curve look right at both ends. The lines are gone from
    # research.py; H9 is the step itself now.
    ("H9", "under", RESEARCH,
     "⛔ the step spans the SAMPLES instead of the gaps — sixty points "
     "with plausible endpoints and the wrong curve between them",
     [(H_STEP, "    step = len(raw) / float(cap)\n")]),

    # ── K: M9 (repair round 2), the kept agent's row in links.json ──────────
    # ⚠ K, not L: the launch section above already owns L1-L5, and two mutants
    # under one id make `python <harness> L1` run both and a survivor ambiguous.
    ("K1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — a kept agent has no conversation "
     "address, so it vanishes from links.json and delivery.json while its report "
     "still goes to NotebookLM",
     [(L_KEPT, "    if not conversation_url:\n"
               "        return \"\"\n")]),

    ("K2", "over", RESEARCH,
     "⛔⛔ the sweep's veto is lost on the kept path: a leg refused as "
     "off-topic is published as a source because it was restored",
     [(L_VETO, "    if False:\n"
               "        return \"\"\n")]),

    ("K3", "over", RESEARCH,
     "⛔⛔ every leg publishes — including one that never opened a "
     "tab, and both drop guards are skipped on the way",
     [(L_KEPT, "    if False:\n"
               "        return \"\"\n")]),

    ("K4", "under", RESEARCH,
     "⛔⛔ the consumer stops asking the decision and gates on the "
     "conversation address again — the decision is still there, unread",
     [(L_CALL, "        _link_url = (in_app_document_url(_name.lower().replace(\" \", \"\"))\n"
               "                     if _url else \"\")\n")]),

    ("K5", "under", RESEARCH,
     "⛔ what is JUDGED becomes what is PUBLISHED again — the "
     "conversation address lands in links.json and goes to NotebookLM as a source",
     [(L_VALUE, "    return conversation_url\n")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    r = _run(f"\"{PY}\" -m pytest {SUITES} -q -p no:cacheprovider")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. The LAST line only: a
    # pytest warning about tmp cleanup says "error removing" further up.
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    summary = lines[-1] if lines else ""
    return ("passed" in summary and "failed" not in summary
            and "error" not in summary)


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full mutation run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}


    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")


    only = set(sys.argv[1:])
    # Static anchor sweep first: a stale or duplicate anchor is a harness fault.
    faults = []
    for mid, _d, fname, _why, edits in MUTANTS:
        text = ORIGINALS[fname]
        for frm, to in edits:
            if frm == to:
                faults.append(f"{mid}: replacement identical to anchor")
            elif text.count(frm) != 1:
                faults.append(f"{mid}: anchor occurs {text.count(frm)}x: {frm[:70]!r}")
            text = text.replace(frm, to)
    if faults:
        print("⛔ HARNESS FAULTS — fix the anchors before mutating anything:")
        for f in faults:
            print("  " + f)
        sys.exit(2)
    print(f"anchor sweep: {len(MUTANTS)} mutants, every anchor matches once")

    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
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
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
