# Mac login / pairing profile bug — getting‑started for Claude Code

> Hand this file to a fresh Claude Code session **on the Mac**. It is self‑contained
> (the Mac session has its own memory — don't rely on any external notes). Work from
> the real Mac state and logs. **Instrument first, root‑cause, then fix — do not guess.**

---

## 0. Getting started (bootstrap)

1. **Get the repo (from scratch — nothing is set up on this Mac yet):** authenticate git
   first (`gh auth login`, or add an SSH key to GitHub — the fork is private), then clone the
   personal fork and enter it:
   ```
   git clone https://github.com/syamnadhg/dg-research-backend.git
   cd dg-research-backend
   ```
   `research.py` is at the repo root. Branch is `master` (recent P1/login fixes live there —
   don't debug stale code). *Already cloned?* `git pull origin master` instead.
2. **Python env**: use the repo's `uv`/venv (see `pyproject.toml` / README).
3. **Credentials — there is NO GCP key file to transfer:**
   - **Firebase/Firestore** access = an OS‑keystore refresh token minted by pairing
     (`init_firebase()` → *"No Admin SDK; no firebase-service-account.json on disk."*).
     On macOS the keystore is the **Keychain**. You get it by running `--pair` on this
     Mac (below) — nothing to copy.
   - **API keys** (Anthropic for CUA login‑verify; Gemini optional). Resolution order:
     Firestore `apiKeys` (set on the web‑app **Account page**) → `.dg-supervisor.env`
     → shell env. So either the keys are already set on the Account page (they flow in
     after pairing), OR create `.dg-supervisor.env` next to `research.py`:
     ```
     cp scripts/dg-supervisor.env.example .dg-supervisor.env
     # then fill in ANTHROPIC_API_KEY=…  (GEMINI_API_KEY=… optional)
     ```
     `.dg-supervisor.env` is **gitignored** — never commit secrets.
4. **Commit signing (optional)**: signing is configured *repo-local* on the Windows clone,
   so it does NOT travel with a fresh clone/pull — Mac commits are **unsigned by default and
   that's fine** (personal fork). If the user wants signed/Verified commits they'll set it up
   themselves (SSH signing via `gpg.format ssh`, or import the GPG key
   `1CABFF166C1FF8334EC9D83934FA38BECE5387F2` = "Sammy Guli <sammy.guli@distributedglobal.com>").
   **Never bypass or fake signing, and never commit a private key / `.asc` file.**
5. **CLI reference**: `python research.py --help`. Flags you'll use:
   - `python research.py --pair` — first‑time setup incl. **Stage 4** (profile creation).
   - `python research.py --login` — re‑seed logins into existing profiles.
   - `python research.py --worker-id N` — run as worker N (profile = `_profile_dir(N)`).

---

## 1. The bug (reproduce this — it's the ground truth)

> "When I pair and make profiles (log in), or run `--login` and log into profiles, LATER
> the profile the Mac opens for **runs** and for **checking** (verify) is a *different*
> profile. Either the profiles aren't being saved, or the saved profile isn't the one
> opened at run time."

Net effect on macOS: the logged‑in session from pair/login is **not** the session the
research run (and the login‑verify step) uses — so runs behave as signed‑out. **This works
on Windows; it's macOS‑specific.** Focus on **pair Stage 4** (profile creation) and the
shared login flow.

---

## 2. Architecture (take as given — verify at runtime, don't re‑derive)

- **Profile dirs** under `~/.super-research/`:
  - worker 1 → `~/.super-research/browser-profile/` (constant `PROFILE_DIR`)
  - worker N → `~/.super-research/browser-profile-{N}/`
  - resolved by **`_profile_dir(n)`**.
- **Login / seed** (human signs in): **`run_login_flow(profile_indices, …)`** →
  **`_login_one_profile`** → **`_seed_login_plain_chrome(profile_dir, …)`**. Shared by
  `--login` AND pair Stage 4 (**`cmd_pair_v2`**). It launches the user's **real Chrome** on
  `--user-data-dir=<profile_dir>`. On macOS it uses
  `open -na "<Chrome>.app" --args --user-data-dir=…` **specifically because** a direct
  binary launch is intercepted by the macOS app‑singleton broker (routes to the running
  personal Chrome and **ignores `--user-data-dir`**). **Verify this `open -na` path really
  binds to the dedicated dir — suspect #1.**
- **Verify / "checking"**: **`_verify_platform_logins(…)`** opens tabs via patchright on the
  signed‑in profile.
- **Runs**: **`Browser(_profile_dir(WORKER_ID))`**; `Browser.__init__` uses patchright
  `chromium.launch_persistent_context(user_data_dir=self.profile_dir, channel="chrome", …)`.
  `WORKER_ID` = `--worker-id` (default 1).
- **Tests to read + extend**: `tests/test_login_profile_flow.py`,
  `tests/test_browser_profile_match.py`, `tests/test_multiworker_rehydration_728.py`.
- **Logs**: `~/.super-research/logs/backend*.log`.

---

## 3. Prime suspects (macOS) — confirm/refute each with evidence

**A. Seed lands in the wrong profile.** `open -na <app> --args --user-data-dir=X` may STILL
be delegated to the running personal Chrome (broker) → cookies never land in X. **Verify:**
right after sign‑in + Enter, check X's cookie store
(`~/.super-research/browser-profile/Default/Cookies` or `…/Default/Network/Cookies`) —
size / mtime / row count. Empty/untouched ⇒ the seed went to the personal profile.

**B. Path / HOME mismatch between login and run (strong candidate).** Pair/`--login` run in
your Terminal (`HOME=/Users/<you>`). If the actual **run/worker** is started by the
autostart / launchd / agent bridge with a different `HOME` (or a sandbox container),
`Path.home()` resolves a **different** `~/.super-research/browser-profile/` (empty). **Log the
fully‑resolved absolute `profile_dir` AND `os.environ["HOME"]`/`Path.home()` at EVERY step**:
pair Stage 4, login seed, verify, and the run's `Browser.__init__`. Diff them.

**C. worker‑id mismatch.** Login seeds profile 1 but the run launches `--worker-id 2`
(→ `browser-profile-2/`, empty), or vice‑versa. Log `WORKER_ID` + resolved dir at run start.

**D. (Lower likelihood.)** Both seed and run use Chrome `channel="chrome"`, so the macOS
Keychain "Chrome Safe Storage" cookie‑encryption key should match. But **confirm** the run
actually gets `channel="chrome"` (not bundled Chromium) — if it falls back to Chromium,
Chrome‑written cookies won't decrypt and it'll look signed‑out despite the right dir.

---

## 4. Method

1. **Reproduce cleanly**: `python research.py --pair` (do Stage 4, sign in), then trigger a
   real run + the verify path the way a normal run does. Capture backend logs across phases.
2. **Instrument BEFORE fixing** (repo convention: every fix also ADDS the logs that would
   root‑cause the area from `backend.log` alone). Log resolved abspaths, `HOME`, `WORKER_ID`,
   the exact Chrome invocation, and cookie‑DB presence at each step.
3. **Identify the ONE root cause** (A/B/C/D or otherwise) and state it with the proving log lines.
4. **Fix it properly** — keep the macOS `open -na` intent; if login vs run pick different
   dirs, make the profile‑dir resolution **single‑sourced and identical** across
   pair / login / verify / run.
5. **Prove the fix**: re‑run the full reproduce — the run/verify must open the **same** profile
   the login seeded, signed‑in.

---

## 5. Conventions (match the repo)

- **Push to personal `origin` master directly** once the fix is tested + reviewed — you do
  NOT need to wait for the user (auto-push is fine on the personal fork). Small, focused
  commits; end messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  (Never push to the `org` remote.)
- Tests: add/extend under `tests/`; run `python -m pytest tests/ -q` (scope to `tests/` —
  root pytest chokes on `agent/tests`). Keep `ruff check research.py` delta at 0 (F405 on
  star‑imported `PROMPT_*` / config names is the pre‑existing benign baseline — don't touch).
- **Adversarially review** the fix before pushing (spawn skeptic reviewers to refute it, then
  verify findings against the real code).
- Verify behavior on the **actual Mac** — never confirm from code alone. Report failures
  honestly with the log output.

---

## 6. Deliverable

A crisp root‑cause writeup (with the proving log lines), the fix, a regression test, and a
clean reproduce showing **login‑profile == run‑profile == verify‑profile**. Once it's tested
+ reviewed, **commit and push to personal `origin master` directly** (no need to wait for the
user), then post the root‑cause + fix summary.

---

*(This doc can be deleted from the repo once the bug is fixed.)*
