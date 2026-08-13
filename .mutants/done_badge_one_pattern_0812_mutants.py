"""Mutation harness for S4 — one thinking-time badge pattern, two engines.

The fix collapses five hand-written readings of ChatGPT's finished-response
header into one shared source: `_THINKING_TIME_HEADER_SRC`, compiled by Python
for the vision-prose classifier and substituted into four `page.evaluate`
payloads as a JS literal.

Two mutation directions matter here and they pull opposite ways:

  UNDER — put a single verb back, in Python or in JS, or drop a substitution so
  one payload ships the raw placeholder. That is the 2026-08-11 state: two
  vocabularies for one label, which is what the fix exists to end.

  OVER — widen the pattern by deleting the time unit. That is the more dangerous
  direction and the one worth most of the weight, because it fails in the
  expensive direction: a research brief writes "worked for 3 years" in ordinary
  prose, and a unitless match turns the report's own text into a completion
  marker. Every note in research.py records a false COMPLETE as the strictly
  worse failure — it extracts an in-flight response and reports "no brief
  generated".

Safety: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, re-checks `git status` at the end.

    .venv/bin/python .mutants/done_badge_one_pattern_0812_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

# The new file plus the two existing suites that read this label from the other
# side: the vision-prose classifier (0811) and Phase 2's completion determination.
SUITES = ("tests/test_done_badge_one_pattern_0812.py "
          "tests/test_brief_done_label_0811.py "
          "tests/test_completion_determination_948.py "
          "tests/test_chatgpt_done_frames_0806.py "
          "tests/test_bugs_951.py")

_SRC_LINE = (
    '_THINKING_TIME_HEADER_SRC = (\n'
    '    r"\\b(?:thought|worked|reasoned|researched)\\s+for\\s+\\d+\\s*"\n'
    '    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)\\b")'
)

MUTANTS = [
    # ═════════════════ UNDER — the 2026-08-11 split, restored ══════════════
    ("U1", "under", "⭐ the source is back to the single verb — the state that cost 40 minutes",
     [(_SRC_LINE,
       '_THINKING_TIME_HEADER_SRC = (\n'
       '    r"\\bthought\\s+for\\s+\\d+\\s*"\n'
       '    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)\\b")')]),
    ("U2", "under", "⭐ only the JS half reverts — Python sees the label, the page does not",
     [('_THINKING_TIME_HEADER_JS = f"/{_THINKING_TIME_HEADER_SRC}/i"',
       '_THINKING_TIME_HEADER_JS = r"/thought for\\s+\\d/i"')]),
    ("U3", "under", "only the Python half reverts — the page sees it, the classifier does not",
     [("_THINKING_TIME_HEADER = re.compile(_THINKING_TIME_HEADER_SRC)",
       '_THINKING_TIME_HEADER = re.compile(r"\\bthought\\s+for\\s+\\d+\\s*(?:m|min|s|sec)\\b")')]),
    ("U4", "under", "the P2 completion probe ships the raw placeholder to the browser",
     [('             assistantLen, panelLen, bodyLen: bl.length, sources, steps, vw, vh };\n'
       '}""".replace("__DONE_BADGE_RE__", _THINKING_TIME_HEADER_JS)',
       '             assistantLen, panelLen, bodyLen: bl.length, sources, steps, vw, vh };\n'
       '}"""')]),
    ("U5", "under", "the host verify ships the raw placeholder",
     [("            return !!document.querySelector('.result-streaming, [data-is-streaming=\"true\"]');\n"
       '        }""".replace("__DONE_BADGE_RE__", _THINKING_TIME_HEADER_JS))',
       "            return !!document.querySelector('.result-streaming, [data-is-streaming=\"true\"]');\n"
       '        }""")')]),
    ("U6", "under", "the diagnostic twin ships the raw placeholder",
     [('        }""".replace("__DONE_BADGE_RE__", _THINKING_TIME_HEADER_JS)) or "no_hit"',
       '        }""") or "no_hit"')]),
    ("U7", "under", "the DR-iframe walk ships the raw placeholder",
     [('                        return false;\n'
       '                    }""".replace("__DONE_BADGE_RE__", _THINKING_TIME_HEADER_JS))',
       '                        return false;\n'
       '                    }""")')]),
    ("U8", "under", "the host badge short-circuit is deleted — residual streaming chrome wins",
     [("            if (__DONE_BADGE_RE__.test(bl)) return false;\n"
       "            return !!document.querySelector('.result-streaming",
       "            return !!document.querySelector('.result-streaming")]),
    ("U9", "under", "the diagnostic twin's short-circuit is deleted — the two disagree again",
     [('            if (__DONE_BADGE_RE__.test(bl)) return "";\n', "")]),
    ("U10", "under", "the P2 probe stops reading the badge at all",
     [("    const thoughtFor = __DONE_BADGE_RE__.test(bl);",
       "    const thoughtFor = false;")]),

    # ═══════════════ OVER — widened until prose reads as done ══════════════
    ("O1", "over", "⛔ the time unit is dropped — the brief's own prose becomes a done marker",
     [(_SRC_LINE,
       '_THINKING_TIME_HEADER_SRC = r"\\b(?:thought|worked|reasoned|researched)\\s+for\\s+\\d"')]),
    ("O2", "over", "⛔ the unit list keeps only the ambiguous single letters, and drops the digit",
     [(_SRC_LINE,
       '_THINKING_TIME_HEADER_SRC = (\n'
       '    r"\\b(?:thought|worked|reasoned|researched)\\s+for\\s+"\n'
       '    r"(?:hours|hour|minutes|minute|seconds|second|\\w+)\\b")')]),
    ("O3", "over", "the word boundary goes — 'rethought for 5m' inside a word now matches",
     [(_SRC_LINE,
       '_THINKING_TIME_HEADER_SRC = (\n'
       '    r"(?:thought|worked|reasoned|researched)\\s+for\\s+\\d+\\s*"\n'
       '    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)\\b")')]),
    ("O4", "over", "⛔ the verb family opens up to anything — 'ran for 5m' in prose reads as done",
     [(_SRC_LINE,
       '_THINKING_TIME_HEADER_SRC = (\n'
       '    r"\\b(?:\\w+)\\s+for\\s+\\d+\\s*"\n'
       '    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)\\b")')]),
    ("O5", "over", "the trailing boundary goes — 'worked for 3 hourly reports' matches",
     [(_SRC_LINE,
       '_THINKING_TIME_HEADER_SRC = (\n'
       '    r"\\b(?:thought|worked|reasoned|researched)\\s+for\\s+\\d+\\s*"\n'
       '    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)")')]),
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
            survivors.append((mid, direction, f"ANCHOR MISS: {exc}"))
        finally:
            path.write_text(original, encoding="utf-8")

    still_dirty = tracked_dirty()
    if still_dirty:
        print("\n⛔ the tree did not come back clean:\n" + "\n".join(still_dirty))
        return 2

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    for mid, direction, why in survivors:
        print(f"  SURVIVED {mid} [{direction}] {why}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
