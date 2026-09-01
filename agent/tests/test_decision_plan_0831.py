"""The blocked-run planner: which card a run is on, and what chat can DO about it.

⛔⛔ THE DEFECT THIS FILE EXISTS FOR: chat used to decide what to tell a person,
and which command to write, by pattern-matching `pendingDecision.kind`. THREE
DIFFERENT SITUATIONS SHARE THE `login_required` LITERAL — a missing Anthropic API
key, the phase-0 sign-in walk, and a mid-run sign-in wall — so a run that needed
an API key was told to "sign in on the device". And when nothing matched, the old
code MINTED A PLAUSIBLE COMMAND rather than admitting the card had no such
button. Two of those invented commands were actively harmful:

  * on the browser-launch failure card, chat's "skip" reached the phase-0
    decision gate's `else` branch, which TERMINATES THE PIPELINE — a hidden Stop
    reported to the person as "Skipping the current blocker";
  * on a Pro-tier card, chat's "retry" returned `continue_anyway` (first in that
    card's ordered action list) — DOWNGRADING THE PERSON TO THE FREE TIER while
    printing "↻ Retrying — resuming the run".

Every test below names the specific lie it prevents. These are pure-function
tests over the planner; the routes that consume it are pinned in
test_bridge_resolve_0831.py and the chat copy in test_sr_attention_copy_0831.py —
⛔ a helper that is pinned only by its own unit tests is not covered, because the
consumer can stop calling it and nothing goes red.
"""

import itertools

import pytest

from facade import bridge


# ── the six shapes research.py actually writes ───────────────────────────────
# Each mirrors a real `_persist_pending_decision` payload, field for field. A
# fixture that invents a shape production never emits proves nothing — the old
# suite's login fixture carried a `title`, which no login writer sets.

def env_card():
    """research.py phase-0 env check. The ONLY payload carrying `envErrors`."""
    return {
        "kind": "login_required", "phase": 0,
        "platforms": [], "platformLabels": [],
        "machineName": "Mac-mini",
        "envErrors": ["The run needs an Anthropic API key to start. "
                      "Add it in Account → API Config, then Retry."],
        "attempt": 1,
        "message": ("The run needs an Anthropic API key to start. "
                    "Add it in Account → API Config, then Retry."),
        "alert_id": "phase0_env_check",
    }


def p0_login_card():
    """research.py phase-0 sign-in walk. Agent-less, non-empty platforms."""
    return {
        "kind": "login_required", "phase": 0,
        "platforms": ["chatgpt"], "platformLabels": ["ChatGPT"],
        "machineName": "Mac-mini", "attempt": 1,
        "message": "ChatGPT needs a login. Sign in using the open browser, then Retry.",
        "alert_id": "phase0_login_required_chatgpt",
    }


def worktab_login_card(phase=2):
    """research.py mid-run work-tab wall. The only login mirror with `agent`."""
    return {
        "kind": "login_required", "phase": phase, "agent": "claude",
        "platforms": ["claude"], "platformLabels": ["Claude"],
        "machineName": "Mac-mini", "attempt": 1,
        "message": "Claude is signed out. Sign in using the open browser window — "
                   "the run resumes automatically once you're back in — or Skip Claude.",
        "alert_id": f"phase{phase}_login_required_claude",
    }


def hv_card(reason="Human verification challenge", hv_intent=None):
    pd = {
        "kind": "human_verification_required", "phase": 2, "agent": "gemini",
        "platformLabel": "Gemini", "reason": reason,
        "message": "Solve the check in the open browser, then Resume — or Skip Gemini.",
        "alert_id": "phase2_hv_gemini",
    }
    if hv_intent is not None:
        pd["hvIntent"] = hv_intent
    return pd


def pro_card(phase=1, agent="chatgpt"):
    """research.py pro_required. ⛔ `continue_free` is FIRST in the ordered list."""
    if phase == 2:
        # research.py suppresses the retry token entirely at phase 2.
        actions = [
            {"id": "continue_with_free", "label": "Continue with Free",
             "command": {"action": "continue_free", "agent": agent}},
            {"id": "skip", "label": "Skip",
             "command": {"action": "skip_agent", "agent": agent}},
        ]
    else:
        actions = [
            {"id": "continue_with_free", "label": "Continue with Free",
             "command": {"action": "continue_anyway"}},
            {"id": "retry", "label": "Retry",
             "command": {"action": "retry_phase", "phase": phase}},
            {"id": "skip", "label": "Skip",
             "command": ({"action": "skip_init_verify"} if phase == 0
                         else {"action": "skip_agent", "agent": agent})},
        ]
    return {"kind": "pro_required", "phase": phase, "agent": agent,
            "title": "ChatGPT needs a paid plan", "details": "…",
            "actions": actions, "alert_id": f"phase{phase}_pro_required_{agent}"}


def crash_login_interrupt_card(phase=2):
    """research.py's login-interrupt escalation. ONE action token: retry_resume."""
    return {"kind": "pipeline_error", "phase": phase, "agent": None,
            "title": "Paused by the login command",
            "details": "Login closed the research browser. Tap Retry after login — "
                       "the run resumes from its checkpoint.\n"
                       "Note: the Stop button ends the run instead.",
            "actions": [{"id": "retry", "label": "Retry",
                         "command": {"action": "resume_from_checkpoint"}}],
            "dismissible": True, "alert_id": f"phase{phase}_login_interrupt"}


def crash_loop_card(phase=3):
    return {"kind": "pipeline_error", "phase": phase, "agent": None,
            "title": "The run kept hitting errors",
            "details": "We tried to recover a couple of times and it didn't take. "
                       "Retry to start again from the last checkpoint, or Skip to stop here.",
            "actions": [{"id": "retry", "label": "Retry",
                         "command": {"action": "resume_from_checkpoint"}},
                        {"id": "skip", "label": "Skip",
                         "command": {"action": "discard_restart_prompt"}}],
            "dismissible": True, "alert_id": f"phase{phase}_crash_loop"}


def browser_launch_card():
    """research.py phase-0 browser launch failure. Retry ONLY — and its decision
    gate TERMINATES the run for any other answer."""
    return {"kind": "pipeline_error", "phase": 0, "agent": "system",
            "title": "Couldn't start the browser",
            "details": "The automation browser couldn't start. Retry — if it keeps "
                       "failing, check the setup on this machine.",
            "actions": [{"id": "retry", "label": "Retry",
                         "command": {"action": "retry_phase", "phase": 0}}],
            "alert_id": "phase0_error"}


def noretry_card(phase=4):
    """A `phase_error_noretry` mirror: skip is the only offer."""
    return {"kind": "pipeline_error", "phase": phase, "agent": None,
            "title": "That step can't be retried", "details": "",
            "actions": [{"id": "skip", "label": "Skip",
                         "command": {"action": "skip_phase", "phase": phase}}],
            "alert_id": f"phase{phase}_error"}


# ── (a) the shared kind literal ──────────────────────────────────────────────

def test_env_missing_key_is_not_a_sign_in_wall():
    """⛔ THE OWNER'S FIRST ASK. A run that needs an API key must ask for an API
    key. Both cards write kind="login_required"; only the env one writes
    envErrors, which is the discriminator the web app itself uses."""
    plan = bridge._decision_plan(env_card())
    assert plan["card"] == "env_missing_key"
    action = bridge._attention_action(plan)
    assert "API key" in action
    assert "sign in" not in action.lower(), action


def test_p0_sign_in_wall_still_says_sign_in():
    """The over-correction guard: fixing the env card must not silence the real
    sign-in wall, which is the OTHER half of the owner's ask."""
    plan = bridge._decision_plan(p0_login_card())
    assert plan["card"] == "login_walk"
    action = bridge._attention_action(plan)
    assert "Sign in" in action
    assert "API key" not in action


def test_the_three_login_cards_are_three_distinct_cards():
    """One kind literal, three situations. If any two collapse, the person is
    told to do something that will not unblock their run."""
    cards = {bridge._card_id(env_card()),
             bridge._card_id(p0_login_card()),
             bridge._card_id(worktab_login_card())}
    assert cards == {"env_missing_key", "login_walk", "login_worktab"}


def test_worktab_wall_names_the_platform_and_says_it_self_resumes():
    plan = bridge._decision_plan(worktab_login_card())
    action = bridge._attention_action(plan)
    assert "Claude" in action and "picks up on its own" in action


def test_phase_zero_with_an_agent_is_still_the_walk_not_the_worktab():
    """The work-tab discriminator is agent AND phase>=1. A phase-0 card must not
    take the work-tab branch, whose skip drops a platform rather than the check."""
    pd = p0_login_card()
    pd["agent"] = "chatgpt"
    assert bridge._card_id(pd) == "login_walk"


def test_a_json_true_phase_is_not_phase_one():
    """bool is an int subclass. `phase: true` must not satisfy `phase >= 1`."""
    pd = worktab_login_card()
    pd["phase"] = True
    assert bridge._card_id(pd) == "login_walk"


# ── (b) retry must actually resume ───────────────────────────────────────────

@pytest.mark.parametrize("card", [crash_login_interrupt_card(), crash_loop_card()])
def test_crash_cards_resume_by_queue_not_by_per_run_command(card):
    """⛔⛔ THE OWNER'S SECOND ASK. By the time either crash card is on screen,
    run_pipeline has returned and the per-run command listener is torn down — so
    the `retry_phase` the old code wrote was consumed by nobody while chat said
    the run was resuming. The device queue is served by the always-alive start
    listener, and is the only transport that can restart a crashed run."""
    plan = bridge._decision_plan(card)
    assert plan["resume"]["transport"] == "queue_resume"
    assert plan["resume"]["command"] is None


def test_crash_cards_are_told_apart_by_their_own_tokens():
    assert bridge._card_id(crash_login_interrupt_card()) == "crash_login_interrupt"
    assert bridge._card_id(crash_loop_card()) == "crash_loop"


def test_status_only_blockers_resume_by_queue_too():
    """A run paused by a backend restart has NO card at all — the app draws its
    own banner. Chat used to answer "this run isn't waiting on a decision" for a
    run the app offers a working Resume on, and `sr resume` returned a cheerful
    200 for a command whose listener died with the old daemon."""
    for status in ("paused_backend_restart", "paused_backend_restart_failed",
                   "stopped_by_watchdog"):
        plan = bridge._run_plan({"status": status})
        assert plan is not None, status
        assert plan["resume"]["transport"] == "queue_resume", status
        assert plan["skip"] is None, status


def test_a_card_wins_over_the_status_arm():
    """A doc with BOTH a card and a blocked status is resolved by the card — the
    card is the specific thing the person was asked about."""
    plan = bridge._run_plan({"status": "paused_backend_restart",
                             "pendingDecision": worktab_login_card()})
    assert plan["card"] == "login_worktab"


def test_a_healthy_run_has_no_plan():
    assert bridge._run_plan({"status": "ongoing"}) is None
    assert bridge._run_plan({"status": "completed", "pendingDecision": {}}) is None


# ── (c) the skips that do not exist ──────────────────────────────────────────

def test_crash_login_interrupt_offers_no_skip():
    """Its catalog entry has ONE token. Chat offered a Skip anyway."""
    plan = bridge._decision_plan(crash_login_interrupt_card())
    assert plan["skip"] is None
    assert bridge._plan_offers(plan) == ["retry"]
    assert "no skip on this one" in bridge._attention_action(plan)


def test_browser_launch_card_offers_no_skip():
    """⛔⛔ THE DESTRUCTIVE ONE. research.py's phase-0 browser-launch gate treats
    anything that is not "retry" as a reason to TERMINATE THE PIPELINE ("skip
    (not offered but handled defensively) / stop / timeout → terminating"). Chat
    minted `skip_phase(0)` for it and reported "Skipping the current blocker".
    That was a hidden Stop."""
    plan = bridge._decision_plan(browser_launch_card())
    assert plan["skip"] is None
    assert bridge._plan_offers(plan) == ["retry"]


def test_a_card_with_actions_that_match_nothing_offers_nothing():
    """The general rule the two cases above are instances of: a card that HAS an
    actions array and matches no known verb genuinely offers none. Minting one
    anyway is how an invented command reaches a live pipeline."""
    pd = {"kind": "pipeline_error", "phase": 1,
          "actions": [{"id": "x", "command": {"action": "continue_chat"}},
                      {"id": "y", "command": {"action": "stop"}}]}
    plan = bridge._decision_plan(pd)
    assert plan["resume"] is None and plan["skip"] is None
    assert bridge._plan_offers(plan) == []


def test_noretry_card_offers_no_retry():
    plan = bridge._decision_plan(noretry_card())
    assert plan["resume"] is None and plan["skip"] is not None
    assert bridge._plan_offers(plan) == ["skip"]
    assert "Retry isn’t available" in bridge._attention_action(plan)


def test_worktab_login_skip_drops_the_platform_not_the_check():
    """⛔⛔ A SKIP THAT WAS READ AS A RETRY. The old code sent `skip_init_verify`
    for every login card. The work-tab loop watches `skipped_agents`;
    skip_init_verify only calls request_resume, which that loop reads as the user
    tapping RETRY — so it re-probed the still-signed-out page and re-carded the
    same wall. Forever. The real skip is skip_agent."""
    plan = bridge._decision_plan(worktab_login_card())
    assert plan["skip"]["command"] == {"action": "skip_agent", "agent": "claude"}


def test_the_generic_sentence_names_the_agent_and_both_verbs():
    """⛔ THE MOST COMMON BLOCKER HAD NO ASSERTION ON ITS COPY. An agent that
    failed or stalled reaches chat through the generic pipeline_error mirror with
    [retry_agent, skip_agent], and nothing pinned the sentence a person reads —
    so the {Ag} substitution and the whole phrase table could break silently.
    Cross-verify found this by measuring which lines the suite executes."""
    pd = {"kind": "pipeline_error", "phase": 2, "agent": "chatgpt",
          "title": "ChatGPT stopped responding", "details": "",
          "actions": [{"id": "retry", "label": "Retry",
                       "command": {"action": "retry_agent", "agent": "chatgpt"}},
                      {"id": "skip", "label": "Skip ChatGPT",
                       "command": {"action": "skip_agent", "agent": "chatgpt"}}],
          "alert_id": "phase2_error_chatgpt"}
    plan = bridge._decision_plan(pd)
    assert plan["card"] == "pipeline_error"
    assert bridge._attention_action(plan) == (
        "Reply “retry” to restart ChatGPT, or “skip” to drop ChatGPT from this run.")


def test_the_generic_sentence_falls_back_when_no_agent_is_named():
    """The same phrases with no agent on the card — the {Ag} placeholder must not
    survive into a sentence a person reads."""
    pd = {"kind": "pipeline_error", "phase": 1, "title": "No brief",
          "actions": [{"id": "retry", "command": {"action": "retry_phase", "phase": 1}},
                      {"id": "skip", "command": {"action": "skip_phase", "phase": 1}}]}
    action = bridge._attention_action(bridge._decision_plan(pd))
    assert "{Ag}" not in action
    assert action == "Reply “retry” to resume, or “skip” to move past this step."


def test_pro_required_at_phase_zero_skips_the_sign_in_check():
    """⛔ research.py's pro card at phase 0 bypasses the INIT verification walk
    (skip_init_verify); at phase >= 1 it drops that one platform. Flipping this to
    skip_agent stayed green while the sentence still said "skip the sign-in
    check" — the same class of mismatch as the work-tab skip, unpinned."""
    plan = bridge._decision_plan(pro_card(phase=0))
    assert plan["skip"]["command"] == {"action": "skip_init_verify"}
    assert "skip the sign-in check" in bridge._attention_action(plan)


def test_pro_required_above_phase_zero_drops_the_platform():
    plan = bridge._decision_plan(pro_card(phase=1, agent="gemini"))
    assert plan["skip"]["command"] == {"action": "skip_agent", "agent": "gemini"}
    assert "drop Gemini from this run" in bridge._attention_action(plan)


def test_p0_login_skip_is_still_the_sign_in_check():
    """The phase-0 card genuinely gates the verification walk — its Skip must
    stay skip_init_verify, matching the app's own phase-aware Skip."""
    plan = bridge._decision_plan(p0_login_card())
    assert plan["skip"]["command"] == {"action": "skip_init_verify"}


def test_unknown_kind_mints_nothing():
    """The root of every phantom command: falling through to a plausible guess.
    An honest "open the app" beats a command the backend may act on."""
    plan = bridge._decision_plan({"kind": "something_new_from_a_later_backend",
                                  "phase": 1})
    assert plan["card"] == "unknown"
    assert plan["resume"] is None and plan["skip"] is None
    assert "Open the app" in bridge._attention_action(plan)


# ── the Pro-tier inversion ───────────────────────────────────────────────────

def test_pro_required_retry_is_not_continue_with_free():
    """⛔⛔ CHAT PRESSED THE WRONG BUTTON. `continue_free` is FIRST in
    pro_required's ordered action list and mints `continue_anyway`, which used to
    be a member of _RESUME_ACTIONS — so the first-match scan returned it and the
    person was moved to the free tier while chat said "Retrying"."""
    plan = bridge._decision_plan(pro_card(phase=1))
    assert plan["resume"]["command"]["action"] == "retry_phase"
    assert plan["resume"]["command"] != {"action": "continue_anyway"}


def test_continue_anyway_is_not_a_resume_anywhere():
    """Belt-and-braces: even reached through the generic scan it must not count."""
    assert "continue_anyway" not in bridge._RESUME_ACTIONS
    pd = {"kind": "pipeline_error", "phase": 1,
          "actions": [{"id": "c", "command": {"action": "continue_anyway"}}]}
    assert bridge._decision_plan(pd)["resume"] is None


def test_pro_required_at_phase_two_offers_no_retry():
    """research.py deliberately withholds the Retry token at phase 2: a restart
    there cancels run_phase2 and nukes every in-flight deep research. Chat minted
    retry_phase(2) anyway — the one command the backend refuses to offer."""
    plan = bridge._decision_plan(pro_card(phase=2))
    assert plan["resume"] is None
    assert "restart the whole research step" in bridge._attention_action(plan)


def test_pro_required_copy_never_promises_the_free_tier_from_chat():
    for phase in (0, 1, 2):
        action = bridge._attention_action(bridge._decision_plan(pro_card(phase=phase)))
        assert "only the app offers" in action, phase


# ── the human-verification split ─────────────────────────────────────────────

def test_cloudflare_wall_offers_no_retry():
    """A Cloudflare wall cannot be cleared by resuming — trying makes it ask
    harder. The card's own copy says so; chat offered Retry anyway."""
    plan = bridge._decision_plan(hv_card(reason="Cloudflare Turnstile"))
    assert plan["card"] == "hv_wall"
    assert plan["resume"] is None and plan["skip"] is not None


def test_solvable_check_offers_resume():
    plan = bridge._decision_plan(hv_card())
    assert plan["card"] == "hv_solvable"
    assert plan["resume"]["command"] == {"action": "resume"}


def test_hv_intent_beats_the_word_test():
    """⛔ `reason` is a NON-LATCHING nonlocal that later probes overwrite, so a
    Cloudflare wall can persist with a reason that never says "cloudflare". The
    card now carries the gate's own latched verdict; the word test is only the
    fallback for a card written before that field existed."""
    pd = hv_card(reason="Claude human verification", hv_intent="hv_wall")
    assert bridge._card_id(pd) == "hv_wall"
    pd2 = hv_card(reason="Cloudflare check seen earlier", hv_intent="hv_solvable")
    assert bridge._card_id(pd2) == "hv_solvable"


# ── (d) the discarded detail ─────────────────────────────────────────────────

def test_details_reaches_the_plan():
    """⛔ THE OWNER'S FOURTH ASK. The crash card's headline is three words; the
    sentence that tells you to sign back in FIRST lives in `details`, and chat
    threw it away."""
    plan = bridge._decision_plan(crash_login_interrupt_card())
    assert "resumes from its checkpoint" in plan["details"]


def test_details_is_capped():
    """The row has no byte cap and `details` is caller-authored."""
    pd = crash_loop_card()
    pd["details"] = "x" * 5000
    det = bridge._decision_plan(pd)["details"]
    assert len(det) == bridge._DETAILS_MAX + 1 and det.endswith("…")


def test_a_card_with_no_details_ships_none_not_empty_string():
    """Three of the six live shapes never write `details`. Shipping "" would put
    an empty second line under every sign-in card."""
    for pd in (env_card(), p0_login_card(), hv_card()):
        assert bridge._decision_plan(pd)["details"] is None
    pd = crash_loop_card()
    pd["details"] = "   "
    assert bridge._decision_plan(pd)["details"] is None


# ── totality and sink safety ─────────────────────────────────────────────────

def test_plan_is_total_over_fuzzed_cards():
    """Every mutation of every production shape returns None or a well-formed
    plan, and never raises. A planner that throws on a shape a later backend
    writes takes the whole /updates route down with it."""
    shapes = [env_card(), p0_login_card(), worktab_login_card(), hv_card(),
              pro_card(0), pro_card(1), pro_card(2), crash_loop_card(),
              crash_login_interrupt_card(), browser_launch_card(), noretry_card()]
    junk = [None, "", 0, [], {}, True, {"kind": None}, {"kind": 7},
            {"kind": "login_required", "phase": "two", "agent": 5},
            {"kind": "pipeline_error", "actions": "not-a-list"},
            {"kind": "pipeline_error", "actions": [None, 3, {"command": "x"},
                                                   {"command": {"action": None}}]},
            {"kind": "human_verification_required", "reason": None},
            {"kind": "human_verification_required", "hvIntent": 5},
            {"kind": "pro_required", "phase": [2]},
            {"pendingDecision": {"kind": "login_required"}}]
    keys = {"card", "phase", "agent", "machine", "platform",
            "reason", "details", "resume", "skip"}
    checked = 0
    for base in shapes:
        for field, value in itertools.product(
                list(base) + ["envErrors", "hvIntent"],
                [None, "", 0, [], {}, True, "zzz", -1, ["x"], {"a": 1}]):
            pd = dict(base)
            pd[field] = value
            plan = bridge._decision_plan(pd)
            assert plan is not None and set(plan) == keys
            assert plan["card"] in bridge._CARD_IDS
            assert isinstance(bridge._attention_action(plan), str)
            assert bridge._plan_offers(plan) in ([], ["retry"], ["skip"], ["retry", "skip"])
            checked += 1
    for pd in junk:
        plan = bridge._decision_plan(pd)
        assert plan is None or set(plan) == keys
        checked += 1
    assert checked > 800, checked


def test_every_command_the_planner_emits_is_one_the_backend_dispatches():
    """⛔ THE FAILURE MODE THAT STARTED ALL THIS: a command written to Firestore,
    marked processed, and executed by nobody — while chat reports success. Every
    command this planner can mint must be an action research.py's per-run
    listener actually dispatches on."""
    shapes = [env_card(), p0_login_card(), worktab_login_card(),
              hv_card(), hv_card(reason="cloudflare"),
              pro_card(0), pro_card(1), pro_card(2), crash_loop_card(),
              crash_login_interrupt_card(), browser_launch_card(), noretry_card(),
              {"kind": "agent_link_failed", "agent": "gemini", "phase": 2},
              {"kind": "pipeline_error", "phase": 3}]
    seen = set()
    for pd in shapes:
        plan = bridge._decision_plan(pd)
        for spec in (plan["resume"], plan["skip"]):
            if spec is None or spec["transport"] != "command":
                continue
            action = spec["command"]["action"]
            assert action in bridge._DISPATCHER_ACTIONS, (pd.get("kind"), action)
            seen.add(action)
    # A guard that never saw a command would pass vacuously.
    assert len(seen) >= 5, seen


def test_the_dispatcher_list_matches_research_py():
    """The bridge ships separately from the backend, so its idea of what the
    per-run listener handles can drift. Read the real elif chain and compare."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "research.py").read_text(encoding="utf-8")
    listener = src[src.index("def _start_command_listener"):]
    listener = listener[:listener.index("\ndef ", 100)]
    found = set(re.findall(r'action == "([a-z_]+)"', listener))
    assert found, "the listener's dispatch chain was not found — this guard is blind"
    missing = found - bridge._DISPATCHER_ACTIONS
    assert not missing, f"research.py dispatches actions the bridge doesn't know: {missing}"


def test_offers_names_exactly_the_non_none_specs():
    plan = bridge._decision_plan(crash_loop_card())
    assert bridge._plan_offers(plan) == ["retry", "skip"]
    assert bridge._plan_offers(None) == []


def test_attention_extras_is_empty_for_a_healthy_run():
    """`attentionOffers` must be [] — never None — when there is nothing to do,
    because a client reads ABSENT as "older bridge, assume both"."""
    act, det, offers = bridge._attention_extras(None)
    assert act is None and det is None and offers == []
