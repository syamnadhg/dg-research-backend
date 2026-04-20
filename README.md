# Super Research — Backend Pipeline

Automates multi-agent deep research across 6 platforms using Claude Computer Use API.

## Quick Start

```bash
# 0. You need a Firebase Admin key file. See "Firebase Admin Key" below.

# 1. Install
git clone <repo-url>
cd research-automate
pip install -r requirements.txt

# 2. Setup (one-time: mints ResearchToken, renders QR, waits for logins)
python research.py --setup

# 3. Start the server (keep it running)
python research.py --serve

# 3a. (Optional, recommended) Survive reboots + crashes.
python research.py --resurrect

# 3b. (Undo 3a) Clean full-reset — kills supervisor + serve, removes
#     the Scheduled Task, syncs the Firestore flag.
python research.py --exorcise
```

That's it. Four commands to a hands-off always-on backend — plus `--exorcise` when you need a clean teardown.

## Firebase Admin Key (required) — `firebase-service-account.json`

The backend needs a Firebase Admin SDK key to read the queue, write heartbeats, and stream events. **This file is NOT committed to git and never will be.**

**How to get it:** Sammy (sammy.guli@distributedglobal.com) will email you the JSON file directly. One file per person.

**Where it goes (exact path):**

```
research-automate/firebase-service-account.json
```

That's it — same directory as `research.py`. The `.gitignore` is pre-configured so you can never accidentally commit it. If Python can't find the file, `--setup` / `--serve` will fail loudly with a clear path in the error.

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
python research.py --setup
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
- A **command listener** for stop / pause / resume / config / add_context / agent_decision / **continue_anyway** / **skip_audio** / **skip_email**.
- A **local HTTP API** on `http://localhost:8000` for the CLI + any direct calls.

Keep `--serve` running while you use the app. If the server stops, the web app's 60s watchdog detects it, marks running tiles as stopped, and prevents a reload from resurrecting the pipeline.

**Queue persistence across restarts** — on `--serve` startup, the backend re-enqueues any `status:"queued"` researches from Firestore, so the queue survives a `--daemon-loop` respawn. Anything that was `status:"ongoing"` when the previous process died is flipped to `stopped` with a "Backend restarted mid-run" message, instead of appearing live-but-frozen.

### Step 5a (optional, recommended): Make it indestructible

```bash
python research.py --resurrect
```

Registers a Windows Scheduled Task that runs a **daemon-loop wrapper** — a tiny supervisor process that (re-)starts `--serve` whenever it exits for any reason: crash, stop button, logout, reboot, etc. The task is set to ONLOGON + AT STARTUP with unlimited duration, so the backend is effectively always-on while the PC is powered.

The Account page's **Indestructible** toggle reflects the real scheduled task state (`schtasks /Query`), so the toggle survives unlink+relink. Turn it off from the same page if you ever want to stop auto-restart.

### Step 5b (undo Step 5a): `--exorcise`

```bash
python research.py --exorcise
```

The opposite of `--resurrect` — a clean full-reset of everything indestructible. Four-step:

1. **Deletes the Windows Scheduled Task** so `--daemon-loop` won't auto-start at next logon / reboot.
2. **Kills every running `--daemon-loop` AND `--serve` process**, looping for up to 8s so a mid-enumeration respawn still gets caught (the supervisor respawns `--serve` every ~5s between deaths, so a single-shot kill misses any `--serve` that happened to be respawning at the wrong moment).
3. **Flips the Firestore `indestructible` flag to `false`** so the Account toggle matches reality instantly.
4. **Final-state verification** — if anything survived, prints the surviving PIDs so you can nuke them from Task Manager (or re-run `--exorcise`).

Idempotent: works whether or not the task/loop was installed. After `--exorcise` the system is back to "nothing research.py-related is running" — any in-flight pipeline under the supervised `--serve` aborts (the deliberate cost of a clean undo). To bring the backend back, re-run `--serve` yourself; to re-enable supervision, run `--resurrect` again.

Turning off the **Indestructible** toggle in the app → Account page runs the same teardown remotely.

### Step 6: Fire a research topic in the app

Open Super Research (the web app) → type a topic → backend picks it up from Firestore → pipeline runs here. If the app says "No backend connected" there's a Connect bubble with a Scan QR button that links in seconds.

## Multiple Devices (same user)

One account can pair multiple PCs. Each `--setup` on a new machine registers its own `users/{uid}/devices/{deviceId}` doc. The app's sidebar gets a device switcher (with online/offline dots) and every research is stamped with the device it ran on — so jobs you fire from the app route back to the specific PC that was **active** when you hit Start. If you fire two jobs on the same device while one is running, the second queues; if you fire one on a different device, both run in parallel.

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
| 5. Report | Google Docs + Gmail (delivery) | ~3 min |

Times based on real run analytics. Total: ~1h 50m for a full pipeline.

## Phase narration (backend Gemini Flash + frontend fallback)

Long quiet stretches in Phases 1–3 are expected (ChatGPT Pro thinks for ~3 min before writing, NotebookLM renders for 5–15 min), but a dead-looking tile makes the whole app feel broken even when nothing's wrong. Apr 19 added a two-tier narration system so there's always a visible human-language pulse:

- **Backend (Gemini 2.0 Flash inside `research.py`)** — every active phase has a narrator worker that reads a bounded ring buffer of recent events (~40) and emits a `phase_narration` event about every 45s. Narrator warms on `phase_start`, stays quiet during `pipeline_paused`, tears down on `phase_complete` / `pipeline_stopped`. Cost envelope: ~200 input / 30 output tokens per narration → <$0.02 per full pipeline run.
- **Frontend fallback (Gemini 2.0 Flash via `/api/narrate`)** — if the backend narrator goes silent for >15s on the currently-running phase AND the watchdog considers the backend alive, the frontend writes a speculative sentence into the same dropdown slot, rendered italic with a **"Likely: …"** prefix so the user sees it's a guess. Budget-capped at 20 calls per research. Disabled when the watchdog says the backend is actually dead (PokeNote owns that surface).

## Phase 0 verification (sequential, Apr 19)

Preflight now walks platforms one at a time instead of opening 7 tabs at once. For each enabled platform:

1. `cookie_login_hit()` reads the persistent profile's cookie store for that platform's primary session token. Hit → emit `agent_progress status=ok` and move on. No tab, no network, no CUA.
2. Cookie miss → open that one tab, wait 4s for SPA hydration, check URL for known login hosts.
3. Still ambiguous → CUA vision verification.
4. Still not logged in → emit `login_required` **scoped to that single platform** and pause for user retry. The next platform does NOT open until the current one is resolved (Cloudflare stealth + less user overwhelm).

Matches the `--setup` script's one-at-a-time walk that's been working well for months. Global "Skip verification" still bypasses the whole sequence. Per-phase login checks at every subsequent phase are cookie-only (no tabs, no CUA) — they catch mid-run session drift without re-opening anything.

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
- **Phase 5** — ffmpeg disk-full / not-found / generic, YouTube URL extract fail, Google Doc creation fail, email bad-address / auth / SMTP, email skip via command
- **Cross-cutting** — Anthropic 429/529 narrate as retrying; other API errors surface as `pipeline_warning` on the current phase

Default action on every alert is `[Skip]` (advance past the failure). Phase-specific alerts offer extra actions: `HV Resume`, `continue_anyway`, `skip_audio`, `skip_email`. **Stop is NOT a per-phase action** — pause/stop/resume stay global in the app's chat input bar.

### Error matrix (normalized, Apr 19 late-late)

The per-alert action set was consolidated to reduce noise and remove affordances that invited broken states:

- **Default everywhere: Retry · Skip.** Every failure surface offers this pair unless it's specifically overridden below.
- **Workspace cap hit in Phase 2 → `End research` only** (`action=stop`). No point retrying when the user is out of workspace slots; other phases keep Retry · Skip.
- **Poll timeout in Phase 2 → Retry · Skip · Wait** (Wait extends the agent's budget by 15 min). Only phase that gets a third option because "wait a little longer" is a frequently-correct user choice for Phase 2.
- **Removed the "Poke" button and "Proceed without CUA" options entirely.** Poke morphed into the normalized Retry (which in turn does the hard tab close+reopen from the Apr 19 early `retry_agent` work). "Proceed without CUA" let users walk into broken-state pipelines with no recovery path.
- **Stuck-agent buttons relabeled** to match the normalized vocabulary: Poke → **Retry**, "Wait longer" → **Wait**, "Skip agent" → **Skip**.

The backend's per-agent narrator runs alongside the phase narrator during P1/P2 — separate Gemini 2.0 Flash calls emit `agent_narration` events (one per active agent, ~6s cadence) that the frontend shows inside each agent row of the Phase 2 accordion. Cost bounded: ~200 in / 30 out per call × 3 agents × a few hundred seconds per run.

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
├── requirements.txt            # Python dependencies
├── firebase-service-account.json  # Firebase connection (not committed)
├── research_config.json        # Your ResearchToken (generated by --setup)
├── run_analytics.json          # Historical phase durations (auto-updated)
├── ARCHITECTURE.md             # Backend architecture + Frontend ↔ Backend API contract
├── queues/                     # Active/completed pipeline runs (per-topic dirs)
│   └── {topic}_{timestamp}/    # meta.json, config.json, delivery.json, documents/, podcasts/
└── tracks/                     # Real-time progress data (events.jsonl + per-agent scrapes)
    └── {topic}_{timestamp}/    # events.jsonl, phase0/, phase1/, phase2/, ...
```

## Troubleshooting

**"No PipeToken found"** — Run `python research.py --setup` first.

**Backend shows "Offline" in the web app** — Make sure `python research.py --serve` is running. The heartbeat updates every 30 seconds.

**"Backend did not respond within 15s"** — The backend may be busy with another research. Check the queue: `GET http://localhost:8000/api/queue`.

**Browser sessions expired** — Re-run `python research.py --setup` to log in again.

**NotebookLM login expired mid-run** — Surfaces as a Phase 3 alert with `login_expired` detail (distinct from generic upload failure). Re-run `--setup` to refresh that session; hit `[Skip]` on the alert if you want to move past Phase 3 and still get Phase 5 report/email.

**Anthropic 429 / 529 (rate-limit or overload)** — Retries automatically with narration in the current phase dropdown; usually self-resolves within one or two attempts.

**Phase 4 audio failed but Phase 5 still matters** — Hit `[skip_audio]` on the Phase 4 alert; Phase 5 YouTube + Email proceed normally.

**Phase 5 email not sending** — Alert surfaces with the specific cause (bad address / auth / SMTP). Hit `[skip_email]` to skip email but still get the Google Doc link.

---

Built by Sammy for Distributed Global.
