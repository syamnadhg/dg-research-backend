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
```

That's it. Four commands to a hands-off always-on backend.

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
- A **command listener** for stop / pause / resume / config / add_context / agent_decision.
- A **local HTTP API** on `http://localhost:8000` for the CLI + any direct calls.

Keep `--serve` running while you use the app. If the server stops, the web app's 60s watchdog detects it, marks running tiles as stopped, and prevents a reload from resurrecting the pipeline.

### Step 5a (optional, recommended): Make it indestructible

```bash
python research.py --resurrect
```

Registers a Windows Scheduled Task that runs a **daemon-loop wrapper** — a tiny supervisor process that (re-)starts `--serve` whenever it exits for any reason: crash, stop button, logout, reboot, etc. The task is set to ONLOGON + AT STARTUP with unlimited duration, so the backend is effectively always-on while the PC is powered.

The Account page's **Indestructible** toggle reflects the real scheduled task state (`schtasks /Query`), so the toggle survives unlink+relink. Turn it off from the same page if you ever want to stop auto-restart.

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
├── PIPELINE_SPEC.md            # Frontend ↔ Backend API contract
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

---

Built by Sammy for Distributed Global.
