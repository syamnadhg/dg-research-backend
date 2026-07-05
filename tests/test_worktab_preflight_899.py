"""#899 — work-tab preflight helpers (phase A).

The isolated verify tab is being retired: every phase confirms sign-in on the
tab it is about to WORK in (zero extra navigations = zero extra bot-score),
DOM-only, with the login_required pause upgraded from a pure event wait to an
HV-style poll loop that auto-resumes when the user signs in inside the open
tab. These tests pin the two helpers that carry that design:

  _work_tab_signed_out   — double-probe wall confirm (+3s settle re-probe so
                           slow SPA hydration can't false-alarm) + flips
                           cookie_trust_broken on a confirmed wall.
  _work_tab_login_pause  — same events/alert_id/pendingDecision contract as
                           the old gate, resolutions: auto-resume / Retry
                           reload / Skip / stop / timeout→skip.

Review-hardened (adversarial pass, 2026-07-04): agent-scoped mirror payload +
re-persist on every re-pause (a cross-agent card click must not permanently
kill cold-open recovery); pipeline_resumed/pipeline_paused re-emitted on the
wake/re-pause cycle (the FE Retry click optimistically un-pauses — without
the re-emit the FE shows 'running' against a parked BE); 'ok' requires the
WORK page (an IdP landing is wall-free but proves nothing); a Skip landing
mid-probe beats a simultaneous 'ok'; Google's modern /v3/signin resting URLs
count as walls (the legacy /servicelogin is just a 302 hop).
"""
import inspect
import types

import pytest

import research


# ── fakes ─────────────────────────────────────────────────────────────────────

class _FakeControls:
    def __init__(self):
        self.cookie_trust_broken = set()
        self.login_pause_timeout_agents = set()
        self.skipped_agents = set()
        self.skip_init_verify = True
        self.pause_target_agent = ""
        self.retry_init_verify = False
        self._stop = False
        self._paused = False
        self.pause_reasons = []
        self.resume_count = 0
        self.consumed_retry_phases = []

    def is_stop(self):
        return self._stop

    def is_pause(self):
        return self._paused

    def request_pause(self, reason):
        self._paused = True
        self.pause_reasons.append(reason)

    def request_resume(self):
        self._paused = False
        self.resume_count += 1
        self.pause_target_agent = ""

    def consume_retry_phase(self, phase):
        self.consumed_retry_phases.append(phase)
        return False


class _FakePage:
    def __init__(self, url="https://chatgpt.com/", closed=False, goto_raises=False):
        self.url = url
        self._closed = closed
        self._goto_raises = goto_raises
        self.goto_calls = []

    def is_closed(self):
        return self._closed

    async def goto(self, url, **kw):
        self.goto_calls.append(url)
        if self._goto_raises:
            raise RuntimeError("Target page, context or browser has been closed")
        self.url = url

    async def evaluate(self, _js):
        return False


@pytest.fixture
def harness(monkeypatch):
    """Patch the module seams the helpers reach for; every probe/emit is
    recorded so the tests assert the CONTRACT, not implementation order."""
    ctl = _FakeControls()
    events = []
    persisted = []
    cleared = []

    async def _fast_sleep(_s):
        return None

    monkeypatch.setattr(research, "_controls", ctl)
    monkeypatch.setattr(research, "emit_event",
                        lambda ev, **kw: events.append((ev, kw)))
    monkeypatch.setattr(research, "_persist_pending_decision",
                        lambda payload: persisted.append(payload))
    monkeypatch.setattr(research, "_clear_pending_decision",
                        lambda *a, **kw: cleared.append(a))
    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)
    return types.SimpleNamespace(ctl=ctl, events=events, persisted=persisted,
                                 cleared=cleared, monkeypatch=monkeypatch)


def _probe_script(harness, results):
    """_page_shows_login_wall stub fed from a list; when the list runs dry it
    keeps returning the last value. Entries may be callables (side effects)."""
    seq = list(results)
    calls = []

    async def _probe(_page):
        step = seq.pop(0) if len(seq) > 1 else seq[0]
        if callable(step):
            step = step()
        calls.append(step)
        return step

    harness.monkeypatch.setattr(research, "_page_shows_login_wall", _probe)
    return calls


def _events_named(harness, name):
    return [kw for ev, kw in harness.events if ev == name]


# ── _work_tab_signed_out: double-probe confirm ────────────────────────────────

@pytest.mark.asyncio
async def test_signed_out_requires_wall_to_survive_settle_reprobe(harness):
    calls = _probe_script(harness, ["login page (auth.openai.com)",
                                    "login page (auth.openai.com)"])
    detail = await research._work_tab_signed_out(_FakePage(), "chatgpt", "ChatGPT")
    assert detail == "login page (auth.openai.com)"
    assert "chatgpt" in harness.ctl.cookie_trust_broken
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_transient_wall_read_is_not_signed_out(harness):
    # Slow SPA hydration paints the logged-out shell for a beat — the wall
    # vanishing on the +3s re-probe must NOT flag the platform.
    _probe_script(harness, ["logged-out landing (Log in button visible)", None])
    detail = await research._work_tab_signed_out(_FakePage(), "claude", "Claude")
    assert detail is None
    assert harness.ctl.cookie_trust_broken == set()


@pytest.mark.asyncio
async def test_signed_in_page_probes_once_and_passes(harness):
    calls = _probe_script(harness, [None])
    detail = await research._work_tab_signed_out(_FakePage(), "gemini", "Gemini")
    assert detail is None
    assert len(calls) == 1  # no settle wait burned on the healthy path
    assert harness.ctl.cookie_trust_broken == set()


@pytest.mark.asyncio
async def test_google_signin_hosts_count_as_walls():
    # Google's sign-in flow RESTS on /v3/signin/* (identifier + password
    # challenge pages) — a mid-sign-in user is still walled. /ServiceLogin is
    # the legacy 302 hop toward it. These URL negatives are the ONLY
    # signed-out tell for Gemini/NotebookLM (the DOM probes are
    # ChatGPT-specific), so both generations must match, case-insensitively.
    for frag in ("accounts.google.com/servicelogin",
                 "accounts.google.com/v3/signin"):
        assert frag in research._LOGIN_HOST_NEGATIVES
    for url in (
        "https://accounts.google.com/ServiceLogin?continue=https://notebooklm.google.com",
        "https://accounts.google.com/v3/signin/identifier?ifkv=xyz",
        "https://accounts.google.com/v3/signin/challenge/pwd",
    ):
        assert await research._page_shows_login_wall(_FakePage(url)) is not None, url


def test_session_expiry_markers_are_lowercase_and_know_v3():
    # The old "accounts.google.com/serviceLogin" camelCase marker was matched
    # against a LOWERCASED url — dead code that could never fire.
    src = inspect.getsource(research.detect_session_expiry)
    assert '"accounts.google.com/serviceLogin"' not in src  # the dead marker itself
    assert "accounts.google.com/v3/signin" in src


def test_cli_skip_routes_login_required_pause_to_skip_agent():
    # The work-tab login pause names its platform via pause_target_agent and
    # its poll loop watches skipped_agents — the CLI `s` must route there,
    # not to request_skip_phase (wrong set: the loop would re-card until
    # timeout AND leave a stale skipped_phases entry that await_phase_decision
    # later eats as a silent 'skip').
    src = inspect.getsource(research)
    assert 'pr == "login_required" and (getattr(_controls, "pause_target_agent", "") or "")' in src


# ── phase B: P2 wiring ────────────────────────────────────────────────────────

def test_p2_preflight_probes_before_setup():
    # Layer 0.5: the signed-out probe must run on the work tab BEFORE any
    # setup_*_dr clicks are spent on a logged-out page, and its card must use
    # the honest signed-out copy (matching the outer fail paths). Non-blocking
    # by design: a per-agent fail card + (page, False) — never a pipeline
    # pause (the other agents keep starting; Retry re-enters fresh).
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert "_work_tab_signed_out(page, platform_l, label)" in src
    probe_at = src.index("_work_tab_signed_out")
    setup_at = src.index("setup_chatgpt_dr")
    assert probe_at < setup_at
    # The wall branch must card-and-BAIL. Dropping the early return would
    # burn setup clicks on the confirmed-walled page — the exact failure
    # Layer 0.5 exists to prevent — while the rest of the suite stayed green
    # (mutation-verified in review). Scope the pins to the branch itself.
    branch = src[probe_at:setup_at]
    assert "return page, False" in branch
    assert 'status="needs_login"' in branch
    assert 'fail_agent(platform_l, f"{platform} looks signed out"' in branch
    assert "_work_tab_login_pause" not in src


def test_chatgpt_gets_a_zero_navigation_tier_backstop():
    # ChatGPT parity with 2C's Gemini DOM-tier read: with verification off by
    # default and the gate's isolated-tab tier check retired, this is
    # ChatGPT's Free-tier tell on runs where the P1 Pro-selector backstop
    # never runs (skip-P1 / attached-sources runs).
    src = inspect.getsource(research.run_phase2)
    assert "_chatgpt_dom_tier(chatgpt_page)" in src
    assert '_emit_pro_required_alert(phase=2, agent="chatgpt", source="phase2/setup_pro_backstop")' in src
    # POSITION is load-bearing (review MAJOR): the read must sit AFTER 2C so
    # its pro_required pause can only delay round-robin polling — a pause
    # inside 2A would freeze Claude + Gemini startup behind a fail-open DOM
    # heuristic (2/3 of the phase never launching on an unattended run).
    assert src.index("_chatgpt_dom_tier(chatgpt_page)") > src.index("_gemini_dom_tier(gemini_page)")
    _idx = src.index("_chatgpt_dom_tier(chatgpt_page)")
    _blk = src[_idx - 900:_idx + 3400]
    # all three guards (consent ×2 + liveness), the pause machinery, and a
    # resolution for EVERY path — Skip must close the paused/resumed pair
    # (mutation-verified gaps in review: each of these was droppable green).
    assert "pro_warning_acknowledged" in _blk
    assert 'free_tier_consent.get("chatgpt"' in _blk
    assert '"chatgpt" not in _controls.skipped_agents' in _blk
    assert '_controls.request_pause("pro_required")' in _blk
    assert "wait_if_paused" in _blk
    assert 'reason="agent_skipped"' in _blk


def test_p2_tier_backstop_skip_closes_pause_pair():
    # BOTH tier backstops (2C Gemini + post-2C ChatGPT) must emit
    # pipeline_resumed on the Skip path. Every other pro_required wait site
    # closes the paused/resumed pair; an unclosed pipeline_paused leaves the
    # FE pause chrome stale (the F3/DGOPS-7449 stale-alert class).
    src = inspect.getsource(research.run_phase2)
    assert src.count('emit_event("pipeline_resumed", phase=2, reason="agent_skipped")') >= 2


def test_chatgpt_tier_retry_actually_re_verifies():
    # The pro_required card promises 'sign in with Pro, then Retry' — Retry
    # must RE-READ the tier (review MAJOR: it was a silent no-op that left
    # the card unresolved). A still-free re-read resolves to
    # Free-acknowledged + alert clear, never an unbounded re-card loop.
    src = inspect.getsource(research.run_phase2)
    assert src.count("_chatgpt_dom_tier(chatgpt_page)") >= 2
    # the first pro_retry AFTER the ChatGPT tier read (the 2C Gemini block
    # has its own, earlier pro_retry — don't pin that one)
    _retry_at = src.index('reason="pro_retry"', src.index("_chatgpt_dom_tier(chatgpt_page)"))
    _retry_blk = src[_retry_at:_retry_at + 1200]
    assert "_chatgpt_dom_tier(chatgpt_page)" in _retry_blk
    assert "_clear_pro_required_alerts(triggered_at_phase=2)" in _retry_blk


# ── phase C: P1 + P3 wiring ───────────────────────────────────────────────────

def test_p1_preflight_pauses_on_the_work_tab():
    # P1 probes the tab it is about to drive, BEFORE the HV gate / Pro
    # selection burn CUA on a signed-out page. Single-agent phase → the
    # helper PAUSES (auto-resume on in-tab sign-in), unlike P2's fail cards.
    src = inspect.getsource(research.run_phase1)
    assert '_work_tab_signed_out(browser.page, "chatgpt", "ChatGPT")' in src
    probe_at = src.index("_work_tab_signed_out")
    assert probe_at < src.index("check_hv_gate")
    # BOTH P1 pause sites (preflight + the Pro-backstop's late wall branch)
    # route through the helper — the old inline pause with no Skip branch is
    # gone, and the helper owns the pendingDecision mirror now.
    assert src.count("_work_tab_login_pause") == 2
    assert "_persist_pending_decision" not in src
    # RESULT handling is load-bearing (review: deleting it left the suite
    # green — the preflight became decorative). Preflight branch: stop AND
    # skipped both bail out of the phase.
    pre_blk = src[probe_at:probe_at + 900]
    assert pre_blk.count("return None") >= 2
    assert '== "stop"' in pre_blk and '== "skipped"' in pre_blk
    # Late wall branch: same bails + 'ok' re-loops the Pro selector.
    late_at = src.index("_work_tab_signed_out", probe_at + 1)
    late_blk = src[late_at:late_at + 1100]
    assert late_blk.count("return None") >= 2
    assert "continue" in late_blk


def test_p1_login_skip_routes_to_manual_brief():
    # EXPLICIT Skip at the P1 login pause = "I'll write the brief myself":
    # the caller goes STRAIGHT to the manual-brief flow. The unattended
    # 10-min TIMEOUT does NOT — it gets the Retry-able "No brief" card (a
    # returning user signs in + Retries; review: hardcoding skip stranded
    # the run in a 3h typed-brief wait nobody asked for). Exactly ONE
    # phase_skipped:1 with the honest reason.
    src = inspect.getsource(research)
    assert '"chatgpt" in _controls.login_pause_timeout_agents' in src
    i = src.index('_p1_login_timeout = ')
    blk = src[i:i + 3000]
    assert '"chatgpt" in _controls.skipped_agents' in blk
    assert 'decision = "skip"' in blk
    # Retry must clear the stale skip or the preflight pause returns
    # 'skipped' on its first tick and Retry can never work.
    assert 'skipped_agents.discard("chatgpt")' in blk
    assert 'login_pause_timeout_agents.discard("chatgpt")' in blk
    # single conditional-reason emit — no double phase_skipped
    assert ('reason=("user_skip_at_login_pause" if _p1_login_skipped'
            in src)


def test_p2_trims_preskipped_agents_before_launch():
    # A P1 login-pause skip leaves chatgpt in skipped_agents REGARDLESS of
    # verifyLogins, but the P2 verify-gate loop only consumes it on
    # skip-init runs (review MAJOR: on init-verified runs 2A re-launched
    # ChatGPT — re-asking the decision, or letting the round-robin's skip
    # consumer kill a fresh DR on its first tick). The caller must trim
    # enabled_agents by skipped_agents unconditionally.
    src = inspect.getsource(research)
    i = src.index("_p2_preskipped = ")
    blk = src[i - 200:i + 1400]
    assert "[a for a in enabled_agents if a in _controls.skipped_agents]" in blk
    assert "enabled_agents = [a for a in enabled_agents if a not in _p2_preskipped]" in blk
    assert 'emit_event("agent_skipped", phase=2' in blk
    # the honest reason split: timeout ≠ user decision
    assert "login_required_timeout" in blk


def test_p3_upload_preflights_and_respects_prior_skip():
    src = inspect.getsource(research.run_phase3_upload)
    # entry guard: a prior Skip (login pause leaves notebooklm in
    # skipped_agents) must not re-prompt or burn CUA on re-entry
    assert '"notebooklm" in _controls.skipped_agents' in src
    # preflight probes the fresh tab BEFORE the first upload agent_loop
    assert '_work_tab_signed_out(page, "notebooklm", "NotebookLM")' in src
    probe_at = src.index("_work_tab_signed_out")
    assert probe_at < src.index("PROMPT_NOTEBOOKLM_UPLOAD")
    # RESULT handling: stop/skipped must BREAK out (empty notebook_url),
    # never fall through into the upload agent_loops on a signed-out tab.
    blk = src[probe_at:probe_at + 900]
    assert 'in ("stop", "skipped")' in blk and "break" in blk


def test_p3_audio_preflights_and_midpoll_pause_upgraded():
    src = inspect.getsource(research.run_phase3_audio)
    # entry skip guard — the no-audio auto-retry loop re-enters this function
    assert '"notebooklm" in _controls.skipped_agents' in src
    # two pause sites: the post-navigate preflight + the mid-poll expiry
    # check (upgraded from the bare pause-less login_required emit that
    # re-carded every cycle with no alert_id and no durable mirror)
    assert src.count("_work_tab_login_pause") == 2
    assert 'reason="notebooklm_login_expired"' not in src
    # RESULT handling at both sites: preflight returns the no-audio shape;
    # the mid-poll pause breaks the poll loop.
    pre_at = src.index("_work_tab_login_pause")
    pre_blk = src[pre_at:pre_at + 700]
    assert 'in ("stop", "skipped")' in pre_blk
    assert 'return {"audio_path": None}' in pre_blk
    poll_at = src.index("_work_tab_login_pause", pre_at + 1)
    poll_blk = src[poll_at:poll_at + 700]
    assert 'in ("stop", "skipped")' in poll_blk and "break" in poll_blk


def test_p3_login_skip_cascades_p4_and_never_fakes_complete():
    # A login-pause Skip means no notebook → the OUTER extract-retry gate
    # must take the skip branch (review: dropping '_p3_login_skipped or'
    # from the condition stayed green while resurrecting the re-prompt),
    # P4 cascades off, a TERMINAL phase_skipped:3 is emitted (it also
    # live-triggers FE-P4's no-audio fast path → FE-P5), and the green
    # "NotebookLM notebook created" phase_complete is suppressed.
    src = inspect.getsource(research)
    assert "if _p3a_user_skipped or _p3_login_skipped or _controls.is_stop():" in src
    i = src.index("_p3_login_skipped = ")
    blk = src[i:i + 1400]
    assert "skipped_phases.add(4)" in blk
    assert 'emit_event("phase_skipped", phase=3' in blk
    # the complete emit is gated on BOTH skip flags + stop
    assert ("if (not _p3_audio_user_skipped and not _p3_login_skipped"
            in src)


# ── phase D: the slimmed gate is a pure trust check (functional) ─────────────

def _gate_cookie(harness, present):
    calls = []

    async def _probe(_browser, _key):
        calls.append(_key)
        return present

    harness.monkeypatch.setattr(research, "_platform_auth_cookie_present", _probe)
    return calls


async def _run_gate(harness, agent="chatgpt", phase=1):
    return await research._phase_verify_gate(phase, agent, object(), None)


@pytest.mark.asyncio
async def test_gate_trusts_a_present_cookie(harness):
    _gate_cookie(harness, True)
    assert await _run_gate(harness) == "ok"
    ev = dict(harness.events)
    assert ev["agent_progress"]["status"] == "verified"
    assert harness.ctl.pause_reasons == [] and not harness.persisted


@pytest.mark.asyncio
async def test_gate_cookie_miss_is_unverified_not_a_pause(harness):
    # #899: cookie missing → honest 'unverified' tile line, return 'ok',
    # and NOTHING else — no tab, no pause, no mirror. The work-tab
    # preflight owns the real outcome.
    _gate_cookie(harness, False)
    assert await _run_gate(harness) == "ok"
    ev = dict(harness.events)
    assert ev["agent_progress"]["status"] == "unverified"
    assert "will confirm on the work page" in ev["agent_progress"]["progress"]
    assert harness.ctl.pause_reasons == [] and not harness.persisted


@pytest.mark.asyncio
async def test_gate_never_re_trusts_a_broken_jar(harness):
    # trust-broken + cookie PRESENT must read unverified (review: a source
    # guard alone couldn't catch the condition being inverted) — and the
    # cookie probe isn't even consulted for a broken platform.
    harness.ctl.cookie_trust_broken.add("chatgpt")
    calls = _gate_cookie(harness, True)
    assert await _run_gate(harness) == "ok"
    assert dict(harness.events)["agent_progress"]["status"] == "unverified"
    assert calls == []


@pytest.mark.asyncio
async def test_gate_early_outs(harness):
    calls = _gate_cookie(harness, True)
    # verifyLogins ON (skip_init_verify False) → no-op 'ok', zero emits
    harness.ctl.skip_init_verify = False
    assert await _run_gate(harness) == "ok"
    assert harness.events == [] and calls == []
    # prior-skip echo
    harness.ctl.skip_init_verify = True
    harness.ctl.skipped_agents.add("chatgpt")
    assert await _run_gate(harness) == "skipped"
    # stop
    harness.ctl.skipped_agents.clear()
    harness.ctl._stop = True
    assert await _run_gate(harness) == "stop"


# ── _work_tab_login_pause: the FE contract on entry ───────────────────────────

async def _run_pause(harness, page=None, agent="chatgpt", phase=1,
                     label="ChatGPT", work_url="https://chatgpt.com"):
    return await research._work_tab_login_pause(
        page or _FakePage(), agent, phase, label, work_url=work_url)


@pytest.mark.asyncio
async def test_pause_emits_gate_compatible_contract_then_auto_resumes(harness):
    # Wall on the first ticks' probes, gone (settled) from then on: the user
    # signed in INSIDE the open tab, no button press.
    page = _FakePage()
    _probe_script(harness, ["wall", "wall", None])
    out = await _run_pause(harness, page=page)
    assert out == "ok"

    ev = dict(harness.events)
    assert "login_required" in ev and ev["login_required"]["alert_id"] == "phase1_login_required_chatgpt"
    assert ev["login_required"]["phase"] == 1 and ev["login_required"]["platforms"] == ["chatgpt"]
    assert ev["pipeline_paused"]["reason"] == "login_required"
    # the needs_login progress emit must precede the final verified one
    statuses = [kw.get("status") for kw in _events_named(harness, "agent_progress")]
    assert statuses[0] == "needs_login" and statuses[-1] == "verified"
    # durable mirror: FULL payload shape (cold-open decisionToCard hydration),
    # agent-scoped so a different agent's card click can't retract it,
    # retracted on resolve.
    assert harness.persisted
    p = harness.persisted[0]
    assert p["kind"] == "login_required" and p["agent"] == "chatgpt"
    assert p["platforms"] == ["chatgpt"] and p["platformLabels"] == ["ChatGPT"]
    assert p["alert_id"] == "phase1_login_required_chatgpt"
    assert p["attempt"] == 1 and p["machineName"] and p["message"]
    assert harness.cleared
    assert ev["pipeline_resumed"]["reason"] == "login_cleared"
    assert harness.ctl.resume_count == 1 and not harness.ctl.is_pause()
    # 'ok' must be confirmed ON the work page, not wherever the redirect
    # chain (or the user) left the tab.
    assert page.goto_calls == ["https://chatgpt.com"]


@pytest.mark.asyncio
async def test_auto_resume_restores_cookie_trust(harness):
    # 'ok' is the ONLY mid-run remover of cookie_trust_broken — trust comes
    # back by direct observation of the signed-in work page, nothing else.
    harness.ctl.cookie_trust_broken.add("notebooklm")
    harness.ctl.login_pause_timeout_agents.add("notebooklm")  # stale marker from an earlier timeout
    _probe_script(harness, ["wall", "wall", None])
    out = await _run_pause(harness, agent="notebooklm", phase=3, label="NotebookLM",
                           work_url="https://notebooklm.google.com")
    assert out == "ok"
    assert "notebooklm" not in harness.ctl.cookie_trust_broken
    assert "notebooklm" not in harness.ctl.login_pause_timeout_agents


@pytest.mark.asyncio
async def test_mid_redirect_blank_does_not_fake_a_sign_in(harness):
    # Settled-gone: ONE wall-free read (a mid-redirect blank) must not
    # resolve — the wall returning on the +3s re-probe keeps the pause.
    calls = _probe_script(harness, ["wall", None, "wall", None, None])
    out = await _run_pause(harness)
    assert out == "ok"
    # both walls were observed — the blank read did NOT shortcut past the
    # second one (it was settle-re-probed and rejected)
    assert calls.count("wall") == 2
    assert dict(harness.events)["pipeline_resumed"]["reason"] == "login_cleared"


@pytest.mark.asyncio
async def test_skip_leaves_agent_in_skipped_set_and_releases_the_pause(harness):
    def _skip_side_effect():
        harness.ctl.skipped_agents.add("chatgpt")
        return "wall"
    _probe_script(harness, [_skip_side_effect, "wall"])
    out = await _run_pause(harness)
    assert out == "skipped"
    # UNLIKE the HV pause (which discards), the login contract leaves the
    # agent in skipped_agents — later phases/gates respect the decision, and
    # the P1 caller keys manual-brief routing off exactly this membership.
    assert "chatgpt" in harness.ctl.skipped_agents
    assert harness.cleared
    assert dict(harness.events)["pipeline_resumed"]["reason"] == "agent_skipped"
    # pause fully released even if a re-pause re-armed it after the
    # dispatcher's resume (the Retry→Skip race) — no orphaned pause_event.
    assert harness.ctl.resume_count >= 1 and not harness.ctl.is_pause()


@pytest.mark.asyncio
async def test_skip_landing_mid_probe_beats_ok(harness):
    # A Skip that lands while the settled/work-page probes are in flight must
    # win over the simultaneous 'ok' — otherwise the phase runs NOW while the
    # agent silently stays in skipped_agents for every later phase (a
    # half-applied skip with a contradictory 'verified' event on record).
    def _gone_but_skip_landed():
        harness.ctl.skipped_agents.add("chatgpt")
        return None
    _probe_script(harness, [_gone_but_skip_landed, None])
    out = await _run_pause(harness)
    assert out == "skipped"
    statuses = [kw.get("status") for kw in _events_named(harness, "agent_progress")]
    assert "verified" not in statuses


@pytest.mark.asyncio
async def test_stop_wins_immediately(harness):
    harness.ctl._stop = True
    _probe_script(harness, ["wall"])
    out = await _run_pause(harness)
    assert out == "stop"
    assert harness.cleared
    assert dict(harness.events)["pipeline_stopped"]["reason"] == "stopped during login_required"


@pytest.mark.asyncio
async def test_retry_reloads_the_work_url_then_probes(harness):
    # User signs in (maybe in another window) and taps Retry → the pause
    # lifts, the helper acknowledges with pipeline_resumed (the FE already
    # optimistically un-paused), reloads the WORK url (the tab may be parked
    # on the login host) and probes settled-gone there.
    page = _FakePage(url="https://auth.openai.com/authorize")
    _probe_script(harness, [None, None])

    real_pause = harness.ctl.request_pause

    def _pause_then_lift(reason):
        real_pause(reason)
        # simulate the dispatcher's Retry: sets the flag + releases the pause
        harness.ctl.retry_init_verify = True
        harness.ctl._paused = False

    harness.ctl.request_pause = _pause_then_lift
    out = await _run_pause(harness, page=page)
    assert out == "ok"
    assert page.goto_calls == ["https://chatgpt.com"]
    assert harness.ctl.consumed_retry_phases == [1]
    # the retry flag was CONSUMED (set True by the simulated dispatcher above)
    # — a stale True later replays P0 re-verify semantics.
    assert harness.ctl.retry_init_verify is False
    reasons = [kw.get("reason") for kw in _events_named(harness, "pipeline_resumed")]
    assert reasons[0] == "retry"


@pytest.mark.asyncio
async def test_retry_while_still_walled_re_pauses_and_re_persists(harness):
    # Retry with the sign-in page still up: full re-card — pipeline_resumed
    # (retry) on the wake, then login_required + pipeline_paused + a FRESH
    # mirror persist on the re-pause. The FE Retry click optimistically
    # un-pauses, so without the pipeline_paused re-emit the FE shows
    # 'running' against a parked BE; without the re-persist a cold chat-open
    # resurrects stale copy (or, after a cross-agent clear, nothing at all).
    page = _FakePage(url="https://auth.openai.com/authorize")
    _probe_script(harness, ["wall", "wall", None])

    real_pause = harness.ctl.request_pause
    lifted = {"done": False}

    def _pause_once_lift(reason):
        real_pause(reason)
        if not lifted["done"]:
            lifted["done"] = True
            harness.ctl._paused = False

    harness.ctl.request_pause = _pause_once_lift
    out = await _run_pause(harness, page=page)
    assert out == "ok"
    assert harness.ctl.pause_reasons == ["login_required", "login_required"]
    logins = _events_named(harness, "login_required")
    assert len(logins) == 2
    assert {kw["alert_id"] for kw in logins} == {"phase1_login_required_chatgpt"}
    assert len(_events_named(harness, "pipeline_paused")) == 2
    resumed = [kw.get("reason") for kw in _events_named(harness, "pipeline_resumed")]
    assert "retry" in resumed
    # mirror re-persisted with the LIVE corrective copy, still agent-scoped
    assert len(harness.persisted) == 2
    assert "still shows its sign-in page" in harness.persisted[1]["message"]
    assert harness.persisted[1]["agent"] == "chatgpt"


@pytest.mark.asyncio
async def test_retry_with_dead_tab_swallows_nav_error_and_re_pauses(harness):
    # User closed the work tab, then tapped Retry: goto raises, the in-place
    # probe runs on a dead page (is_closed guard → still walled), and the
    # helper re-cards + re-pauses — it must NOT crash and must NOT return a
    # false 'ok'. Rides to the timeout-skip.
    harness.monkeypatch.setattr(research, "_WORK_TAB_LOGIN_MAX_LOOPS", 2)
    page = _FakePage(url="https://auth.openai.com/authorize",
                     closed=True, goto_raises=True)
    _probe_script(harness, [None])

    real_pause = harness.ctl.request_pause
    lifted = {"done": False}

    def _pause_once_lift(reason):
        real_pause(reason)
        if not lifted["done"]:
            lifted["done"] = True
            harness.ctl._paused = False

    harness.ctl.request_pause = _pause_once_lift
    out = await _run_pause(harness, page=page)
    assert out == "skipped"
    assert len(page.goto_calls) == 1  # the raise was swallowed, not retried blindly
    assert len(_events_named(harness, "login_required")) == 2  # entry + re-card
    statuses = [kw.get("status") for kw in _events_named(harness, "agent_progress")]
    assert "verified" not in statuses


@pytest.mark.asyncio
async def test_timeout_degrades_to_skip_not_a_hang(harness):
    harness.monkeypatch.setattr(research, "_WORK_TAB_LOGIN_MAX_LOOPS", 3)
    _probe_script(harness, ["wall"])
    out = await _run_pause(harness, agent="notebooklm", phase=3, label="NotebookLM",
                           work_url="https://notebooklm.google.com")
    assert out == "skipped"
    assert "notebooklm" in harness.ctl.skipped_agents
    # timeout ≠ user decision — the marker lets P1's caller offer the
    # Retry-able card instead of hardcoding the manual-brief skip
    assert "notebooklm" in harness.ctl.login_pause_timeout_agents
    # mirror retracted + pause released — a cold chat-open must not paint a
    # ghost login card, and the pipeline must not stay paused (HV parity).
    assert harness.cleared
    assert harness.ctl.resume_count == 1 and not harness.ctl.is_pause()
    ev_names = [ev for ev, _ in harness.events]
    assert "agent_skipped" in ev_names


@pytest.mark.asyncio
async def test_closed_tab_never_reads_as_signed_in(harness):
    # A dead page can't confirm anything: _page_shows_login_wall returns None
    # on it, so WITHOUT the is_closed guard the pause would happily return
    # 'ok' on a tab the user closed. It must ride to the timeout-skip instead.
    harness.monkeypatch.setattr(research, "_WORK_TAB_LOGIN_MAX_LOOPS", 2)
    page = _FakePage(closed=True)
    _probe_script(harness, [None])
    out = await _run_pause(harness, page=page)
    assert out == "skipped"
