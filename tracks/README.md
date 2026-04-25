# Tracks — Real-Time Pipeline Progress Data

Each pipeline run creates a timestamped folder with progress snapshots.

## Structure

```
tracks/<topic>_<timestamp>/
  events.jsonl              ← ALL events, one JSON per line (web app streams this)
  phase0/                   ← Phase 0: Init progress
  phase1/                   ← Phase 1: Brief generation progress
    001_093015.json
  phase2/                   ← Phase 2: Deep research per agent
    chatgpt/
      001_094530.json
    gemini/
      001_094535.json
    claude/
      001_094540.json
  phase3/                   ← Phase 3: NotebookLM + audio generation
    001_110000.json
  phase4/                   ← Phase 4: YouTube upload progress
  phase5/                   ← Phase 5: Report + email delivery
```

## events.jsonl (Primary — Web App Streaming)

Single append-only file with ALL events from all phases. Backend writes here.
Frontend polls `GET /api/runs/{id}/events?offset=N` or connects via `WS /ws/{run_id}`.

## Event Types

### Phase lifecycle
| Type | Phase | Description |
|------|-------|-------------|
| phase_start | 0-5 | Phase begins |
| phase_complete | 0-5 | Phase finished with links + durationSec |
| phase_skipped | 0-5 | Phase disabled in config OR user skipped after error |
| phase_restart | 0-5 | Mid-phase restart (user feedback, retry-after-error, Phase 0 re-verify) |

### Pipeline lifecycle
| Type | Phase | Description |
|------|-------|-------------|
| pipeline_paused | N | Pipeline paused — waits for user command to resume/stop |
| pipeline_resumed | N | Paused pipeline resumed |
| pipeline_complete | — | All phases done |
| pipeline_stopped | N | User hit Stop (ONLY trigger — see never-die contract below) |
| pipeline_warning | N | Non-fatal warning (optionally with actions + alertType="retrying") |
| pipeline_error | N | Phase-level error — carries `actions` like [Retry, Skip] so the frontend shows a phase alert and AWAITS the user's decision. Never terminates the pipeline (never-die contract, 2026-04-18). |

### Per-agent (Phase 2 + individual platform work)
| Type | Phase | Description |
|------|-------|-------------|
| agent_progress | 2+ | Live scrape snapshot (status, sources, sections, partial text length) |
| agent_skipped | 2 | Agent disabled in config OR user skipped after HV / link failure |
| agent_warning | 2+ | Per-agent non-fatal warning |
| agent_verified | 2+ | HV challenge cleared on this agent (fires after Playwright/CUA/tab-kill tier succeeds) |
| agent_link_failed | 2 | Link-first retry exhausted — agent-level phase alert follows |

### Link extraction (post-phase URL collection)
| Type | Phase | Description |
|------|-------|-------------|
| link_extracting | 2-5 | Started URL extraction for a completed artifact |
| link_extracted | 2-5 | Verified URL captured |
| link_extract_retry | 2-5 | Extraction retry in progress (3× before asking user) |
| link_extraction_failed | 2-5 | All retries failed — pairs with a pipeline_error asking Retry / Skip |

### User-interruption gates
| Type | Phase | Description |
|------|-------|-------------|
| login_required | 0-5 | Platform session missing. **Phase 0** (as of Apr 19): sequential — fired with `platforms: [key]` scoped to the ONE platform currently being verified, one at a time until all pass. **Phases 1-5**: cookie-only probe at phase entry fires this with the missing platforms for that phase regardless of `skipInitVerify`. |
| human_verification_required | 1-5 | Cloudflare / CAPTCHA / "Verify you are human" gate persisted past all auto-clear tiers (Playwright → CUA×2 → tab-kill). Pauses pipeline until user resolves. |

### Phase narration (Apr 19)
| Type | Phase | Description |
|------|-------|-------------|
| phase_narration | 1-5 | Backend Gemini 2.0 Flash narrator emits one human-readable sentence describing what's happening in the current phase. Fed by a bounded ring buffer (~40 recent events). Cadence ~45s; warms on `phase_start`, tears down on `phase_complete` / `pipeline_stopped` / `pipeline_paused`. Frontend renders inside the active phase dropdown. Payload: `{text, timestamp, speculative: false}`. (The frontend speculative `/api/narrate` fallback was removed in U2 — `speculative: true` no longer appears.) |

### Infra + misc
| Type | Phase | Description |
|------|-------|-------------|
| heartbeat | N | Backend liveness signal (every 60s during active phases — feeds the frontend watchdog) |
| config_updated | N | pipeline_config changed mid-run (e.g. skip list) |
| cua_action | N | CUA vision call taken (debug audit) |
| user_input_dispatched | N | User's chat input merged into the active phase's context |

### Never-die contract (2026-04-18)
`pipeline_error` no longer terminates the pipeline. It emits actions like `[Retry, Skip]` that map to commands the backend picks up via `_controls.await_phase_decision(phase)`. The ONLY events that end a run are `pipeline_stopped` (user Stop) and `pipeline_complete` (natural finish). Everything else is recoverable.

## Track Entry Schema (DOM scrape snapshots)

```json
{
  "timestamp": "ISO8601",
  "platform": "chatgpt|gemini|claude",
  "status": "Researching...",
  "phase": 2,
  "sources": 47,
  "source_urls": ["..."],
  "sections": ["Introduction", "..."],
  "partial_text_len": 12800,
  "model": "o3",
  "title": "Deep Research on..."
}
```
