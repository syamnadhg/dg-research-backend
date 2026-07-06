"""Guards for the --login / pair-Stage-4 real-Chrome profile flow.

Two bugs these lock:
1. macOS profile mismatch — Phase 1 (plain-Chrome sign-in) launched the Chrome
   BINARY directly; on macOS the app singleton broker forwards the URLs to the
   user's ALREADY-RUNNING personal Chrome (default profile) and ignores
   --user-data-dir, so the sign-in never lands in the dedicated profile that
   Phase 2 (patchright) + research reopen. Fix: `open -na <app> --args …` on
   Darwin forces a separate instance bound to the dedicated profile; the graceful
   close SIGTERMs the real Chrome (the Popen handle is the `open` launcher).
2. --login only did the single existing profile — no pair-style "add another
   browser profile?" loop. Fix: run_login_flow(allow_add=True), used by --login.
"""
import asyncio
import inspect

import research


def _svc_keys():
    return [k for _n, _u, k in research._LOGIN_SERVICES]


def _one_profile(monkeypatch, *, probe_status, signed_in, answer, ask_reopen,
                 verify_mode="skip"):
    """Drive _login_one_profile with a stubbed pre-probe/skip-probe + seed spy +
    canned input. Returns (status, results, seeded_calls)."""
    seeded = []

    async def _fake_seed(*a, **k):
        seeded.append(a)
        return True

    async def _fake_probe(profile_dir, *, security_check, results):
        if probe_status == "ok":
            for k in _svc_keys():
                results[k] = signed_in
        return probe_status

    monkeypatch.setattr(research, "_seed_login_plain_chrome", _fake_seed)
    monkeypatch.setattr(research, "_probe_profile_logins", _fake_probe)
    monkeypatch.setattr("builtins.input", lambda *a, **k: answer)
    results = {}
    status = asyncio.run(research._login_one_profile(
        "prof", None, label="profile", results=results,
        emit_row=lambda *a, **k: None, verify_mode=verify_mode,
        ask_reopen_if_signed_in=ask_reopen))
    return status, results, seeded


def test_seed_uses_open_na_on_macos():
    # macOS MUST use `open -na <app> --args` to bypass the singleton broker so the
    # sign-in lands in the dedicated --user-data-dir (not the user's personal Chrome).
    src = inspect.getsource(research._seed_login_plain_chrome)
    assert '"Darwin"' in src, "seed must branch on macOS (Darwin) for the launch"
    assert '"open"' in src and '"-na"' in src and '"--args"' in src, (
        "on macOS the plain-Chrome launch must use `open -na <app> --args` to force "
        "a NEW instance bound to the dedicated profile (a direct binary launch is "
        "routed to the user's running Chrome and ignores --user-data-dir)."
    )
    # Windows/Linux keep the direct-binary launch (honors --user-data-dir).
    assert "--user-data-dir=" in src


def test_graceful_close_is_profile_aware_on_macos():
    # On macOS `proc` is the `open` launcher (already exited), so SIGTERM-ing it is
    # a no-op — the close must SIGTERM the real Chrome bound to the profile so it
    # flushes cookies before phase 2 reopens the profile.
    src = inspect.getsource(research._close_chrome_gracefully)
    assert '"Darwin"' in src, "close must have a macOS branch"
    assert "graceful=True" in src, (
        "macOS close must SIGTERM the profile's Chrome via "
        "_kill_chrome_for_profile(profile_dir, graceful=True) (flush before exit)."
    )
    # The graceful mode must actually SIGTERM (terminate), not SIGKILL, so cookies flush.
    ksrc = inspect.getsource(research._kill_chrome_for_profile)
    assert "graceful" in ksrc and "terminate()" in ksrc, (
        "_kill_chrome_for_profile must support graceful=True → proc.terminate() (SIGTERM)."
    )


def test_login_offers_multi_profile_loop_like_pair():
    # --login must let the user add more worker profiles (pair-style), not stop
    # after the single existing one.
    rl = inspect.getsource(research.run_login)
    assert "allow_add=True" in rl, "run_login must call run_login_flow(allow_add=True)"
    flow = inspect.getsource(research.run_login_flow)
    assert "allow_add" in flow, "run_login_flow must accept allow_add"
    assert "Add another browser profile" in flow, (
        "the add-loop must prompt to add another browser profile (like pair Stage 4)."
    )
    assert "save_worker_count" in flow, (
        "each fully-verified added profile must bump workerCount via save_worker_count."
    )


def test_research_uses_dedicated_per_worker_profile():
    # The whole design: research reuses the SAME dedicated profile the user signed
    # into — Browser(_profile_dir(WORKER_ID)) — so verify + research see the logins.
    mod = inspect.getsource(research)
    assert "Browser(_profile_dir(WORKER_ID)" in mod, (
        "research must run in the per-worker dedicated profile _profile_dir(WORKER_ID)."
    )


# ── --login pre-probe: don't force a re-login on an already-signed-in profile ──

def test_signed_in_default_declines_and_never_reseeds(monkeypatch):
    # THE trust fix: a signed-in profile + Enter (default N) must NOT re-open
    # Chrome — the session is left completely untouched.
    status, results, seeded = _one_profile(
        monkeypatch, probe_status="ok", signed_in=True, answer="", ask_reopen=True)
    assert status == "ok"
    assert seeded == [], "signed-in profile must NOT be re-seeded on the default decline"
    assert all(results[k] for k in _svc_keys()), "probed sessions recorded truthfully"


def test_signed_in_yes_reopens_for_human_verification(monkeypatch):
    # The user can still re-open a signed-in profile (e.g. to do a Human
    # Verification) by answering y.
    status, _results, seeded = _one_profile(
        monkeypatch, probe_status="ok", signed_in=True, answer="y", ask_reopen=True)
    assert status == "ok"
    assert seeded, "explicit 'y' must re-open Chrome"


def test_signed_out_default_opens_to_sign_in(monkeypatch):
    # A signed-out profile defaults to opening Chrome (default Y) so the user signs in.
    status, _results, seeded = _one_profile(
        monkeypatch, probe_status="ok", signed_in=False, answer="", ask_reopen=True)
    assert status == "ok"
    assert seeded, "signed-out profile defaults to opening Chrome"


def test_signed_out_decline_skips_without_reseed(monkeypatch):
    # Declining a signed-out profile just leaves it as-is (never cleaned).
    status, _results, seeded = _one_profile(
        monkeypatch, probe_status="ok", signed_in=False, answer="n", ask_reopen=True)
    assert status == "ok"
    assert seeded == []


def test_probe_failed_falls_through_to_seed(monkeypatch):
    # If the profile can't be read (e.g. locked by a live Chrome) we fall through
    # to seeding — today's behavior — rather than a false skip. No prompt shown.
    def _no_prompt(*a, **k):
        raise AssertionError("no per-profile prompt when the probe failed")
    monkeypatch.setattr("builtins.input", _no_prompt)
    seeded = []

    async def _fake_seed(*a, **k):
        seeded.append(a)
        return True

    async def _fake_probe(profile_dir, *, security_check, results):
        return "probe_failed"

    monkeypatch.setattr(research, "_seed_login_plain_chrome", _fake_seed)
    monkeypatch.setattr(research, "_probe_profile_logins", _fake_probe)
    results = {}
    status = asyncio.run(research._login_one_profile(
        "prof", None, label="profile", results=results,
        emit_row=lambda *a, **k: None, verify_mode="skip",
        ask_reopen_if_signed_in=True))
    assert status == "ok"
    assert seeded, "probe_failed must fall through to seeding"
    # fail-open: skip-branch setdefaults every service True (human just signed in)
    assert all(results[k] for k in _svc_keys())


def test_pre_probe_refused_returns_without_seeding(monkeypatch):
    # A security_check refusal during the pre-probe must abort before any seed.
    status, _results, seeded = _one_profile(
        monkeypatch, probe_status="refused", signed_in=False, answer="",
        ask_reopen=True)
    assert status == "refused"
    assert seeded == []


def test_pair_path_no_preprobe_seeds_directly(monkeypatch):
    # Regression: with ask_reopen_if_signed_in False (pair Step 4) the pre-probe
    # is NOT run — pair seeds directly, exactly as before. Only the skip-branch
    # probe runs (once).
    probe_calls = {"n": 0}
    seeded = []

    async def _fake_seed(*a, **k):
        seeded.append(a)
        return True

    async def _fake_probe(profile_dir, *, security_check, results):
        probe_calls["n"] += 1
        for k in _svc_keys():
            results[k] = True
        return "ok"

    monkeypatch.setattr(research, "_seed_login_plain_chrome", _fake_seed)
    monkeypatch.setattr(research, "_probe_profile_logins", _fake_probe)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    results = {}
    status = asyncio.run(research._login_one_profile(
        "prof", None, label="profile", results=results,
        emit_row=lambda *a, **k: None, verify_mode="skip"))  # ask_reopen defaults False
    assert status == "ok"
    assert seeded, "pair path must seed directly (no pre-probe skip)"
    assert probe_calls["n"] == 1, "only the skip-branch probe runs when pre-probe is off"


def test_walk_pre_probes_addloop_does_not():
    # Wiring guard: the existing-profile walk pre-probes (ask_reopen=True); the
    # add-loop (new profiles) does not (it has its own 'Add another?' gate).
    src = inspect.getsource(research.run_login_flow)
    assert "ask_reopen=True" in src, "the existing-profile walk must pass ask_reopen=True"
    assert "ask_reopen_if_signed_in=ask_reopen" in src, (
        "_do_profile must thread ask_reopen into _login_one_profile")


# ── _probe_profile_logins: read-only, never kills/cleans the profile ──

def test_probe_reads_cookies_without_seeding(monkeypatch):
    started = {"start": 0, "close": 0}

    class _FakeCtx:
        async def cookies(self):
            return []

    class _FakeBrowser:
        def __init__(self, *a, **k):
            self.context = _FakeCtx()

        async def start(self):
            started["start"] += 1

        async def close(self):
            started["close"] += 1

    monkeypatch.setattr(research, "Browser", _FakeBrowser)

    async def _present(browser, key):
        return key == _svc_keys()[0]  # only the first service is signed in

    monkeypatch.setattr(research, "_platform_auth_cookie_present", _present)
    results = {}
    status = asyncio.run(research._probe_profile_logins(
        "prof", security_check=None, results=results))
    assert status == "ok"
    assert started == {"start": 1, "close": 1}, "opens + closes exactly once, no kill"
    assert results[_svc_keys()[0]] is True
    assert all(results[k] is False for k in _svc_keys()[1:])


def test_probe_reports_failure_when_context_unavailable(monkeypatch):
    class _FakeBrowser:
        def __init__(self, *a, **k):
            self.context = None

        async def start(self):
            raise RuntimeError("profile locked")

        async def close(self):
            pass

    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    results = {}
    status = asyncio.run(research._probe_profile_logins(
        "prof", security_check=None, results=results))
    assert status == "probe_failed"
