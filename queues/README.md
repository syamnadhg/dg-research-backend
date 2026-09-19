# Research Queues

Each pipeline run creates a directory with all outputs.

```
queues/<topic>_<timestamp>/
  owner.json             — {uid, researchId}; identifies the run owner so queue
                           cleanup can cascade the Firestore delete of
                           users/{uid}/researches/{rid}. Written at run creation.
  config.json            — Pipeline config (agents, skipPhases, podcastLength,
                           video/email flags, autoSkipStuck). Written at run
                           creation; POST /api/runs/{id}/resume merges into it.
  meta.json              — Frontend Research object: a scan of documents/ and
                           podcasts/, per-agent stats, phase timeline. FIRST
                           written at the END of Phase 1, then updated each phase.
  checkpoint.json        — Resume data (last_completed_phase, topic, brief_url,
                           notebook_url, audio_path, tier-escalation history,
                           per-agent states, last_event_id). Written after
                           Phases 1-3.
  checkpoint_pause.json  — Browser/page state written by the pause path; cleared
                           on resume.
  delivery.json          — Live links + run status (updated incrementally)
  links.json             — Written at Phase 3 from the P2→P3 handoff. Its
                           EXISTENCE is the resume-from-Phase-3 signal.
  phase2_complete.marker — {completedAt, doneCount, totalAgents, skippedAgents}.
                           Written only on a CLEAN Phase 2 finish, so a stop or
                           pause mid-P2 makes resume re-run Phase 2.
  feedback.json          — {phase: message} from POST /api/runs/{id}/feedback;
                           the entry is cleared when Phase 1 or 2 consumes it.
  .p2_sources.json       — Manifest of which documents/ files are user-attached
                           sources, plus the once-only "attach them to P2"
                           decision. Durable across pause/resume and hard retry.
  documents/
    brief.md             — Phase 1: Research brief
    chatgpt.md           — Phase 2: ChatGPT deep research
    gemini.md            — Phase 2: Gemini deep research
    claude.md            — Phase 2: Claude deep research
    <attached files>     — Flow B: user-supplied sources downloaded from Storage
                           (md/txt/pdf/docx), sanitized filenames
  podcasts/
    *.mp3                — Phase 3: Audio overview from NotebookLM, transcoded
                           from the downloaded .m4a (see below)
  .stop / .pause         — Sentinel files (legacy fallback; primary stop/pause
                           goes via Firestore commands)
```

Alongside the run directories, `queues/` itself holds `_pending_queue.json`
(worker 1's job-queue snapshot; `_pending_queue_worker_{N}.json` for the other
workers) and the `.worker.{N}.lock` / `.worker.{N}.dead` sentinels.

> **Note**: `events.jsonl` (per-run event log) was removed 2026-04-29. Events
> now live exclusively in Firestore at `users/{uid}/researches/{rid}/pipeline_events/`.
> The FE reads pipeline events from Firestore via `onSnapshot`, not by polling
> any local HTTP/file endpoint.

> **Note**: `documents/consolidated.md` is no longer written to disk (removed
> 2026-09-18). Every consumer of `documents/` already refused it by name — the
> P3 NotebookLM scan, the Flow-B fallback scan and the P1 attach scan each carry
> a derived-stem exclusion — and it disagreed with its own inputs on any re-run,
> because only the first Phase 2 pass ever built it. The concatenation is still
> mirrored to Firestore under the `consolidated` doc type, which is what the
> app's P5 Summary reads.

> **Note**: there is no `video/` directory and no `thumbnail.png`. Phase 4
> (YouTube) and Phase 5 (Doc + email) run entirely in the frontend, so the
> backend writes nothing to disk for them. `delivery.json` still *declares*
> `doc_url` and `email_sent` — the app owns those slots and fills them there.

> **Note**: run *logs* are not here. Each attempt gets its own folder under
> `~/.super-research/logs/runs/` holding `run.log`, its own `meta.json`,
> `events.json` and (once the cloud half arrives) `cloud.log`. That tree is what
> `--send-logs` collects and what the 30-day retention sweep prunes; `queues/`
> is untouched by both.

## Pipeline Phases (0-5)

| Phase | Output in queues/ |
|-------|-------------------|
| 0. Init | run dir + documents/ created; owner.json, config.json written |
| 1. Brief | documents/brief.md; first meta.json + checkpoint.json |
| 2. Research | documents/chatgpt.md, gemini.md, claude.md (parallel); phase2_complete.marker on a clean finish |
| 3. NLM + Audio | links.json, podcasts/*.mp3 |
| 4. YouTube | nothing — FE-owned |
| 5. Report | nothing — FE-owned (Google Doc + email) |

Phase 2 runs 3 parallel research agents. Each saves output as separate MD.
delivery.json updates incrementally — frontend reads it for live link availability.
meta.json contains per-agent stats (sources, sections, timing) for analytics graphs.

## What the MD files carry

Before any document is written — the brief, the three reports, a re-save on
resume or retry — every image in it goes through one rehost pass: fetched once
per research, handed to the web, and rewritten as
`/document-images/{researchId}/{sha256}.{ext}`. No image bytes land in the run
directory. An image that could not be stored (decorative, over the caps, or a
scheduled process exit cancelling the fetch) is left as a caption with no
address.

The three agent reports also get a numbered Sources bibliography appended before
they are written, built from the findings extracted out of the clean report.
`brief.md` deliberately does not — that file is what ChatGPT and Claude are
handed, and numbering it fed the agents our own idempotency marker.

## Links, not conversation addresses

Phase 2's platform share-link extraction was removed (2026-08-28): it cost ~2.2
minutes and 21.7 CUA calls per run for a link nothing gated on, and Phase 2's
completion gate was always `n_chars > 0 and md_saved`. Nothing in the run
directory holds a platform share URL any more.

The values in `links.json` and in `delivery.json`'s `research_links` are this
app's own report pages — `/documents?open={researchId}:{kind}` — keyed by display
name. `checkpoint.json`'s `brief_url` is the same shape. The raw conversation
address is still *read* during the Phase 2→3 handoff, because the off-topic
sweep's verdict and the ChatGPT stale-tab age test are recorded against it, but
it is not what gets written.

## Podcast files

The Playwright download event saves NotebookLM's suggested filename, sanitized
(non-`\w\s.-` characters stripped). If that event never fires, a content-based
scan of the download directories recovers the file — copied out of the user's
Downloads, moved only out of Playwright's own artifacts directory.

The file is then transcoded to a constant-bitrate mp3, because NotebookLM's
.m4a puts its `moov` atom at the end of the file and a cloud agent that streams
the URL cannot begin playback. On success the source .m4a is deleted so exactly
one file per stem remains — `save_meta` globs the directory and would otherwise
double-count the podcast. On a missing ffmpeg or a failed transcode the original
file is kept unchanged, so the podcast is never lost.

Phase 3 reports **complete** only once the audio has actually been stored
(2026-08-28). A run that produced no playable podcast reports a skip naming
which half failed — `no_audio_generated`, or `audio_generated_but_upload_failed`
when the file is sitting in `podcasts/` but never reached the app.
