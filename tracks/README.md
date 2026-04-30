# tracks/ — DEPRECATED 2026-04-29

This directory is **no longer written to by the pipeline.** The previous
implementation persisted per-run event logs (`events.jsonl`) and per-platform
scrape snapshots (`phase{0..5}/{platform}.json`) here. Both write paths were
removed when Firestore became the sole transport for pipeline events.

## Where event data lives now

Firestore subcollection per research run:

```
users/{uid}/researches/{researchId}/pipeline_events/{autoId}
```

Each doc carries the same shape as the old events.jsonl entries (`type`,
`phase`, `agent`, `data`, `seq`, `expireAt`). FE reads via Firestore
`onSnapshot`. A 30-day TTL policy on `pipeline_events.expireAt` prunes
old events automatically.

## What's safe to do with this directory

- **Delete it.** Old `tracks/{topic}_{timestamp}/` folders from pre-2026-04-29
  runs are pure cache and don't affect any current code path.
- **Leave it.** Nothing reads from it; the directory just consumes disk.

## Why the change

Disk-mirroring events.jsonl was redundant with Firestore + costlier to
operate (every emit_event was a dual-write). Removing it simplified the
event flow to a single sink and dropped ~150 LOC of dead reader code.

For the canonical event-type catalog and per-phase semantics, see
`research-automate/ARCHITECTURE.md`.
