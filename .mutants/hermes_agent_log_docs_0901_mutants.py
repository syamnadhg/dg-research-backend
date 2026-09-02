"""Mutation harness — the agent's own log, as an ASSISTANT sees it (2026-09-01).

⛔⛔ WHAT THIS CODE DECIDES. Whether the option to send the chat host's own log
EXISTS for anybody who does not already know it exists — and, once offered,
whether the second step that actually uploads it is ever taken.

⛔⛔ THE GAP THIS CLOSES WAS A CALLER GAP, NOT A CAPABILITY GAP. `--agent-log`
has been built, tested and mutated since stretch 4B (2026-08-26). Four guards in
the fork's suite pin its wording. Every one of them reads `sr.py`. Nothing read
the document — and in the fork the document is the ONLY route to the flag: that
client has no natural-language routing (44 `re.search` upstream, 0 in the fork)
and no directive block (11 upstream, 0 in the fork). So the flag, its branches
and its four guards were unreachable, and the four guards could not tell.

⭐⭐ THE SHARPEST MUTANTS HERE:
  F1c     — ⛔⛔ THE WORST ONE, AND CROSS-VERIFICATION FOUND IT. The flag comes
            off the OFFER line while the second step keeps it. The plan then
            prints "The log from the program running this chat is not included.",
            the person agrees to THAT, and the documented check-time command
            uploads it anyway — nothing anywhere cross-checks the check-time flag
            against the plan they agreed to. That is not a missing feature; it is
            a consent claim about a conversation that said the opposite.
  F1b     — the offer's code block goes and the prose stays. The first version of
            this wave's own guard read the whole SECTION for "--agent-log", which
            the second-step line satisfies alone, so this passed 7/7. F1 hid it by
            deleting the prose too, which made three other guards error out — a
            collateral kill dressed up as a guard that worked.
  F3      — the fork's second step is spelled upstream's way. `--status` does not
            exist on this parser; the documented command exits 2.
  B3/B12  — the backend row and bullet stop saying to pass the flag on
            `--confirm`. Measured by driving the client: without it there, a plain
            `--confirm` prints NEITHER the person's "goes up once the bundle
            lands" line NOR the assistant's follow-up command. The row's promise
            that "the client hands you" the command becomes false under the flow
            the same row prescribes.
  F7/B5   — the passage borrows the owner-only gate from the paragraph above it.
            Measured: there is NO ownership check on this one, anywhere. An
            assistant that inherits the gate withholds, on a rule that does not
            exist, something a person asked for.
  C1-C5   — the CLIENTS move underneath the documents. These prove the guards are
            pinned to the code rather than to a remembered fact.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ EVERY MUTANT IS SCORED AGAINST THIS WAVE'S OWN GUARDS, via `-k`. The first
version of this file ran the doc mutants against the whole suites and claimed
"nothing else in the tree reads these passages". That was measurably false:
`test_the_skill_tells_the_assistant_to_wait_for_a_real_yes` walks EVERY line
starting with `$SR send-logs`, so F3 went red on a pre-existing guard. A borrowed
kill is not evidence that the guard you just wrote works. Pass `--unfiltered` to
get the other number — whether the TREE catches it — deliberately as a separate
question. The full suites were measured green on their own: 6571 backend root,
1373 backend agent, 224 fork.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
One typo in the filter would have scored every mutant killed against zero tests.
`_pytest` separates that case out and it is raised as a fault; the baseline runs
filtered as well as unfiltered so a filter that matches nothing refuses the run.

⚠ TWO PROGRAMS, AND BOTH MUST BE GREEN. The backend agent's skill and the fork's
skill are separate documents with separate suites and separate virtualenvs; a
harness that ran one leg would report every mutant in the other as killed.

⭐ THE TREE IS CHECKED BACK BY CONTENT, NOT BY `git status`. This work is
uncommitted by design (the fork stages for a signing session), so a git-based
"came back clean" check would fire on every run and hide a real leftover mutant
in the noise. Each file is hashed before the loop and re-hashed after.

    .venv/bin/python .mutants/hermes_agent_log_docs_0901_mutants.py
    .venv/bin/python .mutants/hermes_agent_log_docs_0901_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT.parent / "dg-hermes-fleet"

# ⛔ The client suites ride along deliberately. The C-series changes real code, and
# a doc guard that noticed while the client's own tests went red would be reporting
# somebody else's kill as its own.
BE_SUITES = ("tests/test_send_logs_skill_0825.py "
             "tests/test_agent_log_out_0826.py "
             "tests/test_send_logs_cli_0825.py")
FORK_SUITES = "skills/tests/test_super_research_skill.py"

# ⭐ THE GUARDS THIS WAVE ADDED, and the only tests a score here is about.
# It leaks exactly one pre-existing test per leg — `test_the_document_does_not_
# hand_the_model_a_wait_to_quote`, which exists in BOTH files and reads only the
# cooldown copy. Measured, not assumed: no mutant here can reach it.
MINE = "the_document or the_table_routes or the_second_step_is_where"
MIN_SELECTED = 7

BE_SKILL = "agent/facade/skill/SKILL.md"
BE_SR = "agent/facade/skill/scripts/sr.py"
OURS = (BE_SKILL, BE_SR)

FORK_SKILL = "skills/super-research/SKILL.md"
FORK_SR = "skills/super-research/scripts/sr.py"
THEIRS = (FORK_SKILL, FORK_SR)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_INFLIGHT = Path(__file__).with_suffix(".inflight")

BE_BULLET = (
    "- **The agent's own log on THIS host** is a third thing and a third computer —\n"
    "  the program running this chat, not their Research Computer. `--agent-log`\n"
    "  asks for it on the bare command, so the plan names it. Unlike `--machine`\n"
    "  there is **no ownership gate**, so no refusal will stop you: offer it only\n"
    "  when the problem is this chat reaching their computer at all. It covers that\n"
    "  file since it last rotated, not just this conversation, so it can reach back\n"
    "  further than the problem being reported. **It does not ride the send** — but\n"
    "  **pass it on `--confirm` too**: nothing is uploaded on that call either, and it\n"
    "  is what makes the client tell the user a step is still outstanding and hand you\n"
    "  the exact follow-up command. Leave it off and you get neither, and the second\n"
    "  step survives only in your memory. Run that follow-up when the user asks you to\n"
    "  check, never on a timer. Refused before then is by design, not a fault; a\n"
    "  failure there leaves the bundle and the support code untouched; \"nothing to\n"
    "  add\" means the log was empty.\n"
)

BE_ROW = (
    "| \"send the agent's log too\", \"include the bridge log\", \"the log from this "
    "chat\" | add `--agent-log` to the **bare** command **and to `--confirm`** — it "
    "uploads nothing on either; it makes the plan name it, and makes the client hand "
    "you `sr.py send-logs --status <CODE> --agent-log` for once the bundle lands. "
    "**Not** owner-gated. See **Sending logs to support** |\n"
)

FORK_OFFER_BLOCK = (
    "```bash\n"
    "$SR send-logs --agent-log             # SHOWS what would go. Sends nothing.\n"
    "$SR send-logs --confirm               # only after they say yes\n"
    "```\n"
)

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ F — the fork's document, the only route it has ═════════════
    ("F1", FORK_SKILL, "under",
     "⛔ THE WHOLE OFFER GOES — prose and command — and the flag is unreachable "
     "again. Kept for the regression, but note it is killed partly as collateral: "
     "three guards error out on the vanished prose anchor. F1b is the honest one",
     [("The log from **the program running this chat** is a third thing, and a third\n"
       "computer: not their research computer, and in this setup very often not theirs\n"
       "at all. It holds a record of connecting and signing in. Offer it when the\n"
       "trouble is this chat reaching their computer at all, rather than a piece of\n"
       "research going wrong:\n\n" + FORK_OFFER_BLOCK +
       "\nThree things nothing else here will say.",
       "Three things nothing else here will say.")]),
    ("F1b", FORK_SKILL, "under",
     "⛔⛔ THE COMMAND GOES AND THE PROSE STAYS. The offer reads as an offer and "
     "names nothing to run — and the FIRST version of this wave's own guard passed "
     "7/7 against exactly this, because it read the whole section for a string the "
     "second-step line already carried",
     [(FORK_OFFER_BLOCK + "\nThree things", "\nThree things")]),
    ("F1c", FORK_SKILL, "over",
     "⛔⛔⛔ THE CONSENT ONE. The flag comes off the OFFER while the check keeps it, "
     "so the plan says the log is NOT included, they agree to that, and the "
     "documented check uploads it anyway — nothing cross-checks the two",
     [("$SR send-logs --agent-log             # SHOWS what would go. Sends nothing.",
       "$SR send-logs                          # SHOWS what would go. Sends nothing.")]),
    ("F2", FORK_SKILL, "under",
     "⛔⛔ THE SECOND STEP GOES. The plan still promises the log; nothing ever "
     "uploads it, and nobody is told a step is outstanding — which is precisely "
     "the shape this client shipped with",
     [("If the plan named the log from the program running this chat, this is where it\n"
       "actually goes — ask for it on the same check:\n\n"
       "```bash\n"
       "$SR send-logs --check <the code> --agent-log\n"
       "```\n\n"
       "Before their computer's record has landed", "Before their computer's record has landed")]),
    ("F3", FORK_SKILL, "over",
     "⛔⛔ UPSTREAM'S SPELLING. This parser has no `--status` at all; the "
     "documented command exits 2. Right flag, unrunnable line",
     [("$SR send-logs --check <the code> --agent-log",
       "$SR send-logs --status <the code> --agent-log")]),
    ("F4", FORK_SKILL, "over",
     "⛔⛔ THE FLAG MOVES ONTO `--confirm`, WHICH THIS FORK DOES NOT READ THERE. "
     "The assistant reports a log as sent that nothing uploaded",
     [("$SR send-logs --agent-log             # SHOWS what would go. Sends nothing.\n"
       "$SR send-logs --confirm               # only after they say yes",
       "$SR send-logs --agent-log             # SHOWS what would go. Sends nothing.\n"
       "$SR send-logs --confirm --agent-log   # only after they say yes")]),
    ("F5", FORK_SKILL, "under",
     "the absence of an ownership gate stops being stated, so a reader carries "
     "across the owner-only rule from the paragraph above and withholds it",
     [("It is **not** owner-only the way the\n"
       "records above are, so no refusal will stand in the way — whether it should go\n"
       "is a judgement rather than a permission. ", "")]),
    ("F6", FORK_SKILL, "under",
     "the rotation clause goes, so the log reads as this conversation's when it "
     "is the whole active file — weeks on a quiet host, and past the run reported",
     [("It covers that file since it last\n"
       "rotated, not just this conversation, so it can reach back further than the\n"
       "problem they are reporting. ", "")]),
    ("F7", FORK_SKILL, "over",
     "⛔⛔ THE WRONG MACHINE. The passage borrows this document's phrase for the "
     "RESEARCH computer, in the one place whose job is to be exact about which",
     [("It is **not** owner-only the way the\nrecords above are",
       "It is **not** owner-only the way that computer's own records are")]),
    ("F8", FORK_SKILL, "under",
     "the refusal before the record lands stops being called deliberate, so the "
     "design working reads as a fault — a retry loop, or a person told it was lost",
     [("Before their computer's record has landed this is **refused on purpose**, and\n"
       "that refusal is not a fault: try it again the next time they ask. ", "")]),
    ("F9", FORK_SKILL, "under",
     "a failure on the second step stops being scoped, so it reads as the whole "
     "send failing — and the support code they already hold sounds worthless",
     [("If it does\nnot go, the research files already went and the support code still works — say\n"
       "that, rather than letting it sound as though the whole thing failed. ", "")]),
    ("F10", FORK_SKILL, "under",
     "an empty log stops being a fact and reads as a failure",
     [("If it\ncomes back saying there was nothing to add, the log was empty.", "")]),
    ("F11", FORK_SKILL, "under",
     "⛔ the one line that gets the outstanding step INTO THE CONVERSATION goes. "
     "This fork's success message never mentions the log, so the step then lives "
     "only in a model's memory across turns",
     [(" Nothing reminds you of that once they have agreed, so tell them at\n"
       "that moment — a step held only in your own head is a step that gets dropped.",
       "")]),

    # ═══════════ B — the backend agent's document ════════════════════════════
    ("B1", BE_SKILL, "under",
     "⛔ THE BULLET GOES. The NL router still honours somebody who says the exact "
     "words, so the option survives for people who already know it — and is never "
     "OFFERED to anyone else",
     [(BE_BULLET, "")]),
    ("B2", BE_SKILL, "under",
     "⛔⛔ THE ROW GOES AND THE SECTION STAYS. The table is what a model actually "
     "reads to decide what to run; a section further down it never reaches on a "
     "lookup is not an offer",
     [(BE_ROW, "")]),
    ("B3", BE_SKILL, "over",
     "⛔⛔ THE ROW DROPS `--confirm` FROM THE FLOW and still promises the client "
     "hands over the follow-up. Measured: a plain `--confirm` prints neither the "
     "person's line nor the directive, so the row's own claim becomes false",
     [("add `--agent-log` to the **bare** command **and to `--confirm`** — it "
       "uploads nothing on either; it makes the plan name it, and makes the client "
       "hand you",
       "add `--agent-log` to the **bare** command so the plan names it. The client "
       "hands you")]),
    ("B4", BE_SKILL, "under",
     "the absence of an ownership gate stops being stated, one bullet below the "
     "owner-only rule it must not be confused with",
     [("Unlike `--machine`\n"
       "  there is **no ownership gate**, so no refusal will stop you: offer it only\n"
       "  when the problem is this chat reaching their computer at all. ", "")]),
    ("B5", BE_SKILL, "over",
     "⛔⛔ A GATE THAT DOES NOT EXIST. Measured: no ownership check on this one in "
     "any client, the bridge, or the route. The assistant withholds on a rule "
     "nothing enforces",
     [("there is **no ownership gate**, so no refusal will stop you: offer it only",
       "it is the owner's too, so a non-owner is told no: offer it only")]),
    ("B6", BE_SKILL, "under",
     "⛔ TWO DIFFERENT COMPUTERS, and the bullet stops saying which. Six lines "
     "above, the same document calls the Research Computer's records that",
     [("  the program running this chat, not their Research Computer. `--agent-log`\n",
       "  `--agent-log`\n")]),
    ("B7", BE_SKILL, "under",
     "the separate step stops being named, so the assistant adds the flag to the "
     "send and stops there",
     [("**It does not ride the send** — but\n", "")]),
    ("B12", BE_SKILL, "under",
     "⛔⛔ THE INSTRUCTION THAT MAKES THE CLIENT SPEAK GOES. Without the flag on "
     "`--confirm` this client prints neither the outstanding-step line nor the "
     "follow-up command — measured by driving it both ways",
     [("  **pass it on `--confirm` too**: nothing is uploaded on that call either, and it\n"
       "  is what makes the client tell the user a step is still outstanding and hand you\n"
       "  the exact follow-up command. Leave it off and you get neither, and the second\n"
       "  step survives only in your memory. Run that follow-up when the user asks you to\n"
       "  check, never on a timer. ",
       "  the client hands you the exact follow-up command; run it when the user asks\n"
       "  you to check, never on a timer. ")]),
    ("B8", BE_SKILL, "under",
     "the rotation clause goes, so the log reads as this conversation's when it "
     "covers everything since the file last rotated",
     [("It covers that\n"
       "  file since it last rotated, not just this conversation, so it can reach back\n"
       "  further than the problem being reported. ", "")]),
    ("B9", BE_SKILL, "under",
     "the deliberate refusal stops being called deliberate, so the ordering that "
     "keeps a log deletable reads as a bug",
     [("Refused before then is by design, not a fault; ", "")]),
    ("B10", BE_SKILL, "under",
     "a failure on the second step stops being scoped and reads as the whole send "
     "failing",
     [("failure there leaves the bundle and the support code untouched; ", "")]),
    ("B11", BE_SKILL, "over",
     "an empty log is reported as a successful send rather than as nothing to send",
     [("\"nothing to\n  add\" means the log was empty.",
       "\"nothing to\n  add\" means it went.")]),

    # ═══ C — the CLIENTS move, and the documents must notice ════════════════
    #
    # ⛔⛔ THIS IS THE HALF THAT WAS MISSING LAST TIME. Four guards pinned the
    # client's wording and none pinned the caller, so the caller could be absent
    # entirely and the suite stayed green. These invert it: the guards are pinned
    # to the code, so a client that changes underneath them fails loudly instead
    # of leaving a document quietly describing the old shape forever.
    ("C1", FORK_SR, "over",
     "the fork's SEND path learns to carry the log, so the document's "
     "\"goes on the check\" is now wrong in the other direction",
     [('    payload = {"runNames": names, "includeMachine": machine,',
       '    payload = {"runNames": names, "includeMachine": machine,\n'
       '               "includeAgentLog": agent_log,')]),
    ("C2", BE_SR, "over",
     "the backend client uploads on the send path, before any record exists — the "
     "readable-log-nothing-can-delete case — and the document still says it does not",
     [('    code, sent = _post("/logs/send", payload)',
       '    code, sent = _post("/logs/send", payload)\n'
       '    if agent_log:\n'
       '        _post("/logs/agent-log", {"code": ""})')]),
    ("C3", BE_SR, "under",
     "⛔⛔ the client stops printing the follow-up the table promises, so the "
     "document sends the assistant looking for a directive that never arrives",
     [('        directives.append(\n'
       '            f"Once the bundle shows done, run: sr send-logs --status {support} "\n'
       '            "--agent-log   (it is refused until then, by design)")',
       '        pass')]),
    ("C4", FORK_SR, "over",
     "an ownership gate appears on the fork's agent log, so the document now "
     "understates what stops it",
     [("    if machine and not owned:", "    if (machine or agent_log) and not owned:")]),
    ("C5", BE_SR, "over",
     "the same gate appears on the backend client, and the bullet's \"no ownership "
     "gate\" becomes false",
     [("    if machine and not owned:", "    if (machine or agent_log) and not owned:")]),
    ("C6", FORK_SR, "over",
     "⛔ the fork's success path gains its own reminder, so the document's "
     "\"nothing reminds you of that\" is no longer true",
     [('    _say("Asked %s for the files. Their support code is %s." % (name, support))',
       '    _say("Asked %s for the files. Their support code is %s." % (name, support))\n'
       '    if agent_log:\n'
       '        _say("The log from the program running this chat follows.")')]),
    ("C7", BE_SR, "under",
     "⛔ the backend client stops reading the flag after the send, so the "
     "document's instruction to pass it on `--confirm` becomes cargo cult",
     [('    if agent_log:\n'
       '        # ⛔⛔ THE AGENT\'S LOG CANNOT GO YET,',
       '    if False:\n'
       '        # ⛔⛔ THE AGENT\'S LOG CANNOT GO YET,')]),
]


def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> str | None:
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return (FORK if fname in THEIRS else ROOT) / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. This wave is uncommitted on purpose — the fork
    stages for a signing session — so a git check would report dirty on every run
    and a real leftover mutant would be invisible inside that noise.
    """
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest()
            for f in (*OURS, *THEIRS)}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when `-k` matches no tests, and
    a runner that only asks `returncode == 0` reads that as red — so one typo in
    the filter would score every mutant killed against zero tests. It is separated
    out here and raised as a harness fault by the caller.
    """
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(kfilter: str | None) -> bool:
    """Two programs, and both must be green."""
    purge_pycache(ROOT)
    be_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    be_args = [sys.executable, "-B", "-m", "pytest", *BE_SUITES.split(),
               "-q", "-p", "no:cacheprovider"]
    fork_args_tail = ["-q", "-p", "no:cacheprovider"]
    if kfilter:
        be_args += ["-k", kfilter]
        fork_args_tail += ["-k", kfilter]

    be = _pytest(be_args, ROOT / "agent", be_env)
    if be == "nothing-collected":
        raise AssertionError("the backend leg collected NO tests — check the filter")
    if be == "red":
        return False

    purge_pycache(FORK)
    fork_py = FORK / ".venv" / "bin" / "python"
    if not fork_py.exists():
        raise AssertionError(f"the fork's virtualenv is missing at {fork_py}")
    fork = _pytest([str(fork_py), "-B", "-m", "pytest", FORK_SUITES, *fork_args_tail],
                   FORK, ENV)
    if fork == "nothing-collected":
        raise AssertionError("the fork leg collected NO tests — check the filter")
    return fork == "green"


def _selected_count(kfilter: str) -> tuple[int, int]:
    """How many tests the filter actually picks, per leg."""
    def count(args, cwd, env) -> int:
        out = sh(args + ["--collect-only", "-q", "-p", "no:cacheprovider",
                         "-k", kfilter], cwd=cwd, env=env).stdout
        for line in out.splitlines():
            if "collected" in line and "/" in line:
                return int(line.split("/", 1)[0].split()[-1])
        return 0
    be_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    be = count([sys.executable, "-B", "-m", "pytest", *BE_SUITES.split()],
               ROOT / "agent", be_env)
    fork = count([str(FORK / ".venv" / "bin" / "python"), "-B", "-m", "pytest",
                  FORK_SUITES], FORK, ENV)
    return be, fork


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
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — this is a spot check, "
              f"not a score for the wave.")
    print("scope: THE WHOLE TREE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY (-k) — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\n"
              "Restore that file, then delete\n"
              f"    {_INFLIGHT}")
        return 2

    if kfilter:
        be_n, fork_n = _selected_count(kfilter)
        print(f"filter picks {be_n} backend / {fork_n} fork test(s)")
        if be_n < MIN_SELECTED or fork_n < MIN_SELECTED:
            print(f"⛔⛔ THE FILTER PICKS TOO FEW (need >= {MIN_SELECTED} each). "
                  "A filter that matches nothing exits 5 and scores every mutant "
                  "killed — refusing to run.")
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

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then goes
            # red on an import error and the mutant reports a kill it never earned.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            _mark(mid, fname)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests(kfilter)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                # ⭐ RE-RUN EITHER VERDICT, not only a survival. A flaky leg that
                # went red once would otherwise bank a kill nothing earned.
                again = not run_tests(kfilter)
                flapped = flapped or (again != killed)
                killed = killed and again
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed or flapped:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    leftover = [f for f in before if before[f] != after[f]]
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    scope = " [whole tree]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out "
              f"of the score above:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
