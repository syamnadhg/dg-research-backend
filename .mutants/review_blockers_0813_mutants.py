"""Mutation harness for the three blocking findings of the 2026-08-12 review.

All three are missing-guard findings, and for every one of them the cheapest
wrong fix is a guard that refuses everything — which looks like caution and
silently deletes the feature. So the OVER-corrections carry most of the weight
here, and three of them are the reviewer's own suggested fixes:

  * gating the port reclaim on `_port_answers_health` (R7), which would refuse
    every reclaim because `/api/health` answers ok unconditionally;
  * requiring a version before a click counts as a pick (M7), which would empty
    the model menu on the day a vendor ships a version-less label;
  * merging on EVERY status write (S6), which would leave a previous attempt's
    verdict underneath a newer one.

Two files are mutated, so each mutant names its own.

Safety, learned from an earlier harness on this repo that adopted a mutant as
its own baseline: refuses to start on a dirty tree, holds originals in memory
only, restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/review_blockers_0813_mutants.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_review_blockers_0813.py "
          "tests/test_device_update_command.py "
          "tests/test_update_never_silent.py "
          "tests/test_claude_model_pick.py "
          "tests/test_claude_popover_skip.py "
          "tests/test_known_good_fallback.py "
          "tests/test_serve_port_reclaim_0810.py")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ finding 1 — a second --serve must not end a live run ═══════
    ("R1", "research.py", "under",
     "⭐ the busy guard is gone — the finding, restored verbatim",
     # RE-ANCHORED 08-23: the probe is now retried across the settle window.
     [('    _activity = _probe_backend_activity_until_settled(port, settle_s)\n'
       '    if _backend_activity_is_work(_activity):', '    if False:')]),
    ("R2", "research.py", "under",
     "`running` no longer counts as work — only a queued job would refuse",
     [('    return bool(activity.get("running")) or (activity.get("pending") or 0) > 0',
       '    return (activity.get("pending") or 0) > 0')]),
    ("R3", "research.py", "under",
     "`pending` no longer counts — a queued job is destroyed between runs",
     [('    return bool(activity.get("running")) or (activity.get("pending") or 0) > 0',
       '    return bool(activity.get("running"))')]),
    ("R4", "research.py", "under",
     "the probe reads the status line again, so every holder looks idle",
     [("            if not 200 <= getattr(r, \"status\", 200) < 300:\n"
       "                return None\n"
       "            body = json.loads(r.read().decode(\"utf-8\"))",
       "            body = {\"status\": \"ok\"} if r else {}")]),
    ("R5", "research.py", "under",
     "a non-2xx answer is trusted, so an error page decides whether we kill",
     [("            if not 200 <= getattr(r, \"status\", 200) < 300:\n"
       "                return None\n", "")]),
    ("R6", "research.py", "over",
     "⛔ silence is read as work — the terminal-less orphan is never cleared "
     "and the unexplained EADDRINUSE comes back",
     [("    if not activity:\n        return False", "    if not activity:\n        return True")]),
    ("R7", "research.py", "over",
     "⛔ THE REVIEW'S LITERAL SUGGESTION — gate on the liveness probe. Health "
     "answers ok unconditionally, so this refuses EVERY reclaim",
     # RE-ANCHORED 08-23, same move as R1.
     [('    _activity = _probe_backend_activity_until_settled(port, settle_s)\n'
       '    if _backend_activity_is_work(_activity):',
       '    _activity = _probe_backend_activity_until_settled(port, settle_s)\n'
       '    if _port_answers_health(port):')]),
    ("R8", "research.py", "over",
     "⛔ every holder we recognise is refused — reclaim disabled outright",
     [("    if _backend_activity_is_work(_activity):", "    if True:")]),
    ("R9", "research.py", "under",
     "the caller no longer refuses the bind, so a live run is bound over",
     [('    if _port_state == "busy":', '    if False:')]),
    ("R10", "research.py", "under",
     "the busy verdict is reported as free, so the guard never reaches the caller",
     [('        return "busy", ours', '        return "free", []')]),
    ("R11", "research.py", "over",
     "⛔ identity stops outranking activity — a foreign holder is probed and, "
     "if quiet, killed",
     [("    if foreign:\n        return \"foreign\", foreign\n", "")]),

    # ═══════════ finding 2 — a billing chip is not a model ══════════════════
    ("M1", "research.py", "under",
     "⭐ the browser no longer excludes chips — the finding, restored",
     [("                if (isUpsell(t)) continue;\n", "")]),
    ("M2", "research.py", "under",
     "the exclusion moves after the version parse and only fires on "
     "version-less rows — the narrow triage that missed the versioned chip",
     [("                if (isUpsell(t)) continue;\n"
       "                const v = verOf(t);\n"
       "                const isFam = v !== null || famRe.test(t);",
       "                const v = verOf(t);\n"
       "                const isFam = v !== null || (famRe.test(t) && !isUpsell(t));")]),
    ("M3", "research.py", "under",
     "the verb boundary is dropped, so 'regetopus' reads as a sales prompt",
     # ⛔⛔ RE-ANCHORED 08-23. THREE BYTE-IDENTICAL COPIES of this filter now
     # live in research.py — the picker, the probe and the dropdown click —
     # plus a fourth in the Gemini ranker, so the old one-line anchors matched
     # 2-3x and measured nothing. Each mutant below is now pinned to a
     # DIFFERENT copy on purpose: the suite only ever exercised one, and a
     # copy nothing measures will now show up as a SURVIVOR rather than as
     # silence.
     # M3 → the PICKER copy.
     [('            // a "character-for-character port" turned out not to be one.\n'
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), n = normU(fam).toLowerCase();\n'
       '                if (!s || !n) return false;\n'
       '                // ⛔ NO "FAMILY NAMED FIRST" EXEMPTION, and this comment used to\n'
       '                // describe one that is not here. It was tried and REVERTED\n'
       '                // 2026-08-14 because it re-opened the blocking finding: driven\n'
       '                // through this very JS, a menu whose top row read\n'
       '                // "Opus 5 · Upgrade to Opus Max for more usage" was clicked and\n'
       '                // returned as a confirmed pick. So a genuine row whose blurb\n'
       '                // happens to read verb-then-family IS dropped here, on purpose.\n'
       '                // See models.is_upsell for the full account.\n'
       '                for (const rawVerb of (verbs || [])) {\n'
       '                    const verb = String(rawVerb).toLowerCase();\n'
       '                    if (!verb) continue;\n'
       '                    let i = s.indexOf(verb);\n'
       '                    while (i !== -1) {\n'
       '                        const end = i + verb.length;\n'
       '                        const leftOk = i === 0 || !isAlnum(s[i - 1]);\n'
       '                        const rightOk = end >= s.length || !isAlnum(s[end]);\n'
       '                        if (leftOk && rightOk) {\n'
       '                            const j = s.indexOf(n, end);\n',
       '            // a "character-for-character port" turned out not to be one.\n'
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), n = normU(fam).toLowerCase();\n'
       '                if (!s || !n) return false;\n'
       '                // ⛔ NO "FAMILY NAMED FIRST" EXEMPTION, and this comment used to\n'
       '                // describe one that is not here. It was tried and REVERTED\n'
       '                // 2026-08-14 because it re-opened the blocking finding: driven\n'
       '                // through this very JS, a menu whose top row read\n'
       '                // "Opus 5 · Upgrade to Opus Max for more usage" was clicked and\n'
       '                // returned as a confirmed pick. So a genuine row whose blurb\n'
       '                // happens to read verb-then-family IS dropped here, on purpose.\n'
       '                // See models.is_upsell for the full account.\n'
       '                for (const rawVerb of (verbs || [])) {\n'
       '                    const verb = String(rawVerb).toLowerCase();\n'
       '                    if (!verb) continue;\n'
       '                    let i = s.indexOf(verb);\n'
       '                    while (i !== -1) {\n'
       '                        const end = i + verb.length;\n'
       '                        if (true) {\n'
       '                            const j = s.indexOf(n, end);\n')]),
    ("M4", "research.py", "under",
     "the proximity window is unbounded — any verb anywhere bins a real row",
     # RE-ANCHORED 08-23 → the PROBE copy (see M3's note).
     [("            // Same whitespace set as the picker's port and models._collapse_ws —\n"
       "            // see the picker for why JS's own `\\\\s` is the wrong set here.\n"
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), nn = normU(fam).toLowerCase();\n'
       '                if (!s || !nn) return false;\n'
       '                for (const rawVerb of (verbs || [])) {\n'
       '                    const verb = String(rawVerb).toLowerCase();\n'
       '                    if (!verb) continue;\n'
       '                    let i = s.indexOf(verb);\n'
       '                    while (i !== -1) {\n'
       '                        const end = i + verb.length;\n'
       '                        const leftOk = i === 0 || !isAlnum(s[i - 1]);\n'
       '                        const rightOk = end >= s.length || !isAlnum(s[end]);\n'
       '                        if (leftOk && rightOk) {\n'
       '                            const j = s.indexOf(nn, end);\n'
       '                            if (j !== -1 && j - end <= upsellWindow) return true;\n',
       "            // Same whitespace set as the picker's port and models._collapse_ws —\n"
       "            // see the picker for why JS's own `\\\\s` is the wrong set here.\n"
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), nn = normU(fam).toLowerCase();\n'
       '                if (!s || !nn) return false;\n'
       '                for (const rawVerb of (verbs || [])) {\n'
       '                    const verb = String(rawVerb).toLowerCase();\n'
       '                    if (!verb) continue;\n'
       '                    let i = s.indexOf(verb);\n'
       '                    while (i !== -1) {\n'
       '                        const end = i + verb.length;\n'
       '                        const leftOk = i === 0 || !isAlnum(s[i - 1]);\n'
       '                        const rightOk = end >= s.length || !isAlnum(s[end]);\n'
       '                        if (leftOk && rightOk) {\n'
       '                            const j = s.indexOf(nn, end);\n'
       '                            if (j !== -1) return true;\n')]),
    ("M5", "research.py", "under",
     "the probe stops excluding chips — 'offered but not clickable', forever",
     # RE-ANCHORED 08-23: the branch grew a chip COUNT, so `continue` is no
     # longer the next line.
     [("                const raw = (el.textContent || '').trim();\n"
       '                if (isUpsell(raw)) {\n',
       "                const raw = (el.textContent || '').trim();\n"
       '                if (false) {\n')]),
    ("M6", "research.py", "over",
     "⛔ the family word alone disqualifies a row — the menu is always empty",
     # RE-ANCHORED 08-23 → the DROPDOWN-CLICK copy (see M3's note).
     [('            // the guard existed one function away.\n'
       "            const isAlnum = c => !!c && ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'));\n"
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n',
       '            // the guard existed one function away.\n'
       "            const isAlnum = c => !!c && ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'));\n"
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => { return true;\n')]),
    ("M7", "research.py", "over",
     "⛔ THE REVIEW'S SECOND SUGGESTION — a version-less row can no longer be "
     "picked, so a rename empties the menu",
     [("                const isFam = v !== null || famRe.test(t);",
       "                const isFam = v !== null;")]),
    ("M8", "research.py", "over",
     "⛔ a bare verb test — a genuine row whose blurb says 'try' is binned",
     # RE-ANCHORED 08-23 → the PICKER copy (see M3's note).
     [('            // a "character-for-character port" turned out not to be one.\n'
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), n = normU(fam).toLowerCase();\n'
       '                if (!s || !n) return false;\n'
       '                // ⛔ NO "FAMILY NAMED FIRST" EXEMPTION, and this comment used to\n'
       '                // describe one that is not here. It was tried and REVERTED\n'
       '                // 2026-08-14 because it re-opened the blocking finding: driven\n'
       '                // through this very JS, a menu whose top row read\n'
       '                // "Opus 5 · Upgrade to Opus Max for more usage" was clicked and\n'
       '                // returned as a confirmed pick. So a genuine row whose blurb\n'
       '                // happens to read verb-then-family IS dropped here, on purpose.\n'
       '                // See models.is_upsell for the full account.\n'
       '                for (const rawVerb of (verbs || [])) {\n'
       '                    const verb = String(rawVerb).toLowerCase();\n'
       '                    if (!verb) continue;\n'
       '                    let i = s.indexOf(verb);\n'
       '                    while (i !== -1) {\n'
       '                        const end = i + verb.length;\n'
       '                        const leftOk = i === 0 || !isAlnum(s[i - 1]);\n'
       '                        const rightOk = end >= s.length || !isAlnum(s[end]);\n'
       '                        if (leftOk && rightOk) {\n'
       '                            const j = s.indexOf(n, end);\n'
       '                            if (j !== -1 && j - end <= upsellWindow) return true;\n',
       '            // a "character-for-character port" turned out not to be one.\n'
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), n = normU(fam).toLowerCase();\n'
       '                if (!s || !n) return false;\n'
       '                // ⛔ NO "FAMILY NAMED FIRST" EXEMPTION, and this comment used to\n'
       '                // describe one that is not here. It was tried and REVERTED\n'
       '                // 2026-08-14 because it re-opened the blocking finding: driven\n'
       '                // through this very JS, a menu whose top row read\n'
       '                // "Opus 5 · Upgrade to Opus Max for more usage" was clicked and\n'
       '                // returned as a confirmed pick. So a genuine row whose blurb\n'
       '                // happens to read verb-then-family IS dropped here, on purpose.\n'
       '                // See models.is_upsell for the full account.\n'
       '                for (const rawVerb of (verbs || [])) {\n'
       '                    const verb = String(rawVerb).toLowerCase();\n'
       '                    if (!verb) continue;\n'
       '                    let i = s.indexOf(verb);\n'
       '                    while (i !== -1) {\n'
       '                        const end = i + verb.length;\n'
       '                        const leftOk = i === 0 || !isAlnum(s[i - 1]);\n'
       '                        const rightOk = end >= s.length || !isAlnum(s[end]);\n'
       '                        if (leftOk && rightOk) {\n'
       '                            return true;\n')]),
    ("M9", "research.py", "under",
     "the verb list is never passed, so the browser excludes nothing",
     [('                          "verbs": list(UPSELL_VERBS), "upsellWindow": UPSELL_WINDOW}',
       '                          "verbs": [], "upsellWindow": UPSELL_WINDOW}')]),
    ("M10", "models.py", "under",
     "the python mirror stops excluding chips",
     [("        if drop_upsell and (is_upsell_any(t, sale_nouns) if sale_nouns\n"
       "                            else is_upsell(t, family)):\n            continue\n", "")]),
    ("M11", "models.py", "under",
     "the mirror's boundary check is dropped",
     [("            left_ok = i == 0 or not _ascii_alnum(t[i - 1])\n"
       "            right_ok = end >= len(t) or not _ascii_alnum(t[end])\n"
       "            if left_ok and right_ok:", "            if True:")]),
    ("M12", "models.py", "under",
     "the mirror's window is unbounded",
     [("                if j != -1 and j - end <= window:", "                if j != -1:")]),
    ("M13", "models.py", "under",
     "the mirror requires the noun BEFORE the verb — inverted, so real rows "
     "are binned and chips pass",
     [("                j = t.find(n, end)", "                j = t.find(n)")]),
    ("M14", "models.py", "over",
     "⛔ the exclusion becomes default-on, so the un-ported Gemini ranker and "
     "this mirror answer differently",
     [("def pick_highest_model(labels, family: str, below=None, reject=(), drop_upsell=False,\n"
       "                       sale_nouns=None):",
       "def pick_highest_model(labels, family: str, below=None, reject=(), drop_upsell=True,\n"
       "                       sale_nouns=None):")]),
    ("M15", "models.py", "under",
     "the verb list forks from the one the tier picker and the mission read",
     [('        "upgrade_verbs": UPSELL_VERBS,', '        "upgrade_verbs": ["upgrade"],')]),
    ("M16", "models.py", "under",
     "whitespace is no longer collapsed, so a row split across lines escapes",
     # RE-ANCHORED 08-23: the collapse moved into `_collapse_ws`, which is now
     # shared with the JS port — so the mutant has to remove BOTH calls.
     [('    t = _collapse_ws(text).lower()\n    n = _collapse_ws(noun).lower()',
       '    t = (text or \"\").lower()\n    n = (noun or \"\").lower()')]),

    # ═══════════ finding 3 — a refusal must not lower needsRestart ══════════
    ("S1", "research.py", "under",
     "⭐ merge does nothing — the whole map is replaced again, the finding",
     [("        if merge:\n            # Keys here are in-tree literals",
       "        if False:\n            # Keys here are in-tree literals")]),
    ("S2", "research.py", "under",
     "the busy restart refusal replaces again — the exact branch reported",
     [('                        "reason": "a research run is in progress"}, merge=True)',
       '                        "reason": "a research run is in progress"})')]),
    ("S3", "research.py", "under",
     "the not-the-owner restart refusal replaces — a sharer erases the owner's flag",
     # RE-ANCHORED 08-23: the same refusal line now exists on the update button
     # too, so the one-liner matched twice. Pinned to the RESTART branch.
     [('                        "state": "failed", "current": _sr_version(),\n'
       '                        "reason": "not the device owner"}, merge=True)',
       '                        "state": "failed", "current": _sr_version(),\n'
       '                        "reason": "not the device owner"})')]),
    ("S4", "research.py", "under",
     "the no-identity restart refusal replaces",
     [('                        "reason": "could not verify device ownership"}, merge=True)',
       '                        "reason": "could not verify device ownership"})')]),
    ("S5", "research.py", "under",
     "a refusal writes `latest` again — under dotted paths that nulls it exactly "
     "as before, so the fix is undone one key at a time",
     [('                        "state": "deferred", "current": _sr_version(),\n'
       '                        "reason": "a research run is in progress"}, merge=True)',
       '                        "state": "deferred", "current": _sr_version(),\n'
       '                        "latest": None,\n'
       '                        "reason": "a research run is in progress"}, merge=True)')]),
    ("S6", "research.py", "over",
     "⛔ EVERY write merges — a completed verdict inherits the previous "
     "attempt's evidence and can never clear needsRestart",
     [("def _write_update_status(device_id: str, status: dict, *, merge: bool = False) -> bool:",
       "def _write_update_status(device_id: str, status: dict, *, merge: bool = True) -> bool:")]),
    ("S7", "research.py", "over",
     "⛔ a refusal re-asserts needsRestart itself, so the button outlives the "
     "restart that satisfied it",
     [('            payload = {f"updateStatus.{k}": v for k, v in status.items()}',
       '            payload = {f"updateStatus.{k}": v for k, v in status.items()}\n'
       '            payload["updateStatus.needsRestart"] = True')]),
    ("S8", "research.py", "under",
     "the merge branch drops its stamp, so the app never sees the refusal",
     [('            payload["updateStatus.at"] = _at\n', "")]),
    ("S9", "research.py", "under",
     "the update handler's mid-run defer replaces again",
     [('        _write_update_status(device_id, {"state": "deferred", "current": cur,\n'
       '                                         "reason": "a research run is in progress"},\n'
       '                             merge=True)',
       '        _write_update_status(device_id, {"state": "deferred", "current": cur,\n'
       '                                         "reason": "a research run is in progress"})')]),
]


# ⛔ 2026-08-13 — THIS HARNESS LIED ONCE, AND THE LIE IS THE DANGEROUS DIRECTION.
# The first run reported nine survivors; six of them were killed the moment the
# same mutant was applied by hand. The results were not even stable between
# runs of the harness itself.
#
# The cause is cached bytecode. `research.py` is 3.5 MB, so its `__pycache__`
# entry is worth a lot of wall-clock, and CPython decides whether to reuse it
# from the source's mtime IN WHOLE SECONDS plus its size. A harness rewrites
# one file repeatedly, in place, in quick succession — which is precisely the
# pattern that pair cannot separate. When the stale `.pyc` won, the test process
# imported the ORIGINAL code, every test passed, and the mutant was recorded as
# surviving: a report that the suite has a hole where it does not.
#
# ⭐ A false SURVIVOR wastes an afternoon. A false KILL is worse — it certifies
# coverage that does not exist. Both are possible here, so bytecode is disabled
# outright (`-B` plus the env var, because the flag governs only the child) and
# every `__pycache__` under the tree is removed before each run. The cost is
# about a second per run; the alternative is a harness whose output cannot be
# trusted in either direction.
# ⛔ AND THE BYTECODE WAS NOT THE WHOLE STORY. After disabling it the verdicts
# were still unstable — different mutants "survived" on each run, and every one
# of them died when applied by hand. The dev venv carries an EDITABLE INSTALL of
# the PERSONAL checkout, so `import research` has two possible answers on this
# machine and the loser is whichever `sys.path` entry lost the race. A test
# process that resolved `dg-research-backend` read UNMUTATED source, passed
# everything, and the mutant was recorded as surviving.
#
# PYTHONPATH pins this worktree ahead of the editable finder, and
# `test_the_suite_is_testing_THIS_tree` fails loudly if it is ever not the one
# imported. The re-run below is the backstop: a SURVIVED verdict is the
# expensive, misleading one, so it is never believed on a single observation.
ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

# How many times a claimed survivor must survive before it is reported as one.
SURVIVOR_CONFIRMATIONS = 3


def sh(cmd: list[str], *, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          env=env or ENV)


def purge_pycache() -> None:
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--",
              "research.py", "models.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


# ⛔⛔ THE SUMMARY LINE ONLY. A bare `(\d+)\s+skipped` scan over all of pytest's
# output reads the ASSERTION DIFFS too — and this guard's own tests carry strings
# like "72 passed, 68 skipped in 17.48s" as fixtures. Measured 2026-08-27: five
# mutants came back "68 test(s) skipped — verdict refused" when nothing had
# skipped at all; the detector was reading the test data it was being tested
# with. The apparatus lied about the apparatus.
SUMMARY_RE = re.compile(r"^=*\s*(?:\d+\s+\w+(?:,\s*)?)+\s+in\s+[\d.]+s", re.M)
SKIP_RE = re.compile(r"(\d+)\s+skipped")


def skipped_count(pytest_output: str) -> int:
    """How many tests pytest SKIPPED, read off its own summary.

    ⛔⛔ THIS EXISTS BECAUSE THE HARNESS ONCE SCORED ITSELF AGAINST HALF A SUITE
    AND SAID 35/36. 2026-08-27: run from a shell with no `node` on PATH, 68 of
    the 140 tests in `test_review_blockers_0813.py` skipped — including all three
    that kill M6 — and pytest still exited 0. The harness read "exit 0" as "no
    test caught this" and printed `✗ SURVIVED M6`, three confirmations deep,
    because re-running a broken environment reproduces the broken result.

    ▶ A SKIP IS NOT A PASS, AND IT IS NOT A FAILURE EITHER — it is the absence
    of a measurement, and a mutation score computed over absences is a lie in
    BOTH directions. A false survivor costs a repair round chasing a defect that
    does not exist; a false KILL is worse, and silently hides one that does.

    Reads the LAST match: pytest prints per-file progress before the summary and
    a stray "1 skipped" in a test name must not be mistaken for the total.
    """
    summaries = SUMMARY_RE.findall(pytest_output or "")
    line = None
    for m in SUMMARY_RE.finditer(pytest_output or ""):
        line = m.group(0)
    if line is None:
        return 0
    hits = SKIP_RE.findall(line)
    return int(hits[-1]) if hits else 0


def run_tests() -> "tuple[bool, int]":
    """(green, skipped). ⛔ BOTH halves matter — see `skipped_count`."""
    purge_pycache()
    proc = sh([sys.executable, "-B", "-m", "pytest", *SUITES.split(), "-q",
               "-p", "no:cacheprovider"])
    return proc.returncode == 0, skipped_count(proc.stdout + proc.stderr)


def missing_tooling() -> list[str]:
    """Executables the SUITES need, that are not on PATH.

    ⛔ `node` is not optional here. The three Claude model-menu filters are
    JavaScript evaluated in the page, and the only tests that execute them
    (rather than grep the source) shell out to node. Without it they skip, and
    the harness goes blind to an entire finding while still printing a score.
    """
    return [exe for exe in ("node", "git") if shutil.which(exe) is None]


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    absent = missing_tooling()
    if absent:
        print("Missing from PATH: " + ", ".join(absent) + ".\n"
              "⛔ REFUSING TO SCORE. The JavaScript filters are executed by node; without it\n"
              "   those tests SKIP and every mutant in them looks like a survivor. Run this\n"
              "   from an interactive shell, or put the tools on PATH first.")
        return 2

    print("baseline… ", end="", flush=True)
    ok, skipped = run_tests()
    if not ok:
        print("RED. Nothing below would mean anything.")
        return 2
    if skipped:
        print(f"green, but {skipped} test(s) SKIPPED.\n"
              "⛔ REFUSING TO SCORE. A skip is the absence of a measurement, not a pass —\n"
              "   a mutant those tests would have killed is reported as a SURVIVOR, and one\n"
              "   they would have missed is reported as KILLED. Fix the skips first.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in MUTANTS:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found in {fname}: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            # Belt and braces after the stale-bytecode incident: prove the edit
            # is on disk before crediting anything to the suite.
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            green, skipped = run_tests()
            # ⛔⛔ A SKIP MID-RUN IS A FAULT, NOT A VERDICT. The environment can
            # lose a tool between mutants (a PATH change, a crashed helper), and
            # from here that is indistinguishable from a suite with no opinion.
            # Raising routes it to the `! ERROR` arm — loud, and counted against
            # the score — rather than letting it print a confident `SURVIVED`.
            if skipped:
                raise AssertionError(f"{skipped} test(s) skipped — verdict refused")
            killed = not green
            flapped = False
            # Only a survivor needs confirming: a kill is one failing assertion
            # and cannot be produced by importing the wrong copy.
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                green, skipped = run_tests()
                if skipped:
                    raise AssertionError(f"{skipped} test(s) skipped — verdict refused")
                killed = not green
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
