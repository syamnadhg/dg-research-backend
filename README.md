# Super Research — Backend Pipeline

Automates multi-agent deep research across 6 platforms. Tiered automation: Playwright/DOM (primary) → CUA (Anthropic Computer Use, current fallback). Claude Sonnet vision is wired in as tier-2 in **shadow mode today** — it observes CUA's actions and logs agreement; per-hotspot promotion to actively-driving tier-2 is coming, with CUA kept as a tier-3 safety net even after promotion.

> **Jira:** [DGOPS-6933](https://distributedglobal.atlassian.net/browse/DGOPS-6933)
> **Repo (this one):** github.com/dg-eng/super-research-backend
>
> No admin keys, no JSON files to copy around. `--pair` mints an 8-char
> code in the terminal; you paste it into the web app once. Per-device
> Firebase refresh tokens live in your OS keystore — Windows DPAPI,
> macOS Keychain, Linux libsecret.

## Google accounts: use personal accounts, not workspace ones

The web app side accepts any Google sign-in. **The backend is different — use a personal Gmail/Google account here, not a Google Workspace one.** Phase 0 logs the backend's Chrome session into NotebookLM, ChatGPT, Claude, and Gemini on your behalf, and Workspace-managed accounts hit the admin-approval gate on each of those services. Personal accounts skip that prompt and let the pipeline run unattended. If you've already paired with a Workspace account and Phase 0 stalls on a "this app needs admin approval" screen, the fastest fix is `python research.py --unpair` then re-pair with a personal account.

Pairing-side data scope: this backend pairs to a single web-app account at a time via `--pair`. The ResearchToken minted during pairing is bound to that uid; the backend rejects start requests whose `uid` doesn't match the token's `linkedUid`, so even if the token leaks it can't be used to drive runs against another user's research collection.

## Platform support

| Platform | Server | `--pair` | `--resurrect` / `--retire` | `--unpair` |
|----------|--------|----------|----------------------------|------------|
| Windows 10 / 11 | Full | Full | Full (Scheduled Task) | Full |
| macOS | Full | Full | Full — launchd user agent | Full |
| Linux desktop (X11/Wayland) | Full | Full | Full — systemd-user unit | Full |
| Linux headless / WSL / Docker | **Unsupported** — Chrome needs a real display + user session for CAPTCHA / 2FA / login refresh |

The supervisor (`--resurrect` / `--retire`) is cross-platform first-class on all three desktop OSes: Scheduled Task on Windows, launchd user agent on macOS (`~/Library/LaunchAgents/com.dgresearch.supervisor.plist`), systemd-user unit on Linux (`~/.config/systemd/user/dgresearch-supervisor.service`). All three share the same `--env-file` config flow (see [`.dg-supervisor.env`](#step-2-environment) below). Linux also requires `sudo loginctl enable-linger $USER` so the user-systemd manager survives logout; `--resurrect` probes and surfaces a WARN if Linger=no.

## Before you start (prerequisites checklist)

- **Python 3.11+** (`python --version`).
- **Real Google Chrome** installed (not just Chromium — patchright launches with `channel="chrome"`). Chrome itself is an OS-level prerequisite; the patchright Chrome wrapper, though, is **auto-fetched** for you — `--pair` and `--doctor` now run `patchright install chrome` automatically, so you don't have to do that step by hand.
- **Anthropic API key** with browser-automation access (`ANTHROPIC_API_KEY`; see Step 2).
- **Super Research web app account** — sign in at the deployment URL the dev shares with you (Google sign-in). You'll paste the 8-char pair code into Account → Add Device during `--pair` Stage 1.
- **Paid Pro tiers on ChatGPT, Claude, and Gemini** — required for the depth Phases 1–2 were tuned against:
  - **ChatGPT Pro** ($200/mo per seat) — Phase 1 brief uses Pro + Extended Thinking.
  - **Claude Pro** ($20/mo per seat) — Phase 2 Claude agent uses Opus 4.8 + Max effort + Adaptive Thinking + Research tool (Free tiers don't expose Opus or Research).
  - **Gemini Advanced** ($20/mo per seat, via Google One AI Premium) — Phase 2 Gemini agent uses 2.5 Pro / Deep Think + Deep Research.
  - The pipeline will *run* end-to-end on Free tiers, but Deep Research depth, image quality, and turn limits are far lower. **A non-Pro account is flagged with a `[Continue with Free] [Retry]` alert** — via the in-phase tier tells by default (ChatGPT's P1 Pro selector, Gemini's P2 DOM read), or Phase 0's vision check when the opt-in "Verify sign-ins before each run" Setting is on — sign in with a Pro account in the same browser, then click Retry. Opting into Free for one platform suppresses the prompt for the rest of the run, so verify Pro is active in each platform's account/billing page before pairing to avoid surprises. (Stop is always reachable from the chat-box during a paused pipeline — no separate Stop button on the alert.)
- *(Optional)* Gemini API key for the narrator's Flash fallback. (Phase 4 — YouTube upload — and Phase 5 — Google Doc creation + email — both run entirely in the frontend; no BE-side Resend / YouTube / Docs setup needed.)

## Quick Start

### Option A — Install as a command (recommended)

The backend installs as a `superresearch` console command via [pipx](https://pipx.pypa.io). No checkout to manage, and it runs from **any directory** — data + config live under `~/.super-research/` and `.dg-supervisor.env`.

**One command** — also at **[superresearch.io/install](https://superresearch.io/install)** (ensures Python 3.11+ & pipx — auto-installs pipx if missing — then installs `superresearch`):

```bash
# Windows (PowerShell)
irm https://superresearch.io/install.ps1 | iex

# macOS / Linux
curl -fsSL https://superresearch.io/install.sh | sh
```

Or, if you already have pipx:

```bash
# 1. Install
pipx install superresearch

# 2. Pair (one-time: mints an 8-char pair code, prompts API keys, runs browser logins)
superresearch --pair      # auto-fetches the patchright Chrome wrapper for you

# 3. Start the server (keep it running)
superresearch --serve

# One-shot CLI run (no pairing / Firebase round-trip — see § CLI Mode)
superresearch "your topic"
```

> **`superresearch <flags>` is a pure drop-in for `python research.py <flags>`** — identical flags, identical branded UI, and the same `--pair` / `--login` / `--update` / `--serve` / `--resurrect` / `--retire` / `--unpair` / `--doctor` / `--commands` / `agent` verbs. Help is invocation-aware: it shows `superresearch …` when launched from the installed command, `python research.py …` from a source checkout. So every `python research.py …` example below works verbatim as `superresearch …` on an installed build.
>
> **`--update`** updates an installed build and is **idempotent** — it checks PyPI and only reinstalls the pipx package when the installed build is actually outdated, otherwise it says "already up to date" (no pointless reinstall). This is the CLI path for updating the backend; the app's Settings → About Check → Update is the remote equivalent (a source checkout updates with `git pull` instead).

### Option B — From source (developers)

```bash
# 1. Install
git clone https://github.com/dg-eng/super-research-backend.git
cd super-research-backend
pip install -r requirements.txt
python -m patchright install chrome    # downloads patchright's stealth Chrome wrapper

# 2. Pair (one-time: mints an 8-char pair code, prompts API keys, runs browser logins)
python research.py --pair

# 3. Start the server (keep it running)
python research.py --serve

# 3a. (Optional, recommended) Survive reboots + crashes (cross-platform).
python research.py --resurrect

# 3b. (Undo 3a) Disable On Startup — kills supervisor + serve, removes
#     the scheduled-task / launchd / systemd unit, syncs the Firestore flag.
#     Pairing stays.
python research.py --retire

# 3c. (Full disconnect) Clean teardown — deletes the device server-side
#     via /api/devices/unpair-self, wipes pairing + the OS keystore entry.
#     Tile disappears across every browser within a second.
python research.py --unpair
```

That's it. Three commands to a hands-off always-on backend — plus `--retire` to disable On Startup or `--unpair` to fully disconnect this PC.

> Run `python research.py --commands` anytime for a branded, use-case-grouped reference card of every CLI verb (Daily / Lifecycle / Advanced / Internal-Debug). Lighter-weight than `--help`.

> **Just want to smoke-test from the terminal first?** Skip pairing entirely and run `python research.py "your topic"` — see [§ CLI Mode](#cli-mode). No code, no Firebase round-trip, output lands in `queues/`.

> **Order of ops:**
> - Steps 1 (install) and 2's API-key prep can run in parallel.
> - You're **blocked** on a web-app account before `--pair` Stage 1 finishes (paste the 8-char code into Account → Add Device).

## Drive it from chat — Super Agent (Hermes / OpenClaw)

Run Super Research from a chat runtime instead of the terminal — every run still
shows up in the web app as a normal chat. It's just another `research.py`
command (no extra install — the two deps are already in `requirements.txt`):

```bash
python research.py agent connect      # install the skill into your runtime (auto-detects hermes/openclaw)
python research.py agent serve        # start the bridge that holds your account session (keep running)
# then, in chat:  /reload-skills once (the gateway caches its skill scan),
#                 then  /sr login  →  /sr research <topic>  →  /sr status
#                 (there's one /sr command — actions follow it; bare /sr = welcome/help)
```

> On an installed build, the same front door is `superresearch agent connect` (and the other `agent` verbs). The chat-runtime agent is a **separate package** — the installed `superresearch agent <verb>` delegates to `pipx run superresearch-agent <verb>`, which installs the `/sr` skill into Hermes/OpenClaw; a source checkout runs the in-tree agent instead.

The agent is **research-only** — it runs / tracks / cancels research on your
existing devices but can never add, remove, pair, or share them (that stays
owner-only in the web app). Full command list: `python research.py agent
--help`. How it works + the chat slash commands: **[`agent/README.md`](agent/README.md)**.

## Pairing model (no JSON keys to copy around)

The backend authenticates as a per-device **synthetic Firebase user**
whose long-lived refresh token lives in your OS keystore — Windows
DPAPI / macOS Keychain / Linux libsecret (with a `chmod 0600` file
fallback). No service-account JSON. No god-mode credentials shared
across devices.

The handshake at `--pair`:

1. BE mints a 256-bit `pollSecret` locally and POSTs `sha256(pollSecret)`
   to the FE Cloud Function `/api/devices/initiate-pair`. The function
   creates a synthetic Firebase Auth user and returns
   `{ deviceId, pairCode }` — an 8-char code from a confusion-resistant
   alphabet (digits 2-9 + uppercase A-Z minus I/L/O).
2. The terminal prints the code + a scannable QR. You open the web app
   → **Account → Add Device** → paste the code. The FE claim Cloud
   Function mints a customToken scoped to this device + you (with
   custom claims `ownerUid` + `deviceId`) and writes it to a subdoc
   keyed by `sha256(pollSecret)`. Sharers know the deviceId but not
   the secret hash, so the customToken is unreadable to them.
3. BE polls that subdoc (anonymous Firestore REST — `allow get: if true`
   on the keyed path), exchanges the customToken for a refresh+ID
   token pair via Firebase REST, saves the refresh token to the OS
   keystore.

From then on, every BE Firestore write goes through that refresh token
+ google-cloud-firestore. The refresh token rotates each refresh cycle
(~1h) and the keystore rotation slot guarantees a clean swap under
parallel-process contention.

**Shared devices.** Same 8-char code drives sharing — a second account
pastes the same code into Account → Add Device and the claim function
appends their uid to `sharedWith[]`. They can submit research that
runs on your PC but can't read your other data; per-device Firestore
rules enforce the boundary via the BE's custom claim.

**Reset Pair Code.** Settings → Manage devices → Reset rotates the
code, revokes the BE's refresh token, clears `sharedWith=[]`, and
emails you the new code with a 15-min TTL. The BE's recovery watcher
notices the revoke, polls the same pending subdoc, picks up the new
customToken once you enter the new code in the FE, and exits cleanly
so the supervisor respawns with a fresh keystore + listener
subscriptions. **No `--pair` on the PC needed** — the device is back
online within ~5s of you entering the new code. Miss the 15-min
window and you'll need to re-run `--pair` for a fresh device record.

What Reset does to **in-flight runs** (multi-worker safe): the FE
route writes a `hard_reset` command to `devices/{id}/commands/`
**before** revoking refresh tokens. Every worker subscribes to that
subcollection (research.py:27452) so all N workers process the
command independently — each touches `.stop` on its own active run
dir, flips its own active research doc to `cancelled`, and schedules
`os._exit(0)` so the daemon-loop respawns it clean. **No zombie
runs.** The route polls up to 5s for the BE to ack (delete the
command) before proceeding to revoke; if the BE is already wedged
the 30s stale-gate at research.py:2253 ensures a respawned BE won't
re-fire it.

What Reset does to **queued runs**: the FE route stamps
`expireAt: now+15min` + `cancelledReason: "device_pair_expired"` on
every user-tree research doc that points at this device (owner +
every sharer + every previously-revoked sharer, in `queued` /
`ongoing` / `running` / `paused` / `paused_pending_repair` state)
plus every `devices/{id}/queue/*` subdoc. Firestore TTL (configured
via `firestore.indexes.json` `fieldOverrides`) auto-deletes them at
the 15-min mark — sharer's research page clears the orphans
automatically via the existing real-time listener. The sharer sees
no Cancelled card to dismiss; rows just disappear.

**If you re-pair within 15 min**: the claim route's
awaiting-re-pair branch reads the snapshotted `preResetUids` field
from the device doc, clears the `expireAt` + `cancelledReason`
fields across every sharer's user-tree, and clears `expireAt` on
the queue subdocs. Queued sharer + owner runs resume seamlessly on
the post-respawn BE — sharer never sees a blip beyond the brief
"device offline" interval during the 15-min window.

**If you don't re-pair within 15 min**: device doc + all sharer
research docs + all queued runs vanish from every browser at the
15-min mark. To restore, run `python research.py --pair` on the PC.
Sharers will not regain access until you explicitly re-share with
them (post-Reset `sharedWith[]` is empty, even if you re-pair).

Partial-failure semantics: both the cross-tree expireAt set (Reset)
and the cross-tree clear (re-pair) wrap each user-tree batch in a
3-attempt retry with 250ms × attempt backoff. Persistent failures
surface as `[reset-pair-code] expireAt set FAILED after 3 attempts`
or `[claim] re-pair expireAt clear FAILED after 3 attempts` log
lines — single-RPC blips are absorbed.

What Reset does NOT touch: `~/.super-research/browser-profile*/`
directories (your Google/ChatGPT/Gemini/Claude logins survive),
`workerCount` in `research_config.json`, the supervisor (daemon-loop
keeps respawning workers on the same ports — `--retire` is the only
way to stop it), the OS keystore (the recovery watcher needs the
existing `pollSecret` from `research_config.json` to redeem the new
customToken).

## Setup Details

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
python -m patchright install chrome
```

Requires **Python 3.11+** and a working **real Google Chrome** install, plus `patchright>=1.61` and `playwright>=1.61` (floors bumped 2026-06-30 — both are pinned in `requirements.txt`). `research.py` launches via `patchright` (a stealth Playwright fork) with `channel="chrome"` — it uses your installed Chrome binary, NOT bundled Chromium, so anti-bot heuristics see a real browser fingerprint.

If Chrome itself isn't installed, install it first:
- **Windows:** [google.com/chrome](https://www.google.com/chrome/) → run the installer.
- **macOS:** `brew install --cask google-chrome` (or download from google.com/chrome).
- **Linux (Debian/Ubuntu):** `sudo apt-get install google-chrome-stable` (after adding Google's apt repo) or download the `.deb` from google.com/chrome.
- **Linux (Fedora/RHEL):** `sudo dnf install google-chrome-stable` (after adding the repo) or `.rpm` from google.com/chrome.

`python -m patchright install chrome` then downloads the stealth wrapper that drives that Chrome. Do this once on every machine.

`qrcode>=7.4` is already listed — the pair flow renders a scannable QR in your terminal.

### Step 2: Environment

The supervisor reads env vars from `.dg-supervisor.env` (created automatically on first `--resurrect` from `scripts/dg-supervisor.env.example`). Edit that file to set Vision/CUA config; no shell-rc / `setx` needed.

**API keys** — Anthropic powers the agents (CUA + Vision) and is **required** for browser automation. Gemini powers narration + acts as the Haiku fallback for title refinement, and is **optional** (narrator silently disables without it). Four ways to set either, **all platforms**:

- **(easiest — recommended)** **`--pair` Stage 3 auto-prompt.** At the end of pairing, `--pair` checks whether each key is already resolvable from any source; for missing keys it prompts with `[paste / S=skip]`, **verifies** the pasted key against the provider's API (5s cheap probe), and on success writes BE-local persistence + `os.environ` + busts the resolver cache. Persistence is per-machine: Windows User-scope env on Windows; `.dg-supervisor.env` upsert on macOS / Linux. Skip is first-class per key.
- **(equivalent — set later, or rotate, or sync across devices)** "Account → API Config" in the web app — writes `users/{uid}/settings/prefs.apiKeys.{anthropic,gemini}` in Firestore. Distinct surface from pair-time keys: pair never auto-fills these inputs, so anything you see there is something you typed there. Works on Windows, macOS, Linux. No restart required after rotating; backend re-reads on next call (60s cache).
- **(file-based, all platforms)** Uncomment `ANTHROPIC_API_KEY=sk-ant-...` and/or `GEMINI_API_KEY=AIza...` in `.dg-supervisor.env`. Loaded by `--env-file` at supervisor startup; survives reboots via the persistence supervisor. Good for un-paired backends or operators who prefer files. (On POSIX, `--pair` writes here too.)
- **(advanced / legacy)** Set in your shell rc (Mac/Linux) or via PowerShell `[System.Environment]::SetEnvironmentVariable(..., 'User')` (Windows user-scope). The canonical env-var names are `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` (matching the Anthropic SDK + Gemini API docs). Legacy aliases `CUA_API_KEY` and `GOOGLE_API_KEY` are auto-migrated on next startup and removed; new BE versions only read the canonical names. (On Windows, `--pair` writes here too.)

**Don't set the same key in multiple places with different values** — pick one. Priority chain: CLI `--api-key` → **FE Account-page Firestore key** → Windows user-scope env (where `--pair` persists on Windows) → `os.environ` (the `.dg-supervisor.env` file loads here on POSIX, including pair-time keys). FE-Account-page key wins, so a stale BE-local pair key won't override a freshly-set web-app key.

**Other config** (Vision tier, CUA model overrides, shadow log path) also lives in `.dg-supervisor.env`. See `scripts/dg-supervisor.env.example` for the documented template + key descriptions.

> P4 thumbnail generation lives on the FE: `web/src/lib/album-art.ts` calls Gemini image-gen from inside `/api/uploadYouTube` using the FE-side env key or the user's per-prefs key. BE never owned a thumbnail role post-2026-05-10.

**Phases 4 + 5 are FE-owned.** No BE setup needed for either. The frontend handles YouTube upload via `youtube.videos.insert` (Data API + OAuth refresh token, ffmpeg encode in Cloud Run) AND Google Doc creation via the Docs API AND email via Resend — see the FE README for that side's env vars (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`, `RESEND_API_KEY`, `NOTIFY_FROM_EMAIL`).

`BUG_REPORT_EMAIL` is optional — see the env-var table.

### Step 3: Run pair flow

```bash
python research.py --pair
```

The flow has **five** gated stages — each waits for the previous to confirm before advancing. (The terminal renumbered from 4 to 5 stages with the 2026-05-18 pair-prompt addition.)

**`[1/5] Pair code` — mint + render code+QR + wait for app to claim**
Mints (or reuses) a 256-bit `pollSecret` and POSTs `sha256(pollSecret)`
to the FE Cloud Function `/api/devices/initiate-pair`. The function
creates a synthetic Firebase Auth user, allocates a unique 8-char pair
code, and returns `{ deviceId, pairCode }`. The terminal prints the
code in big mono digits with a dash at position 4 (`K7XQ-9B2M`) and an
ASCII QR right below; the BE then polls
`devices/{deviceId}/pending/{sha256(pollSecret)}` (anonymous Firestore
REST) every ~2s for a customToken. Two ways to claim:
- **Type** — Super Research app → **Account → Add Device** → paste
  the 8-char code → submit. Works on any device with the app open.
- **Scan** — phone camera on the QR; the encoded payload deep-links
  to Account → Add Device with the code pre-filled.

> **Don't have a web app account yet?** The Super Research app lives
> at the deployment URL the dev shares with you (Google sign-in only).
> The app is required for this stage — `--pair` sits on its polling
> loop until you claim the code. Default window is 15 minutes.

Once the claim function writes the customToken, the BE exchanges it
via Firebase REST for `{refreshToken, idToken, uid}`, saves the
refresh token to the OS keystore, and prints
`[ok] Paired — you@example.com`. The `pollSecret` survives in
`research_config.json` so a future Reset Pair Code can rebind to the
same `deviceId` without a fresh handshake.

**`[2/5] On Startup` — supervised auto-restart prompt**
After the link lands, `--pair` prompts:

```
Enable On Startup? [Y/n]:
```

- **`Y` (default)** — opts into supervised mode; actual arming is **deferred to Stage 5** so an aborted login can't leave Firestore flagged as supervised while platforms are half-logged-in.
- **`n`** — skip; you'll run `python research.py --serve` manually after `--pair` finishes (and, on Linux/Mac, set up your own backgrounding via `nohup` / `tmux` / `screen` / your own systemd unit — see [§ Linux/Mac backgrounding](#linuxmac-backgrounding-while-track-c-is-still-pending)).

**`[3/5] API keys` — Anthropic + Gemini detect-prompt-verify** *(reordered to position 3 on 2026-05-18 so CUA + Vision are available for Stage 4)*
`--pair` runs `resolve_api_key()` and `resolve_gemini_api_key()` to check whether each key is already resolvable from any source (FE Account-page Firestore, Windows user-scope, shell env, or `.dg-supervisor.env`). For each missing key, it prompts:

```
Anthropic  — get one at https://console.anthropic.com/settings/keys
>  Paste Anthropic key (sk-ant-...) or [S]kip:
```

On paste, the BE makes a cheap **live-API verification call** (`models.list` for Anthropic; `GET /v1beta/models` for Gemini) with a 5s timeout. If the provider rejects the key (auth_failed), the prompt re-asks up to 3 times then offers `Save anyway? [y/N]` defaulting to no. If the verifier itself can't reach the API (network_error — offline pair, transient blip), the key is saved with a fail-loud-at-first-run warning rather than blocking the pair.

On verified paste, the BE writes the key to **BE-local persistence**: Windows User-scope env on Windows, `.dg-supervisor.env` upsert on macOS / Linux. It also mirrors to `os.environ` under the canonical name (`ANTHROPIC_API_KEY` for the Anthropic key, `GEMINI_API_KEY` for the Gemini key) so the running pair session can use the key immediately, and busts `_RESOLVED_KEY_CACHE` so the very next `resolve_api_key()` call (at the top of Stage 4 browser-login CUA init) sees the new key. Pair-time keys do NOT touch Firestore — the FE Account → API Config page is a separate surface that writes Firestore directly. (Pre-2026-05-23 devices may still have the legacy aliases `CUA_API_KEY` / `GOOGLE_API_KEY` in their User-scope env; `_migrate_legacy_api_keys()` runs once at startup, copies any surviving value to the canonical name, then retires the legacy entry. Idempotent + sentinel-cached.)

Skip is first-class per key — pair finishes regardless. Missing Anthropic falls back to **Playwright-only** verification in Stage 4 (less rigorous; no Pro-tier check) and surfaces a `cua_unavailable` alert at first job (recoverable via the chat-side `[Retry]` button once you add the key); missing Gemini silently disables narration.

**`[4/5] Browser logins`**
Runs the same real-Chrome sign-in engine `--login` uses:
- **Phase 1 — real Chrome sign-in.** Opens your *real, non-automated* Chrome (a plain subprocess) on the profile, pointed at the ChatGPT / Gemini / Claude / NotebookLM sign-in pages. You sign into each and solve any human-verification, then press Enter. Real Chrome is used here because Google BotGuard / Cloudflare block the automated browser on sign-in pages — and a human sign-in also *warms* the fresh profile's trust.
- **Verification is optional (2026-07-02).** Pair then asks `Skip the verification step? [Y/n]` — **Enter skips** (recommended: automated verify navigations on a brand-new profile are the strongest bot-score signal, and runs recheck logins at phase time anyway). Your per-platform state is still recorded truthfully via a local cookie read (zero page loads). Answer `n` to run the old patchright verify pass (sign-in + Pro tier per platform). `--login` never verifies — it's Phase 1 + the add-another-profile loop only.

The four platforms:
- ChatGPT (chatgpt.com)
- Gemini (gemini.google.com)
- Claude (claude.ai)
- NotebookLM (notebooklm.google.com)

When the optional verify pass runs and a platform is not-signed-in or on Free, an interactive prompt offers **[r]** reopen your real Chrome to fix (sign in / switch to Pro) or **[Enter]** continue as-is (keep Free / skip a missing platform). Verify also TOLERATES a Cloudflare / human-verification interstitial — it records "couldn't verify (likely still signed in)" instead of a false "not signed in". Ctrl+C cancels. The pair completes and the supervisor arms even on partial or zero logins — a login hiccup no longer blocks pairing.

> Phases 4 + 5 run in the frontend now (YouTube via Data API, Doc + email via Docs API + Resend), so YouTube Studio, Gmail, and Google Docs are no longer in the BE login checklist.

It mirrors the resulting login state to the BE-owned `devices/{deviceId}.logins` map so the app can show your progress.

> **Markers only tick after real auth.** `verify_login()` checks only auth-specific DOM (profile menus, account chips, chat-history lists). Generic chat-input elements are excluded because they show up on logged-out landing pages too.

> **F4 / DGOPS-7451 cookie check** *(relaxed 2026-05-18)*: when Stage 4 opens the browser, it inspects the Playwright profile for persisted Google auth cookies. The relaxed semantics: refuse pair only when the device was previously paired to a DIFFERENT account (`account_switch_with_prior_cookies`). First-pair on a fresh device OR re-pair to the same account both allow cookies through with a passive log line + `security_pair_allowed_with_prior_cookies` event — the existing Google session is presumed to belong to the user about to claim THIS link. Strict "any cookie → refuse" was creating a catch-22 with `--unpair` preserving the profile. For the account-switch refuse case, the message points to `--unpair --deep` (below) which wipes the profile cleanly.

**`[5/5] Ready` — arm supervisor (if opted in) + final message**
If you said `Y` to On Startup back in Stage 2, the supervisor is armed now — Windows Scheduled Task, macOS LaunchAgent (`~/Library/LaunchAgents/com.dgresearch.supervisor.plist`), or Linux systemd-user unit (`~/.config/systemd/user/dgresearch-supervisor.service`) depending on platform. If you said `n`, any leftover scheduled task / launchd agent / systemd unit is torn down so the machine genuinely matches "unsupervised". Final banner branches on whether the supervisor is live.

### Step 4: After pair succeeds

When all 4 platform logins clear, the flow:

1. Closes the browser
2. Persists `pollSecret`, `deviceId`, `pairedUid` in `research_config.json`
3. Keeps the refresh token in the OS keystore (DPAPI / Keychain / libsecret)
4. Arms the supervisor inline if you said `Y` to On Startup back in Stage 2 (Windows Scheduled Task / macOS LaunchAgent / Linux systemd-user unit), or tears down any leftover scheduled task if you said `n`
5. **Exits the Python process — pair does not stay running.**

The final banner branches on whether the supervisor is live:

```
✓  Paired with you@example.com
✓  All 4 platforms logged in
✓  Browser closed
✓  Anthropic key saved to this machine  (or "Skipped — set later via Account → API Config")
✓  Gemini key saved to this machine     (or "Skipped — set later via Account → API Config")
...
The bond is forged.  The backend is live — running in the background.        # if supervisor armed
                                          OR
The bond is forged.  Start the backend in this terminal to accept jobs:       # if unsupervised
    python research.py --serve
```

### Step 5: Start the Server

```bash
python research.py --serve
```

The server runs on port 8000 with:
- A **5s heartbeat** → writes `devices/{deviceId}.lastHeartbeat` + `status` + `workerCount` so the app's Account page and sidebar device switcher show the right online/offline dot AND know how many parallel slots this device has. (FE offline threshold = **30s** = `DEVICE_OFFLINE_THRESHOLD_MS`, so six missed heartbeats flip the tile.) Worker-1 also publishes `version` / `updateAvailable` / `updateStatus` / `versionCheckedAt` (the app's Settings → About version + inline Check → Update control reads these) and `sourceCheckout` — `true` for a source tree (`git clone` + `python research.py`), gated on the PATH probe `_is_source_checkout()`, so the app shows "Source checkout · update with `git pull`" (no Check button) instead of the app-update control.
- A **Reset-recovery watcher** — idle while the Firestore client is healthy; when the owner triggers Reset Pair Code, the BE's refresh-token revokes and this watcher polls `devices/{deviceId}/pending/{sha256(pollSecret)}` for the new customToken. On pickup it bootstraps a fresh keystore entry and exits cleanly so the supervisor respawns with new subscriptions. Net effect: Reset is hands-off on the PC under supervised mode.
- A **Firestore queue listener** — picks up jobs from `devices/{deviceId}/queue/`. Multi-worker aware: with `workerCount = N` (see § Multi-Worker below), N concurrent slots run in parallel; a new submit lands in explicit `queued` state only when ALL N slots are busy OR there are already-deferred queue docs ahead of it (FIFO fairness). Sharers can submit too — the BE picks up their queue items as long as their uid is in `sharedWith[]`. Cross-account submits sort by Firestore `submittedAt` (server timestamp, clock-skew immune); `_recompute_deferred_queue_positions` renumbers all deferred docs on every claim and cancel so the FE banner reflects #N changes live.
- A **command listener** for `stop` / `pause` / `resume` / `config` / `add_context` / `agent_decision` / `continue_anyway` / `retry_phase` / `skip_phase` / `skip_init_verify` / `retry_init_verify` / `skip_agent` / `retry_agent` / `continue_partial_agent` / `poke_agent` / `wait_longer_agent` / `dismiss_alert` / `discard_run` / `ping`, plus the owner-only worker-1 device commands `update` / `check-update` (the app-driven remote backend update: `update` runs the idempotent `_perform_self_update` + writes `updateStatus`; `check-update` re-checks PyPI and republishes the version fields). **Dispatcher resume-contract (2026-05-18):** every action that acknowledges a paused alert calls `_controls.request_resume()` so the pipeline doesn't stay paused after the user clicks the action button. A static-analysis test (`tests/test_dispatcher_resume_contract.py`) asserts the rule on every required-resume action and rejects accidental `request_resume` on non-pause actions (`pause`, `stop`, `discard_run`, `ping`, `add_context`, `config`, `dismiss_alert`).

- **CLI dispatcher pause-reason routing** (DGOPS-7710 / F6 + 3 follow-up fixes) — when an alert pauses the BE with a `pause_reason` (`agent_link_failed`, `human_verification_required`, `cua_unavailable`, `claude_chat_mode`, `login_required`, `pro_required`), the CLI `r` / `s` keystrokes route to the correct alert-specific helpers (`set_agent_decision`, `set_continue_anyway`, `request_skip_agent`, `request_skip_init_verify`) **plus** `request_resume`, so manual operator intervention always releases the pause. The same routing pattern is mirrored on the Firestore command bus.

- **Phase 2 Claude clarification auto-reply** — when a vague brief makes Claude respond with chat-text clarifying questions instead of starting Deep Research (signature: tail of last message matches "Once you ... I'll launch the research"), the polling loop auto-types `"Up to Claude to decide for the best output."` + Send so the agent proceeds without operator intervention. 5-condition heuristic (one-shot per agent) gates the trigger; see `_claude_asking_clarification` + `_claude_send_clarification_reply` near `poll_all_agents_round_robin`. Without this, the BE used to wait for an artifact that never appeared and eventually surfaced a generic "Hit a snag" alert at the wall-clock cap.
- A **local HTTP API** on `http://localhost:8000` for the CLI + any direct calls.

Keep `--serve` running while you use the app. If the server stops, the FE's heartbeat-based offline detection flips the device dot red at the **30s** threshold, and the per-phase silence watchdog (T1/T2 — see FE README → Watchdog) surfaces actionable dropdown alerts on each in-flight phase. The pipeline does NOT resurrect on reload if the heartbeat is stale.

**Queue persistence across restarts** — on `--serve` startup, the backend re-enqueues any `status:"queued"` researches from Firestore, so the queue survives a `--daemon-loop` respawn. Anything that was `status:"ongoing"` when the previous process died is flipped to `paused_backend_restart` (with a "Resume from checkpoint?" warn alert in the FE), instead of appearing live-but-frozen. If the persist itself fails (Firestore unavailable on respawn), affected researches surface a `paused_backend_restart_failed` red error with the actual error string.

### Step 5a (optional, recommended): Enable On Startup (supervised auto-restart)

```bash
python research.py --resurrect
```

Registers an OS-native supervisor that runs a **daemon-loop wrapper** — a tiny supervisor process that (re-)starts `--serve` whenever it exits for any reason: crash, stop button, logout, reboot, etc.

- **Windows**: Scheduled Task (`SuperResearchBackend`), ONLOGON + PT5M re-fire, `MultipleInstances=IgnoreNew`. Worst-case downtime: ~5s on `--serve` exit, ~5min on daemon-loop exit.
- **macOS**: launchd user agent at `~/Library/LaunchAgents/com.dgresearch.supervisor.plist`, `KeepAlive=true` + `ThrottleInterval=10`. Bootstrapped into `gui/$(id -u)` so Chrome gets the Aqua session.
- **Linux**: systemd user unit at `~/.config/systemd/user/dgresearch-supervisor.service`, `Restart=always` + `RestartSec=10` + `PassEnvironment=DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR` so Chrome can render in the graphical session. Requires `sudo loginctl enable-linger $USER` once — `--resurrect` probes and surfaces a WARN if Linger=no.

The Account page's **Indestructible** toggle reflects the real installed-task state, so the toggle survives unlink+relink. Turn it off from the same page if you ever want to stop auto-restart.

> **Cross-platform supervisor** — Windows uses a Scheduled Task; macOS installs `~/Library/LaunchAgents/com.dgresearch.supervisor.plist`; Linux installs `~/.config/systemd/user/dgresearch-supervisor.service` (run `loginctl enable-linger $USER` so the daemon-loop survives logout — the installer prints a WARN if linger=no but doesn't sudo-escalate). All three are first-class supported as of 2026-05-18. The Latin header (`resurgam · the backend rises`) fires on all platforms so you know the verb reached.

### Linux/Mac backgrounding (stop-gap)

`--serve` is a normal foreground Python process. To keep it alive past your shell session:

**Linux/macOS — `nohup` (lowest friction):**
```bash
nohup python research.py --serve > serve.log 2>&1 &
disown
```
Use `pkill -f "research.py --serve"` to stop. Log accumulates at `serve.log`.

**Linux/macOS — `tmux` / `screen`:**
```bash
tmux new -s superresearch
python research.py --serve
# Ctrl-b d to detach. Reattach with: tmux attach -t superresearch
```

**Linux — `systemd --user` (DIY alternative; native supervisor via `--resurrect` is preferred):**

The native supervisor (`python research.py --resurrect`) installs an equivalent unit at `~/.config/systemd/user/dgresearch-supervisor.service` automatically. Use this DIY ini only if you want to manage the unit yourself or pin a specific path:

```ini
# ~/.config/systemd/user/superresearch.service
[Unit]
Description=Super Research backend
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=%h/super-research-backend
ExecStart=/usr/bin/python3 %h/super-research-backend/research.py --serve --env-file %h/super-research-backend/.dg-supervisor.env
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```
Then: `loginctl enable-linger $USER && systemctl --user daemon-reload && systemctl --user enable --now superresearch.service`.

### Step 5b (disable On Startup): `--retire`

```bash
python research.py --retire
```

The opposite of `--resurrect` — disables auto-restart while keeping this PC paired with your account. Three-step:

1. **Deletes the Windows Scheduled Task** so `--daemon-loop` won't auto-start at next logon / reboot.
2. **Kills every running `--daemon-loop` AND `--serve` process**, looping for up to 8s so a mid-enumeration respawn still gets caught (the supervisor respawns `--serve` every ~5s between deaths, so a single-shot kill misses any `--serve` that happened to be respawning at the wrong moment).
3. **Flips the Firestore `supervised` flag to `false`** so the Account toggle matches reality instantly.

Idempotent: works whether or not the task/loop was installed. Manual one-off `python research.py --serve` runs (role="other" in process discovery) within `DG_ORPHAN_MAX_AGE_HOURS` (default 4h) are NOT touched — only supervisor-spawned procs.

Turning off the **On Startup** toggle in the app → Account page runs the same teardown remotely.

### Step 5c (full disconnect): `--unpair` *(with `--deep` 2026-05-18)*

```bash
python research.py --unpair          # default: preserves the Playwright browser profile (your platform logins survive)
python research.py --unpair --deep   # also wipes ~/.super-research/browser-profile/ for a fresh-browser re-pair
```

The "I'm done with this PC" command — wipes everything `--retire` wipes, AND deletes the device server-side so it disappears from every browser instantly. After `--unpair`, this PC appears NOWHERE in the Super Research app's device list.

Five-step:

1. **Process kill + scheduled-task/launchd/systemd-unit removal** (always runs regardless of pairing state, so partial-pairing scenarios clean up correctly).
2. **Server-side delete** — mints a fresh ID token against the current refresh token, calls `/api/devices/unpair-self` so the Cloud Function revokes the synthetic Firebase Auth user, deletes the device doc, and drops the admin-only pollSecretHash entry. Owner + sharer tiles vanish across every browser within a second.
3. **Keystore clear** — wipes the OS keystore entry (DPAPI / Keychain / libsecret slot or the `chmod 0600` file fallback).
4. **Wipes `research_config.json` + `device_config.json`** locally so a future `--pair` starts fresh.
5. **Final-state verification** — if anything survived, prints the surviving PIDs so you can taskkill manually.

**With `--deep`**, an additional step removes the Playwright profile directory (`~/.super-research/browser-profile/`) via `shutil.rmtree(..., ignore_errors=True)`. Use this when re-pairing to a different account or when the F4 cookie check refused pair due to stale Google auth. The default preserves the profile so a re-pair on the same account doesn't force you back through ChatGPT/Gemini/Claude/NotebookLM logins.

To bring this PC back: re-run `--pair` to mint a fresh deviceId + pair code and claim it from the app.

### Step 6: Fire a research topic in the app

Open Super Research (the web app) → type a topic → backend picks it up from Firestore → pipeline runs here. If the app says "No backend connected" there's a Connect bubble with a Scan QR button that links in seconds.

## Multiple Devices (same user)

One account can pair multiple PCs. Each `--pair` on a new machine mints its own synthetic device user + top-level `devices/{deviceId}` doc. The app's sidebar gets a device switcher (with online/offline dots) and every research is stamped with the device it ran on — so jobs you fire from the app route back to the specific PC that was **active** when you hit Start. If you fire two jobs on the same device while it's at capacity, the second queues; if you fire one on a different device, both run in parallel.

## Multi-Worker (parallel runs on one PC)

A device can run **multiple pipelines in parallel** when its backend has `workerCount > 1` in `research_config.json`. Default is **1** (single-worker); a typical multi-profile production setup is **2**. Each worker is a separate Python subprocess spawned by the daemon-loop supervisor on adjacent ports (8000, 8001, …); each subscribes independently to the same `devices/{deviceId}/queue/` and `devices/{deviceId}/commands/` subcollections, and each pins to its own browser-profile dir (`~/.super-research/browser-profile-N/`) so they don't race on the same Chrome session.

- **Where it's set:** `research_config.json.workerCount`. Loaded by `load_worker_count()` (research.py:3486) with a >=1 clamp so a bad config can't disable the only worker.
- **How to raise it:** run `python research.py --pair` and at the "Add another browser profile?" prompt during Stage 4, add a second profile. The BE will spawn the additional worker on next supervisor cycle.
- **Where the FE learns about it:** every heartbeat publishes `workerCount` on `devices/{deviceId}`. The FE gates a new submit on `ongoing >= workerCount OR queued > 0` to decide ongoing vs queued.
- **Two researches running at once on one PC — is that a bug?** No. It's the expected behavior under `workerCount=2`. The queue only kicks in when ALL workers are busy.
- **Cross-cutting safety:** the on-disk worker lock (`safe_enqueue_lock_*`) prevents dual-spawn on supervisor restarts; the listener `_pending_enq` counter prevents back-to-back claims by Firestore listener replay; a pre-claim status re-check drops a claim if the research doc transitioned to a terminal status (cancel, stop) between claim-scan and enqueue (cross-worker cancel race guard).
- **HARD_RESET safety:** Reset Pair Code writes a single `hard_reset` command to `devices/{deviceId}/commands/`. Every worker subscribes and processes it independently — each touches `.stop` on its own active run dir, flips its own active research doc to `cancelled`, and schedules `os._exit(0)` so the daemon-loop respawns it clean. No zombie runs across N workers.
- **Worker rest/wake (#903):** the owner can park an idle worker from the app's Shared-With popup, recorded in the owner-writable `devices/{deviceId}.restingWorkerIds[]` field. A resting worker takes **no new runs** — `_worker_is_resting()` gates both new-claim paths (the start-listener claim and the idle-rescan claim; fresh device-doc read, ~3s TTL, fails open to awake). In-flight runs finish untouched (resumes bypass the listener). When all workers rest, new submits queue with a "Workers paused" state; it persists across BE restarts (the 12h stale-queue sweep exempts rest-deferred docs). Sharers never see worker pills.

## Multiple Users (same backend) — sharing via pair code

The same 8-char pair code drives sharing. Show the code in Account → Manage devices (or copy it from the email after Reset), share it with a teammate, and they paste it into their own Account → Add Device. The FE claim function notices the device is already owned and appends their uid to `sharedWith[]` — they get a tile labeled "Shared by {your name}" and can submit research that runs on your PC.

Per-user scoping is enforced by Firestore rules + the BE's custom claim. Sharers can submit research and read their own runs; they can't read the owner's other data, can't read the owner's research history, and can't see the pair code (it's gated by the owner's Pair Code Lock if enabled). Reset clears `sharedWith=[]` in one step — handy for revoking access to a stolen / overshared device without taking the BE down.

## Pipeline Phases

| Phase | Platform | Typical Time |
|-------|----------|------|
| 0. Init | System (browser launch + login check) | ~10s |
| 1. Brief | ChatGPT Pro + Extended Thinking | ~25 min |
| 2. Research | ChatGPT + Gemini + Claude (parallel) | ~49 min |
| 3. Podcast | NotebookLM (upload + audio generation) | ~25 min |
| 4. YouTube | FE-owned: Data API (ffmpeg encode + `youtube.videos.insert` via OAuth) | ~1-2 min |
| 5. Report | FE-owned: Docs API + Resend | ~3 min |

Times based on real run analytics. Total: ~1h 50m for a full pipeline. ChatGPT Pro, Claude Pro, and Gemini Advanced are the assumed baseline — see [Before you start](#before-you-start-prerequisites-checklist) for per-seat costs. Non-Pro accounts are flagged with `[Continue with Free] [Retry]` — by the in-phase tier tells by default (verification is opt-in since 2026-07-02), or by Phase 0's vision check when that Setting is on; Retry re-checks after you sign in with a Pro account in the same browser. If you `Continue with Free`, the pipeline runs end-to-end on Free tiers, but Deep Research depth, image quality, and turn limits are far lower than what the per-agent timings, prompts, and waits were tuned against, so per-agent output is much shallower.

## Phase + per-agent narration (consolidated 2026-04-30)

Long quiet stretches in Phases 1–3 are expected (ChatGPT Pro thinks for ~3 min before writing, NotebookLM renders for **5–10 min on Short, 10–20 on Default, 30–45 on Long** mode — `_AUDIO_TYPICAL_RANGE_MIN` in research.py drives the in-chat ETA narration), but a dead-looking tile makes the whole app feel broken even when nothing's wrong. The narration system was consolidated 2026-04-30 from four overlapping writers down to a single per-agent narrator with a backend-fallback tail. Result: cheaper, less duplication, less parroting.

- **Per-agent narrator (the only writer now)** — every Phase 1/2 agent has a narrator worker that reads a bounded ring buffer of recent events (~50) and emits a `phase_narration` / `agent_narration` event about every 6s per active agent. Brain (as of 2026-05-28): **Gemini 3.5 Flash** primary (`gemini-3.5-flash`, env `GEMINI_TEXT_MODEL`); **Anthropic Haiku 4.5** cross-vendor fallback (`claude-haiku-4-5`, env `DG_NARRATOR_HAIKU_MODEL`) on any non-429 4xx/5xx/timeout/empty response. 429 is surfaced to the outer loop for backoff rather than absorbed by the fallback. The swap consolidates the narrator onto the same text-task stack as summary / title-fallback / URL-extractor (was the lone Anthropic-text-call outlier); Haiku stays as the hedge for Google regional blips. Pre-04-30 used Gemini Pro 2.5 (parrot issue at temp 0.2 — fixed on 3.5 Flash). Cost envelope: ~200 input / 30 output tokens per call → <$0.02 per full pipeline run.
- **Anti-parroting prompt + chrome scrub.** The narrator system prompt (research.py:~13005-13104) has explicit anti-pattern rules: don't echo input verbatim, don't start with "currently" or "Status:", skip chat-thread chrome (`You said:` / `Claude responded:` / `Gemini said` / `brief.md`). Above the narrator, `_compact_event_for_narration` (research.py:12705) scrubs those same chrome strings out of the input window BEFORE the narrator sees them — scrape outputs (chip / step counts) are untouched.
- **DOM scrape rules per platform:** Claude scrape (research.py:7116-7124) is panel-scoped to `aside` / `[class*="artifact"]` / `[class*="research"]` — dropped `.font-claude-message` and `.contents` heading selectors that grabbed conversation-chrome. ChatGPT P2 panel walker (research.py:7979-7984) dropped the loose `[class*="row" i]` selector and added a 23-verb `VERB_GATE` regex with min-length raised 4→12 to drop "OK" / "Done" single-word noise.
- **Vision narrator (`narrate.py`) RETIRED.** `PHASE_BUDGET=0` by default — the per-agent narrator covers the same slot via DOM events without burning a separate Gemini call. Set `DG_VISION_NARRATE=1` to re-enable it as a coverage escape hatch.
- **BE phase-fallback tail.** When the narrator is silent (Gemini + Haiku both failing, or 6s startup gap), research.py:9601-9604 emits `Extended Thinking active · 12,400 chars drafted` into `progress["progress"]`. The FE renders this as a final tail under the agent narration (PhaseDropdown.tsx:1880-1885). No more dead silence on a working agent.

> **Narration brain envs:** `DG_NARRATOR_USE_GEMINI` (default `1`; set `0` to skip Gemini and go straight to the Haiku fallback — renamed from `DG_NARRATOR_USE_HAIKU` on 2026-05-28 when the primary swapped, with the old name honored as a backwards-compat alias for one release), `GEMINI_TEXT_MODEL` (default `gemini-3.5-flash`, also drives narrator primary), `DG_NARRATOR_HAIKU_MODEL` (default `claude-haiku-4-5`, the cross-vendor fallback), `DG_VISION_NARRATE` (default `0`; set `1` to re-enable the retired vision narrator). All optional.

## Phase 0 verification (OPT-IN since 2026-07-02)

**Login verification is off by default for every account** — proactive verify navigations are the strongest bot-score signal on fresh profiles (live evidence: a verify pass sailed through and the Cloudflare challenge hit the *work* page seconds later). Turn it back on per-account via Settings → Pipeline → "Verify sign-ins before each run" (`verifyLogins`). What replaces it:

- **Phase-time cookie trust** — before each phase touches a platform, a local cookie read (zero page loads) confirms the profile still holds that platform's session cookie. Cookie present → trusted; genuinely missing → the full tab+vision gate + `login_required` card runs, exactly as before.
- **Stale-cookie honesty** — a session that died server-side (cookie present but invalid) is caught by the phase's own failure paths, which now probe the already-open page for a login wall and surface an actionable "looks signed out" card (never the old generic "didn't start"); that platform is then re-verified for real on Retry.
- **Tier tells without navigation** — ChatGPT: the P1 Pro-selector backstop; Gemini: a DOM tier read on its P2 work page; Claude: the chat-mode card (Free Claude lacks the Research tool).

When verification IS enabled, preflight walks platforms one at a time (tab open → 4s hydration → URL check → CUA vision → per-platform `login_required`), exactly the 2026-04-24 sequential design.

## Phase 2 — per-agent extraction rules (Apr 19 late-late)

Phase 2 enforces different link-extraction rules per platform. The right rule for each platform comes from how each service exposes authenticated conversations:

- **ChatGPT** — unchanged from Phase 1 brief behavior: public-share link extraction first, falls back to the conversation URL if the share flow fails. A conversation URL is acceptable because it's publicly readable to anyone with the link (shareable without explicit action).
- **Gemini + Claude** — **PUBLIC share links ONLY**, hard-fail on miss. No conversation-URL fallback — those URLs are private to the authenticated session and would fail silent-ticks downstream. If the share flow fails after 3× retries, the agent surfaces a Retry / Skip gate (matching the B1 link-first completion gate).

Every extraction method logs explicitly: `[gemini_extractor] method=X result=Y` (and equivalent per platform). Makes post-mortem debugging of "why did this agent not tick" trivial. `link_extracted` is emitted per agent the moment a verified link lands (no phase-end batching).

**Claude 2-artifact wait hard-fail.** If Claude has reached ≥80% of its allotted wait time AND has <2 artifacts in the side panel, the pipeline hard-fails that agent with Retry / Skip — no silent half-answer. First artifact is almost always a research plan, not the final report; accepting a single-artifact Claude as done produces a broken downstream.

**Tab round-robin — `target_page` anchoring.** `agent_loop` accepts a `target_page=None` parameter. Before every polling tick it calls `bring_to_front()` on that agent's tab so CUA always sees a live browser viewport, not a stale background capture from whichever tab happened to be front when three agents were racing. `_anchored_screenshot()` helper handles the pattern; re-anchors after every `execute_action` too. Prevents cross-agent tab interference — e.g. Gemini's vision call returning Claude's screenshot because Claude's tab happened to be front-of-stack when the capture fired.

**Claude setup via Playwright (not CUA).** `setup_claude_dr` was rewritten as Playwright steps — select Opus 4.8 from the model dropdown, set Effort = Max, toggle Adaptive Thinking, enable the Research tool — all DOM selectors + `.click()` calls. Eliminates ~30-90s of CUA vision overhead per setup and removes a class of "CUA clicked the wrong thing" setup failures. CUA is still used mid-run for anything that isn't deterministic DOM.

**Clipboard permissions — granted once at browser bootstrap, covers every P1/P2 agent.** The pipeline drives the clipboard for two things: brief *delivery* (`verified_paste_brief` Strategy A pastes via `navigator.clipboard.writeText` + Ctrl+V — Phase 1 brief and Phase 2 brief hand-off) and report *extraction* (Gemini's "Share & Export → Copy contents" writes the report markdown to the clipboard for the T1 tier; ChatGPT/Claude copy paths likewise). In the automated patchright context those clipboard APIs are **denied** unless the permission is granted, and the denial is silent — the page still shows a "copied" toast but the read comes back empty, so Gemini T1 falls through to the T2 DOM scrape on every run. To cover all agents in one place, `Browser.start` grants `clipboardReadWrite` once at browser bootstrap via CDP `Browser.grantPermissions` (research.py `Browser.start`, ~line 14564). The grant has no `origin`/`browserContextId`, so it applies to the persistent context and persists for the session — every agent tab (`new_tab` and `open_isolated_tab` share this one context) inherits it. `verified_paste_brief` still grants per-paste as a defensive fallback in case the bootstrap grant ever fails.

## Per-phase alert narration

Every failure category — timeouts, CUA fallbacks, Anthropic 429/529 retries, share-link misses, login-expired, ffmpeg failures, email auth problems, browser crashes, and more — emits into the correct phase's `PhaseAlertPanel` inside the app's phase dropdown. No chat-bubble spam. Per-phase coverage:

- **Phase 0** — browser launch/crash, Playwright profile lock, missing Chromium binary
- **Phase 1** — brief timeout, brief paste retry per attempt, brief-short (offers `continue_anyway`), brief model error, manual-brief 3h backstop (auto-fail with `pipeline_stopped` reason `manual_brief_wait_backstop_3h`)
- **Phase 2** — agent timeout (auto-skip with partial save if ≥200 chars; no human prompt needed since 2026-04-30 `be8f7b3`), send-button CUA fallback, paste outer-retry narration, full HV (human-verification) stage narration: detected → auto-clear 1/2 → 3 min cooldown → retry 2/2 → success/fail with Resume/Skip. HV cooldown is 180s (was 45s — providers need the time to release holds). Browser crashes auto-retry with a passive recovery banner; no Retry/Skip prompt.
- **Phase 3** — per-agent share-link extraction failure, NotebookLM login-expired vs generic upload failure, "no MD files" gate, inter-phase gate (P2 produced no documents). Derived stems (`brief.md`, `consolidated.md`) are excluded from NotebookLM uploads via `_DERIVED_STEMS` filter (research.py:14627) — never uploads consolidated.md.
- **Phase 4** — owned by FE (YouTube upload via Data API). BE no longer surfaces P4 errors; see FE for the alert matrix (`uploadYouTube 401/403/quotaExceeded` map to OAuth-scope / quota-cap actionable copy).
- **Phase 5** — owned by FE (Doc creation + email). BE no longer surfaces P5 errors; see FE for the alert matrix.
- **Cross-cutting** — Anthropic 429/529 narrate as retrying; other API errors surface as `pipeline_warning` on the current phase

Default action on every alert is `[Retry] [Skip]`. Skip writes the unified `skip_phase phase=N` command, replacing the old `skip_phase` / `skip_phase` verbs (removed in U2). Phase-specific alerts may add `HV Resume` or `continue_anyway`. **Stop is NOT a per-phase action** — pause/stop/resume stay global in the app's chat input bar.

### Error matrix (normalized, Apr 19 late-late)

The per-alert action set was consolidated to reduce noise and remove affordances that invited broken states:

- **Default everywhere: Retry · Skip.** Every failure surface offers this pair unless it's specifically overridden below.
- **Workspace cap hit in Phase 2 → `End research` only** (`action=stop`). No point retrying when the user is out of workspace slots; other phases keep Retry · Skip.
- **Poll timeout in Phase 2 → auto-skip** (since 2026-04-30 `be8f7b3`). Removed the `Retry · Skip · Wait` alert; the BE saves whatever ≥200 chars it has and continues. Eliminates an indefinite human-decision wait.
- **Removed the "Proceed without CUA" option** (let users walk into broken-state pipelines with no recovery path). Poke morphed into the normalized Retry (which in turn does the hard tab close+reopen from the Apr 19 early `retry_agent` work).
- **Stuck-agent buttons relabeled** to match the normalized vocabulary: Poke → **Retry**, "Wait longer" → **Wait**, "Skip agent" → **Skip**.

## Stuck-state risk fixes (2026-04-30 `6545335` + `be8f7b3` + `549f079`)

Three classes of "pipeline silently wedged forever" caught and capped:

- **Manual brief 3h backstop** — `_BRIEF_WAIT_BACKSTOP_S = 3 * 3600`. If the user enabled "Provide my own brief" but never sends one within 3h of the chat-input prompt, `fail_phase` fires + emits `pipeline_stopped` with reason `manual_brief_wait_backstop_3h`. No more pipelines wedged on a vacant chat input.
- **Pending queue persist-failure surface** — `_persist_pending_queue` returns bool; if a Firestore write fails during BE shutdown handover, affected researches get `status=paused_backend_restart_failed` + `lastError` field with the actual exception string. FE renders this as a red error banner, not the green "queued" pill.
- **Dead-tab guard before soft retry** — research.py:10380. After 2 hard failures, the loop checks if the agent's tab is dead (closed / crashed); if dead, `fail_agent` fires + remove from pending. Prevents soft-retrying a corpse forever.
- **Browser crash auto-retry** — when 3 sites crash in the same window, `emit_browser_recovery_status` sends a passive banner to FE and bypasses the run_pipeline.finally retry guard. FE auto-clears the banner on resume (`auto_clear_on_resume=true` flag on AgentAlert).
- **P2 timeout auto-skip** — drops the `await_agent_decision` block; if the agent has ≥200 chars of partial output, it's saved and the agent flips to skipped without human prompt.
- **Auto-retry kwarg forwarding** — `uid/research_id/run_id` are forwarded on retry recursion (research.py:18006) so the Firestore listener stays attached on auto-retry.

## CLI Mode

Run research directly from the terminal (no web app):

```bash
python research.py "Your research topic"
python research.py "Topic" --brief-file brief.txt     # Skip Phase 1
python research.py "Topic" --pdf paper.pdf             # Attach PDFs
python research.py --resume queue_name                 # Resume stopped run
```

**If the pipeline pauses** (most commonly Phase 0 `login_required`), the terminal prints a recovery menu:

```
[PAUSE] login_required — log in via the open browser, then:
  r) resume   s) skip phase   q) stop pipeline
>
```

After completing the login in the Chrome window the backend opened, type `r` + Enter to resume — Phase 0 re-verifies and the pipeline continues. `s` skips the current phase; `q` stops the run cleanly. Commands are accepted while stdin is a TTY; piped or headless runs see the menu but ignore typed input.

## Environment Variables

> **Recommended path**: set these in `.dg-supervisor.env` (auto-loaded by the supervisor at startup via `--env-file`; see [Step 2](#step-2-environment) above). The shell-env path below still works for manual debugging or legacy shell-rc setups — `resolve_api_key()` honors both.

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key for browser automation (CUA) + narrator's Haiku 4.5 cross-vendor fallback. Industry-standard name (matches the Anthropic SDK's auto-pickup). Legacy `CUA_API_KEY` is auto-migrated to this name on next BE startup. |
| `CUA_MODEL` | `claude-sonnet-4-6` | Claude model for CUA. Sonnet 4.6 is Anthropic's recommended CUA model (largest OSWorld jump in the 4.x lineup) and ~40% cheaper than Opus. Override via env for A/B tests. |
| `VISION_LIGHT_MODEL` | `claude-sonnet-4-6` | Claude model for the lightweight vision checks (login-wall detection, pro-tier detection). Decoupled from `CUA_MODEL` so they can evolve independently. |
| `VISION_HEAVY_MODEL` | `claude-opus-4-8` | Claude model for the vision tier-2 high-stakes / retry-after-failure path. |
| `CUA_SCREEN_WIDTH` | `1280` | Browser viewport width |
| `CUA_SCREEN_HEIGHT` | `800` | Browser viewport height |
| `GEMINI_API_KEY` | (optional) | Gemini API key. Used by the narrator (Gemini 3.5 Flash primary), summary helper, URL extractor, and other BE text tasks. (P4 thumbnail generation lives on the FE — `web/src/lib/album-art.ts` — and uses the FE-side env / per-user-pref Gemini key, not this BE one.) |
| `GEMINI_TEXT_MODEL` | `gemini-3.5-flash` | Gemini text model for summary, URL extraction, narrator primary. 2.5 Flash hard-deprecates 2026-06-17 on the generativelanguage API path — leave at default unless reproducing on the prior model. |
| `GEMINI_NARRATE_MODEL` | `gemini-3.5-flash` | Gemini model for the vision-narrator (`narrate.py`) screenshot panel reader. Kept as its own env so the narrator can be tuned independently from text-only sites. |
| `GEMINI_NARRATE_FALLBACK_MODEL` | `gemini-2.5-pro` | Hedge against a Flash-specific outage in the vision narrator. Holding on 2.5 Pro until 3.x Pro reaches GA. |
| `TITLE_MODEL` | `claude-haiku-4-5` | Claude model for research-title generation + API-key-validation tests. Same family as the narrator fallback. |
| `MAX_WAIT_DEEP` | `90` | Max minutes to wait per Phase 2 agent |
| `POLL_DEEP_RESEARCH` | `120` | Seconds between polling cycles (Phase 2 round-robin) |
| `MIN_AGENT_WAIT_MIN` | `5` | Minimum minutes from research-start before CUA completion check is allowed to fire |
| `BUG_REPORT_EMAIL` | (optional) | Where bug-report submissions land if FE bug-report uses the BE relay. FE has its own `BUG_REPORT_EMAIL` env on `/api/bug` — see FE README. |
| `DG_NARRATOR_USE_GEMINI` | `1` | Enable Gemini 3.5 Flash as the narrator primary (Haiku 4.5 as cross-vendor fallback). Set `0` to force the Haiku path directly. (Renamed from `DG_NARRATOR_USE_HAIKU` 2026-05-28 when the primary swapped.) |
| `DG_NARRATOR_HAIKU_MODEL` | `claude-haiku-4-5` | Haiku model id for the narrator fallback. |
| `DG_VISION_NARRATE` | `0` | Re-enable the retired vision narrator (`narrate.py`, `PHASE_BUDGET=80/phase`). Set `1` if a coverage gap appears in DOM-derived narration. |
| `DG_ORPHAN_MAX_AGE_HOURS` | `4` | Cutoff age for `--retire`'s "manual one-off `--serve` runs" preservation. |

## File Structure

```
research-automate/
├── research.py                 # Pipeline + FastAPI server
├── prompts.py                  # CUA prompts for each phase
├── vision.py                   # Anthropic Sonnet vision client (tier-2 acting): take_screenshot, vision_action, with_vision_fallback, shadow_observe_then_cua
├── narrate.py           # Vision-tier panel narrator (PHASE_BUDGET=0 by default; retired 2026-04-30 — re-enable via DG_VISION_NARRATE=1)
├── vision_test.py              # Fixture replay tool: --capture saves PNG+JSON, --fixtures replays + asserts action-class agreement + bbox containment
├── requirements.txt            # Python dependencies (now includes patchright>=1.61 + playwright>=1.61; floors bumped 2026-06-30)
├── research_config.json        # deviceId + pollSecret + pairedUid (generated by --pair; keep gitignored)
├── run_analytics.json          # Historical phase durations (auto-updated)
├── ARCHITECTURE.md             # Backend architecture + Frontend ↔ Backend API contract
├── .dg-supervisor.env          # Per-machine env config (gitignored; seeded from scripts/dg-supervisor.env.example on first --resurrect)
├── scripts/
│   ├── dg-supervisor.env.example  # Committed env-file template — install-time copied to .dg-supervisor.env if absent
│   ├── run_supervisor.cmd      # Manual-debug CMD helper (NOT wired into the Scheduled Task — supervisor invokes pythonw directly with --env-file)
│   └── vision_shadow_report.py # Per-hotspot agreement table from logs/vision_shadow.jsonl
├── tests/fixtures/vision/      # V1 Vision fixtures (PNG + JSON pairs); auto/ subdir is gitignored
├── queues/                     # Active/completed pipeline runs (per-topic dirs)
│   └── {topic}_{timestamp}/    # meta.json, config.json, delivery.json, documents/, podcasts/
# tracks/ — REMOVED 2026-04-29. The directory tree is gone (its only
# artifacts, events.jsonl + per-platform scrape JSONs, were already
# unwritten when Firestore became the sole transport). Firestore
# `users/{uid}/researches/{rid}/pipeline_events/` is the sole event store.
```

## Troubleshooting

**"No PipeToken found"** — Run `python research.py --pair` first.

**`ModuleNotFoundError: No module named 'patchright'`** — Run `pip install -r requirements.txt` again (patchright was added 2026-04-30; floor bumped to `patchright>=1.61` alongside `playwright>=1.61` on 2026-06-30). Then `python -m patchright install chrome`.

**`patchright` launches but Chrome doesn't open** — Patchright launches with `channel="chrome"` (real Chrome, not bundled Chromium). If real Chrome isn't installed on this machine, install it from google.com/chrome (Windows), `brew install --cask google-chrome` (macOS), or your distro's Chrome package (Linux).

**Backend shows "Offline" in the web app** — Make sure `python research.py --serve` is running. The heartbeat updates every **5 seconds**; the FE flips the dot red after **30 seconds** of silence (6 missed ticks).

**"Backend did not respond within 15s" / "didn't pick up the job"** — Only fires for immediate-claim submits (workers were free at submit time). Means the BE didn't ack within 15s — usually a transient Firestore RPC blip. Tap Retry. **Queued submits are exempt** as of 2026-05-22 (FE commit `992db14`) — they don't trigger this alarm even if claim takes minutes, which it legitimately can when all workers are busy with cross-account runs.

**Two researches running at once on one PC** — Expected under `workerCount > 1`. See § Multi-Worker above. Not a bug.

**Browser sessions expired** — The lighter path is now `python research.py --login`: it runs a **per-profile Y/N walk** (same as pair Stage 4) fronted by a **read-only pre-probe** that leaves any still-valid session **intact** — it only re-opens your real Chrome for the profiles you say Y to, so an already-signed-in profile is never blown away. Sign into the platforms + clear any Google/Cloudflare human-check in that window. It does **not** run the patchright login/Pro-tier verify pass (`--login` never verifies). Re-running `python research.py --pair` also logs you in again.

**NotebookLM login expired mid-run** — Surfaces as a Phase 3 alert with `login_expired` detail (distinct from generic upload failure). Re-run `--pair` to refresh that session; hit `[Skip]` on the alert if you want to move past Phase 3 and still get Phase 5 report/email.

**Anthropic 429 / 529 (rate-limit or overload)** — Retries automatically with narration in the current phase dropdown; usually self-resolves within one or two attempts.

**Anthropic API key invalid (401) — narrator goes silent** — The narrator falls through to Gemini 2.5 Flash on any Haiku error including 401. You'll see narration keep flowing (Flash-driven) but the BE log shows `[narrator] Haiku failed sc=401 — falling back to Gemini Flash` once. CUA itself ALSO needs a working Anthropic key — if the key is fully revoked, CUA tier-3 stops working and the pipeline relies on Playwright tier-1 / Vision tier-2 only. Check your Anthropic billing/keys page.

**Anthropic workspace usage limit hit (CUA 400)** — Same fallback semantics as 401: narrator routes to Flash; CUA tier-3 is unavailable until the limit window resets (typically 24h). Pipeline keeps running on Playwright + Vision; specific platform actions that require CUA (e.g. some HV captcha clicks) may need manual help via the FE alerts.

**Phase 4 audio failed but Phase 5 still matters** — Hit `[Skip]` on the FE Phase 4 alert; FE-P4's fast-path skip emits `phase_skipped:4` and chains directly into FE-P5 (Doc + email) without a YouTube URL.

**FE shows `paused_backend_restart_failed` red banner** — Backend tried to persist the in-flight queue on shutdown but the Firestore write failed. The `lastError` field on the research doc has the actual exception. Restart `--serve`; affected runs are kept on disk in `queues/` and can be resumed via the FE checkpoint banner once BE is back online.

**CLI mode pause hangs (no web app)** — `python research.py "topic"` running standalone (without `--serve`) cannot use the app's Skip/Retry buttons. When Phase 0 emits `login_required` (or any other pause), the terminal prints a recovery menu:

```
[PAUSE] login_required — log in via the open browser, then:
  r) resume   s) skip phase   q) stop pipeline
```

Complete the login in the open Chrome window, then type `r` + Enter to resume. `s` skips the current phase; `q` stops cleanly. Useful for headless rigs and onboarding before the web app is available. The menu only accepts input when stdin is a TTY — piped/Task-Scheduler runs print the menu but ignore typed input.

---

Built for Distributed Global.
