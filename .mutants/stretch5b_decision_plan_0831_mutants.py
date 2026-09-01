"""Mutation harness — what chat TELLS a person about a blocked run, and what it
actually WRITES when they answer.

The owner's words: *"If the run actually needs an API key, it should ask for an
API key. And if it's signed out, that's when it should ask for sign in."* Plus:
make retry actually resume on the crash cards, stop offering a Skip that does not
exist, and stop discarding `details`.

⛔⛔ THE DANGEROUS DIRECTION HERE IS THE HELPFUL GUESS. Every one of the defects
this wave fixed was code being accommodating: a kind literal three situations
share, matched loosely; a command minted because *something* ought to be written;
a first-match scan that took whichever verb came first. Each looked like
robustness. Two of them were destructive —

  * chat's "skip" on the browser-launch card reached a gate that TERMINATES THE
    PIPELINE, and reported "Skipping the current blocker";
  * chat's "retry" on a Pro-tier card returned `continue_anyway` (first in that
    card's ordered list) and DOWNGRADED THE PERSON TO THE FREE TIER, while
    printing "↻ Retrying — resuming the run".

So the mutants below are weighted toward OVER-correction: putting the guess back,
widening a discriminator, collapsing two answers that must stay distinct. A fix
that "simplifies" any of those re-introduces a lie.

⛔ FOUR THINGS THIS HARNESS IS WATCHING FOR SPECIFICALLY.

  1. **A discriminator that widens.** `envErrors` is what separates "needs an API
     key" from "is signed out". Drop it, or move it after the agent test, and the
     owner's first ask is undone with one line.
  2. **A None that becomes a command.** `resume is None` and `skip is None` mean
     THIS CARD HAS NO SUCH BUTTON. Any mutant that turns one into a fallback
     command restores the phantom — including the hidden Stop.
  3. **A transport that reverts.** A crash card resumed by per-run command is
     written, marked processed, and executed by nobody. The queue is the only
     transport that reaches a run whose listener is gone.
  4. **A consumer that stops consuming.** ⛔⛔ The planner is a helper; the two
     chat scripts are the product. Mutants that leave the planner intact and cut
     the scripts' use of it must die, or "the helper is tested" would be the only
     thing true here.

⛔⛔ ANCHOR UNIQUENESS IS CHECKED, NOT ASSUMED. A presence test plus a
first-occurrence replace mutates a place the mutant was never about and reports a
kill.

⛔ AND A SKIP IS NOT A PASS. pytest exits 0 for a run in which tests were skipped
and for a run that collected far fewer than it should. This runner reads the
summary line and REFUSES a verdict rather than guessing.

    .venv/bin/python .mutants/stretch5b_decision_plan_0831_mutants.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BRIDGE = "agent/facade/bridge.py"
REST = "agent/facade/firestore_rest.py"
SR = "agent/facade/skill/scripts/sr.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
RESEARCH = "research.py"
MUTATED_FILES = (BRIDGE, REST, SR, POLL, RESEARCH)

# The agent tree keeps its own pytest rootdir and imports `facade`, so this leg
# runs from `agent/`. The neighbouring route + client suites come along because
# several mutants edit shared seams (the row literal, the resolve route, sr.py's
# line builders) and a harness that ran only the new files would call collateral
# damage a kill.
AGENT_SUITES = (
    "tests/test_decision_plan_0831.py "
    "tests/test_bridge_resolve_0831.py "
    "tests/test_sr_attention_copy_0831.py "
    "tests/test_bridge_device.py "
    "tests/test_bridge_routes.py "
    "tests/test_sr_client.py "
    "tests/test_sr_stream.py "
    "tests/test_firestore_rest.py"
)
AGENT_FLOOR = 380

# The one research.py edit (the HV card's own latched verdict) is covered from
# the root tree, which is where research.py's suites live.
ROOT_SUITES = ("tests/test_hv_intent_mirror_0831.py tests/test_alert_intents.py "
               "tests/test_phase5_gate_migration_955.py")
ROOT_FLOOR = 45

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# A survivor is re-run before it is believed: these suites start a real loopback
# HTTP server per test, and a port race would otherwise be reported as a suite
# gap that does not exist.
SURVIVOR_CONFIRMATIONS = 3

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ══ A — the API key vs the sign-in wall (the owner's first ask) ══════════
    ("A1", BRIDGE, "under",
     "⛔⛔ THE OWNER'S FIRST ASK, UNDONE IN ONE LINE. The env-check card stops "
     "being told apart from a sign-in wall, so a run that needs an Anthropic API "
     "key is once again told to sign in on the device — under a headline that "
     "correctly says it needs a key",
     [('        if pd.get("envErrors"):\n            return "env_missing_key"',
       '        if False:\n            return "env_missing_key"')]),

    ("A2", BRIDGE, "over",
     "⛔ THE DISCRIMINATOR WIDENS: any login card with an `agent` is read as the "
     "env card, so a real mid-run sign-out is answered with 'add an API key'. The "
     "over-correction of A1 and just as wrong",
     [('        if pd.get("envErrors"):\n            return "env_missing_key"',
       '        if pd.get("envErrors") or pd.get("agent"):\n            return "env_missing_key"')]),

    # ⛔⛔ A3 WAS THE SAME MUTANT AS A1 AND ITS KILL WAS INFLATING THE SCORE.
    # Cross-verify measured it: deleting the envErrors branch and replacing its
    # test with `if False` produce byte-identical behaviour, so 44 mutants were
    # measuring 43 behaviours. Replaced with a defect at the OTHER end of the
    # same fix — the classification stays right and the SENTENCE lies, which is
    # the half a person actually reads. (A genuine reorder cannot be written
    # here: no production writer emits an env card carrying an `agent`, so
    # swapping the two tests is equivalent too, and an equivalent mutant is a
    # harness bug rather than coverage.)
    ("A3", BRIDGE, "under",
     "⛔⛔ THE CARD IS CLASSIFIED CORRECTLY AND THE SENTENCE STILL SAYS 'SIGN "
     "IN'. A half-fix that lands the plumbing and reverts the copy — and the copy "
     "is the entire thing the person reads, so the owner's first ask is undone "
     "with every test of the classifier still green",
     [('    if card == "env_missing_key":\n'
       '        return (f"Add an Anthropic API key on {M} (Account → API Config), then reply "\n'
       '                "“retry”. Reply “skip” to carry on without one.")',
       '    if card == "env_missing_key":\n'
       '        return (f"Sign in to {P} in the browser open on {M}, then reply “retry”. "\n'
       '                "Reply “skip” to skip the sign-in check.")')]),

    ("A4", BRIDGE, "over",
     "⛔ A JSON `true` PHASE SATISFIES `phase >= 1` (bool is an int subclass), so "
     "a malformed phase-0 walk is resolved as a work-tab wall — and its skip "
     "drops a platform instead of the sign-in check",
     [('        if agent and isinstance(phase, int) and not isinstance(phase, bool) and phase >= 1:',
       '        if agent and isinstance(phase, int) and phase >= 1:')]),

    ("A5", BRIDGE, "under",
     "the three login situations collapse back into one card, so every one of "
     "them gets the phase-0 walk's copy and the phase-0 walk's skip",
     [('        if agent and isinstance(phase, int) and not isinstance(phase, bool) and phase >= 1:\n'
       '            return "login_worktab"\n', '')]),

    # ══ B — retry must actually resume ══════════════════════════════════════
    ("B1", BRIDGE, "under",
     "⛔⛔ THE CRASH-CARD RETRY GOES BACK TO A PER-RUN COMMAND — written, marked "
     "processed, and consumed by nobody, because run_pipeline returned and tore "
     "the listener down before the card was ever drawn. Chat says the run is "
     "resuming and nothing moves",
     [('    if card == "crash_login_interrupt":\n        return (_QUEUE_RESUME, None)\n'
       '    if card == "crash_loop":\n        return (_QUEUE_RESUME, _CLEAR_CARD)',
       '    if card == "crash_login_interrupt":\n'
       '        return (_cmd_spec({"action": "retry_phase", **_ph(phase)}, "resume"), None)\n'
       '    if card == "crash_loop":\n'
       '        return (_cmd_spec({"action": "retry_phase", **_ph(phase)}, "resume"), _CLEAR_CARD)')]),

    ("B2", BRIDGE, "under",
     "the two crash cards stop being recognised at all, so both fall to the "
     "generic scan — whose known verbs `resume_from_checkpoint` and "
     "`discard_restart_prompt` are not, so the card offers nothing and the person "
     "is sent to the app for a run chat could have resumed",
     [('        if "resume_from_checkpoint" in acts:\n'
       '            return "crash_loop" if "discard_restart_prompt" in acts else "crash_login_interrupt"',
       '        if False:\n'
       '            return "crash_loop" if "discard_restart_prompt" in acts else "crash_login_interrupt"')]),

    ("B3", BRIDGE, "over",
     "the two crash cards stop being told apart, so the login-interrupt card "
     "acquires a Skip it never had — and that Skip clears a live card",
     [('            return "crash_loop" if "discard_restart_prompt" in acts else "crash_login_interrupt"',
       '            return "crash_loop"')]),

    ("B4", BRIDGE, "under",
     "⛔⛔ A RUN PAUSED BY A BACKEND RESTART GOES BACK TO HAVING NO ANSWER AT "
     "ALL. The watchdog still pushes 'needs you' for it (it is in the live-stuck "
     "list), and every reply is refused with 'this run isn't waiting on a "
     "decision' — for a run the web app offers a working Resume on",
     [('    status = doc.get("status")\n    if status in _STATUS_CARD_OF:\n'
       '        return _status_plan(status)',
       '    status = doc.get("status")\n    if False:\n'
       '        return _status_plan(status)')]),

    ("B5", BRIDGE, "over",
     "the status arm wins over a real card, so a run that is BOTH restart-paused "
     "and carrying a sign-in card is answered with 'reply retry' — losing the "
     "actual thing the person was asked to do",
     [('    plan = _decision_plan(doc.get("pendingDecision"))\n'
       '    if plan is not None:\n        return plan\n    status = doc.get("status")',
       '    plan = _decision_plan(doc.get("pendingDecision"))\n'
       '    status = doc.get("status")\n'
       '    if status in _STATUS_CARD_OF:\n        return _status_plan(status)\n'
       '    if plan is not None:\n        return plan')]),

    ("B6", BRIDGE, "under",
     "⛔ THE SILENT-DROP GUARD GOES. A resume with no backendRunId is enqueued "
     "anyway — and the backend deletes that queue doc with a local WARN and no "
     "write-back, so chat reports a resume that evaporated where nobody can see",
     [('                    if not brid:\n'
       '                        self._json(409, {\n'
       '                            "error": "this run has no checkpoint to resume from — "\n'
       '                                     "start a new research instead",\n'
       '                            "reason": "no_checkpoint", "card": plan["card"]})\n'
       '                        return\n', '')]),

    ("B7", BRIDGE, "under",
     "⛔ /research/{id}/resume goes back to a false 200 for a restart-paused run: "
     "the per-run command is written to a listener that died with the old daemon, "
     "and chat prints '▶ Resumed'",
     [('            _plan = _run_plan(doc) if action == "resume" else None',
       '            _plan = None')]),

    ("B8", BRIDGE, "over",
     "⛔ EVERY resume takes the queue transport, so a run the person merely "
     "PAUSED — whose listener is alive and waiting — is restarted from its "
     "checkpoint instead of un-paused",
     [('            _queue = bool(_spec) and _spec["transport"] == "queue_resume"',
       '            _queue = action == "resume"')]),

    ("B9", REST, "over",
     "the resume queue doc carries a `config`, which the backend merges "
     "PERMANENTLY into the run's config.json — a resume silently rewrites the "
     "run's own configuration",
     [('            "email": email,\n            "timestamp": now_ms,\n'
       '            "viaAgent": True,\n        }',
       '            "email": email,\n            "config": {},\n'
       '            "timestamp": now_ms,\n            "viaAgent": True,\n        }')]),

    ("B10", REST, "under",
     "⛔ `submittedBy` drops off the resume payload. The queue create rule "
     "requires it to equal the caller's uid, so every checkpoint resume is denied "
     "by Firestore — and surfaces as 'could not reach the research store'",
     [('            "submittedBy": uid,   # rules-pinned: must equal request.auth.uid\n', '')]),

    ("B11", REST, "under",
     "the resume doc loses its backendRunId, so the backend cannot find the run's "
     "folder and drops the request",
     [('            "backendRunId": backend_run_id,\n', '')]),

    # ══ C — the skip that does not exist ════════════════════════════════════
    # ⛔ REWRITTEN after cross-verify: the first version's rationale was WRONG
    # about what it mutated. `if have and (scan(True) or scan(False))` changes
    # nothing for the browser-launch card, because that card's `[retry_phase]`
    # makes scan(True) truthy — it only fired when BOTH scans were empty. The
    # mutation below is the one that actually restores the hidden Stop.
    ("C1", BRIDGE, "over",
     "⛔⛔ THE PHANTOM SKIP COMES BACK, AND WITH IT THE HIDDEN STOP. Any card "
     "lacking a skip is handed a generic skip_phase — and on the phase-0 "
     "browser-launch card that command reaches a gate which TERMINATES THE "
     "PIPELINE for anything that is not 'retry', reported to the person as "
     "'Skipping the current blocker'",
     [('    if have:\n        return scan(True), scan(False)',
       '    if have:\n        return scan(True), (scan(False) or _cmd_spec(\n'
       '            {"action": "skip_phase", **_ph(pd.get("phase"))}, "move past this step"))')]),

    ("C10", BRIDGE, "over",
     "⛔ A CARD THAT OFFERS NEITHER VERB IS HANDED BOTH. This is what the first "
     "C1 actually did, kept as its own mutant with an honest rationale: the "
     "no-actions compatibility shim fires for a card that HAS actions and matches "
     "none of them — chat_mode's continue/stop, for instance",
     [('    if have:\n        return scan(True), scan(False)',
       '    if have and (scan(True) or scan(False)):\n        return scan(True), scan(False)')]),

    ("C2", BRIDGE, "over",
     "⛔ THE REFUSAL BECOMES A WRITE. /resolve stops distinguishing 'no card' "
     "from 'this card has no such button' and acts on the other verb's spec, so "
     "asking to skip performs a retry",
     [('            spec = plan["resume"] if intent == "retry" else plan["skip"]',
       '            spec = (plan["resume"] if intent == "retry" else plan["skip"]) \\\n'
       '                or plan["resume"] or plan["skip"]')]),

    ("C3", BRIDGE, "under",
     "the 409 refusal is dropped, so a missing action falls through to a "
     "transport read on None and the route 500s — the person gets a bridge error "
     "for a question with a clear answer",
     [('            if spec is None:\n'
       '                self._json(409, {"error": _no_action_sentence(plan, intent),\n'
       '                                 "reason": "no_such_action",\n'
       '                                 "card": plan["card"],\n'
       '                                 "offers": _plan_offers(plan)})\n'
       '                return\n', '')]),

    ("C4", BRIDGE, "over",
     "⛔⛔ THE WORK-TAB SKIP REVERTS TO skip_init_verify — which that loop reads "
     "as the user tapping RETRY, so it re-probes the still signed-out page and "
     "re-cards the same wall. Forever. A skip that is a retry",
     [('        return (_cmd_spec({"action": "retry_phase", **_ph(phase)}, "check the sign-in again"),\n'
       '                drop)',
       '        return (_cmd_spec({"action": "retry_phase", **_ph(phase)}, "check the sign-in again"),\n'
       '                _cmd_spec({"action": "skip_init_verify"}, "skip the sign-in check"))')]),

    ("C5", BRIDGE, "over",
     "⛔⛔ `continue_anyway` IS A RESUME AGAIN. It is the FIRST token in the "
     "Pro-tier card's ordered list, so a chat 'retry' presses Continue with Free "
     "— the person is moved to the free tier while being told the run is resuming",
     [('_RESUME_ACTIONS = frozenset({\n'
       '    "retry_phase", "retry_agent", "resume", "retry_init_verify",\n})',
       '_RESUME_ACTIONS = frozenset({\n'
       '    "retry_phase", "retry_agent", "resume", "retry_init_verify", "continue_anyway",\n})')]),

    ("C6", BRIDGE, "over",
     "⛔ THE PHASE-2 PRO CARD GETS ITS RETRY BACK — retry_phase(2), the one "
     "command research.py deliberately withholds there because a phase restart "
     "cancels run_phase2 and nukes every in-flight deep research",
     [('        resume = None if ph == 2 else _cmd_spec({"action": "retry_phase", **_ph(phase)},\n'
       '                                                "re-check the plan")',
       '        resume = _cmd_spec({"action": "retry_phase", **_ph(phase)}, "re-check the plan")')]),

    ("C7", BRIDGE, "over",
     "a Cloudflare wall is offered a Resume the gate will refuse — trying only "
     "makes Cloudflare ask harder, which the card's own copy says",
     [('    if card == "hv_wall":\n        return (None, drop)',
       '    if card == "hv_wall":\n        return (_cmd_spec({"action": "resume"}, "carry on"), drop)')]),

    ("C8", BRIDGE, "over",
     "an unrecognised card kind mints a plausible command again — the root of "
     "every phantom in this wave, and the one that will fire on a kind a LATER "
     "backend introduces",
     [('    return (None, None)  # unknown',
       '    return _generic_offers(pd)  # unknown')]),

    ("C9", BRIDGE, "over",
     "⛔ `offers` reports both verbs regardless of what the card holds, so the "
     "row advertises a Skip the route will refuse — the row and the route "
     "disagreeing again, which is the whole property this wave bought",
     [('    return [v for v in ("retry", "skip")\n'
       '            if plan.get("resume" if v == "retry" else "skip") is not None]',
       '    return ["retry", "skip"]')]),

    # ══ D — the discarded sentence ══════════════════════════════════════════
    ("D1", BRIDGE, "under",
     "⛔ `details` is dropped again, so the crash card is once more a three-word "
     "headline with no instruction — the sentence telling you to sign back in "
     "FIRST never reaches chat",
     [('    details = pd.get("details")\n'
       '    if not isinstance(details, str) or not details.strip():\n'
       '        details = None',
       '    details = None\n'
       '    if False:\n'
       '        details = None')]),

    ("D2", BRIDGE, "over",
     "the cap goes, so a caller-authored `details` of any length rides a row that "
     "has no byte limit of its own",
     [('    elif len(details) > _DETAILS_MAX:\n'
       '        details = details[:_DETAILS_MAX].rstrip() + "…"\n', '')]),

    ("D3", BRIDGE, "over",
     "a whitespace-only `details` is shipped as a detail, so every sign-in card "
     "grows an empty second line",
     [('    if not isinstance(details, str) or not details.strip():',
       '    if not isinstance(details, str):')]),

    # ══ E — the consumers. ⛔⛔ A PLANNER NOBODY CALLS PROVES NOTHING ════════
    ("E1", SR, "under",
     "⛔⛔ sr.py IGNORES THE BRIDGE'S ANSWER and goes back to guessing from the "
     "kind literal — the planner is intact, every planner test still passes, and "
     "the person is told to sign in for a missing API key again",
     [('    action = r.get("attentionAction")\n    if action:',
       '    action = None\n    if action:')]),

    ("E2", SR, "under",
     "the card's own sentence stops being rendered, so (d) is undone at the "
     "surface while the field it needs is still on the wire",
     [('    det = r.get("attentionDetails") or (pd.get("details") if isinstance(pd, dict) else None)\n'
       '    if det:\n        lines.append(f"  ↳ {det}")\n', '')]),

    ("E3", SR, "over",
     "⛔⛔ ABSENT OFFERS IS READ AS EMPTY OFFERS, so a current script against an "
     "older bridge refuses every retry and every skip — the update makes chat "
     "stop working rather than start telling the truth",
     [('    if offers is None or verb in offers:\n        return None',
       '    if offers and verb in offers:\n        return None')]),

    ("E12", SR, "over",
     "⛔⛔ A RUN WITH NO BLOCKER IS TOLD IT HAS NO RETRY. An unblocked run also "
     "carries an empty offers list, and it means 'there is no card' rather than "
     "'this card has no Retry' — so somebody whose run was streaming along fine "
     "is told to open the app about a problem that does not exist",
     [('    if not run.get("needsAttention"):\n        return None\n', '')]),

    ("E13", SR, "under",
     "⛔ THE OVER-CORRECTION OF E12: the guard swallows EVERY refusal, so the "
     "phantom skip is offered again on cards that have none — including the one "
     "whose skip ends the run",
     [('    if not run.get("needsAttention"):\n        return None\n',
       '    return None\n')]),

    ("E4", SR, "under",
     "the local refusal goes, so chat posts the request anyway — harmless at the "
     "route, but the person is told 'couldn't skip' rather than what the card "
     "actually offers",
     [('        refusal = _refuse_if_not_offered(run, "skip")\n'
       '        if refusal:\n            return _emit(body, args.json, refusal, 1)\n', '')]),

    ("E5", SR, "over",
     "⛔ THE OVERCLAIM RETURNS: a checkpoint resume — a REQUEST the research "
     "computer can still decline without telling us — is reported as 'resuming "
     "the run'",
     [('    if b2.get("transport") == "queue_resume":\n'
       '        return _emit(b2, args.json,\n'
       '                     [f"↻ Asked your computer to pick “{title}” up from its last checkpoint."])\n',
       '')]),

    ("E6", SR, "under",
     "the legacy branch's API-key line goes, so (a) stops landing against a "
     "bridge that has not been updated — the one surface where the wrong line "
     "ever fired",
     [('    if kind == "login_required" and isinstance(pd, dict) and pd.get("envErrors"):\n'
       '        lines.append("  → add an Anthropic API key on the device (Account → API "\n'
       '                     "Config), then tell me to retry.")\n    elif kind == "login_required":',
       '    if kind == "login_required":')]),

    ("E7", POLL, "under",
     "⛔⛔ THE PROACTIVE PUSH IGNORES THE CARD and goes back to offering 'retry "
     "or skip' on every blocker — including the one whose Skip ends the run and "
     "the two where neither verb exists. This is the surface a person is told "
     "about a blocker WITHOUT ASKING",
     [('    act = run.get("attentionAction")\n    if not act:',
       '    act = None\n    if not act:')]),

    ("E8", POLL, "over",
     "⛔ THE SWALLOWED NOTICE COMES BACK. The change key drops the action half, "
     "so a second, different blocker whose reason text matches the first is never "
     "announced — the run sits blocked in silence",
     [('    return (run.get("attention") or "") + "\\x1f" + (run.get("attentionAction") or "")',
       '    return run.get("attention") or ""')]),

    ("E9", POLL, "over",
     "⛔ A STATE FILE FROM AN OLDER SCRIPT RE-ANNOUNCES EVERYTHING. The two-part "
     "key is compared against a file that has only the one part, so every live "
     "blocker fires again on the first tick after an update",
     [('        if "akey" in prior:\n            changed = prior.get("akey") != akey\n'
       '        else:\n            changed = (prior.get("attention") or "") != attention',
       '        changed = prior.get("akey", "") != akey')]),

    ("E10", BRIDGE, "under",
     "⛔ /research/{id} stops carrying the computed fields, so `sr status` prints "
     "no blocker line at all for a run blocked by STATUS while `sr updates` "
     "prints one — the same run, two answers, depending which command you asked",
     [('            _doc_view["attentionAction"] = _act\n'
       '            _doc_view["attentionDetails"] = _det\n'
       '            _doc_view["attentionOffers"] = _offers\n', '')]),

    ("E11", BRIDGE, "under",
     "the row stops carrying them, so the watchdog — which never receives "
     "pendingDecision at all — has nothing to work from and every push reverts",
     [('                    "attentionAction": _act,\n'
       '                    "attentionDetails": _det,\n'
       '                    "attentionOffers": _offers,\n', '')]),

    # ══ H — the paths cross-verify measured as UNEXECUTED by any assertion ══
    # ⛔ Found by INSTRUMENTING the suite, not by reading it: three reachable
    # lines in the new planner ran zero times under every assertion in it. Each
    # of these mutants survived before the pins that now cover them.
    ("H1", BRIDGE, "over",
     "⛔⛔ THE MOST COMMON BLOCKER'S SENTENCE BREAKS AND NOBODY NOTICES. An agent "
     "that failed or stalled reaches chat through the generic mirror, and the "
     "{Ag} placeholder stops being substituted — so a person is told to “restart "
     "{Ag}”, verbatim, braces and all",
     [('                return _cmd_spec(dict(cmd),\n'
       '                                 phrase.replace("{Ag}", _agent_display(_lc(cmd.get("agent")) or ag)))',
       '                return _cmd_spec(dict(cmd), phrase)')]),

    ("H2", BRIDGE, "over",
     "⛔ THE PRO CARD'S PHASE-0 SKIP DROPS A PLATFORM instead of bypassing the "
     "sign-in verification walk — while its own sentence still says “skip the "
     "sign-in check”. The same mismatch the work-tab skip had, on the other card",
     [('        skip = (_cmd_spec({"action": "skip_init_verify"}, "skip the sign-in check")\n'
       '                if ph == 0 else drop)',
       '        skip = drop')]),

    ("H3", BRIDGE, "under",
     "⛔ /research/{id}/resume LOSES ITS NO-CHECKPOINT GUARD while /resolve keeps "
     "its identical one, so the route a chat model reaches by saying “resume” "
     "enqueues a request the backend deletes with a local WARN and no write-back "
     "— a resume reported as asked for and silently dropped",
     [('                    if not brid:\n'
       '                        self._json(409, {\n'
       '                            "error": "this run has no checkpoint to resume from — "\n'
       '                                     "start a new research instead",\n'
       '                            "reason": "no_checkpoint"})\n'
       '                        return\n', '')]),

    # ══ F — type safety at the seam ═════════════════════════════════════════
    ("F1", BRIDGE, "over",
     "⛔ A CARD FIELD OF THE WRONG TYPE TAKES DOWN THE WHOLE ROUTE. `True` where "
     "a string was expected raises out of the row loop, so ONE malformed document "
     "hides every other run on the account",
     [('    return v.strip().lower() if isinstance(v, str) else ""',
       '    return (v or "").strip().lower()')]),

    ("F2", BRIDGE, "over",
     "the planner stops being total: a non-dict pendingDecision is classified "
     "rather than refused, and the route raises on a document shape a later "
     "backend can write",
     [('    if not isinstance(pd, dict) or not pd:\n        return None\n    card = _card_id(pd)',
       '    if pd is None:\n        return None\n    card = _card_id(pd)')]),

    # ══ G — the card's own latched verdict (the one research.py edit) ═══════
    ("G1", RESEARCH, "under",
     "⛔ THE HV CARD STOPS CARRYING ITS OWN VERDICT, so a reader must re-derive "
     "it from `reason` — a NON-LATCHING value later probes overwrite. A Cloudflare "
     "wall whose last probe landed in the Turnstile gap is then offered a Resume "
     "the gate will refuse",
     [('        "hvIntent": _hv_intent,\n', '')]),

    ("G2", RESEARCH, "over",
     "the card claims every human-verification challenge is a hard wall, so a "
     "solvable check loses its Resume and the person is told to drop the platform "
     "they could have unblocked in ten seconds",
     [('        "hvIntent": _hv_intent,', '        "hvIntent": "hv_wall",')]),

    ("G3", BRIDGE, "over",
     "the bridge ignores the card's own verdict and keeps guessing from the word "
     "in `reason` — the field was added and nothing reads it",
     [('        hv_intent = pd.get("hvIntent")\n'
       '        if isinstance(hv_intent, str) and hv_intent:',
       '        hv_intent = None\n'
       '        if isinstance(hv_intent, str) and hv_intent:')]),
]


def sh(cmd: list[str], *, cwd=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                          env=env or ENV)


def purge_pycache() -> None:
    """⛔ STALE BYTECODE ONCE FAKED THREE ROUNDS OF MEASUREMENT on this project.
    A mutant written and reverted inside one second can leave a .pyc whose mtime
    granularity hides the change."""
    for d in (ROOT / "agent" / "facade", ROOT / "agent" / "tests", ROOT):
        for p in d.rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES,
              "agent/tests", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) error")
_SKIPPED = re.compile(r"(\d+) skipped")


def _verdict(proc, floor: int, label: str):
    """(green, refusal). ⛔ A SKIP IS THE ABSENCE OF A MEASUREMENT, and pytest
    exits 0 for a run that collected almost nothing. Refuse rather than guess."""
    tail = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-1500:]
    passed, failed = _PASSED.search(tail), _FAILED.search(tail)
    errors, skipped = _ERRORS.search(tail), _SKIPPED.search(tail)
    if not passed and not failed:
        return None, f"{label}: pytest printed no counts — the run did not happen: {tail[-300:]!r}"
    if skipped:
        return None, f"{label}: {skipped.group(1)} test(s) SKIPPED — a skip is not a pass"
    n = int(passed.group(1) if passed else 0) + int(failed.group(1) if failed else 0)
    if n < floor:
        return None, (f"{label}: only {n} tests collected, expected at least {floor}"
                      " — the run measured something other than this suite")
    return proc.returncode == 0 and not failed and not errors, None


def run_tests(files_touched):
    """Both legs, but only the ones a mutant can reach — the root suite is slow
    and no bridge/script edit can change it."""
    purge_pycache()
    if any(f != RESEARCH for f in files_touched):
        agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
        proc = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
                   "-q", "-p", "no:cacheprovider"],
                  cwd=ROOT / "agent", env=agent_env)
        green, refuse = _verdict(proc, AGENT_FLOOR, "agent")
        if refuse:
            return None, refuse
        if not green:
            return False, None
    if RESEARCH in files_touched:
        proc = sh([sys.executable, "-B", "-m", "pytest", *ROOT_SUITES.split(),
                   "-q", "-p", "no:cacheprovider"])
        green, refuse = _verdict(proc, ROOT_FLOOR, "root")
        if refuse:
            return None, refuse
        if not green:
            return False, None
    return True, None


ALL_FILES = tuple(MUTATED_FILES)


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    only = {a for a in sys.argv[1:] if not a.startswith("-")}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only and len(selected) != len(only):
        print(f"unknown mutant id(s): {only - {m[0] for m in selected}}")
        return 2

    print("baseline… ", end="", flush=True)
    green, refuse = run_tests(ALL_FILES)
    if refuse:
        print(f"REFUSED: {refuse}")
        return 2
    if not green:
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in selected:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                # ⛔ EXACTLY ONE. A stale anchor measured nothing and would still
                # report a kill; a duplicated one mutates a place nobody meant.
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            # ⛔⛔ A MUTANT THAT DOES NOT PARSE MEASURES NOTHING and still reports
            # a kill — the suite goes red on an import error rather than on the
            # behaviour the mutant was about. Mis-indented anchors are how this
            # happens: a replacement whose leading whitespace differs still
            # substring-matches and produces an unparseable file.
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            green, refuse = run_tests((fname,))
            if refuse:
                raise AssertionError(f"verdict refused — {refuse}")
            killed = not green
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                green, refuse = run_tests((fname,))
                if refuse:
                    raise AssertionError(f"verdict refused — {refuse}")
                killed = not green
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            survivors.append((mid, direction, f"STALE ANCHOR — measured nothing ({exc})"))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed "
          f"({over} over-corrections)")
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
