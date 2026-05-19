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
| 4 | **YouTube Upload** | youtube | **FE-owned (2026-05-10 cutover).** FE reads the P3 audio from Firebase Storage, ffmpeg-encodes a static-image+audio mp4 in Cloud Run, uploads to YouTube as unlisted via `youtube.videos.insert` (resumable, OAuth refresh token). BE no longer drives YouTube Studio. |
| 5 | **Report & Notification** | gdocs, gmail | **FE-owned (2026-04-30 cutover).** Creates Google Doc hub with all links via `/api/createDoc`, sends email via `/api/notify-email` (Resend). BE no longer drives Gmail / Google Docs. |

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

**Where each phase runs:**
- Phases 0-3 run **BE-side** (Python daemon on user's PC — needs the local browser for ChatGPT / Gemini / Claude / NotebookLM).
- Phases 4-5 run **FE-side** (Firebase App Hosting / Cloud Run — Data API + Resend, no browser needed). FE-P4 fires off BE's `phase_complete:3` (or `phase_skipped:3` for the no-audio path), then chains directly into FE-P5 on success or fast-path skip. BE exits cleanly after P3 with `delivery.status="completed"`; the user-visible `research.status` stays "ongoing" until FE-P5's `markFeP5Completed` flips it to "completed".

---

## Event Types

All events are JSON objects written to `events.jsonl` (one per line) AND mirrored to Firestore `users/{uid}/researches/{id}/pipeline_events/` for real-time frontend delivery.

| Event Type | Phase | Fields | When |
|-----------|-------|--------|------|
| `phase_start` | 0-5 | `{agents?: string[], description: string}` | Phase begins |
| `phase_restart` | 1-2 | `{phase, reason, chars, attempt?}` | Phase rerun after pause+input+resume (mid-phase or boundary) |
| `agent_progress` | 1-2 | `{status, progress, sources, sourceUrls, sections, partialTextLen, model, thinking, steps, plan, toolUses, elapsedSec, expectedMinutes, scrapeOk, scrapeSource, visionNarration}` | During Phase 1/2 polling (~120s interval, `POLL_DEEP_RESEARCH` default). `scrapeSource: "dom" \| "vision"` records which tier produced the data. `visionNarration` is populated by the agent-side-panel walker when DG_VISION_NARRATE=1 OR when the vision-narrator fallback is exercised (see `_vision_narration` / `_vision_narration_p2` emits at the P1 + P2 sites); when neither fires it's empty string. FE renders verbatim when present. |
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
| `phase_narration` | 1-5 | `{text: string, timestamp: int}` | **Per-phase narrator** — emits one human-readable sentence describing what's happening in the active phase, every ~45s. Fed by a bounded ring buffer (~50 recent events). Warms on `phase_start`, quiet during `pipeline_paused`, tears down on `phase_complete` / `pipeline_stopped`. Frontend stores in `phaseNarrations[researchId][phase]` and renders inside the phase dropdown. **Brain (2026-04-30):** Anthropic Haiku 4.5 primary → Gemini 2.5 Flash fallback. *(The U2 cleanup removed the older `/api/narrate` speculative-fallback hook; speculative entries no longer appear.)* |
| `agent_narration` | 2 | `{agent: string, text: string, timestamp: int}` | **Per-agent narrator** — emits one human-readable sentence per active Phase 2 agent every ~6s. Separate API call per agent because per-agent context changes fast during P1/P2. Frontend stores in `agentNarrations[researchId][agentKey]`, rendered by `AgentAccordionRow` as the canonical narration source. Cleared on phase-2 complete. **Brain (2026-04-30):** Anthropic Haiku 4.5 primary → Gemini 2.5 Flash fallback. Narrator input is scrubbed of chat-thread chrome (`You said:` / `Claude responded:` / `Gemini said` / `brief.md` / `Building:`-prefix composites) at `_compact_event_for_narration` (research.py:5550-5625) BEFORE the narrator sees it; scrape outputs (chip / step counts) untouched. |
| `tier_transition` | 0-5 | `{op, agent?, hotspot_id?, from_tier, to_tier, reason, attempt}` | **Vision shadow-eval telemetry (Apr 26) + TierEscalation tracking (Apr 28).** Records every escalation between interaction tiers (e.g. DOM→CUA, Vision→CUA). The `attempt` field is the per-(op, agent) counter inside a 30-min sliding window — fed by `TierEscalation.record()` (research.py:2580+), centralized via `emit_tier_transition()`. Used by `scripts/vision_shadow_report.py` to compute per-hotspot agreement metrics. Persisted to events.jsonl AND to `logs/vision_shadow.jsonl` when `DG_VISION_TIER=shadow`. |
| `wrong_artifact_rejected` | 2 | `{agent, op, tier, attempt}` | **Finalize-extraction guard (Apr 26).** Fired when `_is_sources_not_document` rejects a finalize-copy result (extracted content is the source-list panel, not the report). Tier ∈ {cua, dom_html_md, dom_js, dom_panel}. Drives the retry-cap-2 loop on hotspots #2c and #2d. |
| `extract_failed` | 2 | `{agent, op, attempts, last_tier}` | **Final-failure terminal (Apr 26).** Fired when all retry attempts on hotspots #2c / #2d are exhausted. Pairs with a `pipeline_error` for FE phase-alert routing. |

---

## Narration Architecture (consolidated 2026-04-30)

**Pre-04-30 — four overlapping writers:**
1. DOM scraper (Claude headings + ChatGPT row walker) — wrote into `progress["sections"]` / `progress["steps"]`, surfaced by FE as section chips + step strip
2. Vision narrator (`narrate.py`, Gemini Flash, screenshot-of-panel) — emitted `visionNarration` field on `agent_progress`; FE rendered verbatim
3. Per-agent narrator (Gemini Pro 2.5, event-stream-based) — emitted `agent_narration` events
4. Phase fallback (research.py heuristics) — populated `progress["progress"]` with "Extended Thinking active · N min elapsed"

Conflict: last-write-wins on FE; vision narrator + per-agent narrator overlapped; section chips piled up post-completion; Pro 2.5 echoed input verbatim at temp 0.2.

**Post-04-30 — single writer + tail:**
1. **Per-agent narrator (canonical)** — Anthropic Haiku 4.5 primary, Gemini 2.5 Flash fallback. Emits `agent_narration` events. Tighter anti-parrot prompt (research.py:5904-5933) + chrome scrub on input window (research.py:5550-5625).
2. **BE phase-fallback tail** — when narrator silent, research.py:9601-9604 emits `Extended Thinking active · 12,400 chars drafted` into `progress["progress"]`. FE renders as last-resort tail (PhaseDropdown.tsx:1880-1885).
3. **DOM scrape feeds the input window** — `_compact_event_for_narration` flattens events to `key=value` strings, scrubbed of chat-thread chrome before narrator sees them. Sections and step counts still feed FE chips/strips, but the narrator no longer parrots them back.
4. **Vision narrator retired** — `narrate.py` `PHASE_BUDGET=0` by default; set `DG_VISION_NARRATE=1` to re-enable.

**Display chain on the agent card (FE, PhaseDropdown.tsx:1861-1891):**
```
agentNarrationText                     ← per-agent narrator (Haiku/Flash)
  || detail.lastNarration              ← persisted last narration on F5/reopen
  || _progressTail                     ← BE fallback (research.py:9601-9604)
  || narrations[stage]                 ← P1 parent card phase narrations
  || generatingFallback                ← "ChatGPT working — fetching live activity..."
  || ""
```

**Display chain on the P1 parent card (FE, PhaseDropdown.tsx:889-890):**
```
agentNarrationText || fallbackNarratives[stage]
```

**DOM scrape rules (panel-scoping fixes, 2026-04-30 commit `94b7bde`):**

| Platform | Selector before | Selector after | Why |
|----------|------------------|----------------|-----|
| Claude headings | `aside h*, [class*="artifact"] h*, [class*="research"] h*, .font-claude-message, .contents .prose` | dropped `.font-claude-message` + `.contents .prose` selectors; kept aside / artifact / research only | `.font-claude-message` grabbed conversation chrome, contaminating sections/steps |
| Claude headings | (no chrome filter) | belt-suspender filter `!/^(?:you\|claude\|chatgpt\|gemini\|notebooklm\|gpt)\s+(?:said\|responded)\b/i` | defends future selectors |
| ChatGPT P2 walker | `STEP_SELS` included `[class*="row" i]` | dropped `[class*="row" i]`; min-len 4→12; new `VERB_GATE` regex with 23 activity verbs | row was too loose; min-len drops "OK"/"Done"; VERB_GATE drops non-activity prose |

## Brief 3h backstop + Manual brief auto-fail (2026-04-30 `6545335`)

Manual-brief mode (Flow A in FE) waits indefinitely for the user to send their own brief into the chat. Pre-04-30, a never-finished brief left the pipeline wedged forever.

- `_BRIEF_WAIT_BACKSTOP_S = 3 * 3600` (research.py:17174). After 3h with no manual brief, `fail_phase` fires + emits `pipeline_stopped` with `reason="manual_brief_wait_backstop_3h"`.
- FE renders the stopped-by-watchdog status with the same humanized "Manual brief never arrived" message.

## Browser Crash Auto-Retry (2026-04-30 `be8f7b3`)

When 3 sites crash inside the same recovery window:

```
Browser crash detected (1st site) → log warn, keep going
Browser crash detected (2nd site) → log warn, keep going
Browser crash detected (3rd site) → triggers recovery:
  1. emit_browser_recovery_status(phase, agent) → passive banner on FE
  2. browser.stop() → browser.start() (T2 restart)
  3. Bypass run_pipeline.finally retry guard (no Retry/Skip prompt)
  4. FE shows AgentAlert with auto_clear_on_resume=true flag
  5. On resume, FE auto-clears the banner
```

No human prompt; the previous behavior of pausing for Retry/Skip blocked recovery.

## Phase 2 Agent Timeout — Auto-Skip (2026-04-30 `be8f7b3`)

Pre-04-30: Phase 2 agent 90-min poll timeout surfaced an alert + `await_agent_decision` block waiting for Retry/Skip/Wait. If the user wasn't watching, the run wedged for 5 min then auto-defaulted to Skip — but the wait itself was wasted.

Post-04-30: drop the alert + `await_agent_decision`. Auto-flow:

```
if elapsedSec >= MAX_WAIT_DEEP * 60:
    if partial_extracted_chars >= 200:
        save_partial(agent)        # records as done_partial
        agent_state = "skipped"
    else:
        agent_state = "skipped"    # no partial salvaged
    fail_agent(agent, reason="poll_timeout_auto_skip")
    continue                       # other agents keep polling
```

No human-decision wait. FE narration line surfaces the auto-skip via the existing `pipeline_warning` infra.

## Dead-Tab Guard (2026-04-30 `6545335`)

Before soft-retrying a Phase 2 agent (research.py:10380):

```
if hard_failure_count >= 2:
    if tab_is_dead(agent.page):    # check page.is_closed() + crash signals
        fail_agent(agent, reason="dead_tab")
        remove_from_pending(agent)
    else:
        soft_retry(agent)
```

Prevents soft-retrying a corpse forever — soft-retry on a dead page just re-fails immediately.

## NotebookLM Upload Filter (2026-04-30 `70e2ab2`)

`_DERIVED_STEMS = {"brief", "consolidated"}` (research.py:14627). Phase 3 NotebookLM upload now skips files whose stem matches `_DERIVED_STEMS` — never uploads `consolidated.md` (a P2 byproduct of claude+gemini concatenation, used for the Documents page only) or `brief.md` (Phase 1 input, already implicit in the agent reports). Pre-fix, the scan-fallback loop picked these up as duplicate sources.

## NotebookLM Strict-Keep Cleanup (`a52bd7b`, `2a93af0`)

Phase 3 used to lean on a "cleanup-by-delete" pass after audio generation — sweep the studio panel and delete any audio cards we didn't want. That model is deprecated; the current flow is a **strict-keep** cleanup with invariant guards on either side of generation:

- **Pre-flight invariant** — before triggering audio generation, the narrator counts the existing NLM audio cards in the studio panel. The expected baseline is 0 (a fresh notebook); if the count is non-zero the agent reconciles state before clicking generate, so we never start with a dirty studio.
- **Post-generate invariant** — after generate fires, the agent verifies `count == 1` (the new Long + Deep-Dive card is the only one present). A mismatch here surfaces a Phase 3 alert instead of silently letting the wrong card flow downstream to YouTube.
- **Post-completion strict-keep** — once the audio is fully rendered, the cleanup pass deletes any cards that are NOT the Long + Deep-Dive entry, while ALWAYS preserving the Long + Deep-Dive one. The keep-list is the contract; deletions are derived from "everything else", not from a denylist of known-bad shapes. This makes the cleanup robust to NLM UI changes that introduce new card variants.

Within the same flow, the audio-generate prompt itself was tightened (`98bd631`) to keep CUA's click target on the generate button rather than wandering onto the surrounding tile body — a class of misclicks that, pre-fix, occasionally created a second card the strict-keep pass then had to clean up.

## Auto-Retry Kwarg Forwarding (2026-04-30 `549f079`)

When the pipeline auto-retries (e.g. Phase 1 brief-short retry):

```python
return await run_pipeline(
    topic=topic, ...,
    uid=uid,                  # NEW — forward
    research_id=research_id,  # NEW — forward
    run_id=run_id,            # NEW — forward
    _retry_count=_retry_count + 1,
)
```

(research.py:18006). Pre-fix, the recursive call dropped `uid/research_id/run_id`, severing the Firestore listener mid-retry. FE saw the run flatline despite BE still running.

## Phase 5 — FE-owned

Phase 5 (Google Doc creation + email delivery) is owned by the frontend. After P4 success, the FE picks up all accumulated links from the `pipeline_events` Firestore subcollection, creates the Doc via the Docs API, sends the email via Resend, and emits its own `phase_complete phase=5` event so the P5 dropdown populates uniformly with every other phase. BE has no Doc/email code path. See FE README + ARCHITECTURE for details on that side.

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
| `skip_phase` | `{phase}` | Frontend's default Skip action on every `phase_alert`. Backend's phase coroutine consumes the request and advances past the failing step. For Phase 4, this replaces the old `skip_phase` verb (removed U2); Phase 5 likewise replaces `skip_phase`. `_controls.skip_phase` / `skip_phase` flags remain as internal-only state read by Phase 4/5 polling logic, but no FE command toggles them anymore |
| `feedback` | `{phase, message}` | User feedback injection. Stored per-phase, injected into next phase rerun |
| `retry_phase` | `{phase}` | Frontend response to a phase-level warning (brief-short, brief-timeout, NotebookLM failure, audio timeout, Phase 3 gate). Backend's phase coroutine polls `consume_retry_phase(N)` + loops back to restart |
| `retry_agent` | `{agent}` | Frontend response to a Phase 2 agent warning (timeout, empty-final, send-fallback, session-expiry). Phase 2 polling consumes + submits a follow-up prompt via `paste_followup` |
| `continue_partial_agent` | `{agent}` | Accept Phase 2 agent's current short/timed-out output as final; agent finalizes with status `done_partial` / `timeout_partial` |
| `poke_agent` | `{agent}` | Stuck-agent response: send mild "please continue" follow-up without extending budget |
| `wait_longer_agent` | `{agent}` | Stuck-agent response: reset `last_growth_time`, granting ~20 min before the no-growth watchdog can flag the agent again. (Distinct from the Claude 2-artifact `Wait` button which extends `start_time` by 15 min — different gate, different semantics.) |
| `skip_init_verify` | — | Phase 0 dropdown response — bail verification, proceed to Phase 1 with whatever cookie-fast-path read says |
| `retry_init_verify` | — | Phase 0 `login_required` banner response — re-run Phase 0 verification with a fresh tile (frontend tears down the prior tile, BE re-emits `phase_start`) |
| `skip_agent` | `{agent}` | Skip a stuck Phase 2 agent from `BackendSilentBanner` / `HumanVerifyBanner` / `agent_alert`. Polling loop drops the agent from `pending` on the next tick |
| `dismiss_alert` | `{alert_id}` | No-op on BE; FE clears its alert slice locally + records dismissedAlertIds so re-emits with the same id are suppressed |
| `discard_run` | `{alert_id}` | Watchdog T3 "Discard" action — emit `pipeline_complete` with `status="terminated_by_user_discard"` + schedule clean server exit. Preserves any partial results already on disk |
| `ping` | — | Watchdog confirmation ping. BE marks the doc processed + writes `pongedAt` timestamp the watchdog reads back. Fast path — no `_controls` side effects |

> **Dispatcher resume-contract (2026-05-18)**: every action that acknowledges a paused alert MUST call `_controls.request_resume()` so the pipeline doesn't stay paused after the user clicks the action button. The per-action helpers (`request_skip_agent`, `request_retry_agent`, `set_continue_anyway`, etc.) already clear `pause_event` + set `resume_event`; the dispatcher's explicit `request_resume()` ALSO clears `pause_reason` + `pause_target_agent` — a state-leak class that previously kept FE rendering "paused" even after Retry. The 8 actions covered: `skip_init_verify`, `retry_init_verify`, `skip_agent`, `retry_agent`, `continue_partial_agent`, `poke_agent`, `wait_longer_agent`, `continue_anyway`. Plus the 5 already-correct ones (`pause`, `resume`, `skip_phase`, `retry_phase`, `agent_decision`). Plus 8 intentionally-not-resumed actions (`pause`, `stop`, `discard_run`, `ping`, `add_context`, `config`, `dismiss_alert`). Static-analysis test `tests/test_dispatcher_resume_contract.py` (4 cases) enforces the contract — adding a new resume-required action without wiring `request_resume` fails CI.

> **CLI dispatcher pause-reason routing (DGOPS-7710 / F6 + 3 follow-ups)** — same root pattern surfaces on the CLI side. When an alert pauses with a `pause_reason` (`agent_link_failed`, `human_verification_required`, `cua_unavailable`, `claude_chat_mode`, `login_required`, `pro_required`), the CLI `r` / `s` keystrokes route to the correct alert-specific helpers (`set_agent_decision`, `set_continue_anyway`, `request_skip_agent`, `request_skip_init_verify`) **plus** `request_resume`. Before the fix, `r` only called `request_resume` and the consume site defaulted user-intended "retry" to silent "skip".

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
| `phase_restart` | (no FE handler — C3 cleanup) | telemetry only; phase tile updates in place, no banner |
| `pipeline_stopped` | `pipeline_stopped` branch (legacy paired event) | error panel with humanized error text |
| `human_verification_required` | `human_verification_required` branch | per-AGENT (not phase) alert via `setAgentAlert` — listed here because it's part of the same alert system |
| `agent_link_failed` | `agent_link_failed` branch | per-AGENT alert with `[Retry, Skip]` actions |
| watchdog T1 silence (per-phase tier 1) | `startFirestoreListener` watchdog interval | warn-level dropdown alert with **Dismiss** only + OS notification. Heartbeat-gated: only fires when heartbeat-stale (>2 min) AND silence ≥ T1. Pipeline keeps running. |
| watchdog T2 silence (per-phase tier 2) | same | warn-level dropdown alert with **Retry phase** + **Skip phase** + OS notification. Dedup gate (Stream 2) excludes same-phase T1 watchdog alertId so T2 cleanly replaces T1. Pipeline keeps running — T2 doesn't auto-stop. ChatContainer separately surfaces the checkpoint-resume CTA when status flips to `stopped_by_watchdog`. |
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

**Action semantics recap:** action buttons in a panel come from the source event's `actions` array. The FE renders them via `PhaseAlertPanel` / `AgentAlertPanel`; tapping a button writes the embedded `command` (`{action, …}`) to the research's `commands` subcollection. Phase 4/5 use the unified `skip_phase phase=N` verb (legacy `skip_phase` / `skip_phase` were removed in U2).

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
| Persist failure (Firestore write fails on shutdown handover) | Marked `status:"paused_backend_restart_failed"` + `lastError` field with the actual exception. FE renders red error banner instead of green checkpoint banner. (2026-04-30 `6545335`.) |

Frontend renders the new status as a phaseAlert at the last-known phase:
- `[Resume from checkpoint]` → calls `POST /api/pipeline?action=resume&id={backendRunId}` → backend enqueues job with `resume_dir=queue`; `run_pipeline` uses `detect_resume_phase()` to skip to the right phase.
- `[Discard + start new]` → clears the alert locally; queue directory stays on disk as a backup.

Checkpoints that survive the crash, all under `queues/{run}/`: `documents/*.md`, `delivery.json`, `links.json`, `podcasts/*.m4a`, `checkpoint.json`, `phase2_complete.marker`. Missing state (browser + CUA session) is re-created by the resume run. (The legacy `tracks/*.json` per-agent scrape snapshots were removed alongside the tracks/ directory tree on 2026-04-29 — `documents/*.md` is the single source for Phase 2 output now.)

---

## Tier Escalation Tracking + Phoenix Resume (C1, Apr 28)

Unified per-(op, agent) attempt tracking for retry/escalation across BE operations. Replaces ad-hoc tier_transition emits with the centralized `emit_tier_transition()` helper.

**TierEscalation class** (`research.py:2580+`) — one record per (`op`, `agent`) pair, with a 30-min sliding window:
- `attempts: {T0, T1, T2, T3}` — counters bucketed by tier label
- `window_start: float` — counters auto-reset after `_TIER_WINDOW_SEC = 1800`
- `history: list[{tier, ts_ms, reason, attempt}]` — bounded at 50 entries
- `to_dict()` / `from_dict()` for checkpoint serialization

**Tier ladder semantics (crash-recovery):**
| Tier | Action | Budget |
|------|--------|--------|
| T0 | In-place retry | up to 3× (≤30s gap, ≤90s total) |
| T1 | Tab restart (close → reopen → retry) | up to 2× |
| T2 | Full-browser restart (`browser.stop()` → `browser.start()`) | once |
| T3 | BE Phoenix exit via daemon-loop (saves to `_pending_queue.json`, exits 0) | once per window |

> **Naming note:** these T0/T1/T2/T3 labels are the **crash-recovery escalation ladder** and are unrelated to the **interaction tier ladder** in `DG Research/VisionRecipe.md` (DOM = tier-1, Vision = tier-2, CUA = tier-3). The two systems coexist; the `from_tier`/`to_tier` fields on `tier_transition` events use the *interaction* labels (`dom`, `cua`, `vision`).

**Centralized emit:** `emit_tier_transition(*, phase, agent, op, from_tier, to_tier, reason)` calls `TierEscalation.record(to_tier, reason)` then fires the `tier_transition` event with the new attempt counter. The 6 wired hotspots are:

| research.py site | `op` | `agent` | direction |
|------------------|------|---------|-----------|
| `extract_share_link_chatgpt` | `p2_share_extract` | chatgpt | dom→cua |
| `verified_paste_brief` → `cua_paste_fallback` | `brief_paste` | platform | dom→cua |
| ChatGPT P1 activity panel | `open_activity_panel_p1` | chatgpt | dom→cua |
| Round-robin gemini share | `p2_share_extract` | gemini | dom→cua |
| Claude artifact panel | `open_artifact_1` | claude | dom→cua |
| ChatGPT P2 activity panel | `open_activity_panel` | chatgpt | dom→cua |

**Checkpoint enrichment:**
- `tier_escalation_history: dict[str, dict]` — full registry of TierEscalation records, keyed by `f"{op}:{agent.lower()}"`
- `agent_states: dict` — per-agent runtime state mirror so a Phoenix restart rebuilds "where each agent was"
- `last_event_id: str` — `f"{ts_ms}_{event_type}"` cursor so the FE can dedup events on resume

**Phoenix T3 resume — `_pending_queue.json`:** the in-memory `_job_queue` (asyncio.Queue) is lost on BE exit. The worker writes a snapshot `{ts_ms, current, pending}` to `queues/_pending_queue.json` after every `_job_queue.get()` and again in the `finally` block. On startup, after Firestore-driven rehydration runs, the disk snapshot is read and any research_id NOT already in the rehydrated set is re-enqueued. Covers the gap where a job got `put_nowait`'d locally but the Firestore `status:"queued"` write hadn't landed yet.

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

*Updated: 2026-04-18 — added `phase_alert` + `phase_alert_clear` events with per-phase emit matrix; new commands `continue_anyway` / `skip_phase` / `skip_phase` (all wired via `_controls.set_*`); HV cooldown 45s → 180s; queue persistence across `--daemon-loop` restart.*

*Updated: 2026-04-19 — **Sequential Phase 0 verification** (one platform at a time — cookie → tab-open → CUA → `login_required` scoped to that platform; matches `--setup` script's walk). **Cookie-only per-phase login probe** (runs on every phase regardless of `skipInitVerify`; `cookie_login_hit` read only, no tabs/CUA; catches mid-run session drift). **`phase_narration` event** (Gemini 2.5 Pro narrator emits one human-readable sentence every ~45s during active phases; frontend `/api/narrate` fallback fills >15s gaps with speculative "Likely: …" entries). Frontend stack: `phaseNarrations` store slice + `<PhaseNarrationLine>` + `useNarrationFallback` hook, budget-capped at 20 fallback calls per run.*

*Updated: 2026-04-19 (late-late) — **Phase 2 per-agent extraction rules**: ChatGPT keeps public-share-then-conversation-URL fallback; Gemini + Claude PUBLIC share ONLY, hard-fail on miss. Explicit `[gemini_extractor] method=X result=Y` logs; `link_extracted` per agent the moment a verified link lands. **Claude 2-artifact hard-fail** at ≥80% wait time. **Tab round-robin**: `agent_loop(target_page=None)` + `_anchored_screenshot()`; `bring_to_front()` before every polling tick + after every `execute_action`. **Playwright Claude setup**: `setup_claude_dr` rewritten as 3 Playwright steps (Opus 4.7 dropdown, Adaptive Thinking, Research tool) — no more CUA vision for setup. **Normalized error matrix**: default Retry · Skip everywhere; Phase 2 workspace cap → End research only; Phase 2 poll timeout → Retry · Skip · Wait; removed Poke + "Proceed without CUA"; stuck-agent relabeled Retry/Wait/Skip. **New `agent_narration` event**: per-agent Gemini 2.5 Pro call, ~6s cadence during P1/P2. Backend commit `547bf17`.*

*Updated: 2026-04-30 — **Narration consolidation** (commit `94b7bde`): retired vision narrator (`narrate.py` PHASE_BUDGET=0 default; `DG_VISION_NARRATE=1` re-enables). Per-agent narrator brain swap: Gemini Pro 2.5 → Anthropic Haiku 4.5 primary with Gemini 2.5 Flash fallback (`DG_NARRATOR_USE_HAIKU` / `DG_NARRATOR_HAIKU_MODEL` envs). Tighter anti-parrot prompt (research.py:5904-5933) + chrome scrub on narrator inputs (research.py:5550-5625) — strips `You said:` / `Claude responded:` / `Gemini said` / `brief.md` / `Building:`-prefix composites BEFORE narrator sees them; scrape outputs untouched. Claude DOM scrape: dropped `.font-claude-message` + `.contents` heading selectors (research.py:7116-7124). ChatGPT P2 walker: dropped `[class*="row" i]`; added 23-verb VERB_GATE + min-len 4→12 (research.py:7979-7984). **P1 ET fallback** (`86d0ab4`): dropped duplicate elapsed-time bit at research.py:9601-9604 — parent card already shows elapsed. **Stuck-state risk fixes** (`6545335`): manual brief 3h backstop (`_BRIEF_WAIT_BACKSTOP_S`); pending queue persist-failure surfaces `paused_backend_restart_failed` status; dead-tab guard before soft retry at research.py:10380. **Browser crash + P2 timeout** (`be8f7b3`): always-auto, no human prompt — browser crash emits passive `emit_browser_recovery_status` banner + bypasses run_pipeline.finally retry guard; P2 agent timeout drops alert + `await_agent_decision`, saves partial if ≥200 chars and auto-skips. **NotebookLM derived-stems filter** (`70e2ab2`): `_DERIVED_STEMS = {"brief", "consolidated"}` excluded — never uploads consolidated.md. **Auto-retry kwarg forwarding** (`549f079`): forward `uid/research_id/run_id` on retry recursion (research.py:18006) so Firestore listener stays attached. **Doc upload wiring** (`8a05227`): P1/P2 attach + Flow B unblock; `attach_brief_file` extended with `extra_files` for multi-file `set_input_files`. **P2 ChatGPT** (`bf66c9d`): continuous activity-panel scrape mirroring Claude artifact pattern. **patchright** added to `requirements.txt` (`221394d`).*

*Updated: 2026-05-18 (late) — **Pair flow stages reordered (Linux smoke pass surfaced 3 issues)**: Stage 3 ↔ Stage 4 swap so API keys come BEFORE browser logins — CUA + Vision are now available for login verification AND the Pro-tier check (`_cua_pro_tier_call`); before this, those fell back to Playwright-only whenever the user hadn't pre-set the Anthropic key in env. Banner header "Four steps" → "Five steps" with sequence Token → On Startup → API Keys → Logins → Ready. Stale "Step 2" / "Stage 3" references in code comments + log strings swept. **F4 / DGOPS-7451 cookie check relaxed**: refuses pair only on account-switch (`_initial_paired_uid` != `linked_uid`); first-pair + same-account re-pair pass through with a passive `security_pair_allowed_with_prior_cookies` event. Eliminates the catch-22 where `--unpair` preserved the browser profile then `--pair` refused on the same cookies. **New `--unpair --deep` flag**: also wipes `~/.super-research/browser-profile/` (`shutil.rmtree`, ignore_errors=True). Default `--unpair` unchanged. Closing message branches on `browser_wiped` flag.*

*Updated: 2026-05-18 — **Pair flow renumbered 4 → 5 stages** (commit `ec34481`): new Stage 4/5 = API-key detect-or-prompt for Anthropic + Gemini. Detects via `resolve_api_key()` / `resolve_gemini_api_key()`; if any source resolves (Firestore / Windows user-scope / shell rc / `.dg-supervisor.env`), the prompt is skipped. On paste: writes Firestore `users/{uid}/settings/prefs.apiKeys.<name>` (merge — same path FE Account page writes) + `os.environ` (both var names per key) + busts `_RESOLVED_KEY_CACHE`. Skip first-class per key. Helpers `_save_api_key_to_firestore` / `_pair_prompt_one_key` / `_pair_prompt_api_keys` live just before `run_pair`. **Claude P2 clarification auto-reply** (commit `897353f`): new 5-condition detector in `poll_all_agents_round_robin` per-tick. When user submits a vague brief and Claude responds with chat-text clarifying questions ending with the "Once you ... I'll launch the research" sign-off (matched by `_CLAUDE_CLARIFICATION_SIGNOFF_RE`), the loop auto-types `"Up to Claude to decide for the best output."` + Send-button (Enter fallback) so the agent proceeds without operator intervention. One-shot per agent via `claude_clarification_replied` flag; resets `start_time` / `last_heartbeat` / `last_growth_time` / `stuck_warned_at` / `last_artifact_scrape` after firing. **Dispatcher resume-contract** (commit `1d0366b`): all 8 Firestore command-action handlers that lacked explicit `_controls.request_resume()` now have it (`skip_init_verify` / `retry_init_verify` / `skip_agent` / `retry_agent` / `continue_partial_agent` / `poke_agent` / `wait_longer_agent` / `continue_anyway`). `request_resume()` also clears `pause_reason` + `pause_target_agent` (per-action helpers don't) — closes a state-leak class. Static-analysis test `tests/test_dispatcher_resume_contract.py` enforces the rule. Mirrors the F6 (`f7aa842`) + 3 pre-existing CLI bug fix pattern (`79d6f7e` — `agent_link_failed` / `human_verification_required` / `cua_unavailable`). **Cross-platform supervisor (Track C, code-shipped, smoke-pending)**: macOS launchd (PR1 `bebe4fa`) + Linux systemd-user (PR2 `feature/track-c-pr2-linux`) gated behind `DG_ALLOW_CROSS_PLATFORM=1`. Env-file pivot (PR-Env `fc944a0`) decoupled Track C from Track B. PR3 (drop gate) pending real-hardware smoke verification. Dispatcher `_supervisor_platform()` routes between Windows Scheduled Task / launchd plist / systemd-user unit. Dead `_heartbeat_task = None` removed at research.py:1295 (commit `bce1e90`). `tests/fixtures/vision/auto/` added to `.gitignore`.*
