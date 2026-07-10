"""#930 (2026-07-09): P2 stepper stuck-at-"Submitted" hardening + build log.

The user's repeat "stuck at Submitted" report turned out to be a STALE WORKER
(the process predated the #924 fix — no P1 code bug), but the P2 cross-check
found two real gaps with the same symptom:

1. The round-robin poller's agent_progress emit carried NO `stage` — the
   one-shot launch emits (stage="researching" seconds after each agent's
   send-verify) were the only thing moving the FE off "Submitted". Miss that
   one-shot (mid-run reload, hard retry, phase restart) and a scrape-blind
   agent (ChatGPT's cross-origin iframe: 0 sources/0 chars on a healthy run)
   parks on Submitted forever. The poller now re-affirms an honest stage on
   every emit: "planning" while the scraper reports a plan page (FE maps
   planning → Submitted by design), "researching" otherwise; empty stage is
   OMITTED so it never clobbers a previously-set value in the FE merge.

2. The hard-retry success emit was stage-less right after the FE reset the
   agent's tile — same parking, guaranteed. It now carries stage="researching"
   (honest: verified_h means generation was just re-verified).

Plus: server startup logs the loaded git build ("[build] <sha> <date> <subj>")
so a stale-code worker is a one-grep diagnosis from backend.log.
"""

import inspect

import research

_RR = inspect.getsource(research.poll_all_agents_round_robin)


def test_round_robin_emit_carries_stage():
    # Computed once per agent per tick, fed to the main emit via a splat that
    # OMITS empty stage (an emitted "" would overwrite the FE's merged value).
    assert '_p2_stage = ""' in _RR
    assert '**({"stage": _p2_stage} if _p2_stage else {})' in _RR


def test_stage_planning_gated_on_scrape_phase():
    # Gemini plan pages report status='generating' with planning only in the
    # scraper's separate `phase` field (#929) — stage must mirror that so the
    # FE keeps a planning Gemini on "Submitted" (by design) instead of
    # advancing it to Researching.
    assert 'if _scrape_phase == "planning":' in _RR
    assert '_p2_stage = "planning"' in _RR


def test_stage_researching_excludes_terminal_statuses():
    # done/complete/waiting/etc must not stamp "researching"; everything else
    # in the poll loop was verified generating at launch.
    assert '_p2_stage = "researching"' in _RR
    assert '"done", "complete", "completed", "waiting", "queued",' in _RR


def test_stage_participates_in_dedupe_key():
    # A planning→researching flip with no counter delta must not be suppressed
    # by the dedupe gate.
    assert '"stage": _p2_stage,' in _RR


def test_hard_retry_emit_carries_researching_stage():
    # The FE resets the agent tile on retry; the fresh DR shows 0 counters for
    # minutes — without stage the stepper re-parks on Submitted.
    _idx = _RR.index("Hard retry successful")
    _window = _RR[max(0, _idx - 1500):_idx]
    assert 'stage="researching"' in _window


def test_startup_logs_the_loaded_build():
    # "[build] <sha> <date> <subject>" at server start — stale-worker forensics
    # in one grep (source checkouts only; silent for compiled wheels).
    _srv = inspect.getsource(research.run_server)
    assert '"[build] ' in _srv or "[build] {_build}" in _srv
