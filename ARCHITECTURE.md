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
| ~~`phase_alert`~~ | — | — | **Frontend-synthesized, never emitted by backend.** The FE derives `PhaseAlertPanel` state from `pipeline_error` / `pipeline_warning` / `login_required` / `phase_restart` / `pipeline_stopped` / watchdog escalation, then calls `setPhaseAlert(researchId, phase, …)` on the store. Backends should NOT emit `phase_alert` events — they're consumed nowhere. |
| ~~`phase_alert_clear`~~ | — | — | **Frontend-only.** FE clears panels via `clearPhaseAlert(researchId, phase)` on `phase_complete` / `phase_skipped` / pong recovery / user action acknowledgement. Not a wire event. |
| `heartbeat` | N | `{phase, ts}` | Emitted ~60s during long waits so frontend liveness watchdog stays green |
| `login_required` | 0-5 | `{platforms: string[], platformLabels: string[], envErrors?: string[], attempt, message}` | **Phase 0 (Apr 19): sequential — fired with `platforms: [key]` scoped to the ONE platform currently being verified, one at a time until all pass. Phases 1-5: cookie-only probe at phase entry fires this with the missing platforms for that phase regardless of `skipInitVerify`.** |
| `phase_narration` | 1-5 | `{text: string, timestamp: int}` | **Gemini 2.0 Flash narrator (Apr 19).** Emits one human-readable sentence describing what's happening in the active phase, every ~45s. Fed by a bounded ring buffer (~40 recent events). Warms on `phase_start`, quiet during `pipeline_paused`, tears down on `phase_complete` / `pipeline_stopped`. Frontend stores in `phaseNarrations[researchId][phase]` and renders inside the phase dropdown. Speculative counterpart emitted by the frontend's `/api/narrate` fallback route carries `speculative: true` and renders italic with a "Likely: …" prefix. |
| `agent_narration` | 2 | `{agent: string, text: string, timestamp: int}` | **Per-agent Gemini 2.0 Flash narrator (Apr 19 late-late).** Emits one human-readable sentence per active Phase 2 agent every ~6s. Separate Flash API call per agent (not one call for all of Phase 2) because per-agent context changes fast during P1/P2. Frontend stores in `agentNarrations[researchId][agentKey]`, rendered by `AgentAccordionRow` in preference over the legacy `richNarrative` string. Cleared on phase-2 complete. Cost bounded: ~200 in / 30 out per call × 3 agents × a few hundred seconds per run. |

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
| `skip_phase` | `{phase}` | Frontend's default Skip action on every `phase_alert`. Backend's phase coroutine consumes the request and advances past the failing step. For Phase 4, this replaces the old `skip_audio` verb (removed U2); Phase 5 likewise replaces `skip_email`. `_controls.skip_audio` / `skip_email` flags remain as internal-only state read by Phase 4/5 polling logic, but no FE command toggles them anymore |
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

`PhaseAlertPanel` (the alert UI inside each phase dropdown) is **frontend-synthesized**. The backend never emits a `phase_alert` event. Instead, the FE listens for these wire events and calls `setPhaseAlert(researchId, phase, …)` on the Zustand store:

**FE writers that populate `phaseAlerts`:**

| Source event | FE handler in `usePipeline.ts` | Resulting alert |
|--------------|--------------------------------|-----------------|
| `pipeline_error` | `pipeline_error` branch | warn/error panel with backend-supplied `actions: [Retry, Skip, …]` |
| `pipeline_warning` | `pipeline_warning` branch | info/warn panel with the `actions` payload (e.g. `[Retry, Continue anyway]`) |
| `login_required` | `login_required` branch | warn panel: "Log into X on Y", actions `[Retry, Skip verification]` |
| `phase_restart` | `phase_restart` branch | quiet info panel: "Phase N restarted with your additional context" |
| `pipeline_stopped` | `pipeline_stopped` branch (legacy paired event) | error panel with humanized error text |
| `human_verification_required` | `human_verification_required` branch | per-AGENT (not phase) alert via `setAgentAlert` — listed here because it's part of the same alert system |
| `agent_link_failed` | `agent_link_failed` branch | per-AGENT alert with `[Retry, Skip]` actions |
| watchdog 30-min auto-pause | `startFirestoreListener` watchdog interval | warn panel: "Backend silent for 30 min — pipeline auto-paused" with `[Retry (ping), Skip phase]` |
| watchdog reviving (supervised) | same | quiet info panel: "Reviving backend…" |
| `ChatContainer.tsx` paused_backend_restart recovery | onMount Firestore read | warn panel: "Backend restarted mid-run — resume from the last checkpoint?" |
| pre-Phase-0 start failure | `startPipelineViaFirestore` ack timeout in `startPipeline` | warn panel with `[Retry, Skip]` (`retry_start` / `skip_start`) |

**FE writers that clear `phaseAlerts`:**

| Trigger | Handler |
|---------|---------|
| `phase_complete` | `clearPhaseAlert(researchId, phase)` after the message update |
| `phase_skipped` | same |
| watchdog passive recovery (events flowing again) | `clearPhaseAlert` for current phase |
| watchdog explicit pong recovery | same |
| user taps a panel button (Retry/Skip/etc.) | `PhaseDropdown.tsx` action handler clears after the Firestore command writes |
| `pipeline_resumed` | resumes paused state but doesn't clear panels — the next phase event clears them |

**Action semantics recap:** action buttons in a panel come from the source event's `actions` array. The FE renders them via `PhaseAlertPanel` / `AgentAlertPanel`; tapping a button writes the embedded `command` (`{action, …}`) to the research's `commands` subcollection. Phase 4/5 use the unified `skip_phase phase=N` verb (legacy `skip_audio` / `skip_email` were removed in U2).

### Normalized error matrix (Apr 19 late-late)

The agent-level action set was consolidated to reduce noise:

| Situation | Default options |
|-----------|----------------|
| Every agent/phase alert (unless overridden below) | **Retry · Skip** |
| Phase 2 workspace cap hit | **End research** only (`action=stop`) |
| Phase 2 poll timeout | **Retry · Skip · Wait** (Wait extends budget 15 min) |
| Stuck-agent (renamed vocabulary) | **Retry · Wait · Skip** (was Poke / Wait longer / Skip agent) |

**Removed entirely:** the `[Poke]` button (folded into Retry, which now does the hard tab close+reopen from Apr 19 early `retry_agent`) and `[Proceed without CUA]` (let users walk into broken-state pipelines with no recovery path). Frontend PhaseAlertPanel already renders every alert via the `action.command` passthrough, so the normalization was pure backend: change the `actions` array the event carries and the UI follows.

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
| Agent 90-min poll timeout | poll_all_agents_round_robin | 5 min | `[Retry]` · `[Skip]` · `[Wait]` (Apr 19 late-late: Wait extends budget 15 min) | `paste_followup` "please output complete report" on Retry; `target_page` re-anchor on next poll tick |
| Agent empty-final | 3× CUA done + empty extract | 5 min | `[Retry]` · `[Skip]` | Same follow-up, reset done state |
| Agent send-button fallback | start_agent_no_gemini_wait | 90 s | `[Retry]` · `[Skip]` | Re-run `PROMPT_CLICK_SEND` CUA loop |
| Claude 2-artifact hard-fail | Inline (elapsed ≥ 80% of wait AND <2 artifacts) | 5 min | `[Retry]` · `[Skip]` | Retry closes + reopens Claude tab via hard-mode `retry_agent` |
| Workspace cap | Phase 2 platform constraint hit | — | **`[End research]` only** (`stop`) | n/a |
| Stuck-agent | Inline (when `elapsed > 20m` AND `no_growth > 20m` AND status NOT in `{planning, thinking, researching, searching}`) | async (non-blocking) | `[Retry]` · `[Wait]` · `[Skip]` (Apr 19 late-late — relabeled from Poke / Wait longer / Skip agent) | Retry = hard-mode tab close+reopen; Wait resets the no-growth timer 15 min |
| Session expiry | Inline (requires 2× consecutive confirms spaced 2 min) | 30 min | `[I've logged in — Retry]` · `[Skip]` | Reload tab + keep polling |

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

*Updated: 2026-04-19 — **Sequential Phase 0 verification** (one platform at a time — cookie → tab-open → CUA → `login_required` scoped to that platform; matches `--setup` script's walk). **Cookie-only per-phase login probe** (runs on every phase regardless of `skipInitVerify`; `cookie_login_hit` read only, no tabs/CUA; catches mid-run session drift). **`phase_narration` event** (Gemini 2.0 Flash narrator emits one human-readable sentence every ~45s during active phases; frontend `/api/narrate` fallback fills >15s gaps with speculative "Likely: …" entries). Frontend stack: `phaseNarrations` store slice + `<PhaseNarrationLine>` + `useNarrationFallback` hook, budget-capped at 20 fallback calls per run.*

*Updated: 2026-04-19 (late-late) — **Phase 2 per-agent extraction rules**: ChatGPT keeps public-share-then-conversation-URL fallback; Gemini + Claude PUBLIC share ONLY, hard-fail on miss. Explicit `[gemini_extractor] method=X result=Y` logs; `link_extracted` per agent the moment a verified link lands. **Claude 2-artifact hard-fail** at ≥80% wait time. **Tab round-robin**: `agent_loop(target_page=None)` + `_anchored_screenshot()`; `bring_to_front()` before every polling tick + after every `execute_action`. **Playwright Claude setup**: `setup_claude_dr` rewritten as 3 Playwright steps (Opus 4.7 dropdown, Adaptive Thinking, Research tool) — no more CUA vision for setup. **Normalized error matrix**: default Retry · Skip everywhere; Phase 2 workspace cap → End research only; Phase 2 poll timeout → Retry · Skip · Wait; removed Poke + "Proceed without CUA"; stuck-agent relabeled Retry/Wait/Skip. **New `agent_narration` event**: per-agent Gemini 2.0 Flash call, ~6s cadence during P1/P2. Backend commit `547bf17`.*
