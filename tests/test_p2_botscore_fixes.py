"""P2 bot-score fixes (2026-07-06) — locks three user-approved changes:

1. CLAUDE: the cycle-2 "unstick prophylaxis" reload is REMOVED (with its
   DGOPS-7367 DNS-backoff retry machinery, which existed only to retry it).
   On the 2026-07 claude.ai SPA a mid-run reload blanked the conversation and
   the artifact card, `_count_claude_artifacts` read 0 twice, and the CUA
   tier-3 fallback then vision-misclicked the SIDEBAR chat's ⋮ menu
   (Star/Rename popup — user screenshot). Mirrors the #897a Gemini
   never-reload removal. The sources panel opens IN-PLACE from the live DOM.

2. CHATGPT 2A: REUSE the warm Phase-1 ChatGPT tab (client-side "New chat")
   instead of opening a second tab via `new_tab("https://chatgpt.com")`.
   Every cold top-level chatgpt.com load is a Cloudflare bot-score event;
   P2 was paying a second one per run right after P1 established a warm,
   challenge-passed tab ("already in ChatGPT from Phase 1" — the code's own
   comment). Skip-P1 runs fall back to the fresh-tab path automatically.

3. HV-TRIM: for a POSITIVELY-identified Cloudflare wall the clearance
   cascade skips the score-raising tiers — CUA checkbox re-clicks (failed
   attestations that re-issue + raise the score, #896) and the kill-tab
   (another cold nav a fresh tab can't fix, attestation being profile+IP-
   scoped) — and check_hv_gate never re-runs the chain a second time.
   Non-Cloudflare / unknown challenges keep the FULL cascade.
"""

import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402


# ── 1. Claude cycle-2 reload + DNS-backoff machinery gone ────────────────────

def test_dns_backoff_machinery_removed():
    # The whole DGOPS-7367 subsystem existed only to retry the prophylaxis
    # reload; with the reload gone it must be gone too (dead code).
    assert not hasattr(research, "_advance_dns_backoff")
    assert not hasattr(research, "_is_transient_net_error")
    assert not hasattr(research, "_DNS_BACKOFF_SECS")
    assert not hasattr(research, "_TRANSIENT_NET_ERRORS")


def test_no_claude_cycle2_reload_in_poll_loop():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    # The one-shot refresh + its bookkeeping key must be gone. (A tombstone
    # comment documents the removal — assert on the functional markers.)
    assert "claude_refreshed_once" not in src, (
        "the Claude cycle-2 'unstick prophylaxis' reload must stay removed — "
        "a mid-run reload blanks the claude.ai conversation and cascades into "
        "the CUA sidebar mis-click (Star/Rename popup)."
    )
    assert "dns_retry_at" not in src, (
        "no DNS-retry state may survive in the poll loop — the machinery "
        "existed only for the removed reload."
    )
    # The ONLY reload left in the poll loop is the session-expiry re-auth
    # branch (fires only after a confirmed logged-out detection + user Retry).
    assert src.count('.reload(') == 1, (
        "exactly one reload may remain in poll_all_agents_round_robin — the "
        "session-expiry re-auth branch. Any other mid-run reload is a "
        "regression of the 2026-07-06 removal."
    )
    assert "Reload after re-auth failed" in src  # …and it is that branch.


def test_claude_artifact_panel_still_opens_in_place():
    # The in-place DOM path (poll loop → scrape_claude_artifact_tracking →
    # _click_claude_artifact) is what replaces the reload — it must survive.
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "scrape_claude_artifact_tracking" in src
    src_scrape = inspect.getsource(research.scrape_claude_artifact_tracking)
    assert "_click_claude_artifact" in src_scrape


# ── 2. ChatGPT 2A warm-tab reuse ─────────────────────────────────────────────

def test_start_agent_accepts_reuse_page():
    sig = inspect.signature(research.start_agent_no_gemini_wait)
    assert "reuse_page" in sig.parameters
    assert sig.parameters["reuse_page"].default is None, (
        "reuse_page must default to None so every other caller (2B/2C, "
        "hard-retry restart, known-good fallback) keeps fresh-tab behavior."
    )


def test_reuse_branch_falls_back_to_fresh_tab():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    # Reuse is guarded (closed tab → fresh tab) and the fresh-tab path remains.
    assert "reuse_page.is_closed()" in src
    assert "browser.new_tab(url)" in src
    assert "_chatgpt_force_new_chat" in src
    # SPA New-chat failure degrades to a same-tab goto, never a second tab.
    assert "page.goto(url" in src


def test_2a_passes_warm_tab_and_guards_the_close():
    src = inspect.getsource(research.run_phase2)
    # 2A: warm tab passed on attempt 0 only; retry gets a fresh tab.
    assert "reuse_page=_warm_chatgpt_tab if attempt == 0 else None" in src
    # The retry-close must never close the reused P1/main tab.
    assert "chatgpt_page is not _warm_chatgpt_tab" in src
    # ChatGPT-only: exactly one warm-tab pass in Phase 2 — Claude (2B) and
    # Gemini (2C) keep their own fresh tabs (their calls pass no reuse_page,
    # so the kwarg's None default applies).
    assert src.count("reuse_page=_warm_chatgpt_tab") == 1
    for _other_agent_url in ("claude.ai/new", "gemini.google.com"):
        _seg = src[src.index(_other_agent_url):src.index(_other_agent_url) + 400]
        assert "reuse_page" not in _seg


def test_chatgpt_force_new_chat_functional():
    class FakePage:
        def __init__(self, url, click_ok=True, url_after="https://chatgpt.com/"):
            self.url = url
            self._click_ok = click_ok
            self._url_after = url_after

        async def evaluate(self, _js):
            if self._click_ok:
                self.url = self._url_after
            return self._click_ok

    async def _run(page):
        return await research._chatgpt_force_new_chat(page, "2A")

    # Happy path: /c/<id> conversation → New-chat click → fresh composer.
    assert asyncio.run(_run(FakePage("https://chatgpt.com/c/abc123"))) is True
    # Already fresh (P1 skipped upstream check let it through) → True, no click.
    assert asyncio.run(_run(FakePage("https://chatgpt.com/"))) is True
    # Not a ChatGPT tab at all → False (caller opens a fresh tab).
    assert asyncio.run(_run(FakePage("https://claude.ai/new"))) is False
    # Click found nothing → False (caller falls back to same-tab goto).
    assert asyncio.run(_run(FakePage("https://chatgpt.com/c/abc", click_ok=False))) is False
    # Clicked but the SPA never left the conversation → False.
    assert asyncio.run(_run(FakePage(
        "https://chatgpt.com/c/abc", url_after="https://chatgpt.com/c/abc"))) is False


# ── 3. HV-trim: Cloudflare-aware clearance cascade ──────────────────────────

def test_hv_cascade_skips_score_raising_tiers_for_cloudflare():
    # 2026-07-06 hands-off directive: Cloudflare gets NO interaction at all —
    # DOM, CUA, Vision, navigation, fresh tab. Detection reads only; then the
    # user alert (Skip-only) with the passive auto-resume poll.
    src = inspect.getsource(research.wait_for_verification_clearance)
    assert "_is_cloudflare" in src
    # Tier 0 (the former "one allowed" Playwright click) skipped for Cloudflare.
    assert "hands-off policy: no DOM click" in src
    # Tier 1 (CUA 3-iter click pass) skipped for Cloudflare.
    assert "skipping the CUA click pass" in src
    # Tier 2 (cooldown + about:blank/reload = two cold navigations) skipped.
    assert "no cooldown/reload; straight to the user alert" in src
    # Tier 3 (post-cooldown CUA 5-iter re-click) skipped for Cloudflare.
    assert "no re-click; settled probe decides" in src
    # Tier 4 (kill-tab = one more cold nav) skipped for Cloudflare.
    assert "skipping kill-tab" in src


def test_hv_cascade_keeps_full_chain_for_non_cloudflare():
    src = inspect.getsource(research.wait_for_verification_clearance)
    # Non-Cloudflare challenges keep every tier: the in-place CUA click…
    assert "max_iterations=3" in src
    # …the post-cooldown 5-iter retry…
    assert "max_iterations=5" in src
    # …and the kill-tab fresh-tab tier.
    assert "browser.new_tab(original_url)" in src
    # The decay-based cooldown+reload stays for non-Cloudflare challenges
    # (2026-07-06 hands-off directive removed it for Cloudflare — a reload
    # is a cold navigation feeding the score).
    assert "asyncio.sleep(180)" in src


# ── functional cascade harness (review 2026-07-06: the string pins above are
# branch-polarity-blind — an inverted `if _is_cloudflare()` would keep every
# literal present while regressing the behavior; these tests execute the real
# cascade with fakes and count the score-raising actions) ────────────────────

class _FakeLocator:
    @property
    def first(self):
        return self

    async def count(self):
        return 0

    async def is_visible(self):
        return False

    async def click(self, timeout=None):
        pass


class _FakeHvPage:
    def __init__(self, counters):
        self.url = "https://chatgpt.com/"
        self._c = counters

    def locator(self, sel):
        return _FakeLocator()

    def is_closed(self):
        return False

    async def goto(self, *a, **k):
        self._c["goto"] += 1

    async def close(self):
        self._c["closed"] += 1

    async def evaluate(self, js):
        return False


class _FakeHvBrowser:
    def __init__(self, counters):
        self._c = counters
        self.page = None

    async def switch_to_page(self, p):
        pass

    async def new_tab(self, url):
        self._c["new_tab"] += 1
        return _FakeHvPage(self._c)


class _FakeControls:
    def __init__(self):
        self.hv_blocked = {}
        self.skipped_agents = set()
        self.pause_target_agent = ""

    def is_stop(self):
        return True  # tier-5 loop exits on its first iteration

    def is_pause(self):
        return True

    def request_pause(self, reason=""):
        pass

    def request_resume(self):
        pass


def _run_cascade(monkeypatch, *, reasons, preserve_tab=False):
    """Execute the REAL wait_for_verification_clearance with fakes. `reasons`
    feeds detect_human_verification: first call pops the head, later calls
    repeat the tail — always blocked, so the cascade walks every tier it is
    WILLING to run and ends at tier-5 (which exits immediately via is_stop).
    Returns the action counters."""
    counters = {"agent_loop": 0, "closed": 0, "new_tab": 0, "goto": 0, "hv_click": 0}
    seq = list(reasons)

    async def fake_detect(page, platform, label):
        r = seq.pop(0) if len(seq) > 1 else seq[0]
        return True, r

    async def fake_agent_loop(*a, **k):
        counters["agent_loop"] += 1
        return {"text": "blocked"}

    async def fake_hv_click(page, label):
        counters["hv_click"] += 1
        return False  # never clears — the cascade keeps walking

    async def _nosleep(_s):
        return None

    monkeypatch.setattr(research, "detect_human_verification", fake_detect)
    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)
    monkeypatch.setattr(research, "_playwright_hv_click", fake_hv_click)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_persist_pending_decision", lambda *a, **k: None)
    monkeypatch.setattr(research, "_controls", _FakeControls())
    monkeypatch.setattr(asyncio, "sleep", _nosleep)

    browser = _FakeHvBrowser(counters)
    page = _FakeHvPage(counters)
    cleared = asyncio.run(research.wait_for_verification_clearance(
        browser, object(), page, "ChatGPT", "2A",
        max_wait_loops=1, initial_reason="", preserve_tab=preserve_tab))
    assert cleared is False  # never clears in this harness — walks all tiers
    return counters


def test_functional_cloudflare_runs_zero_interactions(monkeypatch):
    # 2026-07-06 hands-off directive: a Cloudflare wall must produce ZERO
    # touches of ANY kind — no DOM click, no CUA pass, no navigation
    # (cooldown/reload), no tab close, no fresh tab. Detection reads only,
    # then the Skip-only user alert. This is the polarity pin: inverting
    # any `if _is_cloudflare()` flips these counters.
    c = _run_cascade(monkeypatch, reasons=["Cloudflare"])
    assert c["hv_click"] == 0     # tier-0 DOM click never fires
    assert c["agent_loop"] == 0   # no CUA pass, ever
    assert c["goto"] == 0         # no about:blank / reload navigation
    assert c["closed"] == 0
    assert c["new_tab"] == 0


def test_functional_non_cloudflare_keeps_full_cascade(monkeypatch):
    # A reCAPTCHA wall keeps its working tiers: the DOM click, both CUA
    # passes, the cooldown/reload navigations, and the kill-tab.
    c = _run_cascade(monkeypatch, reasons=["reCAPTCHA"])
    assert c["hv_click"] == 1     # tier-0 Playwright click
    assert c["agent_loop"] == 2   # 3-iter pass + post-cooldown 5-iter pass
    assert c["goto"] == 2         # about:blank + original-URL reload
    assert c["closed"] == 1       # kill-tab closed the page…
    assert c["new_tab"] == 1      # …and opened a replacement


def test_functional_cloudflare_verdict_is_sticky(monkeypatch):
    # Review MAJOR (#896 re-issue gap): the detector can relabel a REAL
    # Cloudflare wall "Claude human verification" mid-cascade. The verdict
    # must LATCH — a later gap-landing probe can't re-arm the skipped tiers.
    # Feed: top probe says Cloudflare, every later probe says the generic
    # platform label.
    c = _run_cascade(monkeypatch, reasons=["Cloudflare", "Claude human verification"])
    assert c["hv_click"] == 0
    assert c["agent_loop"] == 0
    assert c["goto"] == 0
    assert c["closed"] == 0
    assert c["new_tab"] == 0


def test_functional_preserve_tab_blocks_kill_tab(monkeypatch):
    # Warm-tab reuse: even a NON-Cloudflare wall must not kill a tab the
    # caller marked preserve_tab (the replacement page never reaches the
    # caller — it would be stranded on a closed handle).
    c = _run_cascade(monkeypatch, reasons=["reCAPTCHA"], preserve_tab=True)
    assert c["agent_loop"] == 2   # CUA tiers still run — only the close is off
    assert c["closed"] == 0
    assert c["new_tab"] == 0


def test_check_hv_gate_no_second_cascade_pass_for_cloudflare():
    src = inspect.getsource(research.check_hv_gate)
    assert "not re-running the clearance chain" in src, (
        "check_hv_gate must not re-run the full clearance cascade for a "
        "Cloudflare wall — a second pass is more cold navigations against a "
        "profile+IP-scoped attestation and snowballs into the next run."
    )
    # The silent exception-retry for non-Cloudflare infra noise stays (#705).
    assert "range(2)" in src


def test_hv_trim_is_challenge_scoped_not_platform_scoped():
    """User rule (2026-07-06): ALL HV is dealt with carefully — every platform,
    every phase. The trim therefore lives in the ONE shared cascade and keys on
    the CHALLENGE TYPE (the probe-refreshed `reason`), never on platform/phase:
    P1's ChatGPT gate, P2's Layer-0 + post-setup probes (ChatGPT/Claude/Gemini),
    and P3's NotebookLM gates (upload + audio) all route here. A regression that
    special-cases the trim to one platform re-opens the score snowball on the
    others."""
    src = inspect.getsource(research.wait_for_verification_clearance)
    # The gate reads the challenge verdict, not the platform.
    assert '"cloudflare" in (reason or "").lower()' in src
    # _is_cloudflare's decision logic takes no platform input (the enclosing
    # function's `platform` param is for labels/events only).
    _body = src[src.index("def _is_cloudflare"):]
    _body = _body[_body.index("\n"):_body.index("def ", 4)]  # body only, up to the next def
    assert "platform" not in _body.replace("profile+IP", "")
    # Every phase's HV entry point funnels into this one cascade — P1 + P3 via
    # check_hv_gate, P2 via start_agent_no_gemini_wait's two probes.
    assert "wait_for_verification_clearance" in inspect.getsource(research.check_hv_gate)
    _p2_src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert _p2_src.count("wait_for_verification_clearance(") == 2
    _p1_src = inspect.getsource(research.run_phase1)
    assert "check_hv_gate" in _p1_src
    assert "check_hv_gate" in inspect.getsource(research.run_phase3_upload)
    assert "check_hv_gate" in inspect.getsource(research.run_phase3_audio)
