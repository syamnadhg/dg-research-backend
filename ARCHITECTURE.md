# Super Research Backend — Architecture

Backend architecture + Frontend ↔ Backend contract for the Multi-Agent Deep Research Pipeline. Covers phase structure, event/command protocol, retry/continue/skip decision gates, phase-restart semantics, backend-restart resume flow, and watchdog spec.

> ⛔ **NO LINE NUMBERS IN THIS FILE.** Name the symbol; a grep finds it and stays
> correct. Sixteen `research.py:NNNN` citations lived here and on 2026-09-03
> every single one pointed at unrelated code — the file has grown past 76,000
> lines and a citation that rots in silence is worse than no citation, because
> it reads as evidence. A test enforces this, and it enforces one more rule: a
> retired symbol may be named only on a line marked ⛔, so a correction can say
> what it corrects without the mention reading as a live claim.

---

## Running the Backend

The backend ships as the **`superresearch` console command** (recommended). Install it with one command from **[superresearch.io/install](https://superresearch.io/install)** (it sets up Python/pipx for you), then run it from any directory — no checkout to manage; data/config live under `~/.super-research/` + `.dg-supervisor.env`:

```bash
# Install (one command — see superresearch.io/install)
irm https://superresearch.io/install.ps1 | iex        # Windows
curl -fsSL https://superresearch.io/install.sh | sh   # macOS / Linux

superresearch --pair      # one-time pairing + browser logins
superresearch --serve     # run the backend
superresearch "<topic>"   # one-shot CLI run
```

`superresearch <flags>` is a pure drop-in for `python research.py <flags>` — identical flags (`--pair` / `--serve` / `--resurrect` / `--retire` / `--restart` / `--unpair` / `--visibility` / `--doctor` / `--send-logs` / `--update` / `--uninstall` / `--version` / `--login` / `agent`), identical branded UI. ⛔ `--commands` is not one of them any more — the branded reference card it printed became `--help` / `-h` itself (`run_commands_help`, `add_help=False`), which is the only discovery surface there is. `--update` is **idempotent** — it only reinstalls when the installed build is actually outdated. `--login` runs a per-profile Y/N login walk (parity with the pair flow's **Browser logins** step — named rather than numbered, because the arc has renumbered twice and a step number in this sentence rots silently) fronted by a READ-ONLY pre-probe that never blows away an already-signed-in session (it does NOT run the patchright verify pass). Invocation-aware help shows whichever prefix matches how it was launched (`superresearch` when installed, `python research.py` from a checkout).

The **source / developer path** is unchanged and still fully supported:

```bash
git clone …
cd …
pip install -r requirements.txt
python research.py --pair
```

> **Chrome:** `--pair` and `--doctor` now auto-fetch the patchright Chrome wrapper (`patchright install chrome`). Real Google Chrome remains an OS-level prerequisite.

> **Chat-runtime agent (separate package):** the `/sr` chat skill is installed differently — `pipx run superresearch-agent connect`. The backend's own front door `superresearch agent <verb>` (installed build) delegates to `pipx run superresearch-agent <verb>`; a source checkout runs the in-tree agent. Don't conflate the two packages.

---

## Pipeline Phases

The pipeline has **6 phases** (0–5). Each phase has a backend execution step and a corresponding frontend visualization.

| Phase | Name | Platform(s) | Description |
|-------|------|-------------|-------------|
| 0 | **Init** | system | Launch Playwright browser, load persistent Chrome profile, verify logins |
| 1 | **Research Brief** | brief | ChatGPT Pro's latest thinking model generates a comprehensive research brief from the user's topic |
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

---

## Multi-Worker Architecture

A backend can run **N concurrent pipelines** in parallel when `research_config.json.workerCount` is set above 1 (default 1, common production setting 2). Each worker is a separate Python subprocess spawned by the daemon-loop supervisor on adjacent ports (8000, 8001, …); each independently subscribes to `devices/{deviceId}/queue/` and `devices/{deviceId}/commands/`, pins to its own browser-profile dir (`~/.super-research/browser-profile-N/`), and runs its own pipeline coroutine.

**Config + load path:**
- `load_worker_count()` (research.py) reads `research_config.json.workerCount` with a `max(1, n)` clamp so a bad value can't disable the only worker.
- `save_worker_count(n)` (research.py) atomic-writes back via `_atomic_write_json` — partial-write safe.
- BE publishes `workerCount` on every heartbeat to `devices/{deviceId}` (research.py) so the FE knows N when deciding ongoing vs queued.

**Per-worker safety guards:**
- **On-disk worker lock** (`safe_enqueue_lock_*`) — prevents two workers from claiming the same queue doc on a back-to-back supervisor restart (one-cycle race).
- **Listener `_pending_enq` counter** — prevents back-to-back claims caused by Firestore listener replay (the listener re-fires on reconnect; counter blocks dual-enqueue of the same `research_id`).
- **Pre-claim status re-check** (added 2026-05-22, commit `bcc4f84`) — between the claim scan and the actual `_safe_enqueue`, the worker re-reads `research.status`. If the doc transitioned to a terminal status (`stopped`, `completed`, `archived`, `terminated_by_user_discard`, `stopped_by_watchdog`) in the meantime, the claim is dropped. Closes a cross-worker race where worker A could claim a doc that worker B already cancelled.

**Cross-worker HARD_RESET:** Reset Pair Code writes a single `hard_reset` command to `devices/{deviceId}/commands/`. Every worker subscribes to the same subcollection — each processes the command independently, touches `.stop` on its own active run dir, flips its own active research doc to `cancelled`, and schedules `os._exit(0)` so the daemon-loop respawns it with a fresh listener subscription. No zombie runs across N workers.

**Worker rest/wake (#903):** the owner can park an idle worker from the app's Shared-With popup (tap an idle worker pill → resting), recorded in the **owner-writable** `devices/{deviceId}.restingWorkerIds[]` field. A resting worker takes **no new runs** — the check gates both new-claim paths (`_worker_is_resting()` at the start-listener claim and the idle-rescan claim; fresh device-doc read, ~3s TTL, **fails open** to awake so a Firestore blip can never pause the device). In-flight runs finish untouched (resumes bypass the listener). When **all** workers rest, new submits queue with a "Workers paused" state instead of starting; the state persists across BE restarts. Sharers never see worker pills. The 12h ABANDONED queue sweep exempts rest-deferred docs (measured from a `restDeferredAt` keep-alive) so a run parked behind a long rest survives a restart.

**Reading the worker logs:** each worker prefixes log lines with `[WORKER N]` so multi-process logs interleave cleanly in supervisor stdout. WORKER_ID is `os.getpid() % 1000` for human-readable identification.

---

## Queue Position Invariants

Queue ordering and per-doc position numbers stay coherent across cross-account, cross-worker, and cancel-mid-defer scenarios via four BE rules — all in `research.py`, all touched by the 2026-05-22 cycle.

1. **FIFO sort key is `submittedAt` (Firestore serverTimestamp), not client `timestamp`** — `_queue_doc_fifo_ms` helper (research.py) prefers the server-set timestamp and falls back to `timestamp` (client `Date.now()` millis) only when `submittedAt` is missing on legacy docs. Removes the cross-account clock-skew bug where a sharer's lagging clock could rank ahead of the owner's earlier submit. Commit `41d0a27`.

2. **Real-time renumber on every claim and cancel** — `_recompute_deferred_queue_positions` (research.py) does a single scan of `devices/{deviceId}/queue/`, sorts by the helper above, filters out `assignedWorker` / `processed` / non-`start` docs, and batch-writes new `queuePosition` / `queuedBehindRunId` / `queueTotalAhead` / `queueAheadFromSelf` / `queueAheadFromOthers` / `queueEtaMs` / `queueEtaComputedAt` to every remaining deferred research doc in one round-trip. ⚠ Read that as a closed list only if you keep it closed: `queueEtaComputedAt` rides all three patch shapes and was missing from this enumeration until 2026-09-19. ⛔ `queuedBehindTitle` is in that patch as a **field delete**, not a value — 7.7E (2026-09-04) stopped publishing another account's topic on a record every sharer reads; a delete rather than an omission so a pickup removes whatever the previous one wrote, and the key stays on the rules whitelist because a `deleteField()` still lands in `affectedKeys`. Fires from three sites: (a) listener claim path (`_enqueue_with_position_refresh`, research.py), (b) idle-rescan claim (research.py), (c) `_do_cancel` deferred-cancel branch (research.py). All three call sites wrap the helper in `asyncio.create_task(asyncio.to_thread(...))` so the synchronous Firestore scan never blocks the asyncio loop or the listener thread. Commit `c362126`.

3. **Cancel of a deferred (Firestore-resident) doc** — `_do_cancel` (research.py) was extended to handle the case where the cancel target isn't in the local asyncio deque. The handler scans `devices/{deviceId}/queue/`, finds the start doc whose `researchId` matches, deletes it, flips the research doc to `status="stopped"`, then fires the deferred-recompute helper above so the remaining queue renumbers live. Commit `bcc4f84`.

4. **Worker count + cross-user awareness in defer decisions** — the listener at `research.py` checks `is_busy or _gate_will_block`, and the FE-side `usePipeline.startPipeline` checks `ongoing >= workerCount OR queued > 0` (per-device, cross-account). Sharer's FE uses `device.currentRunId` as a cross-user "device busy" signal when its own `cachedResearches` scan can't see the owner's run; 24h `currentRunIsStale` cutoff prevents crash-leftover values from blocking fresh submits.

**Where each phase runs:**
- Phases 0-3 run **BE-side** (Python daemon on user's PC — needs the local browser for ChatGPT / Gemini / Claude / NotebookLM).
- Phases 4-5 run **FE-side** (Firebase App Hosting / Cloud Run — Data API + Resend, no browser needed). FE-P4 fires off BE's `phase_complete:3` (or `phase_skipped:3` for the no-audio path), then chains directly into FE-P5 on success or fast-path skip. BE exits cleanly after P3 with `delivery.status="completed"`; the user-visible `research.status` stays "ongoing" until FE-P5's `markFeP5Completed` flips it to "completed".
- **BE-driven P4/P5 (autonomous, #742 / BE `79d943f`)** — the live `phase_complete:3` event is one trigger, **not the only one**. So a run finishes even when the chat app never opens, after P3 the BE also calls `_post_fe_p4p5_trigger(uid, research_id)` (research.py) from a detached daemon thread: it writes a `needsFeTrigger` marker AND POSTs `{FE_BASE_URL}/api/uploadYouTube {research_id, ownerUid}`, authenticated with the synth-device user's own fresh ID token; the route runs P4 then chains P5. `casRouteP4` dedups this against the live-event FE catch-up so both triggers coexist.

---

## Event Types

All events are JSON objects written to `events.jsonl` (one per line) AND mirrored to Firestore `users/{uid}/researches/{id}/pipeline_events/` for real-time frontend delivery.

| Event Type | Phase | Fields | When |
|-----------|-------|--------|------|
| `phase_start` | 0-5 | `{agents?: string[], description: string}` | Phase begins |
| `phase_restart` | 1-2 | `{phase, reason, chars, attempt?}` | Phase rerun after pause+input+resume (mid-phase or boundary) |
| `agent_progress` | 1-2 | `{status, stage, progress, sources, sourceUrls, sections, partialTextLen, model, thinking, steps, plan, toolUses, elapsedSec, expectedMinutes, scrapeOk, scrapeSource, visionNarration}` | During Phase 1/2 polling (~120s interval, `POLL_DEEP_RESEARCH` default). `stage` (`"planning" \| "researching" \| "writing"`) drives the FE milestone stepper — it advances an agent off "Submitted" the moment a real counter is scrape-blind. P1 emits it from `poll_until_done` (#924); P2 emits it continuously from the round-robin poller + launch sites + hard-retry (#930), with `"planning"` gated on the scraper's plan-page signal so a planning Gemini stays on "Submitted" by design. Empty `stage` is omitted so it never clobbers a prior value in the FE merge. `scrapeSource: "dom" \| "vision"` records which tier produced the data. `visionNarration` is populated by the agent-side-panel walker when DG_VISION_NARRATE=1 OR when the vision-narrator fallback is exercised (see `_vision_narration` / `_vision_narration_p2` emits at the P1 + P2 sites); when neither fires it's empty string. FE renders verbatim when present. |
| `agent_skipped` | 2 | `{agent: string}` | Disabled agent in Phase 2 config |
| `agent_verified` | 2 | `{agent: string, verified: bool}` | Agent confirmed running |
| `link_extracting` | 3 | `{agent: string}` | Notebook-link read starting. ⛔ Phase 3 only — all three of these come from `extract_with_retry`, whose one caller is NotebookLM |
| `link_extract_retry` | 3 | `{agent, attempt, maxAttempts, description}` | Notebook-link read retried |
| `link_extracted` | 1-4 | `{agent, url, label, verified, primary?}` | P1/P2: the report's page in OUR app, `primary=true`. P3/P4: a validated third-party link. ⛔ Never a conversation address — see stretch 7.5 |
| `link_extraction_failed` | 3 | `{agent: string, error}` | Notebook-link read failed |
| `agent_link_failed` | 2 | `{agent, attempts, lastError}` | ⛔ The name is a wire contract, not a description: the only live producer is Claude finishing without its report artifact. `attempts` is hardcoded 1. **Does not pause** — parks the agent for 300s while the others keep polling |
| `phase_complete` | 0-5 | `{durationSec, links: [{label, url, verified, primary?}], skippedAgents?, erroredAgents?, skipped?, summary}` | Phase finishes. `skipped` is the wipeout marker the app reads to tell "produced nothing" from "was never asked" |
| `phase_skipped` | 1-5 | `{reason: string, detail?, durationSec?, links?}` | Phase disabled in config — **and, since stretch 6.6C, a Phase 3 that produced no deliverable podcast** (`no_audio_generated` / `audio_generated_but_upload_failed`; see *Phase 3 completes on a podcast* below). ⚠ The app reads `detail` on this event and `summary` only on `phase_complete`, so a sentence meant for the user goes in `detail` or it reaches no surface |
| `pipeline_paused` | N | `{phase, reason?, agent?, snapshot?}` | Pipeline paused. Reasons actually emitted: `login_required`, `pro_required`, `human_verification_required`, `cua_unavailable`, `google_credential_expired`, `phase_timeout`, `login_interrupt` — and NO reason at all when the user pauses, which is the common case. ⛔⛔ **The last two were missing from this row and the repo's own guard test cannot see them**: `tests/test_doc_matches_code_0903.py::test_the_table_lists_every_reason_that_is_emitted_and_no_others` extracts `request_pause("…")` string literals, not the `reason=` kwarg on the event, and both of these sites call a bare `request_pause()`. Its docstring still asserts that `phase_timeout` is a `pipeline_stopped` reason and that neither pauses anything; `_phase_timeout_decision` emits `pipeline_paused reason="phase_timeout"` one line after `request_pause()`, so the docstring is the thing that is wrong. Read the row against `emit_event("pipeline_paused"` in `research.py`, not against that test. `phase_timeout` is the hard per-phase ceiling gate — four call sites (P1 at `PHASE_1_MAX_MIN`, P2 at `PHASE_2_MAX_MIN`, the P3 upload and the P3 audio sub-step) — and it pauses only to freeze the active-time clock while the user answers Retry/Skip. `login_interrupt` is `run_pipeline`'s failure path recognising that `--login` closed our Chrome on purpose. ⭐ `google_credential_expired` is raised at phase 0, BEFORE the work: the identity that creates the research document is pinned by design (a document lands in one Drive) so nothing can rotate around it, and on 2026-09-03 a revoked grant was discovered at minute 40 of a 40-minute run. Blocker, Retry only — the sign-in is reconnected out of band. ⛔ The value this row used to name for that case is emitted nowhere. ⛔ `agent_link_failed` is reachable only from the orphaned gate, so in practice it never appears either. ⛔⛔ `snapshot` is the app-facing runtime snapshot and is **deliberately smaller than the one on disk** — see the *2026-09-03 (stretch 7.5)* entry at the foot of this file, second bullet (this row used to point at a "Pause snapshot" section that has never existed) |
| `pipeline_resumed` | N | `{phase: number}` | Resumed from pause |
| `pipeline_complete` | — | `{summary: string}` | All phases done |
| `pipeline_stopped` | N | `{phase: number, reason}` | User requested stop OR backend watchdog detected disconnect |
| `pipeline_error` | N? | `{error: string, agent?: string}` | Fatal or agent error |
| `pipeline_warning` | N? | `{agent?, message}` | Non-fatal warning (e.g., post-P2 `add_context` dropped, residual extra_context at phase boundary) |
| ~~`phase_alert`~~ | — | — | **Frontend-synthesized, never emitted by backend.** The FE derives `PhaseAlertPanel` state from `pipeline_error` / `pipeline_warning` / `login_required` / `phase_restart` / `pipeline_stopped` / watchdog escalation, then calls `setPhaseAlert(researchId, phase, …)` on the store. Backends should NOT emit `phase_alert` events — they're consumed nowhere. |
| ~~`phase_alert_clear`~~ | — | — | **Frontend-only.** FE clears panels via `clearPhaseAlert(researchId, phase)` on `phase_complete` / `phase_skipped` / pong recovery / user action acknowledgement. Not a wire event. |
| `heartbeat` | N | `{phase, ts}` | Emitted ~60s during long waits so frontend liveness watchdog stays green |
| `login_required` | 0-5 | `{platforms: string[], platformLabels: string[], envErrors?: string[], attempt, message}` | **Phase 0 (Apr 19): sequential — fired with `platforms: [key]` scoped to the ONE platform currently being verified, one at a time until all pass. Phases 1-5: cookie-only probe at phase entry fires this with the missing platforms for that phase regardless of `skipInitVerify`.** |
| `phase_narration` | 1-5 | `{text: string, timestamp: int}` | **Per-phase narrator** — emits one human-readable sentence describing what's happening in the active phase, every ~45s. Fed by a bounded ring buffer (~50 recent events). Warms on `phase_start`, quiet during `pipeline_paused`, tears down on `phase_complete` / `pipeline_stopped`. Frontend stores in `phaseNarrations[researchId][phase]` and renders inside the phase dropdown. **Brain (swapped 2026-05-28):** Gemini Flash primary (env `GEMINI_TEXT_MODEL`, `gemini-3.8-flash` since 2026-09-17 — a numbered pin, re-read against the live GA list rather than recalled) → Anthropic Haiku 4.5 cross-vendor fallback (`claude-haiku-4-5`, env `DG_NARRATOR_HAIKU_MODEL`). *(The U2 cleanup removed the older `/api/narrate` speculative-fallback hook; speculative entries no longer appear.)* |
| `agent_narration` | 2 | `{agent: string, text: string, timestamp: int}` | **Per-agent narrator** — emits one human-readable sentence per active Phase 2 agent every ~6s. Separate API call per agent because per-agent context changes fast during P1/P2. Frontend stores in `agentNarrations[researchId][agentKey]`, rendered by `AgentAccordionRow` as the canonical narration source. Cleared on phase-2 complete. **Brain (swapped 2026-05-28):** Gemini Flash primary (env `GEMINI_TEXT_MODEL`, `gemini-3.8-flash` since 2026-09-17 — a numbered pin, re-read against the live GA list rather than recalled) → Anthropic Haiku 4.5 cross-vendor fallback (`claude-haiku-4-5`, env `DG_NARRATOR_HAIKU_MODEL`). Narrator input is scrubbed of chat-thread chrome (`You said:` / `Claude responded:` / `Gemini said` / `brief.md` / `Building:`-prefix composites) at `_compact_event_for_narration` (research.py) BEFORE the narrator sees it; scrape outputs (chip / step counts) untouched. |
| `tier_transition` | 0-5 | `{op, agent?, hotspot_id?, from_tier, to_tier, reason, attempt}` | **Vision shadow-eval telemetry (Apr 26) + TierEscalation tracking (Apr 28).** Records every escalation between interaction tiers (e.g. DOM→CUA, Vision→CUA). The `attempt` field is the per-(op, agent) counter inside a 30-min sliding window — fed by `TierEscalation.record()` (research.py), centralized via `emit_tier_transition()`. Used by `scripts/vision_shadow_report.py` to compute per-hotspot agreement metrics. Persisted to events.jsonl AND to `logs/vision_shadow.jsonl` when `DG_VISION_TIER=shadow`. |
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
1. **Per-agent narrator (canonical)** — Gemini Flash primary (env `GEMINI_TEXT_MODEL`, `gemini-3.8-flash` since 2026-09-17 — a numbered pin, re-read against the live GA list rather than recalled), Anthropic Haiku 4.5 cross-vendor fallback (`claude-haiku-4-5`, env `DG_NARRATOR_HAIKU_MODEL`); swapped 2026-05-28. Emits `agent_narration` events. Tighter anti-parrot prompt (research.py) + chrome scrub on input window (research.py).
2. **BE phase-fallback tail** — when narrator silent, research.py emits `Extended Thinking active · 12,400 chars drafted` into `progress["progress"]`. FE renders as last-resort tail (`PhaseDropdown.tsx`).
3. **DOM scrape feeds the input window** — `_compact_event_for_narration` flattens events to `key=value` strings, scrubbed of chat-thread chrome before narrator sees them. Sections and step counts still feed FE chips/strips, but the narrator no longer parrots them back.
4. **Vision narrator retired** — `narrate.py` `PHASE_BUDGET=0` by default; set `DG_VISION_NARRATE=1` to re-enable.

**Display chain on the agent card (FE, `PhaseDropdown.tsx`):**
```
agentNarrationText                     ← per-agent narrator (Haiku/Flash)
  || detail.lastNarration              ← persisted last narration on F5/reopen
  || _progressTail                     ← BE fallback (research.py)
  || narrations[stage]                 ← P1 parent card phase narrations
  || generatingFallback                ← "ChatGPT working — fetching live activity..."
  || ""
```

**Display chain on the P1 parent card (FE, `PhaseDropdown.tsx`):**
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

- `_BRIEF_WAIT_BACKSTOP_S = 3 * 3600` (research.py). After 3h with no manual brief, `fail_phase` fires + emits `pipeline_stopped` with `reason="manual_brief_wait_backstop_3h"`.
- FE renders the stopped-by-watchdog status with the same humanized "Manual brief never arrived" message.

## Browser death — two different things under one name (2026-04-30 `be8f7b3`, corrected 2026-08-27)

⛔⛔ **THIS SECTION DESCRIBED A REBUILD-AND-RESUME THAT DOES NOT HAPPEN AT THE
SITES THAT EMIT THE BANNER**, and `browser_crash_copy`'s docstring is the
measurement that retired it: *"Gemini's tab died at 17:21:00 and the phase
reported COMPLETE at 17:21:06 with 2 of 3 agents. Nothing was rebuilt and
nothing resumed — the agent was failed and the run carried on."* One sentence was
covering two failures with opposite outcomes. They are split here.

**A. The whole browser dies and an exception reaches `run_pipeline`** — the
promise holds, and this is the only case it ever held for. `_is_browser_close_error`
classifies the exception (the same string set the `navigate()` retry path keys
on, all CDP-driver strings, so the classification reads identically on every OS)
and sets `last_failure_kind="browser_crash"`. `_plan_pipeline_auto_retry` is then
the single source of truth for what happens next, and it is called twice with
identical inputs — once inside the `except` to decide whether to **suppress** the
user-facing card, once after the `finally` to actually recurse — so the two can
never disagree. A crash bypasses the one-shot gate a normal failure gets and is
capped at `BROWSER_CRASH_MAX_RETRIES` (2) consecutive **silent** retries, i.e.
three browser launches before a human is involved. Terminal or intentional states
never auto-retry: `delivery.json` status in `completed` / `stopped` / `paused`, a
`.stop` or `.pause` sentinel, or a `--login` in flight. Phases 0-4 are eligible for
a crash (a phase-0/1 crash was excluded by the legacy `1 < phase` gate — that was
the #725 bug); a normal one-shot retry keeps the conservative 2-4 window.

**B. One agent's tab dies inside the Phase 2 round-robin** — nothing is rebuilt
and nothing resumes. The per-tick crash sweep runs before any per-agent work,
tests each pending agent's page for `is_closed()`, and for a dead one writes
`results[agent] = {"status": "browser_crashed", …}`, calls `_disarm_registry` (a
crash emits no resolve-seam signal, so a stale armed deadline would auto-skip a
healthy same-key agent on the next run in this long-lived worker), drops the agent
from `pending` and continues. The rotation is not starved and the other two keep
polling. Two cases are taken out before that: a tab **we** closed on a user Skip
is not a crash, and a `--login` in flight raises instead, so the whole run unwinds
to its checkpoint rather than failing agents one at a time into a phantom
"PHASE 2 COMPLETE: 0/3".

**What the person is told, wherever a banner fires at all** — three call sites: the
two poll loops and the P2 crash sweep — is `emit_browser_recovery_status` →
a dismissible `pipeline_warning` with no actions and `auto_clear_on_resume=true`.
⛔ In case A, when a silent retry is planned, the card is **suppressed** and the
only trace is a log line; the silent-self-heal rule is that Retry/Skip appears only
once the auto-retries are exhausted.
Its copy comes from the pure `browser_crash_copy` and **reports only what was
observed** — on the platform's own page, for this long, re-checked this many
times — and names no cause, because a platform stall and our own scrapers going
blind are genuinely indistinguishable from here: `<Agent> stopped responding …
Nothing on your side caused this; the run continued without it.` ⚠ `quiet_sec` is
a **floor, not an age**: an arbiter WORKING verdict rewinds the growth clock up to
`_ARBITER_MAX_WORKING_RESETS` times, so the true silence can be longer than what we
hold, never shorter — hence "at least". ⛔ The clocks are read off the pending entry
**before** it is deleted, because a crash calls no `fail_agent`, nothing persists
"errored", and the exit sweep never sees that agent at all. ⛔ The banner is
suppressed entirely while `--login` is active: no auto-retry is coming, so
"auto-retrying" would be both wrong and alarming, and `run_pipeline`'s failure path
emits the honest login-interrupt card instead.

No human prompt in either case; the previous behavior of pausing for Retry/Skip
blocked recovery.

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

Before soft-retrying a Phase 2 agent (research.py):

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

`_DERIVED_STEMS = {"brief", "consolidated"}` (research.py). Phase 3 NotebookLM upload skips files whose stem matches `_DERIVED_STEMS` — never uploads `consolidated.md` (a P2 byproduct of claude+gemini concatenation) or `brief.md` (Phase 1 input, already implicit in the agent reports). Pre-fix, the scan-fallback loop picked these up as duplicate sources.

⛔ **2026-09-18, wave 10 — `consolidated.md` no longer reaches disk at all**, and
the exclusions stay anyway because runs made before that day still carry the
file. The stacked document was one H1 plus each agent's report verbatim, with no
reader of its own left: the app synthesises the real combined document at P5 from
**the three per-agent reports**, never from the stack. ⛔⛔ The **Firestore
mirror** of the `consolidated` doc type is pinned PRESENT on purpose — the app's
P5 Summary document reads it as its only source and refuses without it, and on
both P5 legs the summary runs BEFORE the synthesis, so deleting the mirror today
would cost every run its Summary silently. The merged text also still reaches its
two in-memory readers (the post-P2 summary refresh and the title refresh), which
is why the BUILD outlived the write.

## NotebookLM Strict-Keep Cleanup (`a52bd7b`, `2a93af0`)

Phase 3 used to lean on a "cleanup-by-delete" pass after audio generation — sweep the studio panel and delete any audio cards we didn't want. That model is deprecated; the current flow is a **strict-keep** cleanup with invariant guards on either side of generation:

- **Pre-flight invariant** — before triggering audio generation, the narrator counts the existing NLM audio cards in the studio panel. The expected baseline is 0 (a fresh notebook); if the count is non-zero the agent reconciles state before clicking generate, so we never start with a dirty studio.
- **Post-generate invariant** — after generate fires, the agent verifies `count == 1` (the new Long + Deep-Dive card is the only one present). A mismatch here surfaces a Phase 3 alert instead of silently letting the wrong card flow downstream to YouTube.
- **Post-completion strict-keep** — once the audio is fully rendered, the cleanup pass deletes any cards that are NOT the Long + Deep-Dive entry, while ALWAYS preserving the Long + Deep-Dive one. The keep-list is the contract; deletions are derived from "everything else", not from a denylist of known-bad shapes. This makes the cleanup robust to NLM UI changes that introduce new card variants.

Within the same flow, the audio-generate prompt itself was tightened (`98bd631`) to keep CUA's click target on the generate button rather than wandering onto the surrounding tile body — a class of misclicks that, pre-fix, occasionally created a second card the strict-keep pass then had to clean up.

## Phase 3 completes on a podcast (stretch 6.6C, 2026-08-28)

⛔⛔ **"`phase_complete:3`, therefore there is a podcast" was a coincidence, not a
rule.** The emit was gated purely on the ABSENCE of four skip flags — a login
pause, a stop, a Skip on the link card, a Skip on the upload-timeout card — and
not one of them read the audio. The app states the invariant in prose and fires
its "Podcast ready" notice off the event, so a run whose bytes never reached
Storage produced a green tile and a notice, while FE-P4 read `links.audio_file`,
found nothing, and skipped the video in silence. Completion and delivery
disagreed about the same run.

The gate now says it out loud: the phase completes when nothing skipped it **and
the Storage upload returned a URL** — the downloaded-and-uploaded podcast, not a
link. Otherwise it emits `phase_skipped phase=3` naming which of the two failed:

| reason | what happened | what the user is told |
|---|---|---|
| `no_audio_generated` | NotebookLM produced no audio overview | the notebook was created, there is no podcast |
| `audio_generated_but_upload_failed` | the file exists locally, the Storage upload did not land | the podcast **is still on the research computer** |

Those are different states with different repairs, which is why one reason
would have been worse than none. The sentence rides `detail`, not `summary` —
the app reads `summary` only on `phase_complete`.

⛔ **The "Audio Overview" link row went in the same round, and it was already
dead.** `audio_overview_url` is empty for the whole of the ordinary run path
(its only other writer is the mutually-exclusive Flow-C hydration of a link the
user pasted), so the append could never fire while its comment still explained
how the app would render it. The app injects that row itself from the playable
Storage file. ⛔ What did NOT change: the notebook URL is still the navigation
target for the audio step, so the loop that recovers it stays — what stopped
being true is that a link decides whether the phase succeeded.

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

(research.py). Pre-fix, the recursive call dropped `uid/research_id/run_id`, severing the Firestore listener mid-retry. FE saw the run flatline despite BE still running.

## The topic guard — a guard at the sink, not at the producer

⛔⛔ **This is what stops 121 KB about golden retrievers being written to
`documents/chatgpt.md`, reported `status=done`, and handed to NotebookLM as source
3-of-3** — which is exactly what the 2026-08-05 e2e shipped. The check existed; it
lived at ONE call site inside `extract_and_record_agent`, which is the path a
**healthy** agent takes. Two other paths reach the same files and neither went
through it: the user-Skip branch calls the extractor directly and drops the raw
string into `results[name]["text"]`, and the Phase-2 finalize re-save loop writes
every `results[name]["text"]` to `documents/<agent>.md` and Firestore. Only the
title guard objected, four seconds after the upload had been queued.

⭐ **A guard on the producer is a guard on the producers you remembered; a guard on
the sink covers the ones you did not.** `reject_off_topic_text(text, queue_dir,
label, agent_key, op=…)` returns the text, or `""` if it is demonstrably not about
this run's topic, and **every path that fills a `text` destined for disk calls it**.

⚠ **Everything uncertain passes** — the asymmetry is deliberate, because firing can
cost a whole leg. `text_is_off_topic` does the deciding and ABSTAINS on: no
`queue_dir`, an unreadable topic, fewer than `_TOPIC_GUARD_MIN_ANCHORS` (3)
distinctive words in the topic, or a document under `_TOPIC_GUARD_MIN_CHARS`
(20,000). It fires only on the shape with no innocent explanation.

## Document images (wave 4, 2026-09-13)

⛔⛔ **Every image in an extracted document used to be deleted, and the two
halves failed differently.** `html_to_markdown` was called with `strip=['img', …]`,
so every HTML capture route dropped each image AND its alt text — Gemini's first
choice, Claude chat mode, Claude research's panel scrape, and the ChatGPT
brief's only route. The routes that save a platform's own markdown (a download,
a copy button) kept `![alt](url)` pointing at the platform's servers, often
signed and short-lived, and nothing ever fetched a byte.

**The shape.** The converter keeps image tags (decorative ones — favicon
services, or a width/height at or under 32px — are dropped). Before a document
is written anywhere, `_rehost_document_images` fetches each image **once per
research**, hands the bytes to the web app (`POST /api/document-images`, the
machine's own device token), and rewrites the destination to the reference the
web **returned**: `/document-images/{researchId}/{sha256}.{ext}`. Anything not
kept, for any reason, becomes `![alt]()` — or disappears when it has no alt. The
contract lives in dg-research `src/lib/document-images.ts`; the regexes and
raster rules here mirror it exactly (`\A…\Z`, not `^…$`, because Python's `$`
also matches before a trailing newline and the web's anchored JS regex does not).

⚠ **Every length check upstream of the rehost had to learn to discount image
destinations, and `_doc_img_prose_len` is how.** The capture floors and Claude's
30% length-sanity check run BEFORE the rehost shrinks a URL to a reference or a
caption, and a signed platform URL runs to hundreds of characters — so three chart
URLs lifted a 4,000-character **wrong** artifact past the sanity check, and a sparse
container past its floor. Before wave 4 those checks saw no image markup at all
(`strip=['img']`). The helper is `len(text)` with each inline image's destination
left out and the **alt kept**, because alt text is a caption a reader sees; it never
changes the text, and its only readers are the HTML→MD floors and
`extract_and_record_agent`'s length-sanity.

It is **the** funnel, and it is idempotent — a reference to this research is left
alone, so a second pass costs no fetch. Call sites: `extract_and_record_agent`
(after the topic guard, so an off-topic document's images are never fetched, and
before the first write, so the local `.md`, the Firestore document and the
consolidated report all carry references), `_rehost_result_texts` for salvaged
partials and resumes, and `_rehost_skipped_brief` plus the Phase 1 brief sites.

⛔⛔ **THE FETCH IS THE RISK, because the URL comes from text a platform
produced** — and the prompt behind that text may have been written by somebody
the owner shared the machine with. So: https only; a session with `trust_env`
off, no cookies, no auth and no product name in the User-Agent; the address
checked public when the URL is checked, **again for each address the connect
resolves, before a socket is made for it** (DNS rebinding — the second lookup
may answer a LAN host), and the connected peer checked a third time after the
handshake, before TLS and before a byte of the request is written; redirects
followed by hand and re-checked; a hard byte cap; a magic-byte sniff with a
minimum pixel size; never SVG. ⛔ No image URL, alt text or document text is
ever logged — run logs are declared to hold no topic, so what a document's
images produce is one counts-only line: `found · stored · reused · dropped ·
refused · login · failed · linked · captioned · removed`.

**`_DocImgDeadline` — one image's whole clock, and why a timer.** A socket
timeout bounds ONE receive, and a buffered read keeps receiving until it has its
64 KB: a server sending a byte every nine seconds never trips it, in the headers
or the body, and the thread was held while the hard stop outside could only stop
waiting for it. So the deadline cuts every connection the image opened. It
watches a **dup** of each socket, because TLS detaches the socket urllib3
connected and the cut has to act on the connection rather than one descriptor.

> ⛔⛔ **`shutdown` DOES NOT END A BLOCKED READ ON WINDOWS — and does not fail
> either.** It returns success and does nothing, so the `except OSError` never
> fired and `expire()` was a silent no-op on the platform the research computer
> actually runs. Measured 2026-09-18 through the shipped paths: a fetch with a
> 1.0s deadline ended at 10.008s (the socket read timeout — the bound this class
> exists to replace), and an upload whose guard ended at 1.0s ended at 30.012s,
> some 28s past the hard stop the upload margin protects. ⭐ What lands is an
> **abortive close**: `SO_LINGER {on, 0}` makes `close` send RST instead of FIN
> and the blocked read wakes. ⛔ **Order is load-bearing** — calling `shutdown`
> first defeats it and the read goes back to sitting out its full timeout, so on
> Windows the abort is *instead of* `shutdown`, not in addition to it. POSIX
> keeps `shutdown`: it already ends the read and leaves the peer a clean FIN.

**The budgets, outermost first.** A document gets `_DOC_IMG_DOC_BUDGET_SEC`
(120s) of fetching; one image gets at most `_DOC_IMG_PER_IMAGE_SEC` (30s) of
that; the caller's hard stop is the document budget plus a 30s grace. An upload
is the tail of an image already fetched, so it lives in that grace: its whole
request must end `_DOC_IMG_UPLOAD_MARGIN_SEC` before the hard stop, and it is
not started with less than `_DOC_IMG_UPLOAD_MIN_SEC` of that left. ⛔ The caller
waits — the round-robin's polling of the other agents stalls for up to the hard
stop per document.

**What is remembered, and what deliberately is not.** The cache is per research,
keyed by URL (or `data:` + a digest of the data URI) and bounded both ways. A
refusal IS remembered for the whole research — but two verdicts are not, and
each was a real defect:

- ⭐ **The clock is not a refusal (wave 9).** A fetch cut off while the image was
  still being read, ending at or after the DOCUMENT's deadline, is this
  document's spent budget rather than anything about the image. It is counted
  `failed` and never cached, so the next document — a fresh budget — tries again.
  Cached, a chart that happened to start with three seconds left was a caption in
  every later document.
- ⭐ **A moment's failure at the web app is not a verdict.** An upload that never
  started (the run stopped, too little time left) or that the web failed for the
  moment (a 5xx, no answer at all, the guard's cut) returns a never-remembered
  miss. A one-off 503 used to be cached as a failed image for the rest of the run.

**Stop is not exit.** `_doc_img_exit_coming()` reads `_exit_scheduled`, set only
inside `_schedule_server_exit` — the one condition under which a document is
written without waiting on its images. ⛔⛔ NOT the stop flag: the 24-hour pause
limit, a cancel landing in a gate wait and a foreground hard reset all set a
Stop and exit nothing, the run goes on to finalize, and treating that as an exit
wrote every not-yet-stored image as a caption **for good** — a caption can never
become an image again, because the source address is gone from the text.
Whatever ends the wait, the run is marked stopped **before** the fallback pass
reads the cache, so an abandoned rehost stores nothing and remembers nothing.

⭐ **Why this lives in `research.py` and not a module of its own** (see *Module
boundaries*): it needs `log`, the per-run uid / research id and the token
minting, all of which live there — and a new module has to be added to BOTH
`py-modules` and `TOP_MODULES`, where a miss ships readable source.

## Phase 5 — FE-owned

Phase 5 (Google Doc creation + email delivery) is owned by the frontend. After P4 success the FE mints a durable snapshot page for each document this run produced, builds the Doc from those, sends the email via Resend, and emits its own `phase_complete phase=5` so the P5 dropdown populates like every other phase. BE has no Doc/email code path.

⛔ **2026-09-03, step 6 — this said the app "picks up all accumulated links" from the events subcollection.** It does not, and believing it did is what let an unvalidated write into the `links.{kind}` map look like the documented way to get something into a delivered document. The Doc's report sections come from the minted snapshot pages, falling back to an in-app deep link; the keyed `links` map supplies only the notebook, audio and video rows; the user's own pasted links come from `userSources`. See FE README + ARCHITECTURE for details on that side.

## Lint + CI gates

`.github/workflows/be-tests.yml` runs both pytest suites (root `tests/` and
`agent/tests/` — two packages, two suites) plus a scoped **correctness lint floor**:
`E9` + the `F82x` name-error family, with `--ignore-noqa` so a comment cannot
silence a crash. **Style lint stays local and is not a CI gate** — that is
deliberate; nothing fails a build over formatting.

The ruleset and the reason for each exclusion live in the `[tool.ruff]` block of
the root `pyproject.toml` (DGOPS-9508) — single source of truth, not restated here.
Two things to know before touching it: the ruff **version** is pinned as tightly as
the ruleset, because `select` fixes which rules run but not what they find; and
`research.py` must never go back to `from prompts import *`, which blinds F821
across the whole file (it degrades to the much weaker F405 — two guaranteed-crash
defects had been hiding in that gap). `tests/test_no_unresolvable_names.py` guards
both that and the one name-error shape ruff has no rule for: a nested function used
above its own `def`.

---

## Module boundaries — what may be added to `research.py`

> **A new subsystem goes in a new module. Only work that belongs to the existing
> phase-by-phase flow lands in `research.py`.**

That is a standing rule, not an aspiration, and it is written here because until
now it existed **only in a closed Jira comment** (DGOPS-9506, closed will-not-do
2026-08-05). A rule nobody reading this repo can find is not a rule.

**Why the file is not being split.** What could be extracted already has been —
seven subsystems live in their own modules:

| module | subsystem |
|---|---|
| `models.py` | model policy: family-only ranking, no version literals |
| `prompts.py` | the CUA prompt for each phase |
| `vision.py` | the vision client and the tier-2 acting path |
| `narrate.py` | the panel narrator |
| `selfheal.py` | the self-healing selector engine |
| `telemetry.py` | the content-free diagnostics tier |
| `logquiet.py` | log quieting |

*(`vision_test.py` is a fixture-replay tool run by hand, not a subsystem.)*

What remains in `research.py` is one procedural pipeline, phase by phase, plus
the API server that drives it. Splitting *that* does not produce modules; it produces fragments that
only ever call each other in one order and share all of their mutable state
(pipeline controls, the automation ledger, learned known-good model versions, the
self-heal counters, the job queue, clipboard arming — all module-level, all
written from several phases). And no test can protect the refactor: a pure code
move has no behavioural change to assert on, so the suite cannot tell a correct
split from a subtly wrong one. Real verification is a live run of roughly an hour
against paid third-party services.

**⚠ The honest counterweight, measured 2026-09-19 rather than recalled.**

| | lines |
|---|---|
| `research.py` when DGOPS-9506 was filed (2026-07-28) | 54,626 |
| at the will-not-do decision (2026-08-05) | ~58,800 |
| at 2026-08-25 | 75,965 |
| at 2026-08-28, after the share step came out | 74,663 |
| **today (2026-09-19)** | **83,374** |
| the seven sibling modules, between them | 7,077 |

So the file has grown by roughly **42%** in the forty-five days since the
decision, and holds **88%** of the non-test Python outside `agent/` (the figure
this row carried before named no denominator; counting the agent package's own
sources it is 71%, and the number only means something with the boundary
stated). An unbounded trajectory is a real objection and none of the reasoning
above answers it.

⭐ **The only fall on record is the step between the 2026-08-25 and 2026-08-28
rows above, −1,302 lines**, over the days stretch 6.6B removed the P2 platform
share step. ⛔ Read it as what it is: subtraction between two rows measured three
days apart, so it is the NET of everything that landed in that window — additions
included — and not a measurement of the removal. The growth table itself was
re-measured on 2026-09-19; this figure is still derived from it and nobody has
re-counted the commit. It is worth writing down because it is the
only evidence in this table that the trajectory is not one-directional — and
because of what it took to get: 2.2 minutes and 21.7 CUA calls per run bought a
link nothing in the pipeline gated on. The lines came out because the FEATURE
was wrong, not because anyone set out to shrink the file.

**What the rule has actually delivered.** Five sibling modules existed at the
decision; `telemetry.py` (2026-08-18) and `logquiet.py` (2026-08-19) were both
created after it, by this rule, for work that would previously have landed in
`research.py`. The rule bounds *new* subsystems and does nothing about growth
inside the existing flow — which is where the 17,000 lines came from. Both
statements are true and neither cancels the other.

**Revisit the decision if any of these becomes true**

- A second engineer edits `research.py` regularly. Single-author work has been
  hiding what would otherwise be constant merge pain.
- A genuinely separable subsystem is identified inside the remaining flow — one
  with its own state and a narrow interface, not just a contiguous block of lines.
- The live end-to-end run stops being the primary verification, which removes the
  "no test can protect the refactor" objection.

**Practical consequence for packaging.** `research.py` is a compiled module in
the published wheel, so any extraction changes what gets built and must be paired
with a wheel rebuild across the full platform set — see *Package distribution +
supply chain* below, and note that the compile list and the wheel manifest fail
in opposite directions, so a module missing from both satisfies both.

---

## Diagnostics: telemetry, log quieting, support bundles (2026-08 wave)

⛔ **The problem all three solve.** A new owner's machine lost DNS for Google's
hosts. Pairing failed, the reconnect ladder retried forever, the aegis pulse kept
reporting "standing watch", and the only account of the failure anyone ever
received was **a photograph of a terminal**. Nothing on that machine could report
that it was in trouble, because nothing on any machine ever reported anything.

### `telemetry.py` — the content-free tier

What the team can see **without being sent anything**. The obvious design is a
small JSON blob with the sensitive parts scrubbed on the way out; a scrubber leaks
the first time somebody adds a field, and somebody always adds a field. So there
is **no free text at all** — every field is an int, a bool, or an enum.
`research_id` is the module's single string parameter and is regex-guarded to the
shape the frontend actually mints (`chat_${Date.now()}_${counter}`). A research
topic reaching this module is not a scrubbing miss, it is a `TypeError`.

Spools to disk and flushes opportunistically, because **no transport works during
the outage it exists to report**. Imports nothing first-party, so a telemetry
failure can never sit in the path of the thing it is reporting on.

### `logquiet.py` — repeat suppression, not silence

**Measured, not reasoned about.** Three lines, one defect — a true statement
restated until it destroyed the file it was written into:

| Line | Share of the file it flooded |
|---|---|
| `telemetry: no id-token accessor …` | 412 of 1,367 lines — **33.9% of bytes** |
| `[aegis] worker N: standing watch` | 2,274 of 2,754 lines in the last 5 MiB of two raw logs |
| `refresh: network error … securetoken…` | 13,479 of 14,083 lines — **95.7%** |

The first two together were **43.7% of the bytes** in the session log a user sends
with `--send-logs`. Two sentences, half the evidence.

⭐ **The fix is not silence, and that distinction is the whole design.** Every one
of those lines is worth having **once** — the accessor line is the only account of
a wiring fault that made every telemetry batch anonymous, and the refresh line is
the single line that diagnosed a new owner's entire outage. What is worthless is
the 412th copy. A suppressed repeat is therefore **counted, not discarded**, and
the count rides the next line that does get emitted: a reader learns strictly more
from `(+247 since the last of these)` than from 247 identical lines. Imports
nothing first-party, for the same reason as `telemetry.py`.

### Support bundles — quieted at source AND at read time

`_build_log_bundle` assembles a zip; `_tail_bytes` reads the tail of each log
**backwards from the end, on whole-line boundaries**, under a byte budget and a
scan cap (`TAIL_SCAN_MAX_BYTES`, tied to `RAW_LOG_ROTATE_BYTES` so it can always
reach the start of a file that has not rotated). Truncation is **reported** —
`stats["reachedStart"] == False` — because a reader who cannot tell a tail from a
whole file concludes the file begins where the tail begins.

Net effect on a real bundle: **8.36 MB → 2.19 MB**, and the share taken up by the
user's own run rose from **3.3% to 13.1%**. Same bundle, four times the signal.

⚠ The reader is **byte**-oriented throughout. Fixtures in its tests are written
with `write_bytes`, never `write_text`: on Windows `write_text` performs newline
translation (LF becomes CRLF on the way to disk), so the fixture would not hold
the bytes the assertions compare against.

The frontend half — owner-only gating, modern-device gating, the consent copy, the
support code, and the bucket lifecycle runbook — lives in the app repo's
`ARCHITECTURE.md` under "Support logs".

### Whose runs a bundle may carry (2026-09-01)

Only the person who fired a run knows it went wrong, and the picker used to list
the devices you OWN — so a sharer saw an empty list and a disabled button and
could not report a broken run at all. **Owner-versus-sharer was the wrong axis;
the run is.** Everyone picks from their own runs on a machine, and what rides
along is decided at the sink rather than by the request.

⛔⛔ **Attribution was reading the field the rules do not guard.** A start
document carries `uid` (the tree the run executes in) and `submittedBy` (the
writer); `firestore.rules` pins `submittedBy == request.auth.uid` on the device
queue and says nothing about `uid`. Once that stamp decides whose support bundle
may carry a run it is a permission, and a permission may not rest on an unpinned
field. `_resolve_run_submitter` therefore grants attribution only when the two
**agree**, and records which kind of nothing a null is — `local` (no cloud
identity: a `--resume` or CLI topic run), `unclaimed` (a tree, no pinned writer —
every run written by a build older than this one), `disputed` (both present and
different; the owner-control path writes exactly that divergence on a `cancel`,
so it is a real shape and it fails closed). A start doc whose two identities
disagree is refused **at both claim sites**, because the idle rescan would
otherwise turn the listener's refusal into a delay.

The bundle intersects the selection against what the machine actually holds and
fails closed on a run it cannot attribute. ⚠ The machine-level material —
pairing and sign-in sessions, the raw device tails — is the owner's and is
opt-in even for them: measured on one machine, those tails carry eighteen
research ids and fifteen topics against five run folders on disk, so they are
not a bigger version of the runs, they are everything that computer has ever
done for everyone who uses it. A bundle with nothing in it is refused rather
than uploaded, because a support code that explains nothing is worse than a
refusal.

The machine publishes which runs it still holds, **per submitter, into that
person's own tree** (`_publish_run_log_index`, off the heartbeat). Ids only —
there is no topic or title anywhere in a run folder to publish, which is the
same reason the folder name has never carried one. The terminal half is
`--send-logs --select`: a numbered list of what is on the disk, taking `1,3` or
`all` or nothing; ⛔ a RANGE is refused rather than read, since somebody who
meant one and three and typed a dash would otherwise send two.

⛔⛔ **The cloud's half of a run is pulled DOWN to the disk.** P4 and P5 execute
in the cloud, so everything they print has always been in a platform log nobody
cutting a bundle can reach — measured across six run folders, the P4/P5 dispatch
string appears zero times in them against 23 in the machine-wide log. The
collector never reads Firestore (it is disk-only and allow-listed under the log
root), so `_pull_cloud_logs` lands those lines as a FILE inside the finished run
folder, where the existing walk ships them with no collector change and no edit
to the bundle contract. ⚠ It writes into a sealed folder on purpose: the folder
is finalized within milliseconds of the pipeline returning while P4/P5 run for
minutes afterwards, so there is no version of this that lands before the seal.

### Retention — thirty days, with a clock (2026-09-01)

⛔⛔ **The 30-day bound had no trigger of its own.** `_prune_local_logs` had
exactly two callers — arming a run and supervisor startup — so the age bound
only ever fired as a side effect of the machine being USED: a device up and idle
kept 45-day-old folders, and one that never ran another pipeline kept them until
its next restart, which on a long-lived install is never. It now also runs from
the heartbeat, six-hourly, worker-1 only, in a thread, and it starts DUE so a
machine coming back after two months cleans up on the way in.

⛔ **The count bound was being read as the policy.** 60 runs and 30 days are
joined by `or`, so on a busy machine the run half of a person's diagnostics died
in days while the cloud half lived its full thirty. The counts stay — an
unbounded directory on a laptop is a real hazard — and are named
`LOCAL_RUNS_DISK_VALVE` / `LOCAL_SESSIONS_DISK_VALVE` for what they are;
`LOCAL_LOG_MAX_AGE_DAYS` is the policy.

⛔ **The raw tails had no age bound at all** — only `RAW_LOG_ROTATE_BYTES`,
checked at three events and never on a clock. Their two halves are enforced in
different places on purpose: a rolled `.1` is safe to remove from a timer, while
the LIVE file is held open in append mode by the supervisor, so renaming it from
a background tick would strand every later write in an unnamed inode. The live
half therefore rolls at the three points the file is reopened anyway. ⚠ The
promise is stated rather than papered over: *no rolled tail outlives thirty
days, and no live tail outlives it across a restart* — not "no line anywhere is
ever older", which would mean truncating a file somebody is appending to.
⛔ Age cannot be read from mtime (it moves on every append, so a file holding
May survives to September looking new); a `.since` marker records it.

## Package distribution + supply chain

Two packages ship from this repo, both to public PyPI:

| Package | Contents | Installed by | Updated by |
|---|---|---|---|
| `superresearch` | the backend (`research.py` and friends) | `pipx install superresearch` | `superresearch --update`, or the app's Settings → About |
| `superresearch-agent` | the chat bridge + `/sr` skill (`agent/facade/`) | `pipx run superresearch-agent connect` | `agent/facade/selfupdate.py`'s detached reconnect |

### What actually ships inside the `superresearch` wheel

`superresearch` is **not** a source distribution. `tools/build_compiled.py` builds
one platform wheel per OS + CPython minor, compiling the first-party modules to
native extensions with Nuitka:

| In the wheel | Form |
|---|---|
| `research.py` | a ~49-line readable **launcher shim**, nothing more |
| `_sr_core` | the pipeline itself — `research.py` compiled |
| `models`, `prompts`, `vision`, `narrate`, `selfheal`, `telemetry`, `logquiet` | compiled extensions |
| `auth/`, `scripts/` | **source, deliberately** |
| `_sr_build.json` | the provenance stamp — see "Every platform wheel of a release publishes together" below |

**Eight** compiled modules. A wheel showing six or seven was built from a stale
checkout. A `py3-none-any` wheel means the build fell back to source mode and
must never be published. Nuitka sets `__file__` to the original `.py` name even
for a compiled module, so `__file__` is not the signal that something compiled —
the loader (`nuitka_module_loader`) and the absence of a `.py` on disk are.

⛔ **Two lists have to agree, and for six weeks nothing made them.** pyproject's
`py-modules` decides what is PACKED into the wheel; `TOP_MODULES` in the build
script decides what is COMPILED. `selfheal.py` was added to the first and never
the second, so ~1,160 lines of the self-healing selector engine shipped as
readable source in every release from **0.1.2 through 0.1.11**. Nothing caught
it: the build printed DONE, the wheel installed, the suite passed, and the build
script's own docstring asserted the opposite. It was found only by reading a
built wheel.

`tests/test_compiled_wheel_covers_every_module.py` now pins the RELATIONSHIP
(`py-modules ⊆ TOP_MODULES ∪ {shim}`) rather than a hardcoded list — a list would
need editing by the same person who forgot the build script. It also pins the
third leg the first two guards missed: *every module-scope first-party import
must ship at all*. Both pre-existing guards compared those two lists only to each
other, so a module missing from BOTH satisfied both — which is how `telemetry.py`
came within one build of a `ModuleNotFoundError` before the first line of output.
The guard parses with `ast`/`tomllib` and never regex: a regex cannot see a
commented-out `# "selfheal",`, and that direction fails SILENTLY.

One more packaging trap: setuptools' `build_py` copies declared modules into
`build/lib` and never prunes, so a module renamed or dropped from `py-modules`
keeps shipping from a stale copy with no on-disk counterpart. The build clears
`build/` before packing.

⛔ **Every platform wheel of a release publishes together.** `_latest_on_pypi`
reads `info.version` — the **global** latest, platform-blind. The moment a version
exists on PyPI without one platform's wheel, every host on that platform sees
*latest > current*, passes its own last point of no return, shuts the backend down
to free the venv, and runs an upgrade that cannot resolve a wheel: **backend down,
not upgraded**. Neither installer catches it — `install.ps1` disables its platform
guard when the latest release has no Windows wheel, and `install.sh` gates both
its guard and its drift check on a variable that is empty in exactly that case.
Stage all of a release's wheels into one directory and publish in a single
command; `uv publish` does not recurse into subdirectories, so publishing from a
tree that keeps one platform in a subfolder silently ships a partial release.

**Before that command, run `python tools/check_release.py <staging-dir>`.** Each
wheel carries `_sr_build.json`, written by the build BEFORE it compiles: a
fingerprint of the first-party `.py` sources with CRLF read as LF — so a Windows
autocrlf checkout, an rsync copy and a zip of the same code all agree — plus the
git commit and dirty flag where the build tree could say. The check prints every
wheel's stamp side by side and exits 1 if any wheel has none or the fingerprints
differ. Commits are shown, never compared. **It also counts the platforms** —
macOS, Windows and Linux — and names the one that is missing: agreeing about the
source says nothing about whether the release is whole, and a single staged wheel
agrees with itself, so this printed `OK: every wheel (1)` and exited 0 on exactly
the partial release the paragraph above is about. A wheel's platform is read from
its tag as a fragment (`macosx`, `win_amd64`, `manylinux`), so the Mac deployment
target and the glibc version can move without failing the check. An agent wheel
(`superresearch_agent-*`) staged in the same folder is named and skipped: it is a
separate, pure-Python package built once for every platform, so there is no
cross-machine build for it to disagree with. `tools/bump_version.py --check`
covers it before the publish, and `--post-publish VERSION` after it — that step
confirms the version on PyPI, moves the web repo's published version and
agent-log gate, and syncs the hosted skill.

**This is a code-execution supply chain, and it is worth being explicit about
the surface.** The agent self-update resolves from the configured index —
`pipx upgrade`, then `pipx install --force`, then `pipx run --no-cache` as the
non-destructive fallback — and the fetched code runs on the host at the next
update. The route that triggers it, `POST /agent-install`, is unauthenticated on
loopback (see the TRUST MODEL block in `agent/facade/bridge.py`).

### DGOPS-9507 decision — floor by version, do not pin the index

Hash and index-URL pinning stay declined. A **version floor** was added, because
the three invocations do not behave alike and the difference is measurable:

| Invocation | Kind of resolve | Can it install an OLDER build? | Floored |
|---|---|---|---|
| `pipx upgrade <pkg>` | in-place | **No** | no, deliberately |
| `pipx install --force <pkg>` | recreates the venv | **Yes** | yes |
| `pipx run --no-cache <pkg>` | ephemeral venv | **Yes** | yes |

Measured against an index whose newest release was *older* than the installed
one: `pip install --upgrade` (what `pipx upgrade` runs) reported "Requirement
already satisfied" and kept the newer build, while a fresh venv install from the
same index took the older one.

⚠ The rationale recorded here previously credited that non-downgrade property to
**all three** invocations. It belongs to one. Both fallbacks are fresh resolves,
so they have no prior version to be protected by — which is the gap the floor
closes.

`pipx upgrade` stays unfloored for a second, independent reason: pipx **silently
discards** a constraint passed to it. `pipx upgrade 'pkg>=0.1.31'` exits 0
reporting "already at latest version 0.1.30", so a floor there would read as
protection in a diff and do nothing on the host.

The floor is `>=` the version currently running, so an update can never move a
host backwards while re-installing the same version stays possible (repairing a
half-broken venv is a supported use of `--update`). Mechanism, the fail-closed
safety argument, and why the pre-flight must resolve the *same* spec as the
detached waiter are all at `_agent_floor_spec()` in `agent/facade/selfupdate.py`;
`agent/tests/test_selfupdate_version_floor.py` holds the invariants.
`spawn_detached_backend_install()` is deliberately not floored — a first install
onto a host with no backend has no prior version to walk backwards from.

**Why the index pin stays declined.** It breaks any host legitimately behind an
internal mirror, which is a supported configuration. And what it defends against
is *local* index redirection — a poisoned `PIP_INDEX_URL`, `pip.conf`, or process
environment. Every one of those requires write access to the user's home
directory or to the launching environment, and an attacker holding that can
already replace the agent's console script or its venv outright. The pin protects
nothing that is not already lost, at a real cost to mirror hosts. The version
floor, by contrast, costs a mirror host nothing: it still resolves normally, it
just cannot serve a downgrade.

Hash pinning was declined as mechanically disproportionate, not merely tedious:
pip's `--require-hashes` demands every requirement pinned with `==` and hashed,
transitive dependencies included, so `pipx install <pkg>` would error under it.
Adopting it means restructuring all three calls onto a hash-pinned requirements
file and regenerating it every release.

### What actually holds the line: publish rights on the index

The floor bounds *direction* — a host cannot be walked backwards — but it does not
authenticate the publisher, so a compromised account can still ship a higher
version. Both projects must keep 2FA enforced on every account with upload
permission, and the owner list is the security boundary for every host running
the agent: treat adding a maintainer as a production access grant, and re-check
the list at each release rather than on discovery.

The authoritative list is PyPI's own *Collaborators* page per project — not this
file. Naming individuals here would go stale the moment someone joins or leaves,
and a stale access-control record is worse than a pointer to a live one. The
current owner set at the time of the decision is recorded on DGOPS-9507; each
subsequent grant belongs on the ticket that authorises it.

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

> ⛔⛔ **TWO LAYERS: A LOOPBACK BIND (2026-09-05) AND A TOKEN (2026-09-20,
> wave 10.5).** `uvicorn` binds `127.0.0.1`, CORS allows only
> `http://localhost:{port}` / `http://127.0.0.1:{port}`, and **every route in
> the table below except `GET /api/health` requires a shared secret**:
>
> ```
> X-Super-Research-Token: <value of ~/.super-research/serve-api.token>
> ```
>
> The file is 0600, minted at `--serve` boot, and both the boot banner and
> `--help` print its path (never its value). The header is the ONLY accepted
> form — a `?token=` query parameter does **not** authenticate, deliberately,
> because a URL-borne secret lands in the access log and in shell history.
> Without a valid token every route answers `401`; with no readable token file
> the gate fails **closed**.
>
> ⛔ `POST /api/runs` no longer takes `uid` from the request body. The identity
> is the machine's pairing (`load_paired_uid()`), and a body that names a
> *different* uid is refused with `403` rather than quietly rewritten.
>
> ⭐ **Why `/api/health` is exempt:** four callers probe it and the supervisor
> watchdog force-respawns a worker whose health goes unreachable, so a liveness
> probe that can fail for an authentication reason would kill healthy workers.
> It answers process counters and nothing about anybody's research.
>
> **What it was, for the record.** Before 09-05 it bound `0.0.0.0` with
> `allow_origins=["*"]` and no authentication of any kind, so anything on the
> same network could list every run on the machine **for every account that
> shares it**, read the brief / the agent markdown / the podcast, start a run
> billing a uid it supplied, or stop somebody else's. The bind fixed the
> network half and said so in its own tests; the gate is the other half.
> ⚠ The bind is **not** redundant now — the two are layers, and neither has to
> be perfect alone.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/runs` | Start new pipeline `{topic, email?, config?}` → `{id, status}` |
| GET | `/api/runs` | List all runs |
| GET | `/api/runs/{id}` | Get run details (meta, checkpoint, delivery) |
| GET | `/api/runs/{id}/documents/{type}` | Get document content (brief/chatgpt/gemini/claude). ⛔ `consolidated` was retired here on 2026-09-18 (wave 10): this route reads the run folder and nothing else (`documents/{type}.md`, with a legacy sibling fallback), and the stacked document no longer reaches disk — it survives only as a Firestore mirror, so the route 404s it for every run made since. See *NotebookLM Upload Filter* |
| GET | `/api/runs/{id}/audio/{filename}` | Stream audio file |
| POST | `/api/runs/{id}/stop` | Stop pipeline |
| POST | `/api/runs/{id}/pause` | Pause pipeline |
| POST | `/api/runs/{id}/resume` | Resume from checkpoint `{config?}` |
| POST | `/api/runs/{id}/feedback` | Submit feedback `{phase, message}` |
| POST | `/api/runs/{id}/add_context` | Inject extra context mid-run |
| PATCH | `/api/runs/{id}/config` | Update pipeline config mid-run |
| DELETE | `/api/runs/{id}` | Delete a run |
| GET | `/api/queue` | Queue status |

*(GET /api/runs/{id}/events and WS /ws/{id} were removed 2026-04-29 — Firestore pipeline_events is the exclusive FE event transport.)*

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
| `agent_decision` | `{agent, decision: "retry" \| "skip" \| "stop" \| "continue_chat"}` | Response to the agent's failure card. **Retry** nudges the agent and resumes polling — it does not loop back to extraction, there is none. **Skip** salvages whatever partial text exists and closes the tab; it records no URL. **Stop** terminates. `continue_chat` is a fourth value the dispatcher accepts and this row omitted |
| `continue_anyway` | `{phase?}` | Frontend response to a `phase_alert` that exposed `continue_anyway` (e.g. brief-short). Backend `_controls.set_continue_anyway()` fires; orchestrator accepts the short/partial output and advances |
| `skip_phase` | `{phase}` | Frontend's default Skip action on every `phase_alert`. Backend's phase coroutine consumes the request and advances past the failing step. Phase 4 and Phase 5 come through this same unified verb; each used to have its own per-phase Skip verb and both were removed in U2. ⛔ **This sentence used to "name" those two verbs and named `skip_phase` for both**, so it said nothing — an over-eager rename, and the original names are gone from the tree, so they are not recoverable from code and are left unnamed rather than guessed. The internal `_controls` flags Phase 4/5 polling reads remain, but no FE command toggles them anymore |
| `feedback` | `{phase, message}` | User feedback injection. Stored per-phase, injected into next phase rerun |
| `retry_phase` | `{phase}` | Frontend response to a phase-level warning (brief-short, brief-timeout, NotebookLM failure, audio timeout, Phase 3 gate). Backend's phase coroutine polls `consume_retry_phase(N)` + loops back to restart |
| `retry_agent` | `{agent}` | Frontend response to a Phase 2 agent warning (timeout, empty-final, send-fallback, session-expiry). Phase 2 polling consumes + submits a follow-up prompt via `paste_followup` |
| `continue_partial_agent` | `{agent}` | Accept Phase 2 agent's current short/timed-out output as final; agent finalizes with status `done_partial` / `timeout_partial` |
| `poke_agent` | `{agent}` | Stuck-agent response: send mild "please continue" follow-up without extending budget |
| `wait_longer_agent` | `{agent}` | Stuck-agent response: reset `last_growth_time`, granting ~15 min (`STUCK_NO_GROWTH_SEC`, since #929) before the no-growth watchdog can flag the agent again. (Distinct from the Claude 2-artifact `Wait` button which extends `start_time` by 15 min — different gate, different semantics.) |
| `skip_init_verify` | — | Phase 0 dropdown response — bail verification, proceed to Phase 1 with whatever cookie-fast-path read says |
| `retry_init_verify` | — | Phase 0 `login_required` banner response — re-run Phase 0 verification with a fresh tile (frontend tears down the prior tile, BE re-emits `phase_start`) |
| `skip_agent` | `{agent}` | Skip a stuck Phase 2 agent from `BackendSilentBanner` / `HumanVerifyBanner` / `agent_alert`. Polling loop drops the agent from `pending` on the next tick. ALSO retracts the durable agent-scoped `pendingDecision` Firestore mirror via `_clear_pending_decision` (idempotent `DELETE_FIELD` on `pendingDecision`) so the "Hit a snag" card dismisses on the FE instead of re-surfacing on reload |
| `dismiss_alert` | `{alert_id}` | No-op on BE; FE clears its alert slice locally + records dismissedAlertIds so re-emits with the same id are suppressed |
| `discard_run` | `{alert_id}` | Watchdog T3 "Discard" action — emit `pipeline_complete` with `status="terminated_by_user_discard"` + schedule clean server exit. Preserves any partial results already on disk |
| `ping` | — | Watchdog confirmation ping. BE marks the doc processed + writes `pongedAt` timestamp the watchdog reads back. Fast path — no `_controls` side effects |

**Device-scoped commands** (written to `devices/{deviceId}/commands/` instead of the per-research path; every worker on the device subscribes independently):

> ⛔⛔ **EVERY ROW BELOW PASSES THROUGH ONE CLOCK-SKEW GATE, `_is_stale_replay`,
> and until stretch 7 that gate was written twice.** Firestore replays every
> pre-existing doc as ADDED in the first callback after attach, so only docs in
> that first snapshot can be a previous session's leftovers; a doc arriving later
> is something that just happened and **can never be stale**. The per-research
> listener had that `is_first_snapshot` guard; the device listener — the one every
> Settings button talks to — did not, and applied the age check to LIVE commands.
> `timestamp` on those docs is written by the **browser**, so a research computer
> whose clock ran even ~30s ahead (`STALE_COMMAND_AGE_MS`) silently discarded
> Update, check-update, Restart, Hard Reset, Clear logs and all three send-logs
> actions, forever, and left no trace — the `[device-cmds] received action=` line
> sits *after* the skip. One function now, because two copies of a safety gate is
> one copy that gets fixed. ⛔ A bool is not a timestamp: `isinstance(True, int)`
> is True in Python, so `{"timestamp": True}` passed the original numeric check
> and was then subtracted from the clock, making a live command look 1.7e12 ms
> old. ⛔ A **failed device read refuses** on the owner-checked rows rather than
> falling through — `update` and `restart` both log `device read failed … —
> refusing` — and on the send-logs family every refusing guard also writes a
> refusal row (`_refuse_log_bundle_with_row`), because worker 1 deletes the
> command before dispatch and a silent return is indistinguishable from a build
> too old to understand the request.

| Action | Body | Behavior |
|--------|------|----------|
| `hard_reset` | — | Drains in-flight pipeline on every worker, sweeps stale queue + share + research artifacts across owner + every sharer's Firestore tree, clears local browser-profile state, schedules `os._exit(0)` so the daemon-loop respawns clean. Fired by Settings → Manage devices → Hard Reset AND by the Reset Pair Code path (before refresh-token revoke) so all N workers tear down before the token death. Commits `f744913` + `ab119b2`. |
| `clear_local_storage` | — | Wipes BE-local checkpoint + completed-run + browser-profile caches. Does NOT touch Firestore-side researches. Fired by Settings → Manage devices → Clear local data. |
| `update` | `{force?}` | **Owner-only, worker-1.** App-driven remote backend update via `_perform_self_update` (the same idempotent core as `superresearch --update`). Owner-check (`submittedBy == ownerUid`) + supervised-check + mid-run defer (unless `force`, which stops the active run first, keeping partial results). Writes `updateStatus` to the device doc; success is observed via the heartbeat `version` bumping after the pipx rebuild + respawn. Fired by Settings → About → Update. |
| `check-update` | — | **Owner-only, worker-1.** Forces a fresh PyPI check and republishes `version` / `updateAvailable` / `versionCheckedAt` so the About row's inline Check control resolves. No restart. |
| `restart` | — | **Owner-only, worker-1.** The narrow "finish the update" action for an upgrade whose files landed but whose restart leg didn't (`updateStatus.needsRestart`): cycles worker 1 so the supervisor respawns it from the rebuilt venv and the app sees the new version. Deliberately NOT `hard_reset` — it refuses while a run is in progress rather than destroying it. ⛔ The owner check is defence in depth and was missing until 2026-08-05: the rule lets any device member create a command with their own `submittedBy`, so a sharer could cycle the owner's backend while the sibling `update` refused them. A device read that FAILS refuses too. |
| `clear-logs` | — | **Owner-only (by the default-closed command rule, not a check here), worker-1.** Settings → Manage Data → Clear logs, the LOCAL half: run folders, session logs, raw tails, local bundles, telemetry spool. The app deletes this device's cloud bundles itself — the two halves are reported separately and neither pretends to be the other. |
| `send-logs` · `send-logs-limited` · `send-logs-selected` | `{code, requestId, submittedBy, runs? (limited), runNames? (selected), includeMachine?}` | Build a support bundle and upload it under a support code. **Three action NAMES, not one action with a field** — a build one release behind ignores an unknown field and would collect the newest thirty against a request for two, so the skew has to fail as "nothing left the machine" rather than as over-collection. The names come from `bundle-contract.json`, pinned byte-identical in both repos (the installed wheel packs no `.json`, so `BUNDLE_CONTRACT_FALLBACK` is what every field build actually reads). `send-logs-selected` is the one a **sharer** may fire: what it contains is decided at the sink, never by the request — the runs attributed to that submitter and nothing else, with the machine-level material (pairing and sign-in sessions, the raw device tails) owner-only AND opt-in. Every guard that can refuse writes a refusal row, because worker 1 deletes the command before dispatch and a bare return is indistinguishable from a build too old to understand the request. |

> **App-driven backend update + source-checkout.** Worker-1 publishes `version`, `updateAvailable`, `updateStatus`, `versionCheckedAt`, and `sourceCheckout` to `devices/{deviceId}` from the heartbeat loop — ⛔ **decoupled from the liveness write and best-effort by design**, throttled to ~5 min and written only when a value changed: these fields are a SEPARATE allow-list entry, so a 403 from rules that have not been deployed yet must not flip the device offline; the app's Settings → About shows a real-time BE version **per owned device** with an inline Check → Update control (no popups; sharers / no-device users see no version row). A source-tree BE (`git clone` + `python research.py`) sets `sourceCheckout:true` — gated on the authoritative PATH probe `_is_source_checkout()`, NOT the version string (an editable install still reports a real version) — so the About row reads "Source checkout · update with `git pull`" with no Check button; only a pipx build is app-updatable.

> **Dispatcher resume-contract (2026-05-18)**: every action that acknowledges a paused alert MUST call `_controls.request_resume()` so the pipeline doesn't stay paused after the user clicks the action button. The per-action helpers (`request_skip_agent`, `request_retry_agent`, `set_continue_anyway`, etc.) already clear `pause_event` + set `resume_event`; the dispatcher's explicit `request_resume()` ALSO clears `pause_reason` + `pause_target_agent` — a state-leak class that previously kept FE rendering "paused" even after Retry. The 8 actions the fix covered: `skip_init_verify`, `retry_init_verify`, `skip_agent`, `retry_agent`, `continue_partial_agent`, `poke_agent`, `wait_longer_agent`, `continue_anyway`. Plus the already-correct ones — `resume`, `skip_phase`, `retry_phase`, `agent_decision`; those last three join the 8 in the test's `REQUIRED_RESUME_ACTIONS` list, 11 names in all. ⛔ **The tallies in this line were wrong in both directions and are corrected 2026-09-19:** `pause` was counted twice, once as "already correct", and the intentionally-not-resumed group was labelled 8 while listing 7. It is seven, and `pause` is one of them — `pause`, `stop`, `discard_run`, `ping`, `add_context`, `config`, `dismiss_alert`. Static-analysis test `tests/test_dispatcher_resume_contract.py` enforces the contract — adding a new resume-required action without wiring `request_resume` fails CI.

> **CLI dispatcher pause-reason routing (DGOPS-7710 / F6 + 3 follow-ups)** — same root pattern surfaces on the CLI side. When an alert pauses with a `pause_reason` (`agent_link_failed`, `human_verification_required`, `cua_unavailable`, `claude_chat_mode`, `login_required`, `pro_required`), the CLI `r` / `s` keystrokes route to the correct alert-specific helpers (`set_agent_decision`, `set_continue_anyway`, `request_skip_agent`, `request_skip_init_verify`) **plus** `request_resume`. Before the fix, `r` only called `request_resume` and the consume site defaulted user-intended "retry" to silent "skip".

> New consumers wired via `_controls.request_*` + `consume_*` methods; `reset()` clears them on run start. ⛔ **2026-09-03, step 6 — this named three blocking helpers and got all three wrong.** `await_stuck_decision` has never existed anywhere in the repository; `await_retry_or_continue` has no callers; `await_agent_decision` survives on exactly one, the 90-second send-button fallback. The real blocking gate is **`await_phase_decision`** (24-hour default), which this line did not mention.

---

## Phase-Restart Semantics (pause + input + resume)

When a user adds context while paused and then resumes, the **current phase reruns** with the combined input. Four distinct entry points, same effect:

| Case | Detection site | Mechanism |
|------|---------------|-----------|
| **P1 mid-phase** | `poll_until_done` — after `wait_if_paused()` returns, checks `peek_extra_context()` | Sets `_runtime.restart_requested = True`, returns False. The Phase 1 orchestrator retry loop catches the flag, pops context, merges into `topic`, reruns `run_phase1`. Cap 3× |
| **P1 boundary** | After Phase 1 finishes — `is_stop_or_pause()` true | `pause_and_close_browser` → on resume, that site pops queue directly → rebuilds `combined_topic` → calls `run_phase1` once inline |
| **P2 mid-phase** | Same as P1, plus the round-robin poller | The Phase 2 orchestrator retry loop. Context appended to `research_brief`. Cap 3× |
| **P2 boundary** | After Phase 2 finishes — `is_stop_or_pause()` true | Pops the queue inline, builds `combined_brief`, calls `run_phase2` once |

**No input during pause** → queue empty → flag never trips → phase continues from where it stopped.

---

## Agent completion gate

⛔⛔ **THIS SECTION WAS CALLED "Agent Link Gate (B1)" AND EVERY LINE OF IT WAS
FALSE — 2026-09-03, stretch 7.5 step 6.** It described a gate requiring a
shareable link to pass validation before an agent could be declared done. Not
only is that not the gate, it is **unsatisfiable by construction**: the
validator table holds three entries — `notebooklm`, `youtube`, `gdocs` — and
rejects every platform it does not know, so it answers *no* for `chatgpt`,
`gemini` and `claude`, always. **Anyone restoring the behaviour written here
would ship a pipeline in which no research agent ever completes.** The section
is kept, corrected, rather than deleted, because five in-code comments were
written from it and the fear of removing link code came from this page.

A Phase 2 agent is declared done when **all three** hold:
1. **Its markdown is non-empty** — greater than zero characters, not 100.
2. **The run has a research anchor** — without one there is no document address
   to hand the app.
3. **The Firestore document write succeeded** — so the app can find what it is
   being told about.

No link is consulted. What the agent emits on success is a link to the report's
page **in our own app**, always marked verified, and it is emitted under the
same gate — the announcement and the link are one decision, not two.

**How the app decides to show a tick:** it reads that agent's own document, by
type, and checks the content is non-empty. It does not read a link, and it does
not read `verified`. See the app's `docContentReadyForType`.

**On failure** there is no pause. The one live producer of `agent_link_failed`
is the Claude safeguard below; it **parks** the agent non-blockingly with a 300
second timeout and the round-robin keeps polling the other two.

**Gemini safeguard:** CUA completion checks don't begin until after "Start
research" is clicked. If <3 sources and <2000 chars early in the run, the "done"
verdict is reverted.

**Claude safeguard:** if fewer than 2 artifacts exist at 80% of the maximum wait,
completion is reverted — the first artifact is usually the plan and sources, not
the report. ⚠ A modern-completion-marker check added 2026-04-26 accepts a
one-artifact layout outright and bypasses both this and the Gemini gate.

⛔ **`extract_with_retry` IS NOT PART OF THIS.** It is a Phase 3 helper with one
caller — the NotebookLM notebook link — and it is where `link_extracting`,
`link_extract_retry` and `link_extraction_failed` come from. Phase 2 has had no
link-extraction retry loop since the extraction was removed on 2026-08-28.

⛔ **`wait_for_agent_decision` IS NOT THE PAUSE PATH.** It has no production
caller at all; the live route is `poll_agent_decision` into
`_resolve_parked_agent_decision`.

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

**Action semantics recap:** action buttons in a panel come from the source event's `actions` array. The FE renders them via `PhaseAlertPanel` / `AgentAlertPanel`; tapping a button writes the embedded `command` (`{action, …}`) to the research's `commands` subcollection. Phase 4/5 use the unified `skip_phase phase=N` verb (the two legacy per-phase Skip verbs were removed in U2 — ⛔ the same over-eager rename that garbled the `skip_phase` command row above left both of their names written here as `skip_phase`).

### Normalized error matrix (Apr 19 late-late)

The agent-level action set was consolidated to reduce noise:

| Situation | Default options |
|-----------|----------------|
| Every agent/phase alert (unless overridden below) | **Retry · Skip** |
| Phase 2 workspace cap hit | **End research** only (`action=stop`) |
| Phase 2 poll timeout (90-min hard cap) | **Auto-skip** — partial saved (≥200 chars), no decision gate since 2026-04-30 (`be8f7b3`) |
| Stuck-agent (renamed vocabulary) | **Retry · Wait · Skip** (was Poke / Wait longer / Skip agent) |

**Removed entirely:** the `[Poke]` button (folded into Retry, which now does the hard tab close+reopen from Apr 19 early `retry_agent`) and `[Proceed without CUA]` (let users walk into broken-state pipelines with no recovery path). Frontend PhaseAlertPanel already renders every alert via the `action.command` passthrough, so the normalization was pure backend: change the `actions` array the event carries and the UI follows.

---

## Retry / Continue / Skip Decision Gates

Every recoverable failure offers at least one explicit choice via `phase_alert.actions`. Blocking gates wait on `await_phase_decision` (24-hour default) until the user responds via a Firestore command or a bounded timeout elapses, at which point the caller picks a safe default. ⛔ 2026-09-03, step 6 — this line named `await_retry_or_continue`, `await_agent_decision` and `await_stuck_decision` as the gates. The third has never existed, the first has no callers, and the second is down to a single send-button fallback.

**Intent catalog + non-blocking decisions (#955).** Alerts are now authored through a single seam, `emit_decision`, over an `ALERT_INTENTS` catalog. Each decision carries a **recoverability class** — `recoverable` / `hands_off` / `blocker` / `infra` — a `decision_id`, and (when auto-skippable) a deadline; `_alert_actions_for` derives the action tokens and distinct `alert_id`s per intent (login/HV/link/brief/pro_required/chat_mode/crash/cua_unavailable/env-check/soft-warn), with an async best-effort AI copy-sharpen for vague cards. **P2 setup gates are non-blocking**: HV (#1b), `pro_required` (#1a) and `chat_mode` (#1c) are send-before-decision and no longer pause the pipeline — P2 dropped the blocking `wait_for_verification_clearance`/600s tier-5 poll (research.py → `hv_blocked` + `_hv_setup_fail_card`; the shared blocking wait now runs only for P1/P5's single-surface path). A **non-blocking parked-decision resolver** (#953) means one agent's card never freezes the round-robin; every alert **auto-resumes** on resolve. The auto-skip **deadline lifecycle** is arm → fire → disarm (`HANDS_OFF_AUTO_SKIP_SEC=300` for hands-off walls). A **command-ack** emitted at dispatcher intake lets the FE re-enable a tapped button promptly. Silent self-heals (no card): Gemini lost-send adopt-first + one-Retry reconnect; transient Anthropic errors retry before escalating; a must-act Anthropic `blocker` is never swallowed into a retry banner.

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
| Agent 90-min hard cap (`PER_AGENT_HARD_CAP_SEC`) | poll_all_agents_round_robin | auto | **Auto-skip** — no decision gate since 2026-04-30 (`be8f7b3`); toggleable via Settings → Pipeline (#921) | Partial output (≥200 chars) salvaged before the tab closes |
| Agent empty-final | 3× CUA done + empty extract | 5 min | `[Retry]` · `[Skip]` | Same follow-up, reset done state |
| Agent send-button fallback | start_agent_no_gemini_wait | 90 s | `[Retry]` · `[Skip]` | Re-run `PROMPT_CLICK_SEND` CUA loop |
| Claude 2-artifact hard-fail | Inline (elapsed ≥ 80% of wait AND <2 artifacts) | 5 min | `[Retry]` · `[Skip]` | Retry closes + reopens Claude tab via hard-mode `retry_agent` |
| Workspace cap | Phase 2 platform constraint hit | — | **`[End research]` only** (`stop`) | n/a |
| Stuck-agent (L1 card) | Inline (`no_growth > 15m` [`STUCK_NO_GROWTH_SEC`] AND `elapsed > 10m` [`STUCK_MIN_ELAPSED_SEC`] AND status NOT in `{planning, thinking, researching, searching}` AND scrape `phase != planning`), then confirmed by a CUA vision arbiter before the card fires | async (non-blocking) | `[Retry]` · `[Skip]` (#921/#929 single-alert design) | Retry = hard-mode tab close+reopen |
| Stuck-agent (L3 auto-skip) | L1 card left unacted `> 30m` (`AUTO_SKIP_UNACTED_SEC`, since #929) | async | Auto-skip this agent (toggleable via Settings → Pipeline, default ON) | Partial output salvaged; tab closes |
| Session expiry | Inline (requires 2× consecutive confirms spaced 2 min) | 30 min | `[I've logged in — Retry]` · `[Skip]` | Reload tab + keep polling |

**False-alarm suppression baked into the detectors:**
- Stuck-agent: 10-min elapsed floor + 15-min no-growth threshold (#929), checks text AND source growth, skips during known active statuses (incl. the scraper's `phase == "planning"` for Gemini), and a CUA vision arbiter must confirm genuinely-stuck before the card fires.
- Session-expiry: 2 consecutive confirmations 2 min apart; distinct from HV (CAPTCHA/Cloudflare) which has its own detector.
- Brief-short: only fires in 100-500 char window (never on truly empty output — that's a different path with its own handling).
- Every alert is dedup'd on `(phase, type, title, details)` so duplicates from polling loops don't spam the dropdown.

---

## Backend Restart Resume-from-Checkpoint

When the `--daemon-loop` supervisor respawns `--serve` after a crash, queue rehydration recovers state from Firestore:

| Previous status | Action |
|-----------------|--------|
| `queued` | Re-enqueued into the in-memory queue with original topic + pipelineConfig |
| `ongoing`, **supervised** device with on-disk artifacts | Auto-resumed: re-enqueued with `resume_dir` from the checkpoint, no user action needed |
| `ongoing`, otherwise | Marked `status:"paused_backend_restart"` with summary "Backend restarted mid-run — hit Resume to pick up from the last checkpoint." |
| Persist failure (Firestore write fails on shutdown handover) | Marked `status:"paused_backend_restart_failed"` + `lastError` field with the actual exception. FE renders red error banner instead of green checkpoint banner. (2026-04-30 `6545335`.) |

**Per-worker rehydration + dead-worker abandonment (#966 / #64, 2026-07).** Rehydration now runs **per-worker** rather than whole-fleet, so a single respawned worker in a multi-worker fleet self-heals its own in-flight run without disturbing its siblings (#966/GAP1). Separately, an **abandonment backstop** covers a run stranded on a **permanently-dead** worker (one that never comes back): the run is marked `paused_backend_restart` (surfacing the same Resume affordance) instead of hanging `ongoing` forever (#64). The self-heal watchdog no longer fires a T1 push notification and surfaces one honest Resume card (no misleading 2-min wait).

Frontend renders the new status as a phaseAlert at the last-known phase:
- `[Resume from checkpoint]` → calls `POST /api/pipeline?action=resume&id={backendRunId}` → backend enqueues job with `resume_dir=queue`; `run_pipeline` uses `detect_resume_phase()` to skip to the right phase.
- `[Discard + start new]` → clears the alert locally; queue directory stays on disk as a backup.

⚠ The supervised auto-resume row was inert until DGOPS-9508 — it reached the worker
queue by a bare name belonging to another scope, so it raised `NameError` and the
caller's broad `except Exception` abandoned the whole block, taking the
`paused_backend_restart` fallback with it. It now goes through
`_QUEUE_STATE["queue_ref"]` (the same remedy the device-command listener uses) and
falls back to `paused_backend_restart` when that is not yet populated.

Checkpoints that survive the crash, all under `queues/{run}/`: `documents/*.md`, `delivery.json`, `links.json`, `podcasts/*.m4a`, `checkpoint.json`, `phase2_complete.marker`. Missing state (browser + CUA session) is re-created by the resume run. (The legacy `tracks/*.json` per-agent scrape snapshots were removed alongside the tracks/ directory tree on 2026-04-29 — `documents/*.md` is the single source for Phase 2 output now.)

---

## Credential state, and recovery on a machine nothing supervises

⚠ **Everything above this line assumes a supervisor.** A machine started by hand
— `superresearch --serve` in a terminal, which is a supported way to run this — has
no daemon loop, no Scheduled Task, no launchd plist and nothing at all to respawn
it. Two defects lived in that gap, and both were about what the program *says* and
then *does* when its credentials go.

**One classifier, every advice site.** `classify_credentials(device_id, paired_uid,
has_token, token_rejected)` is pure and returns one of five states, and **the order
of its tests is the whole point**: `device_id` is asked FIRST, because that is the
fact deciding whether pairing is a repair or a demolition. A machine with no id has
nothing to lose; a machine WITH an id loses that id the moment it pairs, so no
branch below the first may recommend pairing.

| state | what it means | what it may advise |
|---|---|---|
| never paired | no device id | `--pair` |
| orphaned | an id, no owner link | `--pair` — the only door left; the relink command the id-preserving path names does not exist in this program |
| token rejected | the server said no | ⛔ never `--pair` |
| no token | we never asked, or the keystore itself cannot be reached | ⛔ never `--pair` |
| healthy | — | — |

⛔⛔ **`--pair` ON A MACHINE THAT STILL HAS ITS ID IS DESTRUCTIVE, AND FOUR SITES
USED TO PRINT IT.** An access-code Reset leaves an empty keystore; `--pair` on that
machine does not restore anything — it mints a NEW `deviceId`, and a new device has
no `visibility`, so the owner loses the computer's identity **and** its public
listing in one command. The advice was said to an owner on 2026-09-06 and very
nearly run. ⭐ The routing word `revoked` is deliberately unchanged: both the empty
keystore and a rejected token must reach the relink loop rather than the reconnect
ladder. The classification was never the bug; the advice hung off it was.

`credential_state_now()` feeds the classifier from this computer — two on-disk reads
plus a keystore probe. ⛔ No network, no gRPC, which is what keeps it callable from
the REST-only subcommands that deliberately never build a client; `token_rejected`
is passed **in** rather than probed, because only a live refresh can tell "the server
said no" from "we never asked". A keystore that cannot even be asked folds into *no
token*, whose advice is safe either way. `credential_remedy(state)` holds the
sentences, worst-first, in one place so the `--pair` rule cannot grow back at the
next site somebody adds — and ⛔ **no branch promises a timer or an automatic
respawn**. The recovered states wait for a person (an approval in the app, a process
on this computer), not a clock, and "the watcher will respawn the backend
automatically" is true only where a supervisor is installed.

**`--serve` is its own supervisor when nothing else is.** After the revoked-recovery
loop relinks successfully, `--serve` must exit so its Firestore subscriptions reload.
It now asks the same question `_recover_after_reconnect` already asked —
`_supervisor_is_my_parent()`:

- **supervised** → `_os._exit(0)`, the daemon loop brings it back.
- **unsupervised** → **re-exec this process, once.** The recovery has already
  succeeded, so there is nothing left for a person to decide, and a message telling
  them to run the command again would leave the machine off the public list until
  they read it. ⛔ The exec is behind the seam `_relink_reexec()` rather than inline:
  the first version called `os.execv` in the loop body, and the test that drives that
  loop replaces `os._exit` with a raising sentinel but had nothing to replace here —
  so the loop re-execed **pytest**, 71% through the suite, and the run ended with
  exit code 0 and no summary. ⛔ The command line comes from `sys.orig_argv`, not
  `[sys.executable, *sys.argv]`: on a pipx or pip install `sys.argv[0]` is a console
  script, and on Windows that is an `.exe` wrapper no interpreter can be handed —
  the restart would have failed on exactly the installs most likely to be
  unsupervised. `_relink_reexec` returns only when the exec did NOT happen, so the
  path falls through to the sentence the person is owed.
- ⛔ **Once, and only once.** An invisible restart loop is worse than the defect it
  replaces. The latch is the env var `SR_RELINK_REEXEC` (`RELINK_REEXEC_ENV`) rather
  than a module global, precisely because it must survive into a process that has not
  run this file's top level yet — and it is **cleared on a healthy Firestore init**,
  which is the one moment that proves no loop is in progress. Left uncleared it meant
  "once per process lineage", so the *next* access-code reset, months later, would
  refuse to restart and reproduce the original incident with no clue why.

---

## Tier Escalation Tracking + Phoenix Resume (C1, Apr 28)

Unified per-(op, agent) attempt tracking for retry/escalation across BE operations. Replaces ad-hoc tier_transition emits with the centralized `emit_tier_transition()` helper.

**TierEscalation class** (`research.py`) — one record per (`op`, `agent`) pair, with a 30-min sliding window:
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

> **Naming note:** these T0/T1/T2/T3 labels are the **crash-recovery escalation ladder** and are unrelated to the **interaction tier ladder** (DOM = tier-1, Vision = tier-2, CUA = tier-3 — the fallback order the pipeline uses to drive each UI hotspot). The two systems coexist; the `from_tier`/`to_tier` fields on `tier_transition` events use the *interaction* labels (`dom`, `cua`, `vision`).

**Centralized emit:** `emit_tier_transition(*, phase, agent, op, from_tier, to_tier, reason)` calls `TierEscalation.record(to_tier, reason)` then fires the `tier_transition` event with the new attempt counter. The 4 wired hotspots are:

| research.py site | `op` | `agent` | direction |
|------------------|------|---------|-----------|
| `verified_paste_brief` → `cua_paste_fallback` | `brief_paste` | platform | dom→cua |
| ChatGPT P1 activity panel | `open_activity_panel_p1` | chatgpt | dom→cua |
| Claude artifact panel | `open_artifact_1` | claude | dom→cua |
| ChatGPT P2 activity panel | `open_activity_panel` | chatgpt | dom→cua |

> ⛔ **Two rows left on 2026-08-28 (stretch 6.6B).** The `p2_share_extract` op — `extract_share_link_chatgpt` and the round-robin Gemini share — was the P2 platform share-link step, measured at 2.2 minutes and 21.7 CUA calls per run for a link nothing in the pipeline gated on. Phase 5 now delivers Super Research's own `/shared/doc/{id}` snapshot pages, minted from the markdown already in Firestore. The `p2_share_extract` op no longer exists.

**Checkpoint enrichment:**
- `tier_escalation_history: dict[str, dict]` — full registry of TierEscalation records, keyed by `f"{op}:{agent.lower()}"`
- `agent_states: dict` — per-agent runtime state mirror so a Phoenix restart rebuilds "where each agent was"
- `last_event_id: str` — `f"{ts_ms}_{event_type}"` cursor so the FE can dedup events on resume

**Phoenix T3 resume — `_pending_queue.json`:** the in-memory `_job_queue` (asyncio.Queue) is lost on BE exit. The worker writes a snapshot `{ts_ms, current, pending}` to `queues/_pending_queue.json` after every `_job_queue.get()` and again in the `finally` block. On startup, after Firestore-driven rehydration runs, the disk snapshot is read and any research_id NOT already in the rehydrated set is re-enqueued. Covers the gap where a job got `put_nowait`'d locally but the Firestore `status:"queued"` write hadn't landed yet.

---

## Public computers — discovery, and what the device document may carry

**Discovery is not access.** A machine marked public is one other people can see
listed and **ask** to use; the owner approves every request by hand, and an
approved person becomes an ordinary sharer. Nothing about the setting grants
anybody anything, and the device document stays readable by exactly the same
three principals either way.

**The state lives on the device document and nowhere else** — deliberately no
`research_config.json` key, because the owner can change this from the app and a
local copy would be a second answer that goes stale the moment they do. The
reader is `_fetch_device_meta_rest`, the same one `--resurrect` and `--retire`
use, so it needs no gRPC client.

⭐ **Two names, one answer, and the OLD name wins while it is there.**
`_DISCOVERY_KEYS = ("visibility", "joinPolicy")` — the same question ("who may
join this computer") under the name the rename is heading for. `firestore.rules`
has admitted both keys side by side since wave 7 and the agent bridge learned to
read both in wave 8; this program still compared against the literal `visibility`
until wave 9 and fell through to PRIVATE, so the day a document is written under
the new name it would read "private" to the very machine that owns it. Order is
load-bearing and the first build had it backwards: everything that ACTS on the
setting still reads `visibility` — the app's public list queries it, and both of
this program's writes (pair Stage 3 and `--visibility`) put the old key down — so
a reader must agree with the **writers**, not with the migration's destination.
Preferring the new name on a toggle is a door that never closes: write
`visibility: private` while `joinPolicy` still says public and the next read
answers "already public". ⭐ It survives the rename anyway — when the migration
removes `visibility`, `joinPolicy` is what is left and it answers. The machine
reads both names and writes only the old one.

⛔ **ABSENT IS PRIVATE.** A machine paired before 2026-09-04 carries neither key
and nothing backfills one; the safe direction for a discovery setting is the one
that hides.

**`superresearch --visibility [public|private]`** shows or sets it; bare, it
prints. Three things about that command are decisions rather than style:

- ⛔ **An empty read is not "private".** `_fetch_device_meta_rest` returns `{}`
  for a network failure, an expired session and a real document alike, so the
  absent-means-private rule may only be applied to a read that SUCCEEDED — the
  guard sits ABOVE `_discovery_of`, never below it. The one cause that can be
  named from disk with no network call (a wiped keystore after a reset) is named.
- ⛔ **A failed write may not claim "nothing changed".** `_pair_patch_device`
  returns False for four situations and only two of them prove the write did not
  land; a timeout and a 5xx both happen after the request went out.
- ⚠ `topic` is itself optional, so argparse will happily bind the next word to
  `--visibility`'s `nargs="?"` and swallow a topic. A manual check in `main`
  refuses anything that is not one of the two words and says what happened.

Pair Stage 3 asks the same question (default **No**, so an unattended pair
publishes nothing) and its answer travels in the **same single**
`_pair_patch_device` write as On Startup — see the 2026-09-17 entry below for why
splitting that write would lose a discoverability answer for good.

### What `devices/{deviceId}` may carry — 7.7E (2026-09-04)

⛔⛔ **The device document is read WHOLE by the owner, by every sharer and by the
machine** — Firestore cannot scope a read to fields. This file had already
written that reason down at the run-history publisher, which refuses to put
history there because "one sharer would learn every other sharer's run history",
and three other sites put the live one there anyway. So the machine stopped
publishing what other people are researching:

- `currentRunTitle` and `queuedBehindTitle` are **cleared** on every pickup and
  every renumber — a delete rather than an omission, so a write that would have
  published a title removes the one before it. Both keys stay on the rules
  whitelist, because a `deleteField()` lands in `affectedKeys` and every machine
  still on the shipped wheel goes on writing them until its owner upgrades.
- the per-sharer queue-owners list carries uid, run id and position, no title.
- the sibling fields stay: `currentRunId`, the owner uid and the phase are what
  let the app say "you are second in the queue", which is the reader's own
  business.

⛔ **And the sharer-tree rehydration scan is scoped to this machine.** Nothing
below that query reads `deviceId` — every ownership test keys on
`assignedWorker`, a worker NUMBER, which is unset on the overwhelmingly common
single-worker run and defaults to worker 1. Unscoped, this machine marked
*another* machine's healthy run `paused_backend_restart`, and on a device whose
doc says `supervised` it would auto-resume that run against THIS machine's
browser profiles — the wrong-accounts failure the `assignedWorker` logic exists
to prevent, arriving through the machine dimension instead of the worker one.
⭐ The OWNER's tree stays unscoped deliberately: the rule admits it with no
per-document test, and an equality filter would drop every pre-stamp document
from the orphan safety net. The denial log on a sharer tree is WARN, not DEBUG —
rules deploy in seconds while a wheel arrives when its owner upgrades.

⛔ **The pair code is a credential, not a name.** The unlink route rotates it,
and must: the claim route grants ownership to whoever presents a code against an
ownerless device, which is exactly the state unlinking creates. Because
`list_devices` sends no field mask, a device row arrives whole — a never-rotated
machine's plaintext `pairCode` included — so the agent bridge prunes every device
relay to an allow-list of the keys a consumer actually reads
(`_DEVICE_PUBLIC_KEYS`, and narrower lists again for the public-browse and
request-queue projections). The rotated code is relayed once, to the owner
branch only, and never logged.

---

## A parked run: the pause ceiling, and the one notice that reaches a closed app

These two shipped together (2026-09-01) because they are the same hole seen from
either end — a run that needs a person, and a person who is not there.

**`PAUSE_MAX_WAIT_S = 86400.0` — pause is bounded now, and audible while it waits.**
`wait_if_paused` had no bound at all and spoke exactly once. ⛔⛔ It is also the one
wait the worker watchdog **deliberately** ignores: paused time is excluded from the
active-time ceiling by design, so a parked run accrues nothing, trips nothing, and is
invisible to every backstop in the process. It now logs every `PAUSE_HEARTBEAT_S`
(10 min) naming what it is waiting on, and at the ceiling it **requests a stop** —
all sixteen callers ignore the return value, so the only way to end the wait is the
path that already has a handler, exactly as an operator's Stop would. ⛔ It clears
`pause_event` before stopping: leaving it set would keep the watchdog blind for the
rest of the process while the run was stopping. ⭐ 24h is not a new number — it is
what `await_phase_decision` already uses, this project's own answer to how long to
wait for a person. (This is the "24-hour pause limit" the *Document images* section
refers to.)

**The notification ask is gated on the card's CLASS, not its event name.** Every
phase notice in the product is dispatched by a React component, so it needs an open
tab; a run takes ninety minutes and nobody watches a tab for ninety minutes. One
seam in `emit_event` asks the web app to notify, and ⛔ it sends **ids only** — the
phase, the event type, and the seq of the document just written — so the app reads
that document and composes every word from what it actually says, and this side
cannot announce an artifact by claiming one exists.

⛔⛔ **Until 2026-09-01 that seam was two good-news event types and nothing else.**
A run waiting on a sign-in at 02:00, a quota exhaustion, a stop at the time ceiling,
a backend restart mid-run — each was written to Firestore and to nothing else, while
the settings screen promised "a research finished, hit an error, went offline
mid-run, or needs you". Only *finished* had a sender. The gate is now:

```
(event_type in ("phase_complete", "phase_skipped") and 1 <= phase <= 5)
  or  recoverability == "blocker"
```

⭐ `recoverability == "blocker"` is the field the alert catalog already maintains for
exactly this question — the intents a **person** resolves, that never auto-fire. It
is event-name agnostic, which matters because `emit_decision` takes an `event_name`
override and every blocker that actually strands a run overnight uses one
(`login_required`, `human_verification_required`, `manual_brief_required`); an
event-name gate missed all of them. A blocker is not phase-scoped, so it is **not**
held to the 1..5 range — one raised in preflight is exactly the kind that strands a
run before it starts. ⛔ `quiet` cards are **not** excluded: `quiet` means "do not
paint a phase tile red for a phase that was never reached", and excluding it silenced
precisely the preflight blockers. ⛔ `pipeline_stopped` is **not** included: every
emit site of it is a stop the person asked for, and pushing "Your research stopped"
to somebody who just pressed Stop is what the completion notice already refuses to
do, in writing, for the same reason.

---

## Backend Liveness (Heartbeat + Watchdog)

Worker 1 writes a liveness tick to `devices/{deviceId}` every **5s**
(`HEARTBEAT_INTERVAL_SEC`, research.py), carrying `lastHeartbeat` + `heartbeatAt`
+ `status` + `workerCount`, plus the atomic-pair contract (`pairConfirmedAt:true`
and a delete of the claim Cloud Function's `expireAt` TTL). ⛔ The loop has not
written `research_tokens/{token}` since the device-doc cutover — the only
research_tokens write left is the pair-time logins/setupState patch. FE offline
threshold = **30s** (`DEVICE_OFFLINE_THRESHOLD_MS`) → six missed ticks flip the
device dot red.

> ⛔⛔ **`lastHeartbeat` IS THIS COMPUTER'S OWN CLOCK — millis-as-int, not a
> server timestamp** (this row said `serverTimestamp()` and had it backwards).
> Every reader ages it against a DIFFERENT clock, so the answer to "is that
> machine on?" was the difference between two unsynchronised clocks and it was
> wrong in both directions: a machine running fast reads ONLINE after it is
> switched off, one running slow reads OFFLINE while it is working and every run
> is refused. Wave 9 (2026-09-16) added a SECOND field, `heartbeatAt`, written
> with Firestore's `SERVER_TIMESTAMP` sentinel — `request.time`, one clock for
> writer and reader, and the only form a rule can enforce, because a millis int
> can be forged to any value. ⛔ `lastHeartbeat` stays forever beside it: the
> agent reads Firestore over REST and the app's legacy mapper compares a plain
> number, so a Timestamp in that field would read as perpetually offline.
> ⛔⛔ It rides the SAME `update()` on purpose — a stamp written by a separate
> request can land before or after the liveness write it is supposed to date —
> and the cost of that choice is a **release order, not a code change**: the
> update is atomic, so one key the deployed `firestore.rules` does not admit
> 403s the `expireAt` delete with it, and a machine pairing inside the claim
> function's 5-minute TTL window then loses its whole device document. Rules
> deploy and verify in production BEFORE the wheel publishes.

On long-waits (polling Deep Research for 25+ min) the pipeline ALSO emits a `heartbeat` event so legitimate quiet periods stay green on the per-phase liveness watchdog (FE T1/T2 — see web/ARCHITECTURE.md).

Frontend watchdog: if `lastHeartbeat` is stale >60s AND recent events are stale >60s, pipeline is considered dead. Frontend:
1. `cancelRunningPhases` — freezes running tile timers, flips badges to "stopped"
2. `saveResearch({status:"stopped"})` — prevents a reload from resurrecting the pipeline
3. `teardown` — removes pipeline from Zustand store → buttons and animations clear

Emits a chat notification: *"Backend disconnected during Phase N (no heartbeat for Xs). Partial results saved."*

---

*Updated: 2026-04-16 (late) — added `phase_restart`, `agent_link_failed`, `heartbeat`, `login_required` events; `agent_decision`, `add_context` post-P2 guard; B1 gate; phase-restart semantics; watchdog protocol.*

*Updated: 2026-04-18 — added `phase_alert` + `phase_alert_clear` events with per-phase emit matrix; new commands `continue_anyway` / `skip_phase` / `skip_phase` (all wired via `_controls.set_*`); HV cooldown 45s → 180s; queue persistence across `--daemon-loop` restart.*

*Updated: 2026-04-19 — **Sequential Phase 0 verification** (one platform at a time — cookie → tab-open → CUA → `login_required` scoped to that platform; matches `--setup` script's walk). **Cookie-only per-phase login probe** (runs on every phase regardless of `skipInitVerify`; `cookie_login_hit` read only, no tabs/CUA; catches mid-run session drift). **`phase_narration` event** (Gemini 2.5 Pro narrator emits one human-readable sentence every ~45s during active phases; frontend `/api/narrate` fallback fills >15s gaps with speculative "Likely: …" entries). Frontend stack: `phaseNarrations` store slice + `<PhaseNarrationLine>` + `useNarrationFallback` hook, budget-capped at 20 fallback calls per run.*

*Updated: 2026-04-19 (late-late) — ⛔⛔ **THE PHASE 2 EXTRACTION RULES IN THIS ENTRY WERE SUPERSEDED ON 2026-08-28 AND THE ENTRY WAS NEVER RETRACTED.** It described ChatGPT keeping a public-share-then-conversation-URL fallback, Gemini and Claude hard-failing on a missing public share, and a per-agent emit the moment a verified link landed. Every artifact it names is gone: the three platform extractors, the share-authority table, the CUA fallback and the `gemini_extractor` logs all return zero hits. Phase 2 publishes a link to the report's page in our own app and never touches a platform share. The rest of this entry still holds. **Claude 2-artifact hard-fail** at ≥80% wait time. **Tab round-robin**: `agent_loop(target_page=None)` + `_anchored_screenshot()`; `bring_to_front()` before every polling tick + after every `execute_action`. **Playwright Claude setup**: `setup_claude_dr` rewritten as 3 Playwright steps (model dropdown, Adaptive Thinking, Research tool) ⛔ *the aside that named the model here — Opus 4.7 then, "currently Opus 4.8" — is exactly the shape the 2026-08-01 owner directive removed: `P2_MODEL_POLICY` in `models.py` holds no version literal at all, only family `opus` + highest-offered (`free_family` sonnet when every Opus row is a sales chip), and a frozen floor is how P2 sat on the previous Opus through a whole rollout. The Thinking step went with it — `thinking` is False for Claude because effort IS the reasoning lever now* — no more CUA vision for setup. **Normalized error matrix**: default Retry · Skip everywhere; Phase 2 workspace cap → End research only; Phase 2 poll timeout → Retry · Skip · Wait; removed Poke + "Proceed without CUA"; stuck-agent relabeled Retry/Wait/Skip. **New `agent_narration` event**: per-agent Gemini 2.5 Pro call, ~6s cadence during P1/P2. Backend commit `547bf17`.*

*Updated: 2026-04-30 — **Narration consolidation** (commit `94b7bde`): retired vision narrator (`narrate.py` PHASE_BUDGET=0 default; `DG_VISION_NARRATE=1` re-enables). Per-agent narrator brain swap: Gemini Pro 2.5 → Anthropic Haiku 4.5 primary with Gemini 2.5 Flash fallback (`DG_NARRATOR_USE_HAIKU` / `DG_NARRATOR_HAIKU_MODEL` envs). Tighter anti-parrot prompt (research.py) + chrome scrub on narrator inputs (research.py) — strips `You said:` / `Claude responded:` / `Gemini said` / `brief.md` / `Building:`-prefix composites BEFORE narrator sees them; scrape outputs untouched. Claude DOM scrape: dropped `.font-claude-message` + `.contents` heading selectors (research.py). ChatGPT P2 walker: dropped `[class*="row" i]`; added 23-verb VERB_GATE + min-len 4→12 (research.py). **P1 ET fallback** (`86d0ab4`): dropped duplicate elapsed-time bit in the P1 ET fallback — the parent card already shows elapsed. **Stuck-state risk fixes** (`6545335`): manual brief 3h backstop (`_BRIEF_WAIT_BACKSTOP_S`); pending queue persist-failure surfaces `paused_backend_restart_failed` status; dead-tab guard before soft retry. **Browser crash + P2 timeout** (`be8f7b3`): always-auto, no human prompt — browser crash emits passive `emit_browser_recovery_status` banner + bypasses run_pipeline.finally retry guard ⛔ *the "bypasses the retry guard, therefore it rebuilds and resumes" half was measured false on 2026-08-27 for the per-agent tab death, which fails the agent and carries on; see* Browser death — two different things under one name; P2 agent timeout drops alert + `await_agent_decision`, saves partial if ≥200 chars and auto-skips. **NotebookLM derived-stems filter** (`70e2ab2`): `_DERIVED_STEMS = {"brief", "consolidated"}` excluded — never uploads consolidated.md. **Auto-retry kwarg forwarding** (`549f079`): forward `uid/research_id/run_id` on retry recursion (research.py) so Firestore listener stays attached. **Doc upload wiring** (`8a05227`): P1/P2 attach + Flow B unblock; `attach_brief_file` extended with `extra_files` for multi-file `set_input_files`. **P2 ChatGPT** (`bf66c9d`): continuous activity-panel scrape mirroring Claude artifact pattern. **patchright** added to `requirements.txt` (`221394d`).*

*Updated: 2026-05-18 (final) — **Cross-platform supervisor gate retired (PR3)**: `DG_ALLOW_CROSS_PLATFORM=1` env-flag gate dropped from `_supervisor_platform()`. macOS launchd + Linux systemd-user are first-class supported supervisors alongside the Windows Scheduled Task; no env flag required. Linux smoke caught + fixed two latent bugs (`creationflags` POSIX ValueError in `run_daemon_loop`, `--unpair` browser-profile catch-22 with F4 cookie check). Gate-drop sweep removed all "experimental" / "PR1 PR2 merged" / "PR3 pending" framing from CLI messages + section comments + README + ARCHITECTURE so `--resurrect` / `--retire` / `--unpair` on Mac+Linux read as first-class verbs. `_supervisor_platform()` now returns `Windows` / `Darwin` / `Linux` / `Unsupported` with no env check.*

*Updated: 2026-05-18 (late) — **Pair flow stages reordered (Linux smoke pass surfaced 3 issues)**: Stage 3 ↔ Stage 4 swap so API keys come BEFORE browser logins — CUA + Vision are now available for login verification AND the Pro-tier check (`_cua_pro_tier_call`); before this, those fell back to Playwright-only whenever the user hadn't pre-set the Anthropic key in env. Banner header "Four steps" → "Five steps" with sequence Token → On Startup → API Keys → Logins → Ready. Stale "Step 2" / "Stage 3" references in code comments + log strings swept. **F4 / DGOPS-7451 cookie check relaxed**: refuses pair only on account-switch (`_initial_paired_uid` != `linked_uid`); first-pair + same-account re-pair pass through with a passive `security_pair_allowed_with_prior_cookies` event. Eliminates the catch-22 where `--unpair` preserved the browser profile then `--pair` refused on the same cookies. **New `--unpair --deep` flag**: also wipes `~/.super-research/browser-profile/` (`shutil.rmtree`, ignore_errors=True). Default `--unpair` unchanged. Closing message branches on `browser_wiped` flag.*

*Updated: 2026-05-21 — **Pair-time keys → BE-local persistence; FE bridge deleted; verifier added**: --pair Stage 3 now writes API keys to BE-local persistence (Windows User-scope env / `.dg-supervisor.env` on POSIX) instead of Firestore. **NOTE — already-paired users**: prior pairs wrote keys to `users/{uid}/settings/prefs.apiKeys.{anthropic,gemini}` in Firestore via the (now-deleted) FE bridge route. Those entries persist post-deploy and will continue to auto-fill the FE Account → API Config inputs until manually cleared (or overwritten via a fresh paste on that page). Going forward, only keys typed directly into Account → API Config land in Firestore. Cleanly separates BE pair keys from FE Account → API Config keys, so the Account page only ever shows keys the user typed there (auto-fill leak fixed). Resolver precedence (Firestore → User-scope → shell env) unchanged — FE-Account-page key still wins over BE-local pair key. New helpers `_save_api_key_to_user_scope` (PowerShell `SetEnvironmentVariable('User')`; value passed via subprocess env var to defang quote injection), `_save_api_key_to_env_file` (atomic upsert of `.dg-supervisor.env` with POSIX single-quote escape), `_save_api_key_local` (per-OS dispatcher). New paste-time verifier helpers `_verify_anthropic_key` (`anthropic.Anthropic(timeout=5, max_retries=0).models.list()`) + `_verify_gemini_key` (`requests.get v1beta/models?key=...`, parses `error.details[].reason==API_KEY_INVALID` / `error.status==PERMISSION_DENIED`); on auth_failed re-prompts up to 3 attempts then offers save-anyway?, on network_error saves with a fail-loud-at-first-run warning so offline pairs aren't blocked. Wrapper `_pair_prompt_one_key_with_verify` confines retry to a single layer. Deleted `_save_api_key_via_fe_bridge` + `_save_api_key_to_firestore` (both dead post-cleanup); deleted FE route `web/src/app/api/devices/save-api-key/route.ts` (zero callers). Tests rewritten: `TestSaveApiKeyToFirestore` → `TestSaveApiKeyLocal` (per-OS path + upsert + escape coverage); `TestVerifyAnthropicKey`, `TestVerifyGeminiKey`, `TestPairPromptOneKeyWithVerify`. `TestFreshUserModeIdToken` retained (other Track D callers).*

*Updated: 2026-05-22 — **Multi-account queue + multi-worker validation (5-fire E2E)**. Five new BE commits shipped + validated by an owner-owner-sharer-sharer-owner 5-fire test on workerCount=2: `c362126` real-time renumber for Firestore-deferred docs (`_recompute_deferred_queue_positions`); `bcc4f84` deferred-cancel scan+delete+recompute + pre-claim status re-check (cross-worker race guard); `41d0a27` FIFO sort by Firestore `submittedAt` server timestamp (clock-skew immune, with client `timestamp` legacy fallback); `f744913` HARD_RESET sweep extension across sharer trees; `2314f84` device-wide FIFO position numbering on defer + claim. New ARCHITECTURE sections: "Multi-Worker Architecture" (per-worker safety guards, log prefix convention, HARD_RESET fan-out semantics), "Queue Position Invariants" (four BE rules covering FIFO sort + real-time renumber + cancel + worker-count gating), device-scoped commands table (`hard_reset`, `clear_local_storage`). Backend Liveness section corrected: heartbeat cadence 30s → 5s, FE offline threshold 30s. Safe-push tag `safe-push/2026-05-22-multi-account-queue-flow` pinned on both repos at validated HEADs.*

*Updated: 2026-05-18 — **Pair flow renumbered 4 → 5 stages** (commit `ec34481`): new Stage 4/5 = API-key detect-or-prompt for Anthropic + Gemini. Detects via `resolve_api_key()` / `resolve_gemini_api_key()`; if any source resolves (Firestore / Windows user-scope / shell rc / `.dg-supervisor.env`), the prompt is skipped. On paste: writes Firestore `users/{uid}/settings/prefs.apiKeys.<name>` (merge — same path FE Account page writes) + `os.environ` (both var names per key) + busts `_RESOLVED_KEY_CACHE`. Skip first-class per key. Helpers `_save_api_key_to_firestore` / `_pair_prompt_one_key` / `_pair_prompt_api_keys` live just before `run_pair`. **Claude P2 clarification auto-reply** (commit `897353f`): new 5-condition detector in `poll_all_agents_round_robin` per-tick. When user submits a vague brief and Claude responds with chat-text clarifying questions ending with the "Once you ... I'll launch the research" sign-off (matched by `_CLAUDE_CLARIFICATION_SIGNOFF_RE`), the loop auto-types `"Up to Claude to decide for the best output."` + Send-button (Enter fallback) so the agent proceeds without operator intervention. One-shot per agent via `claude_clarification_replied` flag; resets `start_time` / `last_heartbeat` / `last_growth_time` / `stuck_warned_at` / `last_artifact_scrape` after firing. **Dispatcher resume-contract** (commit `1d0366b`): all 8 Firestore command-action handlers that lacked explicit `_controls.request_resume()` now have it (`skip_init_verify` / `retry_init_verify` / `skip_agent` / `retry_agent` / `continue_partial_agent` / `poke_agent` / `wait_longer_agent` / `continue_anyway`). `request_resume()` also clears `pause_reason` + `pause_target_agent` (per-action helpers don't) — closes a state-leak class. Static-analysis test `tests/test_dispatcher_resume_contract.py` enforces the rule. Mirrors the F6 (`f7aa842`) + 3 pre-existing CLI bug fix pattern (`79d6f7e` — `agent_link_failed` / `human_verification_required` / `cua_unavailable`). **Cross-platform supervisor (Track C, code-shipped, smoke-pending)**: macOS launchd (PR1 `bebe4fa`) + Linux systemd-user (PR2 `feature/track-c-pr2-linux`) gated behind `DG_ALLOW_CROSS_PLATFORM=1`. Env-file pivot (PR-Env `fc944a0`) decoupled Track C from Track B. PR3 (drop gate) pending real-hardware smoke verification. Dispatcher `_supervisor_platform()` routes between Windows Scheduled Task / launchd plist / systemd-user unit. Dead `_heartbeat_task = None` removed at research.py (commit `bce1e90`). `tests/fixtures/vision/auto/` added to `.gitignore`.*

---

*Updated: 2026-09-03 (stretch 7.5) — **THE LINK WORK, WHICH THIS DOCUMENT HAD NOT RECORDED AT ALL.**
Six steps across 2026-09-02/03. What an editor of this file most needs to know:*

- ***An agent's private conversation address never leaves this machine.*** *It is still captured, and
  it has exactly one job: reattaching to that agent's tab after a pause. It is not published, not
  mirrored to the delivery file, not sent to the app, and not written to a log in full — the two log
  lines that need to identify a tab print host, path shape and a short digest of the whole address
  via `redacted_chat_url`.*
- ***⛔⛔ THE PAUSE EVENT AND THE PAUSE CHECKPOINT DELIBERATELY CARRY DIFFERENT THINGS, AND UNDOING
  THAT REOPENS A LEAK.*** *`PipelineRuntime.snapshot()` is what goes to disk;
  `snapshot_for_app()` is the same thing minus `_SNAPSHOT_LOCAL_ONLY`, and it is what rides the
  `pipeline_paused` event. The excluded key is the reattachment map. It matters because the event is
  kept for 30 days in Firestore and the follow-up chat's recent-events tool hands whole event
  documents to a model — so every paused run used to put all three agents' conversation addresses
  into a model's context. Two separate methods, rather than an edit to one, precisely so this cannot
  be undone by accident.*
- ***Where a report's link comes from now:*** *`in_app_document_url(kind)` — one answer, previously
  written out by hand at four sites which had already drifted. Without a research id it returns the
  bare Documents page rather than inventing an anchor, so callers needing a specific target test the
  id themselves.*
- ***The `links.{kind}` aggregate.*** *Writable kinds are `brief`, `notebooklm`, `audio`,
  `audio_file`, `youtube`, `video`. ⛔ `chatgpt` / `gemini` / `claude` were retired on 2026-08-28;
  the app filters those three slots on READ because old records hold conversation addresses in them,
  and it filters rather than ignores because the retired writer stored genuine share pages for most
  of its life. ⛔ `update_link_in_firestore` validates nothing — callers arriving through
  `emit_validated_link` are checked, the two direct callers are not.*
- ***The identity check is content-based.*** *Whether a conversation is ours is decided by what is in
  it, not by decoding a timestamp out of its address. The rule over the whole stretch: nothing may
  depend on the shape of a web address.*

---

*Updated: 2026-09-17 — **Pair flow renumbered 5 → 6 stages** (owner request, 2026-09-15). The
discoverability question ("Let other people find this computer and ask to use it?") had been asked
inside Stage 2 as an unannounced second question since 7.7B; it now has its own displayed step. The
arc is `1 Token setup → 2 On Startup → 3 Discoverability → 4 API keys → 5 Browser logins → 6 Ready`,
so the old steps 3/4/5 each shifted up by one. Banner header "Five steps" → "Six steps", and the
preview line wrapped to two rows because six chips do not fit 80 columns.
`_continue_pair_stages_2_to_5` → `_continue_pair_stages_2_to_6` (the name encoded the count and is
reached by `inspect.getsource` from ten test sites).*

- ***IT IS A DISPLAY SPLIT AND NOTHING ELSE.*** *On Startup and Discoverability still share ONE
  `_pair_patch_device` write, and that is load-bearing: the call lands on a `hasOnly()` rule which
  refuses the WHOLE update if a single key is off-list, and `visibility` has no second writer
  anywhere in the pair flow (Stage 6 re-writes `supervised` only). A split write would lose a
  discoverability answer for good while the screen said it was saved.*
- ***⛔⛔ THE TELEMETRY STAGE NUMBERS DID NOT MOVE, AND MUST NOT.*** *`PAIR_STAGE_REACHED` still
  emits 2 / 3 / 4 at the same three code points and `PAIR_COMPLETED` still carries `stage=5`. Those
  numbers are identities in a time series: renumbering them would silently make a historical
  `stage=3` row mean API keys before 2026-09-17 and Discoverability after, which is not reversible.
  The new step 3 gets NO emit — it never had separate coverage, so nothing was lost. Displayed step
  → emitted stage: 2/6 → 2, 3/6 → none, 4/6 → 3, 5/6 → 4, 6/6 → PAIR_COMPLETED 5. The mismatch is
  recorded in a comment block at the step-2 emit site so the next reader does not "fix" it.*
- ***What did NOT renumber.*** *`--unpair` keeps its own five-step arc (`total = 5`,
  "Five-step reset"), `--resurrect` its four and `--retire` its three — different arcs
  sharing the same `_setup_step` helper. README's own `### Step 1 … ### Step 6` headings are the
  install walkthrough, not the pair arc. The agent's `branding.py` is data-driven and needed only a
  docstring word.*
- ***Two things the recount corrected.*** *The pair arc has FOUR `[n/5]` banner comments, not six —
  step 1 has none, and the other six in `research.py` belong to `--unpair`, which has one
  more banner than it has steps: it opens with a `[0/5]` GATE banner that does
  the server-side retire before anything local is touched. And README had been
  calling step 1 "Pair code" while the code and the web modal both said "Token setup"; fixed in the
  same pass.*
- ***⛔ The web half followed on 2026-09-19, and only part of it did.***
  *`dg-research/src/components/chat/WalkthroughModal.tsx` teaches all six now — `[1/6] Token setup`
  through `[6/6] Ready`, with Discoverability under its own header — and
  `tests/unit/deviceVisibility.test.ts` pins that ORDERED list against `research.py` itself, parsing
  the `_setup_step(n, 6, "…")` calls out of the source when the backend tree sits beside the web one
  (it returns early when it does not, so the list written into the test holds the line everywhere
  else). What is still on five is `src/lib/firestore.ts`: its `visibility` field comment credits
  "pair Stage 2" and its `workerCount` one puts the multi-profile loop in "pair Stage 4" — Stage 3
  and Stage 5 respectively, since the split.*

---

*Updated: 2026-09-19 — **the privacy waves and the browser-side wave, read against
the release being prepared (backend 0.1.14 + agent 0.1.33).** Each item below has
its own section above; what is here is the shape and where to look.*

- ***Images inside extracted platform documents are kept now.*** *Every HTML
  capture route used to delete them along with their alt text. They are fetched
  once per research, handed to the app and referenced by digest — see* Document
  images *for the address guards, the budgets and what a refusal remembers.*
- ***⛔ And that document's per-image deadline was a silent no-op on Windows
  until 2026-09-18.*** *`socket.shutdown` returns success there and does nothing,
  so the class that exists to replace a socket timeout was bounded by the socket
  timeout it replaces — an abortive close (SO_LINGER, then close) lands on
  Windows INSTEAD of `shutdown`, and the order is load-bearing. Images quietly
  became captions on the platform the research computer actually runs.*
- ***A computer can be findable, and who may find it has two names.*** *See*
  Public computers. *`visibility` is becoming `joinPolicy`; the machine READS
  both, OLD NAME FIRST, and writes only the old one. 7.7E stopped the device
  document — which every sharer reads whole — from carrying anybody's topic, and
  scoped the sharer-tree rehydration scan to this machine.*
- ***The local API left the network (2026-09-05), then learned to ask who is
  calling (2026-09-20).*** *It bound every interface, with a wildcard CORS
  origin and no authentication of any kind, for the whole of its life. Loopback
  closed the network half and was honest that it was only half — in a test, so
  it could not be forgotten. Wave 10.5 closed the rest with ONE ASGI gate under
  all fourteen routes, so route fifteen is covered by existing rather than by
  somebody remembering to decorate it.*
- ***The heartbeat gained a twin no clock can be wrong about.*** *`heartbeatAt`,
  server-stamped, in the SAME atomic update as `lastHeartbeat` — which is also why
  the rules must deploy and be verified in production BEFORE this wheel publishes.*
- ***Phase 3 completes on a podcast, not on the absence of a skip*** *(stretch
  6.6C), and the P2 platform share step came out in the same round (6.6B) — 2.2
  minutes and 21.7 CUA calls per run for a link nothing in the pipeline gated on.*
- ***A support bundle is per RUN now, and the 30-day promise has a clock.*** *A
  sharer can report their own broken run; attribution rests on the field the rules
  pin and fails closed; the machine-level material is the owner's AND opt-in; the
  cloud's own P4/P5 lines are pulled down into the run folder the collector
  already walks. See* Diagnostics.
- ***The agent's own log travels alone (wave 8).*** *`/logs/agent-log` gained a
  DECLARED standalone mode with a support code of its own — never inferred from a
  missing code, so a client that drops its code takes the refusal instead of
  silently opening a bundle nobody was told about — and the rotated copies go with
  it. That half lives in the agent package; see `agent/README.md`.*
- ***The model pins were re-read against the live GA list rather than recalled
  (2026-09-17).*** *`GEMINI_TEXT` and `GEMINI_NARRATE` move together to
  `gemini-3.8-flash`, because a differential test rests on the two agreeing.
  ⛔ The Pro hedge had to take the `gemini-pro-latest` ALIAS: there is no numbered
  3.x Pro at all, and the only other Pro-class `generateContent` model deprecates
  2026-10-16. It costs reproducibility, deliberately — pin it and delete the note
  the day a numbered GA Pro appears.*
- ***Wave 10, the browser half.*** *Gemini's own Redo now reaches a research that
  DIED, at a new site in the post-Start error branch, entered on the machine's own
  reader rather than on the vision model's `error` verdict — a Gemini research
  failure is a chat bubble, and both prompts define that verdict as a banner or a
  popup. A stuck research reloads itself on a bounded CADENCE rather than a
  detector (`_GEMINI_STALE_RELOAD_SEC`, 12 minutes, capped at three by
  `_GEMINI_STALE_RELOAD_MAX`), because the growth clock advances on signals that
  surface does not feed.*
- ***And the three agent reports carry numbered source links.*** *⛔ NOT the app's
  `[[n]]` token — the app reserves that for what a MODEL writes and rewrites every
  instance against its own numbering, so a machine marker in that grammar would
  open the wrong page with nothing raised. The machine emits `[\[n\]](url)`,
  which renders identically and contains nothing the app's regex can find.
  `brief.md` is deliberately NOT numbered: it is the file the agents are handed,
  and one echoed marker would make a whole report skip numbering.*
- ***A machine nothing supervises can now recover from a reset on its own.*** *One
  pure classifier answers "which credential state is this computer in", every
  advice site asks it, and four of them used to print `--pair` on a machine that
  still had its device id — which mints a new one and silently unlists a public
  computer. `--serve`'s relink exit now asks whether anything will restart it and
  re-execs itself once when nothing will. See* Credential state, and recovery on a
  machine nothing supervises.
- ***Two ways a run could need somebody and tell nobody.*** *`wait_if_paused` was
  unbounded and is the one wait the watchdog excludes by design, so a parked run
  sat forever; and the notify seam keyed on event NAMES, so a blocker raised
  through an `event_name` override — every sign-in, HV and manual-brief card —
  reached no one. Bounded at 24h, gated on `recoverability == "blocker"`. See* A
  parked run.
- ***Every Settings button on the device listener passes one clock-skew gate.***
  *`_is_stale_replay` — live commands are never stale, and the gate that says so
  had been written twice and fixed once. On a computer running ~30s fast, Update,
  Restart, Hard Reset, Clear logs and all three send-logs actions did nothing,
  with no log line. See the note above the device-scoped commands table.*
- ***The off-topic guard moved to the sink on 2026-08-05 and this file had never
  named it.*** *It is the thing standing between a wrong extraction and
  `documents/chatgpt.md`; the* Document images *section had been citing it as an
  ordering constraint for a section that did not exist. It does now.*
