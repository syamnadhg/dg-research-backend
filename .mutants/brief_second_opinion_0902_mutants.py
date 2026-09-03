"""Mutation harness — stretch 7.5 step 4 (2026-09-02).

⛔⛔ THIS AREA HAS NEVER BEEN MUTATION-TESTED. Measured before writing a line:
across all 83 harnesses in this directory, not one anchor sits inside
`topic_anchors`, `text_is_off_topic`, `reject_off_topic_text`,
`apply_off_topic_sweep` or `title_refusal_verdict`, and neither constant has
ever been mutated. The two harnesses that mention the topic guard at all anchor
on the DOWNSTREAM `off_topic_rejected` marker. The guard that stopped the
2026-08-05 incident has been guarded only by tests that pass.

⛔⛔ AND THE STEP'S OWN PLANNING NUMBER WAS FICTION. The plan said briefs run
2,000-5,000 characters, so a subject check on the brief "can never fire" under
the 20,000-character floor. Twenty-seven real briefs in this machine's logs
measure 46,183 to 73,494, median 62,893 — not one below 46 KB. The figure came
from a code comment that has been wrong by an order of magnitude for months.
What makes the obvious fix wrong is not that it cannot fire, it is what it DOES:
`reject_off_topic_text` answers with `""` and phase 2 cannot run without a
brief, so it would end runs reporting the brief MISSING rather than wrong.

⭐⭐ THE SHARPEST MUTANTS HERE — each re-creates a defect this repo has paid for:
  T1/B4/S1 — an ABSTAIN becomes a VERDICT. "I cannot judge this" coming out as
             "this is wrong" is the 2026-08-27 kill, and these put it back in
             three separate places: the shared rule, the brief, the report.
  B2       — the brief's bar drifts above the smallest brief ever measured, so
             the check reports healthy and looks at nothing. The failure the
             stale 2-5k comment would have produced if believed.
  G2       — the card has no Retry button and the gate waits for an answer
             anyway. Phase 1 parks for twenty-four hours on a decision nobody
             can give. Invisible to any test that reads only the return value.
  W1       — the second witness becomes the source URL list, so a hostname
             containing a topic word is treated as the agent SAYING something.
  S3       — the two witnesses stop being distinguished, so an extraction fault
             and a genuine drift collapse into one verdict and the agent that
             did the right work gets accused of the wrong one.
  H2       — the rejected report file is dropped, and the Flow-B fallback scan
             finds it again on disk one directory listing later. Not invented:
             this harness's own test caught it in the first cut of the fix.
  D1       — the retry recursion forwards the attempt count unchanged, so the
             budget never runs down.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
The filtered selection is proven to cover EVERY test in the file this step owns
before a single mutant is applied.

    .venv/bin/python .mutants/brief_second_opinion_0902_mutants.py
    .venv/bin/python .mutants/brief_second_opinion_0902_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ⚠ `tests/test_chatgpt_row_scope_0805.py` IS DELIBERATELY ABSENT. It takes 50
# SECONDS — five pre-existing tests in it sleep for real — which at two runs per
# mutant would be an hour of wall clock. The one test in it this step touched
# (the MD-writer enumeration) is a source scan that no mutant below can reach,
# and the ordinary suite pass runs it in full.
SUITES = ("tests/test_brief_and_second_opinion_0902.py "
          "tests/test_topic_guard_and_never_grew.py "
          "tests/test_title_corroboration_0806.py "
          "tests/test_drift_review_0805.py")

MINE = ("presence or unguardable or empty_text or matching or anchor or "
        "predicate or title or brief or bar or stub or judged or whitespace or "
        "pure or card or gate or abstain or retry or stop or keep or budget or "
        "wait or restart or recorded or witness or urls or poll_set or "
        "snapshot or verdict or suspect or corroborate or thin or sweep or "
        "twice or destroy or notebooklm or dispatch or counts or subject or "
        "second_opinion or opinion or REPORT_FILE or flow_B or derived or "
        "healthy or rejected or refactor or floor or look or nothing")

OWNED_FILES = ("tests/test_brief_and_second_opinion_0902.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ──────────────────────────────────────────────────────────────────
T_ABSTAIN = ("    anchors = topic_anchors(topic)\n"
             "    if len(anchors) < _TOPIC_GUARD_MIN_ANCHORS:\n"
             "        return None")
T_DECIDE = ('    low = (text or "").lower()\n'
            "    return any(a in low for a in anchors)")
F_FLOOR = ('    if len(text or "") < _TOPIC_GUARD_MIN_CHARS:\n'
           "        return False")
F_DECIDE = "    return topic_presence(text, topic) is False"
TT_ACCEPT = ('    if topic_presence(_t, topic) is not False:\n'
             '        return "accept"')

B_CONST = "_BRIEF_TOPIC_MIN_CHARS = 2_000"
B_FLOOR = ('    if len(_b) < _BRIEF_TOPIC_MIN_CHARS:')
B_STRIP = '    _b = (brief or "").strip()'
B_NONE = ('    if _seen is None:\n'
          '        return "abstain"')
B_PICK = '    return "accept" if _seen else "off_topic"'

G_EMPTY = ("    if not brief_text:\n"
           '        return "keep"')
G_GATE = '    if verdict != "off_topic":'
G_SAYS = '        if verdict == "abstain":'
G_EMIT = '        emit_event("wrong_artifact_rejected", phase=1, agent="chatgpt",'
G_CANRETRY = ('               agent="chatgpt",\n'
              "               can_retry=retries_left > 0)")
G_BUDGET = "    if retries_left <= 0:"
G_STOP = ('    if decision == "stop":\n'
          '        return "stop"')
G_RETRY = ('    log(f"Phase 1 brief-topic decision: {decision}")\n'
           '    if decision == "stop":\n'
           '        return "stop"\n'
           '    if decision == "retry":')
G_KEEP = ("    # has looked at the brief and kept it.\n"
          '    return "keep"')

W_KEYS = '    for _key in ("steps", "sections"):'
W_CONST = "_WITNESS_MIN_CHARS = 500"
W_STRIP = '    _w = (witness or "").strip()'

S_NONE = ("    if _seen_in_report is None:\n"
          '        return "abstain"')
S_AGREE = ("    if _seen_in_report:\n"
           '        return "agree"')
S_SPLIT = ('    return "extraction_suspect" if topic_presence(_w, topic) '
           'else "drift_corroborated"')

R_ONCE = '            if "topic_second_opinion" not in r:'
R_CALL = ("                r[\"topic_second_opinion\"] = _second_opinion_on_agent(\n"
          "                    text, _t, _so_key, name)")
R_LOUD = '    if verdict == "drift_corroborated":'
R_ALERT = '                actions=[], alert_id=f"phase2_{agent_key}_second_opinion",'

H_DROP = '        if _has_md and _r.get("off_topic_rejected"):'
H_REMEMBER = "            _dropped_stems.add(_md_path.stem.lower())"
H_SCAN = "                if _f.stem.lower() in _dropped_stems:"

D_CALL = "    _bt_action = await brief_topic_gate(brief_text, topic,"
D_STOP = ('    if _bt_action == "stop":\n'
          "        return None")
D_RETRY = ('    if _bt_action == "retry":\n'
           "        return await run_phase1(browser, cua_client, topic, pdf_paths,\n"
           "                                verbose=verbose, feedback=feedback,\n"
           "                                _retry_count=_retry_count + 1)")

# (id, direction, why, [(from, to)])
MUTANTS = [
    # ═════════ T — the one presence rule ════════════════════════════════════
    ("T1", "under",
     "⛔⛔⛔ ABSTAIN BECOMES 'NAMES NOTHING' IN THE SHARED RULE. An unguardable "
     "topic would now condemn the brief, the title and every report at once — "
     "the 2026-08-27 failure class, promoted to the one place all of them read",
     [(T_ABSTAIN, "    anchors = topic_anchors(topic)\n"
                  "    if len(anchors) < _TOPIC_GUARD_MIN_ANCHORS:\n"
                  "        return False")]),
    ("T2", "under",
     "the rule is inverted: a document that names the subject reads as one that "
     "does not, and vice versa",
     [(T_DECIDE, '    low = (text or "").lower()\n'
                 "    return not any(a in low for a in anchors)")]),
    ("T3", "over",
     "the anchor floor is gone, so a one-word topic becomes guardable and "
     "'best practices for team retrospectives' starts failing healthy runs",
     [(T_ABSTAIN, "    anchors = topic_anchors(topic)\n"
                  "    if False:\n"
                  "        return None")]),

    # ═════════ F — the report predicate keeps its own floor ═════════════════
    ("F1", "over",
     "the 20,000-character floor goes, so the report guard starts judging "
     "partial extractions — the exact reason the floor exists",
     [(F_FLOOR, '    if False:\n        return False')]),
    ("F2", "under",
     "the report guard never fires again: 121 KB about golden retrievers ships "
     "as the run's deliverable, which is the incident verbatim",
     [(F_DECIDE, "    return False")]),
    ("F3", "over",
     "⛔ SUBTLE — `is False` becomes `is not None`, so a report that DOES name "
     "the subject is rejected. Every healthy long report is thrown away",
     [(F_DECIDE, "    return topic_presence(text, topic) is not None")]),

    # ═════════ TT — the title check still has no floor of its own ═══════════
    ("TT1", "under",
     "the title check stops refusing anything — the 2026-08-05 notebook name "
     "'Golden Retriever Health, Breeding, and Ownership Evidence' is written "
     "out as the run's title again",
     [(TT_ACCEPT, '    if True:\n        return "accept"')]),
    ("TT2", "over",
     "an unguardable topic makes the title check REFUSE instead of accept, so "
     "a perfectly good bland topic loses its generated title on every run",
     [(TT_ACCEPT, '    if topic_presence(_t, topic) is True:\n'
                  '        return "accept"')]),

    # ═════════ B — the brief's verdict ══════════════════════════════════════
    ("B1", "over",
     "the brief's bar drops to nothing, so a 40-character streaming stub is "
     "judged — a document with far too few chances to name its subject for a "
     "zero to mean anything",
     [(B_CONST, "_BRIEF_TOPIC_MIN_CHARS = 1")]),
    ("B2", "under",
     "⛔⛔ the bar drifts ABOVE the smallest brief ever measured (46,183), so "
     "the check reports healthy and looks at nothing. This is the failure the "
     "stale '2-5k chars' comment would have produced if anyone believed it",
     [(B_CONST, "_BRIEF_TOPIC_MIN_CHARS = 50_000")]),
    ("B3", "under",
     "a stub reads as ACCEPTED rather than unjudged, so 'we checked and it is "
     "fine' is said about a document nothing looked at",
     [(B_FLOOR, "    if False:")]),
    ("B4", "under",
     "⛔⛔⛔ AN UNGUARDABLE TOPIC CONDEMNS THE BRIEF. Every bland topic now "
     "raises a card accusing a perfectly good brief of being about something "
     "else, on every run",
     [(B_NONE, '    if _seen is None:\n        return "off_topic"')]),
    ("B5", "under",
     "the brief verdict never fires — back to the state this step exists to "
     "end, where nothing has ever read the document all three agents work from",
     [(B_PICK, '    return "accept"')]),
    ("B6", "over",
     "the verdict is inverted: a brief about the topic is refused and a brief "
     "about something else is accepted",
     [(B_PICK, '    return "off_topic" if _seen else "accept"')]),
    ("B7", "over",
     "whitespace buys length, so a 200-character stub padded with blank lines "
     "clears the bar and gets judged",
     [(B_STRIP, '    _b = (brief or "")')]),

    # ═════════ G — the gate's consequences ══════════════════════════════════
    ("G1", "under",
     "the gate never acts on an off-topic verdict — the check runs, decides, "
     "and tells nobody",
     [(G_GATE, "    if True:")]),
    ("G2", "over",
     "⛔⛔ THE HANG. The retry budget check goes, so a card with no Retry "
     "button still waits on the decision bus for an answer the user has no way "
     "to give. Phase 1 parks for twenty-four hours",
     [(G_BUDGET, "    if False:")]),
    ("G3", "under",
     "the card never offers Retry, so the only remedy for a wrong brief is to "
     "accept it",
     [(G_CANRETRY, '               agent="chatgpt",\n'
                   "               can_retry=False)")]),
    ("G4", "under",
     "Retry stops meaning retry: the user asks for a new brief and gets the "
     "old one",
     [(G_RETRY, '    log(f"Phase 1 brief-topic decision: {decision}")\n'
                '    if decision == "stop":\n'
                '        return "stop"\n'
                "    if False:")]),
    ("G5", "under",
     "Stop is ignored — the run carries on after the user ended it",
     [(G_STOP, '    if decision == "stop":\n        return "keep"')]),
    ("G6", "over",
     "⛔ THE LOOP. Keeping the brief becomes retrying it, so a user who says "
     "'this is fine' regenerates until the budget is spent",
     [(G_KEEP, "    # has looked at the brief and kept it.\n"
               '    return "retry"')]),
    ("G7", "under",
     "the abstain goes silent, so 'nothing could be judged' reads in the log "
     "exactly like 'the brief is about the topic'",
     [(G_SAYS, "        if False:")]),
    ("G8", "over",
     "an empty brief is no longer short-circuited, so `len(None)` raises inside "
     "phase 1 on every run where the extraction came back with nothing",
     [(G_EMPTY, "    if False:\n"
                '        return "keep"')]),
    ("G9", "under",
     "the phase-1 verdict is recorded under a name of its own, so it stops "
     "appearing beside every other wrong-document verdict the pipeline counts",
     [(G_EMIT, '        emit_event("brief_off_topic", phase=1, agent="chatgpt",')]),

    # ═════════ W — the second witness ═══════════════════════════════════════
    ("W1", "under",
     "⛔⛔ the witness becomes the SOURCE URL LIST, so a hostname that happens "
     "to contain a topic word counts as the agent having said something about "
     "it — a tracking parameter would corroborate",
     [(W_KEYS, '    for _key in ("source_urls",):')]),
    ("W2", "over",
     "one scraped line is enough to corroborate, so a leg that barely started "
     "can convict itself",
     [(W_CONST, "_WITNESS_MIN_CHARS = 1")]),
    ("W3", "under",
     "no realistic panel ever clears the bar, so the second opinion abstains "
     "on every run and the whole step is decorative",
     [(W_CONST, "_WITNESS_MIN_CHARS = 100_000")]),
    ("W4", "over",
     "whitespace buys a witness, so a panel that scraped nothing but blank "
     "lines is treated as having spoken",
     [(W_STRIP, '    _w = (witness or "")')]),

    # ═════════ S — the second opinion's verdicts ════════════════════════════
    ("S1", "under",
     "⛔⛔⛔ an unguardable topic goes straight to a corroborated drift, so "
     "every bland-topic run accuses its own agents",
     [(S_NONE, "    if _seen_in_report is None:\n"
               '        return "drift_corroborated"')]),
    ("S2", "under",
     "the report's own verdict is inverted, so a leg that named the subject is "
     "the one investigated",
     [(S_AGREE, "    if not _seen_in_report:\n"
                '        return "agree"')]),
    ("S3", "over",
     "⛔⛔ THE TWO WITNESSES STOP BEING DISTINGUISHED. An agent whose own panel "
     "proves it researched the right subject is accused of drift, and the "
     "extraction fault it actually had is never named",
     [(S_SPLIT, '    return "drift_corroborated"')]),
    ("S4", "under",
     "every disagreement is blamed on the extraction, so a genuine drift with "
     "two witnesses against it is never reported",
     [(S_SPLIT, '    return "extraction_suspect"')]),

    # ═════════ R — the reporting ════════════════════════════════════════════
    ("R1", "under",
     "⛔ the once-only guard goes, and the sweep runs TWICE — every corroborated "
     "drift raises two identical cards",
     [(R_ONCE, "            if True:")]),
    ("R2", "under",
     "the sweep stops consulting the second witness at all: every report the "
     "20,000-character floor cannot judge goes back to being unjudged",
     [(R_CALL, '                r["topic_second_opinion"] = "agree"')]),
    ("R3", "over",
     "a suspect EXTRACTION raises the same card as a corroborated drift, so "
     "the run accuses an agent that did the right work",
     [(R_LOUD, '    if verdict in ("drift_corroborated", "extraction_suspect"):')]),
    ("R4", "under",
     "all three agents share one card id, so the second and third findings "
     "overwrite the first and only one agent is ever named",
     [(R_ALERT, '                actions=[], alert_id="phase2_second_opinion",')]),

    # ═════════ H — the handoff honours the rejection ════════════════════════
    ("H1", "under",
     "the rejected leg's report FILE goes to NotebookLM again, which is what "
     "the sweep's own log line has always claimed does not happen",
     [(H_DROP, "        if False:")]),
    ("H2", "under",
     "⛔⛔ the drop is not remembered, so the Flow-B fallback scan finds the "
     "refused file on disk one directory listing later and uploads it anyway. "
     "This is not hypothetical — it is what the first cut of this fix did",
     [(H_REMEMBER, "            pass")]),
    ("H3", "over",
     "the fallback scan refuses everything, so Flow B — the user's own uploaded "
     "sources, with no agent running — hands NotebookLM nothing at all",
     [(H_SCAN, "                if True:")]),

    # ═════════ D — the call site's dispatch ═════════════════════════════════
    ("D1", "over",
     "⛔ THE INFINITE LOOP. The retry recursion forwards the attempt count "
     "unchanged, so the budget never runs down and a persistently off-topic "
     "brief regenerates forever",
     [(D_RETRY, '    if _bt_action == "retry":\n'
                "        return await run_phase1(browser, cua_client, topic, pdf_paths,\n"
                "                                verbose=verbose, feedback=feedback,\n"
                "                                _retry_count=_retry_count)")]),
    ("D2", "under",
     "a Stop verdict no longer ends the phase — the run continues with the "
     "brief the user just stopped it over",
     [(D_STOP, '    if False:\n        return None')]),
    ("D3", "under",
     "⛔⛔ THE CIRCULARITY. The brief is handed in as its own topic, so the "
     "check asks whether a string contains a slice of itself. It passes on "
     "every run and guards nothing — the exact defect this step exists to end",
     [(D_CALL, "    _bt_action = await brief_topic_gate(brief_text, brief_text,")]),
]


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
    kfilter = None if unfiltered else MINE
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
    for mid, direction, why, edits in MUTANTS:
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
            faults.append((mid, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    measured = len(MUTANTS) - len(faults)
    scope = " [whole selection]" if unfiltered else " [own guards]"
    print(f"\n{measured - len(survivors)}/{measured} killed ({over} over-corrections){scope}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
