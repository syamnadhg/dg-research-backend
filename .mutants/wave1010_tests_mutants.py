"""Mutation harness — wave 10.10, the test-hygiene lane.

⛔ WHAT THIS LANE FIXED IS TESTS, so most mutants here mutate a TEST or the
suite's own `conftest.py`. That is where the decisions live: whether a pin that
reads another checkout skips, fails or passes when it cannot see it; whether a
test executes the thing it names or reads its source. A pin nobody can break is
the defect this lane exists for, so each one is broken here, once, on purpose.

⭐⭐ THE SHARPEST MUTANTS HERE:
  F1  — a mistyped SR_WEB_REPO goes quiet again. The one place somebody thought
        they had switched the cross-repo pins ON is the place they stop.
  F2  — the finder stops asking the git common dir, so every pin goes blind in
        a worktree — the layout every wave is gated in.
  C1-C12 — each CONSUMER goes back to building its own path. The finder stays
        perfect and tested; the consumer ignores it. ⛔ These run WITHOUT the
        source sweep (`-k "not builds_its_own_path"`), so a kill can only come
        from a pin that RUNS the consumer.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, counted OUT. Every mutated file is COMPILED before it
is written. ⛔ THE VERDICT IS THE SUMMARY LINE, NEVER THE EXIT CODE: a mutant is
killed when its tests report a failure or an error, or fewer passes than the
baseline did (a new SKIP is a lost measurement, and counts as a kill only
because it is one). A run with no summary line is a fault, not a kill.

⛔ SR_WEB_REPO IS REQUIRED, so every consumer runs for real and none skips.

  SR_WEB_REPO=<web checkout> <venv>/bin/python -u .mutants/wave1010_tests_mutants.py
  SR_WEB_REPO=<web checkout> <venv>/bin/python -u .mutants/wave1010_tests_mutants.py F1 C3
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_RUN_TIMEOUT_S = 900

CONFTEST = "tests/conftest.py"
FINDER_T = "tests/test_web_repo_finder_1010.py"
#: The consumer pins with the source sweep taken out, so a C-mutant's kill has
#: to come from running the consumer.
PINS = [FINDER_T, "-k", "not builds_its_own_path"]
SEND_LOGS = "tests/test_send_logs_command_0818.py"
TELEMETRY = "tests/test_telemetry_0818.py"
CALL_SITES = "tests/test_telemetry_call_sites_0818.py"
SOURCES = "tests/test_numbered_sources_0918.py"
PLACEMENT = "tests/test_numbered_sources_placement_0918.py"
BUNDLE = "tests/test_bundle_left_out_row_109.py"
IMAGES = "tests/test_document_images_0913.py"
INCOGNITO = "tests/test_incognito_capability_109.py"
BUMP = "tests/test_bump_version.py"
RESEARCH = "research.py"
#: Only the rewritten test: the rest of that file still reads source text, and
#: a kill from one of those would not measure the rewrite.
RANK = ["tests/test_gemini_flash_rank.py", "-k", "reject_list_and_family"]

# ── anchors: the one finder ─────────────────────────────────────────────────
ENV_CLAIM = ('        assert (Path(env) / WEB_REPO_MARKER).is_file(), (\n'
             '            f"SR_WEB_REPO={env!r} is not a dg-research checkout — there is no "\n'
             '            f"{WEB_REPO_MARKER} there, so every cross-repo pin was aimed at nothing")\n'
             '        return Path(env)')
COMMON_DIR = ('            if via_common not in out:\n'
              '                out.append(via_common)')
MARKER = ('        if (base / WEB_REPO_MARKER).is_file():\n'
          '            return base')
MISSING_FILE = ('    assert path.is_file(), (\n'
                '        f"{rel} is missing from the web checkout at {web} — {what} "\n'
                '        f"cannot be compared without it; re-anchor this pin if the web moved it")')
LOUD_SKIP = ('        pytest.skip(\n'
             '            f"⛔ NO WEB CHECKOUT on this disk (looked in "\n'
             '            f"{\', \'.join(str(p) for p in web_repo_candidates())}) — {what} was "\n'
             '            f"NOT compared; set SR_WEB_REPO to a dg-research checkout")')
ONLY_CANDIDATE = ('    if env:\n'
                  '        return [Path(env)]\n'
                  '    return sibling_web_checkouts(here)')

# ── the old shapes each consumer had ────────────────────────────────────────
OLD_SKIP = '        pytest.skip("sibling app repo not checked out")\n'

MUTANTS = [
    # ══ the finder ══════════════════════════════════════════════════════════
    ("F1", "under", "⛔⛔ a mistyped SR_WEB_REPO reads as 'no web checkout here', "
     "so every pin goes quiet in the one place somebody switched them on",
     [(ENV_CLAIM, '        if not (Path(env) / WEB_REPO_MARKER).is_file():\n'
                  '            return None\n'
                  '        return Path(env)')],
     CONFTEST, [FINDER_T]),
    ("F2", "under", "⛔⛔ the git common dir is not asked, so in a worktree every "
     "cross-repo pin finds nothing and skips",
     [(COMMON_DIR, '            if False:\n'
                   '                out.append(via_common)')],
     CONFTEST, [FINDER_T]),
    ("F3", "under", "any directory with the right name is taken for the web "
     "checkout, so an empty folder answers every pin",
     [(MARKER, '        if base.is_dir():\n'
               '            return base')],
     CONFTEST, [FINDER_T]),
    ("F4", "under", "⛔ a web checkout that no longer has the file a pin compares "
     "SKIPS — the drift itself, hidden as an absence",
     [(MISSING_FILE, '    if not path.is_file():\n'
                     '        pytest.skip(f"{rel} is not in {web}")')],
     CONFTEST, [FINDER_T]),
    ("F5", "under", "the skip stops saying what went unmeasured and where it looked "
     "— the old 'sibling app repo not checked out'",
     [(LOUD_SKIP, OLD_SKIP.rstrip("\n"))],
     CONFTEST, [FINDER_T]),
    ("F6", "over", "SR_WEB_REPO stops being the ONLY answer: a mistyped value "
     "falls back to the sibling, so the pin reads a checkout nobody named",
     [(ONLY_CANDIDATE, '    return ([Path(env)] if env else []) + sibling_web_checkouts(here)')],
     CONFTEST, [FINDER_T]),

    # ══ every consumer asks the finder ══════════════════════════════════════
    ("C1", "under", "⛔⛔ the send-logs fake store reads its rules from its own path "
     "again, and with none there it enforces NOTHING while every writer test passes",
     [('    web = web_repo()\n'
       '    if web is None:\n'
       '        return None, None\n',
       '    web = Path(__file__).resolve().parents[2] / "dg-research"\n'
       '    if not (web / "firestore.rules").exists():\n'
       '        return None, None\n')],
     SEND_LOGS, PINS),
    ("C2", "under", "the upload-ceiling pin builds its own path again",
     [('    rules = web_file("the log upload\'s size cap", "storage.rules")\n',
       '    rules = Path(__file__).resolve().parents[2] / "dg-research" / "storage.rules"\n'
       '    if not rules.exists():\n' + OLD_SKIP)],
     SEND_LOGS, PINS),
    ("C3", "under", "the content-type pin builds its own path again",
     [('    rules = web_file("the log upload\'s content type", "storage.rules")\n',
       '    rules = Path(__file__).resolve().parents[2] / "dg-research" / "storage.rules"\n'
       '    if not rules.exists():\n' + OLD_SKIP)],
     SEND_LOGS, PINS),
    ("C4", "under", "the bundle-contract pin builds its own path again",
     [('        theirs_path = web_file("the send-logs cap and action names",\n'
       '                               "src/lib/bundle-contract.json")\n',
       '        theirs_path = (Path(__file__).resolve().parents[2] / "dg-research"\n'
       '                       / "src" / "lib" / "bundle-contract.json")\n'
       '        if not theirs_path.exists():\n'
       '            pytest.skip("sibling app repo not checked out")\n')],
     SEND_LOGS, PINS),
    ("C5", "under", "the telemetry catalogue pin builds its own path again",
     [('    there = web_file("the app\'s copy of the telemetry catalogue",\n'
       '                     "src/lib/telemetry-catalogue.json")\n',
       '    there = Path(__file__).resolve().parents[2] / "dg-research" / "src" / "lib" / "telemetry-catalogue.json"\n'
       '    if not there.exists():\n' + OLD_SKIP)],
     TELEMETRY, PINS),
    ("C6", "under", "the pairing-route pin builds its own path again",
     [('    route = web_file("the pairing route\'s install id",\n'
       '                     "src/app/api/devices/initiate-pair/route.ts")\n',
       '    route = Path(__file__).resolve().parents[2] / "dg-research" / "src" / "app" / "api" / "devices" / "initiate-pair" / "route.ts"\n'
       '    if not route.exists():\n' + OLD_SKIP)],
     CALL_SITES, PINS),
    ("C7", "under", "the source-token pin builds its own path again",
     [('        ts = web_file("the web\'s SOURCE_TOKEN_RE, against this port",\n'
       '                      "src/lib/doc-sources.ts")\n',
       '        ts = (Path(__file__).resolve().parents[2]\n'
       '              / "dg-research" / "src" / "lib" / "doc-sources.ts")\n'
       '        if not ts.exists():\n'
       '            pytest.skip("no dg-research checkout beside this repo")\n')],
     SOURCES, PINS),
    ("C8", "under", "the heading-rules pin reads its own path again",
     [('            src = web_file("the planner and viewer heading rules",\n'
       '                           str(WEB_LIB / name)).read_text(encoding="utf-8")',
       '            src = (Path(__file__).resolve().parents[2] / "dg-research" / WEB_LIB\n'
       '                   / name).read_text(encoding="utf-8")')],
     PLACEMENT, PINS),
    ("C9", "under", "the left-out-counts pin builds its own path again",
     [('    rules = web_file("the logBundles left-out counts", "firestore.rules")\n',
       '    rules = Path(__file__).resolve().parents[2] / "dg-research" / "firestore.rules"\n'
       '    if not rules.exists():\n'
       '        pytest.skip("no web checkout beside this one; set SR_WEB_REPO")\n')],
     BUNDLE, PINS),
    ("C10", "under", "the upload-contract pin goes back to a finder that does "
     "not honour SR_WEB_REPO",
     [('    repo = require_web_repo("the machine/web upload contract")\n',
       '    repo = next((c for c in [Path(R.__file__).resolve().parent.parent / "dg-research"]\n'
       '                 if (c / ".git").exists()), None)\n'
       '    if repo is None:\n'
       '        pytest.skip("THE WEB REPO (dg-research) IS NOT ON THIS DISK")\n')],
     IMAGES, PINS),
    ("C11", "under", "⛔ the incognito id-shape pins read their own path again, so "
     "a mistyped SR_WEB_REPO is not a failure there",
     [('    web = require_web_repo("the four copies of the incognito id shape")\n',
       '    web = Path(__file__).resolve().parents[2] / "dg-research"\n')],
     INCOGNITO, [INCOGNITO]),
    ("C12", "under", "the release tool's default is probed against this "
     "checkout's own parent again, which in a worktree holds no app at all",
     [('    looked = sibling_web_checkouts()\n',
       '    looked = [Path(bump_mod.__file__).resolve().parents[1].parent / "dg-research"]\n')],
     BUMP, PINS),

    # ══ the Gemini ranker's caller, executed rather than read ═══════════════
    # ⛔ These mutate the CALLER in research.py. The test they answer to used
    # to read that caller's source by line numbers taken at import, so it
    # failed about one run in ten; it now runs the caller against a page
    # double, and only that test is run here.
    ("R1", "under", "⛔ the ranker is handed a baked-in family instead of the "
     "policy's, so a family rename changes nothing the browser does",
     [('"fam": _gm_family, "reject": _gm_reject,',
       '"fam": "flash", "reject": _gm_reject,')],
     RESEARCH, RANK),
    ("R2", "under", "⛔ the ranker is handed no reject list, so Flash-Lite or a Pro "
     "row can win on version number",
     [('"fam": _gm_family, "reject": _gm_reject,',
       '"fam": _gm_family, "reject": [],')],
     RESEARCH, RANK),
    ("R3", "under", "the family stops coming from policy at all",
     [('        _gm_family = p2_family("gemini") or "flash"',
       '        _gm_family = "flash"')],
     RESEARCH, RANK),
    ("R4", "under", "the reject list is read for the wrong platform",
     [('        _gm_reject = reject_terms("gemini")',
       '        _gm_reject = reject_terms("claude")')],
     RESEARCH, RANK),
    ("R5", "under", "the trigger read hunts a literal family, so on a rename the "
     "ranker can click the dropdown's own button and call it a pick",
     [('            }""", _gm_family)',
       '            }""", "flash")')],
     RESEARCH, RANK),
]


# ── the runner ──────────────────────────────────────────────────────────────

_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)")


def summary(tests):
    """pytest's own tally for `tests`, from its SUMMARY LINE — or a fault."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the tests ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines() if re.search(r" in [\d.]+s", ln) and _COUNT.search(ln)]
    if not lines:
        raise AssertionError("pytest printed no summary line — the run did not happen:\n"
                             + out[-1500:])
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for n, kind in _COUNT.findall(lines[-1]):
        counts["error" if kind.startswith("error") else kind] = int(n)
    return counts


if __name__ == "__main__":
    if not os.environ.get("SR_WEB_REPO"):
        sys.exit("⛔ set SR_WEB_REPO to a web checkout — without it the consumers "
                 "skip, and a skip here would read as a kill")
    only = set(sys.argv[1:])
    selected = [m for m in MUTANTS if not only or m[0] in only]
    files = sorted({m[4] for m in selected})
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in files}

    baselines = {}
    print("baseline… ", end="", flush=True)
    for tests in sorted({tuple(m[5]) for m in selected}):
        got = summary(list(tests))
        if got["failed"] or got["error"] or not got["passed"]:
            print(f"⛔ BASELINE RED for {' '.join(tests)}: {got}")
            sys.exit(2)
        baselines[tests] = got
    print("green\n", flush=True)

    survivors, faults = [], []
    for mid, direction, why, edits, fname, tests in selected:
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
            got = summary(tests)
            base = baselines[tuple(tests)]
            killed = bool(got["failed"] or got["error"] or got["passed"] < base["passed"])
            if killed:
                print(f"  {mid}  ✓ killed  {got}", flush=True)
            else:
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}  {got}", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    over = sum(1 for m in selected if m[1] == "over")
    print(f"\n{measured - len(survivors)}/{measured} killed ({over} over-corrections)")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
