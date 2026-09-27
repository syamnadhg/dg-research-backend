"""Mutation harness — wave 12, "Allow all" on the research computer (2026-09-26).

⛔⛔ WHAT THIS CODE DECIDES.
  A* — `_allow_all_of` and `run_visibility`: allow-all reads ON only on a PUBLIC
       computer (public by `_discovery_of`, either name) carrying a real `True`;
       ON is written as `{visibility: public, allowAll: true}` in one patch; the
       close goes out as `{visibility: private}` ALONE, then a best-effort clear
       only if the tick was there and only after the close landed; an opener
       undoes an old tick in the same patch; bare `--allow-all` only SHOWS,
       except straight after `--visibility public`; an allow-all write on an
       unreadable document is owed "Nothing was changed"; an empty patch never
       goes out.
  M* — `main`: exactly yes|no, refused by name; the flag typed without its
       dashes is "did you mean --allow-all?"; private + yes is refused; one
       dispatch serves both flags and hands the value over.
  S* — the screens: the help row, the conditional approval wording, the parser's
       help strings.
  P* — pairing is untouched: its one patch keeps exactly its two keys.

The mutants the owner's measurement named map onto these: A1 (not gated on
public), A2 (truthy), A3 (yes writes allowAll alone), A4 (the close carries
allowAll), A5 (a string), A6 (an opener leaves the tick), A7 (bare writes), A8
(the old "approve every person" line), M5 (private + yes not refused), A10 (the
literal `visibility` field instead of `_discovery_of`).

The older `--visibility` guards stay in device_visibility_0904 (re-anchored onto
this wave's lines) and the empty-read verdict's own pair in wave790 (W10/W11).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/wave12_allow_all_machine_mutants.py
  .venv/bin/python .mutants/wave12_allow_all_machine_mutants.py A4 M5
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

# ⛔ THE OLD `--visibility` PINS RUN TOO. This wave rewrote the write path they
# guard, so a mutant that breaks plain `--visibility public|private` must die
# here as well as on the new pins — the single-field writes they assert are
# exactly the "write what is written today" half of the spec.
SUITES = {
    RESEARCH: (ROOT, "tests/test_allow_all_0926.py tests/test_visibility_0904.py "
                     "tests/test_terminal_words_0916.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

#: The effective reader — public first, then a real True.
GATE = '    return meta.get("allowAll") is True and _discovery_of(meta) == "public"'
#: The bare flag's resolution.
BARE = '        allow_all = "yes" if value == "public" else None'
#: The ON patch.
ON_PATCH = '        patch = {"visibility": "public", "allowAll": True}'
#: The close.
CLOSE = '        patch = {"visibility": "private"} if current == "public" else {}'
#: The one write site.
WRITE = '    if patch and not _pair_patch_device(device_id, patch):'
#: The leftover clear after the close.
CLEAR = ('    if target == "private" and leftover:\n'
         '        _pair_patch_device(device_id, {"allowAll": False})\n')

MUTANTS = [
    # ═══ A — reading and writing the setting ═══════════════════════════════
    ("A1", RESEARCH, "⛔⛔ the reader is not gated on public, so an old writer's leftover "
     "tick on a PRIVATE computer reads ON — and the next plain `--visibility public` "
     "brings the instant door back",
     [(GATE, '    return meta.get("allowAll") is True')]),
    ("A2", RESEARCH, "⛔ a truthy value reads ON — the STRING \"false\" opens the "
     "computer to every signed-in stranger",
     [(GATE, '    return bool(meta.get("allowAll")) and _discovery_of(meta) == "public"')]),
    ("A3", RESEARCH, "⛔⛔ `--allow-all yes` on a private computer writes `allowAll` "
     "alone — the computer stays hidden, nobody can find it to ask, while the screen "
     "says Allow all is on",
     [(ON_PATCH, '        patch = {"allowAll": True}')]),
    ("A4", RESEARCH, "⛔⛔ the close carries `allowAll` too, so a rules deploy that "
     "lags the key refuses the WHOLE close and the owner cannot hide the computer "
     "from the terminal",
     [(CLOSE, '        patch = {"visibility": "private", "allowAll": False} '
              'if current == "public" else {}')]),
    ("A5", RESEARCH, "⛔ the flag goes out as a string — the rules admit only a bool "
     "and `hasOnly` drops the `visibility` riding with it",
     [(ON_PATCH, '        patch = {"visibility": "public", "allowAll": "true"}')]),
    ("A6", RESEARCH, "⛔⛔ re-opening a private computer leaves an old writer's "
     "`allowAll: true` in place, so a plain `--visibility public` brings back an "
     "instant door nobody asked for this time",
     [('        patch = {"visibility": "public"}\n'
       '        if leftover:\n'
       '            patch["allowAll"] = False\n',
       '        patch = {"visibility": "public"}\n')]),
    ("A7", RESEARCH, "⛔⛔ a bare `--allow-all` means yes everywhere — typing it to "
     "CHECK makes the computer public and instantly joinable",
     [(BARE, '        allow_all = "yes"')]),
    ("A8", RESEARCH, "⛔⛔ the status screen keeps \"You still approve every person "
     "yourself.\" on a computer that lets anyone straight in",
     [("            if allow:\n"
       "                print(f\"  {_c(_BOLD, '     Allow all: on — anyone who asks joins at once')}\")\n"
       "            else:\n"
       "                print(f\"  {_c(_DIM, '     Allow all: off — you approve each person')}\")",
       "            print(f\"  {_c(_DIM, '     You still approve every person yourself.')}\")")]),
    ("A10", RESEARCH, "⛔⛔ the reader compares the literal `visibility` field, so the "
     "day the rename drops it every allow-all computer reads closed",
     [(GATE, '    return meta.get("allowAll") is True and meta.get("visibility") == "public"')]),
    ("A11", RESEARCH, "⛔⛔ `--allow-all yes` on an unreadable document is answered as "
     "a status question — the person is never told it was not applied",
     [("        if value != _VISIBILITY_SHOW or allow_all is not None:",
       "        if value != _VISIBILITY_SHOW:")]),
    ("A12", RESEARCH, "⛔ the owner's one-step form `--visibility public --allow-all` "
     "only makes it public",
     [(BARE, '        allow_all = None')]),
    ("A13", RESEARCH, "⛔ going private leaves the tick behind for the next plain "
     "'make it public' from an old writer",
     [(CLEAR, "")]),
    ("A14", RESEARCH, "⛔ every close sends a second patch, tick or no tick — a write "
     "the rules may refuse, on documents that never had the field",
     [('    if target == "private" and leftover:', '    if target == "private":')]),
    ("A15", RESEARCH, "⛔⛔ the tick is cleared BEFORE the close, so a close that could "
     "not be confirmed still changed something the screen never reports",
     [(WRITE, CLEAR + WRITE)]),
    ("A16", RESEARCH, "⛔⛔ `yes` outranks `private`, so if `main`'s refusal were lost, "
     "`--visibility private --allow-all yes` would OPEN the door instead of closing it",
     [('    if value in _VISIBILITY_VALUES:\n'
       '        target = value\n'
       '    elif allow_all == "yes":\n'
       '        target = "public"\n',
       '    if allow_all == "yes":\n'
       '        target = "public"\n'
       '    elif value in _VISIBILITY_VALUES:\n'
       '        target = value\n')]),
    ("A17", RESEARCH, "⛔ a flag-less `--visibility public` on an allow-all computer "
     "silently turns Allow all off",
     [('    want = (allow_all == "yes") if allow_all is not None else allow_now',
       '    want = (allow_all == "yes") if allow_all is not None else False')]),
    ("A18", RESEARCH, "⛔⛔ `--allow-all no` on a public allow-all computer writes "
     "nothing — the owner is told approval is back while anyone still joins at once",
     [('    else:\n        patch = {"allowAll": False}',
       '    else:\n        patch = {}')]),
    ("A19", RESEARCH, "⛔ the already-set shortcut goes: `--allow-all yes` rewrites a "
     "computer that is already on, and plain `--visibility public` on a public one "
     "writes `allowAll: false` onto it",
     [('    elif current == "public" and want == allow_now:\n        patch = {}\n', "")]),
    ("A20", RESEARCH, "⛔ closing an allow-all computer prints the turn-ON disclosure "
     "instead of saying the people who joined keep access",
     [('    if target == "private":\n        want = False',
       '    if target == "private":\n        pass')]),
    ("A21", RESEARCH, "⛔⛔ an EMPTY patch goes out — a Firestore PATCH with no update "
     "mask replaces the whole device document",
     [(WRITE, '    if not _pair_patch_device(device_id, patch):')]),
    ("A22", RESEARCH, "⛔ `--allow-all no` on a private computer says \"Already set\" "
     "instead of why it is off",
     [('        if target == "private" and allow_all == "no":', '        if False:')]),
    ("A23", RESEARCH, "⛔⛔ `--allow-all yes` alone is answered as a status question "
     "and never writes",
     [('    if value == _VISIBILITY_SHOW and allow_all is None:',
       '    if value == _VISIBILITY_SHOW:')]),
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair, cross-verify F6/F24): the sentence
    # moved into the constant `_ALLOW_ALL_SEES` (the canonical disclosure, which
    # gained "and what's running on it"), and this line prints it. Same defect —
    # the print gone. The wording itself is D3 in wave12_repair1_agent_mutants.
    ("A24", RESEARCH, "⛔ turning it on never says what a joiner gets — your AI "
     "accounts, your email, who else is on it",
     [("        print(f\"  {_c(_DIM, '     ' + _ALLOW_ALL_SEES)}\")\n", "")]),
    ("A25", RESEARCH, "⛔ turning it off never says everyone who joined keeps access, so "
     "'off' reads as 'they are gone'",
     [('    elif allow_now:\n', '    elif False:\n')]),
    ("A26", RESEARCH, "⛔ `--allow-all yes` on a computer that was already public claims "
     "to have made it public",
     [('        if current == "private":\n'
       "            print(f\"  {_c(_DIM, '     This made it public too",
       '        if True:\n'
       "            print(f\"  {_c(_DIM, '     This made it public too")]),
    ("A27", RESEARCH, "⛔ the status screen never names the allow-all commands",
     [('            ("python research.py --allow-all yes",\n'
       '             "let anyone who asks join at once (makes it public too)"),\n'
       '            ("python research.py --allow-all no", "approve each person yourself"),\n',
       "")]),
    ("A28", RESEARCH, "⛔⛔ every opener states `allowAll`, tick or no tick — plain "
     "`--visibility public` then depends on a rules deploy it never needed, and a "
     "lagging ruleset refuses the whole patch",
     [('        if leftover:\n            patch["allowAll"] = False',
       '        if True:\n            patch["allowAll"] = False')]),
    ("A29", RESEARCH, "⛔ the private status line grows \"Allow all: off — you approve "
     "each person\", which is not even true there: code holders join without asking",
     [("                  f\"{_c(_DIM, '— only people you give the access code to "
       "can ask.')}\")",
       "                  f\"{_c(_DIM, '— only people you give the access code to "
       "can ask.')}\")\n"
       "            print(f\"  {_c(_DIM, '     Allow all: off — you approve each "
       "person')}\")")]),

    # ═══ M — main: words, refusals, dispatch ═══════════════════════════════
    ("M1", RESEARCH, "⛔⛔ the word check goes: `--allow-all maybe` and a swallowed topic "
     "run the command instead of being refused by name",
     [("        if (args.allow_all is not None and args.allow_all != _ALLOW_ALL_SHOW\n"
       "                and args.allow_all not in _ALLOW_ALL_VALUES):",
       "        if False:")]),
    ("M2", RESEARCH, "⛔ `Yes` is read generously — the guess that opens a computer to "
     "strangers is the one that must never be guessed",
     [("                and args.allow_all not in _ALLOW_ALL_VALUES):",
       "                and args.allow_all.lower() not in _ALLOW_ALL_VALUES):")]),
    ("M3", RESEARCH, "⛔ `--visibility public allow-all` makes the computer public, "
     "drops the part asked for and offers to research 'allow-all'",
     [("        if (args.visibility is not None and args.topic and re.sub(",
       "        if (False and re.sub(")]),
    ("M4", RESEARCH, "⛔ only the undashed spelling is caught — 'allow-all' and 'allow "
     "all' slip through as topics",
     [('                r"[\\s_-]+", "", args.topic).lower() == _ALLOW_ALL_TOPIC_WORD):',
       '                r"_", "", args.topic).lower() == _ALLOW_ALL_TOPIC_WORD):')]),
    ("M5", RESEARCH, "⛔⛔ `--visibility private --allow-all yes` is not refused — a "
     "sentence that says two opposite things is acted on silently",
     [('        if _vis == "private" and args.allow_all == "yes":', '        if False:')]),
    ("M6", RESEARCH, "⛔ `--visibility private --allow-all no` (or bare) is refused too, "
     "though both agree with closing",
     [('        if _vis == "private" and args.allow_all == "yes":',
       '        if _vis == "private" and args.allow_all is not None:')]),
    ("M7", RESEARCH, "⛔⛔ `--allow-all` on its own never reaches the command — it falls "
     "through to the research path",
     [("    if args.visibility is not None or args.allow_all is not None:",
       "    if args.visibility is not None:")]),
    ("M8", RESEARCH, "⛔⛔ the value never reaches the command, so `--allow-all yes` "
     "prints the status and changes nothing",
     [("        raise SystemExit(run_visibility(_vis, allow_all=args.allow_all,",
       "        raise SystemExit(run_visibility(_vis, allow_all=None,")]),
    ("M9", RESEARCH, "⛔ `--allow-all` alone is refused by the --visibility word check, "
     "because no --visibility word was given",
     [("        _vis = _VISIBILITY_SHOW if args.visibility is None else args.visibility",
       "        _vis = args.visibility")]),
    ("M10", RESEARCH, "⛔ `--visibility allow-all` is refused as an unknown word and "
     "offered as a research TOPIC — the person meant the other flag",
     [('        if re.sub(r"[\\s_-]+", "", _vis).lower() == _ALLOW_ALL_TOPIC_WORD:',
       '        if False:')]),

    # ═══ S — what a person reads ═══════════════════════════════════════════
    ("S1", RESEARCH, "⛔⛔ the help row goes — `add_help=False`, so this screen is the "
     "only place the flag can be found",
     [('        ("python research.py --allow-all [yes|no]",\n'
       '         "Anyone who asks joins at once, no approval (yes also makes it public; '
       'bare = show current)"),\n', "")]),
    ("S2", RESEARCH, "⛔ the --visibility row still promises approval of everyone",
     [('You approve each person unless --allow-all is on"),',
       'You still approve everyone"),')]),
    ("S3", RESEARCH, "⛔ the parser's --visibility help still promises approval of everyone",
     [('             "You approve each person unless --allow-all is on. "\n', "")]),
    ("S4", RESEARCH, "⛔ the parser's --allow-all help says bare turns it on",
     [('"stays public). Bare --allow-all prints the current setting; straight "',
       '"stays public). Bare --allow-all turns it on; straight "')]),

    # ═══ P — pairing is untouched ══════════════════════════════════════════
    ("P1", RESEARCH, "⛔⛔ the pairing patch gains `allowAll` — a rules deploy lagging "
     "the wheel then refuses the whole patch and loses BOTH pairing answers",
     [('            "visibility": "public" if discoverable else "private",\n        })',
       '            "visibility": "public" if discoverable else "private",\n'
       '            "allowAll": False,\n        })')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-x",
             "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    print("baseline… ", end="", flush=True)
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
