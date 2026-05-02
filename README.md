# Super Research — Backend Pipeline

Automates multi-agent deep research across 6 platforms. Tiered automation: Playwright (primary) → Vision (Anthropic Sonnet via `vision.py`, tier-2) → Claude Computer Use (tier-3 fallback).

> **Jira:** [DGOPS-6933](https://distributedglobal.atlassian.net/browse/DGOPS-6933)
> **Repo (this one):** github.com/dg-eng/super-research-backend
>
> The Firebase Admin SDK key (`firebase-service-account.json`) is **gitignored**
> and emailed separately by the dev — see ["Firebase Admin Key" below](#firebase-admin-key-required--firebase-service-accountjson).

## Platform support

| Platform | Server | `--pair` | `--resurrect` / `--retire` | `--unpair` |
|----------|--------|----------|----------------------------|------------|
| Windows 10 / 11 | Full | Full | Full (Scheduled Task) | Full |
| macOS | Full (manual `nohup`/`tmux`/`launchd` user agent) | Full | Coming shortly | Step-1/3 only (no supervisor) |
| Linux desktop (X11/Wayland) | Full (manual `nohup`/`tmux`/`systemd --user`) | Full | Coming shortly | Step-1/3 only (no supervisor) |
| Linux headless / WSL / Docker | **Unsupported** — Chrome needs a real display + user session for CAPTCHA / 2FA / login refresh |

The supervisor (`--resurrect` / `--retire`) currently uses Windows Task Scheduler. macOS launchd + Linux systemd-user supervisors are coming shortly. See [Linux/Mac backgrounding](#linuxmac-backgrounding-stop-gap) below for stop-gap options.

## Before you start (prerequisites checklist)

- **Python 3.11+** (`python --version`).
- **Real Google Chrome** installed (not just Chromium — patchright launches with `channel="chrome"`).
- **Anthropic API key** with browser-automation access (`CUA_API_KEY` or `ANTHROPIC_API_KEY` — either works; see Step 2).
- **Firebase Admin SDK key** (`firebase-service-account.json`) — emailed to you by the dev. See [Firebase Admin Key](#firebase-admin-key-required--firebase-service-accountjson).
- **Super Research web app account** — sign in at the deployment URL the dev shares with you (Google sign-in). You'll link the backend's ResearchToken from this account during `--pair` Stage 2.
- **Paid Pro tiers on ChatGPT, Claude, and Gemini** — required for the depth Phases 1–2 were tuned against:
  - **ChatGPT Pro** ($200/mo per seat) — Phase 1 brief uses Pro + Extended Thinking.
  - **Claude Pro** ($20/mo per seat) — Phase 2 Claude agent uses Opus 4.7 + Research mode (Free tiers don't expose Opus or Research).
  - **Gemini Advanced** ($20/mo per seat, via Google One AI Premium) — Phase 2 Gemini agent uses 2.5 Pro / Deep Think + Deep Research.
  - The pipeline will *run* end-to-end on Free tiers, but Deep Research depth, image quality, and turn limits are far lower. **Phase 0 vision-checks each platform's tier after login-verify and hard-flags the first non-Pro account it finds** with a `[Continue with Free] [Retry]` alert — sign out, sign in with a Pro account in the same browser, then click Retry to re-verify. Opting into Free for one platform suppresses the prompt for the rest of the run, so verify Pro is active in each platform's account/billing page before pairing to avoid surprises. (Stop is always reachable from the chat-box during a paused pipeline — no separate Stop button on the alert.)
- *(Optional)* Gemini API key for Phase 4 nano-banana thumbnails. (Phase 5 — Google Doc creation + email — runs entirely in the frontend; no BE-side Resend setup needed.)

## Quick Start

```bash
# 1. Install
git clone https://github.com/dg-eng/super-research-backend.git
cd super-research-backend
pip install -r requirements.txt
python -m patchright install chrome    # downloads patchright's stealth Chrome wrapper

# 2. Drop in the Firebase Admin key (emailed to you by the dev).
#    The email attachment will have an auto-generated name like
#    "super-research-492814-firebase-adminsdk-fbsvc-XXXXX.json".
#    Save it into THIS directory and RENAME it exactly:
#       firebase-service-account.json
#    Step-by-step + verify command in "Firebase Admin Key" below.

# 3. Pair (one-time: mints ResearchToken, renders QR, waits for logins)
python research.py --pair

# 4. Start the server (keep it running)
python research.py --serve

# 4a. (Optional, recommended) Survive reboots + crashes (Windows only today).
python research.py --resurrect

# 4b. (Undo 4a) Disable On Startup — kills supervisor + serve, removes
#     the Scheduled Task, syncs the Firestore flag. Pairing stays.
python research.py --retire

# 4c. (Full disconnect) Clean teardown — also wipes pairing/device
#     registry. Use this when you're done with this PC entirely.
python research.py --unpair
```

That's it. Four commands to a hands-off always-on backend — plus `--retire` to disable On Startup or `--unpair` to fully disconnect this PC.

> **Just want to smoke-test from the terminal first?** Skip pairing entirely and run `python research.py "your topic"` — see [§ CLI Mode](#cli-mode). No QR, no Firebase round-trip, output lands in `queues/`.

> **Order of ops — what you can do in parallel:**
> - Steps 1 (install) and 2 (env vars) can run alongside waiting for the Firebase Admin email.
> - You're **blocked** on the Firebase email before you can run Step 3 (`--pair`).
> - You're **blocked** on the web app account before Stage 2 of `--pair` (link the token).

## Firebase Admin Key (required) — `firebase-service-account.json`

The backend needs a Firebase Admin SDK key to read the queue, write heartbeats, and stream events. **This file is NOT committed to git and never will be.**

### How to get it

The dev will email you the JSON file directly. One file per person. The attachment will have an auto-generated name from the Firebase Console — typically:

```
super-research-492814-firebase-adminsdk-fbsvc-XXXXX.json
```

You **must rename it** to exactly `firebase-service-account.json` (the BE looks for that exact filename — no auto-detect) and place it in the **repo root** (the directory that contains `research.py`).

### Where it goes (exact path)

The repo root is whatever directory you `cd` into after `git clone`. For the org repo it's:

```
super-research-backend/firebase-service-account.json
```

Same directory as `research.py`. If you ever forked or renamed the directory, the file simply needs to be next to `research.py` — nothing else matters.

### Step-by-step (after `git clone` + `cd super-research-backend`)

**macOS / Linux:**
```bash
mv ~/Downloads/super-research-492814-firebase-adminsdk-fbsvc-*.json \
   ./firebase-service-account.json
ls -lh firebase-service-account.json   # should show ~2 KB
```

**Windows (PowerShell):**
```powershell
Move-Item "$HOME\Downloads\super-research-492814-firebase-adminsdk-fbsvc-*.json" `
          ".\firebase-service-account.json"
Get-Item .\firebase-service-account.json | Format-List Name,Length
```

**Windows (Git Bash / WSL):**
```bash
mv "/c/Users/$USER/Downloads/super-research-492814-firebase-adminsdk-fbsvc-"*.json \
   ./firebase-service-account.json
ls -lh firebase-service-account.json
```

If you have multiple matching files in Downloads (you may have re-downloaded), the wildcard might match >1 — copy the most recent one explicitly instead.

### Verify it landed correctly

```bash
# From the repo root:
ls firebase-service-account.json
# OR on Windows PowerShell:
Test-Path .\firebase-service-account.json
```

Open the file in any editor — it should be valid JSON starting with `{ "type": "service_account", ...`. If the file is HTML or empty, the email attachment didn't save correctly.

### Safety

- The `.gitignore` is pre-configured: this filename can never accidentally land in a commit, even with `git add -A`.
- Don't email the file onward, don't commit it, don't paste it into Slack. One file per person.
- If you suspect the key is compromised, email the dev — keys can be rotated in the Firebase Console.

### What happens if it's missing or wrong

Both `--pair` and `--serve` fail loudly on startup with the path they tried to load:

```
[FATAL] firebase-service-account.json not found at /path/to/super-research-backend/firebase-service-account.json
        Email the dev for the file. See README → "Firebase Admin Key".
```

> **Coming in the next update:** a proper pairing-time token exchange so new users self-onboard without the admin key at all (see `PairingRecipe.md` for the spec). Until then, email flow stays.

## Setup Details

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
python -m patchright install chrome
```

Requires **Python 3.11+** and a working **real Google Chrome** install. `research.py` launches via `patchright` (a stealth Playwright fork) with `channel="chrome"` — it uses your installed Chrome binary, NOT bundled Chromium, so anti-bot heuristics see a real browser fingerprint.

If Chrome itself isn't installed, install it first:
- **Windows:** [google.com/chrome](https://www.google.com/chrome/) → run the installer.
- **macOS:** `brew install --cask google-chrome` (or download from google.com/chrome).
- **Linux (Debian/Ubuntu):** `sudo apt-get install google-chrome-stable` (after adding Google's apt repo) or download the `.deb` from google.com/chrome.
- **Linux (Fedora/RHEL):** `sudo dnf install google-chrome-stable` (after adding the repo) or `.rpm` from google.com/chrome.

`python -m patchright install chrome` then downloads the stealth wrapper that drives that Chrome. Do this once on every machine.

`qrcode>=7.4` is already listed — the pair flow renders a scannable QR in your terminal.

### Step 2: Environment

Set your Anthropic API key (required for browser automation):

```bash
# Windows (PowerShell)
[System.Environment]::SetEnvironmentVariable("CUA_API_KEY", "sk-ant-...", "User")

# macOS/Linux
export CUA_API_KEY="sk-ant-..."
```

**`ANTHROPIC_API_KEY` is accepted as a fallback** — `resolve_api_key()` (research.py:181) checks `CUA_API_KEY` first, then `ANTHROPIC_API_KEY`, on both env and Windows User scope. Most Anthropic devs already have `ANTHROPIC_API_KEY` set globally, so it just works without setting a duplicate.

`GEMINI_API_KEY` is **optional** — required only for Phase 4 nano-banana thumbnail generation. If unset, Phase 4 still uploads the audio video; the thumbnail step skips with a warning. (Same canonical wording in the env-var table below.)

**Phase 5 (Google Doc + email) is FE-owned.** No BE setup needed. The frontend creates the Google Doc via the Docs API and sends the email via Resend, both using the deployment's own service account + Resend key — see the FE README for that side's env vars (`RESEND_API_KEY`, `NOTIFY_FROM_EMAIL`).

`BUG_REPORT_EMAIL` is optional — see the env-var table.

### Step 3: Run pair flow

```bash
python research.py --pair
```

The flow has **four** gated stages — each waits for the previous to confirm before advancing:

**`[1/4] Research token`**
Mints a new ResearchToken (UUID) or reuses the one in `research_config.json`. The token registers in Firestore (`research_tokens/{token}`) with `status: active`, `machineName`, `createdAt`, `lastHeartbeat`. The token is printed and an ASCII QR renders immediately below it. Delete `research_config.json` if you want to mint a fresh one. **Stage 2 is gated on the token being linked from the web app.**

**`[2/4] Link token to your app account` — this gate blocks the rest**
The flow waits (polling Firestore every 3s) until your app actually links the token to an authenticated user. Two equally-good ways:
- **Scan** — in the Super Research app: chat → *Connect* bubble → *Scan QR* button, OR Account → Pipeline Connection → small QR icon beside the paste field. Point the phone camera at the terminal QR.
- **Paste** — copy the token line printed above the QR and paste it into Account → Pipeline Connection → *Paste your ResearchToken* → *Link*.

> **Don't have a web app account yet?** The Super Research app lives at the deployment URL the dev shares with you (Google sign-in only). If you weren't invited yet, ping the dev. The app is required for stages 2 and 3 — `--pair` will sit on its polling loop until you link.

Once the app writes the token to your `users/{uid}/settings.researchToken` field, the flow resolves your email via Firebase Auth and prints `[ok] Linked — you@example.com`. Default link timeout is 10 minutes.

**`[3/4] On Startup` — supervised auto-restart prompt (Windows-only today)**
After the link lands, `--pair` prompts:

```
Enable On Startup? [Y/n]:
```

- **`Y` (default)** — calls `--resurrect` inline, registers the Windows Scheduled Task, and the backend self-restarts on every reboot / crash. Equivalent to running `python research.py --resurrect` after `--pair` finishes. Windows-only; on macOS/Linux this prompt skips with a "supported on Windows today" notice.
- **`n`** — skip; you'll run `python research.py --serve` manually after `--pair` finishes (and, on Linux/Mac, set up your own backgrounding via `nohup` / `tmux` / `screen` / your own systemd unit — see [§ Linux/Mac backgrounding](#linuxmac-backgrounding-while-track-c-is-still-pending)).

**`[4/4] Platform logins`**
Opens 5 browser tabs in a persistent Playwright profile and auto-verifies login state every 30 seconds:
- ChatGPT (chatgpt.com)
- Gemini (gemini.google.com)
- Claude (claude.ai)
- NotebookLM (notebooklm.google.com)
- YouTube Studio (studio.youtube.com)

> Phase 5 (Doc + email) runs in the frontend now, so Gmail and Google Docs are no longer in the BE login checklist.

The checklist re-renders only when a platform flips — `[ok]` for logged in, `[  ]` for not yet. It also mirrors the live state to Firestore (`research_tokens/{token}.logins`, `setupState`) so the app can show your progress. Default timeout is 10 minutes; Ctrl+C cancels.

> **Markers only tick after real auth.** `verify_login()` checks only auth-specific DOM (profile menus, account chips, chat-history lists). Generic chat-input elements are excluded because they show up on logged-out landing pages too.

### Step 4: After pair succeeds

When all 5 are `[ok]`, the flow:

1. Closes the browser
2. Writes `research_config.json` locally (if not already present)
3. Keeps the token registered in Firestore
4. **Exits the Python process — pair does not stay running.**

You'll see a final banner explaining this:
```
PAIR COMPLETE — all 5 platforms verified.

What happens now:
  · Browser has been closed.
  · ResearchToken is saved locally AND registered with Firebase.
  · This process will exit; pair does not stay running.

Next step — start the server:
    python research.py --serve
```

### Step 5: Start the Server

```bash
python research.py --serve
```

The server runs on port 8000 with:
- A **30s heartbeat** → updates `research_tokens/{token}.lastHeartbeat` AND the paired `users/{uid}/devices/{deviceId}.lastHeartbeat` so the app's Account page and sidebar device switcher both show the right online/offline dot.
- A **token-doc watcher** for sub-second relink: if you unlink this device from the app and paste the token back, the device tile reappears in well under a second instead of waiting up to 30s for the next heartbeat to self-heal it.
- A **Firestore queue listener** — picks up jobs from `research_tokens/{token}/queue/`. Single-worker per backend: if you fire a second topic on the same PC while the first is running, the second lands in an explicit `queued` state (with a chat banner + Cancel button in the app) until the first finishes.
- A **command listener** for stop / pause / resume / config / add_context / agent_decision / **continue_anyway** / **retry_phase** / **skip_phase**.
- A **local HTTP API** on `http://localhost:8000` for the CLI + any direct calls.

Keep `--serve` running while you use the app. If the server stops, the web app's 60s watchdog detects it, marks running tiles as stopped, and prevents a reload from resurrecting the pipeline.

**Queue persistence across restarts** — on `--serve` startup, the backend re-enqueues any `status:"queued"` researches from Firestore, so the queue survives a `--daemon-loop` respawn. Anything that was `status:"ongoing"` when the previous process died is flipped to `paused_backend_restart` (with a "Resume from checkpoint?" warn alert in the FE), instead of appearing live-but-frozen. If the persist itself fails (Firestore unavailable on respawn), affected researches surface a `paused_backend_restart_failed` red error with the actual error string.

### Step 5a (optional, recommended): Enable On Startup (supervised auto-restart)

```bash
python research.py --resurrect
```

Registers a Windows Scheduled Task that runs a **daemon-loop wrapper** — a tiny supervisor process that (re-)starts `--serve` whenever it exits for any reason: crash, stop button, logout, reboot, etc. The task is set to ONLOGON + AT STARTUP with unlimited duration, so the backend is effectively always-on while the PC is powered.

The Account page's **Indestructible** toggle reflects the real scheduled task state (`schtasks /Query`), so the toggle survives unlink+relink. Turn it off from the same page if you ever want to stop auto-restart.

> **Cross-platform supervisors** — macOS launchd + Linux systemd-user equivalents are coming shortly. Until they ship, `--resurrect` is a no-op outside Windows; use the manual stop-gaps below.

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

**Linux — `systemd --user` (DIY for now; native supervisor coming shortly):**
```ini
# ~/.config/systemd/user/superresearch.service
[Unit]
Description=Super Research backend
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=%h/super-research-backend
ExecStart=/usr/bin/python3 %h/super-research-backend/research.py --serve
Restart=always
RestartSec=10
Environment=CUA_API_KEY=sk-ant-...

[Install]
WantedBy=default.target
```
Then: `loginctl enable-linger $USER && systemctl --user daemon-reload && systemctl --user enable --now superresearch.service`. (The native supervisor coming shortly will install all this for you automatically.)

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

### Step 5c (full disconnect): `--unpair`

```bash
python research.py --unpair
```

The "I'm done with this PC" command — wipes everything `--retire` wipes, AND removes the device from the registry. After `--unpair`, this PC appears NOWHERE in the Super Research app's device list.

Four-step:

1. **Process kill + Scheduled Task removal** (always runs Step 1 regardless of pairing state, so partial-pairing scenarios clean up correctly).
2. **Removes the device doc** from `users/{uid}/devices/{deviceId}`.
3. **Wipes `research_config.json` + `device_config.json`** locally.
4. **Final-state verification** — if anything survived, prints the surviving PIDs so you can taskkill manually.

To bring this PC back: re-run `--pair` to mint a fresh ResearchToken and re-pair with your account.

### Step 6: Fire a research topic in the app

Open Super Research (the web app) → type a topic → backend picks it up from Firestore → pipeline runs here. If the app says "No backend connected" there's a Connect bubble with a Scan QR button that links in seconds.

## Multiple Devices (same user)

One account can pair multiple PCs. Each `--pair` on a new machine registers its own `users/{uid}/devices/{deviceId}` doc. The app's sidebar gets a device switcher (with online/offline dots) and every research is stamped with the device it ran on — so jobs you fire from the app route back to the specific PC that was **active** when you hit Start. If you fire two jobs on the same device while one is running, the second queues; if you fire one on a different device, both run in parallel.

## Multiple Users (same backend)

Multiple people can also share one backend. Share your ResearchToken — they paste it in their own Account settings. Per-user scoping happens via Firestore security rules; the backend just drains the shared queue.

## Pipeline Phases

| Phase | Platform | Typical Time |
|-------|----------|------|
| 0. Init | System (browser launch + login check) | ~10s |
| 1. Brief | ChatGPT Pro + Extended Thinking | ~25 min |
| 2. Research | ChatGPT + Gemini + Claude (parallel) | ~49 min |
| 3. Podcast | NotebookLM (upload + audio generation) | ~25 min |
| 4. YouTube | YouTube Studio (video render + upload) | ~9 min |
| 5. Report | Google Doc + email delivery (FE-owned: Docs API + Resend) | ~3 min |

Times based on real run analytics. Total: ~1h 50m for a full pipeline. ChatGPT Pro, Claude Pro, and Gemini Advanced are the assumed baseline — see [Before you start](#before-you-start-prerequisites-checklist) for per-seat costs. Phase 0 vision-checks each platform's tier after login-verify and hard-flags non-Pro accounts with `[Continue with Free] [Retry]` before Phase 1 starts; Retry re-verifies after you sign in with a Pro account in the same browser. If you `Continue with Free` (or have Phase 0 verification disabled in Settings), the pipeline runs end-to-end on Free tiers, but Deep Research depth, image quality, and turn limits are far lower than what the per-agent timings, prompts, and waits were tuned against, so per-agent output is much shallower.

## Phase + per-agent narration (consolidated 2026-04-30)

Long quiet stretches in Phases 1–3 are expected (ChatGPT Pro thinks for ~3 min before writing, NotebookLM renders for 5–15 min), but a dead-looking tile makes the whole app feel broken even when nothing's wrong. The narration system was consolidated 2026-04-30 from four overlapping writers down to a single per-agent narrator with a backend-fallback tail. Result: cheaper, less duplication, less parroting.

- **Per-agent narrator (the only writer now)** — every Phase 1/2 agent has a narrator worker that reads a bounded ring buffer of recent events (~50) and emits a `phase_narration` / `agent_narration` event about every 6s per active agent. Brain: **Anthropic Haiku 4.5** primary (`claude-haiku-4-5`); **Gemini 2.5 Flash** fallback on any 4xx/5xx/timeout/empty response so workspace-usage-limit windows don't blank the narrator for 24+ hours. Pre-04-30 used Gemini Pro 2.5; Pro echoed input verbatim at temp 0.2 — Haiku follows the no-parrot prompt rules more tightly. Cost envelope: ~200 input / 30 output tokens per call → <$0.02 per full pipeline run on Haiku.
- **Anti-parroting prompt + chrome scrub.** The narrator system prompt (research.py:5904-5933) has explicit anti-pattern rules: don't echo input verbatim, don't start with "currently" or "Status:", skip chat-thread chrome (`You said:` / `Claude responded:` / `Gemini said` / `brief.md`). Above the narrator, `_compact_event_for_narration` (research.py:5550-5625) scrubs those same chrome strings out of the input window BEFORE the narrator sees them — scrape outputs (chip / step counts) are untouched.
- **DOM scrape rules per platform:** Claude scrape (research.py:7116-7124) is panel-scoped to `aside` / `[class*="artifact"]` / `[class*="research"]` — dropped `.font-claude-message` and `.contents` heading selectors that grabbed conversation-chrome. ChatGPT P2 panel walker (research.py:7979-7984) dropped the loose `[class*="row" i]` selector and added a 23-verb `VERB_GATE` regex with min-length raised 4→12 to drop "OK" / "Done" single-word noise.
- **Vision narrator (`gemini_narrate.py`) RETIRED.** `PHASE_BUDGET=0` by default — the per-agent narrator covers the same slot via DOM events without burning a separate Gemini call. Set `DG_VISION_NARRATE=1` to re-enable it as a coverage escape hatch.
- **BE phase-fallback tail.** When the narrator is silent (Haiku + Flash both failing, or 6s startup gap), research.py:9601-9604 emits `Extended Thinking active · 12,400 chars drafted` into `progress["progress"]`. The FE renders this as a final tail under the agent narration (PhaseDropdown.tsx:1880-1885). No more dead silence on a working agent.

> **Narration brain envs:** `DG_NARRATOR_USE_HAIKU` (default `1`; set `0` to skip Haiku and go straight to Flash), `DG_NARRATOR_HAIKU_MODEL` (default `claude-haiku-4-5`), `DG_VISION_NARRATE` (default `0`; set `1` to re-enable the retired vision narrator). All optional.

## Phase 0 verification (sequential, Apr 19; 2026-04-24 simplified)

Preflight walks platforms one at a time instead of opening all tabs at once. For each enabled platform:

1. **Tab open** — opens that one tab, waits 4s for SPA hydration, checks URL for known login hosts.
2. **CUA vision verification** if URL check is ambiguous.
3. **`login_required`** scoped to that ONE platform if still not logged in. Pause for user retry. The next platform does NOT open until the current one is resolved (Cloudflare stealth + less user overwhelm).

Cookie-only fast-path was removed 2026-04-24 — cookies lie when sessions are server-side invalidated. Phase 0 is now the only login gate; per-phase cookie probes were also removed. Mid-run session drift is caught by the active-platform CUA loop's session-expiry detector (2× consecutive confirms 2 min apart).

## Phase 2 — per-agent extraction rules (Apr 19 late-late)

Phase 2 enforces different link-extraction rules per platform. The right rule for each platform comes from how each service exposes authenticated conversations:

- **ChatGPT** — unchanged from Phase 1 brief behavior: public-share link extraction first, falls back to the conversation URL if the share flow fails. A conversation URL is acceptable because it's publicly readable to anyone with the link (shareable without explicit action).
- **Gemini + Claude** — **PUBLIC share links ONLY**, hard-fail on miss. No conversation-URL fallback — those URLs are private to the authenticated session and would fail silent-ticks downstream. If the share flow fails after 3× retries, the agent surfaces a Retry / Skip gate (matching the B1 link-first completion gate).

Every extraction method logs explicitly: `[gemini_extractor] method=X result=Y` (and equivalent per platform). Makes post-mortem debugging of "why did this agent not tick" trivial. `link_extracted` is emitted per agent the moment a verified link lands (no phase-end batching).

**Claude 2-artifact wait hard-fail.** If Claude has reached ≥80% of its allotted wait time AND has <2 artifacts in the side panel, the pipeline hard-fails that agent with Retry / Skip — no silent half-answer. First artifact is almost always a research plan, not the final report; accepting a single-artifact Claude as done produces a broken downstream.

**Tab round-robin — `target_page` anchoring.** `agent_loop` accepts a `target_page=None` parameter. Before every polling tick it calls `bring_to_front()` on that agent's tab so CUA always sees a live browser viewport, not a stale background capture from whichever tab happened to be front when three agents were racing. `_anchored_screenshot()` helper handles the pattern; re-anchors after every `execute_action` too. Prevents cross-agent tab interference — e.g. Gemini's vision call returning Claude's screenshot because Claude's tab happened to be front-of-stack when the capture fired.

**Claude setup via Playwright (not CUA).** `setup_claude_dr` was rewritten as 3 Playwright steps — select Opus 4.7 from the model dropdown, toggle Adaptive Thinking, enable the Research tool — all DOM selectors + `.click()` calls. Eliminates ~30-90s of CUA vision overhead per setup and removes a class of "CUA clicked the wrong thing" setup failures. CUA is still used mid-run for anything that isn't deterministic DOM.

## Per-phase alert narration

Every failure category — timeouts, CUA fallbacks, Anthropic 429/529 retries, share-link misses, login-expired, ffmpeg failures, email auth problems, browser crashes, and more — emits into the correct phase's `PhaseAlertPanel` inside the app's phase dropdown. No chat-bubble spam. Per-phase coverage:

- **Phase 0** — browser launch/crash, Playwright profile lock, missing Chromium binary
- **Phase 1** — brief timeout, brief paste retry per attempt, brief-short (offers `continue_anyway`), brief model error, manual-brief 3h backstop (auto-fail with `pipeline_stopped` reason `manual_brief_wait_backstop_3h`)
- **Phase 2** — agent timeout (auto-skip with partial save if ≥200 chars; no human prompt needed since 2026-04-30 `be8f7b3`), send-button CUA fallback, paste outer-retry narration, full HV (human-verification) stage narration: detected → auto-clear 1/2 → 3 min cooldown → retry 2/2 → success/fail with Resume/Skip. HV cooldown is 180s (was 45s — providers need the time to release holds). Browser crashes auto-retry with a passive recovery banner; no Retry/Skip prompt.
- **Phase 3** — per-agent share-link extraction failure, NotebookLM login-expired vs generic upload failure, "no MD files" gate, inter-phase gate (P2 produced no documents). Derived stems (`brief.md`, `consolidated.md`) are excluded from NotebookLM uploads via `_DERIVED_STEMS` filter (research.py:14627) — never uploads consolidated.md.
- **Phase 4** — audio skip via command, poll-budget timeout, download-event timeout + fallback + final fail, Firebase Storage upload as best-effort (warning, not fatal)
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

| Variable | Default | Description |
|----------|---------|-------------|
| `CUA_API_KEY` | (required) | Anthropic API key for browser automation. `ANTHROPIC_API_KEY` is also accepted as a fallback (research.py:181). |
| `ANTHROPIC_API_KEY` | (fallback for `CUA_API_KEY`) | Standard Anthropic env var; auto-detected if `CUA_API_KEY` isn't set. Also drives the narrator's Haiku 4.5 primary brain. |
| `RESEARCH_TOKEN` | (from pair) | Override ResearchToken (for Docker/CI) |
| `CUA_MODEL` | `claude-opus-4-7` | Claude model for CUA |
| `CUA_SCREEN_WIDTH` | `1280` | Browser viewport width |
| `CUA_SCREEN_HEIGHT` | `800` | Browser viewport height |
| `GEMINI_API_KEY` | (optional; required only for Phase 4 nano-banana thumbnail generation) | Gemini API key. Phase 4 still uploads audio video without it; only the thumbnail step skips. Also used as the narrator's Flash fallback when Haiku is unavailable. |
| `MAX_WAIT_DEEP` | `90` | Max minutes to wait per Phase 2 agent |
| `POLL_DEEP_RESEARCH` | `30` | Seconds between polling cycles |
| `MIN_AGENT_WAIT_MIN` | `20` | Min minutes before CUA completion checks |
| `BUG_REPORT_EMAIL` | (optional) | Where bug-report submissions land if FE bug-report uses the BE relay. FE has its own `BUG_REPORT_EMAIL` env on `/api/bug` — see FE README. |
| `DG_NARRATOR_USE_HAIKU` | `1` | Enable Anthropic Haiku 4.5 as the narrator primary (Gemini Flash as fallback). Set `0` to use Flash directly. |
| `DG_NARRATOR_HAIKU_MODEL` | `claude-haiku-4-5` | Haiku model id for the narrator. |
| `DG_VISION_NARRATE` | `0` | Re-enable the retired vision narrator (`gemini_narrate.py`, `PHASE_BUDGET=80/phase`). Set `1` if a coverage gap appears in DOM-derived narration. |
| `DG_ORPHAN_MAX_AGE_HOURS` | `4` | Cutoff age for `--retire`'s "manual one-off `--serve` runs" preservation. |

## File Structure

```
research-automate/
├── research.py                 # Pipeline + FastAPI server
├── prompts.py                  # CUA prompts for each phase
├── vision.py                   # Anthropic Sonnet vision client (tier-2 acting): take_screenshot, vision_action, with_vision_fallback, shadow_observe_then_cua
├── gemini_narrate.py           # Vision-tier panel narrator (PHASE_BUDGET=0 by default; retired 2026-04-30 — re-enable via DG_VISION_NARRATE=1)
├── vision_test.py              # Fixture replay tool: --capture saves PNG+JSON, --fixtures replays + asserts action-class agreement + bbox containment
├── requirements.txt            # Python dependencies (now includes patchright>=1.59)
├── firebase-service-account.json  # Firebase connection (not committed)
├── research_config.json        # Your ResearchToken (generated by --pair)
├── run_analytics.json          # Historical phase durations (auto-updated)
├── ARCHITECTURE.md             # Backend architecture + Frontend ↔ Backend API contract
├── scratch/                    # (gitignored) Internal dev notes + wire-in plans
├── scripts/
│   ├── run_supervisor.cmd      # CMD wrapper for the daemon-loop (env-var inheritance + Scheduled Task entry point)
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

**`ModuleNotFoundError: No module named 'patchright'`** — Run `pip install -r requirements.txt` again (patchright was added 2026-04-30 as `patchright>=1.59`). Then `python -m patchright install chrome`.

**`patchright` launches but Chrome doesn't open** — Patchright launches with `channel="chrome"` (real Chrome, not bundled Chromium). If real Chrome isn't installed on this machine, install it from google.com/chrome (Windows), `brew install --cask google-chrome` (macOS), or your distro's Chrome package (Linux).

**Backend shows "Offline" in the web app** — Make sure `python research.py --serve` is running. The heartbeat updates every 30 seconds.

**"Backend did not respond within 15s"** — The backend may be busy with another research. Check the queue: `GET http://localhost:8000/api/queue`.

**Browser sessions expired** — Re-run `python research.py --pair` to log in again.

**NotebookLM login expired mid-run** — Surfaces as a Phase 3 alert with `login_expired` detail (distinct from generic upload failure). Re-run `--pair` to refresh that session; hit `[Skip]` on the alert if you want to move past Phase 3 and still get Phase 5 report/email.

**Anthropic 429 / 529 (rate-limit or overload)** — Retries automatically with narration in the current phase dropdown; usually self-resolves within one or two attempts.

**Anthropic API key invalid (401) — narrator goes silent** — The narrator falls through to Gemini 2.5 Flash on any Haiku error including 401. You'll see narration keep flowing (Flash-driven) but the BE log shows `[narrator] Haiku failed sc=401 — falling back to Gemini Flash` once. CUA itself ALSO needs a working Anthropic key — if the key is fully revoked, CUA tier-3 stops working and the pipeline relies on Playwright tier-1 / Vision tier-2 only. Check your Anthropic billing/keys page.

**Anthropic workspace usage limit hit (CUA 400)** — Same fallback semantics as 401: narrator routes to Flash; CUA tier-3 is unavailable until the limit window resets (typically 24h). Pipeline keeps running on Playwright + Vision; specific platform actions that require CUA (e.g. some HV captcha clicks) may need manual help via the FE alerts.

**Phase 4 audio failed but Phase 5 still matters** — Hit `[Skip]` on the Phase 4 alert (writes `skip_phase phase=4`); Phase 5 YouTube + Email proceed normally.

**FE shows `paused_backend_restart_failed` red banner** — Backend tried to persist the in-flight queue on shutdown but the Firestore write failed. The `lastError` field on the research doc has the actual exception. Restart `--serve`; affected runs are kept on disk in `queues/` and can be resumed via the FE checkpoint banner once BE is back online.

**CLI mode pause hangs (no web app)** — `python research.py "topic"` running standalone (without `--serve`) cannot use the app's Skip/Retry buttons. When Phase 0 emits `login_required` (or any other pause), the terminal prints a recovery menu:

```
[PAUSE] login_required — log in via the open browser, then:
  r) resume   s) skip phase   q) stop pipeline
```

Complete the login in the open Chrome window, then type `r` + Enter to resume. `s` skips the current phase; `q` stops cleanly. Useful for headless rigs and onboarding before the web app is available. The menu only accepts input when stdin is a TTY — piped/Task-Scheduler runs print the menu but ignore typed input.

---

Built for Distributed Global.
