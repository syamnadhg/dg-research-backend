# Super Research — Backend Pipeline

Automates multi-agent deep research across 6 platforms using Claude Computer Use API.

## Quick Start

```bash
# 1. Install
git clone <repo-url>
cd research-automate
pip install -r requirements.txt

# 2. Setup (one-time: mints ResearchToken, renders QR, waits for logins)
python research.py --setup

# 3. Start the server (keep running in a separate terminal)
python research.py --serve
```

That's it. Three commands to a running backend.

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

The flow has three clearly-labeled stages in the terminal:

**`[1/3] Research token`**
Mints a new ResearchToken (UUID) or reuses the one in `research_config.json`. The token registers in Firestore (`research_tokens/{token}`) with `status: active`, `machineName`, `createdAt`, `lastHeartbeat`. Delete `research_config.json` if you want to mint a fresh one.

**`[2/3] Scan QR in the Super Research app`**
Renders a scannable QR code right in the terminal. The QR payload is the bare token string (no URL hops). You have two equally-good ways to link the app:
- **Scan** — in the Super Research app: chat → *Connect* bubble → *Scan QR* button, OR Account → Pipeline Connection → small QR icon beside the paste field. Point the phone camera at the terminal QR.
- **Paste** — copy the token line printed above the QR and paste it into Account → Pipeline Connection → *Paste your ResearchToken* → *Link*.

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
- A heartbeat that tells the web app this backend is online (updates `research_tokens/{token}.lastHeartbeat` every 30s)
- A Firestore listener for queued jobs, commands (stop/pause/resume/config/add_context/agent_decision)
- A local HTTP API for fallback control (when Firestore isn't reachable)

Keep `--serve` running in a separate terminal while you use the app. If the server stops, the web app's 60-second watchdog detects it, marks running tiles as stopped, and prevents a reload from resurrecting the pipeline.

### Step 6: Fire a research topic in the app

Open Super Research (the web app) → type a topic → backend picks it up from Firestore → pipeline runs here. If the app says "No backend connected" there's a Connect bubble with a Scan QR button that links in seconds.

## Multiple Users

Multiple people can use the same backend. Share your PipeToken with them — they paste it in their own Account settings. Each user's research is scoped to their own account; the backend just processes the queue.

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
