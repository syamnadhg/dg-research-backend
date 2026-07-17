"""#62 — alert-id collisions + dead-end cards (BE).

Two classes of fix, both source-pinned here (the emitters live inside the huge
async run_pipeline / its nested _phase_timeout_decision, so — like
test_cua_cards_have_distinct_alert_ids — we assert the branch structure rather
than driving a live pipeline):

  1. DISTINCT ALERT IDS. The generic fail_phase default alert_id is
     f"phase{n}_error". Multiple DISTINCT cards at one phase used to share that
     one slot, and the FE dismiss-resurface ledger is keyed on alert_id — so
     dismissing one card permanently silenced the other. The crash_loop card
     and the hard phase-timeout card (both at the same phase) collided this way.
     Each now carries its own id (phase{n}_crash_loop / phase{n}_timeout),
     distinct from each other, from the generic phase{n}_error default, and from
     the soft path's phase{n}_soft_timeout_{ts}.

  2. NO DEAD-END BUTTONS. Three P2 backstops fired a Retry/Skip card then
     immediately returned (one with a paired pipeline_stopped) — after
     run_pipeline returns, teardown_firestore_run() drops the per-run command
     listener, so those buttons wrote to a dead bus. They now render buttonless
     (actions=[]) honest terminal notices. fail_phase is KEPT at each site (its
     unconditional _QUEUE_STATE["_errored"]=True is what dequeues the next queued
     run — deleting the card would wedge the queue), and the two byte-identical
     all-agents-skipped sites now share one alert_id (one logical card).

Run: pytest tests/test_alert_id_collisions_62.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def _pipeline_src() -> str:
    # run_pipeline's getsource includes its nested _phase_timeout_decision and
    # the post-finally crash-loop escalation, so one grab covers every #62 site.
    return inspect.getsource(research.run_pipeline)


# ── 1. distinct alert ids (crash_loop vs hard phase-timeout) ──────────────────

def test_crash_loop_and_timeout_have_distinct_alert_ids():
    src = _pipeline_src()
    # crash_loop escalation carries its own id (mirrors crash_login_interrupt).
    assert 'f"phase{last_phase}_crash_loop"' in src, (
        "crash_loop must not ride the generic phase{n}_error slot — a dismissed "
        "phase-timeout card would silence it via the FE dismiss ledger."
    )
    # both hard-timeout fail_phase calls (primary + except fallback) use the
    # dedicated timeout id.
    assert src.count('f"phase{phase}_timeout"') >= 2, (
        "both _phase_timeout_decision fail_phase calls must carry "
        'phase{phase}_timeout (primary + fallback).'
    )


def test_timeout_id_distinct_from_soft_warn_and_crash():
    # The three timer cards at one phase must all be distinct ids so none can
    # dismiss-suppress another: hard-timeout phase{n}_timeout, soft-warn
    # phase{n}_soft_timeout_{ts}, crash_loop phase{n}_crash_loop.
    src = inspect.getsource(research)
    assert 'f"phase{phase}_soft_timeout_' in src            # soft path (ts-suffixed)
    assert 'f"phase{phase}_timeout"' in src                 # hard path (this fix)
    assert 'f"phase{last_phase}_crash_loop"' in src         # crash path (this fix)


def test_fail_phase_alert_id_override_is_honored(monkeypatch):
    # The mechanism the distinct ids rely on: an alert_id passed via **extra
    # overrides fail_phase's hardcoded phase{n}_error default (payload.update).
    events = []
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(research, "_persist_pending_decision", lambda p: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_phase(2, "t", "d", alert_id="phase2_crash_loop")
    ev = next(k for (a, k) in events if a and a[0] == "pipeline_error")
    assert ev["alert_id"] == "phase2_crash_loop"


# ── 2. no dead-end buttons on the terminal P2 backstops ───────────────────────

def test_p2_terminal_backstops_are_buttonless():
    src = _pipeline_src()
    # no-brief backstop
    assert 'alert_id="phase2_no_brief"' in src
    # both all-agents-skipped sites share one id (the byte-dup merge)
    assert src.count('alert_id="phase2_no_agents"') == 2, (
        "both all-agents-skipped sites (verify-gate + preskip) must share "
        "phase2_no_agents so they are one logical card, not two colliding ones."
    )
    # Every one of the three terminal backstops must pass actions=[] (no buttons
    # that would dead-end after run_pipeline returns + the listener is dropped).
    for _id in ('"phase2_no_brief"', '"phase2_no_agents"'):
        i = src.index(f"alert_id={_id}")
        window = src[i - 260:i + 40]
        assert "actions=[]" in window, (
            f"the terminal backstop {_id} must be buttonless (actions=[]) — a "
            "Retry/Skip button here writes to a torn-down command bus."
        )


def test_p2_terminal_backstops_dropped_dead_end_button_copy():
    src = _pipeline_src()
    # The old copy literally named buttons that did nothing.
    assert "Retry the brief step, or Skip." not in src
    assert "Retry to re-check logins, or Skip." not in src


def test_no_brief_backstop_emits_terminal_stop():
    # #62: the no-brief backstop must drive the run terminal (pipeline_stopped)
    # so the FE's auto-pause-on-error doesn't leave a chat-input Resume that
    # dead-ends (run_pipeline has returned; the command listener is gone).
    src = _pipeline_src()
    i = src.index('alert_id="phase2_no_brief"')
    window = src[i:i + 700]
    assert 'emit_event("pipeline_stopped", phase=2, reason="no_brief_for_phase2")' in window, (
        "the no-brief buttonless notice must be followed by pipeline_stopped — "
        "else the FE stays paused with a dead-end Resume."
    )


def test_p2_all_skipped_still_keeps_queue_advancing_failphase():
    # fail_phase must remain at the all-skipped + no-brief sites: its
    # unconditional _QUEUE_STATE["_errored"]=True is what lets the next queued
    # run dequeue promptly (a bare return would wedge it on the fallback timer).
    src = _pipeline_src()
    assert 'fail_phase(2,\n                               "No agents left to run"' in src
    assert 'fail_phase(2, "No brief to research"' in src
