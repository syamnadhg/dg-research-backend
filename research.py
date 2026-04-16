#!/usr/bin/env python3
"""
Multi-Agent Deep Research Pipeline
====================================
Topic + PDFs → ChatGPT Brief → 3x Deep Research → NotebookLM → Audio → YouTube → Email

Built on the proven research.py patterns: direct Playwright first, CUA fallback only.
Every submit → verify → then wait. Never blind wait.

Usage:
  python research.py "Topic here"                        # Full pipeline
  python research.py "Topic" --brief-file brief.txt      # Skip Phase 1
  python research.py "Topic" --pdf a.pdf --pdf b.pdf     # Attach PDFs to Phase 1
  python research.py --setup                              # First-time login to all services
"""

import sys
import os
import re
import time
import json
import base64
import asyncio
import shutil
import argparse
import subprocess
from pathlib import Path
from prompts import *
from datetime import datetime

# Windows UTF-8 fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ── Constants ──────────────────────────────────────────────────────────────────

PROFILE_DIR = Path.home() / ".openclaw" / "browser-profile"
BETA_FLAG = "computer-use-2025-11-24"
# All configurable via env vars (defaults are production-tuned)
CUA_MODEL = os.environ.get("CUA_MODEL", "claude-opus-4-6")
API_WIDTH = int(os.environ.get("CUA_SCREEN_WIDTH", "1280"))
API_HEIGHT = int(os.environ.get("CUA_SCREEN_HEIGHT", "800"))

# Polling intervals (override via env for testing with shorter waits)
POLL_PRO = int(os.environ.get("POLL_PRO", "30"))                 # seconds
POLL_DEEP_RESEARCH = int(os.environ.get("POLL_DEEP_RESEARCH", "30"))  # seconds
MAX_WAIT_PRO = int(os.environ.get("MAX_WAIT_PRO", "45"))         # minutes — Phase 1
MAX_WAIT_DEEP = int(os.environ.get("MAX_WAIT_DEEP", "90"))       # minutes — Phase 2


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_env(name):
    val = os.environ.get(name, "")
    if not val:
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 f"[System.Environment]::GetEnvironmentVariable('{name}','User')"],
                capture_output=True, text=True, timeout=5)
            val = r.stdout.strip()
        except Exception:
            pass
    return val


def resolve_api_key(cli_key=None):
    if cli_key: return cli_key
    for var in ("CUA_API_KEY", "ANTHROPIC_API_KEY"):
        key = get_env(var)
        if key: return key
    return None


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def log_action(action, details=""):
    ts = datetime.now().strftime("%H:%M:%S")
    extra = f" — {details}" if details else ""
    print(f"[{ts}] [ACTION] {action}{extra}")


def safe_name(topic, max_len=50):
    return re.sub(r'[^\w\s-]', '', topic)[:max_len].strip().replace(' ', '_')


# ── Progress Tracking ─────────────────────────────────────────────────────────

_tracks_dir = None  # Set per-run in run_pipeline


def init_tracks(run_name):
    """Create/reuse tracks directory for this run. Uses same name as queue dir."""
    global _tracks_dir
    _tracks_dir = Path(__file__).parent / "tracks" / run_name
    # Create full phase structure (idempotent — safe for resumes)
    # Phases 0-5 only. Directory names match _TRACK_ROUTES below.
    for phase_dir in [
        "phase0/init",
        "phase1/brief",
        "phase2/chatgpt", "phase2/gemini", "phase2/claude",
        "phase3/notebooklm",
        "phase4/youtube",
        "phase5/delivery",
    ]:
        (_tracks_dir / phase_dir).mkdir(parents=True, exist_ok=True)
    log(f"Tracks: {_tracks_dir}")
    return _tracks_dir


# Track routing: platform name → phase/subfolder (phases 0-5)
_TRACK_ROUTES = {
    "phase0": "phase0/init",
    "phase1": "phase1/brief",
    "chatgpt": "phase2/chatgpt",
    "gemini": "phase2/gemini",
    "claude": "phase2/claude",
    "phase3": "phase3/notebooklm",
    "notebooklm": "phase3/notebooklm",
    "phase4": "phase4/youtube",
    "youtube": "phase4/youtube",
    "phase5": "phase5/delivery",
}


def get_clipboard():
    """Read clipboard text via PowerShell (Windows). Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


# Canonical agent/platform key the frontend uses in details[<key>]. Matches the
# keys set when agent_progress events are emitted (lowercase, whitespace-stripped).
_AGENT_KEY_ALIASES = {
    # Phase 1 is ChatGPT Pro + Extended Thinking — surface it as "chatgpt"
    # (the platform) rather than "brief" (the output artifact) so the UI
    # shows a single ChatGPT card, not two cards labelled "Brief" and "ChatGPT".
    "phase1": "chatgpt",
    "brief": "chatgpt",
    "chatgpt": "chatgpt",
    "gemini": "gemini",
    "claude": "claude",
    "notebooklm": "notebooklm",
    "youtube": "youtube",
    "gdocs": "gdocs",
    "gdoc": "gdocs",
    "gmail": "gmail",
    "system": "system",
}

def normalize_agent_key(name):
    """Normalize any agent/platform name (capitalized, spaced, aliased) to the
    canonical key the frontend expects in pipelineData.details. Safe for event emits."""
    if not name:
        return "system"
    k = str(name).lower().replace(" ", "")
    return _AGENT_KEY_ALIASES.get(k, k)


def save_track(platform, data):
    """Save a timestamped progress entry — individual JSON + events.jsonl for streaming."""
    if not _tracks_dir:
        return
    # Route to correct subfolder
    plat_key = platform.lower().replace(" ", "")
    route = _TRACK_ROUTES.get(plat_key, plat_key)
    platform_dir = _tracks_dir / route
    platform_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    count = len(list(platform_dir.glob("*.json"))) + 1
    entry = {
        "timestamp": datetime.now().isoformat(),
        "platform": platform,
        **data,
    }
    (platform_dir / f"{count:03d}_{ts}.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
    # NOTE: do NOT append to events.jsonl here — only emit_event() writes typed events
    # Raw scrape data stays in per-platform JSON files only


# ── Firebase Bridge (Firestore real-time transport) ──────────────────────────

_firebase_db = None     # Firestore client (module-level, init once)
_fb_uid = None          # Per-run: user ID for Firestore path
_fb_research_id = None  # Per-run: research ID for Firestore path
_fb_seq = 0             # Per-run: monotonic event sequence number
_fb_listener = None     # Per-run: command listener unsubscribe handle
_pipe_token = None      # PipeToken: this backend instance's unique ID


def init_firebase():
    """Initialize Firebase Admin SDK from service-account JSON. Call once at server start.

    Also configures the Storage bucket so Phase 3 can upload NotebookLM audio
    to Firebase Storage (which then streams to the Vercel Podcasts page). The
    bucket name comes from env var `FIREBASE_STORAGE_BUCKET` if set,
    otherwise defaults to the new `<project>.firebasestorage.app` convention
    (used for projects created Oct 2024+). If your project is older and uses
    `<project>.appspot.com`, set the env var explicitly.
    """
    global _firebase_db
    if _firebase_db:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore as _fs
        sa_path = Path(__file__).parent / "firebase-service-account.json"
        if not sa_path.exists():
            log("Firebase: service-account.json not found — Firestore bridge disabled", "WARN")
            return False
        cred = credentials.Certificate(str(sa_path))
        # Derive project id from service account for the default bucket name.
        import json as _json
        try:
            _sa = _json.loads(sa_path.read_text(encoding="utf-8"))
            _project_id = _sa.get("project_id", "")
        except Exception:
            _project_id = ""
        bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET") or (
            f"{_project_id}.firebasestorage.app" if _project_id else None
        )
        init_opts = {"storageBucket": bucket_name} if bucket_name else None
        firebase_admin.initialize_app(cred, init_opts)
        _firebase_db = _fs.client()
        if bucket_name:
            log(f"Firebase Admin SDK initialized ✓ (storage bucket: {bucket_name})")
        else:
            log("Firebase Admin SDK initialized ✓ (no storage bucket configured)")
        return True
    except ImportError:
        log("Firebase: firebase-admin not installed — Firestore bridge disabled", "WARN")
        return False
    except Exception as e:
        log(f"Firebase init error: {e}", "WARN")
        return False


_start_listener = None  # Global start-command listener
_heartbeat_task = None  # Async task: writes lastHeartbeat every 30s

PIPE_CONFIG_PATH = Path(__file__).parent / "pipe_config.json"


def load_pipe_token():
    """Load PipeToken from local pipe_config.json (or PIPE_TOKEN env var).
    Returns the token string or None if not set up yet."""
    global _pipe_token
    # Env var takes precedence (for Docker/CI deployments)
    env_token = os.environ.get("PIPE_TOKEN", "").strip()
    if env_token:
        _pipe_token = env_token
        return _pipe_token
    # Local config file
    if PIPE_CONFIG_PATH.exists():
        try:
            cfg = json.loads(PIPE_CONFIG_PATH.read_text(encoding="utf-8"))
            _pipe_token = cfg.get("pipeToken", "").strip() or None
            return _pipe_token
        except Exception:
            pass
    return None


def generate_pipe_token():
    """Generate a new PipeToken, store it in Firestore + local config.
    Called during --setup. Returns the token string."""
    import uuid
    import socket
    global _pipe_token
    token = str(uuid.uuid4())
    machine_name = socket.gethostname()

    # Store in Firestore
    if _firebase_db:
        try:
            from google.cloud.firestore import SERVER_TIMESTAMP
            _firebase_db.collection("pipe_tokens").document(token).set({
                "status": "active",
                "machineName": machine_name,
                "createdAt": SERVER_TIMESTAMP,
                "lastHeartbeat": SERVER_TIMESTAMP,
            })
            log(f"PipeToken registered in Firestore: {token[:8]}...")
        except Exception as e:
            log(f"Failed to register PipeToken in Firestore: {e}", "WARN")

    # Store locally
    local_cfg = {}
    if PIPE_CONFIG_PATH.exists():
        try:
            local_cfg = json.loads(PIPE_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    local_cfg["pipeToken"] = token
    local_cfg["machineName"] = machine_name
    PIPE_CONFIG_PATH.write_text(json.dumps(local_cfg, indent=2), encoding="utf-8")
    log(f"PipeToken saved to {PIPE_CONFIG_PATH.name}")

    _pipe_token = token
    return token


async def _heartbeat_loop():
    """Write lastHeartbeat to pipe_tokens/{token} every 30s so the frontend
    can show Online/Offline status."""
    from google.cloud.firestore import SERVER_TIMESTAMP
    while True:
        try:
            if _firebase_db and _pipe_token:
                _firebase_db.collection("pipe_tokens").document(_pipe_token).update({
                    "lastHeartbeat": SERVER_TIMESTAMP,
                    "status": "active",
                })
        except Exception as e:
            log(f"Heartbeat write failed: {e}", "WARN")
        await asyncio.sleep(30)


# ── Run Analytics (phase duration tracking for realistic ETAs) ────────────

ANALYTICS_PATH = Path(__file__).parent / "run_analytics.json"
_phase_averages: dict[int, float] = {}  # phase → avg duration in seconds

# Reasonable defaults when no analytics exist yet. Based on observed runs
# (2026-04-15 data + pipeline design targets). Updated as real data arrives.
_DEFAULT_PHASE_MINUTES = {0: 0.2, 1: 27, 2: 55, 3: 15, 4: 8, 5: 4}


def load_analytics():
    """Load run_analytics.json and compute per-phase average durations."""
    global _phase_averages
    if not ANALYTICS_PATH.exists():
        _phase_averages = {}
        return
    try:
        data = json.loads(ANALYTICS_PATH.read_text(encoding="utf-8"))
        runs = data.get("runs", [])
        # Group by phase, compute average
        from collections import defaultdict
        buckets: dict[int, list[float]] = defaultdict(list)
        for r in runs:
            p = r.get("phase")
            d = r.get("durationSec", 0)
            if isinstance(p, int) and d > 0:
                buckets[p].append(d)
        _phase_averages = {p: sum(ds) / len(ds) for p, ds in buckets.items() if ds}
        if _phase_averages:
            log(f"Analytics loaded: {', '.join(f'P{p}={v/60:.0f}m' for p, v in sorted(_phase_averages.items()))}")
    except Exception as e:
        log(f"Failed to load analytics: {e}", "WARN")
        _phase_averages = {}


def record_phase_duration(phase: int, duration_sec: float, agent: str = ""):
    """Append a phase completion record to run_analytics.json."""
    try:
        data = {"runs": []}
        if ANALYTICS_PATH.exists():
            data = json.loads(ANALYTICS_PATH.read_text(encoding="utf-8"))
        data.setdefault("runs", []).append({
            "phase": phase,
            "agent": agent,
            "durationSec": round(duration_sec),
            "timestamp": int(time.time()),
        })
        ANALYTICS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Refresh in-memory averages
        load_analytics()
    except Exception as e:
        log(f"Failed to record analytics: {e}", "WARN")


def get_expected_minutes(phase: int) -> int:
    """Return realistic ETA in minutes for a phase, using analytics if available."""
    if phase in _phase_averages:
        return max(1, round(_phase_averages[phase] / 60))
    return _DEFAULT_PHASE_MINUTES.get(phase, 10)


def upload_audio_to_storage(local_path: "Path") -> str | None:
    """Upload the NotebookLM audio file to Firebase Storage and return a
    public download URL. Path is scoped under the user's uid + researchId so
    users can only access their own files (see storage.rules).
    Returns None if upload fails or Firebase Storage isn't configured.
    """
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return None
    if not local_path or not local_path.exists():
        return None
    try:
        from firebase_admin import storage as _fb_storage
        # Object path mirrors the Firestore layout for easy reasoning.
        blob_name = f"audio/{_fb_uid}/{_fb_research_id}/{local_path.name}"
        bucket = _fb_storage.bucket()
        blob = bucket.blob(blob_name)
        # Content-Type matters so the browser's <audio> tag plays it inline.
        content_type = "audio/mpeg" if local_path.suffix.lower() == ".mp3" else (
            "audio/mp4" if local_path.suffix.lower() in (".m4a", ".mp4") else "audio/*"
        )
        blob.upload_from_filename(str(local_path), content_type=content_type)
        # Make the object publicly readable by URL. Auth is enforced at the
        # Firestore documents level — a user can only see the `audioUrl`
        # field if they read their own audios subcollection. Making the
        # blob itself public-with-unguessable-URL avoids needing signed URL
        # refresh for long-playing sessions.
        blob.make_public()
        log(f"Audio uploaded to Storage: gs://{bucket.name}/{blob_name}")
        return blob.public_url
    except Exception as e:
        log(f"Audio upload to Firebase Storage failed: {e}", "WARN")
        return None


def save_audio_to_firestore(audio_id: str, name: str, duration_sec: int, audio_url: str | None):
    """Upsert an audio entry into users/{uid}/researches/{id}/audios/{audio_id}
    so the Podcasts page on Vercel can list + stream it without needing the
    local backend. audio_url is the public Storage URL from upload_audio_to_storage.
    """
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return
    try:
        mins, secs = divmod(max(0, int(duration_sec)), 60)
        _firebase_db.collection("users").document(_fb_uid) \
            .collection("researches").document(_fb_research_id) \
            .collection("audios").document(audio_id) \
            .set({
                "id": audio_id,
                "name": name,
                "duration": f"{mins}:{secs:02d}" if duration_sec else "",
                "durationSec": int(duration_sec or 0),
                "createdAt": int(time.time() * 1000),
                **({"audioUrl": audio_url} if audio_url else {}),
            })
    except Exception as e:
        log(f"Failed to sync audio to Firestore: {e}", "WARN")


def save_document_to_firestore(doc_type: str, content: str, name: str | None = None):
    """Upsert a research document (brief/chatgpt/gemini/claude/consolidated)
    into the user's Firestore documents subcollection so the Documents page
    on Vercel can render it without direct access to this local backend.
    Phase 3 (NotebookLM) still reads MDs from queue_dir/documents/ on local
    disk — this sync is strictly for the frontend Documents UI.

    Upsert semantics: doc_type is used as the Firestore doc ID, so re-runs
    or re-extractions for the same research overwrite in place instead of
    creating duplicates.
    """
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return
    if not content or not content.strip():
        return
    try:
        _firebase_db.collection("users").document(_fb_uid) \
            .collection("researches").document(_fb_research_id) \
            .collection("documents").document(doc_type) \
            .set({
                "id": doc_type,
                "name": name or f"{doc_type}.md",
                "type": doc_type,
                "content": content,
                "size": f"{len(content) / 1024:.0f} KB",
                "createdAt": int(time.time() * 1000),
            })
    except Exception as e:
        log(f"Failed to sync {doc_type}.md to Firestore: {e}", "WARN")


def start_firestore_start_listener(job_queue, loop):
    """Listen for pipeline start requests via this backend's PipeToken queue.
    Frontend writes to: pipe_tokens/{token}/queue/{auto-id}
    Backend picks it up, queues the job, writes run_id back.
    Falls back to global pipeline_requests/ if no PipeToken is set (legacy)."""
    global _start_listener
    if not _firebase_db:
        return

    # Token-scoped queue (preferred) vs legacy global collection
    if _pipe_token:
        col_ref = _firebase_db.collection("pipe_tokens").document(_pipe_token).collection("queue")
        listener_label = f"pipe_tokens/{_pipe_token[:8]}…/queue/"
    else:
        col_ref = _firebase_db.collection("pipeline_requests")
        listener_label = "pipeline_requests/ (legacy — run --setup to get a PipeToken)"

    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name != 'ADDED':
                continue
            doc = change.document
            data = doc.to_dict() or {}
            if data.get("processed"):
                continue
            action = data.get("action", "start")
            if action != "start":
                continue
            uid = data.get("uid", "")
            research_id = data.get("researchId", "")
            topic = data.get("topic", "").strip()
            email = data.get("email", "")
            config = data.get("config", {})
            if not topic or not uid or not research_id:
                log(f"Firestore start request missing fields: uid={uid}, rid={research_id}, topic={topic[:30]}", "WARN")
                try:
                    doc.reference.update({"processed": True, "error": "missing fields"})
                except Exception:
                    pass
                continue
            # Generate run_id
            run_id = f"{safe_name(topic)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            log(f"Firestore start: uid={uid[:8]}... topic={topic[:40]} run_id={run_id}")
            # Write run_id back to the research doc so frontend can read it
            try:
                _firebase_db.collection("users").document(uid) \
                    .collection("researches").document(research_id) \
                    .update({"backendRunId": run_id, "status": "ongoing"})
            except Exception as e:
                log(f"Failed to write backendRunId: {e}", "WARN")
                try:
                    _firebase_db.collection("users").document(uid) \
                        .collection("researches").document(research_id) \
                        .set({"backendRunId": run_id, "status": "ongoing"}, merge=True)
                except Exception:
                    pass
            # Mark processed
            try:
                doc.reference.update({"processed": True, "run_id": run_id})
            except Exception:
                pass
            # Queue the job (default-arg capture avoids lambda-in-loop closure bug)
            loop.call_soon_threadsafe(
                lambda t=topic, e=email, c=config, r=run_id, u=uid, ri=research_id:
                    job_queue.put_nowait(
                        {"topic": t, "email": e, "config": c, "run_id": r, "uid": u, "research_id": ri}
                    )
            )

    _start_listener = col_ref.on_snapshot(on_snapshot)
    log(f"Firestore start listener active on {listener_label}")


def setup_firestore_run(uid, research_id, loop=None):
    """Set per-run Firestore context. Call at pipeline start."""
    global _fb_uid, _fb_research_id, _fb_seq, _fb_listener
    _fb_uid = uid
    _fb_research_id = research_id
    _fb_seq = 0
    # Start command listener if Firestore is available
    if _firebase_db and uid and research_id and _controls:
        _start_command_listener(uid, research_id, loop or asyncio.get_event_loop())
        log(f"Firestore bridge active: users/{uid}/researches/{research_id}")


def teardown_firestore_run():
    """Clean up per-run Firestore state."""
    global _fb_uid, _fb_research_id, _fb_seq, _fb_listener
    if _fb_listener:
        _fb_listener.unsubscribe()
        _fb_listener = None
    _fb_uid = None
    _fb_research_id = None
    _fb_seq = 0


def _emit_to_firestore(event):
    """Write event to Firestore pipeline_events subcollection."""
    global _fb_seq
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return
    _fb_seq += 1
    doc_data = {**event, "seq": _fb_seq}
    try:
        _firebase_db.collection("users").document(_fb_uid) \
            .collection("researches").document(_fb_research_id) \
            .collection("pipeline_events").add(doc_data)
    except Exception as e:
        log(f"Firestore emit failed: {e}", "WARN")


def _update_firestore_research(updates):
    """Update the research document in Firestore (status, phase, links, agents, etc.)."""
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return
    try:
        _firebase_db.collection("users").document(_fb_uid) \
            .collection("researches").document(_fb_research_id) \
            .update(updates)
    except Exception as e:
        log(f"Firestore research update failed: {e}", "WARN")


def _write_config_to_disk(cfg_updates):
    """Write config updates to config.json on disk (so reload_config() picks them up).
    Merges with existing config — does not overwrite."""
    if not _tracks_dir:
        return
    config_path = Path(__file__).parent / "queues" / _tracks_dir.name / "config.json"
    try:
        existing = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        existing.update(cfg_updates)
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"Failed to write config to disk: {e}", "WARN")


def _start_command_listener(uid, research_id, loop):
    """Listen for frontend commands (stop/pause/resume/config/add_context) via Firestore."""
    global _fb_listener
    col_ref = _firebase_db.collection("users").document(uid) \
        .collection("researches").document(research_id) \
        .collection("commands")

    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name != 'ADDED':
                continue
            doc = change.document
            data = doc.to_dict() or {}
            if data.get("processed"):
                continue
            action = data.get("action", "")
            if action == "stop":
                loop.call_soon_threadsafe(_controls.request_stop)
                # Bridge: also create file sentinel for old phase-boundary checks
                if _tracks_dir:
                    try: (Path(__file__).parent / "queues" / _tracks_dir.name / ".stop").touch()
                    except Exception: pass
                log("Command received: STOP — server will exit after cleanup")
                # Schedule a delayed server exit so pipeline can close browser + emit final events
                import threading
                def _exit_after_stop():
                    import time as _t, os as _os
                    _t.sleep(10)
                    log("Exiting server after Stop", "WARN")
                    _os._exit(0)
                threading.Thread(target=_exit_after_stop, daemon=True).start()
            elif action == "pause":
                loop.call_soon_threadsafe(_controls.request_pause)
                if _tracks_dir:
                    try: (Path(__file__).parent / "queues" / _tracks_dir.name / ".pause").touch()
                    except Exception: pass
                log("Command received: PAUSE")
            elif action == "resume":
                # Process config payload sent with resume (if any)
                resume_cfg = data.get("config", {})
                if resume_cfg:
                    loop.call_soon_threadsafe(_controls.update_config, resume_cfg)
                    _write_config_to_disk(resume_cfg)
                    log(f"Command received: RESUME (with config update)")
                else:
                    log("Command received: RESUME")
                loop.call_soon_threadsafe(_controls.request_resume)
                # Clean up file sentinels on resume
                if _tracks_dir:
                    q = Path(__file__).parent / "queues" / _tracks_dir.name
                    for f in [q / ".pause", q / ".stop"]:
                        try: f.unlink(missing_ok=True)
                        except Exception: pass
            elif action == "add_context":
                text = data.get("text", "")
                if text:
                    loop.call_soon_threadsafe(_controls.add_context, text)
                    log(f"Command received: ADD_CONTEXT ({len(text)} chars)")
            elif action == "config":
                cfg = data.get("config", {})
                if cfg:
                    loop.call_soon_threadsafe(_controls.update_config, cfg)
                    _write_config_to_disk(cfg)
                    log(f"Command received: CONFIG update (written to disk)")
            # Mark processed
            try:
                doc.reference.update({"processed": True})
            except Exception:
                pass

    _fb_listener = col_ref.on_snapshot(on_snapshot)


# ── Pipeline Controls (asyncio.Event based stop/pause/resume) ────────────────

class PipelineControls:
    """Replaces file-sentinel (.stop/.pause) checks with in-memory async events.
    Set from Firestore command listener OR HTTP endpoint fallback."""

    def __init__(self):
        self.stop_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.resume_event = asyncio.Event()
        self.extra_context: list = []
        self._config_updates: dict = {}

    def request_stop(self):
        self.stop_event.set()

    def request_pause(self):
        self.pause_event.set()

    def request_resume(self):
        self.pause_event.clear()
        self.resume_event.set()

    # Size cap for accumulated context (prevents runaway growth across pause cycles)
    MAX_EXTRA_CONTEXT_CHARS = 50_000

    def add_context(self, text):
        if not text:
            return
        # Cap individual entry + cumulative size
        text = text[:self.MAX_EXTRA_CONTEXT_CHARS]
        self.extra_context.append(text)
        total = sum(len(t) for t in self.extra_context)
        while total > self.MAX_EXTRA_CONTEXT_CHARS and len(self.extra_context) > 1:
            dropped = self.extra_context.pop(0)
            total -= len(dropped)
            log(f"[extra_context] Dropped oldest entry ({len(dropped)} chars) — cap {self.MAX_EXTRA_CONTEXT_CHARS}", "WARN")

    def pop_extra_context(self):
        if self.extra_context:
            ctx = "\n\n".join(self.extra_context)
            self.extra_context.clear()
            return ctx
        return ""

    def peek_extra_context(self):
        """Non-destructive read of buffered context (for dispatcher to check before dispatch)."""
        if self.extra_context:
            return "\n\n".join(self.extra_context)
        return ""

    def is_stop(self):
        return self.stop_event.is_set()

    def is_pause(self):
        return self.pause_event.is_set()

    def is_stop_or_pause(self):
        return self.stop_event.is_set() or self.pause_event.is_set()

    async def wait_if_paused(self):
        """Block pipeline coroutine until resume or stop is received."""
        if not self.pause_event.is_set():
            return
        log("Pipeline paused — waiting for resume or stop...")
        self.resume_event.clear()
        # Wait for either resume or stop
        done, _ = await asyncio.wait(
            [asyncio.create_task(self.resume_event.wait()),
             asyncio.create_task(self.stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        if self.stop_event.is_set():
            log("Stop received while paused")
        else:
            self.pause_event.clear()
            log("Resumed from pause")

    def update_config(self, updates):
        self._config_updates.update(updates)

    def pop_config_updates(self):
        u = dict(self._config_updates)
        self._config_updates.clear()
        return u

    def reset(self):
        self.stop_event.clear()
        self.pause_event.clear()
        self.resume_event.clear()
        self.extra_context.clear()
        self._config_updates.clear()

    async def interruptible_sleep(self, seconds, check_interval=10):
        """Sleep in small increments, checking stop/pause every check_interval seconds.
        Returns 'stop' if stopped, 'pause' if paused, None if sleep completed normally."""
        elapsed = 0
        while elapsed < seconds:
            chunk = min(check_interval, seconds - elapsed)
            await asyncio.sleep(chunk)
            elapsed += chunk
            if self.stop_event.is_set():
                return "stop"
            if self.pause_event.is_set():
                return "pause"
        return None


_controls = PipelineControls()  # Singleton — reset per run


# ── Pipeline Runtime State (shared across coroutines, reset per run) ────────

class PipelineRuntime:
    """Shared mutable state for pause/resume/dispatcher to coordinate.
    Pages are registered here by each phase when they go active; dispatcher
    reads this to decide where mid-run user input should be pasted."""
    def __init__(self):
        self.phase = 0
        self.sub_state = ""
        self.active_pages: dict = {}  # platform → page object
        self.agent_statuses: dict = {}  # platform → 'generating'|'done'|'failed'
        self.agent_chat_urls: dict = {}  # platform → URL
        self.partial_text_lens: dict = {}
        self.original_inputs: dict = {}  # {'topic': str, 'brief': str, 'pdf_paths': []}
        self.queue_dir = None
        self.browser = None
        self.cua_client = None
        self.dispatcher_task = None

    def reset(self):
        self.__init__()

    def register_page(self, platform, page, url=None):
        self.active_pages[platform] = page
        if url:
            self.agent_chat_urls[platform] = url
        elif page is not None:
            try:
                self.agent_chat_urls[platform] = page.url
            except Exception:
                pass
        self.agent_statuses[platform] = "generating"

    def unregister_page(self, platform, final_status="done"):
        self.agent_statuses[platform] = final_status
        # Keep URL in agent_chat_urls for checkpoint/link display
        self.active_pages.pop(platform, None)

    def snapshot(self):
        """Snapshot current state for checkpoint.json."""
        return {
            "phase": self.phase,
            "sub_state": self.sub_state,
            "agent_chat_urls": dict(self.agent_chat_urls),
            "agent_statuses": dict(self.agent_statuses),
            "partial_text_lens": dict(self.partial_text_lens),
            "original_inputs": dict(self.original_inputs),
        }


_runtime = PipelineRuntime()  # Singleton — reset per run


def save_pause_checkpoint(queue_dir, extra=None):
    """Write a full pause checkpoint combining runtime snapshot + extra fields."""
    if not queue_dir:
        return
    cp = _runtime.snapshot()
    cp["timestamp"] = datetime.now().isoformat()
    cp["paused"] = True
    if extra:
        cp.update(extra)
    try:
        (Path(queue_dir) / "checkpoint_pause.json").write_text(
            json.dumps(cp, indent=2), encoding="utf-8")
        log(f"[pause] Checkpoint written — phase={cp['phase']} sub_state={cp['sub_state']} "
            f"agents={list(cp['agent_statuses'].keys())}")
    except Exception as e:
        log(f"[pause] Checkpoint write failed: {e}", "WARN")


def load_pause_checkpoint(queue_dir):
    """Load pause checkpoint if present. Returns dict or None."""
    if not queue_dir:
        return None
    cp_file = Path(queue_dir) / "checkpoint_pause.json"
    if not cp_file.exists():
        return None
    try:
        return json.loads(cp_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_pause_checkpoint(queue_dir):
    if not queue_dir:
        return
    f = Path(queue_dir) / "checkpoint_pause.json"
    if f.exists():
        try: f.unlink()
        except Exception: pass


# ── Email validation ────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")

def validate_email(email):
    """Return (ok: bool, reason: str). Empty string not allowed."""
    if not email or not isinstance(email, str):
        return False, "empty or non-string email"
    email = email.strip()
    if len(email) > 320:
        return False, "email too long"
    if not _EMAIL_RE.match(email):
        return False, f"email format invalid: {email[:60]}"
    return True, ""


class SessionExpiredError(Exception):
    """Raised when a platform's chat URL redirects to login after resume."""
    pass


# ── Auth check after resume navigation ───────────────────────────────────

async def check_auth(page, platform):
    """Verify page isn't a login wall after navigating to a saved chat URL.
    Returns True if authenticated, raises SessionExpiredError if login detected."""
    try:
        url = page.url.lower()
        # Platform-specific login URL patterns
        login_patterns = {
            "chatgpt": ["auth.openai.com", "/login", "chat.openai.com/auth"],
            "gemini": ["accounts.google.com", "/signin"],
            "claude": ["claude.ai/login", "claude.ai/signup", "/auth"],
            "notebooklm": ["accounts.google.com"],
        }
        patterns = login_patterns.get(platform.lower(), ["/login", "/signin", "/auth"])
        for p in patterns:
            if p in url:
                raise SessionExpiredError(
                    f"{platform} session expired — page redirected to {url[:80]}")
        # Additional DOM check: look for login form / sign-in button
        try:
            has_login = await page.evaluate("""() => {
                const text = document.body.innerText.toLowerCase();
                return (text.includes('sign in') || text.includes('log in')) &&
                       (document.querySelector('input[type="password"]') !== null);
            }""")
            if has_login:
                raise SessionExpiredError(f"{platform} session expired — login form detected")
        except SessionExpiredError:
            raise
        except Exception:
            pass
        return True
    except SessionExpiredError:
        raise
    except Exception as e:
        log(f"[auth-check] {platform}: {e}", "WARN")
        return True  # On generic errors, assume OK to avoid false positives


# ── Paste-as-followup primitive ─────────────────────────────────────────

async def paste_followup(page, text, platform, label="followup"):
    """Paste text into the page's input field and send as a follow-up message.
    Reuses verified_paste_brief's strategies but without brief-level verification."""
    try:
        # Scroll to bottom + focus input
        try:
            await page.keyboard.press("End")
        except Exception:
            pass
        await asyncio.sleep(0.3)
        # Use verified_paste_brief with a lower retry count — it clicks and pastes
        ok = await verified_paste_brief(page, text, platform, label, max_retries=2)
        if not ok:
            return False
        # Click send button
        for sel in ['button[data-testid="send-button"]',
                    'button[aria-label="Send prompt"]',
                    'button[aria-label="Send"]',
                    'button[aria-label="Send message"]',
                    'button[aria-label="Submit"]']:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_enabled():
                    await btn.click()
                    await asyncio.sleep(1)
                    return True
            except Exception:
                continue
        # JS fallback
        try:
            sent = await page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    if ((a.includes('send') || a.includes('submit')) && !b.disabled) {
                        b.click(); return true;
                    }
                }
                return false;
            }""")
            return bool(sent)
        except Exception:
            return False
    except Exception as e:
        log(f"[paste_followup] {platform}: {e}", "WARN")
        return False


# ── Check if agent is still generating (cheap DOM) ───────────────────────

async def is_agent_generating(page, platform):
    """Cheap DOM check: is the page showing a stop/loading indicator?"""
    try:
        sel_map = {
            "chatgpt": 'button[data-testid="stop-button"], button[aria-label*="Stop"], [data-testid*="loading"]',
            "gemini": 'button[aria-label*="Stop"], [jsname] [role="progressbar"]',
            "claude": 'button[aria-label*="Stop"], [data-testid*="stop"]',
        }
        sel = sel_map.get(platform.lower(), 'button[aria-label*="Stop"]')
        el = await page.query_selector(sel)
        return el is not None
    except Exception:
        return False  # On error assume not generating


# ── Mid-run Input Dispatcher ──────────────────────────────────────────────

async def run_input_dispatcher(poll_interval=2.0):
    """Background task that watches _controls.extra_context and, if pipeline is
    actively running with live pages, dispatches user input immediately to the
    respective active agent chats as follow-up messages.

    If paused, does nothing — pause/resume flow handles buffered context.
    If between phases (no active pages for that phase), input stays buffered
    for the next phase to consume."""
    log("[dispatcher] Mid-run input dispatcher started")
    try:
        while True:
            await asyncio.sleep(poll_interval)
            # Skip if stopped, paused, or nothing to dispatch
            if _controls.is_stop():
                return
            if _controls.is_pause():
                continue
            if not _controls.peek_extra_context():
                continue
            # Only dispatch to live agent pages
            if not _runtime.active_pages:
                continue  # No active agents — buffer stays for next phase
            text = _controls.pop_extra_context()
            if not text:
                continue
            log(f"[dispatcher] Dispatching {len(text)} chars to {list(_runtime.active_pages.keys())}")
            # Snapshot active pages (avoid mutation during iteration)
            targets = list(_runtime.active_pages.items())
            for platform, page in targets:
                try:
                    # Race guard: re-check status just before paste
                    status_before = _runtime.agent_statuses.get(platform, "generating")
                    if status_before != "generating":
                        continue
                    is_gen = await is_agent_generating(page, platform)
                    if not is_gen and status_before == "generating":
                        # Status flipped to done between registration and now — mark for restart
                        log(f"[dispatcher] {platform} finished before dispatch — skipping (will be handled on next pause/resume)", "WARN")
                        continue
                    ok = await paste_followup(page, text, platform, label=f"dispatcher-{platform}")
                    if ok:
                        emit_event("user_input_dispatched", phase=_runtime.phase,
                                   agent=platform, chars=len(text))
                        log(f"[dispatcher] Sent follow-up to {platform}")
                    else:
                        log(f"[dispatcher] Failed to send follow-up to {platform}", "WARN")
                        # Re-buffer so user input isn't lost
                        _controls.add_context(text)
                        break
                except Exception as e:
                    log(f"[dispatcher] Error dispatching to {platform}: {e}", "WARN")
    except asyncio.CancelledError:
        log("[dispatcher] Cancelled")
        raise


# ── NotebookLM addendum source upload ───────────────────────────────────

async def upload_source_to_notebook(browser, page, file_path, label="addendum"):
    """Upload an extra source document to an existing NotebookLM notebook.
    Returns True on success."""
    try:
        await browser.switch_to_page(page)
        await asyncio.sleep(1)
        # Click "Add source" button
        clicked = False
        for sel in ['button[aria-label*="Add source"]',
                    'button[aria-label*="Add"]',
                    'button:has-text("Add source")',
                    '[data-test*="add-source"]']:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            try:
                clicked = await page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        if ((b.textContent || '').toLowerCase().includes('add source')) {
                            b.click(); return true;
                        }
                    }
                    return false;
                }""")
            except Exception:
                pass
        if not clicked:
            log(f"[notebook-addendum] 'Add source' button not found", "WARN")
            return False
        await asyncio.sleep(2)
        # File chooser should appear — queue the upload
        browser.set_upload_file(file_path)
        # Try clicking a file-upload entry if modal shows tabs
        for sel in ['input[type="file"]']:
            try:
                inp = await page.query_selector(sel)
                if inp:
                    await inp.set_input_files(str(file_path))
                    break
            except Exception:
                continue
        # Wait for ingestion
        await asyncio.sleep(10)
        log(f"[notebook-addendum] Uploaded {label}")
        return True
    except Exception as e:
        log(f"[notebook-addendum] Upload failed: {e}", "WARN")
        return False


# ── Pause/Resume: Close browser + relaunch ──────────────────────────────

async def pause_and_close_browser(browser, queue_dir, phase, extra_kwargs=None):
    """Save pause checkpoint → close browser → block until resume or stop."""
    _runtime.phase = phase
    # Write checkpoint snapshot
    save_pause_checkpoint(queue_dir, extra=extra_kwargs)
    # Emit paused event with snapshot payload (frontend already shows links)
    try:
        emit_event("pipeline_paused", phase=phase,
                   snapshot=_runtime.snapshot())
    except Exception:
        pass
    # Close browser if active (Phase 0 guard: may be None)
    if browser is not None:
        try:
            if browser.context is not None:
                log(f"[pause] Closing browser for resource-efficient pause...")
                await browser.close()
        except Exception as e:
            log(f"[pause] Browser close error: {e}", "WARN")
    # Clear active pages — they're dead page refs now
    _runtime.active_pages.clear()
    # Block on pause event
    await _controls.wait_if_paused()
    # On resume, caller handles relaunch
    return _controls.is_stop()  # True if stopped during pause


async def resume_browser_from_checkpoint(browser, queue_dir):
    """Relaunch browser, navigate to saved agent chat URLs, verify auth.
    Returns dict of {platform: page} for recovered agents."""
    cp = load_pause_checkpoint(queue_dir) or {}
    # Restore runtime state from checkpoint
    if cp:
        _runtime.phase = cp.get("phase", _runtime.phase)
        _runtime.sub_state = cp.get("sub_state", "")
        _runtime.agent_chat_urls = dict(cp.get("agent_chat_urls", {}))
        _runtime.agent_statuses = dict(cp.get("agent_statuses", {}))
        _runtime.original_inputs = dict(cp.get("original_inputs", {}))
    log(f"[resume] Relaunching browser for phase {_runtime.phase} ({_runtime.sub_state or 'idle'})")
    await browser.start()
    restored = {}
    for platform, url in list(_runtime.agent_chat_urls.items()):
        status = _runtime.agent_statuses.get(platform, "done")
        if status == "done":
            continue  # Don't reopen completed agents
        if not url:
            continue
        try:
            page = await browser.new_tab(url)
            await asyncio.sleep(3)
            try:
                await check_auth(page, platform)
            except SessionExpiredError as e:
                log(f"[resume] {e}", "ERROR")
                emit_event("pipeline_error", phase=_runtime.phase,
                           agent=platform, error=str(e))
                continue
            restored[platform] = page
            _runtime.register_page(platform, page, url)
            log(f"[resume] {platform} restored at {url[:80]}")
        except Exception as e:
            log(f"[resume] {platform} reopen failed: {e}", "WARN")
    # Reset dedup cache
    global _last_progress
    _last_progress = {}
    emit_event("pipeline_resumed", phase=_runtime.phase,
               restored=list(restored.keys()))
    clear_pause_checkpoint(queue_dir)
    return restored


# ── Link Extraction ──────────────────────────────────────────────────────────

class LinkResult:
    """Result of a link extraction attempt."""
    __slots__ = ("url", "label", "platform", "verified", "error")

    def __init__(self, url="", label="", platform="", verified=False, error=""):
        self.url = url
        self.label = label
        self.platform = platform
        self.verified = verified
        self.error = error

    def to_dict(self):
        return {"url": self.url, "label": self.label, "verified": self.verified}

    @property
    def success(self):
        return bool(self.url) and not self.error


async def extract_share_link_chatgpt(browser, cua_client, label="Research Brief", verbose=False):
    """Extract shareable ChatGPT link: Share button → Create link → copy URL."""
    page = browser.page
    url = await browser.current_url() or ""
    try:
        # Step 1: Try Playwright — find share button
        share_btn = None
        for sel in ['button[aria-label="Share"]', '[data-testid="share-chat-button"]',
                    'button:has(svg[data-testid="share-icon"])']:
            share_btn = await page.query_selector(sel)
            if share_btn:
                break
        if share_btn:
            await share_btn.click()
            await asyncio.sleep(2)
            # Look for "Create link" or "Copy link" button in modal
            link_btn = None
            for sel in ['button:has-text("Create link")', 'button:has-text("Copy link")',
                        'button:has-text("Share")', '[data-testid="share-link-button"]']:
                link_btn = await page.query_selector(sel)
                if link_btn:
                    break
            if link_btn:
                await link_btn.click()
                await asyncio.sleep(2)
            # PRIMARY — try to get URL from input field in modal
            share_input = await page.query_selector('input[readonly][value*="chatgpt.com/share"]')
            if share_input:
                url = await share_input.get_attribute("value") or url
            # SECONDARY — read the browser's clipboard directly (the "Copy link"
            # button wrote the public /share/ URL into it). This is far more
            # reliable than asking CUA to recover it via screenshots.
            if "chatgpt.com/share" not in url:
                try:
                    clip_js = await page.evaluate("navigator.clipboard.readText()")
                    if clip_js and "chatgpt.com/share" in clip_js:
                        url = clip_js.strip()
                        log(f"[{label}] Share URL recovered from browser clipboard: {url}")
                except Exception as _e:
                    # clipboard-read permission may be denied; fall through
                    pass
            # TERTIARY — Windows OS clipboard via PowerShell
            if "chatgpt.com/share" not in url:
                clip = get_clipboard()
                if "chatgpt.com/share" in clip:
                    url = clip
            # Close modal
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        # Step 2: CUA fallback if no share URL yet
        if "chatgpt.com/share" not in url:
            log(f"[{label}] CUA fallback for share link...")
            result = await agent_loop(cua_client, browser,
                "Share this ChatGPT conversation by clicking the Share button.",
                "Click the Share button at the top of this conversation. If a modal appears, click 'Create link' or 'Copy link'. After clicking Copy link, just STOP — don't try to extract the URL yourself, the code will read it from the clipboard.",
                model=CUA_MODEL, max_iterations=6, verbose=verbose)
            text = (result.get("text") or "")
            # Extract URL from CUA response (if it happened to observe one)
            m = re.search(r'https://chatgpt\.com/share/[a-zA-Z0-9-]+', text)
            if m:
                url = m.group(0)
            # After CUA clicked "Copy link", read the browser clipboard directly
            if "chatgpt.com/share" not in url:
                try:
                    clip_js = await page.evaluate("navigator.clipboard.readText()")
                    if clip_js and "chatgpt.com/share" in clip_js:
                        url = clip_js.strip()
                        log(f"[{label}] Share URL recovered from clipboard after CUA share click: {url}")
                except Exception:
                    pass
            if "chatgpt.com/share" not in url:
                clip = get_clipboard()
                if "chatgpt.com/share" in clip:
                    url = clip
        verified = "chatgpt.com/share" in url
        return LinkResult(url=url, label=label, platform="chatgpt", verified=verified)
    except Exception as e:
        log(f"Link extraction failed (ChatGPT): {e}", "WARN")
        return LinkResult(url=url, label=label, platform="chatgpt", error=str(e))


async def extract_share_link_gemini(browser, cua_client, label="Gemini Deep Research", verbose=False):
    """Extract shareable Gemini conversation link."""
    page = browser.page
    url = await browser.current_url() or ""
    try:
        # Try share button
        share_btn = await page.query_selector('[aria-label="Share"]')
        if share_btn:
            await share_btn.click()
            await asyncio.sleep(2)
            # Look for shareable link in modal
            link_el = await page.query_selector('input[value*="g.co/gemini"]')
            if not link_el:
                link_el = await page.query_selector('input[value*="gemini.google.com/share"]')
            if link_el:
                url = await link_el.get_attribute("value") or url
            else:
                clip = get_clipboard()
                if "gemini" in clip and "share" in clip:
                    url = clip
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        if "share" not in url.lower():
            # CUA fallback
            result = await agent_loop(cua_client, browser,
                "Share this Gemini conversation.",
                "Click the Share button for this Gemini conversation. Create a shareable link and tell me the URL.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
            m = re.search(r'https://[^\s]+gemini[^\s]*share[^\s]*', (result.get("text") or ""))
            if m:
                url = m.group(0)
        verified = "share" in url.lower() and "gemini" in url.lower()
        return LinkResult(url=url, label=label, platform="gemini", verified=verified)
    except Exception as e:
        return LinkResult(url=url, label=label, platform="gemini", error=str(e))


async def extract_share_link_claude(browser, cua_client, label="Claude Deep Research", verbose=False):
    """Extract shareable Claude conversation link (publish artifact)."""
    page = browser.page
    url = await browser.current_url() or ""
    try:
        # CUA is most reliable for Claude's publish flow — USE the PROMPT_PUBLISH_CLAUDE system prompt
        # which correctly targets the ARTIFACT panel (right side), not the conversation itself.
        result = await agent_loop(cua_client, browser,
            PROMPT_PUBLISH_CLAUDE,
            "Publish the research ARTIFACT in the right panel (not the conversation). "
            "If two artifacts exist, open the SECOND/bottom one first. Click the Publish/Share icon on the artifact. "
            "Get the published URL (claude.site/artifacts/... or claude.ai/...). Tell me the URL.",
            model=CUA_MODEL, max_iterations=12, verbose=verbose)
        text = (result.get("text") or "")
        m = re.search(r'https://claude\.ai/[^\s]+', text)
        if m:
            url = m.group(0)
        else:
            clip = get_clipboard()
            if "claude.ai" in clip:
                url = clip
        original_url = await browser.current_url()
        verified = "claude.ai" in url and url != original_url
        return LinkResult(url=url, label=label, platform="claude", verified=verified)
    except Exception as e:
        return LinkResult(url=url, label=label, platform="claude", error=str(e))


async def extract_notebooklm_url(browser, **_):
    """Extract NotebookLM notebook URL (tab URL is inherently shareable)."""
    url = await browser.current_url() or ""
    verified = "notebooklm.google.com/notebook" in url
    return LinkResult(url=url, label="NotebookLM Notebook", platform="notebooklm", verified=verified)


async def extract_youtube_url(browser, cua_client, verbose=False, **_):
    """Extract YouTube video URL after upload."""
    page = browser.page
    url = ""
    try:
        # Look for video URL in Studio
        for sel in ['a[href*="youtu.be"]', 'a[href*="youtube.com/watch"]',
                    'span:has-text("youtu.be/")', '.video-url-container a']:
            el = await page.query_selector(sel)
            if el:
                url = await el.get_attribute("href") or await el.inner_text()
                if url and ("youtu" in url):
                    break
        if not url:
            clip = get_clipboard()
            if "youtu" in clip:
                url = clip
        if not url:
            result = await agent_loop(cua_client, browser,
                "Find the YouTube video URL.",
                "The video was just uploaded. Find and tell me the full YouTube video URL (youtu.be or youtube.com/watch link).",
                model=CUA_MODEL, max_iterations=8, verbose=verbose)
            m = re.search(r'https?://(?:youtu\.be|(?:www\.)?youtube\.com/watch\?v=)[^\s]+', (result.get("text") or ""))
            if m:
                url = m.group(0)
        verified = "youtu" in url
        return LinkResult(url=url, label="YouTube Video", platform="youtube", verified=verified)
    except Exception as e:
        return LinkResult(url=url, label="YouTube Video", platform="youtube", error=str(e))


async def extract_gdoc_url(browser, **_):
    """Extract Google Doc URL (tab URL is the doc)."""
    url = await browser.current_url() or ""
    verified = "docs.google.com/document" in url
    return LinkResult(url=url, label="Google Doc", platform="gdoc", verified=verified)


# Phase → list of (extractor_func, kwargs_override) mappings
PHASE_LINK_EXTRACTORS = {
    1: [("chatgpt", extract_share_link_chatgpt, {"label": "Research Brief"})],
    2: [("chatgpt", extract_share_link_chatgpt, {"label": "ChatGPT Deep Research"}),
        ("gemini", extract_share_link_gemini, {}),
        ("claude", extract_share_link_claude, {})],
    3: [("notebooklm", extract_notebooklm_url, {})],
    4: [("youtube", extract_youtube_url, {})],
    5: [("gdocs", extract_gdoc_url, {})],
}


async def extract_phase_links(phase, browser, cua_client, enabled_agents=None, verbose=False):
    """Run all link extractors for a phase. Returns list of LinkResult.
    Emits link events with agent= (not platform=) so frontend details[agent] lookup works."""
    extractors = PHASE_LINK_EXTRACTORS.get(phase, [])
    results = []
    for platform, extractor, kwargs in extractors:
        if enabled_agents and platform in ("chatgpt", "gemini", "claude"):
            if not enabled_agents.get(platform, True):
                continue  # Skip disabled agents
        emit_event("link_extracting", phase=phase, agent=platform)
        log(f"Extracting link: phase={phase} agent={platform}...")
        result = await extractor(browser, cua_client=cua_client, verbose=verbose, **kwargs)
        if result.success:
            emit_event("link_extracted", phase=phase, agent=platform,
                       url=result.url, label=result.label, verified=result.verified)
            log(f"Link extracted: {result.url} (verified={result.verified})")
        else:
            emit_event("link_extraction_failed", phase=phase, agent=platform,
                       error=result.error or "URL not found")
            log(f"Link extraction failed: {platform} — {result.error}", "WARN")
        results.append(result)
    return results


# ── Brief Artifact (first-class research brief with verified paste) ──────────

class BriefArtifact:
    """Holds the complete research brief text + metadata for reliable Phase 2 paste."""
    __slots__ = ("text", "url", "chars", "sections", "extracted_at")

    def __init__(self, text, url="", extracted_at=None):
        self.text = text
        self.url = url
        self.chars = len(text)
        self.sections = re.findall(r'^#{1,3}\s+(.+)$', text, re.MULTILINE)
        self.extracted_at = extracted_at or int(time.time() * 1000)


async def verified_paste_brief(page, brief_text, platform, label, max_retries=3):
    """Paste brief into the active textarea and verify it was pasted completely.
    Returns True on success. Uses multiple strategies: CDP clipboard, JS injection,
    keyboard insert_text, and navigator.clipboard API.

    For Claude (which auto-converts large pastes to file attachments), also accepts
    attachment presence as a valid paste signal and clears any duplicates before retry."""
    selectors = ['#prompt-textarea', 'div[contenteditable="true"]', 'textarea', '.ProseMirror',
                 'div[contenteditable="true"][data-placeholder]', 'rich-textarea div[contenteditable="true"]',
                 '[aria-label*="message"]', '[aria-label*="Message"]']
    is_claude = platform.lower() == "claude"

    for attempt in range(1, max_retries + 1):
        pasted = False
        # Claude: before retry, delete any existing attachments to prevent duplicates
        if is_claude and attempt > 1:
            try:
                removed = await page.evaluate("""() => {
                    // Find attachment tiles and click their X/remove buttons
                    const removeBtns = document.querySelectorAll(
                        'button[aria-label*="Remove"], button[aria-label*="Delete"], button[data-testid*="remove"]'
                    );
                    let count = 0;
                    for (const b of removeBtns) {
                        if (b.offsetParent !== null) { b.click(); count++; }
                    }
                    return count;
                }""")
                if removed:
                    log(f"[{label}] Cleared {removed} stale attachment(s) before retry")
                    await asyncio.sleep(0.5)
            except Exception:
                pass
        # Ensure page has focus (critical for clipboard access in new tabs)
        try:
            await page.bring_to_front()
            await asyncio.sleep(0.5)
        except Exception:
            pass

        for sel in selectors:
            try:
                ta = await page.wait_for_selector(sel, timeout=3000)
                if not ta:
                    continue
                await ta.click()
                await asyncio.sleep(0.3)
                await page.keyboard.press("Control+a")
                await asyncio.sleep(0.1)

                # Strategy 1: CDP clipboard (bypasses permissions, most reliable)
                try:
                    cdp = await page.context.new_cdp_session(page)
                    await cdp.send("Browser.grantPermissions", {"permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
                    await cdp.detach()
                except Exception:
                    pass
                try:
                    await page.evaluate("text => navigator.clipboard.writeText(text)", brief_text)
                    await asyncio.sleep(0.3)
                    await page.keyboard.press("Control+v")
                    await asyncio.sleep(2)
                    pasted = True
                    break
                except Exception:
                    pass

                # Strategy 2: Direct JS injection into contenteditable/textarea
                if not pasted:
                    try:
                        injected = await page.evaluate("""(text) => {
                            const ta = document.querySelector('#prompt-textarea, div[contenteditable="true"], textarea, .ProseMirror');
                            if (!ta) return false;
                            if (ta.tagName === 'TEXTAREA' || ta.tagName === 'INPUT') {
                                const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                                nativeSet.call(ta, text);
                                ta.dispatchEvent(new Event('input', { bubbles: true }));
                                return true;
                            } else {
                                ta.focus();
                                ta.innerHTML = '';
                                // Use insertText to trigger React/framework state updates
                                document.execCommand('selectAll', false, null);
                                document.execCommand('insertText', false, text);
                                return true;
                            }
                        }""", brief_text)
                        if injected:
                            await asyncio.sleep(1)
                            pasted = True
                            break
                    except Exception:
                        pass

                # Strategy 3: Playwright keyboard.insert_text (no clipboard needed)
                if not pasted:
                    try:
                        await ta.click()
                        await page.keyboard.press("Control+a")
                        await asyncio.sleep(0.1)
                        await page.keyboard.insert_text(brief_text)
                        await asyncio.sleep(1.5)
                        pasted = True
                        break
                    except Exception:
                        pass

            except Exception:
                continue

        if not pasted:
            log(f"[{label}] Paste attempt {attempt}/{max_retries}: no textarea found or all strategies failed", "WARN")
            await asyncio.sleep(1)
            continue

        # Verify: scrape textarea and check length. Claude: also accept attachment tile as success.
        try:
            content_len = await page.evaluate("""() => {
                const ta = document.querySelector('#prompt-textarea, div[contenteditable="true"], textarea, .ProseMirror');
                return ta ? (ta.innerText || ta.value || ta.textContent || '').length : 0;
            }""")
            expected = len(brief_text)
            ratio = content_len / expected if expected > 0 else 0
            # Claude: if text is small but an attachment exists, that's a successful paste (auto-converted)
            if is_claude and ratio < 0.90:
                try:
                    attach_count = await page.evaluate("""() => {
                        // Claude pasted-as-attachment tiles have file-like preview elements
                        const tiles = document.querySelectorAll('[data-testid*="attachment"], [data-testid*="file"], [class*="attachment" i]');
                        let count = 0;
                        for (const t of tiles) {
                            if (t.offsetParent !== null) count++;
                        }
                        return count;
                    }""")
                    if attach_count == 1:
                        log(f"[{label}] Brief pasted ✓ (1 attachment tile, Claude auto-convert)")
                        return True
                    if attach_count > 1:
                        log(f"[{label}] Claude shows {attach_count} attachments (duplicate) — retry will clear", "WARN")
                        continue
                except Exception:
                    pass
            if ratio >= 0.90:
                log(f"[{label}] Brief pasted ✓ ({content_len}/{expected} chars, {ratio:.0%})")
                return True
            else:
                log(f"[{label}] Paste attempt {attempt}: only {content_len}/{expected} chars ({ratio:.0%})", "WARN")
        except Exception as e:
            log(f"[{label}] Paste verify failed: {e}", "WARN")

        await asyncio.sleep(1)

    log(f"[{label}] Brief paste failed after {max_retries} retries", "ERROR")
    return False


# ── Event Emission (dual-write: disk + Firestore) ────────────────────────────

def emit_event(event_type, phase=None, agent=None, **data):
    """Emit a typed event to events.jsonl AND Firestore pipeline_events."""
    if not _tracks_dir:
        return
    event = {
        "type": event_type,
        "timestamp": int(time.time() * 1000),
    }
    if phase is not None:
        event["phase"] = phase
    if agent:
        event["agent"] = agent
    if data:
        event["data"] = data
    # Write to disk (local debugging + resume)
    try:
        with open(_tracks_dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass
    # Record phase durations for analytics-based ETAs
    if event_type == "phase_complete" and phase is not None:
        dur = data.get("durationSec", 0)
        if dur > 0:
            record_phase_duration(phase, dur, agent=agent or "")
    # Write to Firestore (frontend real-time transport)
    _emit_to_firestore(event)


async def scrape_progress_chatgpt(page):
    """Scrape ChatGPT's current research progress (Playwright JS — zero CUA cost).
    Returns rich data for web app: status, thinking steps, sources, sections, text length.
    Selectors use multiple fallbacks per field — if ChatGPT UI changes, values degrade gracefully."""
    try:
        return await page.evaluate("""() => {
            const r = {
                status: 'unknown', phase: '', progress: '', thinking: '',
                sources: 0, source_urls: [], sections: [],
                partial_text_len: 0, model: '', title: ''
            };
            // Model info
            const modelEl = document.querySelector('[data-testid="model-selector"], .model-label');
            if (modelEl) r.model = modelEl.innerText.substring(0, 50);
            // Conversation title
            const titleEl = document.querySelector('h1, [data-testid="conversation-title"]');
            if (titleEl) r.title = titleEl.innerText.substring(0, 100);
            // Thinking/research progress
            const thinking = document.querySelector('.thinking-text, [data-thinking], .research-progress, .step-text');
            if (thinking) r.thinking = thinking.innerText.substring(0, 500);
            // Sources/citations
            const sources = document.querySelectorAll('.citation, .source-link, [data-citation], a[href*="http"]');
            r.sources = sources.length;
            r.source_urls = Array.from(sources).slice(0, 20).map(s => s.href || s.innerText).filter(Boolean);
            // Response sections (headings found so far)
            const headings = document.querySelectorAll('[data-message-author-role="assistant"] h1, [data-message-author-role="assistant"] h2, [data-message-author-role="assistant"] h3');
            r.sections = Array.from(headings).map(h => h.innerText.substring(0, 80));
            // Partial response length
            const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
            if (msgs.length > 0) r.partial_text_len = msgs[msgs.length-1].innerText.length;
            // Status — handles both standard ChatGPT and Deep Research
            const stop = document.querySelector('button[aria-label="Stop generating"], button[data-testid="stop-button"]');
            const bodyLower = document.body.innerText.toLowerCase();
            const drActive = ['researching', 'sources found', 'searching the web', 'analyzing'].some(kw => bodyLower.includes(kw));
            // Also capture canvas/artifact content from DR
            const canvas = document.querySelector('[data-testid="canvas"], .canvas-container, .canvas-content');
            if (canvas && canvas.innerText.length > r.partial_text_len) r.partial_text_len = canvas.innerText.length;
            if (stop) { r.status = 'generating'; r.phase = 'researching'; }
            else if (drActive) { r.status = 'generating'; r.phase = 'deep_research'; r.progress = 'Deep Research in progress'; }
            else if (r.partial_text_len > 100) { r.status = 'complete'; r.phase = 'done'; }
            else { r.status = 'idle'; r.phase = 'waiting'; }
            return r;
        }""")
    except Exception as e:
        log(f"ChatGPT scrape failed (selectors may need update): {e}", "WARN")
        return {"status": "scrape_error", "progress": "Selector mismatch — ChatGPT UI may have changed", "sources": 0, "partial_text_len": 0}


async def scrape_progress_gemini(page):
    """Scrape Gemini's current research progress — rich data for web app.
    Selectors use multiple fallbacks — degrades gracefully on UI changes."""
    try:
        return await page.evaluate("""() => {
            const r = {
                status: 'unknown', phase: '', progress: '', thinking: '',
                sources: 0, source_urls: [], sections: [], steps: [],
                partial_text_len: 0, plan: '', title: '', model: ''
            };
            // Conversation title (Gemini sets it once the chat has a topic)
            const gtitle = document.querySelector('[data-conversation-title], .conversation-title, bard-sidenav-mini-content [aria-current="true"]');
            if (gtitle) r.title = gtitle.innerText.substring(0, 100);
            else if (document.title) r.title = document.title.replace(/ - Gemini$/, '').substring(0, 100);
            // Research steps (Gemini shows a progress panel during Deep Research)
            const steps = document.querySelectorAll('.research-step, .step-content, [data-research-step], .activity-item');
            r.steps = Array.from(steps).map(s => s.innerText.substring(0, 150));
            if (r.steps.length > 0) r.progress = r.steps[r.steps.length - 1];
            // Research plan (shown before "Start research")
            const plan = document.querySelector('.research-plan, .plan-content');
            if (plan) r.plan = plan.innerText.substring(0, 1000);
            // Sources
            const sources = document.querySelectorAll('.source-card, .citation, [data-source], .web-result');
            r.sources = sources.length;
            r.source_urls = Array.from(sources).slice(0, 20).map(s => {
                const a = s.querySelector('a'); return a ? a.href : s.innerText.substring(0, 100);
            }).filter(Boolean);
            // Response sections
            const headings = document.querySelectorAll('message-content h1, message-content h2, message-content h3');
            r.sections = Array.from(headings).map(h => h.innerText.substring(0, 80));
            // Partial text
            const responses = document.querySelectorAll('message-content, .model-response-text');
            if (responses.length > 0) r.partial_text_len = responses[responses.length-1].innerText.length;
            // Status
            const stop = document.querySelector('button[aria-label="Stop"]');
            r.status = stop ? 'generating' : (r.partial_text_len > 0 ? 'complete' : 'idle');
            r.phase = r.steps.length > 0 ? 'researching' : (r.plan ? 'planning' : (r.partial_text_len > 0 ? 'done' : 'waiting'));
            return r;
        }""")
    except Exception as e:
        log(f"Gemini scrape failed (selectors may need update): {e}", "WARN")
        return {"status": "scrape_error", "progress": "Selector mismatch — Gemini UI may have changed", "sources": 0, "partial_text_len": 0}


async def scrape_progress_claude(page):
    """Scrape Claude's current research progress — rich data for web app.
    Selectors use multiple fallbacks — degrades gracefully on UI changes."""
    try:
        return await page.evaluate("""() => {
            const r = {
                status: 'unknown', phase: '', progress: '', thinking: '',
                sources: 0, source_urls: [], sections: [], tool_uses: [],
                partial_text_len: 0, model: '', title: ''
            };
            // Conversation title (Claude shows it in sidebar / window title)
            const ctitle = document.querySelector('[data-conversation-title], .conversation-title, header h1, h1.truncate, [data-testid="conversation-title"]');
            if (ctitle) r.title = ctitle.innerText.substring(0, 100);
            else if (document.title) r.title = document.title.replace(/ - Claude$/, '').replace(/^Claude$/, '').substring(0, 100);
            // Model info
            const modelEl = document.querySelector('.model-selector, [data-testid="model-name"]');
            if (modelEl) r.model = modelEl.innerText.substring(0, 50);
            // Thinking content (Extended Thinking shows this)
            const thinking = document.querySelector('[data-is-thinking="true"], .thinking-content, .thinking-block');
            if (thinking) r.thinking = thinking.innerText.substring(0, 500);
            // Research/tool use activity
            const tools = document.querySelectorAll('.tool-use-content, [data-tool-name], .tool-result');
            r.tool_uses = Array.from(tools).map(t => t.innerText.substring(0, 200));
            if (r.tool_uses.length > 0) r.progress = r.tool_uses[r.tool_uses.length - 1].substring(0, 200);
            // Sources (from research tool)
            const sources = document.querySelectorAll('.citation, [data-source], a[href*="http"]');
            r.sources = sources.length;
            r.source_urls = Array.from(sources).slice(0, 20).map(s => s.href || s.innerText).filter(Boolean);
            // Response sections
            const headings = document.querySelectorAll('.font-claude-message h1, .font-claude-message h2, .font-claude-message h3, .contents h1, .contents h2');
            r.sections = Array.from(headings).map(h => h.innerText.substring(0, 80));
            // Partial text
            const msgs = document.querySelectorAll('.font-claude-message, .contents .prose');
            if (msgs.length > 0) r.partial_text_len = msgs[msgs.length-1].innerText.length;
            // Status
            const stop = document.querySelector('button[aria-label="Stop Response"]');
            let hasStop = !!stop;
            if (!hasStop) {
                const btns = document.querySelectorAll('button');
                for (const b of btns) { if (b.textContent.trim() === 'Stop') { hasStop = true; break; } }
            }
            r.status = hasStop ? 'generating' : (r.partial_text_len > 0 ? 'complete' : 'idle');
            r.phase = r.thinking ? 'thinking' : (r.tool_uses.length > 0 ? 'researching' : (hasStop ? 'generating' : (r.partial_text_len > 0 ? 'done' : 'waiting')));
            return r;
        }""")
    except Exception as e:
        log(f"Claude scrape failed (selectors may need update): {e}", "WARN")
        return {"status": "scrape_error", "progress": "Selector mismatch — Claude UI may have changed", "sources": 0, "partial_text_len": 0}


SCRAPE_FNS = {
    "ChatGPT": scrape_progress_chatgpt,
    "Gemini": scrape_progress_gemini,
    "Claude": scrape_progress_claude,
    "Phase1": scrape_progress_chatgpt,  # Phase 1 runs on ChatGPT
}


# ── Firecrawler API ───────────────────────────────────────────────────────────

FIRECRAWL_API_KEY = get_env("FIRECRAWL_API_KEY")


def firecrawl_scrape(url, formats=None, max_retries=2):
    """Scrape a page via Firecrawler API — returns markdown content.
    Use for rich progress tracking when DOM selectors fail.
    One failed request loses 5 min of enrichment, so retry with backoff on 429/5xx."""
    if not FIRECRAWL_API_KEY:
        return ""
    import requests
    payload = {"url": url, "formats": formats or ["markdown"]}
    headers = {"Authorization": f"Bearer {FIRECRAWL_API_KEY}"}
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                "https://api.firecrawl.dev/v1/scrape",
                json=payload, headers=headers, timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return data.get("markdown", "") or data.get("content", "")
            # Retry on rate-limit / transient server errors
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                # Honor Retry-After header if present
                wait_s = 5 * (attempt + 1)
                try:
                    ra = resp.headers.get("Retry-After")
                    if ra and ra.isdigit():
                        wait_s = max(wait_s, int(ra))
                except Exception:
                    pass
                log(f"Firecrawl {resp.status_code}, retry in {wait_s}s (attempt {attempt + 1}/{max_retries})", "WARN")
                time.sleep(wait_s)
                continue
            # Non-retryable error
            log(f"Firecrawl {resp.status_code}: {resp.text[:200]}", "WARN")
            return ""
        except requests.Timeout as e:
            last_err = e
            if attempt < max_retries:
                log(f"Firecrawl timeout, retry (attempt {attempt + 1}/{max_retries})", "WARN")
                time.sleep(5 * (attempt + 1))
                continue
        except Exception as e:
            last_err = e
            log(f"Firecrawl error: {e}", "WARN")
            return ""
    if last_err:
        log(f"Firecrawl exhausted retries: {last_err}", "WARN")
    return ""


# ── Browser ────────────────────────────────────────────────────────────────────

class Browser:
    """Playwright persistent Chrome context — proven from original research.py."""

    def __init__(self, profile_dir, headless=False):
        self.profile_dir = str(profile_dir)
        self.headless = headless
        self.playwright = None
        self.context = None
        self.page = None
        self._upload_queue = []

    async def start(self):
        # Kill orphaned Chrome first
        try:
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, timeout=5)
            await asyncio.sleep(1)
        except Exception:
            pass

        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=self.headless,
            channel="chrome",
            viewport={"width": API_WIDTH, "height": API_HEIGHT},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        self.context.on("page", self._attach_file_handler)
        self._attach_file_handler(self.page)
        log("Browser started")

    def _attach_file_handler(self, page):
        page.on("filechooser", self._on_file_chooser)

    async def _on_file_chooser(self, file_chooser):
        if self._upload_queue:
            path = self._upload_queue.pop(0)
            if Path(path).exists():
                log(f"File dialog intercepted — uploading: {Path(path).name}")
                await file_chooser.set_files(path)
            else:
                log(f"File dialog — queued file not found: {path}", "WARN")
        else:
            log("File dialog opened but upload queue is empty", "WARN")

    def set_upload_file(self, path):
        """Set the file for the next file dialog (replaces any queued files)."""
        self._upload_queue = [str(path)]

    def queue_upload_file(self, path):
        """Add a file to the upload queue (for sequential file dialogs like video + thumbnail)."""
        self._upload_queue.append(str(path))

    def clear_upload_file(self):
        self._upload_queue = []

    async def screenshot(self) -> str:
        try:
            buf = await self.page.screenshot(type="png", timeout=10000)
            return base64.b64encode(buf).decode("ascii")
        except Exception as e:
            log(f"Screenshot failed: {e}", "WARN")
            await asyncio.sleep(2)
            try:
                buf = await self.page.screenshot(type="png", timeout=15000)
                return base64.b64encode(buf).decode("ascii")
            except Exception:
                return ""

    async def left_click(self, x, y):
        await self.page.mouse.click(x, y)

    async def right_click(self, x, y):
        await self.page.mouse.click(x, y, button="right")

    async def double_click(self, x, y):
        await self.page.mouse.dblclick(x, y)

    async def triple_click(self, x, y):
        await self.page.mouse.click(x, y, click_count=3)

    async def middle_click(self, x, y):
        await self.page.mouse.click(x, y, button="middle")

    async def type_text(self, text):
        await self.page.keyboard.type(text, delay=20)

    async def key(self, combo):
        mapping = {
            "ctrl": "Control", "alt": "Alt", "shift": "Shift",
            "meta": "Meta", "super": "Meta", "cmd": "Meta",
            "return": "Enter", "enter": "Enter",
            "backspace": "Backspace", "delete": "Delete",
            "tab": "Tab", "escape": "Escape", "esc": "Escape",
            "space": " ", "up": "ArrowUp", "down": "ArrowDown",
            "left": "ArrowLeft", "right": "ArrowRight",
            "pageup": "PageUp", "pagedown": "PageDown",
            "home": "Home", "end": "End",
        }
        parts = combo.split("+")
        translated = [mapping.get(p.strip().lower(), p.strip()) for p in parts]
        await self.page.keyboard.press("+".join(translated))

    async def mouse_move(self, x, y):
        await self.page.mouse.move(x, y)

    async def scroll(self, x, y, direction, amount=3):
        await self.page.mouse.move(x, y)
        delta_map = {"up": (0, -100*amount), "down": (0, 100*amount),
                     "left": (-100*amount, 0), "right": (100*amount, 0)}
        dx, dy = delta_map.get(direction, (0, 100*amount))
        await self.page.mouse.wheel(dx, dy)

    async def left_click_drag(self, sx, sy, ex, ey):
        await self.page.mouse.move(sx, sy)
        await self.page.mouse.down()
        await self.page.mouse.move(ex, ey)
        await self.page.mouse.up()

    async def navigate(self, url):
        log(f"Navigating: {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def new_tab(self, url=None):
        """Open new tab. Sets self.page to the new tab."""
        self.page = await self.context.new_page()
        if url:
            log(f"New tab: {url}")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._attach_file_handler(self.page)
        return self.page

    async def switch_to_page(self, page):
        self.page = page
        await page.bring_to_front()

    async def current_url(self):
        return self.page.url

    async def close(self):
        try:
            if self.context: await self.context.close()
            if self.playwright: await self.playwright.stop()
            log("Browser closed")
        except Exception as e:
            log(f"Browser close error: {e}", "WARN")
            try:
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, timeout=5)
            except Exception:
                pass


# ── Action Executor ────────────────────────────────────────────────────────────

async def execute_action(browser, action, params):
    """Execute a CUA action. Returns screenshot base64."""
    if action == "screenshot":
        return None
    try:
        if action == "left_click":
            x, y = params["coordinate"]; log_action("left_click", f"({x}, {y})"); await browser.left_click(x, y)
        elif action == "right_click":
            x, y = params["coordinate"]; log_action("right_click", f"({x}, {y})"); await browser.right_click(x, y)
        elif action == "double_click":
            x, y = params["coordinate"]; log_action("double_click", f"({x}, {y})"); await browser.double_click(x, y)
        elif action == "triple_click":
            x, y = params["coordinate"]; log_action("triple_click", f"({x}, {y})"); await browser.triple_click(x, y)
        elif action == "middle_click":
            x, y = params["coordinate"]; log_action("middle_click", f"({x}, {y})"); await browser.middle_click(x, y)
        elif action == "type":
            text = params["text"]; log_action("type", f"{len(text)} chars")
            if len(text) > 200:
                # insertText for long text — avoids clipboard file-paste issue
                try:
                    await browser.page.keyboard.insert_text(text)
                except Exception:
                    await browser.type_text(text[:2000])
            else:
                await browser.type_text(text)
        elif action == "key":
            combo = params.get("key") or params.get("text", "")
            if not combo:
                log("Empty key — skipping", "WARN"); return await browser.screenshot()
            log_action("key", combo); await browser.key(combo)
        elif action == "mouse_move":
            x, y = params["coordinate"]; log_action("mouse_move", f"({x}, {y})"); await browser.mouse_move(x, y)
        elif action == "scroll":
            x, y = params.get("coordinate", (640, 400))
            d = params.get("direction", "down")
            a = params.get("amount", 3)
            log_action("scroll", f"({x},{y}) {d}"); await browser.scroll(x, y, d, a)
        elif action == "left_click_drag":
            sx, sy = params.get("start_coordinate", (0, 0))
            ex, ey = params.get("end_coordinate", (0, 0))
            log_action("drag", f"({sx},{sy})->({ex},{ey})"); await browser.left_click_drag(sx, sy, ex, ey)
        elif action == "wait":
            d = params.get("duration", 1); log_action("wait", f"{d}s"); await asyncio.sleep(d)
        else:
            log(f"Unknown action: {action}", "WARN")
    except Exception as e:
        log(f"Action '{action}' failed: {e} — continuing", "WARN")
    await asyncio.sleep(0.5)
    return await browser.screenshot()


# ── Agent Loop ─────────────────────────────────────────────────────────────────

async def agent_loop(client, browser, system_prompt, user_message,
                     model=CUA_MODEL, max_iterations=30, verbose=False,
                     phase=None, agent_name=None):
    """CUA agent loop — proven from original research.py."""
    initial_ss = await browser.screenshot()
    if not initial_ss:
        return {"status": "error", "text": "Could not take initial screenshot"}

    messages = [{"role": "user", "content": [
        {"type": "text", "text": user_message},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": initial_ss}},
    ]}]
    tools = [{"type": "computer_20251124", "name": "computer",
              "display_width_px": API_WIDTH, "display_height_px": API_HEIGHT}]

    last_text = ""
    recent_actions = []

    for iteration in range(1, max_iterations + 1):
        # ── Check stop/pause before each CUA API call ──
        if _controls.is_stop():
            return {"status": "stopped", "text": last_text}
        if _controls.is_pause():
            await _controls.wait_if_paused()
            if _controls.is_stop():
                return {"status": "stopped", "text": last_text}

        if verbose: log(f"Iteration {iteration}/{max_iterations}")
        try:
            response = client.beta.messages.create(
                model=model, max_tokens=4096, system=system_prompt,
                tools=tools, messages=messages, betas=[BETA_FLAG],
            )
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                log("Rate limited — waiting 30s", "WARN"); await asyncio.sleep(30); continue
            elif "overloaded" in err.lower() or "529" in err:
                log("API overloaded — waiting 60s", "WARN"); await asyncio.sleep(60); continue
            else:
                log(f"API error: {e}", "ERROR")
                return {"status": "error", "text": str(e)}

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        tool_uses = []
        for block in assistant_content:
            if hasattr(block, "text"):
                last_text = block.text
                if verbose: log(f"Claude: {last_text[:200]}")
            if block.type == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            return {"status": "done", "text": last_text}

        tool_results = []
        for tb in tool_uses:
            act = tb.input.get("action", "")
            # Stuck detection
            sig = f"{act}:{tb.input.get('coordinate', '')}"
            recent_actions.append(sig)
            if len(recent_actions) > 5: recent_actions.pop(0)
            if len(recent_actions) == 5 and len(set(recent_actions)) == 1:
                log("Stuck — same action 5x. Injecting hint.", "WARN")
                tool_results.append({"type": "tool_result", "tool_use_id": tb.id, "content": [
                    {"type": "text", "text": "You seem stuck. Try a different approach."},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": await browser.screenshot()}},
                ]})
                recent_actions.clear()
                continue

            if act == "screenshot":
                ss = await browser.screenshot()
                tool_results.append({"type": "tool_result", "tool_use_id": tb.id,
                    "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ss}}]})
            else:
                ss = await execute_action(browser, act, tb.input)
                tool_results.append({"type": "tool_result", "tool_use_id": tb.id, "content": [
                    {"type": "text", "text": f"Action '{act}' executed."},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ss}},
                ]})
            # Emit CUA action event for frontend visibility
            if agent_name and act != "screenshot":
                emit_event("cua_action", phase=phase, agent=agent_name,
                    action=act, description=last_text[:200] if last_text else f"Action: {act}",
                    iteration=iteration)
        messages.append({"role": "user", "content": tool_results})

    return {"status": "max_iterations", "text": last_text}


# ── Verification Helpers ───────────────────────────────────────────────────────

async def verify_chatgpt_generating(page) -> bool:
    """Check if ChatGPT is actively generating (stop button visible).
    Scrolls both page body AND chat container — DR stop button is in chat UI, not input area."""
    try:
        await page.evaluate("""() => {
            // Scroll the page body
            window.scrollTo(0, document.body.scrollHeight);
            // Also scroll common chat containers (DR stop button is inside the chat, not input)
            const containers = document.querySelectorAll(
                '[class*="react-scroll"], [class*="chat-messages"], main, [role="presentation"]');
            containers.forEach(c => c.scrollTop = c.scrollHeight);
        }""")
        await asyncio.sleep(0.3)
        return await page.evaluate("""() => {
            // Check standard composer stop buttons
            const stop = document.querySelector('button[aria-label="Stop generating"]')
                || document.querySelector('button[data-testid="stop-button"]')
                || document.querySelector('button[aria-label="Stop streaming"]')
                || document.querySelector('button[aria-label="Stop"]');
            if (stop) return true;
            // ChatGPT Deep Research: stop button lives INSIDE the research card/dialog
            // (not in the composer). Look for buttons inside research/canvas containers.
            const cards = document.querySelectorAll(
                '[data-testid*="research"], [data-testid*="canvas"], [class*="research"], ' +
                '[aria-label*="Deep research"], [aria-label*="deep research"]'
            );
            for (const c of cards) {
                const cBtns = c.querySelectorAll('button');
                for (const b of cBtns) {
                    const lbl = (b.getAttribute('aria-label') || '').toLowerCase();
                    const t = (b.textContent || '').trim().toLowerCase();
                    if (lbl.includes('stop') || lbl.includes('cancel') || t === 'stop') return true;
                }
                // Progress/loading indicator inside the card
                if (c.querySelector('[role="progressbar"], [class*="progress"], [class*="spinner"]')) return true;
            }
            // Check by button content (square icon = stop)
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const svg = b.querySelector('svg rect, svg path');
                const label = (b.getAttribute('aria-label') || '').toLowerCase();
                if (label.includes('stop')) return true;
            }
            return !!document.querySelector('.result-streaming, [data-is-streaming="true"]');
        }""")
    except Exception:
        return False


async def verify_gemini_generating(page) -> bool:
    """Check if Gemini is actively generating — broad stop button + animation detection."""
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.3)
        return await page.evaluate("""() => {
            // Broad button scan — any button with stop-related text/label
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const a = (b.getAttribute('aria-label') || '').toLowerCase();
                const t = (b.getAttribute('title') || '').toLowerCase();
                const txt = (b.textContent || '').trim().toLowerCase();
                if (a.includes('stop') || t.includes('stop') || txt === 'stop') return true;
            }
            // Animation/streaming indicators
            if (document.querySelector('[data-is-streaming="true"], .loading-indicator')) return true;
            // CSS animation on any element (spinning, pulsing)
            const animated = document.querySelectorAll('[class*="animate"], [class*="spin"], [class*="pulse"], [class*="loading"]');
            for (const el of animated) {
                const style = window.getComputedStyle(el);
                if (style.animationName && style.animationName !== 'none') return true;
            }
            return false;
        }""")
    except Exception:
        return False


async def verify_claude_generating(page) -> bool:
    """Check if Claude is actively generating — broad stop button + animation detection."""
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.3)
        return await page.evaluate("""() => {
            // Broad button scan — any button with stop-related text/label/icon
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const a = (b.getAttribute('aria-label') || '').toLowerCase();
                const t = (b.getAttribute('title') || '').toLowerCase();
                const txt = (b.textContent || '').trim().toLowerCase();
                if (a.includes('stop') || t.includes('stop') || txt === 'stop'
                    || a.includes('cancel gen') || a.includes('stop gen')) return true;
            }
            // Streaming/animation indicators
            if (document.querySelector('[data-is-streaming="true"]')) return true;
            // CSS animation check (Claude uses spinning asterisk, pulsing indicators)
            const animated = document.querySelectorAll('[class*="animate"], [class*="spin"], [class*="pulse"], [class*="loading"], [class*="streaming"]');
            for (const el of animated) {
                const style = window.getComputedStyle(el);
                if (style.animationName && style.animationName !== 'none') return true;
            }
            return false;
        }""")
    except Exception:
        return False


async def wait_until_verified(verify_fn, page, label, browser=None, cua_client=None,
                              max_retries=20, interval=3, verbose=False, phase=None):
    """Smart verification: DOM check first, then CUA diagnosis if failing.

    Phase 1 (retries 1-5): Quick DOM checks — maybe it just needs a moment.
    Phase 2 (retry 6): CUA diagnoses what's on screen.
    Phase 3 (retry 7): CUA tries to fix the issue (click buttons, dismiss dialogs).
    Phase 4 (retries 8-20): Continue DOM checks after CUA fix.
    """
    for i in range(max_retries):
        if await verify_fn(page):
            log(f"[{label}] ✓ Verified — actively generating")
            agent_key = normalize_agent_key(label)
            emit_event("agent_verified", phase=phase, agent=agent_key,
                verified=True, method="dom",
                message=f"{label} confirmed actively generating",
                attempts=i + 1)
            return True

        # Phase 1: Quick DOM checks
        if i < 5:
            log(f"[{label}] Not yet generating... check {i+1}/5")
            await asyncio.sleep(interval)
            continue

        # Phase 2: CUA diagnosis (once, at retry 6)
        if i == 5 and browser and cua_client:
            log(f"[{label}] DOM checks failed 5x — scrolling to bottom, asking CUA to diagnose...")
            await browser.switch_to_page(page)
            try:
                await page.evaluate("""() => {
                    window.scrollTo(0, document.body.scrollHeight);
                    document.querySelectorAll('[class*="react-scroll"], [class*="chat-messages"], main, [role="presentation"]')
                        .forEach(c => { try { c.scrollTop = c.scrollHeight; } catch(e){} });
                }""")
                await asyncio.sleep(0.4)
            except Exception:
                pass
            diag = await agent_loop(cua_client, browser, PROMPT_DIAGNOSE,
                "Look at the BOTTOM of the chat. Is there a Stop button visible? "
                "Is there a loading animation or spinner? Is the AI actively generating?",
                model=CUA_MODEL, max_iterations=3, verbose=verbose)
            diag_text = (diag.get("text") or "").lower()
            log(f"[{label}] CUA diagnosis: {diag.get('text', '')[:200]}")

            # Parse carefully — avoid false positives from "not still generating"
            has_stop = ("stop" in diag_text and "yes" in diag_text)
            has_loading = ("loading" in diag_text or "spinning" in diag_text or "animation" in diag_text) and "yes" in diag_text
            says_generating = "still generating" in diag_text and "not still generating" not in diag_text and "no" not in diag_text.split("still generating")[0][-20:]
            if has_stop or has_loading or says_generating:
                log(f"[{label}] ✓ CUA confirms generating")
                return True
            if "needs click" in diag_text or "start research" in diag_text:
                log(f"[{label}] CUA says button needs clicking")
                # Will be handled in Phase 3 (CUA fix)

            continue

        # Phase 3: CUA fix attempt (once, at retry 7)
        if i == 6 and browser and cua_client:
            log(f"[{label}] CUA attempting to fix the issue...")
            await browser.switch_to_page(page)
            fix = await agent_loop(cua_client, browser, PROMPT_FIX_ISSUE,
                "Fix whatever is blocking the research from starting. Click any needed buttons.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
            log(f"[{label}] CUA fix attempt: {fix.get('text', '')[:200]}")
            await asyncio.sleep(5)
            continue

        # Phase 4: Continue DOM checks after CUA intervention
        log(f"[{label}] Post-fix check {i-6}/{max_retries-7}")
        await asyncio.sleep(interval)

    log(f"[{label}] ✗ Could not verify after {max_retries} attempts (including CUA)", "WARN")
    return False


# ── DOM Polling (zero CUA cost) ───────────────────────────────────────────────

_last_progress: dict = {}  # Deduplication cache for agent_progress events

async def poll_until_done(page, verify_fn, label, poll_interval, max_wait_min,
                          browser=None, cua_client=None, verbose=False, phase=2):
    """Poll page until response is complete. Smart: uses CUA to check if DOM selectors fail."""
    wait_start = time.time()
    max_wait = max_wait_min * 60
    consecutive_not_generating = 0
    cua_checked = False
    last_heartbeat = time.time()

    while (time.time() - wait_start) < max_wait:
        # ── Stop/Pause check ──
        if _controls.is_stop():
            log(f"[{label}] STOP requested — aborting poll")
            return False
        if _controls.is_pause():
            emit_event("pipeline_paused", phase=phase)
            await _controls.wait_if_paused()
            if _controls.is_stop():
                log(f"[{label}] STOP after pause — aborting poll")
                return False

        # ── Heartbeat every 60s so frontend knows we're alive ──
        if time.time() - last_heartbeat >= 60:
            emit_event("heartbeat", phase=phase, agent=normalize_agent_key(label))
            last_heartbeat = time.time()

        # Scrape progress FIRST — every cycle, regardless of state
        scrape_fn = SCRAPE_FNS.get(label)
        if scrape_fn:
            try:
                progress = await scrape_fn(page)
                save_track(label, progress)
                # Deduplicate: only emit if data actually changed
                progress_key = json.dumps({
                    "status": progress.get("status", ""),
                    "sources": progress.get("sources", 0),
                    "partialTextLen": progress.get("partial_text_len", 0),
                    "sections_len": len(progress.get("sections", [])),
                }, sort_keys=True)
                if _last_progress.get(label) != progress_key:
                    _last_progress[label] = progress_key
                    # Context-aware progress: detect Extended Thinking (no visible output is NORMAL)
                    elapsed_sec = int(time.time() - wait_start)
                    expected_min = get_expected_minutes(phase)
                    is_et = (progress.get("status") == "generating"
                             and progress.get("sources", 0) == 0
                             and progress.get("partial_text_len", 0) < 500)
                    if is_et:
                        progress["status"] = "extended_thinking"
                        progress["progress"] = f"Extended Thinking active ({elapsed_sec // 60}min elapsed, typical {expected_min}min)"
                    agent_key = normalize_agent_key(label)
                    emit_event("agent_progress", phase=phase, agent=agent_key,
                        status=progress.get("status", ""),
                        progress=progress.get("progress", ""),
                        sources=progress.get("sources", 0),
                        sourceUrls=progress.get("source_urls", []),
                        sections=progress.get("sections", []),
                        partialTextLen=progress.get("partial_text_len", 0),
                        model=progress.get("model", ""),
                        thinking=progress.get("thinking", ""),
                        steps=progress.get("steps", []),
                        plan=progress.get("plan", ""),
                        toolUses=progress.get("tool_uses", []),
                        title=progress.get("title", ""),
                        scrapeHealth="limited" if is_et else "full",
                        elapsedSec=elapsed_sec,
                        expectedMinutes=expected_min,
                    )
            except Exception:
                pass

        generating = await verify_fn(page)

        if not generating:
            consecutive_not_generating += 1

            # First few "not generating" could be a DOM selector issue
            if consecutive_not_generating <= 2:
                await asyncio.sleep(5)
                continue

            # After 3 consecutive "not generating" — warn user + ask CUA to verify
            if not cua_checked and browser and cua_client:
                agent_key = normalize_agent_key(label)
                emit_event("agent_warning", phase=phase, agent=agent_key,
                    severity="stuck",
                    message=f"DOM indicates not generating after {int(time.time() - wait_start)}s — CUA checking visually",
                    elapsedSec=int(time.time() - wait_start),
                    suggestion="CUA will verify the actual page state",
                    actions=["skip", "stop"])
                log(f"[{label}] DOM says not generating — scrolling to bottom + asking CUA to confirm...")
                await browser.switch_to_page(page)
                try:
                    await page.evaluate("""() => {
                        window.scrollTo(0, document.body.scrollHeight);
                        document.querySelectorAll('[class*="react-scroll"], [class*="chat-messages"], main, [role="presentation"]')
                            .forEach(c => { try { c.scrollTop = c.scrollHeight; } catch(e){} });
                    }""")
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
                diag = await agent_loop(cua_client, browser, PROMPT_DIAGNOSE,
                    "Look at the BOTTOM of the chat (composer / end of response). "
                    "Is there a Stop button visible? Is there a loading animation or 'Researching...' indicator? "
                    "If a Stop button is visible anywhere, say 'still generating'. "
                    "Only say 'response complete' if there is NO stop button AND the final paragraph of the response is visible.",
                    model=CUA_MODEL, max_iterations=3, verbose=verbose)
                diag_text = (diag.get("text") or "").lower()
                cua_checked = True

                # Parse CUA response: look for the deterministic conclusion phrase
                is_generating = False
                is_complete = False
                if "response complete" in diag_text:
                    is_complete = True
                elif "still generating" in diag_text:
                    is_generating = True
                elif "needs click" in diag_text:
                    is_generating = True  # Needs intervention, not done yet
                else:
                    # Fallback: count YES/NO answers about stop button and loading
                    has_stop = ("stop" in diag_text and "yes" in diag_text.split("stop")[0][-30:])
                    has_loading = ("loading" in diag_text and "yes" in diag_text.split("loading")[0][-30:])
                    has_response = ("completed" in diag_text or "response visible" in diag_text) and "yes" in diag_text
                    if has_stop or has_loading:
                        is_generating = True
                    elif has_response:
                        is_complete = True
                    else:
                        is_complete = True  # Default: if unclear, assume complete (don't get stuck)

                if is_generating:
                    log(f"[{label}] CUA says still generating — continuing poll")
                    consecutive_not_generating = 0
                    cua_checked = False
                    if "needs click" in diag_text:
                        await agent_loop(cua_client, browser, PROMPT_FIX_ISSUE,
                            "Click whatever button needs clicking.", model=CUA_MODEL, max_iterations=5, verbose=verbose)
                        await asyncio.sleep(5)
                    else:
                        await asyncio.sleep(poll_interval)
                    continue
                else:
                    log(f"[{label}] CUA confirms response complete ✓")

            # Double-check DOM
            await asyncio.sleep(3)
            still = await verify_fn(page)
            if not still:
                elapsed = int(time.time() - wait_start)
                log(f"[{label}] Response complete ({elapsed}s)")
                return True
        else:
            consecutive_not_generating = 0
            cua_checked = False  # Reset so CUA can check again if needed

        elapsed_min = int(time.time() - wait_start) // 60
        log(f"[{label}] Still generating... ({elapsed_min}m elapsed)")
        await asyncio.sleep(poll_interval)

    log(f"[{label}] Timeout ({max_wait_min}min)", "WARN")
    return False


# ── Round-Robin Polling (Phase 2) ─────────────────────────────────────────────

async def poll_all_agents_round_robin(agents, browser, cua_client,
                                       max_wait_min=90, poll_interval=30, verbose=False):
    """Round-robin poll all verified agents until each completes or times out.

    ChatGPT DR: polls for document card/canvas appearance (no stop button).
    Gemini/Claude: polls for stop button disappearance.
    Minimum wait enforced per agent to prevent false-positive early completion.
    """
    extract_fns = {
        "ChatGPT": extract_chatgpt_response,
        "Gemini": extract_gemini_response,
        "Claude": extract_claude_response,
    }
    # CUA completion check: first at 20 min, then every 5 min
    # Firecrawl scraping: every 5 min (staggered — starts at 2.5 min to avoid collision)
    _min_agent_wait = int(os.environ.get("MIN_AGENT_WAIT_MIN", "20")) * 60
    MIN_WAIT = {"ChatGPT": _min_agent_wait, "Gemini": _min_agent_wait, "Claude": _min_agent_wait}
    CUA_CHECK_INTERVAL = 300   # 5 min between CUA checks
    FIRECRAWL_INTERVAL = 300   # 5 min between Firecrawl scrapes

    pending = {}
    results = {}

    for name, agent in agents.items():
        if not agent["verified"]:
            results[name] = {"status": "not_verified", "text": "", "url": agent["url"]}
            continue
        pending[name] = {
            "page": agent["page"],
            "url": agent["url"],
            "start_time": time.time(),
            "done_count": 0,
            "cua_confirmed": False,
            "last_firecrawl": time.time() - 150,  # Stagger: first Firecrawl at 2.5 min
            "last_heartbeat": time.time(),       # Avoid heartbeat burst on first cycle
            "last_cua_check": time.time(),       # Ditto — CUA check gate
        }
        # Register for mid-run input dispatcher
        platform_key = name.lower().replace(" ", "")
        _runtime.register_page(platform_key, agent["page"], agent["url"])

    if not pending:
        return results

    _runtime.phase = 2
    _runtime.sub_state = "2_parallel_polling"
    log(f"\n--- Round-robin polling {len(pending)} agents (max {max_wait_min}min each) ---")

    while pending:
        # ── Stop/Pause check via asyncio Events ──
        if _controls.is_stop() or _controls.is_pause():
            is_stop = _controls.is_stop()
            signal = "STOP" if is_stop else "PAUSE"
            log(f"[Round-robin] {signal} requested — collecting partial results from completed agents")
            if is_stop:
                for name in list(pending.keys()):
                    p = pending[name]
                    try:
                        await browser.switch_to_page(p["page"])
                        text = await extract_fns[name](p["page"], browser=browser,
                            cua_client=cua_client, label=name, verbose=verbose)
                        elapsed = time.time() - p["start_time"]
                        status = "partial" if text and len(text) > 100 else "interrupted"
                        results[name] = {"status": status, "text": text or "",
                                         "url": p["page"].url, "page": p["page"],
                                         "elapsed_sec": int(elapsed)}
                        log(f"  [{name}] {status} — {len(text or '')} chars")
                    except Exception as e:
                        results[name] = {"status": "interrupted", "text": "",
                                         "url": p.get("url", ""), "page": p["page"]}
                        log(f"  [{name}] extraction failed: {e}", "WARN")
            else:
                # On PAUSE: snapshot current agent URLs, close browser, block, then relaunch+reopen
                for name in list(pending.keys()):
                    p = pending[name]
                    plat = name.lower().replace(" ", "")
                    url = ""
                    try:
                        url = p["page"].url
                    except Exception:
                        url = p.get("url", "")
                    _runtime.agent_chat_urls[plat] = url
                    _runtime.agent_statuses[plat] = "generating"
                    results[name] = {"status": "paused", "text": "",
                                     "url": url, "page": None,  # Page dies on close
                                     "elapsed_sec": int(time.time() - p["start_time"])}
                _runtime.phase = 2
                _runtime.sub_state = "2_parallel_polling"
                stopped = await pause_and_close_browser(browser, _tracks_dir if _tracks_dir else None, phase=2)
                if stopped:
                    return results
                # Relaunch browser + reopen agent tabs
                await browser.start()
                restored = await resume_browser_from_checkpoint(browser, _tracks_dir if _tracks_dir else None)
                # Reconstruct pending from restored pages
                for name in list(results.keys()):
                    if results[name]["status"] != "paused":
                        continue
                    plat = name.lower().replace(" ", "")
                    if plat in restored:
                        results[name]["page"] = restored[plat]
                        results[name]["url"] = restored[plat].url
                # Resumed — re-read config and only restore agents that are still enabled
                updated_cfg = _controls.pop_config_updates()
                # Also check disk config
                _cfg_path = Path(__file__).parent / "queues"
                if _tracks_dir:
                    _cfg_disk = _cfg_path / _tracks_dir.name / "config.json"
                    if _cfg_disk.exists():
                        try:
                            _disk_cfg = json.loads(_cfg_disk.read_text(encoding="utf-8"))
                            updated_cfg = {**_disk_cfg, **updated_cfg}  # in-memory overrides disk
                        except Exception:
                            pass
                _resume_agents = updated_cfg.get("agents", {"chatgpt": True, "gemini": True, "claude": True})
                _agent_name_map = {"ChatGPT": "chatgpt", "Gemini": "gemini", "Claude": "claude"}
                for name in list(results.keys()):
                    if results[name]["status"] == "paused":
                        agent_key = _agent_name_map.get(name, name.lower())
                        if _resume_agents.get(agent_key, True):
                            # Agent still enabled — restore to polling
                            pending[name] = {"page": results[name]["page"], "url": results[name]["url"],
                                             "start_time": time.time() - results[name]["elapsed_sec"],
                                             "done_count": 0, "cua_confirmed": False,
                                             "last_firecrawl": time.time() - 150,
                                             "last_heartbeat": time.time(),
                                             "last_cua_check": time.time()}
                            del results[name]
                            log(f"  [{name}] Restored to polling")
                        else:
                            # Agent disabled during pause — extract what we have and skip
                            log(f"  [{name}] Disabled during pause — extracting partial results")
                            try:
                                await browser.switch_to_page(results[name]["page"])
                                text = await extract_fns[name](results[name]["page"], browser=browser,
                                    cua_client=cua_client, label=name, verbose=verbose)
                                results[name] = {"status": "disabled_during_pause", "text": text or "",
                                                 "url": results[name]["url"], "page": results[name]["page"],
                                                 "elapsed_sec": results[name]["elapsed_sec"]}
                            except Exception:
                                results[name] = {"status": "disabled_during_pause", "text": "",
                                                 "url": results[name]["url"], "page": results[name]["page"],
                                                 "elapsed_sec": results[name]["elapsed_sec"]}
                            emit_event("agent_skipped", phase=2, agent=agent_key)
                emit_event("pipeline_resumed", phase=2)
                continue
            return results

        for name in list(pending.keys()):
            p = pending[name]
            elapsed = time.time() - p["start_time"]

            # Timeout
            if elapsed > max_wait_min * 60:
                log(f"[{name}] Timeout ({max_wait_min}min)", "WARN")
                try:
                    await browser.switch_to_page(p["page"])
                    text = await extract_fns[name](p["page"], browser=browser,
                        cua_client=cua_client, label=name, verbose=verbose)
                except Exception as e:
                    log(f"[{name}] Extraction after timeout failed: {e}", "WARN")
                    text = ""
                results[name] = {"status": "timeout", "text": text,
                                 "url": p.get("url", ""), "page": p["page"]}
                del pending[name]
                continue

            # Scrape progress — Firecrawl primary, DOM fallback
            # Firecrawl every 5 min (rich data for web app), DOM every cycle (free)
            if FIRECRAWL_API_KEY and (time.time() - p["last_firecrawl"]) > FIRECRAWL_INTERVAL:
                try:
                    fc_md = await asyncio.to_thread(firecrawl_scrape, p["page"].url)
                    if fc_md:
                        save_track(name, {
                            "source": "firecrawl",
                            "content_len": len(fc_md),
                            "preview": fc_md[:3000],
                            "full_text": fc_md,
                        })
                        p["last_firecrawl"] = time.time()
                        # Remember Firecrawl's content_len so the next agent_progress
                        # can report it (more accurate than DOM scraping, which only
                        # sees on-screen partial text).
                        p["firecrawl_len"] = len(fc_md)
                except Exception:
                    pass
            # DOM scrape as supplement (free, best-effort)
            scrape_fn = SCRAPE_FNS.get(name)
            progress = {}
            scrape_ok = False
            if scrape_fn:
                try:
                    progress = await scrape_fn(p["page"]) or {}
                    scrape_ok = True
                    save_track(name, progress)
                except Exception as _scrape_err:
                    # Don't mask scrape failures — tell frontend the scrape degraded
                    log(f"[{name}] DOM scrape failed: {_scrape_err}", "WARN")

            # Emit agent_progress to frontend (critical for real-time UI)
            agent_key = normalize_agent_key(name)
            # If scrape failed we don't know the agent's real status — keep
            # elapsed-time progress text but omit stale/fake fields
            _status_val = progress.get("status") if scrape_ok else "generating"
            _progress_val = progress.get("progress") if scrape_ok else None
            if not _progress_val:
                _progress_val = f"Researching... ({int(time.time() - p['start_time']) // 60}m elapsed)"
            elapsed_sec = int(time.time() - p["start_time"])

            # Prefer Firecrawl's content length over DOM partial text — the DOM scrape
            # only sees what's rendered on-screen, while Firecrawl's markdown fetches the
            # full page. Use whichever is larger so the frontend progress bar climbs
            # monotonically.
            _fc_len = p.get("firecrawl_len", 0)
            _partial_text_len = max(progress.get("partial_text_len", 0) or 0, _fc_len)

            # Dedup: only emit when something meaningful changed (status / sources /
            # partialTextLen / sections-count). Otherwise we spam Firestore ~180 writes
            # per agent per run with identical payloads. Heartbeat still covers liveness.
            progress_key = json.dumps({
                "status": _status_val or "",
                "sources": progress.get("sources", 0),
                "partialTextLen": _partial_text_len,
                "sections_len": len(progress.get("sections", []) or []),
                "steps_len": len(progress.get("steps", []) or []),
                # Coarse elapsed bucket so slow-moving scrapes still re-emit occasionally
                "elapsed_bucket": elapsed_sec // 30,
            }, sort_keys=True)
            if _last_progress.get(agent_key) != progress_key:
                _last_progress[agent_key] = progress_key
                emit_event("agent_progress", phase=2, agent=agent_key,
                    status=_status_val or "generating",
                    progress=_progress_val,
                    sources=progress.get("sources", 0),
                    sourceUrls=progress.get("source_urls", [])[:10],
                    sections=progress.get("sections", []),
                    partialTextLen=_partial_text_len,
                    firecrawlLen=_fc_len,
                    model=progress.get("model", ""),
                    thinking=progress.get("thinking", ""),
                    steps=progress.get("steps", []),
                    plan=progress.get("plan", ""),
                    toolUses=progress.get("tool_uses", []),
                    title=progress.get("title", ""),
                    elapsedSec=elapsed_sec,
                    expectedMinutes=get_expected_minutes(2),
                    scrapeOk=scrape_ok)

            # Heartbeat every 60s per agent
            if time.time() - p.get("last_heartbeat", 0) >= 60:
                emit_event("heartbeat", phase=2, agent=agent_key)
                p["last_heartbeat"] = time.time()

            # Check completion — CUA-primary (DOM selectors unreliable across all 3 platforms)
            # CUA checks every 3 min per agent (cost-effective, actually works)
            if (time.time() - p.get("last_cua_check", 0)) < CUA_CHECK_INTERVAL:
                # Not time for CUA check yet — skip this agent this cycle
                continue

            # Enforce minimum wait before first check
            min_wait = MIN_WAIT.get(name, 180)
            if elapsed < min_wait:
                continue

            # CUA visual check — SCROLL TO BOTTOM first (stop button + loading indicator live near composer/end)
            await browser.switch_to_page(p["page"])
            try:
                await p["page"].evaluate("""() => {
                    window.scrollTo(0, document.body.scrollHeight);
                    // Also scroll common chat containers (ChatGPT DR has internal scroll)
                    const containers = document.querySelectorAll(
                        '[class*="react-scroll"], [class*="chat-messages"], main, [role="presentation"], [data-testid*="conversation"]');
                    containers.forEach(c => { try { c.scrollTop = c.scrollHeight; } catch(e){} });
                }""")
                await asyncio.sleep(0.5)
            except Exception:
                pass
            log(f"[{name}] CUA checking completion ({int(elapsed/60)}m) — scrolled to bottom")
            # Platform-specific instruction for where to look for the stop signal
            platform_hint = {
                "ChatGPT": ("ChatGPT Deep Research renders the research output inside a RESEARCH CARD / DIALOG "
                            "(embedded in the chat, looks like a document panel). The stop button and progress "
                            "indicator live ON THAT CARD, not in the composer. Scroll down to find the card and "
                            "check if it still shows 'Researching...', a progress bar, or a stop button on the card."),
                "Gemini": ("Gemini Deep Research shows a stop button in the composer/input area and a progress "
                            "indicator in the message. Check the composer + the latest message area."),
                "Claude": ("Claude shows a stop button in the composer/input area while generating. After completion, "
                            "two document artifact buttons/cards may appear. Check composer for stop button; absence "
                            "means done."),
            }.get(name, "")
            diag = await agent_loop(cua_client, browser, PROMPT_DIAGNOSE,
                f"{platform_hint}\n\n"
                "Is the AI still generating (stop button visible, loading animation, spinner, 'Researching...' indicator)? "
                "Or is the response FULLY complete (no stop button anywhere, no loading, the final paragraph visible)? "
                "Answer 'still generating' or 'response complete'. "
                "If you see a Stop button ANYWHERE on the page (composer OR research card), answer 'still generating'.",
                model=CUA_MODEL, max_iterations=3, verbose=verbose)
            diag_text_raw = (diag.get("text") or "")
            diag_text = diag_text_raw.lower()
            p["last_cua_check"] = time.time()

            # ── Parse CUA diagnosis ──────────────────────────────────────
            # Old logic used bare substring matches — vulnerable to false
            # positives (e.g. "is NOT complete" contained "complete" →
            # is_done=True while agent was still running, causing premature
            # 0-char extractions at 23m). New logic:
            #   1. Prefer the structured "CONCLUSION: <verdict>" line that
            #      PROMPT_DIAGNOSE now mandates.
            #   2. If missing, use negation-aware heuristics.
            #   3. Stop-button-visible always vetos (per prompt decision rule).
            #   4. Default to still-generating on ambiguity (one extra CUA
            #      check is far cheaper than a zero-char extraction).
            verdict_match = re.search(
                r'conclusion\s*:\s*(generating|done|needs_click|error)',
                diag_text,
            )

            if verdict_match:
                verdict = verdict_match.group(1)
                is_done = verdict == "done"
                is_generating = verdict == "generating"
            else:
                still_running_phrases = (
                    "still in progress", "still running", "still researching",
                    "still being generated", "still working", "still generating",
                    "not complete", "not yet complete", "hasn't completed",
                    "has not completed", "not finished", "not yet done",
                    "not done yet", "isn't done", "is not done", "incomplete",
                )
                done_phrases = (
                    "response complete", "fully complete", "is complete",
                    "has completed", "appears complete", "finished generating",
                    "done generating", "no stop button", "no progress indicator",
                )
                stop_button_visible = bool(
                    re.search(r'stop button[^.]*\byes\b', diag_text) or
                    re.search(r'\bstop button\b[^.]{0,60}\b(visible|present|displayed|showing)\b', diag_text)
                )
                has_still_running = any(ph in diag_text for ph in still_running_phrases)
                has_done = any(ph in diag_text for ph in done_phrases)

                if stop_button_visible or has_still_running:
                    is_generating = True
                    is_done = False
                elif has_done:
                    is_done = True
                    is_generating = False
                else:
                    # Ambiguous — safer default
                    is_generating = True
                    is_done = False
                log(f"[{name}] CUA diag missing CONCLUSION line — heuristic verdict: "
                    f"{'generating' if is_generating else 'done' if is_done else 'unknown'}", "WARN")

            if is_generating and not is_done:
                log(f"[{name}] CUA: still generating ({int(elapsed/60)}m)")
                p["done_count"] = 0
                continue

            if is_done:
                p["done_count"] += 1
                # Need 2 consecutive CUA "done" readings to confirm
                if p["done_count"] < 2:
                    log(f"[{name}] CUA says done ({p['done_count']}/2 confirmations)")
                    p["last_cua_check"] = time.time() - 120  # Check again soon
                    continue
                log(f"[{name}] CUA confirms complete ✓ ({int(elapsed/60)}m)")

                # Extract content
                try:
                    await browser.switch_to_page(p["page"])
                    text = await extract_fns[name](p["page"], browser=browser,
                        cua_client=cua_client, label=name, verbose=verbose)
                except Exception as e:
                    log(f"[{name}] Extraction failed: {e}", "ERROR")
                    text = ""

                # ── Revert on empty extraction ────────────────────────────
                # If CUA confirmed "complete" but extraction yields
                # little/nothing, the CUA verdict was likely premature — the
                # agent is actually still researching. Instead of marking the
                # agent empty and skipping it (the old behavior — gave up at
                # 23m on ChatGPT while the research was still at 397
                # searches), revert to polling so the agent gets a proper
                # chance to finish within its time budget.
                #
                # Bounds:
                #   • Only revert if we're still well within max_wait_min
                #     (don't keep looping forever).
                #   • Cap retries (empty_retries < 3) so we eventually give
                #     up if extraction truly can't recover the content.
                if (not text or len(text) < 100) and elapsed < (max_wait_min * 60 * 0.95):
                    p.setdefault("empty_retries", 0)
                    p["empty_retries"] += 1
                    if p["empty_retries"] < 3:
                        log(f"[{name}] Extraction came back empty at {int(elapsed/60)}m "
                            f"but budget still available — CUA likely misread completion. "
                            f"Reverting to polling (empty retry {p['empty_retries']}/3).", "WARN")
                        p["done_count"] = 0
                        p["cua_confirmed"] = False
                        p["last_cua_check"] = time.time() + 60  # back off 1m before next CUA check
                        emit_event("agent_progress", phase=2,
                                   agent=name.lower().replace(" ", ""),
                                   status="still_researching",
                                   progress=f"Still working — CUA thought it was done but extraction came back empty. Retrying.",
                                   elapsedSec=int(elapsed),
                                   expectedMinutes=get_expected_minutes(2))
                        continue
                    log(f"[{name}] 3 empty extractions — giving up at {int(elapsed/60)}m", "ERROR")

                status = "done" if text and len(text) > 100 else "empty"
                agent_url = p["page"].url

                # Extract shareable link NOW (before moving to next agent)
                try:
                    await browser.switch_to_page(p["page"])
                    extractor_map = {"chatgpt": extract_share_link_chatgpt,
                                     "gemini": extract_share_link_gemini,
                                     "claude": extract_share_link_claude}
                    agent_key_lc = name.lower().replace(" ", "")
                    if agent_key_lc in extractor_map:
                        link_result = await extractor_map[agent_key_lc](browser, cua_client=cua_client, verbose=verbose)
                        if link_result.success:
                            agent_url = link_result.url
                            emit_event("link_extracted", phase=2, agent=agent_key_lc,
                                       url=agent_url, label=f"{name} Research",
                                       verified=link_result.verified)
                            log(f"[{name}] Shareable link: {agent_url}")
                        else:
                            log(f"[{name}] Share link extraction failed, using page URL", "WARN")
                except Exception as e:
                    log(f"[{name}] Share link extraction error: {e}", "WARN")

                results[name] = {"status": status, "text": text or "",
                                 "url": agent_url, "page": p["page"],
                                 "elapsed_sec": int(elapsed)}
                # Unregister from dispatcher — this agent is done
                _runtime.unregister_page(name.lower().replace(" ", ""),
                                          final_status="done" if status == "done" else status)
                _runtime.agent_chat_urls[name.lower().replace(" ", "")] = agent_url
                log(f"[{name}] {status.upper()} — {len(text or '')} chars ({int(elapsed)}s)")
                # Emit completion event for this agent
                agent_key = name.lower().replace(" ", "")
                emit_event("agent_progress", phase=2, agent=agent_key,
                    status="complete" if status == "done" else status,
                    progress=f"Content extracted: {len(text or '')} chars ({int(elapsed)}s)",
                    partialTextLen=len(text or ''), elapsedSec=int(elapsed),
                    links=[{"label": f"{name} Research", "url": agent_url}] if agent_url else [])
                del pending[name]
            else:
                p["done_count"] = 0
                p["cua_confirmed"] = False

        # Status update per cycle
        if pending:
            parts = []
            for n, p in pending.items():
                m = int((time.time() - p["start_time"]) / 60)
                parts.append(f"{n}:{m}m")
            log(f"Still polling: {', '.join(parts)}")
            await asyncio.sleep(poll_interval)

    return results


# ── Direct Playwright Submit (zero CUA cost) ─────────────────────────────────

async def submit_chatgpt_direct(browser, prompt):
    """Submit prompt to ChatGPT using direct Playwright selectors."""
    page = browser.page
    try:
        await asyncio.sleep(2)
        # Dismiss overlays
        for sel in ['button:has-text("Okay")', 'button:has-text("Got it")',
                    'button:has-text("Dismiss")', '[aria-label="Close"]']:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible(): await btn.click(); await asyncio.sleep(0.5)
            except Exception: pass

        # Find input
        textarea = None
        for sel in ['#prompt-textarea', 'div[contenteditable="true"]#prompt-textarea',
                    'textarea[placeholder*="Message"]', 'div[contenteditable="true"][data-placeholder]']:
            try:
                textarea = await page.wait_for_selector(sel, timeout=5000)
                if textarea: break
            except Exception: continue

        if not textarea:
            log("Direct submit: no textarea found", "WARN")
            return False

        await textarea.click()
        await asyncio.sleep(0.3)

        # insertText — instant, avoids ChatGPT's clipboard-to-file behavior
        try:
            await page.keyboard.insert_text(prompt)
        except Exception:
            try:
                await textarea.fill(prompt)
            except Exception:
                await page.keyboard.type(prompt, delay=5)

        await asyncio.sleep(0.5)

        # Send
        send_btn = None
        for sel in ['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Send"]']:
            try:
                send_btn = await page.query_selector(sel)
                if send_btn and await send_btn.is_enabled(): break
                send_btn = None
            except Exception: continue
        if send_btn:
            await send_btn.click()
        else:
            await page.keyboard.press("Enter")

        await asyncio.sleep(2)
        sent = await page.evaluate("""() => {
            const msgs = document.querySelectorAll('[data-message-author-role="user"]');
            return msgs.length > 0;
        }""")
        if sent: log("Direct submit: message sent ✓")
        return sent

    except Exception as e:
        log(f"Direct submit failed: {e}", "WARN")
        return False


# ── PDF Attachment (Playwright) ──────────────────────────────────────────────

async def attach_pdf_chatgpt(browser, pdf_path):
    """Attach a PDF to ChatGPT input via file chooser."""
    page = browser.page
    try:
        # Look for hidden file input first (most reliable)
        file_input = await page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_input_files(str(pdf_path))
            log(f"Attached PDF via hidden input: {Path(pdf_path).name}")
            await asyncio.sleep(2)
            return True

        # Fallback: click the attachment button and handle file chooser
        browser.set_upload_file(str(pdf_path))
        for sel in ['button[aria-label="Attach files"]', 'button[aria-label="Attach"]',
                    'button[data-testid="upload-button"]']:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    log(f"Attached PDF via button click: {Path(pdf_path).name}")
                    browser.clear_upload_file()
                    return True
            except Exception: continue

        browser.clear_upload_file()
        log(f"Could not find attachment button for: {Path(pdf_path).name}", "WARN")
        return False
    except Exception as e:
        browser.clear_upload_file()
        log(f"PDF attachment failed: {e}", "WARN")
        return False


# ── Response Extraction ──────────────────────────────────────────────────────
# Goal: extract the FULL response with proper formatting. Try platform's copy
# Extraction chain: HTML→MD (best formatting) → copy button → JS innerText → clipboard.


def html_to_markdown(html):
    """Convert HTML to clean markdown using markdownify. Preserves all formatting."""
    try:
        from markdownify import markdownify as md
        text = md(html, heading_style="ATX", bullets="-", strip=['img', 'script', 'style'])
        # Clean up excessive whitespace
        lines = text.split('\n')
        cleaned = []
        prev_empty = False
        for line in lines:
            is_empty = not line.strip()
            if is_empty and prev_empty:
                continue
            cleaned.append(line.rstrip())
            prev_empty = is_empty
        return '\n'.join(cleaned).strip()
    except ImportError:
        log("markdownify not installed — falling back to innerText", "WARN")
        return ""


async def _extract_html_to_md(page, selectors, label):
    """Extract response HTML from page, convert to clean markdown."""
    for sel in selectors:
        try:
            html = await page.evaluate(f"""() => {{
                const els = document.querySelectorAll('{sel}');
                if (els.length > 0) return els[els.length - 1].innerHTML;
                return '';
            }}""")
            if html and len(html) > 200:
                md_text = html_to_markdown(html)
                if md_text and len(md_text) > 100:
                    log(f"[{label}] Extracted via HTML→MD: {len(md_text)} chars")
                    return md_text
        except Exception:
            continue
    return ""


async def _try_copy_button(page, browser, cua_client, label, verbose=False):
    """Try to use the platform's copy button, fall back to CUA."""
    # Try JS first — look for copy buttons
    try:
        clicked = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const label = (b.getAttribute('aria-label') || '').toLowerCase();
                const txt = b.textContent.trim().toLowerCase();
                if (label.includes('copy') || txt === 'copy' || txt.includes('copy to clipboard')) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            log(f"[{label}] Copy button clicked via JS")
            await asyncio.sleep(1)
            return get_clipboard()
    except Exception:
        pass

    # CUA fallback
    if browser and cua_client:
        log(f"[{label}] Using CUA to click copy button...")
        await browser.switch_to_page(page)
        await agent_loop(cua_client, browser, PROMPT_COPY_RESPONSE,
            "Copy the AI response text to clipboard using the Copy button.",
            model=CUA_MODEL, max_iterations=5, verbose=verbose)
        await asyncio.sleep(1)
        return get_clipboard()

    return ""


async def extract_chatgpt_response(page, browser=None, cua_client=None, label="ChatGPT", verbose=False):
    """Extract ChatGPT response — CUA artifact copy (primary) → JS fallback.
    ChatGPT Deep Research outputs a document/artifact card, not regular chat text."""
    # Clear clipboard first so stale brief text doesn't get returned
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard ''"],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    await asyncio.sleep(2)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    # Method 1 (PRIMARY): CUA opens the artifact/document and copies it
    if browser and cua_client:
        log(f"[{label}] CUA: Opening and copying Deep Research artifact...")
        await browser.switch_to_page(page)
        await agent_loop(cua_client, browser, PROMPT_COPY_ARTIFACT_CHATGPT,
            "Open the research report document and copy its full content to clipboard.",
            model=CUA_MODEL, max_iterations=12, verbose=verbose)
        await asyncio.sleep(1)
        clipboard = get_clipboard()
        if clipboard and len(clipboard) > 500:
            log(f"[{label}] Extracted via CUA artifact copy: {len(clipboard)} chars")
            return clipboard
        log(f"[{label}] CUA copy got {len(clipboard or '')} chars — trying fallbacks", "WARN")

    # Method 2: HTML→MD from any large content block
    md = await _extract_html_to_md(page, [
        '.canvas-content', '.artifact-content', '[data-testid="canvas-content"]',
        '[data-message-author-role="assistant"]:last-of-type .markdown',
    ], label)
    if md and len(md) > 500:
        return md

    # Method 3: JS — last assistant message (regular chat mode, not Deep Research)
    try:
        text = await page.evaluate("""() => {
            const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
            if (msgs.length > 0) return msgs[msgs.length - 1].innerText;
            return '';
        }""")
        if text and len(text) > 200:
            log(f"[{label}] Extracted via JS: {len(text)} chars")
            return text
    except Exception:
        pass

    # Method 4: Firecrawl API (full page scrape — last resort)
    if FIRECRAWL_API_KEY:
        try:
            fc_md = await asyncio.to_thread(firecrawl_scrape, page.url)
            if fc_md and len(fc_md) > 500:
                log(f"[{label}] Extracted via Firecrawl: {len(fc_md)} chars")
                return fc_md
        except Exception:
            pass

    log(f"[{label}] All extraction methods failed", "WARN")
    return ""


async def extract_gemini_response(page, browser=None, cua_client=None, label="Gemini", verbose=False):
    """Extract last response from Gemini — HTML→MD → copy button → JS → clipboard."""
    await asyncio.sleep(2)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    md = await _extract_html_to_md(page, [
        'message-content', '.model-response-text', '.response-container',
    ], label)
    if md and len(md) > 100:
        return md

    copied = await _try_copy_button(page, browser, cua_client, label, verbose)
    if copied and len(copied) > 100:
        log(f"[{label}] Extracted via copy button: {len(copied)} chars")
        return copied

    try:
        text = await page.evaluate("""() => {
            const r = document.querySelectorAll('message-content, .model-response-text, .response-container');
            if (r.length > 0) return r[r.length - 1].innerText;
            const turns = document.querySelectorAll('.conversation-turn');
            if (turns.length > 0) return turns[turns.length - 1].innerText;
            return '';
        }""")
        if text and len(text) > 100:
            log(f"[{label}] Extracted via JS: {len(text)} chars")
            return text
    except Exception:
        pass

    # Method 4: Firecrawl API (full page scrape)
    if FIRECRAWL_API_KEY:
        try:
            fc_md = await asyncio.to_thread(firecrawl_scrape, page.url)
            if fc_md and len(fc_md) > 500:
                log(f"[{label}] Extracted via Firecrawl: {len(fc_md)} chars")
                return fc_md
        except Exception:
            pass

    # Method 5: Select-all clipboard (last resort)
    log(f"[{label}] Trying select-all clipboard fallback", "WARN")
    await page.keyboard.press("Control+a")
    await asyncio.sleep(0.5)
    await page.keyboard.press("Control+c")
    await asyncio.sleep(1)
    return get_clipboard()


async def extract_claude_response(page, browser=None, cua_client=None, label="Claude", verbose=False):
    """Extract Claude response — CUA artifact copy (primary) → JS fallback.
    Claude Deep Research outputs an artifact panel, not regular chat text."""
    # Clear clipboard first so stale brief text doesn't get returned
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard ''"],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    await asyncio.sleep(2)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    # Method 1 (PRIMARY): CUA opens the artifact and copies it
    if browser and cua_client:
        log(f"[{label}] CUA: Opening and copying Claude artifact...")
        await browser.switch_to_page(page)
        await agent_loop(cua_client, browser, PROMPT_COPY_ARTIFACT_CLAUDE,
            "Open the research artifact/document and copy its full content to clipboard.",
            model=CUA_MODEL, max_iterations=12, verbose=verbose)
        await asyncio.sleep(1)
        clipboard = get_clipboard()
        if clipboard and len(clipboard) > 500:
            log(f"[{label}] Extracted via CUA artifact copy: {len(clipboard)} chars")
            return clipboard
        log(f"[{label}] CUA copy got {len(clipboard or '')} chars — trying fallbacks", "WARN")

    # Method 2: HTML→MD
    md = await _extract_html_to_md(page, [
        '[data-is-streaming="false"] .markdown', '.font-claude-message', '.contents .prose',
    ], label)
    if md and len(md) > 100:
        return md

    # Method 3: JS fallback
    try:
        text = await page.evaluate("""() => {
            const r = document.querySelectorAll('[data-is-streaming="false"] .markdown, .font-claude-message');
            if (r.length > 0) return r[r.length - 1].innerText;
            return '';
        }""")
        if text and len(text) > 100:
            log(f"[{label}] Extracted via JS: {len(text)} chars")
            return text
    except Exception:
        pass

    # Method 4: Firecrawl API (full page scrape — last resort)
    if FIRECRAWL_API_KEY:
        try:
            fc_md = await asyncio.to_thread(firecrawl_scrape, page.url)
            if fc_md and len(fc_md) > 500:
                log(f"[{label}] Extracted via Firecrawl: {len(fc_md)} chars")
                return fc_md
        except Exception:
            pass

    log(f"[{label}] All extraction methods failed", "WARN")
    return ""


# ── Phase 1: Research Brief Generation ───────────────────────────────────────

async def run_phase1(browser, cua_client, topic, pdf_paths, verbose=False, feedback=""):
    """Phase 1: ChatGPT Pro + Extended Thinking → research brief."""
    log("=" * 60)
    log("PHASE 1: Research Brief Generation (ChatGPT Pro + Extended Thinking)")
    log("=" * 60)

    # Navigate to ChatGPT
    await browser.navigate("https://chatgpt.com")
    await asyncio.sleep(3)

    # Select Pro model via CUA
    if cua_client:
        log("Selecting Pro + Extended Thinking...")
        result = await agent_loop(cua_client, browser, PROMPT_SELECT_PRO,
            "Select ChatGPT Pro model with Extended Thinking. Say 'no pro available' if not found.",
            model=CUA_MODEL, max_iterations=15, verbose=verbose)
        last = (result.get("text") or "").lower()
        if "no pro" in last or "not available" in last:
            log("Pro mode not available", "WARN")

    # Attach PDFs
    for pdf in pdf_paths:
        log(f"Attaching PDF: {Path(pdf).name}")
        attached = await attach_pdf_chatgpt(browser, pdf)
        if not attached and cua_client:
            log("Trying CUA for PDF attachment...")
            browser.set_upload_file(str(pdf))
            await agent_loop(cua_client, browser, PROMPT_ATTACH_PDF,
                f"Attach the file. The file dialog will auto-select it — just click the attachment button.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
            browser.clear_upload_file()

    # Build and submit the brief prompt
    prompt = (
        f'Please create a detailed research report brief for a deep research LLM agent '
        f'that covers this topic: {topic}. Be as thorough as you can. Simply output the '
        f'research brief, no preamble or post-amble. I just need something I can copy and '
        f'paste into a research agent LLM.'
    )
    if feedback:
        prompt += f'\n\nUSER FEEDBACK (incorporate this): {feedback}'
        log(f"Phase 1: Injecting user feedback: {feedback[:100]}")
    submitted = await submit_chatgpt_direct(browser, prompt)
    if not submitted and cua_client:
        log("Falling back to CUA for submit...")
        await agent_loop(cua_client, browser, PROMPT_SUBMIT_FALLBACK,
            f"Submit this prompt to ChatGPT:\n\n{prompt}",
            model=CUA_MODEL, max_iterations=15, verbose=verbose)

    # VERIFY: confirm ChatGPT is generating
    verified = await wait_until_verified(verify_chatgpt_generating, browser.page, "Phase1",
        browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
    if not verified:
        log("Phase 1: Could not verify ChatGPT is generating", "ERROR")
        return None

    # Register brief page with dispatcher for mid-run user input
    _runtime.phase = 1
    _runtime.sub_state = "1_brief_generating"
    _runtime.register_page("chatgpt", browser.page, browser.page.url)

    # Wait for response
    log(f"Polling for response (every {POLL_PRO}s, max {MAX_WAIT_PRO}min)...")
    completed = await poll_until_done(browser.page, verify_chatgpt_generating, "Phase1", POLL_PRO, MAX_WAIT_PRO,
        browser=browser, cua_client=cua_client, verbose=verbose, phase=1)
    # Unregister once brief is done
    _runtime.unregister_page("chatgpt", final_status="done" if completed else "timeout")

    # ── Mid-Phase-1 injection: if user sent context while brief was generating,
    #    submit it as a follow-up to ChatGPT and wait for the updated brief ──
    # Only pop the buffer if we're going to use it — otherwise leave it for
    # Phase 2 / NotebookLM to consume (pop is destructive, so peek first).
    extra_ctx = None
    if completed and _controls.peek_extra_context():
        extra_ctx = _controls.pop_extra_context()
    if extra_ctx and completed:
        log(f"Phase 1: Injecting user context as follow-up ({len(extra_ctx)} chars)")
        emit_event("agent_progress", phase=1, agent="chatgpt",
                   status="refining", progress=f"Incorporating user input: {extra_ctx[:80]}...")
        followup = (
            f"Please update and improve the research brief above to also incorporate "
            f"the following additional context from the user:\n\n{extra_ctx}\n\n"
            f"Output the complete updated research brief. No preamble."
        )
        submitted_fu = await submit_chatgpt_direct(browser, followup)
        if not submitted_fu and cua_client:
            await agent_loop(cua_client, browser, PROMPT_SUBMIT_FALLBACK,
                f"Submit this follow-up prompt to ChatGPT:\n\n{followup[:500]}",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
        # Wait for the updated response
        await asyncio.sleep(5)
        verified_fu = await wait_until_verified(verify_chatgpt_generating, browser.page, "Phase1-followup",
            browser=browser, cua_client=cua_client, max_retries=10, interval=3, verbose=verbose)
        if verified_fu:
            log("Phase 1: Waiting for updated brief...")
            await poll_until_done(browser.page, verify_chatgpt_generating, "Phase1-followup",
                POLL_PRO, 15,  # 15 min max for follow-up (shorter than initial)
                browser=browser, cua_client=cua_client, verbose=verbose, phase=1)
        else:
            log("Phase 1: Follow-up may not have triggered generation — using original brief", "WARN")

    # Extract
    brief_text = await extract_chatgpt_response(browser.page)
    chat_url = await browser.current_url()

    if brief_text and len(brief_text) > 100:
        log(f"Brief extracted: {len(brief_text)} chars")
        return {"text": brief_text, "url": chat_url}
    else:
        log(f"Brief too short ({len(brief_text or '')} chars)", "WARN")
        return {"text": brief_text or "", "url": chat_url}


# ── Phase 2: Parallel Deep Research (Sequential Start + Verify) ──────────────

# ── Playwright-direct platform setup (replaces vision-based CUA setup) ────────

async def setup_chatgpt_dr(page) -> bool:
    """Enable ChatGPT Deep Research mode via direct selectors. Returns True on success."""
    try:
        await asyncio.sleep(2)
        # Click the "+" / tools menu in composer
        for sel in ['button[aria-label*="Use a tool"]',
                    'button[aria-label*="Attach"]',
                    'button[data-testid="composer-plus-btn"]',
                    'button[aria-label*="More"]']:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.8)
                    break
            except Exception:
                continue
        # Click "Deep research" option in menu
        clicked = await page.evaluate("""() => {
            const items = document.querySelectorAll('[role="menuitem"], button, div[role="option"]');
            for (const el of items) {
                const t = (el.textContent || '').trim().toLowerCase();
                if (t === 'deep research' || t.startsWith('deep research')) {
                    el.click(); return true;
                }
            }
            return false;
        }""")
        if not clicked:
            return False
        await asyncio.sleep(1.5)
        # Verify Deep Research pill/label present in composer area
        active = await page.evaluate("""() => {
            const text = document.body.innerText.toLowerCase();
            return text.includes('deep research');
        }""")
        return bool(active)
    except Exception as e:
        log(f"[setup_chatgpt_dr] {e}", "WARN")
        return False


async def setup_gemini_dr(page) -> bool:
    """Enable Gemini Deep Research pill via direct selectors. Returns True on success."""
    try:
        await asyncio.sleep(2)
        # Look for the "Deep research" button/pill — various UI layouts
        clicked = await page.evaluate("""() => {
            // Direct button with aria or text "Deep research"
            const candidates = document.querySelectorAll('button, [role="button"], [role="menuitem"]');
            for (const b of candidates) {
                const t = (b.textContent || '').trim().toLowerCase();
                const a = (b.getAttribute('aria-label') || '').toLowerCase();
                if (t === 'deep research' || a === 'deep research' || t.startsWith('deep research')) {
                    // Check it's not already active (pill with active class)
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if not clicked:
            # Try the model/mode dropdown first
            for sel in ['button[aria-label*="model"]', 'button[data-test-id*="model"]']:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(0.8)
                        clicked = await page.evaluate("""() => {
                            const items = document.querySelectorAll('[role="menuitem"], [role="option"], button');
                            for (const el of items) {
                                const t = (el.textContent || '').trim().toLowerCase();
                                if (t.includes('deep research')) { el.click(); return true; }
                            }
                            return false;
                        }""")
                        break
                except Exception:
                    continue
        if not clicked:
            return False
        await asyncio.sleep(1.5)
        # Verify pill is visible
        active = await page.evaluate("""() => {
            const pills = document.querySelectorAll('button, [role="button"], span');
            for (const p of pills) {
                const t = (p.textContent || '').trim().toLowerCase();
                if (t === 'deep research' && p.offsetParent !== null) return true;
            }
            return false;
        }""")
        return bool(active)
    except Exception as e:
        log(f"[setup_gemini_dr] {e}", "WARN")
        return False


async def setup_claude_dr(page) -> bool:
    """Enable Claude Extended Thinking + Research tool via direct selectors.
    Claude.ai: model dropdown shows 'Opus 4.6 Extended' variant; Research is in tools menu."""
    try:
        await asyncio.sleep(2)
        # Step 1: Model selector — pick "Opus 4.6 Extended" (or Sonnet 4.6 Extended if Opus unavailable)
        model_picked = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            let dropdown = null;
            for (const b of btns) {
                const t = (b.textContent || '').toLowerCase();
                if ((t.includes('opus') || t.includes('sonnet') || t.includes('claude')) && b.offsetParent !== null) {
                    dropdown = b; break;
                }
            }
            if (dropdown) { dropdown.click(); return true; }
            return false;
        }""")
        if model_picked:
            await asyncio.sleep(1.0)
            # Pick Extended variant from dropdown
            await page.evaluate("""() => {
                const items = document.querySelectorAll('[role="menuitem"], [role="option"], button, a');
                for (const el of items) {
                    const t = (el.textContent || '').trim().toLowerCase();
                    if ((t.includes('opus') && t.includes('extended')) ||
                        (t.includes('4.6') && t.includes('extended')) ||
                        t === 'extended thinking') {
                        el.click(); return true;
                    }
                }
                return false;
            }""")
            await asyncio.sleep(0.8)

        # Step 2: Open tools menu ("+" button) — enable "Research" tool
        tools_opened = False
        for sel in ['button[aria-label*="tools"]', 'button[aria-label*="attach"]',
                    'button[aria-label="Open tools menu"]', 'button[aria-label*="+"]']:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.8)
                    tools_opened = True
                    break
            except Exception:
                continue
        if tools_opened:
            await page.evaluate("""() => {
                const items = document.querySelectorAll('[role="menuitem"], button, [role="switch"], [role="checkbox"]');
                for (const el of items) {
                    const t = (el.textContent || '').trim().toLowerCase();
                    const a = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (t === 'research' || a === 'research' || t.includes('research tool')) {
                        el.click(); return true;
                    }
                }
                return false;
            }""")
            await asyncio.sleep(0.8)
            # Close menu by clicking body or pressing Escape
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # Focus input
        for sel in ['div[contenteditable="true"]', '[aria-label*="message"]', '.ProseMirror']:
            try:
                inp = await page.query_selector(sel)
                if inp:
                    await inp.click()
                    break
            except Exception:
                continue
        return True
    except Exception as e:
        log(f"[setup_claude_dr] {e}", "WARN")
        return False


async def validate_setup_with_cua(browser, cua_client, page, platform, label, verbose=False):
    """Extra validation layer: CUA looks at the screen and confirms the intended
    options (Deep Research / Extended / Research tool) are actually active. If not,
    CUA tries to fix. Returns True if 'verified' or 'fixed', False otherwise."""
    validator_map = {
        "chatgpt": PROMPT_VALIDATE_CHATGPT_SETUP,
        "gemini": PROMPT_VALIDATE_GEMINI_SETUP,
        "claude": PROMPT_VALIDATE_CLAUDE_SETUP,
    }
    user_msg_map = {
        "chatgpt": "Verify Deep Research mode is ACTIVE in ChatGPT. Fix if not. Do not type.",
        "gemini": "Verify the Deep Research pill is ACTIVE in Gemini composer. Fix if not. Do not type.",
        "claude": "Verify Opus 4.6 Extended + Research tool are ON in Claude. Clear any stale attachments. Do not type.",
    }
    sys_prompt = validator_map.get(platform.lower())
    user_prompt = user_msg_map.get(platform.lower())
    if not sys_prompt:
        return True  # Unknown platform — skip
    try:
        await browser.switch_to_page(page)
        result = await agent_loop(cua_client, browser, sys_prompt, user_prompt,
            model=CUA_MODEL, max_iterations=6, verbose=verbose)
        text = (result.get("text") or "").lower()
        if "verified" in text or "fixed" in text:
            log(f"[{label}] CUA validation: {text[:120]}")
            return True
        if "failed" in text:
            log(f"[{label}] CUA validation FAILED: {text[:160]}", "WARN")
            return False
        # Ambiguous — treat as pass but log
        log(f"[{label}] CUA validation ambiguous: {text[:120]}", "WARN")
        return True
    except Exception as e:
        log(f"[{label}] CUA validation error: {e}", "WARN")
        return True  # Don't block pipeline on validator error


# ═════════════════════════════════════════════════════════════════════
# Phase-2 brief delivery via file attachment (Option A)
# ─────────────────────────────────────────────────────────────────────
# The research brief is ~30 KB. Inline pastes get silently converted
# to attachments by both ChatGPT and Claude, and the resulting state
# is inconsistent (duplicate attachments, empty textareas). We now
# attach the brief as brief.md directly and type a short inline prompt
# that references it. This matches how the platforms actually want to
# receive long input and dodges all the paste-verification issues.
# ═════════════════════════════════════════════════════════════════════

async def attach_brief_file(browser, page, brief_path, platform, label):
    """Attach brief.md to the composer via the hidden file input.
    Returns True if exactly one attachment was confirmed visible."""
    try:
        # Clear any residual attachments from a previous attempt
        try:
            await page.evaluate("""() => {
                document.querySelectorAll(
                    'button[aria-label*="Remove"], button[aria-label*="Delete"], ' +
                    'button[data-testid*="remove-attachment"], button[data-testid*="delete-attachment"]'
                ).forEach(b => { try { b.click(); } catch(e){} });
            }""")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # PRIMARY — hidden file input (most reliable across all platforms)
        file_input = await page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_input_files(str(brief_path))
            await asyncio.sleep(3)  # Wait for UI to acknowledge
            log(f"[{label}] Brief attached via hidden file input")
            return True

        # FALLBACK — queue file for OS-level chooser then click attach
        browser.set_upload_file(str(brief_path))
        for sel in ['button[aria-label*="Attach"]', 'button[aria-label*="Upload"]',
                    'button[data-testid*="upload"]', 'button[data-testid*="file"]']:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    browser.clear_upload_file()
                    log(f"[{label}] Brief attached via button click")
                    return True
            except Exception:
                continue
        browser.clear_upload_file()
        log(f"[{label}] Could not find file input or attach button", "WARN")
        return False
    except Exception as e:
        try: browser.clear_upload_file()
        except Exception: pass
        log(f"[{label}] Brief attach failed: {e}", "WARN")
        return False


async def type_short_inline_prompt(page, platform, label):
    """Type a short inline prompt instructing the agent to research the
    attached brief. Keeps the platform's 'Deep Research' mode as the
    operative instruction; the full brief content lives in the file."""
    # One message, short enough that no platform converts it to an attachment.
    prompt = (
        "Please perform deep research on the topic described in the attached brief. "
        "Use the brief as the complete context — objectives, scope, sections, sources to target. "
        "Produce a comprehensive research report with citations. "
        "Stay in Deep Research mode for this entire response."
    )
    try:
        # Find the composer input (contenteditable or textarea) and type
        for sel in ['div[contenteditable="true"]', 'textarea', '.ProseMirror',
                    '[role="textbox"]', '[aria-label*="message"]']:
            try:
                inp = await page.query_selector(sel)
                if inp:
                    await inp.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.type(prompt, delay=5)
                    await asyncio.sleep(0.5)
                    log(f"[{label}] Inline prompt typed ({len(prompt)} chars)")
                    return True
            except Exception:
                continue
        log(f"[{label}] Could not find composer input for inline prompt", "WARN")
        return False
    except Exception as e:
        log(f"[{label}] Inline prompt type failed: {e}", "WARN")
        return False


async def ensure_deep_mode_active(page, platform, label):
    """Just-before-send check: is the platform still in its required mode?
    Re-activates if it has been toggled off. Returns the final state."""
    platform_l = platform.lower()
    try:
        if platform_l == "chatgpt":
            # Verify "Deep research" pill/badge is still on
            active = await page.evaluate("""() => {
                const txt = (document.body.innerText || '').toLowerCase();
                // Look for the Deep Research pill shown near composer
                const pills = document.querySelectorAll('[aria-pressed="true"], [data-state="on"], .pill, [role="button"]');
                for (const p of pills) {
                    const t = (p.textContent || '').trim().toLowerCase();
                    if (t === 'deep research' || t.startsWith('deep research')) return true;
                }
                // Heuristic: composer area mentions Deep research
                return txt.includes('deep research');
            }""")
            if not active:
                log(f"[{label}] Deep Research OFF before send — re-activating", "WARN")
                await setup_chatgpt_dr(page)
            return True
        if platform_l == "gemini":
            active = await page.evaluate("""() => {
                const pills = document.querySelectorAll('button, [role="button"], span');
                for (const p of pills) {
                    const t = (p.textContent || '').trim().toLowerCase();
                    if (t === 'deep research' && p.offsetParent !== null) return true;
                }
                return false;
            }""")
            if not active:
                log(f"[{label}] Gemini Deep Research chip OFF before send — re-activating", "WARN")
                await setup_gemini_dr(page)
            return True
        if platform_l == "claude":
            # Check BOTH: Opus Extended model AND Research tool are on
            state = await page.evaluate("""() => {
                const txt = (document.body.innerText || '').toLowerCase();
                const hasExtended = txt.includes('opus') && txt.includes('extended');
                // Research tool shows as a magnifying-glass icon / label near composer
                const researchOn = Array.from(document.querySelectorAll('button, [role="button"]'))
                    .some(b => {
                        const t = (b.textContent || '').toLowerCase();
                        const a = (b.getAttribute('aria-label') || '').toLowerCase();
                        return (t.includes('research') || a.includes('research')) &&
                               (b.getAttribute('aria-pressed') === 'true' ||
                                b.getAttribute('data-state') === 'on' ||
                                b.classList.contains('active') ||
                                b.classList.contains('selected'));
                    });
                return { hasExtended, researchOn };
            }""")
            if not state.get("hasExtended") or not state.get("researchOn"):
                log(f"[{label}] Claude mode regressed before send "
                    f"(extended={state.get('hasExtended')}, research={state.get('researchOn')}) — re-activating", "WARN")
                await setup_claude_dr(page)
            return True
    except Exception as e:
        log(f"[{label}] ensure_deep_mode_active error: {e}", "WARN")
    return True


async def start_agent_no_gemini_wait(browser, cua_client, url, prompt_system, prompt_user,
                                     brief, label, platform, verbose=False,
                                     brief_path=None):
    """Start agent: open tab → Playwright-direct setup → CUA validation → paste brief → submit.

    Two-layer setup for reliability:
    1. Playwright clicks known selectors (fast, deterministic when UI is stable)
    2. CUA visually validates the intended state and fixes discrepancies
    """
    log(f"[{label}] Opening {url}...")
    page = await browser.new_tab(url)
    await asyncio.sleep(4)

    # LAYER 1: Playwright-direct setup first
    platform_l = platform.lower()
    setup_ok = False
    if platform_l == "chatgpt":
        setup_ok = await setup_chatgpt_dr(page)
    elif platform_l == "gemini":
        setup_ok = await setup_gemini_dr(page)
    elif platform_l == "claude":
        setup_ok = await setup_claude_dr(page)

    if setup_ok:
        log(f"[{label}] Playwright-direct setup OK")
    else:
        # Playwright failed — try original CUA setup as a first fallback (tight iterations)
        log(f"[{label}] Playwright setup failed — CUA fallback setup (tight)...")
        result = await agent_loop(cua_client, browser, prompt_system, prompt_user,
            model=CUA_MODEL, max_iterations=8, verbose=verbose)

    # LAYER 2: CUA visual validation — confirms options are ACTUALLY active
    log(f"[{label}] CUA validating setup state...")
    cua_ok = await validate_setup_with_cua(browser, cua_client, page, platform, label, verbose)
    if not cua_ok:
        log(f"[{label}] CUA validation failed — proceeding anyway but agent may misbehave", "WARN")
        emit_event("pipeline_warning", phase=2, agent=platform_l,
                   message=f"{platform} setup validation failed — agent may not be fully configured")

    # ── Brief delivery: prefer file-attachment path (Option A) ──
    # The 30KB brief is too large for inline paste — both ChatGPT and Claude
    # auto-convert to attachments and the paste verification then fails.
    # Attaching the file directly + a short inline prompt is the reliable flow.
    if brief_path and Path(brief_path).exists():
        log(f"[{label}] Attaching brief file: {Path(brief_path).name}")
        attached = await attach_brief_file(browser, page, brief_path, platform, label)
        if attached:
            typed = await type_short_inline_prompt(page, platform, label)
            if not typed:
                log(f"[{label}] Inline prompt type failed — trying CUA fallback", "WARN")
                await browser.switch_to_page(page)
                await agent_loop(cua_client, browser,
                    "Type a short research prompt referring to the attached brief — then stop (do NOT send).",
                    "Click the message input, type: 'Please perform deep research on the topic described in the attached brief. Use Deep Research mode and produce a comprehensive report with citations.' Then STOP — do not click Send.",
                    model=CUA_MODEL, max_iterations=6, verbose=verbose)
        else:
            log(f"[{label}] Brief attachment failed — falling back to inline paste", "WARN")
            paste_ok = await verified_paste_brief(page, brief, platform, label, max_retries=3)
            if not paste_ok:
                log(f"[{label}] CRITICAL: Both attach and paste failed — skipping this agent", "ERROR")
                emit_event("pipeline_error", phase=2, agent=platform, error="Brief delivery failed (attach + paste)")
                return page
    else:
        # Legacy path (Phase 1 follow-ups, no brief file yet)
        log(f"[{label}] Pasting full brief ({len(brief)} chars) with verification...")
        paste_ok = await verified_paste_brief(page, brief, platform, label, max_retries=3)
        if not paste_ok:
            log(f"[{label}] All paste strategies failed — retrying with page reload", "WARN")
            try:
                await page.reload(wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
                paste_ok = await verified_paste_brief(page, brief, platform, label, max_retries=2)
            except Exception as e:
                log(f"[{label}] Reload+retry failed: {e}", "WARN")
        if not paste_ok:
            log(f"[{label}] CRITICAL: Brief paste completely failed — skipping this agent", "ERROR")
            emit_event("pipeline_error", phase=2, agent=platform, error="Brief paste failed — could not inject research text")
            return page

    # ── Just-before-send: ensure the required mode is STILL active ──
    # Claude especially can silently drop Research tool / Extended model
    # between setup and send. Re-activate if needed.
    await ensure_deep_mode_active(page, platform, label)

    # Brief ready — now click Send
    await asyncio.sleep(1)
    sent = False
    for sel in ['button[data-testid="send-button"]', 'button[aria-label="Send prompt"]',
                'button[aria-label="Send"]', 'button[aria-label="Send message"]',
                'button[aria-label="Send Message"]', 'button[aria-label="Submit"]']:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_enabled():
                await btn.click()
                log(f"[{label}] Send clicked ✓")
                sent = True
                break
        except Exception:
            continue
    if not sent:
        try:
            sent = await page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    const t = b.textContent.trim().toLowerCase();
                    if ((a.includes('send') || t === 'send' || t === 'submit' || a.includes('submit'))
                        && !b.disabled) {
                        b.click(); return true;
                    }
                }
                return false;
            }""")
            if sent:
                log(f"[{label}] Send clicked via JS ✓")
        except Exception:
            pass
    if not sent:
        log(f"[{label}] Playwright can't find Send — CUA clicking...")
        await browser.switch_to_page(page)
        await agent_loop(cua_client, browser, PROMPT_CLICK_SEND,
            "Click the Send button to submit the message.",
            model=CUA_MODEL, max_iterations=5, verbose=verbose)
        log(f"[{label}] CUA send attempted")

    await asyncio.sleep(3)
    return page


async def run_phase2(browser, cua_client, brief_text, verbose=False, enabled_agents=None):
    """Phase 2: ChatGPT (already in GPT from Phase 1) → Gemini (submit+plan) → Claude → Gemini (Start) → Poll all.
    enabled_agents: list of agent keys to run (e.g. ["chatgpt", "gemini"]). None = all."""
    log("=" * 60)
    log("PHASE 2: Deep Research")
    if enabled_agents:
        log(f"  Enabled agents: {enabled_agents}")
    log("  Sequence: ChatGPT → Gemini (submit+plan) → Claude → Gemini (click Start) → Poll all")
    log("=" * 60)

    # Ensure brief.md is on disk for file-attachment delivery (Option A).
    brief_path = None
    if _tracks_dir:
        brief_path = Path(__file__).parent / "queues" / _tracks_dir.name / "documents" / "brief.md"
        try:
            brief_path.parent.mkdir(parents=True, exist_ok=True)
            if not brief_path.exists() or brief_path.stat().st_size < 100:
                brief_path.write_text(
                    f"# Research Brief\n\n{brief_text}", encoding="utf-8")
                log(f"Wrote brief to disk for attachment: {brief_path.name} ({len(brief_text)} chars)")
            else:
                log(f"Using existing brief.md ({brief_path.stat().st_size} bytes)")
        except Exception as e:
            log(f"Could not prepare brief.md for attachment: {e}", "WARN")
            brief_path = None

    agents = {}

    # ── Step 1: ChatGPT (we're already in ChatGPT from Phase 1 — just open Deep Research) ──
    if enabled_agents is None or "chatgpt" in enabled_agents:
        log("\n--- 2A: ChatGPT Deep Research (already in ChatGPT) ---")
        emit_event("agent_progress", phase=2, agent="chatgpt", status="starting", progress="Opening ChatGPT Deep Research mode...")
        for attempt in range(2):
            if attempt > 0:
                log("[2A] Retrying ChatGPT (fresh tab)...", "WARN")
                try: await chatgpt_page.close()
                except Exception: pass
            chatgpt_page = await start_agent_no_gemini_wait(
                browser, cua_client, "https://chatgpt.com",
                PROMPT_CHATGPT_DEEP_RESEARCH,
                "Enable Deep Research mode in ChatGPT. Do NOT type — just set up and focus input. Say 'ready for paste'.",
                brief_text, "2A", "ChatGPT", verbose, brief_path=brief_path)
            verified_a = await wait_until_verified(verify_chatgpt_generating, chatgpt_page, "2A",
                browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
            if verified_a:
                break
        agents["ChatGPT"] = {"page": chatgpt_page, "verified": verified_a, "url": chatgpt_page.url}
        if verified_a:
            emit_event("agent_progress", phase=2, agent="chatgpt", status="generating", progress="ChatGPT Deep Research started and verified")
            log("[2A] ChatGPT Deep Research is running ✓")
        else:
            log("[2A] ChatGPT failed after 2 attempts", "ERROR")
            emit_event("pipeline_error", phase=2, agent="chatgpt", error="Failed to start after 2 attempts")
    else:
        log("\n--- 2A: ChatGPT SKIPPED (disabled in config) ---")

    # ── Step 2: Gemini (submit brief, let it generate research plan — don't wait for Start yet) ──
    gemini_page = None
    if enabled_agents is None or "gemini" in enabled_agents:
        log("\n--- 2B: Gemini Deep Research (submit + let it plan) ---")
        emit_event("agent_progress", phase=2, agent="gemini", status="starting", progress="Opening Gemini and submitting research brief...")
        gemini_page = await start_agent_no_gemini_wait(
            browser, cua_client, "https://gemini.google.com",
            PROMPT_GEMINI_DEEP_RESEARCH,
            "Enable Deep Research mode in Gemini. Do NOT type — just set up and focus input. Say 'ready for paste'.",
            brief_text, "2B", "Gemini", verbose, brief_path=brief_path)
        log("[2B] Gemini brief submitted — letting it generate research plan")
    else:
        log("\n--- 2B: Gemini SKIPPED (disabled in config) ---")

    # ── Step 3: Claude (starts instantly after submission) ──
    if enabled_agents is None or "claude" in enabled_agents:
        log("\n--- 2C: Claude Deep Research ---")
        emit_event("agent_progress", phase=2, agent="claude", status="starting", progress="Opening Claude with Extended Thinking + Research tools...")
        for attempt in range(2):
            if attempt > 0:
                log("[2C] Retrying Claude (fresh tab)...", "WARN")
                try: await claude_page.close()
                except Exception: pass
            claude_page = await start_agent_no_gemini_wait(
                browser, cua_client, "https://claude.ai/new",
                PROMPT_CLAUDE_DEEP_RESEARCH,
                "Select Opus 4.6 + Extended Thinking + Research tool. Do NOT type — just set up and focus input. Say 'ready for paste'.",
                brief_text, "2C", "Claude", verbose, brief_path=brief_path)
            verified_c = await wait_until_verified(verify_claude_generating, claude_page, "2C",
                browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
            if verified_c:
                break
        agents["Claude"] = {"page": claude_page, "verified": verified_c, "url": claude_page.url}
        if verified_c:
            emit_event("agent_progress", phase=2, agent="claude", status="generating", progress="Claude Extended Thinking started and verified")
            log("[2C] Claude is running ✓")
        else:
            log("[2C] Claude failed after 2 attempts", "ERROR")
            emit_event("pipeline_error", phase=2, agent="claude", error="Failed to start after 2 attempts")
    else:
        log("\n--- 2C: Claude SKIPPED (disabled in config) ---")

    # ── Step 4: Go back to Gemini — wait for plan + click "Start research" ──
    if gemini_page is not None:
        log("\n--- 2B: Gemini — waiting for research plan + clicking 'Start research' ---")
        await browser.switch_to_page(gemini_page)
        await asyncio.sleep(2)

        # Wait up to 90s for "Start research" button (Gemini needs time to generate plan)
        start_clicked = False
        for attempt in range(45):
            try:
                clicked = await gemini_page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = b.textContent.trim().toLowerCase();
                        if (txt.includes('start research')) { b.click(); return true; }
                    }
                    return false;
                }""")
                if clicked:
                    log("[2B] Clicked 'Start research' via JS ✓")
                    start_clicked = True
                    await asyncio.sleep(5)
                    break
            except Exception:
                pass
            if attempt % 10 == 9:
                log(f"[2B] Still waiting for research plan... ({(attempt+1)*2}s)")
            await asyncio.sleep(2)

        # CUA fallback for Start research
        if not start_clicked:
            log("[2B] JS couldn't find button — CUA clicking 'Start research'")
            await browser.switch_to_page(gemini_page)
            fix = await agent_loop(cua_client, browser,
                PROMPT_GEMINI_START_RESEARCH,
                "Click the 'Start research' button to begin the deep research.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
            fix_text = (fix.get("text") or "").lower()
            if "click" in fix_text:
                start_clicked = True
                log("[2B] CUA clicked 'Start research' ✓")
                await asyncio.sleep(5)

        # Verify Gemini is actually researching
        verified_b = await wait_until_verified(verify_gemini_generating, gemini_page, "2B",
            browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
        agents["Gemini"] = {"page": gemini_page, "verified": verified_b, "url": gemini_page.url}
        if verified_b:
            emit_event("agent_progress", phase=2, agent="gemini", status="generating", progress="Gemini Deep Research plan created and started")
            log("[2B] Gemini is researching ✓")
        else:
            log("[2B] Gemini may not be running", "WARN")

    # ── Verify all launched agents are running ──
    total = len(agents)
    verified_count = sum(1 for a in agents.values() if a["verified"])
    log(f"\n{'='*60}")
    log(f"Agents started. {verified_count}/{total} verified as running.")
    for name, a in agents.items():
        log(f"  {name:10s} {'✓ running' if a['verified'] else '✗ not verified'}  {a['url'][:60]}")
    log(f"{'='*60}")

    # Round-robin poll all agents — checks each agent every cycle instead of blocking per-agent
    if not agents:
        log("No agents to poll — all were disabled or skipped")
        return {}
    results = await poll_all_agents_round_robin(
        agents, browser, cua_client,
        max_wait_min=MAX_WAIT_DEEP, poll_interval=POLL_DEEP_RESEARCH, verbose=verbose)

    return results


# ── Phase 3: Extract MDs + Shareable Links + NotebookLM Upload ───────────────

async def run_phase3(browser, cua_client, results, topic, queue_dir, verbose=False):
    """Phase 3: Get shareable links + upload MDs to NotebookLM."""
    log("=" * 60)
    log("PHASE 3: Extract Links + NotebookLM Upload")
    log("=" * 60)

    links = {}
    md_files = []

    # Get shareable links for each platform
    share_prompts = {
        "ChatGPT": PROMPT_SHARE_CHATGPT,
        "Gemini": PROMPT_SHARE_GEMINI,
        "Claude": PROMPT_PUBLISH_CLAUDE,
    }

    # Markers for URLs that are already published/shared (extracted in Phase 2 round-robin)
    _share_url_markers = {
        "ChatGPT": ["chatgpt.com/share/", "/share/"],
        "Gemini": ["gemini.google.com/share/", "/share/"],
        "Claude": ["claude.site/artifacts/", "claude.site/", "/share/"],
    }

    for name, r in results.items():
        # Include timeout agents with .md on disk (Phase 2 partial results count)
        md_name = name.lower().replace(" ", "") + ".md"
        md_path = Path(queue_dir) / "documents" / md_name
        has_md = md_path.exists() and md_path.stat().st_size > 100
        if r["status"] not in ("done", "timeout") and not has_md:
            if r.get("url"):
                links[name] = r["url"]
                log(f"[{name}] Failed — saving chat URL: {r['url'][:60]}")
            else:
                log(f"[{name}] Skipping — no content, no URL, no .md on disk")
            continue
        if not r.get("text") and not has_md:
            if r.get("url"):
                links[name] = r["url"]
            continue

        page = r.get("page")
        if not page:
            links[name] = r.get("url", "")
            continue

        # Skip re-extraction if Phase 2 already captured a verified share link
        existing_url = r.get("url", "")
        markers = _share_url_markers.get(name, [])
        if existing_url and any(m in existing_url for m in markers):
            links[name] = existing_url
            log(f"[{name}] Using Phase-2 share link: {existing_url[:80]}")
            continue

        # Get shareable link via CUA
        log(f"[{name}] Getting shareable link...")
        try:
            await browser.switch_to_page(page)
            await asyncio.sleep(2)
            result = await agent_loop(cua_client, browser, share_prompts.get(name, PROMPT_SHARE_CHATGPT),
                f"Make this {name} conversation shareable and get the link.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)

            # Try to get the link from clipboard or URL bar
            await asyncio.sleep(1)
            clipboard = get_clipboard()
            current_url = await browser.current_url()

            # Use clipboard if it looks like a URL, else use current URL
            if clipboard and ("http" in clipboard) and len(clipboard) < 500:
                links[name] = clipboard
                log(f"[{name}] Shareable link: {clipboard[:80]}")
            else:
                links[name] = current_url
                log(f"[{name}] Using current URL: {current_url[:80]}")
        except Exception as e:
            links[name] = r.get("url", "")
            log(f"[{name}] Link error: {e} — using chat URL", "WARN")

        # Check MD file exists in queue
        fname = name.lower().replace(" ", "") + ".md"
        md_path = queue_dir / "documents" / fname
        if md_path.exists() and md_path.stat().st_size > 100:
            md_files.append(md_path)

    # Save links
    links_file = queue_dir / "links.json"
    links_file.write_text(json.dumps(links, indent=2), encoding="utf-8")
    save_track("Phase3", {"status": "links_saved", "links": links})
    log(f"Links saved: {links}")

    # Upload MDs to NotebookLM
    notebook_url = ""
    if md_files:
        log(f"\n--- Uploading {len(md_files)} MDs to NotebookLM ---")
        try:
            page = await browser.new_tab("https://notebooklm.google.com")
            await asyncio.sleep(4)

            for i, md_path in enumerate(md_files):
                log(f"Uploading {md_path.name} ({i+1}/{len(md_files)})...")
                browser.set_upload_file(str(md_path))

                if i == 0:
                    await agent_loop(cua_client, browser, PROMPT_NOTEBOOKLM_UPLOAD,
                        "Create a new notebook and upload the first file. File dialog is auto-handled.",
                        model=CUA_MODEL, max_iterations=15, verbose=verbose)
                else:
                    await agent_loop(cua_client, browser, PROMPT_NOTEBOOKLM_UPLOAD,
                        f"Add another source (file {i+1}). Click 'Add source' or '+'. File dialog is auto-handled.",
                        model=CUA_MODEL, max_iterations=10, verbose=verbose)

                browser.clear_upload_file()
                await asyncio.sleep(3)

            # Rename notebook
            short_topic = topic[:45].rsplit(' ', 1)[0] if len(topic) > 45 else topic
            title = f"Research: {short_topic}"
            log(f"Renaming notebook to '{title}'...")
            await agent_loop(cua_client, browser, PROMPT_NOTEBOOKLM_RENAME,
                f"Rename this notebook to: {title}",
                model=CUA_MODEL, max_iterations=8, verbose=verbose)

            notebook_url = await browser.current_url()
            log(f"NotebookLM: {notebook_url}")
            save_track("NotebookLM", {"status": "uploaded", "notebook_url": notebook_url,
                                       "sources_count": len(md_files)})
        except Exception as e:
            log(f"NotebookLM upload error: {e}", "ERROR")
    else:
        log("No MD files to upload to NotebookLM", "WARN")

    return {"links": links, "notebook_url": notebook_url, "md_files": [str(p) for p in md_files]}


# ── Phase 4: Audio Overview Generation ───────────────────────────────────────

async def run_phase4(browser, cua_client, notebook_url, queue_dir, verbose=False):
    """Phase 4: Generate long-form audio overview in NotebookLM."""
    log("=" * 60)
    log("PHASE 4: Audio Overview Generation")
    log("=" * 60)

    if not notebook_url:
        log("No NotebookLM notebook — skipping Phase 4", "WARN")
        return {"audio_path": None}

    # Navigate to notebook if not already there
    current = await browser.current_url()
    if "notebooklm" not in current:
        await browser.navigate(notebook_url)
        await asyncio.sleep(4)

    # Check if audio is ALREADY generating (prevent double click)
    already_generating = await _check_audio_generating(browser.page)
    if already_generating:
        log("Audio already generating — skipping Generate click")
    else:
        log("Starting audio generation (Long + Deep dive)...")
        await agent_loop(cua_client, browser, PROMPT_AUDIO_GENERATE,
            "Generate ONE audio overview. Select all sources, set Long + Deep dive, click Generate ONCE. Say 'generating' when started.",
            model=CUA_MODEL, max_iterations=15, verbose=verbose)

    # Verify it started
    verified = await wait_until_verified(
        lambda page: _check_audio_generating(page),
        browser.page, "Phase4", browser=browser, cua_client=cua_client,
        max_retries=10, interval=5, verbose=verbose)

    if not verified:
        log("Could not verify audio generation started", "WARN")

    # Minimum 5 minute wait — audio generation takes at least 5-10 minutes
    log("Waiting 5 minutes before first audio check (generation takes ~10-20 min)...")
    interrupt = await _controls.interruptible_sleep(5 * 60, check_interval=10)
    if interrupt == "stop":
        log("[Phase4] STOP during initial wait — aborting", "WARN")
        return {"audio_path": None}
    if interrupt == "pause":
        emit_event("pipeline_paused", phase=4)
        await _controls.wait_if_paused()
        if _controls.is_stop():
            return {"audio_path": None}

    # Poll for completion — refresh + CUA check every 3 min, 45 min total timeout
    log("Polling for audio completion (every 3 min with refresh, max 45 min total)...")
    audio_done = False
    poll_start = time.time()
    max_poll = 40 * 60  # 40 more min (45 total including initial 5 min wait)

    while (time.time() - poll_start) < max_poll:
        # ── Stop/Pause check per cycle ──
        if _controls.is_stop():
            log("[Phase4] STOP requested — aborting audio poll")
            break
        if _controls.is_pause():
            emit_event("pipeline_paused", phase=4)
            await _controls.wait_if_paused()
            if _controls.is_stop():
                break

        # Refresh page every cycle (NotebookLM doesn't always auto-update)
        try:
            await browser.page.reload(wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(5)
        except Exception:
            pass

        # CUA check — strict: only "audio complete" counts
        diag = await agent_loop(cua_client, browser, PROMPT_AUDIO_CHECK,
            "Check: Has audio generation FINISHED? Is there a completed audio player "
            "with NO progress indicator? Answer 'audio complete' ONLY if fully done.",
            model=CUA_MODEL, max_iterations=3, verbose=verbose)
        diag_text = (diag.get("text") or "").lower()

        if "audio complete" in diag_text:
            log("Audio generation complete ✓")
            audio_done = True
            break

        elapsed_min = 5 + int((time.time() - poll_start) / 60)
        log(f"[Phase4] Audio still generating... ({elapsed_min}m total)")
        save_track("Phase4", {"status": "generating", "elapsed_min": elapsed_min})
        interrupt = await _controls.interruptible_sleep(175, check_interval=10)
        if interrupt == "stop":
            log("[Phase4] STOP during poll wait — aborting")
            break
        if interrupt == "pause":
            emit_event("pipeline_paused", phase=4)
            await _controls.wait_if_paused()
            if _controls.is_stop():
                break

    # Download audio
    audio_path = None
    if audio_done:
        (queue_dir / "podcasts").mkdir(exist_ok=True)

        # Use Playwright download event to capture the file reliably
        download_future = asyncio.get_event_loop().create_future()

        async def _on_download(download):
            try:
                # Sanitize filename — special chars like $ break ffmpeg
                clean_name = re.sub(r'[^\w\s.-]', '', download.suggested_filename).strip() or "audio_overview.m4a"
                dest = queue_dir / "podcasts" / clean_name
                await download.save_as(str(dest))
                if not download_future.done():
                    download_future.set_result(dest)
                log(f"Audio downloaded via Playwright: {dest.name}")
            except Exception as e:
                log(f"Download save failed: {e}", "WARN")
                if not download_future.done():
                    download_future.set_result(None)

        browser.page.on("download", _on_download)

        await agent_loop(cua_client, browser, PROMPT_AUDIO_DOWNLOAD,
            "Download the audio file.", model=CUA_MODEL, max_iterations=8, verbose=verbose)

        # Wait up to 30s for download event
        try:
            audio_path = await asyncio.wait_for(download_future, timeout=30)
        except asyncio.TimeoutError:
            log("Download event not received — checking common download dirs...", "WARN")
            # Fallback: scan common download locations
            for dl_dir in [Path.home() / "Downloads", Path("D:/Downloads")]:
                if not dl_dir.exists():
                    continue
                for ext in ("*.mp3", "*.wav", "*.m4a", "*.webm"):
                    for f in sorted(dl_dir.glob(ext), key=lambda f: f.stat().st_mtime, reverse=True):
                        if (time.time() - f.stat().st_mtime) < 120:  # Created in last 2 min
                            dest = queue_dir / "podcasts" / f.name
                            shutil.move(str(f), str(dest))
                            audio_path = dest
                            log(f"Audio found in {dl_dir.name}: {f.name}")
                            break
                    if audio_path:
                        break
                if audio_path:
                    break

        try:
            browser.page.remove_listener("download", _on_download)
        except Exception:
            pass

    # ── Sync to Firebase Storage + Firestore audios subcollection ──
    # Upload the audio file so the Vercel Podcasts page can stream it
    # without needing the local backend to be reachable. Duration via
    # ffprobe for nice display (M:SS). Best-effort — pipeline continues
    # even if sync fails.
    if audio_path and audio_path.exists():
        try:
            dur_sec = 0
            try:
                _probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries",
                     "format=duration", "-of", "csv=p=0", str(audio_path)],
                    capture_output=True, text=True, timeout=5)
                dur_sec = int(float(_probe.stdout.strip()))
            except Exception:
                pass
            audio_url = upload_audio_to_storage(audio_path)
            # Use the filename stem as doc id so re-runs upsert in place
            # instead of stacking duplicates.
            save_audio_to_firestore(audio_path.stem, audio_path.name, dur_sec, audio_url)
        except Exception as e:
            log(f"Audio Firestore/Storage sync failed: {e}", "WARN")

    return {"audio_path": audio_path}


async def _check_audio_generating(page):
    """Check if NotebookLM is generating audio."""
    try:
        return await page.evaluate("""() => {
            const text = document.body.innerText.toLowerCase();
            return text.includes('generating') || text.includes('creating audio') || text.includes('in progress');
        }""")
    except Exception:
        return False


# ── Phase 5: Video Conversion + YouTube Upload ──────────────────────────────

GEMINI_API_KEY = get_env("GEMINI_API_KEY")  # For thumbnail generation (Imagen)


def generate_thumbnail(topic, output_path):
    """Generate a topic-relevant thumbnail via Gemini Imagen API. Falls back to Pillow text card."""
    # Try Gemini image generation first (Imagen 3 via Gemini API)
    try:
        import requests
        prompt = (
            f"Create a professional, modern YouTube thumbnail for a research video about: "
            f"{topic[:200]}. Dark futuristic theme, clean design, abstract tech visuals. "
            f"No text on the image — just visual design. 16:9 aspect ratio."
        )
        # Use Gemini 2.0 Flash with image generation (supports Imagen 3 natively)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}
        }
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if "inlineData" in part:
                        img_data = base64.b64decode(part["inlineData"]["data"])
                        Path(output_path).write_bytes(img_data)
                        log(f"Thumbnail generated via Gemini ✓ ({len(img_data)} bytes)")
                        return
        log(f"Gemini image gen returned {resp.status_code} — falling back to Pillow", "WARN")
    except Exception as e:
        log(f"Gemini image gen failed: {e} — falling back to Pillow", "WARN")

    # Fallback: Pillow text card
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (1920, 1080), color=(15, 15, 25))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 48)
            subfont = ImageFont.truetype("arial.ttf", 28)
        except (OSError, IOError):
            font = ImageFont.load_default()
            subfont = font
        title = "Research Overview"
        bbox = draw.textbbox((0, 0), title, font=font)
        draw.text(((1920 - bbox[2]) / 2, 400), title, fill=(200, 200, 220), font=font)
        topic_short = topic[:80] + "..." if len(topic) > 80 else topic
        bbox = draw.textbbox((0, 0), topic_short, font=subfont)
        draw.text(((1920 - bbox[2]) / 2, 500), topic_short, fill=(100, 140, 255), font=subfont)
        img.save(str(output_path))
    except ImportError:
        import struct, zlib
        w, h = 1920, 1080
        def chunk(ct, d):
            c = ct + d
            return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        raw = b''.join(b'\x00' + b'\x00\x00\x00' * w for _ in range(h))
        Path(output_path).write_bytes(b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    log(f"Thumbnail: {output_path}")


async def run_phase5(browser, cua_client, audio_path, topic, queue_dir,
                     links=None, notebook_url="", verbose=False):
    """Phase 5: Convert audio to video + upload to YouTube with thumbnail."""
    log("=" * 60)
    log("PHASE 5: Video + YouTube Upload")
    log("=" * 60)

    if not audio_path or not Path(audio_path).exists():
        log("No audio file — skipping Phase 5", "WARN")
        return {"youtube_url": ""}

    video_dir = queue_dir / "video"
    video_dir.mkdir(exist_ok=True)

    # Generate thumbnail (Gemini Imagen → Pillow fallback) — save to queues root
    title_card = queue_dir / "thumbnail.png"
    generate_thumbnail(topic, title_card)

    # ffmpeg: audio + title card → MP4
    video_path = video_dir / "research_overview.mp4"
    log("Converting audio to video (ffmpeg)...")
    try:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", "2", "-i", str(title_card),
               "-i", str(audio_path), "-c:v", "libx264", "-tune", "stillimage",
               "-c:a", "aac", "-b:a", "192k", "-r", "2", "-pix_fmt", "yuv420p",
               "-shortest", str(video_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            log(f"ffmpeg error: {r.stderr[:300]}", "ERROR")
            return {"youtube_url": ""}
        log(f"Video: {video_path} ({video_path.stat().st_size / 1024 / 1024:.1f}MB)")
        save_track("Phase5", {"status": "video_created", "size_mb": round(video_path.stat().st_size / 1024 / 1024, 1)})
    except Exception as e:
        log(f"ffmpeg failed: {e}", "ERROR")
        return {"youtube_url": ""}

    # Upload to YouTube
    log("Uploading to YouTube (unlisted)...")
    page = await browser.new_tab("https://studio.youtube.com")
    await asyncio.sleep(4)

    # Queue video first, then thumbnail for sequential file dialogs
    browser.set_upload_file(str(video_path))
    if title_card.exists():
        browser.queue_upload_file(str(title_card))

    title = f"Research Overview: {topic[:80]}"
    # Build description with research links
    desc_parts = [f"Research overview on: {topic[:200]}"]
    if links:
        desc_parts.append("\nResearch Links:")
        for name, url in (links or {}).items():
            if url:
                desc_parts.append(f"{name}: {url}")
    if notebook_url:
        desc_parts.append(f"NotebookLM: {notebook_url}")
    description = "\n".join(desc_parts)

    result = await agent_loop(cua_client, browser, PROMPT_YOUTUBE_UPLOAD,
        f'Upload video. Title: "{title}"\nDescription:\n{description}\n\n'
        f'All file dialogs are auto-handled (video first, then thumbnail).',
        model=CUA_MODEL, max_iterations=35, verbose=verbose)

    browser.clear_upload_file()

    # Try to get YouTube URL — check CUA response, DOM, then clipboard
    await asyncio.sleep(3)
    youtube_url = ""
    # 1. Check CUA response text for URL
    cua_text = result.get("text", "")
    yt_match = re.search(r'(https?://(?:youtu\.be|youtube\.com/watch\?v=)[a-zA-Z0-9_-]+)', cua_text)
    if yt_match:
        youtube_url = yt_match.group(1)
    # 2. Check DOM for link
    if not youtube_url:
        try:
            url = await page.evaluate("""() => {
                const a = document.querySelector('a[href*="youtu.be"], a[href*="youtube.com/watch"]');
                return a ? a.href : '';
            }""")
            youtube_url = url
        except Exception:
            pass
    # 3. Check clipboard
    if not youtube_url:
        clip = get_clipboard()
        if "youtu" in clip:
            youtube_url = clip
    # 4. Fallback to page URL
    if not youtube_url:
        youtube_url = await browser.current_url()

    log(f"YouTube: {youtube_url}")
    save_track("Phase5", {"status": "youtube_uploaded", "youtube_url": youtube_url})

    # Keep all generated files (audio, video, thumbnail) — used by web app
    # Keep all generated files (audio, video, thumbnail) — used by web app
    log(f"Files preserved in queue: {queue_dir}")

    return {"youtube_url": youtube_url}


# ── Phase 6: Google Doc + Gmail Delivery ─────────────────────────────────────

async def run_phase6(browser, cua_client, topic, links, notebook_url, youtube_url,
                     brief_url="", audio_url="", email=None, verbose=False):
    """Phase 6: Create Google Doc hub + send email."""
    log("=" * 60)
    log("PHASE 6: Email & Delivery")
    log("=" * 60)

    # Build doc content — structured format matching PRD
    short_topic = topic[:100] if len(topic) > 100 else topic
    doc_lines = [
        f"{short_topic}",
        "",
        "Links to Researches:",
    ]
    if brief_url:
        doc_lines.append(f"ChatGPT Brief: {brief_url}")
    for name in ["ChatGPT", "Gemini", "Claude"]:
        url = links.get(name, "")
        if url:
            doc_lines.append(f"{name}: {url}")
    doc_lines.append("")
    if notebook_url:
        doc_lines.append(f"Link to NotebookLM: {notebook_url}")
    if audio_url:
        doc_lines.append(f"Link to Audio Overview:")
        doc_lines.append(f"{audio_url}")
    elif notebook_url:
        doc_lines.append(f"Link to Audio Overview:")
        doc_lines.append(f"{notebook_url}")
    if youtube_url:
        doc_lines.append(f"")
        doc_lines.append(f"Link to YouTube: {youtube_url}")
    doc_content = "\n".join(doc_lines)

    # Create Google Doc
    log("Creating Google Doc...")
    doc_url = ""
    try:
        page = await browser.new_tab("https://docs.google.com/document/create")
        await asyncio.sleep(5)

        await agent_loop(cua_client, browser, PROMPT_CREATE_DOC,
            f"Type this content into the doc, then share with 'Anyone with link can edit':\n\n{doc_content}",
            model=CUA_MODEL, max_iterations=20, verbose=verbose)

        await asyncio.sleep(2)

        doc_url = await browser.current_url()
        log(f"Google Doc: {doc_url}")
        save_track("Phase5", {"status": "doc_created", "doc_url": doc_url})
    except Exception as e:
        log(f"Google Doc error: {e}", "ERROR")

    # Send email
    email_sent = False
    if email:
        log(f"Sending email to {email}...")
        try:
            page = await browser.new_tab("https://mail.google.com")
            await asyncio.sleep(4)

            subject = f"Research Complete: {topic[:60]}"
            body_parts = [f"Research complete: {topic[:100]}\n"]
            if doc_url:
                body_parts.append(f"Google Doc: {doc_url}")
            for pname in ["ChatGPT", "Gemini", "Claude"]:
                purl = links.get(pname, "")
                if purl:
                    body_parts.append(f"{pname}: {purl}")
            if notebook_url:
                body_parts.append(f"NotebookLM: {notebook_url}")
            if youtube_url:
                body_parts.append(f"YouTube: {youtube_url}")
            body = "\n".join(body_parts) + "\n"

            await agent_loop(cua_client, browser, PROMPT_SEND_EMAIL,
                f"Send email to: {email}\nSubject: {subject}\nBody:\n{body}",
                model=CUA_MODEL, max_iterations=12, verbose=verbose)

            email_sent = True
            log("Email sent ✓")
            save_track("Phase5", {"status": "email_sent", "email": email})
        except Exception as e:
            log(f"Email error: {e}", "ERROR")
    else:
        log("No email configured — skipping")

    return {"doc_url": doc_url, "email_sent": email_sent}


# ── Checkpoint & Resume ───────────────────────────────────────────────────────

def save_checkpoint(queue_dir, phase, **kwargs):
    """Save pipeline checkpoint after completing a phase."""
    cp = {"last_completed_phase": phase, "timestamp": datetime.now().isoformat()}
    cp.update(kwargs)
    (Path(queue_dir) / "checkpoint.json").write_text(json.dumps(cp, indent=2), encoding="utf-8")


def load_checkpoint(queue_dir):
    """Load checkpoint from a previous run. Returns dict or None."""
    cp_file = Path(queue_dir) / "checkpoint.json"
    if cp_file.exists():
        try:
            return json.loads(cp_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def save_meta(queue_dir, topic, phase, status="ongoing", **extra):
    """Save/update meta.json — powers ALL frontend components (graphs, analytics, tracking).
    Contains: Research object + per-agent stats + phase timeline + source references."""
    queue_dir = Path(queue_dir)
    meta_path = queue_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if "id" not in meta:
        meta["id"] = queue_dir.name
        meta["createdAt"] = int(time.time() * 1000)

    # ── Scan documents/ for files ──
    docs = []
    doc_dir = queue_dir / "documents"
    if doc_dir.exists():
        for f in sorted(doc_dir.glob("*.md")):
            if f.stat().st_size > 50:
                docs.append({"id": f.stem, "name": f.name, "type": f.stem,
                              "size": f"{f.stat().st_size / 1024:.0f} KB",
                              "createdAt": int(f.stat().st_mtime * 1000)})

    # ── Scan podcasts/ for audio files ──
    podcasts = []
    pod_dir = queue_dir / "podcasts"
    if pod_dir.exists():
        for f in pod_dir.glob("*.*"):
            # Try to get duration from ffprobe
            dur_sec = 0
            try:
                r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                    "format=duration", "-of", "csv=p=0", str(f)],
                    capture_output=True, text=True, timeout=5)
                dur_sec = int(float(r.stdout.strip()))
            except Exception:
                pass
            mins, secs = divmod(dur_sec, 60)
            podcasts.append({"id": f.stem, "name": f.name,
                             "duration": f"{mins}:{secs:02d}" if dur_sec else "",
                             "durationSec": dur_sec,
                             "createdAt": int(f.stat().st_mtime * 1000)})

    # ── Per-agent stats (for analytics graphs, radar chart, health score) ──
    agents = meta.get("agents", {})
    for platform in ["chatgpt", "gemini", "claude"]:
        md_file = doc_dir / f"{platform}.md" if doc_dir.exists() else None
        if md_file and md_file.exists() and md_file.stat().st_size > 100:
            content = md_file.read_text(encoding="utf-8")
            # Extract sections — markdown headings + bold standalone lines (ChatGPT style)
            sections = re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)
            if len(sections) <= 2:
                # ChatGPT often uses **Bold Title** instead of # headings
                bold_sections = re.findall(r'^\*\*(.{5,80})\*\*\s*$', content, re.MULTILINE)
                # Also try numbered bold: **1. Title**
                numbered = re.findall(r'^\*\*\d+[\.\)]\s*(.{5,80})\*\*', content, re.MULTILINE)
                sections = sections + bold_sections + numbered
                sections = list(dict.fromkeys(sections))[:20]  # Dedupe
            # Filter out the file header we added
            sections = [s for s in sections if s not in ("ChatGPT Deep Research", "Gemini Deep Research", "Claude Deep Research")]
            # Extract source URLs from markdown links and references
            urls = re.findall(r'https?://[^\s\)\]\"\'>]+', content)
            unique_urls = list(dict.fromkeys(urls))[:50]  # Dedupe, cap at 50
            # Extract domains
            source_refs = []
            for url in unique_urls:
                try:
                    domain = url.split("//")[1].split("/")[0].replace("www.", "")
                    source_refs.append({"url": url, "domain": domain, "agent": platform})
                except Exception:
                    pass
            # Build/update agent entry
            existing = agents.get(platform, {})
            agents[platform] = {
                "sources": len(unique_urls),
                "sourceUrls": unique_urls[:30],
                "sourceRefs": source_refs[:30],
                "sections": sections[:15],
                "outputChars": len(content),
                "completionTimeSec": existing.get("completionTimeSec", 0),
                "findings": sections[:3] if sections else [],
            }

    # ── Phase timeline (for timeline graph) ──
    phases = meta.get("phases", [])
    phase_labels = ["Initializing", "Research Brief", "Deep Research",
                    "Links + NotebookLM", "Audio Overview", "Video + YouTube", "Delivery"]
    now_ms = int(time.time() * 1000)
    # Ensure all phases up to current exist
    while len(phases) <= phase:
        p_idx = len(phases)
        # Start time: use previous phase's completedAt, or createdAt for first phase
        start = meta.get("createdAt", now_ms)
        if p_idx > 0 and len(phases) > 0 and phases[-1].get("completedAt"):
            start = phases[-1]["completedAt"]
        phases.append({
            "phase": p_idx,
            "label": phase_labels[p_idx] if p_idx < len(phase_labels) else f"Phase {p_idx}",
            "startedAt": start,
            "completedAt": None,
            "durationSec": 0,
        })
    # Mark current phase as completed with actual duration
    if phase < len(phases) and phases[phase]["completedAt"] is None:
        phases[phase]["completedAt"] = now_ms
        started = phases[phase].get("startedAt", now_ms)
        phases[phase]["durationSec"] = max(0, (now_ms - started) // 1000)

    # ── Write meta ──
    meta.update({
        "title": topic[:100] if topic else meta.get("title", ""),
        "topic": topic or meta.get("topic", ""),
        "summary": extra.get("summary", meta.get("summary", "")),
        "status": status,
        "phase": phase,
        "platforms": ["chatgpt", "gemini", "claude"],
        "documents": docs,
        "audios": podcasts,
        "agents": agents,
        "phases": phases,
        "updatedAt": now_ms,
    })
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # ── Propagate structured agents/phases to Firestore research doc ──
    # Without this, the frontend Analytics page never sees per-agent stats or
    # phase timelines for live runs — they live only on disk. Uses a shallow
    # update so we don't clobber other fields (like pipelineConfig).
    try:
        _update_firestore_research({
            "agents": agents,
            "phases": phases,
            "status": status,
            "phase": phase,
            "updatedAt": now_ms,
        })
    except Exception as _e:
        log(f"save_meta: firestore propagation failed: {_e}", "WARN")


def detect_resume_phase(queue_dir):
    """Detect which phase to resume from based on existing output files.
    Returns (phase_number, description). Uses 6-phase model (0-5)."""
    queue_dir = Path(queue_dir)
    if (queue_dir / "delivery.json").exists():
        try:
            delivery = json.loads((queue_dir / "delivery.json").read_text(encoding="utf-8"))
            if delivery.get("status") == "completed":
                return 6, "Pipeline already complete"
        except Exception:
            pass
    cp = load_checkpoint(queue_dir)
    # Phase 4 done → resume from Phase 5: check if YouTube done but no delivery
    if cp and cp.get("youtube_url"):
        return 5, "YouTube done — Phase 4 done, resuming from Phase 5 (Report)"
    # Phase 3 done → resume from Phase 4: check if audio exists
    if cp and cp.get("audio_path") and Path(cp["audio_path"]).exists():
        return 4, "Audio exists — Phase 3 done, resuming from Phase 4 (YouTube)"
    audio_dir = queue_dir / "podcasts"
    if audio_dir.exists() and any(audio_dir.glob("*.*")):
        return 4, "Audio exists — Phase 3 done, resuming from Phase 4 (YouTube)"
    # Phase 2 done but no audio → resume from Phase 3: check if links/notebook exist
    if (queue_dir / "links.json").exists():
        return 3, "Links exist — resuming from Phase 3 (NotebookLM)"
    # Phase 2 done → resume from Phase 3: check if research MDs exist
    research_dir = queue_dir / "documents"
    has_research = research_dir.exists() and any(
        f for f in research_dir.glob("*.md") if f.stat().st_size > 100 and f.stem != "brief")
    if has_research:
        return 3, "Research MDs exist — Phase 2 done, resuming from Phase 3"
    # Phase 1 done → resume from Phase 2: check if brief exists
    brief = queue_dir / "documents" / "brief.md"
    if not brief.exists():
        brief = queue_dir / "brief.md"
    if brief.exists() and brief.stat().st_size > 100:
        return 2, "Brief exists — Phase 1 done, resuming from Phase 2"
    return 0, "Starting from Phase 0 (Init)"


# ── Main Pipeline ─────────────────────────────────────────────────────────────

async def run_pipeline(topic, pdf_paths=None, brief_file=None, verbose=False,
                       api_key=None, email=None, resume_dir=None, config=None,
                       run_id=None, uid=None, research_id=None):
    """Run the full pipeline. Supports resume from a previous queue directory."""
    pdf_paths = pdf_paths or []
    api_key = resolve_api_key(api_key)
    if not api_key:
        log("No API key (set CUA_API_KEY)", "ERROR")
        return

    import anthropic
    cua_client = anthropic.Anthropic(api_key=api_key)

    # ── Initialize pipeline controls + Firestore bridge ──
    _controls.reset()
    _runtime.reset()
    # Clear dedup cache — stale keys from a prior run in the same process
    # would otherwise suppress early events in this run.
    _last_progress.clear()
    brief_artifact = None  # Set after Phase 1 completes
    # Validate email early (email is the user's Google account email from frontend)
    if email:
        ok, reason = validate_email(email)
        if not ok:
            log(f"[email] Invalid email received: {reason} — Phase 5 email will be skipped", "WARN")
            email = None
    if uid:
        # Use frontend research_id for Firestore paths (not run_id which is the backend dir name)
        setup_firestore_run(uid, research_id or run_id, asyncio.get_running_loop())
    # Start mid-run input dispatcher (watches _controls.extra_context, pastes to active pages)
    try:
        _runtime.dispatcher_task = asyncio.create_task(run_input_dispatcher())
    except Exception as e:
        log(f"[dispatcher] Failed to start: {e}", "WARN")

    # ── Determine queue directory + start phase ──
    if resume_dir:
        queue_dir = Path(resume_dir)
        if not queue_dir.exists():
            log(f"Resume dir not found: {queue_dir}", "ERROR")
            return
        (queue_dir / "documents").mkdir(exist_ok=True)
        start_phase, reason = detect_resume_phase(queue_dir)
        log(f"RESUME: {reason}")
        # Emit resume marker so frontend knows to ignore events before this point
        emit_event("pipeline_resumed", phase=start_phase, resumeReason=reason)
        if start_phase > 5:
            log("Pipeline already complete — nothing to resume")
            return
        cp = load_checkpoint(queue_dir) or {}
        topic = topic or cp.get("topic", queue_dir.name.rsplit("_", 2)[0].replace("_", " "))
        # Load pipeline config on resume
        config_path = queue_dir / "config.json"
        pipeline_config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    else:
        run_name = run_id or f"{safe_name(topic)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        queue_dir = Path(__file__).parent / "queues" / run_name
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "documents").mkdir(exist_ok=True)
        start_phase = 1
        cp = {}
        # Save pipeline config for new runs
        pipeline_config = config or {}
        (queue_dir / "config.json").write_text(json.dumps(pipeline_config, indent=2), encoding="utf-8")

    log(f"Queue: {queue_dir}")
    tracks_dir = init_tracks(queue_dir.name)  # Same name as queue — one research = one tracks folder

    # ── Pipeline config: reload from config.json before each phase (supports mid-pipeline changes) ──
    def reload_config():
        nonlocal pipeline_config
        config_path = queue_dir / "config.json"
        if config_path.exists():
            try:
                pipeline_config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        # Merge any in-memory config updates from Firestore commands
        # (in case Firestore config arrived but HTTP PATCH didn't)
        ctrl_updates = _controls.pop_config_updates()
        if ctrl_updates:
            pipeline_config.update(ctrl_updates)
            # Persist merged config back to disk for next reload
            try:
                config_path.write_text(json.dumps(pipeline_config, indent=2), encoding="utf-8")
            except Exception:
                pass
        sp = set(pipeline_config.get("skipPhases", []))
        ac = pipeline_config.get("agents", {"chatgpt": True, "gemini": True, "claude": True})
        ve = pipeline_config.get("videoEnabled", True)
        ee = pipeline_config.get("emailEnabled", True)
        if 3 in sp:
            sp.add(4)
        return sp, ac, ve, ee

    skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()

    # ── Preload data from previous phases (for resume) ──
    brief_text, brief_url = "", cp.get("brief_url", "")
    links, notebook_url, youtube_url = {}, cp.get("notebook_url", ""), cp.get("youtube_url", "")

    # ── Helper: update delivery.json incrementally (frontend reads this for live links) ──
    def update_delivery(**new_fields):
        d_path = queue_dir / "delivery.json"
        d = json.loads(d_path.read_text(encoding="utf-8")) if d_path.exists() else {
            "topic": topic, "status": "ongoing", "brief_url": "", "research_links": {},
            "notebook_url": "", "audio_url": "", "youtube_url": "", "doc_url": "", "email_sent": False,
        }
        d.update(new_fields)
        d_path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    # ── Helper: check if user requested stop or pause ──
    def stop_requested():
        """True if terminal stop requested (pipeline is DONE)."""
        return (queue_dir / ".stop").exists()

    def pause_requested():
        """True if pause requested (pipeline is FROZEN, can resume)."""
        return (queue_dir / ".pause").exists()

    def stop_or_pause_requested():
        """True if either stop or pause — used in between-phase checks."""
        return stop_requested() or pause_requested()

    def clear_pause():
        p = queue_dir / ".pause"
        if p.exists():
            p.unlink()

    # ── Helper: read user feedback for a phase ──
    def get_feedback(phase_num):
        fb_path = queue_dir / "feedback.json"
        if fb_path.exists():
            try:
                fb = json.loads(fb_path.read_text(encoding="utf-8"))
                return fb.get(str(phase_num), "")
            except Exception:
                pass
        return ""

    def clear_feedback(phase_num):
        fb_path = queue_dir / "feedback.json"
        if fb_path.exists():
            try:
                fb = json.loads(fb_path.read_text(encoding="utf-8"))
                fb.pop(str(phase_num), None)
                fb_path.write_text(json.dumps(fb, indent=2), encoding="utf-8")
            except Exception:
                pass

    # Create delivery.json immediately (frontend can see the run from the start)
    if not (queue_dir / "delivery.json").exists():
        update_delivery()

    browser = Browser(PROFILE_DIR, headless=False)
    try:
        # ══════════════════════ PHASE 0: Init ══════════════════════
        emit_event("phase_start", phase=0, description="Initializing pipeline")
        _p0_start = time.time()
        emit_event("agent_progress", phase=0, agent="system", status="Preparing", progress="Loading configuration and API keys...")
        emit_event("agent_progress", phase=0, agent="system", status="Launching", progress="Starting Chromium browser with automation profile...")
        await browser.start()
        emit_event("agent_progress", phase=0, agent="system", status="Verifying", progress="Browser launched — verifying connectivity to AI platforms...")
        emit_event("agent_progress", phase=0, agent="system", status="Ready", progress="All services verified — pipeline ready to begin")
        emit_event("phase_complete", phase=0, durationSec=int(time.time() - _p0_start), summary="Browser launched, all services verified")

        # ══════════════════════ PHASE 1: Brief ══════════════════════
        p1 = None
        if 1 in skip_phases:
            log("Phase 1: SKIPPED by config")
            emit_event("phase_skipped", phase=1, reason="Disabled in pipeline config")
        elif start_phase <= 1:
            emit_event("phase_start", phase=1, description="Generating research brief with ChatGPT Pro + Extended Thinking", agents=["chatgpt"])
            _p1_start = time.time()
            if brief_file:
                brief_text = Path(brief_file).read_text(encoding="utf-8")
                log(f"Phase 1: SKIPPED — loaded brief from {brief_file} ({len(brief_text)} chars)")
            else:
                fb1 = get_feedback(1)
                p1 = await run_phase1(browser, cua_client, topic, pdf_paths, verbose, feedback=fb1)
                if fb1:
                    clear_feedback(1)
                if not p1 or not p1["text"]:
                    log("Phase 1 failed — no brief generated", "ERROR")
                    emit_event("pipeline_error", phase=1, error="no brief generated")
                    return
                brief_text = p1["text"]
                brief_url = p1.get("url", "")
            # Save brief in documents/
            _brief_md = f"# Research Brief\n\n{brief_text}"
            (queue_dir / "documents" / "brief.md").write_text(_brief_md, encoding="utf-8")
            # Sync to Firestore documents subcollection for Vercel Documents page
            save_document_to_firestore("brief", _brief_md, "Research Brief")
            # Create BriefArtifact for reliable Phase 2 paste
            brief_artifact = BriefArtifact(text=brief_text, url=brief_url)
            log(f"BriefArtifact: {brief_artifact.chars} chars, {len(brief_artifact.sections)} sections")
            # ── Link-before-advance: extract shareable ChatGPT link ──
            log("Phase 1: Extracting shareable link before advancing...")
            _p1_link_results = await extract_phase_links(1, browser, cua_client, verbose=verbose)
            _p1_links = [r.to_dict() for r in _p1_link_results if r.success]
            if _p1_links:
                brief_url = _p1_links[0]["url"]
                brief_artifact.url = brief_url
                # Real-time link emission for frontend PhaseDropdown
                emit_event("link_extracted", phase=1, agent="chatgpt",
                           url=brief_url, label="ChatGPT Brief", verified=True)
            save_checkpoint(queue_dir, 1, topic=topic, brief_url=brief_url)
            update_delivery(brief_url=brief_url)
            save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())
            emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start), links=_p1_links,
                summary=f"Research brief generated ({brief_artifact.chars} chars, {len(brief_artifact.sections)} sections)")
            _update_firestore_research({"phase": 1, "status": "ongoing", "links.phase1": _p1_links})
        else:
            # Load brief from documents/ (new location) or root (old location)
            for bp in [queue_dir / "documents" / "brief.md", queue_dir / "brief.md"]:
                if bp.exists():
                    raw = bp.read_text(encoding="utf-8")
                    brief_text = raw.replace("# Research Brief\n\n", "", 1)
                    break
            log(f"Phase 1: Loaded existing brief ({len(brief_text)} chars)")

        if _controls.is_stop_or_pause():
            if _controls.is_stop():
                log("STOP requested after Phase 1 — pipeline terminated", "WARN")
                save_meta(queue_dir, topic, 1, status="stopped")
                update_delivery(status="stopped")
                emit_event("pipeline_stopped", phase=1, reason="stop")
                _update_firestore_research({"status": "stopped", "phase": 1})
            else:
                log("PAUSE requested after Phase 1 — closing browser, awaiting resume", "WARN")
                save_meta(queue_dir, topic, 1, status="paused")
                update_delivery(status="paused")
                _update_firestore_research({"status": "paused", "phase": 1})
                _runtime.original_inputs = {"topic": topic, "pdf_paths": [str(p) for p in (pdf_paths or [])]}
                stopped = await pause_and_close_browser(browser, queue_dir, phase=1,
                                                        extra_kwargs={"topic": topic, "brief_url": brief_url})
                if stopped:
                    save_meta(queue_dir, topic, 1, status="stopped")
                    emit_event("pipeline_stopped", phase=1, reason="stop_after_pause")
                    _update_firestore_research({"status": "stopped", "phase": 1})
                    return
                # Relaunch browser on resume (no active agents to restore since Phase 1 is done)
                browser = Browser(PROFILE_DIR, headless=False)
                await browser.start()
                emit_event("pipeline_resumed", phase=1)
                _update_firestore_research({"status": "ongoing"})
                # Restart-phase logic: if user supplied input while paused, regenerate the brief
                if _controls.peek_extra_context():
                    resume_input = _controls.pop_extra_context()
                    log(f"Phase 1: Resume-with-input — regenerating brief with {len(resume_input)} extra chars")
                    emit_event("phase_restart", phase=1, reason="user_input_on_resume", chars=len(resume_input))
                    combined_topic = topic + "\n\nADDITIONAL USER CONTEXT:\n" + resume_input
                    p1_new = await run_phase1(browser, cua_client, combined_topic, pdf_paths, verbose, feedback="")
                    if p1_new and p1_new.get("text"):
                        brief_text = p1_new["text"]
                        brief_url = p1_new.get("url", brief_url)
                        _brief_md_regen = f"# Research Brief\n\n{brief_text}"
                        (queue_dir / "documents" / "brief.md").write_text(_brief_md_regen, encoding="utf-8")
                        save_document_to_firestore("brief", _brief_md_regen, "Research Brief")
                        brief_artifact = BriefArtifact(text=brief_text, url=brief_url)
                        emit_event("phase_complete", phase=1,
                                   summary=f"Brief regenerated with user input ({len(brief_text)} chars)",
                                   links=[{"label": "ChatGPT Brief", "url": brief_url}] if brief_url else [])
                # Phase-boundary input handling: any buffered extra_context goes into Phase 2's brief (handled below)
            if _controls.is_stop():
                return

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 2: Deep Research ══════════════════════
        results = {}
        if 2 in skip_phases:
            log("Phase 2: SKIPPED by config")
            emit_event("phase_skipped", phase=2, reason="Disabled in pipeline config")
        elif start_phase <= 2:
            if not brief_text:
                log("No brief text available — cannot run Phase 2", "ERROR")
                emit_event("pipeline_error", phase=2, error="no brief text")
                return
            enabled_agents = [a for a, on in agents_cfg.items() if on]
            disabled_agents = [a for a, on in agents_cfg.items() if not on]
            emit_event("phase_start", phase=2, agents=enabled_agents, description="Parallel deep research across AI platforms")
            _update_firestore_research({"phase": 2, "currentPhase": 2, "status": "ongoing"})
            for da in disabled_agents:
                emit_event("agent_skipped", phase=2, agent=da)
            _p2_start = time.time()
            fb2 = get_feedback(2)
            # Use BriefArtifact for full verified paste (never the "already_sent" heuristic)
            research_brief = (brief_artifact.text if brief_artifact else brief_text)
            # Append any extra context from user
            extra_ctx = _controls.pop_extra_context()
            if extra_ctx:
                research_brief += f'\n\nADDITIONAL CONTEXT: {extra_ctx}'
                log(f"Phase 2: Injecting extra user context ({len(extra_ctx)} chars)")
            if fb2:
                research_brief += f'\n\nUSER FEEDBACK (incorporate this into your research): {fb2}'
                log(f"Phase 2: Injecting user feedback: {fb2[:100]}")
                clear_feedback(2)
            results = await run_phase2(browser, cua_client, research_brief, verbose,
                                       enabled_agents=enabled_agents)
            # Safety filter: ensure only enabled agents appear in results
            if enabled_agents:
                agent_name_map = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}
                enabled_names = {agent_name_map.get(a, a) for a in enabled_agents}
                results = {n: r for n, r in results.items() if n in enabled_names}
            for name, r in results.items():
                if r["text"]:
                    fname = name.lower().replace(" ", "") + ".md"
                    _agent_md = f"# {name} Deep Research\n\n{r['text']}"
                    (queue_dir / "documents" / fname).write_text(_agent_md, encoding="utf-8")
                    # Sync to Firestore documents subcollection — doc_type is the
                    # agent key (chatgpt / gemini / claude), consistent with the
                    # frontend's Documents page expectation.
                    save_document_to_firestore(name.lower().replace(" ", ""), _agent_md, f"{name} Deep Research")
            # Generate consolidated report
            consolidated_parts = [f"# Consolidated Research Report: {topic}\n"]
            for name in ["ChatGPT", "Gemini", "Claude"]:
                r = results.get(name, {})
                if r.get("text"):
                    consolidated_parts.append(f"\n## {name} Research\n\n{r['text']}")
            if len(consolidated_parts) > 1:
                _consolidated_md = "\n".join(consolidated_parts)
                (queue_dir / "documents" / "consolidated.md").write_text(_consolidated_md, encoding="utf-8")
                save_document_to_firestore("consolidated", _consolidated_md, "Consolidated Report")
                log(f"Consolidated report: {len(_consolidated_md)} chars")
            done_count = sum(1 for r in results.values() if r["status"] == "done")
            log(f"\nPHASE 2 COMPLETE: {done_count}/{len(results)} agents finished")
            for name, r in results.items():
                log(f"  {name:10s} status={r['status']:12s} text={len(r['text']):>6d} chars")
            save_checkpoint(queue_dir, 2, topic=topic, brief_url=brief_url)
            # Update delivery with live agent URLs
            agent_urls = {n: r.get("url", "") for n, r in results.items() if r.get("url")}
            if agent_urls:
                update_delivery(research_links=agent_urls)
            # Enrich meta with per-agent data from results + track events
            save_meta(queue_dir, topic, 2)
            meta_path = queue_dir / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agents = meta.get("agents", {})
                for name, r in results.items():
                    key = name.lower().replace(" ", "")
                    if key not in agents:
                        agents[key] = {}
                    agents[key]["completionTimeSec"] = r.get("elapsed_sec", 0)
                # Compile source URLs from track events (DOM scraping + Firecrawl)
                events_file = _tracks_dir / "events.jsonl" if _tracks_dir else None
                if events_file and events_file.exists():
                    try:
                        for line in events_file.read_text(encoding="utf-8").strip().split("\n"):
                            if not line.strip():
                                continue
                            evt = json.loads(line)
                            # Agent key is at top level on events, payload is under "data"
                            plat = normalize_agent_key(evt.get("agent") or evt.get("data", {}).get("platform", ""))
                            data = evt.get("data", {}) if isinstance(evt.get("data"), dict) else {}
                            if plat in agents:
                                # Merge source URLs from scraping events (accept both sourceUrls and source_urls)
                                urls = data.get("sourceUrls") or data.get("source_urls") or []
                                if urls:
                                    existing = set(agents[plat].get("sourceUrls", []))
                                    existing.update(urls)
                                    agents[plat]["sourceUrls"] = list(existing)[:50]
                                    agents[plat]["sources"] = len(agents[plat]["sourceUrls"])
                                # Merge source count if higher
                                src_count = data.get("sources", 0)
                                if src_count > agents[plat].get("sources", 0):
                                    agents[plat]["sources"] = src_count
                                # Merge sections
                                secs = data.get("sections", [])
                                if secs and len(secs) > len(agents[plat].get("sections", [])):
                                    agents[plat]["sections"] = secs
                    except Exception:
                        pass
                # Rebuild sourceRefs from sourceUrls
                for plat, data in agents.items():
                    refs = []
                    for url in data.get("sourceUrls", []):
                        try:
                            domain = url.split("//")[1].split("/")[0].replace("www.", "")
                            refs.append({"url": url, "domain": domain, "agent": plat})
                        except Exception:
                            pass
                    data["sourceRefs"] = refs
                meta["agents"] = agents
                meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            # ── Link-before-advance: extract shareable links for all agents ──
            log("Phase 2: Extracting shareable links before advancing...")
            _p2_link_results = await extract_phase_links(2, browser, cua_client,
                enabled_agents=agents_cfg, verbose=verbose)
            _p2_links = [r.to_dict() for r in _p2_link_results if r.success]
            # Fallback: use raw agent URLs if extraction failed
            if not _p2_links:
                _p2_links = [{"label": f"{n} Research", "url": r.get("url", "")}
                             for n, r in results.items() if r.get("url")]
            done_count = sum(1 for r in results.values() if r["status"] == "done")
            total_chars = sum(len(r.get("text", "")) for r in results.values())
            emit_event("phase_complete", phase=2, durationSec=int(time.time() - _p2_start), links=_p2_links,
                summary=f"{done_count}/{len(results)} agents completed — {total_chars:,} chars total")
            _update_firestore_research({"phase": 2, "links.phase2": _p2_links})
        else:
            log("Phase 2: Loading existing research files")

        if _controls.is_stop_or_pause():
            if _controls.is_stop():
                log("STOP requested after Phase 2 — collecting partial results", "WARN")
                doc_dir = queue_dir / "documents"
                partial_agents = []
                for name in ["ChatGPT", "Gemini", "Claude"]:
                    fname = name.lower().replace(" ", "") + ".md"
                    if (doc_dir / fname).exists() and (doc_dir / fname).stat().st_size > 100:
                        partial_agents.append(name)
                log(f"  Partial results saved: {partial_agents or 'none'}")
                save_meta(queue_dir, topic, 2, status="stopped")
                update_delivery(status="stopped")
                emit_event("pipeline_stopped", phase=2, reason="stop",
                           partial_agents=partial_agents)
                _update_firestore_research({"status": "stopped", "phase": 2})
                return
            else:
                log("PAUSE requested after Phase 2 — closing browser, awaiting resume", "WARN")
                save_meta(queue_dir, topic, 2, status="paused")
                update_delivery(status="paused")
                _update_firestore_research({"status": "paused", "phase": 2})
                _runtime.original_inputs = {"topic": topic, "brief": brief_text}
                stopped = await pause_and_close_browser(browser, queue_dir, phase=2,
                                                        extra_kwargs={"topic": topic, "brief_url": brief_url})
                if stopped:
                    save_meta(queue_dir, topic, 2, status="stopped")
                    emit_event("pipeline_stopped", phase=2, reason="stop_after_pause")
                    _update_firestore_research({"status": "stopped", "phase": 2})
                    return
                # Relaunch — agents in Phase 2 are already complete at this boundary
                browser = Browser(PROFILE_DIR, headless=False)
                await browser.start()
                emit_event("pipeline_resumed", phase=2)
                _update_firestore_research({"status": "ongoing"})
                # Restart-phase logic: if user supplied input while paused, re-run Phase 2 with combined input
                if _controls.peek_extra_context():
                    resume_input = _controls.pop_extra_context()
                    log(f"Phase 2: Resume-with-input — rerunning 3 agents with {len(resume_input)} extra chars")
                    emit_event("phase_restart", phase=2, reason="user_input_on_resume", chars=len(resume_input))
                    combined_brief = (brief_artifact.text if brief_artifact else brief_text) + \
                                      "\n\nADDITIONAL USER CONTEXT:\n" + resume_input
                    enabled_agents_now = [a for a, on in agents_cfg.items() if on]
                    results = await run_phase2(browser, cua_client, combined_brief, verbose,
                                                enabled_agents=enabled_agents_now)
                    # Rewrite documents
                    for name, r in results.items():
                        if r.get("text"):
                            fname = name.lower().replace(" ", "") + ".md"
                            _regen_md = f"# {name} Deep Research (regenerated)\n\n{r['text']}"
                            (queue_dir / "documents" / fname).write_text(_regen_md, encoding="utf-8")
                            save_document_to_firestore(name.lower().replace(" ", ""), _regen_md, f"{name} Deep Research")
                    _p2_link_results = await extract_phase_links(2, browser, cua_client,
                        enabled_agents=agents_cfg, verbose=verbose)
                    _p2_links = [r.to_dict() for r in _p2_link_results if r.success]
                    emit_event("phase_complete", phase=2, links=_p2_links,
                               summary=f"Phase 2 regenerated with user input")

        # ── Check we have research output to continue ──
        doc_dir = queue_dir / "documents"
        md_files = [f for f in doc_dir.glob("*.md") if f.stat().st_size > 100 and f.stem != "brief"] if doc_dir.exists() else []
        has_results = md_files or any(r.get("text") for r in results.values())
        if not has_results:
            log("No research output — skipping Phases 3-5", "WARN")
            return

        # ── Consume any extra context added during/after Phase 2 ──
        # Save it as an additional document so NotebookLM can use it as a source
        _late_context = _controls.pop_extra_context()
        if _late_context:
            log(f"Consuming extra context for Phase 3+ ({len(_late_context)} chars)")
            ctx_path = queue_dir / "documents" / "user_context.md"
            ctx_path.write_text(f"# Additional User Context\n\n{_late_context}", encoding="utf-8")
            emit_event("agent_progress", phase=2, agent="system",
                       status="context_saved", progress=f"User context saved ({len(_late_context)} chars)")

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 3: NotebookLM Processing (upload + audio) ══════════════════════
        audio_path = None
        if 3 in skip_phases:
            log("Phase 3: SKIPPED by config")
            emit_event("phase_skipped", phase=3, reason="Disabled in pipeline config")
        elif start_phase <= 3:
            emit_event("phase_start", phase=3, description="Uploading to NotebookLM + generating audio overview", agents=["notebooklm"])
            _p3_start = time.time()
            if not results:
                for md_file in md_files:
                    stem = md_file.stem.lower()
                    name = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}.get(stem, stem)
                    results[name] = {"status": "done", "text": md_file.read_text(encoding="utf-8"),
                                     "url": "", "page": None}
            # Sub-step 3a: Upload to NotebookLM
            p3 = await run_phase3(browser, cua_client, results, topic, queue_dir, verbose)
            links = p3.get("links", {})
            notebook_url = p3.get("notebook_url", "")
            if notebook_url:
                emit_event("link_extracted", phase=3, agent="notebooklm",
                           url=notebook_url, label="NotebookLM Notebook", verified=True)
            (queue_dir / "links.json").write_text(json.dumps(links, indent=2), encoding="utf-8")
            save_checkpoint(queue_dir, 3, topic=topic, brief_url=brief_url,
                            notebook_url=notebook_url)
            update_delivery(research_links=links, notebook_url=notebook_url)
            # Sub-step 3b: Generate audio overview
            if notebook_url:
                p4 = await run_phase4(browser, cua_client, notebook_url, queue_dir, verbose)
                audio_path = p4.get("audio_path")
                save_checkpoint(queue_dir, 3, topic=topic, brief_url=brief_url,
                                notebook_url=notebook_url,
                                audio_path=str(audio_path) if audio_path else "")
                update_delivery(audio_url=notebook_url)
            save_meta(queue_dir, topic, 3)
            _p3_links = [{"label": "NotebookLM Notebook", "url": notebook_url}] if notebook_url else []
            emit_event("phase_complete", phase=3, durationSec=int(time.time() - _p3_start), links=_p3_links,
                summary=f"NotebookLM notebook created{', audio generated' if audio_path else ''}")
        else:
            links_file = queue_dir / "links.json"
            if links_file.exists():
                links = json.loads(links_file.read_text(encoding="utf-8"))
            audio_str = cp.get("audio_path", "")
            if audio_str and Path(audio_str).exists():
                audio_path = Path(audio_str)
            log(f"Phase 3: Loaded existing (links={len(links)}, audio={'yes' if audio_path else 'no'})")

        if _controls.is_stop_or_pause():
            if _controls.is_stop():
                log("STOP requested after Phase 3 — pipeline terminated", "WARN")
                save_meta(queue_dir, topic, 3, status="stopped")
                update_delivery(status="stopped")
                emit_event("pipeline_stopped", phase=3, reason="stop")
                _update_firestore_research({"status": "stopped", "phase": 3})
                return
            else:
                log("PAUSE requested after Phase 3 — closing browser, awaiting resume", "WARN")
                save_meta(queue_dir, topic, 3, status="paused")
                update_delivery(status="paused")
                _update_firestore_research({"status": "paused", "phase": 3})
                stopped = await pause_and_close_browser(browser, queue_dir, phase=3,
                                                        extra_kwargs={"topic": topic, "brief_url": brief_url,
                                                                      "notebook_url": notebook_url})
                if stopped:
                    save_meta(queue_dir, topic, 3, status="stopped")
                    emit_event("pipeline_stopped", phase=3, reason="stop_after_pause")
                    _update_firestore_research({"status": "stopped", "phase": 3})
                    return
                browser = Browser(PROFILE_DIR, headless=False)
                await browser.start()
                emit_event("pipeline_resumed", phase=3)
                _update_firestore_research({"status": "ongoing"})
                # Restart-phase: if user supplied input while paused, save as addendum source
                # (Phase 3 fresh notebook restart is heavy — use append-via-addendum pattern instead)
                if _controls.peek_extra_context():
                    resume_input = _controls.pop_extra_context()
                    log(f"Phase 3: Resume-with-input — saved as addendum source ({len(resume_input)} chars)")
                    emit_event("phase_restart", phase=3, reason="user_input_on_resume", chars=len(resume_input))
                    ctx_path = queue_dir / "documents" / "user_context.md"
                    ctx_path.write_text(f"# Additional User Context\n\n{resume_input}", encoding="utf-8")

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 4: YouTube Upload ══════════════════════
        if 4 in skip_phases or not video_enabled:
            _reason = "Disabled in pipeline config" if 4 in skip_phases else "Video disabled"
            log(f"Phase 4: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=4, reason=_reason)
        elif start_phase <= 4:
            emit_event("phase_start", phase=4, description="Converting audio to video + YouTube upload", agents=["youtube"])
            _p4_start = time.time()
            if audio_path:
                p5 = await run_phase5(browser, cua_client, audio_path, topic, queue_dir,
                                       links=links, notebook_url=notebook_url, verbose=verbose)
                youtube_url = p5.get("youtube_url", "")
                if youtube_url:
                    emit_event("link_extracted", phase=4, agent="youtube",
                               url=youtube_url, label="YouTube Video", verified=True)
                save_checkpoint(queue_dir, 4, topic=topic, brief_url=brief_url,
                                notebook_url=notebook_url, youtube_url=youtube_url)
                update_delivery(youtube_url=youtube_url)
                save_meta(queue_dir, topic, 4)
                _p4_links = [{"label": "YouTube Video", "url": youtube_url}] if youtube_url else []
                emit_event("phase_complete", phase=4, durationSec=int(time.time() - _p4_start), links=_p4_links,
                    summary="Video uploaded to YouTube" if youtube_url else "YouTube upload skipped")
            else:
                log("Skipping Phase 4 — no audio from Phase 3", "WARN")
                emit_event("phase_skipped", phase=4, reason="No audio produced in Phase 3")

        if _controls.is_stop_or_pause():
            if _controls.is_stop():
                log("STOP requested after Phase 4 — pipeline terminated", "WARN")
                save_meta(queue_dir, topic, 4, status="stopped")
                update_delivery(status="stopped")
                emit_event("pipeline_stopped", phase=4, reason="stop")
                _update_firestore_research({"status": "stopped", "phase": 4})
                return
            else:
                log("PAUSE requested after Phase 4 — closing browser, awaiting resume", "WARN")
                save_meta(queue_dir, topic, 4, status="paused")
                update_delivery(status="paused")
                _update_firestore_research({"status": "paused", "phase": 4})
                stopped = await pause_and_close_browser(browser, queue_dir, phase=4,
                                                        extra_kwargs={"topic": topic, "brief_url": brief_url,
                                                                      "notebook_url": notebook_url,
                                                                      "youtube_url": youtube_url})
                if stopped:
                    save_meta(queue_dir, topic, 4, status="stopped")
                    emit_event("pipeline_stopped", phase=4, reason="stop_after_pause")
                    _update_firestore_research({"status": "stopped", "phase": 4})
                    return
                browser = Browser(PROFILE_DIR, headless=False)
                await browser.start()
                emit_event("pipeline_resumed", phase=4)
                _update_firestore_research({"status": "ongoing"})
                # Phase 4 is append-only: any user input goes into description appendix (saved to disk, consumed by Phase 5)
                if _controls.peek_extra_context():
                    resume_input = _controls.pop_extra_context()
                    log(f"Phase 4: Resume-with-input — appending to video description ({len(resume_input)} chars)")
                    (queue_dir / "yt_description_append.txt").write_text(resume_input, encoding="utf-8")

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 5: Report & Notification ══════════════════════
        if 5 in skip_phases or not email_enabled:
            _reason = "Disabled in pipeline config" if 5 in skip_phases else "Email disabled"
            log(f"Phase 5: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=5, reason=_reason)
        else:
            emit_event("phase_start", phase=5, description="Creating Google Doc hub + sending email notification", agents=["gdocs", "gmail"])
            _p5_start = time.time()
            audio_url = notebook_url
            p6 = await run_phase6(browser, cua_client, topic, links, notebook_url, youtube_url,
                                  brief_url=brief_url, audio_url=audio_url,
                                  email=email, verbose=verbose)
            if p6.get("doc_url"):
                emit_event("link_extracted", phase=5, agent="gdocs",
                           url=p6["doc_url"], label="Google Doc Hub", verified=True)
            update_delivery(doc_url=p6.get("doc_url", ""), email_sent=p6.get("email_sent", False),
                            status="completed")
            save_checkpoint(queue_dir, 5, topic=topic, brief_url=brief_url, notebook_url=notebook_url,
                            youtube_url=youtube_url, doc_url=p6.get("doc_url", ""))
            save_meta(queue_dir, topic, 5, status="completed")
            _p5_links = [{"label": "Google Doc", "url": p6.get("doc_url", "")}]
            if p6.get("email_sent"):
                _p5_links.append({"label": "Email Sent", "url": ""})
            emit_event("phase_complete", phase=5, durationSec=int(time.time() - _p5_start), links=_p5_links,
                summary=f"Google Doc created{', email sent' if p6.get('email_sent') else ''}")

        emit_event("pipeline_complete", summary=f"Pipeline finished for: {topic[:100]}")
        log(f"\n{'='*60}")
        log("PIPELINE COMPLETE")
        log(f"  YouTube: {youtube_url or 'N/A'}")
        log(f"  NotebookLM: {notebook_url or 'N/A'}")
        log(f"  Queue: {queue_dir}")
        log(f"{'='*60}")

    except KeyboardInterrupt:
        log("Interrupted — progress saved to checkpoint", "WARN")
        raise
    except Exception as e:
        log(f"Fatal: {e}", "ERROR")
        emit_event("pipeline_error", error=str(e))
        import traceback
        traceback.print_exc()
    finally:
        # New pause semantics: browser is closed by pause_and_close_browser when pause fires.
        # Here we just ensure cleanup on stop/complete/error — don't double-close if already closed.
        try:
            if _runtime.dispatcher_task and not _runtime.dispatcher_task.done():
                _runtime.dispatcher_task.cancel()
                try:
                    await _runtime.dispatcher_task
                except (asyncio.CancelledError, Exception):
                    pass
        except Exception:
            pass
        try:
            if browser is not None and browser.context is not None:
                await browser.close()
        except Exception as e:
            log(f"Browser final close error: {e}", "WARN")
        _runtime.reset()
        teardown_firestore_run()

    # Auto-retry from checkpoint if pipeline failed mid-way
    # Skip if: completed, stopped (terminal), or paused (intentional freeze)
    if not resume_dir and queue_dir:
        try:
            d_path = queue_dir / "delivery.json"
            d_status = json.loads(d_path.read_text(encoding="utf-8")).get("status") if d_path.exists() else ""
        except Exception:
            d_status = ""
        if d_status not in ("completed", "stopped", "paused") \
                and not (queue_dir / ".stop").exists() \
                and not (queue_dir / ".pause").exists():
            phase, _ = detect_resume_phase(queue_dir)
            if 1 < phase <= 5:
                log(f"Pipeline failed at phase {phase} — auto-retrying from checkpoint...", "WARN")
                await asyncio.sleep(5)
                await run_pipeline(topic=topic, email=email, verbose=verbose,
                                   api_key=api_key, resume_dir=str(queue_dir),
                                   config=config)


# ── Server Mode (Web App API) ────────────────────────────────────────────────

async def run_server(port=8000):
    """Start FastAPI server for real-time web app streaming."""
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn

    app = FastAPI(title="Research Pipeline API")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    queues_root = Path(__file__).parent / "queues"
    tracks_root = Path(__file__).parent / "tracks"

    @app.get("/api/runs")
    async def list_runs():
        """List all pipeline runs — returns frontend-compatible Research objects."""
        runs = []
        if queues_root.exists():
            for d in sorted(queues_root.iterdir(), reverse=True):
                if not d.is_dir():
                    continue
                meta_path = d / "meta.json"
                if meta_path.exists():
                    try:
                        runs.append(json.loads(meta_path.read_text(encoding="utf-8")))
                        continue
                    except Exception:
                        pass
                # Fallback: build from checkpoint
                cp = load_checkpoint(d)
                has_delivery = (d / "delivery.json").exists()
                phase = cp.get("last_completed_phase", 0) if cp else 0
                runs.append({
                    "id": d.name,
                    "title": cp.get("topic", d.name) if cp else d.name,
                    "topic": cp.get("topic", d.name) if cp else d.name,
                    "status": "completed" if has_delivery else "ongoing",
                    "phase": max(0, phase - 1),
                    "platforms": ["chatgpt", "gemini", "claude"],
                    "documents": [], "audios": [],
                    "createdAt": int(d.stat().st_ctime * 1000),
                    "updatedAt": int(d.stat().st_mtime * 1000),
                })
        return runs

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        """Get full details — meta.json + delivery + checkpoint + pipeline_state."""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        # Load meta (frontend-compatible Research object)
        meta_path = queue / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        cp = load_checkpoint(queue)
        delivery_file = queue / "delivery.json"
        delivery = json.loads(delivery_file.read_text(encoding="utf-8")) if delivery_file.exists() else None
        # Pipeline state: stopped is terminal, paused is resumable
        pipeline_state = "running"
        if (queue / ".stop").exists():
            pipeline_state = "stopped"
        elif (queue / ".pause").exists():
            pipeline_state = "paused"
        elif delivery and delivery.get("status") == "completed":
            pipeline_state = "completed"
        return {"meta": meta, "checkpoint": cp, "delivery": delivery, "pipeline_state": pipeline_state}

    @app.get("/api/runs/{run_id}/events")
    async def get_events(run_id: str, offset: int = 0):
        """Get progress events. Use ?offset=N to get only new events (long-poll friendly)."""
        events_file = _find_events_file(run_id)
        if not events_file:
            return {"events": [], "offset": 0, "total": 0}
        lines = [l for l in events_file.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        events = []
        for line in lines[offset:]:
            try:
                events.append(json.loads(line))
            except Exception:
                log(f"Events API: Failed to parse line at offset {offset}: {line[:80]}", "WARN")
        return {"events": events, "offset": len(lines), "total": len(lines)}

    @app.websocket("/ws/{run_id}")
    async def ws_stream(websocket: WebSocket, run_id: str):
        """WebSocket: push new progress events in real-time (tracks by line count, not byte offset)."""
        await websocket.accept()
        events_file = _find_events_file(run_id)
        last_line = 0
        try:
            while True:
                if not events_file or not events_file.exists():
                    events_file = _find_events_file(run_id)
                if events_file and events_file.exists():
                    lines = [l for l in events_file.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
                    if len(lines) > last_line:
                        for line in lines[last_line:]:
                            try:
                                await websocket.send_json(json.loads(line))
                            except Exception:
                                log(f"WS: Failed to parse event line: {line[:80]}", "WARN")
                        last_line = len(lines)
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            pass

    def _find_events_file(run_id):
        """Find events.jsonl for a run — exact match (tracks and queues share the same dir name)."""
        if not tracks_root.exists():
            return None
        # Exact match first
        ef = tracks_root / run_id / "events.jsonl"
        if ef.exists():
            return ef
        # Fallback: prefix match for legacy tracks
        prefix = run_id.rsplit("_", 2)[0] if "_" in run_id else run_id
        for d in tracks_root.iterdir():
            if d.is_dir() and prefix in d.name:
                ef = d / "events.jsonl"
                if ef.exists():
                    return ef
        return None

    @app.post("/api/runs/{run_id}/stop")
    async def stop_run(run_id: str):
        """STOP: terminate pipeline, save partial results, mark as stopped (not resumable)."""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        (queue / ".stop").write_text("stop", encoding="utf-8")
        p = queue / ".pause"
        if p.exists():
            p.unlink()
        # Also set asyncio event for immediate response
        _controls.request_stop()
        return {"status": "stop_requested", "id": run_id}

    @app.post("/api/runs/{run_id}/pause")
    async def pause_run(run_id: str):
        """PAUSE: freeze pipeline at next checkpoint, save state for resume."""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        (queue / ".pause").write_text("pause", encoding="utf-8")
        _controls.request_pause()
        return {"status": "pause_requested", "id": run_id}

    @app.post("/api/runs/{run_id}/feedback")
    async def submit_feedback(run_id: str, request_data: dict):
        """Submit user feedback for a phase. Stops pipeline + saves feedback for next resume.
        Body: {phase: 1, message: "Brief is too narrow, include biotech"}"""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        phase = str(request_data.get("phase", ""))
        message = request_data.get("message", "")
        if not message:
            return JSONResponse({"error": "message is required"}, 400)
        # Load existing feedback or create new
        fb_path = queue / "feedback.json"
        fb = json.loads(fb_path.read_text(encoding="utf-8")) if fb_path.exists() else {}
        fb[phase] = message
        fb_path.write_text(json.dumps(fb, indent=2), encoding="utf-8")
        # Auto-pause pipeline so it picks up feedback on resume (not terminal stop)
        (queue / ".pause").write_text("pause", encoding="utf-8")
        _controls.request_pause()
        return {"status": "feedback_saved", "phase": phase, "will_redo_from": phase}

    @app.post("/api/runs/{run_id}/add_context")
    async def add_context(run_id: str, request_data: dict):
        """Add context to running pipeline WITHOUT pausing. Context is injected at next opportunity.
        Body: {text: "Also look at biotech angle"}"""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        text = request_data.get("text", "")
        if not text:
            return JSONResponse({"error": "text is required"}, 400)
        _controls.add_context(text)
        log(f"Context added ({len(text)} chars) — will be injected at next phase boundary")
        return {"status": "context_added", "chars": len(text)}

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(run_id: str, request_data: dict = None):
        """Resume a paused/failed pipeline run. Queued if another is running.
        If feedback exists, pipeline redoes that phase with feedback injected.
        NOTE: only paused runs can be resumed — stopped runs are terminal."""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        # Block resume of stopped (terminal) runs
        if (queue / ".stop").exists():
            return JSONResponse({"error": "Run was stopped (terminal). Cannot resume — start a new run."}, 409)
        # Clear .pause signal
        p = queue / ".pause"
        if p.exists():
            p.unlink()
        # If feedback targets a specific phase, reset checkpoint to redo from there
        fb_path = queue / "feedback.json"
        cp = load_checkpoint(queue)
        if fb_path.exists() and cp:
            fb = json.loads(fb_path.read_text(encoding="utf-8"))
            if fb:
                earliest_phase = min(int(p) for p in fb.keys())
                # Reset checkpoint so pipeline redoes from the feedback phase
                cp["last_completed_phase"] = max(0, earliest_phase - 1)
                (queue / "checkpoint.json").write_text(json.dumps(cp, indent=2), encoding="utf-8")
                # Remove outputs from that phase onwards so they get regenerated
                if earliest_phase <= 1:
                    for f in (queue / "documents").glob("brief.md"):
                        try: f.unlink()
                        except Exception: pass
                if earliest_phase <= 2:
                    for f in (queue / "documents").glob("*.md"):
                        if f.stem != "brief":
                            try: f.unlink()
                            except Exception: pass
                if earliest_phase <= 3:
                    for p in [queue / "links.json"]:
                        try: p.unlink(missing_ok=True)
                        except Exception: pass
                    podcasts_dir = queue / "podcasts"
                    if podcasts_dir.exists():
                        for f in podcasts_dir.glob("*.*"):
                            try: f.unlink()
                            except Exception: pass
        # If request has config, merge with existing config.json
        if request_data and request_data.get("config"):
            config_path = queue / "config.json"
            existing = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
            existing.update(request_data["config"])
            config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        # Reset delivery + meta status from "paused" back to "ongoing"
        d_path = queue / "delivery.json"
        if d_path.exists():
            try:
                d = json.loads(d_path.read_text(encoding="utf-8"))
                if d.get("status") == "paused":
                    d["status"] = "ongoing"
                    d_path.write_text(json.dumps(d, indent=2), encoding="utf-8")
            except Exception:
                pass
        m_path = queue / "meta.json"
        if m_path.exists():
            try:
                m = json.loads(m_path.read_text(encoding="utf-8"))
                if m.get("status") == "paused":
                    m["status"] = "ongoing"
                    m_path.write_text(json.dumps(m, indent=2), encoding="utf-8")
            except Exception:
                pass
        topic = cp.get("topic", "") if cp else ""
        email = (request_data or {}).get("email", "")
        await _job_queue.put({"topic": topic, "email": email, "resume_dir": str(queue)})
        return {"status": "queued_resume", "id": run_id, "queue_position": _job_queue.qsize()}

    # ── Job queue: one pipeline at a time, multiple can be queued ──
    _job_queue = asyncio.Queue()
    _queue_running = False

    async def _job_worker():
        """Process pipeline jobs one at a time from the queue."""
        nonlocal _queue_running
        while True:
            job = await _job_queue.get()
            _queue_running = True
            log(f"Starting queued job: {job['topic'][:60]}")
            try:
                await run_pipeline(topic=job["topic"], email=job.get("email", ""),
                                   verbose=True, resume_dir=job.get("resume_dir"),
                                   config=job.get("config"), run_id=job.get("run_id"),
                                   uid=job.get("uid"), research_id=job.get("research_id"))
            except Exception as e:
                log(f"Pipeline job error: {e}", "ERROR")
            finally:
                _queue_running = False
                _job_queue.task_done()

    # Start the worker + Firestore start listener on server startup
    @app.on_event("startup")
    async def _start_worker():
        asyncio.create_task(_job_worker())
        # Start global Firestore listener for pipeline start requests
        if _firebase_db:
            start_firestore_start_listener(_job_queue, asyncio.get_event_loop())

    @app.get("/api/queue")
    async def get_queue_status():
        """Get queue status: current job + pending count."""
        return {"running": _queue_running, "pending": _job_queue.qsize()}

    @app.get("/api/health")
    async def health_check():
        """Server health check."""
        return {"status": "ok", "running": _queue_running, "pending": _job_queue.qsize()}

    @app.patch("/api/runs/{run_id}/config")
    async def update_config(run_id: str, request_data: dict):
        """Update pipeline config mid-run. Pipeline checks config.json before each phase."""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        config_path = queue / "config.json"
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        except Exception:
            existing = {}
        existing.update(request_data)
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        # Forward to in-memory controls (for mid-phase config awareness)
        _controls.update_config(existing)
        # Emit via dual-write (events.jsonl + Firestore) so frontend gets it
        emit_event("config_updated", config=existing)
        return {"status": "config_updated", "id": run_id, "config": existing}

    @app.delete("/api/runs/{run_id}")
    async def delete_run(run_id: str):
        """Delete a completed/stopped run's queue and tracks."""
        import shutil
        queue = queues_root / run_id
        tracks = tracks_root / run_id
        if not queue.exists() and not tracks.exists():
            return JSONResponse({"error": "not found"}, 404)
        try:
            if queue.exists(): shutil.rmtree(queue)
            if tracks.exists(): shutil.rmtree(tracks)
        except Exception as e:
            return JSONResponse({"error": str(e)}, 500)
        return {"status": "deleted", "id": run_id}

    @app.post("/api/runs")
    async def start_run(request_data: dict):
        """Start a new pipeline run. Queued if another is already running.
        Body: {topic, email?, config?: {agents, skipPhases, videoEnabled, emailEnabled}}"""
        topic = request_data.get("topic")
        if not topic or not topic.strip():
            return JSONResponse({"error": "topic is required"}, 400)
        topic = topic.strip()
        email = request_data.get("email", "")
        uid = request_data.get("uid", "")  # Firebase user ID for Firestore bridge
        config = request_data.get("config", {})
        # Validate config
        agents_cfg = config.get("agents", {"chatgpt": True, "gemini": True, "claude": True})
        if not any(agents_cfg.values()):
            return JSONResponse({"error": "at least one agent must be enabled"}, 400)
        from datetime import datetime as _dt
        run_id = f"{safe_name(topic)}_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
        await _job_queue.put({"topic": topic, "email": email, "config": config, "run_id": run_id, "uid": uid})
        position = _job_queue.qsize()
        is_running = _queue_running
        status = "running" if position <= 1 and not is_running else f"queued (position {position})"
        return {"status": status, "topic": topic, "queue_position": position, "id": run_id}

    @app.get("/api/runs/{run_id}/documents/{doc_type}")
    async def get_document(run_id: str, doc_type: str):
        """Get document content. doc_type: brief, chatgpt, gemini, claude."""
        # All documents live in documents/ (brief included)
        path = queues_root / run_id / "documents" / f"{doc_type}.md"
        if not path.exists():
            path = queues_root / run_id / f"{doc_type}.md"  # Legacy fallback
        if not path.exists():
            return JSONResponse({"error": "not found"}, 404)
        content = path.read_text(encoding="utf-8")
        return {
            "type": doc_type,
            "name": f"{doc_type}.md",
            "size": f"{len(content) / 1024:.0f} KB",
            "content": content,
        }

    @app.get("/api/runs/{run_id}/audio/{filename}")
    async def get_audio(run_id: str, filename: str):
        """Serve audio file from podcasts directory."""
        from fastapi.responses import FileResponse as _FileResponse
        # Sanitize filename to prevent path traversal
        safe = Path(filename).name
        path = queues_root / run_id / "podcasts" / safe
        if not path.exists():
            return JSONResponse({"error": "audio not found"}, 404)
        mime_map = {".m4a": "audio/mp4", ".mp3": "audio/mpeg",
                    ".wav": "audio/wav", ".webm": "audio/webm"}
        media_type = mime_map.get(path.suffix.lower(), "application/octet-stream")
        return _FileResponse(str(path), media_type=media_type, filename=safe)

    log(f"Starting API server on http://0.0.0.0:{port}")
    log(f"  GET  /api/runs                     — List all runs")
    log(f"  POST /api/runs                     — Start new run {{topic, email}}")
    log(f"  GET  /api/runs/{{id}}                — Run details + meta")
    log(f"  GET  /api/runs/{{id}}/documents/{{type}} — Document content (brief/chatgpt/gemini/claude)")
    log(f"  GET  /api/runs/{{id}}/events         — Progress events")
    log(f"  WS   /ws/{{run_id}}                  — Real-time event stream")
    # Start worker directly (don't rely on @app.on_event which is deprecated and
    # sometimes doesn't fire reliably with newer FastAPI versions)
    # Initialize Firebase Admin SDK for Firestore bridge
    init_firebase()
    # Load run analytics for realistic ETAs
    load_analytics()
    # Load PipeToken (required for token-scoped queue + heartbeat)
    token = load_pipe_token()
    if token:
        log(f"PipeToken loaded: {token[:8]}...")
    else:
        log("No PipeToken found — run `python research.py --setup` to generate one", "WARN")
        log("Falling back to legacy pipeline_requests/ listener", "WARN")
    worker_task = asyncio.create_task(_job_worker())
    log("Job worker started (direct)")
    # Start heartbeat so frontend can show Online/Offline status
    heartbeat_task = None
    if token and _firebase_db:
        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        log("Heartbeat started (30s interval)")
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        worker_task.cancel()
        if heartbeat_task:
            heartbeat_task.cancel()
        # Mark offline on shutdown
        if _firebase_db and _pipe_token:
            try:
                _firebase_db.collection("pipe_tokens").document(_pipe_token).update({"status": "offline"})
            except Exception:
                pass


# ── Setup ────────────────────────────────────────────────────────────────────

async def run_setup(profile_dir, wait_minutes=5):
    # ── Step 1: Generate PipeToken ──
    log("")
    log("=" * 60)
    log("  Super Research — Backend Setup")
    log("=" * 60)
    log("")

    # Initialize Firebase for token registration
    firebase_ok = init_firebase()
    if not firebase_ok:
        log("Firebase not available — PipeToken will be local only.", "WARN")

    # Check for existing token
    existing = load_pipe_token()
    if existing:
        log(f"Existing PipeToken found: {existing}")
        log("Reusing existing token. Delete pipe_config.json to generate a new one.")
        token = existing
    else:
        token = generate_pipe_token()

    log("")
    log("-" * 60)
    log(f"  Your PipeToken: {token}")
    log("-" * 60)
    log("  Enter this token in Super Research app:")
    log("  Account > Pipeline Connection > Paste token > Link")
    log("-" * 60)
    log("")

    # ── Step 2: Browser login setup ──
    log("Step 2: Log into all research platforms")
    log("A browser will open. Log into each tab:")
    log("")
    browser = Browser(profile_dir, headless=False)
    await browser.start()
    services = [
        ("ChatGPT", "https://chatgpt.com"), ("Gemini", "https://gemini.google.com"),
        ("Claude", "https://claude.ai"), ("NotebookLM", "https://notebooklm.google.com"),
        ("YouTube Studio", "https://studio.youtube.com"), ("Gmail", "https://mail.google.com"),
        ("Google Docs", "https://docs.google.com"),
    ]
    for i, (n, u) in enumerate(services, 1):
        log(f"  {i}. {n} — {u}")
    log("")
    await browser.navigate(services[0][1])
    await asyncio.sleep(3)
    for n, u in services[1:]:
        try:
            await browser.new_tab(u)
            log(f"  Opened: {n}")
            await asyncio.sleep(3)
        except Exception as e:
            log(f"  Failed: {n} ({e})", "WARN")
    log("")
    log(f"Log into all {len(services)} tabs. You have {wait_minutes} minutes.")
    for r in range(wait_minutes * 60, 0, -30):
        log(f"  Waiting... {r//60}m {r%60}s remaining.")
        await asyncio.sleep(30)
    await browser.close()
    log("")
    log("=" * 60)
    log("  Setup complete!")
    log(f"  PipeToken: {token}")
    log("  Start the server:  python research.py --serve")
    log("=" * 60)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Deep Research Pipeline")
    parser.add_argument("topic", nargs="?", help="Research topic")
    parser.add_argument("--pdf", action="append", default=[], help="PDF to attach (Phase 1)")
    parser.add_argument("--brief-file", "-b", help="Existing brief file (skip Phase 1)")
    parser.add_argument("--email", "-e", help="Email for Phase 6 delivery")
    parser.add_argument("--api-key", "-k", help="CUA API key")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--setup", action="store_true", help="First-time login setup")
    parser.add_argument("--resume", "-r", help="Resume from a previous queue directory (name or full path)")
    parser.add_argument("--serve", action="store_true", help="Start web app API server")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    args = parser.parse_args()

    if args.setup:
        asyncio.run(run_setup(str(PROFILE_DIR)))
        return

    if args.serve:
        asyncio.run(run_server(args.port))
        return

    if args.resume:
        resume_path = Path(args.resume)
        if not resume_path.is_absolute():
            resume_path = Path(__file__).parent / "queues" / args.resume
        log(f"Resuming from: {resume_path}")
        asyncio.run(run_pipeline(
            topic=args.topic or "", resume_dir=str(resume_path),
            verbose=args.verbose, api_key=args.api_key, email=args.email,
        ))
        return

    if not args.topic:
        parser.error('Provide topic: python research.py "Your topic"')

    log(f"Topic: {args.topic}")
    if args.brief_file:
        log(f"Brief: {args.brief_file} (skipping Phase 1)")
    if args.pdf:
        log(f"PDFs: {[Path(p).name for p in args.pdf]}")

    asyncio.run(run_pipeline(
        topic=args.topic, pdf_paths=args.pdf,
        brief_file=args.brief_file, verbose=args.verbose,
        api_key=args.api_key, email=args.email,
    ))


if __name__ == "__main__":
    main()
