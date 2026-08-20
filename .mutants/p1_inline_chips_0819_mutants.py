"""Mutation harness for P1's inline chip row — the 2026-08-19 wave.

⛔⛔ WHAT THE WAVE REPAIRED. `_chatgpt_activity_state` could not see the shape it
was asked to verify. P1's UI expands a row of website chips under the shimmering
line; the predicate looked for a side panel or a 60px-tall "thought"/"activity"
region of ≥40 characters. So an OPEN drawer read as closed, the per-cycle
re-check un-latched it 31 seconds after CUA opened it, and the opener then pressed
the toggle eight times — closing the user's UI, which CUA narrated at 03:06:40 and
03:07:05. The same phase logged ZERO `panel tracking (P1)` lines in 13.7 minutes.

⭐ HALF OF THIS SOURCE IS JAVASCRIPT, so half of these mutants are killed only by
tests that run it in a real browser. That is deliberate: the properties being
mutated (a visibility gate, a prose gate, a shimmer requiring two computed-style
terms) have no meaning outside a layout engine, and pinning them as source text
alone would let any of them be reversed by rewriting the same idea differently.
The Chrome-backed tests SKIP where Chrome is absent — so if a JS mutant below
comes back a survivor, check first whether Chrome ran at all. A skip is not a kill
and it is not a survivor; it is a harness that measured nothing.

⛔ Two mutants exist purely to pin choices a reviewer would plausibly reverse:
counting a single hostname as a row (it is ordinary prose and a lone citation),
and letting the chip row into P2's gate (which would recreate the 2026-08-06
never-clicked-the-strip regression from the other direction).

    python .mutants/p1_inline_chips_0819_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
PROMPTS = "prompts.py"
SHIM = "tests/_domshim.py"
MUTATED_FILES = [SRC, PROMPTS, SHIM]

T_NEW = "tests/test_p1_inline_chips_0819.py"
# ⛔ THE SIBLING SUITES WHOSE PROPERTIES THIS SOURCE ALSO OWNS. Three separate
# times a harness in this repo reported "real suite gaps" that were nothing but
# its own scope. `poll_until_done`, `_chatgpt_activity_state` and the CUA panel
# prompt are shared with the panel-anchor and CUA-retry waves.
T_ANCHOR = "tests/test_p1_panel_anchor_0817.py"
T_RETRY = "tests/test_panel_cua_retry_0817.py"
T_PREC = "tests/test_p1_panel_precedence_0818.py"
ALL = [T_NEW, T_ANCHOR, T_RETRY, T_PREC]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the three gates that were blind — the bug itself ══
    ("G1", SRC, "under", "⭐⭐ the per-cycle re-check goes back to the old pair, so "
     "an open chip row un-latches and the opener starts pressing again",
     [("                        if not _chatgpt_p1_activity_open(_st_now):",
       "                        if not (_st_now.get(\"side_panel\") "
       "or _st_now.get(\"inline_expanded\")):")],
     [T_NEW]),
    ("G2", SRC, "under", "⭐⭐ the anti-toggle PRE-check goes blind, so we press a "
     "drawer that is already open — which closes it",
     [("                        if _chatgpt_p1_activity_open(_st_pre):",
       "                        if _st_pre.get(\"side_panel\") "
       "or _st_pre.get(\"inline_expanded\"):")],
     [T_NEW]),
    ("G3", SRC, "under", "⭐⭐ the post-press verify goes blind, so a successful "
     "press is recorded as a miss and escalates to CUA",
     [("                            verified = _chatgpt_p1_activity_open(_st_post)",
       "                            verified = bool(_st_post.get(\"side_panel\") "
       "or _st_post.get(\"inline_expanded\"))")],
     [T_NEW]),

    # ══ the predicate itself ══
    ("P1", SRC, "over", "⛔ ONE hostname counts as open — ordinary prose and a "
     "single citation would latch the drawer shut for the rest of the phase",
     [("    return bool(st.get(\"side_panel\") or st.get(\"inline_expanded\")\n"
       "                or st.get(\"inline_chip_row\"))",
       "    return bool(st.get(\"side_panel\") or st.get(\"inline_expanded\")\n"
       "                or int(st.get(\"inline_chips\", 0) or 0) >= 1)")],
     [T_NEW]),
    ("P2", SRC, "under", "the side-panel and inline shapes stop counting, so P1 "
     "only ever recognises chips and every P2-shaped drawer is a miss",
     [("    return bool(st.get(\"side_panel\") or st.get(\"inline_expanded\")\n"
       "                or st.get(\"inline_chip_row\"))",
       "    return bool(st.get(\"inline_chip_row\"))")],
     [T_NEW]),
    ("P3", SRC, "over", "⛔ the chip row leaks into P2's round-robin gate — P2 "
     "latches 'already open' and never clicks the DR strip (2026-08-06)",
     [("                    if _st_pre.get(\"side_panel\") or _st_pre.get(\"inline_expanded\"):\n"
       "                        p[\"chatgpt_activity_panel_open\"] = True",
       "                    if _st_pre.get(\"side_panel\") or _st_pre.get(\"inline_expanded\") \\\n"
       "                            or _st_pre.get(\"inline_chip_row\"):\n"
       "                        p[\"chatgpt_activity_panel_open\"] = True")],
     [T_NEW, T_ANCHOR, T_RETRY]),
    ("P4", SRC, "over", "the shape label prefers 'chips' over a real side panel, "
     "sending the next reader to the wrong half of the walker",
     [("    if st.get(\"side_panel\"):\n        return \"side\"",
       "    if st.get(\"inline_chip_row\"):\n        return \"chips\"")],
     [T_NEW]),

    # ══ the JS chip test (browser-killed) ══
    ("J1", SRC, "over", "⛔ one chip is a row",
     [("    out.chip_row = out.chips >= 2;", "    out.chip_row = out.chips >= 1;")],
     [T_NEW]),
    ("J2", SRC, "over", "⛔ the prose gate is dropped, so the finished report's "
     "citation chips read as an open drawer FOREVER",
     [("        if (isChip && !inProse) {\n            const host = t.toLowerCase();",
       "        if (isChip) {\n            const host = t.toLowerCase();")],
     [T_NEW]),
    ("J3", SRC, "over", "⛔⛔ the visibility gate is dropped, so chips a COLLAPSED "
     "drawer keeps mounted count and the pre-check latches forever",
     # ⚠ THE ANCHOR CARRIES ITS PREVIOUS LINE. The gate alone occurs FOUR times
     # in research.py, so on the first round this mutant measured nothing and the
     # harness said so; the pair at this indentation is unique to the inline walker.
     [("        const r = el.getBoundingClientRect();\n"
       "        if (r.width === 0 || r.height === 0) continue;",
       "        const r = el.getBoundingClientRect();\n        if (false) continue;")],
     [T_NEW]),
    ("J4", SRC, "over", "⛔ the geometric pass loses its bound, so the PREVIOUS "
     "turn's chip row is read as this turn's drawer (Phase1-followup)",
     [("        if (inGeo && lub > 0 && (r.top < lub - 8 || r.top > lub + 900)) continue;",
       "        if (false) continue;")],
     [T_NEW]),
    ("J5", SRC, "under", "the geometric pass is removed, so the walk dies for the "
     "first minutes of every response — the measured 13.7 minutes of silence",
     [("    if (!out.status_line && !chipTop.size && !out.steps.length && lub > 0) {",
       "    if (false) {")],
     [T_NEW]),
    ("J6", SRC, "over", "⛔ the geometric pass runs even when the article scope "
     "worked, dragging the composer and the footer into every sample",
     [("    if (!out.status_line && !chipTop.size && !out.steps.length && lub > 0) {",
       "    if (lub > 0) {")],
     [T_NEW]),
    ("J7", SRC, "over", "⛔ the shimmer anchor accepts animation ALONE, so the "
     "animated 'Pro' badge becomes the status line",
     [("        let anim = shimmers(el), clip = clipped(el);\n        if (anim && clip) return true;",
       "        let anim = shimmers(el), clip = clipped(el);\n        if (anim) return true;")],
     [T_NEW]),
    ("J8", SRC, "under", "the shimmer term is removed from the status test, so a "
     "wordless topic-specific label is invisible again",
     [("        else if (t.length <= 240 && r.top < statusTop && shimmerLine(el)) from = 'shimmer';",
       "        else if (false) from = 'shimmer';")],
     [T_NEW]),
    ("J9", SRC, "under", "`websites`/`sites` come back out of the count regex — "
     "the exact omission that left P1 with no status line all phase",
     [("    const COUNT = /\\\\b\\\\d+\\\\s+(?:websites?|sites?|searches?|sources?|results?|citations?)\\\\b/i;",
       "    const COUNT = /\\\\b\\\\d+\\\\s+(?:searches?|sources?|results?|citations?)\\\\b/i;")],
     [T_NEW]),
    ("J10", SRC, "under", "`progress` goes back to the last row, so the narration "
     "line becomes a bare hostname",
     [("    out.progress = out.status_line || lastVerbStep || lastStep;",
       "    out.progress = out.status_line || lastStep;")],
     [T_NEW]),
    ("J11", SRC, "over", "the `expanded` selector is widened to every element, so "
     "the chip row sets the SHARED predicate and P2 latches on it",
     [("            '[class*=\"thought\" i], [class*=\"activity\" i], [data-testid*=\"thought\" i]')) {",
       "            '*')) {")],
     [T_NEW, T_ANCHOR, T_RETRY]),
    ("J12", SRC, "over", "the prose-chip diagnostic counts per element again, so "
     "three citations report as six and the next reader hunts a phantom",
     [("            proseChips.add(t.toLowerCase());",
       "            out.dbg.chipsProse += 1;")],
     [T_NEW]),
    ("J13", SRC, "over", "the hostname test loses its end anchor, so any leaf "
     "whose text merely STARTS with a domain is a chip",
     [("    const HOSTCHIP = /^[a-z0-9][a-z0-9.-]{2,60}\\\\.[a-z]{2,10}$/i;",
       "    const HOSTCHIP = /^[a-z0-9][a-z0-9.-]{2,60}\\\\.[a-z]{2,10}/i;")],
     [T_NEW]),

    # ══ chips → sources ══
    ("S1", SRC, "under", "⭐ the chips are never folded into the source list, so "
     "the owner's ask — stream those links — is not delivered at all",
     [("            _merge_host_chips(res, il.get(\"source_hosts\") or [])",
       "            pass")],
     [T_NEW]),
    ("S2", SRC, "over", "the Python side trusts the JS shape test, so an 'N more' "
     "affordance becomes the clickable URL `https://13 more/`",
     [("        if not h or not _HOST_CHIP_RE.match(h) or h in have:",
       "        if not h or h in have:")],
     [T_NEW]),
    ("S3", SRC, "over", "a host that already has a real page gets a bare twin — "
     "one source listed twice under a count the owner compares with ChatGPT's",
     [("        if not h or not _HOST_CHIP_RE.match(h) or h in have:",
       "        if not h or not _HOST_CHIP_RE.match(h):")],
     [T_NEW]),
    ("S4", SRC, "under", "a chips-only sample is thrown away — and that is the one "
     "sample that proves the drawer open before any verb row has streamed",
     [("                   or int(il.get(\"chips\", 0) or 0)):",
       "                   ):")],
     [T_NEW]),

    # ══ …and the arrival-order half ══
    ("D1", SRC, "under", "placeholders are never pruned, so the chip and the page "
     "for one host both survive to the end of the run",
     [("                            progress[\"source_urls\"], progress[\"source_items\"] = (\n"
       "                                _drop_covered_host_placeholders(\n"
       "                                    progress.get(\"source_urls\") or [],\n"
       "                                    progress.get(\"source_items\") or [],\n"
       "                                    progress[\"chip_hosts\"]))",
       "                            pass")],
     [T_NEW]),
    ("D2", SRC, "over", "⛔ EVERY bare domain is dropped, which deletes the chip "
     "row outright on a P1 run where a domain is the only address there is",
     [("    real = {_host_of(u) for u in urls if not _is_bare(u)}",
       "    real = {_host_of(u) for u in urls}")],
     [T_NEW]),
    ("D3", SRC, "over", "the pruned list is sorted, so `progress` and every "
     "trailing slice stop meaning 'newest'",
     [("    keep = [u for u in urls\n"
       "            if not (_is_bare(u) and _host_of(u) in chips and _host_of(u) in real)]",
       "    keep = sorted(u for u in urls\n"
       "                  if not (_is_bare(u) and _host_of(u) in chips and _host_of(u) in real))")],
     [T_NEW]),
    ("D4", SRC, "over", "a query-only URL is treated as a placeholder, so a real "
     "page is dropped in favour of the bare domain",
     [("        return bool(re.match(r\"^https?://[^/?#]+/?$\", str(u or \"\"), re.I))\n\n"
       "    real = {_host_of(u) for u in urls if not _is_bare(u)}",
       "        return bool(re.match(r\"^https?://[^/?#]+\", str(u or \"\"), re.I))\n\n"
       "    real = {_host_of(u) for u in urls if not _is_bare(u)}")],
     [T_NEW]),
    ("D5", SRC, "over", "the source count is left as it was before the prune, so "
     "the number reported is of a list that no longer exists",
     [("                            progress[\"sources\"] = len(progress.get(\"source_urls\", []) or [])\n"
       "                            _ps = int(_pd.get(\"searches\", 0) or 0)",
       "                            _ps = int(_pd.get(\"searches\", 0) or 0)")],
     [T_NEW]),

    # ══ the diagnostics — informative without becoming yesterday's flood ══
    ("L1", SRC, "over", "⛔⛔ the inline diagnostic loses its signature gate and "
     "fires on every poll — yesterday's 412 identical DEBUG lines, again",
     [("            if _sig != _p1_inline_dbg_sig:", "            if True:")],
     [T_NEW]),
    ("L2", SRC, "under", "the miss line stops reporting the chip delta, so 'no "
     "shape verified' cannot be told from 'we just closed it'",
     [("                                    f\"chips {_cb}->{_ca}\"", "                                    f\"\"")],
     [T_NEW]),

    # ══ what the vision tier is told ══
    ("V1", SRC, "over", "⛔⛔ 7c-p1's success signals demand a right-side panel "
     "again, so every correct CUA attempt is scored a failure",
     [("        \"success_signals\": [\"a row of website chips (favicon + domain) directly under the activity line\",\n"
       "                            \"an inline expansion below the clicked line, not a side panel\"],",
       "        \"success_signals\": [\"a side panel on the RIGHT (~30-40% width)\",\n"
       "                            \"a numbered/bulleted step list with source URL rows\"],")],
     [T_NEW]),
    ("V2", SRC, "over", "7c-p1's hint tells the model to expect an ellipsis, which "
     "not one label of the measured phase had",
     [("            \"TOPIC-SPECIFIC and changes every few seconds, so use the shimmer, not the words, \"\n"
       "            \"and do not expect a trailing '...'. Click that line once; it is a TOGGLE. It is \"",
       "            \"TOPIC-SPECIFIC and changes every few seconds. Click that line once; it is a TOGGLE. It is \"")],
     [T_NEW]),
    ("V3", SRC, "under", "the P1 CUA brief goes back to promising an 'Activity · "
     "<seconds>' panel — an instruction to keep clicking",
     [("                                    \"result: a row of small website chips (favicon + \"",
       "                                    \"result: a NARROW 'Activity · <seconds>' panel on the \"")],
     [T_NEW]),
    ("V4", SRC, "over", "⛔ the ELLIPSIS anchor is deleted from the OPENER, taking "
     "P2's working leg with it — the same run opened its strip off 'Researching...'",
     [("        const ELLIPSIS = /(?:\\\\.{3}|\\\\u2026)\\\\s*$/;\n",
       "")],
     [T_NEW, T_ANCHOR]),
    ("V5", PROMPTS, "over", "the shared prompt re-asserts the ellipsis as an "
     "invariant, which is measured false for P1",
     [("- THE SHIMMER IS THE ANCHOR.",
       "- The live activity line ALWAYS ends with three dots / ellipsis (\"...\").\n"
       "- THE SHIMMER IS THE ANCHOR.")],
     [T_NEW]),
    ("V6", PROMPTS, "under", "the look-before-you-click rule for the chip row is "
     "removed, so CUA closes the drawer it was sent to open",
     [("- IN PRO / EXTENDED THINKING (P1) ONLY — when your task names that mode:\n"
       "  if a row of website chips (favicon + domain, possibly with an \"N more\"\n"
       "  chip) is ALREADY showing under the activity line, it is already open.\n"
       "  Output exactly: \"panel: already_open\". DO NOT CLICK.",
       "- (the chip row is not consulted)")],
     [T_NEW]),
    ("V7", PROMPTS, "over", "the restore clause is dropped while the hard "
     "constraint still allows a second click — a contradiction, and the drawer is "
     "left closed",
     [("- If the chips or a panel DISAPPEARED because of your click, you closed\n"
       "  what was already open: click the SAME line once more to restore it, then\n"
       "  output \"panel: open\". Do not leave it closed, and do not click a third\n"
       "  time.\n", "")],
     [T_NEW]),

    ("V8", PROMPTS, "over", "⛔ the chip clause loses its P1 scoping, so a Deep "
     "Research turn that shows chips reports already_open and P2 never opens the "
     "side panel its walker reads",
     [("  IN DEEP RESEARCH (P2), chips alone are NOT enough: that mode is read\n"
       "  from the right-side panel, so keep looking for the panel and treat a\n"
       "  chip row as \"not open yet\".\n", "")],
     [T_NEW]),

    ("J14", SRC, "over", "⛔ the expensive shimmer walk loses its can-it-matter "
     "gate, so every candidate resolves computed style for its whole subtree",
     [("        else if (t.length <= 240 && r.top < statusTop && shimmerLine(el)) from = 'shimmer';",
       "        else if (t.length <= 240 && shimmerLine(el)) from = 'shimmer';")],
     [T_NEW]),
    ("J15", SRC, "over", "the chip COUNT is capped with the list, so a 70-chip row "
     "reports 60 in the log the callers latch on",
     [("    out.chips = chipTop.size;", "    out.chips = out.source_hosts.length;")],
     [T_NEW]),
    ("J16", SRC, "over", "the status diagnostic is derived after the fact again, so "
     "it misattributes a line that two terms could accept",
     [("        if (from && r.top < statusTop) {", "        if (from) {")],
     [T_NEW]),
    ("S5", SRC, "under", "⭐⭐ the chips never reach the EXTRACTED result, so the "
     "live activity popup shows eight domains all phase and the final payload "
     "drops every one — two views of one run disagreeing",
     [("                if il.get(\"source_hosts\"):\n"
       "                    _pre_n = len(result.get(\"source_urls\") or [])",
       "                if False:\n"
       "                    _pre_n = len(result.get(\"source_urls\") or [])")],
     [T_NEW]),
    # ⛔⛔ S6 RETIRED, AND ITS SURVIVAL IS WHY. It mutated a prune call at extraction
    # time; the call could not fire there (`_merge_host_chips` never adds a
    # placeholder for a covered host, and that dict is rebuilt from the host scrape
    # on every call, so no earlier poll exists for one to arrive on). Chasing the
    # survivor with a test would have been pinning a guard that cannot fire — in the
    # wave whose whole subject is a guard that cannot fire. The call was DELETED
    # instead, and what it was reaching for is covered by S7/S8 below.
    ("S7", SRC, "over", "⛔⛔ the prune goes back to judging by SHAPE, so a genuine "
     "citation of a project's home page is deleted the moment any deeper page on "
     "that host arrives — a real source, silently gone",
     [("    keep = [u for u in urls\n"
       "            if not (_is_bare(u) and _host_of(u) in chips and _host_of(u) in real)]",
       "    keep = [u for u in urls\n"
       "            if not (_is_bare(u) and _host_of(u) in real)]")],
     [T_NEW]),
    ("S8", SRC, "under", "the merge stops recording which hosts it invented an "
     "address for, so nothing is ever prunable and one source is listed twice",
     [("    if added_hosts:\n"
       "        res[\"chip_hosts\"] = sorted(set(res.get(\"chip_hosts\") or []) | added_hosts)",
       "    if False:\n"
       "        res[\"chip_hosts\"] = sorted(set(res.get(\"chip_hosts\") or []) | added_hosts)")],
     [T_NEW]),
    ("S9", SRC, "under", "the accumulated chip-host set is replaced by only this "
     "poll's, so a host chipped at minute two is unprunable at minute nine",
     [("                            progress[\"chip_hosts\"] = sorted(\n"
       "                                set(progress.get(\"chip_hosts\") or [])\n"
       "                                | set(_pd.get(\"chip_hosts\") or []))",
       "                            progress[\"chip_hosts\"] = sorted(\n"
       "                                set(_pd.get(\"chip_hosts\") or []))")],
     [T_NEW]),
    ("S10", SRC, "over", "the provenance match stops normalising, so a host that "
     "arrives as `GitHub.com.` is quietly unprunable",
     [("    chips = {str(h or \"\").strip().lower().rstrip(\".\") for h in (chip_hosts or [])}",
       "    chips = {str(h or \"\") for h in (chip_hosts or [])}")],
     [T_NEW]),

    # ══ the ONE shared definition of "shimmering" ══
    ("H1", SRC, "over", "⛔ the shared constant is emptied, so all three walkers "
     "call an undefined `shimmers` — and the duplication that used to mask that is "
     "gone, which is the point of sharing it",
     [("_CHATGPT_SHIMMER_JS_HELPERS = \"\"\"\n    const shimmers = (n) => {",
       "_CHATGPT_SHIMMER_JS_HELPERS = \"\"\"\n    const _unused = (n) => {")],
     [T_NEW, T_PREC]),
    ("H2", SRC, "over", "⛔ a PAUSED animation counts as shimmering again — a "
     "stopped row still has an animation name",
     [("                && cs.animationPlayState !== 'paused';",
       "                ;")],
     [T_NEW, T_PREC]),
    ("H3", SRC, "over", "`clipped` answers yes for everything, so the animated "
     "'Pro' badge satisfies both halves and becomes the status line",
     [("            return cs.webkitBackgroundClip === 'text'\n                || cs.backgroundClip === 'text';",
       "            return true;")],
     [T_NEW, T_PREC]),

    # ══ the shim that runs the page JS — its failure mode is measuring NOTHING ══
    ("H4", SHIM, "over", "⛔⛔ the fold returns a stub instead of raising, so a "
     "constant it cannot resolve hands node an EMPTY program and every test that "
     "fed it passes having executed nothing",
     [("        raise AssertionError(\n"
       "            f\"{name} in {getattr(fn, '__name__', fn)} is assigned something this \"",
       "        return \"\"\n        raise AssertionError(\n"
       "            f\"{name} in {getattr(fn, '__name__', fn)} is assigned something this \"")],
     [T_NEW]),
    ("H5", SHIM, "under", "the fold stops resolving a shared module constant, so "
     "every walker that splices one becomes untestable",
     [("        if isinstance(node, ast.Name):", "        if False:")],
     [T_NEW, T_ANCHOR]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def skipped(tests: list[str]) -> int:
    """How many tests SKIPPED on the clean tree.

    ⛔ A harness whose JS mutants are killed only in a browser has to know whether
    the browser was there. On a machine without Chrome every J-mutant would come
    back a survivor and the report would read as a suite gap.
    """
    out = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                          "-rs", *tests], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                         timeout=_TEST_TIMEOUT_S).stdout
    for line in out.splitlines():
        if " skipped" in line and ("passed" in line or "=" in line):
            for part in line.replace("=", " ").split(","):
                if "skipped" in part:
                    for tok in part.split():
                        if tok.isdigit():
                            return int(tok)
    return 0


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
        print(f"{'TIMED OUT' if timed_out else 'RED'}. "
              f"Nothing below would mean anything.")
        return 2
    n_skipped = skipped([T_NEW])
    print(f"green ({n_skipped} skipped)", flush=True)
    if n_skipped:
        print(f"⚠ {n_skipped} test(s) SKIPPED — if Chrome is unavailable, every J* "
              f"mutant below measures NOTHING. Fix that before reading the report.")

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, path, direction, why, edits, tests in MUTANTS:
        target = ROOT / path
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor — mutates nothing: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:60]}")
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

    over = sum(1 for m in MUTANTS if m[2] == "over")
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
