"""Mutation harness — nothing late, stale or doubled about a sign-in; a login answer is login only (2026-09-25).

⛔⛔ WHAT THIS CODE DECIDES. Whether the chat is ever told something that is no longer
true, told it twice, or told it minutes late. Measured on the owner's Telegram
(2026-09-24): a TRUE "✓ Signed in" sat 59 s in Hermes's delivery queue and reached the
chat 19 s AFTER the person had logged out; `login-done` and the watcher announced the
same sign-in 34 s apart in contradicting words; "am I logged in?" came back as a device
lecture; and SKILL.md had the model tear the watcher down on logout, which is why the
queued copy had nothing left to stop it.

  B* — the bridge (bridge.py): the logout that closes every source of "signed in",
       the last look `/updates` AND `POST /signin/ack` each take before anything
       leaves, the one-note-one-sign-in refusal, the ack's seal and its chat scope,
       the instant-delivery triggers and the re-checks they hand the push, the
       steady approval check, and the support-log watch that no longer ends in
       silence — nor in a false "✓ Support has the logs".
  U* — instant delivery (push.py): re-checked before every spawn, one run per job,
       retried ONLY while the gateway holds the job, and off where it must be off.
  P* — the store (prefs.py): whose support-log record it is, and how long it lives.
  S* — the chat client (sr.py): login answers are login only and in ONE wording,
       every reply that says "signed in" tells the bridge, `login` while signed in
       starts nothing, `login-done` after a logout, the sign-in questions' route,
       the minute-anchored watcher schedule and its one-time migration.
  W* — the watcher (sr_attention_poll.py), which reaches the person word for word:
       it never removes itself after a logout (the evidence's reader AND writer),
       never logs to stdout, says the late support-log notice it is handed, and
       opens a sign-in with the chat's own line and nothing after it.
  K* — SKILL.md.

⛔⛔ THE SKEPTIC ROUND (2026-09-25). Three first-pass mutants guarded states no caller
can reach — killed only by a unit assertion, never by a message going wrong — and were
REPLACED under their own ids rather than kept for the count:
  B1 — was the LOGOUT's seal. `_remint_signin` refuses an ended session and the
       `/updates` last look withholds whatever slips past it, so no stale "signed in"
       could leave either way. The seal that IS observable is the ACK's (a duplicate
       after an account-wide delivery); B1 mutates that one now.
  U2 — was `_still` counting a re-check that raises as "yes". No production predicate
       raises: every read beneath them swallows and answers False. U2 mutates the
       retry rule now ("already being fired" only).
  P1 — was the seal moving the watermark backwards. Both callers seal at the live
       session's own capture epoch, so the early return never decided anything
       reachable. P1 mutates the support-log store's uid binding now.
⛔ AND THE GAPS IT NAMED ARE MUTANTS NOW: the ack's last look and scope (B9, B10), the
note drop on logout (B11), every push trigger and its re-check (B12-B15), the bridge's
side of the late support-log notice (B16-B18), the ~55 s approval check (B19), the
push's gate (U4), every "signed in" reply's ack (S6, S7), the one wording everywhere
(S8, S9, W5), the schedule and its migration (S10, S11) and the `__authed__` writer
(W4). Two of them had no test that could fail — the ack was tested only at its
ENTRY, and every approval-check test stepped exactly 60.0 s — and each gained a guard
test in the house style (B9, B19).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT. These files are checked out CRLF on Windows (autocrlf); a text
restore would flip every line ending and the tree would not come back clean.
⛔ U3 WAITS ~10 s ON PURPOSE: the coalescing test polls for its "folded into one" log
line before it gives up, and the mutant never writes it.

  python .mutants/late_stale_login_0925_mutants.py
  python .mutants/late_stale_login_0925_mutants.py B1 U2 W3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
PUSH = "agent/facade/push.py"
PREFS = "agent/facade/prefs.py"
SR = "agent/facade/skill/scripts/sr.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
SKILL = "agent/facade/skill/SKILL.md"

AGENT_SUITES = ("tests/test_signout_closes_signin_0925.py "
                "tests/test_login_answers_login_only_0925.py "
                "tests/test_instant_push_0925.py tests/test_support_log_persist_0925.py "
                "tests/test_device_ask_backoff_0921.py tests/test_signin_once_0901.py "
                "tests/test_sr_stream.py tests/test_prefs.py")
# (cwd, suites) per mutated file — every target here is the agent's, so one tree,
# one conftest, one suite set (and so ONE baseline per invocation).
SUITES = {f: (AGENT, AGENT_SUITES) for f in (BRIDGE, PUSH, PREFS, SR, POLL, SKILL)}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ B — the bridge ═══════════════════════════════════════════════════════
    ("B1", BRIDGE, "⛔⛔ THE ACK NO LONGER SEALS THE WATERMARK — after an account-wide "
     "delivery (claimed at ts - 1 for the one repeat), a chat reply says \"✓ Signed in\" "
     "and the next unscoped tick's re-mint still wins: the sign-in, said twice",
     [("                    sealed = prefs.seal_signin_announce(cap, sess.uid)",
       "                    sealed = None")]),
    ("B2", BRIDGE, "⛔⛔ THE FINISHED FLOW OUTLIVES THE LOGOUT — `/login/remote/poll` keeps "
     "saying `connected`, and `login-done` answers \"✓ Connected as None\" to somebody "
     "who just signed out",
     [("    _drop_finished_remote_flow(state, route)\n    _forget_runs(sess.uid)",
       "    _forget_runs(sess.uid)")]),
    ("B3", BRIDGE, "⛔⛔ THE LAST LOOK IS GONE — a logout landing while `/updates` sat in "
     "Firestore no longer withholds the note it already took: a true-then, false-now "
     "\"✓ Signed in\" leaves after the person logged out",
     [('            if not state.is_current(sess):\n'
       '                log.info("updates (%s): the session ended while this request ran — "',
       '            if False:\n'
       '                log.info("updates (%s): the session ended while this request ran — "')]),
    ("B4", BRIDGE, "⛔ A PUT-BACK / RESTORE / AUTO-START PARK IS NO LONGER REFUSED FOR AN "
     "ENDED SESSION — the note of a sign-in that is over is parked again, on disk, "
     "for the next watcher tick to say",
     [("            refused = sess is not None and self._session is not sess",
       "            refused = False")]),
    ("B5", BRIDGE, "⛔ ONE NOTE, ONE SIGN-IN, UNDONE — a note minted for an EARLIER sign-in "
     "(its topic, its email) is handed out to the live one as if it were news",
     [("    return int(raw) != int(cap)", "    return False")]),
    ("B6", BRIDGE, "⛔⛔ A PLAIN \"✓ SIGNED IN\" SWALLOWS THE NEWS — `status-account` takes "
     "a note that says \"Started “X” on Mac\" and nobody ever says it",
     [("                if mine and (with_news or not _note_has_news(ev)):",
       "                if mine:")]),
    ("B7", BRIDGE, "⛔⛔ THE SIGN-IN PUSH RUNS WITHOUT A RE-CHECK — after a logout, or after "
     "a chat reply already said it, the chat's watcher is still run for a note that is "
     "no longer waiting",
     [("        if not state.is_current(sess):\n"
       "            return False\n"
       "        cur = state.peek_signed_in(uid)\n"
       '        return isinstance(cur, dict) and cur.get("ts") == ts',
       "        return True")]),
    ("B8", BRIDGE, "⛔ THE APPROVAL CHECK FALLS BACK TO THE LADDER AFTER TEN MINUTES — an "
     "owner who says yes two hours in is announced up to half an hour late",
     [("_DEVICE_ASK_STEADY_SECONDS = 6 * 3600", "_DEVICE_ASK_STEADY_SECONDS = 600")]),
    ("B9", BRIDGE, "⛔⛔ THE ACK LOSES ITS LAST LOOK — a logout landing while the ack runs "
     "still answers 200, and `login-done` / `status-account` print \"✓ Signed in\" "
     "after the person logged out (guard test added 2026-09-25: only the ack's ENTRY "
     "check was tested)",
     [("            if not state.is_current(sess):\n"
       '                # ⛔ The session ended while this ran: nothing may say "signed in".',
       "            if False:\n"
       '                # ⛔ The session ended while this ran: nothing may say "signed in".')]),
    ("B10", BRIDGE, "⛔⛔ ONE CHAT'S REPLY TAKES ANOTHER CHAT'S NOTE — the ack matches the "
     "platform only, so the Telegram chat that asked for the link is never told, and a "
     "`login-done` in another Telegram chat relays its news there instead",
     [('\n                            and ev_origin["chat_id"] == chat))',
       "))")]),
    ("B11", BRIDGE, "⛔ THE LOGOUT LEAVES THE ENDED SIGN-IN'S NOTE PARKED, in memory and in "
     "prefs.json — the one step of \"close every source\" that removes the note itself; "
     "only the next sign-in's clear and the one-note-one-sign-in refusal (B5) are left "
     "between it and a chat",
     [("            # outlived the session that produced it.\n"
       '            self.clear_signed_in(why="signed out")\n',
       "            # outlived the session that produced it.\n")]),
    ("B12", BRIDGE, "⛔⛔ A CAPTURED SIGN-IN NO LONGER PUSHES — the note waits for the "
     "watcher's own ~2-minute tick and then Hermes's once-a-minute queue: the late "
     "\"✓ Signed in\" of 2026-09-24, back",
     [("            if state.set_signed_in(base_ev, sess=sess):\n"
       "                _push_signin(state, sess, base_ev)",
       "            state.set_signed_in(base_ev, sess=sess)")]),
    ("B13", BRIDGE, "⛔ THE AUTO-START WORKER'S NOTE NO LONGER PUSHES — \"Started “X” on "
     "Mac\" waits for the tick and the queue, minutes after the run began",
     [("    if state.set_signed_in(ev, sess=sess):\n"
       "        _push_signin(state, sess, ev)",
       "    state.set_signed_in(ev, sess=sess)")]),
    ("B14", BRIDGE, "⛔ A FINISHED RUN IS NEVER PUSHED — the 🎉 waits for the watcher's own "
     "tick and Hermes's queue, minutes late",
     [('            reason = "run-completed" if e.get("status") != "completed" else None',
       "            reason = None")]),
    ("B15", BRIDGE, "⛔ THE APPROVAL PUSH RUNS WITHOUT A RE-CHECK — after a logout, or once "
     "the answer was already delivered, the chat's watcher is still run for news that "
     "is no longer news",
     [('    push.request(origin, reason="device-answered",\n'
       "                 still_valid=lambda: state.is_current(sess)\n"
       "                 and bool(prefs.get_device_ask(uid)))",
       '    push.request(origin, reason="device-answered",\n'
       "                 still_valid=lambda: True)")]),
    ("B16", BRIDGE, "⛔⛔ \"NO ANSWER YET\" GOES OUT UNDER `supportLogs` — a watcher from "
     "before 2026-09-25 renders every `supportLogs` that is not \"failed\" as "
     "\"✓ Support has the logs\": a false success about logs that never arrived",
     [('                    out["supportLogsLate"] = {\n'
       '                        "code": code,',
       '                    out["supportLogs"] = {\n'
       '                        "code": code, "status": "late",')]),
    ("B17", BRIDGE, "⛔ THE LATE NOTICE IS NEVER MARKED SAID — the record stays open, the "
     "bridge hands it out on every tick, and as the chat's OLDEST open request it comes "
     "first forever: a newer request's \"✓ Support has the logs\" is never said",
     [("                    self._post_send.append(_mark_late)\n", "")]),
    ("B18", BRIDGE, "⛔ THE SUPPORT-LOG REQUEST IS NEVER RECORDED — nothing on this host "
     "remembers it was asked, so \"✓ Support has the logs\" is never said, restart or "
     "not, and `--status` loses the device name",
     [("        prefs.put_log_request(code, record)\n", "        pass\n")]),
    ("B19", BRIDGE, "⛔ THE APPROVAL CHECK WAITS A FULL 60 s — a one-minute tick that lands a "
     "hair early is refused, and the owner's yes is announced a whole minute later "
     "(guard test added 2026-09-25: every check test stepped exactly 60.0 s)",
     [("_DEVICE_ASK_CHECK_SECONDS = 55.0", "_DEVICE_ASK_CHECK_SECONDS = 60.0")]),
    # ═══ U — instant delivery ═════════════════════════════════════════════════
    ("U1", PUSH, "⛔⛔ NO RE-CHECK BEFORE THE SPAWN — the person logged out between the "
     "event and the run, and the watcher is run anyway",
     [("            live = [r for r, v in todo if _still(v)]",
       "            live = [r for r, v in todo]")]),
    ("U2", PUSH, "⛔ EVERY OUTCOME BUT \"SENT\" IS RETRIED — a timeout or a failed run, which "
     "may have delivered before it died, runs the watcher up to four more times, where "
     "the rule is: retry ONLY \"already being fired\"",
     [('            if outcome != "busy":\n                return outcome',
       '            if outcome == "sent":\n                return outcome')]),
    ("U3", PUSH, "⛔ TWO RUNS OF ONE WATCHER AT ONCE — a request while a run is in flight "
     "starts a second concurrent run instead of one follow-up, and the two race each "
     "other's de-dup state (a doubled message)",
     [("            if pending is not None:\n"
       "                pending.append((reason, still_valid))",
       "            if False:\n"
       "                pending.append((reason, still_valid))")]),
    ("U4", PUSH, "⛔⛔ THE KILL-SWITCH AND THE NOT-HERMES GATE ARE IGNORED — "
     "`DG_AGENT_PUSH=0` in the field, or an OpenClaw runtime on a computer that also "
     "has a Hermes install, still runs `hermes cron run` on every piece of news",
     [("            why = self._why_not()\n            if why:",
       "            why = self._why_not()\n            if False:")]),
    # ═══ P — the store ═════════════════════════════════════════════════════════
    ("P1", PREFS, "⛔⛔ THE SUPPORT-LOG STORE FORGETS WHOSE REQUEST IT IS — this host re-logs "
     "in as different accounts, and the next account's chat is told about the PREVIOUS "
     "account's computer and code",
     [('            if isinstance(c, str) and _log_request_live(r, now) and r.get("uid") == uid}',
       "            if isinstance(c, str) and _log_request_live(r, now)}")]),
    ("P2", PREFS, "⛔ THE SUPPORT-LOG RECORD IS FORGOTTEN WHEN THE WATCH ENDS — the one "
     "\"no answer yet\" notice has nothing left to be said from, so the watch ends in "
     "silence again",
     [("_LOG_REQUEST_TTL = 24 * 3600", "_LOG_REQUEST_TTL = 1800")]),
    # ═══ S — the chat client ═══════════════════════════════════════════════════
    ("S1", SR, "⛔⛔ \"AM I LOGGED IN?\" IS A DEVICE LECTURE AGAIN — `status-account` "
     "glues the no-computer screen to the sign-in line on an empty account",
     [('            lines = [_connected_msg((ack.get("email") if acode == 200 else None)\n'
       '                                    or body.get("email") or body.get("uid"))]',
       '            lines = [_connected_msg((ack.get("email") if acode == 200 else None)\n'
       '                                    or body.get("email") or body.get("uid"))]\n'
       '            if not ((_get("/devices")[1] or {}).get("devices")):\n'
       '                lines += _no_device_lines()')]),
    ("S2", SR, "⛔⛔ \"LOG ME IN\" WHILE SIGNED IN STARTS A NEW FLOW — the bridge throws the "
     "parked note away and the account switches in a step nobody asked for",
     [("    already, status = _already_signed_in()", "    already, status = None, {}")]),
    ("S3", SR, "⛔⛔ `login-done` TRUSTS THE FLOW'S \"connected\" OVER THE SESSION — "
     "somebody who just logged out is told they are signed in",
     [('        if not body.get("authed"):\n'
       "            return _emit(body, args.json, [_SIGNED_OUT_LINE])\n"
       '        return _signed_in_reply(args, body, body.get("email") or body.get("uid"),',
       '        return _signed_in_reply(args, body, body.get("email") or body.get("uid"),')]),
    ("S4", SR, "⛔ \"did the login work?\" / \"login status\" START A NEW SIGN-IN (rule 5's "
     "`\\blogin\\b`) — which also makes the bridge throw away the parked note",
     [('            _NL_LOGIN_CHECK.fullmatch(low):\n        return ["status-account"], None',
       '            False:\n        return ["status-account"], None')]),
    ("S5", SR, "⛔ THE CRON ROW'S FIRST RUN IS OFF THE MINUTE — Hermes re-anchors it "
     "without firing and skips the very run that carries the sign-in",
     [("        return datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()",
       "        return datetime.now(timezone.utc).isoformat()")]),
    ("S6", SR, "⛔⛔ `status-account` SAYS \"SIGNED IN\" WITHOUT TELLING THE BRIDGE — the "
     "watcher repeats the sign-in after the chat's own answer (the 2026-09-24 double), "
     "and a session that ended between the two reads is still called signed in",
     [('        acode, ack = _ack_signed_in("status-account")',
       "        acode, ack = 0, {}")]),
    ("S7", SR, "⛔ `login-done` ACKS WITHOUT OFFERING TO RELAY THE NEWS — it answers a plain "
     "\"✓ Signed in\" and the watcher then says \"✓ Signed in … Started “X” on Mac\": "
     "the sign-in twice, the news late",
     [('    acode, ack = _ack_signed_in("login-done", with_news=True)',
       '    acode, ack = _ack_signed_in("login-done")')]),
    ("S8", SR, "⛔⛔ `login-done` GLUES THE NO-COMPUTER SCREEN ONTO A PLAIN SIGN-IN — the "
     "\"Add a computer … Or ask me for a public computer\" run-on the owner was sent on "
     "2026-09-24 in answer to a login",
     [("    return _emit(body, args.json, [_connected_msg(who)])",
       "    return _emit(body, args.json, [_connected_msg(who)] + (\n"
       '        [] if (_get("/devices")[1] or {}).get("devices") else _no_device_lines()))')]),
    ("S9", SR, "⛔⛔ THE CHAT'S SIGN-IN LINE DRIFTS FROM THE WATCHER'S — \"✓ Connected as X "
     "— you're all set\" in the reply, \"✓ Signed in as X.\" from the watcher: one "
     "sign-in, two wordings (2026-09-24)",
     [("    return f\"✓ Signed in{(' as ' + who) if who else ''}.\"",
       "    return f\"✓ Connected{(' as ' + who) if who else ''} — you're all set.\"")]),
    ("S10", SR, "⛔⛔ A NEW WATCHER IS ARMED ON THE \"every 1m\" INTERVAL EVEN WHERE CRON "
     "WORKS — measured at ~113 s between runs: every note waits up to two minutes "
     "before Hermes's queue even sees it",
     [("    return dict(_STREAM_CRON_SCHEDULE if _runtime_has_croniter() else _STREAM_SCHEDULE)",
       "    return dict(_STREAM_SCHEDULE)")]),
    ("S11", SR, "⛔ EVERY WATCHER ALREADY ARMED KEEPS ITS ~2-MINUTE INTERVAL FOREVER — the "
     "arm is idempotent by name again, so the minute-anchored schedule reaches only "
     "chats armed after the change",
     [("                if not moved:\n"
       "                    return True  # genuinely armed — idempotent no-op",
       "                return True  # genuinely armed — idempotent no-op")]),
    # ═══ W — the watcher (reaches the person with no model turn) ═══════════════
    ("W1", POLL, "⛔⛔ THE WATCHER DELETES ITSELF AFTER A LOGOUT — a chat that was signed "
     "in but whose note a reply took first has no trace of it, and its 401s count to "
     "the give-up (owner decision 3: only `agent disconnect` removes it)",
     [('    signed_in_before = ("__signed_in_ts__" in prior or "__authed__" in prior',
       '    signed_in_before = ("__signed_in_ts__" in prior')]),
    ("W2", POLL, "⛔⛔ THE WATCHER'S LOG GOES TO STDOUT — and stdout IS the chat message, so "
     "every log line is posted into the chat word for word",
     [('        with open(path, "ab") as fh:\n'
       '            fh.write(f"{stamp} watcher[{os.getpid()}] {_mask_emails(msg)}\\n"\n'
       '                     .encode("utf-8", "replace"))',
       '        print(f"{stamp} watcher[{os.getpid()}] {_mask_emails(msg)}")')]),
    ("W3", POLL, "⛔ THE LATE SUPPORT-LOG NOTICE IS DROPPED ON THE WAY IN — the bridge "
     "sends `supportLogsLate` once and marks it said, the watcher never prints it: the "
     "watch ends in silence after all",
     [("            (late if isinstance(late, dict) else None))",
       "            None)")]),
    ("W4", POLL, "⛔⛔ THE WATCHER NO LONGER RECORDS THAT IT WAS SIGNED IN — a chat whose "
     "note a reply took first keeps no trace, and after a logout its 401s count to the "
     "give-up and delete it (W1's writer half)",
     [('    new_state["__authed__"] = 1\n', "")]),
    ("W5", POLL, "⛔ A PLAIN SIGN-IN FROM THE WATCHER SAYS MORE THAN THE CHAT DID — "
     "\"✓ Signed in as X. Just tell me what to research.\" against the reply's "
     "\"✓ Signed in as X.\" (2026-09-24)",
     [("    # research\", which the chat's own answer did not say (owner, 2026-09-25).\n"
       "    return first",
       "    # research\", which the chat's own answer did not say (owner, 2026-09-25).\n"
       '    return f"{first}\\n\\nJust tell me what to research."')]),
    # ═══ K — SKILL.md ══════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ THE MODEL IS TOLD TO TEAR THE WATCHER DOWN ON LOGOUT AGAIN — the "
     "instruction that let the 2026-09-24 queued copy go out with nothing to stop it",
     [('"how\'s it going / send the brief link" just run `sr.py status`. **Never remove it\n'
       "yourself — not on `logout` either**: signed out it stays silent and the next\n"
       "sign-in reuses it.",
       '"how\'s it going / send the brief link" just run `sr.py status`. On `logout`, tear\n'
       'it down too: `cronjob(action="list")` → the `sr-stream…` job →\n'
       '`cronjob(action="remove", job_id=…)`.')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
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

    only = set(sys.argv[1:])
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
