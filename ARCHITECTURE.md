# Super Research Backend — Architecture

Backend architecture + Frontend ↔ Backend contract for the Multi-Agent Deep Research Pipeline. Covers phase structure, event/command protocol, retry/continue/skip decision gates, phase-restart semantics, backend-restart resume flow, and watchdog spec.

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
| `phase_alert` | 0-5 | `{phase, type, title, details?, actions?: string[]}` | Routed to the per-phase `PhaseAlertPanel` in the phase dropdown (all non-Phase-2 failures now surface here instead of as chat bubbles). `actions` declares extra buttons beyond default `[Skip]` — e.g. `["HV Resume"]`, `["continue_anyway"]`, `["skip_audio"]`, `["skip_email"]`. Dedup key on frontend: `type + title + details` |
| `phase_alert_clear` | 0-5 | `{phase}` | Clears the alert for that phase (replaces the old `RECOVERY_MSG` / "Recovered ✓" chat mutation) |
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
| `continue_anyway` | `{phase?}` | Frontend response to a `phase_alert` that exposed `continue_anyway` (e.g. brief-short). Backend `_controls.set_continue_anyway()` fires; orchestrator accepts the short/partial output and advances |
| `skip_audio` | — | Frontend response to a Phase 4 `phase_alert`. Backend `_controls.set_skip_audio()` fires; Phase 4 audio generation is skipped but Phase 5 YouTube+Email still run |
| `skip_email` | — | Frontend response to a Phase 5 `phase_alert`. Backend `_controls.set_skip_email()` fires; Phase 5 email is skipped (Google Doc still created) |
| `feedback` | `{phase, message}` | User feedback injection. Stored per-phase, injected into next phase rerun |
| `retry_phase` | `{phase}` | Frontend response to a phase-level warning (brief-short, brief-timeout, NotebookLM failure, audio timeout, Phase 3 gate). Backend's phase coroutine polls `consume_retry_phase(N)` + loops back to restart |
| `retry_agent` | `{agent}` | Frontend response to a Phase 2 agent warning (timeout, empty-final, send-fallback, session-expiry). Phase 2 polling consumes + submits a follow-up prompt via `paste_followup` |
| `continue_partial_agent` | `{agent}` | Accept Phase 2 agent's current short/timed-out output as final; agent finalizes with status `done_partial` / `timeout_partial` |
| `poke_agent` | `{agent}` | Stuck-agent response: send mild "please continue" follow-up without extending budget |
| `wait_longer_agent` | `{agent}` | Stuck-agent response: reset the no-growth timer, grant another 15 min |

> New consumers wired via `_controls.request_*` + `consume_*` methods; `reset()` clears them on run start. `await_retry_or_continue()`, `await_agent_decision()`, `await_stuck_decision()` are the helper coroutines that Phase N loops block on before branching.

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

## Per-phase Alert Narration

Every failure category emits a `phase_alert` event that the frontend routes to the corresponding phase's `PhaseAlertPanel` (inside the phase dropdown). No phase failure renders as a chat bubble anymore.

**Emit points per phase:**

| Phase | Failure category | Emit shape | Extra action |
|-------|------------------|------------|--------------|
| 0 | Browser launch failed | `phase_alert {type:"browser_launch_failed"}` | — |
| 0 | Chromium binary missing | `phase_alert {type:"chromium_missing"}` | — |
| 0 | Playwright profile locked | `phase_alert {type:"profile_locked"}` | — |
| 1 | Brief timeout | `phase_alert {type:"brief_timeout"}` | `retry_phase(1)` · `continue_anyway` |
| 1 | Brief paste retry (per attempt) | `phase_alert {type:"brief_paste_retry", attempt, max}` | — |
| 1 | Brief short/partial output | `phase_alert {type:"brief_short", details}` | `retry_phase(1)` · `continue_anyway` |
| 1 | Brief model error | `phase_alert {type:"brief_model_error", error}` | — |
| 2 | 90-min timeout | `phase_alert {type:"phase2_timeout", sources}` | `retry_agent` · `continue_partial_agent` · `skip_agent` |
| 2 | Empty-final (3× CUA done + extract empty) | `phase_alert {type:"agent_empty_final"}` | `retry_agent` · `continue_partial_agent` · `skip_agent` |
| 2 | Send-button CUA fallback | `phase_alert {type:"send_button_fallback"}` | `retry_agent` · `continue_partial_agent` · `skip_agent` |
| 2 | Stuck-agent (no growth 20 min + non-active status) | `phase_alert {type:"stuck_agent"}` | `poke_agent` · `wait_longer_agent` · `skip_agent` |
| 2 | Session expired mid-run (2× confirmed) | `pipeline_error {type:"session_expiry"}` | `retry_agent` (= relogin retry) · `skip_agent` |
| 2 | Paste outer-retry | `phase_alert {type:"paste_outer_retry"}` | — |
| 2 | HV detected / auto-clear / cooldown / success / fail | `phase_alert {type:"hv_*", stage}` — detected → auto 1/2 → cooldown 180s → retry 2/2 → success/fail | `HV Resume` (fail) |
| 3 | Per-agent share-link extract fail | `phase_alert {type:"share_link_fail", agent}` | — |
| 3 | NotebookLM login expired | `phase_alert {type:"nlm_login_expired"}` | `retry_phase(3)` (= relogin retry) · `skip_phase(3)` |
| 3 | NotebookLM generic upload fail | `phase_alert {type:"nlm_upload_failed", error}` | `retry_phase(3)` · `skip_phase(3)` |
| 3 | No MD files to upload | `phase_alert {type:"no_md_files"}` | — |
| 3 | Inter-phase gate (P2 produced no docs) | `phase_alert {type:"p2_empty"}` | `retry_phase(2)` · `stop` |
| 4 | Audio skip via command | `phase_alert {type:"audio_skipped"}` | — |
| 4 | Poll-budget timeout | `phase_alert {type:"audio_poll_timeout"}` | `retry_phase(4)` · `skip_audio` |
| 4 | Download-event timeout + fallback + final fail | `phase_alert {type:"audio_download_*"}` | `skip_audio` |
| 4 | Firebase Storage upload (best-effort) | `phase_alert {type:"audio_storage_warn"}` | — |
| 5 | ffmpeg disk-full / not-found / generic | `phase_alert {type:"ffmpeg_*"}` | — |
| 5 | YouTube URL extract fail | `phase_alert {type:"youtube_url_fail"}` | — |
| 5 | Google Doc creation fail | `phase_alert {type:"gdoc_fail"}` | — |
| 5 | Email bad-address / auth / SMTP | `phase_alert {type:"email_*"}` | `skip_email` |
| 5 | Email skip via command | `phase_alert {type:"email_skipped"}` | — |
| cross-cutting | Anthropic 429/529 | `phase_alert {type:"anthropic_retry", code, attempt}` | — |
| cross-cutting | Other API errors | `pipeline_warning {agent?, message}` (not a phase_alert) | — |

Each alert carries a `phase` field so the frontend can dedup on `(phase, type, title, details)` and place it in the right dropdown. Clearing an alert fires `phase_alert_clear {phase}`.

**Action semantics recap:** default `[Skip]` always advances past the failing step. Extra actions are declared in the event's `actions` array and wired to the corresponding Firestore command: `HV Resume` → HV resume dispatch, `continue_anyway` / `skip_audio` / `skip_email` → their named commands.

---

## Retry / Continue / Skip Decision Gates

Every recoverable failure offers at least one explicit choice via `phase_alert.actions`. The backend blocks on a per-gate coroutine (`await_retry_or_continue`, `await_agent_decision`, `await_stuck_decision`) until either the user responds (Firestore command received) or a bounded timeout elapses (caller picks a safe default — usually continue/proceed).

**Phase-level gates (block current phase):**

| Gate | Site | Timeout | Options | Retry action | Default on timeout |
|------|------|---------|---------|--------------|-------------------|
| P1 brief-short | `run_phase1` end (<500 chars) | 10 min | `[Retry Phase 1 (N left)]` · `[Continue anyway]` | Recursive `run_phase1(_retry_count+1)` | Continue |
| P1 brief-timeout | poll_until_done cap | 10 min | `[Retry brief (N left)]` · `[Continue with partial]` | Same recursion | Continue |
| P3 upload failed | NotebookLM upload exception | 10 min | `[Retry upload (N left)]` · `[Skip NotebookLM]` | Close tab + loop back to upload | Skip |
| P3 inter-phase gate | "no MD files" after P2 | 10 min | `[Retry Phase 2]` · `[Stop]` | Re-run `run_phase2` inline | Stop |
| P4 audio timeout | run_phase3_audio poll cap | 10 min | `[Retry audio (N left)]` · `[Skip audio]` | Reload + re-trigger generation | Skip |

Retry counters: hard-capped (P1=2, P3=2, P4=1) so a misbehaving platform can't spin forever.

**Agent-level gates (block per agent; other agents keep polling):**

| Gate | Site | Timeout | Options | Retry action |
|------|------|---------|---------|--------------|
| Agent 90-min timeout | poll_all_agents_round_robin | 5 min | `[Retry]` · `[Continue with partial]` · `[Skip agent]` | `paste_followup` "please output complete report", +15 min budget |
| Agent empty-final | 3× CUA done + empty extract | 5 min | Same three-way | Same follow-up, reset done state |
| Agent send-button fallback | start_agent_no_gemini_wait | 90 s | `[Retry send]` · `[Continue (trust it)]` · `[Skip agent]` | Re-run `PROMPT_CLICK_SEND` CUA loop |
| Stuck-agent | Inline (when `elapsed > 20m` AND `no_growth > 20m` AND status NOT in `{planning, thinking, researching, searching}`) | async (non-blocking, consumed on next poll tick) | `[Poke Agent]` · `[Wait longer]` · `[Skip agent]` | Mild "please continue" follow-up |
| Session expiry | Inline (requires 2× consecutive confirms spaced 2 min) | 30 min | `[I've logged in — Retry]` · `[Skip agent]` | Reload tab + keep polling |

**False-alarm suppression baked into the detectors:**
- Stuck-agent: 20-min elapsed floor, checks text AND source growth, skips during known active statuses.
- Session-expiry: 2 consecutive confirmations 2 min apart; distinct from HV (CAPTCHA/Cloudflare) which has its own detector.
- Brief-short: only fires in 100-500 char window (never on truly empty output — that's a different path with its own handling).
- Every alert is dedup'd on `(phase, type, title, details)` so duplicates from polling loops don't spam the dropdown.

---

## Backend Restart Resume-from-Checkpoint

When the `--daemon-loop` supervisor respawns `--serve` after a crash, queue rehydration recovers state from Firestore:

| Previous status | Action |
|-----------------|--------|
| `queued` | Re-enqueued into `_job_queue` with original topic + pipelineConfig |
| `ongoing` | Marked `status:"paused_backend_restart"` with summary "Backend restarted mid-run — hit Resume to pick up from the last checkpoint." |

Frontend renders the new status as a phaseAlert at the last-known phase:
- `[Resume from checkpoint]` → calls `POST /api/pipeline?action=resume&id={backendRunId}` → backend enqueues job with `resume_dir=queue`; `run_pipeline` uses `detect_resume_phase()` to skip to the right phase.
- `[Discard + start new]` → clears the alert locally; queue directory stays on disk as a backup.

Checkpoints that survive the crash: `documents/*.md`, `tracks/*.json`, `delivery.json`, `links.json`, `podcasts/*.m4a`, `checkpoint.json`. Missing state (browser + CUA session) is re-created by the resume run.

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

*Updated: 2026-04-18 — added `phase_alert` + `phase_alert_clear` events with per-phase emit matrix; new commands `continue_anyway` / `skip_audio` / `skip_email` (all wired via `_controls.set_*`); HV cooldown 45s → 180s; queue persistence across `--daemon-loop` restart.*
