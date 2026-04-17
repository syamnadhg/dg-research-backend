# Super Research — Pipeline Specification

Frontend ↔ Backend contract for the Multi-Agent Deep Research Pipeline.

---

## Pipeline Phases

The pipeline has **6 phases** (0–5). Each phase has a backend execution step and a corresponding frontend visualization.

| Phase | Name | Platform(s) | Description |
|-------|------|-------------|-------------|
| 0 | **Init** | system | Launch Playwright browser, load persistent Chrome profile, verify logins |
| 1 | **Research Brief** | brief | Extended Thinking generates a comprehensive research brief from the user's topic |
| 2 | **Deep Research** | chatgpt, gemini, claude | 3 agents research in parallel. Each produces a long-form report with sources |
| 3 | **NotebookLM Processing** | notebooklm | Upload reports to NotebookLM + generate podcast-style audio overview |
| 4 | **YouTube Upload** | youtube | Convert audio to video via ffmpeg, upload to YouTube as unlisted |
| 5 | **Report & Notification** | gdocs, gmail | Create Google Doc hub with all links, send email notification |

---

## Phase Dependencies

```
Phase 0 (Init)
  └─→ Phase 1 (Brief)              ← can be SKIPPED (user provides own brief)
       └─→ Phase 2 (Research)       ← at least 1 of 3 agents must run
            └─→ Phase 3 (NLM+Audio) ← can be SKIPPED
                 └─→ Phase 4 (YouTube) ← REQUIRES Phase 3 (audio), videoEnabled
                      └─→ Phase 5 (Report) ← emailEnabled
```

**Dependency cascade:** Phase 3 off → Phase 4 auto-off (no audio to upload)

---

## Event Types

All events are JSON objects written to `events.jsonl` (one per line) AND mirrored to Firestore `users/{uid}/researches/{id}/pipeline_events/` for real-time frontend delivery.

| Event Type | Phase | Fields | When |
|-----------|-------|--------|------|
| `phase_start` | 0-5 | `{agents?: string[], description: string}` | Phase begins |
| `phase_restart` | 1-2 | `{phase, reason, chars, attempt?}` | Phase rerun after pause+input+resume (mid-phase or boundary) |
| `agent_progress` | 1-2 | `{status, progress, sources, sourceUrls, sections, partialTextLen, model, thinking, steps, plan, toolUses, elapsedSec, expectedMinutes, scrapeOk}` | During Phase 1/2 polling (~30s interval) |
| `agent_skipped` | 2 | `{agent: string}` | Disabled agent in Phase 2 config |
| `agent_verified` | 2 | `{agent: string, verified: bool}` | Agent confirmed running |
| `link_extracting` | 1-5 | `{agent: string}` | Link extraction starting |
| `link_extract_retry` | 1-5 | `{agent, attempt, max, reason?}` | Extraction retried (emitted by `extract_with_retry`) |
| `link_extracted` | 1-5 | `{agent: string, url, label, verified}` | Public link obtained (emitted immediately) |
| `link_extraction_failed` | 1-5 | `{agent: string, error}` | Link extraction failed |
| `agent_link_failed` | 2 | `{agent, attempts, lastError}` | B1 gate: 3× retry exhausted. Pipeline pauses and waits for `agent_decision` command |
| `phase_complete` | 0-5 | `{durationSec, links: [{label, url, verified}], skippedAgents?, summary}` | Phase finishes |
| `phase_skipped` | 1-5 | `{reason: string}` | Phase disabled in config |
| `pipeline_paused` | N | `{phase: number, reason?: "login_required" | "agent_link_failed" | "user_pause"}` | Pipeline paused |
| `pipeline_resumed` | N | `{phase: number}` | Resumed from pause |
| `pipeline_complete` | — | `{summary: string}` | All phases done |
| `pipeline_stopped` | N | `{phase: number, reason}` | User requested stop OR backend watchdog detected disconnect |
| `pipeline_error` | N? | `{error: string, agent?: string}` | Fatal or agent error |
| `pipeline_warning` | N? | `{agent?, message}` | Non-fatal warning (e.g., post-P2 `add_context` dropped, residual extra_context at phase boundary) |
| `heartbeat` | N | `{phase, ts}` | Emitted ~60s during long waits so frontend liveness watchdog stays green |
| `login_required` | 0 | `{platforms: string[], envErrors?: string[]}` | Phase 0 preflight: one or more platforms not logged in |

---

## Config

Stored in `{queue_dir}/config.json`:

```json
{
  "skipPhases": [3, 4],
  "agents": { "chatgpt": true, "gemini": true, "claude": false },
  "videoEnabled": true,
  "emailEnabled": true
}
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/runs` | Start new pipeline `{topic, email?, config?}` → `{id, status}` |
| GET | `/api/runs` | List all runs |
| GET | `/api/runs/{id}` | Get run details (meta, checkpoint, delivery) |
| GET | `/api/runs/{id}/events?offset=N` | Get events since offset |
| GET | `/api/runs/{id}/documents/{type}` | Get document content (brief/chatgpt/gemini/claude/consolidated) |
| GET | `/api/runs/{id}/audio/{filename}` | Stream audio file |
| WS | `/ws/{id}` | Real-time event stream |
| POST | `/api/runs/{id}/stop` | Stop pipeline |
| POST | `/api/runs/{id}/pause` | Pause pipeline |
| POST | `/api/runs/{id}/resume` | Resume from checkpoint `{config?}` |
| POST | `/api/runs/{id}/feedback` | Submit feedback `{phase, message}` |
| POST | `/api/runs/{id}/add_context` | Inject extra context mid-run |
| PATCH | `/api/runs/{id}/config` | Update pipeline config mid-run |
| DELETE | `/api/runs/{id}` | Delete a run |
| GET | `/api/queue` | Queue status |

---

## Commands (Firestore → Backend)

Frontend writes commands to `users/{uid}/research_commands/{researchId}` (or equivalent per-token path). Backend listener dispatches:

| Action | Body | Behavior |
|--------|------|----------|
| `stop` | — | Terminates pipeline immediately. `pause_and_close_browser` closes Chromium. `pipeline_stopped` emitted. Pipeline is **terminal**; can't resume |
| `pause` | — | At next checkpoint, `wait_if_paused()` blocks. Browser closes. Chat state preserved. `pipeline_paused` emitted |
| `resume` | `{config?}` | Releases `wait_if_paused()`. Config patch re-read from latest. Browser reopens. `pipeline_resumed` emitted |
| `config` | `{config}` | Mid-pipeline config update (agents, skipped phases, video/email flags). Writes to disk, no phase guard |
| `add_context` | `{text}` | Queues text for the running phase. **P1/P2 only**; rejected at listener when `phase >= 3` with a `pipeline_warning`. Behavior: |
|  |  | • **Running, not paused** — dispatcher pastes text into active agent chats |
|  |  | • **Paused** — on resume, `peek_extra_context()` sets `restart_requested=True`, current phase reruns with combined topic/brief (up to 3× per phase) |
| `agent_decision` | `{agent, decision: "retry" \| "skip" \| "stop"}` | Frontend response to `agent_link_failed` modal. Retry loops back to extraction; Skip records best-effort unverified URL and moves on; Stop terminates pipeline |
| `feedback` | `{phase, message}` | User feedback injection. Stored per-phase, injected into next phase rerun |

---

## Phase-Restart Semantics (pause + input + resume)

When a user adds context while paused and then resumes, the **current phase reruns** with the combined input. Four distinct entry points, same effect:

| Case | Detection site | Mechanism |
|------|---------------|-----------|
| **P1 mid-phase** | `poll_until_done:3377` — after `wait_if_paused()` returns, checks `peek_extra_context()` | Sets `_runtime.restart_requested = True`, returns False. Phase 1 orchestrator retry loop (6744-6755) catches flag, pops context, merges into `topic`, reruns `run_phase1`. Cap 3× |
| **P1 boundary** | Line 6805 after Phase 1 finishes — `is_stop_or_pause()` true | `pause_and_close_browser` → on resume, line 6833 pops queue directly → rebuilds `combined_topic` → calls `run_phase1` once inline |
| **P2 mid-phase** | Same as P1 plus round-robin:3632 | Phase 2 orchestrator retry loop (6886-6898). Context appended to `research_brief`. Cap 3× |
| **P2 boundary** | Line 7066 after Phase 2 finishes — `is_stop_or_pause()` true | Line 7101 pops queue inline, builds `combined_brief`, calls `run_phase2` once |

**No input during pause** → queue empty → flag never trips → phase continues from where it stopped.

---

## Agent Link Gate (B1)

Phase 2 agents are declared "done" only when BOTH conditions are met:
1. **Content extracted** — at least 100 chars of research text
2. **Verified public link** — shareable URL passes `validate_link()` (platform-specific patterns)

`extract_with_retry()` attempts link extraction **3 times** with `validate_link` in between. On final failure:
- Emits `agent_link_failed` with `{agent, attempts, lastError}`
- Pauses via `wait_for_agent_decision()`
- Waits for frontend's `agent_decision` command (retry / skip / stop)

**Gemini safeguard:** CUA completion checks don't begin until after "Start research" is clicked. If <3 sources and <2000 chars early in the run, the "done" verdict is reverted.

**Claude safeguard:** If <2 artifacts exist before 80% of max wait time, completion is reverted (first artifact is often a plan, not the final report).

---

## Backend Liveness (Heartbeat + Watchdog)

Backend writes `research_tokens/{token}.lastHeartbeat = serverTimestamp()` every 30s while `--serve` is running. On long-waits (polling Deep Research for 25+ min) it also emits a `heartbeat` event on the pipeline so legitimate quiet periods stay green.

Frontend watchdog: if `lastHeartbeat` is stale >60s AND recent events are stale >60s, pipeline is considered dead. Frontend:
1. `cancelRunningPhases` — freezes running tile timers, flips badges to "stopped"
2. `saveResearch({status:"stopped"})` — prevents a reload from resurrecting the pipeline
3. `teardown` — removes pipeline from Zustand store → buttons and animations clear

Emits a chat notification: *"Backend disconnected during Phase N (no heartbeat for Xs). Partial results saved."*

---

*Updated: 2026-04-16 (late) — added `phase_restart`, `agent_link_failed`, `heartbeat`, `login_required` events; `agent_decision`, `add_context` post-P2 guard; B1 gate; phase-restart semantics; watchdog protocol.*
