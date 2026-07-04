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
import types

import pytest

import research


# ── fakes ─────────────────────────────────────────────────────────────────────

class _FakeControls:
    def __init__(self):
        self.cookie_trust_broken = set()
        self.skipped_agents = set()
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
    src = __import__("inspect").getsource(research.detect_session_expiry)
    assert '"accounts.google.com/serviceLogin"' not in src  # the dead marker itself
    assert "accounts.google.com/v3/signin" in src


def test_cli_skip_routes_login_required_pause_to_skip_agent():
    # The work-tab login pause names its platform via pause_target_agent and
    # its poll loop watches skipped_agents — the CLI `s` must route there,
    # not to request_skip_phase (wrong set: the loop would re-card until
    # timeout AND leave a stale skipped_phases entry that await_phase_decision
    # later eats as a silent 'skip').
    src = __import__("inspect").getsource(research)
    assert 'pr == "login_required" and (getattr(_controls, "pause_target_agent", "") or "")' in src


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
    _probe_script(harness, ["wall", "wall", None])
    out = await _run_pause(harness, agent="notebooklm", phase=3, label="NotebookLM",
                           work_url="https://notebooklm.google.com")
    assert out == "ok"
    assert "notebooklm" not in harness.ctl.cookie_trust_broken


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
