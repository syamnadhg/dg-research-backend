"""Mutation harness for L1/L2 — clipboard-before-prose, and closing the canvas.

L1 is a pure ORDERING fix, which makes it unusually easy to test badly: a
harness that only checks "a URL came back" passes against the bug, because the
bug returns a URL. So the mutants here are mostly re-orderings and deletions of
one of the two readings, and the tests have to notice WHICH source won.

L2 fails in two directions and both are covered:

  UNDER — the canvas is not closed, or is closed after the Share lookup (a
  no-op, since the lookup is what the canvas was covering), or JS clicks it
  itself, which does not work on a React overlay.

  OVER — ⛔ something that is not a canvas gets closed, or Escape is pressed on
  a page with no canvas at all. This path runs on every ChatGPT extraction, so
  an over-eager close is a keystroke sent into every single run.

Safety: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, re-checks `git status` at the end.

    .venv/bin/python .mutants/share_ordering_0812_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_share_ordering_0812.py "
          "tests/test_share_links_0811.py "
          "tests/test_share_expectations_0811.py "
          "tests/test_audio_share_claim_0811.py "
          "tests/test_914_claude_artifact_keepopen.py")

MUTANTS = [
    # ═══════════ L1 — the primary path (publish_open_claude_artifact) ══════
    ("P1", "under", "⭐ prose is read first again — the 2026-08-12 dead link, verbatim",
     [('        text = (result or {}).get("text", "")\n'
       '        clip, _ = await _read_clipboard_after_copy(\n'
       '            lambda c: _is_public_share_url("claude", c))\n'
       '        if clip:\n'
       '            return clip\n'
       '        m = re.search(r\'https://claude\\.site/artifacts/[a-f0-9-]+\', text)\n'
       '        if not m:\n'
       '            m = re.search(r\'https://claude\\.(?:site|ai)/[^\\s]+\', text)\n'
       '        if m:\n'
       '            return m.group(0)',
       '        text = (result or {}).get("text", "")\n'
       '        m = re.search(r\'https://claude\\.site/artifacts/[a-f0-9-]+\', text)\n'
       '        if not m:\n'
       '            m = re.search(r\'https://claude\\.(?:site|ai)/[^\\s]+\', text)\n'
       '        if m:\n'
       '            return m.group(0)\n'
       '        clip, _ = await _read_clipboard_after_copy(\n'
       '            lambda c: _is_public_share_url("claude", c))\n'
       '        if clip:\n'
       '            return clip')]),
    ("P2", "under", "⭐ the stale host literal is back — the live Publish URL is rejected",
     [('        clip, _ = await _read_clipboard_after_copy(\n'
       '            lambda c: _is_public_share_url("claude", c))',
       "        clip, _ = await _read_clipboard_after_copy(\n"
       "            lambda c: 'claude.site' in c)")]),
    ("P3", "over", "⛔ the prose fallback is deleted — a mission that reports without copying fails",
     [('        m = re.search(r\'https://claude\\.site/artifacts/[a-f0-9-]+\', text)\n'
       '        if not m:\n'
       '            m = re.search(r\'https://claude\\.(?:site|ai)/[^\\s]+\', text)\n'
       '        if m:\n'
       '            return m.group(0)',
       "        pass")]),
    ("P4", "over", "the clipboard shape test accepts anything — a stale link impersonates the copy",
     [('            lambda c: _is_public_share_url("claude", c))',
       "            lambda c: bool(c))")]),

    # ═══════════ L1 — the fallback path (extract_share_link_claude) ════════
    ("F1", "under", "⭐ the twin reads prose first again",
     [('                clip, _ = await _read_clipboard_after_copy(\n'
       '                    lambda c: "claude." in c)\n'
       '                if clip:\n'
       '                    url = clip\n'
       '                else:\n'
       '                    m = re.search(r\'https://claude\\.(?:site|ai)/[^\\s]+\', text)\n'
       '                    if m:\n'
       '                        url = m.group(0)',
       '                m = re.search(r\'https://claude\\.(?:site|ai)/[^\\s]+\', text)\n'
       '                if m:\n'
       '                    url = m.group(0)\n'
       '                else:\n'
       '                    clip, _ = await _read_clipboard_after_copy(\n'
       '                        lambda c: "claude." in c)\n'
       '                    if clip:\n'
       '                        url = clip')]),

    # ══════════════════════ L2 — closing the canvas ════════════════════════
    ("C1", "under", "⭐ the canvas is never closed — the Share button stays covered",
     [("            _canvas_closed = await _close_chatgpt_canvas(page)",
       '            _canvas_closed = ""')]),
    ("C2", "under", "the close runs AFTER the Share lookup, which is a no-op",
     [("        try:\n"
       "            _canvas_closed = await _close_chatgpt_canvas(page)\n"
       '            if _canvas_closed:\n'
       '                log(f"[{label}] closed the open canvas before the share step "\n'
       '                    f"({_canvas_closed})")\n'
       "        except Exception as _cc:\n"
       '            log(f"[{label}] canvas close skipped: {_cc}", "DEBUG")\n',
       "")]),
    ("C3", "under", "the close control is never marked — only Escape is ever tried",
     [("                b.setAttribute(mark, '1');\n                return sel;",
       "                return \"\";")]),
    ("C4", "under", "JS clicks the control itself — which does not close a React overlay",
     [("            btn = await page.query_selector(f'[{_CANVAS_CLOSE_MARK}=\"1\"]')\n"
       "            if btn is not None:\n"
       "                await btn.click(timeout=2000)",
       "            btn = await page.query_selector(f'[{_CANVAS_CLOSE_MARK}=\"1\"]')\n"
       "            if btn is not None:\n"
       "                pass")]),
    ("C5", "under", "the Escape fallback is gone — a canvas with no close control stays open",
     [('        await page.keyboard.press("Escape")\n', "")]),
    ("C6", "under", "the label test matches nothing useful — Download and Share are the only buttons left",
     [("        return /close|collapse|shrink|exit|minimi[sz]e|back to chat/.test(t);",
       "        return /dismiss/.test(t);")]),
    ("O1", "over", "⛔ the size floor is gone — a response container with 'canvas' in a class is closed",
     [("            if (r.width >= 320 && r.height >= 240) return true;", "            return true;")]),
    ("O2", "over", "⛔ the mark floor is gone — a close button inside the ANSWER gets pressed",
     [("            if (r.width < 320 || r.height < 240) continue;\n"
       "            for (const b of root.querySelectorAll('button, [role=\"button\"]')) {",
       "            for (const b of root.querySelectorAll('button, [role=\"button\"]')) {")]),
    ("O3", "over", "⛔ Escape is pressed even when no canvas is open — on every single run",
     [("        if not await page.evaluate(_CANVAS_PROBE_JS, list(_CANVAS_ROOT_SELECTORS)):\n"
       '            return ""',
       "        await page.evaluate(_CANVAS_PROBE_JS, list(_CANVAS_ROOT_SELECTORS))")]),
    ("O4", "over", "any button in the canvas is marked — Download is as likely as Close",
     [("            for (const b of root.querySelectorAll('button, [role=\"button\"]')) {\n"
       "                if (!closeish(b)) continue;",
       "            for (const b of root.querySelectorAll('button, [role=\"button\"]')) {")]),
    ("O5", "over", "a stuck canvas reports success — the log claims a close that did not happen",
     [("                if not await _still_open():\n"
       '                    return f"close control in {hit}"',
       '                return f"close control in {hit}"')]),
    ("O6", "over", "⛔ a page that throws takes the whole share attempt down",
     [("    try:\n"
       "        if not await page.evaluate(_CANVAS_PROBE_JS, list(_CANVAS_ROOT_SELECTORS)):\n"
       '            return ""\n'
       "    except Exception:\n"
       '        return ""',
       "    if not await page.evaluate(_CANVAS_PROBE_JS, list(_CANVAS_ROOT_SELECTORS)):\n"
       '        return ""')]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=180).returncode == 0
    except subprocess.TimeoutExpired:
        return False


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
