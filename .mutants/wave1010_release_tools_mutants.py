"""Wave 10.10 — do the release tools' decisions have a test that sees them?

⛔⛔ WHAT THE WAVE CLOSED (2026-09-23).

  POST-PUBLISH — `bump_version.py --post-publish` had no test, and its first
      rehearsal (copies of both repos, PyPI faked) left the web unit suite red.
      It now rewrites no test and no harness - those read the published version
      themselves - and prints a commit built from `POST_PUBLISH_WEB_PATHS`, the
      list of everything it writes. `tests/test_post_publish_rehearsal.py` runs
      the whole step on copies and then the web tests and anchors it can break.
  --agent — a bump printed the hand route (move the constant, then
      `--sync-twin`), which never opens the agent-log gate. It names
      `--post-publish VERSION` now, and so does the `--sync-twin` refusal.
  CHECK — `check_release.py` refused the whole release when the agent wheel sat
      in the staging folder. The agent is named and skipped, by package NAME.

The quiet mutants matter most:

  P3/P11 — PyPI is not asked, or its answer is not obeyed. Every "after the
      publish" assertion stays green; only the refusing rehearsal sees it.
  P5  — the commit forgets the served skill: the step works, the suite is
      green, and the hosted copy never reaches the commit anyone pushes.
  C1  — the agent is recognised by its `py3-none-any` tag: the agent case
      passes, and an unstamped MACHINE wheel from the source-mode fallback is
      waved through with it.

⛔ SR_WEB_REPO IS REQUIRED. The rehearsal skips without a web checkout, and a
skipped rehearsal would read as "the suite was fine with this mutant". Point it
at a checkout nothing else is mutating: the rehearsal COPIES it per run.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.

  SR_WEB_REPO=<web checkout> .venv/bin/python .mutants/wave1010_release_tools_mutants.py
  SR_WEB_REPO=<web checkout> .venv/bin/python .mutants/wave1010_release_tools_mutants.py P5 C1
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BUMP = "tools/bump_version.py"
CHECK = "tools/check_release.py"
FILES = (BUMP, CHECK)
SUITES = {
    BUMP: "tests/test_bump_version.py tests/test_post_publish_rehearsal.py",
    CHECK: "tests/test_release_provenance.py",
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: post_publish ──────────────────────────────────────────────────
B_FLIP_WHEEL = "        _flip_gate(gates, \"AGENT_WHEEL_PUBLISHED\", f'\"{version}\"'),\n"
B_FLIP_LOG = "        _flip_gate(gates, \"AGENT_LOG_STEP_PUBLISHED\", \"true\"),\n"
B_ASK = "    ok, what = _is_on_pypi(version)\n"
B_OBEY = ("        msgs.append(\"  Nothing was changed. Publish the wheel first, then re-run.\")\n"
          "        return False, msgs\n")
B_SYNC = "    ok_sync, msg = sync_fe_twin(root)\n"
B_PATH_SKILL = "    \"public/.well-known/skills\",\n"
B_ADD = "        f\"  {where} add {' '.join(POST_PUBLISH_WEB_PATHS)}\",\n"
B_WHERE = "    where = f'git -C \"{web}\"'\n"
# ── anchors: the printed routes ────────────────────────────────────────────
B_AGENT_ROUTE = "        print(f\"          python tools/bump_version.py --post-publish {args.agent}\")\n"
B_REFUSAL = "                  f\"`python tools/bump_version.py --post-publish {building}` - it \"\n"
# ── anchors: check_release ─────────────────────────────────────────────────
C_PICK = "    agent = [w for w in wheels if distribution(w) == AGENT_DISTRIBUTION]\n"
C_DROP = "    wheels = [w for w in wheels if w not in agent]\n"
C_SAY = "    lines: \"list[str]\" = [*skipped]\n"
C_NOTHING = "    if not wheels:\n        return False, [*skipped,"
C_NAME = "AGENT_DISTRIBUTION = \"superresearch_agent\"\n"
C_FIELD = "    return wheel.name.split(\"-\", 1)[0]\n"

MUTANTS = [
    # ══ post_publish ═══════════════════════════════════════════════════════
    ("P1", "under", BUMP,
     "⛔⛔ the agent-log gate is not opened: the publish lands and the Send Logs "
     "screen and the support assistant still hide the step that now works",
     [(B_FLIP_LOG, "")]),
    ("P2", "under", BUMP,
     "⛔⛔ the published version does not move: the twin syncs to a version the web "
     "repo says is not out, and every Hub install warns",
     [(B_FLIP_WHEEL, "")]),
    ("P3", "over", BUMP,
     "⛔⛔ PyPI is not asked - a typed-in belief moves everything downstream",
     [(B_ASK, "    ok, what = True, \"(PyPI not asked)\"\n")]),
    ("P4", "under", BUMP,
     "the twin is not synced: both gates move and the Hub keeps serving the old skill",
     [(B_SYNC, "    ok_sync, msg = True, \"(not synced)\"\n")]),
    ("P5", "under", BUMP,
     "⛔ the commit forgets the served skill - the step works, the suite is green, "
     "and the hosted copy never reaches what anyone pushes",
     [(B_PATH_SKILL, "")]),
    ("P6", "under", BUMP,
     "the commit line is typed by hand again, naming `tests/unit` - the old line",
     [(B_ADD, "        f\"  {where} add src/lib/agent-release-gates.ts tests/unit "
              "public/.well-known/skills scripts/agent-skill-sync.json\",\n")]),
    ("P7", "under", BUMP,
     "the commit names a placeholder instead of the checkout it changed",
     [(B_WHERE, "    where = \"git -C <web>\"\n")]),
    ("P11", "over", BUMP,
     "⛔⛔ PyPI says no, the step prints STOP - and carries on changing the web repo",
     [(B_OBEY, "        msgs.append(\"  Nothing was changed. Publish the wheel first, "
               "then re-run.\")\n")]),

    # ══ the printed routes ═════════════════════════════════════════════════
    ("R1", "under", BUMP,
     "⛔ a bump prints the hand route again, which never opens the agent-log gate",
     [(B_AGENT_ROUTE, "        print(\"          python tools/bump_version.py --sync-twin\")\n")]),
    ("R2", "under", BUMP,
     "the --sync-twin refusal sends the person to move the constant by hand",
     [(B_REFUSAL, "                  f\"move AGENT_WHEEL_PUBLISHED to {building} - it \"\n")]),

    # ══ check_release: the agent wheel ═════════════════════════════════════
    ("C1", "over", CHECK,
     "⛔⛔ the agent is recognised by its `py3-none-any` tag, so an unstamped "
     "MACHINE wheel from the source-mode fallback is skipped with it",
     [(C_PICK, "    agent = [w for w in wheels if platform_tag(w) == \"any\"]\n")]),
    ("C2", "under", CHECK,
     "⛔ the skip is announced and not done: the agent is still refused as unstamped",
     [(C_DROP, "    wheels = list(wheels)\n")]),
    ("C3", "over", CHECK,
     "the skip is silent - a wheel in the folder that nothing reports on",
     [(C_SAY, "    lines: \"list[str]\" = []\n")]),
    ("C4", "under", CHECK,
     "the agent alone is not 'nothing to check', so the person reads about three "
     "missing platforms instead of an empty release",
     [(C_NOTHING, "    if not wheels and not agent:\n        return False, [*skipped,")]),
    ("C5", "under", CHECK,
     "the package name as typed (`-`) rather than as a wheel spells it (`_`) - the "
     "agent is never recognised and the release is refused again",
     [(C_NAME, "AGENT_DISTRIBUTION = \"superresearch-agent\"\n")]),
    ("C6", "under", CHECK,
     "the whole file name is read as the package, so nothing is ever the agent",
     [(C_FIELD, "    return wheel.name\n")]),
]


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ A SKIP IS NOT A PASS: a skipped rehearsal reads as "fine with this mutant".
    if re.search(r"SKIPPED \[\d+\] tests/test_post_publish_rehearsal", out):
        raise SystemExit("⛔ the post-publish rehearsal SKIPPED — set SR_WEB_REPO")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    if not os.environ.get("SR_WEB_REPO"):
        print("⛔ set SR_WEB_REPO to a web checkout nothing else is mutating.")
        sys.exit(2)
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}

    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for fname in FILES:
        if not green(SUITES[fname]):
            print(f"⛔ BASELINE RED ({SUITES[fname]}) — fix the suite before mutating anything.")
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
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as se:
                raise AssertionError(f"mutant does not compile: {se}")
            path.write_text(mutated, encoding="utf-8")
            if green(SUITES[fname]):
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
