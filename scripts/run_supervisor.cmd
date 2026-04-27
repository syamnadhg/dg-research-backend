@echo off
REM SuperResearchBackend supervisor wrapper.
REM Sets Vision shadow-eval env vars then launches research.py --daemon-loop.
REM Edit DG_VISION_TIER below to toggle shadow / off / tier2 without re-creating
REM the Scheduled Task.

REM Vision tier flag (off|shadow|tier2|tier3) — Track A uses shadow.
set "DG_VISION_TIER=shadow"

REM Auto-harvest screenshots into tests/fixtures/vision/auto/<hotspot>/
set "DG_VISION_FIXTURE_AUTO=1"

REM Tag for shadow records — change per Track A retest.
set "DG_RUN_ID=track-a-2026-04-26"

REM Optional: override shadow log path. Default is logs/vision_shadow.jsonl
REM set "DG_VISION_SHADOW_LOG=logs\vision_shadow.jsonl"

cd /d "C:\Users\syamn\research-dg\Automate\DG Research\research-automate"
"C:\Python314\python.exe" research.py --daemon-loop
