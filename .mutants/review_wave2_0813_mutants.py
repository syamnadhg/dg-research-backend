"""Mutation harness for wave 2 — the backend remainder of the 2026-08-12 review.

Different shape from wave 1's. These are not missing guards, they are wrong
IDENTIFICATIONS and wrong CEILINGS, so the cheapest wrong fix is usually one
that matches too much rather than too little:

  * a `.exe` strip that relaxes the whole predicate (X3, X4) — everything
    downstream of it can end a process, so a looser match is someone else's work
    terminated, not a cosmetic regression;
  * a cache cleaner that matches on a prefix or falls back to a wildcard (C4,
    C5) — the caller rmtree's what it says yes to;
  * a pipx floor turned into a BLOCK rather than a note (P4), which would break
    installs on the pip backend that work today;
  * consolidating narrate's generationConfig without the opt-out (G2), which
    hands a deliberate refusal to an env var and fails nothing.

⚠ Two files here are never imported in production shape — the wheel's
`_sr_core` split (vision/narrate) and the waiter that ships as a `-c` string —
so the mutants for those are the only thing standing between a green suite and
a defect that only appears in a build nobody tests.

Five files are mutated and TWO suites are run: the root one and the agent's,
which has its own rootdir and needs `agent/` on the path.

Safety, same as wave 1: refuses to start on a dirty tree, holds originals in
memory only, restores in `finally`, re-checks `git status` at the end, and
re-runs any claimed SURVIVOR before believing it — the dev venv carries an
editable install of another checkout and has produced phantom survivors before.

    .venv/bin/python .mutants/review_wave2_0813_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_SUITES = ("tests/test_review_wave2_0813.py "
               "tests/test_review_blockers_0813.py "
               "tests/test_gemini_thinking_config_rejected.py "
               "tests/test_windows_spawn_and_pipx_uv.py "
               "tests/test_serve_port_reclaim_0810.py "
               "tests/test_vision_engine.py "
               "tests/test_narrator_circuit_breaker.py")

AGENT_SUITES = ("tests/test_review_wave2_0813.py "
                "tests/test_durable_install.py "
                "tests/test_selfupdate.py "
                "tests/test_selfupdate_version_floor.py")

MUTATED_FILES = ("research.py", "models.py", "narrate.py", "vision.py",
                 "agent/facade/selfupdate.py", "tools/build_compiled.py")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ 4 — the Windows console script is ours ═════════════════════
    ("X1", "research.py", "under",
     "⭐ the .exe strip is gone from the holder scan — the finding, restored",
     [("    base = [_strip_exe(os.path.basename(x).lower()) for x in toks]",
       "    base = [os.path.basename(x).lower() for x in toks]")]),
    ("X2", "research.py", "under",
     "the stripper only removes a bare '.exe', so no real basename matches",
     [('    return b[:-4] if b.lower().endswith(".exe") else b',
       "    return b if b else b")]),
    ("X3", "research.py", "over",
     "⛔ the suffix is stripped ANYWHERE, so 'superresearch.exe.bak' and "
     "'x.exe.log' collapse onto our name — this predicate ends processes",
     [('    return b[:-4] if b.lower().endswith(".exe") else b',
       '    return b.lower().replace(".exe", "")')]),
    ("X4", "research.py", "over",
     "⛔ the console check becomes a prefix test, so 'superresearchd' is us",
     [('    runs_console = any(b == "superresearch" for b in base)',
       '    runs_console = any(b.startswith("superresearch") for b in base)')]),
    ("X5", "research.py", "over",
     "⛔ --serve stops gating, so the user's own --pair is reclaimable",
     [('    if "--serve" not in toks:\n        return False',
       '    if False:\n        return False')]),
    ("X6", "research.py", "under",
     "_prog_name stops sharing the stripper and re-inlines its own copy — the "
     "two-copies condition this finding arrived in",
     [("    stem = _strip_exe(base)",
       '    stem = base[:-4] if base.lower().endswith(".exe") else base')]),

    # ═══════════ 5 — a Gemini 200 with no text says why ═════════════════════
    ("T1", "research.py", "under",
     "⭐ the title ceiling goes back to 120 — thinking spends it and the title "
     "is never refreshed",
     [('            "generationConfig": _gemini_gen_config(temperature=0.3, max_tokens=600),',
       '            "generationConfig": _gemini_gen_config(temperature=0.3, max_tokens=120),')]),
    ("T2", "research.py", "under",
     "the empty-200 log is gone from the title leg — the silent swallow",
     [('        if not (text or "").strip():\n'
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} returned no text — "\n'
       '                f"{_gemini_empty_reason(j)}", "WARN")\n', "")]),
    ("T3", "research.py", "under",
     "the log fires but drops the reason, so a spent budget and a blocked "
     "prompt read identically",
     # RE-ANCHORED 08-23: the summary path grew the same log line, so the
     # one-liner matched twice. Pinned to the TITLE-REFRESH call by its own
     # preceding line.
     [('            log(f"[title-refresh] Gemini {GEMINI_TEXT} returned no text — "\n'
       '                f"{_gemini_empty_reason(j)}", "WARN")',
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} returned no text — "\n'
       '                f"(no text)", "WARN")')]),
    ("T4", "research.py", "over",
     "⛔ the empty-200 log fires on EVERY call, including every success — the "
     "line becomes noise and stops being read",
     [('        if not (text or "").strip():\n'
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} returned no text — "',
       '        if True:\n'
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} returned no text — "')]),
    ("T5", "research.py", "over",
     "⛔ an empty 200 now RAISES instead of returning '' — the caller loses its "
     "non-LLM fallback and the run has no title at all",
     [('        if not (text or "").strip():\n'
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} returned no text — "\n'
       '                f"{_gemini_empty_reason(j)}", "WARN")\n'
       '        return (text or "").strip()',
       '        if not (text or "").strip():\n'
       '            raise RuntimeError(_gemini_empty_reason(j))\n'
       '        return (text or "").strip()')]),
    ("T6", "research.py", "under",
     "the summary leg loses its empty-200 log — the sibling site the review "
     "asked for too",
     [('        if not (text or "").strip():\n'
       '            log(f"[summary] Gemini {GEMINI_TEXT} returned no text — "\n'
       '                f"{_gemini_empty_reason(j)}", "WARN")\n', "")]),
    ("T7", "research.py", "under",
     "the status check is dropped, so a 400 is parsed as an empty answer again",
     [('        if getattr(resp, "status_code", 200) != 200:\n'
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} refused — "',
       '        if False:\n'
       '            log(f"[title-refresh] Gemini {GEMINI_TEXT} refused — "')]),

    # ═══════════ 6 — the cache cleaner owns one distribution ════════════════
    ("C1", "agent/facade/selfupdate.py", "under",
     "⭐ the cleaner identifies us by a bare `facade` package again — the "
     "finding, restored, and it deletes strangers' cached tools",
     [('                    stem = meta.name.rsplit(".", 1)[0]\n'
       '                    if _norm(stem.split("-", 1)[0]) == dist_norm:\n'
       '                        return True',
       '                    if (sp / "facade").is_dir():\n'
       '                        return True')]),
    ("C2", "agent/facade/selfupdate.py", "under",
     "normalization is dropped, so `superresearch_agent-…` never matches the "
     "hyphenated name we pass in and the cleaner deletes nothing",
     [('    return re.sub(r"[-_.]+", "_", s or "").lower()',
       '    return (s or "").lower()')]),
    ("C3", "agent/facade/selfupdate.py", "under",
     "the version is not split off, so a real dist-info name never compares "
     "equal — silently cleans nothing while reporting that it did",
     [('                    if _norm(stem.split("-", 1)[0]) == dist_norm:',
       '                    if _norm(stem) == dist_norm:')]),
    ("C4", "agent/facade/selfupdate.py", "over",
     "⛔ a PREFIX match, so the BACKEND distribution (`superresearch`) is "
     "taken by the AGENT's cleaner",
     [('                    if _norm(stem.split("-", 1)[0]) == dist_norm:',
       '                    if dist_norm.startswith(_norm(stem.split("-", 1)[0])):')]),
    ("C5", "agent/facade/selfupdate.py", "over",
     "⛔ any distribution metadata at all counts as ours — every cached tool "
     "in the shared pipx cache is deleted",
     [('                    stem = meta.name.rsplit(".", 1)[0]\n'
       '                    if _norm(stem.split("-", 1)[0]) == dist_norm:\n'
       '                        return True',
       '                    return True')]),
    ("C6", "agent/facade/selfupdate.py", "under",
     "the no-argument fallback stops naming our distribution, so an older "
     "caller's cleaner silently matches nothing",
     [('dist = sys.argv[3] if len(sys.argv) > 3 else "superresearch-agent"',
       'dist = sys.argv[3] if len(sys.argv) > 3 else ""')]),
    ("C7", "agent/facade/selfupdate.py", "under",
     "the caller stops passing the distribution name — the fallback is load "
     "bearing, and this proves a test covers it",
     [('    cmd = [py, "-c", _CACHE_CLEAR_WAITER, str(os.getpid()), cachedir, AGENT_PKG]',
       '    cmd = [py, "-c", _CACHE_CLEAR_WAITER, str(os.getpid()), cachedir, "wrong-pkg"]')]),

    # ═══════════ 7 — the durable-install ladder ═════════════════════════════
    ("P1", "agent/facade/selfupdate.py", "under",
     "⭐ the non-destructive retry is gone — the finding, restored: one rung, "
     "and a uv-backed pipx 1.15 host ends with no login pin",
     [('            u = subprocess.run([*pipx, "upgrade", AGENT_PKG],\n'
       '                               capture_output=True, text=True, timeout=600)\n'
       '            upgraded = u.returncode == 0',
       '            upgraded = False')]),
    ("P2", "agent/facade/selfupdate.py", "over",
     "⛔ the upgrade's exit code is trusted without the durability check — a "
     "pipx 0 is not a post-condition, and the caller pins the cache path",
     [('        if upgraded and autostart.pin_target_is_durable():',
       '        if upgraded:')]),
    ("P3", "agent/facade/selfupdate.py", "over",
     "⛔ the retry runs on the HAPPY path too, adding a minutes-long pipx "
     "round-trip to every healthy bootstrap",
     [("    if reason:\n"
       "        # ── Rung 2: a NON-DESTRUCTIVE retry", "    if True:\n"
       "        # ── Rung 2: a NON-DESTRUCTIVE retry")]),
    ("P4", "agent/facade/selfupdate.py", "over",
     "⛔ THE FLOOR BECOMES A BLOCK — hosts on an older pipx with the pip "
     "backend install fine today and would be refused",
     [('    try:\n'
       '        r = subprocess.run([*pipx, "install", "--force", _agent_floor_spec()],',
       '    if _pipx_version(pipx) and version_gt(PIPX_MIN_FOR_FORCE, _pipx_version(pipx)):\n'
       '        return False, "pipx is too old"\n'
       '    try:\n'
       '        r = subprocess.run([*pipx, "install", "--force", _agent_floor_spec()],')]),
    ("P5", "agent/facade/selfupdate.py", "over",
     "⛔ the version note is stapled to every failure, so an unrelated index "
     "error is reported as an old pipx",
     [("    v = _pipx_version(pipx)\n"
       "    if not v or not version_gt(PIPX_MIN_FOR_FORCE, v):\n"
       "        return reason",
       "    v = _pipx_version(pipx) or '?'\n"
       "    if False:\n"
       "        return reason")]),
    ("P6", "agent/facade/selfupdate.py", "under",
     "the version probe accepts any first token, so unparseable output ranks "
     "below every release and manufactures a diagnosis",
     [('    for tok in (r.stdout or "").split():\n'
       '        if tok[:1].isdigit():\n'
       '            return tok\n'
       '    return ""',
       '    parts = (r.stdout or "").split()\n'
       '    return parts[0] if parts else ""')]),
    ("P7", "agent/facade/selfupdate.py", "under",
     "pipx's own reason is dropped from the failure, leaving only our note",
     [('        return False, _with_pipx_note(pipx, reason)',
       '        return False, _with_pipx_note(pipx, "install failed")')]),
    ("P8", "agent/facade/selfupdate.py", "over",
     "⛔ THE UNINSTALL LADDER IS BACK — the order that can leave the host with "
     "no agent, and the finding the previous round closed",
     [('            u = subprocess.run([*pipx, "upgrade", AGENT_PKG],',
       '            subprocess.run([*pipx, "uninstall", AGENT_PKG],\n'
       '                           capture_output=True, text=True, timeout=600)\n'
       '            u = subprocess.run([*pipx, "install", AGENT_PKG],')]),

    # ═══════════ 8 — the waiter's padded version compare ════════════════════
    ("V1", "agent/facade/selfupdate.py", "under",
     "⭐ the unpadded compare is back — 0.2 vs floor 0.2.0 sends a good "
     "install to the destructive branch",
     [("    return not (v and floor) or _ver_ge(v, floor)",
       "    return not (v and floor) or _ver(v) >= _ver(floor)")]),
    ("V2", "agent/facade/selfupdate.py", "over",
     "⛔ the comparator always says yes — usable_install() stops being a "
     "post-condition at all",
     [("    x, y = _ver(a), _ver(b)\n"
       "    n = max(len(x), len(y))\n"
       "    return x + (0,) * (n - len(x)) >= y + (0,) * (n - len(y))",
       "    return True")]),
    # ⚠ This slot originally held "pad only the left side", which is an
    # EQUIVALENT mutant and cannot be killed by anything: when the left is
    # padded to the longer length, a shorter right compares identically padded
    # or not — tuple comparison already treats the longer equal-prefix side as
    # greater. It survived, and it was my error rather than a coverage gap.
    # Replaced with the half-applied fix that IS observable: the padding is
    # computed and then not used.
    ("V3", "agent/facade/selfupdate.py", "under",
     "the padding is computed and then never applied — the shape a fix takes "
     "when it is edited back out one line at a time",
     [("    return x + (0,) * (n - len(x)) >= y + (0,) * (n - len(y))",
       "    return x >= y")]),

    # ═══════════ 10 — one generationConfig, with an opt-out ═════════════════
    ("G1", "models.py", "under",
     "the shared builder stops reading the env var, so the opt-in lever is "
     "silently dead for the callers that want it",
     [('    if thinking_budget_env:\n'
       '        _tb = os.environ.get("DG_GEMINI_THINKING_BUDGET", "").strip()',
       '    if False:\n'
       '        _tb = os.environ.get("DG_GEMINI_THINKING_BUDGET", "").strip()')]),
    ("G2", "models.py", "over",
     "⛔ THE NAIVE CONSOLIDATION — the opt-out is ignored, so narrate's "
     "deliberate refusal is handed to an env var and a responseSchema can "
     "truncate mid-field",
     [("    if thinking_budget_env:", "    if True:")]),
    ("G3", "models.py", "over",
     "⛔ the thinking-disable field comes back by default — the HTTP 400 "
     "INVALID_ARGUMENT this whole builder exists to have removed",
     [('    cfg = {"temperature": temperature, "maxOutputTokens": int(max_tokens)}',
       '    cfg = {"temperature": temperature, "maxOutputTokens": int(max_tokens),\n'
       '           "thinkingConfig": {"thinkingBudget": 0}}')]),
    ("G4", "narrate.py", "under",
     "the panel narrator's ceiling drops back to 600 — sized for a request "
     "that disabled thinking; with thinking on the JSON truncates mid-field",
     [("            max_tokens=1400,", "            max_tokens=600,")]),
    ("G5", "narrate.py", "under",
     "the responseSchema stops being sent, so the structured contract the "
     "opt-out protects is gone and the flag guards nothing",
     [("            responseSchema=_RESPONSE_SCHEMA,", "")]),
    ("G6", "research.py", "under",
     "research keeps its own body again instead of delegating — two builders "
     "that agree today is the starting condition of this finding",
     [("    return _models_gemini_gen_config(\n"
       "        temperature=temperature, max_tokens=max_tokens, **extra)",
       '    cfg = {"temperature": temperature, "maxOutputTokens": int(max_tokens)}\n'
       '    _tb = os.environ.get("DG_GEMINI_THINKING_BUDGET", "").strip()\n'
       "    if _tb:\n"
       "        try:\n"
       '            cfg["thinkingConfig"] = {"thinkingBudget": int(_tb)}\n'
       "        except ValueError:\n"
       "            pass\n"
       "    cfg.update(extra)\n"
       "    return cfg")]),

    # ═══════════ 12 — the wheel can reach the key resolvers ═════════════════
    ("K1", "models.py", "under",
     "⭐ the compiled core name is dropped — the finding, restored: in the "
     "wheel the lookup fails and the app's key becomes unreachable",
     [('CORE_MODULE_NAMES = ("research", "_sr_core")',
       'CORE_MODULE_NAMES = ("research",)')]),
    ("K2", "models.py", "under",
     "the real-import fallback is gone, so a standalone caller with nothing "
     "loaded yet gets nothing",
     [("    for mod_name in CORE_MODULE_NAMES:\n"
       "        try:\n"
       "            fn = getattr(importlib.import_module(mod_name), name, None)\n"
       "        except Exception:\n"
       "            continue\n"
       "        if fn is not None:\n"
       "            return fn\n"
       "    return None",
       "    return None")]),
    ("K3", "models.py", "over",
     "⛔ a missing name returns a truthy stub, so every caller's `is not None` "
     "check passes and the fallback key sources are skipped",
     [("    return None\n\n\ndef gemini_gen_config",
       "    return lambda *a, **k: None\n\n\ndef gemini_gen_config")]),
    ("K4", "models.py", "under",
     "the sys.modules leg raises out of a best-effort lookup — a half-"
     "initialised module takes the caller's remaining key sources with it",
     [("        try:\n"
       "            # ⚠ `getattr` is not safe by itself here. A module caught PARTWAY",
       "        if True:\n"
       "            # ⚠ `getattr` is not safe by itself here. A module caught PARTWAY")]),
    ("K5", "vision.py", "under",
     "vision goes back to importing from `research` — the exact line that "
     "raises in every shipped wheel and is swallowed",
     [("                _resolve_api_key = core_attr(\"resolve_api_key\")\n"
       "                if _resolve_api_key is not None:\n"
       "                    key = _resolve_api_key()",
       "                from research import resolve_api_key as _resolve_api_key\n"
       "                key = _resolve_api_key()")]),
    ("K6", "vision.py", "over",
     "⛔ the machine-env last resort is deleted — a standalone caller with a "
     "perfectly good ANTHROPIC_API_KEY now raises instead of running",
     [('            key = os.environ.get("ANTHROPIC_API_KEY")', "            pass")]),
    ("K7", "narrate.py", "under",
     "narrate goes back to importing from `research` — the twin defect, on "
     "the Gemini key",
     [('        _resolve = core_attr("resolve_gemini_api_key")\n'
       '        api_key = (_resolve() or "") if _resolve else ""',
       "        from research import resolve_gemini_api_key as _resolve\n"
       '        api_key = _resolve() or ""')]),

    # ═══════════ the 2026-08-14 cross-check over both waves ═════════════════
    ("F1", "models.py", "over",
     "⛔⭐ THE FAMILY-FIRST EXEMPTION IS BACK — measured to re-open the blocking "
     "finding: a sales row naming the family first is clicked and reported as a "
     "confirmed pick, beating the real row",
     [("    for raw in UPSELL_VERBS:\n"
       "        verb = str(raw).lower()\n"
       "        if not verb:\n"
       "            continue\n"
       "        i = t.find(verb)\n"
       "        while i != -1:\n"
       "            end = i + len(verb)",
       "    first_noun = t.find(n)\n"
       "    for raw in UPSELL_VERBS:\n"
       "        verb = str(raw).lower()\n"
       "        if not verb:\n"
       "            continue\n"
       "        i = t.find(verb)\n"
       "        while i != -1:\n"
       "            if first_noun != -1 and i > first_noun:\n"
       "                break\n"
       "            end = i + len(verb)")]),
    ("F1b", "models.py", "under",
     "'unlock' leaves the shared verb list again — 'Unlock Opus 5.2' parses a "
     "version and outranks every genuine row, using a word three other guards "
     "in research.py already treat as a sales verb",
     [('UPSELL_VERBS = ("upgrade", "subscribe", "unlock", "get", "try")',
       'UPSELL_VERBS = ("upgrade", "subscribe", "get", "try")')]),
    ("F2", "research.py", "over",
     "⛔ an update outcome that did NOTHING replaces the whole record again, so "
     "'already installed' deletes needsRestart and the Restart button vanishes "
     "while the machine serves the old build",
     [('                                         "reason": res.get("reason", "")},\n'
       "                             merge=True)",
       '                                         "reason": res.get("reason", "")})')]),
    ("F3", "research.py", "over",
     "⛔ a LAUNCHED upgrade merges too, so a stale needsRestart survives under a "
     "live update — the mirror-image bug",
     [('        _write_update_status(device_id, {"state": "started",\n'
       '                                         "current": res.get("current"),\n'
       '                                         "latest": res.get("latest"),\n'
       '                                         "reason": res.get("reason", "")})',
       '        _write_update_status(device_id, {"state": "started",\n'
       '                                         "current": res.get("current"),\n'
       '                                         "latest": res.get("latest"),\n'
       '                                         "reason": res.get("reason", "")},\n'
       "                             merge=True)")]),
    ("F4", "models.py", "under",
     "the whitespace collapse reverts to `str.split()`, so Python and the JS "
     "disagree again on the classes each calls whitespace",
     [('    t = _collapse_ws(text).lower()\n    n = _collapse_ws(noun).lower()',
       '    t = " ".join((text or "").split()).lower()\n'
       '    n = " ".join((noun or "").split()).lower()')]),
    ("F5", "research.py", "under",
     "the JS collapse reverts to its own `\\s`, so the shipped picker and the "
     "mirror disagree again on what counts as whitespace",
     # ⛔ RE-ANCHORED 08-23: this collapse now exists FOUR times — the Claude
     # picker, probe and dropdown, plus the Gemini ranker wave 6 ported it to.
     # Pinned to the PICKER by its own comment line.
     [('            // a "character-for-character port" turned out not to be one.\n'
       "            const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), n = normU(fam).toLowerCase();\n',
       '            // a "character-for-character port" turned out not to be one.\n'
       "            const normU = s => (s || '').replace(/\\\\s+/g, ' ').trim();\n"
       '            const isUpsell = (raw) => {\n'
       '                const s = normU(raw).toLowerCase(), n = normU(fam).toLowerCase();\n')]),
    ("F6", "research.py", "under",
     "⭐ the activity probe goes back to ONE attempt — a mid-run worker that "
     "blocks its loop for a moment is killed, which this repo's own 420s "
     "watchdog constant says is normal",
     [("    _activity = _probe_backend_activity_until_settled(port, settle_s)",
       "    _activity = _port_backend_activity(port)")]),
    ("F7", "research.py", "over",
     "⛔ retrying turns silence into BUSY — the wedged terminal-less orphan is "
     "never cleared and the unexplained EADDRINUSE returns",
     [("        found = _port_backend_activity(port)\n"
       "        if found is not None:\n"
       "            return found",
       "        found = _port_backend_activity(port)\n"
       "        if found is not None:\n"
       "            return found\n"
       '        return {"running": True, "pending": 0}')]),
    ("F8", "research.py", "under",
     "the retry loop runs once regardless, so the fix is present and inert",
     [("    for n in range(max(1, attempts)):", "    for n in range(1):")]),
    ("F9", "research.py", "under",
     "⭐ the popover OPENER stops excluding chips — a billing banner above the "
     "composer is pressed as the model trigger",
     [("            const openable = btns.filter(b => !isUpsell(b.textContent || ''));",
       "            const openable = btns;")]),
    ("F10", "research.py", "over",
     "⛔ the opener's filter eats the TRIGGER too — Step 1A can never open the "
     "menu, which is a total P2 outage rather than a modal",
     [("            const openable = btns.filter(b => !isUpsell(b.textContent || ''));",
       "            const openable = [];")]),
    ("F11", "tools/build_compiled.py", "under",
     "the broken diagnostic ships in the wheel again — `import research` binds "
     "the shim and it AttributeErrors on first use",
     [('                   "scripts/claude_popover_capture.py",',
       '                   ')]),
    ("F12", "agent/facade/selfupdate.py", "under",
     "a rung-1 OSError returns early again, so the non-destructive rescue is "
     "reachable only from a non-zero exit code",
     [("        r = None\n        reason = str(e)[:200] or \"pipx install raised\"",
       "        return False, _with_pipx_note(pipx, str(e))")]),
    ("F12b", "agent/facade/selfupdate.py", "over",
     "⛔ a TIMEOUT falls through to the retry, so a second pipx mutates the venv "
     "while the orphaned pip grandchild of the first may still be writing to it",
     [('        return False, _with_pipx_note(pipx, str(e)[:200] or "pipx install timed out")',
       '        r = None\n        reason = str(e)[:200] or "pipx install timed out"')]),
    ("F13", "narrate.py", "under",
     "the panel narrator reports an empty 200 as a parse fault again, sending "
     "the next reader after the JSON decoder instead of the token budget",
     [('        if not (text or "").strip():\n'
       '            # ⭐ A 200 that carried no text is not a parse fault, and reporting it',
       '        if False:\n'
       '            # ⭐ A 200 that carried no text is not a parse fault, and reporting it')]),
]

ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

# How many times a claimed survivor must survive before it is reported as one.
# ⚠ Not optional. The dev venv holds an editable install of a DIFFERENT checkout
# of these same module names, so a test process can resolve the unmutated copy
# and record a phantom survivor. Wave 1 measured 10 of 36 mutants flapping even
# with the path pinned; this backstop is what makes the number trustworthy.
SURVIVOR_CONFIRMATIONS = 3


def sh(cmd: list[str], *, cwd=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                          env=env or ENV)


def purge_pycache() -> None:
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES,
              "tests", "agent/tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    """Both suites. The agent keeps its own pytest rootdir and imports `facade`,
    so it runs from `agent/` with that directory on the path — running it from
    the repo root collects it and then fails on the import."""
    purge_pycache()
    root_ok = sh([sys.executable, "-B", "-m", "pytest", *ROOT_SUITES.split(),
                  "-q", "-p", "no:cacheprovider"]).returncode == 0
    if not root_ok:
        return False
    agent_env = {**ENV, "PYTHONPATH": os.pathsep.join(
        [str(ROOT / "agent"), ENV["PYTHONPATH"]])}
    return sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
               "-q", "-p", "no:cacheprovider"],
              cwd=ROOT / "agent", env=agent_env).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
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
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                killed = not run_tests()
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
