# Super Research — Backend Pipeline

Automates multi-agent deep research across 6 platforms. Tiered automation: Playwright (primary) → Vision (Anthropic Sonnet via `vision.py`, tier-2) → Claude Computer Use (tier-3 fallback).

> **Jira:** [DGOPS-6933](https://distributedglobal.atlassian.net/browse/DGOPS-6933)
> **Repo (this one):** github.com/dg-eng/super-research-backend
>
> The Firebase Admin SDK key (`firebase-service-account.json`) is **gitignored**
> and emailed separately by the dev — see ["Firebase Admin Key" below](#firebase-admin-key-required--firebase-service-accountjson).

## Quick Start

```bash
# 1. Install
git clone https://github.com/dg-eng/super-research-backend.git
cd super-research-backend
pip install -r requirements.txt

# 2. Drop in the Firebase Admin key (emailed to you by the dev).
#    The email attachment will have an auto-generated name like
#    "super-research-492814-firebase-adminsdk-fbsvc-XXXXX.json".
#    Save it into THIS directory and RENAME it exactly:
#       firebase-service-account.json
#    Step-by-step + verify command in "Firebase Admin Key" below.

# 3. Setup (one-time: mints ResearchToken, renders QR, waits for logins)
python research.py --pair

# 4. Start the server (keep it running)
python research.py --serve

# 4a. (Optional, recommended) Survive reboots + crashes.
python research.py --resurrect

# 4b. (Undo 4a) Disable On Startup — kills supervisor + serve, removes
#     the Scheduled Task, syncs the Firestore flag. Pairing stays.
python research.py --retire

# 4c. (Full disconnect) Clean teardown — also wipes pairing/device
#     registry. Use this when you're done with this PC entirely.
python research.py --unpair
```

That's it. Four commands to a hands-off always-on backend — plus `--retire` to disable On Startup or `--unpair` to fully disconnect this PC.

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

> **Coming in the next update:** a proper pairing-time token exchange so new users self-onboard without the admin key at all. Until then, email flow stays.

## Setup Details

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

Requires **Python 3.11+** and a working Chrome/Chromium installation.

Playwright auto-downloads its bundled Chromium on first run — no separate `playwright install` step needed on Windows, but you may run it if installation lands in an unexpected profile dir:
```bash
python -m playwright install chromium
```

`qrcode>=7.4` is already listed — the setup flow renders a scannable QR in your terminal.

### Step 2: Environment

Set your Anthropic API key (required for browser automation):

```bash
# Windows (PowerShell)
[System.Environment]::SetEnvironmentVariable("CUA_API_KEY", "sk-ant-...", "User")

# macOS/Linux
export CUA_API_KEY="sk-ant-..."
```

Optional: `GEMINI_API_KEY` for nano-banana thumbnail generation in Phase 4.

### Step 3: Run Setup

```bash
python research.py --pair
```

The flow has three gated stages — each waits for the previous to confirm before advancing:

**`[1/3] Research token`**
Mints a new ResearchToken (UUID) or reuses the one in `research_config.json`. The token registers in Firestore (`research_tokens/{token}`) with `status: active`, `machineName`, `createdAt`, `lastHeartbeat`. The token is printed and an ASCII QR renders immediately below it. Delete `research_config.json` if you want to mint a fresh one.

**`[2/3] Link token to your app account` — this gate blocks step 3**
Setup waits (polling Firestore every 3s) until your app actually links the token to an authenticated user. Two equally-good ways:
- **Scan** — in the Super Research app: chat → *Connect* bubble → *Scan QR* button, OR Account → Pipeline Connection → small QR icon beside the paste field. Point the phone camera at the terminal QR.
- **Paste** — copy the token line printed above the QR and paste it into Account → Pipeline Connection → *Paste your ResearchToken* → *Link*.

Once the app writes the token to your `users/{uid}/settings.researchToken` field, setup resolves your email via Firebase Auth and prints `[ok] Linked — you@example.com`. Only then does step 3 begin. Default timeout is 10 minutes.

**`[3/3] Platform logins`**
Opens 7 browser tabs in a persistent Playwright profile and auto-verifies login state every 30 seconds:
- ChatGPT (chatgpt.com)
- Gemini (gemini.google.com)
- Claude (claude.ai)
- NotebookLM (notebooklm.google.com)
- YouTube Studio (studio.youtube.com)
- Gmail (mail.google.com)
- Google Docs (docs.google.com)

The checklist re-renders only when a platform flips — `[ok]` for logged in, `[  ]` for not yet. It also mirrors the live state to Firestore (`research_tokens/{token}.logins`, `setupState`) so the app can show your progress. Default timeout is 10 minutes; Ctrl+C cancels.

> **Markers only tick after real auth.** `verify_login()` checks only auth-specific DOM (profile menus, account chips, chat-history lists). Generic chat-input elements are excluded because they show up on logged-out landing pages too.

### Step 4: After setup succeeds

When all 7 are `[ok]`, setup:

1. Closes the browser
2. Writes `research_config.json` locally (if not already present)
3. Keeps the token registered in Firestore
4. **Exits the Python process — setup does not stay running.**

You'll see a final banner explaining this:
```
SETUP COMPLETE — all 7 platforms verified.

What happens now:
  · Browser has been closed.
  · ResearchToken is saved locally AND registered with Firebase.
  · This process will exit; setup does not stay running.

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

**Queue persistence across restarts** — on `--serve` startup, the backend re-enqueues any `status:"queued"` researches from Firestore, so the queue survives a `--daemon-loop` respawn. Anything that was `status:"ongoing"` when the previous process died is flipped to `stopped` with a "Backend restarted mid-run" message, instead of appearing live-but-frozen.

### Step 5a (optional, recommended): Enable On Startup (supervised auto-restart)

```bash
python research.py --resurrect
```

Registers a Windows Scheduled Task that runs a **daemon-loop wrapper** — a tiny supervisor process that (re-)starts `--serve` whenever it exits for any reason: crash, stop button, logout, reboot, etc. The task is set to ONLOGON + AT STARTUP with unlimited duration, so the backend is effectively always-on while the PC is powered.

The Account page's **Indestructible** toggle reflects the real scheduled task state (`schtasks /Query`), so the toggle survives unlink+relink. Turn it off from the same page if you ever want to stop auto-restart.

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
| 5. Report | Google Docs (Playwright DOM) + Resend (HTTP API) (delivery) | ~3 min |

Times based on real run analytics. Total: ~1h 50m for a full pipeline.

## Phase + per-agent narration (backend Gemini Flash, two layers)

Long quiet stretches in Phases 1–3 are expected (ChatGPT Pro thinks for ~3 min before writing, NotebookLM renders for 5–15 min), but a dead-looking tile makes the whole app feel broken even when nothing's wrong. Apr 19 + Apr 26 ship a two-layer narration system so there's always a visible human-language pulse:

- **Phase narrator (Gemini 2.5 Pro inside `research.py`)** — every active phase has a narrator worker that reads a bounded ring buffer of recent events (~40) and emits a `phase_narration` event about every 45s. Narrator warms on `phase_start`, stays quiet during `pipeline_paused`, tears down on `phase_complete` / `pipeline_stopped`. Cost envelope: ~200 input / 30 output tokens per narration → <$0.02 per full pipeline run.
- **Per-agent narrator (Gemini 2.5 Pro inside `gemini_narrate.py`)** — separate module, separate cadence. Each Phase 1/2 agent has a narrator that reads the right-side activity panel directly via Gemini 2.5 Pro vision (screenshot-and-OCR). DOM-walker output is the primary; vision narrator fires when the walker yields nothing AND the panel is non-empty (typical case: ChatGPT Pro "Extended Thinking active" gap), or every 4th poll for a richer rolling sentence. New `agent_progress` fields: `scrapeSource: "dom" | "vision"` records which tier produced the data; `visionNarration` carries the human-readable sentence rendered verbatim in the agent dropdown. Hard caps: 30 calls per phase, 90s minimum gap per agent.
- **Backend-down detection** — the LivenessEye title swap in the phase header signals quiet-but-alive vs. potentially-dead. Past the per-phase T2 silence threshold the watchdog surfaces a Dismiss-only warn dropdown alert + OS notification; the pipeline keeps running while the autonomous tier framework (BE TierEscalation, Apr 28) recovers. T3 silence raises an informational dropdown alert without auto-stopping the run.

## Phase 0 verification (sequential, Apr 19)

Preflight now walks platforms one at a time instead of opening 7 tabs at once. For each enabled platform:

1. `cookie_login_hit()` reads the persistent profile's cookie store for that platform's primary session token. Hit → emit `agent_progress status=ok` and move on. No tab, no network, no CUA.
2. Cookie miss → open that one tab, wait 4s for SPA hydration, check URL for known login hosts.
3. Still ambiguous → CUA vision verification.
4. Still not logged in → emit `login_required` **scoped to that single platform** and pause for user retry. The next platform does NOT open until the current one is resolved (Cloudflare stealth + less user overwhelm).

Matches the `--pair` script's one-at-a-time walk that's been working well for months. Global "Skip verification" still bypasses the whole sequence. Per-phase login checks at every subsequent phase are cookie-only (no tabs, no CUA) — they catch mid-run session drift without re-opening anything.

## Phase 2 — per-agent extraction rules (Apr 19 late-late)

Phase 2 now enforces different link-extraction rules per platform. The right rule for each platform comes from how each service exposes authenticated conversations:

- **ChatGPT** — unchanged from Phase 1 brief behavior: public-share link extraction first, falls back to the conversation URL if the share flow fails. A conversation URL is acceptable because it's publicly readable to anyone with the link (shareable without explicit action).
- **Gemini + Claude** — **PUBLIC share links ONLY**, hard-fail on miss. No conversation-URL fallback — those URLs are private to the authenticated session and would fail silent-ticks downstream. If the share flow fails after 3× retries, the agent surfaces a Retry / Skip gate (matching the B1 link-first completion gate).

Every extraction method logs explicitly: `[gemini_extractor] method=X result=Y` (and equivalent per platform). Makes post-mortem debugging of "why did this agent not tick" trivial. `link_extracted` is emitted per agent the moment a verified link lands (no phase-end batching).

**Claude 2-artifact wait hard-fail.** If Claude has reached ≥80% of its allotted wait time AND has <2 artifacts in the side panel, the pipeline hard-fails that agent with Retry / Skip — no silent half-answer. First artifact is almost always a research plan, not the final report; accepting a single-artifact Claude as done produces a broken downstream.

**Tab round-robin — `target_page` anchoring.** `agent_loop` now accepts a `target_page=None` parameter. Before every polling tick it calls `bring_to_front()` on that agent's tab so CUA always sees a live browser viewport, not a stale background capture from whichever tab happened to be front when three agents were racing. `_anchored_screenshot()` helper handles the pattern; re-anchors after every `execute_action` too. Prevents cross-agent tab interference — e.g. Gemini's vision call returning Claude's screenshot because Claude's tab happened to be front-of-stack when the capture fired.

**Claude setup via Playwright (not CUA).** `setup_claude_dr` was rewritten as 3 Playwright steps — select Opus 4.7 from the model dropdown, toggle Adaptive Thinking, enable the Research tool — all DOM selectors + `.click()` calls. Eliminates ~30-90s of CUA vision overhead per setup and removes a class of "CUA clicked the wrong thing" setup failures. CUA is still used mid-run for anything that isn't deterministic DOM.

## Per-phase alert narration

Every failure category — timeouts, CUA fallbacks, Anthropic 429/529 retries, share-link misses, login-expired, ffmpeg failures, email auth problems, and more — emits into the correct phase's `PhaseAlertPanel` inside the app's phase dropdown. No chat-bubble spam. Per-phase coverage:

- **Phase 0** — browser launch/crash, Playwright profile lock, missing Chromium binary
- **Phase 1** — brief timeout, brief paste retry per attempt, brief-short (offers `continue_anyway`), brief model error
- **Phase 2** — 90-min timeout with live source count, send-button CUA fallback, paste outer-retry narration, full HV (human-verification) stage narration: detected → auto-clear 1/2 → 3 min cooldown → retry 2/2 → success/fail with Resume/Skip. HV cooldown is 180s (was 45s — providers need the time to release holds)
- **Phase 3** — per-agent share-link extraction failure, NotebookLM login-expired vs generic upload failure, "no MD files" gate, inter-phase gate (P2 produced no documents)
- **Phase 4** — audio skip via command, poll-budget timeout, download-event timeout + fallback + final fail, Firebase Storage upload as best-effort (warning, not fatal)
- **Phase 5** — ffmpeg disk-full / not-found / generic, YouTube URL extract fail, Google Doc creation fail, email bad-address / Resend HTTP error, email skip via command
- **Cross-cutting** — Anthropic 429/529 narrate as retrying; other API errors surface as `pipeline_warning` on the current phase

Default action on every alert is `[Retry] [Skip]`. Skip writes the unified `skip_phase phase=N` command, replacing the old `skip_phase` / `skip_phase` verbs (removed in U2). Phase-specific alerts may add `HV Resume` or `continue_anyway`. **Stop is NOT a per-phase action** — pause/stop/resume stay global in the app's chat input bar.

### Error matrix (normalized, Apr 19 late-late)

The per-alert action set was consolidated to reduce noise and remove affordances that invited broken states:

- **Default everywhere: Retry · Skip.** Every failure surface offers this pair unless it's specifically overridden below.
- **Workspace cap hit in Phase 2 → `End research` only** (`action=stop`). No point retrying when the user is out of workspace slots; other phases keep Retry · Skip.
- **Poll timeout in Phase 2 → Retry · Skip · Wait** (Wait extends the agent's budget by 15 min). Only phase that gets a third option because "wait a little longer" is a frequently-correct user choice for Phase 2.
- **Removed the "Poke" button and "Proceed without CUA" options entirely.** Poke morphed into the normalized Retry (which in turn does the hard tab close+reopen from the Apr 19 early `retry_agent` work). "Proceed without CUA" let users walk into broken-state pipelines with no recovery path.
- **Stuck-agent buttons relabeled** to match the normalized vocabulary: Poke → **Retry**, "Wait longer" → **Wait**, "Skip agent" → **Skip**.

The backend's per-agent narrator runs alongside the phase narrator during P1/P2 — separate Gemini 2.5 Pro calls emit `agent_narration` events (one per active agent, ~6s cadence) that the frontend shows inside each agent row of the Phase 2 accordion. Cost bounded: ~200 in / 30 out per call × 3 agents × a few hundred seconds per run.

## CLI Mode

Run research directly from the terminal (no web app):

```bash
python research.py "Your research topic"
python research.py "Topic" --brief-file brief.txt     # Skip Phase 1
python research.py "Topic" --pdf paper.pdf             # Attach PDFs
python research.py --resume queue_name                 # Resume stopped run
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CUA_API_KEY` | (required) | Anthropic API key for browser automation |
| `RESEARCH_TOKEN` | (from setup) | Override ResearchToken (for Docker/CI) |
| `CUA_MODEL` | `claude-opus-4-7` | Claude model for CUA |
| `CUA_SCREEN_WIDTH` | `1280` | Browser viewport width |
| `CUA_SCREEN_HEIGHT` | `800` | Browser viewport height |
| `GEMINI_API_KEY` | (required for Phase 4) | Gemini API for nano-banana thumbnail generation |
| `MAX_WAIT_DEEP` | `90` | Max minutes to wait per Phase 2 agent |
| `POLL_DEEP_RESEARCH` | `30` | Seconds between polling cycles |
| `MIN_AGENT_WAIT_MIN` | `20` | Min minutes before CUA completion checks |

## File Structure

```
research-automate/
├── research.py                 # Pipeline + FastAPI server
├── prompts.py                  # CUA prompts for each phase
├── vision.py                   # Anthropic Sonnet vision client (tier-2 acting): take_screenshot, vision_action, with_vision_fallback, shadow_observe_then_cua
├── gemini_narrate.py           # Gemini Flash agent-side-panel narrator (tier-2 observing): narrate_panel reads the AI activity panel directly via screenshot
├── vision_test.py              # Fixture replay tool: --capture saves PNG+JSON, --fixtures replays + asserts action-class agreement + bbox containment
├── requirements.txt            # Python dependencies
├── firebase-service-account.json  # Firebase connection (not committed)
├── research_config.json        # Your ResearchToken (generated by --pair)
├── run_analytics.json          # Historical phase durations (auto-updated)
├── ARCHITECTURE.md             # Backend architecture + Frontend ↔ Backend API contract
├── scratch/                    # (gitignored) Vision hotspot map + Track A/B/C wire-in plan
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

**Backend shows "Offline" in the web app** — Make sure `python research.py --serve` is running. The heartbeat updates every 30 seconds.

**"Backend did not respond within 15s"** — The backend may be busy with another research. Check the queue: `GET http://localhost:8000/api/queue`.

**Browser sessions expired** — Re-run `python research.py --pair` to log in again.

**NotebookLM login expired mid-run** — Surfaces as a Phase 3 alert with `login_expired` detail (distinct from generic upload failure). Re-run `--pair` to refresh that session; hit `[Skip]` on the alert if you want to move past Phase 3 and still get Phase 5 report/email.

**Anthropic 429 / 529 (rate-limit or overload)** — Retries automatically with narration in the current phase dropdown; usually self-resolves within one or two attempts.

**Phase 4 audio failed but Phase 5 still matters** — Hit `[Skip]` on the Phase 4 alert (writes `skip_phase phase=4`); Phase 5 YouTube + Email proceed normally.

**Phase 5 email not sending** — Alert surfaces with the specific cause (bad recipient / Resend HTTP error / `RESEND_API_KEY` unset / unverified `NOTIFY_FROM_EMAIL` domain). Hit `[Skip]` (writes `skip_phase phase=5`) to skip email but still get the Google Doc link. Verify your domain on resend.com → set `RESEND_API_KEY` + `NOTIFY_FROM_EMAIL` in BE env → restart `--serve`.

---

Built for Distributed Global.
