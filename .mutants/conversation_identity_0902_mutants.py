"""Mutation harness — stretch 7.5 step 3, identity by content (2026-09-02).

⛔⛔ WHAT THIS CODE DECIDES. Whether a healthy research leg is killed mid-run.
The check it replaces decoded a creation time out of the conversation URL and
compared it to when this run started — THIS machine's clock against OpenAI's,
with 120 seconds of slack — and it has been repaired twice after near-misses:
a mid-run settings write that moved the run's own start time forward
(2026-08-05), and a `/c/WEB:<uuid>` id that could not be dated and so failed
CLOSED, killing a healthy leg SEVEN SECONDS AFTER SEND on every poll tick
(2026-08-27). The per-tick sweep fires sixty-odd times in a half-hour run, so a
check that is one percent wrong per tick is not one percent wrong per run.

⭐⭐ THE SHARPEST MUTANTS HERE — every one of them re-creates a shipped defect:
  C1/C2/V1 — an ABSTAIN becomes a REFUSAL. "I cannot tell" coming out as
             "somebody else's" is precisely the 2026-08-27 kill, and these put
             it back in three different places.
  S2       — the first-turn read is cached per PAGE instead of per URL. The
             obvious optimisation, and it freezes the answer from BEFORE a
             drift, so the one thing this sweep exists to catch becomes the one
             thing it cannot see. Nearly shipped.
  R1       — the reader falls back to the page's own text. On a FRESH chat there
             is no user turn, so it would return the page chrome and the
             sidebar's list of the person's OTHER conversations — and the
             pre-send gate would read that as a stranger's thread and refuse a
             healthy send. The sidebar would literally be the evidence.
  F1       — the shared "# Research Brief" header is kept in the fingerprint, so
             every run matches every other run this product has ever done.
  O1       — content gains the power to CONDEMN at the landing site, thirty
             seconds after Send, when the turn may not have rendered yet.
  B1       — a mid-run FOLLOW-UP replaces the fingerprint, so a
             resume-with-added-input makes the run stop recognising its own tab.
  L1       — a bare composer reads as a live conversation. Being in A
             conversation read as being in OURS is the 2026-08-05 incident.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
The filtered selection is proven to cover EVERY test in the file this step owns
before a single mutant is applied.

    .venv/bin/python .mutants/conversation_identity_0902_mutants.py
    .venv/bin/python .mutants/conversation_identity_0902_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ⚠ `tests/test_chatgpt_row_scope_0805.py` IS DELIBERATELY ABSENT, and it is
# the file that drives the refusal this step rewrote. It takes 50 SECONDS —
# five pre-existing tests in it sleep for real — which at two runs per mutant
# would be forty minutes of wall clock to measure twenty-four mutants. The
# fix was not to drop the coverage but to move it: this step's own file now
# drives `_refuse_foreign_chatgpt_tab` directly, in three seconds, so P1 and
# P2 are killed by guards this step owns rather than by a slow neighbour.
# ⛔ The row-scope suite is still run in full by the ordinary suite pass.
SUITES = ("tests/test_conversation_identity_by_content_0902.py "
          "tests/test_drift_review_0805.py "
          "tests/test_chatgpt_conversation_identity.py "
          "tests/test_chatgpt_landing_0827.py")

MINE = ("fingerprint or holds_brief or verdict or abstain or ABSTAIN or "
        "identity or conversation or foreign or sweep or drift or DRIFT or "
        "first_user_message or live_conversation or liveness or override or "
        "landing or paste or platform or polling or dropped or leg or "
        "boundary or ratio or template or token or undatable or UNDATABLE or "
        "unreadable or read_is_not_repeated or brief")

OWNED_FILES = ("tests/test_conversation_identity_by_content_0902.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

F_HEADER = ('    if low.startswith("# research brief"):\n'
            '        body = body.split("\\n", 1)[1] if "\\n" in body else ""')
F_FLOOR = "    return out if len(out) >= _BRIEF_FINGERPRINT_MIN_TOKENS else []"
F_DEDUP = "        if t in seen:\n            continue\n        seen.add(t)"
F_MINLEN = "_BRIEF_TOKEN_MIN_LEN = 4"
F_CAP = "        if len(out) >= _BRIEF_FINGERPRINT_TOKENS:\n            break"
C_NOFP = "    if not fingerprint:\n        return None"
C_FLOOR = "    if len(text) < _CONVO_TEXT_MIN_CHARS:\n        return None"
C_WB = '    hits = sum(1 for t in fingerprint if re.search(rf"\\b{re.escape(t)}\\b", text))'
C_RATIO = "    return (hits / len(fingerprint)) >= _BRIEF_MATCH_RATIO"
C_CONST = "_BRIEF_MATCH_RATIO = 0.6"
V_NONE = '    if held is None:\n        return "unknown"'
V_PICK = '    return "ours" if held else "foreign"'
R_EVAL = '            " return (n && n.innerText || \'\').slice(0, cap); }", cap)) or ""'
S_NOFP = ("        if not fingerprint:\n"
          "            continue          # nothing to compare against — see the docstring")
S_CACHE = ('        cached_url, cached_text = p.get("_ident_read") or ("", "")\n'
           "        if cached_url == url and url:")
S_VERDICT = ('        if chatgpt_identity_verdict(text, fingerprint, url) != "foreign":\n'
             "            continue")
P_GATE = ('    _fp = _runtime.brief_fingerprints.get("chatgpt") or []\n'
          "    _first = await read_chatgpt_first_user_message(page)\n"
          '    if chatgpt_identity_verdict(_first, _fp, url) != "foreign":\n'
          "        return False")
L_ID = ("    if _chatgpt_convo_id(url) is None:\n"
        "        return False\n"
        "    return not _chatgpt_tab_is_foreign(url)")
O_GUARD = '    if verdict != "foreign":\n        return verdict'
O_ISTRUE = ('    return "ours" if conversation_holds_brief(convo_text, fingerprint) '
            'is True else "foreign"')
B_ONCE = ("    if platform_key and platform_key not in _runtime.brief_fingerprints:\n"
          "        _fp = brief_fingerprint(brief_text)\n"
          "        if _fp:\n"
          "            _runtime.brief_fingerprints[platform_key] = _fp")

MUTANTS = [
    # ═════════ F — the fingerprint ══════════════════════════════════════════
    ("F1", "under",
     "⛔⛔ the shared \"# Research Brief\" header stays in the fingerprint, so every "
     "run this product has ever done matches every other one — a stranger's thread "
     "and last week's run both read as ours",
     [(F_HEADER, "    if False:\n        body = body")]),
    ("F2", "under",
     "the minimum-token floor goes, so a one-token fingerprint can condemn a leg on "
     "a single generic word",
     [(F_FLOOR, "    return out")]),
    ("F3", "over",
     "duplicates are kept, so a brief that repeats one word spends its whole "
     "fingerprint on it",
     [(F_DEDUP, "        if False:\n            continue\n        seen.add(t)")]),
    ("F4", "under",
     "one-character tokens count, so \"a\", \"of\" and \"the\" become the evidence "
     "that a conversation is ours",
     [(F_MINLEN, "_BRIEF_TOKEN_MIN_LEN = 1")]),
    ("F5", "over",
     "the fingerprint is unbounded, so a long brief demands a near-complete quote "
     "before it will recognise its own conversation",
     [(F_CAP, "        if False:\n            break")]),

    # ═════════ C — does the conversation hold our brief? ════════════════════
    ("C1", "under",
     "⛔⛔⛔ NO FINGERPRINT BECOMES A REFUSAL. This is the 2026-08-27 kill in a new "
     "place: 'I have nothing to compare against' coming out as 'this is somebody "
     "else's conversation'",
     [(C_NOFP, "    if not fingerprint:\n        return False")]),
    ("C2", "under",
     "⛔⛔⛔ AN UNREADABLE CONVERSATION BECOMES A REFUSAL — a tab mid-navigation, a "
     "slow render or a markup change would each kill a healthy leg",
     [(C_FLOOR, "    if len(text) < _CONVO_TEXT_MIN_CHARS:\n        return False")]),
    ("C3", "over",
     "matching goes back to substring, so \"transmonitor\" satisfies \"transmon\" and "
     "a stranger's thread can pass on coincidence",
     [(C_WB, "    hits = sum(1 for t in fingerprint if t in text)")]),
    ("C4", "under",
     "the ratio boundary becomes exclusive, so a conversation matching exactly the "
     "required share is refused",
     [(C_RATIO, "    return (hits / len(fingerprint)) > _BRIEF_MATCH_RATIO")]),
    ("C5", "over",
     "the match threshold collapses, so one incidental word in a stranger's thread "
     "makes it ours",
     [(C_CONST, "_BRIEF_MATCH_RATIO = 0.1")]),

    # ═════════ V — the verdict ══════════════════════════════════════════════
    ("V1", "under",
     "⛔⛔⛔ ABSTAIN BECOMES CONDEMNATION AT THE VERDICT ITSELF. Every unanswerable "
     "case in the whole step now costs a leg",
     [(V_NONE, '    if held is None:\n        return "foreign"')]),
    ("V2", "under",
     "the verdict is inverted, so our own conversation is refused and a stranger's "
     "is accepted",
     [(V_PICK, '    return "foreign" if held else "ours"')]),

    # ═════════ R — the cheap read ═══════════════════════════════════════════
    ("R1", "under",
     "⛔⛔ THE BODY-TEXT FALLBACK RETURNS. On a fresh chat there is no user turn, so "
     "this reads the page chrome and the sidebar's list of the person's OTHER "
     "conversations — and the pre-send gate refuses a healthy send on it",
     [(R_EVAL, '            " return ((n && n.innerText) || document.body.innerText '
               "|| '').slice(0, cap); }\", cap)) or \"\"")]),

    # ═════════ S — the per-tick sweep ═══════════════════════════════════════
    ("S1", "under",
     "⛔⛔ a run with no fingerprint — every RESUMED run — starts condemning legs "
     "again instead of abstaining",
     [(S_NOFP, "        if False:\n            continue")]),
    ("S2", "under",
     "⛔⛔⛔ THE READ IS CACHED PER PAGE INSTEAD OF PER URL. The obvious "
     "optimisation, and it freezes the answer from BEFORE the drift — so the one "
     "thing this sweep exists to catch becomes the one thing it cannot see",
     [(S_CACHE, '        cached_url, cached_text = p.get("_ident_read") or ("", "")\n'
                "        if cached_text:")]),
    ("S3", "under",
     "⛔⛔ the sweep drops anything that is not positively OURS, so every abstain — "
     "an unread tab, a missing fingerprint — becomes a dead leg",
     [(S_VERDICT, '        if chatgpt_identity_verdict(text, fingerprint, url) == "ours":\n'
                  "            continue")]),

    # ═════════ P — the pre-send and setup-failure gate ══════════════════════
    ("P1", "under",
     "⛔⛔ the gate goes back to dating the address, so an id the platform changed "
     "the format of refuses a healthy send again",
     [(P_GATE, "    if not _chatgpt_tab_is_foreign(url):\n        return False")]),
    ("P2", "under",
     "the gate refuses anything not positively ours, so a FRESH chat — which has no "
     "user turn at all — is refused, and no send ever happens",
     [(P_GATE, '    _fp = _runtime.brief_fingerprints.get("chatgpt") or []\n'
               "    _first = await read_chatgpt_first_user_message(page)\n"
               '    if chatgpt_identity_verdict(_first, _fp, url) == "ours":\n'
               "        return False")]),

    # ═════════ L — the two liveness sites ═══════════════════════════════════
    ("L1", "under",
     "⛔⛔ a bare composer reads as a live conversation. Being in A conversation "
     "read as being in OURS is the 2026-08-05 incident itself",
     [(L_ID, "    return not _chatgpt_tab_is_foreign(url)")]),
    ("L2", "under",
     "⛔⛔ the liveness sites go back to the pre-08-27 copy, so an undatable id "
     "reads as a dead page and a healthy leg is logged as somebody else's",
     [(L_ID, "    if _chatgpt_convo_id(url) is None:\n"
             "        return False\n"
             "    return _chatgpt_conversation_is_ours(url)")]),

    # ═════════ O — the landing override ═════════════════════════════════════
    ("O1", "under",
     "⛔⛔⛔ CONTENT GAINS THE POWER TO CONDEMN at the landing site — thirty seconds "
     "after Send, when the turn may not have rendered yet",
     [(O_GUARD, "    if False:\n        return verdict")]),
    ("O2", "under",
     "the override accepts an ABSTAIN as proof, so a conversation nobody could read "
     "overturns a verdict that was correct",
     [(O_ISTRUE, '    return "ours" if conversation_holds_brief(convo_text, '
                 'fingerprint) is not False else "foreign"')]),

    # ═════════ B — recording the fingerprint ════════════════════════════════
    ("B1", "under",
     "⛔⛔ a mid-run FOLLOW-UP replaces the fingerprint, so the run starts "
     "identifying its own tab by the newest thing typed into it and a "
     "resume-with-added-input makes it stop recognising the conversation it is in",
     [(B_ONCE, "    if platform_key:\n"
               "        _fp = brief_fingerprint(brief_text)\n"
               "        if _fp:\n"
               "            _runtime.brief_fingerprints[platform_key] = _fp")]),
    ("B2", "under",
     "nothing is recorded at all, so every identity question in the step abstains "
     "forever and the check has no teeth anywhere",
     [(B_ONCE, "    if False:\n"
               "        _fp = brief_fingerprint(brief_text)\n"
               "        if _fp:\n"
               "            _runtime.brief_fingerprints[platform_key] = _fp")]),
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
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
