# Research Queues

Each pipeline run creates a directory with all outputs.

```
queues/<topic>_<timestamp>/
  meta.json              — Frontend Research object (updated each phase)
  config.json            — Pipeline config (skipped phases, agents, video/email flags)
  delivery.json          — Live links (updated incrementally)
  owner.json             — {uid, researchId}; identifies the run owner so queue
                           cleanup can cascade the Firestore delete of
                           users/{uid}/researches/{rid}. Written at run creation.
  documents/
    brief.md             — Phase 1: Research brief
    chatgpt.md           — Phase 2: ChatGPT deep research
    gemini.md            — Phase 2: Gemini deep research
    claude.md            — Phase 2: Claude deep research
  podcasts/
    *.m4a                — Phase 3: Audio overview from NotebookLM
  video/
    research_overview.mp4 — Phase 4: YouTube video
  thumbnail.png          — Phase 4: Generated thumbnail
  links.json             — Share/publish URLs collected during pipeline
  checkpoint.json        — Resume data (last completed phase, state)
  .stop / .pause         — Sentinel files (legacy fallback; primary stop/pause
                           goes via Firestore commands)
```

> **Note**: `events.jsonl` (per-run event log) was removed 2026-04-29. Events
> now live exclusively in Firestore at `users/{uid}/researches/{rid}/pipeline_events/`.
> The FE reads pipeline events from Firestore via `onSnapshot`, not by polling
> any local HTTP/file endpoint.

## Pipeline Phases (0-5)

| Phase | Output in queues/ |
|-------|-------------------|
| 0. Init | meta.json created |
| 1. Brief | documents/brief.md |
| 2. Research | documents/chatgpt.md, gemini.md, claude.md (parallel) |
| 3. NLM + Audio | podcasts/*.m4a |
| 4. YouTube | video/research_overview.mp4, thumbnail.png |
| 5. Report | Google Doc + email delivery (FE-owned); delivery.json updated with gdoc URL |

Phase 2 runs 3 parallel research agents. Each saves output as separate MD.
delivery.json updates incrementally — frontend reads it for live link availability.
meta.json contains per-agent stats (sources, sections, timing) for analytics graphs.
