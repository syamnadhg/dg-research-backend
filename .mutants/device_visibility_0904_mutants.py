"""7.7B — who can FIND this computer: the pairing question and `--visibility`.

⛔⛔ AN EMPTY READ IS NOT "PRIVATE", and V1 is that mutant.
`_fetch_device_meta_rest` returns `{}` for a network failure, an expired token
and a document with no field alike. Absent-means-private is right about the
document and wrong about the failure, and only one direction matters: telling
somebody their machine is hidden when it is listed is the answer that lets them
believe they turned discovery off.

⛔⛔ THE PAIRING ANSWER'S DEFAULT IS THE WHOLE SAFETY MARGIN, and B1 is that one.
`_ask_yes_no` returns the DEFAULT after three unreadable answers while the
EOFError branch sets its own value — on the On-Startup question above, whose
default is True, those two disagree. False here is what makes both roads lead to
private, so a scripted pair cannot publish a machine because of noise in a pipe.

⭐ THE OTHERS WORTH READING:
  B3 — the cancel path becomes a bare `return`. This function is annotated
       `-> None` and lies: `cmd_pair_v2` reads the result as
       `pair_completed = bool(...)` and reverts the whole pair on a falsy one.
       None is falsy, so this mutant is RIGHT BY ACCIDENT — and the guard exists
       because the next stage copied from it will not be.
  B4 — two PATCHes instead of one. The rule is `hasOnly()`, which refuses the
       WHOLE update when a key is off-list, so splitting them means one answer
       can be recorded and the other silently lost.
  B5 — the visibility value goes out as a bool. `_pair_patch_device` maps that to
       `booleanValue`, the rules refuse it, and the client narrows it to private.
  B10 — the confirmation moves back ABOVE the write and the write's result is
       thrown away. Cross-verify caught that shape in the first version of this
       block: the tick stood through a network failure, a dead token and a rules
       refusal alike, and `visibility` has NO second writer in the pair flow, so
       the answer was lost for good while the screen said it was saved.
  V6 — the refusal goes back to ASSERTING a state. Two of the four ways
       `_pair_patch_device` returns False happen after the request went out, so
       "Nothing changed. It is still: Private" can be printed over a machine
       that is in fact listed.
  C1 — the manual value check goes, so `superresearch --visibility "my topic"`
       binds the topic to the flag and the run does nothing, quietly. argparse
       cannot express "optional value, but only these two words".
  C5 — the help row goes. `add_help=False` and nothing calls `format_help`, so
       every `help=` string in this file is text no user can reach —
       `run_commands_help` is the only discovery surface there is, which is how
       --send-logs, --update and --uninstall all shipped undocumented.
  O1 — refusing to publish an unsupervised machine, invented as a safety rail.
       It is not one: whether a computer auto-starts has nothing to do with
       whether people may ask to use it, and the refusal would be silent.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/device_visibility_0904_mutants.py
  .venv/bin/python .mutants/device_visibility_0904_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_visibility_0904.py "
          "tests/test_yes_no_prompts_0817.py")

MINE = ("unpaired_machine or failed_read or reports_public or reports_private or "
        "exact_word_public or never_writes or writes_exactly or already_set or "
        "absent_field_still or refused_write or never_a_boolean or "
        "dropped_topic or no_notice or "
        "REFUSED_not_swallowed or unknown_word or bare_flag or "
        "topic_alongside or help_screen or help_row or "
        "pairing_question or ONE_patch or cancel_returns or stage_count or "
        "unreadable_stdin or WRITTEN_before_it_is_confirmed or "
        "lost_write_is_reported or names_the_command_that_changes or "
        "call_site_states_its_default or prompt_kept_its_original_default or "
        "yn_hint_in_the_file")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_visibility_0904.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The pairing question, exactly as shipped.
ASK = ('        discoverable = await _ask_yes_no(\n'
       '            "Let other people find this computer and ask to use it?",\n'
       '            default=False,\n'
       '        )')
#: The single Stage-2 PATCH carrying both of the stage's answers, whose result
#: the block now BRANCHES ON — cross-verify caught the first version printing
#: the confirmation first and throwing the bool away.
PATCH = ('        saved = _pair_patch_device(device_id_for_progress, {\n'
         '            "supervised": bool(enable_on_startup),\n'
         '            "visibility": "public" if discoverable else "private",\n'
         '        })')
#: The read-failure refusal in `run_visibility`.
READ_GUARD = ('    if not meta:\n'
              '        print(f"  {_c(_WARN, \'⚠\')}  Could not read this computer\'s settings just now.")')
#: How the current state is derived from the document.
CURRENT = '    current = "public" if meta.get("visibility") == "public" else "private"'
#: The manual value check in `main`.
VALIDATE = ('        if args.visibility != _VISIBILITY_SHOW and args.visibility not in _VISIBILITY_VALUES:')

MUTANTS = [
    # ═════════ B — pair Stage 2 ══════════════════════════════════════════════
    ("B1", "under",
     "⛔⛔ THE DEFAULT FLIPS TO YES. An unattended pair — piped stdin, a scripted "
     "install, three unreadable answers — then PUBLISHES the machine, because "
     "`_ask_yes_no` hands back the default rather than raising. The one answer "
     "nobody chose becomes the permissive one",
     [(ASK, ASK.replace("default=False", "default=True"))]),
    ("B2", "under",
     "⛔ the question builds its own `[y/N]` hint. The reader renders the hint "
     "from `default=`, so a hand-written one is a second source that can drift "
     "from the parse — and it would drift the moment the default changed",
     [(ASK, ASK.replace(
         '"Let other people find this computer and ask to use it?"',
         '"Let other people find this computer and ask to use it? [y/N]"'))]),
    ("B3", "under",
     "⛔⛔ the cancel path becomes a bare `return`. This function is annotated "
     "`-> None` and lies — `cmd_pair_v2` reads its result as "
     "`pair_completed = bool(...)` and reverts the entire pair on a falsy one. "
     "None IS falsy, so the mutant behaves correctly today and stops being "
     "correct the moment the block is copied into a stage that must not cancel",
     [('        log("Pairing cancelled by user (Stage 2 — discoverability)", "INFO")\n'
       '        return False',
       '        log("Pairing cancelled by user (Stage 2 — discoverability)", "INFO")\n'
       '        return')]),
    ("B4", "under",
     "⛔⛔ the two Stage-2 answers go out as two PATCHes. The rule is `hasOnly()`, "
     "which refuses the WHOLE update when one key is off-list — so one answer can "
     "be recorded and the other lost on its own, which is the failure that leaves "
     "a machine listed while the person believes they said no",
     [(PATCH,
       '        saved = _pair_patch_device(device_id_for_progress, {\n'
       '            "supervised": bool(enable_on_startup),\n'
       '        })\n'
       '        saved = _pair_patch_device(device_id_for_progress, {\n'
       '            "visibility": "public" if discoverable else "private",\n'
       '        })')]),
    ("B5", "under",
     "⛔⛔ the answer is written as a BOOLEAN. `_pair_patch_device` maps a bool to "
     "`booleanValue`, the rules refuse a non-string — taking `supervised` down "
     "with it, since hasOnly rejects the whole write — and any client that did "
     "read it narrows it to private",
     [(PATCH, PATCH.replace('"public" if discoverable else "private"',
                            "bool(discoverable)"))]),
    ("B6", "under",
     "⛔ the answer is inverted, so saying no publishes the machine and saying yes "
     "hides it — and the screen says the opposite of what was stored",
     [(PATCH, PATCH.replace('"public" if discoverable else "private"',
                            '"private" if discoverable else "public"'))]),
    ("B7", "under",
     "⛔⛔ the EOF branch publishes. No stdin is the scripted-install case, and it "
     "is the ONE path where nobody is present to see what was chosen",
     [('        # No stdin (piped / non-interactive) — stay private and continue,\n'
       '        # rather than aborting a scripted pair.\n'
       '        discoverable = False',
       '        # No stdin (piped / non-interactive) — stay private and continue,\n'
       '        # rather than aborting a scripted pair.\n'
       '        discoverable = True')]),
    ("B8", "under",
     "⛔ the question stops being asked and the machine is published outright — "
     "the shape a 'sensible default' refactor takes when the prompt is judged "
     "one question too many",
     [(ASK, "        discoverable = True")]),
    ("B9", "under",
     "⛔ the copy promises people can USE the machine. Answering yes grants nobody "
     "anything: the person still approves every request by hand and an approved "
     "person becomes an ordinary sharer. This asks for consent to something that "
     "does not happen",
     [("    print(f\"  {_c(_DIM, 'this machine and ask you for access. You approve each person.')}\")",
       "    print(f\"  {_c(_DIM, 'this machine, and anyone can then use it.')}\")")]),

    # ═════════ V — run_visibility ════════════════════════════════════════════
    ("V1", "under",
     "⛔⛔ THE FAILED READ IS REPORTED AS PRIVATE. `{}` comes back from a network "
     "blip and an expired token as well as from a document with no field, so a "
     "machine that IS listed is reported hidden — and the person believes they "
     "turned discovery off",
     [(READ_GUARD,
       '    if False:\n'
       '        print(f"  {_c(_WARN, \'⚠\')}  Could not read this computer\'s settings just now.")')]),
    ("V2", "under",
     "⛔⛔ `!= \"private\"` instead of `== \"public\"`, so a machine that was never "
     "asked — every machine paired before this wave, since nothing backfills the "
     "field — reports as PUBLIC",
     [(CURRENT,
       '    current = "private" if meta.get("visibility") == "private" else "public"')]),
    ("V3", "under",
     "⛔ the no-op shortcut goes, so `--visibility private` on an untouched "
     "machine PATCHes the field onto every document the flag was ever pointed at, "
     "for no change at all",
     [('    if value == current:\n'
       '        _describe(current)\n'
       '        print(f"  {_c(_DIM, \'     Already set — nothing to change.\')}")\n'
       '        print()\n'
       '        return 0\n\n', "")]),
    ("V4", "under",
     "⛔⛔ the shortcut inverts, so the write happens ONLY when it would change "
     "nothing — every real change is silently reported as already set",
     [("    if value == current:", "    if value != current:")]),
    ("V5", "under",
     "⛔ a refused write reports success. `--visibility public` then exits 0 "
     "having changed nothing, which is the answer a script reads",
     [('    if not _pair_patch_device(device_id, {"visibility": value}):',
       '    if not _pair_patch_device(device_id, {"visibility": value}) and False:')]),
    ("V6", "under",
     "⛔⛔ the refusal goes back to ASSERTING a state. `_pair_patch_device` returns "
     "False for four situations and only two of them prove the write did not land "
     "— a 10-second timeout and a 5xx both happen after the request went out, so "
     "Firestore may already have committed. Printing \"Nothing changed. It is "
     "still: Private\" over a listed machine is the one direction of that lie this "
     "command's own read guard refuses",
     [('        print(f"  {_c(_WARN, \'⚠\')}  Could not confirm that change.")\n'
       '        print(f"  {_c(_DIM, \'     It may not have been saved. Run this again with no value\')}")',
       '        print(f"  {_c(_WARN, \'⚠\')}  Could not save that. Nothing changed.")\n'
       '        print(f"  {_c(_DIM, \'     It is still:\')}")\n'
       '        _describe(current)\n'
       '        print(f"  {_c(_DIM, \'     ignored\')}")')]),
    ("V7", "under",
     "⛔ the unpaired check goes, so an unpaired machine is told its settings "
     "could not be read — a network story for a state that has nothing to do with "
     "the network, and no mention of --pair",
     [('    if not device_id:\n'
       '        print(f"  {_c(_WARN, \'⚠\')}  This computer is not paired yet.")',
       '    if False:\n'
       '        print(f"  {_c(_WARN, \'⚠\')}  This computer is not paired yet.")')]),
    ("V8", "under",
     "⛔ showing the setting WRITES it. A read-only question would start putting "
     "the field on documents that never had it, from a command whose whole "
     "contract is that it changes nothing",
     [('    if value == _VISIBILITY_SHOW:\n        _describe(current)',
       '    if value == _VISIBILITY_SHOW:\n'
       '        _pair_patch_device(device_id, {"visibility": current})\n'
       '        _describe(current)')]),
    ("V9", "under",
     "⛔ the dropped topic is swallowed silently. Five other flags in this parser "
     "are ignored without a word when passed with the wrong command; this is the "
     "one where silence looks exactly like the argparse misparse going unnoticed",
     [('    if ignored_topic:\n'
       '        print(f"  {_c(_DIM, \'Ignoring the topic — --visibility only changes a setting.\')}")',
       '    if False:\n'
       '        print(f"  {_c(_DIM, \'Ignoring the topic — --visibility only changes a setting.\')}")')]),

    # ═════════ C — the flag and the help screen ══════════════════════════════
    ("C1", "under",
     "⛔⛔ THE MISPARSE GOES UNCAUGHT. `topic` is `nargs=\"?\"` and so is this flag, "
     "so `superresearch --visibility \"my topic\"` binds the topic to the flag and "
     "leaves the positional empty. Without this check the command writes a "
     "nonsense value or does nothing, and says neither",
     [(VALIDATE, "        if False:")]),
    ("C2", "over",
     "⛔ a third word is accepted. Nothing else in the system understands it — the "
     "rules refuse it and the client narrows it to private — so the person's "
     "choice is stored as a state the app ignores",
     [('_VISIBILITY_VALUES = ("public", "private")',
       '_VISIBILITY_VALUES = ("public", "private", "unlisted")')]),
    ("C3", "under",
     "⛔ the command's exit code is thrown away, so a refused write, an unpaired "
     "machine and a successful change all exit 0 — and a script that checks",
     [("        raise SystemExit(run_visibility(args.visibility, ignored_topic=args.topic))",
       "        run_visibility(args.visibility, ignored_topic=args.topic)\n        return")]),
    ("C4", "under",
     "⛔ the dropped topic is never handed to the command, so nothing can report "
     "it — the same silence as V9, arriving from the caller's side",
     [("        raise SystemExit(run_visibility(args.visibility, ignored_topic=args.topic))",
       "        raise SystemExit(run_visibility(args.visibility))")]),
    ("C5", "under",
     "⛔⛔ the help row goes. `add_help=False` and nothing in this file calls "
     "`format_help` or `print_help`, so the `help=` string on the flag is text no "
     "user can reach — this row is the only discovery surface there is, and its "
     "absence is exactly how --send-logs, --update and --uninstall shipped "
     "undocumented",
     [('        ("python research.py --visibility [public|private]",\n'
       '         "Who can FIND this computer and ask to use it (bare = show current). '
       'You still approve everyone"),\n', "")]),
    ("C6", "under",
     "⛔ the row is authored with the real program name instead of the "
     "`python research.py` prefix `_section` rewrites, so it prints literally on "
     "an installed machine and never becomes `superresearch`",
     [('        ("python research.py --visibility [public|private]",',
       '        ("superresearch --visibility [public|private]",')]),
    ("C7", "under",
     "⛔ the help row describes the flag as granting USE. It is the sentence most "
     "people will ever read about this feature, and it would be describing a "
     "product that was deliberately not built",
     [('         "Who can FIND this computer and ask to use it (bare = show current). '
       'You still approve everyone"),',
       '         "Let anyone use this computer (bare = show current)"),')]),

    # ═════════ O — over-corrections ══════════════════════════════════════════
    ("B10", "under",
     "⛔⛔ the confirmation goes back ABOVE the write and the write's result is "
     "discarded — the shape cross-verify caught. The tick then stands through a "
     "network failure, a dead token and a rules refusal alike, and `visibility` "
     "has NO second writer in the pair flow, so the answer is lost for good while "
     "the screen says it was saved",
     [('    saved = False\n'
       '    if device_id_for_progress:\n'
       '        saved = _pair_patch_device(device_id_for_progress, {\n'
       '            "supervised": bool(enable_on_startup),\n'
       '            "visibility": "public" if discoverable else "private",\n'
       '        })',
       '    saved = True\n'
       '    if device_id_for_progress:\n'
       '        _pair_patch_device(device_id_for_progress, {\n'
       '            "supervised": bool(enable_on_startup),\n'
       '            "visibility": "public" if discoverable else "private",\n'
       '        })')]),
    ("B11", "under",
     "⛔ a lost write is announced as a success anyway, so the one path where the "
     "person's answer did not survive is the one path that says it did",
     [('    elif discoverable:', '    elif False:')]),
    ("B12", "under",
     "⛔ both branches name the same command again, so whoever said yes is handed a "
     "no-op and the way back is named nowhere in the pair session",
     [("        print(f\"  {_c(_DIM, '     Turn it off later with:')}  \"\n"
       "              f\"{_c(_BOLD, f'{_PROG} --visibility private')}\")",
       "        print(f\"  {_c(_DIM, '     Turn it off later with:')}  \"\n"
       "              f\"{_c(_BOLD, f'{_PROG} --visibility public')}\")")]),
    ("O1", "over",
     "⛔⛔ publishing is refused unless the machine auto-starts. It reads like a "
     "safety rail and is not one: whether a computer starts at login has nothing "
     "to do with whether people may ASK to use it, and the refusal is silent to "
     "anyone who did not read the code",
     [('    if not _pair_patch_device(device_id, {"visibility": value}):',
       '    if value == "public" and not meta.get("supervised"):\n'
       '        return 1\n'
       '    if not _pair_patch_device(device_id, {"visibility": value}):')]),
    ("O2", "over",
     "⛔ a refused write is retried three times. A `hasOnly` refusal is a rules "
     "decision, not a blip — re-sending the same PATCH cannot change the answer, "
     "and it makes the person wait for three of them before being told",
     [('    if not _pair_patch_device(device_id, {"visibility": value}):',
       '    _ok = any(_pair_patch_device(device_id, {"visibility": value}) for _ in range(3))\n'
       '    if not _ok:')]),
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
