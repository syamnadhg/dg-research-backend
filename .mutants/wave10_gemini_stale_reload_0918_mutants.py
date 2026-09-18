"""Wave 10 — the bounded stale-research reload cadence, and its wiring.

⛔⛔ WHY THIS HARNESS EXISTS. The owner's report was "after Start Research we
should be able to refresh if the research is stale … it's getting stuck in
working phase, sometimes or mostly", and this lane is the answer: a BOUND on how
often a post-Start Gemini tab may be reloaded, an IDENTITY proof after every
reload, and adoption when the conversation did not come back. It drives a LIVE
page in a running phase — and it shipped with no mutation coverage at all
(`.mutants/` held nothing for `_gemini_stale_reload*`), measured only by tests
nothing had tried to defeat.

⛔⛔ AND THE TWO MUTANTS THAT MATTER MOST ARE THE WIRING ONES. On 2026-09-18 the
cross-verify UNWIRED this entire lane in a sandbox clone — `pass  # await
_gemini_stale_reload_tick(p, name)` — and 829 tests stayed green, because the
wiring pins read raw `inspect.getsource` and a comment naming a call satisfies a
substring count. Commenting out run_phase2's `"brief": brief_text,` seed did the
same: the cadence then refuses SILENTLY for the whole run, because without the
brief the identity prover cannot return True. The lane the owner asked for could
have shipped completely dead behind a green gate. Both pins are parsed now, and
R17/R18 are what say so.

⭐ THE OTHERS WORTH READING:
  R10 — the tick rewinds `last_growth_time` on a proven identity. This is the
        first cut of the lane and it is FATAL ARITHMETIC: C is 12 minutes,
        STUCK_NO_GROWTH_SEC is 15, so a rewind every 12 minutes puts the growth
        clock permanently out of the L1 arbiter's reach — no [Retry][Skip] card,
        no owner ping, no 30-minute unacted auto-skip, straight to the 90-minute
        hard cap. The lane built for "it's getting stuck" would have disabled the
        only thing that says so. A SURVIVING URL IS NOT GROWTH.
  R9  — the reload window is stamped AFTER the navigation instead of before it,
        so a tab whose reload times out is hammered on every 30-second tick.
  R11/R12 — the identity prover becomes a liveness prover by halves: either the
        URL id compare goes (any conversation is ours) or the brief compare goes
        (the right URL with somebody else's content). Identity is the whole
        reason this exists rather than `verify_gemini_generating`, which returns
        True on Gemini's blank home while the SPA hydrates.
  R15 — the post-Start adoption stops being told WHICH conversation was lost, so
        the relaxed report verdict can adopt a PREVIOUS run of the same brief and
        deliver its report as this run's. Silent; it looks like a recovery.
  R6  — the ceiling goes. The recorded worst case paid EIGHT reloads on one
        healthy run, each ~35-40 s of the Gemini leg plus a page load on the one
        platform this module avoids them for. A tab three reloads did not cure
        belongs to the stuck arbiter, not to this cadence.
  R7  — a zero window stops turning the cadence OFF. The env var is the only
        switch a machine has; `DG_GEMINI_STALE_RELOAD_SEC=0` must mean off.

⛔ DELIBERATELY ABSENT — recorded so the next reader does not re-add them:
  * "`last_reload_at or research_started_at` → `last_reload_at`". EQUIVALENT: the
    past-Start clause above it already refuses everything the zero case could
    reach, so the mutant cannot change an answer. An equivalent mutant is a
    harness bug, not a survivor.
  * "`_GEMINI_STALE_RELOAD_SEC` 12 min → 6 min". A bound is a JUDGEMENT measured
    against `run_analytics.json`, and the tests that would fail are the recorded
    forty-run simulations — i.e. it would measure the instrument, not the code.
    R6 and R7 mutate the SHAPE of the bound, which is what this lane decides.
  * "the reload's `wait_until`/`timeout` arguments change". No guard drives a
    real navigation, so it could only ever be a survivor; the failure PATH is
    measured instead, by R14.
  * "the cadence reloads Gemini by `page.goto` instead of `reload`". That is the
    2026-07 destruction this lane refuses, but `RELOAD_SAFE` and the five other
    refusal sites are pinned by their own AST/name tests in the same file, and a
    goto mutant would fail on the fake tab's `gotos` list rather than on the
    rule. Filed, not built.

⭐ OWN PINS ADDED WITH THIS HARNESS (tests/test_gemini_stale_reload_0918.py):
  test_a_body_that_read_back_empty_is_no_card_either                → kills R20
  test_identity_refuses_when_there_is_no_brief_to_prove_it_with
      (its third case: the BARE HOME with an unknown convo id)      → kills R19
Nothing already in the suite could fail on those two: the fail-closed test drives
a RAISING evaluate (never an empty body), and the identity refusals it named were
inherited from the URL compare, which refuses them whatever the guard does.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/wave10_gemini_stale_reload_0918_mutants.py
  .venv/bin/python .mutants/wave10_gemini_stale_reload_0918_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = "tests/test_gemini_stale_reload_0918.py"

# Every test in the lane's own file, which is also the only file here — the
# filter exists so the harness's scope line means the same thing it does in the
# other harnesses, and `_filter_misses` proves it hides nothing.
MINE = (
    "flat_post_start_research_tab or bare_home_is_never_reloaded or "
    "cadence_refuses_to_fire_at_all or no_research_card_is_left_alone or "
    "finished_research_is_left_alone or plan_draft_window or "
    "second_reload_inside_the_window or growth_clock_that_moved_recently or "
    "zero_window_turns_the_cadence_off or fastest_healthy_research or "
    "what_the_cadence_really_costs or ceiling_stops_the_tail or "
    "spent_budget_refuses or measured_twelve_minutes or "
    "conversation_id_comes_from_the_url or deleted_897a_recovery or "
    "surface_read_tells_the_card or surface_read_is_fail_closed or "
    "body_that_read_back_empty or identity_needs_both or "
    "landed_on_the_empty_home or different_conversation_is_not_ours or "
    "right_url_with_somebody_elses_content or identity_waits_for_the_conversation or "
    "identity_refuses_when_there_is_no_brief or healthy_looking_but_flat_tab or "
    "nothing_happens_on_a_tick or reload_that_throws or "
    "falls_back_to_post_start_adoption or unrecoverable_reload or "
    "adoption_that_raises or at_most_once_per_window or "
    "still_reaches_the_stuck_card or growth_clock_is_never_rewound or "
    "pays_the_ceiling or send_path_still_refuses or "
    "post_start_caller_reads_a_present_report or pre_start_states_are_adopted or "
    "sidebar_probe_carries_the_same_two_verdicts or "
    "relaxed_report_verdict_is_scoped or unknown_lost_id or "
    "post_start_relaxes_the_report_verdict or cadence_is_wired_into_the_gemini_leg or "
    "leg_gates_the_cadence or still_not_reload_safe or "
    "pending_seed_carries_this_runs_brief or phase_two_hands_the_brief or "
    "contradicting_refusal_sentence or surviving_sentence_still_says or "
    "other_refusal_sites_were_not_widened or re_arms_the_late_start_watch"
)

OWNED_FILES = ("tests/test_gemini_stale_reload_0918.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: Each clause of the bound. They are all `if <clause>: return False`, so every
#: anchor carries its own `return` line to stay unique.
C_PAST_START = ('    if not research_started_at or (now - research_started_at) < w:\n'
                '        return False')
C_CARD = '    if not card_present:\n        return False'
C_DONE = '    if completion_seen:\n        return False'
C_BRIEF = '    if not have_identity_brief:\n        return False'
C_CONVO = '    if not in_conversation:\n        return False'
C_CAP = '    if int(reloads_so_far or 0) >= cap:\n        return False'
C_OFF = '    if w <= 0:\n        return False'
C_FLAT = '    if no_growth_secs < w:\n        return False'
#: The window stamp — taken BEFORE the page is touched, deliberately.
STAMP = ('    p["gemini_stale_reload_at"] = _now\n'
         '    p["gemini_stale_reloads"] = int(p.get("gemini_stale_reloads", 0) or 0) + 1')
#: The navigation itself, for the mutant that moves the stamp after it.
RELOAD = ('        await p["page"].reload(wait_until="domcontentloaded", timeout=30000)\n'
          '        await asyncio.sleep(settle_sec)')
#: The tick's last line — where a growth-clock rewind would go.
TICK_RETURN = '    return _verdict\n\n\n# Escalating nudge wording'
#: The identity prover's two halves, and its retry.
ID_URL = '        if _gemini_convo_url_id(_url) == convo_id:'
ID_BRIEF = ('            if _gemini_conversation_is_ours(_txt, pasted_text):\n'
            '                return True')
ID_ATTEMPTS = ('async def _gemini_reload_identity_ok(page, convo_id: str, pasted_text: str, *,\n'
               '                                     attempts: int = 3,')
#: The guard that stops "prove identity" succeeding with nothing to prove it with.
ID_GUARD = ('    if not convo_id or not (pasted_text or "").strip():\n'
            '        return False')
#: The observer re-attach on the reload-FAILED path.
OBSERVER_FAILED = ('        await _gemini_reattach_observer(p, name)\n'
                   '        return "reload_failed"')
#: The adoption call — the only post_start caller there is.
ADOPT_CALL = ('                p["page"], _brief, name, post_start=True,\n'
              '                lost_convo_id=_convo)')
#: The surface read's two fail-closed answers.
SURFACE_RAISE = ('        body = await page.evaluate("""() => (document.body.innerText || "").slice(0, 8000)""")\n'
                 '    except Exception:\n'
                 '        return False, False')
SURFACE_EMPTY = ('    if not body:\n        return False, False\n'
                 '    return (bool(_GEMINI_RESEARCH_CARD_RE.search(body)),')
#: THE WIRING: the leg's one call, and run_phase2's brief seed.
LEG_CALL = '                await _gemini_stale_reload_tick(p, name)'
BRIEF_SEED = '                                "brief": brief_text,'

MUTANTS = [
    # ═════════ the wiring — the two the cross-verify actually got away with ══
    ("R17", "under",
     "⛔⛔ THE WHOLE LANE IS UNWIRED, PAID FOR WITH A COMMENT NAMING THE CALL. "
     "This is the mutant the 09-18 cross-verify applied to a sandbox clone: 829 "
     "tests stayed green with no reload ever attempted, because the wiring pins "
     "counted substrings in raw source. The owner's reported symptom goes "
     "uncured and the gate says done. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_the_cadence_is_wired_into_the_gemini_leg_before_the_dom_scrape, "
     "which walks the round-robin's TREE for an `await` of the tick — a comment "
     "contributes no node",
     [(LEG_CALL, '                pass  # await _gemini_stale_reload_tick(p, name)')]),
    ("R18", "under",
     "⛔⛔ THE BRIEF NEVER REACHES THE ROUND-ROBIN, so `have_identity_brief` is "
     "False and the cadence REFUSES — silently, and for the rest of every run. "
     "The same comment trick paid for this one too (829 green). A lane that "
     "refuses for the whole run is indistinguishable from one that was never "
     "built. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_phase_two_hands_the_brief_to_the_round_robin, which parses "
     "run_phase2's `agents[\"Gemini\"]` seed and requires `brief` on it — so "
     "moving the key to another agent's seed does not pay for it either",
     [(BRIEF_SEED, '                                # "brief": brief_text,')]),

    # ═════════ the bound ════════════════════════════════════════════════════
    ("R1", "under",
     "⛔⛔ THE PLAN-DRAFT WINDOW MEETS A RELOAD. Before Start there is no "
     "research to preserve and the plan screen has its own machinery — the "
     "kickoff nudges and the late-Start watch — which a reload interrupts. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_the_plan_draft_window_never_meets_a_reload",
     [(C_PAST_START, '    if False:\n        return False')]),
    ("R2", "under",
     "⛔ A TAB WITH NO RESEARCH CARD IS RELOADED. The card is the only thing "
     "that says a research is mounted on this tab at all; without it the cadence "
     "is refreshing a page on a timer. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_tab_with_no_research_card_is_left_alone",
     [(C_CARD, '    if False:\n        return False')]),
    ("R3", "under",
     "⛔⛔ A FINISHED RESEARCH IS RELOADED. The completion line is the one "
     "signal that says the work is done and the report is on the page; reloading "
     "past it risks the extraction for nothing. A finished research is left "
     "alone, always. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_finished_research_is_left_alone",
     [(C_DONE, '    if False:\n        return False')]),
    ("R4", "under",
     "⛔⛔ THE CADENCE FIRES WITH NO BRIEF TO PROVE IDENTITY WITH. Then every "
     "reload falls through to adoption and out to the bare home — this is the "
     "one way this branch can DESTROY the run it exists to save. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_without_this_runs_brief_the_cadence_refuses_to_fire_at_all",
     [(C_BRIEF, '    if False:\n        return False')]),
    ("R5", "under",
     "⛔⛔ THE BARE HOME IS RELOADED. A reload of `/app` restores nothing and "
     "the 2026-07 finding still holds — this is the state the whole lane is "
     "afraid of, reached by the lane itself. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_the_bare_home_is_never_reloaded",
     [(C_CONVO, '    if False:\n        return False')]),
    ("R6", "under",
     "⛔⛔ THE CEILING GOES AND THE CADENCE IS UNBOUNDED AGAIN. The recorded "
     "worst case paid EIGHT reloads on one healthy 101-minute run, each ~35-40 s "
     "of the Gemini leg (30 s reload timeout + settle + identity retries) and a "
     "cold-ish page load on the one platform this module avoids them for. A tab "
     "three reloads did not cure belongs to the stuck arbiter. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_spent_budget_refuses_every_later_tick",
     [(C_CAP, '    if False:\n        return False')]),
    ("R7", "under",
     "⛔⛔ ZERO STOPS MEANING OFF. `DG_GEMINI_STALE_RELOAD_SEC=0` is the only "
     "switch a machine has, and a bound that cannot be turned off is an "
     "unbounded shape with a switch on it. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_zero_window_turns_the_cadence_off_completely",
     [(C_OFF, '    if w < 0:\n        return False')]),
    ("R8", "under",
     "⛔ THE GROWTH CLOCK STOPS SUPPRESSING. It is blind on this screen and it "
     "is deliberately a CHEAP EXTRA — it can only ever suppress a reload, never "
     "justify one — but dropping it means a tab that visibly moved 10 seconds "
     "ago is reloaded anyway. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_growth_clock_that_moved_recently_suppresses_the_reload",
     [(C_FLAT, '    if False:\n        return False')]),

    # ═════════ the tick ═════════════════════════════════════════════════════
    ("R9", "under",
     "⛔⛔ THE WINDOW IS STAMPED AFTER THE NAVIGATION, so a reload that THROWS "
     "consumes nothing and the same wedged tab is hammered on every 30-second "
     "tick — a page load every half minute for the rest of the phase. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_reload_that_throws_still_consumes_its_window",
     [(STAMP, '    pass'),
      (RELOAD, RELOAD + '\n'
       '        p["gemini_stale_reload_at"] = _now\n'
       '        p["gemini_stale_reloads"] = int(p.get("gemini_stale_reloads", 0) or 0) + 1')]),
    ("R10", "under",
     "⛔⛔ THE TICK REWINDS THE GROWTH CLOCK ON A PROVEN IDENTITY — the lane's "
     "first cut, and the worst thing in the wave. C is 12 min and "
     "STUCK_NO_GROWTH_SEC is 15, so a rewind every 12 minutes means "
     "`no_growth_secs` can NEVER reach 15 again: the L1 stuck arbiter, the "
     "[Retry][Skip] card, the owner's ping and the 30-minute unacted auto-skip "
     "all become unreachable for Gemini for the rest of the run, and a genuinely "
     "wedged research runs silently to the 90-minute hard cap. Identity is not "
     "liveness — a SURVIVING URL IS NOT GROWTH. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_wedged_gemini_still_reaches_the_stuck_card_with_the_cadence_running, "
     "which drives the real tick at the real 30 s poll interval over a 90-minute "
     "wedged tab and asserts the card still fires at ~15.5 min",
     [(TICK_RETURN,
       '    if _verdict in ("survived", "adopted"):\n'
       '        p["last_growth_time"] = time.time()\n' + TICK_RETURN)]),
    ("R14", "under",
     "⛔ THE OBSERVER IS NOT RE-ATTACHED WHEN THE RELOAD FAILED. A "
     "`domcontentloaded` timeout does NOT mean the page stayed put — a slow SPA "
     "can navigate and then miss the deadline, which tears the MutationObserver "
     "off exactly as a clean reload would, and the leg goes blind to streaming "
     "for the rest of the phase. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_reload_that_throws_still_consumes_its_window, whose last assertions "
     "are on the re-injection",
     [(OBSERVER_FAILED, '        return "reload_failed"')]),
    ("R15", "under",
     "⛔⛔ THE ADOPTION IS NOT TOLD WHICH CONVERSATION WAS LOST. `post_start` "
     "relaxes the refusal on a conversation that already holds a report — "
     "correctly, because from this side of Start a present report is the "
     "research having FINISHED while the tab was away. Unscoped, that relaxation "
     "lets the hunt take a PREVIOUS run of the same brief and deliver its report "
     "as this run's gemini.md. Silent: it looks like a successful recovery. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_reload_that_lands_on_the_home_falls_back_to_post_start_adoption, "
     "which captures the call and asserts the lost id was passed",
     [(ADOPT_CALL, '                p["page"], _brief, name, post_start=True)')]),

    # ═════════ the identity prover ══════════════════════════════════════════
    ("R11", "under",
     "⛔⛔ ANY CONVERSATION IS OURS. Without the URL id compare the prover "
     "returns True on a DIFFERENT conversation that happens to read like this "
     "run's brief — which is what the sidebar rail is full of on a machine that "
     "has run this topic before. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_different_conversation_is_not_ours_however_familiar_it_reads",
     [(ID_URL, '        if True:')]),
    ("R12", "under",
     "⛔⛔ THE RIGHT URL WITH SOMEBODY ELSE'S CONTENT IS ACCEPTED. The id half "
     "alone cannot tell a restored conversation from a re-used tab, which is the "
     "half `verify_gemini_generating` already got wrong. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_the_right_url_with_somebody_elses_content_is_not_ours",
     [(ID_BRIEF, '            if True:\n                return True')]),
    ("R13", "under",
     "⛔ THE PROVER BECOMES SINGLE-SHOT. Gemini's conversation content mounts "
     "LAZILY after the URL flips; a single check one render tick early already "
     "defeated the sidebar recovery once, and the same trap is here. A prover "
     "that misses sends a healthy conversation to adoption. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_identity_waits_for_the_conversation_to_mount",
     [(ID_ATTEMPTS, ID_ATTEMPTS.replace("attempts: int = 3,", "attempts: int = 1,"))]),
    ("R19", "under",
     "⛔⛔ \"PROVE IDENTITY\" SUCCEEDS ON THE EMPTY HOME. With the guard gone, an "
     "unknown conversation id (`\"\"`) EQUALS the id the bare home's URL yields "
     "(`\"\"`), so the compare cannot refuse anything and the home's own chrome — "
     "which carries this run's brief in the Recent rail — satisfies the "
     "ownership read. The prover then certifies the exact 2026-07 destruction it "
     "exists to catch. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_identity_refuses_when_there_is_no_brief_to_prove_it_with, whose third "
     "case was ADDED WITH THIS HARNESS — the two it already had are refused by "
     "the URL compare whatever this guard does",
     [(ID_GUARD, '    if False:\n        return False')]),

    # ═════════ the surface read ═════════════════════════════════════════════
    ("R16", "under",
     "⛔⛔ A PROBE THAT COULD NOT LOOK REPORTS A RESEARCH CARD. The read is "
     "fail-closed for one reason: `card_present` is what AUTHORISES a reload, so "
     "an error that reads as \"the card is up\" manufactures reloads out of "
     "target-closed exceptions on a tab that may hold a finished report. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_the_surface_read_is_fail_closed_so_a_probe_miss_cannot_cause_a_reload",
     [(SURFACE_RAISE, SURFACE_RAISE.replace("        return False, False",
                                            "        return True, False"))]),
    ("R20", "under",
     "⛔ THE OTHER HALF OF FAIL-CLOSED: an EMPTY body reads as a card. Gemini's "
     "SPA serves an empty `document.body.innerText` for a beat after a "
     "navigation — precisely when this cadence is looking — so this is the "
     "reading a just-reloaded tab gives, and it would authorise the next reload. "
     "KILLED BY tests/test_gemini_stale_reload_0918.py::"
     "test_a_body_that_read_back_empty_is_no_card_either, ADDED WITH THIS "
     "HARNESS because the fail-closed test drives a RAISING evaluate and never "
     "an empty one",
     [(SURFACE_EMPTY, SURFACE_EMPTY.replace("    if not body:\n        return False, False",
                                            "    if not body:\n        return True, False"))]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> "str | None":
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


def _pytest(kfilter: "str | None") -> str:
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


def run_tests(kfilter: "str | None") -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: "str | None") -> set:
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
          else "scope: THIS WAVE'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this wave's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS WAVE'S OWN GUARDS, so "
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
