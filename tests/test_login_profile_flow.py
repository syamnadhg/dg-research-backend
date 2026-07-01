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
import inspect

import research


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
