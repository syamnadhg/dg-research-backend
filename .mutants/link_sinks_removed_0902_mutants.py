"""STRETCH 7.5 STEP 5 (backend half) — the conversation address stops leaving.

⛔⛔ FOUR CHANNELS, AND NOT ONE OF THEM WAS A LINE THAT PUBLISHED A LINK:
the pause event streamed to the app and read back by a MODEL; a direct Firestore
write into `links.brief` that never passed this module's own deny list; an
unguarded mirror into `delivery.json`, which the local run server hands to any
caller on any interface; and the run log, which send-logs zips and uploads.

⛔ THE MUTANTS ARE MOSTLY "PUT IT BACK". A removal is only as good as the guard
that notices it returning, and three of the four sinks were justified by comments
naming consumers that no longer exist — so the prose would have welcomed each one
of these back.

⚠ THE PAUSE PAIR IS SCORED IN THE SAFETY NET'S OWN HARNESS, not here: mutants P2
(the wire gets the full snapshot again) and P2b (the strip moves inside
`snapshot()` and the checkpoint loses the reattachment key) live beside the pause
functions they belong to. This file owns everything else.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
The filtered selection is proven to cover EVERY test in the file this step owns
before a single mutant is applied.

    .venv/bin/python .mutants/link_sinks_removed_0902_mutants.py
    .venv/bin/python .mutants/link_sinks_removed_0902_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# This step's own file, plus the three existing suites whose expectations moved
# with it — so `--unfiltered` answers "does the tree catch it?" honestly.
SUITES = ("tests/test_link_sinks_removed_0902.py "
          "tests/test_drift_review_0805.py "
          "tests/test_p2_share_removed_0828.py "
          "tests/test_p1_regen_link_0902.py")

MINE = ("in_app_page or documents_of_one_run or own_origin or either_half or "
        "redaction or identifier_itself or same_tab or empty_address or "
        "log_lines or app_view or private_address_survives or "
        "full_snapshot_is_untouched or local_only_list or pause_emit_asks or "
        "brief_slot or nothing_is_written or firestore_failure or "
        "brief_branches or conversation_address_to_the_brief_name or "
        "arrived_on_results or delivery_mirror or links_file_is_still or "
        "never_reached_a_page or sweep_refused or predates_the_run or "
        "parser_refuses or "
        "reaches_a_sink or deny_list_still_names or comments_that_justified")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the very
# guard written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one. Every test in the file this step owns must be
# selected, or the harness refuses to score.
OWNED_FILES = ("tests/test_link_sinks_removed_0902.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
LOCAL_ONLY = '    _SNAPSHOT_LOCAL_ONLY = ("agent_chat_urls",)'
APP_VIEW = ('        return {k: v for k, v in self.snapshot().items()\n'
            '                if k not in self._SNAPSHOT_LOCAL_ONLY}')

RECORD_GUARD = '    if not url:\n        return\n    try:\n        update_link_in_firestore("brief", url, label="Research Brief",'
RECORD_TRY = ('    try:\n'
              '        update_link_in_firestore("brief", url, label="Research Brief",\n'
              '                                 phase=1, verified=True)\n'
              '    except Exception:\n'
              '        pass')

LIVE_BIND = ('                _in_app_brief_url = in_app_document_url("brief")\n'
             '                brief_url = _in_app_brief_url\n'
             '                _record_brief_in_aggregate(_in_app_brief_url)\n'
             '                brief_artifact = BriefArtifact(text=brief_text, url=_in_app_brief_url)\n'
             '                log(f"BriefArtifact: {brief_artifact.chars}')
REGEN_BIND = ('                        _regen_in_app_url = in_app_document_url("brief")\n'
              '                        brief_url = _regen_in_app_url\n'
              '                        _record_brief_in_aggregate(_regen_in_app_url)')

HANDOFF_PUBLISH = '            p3_links[_name] = in_app_document_url(_name.lower().replace(" ", ""))'
HANDOFF_GATE = '        if _url:\n            # \u26d4\u26d4 2026-09-02, stretch 7.5 step 5 \u2014 WHAT IS PUBLISHED IS NO LONGER'
OFF_TOPIC_DROP = '        if _url and _r.get("off_topic_rejected"):'
FOREIGN_DROP = ('        if _url and normalize_agent_key(_name) == "chatgpt" '
                'and _chatgpt_tab_is_foreign(_url):')

P2_MIRROR = '            save_checkpoint(queue_dir, 2, topic=topic, brief_url=brief_url)'

RED_EMPTY = '    _u = (url or "").strip()\n    if not _u:\n        return ""'
RED_DIGEST = '    _digest = hashlib.sha256(_u.encode("utf-8", "replace")).hexdigest()[:8]'
RED_EXCEPT = '    except Exception:\n        _host, _seg = "", ""'
RED_RESUME = '            log(f"[resume] {platform} restored at {redacted_chat_url(url)}")'
RED_POLL = '                            f"convo={redacted_chat_url(res.get(\'url\') or \'\')}")'

# (id, direction, why, [(from, to), ...])
MUTANTS = [
    # ═════════ S — the snapshot the app is allowed to see ════════════════════
    ("S1", "under",
     "the local-only list empties, so the paused event streams every agent's "
     "private conversation address to the event log again \u2014 and from there to a "
     "model, via the follow-up chat's recent-events tool",
     [(LOCAL_ONLY, '    _SNAPSHOT_LOCAL_ONLY = ()')]),
    ("S2", "under",
     "the app view stops filtering at all and returns the snapshot whole \u2014 the "
     "leak restored while every call site still reads as protected",
     [(APP_VIEW, '        return self.snapshot()')]),
    ("S3", "over",
     "the app view keeps the KEY with an empty map instead of dropping it, so a "
     "reader testing for the field believes the run reported no tabs rather than "
     "that we declined to say",
     [(APP_VIEW,
       '        _s = self.snapshot()\n'
       '        for _k in self._SNAPSHOT_LOCAL_ONLY:\n'
       '            _s[_k] = {}\n'
       '        return _s')]),

    # ═════════ B — the research record's brief slot ══════════════════════════
    ("B1", "under",
     "the empty-page guard goes, so a run that produced no brief still writes a "
     "brief slot \u2014 a record claiming a document that does not exist",
     [(RECORD_GUARD,
       '    try:\n        update_link_in_firestore("brief", url, label="Research Brief",')]),
    ("B2", "under",
     "the best-effort wrapper goes, so a transient Firestore failure on a "
     "convenience slot ends a run that had already produced its brief",
     [(RECORD_TRY,
       '    update_link_in_firestore("brief", url, label="Research Brief",\n'
       '                             phase=1, verified=True)')]),
    ("B3", "under",
     "\u26d4\u26d4 THE ROOT CAUSE RESTORED: `brief_url` goes back to meaning the ChatGPT "
     "tab on the live branch and the brief's own page on the other three, so the "
     "record, both checkpoints and the pause hand-off take whichever they are given",
     [(LIVE_BIND,
       '                _in_app_brief_url = in_app_document_url("brief")\n'
       '                brief_url = p1.get("url", "")\n'
       '                _record_brief_in_aggregate(_in_app_brief_url)\n'
       '                brief_artifact = BriefArtifact(text=brief_text, url=_in_app_brief_url)\n'
       '                log(f"BriefArtifact: {brief_artifact.chars}')]),
    ("B4", "under",
     "the regenerated brief stops filling the slot, so a run that paused and was "
     "given extra context ends with a record that still points at the first attempt",
     [(REGEN_BIND,
       '                        _regen_in_app_url = in_app_document_url("brief")\n'
       '                        brief_url = _regen_in_app_url')]),

    # ═════════ H — the phase-2 \u2192 phase-3 hand-off ═══════════════════════════
    ("H1", "under",
     "\u26d4\u26d4 the hand-off publishes the conversation address again \u2014 into links.json, "
     "the delivery mirror and the run log, exactly as before",
     [(HANDOFF_PUBLISH, '            p3_links[_name] = _url')]),
    ("H2", "under",
     "the published page is keyed by the DISPLAY name, so `ChatGPT` becomes the "
     "anchor instead of `chatgpt` and every row points at a document id that does "
     "not exist",
     [(HANDOFF_PUBLISH, '            p3_links[_name] = in_app_document_url(_name)')]),
    ("H3", "over",
     "the address gate goes, so a leg that never reached a page still publishes a "
     "row \u2014 and both drop guards are skipped with it, because they read the same "
     "value",
     [(HANDOFF_GATE,
       '        if True:\n            # \u26d4\u26d4 2026-09-02, stretch 7.5 step 5 \u2014 WHAT IS PUBLISHED IS NO LONGER')]),
    ("H4", "under",
     "the off-topic drop goes, so a leg the sweep refused still publishes a row "
     "\u2014 the 2026-08-05 incident, one value later",
     [(OFF_TOPIC_DROP, '        if False and _r.get("off_topic_rejected"):')]),
    ("H5", "under",
     "the foreign-conversation belt goes \u2014 the guard that catches a tab that is "
     "provably not this run's when the topic sweep cannot judge",
     [(FOREIGN_DROP,
       '        if False and normalize_agent_key(_name) == "chatgpt" '
       'and _chatgpt_tab_is_foreign(_url):')]),

    # ═════════ D — the delivery mirror ═══════════════════════════════════════
    ("D1", "under",
     "\u26d4\u26d4 the unguarded phase-2 mirror is restored: every agent's raw address "
     "written to delivery.json before either drop guard has run, and that file is "
     "returned verbatim by a local server that binds every interface with no auth",
     [(P2_MIRROR,
       '            save_checkpoint(queue_dir, 2, topic=topic, brief_url=brief_url)\n'
       '            agent_urls = {n: r.get("url", "") for n, r in results.items() if r.get("url")}\n'
       '            if agent_urls:\n'
       '                update_delivery(research_links=agent_urls)')]),

    # ═════════ L — the run log, which send-logs uploads ══════════════════════
    ("L1", "under",
     "the redactor hands back what it was given, so both log lines print the full "
     "address again and the support bundle carries it",
     [(RED_EMPTY, '    _u = (url or "").strip()\n    if True:\n        return _u')]),
    ("L2", "under",
     "the digest goes, so every tab on a platform logs the same label and two "
     "lines about different conversations can no longer be told apart",
     [(RED_DIGEST, '    _digest = "00000000"')]),
    ("L3", "over",
     "an address that will not parse falls through to the raw string, which makes "
     "a malformed URL the way past the redaction",
     [(RED_EXCEPT, '    except Exception:\n        return _u')]),
    ("L4", "under",
     "the resume line prints the address again \u2014 the one log line written every "
     "time a paused run comes back",
     [(RED_RESUME, '            log(f"[resume] {platform} restored at {url[:80]}")')]),
    ("L5", "under",
     "the extraction line prints the address again, once per agent per run",
     [(RED_POLL, '                            f"convo={(res.get(\'url\') or \'\')[:60]}")')]),
]

TESTS_LINE = __import__("re").compile(r"^(\d+) (passed|failed)", __import__("re").M)


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> str | None:
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _digest() -> dict:
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}


def _pytest(kfilter: str | None) -> str:
    """'green' | 'red' | 'nothing-collected'."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    code = sh(args, cwd=ROOT, env=ENV).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(kfilter: str | None) -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: str | None) -> set:
    args = [sys.executable, "-B", "-m", "pytest", *files,
            "--collect-only", "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    out = sh(args, cwd=ROOT, env=ENV).stdout
    return {ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(" ")}


def _filter_misses(kfilter: str) -> set:
    return _collected(OWNED_FILES, None) - _collected(OWNED_FILES, kfilter)


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    kfilter = None if unfiltered else MINE

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — spot check, not a score.")
    print("scope: THE WHOLE SELECTION (--unfiltered)" if unfiltered
          else "scope: THIS STEP'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this step's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS STEP'S OWN GUARDS, so "
                  "any mutant only they could kill would report as a SURVIVOR:")
            for tid in sorted(missed):
                print(f"    {tid}")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(kfilter) or not run_tests(None):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green (filtered and whole)\n")

    path = ROOT / TARGET
    survivors, faults, flaky = [], [], []
    for mid, direction, why, edits in selected:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            try:
                compile(mutated, TARGET, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            _mark(mid)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. On disagreement,
            # run a third time and take the majority — reported separately,
            # because "the guards cannot see this" and "that run was noisy" are
            # different claims and collapsing them sends the next reader hunting
            # a defect that is not there.
            verdicts = [not run_tests(kfilter) for _ in range(SURVIVOR_CONFIRMATIONS)]
            flapped = len(set(verdicts)) > 1
            if flapped:
                verdicts.append(not run_tests(kfilter))
            killed = sum(verdicts) * 2 > len(verdicts)
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = (f"  ⚠ FLAPPED {sum(verdicts)}/{len(verdicts)} — tie broken by "
                    "majority" if flapped else "")
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
            elif flapped:
                flaky.append((mid, sum(verdicts), len(verdicts)))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in selected if m[1] == "over")
    scope = " [whole selection]" if unfiltered else " [own guards]"
    label = " (SPOT CHECK)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority — killed, "
              f"but this selection is not perfectly stable:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
