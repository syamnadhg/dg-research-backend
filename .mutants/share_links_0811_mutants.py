"""Mutation harness for the thrown-away share links + the errored-on-success phase.

Every agent published a working public link on 2026-08-11 and the run shipped a
report linking to none of them, because the host literals had aged out. Gemini's
link was never read off the dialog; Claude's was read and silently rejected.

The over-corrections here are the dangerous direction, and there are more of them
than under-corrections on purpose. A share gate that is too LOOSE publishes a
private conversation URL as "verified public" — the run then tells the owner the
report is shareable when it is not, and a security event fires naming a URL that
isn't a share. Loosening the host match to a substring is the specific way that
happens, and it is the same defect that discarded 56% of the activity panel's
sources on 2026-08-06.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/share_links_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = "tests/test_share_links_0811.py tests/test_gemini_share_preview_guard.py"

MUTANTS = [
    # ── the hosts that rotted ───────────────────────────────────────────────
    ("H1", "under", "Gemini's new host is unknown again — the 08-11 outage returns",
     [('                (("share.gemini.google",), "/")),', '                ),')]),
    ("H2", "under", "Claude's new public path is unknown again",
     [('                (("claude.ai",), "/public/")),', '                ),')]),
    ("H3", "under", "the legacy Gemini hosts are dropped — trades one outage for another",
     [('    "gemini":  ((("gemini.google.com",), "/share"),\n                (("g.co",), "/gemini"),\n',
       '    "gemini":  (')]),
    ("H4", "under", "the dialog is not read for the current host",
     [("            link_el = await page.query_selector('input[value*=\"share.gemini.google\"]')\n"
       "            if not link_el:\n", "")]),

    # ── host vs substring ───────────────────────────────────────────────────
    ("M1", "over", "host match degraded to a substring — a query string can spoof it",
     [("        if not any(host == h or host.endswith(\".\" + h) for h in hosts):",
       "        if not any(h in url for h in hosts):")]),
    ("M2", "over", "any subdomain-looking suffix passes (evilgemini.google.com)",
     [('        if not any(host == h or host.endswith("." + h) for h in hosts):',
       '        if not any(host == h or host.endswith(h) for h in hosts):')]),
    ("M3", "over", "the path prefix is ignored, so a private chat URL passes",
     [("        if not path.startswith(prefix):\n            continue\n", "")]),
    ("M4", "over", "the share surface itself counts as a link",
     [('        if path.rstrip("/") == prefix.rstrip("/"):\n            continue\n', "")]),
    ("M5", "over", "a javascript: URL is accepted",
     [('    if parts.scheme not in ("http", "https"):\n        return False\n', "")]),
    ("M6", "over", "an unknown platform is accepted instead of rejected",
     [("    if not shapes or not url:\n        return False", "    if not url:\n        return False")]),

    # ── one authority ───────────────────────────────────────────────────────
    ("A1", "under", "Gemini's extractor goes back to its own private copy of the rule",
     [('        verified = _is_public_share_url("gemini", url)',
       '        verified = ("gemini.google.com/share" in url.lower())')]),
    ("A2", "under", "Claude's extractor goes back to its own private copy of the rule",
     [('        verified = _is_public_share_url("claude", url)',
       '        verified = "claude.site" in url.lower()')]),

    # ── the evidence ────────────────────────────────────────────────────────
    ("E1", "under", "the fallback is silent at INFO again",
     [('                          f"viewable by anyone else.", "WARN")',
       '                          f"viewable by anyone else.", "INFO")')]),
    ("E2", "under", "the fallback no longer prints the URL it rejected",
     [('                        + (f"a URL was produced but did not pass the public-share "\n'
       '                           f"rules: {_got[:120]}" if _got',
       '                        + (f"a URL was produced but did not pass the public-share "\n'
       '                           f"rules" if _got')]),
    ("E3", "under", "the extractor stops reporting a read-but-rejected link (Claude)",
     [('        if url and not verified:\n'
       '            log(f"[{label}] a link was read but is not a public share URL — "\n'
       '                f"{url[:120]}", "WARN")\n'
       '        return LinkResult(url=url, label=label, platform="claude"',
       '        return LinkResult(url=url, label=label, platform="claude"')]),

    # ── the phase that succeeded but was recorded errored ───────────────────
    ("P1", "under", "save_meta runs before the status again (extract branch)",
     [('                _write_phase_terminal_status(1, "complete")\n'
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),',
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                _write_phase_terminal_status(1, "complete")\n'
       '                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),')]),
    ("P2", "under", "save_meta runs before the status again (brief-from-file branch)",
     [('                _write_phase_terminal_status(1, "complete")\n'
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                emit_event("phase_complete", phase=1,\n'
       '                    durationSec=int(time.time() - _p1_start), links=_p1_links,',
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                _write_phase_terminal_status(1, "complete")\n'
       '                emit_event("phase_complete", phase=1,\n'
       '                    durationSec=int(time.time() - _p1_start), links=_p1_links,')]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q"]).returncode == 0


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

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
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

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
