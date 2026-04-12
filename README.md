# Super Research — Backend Pipeline

Python + FastAPI + Playwright backend that automates multi-agent deep research via Claude Computer Use API.

## What It Does

Orchestrates browser automation across 6 platforms (ChatGPT, Gemini, Claude, NotebookLM, YouTube, Gmail) to produce a complete research package from a single topic.

## Pipeline (6 Phases)

| Phase | What Happens | Platform | Time |
|-------|-------------|----------|------|
| 0. Init | Launch browser, verify logins | System | ~10s |
| 1. Brief | Extended Thinking generates research plan | ChatGPT | 10-25 min |
| 2. Research | 3 agents research in parallel | ChatGPT + Gemini + Claude | 15-45 min |
| 3. NLM | Upload reports + generate podcast audio | NotebookLM | 10-20 min |
| 4. YouTube | Convert to video, upload unlisted | YouTube | 5-10 min |
| 5. Report | Google Doc hub + email notification | GDocs + Gmail | 2-5 min |

## Stack

- **Python 3.11+**
- **FastAPI** — REST API + WebSocket server
- **Playwright** — Browser automation (persistent Chrome profile)
- **Claude CUA API** — Computer Use for complex UI interactions
- **Pillow** — Image processing for screenshots
- **markdownify** — HTML to Markdown extraction

## Setup

```bash
pip install -r requirements.txt

# First-time: open browser to log into all services
python research.py --setup
```

This opens a Chromium browser. Log into: ChatGPT, Gemini, Claude, NotebookLM, YouTube, Gmail, Google Docs. Close the browser when done.

## Running

### API Server (for web app)

```bash
python research.py --serve --port 8000
```

### CLI (standalone)

```bash
python research.py "Your research topic"
python research.py "Topic" --brief-file brief.txt     # Skip Phase 1
python research.py "Topic" --pdf paper.pdf             # Attach PDFs
python research.py --resume queue_name                 # Resume stopped run
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CUA_API_KEY` | — | Anthropic API key (required) |
| `CUA_MODEL` | `claude-opus-4-6` | Claude model |
| `CUA_SCREEN_WIDTH` | `1280` | Browser viewport width |
| `CUA_SCREEN_HEIGHT` | `800` | Browser viewport height |
| `POLL_PRO` | `30` | Phase 1 poll interval (seconds) |
| `POLL_DEEP_RESEARCH` | `30` | Phase 2 poll interval (seconds) |
| `MAX_WAIT_PRO` | `45` | Phase 1 max wait (minutes) |
| `MAX_WAIT_DEEP` | `90` | Phase 2 max wait (minutes) |

## File Structure

```
research-automate/
├── research.py          # Main pipeline + FastAPI server (~3200 lines)
├── prompts.py           # All CUA prompts for each phase
├── requirements.txt     # Python dependencies
├── PIPELINE_SPEC.md     # Frontend ↔ Backend API contract
├── queues/              # Runtime: active/completed pipeline runs
└── tracks/              # Runtime: extracted research documents
```

## API

See [PIPELINE_SPEC.md](./PIPELINE_SPEC.md) for the full API contract (endpoints, event types, config schema).

## Integration with Frontend

The web app (`research-app/web`) proxies requests through its Next.js API routes to this backend. For local dev:

```
Frontend (localhost:3000) → /api/pipeline → Backend (localhost:8000)
```

For Vercel deployment, expose this server via ngrok and set `PIPELINE_BACKEND_URL` in Vercel env vars.

---

Built by Sammy for Distributed Global (Herve Bizira).
