"""Mutation harness — the send-logs picker, the agent-log consent, the fleet's two
homes and the upload's 401 retry (wave 7.9-1, 2026-09-06).

⛔⛔ WHAT THIS CODE DECIDES. Whether the option to send the chat host's own log is
VISIBLE to somebody who does not already know it exists; whether a person can say
which runs to send at all in a chat; whether what they are told before agreeing is
what the file actually holds; whether the one screen they open when something is
wrong tells them the truth about where that file goes; and whether the upload
survives a token that dies inside its own sixty-second window.

⛔⛔ THE PLAN SAID "ADD 0 TO THE NUMBERED PICKER" AND THERE WAS NO PICKER. Measured
before building: nothing on this surface reads a number from stdin, and a guard
written three weeks earlier records the decision NOT to add a prompt. So the
picker is the printed numbers plus `--runs`, the terminal's default is unchanged,
and the P-series exists to prove the numbers reach the wire.

⭐⭐ THE SHARPEST MUTANTS HERE:
  P2/P3   — the resolver returns the flag and the CALLER drops it. This is the
            shape that has survived a sweep in this family before: a test pinned
            the helper's signature while the mutant changed the call site.
  P10     — the `0` row moves inside the has-runs branch. Every ordinary test
            still sees it; it vanishes on exactly the two branches where somebody
            reaches for it, because the trouble is reaching the computer at all.
  P12     — the runs renumber from zero. `0` is free ONLY because the list starts
            at 1, and nothing else in the tree states that dependency.
  N1/N2   — the live defect restored. `_DO_FLAGS` loses a flag `_nl_resolve`
            emits, `cmd_do` pushes it behind `--`, argparse exits 2 and the whole
            request becomes "I didn't catch a Super Research request in that".
  N3      — a VALUE-taking flag is routed. The flag survives and its VALUE goes
            behind `--` — the same failure one argument along.
  D1      — the false sentence comes back. It was pinned by NO test before this
            wave: the suite asserted the true half and stopped at the em-dash.
  D7      — the split-home warning moves ABOVE the file handler. It is emitted, it
            looks right on a console, and it is absent from the one file that gets
            uploaded — which is the only place anybody will ever read it.
  R1      — the retry re-sends the CACHED token. It retries, it fails the same
            way, and every "did it eventually work" assertion is satisfied.
  R4/R5   — the token mint is unwrapped. The one caller sits OUTSIDE its
            `except RevokedError` and `do_POST` has no blanket handler, so the
            person waiting on the upload gets a closed socket and no reply.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS WAVE'S OWN GUARDS by running this wave's five test files.
Pass --unfiltered to ask the other question — whether the TREE catches it — which
is deliberately separate. A borrowed kill is not evidence that the guard you just
wrote works.

    .venv/bin/python .mutants/wave791_send_logs_picker_mutants.py
    .venv/bin/python .mutants/wave791_send_logs_picker_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

CLI = "agent/facade/cli.py"
BRIDGE = "agent/facade/bridge.py"
CONFIG = "agent/facade/config.py"
SR = "agent/facade/skill/scripts/sr.py"
LOGSETUP = "agent/facade/logsetup.py"
SKILL = "agent/facade/skill/SKILL.md"
OURS = (CLI, BRIDGE, CONFIG, SR, SKILL, LOGSETUP)

# ⭐ THE GUARDS THIS WAVE ADDED, and the only tests a score here is about.
MINE = ("tests/test_send_logs_picker_791.py "
        "tests/test_chat_picker_791.py "
        "tests/test_agent_log_consent_791.py "
        "tests/test_log_locality_791.py "
        "tests/test_fe_bytes_retry_791.py "
        "tests/test_send_logs_crossverify_791.py")
MIN_SELECTED = 140

# ⚠ The whole agent suite, for the other question. ⛔ IT IS ONLY THAT: an earlier
# version of this comment also claimed the backend root's anchor sweep rode along,
# and it does not — nothing here runs `.mutants/_anchor_sweep.py`. This wave
# re-anchored three pre-existing harnesses, and the sweep that proves those still
# match is a SEPARATE command, run by hand before and after this one.
ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ P — the terminal's picker ══════════════════════════════════
    ("P1", CLI, "under",
     "⛔⛔ `0` STOPS BEING THE AGENT LOG and falls back to the range check that "
     "rejected it — the offer is unreachable again for anybody who does not "
     "already know the flag exists, which is the state this wave found",
     [('        if token == _AGENT_LOG_TOKEN:\n'
       '            wants_agent_log = True\n'
       '            continue\n', '')]),
    ("P2", CLI, "under",
     "⛔⛔ THE CALLER DROPS IT. The resolver still returns the flag and nothing "
     "reads it — the exact shape that survived a sweep in this family, where a "
     "test pinned the helper's signature while the mutant changed the call site",
     [("    agent_log = agent_log or picked_agent_log",
       "    agent_log = agent_log or False")]),
    ("P3", CLI, "over",
     "⛔ THE TWO ROUTES BECOME AN AND. Somebody who says it one way is answered "
     "no, and only somebody who says it BOTH ways is heard",
     [("    agent_log = agent_log or picked_agent_log",
       "    agent_log = agent_log and picked_agent_log")]),
    ("P4", CLI, "under",
     "⛔ `all` STOPS BEING A WORD and goes back to failing with \"isn't holding a "
     "run called “all”\" — a sentence naming a run that never existed, while the "
     "flag's own help says the default is all of them",
     [('        if token.lower() == _ALL_TOKEN:\n', '        if False:\n')]),
    ("P5", CLI, "over",
     "`all` stops skipping runs already named, so `--runs 2,all` sends run 2 "
     "twice and the count printed to the person is wrong",
     [('            for row in rows:\n'
       '                if row.get("name") not in picked:\n'
       '                    picked.append(row.get("name"))\n',
       '            for row in rows:\n'
       '                picked.append(row.get("name"))\n')]),
    ("P6", CLI, "under",
     "⛔ A SIGNED NUMBER FALLS BACK TO THE NAME BRANCH, so `-1` is refused as a "
     "missing run NAME rather than as an index out of range — a sentence about a "
     "run name nobody typed",
     [('        body = token[1:] if token[:1] in "+-" else token\n'
       '        if body.isdecimal() and body.isascii():',
       '        body = token\n'
       '        if body.isdigit():')]),
    ("P7", CLI, "under",
     "⛔⛔ THE AGENT-LOG-ONLY REFUSAL GOES, so somebody who picked exactly one "
     "thing is told there is nothing to send",
     [('        if agent_log:\n'
       '            print(f"{_NO} The agent\'s own log can only go up beside a bundle from "\n'
       '                  "that computer,")\n', '        if False:\n')]),
    ("P8", CLI, "over",
     "⛔⛔ IT EXPLAINS AND THEN CARRIES ON — the sentence is printed and the "
     "request goes anyway, so the bridge is asked to build an empty archive after "
     "a person has been told it cannot be done",
     [('                print("    Or, if the trouble is reaching that computer at all, "\n'
       '                      "add --machine.")\n'
       '            return 1\n',
       '                print("    Or, if the trouble is reaching that computer at all, "\n'
       '                      "add --machine.")\n')]),
    ("P9", CLI, "under",
     "⛔ THE `0` ROW IS NEVER PRINTED. The flag still works for anybody who knows "
     "it exists and is offered to nobody — 2026-08-26 to 2026-09-06, restored",
     [('    _print_agent_log_choice()\n', '')]),
    ("P10", CLI, "over",
     "⛔⛔ THE SHARPEST ONE. The row moves inside the has-runs branch, so it "
     "vanishes on exactly the two branches where somebody reaches for it — a "
     "machine holding none of their runs, and one that has published no list",
     [('        if body.get("truncated"):\n'
       '            print("  (only the most recent are listed — it holds more)")\n'
       '    _print_agent_log_choice()\n',
       '        if body.get("truncated"):\n'
       '            print("  (only the most recent are listed — it holds more)")\n'
       '        _print_agent_log_choice()\n')]),
    ("P11", CLI, "under",
     "⛔ THE ROW STOPS NAMING THE OTHER COMPUTER, so a numbered line under a list "
     "of that machine's runs reads as one more of that machine's runs — the exact "
     "confusion a sibling guard polices in the consent copy",
     [('    print("   0  the log from the agent on THIS host — the machine you are "\n'
       '          "typing on,")\n'
       '    print("      which may not be that computer")',
       '    print("   0  the log from the agent on THIS host")')]),
    ("P12", CLI, "over",
     "⛔⛔ THE RUNS RENUMBER FROM ZERO, so the agent's log and the first run share "
     "a number and the log silently becomes run one. `0` is free ONLY because the "
     "list starts at 1 and nothing else in the tree states that dependency",
     [('    for i, row in enumerate(rows, 1):', '    for i, row in enumerate(rows, 0):')]),
    ("P13", CLI, "over",
     "⛔ THE DEFAULT CHANGES to the plan's Enter-means-machine-logs line, which "
     "was written against a prompt this surface does not have — so a person who "
     "names no runs silently sends none of them",
     [('    names: list[str] = [r.get("name") for r in rows]\n',
       '    names: list[str] = []\n')]),

    # ═══════════ C — chat ═══════════════════════════════════════════════════
    ("C1", SR, "under",
     "⛔⛔ CHAT'S SELECTION IS IGNORED — every run goes whatever was asked for, "
     "which is the all-or-nothing state this wave found",
     [('    if getattr(args, "runs", ""):\n'
       '        chosen, picked_agent_log, refusal = _resolve_log_selection(rows, args.runs)\n',
       '    if False:\n'
       '        chosen, picked_agent_log, refusal = _resolve_log_selection(rows, args.runs)\n')]),
    ("C2", SR, "under",
     "⛔⛔ CHAT DROPS INSTEAD OF REFUSING: a token it could not place is skipped "
     "and the rest is sent, so fewer runs go than were asked for and it reports "
     "success — the one direction a log request must not fail in",
     [('        chosen, picked_agent_log, refusal = _resolve_log_selection(rows, args.runs)\n'
       '        if refusal:\n            return _emit(body, args.json, refusal, 1)\n',
       '        chosen, picked_agent_log, refusal = _resolve_log_selection(rows, args.runs)\n'
       '        if refusal:\n            chosen = chosen or []\n')]),
    ("C3", SR, "over",
     "⛔⛔ THE PLAN LISTS ONLY WHAT IS GOING, so the numbers of everything else "
     "are off screen and cannot be asked for — a list nobody can pick FROM",
     [('        for i, row in enumerate(rows, 1):\n'
       '            going = row.get("name") in names\n',
       '        for i, row in enumerate([r for r in rows if r.get("name") in names], 1):\n'
       '            going = True\n')]),
    ("C4", SR, "under",
     "⛔ THE WORDS GO AND THE GLYPH STAYS. One character apart is all that "
     "separates going from not going, in a chat relayed through a model",
     [('''f"{'' if going else '   (not picked)'}")''', 'f"")')]),
    ("C5", SR, "under",
     "⛔ THE `0` ROW APPEARS ONLY WHEN IT IS ALREADY GOING, so it is shown to "
     "everyone who does not need it and to nobody who does",
     [('        lines.append(f"  0 {\'•\' if agent_log else \'·\'} the log from the agent on "\n'
       '                     "THIS host — the machine running this chat, which may not "\n'
       '                     "be that computer"\n'
       '                     f"{\'\' if agent_log else \'   (not picked)\'}")\n',
       '        if agent_log:\n'
       '            lines.append("  0 • the log from the agent on THIS host")\n')]),
    ("C6", SR, "under",
     "⛔ THE LINE THAT SAYS THE NUMBERS ARE SAYABLE GOES. Nothing else in the "
     "conversation tells a person, or the assistant relaying for them, that "
     "saying a number is a thing they may do",
     [(' — or say which numbers to send "\n'
       '                     "instead (0 is the agent’s own log).', '.')]),
    # ⛔⛔ THIS WAS AN EQUIVALENT MUTANT ON ITS FIRST WRITING and survived 47/47
    # honestly. It INSERTED a `--none` block and left the original one below it,
    # so the flag was applied twice and still won — the behaviour was byte-for-byte
    # unchanged and no guard could have killed it. An equivalent mutant is a
    # harness bug, not a hole in the tests. It MOVES the block now.
    ("C7", SR, "over",
     "⛔ `--none` STOPS WINNING: it is applied before the selection instead of "
     "after, so a request that says both sends runs the person asked not to send",
     [('    names = [r.get("name") for r in rows]\n'
       '    if getattr(args, "runs", ""):',
       '    names = [r.get("name") for r in rows]\n'
       '    if getattr(args, "none", False):\n'
       '        names = []\n'
       '    if getattr(args, "runs", ""):'),
      ('    if getattr(args, "none", False):\n'
       '        # ⛔ STILL LAST, so it still wins. It is the documented pairing for\n'
       '        # `--machine` and it means what it has always meant: no runs. It does NOT\n'
       '        # clear the agent\'s log, which is not a run and not on that computer.\n'
       '        names = []\n', '')]),
    ("C8", SR, "under",
     "⛔ CHAT'S AGENT-LOG-ONLY REFUSAL GOES, so the two clients disagree about "
     "the one thing they were just made to agree on",
     [('        if agent_log:\n'
       '            return _emit(body, args.json, [\n'
       '                "The agent’s own log can only go up beside a bundle from that "\n',
       '        if False:\n'
       '            return _emit(body, args.json, [\n'
       '                "The agent’s own log can only go up beside a bundle from that "\n')]),

    # ═══════════ N — the natural-language router ════════════════════════════
    ("N1", SR, "under",
     "⛔⛔ THE LIVE DEFECT RESTORED. `--machine` leaves the allowlist, `cmd_do` "
     "reads it as free text and pushes it behind `--`, `send-logs` has no "
     "positional, argparse exits 2, and \"send the computer's own logs to "
     "support\" becomes \"I didn't catch a Super Research request in that\"",
     [('_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log"})',
       '_DO_FLAGS = frozenset({"--no-video", "--no-email", "--agent-log"})')]),
    ("N2", SR, "under",
     "⛔⛔ THE SAME, FOR THE FLAG THIS WAVE IS ABOUT",
     [('_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log"})',
       '_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine"})')]),
    ("N3", SR, "over",
     "⛔⛔ A VALUE-TAKING FLAG IS ROUTED. The flag survives and its VALUE goes "
     "behind `--` — the same failure one argument along, and invisible to a guard "
     "that only checks membership",
     [('_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log"})',
       '_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log", "--runs"})')]),

    # ═══════════ D — the doctor and the fleet's two homes ═══════════════════
    ("D1", CLI, "over",
     "⛔⛔ THE FALSE SENTENCE COMES BACK. It was pinned by NO test before this "
     "wave — the suite asserted the true half and stopped at the em-dash",
     [('    b.dim("              not sent with a support bundle — that archive is built on the")\n'
       '    b.dim("              research computer and cannot reach this file")',
       '    b.dim("              not sent with a support bundle — this file stays on this host")')]),
    ("D2", CLI, "under",
     "⛔ THE ACTIONABLE LINE GOES, so a person told only that the file is not in "
     "the bundle concludes it cannot be sent — which is what the false sentence "
     "used to say out loud",
     [('    b.dim("              it goes only when you ask for it, with  --agent-log")\n', '')]),
    ("D3", CLI, "under",
     "the not-in-the-bundle half goes, so somebody who sent a bundle assumes this "
     "went with it and waits on evidence nobody has",
     [('    b.dim("              not sent with a support bundle — that archive is built on the")\n'
       '    b.dim("              research computer and cannot reach this file")\n', '')]),
    ("D4", CONFIG, "over",
     "⛔ THE HOMES ARE COMPARED AS STRINGS, so a trailing slash or a symlink "
     "reads as a split — a warning that fires on every fleet box every day is one "
     "people learn to scroll past before the day it means something",
     [('        theirs = Path(raw).expanduser().resolve()\n'
       '        ours = Path.home().resolve()',
       '        theirs = raw\n'
       '        ours = str(Path.home())')]),
    ("D5", CONFIG, "over",
     "the split reports the RESOLVED path instead of what the operator set, so "
     "somebody goes looking for a line that does not exist in their config",
     [('    return None if theirs == ours else raw',
       '    return None if theirs == ours else str(theirs)')]),
    # ⛔ RESTATED 2026-09-07. The first `why` claimed an empty value would raise a
    # warning; it cannot — the function would return the empty string, which is
    # falsy and which no consumer acts on, so the mutant changed nothing anybody
    # could see. Made observable instead: an UNSET variable now reports a split.
    ("D6", CONFIG, "over",
     "an UNSET variable reads as a second home, so every ordinary host — where "
     "HERMES_HOME does not exist at all — raises a warning about nothing",
     [('    raw = (os.environ.get(HERMES_HOME_ENV) or "").strip()',
       '    raw = (os.environ.get(HERMES_HOME_ENV) or "/nowhere").strip()')]),
    ("D7", CLI, "over",
     "⛔⛔ THE WARNING MOVES ABOVE THE FILE HANDLER. It is emitted, it looks right "
     "on a console nobody has, and it is absent from the one file that gets "
     "uploaded — which is the only place anybody will ever read it",
     [('    logsetup.configure(\n'
       '        verbose=(getattr(args, "verbose", False) or config.VERBOSE\n'
       '                 or prefs.get_verbose()),\n'
       '        to_file=True)\n',
       '    _early = config.home_split()\n'
       '    if _early:\n'
       '        log.warning("homes split: %s", _early)\n'
       '    logsetup.configure(\n'
       '        verbose=(getattr(args, "verbose", False) or config.VERBOSE\n'
       '                 or prefs.get_verbose()),\n'
       '        to_file=True)\n')]),
    ("D8", CLI, "under",
     "⛔ THE SERVE WARNING GOES ENTIRELY, so the condition that makes an uploaded "
     "log silently empty leaves no trace in the log support is holding",
     [('    _split = config.home_split()\n'
       '    if _split:\n'
       '        log.warning(\n', '    if False:\n        log.warning(\n')]),
    ("D9", CLI, "over",
     "the doctor's homes row prints whether or not they disagree, so the one "
     "screen whose job is to show what is wrong gains a line that is always there",
     [('    split = config.home_split()\n    if split:',
       '    split = config.home_split() or str(Path.home())\n    if split:')]),

    # ═══════════ R — the upload's 401 retry ═════════════════════════════════
    ("R1", BRIDGE, "over",
     "⛔⛔ THE RETRY RE-SENDS THE CACHED TOKEN. It retries, it fails the same way, "
     "and every \"did it eventually work\" assertion is satisfied — only the "
     "ORDER of the tokens tells the two apart",
     [("    token, why = _mint_bearer(sess, force=True)",
       "    token, why = _mint_bearer(sess, force=False)")]),
    ("R2", BRIDGE, "under",
     "the retry goes, and the call most likely to have its token expire "
     "mid-flight — sixty seconds, megabytes — is the one with no second chance",
     [('    if status != 401:\n        return status, body\n',
       '    if True:\n        return status, body\n')]),
    ("R3", BRIDGE, "over",
     "⛔ IT RETRIES ANY FAILURE, so a 500 or a 413 is sent twice — the app choked "
     "on that body once and is handed it again",
     [('    if status != 401:\n        return status, body\n',
       '    if status == 200:\n        return status, body\n')]),
    ("R4", BRIDGE, "over",
     "⛔⛔ THE FORCED MINT IS UNWRAPPED. The one caller makes this call OUTSIDE "
     "its `except RevokedError` and `do_POST` has no blanket handler, so a dead "
     "refresh token closes the connection instead of answering",
     [("    token, why = _mint_bearer(sess, force=True)\n    if token is None:\n        return 0, why\n"
       "    return _send(token)",
       "    return _send(sess.id_token(force=True))")]),
    ("R5", BRIDGE, "over",
     "⛔ THE FIRST MINT IS UNWRAPPED — the hole that existed before any retry did, "
     "and the reason both are wrapped rather than only the new one",
     [("    token, why = _mint_bearer(sess, force=False)\n    if token is None:\n        return 0, why\n"
       "    status, body = _send(token)",
       "    status, body = _send(sess.id_token())")]),
    ("R6", BRIDGE, "under",
     "⛔ A DEAD SESSION IS REPORTED AS A GENERIC UPLOAD FAILURE, naming no cause "
     "and offering no action, on the route whose retry has just proved the "
     "session is the problem",
     [('            if reply.get("reason") == "revoked":\n', '            if False:\n')]),
    ("R7", BRIDGE, "over",
     "⛔⛔ THE REVOKED BRANCH MOVES BEHIND THE GENERIC ONE, where it can never be "
     "reached — a correct sentence, unreachable, which is how it reads in review",
     [('            if reply.get("reason") == "revoked":\n'
       '                # ⛔ THE SAME SENTENCE THE REST OF THIS FILE GIVES, and reached\n',
       '            if status != 200 and reply.get("reason") == "never":\n'
       '                # ⛔ THE SAME SENTENCE THE REST OF THIS FILE GIVES, and reached\n')]),

    # ═══════════ K — the consent copy ═══════════════════════════════════════
    ("K1", CLI, "under",
     "⛔⛔ THE TERMINAL STOPS SAYING WHOSE RECORDS ARE IN IT. The machine-log line "
     "four sentences above names the people its material covers; this one names "
     "nobody, on the surface where the sharing is LESS obvious, not more",
     [('        print("It covers everyone who signed in through this agent since that "\n'
       '              "file last rotated, not only you — there is no owner to ask on a "\n'
       '              "machine like this, so nothing checks.")\n', '')]),
    ("K2", CLI, "under",
     "⛔ THE FIELDS GO, leaving \"not research content\" — a category, and the "
     "half of it that is a negative",
     [('        print("Among what is in it: a masked form of your email address, the ids "\n'
       '              "of the computers and runs this agent has touched, file paths on "\n'
       '              "this machine, and — when a lookup fails — your account id.")\n', '')]),
    ("K3", CLI, "over",
     "⛔⛔ THE CONSENT LINES MOVE OUT OF THE BRANCH, so a plan that is NOT sending "
     "the file describes what is in it — telling somebody their address is going "
     "when it is not, and making the negative line beside it read as a formality",
     [('    elif agent_log:\n'
       '        print("It will ALSO include the log from the agent on THIS host — the "',
       '    elif True:\n'
       '        print("It will ALSO include the log from the agent on THIS host — the "')]),
    ("K4", SR, "under",
     "chat stops saying whose records are in it, so the two clients answer the "
     "same question differently",
     [('            lines.append("It covers everyone who signed in through this agent "\n'
       '                         "since that file last rotated, not only you — there’s no "\n'
       '                         "owner to ask on a machine like that, so nothing checks.")\n', '')]),
    ("K5", SR, "under",
     "chat stops naming the fields",
     [('            lines.append("Among what’s in it: a masked form of your email "\n'
       '                         "address, the ids of the computers and runs this agent "\n'
       '                         "has touched, file paths on that machine, and — when a "\n'
       '                         "lookup fails — your account id.")\n', '')]),
    ("K6", SKILL, "under",
     "⛔ THE DOCUMENT STOPS TELLING THE MODEL THE NUMBERS CAN BE PASSED BACK, so "
     "the picker is reachable only by a person typing at a terminal — the gap "
     "this wave exists to close",
     # ⛔ IT USED TO CUT ONE LINE and leave the rest of the bullet behind, which
     # the first version of this wave's guard was satisfied by — the exact
     # neighbouring-line shape three mutants in this family have exploited before.
     # It takes the whole bullet now.
     [("- **Which runs go** is the user\'s to choose, and the plan numbers them so they\n"
       "  can. Everything listed goes unless `--runs` says otherwise; `--runs` takes the\n"
       "  printed numbers or the run names, `0` is the agent\'s own log and `all` is every\n"
       "  run listed. Pass the same `--runs` on `--confirm` — the two calls are separate\n"
       "  processes and the second remembers nothing. ⛔ A run the plan did not list\n"
       "  cannot be asked for: the list is what that computer published, and it says so\n"
       "  itself when it is holding more.\n", "")]),
    ("K7", SKILL, "under",
     "⛔⛔ THE DOCUMENT STOPS SAYING TO PASS THE SELECTION ON `--confirm`. Two "
     "processes, and the second remembers nothing: a selection given only to the "
     "first is silently replaced by every run on the call that actually sends",
     [(' Pass the same `--runs` on `--confirm` — the two calls are separate\n'
       '  processes and the second remembers nothing.', '')]),

    # ═══ X — WHAT CROSS-VERIFICATION FOUND AFTER 47/47 ══════════════════════
    #
    # ⛔⛔ EVERY MUTANT BELOW CORRESPONDS TO A DEFECT THAT WAS LIVE WHILE THIS
    # HARNESS REPORTED A PERFECT SCORE. That is the point of the series: a green
    # sweep says the guards catch the mutants somebody thought of, and these are
    # the ones nobody did.
    ("X1", CLI, "over",
     "⛔⛔ BLOCKER, RESTORED. `--none` takes the whole selection branch again, so "
     "`--none --runs 0` never runs the resolver: the agent-log token is dropped, "
     "the plan prints the OPPOSITE of what was asked for, and a spec that would "
     "have been refused is accepted in silence",
     [('    names: list[str] = [r.get("name") for r in rows]\n'
       '    if args.runs:', '    names: list[str] = [r.get("name") for r in rows]\n'
       '    if args.none:\n        args.runs = None\n'
       '    if args.runs:')]),
    ("X2", CLI, "over",
     "⛔⛔ BLOCKER, RESTORED. The agent's log rides a bundle that FAILED — the row "
     "exists and names a device before it is patched, so the bridge's ordering "
     "check passes and the file lands in a folder with no bundle in it",
     [('        if landed:\n            _send_agent_log(code)',
       '        if rc == 0 or not landed:\n            _send_agent_log(code)')]),
    ("X3", CLI, "over",
     "⛔ A TIMEOUT COUNTS AS AN ARRIVAL. `_await_bundle` exits 0 for both, which "
     "is why it reports `landed` separately; keying on the exit code puts an "
     "object under a code whose row nobody has confirmed",
     [("        if landed:\n            _send_agent_log(code)",
       "        if rc == 0:\n            _send_agent_log(code)")]),
    ("X4", CLI, "under",
     "⛔ THE TERMINAL'S SECOND STEP GOES AGAIN, so `--status <CODE> --agent-log` "
     "parses, uploads nothing and says nothing — and both routes out of an "
     "unfinished wait dead-end, as they did before",
     [('            if agent_log:\n                _send_agent_log(code)\n'
       '            return 0\n', '            return 0\n')]),
    ("X5", CLI, "over",
     "⛔⛔ THE LOGGER GOES BACK TO `__name__`, which under the fleet's own "
     "`python -m facade.cli serve` is \"__main__\" — not a child of the logger the "
     "file handler is on. The split warning reaches nothing, on the only "
     "deployment that can produce a split",
     [('log = logging.getLogger("facade.cli")', 'log = logging.getLogger(__name__)')]),
    ("X6", CLI, "under",
     "⛔ THE REFUSAL SENDS A NON-OWNER TO `--machine` AGAIN, which is refused four "
     "lines higher — a sharer with no listed runs goes round in a circle",
     [('            if owned:\n'
       '                print("    Or, if the trouble is reaching that computer at all, "\n'
       '                      "add --machine.")\n',
       '            if True:\n'
       '                print("    Or, if the trouble is reaching that computer at all, "\n'
       '                      "add --machine.")\n')]),
    ("X7", CLI, "over",
     "⛔ `--no-wait` DESCRIBES A FILE IT THEN DECLINES TO SEND, and only says so "
     "after the person has already agreed",
     [("    if agent_log and args.no_wait:", "    if agent_log and False:")]),
    ("X8", LOGSETUP, "under",
     "⛔⛔ TWO WRITERS, ONE FILE. The console handler stays attached while the "
     "fleet's redirect appends to the same path — after the first rotation the "
     "redirect keeps writing to the renamed inode, so the file the uploader "
     "sends is missing everything the console said",
     [('            console_is_the_log_file = _same_file(console.stream, path)\n'
       '            if console_is_the_log_file:\n'
       '                logger.removeHandler(console)\n',
       '            console_is_the_log_file = False\n'
       '            if console_is_the_log_file:\n'
       '                logger.removeHandler(console)\n')]),
    ("X9", LOGSETUP, "over",
     "⛔ THE CONSOLE IS DROPPED ON A GUESS, so a person watching a foreground "
     "`serve` loses the only output they have",
     [("            console_is_the_log_file = _same_file(console.stream, path)",
       "            console_is_the_log_file = True")]),
    ("X10", LOGSETUP, "over",
     "the streams are compared by NAME, which answers \"no\" for the one case this "
     "exists to catch — a redirect names the path, the process holds a descriptor",
     [("        a = os.fstat(stream.fileno())\n        b = path.stat()",
       "        a = getattr(stream, 'name', None)\n        b = str(path)")]),
    ("X11", BRIDGE, "over",
     "⛔⛔ THE JSON HELPER MINTS INSIDE THE `try` AGAIN: a dead refresh token "
     "escapes as an exception through /device/pair and /device/remove, and a "
     "failure reaching GOOGLE is reported as failing to reach the WEB APP",
     [('    token, why = _mint_bearer(sess, force=False)\n'
       '    if token is None:\n        return 0, why\n'
       '    try:\n'
       '        r = requests.post(\n'
       '            f"{config.FE_BASE}{path}",\n'
       '            json=payload,\n'
       '            headers={"Authorization": f"Bearer {token}"},',
       '    try:\n'
       '        r = requests.post(\n'
       '            f"{config.FE_BASE}{path}",\n'
       '            json=payload,\n'
       '            headers={"Authorization": f"Bearer {sess.id_token()}"},')]),
    ("X12", SR, "under",
     "⛔⛔ THE CONFIRM COMMAND GOES BACK TO CARRYING NOTHING, so the assistant "
     "re-sends the NUMBERS against a list the second process re-fetches — and "
     "position 2 can be a different run, or a different computer's run",
     [('        return _emit({**body, "wouldSend": names, "includeMachine": machine},\n'
       '                     args.json, [*lines, *_agent_directive_block(directives)])',
       '        return _emit({**body, "wouldSend": names, "includeMachine": machine},\n'
       '                     args.json, lines)')]),
    ("X13", SR, "over",
     "⛔ THE CONFIRM CARRIES THE NUMBERS INSTEAD OF THE NAMES — the same defect "
     "wearing a directive",
     [('            confirm.append("--runs " + ",".join(names))',
       '            confirm.append("--runs " + str(getattr(args, "runs", "")))')]),
    ("X14", SR, "under",
     "spoken connectives are read as run names again, so \"1 and 3\" is refused "
     "for a run called “and”",
     [('        if token.lower() in _SPOKEN_FILLER and token not in known:\n'
       '            continue\n', '')]),
    ("X15", SR, "over",
     "⛔ A CONNECTIVE THAT IS A REAL RUN NAME IS SWALLOWED. A machine may mint a "
     "run called \"and\"; dropping the word unconditionally loses it",
     [("        if token.lower() in _SPOKEN_FILLER and token not in known:",
       "        if token.lower() in _SPOKEN_FILLER:")]),
    ("X16", SR, "under",
     "\"the runs are numbered 1 to 0\" comes back when that computer listed nothing",
     [('                if not rows:\n'
       '                    return None, False, ["That computer hasn’t listed any runs, "\n'
       '                                         "so there are no numbers to pick — 0, "\n'
       '                                         "the agent’s own log, still needs a "\n'
       '                                         "bundle to ride."]\n', '')]),
    ("X17", SR, "under",
     "⛔ `--runs 0` IS DROPPED IN SILENCE ON THE ONE CALL THAT UPLOADS, so an "
     "assistant carrying the person's own words forward gets nothing",
     [("            if getattr(args, \"agent_log\", False) or _st_wants_log:",
       "            if getattr(args, \"agent_log\", False):")]),
    ("X18", SR, "under",
     "⛔ THE `--runs` FLAG LEAVES THE CHAT PARSER, so the picker exits 2 on the "
     "one client that reaches it through natural language",
     [('    sl.add_argument("--runs", default="",\n'
       '                    help="which runs, by the numbers shown or by name, "\n'
       '                         "comma-separated; 0 is the agent\'s own log on this host "\n'
       '                         "and all is every run listed (default: every run listed)")\n',
       '')]),
    ("X19", SR, "over",
     "chat's resolver takes `isdigit` again, so a superscript reaches `int()` and "
     "leaves a traceback where a sentence belongs",
     [('        body_ = token[1:] if token[:1] in "+-" else token\n'
       '        if body_.isdecimal() and body_.isascii():',
       '        body_ = token\n'
       '        if body_.isdigit():')]),
    ("X20", SKILL, "under",
     "⛔ THE ROUTING ROW THAT MAKES `--runs` REACHABLE FROM CHAT GOES. The table "
     "is what the assistant reads to decide what to run; the section further down "
     "is not an offer",
     [('| "just the one about X", "only the first two", "not all of them" | the plan '
       'numbers every run — pass those numbers back with `--runs`, comma-separated: '
       '`sr.py send-logs --runs 1,3` (and again on `--confirm`). `--runs 0` is the '
       "agent's own log, `--runs all` is every run listed. A name works too. Do "
       "**not** guess a number the plan did not print |\n", "")]),
]


def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> "str | None":
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
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave, so
    a git check would report dirty on every run and a real leftover mutant would
    be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and a
    runner that only asks `returncode == 0` reads that as red — so one typo in the
    selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(filtered: bool) -> bool:
    purge_pycache(AGENT)
    py = str(AGENT / ".venv" / "bin" / "python")
    suites = MINE.split() if filtered else [ALL_SUITES]
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  AGENT, ENV)
    if out == "nothing-collected":
        raise AssertionError("the agent leg collected NO tests — check the selection")
    return out == "green"


def _selected_count() -> int:
    py = str(AGENT / ".venv" / "bin" / "python")
    out = sh([py, "-B", "-m", "pytest", *MINE.split(), "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=AGENT, env=ENV).stdout
    # ⛔ THE SUMMARY LINE IS "N tests collected in 0.09s" — it does not END with
    # "collected", and a parser that assumed it did returned 0 and refused the run.
    # That refusal is the guard working; this is the parser it was guarding.
    import re as _re
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")
    print("scope: THE WHOLE AGENT SUITE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\nRestore that file, then delete\n    {_INFLIGHT}")
        return 2

    if not unfiltered:
        n = _selected_count()
        print(f"the wave's own files collect {n} test(s)")
        if n < MIN_SELECTED:
            print(f"⛔⛔ TOO FEW (need >= {MIN_SELECTED}) — a selection that matches "
                  "nothing exits 5 and scores every mutant killed. Refusing to run.")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(filtered=not unfiltered):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green\n")

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
            # red on an import error and the mutant banks a kill it never earned.
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
            killed = not run_tests(filtered=not unfiltered)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered)
                if again != killed:
                    flapped = True
                    killed = False
            mark = "✓ killed  " if killed and not flapped else "✗ SURVIVED"
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
    scope = " [whole agent suite]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
