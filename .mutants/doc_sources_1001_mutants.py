"""Mutation harness for 2026-10-01: ChatGPT's and Gemini's documents end with
the sites they visited, public pages only.

Each mutant takes back one piece of the change, or one protection around it —
the privacy gate's rules, the one-list rules, the one-section rule (a report's
own link-less trailing section is replaced, R1-R9), the field the web numbers
from — and the tests in `tests/test_doc_visited_sources_1001.py` (plus the two pins
that moved) must go red for every one.

Safety, as the other harnesses here: refuses to start on a dirty tree, holds the
original in memory, restores in `finally`, re-checks `git status` at the end.

    .venv/bin/python .mutants/doc_sources_1001_mutants.py
    ONLY=G5,S3 .venv/bin/python .mutants/doc_sources_1001_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = [
    "tests/test_doc_visited_sources_1001.py",
    "tests/test_numbered_sources_0918.py",
    "tests/test_chatgpt_row_scope_0805.py::"
    "test_EVERY_writer_of_an_agent_md_is_covered_by_one_guard_or_the_other",
]

MUTANTS = [
    # ── the write sites and the run's own list ─────────────────────────────
    ("B1", "the per-agent write stops passing the visited sites",
     [("                visited=_p2_visited_sources(agent_key), label=name)",
       "                visited=None, label=name)")]),
    ("B2", "the finalize re-save stops passing the visited sites",
     [("                visited=_p2_visited_sources(_agent_lc), label=name)",
       "                visited=None, label=name)")]),
    ("B3", "the regenerated report stops passing the visited sites",
     [("        visited=_p2_visited_sources(key), label=name)",
       "        visited=None, label=name)")]),
    ("B4", "the poll loop stops folding each tick into the run's list",
     [("                    _p2_fold_visited_sources(agent_key, progress)\n",
       "                    pass\n")]),
    ("B5", "the run's list is replaced every tick instead of growing",
     [("    store[agent_key] = _doc_fold_sources(\n        store.get(agent_key),",
       "    store[agent_key] = _doc_fold_sources(\n        [],")]),
    ("B6", "the latest snapshot is no longer read at the write",
     [('    return _doc_fold_sources(\n        rows, list(snap.get("source_urls") or [])',
       "    return _doc_fold_sources(\n        rows, list([])")]),
    ("B7", "a regen re-save in run_pipeline skips the helper",
     [('                        _regen_md = _p2_regenerated_document(name, r["text"], "retry")',
       '                        _regen_md = r["text"]')]),
    ("B8", "the per-agent writer loses its topic guard",
     [('    text = reject_off_topic_text(text, queue_dir, name, agent_key,\n'
       '                                 op="finalize_topic_guard")',
       "    text = text")]),

    # ── one list, never two ────────────────────────────────────────────────
    ("L1", "a report's own titles-only list blocks the visited sites again",
     [("    if visited and not own_links:", "    if visited and own_at is None:")]),
    ("L2", "the visited sites follow a report's own list that holds links",
     [("    if visited and not own_links:", "    if visited:")]),
    ("L3", "the visited sites are added however many sources the report cites",
     [("        if cited < _DOC_VISITED_MIN_CITED:", "        if True:")]),
    ("L4", "a document already ending with our list is numbered again",
     [("    if _DOC_SOURCE_MARK_RE.search(md) or _DOC_VISITED_BLOCK_RE.search(md):",
       "    if _DOC_SOURCE_MARK_RE.search(md):")]),
    ("L5", "our list is recognised only under its first title",
     [("    r'\\n\\n%s[ \\t]+(?:%s|%s)[ \\t]*\\n\\n(?:\\d{1,3}\\. \\[.*\\n?)+\\Z'\n"
       '    % ("#" * _DOC_SOURCES_HEADING_LEVEL,\n'
       "       re.escape(_DOC_SOURCES_ALT_TITLE), re.escape(_DOC_SOURCES_TITLE)))",
       "    r'\\n\\n%s[ \\t]+(?:%s|%s)[ \\t]*\\n\\n(?:\\d{1,3}\\. \\[.*\\n?)+\\Z'\n"
       '    % ("#" * _DOC_SOURCES_HEADING_LEVEL,\n'
       "       re.escape(_DOC_SOURCES_TITLE), re.escape(_DOC_SOURCES_TITLE)))")]),

    # ── exactly one sources section (owner, 2026-10-01) ────────────────────
    ("R1", "keep-the-old-block: a link-less own section stays above our list",
     [("    cut = len(md[:own_at].rstrip()) if extra and own_at is not None else None",
       "    cut = None")]),
    ("R2", "require-a-heading-only: no paragraph lead opens the own section",
     [('    return _doc_own_sources_lead(masked or "", last.end() if last is not None else 0)',
       "    return None")]),
    ("R3", "ignore-bold-led: a **Title** lead is not read",
     [("    m = _DOC_BOLD_LEAD_RE.match(line)\n    if m:",
       "    m = None\n    if m:")]),
    ("R4", "replace-even-when-linked: an own section with public links is replaced too",
     [("    own_links = own_at is not None and bool(_doc_cited_public_keys(masked[own_at:]))",
       "    own_links = False")]),
    ("R5", "a plain Title: lead is not read",
     [("    m = _DOC_PLAIN_LEAD_RE.match(line)\n", "    m = None\n")]),
    ("R6", "a lead is looked for from the top, not after the last heading",
     [('    return _doc_own_sources_lead(masked or "", last.end() if last is not None else 0)',
       '    return _doc_own_sources_lead(masked or "", 0)')]),
    ("R7", "the word set is open-ended: any title STARTING with the word fits",
     [("    r'[ \\t]*[.:]?[ \\t]*\\Z', re.IGNORECASE)",
       "    r'[ \\t]*[.:]?', re.IGNORECASE)")]),
    ("R8", "any link, private ones included, keeps the own section",
     [("    own_links = own_at is not None and bool(_doc_cited_public_keys(masked[own_at:]))",
       "    own_links = own_at is not None and bool(_FIND_BARE_URL_RE.search(masked[own_at:]))")]),
    ("R9", "a lead counts on any line, not only a paragraph's first",
     [("        if not blank and prev_blank and _doc_lead_is_sources(line):",
       "        if not blank and _doc_lead_is_sources(line):")]),

    # ── the field the web numbers from ─────────────────────────────────────
    ("S1", "save_meta reads the visited rows only when the document has no marker",
     [("            urls += _doc_listed_visited_sources(_raw_doc, content)\n",
       "            urls += (_doc_listed_visited_sources(_raw_doc, content)\n"
       "                     if not _DOC_SOURCE_MARK_RE.search(_raw_doc) else [])\n")]),
    ("S2", "save_meta stops reading the visited rows",
     [("            urls += _doc_listed_visited_sources(_raw_doc, content)\n", "")]),
    ("S3", "save_meta keeps the %28/%29 spelling beside the plain one",
     [("                _u = _doc_plain_parens(_u)\n", "")]),
    ("S4", "save_meta reads the first address in a row, link text included",
     [(r"    r'^(\d{1,3})\. \[(?:\\.|[^\]\\])*\]\((https?://[^()\s]+)\)', re.MULTILINE)",
       r"    r'^(\d{1,3})\. .*?(https?://[^()\s\]]+)', re.MULTILINE)")]),
    ("S5", "save_meta adds the panel's sites without the public-page gate",
     [("                _panel_urls = _doc_fold_sources([], [",
       "                _panel_urls = (lambda _x, l: list(l))([], [")]),

    # ── the public-page gate ───────────────────────────────────────────────
    ("G1", "the document scrub's private-link test is not asked",
     [('    if _doc_link_is_private(t):\n        return ""\n    try:\n',
       "    try:\n")]),
    ("G2", "a host whose last label is a number passes",
     [('        if last_label.isdigit() or last_label.startswith("0x"):\n            return ""',
       '        if False:\n            return ""')]),
    ("G3", "an in-house name (.corp) passes",
     [('    ".localhost", ".local", ".internal", ".lan", ".home.arpa", ".home", ".corp",',
       '    ".localhost", ".local", ".internal", ".lan", ".home.arpa", ".home",')]),
    ("G4", "a Dropbox link key is not a secret",
     [("    r'|ticket|client_secret|rlkey)$', re.IGNORECASE)",
       "    r'|ticket|client_secret)$', re.IGNORECASE)")]),
    ("G5", "an account settings page passes",
     [('    "sign-up", "sso", "authorize", "settings", "account", "billing", "api-keys"})',
       '    "sign-up", "sso", "authorize", "account", "billing", "api-keys"})')]),
    ("G6", "a consent page passes",
     [('    "login", "signin", "accounts", "auth", "sso", "consent"})',
       '    "login", "signin", "accounts", "auth", "sso"})')]),
    ("G7", "Google's account, workspace and console pages pass",
     [('    # Google account, workspace and console pages\n'
       '    "chat.google.com", "script.google.com", "myactivity.google.com",\n'
       '    "takeout.google.com", "passwords.google.com", "payments.google.com",\n'
       '    "pay.google.com", "admin.google.com", "one.google.com", "meet.google.com",\n'
       '    "console.cloud.google.com", "console.firebase.google.com",\n'
       '    "lookerstudio.google.com", "datastudio.google.com", "analytics.google.com",\n'
       '    "aistudio.google.com",\n', "")]),
    ("G8", "the platforms' user-content and download hosts pass",
     [("    # the platforms' user-content and download hosts\n"
       '    "usercontent.google.com", "usercontent.goog", "claude.site",\n'
       '    "claudeusercontent.com",\n', "")]),
    ("G9", "mail, workspace and file apps pass",
     [('    # other mail, workspace and file apps\n'
       '    "mail.yahoo.com", "mail.proton.me", "atlassian.net", "slack.com",\n'
       '    "notion.so", "linear.app", "app.hubspot.com", "app.box.com",\n'
       '    "teams.microsoft.com", "teams.live.com", "app.asana.com")', ")")]),
    ("G10", "a wrapper around a private page passes",
     [("            if not _doc_public_source_url(re.sub(r'^(https?:/)(?!/)', r'\\1/', i)):\n"
       '                return ""',
       "            if False:\n"
       '                return ""')]),
    ("G11", "tracking tags stay on a listed address",
     [("            if _DOC_TRACKING_PARAM_RE.match(key):\n                continue",
       "            if False:\n                continue")]),
    ("G12", "a Google redirect is not followed",
     [("        target = _doc_unwrap_redirect(t)\n        if not target:\n            break",
       '        target = ""\n        if not target:\n            break')]),
    ("G13", "an address carrying a session or secret key passes",
     [("            if _DOC_SECRET_PARAM_RE.match(key) or _DOC_JWT_VALUE_RE.search(value):",
       "            if _DOC_JWT_VALUE_RE.search(value):")]),
    ("G14", "a search engine's own pages pass",
     [('        if _DOC_SEARCH_HOST_RE.match(bare):\n            return ""',
       '        if False:\n            return ""')]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES, "-q", "-x",
               "-p", "no:cacheprovider"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    path = ROOT / RESEARCH
    original = path.read_text(encoding="utf-8")
    for mid, _why, edits in MUTANTS:
        for frm, _to in edits:
            if original.count(frm) != 1:
                print(f"! ANCHOR {mid} found {original.count(frm)} times: {frm[:70]!r}")
                return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    only = [m for m in os.environ.get("ONLY", "").split(",") if m]
    run = [m for m in MUTANTS if not only or m[0] in only]
    if only and len(run) != len(only):
        print(f"ONLY names {len(only)} mutant(s) and {len(run)} exist")
        return 2
    survivors = []
    try:
        for mid, why, edits in run:
            mutated = original
            for frm, to in edits:
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'killed  ' if killed else 'SURVIVED'} {mid} {why}", flush=True)
            if not killed:
                survivors.append((mid, why))
            path.write_text(original, encoding="utf-8")
    finally:
        path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\nTHE TREE DID NOT COME BACK CLEAN — a mutant may still be in the source:\n"
              + "\n".join(leftover))
        return 3

    print(f"\n{len(run) - len(survivors)}/{len(run)} killed")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} {w}" for m, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
