"""STRETCH 7.5 STEP 6 (backend half) — the branch that could not succeed, the
mirror nobody read, the card that named the wrong failure, and the document that
described a gate no agent could ever pass.

⛔⛔ THE DOCUMENT WAS NOT STALE, IT WAS A TRAP, and that is what most of these
mutants are about. Its agent-completion section said a Phase 2 agent is done only
once a shareable link passes validation. The validator table holds three entries
and none of them is an agent, so it answers no for all three, always — restoring
the documented behaviour would ship a pipeline in which no agent ever completes.
A mutant that adds the missing validator entry is therefore not a typo; it is
somebody making the doc true the easy way.

⭐ THE SHARPEST ONES HERE:
  M2 — the CHECKPOINT write is removed instead of the delivery mirror. The two
       lines sat next to each other and looked identical; one was dead and the
       other is what renders a Research Brief row after a resume. Deleting the
       wrong one costs a real link on a real screen and nothing complains.
  B3 — the unconditional append is removed. That call, not the validated emit
       beside it, is what has been putting a pasted brief into the delivered
       document all along; removing the emit is safe ONLY because of it.
  C2 — the orphaned gate gains a caller. It is a blocking global pause, and the
       live path parks non-blockingly, so wiring it back freezes the round-robin
       on one agent's card.
  V1 — a `brief` validator appears, which is the obvious repair for the branch
       step 6 removed, and it would put somebody else's address back into the
       slot step 5 made mean "our own page".

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/tick_and_tidy_0903_mutants.py
  .venv/bin/python .mutants/tick_and_tidy_0903_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_tick_and_tidy_0903.py "
          "tests/test_doc_matches_code_0903.py")

MINE = ("validator or refused_anyway or dead_call or reaches_the_user or "
        "no_longer_promises or mirrored or checkpoint_write or declares_the_slot or "
        "report_is_missing or blames_a_link or diagnosis_agrees or "
        "ladder_named or ladder_describes or tick_comment or orphaned or "
        "outgrown or gate_reads_no_link or could_not_have_worked or "
        "states_the_gate or production_caller or live_decision or "
        "never_existed or belongs_to_phase_3 or retired_symbol or "
        "emitted_nowhere or is_emitted_and_no_others or carries_our_own or "
        "snapshots_are_different or names_the_helper or citation_survives or "
        "readd_one or extractors_are_gone")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_tick_and_tidy_0903.py",
               "tests/test_doc_matches_code_0903.py")

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
GATE = "    if n_chars > 0 and has_anchor and md_saved:"
VALIDATORS = '    "notebooklm": is_notebooklm_url,'
PASTE = "                        brief_url = _url\n                    elif _kind == \"notebook\" and not notebook_url:"
APPEND = "                    append_user_source_in_firestore(_kind, _url, _label, phase=3)"
CKPT = ("                save_checkpoint(queue_dir, 1, topic=topic, brief_url=_in_app_brief_url)\n"
        "                # \u26d4 2026-09-03, stretch 7.5 step 6 \u2014 THE DELIVERY MIRROR OF THIS")
CARD = '                                facts={"title": "Claude didn\'t finish its report",'
LADDER = "# \u2500\u2500 Per-Agent Extract + Record \u2500"
HARDFAIL = '                        p.setdefault("hf_timeouts", 0)'

MUTANTS = [
    # ═════════ V — making the document true the easy way ═════════════════════
    ("V1", "under",
     "\u26d4\u26d4 a `brief` validator appears, which is the obvious repair for the branch "
     "step 6 removed \u2014 and it puts somebody else's address back into the slot step 5 "
     "made mean \"the brief's page in OUR app\", recreating the two-meanings root cause",
     [(VALIDATORS, '    "brief":   lambda u: u.startswith("http"),\n' + VALIDATORS)]),

    # ═════════ B — the pasted brief ══════════════════════════════════════════
    ("B1", "under",
     "the call that can never succeed comes back, logging two warnings on every "
     "pasted brief for a slot write that is refused before it happens",
     [(PASTE, "                        brief_url = _url\n"
              "                        emit_validated_link(2, \"brief\", _url, _label or \"Research Brief\")\n"
              "                    elif _kind == \"notebook\" and not notebook_url:")]),
    ("B2", "over",
     "\u26d4 the removal goes further and drops the assignment too, so a user who pasted "
     "their own brief link loses it from the run \u2014 the over-correction, and the link "
     "was the user's own, which this stretch was explicitly told not to touch",
     [(PASTE, "                        pass\n"
              "                    elif _kind == \"notebook\" and not notebook_url:")]),
    ("B3", "under",
     "\u26d4\u26d4 the unconditional append goes. THIS is the call that has been putting a "
     "pasted brief into the delivered document all along; removing the validated emit "
     "beside it was safe only because this one runs first and always",
     [(APPEND, "                    pass")]),

    # ═════════ M — the two writes that looked identical ══════════════════════
    ("M1", "under",
     "the delivery mirror returns \u2014 an unread copy in a file returned verbatim by a "
     "local server that binds every interface with no auth",
     [(CKPT, CKPT + "\n                update_delivery(brief_url=_in_app_brief_url)")]),
    ("M2", "over",
     "\u26d4\u26d4 the CHECKPOINT write is removed instead. It sat one line from the dead "
     "mirror and looked the same; it is what renders the Research Brief row after a "
     "resume at phase 5, so the wrong deletion costs a real link and nothing complains",
     [(CKPT, "                # (checkpoint write removed)\n"
             "                # \u26d4 2026-09-03, stretch 7.5 step 6 \u2014 THE DELIVERY MIRROR OF THIS")]),

    # ═════════ C — what a person reads, and what a reader believes ═══════════
    ("C1", "under",
     "\u26d4\u26d4 the card blames a link fetch again, on a run whose report is simply "
     "missing \u2014 sending a person to look for a network fault that is not there",
     [(CARD, '                                facts={"title": "Couldn\'t get Claude\'s report link",')]),
    ("C2", "under",
     "\u26d4\u26d4 the orphaned gate gains a caller. It holds a GLOBAL pause while the live "
     "path parks non-blockingly, so one agent's card would freeze the round-robin for "
     "the other two \u2014 the behaviour the architecture doc described as current",
     [(HARDFAIL, "                        await wait_for_agent_decision(agent_key_hf, \"hard_fail\")\n" + HARDFAIL)]),

    # ═════════ G — the gate the document got backwards ═══════════════════════
    ("G1", "under",
     "\u26d4\u26d4 the completion gate starts consulting a link validator, which is what the "
     "architecture doc described \u2014 and since no agent has a validator entry, every "
     "agent stops completing on every run",
     [(GATE, "    if n_chars > 0 and has_anchor and md_saved and validate_link(agent_key, conversation_url):")]),
    ("G2", "under",
     "the Firestore write is dropped from the gate, so the app is told an agent is "
     "complete and then cannot find the document it was told about",
     [(GATE, "    if n_chars > 0 and has_anchor:")]),

    # ═════════ D — the comment that planted the landmine ═════════════════════
    ("D1", "under",
     "\u26d4\u26d4 the emission ladder's old header returns, naming a share step, a "
     "chat-URL fallback and two identifiers that exist nowhere else in the file. This "
     "sentence is why removing link extraction looked like it would leave all three "
     "agents spinning forever",
     [(LADDER, "# \u2500\u2500 Per-Agent Extract + Record (content-first, link-second) \u2500\n"
               "#   3. attempt public Share/Publish link\n"
               "#   4. emit link_extracted { url, verified, fallback? }\n"
               "#   Caller then does completed_set.add(agent) and clears extraction_in_progress.\n"
               "# \u2500\u2500 Per-Agent Extract + Record \u2500")]),
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
